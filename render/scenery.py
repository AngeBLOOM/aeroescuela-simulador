"""Escenario estático: malla de terreno, pistas, edificios, árboles, carreteras y luces."""
import math

import numpy as np

from . import buildings as bl
from . import geometry as geo
from . import textures as tx

HOUSE_KEYS = ["casa_a", "casa_b", "casa_c", "casa_d"]
BLOCK_KEYS = ["bloque_4", "bloque_10"]
# colores de las casas (pasteles de los pueblos venezolanos) y de los edificios
HOUSE_COLORS = [(0.98, 0.93, 0.78), (0.95, 0.86, 0.7), (0.76, 0.88, 0.96), (0.98, 0.82, 0.76), (0.84, 0.95, 0.8),
                (0.97, 0.97, 0.95), (1.0, 0.9, 0.6), (0.95, 0.8, 0.88), (0.9, 0.78, 0.62), (0.8, 0.92, 0.9)]
BLOCK_COLORS = [(0.95, 0.94, 0.9), (0.9, 0.88, 0.84), (0.86, 0.9, 0.95), (0.96, 0.9, 0.8), (0.82, 0.82, 0.82)]

TOWNS = [
    # (x, y, radio, casas, edificios)
    (-3600.0, -3200.0, 950.0, 260, 26),
    (15300.0, 6300.0, 650.0, 120, 8),
    (-9000.0, 2500.0, 450.0, 60, 0),
    (5200.0, -9000.0, 500.0, 70, 0),
]


def _dist_poly(p, pts):
    """Distancia de un punto (x, y) a una polilínea."""
    best = 1e18
    for a, b in zip(pts[:-1], pts[1:]):
        ab = b - a
        t = max(0.0, min(1.0, float((p - a) @ ab) / max(float(ab @ ab), 1e-9)))
        best = min(best, float(np.hypot(*(a + ab * t - p))))
    return best


class Scenery:
    def __init__(self, world, rng_seed=21):
        self.world = world
        # aeródromos dentro del paisaje (en un tramo de ruta, el de referencia puede quedar fuera y no se dibuja)
        self.aps = [a for a in world.airports if not getattr(a, "offscene", False)]
        self.terrain = world.terrain
        self.rng = np.random.default_rng(rng_seed)
        self.terrain_vertices, self.terrain_indices = self._terrain_mesh()
        self._bparts = []                                  # edificios y casas con fachada (render/buildings.py)
        self.objects = self._objects()
        self.buildings_mesh = np.vstack(self._bparts).astype(np.float32) if self._bparts else None
        self.runways = self._runways()
        self.lights_static, self.light_groups, self.papis, self.rabbits = self._lights()
        self.windsocks = self._windsocks()
        if bl.load_model("valla") is not None:
            self._fences()
        self._navaid_sites()
        self.apron_lights = self._apron_lights()
        if bl.load_model("manga") is not None:          # mástil modelado en Blender (la manga la mueve el renderizador)
            for (x, y, z) in self.windsocks:
                self.house_inst.append(("manga", x, y, z, 0.0, 1.0, 1.0, 1.0, 1.0))
        self.town_lights = self._town_lights()

    # ---------------------------------------------------------------- terreno
    def _terrain_mesh(self):
        T = self.terrain
        n = T.n
        X, Y = T.grid_xy()
        H = T.h
        gx, gy = np.gradient(H, T.cell)
        N = np.stack([-gx, -gy, -np.ones_like(H)], axis=-1)
        N /= np.linalg.norm(N, axis=-1, keepdims=True)
        P = np.stack([X, Y, -H], axis=-1)
        C = T.colors
        verts = np.concatenate([P, N, C], axis=-1).reshape(-1, 9).astype(np.float32)
        i = np.arange(n - 1)
        I, J = np.meshgrid(i, i, indexing="ij")
        v00 = (I * n + J).ravel()
        v10 = ((I + 1) * n + J).ravel()
        v01 = (I * n + J + 1).ravel()
        v11 = ((I + 1) * n + J + 1).ravel()
        idx = np.stack([v00, v10, v11, v00, v11, v01], axis=-1).ravel().astype(np.uint32)
        return verts, idx

    def ground(self, x, y):
        return self.terrain.height(x, y)

    # ---------------------------------------------------------------- pistas
    def _runways(self):
        """Lista de (textura_surface, vertices pos+uv float32, tipo: "pista", "rodaje" o "plataforma")."""
        out = []
        for ap in self.aps:
            for rw in ap.runways:
                if not getattr(rw, "paved", True):
                    continue                  # pasto o tierra: se ve la pista de la foto y sus balizas de borde
                W = rw.width
                L = rw.length
                z = -(ap.elev + 0.09)
                thr = rw.threshold
                d = rw.dir
                r = rw.right
                seg = 420.0

                def P(s, lat):
                    p = thr + d * s + r * lat
                    return (p[0], p[1], z)

                def quad(s0, s1, uvf):
                    vs = []
                    for (s, lat) in ((s0, -W / 2), (s1, -W / 2), (s1, W / 2), (s0, -W / 2), (s1, W / 2), (s0, W / 2)):
                        u, v = uvf(s, lat)
                        vs.append((*P(s, lat), u, v))
                    return vs
                end_a = tx.runway_end_texture(rw.idents[0], W)
                end_b = tx.runway_end_texture(rw.idents[1], W)
                mid = tx.runway_mid_texture(W)
                va = quad(0.0, seg, lambda s, lat: ((lat + W / 2) / W, s / seg))
                vb = quad(L - seg, L, lambda s, lat: ((-lat + W / 2) / W, (L - s) / seg))
                vm = []
                s = seg
                while s < L - seg - 1e-3:
                    s1 = min(s + 50.0 * 8, L - seg)
                    vm += quad(s, s1, lambda ss, lat, s0=s: ((lat + W / 2) / W, (ss - seg) / 50.0))
                    s = s1
                out.append((end_a, np.array(va, np.float32), "pista"))
                out.append((end_b, np.array(vb, np.float32), "pista"))
                out.append((mid, np.array(vm, np.float32), "pista"))
        if self._paved:
            out.append((tx.taxiway_texture(), np.array(self._paved, np.float32), "rodaje"))
        if self._apron:
            out.append((tx.apron_slabs_texture(), np.array(self._apron, np.float32), "plataforma"))
        return out

    # ---------------------------------------------------------------- objetos
    def _objects(self):
        self.parked, self.parked_code = [], np.zeros((0, 9), np.float32)
        self.fuel = []                                    # estación de combustible (modelo de Blender)
        self.house_inst = []                              # casas y edificios de Blender: (clave, x, y, z, rumbo, escala, r, g, b)
        self.hangars, self.towers = [], []                # los dibuja el renderizador con detalle (render/buildings.py)
        self.taxi_signs = []                              # carteles de posición de espera (x, y, z, rumbo, texto, calle)
        self.guide_signs = []                             # carteles amarillos de guía (x, y, z, rumbo, texto, flecha)
        self.dist_signs = self._distance_signs()          # carteles de distancia restante (x, y, z, rumbo, cara, dorso)
        self._paved = []                                  # calles de rodaje de asfalto (pos + uv)
        self._apron = []                                  # plataformas de losas de concreto (pos + uv)
        self.trees = None                                 # árboles: instancias con dos niveles de detalle
        mb = geo.MeshBuilder()
        rng = self.rng
        world = self.world
        T = self.terrain
        # pistas de pasto o tierra: balizas blancas de borde cada 60 m (no hay pintura ni asfalto)
        for ap in self.aps:
            for rw in ap.runways:
                if getattr(rw, "paved", True):
                    continue
                for s_ in np.arange(0.0, rw.length + 1.0, 60.0):
                    for sg in (-1, 1):
                        p = rw.threshold + rw.dir * s_ + rw.right * sg * (rw.width / 2 + 1.0)
                        g = T.height(p[0], p[1])
                        mb.box((p[0], p[1], -(g + 0.25)), (0.4, 1.4, 0.5), (0.95, 0.95, 0.93),
                               yaw=math.radians(rw.heading))
        # plataformas y calles de rodaje
        for ap in self.aps:
            z = -(ap.elev + 0.05)
            for rect in ap.paved_rects:
                c, hdg, ln, wd = rect
                h = math.radians(hdg)
                d = np.array([math.cos(h), math.sin(h)])
                rt = np.array([-d[1], d[0]])
                c = np.array(c)
                corners = [c - d * ln / 2 - rt * wd / 2, c + d * ln / 2 - rt * wd / 2,
                           c + d * ln / 2 + rt * wd / 2, c - d * ln / 2 + rt * wd / 2]
                if rect is ap.apron:
                    # plataforma: losas de concreto de 5 m alineadas con ella (la textura trae 4 x 4 losas); un
                    # poco más alta que las calles para que el concreto tape el empalme
                    uv = [(float((p - c) @ d) / 20.0, float((p - c) @ rt) / 20.0) for p in corners]
                    for i in (0, 1, 2, 0, 2, 3):
                        self._apron.append((corners[i][0], corners[i][1], z - 0.008, *uv[i]))
                else:
                    # calle de rodaje: asfalto con la textura fotográfica (la pone el renderizador)
                    uv = [(float(p[0]) / 8.0, float(p[1]) / 8.0) for p in corners]
                    for i in (0, 1, 2, 0, 2, 3):
                        self._paved.append((corners[i][0], corners[i][1], z, *uv[i]))
                # línea central amarilla a lo largo del lado mayor
                if ln >= wd:
                    a_, b_ = c - d * ln / 2, c + d * ln / 2
                    w_ = rt * 0.15
                else:
                    a_, b_ = c - rt * wd / 2, c + rt * wd / 2
                    w_ = d * 0.15
                if min(ln, wd) < 40:
                    zz = z - 0.015
                    mb.quad((*(a_ - w_), zz), (*(b_ - w_), zz), (*(b_ + w_), zz), (*(a_ + w_), zz), (0.85, 0.7, 0.15))
        # antenas de radio en los cerros: obstáculos pintados de rojo y blanco, con luces de noche
        self.masts = self._masts(mb)
        if world.is_school:                               # tendido de alta tensión que cruza el valle
            self._power_line(mb, (4200.0, -9000.0), (5200.0, 9000.0))
        if not world.is_school:
            loc = world.location
            try:
                if getattr(world, "buildings_3d", False):
                    self._real_buildings(mb, loc)
                else:
                    # foto satelital pura: los edificios ya están en la imagen; de noche, sus luces
                    self._real_lights = self._building_lights(loc)
                self._real_trees(mb, loc)
            except Exception as ex:
                print("No se pudieron construir edificios/árboles:", ex)
            return mb.array()
        esc, vnt = self.aps[0], self.aps[1]
        # edificios del aeródromo principal
        ge = -esc.elev
        for i, hx in enumerate((50.0, 130.0, 210.0)):
            self._hangar(mb, (hx, 262.0, ge), 45.0, 34.0, 11.0, yaw=0.0, col=[(0.94, 0.94, 0.92), (0.92, 0.93, 0.95), (0.95, 0.93, 0.88)][i],
                         sign=("AEROESCUELA", "HANGAR 2", "HANGAR 3")[i])
        self.towers.append((-60.0, 215.0, ge, 16.0))                                # torre
        self.fuel = [(262.0, 238.0, ge, 0.0)]                                        # estación de combustible
        if bl.load_model("terminal") is not None:       # edificio de la escuela (Blender), de frente a la plataforma
            self.house_inst.append(("terminal", 310.0, 160.0, ge, -math.pi / 2, 1.0, 1.0, 1.0, 1.0))
        else:
            mb.box((-60.0, 215.0, ge - 20.3), (11, 11, 0.6), (0.4, 0.4, 0.42))
            mb.box((310.0, 160.0, ge - 3.5), (34, 22, 7), (0.88, 0.86, 0.8))     # terminal
            mb.box((310.0, 160.0, ge - 7.2), (36, 24, 0.5), (0.5, 0.5, 0.52))
            mb.box((290.0, 98.0, ge - 1.5), (6, 3, 3), (0.85, 0.2, 0.15))         # surtidor
        # aeródromo norte
        gn = -vnt.elev
        self._hangar(mb, (17160.0, 3800.0, gn), 35.0, 28.0, 9.0, yaw=0.0, col=(0.93, 0.93, 0.91), sign="VALLE NORTE")
        self._hangar(mb, (17160.0, 3740.0, gn), 30.0, 24.0, 8.0, yaw=0.0, col=(0.95, 0.93, 0.87))
        self.towers.append((17080.0, 3720.0, gn, 12.0))
        # señalización de rodaje: líneas y carteles de espera antes de cada pista
        self._hold_positions(mb)
        # aeródromo no controlado (Valle Norte): círculo segmentado alrededor de la manga con indicadores de circuito
        for ap in self.aps[1:]:
            self._segmented_circle(mb, ap)
        # aviones estacionados: el renderizador los dibuja con los modelos 3D reales (flota variada de la escuela);
        # aquí queda la versión dibujada por código por si falta algún modelo
        t = world.ac.t
        parts, _ = geo.aircraft_parts(t, accent=(0.7, 0.12, 0.1))
        static = np.vstack([parts[k][0] for k in ("body", "gear", "elevator", "rudder", "ail_l", "ail_r",
                                                  "flap_l", "flap_r", "prop")])
        gz = max(g.pos[2] for g in t.gears)
        cols = [(1, 1, 1), (0.95, 0.95, 1.0), (1.0, 0.95, 0.85)]
        pos = []
        self.parked = []
        for k, (px, py) in enumerate(((80.0, 205.0), (115.0, 205.0), (150.0, 205.0), (17110.0, 3860.0))):
            gh = T.height(px, py)
            pos.append((px, py, -(gh + gz - 0.05)))
            self.parked.append((px, py, gh, math.radians(270.0)))
        self.parked_code = geo.instances(static, np.array(pos), np.ones(len(pos)), np.full(len(pos), math.radians(270.0)),
                                         np.array([cols[i % 3] for i in range(len(pos))]))
        # pueblos: casas y edificios modelados en Blender (instancias con su color) o, si faltan, con fachada
        models = all(bl.load_model(k) is not None for k in HOUSE_KEYS + BLOCK_KEYS)
        for (tx_, ty_, rad, nh, nb) in TOWNS:
            pts = self._town_points(tx_, ty_, rad, nh)
            if len(pts):
                h = np.array([T.height(p[0], p[1]) for p in pts])
                P = np.column_stack([pts[:, 0], pts[:, 1], -h])
                sc = np.column_stack([rng.uniform(8, 16, len(pts)), rng.uniform(7, 12, len(pts)), rng.uniform(5, 8, len(pts))])
                yaw = np.round(rng.uniform(0, 4, len(pts))) * math.pi / 2 + 0.2
                cm = rng.uniform(0.85, 1.1, (len(pts), 3))
                if models:
                    kind = rng.choice(len(HOUSE_KEYS), len(pts), p=[0.3, 0.25, 0.25, 0.2])
                    tint = np.array(HOUSE_COLORS)[rng.integers(0, len(HOUSE_COLORS), len(pts))]
                    for i in range(len(pts)):
                        self.house_inst.append((HOUSE_KEYS[kind[i]], *P[i], yaw[i] + rng.uniform(-0.15, 0.15),
                                                rng.uniform(0.9, 1.1), *tint[i]))
                else:
                    self._houses_facade(P, sc, yaw, cm)
                self._houses = getattr(self, "_houses", []) + [P]
            if nb:
                pts = self._town_points(tx_, ty_, rad * 0.35, nb)
                h = np.array([T.height(p[0], p[1]) for p in pts])
                P = np.column_stack([pts[:, 0], pts[:, 1], -h])
                sc = np.column_stack([rng.uniform(18, 30, nb), rng.uniform(18, 30, nb), rng.uniform(12, 38, nb)])
                yaw = np.full(nb, 0.2)
                cm = rng.uniform(0.8, 1.1, (nb, 3))
                if models:
                    for i in range(nb):
                        key = BLOCK_KEYS[1] if sc[i, 2] > 34 else BLOCK_KEYS[0]     # pocas torres altas
                        tint = BLOCK_COLORS[rng.integers(0, len(BLOCK_COLORS))]
                        self.house_inst.append((key, *P[i], 0.2 + rng.integers(0, 4) * math.pi / 2, 1.0, *tint))
                else:
                    style = np.where(sc[:, 2] > 28, bl.TOWER, bl.BLOCK) + rng.uniform(0.1, 0.9, nb)
                    self._bparts.append(bl.box_buildings(P, sc, yaw, np.array([0.78, 0.78, 0.76]) * cm,
                                                         np.array([0.45, 0.45, 0.47]) * cm, style))
        # granjas dispersas
        fx = rng.uniform(-18000, 18000, 600)
        fy = rng.uniform(-18000, 12000, 600)
        keep = []
        for x, y in zip(fx, fy):
            h = T.height(x, y)
            if 20 < h < 600 and min((math.hypot(x - a.ref[0], y - a.ref[1]) for a in self.aps), default=1e9) > 1500:
                keep.append((x, y, -h))
        if keep:
            P = np.array(keep)
            m = len(P)
            sc = np.column_stack([rng.uniform(9, 20, m), rng.uniform(7, 12, m), rng.uniform(5, 9, m)])
            if models:                                   # casas de campo: de una planta, con su color
                kind = rng.choice([0, 1, 3], m, p=[0.4, 0.35, 0.25])
                tint = np.array(HOUSE_COLORS)[rng.integers(0, len(HOUSE_COLORS), m)]
                yaw = rng.uniform(0, math.pi * 2, m)
                for i in range(m):
                    self.house_inst.append((HOUSE_KEYS[kind[i]], *P[i], yaw[i], rng.uniform(0.95, 1.15), *tint[i]))
            else:
                self._houses_facade(P, sc, rng.uniform(0, math.pi, m), rng.uniform(0.85, 1.1, (m, 3)))
        # árboles en bosques (cerca de los aeródromos y a lo largo del valle)
        self._trees()
        # carreteras
        roads = [
            [(-3600, -3200), (-2600, -1500), (-900, -200), (120, 330)],
            [(120, 330), (2600, 1800), (6500, 2600), (10500, 4200), (13800, 5600), (15300, 6300)],
            [(15300, 6300), (16600, 4800), (17150, 3950)],
            [(-3600, -3200), (-6500, -900), (-9000, 2500)],
            [(-3600, -3200), (-1000, -6000), (5200, -9000)],
        ]
        for rd in roads:
            self._road(mb, rd)
        self.road_lines = [np.array(rd, float) for rd in roads]     # el renderizador mueve autos de noche
        return mb.array()

    # ---------------------------------------------------------------- mundo real
    def _sat_color(self, loc, n, e):
        """Color de la foto satelital en un punto (para que los tejados casen con la imagen)."""
        for img, rect in reversed(loc["sat"]):
            n0, e0, sn, se = rect
            u = (e - e0) / se
            v = (n - n0) / sn
            if 0 <= u < 1 and 0 <= v < 1:
                h, w = img.shape[:2]
                return img[int(v * h), int(u * w)].astype(np.float32) / 255.0
        return np.array([0.5, 0.5, 0.5], np.float32)

    def _building_lights(self, loc):
        """Luces de ventanas y farolas en los edificios reales (OpenStreetMap), sin dibujar los edificios."""
        T = self.terrain
        runways = [rw for ap in self.aps for rw in ap.runways]
        lights = []
        for poly, major in loc.get("buildings", [])[:60000]:
            poly = np.asarray(poly, np.float64)
            if len(poly) < 3:
                continue
            cn, ce = float(poly[:, 0].mean()), float(poly[:, 1].mean())
            hsh = (int(cn * 7.13) * 73856093 ^ int(ce * 3.71) * 19349663) & 0xFFFF
            if hsh / 65535.0 < (0.25 if major else 0.5):
                continue
            if any(abs(cn - rw.center[0]) < rw.length and abs(ce - rw.center[1]) < rw.length and rw.contains(cn, ce, 60.0)
                   for rw in runways):
                continue
            lights.append((cn, ce, -(T.height(cn, ce) + 4.0)))
            if len(lights) >= 30000:
                break
        return lights

    def _real_buildings(self, mb, loc):
        T = self.terrain
        runways = [rw for ap in self.aps for rw in ap.runways]
        A, B, G, HT, STY, WC = [], [], [], [], [], []   # paredes (por arista)
        RC, RA, RB, RZ, RCOL = [], [], [], [], []      # tejados (abanicos)
        lights = []
        count = 0
        for poly, major in loc.get("buildings", [])[:40000]:
            poly = np.asarray(poly, np.float64)
            if len(poly) > 3 and abs(poly[0, 0] - poly[-1, 0]) < 1e-6 and abs(poly[0, 1] - poly[-1, 1]) < 1e-6:
                poly = poly[:-1]
            k = len(poly)
            if k < 3:
                continue
            x, y = poly[:, 0], poly[:, 1]
            area = 0.5 * abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))
            if area < 12 or area > 400000:
                continue
            cn, ce = float(x.mean()), float(y.mean())
            near_rw = False
            for rw in runways:
                if abs(cn - rw.center[0]) < rw.length and abs(ce - rw.center[1]) < rw.length and rw.contains(cn, ce, 40.0):
                    near_rw = True
                    break
            if near_rw:
                continue
            hsh = (int(cn * 7.13) * 73856093 ^ int(ce * 3.71) * 19349663) & 0xFFFF
            r01 = hsh / 65535.0
            if major:
                ht = 14 + r01 * 12
            elif area > 5000:
                ht = 9 + r01 * 7
            elif area > 700:
                ht = 7 + r01 * 9
            else:
                ht = 4.5 + r01 * 4.5
            g = T.height(cn, ce)
            roof = self._sat_color(loc, cn, ce) * 0.95
            wall = np.clip(roof * 0.5 + np.array([0.48, 0.46, 0.43]) * (0.75 + 0.3 * r01), 0, 1)
            b = np.roll(poly, -1, axis=0)
            A.append(poly)
            B.append(b)
            G.append(np.full(k, g))
            HT.append(np.full(k, ht))
            kind = (bl.TOWER if r01 > 0.5 else bl.BLOCK) if major else (bl.BLOCK if (area > 700 or ht > 9) else bl.HOUSE)
            STY.append(np.full(k, kind + 0.1 + 0.8 * ((hsh >> 3) % 97) / 97.0))
            WC.append(np.repeat(wall[None], k, axis=0))
            RC.append(np.repeat(np.array([[cn, ce]]), k, axis=0))
            RA.append(poly)
            RB.append(b)
            RZ.append(np.full(k, -(g + ht)))
            RCOL.append(np.repeat(roof[None], k, axis=0))
            count += 1
            if r01 > 0.55:
                lights.append((cn, ce, -(g + ht) - 0.5))
        self._real_lights = lights
        if not count:
            return
        # paredes con fachada (ventanas por piso, vidrieras abajo) y techos planos
        self._bparts.append(bl.facade_walls(np.vstack(A), np.vstack(B), np.concatenate(G), np.full(sum(map(len, A)), -1.0),
                                            np.concatenate(HT), np.vstack(WC), np.concatenate(STY)))
        self._bparts.append(bl.fan_roofs(np.vstack(RC), np.vstack(RA), np.vstack(RB), np.concatenate(RZ), np.vstack(RCOL)))
        print(f"  edificios 3D: {count}")

    def _real_trees(self, mb, loc):
        T = self.terrain
        rng = self.rng
        pts = []
        for poly, kind in loc.get("forests", []):
            poly = np.asarray(poly, np.float64)
            if len(poly) < 3:
                continue
            n0, e0 = poly.min(axis=0)
            n1, e1 = poly.max(axis=0)
            area = (n1 - n0) * (e1 - e0)
            if area < 400:
                continue
            spacing = 16.0 if kind == "bosque" else 26.0
            m = int(min(area / spacing ** 2, 4000))
            if m < 1:
                continue
            cand = np.column_stack([rng.uniform(n0, n1, m), rng.uniform(e0, e1, m)])
            # punto dentro del polígono (regla par-impar, vectorizada)
            inside = np.zeros(m, bool)
            px, py = cand[:, 0], cand[:, 1]
            xs, ys = poly[:, 0], poly[:, 1]
            xj, yj = np.roll(xs, 1), np.roll(ys, 1)
            for xi_, yi_, xj_, yj_ in zip(xs, ys, xj, yj):
                cond = ((yi_ > py) != (yj_ > py)) & (px < (xj_ - xi_) * (py - yi_) / ((yj_ - yi_) + 1e-12) + xi_)
                inside ^= cond
            pts.append(cand[inside])
            if sum(len(p) for p in pts) > 22000:
                break
        if not pts:
            return
        P = np.vstack(pts)[:22000]
        keep = np.ones(len(P), bool)
        for ap in self.aps:
            for rw in ap.runways:
                dx, dy = P[:, 0] - rw.center[0], P[:, 1] - rw.center[1]
                al = np.abs(dx * rw.dir[0] + dy * rw.dir[1])
                la = np.abs(dx * rw.right[0] + dy * rw.right[1])
                keep &= ~((al < rw.length / 2 + 300) & (la < rw.width / 2 + 150))
        P = P[keep]
        h = np.array([T.height(a, b) for a, b in P])
        X = np.column_stack([P[:, 0], P[:, 1], -h + 0.3])
        m = len(X)
        sc = rng.uniform(8, 17, m)
        cm = rng.uniform(0.8, 1.15, (m, 3)) * np.array([1.0, 1.0, 0.9])
        half = m // 2
        kind = np.zeros(m, np.int32)
        kind[:half] = 1
        sc[half:] *= 0.9
        self._add_trees(X, sc, rng.uniform(0, 6.28, m), cm, kind)
        print(f"  árboles: {m}")

    # ---------------------------------------------------------------- señalización de rodaje (OACI / FAA)
    def _ils_runway(self, rw):
        return any(nv.kind == "ILS" and nv.runway is rw for nv in self.world.navaids)

    def _hold_points(self, ap):
        """Puntos de espera de cada calle de rodaje que llega a una pista: (punto, dirección que se aleja de la pista,
        ancho de la calle, pista, nombre de la calle). Distancia al eje según la OACI: 60 m si la pista tiene
        aproximación de precisión (ILS), 30 m si es visual (aeronaves de clave 1)."""
        out = []
        names = iter("ABCDEFGH")
        for (c, h, ln, wd) in ap.taxi:
            c = np.asarray(c, float)
            hr = math.radians(h)
            d = np.array([math.cos(hr), math.sin(hr)])
            axis, L, W = (d, ln, wd) if ln >= wd else (np.array([-d[1], d[0]]), wd, ln)
            for rw in ap.runways:
                if abs(float(axis @ rw.dir)) > 0.5:          # calle paralela a la pista: no llega a ella
                    continue
                ends = [c + axis * L / 2, c - axis * L / 2]
                lat = [abs(float((e - rw.center) @ rw.right)) for e in ends]
                k = int(np.argmin(lat))
                if lat[k] > rw.width / 2 + 8.0 or abs(float((ends[k] - rw.center) @ rw.dir)) > rw.length / 2:
                    continue
                away = (ends[1 - k] - ends[k]) / L
                if float(away @ rw.right) * float((c - rw.center) @ rw.right) < 0:
                    away = -away
                D = 60.0 if self._ils_runway(rw) else 30.0
                far = abs(float((ends[1 - k] - rw.center) @ rw.right))
                D = min(D, far - 4.0)
                # punto sobre el eje de la calle a D metros del eje de la pista
                s0 = float((ends[k] - rw.center) @ rw.right)
                sgn = 1.0 if float(away @ rw.right) > 0 else -1.0
                t = (sgn * D - s0) / float(away @ rw.right)
                out.append((ends[k] + away * t, away, W, rw, next(names), ends[1 - k]))
        return out

    def _distance_signs(self):
        """Carteles de distancia restante (FAA AC 150/5340-18) en pistas pavimentadas, iluminadas y de 1500 m o más:
        cada 1000 ft a la izquierda de quien despega desde el primer extremo, 18 m afuera del borde. El sobrante de
        largo que no llega a 1000 ft se reparte entre ambos extremos, así las dos caras muestran miles exactos: la
        cara muestra lo que queda en un sentido y el dorso lo que queda en el otro."""
        out = []
        for ap in self.aps:
            for rw in ap.runways:
                if not (getattr(rw, "paved", True) and getattr(rw, "lighted", True)) or rw.length < 1500.0:
                    continue
                L_ft = rw.length / 0.3048
                n = int(L_ft // 1000)
                extra = (L_ft - n * 1000) / 2.0
                left = -rw.right                          # izquierda de quien corre en el sentido rw.dir
                face = math.atan2(-rw.dir[1], -rw.dir[0])  # la cara mira hacia el primer umbral
                for j in range(1, n):
                    s = (extra + j * 1000) * 0.3048
                    p = rw.threshold + rw.dir * s + left * (rw.width / 2 + 18.0)
                    g = max(self.terrain.height(p[0], p[1]), ap.elev)
                    out.append((float(p[0]), float(p[1]), -g, face, str(n - j), str(j)))
        return out

    def _guide_signs(self, ap, P, away, W, rw, name, far):
        """Carteles amarillos de guía (letra negra): antes de cada salida de pista, en cada sentido de aterrizaje, la
        letra de la calle con la flecha hacia el lado de la salida (70 m antes, del mismo lado); y al entrar a la calle
        desde la plataforma, el destino: los números de pista con la flecha hacia adelante, a la izquierda."""
        s = float((P - rw.center) @ rw.dir)
        J = rw.center + rw.dir * s                        # cruce con el eje de la pista
        side = rw.right if float(away @ rw.right) > 0 else -rw.right
        for dl in (rw.dir, -rw.dir):
            p = J - dl * 70.0 + side * (rw.width / 2 + 12.0)
            if abs(float((p - rw.center) @ rw.dir)) > rw.length / 2 - 30.0:
                continue                                  # antes del umbral no hace falta
            right = np.array([-dl[1], dl[0]])
            arrow = 90.0 if float(away @ right) > 0 else -90.0
            g = max(self.terrain.height(p[0], p[1]), ap.elev)
            self.guide_signs.append((float(p[0]), float(p[1]), -g, math.atan2(-dl[1], -dl[0]), name, arrow))
        # desde la plataforma: el piloto entra a la calle mirando hacia la pista (-away)
        h = -away
        left = np.array([h[1], -h[0]])
        p = np.asarray(far, float) + h * 10.0 + left * (W / 2 + 3.0)
        g = max(self.terrain.height(p[0], p[1]), ap.elev)
        self.guide_signs.append((float(p[0]), float(p[1]), -g, math.atan2(away[1], away[0]),
                                 f"{rw.idents[0]}-{rw.idents[1]}", 0.0))

    def _hold_positions(self, mb):
        """Líneas de espera (dos continuas del lado de la calle, dos discontinuas del lado de la pista, amarillas de
        15 cm) y el cartel rojo de posición de espera con los números de pista a la izquierda del piloto, junto al
        cartel negro con el nombre de la calle."""
        yellow = (0.86, 0.68, 0.12)
        for ap in self.aps:
            z = -(ap.elev + 0.075)
            for (P, away, W, rw, name, far) in self._hold_points(ap):
                across = np.array([-away[1], away[0]])
                half = W / 2 - 0.3
                # 30 cm por línea y 30 cm de separación: desde la altura del ojo del piloto se ven como en la realidad
                for off, solid in ((-0.9, False), (-0.3, False), (0.3, True), (0.9, True)):
                    base = P + away * off
                    if solid:
                        segs = [(-half, half)]
                    else:
                        segs = [(u, min(u + 0.9, half)) for u in np.arange(-half, half, 1.8)]
                    for u0, u1 in segs:
                        a0, a1 = base + across * u0, base + across * u1
                        w = away * 0.15
                        mb.quad((*(a0 - w), z), (*(a1 - w), z), (*(a1 + w), z), (*(a0 + w), z), yellow)
                # el piloto rueda hacia la pista (mirando -away): a su izquierda está across (giro antihorario)
                f = -away
                left = np.array([f[1], -f[0]])
                left_ident = rw.idents[1] if float(rw.dir @ left) > 0 else rw.idents[0]
                right_ident = rw.idents[0] if left_ident == rw.idents[1] else rw.idents[1]
                sp = P + away * 1.0 + left * (W / 2 + 4.0)
                gh = max(self.terrain.height(sp[0], sp[1]), ap.elev)
                self.taxi_signs.append((float(sp[0]), float(sp[1]), -gh, math.atan2(away[1], away[0]),
                                        f"{left_ident}-{right_ident}", name))
                self._guide_signs(ap, P, away, W, rw, name, far)

    def _segmented_circle(self, mb, ap):
        """Círculo segmentado (FAA AC 150/5340-5) alrededor de la manga de viento y, por cada sentido de aterrizaje,
        una «L»: el brazo largo paralelo a la pista y el corto hacia el lado del circuito (por el lado derecho del
        rumbo primario: izquierda para el opuesto, derecha para el primario). Es lo que el alumno debe leer al
        sobrevolar un aeródromo no controlado."""
        rw = ap.runways[0]
        c = rw.threshold + rw.dir * 250 - rw.right * (rw.width / 2 + 60)     # donde está la manga
        z = -(ap.elev + 0.2)
        white = (0.95, 0.95, 0.93)
        R, nseg = 16.0, 10
        for k in range(nseg):
            a = 2 * math.pi * (k + 0.5) / nseg
            p = c + np.array([math.cos(a), math.sin(a)]) * R
            mb.box((p[0], p[1], z), (1.0, 2 * math.pi * R / nseg * 0.6, 0.35), white, yaw=a)
        side = rw.right                                                       # lado del circuito
        for d in (rw.dir, -rw.dir):                                           # cada sentido de aterrizaje
            base = c - d * (R + 8.0)                                          # del lado por donde se llega
            long_c = base
            mb.box((long_c[0], long_c[1], z), (9.0, 1.0, 0.35), white, yaw=math.atan2(d[1], d[0]))
            end = base - d * 4.5                                              # extremo del brazo largo (lado de llegada)
            short_c = end + side * 2.25
            mb.box((short_c[0], short_c[1], z), (4.5, 1.0, 0.35), white, yaw=math.atan2(side[1], side[0]))

    def _apron_lights(self):
        """Torres de iluminación de 18 m en el borde de cada plataforma (del lado opuesto a la pista), cada ~60 m,
        mirando hacia ella: (x, y, z del suelo, rumbo de la cara, altura). De noche alumbran el concreto."""
        out = []
        for ap in self.aps:
            if ap.apron is None:
                continue
            (c, h, ln, wd) = ap.apron
            hr = math.radians(h)
            d = np.array([math.cos(hr), math.sin(hr)])
            r = np.array([-d[1], d[0]])
            c = np.asarray(c, float)
            rw = ap.runways[0]
            side = 1.0 if float((c - rw.center) @ r) > 0 else -1.0        # el lado de la plataforma lejos de la pista
            n = max(2, int(ln // 60))
            for i in range(n):
                p = c + d * (-ln / 2 + ln * (i + 0.5) / n) + r * side * (wd / 2 + 4.0)
                face = math.atan2(-r[1] * side, -r[0] * side)              # la cara mira hacia la plataforma
                g = max(float(self.terrain.height(p[0], p[1])), ap.elev)
                out.append((float(p[0]), float(p[1]), -g, face, 18.0))
                if bl.load_model("poste_luz") is not None:
                    self.house_inst.append(("poste_luz", float(p[0]), float(p[1]), -g, face + math.pi / 2,
                                            1.0, 1.0, 1.0, 1.0))
        return out

    def _navaid_sites(self):
        """Estaciones físicas de las radioayudas: VOR, NDB y, por cada ILS, la antena del localizador (detrás del
        extremo opuesto de la pista, de frente a ella) y la de senda de planeo (300 m pasado el umbral, al costado)."""
        T = self.terrain
        for nv in self.world.navaids:
            x, y = float(nv.pos[0]), float(nv.pos[1])
            if nv.kind in ("VOR", "NDB"):
                key = "vor" if nv.kind == "VOR" else "ndb"
                if bl.load_model(key) is not None:
                    self.house_inst.append((key, x, y, -float(T.height(x, y)), 0.0, 1.0, 1.0, 1.0, 1.0))
            elif nv.kind == "ILS" and getattr(nv, "runway", None) is not None:
                rw = nv.runway
                ap = next((a for a in self.aps if rw in a.runways), None)
                if ap is None:
                    continue
                thr, _hdg, de = rw.end(nv.end_ident)
                re = np.array([-de[1], de[0]])
                if bl.load_model("localizador") is not None:
                    yaw = math.atan2(-de[0], de[1])          # su -y local mira hacia la pista
                    self.house_inst.append(("localizador", x, y, -ap.elev, yaw, 1.0, 1.0, 1.0, 1.0))
                if bl.load_model("senda") is not None:
                    g = thr + de * 300.0 + re * (rw.width / 2 + 120.0)
                    self.house_inst.append(("senda", float(g[0]), float(g[1]), -ap.elev, 0.0, 1.0, 1.0, 1.0, 1.0))

    def _fences(self):  # noqa: C901
        """Cerca perimetral de los aeródromos de la escuela: rectángulo alrededor de pista, calles y plataforma,
        a 70 m del borde de la pista, con tramos de 3 m que siguen el terreno."""
        if not self.world.is_school:
            return
        for ap in self.aps:
            pts = []
            for rw in ap.runways:
                for s_ in (-1, 1):
                    for l_ in (-1, 1):
                        pts.append(rw.center + rw.dir * s_ * (rw.length / 2 + 120.0) + rw.right * l_ * (rw.width / 2 + 70.0))
            for (c, h, ln, wd) in ap.paved_rects:
                hr = math.radians(h)
                d = np.array([math.cos(hr), math.sin(hr)])
                r = np.array([-d[1], d[0]])
                for s_ in (-1, 1):
                    for l_ in (-1, 1):
                        pts.append(np.asarray(c) + d * s_ * (ln / 2 + 60.0) + r * l_ * (wd / 2 + 60.0))
            rw = ap.runways[0]
            P = np.array(pts)
            u = (P - rw.center) @ rw.dir
            v = (P - rw.center) @ rw.right
            corners = [(u.min(), v.min()), (u.max(), v.min()), (u.max(), v.max()), (u.min(), v.max())]
            C = [rw.center + rw.dir * a + rw.right * b for a, b in corners]
            for k in range(4):
                a, b = C[k], C[(k + 1) % 4]
                L = float(np.linalg.norm(b - a))
                dd = (b - a) / L
                yaw = math.atan2(dd[1], dd[0])
                n = int(L // 3.0)
                pieces = [a + dd * (i + 0.5) * 3.0 for i in range(n)]
                # portones donde la cerca cruza una carretera (hueco de unos 12 m)
                gate = [any(_dist_poly(q, rd) < 7.0 for rd in getattr(self, "road_lines", [])) for q in pieces]
                for i in range(n):
                    if gate[i]:
                        continue
                    p = pieces[i]
                    g = float(self.terrain.height(p[0], p[1]))
                    self.house_inst.append(("valla", p[0], p[1], -g, yaw, 1.0, 1.0, 1.0, 1.0))

    def _masts(self, mb):
        """Antenas de radio y TV (60-90 m) en las cimas más altas a menos de 12 km de los aeródromos, separadas por
        3 km o más, como las repetidoras de los cerros. Pintadas en franjas rojas y blancas (OACI) y con luz roja de
        obstáculo: intermitente arriba y fija a media altura (la enciende el renderizador de noche)."""
        T = self.terrain
        out = []
        for ap in self.aps[:2]:
            g = np.arange(-12000.0, 12001.0, 250.0)
            X, Y = np.meshgrid(ap.ref[0] + g, ap.ref[1] + g, indexing="ij")
            try:
                H = T.height_v(X, Y)
            except Exception:
                continue
            # cimas: el punto más alto de su vecindario de ~1,5 km, bien por encima del aeródromo
            from numpy.lib.stride_tricks import sliding_window_view
            P = np.pad(H, 3, mode="edge")
            loc_max = sliding_window_view(P, (7, 7)).max(axis=(-1, -2))
            inner = np.zeros_like(H, bool)
            inner[3:-3, 3:-3] = True                 # en el borde del muestreo cualquier ladera parece cima
            cand = np.argwhere((H >= loc_max) & (H > ap.elev + 120.0) & inner)
            cand = sorted(cand.tolist(), key=lambda ij: -H[ij[0], ij[1]])
            n = 0
            for i, j in cand:
                x, y = float(X[i, j]), float(Y[i, j])
                if math.hypot(x - ap.ref[0], y - ap.ref[1]) < 2500.0 or T.is_water(x, y):
                    continue
                if any(math.hypot(x - m[0], y - m[1]) < 3000.0 for m in out):
                    continue
                out.append((x, y, -float(H[i, j]), 60.0 + 30.0 * (n % 2)))
                n += 1
                if n >= 2:
                    break
        red, white = (0.78, 0.18, 0.1), (0.9, 0.9, 0.88)
        for (x, y, gz, h) in out:
            nb = 7                                   # franjas alternadas, rojas en los extremos
            for k in range(nb):
                z0, z1 = h * k / nb, h * (k + 1) / nb
                w = 1.6 - 0.8 * (z0 + z1) / (2 * h)  # se afina hacia arriba
                mb.box((x, y, gz - (z0 + z1) / 2), (w, w, z1 - z0), red if k % 2 == 0 else white)
            mb.box((x, y, gz - 0.3), (3.0, 3.0, 0.6), (0.55, 0.55, 0.53))     # base de concreto
        return out

    def _power_line(self, mb, a, b, step=380.0):
        """Tendido de alta tensión: torres de celosía de 32 m cada ~380 m, cuatro conductores en dos crucetas y el
        cable de guarda arriba, todos con su comba. Donde el vano cruza alto sobre el valle lleva esferas naranjas
        y blancas de señalización. Los cables son finos: como en la realidad, cuesta verlos."""
        T = self.terrain
        a, b = np.asarray(a, float), np.asarray(b, float)
        L = float(np.linalg.norm(b - a))
        d = (b - a) / L
        side = np.array([-d[1], d[0]])
        n = int(L // step)
        grey, wire, orange, white = (0.55, 0.56, 0.57), (0.22, 0.22, 0.23), (0.95, 0.42, 0.08), (0.92, 0.92, 0.9)
        attach = [(-6.0, 22.0), (6.0, 22.0), (-4.0, 28.0), (4.0, 28.0), (0.0, 32.0)]     # (lateral, altura)
        towers = []
        for i in range(n + 1):
            p = a + d * (i * L / n)
            g = float(T.height(p[0], p[1]))
            towers.append((p, -g))
            # celosía: cuatro patas que se juntan arriba, crucetas y algunas diagonales
            yaw = math.atan2(d[1], d[0])
            for sx in (-1, 1):
                for sy in (-1, 1):
                    base = np.array([p[0], p[1], -g]) + np.array([*(d * sx * 3.0 + side * sy * 3.0), 0.0])
                    top = np.array([p[0], p[1], -g - 32.0]) + np.array([*(d * sx * 0.6 + side * sy * 0.6), 0.0])
                    mb.beam(base, top, 0.3, 0.3, grey)
            for (lat, h) in ((0.0, 22.0), (0.0, 28.0)):
                w_ = 6.6 if h < 25 else 4.6
                p0 = np.array([*(p - side * w_), -g - h])
                p1 = np.array([*(p + side * w_), -g - h])
                mb.beam(p0, p1, 0.35, 0.5, grey)
            for h0, h1 in ((2.0, 12.0), (12.0, 22.0)):
                for sy in (-1, 1):
                    q0 = np.array([*(p + side * sy * 3.0 * (1 - h0 / 40)), -g - h0])
                    q1 = np.array([*(p - side * sy * 3.0 * (1 - h1 / 40)), -g - h1])
                    mb.beam(q0, q1, 0.15, 0.15, grey)
        for (p0, z0), (p1, z1) in zip(towers[:-1], towers[1:]):
            span = float(np.linalg.norm(p1 - p0))
            mid = (p0 + p1) / 2
            clear = (z0 + z1) / 2 - (-float(T.height(mid[0], mid[1])))      # altura del vano sobre el suelo
            for (lat, h) in attach:
                sag = 0.03 * span
                segs = 14
                pts = []
                for k in range(segs + 1):
                    t = k / segs
                    xy = p0 + (p1 - p0) * t + side * lat
                    z = z0 + (z1 - z0) * t - h + sag * 4 * t * (1 - t)
                    pts.append(np.array([xy[0], xy[1], z]))
                for q0, q1 in zip(pts[:-1], pts[1:]):
                    mb.beam(q0, q1, 0.12, 0.12, wire)
                if lat == 0.0 and h == 32.0 and clear > 25.0:
                    for k, t in enumerate((0.3, 0.5, 0.7)):
                        xy = p0 + (p1 - p0) * t
                        z = z0 + (z1 - z0) * t - h + sag * 4 * t * (1 - t) + 0.3
                        mb.box((xy[0], xy[1], z), (0.7, 0.7, 0.7), orange if k % 2 == 0 else white)
        self.power_towers = [(float(p[0]), float(p[1]), z) for p, z in towers]

    def _houses_facade(self, P, sc, yaw, cm):
        """Casas con fachada (ventanas) y techo de tejas a dos aguas."""
        style = np.full(len(P), float(bl.HOUSE)) + self.rng.uniform(0.1, 0.9, len(P))
        self._bparts.append(bl.box_buildings(P, sc, yaw, np.array([0.9, 0.87, 0.8]) * cm,
                                             np.array([0.62, 0.30, 0.22]) * cm, style, gable_frac=0.3))

    def _hangar(self, mb, base, ln, wd, ht, yaw, col, sign=None):
        """Anota el hangar para el renderizador (chapa ondulada, portones, techo a dos aguas, letrero)."""
        x, y, gz = base
        self.hangars.append((x, y, gz, ln, wd, ht, yaw, tuple(col), sign))

    def _hangar_simple(self, mb, base, ln, wd, ht, yaw, col):
        x, y, gz = base
        mb.box((x, y, gz - ht / 2), (ln, wd, ht), col, yaw=yaw)
        # techo a dos aguas bajo
        a = ln / 2
        b = wd / 2
        top = gz - ht - 2.5
        mb.quad((x - a, y - b, gz - ht), (x + a, y - b, gz - ht), (x + a, y, top), (x - a, y, top), (0.45, 0.47, 0.5))
        mb.quad((x - a, y + b, gz - ht), (x + a, y + b, gz - ht), (x + a, y, top), (x - a, y, top), (0.45, 0.47, 0.5))
        # puerta (cara oeste mirando a la plataforma)
        mb.quad((x - a * 0.85, y - b - 0.05, gz), (x + a * 0.85, y - b - 0.05, gz),
                (x + a * 0.85, y - b - 0.05, gz - ht * 0.8), (x - a * 0.85, y - b - 0.05, gz - ht * 0.8), (0.3, 0.32, 0.35))

    def _town_points(self, cx, cy, rad, n):
        rng = self.rng
        g = 22.0
        k = int(rad * 2 / g)
        xs, ys = np.meshgrid(np.arange(k) * g - rad, np.arange(k) * g - rad)
        xs = xs.ravel()
        ys = ys.ravel()
        r = np.hypot(xs, ys)
        street = ((np.round(xs / g) % 5 == 0) | (np.round(ys / g) % 4 == 0))
        ok = (r < rad) & ~street
        xs, ys, r = xs[ok], ys[ok], r[ok]
        p = np.exp(-(r / (rad * 0.6)) ** 2)
        p /= p.sum()
        n = min(n, len(xs))
        idx = rng.choice(len(xs), n, replace=False, p=p)
        ang = math.radians(11.0)
        x = xs[idx] * math.cos(ang) - ys[idx] * math.sin(ang)
        y = xs[idx] * math.sin(ang) + ys[idx] * math.cos(ang)
        return np.column_stack([x + cx + rng.uniform(-3, 3, n), y + cy + rng.uniform(-3, 3, n)])

    def _trees(self):
        T = self.terrain
        rng = self.rng
        X, Y = T.grid_xy()
        mask = T.forest.copy()
        near = np.zeros_like(mask)
        for ap in self.aps:
            near |= np.hypot(X - ap.ref[0], Y - ap.ref[1]) < 9000
        near |= np.hypot(X + 3600, Y + 3200) < 6000
        mask &= near
        ii, jj = np.nonzero(mask)
        if len(ii) > 8000:
            sel = rng.choice(len(ii), 8000, replace=False)
            ii, jj = ii[sel], jj[sel]
        ii, jj = np.repeat(ii, 3), np.repeat(jj, 3)                  # bosques tupidos: tres árboles por celda
        x = X[ii, jj] + rng.uniform(-50, 50, len(ii))
        y = Y[ii, jj] + rng.uniform(-50, 50, len(ii))
        keep = np.ones(len(x), bool)
        for ap in self.aps:
            for rw in ap.runways:
                dx, dy = x - rw.center[0], y - rw.center[1]
                al = np.abs(dx * rw.dir[0] + dy * rw.dir[1])
                la = np.abs(dx * rw.right[0] + dy * rw.right[1])
                keep &= ~((al < rw.length / 2 + 900) & (la < 600))
        x, y = x[keep], y[keep]
        h = np.array([T.height(a, b) for a, b in zip(x, y)])
        P = np.column_stack([x, y, -h + 0.3])
        m = len(P)
        half = m // 2
        sc = rng.uniform(9, 19, m)
        cm = rng.uniform(0.8, 1.15, (m, 3)) * np.array([1.0, 1.0, 0.9])
        kind = np.zeros(m, np.int32)
        kind[half:] = 1
        sc[half:] *= 0.8
        self._add_trees(P, sc, rng.uniform(0, 6.28, m), cm, kind)

    def _add_trees(self, P, sc, yaw, cm, kind):
        new = dict(P=np.asarray(P, np.float32), s=np.asarray(sc, np.float32), yaw=np.asarray(yaw, np.float32),
                   col=np.asarray(cm, np.float32), kind=np.asarray(kind, np.int32))
        if self.trees is None:
            self.trees = new
        else:
            self.trees = {k: np.concatenate([self.trees[k], new[k]]) for k in new}

    def _road(self, mb, pts):
        T = self.terrain
        col = (0.30, 0.30, 0.31)
        w = 4.5
        prev = None
        for k in range(len(pts) - 1):
            a = np.array(pts[k], float)
            b = np.array(pts[k + 1], float)
            L = np.linalg.norm(b - a)
            d = (b - a) / L
            r = np.array([-d[1], d[0]])
            nseg = max(1, int(L / 30))
            for i in range(nseg + 1):
                p = a + d * L * i / nseg
                hl = T.height(*(p - r * w))
                hr = T.height(*(p + r * w))
                hc = T.height(*p)
                z = -(max(hl, hr, hc, 0.0) + 0.6)
                cur = ((*(p - r * w), z), (*(p + r * w), z))
                if prev is not None:
                    mb.quad(prev[0], prev[1], cur[1], cur[0], col)
                prev = cur

    def _town_lights(self):
        if getattr(self, "_real_lights", None):
            P = np.array(self._real_lights[:30000])
            # mezcla de luz cálida (sodio) y blanca (LED), como en una ciudad real
            rng = np.random.default_rng(5)
            warm = rng.uniform(0, 1, len(P)) < 0.7
            col = np.where(warm[:, None], np.array([[1.0, 0.7, 0.36]]), np.array([[0.95, 0.95, 1.0]]))
            size = rng.uniform(2.2, 3.4, (len(P), 1))
            return np.hstack([P, col, size]).astype(np.float32)
        pts = []
        for P in getattr(self, "_houses", []):
            sel = P[:: 2]
            pts.append(sel + np.array([0, 0, -2.0]))
        if not pts:
            return np.zeros((0, 7), np.float32)
        P = np.vstack(pts)
        col = np.tile(np.array([[1.0, 0.75, 0.4]]), (len(P), 1))
        size = np.full((len(P), 1), 3.0)
        return np.hstack([P, col, size]).astype(np.float32)

    # ---------------------------------------------------------------- luces
    def _lights(self):
        L = []
        groups = []        # (ident_a, idx_slice_a, idx_slice_b, runway) para color bicolor de umbrales
        papis = []
        self._papi_yaw = []
        self._als_bars = []
        rabbits = []

        def add(p, c, s):
            L.append((p[0], p[1], p[2], c[0], c[1], c[2], s))
        for ap in self.aps:
            for rw in ap.runways:
                if not getattr(rw, "lighted", True):
                    continue                  # pista sin luces: de noche no se ve (no se puede planificar ahí)
                z = -(ap.elev + 0.5)
                thr = rw.threshold
                d, r = rw.dir, rw.right
                W, Ln = rw.width, rw.length
                # luces de borde: de alta intensidad (HIRL) en pistas de aproximación de precisión, con la zona de
                # precaución amarilla en los últimos 600 m; de intensidad media (MIRL), todas blancas, en las demás
                hirl = self._ils_runway(rw)
                es, ek = (3.8, 1.3) if hirl else (3.0, 1.0)
                for s in np.arange(0, Ln + 1, 60.0):
                    for sg in (-1, 1):
                        p = thr + d * s + r * sg * (W / 2 + 1.5)
                        caution = hirl and (s > Ln - 600 or s < 600)
                        col = (1.0, 0.92, 0.6) if caution else (1.0, 1.0, 0.95)
                        add((p[0], p[1], z), tuple(c * ek for c in col), es)
                a0 = len(L)
                for k in np.linspace(-W / 2, W / 2, 8):
                    p = thr - d * 1.0 + r * k
                    add((p[0], p[1], z), (0.2, 1.0, 0.35), 3.5)
                a1 = len(L)
                for k in np.linspace(-W / 2, W / 2, 8):
                    p = thr + d * (Ln + 1.0) + r * k
                    add((p[0], p[1], z), (1.0, 0.15, 0.1), 3.5)
                b1 = len(L)
                groups.append((rw, slice(a0, a1), slice(a1, b1)))
                # luces de aproximación del extremo con ILS
                ils_end = None
                ends = [nv for nv in self.world.navaids if nv.kind == "ILS" and nv.runway is rw
                        and (not self.world.is_school or nv.end_ident in ("36", "27"))]
                for ils_end in ends:
                    thr_e, _hdg, de = rw.end(ils_end.end_ident)
                    re = np.array([-de[1], de[0]])
                    for dist in range(60, 780, 60):
                        pc = thr_e - de * dist
                        gz = -(max(self.terrain.height(pc[0], pc[1]), ap.elev, 0.0) + 1.2)
                        for k in (-2, -1, 0, 1, 2):
                            p = pc + re * k * 1.0
                            add((p[0], p[1], gz), (1.0, 1.0, 0.95), 3.5)
                        # soporte de la barra (modelo de Blender): -y local mira a la aproximación
                        self._als_bars.append((float(pc[0]), float(pc[1]), gz + 1.2, math.atan2(-de[0], de[1])))
                        if dist == 300:
                            for k in (-4, 4):
                                q = pc + re * k * 1.6 * 1.25
                                self._als_bars.append((float(q[0]), float(q[1]), gz + 1.2, math.atan2(-de[0], de[1])))
                        if dist == 300:
                            for k in range(-7, 8):
                                p = pc + re * k * 1.6
                                add((p[0], p[1], gz), (1.0, 1.0, 0.95), 3.5)
                        if dist >= 360:
                            rabbits.append((pc[0], pc[1], gz - 1.0, dist))
                    # PAPI a la izquierda, 300 m pasado el umbral
                    angles = [3.5, 3.17, 2.83, 2.5]
                    for i, ang in enumerate(angles):
                        p = thr_e + de * 300 - re * (W / 2 + 15 + i * 9)
                        papis.append((p[0], p[1], -(ap.elev + 0.8), ang))
                        self._papi_yaw.append((p[0], p[1], -(ap.elev + 0.8), ang, math.atan2(-de[0], de[1])))
        # REIL en los extremos sin luces de aproximación (escenario de la escuela; en los aeropuertos reales no hay
        # dato de cuáles las tienen)
        self.reils = []
        if self.world.is_school:
            for ap in self.aps:
                for rw in ap.runways:
                    with_als = {nv.end_ident for nv in self.world.navaids if nv.kind == "ILS" and nv.runway is rw
                                and nv.end_ident in ("36", "27")}
                    for ident in rw.idents:
                        if ident in with_als:
                            continue
                        thr_e, _h, de = rw.end(ident)
                        re = np.array([-de[1], de[0]])
                        for sg in (-1, 1):
                            p = thr_e - de * 3.0 + re * sg * (rw.width / 2 + 12.0)
                            self.reils.append((float(p[0]), float(p[1]), -(ap.elev + 1.0)))
        # luces azules de borde de calles de rodaje y plataforma (cada 30 m, sin las del cruce con la pista)
        for ap in self.aps:
            z = -(ap.elev + 0.4)
            for (c, h, ln, wd) in ap.paved_rects:
                c = np.asarray(c, float)
                hr = math.radians(h)
                d = np.array([math.cos(hr), math.sin(hr)])
                r = np.array([-d[1], d[0]])
                for sgn in (-1, 1):
                    for u in np.arange(-ln / 2, ln / 2 + 0.1, 30.0):
                        p = c + d * u + r * sgn * (wd / 2 + 1.0)
                        q = c + d * u + r * sgn * (wd / 2 + 3.0)
                        if ap.paved(q[0], q[1]) or any(rw.contains(p[0], p[1], 12.0) for rw in ap.runways):
                            continue                 # borde interior (cruce con otra calle) o junto a la pista
                        add((p[0], p[1], z), (0.12, 0.3, 1.0), 2.4)
        self.beacons = self._beacon_points()
        # luminarias físicas (modelos de Blender) bajo las luces de borde, umbral y rodaje, y las cajas de los PAPI
        if bl.load_model("luminaria") is not None:
            for (x, y, z, r_, g_, b_, sz) in L:
                gz = -float(max(self.terrain.height(x, y), 0.0))
                for ap in self.aps:
                    if math.hypot(x - ap.ref[0], y - ap.ref[1]) < 6000:
                        gz = -ap.elev
                        break
                if abs((z - gz) + 0.45) < 0.2:             # las de 0,4-0,5 m sobre el suelo (no las de aproximación)
                    self.house_inst.append(("luminaria", x, y, gz, 0.0, 1.0, 1.0, 1.0, 1.0))
        if bl.load_model("barra_aprox") is not None:
            for (x, y, gz, yaw) in self._als_bars:
                self.house_inst.append(("barra_aprox", x, y, gz, yaw, 1.0, 1.0, 1.0, 1.0))
        if bl.load_model("papi") is not None:
            for (x, y, z, ang, yaw) in self._papi_yaw:
                self.house_inst.append(("papi", x, y, z + 0.8, yaw, 1.0, 1.0, 1.0, 1.0))
        return np.array(L, np.float32), groups, papis, rabbits

    def _beacon_points(self):
        """Faro giratorio del aeródromo (blanco y verde): sobre la torre si hay; si no, cerca del punto de referencia,
        apartado de las pistas."""
        out = []
        for ap in self.aps:
            tw = [t for t in getattr(self, "towers", []) if math.hypot(t[0] - ap.ref[0], t[1] - ap.ref[1]) < 1500]
            if tw:
                x, y, gz, h = tw[0]
                out.append((x, y, gz - h - 6.6))
                continue
            p = np.asarray(ap.ref, float).copy()
            for rw in ap.runways:
                lat = float((p - rw.center) @ rw.right)
                if abs(lat) < 180.0 and abs(float((p - rw.center) @ rw.dir)) < rw.length / 2 + 200:
                    p = p + rw.right * ((180.0 if lat >= 0 else -180.0) - lat)
            g = max(self.terrain.height(p[0], p[1]), ap.elev)
            out.append((float(p[0]), float(p[1]), -(g + 15.0)))
        return out

    def _windsocks(self):
        out = []
        for ap in self.aps:
            rw = ap.runways[0]
            p = rw.threshold + rw.dir * 250 - rw.right * (rw.width / 2 + 60)
            out.append((p[0], p[1], -ap.elev))
        return out
