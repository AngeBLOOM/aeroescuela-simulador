"""Salida de datos de vuelo por UDP: un datagrama JSON varias veces por segundo con el estado del avión.

Para instrumentos en otra pantalla o tableta, paneles con LEDs y avisos (Arduino por un programa puente),
plataformas de movimiento o registros. Solo envía: no recibe órdenes. Formato en docs/PROTOCOLO_UDP.md;
para ver lo que llega: python tools/udp_escucha.py
"""
import json
import math
import socket

from sim.mathx import FT, KT

VERSION = 1
PORT = 49020


def r(v, n=2):
    return round(float(v), n)


def snapshot(app):
    """Estado del avión como diccionario (lo que se envía)."""
    from sim.geo import LocalProjection
    from .atc_link import SCHOOL_ORIGIN
    w = app.world
    ac = w.ac
    s = ac.sys
    loc = w.location
    proj = LocalProjection(loc["lat0"], loc["lon0"]) if loc is not None else LocalProjection(*SCHOOL_ORIGIN)
    lat, lon = proj.to_geo(ac.pos[0], ac.pos[1])
    p, q, rr = (math.degrees(x) for x in ac.omega)
    t = ac.t
    low_fuel = s.fuel_l < 0.1 * t.fuel_capacity
    return {
        "v": VERSION, "t": r(w.sim_time, 3), "estado": app.state, "ficticio": loc is None,
        "lat": round(float(lat), 7), "lon": round(float(lon), 7),
        "alt_ft": r(ac.alt_msl / FT, 1), "alt_ind_ft": r(w.ind.alt_ft, 1), "agl_ft": r(ac.agl / FT, 1),
        "ias_kt": r(w.ind.ias, 1), "tas_kt": r(ac.tas / KT, 1), "gs_kt": r(ac.gs / KT, 1), "vs_fpm": r(w.ind.vs_fpm, 0),
        "rumbo": r(ac.heading, 1), "rumbo_mag": r((ac.heading - w.magvar) % 360, 1), "declinacion": r(w.magvar, 1),
        "derrota": r(ac.track, 1), "cabeceo": r(math.degrees(ac.pitch)),
        "alabeo": r(math.degrees(ac.roll)), "aoa": r(math.degrees(getattr(ac, "alpha", 0.0))),
        "derrape": r(math.degrees(getattr(ac, "beta", 0.0))),
        "p": r(p), "q": r(q), "r": r(rr), "nx": r(ac.nx, 3), "ny": r(ac.ny, 3), "nz": r(ac.nz, 3),
        "motores": [{"rpm": r(en.rpm, 0), "map_inhg": r(en.map_inhg), "aceite_psi": r(en.oil_press, 1),
                     "aceite_c": r(en.oil_temp, 1), "egt_f": r(en.egt, 0), "cht_f": r(en.cht, 0),
                     "flujo_lh": r(en.fuel_flow, 1), "gases": r(en.throttle, 3), "mezcla": r(en.mixture, 3),
                     "magnetos": en.magnetos, "en_marcha": bool(en.running), "hielo_carb": r(en.carb_ice, 3)}
                    for en in s.engines],
        "flaps": r(s.flaps, 1), "tren": r(s.gear_pos, 3), "freno_estac": bool(s.parking_brake),
        "frenos": [r(max(ac.brake, ac.brake_l), 3), r(max(ac.brake, ac.brake_r), 3)],
        "compensador": r(ac.trim, 3), "en_tierra": bool(ac.on_ground), "choque": bool(ac.crashed),
        "barrena": r(ac.spin * ac.spin_dir, 2),
        "bus_v": r(s.bus_volts, 1), "comb_l": r(s.fuel_l, 1),
        "luces": {k: bool(v) for k, v in s.lights.items()},
        "interruptores": {"bateria": bool(s.master), "alternador": bool(s.alternator), "avionica": bool(s.avionics),
                          "bomba": bool(s.fuel_pump), "pitot": bool(s.pitot_heat), "calef_carb": bool(s.carb_heat)},
        "avisos": {"perdida": bool(s.stall_warning), "volt_bajo": bool(s.master and s.bus_volts < 24.5),
                   "aceite_bajo": any(en.running and en.oil_press < 20 for en in s.engines),
                   "comb_bajo": bool(low_fuel), "tren_inseguro": bool(t.retractable and 0.02 < s.gear_pos < 0.98),
                   "pa_desconectado": bool(w.ap.disconnect_alert > 0), "puerta": bool(s.failures.get("door"))},
        "radio": {"com": w.com_freq, "com_reserva": w.com_standby, "nav1": w.nav1.freq, "nav1_obs": w.nav1.obs,
                  "nav1_cdi": r(w.nav1.cdi, 3), "nav1_gs": r(w.nav1.gs, 3), "nav1_valida": bool(w.nav1.valid),
                  "nav1_hacia": w.nav1.to_from, "xpdr": w.xpdr,
                  "adf_khz": w.adf.freq, "adf_valida": bool(w.adf.valid), "adf_relativa": r(w.adf.relative, 1)},
        "pa": {"conectado": bool(w.ap.engaged), "lateral": w.ap.lat, "vertical": w.ap.vert},
        "gps": {"cdi_fuente": w.cdi_src, "valido": bool(w.gps.valid), "punto": w.gps.ident if w.gps.valid else None,
                "dist_nm": r(w.gps.dis_nm, 2) if w.gps.valid else None, "dtk": w.gps.dtk if w.gps.valid else None,
                "xtk_nm": r(w.gps.xtk_nm, 3), "obs": bool(w.gps.obs_mode)},
        "congelado": sorted(w.frozen), "ritmo": w.sim_rate,
    }


class UdpOut:
    """Envía snapshot(app) a host:port hz veces por segundo. Un destino terminado en .255 se envía como difusión
    (todas las pantallas de la red local)."""

    def __init__(self, host="127.0.0.1", port=PORT, hz=30):
        self.host, self.port = host, int(port)
        self.hz = max(1, min(60, int(hz)))
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if host.endswith(".255"):
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.t = 0.0
        self.sent = 0
        self.error = None

    def update(self, dt, app):
        self.t -= dt
        if self.t > 1e-6:
            return
        self.t = max(self.t + 1.0 / self.hz, 0.0)     # sin ráfagas para recuperar si un fotograma tardó
        try:
            data = json.dumps(snapshot(app), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.sock.sendto(data, (self.host, self.port))
            self.sent += 1
            self.error = None
        except OSError as ex:
            self.error = str(ex)

    def status_text(self):
        return (f"→ {self.host}:{self.port} · {self.hz} Hz · {self.sent} enviados" if self.error is None
                else f"Error: {self.error}")

    def stop(self):
        self.sock.close()
