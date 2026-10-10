"""Misiones de Base Sucre voladas de principio a fin por un piloto robot (sin ventana):
amerizaje en el lago tras falla de motor, fuego sobre Maracay con planeo a la pista, nubes contra la
cordillera y el paso por los puntos de las misiones de navegación."""
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
loc = geo.build_location("SVBS", DATA)


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


def fly(lid, pilot, secs=600):
    w = World("c172", location=loc)
    L = LB[lid]()
    L.setup(w)
    pid = PID(0.12, 0.05, 0.03, -0.7, 0.7)
    dt = 1 / 60
    t = 0.0
    msgs = []
    while t < secs and not L.done:
        pilot(w, L, t, dt, pid)
        w.step(dt)
        evs = list(w.events)
        w.events.clear()
        L.update(dt, w, evs)
        msgs += [m for m, v in L.messages]
        L.messages.clear()
        t += dt
    R = L.result(w)
    print(f"== {L.title}: {'OK' if L.success else 'FALLO'} ({L.fail_reason}) t={t:.0f}s nota={R['score']:.0f} "
          f"{R['grade']} · {w.ac.crash_reason}")
    for it in R["items"]:
        print("    ", it)
    print("     mensajes:", " | ".join(msgs[:8]))
    return L, w


# ------------------------------------------------------------ 1. amerizaje
def ditch_pilot(w, L, t, dt, pid):
    ac = w.ac
    thr, hdg, d, r = w.runway_frame()
    he = wrap180(hdg - ac.heading)
    if L.t_fail is None:
        ac.sys.engine.throttle = 1.0
        if ac.on_ground:
            lat = (ac.pos[0] - thr[0]) * r[0] + (ac.pos[1] - thr[1]) * r[1]
            ac.ctl_rud = clamp(he * 0.15 - lat * 0.05 + 0.05, -1, 1)
            ac.ctl_ail = 0.0
            ac.ctl_elev = pid(9 - math.degrees(ac.pitch), dt) if w.ind.ias > 55 else 0.0
        else:
            att(ac, pid, clamp(he, -15, 15), clamp(8 + (w.ind.ias - 74) * 0.6, 0, 14), dt)
        return
    ac.sys.engine.throttle = 0.0
    agl = ac.agl / FT
    if agl < 250:
        ac.sys.flaps_cmd = len(ac.t.flap_settings) - 1
        w.xpdr = 7700
    if agl > 25:
        pc = clamp(-4 + (w.ind.ias - 65) * 0.5, -10, 4)
    else:
        pc = clamp(3 + (25 - agl) * 0.3, 2, 8)          # recogida: velocidad mínima y poca bajada
    att(ac, pid, clamp(he * 0.8, -10, 10), pc, dt)


fly("svbs_amerizaje", ditch_pilot, 240)


# ------------------------------------------------------------ 2. fuego sobre Maracay → planeo a Base Sucre 29
def fire_pilot(w, L, t, dt, pid):
    ac = w.ac
    s = ac.sys
    if L.t_fail is None:
        s.engine.throttle = 0.65
        att(ac, pid, clamp(wrap180(150 - ac.heading), -15, 15), 2 + (5000 - w.ind.alt_ft) * 0.01, dt)
        return
    if L.t - L.t_fail > 3:
        s.engine.mixture = 0.0
        s.fuel_selector = 0
    if L.t - L.t_fail > 8:
        s.master = False
    s.engine.throttle = 0.0
    rw = w.home.runways[0]
    thr, hdg, d = rw.end("29")
    along, lat = rw.local(ac.pos[0], ac.pos[1], "29")
    agl = ac.agl / FT
    # hacia la prolongación del eje de la 29 y después por el eje
    tgt = thr - d * max(400.0, -along * 0.5) if along < -400 else thr + d * 600
    brg = math.degrees(math.atan2(tgt[1] - ac.pos[1], tgt[0] - ac.pos[0])) % 360
    if along > -2500:
        brg = hdg + clamp(-lat * 0.03, -20, 20)
    if agl < 400:
        s.flaps_cmd = 2
    if ac.on_ground:
        # volante atrás y frenado progresivo (frenar a fondo a 60 kt clava el morro)
        ac.brake = 1.0 if w.ind.ias < 40 else 0.3
        ac.ctl_elev = 0.6
        ac.ctl_ail = 0.0
        ac.ctl_rud = clamp(-lat * 0.1 + wrap180(hdg - ac.heading) * 0.1, -1, 1)
        return
    pc = clamp(-3 + (w.ind.ias - 68) * 0.5, -10, 5) if agl > 20 else clamp(4 + (20 - agl) * 0.25, 2, 8)
    # gestión de energía: si va demasiado alto para la distancia, espiral descendente antes de la final
    dthr = math.hypot(ac.pos[0] - thr[0], ac.pos[1] - thr[1])
    too_high = ac.agl > dthr * math.tan(math.radians(5)) + 60
    if too_high and along < -1500 and not L.__dict__.get("final"):
        att(ac, pid, -28, pc, dt)
        return
    if along > -3000 and not too_high:
        L.__dict__["final"] = True
    if L.__dict__.get("final") and ac.agl > dthr * math.tan(math.radians(3)) + 20:
        s.flaps_cmd = 3
    att(ac, pid, clamp(wrap180(brg - ac.heading), -25, 25), pc, dt)


fly("svbs_fuego", fire_pilot, 600)


# ------------------------------------------------------------ 3. nubes contra la cordillera
def imc_pilot(w, L, t, dt, pid):
    ac = w.ac
    ac.sys.engine.throttle = 0.62
    A = 4000
    pc = clamp(2 + (A - w.ind.alt_ft) * 0.012, -4, 8)
    if L.idx >= 1:
        e = wrap180(180 - ac.heading)
        roll = clamp(e * 0.6, -20, 20) if abs(e) > 3 else 0.0
        roll = -20 if L.idx == 1 and abs(e) > 30 else roll        # viraje a la izquierda (hacia el oeste y el lago)
    else:
        roll = clamp(wrap180(360 - ac.heading), -10, 10)
    att(ac, pid, roll, pc, dt)


fly("svbs_cordillera", imc_pilot, 200)


# ------------------------------------------------------------ 4. puntos de las misiones de navegación (teletransporte)
for lid in ("svbs_lago", "svbs_libertador"):
    w = World("c172", location=loc)
    L = LB[lid]()
    L.setup(w)
    print(f"== {L.title}: pista {w.active_end}, ruta {[tuple(np.round(p, 0)) for p in w.route]}")
    for k, st in enumerate(L.steps):
        print(f"     paso {k + 1}: {st.text}")
    L.update(1 / 60, w, [])
    # despegue simulado y paso por cada punto
    pts = [w.route[1], w.route[-1]]
    w.ac.place_in_air(w.home.ref[0], w.home.ref[1], w.home.elev + 800 * FT, 285, 90)
    for _ in range(30):
        w.step(1 / 60)
        L.update(1 / 60, w, [])
    for p in pts:
        w.ac.place_in_air(p[0], p[1], 3000 * FT, 90, 100)
        for _ in range(240):
            w.step(1 / 60)
            L.update(1 / 60, w, [])
        print(f"     en {tuple(np.round(p, 0))}: paso actual {L.idx + 1}/{len(L.steps)} «{L.step.text if L.step else 'fin'}»")
