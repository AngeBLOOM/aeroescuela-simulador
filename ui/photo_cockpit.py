"""Cabina fotográfica: una foto de la cabina (generada con IA) con las zonas verde croma
(ventanas, relojes y pantallas) recortadas. Detrás se ve el mundo 3D y en cada hueco
se dibuja el instrumento vivo correspondiente.

Archivo buscado en assets/: cabina_<avión>.png|jpg (p. ej. cabina_c172.jpg). El PA-28R usa
la del C172 si no tiene la suya.
"""
import math
import os

import numpy as np
import pygame

from . import assets

FALLBACK = {"pa28r": "c172", "c152": "c172", "pa28w": "pa28r", "sr20": "da40"}


class _NullUI:
    """Las pantallas escaladas no reciben clics (las coordenadas no coinciden)."""
    tooltip = None

    def button(self, *a, **k):
        return False

    def cockpit_button(self, *a, **k):
        return False

    def scroll(self, *a, **k):
        return 0

    def hover(self, *a, **k):
        return False

    def hit(self, *a, **k):
        return False


def find_photo(aircraft_id):
    chain = [aircraft_id]
    while chain[-1] in FALLBACK and len(chain) < 4:
        chain.append(FALLBACK[chain[-1]])
    for aid in chain:
        if not aid:
            continue
        for ext in ("png", "jpg", "jpeg", "webp"):
            p = assets.path(f"cabina_{aid}.{ext}")
            if os.path.exists(p):
                return p
    return None


def _components(mask):
    """Etiquetado de regiones conexas (4-vecinos) con numpy + unión-búsqueda por filas."""
    h, w = mask.shape
    labels = np.zeros((h, w), np.int32)
    parent = [0]

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    nxt = 1
    for y in range(h):
        row = mask[y]
        if not row.any():
            continue
        xs = np.flatnonzero(row)
        # tramos contiguos de la fila
        breaks = np.flatnonzero(np.diff(xs) > 1)
        starts = np.concatenate([[xs[0]], xs[breaks + 1]])
        ends = np.concatenate([xs[breaks], [xs[-1]]])
        for a, b in zip(starts, ends):
            above = labels[y - 1, a:b + 1] if y > 0 else np.zeros(0, np.int32)
            ids = np.unique(above[above > 0])
            if len(ids) == 0:
                parent.append(nxt)
                lab = nxt
                nxt += 1
            else:
                roots = sorted({find(int(i)) for i in ids})
                lab = roots[0]
                for r in roots[1:]:
                    parent[r] = lab
            labels[y, a:b + 1] = lab
    roots = np.array([find(i) for i in range(nxt)], np.int32)
    return roots[labels]


def clamp_(v, lo, hi):
    return max(lo, min(hi, v))


class PhotoCockpit:
    def __init__(self, path, work_w=480):
        self._bufs = {}
        img = pygame.image.load(path)
        self.src_size = img.get_size()
        arr = pygame.surfarray.array3d(img).transpose(1, 0, 2).astype(np.float32)
        r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
        # verde croma: verde dominante y saturado
        green = (g > 110) & (g > r * 1.35) & (g > b * 1.35)
        alpha = np.where(green, 0, 255).astype(np.uint8)
        # suavizar el borde del recorte y quitar el reflejo verde de los bordes
        edge = np.zeros_like(green)
        edge[1:-1, 1:-1] = green[1:-1, 1:-1] & ~(green[:-2, 1:-1] & green[2:, 1:-1] & green[1:-1, :-2] & green[1:-1, 2:])
        spill = (g > r * 1.1) & (g > b * 1.1) & ~green
        arr[..., 1] = np.where(spill, np.minimum(g, (r + b) / 2 + 10), g)
        rgba = np.dstack([np.clip(arr, 0, 255).astype(np.uint8), alpha])
        surf = pygame.Surface(self.src_size, pygame.SRCALPHA)
        pygame.surfarray.pixels3d(surf)[...] = rgba[..., :3].transpose(1, 0, 2)
        pygame.surfarray.pixels_alpha(surf)[...] = rgba[..., 3].T
        self.photo = surf
        # análisis de huecos a resolución reducida
        step = max(1, self.src_size[0] // work_w)
        gm = green[::step, ::step]
        lab = _components(gm)
        H, W = gm.shape
        self.circles = []
        self.rects = []
        for lid in np.unique(lab):
            if lid == 0:
                continue
            ys, xs = np.nonzero(lab == lid)
            n = len(xs)
            if n < 30:
                continue
            x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
            bw, bh = x1 - x0 + 1, y1 - y0 + 1
            fill = n / (bw * bh)
            cy = (y0 + y1) / 2 / H
            if y0 < H * 0.08 or (bw > W * 0.45):      # ventanas / parabrisas
                continue
            if x0 == 0 or x1 >= W - 1 or y1 >= H - 1 or bw < W * 0.015:   # ventanas laterales y restos
                continue
            if 0.6 < bw / bh < 1.6 and 0.62 < fill < 0.9:
                self.circles.append(((x0 + x1) / 2 / W, cy, max(bw, bh) / 2 / W))
            elif fill > 0.6:
                self.rects.append(((x0 / W), (y0 / H), (bw / W), (bh / H)))
        self.circles.sort(key=lambda c: -c[2])
        self.rects.sort(key=lambda r: -(r[2] * r[3]))
        self.assign()

    def assign(self):
        """Asigna cada hueco a un instrumento.

        Relojes redondos: se agrupan en filas; en las dos filas principales los tres primeros
        grandes (de izquierda a derecha) son los seis básicos (ASI·AI·ALT / TC·HI·VSI) y el cuarto
        de cada fila es NAV 1 / NAV 2. Los demás huecos reciben tacómetro e indicadores de motor.
        Pantallas rectangulares: dos parecidas = PFD y MFD; una sola = radios."""
        self.slots = {}
        ar = self.src_size[0] / self.src_size[1]

        def aspect(r):
            return r[2] * ar / max(r[3], 1e-6)
        screens = [r for r in self.rects if r[2] > 0.09 and 1.0 < aspect(r) < 2.0]
        if len(screens) >= 2 and abs(screens[0][2] - screens[1][2]) < 0.08:
            a, b = sorted(screens[:2], key=lambda r: r[0])
            self.slots["pfd"], self.slots["mfd"] = a, b
            return                          # cabina de cristal: los círculos suelen ser rejillas o asas
        strips = [r for r in self.rects if r[3] < 0.07]
        radios = [r for r in self.rects if r[3] >= 0.07]
        if radios:
            self.slots["radios"] = radios[0]
        if strips:
            # una tira de avisos tapada en parte (p. ej. por el volante) se une en un solo rectángulo
            row = [r for r in strips if abs(r[1] - strips[0][1]) < 0.03]
            x0 = min(r[0] for r in row)
            y0 = min(r[1] for r in row)
            x1 = max(r[0] + r[2] for r in row)
            y1 = max(r[1] + r[3] for r in row)
            self.slots["annun"] = (x0, y0, x1 - x0, y1 - y0)
        c = list(self.circles)
        if not c:
            return
        rmax = max(t[2] for t in c)
        big = [t for t in c if t[2] >= rmax * 0.8]
        small = [t for t in c if t[2] < rmax * 0.8]
        rows = []
        for t in sorted(big, key=lambda t: t[1]):
            if rows and abs(rows[-1][-1][1] - t[1]) < 0.05:
                rows[-1].append(t)
            else:
                rows.append([t])
        rows = [sorted(r, key=lambda t: t[0]) for r in rows]
        main = [r for r in rows if len(r) >= 3]
        used = set()
        if len(main) >= 2:
            top, bot = main[0], main[1]
            # columnas presentes en las dos filas; las tres primeras son los seis básicos y la cuarta NAV
            tol = rmax * 1.2
            pairs_ = []
            for t in top:
                m = min(bot, key=lambda b: abs(b[0] - t[0]))
                if abs(m[0] - t[0]) < tol:
                    pairs_.append((t, m))
            pairs_.sort(key=lambda p: p[0][0])
            for k, (t, b) in enumerate(pairs_[:4]):
                self.slots[("asi", "ai", "alt", "cdi1")[k]] = t
                self.slots[("tc", "hi", "vsi", "cdi2")[k]] = b
                used.update((t, b))
        rest = [t for t in big + small if t not in used]
        rest.sort(key=lambda t: (-t[2], t[1]))
        names = ["tach", "fuel", "oil", "vac", "amp", "egt"]
        for name, t in zip(names, rest):
            self.slots[name] = t

    @property
    def usable(self):
        return ("asi" in self.slots and "alt" in self.slots) or ("pfd" in self.slots)

    zoom = 1.45                 # acercamiento actual (1 = foto completa)
    zoom_target = 1.45
    BASE_FOV = 72.0             # campo de visión horizontal que abarca la foto completa

    def step_zoom(self, dt):
        self.zoom += (self.zoom_target - self.zoom) * min(1.0, dt * 8.0)
        if abs(self.zoom - self.zoom_target) < 0.002:
            self.zoom = self.zoom_target

    @property
    def animating(self):
        return self.zoom != self.zoom_target

    def fov(self):
        """Campo de visión del mundo 3D para que coincida con la foto ampliada."""
        return math.degrees(2 * math.atan(math.tan(math.radians(self.BASE_FOV / 2)) / self.zoom))

    @property
    def horizon_y(self):
        """Altura (fracción de la foto) donde debe verse el horizonte en vuelo nivelado:
        un poco por encima de la parte alta del tablero."""
        ar = self.src_size[0] / self.src_size[1]
        tops = [v[1] - (v[2] * ar if len(v) == 3 else 0) for v in self.slots.values()]
        return max(0.12, (min(tops) if tops else 0.45) - 0.11)

    def layout(self, W, H):
        """Escala la foto para cubrir la ventana, apoyada abajo. Con zoom se acerca al tablero."""
        sw, sh = self.src_size
        k = max(W / sw, H / sh) * self.zoom
        pw, ph = sw * k, sh * k
        if self.zoom <= 1.0:
            return k, (W - pw) / 2, H - ph, pw, ph
        # centrar en los instrumentos
        pts = [(v[0] + (v[2] / 2 if len(v) == 4 else 0), v[1] + (v[3] / 2 if len(v) == 4 else 0)) for v in self.slots.values()]
        cx = sum(p[0] for p in pts) / len(pts) if pts else 0.5
        cy = sum(p[1] for p in pts) / len(pts) if pts else 0.6
        ox = clamp_(W / 2 - cx * pw, W - pw, 0)
        oy = clamp_(H * 0.55 - cy * ph, H - ph, 0)
        return k, ox, oy, pw, ph

    # ------------------------------------------------------------ dibujo
    def slot_rect(self, name, ox, oy, pw, ph):
        """Rectángulo de pantalla que ocupa el instrumento (con su aro)."""
        t = self.slots[name]
        if len(t) == 3:
            cx, cy, r = ox + t[0] * pw, oy + t[1] * ph, t[2] * pw * 1.02
            m = r * 1.22
            return pygame.Rect(int(cx - m), int(cy - m), int(2 * m) + 2, int(2 * m) + 2)
        x, y, w, h = t
        return pygame.Rect(int(ox + x * pw), int(oy + y * ph), int(w * pw) + 1, int(h * ph) + 1)

    def _hole_mask(self, rect, ox, oy, k):
        """Máscara (blanca, alfa = hueco de la foto) para recortar el instrumento a su hueco."""
        sw, sh = self.src_size
        x0 = (rect.x - ox) / k
        y0 = (rect.y - oy) / k
        x1 = (rect.right - ox) / k
        y1 = (rect.bottom - oy) / k
        ix0, iy0 = max(0, int(x0)), max(0, int(y0))
        ix1, iy1 = min(sw, int(math.ceil(x1))), min(sh, int(math.ceil(y1)))
        m = pygame.Surface(rect.size, pygame.SRCALPHA)
        if ix1 <= ix0 or iy1 <= iy0:
            return m
        crop = pygame.Surface((ix1 - ix0, iy1 - iy0), pygame.SRCALPHA)
        crop.fill((255, 255, 255, 255))
        pygame.surfarray.pixels_alpha(crop)[...] = 255 - self._alpha[ix0:ix1, iy0:iy1]
        dst = pygame.Rect(int((ix0 - x0) * k), int((iy0 - y0) * k), int((ix1 - ix0) * k) + 1, int((iy1 - iy0) * k) + 1)
        m.blit(pygame.transform.smoothscale(crop, dst.size), dst.topleft)
        return m

    def draw(self, surf, world, panel, ui, frame=0, paused=False):
        """Dibuja los instrumentos en sus huecos. La foto la dibuja la tarjeta gráfica aparte
        (Renderer.set_photo). Cada instrumento se guarda en su propia tesela recortada con la
        forma del hueco y se repinta en fotogramas alternos (la mitad en cada uno), así todos
        los fotogramas cuestan lo mismo y la imagen no tiembla."""
        W, H = surf.get_size()
        k, ox, oy, pw, ph = self.layout(W, H)
        key = (W, H, int(ox), int(oy), int(pw))
        if getattr(self, "_tiles_key", None) != key:
            self._tiles_key = key
            if not hasattr(self, "_alpha"):
                self._alpha = pygame.surfarray.array_alpha(self.photo)
            self._tiles = {}
            for name in self.slots:
                rect = self.slot_rect(name, ox, oy, pw, ph)
                self._tiles[name] = [rect, pygame.Surface(rect.size, pygame.SRCALPHA),
                                     self._hole_mask(rect, ox, oy, k), True]
        for i, (name, tile) in enumerate(self._tiles.items()):
            rect, tsurf, mask, fresh = tile
            if fresh or paused or (frame + i) % 2 == 0:
                tsurf.fill((0, 0, 0, 0))
                self._paint(tsurf, name, world, panel, ox - rect.x, oy - rect.y, pw, ph)
                tsurf.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
                tile[3] = False
            surf.blit(tsurf, rect.topleft)

    def _paint(self, surf, name, world, panel, ox, oy, pw, ph):
        """Pinta un instrumento; (ox, oy) es el origen de la foto en coordenadas de 'surf'."""
        g = panel.g
        ac = world.ac
        ind = world.ind
        t = self.slots[name]
        if len(t) == 3:
            p, r = (ox + t[0] * pw, oy + t[1] * ph), int(t[2] * pw * 1.02)
        else:
            rr = pygame.Rect(ox + t[0] * pw, oy + t[1] * ph, t[2] * pw, t[3] * ph)
        if name == "asi":
            g.asi(surf, p, r, ind.ias, ac.t.v)
        elif name == "ai":
            g.attitude(surf, p, r, ind.ai_roll, ind.ai_pitch, flag=ac.sys.gyro_spin < 0.5)
        elif name == "alt":
            g.altimeter(surf, p, r, ind.alt_ft, world.kollsman)
        elif name == "tc":
            g.turn_coord(surf, p, r, ind.turn_rate, ind.slip, ac.sys.electric_ok)
        elif name == "hi":
            g.heading(surf, p, r, ind.dg, world.ap.hdg_bug)
        elif name == "vsi":
            g.vsi(surf, p, r, ind.vs_fpm)
        elif name == "cdi1":
            g.cdi(surf, p, r, world.nav_source(), "GPS" if world.cdi_src == "GPS" else "NAV 1")
        elif name == "cdi2":
            if world.show_adf:
                g.adf(surf, p, r, world.adf)
            else:
                g.cdi(surf, p, r, world.nav2, "NAV 2")
        elif name == "tach":
            g.tach(surf, p, r, ac.sys.engine.rpm)
        elif name in ("fuel", "oil", "vac", "amp", "egt"):
            e = ac.sys.engine
            sysm = ac.sys
            lab, v, lo, hi, gr, fmt = {
                "fuel": ("COMB", sysm.fuel_l / max(1.0, ac.t.fuel_capacity), 0, 1, (0.15, 1), "{:.0%}"),
                "oil": ("ACEITE", e.oil_press, 0, 115, (50, 90), "{:.0f}"),
                "vac": ("VACÍO", sysm.vacuum, 0, 7, (4.5, 5.5), "{:.1f}"),
                "amp": ("VOLT", sysm.bus_volts, 20, 32, (24.5, 29.5), "{:.1f}"),
                "egt": ("EGT", e.egt, 800, 1650, (1150, 1550), "{:.0f}")}[name]
            self._mini(surf, p, r, lab, v, lo, hi, gr, fmt, panel.f)
        elif name in ("pfd", "mfd"):
            # la pantalla se dibuja a tamaño real (como en el panel 2D) y se escala al hueco
            lw = 620
            lh = int(lw * rr.h / max(rr.w, 1))
            buf = self._bufs.get(name)
            if buf is None or buf.get_size() != (lw, lh):
                buf = pygame.Surface((lw, lh), pygame.SRCALPHA)
                self._bufs[name] = buf
            buf.fill((0, 0, 0, 255))
            if name == "pfd":
                panel.glass.pfd(buf, (2, 2, lw - 4, lh - 4), world, _NullUI())
            else:
                panel.glass.mfd(buf, (2, 2, lw - 4, lh - 4), world, _NullUI())
            surf.blit(pygame.transform.smoothscale(buf, (max(1, int(rr.w)), max(1, int(rr.h)))), rr.topleft)
        elif name == "annun":
            self._annun(surf, rr, world, panel.f)
        elif name == "radios":
            self._radios(surf, rr, world, panel)

    def screen_rect(self, W, H):
        k, ox, oy, pw, ph = self.layout(W, H)
        return (ox, oy, pw, ph)

    def _annun(self, surf, rr, world, f):
        """Tira de avisos: luces del tren y alarmas (encendidas solo cuando corresponde)."""
        ac = world.ac
        sysm = ac.sys
        pygame.draw.rect(surf, (10, 10, 12), rr)
        items = []
        if ac.t.retractable:
            items.append(("TREN", (40, 220, 80) if sysm.gear_pos > 0.99 else ((230, 60, 50) if sysm.gear_pos > 0.01 else None)))
        items += [("VAC", (230, 170, 30) if sysm.gyro_spin < 0.75 else None),
                  ("ALT", (230, 170, 30) if not sysm.electric_ok else None),
                  ("ACEITE", (230, 60, 50) if sysm.engine.oil_press < 20 and sysm.engine.running else None)]
        n = len(items)
        cw = rr.w / n
        for i, (lab, col) in enumerate(items):
            c = pygame.Rect(rr.x + i * cw + 2, rr.y + 2, cw - 4, rr.h - 4)
            pygame.draw.rect(surf, col if col else (34, 34, 38), c, border_radius=2)
            size = max(7, int(min(rr.h * 0.45, cw / max(len(lab), 3) * 1.45)))
            f.blit(surf, lab, c.center, size, (10, 10, 10) if col else (90, 90, 96), bold=True, anchor="center")

    def _mini(self, surf, c, r, lab, v, lo, hi, green, fmt, f):
        """Reloj pequeño de motor: arco verde, aguja y valor."""
        pygame.draw.circle(surf, (14, 15, 17), c, r)
        pygame.draw.circle(surf, (60, 62, 66), c, r, 2)

        def ang(x):
            return math.radians(225 - 270 * (min(max(x, lo), hi) - lo) / (hi - lo))
        a0, a1 = ang(green[0]), ang(green[1])
        rr = pygame.Rect(0, 0, r * 1.6, r * 1.6)
        rr.center = c
        pygame.draw.arc(surf, (40, 190, 80), rr, min(a0, a1), max(a0, a1), max(2, int(r * 0.1)))
        a = ang(v)
        tip = (c[0] + math.cos(a) * r * 0.78, c[1] - math.sin(a) * r * 0.78)
        pygame.draw.line(surf, (240, 240, 240), c, tip, max(2, int(r * 0.07)))
        pygame.draw.circle(surf, (40, 40, 44), c, max(2, int(r * 0.12)))
        f.blit(surf, lab, (c[0], c[1] + r * 0.32), max(8, int(r * 0.24)), (200, 200, 200), bold=True, anchor="center")
        f.blit(surf, fmt.format(v), (c[0], c[1] + r * 0.6), max(8, int(r * 0.26)), (240, 240, 240), mono=True, anchor="center")

    def _radios(self, surf, rr, world, panel):
        f = panel.f
        pygame.draw.rect(surf, (12, 14, 18), rr)
        rows = [("COM1", f"{world.com_freq:.3f}"), ("NAV1", f"{world.nav1.freq:.2f}"),
                ("ADF", f"{world.adf.freq:.0f}") if world.show_adf else ("NAV2", f"{world.nav2.freq:.2f}"),
                ("XPDR", f"{world.xpdr:04d}")]
        hh = rr.h / (len(rows) + 1)
        for i, (lab, val) in enumerate(rows):
            y = rr.y + hh * (i + 0.6)
            f.blit(surf, lab, (rr.x + 6, y), max(10, int(hh * 0.3)), (150, 160, 170), bold=True)
            f.blit(surf, val, (rr.right - 6, y), max(12, int(hh * 0.45)), (90, 240, 140), mono=True, bold=True, anchor="topright")
        ap = world.ap
        f.blit(surf, ("AP " if ap.engaged else "") + (ap.lat + "/" + ap.vert if ap.engaged else ""), (rr.x + 6, rr.bottom - hh * 0.7),
               max(10, int(hh * 0.35)), (90, 240, 140), mono=True, bold=True)
