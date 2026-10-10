"""Construcción de geometría (numpy): primitivas, instancias y modelo del avión.

Cada vértice: posición (3), normal (3), color (3) -> float32.
"""
import math

import numpy as np


def _n(v):
    v = np.asarray(v, dtype=np.float64)
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.maximum(n, 1e-12)


class MeshBuilder:
    def __init__(self):
        self.chunks = []

    def tris(self, P, N, C):
        P = np.asarray(P, dtype=np.float32).reshape(-1, 3)
        N = np.asarray(N, dtype=np.float32).reshape(-1, 3)
        C = np.asarray(C, dtype=np.float32).reshape(-1, 3)
        if C.shape[0] == 1:
            C = np.repeat(C, P.shape[0], axis=0)
        self.chunks.append(np.hstack([P, N, C]))

    def tri(self, a, b, c, col):
        a, b, c = (np.asarray(x, dtype=np.float64) for x in (a, b, c))
        n = _n(np.cross(b - a, c - a))
        self.tris([a, b, c], [n, n, n], [col, col, col])

    def quad(self, a, b, c, d, col):
        self.tri(a, b, c, col)
        self.tri(a, c, d, col)

    def add(self, arr):
        if arr is not None and len(arr):
            self.chunks.append(np.asarray(arr, dtype=np.float32))

    def array(self):
        if not self.chunks:
            return np.zeros((0, 9), dtype=np.float32)
        return np.vstack(self.chunks).astype(np.float32)

    # -------------------------------------------------------------- primitivas
    def box(self, center, size, col, yaw=0.0):
        cx, cy, cz = center
        sx, sy, sz = (s / 2 for s in size)
        c, s = math.cos(yaw), math.sin(yaw)

        def P(x, y, z):
            return (cx + x * c - y * s, cy + x * s + y * c, cz + z)
        v = [P(-sx, -sy, -sz), P(sx, -sy, -sz), P(sx, sy, -sz), P(-sx, sy, -sz),
             P(-sx, -sy, sz), P(sx, -sy, sz), P(sx, sy, sz), P(-sx, sy, sz)]
        for f in ((0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            self.quad(v[f[0]], v[f[1]], v[f[2]], v[f[3]], col)

    def beam(self, p0, p1, w, h, col, up=(0, 0, -1)):
        p0 = np.asarray(p0, float)
        p1 = np.asarray(p1, float)
        ax = _n(p1 - p0)
        u = np.asarray(up, float)
        if abs(float(ax @ u)) > 0.95:
            u = np.array([1.0, 0, 0])
        side = _n(np.cross(ax, u)) * w / 2
        upv = _n(np.cross(side, ax)) * h / 2
        v = [p0 - side - upv, p0 + side - upv, p0 + side + upv, p0 - side + upv,
             p1 - side - upv, p1 + side - upv, p1 + side + upv, p1 - side + upv]
        for f in ((0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            self.quad(v[f[0]], v[f[1]], v[f[2]], v[f[3]], col)

    def cylinder(self, p0, p1, r, col, segs=12, caps=True):
        p0 = np.asarray(p0, float)
        p1 = np.asarray(p1, float)
        ax = _n(p1 - p0)
        tmp = np.array([0, 0, 1.0]) if abs(ax[2]) < 0.9 else np.array([1.0, 0, 0])
        u = _n(np.cross(ax, tmp))
        v = np.cross(ax, u)
        ring = [(math.cos(2 * math.pi * i / segs), math.sin(2 * math.pi * i / segs)) for i in range(segs + 1)]
        for i in range(segs):
            c0, s0 = ring[i]
            c1, s1 = ring[i + 1]
            d0 = u * c0 + v * s0
            d1 = u * c1 + v * s1
            a, b = p0 + d0 * r, p0 + d1 * r
            c, d = p1 + d1 * r, p1 + d0 * r
            self.tris([a, b, c, a, c, d], [d0, d1, d1, d0, d1, d0], [col])
            if caps:
                self.tris([p0, b, a], [-ax, -ax, -ax], [col])
                self.tris([p1, d, c], [ax, ax, ax], [col])

    def cone(self, base, tip, r, col, segs=10, cap=True):
        base = np.asarray(base, float)
        tip = np.asarray(tip, float)
        ax = _n(tip - base)
        tmp = np.array([0, 0, 1.0]) if abs(ax[2]) < 0.9 else np.array([1.0, 0, 0])
        u = _n(np.cross(ax, tmp))
        v = np.cross(ax, u)
        for i in range(segs):
            a0 = 2 * math.pi * i / segs
            a1 = 2 * math.pi * (i + 1) / segs
            d0 = u * math.cos(a0) + v * math.sin(a0)
            d1 = u * math.cos(a1) + v * math.sin(a1)
            n0 = _n(d0 + ax * 0.4)
            n1 = _n(d1 + ax * 0.4)
            self.tris([base + d0 * r, base + d1 * r, tip], [n0, n1, _n(n0 + n1)], [col])
            if cap:
                self.tris([base, base + d1 * r, base + d0 * r], [-ax, -ax, -ax], [col])

    def extrude(self, poly, axis, half_t, col, offset=0.0):
        """Extruye un polígono convexo. axis='y': polígono en (x,z); axis='z': en (x,y)."""
        pts = np.asarray(poly, float)
        k = len(pts)

        def P(p, t):
            if axis == "y":
                return np.array([p[0], offset + t, p[1]])
            return np.array([p[0], p[1], offset + t])
        top = [P(p, -half_t) for p in pts]
        bot = [P(p, half_t) for p in pts]
        for i in range(1, k - 1):
            self.tri(top[0], top[i], top[i + 1], col)
            self.tri(bot[0], bot[i + 1], bot[i], col)
        for i in range(k):
            j = (i + 1) % k
            self.quad(top[i], top[j], bot[j], bot[i], col)

    def airfoil_panel(self, x_le, x_te, y0, y1, z, thick, col, dih=0.0, x_le1=None, x_te1=None, z_of=None):
        """Panel de ala con perfil sencillo entre y0 e y1 (envergadura)."""
        if x_le1 is None:
            x_le1 = x_le
        if x_te1 is None:
            x_te1 = x_te
        prof = [(0.0, 0.0), (0.06, -0.55), (0.3, -1.0), (0.7, -0.55), (1.0, -0.05),
                (1.0, 0.05), (0.7, 0.25), (0.3, 0.42), (0.06, 0.3)]

        def section(y, xl, xt):
            c = xl - xt
            dz = (abs(y) - 0.0) * math.tan(dih)
            zz = z - dz
            return [np.array([xl - u * c, y, zz + v * thick]) for u, v in prof]
        s0 = section(y0, x_le, x_te)
        s1 = section(y1, x_le1, x_te1)
        k = len(prof)
        for i in range(k):
            j = (i + 1) % k
            self.quad(s0[i], s0[j], s1[j], s1[i], col)
        for i in range(1, k - 1):
            self.tri(s0[0], s0[i], s0[i + 1], col)
            self.tri(s1[0], s1[i + 1], s1[i], col)

    def loft(self, sections, color_fn, segs=16, power=0.75):
        """Fuselaje a partir de secciones (x, semiancho, semialto, z_centro)."""
        rings = []
        for x, hw, hh, zc in sections:
            ring = []
            for i in range(segs):
                a = 2 * math.pi * i / segs
                c, s = math.cos(a), math.sin(a)
                cy = math.copysign(abs(c) ** power, c)
                sz = math.copysign(abs(s) ** power, s)
                ring.append(np.array([x, hw * cy, zc + hh * sz]))
            rings.append(ring)
        for r in range(len(rings) - 1):
            A, B = rings[r], rings[r + 1]
            for i in range(segs):
                j = (i + 1) % segs
                mid = (A[i] + B[j]) / 2
                self.quad(A[i], A[j], B[j], B[i], color_fn(mid))
        for ring, sgn in ((rings[0], 1), (rings[-1], -1)):
            c = sum(ring) / len(ring)
            for i in range(segs):
                j = (i + 1) % segs
                self.tri(c, ring[i], ring[j], color_fn(c))

    def torus(self, R, r, col, segs=48, sides=8):
        for i in range(segs):
            a0 = 2 * math.pi * i / segs
            a1 = 2 * math.pi * (i + 1) / segs
            for j in range(sides):
                b0 = 2 * math.pi * j / sides
                b1 = 2 * math.pi * (j + 1) / sides

                def P(a, b):
                    # anillo en el plano y-z (normal = eje x)
                    cy, sz = math.cos(a), math.sin(a)
                    rr = R + r * math.cos(b)
                    return np.array([r * math.sin(b), rr * cy, rr * sz])
                self.quad(P(a0, b0), P(a1, b0), P(a1, b1), P(a0, b1), col)


def instances(template, pos, scale, yaw, colmul=None):
    """Replica 'template' (n,9) en muchas posiciones de forma vectorizada.

    pos (m,3), scale (m,3) o (m,), yaw (m,), colmul (m,3) opcional.
    """
    m = len(pos)
    if m == 0:
        return np.zeros((0, 9), np.float32)
    T = template.astype(np.float32)
    n = T.shape[0]
    scale = np.asarray(scale, np.float32)
    if scale.ndim == 1:
        scale = np.repeat(scale[:, None], 3, axis=1)
    c = np.cos(yaw).astype(np.float32)[:, None]
    s = np.sin(yaw).astype(np.float32)[:, None]
    P = T[None, :, 0:3] * scale[:, None, :]
    px = P[..., 0] * c - P[..., 1] * s
    py = P[..., 0] * s + P[..., 1] * c
    out = np.empty((m, n, 9), np.float32)
    out[..., 0] = px + pos[:, 0:1]
    out[..., 1] = py + pos[:, 1:2]
    out[..., 2] = P[..., 2] + pos[:, 2:3]
    N = T[None, :, 3:6] / np.maximum(scale[:, None, :], 1e-6)
    nx = N[..., 0] * c - N[..., 1] * s
    ny = N[..., 0] * s + N[..., 1] * c
    nz = N[..., 2]
    ln = np.sqrt(nx * nx + ny * ny + nz * nz) + 1e-9
    out[..., 3] = nx / ln
    out[..., 4] = ny / ln
    out[..., 5] = nz / ln
    C = np.broadcast_to(T[None, :, 6:9], (m, n, 3))
    if colmul is not None:
        C = C * np.asarray(colmul, np.float32)[:, None, :]
    out[..., 6:9] = C
    return out.reshape(-1, 9)


# --------------------------------------------------------------- plantillas
def template_tree(kind=0):
    mb = MeshBuilder()
    if kind == 0:      # conífera
        mb.cylinder((0, 0, 0), (0, 0, -0.25), 0.05, (0.35, 0.25, 0.15), segs=5, caps=False)
        mb.cone((0, 0, -0.18), (0, 0, -1.0), 0.32, (0.16, 0.30, 0.14), segs=7)
    else:              # frondoso
        mb.cylinder((0, 0, 0), (0, 0, -0.35), 0.06, (0.38, 0.28, 0.17), segs=5, caps=False)
        mb.cone((0, 0, -0.25), (0, 0, -1.0), 0.42, (0.22, 0.38, 0.15), segs=7)
        mb.cone((0, 0, -0.55), (0, 0, -0.2), 0.36, (0.20, 0.35, 0.14), segs=7, cap=False)
    return mb.array()


def template_house():
    mb = MeshBuilder()
    wall = (0.9, 0.87, 0.8)
    mb.box((0, 0, -0.35), (1, 1, 0.7), wall)
    roof = (0.62, 0.30, 0.22)
    a, b = -0.55, 0.55
    top = -1.0
    mb.quad((a, a, -0.7), (b, a, -0.7), (b, 0, top), (a, 0, top), roof)
    mb.quad((a, b, -0.7), (b, b, -0.7), (b, 0, top), (a, 0, top), roof)
    mb.tri((a, a, -0.7), (a, b, -0.7), (a, 0, top), wall)
    mb.tri((b, a, -0.7), (b, b, -0.7), (b, 0, top), wall)
    return mb.array()


def template_block():
    mb = MeshBuilder()
    mb.box((0, 0, -0.5), (1, 1, 1), (0.78, 0.78, 0.76))
    mb.box((0, 0, -1.01), (0.9, 0.9, 0.02), (0.45, 0.45, 0.47))
    return mb.array()


# --------------------------------------------------------------- avión
WHITE = (0.93, 0.93, 0.91)
GLASS = (0.10, 0.14, 0.20)
DARK = (0.08, 0.08, 0.08)
METAL = (0.6, 0.6, 0.62)


def aircraft_parts(t, accent=(0.10, 0.22, 0.55), base=WHITE):
    """Devuelve dict nombre -> (array, pivote, eje) en ejes cuerpo."""
    if getattr(t, "t_tail", False):
        from .geometry_diamond import diamond_parts
        return diamond_parts(t)
    if hasattr(t, "paint"):
        base, accent = t.paint
    low = getattr(t, "low_wing", False)
    parts = {}
    if low:
        secs = [(2.05, 0.28, 0.28, 0.05), (1.6, 0.50, 0.42, 0.05), (0.9, 0.55, 0.52, -0.05),
                (0.2, 0.56, 0.62, -0.12), (-0.9, 0.54, 0.6, -0.12), (-1.8, 0.40, 0.48, -0.1),
                (-3.2, 0.22, 0.32, -0.12), (-4.7, 0.09, 0.2, -0.2), (-5.1, 0.05, 0.1, -0.25)]
    else:
        secs = [(2.05, 0.30, 0.30, 0.05), (1.6, 0.52, 0.47, 0.05), (0.9, 0.56, 0.6, -0.08),
                (0.2, 0.56, 0.72, -0.18), (-0.8, 0.54, 0.70, -0.18), (-1.6, 0.42, 0.55, -0.15),
                (-3.0, 0.22, 0.38, -0.2), (-4.6, 0.10, 0.22, -0.3), (-5.0, 0.05, 0.12, -0.35)]

    def body_col(p):
        x, y, z = p
        if -1.1 < x < 0.95 and z < (-0.28 if not low else -0.22):
            return GLASS
        if 0.02 < z < 0.16 and x < 1.7:
            return accent
        return base

    cowl = MeshBuilder()
    cowl.loft(secs[:2], lambda p: base)
    parts["cowl"] = (cowl.array(), (0, 0, 0), (0, 1, 0))
    mb = MeshBuilder()
    mb.loft(secs, body_col)
    # alas
    if low:
        wz, dih, thick = 0.40, math.radians(6.5), 0.17
    else:
        wz, dih, thick = -0.95, math.radians(1.7), 0.16
    span = t.b / 2
    x_le, x_h, x_te = 0.55, -0.72, -1.08
    for sgn in (-1, 1):
        mb.airfoil_panel(x_le, x_h, sgn * 0.45, sgn * 2.75, wz, thick, base, dih=dih)
        mb.airfoil_panel(x_le, x_h, sgn * 2.75, sgn * (span - 0.35), wz, thick * 0.9, base, dih=dih)
        mb.airfoil_panel(x_le - 0.05, x_te + 0.3, sgn * (span - 0.35), sgn * span, wz, thick * 0.7, accent, dih=dih)
    # empenaje
    if low:
        mb.extrude([(-3.3, -0.25), (-4.65, -1.5), (-5.05, -1.5), (-4.95, -0.2)], "y", 0.05, base)
    else:
        mb.extrude([(-3.3, -0.38), (-4.75, -1.75), (-5.15, -1.75), (-5.0, -0.32)], "y", 0.05, base)
    if not low:
        mb.extrude([(-4.3, -0.18), (-4.3, 0.18), (-4.95, 1.75), (-4.95, -1.75)], "z", 0.04, base, offset=-0.27)
    # puntales
    if not low:
        for sgn in (-1, 1):
            mb.beam((0.05, sgn * 0.5, 0.38), (-0.05, sgn * 2.6, wz + 0.05), 0.12, 0.035, base)
    # tren fijo / retráctil
    gear = MeshBuilder()
    for g in t.gears:
        gx, gy, gz = g.pos
        r = 0.19 if g.name != "nariz" else 0.17
        cz = gz - r
        if g.name == "nariz":
            gear.beam((gx, 0, 0.35), (gx, 0, cz), 0.07, 0.07, METAL)
            gear.cylinder((gx, -0.07, cz), (gx, 0.07, cz), r, DARK, segs=10)
            if not t.retractable:
                gear.box((gx, 0, cz - 0.03), (0.6, 0.18, 0.28), base)
        else:
            sgn = 1 if gy > 0 else -1
            gear.beam((gx, sgn * 0.45, 0.45 if not low else wz), (gx, gy, cz), 0.09, 0.04, METAL if t.retractable else base)
            gear.cylinder((gx, gy - 0.08, cz), (gx, gy + 0.08, cz), r, DARK, segs=10)
            if not t.retractable:
                gear.box((gx, gy, cz - 0.03), (0.7, 0.2, 0.3), base)
    parts["gear"] = (gear.array(), (0, 0, 0), (0, 1, 0))

    # timón de profundidad / estabilizador
    el = MeshBuilder()
    if low:
        el.extrude([(-4.3, -1.65), (-4.3, 1.65), (-5.05, 1.65), (-5.05, -1.65)], "z", 0.04, base, offset=-0.18)
        parts["elevator"] = (el.array(), (-4.55, 0.0, -0.18), (0, 1, 0))
    else:
        el.extrude([(-4.95, -1.75), (-4.95, 1.75), (-5.35, 1.6), (-5.35, -1.6)], "z", 0.03, accent, offset=-0.27)
        parts["elevator"] = (el.array(), (-4.95, 0.0, -0.27), (0, 1, 0))
    ru = MeshBuilder()
    if low:
        ru.extrude([(-4.95, -0.2), (-5.05, -1.5), (-5.35, -1.45), (-5.35, -0.25)], "y", 0.04, accent)
        parts["rudder"] = (ru.array(), (-5.0, 0.0, -0.8), (0, 0, 1))
    else:
        ru.extrude([(-5.0, -0.32), (-5.15, -1.75), (-5.45, -1.7), (-5.45, -0.35)], "y", 0.04, accent)
        parts["rudder"] = (ru.array(), (-5.05, 0.0, -1.0), (math.sin(math.radians(6)), 0, 1))
    # alerones y flaps
    for side, sgn in (("l", -1), ("r", 1)):
        a = MeshBuilder()
        a.airfoil_panel(x_h, x_te + 0.08, sgn * 2.8, sgn * (span - 0.4), wz + 0.02, thick * 0.35, base, dih=dih)
        zc = wz - (abs(sgn * (span * 0.6))) * math.tan(dih)
        parts["ail_" + side] = (a.array(), (x_h, sgn * span * 0.6, zc), (0, 1, 0))
        f = MeshBuilder()
        f.airfoil_panel(x_h, x_te, sgn * 0.6, sgn * 2.7, wz + 0.02, thick * 0.4, base, dih=dih)
        zc = wz - (abs(sgn * 1.6)) * math.tan(dih)
        parts["flap_" + side] = (f.array(), (x_h, sgn * 1.6, zc), (0, 1, 0))
    # hélice
    pr = MeshBuilder()
    pr.cone((2.05, 0, 0.05), (2.42, 0, 0.05), 0.17, (0.85, 0.85, 0.85), segs=12)
    for sgn in (-1, 1):
        pr.beam((2.15, 0, 0.05), (2.15, 0, 0.05 + sgn * t.prop_radius), 0.12, 0.03, (0.12, 0.12, 0.12))
        pr.box((2.15, 0, 0.05 + sgn * (t.prop_radius - 0.06)), (0.035, 0.125, 0.12), (0.9, 0.85, 0.2))
    parts["prop"] = (pr.array(), (2.15, 0.0, 0.05), (1, 0, 0))
    disc = MeshBuilder()
    segs = 32
    for i in range(segs):
        a0 = 2 * math.pi * i / segs
        a1 = 2 * math.pi * (i + 1) / segs
        disc.tris([(2.17, 0, 0.05), (2.17, math.cos(a0) * t.prop_radius, 0.05 + math.sin(a0) * t.prop_radius),
                   (2.17, math.cos(a1) * t.prop_radius, 0.05 + math.sin(a1) * t.prop_radius)],
                  [(1, 0, 0)] * 3, [(0.25, 0.25, 0.25)])
    parts["disc"] = (disc.array(), (2.17, 0, 0.05), (1, 0, 0))
    parts["body"] = (mb.array(), (0, 0, 0), (0, 1, 0))
    tipz = wz - span * math.tan(dih)
    lights = dict(
        left=(0.3, -span, tipz), right=(0.3, span, tipz),
        tail=(-5.45, 0.0, -0.35 if not low else -0.25),
        beacon=(-5.0, 0.0, -1.8 if not low else -1.55),
        landing=(0.6, -2.2, wz + 0.05),
    )
    return parts, lights


def ring_template():
    mb = MeshBuilder()
    mb.torus(1.0, 0.06, (1, 1, 1), segs=40, sides=6)
    return mb.array()


# --------------------------------------------------------------- reactores de línea (tráfico)
JETS = {
    # longitud, radio del fuselaje, envergadura, altura del centro sobre el suelo
    "a320": dict(L=37.6, R=1.98, span=34.1, gear_h=3.6, eng_r=1.05, eng_y=5.75),
    "e190": dict(L=36.2, R=1.50, span=28.7, gear_h=3.0, eng_r=0.85, eng_y=4.9),
}


def jet_parts(kind, tail_col, stripe_col, base=WHITE):
    """Avión de línea sencillo (fuselaje, ala en flecha, motores bajo el ala, cola con los colores de la
    aerolínea). Ejes cuerpo: x adelante, y derecha, z abajo; el origen está a gear_h sobre el suelo."""
    J = JETS[kind]
    L, R, span, gh = J["L"], J["R"], J["span"], J["gear_h"]
    nose, tail = L * 0.48, -L * 0.52
    parts = {}
    mb = MeshBuilder()
    secs = [(nose, 0.12, 0.12, 0.35 * R), (nose - 0.6, R * 0.45, R * 0.42, 0.2 * R), (nose - 2.2, R * 0.85, R * 0.85, 0.05 * R),
            (nose - 4.5, R, R, 0.0), (tail + L * 0.30, R, R, 0.0), (tail + L * 0.17, R * 0.8, R * 0.85, -0.25 * R),
            (tail + L * 0.06, R * 0.4, R * 0.55, -0.6 * R), (tail, R * 0.12, R * 0.25, -0.85 * R)]

    def body_col(p):
        x, y, z = p
        if x > nose - 2.6 and z < -0.15 * R and abs(y) < R * 0.75:
            return GLASS                                    # ventanas de la cabina de mando
        if -0.45 * R < z < -0.25 * R and tail + L * 0.2 < x < nose - 3.5:
            return (0.25, 0.28, 0.33)                       # fila de ventanillas
        if 0.15 * R < z < 0.35 * R:
            return stripe_col                               # franja de la aerolínea
        return base
    mb.loft(secs, body_col, segs=20, power=0.9)
    # ala en flecha baja
    wz = R * 0.55
    root_le, root_te = L * 0.06, -L * 0.13
    sweep = math.tan(math.radians(25))
    y_tip = span / 2
    for sgn in (-1, 1):
        mb.airfoil_panel(root_le, root_te, sgn * R * 0.7, sgn * y_tip, wz, 0.45, base, dih=math.radians(5),
                         x_le1=root_le - y_tip * sweep, x_te1=root_le - y_tip * sweep - L * 0.05)
        # aleta (winglet)
        xt = root_le - y_tip * sweep
        mb.extrude([(xt, wz - 0.2), (xt - 1.8, wz - 0.2), (xt - 2.2, wz - 2.2), (xt - 1.4, wz - 2.2)], "y", 0.06, tail_col,
                   offset=sgn * y_tip)
        # motor bajo el ala
        ey = sgn * J["eng_y"]
        ex = root_le - J["eng_y"] * sweep + 1.6
        ez = wz + J["eng_r"] * 1.25
        mb.cylinder((ex, ey, ez), (ex - J["eng_r"] * 3.6, ey, ez), J["eng_r"], (0.82, 0.83, 0.85), segs=14)
        mb.cylinder((ex + 0.02, ey, ez), (ex + 0.03, ey, ez), J["eng_r"] * 0.8, DARK, segs=14)
        mb.beam((ex - 1.0, ey, wz + 0.1), (ex - 1.0, ey, ez - J["eng_r"] * 0.8), 0.6, 0.25, base)
    # estabilizador horizontal
    hx = tail + L * 0.1
    for sgn in (-1, 1):
        mb.airfoil_panel(hx, hx - L * 0.07, sgn * R * 0.3, sgn * span * 0.19, -0.3 * R, 0.25, base, dih=math.radians(6),
                         x_le1=hx - span * 0.19 * 0.55, x_te1=hx - span * 0.19 * 0.55 - L * 0.035)
    # deriva con los colores de la aerolínea
    vx = tail + L * 0.17
    vh = R * 3.2
    mb.extrude([(vx, -R * 0.8), (vx - L * 0.15, -R * 0.8), (tail + 0.4, -R * 0.8 - vh), (tail + L * 0.06, -R * 0.8 - vh)],
               "y", 0.18, tail_col)
    parts["body"] = (mb.array(), (0, 0, 0), (0, 1, 0))
    # tren
    gear = MeshBuilder()
    for gx, gy in ((nose - 4.0, 0.0), (-L * 0.05, -R * 1.9), (-L * 0.05, R * 1.9)):
        top = R * 0.6 if gy == 0 else wz
        gear.beam((gx, gy, top), (gx, gy, gh - 0.55), 0.25, 0.25, METAL)
        for dy in (-0.35, 0.35):
            gear.cylinder((gx, gy + dy - 0.15, gh - 0.55), (gx, gy + dy + 0.15, gh - 0.55), 0.55, DARK, segs=10)
    parts["gear"] = (gear.array(), (0, 0, 0), (0, 1, 0))
    xt = root_le - y_tip * sweep
    lights = dict(left=(xt, -y_tip, wz - y_tip * math.tan(math.radians(5))),
                  right=(xt, y_tip, wz - y_tip * math.tan(math.radians(5))),
                  tail=(tail, 0.0, -0.8 * R), beacon=(0.0, 0.0, -R - 0.2), landing=(root_le, -R * 1.2, wz))
    return parts, lights
