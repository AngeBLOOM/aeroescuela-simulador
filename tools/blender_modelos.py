"""Modela en Blender los edificios del aeródromo, hornea su luz y los exporta al simulador.

Se ejecuta DENTRO de Blender (lo llama tools/modelos_edificios.py):

    blender --background --factory-startup --python tools/blender_modelos.py -- pedido.json carpeta_salida

pedido.json: lista de {"key": "hangar_45x34x11", "kind": "hangar", "p": {...}, "size": 1024, "samples": 256}.

Cada modelo se arma con piezas sólidas (cajas con bisel, cilindros) y ventanas o vanos recortados con operaciones
booleanas, con su marco y el vidrio hundido: así cada borde agarra la luz. Ejes del modelo: X a lo largo, Y a lo
ancho (el frente mira a -Y), Z arriba, origen en el suelo al centro. Luego:
  - coordenadas de textura en metros (proyección por cara, según el material: la chapa a 4 m, el concreto a 6 m);
  - mapa de luz: desplegado propio y horneado con Cycles de la luz del cielo con rebotes (sin Sol: el simulador
    pone el Sol y sus sombras en cada cuadro) y la penumbra en el suelo alrededor;
  - exporta <key>.npz: por material, triángulos con posición (x adelante, y, z abajo), normal, uv, uv del mapa de
    luz; el mapa de luz (luz / 1,6 en 8 bits), la penumbra del suelo y su rectángulo.
"""
import json
import math
import os
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index("--") + 1:]
SPEC, OUT = argv[0], argv[1]
LIGHT_SCALE = 1.6

# albedo de cada material (para los rebotes de luz) y tamaño de su textura en metros
MATS = {
    "wall": ((0.85, 0.85, 0.83), 4.0), "roof": ((0.66, 0.68, 0.7), 4.0), "trim": ((0.14, 0.3, 0.56), 1.0),
    "steel": ((0.78, 0.8, 0.82), 1.0), "door": ((0.82, 0.83, 0.84), 4.0), "glass": ((0.08, 0.1, 0.12), 1.0),
    "frame": ((0.22, 0.23, 0.25), 1.0), "gutter": ((0.8, 0.81, 0.82), 1.0), "plinth": ((0.6, 0.6, 0.58), 2.0),
    "interior": ((0.42, 0.43, 0.45), 4.0), "interiorfloor": ((0.5, 0.5, 0.48), 6.0),
    "skylight": ((0.78, 0.82, 0.84), 1.0), "lamp": ((0.95, 0.93, 0.85), 1.0), "office": ((0.92, 0.91, 0.88), 3.0),
    "doorpers": ((0.16, 0.32, 0.58), 2.0), "ac": ((0.8, 0.8, 0.78), 1.0), "concrete": ((0.62, 0.62, 0.6), 6.0),
    "tower": ((0.9, 0.89, 0.86), 6.0), "towerglass": ((0.2, 0.3, 0.33), 1.0), "railing": ((0.75, 0.76, 0.78), 1.0),
    "roofdeck": ((0.42, 0.42, 0.4), 4.0), "red": ((0.7, 0.12, 0.1), 1.0), "white": ((0.9, 0.9, 0.88), 1.0),
    "tank": ((0.88, 0.88, 0.86), 2.0), "canopy": ((0.86, 0.86, 0.84), 2.0), "pump": ((0.75, 0.2, 0.15), 1.0),
    "brick": ((0.6, 0.38, 0.3), 2.0), "steelin": ((0.38, 0.4, 0.43), 1.0), "yellow": ((0.95, 0.75, 0.1), 1.0),
    "tile": ((0.6, 0.3, 0.2), 2.0), "housewall": ((0.85, 0.8, 0.7), 3.0), "slab": ((0.55, 0.55, 0.53), 6.0),
    "tinaco": ((0.1, 0.1, 0.11), 1.0), "woodoor": ((0.4, 0.25, 0.15), 1.0), "fence": ((0.35, 0.37, 0.38), 1.0),
}
NOBAKE = {"towerglass"}             # transparentes: no tapan la luz ni llevan mapa de luz
# el interior del hangar queda en penumbra fija (no gasta mapa de luz: así sobra resolución para el exterior)
NOLM = {"interiorfloor", "steelin"}

scene = None
parts = []                          # objetos del modelo en curso


# ============================================================ escena y materiales
def reset():
    global scene, parts
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.use_denoising = False
    scene.cycles.max_bounces = 4
    scene.cycles.diffuse_bounces = 3
    w = bpy.data.worlds.new("cielo")
    scene.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (1.0, 1.0, 1.0, 1.0)
    bg.inputs[1].default_value = 1.0
    parts = []


def material(name):
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        p = m.node_tree.nodes["Principled BSDF"]
        p.inputs["Base Color"].default_value = (*MATS[name][0], 1.0)
        p.inputs["Roughness"].default_value = 1.0
    return m


def obj_from_bm(bm, mat, bevel=0.0, name="pieza"):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    scene.collection.objects.link(ob)
    ob.data.materials.append(material(mat))
    if bevel > 0:
        md = ob.modifiers.new("bisel", "BEVEL")
        md.width = bevel
        md.segments = 2
        md.limit_method = "ANGLE"
    parts.append(ob)
    return ob


# ============================================================ primitivas
def box(mat, p0, p1, bevel=0.0):
    """Caja alineada entre dos esquinas (x, y, z)."""
    lo = [min(a, b) for a, b in zip(p0, p1)]
    hi = [max(a, b) for a, b in zip(p0, p1)]
    if min(h - l for h, l in zip(hi, lo)) < 1e-4:
        return None
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    c = [(a + b) / 2 for a, b in zip(lo, hi)]
    s = [b - a for a, b in zip(lo, hi)]
    bmesh.ops.transform(bm, matrix=Matrix.Translation(c) @ Matrix.Diagonal((*s, 1.0)), verts=bm.verts)
    return obj_from_bm(bm, mat, min(bevel, 0.45 * min(s)))


def beam(mat, p0, p1, w, h, bevel=0.0):
    """Viga de sección w x h entre dos puntos."""
    p0, p1 = Vector(p0), Vector(p1)
    ax = p1 - p0
    L = ax.length
    if L < 1e-4:
        return None
    ax.normalize()
    up = Vector((0, 0, 1)) if abs(ax.z) < 0.95 else Vector((1, 0, 0))
    side = ax.cross(up).normalized()
    upv = ax.cross(side).normalized()                 # (side, upv, ax) de mano derecha: no espeja la caja
    M = Matrix((side, upv, ax)).transposed().to_4x4()
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.transform(bm, matrix=Matrix.Translation((p0 + p1) / 2) @ M @ Matrix.Diagonal((w, h, L, 1.0)),
                        verts=bm.verts)
    return obj_from_bm(bm, mat, min(bevel, 0.45 * min(w, h)))


def cyl(mat, p0, p1, r, segs=10):
    p0, p1 = Vector(p0), Vector(p1)
    ax = p1 - p0
    L = ax.length
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=segs, radius1=r, radius2=r, depth=L)
    rot = ax.to_track_quat("Z", "Y").to_matrix().to_4x4()
    bmesh.ops.transform(bm, matrix=Matrix.Translation((p0 + p1) / 2) @ rot, verts=bm.verts)
    ob = obj_from_bm(bm, mat)
    for f in ob.data.polygons:
        f.use_smooth = True
    return ob


def prism(mat, poly, z0, z1, bevel=0.0):
    """Prisma vertical: polígono (x, y) entre las alturas z0 y z1."""
    bm = bmesh.new()
    vs = [bm.verts.new((x, y, z0)) for x, y in poly]
    f = bm.faces.new(vs)
    if f.normal.z > 0:
        f.normal_flip()
    r = bmesh.ops.extrude_face_region(bm, geom=[f])
    top = [e for e in r["geom"] if isinstance(e, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, vec=(0, 0, z1 - z0), verts=top)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return obj_from_bm(bm, mat, bevel)


def slab_xz(mat, poly_xz, y0, y1, bevel=0.0):
    """Placa vertical: polígono en el plano (x, z) entre y0 e y1 (paredes con hastial)."""
    bm = bmesh.new()
    vs = [bm.verts.new((x, y0, z)) for x, z in poly_xz]
    f = bm.faces.new(vs)
    r = bmesh.ops.extrude_face_region(bm, geom=[f])
    top = [e for e in r["geom"] if isinstance(e, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, vec=(0, y1 - y0, 0), verts=top)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return obj_from_bm(bm, mat, bevel)


def slab_yz(mat, poly_yz, x0, x1, bevel=0.0):
    bm = bmesh.new()
    vs = [bm.verts.new((x0, y, z)) for y, z in poly_yz]
    f = bm.faces.new(vs)
    r = bmesh.ops.extrude_face_region(bm, geom=[f])
    top = [e for e in r["geom"] if isinstance(e, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, vec=(x1 - x0, 0, 0), verts=top)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return obj_from_bm(bm, mat, bevel)


def cut(ob, cutters):
    """Resta cajas (vanos de puertas y ventanas) a una pieza con booleanas exactas."""
    if ob is None or not cutters:
        return
    for i, (p0, p1) in enumerate(cutters):
        lo = [min(a, b) for a, b in zip(p0, p1)]
        hi = [max(a, b) for a, b in zip(p0, p1)]
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        c = [(a + b) / 2 for a, b in zip(lo, hi)]
        s = [b - a for a, b in zip(lo, hi)]
        bmesh.ops.transform(bm, matrix=Matrix.Translation(c) @ Matrix.Diagonal((*s, 1.0)), verts=bm.verts)
        me = bpy.data.meshes.new("corte")
        bm.to_mesh(me)
        bm.free()
        co = bpy.data.objects.new("corte", me)
        scene.collection.objects.link(co)
        md = ob.modifiers.new(f"corte{i}", "BOOLEAN")
        md.operation = "DIFFERENCE"
        md.solver = "EXACT"
        md.object = co
        co.hide_render = True
        co["cutter"] = True


def window(axis, at, u0, u1, z0, z1, depth, frame=0.07, mullion=True, light=False):
    """Ventana en una pared perpendicular a 'axis' ('x' o 'y') en la coordenada 'at' (cara exterior), entre u0-u1
    a lo largo de la pared y z0-z1 de alto: devuelve el corte para la pared y agrega el marco y el vidrio hundido."""
    s = 1.0 if depth > 0 else -1.0                   # hacia dónde está el interior
    d = abs(depth)

    def P(u, w, z):
        return (w, u, z) if axis == "x" else (u, w, z)
    glass_w = at + s * d * 0.55
    box("glass", P(u0, glass_w - 0.01, z0), P(u1, glass_w + 0.01, z1))
    f = frame
    if not light:                                    # marco completo (en las casas basta el vano y el alféizar)
        for (a0, a1, b0, b1) in ((u0 - f, u1 + f, z0 - f, z0), (u0 - f, u1 + f, z1, z1 + f),
                                 (u0 - f, u0, z0, z1), (u1, u1 + f, z0, z1)):
            box("frame", P(a0, at - s * 0.03, b0), P(a1, at + s * d * 0.6, b1))
    if mullion and (u1 - u0) > 1.1:
        m = (u0 + u1) / 2
        box("frame", P(m - 0.03, glass_w - 0.03, z0), P(m + 0.03, glass_w + 0.03, z1))
    box("frame", P(u0 - f - 0.03, at - s * 0.08, z0 - f - 0.05), P(u1 + f + 0.03, at + s * 0.02, z0 - f))   # alféizar
    return (P(u0, at - s * 0.2, z0), P(u1, at + s * (d + 0.2), z1))


# ============================================================ modelos
def hangar(p):
    ln, wd, ht = p["ln"], p["wd"], p["ht"]
    a, b = ln / 2, wd / 2
    rise = max(1.6, wd * 0.085)
    ov = 0.7
    t = 0.14                                         # espesor de pared
    P0 = 0.4
    dx = 0.8 * a
    dh = min(0.78 * ht, ht - 1.6)
    # zócalo de concreto
    box("plinth", (-a - 0.05, b - 0.25, 0), (a + 0.05, b + 0.05, P0), 0.02)
    box("plinth", (-a - 0.05, -b - 0.05, 0), (-dx, -b + 0.25, P0), 0.02)
    box("plinth", (dx, -b - 0.05, 0), (a + 0.05, -b + 0.25, P0), 0.02)
    box("plinth", (a - 0.25, -b, 0), (a + 0.05, b, P0), 0.02)
    box("plinth", (-a - 0.05, -b, 0), (-a + 0.25, b, P0), 0.02)
    # paredes de chapa (con su espesor: por dentro se ve la cara interior)
    back = box("wall", (-a, b - t, P0), (a, b, ht))
    # ventanas altas corridas en la pared trasera (luz natural adentro)
    nwin = max(3, int(ln // 6.5))
    cut(back, [window("y", b, -a + (i + 0.5) * ln / nwin - 1.4, -a + (i + 0.5) * ln / nwin + 1.4,
                      ht - 2.6, ht - 1.6, -t) for i in range(nwin)])
    front_l = box("wall", (-a, -b, P0), (-dx - 0.7, -b + t, ht))
    front_r = box("wall", (dx + 0.7, -b, P0), (a, -b + t, ht))
    box("wall", (-dx - 0.7, -b, dh + 0.9), (dx + 0.7, -b + t, ht))
    sides = []
    for sx in (-1, 1):
        x0, x1 = (sx * a - t, sx * a) if sx > 0 else (sx * a, sx * a + t)
        sides.append(slab_yz("wall", [(-b, P0), (b, P0), (b, ht), (0, ht + rise), (-b, ht)], x0, x1))
    # ventanas altas en el hastial -X y puerta de personas
    cut(sides[0], [window("x", -a, wy - 0.9, wy + 0.9, 2.8, 3.8, t) for wy in (b * 0.15, b * 0.6)] +
        [((-a - 0.2, -b * 0.4 - 0.5, 0.0), (-a + t + 0.2, -b * 0.4 + 0.5, 2.2))])
    box("doorpers", (-a + 0.02, -b * 0.4 - 0.5, 0.02), (-a + 0.08, -b * 0.4 + 0.5, 2.18))
    for (u0, u1, z0, z1) in ((-b * 0.4 - 0.58, -b * 0.4 - 0.5, 0, 2.26), (-b * 0.4 + 0.5, -b * 0.4 + 0.58, 0, 2.26),
                             (-b * 0.4 - 0.58, -b * 0.4 + 0.58, 2.18, 2.26)):
        box("frame", (-a - 0.03, u0, z0), (-a + 0.05, u1, z1))
    box("trim", (-a - 1.0, -b * 0.4 - 0.9, 2.5), (-a, -b * 0.4 + 0.9, 2.6), 0.02)     # alero de la puerta
    box("lamp", (-a - 0.14, -b * 0.4 - 0.15, 2.28), (-a, -b * 0.4 + 0.15, 2.42), 0.02)
    # interior: piso, columnas y cerchas
    box("interiorfloor", (-a + t, -b + t, 0.0), (a - t, b - t, 0.04))
    nb = max(3, int(ln / 7.5))
    for i in range(1, nb):
        x = -a + ln * i / nb
        for sy in (-1, 1):
            y0 = sy * (b - t - 0.2)
            box("steelin", (x - 0.15, y0 - 0.15, 0), (x + 0.15, y0 + 0.15, ht - 0.25))
            beam("steelin", (x, y0, ht - 0.2), (x, 0, ht + rise - 0.35), 0.18, 0.4)
            beam("steelin", (x, y0, ht - 1.3), (x, 0, ht - 1.3), 0.14, 0.14)
            for k in (0.25, 0.5, 0.75):              # montantes entre cordón inferior y par
                yk = y0 * (1 - k)
                beam("steelin", (x, yk, ht - 1.3), (x, yk, ht - 0.2 + (rise - 0.15) * k), 0.08, 0.08)
    # techo: faldones con espesor, cumbrera, frontis, cielo del alero, canaletas y bajantes
    slope = rise / b
    he = ht - ov * slope
    for sy in (-1, 1):
        ye = sy * (b + ov)
        roof = slab_yz("roof", [(ye, he), (0, ht + rise + 0.05), (0, ht + rise + 0.17), (ye, he + 0.12)][::sy], -a - 0.5, a + 0.5)
        for k in range(int(ln // 9)):            # claraboyas
            x0 = -a + 4.5 + k * 9.0 - 0.6
            for tt0, tt1 in ((0.25, 0.8),):
                y0, y1 = ye * (1 - tt0), ye * (1 - tt1)
                z0 = he + (ht + rise + 0.05 - he) * tt0 + 0.13
                z1 = he + (ht + rise + 0.05 - he) * tt1 + 0.13
                slab_yz("skylight", [(y0, z0), (y1, z1), (y1, z1 + 0.04), (y0, z0 + 0.04)][::sy], x0, x0 + 1.2)
        box("trim", (-a - 0.5, ye - sy * 0.0, he - 0.3), (a + 0.5, ye + sy * 0.04, he + 0.12))          # frontis
        g0 = ye + sy * 0.04
        gut = box("gutter", (-a - 0.5, g0, he - 0.38), (a + 0.5, g0 + sy * 0.22, he - 0.12), 0.02)
        for sx in (-1, 1):
            px = sx * (a + 0.2)
            cyl("gutter", (px, g0 + sy * 0.1, he - 0.3), (px, g0 + sy * 0.1, 0.25), 0.055, 8)
            cyl("gutter", (px, g0 + sy * 0.1, 0.3), (px, g0 + sy * 0.4, 0.08), 0.055, 8)
        slab_yz("trim", [(sy * b, ht), (ye, he), (ye, he + 0.02), (sy * b, ht + 0.02)][::sy], -a - 0.5, a + 0.5)   # cielo del alero
    for sx in (-1, 1):                               # frontis del hastial (sigue la pendiente)
        x0 = sx * (a + 0.5)
        for sy in (-1, 1):
            ye = sy * (b + ov)
            slab_yz("trim", [(ye, he - 0.3), (0, ht + rise - 0.25), (0, ht + rise + 0.18), (ye, he + 0.13)][::sy],
                    min(x0, x0 + sx * 0.05), max(x0, x0 + sx * 0.05))
    box("trim", (-a - 0.55, -0.3, ht + rise + 0.1), (a + 0.55, 0.3, ht + rise + 0.26), 0.03)    # cumbrera
    # esquineros
    for sx in (-1, 1):
        for sy in (-1, 1):
            xa, xb = (a - 0.08, a + 0.04) if sx > 0 else (-a - 0.04, -a + 0.08)
            ya, yb = (b - 0.08, b + 0.04) if sy > 0 else (-b - 0.04, -b + 0.08)
            box("trim", (xa, ya, P0), (xb, yb, ht), 0.01)
    # portón: viga, rieles, jambas y hojas
    box("steel", (-dx - 0.7, -b - 0.45, dh), (dx + 0.7, -b + t, dh + 0.9), 0.03)
    box("trim", (-dx - 0.7, -b - 0.72, dh + 0.05), (dx + 0.7, -b - 0.45, dh + 0.3), 0.02)
    box("steel", (-dx - 0.5, -b - 0.75, 0.0), (dx + 0.5, -b - 0.1, 0.03))
    for px in (-dx - 0.35, dx + 0.35):
        box("steel", (px - 0.35, -b - 0.45, 0.0), (px + 0.35, -b + t, dh), 0.03)
    nl = max(4, 2 * int(round(dx / 5.5)))
    leaf = 2 * dx / nl
    gap = nl // 2 - 1
    for k in range(nl):
        if k == gap:
            continue
        p0 = -dx + k * leaf
        off = -0.62 if k == gap - 1 else (-0.22 if k % 2 == 0 else -0.45)
        y0 = -b + off
        lf = box("door", (p0 + 0.02, y0 - 0.06, 0.05), (p0 + leaf - 0.02, y0 + 0.06, dh - 0.02), 0.02)
        nw = max(2, int(leaf / 1.6))
        z0, z1 = dh * 0.66, dh * 0.8
        cuts = []
        for i in range(nw):
            w0 = p0 + leaf * (i + 0.15) / nw
            w1 = p0 + leaf * (i + 0.85) / nw
            cuts.append(((w0, y0 - 0.2, z0), (w1, y0 + 0.2, z1)))
            box("glass", (w0, y0 - 0.01, z0), (w1, y0 + 0.01, z1))
            for (a0, a1, b0, b1) in ((w0 - 0.05, w1 + 0.05, z0 - 0.05, z0), (w0 - 0.05, w1 + 0.05, z1, z1 + 0.05),
                                     (w0 - 0.05, w0, z0, z1), (w1, w1 + 0.05, z0, z1)):
                box("frame", (a0, y0 - 0.09, b0), (a1, y0 + 0.09, b1))
        cut(lf, cuts)
        for hh in np.arange(1.25, dh * 0.62, 1.25):  # refuerzos horizontales
            box("trim", (p0 + 0.1, y0 - 0.1, hh), (p0 + leaf - 0.1, y0 - 0.05, hh + 0.09), 0.015)
        for pe in (p0 + 0.02, p0 + leaf - 0.12):     # largueros
            box("trim", (pe, y0 - 0.1, 0.05), (pe + 0.1, y0 + 0.08, dh - 0.02), 0.015)
        box("trim", (p0 + 0.1, y0 - 0.09, 0.05), (p0 + leaf - 0.1, y0 - 0.05, 0.6), 0.01)        # zócalo
        box("steel", (p0 + 0.3, y0 - 0.25, dh - 0.12), (p0 + 0.6, y0, dh + 0.05))                # carros
        box("steel", (p0 + leaf - 0.6, y0 - 0.25, dh - 0.12), (p0 + leaf - 0.3, y0, dh + 0.05))
    # bolardos amarillos a los lados del portón y gabinete del extintor
    for sx in (-1, 1):
        for k in range(2):
            px = sx * (dx + 1.2 + k * 1.4)
            cyl("yellow", (px, -b - 1.6, 0.0), (px, -b - 1.6, 1.0), 0.11, 10)
            cyl("trim", (px, -b - 1.6, 1.0), (px, -b - 1.6, 1.06), 0.12, 10)
    box("red", (-dx - 1.6, -b - 0.18, 1.1), (-dx - 1.0, -b, 1.9), 0.02)
    box("white", (-dx - 1.52, -b - 0.19, 1.2), (-dx - 1.08, -b - 0.17, 1.8))
    # extractores eólicos sobre la cumbrera
    for k in range(max(2, int(ln // 15))):
        px = -a + (k + 0.5) * ln / max(2, int(ln // 15))
        cyl("steel", (px, 0.0, ht + rise + 0.2), (px, 0.0, ht + rise + 0.6), 0.18, 10)
        cyl("gutter", (px, 0.0, ht + rise + 0.6), (px, 0.0, ht + rise + 1.0), 0.32, 14)
        cyl("steel", (px, 0.0, ht + rise + 1.0), (px, 0.0, ht + rise + 1.08), 0.34, 14)
    # reflectores sobre la viga
    for px in (-dx * 0.6, 0.0, dx * 0.6):
        beam("steel", (px, -b - 0.45, dh + 1.15), (px, -b - 1.0, dh + 1.15), 0.06, 0.06)
        box("lamp", (px - 0.3, -b - 1.15, dh + 0.98), (px + 0.3, -b - 0.85, dh + 1.2), 0.02)
    # respaldo del letrero (el texto lo pone el simulador)
    sw = min(0.55 * ln, 22.0)
    sh = min(1.6, ht - dh - 1.2)
    if sh > 0.6:
        box("trim", (-sw / 2 - 0.1, -b - 0.04, dh + 0.95), (sw / 2 + 0.1, -b, dh + 1.15 + sh), 0.01)
    # oficina anexa sobre el hastial +X
    ow, od, oh = min(14.0, wd * 0.55), 5.0, 3.4
    oy0 = -b + 1.5
    ox0, ox1 = a, a + od
    off = box("office", (ox0 - 0.1, oy0, 0.0), (ox1, oy0 + ow, oh), 0.02)
    wins = []
    for i in range(int(ow // 2.6)):
        w0 = oy0 + 0.9 + i * 2.6
        wins.append(window("x", ox1, w0, w0 + 1.5, 1.0, 2.3, -0.25))
    wins.append(((ox0 + 1.5, oy0 - 0.2, 0.0), (ox0 + 2.5, oy0 + 0.3, 2.2)))
    cut(off, wins)
    box("doorpers", (ox0 + 1.5, oy0 + 0.1, 0.02), (ox0 + 2.5, oy0 + 0.16, 2.18))
    box("trim", (ox0 + 1.1, oy0 - 1.2, 2.5), (ox0 + 2.9, oy0, 2.6), 0.02)
    box("lamp", (ox0 + 1.85, oy0 - 0.14, 2.3), (ox0 + 2.15, oy0, 2.45), 0.02)
    box("trim", (ox0 - 0.1, oy0 - 0.08, oh), (ox1 + 0.08, oy0 + ow + 0.08, oh + 0.4), 0.02)       # pretil
    box("roofdeck", (ox0, oy0, oh), (ox1, oy0 + ow, oh + 0.05))
    box("plinth", (ox0, oy0 - 0.04, 0.0), (ox1 + 0.04, oy0 + ow + 0.04, 0.35), 0.01)
    for i in range(2):                               # aires acondicionados
        py0 = oy0 + ow
        px0 = ox0 + 1.0 + i * 2.2
        box("ac", (px0, py0, 0.4), (px0 + 0.9, py0 + 0.38, 1.0), 0.03)
        for g in range(5):
            box("trim", (px0 + 0.1 + g * 0.15, py0 + 0.38, 0.5), (px0 + 0.16 + g * 0.15, py0 + 0.4, 0.9))
        cyl("steel", (px0 + 0.45, py0, 0.7), (px0 + 0.45, py0 - 0.1, 0.7), 0.03, 6)
    box("ac", (ox0 + 2.0, oy0 + ow * 0.4, oh + 0.05), (ox0 + 3.4, oy0 + ow * 0.4 + 1.2, oh + 0.8), 0.04)
    # losa de concreto delante del portón
    box("concrete", (-a - 2, -b - 16, 0.0), (a + 2, -b, 0.06))
    return dict(grect_margin=max(12.0, 1.4 * ht))


def tower(p):
    """Torre de control: edificio de operaciones al pie, fuste de concreto con ventanas de escalera, piso técnico,
    cabina octogonal de vidrio inclinado con parteluces, pasarela con baranda, techo con alero, antenas y faro."""
    H = p["h"]
    # edificio de operaciones (2 plantas) al pie
    bw, bd, bh = 14.0, 8.0, 6.6
    ob = box("office", (-bw / 2, -bd / 2 - 3.0, 0.0), (bw / 2, bd / 2 - 3.0, bh), 0.03)
    wins = []
    for fl, (z0, z1) in enumerate(((1.0, 2.4), (4.2, 5.6))):
        for i in range(5):
            u0 = -bw / 2 + 1.0 + i * 2.6
            wins.append(window("y", -bd / 2 - 3.0, u0, u0 + 1.6, z0, z1, 0.3))
    wins.append(((-1.0, -bd / 2 - 3.3, 0.0), (1.0, -bd / 2 - 2.5, 2.5)))
    cut(ob, wins)
    box("glass", (-1.0, -bd / 2 - 2.9, 0.02), (1.0, -bd / 2 - 2.86, 2.4))
    box("frame", (-0.04, -bd / 2 - 2.95, 0.0), (0.04, -bd / 2 - 2.8, 2.4))
    box("canopy", (-2.2, -bd / 2 - 5.2, 2.9), (2.2, -bd / 2 - 3.0, 3.1), 0.03)
    for px in (-2.0, 2.0):
        cyl("steel", (px, -bd / 2 - 5.0, 0.0), (px, -bd / 2 - 5.0, 2.9), 0.08, 8)
    box("trim", (-bw / 2 - 0.1, -bd / 2 - 3.1, bh), (bw / 2 + 0.1, bd / 2 - 2.9, bh + 0.5), 0.02)
    box("trim", (-bw / 2 - 0.05, -bd / 2 - 3.05, 3.15), (bw / 2 + 0.05, bd / 2 - 2.95, 3.45), 0.02)   # franja azul
    box("roofdeck", (-bw / 2, -bd / 2 - 3.0, bh), (bw / 2, bd / 2 - 3.0, bh + 0.08))
    box("plinth", (-bw / 2 - 0.04, -bd / 2 - 3.04, 0), (bw / 2 + 0.04, bd / 2 - 2.96, 0.4), 0.01)
    for i in range(3):
        box("ac", (-bw / 2 + 2 + i * 3, 0.0, bh + 0.08), (-bw / 2 + 3.2 + i * 3, 1.0, bh + 0.8), 0.04)
    # fuste: octógono de concreto con una franja de ventanas de la escalera
    r0 = 3.2
    octo = [(r0 * math.cos(math.pi / 8 + k * math.pi / 4), r0 * math.sin(math.pi / 8 + k * math.pi / 4)) for k in range(8)]
    sh = prism("tower", octo, 0.0, H - 1.2, 0.03)
    stairs = [(( -0.5, -r0 - 0.3, z), (0.5, -r0 + 0.4, z + 1.4)) for z in np.arange(bh + 1.5, H - 2.5, 3.2)]
    cut(sh, stairs)
    for (p0, p1) in stairs:
        box("glass", (p0[0], -r0 * math.cos(math.pi / 8) + 0.25, p0[2]), (p1[0], -r0 * math.cos(math.pi / 8) + 0.27, p1[2]))
    # piso técnico con persianas y losa de la pasarela
    prism("tower", [(x * 1.35, y * 1.35) for x, y in octo], H - 1.2, H + 0.6, 0.04)
    for k in range(8):
        a0 = math.pi / 8 + k * math.pi / 4
        a1 = a0 + math.pi / 4
        for z in np.arange(H - 1.0, H + 0.45, 0.22):
            p0 = (r0 * 1.35 * math.cos(a0) * 1.005, r0 * 1.35 * math.sin(a0) * 1.005, z)
            p1 = (r0 * 1.35 * math.cos(a1) * 1.005, r0 * 1.35 * math.sin(a1) * 1.005, z)
            beam("trim", p0, p1, 0.04, 0.06)
    deck = [(x * 1.85, y * 1.85) for x, y in octo]
    prism("trim", deck, H + 0.6, H + 0.85, 0.03)
    # baranda de la pasarela
    for k in range(8):
        a0 = math.pi / 8 + k * math.pi / 4
        a1 = a0 + math.pi / 4
        R = r0 * 1.8
        p0 = (R * math.cos(a0), R * math.sin(a0))
        p1 = (R * math.cos(a1), R * math.sin(a1))
        for z in (H + 1.35, H + 1.85):
            beam("railing", (*p0, z), (*p1, z), 0.05, 0.05)
        for j in range(5):
            t_ = j / 5
            q = (p0[0] + (p1[0] - p0[0]) * t_, p0[1] + (p1[1] - p0[1]) * t_)
            cyl("railing", (*q, H + 0.85), (*q, H + 1.88), 0.025, 6)
    # cabina: zócalo, vidrios inclinados hacia afuera con parteluces, techo con alero
    c0, c1, top = H + 0.85, H + 1.6, H + 4.6
    prism("tower", [(x * 1.45, y * 1.45) for x, y in octo], c0, c1, 0.03)
    rb, rt = r0 * 1.45, r0 * 1.62
    for k in range(8):
        a0 = math.pi / 8 + k * math.pi / 4
        a1 = a0 + math.pi / 4
        q = [(rb * math.cos(a0), rb * math.sin(a0), c1), (rb * math.cos(a1), rb * math.sin(a1), c1),
             (rt * math.cos(a1), rt * math.sin(a1), top), (rt * math.cos(a0), rt * math.sin(a0), top)]
        bm = bmesh.new()
        vs = [bm.verts.new(v) for v in q]
        bm.faces.new(vs)
        obj_from_bm(bm, "towerglass", name="vidrio")
        beam("frame", (rb * math.cos(a0), rb * math.sin(a0), c1), (rt * math.cos(a0), rt * math.sin(a0), top), 0.12, 0.12)
    prism("trim", [(x * 1.7, y * 1.7) for x, y in octo], top, top + 0.25, 0.03)
    prism("roofdeck", [(x * 1.95, y * 1.95) for x, y in octo], top + 0.25, top + 0.55, 0.04)
    # antenas y faro
    cyl("steel", (1.0, 1.0, top + 0.55), (1.0, 1.0, top + 5.0), 0.05, 8)
    cyl("steel", (-1.2, 0.6, top + 0.55), (-1.2, 0.6, top + 3.0), 0.04, 8)
    for z in (top + 1.5, top + 2.5):
        beam("steel", (-1.2, 0.0, z), (-1.2, 1.2, z), 0.03, 0.03)
    cyl("steel", (0.0, -1.0, top + 0.55), (0.0, -1.0, top + 1.3), 0.1, 8)
    cyl("lamp", (0.0, -1.0, top + 1.3), (0.0, -1.0, top + 1.75), 0.28, 12)
    box("concrete", (-bw / 2 - 2, -bd / 2 - 9.0, 0.0), (bw / 2 + 2, -bd / 2 - 3.0, 0.06))
    return dict(grect_margin=16.0)


def fuel(p):
    """Estación de combustible de la plataforma: tanque horizontal en su cuna con escalera, isla de surtidores con
    techo, barrera de protección y cartel."""
    # tanque (cilindro horizontal) en su cuna de concreto
    cyl("tank", (-4.5, 6.0, 1.9), (4.5, 6.0, 1.9), 1.45, 20)
    for x in (-3.0, 3.0):
        box("plinth", (x - 0.4, 4.6, 0.0), (x + 0.4, 7.4, 0.9), 0.03)
    for k, x in enumerate(np.linspace(-4.0, 4.0, 5)):
        box("red", (x - 0.03, 4.53, 1.3), (x + 0.03, 4.56, 2.5))
    box("concrete", (-6.0, 3.5, 0.0), (6.0, 8.5, 0.2), 0.03)                      # cubeto
    for (x0, y0, x1, y1) in ((-6.0, 3.5, 6.0, 3.7), (-6.0, 8.3, 6.0, 8.5), (-6.0, 3.5, -5.8, 8.5), (5.8, 3.5, 6.0, 8.5)):
        box("plinth", (x0, y0, 0.0), (x1, y1, 0.8), 0.02)
    for z in np.arange(0.4, 3.4, 0.35):                                         # escalera
        box("steel", (4.6, 5.6, z), (5.0, 6.4, z + 0.04))
    beam("steel", (4.6, 5.6, 0.2), (4.6, 5.6, 3.6), 0.05, 0.05)
    beam("steel", (4.6, 6.4, 0.2), (4.6, 6.4, 3.6), 0.05, 0.05)
    cyl("steel", (0.0, 6.0, 3.3), (0.0, 6.0, 3.8), 0.18, 10)
    # isla de surtidores con techo
    box("concrete", (-3.0, -1.2, 0.0), (3.0, 1.2, 0.2), 0.05)
    for x in (-1.3, 1.3):
        box("pump", (x - 0.45, -0.3, 0.2), (x + 0.45, 0.3, 1.8), 0.04)
        box("glass", (x - 0.3, -0.31, 1.1), (x + 0.3, -0.29, 1.6))
        cyl("trim", (x + 0.5, -0.1, 1.2), (x + 0.5, -0.1, 0.4), 0.03, 6)
    for x in (-3.4, 3.4):
        cyl("steel", (x, 0.0, 0.0), (x, 0.0, 4.6), 0.12, 10)
    box("canopy", (-4.5, -2.5, 4.6), (4.5, 2.5, 5.2), 0.05)
    box("red", (-4.52, -2.52, 4.75), (4.52, 2.52, 5.05))
    for x in (-2.5, 0.0, 2.5):
        box("lamp", (x - 0.4, -0.3, 4.52), (x + 0.4, 0.3, 4.6))
    for x in (-3.0, 3.0):                                                       # barreras
        cyl("red", (x, -1.6, 0.0), (x, -1.6, 1.0), 0.08, 8)
        cyl("red", (x, 1.6, 0.0), (x, 1.6, 1.0), 0.08, 8)
    box("concrete", (-8.0, -5.0, 0.0), (8.0, 9.5, 0.05))
    return dict(grect_margin=10.0)


def _prueba(p):
    box("concrete", (-10, -10, 0.0), (10, 10, 0.06))
    box("wall", (-3, -3, 0.06), (3, 3, 5.0))
    return dict(grect_margin=8.0)


BUILDERS = {"hangar": hangar, "torre": tower, "combustible": fuel, "prueba": _prueba}


# ============================================================ casas y edificios de los pueblos
def gable_roof(x0, x1, y0, y1, zw, rise, ov=0.5, mat="tile", along="x"):
    """Techo a dos aguas con cumbrera a lo largo de 'along', aleros de ov m y hastiales de pared."""
    if along == "x":
        yc = (y0 + y1) / 2
        half = (y1 - y0) / 2
        slope = rise / half
        for sy in (-1, 1):
            ye = yc + sy * (half + ov)
            ze = zw - ov * slope
            poly = [(ye, ze), (yc, zw + rise), (yc, zw + rise + 0.12), (ye, ze + 0.12)]
            slab_yz(mat, poly[::sy], x0 - ov, x1 + ov)
        for xe, x_in in ((x0, x0 + 0.2), (x1 - 0.2, x1)):
            slab_yz("housewall", [(y0, zw), (y1, zw), (yc, zw + rise)], xe, x_in)
        box("tile", (x0 - ov, yc - 0.14, zw + rise + 0.05), (x1 + ov, yc + 0.14, zw + rise + 0.24))   # caballete
    else:
        xc = (x0 + x1) / 2
        half = (x1 - x0) / 2
        slope = rise / half
        for sx in (-1, 1):
            xe = xc + sx * (half + ov)
            ze = zw - ov * slope
            poly = [(xe, ze), (xc, zw + rise), (xc, zw + rise + 0.12), (xe, ze + 0.12)]
            slab_xz(mat, poly[::-sx], y0 - ov, y1 + ov)
        for ye, y_in in ((y0, y0 + 0.2), (y1 - 0.2, y1)):
            slab_xz("housewall", [(x0, zw), (x1, zw), (xc, zw + rise)][::-1], ye, y_in)
        box("tile", (xc - 0.14, y0 - ov, zw + rise + 0.05), (xc + 0.14, y1 + ov, zw + rise + 0.24))


def hip_roof(x0, x1, y0, y1, zw, rise, ov=0.6, mat="tile"):
    """Techo a cuatro aguas (con espesor) sobre el rectángulo, con alero."""
    X0, X1, Y0, Y1 = x0 - ov, x1 + ov, y0 - ov, y1 + ov
    w, d = X1 - X0, Y1 - Y0
    slope = rise / (min(w, d) / 2 - ov)
    ze = zw - ov * slope
    zr = ze + slope * min(w, d) / 2
    if w >= d:
        r0, r1 = (X0 + d / 2, (Y0 + Y1) / 2), (X1 - d / 2, (Y0 + Y1) / 2)
    else:
        r0, r1 = ((X0 + X1) / 2, Y0 + w / 2), ((X0 + X1) / 2, Y1 - w / 2)
    bm = bmesh.new()
    a = bm.verts.new((X0, Y0, ze)); b = bm.verts.new((X1, Y0, ze))
    c = bm.verts.new((X1, Y1, ze)); dd = bm.verts.new((X0, Y1, ze))
    p = bm.verts.new((*r0, zr)); q = bm.verts.new((*r1, zr))
    if w >= d:
        faces = [(a, b, q, p), (c, dd, p, q), (b, c, q), (dd, a, p)]
    else:
        faces = [(b, c, q, p), (dd, a, p, q), (a, b, p), (c, dd, q)]
    for f in faces:
        bm.faces.new(f)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    ob = obj_from_bm(bm, mat)
    md = ob.modifiers.new("espesor", "SOLIDIFY")
    md.thickness = 0.12
    md.offset = 1.0
    box("housewall", (x0, y0, zw - 0.05), (x1, y1, zw + 0.05))
    return ob


def house_windows(x0, x1, y0, y1, z0, z1, front, back, sides, door=None, depth=0.18, frame=0.06):
    """Cortes de ventanas (y puerta) en un bloque de casa: devuelve la lista de cortes y agrega marcos y vidrios."""
    cuts = []
    W = 1.1

    def spread(a, b, n):
        if n <= 0:
            return []
        step = (b - a) / n
        return [a + step * (i + 0.5) for i in range(n)]
    for (at, u0, u1, n, ax, dsg) in ((y0, x0, x1, front, "y", 1), (y1, x0, x1, back, "y", -1),
                                      (x0, y0, y1, sides, "x", 1), (x1, y0, y1, sides, "x", -1)):
        cs = spread(u0 + 0.8, u1 - 0.8, n)
        for c in cs:
            if door is not None and ax == "y" and dsg == 1 and abs(c - door) < 1.4:
                continue
            cuts.append(window(ax, at, c - W / 2, c + W / 2, z0, z1, dsg * depth, frame, mullion=False, light=True))
    if door is not None:
        cuts.append(((door - 0.5, y0 - 0.2, 0.25), (door + 0.5, y0 + 0.3, 2.3)))
        box("woodoor", (door - 0.5, y0 + 0.12, 0.25), (door + 0.5, y0 + 0.17, 2.28))
        for (a0, a1, b0, b1) in ((door - 0.58, door - 0.5, 0.25, 2.36), (door + 0.5, door + 0.58, 0.25, 2.36),
                                 (door - 0.58, door + 0.58, 2.28, 2.36)):
            box("frame", (a0, y0 - 0.02, b0), (a1, y0 + 0.14, b1))
    return cuts


def casa_a(p):
    """Casa de una planta, techo de teja a dos aguas, puerta con alerito y aire acondicionado."""
    x0, x1, y0, y1, h = -5.0, 5.0, -4.0, 4.0, 3.0
    box("plinth", (x0 - 0.05, y0 - 0.05, 0), (x1 + 0.05, y1 + 0.05, 0.3))
    body = box("housewall", (x0, y0, 0.25), (x1, y1, h))
    cut(body, house_windows(x0, x1, y0, y1, 1.0, 2.2, 3, 2, 1, door=0.0))
    gable_roof(x0, x1, y0, y1, h, 1.9, 0.5)
    box("tile", (-1.0, y0 - 1.0, 2.55), (1.0, y0, 2.65))                  # alerito de la puerta
    box("ac", (x1, 1.0, 1.6), (x1 + 0.3, 1.8, 2.2), 0.02)
    box("plinth", (-0.8, y0 - 1.0, 0), (0.8, y0, 0.2))                    # escalón
    return dict(grect_margin=5.0)


def casa_b(p):
    """Casa con techo de teja a cuatro aguas y corredor al frente con columnas."""
    x0, x1, y0, y1, h = -6.0, 6.0, -4.5, 4.5, 3.0
    box("plinth", (x0 - 0.05, y0 - 2.6, 0), (x1 + 0.05, y1 + 0.05, 0.3))
    body = box("housewall", (x0, y0, 0.25), (x1, y1, h))
    cut(body, house_windows(x0, x1, y0, y1, 1.0, 2.2, 4, 3, 2, door=-1.4))
    hip_roof(x0, x1, y0, y1, h, 2.0, 0.6)
    # corredor: techo de teja en pendiente sobre columnas blancas
    slab_yz("tile", [(y0, h - 0.1), (y0 - 2.6, h - 0.65), (y0 - 2.6, h - 0.53), (y0, h + 0.02)], x0 - 0.2, x1 + 0.2)
    for xc in np.linspace(x0 + 0.3, x1 - 0.3, 4):
        cyl("white", (xc, y0 - 2.3, 0.3), (xc, y0 - 2.3, h - 0.6), 0.12, 10)
    for xc in np.linspace(x0 + 0.3, x1 - 0.3, 4)[:-1]:
        beam("railing", (xc + 0.1, y0 - 2.3, 0.9), (xc + 3.7, y0 - 2.3, 0.9), 0.05, 0.05)
    return dict(grect_margin=5.0)


def casa_c(p):
    """Casa de dos plantas con platabanda: balcón con baranda al frente, pretil y tanque de agua en el techo."""
    x0, x1, y0, y1, h = -4.5, 4.5, -4.0, 4.0, 6.2
    box("plinth", (x0 - 0.05, y0 - 0.05, 0), (x1 + 0.05, y1 + 0.05, 0.3))
    body = box("housewall", (x0, y0, 0.25), (x1, y1, h))
    cuts = house_windows(x0, x1, y0, y1, 1.0, 2.2, 2, 2, 1, door=1.8)
    cuts += house_windows(x0, x1, y0, y1, 4.1, 5.3, 2, 2, 1)
    cut(body, cuts)
    box("slab", (x0 - 0.3, y0 - 1.3, 3.1), (x1 + 0.3, y0, 3.3), 0.02)         # losa del balcón
    for z in (3.9, 4.3):
        beam("railing", (x0 - 0.25, y0 - 1.25, z), (x1 + 0.25, y0 - 1.25, z), 0.05, 0.05)
    for xc in np.linspace(x0 - 0.25, x1 + 0.25, 10):
        beam("railing", (xc, y0 - 1.25, 3.3), (xc, y0 - 1.25, 4.3), 0.035, 0.035)
    box("housewall", (x0 - 0.05, y0 - 0.05, h), (x1 + 0.05, y1 + 0.05, h + 0.7))      # pretil
    box("slab", (x0 + 0.15, y0 + 0.15, h), (x1 - 0.15, y1 - 0.15, h + 0.75))
    for xx, yy in ((x0 + 0.8, y1 - 0.8), (x1 - 0.8, y1 - 0.8)):
        for dx_ in (-0.3, 0.3):
            beam("steel", (xx + dx_, yy, h + 0.75), (xx + dx_, yy, h + 1.5), 0.06, 0.06)
    cyl("tinaco", (x0 + 0.8, y1 - 0.8, h + 1.5), (x0 + 0.8, y1 - 0.8, h + 2.6), 0.6, 14)
    box("ac", (x1, -1.0, 4.4), (x1 + 0.3, -0.2, 5.0), 0.02)
    return dict(grect_margin=6.0)


def casa_d(p):
    """Casa en L de una planta: dos alas con techos de teja a dos aguas cruzados."""
    box("plinth", (-5.05, -3.55, 0), (5.05, 3.55, 0.3))
    box("plinth", (1.95, 3.45, 0), (5.05, 8.05, 0.3))
    a = box("housewall", (-5.0, -3.5, 0.25), (5.0, 3.5, 3.0))
    cut(a, house_windows(-5.0, 5.0, -3.5, 3.5, 1.0, 2.2, 3, 2, 1, door=-2.0))
    b = box("housewall", (2.0, 3.5, 0.25), (5.0, 8.0, 3.0))
    cut(b, house_windows(2.0, 5.0, 3.5, 8.0, 1.0, 2.2, 0, 1, 1))
    gable_roof(-5.0, 5.0, -3.5, 3.5, 3.0, 1.8, 0.5)
    gable_roof(2.0, 5.0, 3.5, 8.0, 3.0, 1.3, 0.45, along="y")
    box("ac", (-5.3, 0.5, 1.6), (-5.0, 1.3, 2.2), 0.02)
    return dict(grect_margin=5.0)


def bloque(p):
    """Edificio de apartamentos de p['pisos'] pisos: ventanas en cada piso, balcones con baranda al frente,
    pretil, tanques de agua, sala de máquinas y alero de la entrada."""
    n = p["pisos"]
    w, d = p["w"], p["d"]
    x0, x1, y0, y1 = -w / 2, w / 2, -d / 2, d / 2
    fh = 3.1
    h = n * fh + 0.4
    box("plinth", (x0 - 0.05, y0 - 0.05, 0), (x1 + 0.05, y1 + 0.05, 0.4))
    body = box("housewall", (x0, y0, 0.35), (x1, y1, h))
    cuts = []
    nf = max(3, int(w // 3.2))
    ns = max(2, int(d // 3.4))
    for k in range(n):
        z0 = 1.0 + k * fh
        cuts += house_windows(x0, x1, y0, y1, z0, z0 + 1.35, nf, nf, ns, door=(0.0 if k == 0 else None))
        if 0 < k:                                    # balcones al frente en pisos altos
            for i in range(0, nf, 2):
                cx = x0 + 0.8 + (w - 1.6) / nf * (i + 0.5)
                box("slab", (cx - 1.0, y0 - 1.0, z0 - 0.75), (cx + 1.0, y0, z0 - 0.6))
                beam("railing", (cx - 0.97, y0 - 0.97, z0 + 0.2), (cx + 0.97, y0 - 0.97, z0 + 0.2), 0.05, 0.05)
                for xx in np.linspace(cx - 0.97, cx + 0.97, 6):
                    beam("railing", (xx, y0 - 0.97, z0 - 0.6), (xx, y0 - 0.97, z0 + 0.2), 0.03, 0.03)
        if k > 0:                                    # cornisa entre pisos
            box("white", (x0 - 0.04, y0 - 0.04, k * fh + 0.25), (x1 + 0.04, y1 + 0.04, k * fh + 0.4))
    cut(body, cuts)
    box("housewall", (x0 - 0.05, y0 - 0.05, h), (x1 + 0.05, y1 + 0.05, h + 0.9))
    box("slab", (x0 + 0.2, y0 + 0.2, h), (x1 - 0.2, y1 - 0.2, h + 0.95))
    box("housewall", (x1 - 4.5, y1 - 4.5, h + 0.95), (x1 - 1.0, y1 - 1.0, h + 3.4), 0.03)   # sala de máquinas
    for i in range(2):
        cyl("tinaco", (x0 + 1.5 + i * 1.6, y1 - 1.5, h + 0.95), (x0 + 1.5 + i * 1.6, y1 - 1.5, h + 2.2), 0.65, 14)
    for i in range(3):
        box("ac", (x0 + 1.0 + i * 1.6, y0 + 1.0, h + 0.95), (x0 + 2.2 + i * 1.6, y0 + 2.0, h + 1.7), 0.03)
    box("canopy", (-2.0, y0 - 2.0, 2.8), (2.0, y0, 3.0), 0.03)
    return dict(grect_margin=8.0)


def luminaria(p):
    """Luz de borde elevada (tipo L-861): base, pata frangible amarilla, cabezal y domo (luce de noche)."""
    cyl("steel", (0, 0, 0.0), (0, 0, 0.03), 0.09, 12)
    cyl("steel", (0, 0, 0.03), (0, 0, 0.07), 0.035, 10)
    cyl("yellow", (0, 0, 0.07), (0, 0, 0.27), 0.022, 10)
    cyl("steel", (0, 0, 0.27), (0, 0, 0.33), 0.06, 12)
    cyl("lamp", (0, 0, 0.33), (0, 0, 0.39), 0.052, 12)
    return dict(grect_margin=0.5)


def papi(p):
    """Caja de un PAPI: carcasa sobre cuatro patas regulables con tres lentes hacia la aproximación (-y)."""
    box("concrete", (-0.8, -0.6, 0.0), (0.8, 0.6, 0.1), 0.02)
    for x in (-0.45, 0.45):
        for y in (-0.15, 0.15):
            cyl("steel", (x, y, 0.1), (x, y, 0.45), 0.025, 8)
    box("white", (-0.6, -0.3, 0.45), (0.6, 0.3, 0.9), 0.04)
    box("white", (-0.62, -0.42, 0.85), (0.62, 0.3, 0.92), 0.02)                 # visera
    for x in (-0.35, 0.0, 0.35):
        cyl("lamp", (x, -0.3, 0.66), (x, -0.34, 0.66), 0.1, 14)
    return dict(grect_margin=1.0)


def manga(p):
    """Mástil de la manga de viento: base de concreto, mástil con franjas rojas y blancas, soporte giratorio arriba
    (la manga la mueve el simulador), dos reflectores para la noche y luz roja de obstáculo en la punta."""
    box("concrete", (-0.8, -0.8, 0.0), (0.8, 0.8, 0.25), 0.03)
    cyl("steel", (0, 0, 0.25), (0, 0, 0.45), 0.16, 12)
    for k in range(7):
        cyl("red" if k % 2 == 0 else "white", (0, 0, 0.45 + k * 0.9), (0, 0, 0.45 + (k + 1) * 0.9), 0.075, 12)
    cyl("steel", (0, 0, 6.75), (0, 0, 7.0), 0.11, 12)                             # rodamiento del giro
    cyl("steel", (0, 0, 7.0), (0, 0, 7.25), 0.05, 8)
    cyl("lamp", (0, 0, 7.25), (0, 0, 7.42), 0.07, 10)                             # luz de obstáculo
    for a in (0.0, math.pi):                                                     # reflectores
        x, y = 0.6 * math.cos(a), 0.6 * math.sin(a)
        beam("steel", (0, 0, 5.2), (x, y, 5.2), 0.05, 0.05)
        box("lamp", (x - 0.12, y - 0.12, 5.1), (x + 0.12, y + 0.12, 5.35), 0.02)
    return dict(grect_margin=2.0)


def valla(p):
    """Tramo de 3 m de cerca perimetral: postes galvanizados, malla (franja oscura translúcida al ojo) y tres
    hilos de alambre de púas en el brazo inclinado de arriba."""
    for x in (-1.5, 1.5):
        cyl("steel", (x, 0, 0.0), (x, 0, 2.1), 0.035, 8)
        beam("steel", (x, 0, 2.1), (x, -0.32, 2.45), 0.03, 0.03)
    beam("steel", (-1.5, 0, 2.05), (1.5, 0, 2.05), 0.03, 0.03)
    beam("steel", (-1.5, 0, 0.1), (1.5, 0, 0.1), 0.02, 0.02)
    box("fence", (-1.5, -0.005, 0.1), (1.5, 0.005, 2.05))
    for k in range(3):
        t = (k + 1) / 3.5
        beam("steel", (-1.5, -0.32 * t, 2.1 + 0.35 * t), (1.5, -0.32 * t, 2.1 + 0.35 * t), 0.008, 0.008)
    return dict(grect_margin=1.0)


def terminal(p):
    """Edificio de la escuela de vuelo y operaciones (34 x 22 m, dos plantas): planta baja con frente de vidrio
    hacia la plataforma (-y) y entrada con marquesina, planta alta con ventanas corridas y balcón mirador con baranda,
    franjas azules, aires y tanques en la azotea."""
    x0, x1, y0, y1 = -17.0, 17.0, -11.0, 11.0
    h1, h2 = 3.6, 7.0
    box("plinth", (x0 - 0.05, y0 - 0.05, 0.0), (x1 + 0.05, y1 + 0.05, 0.4), 0.02)
    body = box("office", (x0, y0, 0.35), (x1, y1, h2), 0.03)
    cuts = []
    # planta baja: vidriera hacia la plataforma con parteluces
    cuts.append(((x0 + 2.0, y0 - 0.3, 0.45), (x1 - 2.0, y0 + 0.5, 3.0)))
    box("glass", (x0 + 2.0, y0 + 0.2, 0.45), (x1 - 2.0, y0 + 0.24, 3.0))
    for xm in np.arange(x0 + 2.0, x1 - 1.9, 2.5):
        box("frame", (xm - 0.05, y0 + 0.1, 0.45), (xm + 0.05, y0 + 0.3, 3.0))
    box("frame", (x0 + 2.0, y0 + 0.1, 2.95), (x1 - 2.0, y0 + 0.3, 3.05))
    # planta alta: ventanas corridas en el frente y en los costados
    for k in range(9):
        u = x0 + 1.8 + k * 3.6
        cuts.append(window("y", y0, u, u + 2.4, 4.3, 6.0, 0.3))
    for k in range(5):
        v = y0 + 2.0 + k * 3.8
        cuts.append(window("x", x0, v, v + 2.0, 4.3, 6.0, 0.3))
        cuts.append(window("x", x1, v, v + 2.0, 4.3, 6.0, -0.3))
        cuts.append(window("x", x0, v, v + 2.0, 1.0, 2.6, 0.3))
        cuts.append(window("x", x1, v, v + 2.0, 1.0, 2.6, -0.3))
    cut(body, cuts)
    # marquesina de la entrada y balcón mirador con baranda
    box("canopy", (-4.0, y0 - 3.5, 3.2), (4.0, y0, 3.45), 0.04)
    for xx in (-3.7, 3.7):
        cyl("steel", (xx, y0 - 3.2, 0.0), (xx, y0 - 3.2, 3.2), 0.1, 10)
    box("slab", (x0 + 1.0, y0 - 1.6, 3.6), (x1 - 1.0, y0, 3.8), 0.02)
    for z in (4.4, 4.75):
        beam("railing", (x0 + 1.05, y0 - 1.55, z), (x1 - 1.05, y0 - 1.55, z), 0.05, 0.05)
    for xx in np.linspace(x0 + 1.05, x1 - 1.05, 24):
        beam("railing", (xx, y0 - 1.55, 3.8), (xx, y0 - 1.55, 4.75), 0.035, 0.035)
    # franjas azules y pretil
    box("trim", (x0 - 0.04, y0 - 0.04, 3.55), (x1 + 0.04, y1 + 0.04, 3.85), 0.01)
    for (a0, b0, a1, b1) in ((x0 - 0.06, y0 - 0.06, x1 + 0.06, y0 + 0.2), (x0 - 0.06, y1 - 0.2, x1 + 0.06, y1 + 0.06),
                             (x0 - 0.06, y0 - 0.06, x0 + 0.2, y1 + 0.06), (x1 - 0.2, y0 - 0.06, x1 + 0.06, y1 + 0.06)):
        box("trim", (a0, b0, h2), (a1, b1, h2 + 0.55), 0.02)               # pretil (solo el borde)
    box("roofdeck", (x0 + 0.1, y0 + 0.1, h2), (x1 - 0.1, y1 - 0.1, h2 + 0.08))
    for k in range(4):
        box("ac", (x0 + 3 + k * 4.0, y1 - 3.0, h2 + 0.08), (x0 + 4.4 + k * 4.0, y1 - 1.8, h2 + 0.85), 0.04)
    for k in range(2):
        cyl("tinaco", (x1 - 2.5 - k * 1.7, y1 - 2.5, h2 + 0.08), (x1 - 2.5 - k * 1.7, y1 - 2.5, h2 + 1.4), 0.65, 14)
    cyl("steel", (x1 - 1.0, y0 + 1.0, h2), (x1 - 1.0, y0 + 1.0, h2 + 6.0), 0.05, 8)     # antena de radio
    box("lamp", (-0.4, y0 - 3.2, 3.05), (0.4, y0 - 2.9, 3.2))
    box("concrete", (x0 - 4.0, y0 - 6.0, 0.0), (x1 + 4.0, y0, 0.06))
    return dict(grect_margin=10.0)


BUILDERS.update({"terminal": terminal, "valla": valla, "manga": manga, "luminaria": luminaria, "papi": papi, "casa_a": casa_a, "casa_b": casa_b, "casa_c": casa_c, "casa_d": casa_d, "bloque": bloque})


# ============================================================ árboles (plantillas para el dibujo por instancias)
# Se arman con mallas (tronco, ramas, copa de masas irregulares) y se exportan en el formato de las plantillas de
# árboles del simulador: altura 1, z hacia abajo, 9 floats por vértice (posición, normal, color). El color lleva la
# oclusión ambiental calculada con rayos (el interior de la copa y la cara de abajo, más oscuros) y las normales de
# la copa son "esféricas" (desde el centro de cada masa) para que el follaje se ilumine suave, sin facetas.
TREE_PARTS = []                     # (bmesh, color, centro de copa o None)


def _tree_reset():
    TREE_PARTS.clear()


def _tcyl(p0, p1, r0, r1, col, segs=7):
    p0, p1 = Vector(p0), Vector(p1)
    ax = p1 - p0
    L = ax.length
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=False, segments=segs, radius1=r0, radius2=r1, depth=L)
    rot = ax.to_track_quat("Z", "Y").to_matrix().to_4x4()
    bmesh.ops.transform(bm, matrix=Matrix.Translation((p0 + p1) / 2) @ rot, verts=bm.verts)
    TREE_PARTS.append((bm, col, None))


def _blob(c, r, col, sub=1, flat=1.0, seed=0, jit=0.18):
    """Masa de follaje: icoesfera deformada al azar (más chata con flat < 1)."""
    rng = np.random.default_rng(seed)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=sub, radius=1.0)
    for v in bm.verts:
        k = 1.0 + rng.uniform(-jit, jit)
        v.co = Vector((v.co.x * r * k, v.co.y * r * k, v.co.z * r * k * flat)) + Vector(c)
    TREE_PARTS.append((bm, col, Vector(c)))


def _cone(zb, zt, r, col, segs=9, seed=0):
    """Piso de conífera: cono con el borde algo caído e irregular."""
    rng = np.random.default_rng(seed)
    bm = bmesh.new()
    tip = bm.verts.new((0, 0, zt))
    ring = []
    for i in range(segs):
        a = 2 * math.pi * i / segs + rng.uniform(-0.12, 0.12)
        rr = r * rng.uniform(0.85, 1.1)
        ring.append(bm.verts.new((rr * math.cos(a), rr * math.sin(a), zb - rng.uniform(0.0, 0.05))))
    for i in range(segs):
        bm.faces.new((ring[i], ring[(i + 1) % segs], tip))
    bm.faces.new(ring[::-1])
    TREE_PARTS.append((bm, col, Vector((0, 0, (zb + zt) / 2))))


def _frond(base, ang, length, col, droop=0.55, n=7, w=0.09):
    """Hoja de palma: tira que sale del cogollo y se curva hacia abajo, con folíolos en zigzag."""
    bm = bmesh.new()
    d = Vector((math.cos(ang), math.sin(ang), 0.0))
    side = Vector((-d.y, d.x, 0.0))
    pts = []
    for i in range(n + 1):
        t = i / n
        p = Vector(base) + d * length * t + Vector((0, 0, length * (0.35 * t - droop * t * t)))
        pts.append(p)
    prev = None
    for i, p in enumerate(pts):
        ww = w * math.sin(math.pi * min(1.0, (i + 0.5) / n)) * (1.6 if i % 2 else 1.0)
        a, b = bm.verts.new(p - side * ww), bm.verts.new(p + side * ww)
        if prev is not None:
            bm.faces.new((prev[0], prev[1], b, a))
        prev = (a, b)
    TREE_PARTS.append((bm, col, Vector(base) + d * length * 0.5))


def pino(p):
    _tcyl((0, 0, -0.02), (0, 0, 0.35), 0.035, 0.02, (0.3, 0.22, 0.15))
    tiers = [(0.12, 0.47, 0.37), (0.28, 0.63, 0.31), (0.44, 0.78, 0.25), (0.58, 0.9, 0.18), (0.72, 1.0, 0.11)]
    for k, (zb, zt, r) in enumerate(tiers):
        g = 0.15 + 0.02 * k
        _cone(zb, zt, r, (g * 0.75, g * 1.7, g * 0.7), seed=k)


def frondoso(p):
    bark = (0.32, 0.24, 0.16)
    _tcyl((0, 0, -0.02), (0, 0, 0.42), 0.05, 0.035, bark)
    for (x, y, z) in ((0.14, 0.06, 0.55), (-0.12, -0.08, 0.57), (0.02, 0.14, 0.6)):
        _tcyl((0, 0, 0.32), (x, y, z), 0.025, 0.012, bark, segs=5)
    leaf = (0.17, 0.32, 0.12)
    for k, (c, r, sub) in enumerate((((0.0, 0.0, 0.68), 0.3, 2), ((0.17, 0.08, 0.6), 0.22, 2),
                                     ((-0.16, -0.08, 0.6), 0.22, 2), ((0.02, -0.15, 0.82), 0.19, 1),
                                     ((-0.05, 0.15, 0.8), 0.19, 1), ((0.1, -0.02, 0.88), 0.15, 1))):
        _blob(c, r, tuple(x * (0.9 + 0.08 * k) for x in leaf), sub, seed=k)


def saman(p):
    """Samán: tronco corto y grueso, ramas que se abren y copa ancha como paraguas (el árbol de los llanos)."""
    bark = (0.3, 0.23, 0.17)
    _tcyl((0, 0, -0.02), (0, 0, 0.3), 0.07, 0.055, bark)
    for a in np.linspace(0, 2 * math.pi, 5, endpoint=False):
        _tcyl((0, 0, 0.26), (0.38 * math.cos(a), 0.38 * math.sin(a), 0.55), 0.035, 0.018, bark, segs=5)
    leaf = (0.16, 0.3, 0.1)
    rng = np.random.default_rng(7)
    _blob((0, 0, 0.72), 0.55, leaf, 2, flat=0.42, seed=1, jit=0.12)
    for k, a in enumerate(np.linspace(0, 2 * math.pi, 6, endpoint=False)):
        c = (0.5 * math.cos(a), 0.5 * math.sin(a), 0.64 + rng.uniform(-0.04, 0.05))
        _blob(c, 0.3, tuple(x * (0.92 + 0.05 * (k % 3)) for x in leaf), 1, flat=0.55, seed=k + 3)


def palma(p):
    """Palma: tronco anillado algo curvo, cogollo y una corona de hojas arqueadas."""
    bark = (0.45, 0.4, 0.33)
    pts = [Vector((0.0, 0.0, 0.0))]
    for i in range(1, 7):
        t = i / 6
        pts.append(Vector((0.06 * t * t, 0.0, 0.82 * t)))
    for i in range(6):
        _tcyl(pts[i], pts[i + 1], 0.045 - 0.004 * i, 0.04 - 0.004 * i, tuple(c * (0.9 + 0.1 * (i % 2)) for c in bark), 7)
    top = pts[-1]
    _blob((top.x, 0.0, top.z + 0.02), 0.05, (0.2, 0.3, 0.12), 1, seed=9)
    leaf = (0.2, 0.38, 0.12)
    for k, a in enumerate(np.linspace(0, 2 * math.pi, 11, endpoint=False)):
        _frond((top.x, 0.0, top.z + 0.03), a + 0.2 * (k % 2), 0.48 + 0.06 * (k % 3), leaf,
               droop=0.75 + 0.25 * (k % 2))


TREES = {"pino": pino, "frondoso": frondoso, "saman": saman, "palma": palma}


def build_tree(name):
    """Junta las piezas, calcula la oclusión por vértice con rayos y devuelve (N, 9) en el formato de plantilla."""
    from mathutils.bvhtree import BVHTree
    _tree_reset()
    TREES[name]({})
    allbm = bmesh.new()
    info = []
    for bm, col, ctr in TREE_PARTS:
        bmesh.ops.triangulate(bm, faces=bm.faces)
        me = bpy.data.meshes.new("t")
        bm.to_mesh(me)
        bm.free()
        start = len(allbm.faces)
        allbm.from_mesh(me)
        info.append((start, len(allbm.faces), col, ctr))
    allbm.faces.ensure_lookup_table()
    tree = BVHTree.FromBMesh(allbm)
    rng = np.random.default_rng(2)
    dirs = [Vector(d / np.linalg.norm(d)) for d in rng.normal(size=(28, 3))]
    H = max(v.co.z for v in allbm.verts)
    out = []
    for (a, b, col, ctr) in info:
        for fi in range(a, b):
            f = allbm.faces[fi]
            fn = f.normal
            for v in f.verts:
                if ctr is not None:              # follaje: normal desde el centro de la masa, mezclada con la cara
                    n = (v.co - ctr).normalized() * 0.75 + fn * 0.25
                    n.normalize()
                else:
                    n = fn
                o = v.co + n * 0.01
                free = 0
                cnt = 0
                for d in dirs:
                    if d.dot(n) < -0.2:
                        continue
                    cnt += 1
                    if tree.ray_cast(o, d, 2.0)[0] is None:
                        free += 1
                ao = 0.35 + 0.65 * (free / max(cnt, 1))
                shade = ao * (0.78 + 0.22 * (v.co.z / H))     # más claro arriba
                c = [ch * shade for ch in col]
                out.append((v.co.x / H, v.co.y / H, -v.co.z / H, n.x, n.y, -n.z, *c))
    return np.array(out, np.float32)


def main_trees(names, outdir):
    for nm in names:
        reset()
        arr = build_tree(nm)
        np.savez_compressed(os.path.join(outdir, "arbol_" + nm + ".npz"), v=arr)
        print("MODELO", "arbol_" + nm, len(arr) // 3, "triángulos", flush=True)


# ============================================================ coordenadas de textura y exportación
def finalize(name):
    """Aplica modificadores, une todo, soldadura por material, normales con bordes vivos y uv en metros."""
    for ob in list(scene.objects):
        if ob.get("cutter"):
            continue
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    bm = bmesh.new()
    mats = []
    for ob in parts:
        ev = ob.evaluated_get(deps)
        me = ev.to_mesh()
        tmp = bmesh.new()
        tmp.from_mesh(me)
        mname = ob.data.materials[0].name
        if mname not in mats:
            mats.append(mname)
        mi = mats.index(mname)
        for f in tmp.faces:
            f.material_index = mi
            f.smooth = ob.data.polygons[0].use_smooth if len(ob.data.polygons) else False
        me2 = bpy.data.meshes.new("tmp")
        tmp.to_mesh(me2)
        tmp.free()
        bm.from_mesh(me2)
        ev.to_mesh_clear()
    for ob in list(scene.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    if not os.environ.get("SIN_ORIENT"):
        orient(bm)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(material(m))
    ob = bpy.data.objects.new(name, me)
    scene.collection.objects.link(ob)
    return ob


def orient(bm):
    """Cada cara mira hacia su lado abierto: primero cuántos rayos llegan al cielo y, para desempatar, cuánto
    espacio libre hay (así el interior del hangar y los aleros quedan bien). Sin esto, una cara del revés se hornea
    negra (Cycles mira hacia adentro del sólido)."""
    from mathutils.bvhtree import BVHTree
    bm.faces.ensure_lookup_table()
    tree = BVHTree.FromBMesh(bm)
    g = 400.0
    gb = bmesh.new()
    vs = [gb.verts.new(v) for v in ((-g, -g, -0.02), (g, -g, -0.02), (g, g, -0.02), (-g, g, -0.02))]
    gb.faces.new(vs)
    gtree = BVHTree.FromBMesh(gb)
    rng = np.random.default_rng(3)
    dirs = rng.normal(size=(40, 3))
    dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
    dv = [Vector(d) for d in dirs]

    def score(c, n):
        k = 0.0
        for d in dv:
            if d.dot(n) <= 0.05:
                continue
            o = c + n * 0.004
            h = tree.ray_cast(o, d, 300.0)
            hg = gtree.ray_cast(o, d, 300.0)
            dist = min(h[3] if h[0] is not None else 1e9, hg[3] if hg[0] is not None else 1e9)
            k += 1000.0 if dist > 1e8 else min(dist, 20.0)
        return k
    flips = []
    for f in bm.faces:
        if f.calc_area() < 1e-7:
            continue
        n = f.normal.copy()
        ctr = f.calc_center_median()
        pts = [ctr] + [v.co * 0.6 + ctr * 0.4 for v in f.verts]
        if sum(score(p, -n) for p in pts) > sum(score(p, n) for p in pts) * 1.05:
            flips.append(f)
    for f in flips:
        f.normal_flip()
    print("caras dadas vuelta:", len(flips), "de", len(bm.faces), flush=True)


def tex_uv(me):
    """uv en metros / tamaño de la textura del material, proyectando cada triángulo en su propio plano: la u corre
    en horizontal (las ondas de la chapa quedan verticales en las paredes y bajando en el techo)."""
    uvl = me.uv_layers.new(name="tex")
    for poly in me.polygons:
        n = Vector(poly.normal)
        tile = MATS[me.materials[poly.material_index].name][1]
        if abs(n.z) > 0.97:
            tu, tv = Vector((1, 0, 0)), Vector((0, 1, 0))
        else:
            tu = Vector((0, 0, 1)).cross(n).normalized()
            tv = n.cross(tu).normalized()
            if tv.z < 0:
                tv = -tv
        for li in poly.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            uvl.data[li].uv = (co.dot(tu) / tile, co.dot(tv) / tile)
    return uvl


def light_uv(ob):
    me = ob.data
    lm = me.uv_layers.new(name="luz")
    me.uv_layers.active = lm
    bpy.context.view_layer.objects.active = ob
    for o in scene.objects:
        o.select_set(o is ob)
    # solo las caras que llevan mapa de luz (el interior en penumbra fija queda afuera); la selección se hace en
    # modo cara desde bmesh (en modo vértice Blender la recalcula y dejaría caras sin desplegar)
    keep = [me.materials[p.material_index].name not in (NOLM | NOBAKE) for p in me.polygons]
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.context.tool_settings.mesh_select_mode = (False, False, True)
    bm = bmesh.from_edit_mesh(me)
    bm.faces.ensure_lookup_table()
    for f in bm.faces:
        f.select_set(False)
    for f in bm.faces:
        if keep[f.index]:
            f.select_set(True)
    bmesh.update_edit_mesh(me)
    bpy.ops.uv.smart_project(angle_limit=math.radians(50.0), island_margin=0.006, area_weight=0.0,
                             correct_aspect=True, scale_to_bounds=False)
    bpy.ops.uv.pack_islands(rotate=True, margin=0.003)
    bpy.ops.object.mode_set(mode="OBJECT")
    # las caras sin mapa de luz conservaban los uv de la textura (Blender los copia al crear la capa): a una
    # esquina mínima, si no al hornearse taparían medio mapa
    lm = me.uv_layers["luz"]                          # la referencia de antes queda inválida tras el modo edición
    for poly, k in zip(me.polygons, keep):
        if not k:
            for li in poly.loop_indices:
                lm.data[li].uv = (0.001, 0.001)
    return lm


def bake(ob, gobj, size, gsize, samples):
    scene.cycles.samples = samples
    img = bpy.data.images.new("luz", size, size, float_buffer=True)
    gimg = bpy.data.images.new("suelo_luz", gsize, gsize, float_buffer=True)
    for m in ob.data.materials:
        nt = m.node_tree
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = img
        nt.nodes.active = n
    # los vidrios transparentes no cuentan para la luz
    for m in ob.data.materials:
        if m.name in NOBAKE:
            p = m.node_tree.nodes["Principled BSDF"]
            p.inputs["Alpha"].default_value = 0.0
    gm = gobj.data.materials[0]
    n = gm.node_tree.nodes.new("ShaderNodeTexImage")
    n.image = gimg
    gm.node_tree.nodes.active = n
    me = ob.data
    me.uv_layers.active = me.uv_layers["luz"]
    me.uv_layers["luz"].active_render = True          # Cycles hornea sobre la capa de render, no la activa
    for o, im in ((ob, img), (gobj, gimg)):
        for x in scene.objects:
            x.select_set(x is o)
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.bake(type="DIFFUSE", pass_filter={"DIRECT", "INDIRECT"}, margin=6, use_clear=True)
    def px(im):
        a = np.empty(im.size[0] * im.size[1] * 4, np.float32)
        im.pixels.foreach_get(a)
        return a.reshape(im.size[1], im.size[0], 4)
    return px(img)[..., :3], px(gimg)[..., :3].mean(-1)


def ground(grect):
    x0, y0, x1, y1 = grect
    g = 400.0
    m = material("concrete")
    for name, (a0, b0, a1, b1, z) in (("suelo", (-g, -g, g, g, -0.02)), ("parche", (x0, y0, x1, y1, 0.0))):
        bm = bmesh.new()
        uvl = bm.loops.layers.uv.new("UVMap")
        vs = [bm.verts.new(v) for v in ((a0, b0, z), (a1, b0, z), (a1, b1, z), (a0, b1, z))]
        f = bm.faces.new(vs)
        for loop, uv in zip(f.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
            loop[uvl].uv = uv
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
        bm.free()
        o = bpy.data.objects.new(name, me)
        mat = bpy.data.materials.new(name + "_m")
        mat.use_nodes = True
        mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.3, 0.3, 0.27, 1.0)
        o.data.materials.append(mat)
        scene.collection.objects.link(o)
        if name == "parche":
            patch = o
    return patch


def export(ob, lm_img, g_img, grect, path):
    me = ob.data
    me.calc_loop_triangles()
    tris = me.loop_triangles
    nt = len(tris)
    li = np.empty(nt * 3, np.int32)
    tris.foreach_get("loops", li)
    mi = np.empty(nt, np.int32)
    tris.foreach_get("material_index", mi)
    vi = np.empty(len(me.loops), np.int32)
    me.loops.foreach_get("vertex_index", vi)
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    cn = np.empty(len(me.loops) * 3, np.float32)
    me.corner_normals.foreach_get("vector", cn)
    cn = cn.reshape(-1, 3)
    uv0 = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers["tex"].data.foreach_get("uv", uv0)
    uv0 = uv0.reshape(-1, 2)
    uv1 = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers["luz"].data.foreach_get("uv", uv1)
    uv1 = uv1.reshape(-1, 2)
    out = {}
    for k, m in enumerate(me.materials):
        sel = np.nonzero(mi == k)[0]
        if not len(sel):
            continue
        L = li.reshape(-1, 3)[sel].reshape(-1)
        P = co[vi[L]]
        N = cn[L]
        rows = np.zeros((len(L), 10), np.float32)
        rows[:, 0], rows[:, 1], rows[:, 2] = P[:, 0], P[:, 1], -P[:, 2]       # x adelante, y, z abajo
        rows[:, 3], rows[:, 4], rows[:, 5] = N[:, 0], N[:, 1], -N[:, 2]
        rows[:, 6:8] = uv0[L]
        rows[:, 8:10] = uv1[L] if m.name not in (NOBAKE | NOLM) else -1.0
        out["m_" + m.name] = rows
    out["lm"] = np.clip(lm_img / LIGHT_SCALE * 255 + 0.5, 0, 255).astype(np.uint8)
    out["ground"] = np.clip(g_img / LIGHT_SCALE * 255 + 0.5, 0, 255).astype(np.uint8)
    out["grect"] = np.array(grect, np.float32)
    np.savez_compressed(path, **out)
    return {k: len(v) // 3 for k, v in out.items() if k.startswith("m_")}


def main():
    spec = json.load(open(SPEC, encoding="utf-8"))
    os.makedirs(OUT, exist_ok=True)
    for item in spec:
        if item["kind"] == "arbol":                  # plantilla de árbol (otro formato de salida)
            main_trees([item["p"]["name"]], OUT)
            continue
        reset()
        info = BUILDERS[item["kind"]](item["p"])
        ob = finalize(item["key"])
        me = ob.data
        # bordes vivos por ángulo y sombreado suave en los cilindros
        for poly in me.polygons:
            poly.use_smooth = True
        bpy.context.view_layer.objects.active = ob
        ob.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.set_sharpness_by_angle(angle=math.radians(35.0))
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.object.mode_set(mode="OBJECT")
        tex_uv(me)
        light_uv(ob)
        xs = np.array([v.co[:] for v in me.vertices])
        mg = info.get("grect_margin", 12.0)
        grect = (xs[:, 0].min() - mg, xs[:, 1].min() - mg, xs[:, 0].max() + mg, xs[:, 1].max() + mg)
        patch = ground(grect)
        lm, gl = bake(ob, patch, item.get("size", 1024), item.get("gsize", 256), item.get("samples", 256))
        counts = export(ob, lm, gl, grect, os.path.join(OUT, item["key"] + ".npz"))
        print("MODELO", item["key"], sum(counts.values()), "triángulos", counts, flush=True)


main()
