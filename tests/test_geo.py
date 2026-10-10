"""Prueba de carga de un aeropuerto real (descarga y caché)."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pygame
pygame.init()
from sim import geo

code = sys.argv[1] if len(sys.argv) > 1 else "LEMD"
data = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datos")
last = [0]


def prog(msg, f):
    if time.time() - last[0] > 3 or f >= 0.9:
        last[0] = time.time()
        print(f"  {f*100:5.1f}% {msg}", flush=True)


t0 = time.time()
db = geo.AirportDB(data)
db.ensure(prog)
print("BD cargada", len(db.airports), "aeropuertos", f"{time.time()-t0:.1f}s")
for q in ("bogota", "SCEL", "MEX", "barajas"):
    print(" busca", q, "->", [(a["ident"], a["name"]) for a in db.search(q, 3)])
t0 = time.time()
loc = geo.build_location(code, data, prog, db)
print(f"{loc['name']} listo en {time.time()-t0:.1f}s; aeropuertos:", [(a.ident, [r.idents for r in a.runways][:3], round(a.elev)) for a in loc["airports"]])
print(" radioayudas:", [(n.kind, n.ident, n.freq) for n in loc["navaids"]][:12])
h = loc["heights"]
print(" relieve min/max", h.min(), h.max(), " capas", [(l[0].shape, l[1]) for l in loc["sat"]])
from sim.world import World
w = World(location=loc)
print(" pista en servicio", w.active_rw.idents, w.active_end, "crucero", w.cruise_alt_ft())
