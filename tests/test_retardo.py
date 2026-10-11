"""Medidor del retardo interno (app/latency.py): cuenta solo los cuadros en que se leyeron mandos, calcula media,
percentil 95 y máximo, y guarda el informe para la guía de pruebas solo con suficientes cuadros."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.latency import LatencyMeter

t = [0.0]
m = LatencyMeter(n=200, clock=lambda: t[0])
assert m.stats() is None and m.mark_frame() is None          # sin mandos leídos no hay muestra
for i in range(150):
    m.mark_input()
    t[0] += 0.020 if i < 140 else 0.050                       # 140 cuadros de 20 ms y 10 de 50 ms
    m.mark_frame()
    t[0] += 0.003
mean, p95, mx = m.stats()
assert abs(mean - (140 * 20 + 10 * 50) / 150) < 1e-6, mean
assert abs(p95 - 50) < 1e-6 and abs(mx - 50) < 1e-6, (p95, mx)
print(f"media {mean:.1f} ms, 95 % {p95:.0f} ms, máximo {mx:.0f} ms")

d = tempfile.mkdtemp()
p = os.path.join(d, "sub", "retardo.json")
assert m.report(p, fps=30, avion="C172S")
r = json.load(open(p, encoding="utf-8"))
assert r["cuadros"] == 150 and r["p95_ms"] == 50.0 and r["avion"] == "C172S"
assert abs(r["peor_caso_ms"] - (50 + 1000 / 30)) < 0.1, r["peor_caso_ms"]     # + un cuadro de espera a 30 FPS
few = LatencyMeter(clock=lambda: t[0])
few.mark_input()
few.mark_frame()
assert not few.report(os.path.join(d, "otro.json"))           # con menos de 100 cuadros no se guarda
print("TODO OK")
