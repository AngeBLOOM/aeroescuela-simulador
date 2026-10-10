"""Herramientas del instructor: congelar altitud, posición y combustible; acelerar el tiempo (y que vuelva a ×1
cerca del suelo); mover el avión en vuelo; y las mismas órdenes desde el puesto web (sin ventana)."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim.mathx import FT, NM
from sim.world import World

fallos = []


def check(ok, msg):
    print(("  ok   " if ok else "  FALLO ") + msg)
    if not ok:
        fallos.append(msg)


def airborne(agl_ft=3000, ias=100):
    """C172 en vuelo a agl_ft sobre el terreno que tiene debajo, rumbo norte."""
    w = World("c172")
    w.reposition("final3")
    ac = w.ac
    gh = w.terrain.surface_height(ac.pos[0], ac.pos[1])
    ac.place_in_air(ac.pos[0], ac.pos[1], gh + agl_ft * FT, 360, ias)
    w.step(1 / 60)
    return w, ac


def fly(w, secs, idle=False):
    for _ in range(int(secs * 60)):
        if idle:
            for en in w.ac.sys.engines:
                en.throttle = 0.0
        w.step(1 / 60)


print("Congelar")
w, ac = airborne()
z0 = ac.alt_msl
w.freeze("alt", True)
fly(w, 30, idle=True)
check(abs(ac.alt_msl - z0) < 0.5 * FT, f"altitud congelada con el motor a ralentí: {(ac.alt_msl - z0) / FT:+.1f} ft en 30 s")
w.freeze("alt", False)
fly(w, 20, idle=True)
check(ac.alt_msl < z0 - 200 * FT, f"al descongelar vuelve a bajar: {(ac.alt_msl - z0) / FT:+.0f} ft en 20 s")

w, ac = airborne()
x0, y0 = ac.pos[0], ac.pos[1]
w.freeze("pos", True)
fly(w, 30)
check(math.hypot(ac.pos[0] - x0, ac.pos[1] - y0) < 0.5, "posición congelada 30 s: el avión no avanza sobre el terreno")
check(85 < w.ind.ias < 115, f"y sigue volando: {w.ind.ias:.0f} kt")

w, ac = airborne()
f0 = ac.sys.fuel_l
w.freeze("fuel", True)
fly(w, 60)
check(ac.sys.fuel_l == f0, f"combustible congelado 60 s: {ac.sys.fuel_l - f0:+.3f} L")

print("Ritmo del tiempo")
w, ac = airborne()
t0, x0 = w.sim_time, ac.pos[0]
check(w.set_rate(4), "×4 en vuelo a 3000 ft")
fly(w, 10)
check(abs((w.sim_time - t0) - 40) < 1.0, f"10 s reales a ×4 = {w.sim_time - t0:.1f} s simulados")
check((ac.pos[0] - x0) > 3.5 * 10 * 50, f"recorre {(ac.pos[0] - x0) / NM:.2f} NM en 10 s reales")
w2 = World("c172")
w2.reposition("pista")
check(not w2.set_rate(4) and w2.sim_rate == 1, "en tierra no se acelera")
w, ac = airborne(agl_ft=800)
check(w.set_rate(2), f"×2 a {ac.agl / FT:.0f} ft sobre el terreno")
for _ in range(60 * 60):
    for en in ac.sys.engines:
        en.throttle = 0.0
    w.step(1 / 60)
    if w.sim_rate == 1:
        break
evs = [e for e, _ in w.events]
check(w.sim_rate == 1 and "ritmo_normal" in evs and ac.agl < 500 * FT + 30,
      f"bajando, vuelve a ×1 cerca de 500 ft sobre el terreno ({ac.agl / FT:.0f} ft)")

print("Mover el avión")
w, ac = airborne()
x0, z0, h0 = ac.pos[0], ac.alt_msl, ac.heading
trk0 = math.degrees(math.atan2(ac.vel[1], ac.vel[0]))
check(w.slew(north_nm=1), "mover en vuelo")
check(abs(ac.pos[0] - x0 - NM) < 1, f"1 NM al norte: {(ac.pos[0] - x0) / NM:.3f} NM")
w.slew(alt_ft=500)
check(abs(ac.alt_msl - z0 - 500 * FT) < 1, f"+500 ft: {(ac.alt_msl - z0) / FT:+.0f} ft")
w.slew(hdg_deg=30)
w.step(1 / 60)
trk = math.degrees(math.atan2(ac.vel[1], ac.vel[0]))
check(abs(((ac.heading - h0 + 180) % 360) - 180 - 30) < 0.5, f"rumbo +30°: {ac.heading:.1f}° (antes {h0:.1f}°)")
check(abs(((trk - trk0 + 180) % 360) - 180 - 30) < 1.0, "la velocidad gira con el rumbo (no derrapa)")
w.freeze("alt", True)
w.slew(alt_ft=-1000)
fly(w, 5)
check(abs(ac.alt_msl - (z0 + 500 * FT - 1000 * FT)) < 2, "con la altitud congelada, mover la deja en la nueva altitud")
w.slew(alt_ft=-20000)
check(ac.agl > 290 * FT, f"nunca por debajo de 300 ft sobre el terreno ({ac.agl / FT:.0f} ft)")
w2 = World("c172")
w2.reposition("pista")
check(not w2.slew(north_nm=1), "en tierra no se mueve")
w.reposition("final3")
check(not w.frozen and w.sim_rate == 1, "reposicionar quita lo congelado y el ritmo")

print("Puesto web del instructor")
from app.core import App


class FakeApp:
    def __init__(self):
        self.world, self.ac = airborne()
        self.state = "flight"
        self.flashes = []

    def flash(self, txt, secs=2.0):
        self.flashes.append(txt)


fa = FakeApp()
App._remote_cmd(fa, {"c": "congelar", "k": "alt", "on": True})
App._remote_cmd(fa, {"c": "ritmo", "x": 2})
App._remote_cmd(fa, {"c": "mover", "n": 2, "hdg": 90})
App._remote_cmd(fa, {"c": "mover", "n": "x", "alt": float("nan")})          # valores inválidos: no hace nada
check("alt" in fa.world.frozen and fa.world.sim_rate == 2, "órdenes web: congelar altitud y ×2")
check(abs(fa.world.ac.heading - 90) < 1, f"orden web: rumbo +90° ({fa.world.ac.heading:.0f}°)")
w3 = World("c172")
w3.reposition("pista")
fa.world = w3
App._remote_cmd(fa, {"c": "ritmo", "x": 4})
check(w3.sim_rate == 1 and fa.flashes, "orden web: ×4 en tierra se rechaza con aviso")

print("\nFALLOS: " + "; ".join(fallos) if fallos else "\nTODO OK")
sys.exit(1 if fallos else 0)
