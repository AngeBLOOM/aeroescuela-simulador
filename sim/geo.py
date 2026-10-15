"""Geodatos reales: aeropuertos del mundo, relieve y fotografía satelital.

Fuentes (descargadas bajo demanda y guardadas en caché en datos/geo):
  * Aeropuertos, pistas y radioayudas: OurAirports (dominio público).
  * Relieve: AWS Terrain Tiles / Mapzen "terrarium" (SRTM, GMTED, ETOPO...).
  * Imágenes: Esri World Imagery (© Esri, Maxar, Earthstar Geographics y
    la comunidad GIS) con respaldo de Sentinel-2 cloudless de EOX (CC BY-NC-SA).

El escenario se proyecta en un plano tangente local (NED) centrado en el
aeropuerto elegido, de modo que la física y el render no cambian.
"""
import concurrent.futures as cf
import csv
import io
import math
import os
import urllib.request

import numpy as np

from .airports import ILS, NDB, VOR, Airport, Runway

R_EARTH = 6371008.8
FT = 0.3048
UA = "AeroEscuela-Simulador/1.0 (entrenamiento de pilotos)"

OA_BASE = "https://davidmegginson.github.io/ourairports-data/"
DEM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
IMG_URLS = [
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2020_3857/default/g/{z}/{y}/{x}.jpg",
]
ATTRIBUTION = ("Imágenes © Esri, Maxar, Earthstar Geographics · Relieve: AWS Terrain Tiles (SRTM/GMTED) · "
               "Edificios: © OpenStreetMap, Microsoft (vía Esri) · Aeropuertos: OurAirports")
VT_URL = "https://basemaps.arcgis.com/arcgis/rest/services/OpenStreetMap_v2/VectorTileServer/tile/{z}/{y}/{x}.pbf"
BUILDING_LAYERS = {"OSM building": 0, "OSM major building": 1, "Daylight building": 0}
FOREST_SYMBOLS = {51: "bosque", 48: "parque", 49: "zona verde"}

HALF = 25600.0           # semilado del escenario (m)
# fotografía satelital en tres niveles: (semilado del área en m, metros por píxel de la descarga, píxeles de la textura)
SAT_LAYERS = ((HALF, 12.0, 4096), (10000.0, 4.8, 4096), (3000.0, 1.2, 4096))
SAT_VERSION = 2          # al cambiar la resolución se vuelve a descargar el escenario
GRID_N = 513


def _cache_dir(base):
    d = os.path.join(base, "geo")
    os.makedirs(d, exist_ok=True)
    return d


def download(url, path, timeout=30):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return path


# ======================================================================= aeropuertos
class AirportDB:
    TYPES = {"large_airport": 3, "medium_airport": 2, "small_airport": 1}

    def __init__(self, data_dir):
        self.dir = _cache_dir(data_dir)
        self.airports = None
        self.runways = None
        self.navaids = None

    def ensure(self, progress=None):
        for i, name in enumerate(("airports.csv", "runways.csv", "navaids.csv")):
            p = os.path.join(self.dir, name)
            if not os.path.exists(p):
                if progress:
                    progress(f"Descargando base mundial de aeropuertos ({name})…", 0.05 + 0.1 * i)
                download(OA_BASE + name, p, timeout=120)
        if self.airports is None:
            self._load()

    def _read(self, name):
        with open(os.path.join(self.dir, name), "r", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    def _load(self):
        self.airports = {}
        for a in self._read("airports.csv"):
            if a["type"] not in self.TYPES:
                continue
            self.airports[a["ident"].upper()] = a
        self.by_code = {}
        for a in self.airports.values():
            for k in ("icao_code", "iata_code", "gps_code", "local_code"):
                c = (a.get(k) or "").upper()
                if c and c not in self.by_code:
                    self.by_code[c] = a
        self.runways = {}
        for r in self._read("runways.csv"):
            if r.get("closed") == "1":
                continue
            self.runways.setdefault(r["airport_ident"].upper(), []).append(r)
        self.navaids = [n for n in self._read("navaids.csv") if n["type"] in ("VOR", "VOR-DME", "VORTAC", "NDB", "NDB-DME")]

    def frequencies(self, ident):
        """Frecuencias publicadas del aeropuerto: {'TWR': 118.1, 'GND': 121.7, 'ATIS': 127.8, ...}."""
        p = os.path.join(self.dir, "airport-frequencies.csv")
        try:
            if not os.path.exists(p):
                download(OA_BASE + "airport-frequencies.csv", p, timeout=60)
            if not hasattr(self, "_freqs"):
                self._freqs = {}
                for r in self._read("airport-frequencies.csv"):
                    self._freqs.setdefault(r["airport_ident"].upper(), []).append(r)
        except Exception as ex:
            print("Sin frecuencias de aeropuerto:", ex)
            return {}
        out = {}
        for r in self._freqs.get(ident.upper(), []):
            t = (r.get("type") or "").upper()
            try:
                mhz = float(r.get("frequency_mhz") or 0)
            except ValueError:
                continue
            if not 118.0 <= mhz <= 137.0:
                continue
            key = {"TWR": "TWR", "TOWER": "TWR", "GND": "GND", "GROUND": "GND", "ATIS": "ATIS", "CTAF": "TWR",
                   "UNIC": "TWR", "UNICOM": "TWR", "AFIS": "TWR", "A/G": "TWR", "APP": "APP", "DEP": "APP"}.get(t)
            if key and key not in out:
                out[key] = round(mhz, 3)
        return out

    def get(self, code):
        code = code.strip().upper()
        return self.airports.get(code) or self.by_code.get(code)

    def search(self, q, limit=12):
        q = q.strip().lower()
        if not q:
            return []
        out = []
        for a in self.airports.values():
            ident = a["ident"].lower()
            hay = " ".join((ident, (a.get("iata_code") or "").lower(), a["name"].lower(),
                            (a.get("municipality") or "").lower()))
            if q in hay:
                score = self.TYPES[a["type"]] * 10
                if ident == q or (a.get("iata_code") or "").lower() == q:
                    score += 100
                elif ident.startswith(q):
                    score += 50
                if self.runways.get(a["ident"].upper()):
                    score += 5
                out.append((score, a))
        out.sort(key=lambda s: -s[0])
        return [a for _, a in out[:limit]]


# ======================================================================= proyección
class LocalProjection:
    def __init__(self, lat0, lon0):
        self.lat0 = lat0
        self.lon0 = lon0
        self.k_lat = math.radians(1.0) * R_EARTH
        self.k_lon = math.radians(1.0) * R_EARTH * math.cos(math.radians(lat0))

    def to_local(self, lat, lon):
        return (np.asarray(lat) - self.lat0) * self.k_lat, (np.asarray(lon) - self.lon0) * self.k_lon

    def to_geo(self, north, east):
        return self.lat0 + np.asarray(north) / self.k_lat, self.lon0 + np.asarray(east) / self.k_lon


def merc_px(lat, lon, z):
    n = 256.0 * (2 ** z)
    x = (np.asarray(lon) + 180.0) / 360.0 * n
    la = np.radians(np.clip(lat, -85.0, 85.0))
    y = (1.0 - np.log(np.tan(la) + 1.0 / np.cos(la)) / math.pi) / 2.0 * n
    return x, y


# ======================================================================= mosaicos
class TileFetcher:
    def __init__(self, data_dir, progress=None):
        self.dir = _cache_dir(data_dir)
        self.progress = progress
        self.done = 0
        self.total = 1

    def _tile_path(self, kind, z, x, y, ext):
        d = os.path.join(self.dir, kind, str(z), str(x))
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"{y}.{ext}")

    def _get(self, kind, z, x, y):
        import pygame
        if kind == "dem":
            p = self._tile_path("dem", z, x, y, "png")
            try:
                download(DEM_URL.format(z=z, x=x, y=y), p)
                img = pygame.image.load(p)
                a = pygame.surfarray.array3d(img).astype(np.float32).transpose(1, 0, 2)
                return a[..., 0] * 256.0 + a[..., 1] + a[..., 2] / 256.0 - 32768.0
            except Exception:
                return np.zeros((256, 256), np.float32)
        p = self._tile_path("img", z, x, y, "jpg")
        for url in IMG_URLS:
            try:
                download(url.format(z=z, x=x, y=y), p)
                img = pygame.image.load(p)
                return pygame.surfarray.array3d(img).transpose(1, 0, 2)
            except Exception:
                if os.path.exists(p):
                    os.remove(p)
        return np.full((256, 256, 3), 90, np.uint8)

    def mosaic(self, kind, z, lat_rng, lon_rng):
        """Descarga los mosaicos que cubren el rectángulo y devuelve (array, x0px, y0px)."""
        x_a, y_a = merc_px(lat_rng[1], lon_rng[0], z)
        x_b, y_b = merc_px(lat_rng[0], lon_rng[1], z)
        tx0, tx1 = int(x_a // 256), int(x_b // 256)
        ty0, ty1 = int(y_a // 256), int(y_b // 256)
        coords = [(x, y) for y in range(ty0, ty1 + 1) for x in range(tx0, tx1 + 1)]
        nx, ny = tx1 - tx0 + 1, ty1 - ty0 + 1
        if kind == "dem":
            out = np.zeros((ny * 256, nx * 256), np.float32)
        else:
            out = np.zeros((ny * 256, nx * 256, 3), np.uint8)
        with cf.ThreadPoolExecutor(max_workers=12) as ex:
            futs = {ex.submit(self._get, kind, z, x, y): (x, y) for x, y in coords}
            for fu in cf.as_completed(futs):
                x, y = futs[fu]
                a = fu.result()
                out[(y - ty0) * 256:(y - ty0 + 1) * 256, (x - tx0) * 256:(x - tx0 + 1) * 256] = a
                self.done += 1
                if self.progress:
                    self.progress(f"Descargando relieve e imágenes satelitales… {self.done}/{self.total}",
                                  0.2 + 0.7 * self.done / max(self.total, 1))
        return out, tx0 * 256, ty0 * 256

    @staticmethod
    def count(z, lat_rng, lon_rng):
        x_a, y_a = merc_px(lat_rng[1], lon_rng[0], z)
        x_b, y_b = merc_px(lat_rng[0], lon_rng[1], z)
        return (int(x_b // 256) - int(x_a // 256) + 1) * (int(y_b // 256) - int(y_a // 256) + 1)


def resample(mosaic, x0, y0, z, proj, n0, n1, e0, e1, size, linear=False):
    """Remuestrea un mosaico Mercator a una rejilla local (filas = norte ascendente, columnas = este)."""
    north = np.linspace(n0, n1, size)
    east = np.linspace(e0, e1, size)
    lat, _ = proj.to_geo(north, np.zeros_like(north))
    _, lon = proj.to_geo(np.zeros_like(east), east)
    px, _ = merc_px(np.full_like(lon, proj.lat0), lon, z)
    _, py = merc_px(lat, np.full_like(lat, proj.lon0), z)
    fx = px - x0 - 0.5
    fy = py - y0 - 0.5
    H, W = mosaic.shape[:2]
    if not linear:
        ix = np.clip(np.round(fx).astype(int), 0, W - 1)
        iy = np.clip(np.round(fy).astype(int), 0, H - 1)
        return mosaic[np.ix_(iy, ix)]
    ix0 = np.clip(np.floor(fx).astype(int), 0, W - 2)
    iy0 = np.clip(np.floor(fy).astype(int), 0, H - 2)
    ax = np.clip(fx - ix0, 0, 1)[None, :]
    ay = np.clip(fy - iy0, 0, 1)[:, None]
    m = mosaic
    a = m[np.ix_(iy0, ix0)]
    b = m[np.ix_(iy0, ix0 + 1)]
    c = m[np.ix_(iy0 + 1, ix0)]
    d = m[np.ix_(iy0 + 1, ix0 + 1)]
    return a * (1 - ax) * (1 - ay) + b * ax * (1 - ay) + c * (1 - ax) * ay + d * ax * ay


def _zoom_for(m_per_px, lat):
    return int(max(1, min(18, math.ceil(math.log2(156543.03 * math.cos(math.radians(lat)) / m_per_px)))))


# ======================================================================= lagos, embalses y ríos anchos
WATER_N = 4096


def fetch_water(data_dir, proj, progress=None, r=HALF, z=13):
    """Máscara de agua (lagos, embalses, ríos anchos y mar) a partir de OpenStreetMap: imagen de WATER_N×WATER_N
    (filas = norte, columnas = este) que cubre el escenario. 255 = agua."""
    import pygame
    from . import mvt
    d = os.path.join(_cache_dir(data_dir), "vt")
    lat0, lon0 = proj.lat0, proj.lon0
    la = (lat0 - r / proj.k_lat, lat0 + r / proj.k_lat)
    lo = (lon0 - r / proj.k_lon, lon0 + r / proj.k_lon)
    x0, y0 = merc_px(la[1], lo[0], z)
    x1, y1 = merc_px(la[0], lo[1], z)
    tiles = [(x, y) for y in range(int(y0 // 256), int(y1 // 256) + 1) for x in range(int(x0 // 256), int(x1 // 256) + 1)]

    def get(t):
        x, y = t
        p = os.path.join(d, str(z), str(x), f"{y}.pbf")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        try:
            if not os.path.exists(p):
                download(VT_URL.format(z=z, x=x, y=y), p)
            with open(p, "rb") as fh:
                return t, mvt.decode(fh.read())
        except Exception:
            return t, {}
    surf = pygame.Surface((WATER_N, WATER_N))
    surf.fill((0, 0, 0))
    scale = 2 ** z * 256.0
    n_done = 0
    found = 0
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        for (tx, ty), L in ex.map(get, tiles):
            n_done += 1
            if progress and n_done % 8 == 0:
                progress(f"Descargando lagos y ríos… {n_done}/{len(tiles)}", 0.95 + 0.03 * n_done / len(tiles))
            for lname, feats in L.items():
                ln = lname.lower()
                if "label" in ln or not ("water area" in ln or "marine" in ln or "ocean" in ln):
                    continue
                for gtype, rings, attrs, extent in feats:
                    if gtype != 3:
                        continue
                    for ring in rings:
                        if len(ring) < 3:
                            continue
                        a = np.array(ring, dtype=np.float64)
                        # anillo exterior: área positiva en coordenadas del mosaico; interior (isla): negativa
                        area = 0.5 * float(np.sum(a[:, 0] * np.roll(a[:, 1], -1) - np.roll(a[:, 0], -1) * a[:, 1]))
                        px = (tx + a[:, 0] / extent) * 256.0
                        py = (ty + a[:, 1] / extent) * 256.0
                        lon = px / scale * 360.0 - 180.0
                        lat = np.degrees(np.arctan(np.sinh(math.pi * (1 - 2 * py / scale))))
                        nn, ee = proj.to_local(lat, lon)
                        col = (ee + r) / (2 * r) * WATER_N
                        row = (nn + r) / (2 * r) * WATER_N
                        pts = list(zip(col.tolist(), row.tolist()))
                        pygame.draw.polygon(surf, (255, 255, 255) if area > 0 else (0, 0, 0), pts)
                        found += 1
    mask = np.array(pygame.surfarray.pixels_red(surf)).T.copy()       # [x][y] → [fila=norte][columna=este]
    del surf
    return mask.astype(np.uint8), (-r, -r, 2 * r, 2 * r), found


# ======================================================================= edificios y bosques
def fetch_features(data_dir, proj, progress=None, r_build=3800.0, r_forest=8000.0):
    """Contornos de edificios y bosques (OpenStreetMap vía mosaicos vectoriales de Esri)."""
    import json
    from . import mvt
    d = os.path.join(_cache_dir(data_dir), "vt")
    lat0, lon0 = proj.lat0, proj.lon0

    def tiles(z, r):
        la = (lat0 - r / proj.k_lat, lat0 + r / proj.k_lat)
        lo = (lon0 - r / proj.k_lon, lon0 + r / proj.k_lon)
        x0, y0 = merc_px(la[1], lo[0], z)
        x1, y1 = merc_px(la[0], lo[1], z)
        return [(z, x, y) for y in range(int(y0 // 256), int(y1 // 256) + 1) for x in range(int(x0 // 256), int(x1 // 256) + 1)]
    jobs = [(t, "b") for t in tiles(15, r_build)] + [(t, "f") for t in tiles(14, r_forest)]

    def get(job):
        (z, x, y), kind = job
        p = os.path.join(d, str(z), str(x), f"{y}.pbf")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        try:
            download(VT_URL.format(z=z, x=x, y=y), p)
            with open(p, "rb") as fh:
                data = fh.read()
            layers = set(BUILDING_LAYERS) if kind == "b" else {"landcover"}
            return job, mvt.decode(data, layers)
        except Exception:
            return job, {}
    buildings, forests = [], []
    n = 0
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        for (tile, kind), L in ex.map(get, jobs):
            n += 1
            if progress and n % 8 == 0:
                progress(f"Descargando edificios y bosques… {n}/{len(jobs)}", 0.9 + 0.05 * n / len(jobs))
            z, tx, ty = tile
            scale = 2 ** z * 256.0
            for lname, feats in L.items():
                for gtype, rings, attrs, extent in feats:
                    if gtype != 3:
                        continue
                    if kind == "f":
                        sym = attrs.get("_symbol")
                        if sym not in FOREST_SYMBOLS:
                            continue
                    for ring in rings[:1]:
                        if len(ring) < 3:
                            continue
                        a = np.array(ring, dtype=np.float64)
                        px = (tx + a[:, 0] / extent) * 256.0
                        py = (ty + a[:, 1] / extent) * 256.0
                        lon = px / scale * 360.0 - 180.0
                        lat = np.degrees(np.arctan(np.sinh(math.pi * (1 - 2 * py / scale))))
                        nn, ee = proj.to_local(lat, lon)
                        poly = np.column_stack([nn, ee])
                        if kind == "b":
                            buildings.append((poly, BUILDING_LAYERS[lname]))
                        else:
                            forests.append((poly, FOREST_SYMBOLS[attrs["_symbol"]]))
    return buildings, forests


# ======================================================================= escenario real
NDB_RANGE_NM = {"HIGH": 75.0, "MEDIUM": 50.0, "LOW": 25.0}


def _variation(n, slaved=False):
    """Declinación magnética de una fila de navaids.csv (grados, + = este). En un VOR, la de su rosa (slaved)."""
    for k in (("slaved_variation_deg", "magnetic_variation_deg") if slaved else ("magnetic_variation_deg",)):
        try:
            return float(n.get(k) or "")
        except ValueError:
            continue
    return None


def local_variation(rows, lat0, lon0, radius_km=250.0):
    """Declinación magnética del lugar (grados, + = este; Venezuela ≈ −13, es decir 13° oeste): media de las
    radioayudas de OurAirports a menos de radius_km, pesada por cercanía. 0 si no hay ninguna."""
    k_lat = 111.2
    k_lon = 111.2 * math.cos(math.radians(lat0))
    num = den = 0.0
    for n in rows:
        v = _variation(n)
        if v is None:
            continue
        try:
            d = math.hypot((float(n["latitude_deg"]) - lat0) * k_lat, (float(n["longitude_deg"]) - lon0) * k_lon)
        except (KeyError, ValueError):
            continue
        if d < radius_km:
            wgt = 1.0 / (d + 20.0)
            num += v * wgt
            den += wgt
    return round(num / den, 1) if den else 0.0


def navaid_from_row(n, proj, lat0, lon0):
    """VOR o NDB de una fila de navaids.csv (OurAirports) en coordenadas locales; None si queda lejos del escenario
    (60 km) o le faltan datos. Los VOR van en MHz y los NDB en kHz, con un alcance según su potencia."""
    try:
        la, lo = float(n["latitude_deg"]), float(n["longitude_deg"])
        khz = float(n["frequency_khz"])
    except (KeyError, ValueError):
        return None
    if abs(la - lat0) > 0.6 or abs(lo - lon0) > 0.8:
        return None
    nn, ee = proj.to_local(la, lo)
    if math.hypot(nn, ee) >= 60000:
        return None
    try:
        el = float(n["elevation_ft"]) * FT
    except (KeyError, ValueError):
        el = 0.0
    if n.get("type", "").startswith("NDB"):
        if not 190 <= khz <= 1750:
            return None
        return NDB(n["ident"], round(khz), (float(nn), float(ee)), el, n["name"],
                   NDB_RANGE_NM.get((n.get("power") or "").upper(), 25.0))
    vor = VOR(n["ident"], round(khz / 1000.0, 2), (float(nn), float(ee)), el, n["name"])
    vor.magvar = _variation(n, slaved=True)        # los radiales se miden desde el norte magnético del VOR
    return vor


def build_location(code, data_dir, progress=None, db=None, center=None):
    """Prepara todo lo necesario para volar en un aeropuerto real.

    Con center=(lat, lon) el escenario se centra en ese punto (tramos de una ruta larga) y su aeródromo principal es
    el más cercano. Devuelve dict con: name, ident, lat0, lon0, airports, navaids, heights, sat (lista de capas)."""
    db = db or AirportDB(data_dir)
    db.ensure(progress)
    if center is not None:
        lat0, lon0 = round(float(center[0]), 2), round(float(center[1]), 2)
        a = None
        ident = None
        key = f"pt_{lat0:.2f}_{lon0:.2f}"
    else:
        a = db.get(code)
        if a is None:
            raise ValueError(f"No se encontró el aeropuerto «{code}»")
        ident = a["ident"].upper()
        key = ident
        lat0, lon0 = float(a["latitude_deg"]), float(a["longitude_deg"])
    cache = os.path.join(_cache_dir(data_dir), f"loc{SAT_VERSION}_{key}.npz")
    proj = LocalProjection(lat0, lon0)
    n0, n1 = -HALF, HALF
    lat_rng = (lat0 - HALF / proj.k_lat * 1.02, lat0 + HALF / proj.k_lat * 1.02)
    lon_rng = (lon0 - HALF / proj.k_lon * 1.02, lon0 + HALF / proj.k_lon * 1.02)

    if os.path.exists(cache):
        if progress:
            progress("Cargando escenario guardado…", 0.6)
        z = np.load(cache)
        heights = z["heights"]
        layers = [(z[f"sat{i}"], tuple(z[f"rect{i}"])) for i in range(3)]
    else:
        tf = TileFetcher(data_dir, progress)
        z_dem = _zoom_for(60.0, lat0)
        sat_z = [(_zoom_for(mpp, lat0), h, size) for h, mpp, size in SAT_LAYERS]

        def rng(h):
            return ((lat0 - h / proj.k_lat * 1.02, lat0 + h / proj.k_lat * 1.02),
                    (lon0 - h / proj.k_lon * 1.02, lon0 + h / proj.k_lon * 1.02))
        tf.total = TileFetcher.count(z_dem, lat_rng, lon_rng) + sum(
            TileFetcher.count(zz, *(rng(h) if h < HALF else (lat_rng, lon_rng))) for zz, h, _s in sat_z)
        dem, x0, y0 = tf.mosaic("dem", z_dem, lat_rng, lon_rng)
        heights = resample(dem, x0, y0, z_dem, proj, n0, n1, n0, n1, GRID_N, linear=True).astype(np.float32)
        layers = []
        for zz, h, size in sat_z:
            la, lo = rng(h) if h < HALF else (lat_rng, lon_rng)
            mos, x0, y0 = tf.mosaic("img", zz, la, lo)
            img = resample(mos, x0, y0, zz, proj, -h, h, -h, h, size)
            layers.append((img.astype(np.uint8), (-h, -h, 2 * h, 2 * h)))
        np.savez_compressed(cache, heights=heights, **{f"sat{i}": l[0] for i, l in enumerate(layers)},
                            **{f"rect{i}": np.array(l[1]) for i, l in enumerate(layers)})

    # ---------------- aeropuertos y pistas reales dentro del escenario
    if progress:
        progress("Preparando aeropuertos y radioayudas…", 0.93)
    airports = []
    navaids = []
    cand = []
    for b in db.airports.values():
        try:
            la, lo = float(b["latitude_deg"]), float(b["longitude_deg"])
        except ValueError:
            continue
        if abs(la - lat0) > 0.3 or abs(lo - lon0) > 0.4:
            continue
        nn, ee = proj.to_local(la, lo)
        if abs(nn) < HALF * 0.9 and abs(ee) < HALF * 0.9 and db.runways.get(b["ident"].upper()):
            cand.append((b["ident"].upper() != ident, float(math.hypot(nn, ee)), b, float(nn), float(ee)))
    cand.sort(key=lambda c: (c[0], c[1]))
    for _, _, b, nn, ee in cand[:8]:
        rws = []
        for r in db.runways.get(b["ident"].upper(), []):
            rw = _runway_from_row(r, proj, b)
            if rw is not None:
                rws.append(rw)
        if not rws:
            continue
        rws.sort(key=lambda r: -r.length)
        try:
            elev = float(b["elevation_ft"]) * FT
        except ValueError:
            elev = 0.0
        # la cota del terreno manda (coherencia con el relieve)
        dem_e = _sample(heights, rws[0].center[0], rws[0].center[1])
        elev = dem_e if abs(dem_e - elev) < 120 else elev
        ap = Airport(b["ident"].upper(), b["name"], (nn, ee), elev, rws)
        ap.real = True
        airports.append(ap)
    if not airports and center is not None:
        # tramo de ruta sin aeródromos: el más cercano (hasta 90 km) sirve de referencia de radio, fuera del paisaje
        best = None
        for b in db.airports.values():
            try:
                la, lo = float(b["latitude_deg"]), float(b["longitude_deg"])
            except ValueError:
                continue
            if abs(la - lat0) > 0.9 or abs(lo - lon0) > 0.9 or not db.runways.get(b["ident"].upper()):
                continue
            nn, ee = proj.to_local(la, lo)
            dd = float(math.hypot(nn, ee))
            if dd < 90000 and (best is None or dd < best[0]):
                best = (dd, b, float(nn), float(ee))
        if best is not None:
            _d, b, nn, ee = best
            rws = [rw for rw in (_runway_from_row(r, proj, b) for r in db.runways.get(b["ident"].upper(), [])) if rw]
            if rws:
                rws.sort(key=lambda r: -r.length)
                try:
                    elev = float(b["elevation_ft"]) * FT
                except ValueError:
                    elev = 0.0
                ap = Airport(b["ident"].upper(), b["name"], (nn, ee), elev, rws)
                ap.real = True
                ap.offscene = True
                airports.append(ap)
    if not airports:
        raise ValueError(f"El aeropuerto «{code}» no tiene pistas con coordenadas en la base de datos" if center is None
                         else "No hay aeródromos con pistas en esta zona")
    if a is None:
        a = db.get(airports[0].ident)
        ident = airports[0].ident
    # ILS sintéticos (las frecuencias reales no están en la base pública)
    freqs = iter([110.30, 108.90, 109.50, 111.10, 110.70, 109.10, 111.50, 108.50, 110.10, 109.70, 111.90, 108.30])
    for ap in airports[:3]:
        for rw in ap.runways[:2]:
            for end in rw.idents:
                f = next(freqs, None)
                # ILS de entrenamiento solo donde es verosímil: pista pavimentada, con luces y de 1500 m o más
                if f is not None and rw.length >= 1500 and rw.paved and rw.lighted:
                    ils = ILS("I" + ap.ident[-3:] + end[:2], f, rw, end)
                    ils.synthetic = True
                    navaids.append(ils)
    for n in db.navaids:
        nv = navaid_from_row(n, proj, lat0, lon0)
        if nv is not None:
            navaids.append(nv)
    # edificios y bosques reales (si el servicio no responde, el escenario sigue sin ellos)
    feat_cache = os.path.join(_cache_dir(data_dir), f"feat_{key}.npz")
    buildings, forests = [], []
    try:
        if os.path.exists(feat_cache):
            z = np.load(feat_cache, allow_pickle=True)
            buildings, forests = list(z["b"]), list(z["f"])
        else:
            buildings, forests = fetch_features(data_dir, proj, progress)
            np.savez_compressed(feat_cache, b=np.array(buildings, dtype=object), f=np.array(forests, dtype=object))
    except Exception as ex:
        print("Sin edificios/bosques:", ex)
    water = None
    w_cache = os.path.join(_cache_dir(data_dir), f"agua_{key}.npz")
    try:
        if os.path.exists(w_cache):
            z = np.load(w_cache)
            water = (z["mask"], tuple(z["rect"]))
        else:
            mask, rect, found = fetch_water(data_dir, proj, progress)
            np.savez_compressed(w_cache, mask=mask, rect=np.array(rect))
            water = (mask, rect)
        if not water[0].any():
            water = None
    except Exception as ex:
        print("Sin lagos/ríos:", ex)
    freqs = db.frequencies(ident)
    name = a["name"] if center is None else f"En ruta, cerca de {(a.get('municipality') or a['name']).split('/')[0].strip()}"
    return dict(name=name, ident=ident, key=key, route=center is not None, lat0=lat0, lon0=lon0,
                magvar=local_variation(db.navaids, lat0, lon0), country=a.get("iso_country", ""), freqs=freqs,
                municipality=a.get("municipality", ""), airports=airports, navaids=navaids,
                heights=heights.astype(np.float64), sat=layers, proj=proj, buildings=buildings, forests=forests,
                water=water)


def _sample(h, north, east):
    n = h.shape[0]
    cell = 2 * HALF / (n - 1)
    i = int(np.clip(round((north + HALF) / cell), 0, n - 1))
    j = int(np.clip(round((east + HALF) / cell), 0, n - 1))
    return float(h[i, j])


def _runway_from_row(r, proj, ap_row):
    def f(k):
        try:
            return float(r[k])
        except (ValueError, KeyError, TypeError):
            return None
    la1, lo1, la2, lo2 = f("le_latitude_deg"), f("le_longitude_deg"), f("he_latitude_deg"), f("he_longitude_deg")
    length = (f("length_ft") or 0) * FT
    width = max((f("width_ft") or 0) * FT, 15.0)
    surface = (r.get("surface") or "").upper()
    if la1 is None or la2 is None or lo1 is None or lo2 is None:
        return None
    n1, e1 = proj.to_local(la1, lo1)
    n2, e2 = proj.to_local(la2, lo2)
    dn, de = float(n2 - n1), float(e2 - e1)
    dist = math.hypot(dn, de)
    if dist < 200:
        return None
    hdg = math.degrees(math.atan2(de, dn)) % 360
    length = length if length > 200 else dist
    # el umbral desplazado del CSV ya está incluido en las coordenadas de los extremos
    c = ((n1 + n2) / 2, (e1 + e2) / 2)
    le = (r.get("le_ident") or "").strip() or f"{round(hdg / 10) % 36 or 36:02d}"
    he = (r.get("he_ident") or "").strip() or f"{round(((hdg + 180) % 360) / 10) % 36 or 36:02d}"
    rw = Runway((le, he), (float(c[0]), float(c[1])), hdg, min(length, dist + 60), min(width, 70.0))
    rw.surface = surface
    rw.paved = surface_is_paved(surface)
    rw.lighted = (r.get("lighted") or "1").strip() != "0"
    return rw


UNPAVED = ("TURF", "GRS", "GRASS", "GRE", "GVL", "GRV", "GRAV", "DIRT", "EARTH", "SAND", "WATER", "CLA", "COR",
           "SNOW", "ICE", "SOIL", "LAT", "MATS")


def surface_is_paved(surface):
    """¿Asfalto/concreto? Los códigos de OurAirports son libres: se miran los comienzos de pasto, tierra, grava,
    agua, etc. Lo desconocido se toma como pavimento (como hasta ahora)."""
    s = (surface or "").upper().strip()
    return not any(s.startswith(k) for k in UNPAVED)
