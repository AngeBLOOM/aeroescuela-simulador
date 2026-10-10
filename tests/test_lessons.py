"""Alumno robot: vuela lecciones con un controlador sencillo para validar la evaluación."""
import math
import numpy as np
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim.lessons import LESSONS_BY_ID as LB
from sim.mathx import FT, KT, clamp, wrap180
from sim.world import World

LOC = os.environ.get("LOC")
if LOC:
    import pygame
    pygame.init()
    from sim import geo
    w = World(location=geo.build_location(LOC, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datos")))
else:
    w = World()
fallos = []


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


def fly(lesson_id, pilot, secs=400):
    pitch_pid.i = 0.0
    pitch_pid.prev = None
    L = LB[lesson_id]()
    L.setup(w)
    dt = 1 / 60
    t = 0.0
    msgs = []
    while t < secs and not L.done:
        pilot(w, L, t, dt)
        w.step(dt)
        evs = list(w.events)
        w.events.clear()
        L.update(dt, w, evs)
        for m, v in L.messages:
            msgs.append(m)
        L.messages.clear()
        t += dt
    R = L.result(w)
    print(f"== {L.title}: {'OK' if L.success else 'FALLO'} {L.fail_reason} t={t:.0f}s nota={R['score']:.0f} ({R['grade']})")
    for it in R["items"]:
        print("   ", it)
    print("   mensajes:", " | ".join(msgs[:12]))
    if not L.success:
        fallos.append(f"{L.title}: {L.fail_reason or 'no aprobada'}")
    return L


roll_pid = PID(0.05, 0.01, 0.01)
pitch_pid = PID(0.12, 0.05, 0.03, -0.6, 0.6)


def attitude(ac, roll_cmd_deg, pitch_cmd_deg, dt):
    ac.ctl_ail = clamp((roll_cmd_deg - math.degrees(ac.roll)) * 0.05 - ac.omega[0] * 0.3, -1, 1)
    ac.ctl_elev = pitch_pid(pitch_cmd_deg - math.degrees(ac.pitch), dt)


def takeoff_pilot(w, L, t, dt):
    ac = w.ac
    ac.sys.engine.throttle = 1.0
    hdg_err = wrap180(L.hdg - ac.heading)
    lat = L.rw_local(w)[1]
    if ac.on_ground:
        ac.ctl_rud = clamp(hdg_err * 0.15 - lat * 0.05 + 0.05, -1, 1)
        attitude(ac, 0, 9 if w.ind.ias > 55 else 0, dt)
        if w.ind.ias < 55:
            ac.ctl_elev = 0.0
    else:
        ac.ctl_rud = clamp(ac.beta * 3, -1, 1)
        pc = clamp(8 + (w.ind.ias - 74) * 0.6, 0, 14)
        attitude(ac, clamp(hdg_err * 1.0, -15, 15), pc, dt)


fly("despegue", takeoff_pilot, 200)


def landing_pilot(w, L, t, dt):
    ac = w.ac
    rw, ident = L._lrw
    along, lat = rw.local(ac.pos[0], ac.pos[1], ident)
    H = rw.end(ident)[1]
    ac.sys.flaps_cmd = 3
    h = (ac.alt_msl - w.home.elev)
    # senda: altura deseada a lo largo
    target_h = (-along + 300) * math.tan(math.radians(3)) if along < 0 else 300 * 0.0524 - along * 0.0
    trk_err = wrap180(0 - ac.track)
    rr = np.array([-rw.end(ident)[2][1], rw.end(ident)[2][0]])
    vlat = ac.vel[0] * rr[0] + ac.vel[1] * rr[1]
    trk_cmd = H + clamp(-lat * 0.15 - vlat * 1.0, -25, 25)
    roll_cmd = clamp(wrap180(trk_cmd - ac.track) * 1.0, -15, 15)
    if False:
        print(f"   t={t:4.0f} along={along:7.0f} lat={lat:6.1f} h={h:5.0f} tgt={target_h:5.0f} ias={w.ind.ias:4.0f} vs={ac.vs_fpm:5.0f} trk={ac.track:5.1f}")
    ra = ac.agl / FT
    if ra > 15:
        e = (target_h - h)
        ac.sys.engine.throttle = clamp(0.35 + e * 0.01 - (ac.vs_fpm + 400) * 0.0003, 0.05, 0.9)
        pc = clamp(-3 + (w.ind.ias - 65) * 0.4, -8, 6)
        attitude(ac, roll_cmd, pc, dt)
    elif not ac.on_ground:
        ac.sys.engine.throttle = 0.0
        attitude(ac, roll_cmd * 0.5, clamp(4 + (15 - ra) * 0.25, 2, 8), dt)
    else:
        ac.sys.engine.throttle = 0.0
        ac.ctl_elev = 0.2
        ac.brake = 1.0 if ac.gs > 3 else 0.5
        ac.ctl_rud = clamp(-lat * 0.1 + wrap180(H - ac.heading) * 0.1, -1, 1)
    if ac.on_ground:
        return
    ac.ctl_rud = clamp(ac.beta * 3, -1, 1)


fly("final", landing_pilot, 300)
fly("cruzado", landing_pilot, 300)


def stall_pilot(w, L, t, dt):
    ac = w.ac
    if L.idx == 0:
        ac.sys.engine.throttle = 0.0
        attitude(ac, 0, min(2 + t * 0.5, 18), dt)
    elif L.idx == 1:
        ac.sys.engine.throttle = 1.0
        attitude(ac, 0, -2 if L.steps[1].t < 2 else 6, dt)
    else:
        ac.sys.engine.throttle = 1.0
        attitude(ac, 0, clamp(8 + (w.ind.ias - 74) * 0.6, 0, 14), dt)
    ac.ctl_rud = clamp(ac.beta * 3, -1, 1)


fly("perdida", stall_pilot, 200)


def spin_pilot(w, L, t, dt):
    """Barrena: ralentí y palanca atrás, pedal izquierdo a fondo, una vuelta, PARE y salida del picado a ~2,8 G."""
    ac = w.ac
    for en in ac.sys.engines:
        en.throttle = 0.0
    if L.idx == 0:
        ac.ctl_ail, ac.ctl_rud = 0.0, clamp(ac.beta * 3, -1, 1)
        ac.ctl_elev = clamp(ac.ctl_elev + 0.6 * dt, -1, 1)
    elif L.idx in (1, 2):
        ac.ctl_ail, ac.ctl_rud, ac.ctl_elev = 0.0, -1.0, 1.0
    elif L.idx == 3:
        ac.ctl_ail, ac.ctl_rud, ac.ctl_elev = 0.0, 1.0, -0.3
    else:
        if L.step.t < dt * 1.5:
            ac.ctl_elev = 0.1
        ac.ctl_rud = clamp(ac.beta * 3.0, -1, 1)
        if ac.pitch > 0:                     # morro sobre el horizonte: nivelar, sin seguir tirando
            attitude(ac, 0, 2, dt)
        else:
            ac.ctl_ail = clamp(-math.degrees(ac.roll) * 0.05 - ac.omega[0] * 0.3, -1, 1)
            ac.ctl_elev = clamp(ac.ctl_elev + (2.8 - ac.nz) * 0.6 * dt, -0.4, 0.8)


fly("barrena", spin_pilot, 120)

# la barrena recoloca el avión 6500 ft más alto al prepararse: el variómetro no debe dar un pico falso al empezar
L = LB["barrena"]()
L.setup(w)
vs_pico = 0.0
for _ in range(60 * 3):
    w.step(1 / 60)
    vs_pico = max(vs_pico, abs(w.ind.vs_fpm))
print(f"  barrena: |VS| máx en los 3 primeros segundos {vs_pico:.0f} ft/min")
if vs_pico > 2000:
    fallos.append(f"pico falso de velocidad vertical al empezar la barrena ({vs_pico:.0f} ft/min)")

# un criterio repetido en varios pasos (la altitud del hielo en el carburador) sale en una sola fila de la evaluación
L = LB["hielo_carb"]()
L.setup(w)
L.all_monitors = [m for st in L.steps for m in st.monitors]
for m in L.all_monitors:
    m.update(2.0, w)
filas = [it for it in L.result(w)["items"] if it[0] == "Altitud"]
print(f"  hielo_carb: filas de Altitud en la evaluación {len(filas)} ({filas[0][1] if filas else '-'}/{filas[0][2] if filas else '-'})")
if len(filas) != 1 or filas[0][2] != 30:
    fallos.append(f"la altitud del hielo en el carburador sale en {len(filas)} filas")
print("FALLOS: " + "; ".join(fallos) if fallos else "TODO OK")
sys.exit(1 if fallos else 0)
