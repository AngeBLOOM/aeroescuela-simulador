"""Modelo de vuelo de 6 grados de libertad.

Integra un cuerpo rígido con aerodinámica no lineal (pérdida, efecto suelo,
flaps), hélice con efecto de torque y factor P, estela de la hélice sobre los
mandos, tren de aterrizaje con amortiguadores y fricción, y detección de
aterrizajes duros e impactos.
"""
import math

import numpy as np

from .mathx import (G, KT, FPM, clamp, cross, length, quat_from_euler, quat_integrate,
                    quat_to_euler, quat_to_mat, vec)
from .systems import Systems


def stall_blend(alpha, a0, M=55.0):
    """Función sigmoide simétrica de Beard & McLain (0 = adherido, 1 = desprendido)."""
    e1 = math.exp(clamp(-M * (alpha - a0), -50, 50))
    e2 = math.exp(clamp(M * (alpha + a0 * 0.85), -50, 50))
    return (1 + e1 + e2) / ((1 + e1) * (1 + e2))


SURFACE = {
    "asfalto": dict(roll=0.015, brake=0.65, lat=0.85),
    "cesped": dict(roll=0.055, brake=0.38, lat=0.6),
    "agua": dict(roll=0.5, brake=0.0, lat=0.5),
}


class Aircraft:
    def __init__(self, t, terrain, atmo):
        self.t = t
        self.terrain = terrain
        self.atmo = atmo
        self.sys = Systems(t)
        self.pos = vec()
        self.vel = vec()
        self.q = quat_from_euler(0, 0, 0)
        self.omega = vec()
        # mandos del piloto (-1..1); elevador +1 = tirar (nariz arriba)
        self.ctl_elev = 0.0
        self.ctl_ail = 0.0
        self.ctl_rud = 0.0
        self.trim = 0.0
        self.brake = 0.0                 # ambos frenos (teclado, botón)
        self.brake_l = self.brake_r = 0.0  # frenos de pie por separado (pedales): se suman a brake en su lado
        # superficies (rad)
        self.de = self.da = self.dr = 0.0
        self.time = 0.0
        self.crashed = False
        self.crash_reason = ""
        self.events = []
        self._contact_prev = {}
        self.on_ground = False
        self.gear_contact = {}
        self.gear_load = {}
        self.max_g = 1.0
        self.min_g = 1.0
        self.overstress = False
        self._cg_dx = 0.0
        self._alpha_prev = None
        self._adot = 0.0
        self._pg, self._wf, self._vf = 0.0, None, None     # turbulencia de giro
        self.spin, self.spin_dir = 0.0, 0.0                # barrena: intensidad 0..1 y sentido (+ = derecha)
        self._pro_t = 0.0
        self._update_outputs(np.zeros(3), 0.0)

    # --------------------------------------------------------------- posición
    def reset_state(self):
        self.crashed = False
        self.crash_reason = ""
        self.events.clear()
        self.omega = vec()
        self.ctl_elev = self.ctl_ail = self.ctl_rud = 0.0
        self.de = self.da = self.dr = 0.0
        self.brake = 0.0
        self.brake_l = self.brake_r = 0.0
        self.max_g = self.min_g = 1.0
        self.overstress = False
        self._alpha_prev = None
        self._adot = 0.0
        self._pg, self._wf, self._vf = 0.0, None, None
        self.spin, self.spin_dir = 0.0, 0.0
        self._pro_t = 0.0
        self._contact_prev = {}
        self.ditched = False
        self.soft_field = False

    def place_on_ground(self, x, y, heading_deg):
        self.reset_state()
        h, _ = self.terrain.surface(x, y)
        static = 0.055
        gz = max(g.pos[2] for g in self.t.gears)
        self.pos = vec(x, y, -(h + gz - static))
        self.vel = vec()
        self.q = quat_from_euler(0.0, 0.0, math.radians(heading_deg))
        self.trim = 0.25
        self.sys.flaps_cmd = 0
        self.sys.flaps = 0.0
        self.sys.gear_down = True
        self.sys.gear_pos = 1.0
        self.on_ground = True
        self._contact_prev = {g.name: True for g in self.t.gears}
        self._update_outputs(np.zeros(3), 0.0)

    def place_in_air(self, x, y, alt_msl, heading_deg, ias_kt, flaps_idx=0, gear_down=None, climb_fpm=0.0):
        self.reset_state()
        t = self.t
        self.sys.flaps_cmd = flaps_idx
        self.sys.flaps = float(t.flap_settings[flaps_idx])
        if gear_down is None:
            gear_down = not t.retractable
        self.sys.gear_down = gear_down
        self.sys.gear_pos = 1.0 if gear_down else 0.0
        _, _, rho, _ = self.atmo.properties(alt_msl)
        V = ias_kt * KT * math.sqrt(1.225 / rho)
        alpha, trim, thr = self.trim_solution(V, rho, climb_fpm * FPM)
        gamma = math.asin(clamp(climb_fpm * FPM / V, -0.5, 0.5))
        hdg = math.radians(heading_deg)
        self.pos = vec(x, y, -alt_msl)
        self.q = quat_from_euler(0.0, alpha + gamma, hdg)
        wind = self.atmo.wind_at(500.0)
        self.vel = vec(V * math.cos(gamma) * math.cos(hdg), V * math.cos(gamma) * math.sin(hdg),
                       -V * math.sin(gamma)) + wind
        self.trim = trim
        for en in self.sys.engines:
            en.throttle = thr
            en.pf = thr
        self.on_ground = False
        self._contact_prev = {}
        self.rho = rho
        self._update_outputs(np.zeros(3), V)

    def trim_solution(self, V, rho, climb_ms=0.0):
        """Calcula alfa, compensador y gases para vuelo equilibrado a velocidad V."""
        t = self.t
        m = self.sys.mass
        ff = self.sys.flaps / max(t.flap_settings)
        qbar = 0.5 * rho * V * V
        gamma = math.asin(clamp(climb_ms / V, -0.5, 0.5))
        CL = m * G * math.cos(gamma) / (qbar * t.S)
        alpha = (CL - t.CL0 - t.CL_flaps * ff) / t.CLa
        k = 1.0 / (math.pi * t.e * t.AR)
        CD = t.CD0 + t.CD_flaps * ff ** 1.4 + t.CD_gear * self.sys.gear_pos + k * CL * CL
        drag = qbar * t.S * CD + m * G * math.sin(gamma)
        # gases: empuje = eta*P/sqrt(V2+Vc2)
        sigma = rho / 1.225
        dens = max(0.05, sigma - (1 - sigma) / 7.55)
        n_eng = len(t.engines_y)
        pf = drag * math.sqrt(V * V + t.prop_vc ** 2) / (t.prop_eff * t.engine_power * n_eng)
        thr = clamp((pf / dens - 0.025) / 0.975, 0.0, 1.0)
        T = t.prop_eff * t.engine_power * n_eng * pf / math.sqrt(V * V + t.prop_vc ** 2)
        qc = qbar + t.slipstream * max(T, 0)
        Cm = t.Cm0 + t.Cma * alpha + t.Cm_flaps * ff + CL * self.cg_dx() / t.c
        de = -Cm * qbar / (t.Cmde * qc)
        trim = clamp(-de / t.trim_range, -1.0, 1.0)
        return alpha, trim, thr

    def _rot_gusts(self, dt, R, V):
        """Turbulencia de giro (Dryden, MIL-F-8785C): ráfagas de alabeo, cabeceo y guiñada (rad/s) que el avión
        siente como si el aire girase. La de alabeo es un proceso propio; las de cabeceo y guiñada salen de cómo cambia
        la ráfaga vertical y lateral a lo largo del avión."""
        at = self.atmo
        lvl = getattr(at, "turb_level", 0.0)
        if lvl < 0.01 or V < 15.0 or self.on_ground:
            self._pg *= 0.9
            self._wf = self._vf = None
            return self._pg, 0.0, 0.0
        b = self.t.b
        g = R.T @ at.turb                                   # ráfaga en ejes del avión
        tq, tr, tp = 4 * b / (math.pi * V), 3 * b / (math.pi * V), 4 * b / (math.pi * V)
        if self._wf is None:
            self._wf, self._vf = g[2], g[1]
        self._wf += (g[2] - self._wf) * min(1.0, dt / tq)
        self._vf += (g[1] - self._vf) * min(1.0, dt / tr)
        qg = -(g[2] - self._wf) / (V * tq)
        rg = (g[1] - self._vf) / (V * tr)
        sig_p = at.sig_w * math.sqrt(0.8 / V) * (math.pi / (4 * b)) ** (1 / 6) / max(at.L_w, 30.0) ** (1 / 3)
        a = math.exp(-dt / tp)
        self._pg = a * self._pg + sig_p * math.sqrt(1 - a * a) * at.rng.gauss(0, 1)
        return self._pg, qg, rg

    def _spin_update(self, dt, sb, alpha=0.0, a_st=1.0):
        """Barrena: con el ala en pérdida, palanca atrás y guiñada pro-barrena (pedal hacia el lado del giro), una
        semiala entra más en pérdida que la otra y el avión autorrota. Se mantiene mientras siga en pérdida con la
        palanca atrás; se recupera con el procedimiento PARE: potencia a ralentí, alerones neutros, pedal contrario y
        palanca adelante (1 a 1,5 vueltas). Devuelve la intensidad 0..1."""
        r = self.omega[2]
        ce = self.ctl_elev
        if self.spin_dir == 0:
            # hace falta mantener el pedal casi a fondo hacia el lado del giro (0,8 s) con el ala en pérdida y la
            # palanca atrás: una pérdida coordinada no entra en barrena
            stalled_in = sb > 0.5 or abs(alpha) > a_st
            if stalled_in and abs(self.ctl_rud) > 0.6 and ce > 0.4 and not self.on_ground:
                self._pro_t += dt
            else:
                self._pro_t = 0.0
            if self._pro_t > 0.8:                         # la barrena gira hacia el lado del pedal
                self.spin_dir = 1.0 if self.ctl_rud > 0 else -1.0
                self.spin = 0.05
                self._pro_t = 0.0
            return 0.0
        pro = self.ctl_rud * self.spin_dir
        k = self.spin
        stalled = sb > 0.3 or abs(alpha) > 0.85 * a_st     # cerca de la pérdida (alfa oscila en el borde)
        if stalled and ce > 0.3:
            k += dt * (0.30 + 0.25 * max(pro, 0.0))       # barrena desarrollada en ~3 s
        else:
            k -= dt * 0.10
        if pro < -0.3:
            k -= dt * 0.25 * -pro                           # pedal contrario
        if ce < 0.1:
            k -= dt * 0.20                                  # palanca adelante
        if sb < 0.1 and abs(alpha) < 0.6 * a_st:
            k -= dt * 0.2                                   # el ala vuelve a volar
        if self.on_ground:
            k = 0.0
        self.spin = clamp(k, 0.0, 1.0)
        if self.spin <= 0.0:
            self.spin_dir = 0.0
        return self.spin

    def cg_dx(self):
        """Cuánto está el CG por detrás (m, + = atrás) del CG con que se ajustó el modelo, según el peso y
        balance cargado (sim/weight.py). Sin hoja de carga es 0 y el avión vuela como siempre."""
        cg = getattr(self.t, "cg_in", None)
        return 0.0 if cg is None else (cg - self.t.cg_ref_in) * 0.0254

    # -------------------------------------------------------------- dinámica
    def step(self, dt):
        if self.crashed:
            self.vel *= 0.0
            self.omega *= 0.0
            return
        t = self.t
        s = self.sys
        e = s.engine
        self.time += dt

        R = quat_to_mat(self.q)
        alt = -self.pos[2]
        T_k, p_amb, rho, a_snd = self.atmo.properties(alt)
        ground_h, surf = self.terrain.surface(self.pos[0], self.pos[1])
        agl = alt - ground_h

        wind = self.atmo.wind_at(max(agl - 1.0, 0.5))
        v_air = self.vel - wind
        vb = R.T @ v_air
        V = length(vb)
        u, v, w = vb
        if V > 0.3:
            alpha = math.atan2(w, u)
            beta = math.asin(clamp(v / V, -1.0, 1.0))
        else:
            alpha = beta = 0.0
        self.alpha = alpha
        self.beta = beta
        self.rho = rho
        self.p_amb = p_amb
        self.temp_k = T_k

        s.oat_c = T_k - 273.15                       # para el hielo en el carburador
        s.dew_spread = self.atmo.moisture_spread() if hasattr(self.atmo, "moisture_spread") else 8.0
        s.update(dt, rho, p_amb, max(u, 0.0), self.on_ground)

        # actuadores
        ce = clamp(self.ctl_elev, -1, 1)
        de_cmd = -ce * (t.elev_up if ce > 0 else t.elev_down)
        da_cmd = clamp(self.ctl_ail, -1, 1) * t.ail_max
        dr_cmd = clamp(self.ctl_rud, -1, 1) * t.rud_max
        k_act = min(1.0, dt / 0.05)
        self.de += (de_cmd - self.de) * k_act
        self.da += (da_cmd - self.da) * k_act
        self.dr += (dr_cmd - self.dr) * k_act
        de = self.de - self.trim * t.trim_range

        qbar = 0.5 * rho * V * V
        thrust = sum(en.thrust for en in s.engines)
        qc = qbar + t.slipstream * max(thrust, 0.0)      # presión dinámica en la cola (estela)
        p, q, r = self.omega
        Vn = max(V, 8.0)
        pg, qg, rg = self._rot_gusts(dt, R, V)
        ph = (p - pg) * t.b / (2 * Vn)
        qh = (q - qg) * t.c / (2 * Vn)
        rh = (r - rg) * t.b / (2 * Vn)
        ff = s.flaps / max(t.flap_settings)

        # sustentación con pérdida
        a_st = t.alpha_stall + t.alpha_stall_flap_delta * ff
        sb = stall_blend(alpha, a_st)
        sb_aero = sb                                         # para el disparador de la barrena (el ala de verdad)
        sb = max(sb, self.spin)                              # en barrena el ala sigue en pérdida (autorrotación)
        self.stall_frac = sb
        CL_lin = t.CL0 + t.CLa * alpha + t.CL_flaps * ff
        CL_fp = 1.05 * math.sin(2 * alpha)
        CL = (1 - sb) * CL_lin + sb * CL_fp
        # efecto suelo
        wing_h = max(agl + (0.3 if t.low_wing else -0.9), 0.2)
        hb = 16.0 * wing_h / t.b
        phi_ge = hb * hb / (1 + hb * hb)
        CL *= 1.0 + 0.10 * (1 - phi_ge)
        CL += t.CLq * qh
        k_ind = 1.0 / (math.pi * t.e * t.AR)
        CD = (t.CD0 + (0.0045 if s.failures.get("door") else 0.0)
              + t.CD_flaps * ff ** 1.4 + t.CD_gear * s.gear_pos + k_ind * phi_ge * CL * CL
              + sb * 1.25 * math.sin(alpha) ** 2 + t.CD_beta * beta * beta)
        CY = t.CYb * beta + t.CYp * ph + t.CYr * rh
        wobble = math.sin(self.time * 1.7) * 0.6 + math.sin(self.time * 0.63 + 1.0) * 0.4
        Cl = (t.Clb * beta + t.Clp * ph * (1 - 0.9 * sb) + t.Clr * rh
              + sb * (0.02 * wobble - 0.15 * beta) + t.rig_roll)        # en pérdida cae el ala que retrocede
        # retardo de la estela del ala sobre la cola: amortigua los cambios rápidos de alfa
        if V > 15.0 and self._alpha_prev is not None:
            self._adot += ((alpha - self._alpha_prev) / dt - self._adot) * min(1.0, dt / 0.05)
        else:
            self._adot = 0.0
        self._alpha_prev = alpha
        # pasada la pérdida el momento de cabeceo deja de crecer con alfa (la extrapolación lineal picaría de más)
        alpha_cm = (1 - sb) * alpha + sb * clamp(alpha, -1.2 * a_st, 1.2 * a_st)
        Cm = (t.Cm0 + t.Cma * alpha_cm + t.Cmq * qh + t.Cm_flaps * ff + sb * t.Cm_stall
              - 0.04 * (1 - phi_ge) + t.Cmadot * self._adot * t.c / (2 * Vn))
        Cn = t.Cnb * beta + t.Cnp * ph + t.Cnr * rh * (1 - 0.4 * sb) + t.rig_yaw

        L_aero = qbar * t.S * CL + qc * t.S * t.CLde * de
        D_aero = qbar * t.S * CD
        Y_aero = qbar * t.S * CY - qc * t.S * t.CYdr * self.dr

        F = vec()
        if V > 0.3:
            F += -D_aero * vb / V
        F += L_aero * vec(math.sin(alpha), 0.0, -math.cos(alpha))
        F[1] += Y_aero
        F[0] += thrust
        # el modelo está ajustado con el CG de referencia: si la carga lo mueve dx hacia atrás, las fuerzas
        # aerodinámicas quedan dx más adelante del CG (CG atrás: más nariz arriba y menos estable)
        dx = self._cg_dx = self.cg_dx()

        M = vec(
            qbar * t.S * t.b * Cl + qbar * t.S * t.b * t.Clda * self.da - qc * t.S * t.b * t.Cldr * self.dr,
            qbar * t.S * t.c * Cm + qc * t.S * t.c * t.Cmde * de,
            qbar * t.S * t.b * Cn + qbar * t.S * t.b * t.Cnda * self.da + qc * t.S * t.b * t.Cndr * self.dr,
        )
        if dx:
            M[1] -= dx * F[2]
            M[2] += dx * F[1]
        # barrena desarrollada: el avión gira ~2,4 rad/s alrededor de la vertical (2,5-3 s por vuelta) con el morro
        # unos 40° abajo y algo de alabeo hacia el lado del giro; las velocidades de giro del avión que corresponden a
        # esa rotación salen de las ecuaciones de Euler, y los momentos llevan al avión hacia ellas según la intensidad
        k = self._spin_update(dt, sb_aero, alpha, a_st)
        if k > 0:
            Ixyz = np.array(t.inertia) * (s.mass / t.ref_mass)
            phi, th = self.roll, self.pitch
            psid = self.spin_dir * 2.4             # la autorrotación pierde fuerza con k: el giro lo frena el aire
            phid = ((self.spin_dir * math.radians(15) - phi + math.pi) % (2 * math.pi) - math.pi) * 1.5
            thd = (math.radians(-40) - th) * 3.0
            pd = phid - psid * math.sin(th)
            qd = thd * math.cos(phi) + psid * math.sin(phi) * math.cos(th)
            rd = -thd * math.sin(phi) + psid * math.cos(phi) * math.cos(th)
            gain = 3.0 * k                        # k sube en ~3 s: la barrena incipiente es sobre todo aerodinámica
            M[0] += Ixyz[0] * clamp(pd - p, -2.0, 2.0) * gain
            M[1] += Ixyz[1] * clamp(qd - q, -3.0, 3.0) * gain
            M[2] += Ixyz[2] * clamp(rd - r, -2.0, 2.0) * gain
        # efectos de la hélice (torque y factor P / estela helicoidal) y empuje asimétrico
        for en, yy in zip(s.engines, t.engines_y):
            M[0] += -t.torque_roll * en.torque
            M[2] += -(t.p_factor + 0.35 * max(alpha, 0.0)) * max(en.thrust, 0.0)
            M[2] += -yy * en.thrust

        # tren y contactos con el suelo
        if agl < 14.0:
            res = self._ground_forces(R)
            if res is None:
                return
            Fg_w, Mg = res
        else:
            Fg_w = vec()
            Mg = vec()
            self.on_ground = False
            for gr in t.gears:
                self.gear_contact[gr.name] = False
                self.gear_load[gr.name] = 0.0
                self._contact_prev[gr.name] = False

        # gravedad y ecuaciones del movimiento
        m = s.mass
        scale = m / t.ref_mass
        I = np.array(t.inertia) * scale
        F_w = R @ F + Fg_w
        acc = F_w / m + vec(0, 0, G)
        Mt = M + Mg
        Iw = I * self.omega
        omega_dot = (Mt - cross(self.omega, Iw)) / I

        self.vel = self.vel + acc * dt
        self.pos = self.pos + self.vel * dt
        self.omega = self.omega + omega_dot * dt
        self.q = quat_integrate(self.q, self.omega, dt)

        # carga 'g' (fuerza específica en ejes cuerpo)
        f_spec = R.T @ (F_w / m)
        self._update_outputs(f_spec, V)

        # límites estructurales y aterrizajes
        nz = self.nz
        self.max_g = max(self.max_g, nz)
        self.min_g = min(self.min_g, nz)
        if not self.on_ground:
            lim_p, lim_n = t.g_limit
            if nz > lim_p * 1.5 or nz < lim_n * 1.5:
                self._crash("Falla estructural por exceso de carga G")
                return
            if (nz > lim_p or nz < lim_n) and not self.overstress:
                self.overstress = True
                self.events.append(("sobrecarga", dict(g=nz)))
            if self.ias_kt > t.v["vne"] + 25:
                self._crash("Falla estructural por exceso de velocidad (VNE)")
                return
        for name, ld in self.gear_load.items():
            if ld > m * G * 4.5:
                self._crash("Tren de aterrizaje colapsado (impacto muy fuerte)")
                return

    def _ground_forces(self, R):
        """Fuerzas del tren y de los puntos de choque. Devuelve None si hay accidente."""
        t = self.t
        s = self.sys
        Fg_w = vec()
        Mg = vec()
        self.on_ground = False
        steer = clamp(self.ctl_rud, -1, 1) * (t.nose_steer_max if self.gs > 4 else t.nose_steer_rudder)
        fwd_h = np.array([R[0, 0], R[1, 0]])
        n_f = math.hypot(fwd_h[0], fwd_h[1])
        fwd_h = fwd_h / n_f if n_f > 1e-6 else np.array([1.0, 0.0])
        for gr in t.gears:
            if s.gear_pos < 0.98:
                self.gear_contact[gr.name] = False
                self.gear_load[gr.name] = 0.0
                continue
            rb = np.array(gr.pos) + (self._cg_dx, 0.0, 0.0)     # el tren, visto desde el CG cargado
            pw = self.pos + R @ rb
            d = pw[2] + self.terrain.surface_height(pw[0], pw[1])
            if d <= 0:
                self.gear_contact[gr.name] = False
                self.gear_load[gr.name] = 0.0
                self._contact_prev[gr.name] = False
                continue
            gsurf = self.terrain.surface(pw[0], pw[1])[1]
            sfc = SURFACE[gsurf]
            vpt = self.vel + R @ cross(self.omega, rb)
            if not self._contact_prev.get(gr.name, False):
                self.events.append(("contacto", dict(gear=gr.name, sink=vpt[2], surf=gsurf)))
            self._contact_prev[gr.name] = True
            N = max(0.0, gr.k * min(d, 0.4) + gr.c * vpt[2])
            if d > 0.4:
                N += gr.k * 6 * (d - 0.4)
            self.gear_contact[gr.name] = True
            self.gear_load[gr.name] = N
            self.on_ground = True
            if gsurf == "agua":
                # amerizaje controlado: poca velocidad vertical, alas niveladas y velocidad baja
                ok = (self.vs_fpm > -400 and abs(math.degrees(self.roll)) < 12
                      and self.ias_kt < self.t.v.get("vs0", 48) * 1.35)
                self.ditched = ok
                self._crash("Amerizaje controlado: ocupantes a salvo" if ok else "Amerizaje: el avión ha caído al agua")
                return None
            wd = fwd_h
            if gr.steer:
                c_s, s_s = math.cos(steer), math.sin(steer)
                wd = np.array([wd[0] * c_s - wd[1] * s_s, wd[0] * s_s + wd[1] * c_s])
            wr = np.array([-wd[1], wd[0]])
            v_long = vpt[0] * wd[0] + vpt[1] * wd[1]
            v_lat = vpt[0] * wr[0] + vpt[1] * wr[1]
            brk = 0.0
            if gr.brake:
                side = self.brake_r if gr.pos[1] > 0 else self.brake_l
                brk = 1.0 if s.parking_brake else clamp(max(self.brake, side), 0.0, 1.0)
            # pista mojada: los frenos agarran menos y la rueda derrapa antes
            wet = getattr(self.atmo, "wet", 0.0) if gsurf != "agua" else 0.0
            mu_l = sfc["roll"] + brk * sfc["brake"] * (1.0 - 0.45 * wet)
            if getattr(self, "soft_field", False):
                # pista blanda: el barro frena mucho más, sobre todo la rueda de morro
                mu_l += 0.10 if gr.steer else 0.06
            f_long = -mu_l * N * math.tanh(v_long / (0.06 if brk > 0.5 else 0.12))
            f_lat = -sfc["lat"] * (1.0 - 0.3 * wet) * N * math.tanh(v_lat / 0.15)
            fw = vec(f_long * wd[0] + f_lat * wr[0], f_long * wd[1] + f_lat * wr[1], -N)
            Fg_w += fw
            Mg += cross(rb, R.T @ fw)

        for name, cp in t.contacts:
            rb = np.array(cp) + (self._cg_dx, 0.0, 0.0)
            pw = self.pos + R @ rb
            d = pw[2] + self.terrain.surface_height(pw[0], pw[1])
            if d > 0:
                vpt = self.vel + R @ cross(self.omega, rb)
                if name == "cola" and vpt[2] < 2.0 and self.gs < 45:
                    if not self._contact_prev.get(name, False):
                        self.events.append(("cola", dict(sink=vpt[2])))
                    self._contact_prev[name] = True
                    N = max(0.0, 90000.0 * d + 6000.0 * vpt[2])
                    fw = vec(-0.5 * N * math.tanh(vpt[0] / 0.3), -0.5 * N * math.tanh(vpt[1] / 0.3), -N)
                    Fg_w += fw
                    Mg += cross(rb, R.T @ fw)
                    continue
                if name.startswith("vientre") and s.gear_pos < 0.5:
                    self._crash("Aterrizaje con el tren arriba")
                else:
                    self._crash(f"Impacto: {name}")
                return None
            else:
                self._contact_prev[name] = False

        return Fg_w, Mg

    def _crash(self, reason):
        if not self.crashed:
            self.crashed = True
            self.crash_reason = reason
            self.events.append(("choque", dict(reason=reason, sink=self.vs_fpm, ias=self.ias_kt)))
            self.vel *= 0.0
            self.omega *= 0.0

    # ------------------------------------------------------------- salidas
    def _update_outputs(self, f_spec, V):
        self.R = quat_to_mat(self.q)
        roll, pitch, yaw = quat_to_euler(self.q)
        self.roll, self.pitch, self.yaw = roll, pitch, yaw
        self.heading = math.degrees(yaw) % 360.0
        self.alt_msl = -self.pos[2]
        gh, surf = self.terrain.surface(self.pos[0], self.pos[1])
        self.ground_h = gh
        self.surface_type = surf
        gz = max(g.pos[2] for g in self.t.gears)
        self.agl = self.alt_msl - gh - gz + 0.055
        self.vs_mps = -self.vel[2]
        self.vs_fpm = self.vs_mps / FPM
        self.tas = V
        self.gs = math.hypot(self.vel[0], self.vel[1])
        self.track = math.degrees(math.atan2(self.vel[1], self.vel[0])) % 360.0 if self.gs > 1 else self.heading
        rho = getattr(self, "rho", 1.225)
        self.ias_kt = math.sqrt(rho / 1.225) * V / KT
        if np.any(f_spec):
            self.nz = -f_spec[2] / G
            self.ny = f_spec[1] / G
            self.nx = f_spec[0] / G
        else:
            self.nz, self.ny, self.nx = 1.0, 0.0, 0.0
        p, q, r = self.omega
        cphi, sphi = math.cos(roll), math.sin(roll)
        cth = max(math.cos(pitch), 0.05)
        self.turn_rate = math.degrees((q * sphi + r * cphi) / cth)
        if not hasattr(self, "alpha"):
            self.alpha = self.beta = 0.0
            self.stall_frac = 0.0
        a_st = self.t.alpha_stall + self.t.alpha_stall_flap_delta * (self.sys.flaps / max(self.t.flap_settings))
        warn = self.alpha > a_st - math.radians(4.5) and self.ias_kt > 20
        self.sys.stall_warning = warn and self.sys.electric_ok
