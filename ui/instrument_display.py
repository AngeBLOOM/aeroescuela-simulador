"""Pantalla de instrumentos para cabinas físicas.

Solo los instrumentos, sin mandos, botones ni textos de ayuda: pensada para ir detrás de un
tablero físico (volante, gases e interruptores reales) en un segundo monitor, o a pantalla
completa en un equipo dedicado.

- Aviones clásicos: seis básicos, NAV 1/NAV 2, tacómetro, indicadores de motor y combustible,
  radios (solo lectura) y anunciadores.
- Aviones G1000 (o con el modo cristal elegido): PFD y MFD a toda la pantalla.

Para que las piezas no tiemblen, cada instrumento se repinta en fotogramas alternos
(la mitad en cada uno).
"""
import math

import pygame

from sim.mathx import clamp
from .gauges import bar_gauge
from .ui import COL


class _NullUI:
    """Pantalla de la consola: no hay ratón. Los botones de cabina se dibujan (las listas del GPS, que se recorren con la
    perilla FMS, y los rótulos de las teclas), pero no se pueden pulsar."""
    tooltip = None

    def __init__(self, fonts=None):
        self.f = fonts

    def button(self, *a, **k):
        return False

    def cockpit_button(self, surf, rect, label, active=False, size=15, color=None, enabled=True, tip=None, style="normal"):
        if self.f is None:
            return False
        rect = pygame.Rect(rect)
        base = COL["button_on"] if active else (color if color is not None else COL["button"])
        if not enabled:
            base = (36, 38, 42)
        if style != "flat":
            pygame.draw.rect(surf, base, rect, border_radius=6)
        pygame.draw.rect(surf, (64, 70, 80), rect, 1, border_radius=6)
        self.f.blit(surf, label, rect.center, size, COL["white"] if enabled else COL["dim"], bold=True, anchor="center")
        return False

    def scroll(self, *a, **k):
        return 0

    def hover(self, *a, **k):
        return False

    def hit(self, *a, **k):
        return False


class InstrumentDisplay:
    SLOW = ("engine", "radios", "annun", "compass", "cdi2", "mfd", "tach")

    def __init__(self, fonts, overrides=None):
        self.f = fonts
        self.frame = 0
        self._tiles = {}
        self._key = None
        # posiciones elegidas a mano (normalizadas 0..1) para encajar en el tablero físico
        self.overrides = overrides if overrides is not None else {}
        self.editing = False
        self.sel = None
        self.drag = None

    # ------------------------------------------------------------ distribución
    def layout(self, W, H, world, glass):
        """Rectángulos de cada instrumento (pantalla completa, fondo negro)."""
        L = {}
        if glass:
            # dos pantallas con la forma real del G1000 (4:3), completas y centradas, sin estirarlas
            m = int(min(W, H) * 0.03)
            gap = int(max(12, W * 0.015))
            h = H - 2 * m
            w = int(h * 4 / 3)
            if 2 * w + gap > W - 2 * m:
                w = int((W - 2 * m - gap) / 2)
                h = int(w * 3 / 4)
            x0 = (W - (2 * w + gap)) // 2
            y0 = (H - h) // 2
            L["pfd"] = pygame.Rect(x0, y0, w, h)
            L["mfd"] = pygame.Rect(x0 + w + gap, y0, w, h)
            return L
        # clásico: columna de motor | seis básicos + NAV | radios
        r = int(min(H / 4.5, (W - 24) / 14.4))
        gap = int(r * 0.22)
        col_w = 2 * r + gap
        engine_w = int(r * 2.3)
        radios_w = int(r * 2.7)
        total = engine_w + 4 * col_w + radios_w
        x0 = max(8, (W - total) // 2)
        y1 = int(H / 2 - r - gap / 2)
        y2 = int(H / 2 + r + gap / 2)
        xs = [x0 + engine_w + col_w * i + col_w // 2 for i in range(4)]
        for name, x, y in (("asi", xs[0], y1), ("ai", xs[1], y1), ("alt", xs[2], y1), ("cdi1", xs[3], y1),
                           ("tc", xs[0], y2), ("hi", xs[1], y2), ("vsi", xs[2], y2), ("cdi2", xs[3], y2)):
            L[name] = (x, y, r)
        # tacómetro arriba y barras de motor debajo
        L["tach"] = (x0 + engine_w // 2, y1, int(r * 0.92))
        L["engine"] = pygame.Rect(x0 + 6, y1 + r + gap, engine_w - 18, y2 + r - (y1 + r + gap))
        rx = x0 + engine_w + 4 * col_w + 8
        L["radios"] = pygame.Rect(rx, y1 - r, radios_w - 8, int(r * 2.6))
        L["annun"] = pygame.Rect(rx, y1 - r + int(r * 2.6) + gap, radios_w - 8, int(r * 1.9))
        L["compass"] = pygame.Rect(xs[1] - r, max(4, y1 - r - int(r * 0.5) - 8), 2 * r, int(r * 0.45))
        return L

    # ------------------------------------------------------------ dibujo
    def draw(self, surf, world, panel, glass=None):
        """Dibuja la pantalla completa de instrumentos en 'surf'."""
        W, H = surf.get_size()
        ac = world.ac
        if glass is None:
            glass = ac.t.default_cockpit == "glass" or panel.mode == "glass"
        self.frame += 1
        mode = "glass" if glass else "clasico"
        ov = self.overrides.get(mode, {})
        key = (W, H, glass, ac.t.id, repr(sorted(ov.items())))
        if key != self._key:
            self._key = key
            self._L = self.layout(W, H, world, glass)
            for name, v in ov.items():
                if name not in self._L:
                    continue
                if isinstance(self._L[name], tuple):
                    self._L[name] = (v[0] * W, v[1] * H, max(10, v[2] * H))
                else:
                    self._L[name] = pygame.Rect(v[0] * W, v[1] * H, max(20, v[2] * W), max(20, v[3] * H))
            self._mode = mode
            self._tiles = {}
            for name, v in self._L.items():
                if isinstance(v, tuple):
                    x, y, r = v
                    m = int(r * 1.42)
                    rect = pygame.Rect(x - m, y - m, 2 * m, 2 * m)
                else:
                    rect = pygame.Rect(v)
                self._tiles[name] = [rect, pygame.Surface(rect.size, pygame.SRCALPHA), True]
        if getattr(self, "bg_style", "futurista") == "futurista":
            surf.blit(self._background(W, H, ac), (0, 0))
        else:
            surf.fill((6, 6, 7))             # negro: para una cabina física con tablero recortado delante de la pantalla
        if not ac.sys.electric_ok and glass:
            for name in ("pfd", "mfd"):
                pygame.draw.rect(surf, (2, 2, 3), self._L[name])
            return
        for i, (name, tile) in enumerate(self._tiles.items()):
            rect, ts, fresh = tile
            every = 4 if name in self.SLOW else 2
            if fresh or (self.frame + i) % every == 0:
                ts.fill((0, 0, 0, 0))
                self._paint(ts, name, rect, world, panel)
                tile[2] = False
            surf.blit(ts, rect.topleft)

    # ------------------------------------------------------------ fondo futurista
    def _background(self, W, H, ac):
        """Tablero futurista detrás de los instrumentos (se construye una vez por disposición)."""
        from . import theme
        key = ("bg", W, H, self._key)
        if getattr(self, "_bg_key", None) == key:
            return self._bg_surf
        base = pygame.Surface((W, H))
        for y in range(H):
            k = y / max(1, H - 1)
            base.fill((int(9 - 6 * k), int(18 - 11 * k), int(29 - 17 * k)), (0, y, W, 1))
        lay = pygame.Surface((W, H), pygame.SRCALPHA)
        # rejilla técnica
        step = 34
        for x in range(0, W, step):
            pygame.draw.line(lay, (0, 200, 255, 12), (x, 0), (x, H))
        for y in range(0, H, step):
            pygame.draw.line(lay, (0, 200, 255, 12), (0, y), (W, y))
        # filete superior con brillo hacia abajo
        for i in range(18):
            pygame.draw.line(lay, (0, 220, 255, int(40 * (1 - i / 18) ** 2)), (0, i), (W, i))
        pygame.draw.line(lay, (*theme.CYAN, 220), (0, 0), (W, 0), 2)
        base.blit(lay, (0, 0))
        # alojamientos de cada instrumento
        sockets = pygame.Surface((W, H), pygame.SRCALPHA)
        for name, v in self._L.items():
            if isinstance(v, tuple):
                x, y, r = v
                rr = int(r * 1.16)
                for g in range(6, 0, -1):
                    pygame.draw.circle(sockets, (0, 200, 255, 6 * g), (int(x), int(y)), rr + g * 2, 2)
                pygame.draw.circle(sockets, (2, 6, 11, 255), (int(x), int(y)), rr)
                pygame.draw.circle(sockets, (*theme.CYAN, 120), (int(x), int(y)), rr, 2)
                for a in range(0, 360, 45):
                    ang = math.radians(a)
                    p0 = (x + math.cos(ang) * (rr + 3), y + math.sin(ang) * (rr + 3))
                    p1 = (x + math.cos(ang) * (rr + 9), y + math.sin(ang) * (rr + 9))
                    pygame.draw.line(sockets, (*theme.CYAN, 150), p0, p1, 2)
            else:
                rect = pygame.Rect(v).inflate(14, 14)
                theme.holo_panel(sockets, rect, (2, 6, 11, 255), True, cut=10)
        base.blit(sockets, (0, 0))
        # rótulos técnicos
        f = self.f
        f.blit(base, f"{ac.t.short.upper()}  -  PANEL DE INSTRUMENTOS", (14, H - 8), 11, (90, 150, 180), tech=True,
               anchor="bottomleft")
        f.blit(base, "AEROESCUELA", (W - 14, H - 8), 11, (90, 150, 180), tech=True, anchor="bottomright")
        self._bg_key, self._bg_surf = key, base
        return base

    # ------------------------------------------------------------ editor (F3)
    def edit(self, surf, origin, ui):
        """Mover (arrastrar) y escalar (rueda) cada instrumento. origin = posición de 'surf' en la ventana."""
        W, H = surf.get_size()
        ox, oy = origin
        mx, my = ui.mouse[0] - ox, ui.mouse[1] - oy
        L = self._L
        mode = self._mode
        ov = self.overrides.setdefault(mode, {})

        def rect_of(name):
            v = L[name]
            if isinstance(v, tuple):
                x, y, r = v
                return pygame.Rect(x - r, y - r, 2 * r, 2 * r)
            return pygame.Rect(v)
        for name in L:
            r = rect_of(name)
            col = (255, 210, 40) if name == self.sel else (60, 200, 255)
            pygame.draw.rect(surf, col, r, 2)
            self.f.blit(surf, name.upper(), (r.x + 4, r.y + 2), 12, col, bold=True)
        pygame.draw.rect(surf, (0, 0, 0, 200), (8, 8, 620, 28))
        self.f.blit(surf, "EDITOR (F3 para salir): arrastre cada instrumento · rueda = tamaño · Supr = posición original",
                    (14, 14), 13, (255, 230, 120), bold=True)
        if ui.clicked:
            cx, cy = ui.clicked[0] - ox, ui.clicked[1] - oy
            hit = [n for n in L if rect_of(n).collidepoint(cx, cy)]
            if hit:
                self.sel = min(hit, key=lambda n: rect_of(n).w)
                r = rect_of(self.sel)
                self.drag = (cx - r.x, cy - r.y)
                ui.clicked = None
        if not pygame.mouse.get_pressed()[0]:
            self.drag = None
        if self.sel and self.drag is not None:
            r = rect_of(self.sel)
            nx, ny = mx - self.drag[0], my - self.drag[1]
            v = L[self.sel]
            if isinstance(v, tuple):
                rr = v[2]
                ov[self.sel] = [(nx + rr) / W, (ny + rr) / H, rr / H]
            else:
                ov[self.sel] = [nx / W, ny / H, r.w / W, r.h / H]
        d = ui.wheel
        if self.sel and d:
            ui.wheel = 0
            v = L[self.sel]
            k = 1.06 if d > 0 else 1 / 1.06
            if isinstance(v, tuple):
                ov[self.sel] = [v[0] / W, v[1] / H, v[2] * k / H]
            else:
                r = pygame.Rect(v)
                c = r.center
                nw, nh = r.w * k, r.h * k
                ov[self.sel] = [(c[0] - nw / 2) / W, (c[1] - nh / 2) / H, nw / W, nh / H]

    def reset_selected(self):
        if self.sel:
            self.overrides.get(self._mode, {}).pop(self.sel, None)

    def _paint(self, s, name, rect, world, panel):
        g = panel.g
        ac = world.ac
        ind = world.ind
        sysm = ac.sys
        v = self._L[name]
        if isinstance(v, tuple):
            x, y, r = v
            p = (x - rect.x, y - rect.y)
        local = pygame.Rect(0, 0, rect.w, rect.h)
        if name == "asi":
            g.asi(s, p, r, ind.ias, ac.t.v)
        elif name == "ai":
            g.attitude(s, p, r, ind.ai_roll, ind.ai_pitch, flag=sysm.gyro_spin < 0.5)
        elif name == "alt":
            g.altimeter(s, p, r, ind.alt_ft, world.kollsman)
        elif name == "tc":
            g.turn_coord(s, p, r, ind.turn_rate, ind.slip, sysm.electric_ok)
        elif name == "hi":
            g.heading(s, p, r, ind.dg, world.ap.hdg_bug)
        elif name == "vsi":
            g.vsi(s, p, r, ind.vs_fpm)
        elif name == "cdi1":
            g.cdi(s, p, r, world.nav_source(), "GPS" if world.cdi_src == "GPS" else "NAV 1")
        elif name == "cdi2":
            if world.show_adf:
                g.adf(s, p, r, world.adf)
            else:
                g.cdi(s, p, r, world.nav2, "NAV 2")
        elif name == "tach":
            g.tach(s, p, r, sysm.engine.rpm)
        elif name == "engine":
            self._engine(s, local, world)
        elif name == "radios":
            self._radios(s, local, world)
        elif name == "annun":
            self._annun(s, local, world)
        elif name == "compass":
            g.compass(s, local, ind.compass)
        elif name in ("pfd", "mfd"):
            # pantalla pequeña: se dibuja a un tamaño mínimo legible y se reduce entera (nunca se recorta)
            NW = 640
            if rect.w >= NW:
                buf, dst = s, local
            else:
                bh = int(NW * rect.h / max(rect.w, 1))
                buf = getattr(self, "_glass_bufs", {}).get((name, bh))
                if buf is None:
                    buf = pygame.Surface((NW, bh), pygame.SRCALPHA)
                    self._glass_bufs = {**getattr(self, "_glass_bufs", {}), (name, bh): buf}
                buf.fill((0, 0, 0, 255))
                dst = pygame.Rect(0, 0, NW, bh)
            if name == "pfd":
                panel.glass.pfd(buf, dst, world, _NullUI(self.f))
            else:
                panel.glass.mfd(buf, dst, world, _NullUI(self.f))
            if buf is not s:
                s.blit(pygame.transform.smoothscale(buf, rect.size), (0, 0))

    def _engine(self, s, rect, world):
        sysm = world.ac.sys
        e = sysm.engine
        f = self.f
        cap = world.ac.t.fuel_capacity / 2
        rows = [("COMB IZQ L", sysm.fuel_l / 2, 0, cap, (cap * 0.15, cap)),
                ("COMB DER L", sysm.fuel_l / 2, 0, cap, (cap * 0.15, cap)),
                ("T ACEITE °F", e.oil_temp, 50, 260, (100, 245)),
                ("P ACEITE PSI", e.oil_press, 0, 115, (50, 90)),
                ("EGT °F", e.egt, 800, 1650, (1150, 1550)),
                ("VACÍO inHg", sysm.vacuum, 0, 7, (4.5, 5.5)),
                ("VOLTIOS", sysm.bus_volts, 20, 32, (24.5, 29.5))]
        if not world.ac.t.fixed_pitch and not world.ac.t.fadec:
            rows.insert(2, ("ADMISIÓN inHg", e.map_inhg, 10, 35, (15, 25)))
        rh = rect.h / len(rows)
        for i, (lab, v, lo, hi, gr) in enumerate(rows):
            bar_gauge(f, s, (rect.x, rect.y + i * rh, rect.w, rh - 4), lab, v, lo, hi, gr,
                      fmt="{:.1f}" if hi < 40 else "{:.0f}")

    def _radios(self, s, rect, world):
        f = self.f
        pygame.draw.rect(s, (14, 15, 18), rect, border_radius=8)
        pygame.draw.rect(s, (60, 62, 68), rect, 2, border_radius=8)
        rows = [("COM 1", f"{world.com_freq:.3f}", f"{world.com_standby:.3f}"),
                ("NAV 1", f"{world.nav1.freq:.2f}", f"{world.nav1.standby:.2f}"),
                (("ADF", f"{world.adf.freq:.0f}", f"{world.adf.standby:.0f}") if world.show_adf else
                 ("NAV 2", f"{world.nav2.freq:.2f}", f"{world.nav2.standby:.2f}")),
                ("XPDR", f"{world.xpdr:04d}", "ALT")]
        hh = rect.h / (len(rows) + 0.6)
        big = max(14, int(hh * 0.42))
        on = world.ac.sys.avionics_ok
        for i, (lab, act, stby) in enumerate(rows):
            y = rect.y + hh * (i + 0.35)
            f.blit(s, lab, (rect.x + 12, y + 4), max(10, int(hh * 0.22)), COL["grey"], bold=True)
            if on:
                f.blit(s, act, (rect.x + 12, y + hh * 0.30), big, (90, 240, 140), mono=True, bold=True)
                f.blit(s, stby, (rect.right - 12, y + hh * 0.36), max(12, int(big * 0.7)), (110, 190, 255), mono=True,
                       anchor="topright")
        ap = world.ap
        txt = ("PA " + ap.lat + " / " + ap.vert) if ap.engaged else "PA OFF"
        f.blit(s, txt, (rect.x + 12, rect.bottom - hh * 0.55), max(12, int(hh * 0.28)),
               (90, 240, 140) if ap.engaged else COL["dim"], mono=True, bold=True)

    def _annun(self, s, rect, world):
        f = self.f
        ac = world.ac
        sysm = ac.sys
        items = [("FUEGO", sysm.fire_level > 0.01, (230, 40, 30)),
                 ("HUMO", sysm.smoke_level > 0.05, (230, 40, 30)),
                 ("PUERTA", sysm.failures.get("door", False), (230, 170, 30)),
                 ("VOLT BAJO", sysm.bus_volts < 25 and sysm.master, (230, 170, 30)),
                 ("VACÍO", sysm.vacuum < 3.5 and any(e.running for e in sysm.engines), (230, 170, 30)),
                 ("P ACEITE", sysm.engine.oil_press < 20 and sysm.engine.running, (230, 60, 50)),
                 ("COMB BAJO", sysm.fuel_l < ac.t.fuel_capacity * 0.1, (230, 170, 30)),
                 ("PÉRDIDA", sysm.stall_warning, (230, 60, 50)),
                 ("FRENO EST", sysm.parking_brake, (230, 170, 30))]
        if ac.t.retractable:
            items.insert(0, ("TREN ABAJO", sysm.gear_pos > 0.99, (40, 220, 80)))
        cols = 2
        rows = (len(items) + 1) // cols
        cw, rh = rect.w / cols, rect.h / rows
        for i, (lab, lit, col) in enumerate(items):
            r = pygame.Rect(rect.x + (i % cols) * cw + 3, rect.y + (i // cols) * rh + 3, cw - 6, rh - 6)
            pygame.draw.rect(s, col if lit else (28, 28, 31), r, border_radius=4)
            f.blit(s, lab, r.center, max(9, int(min(rh * 0.36, cw / max(len(lab), 4) * 1.5))),
                   (10, 10, 10) if lit else (80, 80, 86), bold=True, anchor="center")
