"""Cabina física: asignación de ejes, interruptores y pulsadores de cualquier dispositivo USB
(volante, cuadrante de gases, pedales, placas de botones tipo «joystick»).

Cada función se asigna en Ajustes → Cabina física pulsando «Asignar» y moviendo el mando real.
Se guardan en config.json por el identificador (GUID) del dispositivo, así se conservan aunque
Windows cambie el orden de los dispositivos.

Tipos de función:
  eje        valor continuo (alabeo, cabeceo, timón, gases, mezcla, hélice, frenos de pie, flaps)
  interruptor  interruptor de palanca con posición fija: ON mientras el botón está cerrado
  pulsador   acción al pulsar (flaps arriba/abajo, desconexión del PA, menú de radio…)
  mantener   activo mientras se mantiene pulsado (arranque, frenos, compensador)
"""
import math
import os

import pygame

from sim.mathx import clamp

# (clave, nombre, tipo)
FUNCTIONS = [
    ("eje_alabeo", "Volante: alabeo", "eje"),
    ("eje_cabeceo", "Volante: cabeceo", "eje"),
    ("eje_timon", "Pedales: timón", "eje"),
    ("eje_freno_izq", "Freno de pie izquierdo", "eje"),
    ("eje_freno_der", "Freno de pie derecho", "eje"),
    ("eje_gases", "Gases (motor 1)", "eje"),
    ("eje_gases2", "Gases motor 2 (bimotor)", "eje"),
    ("eje_mezcla", "Mezcla", "eje"),
    ("eje_helice", "Paso de hélice", "eje"),
    ("eje_flaps", "Palanca de flaps (eje)", "eje"),
    ("eje_trim", "Rueda del compensador (eje)", "eje"),
    ("sw_bat", "Interruptor BATERÍA", "interruptor"),
    ("sw_alt", "Interruptor ALTERNADOR", "interruptor"),
    ("sw_avionica", "Interruptor AVIÓNICA", "interruptor"),
    ("sw_bomba", "Bomba de combustible", "interruptor"),
    ("sw_beacon", "Luz anticolisión", "interruptor"),
    ("sw_nav", "Luces de navegación", "interruptor"),
    ("sw_strobe", "Luces estroboscópicas", "interruptor"),
    ("sw_taxi", "Luz de rodaje", "interruptor"),
    ("sw_landing", "Luz de aterrizaje", "interruptor"),
    ("sw_pitot", "Calefacción del pitot", "interruptor"),
    ("sw_calef_carb", "Calefacción al carburador", "interruptor"),
    ("sw_tren", "Palanca del tren (ON = abajo)", "interruptor"),
    ("sw_freno_est", "Freno de estacionamiento", "interruptor"),
    ("sw_motor1", "MOTOR / ENGINE MASTER 1 (FADEC)", "interruptor"),
    ("sw_motor2", "MOTOR / ENGINE MASTER 2 (FADEC)", "interruptor"),
    ("mag_off", "Llave de magnetos: OFF", "interruptor"),
    ("mag_der", "Llave de magnetos: DER", "interruptor"),
    ("mag_izq", "Llave de magnetos: IZQ", "interruptor"),
    ("mag_ambos", "Llave de magnetos: AMBOS", "interruptor"),
    ("mag_arranque", "Llave de magnetos: ARRANQUE", "mantener"),
    ("comb_cerrado", "Selector combustible: CERRADO", "interruptor"),
    ("comb_izq", "Selector combustible: IZQ", "interruptor"),
    ("comb_der", "Selector combustible: DER", "interruptor"),
    ("comb_ambos", "Selector combustible: AMBOS", "interruptor"),
    ("btn_arranque", "Botón de arranque", "mantener"),
    ("btn_frenos", "Frenos (ambos)", "mantener"),
    ("btn_trim_arriba", "Compensador: nariz arriba", "mantener"),
    ("btn_trim_abajo", "Compensador: nariz abajo", "mantener"),
    ("btn_flaps_arriba", "Flaps: subir un punto", "pulsador"),
    ("btn_flaps_abajo", "Flaps: bajar un punto", "pulsador"),
    ("btn_pa", "Desconexión del piloto automático", "pulsador"),
    ("btn_radio", "Abrir / cerrar menú de radio", "pulsador"),
    ("btn_radio_sig", "Radio: siguiente opción", "pulsador"),
    ("btn_radio_ok", "Radio: transmitir (PTT)", "pulsador"),
    ("btn_ptt_voz", "Hablar a la torre por micrófono (PTT)", "pulsador"),
    ("btn_puerta", "Emergencia: cerrar la puerta", "pulsador"),
    ("btn_tren_emerg", "Emergencia: extensión del tren", "pulsador"),
    ("btn_cb_trim", "Emergencia: cortacircuito del compensador", "pulsador"),
    ("btn_extintor", "Emergencia: extintor", "pulsador"),
    ("btn_caps", "Emergencia: paracaídas CAPS (SR20)", "pulsador"),
    ("btn_xpdr_7700", "Transpondedor 7700 (emergencia)", "pulsador"),
    ("btn_xpdr_7600", "Transpondedor 7600 (sin radio)", "pulsador"),
    ("btn_xpdr_1200", "Transpondedor 1200 (VFR)", "pulsador"),
    ("btn_pausa", "Pausa", "pulsador"),
    ("btn_reiniciar", "Reiniciar la lección", "pulsador"),
]
NAMES = {k: n for k, n, _ in FUNCTIONS}
KIND = {k: t for k, _, t in FUNCTIONS}
CENTERED = ("eje_alabeo", "eje_cabeceo", "eje_timon", "eje_trim")     # ejes con centro (el resto son palancas)
SHAPED = ("eje_alabeo", "eje_cabeceo", "eje_timon")    # ejes de vuelo con zona muerta y curva propias (Sensibilidad)
DEFAULT_DZ = 0.04            # zona muerta por defecto (fracción del recorrido)
DEFAULT_EXPO = 0.35          # curva por defecto: 0 = lineal, 1 = cúbica (más suave en el centro)
HAT_DIRS = {"arriba": (0, 1), "abajo": (0, -1), "izquierda": (-1, 0), "derecha": (1, 0)}
HAT_ARROW = {"arriba": "↑", "abajo": "↓", "izquierda": "←", "derecha": "→"}


def shape(v, dz=DEFAULT_DZ, k=DEFAULT_EXPO):
    """Zona muerta (sin salto: el recorrido que queda va de 0 a 1) y curva exponencial de un eje centrado."""
    a = abs(v)
    if a <= dz:
        return 0.0
    a = (a - dz) / (1.0 - dz) if dz < 1 else 0.0
    return math.copysign((1.0 - k) * a + k * a * a * a, v)
SELECTORS = {"mag": "Llave de magnetos", "comb": "Selector de combustible"}
_SDL = None


def _sdl():
    """El SDL2 que ya usa pygame, para leer lo que pygame no ofrece (número de serie, ruta USB). None si no se puede."""
    global _SDL
    if _SDL is None:
        _SDL = False
        try:
            import ctypes
            lib = ctypes.CDLL(os.path.join(os.path.dirname(pygame.__file__), "SDL2.dll"))
            lib.SDL_JoystickFromInstanceID.restype = ctypes.c_void_p
            lib.SDL_JoystickFromInstanceID.argtypes = [ctypes.c_int32]
            for fn in (lib.SDL_JoystickGetSerial, lib.SDL_JoystickPath):
                fn.restype = ctypes.c_char_p
                fn.argtypes = [ctypes.c_void_p]
            _SDL = lib
        except (OSError, AttributeError):
            pass
    return _SDL or None


def unit_id(j):
    """Identifica la unidad física, no el modelo: número de serie o, si no tiene, la ruta USB (depende del puerto)."""
    lib = _sdl()
    if lib is None:
        return None
    try:
        p = lib.SDL_JoystickFromInstanceID(j.get_instance_id())
        for fn, tag in ((lib.SDL_JoystickGetSerial, "serie"), (lib.SDL_JoystickPath, "ruta")):
            v = fn(p) if p else None
            if v:
                return f"{tag}:{v.decode('utf-8', 'replace')}"
    except (pygame.error, OSError):
        pass
    return None


def _model(key):
    return key.rsplit("#", 1)[0]


class Hardware:
    def __init__(self, cfg):
        self.cfg = cfg if cfg is not None else {}
        self.cfg.setdefault("asignaciones", {})
        self.devices = {}            # guid -> Joystick
        self.names = {}              # guid -> nombre (guardado: un mando ya desconectado no lo da)
        self.prev = {}
        self.capture = None          # función que se está asignando
        self.capture_base = None
        self.calib = None            # calibración en curso: función -> (mínimo, máximo) leídos
        self.sync_pending = True     # copiar la posición de los interruptores reales en la próxima lectura
        self.mismatch = set()        # interruptores reales que no coinciden con el avión
        self.radio_sel = 0
        self.brake_cmd = 0.0         # botón de frenos (los dos lados)
        self.brake_l = self.brake_r = 0.0   # frenos de pie, cada uno en su rueda
        self.refresh()

    # ------------------------------------------------------------ dispositivos
    def refresh(self):
        """Vuelve a abrir todos los mandos. Devuelve (nombres conectados, nombres desconectados) desde la última vez.

        Cada mando se guarda como «GUID#n». El GUID es del modelo, así que dos unidades iguales (dos cuadrantes,
        dos paneles) solo se distinguen por n. Para que no se intercambien al cambiar el orden de Windows, cada n
        recuerda su unidad (número de serie o ruta USB) en "unidades"; sin ese dato se usa el orden, como antes."""
        old = dict(self.names)
        pygame.joystick.init()
        joys = []
        for i in range(pygame.joystick.get_count()):
            try:
                j = pygame.joystick.Joystick(i)
                j.init()
                joys.append((j.get_guid(), j, unit_id(j)))
            except pygame.error:
                pass
        ids = [u for _, _, u in joys if u]
        joys = [(g, j, u if ids.count(u) == 1 else None) for g, j, u in joys]   # serie repetida: no sirve
        units = self.cfg.setdefault("unidades", {})                              # "GUID#n" -> unidad
        keys = {}
        for n, (guid, j, uid) in enumerate(joys):        # primero las unidades ya conocidas, en su n de siempre
            k = next((k for k, u in units.items() if u == uid and _model(k) == guid), None) if uid else None
            if k is not None and k not in keys.values():
                keys[n] = k
        for n, (guid, j, uid) in enumerate(joys):        # después las nuevas, en el primer n libre
            if n not in keys:
                i = 0
                while f"{guid}#{i}" in keys.values():
                    i += 1
                keys[n] = f"{guid}#{i}"
        self.devices = {}
        self.names = {}
        for n, (guid, j, uid) in enumerate(joys):
            k = keys[n]
            self.devices[k] = j
            self.names[k] = j.get_name()
            if uid:
                for stale in [s for s, u in units.items() if u == uid and s != k]:
                    del units[stale]
                units[k] = uid
        added = [n for g, n in self.names.items() if g not in old]
        removed = [n for g, n in old.items() if g not in self.names]
        if added or removed:
            self.prev.clear()
            self.sync_pending = True
        return added, removed

    def device_list(self):
        return [(g, self.label(g), j.get_numaxes(), j.get_numbuttons()) for g, j in self.devices.items()]

    def label(self, key):
        """Nombre del mando; con unidades iguales conectadas se numeran: «Cuadrante (1)», «Cuadrante (2)»."""
        name = self.names.get(key, "")
        twins = sum(1 for g in self.devices if _model(g) == _model(key))
        return f"{name} ({int(key.rsplit('#', 1)[1]) + 1})" if twins > 1 else name

    def twin_groups(self):
        """Modelos con dos o más unidades conectadas: [(nombre, [claves])]."""
        groups = {}
        for g in self.devices:
            groups.setdefault(_model(g), []).append(g)
        return [(self.names[ks[0]], sorted(ks)) for ks in groups.values() if len(ks) > 1]

    def swap_twins(self):
        """Corrige a mano unidades iguales que quedaron cruzadas: las asignaciones pasan de cada unidad a la
        siguiente (con dos, se intercambian). Devuelve los nombres de los modelos afectados."""
        done = []
        for name, ks in self.twin_groups():
            nxt = {k: ks[(i + 1) % len(ks)] for i, k in enumerate(ks)}
            for b in self.bindings.values():
                if b.get("dev") in nxt:
                    b["dev"] = nxt[b["dev"]]
                    b.pop("cal", None)       # se midió en la otra unidad: hay que volver a calibrar
            done.append(name)
        if done:
            self.prev.clear()
            self.sync_pending = True
        return done

    def uses_device(self, joy):
        """True si alguna asignación usa este joystick: así el joystick genérico no lo lee por segunda vez."""
        if joy is None:
            return False
        try:
            iid = joy.get_instance_id()
            return any(j is not None and j.get_instance_id() == iid
                       for j in (self.devices.get(b.get("dev")) for b in self.bindings.values()))
        except pygame.error:
            return False

    @property
    def bindings(self):
        return self.cfg["asignaciones"]

    def describe(self, key):
        b = self.bindings.get(key)
        if not b:
            return "—"
        dev = self.label(b["dev"])[:26] if b["dev"] in self.devices else "(no conectado)"
        if "eje" in b:
            return f"{dev} · eje {b['eje']}" + (" (inv.)" if b.get("inv") else "") + (" · cal." if b.get("cal") else "")
        if "hat" in b:
            return f"{dev} · seta {b['hat']} {HAT_ARROW.get(b.get('dir'), '?')}"
        return f"{dev} · botón {b['btn']}"

    # ------------------------------------------------------------ perfiles (copiar una cabina a otra computadora)
    def export_profile(self):
        import json
        from .core import DATA
        p = os.path.join(DATA, "cabina_fisica.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"asignaciones": self.bindings,
                       "dispositivos": {g: j.get_name() for g, j in self.devices.items()}}, f, ensure_ascii=False, indent=1)
        return p

    def import_profile(self):
        import json
        from .core import DATA
        p = os.path.join(DATA, "cabina_fisica.json")
        if not os.path.exists(p):
            return 0
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        self.bindings.clear()
        self.bindings.update(data.get("asignaciones", {}))
        return len(self.bindings)

    # ------------------------------------------------------------ calibración (mínimo, centro y máximo de cada eje)
    def start_calibration(self):
        self.capture = None
        self.calib = {}

    def poll_calibration(self):
        for key, b in self.bindings.items():
            j = self.devices.get(b.get("dev"))
            if "eje" not in b or j is None or b["eje"] >= j.get_numaxes():
                continue
            v = j.get_axis(b["eje"])
            lo, hi = self.calib.get(key, (v, v))
            self.calib[key] = (min(lo, v), max(hi, v))

    def finish_calibration(self):
        """Guarda el recorrido medido. El centro es la posición actual (volante, pedales y compensador sueltos).
        Devuelve cuántos ejes se calibraron; los que apenas se movieron conservan su calibración anterior."""
        n = 0
        for key, (lo, hi) in (self.calib or {}).items():
            if hi - lo < 0.3:
                continue
            b = self.bindings[key]
            cal = {"min": round(lo, 4), "max": round(hi, 4)}
            if key in CENTERED:
                j = self.devices.get(b["dev"])
                v = j.get_axis(b["eje"]) if j is not None else (lo + hi) / 2
                q = (hi - lo) * 0.25
                cal["cen"] = round(v if lo + q < v < hi - q else (lo + hi) / 2, 4)
            b["cal"] = cal
            n += 1
        self.calib = None
        return n

    @staticmethod
    def _calibrated(v, cal):
        lo, hi, c = cal["min"], cal["max"], cal.get("cen")
        if c is None:
            v = 2 * (v - lo) / (hi - lo) - 1 if hi > lo else v
        elif v >= c:
            v = (v - c) / (hi - c) if hi > c else 0.0
        else:
            v = (v - c) / (c - lo) if c > lo else 0.0
        return clamp(v, -1.0, 1.0)

    # ------------------------------------------------------------ asignación
    def start_capture(self, key):
        self.calib = None
        self.capture = key
        self.capture_base = {g: [j.get_axis(a) for a in range(j.get_numaxes())] for g, j in self.devices.items()}
        self.capture_btns = {g: [j.get_button(b) for b in range(j.get_numbuttons())] for g, j in self.devices.items()}
        self.capture_hats = {g: [j.get_hat(h) for h in range(j.get_numhats())] for g, j in self.devices.items()}

    def clear(self, key):
        self.bindings.pop(key, None)

    def invert(self, key):
        b = self.bindings.get(key)
        if b and "eje" in b:
            b["inv"] = not b.get("inv", False)

    def _poll_capture(self):
        key = self.capture
        want_axis = KIND[key] == "eje"
        for g, j in self.devices.items():
            if want_axis:
                for a in range(j.get_numaxes()):
                    if abs(j.get_axis(a) - self.capture_base[g][a]) > 0.5:
                        self.bindings[key] = dict(dev=g, eje=a, inv=False)
                        self.capture = None
                        return
            else:
                for b in range(j.get_numbuttons()):
                    if j.get_button(b) != self.capture_btns[g][b]:
                        self.bindings[key] = dict(dev=g, btn=b)
                        self.capture = None
                        return
                # seta (palanca de 4 posiciones): cada dirección vale como un botón
                for h in range(j.get_numhats()):
                    hx, hy = j.get_hat(h)
                    if (hx, hy) != (0, 0) and (hx, hy) != tuple(self.capture_hats[g][h]):
                        d = "arriba" if hy > 0 else ("abajo" if hy < 0 else ("derecha" if hx > 0 else "izquierda"))
                        self.bindings[key] = dict(dev=g, hat=h, dir=d)
                        self.capture = None
                        return

    # ------------------------------------------------------------ lectura
    def axis(self, key, deadzone=0.04):
        b = self.bindings.get(key)
        if not b or "eje" not in b:
            return None
        j = self.devices.get(b["dev"])
        if j is None or b["eje"] >= j.get_numaxes():
            return None
        v = j.get_axis(b["eje"])
        if b.get("cal"):
            v = self._calibrated(v, b["cal"])
        if b.get("inv"):
            v = -v
        if abs(v) < deadzone:
            v = 0.0
        return v

    def shaped(self, key):
        """Eje de vuelo con la zona muerta ("zm") y la curva ("exp") de ese eje; None si no está asignado."""
        v = self.axis(key, 0.0)
        if v is None:
            return None
        b = self.bindings[key]
        return shape(v, b.get("zm", DEFAULT_DZ), b.get("exp", DEFAULT_EXPO))

    def raw_state(self, b):
        """Estado de un botón o de una dirección de seta asignados; None si el mando no está."""
        j = self.devices.get(b.get("dev"))
        if j is None:
            return None
        if "btn" in b:
            return bool(j.get_button(b["btn"])) if b["btn"] < j.get_numbuttons() else None
        if "hat" in b and b["hat"] < j.get_numhats():
            hx, hy = j.get_hat(b["hat"])
            dx, dy = HAT_DIRS.get(b.get("dir"), (0, 0))
            return bool((dx and hx == dx) or (dy and hy == dy))
        return None

    def button(self, key):
        """(estado, recién pulsado, recién soltado) de un botón o de una dirección de seta."""
        b = self.bindings.get(key)
        if not b or ("btn" not in b and "hat" not in b):
            return None, False, False
        now = self.raw_state(b)
        if now is None:
            return None, False, False
        prev = self.prev.get(key, now)
        self.prev[key] = now
        return now, now and not prev, prev and not now

    def has_axis(self, key):
        return self.axis(key) is not None

    # ------------------------------------------------------------ aplicar al avión
    def update(self, dt, world, app):
        self.brake_cmd = self.brake_l = self.brake_r = 0.0   # sin lectura (mando quitado) no queda frenado
        if self.capture:
            self._poll_capture()
            return
        if not self.bindings or not self.devices:
            return
        ac = world.ac
        s = ac.sys
        engs = s.engines

        def lever01(key):
            v = self.axis(key, 0.0)
            return None if v is None else clamp((v + 1) / 2, 0.0, 1.0)

        # palancas
        v = lever01("eje_gases")
        if v is not None:
            targets = engs if len(engs) == 1 or not self.has_axis("eje_gases2") else engs[:1]
            for en in targets:
                en.throttle = v
        v = lever01("eje_gases2")
        if v is not None and len(engs) > 1:
            engs[1].throttle = v
        v = lever01("eje_mezcla")
        if v is not None:
            for en in engs:
                en.mixture = v
        v = lever01("eje_helice")
        if v is not None:
            for en in engs:
                en.prop_lever = v
        v = lever01("eje_flaps")
        if v is not None:
            n = len(ac.t.flap_settings)
            s.flaps_cmd = int(clamp(round(v * (n - 1)), 0, n - 1))
        v = self.axis("eje_trim", 0.0)
        if v is not None:
            ac.trim = clamp(v, -1, 1)
        # interruptores (se aplican al cambiar, para no pelear con lecciones ni teclado): clave -> (leer, poner)
        def attr(obj, name):
            return (lambda: bool(getattr(obj, name)), lambda on: setattr(obj, name, on))
        sw = {"sw_bat": attr(s, "master"), "sw_alt": attr(s, "alternator"), "sw_avionica": attr(s, "avionics"),
              "sw_bomba": attr(s, "fuel_pump"), "sw_pitot": attr(s, "pitot_heat"), "sw_tren": attr(s, "gear_down"),
              "sw_calef_carb": attr(s, "carb_heat"),
              "sw_freno_est": attr(s, "parking_brake")}
        for k, light in (("sw_beacon", "beacon"), ("sw_nav", "nav"), ("sw_strobe", "strobe"), ("sw_taxi", "taxi"),
                         ("sw_landing", "landing")):
            sw[k] = (lambda L: (lambda: bool(s.lights.get(L)), lambda on: s.lights.__setitem__(L, on)))(light)
        for i, k in enumerate(("sw_motor1", "sw_motor2")):
            if i < len(engs):
                sw[k] = (lambda en: (lambda: en.magnetos > 0,
                                     lambda on: setattr(en, "magnetos", 3 if on else 0)))(engs[i])
        # selectores de varias posiciones (un botón por posición): grupo -> (posiciones, leer, poner)
        def set_mags(v):
            engs[0].magnetos = v
        def set_fuel(v):
            s.fuel_selector = v
        sel = {"mag": ((("mag_off", 0), ("mag_der", 1), ("mag_izq", 2), ("mag_ambos", 3)),
                       lambda: engs[0].magnetos, set_mags),
               "comb": ((("comb_cerrado", 0), ("comb_izq", 1), ("comb_der", 2), ("comb_ambos", 3)),
                        lambda: s.fuel_selector, set_fuel)}
        if self.sync_pending:
            self._sync_switches(world, app, sw, sel)
        for k, (_, put) in sw.items():
            st, pr, rl = self.button(k)
            if pr or rl:
                put(bool(st))
                self.mismatch.discard(k)
        for g, (positions, _, put) in sel.items():
            for k, val in positions:
                st, pr, _ = self.button(k)
                if pr:
                    put(val)
                    self.mismatch.discard(g)
        starter = False
        for k in ("mag_arranque", "btn_arranque"):
            st, _, _ = self.button(k)
            if st:
                starter = True
                if k == "mag_arranque":
                    engs[0].magnetos = 3
        if starter:
            app.panel.starter_held = True
        st, _, _ = self.button("btn_frenos")
        fl = lever01("eje_freno_izq")
        fr = lever01("eje_freno_der")
        if (fl is None) != (fr is None):             # un solo eje de freno asignado: frena las dos ruedas
            fl = fr = fl if fr is None else fr
        self.brake_l = fl if fl and fl > 0.02 else 0.0
        self.brake_r = fr if fr and fr > 0.02 else 0.0
        self.brake_cmd = 1.0 if st else 0.0          # botón de frenos: los dos lados
        for k, d in (("btn_trim_arriba", 1), ("btn_trim_abajo", -1)):
            st, _, _ = self.button(k)
            if st:
                ac.trim = clamp(ac.trim + d * 0.22 * dt, -1, 1)
        _, pr, _ = self.button("btn_flaps_arriba")
        if pr:
            s.flaps_cmd = max(0, s.flaps_cmd - 1)
        _, pr, _ = self.button("btn_flaps_abajo")
        if pr:
            s.flaps_cmd = min(len(ac.t.flap_settings) - 1, s.flaps_cmd + 1)
        _, pr, _ = self.button("btn_pa")
        if pr:
            if s.failures.get("trim") and s.trim_cb:
                app.flash(world.emerg.trim_disconnect(), 2.5)
            world.ap.disengage("PA desconectado")
        # radio sin ratón: abrir menú, recorrer opciones y transmitir
        _, pr, _ = self.button("btn_radio")
        if pr:
            app.show_radio = not app.show_radio
            self.radio_sel = 0
        _, pr, _ = self.button("btn_radio_sig")
        if pr:
            n = max(1, len(world.atc.options()))
            self.radio_sel = (self.radio_sel + 1) % n
            app.show_radio = True
        _, pr, _ = self.button("btn_radio_ok")
        if pr and app.show_radio:
            app.radio_select(self.radio_sel)
            self.radio_sel = 0
        _, pr, _ = self.button("btn_ptt_voz")
        if pr:
            app.push_to_talk()
        _, pr, _ = self.button("btn_pausa")
        if pr:
            app.state = "pause" if app.state == "flight" else "flight"
        _, pr, _ = self.button("btn_reiniciar")
        if pr:
            app.restart_lesson()
        em = world.emerg
        for key, fn in (("btn_puerta", em.close_door), ("btn_cb_trim", em.trim_disconnect),
                        ("btn_extintor", em.extinguisher), ("btn_caps", em.deploy_caps),
                        ("btn_tren_emerg", em.gear_emergency if world.ac.t.retractable else None)):
            _, pr, _ = self.button(key)
            if pr and fn is not None:
                msg = fn()
                if msg:
                    app.flash(msg, 2.5)
        for code in (7700, 7600, 1200):
            _, pr, _ = self.button(f"btn_xpdr_{code}")
            if pr:
                world.xpdr = code
                app.flash(f"Transpondedor {code}", 1.5)

    def request_sync(self):
        """Al empezar un vuelo: la próxima lectura compara los interruptores reales con el avión."""
        self.sync_pending = True

    def _sync_switches(self, world, app, sw, sel):
        """Con el avión frío en tierra (motor parado) copia la posición de los interruptores reales. Si la lección
        empieza con el avión ya preparado (motor en marcha o en vuelo) no cambia nada: avisa de los que no coinciden,
        y cada uno toma el mando en cuanto se mueve."""
        self.sync_pending = False
        cold = world.ac.on_ground and not any(en.running for en in world.ac.sys.engines)
        diff = []                         # (clave, posición real, poner)
        for k, (get, put) in sw.items():
            st, _, _ = self.button(k)
            if st is not None and bool(st) != get():
                diff.append((k, bool(st), put))
        for g, (positions, get, put) in sel.items():
            real = [val for k, val in positions if self.button(k)[0]]
            if real and real[0] != get():
                diff.append((g, real[0], put))
        self.mismatch = set()
        for k, real, put in diff:
            if cold and k != "sw_tren":   # el tren nunca se sube en tierra por sincronizar
                put(real)
            else:
                self.mismatch.add(k)
        if self.mismatch:
            names = ", ".join(SELECTORS.get(k) or NAMES[k] for k in sorted(self.mismatch))
            app.flash(f"Cabina física distinta del avión: {names}. Póngalos como en el simulador.", 8)

    def flight_axes(self):
        """(alabeo, cabeceo, timón) de la cabina física, o None si no están asignados."""
        return self.shaped("eje_alabeo"), self.shaped("eje_cabeceo"), self.shaped("eje_timon")
