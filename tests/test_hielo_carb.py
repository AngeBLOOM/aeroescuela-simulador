"""Hielo en el carburador: se forma con aire húmedo entre -15 y 32 °C (más con el gas reducido), baja las rpm y puede
parar el motor; la calefacción lo funde (el motor va peor unos segundos) y cuesta algo de potencia. No pasa con aire
seco, con calor ni en motores de inyección. El METAR real da el punto de rocío."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim.atmosphere import Weather
from sim.metar import apply
from sim.mathx import FT
from sim.world import World

fallos = []


def check(ok, msg):
    print(("  ok   " if ok else "  FALLO ") + msg)
    if not ok:
        fallos.append(msg)


def cruise(aircraft, spread, oat_c, thr=None, agl_ft=2500):
    w = World(aircraft)
    w.weather.dew_spread = spread
    w.weather.temp_offset = oat_c - 15.0          # a nivel del mar (más arriba hace algo más de frío)
    w.reposition("crucero")
    ac = w.ac
    gh = w.terrain.surface_height(ac.pos[0], ac.pos[1])
    ac.place_in_air(ac.pos[0], ac.pos[1], gh + agl_ft * FT, 0, 90)
    if thr is not None:
        for en in ac.sys.engines:
            en.throttle = thr
    w.step(1 / 60)
    return w


def fly(w, secs, thr=None, pitch=0.03):
    """Alas niveladas y cabeceo fijo (rad); pitch negativo = planeo con el morro abajo."""
    ac = w.ac
    for _ in range(int(secs * 60)):
        ac.ctl_ail = -ac.roll * 2.0 - ac.omega[0] * 0.3
        ac.ctl_elev = max(-1.0, min(1.0, (pitch - ac.pitch) * 3.0 - ac.omega[1] * 0.4))
        if thr is not None:
            for en in ac.sys.engines:
                en.throttle = thr
        w.step(1 / 60)


print("Formación de hielo (C152, crucero)")
w = cruise("c152", 1.0, 12.0)
e = w.ac.sys.engine
fly(w, 6)                                    # motor estabilizado
rpm0 = e.rpm
fly(w, 300)
check(e.carb_ice > 0.5 and e.rpm < rpm0 - 200, f"aire húmedo (rocío a 1 °C), 12 °C: hielo {e.carb_ice:.2f}, rpm {rpm0:.0f} → {e.rpm:.0f} en 5 min")
check(e.rough > 0, "el motor va irregular")
w2 = cruise("c152", 1.0, 12.0, thr=0.15)
fly(w2, 120, thr=0.15)
w3 = cruise("c152", 1.0, 12.0, thr=0.9)
fly(w3, 120, thr=0.9)
check(w2.ac.sys.engine.carb_ice > 1.8 * w3.ac.sys.engine.carb_ice,
      f"con el gas reducido se forma antes: {w2.ac.sys.engine.carb_ice:.2f} (ralentí) frente a {w3.ac.sys.engine.carb_ice:.2f} (90 %)")

print("Calefacción al carburador")
rough_before = e.rough
w.ac.sys.carb_heat = True
fly(w, 3)
check(e.rough >= rough_before - 0.05, f"al aplicarla el motor empeora unos segundos (irregular {e.rough:.2f})")
fly(w, 40)
check(e.carb_ice < 0.01, f"en 40 s el hielo se ha fundido ({e.carb_ice:.2f})")
rpm_heat = e.rpm
w.ac.sys.carb_heat = False
fly(w, 8)
check(e.rpm > rpm_heat + 40, f"la calefacción cuesta potencia: {rpm_heat:.0f} rpm con ella, {e.rpm:.0f} sin ella")

print("Parada del motor por hielo y rearranque")
w = cruise("c152", 0.5, 20.0, thr=0.2, agl_ft=7000)
e = w.ac.sys.engine
for _ in range(60):                          # hasta 10 min a poco gas, descendiendo despacio
    fly(w, 10, thr=0.2, pitch=-0.02)
    if not e.running:
        break
check(not e.running and e.carb_ice >= 0.95 and not w.ac.crashed,
      f"con 10 min a poco gas el motor se para (hielo {e.carb_ice:.2f}, {w.ac.agl / FT:.0f} ft sobre el terreno)")
w.ac.sys.carb_heat = True
for _ in range(6):                           # planeo (morro abajo) con calefacción: el molinete funde el hielo y arranca
    fly(w, 20, thr=0.6, pitch=-0.08)
    if e.running:
        break
check(e.running, f"con calefacción en planeo el hielo se funde y el motor vuelve a arrancar ({e.rpm:.0f} rpm)")

print("Sin hielo")
for aircraft, spread, oat, txt in (("c152", 20.0, 15.0, "aire seco (rocío a 20 °C)"),
                                   ("c152", 1.0, 42.0, "calor (42 °C)"),
                                   ("c172", 0.5, 10.0, "C172S de inyección con aire saturado"),
                                   ("da40", 0.5, 10.0, "DA40 de inyección")):
    w = cruise(aircraft, spread, oat, thr=0.3)
    fly(w, 300, thr=0.3)
    ice = max(en.carb_ice for en in w.ac.sys.engines)
    check(ice < 0.02, f"{txt}: hielo {ice:.2f} en 5 min")

print("Meteorología")
wx = Weather()
apply(wx, {"temp": 20, "dewp": 18, "wdir": 90, "wspd": 5, "altim": 1015})
check(wx.dew_spread == 2.0 and " 20/18 " in wx.describe(), f"METAR con rocío: diferencia {wx.dew_spread:.0f} °C · «{wx.describe()}»")
w = World("c152")
w.reposition("crucero")
w.atmo.rain_here = 0.6
check(w.atmo.moisture_spread() <= 1.0, "con lluvia el aire está casi saturado")

print("\nFALLOS: " + "; ".join(fallos) if fallos else "\nTODO OK")
sys.exit(1 if fallos else 0)
