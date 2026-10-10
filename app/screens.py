"""Pantallas: menú principal, lecciones, vuelo libre, bitácora, ajustes, pausa,
estación del instructor, análisis posterior y superposiciones de ayuda/listas."""
import math
import os
import time

import numpy as np
import pygame

from sim.aircraft_data import AIRCRAFT
from sim.lessons import LESSONS, FreeFlight
from sim.mathx import FT, KT, NM, clamp
from sim.world import POSITIONS
from ui.ui import COL, panel_box

WEATHER_PRESETS = [
    ("Despejado", dict(wind_dir=360, wind_kt=5, gust_kt=0, turbulence=0.0, cloud_cover=0.08, cloud_base_ft=5500,
                       cloud_top_ft=7000, visibility_m=40000)),
    ("Nubes dispersas", dict(wind_dir=20, wind_kt=8, gust_kt=0, turbulence=0.12, cloud_cover=0.38, cloud_base_ft=4500,
                             cloud_top_ft=6200, visibility_m=30000)),
    ("Cubierto (IFR)", dict(wind_dir=340, wind_kt=10, gust_kt=4, turbulence=0.25, cloud_cover=0.97, cloud_base_ft=1500,
                            cloud_top_ft=4200, visibility_m=4000)),
    ("Viento cruzado", dict(wind_dir=270, wind_kt=15, gust_kt=7, turbulence=0.35, cloud_cover=0.3, cloud_base_ft=5000,
                            cloud_top_ft=6500, visibility_m=25000)),
    ("Turbulento", dict(wind_dir=300, wind_kt=18, gust_kt=10, turbulence=0.75, cloud_cover=0.6, cloud_base_ft=3500,
                        cloud_top_ft=6500, visibility_m=15000)),
    ("Niebla", dict(wind_dir=0, wind_kt=0, gust_kt=0, turbulence=0.0, cloud_cover=0.95, cloud_base_ft=900,
                    cloud_top_ft=1600, visibility_m=900)),
    ("Lluvia", dict(wind_dir=320, wind_kt=10, gust_kt=6, turbulence=0.3, cloud_cover=0.96, cloud_base_ft=1800,
                    cloud_top_ft=9000, visibility_m=12000, rain=0.7)),
    ("Tormenta", dict(wind_dir=300, wind_kt=8, gust_kt=6, turbulence=0.3, cloud_cover=0.55, cloud_base_ft=2500,
                      cloud_top_ft=7000, visibility_m=20000, storm=True)),
]


def apply_weather_preset(world, preset):
    """Aplica un preajuste de meteorología. La tormenta se coloca a 8 km del aeródromo y avanza hacia él."""
    w = world.weather
    w.rain, w.storm = 0.0, False
    for k, v in preset.items():
        setattr(w, k, v)
    if w.storm:
        import math
        import random
        a = math.radians(random.uniform(0, 360))
        ref = world.home.ref
        w.storm_r = 2500.0
        w.storm_n, w.storm_e = ref[0] + math.cos(a) * 8000, ref[1] + math.sin(a) * 8000
        w.storm_vn, w.storm_ve = -math.cos(a) * 3.0, -math.sin(a) * 3.0
HOURS = [("Amanecer", 6.6), ("Mañana", 9.5), ("Mediodía", 12.5), ("Atardecer", 18.0), ("Noche", 21.5)]

KEYS = [
    ("Vuelo", [
        ("↑ / ↓", "Cabeceo: nariz abajo / nariz arriba"),
        ("← / →", "Alabeo izquierda / derecha"),
        ("A / D", "Pedales: timón y rueda de morro"),
        ("W / S", "Gases + / − (Shift: rápido)"),
        ("Q / E", "Compensador nariz arriba / abajo"),
        ("F / V", "Flaps abajo / arriba"),
        ("Espacio", "Frenos (mantener)"),
        ("B", "Freno de estacionamiento"),
        ("M / N", "Mezcla rica / pobre"),
        ("U / J", "Hélice (Arrow) + / −"),
        ("G", "Tren de aterrizaje (Arrow)"),
        ("L", "Luz de aterrizaje"),
        ("Ctrl+E", "Arranque automático del motor"),
        ("Insert", "Motor de arranque (mantener)"),
        ("F6", "Calefacción al carburador (C152, PA-28 Warrior)"),
    ]),
    ("Piloto automático y cabina", [
        ("Z", "Conectar / desconectar PA"),
        ("X", "Modo rumbo (HDG)"),
        ("C", "Mantener altitud (ALT)"),
        (", / .", "Marcador de rumbo −5° / +5°"),
        ("Tab", "Cabina clásica / G1000"),
        ("P", "Cabina 3D · foto · panel 2D · sin panel"),
        ("1 2 3 4", "Cabina · exterior · torre · libre"),
        ("5", "Vista de instrumentos (cabina 3D)"),
        ("Y", "Mostrar / ocultar el volante"),
        ("Ctrl+flechas", "Mirar alrededor (o botón derecho)"),
        ("Rueda", "Zoom / ajustar mandos del panel"),
        ("K", "Lista de verificación"),
        ("T", "Radio: hablar con la torre (1–9 elige)"),
        ("Ctrl der.", "Hablar a la torre por micrófono"),
        ("F2", "Pantalla de instrumentos (cabina física)"),
        ("R", "Repetición instantánea"),
        ("I", "Estación del instructor"),
        ("Ctrl+R", "Reiniciar la lección"),
        ("F12", "Captura de pantalla"),
    ]),
]


def standard_checklist(world):
    ac = world.ac
    s = ac.sys
    e = s.engine
    if ac.on_ground and not e.running:
        return "Antes del arranque", [
            ("Freno de estacionamiento", "PUESTO", s.parking_brake),
            ("Interruptor maestro", "ENCENDIDO", s.master),
            ("Luz anticolisión", "ENCENDIDA", s.lights["beacon"]),
            ("Selector de combustible", "AMBOS", s.fuel_selector == 3),
            ("Mezcla", "RICA", e.mixture > 0.9),
            ("Gases", "ABIERTOS 1/4", 0.08 < e.throttle < 0.4),
            ("Magnetos", "AMBOS", e.magnetos == 3),
            ("Arranque", "ACCIONAR", e.running),
        ]
    if ac.on_ground:
        return "Antes del despegue", [
            ("Aviónica", "ENCENDIDA", s.avionics),
            ("Altímetro", "AJUSTADO (QNH)", abs(world.kollsman - world.weather.qnh_hpa) < 1),
            ("Compensador", "DESPEGUE", -0.1 < ac.trim < 0.5),
            ("Flaps", "0° - 10°", s.flaps <= 10.5),
            ("Mezcla", "RICA", e.mixture > 0.9),
            ("Presión de aceite", "EN VERDE", 50 <= e.oil_press <= 95 or e.rpm < 1200),
            ("Luces", "ATERRIZAJE Y STROBE", s.lights["landing"] and s.lights["strobe"]),
            ("Freno de estacionamiento", "QUITADO", not s.parking_brake),
        ]
    near = min(math.hypot(ac.pos[0] - a.ref[0], ac.pos[1] - a.ref[1]) for a in world.airports) < 9000
    if near and ac.vs_fpm < -100 or ac.agl / FT < 1500:
        return "Antes del aterrizaje", [
            ("Altímetro", "QNH", abs(world.kollsman - world.weather.qnh_hpa) < 1),
            ("Mezcla", "RICA", e.mixture > 0.9),
            ("Combustible", "AMBOS", s.fuel_selector == 3),
            ("Luz de aterrizaje", "ENCENDIDA", s.lights["landing"]),
            ("Tren", "ABAJO, 3 VERDES", s.gear_pos > 0.99),
            ("Flaps", "SEGÚN NECESIDAD", True),
            ("Piloto automático", "DESCONECTADO", not world.ap.engaged),
        ]
    return "Crucero", [
        ("Potencia", "2200-2600 RPM", 2100 <= e.rpm <= 2650),
        ("Mezcla", "EMPOBRECIDA", e.mixture < 0.97 or ac.alt_msl < 900),
        ("Compensador", "AJUSTADO", True),
        ("Flaps", "ARRIBA", s.flaps < 1),
        ("Instrumentos de motor", "EN VERDE", 100 < e.oil_temp < 245 and e.oil_press > 45),
        ("Direccional", "ALINEADO CON BRÚJULA", abs(((world.ind.dg - world.ind.compass) + 180) % 360 - 180) < 5),
    ]


class ScreensMixin:
    # ================================================================ menú
    def _menu_button(self, rect, label, active=False, sub=None):
        """Botón del menú principal: placa de cristal con barra de neón a la izquierda."""
        from ui import theme
        ui = self.ui
        s = self.overlay
        rect = pygame.Rect(rect)
        hov = ui.hover(rect)
        pts = theme.chamfer(rect, 12, "tb")
        fill = (0, 92, 128, 235) if active else ((0, 56, 80, 230) if hov else (4, 18, 30, 228))
        pygame.draw.polygon(s, fill, pts)
        pygame.draw.polygon(s, (*theme.CYAN, 255 if (hov or active) else 85), pts, 1)
        bar = pygame.Rect(rect.x + 1, rect.y + 12, 4 if (active or hov) else 2, rect.h - 24)
        pygame.draw.rect(s, theme.CYAN if (active or hov) else theme.CYAN_DIM, bar)
        if active or hov:
            theme.glow(s, rect, theme.CYAN, 2, 12)
            # flecha de selección
            cx = rect.right - 22
            pygame.draw.polygon(s, theme.CYAN, [(cx, rect.centery - 6), (cx + 7, rect.centery), (cx, rect.centery + 6)])
        theme.spaced(self.fonts, s, label.upper(), (rect.x + 20, rect.centery - (9 if sub else 0)), 15,
                     theme.TEXT if (hov or active) else (205, 230, 242), 0.10, anchor="midleft")
        if sub:
            self.fonts.blit(s, sub, (rect.x + 20, rect.centery + 12), 12, theme.TEXT_DIM if not active else (170, 225, 245),
                            anchor="midleft")
        hit = ui.hit(rect)
        if hit and ui.on_click:
            ui.on_click()
        return hit

    def _hud_header(self):
        """Barra de estado superior del menú: sistema, hora, lugar y coordenadas; radar con los aeródromos vecinos."""
        from ui import theme
        import datetime
        s = self.overlay
        f = self.fonts
        W, H = self.W, self.H
        t = getattr(self, "menu_t", 0.0)
        bar = pygame.Rect(0, 0, W, 30)
        pygame.draw.rect(s, (2, 10, 18, 200), bar)
        pygame.draw.line(s, (*theme.CYAN, 120), (0, bar.bottom), (W, bar.bottom))
        w = self.world
        loc = w.location
        now = datetime.datetime.now()
        utc = datetime.datetime.now(datetime.timezone.utc)
        dot = theme.GREEN if theme.blink(1.2) else (20, 90, 60)
        pygame.draw.circle(s, dot, (16, 15), 4)
        theme.spaced(f, s, "SISTEMA LISTO", (28, 15), 11, theme.GREEN, 0.2, anchor="midleft")
        info = []
        if loc is not None:
            la, lo = loc["lat0"], loc["lon0"]
            info.append(f"{w.home.ident}  {abs(la):.4f}°{'N' if la >= 0 else 'S'}  {abs(lo):.4f}°{'O' if lo < 0 else 'E'}"
                        f"  ELEV {w.home.elev / 0.3048:.0f} FT")
            fq = w.freqs
            info.append("TWR " + f"{fq.get('TWR', 0):.3f}".rstrip("0").rstrip(".") + ("  GND " + f"{fq['GND']:.3f}".rstrip("0").rstrip(".")
                                                                                      if "GND" in fq else ""))
        else:
            info.append("ESCENARIO ESCUELA · ESC")
        info.append(f"{now:%H:%M:%S} LOCAL   {utc:%H:%M}Z")
        x = W - 16
        for txt in reversed(info):
            r = f.blit(s, txt, (x, 15), 12, (150, 215, 238), tech=True, anchor="midright")
            x = r.x - 28
            pygame.draw.line(s, (*theme.CYAN, 90), (x + 14, 8), (x + 14, 22))
        # radar con los aeródromos del escenario
        rr = int(min(W, H) * 0.075)
        c = (W - rr - 30, H - rr - 46)
        blips = []
        far = max(1.0, max((math.hypot(*(a.ref[:2] - w.home.ref[:2])) for a in w.airports), default=1.0))
        for a in w.airports[:8]:
            d = a.ref[:2] - w.home.ref[:2]
            ang = math.degrees(math.atan2(d[1], d[0]))
            blips.append((ang, 0.0 if a is w.home else 0.25 + 0.7 * math.hypot(*d) / far, a.ident))
        theme.radar(s, f, c, rr, t, blips)
        theme.spaced(f, s, "AERÓDROMOS", (c[0], c[1] + rr + 10), 10, theme.TEXT_DIM, 0.25, anchor="midtop")

    def screen_menu(self, events):
        self._events = events
        s = self.overlay
        f = self.fonts
        W, H = self.W, self.H
        for ev in events:
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                if self.menu_page != "main":
                    self.menu_page = "main"
                else:
                    self.running = False
        from ui import theme
        theme.hud_backdrop(s, W, H, getattr(self, "menu_t", 0.0), int(W * 0.34))
        self._hud_header()
        # el título cabe en la columna de los botones (Orbitron es ancha)
        colw = int(min(330, W * 0.26))
        tsz = 30
        while tsz > 18 and f.get(tsz, True, tech=True).size("AEROESCUELA")[0] * 1.12 > colw:
            tsz -= 1
        rt = theme.glow_title(f, s, "AEROESCUELA", (40, 50), tsz)
        pygame.draw.line(s, theme.CYAN, (42, rt.bottom + 8), (42 + colw * 0.78, rt.bottom + 8), 2)
        pygame.draw.line(s, (*theme.CYAN, 80), (42 + colw * 0.78, rt.bottom + 8), (42 + colw, rt.bottom + 8), 2)
        ssz = 10
        theme.spaced(f, s, "SIMULADOR DE ENTRENAMIENTO DE VUELO", (42, rt.bottom + 18), ssz, theme.TEXT_DIM, 0.10)
        y = 150
        bw = min(330, W * 0.26)
        nxt = next((c for c in LESSONS if not self.progress.lesson(c.id)["passed"]), None)
        place = self.world.place_name
        items = [("location", "Ubicación", place if len(place) < 38 else place[:36] + "…"),
                 ("lessons", "Programa de lecciones", f"{sum(1 for c in LESSONS if self.progress.lesson(c.id)['passed'])}/{len(LESSONS)} superadas"),
                 ("free", "Vuelo libre", "Elija avión, lugar, clima y hora"),
                 ("logbook", "Progreso y bitácora", f"{self.progress.data['total_s'] / 3600:.1f} h de vuelo"),
                 ("settings", "Ajustes", "Sonido, voz, joystick, pantalla"),
                 ("hardware", "Cabina física", "Asignar volante, palancas e interruptores"),
                 ("help", "Controles", "Teclado, ratón y joystick")]
        for key, lab, sub in items:
            if self._menu_button((40, y, bw, 58), lab, self.menu_page == key, sub):
                self.menu_page = key
            y += 64
        if self._menu_button((40, y + 6, bw, 46), "Salir"):
            self.running = False
        content = pygame.Rect(40 + bw + 30, 40, W - (40 + bw + 30) - 40, H - 80)
        page = self.menu_page
        if page == "main":
            self.page_main(content, nxt)
        elif page == "lessons":
            self.page_lessons(content)
        elif page == "free":
            self.page_free(content)
        elif page == "logbook":
            self.page_logbook(content)
        elif page == "settings":
            self.page_settings(content)
        elif page == "help":
            self.page_help(content)
        elif page == "hardware":
            self.page_hardware(content)
        elif page == "location":
            self.page_location(content, events)

    def page_main(self, r, nxt):
        s = self.overlay
        f = self.fonts
        if not hasattr(self, "globe"):
            from ui.globe import Globe
            self.globe = Globe(self.geo_db)
        loc = self.world.location
        if loc is not None:
            self.globe.set_target(loc["lat0"], loc["lon0"], f"{self.world.home.ident} · {(loc.get('municipality') or loc['name'])[:22].upper()}")
        else:
            self.globe.set_target(40.0, -4.0, "ESC · ESCENARIO ESCUELA")
        gr = int(max(80, min(r.h * 0.27, (self.W * 0.58 - r.x) / 2 - 40, (r.h - 300) / 2, 220)))
        self.globe.draw(s, f, (r.x + 50 + gr, r.y + 24 + gr), gr)
        from ui import theme
        box = pygame.Rect(r.x, r.bottom - 250, min(r.w, 760), 250)
        panel_box(s, box, 14, (4, 14, 24, 215))
        theme.spaced(f, s, "BIENVENIDO A BORDO", (box.x + 24, box.y + 20), 20, theme.TEXT, 0.12)
        pygame.draw.line(s, (*theme.CYAN, 140), (box.x + 24, box.y + 50), (box.x + 200, box.y + 50), 1)
        txt = ("Aprenda a volar paso a paso con un instructor virtual que le habla, evalúa cada maniobra y guarda su "
               "progreso. Modelo de vuelo de 6 grados de libertad, cabina clásica o de cristal G1000, radioayudas VOR/ILS, "
               "piloto automático, meteorología y fallas configurables desde la estación del instructor.")
        y = box.y + 60
        for ln in f.wrap(txt, 16, box.w - 48):
            f.blit(s, ln, (box.x + 24, y), 16, (210, 220, 230))
            y += 22
        bx = box.x + 24
        if nxt is not None:
            lab = f"Siguiente lección: {nxt.title}"
            bw = f.get(15, True).size(lab)[0] + 40
            if self.ui.button(s, (bx, box.bottom - 62, bw, 44), lab, size=15, color=(40, 110, 200)):
                self.selected_lesson = LESSONS.index(nxt)
                self.menu_page = "lessons"
            bx += bw + 16
        if self.ui.button(s, (bx, box.bottom - 62, 200, 44), "Vuelo libre rápido", size=15):
            self.launch_free()

    POPULAR = [("SKBO", "Bogotá"), ("MMMX", "Ciudad de México"), ("SCEL", "Santiago"), ("SAEZ", "Buenos Aires"),
               ("SPJC", "Lima"), ("SEQM", "Quito"), ("MDSD", "Santo Domingo"), ("TJSJ", "San Juan"),
               ("LEMD", "Madrid"), ("LEBL", "Barcelona"), ("KMIA", "Miami"), ("KLAX", "Los Ángeles"),
               ("KJFK", "Nueva York"), ("EGLL", "Londres"), ("LFPG", "París"), ("RJTT", "Tokio")]

    def page_location(self, r, events):
        s = self.overlay
        f = self.fonts
        ui = self.ui
        box = pygame.Rect(r.x, r.y, min(r.w, 1040), r.h)
        panel_box(s, box, 14, (10, 16, 26, 225))
        x0 = box.x + 26
        y = box.y + 20
        f.blit(s, "Ubicación de entrenamiento", (x0, y), 28, COL["white"], bold=True)
        y += 44
        f.blit(s, "Vuele en cualquier aeropuerto del mundo con relieve real, fotografía satelital y sus pistas reales.",
               (x0, y), 15, (200, 210, 222))
        y += 22
        f.blit(s, "La primera vez se descargan unos 25 MB de datos (≈1 min); después queda guardado y carga al instante.",
               (x0, y), 13, COL["grey"])
        y += 34
        f.blit(s, f"Actual: {self.world.place_name}", (x0, y), 16, COL["green"], bold=True)
        y += 34
        # caja de búsqueda
        pygame.key.start_text_input()
        changed = False
        for ev in events:
            if ev.type == pygame.TEXTINPUT and len(self.loc_query) < 40:
                self.loc_query += ev.text
                changed = True
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_BACKSPACE:
                    self.loc_query = self.loc_query[:-1]
                    changed = True
                elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and self.loc_results:
                    self.load_location(self.loc_results[0]["ident"])
        sb = pygame.Rect(x0, y, box.w - 52 - 220, 44)
        pygame.draw.rect(s, (6, 10, 16), sb, border_radius=8)
        pygame.draw.rect(s, COL["accent"], sb, 2, border_radius=8)
        caret = "|" if int(time.time() * 2) % 2 == 0 else " "
        txt = self.loc_query + caret if self.loc_query else "Escriba código OACI/IATA, ciudad o nombre (p. ej. SKBO, MEX, Barajas)…"
        f.blit(s, txt, (sb.x + 14, sb.centery), 17, COL["white"] if self.loc_query else COL["dim"], anchor="midleft")
        if ui.button(s, (sb.right + 12, y, 208, 44), "Escenario escuela", size=15, active=self.world.is_school):
            if not self.world.is_school:
                self.load_location(None)
        y += 58
        if changed:
            try:
                if self.geo_db.airports is None:
                    self._loading("Descargando la base mundial de aeropuertos…", 0.1)
                    self.geo_db.ensure(lambda m, fr: self._loading(m, fr))
                self.loc_results = self.geo_db.search(self.loc_query, 9) if len(self.loc_query) >= 2 else []
            except Exception as ex:
                self.flash("Sin conexión para descargar la base de aeropuertos: " + str(ex), 5)
        busy = self.loc_job is not None
        if self.loc_results:
            for a in self.loc_results:
                rr = pygame.Rect(x0, y, box.w - 52, 40)
                hov = ui.hover(rr)
                pygame.draw.rect(s, (40, 60, 90, 220) if hov else (22, 30, 44, 200), rr, border_radius=8)
                kind = {"large_airport": "Grande", "medium_airport": "Mediano", "small_airport": "Pequeño"}.get(a["type"], "")
                f.blit(s, a["ident"], (rr.x + 14, rr.centery), 17, COL["yellow"], bold=True, mono=True, anchor="midleft")
                f.blit(s, a["name"][:58], (rr.x + 110, rr.centery), 15, COL["white"], anchor="midleft")
                f.blit(s, f"{a.get('municipality') or ''} · {a.get('iso_country', '')} · {kind}", (rr.right - 14, rr.centery), 13,
                       COL["grey"], anchor="midright")
                if ui.hit(rr) and not busy:
                    self.load_location(a["ident"])
                y += 46
        else:
            f.blit(s, "Aeropuertos populares", (x0, y), 15, COL["accent"], bold=True)
            y += 28
            cols = 4
            bw = (box.w - 52 - (cols - 1) * 10) / cols
            for i, (code, city) in enumerate(self.POPULAR):
                rr = (x0 + (i % cols) * (bw + 10), y + (i // cols) * 46, bw, 40)
                if ui.button(s, rr, f"{code} · {city}", size=14, enabled=not busy):
                    self.load_location(code)
        f.blit(s, "Nota: las frecuencias ILS de aeropuertos reales son sintéticas (la base pública no las incluye); "
                  "los VOR y las pistas son reales.", (x0, box.bottom - 30), 12, COL["grey"])

    def draw_loc_progress(self):
        job = self.loc_job
        s = self.overlay
        f = self.fonts
        box = pygame.Rect(0, 0, 640, 110)
        box.midbottom = (self.W / 2, self.H - 40)
        panel_box(s, box, 12, (8, 14, 24, 240))
        f.blit(s, f"Cargando {job['code']}…", (box.x + 20, box.y + 14), 18, COL["white"], bold=True)
        f.blit(s, job["msg"], (box.x + 20, box.y + 44), 13, COL["grey"])
        bar = pygame.Rect(box.x + 20, box.bottom - 26, box.w - 40, 10)
        pygame.draw.rect(s, (40, 46, 56), bar, border_radius=5)
        pygame.draw.rect(s, COL["accent"], (bar.x, bar.y, bar.w * min(1.0, job["frac"]), bar.h), border_radius=5)

    def page_lessons(self, r):
        s = self.overlay
        f = self.fonts
        ui = self.ui
        lw = min(430, r.w * 0.42)
        lst = pygame.Rect(r.x, r.y, lw, r.h)
        panel_box(s, lst, 14, (10, 16, 26, 215))
        # lista desplazable con la rueda del ratón
        rowh = 34
        ncat = len({C.category for C in LESSONS})
        content = len(LESSONS) * rowh + ncat * 22 + 28
        maxs = max(0, content - lst.h)
        if not hasattr(self, "lesson_scroll"):
            self.lesson_scroll = 0
        d = ui.scroll(lst)
        if d:
            self.lesson_scroll -= d * 60
        self.lesson_scroll = int(clamp(self.lesson_scroll, 0, maxs))
        clip0 = s.get_clip()
        s.set_clip(lst.inflate(-4, -8))
        y = lst.y + 14 - self.lesson_scroll
        cat = None
        for i, C in enumerate(LESSONS):
            if C.category != cat:
                cat = C.category
                f.blit(s, cat.upper(), (lst.x + 16, y + 4), 12, (120, 160, 210), bold=True)
                y += 22
            row = pygame.Rect(lst.x + 8, y, lst.w - 16, rowh - 4)
            if row.bottom < lst.y or row.y > lst.bottom:
                y += rowh
                continue
            sel = i == self.selected_lesson
            hov = ui.hover(row)
            if sel or hov:
                pygame.draw.rect(s, (40, 90, 160, 200) if sel else (40, 50, 64, 180), row, border_radius=7)
            P = self.progress.lesson(C.id)
            f.blit(s, C.title, (row.x + 10, row.centery), 15, COL["white"], bold=sel, anchor="midleft")
            if P["best"] is not None:
                col = COL["green"] if P["passed"] else COL["amber"]
                f.blit(s, f"{P['best']:.0f}", (row.right - 10, row.centery), 15, col, bold=True, anchor="midright")
            if lst.collidepoint(ui.clicked or (-1, -1)) and ui.hit(row):
                self.selected_lesson = i
            y += rowh
        s.set_clip(clip0)
        if maxs:
            bar_h = lst.h * lst.h / content
            by = lst.y + (lst.h - bar_h) * self.lesson_scroll / maxs
            pygame.draw.rect(s, (90, 110, 140), (lst.right - 6, by, 4, bar_h), border_radius=2)
        C = LESSONS[self.selected_lesson]
        det = pygame.Rect(lst.right + 20, r.y, r.right - lst.right - 20, r.h)
        panel_box(s, det, 14, (10, 16, 26, 220))
        from ui import assets
        ph = assets.image(f"avion_{C.aircraft}.png")
        if ph is not None:
            pw = min(260, det.w * 0.34)
            phh = pw * ph.get_height() / ph.get_width()
            img = assets.scaled(f"avion_{C.aircraft}.png", (pw, phh))
            s.blit(img, (det.right - pw - 20, det.bottom - phh - 90))     # abajo, para no tapar el texto
        x0 = det.x + 26
        y = det.y + 20
        f.blit(s, f"{C.category}   ·   Tarea ACS {C.acs}", (x0, y), 13, (120, 160, 210), bold=True)
        y += 22
        f.blit(s, C.title, (x0, y), 28, COL["white"], bold=True)
        y += 44
        acn = AIRCRAFT[C.aircraft]().name
        where = ("Escenario escuela" if C.school_only else
                 ({"SVBS": "Base Aérea Mariscal Sucre (SVBS), Maracay", "SVFM": "La Carlota (SVFM), Caracas", "SVMI": "Maiquetía (SVMI)", "SVVA": "Valencia (SVVA)", "SVBM": "Barquisimeto (SVBM)", "SVMD": "Mérida (SVMD)", "SVMG": "Margarita (SVMG)"}.get(getattr(C, "location", None)) or self.world.place_name))
        f.blit(s, f"Duración aprox.: {C.duration}   ·   Avión: {acn}   ·   Lugar: {where}", (x0, y), 14, COL["grey"])
        y += 20
        f.blit(s, f"Estándar de evaluación: {C.standard} (equivalente EASA). Aprobado ≥ 70.", (x0, y), 13, (150, 170, 190))
        y += 30
        for ln in f.wrap(C.brief, 16, det.w - 52):
            f.blit(s, ln, (x0, y), 16, (215, 222, 230))
            y += 23
        y += 14
        f.blit(s, "Objetivos", (x0, y), 17, COL["accent"], bold=True)
        y += 26
        for o in C.objectives:
            f.blit(s, "•  " + o, (x0 + 6, y), 15, COL["white"])
            y += 22
        P = self.progress.lesson(C.id)
        y += 10
        if P["attempts"]:
            f.blit(s, f"Intentos: {P['attempts']}   Mejor nota: {P['best'] if P['best'] is not None else '—'}   "
                      f"{'SUPERADA' if P['passed'] else 'pendiente'}", (x0, y), 14,
                   COL["green"] if P["passed"] else COL["grey"])
        if ui.button(s, (det.right - 250, det.bottom - 70, 220, 50), "Comenzar lección", size=18, color=(30, 120, 70)):
            self.start_lesson(C)

    def launch_free(self):
        cfg = self.free_cfg
        name, preset = WEATHER_PRESETS[cfg["clima"]]
        w = self.world.weather
        apply_weather_preset(self.world, preset)
        w.hour = HOURS[cfg["hora"]][1]
        w.qnh_hpa = 1013.0
        if self.world.aircraft_id != cfg["avion"]:
            self.world.set_aircraft(cfg["avion"])
        self.start_lesson(FreeFlight(cfg["pos"]))

    def _choice_row(self, x, y, w, options, current, size=14, h=36):
        n = len(options)
        bw = (w - (n - 1) * 8) / n
        sel = None
        for i, lab in enumerate(options):
            if self.ui.button(self.overlay, (x + i * (bw + 8), y, bw, h), lab, active=i == current, size=size):
                sel = i
        return sel

    def _aircraft_cards(self, x0, y, w, cfg):
        """Tarjetas de avión con foto (assets/avion_<id>.png si existe), nombre y tipo."""
        from ui import assets
        s = self.overlay
        f = self.fonts
        ids = list(AIRCRAFT.keys())
        n = len(ids)
        per_row = 4 if n > 5 else n
        rows = (n + per_row - 1) // per_row
        cw = (w - (per_row - 1) * 10) / per_row
        ch = 92 if rows > 1 else 118
        for i, aid in enumerate(ids):
            t = AIRCRAFT[aid]()
            r = pygame.Rect(x0 + (i % per_row) * (cw + 10), y + (i // per_row) * (ch + 8), cw, ch)
            sel = cfg["avion"] == aid
            hov = self.ui.hover(r)
            pygame.draw.rect(s, (36, 96, 170, 235) if sel else ((40, 50, 64, 220) if hov else (24, 30, 40, 220)), r, border_radius=10)
            pygame.draw.rect(s, (120, 170, 230) if sel else (60, 70, 86), r, 2 if sel else 1, border_radius=10)
            img = assets.image(f"avion_{aid}.png")
            tx = r.x + 12
            if img is not None:
                ih = ch - 16
                iw = int(img.get_width() * ih / img.get_height())
                iw = min(iw, int(cw * 0.45))
                th = assets.scaled(f"avion_{aid}.png", (iw, ih))
                s.blit(th, (r.x + 8, r.y + 8))
                tx = r.x + iw + 18
            f.blit(s, t.short, (tx, r.y + 10), 18, COL["white"], bold=True)
            yy = r.y + 36
            for ln in f.wrap(t.category, 12, r.right - tx - 8)[:3]:
                f.blit(s, ln, (tx, yy), 12, (200, 212, 225))
                yy += 16
            if self.ui.hit(r):
                cfg["avion"] = aid
                if t.default_cockpit == "glass":
                    self.panel.mode = "glass"
        return y + rows * (ch + 8) + 10

    def page_free(self, r):
        s = self.overlay
        f = self.fonts
        cfg = self.free_cfg
        box = pygame.Rect(r.x, r.y, min(r.w, 980), r.h)
        panel_box(s, box, 14, (10, 16, 26, 220))
        x0 = box.x + 26
        w = box.w - 52
        y = box.y + 20
        f.blit(s, "Vuelo libre", (x0, y), 28, COL["white"], bold=True)
        y += 50
        f.blit(s, "Avión", (x0, y), 16, COL["accent"], bold=True)
        y += 24
        y = self._aircraft_cards(x0, y, w, cfg)
        f.blit(s, "Posición inicial", (x0, y), 16, COL["accent"], bold=True)
        y += 24
        keys = list(POSITIONS.keys())
        cols = 3
        bw = (w - (cols - 1) * 8) / cols
        for i, k in enumerate(keys):
            rr = (x0 + (i % cols) * (bw + 8), y + (i // cols) * 40, bw, 34)
            if self.ui.button(s, rr, POSITIONS[k], active=cfg.get("pos") == k, size=13):
                cfg["pos"] = k
        y += ((len(keys) + cols - 1) // cols) * 40 + 14
        f.blit(s, "Meteorología", (x0, y), 16, COL["accent"], bold=True)
        y += 24
        cols = 4
        bw = (w - (cols - 1) * 8) / cols
        for i, (n, _pr) in enumerate(WEATHER_PRESETS):
            rr = (x0 + (i % cols) * (bw + 8), y + (i // cols) * 40, bw, 34)
            if self.ui.button(s, rr, n, active=cfg["clima"] == i, size=13):
                cfg["clima"] = i
        y += ((len(WEATHER_PRESETS) + cols - 1) // cols) * 40 + 10
        f.blit(s, "Hora del día", (x0, y), 16, COL["accent"], bold=True)
        y += 24
        sel = self._choice_row(x0, y, w * 0.8, [n for n, _ in HOURS], cfg["hora"], 13)
        if sel is not None:
            cfg["hora"] = sel
        y += 50
        f.blit(s, "Cabina", (x0, y), 16, COL["accent"], bold=True)
        y += 24
        sel = self._choice_row(x0, y, w * 0.5, ["Clásica (analógica)", "Cristal (G1000)"], 0 if self.panel.mode == "analog" else 1)
        if sel is not None:
            self.panel.mode = "analog" if sel == 0 else "glass"
            self.settings["cabina"] = self.panel.mode
        if self.ui.button(s, (box.right - 230, box.bottom - 68, 200, 48), "¡Volar!", size=20, color=(30, 120, 70)):
            self.launch_free()

    def page_logbook(self, r):
        s = self.overlay
        f = self.fonts
        d = self.progress.data
        box = pygame.Rect(r.x, r.y, min(r.w, 1080), r.h)
        panel_box(s, box, 14, (10, 16, 26, 220))
        x0 = box.x + 26
        y = box.y + 20
        f.blit(s, f"Progreso de: {self.student}", (x0, y), 28, COL["white"], bold=True)
        # alumnos
        bx = box.right - 26
        if self.ui.button(s, (bx - 200, y, 200, 34), "Ficha del alumno (PDF)", size=13,
                          tip="Abre la ficha imprimible en el navegador (Ctrl+P → Guardar como PDF)"):
            self.make_student_report()
        if self.ui.button(s, (bx - 350, y, 140, 34), "Nuevo alumno", size=13):
            self.new_student = ""
        names = self.students.names()
        if self.ui.button(s, (bx - 520, y, 160, 34), "Cambiar alumno ▾", size=13, active=getattr(self, "_stu_open", False)):
            self._stu_open = not getattr(self, "_stu_open", False)
        y += 50
        if self.new_student is not None:
            pygame.key.start_text_input()
            for ev in self._events:
                if ev.type == pygame.TEXTINPUT and len(self.new_student) < 40:
                    self.new_student += ev.text
                elif ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_BACKSPACE:
                        self.new_student = self.new_student[:-1]
                    elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        n = self.students.create(self.new_student)
                        self.new_student = None
                        if n:
                            self.select_student(n)
            if self.new_student is not None:
                tb = pygame.Rect(x0, y - 6, 520, 38)
                pygame.draw.rect(s, (20, 28, 40), tb, border_radius=6)
                pygame.draw.rect(s, COL["accent"], tb, 2, border_radius=6)
                caret = "|" if int(time.time() * 2) % 2 == 0 else " "
                f.blit(s, "Nombre del alumno: " + self.new_student + caret + "   (Intro para crear)", (tb.x + 12, tb.centery),
                       15, COL["white"], anchor="midleft")
                y += 46
        if getattr(self, "_stu_open", False):
            for i, n in enumerate(names):
                r_ = pygame.Rect(bx - 520, y - 8 + i * 34, 300, 32)
                if self.ui.button(s, r_, n, active=n == self.student, size=13):
                    self.select_student(n)
                    self._stu_open = False
            return
        passed = sum(1 for c in LESSONS if self.progress.lesson(c.id)["passed"])
        stats = [("Horas de vuelo", f"{d['total_s'] / 3600:.1f}"), ("Aterrizajes", str(d["landings"])),
                 ("Lecciones superadas", f"{passed}/{len(LESSONS)}"), ("Vuelos registrados", str(len(d["logbook"])))]
        cw = (box.w - 52) / 4
        for i, (lab, val) in enumerate(stats):
            c = pygame.Rect(x0 + i * cw, y, cw - 12, 70)
            panel_box(s, c, 10, (22, 30, 44, 230))
            f.blit(s, val, (c.centerx, c.y + 10), 28, COL["white"], bold=True, anchor="midtop")
            f.blit(s, lab, (c.centerx, c.bottom - 8), 12, COL["grey"], anchor="midbottom")
        y += 92
        # progreso por lección
        bar_w = (box.w - 52)
        n = len(LESSONS)
        sw = bar_w / n
        for i, C in enumerate(LESSONS):
            P = self.progress.lesson(C.id)
            col = (40, 170, 80) if P["passed"] else ((200, 150, 40) if P["attempts"] else (50, 56, 66))
            pygame.draw.rect(s, col, (x0 + i * sw, y, sw - 4, 10), border_radius=4)
        y += 26
        f.blit(s, "Bitácora (libro de vuelo)", (x0, y), 17, COL["accent"], bold=True)
        y += 28
        cols = [("Fecha", 0.17), ("Lección", 0.36), ("Avión", 0.1), ("Min", 0.08), ("Aterr.", 0.08), ("Nota", 0.08), ("Resultado", 0.13)]
        x = x0
        for name, frac in cols:
            f.blit(s, name, (x, y), 13, COL["grey"], bold=True)
            x += frac * (box.w - 52)
        y += 22
        rows = d["logbook"][: int((box.bottom - y - 20) / 22)]
        if not rows:
            f.blit(s, "Todavía no hay vuelos registrados.", (x0, y + 10), 15, COL["grey"])
        for e in rows:
            x = x0
            vals = [e["fecha"], e["leccion"], e["avion"], f"{e['duracion_min']:.1f}", str(e["aterrizajes"]),
                    "—" if e["nota"] is None else f"{e['nota']:.0f}", e["resultado"]]
            for (name, frac), v in zip(cols, vals):
                f.blit(s, v, (x, y), 14, COL["white"])
                x += frac * (box.w - 52)
            y += 22

    def page_hardware(self, r):
        """Asignación de mandos de la cabina física (ejes, interruptores y pulsadores)."""
        from .hardware import FUNCTIONS, KIND
        s = self.overlay
        f = self.fonts
        ui = self.ui
        hw = self.hardware
        box = pygame.Rect(r.x, r.y, min(r.w, 1100), r.h)
        panel_box(s, box, 14, (10, 16, 26, 225))
        x0 = box.x + 22
        f.blit(s, "Cabina física", (x0, box.y + 16), 26, COL["white"], bold=True)
        # pestañas: asignar mandos · diagnóstico
        if not hasattr(self, "hw_tab"):
            self.hw_tab = "asignar"
        for i, (k, lab) in enumerate((("asignar", "Asignar mandos"), ("sens", "Sensibilidad"), ("diag", "Diagnóstico y prueba"))):
            if ui.button(s, (x0 + 230 + i * 190, box.y + 16, 180, 32), lab, active=self.hw_tab == k, size=13):
                self.hw_tab = k
        if self.hw_tab == "diag":
            self.page_hw_diag(box)
            return
        if self.hw_tab == "sens":
            self.page_hw_sens(box)
            return
        devs = hw.device_list()
        txt = " · ".join(f"{n} ({a} ejes, {b} botones)" for _, n, a, b in devs) or "No hay dispositivos USB conectados"
        f.blit(s, "Dispositivos: " + txt, (x0, box.y + 54), 13, COL["green"] if devs else COL["amber"])
        if ui.button(s, (box.right - 150, box.y + 16, 128, 32), "Buscar", size=13):
            hw.refresh()
        if ui.button(s, (box.right - 300, box.y + 50, 140, 28), "Exportar", size=12,
                     tip="Guarda las asignaciones en un archivo para copiarlas a otra computadora con la misma cabina"):
            self.flash("Asignaciones guardadas en " + hw.export_profile(), 6)
        if ui.button(s, (box.right - 150, box.y + 50, 128, 28), "Importar", size=12,
                     tip="Carga las asignaciones del archivo cabina_fisica.json de la carpeta de datos"):
            n = hw.import_profile()
            self.flash(f"Importadas {n} asignaciones" if n else "No hay archivo cabina_fisica.json en la carpeta de datos", 5)
            self.save_settings()
        if hw.twin_groups() and ui.button(s, (box.right - 640, box.y + 50, 160, 28), "Intercambiar iguales", size=12,
                                          tip="Si dos mandos del mismo modelo quedaron cruzados, pasa las asignaciones "
                                              "de uno al otro (luego vuelva a calibrar)"):
            names = hw.swap_twins()
            self.flash("Asignaciones intercambiadas entre: " + ", ".join(names) + ". Vuelva a calibrar sus ejes.", 6)
            self.save_settings()
        calibrating = hw.calib is not None
        if ui.button(s, (box.right - 470, box.y + 50, 160, 28), "Terminar calibración" if calibrating else "Calibrar ejes",
                     active=calibrating, size=12,
                     tip="Mide el recorrido real de cada eje asignado (tope a tope) y su centro"):
            if calibrating:
                n = hw.finish_calibration()
                self.flash(f"Calibrados {n} ejes" if n else "Ningún eje se movió lo suficiente: no se cambió nada", 5)
                self.save_settings()
            else:
                hw.start_calibration()
        if hw.calib is not None:
            hw.poll_calibration()
            f.blit(s, "Calibrando: mueva cada eje asignado de tope a tope; suelte volante, pedales y compensador en el "
                      "centro y pulse «Terminar calibración».", (x0, box.y + 76), 15, COL["yellow"], bold=True)
        if hw.capture:
            msg = f"Asignando «{dict((k, n) for k, n, _ in FUNCTIONS)[hw.capture]}»: " + (
                "MUEVA el eje a fondo" if KIND[hw.capture] == "eje" else "ACCIONE el interruptor o botón")
            f.blit(s, msg + "   (Esc o clic para cancelar)", (x0, box.y + 76), 15, COL["yellow"], bold=True)
            if ui.clicked:
                hw.capture = None
                ui.clicked = None
        # lista desplazable en dos columnas
        top = box.y + 104
        rowh = 30
        colw = (box.w - 44) / 2
        per_col = max(1, int((box.bottom - top - 16) / rowh))
        if not hasattr(self, "hw_scroll"):
            self.hw_scroll = 0
        d = ui.scroll(box)
        if d:
            self.hw_scroll = max(0, self.hw_scroll - d * 2)
        items = FUNCTIONS[self.hw_scroll * 2:]
        kind_txt = {"eje": "EJE", "interruptor": "INT", "pulsador": "PULS", "mantener": "MANT"}
        for i, (key, name, kind) in enumerate(items[:per_col * 2]):
            col, row = i // per_col, i % per_col
            x = x0 + col * colw
            y = top + row * rowh
            rr = pygame.Rect(x - 6, y - 3, colw - 10, rowh - 2)
            if row % 2 == 0:
                pygame.draw.rect(s, (18, 24, 34), rr, border_radius=4)
            f.blit(s, kind_txt[kind], (x, y + 4), 10, (120, 160, 210), bold=True)
            f.blit(s, name, (x + 40, y + 2), 13, COL["white"])
            desc = hw.describe(key)
            live = ""
            if kind == "eje":
                v = hw.axis(key, 0.0)
                live = "" if v is None else f"  {v:+.2f}"
            else:
                b = hw.bindings.get(key)
                st_ = hw.raw_state(b) if b else None
                if st_ is not None:
                    live = "  ●" if st_ else "  ○"
            f.blit(s, desc + live, (x + colw * 0.45, y + 3), 12, COL["green"] if desc != "—" else COL["dim"])
            bx = x + colw - 128
            if ui.button(s, (bx, y - 1, 64, 24), "Asignar", active=hw.capture == key, size=11):
                hw.start_capture(key)
            if kind == "eje" and hw.bindings.get(key):
                if ui.button(s, (bx + 68, y - 1, 26, 24), "⇅", size=12, tip="Invertir el eje"):
                    hw.invert(key)
            if hw.bindings.get(key) and ui.button(s, (bx + 98, y - 1, 24, 24), "×", size=12, tip="Quitar"):
                hw.clear(key)
        f.blit(s, "INT = interruptor con posición fija · PULS = pulsador · MANT = activo mientras se mantiene. "
                  "Rueda del ratón: más funciones. Se guarda al salir.", (x0, box.bottom - 22), 12, COL["grey"])
        hw.update(0.0, self.world, self) if hw.capture else None

    def page_hw_sens(self, box):
        """Zona muerta y curva de cada eje de vuelo, con la curva dibujada y la posición real del mando encima."""
        from ui import theme
        from .hardware import DEFAULT_DZ, DEFAULT_EXPO, NAMES, SHAPED, shape
        s = self.overlay
        f = self.fonts
        ui = self.ui
        hw = self.hardware
        x0 = box.x + 22
        y = box.y + 66
        f.blit(s, "Zona muerta: cuánto se mueve el mando sin efecto en el centro. Curva: 0 % = lineal; más alta = más "
                  "suave cerca del centro y la misma autoridad al final del recorrido.", (x0, y), 13, COL["grey"])
        y += 30
        rowh = max(150, int((box.bottom - y - 40) / len(SHAPED)))
        for key in SHAPED:
            b = hw.bindings.get(key)
            f.blit(s, NAMES[key], (x0, y + 4), 16, COL["white"], bold=True)
            f.blit(s, hw.describe(key), (x0, y + 28), 12, COL["green"] if b else COL["dim"])
            plot = pygame.Rect(box.right - 22 - 130, y, 130, 130)
            if not b or "eje" not in b:
                f.blit(s, "Sin asignar: asígnelo en «Asignar mandos».", (x0, y + 56), 13, COL["amber"])
                y += rowh
                continue
            dz, k = b.get("zm", DEFAULT_DZ), b.get("exp", DEFAULT_EXPO)
            v = ui.slider(s, (x0 + 300, y, 300, 30), dz * 100, 0, 25, "Zona muerta", "{:.0f} %")
            if v is not None:
                b["zm"] = round(v / 100, 3)
            v = ui.slider(s, (x0 + 300, y + 44, 300, 30), k * 100, 0, 100, "Curva", "{:.0f} %")
            if v is not None:
                b["exp"] = round(v / 100, 2)
            if ui.button(s, (x0 + 300, y + 88, 140, 28), "Restablecer", size=12,
                         tip=f"Zona muerta {DEFAULT_DZ * 100:.0f} % y curva {DEFAULT_EXPO * 100:.0f} %"):
                b.pop("zm", None)
                b.pop("exp", None)
            # curva: entrada (horizontal) → salida (vertical), con la posición actual
            pygame.draw.rect(s, (8, 22, 34), plot)
            pygame.draw.rect(s, (*theme.CYAN, 110), plot, 1)
            pygame.draw.line(s, (40, 70, 90), plot.midleft, plot.midright)
            pygame.draw.line(s, (40, 70, 90), plot.midtop, plot.midbottom)
            pygame.draw.line(s, (60, 80, 100), plot.bottomleft, plot.topright)
            dz, k = b.get("zm", DEFAULT_DZ), b.get("exp", DEFAULT_EXPO)
            pts = [(plot.x + (i / 40) * plot.w, plot.centery - shape(i / 20 - 1, dz, k) * plot.h / 2) for i in range(41)]
            pygame.draw.lines(s, theme.CYAN, False, pts, 2)
            raw = hw.axis(key, 0.0)
            if raw is not None:
                out = hw.shaped(key)
                pygame.draw.circle(s, theme.AMBER, (int(plot.centerx + raw * plot.w / 2), int(plot.centery - out * plot.h / 2)), 5)
                f.blit(s, f"mando {raw:+.2f} → avión {out:+.2f}", (x0 + 460, y + 94), 13, COL["white"])
            f.blit(s, "ENTRADA → SALIDA", (plot.centerx, plot.bottom + 4), 10, COL["grey"], anchor="midtop")
            y += rowh
        f.blit(s, "Se guarda al salir. Las palancas (gases, mezcla, hélice, frenos) son lineales: use «Calibrar ejes».",
               (x0, box.bottom - 22), 12, COL["grey"])

    def page_hw_diag(self, box):
        """Diagnóstico de la cabina física: dispositivos en bruto, prueba de mandos, micrófono, monitores y lista."""
        from ui import theme
        from .hardware import FUNCTIONS, KIND
        s = self.overlay
        f = self.fonts
        ui = self.ui
        hw = self.hardware
        x0 = box.x + 22
        y = box.y + 62
        devs = hw.device_list()
        if ui.button(s, (box.right - 150, box.y + 16, 128, 32), "Buscar", size=13):
            hw.refresh()
        # ---------- 1. dispositivos USB en bruto
        theme.spaced(f, s, "1 · DISPOSITIVOS USB (VALORES EN BRUTO)", (x0, y), 12, theme.CYAN, 0.08)
        y += 24
        if not devs:
            f.blit(s, "No se detecta ningún mando USB. Conéctelo, espere unos segundos y pulse «Buscar».", (x0, y), 14, COL["amber"])
            y += 26
        for g, name, na, nb in devs[:4]:
            j = hw.devices[g]
            f.blit(s, f"{name}", (x0, y), 13, COL["white"], bold=True)
            bx = x0 + 240
            for a in range(min(na, 8)):
                v = j.get_axis(a)
                r_ = pygame.Rect(bx + a * 62, y + 2, 56, 12)
                pygame.draw.rect(s, (20, 34, 46), r_)
                cx = r_.centerx + v * r_.w / 2
                pygame.draw.rect(s, theme.CYAN, (min(cx, r_.centerx), r_.y, abs(cx - r_.centerx) + 1, r_.h))
                f.blit(s, f"E{a}", (r_.x, r_.bottom + 1), 9, COL["grey"])
            lx = bx + 8 * 62 + 10
            for b in range(min(nb, 32)):
                on = j.get_button(b)
                c = (lx + (b % 16) * 14, y + 4 + (b // 16) * 14)
                pygame.draw.circle(s, theme.GREEN if on else (30, 50, 60), c, 5)
            if j.get_numhats():
                hx, hy = j.get_hat(0)
                f.blit(s, f"seta {hx:+d},{hy:+d}", (lx + 16 * 14 + 8, y), 11, COL["grey"])
            y += 38
        # ---------- 2. prueba de mandos de vuelo
        y += 6
        theme.spaced(f, s, "2 · PRUEBA DE MANDOS (CON LAS ASIGNACIONES)", (x0, y), 12, theme.CYAN, 0.08)
        y += 26
        sq = pygame.Rect(x0, y, 150, 150)
        pygame.draw.rect(s, (8, 22, 34), sq)
        pygame.draw.rect(s, (*theme.CYAN, 120), sq, 1)
        pygame.draw.line(s, (40, 70, 90), sq.midleft, sq.midright)
        pygame.draw.line(s, (40, 70, 90), sq.midtop, sq.midbottom)
        roll = hw.axis("eje_alabeo", 0.0)
        pitch = hw.axis("eje_cabeceo", 0.0)
        if roll is not None or pitch is not None:
            px = sq.centerx + (roll or 0) * sq.w / 2
            py = sq.centery + (pitch or 0) * sq.h / 2
            pygame.draw.circle(s, theme.AMBER, (int(px), int(py)), 8, 2)
        f.blit(s, "VOLANTE", (sq.centerx, sq.bottom + 4), 11, COL["grey"], anchor="midtop")
        bars = [("eje_timon", "Timón", True), ("eje_freno_izq", "Freno izq.", False), ("eje_freno_der", "Freno der.", False),
                ("eje_gases", "Gases", False), ("eje_mezcla", "Mezcla", False), ("eje_helice", "Hélice", False),
                ("eje_flaps", "Flaps", False), ("eje_trim", "Compensador", True)]
        bx = sq.right + 30
        for i, (k, lab, center) in enumerate(bars):
            v = hw.axis(k, 0.0)
            r_ = pygame.Rect(bx + i * 74, y, 22, 150)
            pygame.draw.rect(s, (8, 22, 34), r_)
            pygame.draw.rect(s, (*theme.CYAN, 110), r_, 1)
            if v is not None:
                if center:
                    yy = r_.centery - v * r_.h / 2
                    pygame.draw.rect(s, theme.CYAN, (r_.x + 2, min(yy, r_.centery), r_.w - 4, abs(yy - r_.centery) + 1))
                else:
                    k01 = (1 - v) / 2 if k.startswith("eje_freno") is False else (v + 1) / 2
                    hgt = r_.h * max(0.0, min(1.0, k01))
                    pygame.draw.rect(s, theme.CYAN, (r_.x + 2, r_.bottom - hgt, r_.w - 4, hgt))
            else:
                f.blit(s, "—", r_.center, 12, COL["dim"], anchor="center")
            f.blit(s, lab, (r_.centerx, r_.bottom + 4), 10, COL["grey"], anchor="midtop")
        # interruptores asignados
        ix = bx + len(bars) * 74 + 10
        iy = y
        sw = [(k, n) for k, n, kind in FUNCTIONS if kind != "eje" and hw.bindings.get(k)]
        f.blit(s, f"Interruptores y botones asignados: {len(sw)}", (ix, iy), 12, COL["white"], bold=True)
        iy += 20
        for k, n in sw[:9]:
            st, _, _ = hw.button(k)
            pygame.draw.circle(s, theme.GREEN if st else (30, 50, 60), (ix + 6, iy + 7), 5)
            f.blit(s, n[:34], (ix + 16, iy), 11, COL["white"])
            iy += 16
        y += 180
        # ---------- 3. micrófono y monitores
        theme.spaced(f, s, "3 · MICRÓFONO Y MONITORES", (x0, y), 12, theme.CYAN, 0.08)
        y += 26
        vi = self.voice_in
        if ui.button(s, (x0, y, 230, 34), "ESCUCHANDO…" if vi.listening else "Probar micrófono", active=vi.listening, size=13,
                     tip="Pulse y diga «prueba de micrófono»"):
            vi.listen([("prueba de micrófono", "", None), ("probando", "", None), ("uno dos tres", "", None)], "", "")
        r = vi.poll()
        if r is not None:
            self._mic_res = ("✓ Entendido: «" + r[1] + "»") if r[0] is not None else ("✗ " + r[1])
        f.blit(s, getattr(self, "_mic_res", "Pulse y diga «prueba de micrófono»."), (x0 + 244, y + 9), 13,
               COL["green"] if getattr(self, "_mic_res", "").startswith("✓") else COL["grey"])
        y += 44
        mons = pygame.display.get_desktop_sizes()
        st = self.settings
        mtxt = "  ·  ".join(f"Monitor {i + 1}: {w_}×{h_}" for i, (w_, h_) in enumerate(mons))
        f.blit(s, mtxt, (x0, y), 13, COL["white"])
        y += 20
        f.blit(s, f"Pantalla de instrumentos: {self.INSTR_NAMES.get(st.get('pantalla_instr', 'no'), '')}  ·  Paisaje en "
                  f"{st.get('monitores_paisaje', 1)} monitor(es)  ·  Vistas: {st.get('vistas', 1)}", (x0, y), 12, COL["grey"])
        y += 30
        # ---------- 4. lista de conexión
        theme.spaced(f, s, "4 · LISTA DE CONEXIÓN", (x0, y), 12, theme.CYAN, 0.08)
        y += 24
        ax_ok = all(hw.bindings.get(k) for k in ("eje_alabeo", "eje_cabeceo", "eje_timon", "eje_gases"))
        checks = [
            ("Mando USB detectado", bool(devs)),
            ("Volante (alabeo y cabeceo), pedales y gases asignados", ax_ok),
            ("Frenos de pie asignados", bool(hw.bindings.get("eje_freno_izq") or hw.bindings.get("btn_frenos"))),
            ("Interruptores básicos (batería, alternador, aviónica, magnetos)",
             all(hw.bindings.get(k) for k in ("sw_bat", "sw_alt", "sw_avionica")) and
             any(hw.bindings.get(k) for k in ("mag_ambos", "mag_off"))),
            ("Botón de hablar por micrófono (PTT) asignado", bool(hw.bindings.get("btn_ptt_voz"))),
            ("Micrófono probado", getattr(self, "_mic_res", "").startswith("✓")),
            ("Pantalla en «Paisaje + instr.» o «2.º monitor»", st.get("pantalla_instr") in ("ambiente", "segunda", "unica")),
            ("Ejes calibrados", any(b.get("cal") for b in hw.bindings.values())),
            ("Interruptores reales iguales que en el avión", not hw.mismatch),
        ]
        for i, (lab, ok) in enumerate(checks):
            cx = x0 + (i % 2) * 480
            cy = y + (i // 2) * 22
            f.blit(s, "✓" if ok else "○", (cx, cy), 14, theme.GREEN if ok else COL["amber"], bold=True)
            f.blit(s, lab, (cx + 22, cy + 1), 13, COL["white"] if ok else COL["grey"])

    def page_settings(self, r):
        s = self.overlay
        f = self.fonts
        st = self.settings
        box = pygame.Rect(r.x, r.y, min(r.w, 900), r.h)
        panel_box(s, box, 14, (10, 16, 26, 220))
        x0 = box.x + 26
        y = box.y + 20
        f.blit(s, "Ajustes", (x0, y), 28, COL["white"], bold=True)
        y += 56
        f.blit(s, "Volumen", (x0, y + 8), 16, COL["white"])
        v = self.ui.slider(s, (x0 + 220, y, 300, 30), st["volumen"] * 100, 0, 100, "", "{:.0f} %")
        if v is not None:
            st["volumen"] = v / 100
            self.audio.set_volume(st["volumen"])
        y += 46

        def toggle(label, key, extra=None):
            nonlocal y
            f.blit(s, label, (x0, y + 8), 16, COL["white"])
            if self.ui.button(s, (x0 + 220, y, 140, 32), "Activado" if st[key] else "Desactivado", active=st[key], size=14):
                st[key] = not st[key]
                if extra:
                    extra()
                self.save_settings()
            y += 44
        toggle("Voz del instructor", "voz", lambda: setattr(self.voice, "enabled", st["voz"]))
        if not self.voice.available:
            f.blit(s, "(síntesis de voz no disponible en este equipo)", (x0 + 380, y - 36), 13, COL["amber"])
        elif self.ui.button(s, (x0 + 380, y - 44, 140, 32), "Probar voz", size=14):
            self.voice.say("Torre Escuela, autorizado a despegar pista tres seis, viento tres seis cero, cinco nudos.", key="test", min_gap=0)
        toggle("Tráfico aéreo", "trafico", self.configure_world)
        if self.ui.button(s, (x0 + 380, y - 44, 260, 32),
                          "Paisaje: " + ("satelital + edificios 3D" if st.get("edificios_3d") else "foto satelital real"),
                          active=not st.get("edificios_3d"), size=13,
                          tip="Foto satelital real (como desde el avión) o con edificios 3D de OpenStreetMap. "
                              "Se aplica al cargar el lugar."):
            st["edificios_3d"] = not st.get("edificios_3d")
            self.save_settings()
        toggle("Control aéreo (torre por voz)", "atc", self.configure_world)
        if self.ui.button(s, (x0 + 380, y - 44, 200, 32), "ATC externo: " + ("Sí" if st.get("atc_externo") else "No"),
                          active=bool(st.get("atc_externo")), size=13,
                          tip="Deja este simulador listo para conectarse con un simulador de tránsito aéreo (puerto 8770)"):
            st["atc_externo"] = not st.get("atc_externo")
            self.apply_atc_link()
            self.save_settings()
        if self.atc_bridge is not None:
            txt = self.atc_bridge.status_text()
            col = COL["green"] if self.atc_bridge.link.connected else COL["grey"]
            for i, ln in enumerate(f.wrap(txt, 12, box.right - (x0 + 590) - 12)[:2]):
                f.blit(s, ln, (x0 + 590, y - 42 + i * 15), 12, col, bold=True)
        toggle("Timón automático (ayuda)", "timon_auto", lambda: setattr(self.controls, "assist_rudder", st["timon_auto"]))
        if self.ui.button(s, (x0 + 380, y - 44, 200, 32), "Salida UDP: " + ("Sí" if st.get("udp_salida") else "No"),
                          active=bool(st.get("udp_salida")), size=13,
                          tip="Envía los datos de vuelo por la red (instrumentos externos, paneles, movimiento). "
                              "Formato en docs/PROTOCOLO_UDP.md"):
            st["udp_salida"] = not st.get("udp_salida")
            self.apply_udp()
            self.save_settings()
        if self.udp is not None:
            f.blit(s, self.udp.status_text(), (x0 + 590, y - 36), 12,
                   COL["green"] if self.udp.error is None else COL["amber"], bold=True)
        toggle("Mostrar FPS", "mostrar_fps")
        fondo = st.get("fondo_instr", "futurista")
        if self.ui.button(s, (x0 + 380, y - 44, 300, 32),
                          "Fondo de instrumentos: " + ("Futurista" if fondo == "futurista" else "Negro (cabina física)"),
                          active=fondo == "futurista", size=13,
                          tip="Negro si delante de la pantalla hay un tablero físico con los huecos de los instrumentos"):
            st["fondo_instr"] = "negro" if fondo == "futurista" else "futurista"
            self.instr_display.bg_style = st["fondo_instr"]
            self.save_settings()
        toggle("Pantalla completa*", "pantalla_completa")
        f.blit(s, "Calidad gráfica", (x0, y + 8), 16, COL["white"])
        for i, (key, lab) in enumerate((("auto", "Automática"), ("alta", "Alta"), ("media", "Media"), ("rendimiento", "Rendimiento"))):
            if self.ui.button(s, (x0 + 220 + i * 128, y, 120, 32), lab, active=st.get("calidad", "auto") == key, size=13):
                st["calidad"] = key
                self.apply_quality()
                self.save_settings()
        y += 44
        f.blit(s, "Fluidez (FPS)", (x0, y + 8), 16, COL["white"])
        for i, (key, lab) in enumerate((("auto", "Automática"), ("60", "60 FPS"), ("30", "30 estables"))):
            if self.ui.button(s, (x0 + 220 + i * 128, y, 120, 32), lab, active=st.get("fluidez", "auto") == key, size=13):
                st["fluidez"] = key
                self.save_settings()
        y += 44
        f.blit(s, "Pantalla de instrumentos", (x0, y + 8), 16, COL["white"])
        for i, (key, lab) in enumerate((("no", "Normal"), ("ambiente", "Paisaje + instr."), ("unica", "Solo instrumentos"),
                                        ("segunda", "2.º monitor"))):
            if self.ui.button(s, (x0 + 220 + i * 150, y, 144, 32), lab, active=st.get("pantalla_instr", "no") == key, size=13,
                              tip="Para cabinas físicas: muestra solo los instrumentos, sin mandos (F2 en vuelo)"):
                st["pantalla_instr"] = key
                self.apply_instrument_screen()
                self.save_settings()
        y += 44
        f.blit(s, "Instructor en red", (x0, y + 8), 16, COL["white"])
        if self.ui.button(s, (x0 + 220, y, 140, 32), "Activado" if st.get("instructor_red") else "Desactivado",
                          active=bool(st.get("instructor_red")), size=14,
                          tip="Controlar el simulador desde el navegador de otra computadora, tableta o móvil de la misma red"):
            st["instructor_red"] = not st.get("instructor_red")
            self.apply_remote()
            self.save_settings()
        if self.remote is not None:
            f.blit(s, f"{self.remote.url}   ·   código {self.remote.code}" + ("   ● conectado" if self.remote.connected else ""),
                   (x0 + 380, y + 8), 16, COL["green"], bold=True)
        y += 44
        f.blit(s, "Vista exterior", (x0, y + 8), 16, COL["white"])
        for i, (n, lab) in enumerate(((1, "1 vista"), (3, "3 vistas (panorámica)"))):
            if self.ui.button(s, (x0 + 220 + i * 190, y, 182, 32), lab, active=int(st.get("vistas", 1)) == n, size=13,
                              tip="Izquierda · frente · derecha (sin cabina dibujada: Paisaje + instr. o 2.º monitor)"):
                st["vistas"] = n
                self.save_settings()
        nmon = len(pygame.display.get_desktop_sizes())
        for i, n in enumerate(range(1, max(2, nmon + 1))):
            if self.ui.button(s, (x0 + 610 + i * 70, y, 64, 32), f"{n} mon.", active=int(st.get("monitores_paisaje", 1)) == n,
                              size=12, tip="Monitores que ocupa la vista exterior (se aplica al reiniciar)"):
                st["monitores_paisaje"] = n
                self.save_settings()
        y += 44
        f.blit(s, "Resolución*", (x0, y + 8), 16, COL["white"])
        opts = [(0, 0, "Automática"), (1280, 720, "1280×720"), (1600, 900, "1600×900"), (1920, 1080, "1920×1080")]
        for i, (w_, h_, lab) in enumerate(opts):
            act = (st.get("ancho", 0), st.get("alto", 0)) == (w_, h_)
            if self.ui.button(s, (x0 + 220 + i * 128, y, 120, 32), lab, active=act, size=13):
                st["ancho"], st["alto"] = w_, h_
                self.save_settings()
        y += 44
        f.blit(s, "* Se aplica al reiniciar el programa.", (x0, y), 13, COL["grey"])
        y += 34
        f.blit(s, "Joystick / volante de vuelo", (x0, y), 17, COL["accent"], bold=True)
        y += 28
        c = self.controls
        if c.joy is None:
            f.blit(s, "No se detecta ningún joystick. Conéctelo y pulse «Buscar».", (x0, y), 15, COL["grey"])
        else:
            f.blit(s, f"Detectado: {c.joy_name}  ({c.joy.get_numaxes()} ejes, {c.joy.get_numbuttons()} botones)", (x0, y), 15, COL["green"])
        if self.ui.button(s, (box.right - 170, y - 6, 140, 32), "Buscar", size=14):
            c.refresh_joystick()
        y += 32
        if c.joy is not None and self.hardware.uses_device(c.joy):
            f.blit(s, "Este mando está asignado en «Cabina física»: se configura allí y aquí se ignora.", (x0, y), 14,
                   COL["amber"])
            y += 28
        if c.joy is not None:
            for key, lab in (("eje_alabeo", "Eje alabeo"), ("eje_cabeceo", "Eje cabeceo"), ("eje_timon", "Eje timón"),
                             ("eje_potencia", "Eje gases")):
                f.blit(s, lab, (x0, y + 6), 15, COL["white"])
                val = c.cfg[key]
                if self.ui.button(s, (x0 + 220, y, 36, 30), "−", size=16):
                    c.cfg[key] = max(-1, val - 1)
                f.blit(s, "ninguno" if val < 0 else str(val), (x0 + 300, y + 15), 15, COL["white"], bold=True, anchor="center")
                if self.ui.button(s, (x0 + 344, y, 36, 30), "+", size=16):
                    c.cfg[key] = min(c.joy.get_numaxes() - 1, val + 1)
                if 0 <= val < c.joy.get_numaxes():
                    a = c.joy.get_axis(val)
                    bar = pygame.Rect(x0 + 400, y + 10, 220, 10)
                    pygame.draw.rect(s, (30, 34, 40), bar, border_radius=4)
                    pygame.draw.rect(s, COL["accent"], (bar.centerx, bar.y, a * bar.w / 2, bar.h) if a >= 0 else
                                     (bar.centerx + a * bar.w / 2, bar.y, -a * bar.w / 2, bar.h), border_radius=4)
                y += 38
            for key, lab in (("invertir_cabeceo", "Invertir cabeceo"), ("invertir_potencia", "Invertir gases")):
                f.blit(s, lab, (x0, y + 6), 15, COL["white"])
                if self.ui.button(s, (x0 + 220, y, 120, 30), "Sí" if c.cfg[key] else "No", active=c.cfg[key], size=14):
                    c.cfg[key] = not c.cfg[key]
                y += 38
            for key, lab, step, lo, hi in (("zona_muerta", "Zona muerta", 0.02, 0.0, 0.3),
                                           ("exponencial", "Curva (expo)", 0.05, 0.0, 1.0)):
                f.blit(s, lab, (x0, y + 6), 15, COL["white"])
                val = float(c.cfg[key])
                if self.ui.button(s, (x0 + 220, y, 36, 30), "−", size=16):
                    c.cfg[key] = round(max(lo, val - step), 2)
                f.blit(s, f"{val * 100:.0f} %", (x0 + 300, y + 15), 15, COL["white"], bold=True, anchor="center")
                if self.ui.button(s, (x0 + 344, y, 36, 30), "+", size=16):
                    c.cfg[key] = round(min(hi, val + step), 2)
                y += 38
            st["joystick"] = c.cfg

    def page_help(self, r):
        s = self.overlay
        f = self.fonts
        box = pygame.Rect(r.x, r.y, min(r.w, 1000), r.h)
        panel_box(s, box, 14, (10, 16, 26, 220))
        self._keys_columns(box)

    def _keys_columns(self, box):
        s = self.overlay
        f = self.fonts
        colw = (box.w - 60) / 2
        for ci, (title, rows) in enumerate(KEYS):
            x = box.x + 26 + ci * (colw + 10)
            y = box.y + 22
            f.blit(s, title, (x, y), 19, COL["accent"], bold=True)
            y += 34
            for k, d in rows:
                kr = f.blit(s, k, (x, y), 15, COL["yellow"], bold=True, mono=True)
                f.blit(s, d, (x + 150, y), 15, COL["white"])
                y += 25
        f.blit(s, "Joystick: ejes de alabeo/cabeceo/timón/gases, botón 1 frenos, botón 2 desconecta el PA, seta = compensador.",
               (box.x + 26, box.bottom - 30), 13, COL["grey"])

    # ================================================================ superposiciones de vuelo
    def draw_help_overlay(self):
        box = pygame.Rect(0, 0, min(self.W - 60, 1000), min(self.H - 80, 520))
        box.center = (self.W / 2, self.H / 2 - 40)
        panel_box(self.overlay, box, 14, (8, 12, 20, 235))
        self._keys_columns(box)

    def draw_radio_subtitle(self):
        """Subtítulo de la transmisión que suena ahora (con el panel de radio cerrado)."""
        rn = self.radio_now
        if rn is None or time.time() > rn[1]:
            return
        msg = rn[0]
        s = self.overlay
        f = self.fonts
        who = {"yo": "Usted", "atc": {"GND": "Rodadura", "ATIS": "ATIS"}.get(msg.station, "Torre"), "ia": "Tráfico", "atis": "ATIS"}[msg.who]
        col = {"yo": (140, 220, 255), "atc": (255, 220, 120), "ia": (200, 200, 200), "atis": (180, 230, 180)}[msg.who]
        maxw = int(self.W * 0.5)
        lines = f.wrap(msg.disp, 16, maxw)[:3]
        bw = max(f.get(16).size(t)[0] for t in lines) + 30
        box = pygame.Rect(0, 0, max(bw, 200), 30 + 22 * len(lines))
        box.midtop = (self.W / 2, int(self.H * 0.2))
        panel_box(s, box, 8, (4, 14, 24, 205), border=col)
        r_lab = f.blit(s, "RADIO · " + who.upper(), (box.x + 14, box.y + 6), 12, col, bold=True)
        # ecualizador mientras suena la transmisión
        t = time.time()
        for k in range(7):
            h = 3 + 9 * abs(math.sin(t * (7 + k * 1.7) + k * 1.3))
            pygame.draw.rect(s, col, (r_lab.right + 10 + k * 5, r_lab.centery + 6 - h, 3, h))
        for i, t in enumerate(lines):
            f.blit(s, t, (box.x + 14, box.y + 24 + 22 * i), 16, (240, 240, 240))

    def draw_radio_overlay(self):
        """Panel de radio: frecuencia sintonizada, menú de transmisiones y transcripción."""
        s = self.overlay
        f = self.fonts
        ui = self.ui
        w = self.world
        atc = w.atc
        bw = min(560, self.W * 0.42)
        opts = atc.options()
        log = list(self.radio_log)[-6:]
        bh = 112 + 34 * len(opts) + 26 + 22 * max(1, len(log)) + 20
        box = pygame.Rect(14, max(70, int(self.H * 0.16)), bw, min(bh, self.H - 100))
        panel_box(s, box, 12, (8, 12, 20, 235), border=(70, 120, 190))
        # cabecera con la frecuencia
        st = atc.tuned()
        nm = {"TWR": "TORRE", "GND": "RODADURA", "ATIS": "ATIS"}.get(st, "sin estación" if w.ac.sys.avionics_ok else "RADIO APAGADA")
        f.blit(s, "RADIO COM1", (box.x + 14, box.y + 10), 13, COL["accent"], bold=True)
        f.blit(s, f"{w.com_freq:7.3f}", (box.x + 120, box.y + 6), 22, (90, 240, 140), mono=True, bold=True)
        f.blit(s, nm + (f" · {atc.facility()[0]}" if st else "") + (" · ATC EXTERNO" if atc.external else ""),
               (box.x + 250, box.y + 12), 14, COL["white"] if st else COL["amber"], bold=True)
        # botones de sintonía rápida
        x = box.x + 14
        for key in ("ATIS", "GND", "TWR"):
            fq = w.freqs.get(key)
            if not fq:
                continue
            lab = {"ATIS": "ATIS", "GND": "Rodadura", "TWR": "Torre"}[key] + f" {fq:.3f}".rstrip("0").rstrip(".")
            tw = f.get(12, True).size(lab)[0] + 20
            if ui.button(s, (x, box.y + 40, tw, 28), lab, active=st == key, size=12, tip="Sintonizar en COM1"):
                self.radio_tune(key)
            x += tw + 6
        if atc.squawk:
            ok = w.xpdr == int(atc.squawk)
            r = pygame.Rect(box.right - 150, box.y + 40, 136, 28)
            if ui.button(s, r, f"XPDR {atc.squawk}" + ("" if ok else " ←"), active=ok, size=12,
                         tip="Poner el código de transpondedor asignado"):
                w.xpdr = int(atc.squawk)
        y = box.y + 80
        f.blit(s, "¿Qué quiere decir?  (teclas 1–9, o Ctrl derecho y dígalo por el micrófono)", (box.x + 14, y), 13, COL["grey"])
        y += 22
        for i, (lab, station, fn) in enumerate(opts):
            r = pygame.Rect(box.x + 10, y, box.w - 20, 30)
            hov = ui.hover(r)
            emerg = "MAYDAY" in lab
            hsel = i == self.hardware.radio_sel and bool(self.hardware.bindings.get("btn_radio_sig"))
            pygame.draw.rect(s, (120, 30, 30) if emerg else ((40, 70, 110) if (hov or hsel) else (24, 32, 44)), r, border_radius=6)
            f.blit(s, str(i + 1), (r.x + 14, r.centery), 14, COL["yellow"], bold=True, mono=True, anchor="center")
            f.blit(s, lab, (r.x + 30, r.centery), 14, COL["white"], anchor="midleft")
            f.blit(s, {"TWR": "TWR", "GND": "GND"}.get(station, ""), (r.right - 8, r.centery), 11, COL["grey"], anchor="midright")
            if ui.hit(r):
                fn()
            y += 34
        if not opts:
            f.blit(s, "(nada que transmitir ahora)", (box.x + 14, y), 14, COL["grey"])
            y += 24
        y += 6
        pygame.draw.line(s, (50, 60, 76), (box.x + 10, y), (box.right - 10, y))
        y += 8
        cols = {"yo": (140, 220, 255), "atc": (255, 220, 120), "ia": (190, 190, 190), "atis": (180, 230, 180)}
        for who, txt, t0 in log:
            tag = {"yo": "Usted", "atc": "ATC", "ia": "Tráfico", "atis": "ATIS"}[who]
            line = f.wrap(f"{tag}: {txt}", 13, box.w - 28)
            for ln in line[:2]:
                if y > box.bottom - 18:
                    break
                f.blit(s, ln, (box.x + 14, y), 13, cols[who])
                y += 18
        if not log:
            f.blit(s, "Consejo: escuche el ATIS, pida rodaje a Rodadura y salida a la Torre.", (box.x + 14, y), 13, COL["grey"])

    def draw_checklist_overlay(self):
        """Tableta electrónica (EFB) con las listas de verificación por fase de vuelo."""
        from sim import checklists as CL
        s = self.overlay
        f = self.fonts
        ui = self.ui
        w = self.world
        L = self.lesson
        lists = CL.lists_for(w)
        if L is not None and getattr(L, "checklist", None):
            lists.insert(0, ("Lección", [(t, "", (lambda ww, d=done: d)) for t, done in L.checklist]))
        if not hasattr(self, "efb_manual"):
            self.efb_manual = {}
            self.efb_auto = True
            self.efb_tab = 0
            self.efb_emerg = None
        # pestaña de emergencias: menú de listas o la lista elegida
        elists = CL.emergency_lists(w)
        sug = CL.suggested_emergency(w, elists)
        if self.efb_auto and sug:
            self.efb_emerg = sug
        sel = next((it for n, it in elists if n == self.efb_emerg), None)
        if sel is None:
            self.efb_emerg = None
            em_items = [(n, "▶", "menu") for n, _ in elists]
        else:
            em_items = [("◀ Todas las emergencias", "", "back")] + list(sel)
        lists.append(("EMERGENCIAS", em_items))
        lists.append(("PESO Y RENDIMIENTO", [("", "", "info")] * 12))
        if L is not None and hasattr(L, "plan_rows"):
            # cuaderno de navegación de la travesía
            rows = []
            for a, b_, c in L.plan_rows():
                rows += [(a, b_, "info"), ("", c, "info")]
            lists.insert(0, ("PLAN", rows))
        if self.efb_auto:
            self.efb_tab = CL.suggested_phase(w, lists)
            if lists[0][0] == "Lección" and not all(d for _, d in L.checklist):
                self.efb_tab = 0
            if sug:
                self.efb_tab = len(lists) - 1
        self.efb_tab = max(0, min(self.efb_tab, len(lists) - 1))
        name, items = lists[self.efb_tab]
        bw = min(500, self.W * 0.36)

        def row_h(txt, val):
            wide = f.get(14).size(txt)[0] + f.get(12, True).size(val or "")[0] + 70
            return 48 if wide > bw - 16 else 32
        short_names = {"Antes de arrancar": "Pre-arranque", "Antes del despegue": "Pre-despegue", "Despegue y ascenso": "Despegue",
                       "Antes del aterrizaje": "Aterrizaje", "Después del aterrizaje": "Post-aterrizaje"}
        tab_rows, tx_ = 1, 0
        for nm, _ in lists:
            tw_ = f.get(12, True).size(short_names.get(nm, nm))[0] + 24
            if tx_ + tw_ > bw - 20:
                tab_rows += 1
                tx_ = 0
            tx_ += tw_
        bh = min(self.H - 80, 116 + 30 * tab_rows + sum(row_h(t, v) for t, v, _ in items) + 60)
        box = pygame.Rect(self.W - bw - 14, 64, bw, bh)
        # marco de la tableta
        pygame.draw.rect(s, (18, 20, 24, 245), box.inflate(16, 16), border_radius=22)
        pygame.draw.rect(s, (70, 74, 82), box.inflate(16, 16), 2, border_radius=22)
        pygame.draw.rect(s, (236, 238, 240, 250), box, border_radius=12)
        hdr = pygame.Rect(box.x, box.y, box.w, 42)
        pygame.draw.rect(s, (28, 92, 168), hdr, border_top_left_radius=12, border_top_right_radius=12)
        f.blit(s, "LISTA DE VERIFICACIÓN", (hdr.x + 14, hdr.centery), 14, (255, 255, 255), bold=True, anchor="midleft")
        f.blit(s, w.ac.t.short, (hdr.right - 14, hdr.centery), 13, (210, 225, 245), bold=True, anchor="midright")
        # pestañas
        tx, ty = box.x + 10, hdr.bottom + 8
        for k, (nm, _) in enumerate(lists):
            short = {"Antes de arrancar": "Pre-arranque", "Antes del despegue": "Pre-despegue", "Despegue y ascenso": "Despegue",
                     "Antes del aterrizaje": "Aterrizaje", "Después del aterrizaje": "Post-aterrizaje",
                     "EMERGENCIA: falla de motor": "EMERGENCIA"}.get(nm, nm)
            tw = f.get(12, True).size(short)[0] + 18 + 18
            if tx + tw > box.right - 10:
                tx = box.x + 10
                ty += 30
            r = pygame.Rect(tx, ty, tw, 26)
            act = k == self.efb_tab
            col = (200, 40, 40) if "EMERG" in nm else (28, 92, 168)
            pygame.draw.rect(s, col if act else (214, 218, 224), r, border_radius=6)
            from ui import theme
            kind = ("emergencia" if "EMERG" in nm else "peso" if "PESO" in nm else "plan" if nm == "PLAN" else
                    "leccion" if nm == "Lección" else "lista")
            tcol = (255, 255, 255) if act else (40, 46, 56)
            theme.icon(s, kind, (r.x + 15, r.centery), 13, tcol, 2)
            f.blit(s, short, (r.x + 26, r.centery), 12, tcol, bold=True, anchor="midleft")
            if ui.hit(r):
                self.efb_tab = k
                self.efb_auto = False
            tx += tw + 6
        y = ty + 38
        title = ("EMERGENCIA: " + self.efb_emerg).upper() if name == "EMERGENCIAS" and self.efb_emerg else name.upper()
        f.blit(s, title, (box.x + 14, y), 15, (200, 40, 40) if "EMERG" in name else (20, 30, 44), bold=True)
        y += 28
        if name == "PESO Y RENDIMIENTO":
            self._efb_weight(s, box, y)
            return
        done_n = 0
        for k, (txt, val, fn) in enumerate(items):
            rh = row_h(txt, val)
            row = pygame.Rect(box.x + 8, y - 2, box.w - 16, rh - 2)
            if y + rh > box.bottom - 50:
                break
            if fn == "info":
                f.blit(s, txt, (row.x + 10, row.y + 6), 14, (20, 30, 44), bold=True)
                f.blit(s, val, (row.right - 10, row.y + 7), 13, (40, 90, 160), bold=True, anchor="topright")
                y += rh
                continue
            if fn in ("menu", "back"):
                # filas de navegación del menú de emergencias
                if ui.hover(row):
                    pygame.draw.rect(s, (246, 220, 220), row, border_radius=6)
                f.blit(s, txt, (row.x + 12, row.y + 6), 14, (170, 30, 30) if fn == "menu" else (40, 90, 160), bold=True)
                if val:
                    f.blit(s, val, (row.right - 10, row.y + 6), 14, (170, 30, 30), bold=True, anchor="topright")
                if ui.hit(row):
                    self.efb_emerg = txt if fn == "menu" else None
                    self.efb_auto = False
                y += 32
                continue
            key = (name if name != "EMERGENCIAS" else self.efb_emerg, k)
            auto = fn is not None and fn(w)
            manual = self.efb_manual.get(key, False)
            done = auto or manual
            done_n += done
            if ui.hover(row):
                pygame.draw.rect(s, (220, 228, 238), row, border_radius=6)
            cb = pygame.Rect(row.x + 6, row.y + 6, 18, 18)
            pygame.draw.rect(s, (40, 160, 80) if done else (255, 255, 255), cb, border_radius=4)
            pygame.draw.rect(s, (90, 100, 110), cb, 1, border_radius=4)
            if done:
                pygame.draw.lines(s, (255, 255, 255), False, [(cb.x + 4, cb.centery), (cb.x + 8, cb.bottom - 4), (cb.right - 3, cb.y + 4)], 3)
            col = (110, 120, 130) if done else (20, 24, 30)
            f.blit(s, txt, (cb.right + 10, row.y + 6), 14, col)
            if val:
                vy = row.y + 7 if rh == 32 else row.y + 26
                f.blit(s, val, (row.right - 8, vy), 12, (40, 90, 160) if not done else (120, 160, 130), bold=True, anchor="topright")
            if fn is None and ui.hit(row):
                self.efb_manual[key] = not manual
            y += rh
        # pie: progreso y navegación
        foot = pygame.Rect(box.x + 10, box.bottom - 46, box.w - 20, 36)
        f.blit(s, f"{done_n}/{len(items)} completados", (foot.x, foot.centery), 13, (60, 70, 84), anchor="midleft")
        if ui.button(s, (foot.right - 150, foot.y, 150, 34), "Siguiente lista ▶", size=13):
            self.efb_tab = (self.efb_tab + 1) % len(lists)
            self.efb_auto = False
        if ui.button(s, (foot.right - 254, foot.y, 96, 34), "Auto", active=self.efb_auto, size=13,
                     tip="Elegir la lista según la fase del vuelo"):
            self.efb_auto = not self.efb_auto

    def _efb_weight(self, s, box, y):
        """Pestaña de la tableta: peso y centrado y distancias de despegue/aterrizaje."""
        from sim.weight import LB, WeightBalance
        f = self.fonts
        ui = self.ui
        w = self.world
        ac = w.ac
        t = ac.t
        if getattr(self, "wb", None) is None or self.wb.type_id != t.id:
            self.wb = WeightBalance(t.id)
        wb = self.wb
        x0 = box.x + 14
        dark = (20, 30, 44)
        changed = False
        for key, nm, _arm, mx in wb.d["stations"]:
            f.blit(s, nm, (x0, y + 6), 13, dark)
            v = wb.loads.get(key, 0.0)
            bx = box.right - 170
            if ui.button(s, (bx, y, 30, 26), "−", size=14):
                wb.loads[key] = max(0.0, v - 5)
                changed = True
            f.blit(s, f"{wb.loads[key]:.0f} kg", (bx + 75, y + 13), 14, dark, bold=True, anchor="center")
            if ui.button(s, (bx + 120, y, 30, 26), "+", size=14):
                wb.loads[key] = min(mx * 1.3, v + 5)
                changed = True
            y += 32
        # combustible
        f.blit(s, "Combustible", (x0, y + 6), 13, dark)
        bx = box.right - 170
        if ui.button(s, (bx, y, 30, 26), "−", size=14):
            ac.sys.fuel_l = max(10.0, ac.sys.fuel_l - 10)
            changed = True
        f.blit(s, f"{ac.sys.fuel_l:.0f} L", (bx + 75, y + 13), 14, dark, bold=True, anchor="center")
        if ui.button(s, (bx + 120, y, 30, 26), "+", size=14):
            ac.sys.fuel_l = min(t.fuel_capacity, ac.sys.fuel_l + 10)
            changed = True
        y += 40
        r = wb.apply(t, ac.sys.fuel_l) if (changed or getattr(self, "_wb_applied", None) != t.id) else \
            wb.compute(ac.sys.fuel_l, t.fuel_density)
        self._wb_applied = t.id
        ok = r["ok_w"] and r["ok_cg"] and r["ok_bag"]
        res = pygame.Rect(box.x + 10, y, box.w - 20, 62)
        pygame.draw.rect(s, (215, 240, 222) if ok else (250, 220, 215), res, border_radius=8)
        f.blit(s, f"Peso {r['w_lb']:.0f} lb ({r['w_kg']:.0f} kg) · máx {r['mtow_lb']} lb", (res.x + 10, res.y + 8), 14,
               (20, 110, 50) if r["ok_w"] else (180, 40, 30), bold=True)
        f.blit(s, f"CG {r['cg']:.1f} in · límites {r['fwd']:.1f} – {r['aft']:.1f} in", (res.x + 10, res.y + 32), 14,
               (20, 110, 50) if r["ok_cg"] else (180, 40, 30), bold=True)
        y = res.bottom + 10
        # envolvente de centrado
        env = wb.d["env"]
        ch = pygame.Rect(box.x + 14, y, box.w - 28, 110)
        pygame.draw.rect(s, (246, 248, 250), ch, border_radius=6)
        cgs = [e[1] for e in env] + [e[2] for e in env] + [r["cg"]]
        ws = [e[0] for e in env] + [r["w_lb"]]
        c0, c1 = min(cgs) - 1, max(cgs) + 1
        w0, w1 = min(ws) - 100, max(max(ws), wb.d["mtow_lb"]) + 100

        def P(cg, wt):
            return (ch.x + 8 + (cg - c0) / (c1 - c0) * (ch.w - 16), ch.bottom - 8 - (wt - w0) / (w1 - w0) * (ch.h - 16))
        poly = [P(e[1], e[0]) for e in env] + [P(e[2], e[0]) for e in reversed(env)]
        pygame.draw.polygon(s, (200, 228, 210), poly)
        pygame.draw.polygon(s, (40, 130, 70), poly, 2)
        pygame.draw.circle(s, (20, 110, 50) if ok else (200, 40, 30), P(r["cg"], r["w_lb"]), 6)
        f.blit(s, "envolvente de centrado", (ch.x + 8, ch.y + 4), 11, (90, 100, 110))
        y = ch.bottom + 10
        # rendimiento con la meteorología y el aeródromo actuales
        wx = w.weather
        rw_hdg = w.active_rw.end(w.active_end)[1]
        head = wx.wind_kt * math.cos(math.radians(wx.wind_dir - rw_hdg))
        oat = 15 + wx.temp_offset - w.home.elev / FT * 0.00198
        _, surf = w.terrain.surface(w.active_rw.center[0], w.active_rw.center[1])
        p = wb.performance(r["w_lb"], w.home.elev / FT, wx.qnh_hpa, oat, head, grass=(surf == "cesped"))
        rows = [("Altitud de densidad", f"{p['da']:.0f} ft"), (f"Viento en pista {w.active_end}", f"{head:+.0f} kt"),
                ("Despegue: carrera / sobre 50 ft", f"{p['to_roll']:.0f} / {p['to_50']:.0f} ft"),
                ("Aterrizaje: carrera / sobre 50 ft", f"{p['ldg_roll']:.0f} / {p['ldg_50']:.0f} ft"),
                ("Pista disponible", f"{w.active_rw.length / FT:.0f} ft")]
        for lab, val in rows:
            if y > box.bottom - 30:
                break
            f.blit(s, lab, (x0, y), 13, dark)
            col = (180, 40, 30) if ("Despegue" in lab and p["to_50"] > w.active_rw.length / FT) else (40, 90, 160)
            f.blit(s, val, (box.right - 14, y), 13, col, bold=True, anchor="topright")
            y += 22
        f.blit(s, "Valores típicos del POH: use siempre los de su avión.", (x0, box.bottom - 22), 11, (110, 120, 130))

    # ================================================================ pausa
    def screen_pause(self, events):
        s = self.overlay
        f = self.fonts
        for ev in events:
            if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_ESCAPE, pygame.K_p):
                self.state = "flight"
                return
        dim = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 120))
        s.blit(dim, (0, 0))
        box = pygame.Rect(0, 0, 380, 470)
        box.center = (self.W / 2, self.H / 2)
        panel_box(s, box, 16, (10, 16, 26, 235))
        f.blit(s, "PAUSA", (box.centerx, box.y + 18), 28, COL["white"], bold=True, anchor="midtop")
        y = box.y + 70
        bw = box.w - 60
        acts = [("Continuar", lambda: setattr(self, "state", "flight")),
                ("Reiniciar", self.restart_lesson),
                ("Estación del instructor", lambda: setattr(self, "state", "instructor")),
                ("Repetición", self.enter_replay),
                ("Terminar y evaluar", self.end_flight),
                ("Menú principal", self.to_menu)]
        for lab, fn in acts:
            if self.ui.button(s, (box.x + 30, y, bw, 46), lab, size=17):
                fn()
                return
            y += 54
        f.blit(s, f"Timón automático: {'sí' if self.controls.assist_rudder else 'no'}  ·  Voz: {'sí' if self.voice.enabled else 'no'}",
               (box.centerx, box.bottom - 24), 13, COL["grey"], anchor="center")

    def to_menu(self):
        self.audio.silence()
        self.voice.stop()
        self.lesson = None
        self.state = "menu"
        self.menu_page = "main"
        self.world.weather.hour = 11.0
        self.world.reposition("pista")

    # ================================================================ estación del instructor
    def screen_instructor(self, events):
        s = self.overlay
        f = self.fonts
        ui = self.ui
        w = self.world
        wx = w.weather
        ac = w.ac
        for ev in events:
            if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_ESCAPE, pygame.K_i):
                self.state = "flight"
                return
        box = pygame.Rect(0, 0, min(self.W - 60, 1000), min(self.H - 60, 620))
        box.center = (self.W / 2, self.H / 2)
        panel_box(s, box, 16, (8, 14, 24, 240))
        f.blit(s, "ESTACIÓN DEL INSTRUCTOR", (box.x + 24, box.y + 18), 22, COL["white"], bold=True)
        f.blit(s, "La simulación está en pausa mientras configura.", (box.x + 26, box.y + 50), 13, COL["grey"])
        tabs = [("clima", "Meteorología"), ("fallas", "Fallas"), ("pos", "Reposicionar"), ("control", "Congelar y mover"),
                ("avion", "Avión")]
        tx = box.x + 24
        for key, lab in tabs:
            if ui.button(s, (tx, box.y + 76, 170, 36), lab, active=self.instr_tab == key, size=15):
                self.instr_tab = key
            tx += 178
        if ui.button(s, (box.right - 160, box.y + 16, 136, 36), "Volver (Esc)", size=14, color=(30, 110, 70)):
            self.state = "flight"
            return
        x0 = box.x + 30
        y = box.y + 134

        def stepper(label, txt, dec, inc, yy):
            f.blit(s, label, (x0, yy + 8), 16, COL["white"])
            if ui.button(s, (x0 + 230, yy, 40, 32), "−", size=18):
                dec()
            f.blit(s, txt, (x0 + 340, yy + 16), 16, COL["white"], bold=True, anchor="center")
            if ui.button(s, (x0 + 410, yy, 40, 32), "+", size=18):
                inc()
        tab = self.instr_tab
        if tab == "clima":
            rows = [
                ("Dirección del viento", f"{wx.wind_dir:03.0f}°", lambda: setattr(wx, "wind_dir", (wx.wind_dir - 10) % 360),
                 lambda: setattr(wx, "wind_dir", (wx.wind_dir + 10) % 360)),
                ("Velocidad del viento", f"{wx.wind_kt:.0f} kt", lambda: setattr(wx, "wind_kt", max(0, wx.wind_kt - 2)),
                 lambda: setattr(wx, "wind_kt", min(45, wx.wind_kt + 2))),
                ("Ráfagas (+kt)", f"{wx.gust_kt:.0f} kt", lambda: setattr(wx, "gust_kt", max(0, wx.gust_kt - 2)),
                 lambda: setattr(wx, "gust_kt", min(30, wx.gust_kt + 2))),
                ("Turbulencia", f"{wx.turbulence * 100:.0f} %", lambda: setattr(wx, "turbulence", max(0, wx.turbulence - 0.1)),
                 lambda: setattr(wx, "turbulence", min(1, wx.turbulence + 0.1))),
                ("Visibilidad", f"{wx.visibility_m / 1000:.1f} km", lambda: setattr(wx, "visibility_m", max(300, wx.visibility_m * 0.7)),
                 lambda: setattr(wx, "visibility_m", min(60000, wx.visibility_m / 0.7))),
                ("Nubosidad", f"{wx.cloud_cover * 100:.0f} %", lambda: setattr(wx, "cloud_cover", max(0, round(wx.cloud_cover - 0.1, 2))),
                 lambda: setattr(wx, "cloud_cover", min(1, round(wx.cloud_cover + 0.1, 2)))),
                ("Base de nubes (QNH)", f"{wx.cloud_base_ft:.0f} ft", lambda: setattr(wx, "cloud_base_ft", max(500, wx.cloud_base_ft - 250)),
                 lambda: setattr(wx, "cloud_base_ft", min(12000, wx.cloud_base_ft + 250))),
                ("QNH", f"{wx.qnh_hpa:.0f} hPa", lambda: setattr(wx, "qnh_hpa", wx.qnh_hpa - 1), lambda: setattr(wx, "qnh_hpa", wx.qnh_hpa + 1)),
                ("Humedad (temp − rocío)", f"{wx.dew_spread:.0f} °C", lambda: setattr(wx, "dew_spread", max(0.0, wx.dew_spread - 1)),
                 lambda: setattr(wx, "dew_spread", min(25.0, wx.dew_spread + 1))),
                ("Hora local", f"{int(wx.hour):02d}:{int(wx.hour % 1 * 60):02d}", lambda: setattr(wx, "hour", (wx.hour - 0.5) % 24),
                 lambda: setattr(wx, "hour", (wx.hour + 0.5) % 24)),
            ]
            wx.cloud_top_ft = max(wx.cloud_top_ft, wx.cloud_base_ft + 800)
            for i, (lab, txt, dec, inc) in enumerate(rows):
                stepper(lab, txt, dec, inc, y + i * 40)
            px = box.x + 520
            f.blit(s, "Preajustes", (px, y), 15, COL["accent"], bold=True)
            for i, (name, pr) in enumerate(WEATHER_PRESETS):
                pr_rect = (px, y + 28 + i * 40, 200, 34) if i < 6 else (px + 210, y + 28 + (i - 5) * 40, 170, 34)
                if ui.button(s, pr_rect, name, size=14):
                    apply_weather_preset(self.world, pr)
            if ui.button(s, (px + 210, y + 28, 170, 34), "☁ METAR real", size=14,
                         tip="Descarga la meteorología real del aeropuerto (aviationweather.gov)"):
                self.apply_live_weather()
            if ui.button(s, (px, y + 28 + 6 * 40, 200, 34), "Cizalladura: " + ("SÍ" if wx.wind_shear else "no"),
                         active=wx.wind_shear, size=14):
                wx.wind_shear = not wx.wind_shear
            f.blit(s, wx.describe(), (px, y + 28 + 7 * 40 + 6), 13, COL["grey"], mono=True)
        elif tab == "fallas":
            from sim.emergencies import CATALOG, TRIGGERS
            em = w.emerg
            if not hasattr(self, "fail_trigger"):
                self.fail_trigger = "ahora"
            f.blit(s, "¿Cuándo?", (x0, y + 8), 15, COL["accent"], bold=True)
            tx = x0 + 90
            for key, lab in TRIGGERS:
                tw = f.get(12, True).size(lab)[0] + 20
                if ui.button(s, (tx, y, tw, 30), lab, active=self.fail_trigger == key, size=12):
                    self.fail_trigger = key
                tx += tw + 6
            y += 44
            fails = [(k, n) for k, n, ok in CATALOG if ok(ac.t)]
            pending = {e["key"]: e["trigger"] for e in em.plan if not e["fired"]}
            cw = (box.w - 60) / 3
            for i, (k, lab) in enumerate(fails):
                col, row = i % 3, i // 3
                on = ac.sys.failures.get(k, False)
                pend = k in pending
                txt = ("⚠ " + lab) if on else (("⏱ " + lab) if pend else lab)
                r = (x0 + col * cw, y + row * 44, cw - 10, 38)
                if ui.button(s, r, txt, color=(140, 40, 30) if on else ((120, 90, 20) if pend else None), size=13,
                             tip="Activa: clic para reparar" if on else ("Programada: clic para cancelar" if pend else
                                                                         "Clic para provocar la falla en el momento elegido")):
                    if on:
                        ac.sys.failures[k] = False
                        if k == "fire":
                            ac.sys.fire_level = 0.0
                    elif pend:
                        em.plan = [e for e in em.plan if not (e["key"] == k and not e["fired"])]
                    else:
                        em.schedule(k, self.fail_trigger)
            ry = y + 44 * ((len(fails) + 2) // 3) + 8
            if ui.button(s, (x0, ry, 220, 36), "Reparar todo", size=14, color=(30, 110, 70)):
                for k in ac.sys.failures:
                    ac.sys.failures[k] = False
                for en in ac.sys.engines:
                    en.carb_ice = 0.0
                em.plan = []
                ac.sys.fire_level = ac.sys.smoke_level = 0.0
                ac.sys.gear_emergency = False
                ac.sys.trim_cb = True
            f.blit(s, "⚠ activa   ⏱ programada. El alumno no ve qué falla es: debe reconocer los síntomas.",
                   (x0 + 240, ry + 10), 13, COL["grey"])
            yy = ry + 50
            for name, txt, ok in em.report()[-4:]:
                f.blit(s, f"{name}: {txt}", (x0, yy), 13, COL["green"] if ok else COL["amber"])
                yy += 20
        elif tab == "pos":
            keys = list(POSITIONS.keys())
            for i, k in enumerate(keys):
                col, row = i % 2, i // 2
                if ui.button(s, (x0 + col * 420, y + row * 48, 400, 40), POSITIONS[k], size=15):
                    w.reposition(k, cold=(k == "plataforma"))
                    self.state = "flight"
                    self.flash(POSITIONS[k])
                    return
        elif tab == "control":
            f.blit(s, "Congelar", (x0, y + 8), 16, COL["white"])
            for i, (k, lab) in enumerate(w.FREEZES.items()):
                on = k in w.frozen
                if ui.button(s, (x0 + 230 + i * 150, y, 140, 34), ("❄ " if on else "") + lab.capitalize(), active=on,
                             size=14, tip="Mantiene el valor actual mientras el avión sigue volando"):
                    w.freeze(k, not on)
            y += 50
            f.blit(s, "Ritmo del tiempo", (x0, y + 8), 16, COL["white"])
            for i, x in enumerate((1, 2, 4)):
                if ui.button(s, (x0 + 230 + i * 100, y, 90, 34), f"×{x}", active=w.sim_rate == x, size=14,
                             tip="Acelerar solo en vuelo, por encima de 500 ft; cerca del suelo vuelve a ×1"):
                    if not w.set_rate(x):
                        self.flash("El tiempo solo se acelera en vuelo, por encima de 500 ft", 3)
            y += 50
            f.blit(s, "Mover el avión", (x0, y + 8), 16, COL["white"])
            moves = [("1 NM al norte", dict(north_nm=1)), ("1 NM al sur", dict(north_nm=-1)),
                     ("1 NM al este", dict(east_nm=1)), ("1 NM al oeste", dict(east_nm=-1)),
                     ("+500 ft", dict(alt_ft=500)), ("−500 ft", dict(alt_ft=-500)),
                     ("Rumbo −30°", dict(hdg_deg=-30)), ("Rumbo +30°", dict(hdg_deg=30)), ("Dar la vuelta", dict(hdg_deg=180))]
            for i, (lab, kw) in enumerate(moves):
                col, row = i % 4, i // 4
                if ui.button(s, (x0 + 230 + col * 160, y + row * 44, 150, 36), lab, size=14):
                    if not w.slew(**kw):
                        self.flash("El avión solo se mueve en vuelo", 3)
            y += 3 * 44 + 10
            d = math.hypot(ac.pos[0] - w.home.ref[0], ac.pos[1] - w.home.ref[1]) / NM
            f.blit(s, f"Ahora: {ac.alt_msl / FT:,.0f} ft · rumbo {ac.heading:03.0f}° · {ac.ias_kt:.0f} kt · "
                      f"a {d:.1f} NM de {w.home.ident}", (x0, y), 14, COL["grey"])
            f.blit(s, "Lo congelado y el ritmo se quitan al reposicionar o empezar otra lección.", (x0, y + 24), 13,
                   COL["grey"])
        elif tab == "avion":
            f.blit(s, "Combustible", (x0, y + 8), 16, COL["white"])
            for i, (lab, frac) in enumerate((("Lleno", 1.0), ("3/4", 0.75), ("Mitad", 0.5), ("Reserva", 0.12))):
                if ui.button(s, (x0 + 230 + i * 110, y, 100, 34), lab, size=14):
                    ac.sys.fuel_l = ac.t.fuel_capacity * frac
            f.blit(s, f"{ac.sys.fuel_l:.0f} L  ·  masa {ac.sys.mass:.0f} kg", (x0 + 230, y + 44), 14, COL["grey"])
            y += 90
            f.blit(s, "Cambiar de avión (reinicia la posición)", (x0, y + 8), 16, COL["white"])
            ids = list(AIRCRAFT.keys())
            for i, k in enumerate(ids):
                if ui.button(s, (x0 + 360 + i * 220, y, 210, 34), AIRCRAFT[k]().short, active=w.aircraft_id == k, size=14):
                    if w.aircraft_id != k:
                        w.set_aircraft(k)
                        w.reposition("pista36")
                        self.state = "flight"
                        return
            y += 60
            f.blit(s, "Timón automático", (x0, y + 8), 16, COL["white"])
            if ui.button(s, (x0 + 230, y, 140, 34), "Sí" if self.controls.assist_rudder else "No",
                         active=self.controls.assist_rudder, size=14):
                self.controls.assist_rudder = not self.controls.assist_rudder
                self.settings["timon_auto"] = self.controls.assist_rudder

    # ================================================================ análisis posterior
    def screen_debrief(self, events):
        s = self.overlay
        f = self.fonts
        ui = self.ui
        for ev in events:
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                self.to_menu()
                return
        dim = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
        dim.fill((4, 8, 14, 170))
        s.blit(dim, (0, 0))
        box = pygame.Rect(30, 30, self.W - 60, self.H - 60)
        panel_box(s, box, 16, (8, 14, 24, 235))
        L = self.lesson
        R = self.result
        title = L.title if L else "Vuelo libre"
        f.blit(s, "ANÁLISIS DEL VUELO", (box.x + 28, box.y + 20), 14, COL["accent"], bold=True)
        f.blit(s, title, (box.x + 28, box.y + 40), 28, COL["white"], bold=True)
        lw = box.w * 0.48
        y = box.y + 92
        if R is not None:
            from ui import theme
            sc = R["score"]
            col = theme.GREEN if R["passed"] else (theme.AMBER if R["success"] else theme.RED)
            # anillo de la nota (se llena al abrir el análisis)
            if getattr(self, "_deb_res", None) is not R:
                self._deb_res, self._deb_t0 = R, time.time()
            k = min(1.0, (time.time() - self._deb_t0) / 1.2)
            k = 1 - (1 - k) ** 3
            c = (box.x + 28 + 46, y + 40)
            theme.ring(s, c, 44, sc / 100 * k, col, 7)
            f.blit(s, f"{sc * k:.0f}", (c[0], c[1] - 2), 30, col, tech=True, anchor="center")
            f.blit(s, "/100", (c[0], c[1] + 20), 11, COL["grey"], anchor="center")
            f.blit(s, R["grade"].upper(), (box.x + 210, y + 10), 26, col, bold=True)
            if R.get("acs"):
                f.blit(s, f"Tarea ACS {R['acs']} · {R.get('standard', '')}", (box.x + 28, y - 18), 13, (130, 160, 200))
            f.blit(s, "APROBADA" if R["passed"] else ("NO SUPERADA" + (f": {R['reason']}" if R["reason"] else "")),
                   (box.x + 210, y + 46), 15, COL["white"])
            y += 100
            f.blit(s, "Concepto", (box.x + 28, y), 13, COL["grey"], bold=True)
            f.blit(s, "Puntos", (box.x + lw - 10, y), 13, COL["grey"], bold=True, anchor="topright")
            y += 22
            maxrows = int((box.bottom - 90 - y) / 38)
            for name, got, mx, com in R["items"][:maxrows]:
                pygame.draw.line(s, (40, 48, 60), (box.x + 28, y - 3), (box.x + lw, y - 3))
                f.blit(s, name, (box.x + 28, y), 15, COL["white"], bold=True)
                ptxt = f"{got}/{mx}" if mx else f"{got:+d}"
                f.blit(s, ptxt, (box.x + lw - 10, y), 15, COL["green"] if (mx and got >= 0.75 * mx) else (COL["red"] if got < 0 else COL["white"]),
                       bold=True, anchor="topright")
                f.blit(s, com, (box.x + 28, y + 18), 12, COL["grey"])
                y += 38
        else:
            f.blit(s, "Vuelo libre registrado en la bitácora.", (box.x + 28, y), 18, COL["white"])
            y += 30
        f.blit(s, f"Tiempo de vuelo: {getattr(self, 'debrief_flight_s', 0) / 60:.1f} min   ·   Aterrizajes: {getattr(self, 'debrief_landings', 0)}"
                  f"   ·   G máx: {self.world.ac.max_g:.1f}", (box.x + 28, box.bottom - 80), 14, COL["grey"])
        em_rep = self.world.emerg.report()
        if em_rep:
            yy = box.bottom - 56 - 20 * min(3, len(em_rep))
            for name, txt, ok in em_rep[-3:]:
                f.blit(s, f"Emergencia — {name}: {txt}", (box.x + 28, yy), 13, COL["green"] if ok else COL["red"])
                yy += 20
        atc = self.world.atc
        if atc.engaged or atc.violations:
            txt = "Radio (ATC): " + ("; ".join(atc.violations) if atc.violations else "comunicaciones correctas")
            f.blit(s, f.wrap(txt, 13, lw - 420)[0] if lw > 600 else txt[:70], (box.x + 28, box.bottom - 56), 13,
                   COL["amber"] if atc.violations else COL["green"])
        # gráficas
        gx = box.x + lw + 30
        gw = box.right - gx - 28
        a = self.recorder.array()
        if a is not None and len(a) > 5:
            t = a[:, 0] - a[0, 0]
            F = self.recorder.FIELDS
            charts = [("Altitud (ft)", a[:, F.index("alt")], (120, 190, 255)),
                      ("Velocidad indicada (kt)", a[:, F.index("ias")], (120, 230, 140)),
                      ("Velocidad vertical (ft/min)", a[:, F.index("vs")], (250, 190, 90))]
            ch = (box.h - 92 - 84) / 4 - 10
            yy = box.y + 92
            for name, vals, colr in charts:
                self._chart(pygame.Rect(gx, yy, gw, ch), t, vals, name, colr)
                yy += ch + 14
            self._track_map(pygame.Rect(gx, yy, gw, ch), a)
        bx = box.right - 28
        if ui.button(s, (bx - 180, box.bottom - 60, 180, 42), "Menú principal", size=15):
            self.to_menu()
            return
        if ui.button(s, (bx - 370, box.bottom - 60, 180, 42), "Repetir lección", size=15, color=(30, 110, 70)):
            self.restart_lesson()
            return
        if ui.button(s, (bx - 560, box.bottom - 60, 180, 42), "Ver repetición", size=15):
            self.enter_replay()
            if self.replay:
                self.replay["prev_state"] = "debrief"
            return
        if ui.button(s, (bx - 940, box.bottom - 60, 180, 42), "Informe (PDF)", size=15, color=(30, 80, 140),
                     tip="Informe imprimible del vuelo para el alumno y el instructor"):
            self.make_flight_report()
        if ui.button(s, (bx - 750, box.bottom - 60, 180, 42), "Exportar CSV", size=15):
            d = os.path.join(os.path.dirname(self.settings_path), "vuelos")
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, time.strftime("vuelo_%Y%m%d_%H%M%S.csv"))
            if self.recorder.save_csv(p):
                self.flash("Datos guardados en datos/vuelos")

    def _chart(self, r, t, v, name, col):
        s = self.overlay
        f = self.fonts
        pygame.draw.rect(s, (14, 20, 30), r, border_radius=8)
        f.blit(s, name, (r.x + 10, r.y + 6), 12, COL["grey"], bold=True)
        inner = r.inflate(-20, -34)
        inner.y = r.y + 26
        lo, hi = float(np.min(v)), float(np.max(v))
        if hi - lo < 1:
            hi, lo = hi + 1, lo - 1
        f.blit(s, f"{hi:.0f}", (r.right - 8, r.y + 6), 11, COL["grey"], anchor="topright")
        f.blit(s, f"{lo:.0f}", (r.right - 8, r.bottom - 16), 11, COL["grey"], anchor="topright")
        n = len(t)
        step = max(1, n // 400)
        T = t[::step]
        V = v[::step]
        tmax = max(T[-1], 1e-3)
        pts = [(inner.x + tt / tmax * inner.w, inner.bottom - (vv - lo) / (hi - lo) * inner.h) for tt, vv in zip(T, V)]
        if len(pts) > 1:
            pygame.draw.lines(s, col, False, pts, 2)
        for te, txt in self.recorder.events[:20]:
            x = inner.x + (te - (self.recorder.rows[0][0] if self.recorder.rows else 0)) / tmax * inner.w
            if inner.x <= x <= inner.right:
                pygame.draw.line(s, (90, 90, 110), (x, inner.y), (x, inner.bottom), 1)

    def _track_map(self, r, a):
        s = self.overlay
        f = self.fonts
        pygame.draw.rect(s, (14, 20, 30), r, border_radius=8)
        clip = s.get_clip()
        s.set_clip(r)
        f.blit(s, "Trayectoria (vista en planta)", (r.x + 10, r.y + 6), 12, COL["grey"], bold=True)
        F = self.recorder.FIELDS
        xs, ys = a[:, F.index("x")], a[:, F.index("y")]
        pts_n = list(xs)
        pts_e = list(ys)
        for ap in self.world.airports:
            for rw in ap.runways:
                for p in (rw.threshold, rw.far_end):
                    if abs(p[0] - np.mean(xs)) < 20000 and abs(p[1] - np.mean(ys)) < 20000:
                        pts_n.append(p[0])
                        pts_e.append(p[1])
        n0, n1 = min(pts_n), max(pts_n)
        e0, e1 = min(pts_e), max(pts_e)
        inner = r.inflate(-24, -36)
        inner.y = r.y + 26
        span = max(n1 - n0, e1 - e0, 500.0)
        sc = min(inner.w, inner.h) / span
        cx, cy = (e0 + e1) / 2, (n0 + n1) / 2

        def P(n, e):
            return (inner.centerx + (e - cx) * sc, inner.centery - (n - cy) * sc)
        for ap in self.world.airports:
            for rw in ap.runways:
                pygame.draw.line(s, (200, 200, 200), P(*rw.threshold), P(*rw.far_end), max(2, int(rw.width * sc)))
        step = max(1, len(xs) // 600)
        pts = [P(n, e) for n, e in zip(xs[::step], ys[::step])]
        if len(pts) > 1:
            pygame.draw.lines(s, (240, 80, 240), False, pts, 2)
            pygame.draw.circle(s, COL["green"], pts[0], 4)
            pygame.draw.circle(s, COL["red"], pts[-1], 4)
        s.set_clip(clip)
