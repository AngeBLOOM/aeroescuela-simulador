"""Validación contra el manual: el C172S de referencia, volado por el piloto robot de tools/validacion.py, debe dar
cada cifra de sim/poh.py (pérdida, ascenso, crucero, consumo, planeo, despegue y aterrizaje) dentro de su
tolerancia. Si un cambio del modelo de vuelo saca alguna fuera, esta prueba falla."""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import validacion

filas = validacion.medir()
validacion.tabla(filas)
with tempfile.TemporaryFile("w+", encoding="utf-8") as fh:
    json.dump(filas, fh)                         # la guía de pruebas guarda estos resultados en JSON
bad = [f"{f['titulo']} ({'—' if f['medido'] is None else round(f['medido'], 1)} {f['magnitud']}, POH {f['poh']:g})"
       for f in filas if not f["ok"]]
print("FALLOS: " + "; ".join(bad) if bad else "TODO OK")
sys.exit(1 if bad else 0)
