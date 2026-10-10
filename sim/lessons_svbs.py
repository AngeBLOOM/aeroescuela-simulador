"""Misiones en la Base Aérea Mariscal Sucre (SVBS), Maracay, estado Aragua (Venezuela).

Usan el escenario real (foto satelital, relieve, Lago de Valencia como agua de verdad) y lugares reales:
Isla del Burro, la ciudad de Maracay, la Base Aérea El Libertador (SVBL, Palo Negro) y la Cordillera de la
Costa (Parque Nacional Henri Pittier) al norte. Cada misión carga SVBS sola si hace falta (atributo location).
"""
import math

import numpy as np

from .lessons import PPL, Monitor, Step, _LandingLesson, alt, hdg_err, mon_alt, mon_speed
from .lessons_emerg import L_Fuego, L_IMC, _Emerg, landed, mon_bank_max
from .lessons_xc import L_Travesia, course_deg
from .mathx import FT, KT, NM, clamp, wrap180

CAT = "10 · Misiones Base Sucre (Maracay)"
SVBS = "SVBS"
# lugares reales (lat, lon)
ISLA_BURRO = (10.1596, -67.7303)
MARACAY_CENTRO = (10.2469, -67.5958)


def local(world, latlon):
    """Coordenadas locales (norte, este) de un punto geográfico del escenario real."""
    n, e = world.location["proj"].to_local(*latlon)
    return np.array([float(n), float(e)])


def airport(world, ident):
    return next((i for i, a in enumerate(world.airports) if a.ident == ident), None)


def dist(w, p):
    return math.hypot(w.ac.pos[0] - p[0], w.ac.pos[1] - p[1])


class _Mision:
    """Mezcla común: categoría, ubicación obligatoria y viento del oeste (pista 29 en servicio)."""
    category = CAT
    location = SVBS
    standard = PPL

    def weather(self, w):
        super().weather(w)
        w.wind_kt, w.gust_kt = 8, 0
        w.hour = 9.5
        w.cloud_cover, w.cloud_base_ft = 0.3, 5000
        w.visibility_m = 25000


class _Ruta(_Mision, L_Travesia):
    """Navegación por puntos reales (aros amarillos) y aterrizaje en el aeródromo de destino."""
    altitude = 3000.0
    dest_ident = SVBS
    wind_rel = 180                  # viento del oeste: pista 29

    def waypoints(self, world):
        return []

    def setup(self, world):
        i = airport(world, self.dest_ident)
        self.airport_idx = i if i is not None else 0
        super(L_Travesia, self).setup(world)

    def build(self, world):
        from .lessons_xc import Leg
        home = world.home
        dest = world.airports[self.airport_idx]
        A = self.altitude
        wx = world.weather
        wps = self.waypoints(world)
        pts = [("Base Sucre", home.ref)] + wps + [(dest.name if dest is not home else "Base Sucre", dest.ref)]
        self.cruise = A
        self.legs = [Leg(f"{a[0]} → {b[0]}", a[1], b[1], A, 100, wx, world.magvar) for a, b in zip(pts, pts[1:])]
        self.cp = wps[0][1]
        self.dest = dest
        trip = sum(l.ete_min for l in self.legs)
        self.fuel_trip = trip / 60 * self.fuel_lph
        self.fuel_need = self.fuel_trip + 5 + 0.5 * self.fuel_lph
        self.t_off = None
        self.eta_err = None
        self.diverted_t = None
        self.divert = False
        self.wp_i = 0
        world.route = [p for _n, p in pts]

        def off(w, L):
            if not w.ac.on_ground and w.ac.agl / FT > 300:
                L.t_off = L.t
                return True
            return False

        def hdg_mon(leg):
            return Monitor("Rumbo", lambda w: (w.mag(w.ac.heading), abs(hdg_err(w, leg.hdg)) < 20, f"{leg.hdg_m:03d} ±20°"),
                           12, "{:03.0f}", "°")
        self.steps = [Step(f"Despegue por la {world.active_end} y ascenso a {A:.0f} ft", off,
                           voice=f"Despegue por la pista {world.active_end}. Ascienda a {A:.0f} pies.")]
        for k, leg in enumerate(self.legs[:-1]):
            name, p = wps[k]

            def at_wp(w, L, p=p, k=k, leg=leg):
                if dist(w, p) < 1500:
                    if k == 0:
                        L.eta_err = (L.t - (L.t_off or 0)) / 60 - leg.ete_min
                    L.wp_i = k + 1
                    return True
                return False
            self.steps.append(Step(f"Rumbo {leg.hdg_m:03d} a {name} ({leg.dist_nm:.1f} NM, {leg.ete_min:.0f} min)", at_wp,
                                   voice=self.wp_voice(k, name, leg),
                                   monitors=[hdg_mon(leg), mon_alt(A, 200, 12, "Altitud de crucero")]))
        last = self.legs[-1]
        near = 4000.0 if dest is not home else 6000.0
        self.steps += [
            Step(f"Rumbo {last.hdg_m:03d} a {dest.ident} ({last.dist_nm:.1f} NM)", lambda w, L: dist(w, dest.ref) < near,
                 voice=self.last_voice(dest, last), monitors=[hdg_mon(last), mon_alt(A, 200, 12, "Altitud de crucero")]),
            Step(f"Descienda e incorpórese al circuito de {dest.ident}", lambda w, L: True,
                 voice=f"Inicie el descenso y prepare la llegada a {dest.name}."),
        ] + self.final_steps(world, 65)

    def wp_voice(self, k, name, leg):
        return f"Rumbo {leg.hdg_m:03d} hacia {name}."

    def last_voice(self, dest, leg):
        return f"Nuevo rumbo {leg.hdg_m:03d} hacia {dest.name}."

    def update(self, dt, world, events):
        super(L_Travesia, self).update(dt, world, events)
        wps = self.waypoints(world)
        if 1 <= self.idx <= len(wps) and self.wp_i < len(wps):
            p = wps[self.wp_i][1]
            gh = world.terrain.height(p[0], p[1])
            self.rings = [(np.array([p[0], p[1], -(gh + 4)]), 0.0, 60.0, (1.0, 0.85, 0.2, 0.9))]
        elif self.landing is None or self.landing.touch is None:
            self.rings = []


# ------------------------------------------------------------------ 1. reconocimiento del lago
class M_Lago(_Ruta):
    id = "svbs_lago"
    title = "Reconocimiento del Lago de Valencia e Isla del Burro"
    acs = "PA.VI.A"
    duration = "12 min"
    altitude = 3000.0
    brief = ("Misión de navegación observada (pilotaje). Despegue por la 29 de Base Sucre, salga sobre el Lago de Valencia "
             "y vuele hasta la Isla del Burro (aro amarillo) a 3000 ft. Identifique la isla, la costa de Maracay y la Base "
             "El Libertador al este. Regrese a Base Sucre, incorpórese al circuito y aterrice. Altitud ±200 ft. "
             "Si el motor fallase sobre el lago: amerizaje controlado cerca de la costa.")
    objectives = ["Navegación por referencias visuales", "Altitud 3000 ft ±200", "Llegar a la Isla del Burro",
                  "Regreso y aterrizaje en Base Sucre"]

    def waypoints(self, world):
        return [("la Isla del Burro", local(world, ISLA_BURRO))]

    def wp_voice(self, k, name, leg):
        return f"Rumbo {leg.hdg_m:03d} hacia la Isla del Burro, la isla grande en el centro del lago."

    def last_voice(self, dest, leg):
        return (f"Isla del Burro a la vista. Vire a rumbo {leg.hdg_m:03d} y regrese a Base Sucre. La ciudad de Maracay "
                "queda a la derecha y la base El Libertador al fondo.")


# ------------------------------------------------------------------ 2. travesía a El Libertador
class M_Libertador(_Ruta):
    id = "svbs_libertador"
    title = "Travesía a la Base Aérea El Libertador (SVBL)"
    acs = "PA.VI.A"
    duration = "10 min"
    altitude = 3500.0
    dest_ident = "SVBL"
    brief = ("Navegación de Base Sucre (SVBS) a la Base Aérea El Libertador (SVBL, Palo Negro), al sureste. Primer punto: "
             "el centro de Maracay (aro amarillo); después rumbo a El Libertador. Tableta (K) → PLAN: rumbos corregidos con "
             "el viento, tiempos y combustible. 3500 ft ±200, rumbo ±20°, y aterrizaje en la pista larga de El Libertador.")
    objectives = ["Rumbo ±20°", "Altitud 3500 ft ±200", "Pasar por el centro de Maracay", "Aterrizar en El Libertador"]

    def waypoints(self, world):
        return [("el centro de Maracay", local(world, MARACAY_CENTRO))]

    def wp_voice(self, k, name, leg):
        return f"Rumbo {leg.hdg_m:03d} hacia el centro de Maracay, siguiendo la autopista."

    def last_voice(self, dest, leg):
        return f"Sobre Maracay. Nuevo rumbo {leg.hdg_m:03d} hacia la Base Aérea El Libertador, en Palo Negro."


# ------------------------------------------------------------------ 3. falla de motor al despegue: amerizaje
class M_Amerizaje(_Mision, _Emerg):
    id = "svbs_amerizaje"
    title = "Motor parado al despegar: amerizaje en el lago"
    acs = "PA.IX.B"
    duration = "4 min"
    start = "pista"
    wind_rel = 180
    fail_key = "engine"
    allow_stall = False
    brief = ("La pista 29 de Base Sucre termina en la orilla del Lago de Valencia. Tras el despegue, a unos 400 ft, el "
             "motor se parará. NO intente volver a la pista (el «viraje imposible»): baje la nariz de inmediato, mantenga "
             "la velocidad de planeo y aterrice al frente, como mucho 30° a cada lado. Si solo hay agua: amerizaje "
             "controlado con flaps completos, alas niveladas y la menor velocidad posible. MAYDAY si hay tiempo.")
    objectives = ["Nariz abajo de inmediato (velocidad ≥ 60 kt)", "Sin virajes de más de 30°",
                  "Amerizaje controlado: alas niveladas, baja velocidad"]

    def make_steps(self, world):
        self.rw_hdg = world.runway_frame()[1]
        self.max_turn = 0.0
        self.min_ias = None

        def climb_and_fail(w, L):
            if not w.ac.on_ground and w.ac.agl / FT > 400:
                w.emerg.trigger("engine")
                L.t_fail = L.t
                return True
            return False
        vg = world.ac.t.v["vglide"]
        return [
            Step(f"Despegue por la {world.active_end} y ascenso a Vy", climb_and_fail,
                 voice=f"Despegue por la pista {world.active_end}. Gases a fondo y ascenso a Vy."),
            Step("¡Motor parado! Nariz abajo, planee AL FRENTE y prepare el amerizaje", lambda w, L: False,
                 voice="¡Falla de motor! Nariz abajo, mejor planeo. Al frente, no vire de regreso. Flaps completos y amerizaje "
                       "controlado.",
                 monitors=[mon_speed(vg, 8, 12, 20, "Velocidad de planeo"),
                           Monitor("Desvío del rumbo de pista", lambda w: (abs(hdg_err(w, L_rw(self))),
                                                                          abs(hdg_err(w, L_rw(self))) <= 30, "≤ 30°"),
                                   20, "{:.0f}", "°")]),
        ]

    def update(self, dt, world, events):
        ac = world.ac
        if self.t_fail is not None and not ac.on_ground:
            self.max_turn = max(self.max_turn, abs(hdg_err(world, self.rw_hdg)))
            if self.t - self.t_fail > 1.0 and ac.agl / FT > 50:
                # antes de la recogida (en el amerizaje la velocidad mínima al final es lo correcto)
                self.min_ias = world.ind.ias if self.min_ias is None else min(self.min_ias, world.ind.ias)
            if world.xpdr == 7700:
                self.mark("7700")
            if ac.sys.flaps_cmd >= len(ac.t.flap_settings) - 1:
                self.mark("flaps")
        if ac.crashed and not self.done:
            self.touch_water = world.terrain.surface(ac.pos[0], ac.pos[1])[1] == "agua"
            if getattr(ac, "ditched", False):
                self.finish(True, "Amerizaje controlado", world)
                self.success = True
                return
        super().update(dt, world, events)
        if ac.on_ground and ac.gs < 2 and not ac.crashed and self.t_fail is not None and not self.done:
            self.finish(True, "Aterrizaje forzoso en tierra", world)

    def coaching(self, dt, world):
        if self.t_fail is not None:
            self.allow_stall = True             # la recogida del amerizaje se hace al borde de la pérdida
            if world.ac.agl / FT < 300:
                return                          # sin «¡Terreno!» en el descenso final al agua
        super().coaching(dt, world)

    def extra_items(self, world):
        ac = world.ac
        mi = self.min_ias if self.min_ias is not None else 0
        vs1 = ac.t.v.get("vs1", 53)
        items = [("Velocidad mínima en el planeo", 20 if mi >= vs1 + 5 else (8 if mi >= vs1 else 0), 20,
                  f"{mi:.0f} kt (pérdida {vs1} kt)"),
                 ("Viraje máximo (sin «viraje imposible»)", 15 if self.max_turn <= 30 else (6 if self.max_turn <= 60 else 0), 15,
                  f"{self.max_turn:.0f}°"),
                 self.timing("Flaps completos", "flaps", 30, 60, 5),
                 self.timing("Transpondedor 7700", "7700", 40, 90, 5)]
        if getattr(ac, "ditched", False):
            items.append(("Amerizaje", 25, 25, "controlado: ocupantes a salvo"))
        elif ac.crashed:
            items.append(("Amerizaje", 0, 25, ac.crash_reason))
        elif ac.on_ground:
            items.append(("Aterrizaje forzoso", 25, 25, "en tierra, sin daños"))
        else:
            items.append(("Amerizaje", 0, 25, "no terminó"))
        return items


def L_rw(lesson):
    return lesson.rw_hdg


# ------------------------------------------------------------------ 4. fuego sobre Maracay
class M_FuegoMaracay(_Mision, L_Fuego):
    id = "svbs_fuego"
    title = "Fuego de motor sobre Maracay: aterrizaje en una base"
    acs = "PA.IX.C"
    duration = "6 min"
    start = "crucero"
    brief = ("Vuela sobre el centro de Maracay a 5000 ft. Aparecerán humo y llamas en el morro. Elementos de memoria: "
             "MEZCLA CORTE, COMBUSTIBLE CERRADO, BOMBA OFF y MAESTRO OFF. Sin motor, planee hasta la pista más cercana: "
             "Base Sucre (SVBS) al oeste o El Libertador (SVBL) al sureste. No aterrice en la ciudad. MAYDAY y 7700.")
    objectives = ["Cortar el combustible en menos de 10 s", "Planeo a la mejor velocidad",
                  "Elegir la base más cercana", "Aterrizar en una pista"]

    def build(self, world):
        c = local(world, MARACAY_CENTRO)
        world.ac.place_in_air(c[0], c[1], 5000 * FT, 150.0, 100)
        super().build(world)

    def make_steps(self, world):
        steps = super().make_steps(world)
        steps[0] = self.fail_step("Crucero sobre Maracay a 5000 ft, rumbo 150", "Mantenga 5000 pies sobre Maracay, rumbo uno "
                                                                                "cinco cero.")
        steps[2] = Step("Planee a Base Sucre (oeste) o El Libertador (sureste) y aterrice", landed,
                        voice="Fuego apagado. Sin motor: elija la base más cercana y planee hasta su pista. Base Sucre al "
                              "oeste, El Libertador al sureste.",
                        monitors=[mon_speed(world.ac.t.v["vglide"], 10, None, 15, "Velocidad de planeo")])
        return steps

    def extra_items(self, world):
        items = super().extra_items(world)[:-1]
        ac = world.ac
        where = None
        if ac.on_ground and not ac.crashed:
            for a in world.airports:
                for rw in a.runways:
                    if rw.contains(ac.pos[0], ac.pos[1], 10.0):
                        where = a.ident
        if where:
            items.append(("Aterrizaje en una base", 25, 25, f"en la pista de {where}"))
        elif ac.crashed:
            items.append(("Aterrizaje en una base", 0, 25, "accidente"))
        elif ac.on_ground:
            items.append(("Aterrizaje en una base", 8, 25, "fuera de pista"))
        else:
            items.append(("Aterrizaje en una base", 0, 25, "no terminó"))
        return items


# ------------------------------------------------------------------ 5. nubes contra la cordillera
class M_Cordillera(_Mision, L_IMC):
    id = "svbs_cordillera"
    title = "Nubes contra la Cordillera de la Costa (Henri Pittier)"
    acs = "PA.VIII"
    duration = "4 min"
    start = "crucero"
    brief = ("Sale de Base Sucre hacia el norte a 4000 ft, bajo nubes que bajan sobre la Cordillera de la Costa (Parque "
             "Henri Pittier, picos de más de 5000 ft a 12 km). Entrará en nubes con las montañas DELANTE: no suba a ciegas "
             "ni siga. Viraje de 180° de régimen estándar hacia el sur, hacia el valle y el lago, con alabeo ≤ 30° y "
             "altitud ±200 ft. El margen con el terreno se evalúa.")
    objectives = ["Viraje inmediato hacia el valle", "Alabeo ≤ 30°", "Altitud ±200 ft", "Margen con el terreno ≥ 1000 ft"]

    def build(self, world):
        h = world.home.ref
        world.ac.place_in_air(h[0] + 5000.0, h[1] + 500.0, 4000 * FT, 360.0, 100)
        self.min_clear = None
        super().build(world)
        # la misión se vuela a 4000 ft (no a la altitud de crucero general)
        A = 4000.0
        self.A = A
        wx = world.weather
        self.steps[0].text = "VFR a 4000 ft, rumbo 360 hacia la cordillera"
        self.steps[0].voice = "Mantenga cuatro mil pies, rumbo tres seis cero. Las nubes están bajando sobre la cordillera."

        def enter_cloud(w, L):
            if L.t > 15:
                wx.cloud_cover, wx.cloud_base_ft, wx.cloud_top_ft, wx.visibility_m = 1.0, A - 600, A + 3500, 200
                return True
            return False
        self.steps[0].done = enter_cloud
        self.steps[1].monitors = [mon_alt(A, 200, 20), mon_bank_max(30, 20)]
        self.steps[2].monitors = [mon_alt(A, 200, 10),
                                  Monitor("Rumbo", lambda w: (w.mag(w.ac.heading), abs(hdg_err(w, self.Hr)) < 15,
                                                              f"{w.mag(self.Hr):03.0f} ±15°"), 10, "{:03.0f}", "°")]

        def exit_cloud(w, L):
            wx.cloud_cover, wx.cloud_base_ft, wx.cloud_top_ft = 0.6, A + 900, A + 3500
            wx.visibility_m = 15000
            return True
        self.steps[3].done = exit_cloud

    def weather(self, w):
        super().weather(w)
        # en un aeropuerto real las nubes de la lección se dan sobre el campo (Base Sucre está a 1420 ft)
        w.cloud_cover, w.cloud_base_ft, w.cloud_top_ft = 0.8, 3500, 7500
        w.visibility_m = 8000

    def update(self, dt, world, events):
        super().update(dt, world, events)
        ac = world.ac
        if not ac.on_ground:
            c = ac.agl / FT
            self.min_clear = c if self.min_clear is None else min(self.min_clear, c)
            self.coach("terreno", c < 1000 and ac.vs_fpm > -300, "¡Terreno! ¡Vire hacia el sur y suba!", 6)

    def extra_items(self, world):
        c = self.min_clear or 0
        return [("Margen mínimo con el terreno", 20 if c >= 1000 else (8 if c >= 500 else 0), 20, f"{c:.0f} ft")]


# ------------------------------------------------------------------ 6. traslado Caracas → Maracay
class M_CaracasMaracay(_Mision, _LandingLesson):
    """Dos escenarios reales en un solo vuelo: sale de La Carlota (Caracas) y, tras la salida del valle, el simulador
    pasa en vuelo al escenario de Maracay (crucero acelerado) para la llegada y el aterrizaje en Base Sucre."""
    id = "ccs_maracay"
    title = "Traslado La Carlota (Caracas) → Base Sucre (Maracay)"
    acs = "PA.VI.A / PA.IV.B"
    duration = "8 min"
    location = "SVFM"
    start = "pista"
    wind_rel = 180                  # viento del oeste: pista 29 en La Carlota y en Base Sucre
    dep_hdg = 280.0
    dep_alt = 4500.0
    brief = ("Traslado real de Caracas a Maracay en dos tramos. Despegue por la 29 de la Base Aérea Generalísimo Francisco "
             "de Miranda (La Carlota), con El Ávila a la derecha, y salga del valle de Caracas con rumbo 280 ascendiendo a "
             "4500 ft. Al dejar el valle, el crucero se acelera y el simulador le sitúa sobre Maracay, a 4 NM de Base Sucre "
             "en la prolongación de la pista 29: llame a Maracay torre, haga una aproximación directa y aterrice.")
    objectives = ["Salida del valle con rumbo 280 ±20°", "Ascenso a 4500 ft", "Aproximación directa a la 29 de Base Sucre",
                  "Aterrizaje"]

    def build(self, world):
        self.phase = 1
        self.switch_to = None
        home = world.home

        def off(w, L):
            return not w.ac.on_ground and w.ac.agl / FT > 300

        def out_of_valley(w, L):
            d = math.hypot(w.ac.pos[0] - home.ref[0], w.ac.pos[1] - home.ref[1])
            if d > 8000 and w.ind.alt_ft > self.dep_alt - 400:
                L.switch_to = SVBS
                return True
            return False
        hd_m = self.dep_hdg                 # rumbo de salida publicado (magnético)
        hd = world.true(hd_m)
        self.steps = [
            Step(f"Despegue por la {world.active_end} de La Carlota", off,
                 voice=f"Despegue por la pista {world.active_end} de La Carlota. El Ávila queda a la derecha."),
            Step(f"Rumbo {hd_m:03.0f} y ascenso a {self.dep_alt:.0f} ft: salida oeste del valle de Caracas", out_of_valley,
                 voice=f"Vire a rumbo {hd_m:03.0f} y ascienda a {self.dep_alt:.0f} pies para salir del valle de Caracas hacia "
                       "el oeste.",
                 monitors=[Monitor("Rumbo de salida", lambda w: (w.mag(w.ac.heading), abs(hdg_err(w, hd)) < 20, f"{hd_m:03.0f} ±20°"),
                                   12, "{:03.0f}", "°"),
                           mon_speed(world.ac.t.v["vy"], 5, 10, 10, "Velocidad de ascenso (Vy)")]),
            Step("Crucero hacia Maracay (avance rápido)…", lambda w, L: False,
                 voice="Fuera del valle. Crucero hacia Maracay."),
        ]

    def arrive(self, world):
        """Ya en el escenario de Maracay: a 4 NM de Base Sucre en la prolongación de la pista en servicio."""
        self.phase = 2
        self.rw = world.active_rw
        self.ident = world.active_end
        self.thr, self.hdg, self.d, self.r = world.runway_frame()
        self.elev_ft = world.home.elev / FT
        p = self.thr - self.d * (4 * NM)
        alt_ft = self.elev_ft + 4 * NM * math.tan(math.radians(3.0)) / FT + 60
        world.ac.place_in_air(p[0], p[1], alt_ft * FT, self.hdg, 95)
        world.ac.sys.engine.throttle = 0.55
        world.route = None
        thr = self.thr

        def near(w, L):
            return math.hypot(w.ac.pos[0] - thr[0], w.ac.pos[1] - thr[1]) < 2.6 * NM
        self.steps = [
            Step(f"Sobre Maracay: llame a Maracay torre y aproxímese a la {self.ident} de Base Sucre", near,
                 voice=f"Bienvenido a Maracay. Llame a Maracay torre, ciento dieciocho cero cinco, y haga una aproximación "
                       f"directa a la pista {self.ident} de Base Sucre.",
                 monitors=[Monitor("Rumbo de aproximación", lambda w: (w.mag(w.ac.heading), abs(hdg_err(w, self.hdg)) < 20,
                                                                      f"{w.mag(self.hdg):03.0f} ±20°"), 10, "{:03.0f}", "°")]),
        ] + self.final_steps(world, 65)
        self.idx = 0
        self._enter(world)


# ------------------------------------------------------------------ 7. travesía completa, sin cortes
class M_RutaCaracasMaracay(_Mision, _LandingLesson):
    """Ruta real Caracas → Maracay volada entera: el simulador va cargando escenarios reales a lo largo del camino
    (mundo continuo) sin detener el vuelo. Los puntos están en coordenadas geográficas y se recalculan en cada escenario."""
    id = "ruta_ccs_maracay"
    title = "Travesía completa La Carlota → Base Sucre (sin cortes)"
    acs = "PA.VI.A / PA.VI.B / PA.IV.B"
    duration = "35 min"
    location = "SVFM"
    start = "pista"
    wind_rel = 180
    continuous = True
    dest_ident = SVBS
    cruise = 7500.0
    WPS = [("Los Teques", (10.344, -67.041), 7500.0), ("La Victoria", (10.227, -67.333), 7500.0),
           ("Maracay", (10.2469, -67.5958), 4500.0)]
    brief = ("Travesía VFR real de Caracas a Maracay, entera y sin saltos: el simulador va cargando el paisaje real a lo "
             "largo de la ruta mientras vuela. Despegue por la 29 de La Carlota, ascienda dentro del valle con rumbo 290 "
             "hasta 5500 ft (hay cerros al suroeste), siga subiendo a 7500 ft y vuele los puntos de "
             "notificación: Los Teques, La Victoria (valle de Aragua) y Maracay (aros amarillos y ruta magenta en el MFD). "
             "Después de La Victoria descienda a 4500 ft, llame a Maracay torre y aterrice en la 29 de Base Sucre.")
    objectives = ["Seguir la ruta por los puntos de notificación", "Altitud de crucero ±300 ft",
                  "Descenso planificado al valle de Aragua", "Aterrizaje en Base Sucre"]

    def _pt(self, world, latlon):
        n, e = world.location["proj"].to_local(*latlon)
        return np.array([float(n), float(e)])

    def scene_hint(self, world, target_latlon):
        """El último tramo usa el escenario de Base Sucre (con su aeródromo como principal)."""
        la, lo = target_latlon
        if math.hypot((la - 10.25) * 111.3, (lo + 67.6494) * 109.5) < 30:
            return SVBS
        return None

    def on_scene_change(self, world):
        self._update_route(world)

    def _update_route(self, world):
        pts = [self._pt(world, p) for _n, p, _a in self.WPS[self.wp_i:]]
        world.route = [world.ac.pos[:2].copy()] + pts

    def build(self, world):
        self.wp_i = 0
        self.arrived = False
        self.stab = None
        self._lrw = None

        def off(w, L):
            return not w.ac.on_ground and w.ac.agl / FT > 300
        self.steps = [Step(f"Despegue por la {world.active_end} de La Carlota", off,
                           voice=f"Despegue por la pista {world.active_end} de La Carlota."),
                      Step("Ascenso en el valle con rumbo 290 hasta 5500 ft (cerros al suroeste)",
                           lambda w, L: w.ind.alt_ft > 5400,
                           voice="Ascienda dentro del valle con rumbo dos nueve cero hasta cinco mil quinientos pies antes de "
                                 "virar hacia Los Teques: al suroeste hay cerros.",
                           monitors=[Monitor("Rumbo de ascenso", lambda w: (w.mag(w.ac.heading), abs(hdg_err(w, w.true(290))) < 20,
                                                                           "290 ±20°"), 8, "{:03.0f}", "°")])]
        for k, (name, ll, A) in enumerate(self.WPS):
            def at(w, L, ll=ll, k=k):
                if math.hypot(*(w.ac.pos[:2] - L._pt(w, ll))) < 2500:
                    L.wp_i = k + 1
                    L._update_route(w)
                    return True
                return False
            voice = (f"Rumbo a {name}." if k == 0 else
                     f"Sobre {self.WPS[k - 1][0]}. Siguiente punto: {name}" + (", descienda a cuatro mil quinientos pies."
                                                                               if A < self.cruise else "."))
            self.steps.append(Step(f"Rumbo a {name} · {A:.0f} ft", at, voice=voice,
                                   monitors=[mon_alt(A, 300, 10, f"Altitud hacia {name}")]))

        def ready_for_final(w, L):
            if w.location.get("ident") != SVBS:
                return False
            if not L.arrived:
                L.arrived = True
                L.rw, L.ident = w.active_rw, w.active_end
                L.thr, L.hdg, L.d, L.r = w.runway_frame()
                L.elev_ft = w.home.elev / FT
                L.steps.extend(L.final_steps(w, 65))
            return True
        self.steps.append(Step("Sobre Maracay: llame a Maracay torre y prepare la llegada a Base Sucre", ready_for_final,
                               voice="Sobre Maracay. Llame a Maracay torre, ciento dieciocho cero cinco, e incorpórese para la "
                                     "pista de Base Sucre."))
        self._update_route(world)

    def update(self, dt, world, events):
        super().update(dt, world, events)
        if 2 <= self.idx <= len(self.WPS) + 1 and self.wp_i < len(self.WPS):
            p = self._pt(world, self.WPS[self.wp_i][1])
            gh = world.terrain.height(p[0], p[1])
            self.rings = [(np.array([p[0], p[1], -(gh + 4)]), 0.0, 90.0, (1.0, 0.85, 0.2, 0.9))]
        elif self.landing is None or self.landing.touch is None:
            if self.idx <= len(self.WPS) + 2:
                self.rings = []

    def finish(self, success, reason, world):
        world.route = None
        super().finish(success, reason, world)


SVBS_MISSIONS = [M_CaracasMaracay, M_RutaCaracasMaracay, M_Lago, M_Libertador, M_Amerizaje, M_FuegoMaracay, M_Cordillera]
