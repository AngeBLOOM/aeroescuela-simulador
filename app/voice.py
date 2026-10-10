"""Voz del instructor y avisos hablados mediante la síntesis de voz de Windows (SAPI)."""
import time


class Voice:
    def __init__(self, enabled=True, rate=1):
        self.enabled = enabled
        self.engine = None
        self.last = {}
        try:
            import comtypes.client as cc
            self.engine = cc.CreateObject("SAPI.SpVoice")
            voices = self.engine.GetVoices()
            best = None
            for i in range(voices.Count):
                d = voices.Item(i).GetDescription().lower()
                if "spanish" in d or "español" in d or "espanol" in d:
                    best = voices.Item(i)
                    break
            if best is not None:
                self.engine.Voice = best
            self.engine.Rate = rate
            self.engine.Volume = 100
        except Exception as ex:
            print("Voz no disponible:", ex)
            self.engine = None

    @property
    def available(self):
        return self.engine is not None

    def say(self, text, urgent=False, key=None, min_gap=4.0):
        """Habla de forma asíncrona. 'key' evita repetir el mismo aviso muy seguido."""
        if not self.enabled or self.engine is None or not text:
            return
        k = key or text
        now = time.time()
        if now - self.last.get(k, 0) < min_gap:
            return
        self.last[k] = now
        try:
            flags = 1 | (2 if urgent else 0)      # asíncrono (+ purgar si es urgente)
            self.engine.Speak(text, flags)
        except Exception:
            pass

    def stop(self):
        if self.engine is not None:
            try:
                self.engine.Speak("", 3)
            except Exception:
                pass
