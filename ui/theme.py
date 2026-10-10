"""Estilo futurista de la interfaz (menús, paneles, botones y avisos). Los instrumentos no se tocan:
siguen siendo réplicas realistas de los del avión.

Paneles de cristal oscuro con esquinas recortadas, filetes y corchetes de neón cian, botones biselados que
brillan al pasar el ratón, títulos con letras espaciadas, fondo con rejilla y barrido de radar, y anillos de
progreso. Todo se dibuja con pygame sobre la superposición y lo costoso se guarda en caché.
"""
import math
import time

import pygame

CYAN = (0, 220, 255)
CYAN_DIM = (0, 150, 190)
TEAL = (90, 255, 210)
TEXT = (226, 242, 252)
TEXT_DIM = (120, 166, 192)
DEEP = (5, 12, 22)
FILL = (6, 18, 30, 232)
AMBER = (255, 184, 40)
RED = (255, 74, 74)
GREEN = (60, 240, 150)

_cache = {}


def chamfer(rect, c=10, corners="tlbr"):
    """Polígono del rectángulo con esquinas recortadas (t=arriba-izq., b=abajo-dcha., r=arriba-dcha., l=abajo-izq.)."""
    r = pygame.Rect(rect)
    c = max(0, min(c, r.w // 3, r.h // 3))
    tl = "t" in corners
    br = "b" in corners
    tr = "r" in corners
    bl = "l" in corners
    pts = []
    pts += [(r.x, r.y + c), (r.x + c, r.y)] if tl else [(r.x, r.y)]
    pts += [(r.right - 1 - c, r.y), (r.right - 1, r.y + c)] if tr else [(r.right - 1, r.y)]
    pts += [(r.right - 1, r.bottom - 1 - c), (r.right - 1 - c, r.bottom - 1)] if br else [(r.right - 1, r.bottom - 1)]
    pts += [(r.x + c, r.bottom - 1), (r.x, r.bottom - 1 - c)] if bl else [(r.x, r.bottom - 1)]
    return pts


def accent_for(fill):
    """Color de los filetes: cian para paneles oscuros; el propio color, aclarado, para avisos de color."""
    if fill is None or max(fill[:3]) < 45:
        return CYAN
    m = max(fill[:3])
    return tuple(min(255, int(v * 255 / m * 0.95 + 30)) for v in fill[:3])


def holo_panel(surf, rect, fill=None, border=True, accent=None, cut=14):
    """Panel de cristal: relleno translúcido, filete fino, corchetes brillantes en dos esquinas y brillo superior."""
    r = pygame.Rect(rect)
    if r.w < 4 or r.h < 4:
        return
    fill = fill or FILL
    if len(fill) == 3:
        fill = (*fill, 215)
    pts = chamfer(r, cut)
    pygame.draw.polygon(surf, fill, pts)
    if not border:
        return
    acc = accent or (accent_for(fill) if not isinstance(border, tuple) else border)
    pygame.draw.polygon(surf, (*acc[:3], 90), pts, 1)
    # brillo en el borde superior
    pygame.draw.line(surf, (*acc[:3], 60), (r.x + cut + 2, r.y + 1), (r.right - 3, r.y + 1))
    # corchetes en la esquina superior izquierda y la inferior derecha
    k = min(26, r.w // 4, r.h // 3)
    bright = (*acc[:3], 235)
    pygame.draw.lines(surf, bright, False, [(r.x, r.y + cut + k), (r.x, r.y + cut), (r.x + cut, r.y), (r.x + cut + k, r.y)], 2)
    pygame.draw.lines(surf, bright, False, [(r.right - 1, r.bottom - 1 - cut - k), (r.right - 1, r.bottom - 1 - cut),
                                            (r.right - 1 - cut, r.bottom - 1), (r.right - 1 - cut - k, r.bottom - 1)], 2)
    # marcas pequeñas en las otras dos esquinas
    pygame.draw.line(surf, (*acc[:3], 150), (r.right - 1 - 8, r.y), (r.right - 1, r.y), 2)
    pygame.draw.line(surf, (*acc[:3], 150), (r.x, r.bottom - 1), (r.x + 8, r.bottom - 1), 2)


def glow(surf, rect, color, layers=3, cut=8):
    r = pygame.Rect(rect)
    for i in range(layers, 0, -1):
        rr = r.inflate(i * 4, i * 4)
        pygame.draw.polygon(surf, (*color[:3], int(26 / i)), chamfer(rr, cut + i * 2), 2)


def button(surf, fonts, rect, label, hov=False, active=False, color=None, enabled=True, size=15):
    r = pygame.Rect(rect)
    cut = min(9, r.h // 3)
    pts = chamfer(r, cut)
    if not enabled:
        pygame.draw.polygon(surf, (14, 22, 30, 190), pts)
        pygame.draw.polygon(surf, (50, 70, 84, 160), pts, 1)
        fonts.blit(surf, label, r.center, size, (90, 110, 125), bold=True, anchor="center")
        return
    if active:
        base = color[:3] if color is not None else (0, 196, 236)
        pygame.draw.polygon(surf, (*base, 235), pts)
        pygame.draw.polygon(surf, (*accent_for(base), 255), pts, 1)
        glow(surf, r, accent_for(base), 2, cut)
        dark = sum(base) > 360
        fonts.blit(surf, label, r.center, size, (4, 16, 26) if dark else TEXT, bold=True, anchor="center")
        return
    if color is not None:
        base = color[:3]
        acc = accent_for(base)
        pygame.draw.polygon(surf, (*base, 225 if hov else 200), pts)
        pygame.draw.polygon(surf, (*acc, 255 if hov else 170), pts, 1)
        if hov:
            glow(surf, r, acc, 2, cut)
        fonts.blit(surf, label, r.center, size, TEXT, bold=True, anchor="center")
        return
    pygame.draw.polygon(surf, (0, 70, 100, 225) if hov else (6, 26, 40, 205), pts)
    pygame.draw.polygon(surf, (*CYAN, 255 if hov else 120), pts, 1)
    if hov:
        glow(surf, r, CYAN, 2, cut)
        pygame.draw.line(surf, CYAN, (r.x + cut, r.bottom - 2), (r.right - cut - 2, r.bottom - 2), 2)
    fonts.blit(surf, label, r.center, size, (235, 250, 255) if hov else (196, 232, 246), bold=True, anchor="center")


def spaced(fonts, surf, text, pos, size, color, spacing=0.18, bold=True, anchor="topleft"):
    """Texto en mayúsculas con letras espaciadas (estilo de rótulo técnico)."""
    key = ("sp", text, size, color, spacing, bold)
    img = _cache.get(key)
    if img is None:
        f = fonts.get(size, bold, tech=True)                  # Orbitron
        text = fonts._tech_safe(f, text)
        gap = int(size * spacing)
        chars = [f.render(ch, True, color) for ch in text]
        # algunas fuentes dibujan las mayúsculas con tilde (Á, Ó…) más bajas: se alinean con la «O» normal
        ref = f.render("O", True, color).get_bounding_rect().bottom
        shifts = []
        for ch, c in zip(text, chars):
            sh = 0
            if ch in "ÁÉÍÓÚÜÑ":
                sh = c.get_bounding_rect().bottom - ref
            shifts.append(max(0, sh))
        pad = max(shifts, default=0)
        w = sum(c.get_width() for c in chars) + gap * max(0, len(chars) - 1)
        h = max((c.get_height() for c in chars), default=1) + pad
        img = pygame.Surface((max(1, w), h), pygame.SRCALPHA)
        x = 0
        for c, sh in zip(chars, shifts):
            img.blit(c, (x, pad - sh))
            x += c.get_width() + gap
        if len(_cache) > 400:
            _cache.clear()
        _cache[key] = img
    rr = img.get_rect(**{anchor: (int(pos[0]), int(pos[1]))})
    surf.blit(img, rr)
    return rr


def glow_title(fonts, surf, text, pos, size, color=TEXT, glow_col=CYAN):
    """Título con halo de neón: el texto en cian, translúcido y desplazado, y encima el texto claro."""
    key = ("halo", text, size, glow_col)
    halo = _cache.get(key)
    if halo is None:
        tmp = pygame.Surface((1, 1), pygame.SRCALPHA)
        r = spaced(fonts, tmp, text, (0, 0), size, glow_col, 0.12)
        img = _cache[("sp", text, size, glow_col, 0.12, True)].copy()
        img.set_alpha(60)
        halo = img
        _cache[key] = halo
    for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-3, -1), (3, 1)):
        surf.blit(halo, (pos[0] + dx, pos[1] + dy))
    return spaced(fonts, surf, text, pos, size, color, 0.12)


def ring(surf, center, radius, frac, color, width=8, track=(30, 50, 66)):
    """Anillo de progreso (frac 0..1) empezando arriba, en sentido horario."""
    cx, cy = center
    rect = pygame.Rect(0, 0, radius * 2, radius * 2)
    rect.center = (int(cx), int(cy))
    pygame.draw.circle(surf, (*track, 200), rect.center, radius, width)
    frac = max(0.0, min(1.0, frac))
    if frac > 0.002:
        a0 = math.pi / 2 - 2 * math.pi * frac
        a1 = math.pi / 2
        for k in range(width):
            rr = rect.inflate(-k * 2 + width // 2, -k * 2 + width // 2)
            pygame.draw.arc(surf, color, rr, a0, a1, 2)
        # cabeza brillante
        ang = math.pi / 2 - 2 * math.pi * frac
        hx = cx + math.cos(ang) * (radius - width / 2)
        hy = cy - math.sin(ang) * (radius - width / 2)
        pygame.draw.circle(surf, (255, 255, 255), (int(hx), int(hy)), max(2, width // 3))
    # marcas cada 10 %
    for i in range(20):
        ang = math.pi / 2 - 2 * math.pi * i / 20
        r0 = radius + 4
        r1 = radius + (9 if i % 5 == 0 else 6)
        pygame.draw.line(surf, (*CYAN_DIM, 160), (cx + math.cos(ang) * r0, cy - math.sin(ang) * r0),
                         (cx + math.cos(ang) * r1, cy - math.sin(ang) * r1), 1)


def spinner(surf, center, radius, t, color=CYAN):
    cx, cy = center
    rect = pygame.Rect(0, 0, radius * 2, radius * 2)
    rect.center = (int(cx), int(cy))
    pygame.draw.circle(surf, (*CYAN_DIM, 70), rect.center, radius, 1)
    for k, (speed, span, w) in enumerate(((2.2, 1.6, 4), (-1.3, 0.9, 2))):
        a0 = t * speed + k
        rr = rect.inflate(-k * 22, -k * 22)
        pygame.draw.arc(surf, color, rr, a0, a0 + span, w)


def hud_backdrop(surf, W, H, t, left_w=None):
    """Capa de fondo de los menús: viñeta, rejilla técnica y una línea de barrido que baja despacio."""
    key = ("bd", W, H, left_w)
    base = _cache.get(key)
    if base is None:
        base = pygame.Surface((W, H), pygame.SRCALPHA)
        # degradado oscuro a la izquierda (zona de los botones) y viñeta abajo, cada uno en su capa y mezclados
        lw = left_w or int(W * 0.32)
        left = pygame.Surface((W, H), pygame.SRCALPHA)
        for x in range(lw):
            a = int(215 * (1 - x / lw) ** 0.55)
            pygame.draw.line(left, (3, 9, 18, a), (x, 0), (x, H))
        bottom = pygame.Surface((W, H), pygame.SRCALPHA)
        for y in range(H // 3):
            a = int(150 * (y / (H / 3)) ** 2)
            pygame.draw.line(bottom, (3, 9, 18, a), (0, H - H // 3 + y), (W, H - H // 3 + y))
        base.blit(left, (0, 0))
        base.blit(bottom, (0, 0))
        # rejilla en su propia capa, mezclada encima (dibujarla directamente reemplazaría la viñeta)
        grid = pygame.Surface((W, H), pygame.SRCALPHA)
        step = 48
        for x in range(0, W, step):
            pygame.draw.line(grid, (0, 200, 255, 16), (x, 0), (x, H))
        for y in range(0, H, step):
            pygame.draw.line(grid, (0, 200, 255, 16), (0, y), (W, y))
        for x in range(0, W, step * 4):
            for y in range(0, H, step * 4):
                pygame.draw.line(grid, (0, 220, 255, 70), (x - 4, y), (x + 4, y))
                pygame.draw.line(grid, (0, 220, 255, 70), (x, y - 4), (x, y + 4))
        base.blit(grid, (0, 0))
        _cache[key] = base
    surf.blit(base, (0, 0))
    # barrido
    y = int((t * 60) % (H + 200)) - 100
    band = _cache.get(("band", W))
    if band is None:
        band = pygame.Surface((W, 90), pygame.SRCALPHA)
        for i in range(90):
            a = int(22 * math.sin(math.pi * i / 90) ** 2)
            pygame.draw.line(band, (0, 220, 255, a), (0, i), (W, i))
        _cache[("band", W)] = band
    surf.blit(band, (0, y))
    pygame.draw.line(surf, (0, 230, 255, 70), (0, y + 45), (W, y + 45))


def radar(surf, fonts, center, radius, t, blips=()):
    """Radar con barrido giratorio y ecos (lista de (ángulo_grados, distancia 0..1, etiqueta))."""
    cx, cy = center
    disc = pygame.Surface((radius * 2 + 4, radius * 2 + 4), pygame.SRCALPHA)
    c = (radius + 2, radius + 2)
    pygame.draw.circle(disc, (2, 16, 24, 170), c, radius)
    for k in (1.0, 0.66, 0.33):
        pygame.draw.circle(disc, (0, 200, 255, 70 if k < 1 else 140), c, int(radius * k), 1)
    pygame.draw.line(disc, (0, 200, 255, 50), (c[0] - radius, c[1]), (c[0] + radius, c[1]))
    pygame.draw.line(disc, (0, 200, 255, 50), (c[0], c[1] - radius), (c[0], c[1] + radius))
    ang = (t * 1.1) % (2 * math.pi)
    for i in range(28):
        a = ang - i * 0.035
        pygame.draw.line(disc, (0, 230, 255, max(0, 120 - i * 5)), c,
                         (c[0] + math.cos(a) * radius, c[1] + math.sin(a) * radius), 2)
    surf.blit(disc, (cx - radius - 2, cy - radius - 2))
    for deg, d, lab in blips:
        a = math.radians(deg - 90)
        x = cx + math.cos(a) * radius * d
        y = cy + math.sin(a) * radius * d
        diff = (ang - a) % (2 * math.pi)
        alpha = int(255 * max(0.25, 1 - diff / (2 * math.pi)))
        pygame.draw.circle(surf, (*TEAL, alpha), (int(x), int(y)), 3)
        if lab:
            fonts.blit(surf, lab, (x + 6, y - 6), 10, (*TEAL[:3],), bold=True)


def blink(period=1.0):
    return (time.time() % period) < period * 0.6


def icon(surf, kind, center, size=16, color=CYAN, width=2):
    """Iconos de línea sencillos: lista, emergencia, peso, plan (ruta), lección, radio, motor."""
    cx, cy = int(center[0]), int(center[1])
    h = size / 2
    if kind == "lista":            # tablilla con marca de verificación
        r = pygame.Rect(0, 0, size * 0.8, size)
        r.center = (cx, cy)
        pygame.draw.rect(surf, color, r, width, border_radius=2)
        pygame.draw.line(surf, color, (r.centerx - 3, r.y), (r.centerx + 3, r.y), width + 1)
        pygame.draw.lines(surf, color, False, [(r.x + 3, cy), (cx - 1, cy + h * 0.45), (r.right - 3, cy - h * 0.4)], width)
    elif kind == "emergencia":     # triángulo con exclamación
        pts = [(cx, cy - h), (cx + h, cy + h * 0.85), (cx - h, cy + h * 0.85)]
        pygame.draw.polygon(surf, color, pts, width)
        pygame.draw.line(surf, color, (cx, cy - h * 0.35), (cx, cy + h * 0.25), width)
        pygame.draw.circle(surf, color, (cx, int(cy + h * 0.55)), max(1, width - 1))
    elif kind == "peso":           # balanza
        pygame.draw.line(surf, color, (cx, cy - h), (cx, cy + h * 0.8), width)
        pygame.draw.line(surf, color, (cx - h, cy - h * 0.5), (cx + h, cy - h * 0.5), width)
        pygame.draw.line(surf, color, (cx - h * 0.5, cy + h * 0.8), (cx + h * 0.5, cy + h * 0.8), width)
        for sx in (-1, 1):
            x = cx + sx * h * 0.8
            pygame.draw.arc(surf, color, (x - h * 0.4, cy - h * 0.3, h * 0.8, h * 0.6), math.pi, 2 * math.pi, width)
    elif kind == "plan":           # ruta con puntos
        pts = [(cx - h, cy + h * 0.6), (cx - h * 0.2, cy - h * 0.2), (cx + h * 0.3, cy + h * 0.3), (cx + h, cy - h * 0.7)]
        pygame.draw.lines(surf, color, False, pts, width)
        for p in (pts[0], pts[-1]):
            pygame.draw.circle(surf, color, (int(p[0]), int(p[1])), width + 1)
    elif kind == "leccion":        # estrella
        pts = []
        for k in range(10):
            rr = h if k % 2 == 0 else h * 0.45
            a = -math.pi / 2 + k * math.pi / 5
            pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
        pygame.draw.polygon(surf, color, pts, width)
    elif kind == "radio":          # antena con ondas
        pygame.draw.line(surf, color, (cx, cy - h * 0.2), (cx, cy + h), width)
        pygame.draw.circle(surf, color, (cx, int(cy - h * 0.3)), max(2, width))
        for k in (0.55, 0.95):
            rr = pygame.Rect(0, 0, h * 2 * k, h * 2 * k)
            rr.center = (cx, int(cy - h * 0.3))
            pygame.draw.arc(surf, color, rr, -0.7, 0.7, width)
            pygame.draw.arc(surf, color, rr, math.pi - 0.7, math.pi + 0.7, width)
    else:                          # punto
        pygame.draw.circle(surf, color, (cx, cy), int(h * 0.6), width)
