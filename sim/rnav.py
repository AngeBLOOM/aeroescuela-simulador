"""Aproximaciones RNAV (GPS) de entrenamiento, generadas para cada pista.

No hay datos publicados gratuitos de los procedimientos de Venezuela, así que cada pista recibe una aproximación
RNAV estándar en «T» (como las de la OACI y la FAA), marcada siempre como DE ENTRENAMIENTO, NO PUBLICADA:

          IAF izq ─── IF ─── IAF der        (4 NM a cada lado del IF, perpendiculares al final)
                       │
                       │  9 NM del umbral: IF, tramo intermedio nivelado
                       │
                      FAF                   5 NM: inicio del descenso por la senda de 3°
                       │
                      MAP                   umbral de la pista (RWxx), 50 ft de altura de cruce
                       │
                      MAH                   espera de la frustrada, 5 NM más allá por el eje

Alturas sobre el umbral: IAF e IF 2500 ft, FAF por la senda (~1600 ft), mínimos LPV a 250 ft (altura de decisión)
y LNAV a 450 ft (altura mínima de descenso). La senda vertical (como la del ILS) va del umbral a 50 ft hacia
arriba con 3°; la desviación lateral, con la escala de aproximación de 0,3 NM desde 2 NM antes del FAF.
"""
import math
from types import SimpleNamespace

import numpy as np

from .mathx import FT, NM

GP_DEG = 3.0                 # ángulo de la senda
TCH_FT = 50.0                # altura de cruce del umbral
IF_NM, FAF_NM, IAF_SIDE_NM, MAH_NM = 9.0, 5.0, 4.0, 5.0
IAF_AGL_FT = 2500.0
DA_LPV_FT, MDA_LNAV_FT = 250.0, 450.0


def fix(ident, pos, kind, name, alt_ft=None, role=""):
    from .gps import Waypoint
    w = Waypoint(ident, pos, kind, name)
    w.alt_ft = alt_ft            # altitud MSL a cruzar (None: sin restricción)
    w.role = role                # "IAF", "IF", "FAF", "MAP", "MAH"
    return w


def build(airport, runway, end):
    """La aproximación RNAV de entrenamiento a la pista 'end' de 'airport'. Devuelve un objeto con: title,
    fixes (IAF izq, IAF der, IF, FAF, MAP, MAH), legs(iaf) (la secuencia a volar desde un IAF o desde el IF),
    threshold, course (verdadero), elev_ft, da_ft, mda_ft."""
    thr, hdg, d = runway.end(end)
    thr = np.array(thr, dtype=float)
    d = np.array(d, dtype=float)
    r = np.array([-d[1], d[0]])                  # a la derecha del final
    elev_ft = airport.elev / FT
    code = f"{airport.ident[:3]}{end}"[:5]

    def at(nm_before, lat_nm=0.0):
        return thr - d * nm_before * NM + r * lat_nm * NM

    faf_alt = elev_ft + TCH_FT + FAF_NM * NM / FT * math.tan(math.radians(GP_DEG))
    iaf_alt = elev_ft + IAF_AGL_FT
    fx = SimpleNamespace(
        iaf_l=fix(f"{code}L", at(IF_NM, -IAF_SIDE_NM), "USR", "IAF izquierdo", iaf_alt, "IAF"),
        iaf_r=fix(f"{code}R", at(IF_NM, IAF_SIDE_NM), "USR", "IAF derecho", iaf_alt, "IAF"),
        if_=fix(f"{code}I", at(IF_NM), "USR", "IF", iaf_alt, "IF"),
        faf=fix(f"{code}F", at(FAF_NM), "USR", "FAF", faf_alt, "FAF"),
        map=fix(f"RW{end}", thr, "USR", f"Umbral {end}", elev_ft + TCH_FT, "MAP"),
        mah=fix(f"{code}M", thr + d * MAH_NM * NM, "USR", "Espera de la frustrada", iaf_alt, "MAH"),
    )

    def legs(iaf=None):
        """Secuencia del procedimiento. iaf: "L", "R" o None (vectores al IF)."""
        first = {"L": [fx.iaf_l], "R": [fx.iaf_r]}.get(iaf, [])
        return first + [fx.if_, fx.faf, fx.map, fx.mah]

    return SimpleNamespace(
        title=f"RNAV (GPS) {end} · {airport.ident} · ENTRENAMIENTO, NO PUBLICADA",
        short=f"RNAV {end} {airport.ident}", airport=airport, runway=runway, end=end,
        fixes=fx, legs=legs, threshold=thr, dir=d, course=hdg, elev_ft=elev_ft,
        da_ft=elev_ft + DA_LPV_FT, mda_ft=elev_ft + MDA_LNAV_FT, gp_deg=GP_DEG, tch_ft=TCH_FT)


def entry(apr, pos):
    """Cómo unirse a la aproximación desde 'pos': (iaf, primer punto). Alineado con el final (a menos de 3 NM del eje,
    antes del umbral) se va al siguiente punto por delante: el IF si está detrás de él, si no el FAF o el umbral
    (como un G1000 con vectores al final). Si no, el IAF del lado por el que llega."""
    rel = np.array(pos[:2], dtype=float) - apr.threshold
    back = -float(np.dot(rel, apr.dir)) / NM          # NM antes del umbral
    lat = float(rel[0] * -apr.dir[1] + rel[1] * apr.dir[0]) / NM
    if abs(lat) < 3.0 and back > 0.3:
        if back > IF_NM + 1.0:
            return None, "IF"
        if back > FAF_NM + 0.5:
            return None, "FAF"
        return None, "MAP"
    return ("R" if lat > 0 else "L"), "IAF"


def best_iaf(apr, pos):
    """El IAF del lado por el que llega el avión, o None si viene alineado con el final (vectores)."""
    return entry(apr, pos)[0]


def for_world(world):
    """Todas las aproximaciones RNAV de entrenamiento del escenario: una por cada extremo de pista."""
    out = []
    for apt in world.airports:
        for rw in apt.runways:
            for end in rw.idents:
                out.append(build(apt, rw, end))
    return out
