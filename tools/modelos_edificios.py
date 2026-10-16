"""Modela en Blender los edificios del aeródromo (hangares, torres de control, estación de combustible), hornea su
luz y los deja en assets/edificios/<clave>.npz, que el simulador usa en lugar de los edificios armados por código.

    python tools/modelos_edificios.py "C:/ruta/a/blender.exe"              (calidad final)
    python tools/modelos_edificios.py "C:/ruta/a/blender.exe" --rapido     (prueba rápida)
    python tools/modelos_edificios.py "C:/ruta/a/blender.exe" hangar_45x34x11   (solo esos)

El modelado está en tools/blender_modelos.py (se ejecuta dentro de Blender 4.2 LTS). Blender no hace falta para usar
el simulador: solo para volver a generar los modelos.
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "assets", "edificios")


def pedido(fast):
    from render import buildings as bl
    from render.scenery import Scenery
    from sim.world import World
    scn = Scenery(World())
    size, samples = (256, 32) if fast else (1024, 400)
    items = {}
    for (_x, _y, _gz, ln, wd, ht, _yaw, _col, _sign) in scn.hangars:
        items[bl.hangar_key(ln, wd, ht)] = dict(kind="hangar", p=dict(ln=ln, wd=wd, ht=ht))
    for (_x, _y, _gz, h) in scn.towers:
        items[bl.tower_key(h)] = dict(kind="torre", p=dict(h=h))
    if getattr(scn, "fuel", None):
        items["combustible"] = dict(kind="combustible", p={})
    out = [dict(key=k, size=size, gsize=size // 4, samples=samples, **v) for k, v in items.items()]
    # casas y edificios de los pueblos (variantes que el simulador repite con su color)
    hs = (128, 24) if fast else (512, 256)
    for k in ("casa_a", "casa_b", "casa_c", "casa_d"):
        out.append(dict(key=k, kind=k, p={}, size=hs[0], gsize=hs[0] // 4, samples=hs[1]))
    out.append(dict(key="bloque_4", kind="bloque", p=dict(pisos=4, w=20.0, d=14.0), size=size, gsize=size // 4,
                    samples=samples))
    out.append(dict(key="bloque_10", kind="bloque", p=dict(pisos=10, w=18.0, d=18.0), size=size, gsize=size // 4,
                    samples=samples))
    return out


def main():
    blender = sys.argv[1]
    fast = "--rapido" in sys.argv
    only = [a for a in sys.argv[2:] if not a.startswith("--")]
    spec = pedido(fast)
    if only:
        spec = [s for s in spec if s["key"] in only]
    os.makedirs(OUT, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for item in spec:                            # un proceso de Blender por modelo (más robusto)
            sp = os.path.join(tmp, item["key"] + ".json")
            with open(sp, "w", encoding="utf-8") as fh:   # cerrado antes de que Blender lo lea
                json.dump([item], fh)
            r = subprocess.run([blender, "--background", "--factory-startup", "--python",
                                os.path.join(ROOT, "tools", "blender_modelos.py"), "--", sp, OUT],
                               capture_output=True, text=True)
            lines = [ln for ln in r.stdout.splitlines() if ln.startswith("MODELO")]
            if r.returncode != 0 or not lines:
                print(r.stdout[-4000:], r.stderr[-4000:])
                raise SystemExit(f"falló el modelado de {item['key']} en Blender")
            print(lines[-1][:120], flush=True)
    print("listo:", OUT)


if __name__ == "__main__":
    main()
