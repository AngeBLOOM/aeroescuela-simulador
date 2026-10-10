"""Ejecuta las pruebas que no necesitan internet ni la caché de escenarios (datos/geo): las mismas que GitHub
lanza en cada pull request. Uso:  python tools/pruebas.py  [nombre ...]

Cada prueba es un programa aparte con su piloto robot; termina con error si algo sale mal. Las que cargan
aeropuertos reales (test_geo, test_lugar_real, test_misiones_svbs, test_ccs_maracay, test_ruta_continua,
test_noche_clima) descargan escenarios y se ejecutan a mano."""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = ["test_cabina_fisica", "test_frenos", "test_centro_gravedad", "test_physics", "test_aviones", "test_diamond",
         "test_ap", "test_instructor", "test_udp", "test_adf", "test_declinacion",
         "test_lessons", "test_emergencias", "test_atc_externo"]


def main(names):
    env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy", PYTHONIOENCODING="utf-8")
    rows = []
    for name in names:
        t0 = time.time()
        p = subprocess.run([sys.executable, os.path.join(ROOT, "tests", name + ".py")], cwd=ROOT, env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        secs = time.time() - t0
        out = (p.stdout + p.stderr).strip().splitlines()
        ok = p.returncode == 0
        rows.append((name, ok, secs, out[-1].strip() if out else ""))
        print(f"{'PASA ' if ok else 'FALLA'} {name:20s} {secs:5.0f} s  {rows[-1][3][:110]}", flush=True)
        if not ok:
            print("\n".join("    " + ln for ln in out[-25:]), flush=True)
    bad = [r for r in rows if not r[1]]
    print(f"\n{len(rows) - len(bad)} de {len(rows)} pruebas pasan")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"### Pruebas: {len(rows) - len(bad)} de {len(rows)} pasan\n\n| Prueba | Resultado | Tiempo | Última línea |\n"
                    "|---|---|---|---|\n")
            for name, ok, secs, last in rows:
                f.write(f"| `{name}` | {'✅ pasa' if ok else '❌ falla'} | {secs:.0f} s | {last[:120].replace('|', '/')} |\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or TESTS))
