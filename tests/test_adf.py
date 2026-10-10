"""ADF y NDB: marcación relativa correcta, alcance, sin corriente, sintonía en kHz, que el NAV no se engancha a un
NDB, un vuelo hacia el NDB siguiendo la aguja (paso por la vertical) y la lectura de filas reales de OurAirports."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim.geo import LocalProjection, navaid_from_row
from sim.mathx import FT, NM, clamp, wrap180
from sim.world import World

fallos = []


def check(ok, msg):
    print(("  ok   " if ok else "  FALLO ") + msg)
    if not ok:
        fallos.append(msg)


w = World("c172")
ndb = next(n for n in w.navaids if n.kind == "NDB" and n.ident == "ES")
check(w.adf.freq == 350.0, f"el ADF empieza en el NDB más cercano al aeródromo ({w.adf.freq:.0f} kHz)")


def put(north_m, east_m, hdg, agl_ft=2000):
    ac = w.ac
    x, y = ndb.pos[0] + north_m, ndb.pos[1] + east_m
    ac.place_in_air(x, y, w.terrain.surface_height(x, y) + agl_ft * FT, hdg, 100)
    w.step(1 / 60)
    return w.adf


print("Marcación relativa")
for (n, e, hdg, want, txt) in ((-5 * NM, 0, 0, 0, "al sur, rumbo norte: delante"),
                               (-5 * NM, 0, 90, 270, "al sur, rumbo este: a la izquierda"),
                               (0, 5 * NM, 0, 270, "al este, rumbo norte: a la izquierda"),
                               (0, -5 * NM, 0, 90, "al oeste, rumbo norte: a la derecha"),
                               (5 * NM, 0, 0, 180, "al norte, rumbo norte: detrás")):
    a = put(n, e, hdg)
    err = abs(wrap180(a.relative - want))
    check(a.valid and err < 1.5, f"{txt}: {a.relative:5.1f}° (esperado {want}°) {a.ident} {a.dist_nm:.1f} NM")

print("Alcance, corriente y sintonía")
a = put(-30 * NM, 0, 0)
check(not a.valid and a.relative == 90.0, "a 30 NM (alcance 25 NM): sin señal, la aguja en 90°")
put(-5 * NM, 0, 0)
w.ac.sys.avionics = False
w.step(1 / 60)
check(not w.adf.valid, "sin aviónica no hay señal")
w.ac.sys.avionics = True
w.adf.freq = 1750.0
w.adf.tune(1)
check(w.adf.freq == 190.0, "sintonía: de 1750 kHz pasa a 190 kHz")
w.adf.freq = 280.0
w.adf.swap()
check(w.adf.freq == w.adf.standby or w.adf.standby == 280.0, "intercambio activa/reserva")
w.adf.freq = 350.0
w.nav1.freq = 350.0
w.step(1 / 60)
check(w.nav1.station is None, "el receptor NAV no se engancha a un NDB")

print("Ir al NDB siguiendo la aguja")
a = put(-8 * NM, 2 * NM, 30)
ac = w.ac
closest, passed = 1e9, False
for i in range(60 * 60 * 6):
    rel = wrap180(a.relative)
    bank = clamp(rel * 1.2, -25, 25)
    ac.ctl_ail = clamp((bank - math.degrees(ac.roll)) * 0.05 - ac.omega[0] * 0.3, -1, 1)
    ac.ctl_elev = clamp((3 - math.degrees(ac.pitch)) * 0.08 - ac.omega[1] * 0.4, -1, 1)
    w.step(1 / 60)
    if a.valid:
        closest = min(closest, a.dist_nm)
        if closest < 0.5 and abs(wrap180(a.relative)) > 120:
            passed = True
            break
check(passed, f"paso por la vertical del NDB: se acercó a {closest:.2f} NM y la aguja giró hacia atrás")

print("Filas de OurAirports (navaids.csv)")
proj = LocalProjection(10.25, -67.65)
row = {"ident": "BSC", "name": "Base Sucre", "type": "NDB", "frequency_khz": "372", "latitude_deg": "10.30",
       "longitude_deg": "-67.60", "elevation_ft": "1500", "power": "MEDIUM"}
nv = navaid_from_row(row, proj, 10.25, -67.65)
check(nv is not None and nv.kind == "NDB" and nv.freq == 372 and abs(nv.range_m - 50 * 1852) < 1,
      "NDB de potencia media: 372 kHz, alcance 50 NM")
vor = navaid_from_row(dict(row, type="VOR-DME", frequency_khz="114300", power=""), proj, 10.25, -67.65)
check(vor is not None and vor.kind == "VOR" and vor.freq == 114.3, "VOR-DME: 114,30 MHz")
check(navaid_from_row(dict(row, frequency_khz="2500"), proj, 10.25, -67.65) is None, "NDB fuera de banda: se descarta")
check(navaid_from_row(dict(row, latitude_deg="12.0"), proj, 10.25, -67.65) is None, "lejos del escenario: se descarta")

print("\nFALLOS: " + "; ".join(fallos) if fallos else "\nTODO OK")
sys.exit(1 if fallos else 0)
