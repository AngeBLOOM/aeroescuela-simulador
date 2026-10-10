"""Todas las lecciones, emergencias y exámenes en un aeropuerto real (por defecto SVBS, Base Aérea Mariscal Sucre,
Maracay): cada una se prepara y vuela 25 s con un piloto que mantiene la actitud. Detecta errores, salidas
contra el terreno y posiciones de partida absurdas.

    python tests/test_lugar_real.py [OACI]
"""
import math
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim import geo
from sim.lessons import LESSONS
from sim.mathx import FT, clamp
from sim.world import World

CODE = sys.argv[1] if len(sys.argv) > 1 else "SVBS"
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datos")
loc = geo.build_location(CODE, DATA)
print(f"Escenario: {loc['name']} ({CODE}) · aeropuertos: {[a.ident for a in loc['airports']]} · "
      f"radioayudas: {[(n.ident, n.kind, n.freq) for n in loc['navaids']][:8]}")
problems = []
for cls in LESSONS:
    if getattr(cls, "school_only", False):
        print(f"--  {cls.id:14s} solo escenario escuela")
        continue
    w = World(getattr(cls, "aircraft", None) or "c172", location=loc)
    try:
        L = cls()
        if getattr(L, "aircraft", None) and L.aircraft != w.aircraft_id:
            w.set_aircraft(L.aircraft)
        L.setup(w)
        ac = w.ac
        agl0 = ac.agl / FT
        # relieve más alto a 3 km por delante
        h = math.radians(ac.heading)
        ahead = max(w.terrain.height(ac.pos[0] + math.cos(h) * d, ac.pos[1] + math.sin(h) * d) for d in range(300, 3001, 300))
        clear = (ac.alt_msl - ahead) / FT
        dt = 1 / 60
        t = 0.0
        while t < 25 and not ac.crashed and not L.done:
            if not ac.on_ground:
                ac.ctl_ail = clamp(-math.degrees(ac.roll) * 0.05 - ac.omega[0] * 0.3, -1, 1)
                ac.ctl_elev = clamp((3 - math.degrees(ac.pitch)) * 0.08, -0.6, 0.6)
            w.step(dt)
            evs = list(w.events)
            w.events.clear()
            L.update(dt, w, evs)
            L.messages.clear()
            t += dt
        water = w.terrain.surface(ac.pos[0], ac.pos[1])[1] == "agua"
        flag = []
        if ac.crashed:
            flag.append("CHOCA: " + ac.crash_reason)
        if not ac.on_ground and clear < 500:
            flag.append(f"terreno a {clear:.0f} ft por delante")
        if water and ac.on_ground:
            flag.append("empieza en el agua")
        st = "OK " if not flag else "!! "
        print(f"{st} {cls.id:14s} inicio {getattr(L, 'start', ''):12s} AGL {agl0:6.0f} ft · margen con el relieve "
              f"{clear:6.0f} ft · {'sobre el lago' if water else ''} {'; '.join(flag)}")
        if flag:
            problems.append((cls.id, flag))
    except Exception as ex:
        print(f"ERR {cls.id:14s} {type(ex).__name__}: {ex}")
        traceback.print_exc(limit=3)
        problems.append((cls.id, [str(ex)]))
print("\nPROBLEMAS:" if problems else "\nTODAS FUNCIONAN", problems if problems else "")
