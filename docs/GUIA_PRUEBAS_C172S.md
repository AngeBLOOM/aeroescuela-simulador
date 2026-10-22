# Guía de pruebas — AeroEscuela con el Cessna 172S Skyhawk

Generada el 10/10/2026 a las 23:32 con `python tools/guia_pruebas.py --pruebas` · versión del programa `fdba4eb`.

> Esta guía reúne las pruebas objetivas y funcionales del dispositivo para el expediente ante la autoridad aeronáutica (guía de pruebas de calificación, OACI Doc 9625). **No es una certificación:** la calificación la otorga la autoridad tras evaluar el dispositivo instalado, con su consola física y sus pantallas. Las cifras del manual son las típicas publicadas del C172S; para un avión concreto deben usarse las de su propio POH.

## 1. Identificación del dispositivo

| | |
|---|---|
| Dispositivo | AeroEscuela, simulador de entrenamiento de pilotos (programa propio, Python) |
| Avión de referencia | Cessna 172S Skyhawk (consola física y cabina automática; los otros seis aviones se vuelan sin consola) |
| Modelo de vuelo | Cuerpo rígido de 6 grados de libertad a 240 Hz, aerodinámica no lineal con pérdida y barrena, motor de pistón, tren con amortiguadores |
| Instrumentos | Seis básicos y G1000 (PFD y MFD), con fallas; VOR, ILS, DME, NDB/ADF, GPS con aproximaciones RNAV de entrenamiento; piloto automático tipo GFC 700 |
| Vista exterior | Relieve y fotografía satelital reales, 51 × 51 km; uno o varios monitores |
| Puesto del instructor | En el simulador (tecla I) y por navegador en la red local |

## 2. Pruebas objetivas: el modelo de vuelo contra el manual

Cada prueba la vuela un piloto robot en la configuración del manual (2550 lb, nivel del mar ISA sin viento salvo donde se indica). Las tolerancias siguen el orden de las del Doc 9625 para dispositivos de instrucción. **Resultado: 10 de 10 dentro de tolerancia.**

| # | Prueba | Condición | Manual | Medido | Tolerancia | Resultado | Fuente |
|---|---|---|---|---|---|---|---|
| 1 | Velocidad de pérdida, flaps arriba | 2550 lb, CG trasero, motor en ralentí, alas niveladas, deceleración de 1 kt/s | 53,0 KCAS | 54,7 KCAS | ±3 KCAS | ✅ dentro | POH 172S, sección 5: velocidades de pérdida (53 KCAS) |
| 2 | Velocidad de pérdida, flaps 30° | 2550 lb, CG trasero, motor en ralentí, alas niveladas, deceleración de 1 kt/s | 48,0 KCAS | 47,7 KCAS | ±3 KCAS | ✅ dentro | POH 172S, sección 5: velocidades de pérdida (48 KCAS) |
| 3 | Régimen de ascenso máximo | 2550 lb, nivel del mar ISA, potencia máxima, mezcla rica, flaps arriba, 74 KIAS (Vy) | 730 ft/min | 673 ft/min | ±100 ft/min | ✅ dentro | POH 172S, sección 5: régimen de ascenso máximo |
| 4 | Velocidad de crucero al 75 % | 8000 ft de altitud de presión, ISA, 75 % de potencia, mezcla empobrecida | 124,0 KTAS | 125,4 KTAS | ±5 KTAS | ✅ dentro | POH 172S, sección 5: crucero (124 KTAS al 75 % a 8000 ft) |
| 5 | Consumo en crucero al 75 % | 8000 ft de altitud de presión, ISA, 75 % de potencia, mezcla empobrecida | 8,9 gal/h | 9,5 gal/h | ±0,9 gal/h | ✅ dentro | POH 172S, sección 5: crucero (≈ 8,9 gal/h al 75 %) |
| 6 | Relación de planeo | 2550 lb, motor parado con la hélice en molinete, flaps arriba, 68 KIAS | 9,1 : 1 | 8,9 : 1 | ±0,9 : 1 | ✅ dentro | POH 172S, sección 3: planeo máximo, 1,5 NM por cada 1000 ft |
| 7 | Despegue de pista corta: carrera | 2550 lb, nivel del mar ISA, flaps 10°, potencia máxima antes de soltar frenos, asfalto seco, sin viento, despegue a 51 KIAS | 960 ft | 876 ft | ±15 % | ✅ dentro | POH 172S, sección 5: distancia de despegue |
| 8 | Despegue de pista corta: sobre 50 ft | la misma, 56 KIAS a 50 ft | 1.630 ft | 1.806 ft | ±15 % | ✅ dentro | POH 172S, sección 5: distancia de despegue |
| 9 | Aterrizaje de pista corta: carrera | 2550 lb, nivel del mar ISA, flaps 30°, ralentí, frenada máxima, asfalto seco, sin viento, 61 KIAS a 50 ft | 575 ft | 576 ft | ±20 % | ✅ dentro | POH 172S, sección 5: distancia de aterrizaje |
| 10 | Aterrizaje de pista corta: desde 50 ft | la misma | 1.335 ft | 1.276 ft | ±15 % | ✅ dentro | POH 172S, sección 5: distancia de aterrizaje |

Se repite en cada cambio del programa con `tests/test_validacion.py`, que falla si alguna cifra sale de tolerancia.

## 3. Retardo de transporte

Medido en vuelo el 2026-10-10 22:56 (C172S, 1600x900, 30 imágenes por segundo, 600 cuadros): desde la lectura de los mandos hasta la entrega de la imagen.

| | ms |
|---|---|
| Retardo interno medio | 10,2 |
| Retardo interno, percentil 95 | 16,7 |
| Un cuadro (espera hasta la lectura de los mandos) | 33,7 |
| **Peor caso del programa** | **50,4** |

No incluye el sondeo USB de los mandos (~1-8 ms) ni el procesado y el refresco del monitor (~5-30 ms). **Pendiente con la consola montada:** medición de punta a punta con una cámara rápida que grabe a la vez el mando y la pantalla.

## 4. Pruebas funcionales

Programas con piloto robot que comprueban cada sistema sin intervención (`python tools/pruebas.py`). GitHub las ejecuta en cada cambio.

| Prueba | Qué comprueba | Resultado |
|---|---|---|
| `test_cabina_fisica` | Prueba de la cabina física con mandos USB simulados (sin ventana ni mandos reales): calibración de ejes, sincronización de los interruptores al empezar el vuelo, conexión en caliente y que el joystick genérico no lea un mando que ya está asignado en «Cabina física». | ✅ pasa |
| `test_frenos` | Frenos diferenciales: rodando despacio, frenar solo la rueda derecha gira el avión a la derecha (y la izquierda a la izquierda); los dos frenos a la vez lo paran en línea recta. | ✅ pasa |
| `test_centro_gravedad` | Centro de gravedad: con el CG adelante hace falta más compensador y más profundidad (tirar) para volar despacio; con el CG atrás, menos, y el avión es menos estable. | ✅ pasa |
| `test_physics` | Pruebas rápidas del modelo de vuelo (sin gráficos). | ✅ pasa |
| `test_aviones` | Despegue con alumno robot en cada avión: comprueba que todos despegan y ascienden a su Vy con las velocidades de su manual (Vr y Vy de cada tipo). | ✅ pasa |
| `test_diamond` | Pruebas de rendimiento de los Diamond DA40 y DA42 (incluye vuelo con un motor y Vmc). | ✅ pasa |
| `test_ap` | Prueba del piloto automático: ILS acoplado y mantenimiento de rumbo/altitud. | ✅ pasa |
| `test_instructor` | Herramientas del instructor: congelar altitud, posición y combustible; acelerar el tiempo (y que vuelva a ×1 cerca del suelo); mover el avión en vuelo; y las mismas órdenes desde el puesto web (sin ventana). | ✅ pasa |
| `test_udp` | Salida UDP: un receptor en esta misma computadora recibe los datagramas JSON a la frecuencia pedida, con los valores del avión (posición, velocidad, rumbo, motores), los avisos (pérdida) y los dos motores del DA42. | ✅ pasa |
| `test_adf` | ADF y NDB: marcación relativa correcta, alcance, sin corriente, sintonía en kHz, que el NAV no se engancha a un NDB, un vuelo hacia el NDB siguiendo la aguja (paso por la vertical) y la lectura de filas reales de OurAirports. | ✅ pasa |
| `test_declinacion` | Declinación magnética (13° oeste, como en Venezuela) en el escenario escuela: la brújula, el direccional, el VOR, el piloto automático (HDG y NAV), el OBS al colocar el avión, el viento que da la torre y los rumbos que dictan las lecciones son magnéticos; la física y la evaluación siguen en verdadero. | ✅ pasa |
| `test_hielo_carb` | Hielo en el carburador: se forma con aire húmedo entre -15 y 32 °C (más con el gas reducido), baja las rpm y puede parar el motor; la calefacción lo funde (el motor va peor unos segundos) y cuesta algo de potencia. | ✅ pasa |
| `test_barrena` | Barrena y turbulencia de giro (C172): - con pérdida, palanca atrás y pedal a fondo el avión entra en barrena (3-4 s por vuelta, morro muy abajo); - con PARE (ralentí, alerones neutros, pedal contrario, palanca adelante) sale en menos de 1,5 vueltas y se recupera   del picado sin pasar de VNE ni de 3,8 G; - una pérdida coordinada (pedal neutro) no entra en barrena; - la turbulencia fuerte hace girar el avión (alabeo, cabeceo y guiñada) y sin turbulencia no hay giros. | ✅ pasa |
| `test_gps` | GPS: base de datos, «Directo a», desvío lateral y escala del CDI, curso magnético, modo OBS, y un vuelo con el piloto automático en NAV siguiendo un plan de tres puntos con la secuencia automática de tramos. | ✅ pasa |
| `test_rnav` | Aproximaciones RNAV (GPS) de entrenamiento: geometría del procedimiento en T, escala de aproximación, senda vertical como la del ILS, y un vuelo con el piloto automático en APR acoplado desde el IF hasta la altura de decisión. | ✅ pasa |
| `test_retardo` | Medidor del retardo interno (app/latency.py): cuenta solo los cuadros en que se leyeron mandos, calcula media, percentil 95 y máximo, y guarda el informe para la guía de pruebas solo con suficientes cuadros. | ✅ pasa |
| `test_lessons` | Alumno robot: vuela lecciones con un controlador sencillo para validar la evaluación. | ✅ pasa |
| `test_emergencias` | Prueba de las lecciones de emergencia con un alumno robot que aplica el procedimiento. | ✅ pasa |
| `test_atc_externo` | Prueba del enlace con un simulador de ATC externo (sin ventana): un cliente TCP hace de consola de controlador, saluda, toma la torre, publica un tráfico, manda una autorización y recibe el estado del avión y la transmisión del piloto. | ✅ pasa |
| `test_validacion` | Validación contra el manual: el C172S de referencia, volado por el piloto robot de tools/validacion.py, debe dar cada cifra de sim/poh.py (pérdida, ascenso, crucero, consumo, planeo, despegue y aterrizaje) dentro de su tolerancia. | ✅ pasa |
| `test_documentacion` | Herramientas de la documentación: el chequeo anota en el registro de mantenimiento (CSV con cabecera una sola vez) y la guía de pruebas encuentra la descripción de cada prueba de tools/pruebas.py. | ✅ pasa |

Con escenarios reales (se ejecutan a mano, necesitan la caché `datos/geo`): `test_misiones_svbs`, `test_ccs_maracay`, `test_ruta_continua`, `test_noche_clima`, `test_lugar_real`.

## 5. Comprobaciones del inspector con la consola montada

| Comprobación | Resultado | Observaciones |
|---|---|---|
| Cada mando de la consola mueve su función en el simulador en el sentido correcto (Cabina física → Diagnóstico y prueba) | ☐ conforme ☐ no conforme | |
| Interruptores y magnetos sincronizados con el avión al empezar el vuelo | ☐ conforme ☐ no conforme | |
| Calibración de ejes: recorrido completo y centro | ☐ conforme ☐ no conforme | |
| Retardo de punta a punta medido con cámara | ☐ conforme ☐ no conforme | |
| Instrumentos legibles en su pantalla, sin mandos dibujados | ☐ conforme ☐ no conforme | |
| Fallas provocadas desde el puesto del instructor y su procedimiento | ☐ conforme ☐ no conforme | |
| Congelar, reposicionar y repetición desde el puesto del instructor | ☐ conforme ☐ no conforme | |
| Aproximaciones RNAV marcadas como de entrenamiento, no publicadas | ☐ conforme ☐ no conforme | |

## 6. Firmas

| | Nombre | Firma | Fecha |
|---|---|---|---|
| Responsable del dispositivo | | | |
| Instructor de vuelo | | | |
| Inspector de la autoridad | | | |
