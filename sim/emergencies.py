"""Emergencias simuladas y fallas programadas por el instructor.

Cada falla produce sus síntomas (humo, llamas, ruido, indicaciones) y se resuelve con el
procedimiento real del manual (POH/AFM):

  fire        Fuego de motor en vuelo: mezcla CORTE (o MOTOR OFF en FADEC) y combustible CERRADO.
  smoke       Humo / fuego eléctrico: interruptor maestro OFF (y extintor); el humo se despeja.
  radio       Falla de comunicaciones: transpondedor 7600 y señales luminosas de la torre.
  gear        El tren no baja: extensión de emergencia.
  trim        Compensador eléctrico desbocado: desconectar (botón del PA / cortacircuito).
  door        Puerta abierta en vuelo: más resistencia y ruido; cerrar por debajo de 80 kt.
  magneto     Magneto derecho en falla: motor irregular en AMBOS; seleccionar IZQ.
  fuel_leak   Fuga de combustible: el nivel baja deprisa; aterrizar cuanto antes.
  carb_ice    Hielo en el carburador (C152, PA-28 Warrior): bajan las rpm y el motor va irregular;
              calefacción al carburador (empeora unos segundos al fundirse y luego se recupera).
"""
import math
import random

from .mathx import FT, KT, NM, clamp

CATALOG = [
    # clave, nombre, aplicable(t)
    ("engine", "Parada de motor", lambda t: True),
    ("engine2", "Parada del motor derecho", lambda t: len(t.engines_y) > 1),
    ("fire", "Fuego de motor", lambda t: True),
    ("smoke", "Humo en cabina (fuego eléctrico)", lambda t: True),
    ("electrical", "Falla eléctrica total", lambda t: True),
    ("alternator", "Falla del alternador", lambda t: True),
    ("radio", "Falla de radio (comunicaciones)", lambda t: True),
    ("vacuum", "Bomba de vacío", lambda t: True),
    ("pitot", "Pitot obstruido", lambda t: True),
    ("static", "Toma estática obstruida", lambda t: True),
    ("magneto", "Magneto en falla (motor irregular)", lambda t: not t.fadec),
    ("carb_ice", "Hielo en el carburador", lambda t: getattr(t, "carburetor", False)),
    ("fuel_leak", "Fuga de combustible", lambda t: True),
    ("gear", "El tren no baja", lambda t: t.retractable),
    ("trim", "Compensador desbocado", lambda t: True),
    ("flaps", "Flaps bloqueados", lambda t: True),
    ("door", "Puerta abierta en vuelo", lambda t: True),
    ("pfd", "Falla del PFD", lambda t: t.default_cockpit == "glass"),
]
NAMES = {k: n for k, n, _ in CATALOG}

TRIGGERS = [
    ("ahora", "Ahora"),
    ("despegue", "Tras el despegue (300 ft)"),
    ("crucero", "En crucero"),
    ("final", "En la final"),
    ("tiempo", "Dentro de 2 min"),
    ("azar", "Al azar (1–8 min)"),
]


class Emergencies:
    def __init__(self, world):
        self.world = world
        self.plan = []           # fallas programadas
        self.log = []            # [dict(key, t, resolved_t, nota)]
        self.rng = random.Random()
        self.reset()

    def reset(self):
        s = self.world.ac.sys
        self.plan = []
        self.log = []
        s.fire_level = 0.0
        s.smoke_level = 0.0
        s.trim_cb = True
        s.gear_emergency = False
        s.extinguisher = 1.0
        self.trim_dir = 1.0
        self.light = None        # señal luminosa de la torre (color, intermitente)
        self.caps = False        # paracaídas balístico desplegado (Cirrus)
        self.caps_t = 0.0
        self.was_airborne = False

    # ------------------------------------------------------------ programación
    def schedule(self, key, trigger):
        w = self.world
        e = dict(key=key, trigger=trigger, t0=w.sim_time, fired=False)
        if trigger == "tiempo":
            e["at"] = w.sim_time + 120.0
        elif trigger == "azar":
            e["at"] = w.sim_time + self.rng.uniform(60.0, 480.0)
        self.plan.append(e)
        if trigger == "ahora":
            self.trigger(key)
            e["fired"] = True

    def trigger(self, key):
        w = self.world
        s = w.ac.sys
        if key not in s.failures:
            return
        s.failures[key] = True
        if key == "trim":
            self.trim_dir = self.rng.choice((-1.0, 1.0))
            s.trim_cb = True
        if key == "fire":
            s.fire_level = max(s.fire_level, 0.05)
        if key == "smoke":
            s.smoke_level = max(s.smoke_level, 0.05)
        if key == "magneto":
            s.engines[0].bad_mag = 1
        self.log.append(dict(key=key, t=w.sim_time, resolved=None, note=""))

    def resolve(self, key, note=""):
        for e in reversed(self.log):
            if e["key"] == key and e["resolved"] is None:
                e["resolved"] = self.world.sim_time
                e["note"] = note
                return

    def resolve_once(self, key, note):
        if any(e["key"] == key and e["resolved"] is None for e in self.log):
            self.resolve(key, note)

    def active(self):
        s = self.world.ac.sys
        return [k for k, v in s.failures.items() if v]

    # ------------------------------------------------------------ simulación
    def update(self, dt):
        w = self.world
        ac = w.ac
        s = ac.sys
        if ac.crashed:
            return
        agl = ac.agl / FT
        airborne = not ac.on_ground and agl > 50
        if airborne:
            self.was_airborne = True
        # disparadores programados
        for e in self.plan:
            if e["fired"]:
                continue
            tr = e["trigger"]
            go = False
            if tr == "despegue":
                go = airborne and agl > 300 and ac.vs_fpm > 100
            elif tr == "crucero":
                go = airborne and agl > 1500 and abs(ac.vs_fpm) < 300
            elif tr == "final":
                h = w.home.ref
                d = math.hypot(ac.pos[0] - h[0], ac.pos[1] - h[1])
                go = airborne and agl < 800 and ac.vs_fpm < -200 and d < 3 * NM
            elif tr in ("tiempo", "azar"):
                go = w.sim_time >= e["at"]
            if go:
                e["fired"] = True
                self.trigger(e["key"])
        # --- paracaídas CAPS: descenso estabilizado a ~1700 ft/min con el avión nivelado
        if self.caps:
            import numpy as np
            from .mathx import quat_from_euler
            self.caps_t += dt
            k = min(1.0, self.caps_t / 4.0)
            wind = w.atmo.wind_at(max(0.0, ac.agl))
            target = np.array([wind[0], wind[1], 6.0])
            ac.vel = ac.vel + (target - ac.vel) * min(1.0, dt * (0.6 + 2.0 * k))
            ac.q = quat_from_euler(0.0, math.radians(-2.0) * k, math.radians(ac.heading))
            ac.omega *= 0.0
            for en in s.engines:
                en.throttle = 0.0
            if ac.on_ground or ac.agl < 0.5:
                ac.caps_landing = True
                ac._crash("Aterrizaje bajo el paracaídas CAPS: avión dañado, ocupantes a salvo")
                self.resolve_once("engine", "paracaídas CAPS")
                return
        f = s.failures
        e0 = s.engines[0]
        # --- fuego de motor
        if f.get("fire"):
            cut = s.fuel_selector == 0 or (e0.magnetos == 0 if ac.t.fadec else e0.mixture < 0.1)
            if cut:
                fast = 1.6 if w.ind.ias > ac.t.v["vy"] * 1.15 else 1.0       # picar ayuda a apagarlo
                s.fire_level = max(0.0, s.fire_level - dt / 14.0 * fast)
                if s.fire_level <= 0.0:
                    f["fire"] = False
                    self.resolve("fire", "fuego apagado (combustible cortado)")
            else:
                s.fire_level = min(1.0, s.fire_level + dt / 110.0)
            if s.fire_level > 0.25:
                f["engine"] = True                                        # el motor acaba parándose
            if s.fire_level >= 1.0:
                ac._crash("Fuego de motor fuera de control")
                return
        # --- humo en cabina (fuego eléctrico)
        if f.get("smoke"):
            if s.master:
                s.smoke_level = min(1.0, s.smoke_level + dt / 95.0)
            else:
                s.smoke_level = max(0.0, s.smoke_level - dt / 40.0)
                if s.smoke_level <= 0.0:
                    self.resolve("smoke", "maestro OFF, humo despejado")
            if s.smoke_level >= 1.0:
                ac._crash("Incapacitación por humo en cabina")
                return
        else:
            s.smoke_level = max(0.0, s.smoke_level - dt / 30.0)
        # --- compensador desbocado
        if f.get("trim") and s.trim_cb:
            ac.trim = clamp(ac.trim + self.trim_dir * 0.075 * dt, -1.0, 1.0)
        # --- puerta abierta
        if f.get("door") and ac.on_ground and ac.gs < 1:
            f["door"] = False
            self.resolve("door", "cerrada en tierra")
        # --- fuga de combustible
        if f.get("fuel_leak") and s.fuel_l > 0:
            s.fuel_l = max(0.0, s.fuel_l - 32.0 / 3600.0 * dt)
        # --- magneto
        if not f.get("magneto"):
            for en in s.engines:
                en.bad_mag = 0
        elif e0.magnetos == 2 and not any(x["key"] == "magneto" and x["resolved"] for x in self.log):
            self.resolve("magneto", "magneto izquierdo seleccionado")
        # --- hielo en el carburador: la calefacción termina la falla (el hielo ya formado se funde en el motor)
        if f.get("carb_ice") and s.carb_heat:
            f["carb_ice"] = False
            self.resolve("carb_ice", "calefacción al carburador")
        # --- procedimientos cumplidos (para el informe)
        if f.get("radio") and w.xpdr == 7600:
            self.resolve_once("radio", "transpondedor 7600")
        if (f.get("alternator") or f.get("electrical")) and not s.lights["landing"] and not s.pitot_heat:
            self.resolve_once("alternator" if f.get("alternator") else "electrical", "cargas no esenciales apagadas")
        if (f.get("engine") or f.get("engine2")) and w.xpdr == 7700:
            self.resolve_once("engine", "MAYDAY / 7700")
        # --- radio: señales luminosas de la torre (transpondedor 7600)
        self.light = None
        if f.get("radio"):
            h = w.home.ref
            d = math.hypot(ac.pos[0] - h[0], ac.pos[1] - h[1])
            if d < 4 * NM:
                busy = w.atc.runway_busy_ai(final_nm=1.5) is not None
                if ac.on_ground:
                    self.light = ("verde", True) if not busy else ("rojo", True)
                else:
                    self.light = ("rojo", False) if busy else ("verde", False)

    # ------------------------------------------------------------ acciones del piloto
    def deploy_caps(self):
        w = self.world
        ac = w.ac
        if ac.t.id != "sr20":
            return "Este avión no tiene paracaídas balístico."
        if self.caps:
            return "El paracaídas ya está desplegado."
        if ac.on_ground or ac.agl / FT < 300:
            return "Demasiado bajo para el paracaídas (mínimo recomendado 400 ft sobre el terreno)."
        if w.ind.ias > 140:
            return "Reduzca por debajo de 140 kt antes de activar el CAPS."
        self.caps = True
        self.caps_t = 0.0
        return "¡CAPS ACTIVADO! Mezcla corte, combustible cerrado, maestro OFF, cinturones apretados."

    def close_door(self):
        w = self.world
        s = w.ac.sys
        if not s.failures.get("door"):
            return "La puerta ya está cerrada."
        if w.ind.ias > 82:
            return "Reduzca por debajo de 80 kt para poder cerrar la puerta."
        s.failures["door"] = False
        self.resolve("door", "cerrada en vuelo")
        return "Puerta cerrada."

    def trim_disconnect(self):
        s = self.world.ac.sys
        if s.trim_cb:
            s.trim_cb = False
            if s.failures.get("trim"):
                self.resolve("trim", "compensador eléctrico desconectado")
            return "Compensador eléctrico DESCONECTADO (cortacircuito fuera)."
        s.trim_cb = True
        return "Compensador eléctrico conectado."

    def gear_emergency(self):
        s = self.world.ac.sys
        if not self.world.ac.t.retractable:
            return "Este avión tiene tren fijo."
        s.gear_emergency = True
        s.gear_down = True
        if s.failures.get("gear"):
            self.resolve("gear", "extensión de emergencia")
        return "Extensión de emergencia del tren: bajando por gravedad."

    def extinguisher(self):
        s = self.world.ac.sys
        if s.extinguisher <= 0:
            return "El extintor está vacío."
        s.extinguisher = 0.0
        s.smoke_level = max(0.0, s.smoke_level - 0.35)
        return "Extintor descargado. Ventile la cabina."

    # ------------------------------------------------------------ informe
    def report(self):
        out = []
        for e in self.log:
            name = NAMES.get(e["key"], e["key"])
            if e["resolved"] is not None:
                out.append((name, f"resuelta en {e['resolved'] - e['t']:.0f} s — {e['note']}", True))
            else:
                out.append((name, "sin resolver", False))
        return out
