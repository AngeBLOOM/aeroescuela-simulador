"""Genera las texturas "fotográficas" del simulador por código (sin IA de imágenes).

Ejecutar:  python tools/make_assets.py      -> crea assets/*.png

Técnicas: ruido fractal isótropo por FFT (enlosable), relieve iluminado para
dar volumen (cuero, remaches, tornillos), degradados radiales para el metal y
canal alfa real para las piezas recortadas.
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
RNG = np.random.default_rng(2026)


# ------------------------------------------------------------------ utilidades
def fnoise(size, beta, fmin=1.0, rng=RNG):
    """Ruido fractal enlosable normalizado a media 0 y desviación 1."""
    white = rng.normal(size=(size, size))
    F = np.fft.fft2(white)
    fx = np.fft.fftfreq(size) * size
    f = np.sqrt(fx[:, None] ** 2 + fx[None, :] ** 2)
    f[0, 0] = 1.0
    F *= 1.0 / np.maximum(f, fmin) ** (beta / 2.0)
    F[0, 0] = 0
    n = np.real(np.fft.ifft2(F))
    return (n - n.mean()) / (n.std() + 1e-9)


def shade(height, strength=1.0, light=(-0.6, -0.6, 0.55)):
    """Iluminación de un mapa de alturas (relieve) -> factor de brillo."""
    gy, gx = np.gradient(height)
    nx, ny, nz = -gx * strength, -gy * strength, np.ones_like(height)
    ln = np.sqrt(nx * nx + ny * ny + nz * nz)
    lx, ly, lz = light
    ll = math.sqrt(lx * lx + ly * ly + lz * lz)
    return (nx * lx + ny * ly + nz * lz) / (ln * ll)


def save_rgb(arr, name):
    img = np.clip(arr, 0, 1)
    surf = pygame.surfarray.make_surface((img.transpose(1, 0, 2) * 255).astype(np.uint8))
    pygame.image.save(surf, os.path.join(OUT, name))
    print("  ", name, img.shape[1], "x", img.shape[0])


def save_rgba(rgb, alpha, name):
    h, w = alpha.shape
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.surfarray.pixels3d(surf)[...] = (np.clip(rgb, 0, 1).transpose(1, 0, 2) * 255).astype(np.uint8)
    pygame.surfarray.pixels_alpha(surf)[...] = (np.clip(alpha, 0, 1).T * 255).astype(np.uint8)
    pygame.image.save(surf, os.path.join(OUT, name))
    print("  ", name, w, "x", h)


def wrap_lines(size, n, length, width, rng, angle_spread=math.pi):
    """Rayitas finas enlosables (máscara 0..1)."""
    m = np.zeros((size, size))
    for _ in range(n):
        x, y = rng.uniform(0, size, 2)
        a = rng.uniform(0, angle_spread)
        L = rng.uniform(length * 0.3, length)
        steps = int(L)
        for k in range(steps):
            xi = int(x + math.cos(a) * k) % size
            yi = int(y + math.sin(a) * k) % size
            m[yi, xi] = max(m[yi, xi], rng.uniform(0.4, 1.0))
            if width > 1:
                m[(yi + 1) % size, xi] = max(m[(yi + 1) % size, xi], 0.4)
    return m


def disk(size, cx, cy, r, soft=1.5):
    y, x = np.mgrid[0:size[0], 0:size[1]]
    d = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
    return np.clip((r - d) / soft + 0.5, 0, 1), d


def rounded_rect_mask(h, w, x0, y0, x1, y1, rad, soft=1.2):
    y, x = np.mgrid[0:h, 0:w]
    cx = np.clip(x, x0 + rad, x1 - rad)
    cy = np.clip(y, y0 + rad, y1 - rad)
    d = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
    return np.clip((rad - d) / soft + 0.5, 0, 1)


# ------------------------------------------------------------------ materiales
def panel_material(S=1024):
    base = np.array([0.155, 0.162, 0.172])
    grain = fnoise(S, 0.2, 1) * 0.018          # polvo de la pintura
    mottle = fnoise(S, 3.0, 2) * 0.022         # variaciones suaves
    scratches = wrap_lines(S, 260, 70, 1, RNG, math.pi) * 0.05
    lum = 1.0 + grain + mottle + scratches
    sh = shade(fnoise(S, 0.6, 1) * 0.6, 1.0) * 0.06
    rgb = base[None, None, :] * (lum + sh)[..., None]
    save_rgb(rgb, "panel_material.png")


def glareshield(S=1024):
    # grano de cuero: celdas de ruido iluminadas en relieve
    cells = fnoise(S, 1.2, 40)
    cells = np.abs(cells) ** 0.7
    h = cells * 1.6 + fnoise(S, 2.5, 3) * 0.6
    light = shade(h, 2.2) * 0.13
    base = 0.045 + 0.012 * fnoise(S, 3.0, 2)
    rgb = np.repeat((base + light + 0.035)[..., None], 3, axis=2) * np.array([1.0, 1.0, 1.04])
    save_rgb(rgb, "glareshield.png")


def interior(S=1024):
    h = fnoise(S, 1.0, 20) * 0.5 + fnoise(S, 2.6, 2) * 0.4
    lum = 0.66 + shade(h, 1.6) * 0.05 + fnoise(S, 0.4, 1) * 0.012
    rgb = lum[..., None] * np.array([0.98, 0.98, 1.0])
    save_rgb(rgb, "interior_lateral.png")


def seat(S=512):
    y, x = np.mgrid[0:S, 0:S]
    weave = (np.sin(x * 2 * math.pi / 8) * np.sin(y * 2 * math.pi / 8)) * 0.5
    tweed = fnoise(S, 0.8, 30)
    h = weave * 0.7 + tweed * 0.6
    lum = 0.20 + shade(h, 1.8) * 0.06 + tweed * 0.025 + fnoise(S, 2.8, 2) * 0.02
    rgb = lum[..., None] * np.array([0.95, 0.96, 1.0])
    save_rgb(rgb, "tela_asiento.png")


def aircraft_skin(S=1024):
    lum = 0.92 + fnoise(S, 3.0, 2) * 0.012 + fnoise(S, 0.5, 1) * 0.006
    h = np.zeros((S, S))
    # costuras de paneles cada 256 px y remaches cada 16 px a lo largo
    seam = np.zeros((S, S))
    for k in range(0, S, 256):
        seam[:, k:k + 2] = 1
        seam[k:k + 2, :] = 1
    y, x = np.mgrid[0:S, 0:S]
    riv = np.zeros((S, S))
    for k in range(0, S, 256):
        for off in (6, -6):
            line_x = (k + off) % S
            dx = np.abs(((x - line_x + S / 2) % S) - S / 2)
            dy = ((y % 16) - 8)
            riv = np.maximum(riv, np.clip(1.0 - np.sqrt(dx ** 2 + dy ** 2) / 2.3, 0, 1))
            line_y = (k + off) % S
            dy2 = np.abs(((y - line_y + S / 2) % S) - S / 2)
            dx2 = ((x % 16) - 8)
            riv = np.maximum(riv, np.clip(1.0 - np.sqrt(dy2 ** 2 + dx2 ** 2) / 2.3, 0, 1))
    h = riv * 1.2 - seam * 0.8
    lum = lum + shade(h, 3.0) * 0.08 - seam * 0.10
    grime = np.clip(fnoise(S, 2.0, 4), 0, None) * 0.015 * (0.4 + seam * 3)
    lum -= grime
    rgb = lum[..., None] * np.array([1.0, 1.0, 1.01])
    save_rgb(rgb, "pintura_avion.png")


def asphalt(S=1024):
    # árido fino: granos claros y oscuros de 1-3 px sobre betún gris
    fine = fnoise(S, 0.0, 1)
    grains = fnoise(S, 0.6, 1)
    light = np.clip(grains - 1.1, 0, None) * 0.22
    dark = np.clip(-grains - 1.2, 0, None) * 0.18
    mottle = fnoise(S, 2.8, 2) * 0.018 + fnoise(S, 1.8, 6) * 0.012
    lum = 0.30 + fine * 0.035 + light - dark + mottle
    # pocas grietas selladas, finas y suaves
    cr = np.zeros((S, S))
    for _ in range(3):
        x, y = RNG.uniform(0, S, 2)
        a = RNG.uniform(0, 2 * math.pi)
        for k in range(RNG.integers(200, 420)):
            a += RNG.normal(0, 0.08)
            x, y = (x + math.cos(a) * 1.5) % S, (y + math.sin(a) * 1.5) % S
            xi, yi = int(x), int(y)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    w = 1 - math.hypot(dx, dy) / 2.0
                    if w > 0:
                        cr[(yi + dy) % S, (xi + dx) % S] = max(cr[(yi + dy) % S, (xi + dx) % S], w)
    lum = lum * (1 - cr * 0.35)
    lum += shade(grains * 0.5, 1.0) * 0.025
    rgb = lum[..., None] * np.array([0.97, 0.98, 1.02])
    save_rgb(rgb, "asfalto.png")


def grass(S=1024):
    blades = fnoise(S, 0.2, 1)
    tufts = fnoise(S, 1.2, 12)
    patches = fnoise(S, 3.2, 3)
    dry = np.clip(fnoise(S, 2.6, 5) - 0.9, 0, 1) * 0.6
    g = np.array([0.31, 0.41, 0.19])
    y_ = np.array([0.52, 0.48, 0.30])
    rgb = g[None, None] * (1 + 0.05 * patches[..., None] + 0.05 * tufts[..., None])
    rgb = rgb * (1 - dry[..., None]) + y_ * dry[..., None]
    rgb *= (0.90 + 0.10 * np.tanh(blades)[..., None])
    rgb *= 1.0 + shade(tufts * 0.6 + blades * 0.25, 1.0)[..., None] * 0.07
    save_rgb(rgb, "cesped.png")


# ------------------------------------------------------------------ piezas de cabina
def bezel(S=512):
    """Marco cuadrado de instrumento: aluminio anodizado negro, 4 tornillos, agujero redondo."""
    alpha = rounded_rect_mask(S, S, 2, 2, S - 3, S - 3, 26)
    c = S / 2
    hole, d = disk((S, S), c, c, S * 0.455, 1.2)
    y, x = np.mgrid[0:S, 0:S]
    # base con anodizado y leve cepillado
    brushed = fnoise(S, 0.3, 1) * 0.012
    base = 0.085 + brushed + 0.02 * (1 - y / S)
    # biselado del agujero: anillo con brillo arriba-izquierda
    ring_in, ring_out = S * 0.455, S * 0.5
    t = np.clip((d - ring_in) / (ring_out - ring_in), 0, 1)
    ang = np.arctan2(y - c, x - c)
    hl = (np.cos(ang + 2.35) * 0.5 + 0.5)
    bevel = (1 - t) ** 3 * (0.10 + 0.22 * hl) * (d > ring_in)
    lip = np.exp(-((d - ring_in - 2.5) / 2.2) ** 2) * (0.20 + 0.35 * hl)
    # borde exterior biselado de la placa
    edge = rounded_rect_mask(S, S, 10, 10, S - 11, S - 11, 20, 6)
    outer = (1 - edge) * 0.05 * (1 - y / S + 0.3)
    lum = base + bevel + lip + outer
    rgb = np.repeat(lum[..., None], 3, axis=2) * np.array([1.0, 1.0, 1.06])
    # tornillos Phillips
    for sx, sy in ((0.1, 0.1), (0.9, 0.1), (0.1, 0.9), (0.9, 0.9)):
        cx, cy = sx * S, sy * S
        m, dd = disk((S, S), cx, cy, S * 0.032, 1.0)
        dome = np.clip(1 - dd / (S * 0.032), 0, 1)
        sang = np.arctan2(y - cy, x - cx)
        sl = 0.25 + 0.45 * dome * (np.cos(sang + 2.35) * 0.5 + 0.5)
        cross = ((np.abs(x - cx) < 1.6) | (np.abs(y - cy) < 1.6)) & (dd < S * 0.022)
        sl = np.where(cross, 0.05, sl)
        shadow, _ = disk((S, S), cx + 2, cy + 3, S * 0.036, 2.5)
        rgb *= (1 - shadow * 0.5)[..., None]
        rgb = rgb * (1 - m[..., None]) + np.repeat(sl[..., None], 3, axis=2) * m[..., None] * np.array([0.9, 0.92, 0.95])
    a = alpha * (1 - hole)
    save_rgba(rgb, a, "bisel_redondo.png")


def dial_face(S=512):
    c = S / 2
    m, d = disk((S, S), c, c, S * 0.497, 1.0)
    vign = 1 - np.clip((d / (S * 0.5)) ** 4, 0, 1) * 0.55
    lum = (0.055 + fnoise(S, 0.4, 1) * 0.006 + fnoise(S, 3, 2) * 0.006) * vign
    # sombra interior que proyecta el bisel
    inner = np.clip((d - S * 0.40) / (S * 0.1), 0, 1) ** 2 * 0.6
    lum *= (1 - inner)
    rgb = np.repeat(lum[..., None], 3, axis=2)
    save_rgba(rgb, m, "esfera_vacia.png")


def glass(S=512):
    c = S / 2
    y, x = np.mgrid[0:S, 0:S]
    d = np.sqrt((x - c) ** 2 + (y - c) ** 2) / (S / 2)
    ang = np.arctan2(y - c, x - c)
    # franja curva superior izquierda
    band = np.exp(-((d - 0.78) / 0.07) ** 2) * np.clip(np.cos(ang + 2.2) * 1.4 - 0.4, 0, 1)
    glow = np.exp(-(((x - S * 0.33) ** 2 + (y - S * 0.28) ** 2) / (2 * (S * 0.16) ** 2))) * 0.18
    rim = np.exp(-((d - 0.985) / 0.02) ** 2) * 0.25
    a = np.clip(band * 0.55 + glow + rim, 0, 1) * (d < 1.0)
    rgb = np.ones((S, S, 3))
    save_rgba(rgb, a, "vidrio_reflejo.png")


def g1000_frame(W=1024, H=768):
    """Marco genérico de pantalla de cabina de cristal (sin marcas), pantalla transparente."""
    y, x = np.mgrid[0:H, 0:W]
    body = rounded_rect_mask(H, W, 2, 2, W - 3, H - 3, 34)
    sx0, sy0, sx1, sy1 = 92, 54, W - 92, H - 128
    screen = rounded_rect_mask(H, W, sx0, sy0, sx1, sy1, 6, 1.0)
    tex = fnoise(max(W, H), 0.2, 1)[:H, :W] * 0.01
    lum = 0.20 + tex - 0.05 * (y / H) + fnoise(max(W, H), 3, 2)[:H, :W] * 0.01
    # bisel alrededor de la pantalla (sombra hacia dentro)
    dx = np.minimum(np.abs(x - sx0), np.abs(x - sx1))
    dy = np.minimum(np.abs(y - sy0), np.abs(y - sy1))
    near = np.exp(-np.minimum(dx, dy) / 6.0) * (1 - screen)
    lum -= near * 0.08
    # borde exterior con brillo superior
    edge = 1 - rounded_rect_mask(H, W, 8, 8, W - 9, H - 9, 28, 5)
    lum += edge * (0.10 * (1 - y / H))
    rgb = np.repeat(lum[..., None], 3, axis=2)

    def button(cx, cy, w, h):
        nonlocal rgb
        m = rounded_rect_mask(H, W, cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, 5, 1.0)
        top = np.clip(1 - (y - (cy - h / 2)) / h, 0, 1)
        bl = 0.13 + 0.07 * top
        sh = rounded_rect_mask(H, W, cx - w / 2 + 2, cy - h / 2 + 3, cx + w / 2 + 2, cy + h / 2 + 3, 6, 2.0)
        rgb *= (1 - sh * 0.35)[..., None]
        rgb = rgb * (1 - m[..., None]) + np.repeat(bl[..., None], 3, axis=2) * m[..., None]

    def knob(cx, cy, r1, r2):
        nonlocal rgb
        sh, _ = disk((H, W), cx + 3, cy + 4, r1 + 3, 3)
        rgb *= (1 - sh * 0.45)[..., None]
        for r, b in ((r1, 0.10), (r2, 0.16)):
            m, d = disk((H, W), cx, cy, r, 1.0)
            ang = np.arctan2(y - cy, x - cx)
            knurl = (np.sin(ang * 40) * 0.5 + 0.5) * 0.04 * (d > r * 0.8)
            dome = np.clip(1 - d / r, 0, 1)
            l = b + knurl + dome * 0.05 * (np.cos(ang + 2.35) * 0.5 + 0.5)
            rgb = rgb * (1 - m[..., None]) + np.repeat(l[..., None], 3, axis=2) * m[..., None]
    nb = 12
    bw = (sx1 - sx0) / nb
    for i in range(nb):
        button(sx0 + bw * (i + 0.5), H - 92, bw * 0.72, 26)
    for side in (46, W - 46):
        for k in range(4):
            button(side, 120 + k * 110, 50, 30)
    knob(70, H - 52, 34, 22)
    knob(W - 70, H - 52, 34, 22)
    a = body * (1 - screen)
    save_rgba(rgb, a, "pantalla_g1000_marco.png")


def clouds():
    """Cúmulos: unión suave de bocanadas esféricas, sombreado continuo desde arriba."""
    for i in range(3):
        S = 512
        rng = np.random.default_rng(100 + i)
        y, x = np.mgrid[0:S, 0:S] / (S - 1) * 2 - 1
        keep = np.ones((S, S))
        for _ in range(16 + 4 * i):
            cx = rng.uniform(-0.6, 0.6)
            cy = rng.uniform(-0.45, 0.25) + abs(cx) * 0.35
            rr = rng.uniform(0.14, 0.34) * (1.0 - abs(cx) * 0.5)
            d2 = ((x - cx) ** 2 + (y - cy) ** 2) / rr ** 2
            ball = np.clip(1 - d2, 0, 1) ** 0.5
            keep *= (1 - ball)
        dens = 1 - keep                                     # unión suave
        dens *= np.clip((0.42 - y) / 0.06, 0, 1)            # base plana
        n = fnoise(S, 3.0, 4, rng)
        # sombreado: la "altura" es la densidad muy suavizada (bordes redondeados), luz desde arriba
        F = np.fft.fft2(dens)
        fx = np.fft.fftfreq(S)
        g = np.exp(-(fx[:, None] ** 2 + fx[None, :] ** 2) * (2 * np.pi * 7.0) ** 2 / 2)
        hgt = np.real(np.fft.ifft2(F * g))
        light = shade(hgt * 45.0, 1.0, light=(-0.3, -0.85, 0.45))
        top = np.clip(0.55 - y * 0.6, 0.2, 1.0)
        lum = np.clip(0.58 + 0.36 * np.clip(light, 0, 1) + 0.16 * top + n * 0.03, 0.55, 1.05)
        lum = lum * (0.86 + 0.14 * np.clip((0.42 - y) * 2.5, 0, 1))
        # borde plateado: las zonas finas dejan pasar la luz
        edge = 1 - np.clip(hgt * 3.0, 0, 1)
        lum = lum * (1 - edge) + 1.0 * edge
        # bordes deshilachados con ruido
        wisp = fnoise(S, 1.6, 6, rng)
        a = np.clip((hgt - 0.04 + wisp * 0.035) * 3.2, 0, 1) ** 1.2
        rgb = np.repeat(lum[..., None], 3, axis=2) * np.array([1.0, 1.0, 1.03])
        save_rgba(np.clip(rgb, 0, 1), a, f"nube_{i + 1}.png")


def main(only=None):
    pygame.init()
    os.makedirs(OUT, exist_ok=True)
    print("Generando texturas en", OUT)
    if only:
        for name in only:
            globals()[name]()
        return
    panel_material()
    glareshield()
    interior()
    seat()
    aircraft_skin()
    asphalt()
    grass()
    bezel()
    dial_face()
    glass()
    g1000_frame()
    clouds()
    print("Listo.")


if __name__ == "__main__":
    main(sys.argv[1:])
