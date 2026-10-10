"""Enlace con un simulador de tránsito aéreo externo (consola de controlador, radar, etc.).

Protocolo abierto (ver docs/PROTOCOLO_ATC.md): TCP en el puerto 8770, un objeto JSON por línea (UTF-8,
terminado en '\n'). El simulador de ATC se conecta, saluda con {"tipo": "hola"} y desde ese momento recibe
5 veces por segundo el estado del avión (posición, altitud, velocidad, transpondedor, frecuencia…), las
transmisiones del piloto y los eventos del vuelo. Puede mandar mensajes de radio (se oyen con voz de radio
si el piloto está en esa frecuencia), tomar el control de la torre (la torre automática se calla), cambiar
las opciones del menú de radio del piloto, publicar tráfico propio (aparece en el paisaje y en el TCAS) y
fijar viento y QNH.

Para encontrar el simulador en la red, cada 2 s se anuncia por UDP (difusión) en el puerto 8771.

Los sockets van en hilos aparte; lo recibido se encola y se aplica en el bucle principal (AtcBridge.update),
así el estado del vuelo nunca se toca desde dos hilos a la vez.
"""
import json
import math
import queue
import socket
import threading
import time

import numpy as np

from sim.mathx import FT, KT, quat_from_euler

PROTOCOLO = 1
PUERTO = 8770
PUERTO_ANUNCIO = 8771
ICAO_TYPE = dict(c152="C152", c172="C172", pa28w="P28A", pa28r="P28R", sr20="SR20", da40="DA40", da42="DA42")
SCHOOL_ORIGIN = (40.0, -4.0)        # el escenario escuela es ficticio: se publica con este origen (y "ficticio": true)

# opciones del menú de radio cuando manda el ATC externo: (texto del menú, frase, estación, en tierra / en vuelo)
DEFAULT_OPTIONS = [
    ("Solicitar rodaje (con la información ATIS)", "con la información, solicito rodaje", "GND", "tierra"),
    ("Punto de espera: listo para salir", "en punto de espera, listo para salir", "TWR", "tierra"),
    ("Listo para despegar (en pista)", "alineado, listo para despegar", "TWR", "tierra"),
    ("Pista libre, solicito rodar a plataforma", "pista libre, solicito rodar a plataforma", "GND", "tierra"),
    ("Solicitar ATIS / meteorología", "solicito meteorología", "TWR", "ambos"),
    ("Contacto inicial: solicitar entrada al circuito", "solicito entrada al circuito para aterrizaje", "TWR", "vuelo"),
    ("Notificar viento en cola", "en viento en cola", "TWR", "vuelo"),
    ("Notificar base", "en base", "TWR", "vuelo"),
    ("Notificar final (aterrizaje completo)", "en final, aterrizaje completo", "TWR", "vuelo"),
    ("Notificar final (toma y despegue)", "en final, toma y despegue", "TWR", "vuelo"),
    ("Abandonar el circuito", "abandono el circuito", "TWR", "vuelo"),
    ("Motor y al aire", "motor y al aire", "TWR", "vuelo"),
    ("MAYDAY (emergencia)", "MAYDAY MAYDAY MAYDAY", "TWR", "vuelo"),
]


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class _Client:
    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = addr
        self.name = ""
        self.ready = False              # True tras el saludo
        self.lock = threading.Lock()
        self.alive = True

    def send(self, obj):
        data = (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            with self.lock:
                self.sock.sendall(data)
        except OSError:
            self.alive = False


class AtcLink:
    """Servidor TCP de líneas JSON y anuncio UDP. Sin lógica de vuelo."""

    def __init__(self, port=PUERTO, code=""):
        self.port = port
        self.code = str(code or "")
        self.inbox = queue.Queue()
        self.clients = []
        self.lock = threading.Lock()
        self.srv = None
        self.error = None
        self.running = False
        self.announce = {}

    @property
    def address(self):
        return f"{local_ip()}:{self.port}"

    @property
    def connected(self):
        with self.lock:
            return [c for c in self.clients if c.ready and c.alive]

    def start(self):
        if self.running:
            return
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("0.0.0.0", self.port))
            srv.listen(8)
            srv.settimeout(0.5)
        except OSError as ex:
            self.error = f"No se pudo abrir el puerto {self.port} para el ATC externo: {ex}"
            return
        self.srv = srv
        self.running = True
        threading.Thread(target=self._accept, daemon=True).start()
        threading.Thread(target=self._beacon, daemon=True).start()

    def stop(self):
        self.running = False
        with self.lock:
            cl, self.clients = self.clients, []
        for c in cl:
            try:
                c.sock.close()
            except OSError:
                pass
        if self.srv is not None:
            try:
                self.srv.close()
            except OSError:
                pass
            self.srv = None

    def _accept(self):
        while self.running:
            try:
                sock, addr = self.srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            c = _Client(sock, addr)
            with self.lock:
                self.clients.append(c)
            threading.Thread(target=self._reader, args=(c,), daemon=True).start()

    def _reader(self, c):
        buf = b""
        c.sock.settimeout(1.0)
        while self.running and c.alive:
            try:
                chunk = c.sock.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            if len(buf) > 1 << 20:          # una línea de más de 1 MB no es de este protocolo
                break
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    c.send(dict(tipo="error", texto="JSON no válido"))
                    continue
                if not isinstance(msg, dict):
                    continue
                if not c.ready:
                    if msg.get("tipo") != "hola":
                        c.send(dict(tipo="error", texto="Primero hay que saludar: {\"tipo\": \"hola\"}"))
                        continue
                    if self.code and str(msg.get("codigo", "")) != self.code:
                        c.send(dict(tipo="error", texto="Código incorrecto"))
                        break
                    c.name = str(msg.get("nombre") or f"{c.addr[0]}")[:40]
                    c.ready = True
                self.inbox.put((c, msg))
        c.alive = False
        try:
            c.sock.close()
        except OSError:
            pass
        with self.lock:
            if c in self.clients:
                self.clients.remove(c)
        if c.ready:
            self.inbox.put((c, dict(tipo="_desconectado")))

    def _beacon(self):
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        u.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while self.running:
            msg = dict(tipo="anuncio", sim="AeroEscuela", protocolo=PROTOCOLO, puerto=self.port,
                       ip=local_ip(), codigo=bool(self.code), **self.announce)
            try:
                u.sendto(json.dumps(msg, ensure_ascii=False).encode("utf-8"), ("255.255.255.255", PUERTO_ANUNCIO))
            except OSError:
                pass
            for _ in range(20):
                if not self.running:
                    break
                time.sleep(0.1)
        u.close()

    def poll(self):
        out = []
        while True:
            try:
                out.append(self.inbox.get_nowait())
            except queue.Empty:
                return out

    def broadcast(self, obj):
        for c in self.connected:
            c.send(obj)


class ExtPlane:
    """Tráfico publicado por el simulador de ATC: se mueve por estima entre mensajes."""
    external = True

    def __init__(self, world, ident):
        self.world = world
        self.ident = ident
        self.callsign = ident
        self.type_id = "c172"
        self.type_name = "avión"
        self.kind = "externo"
        self.state = "vuelo"
        self.leg = ""
        self.pos = np.zeros(3)
        self.heading = 0.0
        self.speed = 0.0
        self.vs = 0.0
        self.roll = 0.0
        self.pitch = 0.0
        self.on_ground = False
        self.done = False
        self.last = time.time()
        self.color = (1, 1, 1)

    def set(self, d, proj):
        n = e = None
        if "lat" in d and "lon" in d and proj is not None:
            n, e = proj.to_local(float(d["lat"]), float(d["lon"]))
        elif "x" in d and "y" in d:
            n, e = float(d["x"]), float(d["y"])
        if n is not None:
            self.pos[0], self.pos[1] = float(n), float(e)
        if "alt_ft" in d:
            self.pos[2] = -float(d["alt_ft"]) * FT
        hd = d.get("rumbo", self.heading)
        turn = ((float(hd) - self.heading + 540) % 360) - 180
        self.heading = float(hd) % 360
        self.speed = float(d.get("gs_kt", self.speed / KT)) * KT
        self.vs = float(d.get("vs_fpm", 0.0)) * FT / 60
        self.on_ground = bool(d.get("en_tierra", False))
        self.callsign = str(d.get("indicativo", self.ident))[:12]
        tid = str(d.get("tipo", "")).upper()
        self.type_id = next((k for k, v in ICAO_TYPE.items() if v == tid), "c172")
        self.type_name = tid or "avión"
        self.leg = str(d.get("tramo", ""))
        self.roll = math.radians(max(-30.0, min(30.0, turn * 3.0))) if not self.on_ground else 0.0
        self.pitch = math.atan2(self.vs, max(self.speed, 1.0)) if not self.on_ground else 0.0
        if self.on_ground:
            g = self.world.terrain.height(self.pos[0], self.pos[1]) if hasattr(self.world.terrain, "height") else None
            if g is not None and "alt_ft" not in d:
                self.pos[2] = -(g + 1.2)
        self.last = time.time()

    def update(self, dt):
        h = math.radians(self.heading)
        self.pos[0] += math.cos(h) * self.speed * dt
        self.pos[1] += math.sin(h) * self.speed * dt
        self.pos[2] -= self.vs * dt
        if time.time() - self.last > 10.0:
            self.done = True

    @property
    def quat(self):
        return quat_from_euler(self.roll, self.pitch, math.radians(self.heading))

    @property
    def alt_ft(self):
        return -self.pos[2] / FT


class AtcBridge:
    """Une el enlace de red con el vuelo: publica el estado y aplica lo que manda el ATC externo."""

    def __init__(self, app, port=PUERTO, code=""):
        self.app = app
        self.link = AtcLink(port, code)
        self.link.start()
        self.error = self.link.error
        self._t = 0.0
        self._world = app.world
        self._was_ground = None
        self.control = False            # el ATC externo lleva la torre
        self.ext_traffic = {}

    # ------------------------------------------------------------ utilidades
    @property
    def world(self):
        return self.app.world

    def proj(self):
        from sim.geo import LocalProjection
        loc = self.world.location
        if loc is not None:
            return LocalProjection(loc["lat0"], loc["lon0"])
        return LocalProjection(*SCHOOL_ORIGIN)

    def geo(self, n, e):
        la, lo = self.proj().to_geo(n, e)
        return round(float(la), 7), round(float(lo), 7)

    def status_text(self):
        cl = self.link.connected
        if self.error:
            return self.error
        if not cl:
            return f"Esperando conexión en {self.link.address}"
        return "Conectado: " + ", ".join(c.name for c in cl) + (" · lleva la torre" if self.control else "")

    def stop(self):
        self._release()
        self.link.stop()

    # ------------------------------------------------------------ salida
    def airport_msg(self):
        w = self.world
        loc = w.location
        apts = []
        for a in w.airports:
            rws = []
            for rw in a.runways:
                la1, lo1 = self.geo(*rw.threshold)
                la2, lo2 = self.geo(*rw.far_end)
                rws.append(dict(nombre="/".join(rw.idents), rumbo=round(rw.heading, 1), largo_m=round(rw.length),
                                ancho_m=round(rw.width), lat1=la1, lon1=lo1, lat2=la2, lon2=lo2,
                                elev_ft=round(rw.elev / FT)))
            la, lo = self.geo(*a.ref[:2])
            apts.append(dict(icao=a.ident, nombre=a.name, lat=la, lon=lo, elev_ft=round(a.elev / FT), pistas=rws))
        return dict(tipo="escenario", nombre=w.place_name, ficticio=loc is None,
                    origen=dict(lat=self.proj().lat0, lon=self.proj().lon0),
                    aeropuerto=w.home.ident, pista_en_servicio=w.active_end,
                    frecuencias={k: round(v, 3) for k, v in w.freqs.items()}, aeropuertos=apts,
                    navaids=[dict(id=n.ident, tipo=n.kind, frecuencia=n.freq, lat=self.geo(*n.pos[:2])[0],
                                  lon=self.geo(*n.pos[:2])[1]) for n in w.navaids if n.kind == "VOR"])

    def state_msg(self):
        w = self.world
        ac = w.ac
        s = ac.sys
        la, lo = self.geo(ac.pos[0], ac.pos[1])
        vel = ac.vel if hasattr(ac, "vel") else None
        gs = math.hypot(float(vel[0]), float(vel[1])) / KT if vel is not None else w.ind.ias
        trk = (math.degrees(math.atan2(float(vel[1]), float(vel[0]))) % 360) if vel is not None and gs > 2 else ac.heading
        atc = w.atc
        return dict(
            tipo="estado", t=round(w.sim_time, 2), indicativo=atc.callsign, tipo_avion=ICAO_TYPE.get(ac.t.id, ac.t.id.upper()),
            lat=la, lon=lo, x=round(float(ac.pos[0]), 1), y=round(float(ac.pos[1]), 1),
            alt_ft=round(ac.alt_msl / FT), alt_ind_ft=round(w.ind.alt_ft), agl_ft=round(ac.agl / FT),
            ias_kt=round(w.ind.ias, 1), gs_kt=round(gs, 1), rumbo=round(ac.heading % 360, 1), derrota=round(trk, 1),
            vs_fpm=round(ac.vs_fpm), alabeo=round(math.degrees(ac.roll), 1), cabeceo=round(math.degrees(ac.pitch), 1),
            en_tierra=bool(ac.on_ground), choque=bool(ac.crashed),
            transpondedor=dict(codigo=f"{int(w.xpdr):04d}", modo="ALT" if s.avionics_ok else "OFF"),
            com1=round(w.com_freq, 3), com1_reserva=round(w.com_standby, 3), radio_ok=self._radio_ok(),
            qnh_hpa=round(w.kollsman, 1), motor=bool(s.engine.running), rpm=round(s.engine.rpm),
            flaps=round(s.flaps), tren_abajo=bool(s.gear_down), luces={k: bool(v) for k, v in s.lights.items()},
            emergencia=int(w.xpdr) == 7700 or bool(getattr(atc, "mayday_declared", False)),
            leccion=(self.app.lesson.title if self.app.lesson is not None else ""))

    def _radio_ok(self):
        s = self.world.ac.sys
        return bool(s.avionics_ok and not s.failures.get("radio"))

    def send_pilot_tx(self):
        atc = self.world.atc
        for station, disp in atc.pilot_tx:
            if self._radio_ok():
                self.link.broadcast(dict(tipo="transmision", de="piloto", indicativo=atc.callsign,
                                         frecuencia=round(self.world.com_freq, 3), estacion=station, texto=disp))
        atc.pilot_tx.clear()

    def _events(self):
        w = self.world
        now = (bool(w.stats.get("airborne")), bool(w.ac.crashed), int(w.xpdr))
        prev, self._prev = getattr(self, "_prev", None), now
        if prev is None:
            return
        if now[0] and not prev[0]:
            self.event("despegue", pista=w.active_end)
        elif prev[0] and not now[0] and not now[1]:
            self.event("aterrizaje", pista=w.active_end)
        if now[1] and not prev[1]:
            self.event("accidente", motivo=w.ac.crash_reason)
        if now[2] != prev[2] and now[2] in (7500, 7600, 7700):
            self.event({7500: "interferencia_ilicita", 7600: "falla_de_radio", 7700: "emergencia"}[now[2]],
                       transpondedor=f"{now[2]:04d}")

    def event(self, name, **detail):
        self.link.broadcast(dict(tipo="evento", evento=name, detalle=detail))

    def ptt(self, on):
        self.link.broadcast(dict(tipo="ptt", activo=bool(on), frecuencia=round(self.world.com_freq, 3)))

    # ------------------------------------------------------------ entrada
    def _release(self):
        if self.control:
            self.control = False
            atc = self.world.atc
            atc.external = False
            atc.ext_options = None
            self.app.flash("La torre vuelve a ser la automática", 2.5)
        for p in list(self.world.traffic.planes):
            if getattr(p, "external", False):
                p.done = True
        self.ext_traffic.clear()

    def handle(self, c, m):
        w = self.world
        atc = w.atc
        t = m.get("tipo")
        if t == "hola":
            c.send(dict(tipo="bienvenida", sim="AeroEscuela", protocolo=PROTOCOLO, indicativo=atc.callsign,
                        tipo_avion=ICAO_TYPE.get(w.ac.t.id, ""), aeropuerto=w.home.ident))
            c.send(self.airport_msg())
            self.app.flash(f"Simulador ATC conectado: {c.name}", 2.5)
            if m.get("torre") == "externa":
                self.handle(c, dict(tipo="control", torre="externa", trafico_ia=m.get("trafico_ia", True)))
        elif t == "_desconectado":
            if not self.link.connected:
                self._release()
            self.app.flash("Simulador ATC desconectado", 2.0)
        elif t == "ping":
            c.send(dict(tipo="pong", t=m.get("t")))
        elif t == "control":
            ext = m.get("torre") == "externa"
            self.control = ext
            atc.external = ext
            if not ext:
                atc.ext_options = None
            if "trafico_ia" in m:
                tr = w.traffic
                tr.enabled = bool(m["trafico_ia"]) and bool(self.app.settings.get("trafico", True))
                if not tr.enabled:
                    tr.planes = [p for p in tr.planes if getattr(p, "external", False)]
            self.app.flash("El simulador ATC lleva la torre" if ext else "La torre vuelve a ser la automática", 2.5)
            c.send(dict(tipo="ok", de="control", torre="externa" if ext else "interna"))
        elif t == "mensaje":
            txt = str(m.get("texto", "")).strip()
            if not txt:
                return
            f = m.get("frecuencia")
            heard = self._radio_ok() and (f is None or abs(float(f) - w.com_freq) < 0.004)
            if heard:
                atc.ext_message(txt, str(m.get("voz") or txt), str(m.get("estacion") or "TWR"),
                                readback=bool(m.get("colacionar", True)))
            c.send(dict(tipo="recibido", oido=heard, texto=txt))
        elif t == "opciones":
            lst = m.get("lista")
            if lst is None:
                atc.ext_options = None
            else:
                opts = []
                for it in lst[:9]:
                    if isinstance(it, str):
                        opts.append((it, it, "TWR", "ambos"))
                    elif isinstance(it, dict) and it.get("texto"):
                        opts.append((str(it["texto"]), str(it.get("frase") or it["texto"]), str(it.get("estacion", "TWR")),
                                     "ambos"))
                atc.ext_options = opts
        elif t == "trafico":
            proj = self.proj()
            seen = set()
            for d in m.get("lista", []):
                if not isinstance(d, dict) or "id" not in d:
                    continue
                k = str(d["id"])
                seen.add(k)
                p = self.ext_traffic.get(k)
                if p is None or p.done or all(q is not p for q in w.traffic.planes):
                    p = ExtPlane(w, k)
                    self.ext_traffic[k] = p
                    w.traffic.planes.append(p)
                p.set(d, proj)
            if m.get("completa", True):
                for k, p in list(self.ext_traffic.items()):
                    if k not in seen:
                        p.done = True
                        del self.ext_traffic[k]
        elif t == "meteo":
            wx = w.weather
            if "viento_dir" in m:
                wx.wind_dir = float(m["viento_dir"]) % 360
            if "viento_kt" in m:
                wx.wind_kt = max(0.0, float(m["viento_kt"]))
            if "rafagas_kt" in m:
                wx.gust_kt = max(0.0, float(m["rafagas_kt"]))
            if "qnh_hpa" in m:
                wx.qnh_hpa = float(m["qnh_hpa"])
            if "visibilidad_m" in m:
                wx.visibility_m = float(m["visibilidad_m"])
            c.send(dict(tipo="ok", de="meteo"))
        elif t == "frecuencias":
            for k, v in (m.get("lista") or {}).items():
                if k in ("TWR", "GND", "ATIS"):
                    w.freqs[k] = float(v)
            c.send(dict(tipo="ok", de="frecuencias", lista=w.freqs))
        elif t == "pedir":
            c.send(self.airport_msg() if m.get("que") == "escenario" else self.state_msg())
        else:
            c.send(dict(tipo="error", texto=f"Tipo de mensaje desconocido: {t}"))

    def update(self, dt):
        if self._world is not self.world:
            # nuevo escenario: se reenvía a los conectados y la torre externa sigue mandando
            self._world = self.world
            self.ext_traffic.clear()
            self.world.atc.external = self.control
            self.link.broadcast(self.airport_msg())
        self.link.announce = dict(indicativo=self.world.atc.callsign, aeropuerto=self.world.home.ident)
        for c, m in self.link.poll():
            try:
                self.handle(c, m)
            except (ValueError, TypeError, KeyError) as ex:
                c.send(dict(tipo="error", texto=f"Mensaje no válido: {ex}"))
        if not self.link.connected:
            self.world.atc.pilot_tx.clear()
            return
        self.send_pilot_tx()
        self._events()
        self._t -= dt
        if self._t <= 0:
            self._t = 0.2
            self.link.broadcast(self.state_msg())
