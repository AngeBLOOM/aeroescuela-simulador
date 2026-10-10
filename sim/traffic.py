"""Tráfico aéreo con IA: aviones que hacen circuitos, llegadas y salidas en la pista en servicio.

Los aviones IA usan cinemática sencilla (no el modelo 6DOF) siguiendo puntos del circuito,
con virajes de régimen estándar, ascensos/descensos limitados y separación con el alumno.
"""
import math
import random

import numpy as np

from .mathx import FT, KT, NM, G, clamp, quat_from_euler, wrap180

TYPES = [("c172", "Cessna"), ("pa28r", "Piper"), ("da40", "Diamond")]
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
# prefijos de matrícula por país (OACI): con cifras o con letras
NUMERIC_REG = {"VE": "YV", "US": "N"}
LETTER_REG = {"ES": "EC-", "MX": "XB-", "CO": "HK-", "AR": "LV-", "CL": "CC-", "PE": "OB-", "EC": "HC-", "BR": "PR-",
              "PA": "HP-", "DO": "HI-", "CU": "CU-", "GT": "TG-", "CR": "TI-", "UY": "CX-", "PY": "ZP-", "BO": "CP-",
              "FR": "F-", "GB": "G-", "DE": "D-", "IT": "I-", "PT": "CS-"}


class AIPlane:
    gear_h = 1.2            # altura del centro del avión sobre el suelo (m)
    aim = 150.0             # punto de toma pasado el umbral (m)
    max_vs = 3.8            # ascenso máximo (m/s)
    max_sink = 4.0          # descenso máximo (m/s)
    accel = 2.4             # aceleración en la carrera de despegue (m/s²)
    vr = 56 * KT            # velocidad de rotación
    min_spd = 60 * KT       # velocidad mínima al separarse de otro tráfico
    hold_off = 40.0         # distancia del punto de espera al borde de la pista (m)
    flare_vs = -0.5         # régimen de descenso en la recogida (m/s)
    flare_h = 6.0           # altura de las ruedas a la que empieza la recogida (m)
    jet = False

    def __init__(self, world, kind, type_id, type_name, callsign, start_leg=0):
        self.world = world
        self.kind = kind                # 'circuito', 'llegada', 'salida'
        self.type_id = type_id
        self.type_name = type_name
        self.callsign = callsign
        self.pos = np.zeros(3)
        self.heading = 0.0
        self.speed = 0.0                # m/s
        self.vs = 0.0                   # m/s (positivo arriba)
        self.roll = 0.0
        self.pitch = 0.0
        self.on_ground = True
        self.state = "espera"
        self.wp = []
        self.wi = 0
        self.leg = ""
        self.done = False
        self.wait_t = 0.0
        self.last_report = None
        self.color = random.choice([(1, 1, 1), (0.95, 0.95, 1.0), (1.0, 0.96, 0.9)])
        self._build(start_leg)

    # ------------------------------------------------------------ circuito
    def _frame(self):
        w = self.world
        thr, hdg, d, r = w.runway_frame()
        return thr, hdg, d, r, w.home.elev, w.active_rw.length

    def _pattern(self):
        thr, hdg, d, r, e, L = self._frame()
        pa = e + 1000 * FT

        def P(a, l, alt, kt, leg):
            p = thr + d * a + r * l
            return (p[0], p[1], alt, kt * KT, leg)
        return [P(L + 500, 0, e + 450 * FT, 75, "salida"), P(L + 1400, -650, e + 800 * FT, 80, "viento cruzado"),
                P(L + 700, -1350, pa, 90, "viento en cola"), P(0, -1350, pa, 85, "viento en cola"),
                P(-1500, -1350, pa - 150 * FT, 80, "base"), P(-2100, -500, e + 700 * FT, 75, "base"),
                P(-2500, 0, e + 560 * FT, 68, "final"), P(-600, 0, e + 140 * FT, 65, "final"),
                P(150, 0, e, 60, "toma")]

    def _build(self, start_leg):
        thr, hdg, d, r, e, L = self._frame()
        pat = self._pattern()
        if self.kind == "llegada":
            # desde 8 km al lado del viento en cola, uniéndose a 45°
            p = thr + d * 3500 - r * 6500
            self._place_air(p, e + 1500 * FT, 100 * KT)
            j = thr + d * 1200 - r * 1350
            self.wp = [(j[0], j[1], e + 1000 * FT, 95 * KT, "entrada")] + pat[3:]
        elif self.kind == "circuito" and start_leg > 0:
            k = min(start_leg, len(pat) - 2)
            a = pat[k - 1]
            self._place_air(np.array(a[:2]), a[2], a[3])
            self.wp = pat[k:]
            self.wi = 0
        else:
            # espera en el punto de espera, a un lado de la pista
            rw = self.world.active_rw
            p = thr + d * 90 - r * (rw.width / 2 + self.hold_off)
            self.pos = np.array([p[0], p[1], -(e + self.gear_h)])
            self.heading = (hdg + 90) % 360
            self.on_ground = True
            self.state = "espera"
            self.wait_t = random.uniform(3, 15)
            self.wp = pat[:1] + ([(*(thr + d * 9000)[:2], e + 3500 * FT, 100 * KT, "salida")] if self.kind == "salida" else pat[1:])
        self.leg = self.wp[0][4] if self.wp else ""

    def _place_air(self, p, alt, spd):
        self.pos = np.array([p[0], p[1], -alt])
        self.speed = spd
        self.on_ground = False
        self.state = "vuelo"
        tgt = self.wp[0] if self.wp else None
        if tgt:
            self.heading = math.degrees(math.atan2(tgt[1] - p[1], tgt[0] - p[0])) % 360

    # ------------------------------------------------------------ comportamiento
    def runway_busy_by_user(self):
        w = self.world
        ac = w.ac
        rw = w.active_rw
        on_rw = ac.on_ground and rw.contains(ac.pos[0], ac.pos[1], 5.0)
        thr, hdg, d, r = w.runway_frame()
        along = -((ac.pos[0] - thr[0]) * d[0] + (ac.pos[1] - thr[1]) * d[1])
        lat = abs((ac.pos[0] - thr[0]) * r[0] + (ac.pos[1] - thr[1]) * r[1])
        on_final = (not ac.on_ground) and 0 < along < 2.5 * NM and lat < 400 and ac.agl / FT < 900
        return on_rw, on_final

    def update(self, dt):
        if self.done:
            return
        w = self.world
        e = w.home.elev
        user_rw, user_final = self.runway_busy_by_user()
        if self.state == "espera":
            self.wait_t -= dt
            if self.wait_t <= 0 and not user_rw and not user_final and not self._ai_on_runway():
                self.state = "alineando"
                self.speed = 5.0
            return
        if self.state == "alineando":
            thr, hdg, d, r = w.runway_frame()
            tgt = thr + d * 20
            dx, dy = tgt[0] - self.pos[0], tgt[1] - self.pos[1]
            if math.hypot(dx, dy) < 3:
                self.heading = hdg
                self.speed = 0.0
                self.state = "carrera"
                return
            self.heading = math.degrees(math.atan2(dy, dx)) % 360
            self.speed = 5.0
            self._move(dt, ground=True)
            return
        if self.state == "saliendo":
            self.wait_t -= dt
            self.speed = 5.0
            self._move(dt, ground=True)
            if self.wait_t <= 0:
                self.done = True
            return
        if self.state == "carrera":
            self.speed = min(self.speed + self.accel * dt, self.vr * 1.1)
            self._move(dt, ground=True)
            if self.speed > self.vr:
                self.state = "vuelo"
                self.on_ground = False
                self.wi = 0
            return
        if self.state == "rodando":
            self.speed = max(self.speed - 3.0 * dt, 8 * KT)
            self._move(dt, ground=True)
            if self.speed <= 8.5 * KT:
                if self.kind == "circuito":
                    # toma y despegue: vuelve a acelerar
                    self.state = "carrera"
                    self.wp = self._pattern()
                    self.wi = 0
                else:
                    # abandona la pista por la derecha y desaparece en la plataforma
                    thr, hdg, d, r = w.runway_frame()
                    self.heading = (hdg + 90) % 360
                    self.speed = 5.0
                    self.state = "saliendo"
                    self.wait_t = 16.0
            return
        # vuelo hacia el punto actual
        if self.wi >= len(self.wp):
            self.done = True
            return
        tx, ty, talt, tspd, leg = self.wp[self.wi]
        self.leg = leg
        # motor y al aire si el alumno ocupa la pista o va delante en la final
        ahead_user = False
        if user_final and leg in ("final", "toma"):
            ac = w.ac
            thr_, _h, d_, _r = w.runway_frame()
            a_user = (ac.pos[0] - thr_[0]) * d_[0] + (ac.pos[1] - thr_[1]) * d_[1]
            a_me = (self.pos[0] - thr_[0]) * d_[0] + (self.pos[1] - thr_[1]) * d_[1]
            ahead_user = a_me < a_user < a_me + 2200
        if leg in ("final", "toma") and ((user_rw and -self.pos[2] - e < 400 * FT) or ahead_user):
            self.wp = self._pattern()
            self.wi = 0
            self.leg = "motor y al aire"
            return
        thr, hdg, d, r = w.runway_frame()
        if leg == "toma":
            # sobre el eje de pista hacia un punto lejano, descenso constante y recogida
            far = thr + d * 3000
            tx, ty = far[0], far[1]
        dx, dy = tx - self.pos[0], ty - self.pos[1]
        dist = math.hypot(dx, dy)
        brg = math.degrees(math.atan2(dy, dx)) % 360
        err = wrap180(brg - self.heading)
        rate = 3.0 if leg not in ("final", "toma") else 2.0
        turn = clamp(err * 0.8, -rate, rate)
        self.heading = (self.heading + turn * dt) % 360
        self.roll += (math.atan(math.radians(turn) * self.speed / G) - self.roll) * min(1.0, dt * 2)
        # separación con otros IA delante en el mismo tramo
        spd_tgt = tspd
        for o in w.traffic.planes:
            if o is self or o.done or o.on_ground:
                continue
            if o.leg == self.leg and math.hypot(o.pos[0] - self.pos[0], o.pos[1] - self.pos[1]) < 900:
                rel = math.degrees(math.atan2(o.pos[1] - self.pos[1], o.pos[0] - self.pos[0])) - self.heading
                if abs(wrap180(rel)) < 45:
                    spd_tgt = min(spd_tgt, max(o.speed * 0.95, self.min_spd))
        self.speed += clamp(spd_tgt - self.speed, -1.5 * dt, 1.5 * dt)
        alt = -self.pos[2]
        gh = w.terrain.surface(self.pos[0], self.pos[1])[0]
        to_aim = -((self.pos[0] - thr[0]) * d[0] + (self.pos[1] - thr[1]) * d[1]) + self.aim
        if leg in ("final", "toma") and to_aim > 0 and self.wi >= len(self.wp) - 2:
            # senda de 3° hacia el punto de toma (150 m pasado el umbral) y recogida a 6 m
            hgt = alt - e - self.gear_h
            if hgt > self.flare_h:
                vs_tgt = clamp(-self.speed * 0.0524 + (to_aim * 0.0524 - hgt) * 0.25, -self.max_sink, 0.5)
            else:
                vs_tgt = self.flare_vs
        elif leg == "toma":
            vs_tgt = self.flare_vs if alt - gh - self.gear_h < 6 else -2.5
        else:
            vs_tgt = clamp((talt - alt) / max(dist / max(self.speed, 1), 4.0), -self.max_sink, self.max_vs)
            # nunca por debajo de 300 ft sobre el terreno fuera de la final
            if alt - gh < 300 * FT and leg not in ("final",):
                vs_tgt = max(vs_tgt, 1.5)
        # evasión: si el alumno está cerca y delante, el IA asciende y vira a la derecha
        ac = w.ac
        rx, ry, rz = ac.pos[0] - self.pos[0], ac.pos[1] - self.pos[1], ac.pos[2] - self.pos[2]
        if not ac.on_ground and math.hypot(rx, ry) < 600 and abs(rz) < 120:
            rel = wrap180(math.degrees(math.atan2(ry, rx)) - self.heading)
            if abs(rel) < 70:
                vs_tgt = 3.5 if rz > -30 else -3.0
                self.heading = (self.heading + 3.0 * dt) % 360
        self.vs += (vs_tgt - self.vs) * min(1.0, dt * 1.5)
        self.pitch = math.radians(clamp(self.vs * 1.4 + 2.0, -6, 10))
        self._move(dt, ground=False)
        if leg == "toma":
            if -self.pos[2] <= gh + self.gear_h + 0.1:
                self.pos[2] = -(gh + self.gear_h)
                self.on_ground = True
                self.state = "rodando"
                self.roll = 0.0
                self.pitch = 0.0
                self.vs = 0.0
            return
        # captura del punto: anticipa el viraje (radio de giro) o lo da por pasado si queda detrás
        lead = self.speed / math.radians(rate) * (0.7 if leg not in ("final", "toma") else 0.15)
        if dist < max(150.0, lead) or (abs(err) > 100 and dist < 2500):
            self.wi += 1
        if math.hypot(self.pos[0] - w.home.ref[0], self.pos[1] - w.home.ref[1]) > 14000 and self.kind == "salida":
            self.done = True

    def _ai_on_runway(self):
        for o in self.world.traffic.planes:
            if o is self or o.done:
                continue
            if o.state in ("carrera", "rodando", "alineando") or (o.leg in ("final", "toma") and o.state == "vuelo"
                                                                  and -o.pos[2] - self.world.home.elev < 500 * FT):
                return True
        return False

    def _move(self, dt, ground):
        h = math.radians(self.heading)
        if ground:
            # en tierra se detiene si el avión del alumno está delante y cerca
            ac = self.world.ac
            dx, dy = ac.pos[0] - self.pos[0], ac.pos[1] - self.pos[1]
            dd = math.hypot(dx, dy)
            if ac.on_ground and dd < 45 and (dx * math.cos(h) + dy * math.sin(h)) > 0:
                self.speed = max(0.0, self.speed - 6.0 * dt)
        self.pos[0] += math.cos(h) * self.speed * dt
        self.pos[1] += math.sin(h) * self.speed * dt
        if ground:
            gh = self.world.terrain.surface(self.pos[0], self.pos[1])[0]
            self.pos[2] = -(gh + self.gear_h)
            self.pitch = math.radians(4.0) if self.state == "carrera" and self.speed > self.vr * 0.9 else 0.0
        else:
            self.pos[2] -= self.vs * dt

    @property
    def quat(self):
        return quat_from_euler(self.roll, self.pitch, math.radians(self.heading))

    @property
    def alt_ft(self):
        return -self.pos[2] / FT


# --------------------------------------------------------------- aviación comercial
# aerolíneas (nombre, indicativo radiotelefónico, tipos, colores de la deriva y de la franja)
AIRLINES_VE = [("Conviasa", ("e190", "a320"), (0.80, 0.10, 0.12), (0.10, 0.20, 0.60)),
               ("Avior", ("a320",), (0.08, 0.15, 0.40), (0.25, 0.55, 0.85)),
               ("Laser", ("a320",), (0.75, 0.08, 0.10), (0.08, 0.15, 0.40)),
               ("Estelar", ("a320",), (0.90, 0.40, 0.10), (0.35, 0.15, 0.45)),
               ("Turpial", ("a320",), (0.95, 0.75, 0.10), (0.08, 0.15, 0.40))]
AIRLINES_INT = [("Copa", ("a320",), (0.05, 0.12, 0.35), (0.85, 0.70, 0.20)),
                ("Avianca", ("a320",), (0.85, 0.05, 0.10), (0.85, 0.05, 0.10)),
                ("Wingo", ("a320",), (0.45, 0.15, 0.60), (0.45, 0.15, 0.60))]
# aeropuertos venezolanos con vuelos comerciales (el internacional de Maiquetía también con aerolíneas extranjeras)
AIRLINE_AIRPORTS = {"SVMI": 0.35, "SVVA": 0.15, "SVBM": 0.0, "SVMG": 0.1, "SVMC": 0.15, "SVBC": 0.0, "SVPR": 0.0,
                    "SVJC": 0.0, "SVSA": 0.0, "SVBI": 0.0, "SVCB": 0.0, "SVER": 0.0, "SVPA": 0.0, "SVMD": 0.0}
JET_NAMES = {"a320": "Airbus 320", "e190": "Embraer 190"}
JET_GEAR_H = {"a320": 3.6, "e190": 3.0}
DIG_ES = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve"]


class AIJet(AIPlane):
    """Avión de línea: llegadas directas por la final larga, salidas con ascenso rápido y, si tiene que
    hacer motor y al aire, un circuito amplio a 2500 ft."""
    aim = 380.0
    max_vs = 10.0
    max_sink = 6.5
    accel = 2.2
    vr = 135 * KT
    min_spd = 125 * KT
    hold_off = 70.0
    flare_vs = -1.2
    flare_h = 3.0
    jet = True

    def __init__(self, world, kind, type_id, airline, number, livery):
        self.gear_h = JET_GEAR_H[type_id]
        self.airline = airline
        self.livery = livery
        self.spoken = f"{airline} " + " ".join(DIG_ES[int(c)] for c in str(number))
        super().__init__(world, kind, type_id, JET_NAMES[type_id], f"{airline} {number}")

    def _pattern(self):
        thr, hdg, d, r, e, L = self._frame()
        g = math.tan(math.radians(3.0))

        def P(a, l, alt, kt, leg):
            p = thr + d * a + r * l
            return (p[0], p[1], alt, kt * KT, leg)
        return [P(L + 3000, 0, e + 1500 * FT, 170, "salida"), P(L + 6000, -4000, e + 2500 * FT, 180, "viento cruzado"),
                P(0, -5500, e + 2500 * FT, 180, "viento en cola"), P(-9000, -5500, e + 2500 * FT, 170, "base"),
                P(-12000, 0, e + (12000 + self.aim) * g, 155, "aproximación"),
                P(-3000, 0, e + (3000 + self.aim) * g, 142, "final"), P(-600, 0, e + (600 + self.aim) * g, 140, "final"),
                P(self.aim, 0, e, 135, "toma")]

    def _build(self, start_leg):
        thr, hdg, d, r, e, L = self._frame()
        pat = self._pattern()
        if self.kind == "llegada":
            # aproximación directa desde la final larga (dentro del escenario)
            ref = self.world.home.ref
            far = 15000.0
            while far > 8000 and np.linalg.norm(thr - d * far - ref) > 21000:
                far -= 1000
            p = thr - d * far
            self.wp = pat[5:]
            self.wp[0] = (*self.wp[0][:4], "aproximación")
            self._place_air(p, e + (far + self.aim) * math.tan(math.radians(3.0)) + 20, 165 * KT)
            self.heading = hdg
        else:
            super()._build(start_leg)
            if self.kind == "salida":
                self.wp = [pat[0], (*(thr + d * (L + 16000))[:2], e + 6000 * FT, 230 * KT, "salida")]
            self.leg = self.wp[0][4] if self.wp else ""


class Traffic:
    def __init__(self, world, density=2):
        self.world = world
        self.planes = []
        self.density = density
        self.enabled = True
        self.timer = 5.0
        self.rng = random.Random(7)
        self.ta_alert = None            # avión que dispara el aviso de tráfico

    def reset(self):
        self.planes = []
        self.timer = 3.0
        if not self.enabled or getattr(self.world.home, "offscene", False):
            return
        # tráfico inicial: dos en el circuito en distintos tramos, lejos del alumno
        ac = self.world.ac
        thr, hdg, d, r = self.world.runway_frame()
        along = (ac.pos[0] - thr[0]) * d[0] + (ac.pos[1] - thr[1]) * d[1]
        lat = (ac.pos[0] - thr[0]) * r[0] + (ac.pos[1] - thr[1]) * r[1]
        on_final = not ac.on_ground and along < 0 and abs(lat) < 1500
        on_downwind = not ac.on_ground and lat < -700
        legs = (2, 3) if on_final else ((6, 2) if on_downwind else (3, 6))
        for k in legs:
            self.spawn("circuito", start_leg=k)
        if self.airline_share() > 0:
            # aeropuerto comercial: un avión de línea en la final larga (o esperando para salir si el alumno va en final)
            self.spawn_jet("salida" if on_final else "llegada")

    def callsign(self):
        """Matrícula del tráfico según el país del escenario (Venezuela YV1234, México XB-ABC, España EC-ABC…)."""
        country = (self.world.location or {}).get("country", "")
        if country in NUMERIC_REG:
            return NUMERIC_REG[country] + "".join(self.rng.choice("0123456789") for _ in range(4))
        pre = LETTER_REG.get(country, "EC-")
        return pre + "".join(self.rng.choice(LETTERS) for _ in range(3))

    def airline_share(self):
        """Proporción de aviones de línea en este aeródromo (0 si no tiene vuelos comerciales o la pista es corta)."""
        w = self.world
        if (w.location or {}).get("country", "") != "VE" or w.home.ident not in AIRLINE_AIRPORTS:
            return 0.0
        if w.active_rw is None or w.active_rw.length < 1900:
            return 0.0
        return 0.6

    def spawn_jet(self, kind):
        # una llegada o una salida de línea a la vez (separación real entre reactores)
        for o in self.planes:
            if getattr(o, "jet", False) and o.kind == kind and not o.done and (kind == "salida" and o.state in ("espera", "alineando", "carrera")
                                                             or kind == "llegada" and o.state == "vuelo"):
                return None
        intl = AIRLINE_AIRPORTS.get(self.world.home.ident, 0.0)
        pool = AIRLINES_INT if self.rng.random() < intl else AIRLINES_VE
        name, types, tail, stripe = self.rng.choice(pool)
        tid = self.rng.choice(types)
        number = self.rng.choice(range(100, 999)) if name != "Copa" else self.rng.choice(range(200, 899))
        p = AIJet(self.world, kind, tid, name, number, (tail, stripe))
        self.planes.append(p)
        return p

    def spawn(self, kind, start_leg=0):
        if kind in ("llegada", "salida") and self.rng.random() < self.airline_share():
            p = self.spawn_jet(kind)
            if p is not None:
                return p
        tid, tname = self.rng.choice(TYPES)
        p = AIPlane(self.world, kind, tid, tname, self.callsign(), start_leg)
        self.planes.append(p)
        return p

    def update(self, dt):
        if not self.enabled:
            # sin tráfico automático solo queda el que publica un simulador de ATC externo
            self.planes = [p for p in self.planes if getattr(p, "external", False)]
        for p in self.planes:
            p.update(dt)
        self.planes = [p for p in self.planes if not p.done]
        self.timer -= dt
        if self.enabled and self.timer <= 0 and not getattr(self.world.home, "offscene", False):
            self.timer = self.rng.uniform(70, 160)
            n_air = sum(1 for p in self.planes)
            if n_air < 2 + self.density:
                self.spawn(self.rng.choice(["llegada", "salida", "circuito"]))
        # aviso de tráfico (como el TAS del G1000) y colisión
        ac = self.world.ac
        self.ta_alert = None
        for p in self.planes:
            d = p.pos - ac.pos
            dist = math.sqrt(float(d @ d))
            if dist < (22.0 if getattr(p, "jet", False) else 11.0) and not ac.crashed and not (ac.on_ground and p.on_ground):
                ac._crash(f"Colisión con el {p.type_name} {p.callsign}")
                return
            if not ac.on_ground and not p.on_ground and dist < 0.9 * NM and abs(d[2]) < 600 * FT:
                if self.ta_alert is None or dist < self.ta_alert[1]:
                    self.ta_alert = (p, dist)

    def ahead_count(self):
        """Cuántos aviones IA van delante del alumno en el circuito (para el número de secuencia)."""
        return sum(1 for p in self.planes if p.leg in ("viento en cola", "base", "final", "toma") and not p.on_ground)
