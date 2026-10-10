"""Lecciones de emergencias (ACS PA.IX y PA.VIII.E) con evaluación del procedimiento.

Cada lección provoca una falla real del módulo sim.emergencies y comprueba que el alumno
siga la lista de emergencia del manual (POH): rapidez, orden y resultado.
"""
import math

import numpy as np

from .lessons import (PPL, Lesson, Monitor, Step, alt, hdg_err, mon_alt, mon_speed, rnd10)
from .mathx import FT, KT, NM, clamp, quat_from_euler, quat_to_mat, wrap180

CAT = "4 · Emergencias"


def landed(w, L):
    return w.ac.on_ground and w.ac.gs < 2


def outcome(world, pts, ok_text="en tierra, sin daños"):
    if world.ac.crashed:
        return ("Resultado", 0, pts, "accidente")
    if world.ac.on_ground and world.ac.gs < 2:
        return ("Resultado", pts, pts, ok_text)
    return ("Resultado", 0, pts, "no terminó el aterrizaje")


def mon_bank_max(limit, weight=10):
    return Monitor("Alabeo", lambda w: (abs(math.degrees(w.ac.roll)), abs(math.degrees(w.ac.roll)) <= limit,
                                        f"≤ {limit}°"), weight, "{:.0f}", "°")


class _Emerg(Lesson):
    category = CAT
    acs = "PA.IX.C"
    duration = "5 min"
    fail_key = None
    fail_after = 12.0

    def build(self, world):
        self.t_fail = None
        self.t_fix = None
        self.marks = {}
        self.steps = self.make_steps(world)

    def fail_step(self, text, voice):
        def go(w, L):
            if L.t >= L.fail_after:
                w.emerg.trigger(L.fail_key)
                L.t_fail = L.t
                return True
            return False
        return Step(text, go, voice=voice)

    def mark(self, key):
        if key not in self.marks and self.t_fail is not None:
            self.marks[key] = self.t - self.t_fail

    def timing(self, name, key, good, ok, pts):
        t = self.marks.get(key)
        if t is None:
            return (name, 0, pts, "no se hizo")
        p = pts if t <= good else (pts // 2 if t <= ok else pts // 5)
        return (name, p, pts, f"a los {t:.0f} s")


# ------------------------------------------------------------------ fuego de motor
class L_Fuego(_Emerg):
    id = "fuego"
    title = "Fuego de motor en vuelo"
    fail_key = "fire"
    start = "crucero"
    brief = ("ACS PA.IX.C — Fallas de sistemas: fuego de motor. En crucero aparecerán humo y llamas en el morro. "
             "Elementos de memoria: MEZCLA CORTE (MOTOR OFF en el DA40), COMBUSTIBLE CERRADO, BOMBA OFF y MAESTRO OFF. "
             "Pique a unos 100 kt para ayudar a apagar las llamas y después planee para un aterrizaje forzoso. "
             "Si no corta el combustible, el fuego se extiende.")
    objectives = ["Cortar el combustible en menos de 10 s", "Maestro OFF", "Planeo controlado", "Aterrizaje forzoso seguro"]

    def make_steps(self, world):
        A = world.cruise_alt_ft()
        return [
            self.fail_step(f"Crucero estable a {A:.0f} ft", f"Mantenga el crucero a {A:.0f} pies."),
            Step("¡FUEGO! Mezcla CORTE y combustible CERRADO", lambda w, L: not w.ac.sys.failures["fire"],
                 voice="¡Fuego en el motor! Mezcla corte, combustible cerrado, maestro apagado.",
                 timeout=12, hint="Corte el combustible: mezcla a CORTE y selector de combustible en CERRADO."),
            Step("Planee y haga un aterrizaje forzoso", landed, voice="Fuego apagado. Planee y prepare el aterrizaje forzoso.",
                 monitors=[mon_speed(world.ac.t.v["vglide"], 10, None, 15, "Velocidad de planeo")]),
        ]

    def update(self, dt, world, events):
        super().update(dt, world, events)
        s = world.ac.sys
        e = s.engine
        if self.t_fail is not None:
            if (e.magnetos == 0 if world.ac.t.fadec else e.mixture < 0.1):
                self.mark("corte")
            if s.fuel_selector == 0:
                self.mark("combustible")
            if not s.master:
                self.mark("maestro")

    def extra_items(self, world):
        return [self.timing("Mezcla / MOTOR a corte", "corte", 8, 20, 20),
                self.timing("Selector de combustible CERRADO", "combustible", 12, 25, 15),
                self.timing("Interruptor maestro OFF", "maestro", 20, 40, 10),
                outcome(world, 15, "avión en tierra")]


# ------------------------------------------------------------------ humo en cabina
class L_Humo(_Emerg):
    id = "humo"
    title = "Humo en cabina (fuego eléctrico)"
    fail_key = "smoke"
    start = "viento_cola"
    brief = ("ACS PA.IX.C — Fuego eléctrico. En el circuito la cabina se llenará de humo con olor a cable quemado. "
             "Elementos de memoria: INTERRUPTOR MAESTRO OFF (corta la fuente), extintor si hay llamas, ventilar y aterrizar "
             "lo antes posible. Sin electricidad no tendrá flaps eléctricos ni radio: planifique la toma sin ellos.")
    objectives = ["Maestro OFF en menos de 10 s", "Extintor / ventilación", "Aterrizar sin flaps eléctricos"]

    def make_steps(self, world):
        return [
            self.fail_step("Vuelo en viento en cola, 1000 ft AGL", "Mantenga el viento en cola."),
            Step("¡HUMO! Interruptor MAESTRO OFF", lambda w, L: not w.ac.sys.master,
                 voice="¡Humo en cabina! Interruptor maestro apagado.", timeout=10,
                 hint="Apague el interruptor maestro (BAT)."),
            Step("Aterrice lo antes posible", landed, voice="Bien. Ventile la cabina y aterrice lo antes posible.",
                 monitors=[mon_speed(world.ac.t.v["vapp"], 10, None, 10, "Velocidad de aproximación")]),
        ]

    def update(self, dt, world, events):
        super().update(dt, world, events)
        s = world.ac.sys
        if self.t_fail is not None:
            if not s.master:
                self.mark("maestro")
            if s.extinguisher <= 0:
                self.mark("extintor")

    def extra_items(self, world):
        return [self.timing("Maestro OFF", "maestro", 8, 20, 25),
                ("Extintor", 5 if "extintor" in self.marks else 0, 5, "usado" if "extintor" in self.marks else "no usado"),
                outcome(world, 15, "en tierra")]


# ------------------------------------------------------------------ falla de radio
class L_Radio(_Emerg):
    id = "radio_falla"
    title = "Falla de radio: señales luminosas"
    fail_key = "radio"
    start = "viento_cola"
    brief = ("Falla de comunicaciones en el circuito. Ponga el transpondedor en 7600 (en el panel de "
             "radios) y observe la torre: luz VERDE fija = autorizado a aterrizar; ROJA fija = ceda el paso y siga en el "
             "circuito. Hay tráfico en el circuito: no aterrice con luz roja.")
    objectives = ["Transpondedor 7600", "Esperar la luz verde", "Aterrizaje seguro"]

    def make_steps(self, world):
        self.red_landing = False
        return [
            self.fail_step("Vuelo en viento en cola", "Mantenga el viento en cola y llame a la torre si quiere."),
            Step("Sin radio: transpondedor 7600", lambda w, L: w.xpdr == 7600,
                 voice="La radio ha dejado de funcionar. Transpondedor siete seis cero cero.", timeout=20,
                 hint="Ponga el transpondedor en 7600."),
            Step("Observe la torre y aterrice con luz VERDE", landed,
                 voice="Observe las señales luminosas de la torre. Aterrice solo con luz verde fija."),
        ]

    def on_event(self, ev, data, world):
        super().on_event(ev, data, world)
        if ev == "contacto" and world.emerg.light is not None and world.emerg.light[0] == "rojo":
            self.red_landing = True

    def update(self, dt, world, events):
        super().update(dt, world, events)
        if self.t_fail is not None and world.xpdr == 7600:
            self.mark("7600")

    def extra_items(self, world):
        return [self.timing("Transpondedor 7600", "7600", 15, 40, 20),
                ("Respeto de las señales", 0 if self.red_landing else 25, 25,
                 "aterrizó con luz ROJA" if self.red_landing else "aterrizó con luz verde"),
                outcome(world, 15, "en tierra")]


# ------------------------------------------------------------------ el tren no baja
class L_Tren(_Emerg):
    id = "tren"
    title = "El tren no baja: extensión de emergencia"
    fail_key = "gear"
    aircraft = "pa28r"
    start = "viento_cola"
    fail_after = 0.5
    brief = ("Piper Arrow con el tren arriba en viento en cola. Al bajarlo, el motor del tren fallará: no habrá tres luces "
             "verdes. Lista: maestro y cortacircuito comprobados, palanca ABAJO, velocidad por debajo de 100 kt y EXTENSIÓN "
             "DE EMERGENCIA (palanca de extensión de emergencia). Compruebe las tres verdes y aterrice.")
    objectives = ["Detectar que no hay tres verdes", "Extensión de emergencia por debajo de 100 kt", "Aterrizar con el tren abajo"]

    def make_steps(self, world):
        self.ext_ias = None
        return [
            self.fail_step("Prepárese para bajar el tren", "Prepárese para bajar el tren."),
            Step("Baje el tren (G) y compruebe las luces", lambda w, L: w.ac.sys.gear_down and L.step.t > 6,
                 voice="Baje el tren y compruebe las tres luces verdes.", timeout=20, hint="Pulse G para bajar el tren."),
            Step("¡Sin tres verdes! Extensión de emergencia", lambda w, L: w.ac.sys.gear_pos > 0.99,
                 voice="No hay tres verdes. Velocidad por debajo de cien nudos y extensión de emergencia.", timeout=20,
                 hint="Mayúsculas más G: extensión de emergencia del tren."),
            Step("Tres verdes: aterrice", landed, voice="Tres verdes. Continúe y aterrice."),
        ]

    def update(self, dt, world, events):
        super().update(dt, world, events)
        if world.ac.sys.gear_emergency and self.ext_ias is None:
            self.ext_ias = world.ind.ias
            self.mark("emergencia")

    def extra_items(self, world):
        ok_speed = self.ext_ias is not None and self.ext_ias < 102
        return [self.timing("Extensión de emergencia", "emergencia", 25, 60, 20),
                ("Velocidad al extender", 10 if ok_speed else 0, 10,
                 f"{self.ext_ias:.0f} kt" if self.ext_ias is not None else "no se extendió"),
                outcome(world, 20, "tren abajo, en tierra")]


# ------------------------------------------------------------------ compensador desbocado
class L_Compensador(_Emerg):
    id = "compensador"
    title = "Compensador desbocado"
    fail_key = "trim"
    start = "crucero"
    brief = ("El compensador eléctrico empezará a moverse solo y el avión querrá encabritarse o picar. SUJETE EL VOLANTE "
             "y mantenga la altitud, pulse la desconexión del piloto automático y del compensador (Z) o saque el "
             "cortacircuito. Después compense a mano.")
    objectives = ["Mantener el control (altitud ±200 ft)", "Desconectar en menos de 5 s", "Compensar a mano"]

    def make_steps(self, world):
        A = world.cruise_alt_ft()
        return [
            self.fail_step(f"Crucero a {A:.0f} ft", f"Mantenga {A:.0f} pies."),
            Step("¡Compensador desbocado! Sujete y desconecte (Z)", lambda w, L: not w.ac.sys.trim_cb,
                 voice="¡El compensador se mueve solo! Sujete el volante y desconecte.", timeout=8,
                 hint="Pulse Z para desconectar el compensador eléctrico.",
                 monitors=[mon_alt(A, 200, 15, "Altitud durante la falla")]),
            Step("Compense a mano y mantenga la altitud 40 s", lambda w, L: True, min_time=40,
                 voice="Compense a mano con la rueda y mantenga la altitud.",
                 monitors=[mon_alt(A, 100, 15), mon_speed(105, 10, None, 10)]),
        ]

    def update(self, dt, world, events):
        super().update(dt, world, events)
        if self.t_fail is not None and not world.ac.sys.trim_cb:
            self.mark("desconexion")

    def extra_items(self, world):
        return [self.timing("Desconexión del compensador", "desconexion", 5, 12, 25)]


# ------------------------------------------------------------------ alternador
class L_Electrica(_Emerg):
    id = "alternador"
    title = "Falla del alternador: gestión eléctrica"
    fail_key = "alternator"
    start = "crucero"
    brief = ("El alternador fallará y la batería empezará a descargarse (amperímetro negativo, voltímetro bajando). "
             "Reconózcalo, apague las cargas que no necesite (luz de aterrizaje, calefacción del pitot, bomba) y "
             "regrese a aterrizar antes de que se agote la batería.")
    objectives = ["Detectar la falla (voltios / amperios)", "Reducir la carga eléctrica", "Regresar y aterrizar"]

    def make_steps(self, world):
        return [
            self.fail_step("Crucero: vigile voltímetro y amperímetro", "Crucero. Vigile los instrumentos del motor y el eléctrico."),
            Step("Reduzca la carga eléctrica", lambda w, L: not w.ac.sys.lights["landing"] and not w.ac.sys.pitot_heat
                 and not w.ac.sys.fuel_pump and L.step.t > 3, voice="Continúe el crucero.", timeout=60,
                 hint="El amperímetro marca descarga: apague luz de aterrizaje, calefacción del pitot y bomba."),
            Step("Regrese al aeródromo y aterrice", landed, voice="Bien. Regrese al aeródromo y aterrice."),
        ]

    def setup(self, world):
        super().setup(world)
        s = world.ac.sys
        s.lights["landing"] = True
        s.pitot_heat = True
        s.fuel_pump = True

    def update(self, dt, world, events):
        super().update(dt, world, events)
        if self.idx >= 2 and self.t_fail is not None:
            self.mark("cargas")

    def extra_items(self, world):
        bat = world.ac.sys.battery_charge * 100
        return [self.timing("Cargas reducidas", "cargas", 40, 90, 20),
                ("Batería al terminar", 15 if bat > 50 else (8 if bat > 20 else 0), 15, f"{bat:.0f} %"),
                outcome(world, 15, "en tierra")]


# ------------------------------------------------------------------ entrada en nubes
class L_IMC(Lesson):
    id = "imc"
    title = "Entrada inadvertida en nubes: viraje de 180°"
    category = CAT
    acs = "PA.VIII (instrumentos básicos)"
    duration = "4 min"
    start = "crucero"
    brief = ("Volará en VFR por debajo de nubes que van bajando. De pronto entrará en ellas y perderá toda referencia "
             "exterior. NO intente seguir: confíe en los instrumentos, nivele las alas y haga un viraje de 180° de régimen "
             "estándar (coordinador en la marca, máx. 20–30° de alabeo) manteniendo la altitud ±200 ft. Saldrá de las nubes "
             "por donde vino.")
    objectives = ["Alas niveladas y confianza en instrumentos", "Viraje de 180° con alabeo ≤ 30°", "Altitud ±200 ft"]

    def build(self, world):
        A = world.cruise_alt_ft()
        self.A = A
        self.H0 = rnd10(world.ac.heading)
        self.Hr = (self.H0 + 180) % 360 or 360
        wx = world.weather

        def enter_cloud(w, L):
            if L.t > 15:
                wx.cloud_cover = 1.0
                wx.cloud_base_ft = A - 600
                wx.cloud_top_ft = A + 2500
                wx.visibility_m = 250
                return True
            return False

        def reversed_(w, L):
            return abs(hdg_err(w, L.Hr)) < 12 and abs(math.degrees(w.ac.roll)) < 10

        def exit_cloud(w, L):
            wx.cloud_cover, wx.cloud_base_ft, wx.cloud_top_ft = 0.6, A + 900, A + 3000
            wx.visibility_m = 15000
            return True
        self.steps = [
            Step(f"VFR a {A:.0f} ft, rumbo {self.H0:03.0f}", enter_cloud, voice=f"Mantenga {A:.0f} pies y rumbo {self.H0:03.0f}."),
            Step(f"¡En nubes! Viraje de 180° a rumbo {self.Hr:03.0f}", reversed_,
                 voice=f"¡Ha entrado en nubes! Confíe en los instrumentos. Viraje de régimen estándar a rumbo {self.Hr:03.0f}.",
                 monitors=[mon_alt(A, 200, 20), mon_bank_max(30, 20)], timeout=90,
                 hint="Use el coordinador: ala en la marca de régimen estándar. Mantenga la altitud."),
            Step(f"Mantenga el rumbo {self.Hr:03.0f} y la altitud", lambda w, L: True, min_time=20,
                 voice="Bien. Mantenga el rumbo y la altitud hasta salir de las nubes.",
                 monitors=[mon_alt(A, 200, 10), Monitor("Rumbo", lambda w: (w.ac.heading, abs(hdg_err(w, self.Hr)) < 15,
                                                                           f"{self.Hr:03.0f} ±15°"), 10, "{:03.0f}", "°")]),
            Step("Fuera de las nubes", exit_cloud, voice="Ha salido de las nubes. Continúe en VFR."),
        ]

    def weather(self, w):
        super().weather(w)
        w.cloud_cover, w.cloud_base_ft, w.cloud_top_ft = 0.75, 5600, 9000
        w.visibility_m = 9000


# ------------------------------------------------------------------ actitudes anormales
def set_attitude(world, roll_deg, pitch_deg, ias_kt, throttle):
    ac = world.ac
    yaw = math.radians(ac.heading)
    ac.q = quat_from_euler(math.radians(roll_deg), math.radians(pitch_deg), yaw)
    R = quat_to_mat(ac.q)
    V = ias_kt * KT * math.sqrt(1.225 / getattr(ac, "rho", 1.225))
    ac.vel = R @ np.array([V, 0.0, 0.0]) + world.atmo.wind_at(500.0)
    ac.omega = np.zeros(3)
    for e in ac.sys.engines:
        e.throttle = throttle


class L_Actitudes(Lesson):
    id = "actitudes"
    title = "Recuperación de actitudes anormales"
    category = CAT
    acs = "PA.VIII.E"
    duration = "4 min"
    start = "crucero"
    allow_bank = True
    allow_fast = True
    allow_stall = True
    brief = ("ACS PA.VIII.E — Dentro de nubes, el instructor dejará el avión en una actitud anormal. Recupere solo con "
             "instrumentos. MORRO ARRIBA (velocidad bajando): potencia a fondo, morro abajo y después nivele las alas. "
             "MORRO ABAJO (velocidad subiendo): potencia a ralentí, nivele las alas y después suba el morro con suavidad. "
             "Termine con alas niveladas y vuelo horizontal.")
    objectives = ["Secuencia correcta de recuperación", "Sin pérdida ni exceso de velocidad", "Recuperar en menos de 10 s"]

    def weather(self, w):
        super().weather(w)
        w.cloud_cover, w.cloud_base_ft, w.cloud_top_ft = 1.0, 1500, 12000
        w.visibility_m = 300

    def build(self, world):
        self.rec = {}
        self.first = {}

        def recovered(w, L):
            ok = abs(math.degrees(w.ac.roll)) < 10 and abs(math.degrees(w.ac.pitch)) < 7 and abs(w.ac.vs_fpm) < 600
            return ok and L.step.t > 1.0

        def setup_a(w, L):
            set_attitude(w, 35, 25, 72, 0.55)
            L.case = "arriba"
            L.case_t0 = L.t
            L.thr0 = w.ac.sys.engine.throttle

        def setup_b(w, L):
            set_attitude(w, -45, -25, 125, 0.75)
            L.case = "abajo"
            L.case_t0 = L.t
            L.thr0 = w.ac.sys.engine.throttle
        self.case = None
        self.steps = [
            Step("Prepárese: en unos segundos el avión quedará en actitud anormal", lambda w, L: L.t > 6,
                 voice="Suelte los mandos. Voy a dejar el avión en una actitud anormal."),
            Step("¡MORRO ARRIBA! Recupere", recovered, enter=setup_a,
                 voice="Recupere. Morro arriba, velocidad bajando."),
            Step("Bien. Prepárese para la siguiente", lambda w, L: L.step.t > 5, voice="Bien. Prepárese para la siguiente."),
            Step("¡MORRO ABAJO! Recupere", recovered, enter=setup_b,
                 voice="Recupere. Morro abajo, velocidad subiendo."),
        ]

    def update(self, dt, world, events):
        prev = self.idx
        super().update(dt, world, events)
        if self.case and self.idx in (1, 3):
            e = world.ac.sys.engine
            dtc = self.t - self.case_t0
            if dtc < 3.0 and self.case not in self.first:
                if self.case == "arriba" and e.throttle > self.thr0 + 0.2:
                    self.first[self.case] = True
                if self.case == "abajo" and e.throttle < self.thr0 - 0.3:
                    self.first[self.case] = True
        if prev in (1, 3) and self.idx != prev:
            self.rec[self.case] = self.t - self.case_t0

    def extra_items(self, world):
        items = []
        for case, lab in (("arriba", "Morro arriba"), ("abajo", "Morro abajo")):
            t = self.rec.get(case)
            items.append((f"{lab}: tiempo de recuperación", 15 if t is not None and t < 10 else (7 if t is not None else 0), 15,
                          f"{t:.0f} s" if t is not None else "no recuperó"))
            items.append((f"{lab}: potencia correcta primero", 10 if self.first.get(case) else 0, 10,
                          "sí" if self.first.get(case) else "no"))
        return items


# ------------------------------------------------------------------ aterrizaje fuera de campo
class L_FueraCampo(_Emerg):
    id = "fuera_campo"
    title = "Aterrizaje forzoso fuera de campo"
    acs = "PA.IX.B"
    fail_key = "engine"
    start = "crucero"
    fail_after = 6.0
    allow_stall = False
    brief = ("ACS PA.IX.B — Lejos del aeródromo, el motor se parará. No podrá llegar a la pista: elija un campo llano y "
             "despejado, a ser posible con viento de cara. Mejor planeo, lista de causas, MAYDAY y transpondedor 7700, y un "
             "aterrizaje a la menor velocidad posible con alas niveladas. Si solo hay agua, haga un amerizaje controlado.")
    objectives = ["Mejor planeo", "Elección del campo y viento de cara", "Toma suave a baja velocidad"]

    def make_steps(self, world):
        self.touch = None
        return [
            self.fail_step("Crucero", "Mantenga el crucero."),
            Step("¡Motor parado! Planee y elija un campo", landed,
                 voice="¡Falla de motor! Mejor planeo, elija un campo y prepare el aterrizaje forzoso.",
                 monitors=[mon_speed(world.ac.t.v["vglide"], 10, None, 20, "Velocidad de mejor planeo")]),
        ]

    def on_event(self, ev, data, world):
        super().on_event(ev, data, world)
        if ev == "contacto" and self.touch is None and data.get("gear") in ("izq", "der", "nariz"):
            ac = world.ac
            wind = world.atmo.mean_wind(0.0)
            hv = np.array([math.cos(ac.yaw), math.sin(ac.yaw)])
            head = -float(wind[0] * hv[0] + wind[1] * hv[1]) / KT
            _, surf = world.terrain.surface(ac.pos[0], ac.pos[1])
            self.touch = dict(sink=max(0.0, data.get("sink", 0.0)) / FT * 60.0, ias=world.ind.ias, head=head, surf=surf,
                              roll=abs(math.degrees(ac.roll)))

    def update(self, dt, world, events):
        ac = world.ac
        if ac.crashed and getattr(ac, "ditched", False) and not self.done:
            self.touch = self.touch or dict(sink=0, ias=world.ind.ias, head=0, surf="agua", roll=0)
            self.finish(True, "Amerizaje controlado", world)
            self.success = True
            return
        super().update(dt, world, events)
        if self.t_fail is not None and world.xpdr == 7700:
            self.mark("7700")

    def extra_items(self, world):
        t = self.touch
        if t is None:
            return [("Aterrizaje", 0, 40, "no se aterrizó")]
        vs0 = world.ac.t.v.get("vs0", 48)
        return [("Velocidad en la toma", 15 if t["ias"] < vs0 * 1.25 else (8 if t["ias"] < vs0 * 1.5 else 0), 15, f"{t['ias']:.0f} kt"),
                ("Viento en la toma", 10 if t["head"] > -2 else 0, 10,
                 "de cara" if t["head"] > 2 else ("cruzado" if t["head"] > -2 else "de cola")),
                ("Terreno elegido", 10 if t["surf"] in ("cesped", "asfalto") else 6, 10,
                 {"cesped": "campo", "asfalto": "pavimento", "agua": "amerizaje"}.get(t["surf"], t["surf"])),
                self.timing("Transpondedor 7700", "7700", 60, 120, 5)]


EMERGENCY_LESSONS = [L_Fuego, L_Humo, L_Electrica, L_Radio, L_Tren, L_Compensador, L_IMC, L_Actitudes, L_FueraCampo]
