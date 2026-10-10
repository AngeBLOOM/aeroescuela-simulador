"""Alumnos (cada uno con su progreso y bitácora) e informes imprimibles.

- datos/progreso.json           → alumno por defecto («Alumno»), compatible con versiones anteriores
- datos/alumnos/<nombre>.json   → resto de alumnos
- datos/informes/*.html         → informes del vuelo y del alumno; se abren en el navegador y desde
                                  ahí se imprimen o se guardan como PDF (Ctrl+P → «Guardar como PDF»)
"""
import html
import json
import os
import re
import time

from .progress import Progress

DEFAULT = "Alumno"


def slug(name):
    s = re.sub(r"[^\w\- ]", "", name, flags=re.UNICODE).strip().replace(" ", "_")
    return s or "alumno"


class Students:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.dir = os.path.join(data_dir, "alumnos")
        os.makedirs(self.dir, exist_ok=True)

    def path(self, name):
        if name == DEFAULT:
            return os.path.join(self.data_dir, "progreso.json")
        return os.path.join(self.dir, slug(name) + ".json")

    def names(self):
        out = [DEFAULT]
        for fn in sorted(os.listdir(self.dir)):
            if fn.endswith(".json"):
                try:
                    with open(os.path.join(self.dir, fn), encoding="utf-8") as f:
                        out.append(json.load(f).get("nombre") or fn[:-5].replace("_", " "))
                except Exception:
                    out.append(fn[:-5].replace("_", " "))
        return out

    def load(self, name):
        p = Progress(self.path(name))
        p.data.setdefault("nombre", name)
        return p

    def create(self, name):
        name = name.strip()[:40]
        if not name:
            return None
        p = self.load(name)
        p.data["nombre"] = name
        p.data.setdefault("alta", time.strftime("%Y-%m-%d"))
        p.save()
        return name


# ------------------------------------------------------------------ informes HTML
CSS = """body{font:14px Bahnschrift,'Segoe UI',Arial,sans-serif;color:#10202e;margin:28px auto;max-width:980px;padding:26px 30px;
background:#fff;position:relative;border:1px solid #9fdcef;clip-path:polygon(18px 0,100% 0,100% calc(100% - 18px),calc(100% - 18px) 100%,0 100%,0 18px)}
body:before{content:"AEROESCUELA · INFORME DE ENTRENAMIENTO";display:block;letter-spacing:4px;font-size:11px;color:#0098c4;
border-bottom:2px solid #00c8f0;padding-bottom:6px;margin-bottom:14px}
h1{font-size:25px;margin:0;letter-spacing:1px;text-transform:uppercase}
h2{font-size:13px;color:#007fa6;letter-spacing:3px;text-transform:uppercase;border-left:4px solid #00c8f0;padding:3px 0 3px 10px;
margin-top:24px;background:linear-gradient(90deg,#e4f8fe,#fff)}
.sub{color:#4d6478}.big{font:700 46px 'OCR A Extended','OCR-A BT',Consolas,monospace}.ok{color:#0b9a5c}.bad{color:#d1373a}.mid{color:#c78100}
table{border-collapse:collapse;width:100%;margin-top:6px}td,th{border-bottom:1px solid #d3e9f1;padding:6px 7px;text-align:left;vertical-align:top}
th{background:#06202e;font-size:11px;text-transform:uppercase;letter-spacing:2px;color:#7fe6ff}td.n{text-align:right;white-space:nowrap;
font-family:'OCR A Extended','OCR-A BT',Consolas,monospace}tr:nth-child(even) td{background:#f5fbfd}
.firma{margin-top:40px;display:flex;gap:60px}.firma div{border-top:2px solid #00c8f0;padding-top:4px;width:260px;color:#4d6478;
letter-spacing:1px;font-size:12px;text-transform:uppercase}
button{background:#06202e;color:#7fe6ff;border:1px solid #00c8f0;padding:8px 16px;letter-spacing:2px;cursor:pointer;
clip-path:polygon(8px 0,100% 0,100% calc(100% - 8px),calc(100% - 8px) 100%,0 100%,0 8px)}
svg{border:1px solid #cfeaf3}
@media print{body{margin:0 auto;border:none;clip-path:none}button{display:none}
*{-webkit-print-color-adjust:exact;print-color-adjust:exact}}"""


def _svg_chart(t, vals, title, color, w=900, h=150):
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-6:
        hi = lo + 1
    t0, t1 = t[0], t[-1] if t[-1] > t[0] else t[0] + 1
    step = max(1, len(vals) // 600)
    pts = " ".join(f"{40 + (t[i] - t0) / (t1 - t0) * (w - 50):.1f},{h - 20 - (vals[i] - lo) / (hi - lo) * (h - 40):.1f}"
                   for i in range(0, len(vals), step))
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" style="background:#f7f9fc;border-radius:6px;margin:4px 0">'
            f'<text x="44" y="16" font-size="12" fill="#45566b">{html.escape(title)}</text>'
            f'<text x="4" y="24" font-size="10" fill="#7a8899">{hi:.0f}</text><text x="4" y="{h - 20}" font-size="10" fill="#7a8899">{lo:.0f}</text>'
            f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{pts}"/></svg>')


def flight_report(path, student, title, aircraft, place, result, rec_array, fields, flight_s, landings, extra=None):
    """Informe de un vuelo (lección, nota, puntos de evaluación y gráficas)."""
    R = result
    rows = ""
    if R:
        for name, got, mx, com in R["items"]:
            cls = "ok" if (mx and got >= 0.75 * mx) else ("bad" if got < 0 or (mx and got < 0.4 * mx) else "mid")
            pts = f"{got}/{mx}" if mx else f"{got:+d}"
            rows += f"<tr><td>{html.escape(str(name))}</td><td class='n {cls}'>{pts}</td><td>{html.escape(str(com))}</td></tr>"
    charts = ""
    a = rec_array
    if a is not None and len(a) > 5:
        t = list(a[:, 0] - a[0, 0])
        for key, lab, col in (("alt", "Altitud (ft)", "#1c5ca8"), ("ias", "Velocidad indicada (kt)", "#1d8a45"),
                              ("vs", "Velocidad vertical (ft/min)", "#b9770e")):
            if key in fields:
                charts += _svg_chart(t, list(a[:, fields.index(key)]), lab, col)
    score = (f"<div class='big {'ok' if R['passed'] else 'bad'}'>{R['score']:.0f}<span class='sub' style='font-size:18px'> / 100 · "
             f"{html.escape(R['grade'])}</span></div><p>{'APTO' if R['passed'] else 'NO APTO'} — estándar {html.escape(R.get('standard', ''))} "
             f"· tarea {html.escape(R.get('acs', ''))}</p>") if R else "<p>Vuelo libre (sin evaluación)</p>"
    extras = "".join(f"<p>{html.escape(x)}</p>" for x in (extra or []))
    doc = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Informe de vuelo · {html.escape(student)}</title>
<style>{CSS}</style></head><body><button onclick="print()">Imprimir / Guardar PDF</button>
<h1>Informe de vuelo — {html.escape(title)}</h1>
<p class="sub">Alumno: <b>{html.escape(student)}</b> · {time.strftime('%d/%m/%Y %H:%M')} · {html.escape(aircraft)} · {html.escape(place)}
· {flight_s / 60:.1f} min de vuelo · {landings} aterrizaje(s)</p>
{score}{extras}
<h2>Evaluación por puntos</h2><table><tr><th>Concepto</th><th>Puntos</th><th>Observación</th></tr>{rows}</table>
<h2>Registro del vuelo</h2>{charts}
<div class="firma"><div>Firma del instructor</div><div>Firma del alumno</div></div>
<p class="sub" style="margin-top:30px">AeroEscuela — simulador de entrenamiento de procedimientos. No es un dispositivo certificado (FTD/FFS).</p>
</body></html>"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return path


def student_report(path, progress, lessons):
    """Informe del alumno: estado de cada tarea del programa y bitácora."""
    d = progress.data
    name = d.get("nombre", DEFAULT)
    rows = ""
    cat = None
    for C in lessons:
        if C.category != cat:
            cat = C.category
            rows += f"<tr><th colspan='5'>{html.escape(cat)}</th></tr>"
        P = progress.lesson(C.id)
        best = "—" if P["best"] is None else f"{P['best']:.0f}"
        st = "<b class='ok'>Superada</b>" if P["passed"] else ("<span class='mid'>En curso</span>" if P["attempts"] else "Pendiente")
        rows += (f"<tr><td>{html.escape(C.acs)}</td><td>{html.escape(C.title)}</td><td class='n'>{P['attempts']}</td>"
                 f"<td class='n'>{best}</td><td>{st}</td></tr>")
    log = "".join(f"<tr><td>{html.escape(e['fecha'])}</td><td>{html.escape(e['leccion'])}</td><td>{html.escape(e['avion'])}</td>"
                  f"<td class='n'>{e['duracion_min']}</td><td class='n'>{e['aterrizajes']}</td>"
                  f"<td class='n'>{'—' if e['nota'] is None else e['nota']}</td><td>{html.escape(str(e['resultado']))}</td></tr>"
                  for e in d.get("logbook", [])[:120])
    passed = sum(1 for C in lessons if progress.lesson(C.id)["passed"])
    doc = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Ficha del alumno · {html.escape(name)}</title>
<style>{CSS}</style></head><body><button onclick="print()">Imprimir / Guardar PDF</button>
<h1>Ficha del alumno — {html.escape(name)}</h1>
<p class="sub">Emitida el {time.strftime('%d/%m/%Y')} · {d.get('total_s', 0) / 3600:.1f} h de simulador · {d.get('landings', 0)} aterrizajes ·
{passed}/{len(lessons)} lecciones superadas</p>
<h2>Programa de entrenamiento (FAA ACS / equivalente EASA)</h2>
<table><tr><th>Tarea</th><th>Lección</th><th>Intentos</th><th>Mejor nota</th><th>Estado</th></tr>{rows}</table>
<h2>Bitácora</h2><table><tr><th>Fecha</th><th>Lección</th><th>Avión</th><th>Min</th><th>Aterr.</th><th>Nota</th><th>Resultado</th></tr>{log}</table>
<div class="firma"><div>Firma del instructor</div><div>Firma del alumno</div></div>
<p class="sub" style="margin-top:30px">Las horas de simulador de AeroEscuela no son horas de instrucción registrables (no es un FTD/FFS certificado).</p>
</body></html>"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return path


def open_file(path):
    try:
        os.startfile(path)              # Windows: abre en el navegador predeterminado
    except Exception as ex:
        print("No se pudo abrir el informe:", ex)
