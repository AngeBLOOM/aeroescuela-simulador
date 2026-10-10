"""Pruebas rápidas del modelo de vuelo (sin gráficos)."""
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sim.aircraft_data import cessna172, piper_arrow
from sim.airports import build_airports
from sim.atmosphere import Atmosphere, Weather
from sim.flightmodel import Aircraft
from sim.mathx import KT
from sim.terrain import Terrain

DT = 1 / 240

t0 = time.time()
airports, navaids = build_airports()
terrain = Terrain(airports)
print(f"terreno generado en {time.time()-t0:.2f}s  rango {terrain.h.min():.0f}..{terrain.h.max():.0f} m")
w = Weather(); w.wind_kt = 0
atmo = Atmosphere(w)


def run(ac, secs, ctl=None, log_every=5.0):
    n = int(secs / DT)
    t = 0.0
    for i in range(n):
        if ctl:
            ctl(ac, t)
        atmo.update(DT, ac.tas, ac.agl)
        ac.step(DT)
        t += DT
        if log_every and (i % int(log_every / DT) == 0):
            print(f"  t={t:6.1f} ias={ac.ias_kt:6.1f}kt alt={ac.alt_msl/0.3048:7.0f}ft agl={ac.agl:6.1f}m vs={ac.vs_fpm:6.0f} "
                  f"pitch={math.degrees(ac.pitch):5.1f} roll={math.degrees(ac.roll):6.1f} hdg={ac.heading:5.1f} "
                  f"aoa={math.degrees(ac.alpha):5.1f} rpm={ac.sys.engine.rpm:5.0f} gnd={ac.on_ground} {ac.crash_reason}")
        if ac.crashed:
            break
    return ac


for maker in (cessna172, piper_arrow):
    print("=====", maker.__name__)
    ac = Aircraft(maker(), terrain, atmo)
    print("Prueba 1: crucero equilibrado a 3000 ft, 105 kt, sin mandos")
    ac.sys.ready_to_fly(True)
    ac.place_in_air(0, 0, 3000 * 0.3048 + 0, 0, 105)
    t1 = time.time()
    run(ac, 40, log_every=10)
    print(f"  (40 s simulados en {time.time()-t1:.2f}s reales)")

    print("Prueba 2: carrera de despegue con gases a fondo")
    ac2 = Aircraft(maker(), terrain, atmo)
    ac2.sys.ready_to_fly(False)
    rw = airports[0].runways[0]
    thr = rw.threshold
    ac2.place_on_ground(thr[0] + 30, thr[1], 0.0)
    run(ac2, 3, log_every=1)
    vr = ac2.t.v["vr"]

    def takeoff(a, t):
        a.sys.engine.throttle = 1.0
        a.ctl_elev = 0.0 if a.ias_kt < vr else (0.35 if a.pitch < math.radians(9) else 0.0)
    run(ac2, 45, takeoff, log_every=3)

    print("Prueba 3: pérdida sin motor")
    ac3 = Aircraft(maker(), terrain, atmo)
    ac3.sys.ready_to_fly(True)
    ac3.place_in_air(0, 0, 4000 * 0.3048, 0, 80)
    ac3.sys.engine.throttle = 0.0

    def stall(a, t):
        a.ctl_elev = min(1.0, t * 0.04) if t < 30 else 0.0
    run(ac3, 40, stall, log_every=2)

    print("Prueba 4: planeo sin motor (motor fallado) 68 kt")
    ac4 = Aircraft(maker(), terrain, atmo)
    ac4.sys.ready_to_fly(True)
    ac4.place_in_air(0, 0, 4000 * 0.3048, 0, ac4.t.v["vglide"], climb_fpm=-700)
    ac4.sys.failures["engine"] = True
    run(ac4, 30, log_every=10)
