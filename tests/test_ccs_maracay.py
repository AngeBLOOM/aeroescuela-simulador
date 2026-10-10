"""Misión de dos escenarios La Carlota (SVFM) → Base Sucre (SVBS) volada por un piloto robot, sin ventana.
Comprueba la salida del valle de Caracas, el cambio de escenario en vuelo y el aterrizaje en Maracay."""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim import geo
from sim.lessons import LESSONS_BY_ID as LB
from sim.mathx import FT, clamp, wrap180
from sim.world import World

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datos")


class PID:
    def __init__(s, kp, ki, kd, lo=-1, hi=1):
        s.kp, s.ki, s.kd, s.lo, s.hi = kp, ki, kd, lo, hi
        s.i, s.prev = 0.0, None

    def __call__(s, e, dt):
        s.i = clamp(s.i + e * dt * s.ki, s.lo, s.hi)
        d = 0.0 if s.prev is None else (e - s.prev) / dt
        s.prev = e
        return clamp(s.kp * e + s.i + s.kd * d, s.lo, s.hi)


def att(ac, pid, roll_cmd, pitch_cmd, dt):
    ac.ctl_ail = clamp((roll_cmd - math.degrees(ac.roll)) * 0.05 - ac.omega[0] * 0.3, -1, 1)
    ac.ctl_elev = pid(pitch_cmd - math.degrees(ac.pitch), dt)
    ac.ctl_rud = clamp(ac.beta * 3, -1, 1)


def pilot(w, L, t, dt, pid):
    """Fase 1: despegue, rumbo 280 y ascenso a 5500 ft. Fase 2: aproximación por la senda de 3° y aterrizaje."""
    ac = w.ac
    e = ac.sys.engine
    if L.phase == 1:
        thr, hdg, d, r = w.runway_frame()
        lat = (ac.pos[0] - thr[0]) * r[0] + (ac.pos[1] - thr[1]) * r[1]
        if ac.on_ground:
            e.throttle = 1.0
            ac.ctl_rud = clamp(wrap180(hdg - ac.heading) * 0.15 - lat * 0.05 + 0.05, -1, 1)
            ac.ctl_ail = 0.0
            ac.ctl_elev = pid(9 - math.degrees(ac.pitch), dt) if w.ind.ias > 55 else 0.0
            return
        tgt = hdg if ac.agl / FT < 500 else L.dep_hdg
        A = L.dep_alt
        if w.ind.alt_ft < A - 150:
            e.throttle = 1.0
            pc = clamp(8 + (w.ind.ias - 74) * 0.6, 0, 14)
        else:
            e.throttle = 0.68
            pc = clamp(2 + (A - w.ind.alt_ft) * 0.012, -4, 8)
        att(ac, pid, clamp(wrap180(tgt - ac.heading) * 1.0, -20, 20), pc, dt)
        return
    # fase 2: aterrizaje en Base Sucre
    rw, ident = L._lrw
    along, lat = rw.local(ac.pos[0], ac.pos[1], ident)
    H = rw.end(ident)[1]
    d = rw.end(ident)[2]
    h = ac.alt_msl - w.home.elev
    target_h = (-along + 420) * math.tan(math.radians(3)) if along < 0 else max(0.0, 420 - along) * 0.0524
    rr = np.array([-d[1], d[0]])
    vlat = ac.vel[0] * rr[0] + ac.vel[1] * rr[1]
    trk_cmd = H + clamp(-lat * 0.15 - vlat * 1.0, -25, 25)
    roll_cmd = clamp(wrap180(trk_cmd - ac.track) * 1.0, -15, 15)
    if along > -5500:
        ac.sys.flaps_cmd = 3
    ra = ac.agl / FT
    if ra > 15 and not ac.on_ground:
        err = target_h - h
        e.throttle = clamp(0.35 + err * 0.01 - (ac.vs_fpm + 400) * 0.0003, 0.05, 0.9)
        att(ac, pid, roll_cmd, clamp(-3 + (w.ind.ias - 65) * 0.4, -8, 6), dt)
    elif not ac.on_ground:
        e.throttle = 0.0
        att(ac, pid, roll_cmd * 0.5, clamp(4 + (15 - ra) * 0.25, 2, 8), dt)
    else:
        e.throttle = 0.0
        ac.ctl_elev = 0.4
        ac.ctl_ail = 0.0
        ac.brake = 1.0 if w.ind.ias < 40 else 0.4
        ac.ctl_rud = clamp(-lat * 0.1 + wrap180(H - ac.heading) * 0.1, -1, 1)


if __name__ == "__main__":
    w = World("c172", location=geo.build_location("SVFM", DATA))
    L = LB["ccs_maracay"]()
    L.setup(w)
    print(f"Fase 1 en {w.home.ident}: pista {w.active_end}, viento {w.weather.wind_dir:.0f}/{w.weather.wind_kt:.0f}")
    pid = PID(0.12, 0.05, 0.03, -0.7, 0.7)
    dt = 1 / 60
    t = 0.0
    msgs = []
    min_clear = 1e9
    while t < 900 and not L.done:
        pilot(w, L, t, dt, pid)
        w.step(dt)
        evs = list(w.events)
        w.events.clear()
        L.update(dt, w, evs)
        for ev, data in evs:
            if ev == "contacto" and getattr(L, "phase", 1) == 2 and not getattr(L, "_dbg", False):
                L._dbg = True
                rw_, id_ = L._lrw
                al, la = rw_.local(w.ac.pos[0], w.ac.pos[1], id_)
                print(f"  toma: a {al:.0f} m del umbral {id_}, lateral {la:.1f} m (pista {rw_.length:.0f} m), {w.ind.ias:.0f} kt")
        msgs += [m for m, v in L.messages]
        L.messages.clear()
        if not w.ac.on_ground:
            min_clear = min(min_clear, w.ac.agl / FT) if w.ac.agl / FT > 400 or getattr(L, 'idx', 0) > 0 and L.phase == 1 and t > 60 else min_clear
        if L.switch_to:
            code, L.switch_to = L.switch_to, None
            print(f"  t={t:.0f}s cambio de escenario a {code}: {w.ind.alt_ft:.0f} ft, rumbo {w.ac.heading:.0f}, "
                  f"margen mínimo con el terreno {min_clear:.0f} ft")
            wx = w.weather
            w = World("c172", location=geo.build_location(code, DATA))
            w.weather.copy_from(wx)
            w.select_runway()
            w.reposition("pista")
            L.arrive(w)
            pid = PID(0.12, 0.05, 0.03, -0.7, 0.7)
            print(f"  Fase 2 en {w.home.ident}: pista {w.active_end}, inicio a {w.ind.alt_ft:.0f} ft")
        t += dt
    R = L.result(w)
    print(f"== {L.title}: {'OK' if L.success else 'FALLO'} ({L.fail_reason}) t={t:.0f}s nota={R['score']:.0f} {R['grade']} "
          f"{w.ac.crash_reason}")
    for it in R["items"]:
        print("    ", it)
    print("   mensajes:", " | ".join(msgs[:10]))
