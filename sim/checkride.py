"""Examen práctico completo (checkride): encadena las tareas del ACS una tras otra, como
hace el examinador, y da una nota por tarea y el resultado final.

Criterio: hay que superar TODAS las tareas (nota ≥ 70 en cada una). Un accidente o una tarea
insatisfactoria hace que el examen sea «No apto», como en el examen real (una tarea no
superada = examen no superado, aunque se pueda repetir esa tarea más adelante).
"""
from .lessons import IR, PPL, Lesson


class Checkride(Lesson):
    category = "9 · Examen práctico"
    duration = "45–60 min"
    tasks = []

    def __init__(self):
        super().__init__()
        self.k = 0
        self.sub = None
        self.results = []

    def setup(self, world):
        self.world_ref = world
        self.k = 0
        self.results = []
        self._start_task(world)

    def _start_task(self, world):
        from .lessons import LESSONS_BY_ID
        cls = LESSONS_BY_ID[self.tasks[self.k]]
        if world.aircraft_id != cls.aircraft:
            world.set_aircraft(cls.aircraft)
        self.sub = cls()
        self.sub.setup(world)
        self.say(f"Tarea {self.k + 1} de {len(self.tasks)}: {self.sub.title}. {self.sub.brief.split('—')[-1].split('.')[0]}.")

    @property
    def rings(self):
        return self.sub.rings if self.sub is not None else []

    @rings.setter
    def rings(self, v):
        pass

    @property
    def checklist(self):
        return getattr(self.sub, "checklist", None) if self.sub is not None else None

    @checklist.setter
    def checklist(self, v):
        pass

    def update(self, dt, world, events):
        if self.done:
            return
        self.t += dt
        sub = self.sub
        sub.update(dt, world, events)
        self.messages += sub.messages
        sub.messages.clear()
        if sub.done:
            R = sub.result(world)
            self.results.append((sub.title, sub.acs, R))
            if world.ac.crashed:
                self.finish(False, f"Accidente en la tarea «{sub.title}»", world)
                return
            self.k += 1
            if self.k >= len(self.tasks):
                ok = all(r["passed"] for _, _, r in self.results)
                self.finish(ok, "" if ok else "Una o más tareas no superadas", world)
            else:
                self.say(f"Tarea terminada: {R['score']:.0f} puntos.")
                self._start_task(world)

    def hud(self, world):
        lines = [("paso", f"EXAMEN · tarea {self.k + 1}/{len(self.tasks)}: {self.sub.title}")] if self.sub else []
        return lines + (self.sub.hud(world) if self.sub else [])

    def result(self, world):
        if self.sub is not None and not self.sub.done and self.k < len(self.tasks):
            self.results.append((self.sub.title, self.sub.acs, self.sub.result(world)))
        items = []
        for title, acs, R in self.results:
            items.append((f"{acs} · {title}", round(R["score"]), 100,
                          ("APTO" if R["passed"] else "NO APTO") + (f" — {R['reason']}" if R.get("reason") else "")))
        done = len(self.results)
        for k in range(done, len(self.tasks)):
            from .lessons import LESSONS_BY_ID
            c = LESSONS_BY_ID[self.tasks[k]]
            items.append((f"{c.acs} · {c.title}", 0, 100, "no realizada"))
        score = sum(i[1] for i in items) / max(1, len(items))
        passed = done == len(self.tasks) and all(R["passed"] for _, _, R in self.results)
        grade = "APTO" if passed else "NO APTO"
        return dict(score=score, grade=grade, items=items, success=passed, reason=self.fail_reason,
                    passed=passed, acs=self.acs, standard=self.standard)


class C_PPL(Checkride):
    id = "examen_ppl"
    title = "Examen práctico de Piloto Privado"
    acs = "FAA-S-ACS-6C"
    standard = PPL
    brief = ("Examen práctico completo de Piloto Privado (equivalente a la prueba de pericia PPL(A) de EASA). El examinador "
             "le pedirá, una tras otra, las tareas del ACS: despegue normal, virajes escarpados, vuelo lento, pérdidas con y sin "
             "motor, falla de motor con aterrizaje de emergencia, motor y al aire y aterrizaje normal. Para aprobar hay que "
             "superar todas las tareas dentro de las tolerancias del ACS.")
    objectives = ["Todas las tareas ≥ 70 puntos", "Sin accidentes", "Tolerancias ACS en cada maniobra"]
    tasks = ["despegue", "escarpados", "vuelo_lento", "perdida", "perdida_motor", "motor", "motor_aire", "final"]


class C_IR(Checkride):
    id = "examen_ir"
    title = "Examen práctico de Vuelo Instrumental"
    acs = "FAA-S-ACS-8C"
    standard = IR
    brief = ("Examen práctico de la habilitación instrumental (equivalente a la prueba de pericia IR(A) de EASA): espera "
             "sobre un VOR, panel parcial, actitudes anormales, aproximación de precisión ILS, aproximación de no precisión y "
             "aproximación frustrada.")
    objectives = ["Todas las tareas ≥ 70 puntos", "Sin bajar de mínimos", "Tolerancias ACS IR"]
    tasks = ["espera", "parcial", "actitudes", "ils", "loc", "frustrada"]


CHECKRIDES = [C_PPL, C_IR]
