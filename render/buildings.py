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
    """Hangar de ln x wd x ht m (portón en la cara -y local, la que mira a la plataforma), techo a dos aguas."""
    c, s = math.cos(yaw), math.sin(yaw)

    def W(px, py, h):                               # local (a lo largo, a lo ancho, altura) -> mundo NED
        return (x + px * c - py * s, y + px * s + py * c, gz - h)
    a, b = ln / 2, wd / 2
    rise = 2.5
    ov = 0.6                                        # alero
    wall = f"wall:{color_key}"
    T = 4.0                                         # la textura de chapa cubre 4 x 4 m

    def wallq(p, q, py_p, py_q, h0, h1, ao_top=0.92, mat=wall, off=0.0):
        """Pared vertical de (p, py_p) a (q, py_q) en planta local, entre las alturas h0 y h1."""
        L = math.hypot(q - p, py_q - py_p)
        u0 = 0.0
        tm.quad(mat, W(p, py_p + off, h0), W(q, py_q + off, h0), W(q, py_q + off, h1), W(p, py_p + off, h1),
                [(u0, h0 / T), (u0 + L / T, h0 / T), (u0 + L / T, h1 / T), (u0, h1 / T)],
                [_ao_h(h0), _ao_h(h0), min(ao_top, _ao_h(h1)), min(ao_top, _ao_h(h1))])
    # cara del portón (-b): marcos laterales y franja sobre la abertura
    dx = 0.85 * a
    dh = 0.8 * ht
    wallq(-a, -dx, -b, -b, 0, ht)
    wallq(dx, a, -b, -b, 0, ht)
    wallq(-dx, dx, -b, -b, dh, ht)
    # trasera y laterales
    wallq(a, -a, b, b, 0, ht)
    for sx in (-1, 1):
        px = sx * a
        wallq(px, px, -b * sx, b * sx, 0, ht)
        # hastial triangular hasta la cumbrera
        tm.tri(wall, W(px, -b, ht), W(px, b, ht), W(px, 0, ht + rise),
               [(0, ht / T), (wd / T, ht / T), (b / T, (ht + rise) / T)], (0.85, 0.85, 0.8))
    # techo: dos faldones con alero, canto (fascia), parte de abajo del alero y cumbrera
    roof = "roof"
    slope = rise / b
    L = math.hypot(b + ov, rise + ov * slope)
    for sy in (-1, 1):
        ye = sy * (b + ov)
        he = ht - ov * slope
        tm.quad(roof, W(-a - 0.4, ye, he), W(a + 0.4, ye, he), W(a + 0.4, 0, ht + rise + 0.05),
                W(-a - 0.4, 0, ht + rise + 0.05),
                [(0, 0), ((ln + 0.8) / T, 0), ((ln + 0.8) / T, L / T), (0, L / T)])
        tm.quad("trim", W(-a - 0.4, ye, he), W(a + 0.4, ye, he), W(a + 0.4, ye, he - 0.28), W(-a - 0.4, ye, he - 0.28),
                [(0, 0), (1, 0), (1, 1), (0, 1)])
        tm.quad("trim", W(-a - 0.4, sy * b, ht), W(a + 0.4, sy * b, ht), W(a + 0.4, ye, he), W(-a - 0.4, ye, he),
                [(0, 0), (1, 0), (1, 1), (0, 1)], (0.55, 0.55, 0.62, 0.62))
        # canaleta
        g0 = ye + sy * 0.08
        tm.quad("gutter", W(-a - 0.4, g0, he - 0.05), W(a + 0.4, g0, he - 0.05), W(a + 0.4, g0, he - 0.3),
                W(-a - 0.4, g0, he - 0.3), [(0, 0), (1, 0), (1, 1), (0, 1)])
    tm.quad("trim", W(-a - 0.4, -0.25, ht + rise + 0.02), W(a + 0.4, -0.25, ht + rise + 0.02),
            W(a + 0.4, 0.25, ht + rise + 0.02), W(-a - 0.4, 0.25, ht + rise + 0.02), [(0, 0), (1, 0), (1, 1), (0, 1)])
    # portón: cuatro hojas corredizas en dos rieles (unas más afuera que otras), con ventanas y canto
    leaf = 2 * dx / 4
    for k in range(4):
        p0 = -dx + k * leaf
        p1 = p0 + leaf
        off = -0.12 if k % 2 == 0 else -0.32
        py = -b + off
        tm.quad("door", W(p0, py, 0.02), W(p1, py, 0.02), W(p1, py, dh), W(p0, py, dh),
                [(0, 0), (leaf / T, 0), (leaf / T, dh / T), (0, dh / T)], (0.62, 0.62, 0.95, 0.95))
        for pe in (p0, p1):                          # cantos de la hoja
            tm.quad("door", W(pe, -b, 0.02), W(pe, py, 0.02), W(pe, py, dh), W(pe, -b, dh),
                    [(0, 0), (0.05, 0), (0.05, dh / T), (0, dh / T)], (0.5, 0.5, 0.8, 0.8))
        nw = max(2, int(leaf / 3.2))
        for i in range(nw):                          # ventanas altas de la hoja
            w0 = p0 + leaf * (i + 0.2) / nw
            w1 = p0 + leaf * (i + 0.8) / nw
            tm.quad("glass", W(w0, py - 0.02, dh * 0.72), W(w1, py - 0.02, dh * 0.72), W(w1, py - 0.02, dh * 0.86),
                    W(w0, py - 0.02, dh * 0.86), [(0, 0), (1, 0), (1, 1), (0, 1)])
    # riel y marco del portón
    tm.box("trim", W(-dx - 0.6, -b - 0.55, dh + 0.45), W(dx + 0.6, -b - 0.02, dh), tile=1.0)
    for px in (-dx - 0.35, dx + 0.35):
        tm.box("trim", W(px - 0.25, -b - 0.4, dh), W(px + 0.25, -b, 0.0), tile=1.0, ao_floor=0.6)
    # letrero sobre el portón
    if sign_key is not None:
        sw = min(0.55 * ln, 22.0)
        sh = min(1.6, ht - dh - 0.7)
        if sh > 0.6:
            z0 = dh + 0.55
            tm.quad(f"sign:{sign_key}", W(-sw / 2, -b - 0.04, z0), W(sw / 2, -b - 0.04, z0),
                    W(sw / 2, -b - 0.04, z0 + sh), W(-sw / 2, -b - 0.04, z0 + sh), [(1, 0), (0, 0), (0, 1), (1, 1)])
    # puerta de personas y ventanas en el hastial +a
    for px, pyd in ((a + 0.03, -b * 0.5),):
        tm.quad("trim", W(px, pyd - 0.5, 0.02), W(px, pyd + 0.5, 0.02), W(px, pyd + 0.5, 2.15), W(px, pyd - 0.5, 2.15),
                [(0, 0), (1, 0), (1, 1), (0, 1)], (0.7, 0.7, 0.9, 0.9))
        for wy in (b * 0.1, b * 0.55):
            tm.quad("glass", W(px, wy - 0.9, 2.6), W(px, wy + 0.9, 2.6), W(px, wy + 0.9, 3.6), W(px, wy - 0.9, 3.6),
                    [(0, 0), (1, 0), (1, 1), (0, 1)])
    # losa de concreto delante del portón
    S = 6.0
    tm.quad("concrete", W(-a - 2, -b - 14, 0.06), W(a + 2, -b - 14, 0.06), W(a + 2, -b, 0.06), W(-a - 2, -b, 0.06),
            [(0, 0), ((ln + 4) / S, 0), ((ln + 4) / S, 14 / S), (0, 14 / S)], (1.0, 1.0, 0.8, 0.8))


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
}


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
