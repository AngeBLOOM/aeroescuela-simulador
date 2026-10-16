"""Renderizador OpenGL (moderngl) del simulador."""
import math
import os

import moderngl
import numpy as np

from sim.mathx import (axis_rotation, clamp, gl_bytes, look_dir, lerp, model_matrix, perspective,
                       quat_to_mat, smoothstep, translate)

from . import geometry as geo
from . import shaders as sh
from . import textures as tx
from .cockpit3d import Cockpit3D
from .scenery import Scenery

FAR = 140000.0
PATCH_HALF = 16              # malla fina del terreno: celdas de 100 m a cada lado del avión…
PATCH_SUB = 8                # …divididas en 8 x 8 (12,5 m)
PATCH_FADE = 3.0             # celdas del borde donde empalma con la malla gruesa
PATCH_MOVE = 5               # se rehace cuando el avión se aleja tantas celdas del centro
SH2_RAD = 1200.0             # medio lado de la caja de sombras del escenario (m)


def _smooth(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _bilinear(A, U, V):
    """Interpola la grilla A (n x n [x k]) en las coordenadas fraccionarias U, V."""
    n = A.shape[0]
    i = np.clip(U.astype(int), 0, n - 2)
    j = np.clip(V.astype(int), 0, n - 2)
    fu = (U - i)[..., None] if A.ndim == 3 else U - i
    fv = (V - j)[..., None] if A.ndim == 3 else V - j
    return (A[i, j] * (1 - fu) * (1 - fv) + A[i + 1, j] * fu * (1 - fv) + A[i, j + 1] * (1 - fu) * fv
            + A[i + 1, j + 1] * fu * fv)


def build_terrain_patch(T, ci, cj):
    """Malla fina del terreno alrededor de la celda (ci, cj): superficie suave con ondulaciones (la misma de la
    física, Terrain.height) y, en el borde, la de la malla gruesa para que empalmen sin rendijas.
    Devuelve (vértices, índices, (i0, i1, j0, j1)) o None si queda fuera de la grilla."""
    n = T.n
    i0, i1 = max(1, ci - PATCH_HALF), min(n - 4, ci + PATCH_HALF)
    j0, j1 = max(1, cj - PATCH_HALF), min(n - 4, cj + PATCH_HALF)
    if i1 - i0 < 6 or j1 - j0 < 6:
        return None
    mu, mv = (i1 - i0) * PATCH_SUB + 1, (j1 - j0) * PATCH_SUB + 1
    U, V = np.meshgrid(np.linspace(i0, i1, mu), np.linspace(j0, j1, mv), indexing="ij")
    X = -T.half + U * T.cell
    Y = -T.half + V * T.cell
    ht = T.height_tri_v(X, Y)
    e = _smooth(0.0, PATCH_FADE, np.minimum(np.minimum(U - i0, i1 - U), np.minimum(V - j0, j1 - V)))
    h = ht + (T.height_v(X, Y) - ht) * e
    gx, gy = np.gradient(h, T.cell / PATCH_SUB)
    nf = np.stack([-gx, -gy, -np.ones_like(h)], axis=-1)
    nf /= np.linalg.norm(nf, axis=-1, keepdims=True)
    # en el borde, las normales de la malla gruesa (así la luz tampoco hace costura)
    sub = T.h[i0 - 1:i1 + 2, j0 - 1:j1 + 2]
    cgx, cgy = np.gradient(sub, T.cell)
    nc = np.stack([-cgx, -cgy, -np.ones_like(sub)], axis=-1)
    nc /= np.linalg.norm(nc, axis=-1, keepdims=True)
    nc = _bilinear(nc, U - i0 + 1, V - j0 + 1)
    nrm = nc * (1 - e[..., None]) + nf * e[..., None]
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
    col = _bilinear(T.colors, U, V)
    verts = np.concatenate([np.stack([X, Y, -h], axis=-1), nrm, col], axis=-1).reshape(-1, 9).astype(np.float32)
    a = np.arange(mu - 1)
    b = np.arange(mv - 1)
    I, J = np.meshgrid(a, b, indexing="ij")
    v00 = (I * mv + J).ravel()
    v10 = ((I + 1) * mv + J).ravel()
    v01 = (I * mv + J + 1).ravel()
    v11 = ((I + 1) * mv + J + 1).ravel()
    idx = np.stack([v00, v10, v11, v00, v11, v01], axis=-1).ravel().astype(np.uint32)
    return verts, idx, (i0, i1, j0, j1)


def mix3(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


class GPUMesh:
    def __init__(self, ctx, prog, data, fmt="3f 3f 3f", attrs=("in_pos", "in_norm", "in_col"), index=None):
        self.ctx = ctx
        self.prog = prog
        data = np.ascontiguousarray(data, dtype=np.float32)
        if data.size == 0:
            data = np.zeros((3, len(fmt.split()) and sum(int(f[:-1]) for f in fmt.split())), np.float32)
        self.vbo = ctx.buffer(data.tobytes())
        self.ibo = ctx.buffer(np.ascontiguousarray(index, dtype=np.uint32).tobytes()) if index is not None else None
        # los atributos que el shader no usa se sustituyen por relleno
        fmts = fmt.split()
        keep_f, keep_a = [], []
        for f, a in zip(fmts, attrs):
            if a in prog:
                keep_f.append(f)
                keep_a.append(a)
            else:
                keep_f.append(f"{int(f[:-1]) * 4}x")
        content = [(self.vbo, " ".join(keep_f), *keep_a)]
        self.vao = ctx.vertex_array(prog, content, self.ibo) if self.ibo else ctx.vertex_array(prog, content)

    def render(self, mode=moderngl.TRIANGLES):
        self.vao.render(mode)

    def release(self):
        self.vao.release()
        self.vbo.release()
        if self.ibo:
            self.ibo.release()


class Renderer:
    def __init__(self, ctx, world, size, progress=None):
        self.ctx = ctx
        self.world = world
        self.size = size
        self.time = 0.0
        self._progress = progress or (lambda msg: None)
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.enable(moderngl.PROGRAM_POINT_SIZE)

        self._progress("Compilando shaders…")
        self.p_terrain = ctx.program(vertex_shader=sh.TERRAIN_VS, fragment_shader=sh.TERRAIN_FS)
        self.p_water = ctx.program(vertex_shader=sh.WATER_VS, fragment_shader=sh.WATER_FS)
        self.p_obj = ctx.program(vertex_shader=sh.OBJECT_VS, fragment_shader=sh.OBJECT_FS)
        self.p_tex = ctx.program(vertex_shader=sh.TEX_VS, fragment_shader=sh.TEX_FS)
        self.p_model = ctx.program(vertex_shader=sh.MODEL_VS, fragment_shader=sh.MODEL_FS)
        self.p_shadow = ctx.program(vertex_shader=sh.SHADOW_VS, fragment_shader=sh.SHADOW_FS)
        self.p_tree = ctx.program(vertex_shader=sh.TREE_VS, fragment_shader=sh.TREE_FS)
        self.p_bldg = ctx.program(vertex_shader=sh.BLDG_VS, fragment_shader=sh.BLDG_FS)
        self.p_decal = ctx.program(vertex_shader=sh.DECAL_VS, fragment_shader=sh.DECAL_FS)
        self.p_smoke = ctx.program(vertex_shader=sh.SMOKE_VS, fragment_shader=sh.SMOKE_FS)
        self.decals = []
        self.p_shadow_tree = ctx.program(vertex_shader=sh.SHADOW_TREE_VS, fragment_shader=sh.SHADOW_FS)
        self.p_bright = ctx.program(vertex_shader=sh.POST_VS, fragment_shader=sh.BRIGHT_FS)
        self.p_blur = ctx.program(vertex_shader=sh.POST_VS, fragment_shader=sh.BLUR_FS)
        for prog in (self.p_terrain, self.p_obj, self.p_tex, self.p_model, self.p_tree, self.p_bldg, self.p_decal):
            prog["u_cloudmap"] = self.CLOUD_UNIT
            prog["u_shmap"] = self.SH_UNIT          # nunca en la misma unidad que una textura normal
            prog["u_shmap2"] = self.SH2_UNIT
        self.p_sky = ctx.program(vertex_shader=sh.SKY_VS, fragment_shader=sh.SKY_FS)
        self.p_light = ctx.program(vertex_shader=sh.LIGHT_VS, fragment_shader=sh.LIGHT_FS)
        self.p_cloud = ctx.program(vertex_shader=sh.CLOUD_VS, fragment_shader=sh.CLOUD_FS)
        self.p_overlay = ctx.program(vertex_shader=sh.OVERLAY_VS, fragment_shader=sh.OVERLAY_FS)

        # texturas
        det = tx.detail_noise()
        self.t_detail = ctx.texture((det.shape[1], det.shape[0]), 4, det.tobytes())
        self.t_detail.build_mipmaps()
        self.t_detail.repeat_x = self.t_detail.repeat_y = True
        self.t_detail.anisotropy = 8.0
        self.t_cloud, self.n_cloud_var = self._cloud_atlas()
        # suelo fotográfico (escaneos CC0, tools/texturas_suelo.py): color con su relieve (mapa de normales)
        self.t_asph, self.asph_gain = self._photo_texture("asfalto_pista.jpg", rgb_gain=True)
        if self.t_asph is None:                          # sin los escaneos: las texturas generadas de antes
            self.t_asph, self.asph_gain = self._photo_texture("asfalto.png", rgb_gain=True)
        self.t_asph_n = self._normal_texture("asfalto_pista_n.jpg")
        self.t_conc, self.conc_gain = self._photo_texture("concreto.jpg", rgb_gain=True)
        self.t_conc_n = self._normal_texture("concreto_n.jpg")
        self.t_grass, self.grass_gain = self._photo_texture("pasto.jpg", rgb_gain=True)
        if self.t_grass is None:
            self.t_grass, self.grass_gain = self._photo_texture("cesped.png", rgb_gain=True)
        self.t_grass_n = self._normal_texture("pasto_n.jpg")
        self.t_skin, _ = self._photo_texture("pintura_avion.png")
        deck = tx.cloud_deck()
        self.t_deck = ctx.texture((deck.shape[1], deck.shape[0]), 4, deck.tobytes())
        self.t_deck.build_mipmaps()
        self.t_deck.repeat_x = self.t_deck.repeat_y = True
        D = 70000.0
        uvk = 1.0 / 2600.0
        deck_v = np.array([[x, y, 0.0, x * uvk, y * uvk] for x, y in
                           ((-D, -D), (D, -D), (D, D), (-D, -D), (D, D), (-D, D))], np.float32)
        self.m_deck = GPUMesh(ctx, self.p_tex, deck_v, fmt="3f 2f", attrs=("in_pos", "in_uv"))

        quad = np.array([-1, -1, 3, -1, -1, 3], dtype="f4")
        self.vbo_tri = ctx.buffer(quad.tobytes())
        self.vao_sky = ctx.vertex_array(self.p_sky, [(self.vbo_tri, "2f", "in_pos")])
        self.vao_bright = ctx.vertex_array(self.p_bright, [(self.vbo_tri, "2f", "in_pos")])
        self.vao_blur = ctx.vertex_array(self.p_blur, [(self.vbo_tri, "2f", "in_pos")])
        quad2 = np.array([-1, -1, 1, -1, 1, 1, -1, -1, 1, 1, -1, 1], dtype="f4")
        self.vbo_quad = ctx.buffer(quad2.tobytes())
        self.vao_overlay = ctx.vertex_array(self.p_overlay, [(self.vbo_quad, "2f", "in_pos")])
        self.t_overlay = None

        self._progress("Construyendo terreno y escenario…")
        self.scn = Scenery(world)
        self.m_terrain = GPUMesh(ctx, self.p_terrain, self.scn.terrain_vertices, index=self.scn.terrain_indices)
        self.sat = []
        loc = getattr(world, "location", None)
        if loc is not None:
            self._progress("Cargando fotografía satelital…")
            for img, rect in loc["sat"]:
                img = np.ascontiguousarray(img, dtype=np.uint8)
                t = ctx.texture((img.shape[1], img.shape[0]), 3, img.tobytes())
                t.build_mipmaps()
                t.anisotropy = 16.0
                t.repeat_x = t.repeat_y = False
                self.sat.append((t, tuple(float(v) for v in rect)))
            self.t_lake = None
            if loc.get("water") is not None:
                m, rect = loc["water"]
                m = np.ascontiguousarray(m, dtype=np.uint8)
                t = ctx.texture((m.shape[1], m.shape[0]), 1, m.tobytes())
                t.build_mipmaps()
                t.repeat_x = t.repeat_y = False
                self.t_lake = (t, tuple(float(v) for v in rect))
        E = 140000.0
        water = np.array([
            [-E, -E, 0, 0, 0, -1, 0, 0, 0], [E, -E, 0, 0, 0, -1, 0, 0, 0], [E, E, 0, 0, 0, -1, 0, 0, 0],
            [-E, -E, 0, 0, 0, -1, 0, 0, 0], [E, E, 0, 0, 0, -1, 0, 0, 0], [-E, E, 0, 0, 0, -1, 0, 0, 0]], np.float32)
        self.m_water = GPUMesh(ctx, self.p_water, water)
        self.m_objects = GPUMesh(ctx, self.p_obj, self.scn.objects)
        bm = getattr(self.scn, "buildings_mesh", None)
        self.m_bldg = None
        if bm is not None and len(bm):
            self.m_bldg = GPUMesh(ctx, self.p_bldg, bm, fmt="3f 3f 3f 3f 1f",
                                  attrs=("in_pos", "in_norm", "in_col", "in_uvh", "in_style"))
        self._build_parked()
        self._build_buildings()
        self._build_trees()
        self._build_casters()
        self.runway_meshes = []
        for surf, verts, kind in self.scn.runways:
            data = tx.surface_rgba(surf, True)
            tex = ctx.texture(surf.get_size(), 4, data)
            tex.build_mipmaps()
            tex.anisotropy = 16.0
            tex.repeat_x = kind != "pista"
            tex.repeat_y = True
            m = GPUMesh(ctx, self.p_tex, verts, fmt="3f 2f", attrs=("in_pos", "in_uv"))
            self.runway_meshes.append((tex, m, kind))
        # luces
        self.light_data = self.scn.lights_static.copy()
        self.vbo_lights = ctx.buffer(self.light_data.tobytes())
        self.vao_lights = ctx.vertex_array(self.p_light, [(self.vbo_lights, "3f 3f 1f", "in_pos", "in_col", "in_size")])
        self.vbo_refl = ctx.buffer(reserve=7 * 4 * 3000, dynamic=True)
        self.vao_refl = ctx.vertex_array(self.p_light, [(self.vbo_refl, "3f 3f 1f", "in_pos", "in_col", "in_size")])
        self.n_refl = 0
        tl = self.scn.town_lights
        self.n_town = len(tl)
        self.vbo_town = ctx.buffer(tl.tobytes() if len(tl) else np.zeros((1, 7), np.float32).tobytes())
        self.vao_town = ctx.vertex_array(self.p_light, [(self.vbo_town, "3f 3f 1f", "in_pos", "in_col", "in_size")])
        self.vbo_dyn = ctx.buffer(reserve=7 * 4 * 256, dynamic=True)
        self.p_speck = ctx.program(vertex_shader=sh.SPECK_VS, fragment_shader=sh.SPECK_FS)
        self.vbo_speck = ctx.buffer(reserve=5 * 4 * 64, dynamic=True)
        self.vao_speck = ctx.vertex_array(self.p_speck, [(self.vbo_speck, "3f 1f 1f", "in_pos", "in_size", "in_alpha")])
        self.vao_dyn = ctx.vertex_array(self.p_light, [(self.vbo_dyn, "3f 3f 1f", "in_pos", "in_col", "in_size")])

        # avión
        self._progress("Preparando aeronave…")
        self.build_aircraft()
        # manga de viento y aros de misión
        ws = geo.MeshBuilder()
        ws.cylinder((0, 0, 0), (0, 0, -7.0), 0.08, (0.7, 0.7, 0.7), segs=6)
        sock = geo.MeshBuilder()
        for i in range(5):
            col = (1.0, 0.45, 0.05) if i % 2 == 0 else (0.95, 0.95, 0.95)
            r0 = 0.45 - i * 0.06
            r1 = 0.45 - (i + 1) * 0.06
            sock.cone((i * 0.7, 0, 0), ((i + 1) * 0.7, 0, 0), r0, col, segs=8, cap=False) if False else \
                sock.cylinder((i * 0.7, 0, 0), ((i + 1) * 0.7, 0, 0), (r0 + r1) / 2, col, segs=8, caps=False)
        self.m_pole = GPUMesh(ctx, self.p_obj, ws.array())
        self.m_sock = GPUMesh(ctx, self.p_obj, sock.array())
        self.m_ring = GPUMesh(ctx, self.p_obj, geo.ring_template())
        arrow = geo.MeshBuilder()
        arrow.cone((0, 0, 0), (6, 0, 0), 1.6, (1, 1, 1), segs=8)
        self.m_arrow = GPUMesh(ctx, self.p_obj, arrow.array())

        # nubes
        self.vbo_cloud_inst = None
        self.vao_cloud = None
        self.n_clouds = 0
        self.cloud_key = None
        corners = np.array([-1, -1, 1, -1, 1, 1, -1, -1, 1, 1, -1, 1], dtype="f4")
        self.vbo_corners = ctx.buffer(corners.tobytes())
        # humo de quemas y chimeneas cerca de los aeródromos (indica el viento)
        self.smoke_src = self._smoke_sources()
        self.vbo_smoke = ctx.buffer(reserve=8 * 4 * self.SMOKE_N * max(1, len(self.smoke_src)), dynamic=True)
        self.vao_smoke = ctx.vertex_array(self.p_smoke, [
            (self.vbo_corners, "2f", "in_corner"),
            (self.vbo_smoke, "4f 1f 1f 1f 4x/i", "in_center", "in_alpha", "in_var", "in_tone")])
        self.env = {}
        self.rscale = 1.0
        self.samples = 4
        self.fbo_ms = self.fbo_res = self.tex_res = None
        self.bloom = None                        # [(textura, fbo), (textura, fbo)] a 1/4 de resolución
        self.effects = True                      # resplandor, destello del Sol y gradación de color
        self.sh_tex = self.sh_fbo = None
        self.sh_k = 0.0
        self.set_shadow_size(2048)
        self.photo_request = None                # (archivo, escala): Foto pro pedida para el próximo cuadro
        self.photo_result = None
        self._photo_target = None
        self.cloud_shadow_k = 0.0
        self.cloud_shadow_alt = 0.0
        self.patch = None
        self._patch_job = None
        self._patch_T = None
        self._patch_pool = None
        self.p_comp = ctx.program(
            vertex_shader="#version 330\nin vec2 in_pos; void main(){ gl_Position = vec4(in_pos, 0.0, 1.0); }",
            fragment_shader=sh.COMP_FS)
        self.vao_comp = ctx.vertex_array(self.p_comp, [(self.vbo_tri, "2f", "in_pos")])
        self.cockpit = Cockpit3D(ctx, self._photo_texture)
        self.last_view = self.last_proj = None
        self.ensure_overlay(size)

    # ------------------------------------------------------------ texturas fotográficas
    def _load_rgba(self, name):
        import pygame
        from ui import assets
        img = assets.image(name)
        if img is None:
            return None
        rgb = pygame.surfarray.array3d(img).transpose(1, 0, 2)
        try:
            a = pygame.surfarray.array_alpha(img).T
        except Exception:
            a = np.full(rgb.shape[:2], 255, np.uint8)
        return np.dstack([rgb, a]).astype(np.uint8)

    def _photo_texture(self, name, rgb_gain=False):
        """Textura fotográfica enlosable y su ganancia (1 / valor medio): multiplicada por ella queda con promedio 1,
        así aporta el detalle sin cambiar el color de la superficie. Con rgb_gain, la ganancia es por canal."""
        arr = self._load_rgba(name)
        if arr is None:
            return None, ((1.0, 1.0, 1.0) if rgb_gain else 1.0)
        arr = arr[::-1].copy()
        t = self.ctx.texture((arr.shape[1], arr.shape[0]), 4, arr.tobytes())
        t.build_mipmaps()
        t.repeat_x = t.repeat_y = True
        t.anisotropy = 16.0
        if rgb_gain:
            return t, tuple(1.0 / max(float(m) / 255.0, 0.05) for m in arr[..., :3].reshape(-1, 3).mean(0))
        mean = float(arr[..., :3].mean()) / 255.0
        return t, 1.0 / max(mean, 0.05)

    def _normal_texture(self, name):
        """Mapa de normales (convención OpenGL) de una textura de suelo; None si falta (se ve plano)."""
        arr = self._load_rgba(name)
        if arr is None:
            return None
        arr = arr[::-1].copy()
        t = self.ctx.texture((arr.shape[1], arr.shape[0]), 4, arr.tobytes())
        t.build_mipmaps()
        t.repeat_x = t.repeat_y = True
        t.anisotropy = 8.0
        return t

    def _cloud_atlas(self):
        imgs = [self._load_rgba(f"nube_{i}.png") for i in (1, 2, 3)]
        imgs = [i for i in imgs if i is not None]
        if not imgs:
            puff = tx.cloud_puff()[::-1].copy()
            t = self.ctx.texture((puff.shape[1], puff.shape[0]), 4, puff.tobytes())
            t.build_mipmaps()
            return t, 1
        h = min(i.shape[0] for i in imgs)
        atlas = np.concatenate([i[:h, :h] for i in imgs], axis=1)[::-1].copy()
        # color premultiplicado para mezclar sin halos oscuros
        t = self.ctx.texture((atlas.shape[1], atlas.shape[0]), 4, atlas.tobytes())
        t.build_mipmaps()
        return t, len(imgs)

    # ------------------------------------------------------------ avión
    def build_aircraft(self):
        if hasattr(self, "ac_meshes"):
            for m, _p, _a in self.ac_meshes.values():
                m.release()
        t = self.world.ac.t
        parts, lights = geo.aircraft_parts(t)
        self.ac_meshes = {k: (GPUMesh(self.ctx, self.p_obj, a), np.array(p), np.array(ax)) for k, (a, p, ax) in parts.items()}
        self.ac_lights = lights
        self.ac_type_id = t.id

    # ------------------------------------------------------------ modelos 3D reales (assets/modelos)
    MODEL_ALIAS = {"pa28r": "pa28w"}         # el Arrow usa el modelo del PA-28 (mismo fuselaje)

    def aircraft_model(self, type_id):
        """Modelo 3D real del avión (convertido con tools/importar_modelo.py) o None si no hay: entonces se usa el
        dibujado por código. Lista de (vao, textura, material, vao de sombra), primero los opacos."""
        if not hasattr(self, "_models"):
            self._models = {}
        mid = self.MODEL_ALIAS.get(type_id, type_id)
        if mid in self._models:
            return self._models[mid]
        import json
        import pygame
        from ui import assets
        model = None
        path = assets.path(os.path.join("modelos", mid + ".npz"))
        if os.path.exists(path):
            try:
                z = np.load(path)
                meta = json.loads(str(z["meta"]))
                model, texs = [], {}
                for k, m in enumerate(meta):
                    v = np.ascontiguousarray(z[f"v{k}"], np.float32)
                    if v.shape[1] == 8:                   # sin oclusión horneada: todo a la luz
                        v = np.hstack([v, np.ones((len(v), 1), np.float32)])
                    vbo = self.ctx.buffer(np.ascontiguousarray(v).tobytes())
                    ibo = self.ctx.buffer(np.ascontiguousarray(z[f"i{k}"], np.uint32).tobytes())
                    vao = self.ctx.vertex_array(self.p_model, [(vbo, "3f 3f 2f 1f", "in_pos", "in_norm", "in_uv", "in_ao")],
                                                ibo)
                    # los vidrios (transparentes de verdad) no dan sombra
                    solid = not m.get("blend") or m["color"][3] >= 0.6
                    svao = self.ctx.vertex_array(self.p_shadow, [(vbo, "3f 24x", "in_pos")], ibo) if solid else None
                    tex = None
                    if m.get("tex"):
                        if m["tex"] not in texs:
                            img = pygame.image.load(assets.path(os.path.join("modelos", m["tex"])))
                            t_ = self.ctx.texture(img.get_size(), 4, pygame.image.tobytes(img, "RGBA"))
                            t_.build_mipmaps()
                            t_.repeat_x = t_.repeat_y = True
                            t_.anisotropy = 8.0
                            texs[m["tex"]] = t_
                        tex = texs[m["tex"]]
                    model.append((vao, tex, m, svao))
                model.sort(key=lambda it: it[2].get("blend", False))
            except Exception as ex:                       # archivo dañado: se sigue con el avión de código
                print("Modelo", mid, "no se pudo cargar:", ex)
                model = None
        self._models[mid] = model
        return model

    def _draw_model(self, model, M, alpha=1.0):
        pm = self.p_model
        pm["u_model"].write(gl_bytes(M))
        pm["u_spec"].value = 0.45
        pm["u_tint"].value = (1.0, 1.0, 1.0, float(alpha))
        blending = False
        for vao, tex, m, _svao in model:
            if m.get("blend") and not blending:          # los transparentes (vidrios) al final, sin escribir profundidad
                blending = True
                self.ctx.enable(moderngl.BLEND)
                self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
                self.ctx.fbo.depth_mask = False
            pm["u_base"].value = tuple(float(c) for c in m["color"])
            pm["u_emis"].value = float(m.get("emis", 0.0)) * float(self.env.get("night", 0.0))
            pm["u_cutoff"].value = float(m.get("cutoff", 0.0))
            lmap = m.get("lmap")
            pm["u_lm_on"].value = 1 if lmap is not None else 0
            pm["u_corr"].value = float(m.get("corr", 0.0))
            if lmap is not None:
                lmap.use(18)
                pm["u_lmap"].value = 18
            if tex is not None:
                tex.use(9)
                pm["u_tex"].value = 9
                pm["u_has_tex"].value = 1
            else:
                pm["u_has_tex"].value = 0
            vao.render()
        if blending:
            self.ctx.fbo.depth_mask = True
            self.ctx.disable(moderngl.BLEND)

    # ------------------------------------------------------------ tráfico IA
    ACCENTS = [(0.70, 0.08, 0.08), (0.08, 0.20, 0.55), (0.10, 0.40, 0.22), (0.85, 0.45, 0.05)]

    def traffic_mesh(self, type_id, accent):
        """Mallas (sin cabina ni hélice) de un avión del tráfico, con su pintura."""
        if not hasattr(self, "tr_meshes"):
            self.tr_meshes = {}
        key = (type_id, accent)
        if key not in self.tr_meshes and type_id in geo.JETS:
            # avión de línea: accent son los colores de la aerolínea (deriva, franja)
            parts, lights = geo.jet_parts(type_id, accent[0], accent[1])
            self.tr_meshes[key] = ({k: GPUMesh(self.ctx, self.p_obj, a) for k, (a, p, ax) in parts.items()}, lights)
        if key not in self.tr_meshes:
            from sim.aircraft_data import AIRCRAFT
            t = AIRCRAFT[type_id]()
            t.paint = ((0.93, 0.93, 0.92), self.ACCENTS[accent % len(self.ACCENTS)])
            parts, lights = geo.aircraft_parts(t)
            keep = {k: v for k, v in parts.items() if k not in ("cowl", "prop", "prop2")}
            self.tr_meshes[key] = ({k: GPUMesh(self.ctx, self.p_obj, a) for k, (a, p, ax) in keep.items()}, lights)
        return self.tr_meshes[key]

    def _draw_traffic(self, cam_eye):
        po = self.p_obj
        planes = getattr(self.world, "traffic", None)
        if planes is None or not planes.planes:
            return
        po["u_spec"].value = 0.5
        if self.t_skin is not None:
            self.t_skin.use(8)
            po["u_skin_tex"] = 8
            po["u_skin"].value = 1
        for p in planes.planes:
            d = p.pos - cam_eye
            if float(d @ d) > 16000.0 ** 2:
                continue
            M = model_matrix(quat_to_mat(p.quat), p.pos)
            real = None if p.type_id in geo.JETS else self.aircraft_model(p.type_id)
            if real is not None:
                self._draw_model(real, M)
                continue
            meshes, _ = self.traffic_mesh(p.type_id, getattr(p, 'livery', None) or hash(p.callsign) % 4)
            po["u_model"].write(gl_bytes(M))
            if float(d @ d) > 2500.0 ** 2:
                meshes["body"].render()
                continue
            hide_gear = p.type_id == "pa28r" and not p.on_ground and p.leg not in ("final", "toma", "base")
            for name, m in meshes.items():
                if name == "gear" and hide_gear:
                    continue
                if name.startswith("disc"):
                    self.ctx.enable(moderngl.BLEND)
                    self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
                    po["u_tint"].value = (1.0, 1.0, 1.0, 0.25)
                    po["u_model"].write(gl_bytes(M))
                    m.render()
                    po["u_tint"].value = (1.0, 1.0, 1.0, 1.0)
                    self.ctx.disable(moderngl.BLEND)
                    continue
                m.render()
        po["u_spec"].value = 0.15
        if "u_skin" in po:
            po["u_skin"].value = 0

    def _draw_traffic_specks(self, cam, env, h_px, fovy, view, proj):
        """Tráfico que en la imagen mide menos de ~2 píxeles: un punto oscuro de 1,5 a 3 px (como lo ve el ojo),
        cada vez más tenue con la distancia y la bruma. De día; de noche se ven sus luces."""
        tr = getattr(self.world, "traffic", None)
        if tr is None or not tr.planes or env["day"] < 0.2:
            return
        px = h_px / (2.0 * math.tan(math.radians(fovy) / 2.0))
        data = []
        for p in tr.planes:
            d = float(np.linalg.norm(p.pos - cam.eye))
            if d < 300.0 or d > 12000.0:
                continue
            span = 30.0 if p.type_id in geo.JETS else 11.0
            size_px = span / d * px
            if size_px > 3.0:
                continue                                  # ya se ve el modelo
            alpha = env["day"] * (1.0 - smoothstep(4000.0, 12000.0, d)) * min(1.0, 0.45 + size_px * 0.4)
            data.append((*p.pos, max(1.6, min(3.0, size_px * 1.4)), alpha))
        if not data:
            return
        arr = np.array(data[:64], np.float32)
        self.vbo_speck.write(arr.tobytes())
        ps = self.p_speck
        self._set_common(ps, view, proj, cam.eye)
        ps["u_speck_col"].value = tuple(float(c) * 0.35 for c in env["fog_col"])
        ctx = self.ctx
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        ctx.fbo.depth_mask = False
        self.vao_speck.render(moderngl.POINTS, vertices=len(arr))
        ctx.fbo.depth_mask = True
        ctx.disable(moderngl.BLEND)

    # ------------------------------------------------------------ calidad gráfica
    def set_quality(self, scale, samples):
        self.rscale = float(scale)
        self.samples = int(samples)
        for o in (self.fbo_ms, self.fbo_res, self.tex_res):
            if o is not None:
                o.release()
        self.fbo_ms = self.fbo_res = self.tex_res = None
        self._release_bloom()

    def set_effects(self, on, shadow_size=2048):
        """Efectos de imagen (resplandor, destello del Sol, gradación) y resolución de la sombra del avión."""
        self.effects = bool(on)
        if not self.effects:
            self._release_bloom()
        self.set_shadow_size(shadow_size)
        if getattr(self, "vao_casters", None) is not None:      # sombras del escenario: 4096 solo en la Foto pro
            try:
                self._set_sh2_size(4096 if shadow_size >= 4096 else 2048)
            except Exception as ex:
                print("Sombras del escenario:", ex)

    def _release_bloom(self):
        for tex, fbo in (self.bloom or ()):
            fbo.release()
            tex.release()
        self.bloom = None

    def _ensure_bloom(self):
        sw, sh_ = self.tex_res.size
        size = (max(8, sw // 4), max(8, sh_ // 4))
        if self.bloom is not None and self.bloom[0][0].size == size:
            return
        self._release_bloom()
        self.bloom = []
        for _ in range(2):
            t_ = self.ctx.texture(size, 4)
            t_.filter = (moderngl.LINEAR, moderngl.LINEAR)
            t_.repeat_x = t_.repeat_y = False
            self.bloom.append((t_, self.ctx.framebuffer([t_])))

    # ------------------------------------------------------------ sombra del avión (mapa de sombras)
    SH_UNIT = 11
    SHADOW_CODE_PARTS = ("body", "gear", "elevator", "rudder", "ail_l", "ail_r", "flap_l", "flap_r")

    def set_shadow_size(self, size):
        size = int(size)
        if self.sh_tex is not None and self.sh_tex.size == (size, size):
            return
        if self.sh_fbo is not None:
            self.sh_fbo.release()
            self.sh_tex.release()
        self.sh_tex = self.sh_fbo = None
        try:
            t_ = self.ctx.depth_texture((size, size))
            t_.compare_func = "<="
            t_.filter = (moderngl.LINEAR, moderngl.LINEAR)
            t_.repeat_x = t_.repeat_y = False
            self.sh_fbo = self.ctx.framebuffer(depth_attachment=t_)
            self.sh_tex = t_
        except Exception as ex:                  # sin mapa de sombras: queda la sombra plana de antes
            print("Sin mapa de sombras:", ex)

    def _code_shadow_vaos(self):
        if getattr(self, "_sh_code_for", None) is not self.ac_meshes:
            for vao in getattr(self, "_sh_code", {}).values():
                vao.release()
            self._sh_code = {name: self.ctx.vertex_array(self.p_shadow, [(m.vbo, "3f 24x", "in_pos")], m.ibo)
                             for name, (m, _p, _a) in self.ac_meshes.items() if name in self.SHADOW_CODE_PARTS}
            self._sh_code_for = self.ac_meshes
        return self._sh_code

    def _shadow_pass(self, env, body_M, pos, show_aircraft):
        """Dibuja la profundidad del avión vista desde el Sol. La sombra se ve sobre el terreno, las pistas y los
        hangares con la silueta real del modelo; se desvanece con la altura, de noche y con cielo cubierto."""
        self.sh_k = 0.0
        if not show_aircraft or self.sh_fbo is None:
            return
        w = self.world
        sun = np.asarray(env["sun"], np.float64)
        up = -sun[2]
        gh = max(w.terrain.height(pos[0], pos[1]), 0.0)
        hgt = -pos[2] - gh
        k = 0.85 * env["day"] * (1.0 - 0.85 * env["overcast"]) * smoothstep(0.03, 0.16, up) \
            * (1.0 - smoothstep(250.0, 700.0, hgt))
        if k < 0.02 or env["incloud"]:
            return
        t = w.ac.t
        rad = 0.6 * max(t.b, 8.0) + 0.8                 # caja que contiene al avión, vista desde el Sol
        reach = min(max(hgt, 0.0) / max(up, 0.03) + 2.0 * rad + 10.0, 6000.0)
        eye = np.asarray(pos, np.float64) + sun * (rad + 2.0)
        upv = np.array((1.0, 0.0, 0.0) if abs(sun[0]) < 0.9 else (0.0, 1.0, 0.0))
        V = look_dir(eye, -sun, upv)
        n, f = 0.1, rad + 2.0 + reach
        O = np.identity(4)
        O[0, 0] = O[1, 1] = 1.0 / rad
        O[2, 2] = -2.0 / (f - n)
        O[2, 3] = -(f + n) / (f - n)
        LV = O @ V
        B = np.array([[0.5, 0, 0, 0.5], [0, 0.5, 0, 0.5], [0, 0, 0.5, 0.5], [0, 0, 0, 1.0]])
        self.sh_mat = B @ LV
        ctx = self.ctx
        self.sh_fbo.use()
        ctx.scissor = None
        ctx.viewport = (0, 0, *self.sh_tex.size)
        self.sh_fbo.clear(depth=1.0)
        self.p_shadow["u_lmvp"].write(gl_bytes(LV @ body_M))
        real = self.aircraft_model(t.id)
        if real is not None:
            for _vao, _tex, _m, svao in real:
                if svao is not None:
                    svao.render()
        else:
            for name, vao in self._code_shadow_vaos().items():
                if name == "gear" and w.ac.sys.gear_pos < 0.5:
                    continue
                vao.render()
        self.sh_k = float(k)

    # ------------------------------------------------------------ sombras del escenario
    SH2_UNIT = 12

    # ------------------------------------------------------------ hangares y torres con detalle
    def _build_buildings(self):
        """Hangares (chapa ondulada, portones, techo a dos aguas, letrero) y torres de control, con texturas
        generadas y penumbra; se dibujan como un modelo más (mismo sombreado y sombras que los aviones)."""
        from . import buildings as bl
        self.buildings_model = None
        hs = getattr(self.scn, "hangars", [])
        tw = getattr(self.scn, "towers", [])
        signs = getattr(self.scn, "taxi_signs", [])
        dsigns = getattr(self.scn, "dist_signs", [])
        gsigns = getattr(self.scn, "guide_signs", [])
        self.decals = []
        if not hs and not tw and not signs and not dsigns and not gsigns:
            return
        ctx = self.ctx
        # luz del cielo horneada en Blender (tools/hornear_luz.py): cada geometría tiene su mapa de luz; los
        # edificios de igual forma lo comparten y se agrupan en la misma malla. Sin mapa, la penumbra por vértice
        groups = {None: bl.TexMesh()}
        ground = {}

        def place(key, build, x, y, gz, yaw):
            data = bl.load_light(key) if key else None
            if data is None:
                build(groups[None])
                return
            t1 = bl.TexMesh()
            build(t1)
            if not bl.apply_light(t1, data):
                for m_, rows in t1.parts.items():
                    groups[None].parts.setdefault(m_, []).extend(rows)
                return
            g = groups.setdefault(key, bl.TexMesh())
            for m_, rows in t1.parts.items():
                g.parts.setdefault(m_, []).extend(rows)
            ground.setdefault(key, []).extend(bl.ground_quad(x, y, gz, yaw, data["grect"]))

        for (x, y, gz, ln, wd, ht, yaw, col, sign) in hs:
            ck = ",".join(f"{c:.3f}" for c in col)
            place(bl.hangar_key(ln, wd, ht),
                  lambda t, a=(x, y, gz, ln, wd, ht, yaw, ck, sign): bl.add_hangar(t, *a), x, y, gz, yaw)
        for (x, y, gz, h) in tw:
            place(bl.tower_key(h), lambda t, a=(x, y, gz, h): bl.add_tower(t, *a), x, y, gz, 0.0)
        tm = groups[None]
        for (x, y, gz, yaw, mand, loc) in signs:
            bl.add_taxi_sign(tm, x, y, gz, yaw, mand, loc)
        for (x, y, gz, yaw, front, back) in dsigns:
            bl.add_distance_sign(tm, x, y, gz, yaw, front, back)
        for (x, y, gz, yaw, text, arrow) in gsigns:
            bl.add_guide_sign(tm, x, y, gz, yaw, text, arrow)
        texs, model = {}, []
        lmaps = {}
        for key in groups:
            if key is None:
                continue
            data = bl.load_light(key)
            img = np.ascontiguousarray(data["lm"])
            t_ = ctx.texture((img.shape[1], img.shape[0]), 3, img.tobytes())
            t_.build_mipmaps()
            t_.repeat_x = t_.repeat_y = False
            lmaps[key] = t_
            gimg = np.ascontiguousarray(data["ground"])
            gt = ctx.texture((gimg.shape[1], gimg.shape[0]), 1, gimg.tobytes())
            gt.build_mipmaps()
            gt.repeat_x = gt.repeat_y = False
            vbo = ctx.buffer(np.asarray(ground[key], np.float32).tobytes())
            self.decals.append((ctx.vertex_array(self.p_decal, [(vbo, "3f 2f", "in_pos", "in_uv")]), gt))
        items = [(k, m_, a_) for k, t_ in groups.items() for m_, a_ in t_.arrays().items()]
        for key, mat, arr in items:
            col, tkey, blend = bl.material(mat)
            tex = None
            if tkey:
                if tkey not in texs:
                    img = np.ascontiguousarray(bl.make_texture(tkey))
                    t_ = ctx.texture((img.shape[1], img.shape[0]), 4, img.tobytes())
                    t_.build_mipmaps()
                    t_.repeat_x = t_.repeat_y = not tkey.startswith("sign:")
                    t_.anisotropy = 8.0
                    texs[tkey] = t_
                tex = texs[tkey]
            vbo = ctx.buffer(np.ascontiguousarray(arr, np.float32).tobytes())
            vao = ctx.vertex_array(self.p_model, [(vbo, "3f 3f 2f 1f 2f", "in_pos", "in_norm", "in_uv", "in_ao",
                                                   "in_uv2")])
            svao = None if blend else ctx.vertex_array(self.p_shadow, [(vbo, "3f 32x", "in_pos")])
            meta = dict(color=list(col), blend=blend, cutoff=0.0)
            if mat.startswith(("tsign:", "dsign:", "gsign:")):
                meta["emis"] = 0.85                      # los carteles de rodaje y de pista tienen luz propia de noche
            elif mat == "lamp":
                meta["emis"] = 1.8                       # reflectores y luces de las puertas, encendidos de noche
            if mat.startswith("wall:") or mat in ("roof", "interior"):
                meta["corr"] = bl.CORRUGATED
            if key is not None:
                meta["lmap"] = lmaps[key]
            model.append((vao, tex, meta, svao))
        model.sort(key=lambda it: it[2]["blend"])
        self.buildings_model = model

    # ------------------------------------------------------------ árboles: dos niveles de detalle
    TREE_NEAR = 1200.0           # de cerca, el árbol detallado…
    TREE_NEAR_MAX = 1800         # …para los más cercanos (como mucho)
    TREE_REFRESH = 120.0         # se reparte de nuevo cuando la cámara se mueve tanto
    TREE_FAR = 6500.0            # más lejos la bruma los tapa: no se dibujan

    def _build_trees(self):
        self.tree_vaos = {}
        self.tree_inst = None
        tr = getattr(self.scn, "trees", None)
        if tr is None or len(tr["P"]) == 0:
            return
        inst = np.zeros((len(tr["P"]), 8), np.float32)
        inst[:, 0:3] = tr["P"]
        inst[:, 3] = tr["s"]
        inst[:, 4] = tr["yaw"]
        inst[:, 5:8] = tr["col"]
        self.tree_inst = inst
        self.tree_kind = tr["kind"]
        ctx = self.ctx
        for lod in (0, 1):
            for k in (0, 1):
                tpl = geo.template_tree_detail(k) if lod == 0 else geo.template_tree(k)
                tvbo = ctx.buffer(np.ascontiguousarray(tpl, np.float32).tobytes())
                nk = max(1, int((self.tree_kind == k).sum()))
                ibuf = ctx.buffer(reserve=nk * 32)
                vao = ctx.vertex_array(self.p_tree, [(tvbo, "3f 3f 3f", "in_pos", "in_norm", "in_col"),
                                                     (ibuf, "3f 1f 1f 3f/i", "i_pos", "i_scale", "i_yaw", "i_col")])
                svao = ctx.vertex_array(self.p_shadow_tree, [(tvbo, "3f 24x", "in_pos"),
                                                             (ibuf, "3f 1f 1f 12x/i", "i_pos", "i_scale", "i_yaw")])
                self.tree_vaos[(lod, k)] = [vao, svao, ibuf, 0, len(tpl)]
        self._tree_ref = None

    def _update_trees(self, eye):
        if self.tree_inst is None:
            return
        ref = self._tree_ref
        if ref is not None and math.hypot(eye[0] - ref[0], eye[1] - ref[1]) < self.TREE_REFRESH:
            return
        self._tree_ref = (float(eye[0]), float(eye[1]))
        P = self.tree_inst
        d2 = (P[:, 0] - eye[0]) ** 2 + (P[:, 1] - eye[1]) ** 2
        near = d2 < self.TREE_NEAR ** 2
        if near.sum() > self.TREE_NEAR_MAX:
            near = d2 < np.partition(d2, self.TREE_NEAR_MAX)[self.TREE_NEAR_MAX]
        far = d2 < self.TREE_FAR ** 2
        for k in (0, 1):
            mk = self.tree_kind == k
            for lod, sel in ((0, near & mk), (1, ~near & far & mk)):
                ent = self.tree_vaos[(lod, k)]
                data = P[sel]
                if len(data):
                    ent[2].write(np.ascontiguousarray(data).tobytes())
                ent[3] = len(data)
        self._sh2_key = None                         # las sombras de los árboles se rehacen con el reparto nuevo

    # ------------------------------------------------------------ humo (quemas y chimeneas)
    SMOKE_N = 40                 # bocanadas por columna

    def _smoke_sources(self):
        """Dos o tres columnas de humo a 2,5-8 km de los aeródromos, siempre en tierra: una quema agrícola (humo
        gris, columna alta) y alguna chimenea (vapor blanco, columna baja). Fijas para cada escenario."""
        out = []
        T = self.world.terrain
        aps = [a for a in self.world.airports if not getattr(a, "offscene", False)][:2]
        seed = sum(ord(c) for a in aps for c in a.ident)
        rng = np.random.default_rng(seed)
        for n, ap in enumerate(aps):
            kinds = ("quema", "chimenea") if n == 0 else ("quema",)
            for kind in kinds:
                for _try in range(30):
                    a = rng.uniform(0.0, 2.0 * math.pi)
                    d = rng.uniform(2500.0, 8000.0)
                    x, y = ap.ref[0] + math.cos(a) * d, ap.ref[1] + math.sin(a) * d
                    try:
                        g = float(T.height(x, y))
                        wet = T.is_water(x, y)
                    except Exception:
                        continue
                    if g > 1.0 and not wet:
                        out.append((x, y, -g, kind))
                        break
        return out

    def _draw_smoke(self, cam, view, proj):
        if not self.smoke_src:
            return
        w = self.world.weather
        if w.rain > 0.4:
            return                                       # con lluvia fuerte no hay quemas
        N = self.SMOKE_N
        wv = np.array(self._wind_vec(), float)
        k = float(np.hypot(*wv))
        wind_ms = float(w.wind_kt) * 0.5144
        wd = wv / k if k > 1e-4 else np.array([1.0, 0.0])
        wc = np.array([-wd[1], wd[0]])
        rows = []
        for si, (x, y, gz, kind) in enumerate(self.smoke_src):
            if math.hypot(x - cam.eye[0], y - cam.eye[1]) > 30000.0:
                continue
            quema = kind == "quema"
            life = 110.0 if quema else 45.0
            i = np.arange(N, dtype=float)
            age = ((self.time / life + i / N + si * 0.37) % 1.0) * life
            # sube rápido y se nivela (más bajo con viento fuerte, que la acuesta) mientras deriva con el viento
            top = (420.0 if quema else 120.0) / (1.0 + wind_ms / 5.0)
            rise = top * (1.0 - np.exp(-age * (3.5 if quema else 2.5) / top))
            drift = wind_ms * age * 0.9 + 0.4 * age
            side = np.sin(age * 0.11 + i * 1.7 + si) * age * (0.35 if quema else 0.15)
            px = x + wd[0] * drift + wc[0] * side
            py = y + wd[1] * drift + wc[1] * side
            pz = gz - 3.0 - rise
            size = (10.0 + 2.0 * age) if quema else (3.0 + 0.6 * age)
            fade = np.clip(age / 4.0, 0.0, 1.0) * (1.0 - age / life) ** 1.3
            alpha = fade * (0.7 if quema else 0.55)
            tone = np.full(N, 0.0 if quema else 1.0)
            rows.append(np.column_stack([px, py, pz, size, alpha, i % max(1, self.n_cloud_var), tone, np.zeros(N)]))
        if not rows:
            return
        arr = np.vstack(rows)
        d = np.linalg.norm(arr[:, :3] - np.asarray(cam.eye)[None], axis=1)
        arr = arr[np.argsort(-d)].astype(np.float32)               # de atrás hacia adelante
        self.vbo_smoke.write(arr.tobytes())
        ps = self.p_smoke
        self._set_common(ps, view, proj, cam.eye)
        right = np.cross(cam.fwd, cam.up)
        right /= np.linalg.norm(right)
        up = np.cross(right, cam.fwd)
        ps["u_right"].value = tuple(float(v) for v in right)
        ps["u_up"].value = tuple(float(v) for v in up)
        ps["u_nvar"].value = float(self.n_cloud_var)
        self.t_cloud.use(2)
        ps["u_tex"] = 2
        ctx = self.ctx
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
        self.vao_smoke.render(instances=len(arr), vertices=6)

    def _road_traffic(self, cam):
        out = []
        T = self.world.terrain
        eye = np.asarray(cam.eye, float)
        for li, pts in enumerate(self.scn.road_lines):
            seg = np.diff(pts, axis=0)
            ln = np.hypot(seg[:, 0], seg[:, 1])
            cum = np.concatenate([[0.0], np.cumsum(ln)])
            Ltot = float(cum[-1])
            n = max(2, int(Ltot / 900.0))
            for k in range(n):
                for dirn in (1.0, -1.0):
                    v = 19.0 + 6.0 * ((k * 7 + li * 3) % 5) / 4.0          # 70 a 90 km/h
                    s = (k * Ltot / n + (0.5 if dirn < 0 else 0.0) * Ltot / n + dirn * v * self.time) % Ltot
                    i = min(int(np.searchsorted(cum, s, side="right")) - 1, len(ln) - 1)
                    d = seg[i] / max(ln[i], 1e-6)
                    fwd = d * dirn
                    right = np.array([-fwd[1], fwd[0]])
                    p = pts[i] + d * (s - cum[i]) + right * 2.5          # carril de la derecha
                    if math.hypot(p[0] - eye[0], p[1] - eye[1]) > 12000.0:
                        continue
                    z = -float(T.height(p[0], p[1])) - 0.8
                    toward = (eye[0] - p[0]) * fwd[0] + (eye[1] - p[1]) * fwd[1] > 0.0
                    if toward:
                        out.append((p[0], p[1], z, 1.0, 0.95, 0.78, 2.6))
                    else:
                        out.append((p[0], p[1], z, 0.9, 0.06, 0.03, 2.0))
        return out

    def _wind_vec(self):
        """Hacia dónde sopla el viento en superficie (unitario, NED) por su fuerza: 0 en calma, 1 con 25 kt o más.
        Lo usan el agua y los árboles, las referencias con que el piloto estima el viento desde el aire."""
        w = self.world.weather
        k = min(max(float(w.wind_kt), 0.0), 25.0) / 25.0
        a = math.radians(w.wind_dir + 180.0)
        return (math.cos(a) * k, math.sin(a) * k)

    def _draw_trees(self):
        if not self.tree_vaos:
            return
        pt = self.p_tree
        pt["u_time"].value = float(self.time)
        pt["u_wind"].value = float(0.3 + min(self.world.weather.wind_kt, 30.0) / 15.0)
        pt["u_wind_vec"].value = self._wind_vec()
        for vao, _svao, _ib, n, _nv in self.tree_vaos.values():
            if n:
                vao.render(instances=n)

    PARKED_FLEET = ("c172", "c152", "pa28w", "sr20")

    def _build_parked(self):
        """Aviones estacionados: modelos 3D reales variados (C172, C152, PA-28, SR22) apoyados en sus ruedas; si
        falta alguno, todos se dibujan con el modelo de código."""
        from sim.aircraft_data import AIRCRAFT
        self.parked_real, self.m_parked = [], None
        parked = getattr(self.scn, "parked", [])
        if not parked:
            return
        fleet = [a for a in self.PARKED_FLEET if self.aircraft_model(a) is not None and a in AIRCRAFT]
        if len(fleet) == len(self.PARKED_FLEET):
            for k, (px, py, gh, yaw) in enumerate(parked):
                aid = fleet[k % len(fleet)]
                gz = max(g.pos[2] for g in AIRCRAFT[aid]().gears)
                M = translate((px, py, -(gh + gz - 0.05))) @ axis_rotation((0, 0, 1), yaw)
                self.parked_real.append((self.aircraft_model(aid), M))
        elif len(self.scn.parked_code):
            self.m_parked = GPUMesh(self.ctx, self.p_obj, self.scn.parked_code)

    def _build_casters(self):
        """Hangares, edificios, árboles y mangas: los triángulos que sobresalen del suelo (las plataformas y calles
        de rodaje planas no dan sombra y así no se sombrean a sí mismas)."""
        self.vao_casters = None
        self.sh2_tex = self.sh2_fbo = None
        self.sh2_k = 0.0
        self._sh2_key = None
        objs = np.asarray(self.scn.objects, np.float32)
        if self.m_parked is not None:
            objs = np.vstack([objs, np.asarray(self.scn.parked_code, np.float32)])
        bm = getattr(self.scn, "buildings_mesh", None)
        if bm is not None and len(bm):                   # edificios con fachada: dan sombra igual
            objs = np.vstack([objs, np.asarray(bm, np.float32)[:, :9]])
        tri = objs.reshape(-1, 3, 9)
        if len(tri) == 0 and not self.parked_real and not self.buildings_model and not self.tree_vaos:
            return
        cen = tri[:, :, :3].mean(axis=1)
        nz = np.abs(tri[:, :, 5].mean(axis=1))
        T = self.world.terrain
        above = -cen[:, 2] - T.height_v(cen[:, 0], cen[:, 1])
        keep = ~((nz > 0.9) & (above < 1.0))
        pos = np.ascontiguousarray(tri[keep][:, :, :3].reshape(-1, 3), np.float32)
        if len(pos) == 0:
            pos = np.zeros((3, 3), np.float32)             # solo aviones estacionados
        self.vbo_casters = self.ctx.buffer(pos.tobytes())
        self.vao_casters = self.ctx.vertex_array(self.p_shadow, [(self.vbo_casters, "3f", "in_pos")])
        try:
            self._set_sh2_size(2048)
        except Exception as ex:
            print("Sin sombras del escenario:", ex)
            self.sh2_tex = self.sh2_fbo = None

    def _set_sh2_size(self, size):
        if self.sh2_tex is not None and self.sh2_tex.size[0] == size:
            return
        if self.sh2_fbo is not None:
            self.sh2_fbo.release()
            self.sh2_tex.release()
        t_ = self.ctx.depth_texture((size, size))
        t_.compare_func = "<="
        t_.filter = (moderngl.LINEAR, moderngl.LINEAR)
        t_.repeat_x = t_.repeat_y = False
        self.sh2_fbo = self.ctx.framebuffer(depth_attachment=t_)
        self.sh2_tex = t_
        self._sh2_key = None

    def _static_shadow_pass(self, env, cam):
        """Sombras de hangares, edificios y árboles en una caja de 2,4 km un poco por delante de la cámara. El mapa
        se rehace solo si la cámara se movió más de 200 m o el Sol cambió de lugar."""
        self.sh2_k = 0.0
        if self.sh2_fbo is None or self.vao_casters is None:
            return
        sun = np.asarray(env["sun"], np.float64)
        up = -sun[2]
        k = 0.85 * env["day"] * (1.0 - 0.85 * env["overcast"]) * smoothstep(0.03, 0.16, up)
        if k < 0.02 or env["incloud"]:
            return
        T = self.world.terrain
        eye = np.asarray(cam.eye, np.float64)
        gnd = max(T.height_tri(eye[0], eye[1]), 0.0)
        if -eye[2] - gnd > 2500.0:                   # muy alto: las sombras del suelo ya no se distinguen
            return
        fwd = np.array([cam.fwd[0], cam.fwd[1]], np.float64)
        fl = np.linalg.norm(fwd)
        ahead = fwd / fl * SH2_RAD * 0.45 if fl > 1e-3 else np.zeros(2)
        cx = round((eye[0] + ahead[0]) / 200.0) * 200.0
        cy = round((eye[1] + ahead[1]) / 200.0) * 200.0
        key = (cx, cy, tuple(np.round(sun, 3)))
        if key != self._sh2_key:
            self._sh2_key = key
            c = np.array([cx, cy, -max(T.height_tri(cx, cy), 0.0)])
            dist = 3000.0
            upv = np.array((1.0, 0.0, 0.0) if abs(sun[0]) < 0.9 else (0.0, 1.0, 0.0))
            V = look_dir(c + sun * dist, -sun, upv)
            n, f = 10.0, dist + 3000.0
            O = np.identity(4)
            O[0, 0] = O[1, 1] = 1.0 / SH2_RAD
            O[2, 2] = -2.0 / (f - n)
            O[2, 3] = -(f + n) / (f - n)
            LV = O @ V
            B = np.array([[0.5, 0, 0, 0.5], [0, 0.5, 0, 0.5], [0, 0, 0.5, 0.5], [0, 0, 0, 1.0]])
            self.sh2_mat = B @ LV
            ctx = self.ctx
            self.sh2_fbo.use()
            ctx.scissor = None
            ctx.viewport = (0, 0, *self.sh2_tex.size)
            self.sh2_fbo.clear(depth=1.0)
            self.p_shadow["u_lmvp"].write(gl_bytes(LV))
            self.vao_casters.render()
            for _vao, _tex, _m, svao in (self.buildings_model or ()):    # hangares y torres
                if svao is not None:
                    svao.render()
            if self.tree_vaos:                           # árboles (instancias)
                self.p_shadow_tree["u_lmvp"].write(gl_bytes(LV))
                for _vao, svao, _ib, n, _nv in self.tree_vaos.values():
                    if n:
                        svao.render(instances=n)
            for model, M in self.parked_real:            # aviones estacionados (modelos reales)
                self.p_shadow["u_lmvp"].write(gl_bytes(LV @ M))
                for _vao, _tex, _m, svao in model:
                    if svao is not None:
                        svao.render()
        self.sh2_k = float(k)

    # ------------------------------------------------------------ relieve fino alrededor del avión
    def _update_patch(self, pos):
        T = self.world.terrain
        if self._patch_T is not T:
            self._release_patch()
            self._patch_T = T
            self._patch_job = None
        ci = int(round((pos[0] + T.half) / T.cell))
        cj = int(round((pos[1] + T.half) / T.cell))
        job = self._patch_job
        if job is not None and job.done():
            self._patch_job = None
            try:
                self._set_patch(job.result(), job.center)
            except Exception as ex:
                print("Malla fina del terreno:", ex)
        p = self.patch
        if p is not None and max(abs(ci - p["c"][0]), abs(cj - p["c"][1])) <= PATCH_MOVE:
            return
        if not (PATCH_HALF // 2 < ci < T.n - PATCH_HALF // 2 and PATCH_HALF // 2 < cj < T.n - PATCH_HALF // 2):
            self._release_patch()
            return
        if p is None:                                 # la primera vez se arma enseguida
            self._set_patch(build_terrain_patch(T, ci, cj), (ci, cj))
        elif self._patch_job is None:                 # después, en segundo plano (sin tirones)
            if self._patch_pool is None:
                from concurrent.futures import ThreadPoolExecutor
                self._patch_pool = ThreadPoolExecutor(max_workers=1)
            self._patch_job = self._patch_pool.submit(build_terrain_patch, T, ci, cj)
            self._patch_job.center = (ci, cj)

    def _set_patch(self, res, center):
        self._release_patch()
        if res is None:
            return
        verts, idx, cells = res
        self.patch = dict(mesh=GPUMesh(self.ctx, self.p_terrain, verts, index=idx), cells=cells, c=center)

    def _release_patch(self):
        if self.patch is not None:
            self.patch["mesh"].release()
        self.patch = None

    def _draw_terrain(self):
        """Malla gruesa sin las celdas que cubre la malla fina, y la malla fina."""
        p = self.patch
        if p is None:
            self.m_terrain.render()
            return
        vao = self.m_terrain.vao
        nq = self.world.terrain.n - 1
        i0, i1, j0, j1 = p["cells"]
        if i0 > 0:
            vao.render(vertices=6 * i0 * nq, first=0)
        for i in range(i0, i1):
            if j0 > 0:
                vao.render(vertices=6 * j0, first=6 * i * nq)
            if j1 < nq:
                vao.render(vertices=6 * (nq - j1), first=6 * (i * nq + j1))
        if i1 < nq:
            vao.render(vertices=6 * (nq - i1) * nq, first=6 * i1 * nq)
        p["mesh"].render()

    def _post(self, env, proj, rot_view):
        """Resplandor de las luces y del Sol (a 1/4 de resolución) y datos del destello y la gradación."""
        ctx = self.ctx
        pc = self.p_comp
        if not self.effects:
            pc["u_fx"].value = 0.0
            return
        night, day = float(env["night"]), float(env["day"])
        self._ensure_bloom()
        (t0, f0), (t1, f1) = self.bloom
        bw, bh = t0.size
        sw, sh_ = self.tex_res.size
        ctx.disable(moderngl.DEPTH_TEST)
        ctx.scissor = None
        ctx.viewport = (0, 0, bw, bh)
        f0.use()
        self.tex_res.use(0)
        pb = self.p_bright
        pb["u_tex"] = 0
        pb["u_texel"].value = (1.0 / sw, 1.0 / sh_)
        pb["u_thr"].value = float(lerp(0.94, 0.68, night))
        self.vao_bright.render()
        pl = self.p_blur
        pl["u_tex"] = 0
        for _ in range(2):
            f1.use()
            t0.use(0)
            pl["u_dir"].value = (1.0 / bw, 0.0)
            self.vao_blur.render()
            f0.use()
            t1.use(0)
            pl["u_dir"].value = (0.0, 1.0 / bh)
            self.vao_blur.render()
        pc["u_fx"].value = 1.0
        pc["u_bloom"] = 1
        pc["u_bloom_k"].value = float(lerp(0.12, 0.6, night) * (0.6 if env["incloud"] else 1.0))
        # tono de la luz: dorado con el Sol bajo, neutro a mediodía, azulado de noche
        dusk = float(env.get("dusk", 0.0)) * (1.0 - env["overcast"])
        g = mix3((1.0, 1.0, 1.0), (1.08, 0.99, 0.86), dusk * 0.85)
        g = mix3(g, (0.9, 0.97, 1.1), night * 0.75)
        pc["u_grade"].value = tuple(float(c) for c in g)
        pc["u_contrast"].value = float(lerp(0.12, 0.06, night) * (1.0 - 0.4 * env["overcast"]))
        pc["u_sat"].value = float(lerp(1.08, 1.0, max(night, env["overcast"])))
        sun = np.asarray(env["sun"], np.float64)
        clip = proj @ rot_view @ np.array([sun[0], sun[1], sun[2], 0.0])
        flare = 0.0
        sx = sy = -1.0
        if clip[3] > 1e-6 and not env["incloud"]:
            sx, sy = clip[0] / clip[3] * 0.5 + 0.5, clip[1] / clip[3] * 0.5 + 0.5
            edge = min(sx, 1.0 - sx, sy, 1.0 - sy)
            flare = day * (1.0 - env["overcast"]) * smoothstep(-0.02, 0.05, -sun[2]) * smoothstep(-0.02, 0.06, edge)
        pc["u_sun_uv"].value = (float(sx), float(sy), float(flare))
        pc["u_aspect"].value = float(sw / max(sh_, 1))
        t0.use(1)

    def _ensure_fbo(self, W=None, H=None):
        """Búfer de dibujo del tamaño de la vista 3D (no de toda la ventana): con la franja de instrumentos
        abajo se dibuja y se resuelve el antialiasing solo donde se ve el paisaje."""
        if W is None:
            W, H = self.size
        sw, sh = max(16, int(W * self.rscale)), max(16, int(H * self.rscale))
        if self.tex_res is not None and self.tex_res.size == (sw, sh):
            return
        for o in (self.fbo_ms, self.fbo_res, self.tex_res):
            if o is not None:
                o.release()
        ctx = self.ctx
        self.tex_res = ctx.texture((sw, sh), 4)
        self.tex_res.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.fbo_res = ctx.framebuffer([self.tex_res])
        try:
            if self.samples > 1:
                rb = ctx.renderbuffer((sw, sh), 4, samples=self.samples)
                db = ctx.depth_renderbuffer((sw, sh), samples=self.samples)
                self.fbo_ms = ctx.framebuffer([rb], db)
            else:
                raise RuntimeError
        except Exception:
            self.samples = 0
            self.fbo_ms = ctx.framebuffer([self.tex_res], ctx.depth_renderbuffer((sw, sh)))

    # ------------------------------------------------------------ superposición
    def ensure_overlay(self, size):
        if self.t_overlay is not None and self.t_overlay.size == tuple(size):
            return
        if self.t_overlay is not None:
            self.t_overlay.release()
        self.t_overlay = self.ctx.texture(tuple(size), 4, bytes(size[0] * size[1] * 4))
        self.t_overlay.filter = (moderngl.NEAREST, moderngl.NEAREST)
        self._ov_prev = None
        self.overlay_swizzle = None
        self.size = tuple(size)

    # ------------------------------------------------------------ imagen de fondo (en la GPU): fondo de los menús
    PHOTO_VS = """
#version 330
in vec2 in_pos;
uniform vec4 u_rect;
out vec2 v_uv;
void main() {
    v_uv = in_pos;
    gl_Position = vec4(mix(u_rect.x, u_rect.z, in_pos.x), mix(u_rect.y, u_rect.w, in_pos.y), 0.0, 1.0);
}
"""
    PHOTO_FS = """
#version 330
uniform sampler2D u_tex;
in vec2 v_uv;
out vec4 f_color;
void main() { f_color = texture(u_tex, v_uv); }
"""

    def set_photo(self, surf, rect):
        """Imagen a dibujar este fotograma, debajo de la superposición (None la quita).
        La imagen se sube una sola vez; el escalado y el zoom los hace la tarjeta gráfica."""
        if surf is None:
            self.photo_draw = None
            return
        import pygame
        if getattr(self, "_photo_src", None) is not surf:
            if getattr(self, "t_photo", None) is not None:
                self.t_photo.release()
            # alfa premultiplicado: los píxeles recortados (verde croma) no tiñen los bordes al escalar
            arr = np.frombuffer(pygame.image.tobytes(surf, "RGBA"), np.uint8).reshape(-1, 4).astype(np.uint16)
            arr[:, :3] = arr[:, :3] * arr[:, 3:4] // 255
            self.t_photo = self.ctx.texture(surf.get_size(), 4, arr.astype(np.uint8).tobytes())
            self.t_photo.build_mipmaps()
            self.t_photo.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
            self.t_photo.anisotropy = 4.0
            self._photo_src = surf
            if not hasattr(self, "p_photo"):
                self.p_photo = self.ctx.program(vertex_shader=self.PHOTO_VS, fragment_shader=self.PHOTO_FS)
                vb = self.ctx.buffer(np.array([0, 0, 1, 0, 1, 1, 0, 0, 1, 1, 0, 1], "f4").tobytes())
                self.vao_photo = self.ctx.vertex_array(self.p_photo, [(vb, "2f", "in_pos")])
        self.photo_draw = rect

    def _draw_photo(self):
        rect = getattr(self, "photo_draw", None)
        if rect is None:
            return
        W, H = self.size
        x, y, w, h = rect
        ctx = self.ctx
        ctx.screen.use()
        ctx.viewport = (0, 0, W, H)
        ctx.disable(moderngl.DEPTH_TEST)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
        self.t_photo.use(0)
        self.p_photo["u_tex"] = 0
        self.p_photo["u_rect"].value = (x / W * 2 - 1, 1 - y / H * 2, (x + w) / W * 2 - 1, 1 - (y + h) / H * 2)
        self.vao_photo.render()
        ctx.disable(moderngl.BLEND)
        ctx.enable(moderngl.DEPTH_TEST)
        self.photo_draw = None

    def draw_overlay(self, surf):
        self.ensure_overlay(surf.get_size())
        self._draw_photo()
        if self.overlay_swizzle is None:
            masks = surf.get_masks()
            if masks[:3] == (0xFF0000, 0xFF00, 0xFF):
                self.overlay_swizzle = "BGRA"
            elif masks[:3] == (0xFF, 0xFF00, 0xFF0000):
                self.overlay_swizzle = "RGBA"
            else:
                self.overlay_swizzle = "copy"
            if self.overlay_swizzle in ("BGRA", "RGBA"):
                self.t_overlay.swizzle = self.overlay_swizzle
        import pygame
        # zona con contenido: búsqueda rápida sobre el canal alfa submuestreado
        a = pygame.surfarray.pixels_alpha(surf)
        sub = a[::4, ::4]
        cols = np.flatnonzero(sub.any(axis=1))
        rows = np.flatnonzero(sub.any(axis=0))
        del a, sub
        if len(cols) and len(rows):
            W_, H_ = surf.get_size()
            x0 = max(0, cols[0] * 4 - 4)
            x1 = min(W_, cols[-1] * 4 + 8)
            y0 = max(0, rows[0] * 4 - 4)
            y1 = min(H_, rows[-1] * 4 + 8)
            bb = pygame.Rect(x0, y0, x1 - x0, y1 - y0)
        else:
            bb = pygame.Rect(0, 0, 0, 0)
        prev = getattr(self, "_ov_prev", None)
        region = bb.union(prev) if (prev is not None and prev.w and prev.h) else bb
        self._ov_prev = bb
        if region.w == 0 or region.h == 0:
            return
        W_, H_ = surf.get_size()
        pitch = surf.get_pitch()
        if self.overlay_swizzle != "copy" and pitch == W_ * 4:
            # franja de filas completas: es un trozo contiguo de memoria, se sube sin copiar
            y0, y1 = region.y, min(H_, region.bottom)
            view = surf.get_view("1")
            data = np.frombuffer(view, np.uint8)[y0 * pitch:y1 * pitch]
            self.t_overlay.write(data, viewport=(0, y0, W_, y1 - y0))
            del data, view
        else:
            fmt = "RGBA" if self.overlay_swizzle in ("copy", "RGBA") else "BGRA"
            data = pygame.image.tobytes(surf.subsurface(region), fmt)
            self.t_overlay.write(data, viewport=(region.x, region.y, region.w, region.h))
        ctx = self.ctx
        ctx.screen.use()
        ctx.viewport = (0, 0, *self.size)
        ctx.disable(moderngl.DEPTH_TEST)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self.t_overlay.use(0)
        self.p_overlay["u_tex"] = 0
        self.vao_overlay.render()
        ctx.disable(moderngl.BLEND)
        ctx.enable(moderngl.DEPTH_TEST)

    # ------------------------------------------------------------ entorno
    def _puff_inside(self, eye):
        """0..1: cuánto está la cámara dentro de un cúmulo suelto (1 = en pleno blanco)."""
        P = getattr(self, "_cloud_np", None)
        if P is None or eye is None or not len(P):
            return 0.0
        d = np.sqrt(((P[:, :3] - np.asarray(eye, np.float32)) ** 2).sum(axis=1)) / (P[:, 3] * 0.7)
        m = float(d.min())
        return 0.0 if m >= 1.0 else float(smoothstep(1.0, 0.45, m))

    def environment(self, cam_alt, eye=None):
        w = self.world.weather
        hour = w.hour % 24
        # Sol y Luna reales para la fecha, la hora local y el lugar del escenario
        import datetime as _dt
        from sim import astro
        loc = getattr(self.world, "location", None) or {}
        date = w.date or _dt.date.today()
        key = (round(hour, 3), date, loc.get("lat0"), loc.get("lon0"))
        if getattr(self, "_astro_key", None) != key:
            self._astro_key = key
            self._astro = astro.sky(loc.get("lat0", 10.25), loc.get("lon0", -67.65), loc.get("country", "VE"), date, hour)
        se, sa, me, ma, mk = self._astro
        el, az = math.radians(se), math.radians(sa)
        sun = np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), -math.sin(el)])
        mel, maz = math.radians(me), math.radians(ma)
        moon = np.array([math.cos(mel) * math.cos(maz), math.cos(mel) * math.sin(maz), -math.sin(mel)])
        eld = math.degrees(el)
        day = smoothstep(-6.0, 10.0, eld)
        dusk = smoothstep(-8.0, 2.0, eld) * (1.0 - smoothstep(2.0, 22.0, eld))
        night = 1.0 - smoothstep(-10.0, 0.0, eld)
        top_m = w.cloud_top_ft * 0.3048
        ov = smoothstep(0.6, 0.98, w.cloud_cover) * (1.0 - smoothstep(top_m - 30.0, top_m + 120.0, cam_alt))
        zen = mix3((0.015, 0.022, 0.055), (0.20, 0.40, 0.78), day)
        hor = mix3((0.06, 0.07, 0.11), (0.70, 0.80, 0.92), day)
        hor = mix3(hor, (0.98, 0.62, 0.38), dusk * 0.85)
        zen = mix3(zen, (0.30, 0.34, 0.55), dusk * 0.4)
        grey = mix3((0.04, 0.045, 0.06), (0.62, 0.65, 0.68), day)
        zen = mix3(zen, grey, ov * 0.85)
        hor = mix3(hor, grey, ov * 0.85)
        sun_col = mix3((0.0, 0.0, 0.0), (0.92, 0.89, 0.82), day)
        sun_col = mix3(sun_col, (1.0, 0.58, 0.32), dusk * 0.7)
        sun_col = tuple(c * (1.0 - 0.75 * ov) for c in sun_col)
        # bajo un cielo cubierto o en la niebla la luz es gris: sin el tono anaranjado del amanecer
        lum = sum(sun_col) / 3.0
        sun_col = mix3(sun_col, (lum, lum, lum), ov)
        amb = mix3((0.075, 0.085, 0.13), (0.36, 0.41, 0.48), day)
        amb = mix3(amb, (0.55, 0.57, 0.6), ov * day * 0.6)
        # luz de la Luna: con luna llena alta se distingue el paisaje; sin luna la noche es muy oscura
        moon_light = night * mk * smoothstep(-2.0, 25.0, me) * (1.0 - 0.8 * ov)
        amb = tuple(c * (0.55 + 0.45 * mk if night > 0.5 else 1.0) + moon_light * k
                    for c, k in zip(amb, (0.05, 0.06, 0.085)))
        atmo = self.world.atmo
        rain = float(getattr(atmo, "rain_here", 0.0))
        if rain > 0.01:
            # bajo la lluvia: cielo gris plomizo, sin sol directo y todo más apagado
            wet_grey = mix3((0.03, 0.035, 0.045), (0.42, 0.45, 0.48), day)
            zen = mix3(zen, wet_grey, rain * 0.8)
            hor = mix3(hor, mix3(wet_grey, (0.55, 0.58, 0.6), day * 0.5), rain * 0.8)
            sun_col = tuple(c * (1.0 - 0.7 * rain) for c in sun_col)
            amb = tuple(c * (1.0 - 0.25 * rain) for c in amb)
            ov = max(ov, min(1.0, rain * 1.3))        # sin estrellas ni sol bajo la lluvia
        flash = float(getattr(atmo, "flash", 0.0))
        if flash > 0.01:
            # relámpago: todo se ilumina un instante con luz blanca azulada
            amb = tuple(c + flash * k for c, k in zip(amb, (0.32, 0.35, 0.45)))
            zen = tuple(c + flash * k for c, k in zip(zen, (0.2, 0.22, 0.3)))
            hor = tuple(c + flash * k for c, k in zip(hor, (0.26, 0.28, 0.36)))
        # niebla: visibilidad y nubes
        base = w.cloud_base_ft * 0.3048
        top = w.cloud_top_ft * 0.3048
        vis = max(atmo.visibility() if hasattr(atmo, "visibility") else w.visibility_m, 200.0)
        incloud = w.cloud_cover > 0.8 and base < cam_alt < top
        fog_col = hor
        # dentro de la nube: gris de día, oscuro de noche y, al amanecer o al atardecer, con el tono del Sol
        cloud_in = mix3((0.07, 0.07, 0.09), (0.8, 0.82, 0.85), day)
        cloud_in = mix3(cloud_in, tuple(min(1.0, c * 1.05) for c in sun_col), dusk * 0.22)
        if incloud:
            vis = 70.0
            fog_col = cloud_in
        # atravesar un cúmulo suelto: se queda en blanco unos segundos (entrada inadvertida en nube)
        puff = 0.0 if (incloud or w.cloud_cover >= 0.85 or cam_alt < base) else self._puff_inside(eye)
        if puff > 0.0:
            vis = min(vis, 60.0 / max(puff, 1e-3) ** 1.5)
            fog_col = mix3(fog_col, cloud_in, puff)
            ov = max(ov, puff * 0.8)
        self.in_puff = puff
        # luces propias dentro de la nube o de la niebla espesa: la nube devuelve la luz al piloto. Las
        # estroboscópicas dan destellos blancos que desorientan (por eso se apagan en IMC), el anticolisión un pulso
        # rojo y el faro de aterrizaje un resplandor que enceguece; de noche mucho más que de día
        dense = max(1.0 if incloud else puff, clamp((500.0 - vis) / 400.0, 0.0, 1.0))
        sysm = getattr(getattr(self.world, "ac", None), "sys", None)
        if dense > 0.05 and sysm is not None and getattr(sysm, "electric_ok", False):
            lt = getattr(sysm, "lights", {})
            nk = dense * (0.2 + 0.8 * night)
            ph = self.time % 1.2
            glow = (0.0, 0.0, 0.0)
            if lt.get("strobe") and (ph < 0.05 or 0.13 < ph < 0.18):
                glow = (0.6, 0.62, 0.68)
            if lt.get("beacon") and (self.time % 1.0) < 0.12:
                glow = tuple(g + c for g, c in zip(glow, (0.22, 0.02, 0.01)))
            if lt.get("landing") or lt.get("taxi"):
                glow = tuple(g + c for g, c in zip(glow, (0.16, 0.15, 0.13)))
            fog_col = tuple(f + g * nk for f, g in zip(fog_col, glow))
            amb = tuple(a + g * nk * 0.3 for a, g in zip(amb, glow))
        dens = 1.987 / vis + 1.0 / 400000.0
        ground = mix3(hor, (0.25, 0.3, 0.25), 0.3)
        # niebla de valle (la misma que informa el METAR): capa sobre el aeródromo base, blanca y con la luz del día
        gk, gtop, gvis = w.ground_fog()
        home_elev = float(getattr(getattr(self.world, "home", None), "elev", 0.0) or 0.0)
        sun_up = max(-float(sun[2]), 0.0)
        gcol = tuple(min(0.88, a * 1.35 + s_ * 0.5 * (0.3 + sun_up)) for a, s_ in zip(amb, sun_col))
        self.env = dict(gfog=(3.0 / gvis if gk > 0 else 0.0), gfog_top=home_elev + gtop, gfog_col=gcol,
                        fog_glow=(0.0 if incloud else 0.22 * (1.0 - ov * 0.8)),
                        sun=sun, sun_col=sun_col, amb=amb, zen=zen, hor=hor, fog_col=fog_col, fog=dens,
                        fog_base=float(getattr(getattr(self.world, "home", None), "elev", 0.0) or 0.0),
                        fog_scale=(1.0e6 if (incloud or puff > 0.3) else 1400.0 + 1600.0 * rain),
                        night=night, day=day, dusk=dusk, overcast=ov, incloud=incloud, ground=ground, puff=puff,
                        moon=moon, moon_k=mk, moon_on=(1.0 - ov) * smoothstep(-1.0, 1.0, me) * (0.25 + 0.75 * night))
        return self.env

    def _set_common(self, prog, view, proj, cam_pos):
        env = self.env
        prog["u_proj"].write(gl_bytes(proj))
        prog["u_view"].write(gl_bytes(view))
        for name, val in (("u_campos", tuple(cam_pos)), ("u_sun", tuple(env["sun"])), ("u_sun_col", env["sun_col"]),
                          ("u_amb", env["amb"]), ("u_fog_col", env["fog_col"])):
            if name in prog:
                prog[name].value = tuple(float(x) for x in val)
        if "u_fog_density" in prog:
            prog["u_fog_density"].value = float(env["fog"])
        if "u_fog_base" in prog:
            prog["u_fog_base"].value = float(env.get("fog_base", 0.0))
            prog["u_fog_scale"].value = float(env.get("fog_scale", 1400.0))
        if "u_fog_glow" in prog:
            prog["u_fog_glow"].value = float(env.get("fog_glow", 0.0))
        if "u_gfog" in prog:
            prog["u_gfog"].value = float(env.get("gfog", 0.0))
            prog["u_gfog_top"].value = float(env.get("gfog_top", -1e6))
        if "u_gfog_col" in prog:
            prog["u_gfog_col"].value = tuple(float(c) for c in env.get("gfog_col", (0.8, 0.8, 0.8)))
        if "u_logc" in prog:
            prog["u_logc"].value = 2.0 / math.log2(FAR + 1.0)

    # ------------------------------------------------------------ nubes
    def _landing_light(self, env):
        """Intensidad, posición y dirección del foco de aterrizaje (solo se nota de noche o con poca luz)."""
        ac = self.world.ac
        s = ac.sys
        dark = clamp(env["night"] * 1.0 + (1.0 - env["day"]) * 0.3, 0.0, 1.0) if s.electric_ok else 0.0
        kl = dark if s.lights.get("landing") else 0.0
        kt = dark if s.lights.get("taxi") else 0.0
        R = ac.R
        p = ac.pos + R @ np.array([1.2, 0.0, 0.4])
        d = R @ np.array([math.cos(math.radians(5.0)), 0.0, math.sin(math.radians(5.0))])
        dt_ = R @ np.array([math.cos(math.radians(11.0)), 0.0, math.sin(math.radians(11.0))])   # rodaje: más abajo
        return (float(kl), tuple(float(v) for v in p), tuple(float(v) for v in d / np.linalg.norm(d)),
                float(kt), tuple(float(v) for v in dt_ / np.linalg.norm(dt_)))

    def _storm_vaos(self):
        """Cumulonimbo (columna + yunque) y cortina de lluvia, centrados en el origen; se desplazan con u_offset."""
        w = self.world.weather
        key = (round(w.storm_r), round(w.cloud_base_ft), round(self.world.home.elev))
        if getattr(self, "_storm_built", None) is not None and self._storm_key == key:
            return self._storm_built
        self._storm_key = key
        rng = np.random.default_rng(7)
        r = max(w.storm_r, 800.0)
        gnd = max(self.world.home.elev, 0.0)
        base = max(w.cloud_base_ft * 0.3048, gnd + 500.0)
        top = gnd + 11000.0
        tower, shaft = [], []
        for _ in range(210):
            h = base + (top - base) * rng.uniform(0.0, 1.0) ** 0.8
            f = (h - base) / (top - base)
            rad = r * (0.75 + 0.25 * f) if f < 0.82 else r * (1.0 + 2.4 * (f - 0.82) / 0.18)
            a = rng.uniform(0, 2 * math.pi)
            q = rad * math.sqrt(rng.uniform(0.0, 1.0))
            size = rng.uniform(1100, 1900) * (1.0 + 0.6 * f)
            tower.append((q * math.cos(a), q * math.sin(a), -h, size, 0.2 + 0.8 * f, float(rng.integers(0, 3))))
        for _ in range(55):
            h = gnd + (base - gnd) * rng.uniform(0.0, 1.0)
            a = rng.uniform(0, 2 * math.pi)
            q = r * 0.8 * math.sqrt(rng.uniform(0.0, 1.0))
            shaft.append((q * math.cos(a), q * math.sin(a), -h, rng.uniform(700, 1100), 0.0, float(rng.integers(0, 3))))
        out = []
        for inst in (tower, shaft):
            arr = np.array(inst, np.float32)
            vbo = self.ctx.buffer(arr.tobytes())
            vao = self.ctx.vertex_array(self.p_cloud, [(self.vbo_corners, "2f", "in_corner"),
                                                        (vbo, "4f 1f 1f/i", "in_center", "in_shade", "in_var")])
            out.append((vao, len(arr)))
        self._storm_built = out
        return out

    def _draw_storm(self, cam, env):
        w = self.world.weather
        (tower, n_t), (shaft, n_s) = self._storm_vaos()
        pc = self.p_cloud
        self.ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
        right = np.cross(cam.fwd, cam.up)
        right /= np.linalg.norm(right)
        up = np.cross(right, cam.fwd)
        pc["u_right"].value = tuple(float(v) for v in right)
        pc["u_up"].value = tuple(float(v) for v in up)
        self.t_cloud.use(2)
        pc["u_tex"] = 2
        pc["u_nvar"].value = float(self.n_cloud_var)
        pc["u_offset"].value = (float(w.storm_n), float(w.storm_e), 0.0)
        pc["u_alpha"].value = 0.55
        pc["u_cbase"].value = -1.0e6
        pc["u_dark"].value = 0.42
        shaft.render(instances=n_s, vertices=6)
        pc["u_alpha"].value = 0.97
        # el relámpago ilumina la nube por dentro
        pc["u_dark"].value = 0.62 + 2.5 * float(getattr(self.world.atmo, "flash", 0.0))
        tower.render(instances=n_t, vertices=6)
        pc["u_offset"].value = (0.0, 0.0, 0.0)
        pc["u_dark"].value = 1.0

    # ------------------------------------------------------------ sombras de las nubes sobre el suelo
    CLOUD_UNIT = 13
    CLOUD_RECT = (-34000.0, -34000.0, 68000.0, 0.0)
    CLOUD_RES = 1024

    def _cloud_coverage(self, inst):
        """Cobertura de las nubes vista desde arriba (0..1) en una grilla de 66 m: una mancha suave por cada copo."""
        n = self.CLOUD_RES
        x0, y0, side = self.CLOUD_RECT[:3]
        k = n / side
        cov = np.zeros((n, n), np.float32)
        for (px, py, _z, size, _sh, _v) in inst:
            r = size * 1.0 * k                       # el copo se ve de unos 2 tamaños de ancho
            ci, cj = (px - x0) * k, (py - y0) * k
            i0, i1 = int(max(ci - r - 1, 0)), int(min(ci + r + 2, n))
            j0, j1 = int(max(cj - r - 1, 0)), int(min(cj + r + 2, n))
            if i0 >= i1 or j0 >= j1:
                continue
            I, J = np.meshgrid(np.arange(i0, i1), np.arange(j0, j1), indexing="ij")
            d2 = ((I - ci) ** 2 + (J - cj) ** 2) / max(r * r, 1e-6)
            blob = np.clip(1.0 - d2, 0.0, 1.0) ** 1.5
            cov[i0:i1, j0:j1] = 1.0 - (1.0 - cov[i0:i1, j0:j1]) * (1.0 - blob * 0.9)
        return cov

    def _update_cloud_shadows(self, env):
        w = self.world.weather
        k = 0.55 * env["day"] * (1.0 - env["overcast"]) * smoothstep(0.05, 0.2, -float(env["sun"][2]))
        self.cloud_shadow_k = float(k) if (getattr(self, "t_cloudmap", None) is not None and w.cloud_cover > 0.02
                                          and w.cloud_cover < 0.85) else 0.0
        self.cloud_shadow_alt = float(w.cloud_base_ft * 0.3048)
        if getattr(self, "t_cloudmap", None) is not None:
            self.t_cloudmap.use(self.CLOUD_UNIT)

    def _update_clouds(self):
        w = self.world.weather
        key = (round(w.cloud_cover, 2), round(w.cloud_base_ft), round(w.cloud_top_ft))
        if key == self.cloud_key:
            return
        self.cloud_key = key
        rng = np.random.default_rng(99)
        cov = w.cloud_cover
        base = w.cloud_base_ft * 0.3048
        top = max(w.cloud_top_ft * 0.3048, base + 150)
        inst = []
        if cov > 0.02:
            # cúmulos en grupos: vistos desde arriba cubren más o menos la fracción del METAR (FEW, SCT, BKN), así el
            # cielo y las sombras en el suelo corresponden a lo que se informa
            scattered = cov < 0.85
            n_cl = int(cov * 900) if scattered else 260
            half = 26000.0 if scattered else 30000.0
            cx = rng.uniform(-half, half, n_cl)
            cy = rng.uniform(-half, half, n_cl)
            for i in range(n_cl):
                k = rng.integers(3, 7) if scattered else rng.integers(2, 5)
                ext = rng.uniform(600, 1400) * (0.6 + cov)
                for j in range(k):
                    px = cx[i] + rng.normal(0, ext * 0.45)
                    py = cy[i] + rng.normal(0, ext * 0.45)
                    hz = base + (top - base) * rng.uniform(0.1, 0.6) ** 1.4
                    size = rng.uniform(380, 820) * (0.7 + 0.6 * (hz - base) / (top - base + 1))
                    shade = 0.35 + 0.65 * (hz - base) / (top - base + 1)
                    inst.append((px, py, -(hz + size * 0.2), size, shade, float(rng.integers(0, 3))))
            if cov >= 0.85:
                g = np.arange(-32000, 32001, 1100.0)
                for x in g:
                    for y in g:
                        if x * x + y * y > 33000 ** 2:
                            continue
                        for lvl in (0.15, 0.6):
                            hz = base + (top - base) * lvl
                            inst.append((x + rng.uniform(-300, 300), y + rng.uniform(-300, 300), -hz,
                                         rng.uniform(900, 1250), 0.3 + 0.6 * lvl, float(rng.integers(0, 3))))
        if self.vao_cloud is not None:
            self.vao_cloud.release()
            self.vbo_cloud_inst.release()
            self.vao_cloud = None
        self.n_clouds = len(inst)
        self._cloud_np = np.array([(i[0], i[1], i[2], i[3]) for i in inst], np.float32) if inst and cov < 0.85 else None
        # mapa de cobertura para las sombras de las nubes (con cielo cubierto no hace falta: la luz es difusa)
        if getattr(self, "t_cloudmap", None) is not None:
            self.t_cloudmap.release()
            self.t_cloudmap = None
        if inst and cov < 0.85:
            cmap = self._cloud_coverage(inst)
            # filas = x (norte), columnas = y (este): la textura se lee con uv = (x, y)
            self.t_cloudmap = self.ctx.texture((self.CLOUD_RES, self.CLOUD_RES), 1,
                                               np.ascontiguousarray((cmap.T * 255).astype(np.uint8)).tobytes())
            self.t_cloudmap.build_mipmaps()
            self.t_cloudmap.repeat_x = self.t_cloudmap.repeat_y = False
        if self.n_clouds:
            arr = np.array(inst, np.float32)
            self.vbo_cloud_inst = self.ctx.buffer(arr.tobytes())
            self.vao_cloud = self.ctx.vertex_array(self.p_cloud, [
                (self.vbo_corners, "2f", "in_corner"),
                (self.vbo_cloud_inst, "4f 1f 1f/i", "in_center", "in_shade", "in_var")])

    # ------------------------------------------------------------ dibujo principal
    def render(self, cam, viewport, extra=None, pose=None, show_aircraft=True, dt=0.016, cockpit=None):
        """Dibuja la escena 3D en 'viewport' (x, y, w, h en píxeles GL)."""
        ctx = self.ctx
        world = self.world
        ac = world.ac
        self.time += dt
        extra = extra or {}
        if self.ac_type_id != ac.t.id:
            self.build_aircraft()
            self.cockpit.configure(ac.t)
        screen_vp = viewport
        self._ensure_fbo(viewport[2], viewport[3])
        env = self.environment(-cam.eye[2], cam.eye)
        if pose is None:
            pos, R = ac.pos, ac.R
        else:
            pos, R = pose[0], quat_to_mat(pose[1])
        body_M = model_matrix(R, pos)
        self._update_patch(pos)
        self._update_trees(cam.eye)
        self._shadow_pass(env, body_M, pos, show_aircraft)
        self._static_shadow_pass(env, cam)
        self.fbo_ms.use()
        x, y, w, h = 0, 0, self.tex_res.size[0], self.tex_res.size[1]
        viewport = (x, y, w, h)
        ctx.viewport = viewport
        ctx.scissor = viewport
        ctx.clear(*env["hor"], 1.0, depth=1.0)
        aspect = w / max(h, 1)
        fovy = cam.fov
        if cam.mode == "cabina":
            # en cabina el campo de visión se define en horizontal (como en los simuladores comerciales)
            fovy = math.degrees(2 * math.atan(math.tan(math.radians(cam.fov) / 2) / aspect))
        self.fovy = fovy
        proj = perspective(fovy, aspect, cam.near, FAR)
        if cam.mode == "cabina" and getattr(cam, "shift_y", 0.0):
            proj[1, 2] = float(cam.shift_y)          # visión 1:1: el centro de la pantalla queda bajo el ojo
        view = look_dir(cam.eye, cam.fwd, cam.up)
        self.last_view, self.last_proj, self.last_viewport = view, proj, screen_vp
        rot_view = view.copy()
        rot_view[:3, 3] = 0
        inv = np.linalg.inv(proj @ rot_view)

        # cielo
        ctx.disable(moderngl.DEPTH_TEST)
        ps = self.p_sky
        ps["u_inv"].write(gl_bytes(inv))
        ps["u_sun"].value = tuple(float(v) for v in env["sun"])
        ps["u_sun_col"].value = env["sun_col"]
        pf = 1.0 if env["incloud"] else float(env.get("puff", 0.0))     # dentro de la nube no se ve el cielo
        ps["u_zenith"].value = mix3(env["zen"], env["fog_col"], pf)
        ps["u_horizon"].value = mix3(env["hor"], env["fog_col"], pf)
        ps["u_ground"].value = mix3(env["ground"], env["fog_col"], pf)
        ps["u_night"].value = float(env["night"])
        ps["u_overcast"].value = float(env["overcast"])
        if "u_moon" in ps:
            ps["u_moon"].value = tuple(float(v) for v in env["moon"])
            ps["u_moon_on"].value = float(env["moon_on"]) * (0.0 if env["incloud"] else 1.0)
        self.vao_sky.render()
        ctx.enable(moderngl.DEPTH_TEST)

        # terreno y agua
        for prog in (self.p_terrain, self.p_water, self.p_obj, self.p_tex, self.p_model, self.p_tree, self.p_bldg,
                     self.p_decal, self.p_light, self.p_cloud):
            self._set_common(prog, view, proj, cam.eye)
        if self.sh_tex is not None:
            self.sh_tex.use(self.SH_UNIT)
        if self.sh2_tex is not None:
            self.sh2_tex.use(self.SH2_UNIT)
        self._update_cloud_shadows(env)
        for prog in (self.p_terrain, self.p_obj, self.p_tex, self.p_model, self.p_tree, self.p_bldg, self.p_decal):
            prog["u_sh_on"].value = self.sh_k if prog is not self.p_model else 0.0
            if self.sh_k > 0.0 and prog is not self.p_model:
                prog["u_shmat"].write(gl_bytes(self.sh_mat))
            prog["u_cloud_on"].value = self.cloud_shadow_k
            if self.cloud_shadow_k > 0.0:
                prog["u_cloud_alt"].value = self.cloud_shadow_alt
                prog["u_cloud_rect"].value = self.CLOUD_RECT
            prog["u_sh2_on"].value = self.sh2_k
            if self.sh2_k > 0.0:
                prog["u_shmat2"].write(gl_bytes(self.sh2_mat))
                prog["u_sh2_texel"].value = float(2.0 * SH2_RAD / self.sh2_tex.size[0])
        self.t_detail.use(1)
        self.p_terrain["u_detail"] = 1
        pt = self.p_terrain
        if self.t_grass is not None:
            self.t_grass.use(7)
            pt["u_grass"] = 7
            pt["u_grass_on"].value = 1
            pt["u_grass_gain"].value = self.grass_gain
            if self.t_grass_n is not None:
                self.t_grass_n.use(14)
                pt["u_grass_n"] = 14
            pt["u_grass_nk"].value = 1.0 if self.t_grass_n is not None else 0.0
        if self.sat:
            pt["u_sat_on"].value = 1
            for i, (tex, rect) in enumerate(self.sat[:3]):
                tex.use(3 + i)
                pt[f"u_sat{i}"] = 3 + i
                pt[f"u_rect{i}"].value = rect
        elif "u_sat_on" in pt:
            pt["u_sat_on"].value = 0
        ll = self._landing_light(env)
        for prog in (pt, self.p_tex):
            if "u_ll_on" in prog:
                prog["u_ll_on"].value = ll[0]
                prog["u_ll_pos"].value = ll[1]
                prog["u_ll_dir"].value = ll[2]
                prog["u_tl_on"].value = ll[3]
                prog["u_tl_dir"].value = ll[4]
        if "u_night" in pt:
            pt["u_night"].value = float(env["night"])
        lake = getattr(self, "t_lake", None)
        if "u_water_on" in pt:
            pt["u_water_on"].value = 1 if lake is not None else 0
            if lake is not None:
                lake[0].use(10)
                pt["u_water"] = 10
                pt["u_wrect"].value = lake[1]
                pt["u_time"].value = self.time
        wv = self._wind_vec()
        if "u_wind_vec" in pt:
            pt["u_wind_vec"].value = wv
        self._draw_terrain()
        self.p_water["u_detail"] = 1
        self.p_water["u_time"].value = self.time
        self.p_water["u_wind_vec"].value = wv
        self.m_water.render()

        # pistas
        self.p_tex["u_model"].write(gl_bytes(np.identity(4)))
        self.p_tex["u_detail"] = 1
        self.p_tex["u_tint"].value = (1.0, 1.0, 1.0, 1.0)
        ptx = self.p_tex
        if self.t_asph is not None:
            self.t_asph.use(6)
            ptx["u_asph"] = 6
            ptx["u_asph_on"].value = 1
            ptx["u_asph_gain"].value = self.asph_gain
            for t, unit, name in ((self.t_asph_n, 15, "u_asph_n"), (self.t_conc or self.t_asph, 16, "u_conc"),
                                  (self.t_conc_n, 17, "u_conc_n")):
                if t is not None:
                    t.use(unit)
                    ptx[name] = unit
            ptx["u_conc_gain"].value = self.conc_gain if self.t_conc is not None else self.asph_gain
            ptx["u_asph_nk"].value = 1.0 if self.t_asph_n is not None else 0.0
            ptx["u_conc_nk"].value = 1.0 if self.t_conc_n is not None else 0.0
        # pista mojada: la misma que calcula la atmósfera (la que informa el ATIS y la que usa el frenado)
        wet = float(getattr(world.atmo, "wet", 0.0))
        self._wet = wet
        self.p_tex["u_wet"].value = wet
        for tex, m, kind in self.runway_meshes:
            tex.use(0)
            self.p_tex["u_tex"] = 0
            self.p_tex["u_surf"].value = 1 if kind == "plataforma" else 0
            m.render()
        self.p_tex["u_surf"].value = 0
        self.p_tex["u_wet"].value = 0.0

        # penumbra horneada en el suelo alrededor de hangares y torres: multiplica lo ya dibujado (solo la parte de
        # la luz del cielo; donde da el Sol casi no se nota)
        if self.decals:
            ctx.enable(moderngl.BLEND)
            ctx.blend_func = moderngl.DST_COLOR, moderngl.ZERO
            ctx.fbo.depth_mask = False                    # (moderngl: la máscara es del framebuffer activo)
            for vao, gt in self.decals:
                gt.use(18)
                self.p_decal["u_gao"].value = 18
                vao.render()
            ctx.fbo.depth_mask = True
            ctx.disable(moderngl.BLEND)
            ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA

        # objetos estáticos
        po = self.p_obj
        po["u_model"].write(gl_bytes(np.identity(4)))
        po["u_tint"].value = (1.0, 1.0, 1.0, 1.0)
        po["u_flat"].value = 0.0
        po["u_spec"].value = 0.15
        self.m_objects.render()
        if self.m_parked is not None:
            self.m_parked.render()
        for model, M in self.parked_real:
            self._draw_model(model, M)
        if self.buildings_model:
            self._draw_model(self.buildings_model, np.identity(4))
        if self.m_bldg is not None:                      # edificios y casas con fachada
            self.p_bldg["u_night"].value = float(env["night"])
            self.m_bldg.render()
        self._draw_trees()

        # mangas de viento
        wdir = math.radians(world.weather.wind_dir + 180.0)
        wspd = world.weather.wind_kt
        droop = math.radians(clamp(70.0 - wspd * 4.5, 0.0, 70.0))
        for p in self.scn.windsocks:
            po["u_model"].write(gl_bytes(translate(p)))
            self.m_pole.render()
            M = translate((p[0], p[1], p[2] - 6.8)) @ axis_rotation((0, 0, 1), wdir) @ axis_rotation((0, 1, 0), -droop)
            po["u_model"].write(gl_bytes(M))
            po["u_flat"].value = float(min(0.85, env["night"] * 0.95))   # de noche la ilumina su reflector
            self.m_sock.render()
            po["u_flat"].value = 0.0

        # aros/guías de la misión
        for ring in extra.get("rings", []):
            pos, hdg, radius, col = ring
            M = translate(pos) @ axis_rotation((0, 0, 1), math.radians(hdg)) @ np.diag([radius, radius, radius, 1.0])
            po["u_model"].write(gl_bytes(M))
            po["u_tint"].value = col
            po["u_flat"].value = 0.6
            self.m_ring.render()
        po["u_flat"].value = 0.0
        po["u_tint"].value = (1.0, 1.0, 1.0, 1.0)

        # avión (sin sombra sobre sí mismo)
        po["u_sh_on"].value = 0.0
        inside = cam.mode == "cabina"
        self._cab3d = cockpit is not None
        if show_aircraft:
            self._draw_aircraft(body_M, inside, pose)
            # sombra plana sobre el terreno, solo si la tarjeta no tiene mapa de sombras
            gh = max(world.terrain.height(pos[0], pos[1]), 0.0)
            hgt = -pos[2] - gh
            if self.sh_fbo is None and hgt < 400 and env["day"] > 0.2:
                ctx.enable(moderngl.BLEND)
                ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
                S = np.identity(4)
                S[2, 2] = 0.0
                S[2, 3] = -(gh + 0.12)
                alpha = 0.42 * (1 - hgt / 400) * env["day"] * (1 - env["overcast"] * 0.6)
                po["u_tint"].value = (0.0, 0.0, 0.0, float(alpha))
                po["u_flat"].value = 1.0
                for name in ("body", "gear", "elevator", "rudder", "ail_l", "ail_r", "flap_l", "flap_r"):
                    if name == "gear" and ac.sys.gear_pos < 0.5:
                        continue
                    m, piv, ax = self.ac_meshes[name]
                    po["u_model"].write(gl_bytes(S @ body_M))
                    m.render()
                po["u_tint"].value = (1.0, 1.0, 1.0, 1.0)
                po["u_flat"].value = 0.0
                ctx.disable(moderngl.BLEND)

        # tráfico (y, de lejos, el puntito que vería el piloto)
        self._draw_traffic(cam.eye)
        self._draw_traffic_specks(cam, env, h, fovy, view, proj)

        # luces
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.ONE, moderngl.ONE
        ctx.fbo.depth_mask = False
        px = h / (2 * math.tan(math.radians(fovy) / 2))
        pl = self.p_light
        pl["u_px"].value = float(px)
        bright = clamp(env["night"] * 1.2 + (1 - env["day"]) * 0.4 + env["overcast"] * 0.4 + (0.6 if world.atmo.visibility() < 3000 else 0), 0.15, 1.0)
        pl["u_bright"].value = float(bright)
        self._update_dynamic_lights(cam, pos, R, show_aircraft)
        self.vao_lights.render(moderngl.POINTS)
        if self.n_dyn:
            self.vao_dyn.render(moderngl.POINTS, vertices=self.n_dyn)
        self._wet_reflections(cam, env)
        if self.n_refl:
            self.vao_refl.render(moderngl.POINTS, vertices=self.n_refl)
        if self.n_town and env["night"] > 0.3:
            pl["u_bright"].value = float(env["night"])
            self.vao_town.render(moderngl.POINTS)

        # nubes: capa continua si está cubierto
        self._update_clouds()
        w = world.weather
        if w.cloud_cover >= 0.85:
            ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
            self.t_deck.use(0)
            pt = self.p_tex
            pt["u_tex"] = 0
            day = env["day"]
            if "u_asph_on" in pt:
                pt["u_asph_on"].value = 0
            for alt_ft, shade in ((w.cloud_base_ft, 0.55), (w.cloud_top_ft, 1.15)):
                pt["u_model"].write(gl_bytes(translate((0.0, 0.0, -alt_ft * 0.3048))))
                k = shade * (0.25 + 0.75 * day)
                pt["u_tint"].value = (k, k, k, 0.97)
                self.m_deck.render()
            pt["u_model"].write(gl_bytes(np.identity(4)))
            pt["u_tint"].value = (1.0, 1.0, 1.0, 1.0)
        self._draw_smoke(cam, view, proj)
        if self.vao_cloud is not None:
            ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
            pc = self.p_cloud
            right = np.cross(cam.fwd, cam.up)
            right /= np.linalg.norm(right)
            up = np.cross(right, cam.fwd)
            pc["u_right"].value = tuple(float(v) for v in right)
            pc["u_up"].value = tuple(float(v) for v in up)
            self.t_cloud.use(2)
            pc["u_tex"] = 2
            pc["u_alpha"].value = 0.95
            pc["u_nvar"].value = float(self.n_cloud_var)
            pc["u_offset"].value = (0.0, 0.0, 0.0)
            pc["u_dark"].value = 1.0
            pc["u_cbase"].value = float(w.cloud_base_ft * 0.3048)
            self.vao_cloud.render(instances=self.n_clouds, vertices=6)
        if w.storm:
            self._draw_storm(cam, env)
        ctx.fbo.depth_mask = True
        ctx.disable(moderngl.BLEND)
        # cabina 3D por dentro
        if cockpit is not None:
            self.cockpit.draw(view, proj, cam.eye, env, body_M, 2.0 / math.log2(FAR + 1.0),
                              yoke=cockpit.get("yoke", (0.0, 0.0)), night=env["night"],
                              show_yoke=cockpit.get("show_yoke", True))
        ctx.scissor = None
        # resolver el antialiasing y componer en la ventana
        if self.fbo_ms is not self.fbo_res and self.samples > 1:
            ctx.copy_framebuffer(self.fbo_res, self.fbo_ms)
        self._post(env, proj, rot_view)
        (self._photo_target or ctx.screen).use()
        ctx.viewport = screen_vp
        ctx.scissor = screen_vp
        ctx.disable(moderngl.DEPTH_TEST)
        self.tex_res.use(0)
        self.p_comp["u_tex"] = 0
        self.p_comp["u_vp"].value = tuple(float(v) for v in screen_vp)
        self.vao_comp.render()
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.scissor = None
        if self.photo_request is not None and self._photo_target is None:
            req, self.photo_request = self.photo_request, None
            self._take_photo(req, cam, extra, pose, show_aircraft, cockpit)

    # ------------------------------------------------------------ Foto pro
    def _take_photo(self, req, cam, extra, pose, show_aircraft, cockpit):
        """Vuelve a dibujar este mismo cuadro sin tablero ni textos, a 'escala' veces la resolución de la ventana,
        con antialiasing, sombras finas y todos los efectos, y lo guarda en PNG."""
        import pygame
        path, scale = req
        ctx = self.ctx
        W, H = int(self.size[0] * scale), int(self.size[1] * scale)
        saved = (self.rscale, self.samples, self.effects, self.sh_tex.size[0] if self.sh_tex is not None else 2048,
                 self.last_view, self.last_proj, self.last_viewport)
        tex = fbo = None
        try:
            tex = ctx.texture((W, H), 3)
            fbo = ctx.framebuffer([tex])
            self.set_quality(1.0, 4 if W * H <= 4.2e6 else 2)
            self.set_effects(True, 4096)
            self._photo_target = fbo
            self.render(cam, (0, 0, W, H), extra=extra, pose=pose, show_aircraft=show_aircraft, dt=0.0,
                        cockpit=cockpit)
            img = pygame.image.frombytes(fbo.read(components=3), (W, H), "RGB", True)
            pygame.image.save(img, path)
            self.photo_result = (path, None)
        except Exception as ex:
            self.photo_result = (path, str(ex))
        finally:
            self._photo_target = None
            for o in (fbo, tex):
                if o is not None:
                    o.release()
            self.set_quality(saved[0], saved[1])
            self.set_effects(saved[2], saved[3])
            self.last_view, self.last_proj, self.last_viewport = saved[4:]

    def _draw_aircraft(self, body_M, inside, pose):
        po = self.p_obj
        ac = self.world.ac
        s = ac.sys
        t = ac.t
        ang = {
            "elevator": ac.de - ac.trim * t.trim_range,
            "rudder": -ac.dr,
            "ail_l": ac.da,
            "ail_r": -ac.da,
            "flap_l": math.radians(s.flaps),
            "flap_r": math.radians(s.flaps),
        }
        rpms = [e.rpm for e in s.engines]
        if not hasattr(self, "prop_angles"):
            self.prop_angles = [0.0, 0.0]
        for i, r_ in enumerate(rpms[:2]):
            self.prop_angles[i] = (self.prop_angles[i] + r_ / 60.0 * 2 * math.pi * 0.016 * 0.37) % (2 * math.pi)
        real = None if inside else self.aircraft_model(t.id)
        if real is not None:                          # vistas de afuera: el modelo real; desde la cabina, el de código
            self._draw_model(real, body_M)
        po["u_spec"].value = 0.5
        if self.t_skin is not None:
            self.t_skin.use(8)
            po["u_skin_tex"] = 8
            po["u_skin"].value = 1
        for name, (m, piv, ax) in self.ac_meshes.items():
            if real is not None and not name.startswith("disc"):
                continue                                  # con el modelo real solo se añade el disco de la hélice girando
            if inside and name in ("body", "gear", "elevator", "rudder"):
                continue
            if name == "cowl" and not (inside and getattr(self, "_cab3d", False)):
                continue
            if name.startswith("disc") and inside and not getattr(self, "_cab3d", False) and not s.twin:
                continue
            if name == "gear" and s.gear_pos < 0.3:
                continue
            M = body_M
            if name in ang:
                M = body_M @ translate(piv) @ axis_rotation(ax, ang[name]) @ translate(-piv)
            elif name.startswith("prop"):
                k = 1 if name == "prop2" else 0
                rpm = rpms[min(k, len(rpms) - 1)]
                if rpm > 350 or (inside and not s.twin):
                    continue
                M = body_M @ translate(piv) @ axis_rotation(ax, self.prop_angles[k]) @ translate(-piv)
            elif name.startswith("disc"):
                k = 1 if name == "disc2" else 0
                rpm = rpms[min(k, len(rpms) - 1)]
                if rpm <= 350:
                    continue
                self.ctx.enable(moderngl.BLEND)
                self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
                po["u_tint"].value = (1.0, 1.0, 1.0, 0.05 if inside else 0.28)
                po["u_model"].write(gl_bytes(M))
                m.render()
                po["u_tint"].value = (1.0, 1.0, 1.0, 1.0)
                self.ctx.disable(moderngl.BLEND)
                continue
            if name == "gear" and s.gear_pos < 0.98:
                M = body_M @ translate((0, 0, -(1 - s.gear_pos) * 0.6))
            po["u_model"].write(gl_bytes(M))
            m.render()
        po["u_spec"].value = 0.15
        if "u_skin" in po:
            po["u_skin"].value = 0

    def _wet_reflections(self, cam, env):
        """Pista mojada de noche: cada luz de pista se refleja en el pavimento entre ella y el piloto, estirada hacia él
        en una estela (como en una aproximación nocturna con lluvia)."""
        self.n_refl = 0
        wet = float(getattr(self, "_wet", 0.0))
        if wet < 0.05 or max(env["night"], env["overcast"] * 0.6) < 0.25:
            return
        L = self.light_data
        eye = np.asarray(cam.eye, np.float64)
        d = L[:, :2] - eye[:2]
        dist = np.hypot(d[:, 0], d[:, 1])
        sel = (dist < 2500.0) & (dist > 3.0)
        if not sel.any():
            return
        Ls = L[sel].astype(np.float64)
        zg = Ls[:, 2] + 0.4                                   # el suelo, unos 40 cm bajo la luz
        hl = 0.4
        he = np.maximum(zg - eye[2], 0.3)                     # altura del ojo sobre ese suelo
        Lg = Ls[:, :2]
        to_eye = eye[:2] - Lg
        de = np.maximum(np.hypot(to_eye[:, 0], to_eye[:, 1]), 1e-3)
        u = to_eye / de[:, None]
        Rp = Lg + to_eye * (hl / (hl + he))[:, None]           # punto donde se ve el reflejo
        ok = np.zeros(len(Rp), bool)
        for ap in self.scn.aps:
            for rw in ap.runways:
                rel = Rp - rw.center
                a = rel @ rw.dir
                b = rel @ rw.right
                ok |= (np.abs(a) <= rw.length / 2 + 20.0) & (np.abs(b) <= rw.width / 2 + 0.5)
        if not ok.any():
            return
        Rp, u, Ls, zg = Rp[ok], u[ok], Ls[ok], zg[ok]
        dr = np.hypot(*(eye[:2] - Rp).T)
        ln = np.clip(dr * 0.06, 2.0, 45.0)
        out = []
        for k in range(5):
            P = Rp + u * (ln * k / 4.0)[:, None]
            f = 0.42 * wet * (1.0 - k / 5.0) ** 1.3
            arr = np.empty((len(P), 7), np.float32)
            arr[:, 0:2] = P
            arr[:, 2] = zg - 0.08
            arr[:, 3:6] = Ls[:, 3:6] * f
            arr[:, 6] = Ls[:, 6] * 0.7
            out.append(arr)
        data = np.vstack(out)[:3000]
        self.vbo_refl.write(np.ascontiguousarray(data).tobytes())
        self.n_refl = len(data)

    def _update_dynamic_lights(self, cam, pos, R, show_aircraft):
        world = self.world
        L = []
        # PAPI
        for (x, y, z, ang) in self.scn.papis:
            dx, dy = cam.eye[0] - x, cam.eye[1] - y
            hz = z - cam.eye[2]
            el = math.degrees(math.atan2(hz, math.hypot(dx, dy)))
            col = (1.0, 1.0, 1.0) if el > ang else (1.0, 0.08, 0.05)
            L.append((x, y, z, *col, 4.5))
        # señal luminosa de la torre (pistola de luz): un foco muy intenso apuntado al avión desde la cabina de la torre
        lt = getattr(getattr(world, "emerg", None), "light", None)
        if lt is not None and getattr(self.scn, "beacons", None):
            home = getattr(world, "home", None)
            ref = home.ref if home is not None else (0.0, 0.0)
            bx, by, bz = min(self.scn.beacons, key=lambda b: math.hypot(b[0] - ref[0], b[1] - ref[1]))
            col, blink = lt
            ph = int(self.time * 2.0) % 2 == 0
            if col == "alterna":
                col, on = ("rojo" if ph else "verde"), True
            else:
                on = (not blink) or ph
            if on:
                rgb = {"verde": (0.25, 1.0, 0.4), "rojo": (1.0, 0.1, 0.06), "blanco": (1.0, 1.0, 0.95)}[col]
                L.append((bx, by, bz + 3.0, *rgb, 9.0))
        # tránsito nocturno en las carreteras: autos en ambos sentidos; se ven los faros (blancos) de los que vienen
        # hacia el piloto y las luces traseras (rojas) de los que se alejan: referencia para navegar de noche
        if getattr(self.scn, "road_lines", None) and self.env.get("night", 0.0) > 0.3:
            L.extend(self._road_traffic(cam))
        # luces de obstáculo de las antenas: roja intermitente arriba (unos 30 destellos por minuto) y fija a media
        # altura; de noche o con poca luz
        if getattr(self.scn, "masts", None) and (self.env.get("night", 0.0) > 0.25 or self.env.get("overcast", 0.0) > 0.7):
            on = (self.time * 0.5) % 1.0 < 0.45
            for (x, y, gz, h) in self.scn.masts:
                if on:
                    L.append((x, y, gz - h - 0.6, 1.0, 0.08, 0.04, 6.0))
                L.append((x, y, gz - h * 0.5, 0.9, 0.06, 0.03, 3.5))
        # faro giratorio del aeródromo: dos haces opuestos (blanco y verde) que giran 12 veces por minuto; se ve un
        # destello cuando el haz pasa por el observador. Encendido de noche o con poca visibilidad
        if getattr(self.scn, "beacons", None) and (self.env.get("night", 0.0) > 0.25 or self.env.get("overcast", 0.0) > 0.7):
            th = self.time * 2.0 * math.pi * 12.0 / 60.0
            for (x, y, z) in self.scn.beacons:
                a = math.cos(math.atan2(cam.eye[1] - y, cam.eye[0] - x) - th)
                iw, ig = max(a, 0.0) ** 40, max(-a, 0.0) ** 40
                if iw > 0.03:
                    L.append((x, y, z, iw, iw, iw * 0.95, 7.0))
                if ig > 0.03:
                    L.append((x, y, z, 0.1 * ig, ig, 0.35 * ig, 7.0))
        # REIL: dos destellos blancos sincronizados a los lados del umbral (dos por segundo), de noche o con poca luz
        if getattr(self.scn, "reils", None) and (self.env.get("night", 0.0) > 0.2 or self.env.get("overcast", 0.0) > 0.7):
            if (self.time % 0.5) < 0.05:
                for (x, y, z) in self.scn.reils:
                    L.append((x, y, z, 1.0, 1.0, 1.0, 10.0))
        # luces de destello secuencial ("conejo")
        if self.scn.rabbits:
            ph = (self.time * 2.0) % 1.0
            n = len(self.scn.rabbits)
            k = int((1.0 - ph) * n * 1.2)
            for i, (x, y, z, dist) in enumerate(sorted(self.scn.rabbits, key=lambda r: -r[3])):
                if i == k % (n + 4):
                    L.append((x, y, z, 1.0, 1.0, 1.0, 9.0))
        # luces del avión
        if show_aircraft:
            s = world.ac.sys
            lt = self.ac_lights
            if s.electric_ok:
                if s.lights["nav"]:
                    for key, col in (("left", (1.0, 0.1, 0.05)), ("right", (0.1, 1.0, 0.2)), ("tail", (1.0, 1.0, 1.0))):
                        p = pos + R @ np.array(lt[key])
                        L.append((*p, *col, 0.7))
                if s.lights["beacon"] and (self.time % 1.2) < 0.15:
                    p = pos + R @ np.array(lt["beacon"])
                    L.append((*p, 1.0, 0.1, 0.05, 1.4))
                if s.lights["strobe"] and (self.time % 1.0) < 0.06:
                    for key in ("left", "right"):
                        p = pos + R @ np.array(lt[key])
                        L.append((*p, 1.0, 1.0, 1.0, 2.5))
                if s.lights["landing"] and cam.mode != "cabina":
                    p = pos + R @ np.array(lt["landing"])
                    L.append((*p, 1.0, 0.98, 0.9, 1.6))
        # luces del tráfico (navegación, anticolisión, estroboscópicas y de aterrizaje)
        tr = getattr(world, "traffic", None)
        if tr is not None:
            for p in tr.planes:
                if not hasattr(self, "tr_meshes") or not self.tr_meshes:
                    break
                _, lt = self.traffic_mesh(p.type_id, getattr(p, 'livery', None) or hash(p.callsign) % 4)
                Rp = quat_to_mat(p.quat)
                ph = (self.time + (hash(p.callsign) % 100) * 0.013)
                for key, col in (("left", (1.0, 0.1, 0.05)), ("right", (0.1, 1.0, 0.2)), ("tail", (1.0, 1.0, 1.0))):
                    L.append((*(p.pos + Rp @ np.array(lt[key])), *col, 0.8))
                if ph % 1.2 < 0.15:
                    L.append((*(p.pos + Rp @ np.array(lt["beacon"])), 1.0, 0.1, 0.05, 1.5))
                if not p.on_ground and ph % 1.0 < 0.06:
                    for key in ("left", "right"):
                        L.append((*(p.pos + Rp @ np.array(lt[key])), 1.0, 1.0, 1.0, 3.0))
                if not p.on_ground or p.state == "carrera":
                    L.append((*(p.pos + Rp @ np.array(lt["landing"])), 1.0, 0.98, 0.9, 2.2))
        # colores bicolor de los umbrales según el lado desde el que se mira
        data = self.light_data
        for rw, sa, sb in self.scn.light_groups:
            rel = cam.eye[:2] - rw.center
            behind = float(rel @ rw.dir) < 0
            ga = (0.2, 1.0, 0.35) if behind else (1.0, 0.15, 0.1)
            gb = (1.0, 0.15, 0.1) if behind else (0.2, 1.0, 0.35)
            data[sa, 3:6] = ga
            data[sb, 3:6] = gb
        key = tuple(round(float(v), 2) for v in data[[g[1].start for g in self.scn.light_groups], 3])
        if key != getattr(self, "_light_key", None):
            self._light_key = key
            self.vbo_lights.write(data.tobytes())
        arr = np.array(L, np.float32) if L else np.zeros((0, 7), np.float32)
        self.n_dyn = min(len(arr), 256)
        if self.n_dyn:
            self.vbo_dyn.write(arr[:256].tobytes())
