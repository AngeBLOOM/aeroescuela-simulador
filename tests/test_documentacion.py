"""Herramientas de la documentación: el chequeo anota en el registro de mantenimiento (CSV con cabecera una sola vez)
y la guía de pruebas encuentra la descripción de cada prueba de tools/pruebas.py."""
import csv
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import chequeo
import guia_pruebas
import pruebas

p = os.path.join(tempfile.mkdtemp(), "datos", "mantenimiento.csv")
chequeo.log(dict(fecha="2026-10-11 08:00", version="abc1234", responsable="Prueba", pruebas="20/20", fallos="", nota="a"), p)
chequeo.log(dict(fecha="2026-10-11 09:00", version="abc1234", responsable="Prueba", pruebas="19/20", fallos="test_x",
                 nota="b"), p)
rows = list(csv.DictReader(open(p, encoding="utf-8")))
assert [r["pruebas"] for r in rows] == ["20/20", "19/20"] and rows[1]["fallos"] == "test_x", rows
print("registro de mantenimiento OK")

missing = [t for t in pruebas.TESTS if len(guia_pruebas.doc_line(t)) < 10]
assert not missing, f"pruebas sin descripción para la guía: {missing}"
assert guia_pruebas.version()
print(f"descripción de las {len(pruebas.TESTS)} pruebas OK")
print("TODO OK")
