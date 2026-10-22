"""Cifras del manual (POH) con que se valida el modelo de vuelo, y la tolerancia admitida en cada una.

El avión de referencia de AeroEscuela es el Cessna 172S: su consola física y su guía de pruebas (docs/) se basan en
él. Cada prueba indica la configuración del manual en que se mide; tools/validacion.py la vuela con un piloto robot
y compara. Las tolerancias siguen el orden de las de los dispositivos de instrucción (OACI Doc 9625: ±3 kt en
velocidad de pérdida, ±100 ft/min en ascenso, ±5 kt en velocidad, ±10-20 % en distancias).

Son valores típicos de los manuales publicados: para un avión concreto use siempre su propio POH y su hoja de peso.
Velocidades en KCAS (el simulador no tiene error de instalación del pitot, así que su velocidad indicada es la
calibrada); en el anemómetro del manual, las de pérdida son 48 KIAS (flaps arriba) y 40 KIAS (flaps 30°).
"""

C172S = dict(
    avion="c172",
    nombre="Cessna 172S Skyhawk",
    peso_lb=2550,                      # peso máximo de despegue: el de todas las tablas del manual
    pruebas=[
        dict(id="perdida_limpio", titulo="Velocidad de pérdida, flaps arriba",
             condicion="2550 lb, CG trasero, motor en ralentí, alas niveladas, deceleración de 1 kt/s",
             magnitud="KCAS", poh=53.0, tol=3.0, fuente="POH 172S, sección 5: velocidades de pérdida (53 KCAS)"),
        dict(id="perdida_flaps30", titulo="Velocidad de pérdida, flaps 30°",
             condicion="2550 lb, CG trasero, motor en ralentí, alas niveladas, deceleración de 1 kt/s",
             magnitud="KCAS", poh=48.0, tol=3.0, fuente="POH 172S, sección 5: velocidades de pérdida (48 KCAS)"),
        dict(id="ascenso", titulo="Régimen de ascenso máximo",
             condicion="2550 lb, nivel del mar ISA, potencia máxima, mezcla rica, flaps arriba, 74 KIAS (Vy)",
             magnitud="ft/min", poh=730.0, tol=100.0, fuente="POH 172S, sección 5: régimen de ascenso máximo"),
        dict(id="crucero_tas", titulo="Velocidad de crucero al 75 %",
             condicion="8000 ft de altitud de presión, ISA, 75 % de potencia, mezcla empobrecida",
             magnitud="KTAS", poh=124.0, tol=5.0, fuente="POH 172S, sección 5: crucero (124 KTAS al 75 % a 8000 ft)"),
        dict(id="crucero_consumo", titulo="Consumo en crucero al 75 %",
             condicion="8000 ft de altitud de presión, ISA, 75 % de potencia, mezcla empobrecida",
             magnitud="gal/h", poh=8.9, tol=0.9, fuente="POH 172S, sección 5: crucero (≈ 8,9 gal/h al 75 %)"),
        dict(id="planeo_relacion", titulo="Relación de planeo",
             condicion="2550 lb, motor parado con la hélice en molinete, flaps arriba, 68 KIAS",
             magnitud=": 1", poh=9.1, tol=0.9, fuente="POH 172S, sección 3: planeo máximo, 1,5 NM por cada 1000 ft"),
        dict(id="despegue_carrera", titulo="Despegue de pista corta: carrera",
             condicion="2550 lb, nivel del mar ISA, flaps 10°, potencia máxima antes de soltar frenos, "
                       "asfalto seco, sin viento, despegue a 51 KIAS",
             magnitud="ft", poh=960.0, tol=0.15, rel=True, fuente="POH 172S, sección 5: distancia de despegue"),
        dict(id="despegue_50ft", titulo="Despegue de pista corta: sobre 50 ft",
             condicion="la misma, 56 KIAS a 50 ft", magnitud="ft", poh=1630.0, tol=0.15, rel=True,
             fuente="POH 172S, sección 5: distancia de despegue"),
        dict(id="aterrizaje_carrera", titulo="Aterrizaje de pista corta: carrera",
             condicion="2550 lb, nivel del mar ISA, flaps 30°, ralentí, frenada máxima, asfalto seco, sin viento, "
                       "61 KIAS a 50 ft", magnitud="ft", poh=575.0, tol=0.20, rel=True,
             fuente="POH 172S, sección 5: distancia de aterrizaje"),
        dict(id="aterrizaje_50ft", titulo="Aterrizaje de pista corta: desde 50 ft",
             condicion="la misma", magnitud="ft", poh=1335.0, tol=0.15, rel=True,
             fuente="POH 172S, sección 5: distancia de aterrizaje"),
    ],
)

REFERENCIA = C172S
