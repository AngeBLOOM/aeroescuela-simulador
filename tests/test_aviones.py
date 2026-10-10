"""Despegue con alumno robot en cada avión: comprueba que todos despegan y ascienden a su Vy
con las velocidades de su manual (Vr y Vy de cada tipo)."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim.aircraft_data import AIRCRAFT
from sim.mathx import FT, clamp, wrap180
from sim.world import World


class PID:
    def __init__(s, kp, ki, kd, lo=-1, hi=1):
        s.kp, s.ki, s.kd, s.lo, s.hi = kp, ki, kd, lo, hi
        s.i = 0.0
        s.prev = None

    def __call__(s, err, dt):
        s.i = clamp(s.i + err * dt * s.ki, s.lo, s.hi)
        d = 0.0 if s.prev is None else (err - s.prev) / dt
        s.prev = err
        return clamp(s.kp * err + s.i + s.kd * d, s.lo, s.hi)


ok_all = True
for tid in AIRCRAFT:
    w = World(tid)
    w.reposition("pista")
    ac = w.ac
    thr, hdg, d, r = w.runway_frame()
    pitch_pid = PID(0.12, 0.05, 0.03, -0.6, 0.6)
    vr, vy = ac.t.v["vr"], ac.t.v["vy"]
    dt = 1 / 60
    t = 0.0
    lift = None
    while t < 240 and ac.agl / FT < 1000 and not ac.crashed:
        for en in ac.sys.engines:
            en.throttle = 1.0
        he = wrap180(hdg - ac.heading)
        lat = (ac.pos[0] - thr[0]) * r[0] + (ac.pos[1] - thr[1]) * r[1]
        if ac.on_ground:
            ac.ctl_rud = clamp(he * 0.15 - lat * 0.05 + 0.05, -1, 1)
            pc = 9 if w.ind.ias > vr else 0
            ac.ctl_ail = clamp(-math.degrees(ac.roll) * 0.05 - ac.omega[0] * 0.3, -1, 1)
            ac.ctl_elev = pitch_pid(pc - math.degrees(ac.pitch), dt) if w.ind.ias > vr else 0.0
        else:
            if lift is None:
                lift = (t, w.ind.ias)
            ac.ctl_rud = clamp(ac.beta * 3, -1, 1)
            pc = clamp(8 + (w.ind.ias - vy) * 0.6, 0, 14)
            roll_cmd = clamp(he * 1.0, -15, 15)
            ac.ctl_ail = clamp((roll_cmd - math.degrees(ac.roll)) * 0.05 - ac.omega[0] * 0.3, -1, 1)
            ac.ctl_elev = pitch_pid(pc - math.degrees(ac.pitch), dt)
            if ac.t.retractable and ac.agl / FT > 100:
                ac.sys.gear_down = False
        w.step(dt)
        t += dt
    good = not ac.crashed and ac.agl / FT >= 1000
    ok_all &= good
    print(f"{tid:6s} {'OK ' if good else 'FALLO'} despegue a {lift[1] if lift else 0:.0f} kt (Vr {vr}) en {lift[0] if lift else 0:.0f} s; "
          f"1000 ft AGL a los {t:.0f} s, {w.ind.ias:.0f} kt (Vy {vy}), {ac.vs_fpm:.0f} ft/min {ac.crash_reason}")
print("TODOS OK" if ok_all else "HAY FALLOS")
sys.exit(0 if ok_all else 1)
