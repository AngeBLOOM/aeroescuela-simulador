"""Sonido sintetizado en tiempo real (sin archivos): motor, viento, avisos y radiobalizas."""
import math

import numpy as np
import pygame

SR = 44100


def _lowpass(x, k):
    """Filtro paso bajo simple (media exponencial) aplicado k veces."""
    y = x.copy()
    for _ in range(k):
        y = np.convolve(y, np.ones(8) / 8, mode="same")
    return y


def _to_sound(mono, vol=1.0):
    mono = np.clip(mono * vol, -1, 1)
    data = (mono * 32000).astype(np.int16)
    st = np.ascontiguousarray(np.column_stack([data, data]))
    return pygame.sndarray.make_sound(st)


class Audio:
    def __init__(self, volume=0.8):
        self.ok = False
        self.volume = volume
        try:
            pygame.mixer.pre_init(SR, -16, 2, 512)
            pygame.mixer.init(SR, -16, 2, 512)
            pygame.mixer.set_num_channels(48)
            self._build()
            self.ok = True
        except Exception as ex:  # sin dispositivo de audio
            print("Audio desactivado:", ex)
        self.marker_cur = None
        self.prev_contact = False

    # ------------------------------------------------------------ síntesis
    def _engine_loop(self, rpm, rng):
        f0 = max(4, int(round(rpm / 30.0)))          # encendidos/s de un 4 cilindros
        t = np.arange(SR) / SR
        sig = np.zeros(SR)
        for k in range(1, 14):
            a = (1.0 / k ** 0.75) * rng.uniform(0.6, 1.0)
            sig += a * np.sin(2 * np.pi * k * f0 * t + rng.uniform(0, 6.28))
        if f0 % 2 == 0:
            sig += 0.35 * np.sin(2 * np.pi * (f0 // 2) * t)
        pulse = (0.5 + 0.5 * np.cos(2 * np.pi * f0 * t)) ** 6
        noise = _lowpass(rng.normal(0, 1, SR), 2)
        sig += noise * pulse * 1.6
        # siseo de la hélice
        hiss = rng.normal(0, 1, SR) - _lowpass(rng.normal(0, 1, SR), 3)
        sig += hiss * 0.08 * (rpm / 2700) * (0.6 + 0.4 * pulse)
        sig /= np.max(np.abs(sig)) + 1e-9
        return _to_sound(sig, 0.85)

    @staticmethod
    def _tap(rng, base, glide, dur=0.075):
        """Clic de interfaz: un golpe de ruido de 2 ms, un tono que se desliza hacia abajo y su octava grave."""
        n = int(SR * dur)
        tt = np.arange(n) / SR
        f = base + glide * np.exp(-tt * 220)
        tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 65)
        body = np.sin(2 * np.pi * np.cumsum(f / 2) / SR) * np.exp(-tt * 90) * 0.35
        noise = rng.normal(0, 1, n)
        noise = (noise - _lowpass(noise, 1)) * np.exp(-tt * 1500) * 0.35
        sig = (tone + body + noise) * np.minimum(1, tt / 0.001)
        return sig / (np.max(np.abs(sig)) + 1e-9)

    def _build(self):
        rng = np.random.default_rng(4)
        self.engine_rpms = list(range(300, 3001, 100))
        self.engine = [self._engine_loop(r, rng) for r in self.engine_rpms]
        self.engine_ch = []
        for snd in self.engine:
            ch = snd.play(loops=-1)
            ch.set_volume(0.0)
            self.engine_ch.append(ch)
        # viento
        n = SR * 2
        w = _lowpass(rng.normal(0, 1, n), 4)
        w = w + 0.3 * (rng.normal(0, 1, n) - _lowpass(rng.normal(0, 1, n), 2)) * 0.2
        w /= np.max(np.abs(w))
        fade = np.minimum(1, np.minimum(np.arange(n), n - np.arange(n)) / 2000)
        self.wind = _to_sound(w * fade + w[::-1] * (1 - fade), 0.9)
        self.wind_ch = self.wind.play(loops=-1)
        self.wind_ch.set_volume(0)
        # rodadura
        r = _lowpass(rng.normal(0, 1, SR), 10)
        r *= 1 + 0.5 * np.sin(2 * np.pi * 7 * np.arange(SR) / SR)
        r /= np.max(np.abs(r))
        self.roll = _to_sound(r, 0.9)
        self.roll_ch = self.roll.play(loops=-1)
        self.roll_ch.set_volume(0)
        # bocina de pérdida
        t = np.arange(SR) / SR
        horn = np.sign(np.sin(2 * np.pi * 1600 * t)) * 0.3 + np.sin(2 * np.pi * 3200 * t) * 0.2
        horn *= 0.8 + 0.2 * np.sin(2 * np.pi * 20 * t)
        self.horn = _to_sound(horn, 0.5)
        self.horn_ch = self.horn.play(loops=-1)
        self.horn_ch.set_volume(0)
        # arranque
        crank = np.zeros(SR)
        for k in range(1, 8):
            crank += np.sin(2 * np.pi * 8 * k * t) / k
        crank += 0.25 * np.sin(2 * np.pi * 420 * t) + 0.1 * np.sin(2 * np.pi * 840 * t)
        crank *= 0.6 + 0.4 * (0.5 + 0.5 * np.cos(2 * np.pi * 8 * t)) ** 4
        crank /= np.max(np.abs(crank))
        self.crank = _to_sound(crank, 0.7)
        self.crank_ch = self.crank.play(loops=-1)
        self.crank_ch.set_volume(0)
        # motor de flaps
        fl = np.sin(2 * np.pi * 240 * t) + 0.5 * np.sin(2 * np.pi * 480 * t) + 0.2 * rng.normal(0, 1, SR)
        fl /= np.max(np.abs(fl))
        self.flaps = _to_sound(fl, 0.35)
        self.flaps_ch = self.flaps.play(loops=-1)
        self.flaps_ch.set_volume(0)
        # toma de contacto
        n = int(SR * 0.45)
        tt = np.arange(n) / SR
        thump = np.sin(2 * np.pi * 70 * tt) * np.exp(-tt * 18)
        chirp = rng.normal(0, 1, n) * np.exp(-tt * 9) * 0.5 + np.sin(2 * np.pi * 1100 * tt) * np.exp(-tt * 14) * 0.3
        self.touch = _to_sound((thump + chirp) / 1.5, 0.9)
        # choque
        n = int(SR * 2.0)
        tt = np.arange(n) / SR
        cr = _lowpass(rng.normal(0, 1, n), 2) * np.exp(-tt * 2.0) + np.sin(2 * np.pi * 45 * tt) * np.exp(-tt * 4)
        cr /= np.max(np.abs(cr))
        self.crash = _to_sound(cr, 1.0)
        # desconexión del PA
        n = int(SR * 1.2)
        tt = np.arange(n) / SR
        ap = np.zeros(n)
        for i, fq in enumerate((1200, 900, 1200, 900)):
            seg = (tt >= i * 0.3) & (tt < i * 0.3 + 0.25)
            ap[seg] = np.sin(2 * np.pi * fq * tt[seg])
        self.ap_off = _to_sound(ap, 0.35)
        # clic
        n = int(SR * 0.03)
        tt = np.arange(n) / SR
        self.click = _to_sound(np.sin(2 * np.pi * 2000 * tt) * np.exp(-tt * 300), 0.4)
        # botón de la interfaz: toque limpio y moderno (ataque nítido, tono que cae de 1,8 a 1,15 kHz, cuerpo suave)
        self.ui_click = _to_sound(self._tap(np.random.default_rng(11), 1150, 650), 0.5)   # su propio azar: no cambia los demás
        # interfaz: abrir (barrido ascendente), cerrar (descendente) y aviso (dos tonos)
        n = int(SR * 0.14)
        tt = np.arange(n) / SR
        env = np.sin(np.pi * tt / tt[-1]) ** 2
        f_up = 700 + 900 * tt / tt[-1]
        self.ui_open = _to_sound(np.sin(2 * np.pi * np.cumsum(f_up) / SR) * env, 0.22)
        f_dn = 1500 - 900 * tt / tt[-1]
        self.ui_close = _to_sound(np.sin(2 * np.pi * np.cumsum(f_dn) / SR) * env, 0.18)
        n = int(SR * 0.5)
        tt = np.arange(n) / SR
        sig = np.where(tt < 0.12, np.sin(2 * np.pi * 988 * tt), 0.0) + np.where((tt > 0.18) & (tt < 0.32),
                                                                               np.sin(2 * np.pi * 740 * tt), 0.0)
        self.ui_alert = _to_sound(sig * 0.8, 0.3)
        # lluvia sobre el fuselaje: ruido blanco suavizado, sin repetición audible
        n = SR * 3
        rn = rng.normal(0, 1, n)
        rn = rn - _lowpass(rn, 1) * 0.6
        patter = (rng.uniform(0, 1, n) < 0.004) * rng.normal(0, 3.0, n)
        rn = rn + _lowpass(patter, 1)
        rn /= np.max(np.abs(rn))
        fade = np.minimum(1, np.minimum(np.arange(n), n - np.arange(n)) / 3000)
        self.rain = _to_sound(rn * fade + rn[::-1] * (1 - fade), 0.5)
        self.rain_ch = self.rain.play(loops=-1)
        self.rain_ch.set_volume(0)
        # trueno: chasquido y retumbo largo de baja frecuencia
        n = int(SR * 4.5)
        tt = np.arange(n) / SR
        rumble = _lowpass(rng.normal(0, 1, n), 14)
        rumble /= np.max(np.abs(rumble)) + 1e-9
        rumble *= (np.exp(-tt * 0.9) * (1 + 0.6 * np.sin(2 * np.pi * 1.3 * tt + 1.0)) * np.minimum(1, tt / 0.25))
        crack = _lowpass(rng.normal(0, 1, n), 2) * np.exp(-tt * 9)
        th = rumble * 0.9 + crack * 0.45
        th /= np.max(np.abs(th)) + 1e-9
        self.thunder = _to_sound(th, 1.0)
        # radiobalizas
        self.markers = {}
        for m, fq, pattern in (("O", 400, [(0, 0.4)]), ("M", 1300, [(0, 0.12), (0.2, 0.5)]), ("I", 3000, [(0, 0.08)])):
            per = 0.6 if m != "I" else 0.16
            n = int(SR * per)
            tt = np.arange(n) / SR
            sig = np.zeros(n)
            for a, b in pattern:
                seg = (tt >= a) & (tt < min(b, per))
                sig[seg] = np.sin(2 * np.pi * fq * tt[seg])
            self.markers[m] = _to_sound(sig, 0.25)
        self.marker_ch = pygame.mixer.Channel(47)

    # ------------------------------------------------------------ control
    def set_volume(self, v):
        self.volume = v

    def silence(self):
        if not self.ok:
            return
        for ch in self.engine_ch:
            ch.set_volume(0)
        for ch in (self.wind_ch, self.roll_ch, self.horn_ch, self.crank_ch, self.flaps_ch, self.rain_ch):
            ch.set_volume(0)
        self.marker_ch.stop()
        self.marker_cur = None

    def play(self, name, vol=1.0):
        if not self.ok:
            return
        snd = getattr(self, name, None)
        if snd is not None:
            ch = snd.play()
            if ch:
                ch.set_volume(min(1.0, vol * self.volume))

    def update(self, world, cockpit_view, paused=False):
        if not self.ok:
            return
        if paused:
            self.silence()
            return
        ac = world.ac
        e = max(ac.sys.engines, key=lambda en: en.rpm)
        n_run = sum(1 for en in ac.sys.engines if en.running)
        v = self.volume * (1.2 if n_run > 1 else 1.0)
        inside = 0.75 if cockpit_view else 1.0
        rpm = e.rpm
        # mezcla de bucles de motor cercanos
        vols = [0.0] * len(self.engine_rpms)
        if rpm > 120 and not ac.crashed:
            x = (rpm - 300) / 100.0
            i0 = int(math.floor(x))
            fr = x - i0
            loud = (0.35 + 0.65 * min(1.0, e.pf * 1.5 + 0.15)) if e.running else 0.25
            for i, w in ((i0, 1 - fr), (i0 + 1, fr)):
                if 0 <= i < len(vols):
                    vols[i] = w * loud * v * inside
        for ch, vol in zip(self.engine_ch, vols):
            ch.set_volume(vol)
        tas = ac.tas
        self.wind_ch.set_volume(min(1.0, (tas / 70.0) ** 2) * 0.55 * v * (0.6 if cockpit_view else 1.0))
        rolling = ac.on_ground and ac.gs > 1.0 and not ac.crashed
        self.roll_ch.set_volume(min(1.0, ac.gs / 30.0) * 0.6 * v if rolling else 0.0)
        horn = ac.sys.stall_warning and not ac.crashed
        self.horn_ch.set_volume(0.45 * v if horn else 0.0)
        cranking = any(en.starter and not en.running for en in ac.sys.engines)
        self.crank_ch.set_volume(0.6 * v if (cranking and ac.sys.electric_ok) else 0.0)
        # bocina de tren: tren arriba con poca potencia cerca del suelo
        t = ac.t
        gear_warn = (t.retractable and ac.sys.gear_pos < 0.9 and not ac.on_ground and ac.agl < 300
                     and (all(en.throttle < 0.25 for en in ac.sys.engines) or ac.sys.flaps > 25))
        if gear_warn and not ac.sys.stall_warning:
            self.horn_ch.set_volume(0.35 * v)
        moving = abs(ac.sys.flaps - ac.sys.flap_target) > 0.2 and ac.sys.electric_ok
        self.flaps_ch.set_volume(0.25 * v if moving else 0.0)
        # lluvia (más fuerte cuanto más llueve y más rápido se vuela) y truenos con su retraso
        atmo = world.atmo
        rain = float(getattr(atmo, "rain_here", 0.0))
        self.rain_ch.set_volume(min(1.0, rain * (0.55 + 0.45 * min(1.0, tas / 50.0))) * 0.7 * v if not ac.crashed else 0.0)
        th = getattr(atmo, "thunder", None)
        if th:
            for item in [t for t in th if t[0] <= 0]:
                th.remove(item)
                self.play("thunder", item[1] * 0.9)
        mk = world.nav1.marker if ac.sys.avionics_ok else None
        if mk != self.marker_cur:
            self.marker_cur = mk
            self.marker_ch.stop()
            if mk:
                self.marker_ch.play(self.markers[mk], loops=-1)
                self.marker_ch.set_volume(0.5 * v)

    def on_event(self, ev, data):
        if ev == "contacto":
            sink = max(0.0, data.get("sink", 0.0))
            if sink > 0.3:
                self.play("touch", min(1.0, 0.3 + sink / 3.0))
        elif ev == "choque":
            self.play("crash", 1.0)
