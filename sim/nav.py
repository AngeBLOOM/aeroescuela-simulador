"""Receptores de navegación: VOR, ILS (localizador y senda), DME, radiobalizas y ADF (NDB)."""
import math

from .mathx import NM, FT, clamp, wrap180, wrap360


class AdfRadio:
    """Receptor ADF: sintoniza un NDB (190-1750 kHz) y la aguja marca hacia él, relativa al morro (0 = delante,
    en el sentido de las agujas del reloj). Sin señal, la aguja se queda en 90° como en el avión."""

    def __init__(self, navaids, freq=350.0):
        self.navaids = navaids
        self.freq = freq
        self.standby = 280.0
        self.station = None
        self.valid = False
        self.bearing_to = 0.0          # verdadera, hacia el NDB
        self.relative = 90.0           # marcación relativa (aguja)
        self.dist_nm = None

    def swap(self):
        self.freq, self.standby = self.standby, self.freq

    def tune(self, delta):
        """Sintoniza en kHz enteros dentro de 190-1750 (da la vuelta en los extremos)."""
        f = round(self.freq + delta)
        self.freq = float(190 if f > 1750 else (1750 if f < 190 else f))

    def update(self, ac, powered=True):
        self.station = None
        self.valid = False
        self.dist_nm = None
        if powered:
            x, y = ac.pos[0], ac.pos[1]
            best = None
            for nv in self.navaids:
                if nv.kind == "NDB" and abs(nv.freq - self.freq) < 0.5:
                    d = math.hypot(nv.pos[0] - x, nv.pos[1] - y)
                    if d < nv.range_m and (best is None or d < best[0]):
                        best = (d, nv)
            if best is not None:
                d, nv = best
                self.station = nv
                self.valid = True
                self.dist_nm = d / NM
                self.bearing_to = math.degrees(math.atan2(nv.pos[1] - y, nv.pos[0] - x)) % 360
        self.relative = wrap360(self.bearing_to - ac.heading) if self.valid else 90.0

    @property
    def ident(self):
        return self.station.ident if self.station else "--"


class NavRadio:
    def __init__(self, navaids, freq=110.30, obs=360.0):
        self.navaids = navaids
        self.freq = freq
        self.standby = 113.70
        self.obs = obs
        self.station = None
        self.valid = False
        self.cdi = 0.0             # -1..1 (aguja izquierda/derecha)
        self.gs = 0.0              # -1..1 (aguja arriba = subir)
        self.gs_valid = False
        self.to_from = None        # "TO", "FROM" o None
        self.dme_nm = None
        self.radial = 0.0
        self.bearing_to = 0.0
        self.marker = None
        self.loc_angle = 0.0
        self.gs_angle_dev = 0.0

    def swap(self):
        self.freq, self.standby = self.standby, self.freq

    def tune(self, delta):
        """Sintoniza en pasos de 0.05 MHz dentro de 108.00-117.95."""
        f = round((self.freq + delta) * 20) / 20
        if f > 117.95:
            f = 108.0
        if f < 108.0:
            f = 117.95
        self.freq = f

    def update(self, ac, powered=True):
        self.station = None
        self.valid = self.gs_valid = False
        self.to_from = None
        self.dme_nm = None
        self.marker = None
        if not powered:
            return
        x, y, alt = ac.pos[0], ac.pos[1], ac.alt_msl
        for nv in self.navaids:
            if nv.kind != "NDB" and abs(nv.freq - self.freq) < 0.01:
                dx, dy = x - nv.pos[0], y - nv.pos[1]
                d = math.hypot(dx, dy)
                if d < nv.range_m:
                    self.station = nv
                    break
        nv = self.station
        if nv is None:
            return
        dx, dy = x - nv.pos[0], y - nv.pos[1]
        dh = alt - nv.elev
        self.dme_nm = math.sqrt(dx * dx + dy * dy + dh * dh) / NM
        if nv.kind == "VOR":
            # radial magnético: la rosa del VOR está orientada a su norte magnético
            self.radial = (math.degrees(math.atan2(dy, dx)) - (getattr(nv, "magvar", None) or 0.0)) % 360
            self.bearing_to = (self.radial + 180) % 360
            if self.dme_nm < 0.2:
                return
            diff = wrap180(self.radial - self.obs)
            if abs(diff) <= 90:
                self.to_from = "FROM"
                dev = -diff
            else:
                self.to_from = "TO"
                dev = wrap180(diff + 180)
            self.cdi = clamp(dev / 10.0, -1.0, 1.0)
            self.valid = True
        else:
            d = nv.dir
            rx, ry = x - nv.loc_pos[0], y - nv.loc_pos[1]
            along = -(rx * d[0] + ry * d[1])          # distancia hacia atrás desde el localizador
            lat = rx * (-d[1]) + ry * d[0]            # a la derecha del eje de aterrizaje
            ang = math.degrees(math.atan2(lat, along))
            self.loc_angle = ang
            self.bearing_to = math.degrees(math.atan2(-ry, -rx)) % 360
            if along > 0 and abs(ang) < 35:
                self.valid = True
                self.cdi = clamp(-ang / 2.5, -1.0, 1.0)
                self.to_from = "TO"
            gx, gy = x - nv.gs_pos[0], y - nv.gs_pos[1]
            g_along = -(gx * d[0] + gy * d[1])
            if g_along > 50 and abs(ang) < 10 and g_along < 10 * NM:
                h = alt - nv.elev
                gang = math.degrees(math.atan2(h, g_along))
                dev = gang - nv.gs_angle
                self.gs_angle_dev = dev
                self.gs = clamp(-dev / 0.7, -1.0, 1.0)
                self.gs_valid = True
            # radiobalizas exterior (4 NM) / intermedia (0.5 NM) del umbral
            ta = -((x - nv.threshold[0]) * d[0] + (y - nv.threshold[1]) * d[1])
            if abs(lat) < 600:
                if abs(ta - 4.0 * NM) < 250 + alt * 0.0:
                    self.marker = "O"
                elif abs(ta - 0.5 * NM) < 120:
                    self.marker = "M"

    @property
    def ident(self):
        return self.station.ident if self.station else "----"

    @property
    def is_loc(self):
        return self.station is not None and self.station.kind == "ILS"


def glideslope_height_ft(ils, x, y):
    """Altura MSL (ft) de la senda en un punto (para guías visuales)."""
    d = ils.dir
    g_along = -((x - ils.gs_pos[0]) * d[0] + (y - ils.gs_pos[1]) * d[1])
    return (ils.elev + max(g_along, 0) * math.tan(math.radians(ils.gs_angle))) / FT
