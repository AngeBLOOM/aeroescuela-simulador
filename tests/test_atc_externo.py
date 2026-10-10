"""Prueba del enlace con un simulador de ATC externo (sin ventana): un cliente TCP hace de consola
de controlador, saluda, toma la torre, publica un tráfico, manda una autorización y recibe el estado
del avión y la transmisión del piloto."""
import json
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.atc_link import AtcBridge
from sim.world import World

PORT = 8797


class FakeApp:
    def __init__(self):
        self.world = World("c172")
        self.world.reposition("plataforma")
        self.settings = dict(trafico=True)
        self.lesson = None
        self.flashes = []

    def flash(self, txt, secs=2.0):
        self.flashes.append(txt)


app = FakeApp()
bridge = AtcBridge(app, PORT)
assert bridge.error is None, bridge.error

cli = socket.create_connection(("127.0.0.1", PORT), timeout=3)
buf = b""


def send(o):
    cli.sendall((json.dumps(o) + "\n").encode())


def pump(secs):
    """Avanza el simulador y recoge lo recibido por el cliente."""
    global buf
    got = []
    t_end = time.time() + secs
    if cli is not None:
        cli.settimeout(0.02)
    while time.time() < t_end:
        app.world.step(1 / 30)
        bridge.update(1 / 30)
        if cli is None:
            continue
        try:
            buf += cli.recv(65536)
        except socket.timeout:
            pass
        while b"\n" in buf:
            ln, buf = buf.split(b"\n", 1)
            got.append(json.loads(ln))
    return got


ok = True


def check(cond, txt):
    global ok
    ok &= bool(cond)
    print(("OK   " if cond else "FALLO ") + txt)


send(dict(tipo="estado"))                     # sin saludo: debe dar error
got = pump(0.3)
check(any(m["tipo"] == "error" for m in got), "rechaza mensajes antes del saludo")

send(dict(tipo="hola", nombre="Consola de prueba", protocolo=1))
got = pump(0.6)
got += pump(0.8)
tipos = [m["tipo"] for m in got]
check("bienvenida" in tipos, "bienvenida tras el saludo")
esc = next((m for m in got if m["tipo"] == "escenario"), None)
check(esc is not None and esc["aeropuertos"] and esc["aeropuertos"][0]["pistas"], "envía el escenario con pistas")
est = [m for m in got if m["tipo"] == "estado"]
check(len(est) >= 2 and "lat" in est[-1] and "transpondedor" in est[-1], f"estado periódico ({len(est)} mensajes)")

send(dict(tipo="control", torre="externa", trafico_ia=False))
got = pump(0.3)
check(app.world.atc.external and any(m.get("de") == "control" for m in got), "toma el control de la torre")
check(not any(not getattr(p, "external", False) for p in app.world.traffic.planes), "quita el tráfico automático")

opts = app.world.atc.options()
check(any("rodaje" in o[0].lower() for o in opts), "menú de radio con frases estándar en tierra")
app.world.ac.sys.avionics = True
app.world.ac.sys.battery = True
for e in app.world.ac.sys.engines:
    e.running = True
pump(0.2)
next(o for o in opts if "rodaje" in o[0].lower())[2]()
got = pump(0.4)
tx = [m for m in got if m["tipo"] == "transmision"]
check(tx and "solicito rodaje" in tx[0]["texto"], "la transmisión del piloto llega al ATC: " + (tx[0]["texto"] if tx else "—"))

f = app.world.com_freq
send(dict(tipo="mensaje", texto=f"{app.world.atc.callsign}, ruede a punto de espera pista 36, QNH 1013", frecuencia=f))
got = pump(0.3)
rec = next((m for m in got if m["tipo"] == "recibido"), None)
check(rec and rec["oido"], "el piloto oye el mensaje en su frecuencia")
check(any(m.who == "atc" and "punto de espera" in m.disp for m in app.world.atc.out), "el mensaje pasa a la radio del piloto")
check(app.world.atc.options()[0][0].startswith("Colacionar"), "ofrece colacionar")
send(dict(tipo="mensaje", texto="otra frecuencia", frecuencia=119.95))
got = pump(0.3)
rec = next((m for m in got if m["tipo"] == "recibido"), None)
check(rec and not rec["oido"], "no se oye en otra frecuencia")

lat, lon = esc["aeropuertos"][0]["lat"], esc["aeropuertos"][0]["lon"]
send(dict(tipo="trafico", lista=[dict(id="T1", indicativo="EC-XYZ", tipo="PA28", lat=lat + 0.01, lon=lon,
                                      alt_ft=2500, rumbo=180, gs_kt=100)]))
pump(0.5)
ext = [p for p in app.world.traffic.planes if getattr(p, "external", False)]
check(len(ext) == 1 and abs(ext[0].alt_ft - 2500) < 5, "tráfico externo en el mundo")
send(dict(tipo="meteo", viento_dir=270, viento_kt=12, qnh_hpa=1020))
pump(0.2)
check(app.world.weather.wind_kt == 12 and app.world.weather.qnh_hpa == 1020, "viento y QNH desde el ATC")

cli.close()
cli = None
pump(0.6)
check(not app.world.atc.external, "al desconectarse vuelve la torre automática")
bridge.stop()
print("TODO OK" if ok else "HAY FALLOS")
