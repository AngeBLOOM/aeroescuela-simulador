"""Texturas procedurales: ruido de detalle, pistas con señalización OACI y nubes."""
import numpy as np
import pygame


def _value_noise(size, res, rng):
    """Ruido de valor periódico (enlosable)."""
    g = rng.random((res, res))
    u = np.arange(size) * res / size
    i0 = np.floor(u).astype(int)
    f = u - i0
    f = f * f * (3 - 2 * f)
    i1 = (i0 + 1) % res
    a = g[np.ix_(i0, i0)]
    b = g[np.ix_(i1, i0)]
    c = g[np.ix_(i0, i1)]
    d = g[np.ix_(i1, i1)]
    fi = f[:, None]
    fj = f[None, :]
    return a * (1 - fi) * (1 - fj) + b * fi * (1 - fj) + c * (1 - fi) * fj + d * fi * fj


def spectral_noise(size, beta, rng, fmin=1.0):
    """Ruido fractal isótropo y enlosable por síntesis espectral (FFT)."""
    white = rng.normal(size=(size, size))
    F = np.fft.fft2(white)
    fx = np.fft.fftfreq(size) * size
    f = np.sqrt(fx[:, None] ** 2 + fx[None, :] ** 2)
    f[0, 0] = 1.0
    F *= 1.0 / np.maximum(f, fmin) ** (beta / 2.0)
    F[0, 0] = 0.0
    n = np.real(np.fft.ifft2(F))
    n = (n - n.mean()) / (n.std() * 4.0) + 0.5
    return np.clip(n, 0.0, 1.0)


def detail_noise(size=512, seed=11):
    rng = np.random.default_rng(seed)
    chans = [spectral_noise(size, 2.0, rng, 2.0), spectral_noise(size, 2.4, rng, 1.5),
             spectral_noise(size, 1.6, rng, 3.0)]
    img = np.stack(chans + [np.ones_like(chans[0])], axis=-1)
    return (img * 255).astype(np.uint8)


def cloud_puff(size=128, seed=5):
    """Bocanada de cúmulo: borde irregular tipo coliflor y base algo plana."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:size, 0:size] / (size - 1) * 2 - 1
    yy = np.where(y > 0.25, (y - 0.25) * 2.2 + 0.25, y)      # base más plana (abajo = +y)
    r = np.sqrt(x * x + yy * yy)
    n = np.zeros((size, size))
    amp = 1.0
    tot = 0.0
    for res in (3, 6, 12, 24, 48):
        n += _value_noise(size, res, rng) * amp
        tot += amp
        amp *= 0.55
    n /= tot
    a = (1.0 - r) * 1.25 + (n - 0.5) * 1.1
    a = np.clip(a * 2.2, 0, 1) ** 1.2
    a *= np.clip((1.0 - r) * 3.0, 0, 1)
    img = np.stack([a, a, a, a], axis=-1)
    return (img * 255).astype(np.uint8)


def cloud_deck(size=256, seed=8):
    rng = np.random.default_rng(seed)
    n = np.zeros((size, size))
    amp = 1.0
    tot = 0.0
    for res in (4, 8, 16, 32, 64):
        n += _value_noise(size, res, rng) * amp
        tot += amp
        amp *= 0.55
    n /= tot
    n = (n - n.min()) / (n.max() - n.min())
    c = 0.78 + 0.22 * n
    a = np.clip(0.8 + 0.4 * n, 0, 1)
    img = np.stack([c, c, c * 1.01, a], axis=-1)
    return (np.clip(img, 0, 1) * 255).astype(np.uint8)


def _font(size, bold=True):
    pygame.font.init()
    for name in ("arialblack", "arial", "segoeui", "dejavusans"):
        try:
            f = pygame.font.SysFont(name, size, bold=bold)
            if f:
                return f
        except Exception:
            pass
    return pygame.font.Font(None, size)


def runway_end_texture(number, width_m, ppm_w=8.5, length_m=420.0, ppm_l=5.0, tdz=True):
    """Textura del extremo de pista (umbral, número, zona de toma y punto de visada).

    La fila inferior de la imagen corresponde al umbral; se sube volteada.
    """
    W = int(width_m * ppm_w)
    H = int(length_m * ppm_l)
    surf = pygame.Surface((W, H))
    surf.fill((58, 58, 60))
    white = (232, 232, 228)

    def ry(m):           # metros desde el umbral -> fila de imagen
        return H - int(m * ppm_l)

    def rx(m):           # metros desde el borde izquierdo
        return int(m * ppm_w)
    # bandas de borde laterales
    pygame.draw.rect(surf, white, (rx(0.3), 0, max(2, rx(0.9)), H))
    pygame.draw.rect(surf, white, (W - rx(0.3) - max(2, rx(0.9)), 0, max(2, rx(0.9)), H))
    # marcas de umbral (teclas de piano): dos grupos con hueco central
    nb = 4 if width_m >= 30 else 3
    sw, sg = 1.8, 1.2
    cx = width_m / 2
    for i in range(nb):
        off = 1.8 + i * (sw + sg)
        for xm in (cx - off - sw, cx + off):
            pygame.draw.rect(surf, white, (rx(xm), ry(36), rx(sw), int(30 * ppm_l)))
    # número de pista
    f = _font(220)
    digits = "".join(ch for ch in number if ch.isdigit()) or number
    letter = "".join(ch for ch in number if not ch.isdigit())
    tw = rx(min(width_m * 0.5, 16.0))
    th = int(18 * ppm_l)
    base = 62
    if letter:
        lt = pygame.transform.smoothscale(f.render(letter, True, white), (int(tw * 0.45), th))
        surf.blit(lt, ((W - lt.get_width()) // 2, ry(base)))
        base += 24
    txt = pygame.transform.smoothscale(f.render(digits, True, white), (tw, th))
    surf.blit(txt, ((W - tw) // 2, ry(base)))
    # eje
    for m in range(80, int(length_m), 50):
        pygame.draw.rect(surf, white, (W // 2 - rx(0.45), ry(m + 30), rx(0.9), int(30 * ppm_l)))
    if tdz:
        # punto de visada a 300 m
        pygame.draw.rect(surf, white, (rx(width_m * 0.5 - 7.0), ry(345), rx(3.0), int(45 * ppm_l)))
        pygame.draw.rect(surf, white, (rx(width_m * 0.5 + 4.0), ry(345), rx(3.0), int(45 * ppm_l)))
        # zona de toma de contacto
        for m, n in ((150, 3), (450, 2)):
            if m + 22 > length_m:
                continue
            for k in range(n):
                off = 9.0 + k * 1.6
                pygame.draw.rect(surf, white, (rx(width_m * 0.5 - off - 1.0), ry(m + 22), rx(1.0), int(22 * ppm_l)))
                pygame.draw.rect(surf, white, (rx(width_m * 0.5 + off), ry(m + 22), rx(1.0), int(22 * ppm_l)))
    # marcas de neumáticos en la zona de toma
    rng = np.random.default_rng(len(number))
    arr = pygame.surfarray.pixels3d(surf)
    yy0, yy1 = ry(500), ry(120)
    for _ in range(140):
        x0 = int(W / 2 + rng.normal(0, W * 0.09))
        y0 = rng.integers(yy0, yy1)
        ln = rng.integers(20, 200)
        x0 = int(np.clip(x0, 2, W - 10))
        arr[x0:x0 + 6, y0:min(H, y0 + ln)] = (arr[x0:x0 + 6, y0:min(H, y0 + ln)] * 0.8).astype(np.uint8)
    del arr
    return surf


def taxiway_texture():
    """Calles de rodaje y plataformas: asfalto algo más claro y gastado que la pista (el detalle lo pone la textura
    de asfalto del shader)."""
    surf = pygame.Surface((16, 16))
    surf.fill((66, 66, 67))
    return surf


def runway_mid_texture(width_m, ppm_w=8.5, length_m=50.0, ppm_l=5.0):
    W = int(width_m * ppm_w)
    H = int(length_m * ppm_l)
    surf = pygame.Surface((W, H))
    surf.fill((60, 60, 62))
    white = (232, 232, 228)
    pygame.draw.rect(surf, white, (int(0.3 * ppm_w), 0, max(2, int(0.9 * ppm_w)), H))
    pygame.draw.rect(surf, white, (W - int(1.2 * ppm_w), 0, max(2, int(0.9 * ppm_w)), H))
    pygame.draw.rect(surf, white, (W // 2 - int(0.45 * ppm_w), 0, int(0.9 * ppm_w), int(30 * ppm_l)))
    return surf


def taxi_texture():
    W, H = 64, 128
    surf = pygame.Surface((W, H))
    surf.fill((70, 70, 72))
    pygame.draw.rect(surf, (225, 190, 40), (W // 2 - 2, 0, 4, H))
    return surf


def apron_texture():
    W, H = 256, 256
    surf = pygame.Surface((W, H))
    surf.fill((86, 86, 88))
    for k in range(0, W, 64):
        pygame.draw.line(surf, (78, 78, 80), (k, 0), (k, H), 2)
        pygame.draw.line(surf, (78, 78, 80), (0, k), (W, k), 2)
    pygame.draw.line(surf, (225, 190, 40), (0, H // 2), (W, H // 2), 3)
    return surf


def surface_rgba(surf, flip=True):
    return pygame.image.tobytes(surf, "RGBA", flip)
