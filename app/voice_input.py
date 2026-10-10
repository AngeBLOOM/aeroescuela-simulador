"""Hablar con la torre por micrófono (reconocimiento de voz de Windows, sin conexión).

Se usa el reconocedor de voz en español integrado en Windows 10/11 (Windows.Media.SpeechRecognition)
con una gramática cerrada: solo se aceptan las frases de las transmisiones disponibles en ese
momento (con o sin el indicativo y la estación delante). Así funciona sin Internet y con buena
precisión. Pulsar Ctrl derecho (o el botón PTT de la cabina) y decir la frase.
"""
import asyncio
import datetime
import re
import threading
import unicodedata

PHON = dict(A="alfa", B="bravo", C="charlie", D="delta", E="eco", F="foxtrot", G="golf", H="hotel", I="india",
            J="juliet", K="kilo", L="lima", M="maik", N="noviembre", O="oscar", P="papa", Q="quebec", R="romeo",
            S="sierra", T="tango", U="uniform", V="victor", W="whisky", X="equis", Y="yanqui", Z="zulu")

# sinónimos por palabra clave de la opción del menú de radio
SYN = [
    ("colacionar", ["colaciono", "recibido", "copiado"]),
    ("rodaje", ["solicito rodaje", "solicito rodar", "listo para rodar", "solicito rodar para circuitos locales"]),
    ("listo para salir", ["listo para salir", "listo para despegar", "punto de espera listo para salir",
                          "en punto de espera listo"]),
    ("listo para despegar", ["listo para despegar", "listo para salir", "alineado listo para salir"]),
    ("atis", ["solicito meteorologia", "solicito el atis", "meteorologia"]),
    ("entrada al circuito", ["solicito entrada al circuito", "para aterrizaje", "solicito aterrizaje", "contacto inicial"]),
    ("viento en cola", ["viento en cola", "en viento en cola"]),
    ("notificar base", ["base", "en base", "tramo base"]),
    ("aterrizaje completo", ["final", "final aterrizaje completo", "en final", "final para aterrizaje"]),
    ("toma y despegue", ["final toma y despegue", "final para toma y despegue", "toma y despegue"]),
    ("abandonar el circuito", ["abandono el circuito", "abandonando el circuito"]),
    ("motor y al aire", ["motor y al aire", "frustrando", "frustrada"]),
    ("mayday", ["mayday mayday mayday", "mayday"]),
    ("pista libre", ["pista libre", "pista libre solicito rodar a plataforma"]),
    ("trafico a la vista", ["trafico a la vista", "trafico en contacto", "en contacto visual"]),
    ("negativo contacto", ["negativo contacto", "sin contacto", "buscando"]),
]


def norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"\(.*?\)", " ", s)
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


def spell(cs):
    return " ".join(PHON.get(c, c) for c in cs.upper() if c.isalpha())


def phrases_for(options, callsign, facility):
    """{frase: índice de la opción} con variantes (indicativo / estación delante)."""
    cs = spell(callsign)
    fac = norm(facility)
    out = {}
    for i, (label, _st, _fn) in enumerate(options):
        base = norm(label)
        cands = [base]
        for key, syn in SYN:
            if key in base:
                cands += syn
        for c in cands:
            for v in (c, f"{cs} {c}", f"torre {cs} {c}", f"{fac} torre {cs} {c}", f"rodadura {cs} {c}",
                      f"{fac} rodadura {cs} {c}"):
                v = re.sub(r"\s+", " ", v).strip()
                out.setdefault(v, i)
    return out


class VoiceInput:
    def __init__(self):
        self.available = None        # None = sin comprobar
        self.error = None
        self.listening = False
        self.result = None           # (índice, texto) o (None, mensaje)
        self._loop = None
        self._thread = None

    def _ensure(self):
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
            self._thread.start()

    def listen(self, options, callsign, facility):
        if self.listening:
            return
        try:
            from winrt.windows.media.speechrecognition import SpeechRecognizer  # noqa: F401
        except Exception:
            self.available = False
            self.result = (None, "Reconocimiento de voz no disponible (falta el componente winrt).")
            return
        mapping = phrases_for(options, callsign, facility)
        if not mapping:
            self.result = (None, "No hay nada que transmitir ahora.")
            return
        self._ensure()
        self.listening = True
        asyncio.run_coroutine_threadsafe(self._recognize(mapping), self._loop)

    async def _recognize(self, mapping):
        from winrt.windows.globalization import Language
        from winrt.windows.media.speechrecognition import (SpeechRecognitionListConstraint, SpeechRecognizer)
        try:
            langs = [l.language_tag for l in SpeechRecognizer.supported_grammar_languages]
            tag = next((t for t in langs if t.lower().startswith("es")), None)
            if tag is None:
                self.result = (None, "Windows no tiene un reconocedor de voz en español. Instálelo en Configuración → Hora e "
                                     "idioma → Voz.")
                return
            rec = SpeechRecognizer(Language(tag))
            rec.constraints.append(SpeechRecognitionListConstraint(list(mapping.keys()), "radio"))
            comp = await rec.compile_constraints_async()
            if int(comp.status) != 0:
                self.result = (None, "No se pudo preparar el reconocimiento de voz.")
                return
            rec.timeouts.initial_silence_timeout = datetime.timedelta(seconds=4)
            rec.timeouts.end_silence_timeout = datetime.timedelta(seconds=0.8)
            res = await rec.recognize_async()
            text = (res.text or "").strip()
            conf = int(res.confidence)          # 0 alta · 1 media · 2 baja · 3 rechazada
            if text and conf <= 2 and text in mapping:
                self.result = (mapping[text], text)
            elif text:
                self.result = (None, f"No le he entendido bien («{text}»). Repita.")
            else:
                self.result = (None, "No le he oído. Pulse Ctrl derecho y hable con claridad.")
            self.available = True
        except Exception as ex:
            msg = str(ex)
            if "privacy" in msg.lower() or "denied" in msg.lower() or "0x80045509" in msg:
                self.result = (None, "Windows no deja usar el micrófono: Configuración → Privacidad → Micrófono → "
                                     "permitir a las aplicaciones de escritorio.")
            else:
                self.result = (None, f"Error del reconocimiento de voz: {msg[:80]}")
        finally:
            self.listening = False

    def poll(self):
        r, self.result = self.result, None
        return r
