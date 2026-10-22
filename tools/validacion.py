"""Validación del modelo de vuelo contra el manual (POH): un piloto robot vuela cada prueba de sim/poh.py en la
configuración del manual y compara lo medido con su tolerancia.

Uso:  python tools/validacion.py            (tabla en pantalla)
      python tools/validacion.py --json f   (además, resultados en un archivo para la guía de pruebas)

Condiciones de nivel del mar ISA: el QNH y la temperatura se ajustan para que, a la altura en que se mide, la
presión y la temperatura sean las de nivel del mar estándar (altitud de densidad 0), sin viento ni turbulencia.
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim.mathx import FT, KT, clamp, wrap180
from sim.poh import REFERENCIA
from sim.weight import DATA, LB, limits_at, reference_cg
from sim.world import World

DT = 1 / 120
GAL = 3.785411784


class PID:
    def __init__(s, kp, ki, kd, lo=-1.0, hi=1.0):
        s.kp, s.ki, s.kd, s.lo, s.hi = kp, ki, kd, lo, hi
        s.i = 0.0
        s.prev = None

    def __call__(s, err, dt):
        s.i = clamp(s.i + err * dt * s.ki, s.lo, s.hi)
        d = 0.0 if s.prev is None else (err - s.prev) / dt
        s.prev = err
        return clamp(s.kp * err + s.i + s.kd * d, s.lo, s.hi)


# ------------------------------------------------------------------ preparación
def mundo(tid, peso_lb, cg="ref", sl_en_m=None):
    """Mundo sin viento ni turbulencia, el avión al peso pedido. cg: "ref" (el de ajuste), "trasero" o "delantero"
    (límites del manual a ese peso). sl_en_m: altura MSL a la que se quieren condiciones de nivel del mar ISA."""
    w = World(tid)
    wx = w.weather
    wx.wind_kt = wx.gust_kt = 0.0
    wx.turbulence = 0.0
    wx.wind_shear = False
    wx.rain = 0.0
    wx.storm = False
    wx.qnh_hpa, wx.temp_offset = 1013.25, 0.0
    if sl_en_m is not None:
        # p(h) = 101325 Pa y T(h) = 288,15 K a esa altura
        wx.qnh_hpa = 1013.25 / (1 - 2.25577e-5 * sl_en_m) ** 5.25588
        wx.temp_offset = 0.0065 * sl_en_m
    t = w.ac.t
    fuel_kg = w.ac.sys.fuel_l * t.fuel_density
    t.payload = peso_lb * LB - t.empty_mass - fuel_kg
    if cg != "ref" and t.id in DATA:
        fwd, aft = limits_at(DATA[t.id]["env"], peso_lb)
        t.cg_ref_in = reference_cg(t)
        t.cg_in = aft if cg == "trasero" else fwd
    return w


class Velocidad:
    """Lleva una velocidad con el cabeceo, como un piloto: mueve la actitud deseada despacio (≤ 2 °/s) según el error
    de velocidad y el volante sigue esa actitud. Así no hay tirones que adelanten la pérdida."""

    def __init__(self, ac, kv=0.5, rate=2.0):
        self.pitch_cmd = math.degrees(ac.pitch)
        self.kv, self.rate = kv, rate
        self.pid = PID(0.12, 0.05, 0.03, -1.0, 1.0)

    def __call__(self, ac, v_target, dt):
        self.pitch_cmd += clamp((ac.ias_kt - v_target) * self.kv, -self.rate, self.rate) * dt
        self.pitch_cmd = clamp(self.pitch_cmd, -15.0, 25.0)
        ac.ctl_elev = self.pid(self.pitch_cmd - math.degrees(ac.pitch), dt) - 0.05 * ac.omega[1]


def nivelar(ac, dt, roll_cmd=0.0):
    """Alerones a alas niveladas (o al alabeo pedido) y timón para la bola."""
    ac.ctl_ail = clamp((roll_cmd - math.degrees(ac.roll)) * 0.05 - ac.omega[0] * 0.3, -1, 1)
    ac.ctl_rud = clamp(ac.beta * 3.0, -1, 1)


def gases(ac, v):
    for en in ac.sys.engines:
        en.throttle = v


def a_lo_largo(w, thr, d):
    """Distancia (m) a lo largo de la pista desde el umbral."""
    p = w.ac.pos
    return (p[0] - thr[0]) * d[0] + (p[1] - thr[1]) * d[1]


# ------------------------------------------------------------------ pruebas
def perdida(tid, peso, flaps_idx):
    """Velocidad (KCAS) a la que el ala entra en pérdida decelerando 1 kt/s con ralentí y alas niveladas."""
    w = mundo(tid, peso, cg="trasero")
    ac = w.ac
    gh = w.terrain.surface_height(ac.pos[0], ac.pos[1])
    ac.place_in_air(ac.pos[0], ac.pos[1], gh + 5000 * FT, ac.heading, 75, flaps_idx=flaps_idx)
    gases(ac, 0.0)
    vel = Velocidad(ac, kv=1.0, rate=3.0)
    t = 0.0
    v0 = 70.0
    while t < 120:
        target = v0 - max(0.0, t - 10.0) * 1.0         # 10 s para estabilizar y después 1 kt/s
        vel(ac, target, DT)
        nivelar(ac, DT)
        w.step(DT)
        t += DT
        if ac.stall_frac > 0.5:
            return ac.ias_kt
    return None


def ascenso(tid, peso, vy):
    """Régimen de ascenso (ft/min) a Vy con potencia máxima a nivel del mar ISA."""
    h0 = 300.0
    w = mundo(tid, peso, sl_en_m=h0)
    ac = w.ac
    ac.place_in_air(ac.pos[0], ac.pos[1], h0 - 120.0, ac.heading, vy, climb_fpm=500)
    for en in ac.sys.engines:
        en.mixture = 1.0
    gases(ac, 1.0)
    vel = Velocidad(ac)
    t, vs = 0.0, []
    while t < 75:
        vel(ac, vy, DT)
        nivelar(ac, DT)
        w.step(DT)
        t += DT
        if t > 35:                                      # ascenso estabilizado, centrado en h0
            vs.append(ac.vs_fpm)
    return sum(vs) / len(vs)


def crucero(tid, peso, alt_ft, frac):
    """(KTAS, gal/h) en vuelo nivelado a la altitud de presión dada con esa fracción de la potencia máxima,
    con la mezcla en la de mejor potencia."""
    w = mundo(tid, peso)
    ac = w.ac
    ac.place_in_air(ac.pos[0], ac.pos[1], alt_ft * FT, ac.heading, 110)
    en = ac.sys.engines[0]
    p_alt = PID(0.004, 0.0008, 0.006, -0.5, 0.5)
    p_pow = PID(1.5, 0.6, 0.0, 0.0, 1.0)
    t, tas, ff = 0.0, [], []
    while t < 240:
        _, _, rho, _ = ac.atmo.properties(ac.alt_msl)
        en.mixture = en.best_mixture(rho / 1.225)
        frac_now = en.shaft_power / ac.t.engine_power
        gases(ac, clamp(en.throttle + p_pow(frac - frac_now, DT) * DT * 2.0, 0.0, 1.0))
        ac.ctl_elev = p_alt((alt_ft * FT - ac.alt_msl) / FT, DT) - 0.05 * ac.omega[1]
        nivelar(ac, DT)
        w.step(DT)
        t += DT
        if t > 200:
            tas.append(ac.tas / KT)
            ff.append(en.fuel_flow / GAL)
    return sum(tas) / len(tas), sum(ff) / len(ff)


def planeo(tid, peso, vg):
    """Relación de planeo a la velocidad de mejor planeo con el motor parado (hélice en molinete)."""
    h0 = 1500.0
    w = mundo(tid, peso, sl_en_m=h0)
    ac = w.ac
    ac.place_in_air(ac.pos[0], ac.pos[1], h0 + 200.0, ac.heading, vg, climb_fpm=-700)
    for en in ac.sys.engines:
        en.mixture = 0.0
    gases(ac, 0.0)
    vel = Velocidad(ac)
    t, r = 0.0, []
    while t < 80:
        vel(ac, vg, DT)
        nivelar(ac, DT)
        w.step(DT)
        t += DT
        if t > 40 and ac.vs_fpm < -50:
            r.append((ac.tas / KT) * 101.27 / -ac.vs_fpm)
    return sum(r) / len(r)


def despegue(tid, peso, flaps_idx, v_lof, v_50):
    """(carrera, distancia sobre 50 ft) en ft: potencia máxima con frenos, soltarlos y despegar a v_lof."""
    w = mundo(tid, peso)
    w.reposition("pista")
    ac = w.ac
    elev = w.home.elev
    w2 = mundo(tid, peso, sl_en_m=elev)                 # mismas condiciones, con nivel del mar a la altura del campo
    w.weather.qnh_hpa, w.weather.temp_offset = w2.weather.qnh_hpa, w2.weather.temp_offset
    thr, hdg, d, r = w.runway_frame()
    ac.sys.flaps_cmd = flaps_idx
    ac.sys.flaps = float(ac.t.flap_settings[flaps_idx])
    for en in ac.sys.engines:
        en.mixture = 1.0
    gases(ac, 1.0)
    ac.brake = 1.0
    for _ in range(int(4 / DT)):                        # potencia máxima antes de soltar frenos
        w.step(DT)
    ac.brake = 0.0
    x0 = a_lo_largo(w, thr, d)
    pid = PID(0.12, 0.05, 0.03, -0.6, 0.8)
    t, roll, x50 = 0.0, None, None
    while t < 90 and x50 is None and not ac.crashed:
        he = wrap180(hdg - ac.heading)
        lat = (ac.pos[0] - thr[0]) * r[0] + (ac.pos[1] - thr[1]) * r[1]
        if ac.on_ground:
            ac.ctl_rud = clamp(he * 0.15 - lat * 0.05 + 0.05, -1, 1)
            ac.ctl_ail = clamp(-math.degrees(ac.roll) * 0.05, -1, 1)
            # rotar unos nudos antes para despegar a v_lof
            ac.ctl_elev = pid(10.0 - math.degrees(ac.pitch), DT) if ac.ias_kt > v_lof - 4 else 0.0
        else:
            if roll is None:
                roll = a_lo_largo(w, thr, d) - x0
            ac.ctl_elev = pid(clamp(6 + (ac.ias_kt - v_50) * 0.8, 0, 14) - math.degrees(ac.pitch), DT)
            nivelar(ac, DT, clamp(he, -10, 10))
            if ac.agl / FT >= 50:
                x50 = a_lo_largo(w, thr, d) - x0
        w.step(DT)
        t += DT
    return (roll / FT if roll else None), (x50 / FT if x50 else None)


def aterrizaje(tid, peso, flaps_idx, v_app, traza=None):
    """(carrera, distancia desde 50 ft) en ft: senda de 3° a v_app, ralentí desde 50 ft, frenada máxima.
    traza: lista donde anotar el vuelo cada segundo (diagnóstico)."""
    w = mundo(tid, peso)
    w.reposition("pista")
    elev = w.home.elev
    w2 = mundo(tid, peso, sl_en_m=elev)
    w.weather.qnh_hpa, w.weather.temp_offset = w2.weather.qnh_hpa, w2.weather.temp_offset
    ac = w.ac
    thr, hdg, d, r = w.runway_frame()
    aim = 150.0                                          # punto de toma, m después del umbral
    back = 1200.0
    x, y = thr[0] - d[0] * back, thr[1] - d[1] * back
    h = elev + (back + aim) * math.tan(math.radians(3.0))
    ac.place_in_air(x, y, h, hdg, v_app, flaps_idx=flaps_idx, climb_fpm=-v_app * 101.27 * math.tan(math.radians(3)))
    pid_v = PID(0.08, 0.03, 0.0, 0.0, 1.0)
    pid_p = PID(0.12, 0.05, 0.03, -0.8, 0.8)
    t, x50, xtd, stop = 0.0, None, None, None
    phase = "senda"
    path_pitch = math.degrees(ac.pitch)
    while t < 150 and stop is None and not ac.crashed:
        along = a_lo_largo(w, thr, d)
        he = wrap180(hdg - ac.heading)
        lat = (ac.pos[0] - thr[0]) * r[0] + (ac.pos[1] - thr[1]) * r[1]
        # altura sobre la pista (el terreno antes del umbral puede estar más alto o más bajo que ella)
        hgt_ft = (ac.alt_msl - elev) / FT
        h_path = elev + (aim - along) * math.tan(math.radians(3.0))
        # senda: velocidad vertical de la senda corregida por la desviación; la actitud la sigue despacio
        vs_target = -ac.gs / KT * 101.27 * math.tan(math.radians(3.0)) + (h_path - ac.alt_msl) * 25.0
        path_pitch = clamp(path_pitch + clamp((vs_target - ac.vs_fpm) * 0.01, -2.0, 2.0) * DT, -8, 10)
        if phase == "senda":
            # cabeceo para la senda, gases para la velocidad
            ac.ctl_elev = pid_p(path_pitch - math.degrees(ac.pitch), DT)
            gases(ac, pid_v(v_app - ac.ias_kt, DT))
            nivelar(ac, DT, clamp(he * 1.5 - lat * 0.05, -10, 10))
            if hgt_ft <= 50:
                x50 = along
                phase = "recogida"
        elif phase == "recogida":
            gases(ac, 0.0)
            # sigue la senda hasta 20 ft y después redondea para tocar con poca velocidad vertical
            agl_ft = ac.agl / FT
            pitch_cmd = path_pitch if agl_ft > 20 else clamp(7.0 - agl_ft * 0.25, 2, 7)
            ac.ctl_elev = pid_p(pitch_cmd - math.degrees(ac.pitch), DT)
            nivelar(ac, DT, clamp(he * 1.5 - lat * 0.05, -5, 5))
            if ac.on_ground:
                xtd = along
                phase = "frenada"
        else:
            gases(ac, 0.0)
            # volante atrás sin llegar a tocar la cola (cabeceo ≤ 4°) y frenada máxima
            ac.ctl_elev = pid_p(min(4.0, math.degrees(ac.pitch)) - 0.5 - math.degrees(ac.pitch), DT) + 0.3
            ac.brake = 1.0
            ac.ctl_rud = clamp(he * 0.15 - lat * 0.05, -1, 1)
            ac.ctl_ail = 0.0
            if ac.gs / KT < 1.0:
                stop = along
        if traza is not None and int((t + DT) / 1.0) != int(t / 1.0):
            traza.append(f"t={t:5.1f} {phase:9s} h={hgt_ft:6.1f} agl={ac.agl / FT:6.1f} ias={ac.ias_kt:5.1f} x={along:7.1f} "
                         f"pitch={math.degrees(ac.pitch):5.1f} vs={ac.vs_fpm:5.0f} gs={ac.gs / KT:5.1f} {ac.crash_reason}")
        w.step(DT)
        t += DT
    if traza is not None:
        traza.append(f"fin: t={t:.1f} fase={phase} choque={ac.crashed} {ac.crash_reason}")
    if stop is None or x50 is None or xtd is None:
        return None, None
    return (stop - xtd) / FT, (stop - x50) / FT


# ------------------------------------------------------------------ conjunto
def medir(ref=REFERENCIA):
    """Vuela todas las pruebas y devuelve las filas con lo medido y si está dentro de tolerancia."""
    tid, peso = ref["avion"], ref["peso_lb"]
    from sim.aircraft_data import AIRCRAFT
    v = AIRCRAFT[tid]().v
    med = {}
    med["perdida_limpio"] = perdida(tid, peso, 0)
    med["perdida_flaps30"] = perdida(tid, peso, 3)
    med["ascenso"] = ascenso(tid, peso, v["vy"])
    med["crucero_tas"], med["crucero_consumo"] = crucero(tid, peso, 8000, 0.75)
    med["planeo_relacion"] = planeo(tid, peso, v["vglide"])
    med["despegue_carrera"], med["despegue_50ft"] = despegue(tid, peso, 1, 51, 56)
    med["aterrizaje_carrera"], med["aterrizaje_50ft"] = aterrizaje(tid, peso, 3, 61)
    filas = []
    for p in ref["pruebas"]:
        m = med.get(p["id"])
        m = None if m is None else float(m)               # numpy → número normal (para guardarlo en JSON)
        tol = p["tol"] * p["poh"] if p.get("rel") else p["tol"]
        ok = bool(m is not None and abs(m - p["poh"]) <= tol)
        filas.append(dict(p, medido=m, tol_abs=tol, ok=ok))
    return filas


def tabla(filas):
    print(f"{'Prueba':42s} {'POH':>9s} {'medido':>9s} {'tolerancia':>12s}  resultado")
    for f in filas:
        m = "—" if f["medido"] is None else f"{f['medido']:.1f}"
        tol = f"±{f['tol'] * 100:.0f} %" if f.get("rel") else f"±{f['tol']:g}"
        print(f"{f['titulo']:42s} {f['poh']:9.1f} {m:>9s} {tol:>12s}  {'dentro' if f['ok'] else 'FUERA'} {f['magnitud']}")


if __name__ == "__main__":
    filas = medir()
    tabla(filas)
    if "--json" in sys.argv:
        with open(sys.argv[sys.argv.index("--json") + 1], "w", encoding="utf-8") as fh:
            json.dump(filas, fh, ensure_ascii=False, indent=1)
    bad = [f["titulo"] for f in filas if not f["ok"]]
    print("\nFUERA DE TOLERANCIA: " + "; ".join(bad) if bad else "\nTODAS DENTRO DE TOLERANCIA")
