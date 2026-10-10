"""Centro de gravedad: con el CG adelante hace falta más compensador y más profundidad (tirar) para volar despacio;
con el CG atrás, menos, y el avión es menos estable. Dentro de la envolvente del manual todos los aviones siguen
siendo estables, y una perturbación de cabeceo se amortigua."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim.aircraft_data import AIRCRAFT
from sim.mathx import KT, clamp
from sim.weight import DATA, IN, WeightBalance, limits_at, reference_cg
from sim.world import World

fallos = []

# ---------------------------------------------------------------- 1. margen estático en la envolvente
print("Margen estático (% de la cuerda media) con el CG de referencia y en los límites del manual")
for tid, d in DATA.items():
    t = AIRCRAFT[tid]()
    ref = reference_cg(t)

    def margin(cg):
        return -(t.Cma + t.CLa * (cg - ref) * IN / t.c) / t.CLa * 100

    aft = max(limits_at(d["env"], w)[1] for w, _, _ in d["env"])
    fwd = min(limits_at(d["env"], w)[0] for w, _, _ in d["env"])
    print(f"  {tid:6s} ref {ref:6.1f} in: {margin(ref):5.1f} %   delantero {fwd:6.1f} in: {margin(fwd):5.1f} %   "
          f"trasero {aft:6.1f} in: {margin(aft):5.1f} %")
    if margin(aft) < 3.0:
        fallos.append(f"{tid}: margen estático {margin(aft):.1f} % en el límite trasero (mínimo 3 %)")

# ---------------------------------------------------------------- 2. compensador y profundidad a 65 kt (C172)
# delantero y trasero: la misma carga total (180 kg y 100 L) en otros asientos; límite: el CG trasero del manual
LOADS = {"delantero": dict(front=180.0, rear=0.0, bag=0.0, fuel=100.0),
         "referencia": None,
         "trasero": dict(front=80.0, rear=46.0, bag=54.0, fuel=100.0),
         "límite trasero": dict(front=80.0, rear=160.0, bag=54.0, fuel=150.0)}


def load(w, name):
    ac = w.ac
    ac.t.cg_in = None
    spec = LOADS[name]
    if spec is None:
        return None
    ac.sys.fuel_l = spec["fuel"]
    wb = WeightBalance(ac.t.id)
    wb.loads = {k: spec[k] for k in ("front", "rear", "bag")}
    r = wb.apply(ac.t, ac.sys.fuel_l)
    assert r["ok_cg"] and r["ok_w"], (name, r)
    return r


def slow_flight(name, secs=40):
    """Vuela nivelado a 65 kt con el compensador de la carga de referencia y devuelve la profundidad media."""
    w = World("c172")
    w.reposition("final3")
    ac = w.ac
    load(w, "referencia")
    ac.place_in_air(ac.pos[0], ac.pos[1], 3000 * 0.3048, 360, 65)
    trim_ref = ac.trim
    r = load(w, name)
    trim_own = ac.trim_solution(65 * KT * math.sqrt(1.225 / ac.rho), ac.rho)[1]
    ac.trim = trim_ref
    A = ac.alt_msl
    integ, elev, n = 0.0, 0.0, 0
    for i in range(int(secs * 60)):
        vs = -ac.vel[2]
        vs_tgt = clamp((A - ac.alt_msl) * 0.2, -2.0, 2.0)
        integ = clamp(integ + 0.05 * (vs_tgt - vs) / 60, -1, 1)
        ac.ctl_elev = clamp(integ + 0.08 * (vs_tgt - vs) - 0.6 * ac.omega[1], -1, 1)
        ac.ctl_ail = clamp(-math.degrees(ac.roll) * 0.04 - ac.omega[0] * 0.3, -1, 1)
        w.step(1 / 60)
        if i >= secs * 60 / 2:
            elev += ac.ctl_elev
            n += 1
    cg = r["cg"] if r else reference_cg(ac.t)
    return cg, trim_own, elev / n, abs(ac.alt_msl - A) / 0.3048, ac.ias_kt


print("\nC172 nivelado a 65 kt con el compensador de la carga de referencia")
res = {}
for name in ("delantero", "referencia", "trasero"):
    cg, trim, elev, dalt, ias = slow_flight(name)
    res[name] = (trim, elev)
    print(f"  CG {name:10s} {cg:5.1f} in: compensador necesario {trim:+.3f}  profundidad media {elev:+.3f} "
          f"(desvío de altitud {dalt:.0f} ft, {ias:.0f} kt)")
    if dalt > 100:
        fallos.append(f"CG {name}: no mantuvo la altitud ({dalt:.0f} ft)")
if not res["delantero"][0] > res["referencia"][0] > res["trasero"][0]:
    fallos.append("el compensador necesario no sigue al CG (delante > referencia > atrás)")
if not res["delantero"][1] > res["trasero"][1] + 0.02:
    fallos.append("con el mismo peso, el CG delantero no pide más profundidad que el trasero")

# ---------------------------------------------------------------- 3. perturbación de cabeceo con el CG atrás
print("\nC172 compensado, tirón de cabeceo y mandos sueltos (velocidad de cabeceo, °/s)")
for name in ("referencia", "límite trasero"):
    w = World("c172")
    w.reposition("final3")
    ac = w.ac
    r = load(w, name)
    ac.place_in_air(ac.pos[0], ac.pos[1], 3000 * 0.3048, 360, 100)
    w.step(1 / 60)
    ac.omega[1] += 0.15
    first, later, nose = 0.0, 0.0, 0.0
    for i in range(10 * 60):
        ac.ctl_elev = 0.0
        ac.ctl_ail = clamp(-math.degrees(ac.roll) * 0.04 - ac.omega[0] * 0.3, -1, 1)
        w.step(1 / 60)
        q = abs(math.degrees(ac.omega[1]))
        if i < 2 * 60:
            first = max(first, q)
        elif i >= 4 * 60:
            later = max(later, q)
        nose = max(nose, abs(math.degrees(ac.pitch)))
    cg = r["cg"] if r else reference_cg(ac.t)
    print(f"  CG {name:14s} {cg:5.1f} in: {first:4.1f} °/s en los 2 primeros s, {later:4.2f} °/s de 4 a 10 s, "
          f"cabeceo máximo {nose:.1f}°")
    if not later < 0.3 * first or nose > 15:
        fallos.append(f"CG {name}: la perturbación de cabeceo no se amortigua ({first:.1f} -> {later:.2f} °/s)")

# ---------------------------------------------------------------- 4. distancias de la tableta (peso y rendimiento)
# a nivel del mar, ISA, peso máximo y sin viento deben salir las cifras del manual, y crecer con altitud y calor
print("\nDistancias de despegue y aterrizaje de la tableta")
for tid, d in DATA.items():
    wb = WeightBalance(tid)
    try:
        p = wb.performance(d["mtow_lb"], 0.0, 1013.25, 15.0, 0.0)
        hot = wb.performance(d["mtow_lb"], 5000.0, 1013.25, 30.0, 0.0)
    except Exception as ex:
        fallos.append(f"{tid}: la tableta no calcula las distancias ({ex.__class__.__name__}: {ex})")
        continue
    book = abs(p["to_roll"] - d["to_roll_ft"]) < 1 and abs(p["ldg_50"] - d["ldg_50_ft"]) < 1
    print(f"  {tid:6s} despegue {p['to_roll']:.0f}/{p['to_50']:.0f} ft, aterrizaje {p['ldg_roll']:.0f}/{p['ldg_50']:.0f} ft; "
          f"a 5000 ft y 30 °C despegue {hot['to_roll']:.0f} ft")
    if not book or hot["to_roll"] <= p["to_roll"]:
        fallos.append(f"{tid}: distancias de la tableta fuera del manual")

print("\nFALLOS: " + "; ".join(fallos) if fallos else "\nTODO OK")
sys.exit(1 if fallos else 0)
