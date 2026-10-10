"""Pruebas de rendimiento de los Diamond DA40 y DA42 (incluye vuelo con un motor y Vmc)."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim.mathx import FT, KT, clamp, wrap180
from sim.world import World

w = World()


def fly(secs, ctl=None, every=10, label=""):
    t = 0.0
    dt = 1 / 60
    nxt = 0
    out = None
    while t < secs:
        if ctl:
            ctl(t, dt)
        w.step(dt)
        t += dt
        if t >= nxt:
            nxt += every
            ac = w.ac
            out = (w.ind.ias, ac.vs_fpm)
            print(f"  {label} t={t:5.0f} ias={w.ind.ias:5.1f} alt={w.ind.alt_ft:6.0f} vs={ac.vs_fpm:+6.0f} hdg={ac.heading:5.1f} "
                  f"roll={math.degrees(ac.roll):+5.1f} beta={math.degrees(ac.beta):+5.1f} rud={ac.ctl_rud:+.2f} "
                  f"rpm={[round(e.rpm) for e in ac.sys.engines]} {ac.crash_reason}")
        if w.ac.crashed:
            break
    return out


def hold(target_ias, hdg_target=None, rud_assist=True, bank_into=0.0):
    st = {"i": 0.0}

    def ctl(t, dt):
        ac = w.ac
        err = math.radians(clamp((w.ind.ias - target_ias) * 0.6, -8, 8)) + math.radians(6) - ac.pitch
        st["i"] = clamp(st["i"] + err * dt * 0.8, -0.5, 0.5)
        ac.ctl_elev = clamp(st["i"] + err * 2.0 - ac.omega[1] * 0.5, -1, 1)
        h = hdg_target if hdg_target is not None else ac.heading
        roll_cmd = clamp(wrap180(h - ac.heading) * 1.0 + bank_into, -20, 20)
        ac.ctl_ail = clamp((math.radians(roll_cmd) - ac.roll) * 2.0 - ac.omega[0] * 0.4, -1, 1)
        if rud_assist:
            ac.ctl_rud = clamp(ac.beta * 6.0 - ac.omega[2] * 1.0 + wrap180((hdg_target or ac.heading) - ac.heading) * 0.05, -1, 1)
    return ctl


for aid in ("da42",):
    w.set_aircraft(aid)
    t = w.ac.t
    print("=====", t.name, "masa", round(w.ac.sys.mass))
    w.reposition("crucero")
    print(" crucero equilibrado sin mandos")
    fly(30, every=15)
    w.reposition("pista")
    print(" despegue: potencia máxima, rotación a Vr y ascenso a Vy")
    st = {}

    def to(tt, dt):
        ac = w.ac
        for e in ac.sys.engines:
            e.throttle = 1.0
        if ac.on_ground:
            ac.ctl_elev = 0.0 if w.ind.ias < t.v["vr"] else 0.4
            ac.ctl_rud = clamp(wrap180(w.active_rw.end(w.active_end)[1] - ac.heading) * 0.2, -1, 1)
        else:
            hold(t.v["vy"], w.active_rw.end(w.active_end)[1])(tt, dt)
            if w.ac.agl > 60 and t.retractable:
                w.ac.sys.gear_down = False
    fly(70, to, every=10, label="TO")
    if aid == "da42":
        print(" FALLA DEL MOTOR IZQUIERDO a Vyse con motor bueno a fondo, embanderado")
        w.reposition("crucero")
        w.ac.sys.gear_down = False
        w.ac.sys.gear_pos = 0.0
        w.ac.sys.failures["engine"] = True
        w.ac.sys.engines[0].magnetos = 0          # motor parado y embanderado
        w.ac.sys.engines[1].throttle = 1.0
        hdg0 = w.ac.heading
        fly(60, hold(t.v["vyse"], hdg0, bank_into=4.0), every=10, label="SE")
        print(" mismo caso SIN embanderar (molinete)")
        w.reposition("crucero")
        w.ac.sys.gear_down = False
        w.ac.sys.gear_pos = 0.0
        w.ac.sys.failures["engine"] = True
        w.ac.sys.engines[1].throttle = 1.0
        fly(40, hold(t.v["vyse"], w.ac.heading, bank_into=4.0), every=10, label="SEw")
        print(" Vmc: motor izq. a ralentí, derecho a fondo, frenando hasta perder el control (timón a fondo derecho)")
        w.reposition("crucero")
        w.ac.sys.gear_down = False
        w.ac.sys.gear_pos = 0.0
        w.ac.sys.engines[0].throttle = 0.0
        w.ac.sys.engines[1].throttle = 1.0
        h0 = w.ac.heading
        st2 = {"tgt": 90.0}

        def vmc(tt, dt):
            st2["tgt"] = max(55.0, 90.0 - tt * 1.0)
            hold(st2["tgt"], h0, rud_assist=False, bank_into=5.0)(tt, dt)
            ac = w.ac
            ac.ctl_rud = clamp(wrap180(h0 - ac.heading) * -0.0 + 0.0 + (ac.beta * 6 - ac.omega[2]) , -1, 1)
            ac.ctl_rud = clamp(ac.ctl_rud + clamp(-wrap180(ac.heading - h0) * 0.2, -1, 1), -1, 1)
            if abs(wrap180(ac.heading - h0)) > 20 and "vmc" not in st2:
                st2["vmc"] = w.ind.ias
                print(f"   >> pérdida de control direccional a {w.ind.ias:.0f} KIAS (Vmc publicada {t.v['vmc']})")
        fly(45, vmc, every=5, label="VMC")
