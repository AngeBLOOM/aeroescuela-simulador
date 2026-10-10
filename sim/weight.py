"""Peso y balance y rendimiento de despegue/aterrizaje (valores típicos de los manuales POH/AFM).

Las cifras son representativas de cada modelo; para un avión real use siempre su propio manual y
su hoja de peso y centrado. Unidades: kg y metros respecto al plano de referencia (datum) del POH.
"""
import math

from .mathx import FT

LB = 0.45359237
IN = 0.0254

# estaciones: (clave, nombre, brazo en pulgadas, máx kg)  ·  envolvente: [(peso_lb, cg_delantero, cg_trasero)]
DATA = {
    "c172": dict(bew_lb=1663, bew_arm=39.2, mtow_lb=2550, mlw_lb=2550,
                 stations=[("front", "Piloto y copiloto", 37.0, 180), ("rear", "Asientos traseros", 73.0, 180),
                           ("bag", "Equipaje", 95.0, 54)],
                 fuel_arm=48.0,
                 env=[(1500, 35.0, 47.3), (1950, 35.0, 47.3), (2550, 41.0, 47.3)],
                 to_roll_ft=960, to_50_ft=1630, ldg_roll_ft=575, ldg_50_ft=1335),
    "c152": dict(bew_lb=1129, bew_arm=30.7, mtow_lb=1670, mlw_lb=1670,
                 stations=[("front", "Piloto y alumno", 39.0, 180), ("rear", "(sin asientos traseros)", 39.0, 0),
                           ("bag", "Equipaje", 64.0, 54)],
                 fuel_arm=42.0,
                 env=[(1100, 31.0, 36.5), (1350, 31.0, 36.5), (1670, 32.65, 36.5)],
                 to_roll_ft=725, to_50_ft=1340, ldg_roll_ft=475, ldg_50_ft=1200),
    "pa28w": dict(bew_lb=1500, bew_arm=86.5, mtow_lb=2440, mlw_lb=2440,
                  stations=[("front", "Piloto y copiloto", 80.5, 180), ("rear", "Asientos traseros", 118.1, 180),
                            ("bag", "Equipaje", 142.8, 90)],
                  fuel_arm=95.0,
                  env=[(1500, 83.0, 93.0), (1950, 83.0, 93.0), (2440, 87.0, 93.0)],
                  to_roll_ft=975, to_50_ft=1650, ldg_roll_ft=595, ldg_50_ft=1160),
    "sr20": dict(bew_lb=2150, bew_arm=140.0, mtow_lb=3050, mlw_lb=2900,
                 stations=[("front", "Piloto y copiloto", 143.5, 200), ("rear", "Asientos traseros", 180.0, 200),
                           ("bag", "Equipaje", 208.0, 59)],
                 fuel_arm=153.75,
                 env=[(2110, 138.7, 148.1), (2700, 139.9, 148.1), (3050, 141.4, 148.1)],
                 to_roll_ft=1050, to_50_ft=1700, ldg_roll_ft=900, ldg_50_ft=1650),
    "pa28r": dict(bew_lb=1653, bew_arm=86.0, mtow_lb=2750, mlw_lb=2750,
                  stations=[("front", "Piloto y copiloto", 80.5, 180), ("rear", "Asientos traseros", 118.1, 180),
                            ("bag", "Equipaje", 142.8, 90)],
                  fuel_arm=95.0,
                  env=[(1600, 80.0, 93.0), (2375, 80.0, 93.0), (2750, 87.0, 93.0)],
                  to_roll_ft=1050, to_50_ft=1600, ldg_roll_ft=780, ldg_50_ft=1430),
    "da40": dict(bew_lb=1984, bew_arm=96.0, mtow_lb=2645, mlw_lb=2535,
                 stations=[("front", "Piloto y copiloto", 90.6, 180), ("rear", "Asientos traseros", 128.0, 180),
                           ("bag", "Equipaje", 143.7, 30)],
                 fuel_arm=103.5,
                 env=[(1720, 94.5, 102.4), (2161, 94.5, 102.4), (2645, 97.6, 102.4)],
                 to_roll_ft=1180, to_50_ft=1720, ldg_roll_ft=850, ldg_50_ft=1660),
    "da42": dict(bew_lb=3240, bew_arm=95.0, mtow_lb=3935, mlw_lb=3740,
                 stations=[("front", "Piloto y copiloto", 90.6, 200), ("rear", "Asientos traseros", 128.0, 200),
                           ("bag", "Equipaje", 143.7, 30)],
                 fuel_arm=103.5,
                 env=[(2800, 93.5, 98.0), (3400, 93.5, 98.0), (3935, 94.9, 98.0)],
                 to_roll_ft=1150, to_50_ft=2000, ldg_roll_ft=1150, ldg_50_ft=2230),
}


def limits_at(env, w_lb):
    """CG delantero y trasero permitidos para un peso (interpolando la envolvente)."""
    if w_lb <= env[0][0]:
        return env[0][1], env[0][2]
    for (w0, f0, a0), (w1, f1, a1) in zip(env, env[1:]):
        if w_lb <= w1:
            k = (w_lb - w0) / (w1 - w0)
            return f0 + (f1 - f0) * k, a0 + (a1 - a0) * k
    return env[-1][1], env[-1][2]


class WeightBalance:
    def __init__(self, type_id):
        self.type_id = type_id if type_id in DATA else "c172"
        self.d = DATA[self.type_id]
        self.loads = {"front": 160.0, "rear": 0.0, "bag": 10.0}        # kg

    def compute(self, fuel_l, fuel_density):
        d = self.d
        w = d["bew_lb"]
        mom = d["bew_lb"] * d["bew_arm"]
        for key, _n, arm, _mx in d["stations"]:
            lb = self.loads.get(key, 0.0) / LB
            w += lb
            mom += lb * arm
        fuel_lb = fuel_l * fuel_density / LB
        w += fuel_lb
        mom += fuel_lb * d["fuel_arm"]
        cg = mom / w
        fwd, aft = limits_at(d["env"], w)
        return dict(w_lb=w, w_kg=w * LB, cg=cg, fwd=fwd, aft=aft, mtow_lb=d["mtow_lb"],
                    ok_w=w <= d["mtow_lb"], ok_cg=fwd <= cg <= aft,
                    ok_bag=self.loads.get("bag", 0) <= dict((k, mx) for k, _n, _a, mx in d["stations"])["bag"])

    def apply(self, t, fuel_l):
        """Pone el peso y el centrado en el modelo de vuelo: masa total = vacío + carga + combustible, y el CG,
        que cambia la estabilidad y la fuerza de profundidad (sim/flightmodel.py, cg_dx)."""
        r = self.compute(fuel_l, t.fuel_density)
        t.payload = max(0.0, r["w_kg"] - fuel_l * t.fuel_density - t.empty_mass)
        t.cg_ref_in = reference_cg(t)
        t.cg_in = r["cg"]
        return r


def reference_cg(t):
    """CG (pulgadas desde el datum) con que se ajustó el modelo de vuelo: la carga por defecto (piloto e instructor,
    10 kg de equipaje) con 3/4 de combustible, como empieza cada vuelo."""
    return WeightBalance(t.id).compute(t.fuel_capacity * 0.75, t.fuel_density)["cg"]

    def performance(self, w_lb, field_elev_ft, qnh_hpa, oat_c, headwind_kt, grass=False):
        """Distancias de despegue y aterrizaje (ft) corregidas por altitud de presión, temperatura,
        peso, viento y superficie (regla práctica de los POH)."""
        d = self.d
        pa = field_elev_ft + (1013.25 - qnh_hpa) * 30.0
        isa = 15.0 - 1.98 * pa / 1000.0
        da = pa + 120.0 * (oat_c - isa)
        f_alt = 1.0 + 0.12 * max(0.0, da) / 1000.0
        f_w = (w_lb / d["mtow_lb"]) ** 2
        f_wind = 1.0 - 0.10 * headwind_kt / 9.0 if headwind_kt >= 0 else 1.0 - 0.10 * headwind_kt / 2.0
        f_g = 1.15 if grass else 1.0
        k = f_alt * f_w * max(0.4, f_wind)
        return dict(pa=pa, da=da,
                    to_roll=d["to_roll_ft"] * k * f_g, to_50=d["to_50_ft"] * k * f_g,
                    ldg_roll=d["ldg_roll_ft"] * (1 + 0.04 * max(0, da) / 1000) * max(0.4, f_wind) * f_g,
                    ldg_50=d["ldg_50_ft"] * (1 + 0.04 * max(0, da) / 1000) * max(0.4, f_wind) * f_g)
