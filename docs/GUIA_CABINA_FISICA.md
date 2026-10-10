# Guía para conectar la cabina física

Todo se hace en el menú **Cabina física**. La pestaña **Diagnóstico y prueba** muestra en directo lo que llega de
cada mando y una lista de lo que falta.

## 1. Antes de abrir AeroEscuela
1. Conecte todos los mandos USB (volante, pedales, cuadrante de gases, paneles de interruptores).
2. Compruebe que Windows los ve: tecla Windows → escriba `joy.cpl` → Intro. Deben aparecer en la lista.
3. Abra AeroEscuela. Si conecta algo después, pulse **Buscar**.

## 2. Identificar cada mando (Diagnóstico y prueba → 1)
Cada dispositivo aparece con sus ejes (barras E0, E1…) y sus botones (puntos que se encienden). Mueva cada mando y
anote qué barra o punto cambia. Así sabrá, por ejemplo, que el timón es el «E5» de los pedales.

## 3. Asignar (pestaña Asignar mandos)
1. Pulse **Asignar** junto a la función y mueva ese mando **a fondo** (o accione el interruptor).
2. Vuelva a **Diagnóstico y prueba → 2** y compruebe el sentido:
   - Volante: tirar hacia usted → el círculo **baja**; girar a la derecha → va a la **derecha**.
   - Pedal derecho → la barra del timón **sube**.
   - Gases, mezcla y hélice: palanca adelante → barra **llena**. Frenos: pisar → barra **llena**.
   - Si algo va al revés, pulse **⇅** en Asignar mandos.
3. Asigne como mínimo: volante (alabeo y cabeceo), pedales, gases, frenos, batería, alternador, aviónica, llave de
   magnetos y el **botón para hablar por micrófono (PTT)**. Los mandos de emergencia (puerta, extintor, tren de
   emergencia, cortacircuito del compensador, CAPS, transpondedor 7700/7600) están al final de la lista.

## 4. Micrófono
1. Windows → Configuración → Privacidad y seguridad → **Micrófono** → permitir a las aplicaciones de escritorio.
2. Windows → Configuración → Hora e idioma → **Voz**: debe estar el reconocimiento en **español**.
3. Diagnóstico → **Probar micrófono** y diga «prueba de micrófono». Debe salir ✓ con lo que entendió.
4. En vuelo: pulse el botón PTT (o Ctrl derecho) y diga la frase de radio («solicito rodaje», «listo para salir»…).

## 5. Monitores
1. Windows → Configuración → Sistema → Pantalla → **Extender estas pantallas**; ordénelas de izquierda a derecha.
2. AeroEscuela → Ajustes:
   - **Pantalla de instrumentos**: «Paisaje + instr.» (un monitor), «2.º monitor» (instrumentos en otro) o «Solo
     instrumentos».
   - **Vista exterior**: 1 vista o 3 vistas (panorámica) y en cuántos monitores va el paisaje.
   - **Fondo de instrumentos**: «Negro (cabina física)» si delante hay un tablero con los huecos de los relojes.
3. En vuelo, **F3** permite mover y escalar cada instrumento hasta que coincida con el hueco del tablero.

## 6. Varias cabinas iguales
Cuando una cabina esté lista: Asignar mandos → **Exportar** (crea `cabina_fisica.json` en la carpeta de datos).
Copie ese archivo a la carpeta de datos de la otra computadora (`%LOCALAPPDATA%\AeroEscuela\datos`) y pulse
**Importar**. Funciona si los mandos son del mismo modelo.

## Si algo falla
- Un mando no aparece: otro puerto USB (mejor directo al equipo, sin concentrador) y **Buscar**.
- Un eje tiembla en reposo: es normal un poco; el simulador ignora los movimientos muy pequeños.
- El micrófono no entiende: hable cerca, después de pulsar el PTT, y con las frases del menú de radio (T).
