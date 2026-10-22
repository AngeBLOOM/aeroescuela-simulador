"""Declinación magnética (13° oeste, como en Venezuela) en el escenario escuela: la brújula, el direccional, el VOR,
el piloto automático (HDG y NAV), el OBS al colocar el avión, el viento que da la torre y los rumbos que dictan las
lecciones son magnéticos; la física y la evaluación siguen en verdadero. Sin declinación, todo queda como antes."""
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim.geo import local_variation
from sim.lessons import LESSONS_BY_ID, mon_hdg, rnd10, rnd10m
from sim.mathx import FT, NM, wrap180
from sim.world import World

VAR = -13.0
fallos = []


def check(ok, msg):
    print(("  ok   " if ok else "  FALLO ") + msg)
    if not ok:
        fallos.append(msg)


def world(var=VAR):
    w = World("c172")
    w.set_magvar(var)
    return w


def fly(w, secs, ap=False):
    for _ in range(int(secs * 60)):
        if ap:
            cmd = w.apply_autopilot(1 / 60)
            if cmd is not None:
                w.ac.ctl_elev, w.ac.ctl_ail = cmd
        w.step(1 / 60)


print("Declinación del lugar (OurAirports)")
rows = [dict(latitude_deg="10.2", longitude_deg="-67.6", magnetic_variation_deg="-12.0"),
        dict(latitude_deg="10.6", longitude_deg="-66.9", magnetic_variation_deg="-14.0"),
        dict(latitude_deg="40.0", longitude_deg="-4.0", magnetic_variation_deg="1.0"),        # lejos: no cuenta
        dict(latitude_deg="10.3", longitude_deg="-67.7", magnetic_variation_deg="")]
v = local_variation(rows, 10.25, -67.65)
check(-14.0 < v < -12.0, f"media pesada de las radioayudas cercanas: {v:+.1f}° (oeste)")
check(local_variation([], 10.25, -67.65) == 0.0, "sin radioayudas: 0")

print("Conversiones")
w = world()
check(w.mag(90) == 103 and abs(w.true(103) - 90) < 1e-9 and w.mag(347) == 360, "090 verdadero = 103 magnético; 347 → 360")
check(rnd10m(w, 90) == w.true(100) and w.mag(rnd10m(w, 90)) == 100, "los objetivos se redondean en magnético")

print("Brújula y direccional")
w.reposition("crucero")
ac = w.ac
gh = w.terrain.surface_height(ac.pos[0], ac.pos[1])
ac.place_in_air(ac.pos[0], ac.pos[1], gh + 3000 * FT, 90, 100)
w.ind.reset(ac, w.kollsman)
fly(w, 20)
# con los mandos sueltos el rumbo deriva un poco: se compara con el magnético del rumbo que lleva el avión
mag_now = (ac.heading + 13.0) % 360
check(abs(wrap180(w.ind.dg - mag_now)) < 1.0,
      f"direccional {w.ind.dg:.1f}° con rumbo verdadero {ac.heading:.1f}° (magnético {mag_now:.1f}°)")
check(abs(wrap180(w.ind.compass - mag_now)) < 2.0, f"brújula: {w.ind.compass:.1f}°")
w.ind.dg_drift = 5.0
w.ind.dg_drift = 0.0                     # «alinear con la brújula» (panel)
fly(w, 1)
check(abs(wrap180(w.ind.dg - w.ind.compass)) < 2.0, "alinear el direccional lo deja igual que la brújula")

print("VOR")
vor = next(n for n in w.navaids if n.ident == "ESC")
w.nav1.freq = vor.freq
w.nav1.obs = 103
ac.place_in_air(vor.pos[0], vor.pos[1] + 10000, gh + 3000 * FT, 90, 100)
fly(w, 1)
check(abs(w.nav1.radial - 103) < 0.5 and w.nav1.to_from == "FROM" and abs(w.nav1.cdi) < 0.05,
      f"al este del VOR: radial {w.nav1.radial:.1f} (magnético), FROM, aguja centrada con OBS 103")

print("Piloto automático")
w = world()
w.reposition("crucero")
ac = w.ac
gh = w.terrain.surface_height(ac.pos[0], ac.pos[1])
ac.place_in_air(ac.pos[0], ac.pos[1], gh + 3000 * FT, 0, 100)
w.ap.engage(ac)
w.ap.set_alt(ac)
w.ap.lat = "HDG"
w.ap.hdg_bug = 103
fly(w, 90, ap=True)
check(abs(wrap180(ac.heading - 90)) < 3, f"HDG 103 (magnético) → rumbo verdadero {ac.heading:.1f}°")
vor = next(n for n in w.navaids if n.ident == "ESC")
w.nav1.freq, w.nav1.obs = vor.freq, 103
ac.place_in_air(vor.pos[0] + 900, vor.pos[1] + 4 * NM, gh + 3000 * FT, 100, 100)
w.ap.engage(ac)
w.ap.set_alt(ac)
w.ap.lat = "HDG"
w.ap.set_nav(ac)
fly(w, 150, ap=True)
check(w.ap.lat == "NAV" and abs(w.nav1.cdi) < 0.2 and abs(wrap180(ac.track - 90)) < 4,
      f"NAV en el radial 103: derrota verdadera {ac.track:.1f}°, aguja {w.nav1.cdi:+.2f}")

print("Al colocar el avión, la torre y las lecciones")
w = world()
w.reposition("final3")
ils = w.ils_for(w.active_rw, w.active_end)
check(w.nav1.obs == w.mag(ils.course) and w.ap.hdg_bug == w.mag(w.ac.heading),
      f"final 3 NM: OBS {w.nav1.obs} y marcador {w.ap.hdg_bug} en magnético (curso verdadero {ils.course:.0f})")
w.weather.wind_dir, w.weather.wind_kt, w.weather.gust_kt = 270.0, 10.0, 0.0
txt, _ = w.atc.wind()
check("280°" in txt, f"la torre da el viento magnético: «{txt}» (METAR 270 verdadero)")
m = mon_hdg(rnd10m(w, w.ac.heading), 10)
val, ok, tgt = m.fn(w)
check(ok and int(tgt[:3]) % 10 == 0 and abs(wrap180(val - w.mag(w.ac.heading))) < 0.6,
      f"monitor de rumbo: muestra {val:.0f} y pide «{tgt}»")
L = LESSONS_BY_ID["basico"]()
w2 = world()
L.setup(w2)
nums = [int(n) for s in L.steps for n in re.findall(r"rumbo (\d{3})", s.text)]
want = rnd10(w2.mag(w2.ac.heading))
check(nums and all(n % 10 == 0 for n in nums) and nums[0] == want,
      f"lección «{L.title}» dicta rumbos magnéticos redondos: {nums} (direccional {w2.ind.dg:.0f})")

print("Sin declinación (escenario escuela de siempre)")
w0 = World("c172")
w0.reposition("final3")
check(w0.magvar == 0 and w0.nav1.obs == round(ils.course) % 360 or w0.nav1.obs == 360, "OBS igual que antes")
check(abs(wrap180(w0.ind.dg - w0.ac.heading)) < 0.01 and w0.mag(90) == 90, "direccional = rumbo verdadero")

print("\nFALLOS: " + "; ".join(fallos) if fallos else "\nTODO OK")
sys.exit(1 if fallos else 0)
