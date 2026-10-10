"""Posición real del Sol y de la Luna (y la fase lunar) para una fecha, hora local y lugar.

Algoritmos de baja precisión (NOAA para el Sol, términos principales de la órbita lunar): errores de unos
minutos de arco, de sobra para ver el amanecer, el atardecer y la Luna en el cielo del simulador.
"""
import datetime as _dt
import math

# huso horario de los países con escenarios frecuentes (horas respecto a UTC, sin horario de verano)
TZ = {"VE": -4.0, "CO": -5.0, "PE": -5.0, "EC": -5.0, "MX": -6.0, "PA": -5.0, "DO": -4.0, "CU": -5.0, "AR": -3.0,
      "CL": -4.0, "BR": -3.0, "UY": -3.0, "PY": -4.0, "BO": -4.0, "ES": 1.0, "PT": 0.0, "FR": 1.0, "GB": 0.0,
      "US": -5.0}


def tz_for(country, lon):
    return TZ.get(country, round(lon / 15.0))


def sun_position(lat, lon, day_of_year, hour_local, tz):
    """Elevación y azimut (grados, azimut desde el norte en sentido horario) del Sol."""
    g = 2 * math.pi / 365.0 * (day_of_year - 1 + (hour_local - 12) / 24.0)
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g) - 0.014615 * math.cos(2 * g)
                    - 0.040849 * math.sin(2 * g))
    tst = hour_local * 60.0 + eqt + 4.0 * lon - 60.0 * tz
    ha = math.radians(tst / 4.0 - 180.0)
    la = math.radians(lat)
    cz = math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha)
    el = math.degrees(math.asin(max(-1.0, min(1.0, cz))))
    az = math.degrees(math.atan2(math.sin(ha), math.cos(ha) * math.sin(la) - math.tan(decl) * math.cos(la))) + 180.0
    return el, az % 360.0


def _days_j2000(utc):
    return (utc - _dt.datetime(2000, 1, 1, 12, 0)).total_seconds() / 86400.0


def moon_position(lat, lon, utc):
    """Elevación, azimut (grados) y fracción iluminada (0 = luna nueva, 1 = llena) de la Luna."""
    d = _days_j2000(utc)
    rad = math.radians
    L = rad((218.316 + 13.176396 * d) % 360)
    M = rad((134.963 + 13.064993 * d) % 360)
    F = rad((93.272 + 13.229350 * d) % 360)
    lam = L + rad(6.289) * math.sin(M)              # longitud eclíptica
    beta = rad(5.128) * math.sin(F)                 # latitud eclíptica
    eps = rad(23.439)
    ra = math.atan2(math.sin(lam) * math.cos(eps) - math.tan(beta) * math.sin(eps), math.cos(lam))
    dec = math.asin(math.sin(beta) * math.cos(eps) + math.cos(beta) * math.sin(eps) * math.sin(lam))
    gmst = rad((280.46061837 + 360.98564736629 * d) % 360)
    ha = gmst + rad(lon) - ra
    la = rad(lat)
    alt = math.asin(math.sin(la) * math.sin(dec) + math.cos(la) * math.cos(dec) * math.cos(ha))
    az = math.atan2(-math.sin(ha), math.tan(dec) * math.cos(la) - math.sin(la) * math.cos(ha))
    # fase: elongación respecto al Sol
    gs = rad((357.529 + 0.98560028 * d) % 360)
    lam_s = rad((280.459 + 0.98564736 * d) % 360) + rad(1.915) * math.sin(gs) + rad(0.020) * math.sin(2 * gs)
    elong = math.acos(max(-1.0, min(1.0, math.cos(beta) * math.cos(lam - lam_s))))
    illum = (1 - math.cos(elong)) / 2
    return math.degrees(alt), math.degrees(az) % 360.0, illum


def sky(lat, lon, country, date, hour_local):
    """Sol y Luna para el simulador: (sol_el, sol_az, luna_el, luna_az, luna_iluminada)."""
    tz = tz_for(country, lon)
    doy = date.timetuple().tm_yday
    se, sa = sun_position(lat, lon, doy, hour_local, tz)
    utc = _dt.datetime(date.year, date.month, date.day) + _dt.timedelta(hours=hour_local - tz)
    me, ma, k = moon_position(lat, lon, utc)
    return se, sa, me, ma, k
