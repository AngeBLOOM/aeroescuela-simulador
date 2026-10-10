"""Atmósfera estándar ISA, viento, ráfagas y turbulencia tipo Dryden."""
import math
import random

import numpy as np

from .mathx import KT, clamp

R_AIR = 287.053
G0 = 9.80665
RHO0 = 1.225


class Weather:
    """Parámetros meteorológicos que el instructor puede cambiar en vuelo."""

    def __init__(self):
        self.qnh_hpa = 1013.25
        self.temp_offset = 0.0          # desviación ISA en °C
        self.wind_dir = 360.0           # grados desde donde sopla
        self.wind_kt = 5.0
        self.gust_kt = 0.0
        self.turbulence = 0.0           # 0..1
        self.visibility_m = 30000.0
        self.cloud_base_ft = 4500.0     # MSL
        self.cloud_top_ft = 6000.0
        self.cloud_cover = 0.35         # 0..1 (1 = cubierto)
        self.hour = 11.0                # hora local 0..24
        self.wind_shear = False
        self.rain = 0.0                 # lluvia 0..1 (0,3 llovizna · 0,6 lluvia · 1 aguacero)
        self.date = None                # fecha del vuelo (None = hoy): Sol y Luna reales para esa fecha
        # tormenta (cumulonimbo): centro en coordenadas locales (m), radio del núcleo y desplazamiento (m/s)
        self.storm = False
        self.storm_n, self.storm_e = 0.0, 0.0
        self.storm_r = 2500.0
        self.storm_vn, self.storm_ve = 0.0, 0.0

    def copy_from(self, other):
        self.__dict__.update(other.__dict__)

    def describe(self):
        cov = self.cloud_cover
        if cov < 0.1:
            nub = "SKC"
        elif cov < 0.3:
            nub = "FEW"
        elif cov < 0.55:
            nub = "SCT"
        elif cov < 0.85:
            nub = "BKN"
        else:
            nub = "OVC"
        vis_m = min(self.visibility_m, rain_visibility(self.rain))
        vis = "9999" if vis_m >= 10000 else f"{int(vis_m):04d}"
        gust = f"G{int(self.gust_kt + self.wind_kt):02d}" if self.gust_kt > 0 else ""
        base = int(self.cloud_base_ft / 100)
        t = 15 + self.temp_offset
        wx = ""
        if self.storm:
            wx = " TSRA" if self.rain < 0.75 else " +TSRA"
        elif self.rain > 0.02:
            wx = " -RA" if self.rain < 0.35 else (" RA" if self.rain < 0.75 else " +RA")
        cb = "CB" if self.storm else ""
        return (f"{int(self.wind_dir) % 360:03d}{int(self.wind_kt):02d}{gust}KT {vis}{wx} "
                f"{nub}{base:03d}{cb} {int(t):02d}/{int(t - 8):02d} Q{int(round(self.qnh_hpa))}")


def rain_visibility(rain):
    """Visibilidad (m) que deja la lluvia: llovizna ~20 km, lluvia ~8 km, aguacero ~2 km."""
    if rain <= 0.02:
        return 1e9
    return max(1500.0, 30000.0 * (1.0 - rain) ** 1.6 + 1800.0)


def _smooth(e0, e1, x):
    """smoothstep: 0 en e0, 1 en e1 (vale también con e0 > e1)."""
    t = clamp((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


class Atmosphere:
    def __init__(self, weather=None, seed=1):
        self.w = weather or Weather()
        self.rng = random.Random(seed)
        self.turb = np.zeros(3)
        self.gust_state = 0.0
        self.gust_target = 0.0
        self.gust_timer = 0.0
        self.time = 0.0
        # efectos locales de la tormenta y la lluvia donde está el avión
        self.rain_here = 0.0            # lluvia en el avión 0..1
        self.storm_core = 0.0           # 1 dentro del núcleo de la tormenta
        self.storm_near = 0.0           # 1 cerca (frente de ráfagas)
        self.storm_dist = 1e9
        self.outflow = np.zeros(3)      # viento de la tormenta (ráfaga de frente, corrientes verticales)
        self.wet = 0.0                  # pista mojada 0..1
        self.flash = 0.0                # destello del relámpago 0..1
        self.flash_timer = 3.0
        self.thunder = []               # truenos pendientes: [segundos hasta oírse, volumen]

    # ------------------------------------------------------------ propiedades
    def properties(self, alt_m):
        """Devuelve (T [K], p [Pa], rho [kg/m3], a [m/s]) a una altitud MSL."""
        h = clamp(alt_m, -500.0, 11000.0)
        p0 = self.w.qnh_hpa * 100.0
        t_isa = 288.15 - 0.0065 * h
        p = p0 * (1 - 2.25577e-5 * h) ** 5.25588
        T = t_isa + self.w.temp_offset
        rho = p / (R_AIR * T)
        a = math.sqrt(1.4 * R_AIR * T)
        return T, p, rho, a

    @staticmethod
    def pressure_altitude(p, kollsman_hpa):
        """Altitud que marca un altímetro calibrado a 'kollsman_hpa'."""
        return 44330.77 * (1 - (p / (kollsman_hpa * 100.0)) ** 0.190263)

    # ------------------------------------------------------------------ viento
    def mean_wind(self, agl_m):
        w = self.w
        ang = math.radians(w.wind_dir)
        f = clamp((max(agl_m, 1.0) / 10.0) ** 0.14, 0.35, 1.5)
        spd = w.wind_kt * KT * f
        if w.wind_shear and agl_m < 300:
            # cizalladura: el viento de cara cae bruscamente cerca del suelo
            spd *= clamp(agl_m / 300.0, 0.0, 1.0)
        # el viento sopla DESDE wind_dir
        return np.array([-math.cos(ang) * spd, -math.sin(ang) * spd, 0.0])

    def visibility(self):
        """Visibilidad efectiva (m) donde está el avión, con la lluvia."""
        return min(self.w.visibility_m, rain_visibility(self.rain_here))

    def _storm(self, dt, pos, agl_m):
        w = self.w
        self.flash = max(0.0, self.flash - dt * 6.0)
        if not w.storm:
            self.storm_core = self.storm_near = 0.0
            self.storm_dist = 1e9
            self.outflow *= max(0.0, 1.0 - dt * 0.6)
            return
        w.storm_n += w.storm_vn * dt
        w.storm_e += w.storm_ve * dt
        r = max(w.storm_r, 500.0)
        if pos is not None:
            dn, de = pos[0] - w.storm_n, pos[1] - w.storm_e
        else:
            dn, de = 1e6, 0.0
        d = math.hypot(dn, de)
        self.storm_dist = d
        core = 1.0 - _smooth(r * 0.55, r, d)
        near = 1.0 - _smooth(r, r * 2.6, d)
        self.storm_core, self.storm_near = core, near
        # frente de ráfagas: el aire frío sale de la tormenta hacia fuera, más fuerte cerca del suelo
        out = np.zeros(3)
        if d > 1.0:
            low = 1.0 if agl_m < 600 else max(0.3, 1.0 - (agl_m - 600) / 1500)
            spd = 9.0 * near * (1.0 - core * 0.5) * low
            out[0], out[1] = dn / d * spd, de / d * spd
        # corrientes: descendente en el núcleo con lluvia, ascendente en el borde (NED: z positivo hacia abajo)
        out[2] = 7.0 * _smooth(r * 0.65, 0.0, d) - 4.0 * core * _smooth(0.0, r * 0.45, d)
        self.outflow += (out - self.outflow) * min(1.0, dt * 0.6)
        # relámpagos: más seguidos cuanto más cerca; el trueno llega con el retraso del sonido
        self.flash_timer -= dt
        if self.flash_timer <= 0:
            self.flash_timer = self.rng.uniform(3.0, 9.0) if d < r * 3 else self.rng.uniform(8.0, 20.0)
            dist_flash = max(200.0, d + self.rng.uniform(-r, r))
            self.flash = clamp(1.4 - dist_flash / 12000.0, 0.15, 1.0)
            self.thunder.append([dist_flash / 340.0, clamp(1.2 - dist_flash / 10000.0, 0.15, 1.0)])
        for t in self.thunder:
            t[0] -= dt
        if len(self.thunder) > 8:
            del self.thunder[:-8]

    def update(self, dt, airspeed, agl_m, pos=None):
        """Avanza ráfagas y turbulencia (filtros Gauss-Markov tipo Dryden), lluvia y tormenta."""
        self.time += dt
        w = self.w
        self._storm(dt, pos, agl_m)
        rain = w.rain
        if w.storm:
            rain = max(rain, self.storm_core + 0.55 * self.storm_near)
        self.rain_here += (min(rain, 1.0) - self.rain_here) * min(1.0, dt * 0.5)
        # la pista se moja en un par de minutos de lluvia y tarda mucho más en secarse
        if self.rain_here > 0.15:
            self.wet = min(1.0, self.wet + dt * self.rain_here / 90.0)
        else:
            self.wet = max(0.0, self.wet - dt / 1200.0)
        turb_level = w.turbulence + 0.9 * self.storm_core + 0.35 * self.storm_near
        # ráfagas
        self.gust_timer -= dt
        if self.gust_timer <= 0:
            self.gust_timer = self.rng.uniform(2.0, 7.0)
            self.gust_target = self.rng.uniform(0.0, 1.0) ** 1.5 * w.gust_kt * KT
        self.gust_state += (self.gust_target - self.gust_state) * min(1.0, dt * 1.2)
        # turbulencia
        if turb_level > 0.0:
            h = max(agl_m, 10.0)
            L = clamp(h * 1.0, 50.0, 530.0)
            V = max(airspeed, 15.0)
            sig_w = turb_level * 3.2 * (1.0 if h > 300 else 0.6 + 0.4 * h / 300)
            sig_uv = sig_w * clamp(1.0 / (0.177 + 0.000823 * h) ** 0.4, 1.0, 2.0)
            sig = (sig_uv, sig_uv, sig_w)
            for i in range(3):
                tau = (L * (0.5 if i == 2 else 1.0)) / V
                a = math.exp(-dt / tau)
                self.turb[i] = a * self.turb[i] + sig[i] * math.sqrt(1 - a * a) * self.rng.gauss(0, 1)
        else:
            self.turb *= 0.95

    def wind_at(self, agl_m):
        mw = self.mean_wind(agl_m)
        spd = math.hypot(mw[0], mw[1])
        if spd > 0.1:
            gust = mw / spd * self.gust_state
        else:
            gust = np.zeros(3)
        return mw + gust + self.turb + self.outflow
