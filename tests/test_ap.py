"""Prueba del piloto automático: ILS acoplado y mantenimiento de rumbo/altitud."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim.mathx import FT
from sim.world import World

w = World()


def run(secs, every=10, ctl=None):
    t = 0.0
    dt = 1 / 60
    nxt = 0
    while t < secs:
        cmd = w.apply_autopilot(dt)
        if cmd:
            w.ac.ctl_elev, w.ac.ctl_ail = cmd
        if ctl:
            ctl(t)
        w.step(dt)
        t += dt
        if t >= nxt:
            nxt += every
            ac = w.ac
            print(f" t={t:5.0f} {w.ap.lat:4}/{w.ap.vert:4} arm={'N' if w.ap.nav_armed else ' '}{'G' if w.ap.gs_armed else ' '} "
                  f"ias={w.ind.ias:5.1f} alt={w.ind.alt_ft:6.0f} agl={ac.agl/FT:6.0f} hdg={ac.heading:5.1f} "
                  f"cdi={w.nav1.cdi:+.2f} gs={w.nav1.gs:+.2f} roll={math.degrees(ac.roll):+5.1f} trim={ac.trim:+.2f} {ac.crash_reason}")
        if w.ac.crashed or (w.ac.agl / FT < 200 and w.ap.vert == "GS"):
            break


print("== ILS acoplado (APR) desde 9 NM ==")
w.weather.wind_kt = 8; w.weather.wind_dir = 330; w.weather.turbulence = 0.2
w.reposition("final10")
w.ac.sys.engine.throttle = 0.55
w.ap.alt_sel = 2900
w.ap.set_alt(w.ac)
w.ap.alt_sel = 2900
w.ap.set_nav(w.ac, approach=True)
run(400, 20)
print("== HDG 090 + ALT 4500 en crucero ==")
w.weather.turbulence = 0.0
w.reposition("crucero")
w.ap.hdg_bug = 90
w.ap.set_hdg(w.ac)
w.ap.set_alt(w.ac)
run(90, 15)
print("== VS +500 a 5500 ==")
w.ap.alt_sel = 5500
w.ap.vert = "VS"; w.ap.vs_sel = 500; w.ap.alt_armed = True
w.ac.sys.engine.throttle = 1.0
run(200, 20)
