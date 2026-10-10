"""Piloto automático de dos ejes con director de vuelo (estilo GFC 700 / KAP 140).

Modos laterales: ROL (mantener alabeo), HDG (rumbo), NAV (VOR/LOC), APR (ILS).
Modos verticales: PIT (mantener cabeceo), ALT, VS, GS (senda de planeo).
"""
import math

from .mathx import FPM, FT, KT, clamp, wrap180


class Autopilot:
    def __init__(self):
        self.engaged = False
        self.fd = False
        self.lat = "ROL"
        self.vert = "PIT"
        self.alt_armed = False
        self.gs_armed = False
        self.nav_armed = False
        self.hdg_bug = 360.0
        self.alt_sel = 3000.0          # ft
        self.vs_sel = 500.0            # fpm
        self.pitch_ref = 0.0
        self.roll_ref = 0.0
        self.cmd_roll = 0.0            # rad
        self.cmd_pitch = 0.0           # rad
        self._elev_i = 0.0
        self._vs_i = 0.0
        self._nav_i = 0.0
        self.message = ""
        self.disconnect_alert = 0.0
        self.minspd = False
        self.magvar = 0.0              # el marcador de rumbo y el OBS son magnéticos; la física, verdadera

    # ----------------------------------------------------------- órdenes
    def toggle(self, ac):
        if self.engaged:
            self.disengage("PA desconectado")
        else:
            self.engage(ac)

    def engage(self, ac):
        self.engaged = True
        self.fd = True
        self.disconnect_alert = 0.0
        self.pitch_ref = clamp(ac.pitch, math.radians(-10), math.radians(12))
        self.roll_ref = ac.roll if abs(ac.roll) > math.radians(6) else 0.0
        self.roll_ref = clamp(self.roll_ref, math.radians(-25), math.radians(25))
        if self.lat not in ("HDG", "NAV", "APR"):
            self.lat = "ROL"
        if self.vert not in ("ALT", "VS", "GS"):
            self.vert = "PIT"
        self._elev_i = ac.ctl_elev
        self._vs_i = ac.pitch

    def disengage(self, msg="PA desconectado"):
        if self.engaged:
            self.disconnect_alert = 2.5
            self.message = msg
        self.engaged = False

    def set_hdg(self, ac):
        self.lat = "HDG" if self.lat != "HDG" else "ROL"
        self.nav_armed = False
        if not self.engaged:
            self.engage(ac)

    def set_nav(self, ac, approach=False):
        mode = "APR" if approach else "NAV"
        if self.lat == mode or self.nav_armed:
            self.lat = "HDG"
            self.nav_armed = False
            self.gs_armed = False
            return
        self.nav_armed = True
        self.gs_armed = approach
        if self.lat not in ("HDG",):
            self.lat = "HDG"
            self.hdg_bug = round(ac.heading - self.magvar) % 360 or 360
        if not self.engaged:
            self.engage(ac)

    def set_alt(self, ac):
        if self.vert == "ALT":
            self.vert = "PIT"
            return
        self.vert = "ALT"
        self.alt_sel = round(ac.alt_ind_ft / 10) * 10 if hasattr(ac, "alt_ind_ft") else ac.alt_msl / FT
        self.alt_hold = self.alt_sel
        if not self.engaged:
            self.engage(ac)

    def set_vs(self, ac):
        self.vert = "VS"
        self.vs_sel = round(ac.vs_fpm / 100) * 100
        self.alt_armed = True
        if not self.engaged:
            self.engage(ac)

    def adjust_vs(self, d):
        if self.vert == "VS":
            self.vs_sel = clamp(self.vs_sel + d, -1500, 1500)
        elif self.vert == "PIT":
            self.pitch_ref = clamp(self.pitch_ref + math.radians(0.5 if d > 0 else -0.5),
                                   math.radians(-10), math.radians(15))

    # --------------------------------------------------------- actualización
    def update(self, dt, ac, nav, alt_ind_ft):
        if self.disconnect_alert > 0:
            self.disconnect_alert -= dt
        if not self.engaged:
            return None
        if not ac.sys.avionics_ok:
            self.disengage("PA desconectado: falla eléctrica")
            return None
        if abs(ac.roll) > math.radians(50) or abs(ac.pitch) > math.radians(30) or ac.on_ground:
            self.disengage("PA desconectado: actitud anormal")
            return None

        # ---- lateral
        if self.nav_armed and nav.valid and abs(nav.cdi) < 0.85:
            self.lat = "APR" if self.gs_armed else "NAV"
            self.nav_armed = False
            self._nav_i = 0.0
        if self.lat == "ROL":
            roll_cmd = self.roll_ref
        elif self.lat == "HDG":
            err = wrap180(self.hdg_bug + self.magvar - ac.heading)
            roll_cmd = clamp(math.radians(err * 1.2), math.radians(-22), math.radians(22))
        else:
            if not nav.valid:
                roll_cmd = 0.0
            else:
                # curso verdadero: el del localizador, o el OBS (magnético) más la declinación del VOR
                course = nav.station.course if nav.is_loc else nav.obs + (getattr(nav.station, "magvar", None) or 0.0)
                full = 35.0 if nav.is_loc else 40.0
                self._nav_i = clamp(self._nav_i + nav.cdi * dt * 0.6, -12, 12)
                want = course + clamp(nav.cdi * full + self._nav_i, -45, 45)
                err = wrap180(want - ac.track)
                lim = 15 if nav.is_loc else 20
                roll_cmd = clamp(math.radians(err * 1.0), math.radians(-lim), math.radians(lim))
        self.cmd_roll = roll_cmd
        p = ac.omega[0]
        roll_err = roll_cmd - ac.roll
        rate_cmd = clamp(roll_err * 1.2, -math.radians(6), math.radians(6))
        ail = clamp((rate_cmd - p) * 1.6, -0.45, 0.45)

        # ---- vertical
        if self.gs_armed and self.lat == "APR" and nav.gs_valid and nav.gs < 0.1:
            self.vert = "GS"
            self.gs_armed = False
            self.alt_armed = False
        vs_cmd = None
        if self.vert == "ALT":
            err = self.alt_sel - alt_ind_ft
            vs_cmd = clamp(err * 4.0, -700, 700)
        elif self.vert == "VS":
            vs_cmd = self.vs_sel
            if self.alt_armed and abs(self.alt_sel - alt_ind_ft) < max(80, abs(ac.vs_fpm) * 0.12):
                if (self.vs_sel > 0 and alt_ind_ft < self.alt_sel + 50) or (self.vs_sel < 0 and alt_ind_ft > self.alt_sel - 50):
                    self.vert = "ALT"
                    self.alt_armed = False
        elif self.vert == "GS":
            if nav.gs_valid:
                nominal = -ac.gs / KT * 5.3
                vs_cmd = nominal + clamp(nav.gs * 600, -400, 400)
            else:
                vs_cmd = -400
        self.minspd = False
        vmin = ac.t.v["vs1"] + 14
        if vs_cmd is not None and nav is not None and ac.sys is not None:
            ias_now = ac.ias_kt
            if ias_now < vmin:
                self.minspd = True
                vs_cmd = min(vs_cmd, ac.vs_fpm - (vmin - ias_now) * 60.0)
            elif ias_now > ac.t.v["vne"] - 5:
                vs_cmd = max(vs_cmd, ac.vs_fpm + (ias_now - ac.t.v["vne"] + 5) * 60.0)
        if vs_cmd is not None:
            vs_err = (vs_cmd - ac.vs_fpm) * FPM
            V = max(ac.tas, 20)
            self._vs_i = clamp(self._vs_i + vs_err / V * dt * 0.5, math.radians(-12), math.radians(15))
            pitch_cmd = self._vs_i + vs_err / V * 0.6
        else:
            pitch_cmd = self.pitch_ref
            self._vs_i = ac.pitch
        pitch_cmd = clamp(pitch_cmd, math.radians(-12), math.radians(16))
        self.cmd_pitch = pitch_cmd
        q = ac.omega[1]
        perr = pitch_cmd - ac.pitch
        self._elev_i = clamp(self._elev_i + perr * dt * 0.8, -0.6, 0.6)
        elev = clamp(self._elev_i + perr * 2.0 - q * 0.6, -0.7, 0.7)

        # servo de compensación automática
        if abs(self._elev_i) > 0.02:
            d = self._elev_i * dt * 0.3
            self._elev_i -= d
            ac.trim = clamp(ac.trim + d * ac.t.elev_up / ac.t.trim_range, -1, 1)
        return elev, ail
