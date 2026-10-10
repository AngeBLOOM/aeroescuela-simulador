"""Programa de entrenamiento con instructor virtual y evaluación automática.

El programa sigue la estructura y las tolerancias de los estándares oficiales de
examen práctico de la FAA (Airman Certification Standards):

  * Piloto Privado – Avión (FAA-S-ACS-6C): áreas de operación PA.II a PA.X.
  * Habilitación de Vuelo Instrumental – Avión (FAA-S-ACS-8C): IR.III a IR.VII.

Son equivalentes en contenido a la prueba de pericia EASA PPL(A) / IR(A).
Cada lección indica su tarea ACS y evalúa con la tolerancia oficial.

Todas las lecciones son relativas a la "pista en servicio" del mundo, de modo
que funcionan en el escenario escuela y en cualquier aeropuerto real.
"""
import math

import numpy as np

from .mathx import FT, KT, NM, clamp, wrap180, wrap360

PPL = "FAA-S-ACS-6C Piloto Privado"
IR = "FAA-S-ACS-8C Vuelo Instrumental"
MEL = "FAA-S-ACS-7B Piloto Comercial · clase multimotor"


# =================================================================== utilidades
class Monitor:
    def __init__(self, name, fn, weight, fmt="", unit=""):
        self.name = name
        self.fn = fn              # fn(world) -> (valor, ok:bool, objetivo_txt)
        self.weight = weight
        self.ok_t = 0.0
        self.tot_t = 0.0
        self.value = None
        self.ok = True
        self.target = ""
        self.fmt = fmt
        self.unit = unit

    def update(self, dt, world):
        v, ok, tgt = self.fn(world)
        self.value, self.ok, self.target = v, ok, tgt
        self.tot_t += dt
        if ok:
            self.ok_t += dt

    @property
    def frac(self):
        return self.ok_t / self.tot_t if self.tot_t > 0.5 else 1.0


class Step:
    def __init__(self, text, done, voice=None, monitors=(), enter=None, timeout=None, hint=None, min_time=0.0):
        self.text = text
        self.done = done              # done(world, lesson) -> bool
        self.voice = voice if voice is not None else text
        self.monitors = list(monitors)
        self.enter = enter
        self.timeout = timeout
        self.hint = hint
        self.min_time = min_time
        self.t = 0.0


def ias(w):
    return w.ind.ias


def alt(w):
    return w.ind.alt_ft


def hdg_err(w, target):
    return wrap180(w.ac.heading - target)


def rnd10(h):
    return (round(h / 10.0) * 10) % 360 or 360


def rnd10m(w, true_hdg):
    """Rumbo verdadero cuyo valor magnético (el que marca el direccional) es múltiplo de 10: los rumbos se
    dictan redondos en magnético y se evalúan en verdadero."""
    return w.true(rnd10(w.mag(true_hdg)))


def turn(h, d):
    return wrap360(h + d)


def mon_speed(target, tol_lo, tol_hi=None, weight=10, name="Velocidad"):
    """Velocidad con tolerancia asimétrica (p. ej. ACS: Vy +10/-5)."""
    hi = tol_lo if tol_hi is None else tol_hi
    txt = f"{target} ±{tol_lo} kt" if tol_hi is None else f"{target} +{hi}/-{tol_lo} kt"
    return Monitor(name, lambda w: (ias(w), target - tol_lo <= ias(w) <= target + hi, txt), weight, "{:.0f}", "kt")


def mon_alt(target_ft, tol, weight=10, name="Altitud"):
    return Monitor(name, lambda w: (alt(w), abs(alt(w) - target_ft) <= tol, f"{target_ft:.0f} ±{tol} ft"), weight, "{:.0f}", "ft")


def mon_hdg(target, tol, weight=10, name="Rumbo"):
    return Monitor(name, lambda w: (w.mag(w.ac.heading), abs(hdg_err(w, target)) <= tol, f"{w.mag(target):03.0f} ±{tol}°"), weight, "{:03.0f}", "°")


def mon_ball(weight=5):
    return Monitor("Coordinación (bola)", lambda w: (w.ind.slip, abs(w.ind.slip) < 0.35, "bola centrada"), weight, "{:+.1f}", "")


def mon_bank(target, tol, weight=10, name="Alabeo"):
    return Monitor(name, lambda w: (abs(math.degrees(w.ac.roll)), abs(abs(math.degrees(w.ac.roll)) - target) <= tol,
                                    f"{target} ±{tol}°"), weight, "{:.0f}", "°")


# =================================================================== aterrizaje
class LandingJudge:
    """Evalúa toma de contacto y carrera según ACS PA.IV.B/D:
    toma en actitud correcta, dentro de 400 ft (122 m) más allá del punto especificado,
    sin deriva lateral y con el eje longitudinal alineado con el eje de pista."""

    AIM = 120.0          # punto especificado (m desde el umbral)
    WINDOW = 122.0       # 400 ft

    def __init__(self, runway, ident):
        self.rw = runway
        self.ident = ident
        self.touch = None
        self.bounces = 0
        self.nose_first = False
        self.stopped = False
        self.off_runway = False
        self.airborne_after = 0.0
        self.last_contact = False
        self.armed = False

    def update(self, dt, world, events):
        ac = world.ac
        if not self.armed:
            # solo se evalúa una toma después de haber volado
            if not ac.on_ground and ac.agl > 15:
                self.armed = True
            return
        mains = ac.gear_contact.get("izq", False) or ac.gear_contact.get("der", False)
        nose = ac.gear_contact.get("nariz", False)
        if self.touch is None:
            if nose and not mains and ac.on_ground:
                self.nose_first = True
            if mains or (nose and ac.on_ground):
                along, lat = self.rw.local(ac.pos[0], ac.pos[1], self.ident)
                thr, hdg_rw, d = self.rw.end(self.ident)
                r = np.array([-d[1], d[0]])
                drift = float(ac.vel[0] * r[0] + ac.vel[1] * r[1])
                sink = -ac.vs_fpm
                for ev, data in events:
                    if ev == "contacto" and data.get("gear") in ("izq", "der", "nariz"):
                        sink = max(sink, data["sink"] / FT * 60.0)
                self.touch = dict(sink=max(0.0, sink), along=along, lat=lat, ias=world.ind.ias,
                                  pitch=math.degrees(ac.pitch), drift=drift,
                                  align=abs(wrap180(ac.heading - hdg_rw)),
                                  on_runway=self.rw.contains(ac.pos[0], ac.pos[1], 2.0))
                self.last_contact = True
        else:
            if not ac.on_ground:
                self.airborne_after += dt
                if self.airborne_after > 0.6 and self.last_contact and ac.agl > 0.6:
                    self.bounces += 1
                    self.last_contact = False
            else:
                self.airborne_after = 0.0
                self.last_contact = True
                if not self.rw.contains(ac.pos[0], ac.pos[1], 1.0) and ac.gs > 5:
                    self.off_runway = True
            if ac.on_ground and ac.gs < 1.5:
                self.stopped = True

    @property
    def done(self):
        return self.touch is not None and self.stopped

    def score(self, max_pts=40):
        t = self.touch
        if t is None:
            return [("Aterrizaje", 0, max_pts, "No se aterrizó")]
        items = []
        s = t["sink"]
        if s < 200:
            p, c = 1.0, f"Suave ({s:.0f} ft/min)"
        elif s < 400:
            p, c = 0.85, f"Bueno ({s:.0f} ft/min)"
        elif s < 650:
            p, c = 0.55, f"Firme ({s:.0f} ft/min)"
        else:
            p, c = 0.2, f"Duro ({s:.0f} ft/min)"
        items.append(("Régimen de descenso en la toma", round(p * max_pts * 0.3), round(max_pts * 0.3), c))
        a = t["along"]
        aim, win = self.AIM, self.WINDOW
        if not t["on_runway"]:
            p, c = 0.0, "Fuera de la pista"
        elif aim <= a <= aim + win:
            p, c = 1.0, f"Dentro de los 400 ft tras el punto ({a:.0f} m del umbral) — ACS"
        elif a < aim:
            p, c = 0.4, f"Antes del punto especificado ({a:.0f} m) — fuera de estándar"
        elif a <= aim + 2 * win:
            p, c = 0.5, f"{(a - aim) / 0.3048:.0f} ft pasado el punto (máx. ACS 400 ft)"
        else:
            p, c = 0.1, f"Toma larga: {(a - aim) / 0.3048:.0f} ft pasado el punto"
        items.append(("Punto de toma (±400 ft)", round(p * max_pts * 0.25), round(max_pts * 0.25), c))
        lat = abs(t["lat"])
        p = 1.0 if lat < 3 else (0.7 if lat < 6 else (0.3 if lat < 12 else 0.0))
        items.append(("Sobre el eje de pista", round(p * max_pts * 0.15), round(max_pts * 0.15), f"Desvío {lat:.1f} m"))
        p = 1.0
        com = []
        if self.nose_first:
            p -= 0.6
            com.append("rueda de morro primero")
        if t["pitch"] < -0.5:
            p -= 0.2
            com.append("sin recogida (flare)")
        if self.bounces:
            p -= 0.3 * self.bounces
            com.append(f"{self.bounces} rebote(s)")
        if abs(t["drift"]) > 1.5 or t["align"] > 6:
            p -= 0.3
            com.append(f"deriva lateral {abs(t['drift']):.1f} m/s / desalineado {t['align']:.0f}°")
        items.append(("Actitud y alineación en la toma", round(clamp(p, 0, 1) * max_pts * 0.2), round(max_pts * 0.2),
                      ", ".join(com) if com else "Actitud correcta, sin deriva, alineado"))
        p = 0.0 if self.off_runway else 1.0
        items.append(("Control direccional en la carrera", round(p * max_pts * 0.1), round(max_pts * 0.1),
                      "Salida de pista" if self.off_runway else "Correcto"))
        return items


# =================================================================== lección base
class Lesson:
    id = "base"
    title = "Lección"
    category = "General"
    acs = ""                  # código de tarea ACS
    standard = PPL
    brief = ""
    objectives = []
    start = "pista"
    cold = False
    aircraft = "c172"
    duration = "5 min"
    school_only = False

    def __init__(self):
        self.steps = []
        self.idx = 0
        self.t = 0.0
        self.messages = []
        self.done = False
        self.success = False
        self.fail_reason = ""
        self.rings = []
        self.landing = None
        self.penalties = []
        self.all_monitors = []
        self._coach = {}
        self.checklist = None
        self.callouts_done = set()

    # ----- configuración del mundo
    def weather(self, w):
        w.wind_dir, w.wind_kt, w.gust_kt, w.turbulence = 360, 4, 0, 0.05
        w.cloud_cover, w.cloud_base_ft, w.cloud_top_ft = 0.3, 4800, 6200
        w.visibility_m, w.hour, w.qnh_hpa = 30000, 10.5, 1015.0
        w.wind_shear = False
        w.rain, w.storm = 0.0, False

    def setup(self, world):
        self.weather(world.weather)
        # la lluvia de la lección ya está cayendo al empezar (y la pista, mojada si llueve fuerte)
        at = world.atmo
        at.rain_here = world.weather.rain
        at.wet = min(1.0, world.weather.rain * 1.4) if world.weather.rain > 0.3 else 0.0
        at.flash, at.thunder = 0.0, []
        if not world.is_school:
            # nubes y viento relativos al aeródromo real
            e = world.home.elev / FT
            w = world.weather
            w.cloud_base_ft += e
            w.cloud_top_ft += e
            # el viento sopla por la pista en servicio salvo que la lección pida otra cosa
            rw = max(world.home.runways, key=lambda r: r.length)
            if getattr(self, "wind_rel", None) is not None:
                w.wind_dir = (rw.heading + self.wind_rel) % 360
            else:
                w.wind_dir = rw.heading
        world.reposition(self.start, cold=self.cold)
        for k in world.ac.sys.failures:
            world.ac.sys.failures[k] = False
        self.rw = world.active_rw
        self.ident = world.active_end
        self.thr, self.hdg, self.d, self.r = world.runway_frame()
        self.elev_ft = world.home.elev / FT
        self.build(world)
        # build puede recolocar el avión (p. ej. más alto): los instrumentos arrancan ya en la posición final,
        # sin que el altímetro «viaje» y dé un pico falso de velocidad vertical
        world.ind.reset(world.ac, world.kollsman)
        self.idx = 0
        self._enter(world)

    def build(self, world):
        pass

    def rw_local(self, w):
        return self.rw.local(w.ac.pos[0], w.ac.pos[1], self.ident)

    def at(self, along, lat):
        """Punto en coordenadas de pista (a lo largo desde el umbral, lateral a la derecha)."""
        return self.thr + self.d * along + self.r * lat

    # ----- mensajes
    def say(self, text, voice=True, key=None, gap=0.0):
        if key:
            last = self._coach.get(key, -999)
            if self.t - last < gap:
                return
            self._coach[key] = self.t
        self.messages.append((text, voice))

    def coach(self, key, cond, text, gap=12.0):
        if cond:
            self.say(text, True, key=key, gap=gap)

    # ----- ciclo
    @property
    def step(self):
        return self.steps[self.idx] if self.idx < len(self.steps) else None

    def _enter(self, world):
        st = self.step
        if st is None:
            return
        st.t = 0.0
        if st.enter:
            st.enter(world, self)
        self.say(st.voice if isinstance(st.voice, str) else st.text)
        for m in st.monitors:
            if m not in self.all_monitors:
                self.all_monitors.append(m)

    def update(self, dt, world, events):
        if self.done:
            return
        self.t += dt
        ac = world.ac
        for ev, data in events:
            self.on_event(ev, data, world)
        if ac.crashed:
            self.finish(False, ac.crash_reason, world)
            return
        if self.landing is not None:
            self.landing.update(dt, world, events)
        st = self.step
        if st is None:
            self.finish(True, "", world)
            return
        st.t += dt
        for m in st.monitors:
            m.update(dt, world)
        self.coaching(dt, world)
        if st.t >= st.min_time and st.done(world, self):
            self.idx += 1
            if self.step is None:
                self.finish(True, "", world)
            else:
                self._enter(world)
        elif st.timeout and st.t > st.timeout:
            if st.hint:
                self.say(st.hint, key="hint" + str(self.idx), gap=25)
            st.t = st.min_time

    def coaching(self, dt, world):
        ac = world.ac
        self.coach("stall", ac.sys.stall_warning and not ac.on_ground and not getattr(self, "allow_stall", False),
                   "Aviso de pérdida: baje la nariz y aplique potencia.", 8)
        self.coach("vne", world.ind.ias > ac.t.v["vno"] + 8 and not getattr(self, "allow_fast", False),
                   "Velocidad excesiva: reduzca potencia y suba la nariz.", 10)
        self.coach("flapspd", ac.sys.flaps > 11 and world.ind.ias > ac.t.v["vfe"] + 3,
                   "Cuidado, velocidad por encima de la máxima con flaps.", 15)
        self.coach("bank", abs(math.degrees(ac.roll)) > 50 and not getattr(self, "allow_bank", False) and not ac.on_ground,
                   "Alabeo excesivo, nivele las alas.", 8)
        self.coach("taws", not ac.on_ground and ac.agl / FT < 300 and ac.vs_fpm < -900 and self.landing is None,
                   "¡Terreno! ¡Suba!", 6)
        self.coach("gear", ac.t.retractable and ac.sys.gear_pos < 0.5 and not ac.on_ground and ac.agl / FT < 400
                   and ac.vs_fpm < -200, "¡Atención: tren arriba! Baje el tren (G).", 6)

    def on_event(self, ev, data, world):
        if ev == "sobrecarga":
            self.penalties.append(("Sobrecarga estructural", -15, f"{data['g']:.1f} G"))
            self.say("Ha sobrepasado el límite de carga G.")
        elif ev == "cola":
            self.penalties.append(("Toque de cola", -10, "rotación excesiva"))
            self.say("Ha tocado la cola contra la pista: rotación excesiva.")

    def finish(self, success, reason, world):
        if self.done:
            return
        self.done = True
        self.success = success and not world.ac.crashed
        self.fail_reason = reason
        if self.success:
            self.say("Lección completada.")
        else:
            self.say(f"Lección terminada: {reason}" if reason else "Lección terminada.")

    # ----- evaluación
    def extra_items(self, world):
        return []

    def result(self, world):
        items = []
        # el mismo criterio repetido en varios pasos (mismo nombre y tolerancia) se puntúa en una sola fila
        groups = {}
        for m in self.all_monitors:
            if m.tot_t < 0.5:
                continue                      # paso no realizado: no se puntúa
            g = groups.setdefault((m.name, m.target), [0.0, 0.0, 0])
            g[0] += m.ok_t
            g[1] += m.tot_t
            g[2] += m.weight
        for (name, target), (ok_t, tot_t, weight) in groups.items():
            frac = ok_t / tot_t
            items.append((name, round(weight * frac), weight, f"{frac * 100:.0f}% del tiempo dentro de {target}"))
        if self.landing is not None:
            items += self.landing.score()
        items += self.extra_items(world)
        tot = sum(i[2] for i in items) or 1
        got = sum(i[1] for i in items)
        for name, pen, com in self.penalties:
            items.append((name, pen, 0, com))
            got += pen
        score = clamp(100.0 * got / tot, 0, 100)
        if not self.success:
            score = min(score, 40.0)
            if world.ac.crashed:
                score = 0.0
        grade = ("Excelente" if score >= 90 else "Muy bien" if score >= 80 else "Satisfactorio" if score >= 70
                 else "Insatisfactorio")
        # criterio de examen: superar con 70 o más (dentro de estándar la mayor parte del tiempo)
        return dict(score=score, grade=grade, items=items, success=self.success, reason=self.fail_reason,
                    passed=self.success and score >= 70, acs=self.acs, standard=self.standard)

    # ----- presentación
    def hud(self, world):
        st = self.step
        lines = []
        if st is not None:
            lines.append(("paso", f"{self.idx + 1}/{len(self.steps)}  {st.text}"))
            for m in st.monitors:
                if m.value is None:
                    continue
                v = m.fmt.format(m.value) if m.fmt else str(m.value)
                lines.append(("ok" if m.ok else "mal", f"{m.name}: {v} {m.unit}  (ACS {m.target})"))
        return lines

    def ring(self, world, x, y, alt_ft, hdg, radius=45.0, active=True):
        return (np.array([x, y, -alt_ft * FT]), hdg, radius, (0.2, 1.0, 0.4, 0.9) if active else (1.0, 1.0, 1.0, 0.35))


# =================================================================== Área PA.II: preparación y tierra
class L_Arranque(Lesson):
    id = "arranque"
    title = "Arranque del motor y rodaje"
    category = "1 · Procedimientos en tierra"
    acs = "PA.II.C / PA.II.D"
    duration = "6 min"
    start = "plataforma"
    cold = True
    school_only = True
    brief = ("ACS PA.II.C (arranque) y PA.II.D (rodaje). Empezará con el avión frío y oscuro en la plataforma. "
             "Siga la lista de verificación para poner en marcha el motor y después ruede por la calle de rodaje "
             "hasta el punto de espera. Use los interruptores del panel inferior (Ctrl+E es el arranque automático, "
             "que no puntúa). En tierra, los pedales (A/D) dirigen la rueda de morro y la barra espaciadora frena.")
    objectives = ["Lista de arranque completa y en orden", "Presión de aceite en verde en 30 s",
                  "Rodar a velocidad segura (< 15 kt)", "Mantenerse sobre el asfalto", "Detenerse en el punto de espera"]

    def build(self, world):
        s = world.ac.sys
        e = s.engine
        self.order_ok = 0
        self.auto_start_used = False
        self.max_taxi = 0.0
        self.grass_time = 0.0
        items = [
            ("Freno de estacionamiento PUESTO", lambda w: s.parking_brake),
            ("Interruptor maestro (BAT/ALT) ENCENDIDO", lambda w: s.master),
            ("Luz anticolisión (BEACON) ENCENDIDA", lambda w: s.lights["beacon"]),
            ("Mezcla RICA (tecla M o palanca roja)", lambda w: e.mixture > 0.9),
            ("Gases 1/4 abiertos (W/S)", lambda w: 0.08 < e.throttle < 0.4),
            ("Magnetos en AMBOS (clic en la llave)", lambda w: e.magnetos == 3),
            ("ARRANQUE: mantenga pulsado hasta que arranque", lambda w: e.running),
            ("Aviónica ENCENDIDA", lambda w: s.avionics),
            ("Presión de aceite en verde", lambda w: e.oil_press > 25),
        ]
        self.checklist = [[t, False] for t, _ in items]
        self.check_fns = [f for _, f in items]

        def check_done(w, L):
            nxt = next((i for i, c in enumerate(L.checklist) if not c[1]), None)
            for i, fn in enumerate(L.check_fns):
                if not L.checklist[i][1] and fn(w):
                    L.checklist[i][1] = True
                    if i == nxt:
                        L.order_ok += 1
            return all(c[1] for c in L.checklist)
        gate = (-650.0, 45.0)

        def at_hold(w, L):
            return math.hypot(w.ac.pos[0] - gate[0], w.ac.pos[1] - gate[1]) < 25 and w.ac.gs < 0.8
        self.steps = [
            Step("Complete la lista de puesta en marcha (K para verla)", check_done,
                 voice="Bienvenido. Vamos a poner en marcha el motor. Siga la lista de verificación en pantalla."),
            Step("Suelte el freno (B) y ruede hasta el punto de espera siguiendo los aros",
                 at_hold, voice="Motor en marcha. Suelte el freno de estacionamiento y ruede despacio hasta el punto de espera.",
                 monitors=[Monitor("Velocidad de rodaje", lambda w: (w.ac.gs / KT, w.ac.gs / KT < 15, "< 15 kt"), 15, "{:.0f}", "kt")]),
        ]

    def update(self, dt, world, events):
        super().update(dt, world, events)
        ac = world.ac
        if self.idx == 1:
            self.max_taxi = max(self.max_taxi, ac.gs / KT)
            if ac.on_ground and ac.surface_type == "cesped" and ac.gs > 0.5:
                self.grass_time += dt
                self.coach("grass", True, "Se ha salido del asfalto. Vuelva a la calle de rodaje.", 10)
            self.coach("fast", ac.gs / KT > 16, "Demasiado rápido para rodar: reduzca gases y frene suavemente.", 10)
            self.coach("rpm", ac.sys.engine.rpm > 1900 and ac.on_ground and ac.gs < 2, "No necesita tanta potencia para iniciar el rodaje.", 15)
        pts = [(140.0, 100.0), (0.0, 100.0), (-500.0, 100.0), (-650.0, 95.0), (-650.0, 45.0)]
        self.rings = []
        if self.idx >= 1:
            pos = ac.pos
            self.taxi_i = getattr(self, "taxi_i", 0)
            if self.taxi_i < len(pts) and math.hypot(pos[0] - pts[self.taxi_i][0], pos[1] - pts[self.taxi_i][1]) < 30:
                self.taxi_i += 1
            for i, (x, y) in enumerate(pts[self.taxi_i:self.taxi_i + 2]):
                h = (world.terrain.height(x, y) + 6.5) / FT
                nx, ny = pts[min(self.taxi_i + i + 1, len(pts) - 1)]
                hd = math.degrees(math.atan2(ny - y, nx - x)) if (nx, ny) != (x, y) else 270
                self.rings.append(self.ring(world, x, y, h, hd, 6.0, i == 0))

    def extra_items(self, world):
        n = len(self.checklist)
        items = [("Lista en orden", round(30 * self.order_ok / n), 30, f"{self.order_ok}/{n} pasos en el orden correcto"),
                 ("Rodaje sobre asfalto", 15 if self.grass_time < 1 else (7 if self.grass_time < 6 else 0), 15,
                  f"{self.grass_time:.0f} s fuera del asfalto"),
                 ("Velocidad máxima de rodaje", 15 if self.max_taxi < 15 else (8 if self.max_taxi < 20 else 0), 15,
                  f"máx. {self.max_taxi:.0f} kt")]
        items.append(("Arranque manual", 0 if self.auto_start_used else 10, 10,
                      "Se usó el arranque automático" if self.auto_start_used else "Correcto"))
        return items


# =================================================================== Área PA.IV: despegues y aterrizajes
class L_Despegue(Lesson):
    id = "despegue"
    title = "Despegue normal y ascenso"
    category = "2 · Despegues, aterrizajes y circuito"
    acs = "PA.IV.A"
    duration = "3 min"
    brief = ("ACS PA.IV.A — Despegue normal y ascenso. Está alineado en la pista en servicio. Aplique toda la potencia "
             "(Shift+W), mantenga el eje con los pedales (A/D): el efecto de la hélice tira a la izquierda. "
             "Rote a Vr 55 kt (flecha abajo) hasta unos 8-10° y ascienda a Vy 74 kt (tolerancia ACS +10/-5 kt) "
             "manteniendo el rumbo de pista hasta 1000 ft sobre el terreno.")
    objectives = ["Potencia máxima y control direccional", "Rotación a Vr 55 kt", "Vy 74 kt +10/-5 (ACS)",
                  "Rumbo de pista ±10°", "Ascender a 1000 ft AGL"]

    def build(self, world):
        self.rot_speed = None
        self.liftoff_speed = None
        H = self.hdg

        def airborne(w, L):
            if L.rot_speed is None and w.ac.pitch > math.radians(3) and w.ac.on_ground:
                L.rot_speed = w.ind.ias
            if not w.ac.on_ground and w.ac.agl > 2:
                L.liftoff_speed = w.ind.ias if L.liftoff_speed is None else L.liftoff_speed
                return True
            return False
        self.steps = [
            Step("Gases a fondo y mantenga el eje; rote a 55 kt", airborne,
                 voice="Gases a fondo. Mantenga el eje con los pedales y rote a cincuenta y cinco nudos.",
                 monitors=[Monitor("Eje de pista", lambda w: (self.rw_local(w)[1], abs(self.rw_local(w)[1]) < 4, "±4 m"),
                                   15, "{:+.1f}", "m")]),
            Step(f"Ascienda a Vy 74 kt con rumbo {world.mag(H):03.0f} hasta 1000 ft AGL",
                 lambda w, L: w.ac.agl / FT > 1000, voice="Despegado. Mantenga setenta y cuatro nudos y rumbo de pista.",
                 monitors=[mon_speed(74, 5, 10, 25, "Velocidad Vy"), mon_hdg(H, 10, 15), mon_ball(5)]),
        ]

    def update(self, dt, world, events):
        super().update(dt, world, events)
        ac = world.ac
        if self.idx == 0 and ac.on_ground and ac.gs > 8:
            if not self.rw.contains(ac.pos[0], ac.pos[1]):
                self.finish(False, "Se salió de la pista durante la carrera", world)
            self.coach("thr", ac.sys.engine.throttle < 0.9 and ac.gs > 3, "Use toda la potencia para el despegue.", 10)
            lat = self.rw_local(world)[1]
            self.coach("lat", abs(lat) > 4, "Corrija hacia el eje con los pedales.", 6)
            self.coach("early", ac.pitch > math.radians(4) and world.ind.ias < 45, "Todavía no: espere a cincuenta y cinco nudos para rotar.", 8)
        if self.idx == 1:
            self.coach("slow", world.ind.ias < 68, "Velocidad baja, baje un poco la nariz.", 8)
            self.coach("fast", world.ind.ias > 86, "Velocidad alta, suba un poco la nariz para ascender a Vy.", 10)

    def extra_items(self, world):
        r = self.rot_speed or self.liftoff_speed
        if r is None:
            return [("Velocidad de rotación", 0, 15, "No se rotó")]
        p = 15 if 50 <= r <= 62 else (8 if 45 <= r <= 68 else 2)
        return [("Velocidad de rotación", p, 15, f"{r:.0f} kt (Vr 55)")]


class _LandingLesson(Lesson):
    """Base para lecciones que terminan con un aterrizaje (ACS PA.IV.B)."""
    airport_idx = 0
    land_end = None
    guided = True
    vapp = 65

    def landing_runway(self, world):
        if self.airport_idx == 0:
            return world.active_rw, world.active_end
        ap = world.airports[self.airport_idx]
        if self.land_end:
            return ap.runways[0], self.land_end
        return world.select_runway(ap)

    def glide_rings(self, world):
        rw, ident = self._lrw
        ap = world.airports[self.airport_idx]
        thr, hdg, d = rw.end(ident)
        ac = world.ac
        a = -((ac.pos[0] - thr[0]) * d[0] + (ac.pos[1] - thr[1]) * d[1])
        out = []
        for k in range(12, 0, -1):
            dist = k * 0.3 * NM
            if dist < a - 180:
                p = thr - d * dist
                h = ap.elev + (dist + 300) * math.tan(math.radians(3.0))
                out.append(self.ring(world, p[0], p[1], h / FT, hdg, 38.0, len(out) == 0))
            if len(out) >= 3:
                break
        return out

    def update(self, dt, world, events):
        super().update(dt, world, events)
        fs = getattr(self, "_final_objs", ())
        if self.guided and self.landing is not None and self.landing.touch is None and self.step in fs:
            self.rings = self.glide_rings(world)
        elif self.step in fs:
            self.rings = []

    def final_steps(self, world, vapp=65, flaps_full=True):
        ap = world.airports[self.airport_idx]
        rw, ident = self.landing_runway(world)
        self._lrw = (rw, ident)
        self.landing = LandingJudge(rw, ident)
        thr, hdg_rw, d = rw.end(ident)
        gs_pos = thr + d * 300
        self.stab = None

        def gs_dev(w):
            ga = -((w.ac.pos[0] - gs_pos[0]) * d[0] + (w.ac.pos[1] - gs_pos[1]) * d[1])
            h = w.ac.alt_msl - ap.elev
            if ga < 100:
                return 0.0
            return math.degrees(math.atan2(h, ga)) - 3.0

        def lat_of(w):
            return rw.local(w.ac.pos[0], w.ac.pos[1], ident)[1]

        def stab_check(w, L):
            if (w.ac.alt_msl - ap.elev) / FT < 500 and L.stab is None:
                ok_spd = vapp - 5 <= w.ind.ias <= vapp + 10
                ok_vs = w.ind.vs_fpm > -1000
                ok_lat = abs(lat_of(w)) < 60
                ok_flaps = w.ac.sys.flaps >= 18 or not flaps_full
                L.stab = dict(spd=ok_spd, vs=ok_vs, lat=ok_lat, flaps=ok_flaps)
                if all(L.stab.values()):
                    L.say("Aproximación estabilizada.", key="stab")
                else:
                    falt = [k for k, v in L.stab.items() if not v]
                    nombres = dict(spd="velocidad", vs="régimen de descenso", lat="alineación", flaps="flaps")
                    L.say("Aproximación no estabilizada: revise " + ", ".join(nombres[k] for k in falt) +
                          ". Considere motor y al aire.", key="stab")
            return w.ac.on_ground
        mon_gs = Monitor("Senda de planeo (PAPI)", lambda w: (gs_dev(w), abs(gs_dev(w)) < 0.6, "3° ±0.6"), 15, "{:+.1f}", "°")
        mon_v = mon_speed(vapp, 5, 10, 15, "Velocidad de aproximación")
        mon_loc = Monitor("Alineación con el eje", lambda w: (lat_of(w), abs(lat_of(w)) < 25, "±25 m"), 8, "{:+.0f}", "m")
        self._final_objs = [
            Step(f"Final pista {ident}: {vapp} kt, senda 3° (PAPI 2 blancas/2 rojas), flaps completos",
                 stab_check, voice=f"Final de la pista {ident}. Mantenga {vapp} nudos y la senda de tres grados: dos luces blancas y dos rojas en el PAPI.",
                 monitors=[mon_gs, mon_v, mon_loc]),
            Step("Recogida: reduzca gases y suba la nariz suavemente; frene en pista", lambda w, L: L.landing.done,
                 voice="Gases a ralentí, recoja suavemente y deje que el avión se pose. Después frene."),
        ]
        return self._final_objs

    def extra_items(self, world):
        if self.stab is None:
            return []
        ok = all(self.stab.values())
        return [("Aproximación estabilizada a 500 ft", 10 if ok else 0, 10,
                 "Sí" if ok else "No: " + ", ".join(k for k, v in self.stab.items() if not v))]

    def coaching(self, dt, world):
        super().coaching(dt, world)
        ac = world.ac
        if self.landing is not None and self.landing.touch is None and not ac.on_ground and ac.agl / FT < 1500:
            ra = ac.agl / FT
            for h, txt in ((500, "quinientos"), (100, "cien"), (50, "cincuenta"), (30, "treinta"), (20, "veinte"), (10, "diez")):
                if ra < h and h not in self.callouts_done and ac.vs_fpm < 0:
                    self.callouts_done.add(h)
                    self.messages.append((txt, "callout"))
                    break


class L_Final(_LandingLesson):
    id = "final"
    title = "Aproximación y aterrizaje normal"
    category = "2 · Despegues, aterrizajes y circuito"
    acs = "PA.IV.B"
    duration = "3 min"
    start = "final3"
    brief = ("ACS PA.IV.B — Aproximación y aterrizaje normal. Comienza en final larga a 3 millas, con flaps 10. "
             "Extienda flaps completos (F), mantenga 65 kt (+10/-5 ACS) con la actitud y la senda con la potencia: el PAPI a la "
             "izquierda de la pista debe mostrar 2 luces blancas y 2 rojas. Toque dentro de los 400 ft siguientes al punto "
             "especificado (las primeras marcas de zona de toma), sin deriva y alineado con el eje.")
    objectives = ["Aproximación estabilizada a 500 ft", "65 kt +10/-5 (ACS)", "Senda 3° ±0.6°",
                  "Toma dentro de 400 ft del punto (ACS)", "Sin deriva, sobre el eje"]

    def build(self, world):
        self.steps = self.final_steps(world, 65)


class L_Circuito(_LandingLesson):
    id = "circuito"
    title = "Circuito de tránsito completo"
    category = "2 · Despegues, aterrizajes y circuito"
    acs = "PA.III.B + PA.IV.A/B"
    duration = "9 min"
    night = False
    brief = ("ACS PA.III.B — Circuito de tránsito. Despegue, circuito por la izquierda a 1000 ft sobre el terreno "
             "(tolerancia ACS ±100 ft y ±10 kt) y aterrizaje. Siga los aros verdes: salida, viento cruzado, viento en cola "
             "(90 kt; al través del umbral reduzca potencia y ponga flaps 10), base (flaps 20, 75 kt) y final (flaps 30, 65 kt).")
    objectives = ["Altitud de circuito ±100 ft (ACS)", "Velocidades por tramo ±10 kt", "Pasar por los aros en orden",
                  "Aterrizaje dentro de estándar"]

    def weather(self, w):
        super().weather(w)
        if self.night:
            w.hour = 21.5
            w.cloud_cover = 0.15

    def build(self, world):
        e = self.elev_ft
        pa = e + 1000
        L = self.rw.length
        H = self.hdg
        g = [
            (L + 1000, 0, e + 600, H, "Tramo de salida: ascienda a Vy"),
            (L + 1800, -700, e + 850, H - 90, "Viraje a viento cruzado (izquierda)"),
            (L + 800, -1350, pa, H + 180, "Viento en cola: nivele a altitud de circuito, 90 kt"),
            (0, -1350, pa, H + 180, "Al través del umbral: reduzca potencia, flaps 10"),
            (-1700, -1350, pa - 150, H + 180, "Inicie el viraje a base"),
            (-2200, -500, e + 750, H + 90, "Base: flaps 20, 75 kt"),
            (-2400, 0, e + 550, H, "Final: flaps 30, 65 kt"),
        ]
        self.gates = []
        for a, l, al, hd, txt in g:
            p = self.at(a, l)
            self.gates.append((p[0], p[1], al, hd % 360, txt))
        self.gi = 0
        self.gate_alt_err = []

        def gate_fn(i):
            def fn(w, Lz):
                x, y, a, h, _ = Lz.gates[i]
                if math.hypot(w.ac.pos[0] - x, w.ac.pos[1] - y) < 160:
                    Lz.gate_alt_err.append(abs(alt(w) - a))
                    Lz.gi = i + 1
                    return True
                return False
            return fn
        steps = [Step("Despegue: gases a fondo, rote a 55 kt", lambda w, Lz: w.ac.agl / FT > 300,
                      voice=f"Despegue por la pista {self.ident}. Circuito por la izquierda a mil pies sobre el terreno.")]
        mons = {2: [mon_alt(pa, 100, 10, "Altitud de circuito"), mon_speed(90, 10, None, 8, "Velocidad en viento en cola")],
                5: [mon_speed(75, 10, None, 6, "Velocidad en base")]}
        for i, gt in enumerate(self.gates):
            steps.append(Step(gt[4], gate_fn(i), monitors=mons.get(i, ()), timeout=150,
                              hint="Siga el aro verde. Si lo ha pasado de largo, vuelva hacia él."))
        steps += self.final_steps(world, 65)
        self.steps = steps

    def update(self, dt, world, events):
        super().update(dt, world, events)
        if self.gi >= len(self.gates):
            return
        self.rings = []
        for k in range(self.gi, min(self.gi + 2, len(self.gates))):
            x, y, a, h, _ = self.gates[k]
            self.rings.append(self.ring(world, x, y, a, h, 55.0, k == self.gi))

    def extra_items(self, world):
        items = super().extra_items(world)
        good = sum(1 for e in self.gate_alt_err if e < 150)
        items.append(("Aros del circuito", round(20 * good / len(self.gates)), 20, f"{good}/{len(self.gates)} a la altura correcta"))
        return items


class L_Cruzado(_LandingLesson):
    id = "cruzado"
    title = "Aterrizaje con viento cruzado"
    category = "2 · Despegues, aterrizajes y circuito"
    acs = "PA.IV.B (viento cruzado)"
    duration = "3 min"
    start = "final3"
    wind_rel = -70
    brief = ("ACS PA.IV.B con viento cruzado — 12 kt con ráfagas de 18 desde la izquierda. En la aproximación corrija la "
             "deriva poniendo la nariz hacia el viento (cangrejeo). Justo antes de la toma alinee el morro con la pista con el "
             "pedal y baje el ala del lado del viento (resbale) para tocar SIN deriva lateral y alineado (requisito ACS). "
             "Añada la mitad del factor de ráfaga a la velocidad de aproximación.")
    objectives = ["Mantener el eje en final", "Velocidad + mitad del factor de ráfaga", "Alinear el morro antes de la toma",
                  "Sin deriva lateral al tocar (ACS)"]

    def weather(self, w):
        super().weather(w)
        w.wind_dir, w.wind_kt, w.gust_kt, w.turbulence = 290, 12, 6, 0.35

    def build(self, world):
        self.steps = self.final_steps(world, 70)


# =================================================================== Área PA.V / PA.VII: maniobras
class L_Basico(Lesson):
    id = "basico"
    title = "Vuelo recto, ascensos, descensos y virajes"
    category = "3 · Maniobras de vuelo"
    acs = "PA.VIII.A-D / maniobras básicas"
    duration = "8 min"
    start = "crucero"
    brief = ("Maniobras básicas por referencia visual e instrumentos (tolerancias ACS: altitud ±100 ft, rumbo ±10°, "
             "velocidad ±10 kt). Use el compensador (Q nariz arriba / E nariz abajo) para no sostener la palanca. "
             "Hará vuelo recto y nivelado, un viraje a la derecha de 20°, un ascenso a Vy, nivelación, un viraje a la "
             "izquierda y un descenso a 500 ft/min.")
    objectives = ["Altitud ±100 ft", "Rumbo ±10°", "Virajes de 20° con bola centrada", "Ascenso a Vy ±10 kt",
                  "Descenso a 500 ft/min"]

    def build(self, world):
        A = world.cruise_alt_ft()
        A2 = A + 1000
        H0 = rnd10m(world, world.ac.heading)
        H1 = turn(H0, 90)
        H2 = turn(H0, -90)
        self.steps = [
            Step(f"Mantenga {A:.0f} ft y rumbo {world.mag(H0):03.0f} durante 30 s (compense)", lambda w, L: True, min_time=30,
                 voice=f"Mantenga {A:.0f} pies y rumbo {world.mag(H0):03.0f}. Use el compensador para aliviar la presión.",
                 monitors=[mon_alt(A, 100, 12), mon_hdg(H0, 10, 8)]),
            Step(f"Viraje a la derecha a rumbo {world.mag(H1):03.0f} con 20° de alabeo", lambda w, L: abs(hdg_err(w, H1)) < 5,
                 voice=f"Viraje a la derecha a rumbo {world.mag(H1):03.0f} con veinte grados de alabeo. Coordine con los pedales.",
                 monitors=[mon_alt(A, 100, 10, "Altitud en viraje"), mon_bank(20, 7, 10), mon_ball(6)],
                 hint="Incline a la derecha unos 20° y tire ligeramente para no perder altura."),
            Step(f"Mantenga rumbo {world.mag(H1):03.0f} y {A:.0f} ft durante 20 s", lambda w, L: True, min_time=20,
                 voice="Nivele las alas y mantenga el rumbo.", monitors=[mon_alt(A, 100, 8), mon_hdg(H1, 10, 8)]),
            Step(f"Ascienda a {A2:.0f} ft a Vy 74 kt con potencia máxima", lambda w, L: alt(w) > A2 - 50,
                 voice=f"Potencia máxima y ascienda a {A2:.0f} pies manteniendo setenta y cuatro nudos.",
                 monitors=[mon_speed(74, 10, None, 12, "Velocidad de ascenso"), mon_hdg(H1, 10, 6)]),
            Step(f"Nivele a {A2:.0f} ft, potencia de crucero (2400 RPM) y compense", lambda w, L: True, min_time=25,
                 voice="Nivele, reduzca la potencia a unas dos mil cuatrocientas revoluciones y compense.",
                 monitors=[mon_alt(A2, 100, 10), mon_hdg(H1, 10, 5)]),
            Step(f"Viraje a la izquierda a rumbo {world.mag(H2):03.0f} con 20° de alabeo", lambda w, L: abs(hdg_err(w, H2)) < 5,
                 voice=f"Viraje a la izquierda a rumbo {world.mag(H2):03.0f}.",
                 monitors=[mon_alt(A2, 100, 8, "Altitud en viraje"), mon_bank(20, 7, 8), mon_ball(6)]),
            Step(f"Descienda a {A:.0f} ft a 500 ft/min y nivele", lambda w, L: abs(alt(w) - A) < 60 and abs(w.ind.vs_fpm) < 200,
                 voice=f"Reduzca potencia y descienda a quinientos pies por minuto hasta {A:.0f} pies.",
                 monitors=[Monitor("Régimen de descenso", lambda w: (w.ind.vs_fpm, -700 <= w.ind.vs_fpm <= -300 or abs(alt(w) - A) < 150, "-500 ±200 ft/min"), 12, "{:+.0f}", "ft/min"),
                           mon_hdg(H2, 10, 6)]),
        ]


class L_Escarpados(Lesson):
    id = "escarpados"
    title = "Virajes escarpados (45°)"
    category = "3 · Maniobras de vuelo"
    acs = "PA.V.A"
    duration = "5 min"
    start = "crucero"
    allow_bank = True
    brief = ("ACS PA.V.A — Virajes escarpados. Un viraje completo de 360° con 45° de alabeo. Tolerancias ACS: alabeo "
             "45° ±5°, altitud ±100 ft, velocidad ±10 kt y salida en el rumbo de entrada ±10°. Al inclinar necesitará "
             "tirar más y añadir potencia. Velocidad de entrada por debajo de Va (105 kt): use 95 kt.")
    objectives = ["Alabeo 45° ±5°", "Altitud ±100 ft", "Velocidad 95 ±10 kt", "Salida en rumbo ±10°"]

    def build(self, world):
        A = world.cruise_alt_ft()
        H0 = rnd10m(world, world.ac.heading)
        self.H0 = H0
        self.turned = 0.0
        self.prev_h = None
        self.rollout_err = None

        def full_turn(w, L):
            h = w.ac.heading
            if L.prev_h is not None:
                L.turned += wrap180(h - L.prev_h)
            L.prev_h = h
            if abs(L.turned) > 340 and abs(hdg_err(w, H0)) < 12 and abs(math.degrees(w.ac.roll)) < 10:
                L.rollout_err = abs(hdg_err(w, H0))
                return True
            return False
        self.A = A
        self.steps = [
            Step(f"Estabilice: {A:.0f} ft, rumbo {world.mag(H0):03.0f}, 95 kt", lambda w, L: True, min_time=12,
                 voice=f"Estabilice a {A:.0f} pies, rumbo {world.mag(H0):03.0f} y noventa y cinco nudos.",
                 monitors=[mon_alt(A, 100, 5), mon_speed(95, 10, None, 5)]),
            Step("Viraje de 360° a la izquierda con 45° de alabeo", full_turn,
                 voice="Inicie un viraje completo a la izquierda con cuarenta y cinco grados de alabeo. Tire y añada potencia para mantener la altura.",
                 monitors=[mon_bank(45, 5, 20), mon_alt(A, 100, 20), mon_speed(95, 10, None, 10), mon_ball(5)]),
        ]

    def update(self, dt, world, events):
        super().update(dt, world, events)
        if self.idx == 1:
            self.coach("alt_lo", alt(world) < self.A - 100, "Está perdiendo altura: tire un poco más.", 8)
            self.coach("alt_hi", alt(world) > self.A + 100, "Está ganando altura: afloje un poco o aumente el alabeo.", 8)

    def extra_items(self, world):
        e = self.rollout_err
        if e is None:
            return [("Salida del viraje", 0, 15, "No completado")]
        return [("Salida del viraje (±10° ACS)", 15 if e <= 10 else 4, 15, f"{e:.0f}° del rumbo de entrada")]


class L_Perdida(Lesson):
    id = "perdida"
    title = "Pérdida sin motor y recuperación"
    category = "3 · Maniobras de vuelo"
    acs = "PA.VII.B"
    duration = "4 min"
    start = "crucero"
    allow_stall = True
    brief = ("ACS PA.VII.B — Pérdida sin motor (configuración de aproximación). Reduzca a ralentí y mantenga la altitud "
             "subiendo la nariz poco a poco, con rumbo ±10° (ACS). Reconozca los avisos (bocina, sacudidas, mandos "
             "blandos). En la pérdida: REDUZCA EL ÁNGULO DE ATAQUE (nariz abajo), POTENCIA MÁXIMA, nivele las alas con "
             "coordinación y ascienda a Vy. Evite la pérdida secundaria y exceder los límites.")
    objectives = ["Rumbo ±10° durante la entrada (ACS)", "Recuperación inmediata y coordinada",
                  "Mínima pérdida de altura", "Sin pérdida secundaria", "Ascenso a Vy"]

    def build(self, world):
        self.stall_alt = None
        self.min_alt = None
        self.secondary = 0
        self.max_bank = 0.0
        self.stalled = False
        H0 = rnd10m(world, world.ac.heading)

        def stalled(w, L):
            if w.ac.stall_frac > 0.5 or (w.ac.sys.stall_warning and w.ac.pitch < math.radians(2) and w.ac.alpha > math.radians(13)):
                L.stall_alt = alt(w)
                L.min_alt = alt(w)
                L.stalled = True
                return True
            return False

        def recovered(w, L):
            L.min_alt = min(L.min_alt, alt(w))
            return w.ind.vs_fpm > 200 and w.ind.ias > 60 and not w.ac.sys.stall_warning
        self.steps = [
            Step("Gases a ralentí y mantenga la altitud subiendo la nariz", stalled,
                 voice="Reduzca los gases a ralentí y mantenga la altitud subiendo la nariz progresivamente hasta la pérdida.",
                 monitors=[mon_hdg(H0, 10, 10, "Rumbo en la entrada"),
                           Monitor("Alas niveladas", lambda w: (abs(math.degrees(w.ac.roll)), abs(math.degrees(w.ac.roll)) < 10, "< 10°"), 5, "{:.0f}", "°")],
                 timeout=70, hint="Tire más de la palanca y reduzca los gases a cero."),
            Step("¡RECUPERE! Nariz abajo, potencia máxima, alas niveladas", recovered,
                 voice="¡Pérdida! Baje la nariz, potencia máxima y nivele las alas."),
            Step("Ascienda a Vy 74 kt y estabilice", lambda w, L: True, min_time=12,
                 voice="Bien. Ascienda a setenta y cuatro nudos.", monitors=[mon_speed(74, 5, 10, 10)]),
        ]

    def update(self, dt, world, events):
        super().update(dt, world, events)
        ac = world.ac
        if self.idx >= 1 and self.stalled:
            self.max_bank = max(self.max_bank, abs(math.degrees(ac.roll)))
            if self.idx >= 2 and ac.stall_frac > 0.5:
                self.secondary += 1
                self.say("Segunda pérdida: no tire tan fuerte en la recuperación.", key="sec", gap=10)
        if self.idx == 1:
            self.coach("pwr", ac.sys.engine.throttle < 0.8 and self.steps[1].t > 2, "¡Potencia máxima!", 5)

    def extra_items(self, world):
        if self.stall_alt is None:
            return [("Pérdida", 0, 40, "No se llegó a la pérdida")]
        loss = max(0.0, self.stall_alt - (self.min_alt or self.stall_alt))
        p = 25 if loss < 200 else (18 if loss < 300 else (10 if loss < 450 else 3))
        return [("Altura perdida en la recuperación", p, 25, f"{loss:.0f} ft"),
                ("Control de alabeo (máx. 20° ACS)", 10 if self.max_bank <= 20 else (4 if self.max_bank < 35 else 0), 10,
                 f"alabeo máximo {self.max_bank:.0f}°"),
                ("Sin pérdida secundaria", 10 if self.secondary == 0 else 0, 10,
                 "correcto" if self.secondary == 0 else "hubo pérdida secundaria")]


# =================================================================== Área PA.IX: emergencias
class L_Motor(_LandingLesson):
    id = "motor"
    title = "Falla de motor y aterrizaje de emergencia"
    category = "4 · Emergencias"
    acs = "PA.IX.B"
    duration = "5 min"
    start = "viento_cola"
    guided = False
    brief = ("ACS PA.IX.B — Aproximación y aterrizaje de emergencia (simulada). En viento en cola el motor se parará. "
             "Primero VUELE EL AVIÓN: velocidad de mejor planeo 68 kt (tolerancia ACS ±10 kt) y compénsela. Elija un lugar "
             "(la pista está a su izquierda), haga la lista de causas (mezcla RICA, combustible AMBOS, magnetos AMBOS) y "
             "planifique el planeo para llegar con altura suficiente.")
    objectives = ["Mejor planeo 68 ±10 kt (ACS)", "Reacción inmediata", "Lista de emergencia (mezcla, combustible, magnetos)",
                  "Aterrizaje seguro en lugar adecuado"]

    def build(self, world):
        self.fail_t = 6.0
        self.reaction = None
        self.checked = set()

        def failed(w, L):
            if L.t > L.fail_t:
                w.ac.sys.failures["engine"] = True
                return True
            return False

        def landed(w, L):
            return w.ac.on_ground and w.ac.gs < 2
        self.landing = LandingJudge(world.active_rw, world.active_end)
        self.steps = [
            Step("Vuelo en viento en cola, 1000 ft AGL", failed, voice="Mantenga el viento en cola a mil pies sobre el terreno."),
            Step("¡FALLA DE MOTOR! Planeo a 68 kt y elija dónde aterrizar", lambda w, L: w.ac.agl / FT < 300 or landed(w, L),
                 voice="¡Falla de motor! Vuele el avión: sesenta y ocho nudos de planeo. Elija dónde aterrizar.",
                 monitors=[mon_speed(68, 10, None, 25, "Velocidad de mejor planeo")]),
            Step("Aterrice y detenga el avión", landed, voice="Prepare el aterrizaje. Flaps cuando tenga el campo asegurado."),
        ]

    def update(self, dt, world, events):
        super().update(dt, world, events)
        ac = world.ac
        if self.idx >= 1:
            e = ac.sys.engine
            if self.reaction is None and abs(world.ind.ias - 68) < 8:
                self.reaction = self.steps[1].t if self.idx == 1 else 99
            if e.mixture > 0.95:
                self.checked.add("mezcla")
            if ac.sys.fuel_selector == 3:
                self.checked.add("combustible")
            if e.magnetos == 3:
                self.checked.add("magnetos")

    def extra_items(self, world):
        rt = self.reaction
        items = [("Reacción (planeo establecido)", 15 if rt is not None and rt < 6 else (8 if rt is not None and rt < 12 else 0), 15,
                  f"{rt:.0f} s" if rt is not None else "no se estableció el planeo")]
        on_rw = self.landing.touch is not None and self.landing.touch["on_runway"]
        items.append(("Lugar de aterrizaje", 15 if on_rw else 8, 15, "En la pista" if on_rw else "Fuera de aeródromo (aceptable)"))
        return items


# =================================================================== Áreas PA.X / IR: noche e instrumentos
class L_Nocturno(L_Circuito):
    id = "nocturno"
    title = "Circuito nocturno"
    category = "5 · Vuelo nocturno y panel parcial"
    acs = "PA.X.A"
    night = True
    brief = ("ACS PA.X.A — Operaciones nocturnas. Mismo circuito, de noche. Encienda luces de navegación y aterrizaje (L). "
             "Las luces de borde de pista, las de aproximación con destellos secuenciales y el PAPI le guiarán. Confíe en los "
             "instrumentos: de noche es fácil sufrir ilusiones visuales (agujero negro en la aproximación).")


class L_Parcial(Lesson):
    id = "parcial"
    title = "Falla de vacío: panel parcial"
    category = "5 · Vuelo nocturno y panel parcial"
    acs = "IR.VII.C / IR.III"
    standard = IR
    duration = "4 min"
    start = "crucero"
    brief = ("ACS IR — Pérdida de instrumentos primarios. Volará dentro de nubes; la bomba de vacío fallará y el horizonte "
             "y el direccional darán indicaciones falsas. Identifíquelo (anunciador VACÍO) e ignórelos: mantenga altitud ±100 ft "
             "y rumbo ±10° (ACS) con el coordinador, altímetro, variómetro, anemómetro y la brújula magnética. "
             "Use la cabina CLÁSICA (Tab) para esta lección.")
    objectives = ["Detectar la falla", "Altitud ±100 ft (ACS IR)", "Rumbo por brújula ±10°", "Velocidad ±10 kt"]

    def weather(self, w):
        super().weather(w)
        w.cloud_cover, w.cloud_base_ft, w.cloud_top_ft = 0.98, 2500, 9000
        w.visibility_m = 4000
        w.turbulence = 0.2

    def build(self, world):
        A = world.cruise_alt_ft()
        H0 = rnd10m(world, world.ac.heading)

        def fail(w, L):
            if L.t > 15:
                w.ac.sys.failures["vacuum"] = True
                return True
            return False
        self.steps = [
            Step(f"Mantenga {A:.0f} ft y rumbo {world.mag(H0):03.0f} en nubes", fail, voice=f"Está en nubes. Mantenga {A:.0f} pies y rumbo {world.mag(H0):03.0f}."),
            Step("Falla de vacío: vuele con panel parcial durante 2 minutos", lambda w, L: True, min_time=120,
                 voice="Falla de vacío. No se fíe del horizonte ni del direccional. Use el coordinador, el altímetro y la brújula.",
                 monitors=[mon_alt(A, 100, 25), Monitor("Rumbo (brújula)", lambda w: (w.ind.compass, abs(hdg_err(w, H0)) < 10, f"{world.mag(H0):03.0f} ±10°"), 20, "{:03.0f}", "°"),
                           mon_speed(105, 10, None, 10)]),
        ]


class L_ILS(_LandingLesson):
    id = "ils"
    title = "Aproximación ILS de precisión"
    category = "6 · Vuelo instrumental (IFR)"
    acs = "IR.VI.B"
    standard = IR
    guided = False
    duration = "8 min"
    start = "final10"
    brief = ("ACS IR.VI.B — Aproximación de precisión. Techo a 800 ft y visibilidad 3 km. NAV1 está sintonizado en el ILS "
             "de la pista en servicio. Intercepte el localizador (aguja vertical) y, cuando la aguja de senda (horizontal) "
             "llegue al centro, inicie el descenso. Tolerancias ACS: velocidad ±10 kt y no más de 3/4 de escala de desviación "
             "en localizador y senda. Altura de decisión: 200 ft sobre la pista; si no ve la pista, motor y al aire. "
             "Puede usar el piloto automático en modo APR (en un ILS sintético si el aeropuerto real no publica frecuencia).")
    objectives = ["Localizador dentro de 3/4 de escala", "Senda dentro de 3/4 de escala", "Velocidad ±10 kt",
                  "Decisión a 200 ft sobre la pista", "Aterrizaje"]

    def weather(self, w):
        super().weather(w)
        w.wind_dir, w.wind_kt, w.turbulence = 330, 8, 0.25
        w.cloud_cover, w.cloud_base_ft, w.cloud_top_ft = 0.97, 1300, 3600
        w.visibility_m = 3000
        w.hour = 9.0

    def build(self, world):
        ils = world.ils_for(world.active_rw, world.active_end)
        nav = world.nav1
        if ils:
            nav.freq, nav.obs = ils.freq, round(ils.course) % 360 or 360
        da = self.elev_ft + 200
        loc = Monitor("Localizador", lambda w: (w.nav1.cdi * 5, w.nav1.valid and abs(w.nav1.cdi) < 0.75, "≤ 3/4 escala"), 15, "{:+.1f}", "pt")
        gs = Monitor("Senda", lambda w: (w.nav1.gs * 5, w.nav1.gs_valid and abs(w.nav1.gs) < 0.75, "≤ 3/4 escala"), 15, "{:+.1f}", "pt")

        def established(w, L):
            return w.nav1.valid and abs(w.nav1.cdi) < 0.3 and w.nav1.gs_valid and w.nav1.gs < 0.2
        self.steps = [
            Step(f"Intercepte el localizador (ILS {nav.freq:.2f}) con rumbo de intercepción", established,
                 voice="Intercepte el localizador. Mantenga la altitud hasta capturar la senda.",
                 monitors=[mon_speed(90, 10, None, 5, "Velocidad")], timeout=200,
                 hint="Gire hacia la aguja: si la aguja está a la derecha, vire a la derecha."),
            Step("Siga localizador y senda hasta 1000 ft sobre la pista", lambda w, L: alt(w) < self.elev_ft + 1000,
                 voice="Establecido. Descienda por la senda manteniendo ambas agujas centradas.",
                 monitors=[loc, gs, mon_speed(90, 10, None, 6, "Velocidad")]),
            Step(f"70 kt y flaps completos; altura de decisión {da:.0f} ft", lambda w, L: alt(w) < da + 20,
                 voice=f"Reduzca a setenta nudos y extienda flaps. Altura de decisión {da:.0f} pies.",
                 monitors=[loc, gs]),
        ] + self.final_steps(world, 68)[1:]
        self.minimums_called = False
        self.da = da

    def coaching(self, dt, world):
        super().coaching(dt, world)
        if not self.minimums_called and alt(world) < self.da + 60 and self.idx >= 2:
            self.minimums_called = True
            self.messages.append(("mínimos", "callout"))


class L_VOR(_LandingLesson):
    id = "vor"
    title = "Navegación VOR a otro aeródromo"
    category = "6 · Vuelo instrumental (IFR)"
    acs = "PA.VI.B / IR.V.A"
    standard = IR
    duration = "12 min"
    airport_idx = 1
    land_end = "27"
    school_only = True
    brief = ("ACS PA.VI.B / IR.V.A — Radionavegación. Despegue y ascienda a 3500 ft. NAV1 está sintonizado en el VOR VNT "
             "(115.20). Gire el OBS (rueda sobre el CDI) hasta centrar la aguja con indicación TO y siga ese curso hasta el VOR "
             "(ACS: altitud ±100 ft, desviación ≤ 3/4 de escala). Después sintonice el ILS 27 de Valle Norte (109.90, botón ⇄) "
             "y aterrice en la pista 27.")
    objectives = ["Interceptar y seguir el radial", "Altitud ±100 ft", "Desviación ≤ 3/4 de escala", "Aterrizar en destino"]

    def build(self, world):
        world.nav1.freq = 115.20
        world.nav1.standby = 109.90
        vor = next(n for n in world.navaids if n.ident == "VNT")

        def at_vor(w, L):
            return math.hypot(w.ac.pos[0] - vor.pos[0], w.ac.pos[1] - vor.pos[1]) < 1300

        def near_field(w, L):
            thr, _, d = w.airports[1].runways[0].end("27")
            return math.hypot(w.ac.pos[0] - thr[0], w.ac.pos[1] - thr[1]) < 7000
        trk = Monitor("Curso VOR", lambda w: (w.nav1.cdi * 5, w.nav1.valid and abs(w.nav1.cdi) < 0.75, "≤ 3/4 escala"), 15, "{:+.1f}", "pt")
        self.steps = [
            Step("Despegue y ascenso inicial", lambda w, L: w.ac.agl / FT > 500, voice="Despegue y ascienda a tres mil quinientos pies."),
            Step("Centre la aguja con el OBS (TO) y vire hacia el VOR VNT",
                 lambda w, L: w.nav1.to_from == "TO" and abs(w.nav1.cdi) < 0.3 and abs(wrap180(w.ac.heading - w.true(w.nav1.obs))) < 25,
                 voice="Gire el selector de curso hasta centrar la aguja con indicación TO y vire a ese rumbo.", timeout=120,
                 hint="Use la rueda del ratón sobre el indicador NAV 1 para girar el OBS."),
            Step("Siga el curso hasta el VOR a 3500 ft", at_vor, voice="Mantenga la aguja centrada hasta sobrevolar el VOR.",
                 monitors=[trk, mon_alt(3500, 100, 12, "Altitud de crucero")]),
            Step("Sintonice ILS 27 (109.90) y diríjase a la final de la pista 27", near_field,
                 voice="Sobre el VOR. Sintonice el ILS dos siete e inicie el descenso para la pista dos siete.",
                 timeout=180, hint="La pista 27 está al suroeste del VOR; aproxímese desde el este con rumbo 270."),
        ] + self.final_steps(world, 65)


class L_BimotorFalla(Lesson):
    id = "bimotor_falla"
    title = "Falla de motor en bimotor: identificar, verificar, embanderar"
    category = "7 · Multimotor (DA42)"
    acs = "CA.X.A"
    standard = MEL
    aircraft = "da42"
    start = "crucero"
    duration = "5 min"
    brief = ("ACS CA.X.A — Maniobras con un motor inoperativo en el Diamond DA42. En crucero fallará un motor. "
             "Procedimiento: 1) CONTROL: mantenga el rumbo con el pedal del lado del motor bueno ('pie muerto, motor muerto'); "
             "2) POTENCIA: ambas palancas a fondo; 3) IDENTIFICAR el motor muerto por el pie que no pisa; 4) VERIFICAR "
             "reduciendo esa palanca (no debe cambiar nada); 5) EMBANDERAR apagando su interruptor MOTOR. Después vuele a "
             "Vyse 82 kt (línea azul) con 2-5° de alabeo hacia el motor bueno. Tolerancias ACS: rumbo ±10°, altitud ±100 ft, "
             "velocidad ±10 kt.")
    objectives = ["Mantener el control direccional", "Identificar y verificar el motor correcto",
                  "Embanderar en menos de 30 s", "Vyse 82 kt +10/-5", "Rumbo ±10°, alabeo 2-5° hacia el motor bueno"]

    def build(self, world):
        A = world.cruise_alt_ft()
        H0 = rnd10m(world, world.ac.heading)
        self.H0 = H0
        self.fail_t = None
        self.wrong = False
        self.feather_time = None
        sysm = world.ac.sys

        def fail(w, L):
            if L.t > 12:
                sysm.failures["engine"] = True
                L.fail_t = L.t
                return True
            return False

        def feathered(w, L):
            if sysm.engines[1].magnetos == 0:
                L.wrong = True
                return True
            if sysm.engines[0].magnetos == 0:
                L.feather_time = L.t - (L.fail_t or L.t)
                return True
            return False
        self.steps = [
            Step(f"Crucero a {A:.0f} ft, rumbo {world.mag(H0):03.0f}", fail, voice=f"Mantenga {A:.0f} pies y rumbo {world.mag(H0):03.0f}."),
            Step("¡FALLA DE MOTOR! Control, potencia, identificar, verificar y embanderar", feathered,
                 voice="¡Falla de motor! Mantenga el control con el pedal, potencia máxima, identifique, verifique y embandere el motor muerto.",
                 monitors=[mon_hdg(H0, 20, 15, "Rumbo durante la identificación")], timeout=40,
                 hint="El pie que no pisa indica el motor muerto. Apague su interruptor MOTOR."),
            Step("Vuele a Vyse 82 kt con 2-5° de alabeo hacia el motor bueno durante 60 s", lambda w, L: True, min_time=60,
                 voice="Motor embanderado. Mantenga ochenta y dos nudos, línea azul, con unos cinco grados de alabeo hacia el motor bueno.",
                 monitors=[mon_speed(82, 5, 10, 20, "Vyse (línea azul)"), mon_hdg(H0, 10, 15),
                           Monitor("Alabeo hacia el motor bueno", lambda w: (math.degrees(w.ac.roll), 1.0 <= math.degrees(w.ac.roll) <= 6.0, "+2 a +5°"), 10, "{:+.0f}", "°")]),
        ]

    def update(self, dt, world, events):
        super().update(dt, world, events)
        if self.wrong and not self.done:
            self.finish(False, "Apagó el motor equivocado: los dos motores parados", world)

    def extra_items(self, world):
        ft = self.feather_time
        if self.wrong:
            return [("Motor identificado", 0, 25, "Se apagó el motor bueno")]
        if ft is None:
            return [("Embanderado", 0, 25, "No se embanderó")]
        return [("Motor identificado correctamente", 15, 15, "Motor izquierdo"),
                ("Tiempo hasta embanderar", 10 if ft < 20 else (6 if ft < 30 else 2), 10, f"{ft:.0f} s")]


class L_Vmc(Lesson):
    id = "vmc"
    title = "Demostración de Vmc"
    category = "7 · Multimotor (DA42)"
    acs = "CA.X.B"
    standard = MEL
    aircraft = "da42"
    start = "crucero"
    duration = "5 min"
    allow_stall = True
    brief = ("ACS CA.X.B — Demostración de la velocidad mínima de control (Vmc 68 kt, línea roja). Tren y flaps arriba, "
             "motor IZQUIERDO a ralentí (simula la falla) y DERECHO a fondo. Suba la nariz para perder 1 kt por segundo "
             "manteniendo el rumbo con el pedal derecho y 5° de alabeo hacia el motor bueno. A la PRIMERA señal de pérdida de "
             "control direccional o aviso de pérdida: REDUZCA la potencia del motor bueno y baje la nariz, y recupere a Vyse. "
             "Tolerancia ACS: rumbo ±10° hasta la recuperación; recuperación inmediata.")
    objectives = ["Configuración correcta", "Desaceleración de ~1 kt/s", "Rumbo ±10° con pedal",
                  "Recuperación a la primera señal", "Volver a Vyse sin perder control"]

    def build(self, world):
        H0 = rnd10m(world, world.ac.heading)
        self.H0 = H0
        sysm = world.ac.sys
        self.signal_t = None
        self.reaction = None
        self.min_ias = 999.0
        self.alt0 = None

        def config(w, L):
            return sysm.engines[0].throttle < 0.12 and sysm.engines[1].throttle > 0.9

        def signal(w, L):
            L.min_ias = min(L.min_ias, w.ind.ias)
            if L.alt0 is None:
                L.alt0 = alt(w)
            lost = abs(hdg_err(w, H0)) > 15 or w.ac.sys.stall_warning
            if lost:
                L.signal_t = L.t
                return True
            return False

        def recovered(w, L):
            if L.reaction is None and sysm.engines[1].throttle < 0.6:
                L.reaction = L.t - L.signal_t
            return L.reaction is not None and w.ind.ias > 78 and abs(w.ac.omega[2]) < 0.05
        self.steps = [
            Step("Motor IZQUIERDO a ralentí y DERECHO a fondo (tren y flaps arriba)", config,
                 voice="Reduzca el motor izquierdo a ralentí y ponga el derecho a fondo.", timeout=40,
                 hint="Use las palancas POT IZQ y POT DER del panel."),
            Step("Suba la nariz: pierda 1 kt por segundo con rumbo fijo (pedal derecho) y 5° de alabeo a la derecha", signal,
                 voice="Suba la nariz poco a poco. Mantenga el rumbo con el pedal derecho y cinco grados de alabeo a la derecha.",
                 monitors=[mon_hdg(H0, 10, 20, "Rumbo con pedal"),
                           Monitor("Alabeo hacia el motor bueno", lambda w: (math.degrees(w.ac.roll), 2.0 <= math.degrees(w.ac.roll) <= 7.0, "+3 a +5°"), 10, "{:+.0f}", "°")],
                 timeout=120),
            Step("¡RECUPERE! Reduzca el motor bueno, baje la nariz y acelere a Vyse", recovered,
                 voice="¡Recupere! Reduzca la potencia del motor derecho y baje la nariz."),
        ]

    def extra_items(self, world):
        rt = self.reaction
        items = [("Velocidad mínima alcanzada", 10, 10, f"{self.min_ias:.0f} kt (Vmc publicada 68)")]
        if rt is None:
            items.append(("Reacción a la pérdida de control", 0, 25, "No se recuperó"))
        else:
            items.append(("Reacción a la pérdida de control", 25 if rt < 2 else (15 if rt < 4 else 5), 25, f"{rt:.1f} s"))
        return items


from .lessons_emerg import EMERGENCY_LESSONS  # noqa: E402  (usa las clases de arriba)
from .lessons_maneuvers import MANEUVER_LESSONS, MANEUVER_LESSONS_TO  # noqa: E402
from .lessons_xc import XC_LESSONS  # noqa: E402
from .lessons_svbs import SVBS_MISSIONS  # noqa: E402
from .lessons_venezuela import VENEZUELA_MISSIONS  # noqa: E402
from .lessons_clima import CLIMA_MISSIONS  # noqa: E402
from .lessons_ifr import IFR_LESSONS  # noqa: E402
from .checkride import CHECKRIDES  # noqa: E402

LESSONS = [L_Arranque, L_Despegue, L_Final, L_Circuito, L_Cruzado, *MANEUVER_LESSONS_TO,
           L_Basico, L_Escarpados, L_Perdida, *MANEUVER_LESSONS, L_Motor,
           *EMERGENCY_LESSONS, L_Nocturno, L_Parcial, L_ILS, *IFR_LESSONS, L_VOR, L_BimotorFalla, L_Vmc, *XC_LESSONS,
           *CHECKRIDES, *SVBS_MISSIONS, *VENEZUELA_MISSIONS, *CLIMA_MISSIONS]
LESSONS_BY_ID = {c.id: c for c in LESSONS}


class FreeFlight(Lesson):
    """Vuelo libre: sin pasos, solo comentarios de aterrizaje."""
    id = "libre"
    title = "Vuelo libre"
    category = "Libre"

    def __init__(self, start="pista"):
        super().__init__()
        self.start = start

    def setup(self, world):
        world.reposition(self.start, cold=self.start == "plataforma")
        self.steps = []
        at = world.atmo
        at.rain_here = world.weather.rain
        at.wet = min(1.0, world.weather.rain * 1.4) if world.weather.rain > 0.3 else 0.0

    def update(self, dt, world, events):
        self.t += dt
        for ev, data in events:
            if ev == "contacto" and data.get("gear") in ("izq", "der"):
                sink = max(0.0, data["sink"]) / FT * 60
                if sink > 60:
                    q = "suave" if sink < 200 else ("buena" if sink < 400 else ("firme" if sink < 650 else "dura"))
                    self.say(f"Toma {q}: {sink:.0f} pies por minuto.", key="land", gap=5)
            self.on_event(ev, data, world)
        self.coaching(dt, world)

    def hud(self, world):
        return []
