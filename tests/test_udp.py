"""Salida UDP: un receptor en esta misma computadora recibe los datagramas JSON a la frecuencia pedida, con los
valores del avión (posición, velocidad, rumbo, motores), los avisos (pérdida) y los dos motores del DA42."""
import json
import math
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.udp_out import UdpOut, snapshot
from sim.mathx import FT, clamp
from sim.world import World

fallos = []


def check(ok, msg):
    print(("  ok   " if ok else "  FALLO ") + msg)
    if not ok:
        fallos.append(msg)


class FakeApp:
    def __init__(self, aircraft="c172"):
        self.world = World(aircraft)
        self.state = "flight"


rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
rx.bind(("127.0.0.1", 0))
rx.settimeout(0.5)
port = rx.getsockname()[1]


def drain():
    got = []
    rx.settimeout(0.05)
    try:
        while True:
            got.append(json.loads(rx.recv(65535).decode("utf-8")))
    except socket.timeout:
        pass
    return got


print("Antes de volar (menú)")
app = FakeApp()
app.state = "menu"
d = snapshot(app)
check(d["v"] == 1 and d["ficticio"] is True and len(d["motores"]) == 1, "el estado se puede enviar sin haber volado")

print("En vuelo")
app.state = "flight"
w = app.world
w.reposition("final3")
ac = w.ac
gh = w.terrain.surface_height(ac.pos[0], ac.pos[1])
ac.place_in_air(ac.pos[0], ac.pos[1], gh + 3000 * FT, 90, 100)
out = UdpOut("127.0.0.1", port, 30)
got = []
for i in range(120):                         # 2 s a 60 fotogramas por segundo; el receptor lee cada 10
    w.step(1 / 60)
    out.update(1 / 60, app)
    if i % 10 == 9:
        got += drain()
got += drain()
check(59 <= out.sent <= 61 and len(got) == out.sent, f"30 Hz: {out.sent} enviados y {len(got)} recibidos en 2 s")
d = got[-1]
check(abs(d["ias_kt"] - w.ind.ias) < 1 and abs(d["alt_ind_ft"] - w.ind.alt_ft) < 2,
      f"velocidad y altitud: {d['ias_kt']:.0f} kt, {d['alt_ind_ft']:.0f} ft")
check(abs(d["rumbo"] - 90) < 2 and abs(d["nz"] - 1) < 0.15, f"rumbo {d['rumbo']:.1f}° y nz {d['nz']:.2f} g")
check(d["motores"][0]["rpm"] > 1500 and d["motores"][0]["en_marcha"], f"motor: {d['motores'][0]['rpm']:.0f} rpm")
check(-90 <= d["lat"] <= 90 and -180 <= d["lon"] <= 180 and not d["en_tierra"], "lat/lon válidas y en el aire")
size = len(json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode())
check(size < 1472, f"monomotor: cabe en un paquete Ethernet sin fragmentar ({size} bytes)")

print("Aviso de pérdida")
for en in ac.sys.engines:
    en.throttle = 0.0
seen = False
for _ in range(60 * 40):
    ac.ctl_elev = clamp(ac.ctl_elev + 0.01, -1, 0.9)
    w.step(1 / 60)
    out.update(1 / 60, app)
    if any(x["avisos"]["perdida"] for x in drain()):
        seen = True
        break
check(seen, "el aviso de pérdida llega por UDP al tirar con el motor a ralentí")

print("Bimotor")
app2 = FakeApp("da42")
out2 = UdpOut("127.0.0.1", port, 10)
out2.update(0.2, app2)
d2 = drain()[-1]
check(len(d2["motores"]) == 2, "DA42: dos motores")
out.stop()
out2.stop()

print("Difusión a la red local")
try:
    b = UdpOut("255.255.255.255", port, 5)
    b.stop()
    check(True, "se puede abrir un destino de difusión (.255)")
except OSError as ex:
    check(False, f"difusión: {ex}")

print("\nFALLOS: " + "; ".join(fallos) if fallos else "\nTODO OK")
sys.exit(1 if fallos else 0)
