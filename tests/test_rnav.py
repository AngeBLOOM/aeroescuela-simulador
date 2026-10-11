"""Aproximaciones RNAV (GPS) de entrenamiento: geometría del procedimiento en T, escala de aproximación, senda vertical
como la del ILS, y un vuelo con el piloto automático en APR acoplado desde el IF hasta la altura de decisión."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim import rnav
from sim.mathx import FT, KT, NM, clamp, wrap180
from sim.world import World

fallos = []


def check(ok, msg):
    print(("  ok   " if ok else "  FALLO ") + msg)
    if not ok:
        fallos.append(msg)


w = World("c172")
apt = w.home
rw = w.active_rw
end = w.active_end
apr = rnav.build(apt, rw, end)
fx = apr.fixes
thr, hdg, d = rw.end(end)

print("Procedimiento")
check("ENTRENAMIENTO" in apr.title and "NO PUBLICADA" in apr.title, f"marcada como de entrenamiento: «{apr.title}»")


def back_nm(p):
    return -((p[0] - thr[0]) * d[0] + (p[1] - thr[1]) * d[1]) / NM


def lat_nm(p):
    return ((p[0] - thr[0]) * -d[1] + (p[1] - thr[1]) * d[0]) / NM


check(abs(back_nm(fx.faf.pos) - 5) < 0.01 and abs(back_nm(fx.if_.pos) - 9) < 0.01 and abs(back_nm(fx.map.pos)) < 0.01,
      f"FAF a {back_nm(fx.faf.pos):.1f} NM, IF a {back_nm(fx.if_.pos):.1f} NM, MAP en el umbral")
check(abs(lat_nm(fx.iaf_l.pos) + 4) < 0.01 and abs(lat_nm(fx.iaf_r.pos) - 4) < 0.01, "IAF a 4 NM a cada lado del IF")
faf_agl = fx.faf.alt_ft - apr.elev_ft
check(1550 < faf_agl < 1650 and abs(fx.if_.alt_ft - apr.elev_ft - 2500) < 1,
      f"FAF a {faf_agl:.0f} ft sobre el umbral (senda de 3°), IF a 2500 ft")
check([p.role for p in apr.legs("L")] == ["IAF", "IF", "FAF", "MAP", "MAH"] and len(apr.legs(None)) == 4,
      "secuencia IAF → IF → FAF → MAP → espera; con vectores, desde el IF")
check(len(rnav.for_world(w)) == sum(2 * len(a.runways) for a in w.airports), "una aproximación por cada extremo de pista")
left_side = thr - d * 12 * NM + rnav.np.array([-d[1], d[0]]) * -6 * NM
behind = thr - d * 15 * NM
check(rnav.best_iaf(apr, left_side) == "L" and rnav.best_iaf(apr, behind) is None,
      "IAF del lado por el que se llega; alineado detrás del IF: vectores al IF")
ent = [rnav.entry(apr, thr - d * nm * NM) for nm in (15, 7, 3)]
check(ent == [(None, "IF"), (None, "FAF"), (None, "MAP")],
      f"ya alineado en el final se va al siguiente punto por delante: {ent}")
g0 = World("c172").gps
g0.load_approach(rnav.build(g0.world.home, g0.world.active_rw, g0.world.active_end), None, "MAP")
check(g0.target.role == "MAP", f"cargada a 3 NM en el final: activa hacia el umbral ({g0.ident})")
# otra aproximación reemplaza a la anterior y deja los puntos de ruta del instructor
g1 = World("c172").gps
w1 = g1.world
vn = g1.find("VN", "NDB")
g1.add(vn)
a_esc = rnav.for_world(w1)
a1 = next(a for a in a_esc if a.airport.ident == "ESC")
a2 = next(a for a in a_esc if a.airport.ident == "VNT")
g1.load_approach(a1, "L")
g1.load_approach(a2, "R")
ids1 = [p.ident for p in g1.plan]
check(ids1[0] == "VN" and g1.approach is a2 and not any(i.startswith("ESC") for i in ids1) and len(ids1) == 6,
      f"cambiar de aproximación la reemplaza: {ids1}")

print("Agujas en el tramo final")
g = w.gps
g.load_approach(apr, None)
g.activate(apr.legs(None).index(fx.map) if False else 2)    # tramo FAF → MAP
ac = w.ac
w.cdi_src = "GPS"


def place(nm, above_ft=0.0, side_nm=0.0):
    p = thr - d * nm * NM + rnav.np.array([-d[1], d[0]]) * side_nm * NM
    path_ft = apr.tch_ft + nm * NM / FT * math.tan(math.radians(3.0))
    ac.place_in_air(p[0], p[1], (apr.elev_ft + path_ft + above_ft) * FT, hdg, 90, flaps_idx=1)
    g.update(ac)


place(4.0)
check(g.scale == "APR" and g.is_loc and g.gs_valid and abs(g.gs) < 0.05 and abs(g.cdi) < 0.05,
      f"en la senda a 4 NM: escala {g.scale}, aguja {g.cdi:+.2f}, senda {g.gs:+.2f}")
place(4.0, above_ft=200)
check(g.gs < -0.3, f"200 ft por encima: la senda pide bajar ({g.gs:+.2f})")
place(4.0, side_nm=0.15)
check(-0.6 < g.cdi < -0.4, f"0,15 NM a la derecha: media escala con 0,3 NM ({g.cdi:+.2f})")
g.activate(1)                                                # hacia el FAF, lejos: todavía en terminal
place(8.5)
check(g.scale == "TERM" and not g.gs_valid, f"lejos del FAF: escala {g.scale}, sin senda")

print("Vuelo con el piloto automático en APR desde el IF")
w = World("c172")
apr = rnav.build(w.home, w.active_rw, w.active_end)
ac = w.ac
g = w.gps
p0 = thr - d * 10.5 * NM
ac.place_in_air(p0[0], p0[1], apr.fixes.if_.alt_ft * FT, hdg + 25, 95, flaps_idx=1)
g.load_approach(apr, None)
w.cdi_src = "GPS"
w.ind.reset(ac, w.kollsman)
w.step(1 / 60)                          # un paso: la altitud indicada del avión ya es la nueva al pulsar ALT
w.ap.set_alt(ac)
w.ap.set_nav(ac, approach=True)
dt = 1 / 60
t = 0.0
modes = set()
worst_lat, worst_v, at_da = 0.0, 0.0, None
while t < 600 and not ac.crashed:
    cmd = w.apply_autopilot(dt)
    if cmd is not None:
        ac.ctl_elev, ac.ctl_ail = cmd
    ac.ctl_rud = clamp(ac.beta * 3, -1, 1)
    for en in ac.sys.engines:                                # gases para 90 kt (no hay autogases)
        en.throttle = clamp(en.throttle + (90 - ac.ias_kt) * 0.02 * dt, 0.0, 1.0)
    w.step(dt)
    t += dt
    modes.add((w.ap.lat, w.ap.vert))
    nm = back_nm(ac.pos)
    if w.ap.vert == "GS" and nm < 4.0:
        path_ft = apr.elev_ft + apr.tch_ft + nm * NM / FT * math.tan(math.radians(3.0))
        worst_lat = max(worst_lat, abs(lat_nm(ac.pos)))
        worst_v = max(worst_v, abs(ac.alt_msl / FT - path_ft))
    if ac.alt_msl / FT < apr.da_ft and nm > 0:
        at_da = (t, nm, lat_nm(ac.pos), ac.ias_kt)
        break
check(("APR", "GS") in modes, f"el piloto automático captura la senda del GPS: {sorted(modes)}")
check(at_da is not None and not ac.crashed, f"llega a la altura de decisión: {at_da}")
check(worst_lat < 0.1, f"lateral en el tramo final ≤ 0,1 NM: máx {worst_lat:.3f} NM")
check(worst_v < 100, f"vertical en la senda (últimas 4 NM) ≤ 100 ft: máx {worst_v:.0f} ft")
if at_da:
    check(abs(at_da[2]) < 0.05, f"en la altura de decisión, sobre el eje: {at_da[2] * NM:.0f} m del eje a {at_da[1]:.2f} NM")

print("Lección «Aproximación RNAV (GPS)» con el piloto automático: IAF → IF → FAF → altura de decisión")
from sim.lessons import LESSONS_BY_ID                             # noqa: E402

w = World("c172")
L = LESSONS_BY_ID["rnav"]()
L.setup(w)
ac, g = w.ac, w.gps
check(g.approach is L.apr and w.cdi_src == "GPS" and g.target.role == "IAF",
      f"empieza con la RNAV cargada desde el IAF ({g.ident}) y el CDI en GPS")
w.step(dt)
w.ap.set_alt(ac)
w.ap.set_nav(ac, approach=True)
roles, t = [], 0.0
while t < 900 and not L.done and not ac.crashed and L.idx < 4:
    cmd = w.apply_autopilot(dt)
    if cmd is not None:
        ac.ctl_elev, ac.ctl_ail = cmd
    ac.ctl_rud = clamp(ac.beta * 3, -1, 1)
    for en in ac.sys.engines:
        en.throttle = clamp(en.throttle + ((90 if L.idx < 3 else 72) - ac.ias_kt) * 0.02 * dt, 0.0, 1.0)
    if L.idx >= 3:
        ac.sys.flaps_cmd = 3
    w.step(dt)
    evs = list(w.events)
    w.events.clear()
    L.update(dt, w, evs)
    t += dt
    r = getattr(g.target, "role", "")
    if not roles or roles[-1] != r:
        roles.append(r)
check(roles[:3] == ["IAF", "IF", "FAF"], f"secuencia del GPS: {roles}")
check(L.idx >= 4 and not ac.crashed, f"la lección llega a la altura de decisión (paso {L.idx + 1}, {t:.0f} s)")
mons = {m.name: m for m in L.all_monitors}
for name in ("Lateral (GPS)", "Senda (GPS)"):
    m = mons.get(name)
    check(m is not None and m.frac > 0.95, f"{name}: {m.frac * 100 if m else 0:.0f}% del tiempo dentro de 3/4 de escala")

print("\nFALLOS: " + "; ".join(fallos) if fallos else "\nTODO OK")
sys.exit(1 if fallos else 0)
