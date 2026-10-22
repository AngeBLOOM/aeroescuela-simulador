"""Retardo interno del simulador: desde que se leen los mandos hasta que la imagen calculada con ellos se entrega a la
pantalla (pygame.display.flip).

Es la parte del retardo de transporte que depende del programa: lectura de mandos → física (240 Hz) → dibujo →
entrega. No incluye lo que añade el hardware (sondeo USB de los mandos, ~1-8 ms, ni el procesado y refresco del
monitor, ~5-30 ms): eso se mide de punta a punta con la consola montada (cámara rápida grabando mando y pantalla).
Las normas de los dispositivos de instrucción (OACI Doc 9625) fijan un máximo de retardo de transporte; en los
dispositivos básicos del orden de 300 ms y en los de nivel alto de 100 ms o menos.
"""
import json
import os
import time
from collections import deque


class LatencyMeter:
    def __init__(self, n=600, clock=time.perf_counter):
        self.samples = deque(maxlen=n)          # ms de los últimos n cuadros
        self.clock = clock
        self._t_input = None

    def mark_input(self):
        """Justo antes de leer los mandos del cuadro."""
        self._t_input = self.clock()

    def mark_frame(self):
        """Justo después de entregar la imagen (flip). Solo cuenta si en el cuadro se leyeron mandos."""
        if self._t_input is None:
            return None
        ms = (self.clock() - self._t_input) * 1000.0
        self._t_input = None
        self.samples.append(ms)
        return ms

    def stats(self):
        """(media, percentil 95, máximo) en ms, o None sin muestras."""
        if not self.samples:
            return None
        s = sorted(self.samples)
        p95 = s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]
        return sum(s) / len(s), p95, s[-1]

    @staticmethod
    def worst_case(p95_ms, fps):
        """Peor caso del programa: los mandos se leen una vez por cuadro, así que un movimiento justo después de la
        lectura espera un cuadro entero antes de contar; más el retardo interno (percentil 95)."""
        return p95_ms + 1000.0 / max(fps, 1.0)

    def report(self, path, fps=60.0, **info):
        """Guarda la última medición (JSON) para la guía de pruebas. Necesita al menos 100 cuadros."""
        st = self.stats()
        if st is None or len(self.samples) < 100:
            return False
        data = dict(fecha=time.strftime("%Y-%m-%d %H:%M"), cuadros=len(self.samples), fps=round(fps),
                    media_ms=round(st[0], 1), p95_ms=round(st[1], 1), max_ms=round(st[2], 1),
                    cuadro_ms=round(1000.0 / max(fps, 1.0), 1), peor_caso_ms=round(self.worst_case(st[1], fps), 1),
                    medido="lectura de mandos → imagen entregada (flip), más un cuadro de espera hasta la "
                           "lectura; sin USB ni monitor", **info)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        return True
