# Registro de mantenimiento — AeroEscuela

El registro de un dispositivo de instrucción muestra que funciona como cuando se evaluó: chequeos periódicos, fallas
encontradas, reparaciones y cambios del programa o del equipo. La autoridad lo revisa en sus inspecciones.

## 1. Chequeos automáticos

```
python tools/chequeo.py "Nombre del responsable" "nota opcional"
```

Ejecuta todas las pruebas, incluida la validación del C172S contra su manual, y añade una línea a
`datos/mantenimiento.csv`:

| fecha | versión | responsable | pruebas | fallos | nota |
|---|---|---|---|---|---|
| 2026-10-11 08:05 | `a1b2c3d` | (nombre) | 20/20 | | chequeo diario |

Si alguna prueba falla, el programa avisa **NO USAR PARA INSTRUCCIÓN** y la deja anotada.

| Cuándo | Qué |
|---|---|
| Cada día de uso, antes del primer vuelo | `tools/chequeo.py` y el recorrido de los mandos de la consola |
| Tras actualizar el programa | `tools/chequeo.py` y `tools/guia_pruebas.py --pruebas` (guía nueva con la versión) |
| Tras cambiar un mando, monitor o la PC | `tools/chequeo.py`, calibrar los ejes y medir el retardo de nuevo |
| Cada 3 meses | Las pruebas con escenarios reales (sección 4 de la guía de pruebas) y repaso de esta hoja |

## 2. Recorrido diario de la consola

| Fecha | Volante (alabeo/cabeceo) | Pedales y frenos | Gases, mezcla, flaps, compensador | Interruptores y magnetos | Pantallas | Responsable |
|---|---|---|---|---|---|---|
| | ☐ | ☐ | ☐ | ☐ | ☐ | |
| | ☐ | ☐ | ☐ | ☐ | ☐ | |
| | ☐ | ☐ | ☐ | ☐ | ☐ | |
| | ☐ | ☐ | ☐ | ☐ | ☐ | |
| | ☐ | ☐ | ☐ | ☐ | ☐ | |

## 3. Fallas y reparaciones

Toda discrepancia que vea un instructor o un alumno, aunque sea pequeña, con lo que se hizo para corregirla.

| Fecha | Descrita por | Discrepancia | Acción tomada | Versión tras la reparación | Comprobado por | Fecha de cierre |
|---|---|---|---|---|---|---|
| | | | | | | |
| | | | | | | |
| | | | | | | |
| | | | | | | |

## 4. Cambios del programa y del equipo

| Fecha | Versión | Cambio | Afecta al modelo de vuelo | Guía de pruebas regenerada | Responsable |
|---|---|---|---|---|---|
| 2026-10-10 | | Validación del C172S contra el POH y ajuste del modelo (PR #16) | Sí | Sí | |
| | | | ☐ sí ☐ no | ☐ | |
| | | | ☐ sí ☐ no | ☐ | |

Un cambio que afecte al modelo de vuelo del C172S exige que `test_validacion` siga pasando y una guía de pruebas
nueva. Si la autoridad ya calificó el dispositivo, puede exigir avisarla antes.
