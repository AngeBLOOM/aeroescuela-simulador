"""Maniobras del ACS que completan el programa de piloto privado:

  PA.IV.C/D  Despegue y aterrizaje en pista blanda
  PA.IV.E/F  Despegue y aterrizaje en pista corta (franquear un obstáculo de 50 ft)
  PA.IV.N    Motor y al aire (aproximación frustrada)
  PA.VII.A   Vuelo lento
  PA.VII.C   Pérdida con motor
  PA.V.B     Maniobras de referencia en tierra (virajes alrededor de un punto)
"""
import math

import numpy as np

from .lessons import (Lesson, LandingJudge, Monitor, Step, _LandingLesson, alt, hdg_err, mon_alt, mon_ball, mon_bank,
                      mon_hdg, mon_speed, rnd10)
from .mathx import FT, KT, NM, clamp, wrap180

CAT_TO = "2 · Despegues, aterrizajes y circuito"
CAT_MAN = "3 · Maniobras de vuelo"


def landed(w, L):
    return w.ac.on_ground and w.ac.gs < 2


# ------------------------------------------------------------------ pista corta
class L_PistaCorta(_LandingLesson):
    id = "pista_corta"
    title = "Despegue y aterrizaje en pista corta"
    category = CAT_TO
    acs = "PA.IV.E / PA.IV.F"
    duration = "8 min"
    guided = False
    brief = ("ACS PA.IV.E/F — Pista corta con un obstáculo de 50 ft al final. DESPEGUE: flaps 10, frenos pisados, potencia "
             "máxima, suelte frenos, rote a 51 kt y ascienda a Vx 62 kt (+10/-5) hasta pasar el obstáculo; luego Vy. "
             "ATERRIZAJE: final a 61 kt con flaps 30 (±5 kt ACS), toque en el punto o hasta 200 ft después, frenado máximo "
             "y detenga el avión en la menor distancia posible.")
    objectives = ["Vx 62 kt hasta franquear 50 ft", "Final a 61 ±5 kt", "Toma a 0–200 ft del punto (ACS)", "Frenado máximo"]

    def build(self, world):
        self.roll_start = None
        self.cleared = None
        L_len = self.rw.length
        self.obstacle = L_len - 0.0
        s = world.ac.sys
        s.flaps_cmd = 1

        def rolled(w, L):
            if L.roll_start is None and w.ac.gs > 2:
                L.roll_start = L.rw_local(w)[0]
            return not w.ac.on_ground and w.ac.agl > 2

        def over_obstacle(w, L):
            a = L.rw_local(w)[0]
            if L.cleared is None and a >= L.roll_start + 500:
                L.cleared = w.ac.agl / FT
            return L.cleared is not None

        steps = [
            Step("Flaps 10, frenos, potencia máxima; suelte y rote a 51 kt", rolled,
                 voice="Pista corta. Flaps diez, frenos pisados, potencia máxima. Suelte frenos y rote a cincuenta y un nudos."),
            Step("Vx 62 kt hasta pasar el obstáculo de 50 ft", over_obstacle,
                 voice="Mantenga sesenta y dos nudos hasta superar el obstáculo.",
                 monitors=[mon_speed(62, 5, 10, 20, "Velocidad Vx")]),
            Step("Obstáculo superado: Vy, flaps arriba, ascienda a 1000 ft", lambda w, L: w.ac.agl / FT > 900,
                 voice="Obstáculo superado. Velocidad Vy, flaps arriba y ascienda.",
                 monitors=[mon_speed(74, 5, 10, 10, "Velocidad Vy")]),
            Step("Vuelva a la final (le recolocamos en final corta)", self._go_final, voice="Bien. Ahora la toma en pista corta."),
        ]
        self.steps = steps + self.final_steps(world, 61)

    def _go_final(self, w, L):
        w.reposition("final3")
        w.ac.sys.flaps_cmd = len(w.ac.t.flap_settings) - 1
        return True

    def update(self, dt, world, events):
        super().update(dt, world, events)
        lj = self.landing
        if lj is not None and lj.touch is not None and getattr(self, "stop_at", None) is None and lj.stopped:
            self.stop_at = self.rw_local(world)[0] - lj.touch["along"]

    def extra_items(self, world):
        items = super().extra_items(world)
        c = self.cleared
        items.append(("Altura sobre el obstáculo (500 m, POH)", 15 if c is not None and c >= 50 else 0, 15,
                      f"{c:.0f} ft" if c is not None else "sin datos"))
        lj = self.landing
        if lj is not None and lj.touch is not None:
            a = lj.touch["along"] - lj.AIM
            items.append(("Toma de pista corta (0–200 ft del punto)", 15 if 0 <= a <= 61 else (6 if -15 <= a <= 120 else 0), 15,
                          f"{a / 0.3048:+.0f} ft del punto"))
            d = getattr(self, "stop_at", None)
            if d is not None:
                items.append(("Carrera de aterrizaje", 10 if d < 200 else (5 if d < 300 else 0), 10, f"{d:.0f} m"))
        return items


# ------------------------------------------------------------------ pista blanda
class L_PistaBlanda(_LandingLesson):
    id = "pista_blanda"
    title = "Despegue y aterrizaje en pista blanda"
    category = CAT_TO
    acs = "PA.IV.C / PA.IV.D"
    duration = "6 min"
    guided = False
    brief = ("ACS PA.IV.C/D — Pista de hierba blanda: el barro frena las ruedas. DESPEGUE: flaps 10, no se detenga en la "
             "pista, potencia máxima con el volante atrás para aligerar la rueda de morro; despegue a la menor velocidad posible "
             "y acelere en efecto suelo hasta Vx/Vy. ATERRIZAJE: toque con la menor velocidad posible, morro alto, un poco de "
             "potencia y mantenga el volante atrás.")
    objectives = ["Volante atrás en la carrera", "Despegue a baja velocidad", "Acelerar en efecto suelo", "Toma suave a baja velocidad"]

    def build(self, world):
        self.lift_ias = None
        self.nose_light = 0.0
        self.roll_t = 0.0
        world.ac.soft_field = True
        world.ac.sys.flaps_cmd = 1

        def off(w, L):
            if not w.ac.on_ground and w.ac.agl > 1.5 and L.lift_ias is None:
                L.lift_ias = w.ind.ias
            return L.lift_ias is not None

        steps = [
            Step("Flaps 10, potencia máxima y volante ATRÁS", off,
                 voice="Pista blanda. Flaps diez, potencia máxima y volante atrás para aligerar la rueda de morro."),
            Step("Efecto suelo: acelere a Vy antes de subir", lambda w, L: w.ac.agl / FT > 500,
                 voice="Mantenga el avión cerca del suelo y acelere hasta Vy antes de ascender.",
                 monitors=[mon_speed(74, 5, 10, 15, "Velocidad Vy")]),
            Step("Vuelva a la final (le recolocamos)", self._go_final, voice="Bien. Ahora la toma en pista blanda."),
        ]
        self.steps = steps + self.final_steps(world, 61)

    def _go_final(self, w, L):
        w.reposition("final3")
        w.ac.soft_field = True
        w.ac.sys.flaps_cmd = len(w.ac.t.flap_settings) - 1
        return True

    def update(self, dt, world, events):
        super().update(dt, world, events)
        ac = world.ac
        if self.idx == 0 and ac.on_ground and ac.gs > 3:
            self.roll_t += dt
            if ac.ctl_elev > 0.3:
                self.nose_light += dt

    def finish(self, success, reason, world):
        world.ac.soft_field = False
        super().finish(success, reason, world)

    def extra_items(self, world):
        items = super().extra_items(world)
        frac = self.nose_light / self.roll_t if self.roll_t > 0 else 0
        items.append(("Volante atrás en la carrera", round(15 * frac), 15, f"{frac * 100:.0f}% del tiempo"))
        li = self.lift_ias
        items.append(("Velocidad de despegue", 10 if li is not None and li < 55 else (5 if li is not None else 0), 10,
                      f"{li:.0f} kt" if li is not None else "no despegó"))
        lj = self.landing
        if lj is not None and lj.touch is not None:
            v = lj.touch["ias"]
            items.append(("Velocidad en la toma", 10 if v < 55 else (5 if v < 62 else 0), 10, f"{v:.0f} kt"))
        return items


# ------------------------------------------------------------------ motor y al aire
class L_MotorAire(_LandingLesson):
    id = "motor_aire"
    title = "Motor y al aire (aproximación frustrada)"
    category = CAT_TO
    acs = "PA.IV.N"
    duration = "4 min"
    start = "final3"
    guided = True
    brief = ("ACS PA.IV.N — En la final corta el instructor ordenará «motor y al aire» (por ejemplo, hay un avión en la "
             "pista). Sin dudar: POTENCIA MÁXIMA, actitud de ascenso, flaps a 20 enseguida y luego por etapas a 0 cuando "
             "haya velocidad y ascenso positivo, Vy 74 kt (+10/-5) y rumbo de pista desplazado al lado derecho.")
    objectives = ["Decisión y potencia máxima inmediata", "Flaps por etapas", "Vy 74 +10/-5 kt", "Rumbo de pista ±10°"]

    def build(self, world):
        self.t_cmd = None
        self.t_power = None
        self.min_alt = None
        self.flaps_ok = True
        H = self.hdg
        fs = self.final_steps(world, 65)
        app = fs[0]
        app.done = lambda w, L: w.ac.agl / FT < 300

        def cmd(w, L):
            L.t_cmd = L.t
            L.rings = []
            L.guided = False
            return True
        self.steps = [
            app,
            Step("¡MOTOR Y AL AIRE!", cmd, voice="¡Motor y al aire! ¡Motor y al aire!"),
            Step("Potencia máxima, actitud de ascenso, flaps 20", lambda w, L: w.ac.vs_fpm > 300 and w.ac.agl / FT > 400,
                 voice="Potencia máxima, actitud de ascenso y flaps veinte.", timeout=25,
                 hint="Potencia a fondo (Mayús+W) y suba la nariz."),
            Step(f"Flaps arriba por etapas, Vy 74 kt y rumbo {H:03.0f}", lambda w, L: w.ac.agl / FT > 1000 and w.ac.sys.flaps < 1,
                 voice="Retraiga los flaps por etapas y ascienda a Vy con rumbo de pista.",
                 monitors=[mon_speed(74, 5, 10, 20, "Velocidad Vy"), mon_hdg(H, 10, 15), mon_ball(5)]),
        ]
        self.landing = None

    def update(self, dt, world, events):
        super().update(dt, world, events)
        ac = world.ac
        if self.t_cmd is not None:
            if self.t_power is None and ac.sys.engine.throttle > 0.95:
                self.t_power = self.t - self.t_cmd
            a = ac.agl / FT
            self.min_alt = a if self.min_alt is None else min(self.min_alt, a)
            if ac.sys.flaps < 8 and world.ind.ias < 60 and not ac.on_ground:
                self.flaps_ok = False
        if ac.on_ground and self.t_cmd is not None:
            self.finish(False, "Tocó la pista durante el motor y al aire", world)

    def extra_items(self, world):
        tp = self.t_power
        return [("Potencia máxima tras la orden", 20 if tp is not None and tp < 2 else (10 if tp is not None and tp < 5 else 0), 20,
                 f"{tp:.1f} s" if tp is not None else "no se aplicó"),
                ("Altura mínima", 10 if self.min_alt is not None and self.min_alt > 150 else 0, 10,
                 f"{self.min_alt:.0f} ft AGL" if self.min_alt is not None else "—"),
                ("Flaps por etapas (sin perder velocidad)", 10 if self.flaps_ok else 0, 10,
                 "correcto" if self.flaps_ok else "flaps arriba con velocidad baja")]


# ------------------------------------------------------------------ vuelo lento
class L_VueloLento(Lesson):
    id = "vuelo_lento"
    title = "Vuelo lento"
    category = CAT_MAN
    acs = "PA.VII.A"
    duration = "4 min"
    start = "crucero"
    allow_stall = False
    brief = ("ACS PA.VII.A — Vuelo lento sin activar el aviso de pérdida. Reduzca potencia, flaps completos y mantenga una "
             "velocidad a la que cualquier aumento de ángulo de ataque produciría el aviso (unos 50 kt). Tolerancias ACS: "
             "altitud ±100 ft, rumbo ±10°, velocidad +10/-0 kt y alabeo ±10° en los virajes. Haga un viraje de 90° y vuelva.")
    objectives = ["Altitud ±100 ft", "Velocidad 50 +10/-0 kt", "Sin aviso de pérdida", "Viraje de 90° y regreso"]

    def build(self, world):
        A = round(world.cruise_alt_ft() / 100) * 100
        H0 = rnd10(world.ac.heading)
        H1 = (H0 + 90) % 360 or 360
        self.warn = 0.0
        self.steps = [
            Step("Reduzca potencia, flaps completos y desacelere a 50 kt", lambda w, L: w.ind.ias < 56 and w.ac.sys.flaps > 25,
                 voice="Reduzca potencia, flaps completos y desacelere a cincuenta nudos manteniendo la altitud.",
                 monitors=[mon_alt(A, 100, 10)], timeout=60, hint="Gases al 30 % y flaps completos (F tres veces)."),
            Step(f"Vuelo lento recto a rumbo {H0:03.0f} durante 40 s", lambda w, L: True, min_time=40,
                 voice="Mantenga cincuenta nudos, la altitud y el rumbo, con potencia.",
                 monitors=[mon_alt(A, 100, 15), mon_hdg(H0, 10, 10),
                           Monitor("Velocidad", lambda w: (w.ind.ias, 50 <= w.ind.ias <= 60, "50 +10/-0 kt"), 15, "{:.0f}", "kt")]),
            Step(f"Viraje de 90° a rumbo {H1:03.0f} (alabeo ≤ 20°)", lambda w, L: abs(hdg_err(w, H1)) < 8,
                 voice=f"Viraje suave a la derecha a rumbo {H1:03.0f}, sin superar veinte grados de alabeo.",
                 monitors=[mon_alt(A, 100, 10), Monitor("Alabeo", lambda w: (abs(math.degrees(w.ac.roll)),
                                                                             abs(math.degrees(w.ac.roll)) <= 22, "≤ 20°"), 10, "{:.0f}", "°")]),
            Step("Recupere: potencia, flaps por etapas, crucero", lambda w, L: w.ind.ias > 85 and w.ac.sys.flaps < 1,
                 voice="Recupere: potencia, flaps por etapas y vuelva al crucero.", monitors=[mon_alt(A, 100, 10)]),
        ]

    def update(self, dt, world, events):
        super().update(dt, world, events)
        if 1 <= self.idx <= 2 and world.ac.sys.stall_warning:
            self.warn += dt

    def extra_items(self, world):
        return [("Sin aviso de pérdida", 15 if self.warn < 1 else (7 if self.warn < 5 else 0), 15, f"{self.warn:.0f} s con aviso")]


# ------------------------------------------------------------------ pérdida con motor
class L_PerdidaMotor(Lesson):
    id = "perdida_motor"
    title = "Pérdida con motor (despegue y salida)"
    category = CAT_MAN
    acs = "PA.VII.C"
    duration = "3 min"
    start = "crucero"
    allow_stall = True
    brief = ("ACS PA.VII.C — Simula una pérdida en el ascenso tras el despegue. Velocidad de rotación, potencia al 65 % o "
             "más y suba la nariz progresivamente (unos 15–20°) hasta la pérdida. Recuperación: BAJE LA NARIZ (reduzca el ángulo "
             "de ataque), alas niveladas, potencia máxima y ascienda a Vy. Rumbo ±10° y alabeo ≤ 20° durante la entrada.")
    objectives = ["Reconocer la pérdida", "Bajar la nariz primero", "Potencia máxima", "Mínima pérdida de altura"]

    def build(self, world):
        H = rnd10(world.ac.heading)
        self.stall_alt = None
        self.min_alt = None
        self.stalled = False

        def stall(w, L):
            if w.ac.sys.stall_warning and w.ind.ias < 55:
                L.stalled = True
                L.stall_alt = w.ind.alt_ft
                return True
            return False

        def rec(w, L):
            a = w.ind.alt_ft
            L.min_alt = a if L.min_alt is None else min(L.min_alt, a)
            return w.ac.vs_fpm > 200 and w.ind.ias > 65 and not w.ac.sys.stall_warning
        self.steps = [
            Step("Potencia 65 % y nariz arriba progresivamente hasta la pérdida", stall,
                 voice="Potencia sesenta y cinco por ciento. Suba la nariz poco a poco hasta la pérdida, alas niveladas.",
                 monitors=[mon_hdg(H, 10, 10), Monitor("Alabeo", lambda w: (abs(math.degrees(w.ac.roll)),
                                                                            abs(math.degrees(w.ac.roll)) <= 20, "≤ 20°"), 10, "{:.0f}", "°")],
                 timeout=60, hint="Suba la nariz más: unos quince a veinte grados."),
            Step("¡PÉRDIDA! Nariz abajo, potencia máxima, alas niveladas, Vy", rec,
                 voice="¡Pérdida! Baje la nariz, potencia máxima, alas niveladas y ascienda a Vy."),
        ]

    def extra_items(self, world):
        if self.stall_alt is None or self.min_alt is None:
            return [("Recuperación", 0, 25, "no se completó")]
        lost = self.stall_alt - self.min_alt
        return [("Altura perdida en la recuperación", 25 if lost < 100 else (15 if lost < 200 else 5), 25, f"{lost:.0f} ft")]


# ------------------------------------------------------------------ virajes alrededor de un punto
class L_Punto(Lesson):
    id = "punto"
    title = "Virajes alrededor de un punto"
    category = CAT_MAN
    acs = "PA.V.B"
    duration = "5 min"
    start = "viento_cola"
    brief = ("ACS PA.V.B — Maniobra de referencia en tierra. A 800 ft sobre el terreno, describa un círculo de radio "
             "constante (unos 400 m) alrededor del punto marcado con el aro, compensando el viento: más alabeo con viento "
             "de cola (más velocidad respecto al suelo) y menos con viento de cara. Altitud ±100 ft, velocidad ±10 kt y alabeo "
             "máximo 45°. Dos vueltas completas.")
    objectives = ["Radio constante ±100 m", "Altitud 800 ft AGL ±100 ft", "Corregir la deriva del viento", "Dos vueltas"]

    def weather(self, w):
        super().weather(w)
        w.wind_kt = 12
        w.wind_dir = 270

    def build(self, world):
        ac = world.ac
        hv = np.array([math.cos(ac.yaw), math.sin(ac.yaw)])
        r = np.array([-hv[1], hv[0]])
        self.center = ac.pos[:2] + hv * 900 - r * 400
        # 800 ft sobre el campo, o 700 ft sobre el terreno más alto alrededor del punto (aeródromos entre montañas)
        T = world.terrain
        hmax = max(T.height(self.center[0] + dx, self.center[1] + dy)
                   for dx in range(-1500, 1501, 300) for dy in range(-1500, 1501, 300))
        A = round(max(world.home.elev / FT + 800, hmax / FT + 700) / 10) * 10
        self.R = 400.0
        self.turned = 0.0
        self.last_ang = None
        ac.place_in_air(ac.pos[0], ac.pos[1], A * FT, ac.heading, 90)

        def dist(w):
            return math.hypot(w.ac.pos[0] - self.center[0], w.ac.pos[1] - self.center[1])

        def two_turns(w, L):
            ang = math.atan2(w.ac.pos[1] - L.center[1], w.ac.pos[0] - L.center[0])
            if L.last_ang is not None:
                d = (ang - L.last_ang + math.pi) % (2 * math.pi) - math.pi
                L.turned += d
            L.last_ang = ang
            return abs(L.turned) >= 4 * math.pi
        self.steps = [
            Step("Acérquese al punto del aro y entre con viento de cola", lambda w, L: abs(dist(w) - L.R) < 120,
                 voice="Diríjase al punto marcado y entre en el círculo a cuatrocientos metros, con viento de cola.",
                 monitors=[mon_alt(A, 100, 5)], timeout=90, hint="El punto está marcado con el aro verde."),
            Step("Dos vueltas a radio constante (400 m)", two_turns,
                 voice="Mantenga el radio constante. Más alabeo con viento de cola y menos con viento de cara.",
                 monitors=[Monitor("Radio", lambda w: (dist(w), abs(dist(w) - L_Punto.R) < 100, "400 ±100 m"), 25, "{:.0f}", "m"),
                           mon_alt(A, 100, 15), mon_speed(90, 10, None, 10),
                           Monitor("Alabeo máximo", lambda w: (abs(math.degrees(w.ac.roll)), abs(math.degrees(w.ac.roll)) <= 45,
                                                               "≤ 45°"), 10, "{:.0f}", "°")]),
        ]
        self.allow_bank = False

    def update(self, dt, world, events):
        super().update(dt, world, events)
        gh = world.terrain.height(self.center[0], self.center[1])
        self.rings = [(np.array([self.center[0], self.center[1], -(gh + 3)]), 0.0, 25.0, (1.0, 0.9, 0.2, 0.9))]


L_Punto.R = 400.0

MANEUVER_LESSONS_TO = [L_PistaCorta, L_PistaBlanda, L_MotorAire]
MANEUVER_LESSONS = [L_VueloLento, L_PerdidaMotor, L_Punto]
