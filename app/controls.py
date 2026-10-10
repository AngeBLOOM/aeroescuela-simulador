"""Entrada de mandos: teclado, joystick/volante de vuelo y mando de consola."""
import math

import pygame

from sim.mathx import approach, clamp, wrap180

DEFAULT_JOY = dict(
    eje_alabeo=0, eje_cabeceo=1, eje_timon=3, eje_potencia=2,
    invertir_cabeceo=False, invertir_potencia=True, zona_muerta=0.06, exponencial=0.35,
    boton_frenos=0, boton_desconectar_pa=1, boton_flaps_arriba=4, boton_flaps_abajo=5,
)


def expo(x, k):
    return (1 - k) * x + k * x * x * x


class Controls:
    def __init__(self, cfg):
        self.cfg = dict(DEFAULT_JOY)
        self.cfg.update(cfg or {})
        self.joy = None
        self.joy_name = ""
        self.kb_pitch = 0.0
        self.kb_roll = 0.0
        self.kb_rud = 0.0
        self.pilot_force = 0.0
        self.joy_throttle_last = None
        self.assist_rudder = False
        self.joy_shared = False          # el mando también está asignado en «Cabina física»: aquí se ignora
        self._prev_buttons = {}
        self.refresh_joystick()

    def refresh_joystick(self):
        pygame.joystick.init()
        self.joy = None
        if pygame.joystick.get_count() > 0:
            try:
                self.joy = pygame.joystick.Joystick(0)
                self.joy.init()
                self.joy_name = self.joy.get_name()
            except Exception:
                self.joy = None

    def _axis(self, i, invert=False):
        if self.joy is None or self.joy_shared or i is None or i < 0 or i >= self.joy.get_numaxes():
            return None
        v = self.joy.get_axis(i)
        dz = self.cfg["zona_muerta"]
        if abs(v) < dz:
            v = 0.0
        else:
            v = math.copysign((abs(v) - dz) / (1 - dz), v)
        return -v if invert else v

    def _button_pressed(self, i):
        if self.joy is None or i is None or i < 0 or i >= self.joy.get_numbuttons():
            return False, False
        now = bool(self.joy.get_button(i))
        prev = self._prev_buttons.get(i, False)
        self._prev_buttons[i] = now
        return now, now and not prev

    def update(self, dt, world, keys, mods, ui_wants_keys=False):
        ac = world.ac
        sysm = ac.sys
        e = sysm.engine
        shift = mods & pygame.KMOD_SHIFT
        ctrl = mods & pygame.KMOD_CTRL
        K = (lambda k: False) if (ui_wants_keys or keys is None) else (lambda k: bool(keys[k]))

        # ---------------------------------------------------- teclado (ejes)
        tp = (1.0 if K(pygame.K_DOWN) else 0.0) - (1.0 if K(pygame.K_UP) else 0.0)
        tr = (1.0 if K(pygame.K_RIGHT) else 0.0) - (1.0 if K(pygame.K_LEFT) else 0.0)
        td = (1.0 if K(pygame.K_d) else 0.0) - (1.0 if K(pygame.K_a) else 0.0)
        if ctrl:
            tp = tr = 0.0
        rate_in, rate_out = 1.6, 3.2
        self.kb_pitch = approach(self.kb_pitch, tp * 0.85, (rate_in if tp else rate_out) * dt)
        self.kb_roll = approach(self.kb_roll, tr * 0.9, (rate_in * 1.4 if tr else rate_out) * dt)
        self.kb_rud = approach(self.kb_rud, td, (2.0 if td else 3.0) * dt)

        # ---------------------------------------------------- joystick
        hw = getattr(self, "hw", None)
        self.joy_shared = hw is not None and hw.uses_device(self.joy)
        jp = self._axis(self.cfg["eje_cabeceo"], not self.cfg["invertir_cabeceo"])
        jr = self._axis(self.cfg["eje_alabeo"])
        jy = self._axis(self.cfg["eje_timon"])
        jt = self._axis(self.cfg["eje_potencia"], self.cfg["invertir_potencia"])
        k = self.cfg["exponencial"]
        pitch = self.kb_pitch
        roll = self.kb_roll
        rud = self.kb_rud
        if jp is not None and abs(jp) > 0.0:
            pitch = clamp(expo(jp, k) + self.kb_pitch, -1, 1)
        if jr is not None and abs(jr) > 0.0:
            roll = clamp(expo(jr, k) + self.kb_roll, -1, 1)
        if jy is not None and abs(jy) > 0.0:
            rud = clamp(expo(jy, k) + self.kb_rud, -1, 1)
        if hw is not None:
            # cabina física: los ejes asignados mandan sobre el joystick genérico (ya llevan su zona muerta y curva)
            hr, hp, hy = hw.flight_axes()
            if hr is not None:
                roll = clamp(hr + self.kb_roll, -1, 1)
            if hp is not None:
                pitch = clamp(hp + self.kb_pitch, -1, 1)
            if hy is not None:
                rud = clamp(hy + self.kb_rud, -1, 1)
        if jt is not None:
            thr = (jt + 1) / 2
            if self.joy_throttle_last is None or abs(thr - self.joy_throttle_last) > 0.01:
                for en in sysm.engines:
                    en.throttle = clamp(thr, 0, 1)
                self.joy_throttle_last = thr

        # timón automático (ayuda para principiantes)
        if self.assist_rudder and not ac.on_ground and abs(td) < 0.01:
            rud = clamp(ac.beta * 4.0 - ac.omega[2] * 0.3 + rud, -1, 1)

        self.pilot_force = max(abs(pitch), abs(roll))
        ac.ctl_rud = rud

        # piloto automático
        ap = world.ap
        cmd = world.apply_autopilot(dt)
        if cmd is not None:
            if self.pilot_force > 0.55:
                ap.disengage("PA desconectado por el piloto")
                ac.ctl_elev, ac.ctl_ail = pitch, roll
            else:
                ac.ctl_elev = clamp(cmd[0] + pitch * 0.3, -1, 1)
                ac.ctl_ail = clamp(cmd[1] + roll * 0.3, -1, 1)
        else:
            ac.ctl_elev, ac.ctl_ail = pitch, roll

        # ---------------------------------------------------- palancas
        if not ctrl:
            for en in sysm.engines:
                if K(pygame.K_w) or K(pygame.K_PAGEUP):
                    en.throttle = clamp(en.throttle + (0.45 if not shift else 3.0) * dt, 0, 1)
                if K(pygame.K_s) or K(pygame.K_PAGEDOWN):
                    en.throttle = clamp(en.throttle - (0.45 if not shift else 3.0) * dt, 0, 1)
        if K(pygame.K_m):
            e.mixture = clamp(e.mixture + 0.25 * dt, 0, 1)
        if K(pygame.K_n):
            e.mixture = clamp(e.mixture - 0.25 * dt, 0, 1)
        if not ac.t.fixed_pitch:
            if K(pygame.K_u):
                e.prop_lever = clamp(e.prop_lever + 0.3 * dt, 0, 1)
            if K(pygame.K_j):
                e.prop_lever = clamp(e.prop_lever - 0.3 * dt, 0, 1)
        trim_rate = 0.22
        if K(pygame.K_q) or K(pygame.K_END):
            ac.trim = clamp(ac.trim + trim_rate * dt, -1, 1)
        if (K(pygame.K_e) and not ctrl) or K(pygame.K_HOME):
            ac.trim = clamp(ac.trim - trim_rate * dt, -1, 1)
        brake = 1.0 if K(pygame.K_SPACE) else 0.0
        if self.joy is not None and not self.joy_shared:
            held, _ = self._button_pressed(self.cfg["boton_frenos"])
            if held:
                brake = 1.0
            _, pr = self._button_pressed(self.cfg["boton_desconectar_pa"])
            if pr:
                ap.disengage("PA desconectado")
            _, pr = self._button_pressed(self.cfg["boton_flaps_abajo"])
            if pr:
                sysm.flaps_cmd = min(sysm.flaps_cmd + 1, len(ac.t.flap_settings) - 1)
            _, pr = self._button_pressed(self.cfg["boton_flaps_arriba"])
            if pr:
                sysm.flaps_cmd = max(sysm.flaps_cmd - 1, 0)
            if self.joy.get_numhats() > 0:
                hx, hy = self.joy.get_hat(0)
                if hy:
                    ac.trim = clamp(ac.trim - hy * trim_rate * dt, -1, 1)
        ac.brake = brake
