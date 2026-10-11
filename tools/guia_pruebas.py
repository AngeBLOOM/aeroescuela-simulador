"""Genera la guía de pruebas del simulador con el C172S de referencia (docs/GUIA_PRUEBAS_C172S.md) a partir de
mediciones reales: vuela la validación contra el manual (tools/validacion.py), lee el retardo medido en el último
vuelo (datos/retardo.json) y, con --pruebas, ejecuta además las pruebas funcionales (tools/pruebas.py).

Uso:  python tools/guia_pruebas.py [--pruebas]

La guía es la base del expediente para la autoridad (OACI Doc 9625: guía de pruebas de calificación). No certifica
nada por sí misma: la calificación la da la autoridad tras su propia evaluación del dispositivo instalado.
"""
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import validacion                                              # noqa: E402
from sim.poh import REFERENCIA                                 # noqa: E402

OUT = os.path.join(ROOT, "docs", "GUIA_PRUEBAS_C172S.md")


def version():
    try:
        h = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, capture_output=True,
                               text=True).stdout.strip()
        changed = [ln for ln in dirty.splitlines() if not ln.endswith("datos/config.json")]
        return h + (" (con cambios sin guardar)" if changed else "")
    except OSError:
        return "desconocida"


def doc_line(test):
    """Primera frase de la descripción de una prueba (su docstring)."""
    p = os.path.join(ROOT, "tests", test + ".py")
    try:
        src = open(p, encoding="utf-8").read()
    except OSError:
        return ""
    if '"""' not in src:
        return ""
    body = src.split('"""')[1].replace("\n", " ").strip()
    return body.split(". ")[0].rstrip(".") + "."


def fmt(v, mag):
    if v is None:
        return "—"
    return f"{v:,.0f}".replace(",", ".") if mag in ("ft", "ft/min") else f"{v:.1f}".replace(".", ",")


def main():
    run_tests = "--pruebas" in sys.argv
    print("Volando la validación contra el manual…")
    filas = validacion.medir()
    ok_val = sum(f["ok"] for f in filas)
    ret = None
    rp = os.path.join(ROOT, "datos", "retardo.json")
    if os.path.exists(rp):
        ret = json.load(open(rp, encoding="utf-8"))
    pruebas = None
    if run_tests:
        print("Ejecutando las pruebas funcionales…")
        import pruebas as P
        env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy", PYTHONIOENCODING="utf-8")
        pruebas = []
        for name in P.TESTS:
            r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", name + ".py")], cwd=ROOT, env=env,
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            pruebas.append((name, r.returncode == 0))
    import pruebas as P

    L = []
    a = L.append
    a(f"# Guía de pruebas — AeroEscuela con el {REFERENCIA['nombre']}")
    a("")
    a(f"Generada el {time.strftime('%d/%m/%Y a las %H:%M')} con `python tools/guia_pruebas.py"
      f"{' --pruebas' if run_tests else ''}` · versión del programa `{version()}`.")
    a("")
    a("> Esta guía reúne las pruebas objetivas y funcionales del dispositivo para el expediente ante la autoridad "
      "aeronáutica (guía de pruebas de calificación, OACI Doc 9625). **No es una certificación:** la calificación la "
      "otorga la autoridad tras evaluar el dispositivo instalado, con su consola física y sus pantallas. Las cifras del "
      "manual son las típicas publicadas del C172S; para un avión concreto deben usarse las de su propio POH.")
    a("")
    a("## 1. Identificación del dispositivo")
    a("")
    a("| | |")
    a("|---|---|")
    a("| Dispositivo | AeroEscuela, simulador de entrenamiento de pilotos (programa propio, Python) |")
    a(f"| Avión de referencia | {REFERENCIA['nombre']} (consola física y cabina automática; los otros seis aviones se "
      "vuelan sin consola) |")
    a("| Modelo de vuelo | Cuerpo rígido de 6 grados de libertad a 240 Hz, aerodinámica no lineal con pérdida y barrena, "
      "motor de pistón, tren con amortiguadores |")
    a("| Instrumentos | Seis básicos y G1000 (PFD y MFD), con fallas; VOR, ILS, DME, NDB/ADF, GPS con aproximaciones RNAV "
      "de entrenamiento; piloto automático tipo GFC 700 |")
    a("| Vista exterior | Relieve y fotografía satelital reales, 51 × 51 km; uno o varios monitores |")
    a("| Puesto del instructor | En el simulador (tecla I) y por navegador en la red local |")
    a("")
    a("## 2. Pruebas objetivas: el modelo de vuelo contra el manual")
    a("")
    a(f"Cada prueba la vuela un piloto robot en la configuración del manual ({REFERENCIA['peso_lb']} lb, nivel del mar ISA "
      "sin viento salvo donde se indica). Las tolerancias siguen el orden de las del Doc 9625 para dispositivos de "
      f"instrucción. **Resultado: {ok_val} de {len(filas)} dentro de tolerancia.**")
    a("")
    a("| # | Prueba | Condición | Manual | Medido | Tolerancia | Resultado | Fuente |")
    a("|---|---|---|---|---|---|---|---|")
    for i, f in enumerate(filas, 1):
        tol = f"±{f['tol'] * 100:.0f} %" if f.get("rel") else f"±{f['tol']:g} {f['magnitud']}".replace(".", ",")
        a(f"| {i} | {f['titulo']} | {f['condicion']} | {fmt(f['poh'], f['magnitud'])} {f['magnitud']} | "
          f"{fmt(f['medido'], f['magnitud'])} {f['magnitud']} | {tol} | {'✅ dentro' if f['ok'] else '❌ fuera'} | "
          f"{f['fuente']} |")
    a("")
    a("Se repite en cada cambio del programa con `tests/test_validacion.py`, que falla si alguna cifra sale de "
      "tolerancia.")
    a("")
    a("## 3. Retardo de transporte")
    a("")
    if ret:
        a(f"Medido en vuelo el {ret['fecha']} ({ret.get('avion', '')}, {ret.get('resolucion', '')}, {ret['fps']} imágenes "
          f"por segundo, {ret['cuadros']} cuadros): desde la lectura de los mandos hasta la entrega de la imagen.")
        a("")
        a("| | ms |")
        a("|---|---|")
        c = lambda v: f"{v:.1f}".replace(".", ",")                                    # noqa: E731
        a(f"| Retardo interno medio | {c(ret['media_ms'])} |")
        a(f"| Retardo interno, percentil 95 | {c(ret['p95_ms'])} |")
        a(f"| Un cuadro (espera hasta la lectura de los mandos) | {c(ret['cuadro_ms'])} |")
        a(f"| **Peor caso del programa** | **{c(ret['peor_caso_ms'])}** |")
    else:
        a("Sin medición todavía: vuele unos minutos y termine el vuelo; el simulador guarda `datos/retardo.json`. Pulse F9 "
          "para verlo en vuelo.")
    a("")
    a("No incluye el sondeo USB de los mandos (~1-8 ms) ni el procesado y el refresco del monitor (~5-30 ms). **Pendiente "
      "con la consola montada:** medición de punta a punta con una cámara rápida que grabe a la vez el mando y la "
      "pantalla.")
    a("")
    a("## 4. Pruebas funcionales")
    a("")
    a("Programas con piloto robot que comprueban cada sistema sin intervención (`python tools/pruebas.py`). GitHub las "
      "ejecuta en cada cambio.")
    a("")
    a("| Prueba | Qué comprueba" + (" | Resultado |" if pruebas else " |"))
    a("|---|---" + ("|---|" if pruebas else "|"))
    res = dict(pruebas or [])
    for name in P.TESTS:
        r = f" | {'✅ pasa' if res.get(name) else '❌ falla'} |" if pruebas else " |"
        a(f"| `{name}` | {doc_line(name)}{r}")
    a("")
    a("Con escenarios reales (se ejecutan a mano, necesitan la caché `datos/geo`): `test_misiones_svbs`, "
      "`test_ccs_maracay`, `test_ruta_continua`, `test_noche_clima`, `test_lugar_real`.")
    a("")
    a("## 5. Comprobaciones del inspector con la consola montada")
    a("")
    a("| Comprobación | Resultado | Observaciones |")
    a("|---|---|---|")
    for c in ("Cada mando de la consola mueve su función en el simulador en el sentido correcto (Cabina física → "
              "Diagnóstico y prueba)", "Interruptores y magnetos sincronizados con el avión al empezar el vuelo",
              "Calibración de ejes: recorrido completo y centro", "Retardo de punta a punta medido con cámara",
              "Instrumentos legibles en su pantalla, sin mandos dibujados", "Fallas provocadas desde el puesto del "
              "instructor y su procedimiento", "Congelar, reposicionar y repetición desde el puesto del instructor",
              "Aproximaciones RNAV marcadas como de entrenamiento, no publicadas"):
        a(f"| {c} | ☐ conforme ☐ no conforme | |")
    a("")
    a("## 6. Firmas")
    a("")
    a("| | Nombre | Firma | Fecha |")
    a("|---|---|---|---|")
    a("| Responsable del dispositivo | | | |")
    a("| Instructor de vuelo | | | |")
    a("| Inspector de la autoridad | | | |")
    a("")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(L))
    print(f"Guía escrita en {os.path.relpath(OUT, ROOT)}: validación {ok_val}/{len(filas)}"
          + (f", pruebas {sum(ok for _, ok in pruebas)}/{len(pruebas)}" if pruebas else ""))


if __name__ == "__main__":
    main()
