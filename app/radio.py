"""Radio VHF: convierte las transmisiones del ATC en audio con sonido de radio.

La voz se sintetiza con SAPI en un hilo aparte (a memoria, sin bloquear el vuelo), se filtra
como una radio de aviación (banda 300–3000 Hz, saturación, estática y clic de squelch) y se
reproduce en orden, una transmisión detrás de otra, como en una frecuencia real.
"""
import queue
import threading
import time

import numpy as np
import pygame

SR_IN = 22050
SR_OUT = 44100

# voz SAPI y tono (XML <pitch>) para cada tipo de emisor
VOICES = {
    "torre": ("Raul", 0, 1),
    "piloto": ("Sabina", 0, 1),
    "otro": ("Raul", 6, 2),
    "atis": ("Sabina", -3, 0),
}


class RadioVoice:
    def __init__(self, enabled=True, volume=0.8):
        self.enabled = enabled
        self.volume = volume
        self.jobs = queue.Queue()
        self.ready = queue.Queue()
        self.playlist = []              # [(msg, sound | None, dur)]
        self.current = None             # (msg, t_end)
        self.next_t = 0.0
        self.ok = True
        self.channel = None
        try:
            if pygame.mixer.get_init():
                if pygame.mixer.get_num_channels() < 48:
                    pygame.mixer.set_num_channels(48)
                self.channel = pygame.mixer.Channel(46)
        except Exception:
            self.channel = None
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    # ------------------------------------------------------------ hilo de síntesis
    def _worker(self):
        try:
            import comtypes
            import comtypes.client as cc
            comtypes.CoInitialize()
            voices = {}
            tokens = []
            for cat_id in (r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices",
                           r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\Voices"):
                try:
                    cat = cc.CreateObject("SAPI.SpObjectTokenCategory")
                    cat.SetId(cat_id, False)
                    t = cat.EnumerateTokens()
                    tokens += [t.Item(i) for i in range(t.Count)]
                except Exception:
                    pass
            spanish = [t for t in tokens if "spanish" in t.GetDescription().lower() or "español" in t.GetDescription().lower()]
            for key, (name, _p, _r) in VOICES.items():
                v = cc.CreateObject("SAPI.SpVoice")
                pick = next((t for t in spanish if name.lower() in t.GetDescription().lower()), spanish[0] if spanish else None)
                if pick is not None:
                    try:
                        v.Voice = pick
                    except Exception:
                        pass
                voices[key] = v
        except Exception as ex:
            print("Radio sin voz:", ex)
            self.ok = False
            voices = {}
        while True:
            msg = self.jobs.get()
            if msg is None:
                return
            snd = None
            if voices:
                try:
                    pcm = self._synth(cc, voices.get(msg.voice) or next(iter(voices.values())), msg)
                    snd = self._radioize(pcm, msg)
                except Exception as ex:
                    print("Error de síntesis de radio:", ex)
            self.ready.put((msg, snd))

    def _synth(self, cc, voice, msg):
        name, pitch, rate = VOICES.get(msg.voice, ("", 0, 1))
        ms = cc.CreateObject("SAPI.SpMemoryStream")
        fmt = cc.CreateObject("SAPI.SpAudioFormat")
        fmt.Type = 22                                   # 22 kHz, 16 bits, mono
        ms.Format = fmt
        voice.AudioOutputStream = ms
        voice.Rate = rate
        text = msg.spk.replace("&", " y ").replace("<", " ").replace(">", " ")
        voice.Speak(f'<pitch absmiddle="{pitch}">{text}</pitch>', 8)   # 8 = SVSFIsXML
        data = bytes(ms.GetData())
        return np.frombuffer(data, np.int16).astype(np.float32) / 32768.0

    def _radioize(self, x, msg):
        rng = np.random.default_rng()
        # recorta silencios del principio y del final
        nz = np.flatnonzero(np.abs(x) > 0.01)
        if len(nz):
            x = x[max(0, nz[0] - 600):nz[-1] + 1500]
        n = len(x)
        # filtro paso banda en frecuencia (300–3000 Hz) con flancos suaves
        X = np.fft.rfft(x)
        f = np.fft.rfftfreq(n, 1.0 / SR_IN)
        lo = 1 / (1 + (300.0 / np.maximum(f, 1.0)) ** 4)
        hi = 1 / (1 + (f / 3000.0) ** 6)
        y = np.fft.irfft(X * lo * hi, n)
        y /= max(1e-4, np.percentile(np.abs(y), 99.5))
        # compresión/saturación de la emisora
        y = np.tanh(y * 1.8) / np.tanh(1.8)
        # estática de fondo (más fuerte en el ATIS lejano y en otros aviones)
        lvl = {"torre": 0.035, "piloto": 0.025, "otro": 0.06, "atis": 0.03}.get(msg.voice, 0.04)
        hiss = rng.normal(0, 1, n).astype(np.float32)
        H = np.fft.rfft(hiss) * hi * lo
        hiss = np.fft.irfft(H, n)
        hiss /= max(1e-4, np.abs(hiss).max())
        y = y * 0.8 + hiss * lvl
        # clic de apertura y cola de squelch al soltar el botón
        click = np.concatenate([np.linspace(0, 1, 40), np.linspace(1, 0, 260)]) * 0.35
        click *= rng.choice([-1, 1], len(click))
        tail_n = int(SR_IN * 0.16)
        tail = rng.normal(0, 0.18, tail_n) * np.linspace(1, 0, tail_n) ** 0.5
        tail = np.fft.irfft(np.fft.rfft(tail) * (1 / (1 + (np.fft.rfftfreq(tail_n, 1 / SR_IN) / 4000.0) ** 4)), tail_n)
        y = np.concatenate([click, np.zeros(200), y, tail]).astype(np.float32)
        # 22 kHz mono → 44,1 kHz estéreo
        y = np.repeat(y, 2)
        a = np.clip(y * 0.9 * 32767, -32767, 32767).astype(np.int16)
        st = np.ascontiguousarray(np.stack([a, a], axis=1))
        return pygame.sndarray.make_sound(st)

    # ------------------------------------------------------------ hilo principal
    def submit(self, msg):
        if self.enabled and self.ok and self.channel is not None:
            self.jobs.put(msg)
        else:
            self.ready.put((msg, None))

    def busy(self):
        return self.current is not None or bool(self.playlist) or not self.jobs.empty()

    def clear(self):
        while not self.jobs.empty():
            try:
                self.jobs.get_nowait()
            except queue.Empty:
                break
        while not self.ready.empty():
            try:
                self.ready.get_nowait()
            except queue.Empty:
                break
        self.playlist.clear()
        self.current = None
        if self.channel is not None:
            self.channel.stop()

    def update(self, on_start):
        """Reproduce la siguiente transmisión lista. on_start(msg, dur) se llama al empezar cada una."""
        while not self.ready.empty():
            try:
                msg, snd = self.ready.get_nowait()
            except queue.Empty:
                break
            dur = snd.get_length() if snd is not None else max(2.0, len(msg.disp) / 15.0)
            self.playlist.append((msg, snd, dur))
        now = time.time()
        if self.current is not None:
            if now < self.current[1]:
                return
            self.current = None
            self.next_t = now
        if self.playlist:
            msg, snd, dur = self.playlist[0]
            if now - self.next_t < msg.delay:
                return
            self.playlist.pop(0)
            if snd is not None and self.channel is not None:
                snd.set_volume(self.volume)
                self.channel.play(snd)
            self.current = (msg, now + dur)
            on_start(msg, dur)
