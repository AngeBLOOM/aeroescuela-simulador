# Salida de datos de vuelo por UDP (protocolo 1)

AeroEscuela puede enviar el estado del avión varias veces por segundo a otro programa: instrumentos en otra
pantalla o tableta, un programa puente para paneles con LEDs y avisos (Arduino), una plataforma de movimiento
o un registro de vuelo. Solo **envía**: no recibe órdenes (para eso están el puesto web del instructor y el
enlace ATC, `docs/PROTOCOLO_ATC.md`).

- **Activar:** Ajustes → *Salida UDP: Sí*. Al lado se ve el destino y cuántos datagramas lleva enviados.
- **Ver lo que llega:** `python tools/udp_escucha.py` (en la misma computadora o en la de destino).
- **Prueba automática:** `python tests/test_udp.py`.

## Transporte

| | |
|---|---|
| Protocolo | UDP, un **objeto JSON por datagrama**, UTF‑8, sin separadores |
| Destino | `udp_destino` en `datos/config.json` (por defecto `127.0.0.1`). Otra computadora: su IP. Toda la red local: una dirección que termine en `.255` (difusión) |
| Puerto | `udp_puerto` (por defecto **49020**) |
| Frecuencia | `udp_hz` (por defecto **30** por segundo, de 1 a 60) |
| Firewall | la primera vez Windows puede preguntar si permite a AeroEscuela usar la red: responder **Permitir** |

Unidades: altitudes en **pies**, velocidades en **nudos**, ángulos en **grados**, velocidades de giro en
**grados por segundo**, aceleraciones en **g**, frecuencias en **MHz** (el ADF en kHz). `rumbo` y `derrota` son
**verdaderos**; `rumbo_mag` es el magnético (el que marcan la brújula y el direccional) y `declinacion` la del lugar
(+ = este; en Venezuela unos −13, es decir 13° oeste). El OBS (`nav1_obs`) es magnético.

## Campos

```json
{"v":1, "t":123.456, "estado":"flight", "ficticio":false,
 "lat":10.2500123, "lon":-67.6494567, "alt_ft":3000.0, "alt_ind_ft":2998.5, "agl_ft":1580.2,
 "ias_kt":100.2, "tas_kt":104.1, "gs_kt":98.7, "vs_fpm":0,
 "rumbo":359.8, "derrota":358.9, "cabeceo":2.1, "alabeo":-0.4, "aoa":3.9, "derrape":0.1,
 "p":0.0, "q":0.1, "r":0.0, "nx":0.012, "ny":0.0, "nz":1.001,
 "motores":[{"rpm":2400, "map_inhg":22.5, "aceite_psi":60.2, "aceite_c":180.5, "egt_f":1350, "cht_f":330,
             "flujo_lh":32.1, "gases":0.62, "mezcla":1.0, "magnetos":3, "en_marcha":true}],
 "flaps":0.0, "tren":1.0, "freno_estac":false, "frenos":[0.0, 0.0], "compensador":0.21,
 "en_tierra":false, "choque":false, "bus_v":28.1, "comb_l":140.0,
 "luces":{"nav":true, "beacon":true, "strobe":true, "landing":false, "taxi":false},
 "interruptores":{"bateria":true, "alternador":true, "avionica":true, "bomba":false, "pitot":false},
 "avisos":{"perdida":false, "volt_bajo":false, "aceite_bajo":false, "comb_bajo":false,
           "tren_inseguro":false, "pa_desconectado":false, "puerta":false},
 "radio":{"com":118.05, "com_reserva":121.7, "nav1":108.9, "nav1_obs":285, "nav1_cdi":-0.12, "nav1_gs":0.05,
          "nav1_valida":true, "nav1_hacia":"TO", "xpdr":1200, "adf_khz":350.0, "adf_valida":true, "adf_relativa":12.5},
 "pa":{"conectado":false, "lateral":"ROL", "vertical":"PIT"},
 "congelado":[], "ritmo":1}
```

| Campo | Significado |
|---|---|
| `v` | versión del protocolo (1). Un campo nuevo no cambia la versión; quitar o cambiar uno, sí |
| `t` | tiempo simulado del vuelo, en segundos |
| `estado` | `flight` (en vuelo), `pause`, `instructor` (estación del instructor abierta), `menu`, `debrief`, `replay` |
| `ficticio` | `true` en el escenario escuela, que no existe: su `lat`/`lon` es un origen convenido |
| `alt_ft` / `alt_ind_ft` | altitud real y la del altímetro (con su QNH y sus errores) |
| `nx` `ny` `nz` | aceleración específica en ejes del avión (adelante, derecha, abajo; `nz` = 1 en vuelo recto): para plataformas de movimiento |
| `p` `q` `r` | velocidad de alabeo, cabeceo y guiñada |
| `motores` | uno por motor (dos en el DA42); `magnetos`: 0 OFF, 1 derecho, 2 izquierdo, 3 ambos |
| `flaps` | grados de flap; `tren`: 0 arriba, 1 abajo y blocado |
| `frenos` | izquierdo y derecho, 0 a 1 |
| `barrena` | intensidad de la barrena, −1 (a la izquierda) a 1 (a la derecha); 0 sin barrena |
| `avisos` | luces de aviso del tablero: encender un LED por cada `true` |
| `nav1_cdi` / `nav1_gs` | desvío del localizador/VOR y de la senda, −1 a 1 (a fondo de escala) |
| `adf_relativa` | marcación relativa del NDB sintonizado (0 = delante, en el sentido de las agujas); 90 sin señal |
| `gps` | selector CDI (`GPS`/`VLOC`), punto activo, distancia, curso deseado (magnético) y desvío lateral (NM, + = a la derecha) |
| `congelado` / `ritmo` | lo que el instructor tiene congelado y el ritmo del tiempo (1, 2 o 4) |

## Ejemplo de receptor (Python)

```python
import json, socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(("0.0.0.0", 49020))
while True:
    d = json.loads(s.recv(65535))
    print(d["ias_kt"], d["alt_ind_ft"], d["avisos"]["perdida"])
```
