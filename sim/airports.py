"""Aeródromos, pistas y radioayudas del escenario de entrenamiento."""
import math

import numpy as np


class Runway:
    def __init__(self, idents, center, heading, length, width, ils=None):
        self.idents = idents              # ("36", "18")
        self.center = np.array(center, dtype=float)
        self.heading = heading            # rumbo del extremo primario (grados)
        self.length = length
        self.width = width
        self.ils = ils                    # (freq, ident) para el extremo primario
        self.elev = 0.0
        self.surface = "ASP"              # superficie (código de OurAirports en los aeropuertos reales)
        self.paved = True                 # asfalto/concreto; False: pasto, tierra, grava (se rueda como en césped)
        self.lighted = True               # tiene luces (sin luces: de noche no se ve ni se puede aterrizar)
        h = math.radians(heading)
        self.dir = np.array([math.cos(h), math.sin(h)])
        self.right = np.array([-self.dir[1], self.dir[0]])

    # extremo de aproximación del rumbo primario (umbral) y el opuesto
    @property
    def threshold(self):
        return self.center - self.dir * self.length / 2

    @property
    def far_end(self):
        return self.center + self.dir * self.length / 2

    def end(self, ident):
        """Devuelve (umbral_xy, rumbo, dir) para aterrizar/despegar por 'ident'."""
        if ident == self.idents[0]:
            return self.threshold, self.heading, self.dir
        return self.far_end, (self.heading + 180) % 360, -self.dir

    def local(self, x, y, ident=None):
        """Coordenadas (a lo largo desde el umbral, lateral a la derecha)."""
        thr, _hdg, d = self.end(ident or self.idents[0])
        rel = np.array([x, y]) - thr
        r = np.array([-d[1], d[0]])
        return float(rel @ d), float(rel @ r)

    def contains(self, x, y, margin=0.0):
        rx = x - self.center[0]
        ry = y - self.center[1]
        a = abs(rx * self.dir[0] + ry * self.dir[1])
        b = abs(rx * self.right[0] + ry * self.right[1])
        return a <= self.length / 2 + margin and b <= self.width / 2 + margin


class Airport:
    def __init__(self, ident, name, ref, elev, runways, apron=None, taxi=None):
        self.ident = ident
        self.name = name
        self.ref = np.array(ref, dtype=float)
        self.elev = elev
        self.runways = runways
        for r in runways:
            r.elev = elev
        # plataforma: (centro_xy, rumbo, largo, ancho)
        self.apron = apron
        self.taxi = taxi or []            # lista de (centro, rumbo, largo, ancho)
        self.paved_rects = ([apron] if apron else []) + self.taxi

    def site_rect(self):
        """Zona de la plataforma y los edificios detrás de ella en un aeropuerto real (centro, rumbo, largo, ancho),
        o None: ahí se aplana el terreno y se quitan los edificios y árboles de OpenStreetMap."""
        side = getattr(self, "site_side", 0)
        if not side or self.apron is None:
            return None
        c, hdg, ln, wd = self.apron
        hr = math.radians(hdg)
        out = np.array([-math.sin(hr), math.cos(hr)]) * side          # hacia afuera, lejos de la pista
        cc = np.asarray(c, float) + out * 40.0
        return (float(cc[0]), float(cc[1])), hdg, ln + 130.0, wd + 80.0

    def paved(self, x, y):
        for r in self.runways:
            if r.paved and r.contains(x, y):
                return True
        for c, h, l, w in self.paved_rects:
            hr = math.radians(h)
            dx, dy = math.cos(hr), math.sin(hr)
            rx, ry = x - c[0], y - c[1]
            if abs(rx * dx + ry * dy) <= l / 2 and abs(-rx * dy + ry * dx) <= w / 2:
                return True
        return False


class VOR:
    def __init__(self, ident, freq, pos, elev, name=""):
        self.ident = ident
        self.freq = freq
        self.pos = np.array(pos, dtype=float)
        self.elev = elev
        self.name = name
        self.range_m = 80000.0
        self.kind = "VOR"
        self.magvar = None             # declinación de su rosa (grados, + = este); None = la del lugar


class NDB:
    """Radiofaro no direccional (o localizador de aproximación). Frecuencia en kHz; se recibe con el ADF."""

    def __init__(self, ident, freq_khz, pos, elev, name="", range_nm=25.0):
        self.ident = ident
        self.freq = freq_khz
        self.pos = np.array(pos, dtype=float)
        self.elev = elev
        self.name = name
        self.range_m = range_nm * 1852.0
        self.kind = "NDB"


class ILS:
    def __init__(self, ident, freq, runway, end_ident, gs_angle=3.0):
        self.ident = ident
        self.freq = freq
        self.runway = runway
        self.end_ident = end_ident
        self.kind = "ILS"
        thr, hdg, d = runway.end(end_ident)
        self.course = hdg
        self.dir = d
        self.threshold = thr
        # localizador al final opuesto de la pista (+300 m)
        self.loc_pos = thr + d * (runway.length + 300)
        # antena de senda: 300 m pasado el umbral
        self.gs_pos = thr + d * 300
        self.gs_angle = gs_angle
        self.elev = runway.elev
        self.range_m = 35000.0
        self.pos = self.loc_pos


def build_airports():
    # Aeródromo principal "Base Escuela", pista 36/18
    rw_esc = Runway(("36", "18"), (0.0, 0.0), 0.0, 1600.0, 30.0)
    esc = Airport("ESC", "Base Escuela", (0.0, 0.0), 150.0, [rw_esc],
                  apron=((150.0, 160.0), 0.0, 260.0, 120.0),
                  taxi=[((-650.0, 85.0), 0.0, 22.0, 140.0),     # conexión umbral 36
                        ((150.0, 70.0), 0.0, 60.0, 100.0),      # conexión centro
                        ((650.0, 85.0), 0.0, 22.0, 140.0),      # conexión umbral 18
                        ((0.0, 100.0), 0.0, 1300.0, 18.0)])     # calle paralela
    # Aeródromo "Valle Norte", pista 09/27
    rw_vnt = Runway(("09", "27"), (17000.0, 4000.0), 90.0, 1200.0, 25.0)
    vnt = Airport("VNT", "Valle Norte", (17000.0, 4000.0), 265.0, [rw_vnt],
                  apron=((17120.0, 3900.0), 90.0, 200.0, 90.0),
                  taxi=[((17060.0, 3900.0), 0.0, 120.0, 18.0)])
    airports = [esc, vnt]

    navaids = [
        ILS("IESC", 110.30, rw_esc, "36"),
        ILS("ISUR", 108.90, rw_esc, "18"),
        ILS("IVNT", 109.90, rw_vnt, "27"),
        VOR("ESC", 113.70, (1500.0, -900.0), 150.0, "Escuela"),
        VOR("VNT", 115.20, (17600.0, 5200.0), 265.0, "Valle Norte"),
        # localizador de la 36 en la radiobaliza exterior (4 NM antes del umbral) y radiofaro de Valle Norte
        NDB("ES", 350.0, (-800.0 - 4 * 1852.0, 0.0), 150.0, "Escuela (localizador)", 25.0),
        NDB("VN", 280.0, (16200.0, 2600.0), 265.0, "Valle Norte", 50.0),
    ]
    return airports, navaids
