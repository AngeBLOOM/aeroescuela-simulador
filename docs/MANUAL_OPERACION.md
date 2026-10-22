# Manual de operación — AeroEscuela

Para el responsable del simulador y los instructores. La conexión de la consola paso a paso está en
`GUIA_CABINA_FISICA.md`; las pruebas del dispositivo, en `GUIA_PRUEBAS_C172S.md`; el mantenimiento, en
`REGISTRO_MANTENIMIENTO.md`.

## 1. Qué es y qué no es

- **Dispositivo de instrucción** con el **Cessna 172S** como avión de referencia: su modelo de vuelo está validado
  contra el manual (POH) y la consola física reproduce su cabina.
- Los otros seis aviones (C152, PA-28 Warrior, PA-28R Arrow, SR20, DA40, DA42) se vuelan **sin consola**: con teclado,
  ratón, el panel 2D o un joystick USB aparte.
- **No está certificado** mientras la autoridad no lo califique. Las horas en él cuentan según lo que la autoridad
  apruebe.
- Las **aproximaciones RNAV (GPS)** son **de entrenamiento, generadas y no publicadas**. Para un procedimiento real se
  usa su carta.
- Las cifras de peso, centrado y rendimiento son las típicas del manual de cada modelo, no las de un avión concreto.

## 2. Encendido y apagado

1. Encienda los monitores y la consola **antes** de abrir el programa (si se conecta después, el simulador la reconoce
   solo).
2. Abra **AeroEscuela** (acceso directo o `Iniciar_Simulador.bat`).
3. Antes del primer vuelo del día, haga el **chequeo** (sección 6).
4. Para apagar: **Esc → Menú principal → Salir**. Los ajustes, el progreso de los alumnos y la bitácora se guardan
   solos.

## 3. Pantallas y cabina

**Cabina automática** (por defecto, tecla **P** para cambiarla):

| Situación | Qué se ve |
|---|---|
| Consola del C172S conectada, instrumentos en su propia pantalla (F2) | Solo el paisaje |
| Consola conectada, sin pantalla de instrumentos | Paisaje con la franja de instrumentos debajo |
| Sin consola, o con un avión que no es el C172S | Panel 2D: interruptores, palancas, radios y G1000 con el ratón |

- **F2**: pantalla de instrumentos: normal · paisaje + franja · solo instrumentos · segunda ventana.
- **Tab**: instrumentos clásicos o G1000.
- **F9**: imágenes por segundo y retardo.
- Los mandos dibujados no se muestran nunca con la consola: la cabina fotográfica se retiró, y los volantes de la cabina
  3D están ocultos (tecla Y).

## 4. Antes de cada sesión

1. Elija el **alumno** (Progreso y bitácora → Cambiar alumno).
2. Con la consola: compruebe en **Cabina física → Diagnóstico y prueba** que cada mando responde.
3. Interruptores de la consola en la posición de la lista de la lección. Al empezar, el simulador copia los
   interruptores reales con el avión frío, o avisa de los que no coinciden con un avión ya preparado.
4. Elija la **lección** (Programa de lecciones) o un **vuelo libre** (avión, lugar, meteorología y hora).

## 5. Puesto del instructor

- **En el simulador:** tecla **I** (el vuelo se pausa mientras se configura).
- **Por la red:** Ajustes → Instructor en red; desde una tableta o PC de la misma red, con la dirección y el código de 4
  cifras que muestra el simulador.

| Función | Para qué |
|---|---|
| Meteorología | Viento, ráfagas, turbulencia, visibilidad, nubes, QNH, humedad, hora; METAR real |
| Fallas | 17 fallas, ahora o programadas (tras el despegue, en crucero, en la final, al azar) |
| Congelar y mover | Congelar altitud, posición o combustible; tiempo ×2/×4; mover el avión |
| Reposicionar | Pista, final, crucero, aeródromo cercano… |
| Avión | Cambiar de avión y de combustible |

Al terminar, **Esc → Terminar y evaluar** abre el análisis con la nota, las gráficas, la repetición y el informe PDF.

## 6. Chequeo antes de usar

Diario, y después de cualquier cambio del programa o del equipo:

```
python tools/chequeo.py "Nombre del responsable"
```

Ejecuta todas las pruebas automáticas, incluida la validación del C172S contra el manual (unos 6 minutos), y lo anota
en el registro de mantenimiento. **Si alguna falla, el simulador no se usa para instrucción** hasta corregirlo.
Además, con la consola: recorrido de cada mando en Diagnóstico y prueba.

## 7. Si algo falla en vuelo

| Problema | Qué hacer |
|---|---|
| Un mando de la consola no responde | Cabina física → Buscar; si sigue, desenchufar y enchufar (conexión en caliente) |
| El avión no responde a la consola | Compruebe que el avión elegido es el **C172S**: la consola solo es suya |
| Va lento (F9: menos de 25 FPS) | Ajustes → Calidad más baja, o menos monitores de paisaje |
| La imagen se congela | Esc; si no responde, cierre el programa y vuelva a abrirlo (el progreso ya guardado se conserva) |
| Un resultado parece incorrecto | Anótelo en el registro de mantenimiento (sección «Fallas y reparaciones») |

## 8. Archivos

| Archivo | Contenido |
|---|---|
| `datos/config.json` | Ajustes del equipo, asignaciones de la consola |
| `datos/alumnos/` | Progreso y bitácora de cada alumno |
| `datos/informes/` | Informes PDF de los vuelos y fichas de alumnos |
| `datos/retardo.json` | Retardo medido en el último vuelo |
| `datos/mantenimiento.csv` | Registro de los chequeos |
| `docs/GUIA_PRUEBAS_C172S.md` | Guía de pruebas (`python tools/guia_pruebas.py --pruebas`) |
