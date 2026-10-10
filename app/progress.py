"""Progreso del alumno: mejores notas por lección y libro de vuelo (bitácora)."""
import json
import os
import time


class Progress:
    def __init__(self, path):
        self.path = path
        self.data = dict(lessons={}, logbook=[], total_s=0.0, landings=0)
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.data.update(json.load(f))
        except Exception:
            pass

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except Exception as ex:
            print("No se pudo guardar el progreso:", ex)

    def lesson(self, lid):
        return self.data["lessons"].get(lid, dict(best=None, attempts=0, passed=False))

    def record(self, lid, title, aircraft, result, flight_s, landings):
        L = self.data["lessons"].setdefault(lid, dict(best=None, attempts=0, passed=False))
        L["attempts"] += 1
        sc = round(result["score"], 1) if result else None
        if sc is not None and (L["best"] is None or sc > L["best"]):
            L["best"] = sc
        if result and result.get("passed"):
            L["passed"] = True
        self.data["total_s"] += flight_s
        self.data["landings"] += landings
        self.data["logbook"].insert(0, dict(
            fecha=time.strftime("%Y-%m-%d %H:%M"), leccion=title, avion=aircraft, duracion_min=round(flight_s / 60, 1),
            aterrizajes=landings, nota=sc, resultado=(result or {}).get("grade", "—")))
        self.data["logbook"] = self.data["logbook"][:300]
        self.save()
