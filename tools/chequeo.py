"""Chequeo del simulador antes de usarlo (diario) o tras un cambio, con anotación en el registro de mantenimiento.

Ejecuta las pruebas automáticas (tools/pruebas.py, incluida la validación contra el manual) y añade una línea a
datos/mantenimiento.csv con la fecha, la versión del programa, quién lo hizo y el resultado. Ver
docs/REGISTRO_MANTENIMIENTO.md.

Uso:  python tools/chequeo.py "Nombre del responsable"  [nota]
"""
import csv
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import pruebas                                                  # noqa: E402
from guia_pruebas import version                               # noqa: E402

LOG = os.path.join(ROOT, "datos", "mantenimiento.csv")
FIELDS = ["fecha", "version", "responsable", "pruebas", "fallos", "nota"]


def run(names):
    env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy", PYTHONIOENCODING="utf-8")
    bad = []
    for name in names:
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", name + ".py")], cwd=ROOT, env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(f"{'PASA ' if r.returncode == 0 else 'FALLA'} {name}", flush=True)
        if r.returncode != 0:
            bad.append(name)
    return bad


def log(row, path=LOG):
    new = not os.path.exists(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def main(argv):
    who = argv[0] if argv else os.environ.get("USERNAME", "")
    note = argv[1] if len(argv) > 1 else ""
    bad = run(pruebas.TESTS)
    n = len(pruebas.TESTS)
    log(dict(fecha=time.strftime("%Y-%m-%d %H:%M"), version=version(), responsable=who,
             pruebas=f"{n - len(bad)}/{n}", fallos=" ".join(bad), nota=note))
    print(f"\n{n - len(bad)} de {n} pruebas pasan · anotado en {os.path.relpath(LOG, ROOT)}")
    if bad:
        print("NO USAR PARA INSTRUCCIÓN hasta corregir: " + ", ".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
