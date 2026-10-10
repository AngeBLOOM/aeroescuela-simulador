# Enlace AeroEscuela ↔ simulador de tránsito aéreo (protocolo 1)

AeroEscuela puede conectarse con un simulador de control de tránsito aéreo (consola de torre, radar, puesto
de un instructor de ATC…). Este documento es todo lo que necesita quien programe ese otro simulador.

- **Activar en AeroEscuela:** Ajustes → *ATC externo: Sí*. Allí se ve la dirección (`IP:8770`) y si hay
  alguien conectado. En vuelo, el panel de radio (T) muestra «ATC EXTERNO» cuando lo lleva el otro simulador.
- **Probar sin el otro simulador:** `Consola_ATC_Prueba.bat` (o `python tools/consola_atc.py`) es una consola de
  ejemplo que habla este protocolo: un radar, la radio y frases rápidas. Su código sirve de ejemplo.
- **Prueba automática:** `python tests/test_atc_externo.py`.

## Transporte

| | |
|---|---|
| Conexión | TCP, puerto **8770** (se puede cambiar con `atc_externo_puerto` en `datos/config.json`) |
| Formato | un objeto **JSON por línea**, UTF‑8, terminado en `\n` |
| Quién conecta | el simulador de ATC es el **cliente**; AeroEscuela es el servidor |
| Varios clientes | sí (p. ej. torre y radar a la vez); todos reciben lo mismo |
| Descubrimiento | cada 2 s AeroEscuela envía por **UDP difusión al puerto 8771**: `{"tipo":"anuncio","sim":"AeroEscuela","protocolo":1,"puerto":8770,"ip":"192.168.1.20","codigo":false,"indicativo":"EC-AES","aeropuerto":"MMMX"}` |
| Firewall | la primera vez Windows pregunta si permite a AeroEscuela usar la red: responder **Permitir** |

Unidades: altitudes en **pies**, velocidades en **nudos**, rumbos en **grados verdaderos** (0–360),
frecuencias en **MHz**, presión en **hPa**. Las posiciones van en **lat/lon WGS‑84** y además en metros
locales (`x` = norte, `y` = este desde el origen del escenario). El *escenario escuela* es ficticio: se publica
con un origen inventado (40° N, 4° O) y `"ficticio": true`.

## 1. Saludo

Lo primero que manda el ATC (si no, cualquier otro mensaje recibe un error):

```json
{"tipo":"hola","nombre":"Torre de prácticas","protocolo":1,"torre":"externa","trafico_ia":false}
```

`torre` y `trafico_ia` son opcionales (ver `control`). AeroEscuela contesta con `bienvenida` y `escenario`, y
desde ese momento envía `estado` 5 veces por segundo.

```json
{"tipo":"bienvenida","sim":"AeroEscuela","protocolo":1,"indicativo":"EC-AES","tipo_avion":"C172","aeropuerto":"MMMX"}
```

## 2. De AeroEscuela al ATC

### `escenario` (al conectar y cada vez que cambia el aeropuerto)
```json
{"tipo":"escenario","nombre":"Ciudad de México (MMMX)","ficticio":false,"origen":{"lat":19.436,"lon":-99.072},
 "aeropuerto":"MMMX","pista_en_servicio":"05R","frecuencias":{"TWR":118.1,"GND":121.85,"ATIS":127.65},
 "aeropuertos":[{"icao":"MMMX","nombre":"…","lat":19.436,"lon":-99.072,"elev_ft":7316,
   "pistas":[{"nombre":"05R/23L","rumbo":52.0,"largo_m":3952,"ancho_m":45,"lat1":…,"lon1":…,"lat2":…,"lon2":…,"elev_ft":7316}]}],
 "navaids":[{"id":"MEX","tipo":"VOR","frecuencia":114.1,"lat":…,"lon":…}]}
```
`lat1/lon1` es el umbral del primer número de la pista (`05R`) y `lat2/lon2` el del otro extremo.

### `estado` (5 Hz)
```json
{"tipo":"estado","t":312.4,"indicativo":"EC-AES","tipo_avion":"C172","lat":19.4402,"lon":-99.0651,"x":456.2,"y":731.0,
 "alt_ft":7850,"alt_ind_ft":7845,"agl_ft":534,"ias_kt":82.0,"gs_kt":79.5,"rumbo":52.3,"derrota":50.8,"vs_fpm":640,
 "alabeo":-2.1,"cabeceo":6.0,"en_tierra":false,"choque":false,
 "transpondedor":{"codigo":"1200","modo":"ALT"},"com1":118.1,"com1_reserva":121.85,"radio_ok":true,"qnh_hpa":1022.0,
 "motor":true,"rpm":2450,"flaps":10,"tren_abajo":true,"luces":{"nav":true,"landing":true,"strobe":false,"beacon":true,"taxi":false},
 "emergencia":false,"leccion":"Circuito de tráfico"}
```
`alt_ft` es la altitud real; `alt_ind_ft` la que marca el altímetro con el reglaje que puso el piloto
(útil para comprobar si puso bien el QNH). `modo` del transpondedor es `OFF` con la aviónica apagada.
`radio_ok` es `false` con la aviónica apagada o con la falla de radio programada por el instructor: en ese
caso el ATC no recibe sus transmisiones y el piloto no oye las del ATC (como en la realidad).

### `transmision` (cada vez que el piloto habla por radio)
```json
{"tipo":"transmision","de":"piloto","indicativo":"EC-AES","frecuencia":118.1,"estacion":"TWR",
 "texto":"México torre, EC-AES, en final, aterrizaje completo"}
```
El piloto transmite eligiendo una frase del menú de radio (ratón, teclas 1–9 o botón de la cabina) o diciéndola
por el micrófono (Ctrl derecho). Solo llega si su radio funciona.

### `ptt`
```json
{"tipo":"ptt","activo":true,"frecuencia":118.1}
```
El piloto pulsa / suelta el botón de hablar por micrófono. Sirve para mostrar «transmitiendo» o para abrir un canal
de voz real (ver *Voz real*).

### `evento`
```json
{"tipo":"evento","evento":"despegue","detalle":{"pista":"05R"}}
```
Eventos: `despegue`, `aterrizaje`, `accidente` (`motivo`), `emergencia` (transpondedor 7700),
`falla_de_radio` (7600), `interferencia_ilicita` (7500).

### Respuestas
`{"tipo":"ok","de":"control",…}`, `{"tipo":"recibido","oido":true,"texto":"…"}`, `{"tipo":"pong","t":…}`,
`{"tipo":"error","texto":"…"}`.

## 3. Del ATC a AeroEscuela

### `control` — quién lleva la torre
```json
{"tipo":"control","torre":"externa","trafico_ia":false}
```
- `torre: "externa"`: la torre automática de AeroEscuela se calla y el menú de radio del piloto pasa a frases
  estándar (solicitar rodaje, listo para salir, viento en cola, base, final, motor y al aire, MAYDAY, colacionar…).
  Todo lo que diga el piloto llega como `transmision`. Con `"interna"` vuelve la torre automática.
- `trafico_ia: false` quita los aviones automáticos de AeroEscuela para que solo haya el tráfico del ATC.
- Si todos los ATC se desconectan, AeroEscuela vuelve sola a la torre automática.

### `mensaje` — transmisión del ATC al piloto
```json
{"tipo":"mensaje","texto":"EC-AES, pista 05R, viento 060 grados 8 nudos, autorizado a aterrizar",
 "estacion":"TWR","frecuencia":118.1,"voz":"opcional: texto para la síntesis de voz","colacionar":true}
```
Se oye **con voz de radio** (con estática) y aparece en pantalla, **solo si el piloto está sintonizado** en
`frecuencia` y su radio funciona (sin `frecuencia` se oye siempre que la radio funcione). La respuesta
`recibido` dice si lo oyó. Con `colacionar: true` el menú del piloto ofrece «Colacionar: …» para repetirlo.
`estacion`: `TWR`, `GND`, `APP` o lo que corresponda (solo informativo).

### `opciones` — cambiar el menú de radio del piloto (opcional)
```json
{"tipo":"opciones","lista":["Solicito cruzar la pista 05R",
                             {"texto":"Solicito descenso","frase":"solicito descenso a 7500 pies","estacion":"APP"}]}
```
Hasta 9 frases. `"lista": null` vuelve a las frases estándar. Las frases se pueden decir por el micrófono.

### `trafico` — aviones del ATC (se ven en el paisaje, el TCAS/MFD y dan aviso de tráfico y colisión)
```json
{"tipo":"trafico","completa":true,"lista":[
  {"id":"T1","indicativo":"AMX123","tipo":"P28A","lat":19.46,"lon":-99.05,"alt_ft":8500,"rumbo":230,"gs_kt":110,
   "vs_fpm":-500,"en_tierra":false,"tramo":"final"}]}
```
Mandar cada 0,5–1 s. Entre mensajes AeroEscuela los mueve por estima; un avión sin noticias en 10 s desaparece.
Con `completa: true` (por defecto) desaparecen también los que no vengan en la lista. En vez de `lat/lon` se
pueden mandar `x/y` en metros locales. `tipo` OACI (C152, C172, P28A, P28R, SR20, DA40, DA42) elige el modelo 3D.

### `meteo`
```json
{"tipo":"meteo","viento_dir":270,"viento_kt":12,"rafagas_kt":6,"qnh_hpa":1018,"visibilidad_m":8000}
```
Todos los campos son opcionales.

### `frecuencias`
```json
{"tipo":"frecuencias","lista":{"TWR":118.1,"GND":121.85,"ATIS":127.65}}
```
Cambia las frecuencias del aeródromo (botones de sintonía rápida del panel de radio).

### Otros
`{"tipo":"ping","t":123}` → `pong`; `{"tipo":"pedir","que":"escenario"}` o `{"tipo":"pedir","que":"estado"}`.

## Voz real entre controlador y piloto

Este protocolo lleva el **texto** de la radio (AeroEscuela lo dice con voz sintética y el piloto puede hablar
por micrófono con reconocimiento de voz). Si en el otro puesto hay una **persona** controlando y se quiere voz
real, lo más sencillo es un intercomunicador de red (Mumble, TeamSpeak, Discord…) y usar el mensaje `ptt` para
mostrar quién transmite. Una versión futura del protocolo puede añadir audio.

## Seguridad

El enlace es para la **red local de la escuela**. Si hace falta, se puede exigir un código: poner
`"atc_externo_codigo": "1234"` en `datos/config.json` y mandar `"codigo":"1234"` en el saludo. No abrir el
puerto 8770 a Internet.
