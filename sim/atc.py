"""Control de tránsito aéreo: torre, rodadura y ATIS del aeródromo principal.

Fraseología OACI en español (Doc 4444 / Doc 9432, como la usan ENAIRE y SENEAM). Cada
transmisión tiene un texto para pantalla y otro para la voz (con alfabeto y cifras deletreadas).
El alumno elige qué decir en el menú de radio; la torre contesta, da autorizaciones, secuencia
el tráfico, avisa de tráfico cercano y anota las faltas de comunicación para el informe.
"""
import math
import random

from .mathx import FT, KT, NM, wrap180

PHON = dict(A="Alfa", B="Bravo", C="Charlie", D="Delta", E="Eco", F="Foxtrot", G="Golf", H="Hotel", I="India",
            J="Juliet", K="Kilo", L="Lima", M="Maik", N="Noviembre", O="Óscar", P="Papa", Q="Quebec", R="Romeo",
            S="Sierra", T="Tango", U="Uniform", V="Víctor", W="Whisky", X="Equis", Y="Yanqui", Z="Zulú")
DIG = "cero uno dos tres cuatro cinco seis siete ocho nueve".split()
CLOCK_WORDS = {1: "la una", 2: "las dos", 3: "las tres", 4: "las cuatro", 5: "las cinco", 6: "las seis", 7: "las siete",
               8: "las ocho", 9: "las nueve", 10: "las diez", 11: "las once", 12: "las doce"}
TYPE_NAMES = {"c172": "Cessna", "pa28r": "Piper", "da40": "Diamond", "da42": "Diamond bimotor", "a320": "Airbus 320",
              "e190": "Embraer 190"}


def digits(s):
    return " ".join(DIG[int(c)] if c.isdigit() else (PHON.get(c.upper(), c)) for c in str(s) if c not in " -")


def spell(callsign):
    return " ".join(PHON.get(c.upper(), DIG[int(c)] if c.isdigit() else "") for c in callsign if c.isalnum())


def freq_disp(f):
    return f"{f:.3f}".rstrip("0").rstrip(".") if f else ""


def freq_sp(f):
    a, _, b = f"{f:.3f}".partition(".")
    b = b.rstrip("0") or "0"
    return f"{digits(a)} decimal {digits(b)}"


class Msg:
    def __init__(self, who, station, disp, spk, delay=0.4, voice=None):
        self.who = who                  # 'yo', 'atc', 'ia', 'atis'
        self.station = station          # 'TWR', 'GND', 'ATIS'
        self.disp = disp
        self.spk = spk
        self.delay = delay
        self.voice = voice or {"yo": "piloto", "atc": "torre", "ia": "otro", "atis": "atis"}[who]


class ATC:
    def __init__(self, world, callsign="EC-AES"):
        self.world = world
        self.callsign = callsign.upper()
        self.out = []                   # transmisiones pendientes de emitir por la radio
        self.hints = []                 # avisos para el alumno (pantalla)
        self.violations = []
        self.enabled = True
        self.external = False           # True: la torre la lleva un simulador de ATC externo (app/atc_link.py)
        self.ext_options = None         # menú de radio propuesto por el ATC externo
        self.ext_last = None            # último mensaje del ATC externo (para colacionarlo)
        self.pilot_tx = []              # transmisiones del piloto para el enlace externo
        self.rng = random.Random()
        self.atis_letter = "A"
        self.reset()

    # ------------------------------------------------------------------ utilidades
    @property
    def ac(self):
        return self.world.ac

    @property
    def freqs(self):
        return self.world.freqs

    def station_of(self, f):
        for k, v in self.freqs.items():
            if abs(v - f) < 0.004:
                return k
        return None

    def tuned(self):
        w = self.world
        if not w.ac.sys.avionics_ok or w.ac.sys.failures.get("radio"):
            return None
        return self.station_of(w.com_freq)

    def cs(self):
        return self.callsign, spell(self.callsign)

    def facility(self):
        w = self.world
        if w.is_school:
            return "Base Escuela", "Base Escuela"
        nm = (w.location or {}).get("municipality") or w.home.name
        nm = nm.split("/")[0].split(",")[0].strip()
        return nm, nm

    def rwy(self):
        e = self.world.active_end
        return e, digits(e)

    def wind(self):
        wx = self.world.weather
        if wx.wind_kt < 2.5:
            return "viento en calma", "viento en calma"
        # la torre y el ATIS dan el viento magnético (el METAR, verdadero)
        d = int(round((wx.wind_dir - self.world.magvar) / 10.0) * 10) % 360 or 360
        k = int(round(wx.wind_kt))
        g = f" ráfagas {int(round(wx.wind_kt + wx.gust_kt))}" if wx.gust_kt > 2 else ""
        return f"viento {d:03d}° {k} kt{g}", f"viento {digits(f'{d:03d}')} grados, {k} nudos" + (
            f", ráfagas {int(round(wx.wind_kt + wx.gust_kt))}" if g else "")

    def qnh(self):
        q = int(round(self.world.weather.qnh_hpa))
        return f"QNH {q}", f"QNH {digits(q)}"

    def say(self, who, station, parts, delay=None, voice=None):
        """parts: lista de str (igual en pantalla y voz) o tuplas (pantalla, voz)."""
        disp = "".join(p if isinstance(p, str) else p[0] for p in parts)
        spk = "".join(p if isinstance(p, str) else p[1] for p in parts)
        if delay is None:
            delay = 0.3 if who == "yo" else self.rng.uniform(1.2, 2.4)
        m = Msg(who, station, disp, spk, delay, voice)
        self.out.append(m)
        if who == "yo":
            self.pilot_tx.append((station, disp))
        return m

    def tower(self, *parts, delay=None):
        st = "TWR" if self.tuned() == "TWR" else (self.tuned() or "TWR")
        return self.say("atc", st, [self.cs(), ", "] + list(parts), delay)

    def violation(self, text):
        if text not in self.violations:
            self.violations.append(text)

    # ------------------------------------------------------------------ estado
    def reset(self):
        """Se llama al recolocar el avión: deduce la fase a partir de la posición."""
        w = self.world
        ac = w.ac
        self.out.clear()
        self.violations = []
        self.engaged = False            # el alumno ha hablado con la torre en este vuelo
        self.need_readback = None
        self.readback_due = 0.0
        self.readback_asked = False
        self.cleared_takeoff = False
        self.cleared_land = False
        self.landing_kind = "completo"
        self.lineup = False
        self.hold_for_traffic = False
        self.continue_app = False
        self.go_around_given = False
        self.exit_given = False
        self.taxi_cleared = False
        self.reported = set()
        self.advised = {}
        self.last_leg = {}
        self.ai_talk_t = 8.0
        self.atis_t = 0.0
        self.time = 0.0
        self.squawk = None
        self.was_airborne = not ac.on_ground
        self.on_rw_prev = False
        self.atis_letter = chr(ord("A") + self.rng.randrange(0, 12))
        on_rw = ac.on_ground and w.active_rw.contains(ac.pos[0], ac.pos[1], 2.0)
        if on_rw:
            # las lecciones empiezan alineadas: se considera ya autorizado a alinear
            self.phase = "alineado"
            self.lineup = True
        elif ac.on_ground:
            self.phase = "tierra"
        else:
            self.phase = "vuelo"

    # ------------------------------------------------------------------ geometría
    def rel_runway(self, p):
        thr, hdg, d, r = self.world.runway_frame()
        along = (p[0] - thr[0]) * d[0] + (p[1] - thr[1]) * d[1]
        lat = (p[0] - thr[0]) * r[0] + (p[1] - thr[1]) * r[1]
        return along, lat

    def dist_home_nm(self):
        h = self.world.home.ref
        return math.hypot(self.ac.pos[0] - h[0], self.ac.pos[1] - h[1]) / NM

    def in_pattern(self):
        return self.dist_home_nm() < 4.0 and self.ac.agl / FT < 2000

    def runway_busy_ai(self, final_nm=0.0):
        """¿Hay un avión IA en la pista o en final a menos de final_nm?"""
        for p in self.world.traffic.planes:
            if p.state in ("carrera", "rodando", "alineando"):
                return p
            if final_nm and p.state == "vuelo" and p.leg in ("final", "toma"):
                along, lat = self.rel_runway(p.pos)
                if -final_nm * NM < along < 200 and abs(lat) < 600:
                    return p
        return None

    def sequence(self):
        """Número de secuencia del alumno y el tráfico al que debe seguir."""
        ahead = [p for p in self.world.traffic.planes if p.state == "vuelo" and p.leg in ("base", "final", "toma")]
        ahead.sort(key=lambda p: {"toma": 0, "final": 1, "base": 2}[p.leg])
        return len(ahead) + 1, (ahead[-1] if ahead else None)

    def describe_plane(self, p):
        tn = TYPE_NAMES.get(p.type_id, "avioneta")
        return f"{tn} en {p.leg}"

    # ------------------------------------------------------------------ menú de radio
    def options(self):
        """Lista de (texto, estación, función) disponibles ahora mismo."""
        if self.external:
            return self.ext_menu()
        ac = self.ac
        w = self.world
        opts = []
        if self.need_readback:
            opts.append(("Colacionar: " + self.need_readback[0][:58], self.need_readback[2], self.do_readback))
        if ac.crashed:
            return opts
        gnd = "GND" if "GND" in self.freqs else "TWR"
        on_rw = ac.on_ground and w.active_rw.contains(ac.pos[0], ac.pos[1], 2.0)
        if ac.on_ground:
            if not on_rw:
                if self.phase == "aterrizado":
                    opts.append(("Pista libre, solicito rodar a plataforma", gnd, self.req_taxi_in))
                else:
                    opts.append(("Solicitar rodaje (con la información ATIS)", gnd, self.req_taxi))
                    opts.append(("Punto de espera: listo para salir", "TWR", self.req_departure))
            if on_rw and not self.cleared_takeoff:
                opts.append(("Listo para despegar (en pista)", "TWR", self.req_departure))
            opts.append(("Solicitar ATIS / meteorología", "TWR", self.req_weather))
        else:
            inbound = self.dist_home_nm() > 3.5
            if inbound:
                opts.append(("Contacto inicial: solicitar entrada al circuito", "TWR", self.req_join))
            else:
                if "viento en cola" not in self.reported:
                    opts.append(("Notificar viento en cola", "TWR", lambda: self.report("viento en cola")))
                if "base" not in self.reported:
                    opts.append(("Notificar base", "TWR", lambda: self.report("base")))
                if "final" not in self.reported:
                    opts.append(("Notificar final (aterrizaje completo)", "TWR", lambda: self.report("final", "completo")))
                    opts.append(("Notificar final (toma y despegue)", "TWR", lambda: self.report("final", "toque")))
                opts.append(("Abandonar el circuito", "TWR", self.req_leave))
            opts.append(("Motor y al aire", "TWR", self.report_go_around))
            opts.append(("MAYDAY (emergencia)", "TWR", self.mayday))
        if self.pending_traffic():
            opts.insert(0, ("Tráfico a la vista", "TWR", lambda: self.traffic_ack(True)))
            opts.insert(1, ("Negativo contacto, buscando", "TWR", lambda: self.traffic_ack(False)))
        return opts[:9]

    # ------------------------------------------------------------------ ATC externo
    def ext_menu(self):
        """Menú de radio cuando la torre la lleva un simulador de ATC externo: frases estándar
        (o las que proponga ese simulador). Lo que se dice se le envía como texto."""
        from app.atc_link import DEFAULT_OPTIONS
        ac = self.ac
        opts = []
        if self.ext_last is not None:
            d, s, st = self.ext_last
            opts.append(("Colacionar: " + d[:58], st, self.ext_readback))
        if ac.crashed:
            return opts
        src = self.ext_options if self.ext_options is not None else DEFAULT_OPTIONS
        where = "tierra" if ac.on_ground else "vuelo"
        for label, phrase, st, when in src:
            if when in ("ambos", where):
                opts.append((label, st, lambda p=phrase, s_=st: self.ext_say(p, s_)))
        return opts[:9]

    def ext_say(self, phrase, station):
        st = self.station_of(self.world.com_freq) or station
        fac = self.facility()
        name = {"TWR": "torre", "GND": "rodadura"}.get(st, "")
        head = [(f"{fac[0]} {name}, ", f"{fac[1]} {name}, ")] if name else []
        self.engaged = True
        self.say("yo", st, head + [self.cs(), (f", {phrase}", f", {phrase}")])
        if not self.world.ac.sys.avionics_ok:
            self.hints.append("La radio está apagada: encienda el interruptor de aviónica.")
        elif self.ac.sys.failures.get("radio"):
            self.hints.append("La radio no transmite: FALLA DE COMUNICACIONES. Transpondedor 7600.")

    def ext_readback(self):
        d, s, st = self.ext_last
        self.ext_last = None
        cs = self.callsign.replace("-", "").upper()
        d2 = d.replace(self.callsign, "").replace(cs, "").strip(" ,")
        s2 = s.replace(self.callsign, "").replace(cs, "").strip(" ,")
        self.say("yo", self.station_of(self.world.com_freq) or st, [(d2 + ", ", s2 + ", "), self.cs()])

    def ext_message(self, disp, spk, station="TWR", readback=True):
        """Transmisión que llega del simulador de ATC externo."""
        spk = spk.replace(self.callsign, spell(self.callsign)).replace(self.callsign.replace("-", ""), spell(self.callsign))
        self.say("atc", station, [(disp, spk)], delay=0.2)
        self.ext_last = (disp, spk, station) if readback else None

    def pending_traffic(self):
        return getattr(self, "_traffic_q", None) is not None and self.time - self._traffic_q < 25

    def transmit(self, station, parts):
        """El alumno transmite. Devuelve True si la estación correcta le escucha."""
        self.engaged = True
        self.say("yo", self.tuned() or station, parts)
        t = self.tuned()
        if t is None:
            if self.ac.sys.failures.get("radio"):
                self.hints.append("La radio no transmite: FALLA DE COMUNICACIONES. Transpondedor 7600 y observe las luces de la torre.")
            elif not self.ac.sys.avionics_ok:
                self.hints.append("La radio está apagada: encienda el interruptor de aviónica.")
            else:
                f = self.freqs.get(station, self.freqs["TWR"])
                self.hints.append(f"Nadie responde: sintonice {station} {freq_disp(f)} en COM1.")
            return False
        if t == "ATIS":
            self.hints.append("Está en la frecuencia del ATIS (solo escucha). Cambie a TWR o GND en COM1.")
            return False
        if t != station:
            f = self.freqs[station]
            name = {"TWR": "torre", "GND": "rodadura"}[station]
            self.say("atc", t, [self.cs(), f", contacte {name} en ", (freq_disp(f), freq_sp(f))])
            return False
        return True

    def ask_readback(self, disp, spk, station="TWR"):
        self.need_readback = (disp, spk, station)
        self.readback_due = self.time + 30
        self.readback_asked = False

    def do_readback(self):
        d, s, st = self.need_readback
        self.need_readback = None
        self.say("yo", self.tuned() or st, [(d + ", ", s + ", "), self.cs()])

    # ------------------------------------------------------------------ peticiones del alumno
    def callup(self, station):
        fac = self.facility()
        name = {"TWR": ("Torre", "torre"), "GND": ("Rodadura", "rodadura")}[station]
        return [(f"{fac[0]} {name[0].lower()}, ", f"{fac[1]} {name[1]}, "), self.cs()]

    def req_taxi(self):
        st = "GND" if "GND" in self.freqs else "TWR"
        info = (f", con la información {self.atis_letter}", f", con la información {PHON[self.atis_letter]}")
        if not self.transmit(st, self.callup(st) + [", en plataforma", info, ", solicito rodar para circuitos locales"]):
            return
        self.squawk = self.squawk or f"{self.rng.randint(4, 6)}{self.rng.randint(0, 7)}{self.rng.randint(0, 7)}{self.rng.randint(0, 7)}"
        r = self.rwy()
        q = self.qnh()
        self.say("atc", st, [self.cs(), ", rode al punto de espera pista ", r, ", ", q, ", transpondedor ",
                             (self.squawk, digits(self.squawk))])
        self.phase = "rodaje"
        self.taxi_cleared = True
        self.ask_readback(f"Rodar al punto de espera pista {r[0]}, {q[0]}, transpondedor {self.squawk}",
                          f"Rodar al punto de espera pista {r[1]}, {q[1]}, transpondedor {digits(self.squawk)}", st)

    def req_departure(self):
        ac = self.ac
        on_rw = ac.on_ground and self.world.active_rw.contains(ac.pos[0], ac.pos[1], 2.0)
        r = self.rwy()
        where = (", alineado pista ", ", alineado pista ") if on_rw else (", punto de espera pista ", ", punto de espera pista ")
        if not self.transmit("TWR", self.callup("TWR") + [where, r, ", listo para salir"]):
            return
        if not self.taxi_cleared and not on_rw and "GND" in self.freqs:
            self.violation("Rodó sin autorización de rodadura")
        self.decide_departure()

    def decide_departure(self, delay=None):
        r = self.rwy()
        busy = self.runway_busy_ai(final_nm=2.5)
        if busy is not None:
            self.hold_for_traffic = True
            what = "tráfico en final" if busy.state == "vuelo" else "tráfico en la pista"
            if self.lineup:
                self.tower("mantenga posición, ", what, delay=delay)
                self.ask_readback("Mantengo posición", "Mantengo posición")
            else:
                self.tower("mantenga posición punto de espera pista ", r, ", ", what, delay=delay)
                self.ask_readback(f"Mantengo punto de espera pista {r[0]}", f"Mantengo punto de espera pista {r[1]}")
            return
        self.hold_for_traffic = False
        wd = self.wind()
        self.tower("pista ", r, ", ", wd, ", autorizado a despegar", delay=delay)
        self.cleared_takeoff = True
        self.lineup = True
        self.phase = "despegue"
        self.ask_readback(f"Autorizado a despegar pista {r[0]}", f"Autorizado a despegar pista {r[1]}")

    def req_weather(self):
        if not self.transmit("TWR", self.callup("TWR") + [", solicito meteorología"]):
            return
        self.tower(self.wind(), ", ", self.qnh(), ", pista en servicio ", self.rwy())

    def req_join(self):
        h = self.bearing_from_home()
        d = max(1, round(self.dist_home_nm()))
        alt = int(round(self.ac.alt_ind_ft / 100.0) * 100)
        info = (f", con la información {self.atis_letter}", f", con la información {PHON[self.atis_letter]}")
        if not self.transmit("TWR", self.callup("TWR") + [(f", {d} millas al {h[0]}", f", {d} millas al {h[1]}"),
                                                         (f", {alt} pies", f", {alt} pies"), info, ", para aterrizaje"]):
            return
        r = self.rwy()
        self.tower("entre en viento en cola izquierda pista ", r, ", ", self.qnh(), ", notifique viento en cola")
        self.phase = "vuelo"
        self.reported.discard("viento en cola")
        self.reported.discard("base")
        self.reported.discard("final")
        self.ask_readback(f"Entrar viento en cola izquierda pista {r[0]}, {self.qnh()[0]}",
                          f"Entrar viento en cola izquierda pista {r[1]}, {self.qnh()[1]}")

    def bearing_from_home(self):
        h = self.world.home.ref
        b = math.degrees(math.atan2(self.ac.pos[1] - h[1], self.ac.pos[0] - h[0])) % 360
        names = ["norte", "noreste", "este", "sureste", "sur", "suroeste", "oeste", "noroeste"]
        n = names[int((b + 22.5) // 45) % 8]
        return n, n

    def report(self, leg, kind=None):
        r = self.rwy()
        extra = ""
        if kind:
            self.landing_kind = kind
            extra = ", aterrizaje completo" if kind == "completo" else ", para toma y despegue"
        if not self.transmit("TWR", [self.cs(), f", {leg}", (" pista " + r[0], " pista " + r[1]) if leg == "final" else "", extra]):
            return
        self.reported.add(leg)
        if leg == "viento en cola":
            self.reported.discard("base")
            self.reported.discard("final")
            n, follow = self.sequence()
            if follow is None:
                self.tower("número uno, notifique base")
            else:
                self.tower(f"número {n}, siga al {self.describe_plane(follow)}, notifique base")
                self._traffic_q = self.time
        else:
            self.landing_decision(leg)

    def landing_decision(self, leg, delay=None):
        r = self.rwy()
        busy = self.runway_busy_ai(final_nm=1.2 if leg == "base" else 0.0)
        if busy is not None:
            self.continue_app = True
            n, follow = self.sequence()
            what = "tráfico en la pista" if busy.state != "vuelo" else "tráfico en final"
            self.tower("continúe aproximación, ", what, ", espere autorización", delay=delay)
            return
        self.continue_app = False
        wd = self.wind()
        what = ("autorizado a aterrizar", "autorizado a aterrizar") if self.landing_kind == "completo" else \
            ("autorizado toma y despegue", "autorizado toma y despegue")
        self.tower("pista ", r, ", ", wd, ", ", what, delay=delay)
        self.cleared_land = True
        lbl = "Autorizado a aterrizar" if self.landing_kind == "completo" else "Autorizado toma y despegue"
        self.ask_readback(f"{lbl} pista {r[0]}", f"{lbl} pista {r[1]}")

    def req_leave(self):
        if not self.transmit("TWR", [self.cs(), ", abandono el circuito"]):
            return
        self.tower("abandone el circuito, notifique cambiando de frecuencia")
        self.phase = "salida"

    def report_go_around(self):
        if not self.transmit("TWR", [self.cs(), ", motor y al aire"]):
            return
        self.tower("recibido, ascienda en rumbo de pista a 1000 pies, notifique viento en cola")
        self.cleared_land = False
        self.continue_app = False
        self.reported = set()

    def mayday(self):
        alt = int(round(self.ac.alt_ind_ft / 100.0) * 100)
        d = round(self.dist_home_nm(), 1)
        h = self.bearing_from_home()
        fac = self.facility()
        self.engaged = True
        prob = "falla de motor" if any(e.failed or not e.running for e in self.ac.sys.engines) else "emergencia"
        self.say("yo", self.tuned() or "TWR", [("MAYDAY MAYDAY MAYDAY, ", "Mayday, mayday, mayday, "),
                                                 (f"{fac[0]} torre, ", f"{fac[1]} torre, "), self.cs(), f", {prob}",
                                                 (f", {d:g} millas al {h[0]}, {alt} pies, intento aterrizar",
                                                  f", {d:g} millas al {h[1]}, {alt} pies, intento aterrizar")])
        if self.tuned() not in ("TWR", "GND"):
            self.hints.append("Para declarar emergencia sintonice la torre o 121.5 y transponder 7700.")
            return
        r = self.rwy()
        self.say("atc", "TWR", [self.cs(), ", recibido MAYDAY, pista ", r, " a su disposición, ", self.wind(),
                                ", ", self.qnh(), ", tráfico informado, autorizado a aterrizar a discreción"])
        self.cleared_land = True
        self.landing_kind = "completo"
        for p in self.world.traffic.planes:
            if p.state == "vuelo" and p.leg in ("final", "toma", "base"):
                p.wp = p._pattern()
                p.wi = 2

    def req_taxi_in(self):
        st = "GND" if "GND" in self.freqs else "TWR"
        if not self.transmit(st, self.callup(st) + [", pista libre, solicito rodar a plataforma"]):
            return
        self.tower("rode a plataforma, ", self.qnh())
        self.phase = "rodaje"
        self.ask_readback("Rodar a plataforma", "Rodar a plataforma", st)

    def traffic_ack(self, seen):
        self._traffic_q = None
        if not self.transmit("TWR", [self.cs(), ", tráfico a la vista" if seen else ", negativo contacto"]):
            return
        if not seen:
            self.tower("mantenga vigilancia, le avisaré")

    # ------------------------------------------------------------------ actualización
    def update(self, dt):
        if self.external:
            self.time += dt
            return
        if not self.enabled:
            self.out.clear()
            return
        self.time += dt
        w = self.world
        ac = w.ac
        if ac.crashed:
            return
        r = self.rwy()
        on_rw = ac.on_ground and w.active_rw.contains(ac.pos[0], ac.pos[1], 2.0)
        # colación olvidada
        if self.need_readback and not self.readback_asked and self.time > self.readback_due:
            self.readback_asked = True
            self.tower("colacione")
            self.violation("No colacionó una autorización")
        if self.engaged:
            # entrar en pista sin autorización
            if on_rw and not self.on_rw_prev and not (self.lineup or self.cleared_takeoff or self.phase == "aterrizado") and ac.gs > 1.5:
                self.tower("ha entrado en la pista sin autorización, mantenga posición")
                self.violation("Incursión en pista: entró sin autorización")
            # despegue sin autorización
            rolling = all(e.throttle > 0.7 for e in ac.sys.engines)
            if on_rw and rolling and ac.gs > 25 * KT and not self.cleared_takeoff:
                if "despegue" not in self.reported:
                    self.reported.add("despegue")
                    self.tower("no está autorizado a despegar")
                    self.violation("Despegó sin autorización")
            # mantener en espera hasta que se libere la pista
            if self.hold_for_traffic and self.runway_busy_ai(final_nm=2.5) is None and not self.out:
                self.hold_for_traffic = False
                self.decide_departure()
            # continuar aproximación → autorización o motor y al aire
            if self.continue_app and not ac.on_ground:
                along, lat = self.rel_runway(ac.pos)
                busy = self.runway_busy_ai(final_nm=0.0)
                if busy is None and not self.out:
                    self.landing_decision("final")
                elif busy is not None and -0.6 * NM < along < 0 and abs(lat) < 400 and not self.go_around_given:
                    self.go_around_given = True
                    self.continue_app = False
                    self.tower("motor y al aire, tráfico en la pista", delay=0.3)
                    self.ask_readback("Motor y al aire", "Motor y al aire")
        # despegue y toma
        if not ac.on_ground and ac.agl > 15:
            if not self.was_airborne:
                self.was_airborne = True
                if self.engaged and self.cleared_takeoff:
                    self.phase = "vuelo"
                self.cleared_takeoff = False
                self.lineup = False
                self.reported.discard("despegue")
        if ac.on_ground and self.was_airborne and ac.gs > 10:
            self.was_airborne = False
            if self.engaged and self.dist_home_nm() < 2:
                if not self.cleared_land:
                    self.tower("ha aterrizado sin autorización, llame a la torre en tierra", delay=2.0)
                    self.violation("Aterrizó sin autorización")
                if self.landing_kind == "toque" and self.cleared_land:
                    self.cleared_takeoff = True
                    self.landing_kind = "toque_ok"
                else:
                    self.phase = "aterrizado"
                    self.exit_given = False
            self.cleared_land = False
            self.reported = set()
            self.go_around_given = False
        if self.landing_kind == "toque_ok" and not ac.on_ground and ac.agl > 15:
            self.landing_kind = "completo"
        if self.phase == "aterrizado" and on_rw and ac.gs < 22 * KT and not self.exit_given and self.engaged:
            self.exit_given = True
            if "GND" in self.freqs:
                g = self.freqs["GND"]
                self.tower("abandone la pista por la primera disponible, contacte rodadura en ", (freq_disp(g), freq_sp(g)))
            else:
                self.tower("abandone la pista por la primera disponible, notifique pista libre")
        self.on_rw_prev = on_rw
        # avisos de tráfico (servicio de información de tránsito)
        if self.engaged and not ac.on_ground and self.tuned() == "TWR":
            for p in w.traffic.planes:
                if p.on_ground:
                    continue
                d = p.pos - ac.pos
                dist = math.hypot(d[0], d[1])
                dalt = (-d[2]) / FT
                if dist < 2.2 * NM and abs(dalt) < 900 and self.time - self.advised.get(p.callsign, -999) > 90 and not self.out:
                    self.advised[p.callsign] = self.time
                    rel = wrap180(math.degrees(math.atan2(d[1], d[0])) - ac.heading)
                    clock = int(round(((rel + 360) % 360) / 30.0)) % 12 or 12
                    nm = max(1, round(dist / NM))
                    if abs(dalt) < 250:
                        vert = "misma altitud"
                    else:
                        vert = f"{int(round(abs(dalt) / 100) * 100)} pies por {'encima' if dalt > 0 else 'debajo'}"
                    tn = TYPE_NAMES.get(p.type_id, "avioneta")
                    self.tower((f"tráfico a sus {clock}, {nm} {'milla' if nm == 1 else 'millas'}, {tn}, {vert}",
                                f"tráfico a {CLOCK_WORDS[clock]}, {nm} {'milla' if nm == 1 else 'millas'}, {tn}, {vert}"))
                    self._traffic_q = self.time
                    break
        # charla del tráfico IA en la frecuencia de torre
        self.ai_talk_t -= dt
        for p in w.traffic.planes:
            prev = self.last_leg.get(p.callsign)
            cur = (p.state, p.leg)
            self.last_leg[p.callsign] = cur
            if prev is None or prev == cur or self.tuned() != "TWR":
                continue
            if self.out or self.ai_talk_t > 0:
                continue
            self.ai_chatter(p, prev, cur)
        # ATIS en bucle
        if self.tuned() == "ATIS":
            self.atis_t -= dt
            if self.atis_t <= 0 and not self.out:
                self.atis_t = 40.0
                self.broadcast_atis()
        else:
            self.atis_t = 0.0

    def ai_chatter(self, p, prev, cur):
        state, leg = cur
        r = self.rwy()
        cs = (p.callsign, getattr(p, "spoken", None) or spell(p.callsign))
        fac = self.facility()
        said = False
        if state == "vuelo" and leg == "viento en cola" and prev[1] != "viento en cola":
            self.say("ia", "TWR", [cs, ", viento en cola, para toma y despegue" if p.kind == "circuito" else ", viento en cola, para aterrizaje completo"])
            n = 1 + sum(1 for o in self.world.traffic.planes if o is not p and o.state == "vuelo" and o.leg in ("base", "final", "toma"))
            self.say("atc", "TWR", [cs, f", número {n}, notifique base" if n > 1 else ", número uno, notifique base"])
            said = True
        elif state == "vuelo" and leg == "final" and prev[1] in ("base", "aproximación"):
            self.say("ia", "TWR", [cs, ", final pista ", r])
            if self.ac.on_ground and self.world.active_rw.contains(self.ac.pos[0], self.ac.pos[1], 2.0):
                self.say("atc", "TWR", [cs, ", continúe aproximación, tráfico en la pista"])
            else:
                kind = "autorizado toma y despegue" if p.kind == "circuito" else "autorizado a aterrizar"
                self.say("atc", "TWR", [cs, ", pista ", r, ", ", self.wind(), ", ", kind])
            said = True
        elif state == "vuelo" and leg == "entrada" and prev[0] != "vuelo":
            pass
        elif state == "alineando" and prev[0] == "espera":
            self.say("ia", "TWR", [(f"{fac[0]} torre, ", f"{fac[1]} torre, "), cs, ", punto de espera pista ", r, ", listo para salir"])
            self.say("atc", "TWR", [cs, ", pista ", r, ", ", self.wind(), ", autorizado a despegar"])
            said = True
        elif state == "saliendo" and prev[0] == "rodando":
            self.say("ia", "TWR", [cs, ", pista libre"])
            said = True
        if said:
            self.ai_talk_t = 12.0

    def broadcast_atis(self):
        w = self.world
        wx = w.weather
        fac = self.facility()
        L = self.atis_letter
        r = self.rwy()
        hh = int(wx.hour) % 24
        mm = int((wx.hour % 1) * 60) // 10 * 10
        hora = f"{hh:02d}{mm:02d}"
        from .atmosphere import rain_visibility
        vis_m = min(wx.visibility_m, rain_visibility(wx.rain))
        vis = "10 kilómetros o más" if vis_m >= 10000 else f"{int(vis_m // 100 * 100)} metros"
        fen = ""
        if getattr(wx, "storm", False):
            dn, de = wx.storm_n - w.home.ref[0], wx.storm_e - w.home.ref[1]
            dist_nm = max(1, round(math.hypot(dn, de) / 1852))
            card = ("norte", "noreste", "este", "sureste", "sur", "suroeste", "oeste", "noroeste")[
                int(((math.degrees(math.atan2(de, dn)) % 360) + 22.5) // 45) % 8]
            fen = f"Tormenta a {dist_nm} millas al {card}. "
            if math.hypot(wx.storm_vn, wx.storm_ve) > 1:
                fen += "Se aproxima al aeródromo. " if (dn * wx.storm_vn + de * wx.storm_ve) < 0 else ""
        elif wx.rain > 0.02:
            fen = ("Llovizna. " if wx.rain < 0.35 else "Lluvia moderada. " if wx.rain < 0.75 else "Lluvia fuerte. ")
        if getattr(w.atmo, "wet", 0.0) > 0.3:
            fen += "Pista mojada, acción de frenado media. "
        cov = wx.cloud_cover
        base = int(max(0, wx.cloud_base_ft - w.home.elev / FT) / 100) * 100
        if cov < 0.1:
            nub = "sin nubes de importancia"
        else:
            nub = ("pocas" if cov < 0.3 else "dispersas" if cov < 0.55 else "nubosidad abundante" if cov < 0.85 else "cubierto") + f" a {base} pies"
        t = int(round(15 + wx.temp_offset - w.home.elev / FT * 0.002))
        dp = t - 7
        q = self.qnh()
        self.say("atis", "ATIS", [(f"{fac[0]}, información {L}, ", f"{fac[1]}, información {PHON[L]}, "),
                                  (f"hora {hora}. ", f"hora {digits(hora)}. "), "Pista en servicio ", r, ". ", self.wind(), ". ",
                                  f"Visibilidad {vis}. ", fen, nub.capitalize(), ". ",
                                  (f"Temperatura {t}, punto de rocío {dp}. ", f"Temperatura {t}, punto de rocío {dp}. "), q, ". ",
                                  (f"Notifique en el contacto inicial que tiene la información {L}.",
                                   f"Notifique en el contacto inicial que tiene la información {PHON[L]}.")], delay=0.6)
