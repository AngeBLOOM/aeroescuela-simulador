"""Terreno procedural: mapa de alturas, colores y consultas para la física."""
import math

import numpy as np

from .mathx import smoothstep

WATER_LEVEL = 0.0
MICRO_TILE = 256                # ondulaciones finas del suelo: tabla periódica de 256 x 256 puntos…
MICRO_STEP = 10.0               # …cada 10 m (se repite cada 2,56 km)


def _micro_noise(seed=11):
    """Ruido periódico suave (longitudes de onda de ~40 a 600 m) entre -1 y 1, para las ondulaciones del suelo."""
    rng = np.random.default_rng(seed)
    w = rng.standard_normal((MICRO_TILE, MICRO_TILE))
    f = np.fft.fftfreq(MICRO_TILE, d=MICRO_STEP)
    fx, fy = np.meshgrid(f, f, indexing="ij")
    fr = np.hypot(fx, fy)
    filt = np.where(fr > 0, np.maximum(fr, 1.0 / 600.0) ** -1.5, 0.0) * np.exp(-(fr * 40.0) ** 2)
    out = np.real(np.fft.ifft2(np.fft.fft2(w) * filt))
    return np.clip(out / (2.5 * out.std()), -1.0, 1.0)


def _cr_weights(t):
    """Pesos de Catmull-Rom (curva suave que pasa por los puntos de la grilla)."""
    t2 = t * t
    t3 = t2 * t
    return ((-t3 + 2 * t2 - t) * 0.5, (3 * t3 - 5 * t2 + 2) * 0.5, (-3 * t3 + 4 * t2 + t) * 0.5, (t3 - t2) * 0.5)


def _smooth_upsample(coarse, n):
    res = coarse.shape[0] - 1
    u = np.linspace(0, res, n)
    i0 = np.minimum(np.floor(u).astype(int), res - 1)
    f = u - i0
    f = f * f * (3 - 2 * f)
    a = coarse[np.ix_(i0, i0)]
    b = coarse[np.ix_(i0 + 1, i0)]
    c = coarse[np.ix_(i0, i0 + 1)]
    d = coarse[np.ix_(i0 + 1, i0 + 1)]
    fi = f[:, None]
    fj = f[None, :]
    return (a * (1 - fi) * (1 - fj) + b * fi * (1 - fj) + c * (1 - fi) * fj + d * fi * fj)


def fbm(n, rng, octaves=(4, 8, 16, 32, 64, 128), gain=0.5):
    out = np.zeros((n, n))
    amp = 1.0
    tot = 0.0
    for res in octaves:
        out += _smooth_upsample(rng.random((res + 1, res + 1)), n) * amp
        tot += amp
        amp *= gain
    return out / tot


class Terrain:
    def __init__(self, airports, seed=7, n=513, cell=100.0, heights=None, sat=None, water=None):
        self.water = water              # (máscara 255 = agua, rect) de lagos y embalses reales
        self.n = n
        self.cell = cell
        self.half = (n - 1) * cell / 2.0
        self.airports = airports
        self.real = heights is not None
        rng = np.random.default_rng(seed)
        if heights is None:
            self.h = self._generate(rng).astype(np.float64)
            self.forest = None
            self.colors = self._colors(rng)
        else:
            h = np.array(heights, dtype=np.float64)
            X, Y = self.grid_xy()
            for ap in airports:
                for rw in ap.runways:
                    h = self._flatten_strip(h, X, Y, rw, ap.elev)
                site = ap.site_rect() if hasattr(ap, "site_rect") else None
                if site is not None:                 # plataforma, hangares y torre al nivel del aeródromo
                    h = self._flatten_rect(h, X, Y, site, ap.elev)
            self.h = h
            self.forest = np.zeros_like(h, dtype=bool)
            if sat is not None:
                k = sat.shape[0] / n
                idx = np.clip((np.arange(n) * k).astype(int), 0, sat.shape[0] - 1)
                self.colors = (sat[np.ix_(idx, idx)].astype(np.float32) / 255.0)
            else:
                self.colors = np.full((n, n, 3), 0.4, np.float32)
        self._micro = _micro_noise()
        self.amp = self._micro_amplitude()

    def _flatten_strip(self, h, X, Y, rw, elev):
        """Aplana solo la franja de pista (el relieve real no se altera)."""
        dx = X - rw.center[0]
        dy = Y - rw.center[1]
        along = np.abs(dx * rw.dir[0] + dy * rw.dir[1])
        lat = np.abs(dx * rw.right[0] + dy * rw.right[1])
        ea = np.clip(along - (rw.length / 2 + 120.0), 0, None)
        el = np.clip(lat - (rw.width / 2 + 60.0), 0, None)
        w = 1.0 - smoothstep(0.0, 350.0, np.sqrt(ea ** 2 + el ** 2))
        return h * (1 - w) + elev * w

    def _flatten_rect(self, h, X, Y, rect, elev):
        """Aplana un rectángulo (centro, rumbo, largo, ancho) con una orilla suave de 250 m."""
        (cx, cy), hdg, ln, wd = rect
        hr = math.radians(hdg)
        dx, dy = X - cx, Y - cy
        along = np.abs(dx * math.cos(hr) + dy * math.sin(hr))
        lat = np.abs(-dx * math.sin(hr) + dy * math.cos(hr))
        ea = np.clip(along - (ln / 2 + 60.0), 0, None)
        el = np.clip(lat - (wd / 2 + 60.0), 0, None)
        w = 1.0 - smoothstep(0.0, 250.0, np.sqrt(ea ** 2 + el ** 2))
        return h * (1 - w) + elev * w

    # ------------------------------------------------------------ generación
    def grid_xy(self):
        c = np.linspace(-self.half, self.half, self.n)
        X, Y = np.meshgrid(c, c, indexing="ij")    # X = norte (i), Y = este (j)
        return X, Y

    def _generate(self, rng):
        n = self.n
        X, Y = self.grid_xy()
        base = fbm(n, rng)
        base = (base - base.min()) / (base.max() - base.min())
        h = 90.0 + 420.0 * base ** 1.3

        # cordillera al noroeste
        ridged = 1.0 - np.abs(2.0 * fbm(n, rng, (6, 12, 24, 48, 96, 192), 0.55) - 1.0)
        ridged = ridged ** 2.2
        d2 = (X - 13000.0) ** 2 + (Y + 15000.0) ** 2
        wm = np.exp(-d2 / (2 * 8000.0 ** 2))
        h += wm * 2100.0 * ridged

        # costa y mar al este
        h -= np.clip(Y - 14000.0, 0, None) * 0.06
        # lago al suroeste del valle
        d2 = (X + 7500.0) ** 2 + (Y - 7000.0) ** 2
        h -= 420.0 * np.exp(-d2 / (2 * 2300.0 ** 2))

        # el escenario es una gran isla: los bordes bajan al mar
        edge = np.maximum(np.abs(X), np.abs(Y))
        h -= smoothstep(19500.0, 25000.0, edge) * 1100.0

        # aeródromos: aplanar y despejar corredores de aproximación
        for ap in self.airports:
            for rw in ap.runways:
                h = self._flatten_runway(h, X, Y, rw, ap.elev)
        return h

    def _flatten_runway(self, h, X, Y, rw, elev):
        dx = X - rw.center[0]
        dy = Y - rw.center[1]
        along = dx * rw.dir[0] + dy * rw.dir[1]
        lat = dx * rw.right[0] + dy * rw.right[1]
        # corredores de aproximación (pendiente máxima 4 %)
        beyond = np.clip(np.abs(along) - rw.length / 2 - 300.0, 0, None)
        cap = elev + 5.0 + beyond * 0.022
        wl = 1.0 - smoothstep(1200.0, 2600.0, np.abs(lat))
        wl = wl * (1.0 - smoothstep(14000.0, 16000.0, np.abs(along)))
        capped = np.minimum(h, cap)
        h = h * (1 - wl) + capped * wl
        # meseta del aeródromo
        ea = np.clip(np.abs(along) - (rw.length / 2 + 350.0), 0, None)
        el = np.clip(np.abs(lat) - 450.0, 0, None)
        dist = np.sqrt(ea ** 2 + el ** 2)
        w = 1.0 - smoothstep(0.0, 1500.0, dist)
        return h * (1 - w) + elev * w

    def _colors(self, rng):
        n = self.n
        h = self.h
        gx, gy = np.gradient(h, self.cell)
        slope = np.sqrt(gx * gx + gy * gy)
        X, Y = self.grid_xy()

        noise = fbm(n, rng, (8, 16, 32, 64), 0.6)
        forest_n = fbm(n, rng, (8, 16, 32, 64, 128), 0.55)

        # parcelas agrícolas: celdas de ~500 m con colores variados
        fx = np.floor((X + 0.18 * Y) / 520.0).astype(np.int64)
        fy = np.floor((Y - 0.12 * X) / 430.0).astype(np.int64)
        hsh = (fx * 73856093) ^ (fy * 19349663)
        hsh = (hsh % 7 + 7) % 7
        field_cols = np.array([
            [0.42, 0.50, 0.25], [0.33, 0.44, 0.21], [0.58, 0.54, 0.32],
            [0.48, 0.40, 0.29], [0.37, 0.48, 0.26], [0.60, 0.57, 0.38],
            [0.31, 0.39, 0.20]])
        col = field_cols[hsh]
        col = col * (0.85 + 0.3 * noise[..., None])

        grass = np.array([0.35, 0.44, 0.23])
        flatness = 1.0 - smoothstep(0.04, 0.12, slope)
        lowness = 1.0 - smoothstep(380.0, 700.0, h)
        fieldw = (flatness * lowness)[..., None]
        col = col * fieldw + grass[None, None, :] * (0.8 + 0.4 * noise[..., None]) * (1 - fieldw)

        # bosques
        forest = (forest_n > 0.55) & (h > 20) & (h < 1700)
        forest = forest | ((slope > 0.12) & (slope < 0.6) & (forest_n > 0.42) & (h < 1700))
        self.forest = forest
        fcol = np.array([0.17, 0.30, 0.13])
        col[forest] = fcol * (0.8 + 0.4 * noise[forest][:, None])

        # roca y nieve
        rock = smoothstep(0.45, 0.8, slope) * smoothstep(250.0, 600.0, h)
        rock = np.maximum(rock, smoothstep(1300.0, 1700.0, h))[..., None]
        rcol = np.array([0.47, 0.44, 0.40]) * (0.85 + 0.3 * noise[..., None])
        col = col * (1 - rock) + rcol * rock
        snow = smoothstep(1750.0, 1950.0, h + noise * 200.0)[..., None]
        col = col * (1 - snow) + np.array([0.93, 0.94, 0.97]) * snow

        # arena en orilla y fondo
        beach = (1.0 - smoothstep(4.0, 14.0, h))[..., None]
        col = col * (1 - beach) + np.array([0.72, 0.66, 0.50]) * beach

        # alrededores de aeródromos: césped cuidado
        for ap in self.airports:
            for rw in ap.runways:
                dx = X - rw.center[0]
                dy = Y - rw.center[1]
                along = np.abs(dx * rw.dir[0] + dy * rw.dir[1])
                lat = np.abs(dx * rw.right[0] + dy * rw.right[1])
                m = (along < rw.length / 2 + 250) & (lat < 320)
                col[m] = np.array([0.37, 0.47, 0.25]) * (0.9 + 0.2 * noise[m][:, None])
                self.forest[(along < rw.length / 2 + 900) & (lat < 600)] = False
        return np.clip(col, 0, 1).astype(np.float32)

    def _micro_amplitude(self):
        """Altura de las ondulaciones finas en cada punto de la grilla (m): más en las laderas, nada en los
        aeródromos (pistas, plataformas y sus alrededores) ni en el agua."""
        h = self.h
        gx, gy = np.gradient(h, self.cell)
        amp = np.clip(1.3 + 10.0 * np.sqrt(gx * gx + gy * gy), 0.0, 7.0)
        X, Y = self.grid_xy()
        for ap in self.airports:
            for rw in ap.runways:
                dx = X - rw.center[0]
                dy = Y - rw.center[1]
                ea = np.clip(np.abs(dx * rw.dir[0] + dy * rw.dir[1]) - (rw.length / 2 + 200.0), 0, None)
                el = np.clip(np.abs(dx * rw.right[0] + dy * rw.right[1]) - 220.0, 0, None)
                amp *= smoothstep(150.0, 900.0, np.sqrt(ea ** 2 + el ** 2))
            site = ap.site_rect() if hasattr(ap, "site_rect") else None
            if site is not None:                         # plataforma y hangares de un aeropuerto real
                (cx, cy), hdg, ln, wd = site
                hr = math.radians(hdg)
                dx, dy = X - cx, Y - cy
                ea = np.clip(np.abs(dx * math.cos(hr) + dy * math.sin(hr)) - ln / 2, 0, None)
                el = np.clip(np.abs(-dx * math.sin(hr) + dy * math.cos(hr)) - wd / 2, 0, None)
                amp *= smoothstep(100.0, 500.0, np.sqrt(ea ** 2 + el ** 2))
        amp *= smoothstep(3.0, 15.0, h)                          # costas y orillas lisas
        if self.water is not None:
            m, (rx, ry, rw_, rh) = self.water
            i = np.clip(((X - rx) / rw_ * m.shape[0]).astype(int), 0, m.shape[0] - 1)
            j = np.clip(((Y - ry) / rh * m.shape[1]).astype(int), 0, m.shape[1] - 1)
            inside = (X >= rx) & (X < rx + rw_) & (Y >= ry) & (Y < ry + rh)
            amp[inside & (m[i, j] > 60)] = 0.0
        return amp

    # ------------------------------------------------------------- consultas
    def height(self, x, y):
        """Altura del terreno (m MSL): superficie suave (Catmull-Rom) por los puntos de la grilla más ondulaciones
        finas. La física y la malla fina que rodea al avión usan esta misma superficie."""
        n = self.n
        u = (x + self.half) / self.cell
        v = (y + self.half) / self.cell
        if u < 1 or v < 1 or u >= n - 3 or v >= n - 3:
            return self.height_tri(x, y)
        i = int(u)
        j = int(v)
        wu = _cr_weights(u - i)
        wv = _cr_weights(v - j)
        H = self.h
        acc = 0.0
        for a in range(4):
            row = H[i - 1 + a]
            acc += wu[a] * (wv[0] * row[j - 1] + wv[1] * row[j] + wv[2] * row[j + 1] + wv[3] * row[j + 2])
        return acc + self._micro_at(x, y, u, v)

    def _micro_at(self, x, y, u, v):
        i = int(u)
        j = int(v)
        fu = u - i
        fv = v - j
        A = self.amp
        amp = (A[i, j] * (1 - fu) * (1 - fv) + A[i + 1, j] * fu * (1 - fv) + A[i, j + 1] * (1 - fu) * fv
               + A[i + 1, j + 1] * fu * fv)
        if amp <= 0.0:
            return 0.0
        a = x / MICRO_STEP
        b = y / MICRO_STEP
        ia = math.floor(a)
        ib = math.floor(b)
        fa = a - ia
        fb = b - ib
        M = self._micro
        k = MICRO_TILE
        i0, i1, j0, j1 = ia % k, (ia + 1) % k, ib % k, (ib + 1) % k
        nz = (M[i0, j0] * (1 - fa) * (1 - fb) + M[i1, j0] * fa * (1 - fb) + M[i0, j1] * (1 - fa) * fb
              + M[i1, j1] * fa * fb)
        return amp * nz

    def height_v(self, X, Y):
        """height() para matrices de puntos (malla fina del renderizador)."""
        n = self.n
        X = np.asarray(X, np.float64)
        Y = np.asarray(Y, np.float64)
        u = np.clip((X + self.half) / self.cell, 1.0, n - 3.0001)
        v = np.clip((Y + self.half) / self.cell, 1.0, n - 3.0001)
        i = u.astype(int)
        j = v.astype(int)
        wu = _cr_weights(u - i)
        wv = _cr_weights(v - j)
        H = self.h
        out = np.zeros_like(u)
        for a in range(4):
            for b in range(4):
                out += wu[a] * wv[b] * H[i - 1 + a, j - 1 + b]
        fu = u - i
        fv = v - j
        A = self.amp
        amp = (A[i, j] * (1 - fu) * (1 - fv) + A[i + 1, j] * fu * (1 - fv) + A[i, j + 1] * (1 - fu) * fv
               + A[i + 1, j + 1] * fu * fv)
        a = X / MICRO_STEP
        b = Y / MICRO_STEP
        ia = np.floor(a).astype(np.int64)
        ib = np.floor(b).astype(np.int64)
        fa = a - ia
        fb = b - ib
        M = self._micro
        k = MICRO_TILE
        i0, i1, j0, j1 = ia % k, (ia + 1) % k, ib % k, (ib + 1) % k
        nz = (M[i0, j0] * (1 - fa) * (1 - fb) + M[i1, j0] * fa * (1 - fb) + M[i0, j1] * (1 - fa) * fb
              + M[i1, j1] * fa * fb)
        return out + amp * nz

    def height_tri_v(self, X, Y):
        """Altura de la malla gruesa (triangulada) para matrices de puntos: el borde de la malla fina empalma con
        ella sin rendijas."""
        n = self.n
        u = np.clip((np.asarray(X, np.float64) + self.half) / self.cell, 0.0, n - 1.0001)
        v = np.clip((np.asarray(Y, np.float64) + self.half) / self.cell, 0.0, n - 1.0001)
        i = u.astype(int)
        j = v.astype(int)
        fu = u - i
        fv = v - j
        H = self.h
        h00 = H[i, j]
        h11 = H[i + 1, j + 1]
        up = fu >= fv
        a = h00 + fu * (H[i + 1, j] - h00) + fv * (h11 - H[i + 1, j])
        b = h00 + fv * (H[i, j + 1] - h00) + fu * (h11 - H[i, j + 1])
        return np.where(up, a, b)

    def height_tri(self, x, y):
        """Altura con la misma triangulación que la malla gruesa (lejos del avión y fuera de la grilla)."""
        n = self.n
        u = (x + self.half) / self.cell
        v = (y + self.half) / self.cell
        if u < 0 or v < 0 or u >= n - 1 or v >= n - 1:
            return -50.0
        i = int(u)
        j = int(v)
        fu = u - i
        fv = v - j
        H = self.h
        h00 = H[i, j]
        h11 = H[i + 1, j + 1]
        if fu >= fv:
            h10 = H[i + 1, j]
            return h00 + fu * (h10 - h00) + fv * (h11 - h10)
        h01 = H[i, j + 1]
        return h00 + fv * (h01 - h00) + fu * (h11 - h01)

    def surface_height(self, x, y):
        h = self.height(x, y)
        return h if h > WATER_LEVEL else WATER_LEVEL

    def is_water(self, x, y):
        """¿Hay un lago, embalse o río ancho en (norte x, este y)?"""
        if self.water is None:
            return False
        m, (rx, ry, rw, rh) = self.water
        i = int((x - rx) / rw * m.shape[0])
        j = int((y - ry) / rh * m.shape[1])
        return 0 <= i < m.shape[0] and 0 <= j < m.shape[1] and m[i, j] > 127

    def surface(self, x, y):
        """(altura de la superficie, tipo) donde tipo es 'agua', 'asfalto' o 'cesped'."""
        h = self.height(x, y)
        if h < WATER_LEVEL:
            return WATER_LEVEL, "agua"
        if self.is_water(x, y):
            return h, "agua"
        for ap in self.airports:
            if abs(x - ap.ref[0]) < 3000 and abs(y - ap.ref[1]) < 3000 and ap.paved(x, y):
                return h, "asfalto"
        return h, "cesped"

    def height_grid_sample(self, step=4):
        return self.h[::step, ::step]
