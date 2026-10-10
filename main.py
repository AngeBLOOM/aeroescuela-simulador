"""AeroEscuela — Simulador de entrenamiento de vuelo.

Ejecutar:  python main.py
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    from app.core import App
    try:
        App().run()
    except Exception:
        from app.core import DATA
        log = os.path.join(DATA, "error.log")
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
