# AeroEscuela — Simulador de entrenamiento de vuelo (Python, PC)

Simulador de entrenamiento para pilotos con física de 6 grados de libertad, cabina clásica y de
cristal (G1000), instructor virtual con voz, evaluación según los estándares oficiales de examen y
escenarios reales de cualquier aeropuerto del mundo (relieve real + fotografía satelital).

## Cómo iniciarlo

**Instalado (recomendado para la escuela):** ejecute `dist/AeroEscuela_Instalador.exe` en cada computadora.
Crea el acceso directo y el desinstalador y no necesita Python. Los datos de cada equipo (alumnos, ajustes,
escenarios descargados) se guardan en `%LOCALAPPDATA%\AeroEscuela\datos`. Para volver a generar el
instalador tras un cambio: `python tools/construir.py` (usa PyInstaller e Inno Setup 6).

**Desde el código:** doble clic en **`Iniciar_Simulador.bat`** (instala lo necesario la primera vez), o bien:

```bash
python main.py
```

Requisitos: Windows 10/11, Python 3.10+ y una GPU con OpenGL 3.3 (sirve la gráfica integrada).
Dependencias: `pygame-ce`, `moderngl`, `numpy`, `comtypes` (voz). Ver `requirements.txt`.

## Novedades (octubre de 2026)

- **Cabina física:**
  - calibración de ejes y sensibilidad por eje (zona muerta y curva, con la curva dibujada);
  - setas asignables y frenos de pie diferenciales;
  - interruptores sincronizados al empezar el vuelo;
  - mandos conectados en caliente y mandos iguales distinguidos por número de serie o puerto;
  - el joystick genérico ya no pisa a los mandos asignados;
  - **teclas y perillas del G1000** del C172S: piloto automático, HDG / CRS / BARO, radios (una perilla por radio o
    una compartida con selector), transpondedor y GPS (D→, FPL, PROC, FMS, ENT, CLR, RANGE); las perillas giratorias
    se leen clic a clic aunque se giren rápido. La barra superior del PFD muestra activa y reserva de cada radio y
    el transpondedor.
  Ver `docs/GUIA_CABINA_FISICA.md`.
- **Física:**
  - el centro de gravedad de la hoja de peso y balance cambia la estabilidad y la fuerza de profundidad;
  - amortiguación `Cmadot`;
  - turbulencia que hace girar el avión (Dryden);
  - barrena con recuperación PARE;
  - hielo en el carburador (C152 y PA-28 Warrior; **F6** = calefacción).
- **Navegación:**
  - radiofaros NDB y ADF (clic derecho en el NAV 2);
  - declinación magnética real: la brújula, el direccional, el HSI, el VOR, el viento de la torre y los rumbos dictados son magnéticos;
  - **GPS** con plan de vuelo, D→ y OBS en el mapa del G1000 (**F7** = CDI GPS/VLOC);
  - en D→ y «+ Añadir» se **teclea cualquier identificador** (o parte del nombre): Enter elige, Esc cierra;
  - **aproximaciones RNAV (GPS) de entrenamiento** para cada pista (FPL → RNAV), en «T» con IAF, IF, FAF a 5 NM y
    senda de 3°: escala de 0,3 NM en el final, rombo de senda en el PFD y piloto automático en APR. Son generadas,
    **no publicadas**: para volar un procedimiento real use su carta.
- **Instructor:**
  - congelar altitud, posición o combustible;
  - tiempo ×2/×4;
  - mover el avión;
  - humedad;
  - fallas nuevas.
- **Lecciones nuevas:** hielo en el carburador y barrena.
- **Gráficos:**
  - **sombra real del avión** con la silueta del modelo 3D, según la hora del Sol, sobre el terreno, la pista y los
    hangares (ayuda a juzgar la altura en el aterrizaje; se desvanece con la altura, de noche y con cielo cubierto);
  - penumbra horneada en los modelos 3D (uniones, ruedas, interior) sin costo en vuelo;
  - resplandor de las luces de pista, estroboscópicos y ciudades de noche;
  - destello del Sol solo cuando el disco se ve (no lo tapan el terreno, el tablero ni las nubes);
  - color según la hora (dorado al amanecer y al atardecer, azulado de noche) y borde plateado de las nubes a
    contraluz.
  - **sombras de hangares, edificios y árboles** alrededor de la cámara, también sobre el avión cuando rueda por
    la sombra de un hangar;
  - **relieve fino alrededor del avión**: malla de 12,5 m (en vez de 100 m) con superficie suave y ondulaciones del
    suelo; la física usa la misma superficie (las ruedas no flotan ni se hunden) y los aeródromos quedan planos;
  - **Foto pro** (Mayús+F12): la escena limpia, sin tablero ni textos, al doble de la resolución de la pantalla;
  - **hangares con detalle**: chapa ondulada, portones corredizos con ventanas, techo a dos aguas con alero y
    canaleta, losa de concreto y letrero; **torre de control** con cabina de vidrio y balcón (texturas generadas
    por el programa, `render/buildings.py`);
  - **árboles con dos niveles de detalle**: de cerca, pinos de varios pisos y frondosos de copa redonda que se mecen
    con el viento; de lejos, los simples; más allá de 6,5 km no se dibujan (la bruma los tapa). Bosques tres veces
    más tupidos y aun así más livianos que antes;
  - **fachadas con ventanas** en los edificios reales (OpenStreetMap; encendidos por defecto, Ajustes → *Paisaje*)
    y en las casas y edificios de los pueblos: pisos, ventanas que reflejan el cielo y el Sol, vidrieras en la
    planta baja, torres de vidrio, casas con techo de tejas a dos aguas y, **de noche, ventanas encendidas al
    azar**. Las dibuja el shader (sin texturas); de lejos se simplifican y no cuestan más que las paredes lisas.
- **Señalización del aeródromo (OACI / FAA)**, pensada para practicar el rodaje y evitar incursiones en pista:
  - líneas de espera antes de cada pista (dos continuas del lado de la calle, dos discontinuas del lado de la
    pista) a 60 m del eje si la pista tiene ILS y a 30 m si es visual;
  - cartel rojo de posición de espera con los números de pista ordenados como los ve el piloto (el de la
    izquierda corresponde al extremo de la izquierda) y cartel negro con el nombre de la calle; iluminados de noche;
  - calles de rodaje y plataforma con asfalto real; luces azules de borde;
  - **faro giratorio** blanco y verde (12 vueltas por minuto) de noche o con cielo cubierto.
  - **REIL** (dos destellos blancos sincronizados a los lados del umbral) en los extremos sin luces de aproximación;
  - **faro de rodaje del avión** separado del de aterrizaje: haz ancho y corto que alumbra la calle y los bordes.
  - **círculo segmentado** alrededor de la manga en Valle Norte (aeródromo no controlado), con las «L» que indican
    hacia qué lado es el circuito de cada pista (por el sur: izquierda para la 27, derecha para la 09).
  En los aeropuertos reales solo se agrega el faro (las calles de rodaje se ven en la foto satelital).
- **Tráfico visible a distancias reales («ver y evitar»)**: un avión ligero a 4 km mide menos de un píxel y la
  imagen lo perdería; se dibuja como el puntito oscuro que ve el ojo (1,5 a 3 px), más tenue con la distancia y la
  bruma, hasta unos 10 km. De noche se ven sus luces.
- **Nubes y bruma para practicar los mínimos VFR**: las nubes tienen la base plana y gris a la altura informada
  (antes asomaban hasta 500 m por debajo del techo del METAR) y la bruma se concentra cerca del suelo: abajo la
  visibilidad es la del METAR, al subir mejora y desde arriba se ve la capa de bruma en el horizonte. Dentro de una
  capa de nubes la visibilidad es pareja. Los cúmulos, vistos desde arriba, cubren más o menos la fracción del
  METAR (FEW, SCT, BKN) y con sol **proyectan su sombra sobre el suelo**, los edificios, los árboles y el avión.
- **Pista mojada**: con lluvia el pavimento se oscurece, se espeja (refleja el cielo cuanto más rasante se mira y el
  brillo del Sol) y aparecen charcos; la pintura sigue viéndose. Es la misma humedad que informa el ATIS y que usa
  el frenado. De noche, las luces de pista se reflejan en el pavimento como estelas hacia el piloto.
- **Pistas reales con sus datos**: las que no tienen luces (dato de OurAirports) quedan a oscuras de noche; las de
  pasto, tierra o grava no se dibujan con asfalto ni pintura (se ve la pista de la foto con balizas blancas de borde)
  y se rueda en ellas como en césped. El ILS de entrenamiento se genera solo en pistas pavimentadas, con luces y de
  1500 m o más (antes, en cualquiera de más de 700 m).
- **Visión 1:1 en la cabina física** (Ajustes → *Visión 1:1*): con el ancho visible del paisaje, la distancia del
  ojo y su altura sobre el centro, el campo de visión es el real y el horizonte queda a la altura del ojo (corrimiento
  óptico de la imagen, sin inclinar la cámara): la pista y las distancias se ven del tamaño que tienen desde el avión.
- **Niebla de valle (radiación)**: con aire casi saturado (temperatura − rocío ≤ 2 °C, se ajusta con la humedad
  del instructor), viento flojo y entre la madrugada y unas horas después del amanecer, los valles se llenan de
  niebla en parches y los cerros quedan despejados. El METAR y el ATIS la informan (FG con menos de 1000 m, BR
  mientras se disipa).
- **Atravesar un cúmulo**: al entrar en una nube suelta la vista queda en blanco (sin horizonte, como en IMC real) y al salir se ve la pared de la nube; dentro de la nube la luz sigue la hora (gris cálido y oscuro al amanecer y al atardecer).
- **Suelo con texturas fotográficas**: la pista y las calles de rodaje usan un escaneo real de asfalto, la plataforma
  losas de concreto de 5 m con juntas y el pasto un escaneo real de césped, cada uno con su **relieve** (mapa de
  normales) que responde al Sol: de cerca, al rodar o en la corta final, se ve el grano del asfalto, las juntas y
  las matas de pasto con su sombra. A media distancia el pasto tiene matas y manchas secas para que no se vea liso.
  Las texturas se preparan con `tools/texturas_suelo.py` (créditos en `assets/CREDITOS_TEXTURAS.md`).
- **Carteles de distancia restante y luces de borde según la pista**: en pistas pavimentadas, iluminadas y de 1500 m
  o más hay carteles negros con el número blanco cada 1000 ft (miles de pies que quedan; el dorso muestra los del
  sentido contrario), con luz propia de noche: sirven para decidir a tiempo un despegue abortado. Las pistas con ILS
  tienen luces de borde de alta intensidad (HIRL), con la zona de precaución amarilla en los últimos 600 m; las
  demás, de intensidad media (MIRL) y todas blancas. Las luces más intensas se ven desde más lejos con bruma.
- **Bruma iluminada por el Sol**: mirando hacia el Sol la bruma del horizonte brilla como el cielo (luz dispersada
  hacia adelante) y el terreno lejano empalma con el cielo sin corte. **Manga de viento iluminada** de noche.
  En calidad «rendimiento» se apagan los efectos de imagen y quedan las sombras.
- **Salida de datos por UDP** para instrumentos, paneles y movimiento: `docs/PROTOCOLO_UDP.md`.
- **Pruebas:** `python tools/pruebas.py` ejecuta 21 pruebas sin ventana; GitHub las ejecuta en cada pull request.
- **Validación y documentación para la autoridad:**
  - el C172S de referencia está validado contra su manual (pérdida, ascenso, crucero, consumo, planeo, despegue y
    aterrizaje dentro de tolerancia: `tools/validacion.py`);
  - `docs/GUIA_PRUEBAS_C172S.md` se genera con `python tools/guia_pruebas.py --pruebas`;
  - `docs/MANUAL_OPERACION.md` y `docs/REGISTRO_MANTENIMIENTO.md`;
  - `python tools/chequeo.py "responsable"` es el chequeo antes de usar, anotado en el registro.

## Qué incluye

**Modelo de vuelo**
- Cuerpo rígido 6DOF a 240 Hz con aerodinámica no lineal: curva de sustentación con pérdida,
  caída de ala y autorrotación, efecto suelo, flaps, derrape, amortiguamientos.
- Hélice con torque, factor P y estela sobre timón y profundidad (el avión "tira" a la izquierda al despegar).
- Motor de pistón: mezcla y altitud, magnetos, arranque, temperaturas, consumo, rearranque en vuelo.
- Tren con amortiguadores y fricción (asfalto/césped/agua), frenos, rueda de morro direccional.
- Detección de aterrizajes duros, toque de cola, golpe de hélice, sobrecarga G y exceso de VNE.
- Siete aviones:
  - **Cessna 152**: biplaza de ala alta, 110 hp (primer entrenador).
  - **Cessna 172S**: ala alta, paso fijo (entrenamiento básico).
  - **Piper PA‑28‑161 Warrior III**: ala baja, tren fijo y paso fijo.
  - **Cirrus SR20**: compuesto, hélice de velocidad constante, Perspective/G1000 y **paracaídas CAPS**.
  - **Piper PA‑28R Arrow**: tren retráctil y hélice de paso variable.
  - **Diamond DA40 NG**: diésel con FADEC (una sola palanca), cola en T, cúpula de burbuja, G1000.
  - **Diamond DA42 NG Twin Star**: bimotor, tren retráctil, embanderado de hélices; empuje asimétrico real,
    Vmc ≈ 68 kt y ascenso con un motor ≈ 140‑300 ft/min según embanderado.

**Cabina**
- **Cabina automática** (por defecto): con la consola física conectada no se dibuja ningún mando (solo el paisaje,
  con la franja de instrumentos debajo si no van en su propia pantalla); sin consola, el panel 2D, que se maneja
  con el ratón y con el teclado o un joystick USB. Cambia sola al enchufar o quitar la consola.
- **Cabina 3D por dentro**: tablero con los instrumentos reales montado en 3D y pulsable con el ratón,
  visera, brújula, montantes, techo, puertas, asientos, capó del motor a la vista, disco de la hélice y reflejos
  del sol en el parabrisas; volantes ocultos (tecla **Y**). Tecla **P**: automática · panel 2D · cabina 3D · sin panel.
- Aspecto fotográfico: marcos metálicos con tornillos, esferas, reflejo del cristal, tablero texturizado y marcos
  físicos de las pantallas G1000. Las texturas se generan por código con `python tools/make_assets.py`
  (carpeta `assets/`); si se sustituyen por fotos o imágenes de IA con el mismo nombre, el simulador las usa.
- Clásica: seis instrumentos básicos, tacómetro, motor, brújula magnética, dos CDI/ILS, radios,
  transpondedor, piloto automático, anunciadores, radiobalizas, cronómetro, palancas e interruptores clicables.
- Cristal G1000: PFD (cintas de velocidad/altitud, HSI, director de vuelo, radioaltímetro,
  tendencia de velocidad) y MFD con mapa móvil, alerta de terreno TAWS y página de motor.
- Instrumentos con errores reales: retardo del variómetro, deriva del direccional, vuelco del
  horizonte por falla de vacío, pitot/estática obstruidos, falla eléctrica.

**Piloto automático** (estilo GFC 700): ROL, HDG, NAV (VOR/LOC), APR (ILS acoplado), PIT, ALT, VS
con captura de altitud, compensación automática y protección de velocidad mínima (MINSPD).

**Meteorología**: atmósfera ISA, QNH, viento con perfil vertical, ráfagas, turbulencia tipo Dryden,
cizalladura, nubes (dispersas y capa cubierta con vuelo dentro de nube), niebla, ciclo día/noche con estrellas.

**Radioayudas**: VOR, ILS (localizador + senda), DME, radiobalizas O/M/I con sonido, PAPI,
luces de borde, umbral bicolor y aproximación con destellos secuenciales.

## Programa de entrenamiento (estándar FAA ACS · equivalente EASA)

Las lecciones siguen las áreas de operación y tolerancias del examen práctico oficial:
**FAA‑S‑ACS‑6C Piloto Privado**, **FAA‑S‑ACS‑8C Habilitación Instrumental** y
**FAA‑S‑ACS‑7B Piloto Comercial (clase multimotor)**. Se aprueba con 70/100.

| Fase | Lección | Tarea ACS | Tolerancias evaluadas |
|---|---|---|---|
| 1 Tierra | Arranque del motor y rodaje | PA.II.C / II.D | lista en orden, rodaje < 15 kt, sobre asfalto |
| 2 Despegue y aterrizaje | Despegue normal y ascenso | PA.IV.A | Vy +10/−5 kt, rumbo ±10°, eje de pista |
| | Aproximación y aterrizaje normal | PA.IV.B | Vapp +10/−5 kt, estabilizada a 500 ft, toma ≤ 400 ft del punto, sin deriva |
| | Circuito de tránsito completo | PA.III.B | altitud ±100 ft, velocidad ±10 kt |
| | Aterrizaje con viento cruzado | PA.IV.B | sin deriva lateral y alineado en la toma |
| 3 Maniobras | Vuelo recto, ascensos, descensos y virajes | PA.VIII | altitud ±100 ft, rumbo ±10°, velocidad ±10 kt |
| | Virajes escarpados 45° | PA.V.A | alabeo 45±5°, altitud ±100 ft, salida ±10° |
| | Pérdida sin motor y recuperación | PA.VII.B | rumbo ±10°, recuperación coordinada, sin pérdida secundaria |
| | Despegue y aterrizaje en pista corta | PA.IV.E/F | Vx hasta franquear 50 ft, toma 0–200 ft del punto, frenado |
| | Despegue y aterrizaje en pista blanda | PA.IV.C/D | volante atrás, despegue en efecto suelo, toma lenta |
| | Motor y al aire | PA.IV.N | potencia máxima inmediata, flaps por etapas, Vy, rumbo ±10° |
| 3 Maniobras (cont.) | Vuelo lento | PA.VII.A | altitud ±100 ft, velocidad +10/−0, sin aviso de pérdida |
| | Pérdida con motor | PA.VII.C | nariz abajo primero, alabeo ≤ 20°, altura perdida |
| | Virajes alrededor de un punto | PA.V.B | radio constante con viento, 800 ft AGL ±100 |
| 4 Emergencias | Falla de motor y aterrizaje de emergencia | PA.IX.B | mejor planeo 68 ±10 kt |
| | Fuego de motor en vuelo | PA.IX.C | mezcla/MOTOR a corte y combustible cerrado en segundos |
| | Humo en cabina (fuego eléctrico) | PA.IX.C | maestro OFF, extintor, aterrizar sin flaps eléctricos |
| | Falla del alternador | PA.IX.C | reconocerla y reducir la carga eléctrica |
| | Falla de radio: señales luminosas | PA.IX | transpondedor 7600, aterrizar solo con luz verde |
| | El tren no baja (Arrow) | PA.IX.C | extensión de emergencia por debajo de 100 kt |
| | Compensador desbocado | PA.IX.C | control y desconexión en menos de 5 s |
| | Entrada inadvertida en nubes | PA.VIII | viraje de 180° con alabeo ≤ 30°, altitud ±200 ft |
| | Actitudes anormales | PA.VIII.E | secuencia correcta (potencia primero), tiempo de recuperación |
| | Aterrizaje forzoso fuera de campo | PA.IX.B | campo elegido, viento de cara, toma lenta; amerizaje controlado |
| 5 Noche / panel parcial | Circuito nocturno | PA.X.A | como el circuito, de noche |
| | Falla de vacío: panel parcial | IR.VII.C | altitud ±100 ft, rumbo ±10° |
| 6 IFR | Aproximación ILS de precisión | IR.VI.B | ≤ 3/4 de escala en LOC y senda, velocidad ±10 kt, DA |
| | Espera (holding) sobre un VOR | IR.IV.A | entrada directa/gota/paralela, tramos de 1 min, altitud ±100 ft |
| | Aproximación de no precisión (LOC) | IR.VI.A | no bajar de la MDA (+100/−0), decisión en el MAP |
| | Aproximación frustrada | IR.VI.C | frustrada inmediata, rumbo ±10°, ascenso publicado |
| | Aproximación RNAV (GPS) de entrenamiento | IR.VI.B | ruta IAF → IF → FAF, ≤ 3/4 de escala lateral y vertical, velocidad ±10 kt, DA 250 ft |
| | Navegación VOR a otro aeródromo | PA.VI.B / IR.V.A | altitud ±100 ft, ≤ 3/4 de escala |
| 7 Multimotor (DA42) | Falla de motor: identificar, verificar, embanderar | CA.X.A | rumbo ±10°, Vyse +10/−5 kt, alabeo 2‑5° al motor bueno |
| | Demostración de Vmc | CA.X.B | rumbo ±10° con pedal, recuperación a la primera señal |
| 8 Travesías | Travesía con plan de vuelo | PA.VI.A | rumbo corregido ±15°, altitud ±200 ft, hora en el punto de control ±2 min |
| | Desvío a un alternativo | PA.VI.D | decisión en < 30 s, rumbo y tiempo al alternativo |
| 9 Examen | **Examen práctico de Piloto Privado** | ACS‑6C | encadena 8 tareas; APTO solo si se superan todas |
| | **Examen práctico de Vuelo Instrumental** | ACS‑8C | espera, panel parcial, actitudes, ILS, LOC y frustrada |
| 10 Misiones Base Sucre | **Traslado La Carlota (Caracas) → Base Sucre (Maracay)** | PA.VI.A / PA.IV.B | salida del valle de Caracas rumbo 280 a 4500 ft; el escenario cambia en vuelo (crucero acelerado) a Maracay; aproximación directa y aterrizaje en la 29 |
| | **Travesía completa La Carlota → Base Sucre (sin cortes)** | PA.VI.A/B | ruta real Caracas–Los Teques–La Victoria–Maracay a 7500 ft con el paisaje cargándose en vuelo; aterrizaje en la 29 |
| | Reconocimiento del Lago de Valencia e Isla del Burro | PA.VI.A | navegación visual, 3000 ft ±200, regreso y aterrizaje |
| | Travesía a la Base Aérea El Libertador (SVBL) | PA.VI.A | por el centro de Maracay, 3500 ft ±200, rumbo ±20°, aterrizaje en SVBL |
| | Motor parado al despegar: amerizaje en el lago | PA.IX.B | nariz abajo, sin «viraje imposible» (≤ 30°), amerizaje controlado |
| | Fuego de motor sobre Maracay: aterrizaje en una base | PA.IX.C | corte de combustible < 10 s, planeo y aterrizaje en SVBS o SVBL |
| | Nubes contra la Cordillera de la Costa (Henri Pittier) | PA.VIII | viraje de 180° hacia el valle, alabeo ≤ 30°, margen con el terreno |

| 11 Misiones en Venezuela | Maiquetía: aproximación ILS entre el mar y El Ávila | IR.VI.B | localizador y senda hasta la altura de decisión |
| | Valencia: aterrizaje con viento cruzado y racheado | PA.IV.B | sin deriva lateral en la toma |
| | Barquisimeto: despegue con calor (altitud de densidad) | PA.IV.A | 35 °C, carrera más larga y ascenso más lento |
| | Mérida: aproximación en el valle de los Andes | PA.IV.B | 5007 ft, aire poco denso, pista corta entre montañas |
| | Margarita: motor parado sobre el Caribe | PA.IX.B | planeo a la costa o amerizaje controlado |

| 12 Noche y meteorología | Noche en Base Sucre: circuito con las luces de Maracay | PA.X.A | luces exteriores, circuito ±100 ft, PAPI, aterrizaje nocturno |
| | Noche sobre el Lago de Valencia: aproximación de agujero negro | PA.X.A | final de 6 NM a la 11 sobre el lago oscuro, nunca por debajo de la senda |
| | Caracas de noche: aterrizaje en La Carlota | PA.X.A | pista entre las luces de la ciudad, senda 3° |
| | Falla del alternador de noche sobre Maracay | PA.IX.C | reducir cargas sin apagar las luces de navegación; luz de aterrizaje solo en final corta |
| | Aguacero tropical: aterrizaje con lluvia fuerte y pista mojada | PA.IV.B | 70 kt, toma firme, frenada progresiva, detenerse en la pista |
| | Tormenta sobre el lago: aterrice antes de que llegue | PA.I.C | frente de ráfagas, motor y al aire si no está estabilizado, no entrar en la tormenta |
| | Desvío por tormenta: de Base Sucre a El Libertador | PA.VI.D | rodear la tormenta a más de 5 km por el sur |
| | Niebla al amanecer: ILS a la pista 29 de Base Sucre | IR.VI.B | techo 250 ft, visibilidad 1200 m, decisión a 200 ft |
| | Travesía nocturna Caracas → Maracay (sin cortes) | PA.X.A + PA.VI.A | de noche por Los Teques y La Victoria, 7500 ft, aterrizaje en Base Sucre |

**Sol y Luna reales:** la salida y la puesta del sol y la Luna (con su fase) se calculan para la fecha de hoy, la hora
local y el lugar del escenario: en Maracay en octubre amanece hacia las 6:19 y anochece hacia las 18:17. Con luna llena
se distingue el paisaje de noche; con luna nueva la noche es mucho más oscura.

**Aviones de línea:** en los aeropuertos comerciales de Venezuela (Maiquetía, Valencia, Barquisimeto, Margarita,
Maracaibo…) aparecen reactores con los colores de Conviasa, Avior, Laser, Estelar y Turpial (y en Maiquetía y Valencia
también Copa, Avianca y Wingo): llegan por la final larga, aterrizan y despegan con su propio ritmo, y hablan con la
torre por la radio («Conviasa tres cero uno, final pista 10»).

**Retardo (F9):** junto a las imágenes por segundo, el simulador muestra su **retardo interno** (desde que lee los mandos
hasta que entrega la imagen) y el peor caso, que suma un cuadro de espera. Al terminar cada vuelo lo guarda en
`datos/retardo.json` para la guía de pruebas. En una PC de 30 FPS con el G1000: 10 ms de media y 50 ms de peor caso. El
USB y el monitor añaden lo suyo, que se mide de punta a punta con la consola montada.

**Fluidez:** si el equipo no llega a 60 imágenes por segundo, el simulador baja un poco la resolución del paisaje 3D
(hasta el 65 %) antes de pasar a 30; el paisaje se dibuja solo en la parte de la pantalla donde se ve.

**Noche y mal tiempo:** de noche se encienden las luces reales de la ciudad (de los edificios de OpenStreetMap) y el
foco de aterrizaje ilumina la pista. La **lluvia** se ve en el parabrisas, se oye sobre el fuselaje, reduce la
visibilidad y moja la pista (frena peor). La **tormenta** es un cumulonimbo que se ve desde lejos, con relámpagos,
truenos con su retraso, frente de ráfagas, turbulencia fuerte, descendentes en el núcleo y lluvia; en la cabina de
cristal aparece en el mapa (NEXRAD) y el ATIS la anuncia. En Vuelo libre y en la estación del instructor hay dos
preajustes nuevos: **Lluvia** y **Tormenta** (se forma a 8 km y avanza hacia el aeródromo).

Las misiones de Base Sucre cargan solas el escenario real de la **Base Aérea Mariscal Sucre (SVBS), Maracay**.
Todas las demás lecciones, emergencias y exámenes también funcionan allí (`python tests/test_lugar_real.py SVBS`).

**Emergencias en cualquier vuelo:** la estación del instructor (tecla I) o el puesto en red pueden provocar
17 fallas (motor, fuego, humo, eléctrica, alternador, radio, vacío, pitot, estática, magneto, fuga de
combustible, tren, compensador, flaps, puerta abierta, PFD) **ahora, tras el despegue, en crucero, en la final,
dentro de 2 min o al azar**. Cada una tiene sus síntomas (humo, llamas, ruido, indicaciones) y se resuelve con
el procedimiento del manual; la tableta abre sola la **lista de emergencia** y el informe anota el tiempo de
reacción. Los mandos de emergencia (puerta, tren de emergencia **Mayús+G**,
cortacircuito del compensador **Z**, extintor, transpondedor 7700/7600, paracaídas CAPS del SR20) están en la cabina física.

Cada lección tiene briefing, instructor con voz en español que da indicaciones en tiempo real,
llamadas de altura en la aproximación, aros guía opcionales, análisis posterior con gráficas,
trayectoria, repetición 3D y exportación CSV. El progreso y la bitácora se guardan en `datos/`.

**Estación del instructor (tecla I):** cambiar viento, ráfagas, turbulencia, visibilidad, nubes,
QNH y hora; provocar fallas (motor, vacío, pitot, estática, eléctrica, alternador, flaps, PFD);
reposicionar el avión; combustible y cambio de avión.

## Puesto del instructor en red

Ajustes → **Instructor en red: Activado**. El simulador muestra una dirección (p. ej. `http://192.168.1.20:8765`)
y un **código de 4 cifras**. Desde cualquier computadora, tableta o móvil de la misma red, abra esa dirección en el
navegador e introduzca el código: verá el vuelo en directo (mapa con la trayectoria, el tráfico y la ruta,
velocidad, altitud, rumbo, motor, combustible, radio y nota final) y podrá **elegir y reiniciar lecciones, pausar,
reposicionar, cambiar la meteorología (o cargar el METAR real) y provocar o programar fallas**. La primera vez
Windows puede preguntar si permite a AeroEscuela usar la red privada: responda que sí.

## Alumnos e informes

Menú → **Progreso y bitácora**: cada alumno tiene su propio progreso y bitácora (*Nuevo alumno* / *Cambiar alumno*).
**Ficha del alumno (PDF)** genera una ficha con todas las tareas del programa, intentos, mejor nota y la bitácora;
tras cada vuelo, **Informe (PDF)** genera el informe del vuelo con la evaluación punto por punto y las gráficas
de altitud, velocidad y vario, con espacio para las firmas. Se abren en el navegador; desde ahí *Imprimir →
Guardar como PDF*. Se guardan en `datos/informes/`.

## Hablar con la torre por micrófono

Pulse **Ctrl derecho** (o el botón PTT asignado en la cabina física) y diga la transmisión: «solicito rodaje»,
«punto de espera listo para salir», «viento en cola», «base», «final toma y despegue», «motor y al aire»,
«mayday mayday mayday»… con o sin «torre» y el indicativo delante. Usa el reconocedor de voz en español de
Windows **sin Internet** y una gramática cerrada con las frases posibles en cada momento. Si Windows no deja usar
el micrófono: Configuración → Privacidad → Micrófono → permitir a las aplicaciones de escritorio.

## Meteorología real y peso y balance

- **METAR real:** en un aeropuerto real, estación del instructor → *☁ METAR real* (o desde el puesto en red):
  descarga el METAR de aviationweather.gov (o el de la estación más cercana) y aplica viento, ráfagas,
  visibilidad, nubes, temperatura y QNH.
- **Peso y rendimiento** (tableta, tecla K → *PESO Y RENDIMIENTO*): piloto, pasajeros, equipaje y combustible;
  peso total y **centro de gravedad dentro de la envolvente**, altitud de densidad, viento en pista y **distancias
  de despegue y aterrizaje** corregidas por altitud, temperatura, peso, viento y superficie. El peso se aplica al
  modelo de vuelo. Valores típicos de cada POH: use siempre los de su avión.

## Escenarios reales de cualquier aeropuerto del mundo

Menú → **Ubicación**: busque por código OACI/IATA, ciudad o nombre (≈48.000 aeropuertos).
El simulador genera 51 × 51 km alrededor del aeropuerto con:

- **Relieve real** (AWS Terrain Tiles: SRTM/GMTED).
- **Fotografía satelital** en tres niveles de detalle (1,2 m/píxel en 3 km alrededor de la pista, 4,8 m/píxel en 10 km
  y 12 m/píxel en todo el escenario), con los **edificios 3D de OpenStreetMap** y sus fachadas encima (en Ajustes →
  *Paisaje* se puede volver a la foto satelital pura).
- **Lagos, embalses y ríos anchos como agua de verdad** (contornos de OpenStreetMap): color de agua, reflejo del cielo,
  destello del sol y olas. Aterrizar en ellos es un amerizaje.
- **Pistas reales** con su orientación, longitud, anchura y número; aeródromos vecinos; **VOR reales**.
- **Edificios en 3D** opcionales (terminales, hangares, naves y casas con su contorno real de OpenStreetMap; altura estimada
  y tejado del color de la foto satelital) y **bosques y parques con árboles**.
- La pista en servicio se elige según el viento y todas las lecciones se adaptan a ella.

La primera carga de cada aeropuerto descarga unos 25 MB (≈1 minuto); queda en `datos/geo` y
después carga al instante. Necesita conexión a Internet solo esa primera vez.

Atribuciones: imágenes © Esri, Maxar, Earthstar Geographics (respaldo: Sentinel‑2 cloudless de EOX,
CC BY‑NC‑SA); relieve AWS Terrain Tiles / Mapzen; edificios y bosques © OpenStreetMap y Microsoft vía mosaicos
vectoriales de Esri; aeropuertos y radioayudas OurAirports (dominio público).
Uso personal y educativo.

## Imágenes propias

Las nubes, el asfalto y el césped son fotos (generadas con IA); para cambiarlas use `python tools/importar_imagenes.py` (nubes sobre fondo negro → transparencia; texturas →
repetibles sin costuras).

## Modelos 3D de los aviones

En las vistas de afuera (exterior, torre, cámara libre, repetición) y en el tráfico, los aviones son modelos 3D
reales descargados de Sketchfab (`assets/modelos`). Desde la cabina se siguen viendo las alas y la hélice del modelo
propio del simulador. Para cambiar o agregar uno, descargue el modelo en **glTF Binary (.glb)** y conviértalo:

    python tools/importar_modelo.py c172 Descargas/free_cessna_172sp.glb quitar=remove_before_flight,Concrete

El conversor lo pone en los ejes del avión, lo escala a la envergadura real, apoya las ruedas a la altura del tren,
reduce las texturas, hornea la penumbra de rendijas y uniones y guarda el crédito del autor (`invertir` si queda al
revés; `quitar=` para piezas que no deben verse en vuelo, como amarres). `python tools/importar_modelo.py hornear`
vuelve a calcular la penumbra de los ya convertidos. El avión que no tenga modelo se dibuja por código. El DA40 descargado traía la cúpula
abierta, así que por ahora sigue con el de código.

## Cabina física: pantalla solo de instrumentos

Para montar el simulador en una cabina real (volante, pedales, gases e interruptores físicos), la
pantalla de instrumentos muestra **solo los relojes**, sin mandos, botones ni textos de ayuda:
seis básicos, NAV 1/NAV 2, tacómetro, motor y combustible, radios (lectura) y anunciadores; en los
aviones G1000, el PFD y el MFD a toda la pantalla. Se elige en **Ajustes → Pantalla de instrumentos**
o con **F2** en vuelo:

- **Normal**: la vista habitual.
- **Solo instrumentos**: esta pantalla muestra únicamente los instrumentos (para un equipo o monitor
  que va detrás del tablero físico).
- **2.ª ventana / monitor**: la vista exterior sigue en la pantalla principal y los instrumentos se abren
  en una ventana aparte; si hay un segundo monitor, la ocupa entera sin bordes.

Los mandos físicos se conectan como joystick (ejes de alabeo, cabeceo, timón y gases en Ajustes).

## Tráfico aéreo y torre de control por voz

- **Tráfico IA**: avionetas (Cessna, Piper, Diamond) que hacen circuitos con tomas y despegues, llegadas
  que se incorporan a 45° al viento en cola y salidas. Esperan en el punto de espera si usted ocupa la pista,
  hacen motor y al aire si la pista no está libre, y se separan entre ellas. Se ven con luces de navegación,
  anticolisión, estroboscópicas y de aterrizaje.
- **Aviso de tráfico (TAS)**: rombos en el mapa del MFD con la altitud relativa (+05 = 500 ft por encima) y
  flecha de ascenso/descenso; si un tráfico se acerca a menos de 0,9 NM y ±600 ft, aparece «TRÁFICO» en el
  PFD y se oye «Tráfico, tráfico». Chocar con otro avión es un accidente.
- **Radio (tecla T)**: menú de lo que se puede decir según la fase (pedir rodaje, listo para salir, notificar
  viento en cola/base/final, toma y despegue, entrada al circuito, motor y al aire, MAYDAY), con las teclas 1–9
  o con el ratón. La torre contesta con voz de radio (filtro VHF, estática y squelch), da autorizaciones,
  secuencia («número 2, siga al Cessna en base»), le hace esperar si hay tráfico en final, da avisos de
  tráfico «a sus 2, 1 milla» y pide colación si no la hace. Los demás aviones también hablan en la frecuencia.
- **Frecuencias**: ATIS, rodadura y torre. En aeropuertos reales se usan las publicadas (OurAirports);
  hay que sintonizar COM1 (o usar los botones de sintonía rápida del panel de radio). El ATIS se escucha en
  bucle con letra de información, viento, visibilidad, nubes, temperatura y QNH.
- **Evaluación**: el informe final anota las faltas de comunicación (despegar o aterrizar sin autorización,
  incursión en pista, no colacionar). Solo se exige la radio si ha hablado con la torre en ese vuelo.
- Indicativo por defecto **EC‑AES** (`indicativo` en `datos/config.json`); tráfico y torre se activan o
  desactivan en Ajustes.

## Interfaz

Estilo futurista en menús y avisos (los instrumentos conservan su aspecto real): paneles de cristal con filetes de neón,
botones biselados con brillo y clic, rejilla y línea de barrido, barra de estado con hora local/UTC, coordenadas y
frecuencias del aeródromo, **globo terráqueo** dibujado con los 48.000 aeropuertos reales que gira hasta el lugar
elegido, **radar** con los aeródromos del escenario, pantalla de carga con anillo de progreso, transiciones suaves entre
pantallas, sonidos de interfaz (abrir, cerrar, aviso), nota del análisis en un anillo, pestañas de la tableta con
iconos e informes PDF con el mismo estilo. Títulos, botones y lecturas con la tipografía **Orbitron**.

## Mundo continuo: rutas largas sin cortes

En vuelo libre y en las travesías largas, al alejarse unos 13 km del centro del escenario el simulador prepara en
segundo plano el siguiente (centrado más adelante en la ruta) y, antes de llegar al borde, cambia a él **sin
detener el vuelo**: misma posición, altitud, velocidad, motor, radios y piloto automático. La primera vez que se
sobrevuela una zona hay que descargarla (1–2 min con Internet); si el avión llega al borde antes de que esté lista,
la simulación espera con un aviso.

## Probar todo con el ratón

Al mover el ratón durante el vuelo aparece arriba una **barra de botones** (se esconde sola a los 5 s, así no
estorba en la cabina física): Menú, Radio, Hablar, Tableta, Instructor, Pantalla, Mover instrumentos,
Cámara, Arrancar, Repetición, Reiniciar y Ayuda. Cada botón hace lo mismo que su tecla.

## Conexión con un simulador de tránsito aéreo

Ajustes → **ATC externo: Sí** deja el simulador listo para conectarse con un simulador de control de tránsito
aéreo en la misma red (puerto 8770; se anuncia solo en la red). El otro simulador recibe en directo la posición,
altitud, velocidad, transpondedor y frecuencia del avión, lo que dice el piloto y los despegues, aterrizajes y
emergencias; puede llevar la torre (la automática se calla), hablarle al piloto con voz de radio, mandar su propio
tráfico (se ve en el paisaje y en el TCAS) y fijar viento y QNH. El protocolo completo, con ejemplos, está en
**`docs/PROTOCOLO_ATC.md`**. Para probarlo sin el otro simulador: **`Consola_ATC_Prueba.bat`** (una consola de
controlador de ejemplo con radar, radio y frases rápidas). Prueba automática: `python tests/test_atc_externo.py`.

## Controles principales

| Tecla | Acción | Tecla | Acción |
|---|---|---|---|
| ↑ / ↓ | nariz abajo / arriba | Z / X / C | PA · modo rumbo · mantener altitud |
| ← / → | alabeo | , / . | marcador de rumbo |
| A / D | pedales y rueda de morro | Tab | cabina clásica / G1000 |
| W / S | gases (Shift: rápido) | 1 2 3 4 | cabina · exterior · torre · libre |
| P | cabina automática · panel 2D · cabina 3D · sin panel | Rueda | zoom / mandos del tablero |
| Q / E | compensador | Ctrl+flechas o botón derecho | mirar alrededor |
| F / V | flaps | K | lista de verificación (tableta) |
| T | radio: torre / rodadura / ATIS | 1–9 | (con la radio abierta) elegir transmisión |
| O | mandos de cada sistema (motor, combustible, eléctrico, luces, flaps/compensador, tren/frenos) | F2 | pantalla solo de instrumentos (cabina física) |
| 5 | vista de instrumentos | Y | mostrar / ocultar volantes (cabina 3D) |
| Espacio / B | frenos / freno de estacionamiento | R | repetición instantánea |
| M / N | mezcla | I | estación del instructor |
| G | tren (Arrow) | Esc | pausa / menú |
| Ctrl+E | arranque automático | F12 | captura de pantalla |
| | | Mayús+F12 | **Foto pro**: paisaje y avión limpios en 4K (`datos/capturas`) |

Joystick o volante de vuelo: se detecta solo; los ejes se configuran en Ajustes.

**Guía paso a paso para conectar la cabina:** `docs/GUIA_CABINA_FISICA.md`. La pestaña **Diagnóstico y prueba** muestra en directo cada eje y botón, prueba el micrófono, lista los monitores y dice qué falta; **Exportar/Importar** copia las asignaciones a otra computadora con la misma cabina.

**La consola física es la del Cessna 172S**, el avión de referencia. Los demás aviones se pueden volar, pero sin ella:
con otro avión la consola no se lee (ni volante, ni palancas, ni interruptores), la cabina automática muestra el panel 2D
y las pantallas «franja» y «solo instrumentos» vuelven a la normal. Se vuelan con teclado, ratón o un joystick USB aparte.

**Cabina física (menú → Cabina física):** asigne a cada función el eje, interruptor o botón real de cualquier
dispositivo USB (volante, cuadrante de gases, pedales con frenos de pie, placas de botones): ejes de alabeo,
cabeceo, timón, frenos, gases (uno por motor), mezcla, hélice, flaps y compensador; interruptores de batería,
alternador, aviónica, bomba, luces, pitot, tren, freno de estacionamiento, ENGINE MASTER; posiciones de la llave de
magnetos y del selector de combustible; pulsadores de flaps, desconexión del PA, radio (abrir, siguiente opción,
transmitir), PTT de voz, pausa y reinicio; y las teclas y perillas del G1000 (`app/consola_g1000.py`). Pulse
*Asignar* y mueva el mando real. Con esto y el puesto del
instructor en red, la cabina se maneja sin ratón ni teclado.

**Pantallas para cabina física:** F2 alterna *paisaje + instrumentos*, *solo instrumentos* y *2.º monitor*;
**F3** abre el editor para mover y escalar cada instrumento hasta que coincida con los huecos del tablero físico.
En Ajustes, *Vista exterior: 3 vistas (panorámica)* y el número de monitores que ocupa el paisaje (p. ej. 3
monitores delante y un 4.º detrás del tablero para los instrumentos).

## Estructura del código

```
main.py              punto de entrada
sim/                 física y lógica (sin gráficos)
  flightmodel.py     modelo 6DOF         systems.py   motor, eléctrico, vacío, flaps, tren
  aircraft_data.py   los 7 aviones        atmosphere.py ISA, viento, turbulencia, humedad
  terrain.py         terreno              airports.py   aeródromos del escenario escuela
  nav.py             VOR/ILS/DME/ADF      autopilot.py  piloto automático
  gps.py             GPS y plan de vuelo  weight.py     peso, centrado y rendimiento
  world.py           integra todo         lessons.py    programa ACS y evaluación
  geo.py             datos reales         recorder.py   caja negra
  traffic.py         tráfico IA           atc.py        torre, rodadura, ATIS y fraseología
  checklists.py      listas de verificación por fase
render/              OpenGL (moderngl): shaders, terreno, satélite, nubes, luces, avión 3D, cabina 3D
assets/              texturas fotográficas (generadas con tools/make_assets.py)
ui/                  panel analógico, G1000, controles de interfaz
app/                 aplicación, menús, sonido sintetizado, voz, radio VHF (radio.py), mandos, progreso
tests/               pruebas: física, piloto automático, lecciones con "alumno robot", geodatos
```

Pruebas sin ventana: `python tools/pruebas.py` (todas las que no necesitan internet, las mismas que GitHub en cada
pull request) o una sola, p. ej. `python tests/test_lessons.py` (con `LOC=LEMD` para probar en un aeropuerto real).

## Licencias de los datos

- **Imágenes satelitales (Esri World Imagery):** sus condiciones permiten el uso personal, educativo y no comercial
  con atribución (se muestra en pantalla). **Para vender el simulador o usarlo con fines comerciales hace falta
  una licencia de Esri** (o cambiar a otro proveedor con licencia comercial, p. ej. Mapbox Satellite o Maxar).
  La alternativa gratuita Sentinel‑2 cloudless (EOX) es CC BY‑NC‑SA: tampoco permite uso comercial.
- Relieve (AWS Terrain Tiles), aeropuertos (OurAirports, dominio público) y METAR (NOAA, dominio público):
  sin restricciones relevantes. Edificios y bosques: © OpenStreetMap (ODbL), con atribución.
- Voces: síntesis y reconocimiento de voz incluidos en Windows.
- Modelos 3D de los aviones (Sketchfab, **CC BY 4.0**, uso comercial permitido citando al autor; la cita se muestra en
  Vuelo libre y está en `assets/modelos/CREDITOS.json`): «FREE Cessna 172SP» de NLM, «Cessna 152» de micheal_wain,
  «Piper Pa 28 Cadet», «Diamond Da42 Twin Star» de helijah y «Cirrus SR22» de KOG_THORNS.
- Texturas fotográficas del suelo (**CC0**, dominio público, uso comercial libre): «Asphalt Pit Lane» y «Concrete
  Floor 02» de Poly Haven, «Grass004» de ambientCG (`assets/CREDITOS_TEXTURAS.md`).
- Tipografía **Orbitron** (© The Orbitron Project Authors, SIL Open Font License 1.1, texto en `assets/fuentes/Orbitron_OFL.txt`): libre para uso comercial e incluida con el programa.

## Límites honestos

- Es un simulador de entrenamiento de procedimientos para PC; **no es un dispositivo certificado**
  (FTD/FFS) y no sustituye horas de instrucción reales registrables.
- La aerodinámica del C172 se basa en datos públicos y está ajustada a las velocidades del manual;
  no es un paquete de datos del fabricante.
- En aeropuertos reales las frecuencias ILS son sintéticas (la base pública no las publica);
  pistas, aeródromos y VOR sí son reales. La altura de los edificios es estimada (la fuente no la incluye).
