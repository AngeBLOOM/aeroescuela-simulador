"""Misiones en aeropuertos reales de Venezuela. Cada una carga sola su escenario (atributo location) y aprovecha la
geografía real del lugar: el mar y El Ávila en Maiquetía, el Lago de Valencia, el calor de Barquisimeto, el valle
andino de Mérida y el mar Caribe en Margarita."""
import math

import numpy as np

from .lessons import L_Cruzado, L_Despegue, L_Final, L_ILS
from .lessons_emerg import L_FueraCampo
from .mathx import FT

CAT = "11 · Misiones en Venezuela"


class V_Maiquetia(L_ILS):
    id = "ve_maiquetia"
    title = "Maiquetía: aproximación ILS entre el mar y El Ávila"
    category = CAT
    location = "SVMI"
    duration = "6 min"
    brief = ("Aeropuerto Internacional Simón Bolívar (SVMI), en la costa: el mar Caribe a un lado y El Ávila, con más de "
             "2000 m, justo detrás. Vuela en nubes hacia el localizador: siga el ILS (aguja del localizador y de la senda) "
             "hasta la altura de decisión, que verá la pista con el mar a la derecha. Si no ve la pista en los mínimos: "
             "motor y al aire de inmediato, NUNCA hacia el Ávila.")


class V_Valencia(L_Cruzado):
    id = "ve_valencia"
    title = "Valencia: aterrizaje con viento cruzado y racheado"
    category = CAT
    location = "SVVA"
    brief = ("Aeropuerto Arturo Michelena (SVVA), Valencia. Viento cruzado de 12 kt con ráfagas de 18 desde la izquierda, "
             "con el Lago de Valencia al este. En final corrija la deriva poniendo el morro hacia el viento; antes de tocar, "
             "alinee el morro con el pedal y baje el ala del lado del viento para tocar sin deriva. Sume la mitad del "
             "factor de ráfaga a la velocidad de aproximación.")


class V_Barquisimeto(L_Despegue):
    id = "ve_barquisimeto"
    title = "Barquisimeto: despegue con calor (altitud de densidad)"
    category = CAT
    location = "SVBM"
    brief = ("Aeropuerto Jacinto Lara (SVBM), Barquisimeto, a 2042 ft y con 35 °C: la altitud de densidad supera los "
             "5000 ft. El motor da menos potencia, la carrera de despegue es más larga y el ascenso más lento. Antes de "
             "despegar mire en la tableta (K) → PESO Y RENDIMIENTO la carrera calculada. Mezcla ajustada para máxima "
             "potencia, rote a Vr y ascienda a Vy sin forzar la nariz.")

    def weather(self, w):
        super().weather(w)
        w.temp_offset = 20.0               # unos 35 °C a la altura del campo
        w.wind_kt = 3


class V_Merida(L_Final):
    id = "ve_merida"
    title = "Mérida: aproximación en el valle de los Andes"
    category = CAT
    location = "SVMD"
    brief = ("Aeropuerto Alberto Carnevalli (SVMD), Mérida, a 5007 ft en un valle estrecho entre la Sierra Nevada y la "
             "Sierra de La Culata. La pista es corta y el aire es poco denso: la velocidad respecto al suelo será mayor de "
             "lo habitual aunque el anemómetro marque lo mismo. Mantenga 65 kt indicados, senda de 3° y toque en los "
             "primeros 300 m. Las montañas a ambos lados no dejan margen para virajes amplios.")

    def weather(self, w):
        super().weather(w)
        w.temp_offset = 8.0


class V_Margarita(L_FueraCampo):
    id = "ve_margarita"
    title = "Margarita: motor parado sobre el Caribe"
    category = CAT
    location = "SVMG"
    brief = ("Vuela sobre el mar al sur de la Isla de Margarita, a 2500 ft, regresando al Aeropuerto Santiago Mariño "
             "(SVMG). El motor se parará. Mejor planeo de inmediato y decida: si alcanza la costa o la pista, aterrice; si "
             "no, amerizaje controlado paralelo a las olas, alas niveladas, flaps completos y la menor velocidad posible. "
             "MAYDAY y transpondedor 7700.")

    def build(self, world):
        h = world.home.ref
        # 9 km al sur del aeropuerto, sobre el mar, rumbo norte hacia la isla
        world.ac.place_in_air(h[0] - 9000.0, h[1] + 1500.0, (world.home.elev / FT + 2500) * FT, 350.0, 100)
        super().build(world)


VENEZUELA_MISSIONS = [V_Maiquetia, V_Valencia, V_Barquisimeto, V_Merida, V_Margarita]
