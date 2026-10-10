"""Modelos 3D de los Diamond DA40 NG y DA42 NG (ala baja, cola en T, cúpula de burbuja)."""
import math

import numpy as np

from .geometry import DARK, GLASS, METAL, MeshBuilder


def _prop(mb, x, y, z, radius, blades=3, col_blade=(0.1, 0.1, 0.1), spinner=(0.92, 0.92, 0.92)):
    mb.cone((x - 0.12, y, z), (x + 0.26, y, z), 0.16, spinner, segs=14)
    for k in range(blades):
        a = 2 * math.pi * k / blades
        dy, dz = math.cos(a), math.sin(a)
        tip = (x, y + dy * radius, z + dz * radius)
        mb.beam((x, y, z), tip, 0.11, 0.03, col_blade, up=(1, 0, 0))
        mb.beam((x, y + dy * (radius - 0.1), z + dz * (radius - 0.1)), tip, 0.115, 0.032, (0.92, 0.82, 0.15), up=(1, 0, 0))


def _disc(x, y, z, radius):
    mb = MeshBuilder()
    segs = 36
    for i in range(segs):
        a0 = 2 * math.pi * i / segs
        a1 = 2 * math.pi * (i + 1) / segs
        mb.tris([(x, y, z), (x, y + math.cos(a0) * radius, z + math.sin(a0) * radius),
                 (x, y + math.cos(a1) * radius, z + math.sin(a1) * radius)], [(1, 0, 0)] * 3, [(0.25, 0.25, 0.25)])
    return mb.array()


def diamond_parts(t):
    base, accent = t.paint
    twin = len(t.engines_y) > 1
    parts = {}
    if twin:
        secs = [(2.75, 0.06, 0.06, 0.12), (2.55, 0.25, 0.22, 0.12), (2.0, 0.45, 0.38, 0.08), (1.3, 0.55, 0.50, 0.02),
                (0.6, 0.60, 0.60, -0.05), (-0.3, 0.60, 0.60, -0.05), (-1.2, 0.48, 0.50, -0.05), (-2.6, 0.24, 0.32, -0.15),
                (-4.4, 0.11, 0.21, -0.25), (-5.45, 0.06, 0.14, -0.32)]
        glass_x = (-1.15, 1.25)
    else:
        secs = [(2.12, 0.30, 0.28, 0.12), (1.55, 0.50, 0.42, 0.10), (0.95, 0.56, 0.52, 0.02), (0.25, 0.58, 0.60, -0.05),
                (-0.6, 0.55, 0.58, -0.05), (-1.4, 0.40, 0.45, -0.05), (-2.8, 0.20, 0.30, -0.15),
                (-4.4, 0.10, 0.20, -0.25), (-5.3, 0.06, 0.14, -0.30)]
        glass_x = (-1.05, 0.95)

    def body_col(p):
        x, y, z = p
        if glass_x[0] < x < glass_x[1] and z < -0.12:
            return GLASS
        if 0.05 < z < 0.14 and x > -3.0:
            return accent
        return base

    mb = MeshBuilder()
    mb.loft(secs, body_col)
    cowl = MeshBuilder()
    # alas bajas con diedro y winglets
    wz, dih = 0.30, math.radians(5.0)
    span = t.b / 2
    x_le_r, x_te_r = 0.62, -0.78
    x_le_t, x_te_t = 0.38, -0.50
    x_h = lambda le, te: te + (le - te) * 0.25
    for sgn in (-1, 1):
        # parte fija (borde de ataque hasta la bisagra)
        mb.airfoil_panel(x_le_r, x_h(x_le_r, x_te_r), sgn * 0.5, sgn * span * 0.98, wz, 0.17, base, dih=dih,
                         x_le1=x_le_t, x_te1=x_h(x_le_t, x_te_t))
        tipz = wz - span * math.tan(dih)
        mb.extrude([(x_le_t - 0.05, tipz), (x_te_t + 0.05, tipz), (x_te_t, tipz - 0.42), (x_le_t - 0.25, tipz - 0.12)],
                   "y", 0.02, accent, offset=sgn * span)
    # cola en T
    mb.extrude([(-3.9, -0.35), (-4.95, -1.55), (-5.4, -1.55), (-5.15, -0.3)], "y", 0.05, base)
    mb.extrude([(-4.95, -0.18), (-4.95, 0.18), (-5.32, 1.6), (-5.32, -1.6)], "z", 0.035, base, offset=-1.62)
    # góndolas (DA42) o capó (DA40)
    if twin:
        for yy in t.engines_y:
            nsec = [(1.30, 0.10, 0.10, 0.02), (1.15, 0.27, 0.27, 0.04), (0.6, 0.31, 0.32, 0.08),
                    (-0.6, 0.28, 0.30, 0.10), (-1.3, 0.10, 0.12, 0.08)]
            nac = MeshBuilder()
            nac.loft([(x, hw, hh, zc) for x, hw, hh, zc in nsec], lambda p: base, segs=14)
            arr = nac.array()
            arr[:, 1] += yy
            mb.add(arr)
            cowl.add(arr)
    else:
        cowl.loft(secs[:2], lambda p: base)
    parts["cowl"] = (cowl.array(), (0, 0, 0), (0, 1, 0))
    # tren
    gear = MeshBuilder()
    for g in t.gears:
        gx, gy, gz = g.pos
        r = 0.20 if g.name != "nariz" else 0.17
        cz = gz - r
        if g.name == "nariz":
            gear.beam((gx, 0, 0.30), (gx, 0, cz), 0.07, 0.07, METAL)
            gear.cylinder((gx, -0.07, cz), (gx, 0.07, cz), r, DARK, segs=10)
            if not t.retractable:
                gear.box((gx, 0, cz - 0.03), (0.62, 0.18, 0.30), base)
        else:
            top = (gx, gy * 0.65 if not twin else gy, wz + 0.05)
            gear.beam(top, (gx, gy, cz), 0.08, 0.06, METAL if t.retractable else base)
            gear.cylinder((gx, gy - 0.08, cz), (gx, gy + 0.08, cz), r, DARK, segs=10)
            if not t.retractable:
                gear.box((gx, gy, cz - 0.03), (0.72, 0.2, 0.32), base)
    parts["gear"] = (gear.array(), (0, 0, 0), (0, 1, 0))
    # superficies móviles
    el = MeshBuilder()
    el.extrude([(-5.32, -1.6), (-5.32, 1.6), (-5.68, 1.5), (-5.68, -1.5)], "z", 0.025, accent, offset=-1.62)
    parts["elevator"] = (el.array(), (-5.32, 0.0, -1.62), (0, 1, 0))
    ru = MeshBuilder()
    ru.extrude([(-5.15, -0.3), (-5.4, -1.52), (-5.72, -1.46), (-5.62, -0.35)], "y", 0.04, accent)
    parts["rudder"] = (ru.array(), (-5.2, 0.0, -0.9), (math.sin(math.radians(12)), 0, 1))
    for side, sgn in (("l", -1), ("r", 1)):
        a = MeshBuilder()
        y0, y1 = span * 0.55, span * 0.95
        f0 = 1 - y0 / span
        f1 = 1 - y1 / span
        xh0 = x_h(x_le_r, x_te_r) * f0 + x_h(x_le_t, x_te_t) * (1 - f0)
        xt0 = x_te_r * f0 + x_te_t * (1 - f0)
        xh1 = x_h(x_le_r, x_te_r) * f1 + x_h(x_le_t, x_te_t) * (1 - f1)
        xt1 = x_te_r * f1 + x_te_t * (1 - f1)
        a.airfoil_panel(xh0, xt0, sgn * y0, sgn * y1, wz + 0.02, 0.06, base, dih=dih, x_le1=xh1, x_te1=xt1)
        zc = wz - (span * 0.75) * math.tan(dih)
        parts["ail_" + side] = (a.array(), ((xh0 + xh1) / 2, sgn * span * 0.75, zc), (0, 1, 0))
        f = MeshBuilder()
        y0, y1 = 0.6, span * 0.54
        f0, f1 = 1 - y0 / span, 1 - y1 / span
        xh0 = x_h(x_le_r, x_te_r) * f0 + x_h(x_le_t, x_te_t) * (1 - f0)
        xt0 = x_te_r * f0 + x_te_t * (1 - f0)
        xh1 = x_h(x_le_r, x_te_r) * f1 + x_h(x_le_t, x_te_t) * (1 - f1)
        xt1 = x_te_r * f1 + x_te_t * (1 - f1)
        f.airfoil_panel(xh0, xt0, sgn * y0, sgn * y1, wz + 0.02, 0.07, base, dih=dih, x_le1=xh1, x_te1=xt1)
        zc = wz - ((y0 + y1) / 2) * math.tan(dih)
        parts["flap_" + side] = (f.array(), ((xh0 + xh1) / 2, sgn * (y0 + y1) / 2, zc), (0, 1, 0))
    # hélices
    if twin:
        for i, yy in enumerate(t.engines_y):
            pr = MeshBuilder()
            _prop(pr, 1.35, yy, 0.02, t.prop_radius)
            key = "prop" if i == 0 else "prop2"
            dkey = "disc" if i == 0 else "disc2"
            parts[key] = (pr.array(), (1.35, yy, 0.02), (1, 0, 0))
            parts[dkey] = (_disc(1.38, yy, 0.02, t.prop_radius), (1.38, yy, 0.02), (1, 0, 0))
    else:
        pr = MeshBuilder()
        _prop(pr, 2.2, 0.0, 0.12, t.prop_radius)
        parts["prop"] = (pr.array(), (2.2, 0.0, 0.12), (1, 0, 0))
        parts["disc"] = (_disc(2.23, 0.0, 0.12, t.prop_radius), (2.23, 0.0, 0.12), (1, 0, 0))
    parts["body"] = (mb.array(), (0, 0, 0), (0, 1, 0))
    tipz = wz - span * math.tan(dih)
    lights = dict(left=(0.25, -span, tipz - 0.1), right=(0.25, span, tipz - 0.1), tail=(-5.7, 0.0, -1.6),
                  beacon=(-5.2, 0.0, -1.68), landing=(0.55, -2.2, wz + 0.05))
    return parts, lights
