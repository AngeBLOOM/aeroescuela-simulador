"""Carga de las texturas de la carpeta assets/ (con caché y escalado)."""
import os
import sys

import pygame

if getattr(sys, "frozen", False):
    BASE = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)), "assets")
else:
    BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
_cache = {}
_scaled = {}


def path(name):
    return os.path.join(BASE, name)


def image(name):
    """Devuelve la imagen o None si no existe (el simulador sigue funcionando sin ella)."""
    if name not in _cache:
        try:
            _cache[name] = pygame.image.load(path(name))
        except Exception:
            _cache[name] = None
    return _cache[name]


def scaled(name, size):
    size = (max(1, int(size[0])), max(1, int(size[1])))
    key = (name, size)
    s = _scaled.get(key)
    if s is None:
        img = image(name)
        if img is None:
            return None
        s = _fast(pygame.transform.smoothscale(img, size))
        if len(_scaled) > 400:
            _scaled.clear()
        _scaled[key] = s
    return s


def _fast(s):
    """Convierte al formato de píxel más rápido para blit (si hay modo de vídeo)."""
    try:
        return s.convert_alpha()
    except Exception:
        return s


def hole_insets(name):
    """Márgenes (izq, arriba, der, abajo) del hueco transparente central de un marco."""
    key = ("hole", name)
    if key in _scaled:
        return _scaled[key]
    img = image(name)
    res = None
    if img is not None:
        import numpy as np
        a = pygame.surfarray.array_alpha(img).T
        H, W = a.shape
        cy, cx = H // 2, W // 2
        if a[cy, cx] < 64:
            row, col = a[cy] >= 128, a[:, cx] >= 128
            left = int(np.flatnonzero(row[:cx])[-1]) + 1 if row[:cx].any() else 0
            right = W - (cx + int(np.flatnonzero(row[cx:])[0])) if row[cx:].any() else 0
            top = int(np.flatnonzero(col[:cy])[-1]) + 1 if col[:cy].any() else 0
            bot = H - (cy + int(np.flatnonzero(col[cy:])[0])) if col[cy:].any() else 0
            res = (left, top, right, bot)
    _scaled[key] = res
    return res


def nine_slice(name, size, insets, border_scale):
    """Escala una imagen de marco manteniendo el grosor de los bordes (9 porciones).

    insets = (izq, arriba, der, abajo) en píxeles de la imagen original."""
    key = ("9", name, (int(size[0]), int(size[1])), insets, round(border_scale, 3))
    s = _scaled.get(key)
    if s is not None:
        return s
    img = image(name)
    if img is None:
        return None
    W, H = img.get_size()
    l, t, r, b = insets
    tw, th = int(size[0]), int(size[1])
    L, T, R, B = (int(v * border_scale) for v in insets)
    out = pygame.Surface((tw, th), pygame.SRCALPHA)
    xs_src = [0, l, W - r, W]
    ys_src = [0, t, H - b, H]
    xs_dst = [0, L, tw - R, tw]
    ys_dst = [0, T, th - B, th]
    for i in range(3):
        for j in range(3):
            sw, sh = xs_src[i + 1] - xs_src[i], ys_src[j + 1] - ys_src[j]
            dw, dh = xs_dst[i + 1] - xs_dst[i], ys_dst[j + 1] - ys_dst[j]
            if sw <= 0 or sh <= 0 or dw <= 0 or dh <= 0:
                continue
            part = img.subsurface((xs_src[i], ys_src[j], sw, sh))
            out.blit(pygame.transform.smoothscale(part, (dw, dh)), (xs_dst[i], ys_dst[j]))
    out = _fast(out)
    _scaled[key] = out
    return out


def tiled(name, size, tile):
    """Superficie de 'size' cubierta con la textura repetida a 'tile' píxeles."""
    t = scaled(name, (tile, tile))
    if t is None:
        return None
    w, h = int(size[0]), int(size[1])
    out = pygame.Surface((w, h))
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            out.blit(t, (x, y))
    return out
