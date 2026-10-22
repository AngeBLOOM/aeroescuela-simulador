"""Se ejecuta DENTRO de Blender (lo llama tools/hornear_luz.py):

    blender --background --factory-startup --python tools/blender_hornear.py -- entrada.npz salida.npz 1024 256 256

Arma el edificio (triángulos en coordenadas de Blender: X este, Y norte, Z arriba) sobre un suelo grande, con un
cielo blanco uniforme y sin Sol, y hornea con Cycles la luz difusa que recibe cada punto (directa del cielo más los
rebotes en el suelo y en las paredes). Así queda solo la parte que no depende de la hora: rincones, aleros, el pie
de las paredes y la penumbra en el suelo alrededor. El Sol y sus sombras los pone el simulador en cada cuadro.

Escala: una superficie horizontal a cielo abierto vale 1,0; una pared vertical sin obstáculos, ~0,6.
"""
import math
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, OUT = argv[0], argv[1]
SIZE, GSIZE, SAMPLES = int(argv[2]), int(argv[3]), int(argv[4])

d = np.load(SRC)
TRIS = d["tris"].astype(np.float64)          # (T, 3, 3)
ALB = d["albedo"].astype(np.float64)         # (T, 3)
OCC = d["occ"].astype(bool)                  # el triángulo existe para la luz (los vidrios transparentes no)
GRECT = d["grect"].astype(np.float64)        # (x0, y0, x1, y1) del parche de suelo, en X/Y de Blender
GALB = tuple(float(v) for v in d["ground_albedo"])

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = False
scene.cycles.max_bounces = 4
scene.cycles.diffuse_bounces = 3
world = bpy.data.worlds.new("cielo")
scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs[0].default_value = (1.0, 1.0, 1.0, 1.0)
bg.inputs[1].default_value = 1.0


def material(name, rgb, image=None):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    p = nt.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (*rgb, 1.0)
    p.inputs["Roughness"].default_value = 1.0
    if image is not None:
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = image
        nt.nodes.active = n
    return m


# ---- orientación: cada triángulo mira hacia el lado más abierto (las normales del generador no siempre miran
# hacia afuera; para hornear hace falta saber qué cara es la exterior)
idx = np.nonzero(OCC)[0]
verts = [Vector(p) for t in TRIS[idx] for p in t]
polys = [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(len(idx))]
g = 400.0
verts += [Vector((-g, -g, -0.02)), Vector((g, -g, -0.02)), Vector((g, g, -0.02)), Vector((-g, g, -0.02))]
polys.append((len(verts) - 4, len(verts) - 3, len(verts) - 2, len(verts) - 1))
bvh = BVHTree.FromPolygons(verts, polys)
rng = np.random.default_rng(1)
dirs = rng.normal(size=(48, 3))
dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)


def openness(c, n):
    """Cuán abierto es ese lado: ante todo, cuántos rayos llegan al cielo (el interior cerrado del hangar no ve
    ninguno); para desempatar, la distancia libre hasta el primer obstáculo (hasta 20 m), que reconoce el lado
    exterior de las caras que miran hacia abajo (aleros), que ven el suelo y no el cielo."""
    k = 0.0
    for dv in dirs:
        if dv @ n <= 0.05:
            continue
        hit = bvh.ray_cast(Vector(c + n * 0.03), Vector(dv), 300.0)
        k += 1000.0 if hit[0] is None else min(hit[3], 20.0)
    return k


flip = np.zeros(len(TRIS), bool)
for i in idx:
    t = TRIS[i]
    n = np.cross(t[1] - t[0], t[2] - t[0])
    ln = np.linalg.norm(n)
    if ln < 1e-12:
        continue
    n /= ln
    # varios puntos del triángulo (un letrero o una viga pegada puede tapar justo el centro)
    pts = [t.mean(0)] + [0.65 * v + 0.35 * t.mean(0) for v in t]
    flip[i] = sum(openness(c, -n) for c in pts) > sum(openness(c, n) for c in pts)

# ---- malla del edificio (vértices soldados para que las paredes sean islas enteras al desplegar)
bm = bmesh.new()
for i in idx:
    t = TRIS[i]
    order = (0, 2, 1) if flip[i] else (0, 1, 2)
    vs = [bm.verts.new(t[k]) for k in order]
    bm.faces.new(vs)
bm.faces.ensure_lookup_table()
nf = len(bm.faces)
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0005)
assert len(bm.faces) == nf, "se perdieron caras al soldar"
mesh = bpy.data.meshes.new("edificio")
bm.to_mesh(mesh)
bm.free()
obj = bpy.data.objects.new("edificio", mesh)
scene.collection.objects.link(obj)

img = bpy.data.images.new("luz", SIZE, SIZE, float_buffer=True)
cols = {}
for fi, i in enumerate(idx):
    key = tuple(np.round(ALB[i], 2))
    if key not in cols:
        cols[key] = len(cols)
        mesh.materials.append(material(f"m{len(cols)}", key, img))
    mesh.polygons[fi].material_index = cols[key]

# desplegado automático (islas por planos, con margen)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.smart_project(angle_limit=math.radians(50.0), island_margin=0.01, area_weight=0.0,
                         correct_aspect=True, scale_to_bounds=False)
bpy.ops.uv.pack_islands(rotate=True, margin=0.004)          # aprovechar toda la imagen
bpy.ops.object.mode_set(mode="OBJECT")

# ---- suelo: plano grande (rebote) y el parche que se hornea alrededor del edificio
gmesh = bpy.data.meshes.new("suelo")
bm = bmesh.new()
vs = [bm.verts.new(v) for v in ((-g, -g, -0.02), (g, -g, -0.02), (g, g, -0.02), (-g, g, -0.02))]
bm.faces.new(vs)
bm.to_mesh(gmesh)
bm.free()
gobj = bpy.data.objects.new("suelo", gmesh)
gobj.data.materials.append(material("suelo", GALB))
scene.collection.objects.link(gobj)

x0, y0, x1, y1 = GRECT
pmesh = bpy.data.meshes.new("parche")
bm = bmesh.new()
uvl = bm.loops.layers.uv.new("UVMap")
vs = [bm.verts.new(v) for v in ((x0, y0, 0.0), (x1, y0, 0.0), (x1, y1, 0.0), (x0, y1, 0.0))]
f = bm.faces.new(vs)
for loop, uv in zip(f.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
    loop[uvl].uv = uv
bm.to_mesh(pmesh)
bm.free()
pobj = bpy.data.objects.new("parche", pmesh)
gimg = bpy.data.images.new("suelo_luz", GSIZE, GSIZE, float_buffer=True)
pobj.data.materials.append(material("parche", GALB, gimg))
scene.collection.objects.link(pobj)


def bake(o):
    for ob in scene.objects:
        ob.select_set(False)
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.bake(type="DIFFUSE", pass_filter={"DIRECT", "INDIRECT"}, margin=6, use_clear=True)


def pixels(im):
    a = np.empty(im.size[0] * im.size[1] * 4, np.float32)
    im.pixels.foreach_get(a)
    return a.reshape(im.size[1], im.size[0], 4)       # fila 0 = abajo (v = 0)


bake(obj)
lm = pixels(img)[..., :3]
bake(pobj)
gl = pixels(gimg)[..., :3].mean(-1)

# uv de cada esquina de cada triángulo original (en su orden original)
uv = np.full((len(TRIS), 3, 2), -1.0, np.float32)
lay = mesh.uv_layers.active.data
for fi, i in enumerate(idx):
    li = list(mesh.polygons[fi].loop_indices)
    corners = [lay[k].uv[:] for k in li]
    if flip[i]:
        corners = [corners[0], corners[2], corners[1]]
    uv[i] = corners
np.savez_compressed(OUT, lm=lm.astype(np.float16), ground=gl.astype(np.float16), uv=uv)
print("HORNEADO", OUT, "luz media", float(lm.mean()), "suelo min", float(gl.min()))
