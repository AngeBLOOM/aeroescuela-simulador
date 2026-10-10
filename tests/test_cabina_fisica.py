"""Prueba de la cabina física con mandos USB simulados (sin ventana ni mandos reales): calibración de ejes,
sincronización de los interruptores al empezar el vuelo, conexión en caliente y que el joystick genérico no lea
un mando que ya está asignado en «Cabina física»."""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pygame

import app.hardware as hardware
from app.controls import Controls
from app.hardware import Hardware
from sim.world import World


class FakeJoy:
    def __init__(self, iid, name, naxes=6, nbtn=16, serial=None):
        self.iid, self.name, self.serial = iid, name, serial
        self.axes = [0.0] * naxes
        self.btns = [0] * nbtn
        self.hats = [(0, 0)]

    def init(self): pass
    def get_guid(self): return f"guid-{self.name}"
    def get_name(self): return self.name
    def get_instance_id(self): return self.iid
    def get_numaxes(self): return len(self.axes)
    def get_numbuttons(self): return len(self.btns)
    def get_numhats(self): return len(self.hats)
    def get_axis(self, i): return self.axes[i]
    def get_button(self, i): return self.btns[i]
    def get_hat(self, i): return self.hats[i]


plugged = []
pygame.joystick.init = lambda: None
pygame.joystick.get_count = lambda: len(plugged)
pygame.joystick.Joystick = lambda i: plugged[i]
hardware.unit_id = lambda j: j.serial


class FakeApp:
    def __init__(self):
        self.flashes = []
        self.panel = types.SimpleNamespace(starter_held=False)
        self.show_radio = False
        self.state = "flight"

    def flash(self, txt, secs=2.0):
        self.flashes.append(txt)


yoke = FakeJoy(10, "Volante")
panel = FakeJoy(11, "Panel interruptores")
plugged[:] = [yoke, panel]
hw = Hardware({})
dev = {j.name: g for g, j in hw.devices.items()}
B = hw.bindings
B["eje_alabeo"] = dict(dev=dev["Volante"], eje=0, inv=False)
B["eje_gases"] = dict(dev=dev["Volante"], eje=2, inv=False)
B["sw_bat"] = dict(dev=dev["Panel interruptores"], btn=0)
B["sw_tren"] = dict(dev=dev["Panel interruptores"], btn=1)
B["mag_off"] = dict(dev=dev["Panel interruptores"], btn=2)
B["mag_ambos"] = dict(dev=dev["Panel interruptores"], btn=3)

# ---------------------------------------------------------------- 1. calibración
hw.start_calibration()
for roll, thr in ((-0.6, -0.9), (0.8, 0.7), (0.1, 0.0)):     # tope a tope y se suelta el volante en 0.1
    yoke.axes[0], yoke.axes[2] = roll, thr
    hw.poll_calibration()
assert hw.finish_calibration() == 2
assert B["eje_alabeo"]["cal"]["cen"] == 0.1
for raw, want in ((-0.6, -1.0), (0.8, 1.0), (0.1, 0.0), (0.45, 0.5)):
    yoke.axes[0] = raw
    assert abs(hw.axis("eje_alabeo") - want) < 1e-6, (raw, hw.axis("eje_alabeo"))
for raw, want in ((-0.9, -1.0), (0.7, 1.0)):
    yoke.axes[2] = raw
    assert abs(hw.axis("eje_gases", 0.0) - want) < 1e-6
hw.start_calibration()                       # un eje que no se mueve conserva la calibración anterior
hw.poll_calibration()
assert hw.finish_calibration() == 0 and "cal" in B["eje_alabeo"]
assert "cal." in hw.describe("eje_alabeo")
print("calibración OK")

# ---------------------------------------------------------------- 2. sincronización al empezar el vuelo
world = World("c172")
world.reposition("plataforma")
s = world.ac.sys
app = FakeApp()

# avión frío en tierra: se copian los interruptores reales, salvo subir el tren
s.cold_and_dark()
panel.btns[0], panel.btns[1], panel.btns[3] = 1, 0, 1        # batería ON, tren ARRIBA, magnetos AMBOS
hw.request_sync()
hw.update(0.016, world, app)
assert s.master is True and s.engines[0].magnetos == 3
assert s.gear_down is True and hw.mismatch == {"sw_tren"}, hw.mismatch
panel.btns[1] = 1                                            # se baja la palanca del tren: ya coincide
hw.update(0.016, world, app)
assert not hw.mismatch

# lección con el avión preparado: no se cambia nada, solo se avisa
s.ready_to_fly()
panel.btns[0] = 0                                            # batería real en OFF
app.flashes.clear()
hw.request_sync()
hw.update(0.016, world, app)
assert s.master is True and hw.mismatch == {"sw_bat"}
assert app.flashes and "BATERÍA" in app.flashes[-1]
panel.btns[0] = 1                                            # al mover el interruptor toma el mando
hw.update(0.016, world, app)
assert s.master is True and not hw.mismatch
panel.btns[0] = 0
hw.update(0.016, world, app)
assert s.master is False
print("sincronización de interruptores OK")

# ---------------------------------------------------------------- 3. joystick genérico y cabina física
ctl = Controls({})
ctl.hw = hw
assert ctl.joy is yoke and hw.uses_device(yoke)
s.ready_to_fly()
for en in s.engines:
    en.throttle = 0.3
B.pop("eje_gases")                           # gases sin asignar en la cabina: el eje 2 genérico no debe moverlos
yoke.axes[2] = 1.0
yoke.btns[4] = 1                             # botón 4 del volante = «flaps arriba» del joystick genérico
flaps = s.flaps_cmd = 1
ctl.update(0.016, world, None, 0)
assert ctl.joy_shared and s.engines[0].throttle == 0.3 and s.flaps_cmd == flaps
print("sin choque con el joystick genérico OK")

# ---------------------------------------------------------------- 3b. frenos de pie: cada uno en su rueda
B["eje_freno_izq"] = dict(dev=dev["Volante"], eje=4, inv=False)
yoke.axes[4] = 1.0                           # solo el pedal izquierdo asignado y pisado a fondo: frena las dos
hw.update(0.016, world, app)
assert hw.brake_l == hw.brake_r == 1.0
B["eje_freno_der"] = dict(dev=dev["Volante"], eje=5, inv=False)
yoke.axes[5] = -1.0                          # con los dos asignados, cada uno en su lado
hw.update(0.016, world, app)
assert hw.brake_l == 1.0 and hw.brake_r == 0.0 and hw.brake_cmd == 0.0
plugged.remove(yoke)                         # se desconecta pisando el freno: no queda frenado
hw.refresh()
hw.update(0.016, world, app)
assert hw.brake_l == hw.brake_r == 0.0
plugged.insert(0, yoke)
hw.refresh()
print("frenos de pie OK")

# ---------------------------------------------------------------- 3c. sensibilidad por eje y setas
from app.hardware import shape

yoke.axes[0] = 0.45                          # con la calibración de arriba = +0,50
assert abs(hw.axis("eje_alabeo", 0.0) - 0.5) < 1e-6
assert abs(hw.shaped("eje_alabeo") - shape(0.5)) < 1e-9 and 0.33 < shape(0.5) < 0.37     # por defecto: 4 %, 35 %
B["eje_alabeo"].update(zm=0.10, exp=0.0)
assert abs(hw.shaped("eje_alabeo") - 0.4 / 0.9) < 1e-6, hw.shaped("eje_alabeo")            # lineal, sin salto
yoke.axes[0] = 0.135                         # = +0,05: dentro de la zona muerta del 10 %
assert hw.shaped("eje_alabeo") == 0.0
yoke.axes[0] = 0.8
assert abs(hw.shaped("eje_alabeo") - 1.0) < 1e-9                                           # a fondo sigue siendo 1
B["eje_alabeo"]["exp"] = 1.0
yoke.axes[0] = 0.45
assert abs(hw.shaped("eje_alabeo") - (0.4 / 0.9) ** 3) < 1e-6                              # cúbica
s.ready_to_fly()
world.ap.engaged = False
ctl.update(0.016, world, None, 0)
assert abs(world.ac.ctl_ail - hw.shaped("eje_alabeo")) < 1e-6, "el avión recibe el eje ya con su curva (sin otra encima)"
B["eje_alabeo"].pop("zm"); B["eje_alabeo"].pop("exp")

hw.start_capture("btn_trim_arriba")
yoke.hats[0] = (0, 1)                        # seta del volante hacia arriba
hw.update(0.016, world, app)
assert B["btn_trim_arriba"] == dict(dev=dev["Volante"], hat=0, dir="arriba"), B.get("btn_trim_arriba")
assert "seta 0 ↑" in hw.describe("btn_trim_arriba")
yoke.hats[0] = (0, 0)
hw.update(0.016, world, app)
t0 = world.ac.trim
yoke.hats[0] = (1, 1)                        # en diagonal también cuenta como arriba
hw.update(1.0, world, app)
assert world.ac.trim > t0 + 0.2, (t0, world.ac.trim)
yoke.hats[0] = (0, -1)
assert hw.button("btn_trim_arriba")[0] is False
yoke.hats[0] = (0, 0)
print("sensibilidad por eje y setas OK")

# ---------------------------------------------------------------- 4. conexión en caliente
pedals = FakeJoy(12, "Pedales")
plugged.append(pedals)
hw.sync_pending = False
added, removed = hw.refresh()
assert added == ["Pedales"] and not removed and hw.sync_pending
plugged.remove(pedals)
added, removed = hw.refresh()
assert removed == ["Pedales"] and not added
assert hw.refresh() == ([], [])
print("conexión en caliente OK")

# ---------------------------------------------------------------- 5. dos mandos iguales (mismo modelo)
q1 = FakeJoy(20, "Cuadrante", serial="serie:A")
q2 = FakeJoy(21, "Cuadrante", serial="serie:B")
q1.axes[0], q2.axes[0] = 0.5, -0.5
plugged[:] = [q1, q2]
hw2 = Hardware({})
key = {j.serial: g for g, j in hw2.devices.items()}
hw2.bindings["eje_gases"] = dict(dev=key["serie:A"], eje=0, inv=False)
hw2.bindings["eje_gases2"] = dict(dev=key["serie:B"], eje=0, inv=False)
assert sorted(n for _, n, _, _ in hw2.device_list()) == ["Cuadrante (1)", "Cuadrante (2)"]
plugged[:] = [q2, q1]                        # Windows los enumera al revés (otro puerto, otro arranque)
hw2.refresh()
assert hw2.axis("eje_gases", 0.0) == 0.5 and hw2.axis("eje_gases2", 0.0) == -0.5
hw3 = Hardware(hw2.cfg)                      # al abrir el programa otra vez, con config.json guardado
assert hw3.axis("eje_gases", 0.0) == 0.5 and hw3.axis("eje_gases2", 0.0) == -0.5

# sin número de serie ni ruta: se sigue el orden y se corrige con «Intercambiar iguales»
q1.serial = q2.serial = None
plugged[:] = [q1, q2]
hw4 = Hardware({})
hw4.bindings["eje_gases"] = dict(dev=next(g for g, j in hw4.devices.items() if j is q1), eje=0, inv=False,
                                 cal=dict(min=-1.0, max=1.0))
plugged[:] = [q2, q1]
hw4.refresh()
assert hw4.axis("eje_gases", 0.0) == -0.5    # cruzados
assert hw4.swap_twins() == ["Cuadrante"]
assert hw4.axis("eje_gases", 0.0) == 0.5 and "cal" not in hw4.bindings["eje_gases"]

# el mismo número de serie en las dos unidades (placas baratas) no se usa para distinguirlas
q1.serial = q2.serial = "serie:X"
hw4.refresh()
assert "serie:X" not in hw4.cfg["unidades"].values()
plugged[:] = [pedals]
assert not Hardware({}).twin_groups()
print("mandos iguales OK")
print("TODO OK")
