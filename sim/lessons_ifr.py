"""Procedimientos IFR del ACS de vuelo instrumental:

  IR.IV.A  Espera (holding) sobre un VOR, con entrada directa, en gota o paralela
  IR.VI.A  Aproximación de no precisión (localizador sin senda, LOC) hasta la MDA
  IR.VI.C  Aproximación frustrada
"""
import math

import numpy as np

from .lessons import IR, Monitor, Step, _LandingLesson, Lesson, alt, hdg_err, mon_alt, mon_speed
from .mathx import FT, KT, NM, clamp, wrap180

CAT = "6 · Vuelo instrumental (IFR)"


def ifr_weather(w, base_agl=700, vis=3000):
    w.wind_dir, w.wind_kt, w.turbulence = 330, 10, 0.2
    w.cloud_cover, w.cloud_base_ft, w.cloud_top_ft = 0.97, base_agl, 6000
    w.visibility_m = vis
    w.hour = 9.0


class L_Espera(Lesson):
    id = "espera"
    title = "Espera (holding) sobre un VOR"
    category = CAT
    acs = "IR.IV.A"
    standard = IR
    duration = "10 min"
    start = "crucero"
    brief = ("ACS IR.IV.A — Espera sobre el VOR con virajes a la DERECHA, tramos de 1 minuto y curso de acercamiento "
             "indicado. NAV1 y el OBS ya están puestos en el curso de acercamiento. Al llegar al VOR (bandera TO → FROM) haga "
             "la entrada que corresponda (directa, en gota o paralela), luego complete dos vueltas: viraje de régimen estándar, "
             "1 min de alejamiento, viraje y tramo de acercamiento con la aguja centrada. Tolerancias ACS: altitud ±100 ft, "
             "velocidad ±10 kt, rumbo ±10° y aguja dentro de 3/4 de escala en el acercamiento.")
    objectives = ["Entrada correcta", "Altitud ±100 ft", "Tramo de acercamiento centrado", "Dos vueltas completas"]

    def weather(self, w):
        super().weather(w)
        ifr_weather(w, 1500, 5000)

    def build(self, world):
        vors = [n for n in world.navaids if n.kind == "VOR"]
        vor = min(vors, key=lambda n: math.hypot(*(n.pos - world.home.ref)))
        self.vor = vor
        ac = world.ac
        self.inbound = (round(world.active_rw.heading / 10) * 10) % 360 or 360
        A = round(world.cruise_alt_ft() / 100) * 100
        self.A = A
        # se empieza a 8 NM del VOR, llegando con 60° respecto al curso de acercamiento
        b = math.radians(self.inbound + 180 + 60)
        p = vor.pos + np.array([math.cos(b), math.sin(b)]) * 8 * NM
        hdg = math.degrees(math.atan2(vor.pos[1] - p[1], vor.pos[0] - p[0])) % 360
        ac.place_in_air(p[0], p[1], A * FT, hdg, 90)
        world.nav1.freq = vor.freq
        world.nav1.obs = self.inbound
        world.ap.hdg_bug = round(hdg)
        self.crossings = 0
        self.prev_tf = None
        self.leg_times = []
        self.out_t0 = None
        self.entry = None

        def at_vor(w, L):
            return L.crossings >= 1

        def laps(w, L):
            return L.crossings >= 3
        inb = Monitor("Acercamiento (aguja)", lambda w: (w.nav1.cdi * 5,
                      (abs(hdg_err(w, self.inbound)) > 40) or abs(w.nav1.cdi) < 0.75, "≤ 3/4 escala"), 15, "{:+.1f}", "pt")
        self.steps = [
            Step(f"Diríjase al VOR {vor.ident} ({vor.freq:.2f}) a {A:.0f} ft", at_vor,
                 voice=f"Diríjase al VOR {vor.ident}. Espera publicada: curso de acercamiento {self.inbound:03.0f}, virajes a la derecha, "
                       "tramos de un minuto.",
                 monitors=[mon_alt(A, 100, 10), mon_speed(90, 10, None, 5)]),
            Step(f"Entrada y dos vueltas de espera (acercamiento {self.inbound:03.0f})", laps,
                 voice="Sobre el VOR. Haga la entrada y mantenga la espera.",
                 monitors=[mon_alt(A, 100, 20), mon_speed(90, 10, None, 10), inb]),
        ]

    def update(self, dt, world, events):
        super().update(dt, world, events)
        n = world.nav1
        tf = n.to_from
        if self.prev_tf == "TO" and tf == "FROM" and n.dme_nm is not None and n.dme_nm < 2.5:
            self.crossings += 1
            if self.crossings == 1:
                # entrada según el sector de llegada (AIM 5-3-8)
                d = wrap180(world.ac.heading - self.inbound)
                self.entry_ok = "directa" if -70 <= d <= 110 else ("paralela" if d < -70 else "gota")
                self.entry = self.entry_ok
        self.prev_tf = tf if tf else self.prev_tf
        # tiempo de alejamiento: desde el través del VOR hasta el viraje de acercamiento
        ac = world.ac
        if self.crossings >= 1:
            outb = (self.inbound + 180) % 360
            if abs(hdg_err(world, outb)) < 15 and self.out_t0 is None:
                self.out_t0 = self.t
            if self.out_t0 is not None and abs(hdg_err(world, outb)) > 40:
                self.leg_times.append(self.t - self.out_t0)
                self.out_t0 = None

    def extra_items(self, world):
        legs = [t for t in self.leg_times if t > 15]
        if legs:
            avg = sum(legs) / len(legs)
            p = 15 if 45 <= avg <= 80 else (7 if 30 <= avg <= 100 else 0)
            txt = f"media {avg:.0f} s (objetivo 60 s)"
        else:
            p, txt = 0, "sin tramos de alejamiento"
        return [("Tramo de alejamiento de 1 min", p, 15, txt),
                ("Entrada", 10 if self.entry else 0, 10, f"entrada {self.entry}" if self.entry else "no llegó al VOR")]


class L_LOC(_LandingLesson):
    id = "loc"
    title = "Aproximación de no precisión (LOC)"
    category = CAT
    acs = "IR.VI.A"
    standard = IR
    duration = "8 min"
    start = "final10"
    guided = False
    missed = False
    brief = ("ACS IR.VI.A — Aproximación LOC: solo localizador, SIN senda de planeo. Mantenga 2000 ft hasta el fijo de "
             "aproximación final (FAF, 4 NM del umbral por DME), después descienda a la altitud mínima de descenso "
             "(MDA = 450 ft sobre la pista) y manténgala (+100/-0 ft ACS) hasta el punto de aproximación frustrada (MAP, 0,5 NM). "
             "Si ve la pista antes del MAP, aterrice; si no, motor y al aire. Velocidad ±10 kt y aguja ≤ 3/4 de escala.")
    objectives = ["No bajar de la MDA", "Localizador ≤ 3/4 de escala", "Decisión en el MAP", "Aterrizaje o frustrada"]

    def weather(self, w):
        super().weather(w)
        ifr_weather(w, 2600 if not self.missed else 250, 4000 if not self.missed else 800)
        if not self.missed:
            w.cloud_base_ft = 650

    def build(self, world):
        ils = world.ils_for(world.active_rw, world.active_end)
        nav = world.nav1
        if ils:
            nav.freq, nav.obs = ils.freq, round(ils.course) % 360 or 360
        self.mda = self.elev_ft + 450
        self.faf_alt = self.elev_ft + 2000 if self.elev_ft + 2000 > alt(world) - 200 else alt(world)
        self.below_mda = 0.0
        self.decision = None
        thr = self.thr

        def dist_thr(w):
            return -((w.ac.pos[0] - thr[0]) * self.d[0] + (w.ac.pos[1] - thr[1]) * self.d[1]) / NM

        self.dist_thr = dist_thr
        loc = Monitor("Localizador", lambda w: (w.nav1.cdi * 5, w.nav1.valid and abs(w.nav1.cdi) < 0.75, "≤ 3/4 escala"), 15, "{:+.1f}", "pt")

        def mda_mon():
            return Monitor("MDA (+100/-0 ft)", lambda w: (alt(w), self.mda - 10 <= alt(w) <= self.mda + 100,
                                                         f"{self.mda:.0f} +100/-0 ft"), 15, "{:.0f}", "ft")

        def at_map(w, L):
            return dist_thr(w) < 0.5

        def visual(w, L):
            return w.weather.cloud_base_ft > L.mda + 100
        steps = [
            Step("Intercepte el localizador y manténgase hasta el FAF (4 NM)", lambda w, L: dist_thr(w) < 4.0,
                 voice="Intercepte el localizador. No descienda hasta el fijo de aproximación final, a cuatro millas.",
                 monitors=[mon_speed(90, 10, None, 5, "Velocidad")], timeout=200,
                 hint="Gire hacia la aguja y mantenga la altitud."),
            Step(f"FAF: descienda a la MDA {self.mda:.0f} ft", lambda w, L: alt(w) < L.mda + 80,
                 voice=f"Fijo de aproximación final. Descienda a la altitud mínima de descenso, {self.mda:.0f} pies.",
                 monitors=[loc, mon_speed(90, 10, None, 5, "Velocidad")]),
            Step("Mantenga la MDA hasta el MAP (0,5 NM) buscando la pista", at_map,
                 voice="Mantenga la altitud mínima y busque la pista.", monitors=[loc, mda_mon()]),
        ]
        if self.missed:
            H = self.hdg

            def climb(w, L):
                return alt(w) > L.elev_ft + 1900
            steps += [
                Step("MAP sin ver la pista: ¡MOTOR Y AL AIRE!", lambda w, L: w.ac.vs_fpm > 300,
                     voice="Punto de aproximación frustrada. No hay referencias visuales: motor y al aire.", timeout=15,
                     hint="Potencia máxima, actitud de ascenso y flaps por etapas."),
                Step(f"Frustrada publicada: rumbo {H:03.0f} y ascenso a {self.elev_ft + 2000:.0f} ft", climb,
                     voice=f"Aproximación frustrada: rumbo de pista y ascienda a {self.elev_ft + 2000:.0f} pies.",
                     monitors=[Monitor("Rumbo", lambda w: (w.ac.heading, abs(hdg_err(w, H)) < 10, f"{H:03.0f} ±10°"), 15, "{:03.0f}", "°"),
                               mon_speed(74, 5, 10, 10, "Velocidad Vy")]),
            ]
            self.landing = None
        else:
            steps += self.final_steps(world, 68)[1:]
        self.steps = steps

    def update(self, dt, world, events):
        super().update(dt, world, events)
        ac = world.ac
        if 1 <= self.idx <= 2 and alt(world) < self.mda - 50 and self.dist_thr(world) > 0.6:
            self.below_mda += dt
        if self.missed and ac.on_ground and not ac.crashed and not self.done:
            self.finish(False, "Aterrizó sin referencias visuales por debajo de mínimos", world)

    def extra_items(self, world):
        items = super().extra_items(world) if self.landing is not None else []
        b = self.below_mda
        items.append(("Respeto de la MDA antes del MAP", 25 if b < 1 else (10 if b < 5 else 0), 25,
                      "nunca por debajo" if b < 1 else f"{b:.0f} s por debajo de la MDA"))
        return items


class L_Frustrada(L_LOC):
    id = "frustrada"
    title = "Aproximación frustrada"
    acs = "IR.VI.C"
    missed = True
    brief = ("ACS IR.VI.C — La misma aproximación LOC, pero el techo estará por debajo de los mínimos: llegará al MAP sin ver "
             "la pista. Inicie la frustrada sin demora (potencia máxima, actitud de ascenso, flaps por etapas) y siga el "
             "procedimiento publicado: rumbo de pista y ascenso a 2000 ft sobre el aeródromo. Tolerancias ACS: rumbo ±10°, "
             "velocidad ±10 kt.")
    objectives = ["No bajar de la MDA", "Frustrada inmediata en el MAP", "Rumbo de pista ±10°", "Ascenso a la altitud publicada"]


IFR_LESSONS = [L_Espera, L_LOC, L_Frustrada]
