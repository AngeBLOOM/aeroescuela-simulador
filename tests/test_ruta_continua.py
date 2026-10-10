"""Travesía completa La Carlota → Base Sucre con mundo continuo, volada por un piloto robot sin ventana.
Comprueba que los escenarios se encadenan sin cortes (misma posición geográfica, altitud y velocidad al cambiar),
que no se choca con el relieve y que se aterriza en Base Sucre."""
import math
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim import geo
from sim.lessons import LESSONS_BY_ID as LB
from sim.mathx import FT, NM, clamp, wrap180
from sim.world import World, transfer_to_scene

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datos")
db = geo.AirportDB(DATA)
G = {"__file__": os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_ccs_maracay.py"), "__name__": "robot"}
exec(open(G["__file__"], encoding="utf-8").read(), G)
PID, att, landing = G["PID"], G["att"], G["pilot"]


def next_scene(w, L):
    ac = w.ac
    h = math.radians(ac.track)
    tla, tlo = w.location["proj"].to_geo(ac.pos[0] + math.cos(h) * 20000, ac.pos[1] + math.sin(h) * 20000)
    hint = L.scene_hint(w, (float(tla), float(tlo)))
    t = time.time()
    loc = geo.build_location(hint, DATA, db=db) if hint else geo.build_location(None, DATA, db=db, center=(float(tla), float(tlo)))
    print(f"    escenario preparado: {loc['name']} ({loc['key']}) en {time.time() - t:.0f} s")
    return loc


def robot(w, L, dt, pid):
    ac = w.ac
    e = ac.sys.engine
    if getattr(L, "arrived", False) and L._lrw is not None:
        rw, ident = L._lrw
        along, lat = rw.local(ac.pos[0], ac.pos[1], ident)
        if along < -7500 or abs(lat) > 1500:
            # incorporación: punto a 7 km en la prolongación del eje, a 2000 ft sobre el campo
            thr, hdg, d = rw.end(ident)
            p = thr - d * 7000
            brg = math.degrees(math.atan2(p[1] - ac.pos[1], p[0] - ac.pos[0])) % 360
            if math.hypot(*(p - ac.pos[:2])) < 900:
                brg = hdg
            A = w.home.elev / FT + 1300
            e.throttle = clamp(0.55 + (A - ac.alt_msl / FT) * 0.002, 0.2, 1.0)
            att(ac, pid, clamp(wrap180(brg - ac.heading) * 1.0, -25, 25), clamp(2 + (A - ac.alt_msl / FT) * 0.012, -6, 8), dt)
            return
        L.phase = 2
        landing(w, L, 0, dt, pid)
        return
    if L.idx == 0 and ac.on_ground:
        L.phase = 1
        L.dep_hdg, L.dep_alt = 290.0, L.cruise
        landing(w, L, 0, dt, pid)
        return
    if L.idx <= 1:
        # ascenso en el valle con rumbo 290 hasta 5500 ft
        e.throttle = 1.0
        att(ac, pid, clamp(wrap180(290 - ac.heading) * 1.0, -20, 20), clamp(8 + (w.ind.ias - 76) * 0.6, 0, 14), dt)
        return
    k = min(L.wp_i, len(L.WPS) - 1)
    name, ll, A = L.WPS[k]
    p = L._pt(w, ll)
    brg = math.degrees(math.atan2(p[1] - ac.pos[1], p[0] - ac.pos[0])) % 360
    alt = ac.alt_msl / FT
    if alt < A - 200:
        e.throttle = 1.0
        pc = clamp(8 + (w.ind.ias - 76) * 0.6, 0, 14)
    else:
        e.throttle = 0.66 if alt < A + 300 else 0.35
        pc = clamp(2 + (A - alt) * 0.012, -6, 8)
    att(ac, pid, clamp(wrap180(brg - ac.heading) * 1.0, -25, 25), pc, dt)


if __name__ == "__main__":
    w = World("c172", location=geo.build_location("SVFM", DATA, db=db))
    L = LB[sys.argv[1] if len(sys.argv) > 1 else "ruta_ccs_maracay"]()
    L.setup(w)

    pid = PID(0.12, 0.05, 0.03, -0.7, 0.7)
    dt = 1 / 60
    t = 0.0
    nxt = None
    min_agl = 1e9
    jumps = []
    msgs = []
    while t < 3600 and not L.done:
        robot(w, L, dt, pid)
        w.step(dt)
        evs = list(w.events)
        w.events.clear()
        L.update(dt, w, evs)
        msgs += [m for m, v in L.messages]
        L.messages.clear()
        ac = w.ac
        if not ac.on_ground and t > 120:
            min_agl = min(min_agl, ac.agl / FT)
        d = math.hypot(ac.pos[0], ac.pos[1])
        if d > 13000 and nxt is None and not ac.on_ground and (w.location.get("ident") != "SVBS"):
            nxt = next_scene(w, L)
        if nxt is not None:
            la, lo = w.location["proj"].to_geo(ac.pos[0], ac.pos[1])
            n, e = nxt["proj"].to_local(float(la), float(lo))
            dn = math.hypot(float(n), float(e))
            if d > 18000 or (nxt["ident"] == L.dest_ident and dn < d - 3000):
                before = (float(la), float(lo), ac.alt_msl, ac.vel.copy())
                w = transfer_to_scene(w, nxt)
                L.on_scene_change(w)
                la2, lo2 = w.location["proj"].to_geo(w.ac.pos[0], w.ac.pos[1])
                jump = math.hypot((la2 - before[0]) * 111320, (lo2 - before[1]) * 111320 * math.cos(math.radians(before[0])))
                jumps.append(jump)
                print(f"  t={t / 60:4.1f} min cambio a {nxt['name']}: salto {jump:.2f} m, altitud {w.ac.alt_msl / FT:.0f} ft "
                      f"(antes {before[2] / FT:.0f}), {w.ind.ias:.0f} kt, punto {L.wp_i}/{len(L.WPS)}")
                nxt = None
        t += dt
    R = L.result(w)
    print(f"== {L.title}: {'OK' if L.success else 'FALLO'} ({L.fail_reason}) {t / 60:.1f} min, nota {R['score']:.0f} "
          f"{R['grade']} {w.ac.crash_reason}")
    print(f"   cambios de escenario: {len(jumps)}, salto máximo {max(jumps or [0]):.2f} m; menor altura sobre el terreno "
          f"en ruta {min_agl:.0f} ft")
    for it in R["items"]:
        print("    ", it)
    print("   mensajes:", " | ".join(msgs[:14]))
