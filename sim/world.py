"""Mundo de simulación: integra terreno, atmósfera, avión, radios, PA e instrumentos."""
import math
import random

import numpy as np

from .aircraft_data import AIRCRAFT
from .airports import build_airports
from .atmosphere import Atmosphere, Weather
from .autopilot import Autopilot
from .flightmodel import Aircraft
from .mathx import FT, KT, NM, clamp, quat_from_euler, quat_to_euler, wrap360
from .gps import Gps
from .nav import AdfRadio, NavRadio
from .terrain import Terrain
from .traffic import Traffic
from .atc import ATC
from .emergencies import Emergencies

PHYS_HZ = 240


class Indications:
    """Lo que ven los instrumentos (con retardos, errores y fallas)."""

    def __init__(self):
        self.ias = 0.0
        self.alt_ft = 0.0
        self.vs_fpm = 0.0
        self.ai_roll = 0.0
        self.ai_pitch = 0.0
        self.dg = 0.0
        self.dg_drift = 0.0
        self.compass = 0.0
        self.compass_rate = 0.0
        self.turn_rate = 0.0
        self.slip = 0.0
        self.p_total_frozen = None
        self.p_static_frozen = None
        self.ai_err_roll = 0.0
        self.ai_err_pitch = 0.0
        self.radar_alt_ft = 0.0
        self.ias_trend = 0.0
        self._ias_prev = 0.0
        self.magvar = 0.0                # declinación del lugar: la brújula y el direccional marcan rumbo magnético

    def reset(self, ac, kollsman):
        self.ias = ac.ias_kt
        self._ias_prev = ac.ias_kt
        self.vs_fpm = 0.0
        self.ai_roll, self.ai_pitch = ac.roll, ac.pitch
        self.dg = wrap360(ac.heading - self.magvar)
        self.dg_drift = 0.0
        self.compass = self.dg
        self.ai_err_roll = self.ai_err_pitch = 0.0
        # presión en la posición actual (p_amb es la del último paso de física: tras recolocar el avión, vieja)
        p = ac.atmo.properties(ac.alt_msl)[1] if getattr(ac, "atmo", None) is not None else getattr(ac, "p_amb", 101325.0)
        self.alt_ft = Atmosphere.pressure_altitude(p, kollsman) / FT

    def update(self, dt, ac, atmo, kollsman, rng):
        s = ac.sys
        f = s.failures
        _, p_static, rho, _ = atmo.properties(ac.alt_msl)
        q = 0.5 * rho * ac.tas ** 2
        p_total = p_static + q
        # sistema pitot-estático
        if f["static"]:
            if self.p_static_frozen is None:
                self.p_static_frozen = p_static
            ps = self.p_static_frozen
        else:
            self.p_static_frozen = None
            ps = p_static
        if f["pitot"]:
            if self.p_total_frozen is None:
                self.p_total_frozen = p_total
            pt = self.p_total_frozen
        else:
            self.p_total_frozen = None
            pt = p_total
        qi = max(pt - ps, 0.0)
        ias = math.sqrt(2 * qi / 1.225) / KT
        self.ias += (ias - self.ias) * min(1.0, dt / 0.15)
        self.ias_trend += ((self.ias - self._ias_prev) / max(dt, 1e-3) * 6.0 - self.ias_trend) * min(1.0, dt / 1.0)
        self._ias_prev = self.ias
        alt = Atmosphere.pressure_altitude(ps, kollsman) / FT
        prev = self.alt_ft
        self.alt_ft += (alt - self.alt_ft) * min(1.0, dt / 0.2)
        vs = (self.alt_ft - prev) / max(dt, 1e-4) * 60.0
        self.vs_fpm += (vs - self.vs_fpm) * min(1.0, dt / 1.2)
        # giróscopos de vacío (horizonte artificial y direccional)
        spin = s.gyro_spin
        if spin < 0.75:
            # giróscopo lento: el horizonte se inclina poco a poco (error acotado, como uno que se cae)
            k = (0.75 - spin) * 4.0 * min(1.0, spin * 6.0)     # parado del todo no se mueve
            self.ai_err_roll += rng.gauss(0, 1) * math.radians(2.5) * k * math.sqrt(dt) + math.radians(0.8) * k * dt
            self.ai_err_pitch += rng.gauss(0, 1) * math.radians(1.2) * k * math.sqrt(dt)
            self.dg_drift += (rng.gauss(0, 1) * 2.0 * math.sqrt(dt) + 1.0 * dt) * k
        else:
            # con el giróscopo a régimen se endereza solo en unos segundos
            self.ai_err_roll *= max(0.0, 1 - dt * 0.25)
            self.ai_err_pitch *= max(0.0, 1 - dt * 0.25)
            self.dg_drift += dt * 0.003          # precesión normal ~3°/15 min
        self.ai_err_roll = clamp(self.ai_err_roll, -math.radians(55), math.radians(55))
        self.ai_err_pitch = clamp(self.ai_err_pitch, -math.radians(18), math.radians(18))
        self.ai_roll = ac.roll + self.ai_err_roll
        self.ai_pitch = ac.pitch + clamp(self.ai_err_pitch, -0.6, 0.6)
        hm = wrap360(ac.heading - self.magvar)          # rumbo magnético
        self.dg = wrap360(hm + self.dg_drift)
        # brújula magnética con amortiguación y errores de viraje/aceleración
        target = hm + math.degrees(ac.roll) * 0.35 * math.cos(math.radians(hm))
        err = ((target - self.compass + 540) % 360) - 180
        self.compass_rate += (err * 2.0 - self.compass_rate * 1.6) * dt
        self.compass = wrap360(self.compass + self.compass_rate * dt)
        # coordinador de virajes (eléctrico)
        if s.electric_ok:
            self.turn_rate += (ac.turn_rate - self.turn_rate) * min(1.0, dt / 0.3)
        else:
            self.turn_rate *= max(0.0, 1 - dt * 0.2)
        self.slip += (clamp(-ac.ny * 6.0, -1.2, 1.2) - self.slip) * min(1.0, dt / 0.35)
        self.radar_alt_ft = max(0.0, ac.agl / FT)


POSITIONS = {
    "pista": "En la pista en servicio, listo para despegar",
    "pista_opuesta": "En la cabecera opuesta",
    "plataforma": "Estacionado, motor apagado",
    "punto_espera": "Punto de espera de la pista",
    "viento_cola": "Tramo viento en cola, 1000 ft AGL",
    "final3": "Final larga (3 NM)",
    "final10": "Interceptando el ILS (9 NM)",
    "crucero": "En crucero, 3000 ft sobre el terreno",
    "otro": "Aeródromo cercano, en pista",
    "otro_final": "Final del aeródromo cercano",
}
ALIASES = {"pista36": "pista", "pista18": "pista_opuesta", "valle_norte": "otro", "valle_norte_final": "otro_final"}


class World:
    def __init__(self, aircraft_id="c172", seed=7, location=None):
        self.location = location
        if location is None:
            self.airports, self.navaids = build_airports()
            self.terrain = Terrain(self.airports, seed=seed)
            self.place_name = "Escenario escuela (Base Escuela · ESC)"
        else:
            self.airports, self.navaids = location["airports"], location["navaids"]
            self.terrain = Terrain(self.airports, heights=location["heights"], sat=location["sat"][0][0],
                                   water=location.get("water"))
            self.place_name = f"{location['name']} ({location['ident']})"
        self.weather = Weather()
        self.atmo = Atmosphere(self.weather)
        self.rng = random.Random(3)
        # declinación magnética del lugar (grados, + = este). La física y la evaluación usan rumbos verdaderos; lo
        # que ve y oye el piloto (brújula, direccional, HSI, VOR, viento de la torre, rumbos dictados) es magnético
        self.magvar = float((location or {}).get("magvar", 0.0) or 0.0)
        for nv in self.navaids:
            if nv.kind == "VOR" and getattr(nv, "magvar", None) is None:
                nv.magvar = self.magvar
        self.nav1 = NavRadio(self.navaids, 110.30, 360.0)
        self.nav2 = NavRadio(self.navaids, 113.70, 360.0)
        vors = [n for n in self.navaids if n.kind == "VOR"]
        if vors:
            self.nav2.freq = vors[0].freq
            self.nav2.standby = vors[1].freq if len(vors) > 1 else vors[0].freq
        else:
            self.nav2.standby = 115.20
        self.adf = AdfRadio(self.navaids)
        ndbs = sorted((n for n in self.navaids if n.kind == "NDB"),
                      key=lambda n: math.hypot(n.pos[0] - self.home.ref[0], n.pos[1] - self.home.ref[1]))
        if ndbs:                       # el ADF empieza en el NDB más cercano al aeródromo
            self.adf.freq = ndbs[0].freq
            self.adf.standby = ndbs[1].freq if len(ndbs) > 1 else ndbs[0].freq
        self.show_adf = False          # el segundo instrumento de navegación muestra el ADF en vez del NAV 2
        self.gps = Gps(self)
        self.cdi_src = "VLOC"          # selector CDI: "VLOC" (NAV 1) o "GPS" para el HSI/CDI y el piloto automático
        fq = dict(TWR=118.300, GND=121.900, ATIS=127.800)
        if location is not None:
            fq.update(location.get("freqs") or {})
        if fq["GND"] == fq["TWR"]:
            fq.pop("GND")
        self.freqs = fq
        self.com_freq = fq["TWR"]
        self.com_standby = fq.get("ATIS", fq.get("GND", fq["TWR"]))
        self.xpdr = 1200
        self.ap = Autopilot()
        self.ap.magvar = self.magvar
        self.ind = Indications()
        self.ind.magvar = self.magvar
        self.kollsman = 1013.25
        self.sim_time = 0.0
        self.acc = 0.0
        self.aircraft_id = aircraft_id
        self.ac = Aircraft(AIRCRAFT[aircraft_id](), self.terrain, self.atmo)
        self.sim_rate = 1                # herramientas del instructor: ritmo del tiempo (1, 2 o 4)
        self.frozen = {}                 # "alt" / "pos" / "fuel" -> valor que se mantiene
        self.events = []
        self.assist_rudder = False
        self.stats = dict(flight_time=0.0, landings=0, airborne=False)
        self.route = None                # ruta planificada (lista de puntos) para el MFD
        self.traffic = Traffic(self)
        self.select_runway()
        self.atc = ATC(self)
        self.emerg = Emergencies(self)
        self.reposition("pista")

    @property
    def is_school(self):
        return self.location is None

    @property
    def home(self):
        return self.airports[0]

    @property
    def main_airport(self):
        return self.airports[0]

    def ils(self, ident):
        for n in self.navaids:
            if n.ident == ident:
                return n
        return None

    def ils_for(self, rw, end):
        for n in self.navaids:
            if n.kind == "ILS" and n.runway is rw and n.end_ident == end:
                return n
        return None

    def set_aircraft(self, aircraft_id):
        self.aircraft_id = aircraft_id
        self.ac = Aircraft(AIRCRAFT[aircraft_id](), self.terrain, self.atmo)
        self.frozen = {}

    # ------------------------------------------------------------ rumbos magnéticos
    def mag(self, true_deg):
        """Rumbo verdadero → magnético (lo que marcan la brújula y el direccional). Redondeado a enteros
        con 360 en vez de 0, como se dicta un rumbo."""
        return round(wrap360(true_deg - self.magvar)) % 360 or 360

    def true(self, mag_deg):
        """Rumbo magnético → verdadero."""
        return wrap360(mag_deg + self.magvar)

    def set_magvar(self, v, vors=True):
        """Cambia la declinación del lugar (pruebas, instructor). vors: también la rosa de los VOR."""
        self.magvar = self.ind.magvar = self.ap.magvar = float(v)
        if vors:
            for nv in self.navaids:
                if nv.kind == "VOR":
                    nv.magvar = float(v)

    # ------------------------------------------------------------ herramientas del instructor
    FREEZES ={"alt": "altitud", "pos": "posición", "fuel": "combustible"}

    def freeze(self, kind, on):
        """Congela la altitud, la posición sobre el terreno o el combustible en su valor actual (el avión sigue
        volando: actitud, velocidad y motor cambian como siempre)."""
        ac = self.ac
        if not on:
            self.frozen.pop(kind, None)
        elif kind == "alt":
            self.frozen["alt"] = float(ac.pos[2])
        elif kind == "pos":
            self.frozen["pos"] = (float(ac.pos[0]), float(ac.pos[1]))
        elif kind == "fuel":
            self.frozen["fuel"] = float(ac.sys.fuel_l)

    def _hold_frozen(self):
        ac = self.ac
        f = self.frozen
        if "alt" in f:
            ac.pos[2] = f["alt"]
            ac.vel[2] = min(ac.vel[2], 0.0) if ac.on_ground else 0.0
        if "pos" in f:
            ac.pos[0], ac.pos[1] = f["pos"]
        if "fuel" in f:
            ac.sys.fuel_l = f["fuel"]

    def set_rate(self, x):
        """Ritmo del tiempo ×1, ×2 o ×4. Acelerar solo en vuelo y por encima de 500 ft sobre el terreno."""
        x = int(x) if x in (1, 2, 4) else 1
        if x > 1 and (self.ac.on_ground or self.ac.crashed or self.ac.agl < 500 * FT):
            return False
        self.sim_rate = x
        return True

    def slew(self, north_nm=0.0, east_nm=0.0, alt_ft=0.0, hdg_deg=0.0):
        """Mueve el avión al instante (en vuelo): millas al norte y al este, pies de altitud y grados de rumbo.
        La velocidad gira con el rumbo y nunca baja a menos de 300 ft sobre el terreno."""
        ac = self.ac
        if ac.on_ground or ac.crashed:
            return False
        ac.pos[0] += north_nm * NM
        ac.pos[1] += east_nm * NM
        ac.pos[2] -= alt_ft * FT
        gh = self.terrain.surface_height(ac.pos[0], ac.pos[1])
        ac.pos[2] = min(ac.pos[2], -(gh + 300 * FT))
        if hdg_deg:
            roll, pitch, yaw = quat_to_euler(ac.q)
            d = math.radians(hdg_deg)
            ac.q = quat_from_euler(roll, pitch, yaw + d)
            c, s = math.cos(d), math.sin(d)
            ac.vel[0], ac.vel[1] = ac.vel[0] * c - ac.vel[1] * s, ac.vel[0] * s + ac.vel[1] * c
        for k in ("alt", "pos"):
            if k in self.frozen:
                self.freeze(k, True)    # lo congelado pasa a ser la nueva posición
        ac._update_outputs(np.zeros(3), ac.tas)    # altitud y rumbo al día aunque la simulación esté en pausa
        return True

    # ------------------------------------------------------------ pista en servicio
    def select_runway(self, airport=None):
        """Elige la pista más larga y la cabecera con viento de cara."""
        ap = airport or self.home
        rw = max(ap.runways, key=lambda r: r.length)
        wd = self.weather.wind_dir if self.weather.wind_kt > 0.5 else rw.heading
        best = min(rw.idents, key=lambda e: abs(((rw.end(e)[1] - wd) + 180) % 360 - 180))
        if airport is None or airport is self.home:
            self.active_rw, self.active_end = rw, best
        return rw, best

    def runway_frame(self, rw=None, end=None):
        rw = rw or self.active_rw
        end = end or self.active_end
        thr, hdg, d = rw.end(end)
        r = np.array([-d[1], d[0]])
        return thr, hdg, d, r

    def cruise_alt_ft(self, radius=9000.0):
        """Altitud de crucero segura: 3000 ft sobre el campo o 1500 ft sobre el terreno más alto cercano."""
        if self.is_school:
            return 4500.0
        T = self.terrain
        c = np.linspace(-T.half, T.half, T.n)
        ref = self.home.ref
        mi = np.abs(c - ref[0]) < radius
        mj = np.abs(c - ref[1]) < radius
        hmax = float(T.h[np.ix_(mi, mj)].max()) if mi.any() and mj.any() else self.home.elev
        a = max(self.home.elev / FT + 3000, hmax / FT + 1500)
        return math.ceil(a / 500.0) * 500.0

    # ------------------------------------------------------------ posiciones
    def reposition(self, name, cold=False):
        name = ALIASES.get(name, name)
        ac = self.ac
        home = self.home
        self.frozen = {}
        self.sim_rate = 1
        self.select_runway()
        rw = self.active_rw
        thr, hdg, d, r = self.runway_frame()
        self.ap.disengage("")
        self.ap.disconnect_alert = 0.0
        self.ap.lat, self.ap.vert = "ROL", "PIT"
        self.ap.nav_armed = self.ap.gs_armed = self.ap.alt_armed = False
        elev_ft = home.elev / FT
        other = self.airports[1] if len(self.airports) > 1 else None
        if name in ("otro", "otro_final") and other is None:
            name = "pista" if name == "otro" else "final3"
        airborne = name not in ("pista", "pista_opuesta", "plataforma", "punto_espera", "otro")
        if cold:
            ac.sys.cold_and_dark()
        else:
            ac.sys.ready_to_fly(airborne)
        gs3 = math.tan(math.radians(3.0))
        if name == "pista":
            p = thr + d * 25
            ac.place_on_ground(p[0], p[1], hdg)
        elif name == "pista_opuesta":
            oe = rw.idents[1] if self.active_end == rw.idents[0] else rw.idents[0]
            t2, h2, d2 = rw.end(oe)
            p = t2 + d2 * 25
            ac.place_on_ground(p[0], p[1], h2)
        elif name == "plataforma":
            if self.is_school:
                ac.place_on_ground(140.0, 170.0, 270.0)
            else:
                p = thr + d * 160 + r * (rw.width / 2 + 90)
                ac.place_on_ground(p[0], p[1], (hdg - 90) % 360)
        elif name == "punto_espera":
            if self.is_school and self.active_end == "36":
                ac.place_on_ground(-650.0, 60.0, 270.0)
            else:
                p = thr + d * 40 + r * (rw.width / 2 + 45)
                ac.place_on_ground(p[0], p[1], (hdg - 90) % 360)
        elif name == "viento_cola":
            p = thr + d * (rw.length * 0.5 + 200) - r * 1300
            ac.place_in_air(p[0], p[1], (elev_ft + 1000) * FT, (hdg + 180) % 360, 90)
        elif name == "final3":
            dist = 3 * NM
            p = thr - d * dist
            h = home.elev + (dist + 300) * gs3
            ac.place_in_air(p[0], p[1], h, hdg, 70, flaps_idx=1, climb_fpm=-380)
        elif name == "final10":
            p = thr - d * 9 * NM - r * 900
            gs_h = (9 * NM + 300) * gs3
            ac.place_in_air(p[0], p[1], home.elev + min(2400 * FT, gs_h * 0.85), (hdg + 10) % 360, 95)
        elif name == "crucero":
            p = thr - d * 6000 - r * 3000
            ac.place_in_air(p[0], p[1], self.cruise_alt_ft() * FT, hdg, 105)
        elif name in ("otro", "otro_final"):
            rw2, e2 = self.select_runway(other)
            t2, h2, d2 = rw2.end(e2)
            if name == "otro":
                p = t2 + d2 * 25
                ac.place_on_ground(p[0], p[1], h2)
            else:
                dist = 3 * NM
                p = t2 - d2 * dist
                ac.place_in_air(p[0], p[1], other.elev + (dist + 300) * gs3, h2, 70, flaps_idx=1, climb_fpm=-380)
                ils2 = self.ils_for(rw2, e2)
                if ils2:
                    self.nav1.freq, self.nav1.obs = ils2.freq, self.mag(ils2.course)
        if cold:
            ac.sys.cold_and_dark()
        self.kollsman = self.weather.qnh_hpa
        _, p_amb, rho, _ = self.atmo.properties(ac.alt_msl)
        ac.p_amb = p_amb
        ac.rho = rho
        self.ind.reset(ac, self.kollsman)
        ac.alt_ind_ft = self.ind.alt_ft
        self.ap.hdg_bug = self.mag(ac.heading)
        self.ap.alt_sel = round((ac.alt_msl / FT) / 100) * 100
        self.stats["airborne"] = not ac.on_ground
        self.events.clear()
        self.traffic.reset()
        self.atc.reset()
        self.emerg.reset()
        if name in ("final3", "final10", "pista"):
            ils = self.ils_for(rw, self.active_end)
            if ils:
                self.nav1.freq = ils.freq
                self.nav1.obs = self.mag(ils.course)


    # ------------------------------------------------------------- paso
    def step(self, frame_dt, controls_fn=None):
        """Avanza la simulación con pasos fijos. controls_fn(world, dt) aplica mandos."""
        ac = self.ac
        if self.sim_rate > 1 and (ac.on_ground or ac.crashed or ac.agl < 500 * FT):
            self.sim_rate = 1            # cerca del suelo el tiempo vuelve a su ritmo normal
            self.events.append(("ritmo_normal", {}))
        frame_dt = min(frame_dt, 0.1) * self.sim_rate
        self.acc += frame_dt
        # en vuelo basta con 120 Hz; con ruedas en el suelo (amortiguadores rígidos) se usan 240 Hz
        h = 1.0 / (PHYS_HZ if (ac.on_ground or ac.agl < 25) else PHYS_HZ / 2)
        n = 0
        max_steps = 16 * self.sim_rate
        while self.acc >= h and n < max_steps:
            self.acc -= h
            n += 1
            if controls_fn:
                controls_fn(self, h)
            self.atmo.update(h, ac.tas, ac.agl, ac.pos)
            ac.step(h)
            if self.frozen:
                self._hold_frozen()
            self.sim_time += h
            if not ac.crashed and not ac.on_ground:
                self.stats["flight_time"] += h
        if n >= max_steps:
            self.acc = 0.0          # si el equipo va justo, la simulación se ralentiza en vez de atascarse
        dt = n * h
        if n == 0:
            return
        # tráfico, instrumentos y radios
        self.traffic.update(dt)
        self.atc.update(dt)
        self.emerg.update(dt)
        self.ind.update(dt, ac, self.atmo, self.kollsman, self.rng)
        ac.alt_ind_ft = self.ind.alt_ft
        pw = ac.sys.avionics_ok
        self.nav1.update(ac, pw)
        self.nav2.update(ac, pw)
        self.adf.update(ac, pw)
        self.gps.update(ac, pw)
        # eventos de la física
        for ev in ac.events:
            self.events.append(ev)
            if ev[0] == "contacto" and self.stats["airborne"]:
                self.stats["landings"] += 1
                self.stats["airborne"] = False
        ac.events.clear()
        if not ac.on_ground and ac.agl > 3:
            self.stats["airborne"] = True

    def nav_source(self):
        """Lo que siguen el HSI/CDI de NAV 1 y el piloto automático en NAV: el GPS o la radio NAV 1 (selector CDI)."""
        return self.gps if self.cdi_src == "GPS" else self.nav1

    def apply_autopilot(self, dt):
        cmd = self.ap.update(dt, self.ac, self.nav_source(), self.ind.alt_ft)
        return cmd


def transfer_to_scene(old, loc):
    """Mundo continuo: crea el escenario 'loc' y pasa a él el avión EN VUELO, sin cortes: misma posición geográfica,
    altitud, velocidad, actitud, motor, sistemas, fallas, radios, piloto automático e indicaciones."""
    ac = old.ac
    la, lo = old.location["proj"].to_geo(ac.pos[0], ac.pos[1])
    n, e = loc["proj"].to_local(la, lo)
    w = World(old.aircraft_id, location=loc)
    w.weather.copy_from(old.weather)
    ac.pos = np.array([float(n), float(e), float(ac.pos[2])])
    ac.terrain, ac.atmo = w.terrain, w.atmo
    w.ac = ac
    for k in ("ap", "ind", "kollsman", "xpdr", "com_freq", "com_standby", "stats", "sim_time", "emerg", "assist_rudder"):
        setattr(w, k, getattr(old, k))
    w.emerg.world = w
    for k in ("nav1", "nav2"):
        a, b = getattr(old, k), getattr(w, k)
        b.freq, b.standby, b.obs = a.freq, a.standby, a.obs
    w.adf.freq, w.adf.standby, w.show_adf = old.adf.freq, old.adf.standby, old.show_adf
    w.ind.magvar = w.ap.magvar = w.magvar        # el direccional se queda donde estaba; la brújula sigue al lugar
    # el plan del GPS pasa al escenario nuevo con sus coordenadas convertidas (mismo punto geográfico)
    g, og = w.gps, old.gps

    def conv(pos):
        la_, lo_ = old.location["proj"].to_geo(pos[0], pos[1])
        n_, e_ = loc["proj"].to_local(la_, lo_)
        return np.array([float(n_), float(e_)])
    for wp in og.plan + ([og.direct] if og.direct is not None else []):
        wp.pos = conv(wp.pos)
    g.plan, g.active, g.direct, g.obs_mode, g.obs_course = og.plan, og.active, og.direct, og.obs_mode, og.obs_course
    g.approach = None        # una aproximación RNAV es del aeródromo del escenario anterior: no pasa al nuevo
    g._from_here = og._from_here
    g.origin = conv(og.origin) if og.origin is not None else None
    w.cdi_src = old.cdi_src
    w.frozen, w.sim_rate = old.frozen, old.sim_rate
    w.select_runway()
    w.traffic.reset()
    w.atc.callsign = old.atc.callsign
    w.atc.enabled = old.atc.enabled
    w.atc.reset()
    return w
