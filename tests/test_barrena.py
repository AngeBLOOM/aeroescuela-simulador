"""Barrena y turbulencia de giro (C172):
- con pérdida, palanca atrás y pedal a fondo el avión entra en barrena (3-4 s por vuelta, morro muy abajo);
- con PARE (ralentí, alerones neutros, pedal contrario, palanca adelante) sale en menos de 1,5 vueltas y se recupera
  del picado sin pasar de VNE ni de 3,8 G;
- una pérdida coordinada (pedal neutro) no entra en barrena;
- la turbulencia fuerte hace girar el avión (alabeo, cabeceo y guiñada) y sin turbulencia no hay giros."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim.mathx import FT, clamp, wrap180
from sim.world import World

fallos = []


def check(ok, msg):
    print(("  ok   " if ok else "  FALLO ") + msg)
    if not ok:
        fallos.append(msg)


def high(aircraft="c172", agl_ft=6000, turb=0.0):
    w = World(aircraft)
    w.weather.turbulence = turb
    w.weather.wind_kt = 0.0
    w.reposition("crucero")
    ac = w.ac
    gh = w.terrain.surface_height(ac.pos[0], ac.pos[1])
    ac.place_in_air(ac.pos[0], ac.pos[1], gh + agl_ft * FT, 0, 80)
    w.step(1 / 60)
    return w, ac


def stall_entry(w, ac, rudder):
    """Ralentí, palanca atrás poco a poco hasta la pérdida y pedal a la vez."""
    for en in ac.sys.engines:
        en.throttle = 0.0
    for i in range(60 * 25):
        ac.ctl_elev = clamp(ac.ctl_elev + 0.6 / 60, -1, 1)
        ac.ctl_ail = 0.0
        if ac.stall_frac > 0.4:
            ac.ctl_rud = rudder
        w.step(1 / 60)
        if ac.spin > 0.8:
            return i / 60
    return None


print("Entrada en barrena")
w, ac = high()
t_in = stall_entry(w, ac, -1.0)
check(t_in is not None and ac.spin_dir < 0, f"pérdida + pedal izquierdo a fondo: barrena a la izquierda a los {t_in or 0:.0f} s")
h0, turned, alt0 = ac.heading, 0.0, ac.alt_msl
prev = ac.heading
for i in range(60 * 8):                      # barrena mantenida 8 s: palanca atrás, pedal a fondo
    ac.ctl_elev, ac.ctl_rud, ac.ctl_ail = 1.0, -1.0, 0.0
    w.step(1 / 60)
    turned += wrap180(ac.heading - prev)
    prev = ac.heading
per_turn = 8.0 / max(abs(turned) / 360.0, 1e-3)
check(2.0 < per_turn < 5.0, f"rota {abs(turned):.0f}° en 8 s: {per_turn:.1f} s por vuelta")
check(math.degrees(ac.pitch) < -20 and -9000 < ac.vs_fpm < -3500, f"morro {math.degrees(ac.pitch):.0f}°, {ac.vs_fpm:.0f} ft/min")
check(w.ind.ias < 75, f"velocidad baja y estable en la barrena: {w.ind.ias:.0f} kt (no es un picado en espiral)")

print("Recuperación PARE")
turned, prev, t_out, turns_out = 0.0, ac.heading, None, 9.0
for i in range(60 * 12):
    ac.ctl_ail = 0.0
    stopped = ac.spin == 0 and abs(ac.omega[2]) < 0.3
    ac.ctl_rud = 0.0 if stopped else 1.0                      # pedal contrario hasta que pare la rotación
    ac.ctl_elev = ac.ctl_elev if stopped else -0.3            # palanca adelante
    w.step(1 / 60)
    turned += wrap180(ac.heading - prev)
    prev = ac.heading
    if stopped:
        t_out, turns_out = i / 60, abs(turned) / 360
        break
check(t_out is not None and 0.1 < turns_out < 1.5,
      f"la rotación se para en {t_out or 0:.1f} s ({turns_out:.2f} vueltas; el manual de Cessna: 1/4 a 1/2)")
max_g, max_ias = 1.0, 0.0
ac.ctl_elev = 0.1
for i in range(60 * 20):                     # salida del picado en cuanto para: alas niveladas y tirar hacia 2,8 G
    ac.ctl_rud = clamp(ac.beta * 3.0, -1, 1)
    ac.ctl_ail = clamp(-math.degrees(ac.roll) * 0.05 - ac.omega[0] * 0.3, -1, 1)
    ac.ctl_elev = clamp(ac.ctl_elev + (2.8 - ac.nz) * 0.6 / 60, -0.4, 0.8)
    w.step(1 / 60)
    max_g, max_ias = max(max_g, ac.nz), max(max_ias, w.ind.ias)
    if ac.vs_fpm > 0:
        break
check(not ac.crashed and max_g < 3.8 and max_ias < ac.t.v["vne"],
      f"sale del picado: {max_g:.1f} G, {max_ias:.0f} kt (VNE {ac.t.v['vne']}), perdió {(alt0 - ac.alt_msl) / FT:.0f} ft")

print("Pérdida coordinada")
w, ac = high()
for en in ac.sys.engines:
    en.throttle = 0.0
max_spin = 0.0
for i in range(60 * 20):                     # pérdida con la palanca atrás, alas niveladas y pedal coordinado
    ac.ctl_elev = clamp(ac.ctl_elev + 0.6 / 60, -1, 1)
    ac.ctl_rud = clamp(ac.beta * 3.0 - ac.omega[2] * 0.5, -1, 1)
    ac.ctl_ail = clamp(-math.degrees(ac.roll) * 0.03, -1, 1)
    w.step(1 / 60)
    max_spin = max(max_spin, ac.spin)
check(max_spin == 0.0, f"pérdida coordinada 20 s con la palanca atrás: no entra en barrena (máx {max_spin:.2f})")

print("Turbulencia de giro")
res = {}
for turb in (0.0, 0.9):
    w, ac = high(agl_ft=3000, turb=turb)
    rates = []
    for i in range(60 * 40):                 # piloto automático de alas niveladas suave (como un alumno)
        ac.ctl_ail = clamp(-math.degrees(ac.roll) * 0.03, -1, 1)
        ac.ctl_elev = clamp((0.05 - ac.pitch) * 2.0, -1, 1)
        w.step(1 / 60)
        if i > 60 * 5:
            rates.append(ac.omega.copy())
    rms = [math.sqrt(sum(r[k] ** 2 for r in rates) / len(rates)) for k in range(3)]
    res[turb] = rms
    print(f"     turbulencia {turb:.1f}: giro RMS alabeo {math.degrees(rms[0]):.2f}°/s, cabeceo {math.degrees(rms[1]):.2f}°/s, "
          f"guiñada {math.degrees(rms[2]):.2f}°/s")
check(all(math.degrees(v) < 0.3 for v in res[0.0]), "sin turbulencia: sin giros")
check(math.degrees(res[0.9][0]) > 1.0 and math.degrees(res[0.9][2]) > 0.3, "turbulencia fuerte: el avión alabea y guiña")
check(not w.ac.crashed and math.degrees(res[0.9][0]) < 15, "pero sigue siendo controlable")

print("\nFALLOS: " + "; ".join(fallos) if fallos else "\nTODO OK")
sys.exit(1 if fallos else 0)
