"""Escenario estático: malla de terreno, pistas, edificios, árboles, carreteras y luces."""
import math

import numpy as np

from . import geometry as geo
from . import textures as tx

TOWNS = [
    # (x, y, radio, casas, edificios)
    (-3600.0, -3200.0, 950.0, 260, 26),
    (15300.0, 6300.0, 650.0, 120, 8),
    (-9000.0, 2500.0, 450.0, 60, 0),
    (5200.0, -9000.0, 500.0, 70, 0),
]


class Scenery:
    def __init__(self, world, rng_seed=21):
        self.world = world
        # aeródromos dentro del paisaje (en un tramo de ruta, el de referencia puede quedar fuera y no se dibuja)
        self.aps = [a for a in world.airports if not getattr(a, "offscene", False)]
        self.terrain = world.terrain
        self.rng = np.random.default_rng(rng_seed)
        self.terrain_vertices, self.terrain_indices = self._terrain_mesh()
        self.objects = self._objects()
        self.runways = self._runways()
        self.lights_static, self.light_groups, self.papis, self.rabbits = self._lights()
        self.windsocks = self._windsocks()
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
        """Lista de (textura_surface, vertices pos+uv float32)."""
        out = []
        for ap in self.aps:
            for rw in ap.runways:
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
                out.append((end_a, np.array(va, np.float32)))
                out.append((end_b, np.array(vb, np.float32)))
                out.append((mid, np.array(vm, np.float32)))
        return out

    # ---------------------------------------------------------------- objetos
    def _objects(self):
        self.parked, self.parked_code = [], np.zeros((0, 9), np.float32)
        mb = geo.MeshBuilder()
        rng = self.rng
        world = self.world
        T = self.terrain
        # plataformas y calles de rodaje
        for ap in self.aps:
            z = -(ap.elev + 0.05)
            for (c, hdg, ln, wd) in ap.paved_rects:
                h = math.radians(hdg)
                d = np.array([math.cos(h), math.sin(h)])
                rt = np.array([-d[1], d[0]])
                c = np.array(c)
                corners = [c - d * ln / 2 - rt * wd / 2, c + d * ln / 2 - rt * wd / 2,
                           c + d * ln / 2 + rt * wd / 2, c - d * ln / 2 + rt * wd / 2]
                pts = [(p[0], p[1], z) for p in corners]
                mb.quad(*pts, (0.36, 0.36, 0.37))
                # línea central amarilla a lo largo del lado mayor
                if ln >= wd:
                    a_, b_ = c - d * ln / 2, c + d * ln / 2
                    w_ = rt * 0.15
                else:
                    a_, b_ = c - rt * wd / 2, c + rt * wd / 2
                    w_ = d * 0.15
                if min(ln, wd) < 40:
                    zz = z - 0.01
                    mb.quad((*(a_ - w_), zz), (*(b_ - w_), zz), (*(b_ + w_), zz), (*(a_ + w_), zz), (0.85, 0.7, 0.15))
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
            self._hangar(mb, (hx, 262.0, ge), 45.0, 34.0, 11.0, yaw=0.0, col=[(0.75, 0.76, 0.78), (0.62, 0.66, 0.70), (0.80, 0.78, 0.72)][i])
        mb.box((-60.0, 215.0, ge - 8.0), (7, 7, 16), (0.86, 0.85, 0.82))          # torre
        mb.box((-60.0, 215.0, ge - 18.0), (10, 10, 4), (0.12, 0.2, 0.28))
        mb.box((-60.0, 215.0, ge - 20.3), (11, 11, 0.6), (0.4, 0.4, 0.42))
        mb.box((310.0, 160.0, ge - 3.5), (34, 22, 7), (0.88, 0.86, 0.8))         # terminal
        mb.box((310.0, 160.0, ge - 7.2), (36, 24, 0.5), (0.5, 0.5, 0.52))
        mb.box((290.0, 98.0, ge - 1.5), (6, 3, 3), (0.85, 0.2, 0.15))             # surtidor
        # aeródromo norte
        gn = -vnt.elev
        self._hangar(mb, (17160.0, 3800.0, gn), 35.0, 28.0, 9.0, yaw=0.0, col=(0.72, 0.74, 0.76))
        self._hangar(mb, (17160.0, 3740.0, gn), 30.0, 24.0, 8.0, yaw=0.0, col=(0.8, 0.78, 0.7))
        mb.box((17080.0, 3720.0, gn - 6.0), (5, 5, 12), (0.86, 0.85, 0.82))
        mb.box((17080.0, 3720.0, gn - 13.5), (7, 7, 3), (0.12, 0.2, 0.28))
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
        # pueblos
        house = geo.template_house()
        block = geo.template_block()
        for (tx_, ty_, rad, nh, nb) in TOWNS:
            pts = self._town_points(tx_, ty_, rad, nh)
            if len(pts):
                h = np.array([T.height(p[0], p[1]) for p in pts])
                P = np.column_stack([pts[:, 0], pts[:, 1], -h])
                sc = np.column_stack([rng.uniform(8, 16, len(pts)), rng.uniform(7, 12, len(pts)), rng.uniform(5, 8, len(pts))])
                yaw = np.round(rng.uniform(0, 4, len(pts))) * math.pi / 2 + 0.2
                cm = rng.uniform(0.85, 1.1, (len(pts), 3))
                mb.add(geo.instances(house, P, sc, yaw, cm))
                self._houses = getattr(self, "_houses", []) + [P]
            if nb:
                pts = self._town_points(tx_, ty_, rad * 0.35, nb)
                h = np.array([T.height(p[0], p[1]) for p in pts])
                P = np.column_stack([pts[:, 0], pts[:, 1], -h])
                sc = np.column_stack([rng.uniform(18, 30, nb), rng.uniform(18, 30, nb), rng.uniform(12, 38, nb)])
                yaw = np.full(nb, 0.2)
                cm = rng.uniform(0.8, 1.1, (nb, 3))
                mb.add(geo.instances(block, P, sc, yaw, cm))
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
            mb.add(geo.instances(house, P, sc, rng.uniform(0, math.pi, m), rng.uniform(0.85, 1.1, (m, 3))))
        # árboles en bosques (cerca de los aeródromos y a lo largo del valle)
        mb.add(self._trees())
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
        A, B, ZB, ZT, WC = [], [], [], [], []          # paredes (por arista)
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
            ZB.append(np.full(k, -(g - 1.0)))
            ZT.append(np.full(k, -(g + ht)))
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
        a = np.vstack(A)
        b = np.vstack(B)
        zb = np.concatenate(ZB)
        zt = np.concatenate(ZT)
        wc = np.vstack(WC)
        d = b - a
        ln = np.sqrt((d ** 2).sum(1)) + 1e-9
        nrm = np.column_stack([d[:, 1] / ln, -d[:, 0] / ln, np.zeros(len(d))])
        shade = (0.82 + 0.18 * np.abs(d[:, 0] / ln))[:, None]
        col = wc * shade
        p00 = np.column_stack([a, zb])
        p10 = np.column_stack([b, zb])
        p11 = np.column_stack([b, zt])
        p01 = np.column_stack([a, zt])
        walls = np.stack([p00, p10, p11, p00, p11, p01], axis=1)          # (E, 6, 3)
        E = len(a)
        wv = np.empty((E, 6, 9), np.float32)
        wv[..., 0:3] = walls
        wv[..., 3:6] = nrm[:, None, :]
        wv[..., 6:9] = col[:, None, :]
        mb.add(wv.reshape(-1, 9))
        rc = np.vstack(RC)
        ra = np.vstack(RA)
        rb = np.vstack(RB)
        rz = np.concatenate(RZ)
        rcol = np.vstack(RCOL)
        tri = np.stack([np.column_stack([rc, rz]), np.column_stack([ra, rz]), np.column_stack([rb, rz])], axis=1)
        F = len(rc)
        rv = np.empty((F, 3, 9), np.float32)
        rv[..., 0:3] = tri
        rv[..., 3:6] = np.array([0.0, 0.0, -1.0])
        rv[..., 6:9] = rcol[:, None, :]
        mb.add(rv.reshape(-1, 9))
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
        mb.add(geo.instances(geo.template_tree(1), X[:half], sc[:half], rng.uniform(0, 6.28, half), cm[:half]))
        mb.add(geo.instances(geo.template_tree(0), X[half:], sc[half:] * 0.9, rng.uniform(0, 6.28, m - half), cm[half:]))
        print(f"  árboles: {m}")

    def _hangar(self, mb, base, ln, wd, ht, yaw, col):
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
        if len(ii) > 9000:
            sel = rng.choice(len(ii), 9000, replace=False)
            ii, jj = ii[sel], jj[sel]
        x = X[ii, jj] + rng.uniform(-45, 45, len(ii))
        y = Y[ii, jj] + rng.uniform(-45, 45, len(ii))
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
        a = geo.instances(geo.template_tree(0), P[:half], sc[:half], rng.uniform(0, 6.28, half), cm[:half])
        b = geo.instances(geo.template_tree(1), P[half:], sc[half:] * 0.8, rng.uniform(0, 6.28, m - half), cm[half:])
        return np.vstack([a, b])

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
        rabbits = []

        def add(p, c, s):
            L.append((p[0], p[1], p[2], c[0], c[1], c[2], s))
        for ap in self.aps:
            for rw in ap.runways:
                z = -(ap.elev + 0.5)
                thr = rw.threshold
                d, r = rw.dir, rw.right
                W, Ln = rw.width, rw.length
                for s in np.arange(0, Ln + 1, 60.0):
                    for sg in (-1, 1):
                        p = thr + d * s + r * sg * (W / 2 + 1.5)
                        caution = s > Ln - 600 or s < 600
                        add((p[0], p[1], z), (1.0, 0.92, 0.6) if caution else (1.0, 1.0, 0.95), 3.0)
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
        return np.array(L, np.float32), groups, papis, rabbits

    def _windsocks(self):
        out = []
        for ap in self.aps:
            rw = ap.runways[0]
            p = rw.threshold + rw.dir * 250 - rw.right * (rw.width / 2 + 60)
            out.append((p[0], p[1], -ap.elev))
        return out
