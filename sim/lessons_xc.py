"""Travesías (cross-country) con plan de vuelo: ACS PA.VI.A (pilotaje y navegación a estima)
y PA.VI.D (desvío a un alternativo).

El plan se calcula con el viento real de la lección: rumbo corregido (triángulo de velocidades),
velocidad respecto al suelo, tiempo estimado y combustible necesario con la reserva legal
VFR diurna de 30 minutos (FAR 91.151 / SERA). En el simulador el norte magnético coincide con el
geográfico, así que rumbo verdadero = magnético.
"""
import math

import numpy as np

from .lessons import IR, PPL, Monitor, Step, _LandingLesson, hdg_err, mon_alt
from .mathx import FT, KT, NM, clamp, wrap180

CAT = "8 · Travesías y misiones"


def course_deg(a, b):
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 360


def wind_triangle(tc, tas, wdir, wkt):
    """(rumbo, velocidad suelo) para volar el curso tc con viento que sopla DESDE wdir."""
    if wkt < 0.5:
        return tc, tas
    rel = math.radians(wdir - tc)
    s = clamp(wkt * math.sin(rel) / tas, -0.95, 0.95)
    wca = math.degrees(math.asin(s))
    gs = tas * math.cos(math.radians(wca)) - wkt * math.cos(rel)
    return (tc + wca) % 360, max(30.0, gs)


class Leg:
    def __init__(self, name, a, b, alt_ft, tas, wx):
        self.name = name
        self.a = np.array(a, float)
        self.b = np.array(b, float)
        self.tc = course_deg(a, b)
        self.dist_nm = float(np.linalg.norm(self.b - self.a)) / NM
        self.hdg, self.gs = wind_triangle(self.tc, tas, wx.wind_dir, wx.wind_kt)
        self.ete_min = self.dist_nm / self.gs * 60.0
        self.alt_ft = alt_ft


class _Travesia(_LandingLesson):
    category = CAT
    acs = "PA.VI.A"
    standard = PPL
    duration = "15 min"
    guided = False
    airport_idx = 1
    divert = False
    fuel_lph = 32.0             # consumo de crucero del C172 (≈ 8,5 gal/h)

    def weather(self, w):
        super().weather(w)
        w.wind_dir, w.wind_kt = 300, 14
        w.cloud_cover, w.cloud_base_ft = 0.35, 6500

    def setup(self, world):
        if len(world.airports) < 2:
            self.airport_idx = 0
        super().setup(world)

    def build(self, world):
        home = world.home
        dest = world.airports[self.airport_idx]
        wx = world.weather
        A = max(world.cruise_alt_ft(), round((max(home.elev, dest.elev) / FT + 2500) / 500) * 500)
        self.cruise = A
        tas = 105 * (1 + 0.02 * A / 1000)
        # punto de control a mitad de camino, algo desplazado (como un pueblo o un cruce)
        d = dest.ref - home.ref
        if np.linalg.norm(d) < 3000:
            d = np.array([12000.0, 6000.0])
        perp = np.array([-d[1], d[0]]) / max(1.0, np.linalg.norm(d))
        cp = home.ref + d * 0.5 + perp * 1500
        self.legs = [Leg("Salida → Punto de control", home.ref, cp, A, tas, wx),
                     Leg(f"Punto de control → {dest.ident}", cp, dest.ref, A, tas, wx)]
        self.cp = cp
        self.dest = dest
        trip = sum(l.ete_min for l in self.legs)
        self.fuel_trip = trip / 60 * self.fuel_lph
        self.fuel_need = self.fuel_trip + 5 + 0.5 * self.fuel_lph          # rodaje + reserva de 30 min
        self.t_off = None
        self.eta_err = None
        self.diverted_t = None
        world.route = [home.ref, cp, dest.ref]
        L0, L1 = self.legs

        def off(w, L):
            if not w.ac.on_ground and w.ac.agl / FT > 300:
                L.t_off = L.t
                return True
            return False

        def dist_to(p):
            return lambda w: math.hypot(w.ac.pos[0] - p[0], w.ac.pos[1] - p[1])

        def at_cp(w, L):
            if dist_to(cp)(w) < 1200:
                L.eta_err = (L.t - (L.t_off or 0)) / 60 - L0.ete_min
                return True
            return False

        def hdg_mon(leg):
            return Monitor("Rumbo corregido", lambda w: (w.ac.heading, abs(hdg_err(w, leg.hdg)) < 15, f"{leg.hdg:03.0f} ±15°"),
                           15, "{:03.0f}", "°")
        self.steps = [
            Step(f"Despegue y ascenso a {A:.0f} ft", off, voice=f"Despegue. Ascienda a {A:.0f} pies."),
            Step(f"Rumbo {L0.hdg:03.0f} al punto de control ({L0.dist_nm:.1f} NM, {L0.ete_min:.0f} min)", at_cp,
                 voice=f"Rumbo {L0.hdg:03.0f} hacia el punto de control. Tiempo estimado {L0.ete_min:.0f} minutos.",
                 monitors=[hdg_mon(L0), mon_alt(A, 200, 12, "Altitud de crucero")]),
        ]
        if self.divert:
            self.airport_idx = 0
            alt_ap = world.home

            def turned(w, L):
                if L.diverted_t is None:
                    L.diverted_t = L.t
                ok = abs(hdg_err(w, course_deg(w.ac.pos[:2], alt_ap.ref))) < 20
                if ok:
                    L.divert_time = L.t - L.diverted_t
                return ok

            def near(w, L):
                return math.hypot(w.ac.pos[0] - alt_ap.ref[0], w.ac.pos[1] - alt_ap.ref[1]) < 6000
            self.steps += [
                Step(f"¡DESVÍO! {dest.ident} cerrado por meteorología: vire hacia {alt_ap.ident}", turned,
                     voice=f"Atención: el aeródromo de destino ha cerrado por meteorología. Desvíe a {alt_ap.name}. "
                           "Estime rumbo, distancia y tiempo y vire sin demora.", timeout=90,
                     hint=f"{alt_ap.ident} está detrás de usted: use el mapa del MFD o el VOR."),
                Step(f"Diríjase a {alt_ap.ident} y prepare la llegada", near,
                     voice="Bien. Mantenga la altitud y prepare la llegada.", monitors=[mon_alt(A, 200, 10)]),
            ]
            world.route = [home.ref, cp, home.ref]
            self.steps += self.final_steps(world, 65)
        else:
            def near_dest(w, L):
                return dist_to(dest.ref)(w) < 7000
            self.steps += [
                Step(f"Rumbo {L1.hdg:03.0f} a {dest.ident} ({L1.dist_nm:.1f} NM, {L1.ete_min:.0f} min)", near_dest,
                     voice=f"Punto de control. Nuevo rumbo {L1.hdg:03.0f} hacia {dest.name}.",
                     monitors=[hdg_mon(L1), mon_alt(A, 200, 12, "Altitud de crucero")]),
                Step(f"Descienda e incorpórese al circuito de {dest.ident}", lambda w, L: True,
                     voice=f"Inicie el descenso y prepare la llegada a {dest.name}."),
            ] + self.final_steps(world, 65)

    def update(self, dt, world, events):
        super().update(dt, world, events)
        cp = self.cp
        if self.idx == 1:
            gh = world.terrain.height(cp[0], cp[1])
            self.rings = [(np.array([cp[0], cp[1], -(gh + 4)]), 0.0, 60.0, (1.0, 0.85, 0.2, 0.9))]
        elif self.landing is None or self.landing.touch is None:
            if not self.guided:
                self.rings = []

    def finish(self, success, reason, world):
        world.route = None
        super().finish(success, reason, world)

    def plan_rows(self):
        """Filas del cuaderno de navegación (para la tableta)."""
        rows = []
        for l in self.legs:
            rows.append((l.name, f"CV {l.tc:03.0f}° · R {l.hdg:03.0f}°",
                         f"{l.dist_nm:.1f} NM · GS {l.gs:.0f} kt · {l.ete_min:.0f} min"))
        rows.append(("Combustible", f"viaje {self.fuel_trip:.0f} L", f"necesario con reserva {self.fuel_need:.0f} L"))
        return rows

    def extra_items(self, world):
        items = super().extra_items(world)
        e = self.eta_err
        items.append(("Llegada al punto de control (estima)", 15 if e is not None and abs(e) <= 2 else (7 if e is not None and abs(e) <= 4 else 0),
                      15, f"{e:+.1f} min respecto al plan" if e is not None else "no se alcanzó"))
        fuel_ok = world.ac.sys.fuel_l > 0.5 * self.fuel_lph
        items.append(("Reserva de combustible al llegar", 10 if fuel_ok else 0, 10, f"{world.ac.sys.fuel_l:.0f} L"))
        if self.divert:
            dtm = getattr(self, "divert_time", None)
            items.append(("Tiempo en decidir y virar al alternativo", 15 if dtm is not None and dtm < 30 else (7 if dtm is not None else 0),
                          15, f"{dtm:.0f} s" if dtm is not None else "no desvió"))
        return items


class L_Travesia(_Travesia):
    id = "travesia"
    title = "Travesía con plan de vuelo"
    acs = "PA.VI.A"
    brief = ("ACS PA.VI.A — Pilotaje y navegación a estima a otro aeródromo con un punto de control intermedio (aro amarillo). "
             "Abra la tableta (K) → pestaña PLAN: allí está el cuaderno de navegación calculado con el viento del día "
             "(curso, rumbo corregido, distancia, velocidad suelo, tiempo y combustible con la reserva de 30 min). "
             "Vuele los rumbos del plan (ACS ±15°, altitud ±200 ft), compruebe la hora en el punto de control y aterrice en destino. "
             "La ruta aparece en magenta en el mapa del MFD.")
    objectives = ["Rumbo corregido ±15°", "Altitud ±200 ft", "Llegar al punto de control en hora (±2 min)", "Aterrizar en destino"]


class L_Desvio(_Travesia):
    id = "desvio"
    title = "Desvío a un alternativo"
    acs = "PA.VI.D"
    divert = True
    brief = ("ACS PA.VI.D — Igual que la travesía, pero al pasar el punto de control el destino cerrará por meteorología. "
             "Decida sin demora, estime rumbo, distancia y tiempo al alternativo (el aeródromo de salida), vire y mantenga la "
             "altitud. Se evalúa la rapidez de la decisión y la llegada segura.")
    objectives = ["Decidir y virar en menos de 30 s", "Rumbo y tiempo al alternativo", "Altitud ±200 ft", "Aterrizar en el alternativo"]


XC_LESSONS = [L_Travesia, L_Desvio]
