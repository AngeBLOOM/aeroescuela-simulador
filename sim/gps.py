"""GPS con plan de vuelo (como el del G1000 o un GNS 430): base de datos de puntos (aeródromos, VOR, NDB), plan de
vuelo con secuencia automática de tramos, «Directo a» (D→) y modo OBS.

Da lo mismo que un receptor NAV (valid, cdi, to_from, obs, station, dme_nm…) para que el HSI y el piloto automático
lo sigan igual que a un VOR cuando el selector CDI está en GPS. La desviación es lineal: la escala completa es de
2 NM en ruta y 1 NM en terminal (a menos de 30 NM del aeródromo de destino). Rumbos y cursos que se muestran,
magnéticos; la geometría, verdadera.

Con una aproximación RNAV cargada (sim/rnav.py), desde 2 NM antes del FAF la escala pasa a 0,3 NM (APR), el GPS da
una senda vertical de 3° como la del ILS (gs, gs_valid) y se comporta como un localizador para el piloto
automático (is_loc), que la puede volar en APR acoplado.
"""
import math
from types import SimpleNamespace

import numpy as np

from .mathx import FT, NM, clamp, wrap180, wrap360

SCALE_NM = {"ENR": 2.0, "TERM": 1.0, "APR": 0.3}


class Waypoint:
    def __init__(self, ident, pos, kind, name=""):
        self.ident = ident
        self.pos = np.array(pos[:2], dtype=float)
        self.kind = kind            # "APT", "VOR", "NDB" o "USR"
        self.name = name

    def __repr__(self):
        return f"{self.kind} {self.ident}"


class Gps:
    def __init__(self, world):
        self.world = world
        self.plan = []              # [Waypoint]
        self.active = 0             # índice del punto al que se va (el tramo es plan[active-1] → plan[active])
        self.origin = None          # inicio del tramo activo cuando no hay punto anterior (posición al activarlo)
        self.direct = None          # punto de «Directo a» fuera del plan
        self.obs_mode = False
        self.obs_course = 360.0     # curso magnético del modo OBS
        self._from_here = False     # el tramo activo empieza en la posición del avión, no en el punto anterior
        self.approach = None        # aproximación RNAV cargada (sim/rnav.py) o None
        self.reset_outputs()

    # ------------------------------------------------------------ base de datos
    def database(self):
        w = self.world
        pts = [Waypoint(a.ident, a.ref, "APT", a.name) for a in w.airports]
        pts += [Waypoint(n.ident, n.pos, n.kind, getattr(n, "name", "")) for n in w.navaids if n.kind in ("VOR", "NDB")]
        return pts

    def find(self, ident, kind=None):
        for p in self.database():
            if p.ident == ident and (kind is None or p.kind == kind):
                return p
        return None

    def nearest(self, n=12):
        """Los n puntos más cercanos al avión: [(Waypoint, distancia NM, rumbo magnético)]."""
        ac = self.world.ac
        out = []
        for p in self.database():
            dx, dy = p.pos[0] - ac.pos[0], p.pos[1] - ac.pos[1]
            out.append((p, math.hypot(dx, dy) / NM, self.world.mag(math.degrees(math.atan2(dy, dx)))))
        out.sort(key=lambda t: t[1])
        return out[:n]

    def search(self, text, n=12):
        """Primero los puntos cuyo identificador es exactamente 'text' (como en el G1000: «ES» es el NDB ES aunque el
        aeródromo ESC esté más cerca), después los que empiezan por él y detrás los que lo llevan en el nombre; cada
        grupo del más cercano al más lejano. Mismo formato que nearest(): [(Waypoint, distancia NM, rumbo magnético)]."""
        q = text.strip().upper()
        if not q:
            return self.nearest(n)
        allp = self.nearest(10 ** 6)
        exact = [r for r in allp if r[0].ident.upper() == q]
        prefix = [r for r in allp if r not in exact and r[0].ident.upper().startswith(q)]
        by_name = [r for r in allp if r not in exact and r not in prefix and q in (r[0].name or "").upper()]
        return (exact + prefix + by_name)[:n]

    # ------------------------------------------------------------ plan y órdenes
    def add(self, wp, index=None):
        if index is None:
            self.plan.append(wp)
        else:
            self.plan.insert(index, wp)
        if len(self.plan) == 1:
            self.activate(0)

    def remove(self, index):
        if 0 <= index < len(self.plan):
            del self.plan[index]
            if index < self.active:
                self.active -= 1
            self.active = clamp(self.active, 0, max(0, len(self.plan) - 1))
            if index == self.active:
                self.origin = self.world.ac.pos[:2].copy()

    def clear(self):
        self.plan = []
        self.active = 0
        self.direct = None
        self.obs_mode = False
        self.origin = None
        self._from_here = False
        self.approach = None

    def load_approach(self, apr, iaf=None, first="IAF"):
        """Carga una aproximación RNAV al final del plan (en lugar del aeródromo de destino, si es el último punto) y,
        si no había plan, la activa. iaf: "L", "R" o None (vectores). first: el punto hacia el que se activa ("IAF" o
        "IF": el primero; "FAF" o "MAP": ya alineado en el final, el siguiente por delante; ver rnav.entry)."""
        if self.plan and self.plan[-1].kind == "APT" and self.plan[-1].ident == apr.airport.ident:
            self.plan.pop()
        start = len(self.plan)
        legs = apr.legs(iaf)
        self.plan += legs
        self.approach = apr
        self.obs_mode = False
        if start == 0 or self.direct is not None:
            k = next((i for i, p in enumerate(legs) if p.role == first), 0)
            self.activate(start + k)
            self._from_here = True
        return start

    def _approach_final(self, tgt):
        """En el tramo final: hacia el FAF a menos de 2 NM de él, o hacia el umbral (MAP)."""
        role = getattr(tgt, "role", "")
        if self.approach is None or role not in ("FAF", "MAP"):
            return False
        return role == "MAP" or self.dis_nm < 2.0

    def activate(self, index):
        """Activa el tramo hacia plan[index] desde el punto anterior (o desde la posición actual si es el primero)."""
        self.direct = None
        self.active = int(clamp(index, 0, max(0, len(self.plan) - 1)))
        self.origin = self.world.ac.pos[:2].copy()
        self._from_here = False

    def direct_to(self, wp):
        """D→: curso directo desde la posición actual. Si el punto está en el plan, el plan sigue desde él."""
        self.obs_mode = False
        for i, p in enumerate(self.plan):
            if p.ident == wp.ident and p.kind == wp.kind:
                self.active = i
                self.direct = None
                self.origin = self.world.ac.pos[:2].copy()
                self._from_here = True
                return
        self.direct = wp
        self.origin = self.world.ac.pos[:2].copy()

    def set_obs(self, on, course=None):
        self.obs_mode = bool(on)
        if course is not None:
            self.obs_course = float(course) % 360 or 360

    # ------------------------------------------------------------ salidas
    def reset_outputs(self):
        self.valid = False
        self.cdi = 0.0
        self.to_from = None
        self.dtk = 0.0              # curso deseado (magnético)
        self.brg = 0.0              # rumbo al punto (magnético)
        self.dis_nm = None
        self.xtk_nm = 0.0           # desviación lateral (+ = a la derecha del curso)
        self.ete_s = None
        self.scale = "ENR"
        self.station = None
        self.dme_nm = None
        self.gs_valid = False
        self.gs = 0.0
        self.marker = None

    @property
    def obs(self):
        return self.dtk             # para el HSI y el piloto automático: el curso a seguir

    @property
    def is_loc(self):
        # en el tramo final de una RNAV el piloto automático la sigue como un localizador (curso del tramo, más fino)
        return self.scale == "APR"

    @property
    def target(self):
        if self.direct is not None:
            return self.direct
        if self.plan and 0 <= self.active < len(self.plan):
            return self.plan[self.active]
        return None

    @property
    def ident(self):
        t = self.target
        return t.ident if t is not None else "----"

    def leg_from(self):
        if self.direct is None and self.active > 0 and not getattr(self, "_from_here", False):
            return self.plan[self.active - 1].pos
        return self.origin if self.origin is not None else self.world.ac.pos[:2]

    def update(self, ac, powered=True):
        self.reset_outputs()
        tgt = self.target
        if not powered or tgt is None:
            return
        w = self.world
        p = ac.pos[:2]
        to = tgt.pos
        if self.obs_mode:
            crs = math.radians(w.true(self.obs_course))
            frm = to - np.array([math.cos(crs), math.sin(crs)]) * 10 * NM
        else:
            frm = np.array(self.leg_from(), dtype=float)
        d = to - frm
        L = float(np.hypot(d[0], d[1]))
        if L < 1.0:                                       # tramo de longitud cero: directo desde aquí
            frm = p.copy()
            d = to - frm
            L = max(float(np.hypot(d[0], d[1])), 1.0)
        u = d / L
        rel = p - frm
        xtk = (rel[0] * u[1] - rel[1] * u[0]) * -1.0       # + = a la derecha del curso
        remaining = float(np.dot(to - p, u))
        self.xtk_nm = xtk / NM
        dx, dy = to[0] - p[0], to[1] - p[1]
        self.dis_nm = math.hypot(dx, dy) / NM
        self.dme_nm = self.dis_nm
        dtk_true = math.degrees(math.atan2(u[1], u[0])) % 360
        self.dtk = w.mag(dtk_true)
        self.brg = w.mag(math.degrees(math.atan2(dy, dx)))
        self.to_from = "TO" if remaining >= 0 else "FROM"
        dest = self.plan[-1] if self.plan else tgt
        dest_pos, dest_apt = dest.pos, dest.kind == "APT"
        if self.approach is not None:                     # con aproximación cargada, el destino es su aeródromo
            dest_pos, dest_apt = self.approach.airport.ref, True
        near_dest = dest_apt and math.hypot(dest_pos[0] - p[0], dest_pos[1] - p[1]) < 30 * NM
        self.scale = "TERM" if near_dest else "ENR"
        if self._approach_final(tgt):
            self.scale = "APR"
            # senda vertical: 3° desde el punto donde toca el suelo (pasado el umbral, para cruzarlo a 50 ft)
            apr = self.approach
            back = -float(np.dot(p - apr.threshold, apr.dir)) + apr.tch_ft * FT / math.tan(math.radians(apr.gp_deg))
            if back > 50.0:
                dev = math.degrees(math.atan2(ac.alt_msl - apr.elev_ft * FT, back)) - apr.gp_deg
                self.gs = clamp(-dev / 0.7, -1.0, 1.0)
                self.gs_valid = True
        self.cdi = clamp(-self.xtk_nm / SCALE_NM[self.scale], -1.0, 1.0)
        self.ete_s = self.dis_nm * NM / ac.gs if ac.gs > 5 else None
        self.station = SimpleNamespace(ident=tgt.ident, kind="GPS", course=dtk_true, magvar=w.magvar, pos=to)
        self.valid = True
        # secuencia automática: al llegar (o pasar) al punto se activa el siguiente tramo del plan
        if not self.obs_mode and self.direct is None and self.active < len(self.plan) - 1:
            nxt = self.plan[self.active + 1].pos - to
            turn = abs(wrap180(math.degrees(math.atan2(nxt[1], nxt[0])) - dtk_true)) if np.any(nxt) else 0.0
            r_turn = ac.gs ** 2 / (9.81 * math.tan(math.radians(20)))     # radio de viraje a 20° de alabeo
            lead = min(r_turn * math.tan(math.radians(turn / 2)), 1.5 * NM) if turn < 170 else 0.0
            if remaining < max(lead, 0.15 * NM):
                self.active += 1
                self._from_here = False
