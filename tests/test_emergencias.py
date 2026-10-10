"""Prueba de las lecciones de emergencia con un alumno robot que aplica el procedimiento.

Comprueba que cada falla aparece, que el paso avanza al hacer lo correcto y que la lección
termina sin errores. El robot mantiene el avión nivelado (o en planeo) y reacciona a los síntomas.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim.lessons import LESSONS_BY_ID as LB
from sim.mathx import FT, clamp, wrap180
from sim.world import World

w = World()


def hold(ac, w, L, dt, target_alt=None, glide=False):
    """Alas niveladas y altitud (o velocidad de planeo) con un control sencillo."""
    roll = math.degrees(ac.roll)
    ac.ctl_ail = clamp(-roll * 0.04 - ac.omega[0] * 0.3, -1, 1)
    if glide:
        err = w.ind.ias - ac.t.v["vglide"]
        pitch_cmd = clamp(err * 0.35, -8, 6)
    else:
        err = (target_alt - w.ind.alt_ft) if target_alt else 0.0
        pitch_cmd = clamp(2.0 + err * 0.01, -5, 8)
    ac.ctl_elev = clamp((pitch_cmd - math.degrees(ac.pitch)) * 0.08 - ac.omega[1] * 0.4, -0.7, 0.7)


def run(lesson_id, react, secs=150, glide_after_fail=False):
    L = LB[lesson_id]()
    if w.aircraft_id != L.aircraft:
        w.set_aircraft(L.aircraft)
    L.setup(w)
    dt = 1 / 60
    t = 0.0
    A = w.ind.alt_ft
    msgs = []
    while t < secs and not L.done:
        ac = w.ac
        failed = getattr(L, "t_fail", None) is not None
        hold(ac, w, L, dt, A, glide=glide_after_fail and failed)
        react(w, L, t)
        w.step(dt)
        evs = list(w.events)
        w.events.clear()
        L.update(dt, w, evs)
        msgs += [m for m, _ in L.messages]
        L.messages.clear()
        t += dt
    R = L.result(w)
    print(f"== {L.title}: paso {L.idx + 1}/{len(L.steps)} t={t:.0f}s choque={w.ac.crashed} {w.ac.crash_reason} "
          f"nota={R['score']:.0f}")
    for it in R["items"][-4:]:
        print("    ", it)
    print("    registro:", w.emerg.report())
    return L


def react_fire(w, L, t):
    s = w.ac.sys
    if s.fire_level > 0 and L.t_fail is not None and L.t - L.t_fail > 4:
        s.engine.mixture = 0.0
        s.fuel_selector = 0
        s.master = False


def react_smoke(w, L, t):
    s = w.ac.sys
    if s.smoke_level > 0.05:
        s.master = False


def react_radio(w, L, t):
    if w.ac.sys.failures["radio"]:
        w.xpdr = 7600


def react_trim(w, L, t):
    s = w.ac.sys
    if s.failures["trim"] and s.trim_cb and L.t - (L.t_fail or 0) > 2:
        w.emerg.trim_disconnect()


def react_gear(w, L, t):
    s = w.ac.sys
    if L.idx == 1:
        s.gear_down = True
    if L.idx == 2 and L.step.t > 3:
        w.emerg.gear_emergency()


def react_alt(w, L, t):
    s = w.ac.sys
    if s.failures["alternator"] and L.t - (L.t_fail or 0) > 5:
        s.lights["landing"] = False
        s.pitot_heat = False
        s.fuel_pump = False


def react_actitudes(w, L, t):
    e = w.ac.sys.engine
    if L.idx == 1 and L.step.t < 2:
        e.throttle = 1.0
    if L.idx == 3 and L.step.t < 2:
        e.throttle = 0.0
    if L.idx == 3 and L.step.t > 6:
        e.throttle = 0.6


run("fuego", react_fire, 90)
run("humo", react_smoke, 60)
run("radio_falla", react_radio, 50)
run("compensador", react_trim, 80)
run("tren", react_gear, 60)
run("alternador", react_alt, 60)
run("actitudes", react_actitudes, 60)
run("imc", lambda w, L, t: None, 40)
run("fuera_campo", lambda w, L, t: None, 30, glide_after_fail=True)


# ---- maniobras nuevas: comprobar que arrancan y avanzan sin errores
def react_none(w, L, t):
    pass


for lid, secs in (("vuelo_lento", 20), ("perdida_motor", 20), ("punto", 20), ("motor_aire", 40),
                  ("pista_corta", 20), ("pista_blanda", 20)):
    run(lid, react_none, secs)

for lid, secs in (("espera", 30), ("loc", 30), ("frustrada", 30), ("travesia", 30), ("desvio", 30)):
    run(lid, react_none, secs)

# examen: se fuerza el fin de cada tarea para comprobar que encadena y puntúa
L = LB["examen_ppl"]()
L.setup(w)
for k in range(len(L.tasks)):
    for i in range(120):
        w.step(1 / 60)
        L.update(1 / 60, w, [])
    L.sub.finish(True, "", w)
    L.update(1 / 60, w, [])
R = L.result(w)
print("== Examen PPL:", R["grade"], f"{R['score']:.0f}", "tareas", len(R["items"]))
for it in R["items"]:
    print("    ", it)
