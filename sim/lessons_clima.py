"""Misiones de noche y con mal tiempo en lugares reales de Venezuela: circuito nocturno con las luces de Maracay,
aproximación de «agujero negro» sobre el Lago de Valencia, Caracas de noche, falla eléctrica nocturna, aguacero
tropical, tormenta que se acerca al aeródromo, desvío alrededor de una tormenta y niebla al amanecer con ILS."""
import math

import numpy as np

from .lessons import PPL, IR, L_Circuito, L_Final, L_ILS, Monitor, Step, _LandingLesson
from .lessons_emerg import L_Electrica, landed, outcome
from .lessons_svbs import MARACAY_CENTRO, M_Libertador, M_RutaCaracasMaracay, dist, local
from .mathx import FT, NM, clamp

CAT = "12 · Noche y meteorología"


class _Clima:
    category = CAT
    location = "SVBS"
    standard = PPL


def lights_item(L, need=("nav", "beacon", "landing")):
    """Puntuación de las luces encendidas al despegar o en la final (requisito nocturno)."""
    snap = getattr(L, "_lights_snap", None)
    names = dict(nav="navegación", beacon="anticolisión", strobe="estroboscópicas", landing="aterrizaje", taxi="rodaje")
    if snap is None:
        return ("Luces exteriores", 0, 10, "no se comprobaron")
    falt = [names[k] for k in need if not snap.get(k)]
    return ("Luces exteriores", 10 if not falt else (5 if len(falt) == 1 else 0), 10,
            "navegación, anticolisión y aterrizaje encendidas" if not falt else "faltaron: " + ", ".join(falt))


def snap_lights(L, world, cond):
    if getattr(L, "_lights_snap", None) is None and cond:
        L._lights_snap = dict(world.ac.sys.lights)


# ------------------------------------------------------------------ 1. circuito nocturno
class NC_Circuito(_Clima, L_Circuito):
    id = "nc_circuito"
    title = "Noche en Base Sucre: circuito con las luces de Maracay"
    acs = "PA.X.A + PA.III.B"
    duration = "10 min"
    night = True
    brief = ("Operación nocturna en Base Sucre, poco después de la puesta de sol. Antes de despegar encienda las luces de "
             "navegación, anticolisión y aterrizaje (L). Circuito por la izquierda a 1000 ft sobre el terreno, siguiendo los "
             "aros. De noche el horizonte casi no se ve sobre el lago: en el despegue y en los virajes vuele por el horizonte "
             "artificial. En la final, el PAPI (2 blancas y 2 rojas) y las luces de borde le dan la senda; las luces de "
             "Maracay engañan la percepción de la altura.")
    objectives = ["Luces exteriores encendidas", "Altitud de circuito ±100 ft", "Senda con el PAPI", "Aterrizaje nocturno"]

    def weather(self, w):
        super().weather(w)
        w.hour = 19.6
        w.cloud_cover, w.wind_kt = 0.12, 6

    def update(self, dt, world, events):
        super().update(dt, world, events)
        snap_lights(self, world, not world.ac.on_ground and world.ac.agl / FT > 50)

    def extra_items(self, world):
        return super().extra_items(world) + [lights_item(self)]


# ------------------------------------------------------------------ 2. agujero negro sobre el lago
class NC_AgujeroNegro(_Clima, L_Final):
    id = "nc_agujero_negro"
    title = "Noche sobre el Lago de Valencia: aproximación de agujero negro"
    acs = "PA.X.A + PA.IV.B"
    duration = "5 min"
    wind_rel = 0                      # viento del este: pista 11, con la final sobre el lago
    brief = ("De noche, final de 6 millas a la pista 11 de Base Sucre, que entra por encima del Lago de Valencia. "
             "Bajo el avión no hay ni una luz: es la ilusión del «agujero negro». El cerebro cree que va más alto de lo "
             "que va y el piloto tiende a bajar demasiado y a quedarse corto, en el agua. Vuele la senda con el PAPI "
             "(2 blancas, 2 rojas) y con el altímetro: unos 300 ft por cada milla de distancia. Nunca por debajo de la "
             "senda sobre el lago.")
    objectives = ["Senda 3° con el PAPI sobre el lago", "Nunca por debajo de la senda", "65 kt estabilizado",
                  "Toma en la zona de contacto"]

    def weather(self, w):
        super().weather(w)
        w.hour, w.cloud_cover, w.wind_kt, w.turbulence = 21.0, 0.05, 6, 0.05

    def build(self, world):
        rw, ident = world.active_rw, world.active_end
        thr, hdg, d = rw.end(ident)
        dd = 6 * NM
        p = thr - d * dd
        world.ac.place_in_air(p[0], p[1], world.home.elev + (dd + 300) * math.tan(math.radians(3.0)), hdg, 85, 1)
        world.ac.sys.lights.update(nav=True, beacon=True, landing=True)
        self.low_over_lake = 0.0
        self.min_dev = 0.0
        super().build(world)

    def update(self, dt, world, events):
        super().update(dt, world, events)
        ac = world.ac
        if self.landing is not None and self.landing.touch is None and not ac.on_ground:
            rw, ident = self._lrw
            along, _lat = rw.local(ac.pos[0], ac.pos[1], ident)
            if along < -300:
                gp = (-along + 300) * math.tan(math.radians(3.0))
                dev = math.degrees(math.atan2(ac.alt_msl - world.home.elev, -along + 300)) - 3.0
                self.min_dev = min(self.min_dev, dev)
                if dev < -0.7 and world.terrain.is_water(ac.pos[0], ac.pos[1]):
                    self.low_over_lake += dt
                    self.coach("bajo_lago", True, "¡Muy bajo sobre el lago! Cuatro luces rojas en el PAPI: potencia y suba a la senda.", 8)

    def extra_items(self, world):
        bajo = self.low_over_lake
        return super().extra_items(world) + [
            ("Sobre la senda en el tramo del lago", 15 if bajo < 1 else (7 if bajo < 10 else 0), 15,
             "nunca por debajo" if bajo < 1 else f"{bajo:.0f} s por debajo de la senda sobre el agua")]


# ------------------------------------------------------------------ 3. Caracas de noche
class NC_Carlota(_Clima, L_Final):
    id = "nc_carlota"
    title = "Caracas de noche: aterrizaje en La Carlota"
    location = "SVFM"
    acs = "PA.X.A + PA.IV.B"
    duration = "4 min"
    brief = ("Aproximación nocturna a La Carlota (SVFM), en el centro del valle de Caracas, con El Ávila oscuro al norte "
             "y la ciudad iluminada alrededor. Las luces de la ciudad no dejan ver bien la pista: búsquela por las luces "
             "de borde, el destello de aproximación y el PAPI. Luces exteriores encendidas, 65 kt estabilizado y senda "
             "de 3°. No descienda por debajo de la senda: hay edificios altos cerca de las cabeceras.")
    objectives = ["Identificar la pista entre las luces de la ciudad", "Senda 3° con el PAPI", "Aterrizaje nocturno"]

    def weather(self, w):
        super().weather(w)
        w.hour, w.cloud_cover, w.wind_kt = 20.3, 0.2, 5

    def build(self, world):
        world.ac.sys.lights.update(nav=True, beacon=True, landing=True)
        super().build(world)


# ------------------------------------------------------------------ 4. falla del alternador de noche
class NC_Electrica(_Clima, L_Electrica):
    id = "nc_electrica"
    title = "Falla del alternador de noche sobre Maracay"
    acs = "PA.IX.C + PA.X.A"
    duration = "8 min"
    brief = ("Crucero nocturno sobre Maracay. El alternador fallará: el amperímetro marca descarga y la batería se va "
             "agotando. De noche no se puede apagar todo: deje encendidas las luces de navegación y la radio, y apague "
             "la luz de aterrizaje, la calefacción del pitot y la bomba de combustible. Regrese a Base Sucre y encienda la "
             "luz de aterrizaje SOLO en la final corta (por debajo de 300 ft), para que la batería dure.")
    objectives = ["Detectar la falla", "Reducir la carga sin apagar las luces de navegación",
                  "Luz de aterrizaje solo en la final corta", "Aterrizar con batería"]

    def weather(self, w):
        super().weather(w)
        w.hour, w.cloud_cover, w.wind_kt = 20.5, 0.15, 6
        w.wind_dir = 285

    def setup(self, world):
        super().setup(world)
        world.ac.sys.lights.update(nav=True, beacon=True)
        self.ll_final = False

    def update(self, dt, world, events):
        super().update(dt, world, events)
        ac = world.ac
        if not ac.on_ground and ac.agl / FT < 300 and self.idx >= 2 and ac.sys.lights.get("landing"):
            self.ll_final = True

    def extra_items(self, world):
        nav = world.ac.sys.lights.get("nav")
        return super().extra_items(world) + [
            ("Luces de navegación encendidas", 5 if nav else 0, 5, "sí" if nav else "las apagó (de noche son obligatorias)"),
            ("Luz de aterrizaje en la final corta", 10 if self.ll_final else 0, 10,
             "encendida por debajo de 300 ft" if self.ll_final else "no se encendió para aterrizar")]


# ------------------------------------------------------------------ 5. aguacero tropical
class NC_Aguacero(_Clima, L_Final):
    id = "nc_aguacero"
    title = "Aguacero tropical: aterrizaje con lluvia fuerte y pista mojada"
    acs = "PA.IV.B (lluvia)"
    duration = "4 min"
    wind_rel = 200                     # pista 29, viento algo cruzado desde la izquierda
    brief = ("Típico chaparrón de la tarde en Maracay: lluvia fuerte, techo bajo, visibilidad de unos 2 km y viento "
             "racheado. El agua en el parabrisas no deja ver bien: vuele los primeros minutos con los instrumentos y "
             "busque las luces de la pista. Sume la mitad de la ráfaga a la velocidad (70 kt). Sobre la pista mojada "
             "las ruedas pueden patinar (hidroplaneo): toque firme, sin flotar, en la zona de contacto, y frene de forma "
             "suave y progresiva. Necesitará más pista para detenerse.")
    objectives = ["Aproximación estabilizada bajo la lluvia", "70 kt (mitad de la ráfaga)", "Toma firme en la zona",
                  "Detenerse dentro de la pista mojada"]

    def weather(self, w):
        super().weather(w)
        w.hour = 15.5
        w.rain = 0.85
        w.cloud_cover, w.cloud_base_ft, w.cloud_top_ft = 0.97, 1300, 9000
        w.wind_kt, w.gust_kt, w.turbulence = 10, 8, 0.35

    def build(self, world):
        world.ac.sys.lights.update(nav=True, beacon=True, landing=True)
        self.steps = self.final_steps(world, 70)

    def extra_items(self, world):
        J = self.landing
        ok = J is not None and J.stopped and not J.off_runway and J.rw.contains(world.ac.pos[0], world.ac.pos[1], 0.0)
        return super().extra_items(world) + [("Detenido dentro de la pista mojada", 10 if ok else 0, 10,
                                               "sí" if ok else "no se detuvo dentro de la pista")]


# ------------------------------------------------------------------ 6. tormenta que se acerca
class NC_Tormenta(_Clima, L_Final):
    id = "nc_tormenta"
    title = "Tormenta sobre el lago: aterrice antes de que llegue"
    acs = "PA.I.C + PA.IV.B"
    duration = "5 min"
    wind_rel = 180                     # pista 29: se aterriza hacia la tormenta
    brief = ("Regresa a Base Sucre por el este, en final larga de la pista 29. Sobre el Lago de Valencia, al oeste, hay "
             "una tormenta (cumulonimbo) que avanza hacia el aeródromo: la verá delante, oscura y con relámpagos (en la "
             "cabina de cristal aparece en el mapa en verde, amarillo y rojo). Antes de que llegue habrá un frente de "
             "ráfagas: viento fuerte y cambiante, turbulencia y lluvia. Aterrice cuanto antes, estabilizado y con 5 kt "
             "de más. Si la aproximación no está estabilizada a 500 ft, NO insista: motor y al aire, vire a la izquierda "
             "(hacia el sur) alejándose de la tormenta y diríjase a El Libertador, al sureste. Nunca entre en la tormenta.")
    objectives = ["Aterrizar antes de que llegue la tormenta", "No entrar en la tormenta", "Aproximación estabilizada",
                  "Controlar las ráfagas del frente"]

    def weather(self, w):
        super().weather(w)
        w.hour = 16.8
        w.cloud_cover, w.cloud_base_ft, w.cloud_top_ft = 0.55, 2800, 7000
        w.wind_kt, w.gust_kt, w.turbulence = 8, 6, 0.25

    def build(self, world):
        rw, ident = world.active_rw, world.active_end
        thr, hdg, d = rw.end(ident)
        dd = 4.5 * NM
        p = thr - d * dd
        world.ac.place_in_air(p[0], p[1], world.home.elev + (dd + 300) * math.tan(math.radians(3.0)) + 60, hdg, 90, 1)
        world.ac.sys.lights.update(nav=True, beacon=True, landing=True)
        # la tormenta, más allá de la cabecera opuesta y avanzando hacia el aeródromo
        w = world.weather
        # a unos 5 km del umbral: cuando se aterriza ya sopla el frente de ráfagas; el núcleo llega a los 10 min
        far = thr + d * 5300.0
        w.storm, w.storm_r = True, 2400.0
        w.storm_n, w.storm_e = float(far[0]), float(far[1])
        w.storm_vn, w.storm_ve = float(-d[0] * 5.0), float(-d[1] * 5.0)
        self.inside_t = 0.0
        self.min_storm = 1e9
        self.warned = False
        self.steps = self.final_steps(world, 70)

    def update(self, dt, world, events):
        super().update(dt, world, events)
        at = world.atmo
        self.min_storm = min(self.min_storm, at.storm_dist)
        if not self.done and at.storm_near > 0.2 and not self.warned:
            self.warned = True
            self.say("Torre: viento racheado por el frente de la tormenta. Mantenga la velocidad y esté listo para motor y al aire.")
        if at.storm_core > 0.5 and not world.ac.on_ground:
            self.inside_t += dt
            if self.inside_t > 8 and not self.done:
                self.finish(False, "Entró en la tormenta: turbulencia severa y descendentes", world)

    def extra_items(self, world):
        km = self.min_storm / 1000.0
        return super().extra_items(world) + [
            ("Lejos del núcleo de la tormenta", 15 if self.inside_t < 0.5 else 0, 15,
             f"distancia mínima {km:.1f} km" if self.inside_t < 0.5 else f"{self.inside_t:.0f} s dentro de la tormenta")]


# ------------------------------------------------------------------ 7. desvío alrededor de una tormenta
TORMENTA_SUR = (10.195, -67.660)       # sobre el lago, al sur de Base Sucre (a más de 5 km de la tormenta)


class NC_Desvio(_Clima, M_Libertador):
    id = "nc_desvio"
    category = CAT
    title = "Desvío por tormenta: de Base Sucre a El Libertador"
    acs = "PA.VI.D"
    duration = "11 min"
    altitude = 3000.0
    brief = ("Hay una tormenta parada sobre el centro de Maracay, justo en la ruta directa a la Base Aérea El Libertador. "
             "Regla de oro: nunca a menos de 5 km (unas 3 millas) de una tormenta, ni por debajo. Despegue por la 29, "
             "vire a la izquierda y rodéela por el sur pasando por el punto SUR (aro amarillo, sobre el lago); "
             "después rumbo a El Libertador y aterrice. 3000 ft ±200. En la cabina de cristal la tormenta se ve en el mapa.")
    objectives = ["Rodear la tormenta a más de 5 km", "Altitud 3000 ft ±200", "Pasar por el punto SUR",
                  "Aterrizar en El Libertador"]

    def weather(self, w):
        super().weather(w)
        w.hour = 15.0
        w.cloud_cover, w.cloud_base_ft = 0.5, 4500

    def waypoints(self, world):
        return [("el punto SUR", local(world, TORMENTA_SUR))]

    def wp_voice(self, k, name, leg):
        return f"Rumbo {leg.hdg_m:03d} hacia el punto SUR, rodeando la tormenta por el sur. Manténgase lejos de ella."

    def last_voice(self, dest, leg):
        return f"Punto SUR. Nuevo rumbo {leg.hdg_m:03d} hacia El Libertador, con la tormenta a su izquierda."

    def build(self, world):
        super().build(world)
        w = world.weather
        c = local(world, MARACAY_CENTRO)
        w.storm, w.storm_r = True, 2000.0
        w.storm_n, w.storm_e = float(c[0]), float(c[1])
        w.storm_vn = w.storm_ve = 0.0
        self.min_storm = 1e9
        self.inside_t = 0.0

    def update(self, dt, world, events):
        super().update(dt, world, events)
        at = world.atmo
        if not world.ac.on_ground:
            self.min_storm = min(self.min_storm, at.storm_dist)
        if at.storm_dist < 4000 and not world.ac.on_ground:
            self.coach("cerca_tormenta", True, "Demasiado cerca de la tormenta: aléjese, mínimo cinco kilómetros.", 10)
        if at.storm_core > 0.5 and not world.ac.on_ground:
            self.inside_t += dt
            if self.inside_t > 8 and not self.done:
                self.finish(False, "Entró en la tormenta: turbulencia severa y descendentes", world)

    def extra_items(self, world):
        km = self.min_storm / 1000.0
        p = 20 if km >= 5 else (12 if km >= 4 else (5 if km >= 3 else 0))
        return super().extra_items(world) + [("Separación de la tormenta (mín. 5 km)", p, 20, f"mínima {km:.1f} km")]


# ------------------------------------------------------------------ 8. niebla al amanecer
class NC_Niebla(_Clima, L_ILS):
    id = "nc_niebla"
    title = "Niebla al amanecer: ILS a la pista 29 de Base Sucre"
    standard = IR
    acs = "IR.VI.B"
    wind_rel = 180
    duration = "8 min"
    brief = ("Amanecer en Maracay con niebla sobre el lago: techo a 250 ft y visibilidad de 1200 m. Solo se puede llegar "
             "por instrumentos: intercepte el localizador del ILS de la pista 29, capture la senda y descienda con las dos "
             "agujas centradas. A la altura de decisión (200 ft sobre la pista) deben verse las luces de aproximación; si "
             "no las ve, motor y al aire de inmediato. Luces de aterrizaje encendidas: en la niebla reflejan, no las "
             "mire fijamente.")
    objectives = ["Localizador y senda dentro de 3/4 de escala", "Decisión a 200 ft", "Aterrizaje con niebla"]

    def weather(self, w):
        super().weather(w)
        w.hour = 6.25
        w.wind_kt, w.gust_kt, w.turbulence = 3, 0, 0.05
        w.cloud_cover, w.cloud_base_ft, w.cloud_top_ft = 0.99, 250, 1300
        w.visibility_m = 1200

    def build(self, world):
        world.ac.sys.lights.update(nav=True, beacon=True, landing=True)
        super().build(world)


# ------------------------------------------------------------------ 9. travesía nocturna sin cortes
class NC_RutaNocturna(_Clima, M_RutaCaracasMaracay):
    id = "nc_ruta_nocturna"
    category = CAT
    location = "SVFM"
    title = "Travesía nocturna Caracas → Maracay (sin cortes)"
    acs = "PA.X.A + PA.VI.A"
    duration = "40 min"
    brief = ("La travesía real de La Carlota a Base Sucre, de noche y sin cortes: el paisaje se va cargando mientras vuela. "
             "Sale con las últimas luces del atardecer hacia el oeste; después solo verá las luces de Los Teques, del valle "
             "de Aragua y de Maracay. Entre los pueblos no hay luces y los cerros no se ven: mantenga la altitud de crucero "
             "(7500 ft, más de 2000 ft sobre los Altos Mirandinos) y navegue por los instrumentos y la ruta del MFD. La "
             "Luna sale según la fecha real. Luces de navegación, anticolisión y aterrizaje encendidas desde el despegue.")
    objectives = ["Luces exteriores encendidas", "Altitud de crucero ±300 ft de noche", "Navegar por los puntos de notificación",
                  "Aterrizaje nocturno en Base Sucre"]

    def weather(self, w):
        super().weather(w)
        w.hour = 18.6
        w.cloud_cover, w.wind_kt = 0.15, 6

    def update(self, dt, world, events):
        super().update(dt, world, events)
        snap_lights(self, world, not world.ac.on_ground and world.ac.agl / FT > 50)

    def extra_items(self, world):
        return super().extra_items(world) + [lights_item(self)]


CLIMA_MISSIONS = [NC_Circuito, NC_AgujeroNegro, NC_Carlota, NC_Electrica, NC_Aguacero, NC_Tormenta, NC_Desvio, NC_Niebla,
                  NC_RutaNocturna]
