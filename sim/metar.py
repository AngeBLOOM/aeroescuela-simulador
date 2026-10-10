"""Meteorología real: METAR del aeropuerto desde aviationweather.gov (NOAA, gratuito, sin clave).

Se descarga en un hilo aparte y se aplica en el bucle principal. Si no hay conexión o el aeropuerto
no emite METAR, se busca el aeropuerto con METAR más cercano en un radio de unos 100 km.
"""
import json
import math
import threading
import urllib.request

API = "https://aviationweather.gov/api/data/metar?format=json&ids="
API_BBOX = "https://aviationweather.gov/api/data/metar?format=json&bbox="

COVER = {"SKC": 0.0, "CLR": 0.0, "NSC": 0.0, "CAVOK": 0.0, "FEW": 0.2, "SCT": 0.42, "BKN": 0.72, "OVC": 0.98, "OVX": 1.0}


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "AeroEscuela-simulador"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8") or "[]")


def fetch(icao, lat=None, lon=None):
    """Devuelve el METAR (dict de la API) del aeropuerto o del más cercano."""
    data = []
    if icao:
        try:
            data = _get(API + icao)
        except Exception:
            data = []
    if not data and lat is not None:
        d = 1.0
        data = _get(API_BBOX + f"{lat - d},{lon - d},{lat + d},{lon + d}")
        data.sort(key=lambda m: math.hypot(m.get("lat", 0) - lat, m.get("lon", 0) - lon))
    return data[0] if data else None


def apply(weather, m, field_elev_ft=0.0):
    """Aplica un METAR a la meteorología del simulador. Devuelve el texto del METAR."""
    w = weather
    wd = m.get("wdir")
    w.wind_dir = float(wd) if isinstance(wd, (int, float)) else w.wind_dir      # VRB → se conserva
    w.wind_kt = float(m.get("wspd") or 0)
    g = m.get("wgst")
    w.gust_kt = max(0.0, float(g) - w.wind_kt) if g else 0.0
    vis = str(m.get("visib", "10"))
    try:
        sm = float(vis.replace("+", ""))
    except ValueError:
        sm = 10.0
    w.visibility_m = 40000.0 if "+" in vis else min(40000.0, sm * 1609.0)
    if m.get("altim"):
        a = float(m["altim"])
        w.qnh_hpa = a if a > 500 else a * 33.8639          # hPa o inHg
    if m.get("temp") is not None:
        isa = 15.0 - 1.98 * field_elev_ft / 1000.0
        w.temp_offset = float(m["temp"]) - isa
    clouds = m.get("clouds") or []
    if clouds:
        worst = max(clouds, key=lambda c: COVER.get(c.get("cover", "SKC"), 0))
        lowest = min((c for c in clouds if c.get("base") is not None), key=lambda c: c["base"], default=None)
        w.cloud_cover = COVER.get(worst.get("cover", "SKC"), 0.3)
        if lowest is not None:
            w.cloud_base_ft = field_elev_ft + float(lowest["base"])
            w.cloud_top_ft = w.cloud_base_ft + (1500 if w.cloud_cover < 0.6 else 3000)
    else:
        w.cloud_cover = 0.05
    raw = m.get("rawOb", "")
    w.turbulence = min(0.8, 0.05 + 0.02 * w.wind_kt + 0.03 * w.gust_kt)
    if any(x in raw for x in (" TS", "+RA", "CB")):
        w.turbulence = max(w.turbulence, 0.7)
    return raw


class LiveWeather:
    """Descarga asíncrona: start(...) y luego poll() en cada fotograma."""

    def __init__(self):
        self.result = None
        self.error = None
        self.busy = False

    def start(self, icao, lat=None, lon=None):
        if self.busy:
            return
        self.busy = True
        self.result = self.error = None

        def run():
            try:
                self.result = fetch(icao, lat, lon)
                if self.result is None:
                    self.error = "No hay METAR disponible cerca"
            except Exception as ex:
                self.error = f"Sin conexión con el servicio de METAR ({ex.__class__.__name__})"
            self.busy = False
        threading.Thread(target=run, daemon=True).start()

    def poll(self):
        if self.busy or (self.result is None and self.error is None):
            return None, None
        r, e = self.result, self.error
        self.result = self.error = None
        return r, e
