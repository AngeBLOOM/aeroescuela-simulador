"""Misiones de noche y meteorología (categoría 12) voladas de principio a fin por un piloto robot, sin ventana.
Comprueba que cada misión empieza bien (pista, posición, hora, lluvia, tormenta) y que se puede completar."""
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
LOCS = {}


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


def takeoff(w, L, dt, pid, hdg_after, alt_ft):
    ac = w.ac
    e = ac.sys.engine
    thr, hdg, d, r = w.runway_frame()
    if ac.on_ground:
        lat = (ac.pos[0] - thr[0]) * r[0] + (ac.pos[1] - thr[1]) * r[1]
        e.throttle = 1.0
        ac.ctl_rud = clamp(wrap180(hdg - ac.heading) * 0.15 - lat * 0.05 + 0.05, -1, 1)
        ac.ctl_ail = 0.0
        ac.ctl_elev = pid(9 - math.degrees(ac.pitch), dt) if w.ind.ias > 55 else 0.0
        return
    tgt = hdg if ac.agl / FT < 500 else hdg_after
    fly_to_hdg_alt(w, dt, pid, tgt, alt_ft)


def fly_to_hdg_alt(w, dt, pid, hdg, alt_ft, bank=20):
    ac = w.ac
    e = ac.sys.engine
    if w.ind.alt_ft < alt_ft - 150:
        e.throttle = 1.0
        pc = clamp(8 + (w.ind.ias - 74) * 0.6, 0, 14)
    else:
        e.throttle = 0.62 if w.ind.alt_ft < alt_ft + 300 else 0.35
        pc = clamp(2 + (alt_ft - w.ind.alt_ft) * 0.012, -5, 8)
    att(ac, pid, clamp(wrap180(hdg - ac.heading) * 1.0, -bank, bank), pc, dt)


def brg_to(ac, p):
    return math.degrees(math.atan2(p[1] - ac.pos[1], p[0] - ac.pos[0])) % 360


def land(w, L, dt, pid, vapp=65):
    """Senda de 3° hacia el punto de toma, con corrección de deriva, recogida y frenada progresiva."""
    ac = w.ac
    e = ac.sys.engine
    rw, ident = L._lrw
    elev = w.airports[getattr(L, "airport_idx", 0)].elev
    along, lat = rw.local(ac.pos[0], ac.pos[1], ident)
    H, d = rw.end(ident)[1], rw.end(ident)[2]
    if along < -7500 or abs(lat) > 1500 or (along > 0 and ac.agl / FT > 300 and not ac.on_ground):
        # incorporación a la prolongación del eje a 7 km
        thr = rw.end(ident)[0]
        p = thr - d * 7000
        b = brg_to(ac, p) if math.hypot(*(p - ac.pos[:2])) > 900 else H
        fly_to_hdg_alt(w, dt, pid, b, elev / FT + 1300, 25)
        return
    h = ac.alt_msl - elev
    target_h = (-along + 480) * math.tan(math.radians(3)) if along < 0 else max(0.0, 480 - along) * 0.0524
    rr = np.array([-d[1], d[0]])
    vlat = ac.vel[0] * rr[0] + ac.vel[1] * rr[1]
    trk_cmd = H + clamp(-lat * 0.15 - vlat * 1.0, -25, 25)
    roll_cmd = clamp(wrap180(trk_cmd - ac.track) * 1.0, -15, 15)
    if along > -5500:
        ac.sys.flaps_cmd = 3
    if ac.agl / FT < 300:
        ac.sys.lights["landing"] = True
    ra = ac.agl / FT
    if ra > 15 and not ac.on_ground:
        err = target_h - h
        e.throttle = clamp(0.35 + err * 0.01 - (ac.vs_fpm + 400) * 0.0003, 0.05, 0.95)
        att(ac, pid, roll_cmd, clamp(-3 + (w.ind.ias - vapp) * 0.4, -8, 6), dt)
    elif not ac.on_ground:
        # recogida con un poco de motor si aún no ha llegado a la pista
        e.throttle = 0.18 if along < 60 else 0.0
        att(ac, pid, roll_cmd * 0.5, clamp(4 + (15 - ra) * 0.25, 2, 8), dt)
    else:
        e.throttle = 0.0
        # volante atrás y frenada progresiva (frenar fuerte a mucha velocidad clava el morro y la hélice toca)
        ac.ctl_elev = 0.6
        ac.ctl_ail = 0.0
        ac.brake = 0.6 if w.ind.ias < 30 else (0.25 if w.ind.ias < 50 else 0.0)
        ac.ctl_rud = clamp(-lat * 0.1 + wrap180(H - ac.heading) * 0.1, -1, 1)


# ------------------------------------------------------------ pilotos de cada misión
def p_final(w, L, t, dt, pid):
    land(w, L, dt, pid, 70 if L.id in ("nc_aguacero", "nc_tormenta") else 65)


def p_circuito(w, L, t, dt, pid):
    ac = w.ac
    if not ac.sys.lights["landing"]:
        ac.sys.lights.update(nav=True, beacon=True, landing=True)
    if L.idx == 0:
        takeoff(w, L, dt, pid, w.runway_frame()[1], L.elev_ft + 1000)
        return
    if L.gi < len(L.gates):
        x, y, a, h, _ = L.gates[L.gi]
        fly_to_hdg_alt(w, dt, pid, brg_to(ac, (x, y)), a, 25)
        return
    land(w, L, dt, pid)


def p_electrica(w, L, t, dt, pid):
    ac = w.ac
    s = ac.sys
    if L.t_fail is not None:
        s.lights["landing"] = False
        s.pitot_heat = False
        s.fuel_pump = False
    if L.idx < 2:
        if not hasattr(L, "_hold"):
            L._hold = (ac.heading, w.ind.alt_ft)
        fly_to_hdg_alt(w, dt, pid, *L._hold)
        return
    if not hasattr(L, "_lrw"):
        L._lrw = (w.active_rw, w.active_end)
    land(w, L, dt, pid)


def p_desvio(w, L, t, dt, pid):
    ac = w.ac
    if L.idx == 0:
        takeoff(w, L, dt, pid, 200.0, L.cruise)
        return
    wps = L.waypoints(w)
    if L.wp_i < len(wps):
        fly_to_hdg_alt(w, dt, pid, brg_to(ac, wps[L.wp_i][1]), L.cruise, 25)
        return
    land(w, L, dt, pid)


def p_niebla(w, L, t, dt, pid):
    land(w, L, dt, pid, 68)


def run(lid, pilot, secs=900):
    code = getattr(LB[lid], "location", "SVBS")
    if code not in LOCS:
        LOCS[code] = geo.build_location(code, DATA)
    w = World("c172", location=LOCS[code])
    L = LB[lid]()
    L.setup(w)
    if not hasattr(L, "_lrw") and hasattr(L, "landing_runway"):
        pass
    wx = w.weather
    print(f"-- {L.title}\n   pista {w.active_end}, hora {wx.hour:.2f}, lluvia {wx.rain:.2f}, tormenta {wx.storm}, "
          f"visibilidad {w.atmo.visibility():.0f} m, METAR {wx.describe()}")
    pid = PID(0.12, 0.05, 0.03, -0.7, 0.7)
    dt = 1 / 60
    t = 0.0
    msgs = []
    max_core = 0.0
    while t < secs and not L.done:
        pilot(w, L, t, dt, pid)
        w.step(dt)
        evs = list(w.events)
        w.events.clear()
        L.update(dt, w, evs)
        msgs += [m for m, v in L.messages]
        L.messages.clear()
        max_core = max(max_core, w.atmo.storm_near)
        t += dt
    R = L.result(w)
    print(f"== {'OK' if L.success else 'FALLO'} ({L.fail_reason}) t={t:.0f}s nota={R['score']:.0f} {R['grade']} "
          f"{w.ac.crash_reason} · pista mojada {w.atmo.wet:.2f}, frente de tormenta máx {max_core:.2f}")
    J = L.landing
    if J is not None and J.touch is not None:
        rw, ident = L._lrw
        al, la = rw.local(w.ac.pos[0], w.ac.pos[1], ident)
        print(f"   toma a {J.touch['along']:.0f} m del umbral {ident} (lateral {J.touch['lat']:.1f}), detenido a {al:.0f} m "
              f"de {rw.length:.0f} m, lateral {la:.1f} m")
    for it in R["items"]:
        print("    ", it)
    print("   mensajes:", " | ".join(msgs[:10]))
    return L, R


if __name__ == "__main__":
    only = sys.argv[1:]
    plan = [("nc_agujero_negro", p_final), ("nc_carlota", p_final), ("nc_aguacero", p_final), ("nc_tormenta", p_final),
            ("nc_niebla", p_niebla), ("nc_circuito", p_circuito), ("nc_electrica", p_electrica), ("nc_desvio", p_desvio)]
    res = []
    for lid, pil in plan:
        if only and lid not in only:
            continue
        L, R = run(lid, pil)
        res.append((lid, L.success, R["score"]))
    print("\nRESUMEN:", ", ".join(f"{lid} {'OK' if ok else 'FALLO'} {sc:.0f}" for lid, ok, sc in res))
