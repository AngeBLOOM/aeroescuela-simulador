"""Prueba de la cabina física con mandos USB simulados (sin ventana ni mandos reales): calibración de ejes,
sincronización de los interruptores al empezar el vuelo, conexión en caliente, que el joystick genérico no lea
un mando que ya está asignado en «Cabina física» y las teclas y perillas del G1000 (radios, transpondedor, piloto
automático, perillas HDG / CRS / BARO y GPS), también girando rápido (por eventos)."""
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

# ---------------------------------------------------------------- 3b'. la consola es solo del C172S
# con otro avión (aquí el DA42) no se lee nada de ella: ni volante, ni gases, ni frenos de pie, ni interruptores
other = World("da42")
other.reposition("plataforma")
so = other.ac.sys
so.ready_to_fly()
B["eje_gases"] = dict(dev=dev["Volante"], eje=2, inv=False)
yoke.axes[0], yoke.axes[2], yoke.axes[4] = 0.8, 1.0, 1.0     # volante a la derecha, gases a fondo, freno pisado
for en in so.engines:
    en.throttle = 0.2
bat = so.master
panel.btns[0] = 0 if bat else 1                               # el interruptor real de batería, al revés
hw.request_sync()
hw.update(0.016, other, app)
assert all(en.throttle == 0.2 for en in so.engines) and so.master == bat
assert hw.brake_l == hw.brake_r == hw.brake_cmd == 0.0
other.ap.engaged = False
ctl.update(0.016, other, None, 0)
assert abs(other.ac.ctl_ail) < 0.05, other.ac.ctl_ail          # ni la consola ni su volante como joystick genérico
assert not hw.applies_to("da42") and hw.applies_to("c172")
hw.update(0.016, world, app)                                  # con el C172S, la misma consola sí manda
assert s.engines[0].throttle == 1.0 and hw.brake_l == 1.0
B.pop("eje_gases")
yoke.axes[2], yoke.axes[4] = 0.0, -1.0
panel.btns[0] = 0
print("consola solo del C172S OK")

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

# consola física = volante (alabeo y cabeceo) asignado y enchufado: decide la cabina automática en pantalla
v = FakeJoy(30, "Volante B")
plugged[:] = [v]
hw5 = Hardware({})
assert not hw5.console_connected()                         # nada asignado: sin consola
g = next(iter(hw5.devices))
hw5.bindings["eje_alabeo"] = dict(dev=g, eje=0, inv=False)
assert not hw5.console_connected()                         # falta el cabeceo
hw5.bindings["eje_cabeceo"] = dict(dev=g, eje=1, inv=False)
assert hw5.console_connected()
plugged[:] = []
hw5.refresh()
assert not hw5.console_connected()                         # volante desenchufado
plugged[:] = [v]
hw5.refresh()
assert hw5.console_connected()                             # vuelto a enchufar
print("detección de consola OK")

# ---------------------------------------------------------------- 6. teclas y perillas del G1000
from app.consola_g1000 import KEYS as G1000_KEYS          # noqa: E402
from ui.glass import GlassCockpit                         # noqa: E402
from ui.ui import Fonts                                   # noqa: E402

g1 = FakeJoy(40, "Panel G1000", nbtn=len(G1000_KEYS))
plugged[:] = [g1]
hw6 = Hardware({})
gk = next(iter(hw6.devices))
for i, k in enumerate(G1000_KEYS):
    hw6.bindings[k] = dict(dev=gk, btn=i)
w6 = World("c172")
w6.reposition("plataforma")
w6.ac.sys.master = w6.ac.sys.avionics = True
app6 = FakeApp()
app6.panel = types.SimpleNamespace(starter_held=False, glass=GlassCockpit(Fonts()))
gl = app6.panel.glass
hw6.update(0.016, w6, app6)                    # primera lectura: todo suelto


def tap(key, n=1):
    """Pulsa y suelta n veces (por sondeo, como un botón normal)."""
    for _ in range(n):
        g1.btns[G1000_KEYS.index(key)] = 1
        hw6.update(0.016, w6, app6)
        g1.btns[G1000_KEYS.index(key)] = 0
        hw6.update(0.016, w6, app6)


# radios, una perilla por radio: se sintoniza la reserva y ⇄ la pasa a activa
w6.com_freq, w6.com_standby = 118.3, 121.9
tap("r_com1_mhz_mas")
tap("r_com1_khz_mas", 2)
assert abs(w6.com_standby - 122.95) < 1e-6, w6.com_standby
tap("r_com1_cambio")
assert abs(w6.com_freq - 122.95) < 1e-6 and abs(w6.com_standby - 118.3) < 1e-6
w6.nav1.standby = 110.30
tap("r_nav1_khz_menos")
assert abs(w6.nav1.standby - 110.25) < 1e-6, w6.nav1.standby
f2 = w6.nav2.freq
tap("r_nav2_cambio")
assert w6.nav2.standby == f2
w6.adf.standby = 280
tap("r_adf_mhz_mas")
tap("r_adf_khz_mas", 3)
assert w6.adf.standby == 383 and w6.show_adf, w6.adf.standby
# radios compartidas: el selector elige la radio y la perilla doble la sintoniza
tap("r_sel", 2)                                # COM 1 → NAV 1
assert w6.radio_sel == "nav1"
tap("r_grande_mas")
assert abs(w6.nav1.standby - 111.25) < 1e-6, w6.nav1.standby
tap("r_cambio")
assert abs(w6.nav1.freq - 111.25) < 1e-6
print("radios por radio y compartidas OK")

# transpondedor dígito a dígito, en octal, e IDENT
w6.xpdr = 1200
tap("x_digito")
tap("x_mas")                                   # 1 → 2
tap("x_digito")
tap("x_menos")                                 # 2 → 1
tap("x_digito", 2)
tap("x_menos")                                 # 0 → 7
assert w6.xpdr == 2107 and w6.xpdr_digit == 3, w6.xpdr
tap("x_ident")
assert w6.xpdr_ident_t == w6.sim_time
print("transpondedor OK")

# piloto automático y perillas
ap = w6.ap
tap("g_hdg")
assert ap.engaged and ap.lat == "HDG"
a0 = ap.alt_sel
tap("g_alt_1000_mas")
tap("g_alt_100_menos", 3)
assert ap.alt_sel == round(a0 / 100) * 100 + 700, ap.alt_sel
tap("g_ap")
assert not ap.engaged
tap("g_hdg_sync")
b0 = ap.hdg_bug
tap("g_hdg_mas", 5)
assert (ap.hdg_bug - b0) % 360 == 5, (b0, ap.hdg_bug)
w6.cdi_src = "VLOC"
o1, o2 = w6.nav1.obs, w6.nav2.obs
tap("g_crs_menos", 2)
tap("g_crs2_mas")
assert (o1 - w6.nav1.obs) % 360 == 2 and (w6.nav2.obs - o2) % 360 == 1
tap("g_baro_std")
tap("g_baro_mas")
assert w6.kollsman == 1014, w6.kollsman
print("piloto automático y perillas HDG / CRS / BARO OK")

# GPS con la perilla FMS: D→, deletrear «VN» y ENT
tap("g_direct")
assert gl.gps_page == "dto"
tap("g_fms_p_mas", 22)                         # A + 21: V
tap("g_fms_push")
tap("g_fms_p_mas", 14)                         # A + 13: N
assert gl.gps_query == "VN", gl.gps_query
tap("g_ent")
assert w6.gps.direct is not None and w6.gps.direct.ident == "VN" and gl.gps_page is None
tap("g_fpl")
assert gl.gps_page == "fpl"
tap("g_clr")
assert gl.gps_page is None
r0 = gl.map_range_nm
tap("g_rango_mas")
assert gl.map_range_nm > r0
tap("g_cdi")
assert w6.cdi_src == "GPS"
print("teclas del GPS OK")

# perilla girada rápido: varios pulsos entre dos lecturas llegan como eventos y no se pierde ninguno
b0 = ap.hdg_bug
i = G1000_KEYS.index("g_hdg_mas")
hw6.on_events([pygame.event.Event(pygame.JOYBUTTONDOWN, instance_id=40, button=i, joy=0)] * 7)
hw6.update(0.016, w6, app6)
assert (ap.hdg_bug - b0) % 360 == 7, (b0, ap.hdg_bug)
hw6.update(0.016, w6, app6)                    # ya contados: no se repiten
assert (ap.hdg_bug - b0) % 360 == 7
# solo en vuelo, con la aviónica encendida y en el C172S
for setup in ("pausa", "sin aviónica"):
    app6.state = "pause" if setup == "pausa" else "flight"
    w6.ac.sys.avionics = setup != "sin aviónica"
    b0 = ap.hdg_bug
    hw6.on_events([pygame.event.Event(pygame.JOYBUTTONDOWN, instance_id=40, button=i, joy=0)])
    hw6.update(0.016, w6, app6)
    assert ap.hdg_bug == b0, setup
app6.state, w6.ac.sys.avionics = "flight", True
da = World("da42")
da.ac.sys.master = da.ac.sys.avionics = True
b0 = da.ap.hdg_bug
hw6.on_events([pygame.event.Event(pygame.JOYBUTTONDOWN, instance_id=40, button=i, joy=0)])
hw6.update(0.016, da, app6)
assert da.ap.hdg_bug == b0
print("perillas por eventos (giro rápido) OK")
print("TODO OK")
