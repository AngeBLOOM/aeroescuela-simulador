"""Convierte un modelo 3D .glb (glTF binario, p. ej. descargado de Sketchfab) al formato del simulador.

    python tools/importar_modelo.py <avión> <archivo.glb> [quitar=material1,material2]
    python tools/importar_modelo.py c172 Descargas/free_cessna_172sp.glb quitar=remove_before_flight,Concrete
    python tools/importar_modelo.py hornear [avión …]      (vuelve a calcular la penumbra de los ya convertidos)

- Lee el .glb sin ejecutar nada de él: el JSON de la escena y los datos binarios (mallas e imágenes).
- Lo pone en los ejes del avión del simulador (x adelante, y a la derecha, z abajo): la mayor medida horizontal es la
  envergadura; la cola es el extremo donde está el punto más alto (la deriva).
- Lo escala a la envergadura real del avión y lo centra como el modelo dibujado por código (mismo largo y la misma
  altura de las ruedas), así coincide con el tren, la física y las luces.
- Junta las piezas por material (pocas llamadas de dibujo) y reduce las texturas a 1024 px como máximo.
- invertir: da vuelta adelante y atrás si la detección de la cola falla.
- quitar=…: materiales que no deben verse en vuelo (cuerdas de amarre, bloques, cintas «remove before flight»).
- Hornea la oclusión ambiental por vértice (rendijas, uniones, ruedas y el interior en penumbra): se calcula una
  sola vez aquí y en vuelo no cuesta nada.
- Escribe assets/modelos/<avión>.npz, sus texturas assets/modelos/<avión>_<n>.png y el crédito en
  assets/modelos/CREDITOS.json (las licencias CC BY piden citar al autor): autor, título, enlace y licencia salen de
  los datos que Sketchfab guarda en el propio archivo.
"""
import io
import json
import os
import struct
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "assets", "modelos")
MAX_TEX = 1024
COMP = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def load_glb(path):
    b = open(path, "rb").read()
    magic, _ver, length = struct.unpack_from("<4sII", b, 0)
    if magic != b"glTF":
        raise ValueError("no es un archivo .glb")
    off, js, binc = 12, None, b""
    while off < length:
        clen, ctype = struct.unpack_from("<I4s", b, off)
        data = b[off + 8: off + 8 + clen]
        if ctype == b"JSON":
            js = json.loads(data)
        elif ctype == b"BIN\x00":
            binc = data
        off += 8 + clen
    return js, binc


def accessor(js, binc, idx):
    acc = js["accessors"][idx]
    dt = np.dtype(COMP[acc["componentType"]])
    n = NCOMP[acc["type"]]
    cnt = acc["count"]
    if "bufferView" not in acc:
        return np.zeros((cnt, n), np.float32)
    bv = js["bufferViews"][acc["bufferView"]]
    off = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = bv.get("byteStride", 0) or dt.itemsize * n
    a = np.ndarray((cnt, n), dtype=dt, buffer=binc, offset=off, strides=(stride, dt.itemsize)).copy()
    if acc.get("normalized") and dt.kind in "iu":
        a = a.astype(np.float32) / np.iinfo(dt).max
    return a


def local_matrix(n):
    if "matrix" in n:
        return np.array(n["matrix"], np.float64).reshape(4, 4).T
    T, R, S = np.eye(4), np.eye(4), np.eye(4)
    if "translation" in n:
        T[:3, 3] = n["translation"]
    if "rotation" in n:
        x, y, z, w = n["rotation"]
        R[:3, :3] = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    if "scale" in n:
        S[0, 0], S[1, 1], S[2, 2] = n["scale"]
    return T @ R @ S


def flatten(js, binc):
    """Triángulos de toda la escena en coordenadas del archivo, agrupados por material:
    {material: [(pos, norm, uv, idx), ...]}."""
    groups = {}
    scene = js.get("scenes", [{}])[js.get("scene", 0)]

    def walk(i, parent):
        node = js["nodes"][i]
        M = parent @ local_matrix(node)
        if "mesh" in node:
            Nm = np.linalg.inv(M[:3, :3]).T
            for pr in js["meshes"][node["mesh"]]["primitives"]:
                if pr.get("mode", 4) != 4 or "POSITION" not in pr["attributes"]:
                    continue
                at = pr["attributes"]
                pos = accessor(js, binc, at["POSITION"]).astype(np.float64)
                idx = (accessor(js, binc, pr["indices"]).reshape(-1).astype(np.uint32) if "indices" in pr
                       else np.arange(len(pos), dtype=np.uint32))
                if "NORMAL" in at:
                    nor = accessor(js, binc, at["NORMAL"]).astype(np.float64)
                else:                                   # sin normales: las de cada cara
                    tri = pos[idx.reshape(-1, 3)]
                    fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
                    pos = tri.reshape(-1, 3)
                    nor = np.repeat(fn, 3, axis=0)
                    idx = np.arange(len(pos), dtype=np.uint32)
                uv = (accessor(js, binc, at["TEXCOORD_0"]).astype(np.float32) if "TEXCOORD_0" in at
                      else np.zeros((len(pos), 2), np.float32))
                if len(uv) != len(pos):
                    uv = np.zeros((len(pos), 2), np.float32)
                wp = (M[:3, :3] @ pos.T).T + M[:3, 3]
                wn = (Nm @ nor.T).T
                wn /= np.linalg.norm(wn, axis=1, keepdims=True) + 1e-12
                if np.linalg.det(M[:3, :3]) < 0:        # nodo espejado: se invierte el orden de los triángulos
                    idx = idx.reshape(-1, 3)[:, ::-1].reshape(-1)
                groups.setdefault(pr.get("material", -1), []).append((wp, wn, uv, idx))
        for c in node.get("children", []):
            walk(c, M)
    for r in scene.get("nodes", []):
        walk(r, np.eye(4))
    return groups


def code_model_extent(aircraft_id):
    """Largo (x mínimo y máximo) y altura de las ruedas (z máximo) del avión dibujado por código."""
    from sim.aircraft_data import AIRCRAFT
    from render import geometry as geo
    t = AIRCRAFT[aircraft_id]()
    parts, _ = geo.aircraft_parts(t)
    pts = np.concatenate([a.reshape(-1, 9)[:, :3] for k, (a, p, ax) in parts.items() if not k.startswith(("disc", "prop"))])
    return t, pts[:, 0].min(), pts[:, 0].max(), pts[:, 2].max()


def to_body_frame(groups, t, x_lo, x_hi, z_bot, flip=False):
    allp = np.concatenate([g[0] for gs in groups.values() for g in gs])
    lo, hi = allp.min(0), allp.max(0)
    ext = hi - lo
    up = np.array([0.0, 1.0, 0.0])                          # glTF: Y hacia arriba
    span_ax = 0 if ext[0] >= ext[2] else 2
    len_ax = 2 - span_ax
    # la cola es el extremo del largo donde está lo más alto (la deriva)
    top = allp[allp[:, 1] > hi[1] - ext[1] * 0.08]
    mid = (lo[len_ax] + hi[len_ax]) / 2
    tail_sign = 1.0 if np.mean(top[:, len_ax]) > mid else -1.0
    if flip:                                                 # lo más alto no es la deriva (p. ej. cúpula abierta)
        tail_sign = -tail_sign
    fwd = np.zeros(3)
    fwd[len_ax] = -tail_sign
    down = -up
    right = np.cross(down, fwd)                              # ejes del cuerpo: x adelante, y derecha, z abajo
    Rm = np.stack([fwd, right, down])                        # filas: coordenadas del archivo → cuerpo
    s = t.b / ext[span_ax]
    p = (Rm @ allp.T).T * s
    cx = (p[:, 0].min() + p[:, 0].max()) / 2
    off = np.array([(x_lo + x_hi) / 2 - cx, -(p[:, 1].min() + p[:, 1].max()) / 2, z_bot - p[:, 2].max()])
    info = dict(escala=round(float(s), 4), largo=round(float(p[:, 0].max() - p[:, 0].min()), 2),
                largo_codigo=round(float(x_hi - x_lo), 2), altura=round(float(p[:, 2].max() - p[:, 2].min()), 2))
    return Rm, s, off, info


def texture_png(js, binc, tex_idx, path):
    import pygame
    tex = js["textures"][tex_idx]
    src = tex.get("source")
    if src is None:
        for ext in tex.get("extensions", {}).values():
            src = ext.get("source", src)
    im = js["images"][src]
    bv = js["bufferViews"][im["bufferView"]]
    data = binc[bv.get("byteOffset", 0): bv.get("byteOffset", 0) + bv["byteLength"]]
    surf = pygame.image.load(io.BytesIO(data), "x." + im.get("mimeType", "image/png").split("/")[-1])
    w, h = surf.get_size()
    rgba = pygame.Surface((w, h), pygame.SRCALPHA, 32)       # 32 bits con alfa (sin ventana no hay convert_alpha)
    rgba.blit(surf, (0, 0))
    k = min(1.0, MAX_TEX / max(w, h))
    if k < 1.0:
        rgba = pygame.transform.smoothscale(rgba, (max(1, int(w * k)), max(1, int(h * k))))
    pygame.image.save(rgba, path)


def convert(aircraft_id, glb, drop=(), flip=False):
    import pygame
    pygame.init()
    js, binc = load_glb(glb)
    groups = flatten(js, binc)
    mats = js.get("materials", [])
    groups = {mi: g for mi, g in groups.items()
              if not (0 <= mi < len(mats) and mats[mi].get("name", "") in drop)}
    t, x_lo, x_hi, z_bot = code_model_extent(aircraft_id)
    Rm, s, off, info = to_body_frame(groups, t, x_lo, x_hi, z_bot, flip)
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):                                # texturas viejas de este avión
        if f.startswith(aircraft_id + "_") and f.endswith(".png"):
            os.remove(os.path.join(OUT, f))
    arrays, meta, texmap = {}, [], {}
    for k, (mi, parts) in enumerate(sorted(groups.items(), key=lambda kv: kv[0])):
        mat = mats[mi] if 0 <= mi < len(mats) else {}
        pbr = mat.get("pbrMetallicRoughness", {})
        color = [float(c) for c in pbr.get("baseColorFactor", [1, 1, 1, 1])]
        tex_file = None
        if "baseColorTexture" in pbr:
            ti = pbr["baseColorTexture"]["index"]
            if ti not in texmap:
                fn = f"{aircraft_id}_{len(texmap)}.png"
                try:
                    texture_png(js, binc, ti, os.path.join(OUT, fn))
                    texmap[ti] = fn
                except Exception as ex:                  # textura ilegible: queda el color del material
                    print("  textura", ti, "no se pudo leer:", ex)
                    texmap[ti] = None
            tex_file = texmap[ti]
        verts, idxs, base = [], [], 0
        for pos, nor, uv, idx in parts:
            bp = (Rm @ pos.T).T * s + off
            bn = (Rm @ nor.T).T
            verts.append(np.hstack([bp, bn, uv]).astype(np.float32))
            idxs.append(idx + base)
            base += len(pos)
        arrays[f"v{k}"] = np.concatenate(verts)
        arrays[f"i{k}"] = np.concatenate(idxs).astype(np.uint32)
        meta.append(dict(color=color, tex=tex_file, blend=mat.get("alphaMode") == "BLEND",
                         cutoff=float(mat.get("alphaCutoff", 0.5)) if mat.get("alphaMode") == "MASK" else 0.0,
                         nombre=mat.get("name", "")))
    arrays = bake_ao(arrays, meta)
    np.savez_compressed(os.path.join(OUT, aircraft_id + ".npz"), meta=json.dumps(meta), **arrays)
    cred_p = os.path.join(OUT, "CREDITOS.json")
    cred = json.load(open(cred_p, encoding="utf-8")) if os.path.exists(cred_p) else {}
    ex = js.get("asset", {}).get("extras", {})
    cred[aircraft_id] = dict(archivo=os.path.basename(glb), titulo=ex.get("title", ""), autor=ex.get("author", ""),
                             url=ex.get("source", ""), licencia=ex.get("license", ""))
    json.dump(cred, open(cred_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ntri = sum(len(arrays[f"i{k}"]) // 3 for k in range(len(meta)))
    print(f"{aircraft_id}: {ntri} triángulos, {len(meta)} materiales, {len([v for v in texmap.values() if v])} texturas, "
          f"{info}")


# ---------------------------------------------------------------- oclusión ambiental horneada
AO_DIRS = 160
AO_RES = 1024
AO_FLOOR = 0.15          # el rincón más cerrado no queda negro del todo (luz que rebota)


def bake_ao(arrays, meta, dirs=AO_DIRS, res=AO_RES):
    """Penumbra por vértice: se mira el avión desde muchas direcciones (mapas de profundidad en la tarjeta
    gráfica) y se cuenta desde cuántas ve cielo cada vértice, pesando por el ángulo con su normal. Devuelve los
    vértices con una 9.ª columna: 1 al aire libre, AO_FLOOR en el rincón más cerrado. Los vidrios no tapan."""
    import moderngl
    n = len(meta)
    V = [np.asarray(arrays[f"v{k}"], np.float32)[:, :8] for k in range(n)]
    solid = [not m.get("blend") or m["color"][3] >= 0.6 for m in meta]
    occ_v, occ_i, base = [], [], 0
    for k in range(n):
        if solid[k]:
            occ_v.append(V[k][:, :3])
            occ_i.append(np.asarray(arrays[f"i{k}"], np.uint32) + base)
            base += len(V[k])
    allp = np.concatenate([v[:, :3] for v in V]).astype(np.float64)
    alln = np.concatenate([v[:, 3:6] for v in V]).astype(np.float64)
    alln /= np.maximum(np.linalg.norm(alln, axis=1, keepdims=True), 1e-9)
    c = (allp.min(0) + allp.max(0)) / 2
    R = float(np.linalg.norm(allp - c, axis=1).max()) * 1.02
    ctx = moderngl.create_standalone_context()
    prog = ctx.program(vertex_shader="""#version 330
uniform vec3 r; uniform vec3 u; uniform vec3 f; uniform vec3 c; uniform float R;
in vec3 in_pos;
void main() { vec3 d = in_pos - c; gl_Position = vec4(dot(d, r) / R, dot(d, u) / R, dot(d, f) / R, 1.0); }""",
                       fragment_shader="#version 330\nvoid main() { }")
    vbo = ctx.buffer(np.ascontiguousarray(np.concatenate(occ_v), np.float32).tobytes())
    ibo = ctx.buffer(np.ascontiguousarray(np.concatenate(occ_i), np.uint32).tobytes())
    vao = ctx.vertex_array(prog, [(vbo, "3f", "in_pos")], ibo)
    depth = ctx.depth_texture((res, res))
    fbo = ctx.framebuffer(depth_attachment=depth)
    ctx.enable(moderngl.DEPTH_TEST)
    prog["c"].value = tuple(float(x) for x in c)
    prog["R"].value = R
    acc = np.zeros(len(allp))
    wsum = np.zeros(len(allp))
    bias = 0.015 / (2 * R)                      # 1,5 cm en unidades de profundidad
    gold = np.pi * (3 - np.sqrt(5))
    for j in range(dirs):                       # direcciones repartidas por igual en toda la esfera
        zz = 1 - 2 * (j + 0.5) / dirs
        rr = np.sqrt(1 - zz * zz)
        d = np.array([rr * np.cos(gold * j), rr * np.sin(gold * j), zz])
        f = -d
        up = np.array([0.0, 0.0, 1.0]) if abs(f[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
        r = np.cross(f, up)
        r /= np.linalg.norm(r)
        u = np.cross(r, f)
        for name, vec in (("r", r), ("u", u), ("f", f)):
            prog[name].value = tuple(float(x) for x in vec)
        fbo.use()
        fbo.clear(depth=1.0)
        vao.render()
        D = np.frombuffer(depth.read(), np.float32).reshape(res, res)
        cosw = alln @ d
        m = cosw > 0.02
        rel = allp[m] + alln[m] * 0.02 - c     # 2 cm hacia afuera: el vértice no se tapa a sí mismo
        ix = np.clip(((rel @ r / R) * 0.5 + 0.5) * res, 0, res - 1).astype(int)
        iy = np.clip(((rel @ u / R) * 0.5 + 0.5) * res, 0, res - 1).astype(int)
        zd = (rel @ f / R) * 0.5 + 0.5
        vis = zd <= D[iy, ix] + bias
        acc[m] += vis * cosw[m]
        wsum[m] += cosw[m]
    ctx.release()
    ao = np.where(wsum > 0, acc / np.maximum(wsum, 1e-9), 1.0)
    ao = AO_FLOOR + (1 - AO_FLOOR) * np.clip(ao, 0, 1)
    out, a0 = dict(arrays), 0
    for k in range(n):
        nv = len(V[k])
        out[f"v{k}"] = np.hstack([V[k], ao[a0:a0 + nv, None].astype(np.float32)])
        a0 += nv
    return out


def rebake(aircraft_id):
    path = os.path.join(OUT, aircraft_id + ".npz")
    z = np.load(path)
    meta = json.loads(str(z["meta"]))
    arrays = {k: z[k] for k in z.files if k != "meta"}
    arrays = bake_ao(arrays, meta)
    np.savez_compressed(path, meta=json.dumps(meta), **arrays)
    ao = np.concatenate([arrays[f"v{k}"][:, 8] for k in range(len(meta))])
    print(f"{aircraft_id}: penumbra horneada (media {ao.mean():.2f}, mínimo {ao.min():.2f})")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "hornear":
        ids = sys.argv[2:] or sorted(f[:-4] for f in os.listdir(OUT) if f.endswith(".npz"))
        for a in ids:
            rebake(a)
        sys.exit(0)
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    drop = ()
    for a in sys.argv[3:]:
        if a.startswith("quitar="):
            drop = tuple(x.strip() for x in a[7:].split(",") if x.strip())
    convert(sys.argv[1], sys.argv[2], drop, "invertir" in sys.argv[3:])
