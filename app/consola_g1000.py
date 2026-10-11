"""Teclas y perillas del G1000 de la consola física (C172S): piloto automático, perillas HDG / CRS / BARO, radios,
transpondedor y teclas del GPS. Cada función es un «pulsador» que se asigna en Cabina física a un botón del USB.

Las perillas giratorias (encoders) llegan al PC como un botón por cada sentido de giro y dan pulsos muy cortos;
app/hardware.py los lee como eventos para no perder ningún clic aunque se giren rápido.

Las radios se pueden asignar de dos formas: una perilla doble por radio (como en el avión) o una sola perilla doble
compartida con un selector que elige la radio. Todo esto pide la aviónica encendida, como en el avión.
"""
from sim.nav import step_adf, step_com, step_nav

RADIOS = ("com1", "nav1", "nav2", "adf")
RADIO_NAMES = {"com1": "COM 1", "nav1": "NAV 1", "nav2": "NAV 2", "adf": "ADF"}

# (clave, nombre que se ve en Cabina física)
FUNCTIONS = [
    ("g_ap", "G1000 · AP: conectar / desconectar"), ("g_fd", "G1000 · FD: director de vuelo"),
    ("g_hdg", "G1000 · AP: HDG"), ("g_nav", "G1000 · AP: NAV"), ("g_apr", "G1000 · AP: APR"),
    ("g_alt", "G1000 · AP: ALT"), ("g_vs", "G1000 · AP: VS"),
    ("g_nariz_arriba", "G1000 · AP: NOSE UP (VS +100)"), ("g_nariz_abajo", "G1000 · AP: NOSE DN (VS −100)"),
    ("g_alt_1000_mas", "G1000 · perilla ALT grande +1000"), ("g_alt_1000_menos", "G1000 · perilla ALT grande −1000"),
    ("g_alt_100_mas", "G1000 · perilla ALT pequeña +100"), ("g_alt_100_menos", "G1000 · perilla ALT pequeña −100"),
    ("g_hdg_mas", "G1000 · perilla HDG +"), ("g_hdg_menos", "G1000 · perilla HDG −"),
    ("g_hdg_sync", "G1000 · perilla HDG pulsada (al rumbo actual)"),
    ("g_crs_mas", "G1000 · perilla CRS +"), ("g_crs_menos", "G1000 · perilla CRS −"),
    ("g_crs2_mas", "G1000 · CRS NAV 2 +"), ("g_crs2_menos", "G1000 · CRS NAV 2 −"),
    ("g_baro_mas", "G1000 · perilla BARO +"), ("g_baro_menos", "G1000 · perilla BARO −"),
    ("g_baro_std", "G1000 · perilla BARO pulsada (STD 1013)"),
] + [(f"r_{r}_{p}", f"Radio {RADIO_NAMES[r]} · {t}") for r in RADIOS
     for p, t in (("mhz_mas", "perilla grande +"), ("mhz_menos", "perilla grande −"),
                  ("khz_mas", "perilla pequeña +"), ("khz_menos", "perilla pequeña −"), ("cambio", "cambio ⇄"))] + [
    ("r_sel", "Radios compartidas · selector (siguiente radio)"),
    ("r_grande_mas", "Radios compartidas · perilla grande +"), ("r_grande_menos", "Radios compartidas · perilla grande −"),
    ("r_peq_mas", "Radios compartidas · perilla pequeña +"), ("r_peq_menos", "Radios compartidas · perilla pequeña −"),
    ("r_cambio", "Radios compartidas · cambio ⇄"),
    ("x_digito", "Transpondedor · siguiente dígito"), ("x_mas", "Transpondedor · dígito +"),
    ("x_menos", "Transpondedor · dígito −"), ("x_ident", "Transpondedor · IDENT"),
    ("g_direct", "G1000 · tecla D→"), ("g_fpl", "G1000 · tecla FPL"), ("g_proc", "G1000 · tecla PROC (RNAV)"),
    ("g_clr", "G1000 · tecla CLR"), ("g_ent", "G1000 · tecla ENT"),
    ("g_fms_g_mas", "G1000 · perilla FMS grande +"), ("g_fms_g_menos", "G1000 · perilla FMS grande −"),
    ("g_fms_p_mas", "G1000 · perilla FMS pequeña +"), ("g_fms_p_menos", "G1000 · perilla FMS pequeña −"),
    ("g_fms_push", "G1000 · perilla FMS pulsada (siguiente letra)"),
    ("g_rango_mas", "G1000 · RANGE + (alejar el mapa)"), ("g_rango_menos", "G1000 · RANGE − (acercar el mapa)"),
    ("g_cdi", "G1000 · tecla CDI (GPS / VLOC)"), ("g_obs", "G1000 · tecla OBS"),
]
KEYS = [k for k, _ in FUNCTIONS]


class ConsolaG1000:
    def __init__(self):
        self.radio_sel = None          # radio elegida con el selector de las radios compartidas
        self.xpdr_digit = None         # dígito del transpondedor que se está cambiando (0-3)

    # ------------------------------------------------------------------ radios
    @staticmethod
    def _tune(world, radio, big=0, small=0):
        """Cambia la frecuencia de reserva (como en el avión: se sintoniza en espera y se pasa con ⇄)."""
        if radio == "com1":
            world.com_standby = step_com(world.com_standby, big, small)
            return f"COM 1 espera {world.com_standby:.3f}"
        if radio in ("nav1", "nav2"):
            nv = getattr(world, radio)
            nv.standby = step_nav(nv.standby, big, small)
            return f"{RADIO_NAMES[radio]} espera {nv.standby:.2f}"
        world.adf.standby = step_adf(world.adf.standby, big, small)
        world.show_adf = True
        return f"ADF espera {world.adf.standby:.0f}"

    @staticmethod
    def _swap(world, radio):
        if radio == "com1":
            world.com_freq, world.com_standby = world.com_standby, world.com_freq
            return f"COM 1 activa {world.com_freq:.3f}"
        if radio in ("nav1", "nav2"):
            nv = getattr(world, radio)
            nv.swap()
            return f"{RADIO_NAMES[radio]} activa {nv.freq:.2f}"
        world.adf.swap()
        world.show_adf = True
        return f"ADF activa {world.adf.freq:.0f}"

    # ------------------------------------------------------------------ una pulsación
    def press(self, key, world, app):
        """Ejecuta una pulsación (un clic de perilla o una tecla). Devuelve el mensaje que se muestra, o None."""
        ac = world.ac
        if not ac.sys.avionics_ok:
            return None                                  # sin aviónica no responde nada del G1000
        ap = world.ap
        glass = app.panel.glass
        msg = None
        # ---- piloto automático
        if key == "g_ap":
            ap.toggle(ac)
        elif key == "g_fd":
            if not ap.engaged:
                ap.fd = not ap.fd
        elif key == "g_hdg":
            ap.set_hdg(ac)
        elif key == "g_nav":
            ap.set_nav(ac, False)
        elif key == "g_apr":
            ap.set_nav(ac, True)
        elif key == "g_alt":
            ap.set_alt(ac)
        elif key == "g_vs":
            ap.set_vs(ac)
        elif key in ("g_nariz_arriba", "g_nariz_abajo"):
            ap.adjust_vs(100 if key == "g_nariz_arriba" else -100)
        elif key.startswith("g_alt_"):
            step = (1000 if "1000" in key else 100) * (1 if key.endswith("mas") else -1)
            ap.alt_sel = max(0, min(17500, round((ap.alt_sel + step) / 100) * 100))
            msg = f"Altitud seleccionada {ap.alt_sel:.0f} ft"
        # ---- perillas HDG, CRS y BARO
        elif key in ("g_hdg_mas", "g_hdg_menos"):
            ap.hdg_bug = (ap.hdg_bug + (1 if key == "g_hdg_mas" else -1)) % 360 or 360
        elif key == "g_hdg_sync":
            ap.hdg_bug = round(world.mag(ac.heading)) % 360 or 360
            msg = f"Rumbo seleccionado {ap.hdg_bug:03.0f}°"
        elif key in ("g_crs_mas", "g_crs_menos"):
            d = 1 if key == "g_crs_mas" else -1
            if world.cdi_src == "GPS":
                g = world.gps
                if g.obs_mode:
                    g.set_obs(True, g.obs_course + d)
            else:
                world.nav1.obs = (world.nav1.obs + d) % 360 or 360
        elif key in ("g_crs2_mas", "g_crs2_menos"):
            world.nav2.obs = (world.nav2.obs + (1 if key == "g_crs2_mas" else -1)) % 360 or 360
        elif key in ("g_baro_mas", "g_baro_menos"):
            world.kollsman = max(940, min(1060, round(world.kollsman) + (1 if key == "g_baro_mas" else -1)))
            msg = f"Altímetro {world.kollsman:.0f} hPa"
        elif key == "g_baro_std":
            world.kollsman = 1013.25
            msg = "Altímetro STD 1013"
        # ---- radios, una perilla por radio
        elif key.startswith("r_") and key.split("_")[1] in RADIOS:
            _, radio, part = key.split("_", 2)
            if part == "cambio":
                msg = self._swap(world, radio)
            else:
                d = 1 if part.endswith("mas") else -1
                msg = self._tune(world, radio, big=d if part.startswith("mhz") else 0,
                                 small=d if part.startswith("khz") else 0)
        # ---- radios compartidas: el selector elige, la perilla doble sintoniza
        elif key == "r_sel":
            i = RADIOS.index(self.radio_sel) + 1 if self.radio_sel in RADIOS else 0
            self.radio_sel = RADIOS[i % len(RADIOS)]
            msg = f"Perilla de radio: {RADIO_NAMES[self.radio_sel]}"
        elif key in ("r_grande_mas", "r_grande_menos", "r_peq_mas", "r_peq_menos", "r_cambio"):
            radio = self.radio_sel or "com1"
            self.radio_sel = radio
            if key == "r_cambio":
                msg = self._swap(world, radio)
            else:
                d = 1 if key.endswith("mas") else -1
                msg = self._tune(world, radio, big=d if "grande" in key else 0, small=d if "peq" in key else 0)
        # ---- transpondedor
        elif key == "x_digito":
            self.xpdr_digit = 0 if self.xpdr_digit is None else (self.xpdr_digit + 1) % 4
            msg = f"Transpondedor: dígito {self.xpdr_digit + 1}"
        elif key in ("x_mas", "x_menos"):
            i = 0 if self.xpdr_digit is None else self.xpdr_digit
            self.xpdr_digit = i
            digits = [int(c) for c in f"{world.xpdr:04d}"]
            digits[i] = (digits[i] + (1 if key == "x_mas" else -1)) % 8
            world.xpdr = int("".join(map(str, digits)))
            msg = f"Transpondedor {world.xpdr:04d}"
        elif key == "x_ident":
            world.xpdr_ident_t = world.sim_time
            msg = f"IDENT · transpondedor {world.xpdr:04d}"
        # ---- teclas y perillas del GPS
        elif key == "g_direct":
            glass.gps_open("dto")
        elif key == "g_fpl":
            glass.gps_open("fpl")
        elif key == "g_proc":
            glass.gps_open("apr")
        elif key == "g_clr":
            glass.gps_clr(world)
        elif key == "g_ent":
            glass.gps_enter(world)
        elif key in ("g_fms_g_mas", "g_fms_g_menos"):
            glass.gps_fms(world, big=1 if key.endswith("mas") else -1)
        elif key in ("g_fms_p_mas", "g_fms_p_menos"):
            glass.gps_fms(world, small=1 if key.endswith("mas") else -1)
        elif key == "g_fms_push":
            glass.gps_fms(world, push=True)
        elif key in ("g_rango_mas", "g_rango_menos"):
            glass.map_range_step(1 if key == "g_rango_mas" else -1)
        elif key == "g_cdi":
            world.cdi_src = "GPS" if world.cdi_src == "VLOC" else "VLOC"
            msg = f"CDI {world.cdi_src}"
        elif key == "g_obs":
            g = world.gps
            g.set_obs(not g.obs_mode, g.dtk if g.valid else None)
        # para que la barra superior del PFD resalte lo que se está cambiando
        world.radio_sel = self.radio_sel
        world.xpdr_digit = self.xpdr_digit
        return msg
