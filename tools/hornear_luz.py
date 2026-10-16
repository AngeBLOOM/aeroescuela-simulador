"""Hornea con Blender (Cycles) la luz del cielo de los hangares y torres del aeródromo y la guarda en assets/luz/.

    python tools/hornear_luz.py "C:/ruta/a/blender.exe"            (calidad final: 1024 px, 256 muestras)
    python tools/hornear_luz.py "C:/ruta/a/blender.exe" --rapido   (prueba: 256 px, 32 muestras)

Por cada geometría distinta (hangar de ln x wd x ht, torre de altura h) arma la malla igual que el simulador pero
en su sistema local, la pasa a Blender (tools/blender_hornear.py) y guarda <clave>.npz con:
  lm      mapa de luz del edificio (S x S x 3, luz / 1,6 en 8 bits; el uv de cada vértice está en uv_<papel>)
  ground  penumbra en el suelo alrededor (G x G, misma escala), sobre el rectángulo grect (local: x0, y0, x1, y1)
Los hangares del mismo tamaño comparten la luz aunque cambien el color o el letrero. Blender no hace falta para usar
el simulador: solo para volver a hornear si cambia la forma de los edificios.
"""
import os
import subprocess
import sys
import tempfile

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from render import buildings as bl  # noqa: E402

GROUND_ALBEDO = (0.30, 0.30, 0.27)          # suelo entre pasto y concreto de plataforma


def geometries():
    """Geometrías distintas del escenario de la escuela, armado igual que en el simulador."""
    from render.scenery import Scenery
    from sim.world import World
    scn = Scenery(World())
    out = {}
    for (_x, _y, _gz, ln, wd, ht, _yaw, _col, _sign) in scn.hangars:
        out.setdefault(bl.hangar_key(ln, wd, ht), ("hangar", (ln, wd, ht)))
    for (_x, _y, _gz, h) in scn.towers:
        out.setdefault(bl.tower_key(h), ("torre", (h,)))
    return out


def local_mesh(kind, p):
    tm = bl.TexMesh()
    if kind == "hangar":
        bl.add_hangar(tm, 0.0, 0.0, 0.0, p[0], p[1], p[2], 0.0, "0.7,0.7,0.7", "AEROESCUELA")
    else:
        bl.add_tower(tm, 0.0, 0.0, 0.0, p[0])
    return tm


def albedo(mat):
    col, tkey, _blend = bl.material(mat)
    rgb = np.array(col[:3], float)
    if tkey:
        img = bl.make_texture(tkey)
        rgb *= img[..., :3].reshape(-1, 3).mean(0) / 255.0
    return rgb


def export(tm, path):
    tris, alb, occ, roles = [], [], [], []
    for mat, rows in tm.arrays().items():
        t = rows[:, :3].reshape(-1, 3, 3).astype(np.float64)
        tris.append(np.stack([t[..., 1], t[..., 0], -t[..., 2]], axis=-1))      # NED -> Blender (este, norte, arriba)
        n = len(t)
        alb.append(np.repeat(albedo(mat)[None], n, 0))
        # los vidrios transparentes y el letrero (que no todos los hangares tienen) no cuentan para la luz
        occ.append(np.full(n, not bl.material(mat)[2] and bl.role(mat) != "sign"))
        roles.append((bl.role(mat), n))
    tris = np.concatenate(tris)
    # parche de suelo: la planta del edificio más un margen según su altura
    ned = np.stack([tris[..., 1], tris[..., 0]], axis=-1).reshape(-1, 2)     # (norte, este)
    zmax = float(tris[..., 2].max())
    m = float(np.clip(1.5 * zmax, 10.0, 30.0))
    x0, y0 = ned.min(0) - m
    x1, y1 = ned.max(0) + m
    np.savez(path, tris=tris, albedo=np.concatenate(alb), occ=np.concatenate(occ),
             grect=np.array([y0, x0, y1, x1]), ground_albedo=np.array(GROUND_ALBEDO))
    return roles, np.array([x0, y0, x1, y1], np.float32)


def main():
    blender = sys.argv[1]
    fast = "--rapido" in sys.argv
    size, gsize, samples = (256, 128, 32) if fast else (1024, 256, 256)
    os.makedirs(bl.LIGHT_DIR, exist_ok=True)
    script = os.path.join(ROOT, "tools", "blender_hornear.py")
    with tempfile.TemporaryDirectory() as tmp:
        for key, (kind, p) in geometries().items():
            src, dst = os.path.join(tmp, key + "_in.npz"), os.path.join(tmp, key + "_out.npz")
            roles, grect = export(local_mesh(kind, p), src)
            print("horneando", key, "...", flush=True)
            r = subprocess.run([blender, "--background", "--factory-startup", "--python", script, "--",
                                src, dst, str(size), str(gsize), str(samples)], capture_output=True, text=True)
            if r.returncode != 0 or not os.path.exists(dst):
                print(r.stdout[-3000:], r.stderr[-3000:])
                raise SystemExit(f"falló el horneado de {key}")
            print([ln for ln in r.stdout.splitlines() if ln.startswith("HORNEADO")][-1])
            with np.load(dst) as zf:
                z = {k: zf[k] for k in zf.files}
            out = dict(lm=np.clip(z["lm"].astype(np.float32) / bl.LIGHT_SCALE * 255 + 0.5, 0, 255).astype(np.uint8),
                       ground=np.clip(z["ground"].astype(np.float32) / bl.LIGHT_SCALE * 255 + 0.5, 0, 255).astype(np.uint8),
                       grect=grect)
            uv, i = z["uv"], 0
            for rl, n in roles:
                out["uv_" + rl] = uv[i:i + n].astype(np.float32)
                i += n
            np.savez_compressed(os.path.join(bl.LIGHT_DIR, key + ".npz"), **out)
    print("listo:", bl.LIGHT_DIR)


if __name__ == "__main__":
    main()
