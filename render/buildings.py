"""Edificios del aeródromo con detalle: hangares de chapa ondulada con portones corredizos, techo a dos aguas con
alero y canaleta, losa de concreto y letrero; torre de control con cabina de vidrio y balcón.

La geometría sale en coordenadas del mundo (NED) con normales, coordenadas de textura en metros y penumbra por
vértice (más oscuro al pie de las paredes y bajo los aleros). Las texturas se generan aquí mismo (no hacen falta
archivos) y son blancas o grises: el color de cada edificio lo pone el material.
"""
import math
import os

import numpy as np

TEX = 512


# ---------------------------------------------------------------- texturas
def _fnoise(rng, n, beta=1.6, lo=2.0):
    """Ruido periódico (se repite sin costuras) entre 0 y 1, más suave cuanto mayor es beta."""
    w = rng.standard_normal((n, n))
    f = np.fft.fftfreq(n) * n
    fx, fy = np.meshgrid(f, f, indexing="ij")
    fr = np.hypot(fx, fy)
    filt = np.where(fr > 0, np.maximum(fr, lo) ** -beta, 0.0)
    out = np.real(np.fft.ifft2(np.fft.fft2(w) * filt))
    out = (out - out.min()) / (out.max() - out.min() + 1e-9)
    return out


def _rgba(gray, tint=(1.0, 1.0, 1.0)):
    g = np.clip(gray, 0.0, 1.0)
    out = np.empty(g.shape + (4,), np.uint8)
    for k in range(3):
        out[..., k] = np.clip(g * tint[k] * 255.0, 0, 255).astype(np.uint8)
    out[..., 3] = 255
    return out


def tex_corrugated(seed=1, ribs=26, horizontal=False):
    """Chapa ondulada (4 x 4 m): ondas con brillo y sombra, uniones de las láminas cada metro y chorreaduras
    verticales de suciedad. Filas = v (de abajo arriba), columnas = u."""
    rng = np.random.default_rng(seed)
    n = TEX
    u = (np.arange(n) + 0.5) / n
    prof = np.cos(2 * math.pi * u * ribs)
    wave = 0.8 + 0.12 * prof + 0.08 * np.clip(np.sin(2 * math.pi * u * ribs + 0.9), 0, 1) ** 6
    f = (u * 4) % 1.0                                                  # uniones de las láminas cada metro
    seam = 1.0 - 0.2 * np.exp(-(np.minimum(f, 1 - f) / 0.006) ** 2)
    img = np.tile((wave * seam)[None, :], (n, 1))                     # [v, u]
    streak = _fnoise(rng, n, 1.2)
    streak = np.repeat(streak.mean(axis=0, keepdims=True), n, axis=0) # varía solo con u: chorreaduras verticales
    img *= 0.9 + 0.12 * streak
    img *= 0.94 + 0.08 * _fnoise(rng, n, 2.2)
    if horizontal:
        img = img.T
    return _rgba(img)


def tex_door(seed=2):
    """Portón corredizo (4 x 4 m): chapa con ondas horizontales finas, refuerzos cada metro y el canto del panel."""
    rng = np.random.default_rng(seed)
    n = TEX
    v = (np.arange(n) + 0.5) / n
    wave = 0.84 + 0.1 * np.cos(2 * math.pi * v * 40)
    rib = 1.0 - 0.22 * np.exp(-(((v * 4) % 1.0) - 0.5) ** 2 / 0.0004)
    img = np.tile((wave * rib)[:, None], (1, n))
    u = (np.arange(n) + 0.5) / n
    edge = 1.0 - 0.35 * (np.exp(-u ** 2 / 0.0003) + np.exp(-(1 - u) ** 2 / 0.0003))
    img *= edge[None, :]
    img *= 0.93 + 0.09 * _fnoise(rng, n, 2.0)
    return _rgba(img)


def tex_concrete(seed=3):
    """Losa de concreto (6 x 6 m): grano, manchas de aceite y juntas en el borde."""
    rng = np.random.default_rng(seed)
    n = TEX
    img = 0.72 + 0.1 * _fnoise(rng, n, 1.1) + 0.06 * (rng.random((n, n)) - 0.5)
    stains = _fnoise(rng, n, 2.4)
    img *= 1.0 - 0.28 * np.clip((stains - 0.62) * 4.0, 0, 1)
    c = (np.arange(n) + 0.5) / n
    j = np.minimum(np.minimum(c, 1 - c), 1.0)
    joint = 1.0 - 0.45 * np.exp(-(j / 0.004) ** 2)
    img *= joint[:, None] * joint[None, :]
    return _rgba(img, (1.0, 0.99, 0.96))


def tex_sign(text, w=1024, h=128):
    """Letrero: franja azul con letras blancas (y fila 0 = abajo, como espera la textura)."""
    import pygame
    if not pygame.font.get_init():
        pygame.font.init()
    surf = pygame.Surface((w, h))
    surf.fill((22, 62, 122))
    pygame.draw.rect(surf, (235, 238, 242), (0, 0, w, h), 6)
    font = pygame.font.SysFont("arial,helvetica,dejavusans", int(h * 0.62), bold=True)
    t = font.render(text, True, (245, 247, 250))
    surf.blit(t, ((w - t.get_width()) // 2, (h - t.get_height()) // 2))
    arr = pygame.surfarray.array3d(surf).transpose(1, 0, 2)[::-1]   # [fila desde abajo, columna, rgb]
    out = np.empty((h, w, 4), np.uint8)
    out[..., :3] = arr
    out[..., 3] = 255
    return out


# ---------------------------------------------------------------- geometría
class TexMesh:
    """Triángulos con [posición, normal, uv, penumbra, uv del mapa de luz] (11 floats), agrupados por material. El
    uv del mapa de luz vale -1 mientras el edificio no tenga luz horneada (ver apply_light)."""

    def __init__(self):
        self.parts = {}

    def quad(self, mat, p0, p1, p2, p3, uv, ao=(1.0, 1.0, 1.0, 1.0)):
        P = [np.asarray(p, np.float64) for p in (p0, p1, p2, p3)]
        n = np.cross(P[1] - P[0], P[3] - P[0])
        n = n / (np.linalg.norm(n) + 1e-12)
        rows = [np.concatenate([P[i], n, uv[i], [ao[i], -1.0, -1.0]]) for i in range(4)]
        self.parts.setdefault(mat, []).extend([rows[0], rows[1], rows[2], rows[0], rows[2], rows[3]])

    def tri(self, mat, p0, p1, p2, uv, ao=(1.0, 1.0, 1.0)):
        P = [np.asarray(p, np.float64) for p in (p0, p1, p2)]
        n = np.cross(P[1] - P[0], P[2] - P[0])
        n = n / (np.linalg.norm(n) + 1e-12)
        self.parts.setdefault(mat, []).extend([np.concatenate([P[i], n, uv[i], [ao[i], -1.0, -1.0]])
                                               for i in range(3)])

    def box(self, mat, lo, hi, tile=2.0, ao_floor=1.0):
        """Caja alineada a los ejes entre lo y hi (NED); cada cara con uv en metros / tile."""
        x0, x1 = sorted((lo[0], hi[0]))
        y0, y1 = sorted((lo[1], hi[1]))
        z0, z1 = sorted((lo[2], hi[2]))
        c = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
        sx, sy, sz = (x1 - x0) / tile, (y1 - y0) / tile, (z1 - z0) / tile
        for f, (du, dv) in (((0, 1, 2, 3), (sx, sy)), ((4, 5, 6, 7), (sx, sy)), ((0, 1, 5, 4), (sx, sz)),
                            ((1, 2, 6, 5), (sy, sz)), ((2, 3, 7, 6), (sx, sz)), ((3, 0, 4, 7), (sy, sz))):
            uv = [(0, 0), (du, 0), (du, dv), (0, dv)]
            ao = [1.0 if c[i][2] <= z0 + 1e-6 else ao_floor for i in f]
            self.quad(mat, *(c[i] for i in f), uv, ao)

    def arrays(self):
        return {m: np.asarray(v, np.float32) for m, v in self.parts.items() if v}


# ---------------------------------------------------------------- luz horneada (tools/hornear_luz.py)
LIGHT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "luz")
LIGHT_SCALE = 1.6                 # los mapas guardan luz / 1,6 en 8 bits (la luz pasa de 1 en techos con rebote)
_light_cache = {}


def hangar_key(ln, wd, ht):
    return f"hangar_{ln:g}x{wd:g}x{ht:g}"


def tower_key(h):
    return f"torre_{h:g}"


def role(mat):
    """Papel de un material en la geometría (el mismo para todos los hangares de igual tamaño aunque cambien el
    color o el letrero): así la luz horneada de uno sirve para todos."""
    for pre, r in (("wall:", "wall"), ("sign:", "sign")):
        if mat.startswith(pre):
            return r
    return mat


def load_light(key):
    """Mapa de luz horneado de una geometría: dict con 'lm' (S, S, 3) uint8, 'ground' (G, G) uint8, 'grect' (rectángulo
    del parche de suelo en coordenadas locales x0, y0, x1, y1) y 'uv_<papel>' (n, 3, 2). None si no está horneada."""
    if key not in _light_cache:
        p = os.path.join(LIGHT_DIR, key + ".npz")
        try:
            with np.load(p) as z:
                _light_cache[key] = {k: z[k] for k in z.files}
        except (OSError, ValueError):
            _light_cache[key] = None
    return _light_cache[key]


def apply_light(tm, data):
    """Copia a cada vértice el uv de su mapa de luz (la malla debe ser la misma geometría que se horneó)."""
    ok = False
    for mat, rows in tm.parts.items():
        uv = data.get("uv_" + role(mat))
        if uv is None or len(uv) * 3 != len(rows):
            continue
        uv = uv.reshape(-1, 2)
        for i, row in enumerate(rows):
            row[9:11] = uv[i]
        ok = True
    return ok


def ground_quad(x, y, gz, yaw, rect, lift=0.1):
    """Parche de suelo con la penumbra horneada alrededor de un edificio: 6 vértices [pos, uv] (en el mundo)."""
    c, s = math.cos(yaw), math.sin(yaw)
    x0, y0, x1, y1 = (float(v) for v in rect)
    out = []
    for (px, py) in ((x0, y0), (x1, y0), (x1, y1), (x0, y0), (x1, y1), (x0, y1)):
        # u a lo largo del este local (y), v del norte local (x): así lo despliega el horneado
        out.append((x + px * c - py * s, y + px * s + py * c, gz - lift, (py - y0) / (y1 - y0), (px - x0) / (x1 - x0)))
    return out


def _ao_h(h):
    """Penumbra según la altura sobre el suelo: el pie de las paredes queda más oscuro."""
    return 0.55 + 0.45 * min(1.0, max(0.0, h / 2.6))


def add_hangar(tm, x, y, gz, ln, wd, ht, yaw, color_key, sign_key=None):
    """Hangar de chapa de ln x wd x ht m (portón en la cara -y local, la que mira a la plataforma), con detalle de
    obra: zócalo de concreto, esquineros, techo a dos aguas con claraboyas y cumbrera, alero con canaleta y bajantes,
    viga y rieles del portón, hojas corredizas con paneles, ventanas y zócalo, una hoja corrida que deja ver el
    interior (piso, paredes, cielo y cerchas), oficina anexa con ventanas, puerta con alero y aires acondicionados,
    reflectores y letrero. La luz del cielo se hornea en Blender (tools/hornear_luz.py)."""
    c, s = math.cos(yaw), math.sin(yaw)

    def W(px, py, h):                               # local (a lo largo, a lo ancho, altura) -> mundo NED
        return (x + px * c - py * s, y + px * s + py * c, gz - h)

    def box(mat, p0, p1, tile=1.0, ao=1.0):
        """Caja en coordenadas locales (px, py, h) entre dos esquinas (con el giro del hangar)."""
        (ax, ay, ah), (bx, by, bh) = p0, p1
        ax, bx = sorted((ax, bx))
        ay, by = sorted((ay, by))
        ah, bh = sorted((ah, bh))
        v = [W(ax, ay, ah), W(bx, ay, ah), W(bx, by, ah), W(ax, by, ah),
             W(ax, ay, bh), W(bx, ay, bh), W(bx, by, bh), W(ax, by, bh)]
        sx, sy, sh = (bx - ax) / tile, (by - ay) / tile, (bh - ah) / tile
        for f, (du, dv) in (((0, 1, 2, 3), (sx, sy)), ((4, 5, 6, 7), (sx, sy)), ((0, 1, 5, 4), (sx, sh)),
                            ((1, 2, 6, 5), (sy, sh)), ((2, 3, 7, 6), (sx, sh)), ((3, 0, 4, 7), (sy, sh))):
            lo = [ao if v[i][2] >= gz - 0.01 else 1.0 for i in f]     # el pie, algo más oscuro
            tm.quad(mat, *(v[i] for i in f), [(0, 0), (du, 0), (du, dv), (0, dv)], lo)

    a, b = ln / 2, wd / 2
    rise = max(1.6, wd * 0.085)                    # techo de poca pendiente (~10°)
    ov = 0.7                                        # alero
    wall = f"wall:{color_key}"
    T = 4.0                                         # la textura de chapa cubre 4 x 4 m
    P0 = 0.4                                        # zócalo de concreto

    def wallq(p, q, py_p, py_q, h0, h1, mat=wall, off=0.0, tile=T):
        L = math.hypot(q - p, py_q - py_p)
        tm.quad(mat, W(p, py_p + off, h0), W(q, py_q + off, h0), W(q, py_q + off, h1), W(p, py_p + off, h1),
                [(0.0, h0 / tile), (L / tile, h0 / tile), (L / tile, h1 / tile), (0.0, h1 / tile)],
                [_ao_h(h0), _ao_h(h0), 1.0, 1.0])

    dx = 0.8 * a                                    # media abertura del portón
    dh = min(0.78 * ht, ht - 1.6)                   # alto del portón
    # ---- zócalo de concreto (sobresale 5 cm) y chapa encima
    box("plinth", (-a - 0.05, -b - 0.05, 0.0), (-dx, -b + 0.15, P0), tile=2.0, ao=0.75)
    box("plinth", (dx, -b - 0.05, 0.0), (a + 0.05, -b + 0.15, P0), tile=2.0, ao=0.75)
    box("plinth", (-a - 0.05, b - 0.15, 0.0), (a + 0.05, b + 0.05, P0), tile=2.0, ao=0.75)
    for sx in (-1, 1):
        box("plinth", (sx * a - 0.15, -b, 0.0), (sx * a + 0.05 * sx, b, P0), tile=2.0, ao=0.75)
    wallq(-a, -dx, -b, -b, P0, ht)
    wallq(dx, a, -b, -b, P0, ht)
    wallq(-dx, dx, -b, -b, dh + 0.9, ht)            # sobre la viga del portón
    wallq(a, -a, b, b, P0, ht)
    for sx in (-1, 1):
        px = sx * a
        wallq(px, px, -b * sx, b * sx, P0, ht)
        tm.tri(wall, W(px, -b, ht), W(px, b, ht), W(px, 0, ht + rise),
               [(0, ht / T), (wd / T, ht / T), (b / T, (ht + rise) / T)])
    # interior: paredes, piso y cielo por dentro (se ven por la hoja corrida; quedan en penumbra al hornear)
    ins = 0.12
    for (p, q, pp, qq) in ((-a + ins, a - ins, b - ins, b - ins), (-a + ins, -a + ins, -b + ins, b - ins),
                           (a - ins, a - ins, b - ins, -b + ins), (-a + ins, a - ins, -b + ins, -b + ins)):
        wallq(p, q, pp, qq, 0.02, ht, mat="interior")
    tm.quad("interiorfloor", W(-a + ins, -b + ins, 0.03), W(a - ins, -b + ins, 0.03), W(a - ins, b - ins, 0.03),
            W(-a + ins, b - ins, 0.03), [(0, 0), (ln / 6, 0), (ln / 6, wd / 6), (0, wd / 6)])
    for sy in (-1, 1):                              # cielo (bajo los faldones)
        tm.quad("interior", W(-a + ins, sy * (b - ins), ht - 0.05), W(a - ins, sy * (b - ins), ht - 0.05),
                W(a - ins, 0, ht + rise - 0.25), W(-a + ins, 0, ht + rise - 0.25),
                [(0, 0), (ln / T, 0), (ln / T, b / T), (0, b / T)])
    nb = max(3, int(ln / 7.5))                      # cerchas cada ~7,5 m
    for i in range(1, nb):
        px = -a + ln * i / nb
        for sy in (-1, 1):
            p0 = np.array(W(px, sy * (b - 0.3), ht - 0.3))
            p1 = np.array(W(px, 0, ht + rise - 0.45))
            _beam(tm, "steel", p0, p1, 0.25, 0.45)
            q0 = np.array(W(px, sy * (b - 0.3), ht - 1.4))
            _beam(tm, "steel", q0, np.array(W(px, 0, ht - 1.4)), 0.2, 0.2)
            _beam(tm, "steel", q0, np.array(W(px, sy * b * 0.5, ht + rise * 0.5 - 0.4)), 0.12, 0.12)
        box("steel", (px - 0.2, -b + 0.15, 0.0), (px + 0.2, -b + 0.5, ht - 0.3), tile=1.0)     # columnas
        box("steel", (px - 0.2, b - 0.5, 0.0), (px + 0.2, b - 0.15, ht - 0.3), tile=1.0)
    # ---- esquineros, botaguas del zócalo
    for sx in (-1, 1):
        for sy in (-1, 1):
            box("trim", (sx * a - 0.13 * (sx > 0), sy * b - 0.13 * (sy > 0), P0),
                (sx * a + 0.13 * (sx < 0) + 0.04 * sx, sy * b + 0.13 * (sy < 0) + 0.04 * sy, ht), tile=1.0)
    for (p, q, pp, qq) in ((-a, -dx, -b, -b), (dx, a, -b, -b), (-a, a, b, b), (-a, -a, -b, b), (a, a, -b, b)):
        nx, ny = (0.0, -0.06) if pp == qq and pp < 0 else ((0.0, 0.06) if pp == qq else ((-0.06 if p < 0 else 0.06), 0.0))
        box("trim", (min(p, q) + (nx if nx < 0 else 0), min(pp, qq) + (ny if ny < 0 else 0), P0 - 0.02),
            (max(p, q) + (nx if nx > 0 else 0), max(pp, qq) + (ny if ny > 0 else 0), P0 + 0.12), tile=1.0)
    # ---- techo: dos faldones con alero, claraboyas, cumbrera, frontis, canaleta y bajantes
    slope = rise / b
    Ls = math.hypot(b + ov, rise + ov * slope)
    he = ht - ov * slope
    for sy in (-1, 1):
        ye = sy * (b + ov)
        tm.quad("roof", W(-a - 0.5, ye, he), W(a + 0.5, ye, he), W(a + 0.5, 0, ht + rise + 0.05),
                W(-a - 0.5, 0, ht + rise + 0.05), [(0, 0), ((ln + 1.0) / T, 0), ((ln + 1.0) / T, Ls / T), (0, Ls / T)])
        # claraboyas: franjas de policarbonato a lo largo del faldón, algo más altas que la chapa
        for k in range(int(ln // 9)):
            u0 = -a + 4.5 + k * 9.0 - 0.6
            t0, t1 = 0.25, 0.8
            def R(px, t, lift=0.04):
                yy = ye * (1 - t)
                return W(px, yy, he + (ht + rise + 0.05 - he) * t + lift)
            tm.quad("skylight", R(u0, t0), R(u0 + 1.2, t0), R(u0 + 1.2, t1), R(u0, t1), [(0, 0), (1, 0), (1, 1), (0, 1)])
        tm.quad("trim", W(-a - 0.5, ye, he), W(a + 0.5, ye, he), W(a + 0.5, ye, he - 0.3), W(-a - 0.5, ye, he - 0.3),
                [(0, 0), (1, 0), (1, 1), (0, 1)])                      # frontis
        tm.quad("trim", W(-a - 0.5, sy * b, ht), W(a + 0.5, sy * b, ht), W(a + 0.5, ye, he), W(-a - 0.5, ye, he),
                [(0, 0), (1, 0), (1, 1), (0, 1)], (0.6, 0.6, 0.65, 0.65))   # cielo del alero
        g0 = ye + sy * 0.05
        box("gutter", (-a - 0.5, g0, he - 0.42), (a + 0.5, g0 + sy * 0.22, he - 0.2), tile=1.0)
        for sx in (-1, 1):                          # bajantes en las esquinas
            px = sx * (a + 0.2)
            box("gutter", (px - 0.07, g0 + sy * 0.02, 0.15), (px + 0.07, g0 + sy * 0.16, he - 0.35), tile=1.0)
            box("gutter", (px - 0.07, g0 + sy * 0.02, 0.05), (px + 0.07, g0 + sy * 0.45, 0.2), tile=1.0)
    for sx in (-1, 1):                              # frontis del hastial (sigue la pendiente)
        px = sx * (a + 0.5)
        for sy in (-1, 1):
            ye = sy * (b + ov)
            tm.quad("trim", W(px, ye, he), W(px, 0, ht + rise + 0.05), W(px, 0, ht + rise - 0.3), W(px, ye, he - 0.3),
                    [(0, 0), (1, 0), (1, 1), (0, 1)])
    box("trim", (-a - 0.5, -0.3, ht + rise - 0.02), (a + 0.5, 0.3, ht + rise + 0.14), tile=1.0)   # cumbrera
    # ---- portón: viga, rieles, hojas con paneles y ventanas; una hoja corrida deja ver adentro
    box("steel", (-dx - 0.7, -b - 0.45, dh), (dx + 0.7, -b, dh + 0.9), tile=2.0)
    box("trim", (-dx - 0.7, -b - 0.7, dh + 0.05), (dx + 0.7, -b - 0.45, dh + 0.3), tile=1.0)    # riel de arriba
    box("steel", (-dx - 0.5, -b - 0.75, 0.0), (dx + 0.5, -b - 0.1, 0.03), tile=1.0)              # riel del piso
    for px in (-dx - 0.35, dx + 0.35):                                                            # jambas
        box("steel", (px - 0.35, -b - 0.45, 0.0), (px + 0.35, -b, dh), tile=1.0, ao=0.7)
    nl = max(4, 2 * int(round(dx / 5.5)))
    leaf = 2 * dx / nl
    gap = nl // 2 - 1                               # esta hoja está corrida detrás de la vecina: abertura de una hoja
    for k in range(nl):
        if k == gap:
            continue
        p0 = -dx + k * leaf
        if k == gap + 1:
            pass
        off = -0.2 if k % 2 == 0 else -0.45
        if k == gap - 1:                            # la vecina queda adelante, en el riel de afuera
            off = -0.6
        py = -b + off
        p1 = p0 + leaf
        tm.quad("door", W(p0, py, 0.04), W(p1, py, 0.04), W(p1, py, dh), W(p0, py, dh),
                [(0, 0), (leaf / T, 0), (leaf / T, dh / T), (0, dh / T)], (0.7, 0.7, 1.0, 1.0))
        for pe in (p0, p1):                          # cantos y largueros de la hoja
            box("trim", (pe - 0.06, py - 0.08, 0.04), (pe + 0.06, py + 0.02, dh), tile=1.0)
        for hh in np.arange(1.2, dh - 0.4, 1.25):    # refuerzos horizontales
            box("trim", (p0 + 0.06, py - 0.05, hh), (p1 - 0.06, py, hh + 0.08), tile=1.0)
        box("trim", (p0 + 0.06, py - 0.04, 0.04), (p1 - 0.06, py, 0.6), tile=1.0, ao=0.7)       # zócalo de la hoja
        nw = max(2, int(leaf / 1.6))
        for i in range(nw):                          # ventanas con marco
            w0 = p0 + leaf * (i + 0.15) / nw
            w1 = p0 + leaf * (i + 0.85) / nw
            z0, z1 = dh * 0.66, dh * 0.8
            tm.quad("glass", W(w0, py - 0.03, z0), W(w1, py - 0.03, z0), W(w1, py - 0.03, z1), W(w0, py - 0.03, z1),
                    [(0, 0), (1, 0), (1, 1), (0, 1)])
            box("frame", (w0 - 0.05, py - 0.07, z0 - 0.05), (w1 + 0.05, py - 0.02, z0), tile=1.0)
            box("frame", (w0 - 0.05, py - 0.07, z1), (w1 + 0.05, py - 0.02, z1 + 0.05), tile=1.0)
    # reflectores sobre la viga del portón
    for px in (-dx * 0.6, 0.0, dx * 0.6):
        box("steel", (px - 0.05, -b - 0.45, dh + 1.0), (px + 0.05, -b - 1.0, dh + 1.08), tile=1.0)
        box("lamp", (px - 0.3, -b - 1.15, dh + 0.85), (px + 0.3, -b - 0.85, dh + 1.05), tile=1.0)
    # letrero sobre el portón
    if sign_key is not None:
        sw = min(0.55 * ln, 22.0)
        sh = min(1.6, ht - dh - 1.2)
        if sh > 0.6:
            z0 = dh + 1.05
            tm.quad(f"sign:{sign_key}", W(-sw / 2, -b - 0.05, z0), W(sw / 2, -b - 0.05, z0),
                    W(sw / 2, -b - 0.05, z0 + sh), W(-sw / 2, -b - 0.05, z0 + sh), [(1, 0), (0, 0), (0, 1), (1, 1)])
    # ---- oficina anexa sobre el hastial +a: bloque de una planta con ventanas, puerta con alero y aires
    ow, od, oh = min(14.0, wd * 0.55), 5.0, 3.4
    oy0 = -b + 1.5
    ox0, ox1 = a, a + od
    box("office", (ox0, oy0, 0.0), (ox1, oy0 + ow, oh), tile=3.0, ao=0.8)
    box("trim", (ox0, oy0 - 0.1, oh), (ox1 + 0.1, oy0 + ow + 0.1, oh + 0.35), tile=1.0)          # pretil
    box("plinth", (ox0, oy0 - 0.03, 0.0), (ox1 + 0.03, oy0 + ow + 0.03, 0.35), tile=2.0, ao=0.75)
    for i in range(int(ow // 2.6)):                  # ventanas al frente de la oficina (cara +x)
        w0 = oy0 + 0.9 + i * 2.6
        w1 = w0 + 1.5
        z0, z1 = 1.0, 2.3
        px = ox1 + 0.02
        tm.quad("glass", W(px, w0, z0), W(px, w1, z0), W(px, w1, z1), W(px, w0, z1), [(0, 0), (1, 0), (1, 1), (0, 1)])
        box("frame", (px - 0.02, w0 - 0.06, z0 - 0.08), (px + 0.06, w1 + 0.06, z0), tile=1.0)    # alféizar
        box("frame", (px - 0.02, w0 - 0.06, z1), (px + 0.05, w1 + 0.06, z1 + 0.06), tile=1.0)
        box("frame", (px - 0.02, (w0 + w1) / 2 - 0.03, z0), (px + 0.04, (w0 + w1) / 2 + 0.03, z1), tile=1.0)
    dy0 = oy0 + ow - 2.2                              # puerta con alero en la cara -y de la oficina
    tm.quad("doorpers", W(ox0 + 1.5, oy0 - 0.02, 0.02), W(ox0 + 2.5, oy0 - 0.02, 0.02), W(ox0 + 2.5, oy0 - 0.02, 2.2),
            W(ox0 + 1.5, oy0 - 0.02, 2.2), [(0, 0), (1, 0), (1, 1), (0, 1)])
    box("trim", (ox0 + 1.1, oy0 - 1.2, 2.5), (ox0 + 2.9, oy0, 2.6), tile=1.0)                   # alero de la puerta
    box("lamp", (ox0 + 1.85, oy0 - 0.12, 2.3), (ox0 + 2.15, oy0, 2.45), tile=1.0)
    for i in range(2):                                # aires acondicionados en la pared lateral +y
        py0 = oy0 + ow
        px0 = ox0 + 1.0 + i * 2.2
        box("ac", (px0, py0, 0.4), (px0 + 0.9, py0 + 0.35, 1.0), tile=1.0)
        box("trim", (px0 + 0.1, py0 + 0.35, 0.5), (px0 + 0.8, py0 + 0.37, 0.9), tile=1.0)
    _ = dy0
    # ---- puerta de personas en el hastial -a, con alero y luz
    px = -a - 0.03
    tm.quad("doorpers", W(px, -b * 0.4 - 0.5, 0.02), W(px, -b * 0.4 + 0.5, 0.02), W(px, -b * 0.4 + 0.5, 2.15),
            W(px, -b * 0.4 - 0.5, 2.15), [(0, 0), (1, 0), (1, 1), (0, 1)])
    box("trim", (px - 1.0, -b * 0.4 - 0.9, 2.45), (px, -b * 0.4 + 0.9, 2.55), tile=1.0)
    box("lamp", (px - 0.12, -b * 0.4 - 0.15, 2.25), (px, -b * 0.4 + 0.15, 2.4), tile=1.0)
    for wy in (b * 0.15, b * 0.6):                    # ventanas altas del hastial
        tm.quad("glass", W(px, wy - 0.9, 2.8), W(px, wy + 0.9, 2.8), W(px, wy + 0.9, 3.7), W(px, wy - 0.9, 3.7),
                [(0, 0), (1, 0), (1, 1), (0, 1)])
        box("frame", (px - 0.06, wy - 0.95, 2.72), (px, wy + 0.95, 2.8), tile=1.0)
    # ---- losa de concreto delante del portón
    S = 6.0
    tm.quad("concrete", W(-a - 2, -b - 16, 0.06), W(a + 2, -b - 16, 0.06), W(a + 2, -b, 0.06), W(-a - 2, -b, 0.06),
            [(0, 0), ((ln + 4) / S, 0), ((ln + 4) / S, 16 / S), (0, 16 / S)], (1.0, 1.0, 0.85, 0.85))


def _beam(tm, mat, p0, p1, w, h):
    """Viga de sección rectangular entre dos puntos (mundo NED)."""
    ax = p1 - p0
    L = float(np.linalg.norm(ax))
    if L < 1e-6:
        return
    ax = ax / L
    up = np.array([0.0, 0.0, -1.0])
    if abs(float(ax @ up)) > 0.95:
        up = np.array([1.0, 0.0, 0.0])
    side = np.cross(ax, up)
    side /= np.linalg.norm(side)
    upv = np.cross(side, ax)
    sd, uv_ = side * w / 2, upv * h / 2
    v = [p0 - sd - uv_, p0 + sd - uv_, p0 + sd + uv_, p0 - sd + uv_, p1 - sd - uv_, p1 + sd - uv_, p1 + sd + uv_, p1 - sd + uv_]
    for f in ((0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        tm.quad(mat, *(v[i] for i in f), [(0, 0), (1, 0), (1, L), (0, L)])


def add_tower(tm, x, y, gz, shaft_h=16.0):
    """Torre de control: fuste de concreto, cabina de vidrio con marcos, balcón con baranda, techo y antena."""
    def Z(h):
        return gz - h
    s = 3.5
    tm.box("tower", (x - s, y - s, Z(shaft_h)), (x + s, y + s, Z(0.0)), tile=6.0, ao_floor=0.7)
    # balcón (losa) y baranda
    tm.box("trim", (x - 6.2, y - 6.2, Z(shaft_h + 0.35)), (x + 6.2, y + 6.2, Z(shaft_h)), tile=1.0)
    for k in range(4):
        ang = k * math.pi / 2
        cx, cy = math.cos(ang), math.sin(ang)
        rx, ry = -cy, cx
        p = (x + cx * 6.1, y + cy * 6.1)
        tm.quad("gutter", (p[0] - rx * 6.1, p[1] - ry * 6.1, Z(shaft_h + 1.15)), (p[0] + rx * 6.1, p[1] + ry * 6.1, Z(shaft_h + 1.15)),
                (p[0] + rx * 6.1, p[1] + ry * 6.1, Z(shaft_h + 1.05)), (p[0] - rx * 6.1, p[1] - ry * 6.1, Z(shaft_h + 1.05)),
                [(0, 0), (1, 0), (1, 1), (0, 1)])
    # cabina: zócalo, vidrios inclinados hacia afuera y marcos
    c0, c1 = shaft_h + 0.35, shaft_h + 1.2
    tm.box("tower", (x - 4.6, y - 4.6, Z(c1)), (x + 4.6, y + 4.6, Z(c0)), tile=6.0)
    top = shaft_h + 4.2
    r0, r1 = 4.6, 5.2
    for k in range(8):
        a0 = (k - 0.5) * math.pi / 4
        a1 = (k + 0.5) * math.pi / 4
        q = [(x + math.cos(a0) * r0, y + math.sin(a0) * r0, Z(c1)), (x + math.cos(a1) * r0, y + math.sin(a1) * r0, Z(c1)),
             (x + math.cos(a1) * r1, y + math.sin(a1) * r1, Z(top)), (x + math.cos(a0) * r1, y + math.sin(a0) * r1, Z(top))]
        tm.quad("towerglass", *q, [(0, 0), (1, 0), (1, 1), (0, 1)])
        pm = (x + math.cos(a0) * r0, y + math.sin(a0) * r0)
        pt = (x + math.cos(a0) * r1, y + math.sin(a0) * r1)
        tm.box("trim", (min(pm[0], pt[0]) - 0.1, min(pm[1], pt[1]) - 0.1, Z(top)),
               (max(pm[0], pt[0]) + 0.1, max(pm[1], pt[1]) + 0.1, Z(c1)), tile=1.0)
    tm.box("trim", (x - 5.6, y - 5.6, Z(top + 0.5)), (x + 5.6, y + 5.6, Z(top)), tile=1.0)
    tm.box("gutter", (x - 0.08, y - 0.08, Z(top + 4.5)), (x + 0.08, y + 0.08, Z(top + 0.5)), tile=1.0)


MATERIALS = {
    # material: (color base, textura, transparente)
    "roof": ((0.5, 0.52, 0.55, 1.0), "corrugated", False),
    "door": ((0.78, 0.8, 0.82, 1.0), "door", False),
    "trim": ((0.3, 0.32, 0.35, 1.0), None, False),
    "gutter": ((0.82, 0.83, 0.84, 1.0), None, False),
    "glass": ((0.1, 0.14, 0.18, 1.0), None, False),
    "concrete": ((0.95, 0.95, 0.95, 1.0), "concrete", False),
    "tower": ((0.9, 0.88, 0.84, 1.0), "concrete", False),
    "towerglass": ((0.25, 0.4, 0.45, 0.42), None, True),
    "plinth": ((0.78, 0.77, 0.74, 1.0), "concrete", False),
    "interior": ((0.42, 0.43, 0.45, 1.0), "corrugated", False),
    "interiorfloor": ((0.55, 0.55, 0.53, 1.0), "concrete", False),
    "steel": ((0.38, 0.4, 0.43, 1.0), None, False),
    "skylight": ((0.78, 0.82, 0.84, 1.0), None, False),
    "frame": ((0.22, 0.23, 0.25, 1.0), None, False),
    "lamp": ((0.95, 0.93, 0.85, 1.0), None, False),
    "office": ((0.88, 0.86, 0.8, 1.0), "concrete", False),
    "doorpers": ((0.45, 0.47, 0.5, 1.0), "door", False),
    "ac": ((0.82, 0.82, 0.8, 1.0), None, False),
}
CORRUGATED = 26.0                 # ondas de la chapa por cuadro de textura (4 m): el shader las ilumina con el Sol


def material(mat):
    """(color, textura, transparente) de un material; 'wall:<r,g,b>' y 'sign:<texto>' llevan sus datos."""
    if mat.startswith("wall:"):
        col = tuple(float(v) for v in mat[5:].split(",")) + (1.0,)
        return col, "corrugated", False
    if mat.startswith(("sign:", "tsign:", "dsign:", "gsign:")):
        return (1.0, 1.0, 1.0, 1.0), mat, False
    return MATERIALS[mat]


def make_texture(key):
    if key == "corrugated":
        return tex_corrugated()
    if key == "door":
        return tex_door()
    if key == "concrete":
        return tex_concrete()
    if key.startswith("sign:"):
        return tex_sign(key[5:])
    if key.startswith("tsign:"):
        mand, loc = key[6:].split("|")
        return tex_taxi_sign(mand, loc)
    if key.startswith("dsign:"):
        return tex_distance_sign(key[6:])
    if key.startswith("gsign:"):
        text, arrow = key[6:].split("|")
        return tex_guide_sign(text, float(arrow))
    raise KeyError(key)


# ---------------------------------------------------------------- fachadas (edificios y casas)
# Vértice de 13 floats: posición, normal, color, u (metros a lo largo de la pared), v (altura sobre el suelo),
# altura del edificio y estilo (0 casa, 1 edificio, 2 torre de vidrio, 3 techo; la parte decimal varía el aspecto).
# Las ventanas, pisos y vidrieras las dibuja el shader (BLDG_FS) a partir de u y v.
HOUSE, BLOCK, TOWER, ROOF = 0, 1, 2, 3


def facade_walls(a, b, g, zb, ht, col, style):
    """Paredes de las aristas a -> b (planta, arrays (E, 2)): g suelo (m), zb altura del pie relativa al suelo
    (negativa para enterrarla un poco), ht altura del edificio, col (E, 3), style (E,). Devuelve (E*6, 13)."""
    d = b - a
    ln = np.sqrt((d ** 2).sum(1)) + 1e-9
    nrm = np.column_stack([d[:, 1] / ln, -d[:, 0] / ln, np.zeros(len(d))])
    E = len(a)
    pz0 = -(g + zb)
    pz1 = -(g + ht)
    p00 = np.column_stack([a, pz0])
    p10 = np.column_stack([b, pz0])
    p11 = np.column_stack([b, pz1])
    p01 = np.column_stack([a, pz1])
    out = np.empty((E, 6, 13), np.float32)
    out[..., 0:3] = np.stack([p00, p10, p11, p00, p11, p01], axis=1)
    out[..., 3:6] = nrm[:, None, :]
    out[..., 6:9] = col[:, None, :]
    zero = np.zeros(E)
    uu = np.stack([zero, ln, ln, zero, ln, zero], axis=1)
    vv = np.stack([zb, zb, ht, zb, ht, ht], axis=1)
    out[..., 9] = uu
    out[..., 10] = vv
    out[..., 11] = ht[:, None]
    out[..., 12] = style[:, None]
    return out.reshape(-1, 13)


def fan_roofs(c, a, b, z, col):
    """Techos planos en abanico desde el centro c por cada arista a -> b (z en NED). Devuelve (F*3, 13)."""
    F = len(c)
    out = np.empty((F, 3, 13), np.float32)
    out[..., 0:3] = np.stack([np.column_stack([c, z]), np.column_stack([a, z]), np.column_stack([b, z])], axis=1)
    out[..., 3:6] = np.array([0.0, 0.0, -1.0])
    out[..., 6:9] = col[:, None, :]
    out[..., 9:11] = out[..., 0:2]                   # en el techo, u y v son la planta (para el grano del techo)
    out[..., 11] = 0.0
    out[..., 12] = ROOF + 0.5
    return out.reshape(-1, 13)


def box_buildings(P, size, yaw, wall_col, roof_col, style, gable_frac=0.0):
    """Edificios rectangulares (casas y bloques de los pueblos del escenario de la escuela).
    P (m, 3) con el pie en NED, size (m, 3) = largo, ancho, alto total; gable_frac > 0: techo a dos aguas que ocupa
    esa parte de la altura (casas). Devuelve (n, 13)."""
    m = len(P)
    if m == 0:
        return np.zeros((0, 13), np.float32)
    c, s = np.cos(yaw), np.sin(yaw)
    hx, hy = size[:, 0] / 2, size[:, 1] / 2
    loc = np.array([(-1, -1), (1, -1), (1, 1), (-1, 1)], float)
    cx = loc[None, :, 0] * hx[:, None]
    cy = loc[None, :, 1] * hy[:, None]
    X = P[:, 0:1] + cx * c[:, None] - cy * s[:, None]
    Y = P[:, 1:2] + cx * s[:, None] + cy * c[:, None]
    corners = np.stack([X, Y], axis=-1)                            # (m, 4, 2)
    a = corners.reshape(-1, 2)
    b = np.roll(corners, -1, axis=1).reshape(-1, 2)
    g = np.repeat(-P[:, 2], 4)
    wall_h = size[:, 2] * (1.0 - gable_frac)
    ht = np.repeat(wall_h, 4)
    parts = [facade_walls(a, b, g, np.full(len(a), -0.6), ht, np.repeat(wall_col, 4, axis=0),
                          np.repeat(style, 4))]
    ztop = -(-P[:, 2] + wall_h)
    if gable_frac <= 0.0:
        cen = P[:, 0:2]
        parts.append(fan_roofs(np.repeat(cen, 4, axis=0), a, b, np.repeat(ztop, 4), np.repeat(roof_col, 4, axis=0)))
    else:
        # dos aguas a lo largo del lado mayor local x: cumbrera en y = 0, con un pequeño alero
        rise = size[:, 2] * gable_frac
        ov = 0.4
        zr = ztop - rise
        def W(lx, ly):
            return np.stack([P[:, 0] + lx * c - ly * s, P[:, 1] + lx * s + ly * c], axis=-1)
        out = []
        for sy in (-1, 1):
            e0 = W(-hx - ov, sy * (hy + ov))
            e1 = W(hx + ov, sy * (hy + ov))
            r1 = W(hx + ov, 0 * hy)
            r0 = W(-hx - ov, 0 * hy)
            ze = ztop + 0.4 * ov                                   # el alero baja un poco
            q = np.stack([np.column_stack([e0, ze]), np.column_stack([e1, ze]), np.column_stack([r1, zr]),
                          np.column_stack([e0, ze]), np.column_stack([r1, zr]), np.column_stack([r0, zr])], axis=1)
            nloc = np.stack([np.zeros(m), sy * rise, -(hy + ov)], axis=-1)
            nloc /= np.linalg.norm(nloc, axis=1, keepdims=True)
            nw = np.stack([-nloc[:, 1] * s, nloc[:, 1] * c, nloc[:, 2]], axis=-1)
            o = np.empty((m, 6, 13), np.float32)
            o[..., 0:3] = q
            o[..., 3:6] = nw[:, None, :]
            o[..., 6:9] = roof_col[:, None, :]
            o[..., 9:11] = q[..., 0:2]
            o[..., 11] = 0.0
            o[..., 12] = ROOF + 0.2
            out.append(o.reshape(-1, 13))
        # hastial triangular (pared, sin ventanas: queda sobre la altura de los pisos)
        for sx in (-1, 1):
            t0 = W(sx * hx, -hy)
            t1 = W(sx * hx, hy)
            tt = W(sx * hx, 0 * hy)
            tri = np.stack([np.column_stack([t0, ztop]), np.column_stack([t1, ztop]), np.column_stack([tt, zr])], axis=1)
            o = np.empty((m, 3, 13), np.float32)
            o[..., 0:3] = tri
            o[..., 3:6] = np.stack([sx * c, sx * s, np.zeros(m)], axis=-1)[:, None, :]
            o[..., 6:9] = wall_col[:, None, :]
            o[..., 9] = 0.0
            o[..., 10] = wall_h[:, None] + 1.0
            o[..., 11] = wall_h[:, None]
            o[..., 12] = style[:, None]
            out.append(o.reshape(-1, 13))
        parts += out
    return np.vstack(parts).astype(np.float32)


# ---------------------------------------------------------------- carteles de rodaje (OACI / FAA)
def tex_taxi_sign(mand, loc, w=512, h=128):
    """Cartel de posición de espera: parte roja con los números de pista en blanco (obligatorio) y, al lado, el de
    posición: fondo negro, letra y borde amarillos. Fila 0 = abajo."""
    import pygame
    if not pygame.font.get_init():
        pygame.font.init()
    surf = pygame.Surface((w, h))
    wm = int(w * 0.68)
    surf.fill((196, 22, 28), (0, 0, wm, h))
    surf.fill((12, 12, 12), (wm, 0, w - wm, h))
    pygame.draw.rect(surf, (240, 200, 30), (wm + 10, 10, w - wm - 20, h - 20), 5)
    font = pygame.font.SysFont("arial,helvetica,dejavusans", int(h * 0.64), bold=True)
    t = font.render(mand, True, (250, 250, 250))
    surf.blit(t, ((wm - t.get_width()) // 2, (h - t.get_height()) // 2))
    t = font.render(loc, True, (240, 200, 30))
    surf.blit(t, (wm + (w - wm - t.get_width()) // 2, (h - t.get_height()) // 2))
    arr = pygame.surfarray.array3d(surf).transpose(1, 0, 2)[::-1]
    out = np.empty((h, w, 4), np.uint8)
    out[..., :3] = arr
    out[..., 3] = 255
    return out


def add_taxi_sign(tm, x, y, gz, yaw, mand, loc):
    """Cartel sobre dos patas, de cara a quien rueda hacia la pista (yaw = hacia dónde mira la cara)."""
    c, s = math.cos(yaw), math.sin(yaw)
    fx, fy = c, s                                 # normal de la cara (hacia el piloto que se acerca)
    rx, ry = -s, c                                # a lo largo del cartel
    wdt, hgt, th, z0 = 2.4, 0.75, 0.25, 0.35
    key = f"tsign:{mand}|{loc}"

    def P(u, t, h):
        return (x + rx * u + fx * t, y + ry * u + fy * t, gz - h)
    # cara delantera (se lee de frente) y trasera (se lee desde atrás)
    tm.quad(key, P(-wdt / 2, th / 2, z0), P(wdt / 2, th / 2, z0), P(wdt / 2, th / 2, z0 + hgt), P(-wdt / 2, th / 2, z0 + hgt),
            [(1, 0), (0, 0), (0, 1), (1, 1)])
    tm.quad(key, P(wdt / 2, -th / 2, z0), P(-wdt / 2, -th / 2, z0), P(-wdt / 2, -th / 2, z0 + hgt), P(wdt / 2, -th / 2, z0 + hgt),
            [(1, 0), (0, 0), (0, 1), (1, 1)])
    # cantos y techo del cartel
    for (u0, u1) in ((-wdt / 2, -wdt / 2), (wdt / 2, wdt / 2)):
        tm.quad("signframe", P(u0, -th / 2, z0), P(u1, th / 2, z0), P(u1, th / 2, z0 + hgt), P(u0, -th / 2, z0 + hgt),
                [(0, 0), (1, 0), (1, 1), (0, 1)])
    tm.quad("signframe", P(-wdt / 2, -th / 2, z0 + hgt), P(wdt / 2, -th / 2, z0 + hgt), P(wdt / 2, th / 2, z0 + hgt),
            P(-wdt / 2, th / 2, z0 + hgt), [(0, 0), (1, 0), (1, 1), (0, 1)])
    for u in (-wdt * 0.32, wdt * 0.32):            # patas
        tm.quad("signframe", P(u - 0.04, 0, 0.0), P(u + 0.04, 0, 0.0), P(u + 0.04, 0, z0), P(u - 0.04, 0, z0),
                [(0, 0), (1, 0), (1, 1), (0, 1)], (0.6, 0.6, 1.0, 1.0))


MATERIALS["signframe"] = ((0.2, 0.2, 0.21, 1.0), None, False)


def tex_guide_sign(text, arrow, w=384, h=128):
    """Cartel de guía: fondo amarillo, letra negra y flecha negra (0 = adelante, -90 izquierda, 90 derecha) del lado
    hacia el que apunta, con borde negro fino."""
    import pygame
    if not pygame.font.get_init():
        pygame.font.init()
    surf = pygame.Surface((w, h))
    surf.fill((236, 190, 30))
    pygame.draw.rect(surf, (20, 20, 20), (0, 0, w, h), 4)
    font = pygame.font.SysFont("arial,helvetica,dejavusans", int(h * 0.66), bold=True)
    t = font.render(text, True, (15, 15, 15))
    aw = int(h * 0.62)
    total = t.get_width() + aw + 18
    x0 = (w - total) // 2
    if arrow < 0:                                   # flecha a la izquierda del texto
        ax, tx = x0, x0 + aw + 18
    else:
        tx, ax = x0, x0 + t.get_width() + 18
    surf.blit(t, (tx, (h - t.get_height()) // 2))
    cx, cy, r = ax + aw / 2, h / 2, aw / 2
    a = math.radians(arrow)
    d = (math.sin(a), -math.cos(a))                 # en la imagen: arriba = adelante
    n = (-d[1], d[0])
    tip = (cx + d[0] * r, cy + d[1] * r)
    base = (cx - d[0] * r, cy - d[1] * r)
    neck = (cx + d[0] * r * 0.05, cy + d[1] * r * 0.05)
    shaft = 0.16 * r
    head = 0.55 * r
    pts = [(base[0] + n[0] * shaft, base[1] + n[1] * shaft), (neck[0] + n[0] * shaft, neck[1] + n[1] * shaft),
           (neck[0] + n[0] * head, neck[1] + n[1] * head), tip,
           (neck[0] - n[0] * head, neck[1] - n[1] * head), (neck[0] - n[0] * shaft, neck[1] - n[1] * shaft),
           (base[0] - n[0] * shaft, base[1] - n[1] * shaft)]
    pygame.draw.polygon(surf, (15, 15, 15), pts)
    arr = pygame.surfarray.array3d(surf).transpose(1, 0, 2)[::-1]
    out = np.empty((h, w, 4), np.uint8)
    out[..., :3] = arr
    out[..., 3] = 255
    return out


def add_guide_sign(tm, x, y, gz, yaw, text, arrow):
    """Cartel de guía de una cara sobre dos patas (yaw = hacia dónde mira la cara); el dorso, gris."""
    c, s = math.cos(yaw), math.sin(yaw)
    fx, fy = c, s
    rx, ry = -s, c
    wdt, hgt, th, z0 = 2.4, 0.85, 0.25, 0.35
    key = f"gsign:{text}|{arrow:g}"

    def P(u, t, h):
        return (x + rx * u + fx * t, y + ry * u + fy * t, gz - h)
    tm.quad(key, P(-wdt / 2, th / 2, z0), P(wdt / 2, th / 2, z0), P(wdt / 2, th / 2, z0 + hgt), P(-wdt / 2, th / 2, z0 + hgt),
            [(1, 0), (0, 0), (0, 1), (1, 1)])
    tm.quad("signframe", P(wdt / 2, -th / 2, z0), P(-wdt / 2, -th / 2, z0), P(-wdt / 2, -th / 2, z0 + hgt),
            P(wdt / 2, -th / 2, z0 + hgt), [(0, 0), (1, 0), (1, 1), (0, 1)])
    for u0 in (-wdt / 2, wdt / 2):
        tm.quad("signframe", P(u0, -th / 2, z0), P(u0, th / 2, z0), P(u0, th / 2, z0 + hgt), P(u0, -th / 2, z0 + hgt),
                [(0, 0), (1, 0), (1, 1), (0, 1)])
    tm.quad("signframe", P(-wdt / 2, -th / 2, z0 + hgt), P(wdt / 2, -th / 2, z0 + hgt), P(wdt / 2, th / 2, z0 + hgt),
            P(-wdt / 2, th / 2, z0 + hgt), [(0, 0), (1, 0), (1, 1), (0, 1)])
    for u in (-wdt * 0.3, wdt * 0.3):
        tm.quad("signframe", P(u - 0.04, 0, 0.0), P(u + 0.04, 0, 0.0), P(u + 0.04, 0, z0), P(u - 0.04, 0, z0),
                [(0, 0), (1, 0), (1, 1), (0, 1)], (0.6, 0.6, 1.0, 1.0))


def tex_distance_sign(num, w=192, h=160):
    """Cartel de distancia restante: fondo negro y el número blanco (miles de pies que quedan de pista)."""
    import pygame
    if not pygame.font.get_init():
        pygame.font.init()
    surf = pygame.Surface((w, h))
    surf.fill((14, 14, 14))
    font = pygame.font.SysFont("arial,helvetica,dejavusans", int(h * 0.8), bold=True)
    t = font.render(num, True, (250, 250, 250))
    surf.blit(t, ((w - t.get_width()) // 2, (h - t.get_height()) // 2 + int(h * 0.03)))
    arr = pygame.surfarray.array3d(surf).transpose(1, 0, 2)[::-1]
    out = np.empty((h, w, 4), np.uint8)
    out[..., :3] = arr
    out[..., 3] = 255
    return out


def add_distance_sign(tm, x, y, gz, yaw, front, back):
    """Cartel de distancia restante de doble cara junto a la pista: la cara que mira hacia yaw muestra `front` (para
    quien corre hacia el cartel en ese sentido) y la otra `back` (para el sentido contrario)."""
    c, s = math.cos(yaw), math.sin(yaw)
    fx, fy = c, s
    rx, ry = -s, c
    wdt, hgt, th, z0 = 1.5, 1.2, 0.3, 0.45

    def P(u, t, h):
        return (x + rx * u + fx * t, y + ry * u + fy * t, gz - h)
    tm.quad(f"dsign:{front}", P(-wdt / 2, th / 2, z0), P(wdt / 2, th / 2, z0), P(wdt / 2, th / 2, z0 + hgt),
            P(-wdt / 2, th / 2, z0 + hgt), [(1, 0), (0, 0), (0, 1), (1, 1)])
    tm.quad(f"dsign:{back}", P(wdt / 2, -th / 2, z0), P(-wdt / 2, -th / 2, z0), P(-wdt / 2, -th / 2, z0 + hgt),
            P(wdt / 2, -th / 2, z0 + hgt), [(1, 0), (0, 0), (0, 1), (1, 1)])
    for u0 in (-wdt / 2, wdt / 2):
        tm.quad("signframe", P(u0, -th / 2, z0), P(u0, th / 2, z0), P(u0, th / 2, z0 + hgt), P(u0, -th / 2, z0 + hgt),
                [(0, 0), (1, 0), (1, 1), (0, 1)])
    tm.quad("signframe", P(-wdt / 2, -th / 2, z0 + hgt), P(wdt / 2, -th / 2, z0 + hgt), P(wdt / 2, th / 2, z0 + hgt),
            P(-wdt / 2, th / 2, z0 + hgt), [(0, 0), (1, 0), (1, 1), (0, 1)])
    for u in (-wdt * 0.3, wdt * 0.3):              # patas frangibles
        tm.quad("signframe", P(u - 0.04, 0, 0.0), P(u + 0.04, 0, 0.0), P(u + 0.04, 0, z0), P(u - 0.04, 0, z0),
                [(0, 0), (1, 0), (1, 1), (0, 1)], (0.6, 0.6, 1.0, 1.0))
