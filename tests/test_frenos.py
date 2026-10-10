"""Frenos diferenciales: rodando despacio, frenar solo la rueda derecha gira el avión a la derecha (y la izquierda
a la izquierda); los dos frenos a la vez lo paran en línea recta."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim.world import World


def roll(aircraft, left, right, both=0.0, secs=4.0):
    w = World(aircraft)
    w.reposition("pista")
    ac = w.ac
    ac.sys.ready_to_fly()
    ac.sys.parking_brake = False
    for en in ac.sys.engines:
        en.throttle = 0.0
    h0 = ac.heading
    hr = math.radians(h0)
    ac.vel[0], ac.vel[1] = 6.0 * math.cos(hr), 6.0 * math.sin(hr)        # rodaje a ~12 kt
    for _ in range(int(secs * 60)):
        ac.ctl_rud = 0.0
        ac.brake, ac.brake_l, ac.brake_r = both, left, right
        w.step(1 / 60)
    turn = ((ac.heading - h0 + 180) % 360) - 180
    return turn, ac.gs


for aircraft in ("c172", "pa28w", "da42"):
    free, gs_free = roll(aircraft, 0.0, 0.0)
    right, _ = roll(aircraft, 0.0, 0.8)
    left, _ = roll(aircraft, 0.8, 0.0)
    straight, gs_stop = roll(aircraft, 0.0, 0.0, both=1.0)
    print(f"{aircraft}: libre {free:+.1f}°  freno der {right:+.1f}°  freno izq {left:+.1f}°  "
          f"ambos {straight:+.1f}° (gs {gs_stop:.1f} m/s, libre {gs_free:.1f})")
    assert right > free + 8, "frenar la rueda derecha debe girar a la derecha"
    assert left < free - 8, "frenar la rueda izquierda debe girar a la izquierda"
    assert abs(right - free + (left - free)) < 0.35 * abs(right - left), "giro simétrico a cada lado"
    assert abs(straight - free) < 2 and gs_stop < gs_free - 2, "los dos frenos: frena en línea recta"
print("TODO OK")
