"""Procedimientos IFR del ACS de vuelo instrumental:

  IR.IV.A  Espera (holding) sobre un VOR, con entrada directa, en gota o paralela
  IR.VI.A  Aproximación de no precisión (localizador sin senda, LOC) hasta la MDA
  IR.VI.C  Aproximación frustrada
"""
import math

import numpy as np

from .lessons import IR, Monitor, Step, _LandingLesson, Lesson, alt, hdg_err, mon_alt, mon_speed, rnd10m
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
        self.inbound = rnd10m(world, world.active_rw.heading)     # verdadero; se publica en magnético
        A = round(world.cruise_alt_ft() / 100) * 100
        self.A = A
        # se empieza a 8 NM del VOR, llegando con 60° respecto al curso de acercamiento
        b = math.radians(self.inbound + 180 + 60)
        p = vor.pos + np.array([math.cos(b), math.sin(b)]) * 8 * NM
        hdg = math.degrees(math.atan2(vor.pos[1] - p[1], vor.pos[0] - p[0])) % 360
        ac.place_in_air(p[0], p[1], A * FT, hdg, 90)
        world.nav1.freq = vor.freq
        world.nav1.obs = world.mag(self.inbound)
        world.ap.hdg_bug = world.mag(hdg)
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
                 voice=f"Diríjase al VOR {vor.ident}. Espera publicada: curso de acercamiento {world.mag(self.inbound):03.0f}, virajes a la derecha, "
                       "tramos de un minuto.",
                 monitors=[mon_alt(A, 100, 10), mon_speed(90, 10, None, 5)]),
            Step(f"Entrada y dos vueltas de espera (acercamiento {world.mag(self.inbound):03.0f})", laps,
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
            nav.freq, nav.obs = ils.freq, world.mag(ils.course)
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
                Step(f"Frustrada publicada: rumbo {world.mag(H):03.0f} y ascenso a {self.elev_ft + 2000:.0f} ft", climb,
                     voice=f"Aproximación frustrada: rumbo de pista y ascienda a {self.elev_ft + 2000:.0f} pies.",
                     monitors=[Monitor("Rumbo", lambda w: (w.mag(w.ac.heading), abs(hdg_err(w, H)) < 10, f"{w.mag(H):03.0f} ±10°"), 15, "{:03.0f}", "°"),
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


class L_RNAV(_LandingLesson):
    id = "rnav"
    title = "Aproximación RNAV (GPS)"
    category = CAT
    acs = "IR.VI.B"
    standard = IR
    duration = "12 min"
    start = "final10"
    guided = False
    brief = ("ACS IR.VI.B — Aproximación RNAV (GPS) con senda vertical (LPV). Es una aproximación DE ENTRENAMIENTO, NO "
             "PUBLICADA, generada para la pista en servicio. El GPS ya la tiene cargada desde el IAF izquierdo y el CDI "
             "está en GPS: vuele al IAF, siga la ruta al IF manteniendo 2500 ft sobre la pista y vire al final. Desde 2 NM "
             "antes del FAF la escala es de 0,3 NM (APR) y aparece la senda (rombo magenta «V» en el PFD, aguja horizontal "
             "en el CDI): al centrarse, descienda por ella. Altura de decisión 250 ft sobre la pista; si no ve la pista, "
             "motor y al aire. Tolerancias ACS: ≤ 3/4 de escala lateral y vertical y velocidad ±10 kt. Puede usar el "
             "piloto automático en APR.")
    objectives = ["Seguir la ruta IAF → IF → FAF", "Lateral ≤ 3/4 de escala", "Senda ≤ 3/4 de escala",
                  "Velocidad ±10 kt", "Decisión a 250 ft sobre la pista", "Aterrizaje"]

    def weather(self, w):
        super().weather(w)
        ifr_weather(w, 600, 2500)

    def build(self, world):
        from . import rnav
        apr = rnav.build(world.home, world.active_rw, world.active_end)
        self.apr = apr
        iaf = apr.fixes.iaf_l
        r = np.array([-apr.dir[1], apr.dir[0]])                 # a la derecha del final
        p = iaf.pos - r * 3 * NM                                 # 3 NM antes del IAF izquierdo, volando hacia él
        world.ac.place_in_air(p[0], p[1], iaf.alt_ft * FT, apr.course + 90, 95, flaps_idx=0)
        world.gps.load_approach(apr, "L")
        world.cdi_src = "GPS"
        world.ap.alt_sel = round(iaf.alt_ft / 100) * 100
        da = apr.da_ft
        g = world.gps
        lat = Monitor("Lateral (GPS)", lambda w: (w.gps.cdi * 5, w.gps.valid and abs(w.gps.cdi) < 0.75, "≤ 3/4 escala"),
                      15, "{:+.1f}", "pt")
        vert = Monitor("Senda (GPS)", lambda w: (w.gps.gs * 5, w.gps.gs_valid and abs(w.gps.gs) < 0.75, "≤ 3/4 escala"),
                       15, "{:+.1f}", "pt")

        def role(w):
            t = w.gps.target
            return getattr(t, "role", "") if t is not None else ""

        def on_gp(w, L):
            return g.scale == "APR" and abs(g.cdi) < 0.3 and g.gs_valid and g.gs < 0.2
        self.steps = [
            Step(f"Ruta del GPS: IAF {iaf.ident} → IF a {iaf.alt_ft:.0f} ft (CDI en GPS)", lambda w, L: role(w) == "FAF",
                 voice=f"Aproximación RNAV de entrenamiento. Vuele al fijo inicial y siga la ruta del GPS al fijo "
                       f"intermedio a {iaf.alt_ft:.0f} pies.",
                 monitors=[mon_alt(iaf.alt_ft, 100, 10, "Altitud del tramo inicial"), mon_speed(95, 10, None, 5, "Velocidad")],
                 timeout=420, hint="Siga la aguja magenta: el GPS secuencia solo los tramos y avisa del viraje en el IF."),
            Step("Tramo intermedio: escala APR y capture la senda", on_gp,
                 voice="Tramo intermedio. A dos millas del fijo de aproximación final la escala pasa a aproximación. "
                       "Cuando el rombo de la senda llegue al centro, descienda.",
                 monitors=[lat, mon_speed(90, 10, None, 5, "Velocidad")], timeout=300,
                 hint="Mantenga la altitud hasta que la senda (rombo magenta) baje al centro."),
            Step("Siga lateral y senda hasta 1000 ft sobre la pista", lambda w, L: alt(w) < self.elev_ft + 1000,
                 voice="Establecido en la senda. Descienda con las dos agujas centradas.",
                 monitors=[lat, vert, mon_speed(90, 10, None, 6, "Velocidad")]),
            Step(f"70 kt y flaps completos; altura de decisión {da:.0f} ft", lambda w, L: alt(w) < da + 20,
                 voice=f"Reduzca a setenta nudos y extienda flaps. Altura de decisión {da:.0f} pies.",
                 monitors=[lat, vert]),
        ] + self.final_steps(world, 68)[1:]
        self.minimums_called = False
        self.da = da

    def coaching(self, dt, world):
        super().coaching(dt, world)
        if not self.minimums_called and alt(world) < self.da + 60 and self.idx >= 3:
            self.minimums_called = True
            self.messages.append(("mínimos", "callout"))


IFR_LESSONS = [L_Espera, L_LOC, L_Frustrada, L_RNAV]
