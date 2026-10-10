"""Consola de controlador de prueba para el enlace con un simulador de ATC externo.

Hace lo mismo que hará el simulador de tránsito aéreo de verdad (protocolo en docs/PROTOCOLO_ATC.md):
se conecta a AeroEscuela, muestra el avión en un radar, recibe lo que dice el piloto y le manda
autorizaciones, tráfico de prueba, viento y QNH. Sirve para comprobar la conexión y como ejemplo
para quien programe el otro simulador.

    python tools/consola_atc.py
"""
import json
import math
import queue
import socket
import threading
import time
import tkinter as tk
from tkinter import ttk

PUERTO = 8770
PUERTO_ANUNCIO = 8771

RAPIDOS = [
    "{cs}, ruede a punto de espera pista {rw}, QNH {qnh}",
    "{cs}, pista {rw}, viento {viento}, autorizado a despegar",
    "{cs}, notifique viento en cola",
    "{cs}, número uno, pista {rw}, viento {viento}, autorizado a aterrizar",
    "{cs}, continúe, tráfico en final delante",
    "{cs}, motor y al aire, repito, motor y al aire",
    "{cs}, ponga transpondedor 4521",
]


class Consola:
    def __init__(self, root):
        self.root = root
        root.title("Consola ATC de prueba · AeroEscuela")
        root.geometry("1180x760")
        self.sock = None
        self.inq = queue.Queue()
        self.estado = None
        self.escenario = None
        self.estela = []
        self.trafico_prueba = False
        self.t0 = time.time()

        top = ttk.Frame(root, padding=6)
        top.pack(fill="x")
        ttk.Label(top, text="Simulador (IP):").pack(side="left")
        self.ip = tk.StringVar(value="127.0.0.1")
        ttk.Entry(top, textvariable=self.ip, width=16).pack(side="left", padx=4)
        ttk.Label(top, text="Puerto:").pack(side="left")
        self.port = tk.StringVar(value=str(PUERTO))
        ttk.Entry(top, textvariable=self.port, width=6).pack(side="left", padx=4)
        ttk.Button(top, text="Buscar en la red", command=self.buscar).pack(side="left", padx=4)
        self.bcon = ttk.Button(top, text="Conectar", command=self.conectar)
        self.bcon.pack(side="left", padx=4)
        self.torre = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Llevar la torre (calla la torre automática)", variable=self.torre,
                        command=self.enviar_control).pack(side="left", padx=12)
        self.ia = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Tráfico automático del simulador", variable=self.ia,
                        command=self.enviar_control).pack(side="left")
        self.info = tk.StringVar(value="Sin conexión")
        ttk.Label(root, textvariable=self.info, padding=(8, 0), font=("Consolas", 11)).pack(fill="x")

        body = ttk.Frame(root, padding=6)
        body.pack(fill="both", expand=True)
        self.radar = tk.Canvas(body, width=640, height=600, bg="#08130c", highlightthickness=0)
        self.radar.pack(side="left", fill="both", expand=True)
        right = ttk.Frame(body, padding=(8, 0))
        right.pack(side="left", fill="y")
        ttk.Label(right, text="Radio (lo que dice el piloto y lo que le manda usted)").pack(anchor="w")
        self.log = tk.Text(right, width=56, height=22, font=("Segoe UI", 10), wrap="word")
        self.log.pack(fill="both", expand=True)
        self.msg = tk.StringVar()
        e = ttk.Entry(right, textvariable=self.msg, width=56)
        e.pack(fill="x", pady=(6, 2))
        e.bind("<Return>", lambda ev: self.enviar_msg())
        ttk.Button(right, text="Transmitir al piloto", command=self.enviar_msg).pack(fill="x")
        ttk.Label(right, text="Frases rápidas:").pack(anchor="w", pady=(8, 0))
        for f in RAPIDOS:
            ttk.Button(right, text=f.replace("{cs}, ", "")[:60], command=lambda f=f: self.rapido(f)).pack(fill="x")
        row = ttk.Frame(right)
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Tráfico de prueba", command=self.toggle_trafico).pack(side="left", expand=True, fill="x")
        ttk.Button(row, text="Viento 270/12, QNH 1018", command=self.meteo).pack(side="left", expand=True, fill="x")

        self.root.after(50, self.tick)

    # ------------------------------------------------------------ red
    def escribir(self, txt, tag=None):
        self.log.insert("end", txt + "\n", tag)
        self.log.see("end")

    def buscar(self):
        self.escribir("Buscando simuladores en la red (3 s)…")

        def run():
            u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            u.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                u.bind(("", PUERTO_ANUNCIO))
            except OSError as ex:
                self.inq.put(("info", f"No se puede escuchar el puerto {PUERTO_ANUNCIO}: {ex}"))
                return
            u.settimeout(0.5)
            end = time.time() + 3
            vistos = {}
            while time.time() < end:
                try:
                    data, addr = u.recvfrom(4096)
                    m = json.loads(data.decode("utf-8"))
                    if m.get("tipo") == "anuncio":
                        vistos[addr[0]] = m
                except (socket.timeout, ValueError):
                    pass
            u.close()
            self.inq.put(("encontrados", vistos))
        threading.Thread(target=run, daemon=True).start()

    def conectar(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None
            return
        try:
            s = socket.create_connection((self.ip.get().strip(), int(self.port.get())), timeout=3)
        except OSError as ex:
            self.escribir(f"No se pudo conectar: {ex}")
            return
        s.settimeout(None)
        self.sock = s
        self.bcon.config(text="Desconectar")
        self.send(dict(tipo="hola", nombre="Consola ATC de prueba", protocolo=1,
                       torre="externa" if self.torre.get() else "interna", trafico_ia=self.ia.get()))
        threading.Thread(target=self.reader, args=(s,), daemon=True).start()

    def reader(self, s):
        buf = b""
        try:
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    ln, buf = buf.split(b"\n", 1)
                    if ln.strip():
                        self.inq.put(("msg", json.loads(ln.decode("utf-8"))))
        except (OSError, ValueError):
            pass
        self.inq.put(("cerrado", None))

    def send(self, obj):
        if self.sock is None:
            self.escribir("(no conectado)")
            return
        try:
            self.sock.sendall((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
        except OSError:
            pass

    # ------------------------------------------------------------ acciones
    def enviar_control(self):
        self.send(dict(tipo="control", torre="externa" if self.torre.get() else "interna", trafico_ia=self.ia.get()))

    def datos(self):
        e, sc = self.estado or {}, self.escenario or {}
        return dict(cs=e.get("indicativo", "EC-AES"), rw=sc.get("pista_en_servicio", "36"),
                    qnh=int(round(e.get("qnh_hpa", 1013))), viento="calma")

    def rapido(self, f):
        self.msg.set(f.format(**self.datos()))
        self.enviar_msg()

    def enviar_msg(self):
        t = self.msg.get().strip()
        if not t:
            return
        fr = (self.estado or {}).get("com1")
        self.send(dict(tipo="mensaje", texto=t, estacion="TWR", frecuencia=fr))
        self.escribir("ATC: " + t, "atc")
        self.msg.set("")

    def meteo(self):
        self.send(dict(tipo="meteo", viento_dir=270, viento_kt=12, qnh_hpa=1018))
        self.escribir("(viento 270° 12 kt y QNH 1018 enviados)")

    def toggle_trafico(self):
        self.trafico_prueba = not self.trafico_prueba
        if not self.trafico_prueba:
            self.send(dict(tipo="trafico", lista=[]))
        self.escribir("Tráfico de prueba " + ("activado: un avión da vueltas sobre el aeródromo" if self.trafico_prueba
                                               else "quitado"))

    def trafico(self):
        ap = (self.escenario or {}).get("aeropuertos", [None])[0]
        if not ap:
            return
        t = time.time() - self.t0
        a = t * 2 * math.pi / 180.0                       # una vuelta cada 3 minutos
        r = 0.025
        lat = ap["lat"] + r * math.cos(a)
        lon = ap["lon"] + r * math.sin(a) / max(0.2, math.cos(math.radians(ap["lat"])))
        rumbo = (math.degrees(a) + 90) % 360
        self.send(dict(tipo="trafico", lista=[dict(id="PRUEBA1", indicativo="EC-TST", tipo="P28A", lat=lat, lon=lon,
                                                   alt_ft=ap["elev_ft"] + 1500, rumbo=rumbo, gs_kt=95, vs_fpm=0)]))

    # ------------------------------------------------------------ bucle de la ventana
    def tick(self):
        while not self.inq.empty():
            kind, m = self.inq.get()
            if kind == "msg":
                self.recibir(m)
            elif kind == "cerrado":
                self.sock = None
                self.bcon.config(text="Conectar")
                self.info.set("Sin conexión")
                self.escribir("— conexión cerrada —")
            elif kind == "encontrados":
                if not m:
                    self.escribir("No se ha encontrado ningún simulador. ¿Está activado «ATC externo» en Ajustes?")
                for ip, a in m.items():
                    self.escribir(f"Encontrado AeroEscuela en {ip}:{a.get('puerto')} · {a.get('indicativo', '')} "
                                  f"en {a.get('aeropuerto', '')}")
                    self.ip.set(ip)
                    self.port.set(str(a.get("puerto", PUERTO)))
            elif kind == "info":
                self.escribir(m)
        if self.trafico_prueba and self.sock is not None:
            self.trafico()
        self.dibujar()
        self.root.after(500 if self.trafico_prueba else 100, self.tick)

    def recibir(self, m):
        t = m.get("tipo")
        if t == "estado":
            self.estado = m
            self.estela.append((m["lat"], m["lon"]))
            self.estela = self.estela[-600:]
            self.info.set(f"{m['indicativo']}  {m['tipo_avion']}   {m['alt_ft']:5d} ft   {m['gs_kt']:5.0f} kt   "
                          f"rumbo {m['rumbo']:03.0f}°   V/S {m['vs_fpm']:+5d}   XPDR {m['transpondedor']['codigo']}   "
                          f"COM1 {m['com1']:.3f}" + ("   EN TIERRA" if m["en_tierra"] else "")
                          + ("   ¡EMERGENCIA!" if m.get("emergencia") else "") + ("   radio averiada" if not m["radio_ok"] else ""))
        elif t == "escenario":
            self.escenario = m
            self.escribir(f"Escenario: {m['nombre']} · pista en servicio {m['pista_en_servicio']} · "
                          f"frecuencias {m['frecuencias']}")
        elif t == "bienvenida":
            self.escribir(f"Conectado a {m['sim']} · {m['indicativo']} ({m['tipo_avion']}) en {m['aeropuerto']}")
        elif t == "transmision":
            self.escribir(f"PILOTO ({m['frecuencia']:.3f}): {m['texto']}", "piloto")
        elif t == "evento":
            self.escribir(f"· Evento: {m['evento']} {m.get('detalle', '')}", "evento")
        elif t == "ptt":
            self.escribir("· El piloto " + ("está transmitiendo…" if m["activo"] else "suelta el PTT"), "evento")
        elif t == "recibido" and not m.get("oido"):
            self.escribir("· El piloto NO lo oyó (otra frecuencia, radio apagada o averiada)", "evento")
        elif t == "error":
            self.escribir("Error: " + m.get("texto", ""))

    def dibujar(self):
        c = self.radar
        c.delete("all")
        W, H = max(c.winfo_width(), 100), max(c.winfo_height(), 100)
        sc = self.escenario
        if not sc or not sc.get("aeropuertos"):
            c.create_text(W / 2, H / 2, text="Sin datos: conecte con el simulador", fill="#5c8")
            return
        ap = sc["aeropuertos"][0]
        lat0, lon0 = ap["lat"], ap["lon"]
        k_lon = math.cos(math.radians(lat0))
        rng = 0.12                                          # grados de latitud de borde a borde (~13 km)
        s = min(W, H) / rng

        def P(la, lo):
            return W / 2 + (lo - lon0) * k_lon * s, H / 2 - (la - lat0) * s
        for r_nm in (2, 4, 6):
            rr = r_nm * 1852 / 111320 * s
            c.create_oval(W / 2 - rr, H / 2 - rr, W / 2 + rr, H / 2 + rr, outline="#1d3a26")
            c.create_text(W / 2 + rr - 14, H / 2 - 8, text=f"{r_nm} NM", fill="#2d5a3a", font=("Consolas", 8))
        for a in sc["aeropuertos"]:
            for p in a["pistas"]:
                c.create_line(*P(p["lat1"], p["lon1"]), *P(p["lat2"], p["lon2"]), fill="#9ab", width=4)
            x, y = P(a["lat"], a["lon"])
            c.create_text(x + 10, y + 12, text=a["icao"], fill="#7a9", anchor="w", font=("Consolas", 9))
        if len(self.estela) > 1:
            c.create_line(*[v for la, lo in self.estela for v in P(la, lo)], fill="#2a6", width=1)
        e = self.estado
        if e:
            x, y = P(e["lat"], e["lon"])
            col = "#f44" if e.get("emergencia") else "#6f6"
            c.create_rectangle(x - 4, y - 4, x + 4, y + 4, outline=col, width=2)
            h = math.radians(e["derrota"])
            c.create_line(x, y, x + math.sin(h) * 30, y - math.cos(h) * 30, fill=col)
            c.create_text(x + 10, y - 10, anchor="w", fill=col, font=("Consolas", 10),
                          text=f"{e['indicativo']}\n{e['alt_ft'] // 100:03d} {e['gs_kt']:.0f}kt\n{e['transpondedor']['codigo']}")
        if self.trafico_prueba and sc:
            c.create_text(10, H - 16, anchor="w", fill="#ccc", text="Tráfico de prueba EC-TST activo")


if __name__ == "__main__":
    root = tk.Tk()
    app = Consola(root)
    app.log.tag_config("piloto", foreground="#0a5fb4")
    app.log.tag_config("atc", foreground="#b46a00")
    app.log.tag_config("evento", foreground="#777")
    root.mainloop()
