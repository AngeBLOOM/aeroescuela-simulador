"""Convierte las imágenes hechas con IA (Gemini) al formato que usa el simulador.

    python tools/importar_imagenes.py nubes  "ruta/nube.jpg" [más nubes…]
    python tools/importar_imagenes.py textura "ruta/asfalto.jpg" asfalto.png
    python tools/importar_imagenes.py foto    "ruta/avion.jpg"   avion_da40.png

- nubes: nube sobre fondo negro → PNG con transparencia (nube_1..3). Si hay menos de tres,
  las que faltan se crean volteando y aplanando las que hay.
- textura: foto cenital → textura repetible sin costuras (mezcla con su copia desplazada).
- foto: se copia como PNG.
"""
import os
import sys

import numpy as np
import pygame

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


def load(path):
    img = pygame.image.load(path)
    return pygame.surfarray.array3d(img).transpose(1, 0, 2).astype(np.float32) / 255.0


def save(arr, name, alpha=None):
    h, w = arr.shape[:2]
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.surfarray.pixels3d(surf)[...] = (np.clip(arr, 0, 1) * 255).astype(np.uint8).transpose(1, 0, 2)
    pygame.surfarray.pixels_alpha(surf)[...] = (255 if alpha is None else (np.clip(alpha, 0, 1) * 255).astype(np.uint8).T)
    pygame.image.save(surf, os.path.join(ASSETS, name))
    print("guardado", name, (w, h))


def resize(arr, w, h):
    surf = pygame.Surface((arr.shape[1], arr.shape[0]))
    pygame.surfarray.pixels3d(surf)[...] = (np.clip(arr, 0, 1) * 255).astype(np.uint8).transpose(1, 0, 2)
    surf = pygame.transform.smoothscale(surf, (w, h))
    return pygame.surfarray.array3d(surf).transpose(1, 0, 2).astype(np.float32) / 255.0


def cloud_alpha(rgb):
    """Nube sobre negro: alfa a partir de la luminancia y color sin premultiplicar."""
    lum = rgb @ np.array([0.3, 0.59, 0.11], np.float32)
    # la base gris de la nube es opaca: la densidad se estima con la luminancia suavizada del entorno
    h, w = lum.shape
    dens = resize(resize(np.repeat(lum[..., None], 3, axis=2), w // 24, h // 24), w, h)[..., 0]
    inside = np.clip((lum - 0.07) / 0.18, 0, 1)                   # solo donde ya hay nube (no en el fondo negro)
    a = np.clip((np.maximum(lum, dens * 1.7 * inside) - 0.03) / 0.4, 0, 1)
    # color: cada píxel normalizado por su propia luminancia (el borde oscuro del recorte se aclara)
    a_lum = np.clip((lum - 0.02) / 0.55, 0, 1)
    col = np.clip(rgb / np.maximum(a_lum[..., None], 0.05), 0, 1)
    k = np.sqrt(a_lum)[..., None]
    col = col * k + np.array([0.8, 0.82, 0.86]) * (1 - k)
    return col, a


def nubes(paths, size=512):
    imgs = []
    for p in paths:
        rgb = load(p)
        s = min(rgb.shape[:2])
        rgb = rgb[(rgb.shape[0] - s) // 2:(rgb.shape[0] - s) // 2 + s, (rgb.shape[1] - s) // 2:(rgb.shape[1] - s) // 2 + s]
        imgs.append(resize(rgb, size, size))
    base = list(imgs)
    k = 0
    while len(imgs) < 3:
        src = base[k % len(base)]
        if len(imgs) == 1 or k % 2 == 0:
            v = src[:, ::-1]                                    # espejo
        else:
            flat = resize(src[:, ::-1], size, int(size * 0.62))  # más ancha y aplanada
            v = np.zeros_like(src)
            v[size - flat.shape[0] - int(size * 0.12):size - int(size * 0.12)] = flat
        imgs.append(v)
        k += 1
    for i, rgb in enumerate(imgs[:3]):
        col, a = cloud_alpha(rgb)
        save(col, f"nube_{i + 1}.png", a)


def textura(path, name, size=1024, contrast=1.0):
    if name.startswith("tela"):
        size = 512
    rgb = load(path)
    s = min(rgb.shape[:2])
    rgb = resize(rgb[:s, :s], size, size)
    # igualar la luz de un lado a otro (las fotos suelen tener viñeteado)
    blur = resize(resize(rgb, 8, 8), size, size)
    rgb = rgb / np.maximum(blur, 0.02) * blur.mean(axis=(0, 1))
    shifted = np.roll(rgb, (size // 2, size // 2), axis=(0, 1))
    t = np.linspace(-1, 1, size)
    d = np.maximum(np.abs(t)[:, None], np.abs(t)[None, :])       # 0 en el centro, 1 en el borde
    w = np.clip((0.92 - d) / 0.3, 0, 1)
    w = w * w * (3 - 2 * w)
    out = rgb * w[..., None] + shifted * (1 - w[..., None])
    m = out.mean(axis=(0, 1))
    out = m + (out - m) * contrast                                  # menos contraste = menos repetición visible
    save(out, name)


def chroma(rgb):
    """Alfa por verde croma, con borde suavizado y sin reflejo verde."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    green = np.clip((g - np.maximum(r, b) - 0.12) / 0.25, 0, 1)
    a = 1 - green
    spill = (g > np.maximum(r, b)) & (a > 0)
    out = rgb.copy()
    out[..., 1] = np.where(spill, np.maximum(r, b), g)
    return out, a


def recorte(path, name, w, h):
    """Objeto sobre verde croma → PNG transparente recortado a su contorno y escalado a w×h."""
    rgb, a = chroma(load(path))
    ys, xs = np.nonzero(a > 0.5)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    rgb, a = rgb[y0:y1, x0:x1], a[y0:y1, x0:x1]
    rgb = resize(rgb, w, h)
    a = resize(np.repeat(a[..., None], 3, axis=2), w, h)[..., 0]
    save(rgb, name, a)


def bisel(path, name, size=512):
    """Aro de instrumento: se conserva solo el aro (sin la placa cuadrada) para que encaje con
    cualquier separación entre relojes. El hueco queda al 79 % del radio de la imagen."""
    rgb, a = chroma(load(path))
    H, W = a.shape
    hole = (a < 0.5)
    cy, cx = H // 2, W // 2
    # radio del hueco medido en las cuatro direcciones desde el centro
    rads = []
    for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        k = 0
        while 0 <= cy + dy * k < H and 0 <= cx + dx * k < W and hole[cy + dy * k, cx + dx * k]:
            k += 1
        rads.append(k)
    hr = float(np.median(rads))
    half = hr / 0.79
    crop = int(half)
    rgb = rgb[cy - crop:cy + crop, cx - crop:cx + crop]
    a = a[cy - crop:cy + crop, cx - crop:cx + crop]
    yy, xx = np.mgrid[-crop:crop, -crop:crop]
    d = np.hypot(yy, xx) / crop
    a = a * np.clip((0.93 - d) / 0.02, 0, 1)                     # fuera del aro, transparente
    rgb = resize(rgb, size, size)
    a = resize(np.repeat(a[..., None], 3, axis=2), size, size)[..., 0]
    save(rgb, name, a)


def croma(path, name):
    """Foto con zonas verde croma (ventanas) → PNG con esas zonas transparentes, mismo tamaño."""
    rgb, a = chroma(load(path))
    save(rgb, name, a)


def foto(path, name):
    rgb = load(path)
    save(rgb, name)


if __name__ == "__main__":
    pygame.init()
    kind = sys.argv[1]
    if kind == "nubes":
        nubes(sys.argv[2:])
    elif kind == "textura":
        textura(sys.argv[2], sys.argv[3], contrast=float(sys.argv[4]) if len(sys.argv) > 4 else 1.0)
    elif kind == "recorte":
        recorte(sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5]))
    elif kind == "bisel":
        bisel(sys.argv[2], sys.argv[3])
    elif kind == "croma":
        croma(sys.argv[2], sys.argv[3])
    elif kind == "foto":
        foto(sys.argv[2], sys.argv[3])
