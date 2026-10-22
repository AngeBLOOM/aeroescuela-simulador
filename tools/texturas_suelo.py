"""Prepara las texturas fotográficas del suelo (asfalto de pista, concreto de plataforma y pasto) a partir de
escaneos PBR de uso libre (CC0) y las deja en assets/.

Fuentes (todas CC0, ver assets/CREDITOS_TEXTURAS.md):
  asfalto  -> Poly Haven «Asphalt Pit Lane»   (asphalt_pit_lane_diff_2k.jpg, asphalt_pit_lane_nor_gl_2k.jpg)
  concreto -> Poly Haven «Concrete Floor 02»  (concrete_floor_02_diff_2k.jpg, concrete_floor_02_nor_gl_2k.jpg)
  pasto    -> ambientCG «Grass004»            (Grass004_2K-JPG_Color.jpg, Grass004_2K-JPG_NormalGL.jpg)

Uso:  python tools/texturas_suelo.py <carpeta con los archivos descargados>

Para que no se note la repetición al rodar, al color se le quitan las manchas grandes (iluminación y suciedad de
escala mayor que ~1/6 del cuadro): el simulador pone la variación grande con su propio ruido. El color queda en
2048 px y el relieve (mapa de normales, convención OpenGL) en 1024 px, para no gastar memoria de la GT 610.
"""
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "..", "assets")

SETS = {
    "asfalto_pista": ("asphalt_pit_lane_diff_2k.jpg", "asphalt_pit_lane_nor_gl_2k.jpg", 0.8),
    "concreto": ("concrete_floor_02_diff_2k.jpg", "concrete_floor_02_nor_gl_2k.jpg", 0.7),
    "pasto": ("Grass004_2K-JPG_Color.jpg", "Grass004_2K-JPG_NormalGL.jpg", 0.6),
}


def _blur_wrap(a, sigma):
    """Desenfoque gaussiano periódico (la textura es enlosable) por FFT."""
    h, w = a.shape
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.fftfreq(w)[None, :]
    g = np.exp(-2.0 * (np.pi * sigma) ** 2 * (fx ** 2 + fy ** 2))
    return np.real(np.fft.ifft2(np.fft.fft2(a) * g))


def flatten(rgb, strength):
    """Quita la variación de brillo de baja frecuencia conservando el detalle fino y el color."""
    lin = (rgb / 255.0) ** 2.2
    lum = lin @ np.array([0.2126, 0.7152, 0.0722])
    low = np.maximum(_blur_wrap(lum, rgb.shape[0] / 6.0), 1e-4)
    k = (lum.mean() / low) ** strength
    out = np.clip(lin * k[..., None], 0.0, 1.0) ** (1 / 2.2)
    return (out * 255.0 + 0.5).astype(np.uint8)


def main(src):
    for name, (diff, nor, strength) in SETS.items():
        c = np.asarray(Image.open(os.path.join(src, diff)).convert("RGB").resize((2048, 2048), Image.LANCZOS),
                       np.float64)
        Image.fromarray(flatten(c, strength)).save(os.path.join(ASSETS, name + ".jpg"), quality=88, optimize=True)
        n = np.asarray(Image.open(os.path.join(src, nor)).convert("RGB").resize((1024, 1024), Image.LANCZOS),
                       np.float64) / 127.5 - 1.0
        n /= np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-6)
        n = ((n * 0.5 + 0.5) * 255.0 + 0.5).astype(np.uint8)
        Image.fromarray(n).save(os.path.join(ASSETS, name + "_n.jpg"), quality=92, optimize=True)
        print(name, "listo")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
