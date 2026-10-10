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


class Hardware:
    def __init__(self, cfg):
        self.cfg = cfg if cfg is not None else {}
        self.cfg.setdefault("asignaciones", {})
        self.devices = {}            # guid -> Joystick
        self.prev = {}
        self.capture = None          # función que se está asignando
        self.capture_base = None
        self.radio_sel = 0
        self.brake_cmd = 0.0
        self.refresh()

    # ------------------------------------------------------------ dispositivos
    def refresh(self):
        pygame.joystick.init()
        self.devices = {}
        for i in range(pygame.joystick.get_count()):
            try:
                j = pygame.joystick.Joystick(i)
                j.init()
                guid = j.get_guid() + f"#{sum(1 for g in self.devices if g.startswith(j.get_guid()))}"
                self.devices[guid] = j
            except Exception:
                pass

    def device_list(self):
        return [(g, j.get_name(), j.get_numaxes(), j.get_numbuttons()) for g, j in self.devices.items()]

    @property
    def bindings(self):
        return self.cfg["asignaciones"]

    def describe(self, key):
        b = self.bindings.get(key)
        if not b:
            return "—"
        j = self.devices.get(b["dev"])
        dev = j.get_name()[:22] if j else "(no conectado)"
        if "eje" in b:
            return f"{dev} · eje {b['eje']}" + (" (inv.)" if b.get("inv") else "")
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

    # ------------------------------------------------------------ asignación
    def start_capture(self, key):
        self.capture = key
        self.capture_base = {g: [j.get_axis(a) for a in range(j.get_numaxes())] for g, j in self.devices.items()}
        self.capture_btns = {g: [j.get_button(b) for b in range(j.get_numbuttons())] for g, j in self.devices.items()}

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

    # ------------------------------------------------------------ lectura
    def axis(self, key, deadzone=0.04):
        b = self.bindings.get(key)
        if not b or "eje" not in b:
            return None
        j = self.devices.get(b["dev"])
        if j is None or b["eje"] >= j.get_numaxes():
            return None
        v = j.get_axis(b["eje"])
        if b.get("inv"):
            v = -v
        if abs(v) < deadzone:
            v = 0.0
        return v

    def button(self, key):
        """(estado, recién pulsado, recién soltado)"""
        b = self.bindings.get(key)
        if not b or "btn" not in b:
            return None, False, False
        j = self.devices.get(b["dev"])
        if j is None or b["btn"] >= j.get_numbuttons():
            return None, False, False
        now = bool(j.get_button(b["btn"]))
        prev = self.prev.get(key, now)
        self.prev[key] = now
        return now, now and not prev, prev and not now

    def has_axis(self, key):
        return self.axis(key) is not None

    # ------------------------------------------------------------ aplicar al avión
    def update(self, dt, world, app):
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
        # interruptores (se aplican al cambiar, para no pelear con lecciones ni teclado)
        sw = {"sw_bat": lambda on: setattr(s, "master", on), "sw_alt": lambda on: setattr(s, "alternator", on),
              "sw_avionica": lambda on: setattr(s, "avionics", on), "sw_bomba": lambda on: setattr(s, "fuel_pump", on),
              "sw_pitot": lambda on: setattr(s, "pitot_heat", on), "sw_tren": lambda on: setattr(s, "gear_down", on),
              "sw_freno_est": lambda on: setattr(s, "parking_brake", on)}
        for k, light in (("sw_beacon", "beacon"), ("sw_nav", "nav"), ("sw_strobe", "strobe"), ("sw_taxi", "taxi"),
                         ("sw_landing", "landing")):
            sw[k] = (lambda L: (lambda on: s.lights.__setitem__(L, on)))(light)
        for i, k in enumerate(("sw_motor1", "sw_motor2")):
            if i < len(engs):
                sw[k] = (lambda en: (lambda on: setattr(en, "magnetos", 3 if on else 0)))(engs[i])
        for k, fn in sw.items():
            st, pr, rl = self.button(k)
            if pr or rl:
                fn(bool(st))
        for k, val in (("mag_off", 0), ("mag_der", 1), ("mag_izq", 2), ("mag_ambos", 3)):
            st, pr, _ = self.button(k)
            if pr:
                engs[0].magnetos = val
        for k, val in (("comb_cerrado", 0), ("comb_izq", 1), ("comb_der", 2), ("comb_ambos", 3)):
            st, pr, _ = self.button(k)
            if pr:
                s.fuel_selector = val
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
        self.brake_cmd = max(fl or 0.0, fr or 0.0, 1.0 if st else 0.0)
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

    def flight_axes(self):
        """(alabeo, cabeceo, timón) de la cabina física, o None si no están asignados."""
        return self.axis("eje_alabeo"), self.axis("eje_cabeceo"), self.axis("eje_timon")
