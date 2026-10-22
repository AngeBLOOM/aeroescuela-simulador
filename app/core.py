"""Aplicación principal: ventana, bucle, estados y vuelo."""
import json
import math
import os
import sys
import time
from collections import deque

os.environ.setdefault("SDL_WINDOWS_DPI_AWARENESS", "permonitorv2")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import moderngl
import numpy as np
import pygame

from render.camera import MODE_NAMES, MODES, Camera
from render.renderer import Renderer
from sim.lessons import LESSONS, FreeFlight
from sim.mathx import FT, KT, clamp
from sim import geo
from sim.recorder import Recorder
from sim.world import World
from ui.panel import CockpitPanel
from ui.ui import COL, UI, Fonts, panel_box

from .audio import Audio
from .controls import Controls
from .progress import Progress
from .screens import ScreensMixin
from .radio import RadioVoice
from .voice import Voice

if getattr(sys, "frozen", False):
    # programa instalado: los recursos van dentro del paquete y los datos en la carpeta del usuario
    BASE = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    DATA = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "AeroEscuela", "datos")
else:
    BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATA = os.path.join(BASE, "datos")

DEFAULT_SETTINGS = dict(
    ancho=0, alto=0, pantalla_completa=False, volumen=0.75, voz=True, timon_auto=False,
    cabina="analog", avion="c172", mostrar_fps=False, joystick={}, ubicacion="", cabina_estilo="auto",
    calidad="auto", fluidez="auto", indicativo="EC-AES", atc=True, trafico=True,
    instructor_red=False,     # puesto del instructor por navegador web en la red local
    edificios_3d=False,
    fondo_instr="futurista",  # fondo de la pantalla de instrumentos: "futurista" o "negro" (tablero físico recortado)       # False: paisaje de foto satelital pura · True: con edificios 3D de OpenStreetMap
    atc_externo=False,        # enlace con un simulador de tránsito aéreo externo (app/atc_link.py, puerto 8770)
    atc_externo_puerto=8770,
    udp_salida=False,         # datos de vuelo por UDP para instrumentos, paneles o movimiento (app/udp_out.py)
    udp_destino="127.0.0.1",  # otra computadora: su IP; toda la red local: termina en .255
    udp_puerto=49020, udp_hz=30,
    monitores_paisaje=1,      # nº de monitores (de izquierda a derecha) que ocupa la vista exterior
    vistas=1,                 # 1 o 3 vistas (izquierda · frente · derecha) en la vista exterior
    pantalla_instr="no",      # "no" · "ambiente" (paisaje + instrumentos) · "unica" (solo instrumentos) · "segunda" (2.º monitor)
)


def seed_data():
    """Programa instalado: la primera vez copia los datos iniciales que trae el instalador (escenarios de Base Sucre y
    Caracas ya descargados, base de aeropuertos y configuración de partida) a la carpeta de datos del usuario.
    Nunca sobrescribe lo que ya exista (progreso, alumnos, ajustes)."""
    import shutil
    if not getattr(sys, "frozen", False):
        return
    src = os.path.join(os.path.dirname(sys.executable), "datos_iniciales")
    if not os.path.isdir(src):
        return
    for root, _dirs, files in os.walk(src):
        dst_dir = os.path.join(DATA, os.path.relpath(root, src))
        os.makedirs(dst_dir, exist_ok=True)
        for fn in files:
            dst = os.path.join(dst_dir, fn)
            if not os.path.exists(dst):
                try:
                    shutil.copy2(os.path.join(root, fn), dst)
                except OSError as ex:
                    print("No se pudo copiar", fn, ex)


class App(ScreensMixin):
    def __init__(self, autotest=None):
        self.autotest = autotest
        os.makedirs(DATA, exist_ok=True)
        seed_data()
        self.settings_path = os.path.join(DATA, "config.json")
        self.settings = dict(DEFAULT_SETTINGS)
        try:
            with open(self.settings_path, "r", encoding="utf-8") as f:
                self.settings.update(json.load(f))
        except Exception:
            pass
        pygame.init()
        pygame.display.set_caption("AeroEscuela — Simulador de entrenamiento de vuelo")
        try:
            pygame.display.set_icon(pygame.image.load(os.path.join(BASE, "assets", "icono.png")))
        except Exception:
            pass
        W, H = self._window_size()
        for attr, val in ((pygame.GL_CONTEXT_MAJOR_VERSION, 3), (pygame.GL_CONTEXT_MINOR_VERSION, 3),
                          (pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE),
                          (pygame.GL_DEPTH_SIZE, 24), (pygame.GL_MULTISAMPLEBUFFERS, 0), (pygame.GL_MULTISAMPLESAMPLES, 0)):
            pygame.display.gl_set_attribute(attr, val)
        flags = pygame.OPENGL | pygame.DOUBLEBUF
        if getattr(self, "_span", False):
            flags |= pygame.NOFRAME
        elif self.settings["pantalla_completa"]:
            flags |= pygame.FULLSCREEN
        try:
            self.screen = pygame.display.set_mode((W, H), flags, vsync=1)
        except Exception:
            pygame.display.gl_set_attribute(pygame.GL_MULTISAMPLEBUFFERS, 0)
            pygame.display.gl_set_attribute(pygame.GL_MULTISAMPLESAMPLES, 0)
            self.screen = pygame.display.set_mode((W, H), flags)
        self.W, self.H = pygame.display.get_window_size()
        self.ctx = moderngl.create_context()
        self.fonts = Fonts(scale=clamp(self.H / 900.0, 0.8, 1.4))
        self.ui = UI(self.fonts)
        self.overlay = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
        self.clock = pygame.time.Clock()
        self.ctx.gc_mode = "auto"
        self.geo_db = geo.AirportDB(DATA)
        self.loc_job = None
        loc = None
        code = self.settings.get("ubicacion") or ""
        if code:
            try:
                loc = geo.build_location(code, DATA, progress=lambda m, f: self._loading(m, f), db=self.geo_db)
            except Exception as ex:
                print("No se pudo cargar la ubicación guardada:", ex)
                self.settings["ubicacion"] = ""
        self._loading("Generando el mundo…", 0.1)
        self.world = World(self.settings.get("avion", "c172"), location=loc)
        self.world.buildings_3d = bool(self.settings.get("edificios_3d", False))
        self.renderer = Renderer(self.ctx, self.world, (self.W, self.H), progress=lambda m: self._loading(m, 0.5))
        self.fps_cap = 60
        self._work_avg = 12.0
        self._cap_timer = 0.0
        self.apply_quality()
        self._loading("Sintetizando sonidos…", 0.8)
        self.audio = Audio(self.settings["volumen"])
        self.voice = Voice(self.settings["voz"])
        self.radio = RadioVoice(self.settings["voz"], volume=min(1.0, self.settings["volumen"] * 1.1))
        self.radio_log = deque(maxlen=7)
        self.radio_now = None
        self.show_radio = False
        from .voice_input import VoiceInput
        self.voice_in = VoiceInput()
        self.show_controls = False
        from ui.instrument_display import InstrumentDisplay
        self.settings.setdefault("instr_layout", {})
        self.instr_display = InstrumentDisplay(self.fonts, self.settings["instr_layout"])
        self.instr_display.bg_style = self.settings.get("fondo_instr", "futurista")
        self.instr_win = None
        self.apply_instrument_screen()
        from ui.controls_screen import ControlsScreen
        self.controls_screen = ControlsScreen(self.fonts)
        self.ta_prev = False
        self.configure_world()
        self.controls = Controls(self.settings.get("joystick"))
        from .hardware import Hardware
        self.settings.setdefault("cabina_fisica", {})
        self.hardware = Hardware(self.settings["cabina_fisica"])
        self.controls.hw = self.hardware
        self._joy_reload_t = None        # mando USB recién conectado: se vuelven a abrir los mandos en este instante
        self.remote = None
        self._remote_t = 0.0
        self.apply_remote()
        self.cont_job = None              # mundo continuo: escenario siguiente que se prepara en segundo plano
        self._cont_retry = 0.0
        self.atc_bridge = None
        self._ptt_prev = False
        self.apply_atc_link()
        self.udp = None
        self.apply_udp()
        # barra de botones para el ratón (se esconde sola: en la cabina física no hay ratón)
        self._mouse_t = time.time()
        self._bar_rect = None
        self._bar_click = None
        self.controls.assist_rudder = self.settings["timon_auto"]
        self.ui.on_click = lambda: self.audio.play("ui_click", 0.6)     # botones del menú y de la interfaz
        self.camera = Camera()
        self.panel = CockpitPanel(self.fonts)
        self.panel.mode = self.settings.get("cabina", "analog")
        self.recorder = Recorder()
        from .students import Students
        self.students = Students(DATA)
        self.student = self.settings.get("alumno") or "Alumno"
        if self.student not in self.students.names():
            self.student = "Alumno"
        self.progress = self.students.load(self.student)
        self.new_student = None
        self.state = "menu"
        self.menu_page = "main"
        self.lesson = None
        self.lesson_cls = None
        self.result = None
        self.messages = deque(maxlen=4)
        self.flash_msg = None
        self.show_panel = True
        # cabina en pantalla: "auto" (según haya consola física), "2d", "3d" o "none". La cabina fotográfica ya no
        # existe: los mandos dibujados no sirven con la consola física (un ajuste antiguo pasa a "auto")
        self.cockpit_mode = self.settings.get("cabina_estilo", "auto")
        if self.cockpit_mode not in self.COCKPIT_MODES:
            self.cockpit_mode = self.settings["cabina_estilo"] = "auto"
        for k in ("foto_migrado", "foto_zoom"):
            self.settings.pop(k, None)
        self.cockpit_style = self.resolve_cockpit_style()     # lo que se dibuja: "2d", "3d", "none" o "franja"
        self.panel_surf3d = None
        self.compass_surf = None
        self.show_yoke = False          # volantes de la cabina 3D: ocultos (tecla Y para verlos)
        self.show_help = False
        self.show_check = False
        self.auto_start = None
        self.menu_t = 0.0
        self.fps = 60.0
        from app.latency import LatencyMeter
        self.latency = LatencyMeter()       # retardo interno (F9 lo muestra; se guarda en datos/retardo.json)
        self.selected_lesson = 0
        self.free_cfg = dict(avion=self.settings.get("avion", "c172"), pos="pista", clima=1, hora=1)
        self.loc_query = ""
        self.loc_results = []
        self.instr_tab = "clima"
        self.replay = None
        self.panel_cache = None
        self.panel_frame = 0
        self.flight_start_time = 0.0
        self.landings_start = 0
        self.flight_time_start = 0.0
        self.world.reposition("pista36")
        self.running = True

    # ------------------------------------------------------------ ventana
    def _window_size(self):
        n = int(self.settings.get("monitores_paisaje", 1) or 1)
        try:
            sizes = pygame.display.get_desktop_sizes()
        except Exception:
            sizes = []
        if n > 1 and len(sizes) >= n:
            # una ventana sin bordes que abarca los n primeros monitores (colocados de izquierda a derecha)
            os.environ["SDL_VIDEO_WINDOW_POS"] = "0,0"
            self._span = True
            return sum(s[0] for s in sizes[:n]), min(s[1] for s in sizes[:n])
        self._span = False
        w, h = self.settings.get("ancho", 0), self.settings.get("alto", 0)
        if w and h:
            return w, h
        try:
            dw, dh = pygame.display.get_desktop_sizes()[0]
        except Exception:
            dw, dh = 1920, 1080
        if self.settings["pantalla_completa"]:
            return dw, dh
        for cand in ((1920, 1080), (1600, 900), (1366, 768), (1280, 720), (1024, 576)):
            if cand[0] <= dw * 0.92 and cand[1] <= dh * 0.86:
                return cand
        return 1024, 576

    QUALITY = {"alta": (1.0, 4), "media": (0.85, 2), "rendimiento": (0.7, 0)}

    def quality_level(self):
        q = self.settings.get("calidad", "auto")
        if q == "auto":
            gpu = self.ctx.info.get("GL_RENDERER", "").lower()
            q = "media" if ("intel" in gpu or "uhd" in gpu or "iris" in gpu) else "alta"
        return q

    def apply_quality(self):
        scale, samples = self.QUALITY[self.quality_level()]
        self.renderer.set_quality(scale, samples)

    def save_settings(self):
        try:
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=1)
        except Exception as ex:
            print("No se pudo guardar la configuración:", ex)

    def _loading(self, msg, frac):
        pygame.event.pump()
        s = self.overlay if hasattr(self, "overlay") else pygame.Surface((self.W, self.H), pygame.SRCALPHA)
        from ui import theme
        s.fill((3, 9, 17, 255))
        f = self.fonts
        t = time.time()
        theme.hud_backdrop(s, self.W, self.H, t, 1)
        cx, cy = self.W / 2, self.H * 0.50
        rr = int(min(self.W, self.H) * 0.11)
        theme.spinner(s, (cx, cy), rr + 26, t * 2.0)
        theme.ring(s, (cx, cy), rr, frac, theme.CYAN, 7)
        f.blit(s, f"{frac * 100:.0f}%", (cx, cy - 4), 34, theme.TEXT, tech=True, anchor="center")
        theme.spaced(f, s, "CARGANDO", (cx, cy + 26), 11, theme.TEXT_DIM, 0.3, anchor="center")
        r_t = theme.spaced(f, s, "AEROESCUELA", (cx, self.H * 0.17), 38, theme.TEXT, 0.12, anchor="center")
        pygame.draw.line(s, theme.CYAN, (r_t.x, r_t.bottom + 8), (r_t.right, r_t.bottom + 8), 2)
        theme.spaced(f, s, "SIMULADOR DE ENTRENAMIENTO DE VUELO", (cx, r_t.bottom + 24), 12, theme.TEXT_DIM, 0.22, anchor="center")
        f.blit(s, "› " + msg, (cx, cy + rr + 60), 14, (150, 215, 238), tech=True, anchor="center")
        self.ctx.viewport = (0, 0, self.W, self.H)
        self.ctx.clear(0.04, 0.06, 0.1)
        if hasattr(self, "renderer"):
            self.renderer.draw_overlay(s)
        else:
            self._raw_overlay(s)
        pygame.display.flip()

    def _raw_overlay(self, s):
        """Dibuja la superposición antes de que exista el renderizador."""
        ctx = self.ctx
        if not hasattr(self, "_boot_prog"):
            self._boot_prog = ctx.program(
                vertex_shader="#version 330\nin vec2 p; out vec2 uv; void main(){uv=vec2(p.x*0.5+0.5,0.5-p.y*0.5);gl_Position=vec4(p,0,1);}",
                fragment_shader="#version 330\nuniform sampler2D t; in vec2 uv; out vec4 c; void main(){c=texture(t,uv);}")
            vb = ctx.buffer(np.array([-1, -1, 1, -1, 1, 1, -1, -1, 1, 1, -1, 1], "f4").tobytes())
            self._boot_vao = ctx.vertex_array(self._boot_prog, [(vb, "2f", "p")])
        tex = ctx.texture(s.get_size(), 4, pygame.image.tobytes(s, "RGBA"))
        tex.use(0)
        ctx.enable(moderngl.BLEND)
        self._boot_vao.render()
        tex.release()

    # ------------------------------------------------------------ utilidades
    def flash(self, text, secs=2.5):
        self.flash_msg = (text, time.time() + secs)

    def reload_joysticks(self):
        """Mando USB conectado o desconectado: se vuelven a abrir todos sin tener que pulsar «Buscar»."""
        added, removed = self.hardware.refresh()
        self.controls.refresh_joystick()
        if removed:
            self.flash("Mando desconectado: " + ", ".join(removed), 6)
        elif added:
            self.flash("Mando conectado: " + ", ".join(added), 4)

    def instructor(self, text, voice=True):
        self.messages.append((text, time.time()))
        if voice and voice != "callout":
            self.voice.say(text, key=text[:40], min_gap=3.0)

    def screenshot(self):
        d = os.path.join(DATA, "capturas")
        os.makedirs(d, exist_ok=True)
        data = self.ctx.screen.read(components=3)
        img = pygame.image.frombytes(data, (self.W, self.H), "RGB", True)
        path = os.path.join(d, time.strftime("captura_%Y%m%d_%H%M%S.png"))
        pygame.image.save(img, path)
        self.flash("Captura guardada en datos/capturas")

    # ------------------------------------------------------------ pantalla de instrumentos (cabina física)
    INSTR_MODES = ("no", "ambiente", "unica", "segunda")
    INSTR_NAMES = {"no": "Pantalla normal", "ambiente": "Paisaje + instrumentos (sin cabina)",
                   "unica": "Solo instrumentos (esta pantalla)", "segunda": "Instrumentos en una segunda ventana"}

    # ------------------------------------------------------------ cabina en pantalla
    COCKPIT_MODES = ("auto", "2d", "3d", "none")
    COCKPIT_NAMES = {"2d": "Panel 2D", "3d": "Cabina 3D", "none": "Sin panel (solo paisaje)",
                     "franja": "Paisaje + franja de instrumentos"}

    def resolve_cockpit_style(self):
        """La cabina que se dibuja. En "auto", con la consola física conectada no se dibuja ningún mando: solo el
        paisaje si los instrumentos van en su propia pantalla (F2) o, si no, el paisaje con la franja de
        instrumentos debajo. Sin consola, el panel 2D, que se maneja con el ratón (interruptores, palancas,
        radios, G1000) y con el teclado o un joystick USB."""
        if self.cockpit_mode != "auto":
            return self.cockpit_mode
        if self.console_here():
            return "none" if self.instr_mode() in ("unica", "segunda") else "franja"
        return "2d"

    def gps_typing(self):
        """Se está escribiendo un punto en el GPS: la lista D→ / añadir está abierta y el mapa del G1000 a la vista
        (panel 2D de cristal). Si se cambia de vista, la lista se cierra y el teclado vuelve a los mandos."""
        g = self.panel.glass
        on_screen = self.panel.mode == "glass" and (self.cockpit_style == "2d" or self.console_here())
        if g.gps_typing() and not on_screen:      # con la consola, el G1000 está en la pantalla de instrumentos
            g.gps_page, g.gps_query = None, ""
        return g.gps_typing()

    def console_here(self):
        """La consola física está conectada y es la de este avión (solo reproduce la cabina del C172S)."""
        return self.hardware.console_connected() and self.hardware.applies_to(self.world.ac.t.id)

    def instr_mode(self):
        """Pantalla de instrumentos efectiva. «Franja» y «solo instrumentos» son para volar con la consola física:
        con un avión que no es el suyo se vuela con el panel 2D, así que esta pantalla vuelve a la normal."""
        mode = self.settings.get("pantalla_instr", "no")
        if mode in ("ambiente", "unica") and not self.hardware.applies_to(self.world.ac.t.id):
            return "no"
        return mode

    def apply_instrument_screen(self):
        """Abre o cierra la ventana de instrumentos según el ajuste."""
        mode = self.settings.get("pantalla_instr", "no")
        if mode == "segunda" and self.instr_win is None:
            sizes = pygame.display.get_desktop_sizes()
            k = int(self.settings.get("monitores_paisaje", 1) or 1) if getattr(self, "_span", False) else 1
            if len(sizes) > k:
                # el monitor siguiente a los del paisaje: ventana sin bordes que lo ocupa entero
                w2, h2 = sizes[k]
                self.instr_win = pygame.Window("AeroEscuela — Instrumentos", (w2, h2),
                                               position=(sum(s[0] for s in sizes[:k]), 0), borderless=True)
            else:
                w2, h2 = int(sizes[0][0] * 0.55), int(sizes[0][1] * 0.55)
                self.instr_win = pygame.Window("AeroEscuela — Instrumentos", (w2, h2), resizable=True)
        elif mode != "segunda" and self.instr_win is not None:
            self.instr_win.destroy()
            self.instr_win = None

    def cycle_instrument_screen(self):
        modes = self.INSTR_MODES
        cur = self.settings.get("pantalla_instr", "no")
        self.settings["pantalla_instr"] = modes[(modes.index(cur) + 1) % len(modes)] if cur in modes else "no"
        self.apply_instrument_screen()
        self._amb_view = None
        self.flash(self.INSTR_NAMES[self.settings["pantalla_instr"]], 2.0)

    def draw_instrument_window(self):
        win = self.instr_win
        if win is None:
            return
        surf = win.get_surface()
        if self.state in ("flight", "pause", "instructor"):
            self.instr_display.draw(surf, self.world, self.panel)
        else:
            surf.fill((6, 6, 7))
            self.fonts.blit(surf, "AeroEscuela · instrumentos", (surf.get_width() / 2, surf.get_height() / 2), 24,
                            COL["grey"], bold=True, anchor="center")
        win.flip()

    # ------------------------------------------------------------ alumnos e informes
    def select_student(self, name):
        self.student = name
        self.settings["alumno"] = name
        self.progress = self.students.load(name)
        self.save_settings()
        self.flash(f"Alumno: {name}", 2)

    def make_flight_report(self):
        from .students import flight_report, open_file
        L = self.lesson
        w = self.world
        d = os.path.join(DATA, "informes")
        p = os.path.join(d, time.strftime(f"vuelo_%Y%m%d_%H%M%S_{self.students.path(self.student).split(os.sep)[-1][:-5]}.html"))
        extra = []
        atc = w.atc
        if atc.engaged or atc.violations:
            extra.append("Radio (ATC): " + ("; ".join(atc.violations) if atc.violations else "comunicaciones correctas"))
        for name, txt, ok in w.emerg.report():
            extra.append(f"Emergencia — {name}: {txt}")
        self.flight_report_path = flight_report(
            p, self.student, L.title if L else "Vuelo libre", w.ac.t.name, w.place_name, self.result,
            self.recorder.array(), self.recorder.FIELDS, getattr(self, "debrief_flight_s", 0.0),
            getattr(self, "debrief_landings", 0), extra)
        open_file(self.flight_report_path)

    def make_student_report(self):
        from .students import open_file, student_report
        p = os.path.join(DATA, "informes", f"ficha_{self.students.path(self.student).split(os.sep)[-1][:-5]}.html")
        open_file(student_report(p, self.progress, LESSONS))

    # ------------------------------------------------------------ puesto del instructor en red
    def apply_remote(self):
        from .instructor_web import InstructorServer
        on = bool(self.settings.get("instructor_red"))
        if on and self.remote is None:
            self.remote = InstructorServer()
            self.remote.start()
            if self.remote.error:
                self.flash(self.remote.error, 5)
                self.remote = None
                self.settings["instructor_red"] = False
        elif not on and self.remote is not None:
            self.remote.stop()
            self.remote = None

    # ------------------------------------------------------------ salida de datos UDP
    def apply_udp(self):
        from .udp_out import UdpOut
        st = self.settings
        if self.udp is not None:
            self.udp.stop()
            self.udp = None
        if st.get("udp_salida"):
            try:
                self.udp = UdpOut(str(st.get("udp_destino") or "127.0.0.1"), int(st.get("udp_puerto") or 49020),
                                  int(st.get("udp_hz") or 30))
            except (OSError, ValueError) as ex:
                self.flash(f"No se pudo abrir la salida UDP: {ex}", 5)
                st["udp_salida"] = False

    # ------------------------------------------------------------ simulador de ATC externo
    def apply_atc_link(self):
        from .atc_link import AtcBridge
        on = bool(self.settings.get("atc_externo"))
        if on and self.atc_bridge is None:
            b = AtcBridge(self, int(self.settings.get("atc_externo_puerto", 8770) or 8770),
                          str(self.settings.get("atc_externo_codigo", "") or ""))
            if b.error:
                self.flash(b.error, 5)
                self.settings["atc_externo"] = False
                return
            self.atc_bridge = b
        elif not on and self.atc_bridge is not None:
            self.atc_bridge.stop()
            self.atc_bridge = None

    def update_atc_link(self, dt):
        b = self.atc_bridge
        if b is None:
            return
        b.update(dt)
        ptt = bool(self.voice_in.listening)
        if ptt != self._ptt_prev:
            b.ptt(ptt)
        self._ptt_prev = ptt

    def _remote_catalog(self):
        from sim.emergencies import TRIGGERS
        from sim.world import POSITIONS
        from .screens import WEATHER_PRESETS
        return dict(lecciones=[dict(id=c.id, titulo=c.title, cat=c.category, acs=c.acs) for c in LESSONS],
                    posiciones=list(POSITIONS.items()), disparadores=TRIGGERS,
                    presets=[n for n, _ in WEATHER_PRESETS])

    def _remote_status(self):
        from sim.emergencies import CATALOG
        w = self.world
        ac = w.ac
        s = ac.sys
        L = self.lesson
        wx = w.weather
        pend = {e["key"] for e in w.emerg.plan if not e["fired"]}
        st = L.step if (L is not None and hasattr(L, "step") and not isinstance(L, FreeFlight)) else None
        res = None
        if L is not None and L.done and not isinstance(L, FreeFlight):
            R = L.result(w)
            res = dict(nota=R["score"], calif=R["grade"], apto=R["passed"],
                       items=[[str(a), b, c, str(d)] for a, b, c, d in R["items"]])
        pistas = []
        for apt in w.airports:
            for rw in apt.runways:
                pistas.append([float(rw.threshold[0]), float(rw.threshold[1]), float(rw.far_end[0]), float(rw.far_end[1])])
        tag = {"yo": "Alumno", "atc": "ATC", "ia": "Tráfico", "atis": "ATIS"}
        return dict(
            leccion=L.title if L is not None else "", estado={"flight": "en vuelo", "pause": "PAUSA", "instructor": "instructor",
                                                             "debrief": "informe", "menu": "menú", "replay": "repetición"}.get(self.state, self.state),
            choque=ac.crashed, ias=float(w.ind.ias), alt=float(w.ind.alt_ft), hdg=float(ac.heading), hdg_mag=float(w.mag(ac.heading)), vs=float(w.ind.vs_fpm),
            rpm=float(s.engine.rpm), fuel=float(s.fuel_l), x=float(ac.pos[0]), y=float(ac.pos[1]),
            paso=(f"Paso {L.idx + 1}/{len(L.steps)}: {st.text}" if st is not None else ""),
            fallas=[dict(k=k, nombre=n, activa=bool(s.failures.get(k)), prog=k in pend) for k, n, ok in CATALOG if ok(ac.t)],
            emergencias=[list(r) for r in w.emerg.report()],
            radio=[[tag.get(who, who), txt] for who, txt, _ in list(self.radio_log)[-8:]],
            resultado=res, pistas=pistas, congelado=sorted(w.frozen), ritmo=w.sim_rate,
            ruta=[[float(p[0]), float(p[1])] for p in w.route] if w.route else None,
            trafico=[[float(p.pos[0]), float(p.pos[1])] for p in w.traffic.planes],
            meteo=dict(wind_dir=wx.wind_dir, wind_kt=wx.wind_kt, gust_kt=wx.gust_kt, visibility_m=wx.visibility_m,
                       cloud_base_ft=wx.cloud_base_ft, cloud_cover=wx.cloud_cover, turbulence=wx.turbulence, hour=wx.hour,
                       dew_spread=wx.dew_spread,
                       texto=wx.describe()))

    def update_remote(self, dt):
        r = self.remote
        if r is None:
            return
        for c in r.pending():
            try:
                self._remote_cmd(c)
            except Exception as ex:
                print("Orden del instructor fallida:", c, ex)
        self._remote_t -= dt
        if self._remote_t <= 0:
            self._remote_t = 0.4
            r.publish(self._remote_status(), self._remote_catalog() if not r.catalog else None)

    def _remote_cmd(self, c):
        from sim.lessons import LESSONS_BY_ID
        from .screens import WEATHER_PRESETS
        w = self.world
        s = w.ac.sys
        k = c.get("c")
        if k == "pausa":
            self.state = "pause" if self.state == "flight" else ("flight" if self.state in ("pause", "instructor") else self.state)
        elif k == "reiniciar":
            self.restart_lesson()
        elif k == "leccion" and c.get("id") in LESSONS_BY_ID:
            self.start_lesson(LESSONS_BY_ID[c["id"]])
            self.flash("El instructor ha iniciado: " + self.lesson.title, 3)
        elif k == "posicion":
            self.start_lesson(FreeFlight(c.get("id", "pista")))
        elif k == "falla":
            key = c.get("k")
            pend = [e for e in w.emerg.plan if e["key"] == key and not e["fired"]]
            if s.failures.get(key):
                s.failures[key] = False
                if key == "fire":
                    s.fire_level = 0.0
            elif pend:
                w.emerg.plan = [e for e in w.emerg.plan if e not in pend]
            else:
                w.emerg.schedule(key, c.get("cuando", "ahora"))
        elif k == "reparar":
            for f in s.failures:
                s.failures[f] = False
            for en in s.engines:
                en.carb_ice = 0.0
            w.emerg.plan = []
            s.fire_level = s.smoke_level = 0.0
            s.gear_emergency = False
            s.trim_cb = True
        elif k == "clima":
            wx = w.weather
            for f in ("wind_dir", "wind_kt", "gust_kt", "visibility_m", "cloud_base_ft", "cloud_cover", "turbulence", "hour",
                      "dew_spread"):
                v = c.get(f)
                if isinstance(v, (int, float)) and v == v:
                    setattr(wx, f, float(v))
            wx.cloud_top_ft = max(wx.cloud_top_ft, wx.cloud_base_ft + 800)
        elif k == "preset":
            from .screens import apply_weather_preset
            for n, pr in WEATHER_PRESETS:
                if n == c.get("nombre"):
                    apply_weather_preset(w, pr)
        elif k == "metar":
            self.apply_live_weather()
        elif k == "congelar" and c.get("k") in w.FREEZES:
            w.freeze(c["k"], bool(c.get("on")))
        elif k == "ritmo":
            if not w.set_rate(c.get("x")):
                self.flash("El tiempo solo se acelera en vuelo, por encima de 500 ft", 3)
        elif k == "mover":
            num = lambda f: float(c[f]) if isinstance(c.get(f), (int, float)) and c[f] == c[f] else 0.0
            w.slew(clamp(num("n"), -50, 50), clamp(num("e"), -50, 50), clamp(num("alt"), -10000, 10000),
                   clamp(num("hdg"), -180, 180))

    # ------------------------------------------------------------ meteorología real (METAR)
    def apply_live_weather(self):
        from sim.metar import LiveWeather
        loc = self.world.location
        if not hasattr(self, "live_wx"):
            self.live_wx = LiveWeather()
        if loc is None:
            self.flash("La meteorología real solo está disponible en aeropuertos reales (Ubicación)", 4)
            return
        self.live_wx.start(loc.get("ident"), loc.get("lat0"), loc.get("lon0"))
        self.flash("Descargando el METAR…", 2)

    def poll_live_weather(self):
        lw = getattr(self, "live_wx", None)
        if lw is None:
            return
        m, err = lw.poll()
        if err:
            self.flash(err, 4)
        elif m:
            from sim.metar import apply
            raw = apply(self.world.weather, m, self.world.home.elev / FT)
            self.world.select_runway()
            self.flash("METAR: " + raw, 6)
            self.instructor("Meteorología real cargada: " + raw, voice=False)

    # ------------------------------------------------------------ radio y tráfico
    def configure_world(self):
        w = self.world
        w.atc.callsign = (self.settings.get("indicativo") or "EC-AES").upper()
        w.buildings_3d = bool(self.settings.get("edificios_3d", False))
        w.atc.enabled = bool(self.settings.get("atc", True))
        w.traffic.enabled = bool(self.settings.get("trafico", True))
        if not w.traffic.enabled:
            w.traffic.planes = []

    def radio_select(self, i):
        opts = self.world.atc.options()
        if 0 <= i < len(opts):
            opts[i][2]()

    def push_to_talk(self):
        """Pulsar para hablar: escucha una transmisión del menú de radio por el micrófono."""
        atc = self.world.atc
        opts = atc.options()
        if not opts:
            self.flash("No hay nada que transmitir ahora", 1.5)
            return
        self.voice_in.listen(opts, atc.callsign, atc.facility()[0])

    def poll_voice_input(self):
        r = self.voice_in.poll()
        if r is None:
            return
        idx, txt = r
        if idx is None:
            self.instructor(txt, voice=False)
        else:
            self.radio_select(idx)

    def radio_tune(self, station):
        f = self.world.freqs.get(station)
        if f:
            self.world.com_standby = self.world.com_freq
            self.world.com_freq = f
            self.flash(f"COM1 {f:.3f} — " + {"TWR": "Torre", "GND": "Rodadura", "ATIS": "ATIS"}[station], 1.5)

    def update_radio(self):
        w = self.world
        atc = w.atc
        for m in atc.out:
            self.radio.submit(m)
        atc.out.clear()
        for h in atc.hints:
            self.instructor(h, voice=False)
        atc.hints.clear()

        def started(msg, dur):
            self.radio_log.append((msg.who, msg.disp, time.time()))
            self.radio_now = (msg, time.time() + dur + 1.5)
        self.radio.update(started)
        # aviso de tráfico del TAS ("Tráfico, tráfico")
        ta = w.traffic.ta_alert is not None
        if ta and not self.ta_prev:
            self.voice.say("Tráfico, tráfico", key="ta", min_gap=15.0)
        self.ta_prev = ta

    # ------------------------------------------------------------ vuelo
    # ------------------------------------------------------------ ubicaciones
    def switch_world(self, loc):
        """Sustituye el mundo y el renderizador (ubicación real o escenario escuela)."""
        aid = self.world.ac.t.id
        wx = self.world.weather
        self._loading("Construyendo el escenario…", 0.95)
        self.world = World(aid, location=loc)
        self.world.weather.copy_from(wx)
        self.configure_world()
        self.world.reposition("pista")
        self.renderer = Renderer(self.ctx, self.world, (self.W, self.H), progress=lambda m: self._loading(m, 0.97))
        self.apply_quality()
        self.panel.glass.map_img = None
        self.panel.glass.map_key = None
        self.panel.glass.track = []
        self.settings["ubicacion"] = loc["ident"] if loc else ""
        self.save_settings()
        self.flash(self.world.place_name, 3.0)

    def load_location(self, code):
        """Carga un aeropuerto real en segundo plano (descarga relieve e imágenes la primera vez)."""
        import threading
        if not code:
            self.switch_world(None)
            return
        job = dict(code=code, msg="Preparando…", frac=0.0, result=None, error=None, done=False)

        def prog(m, f):
            job["msg"], job["frac"] = m, f

        def run():
            try:
                job["result"] = geo.build_location(code, DATA, progress=prog, db=self.geo_db)
            except Exception as ex:
                job["error"] = str(ex)
            job["done"] = True
        threading.Thread(target=run, daemon=True).start()
        self.loc_job = job

    def poll_location(self):
        job = self.loc_job
        if job is None or not job["done"]:
            return
        self.loc_job = None
        if job["error"]:
            self.flash("No se pudo cargar: " + job["error"], 6)
        else:
            self.switch_world(job["result"])

    def start_lesson(self, cls):
        """cls: clase de lección o una instancia de FreeFlight."""
        if not isinstance(cls, FreeFlight) and getattr(cls, "school_only", False) and not self.world.is_school:
            self.switch_world(None)
            self.flash("Esta lección usa el escenario escuela", 4)
        need = None if isinstance(cls, FreeFlight) else getattr(cls, "location", None)
        if need and (self.world.location or {}).get("ident") != need:
            # misión en un aeropuerto real concreto: se carga (la primera vez se descarga)
            try:
                loc = geo.build_location(need, DATA, progress=lambda m, f: self._loading(m, f), db=self.geo_db)
                self.switch_world(loc)
            except Exception as ex:
                self.flash(f"No se pudo cargar {need}: {ex}", 6)
                return
        L = cls if isinstance(cls, FreeFlight) else cls()
        self.lesson_cls = None if isinstance(cls, FreeFlight) else cls
        self.lesson = L
        if getattr(L, "aircraft", None) and not isinstance(L, FreeFlight):
            if self.world.aircraft_id != L.aircraft:
                self.world.set_aircraft(L.aircraft)
        if self.world.ac.t.default_cockpit == "glass":
            self.panel.mode = "glass"
        elif self.console_here():
            from .hardware import CONSOLE_COCKPIT
            self.panel.mode = CONSOLE_COCKPIT        # la consola física reproduce el tablero del C172S (G1000)
        # cada vuelo empieza con el GPS sin plan y el CDI en VLOC (la lección puede cambiarlo en setup)
        self.world.gps.clear()
        self.world.cdi_src = "VLOC"
        L.setup(self.world)
        self.world.sim_time = 0.0
        self.world.events.clear()
        self.recorder.clear()
        self.messages.clear()
        self.result = None
        self.state = "flight"
        self.camera.set_mode("cabina")
        self.camera.head_yaw = 0.0
        self.cockpit_style = self.resolve_cockpit_style()
        self.camera.head_pitch = math.radians(-12 if self.cockpit_style == "3d" else -10)
        self._amb_view = None           # la franja de instrumentos vuelve a encuadrar la vista al frente
        self.flight_time_start = self.world.stats["flight_time"]
        self.landings_start = self.world.stats["landings"]
        self.auto_start = None
        self.crash_t = None
        self.done_t = None
        self.panel.glass.track = []
        self.voice.stop()
        self.radio.clear()
        self.radio_log.clear()
        self.radio_now = None
        self.configure_world()
        self.world.traffic.reset()
        self.world.atc.reset()
        self.show_check = bool(getattr(L, "checklist", None))
        self.hardware.request_sync()
        if self.hardware.console_connected() and not self.hardware.applies_to(self.world.ac.t.id):
            self.flash(f"La consola física es del Cessna 172S: el {self.world.ac.t.short} se vuela con teclado, "
                       "ratón y el panel 2D", 6)

    def lesson_scene_switch(self):
        """Misión de dos escenarios: carga en vuelo el siguiente aeropuerto real (crucero acelerado) y sigue la lección."""
        L = self.lesson
        code, L.switch_to = L.switch_to, None
        try:
            loc = geo.build_location(code, DATA, progress=lambda m, f: self._loading("Crucero acelerado · " + m, f),
                                     db=self.geo_db)
        except Exception as ex:
            self.flash(f"No se pudo cargar {code}: {ex}", 6)
            return
        self.switch_world(loc)
        L.arrive(self.world)
        self.world.events.clear()
        self.world.traffic.reset()
        self.world.atc.reset()
        self.panel.glass.track = []
        self.radio_log.clear()
        self._fade_t = time.time()

    def restart_lesson(self):
        if self.lesson is None:
            return
        if isinstance(self.lesson, FreeFlight):
            self.start_lesson(FreeFlight(self.lesson.start))
        else:
            self.start_lesson(self.lesson_cls)

    def end_flight(self):
        """Termina el vuelo y abre el análisis posterior."""
        # retardo interno medido en este vuelo, para la guía de pruebas
        self.latency.report(os.path.join(DATA, "retardo.json"), fps=self.fps, avion=self.world.ac.t.short,
                            resolucion=f"{self.W}x{self.H}", calidad=self.settings.get("calidad", "auto"))
        L = self.lesson
        flight_s =self.world.stats["flight_time"] - self.flight_time_start
        landings = self.world.stats["landings"] - self.landings_start
        if L is not None and not isinstance(L, FreeFlight):
            if not L.done:
                L.finish(False, "Vuelo terminado por el alumno", self.world)
            self.result = L.result(self.world)
        else:
            self.result = None
        title = L.title if L else "Vuelo libre"
        lid = L.id if L else "libre"
        self.progress.record(lid, title, self.world.ac.t.short, self.result, flight_s, landings)
        self.debrief_flight_s = flight_s
        self.debrief_landings = landings
        self.flight_report_path = None
        self.audio.silence()
        self.state = "debrief"

    def _auto_start_step(self, dt):
        a = self.auto_start
        if a is None:
            return
        s = self.world.ac.sys
        a["t"] += dt
        t = a["t"]
        if t > 0.2:
            s.master = True
            s.lights["beacon"] = True
        for e in s.engines:
            if t > 0.6:
                e.mixture = 1.0
                e.throttle = max(e.throttle, 0.12) if e.throttle < 0.3 else e.throttle
            if t > 1.0:
                e.magnetos = 3
            if 1.4 < t:
                e.starter = not e.running
        if all(e.running for e in s.engines) and t > 1.4:
            for e in s.engines:
                e.starter = False
            s.avionics = True
            s.lights["nav"] = True
            self.auto_start = None
            self.flash("Motor en marcha")
        if t > 12:
            for e in s.engines:
                e.starter = False
            self.auto_start = None
            self.flash("El motor no arranca: revise combustible y mezcla")

    def flight_keys(self, ev):
        w = self.world
        ac = w.ac
        s = ac.sys
        k = ev.key
        mods = pygame.key.get_mods()
        ctrl = mods & pygame.KMOD_CTRL
        shift = mods & pygame.KMOD_SHIFT
        if self.show_radio and pygame.K_1 <= k <= pygame.K_9 and not ctrl:
            self.radio_select(k - pygame.K_1)
            return
        if self.gps_typing() and not ctrl:
            # lista D→ / añadir abierta: Enter, Retroceso y Esc van al GPS; los caracteres llegan como TEXTINPUT
            # (así también escribe el teclado en pantalla de Windows) y aquí solo se impide que muevan el avión
            if self.panel.glass.gps_key(w.gps, k, ""):
                return
            if ev.unicode and (ev.unicode.isalnum() or ev.unicode in " -"):
                return
        if k == pygame.K_ESCAPE:
            if self.show_help or self.show_check or self.show_radio or self.show_controls:
                self.show_help = self.show_check = self.show_radio = self.show_controls = False
                self.panel.starter_held = False
            else:
                self.state = "pause"
                self.audio.silence()
        elif k == pygame.K_5 and not ctrl:
            self.camera.toggle_instrument_view()
        elif k in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4) and not ctrl:
            self.camera.set_mode(MODES[k - pygame.K_1])
            self.flash(MODE_NAMES[self.camera.mode], 1.2)
        elif k == pygame.K_TAB:
            self.panel.mode = "glass" if self.panel.mode == "analog" else "analog"
            self.settings["cabina"] = self.panel.mode
        elif k == pygame.K_p:
            # automática → panel 2D → cabina 3D → sin panel
            order = self.COCKPIT_MODES
            self.cockpit_mode = order[(order.index(self.cockpit_mode) + 1) % len(order)]
            self.settings["cabina_estilo"] = self.cockpit_mode
            self.cockpit_style = self.resolve_cockpit_style()
            self._amb_view = None
            name = self.COCKPIT_NAMES[self.cockpit_style]
            self.flash(("Automática: " + name) if self.cockpit_mode == "auto" else name, 1.5)
        elif k == pygame.K_y:
            self.show_yoke = not self.show_yoke
            self.flash("Volante " + ("visible" if self.show_yoke else "oculto"), 1.0)
        elif k == pygame.K_h:
            self.show_help = not self.show_help
        elif k == pygame.K_k:
            self.show_check = not self.show_check
        elif k == pygame.K_t:
            self.show_radio = not self.show_radio
        elif k == pygame.K_RCTRL:
            self.push_to_talk()
        elif k == pygame.K_F2:
            self.cycle_instrument_screen()
        elif k == pygame.K_F3:
            self.toggle_instr_editor()
        elif k == pygame.K_DELETE and self.instr_display.editing:
            self.instr_display.reset_selected()
        elif k == pygame.K_f:
            s.flaps_cmd = min(s.flaps_cmd + 1, len(ac.t.flap_settings) - 1)
            self.flash(f"Flaps {ac.t.flap_settings[s.flaps_cmd]}°", 1.2)
        elif k == pygame.K_v:
            s.flaps_cmd = max(s.flaps_cmd - 1, 0)
            self.flash(f"Flaps {ac.t.flap_settings[s.flaps_cmd]}°", 1.2)
        elif k == pygame.K_b:
            s.parking_brake = not s.parking_brake
            self.flash("Freno de estacionamiento " + ("PUESTO" if s.parking_brake else "QUITADO"), 1.5)
        elif k == pygame.K_g and shift and ac.t.retractable:
            self.flash(w.emerg.gear_emergency(), 2.5)
        elif k == pygame.K_g and ac.t.retractable:
            s.gear_down = not s.gear_down
            self.flash("Tren " + ("ABAJO" if s.gear_down else "ARRIBA"), 1.5)
        elif k == pygame.K_l:
            s.lights["landing"] = not s.lights["landing"]
            s.lights["nav"] = s.lights["nav"] or s.lights["landing"]
            self.flash("Luz de aterrizaje " + ("encendida" if s.lights["landing"] else "apagada"), 1.2)
        elif k == pygame.K_z and s.failures.get("trim") and s.trim_cb:
            # el botón de desconexión del PA también corta el compensador eléctrico desbocado
            w.ap.disengage("")
            self.flash(w.emerg.trim_disconnect(), 2.5)
        elif k == pygame.K_z:
            w.ap.toggle(ac)
            self.flash("Piloto automático " + ("CONECTADO" if w.ap.engaged else "desconectado"), 1.5)
        elif k == pygame.K_x:
            w.ap.set_hdg(ac)
        elif k == pygame.K_c:
            w.ap.set_alt(ac)
        elif k in (pygame.K_COMMA, pygame.K_PERIOD):
            d = (1 if shift else 5) * (-1 if k == pygame.K_COMMA else 1)
            w.ap.hdg_bug = (w.ap.hdg_bug + d) % 360
            self.flash(f"Rumbo seleccionado {w.ap.hdg_bug:03.0f}°", 1.0)
        elif k == pygame.K_e and ctrl:
            self.start_engine_auto()
        elif k == pygame.K_r and ctrl:
            self.restart_lesson()
        elif k == pygame.K_r:
            self.enter_replay()
        elif k == pygame.K_i:
            self.state = "instructor"
            self.audio.silence()
        elif k == pygame.K_F12 or k == pygame.K_PRINTSCREEN:
            self.screenshot()
        elif k == pygame.K_F9:
            self.settings["mostrar_fps"] = not self.settings["mostrar_fps"]
        elif k == pygame.K_F7:
            w.cdi_src = "GPS" if w.cdi_src == "VLOC" else "VLOC"
            self.flash(f"CDI: {w.cdi_src}" + (" (GPS: plan de vuelo en el mapa del G1000)" if w.cdi_src == "GPS" else ""), 1.8)
        elif k == pygame.K_F6:
            if ac.t.carburetor:
                ac.sys.carb_heat = not ac.sys.carb_heat
                self.flash("Calefacción al carburador " + ("CONECTADA" if ac.sys.carb_heat else "quitada"), 1.5)
            else:
                self.flash("Este avión tiene inyección: no lleva calefacción al carburador", 2.0)

    def toggle_instr_editor(self):
        if self.instr_mode() in ("unica", "ambiente") or self.cockpit_style == "franja":
            self.instr_display.editing = not self.instr_display.editing
            self.save_settings()
            if self.instr_display.editing:
                self.flash("Arrastre cada instrumento con el ratón; la rueda cambia su tamaño", 3)
        else:
            self.flash("Mover instrumentos funciona en «Solo instrumentos» o «Paisaje + instrumentos» (botón Pantalla)", 3)

    def start_engine_auto(self):
        self.auto_start = dict(t=0.0)
        if self.lesson is not None and hasattr(self.lesson, "auto_start_used"):
            self.lesson.auto_start_used = True
        self.flash("Arranque automático…")

    def popups_open(self):
        return self.show_help or self.show_check or self.show_radio or self.show_controls

    # ------------------------------------------------------------ mundo continuo (rutas largas sin cortes)
    CONT_PREFETCH = 13000.0       # a esta distancia del centro del escenario se empieza a preparar el siguiente
    CONT_SWITCH = 18000.0         # aquí se cambia, si el siguiente está listo
    CONT_LIMIT = 23500.0          # borde: si aún no está listo, se espera (el paisaje real termina a 25,6 km)

    def continuous_enabled(self):
        L = self.lesson
        return (self.world.location is not None and L is not None
                and (isinstance(L, FreeFlight) or getattr(L, "continuous", False)))

    def _nearest_airport_code(self, lat, lon, max_km=40.0):
        db = self.geo_db
        best = None
        for b in db.airports.values():
            try:
                la, lo = float(b["latitude_deg"]), float(b["longitude_deg"])
            except ValueError:
                continue
            if abs(la - lat) > 0.4 or abs(lo - lon) > 0.4 or not db.runways.get(b["ident"].upper()):
                continue
            d = math.hypot((la - lat) * 111.3, (lo - lon) * 111.3 * math.cos(math.radians(lat)))
            if d < max_km and (best is None or d < best[0]):
                best = (d, b["ident"].upper())
        return best[1] if best else None

    def _cont_prefetch(self):
        import threading
        w = self.world
        ac = w.ac
        h = math.radians(ac.track if ac.gs > 5 else ac.heading)
        tla, tlo = w.location["proj"].to_geo(ac.pos[0] + math.cos(h) * 20000.0, ac.pos[1] + math.sin(h) * 20000.0)
        tla, tlo = float(tla), float(tlo)
        hint = None
        if hasattr(self.lesson, "scene_hint"):
            hint = self.lesson.scene_hint(w, (tla, tlo))
        job = dict(done=False, result=None, error=None, msg="Preparando el escenario siguiente…", frac=0.0)

        def prog(m, f):
            job["msg"], job["frac"] = m, f

        def run():
            try:
                if hint:
                    job["result"] = geo.build_location(hint, DATA, progress=prog, db=self.geo_db)
                else:
                    try:
                        job["result"] = geo.build_location(None, DATA, progress=prog, db=self.geo_db, center=(tla, tlo))
                    except ValueError:
                        code = self._nearest_airport_code(tla, tlo)
                        if code is None:
                            raise
                        job["result"] = geo.build_location(code, DATA, progress=prog, db=self.geo_db)
            except Exception as ex:
                job["error"] = str(ex)
            job["done"] = True
        threading.Thread(target=run, daemon=True).start()
        self.cont_job = job

    def update_continuous(self):
        """Devuelve True si este fotograma no debe avanzar la simulación (cambio de escenario o espera en el borde)."""
        self._cont_wait = None
        if not self.continuous_enabled():
            self.cont_job = None
            return False
        w = self.world
        ac = w.ac
        d = math.hypot(ac.pos[0], ac.pos[1])
        job = self.cont_job
        if job is None and d > self.CONT_PREFETCH and not ac.on_ground and time.time() > self._cont_retry:
            self._cont_prefetch()
            job = self.cont_job
        if job is not None and job["done"]:
            if job["error"]:
                self.cont_job = None
                self._cont_retry = time.time() + 15
                self.flash("No se pudo preparar el escenario siguiente: " + job["error"][:60], 4)
                return False
            loc = job["result"]
            la, lo = w.location["proj"].to_geo(ac.pos[0], ac.pos[1])
            n, e = loc["proj"].to_local(float(la), float(lo))
            dn = math.hypot(float(n), float(e))
            if dn > 21000 or (d > self.CONT_SWITCH and dn > d):
                self.cont_job = None              # el avión ya no va hacia ese escenario: se prepara otro
                return False
            if d > self.CONT_SWITCH or loc.get("ident") == getattr(self.lesson, "dest_ident", None) and dn < d - 3000:
                self.continue_in_scene(loc)
                return True
        if d > self.CONT_LIMIT and job is not None and not job["done"]:
            self._cont_wait = job
            return True
        return False

    def continue_in_scene(self, loc):
        from sim.world import transfer_to_scene
        self._loading("Escenario siguiente · " + loc["name"], 0.95)
        self.world = transfer_to_scene(self.world, loc)
        self.configure_world()
        self.renderer = Renderer(self.ctx, self.world, (self.W, self.H), progress=lambda m: self._loading(m, 0.97))
        self.apply_quality()
        self.panel.glass.map_img = None
        self.panel.glass.map_key = None
        self.panel.glass.track = []
        self.cont_job = None
        if hasattr(self.lesson, "on_scene_change"):
            self.lesson.on_scene_change(self.world)
        self.world.events.clear()
        self._fade_t = time.time()
        self.flash(f"Sobrevolando: {loc['name']}", 3.0)

    def update_flight(self, dt, events):
        w = self.world
        ac = w.ac
        for ev in events:
            if ev.type == pygame.KEYDOWN:
                self.flight_keys(ev)
            elif ev.type == pygame.TEXTINPUT and self.gps_typing():
                for ch in ev.text:
                    self.panel.glass.gps_key(w.gps, 0, ch)
            elif ev.type == pygame.MOUSEMOTION and ev.buttons[2]:
                self.camera.look(math.radians(ev.rel[0] * 0.25), math.radians(-ev.rel[1] * 0.25))
        if self.state != "flight":
            return
        keys = pygame.key.get_pressed()
        mods = pygame.key.get_mods()
        if mods & pygame.KMOD_CTRL:
            look = 1.6 * dt
            if keys[pygame.K_LEFT]:
                self.camera.look(-look, 0)
            if keys[pygame.K_RIGHT]:
                self.camera.look(look, 0)
            if keys[pygame.K_UP]:
                self.camera.look(0, look * 0.6)
            if keys[pygame.K_DOWN]:
                self.camera.look(0, -look * 0.6)
        if self.update_continuous():
            return
        w = self.world
        ac = w.ac
        self._auto_start_step(dt)
        self.hardware.update(dt, w, self)
        if self.state != "flight":
            return
        if self.auto_start is None:
            crank = self.panel.starter_held or bool(keys[pygame.K_INSERT])
            for en in ac.sys.engines:
                en.starter = crank and en.magnetos > 0 and not en.running
        # mandos a la frecuencia de fotograma; la física avanza a 240 Hz
        # mientras se escribe un identificador en el GPS, las letras no mueven palanca, pedales ni gases
        self.latency.mark_input()
        self.controls.update(dt, w, keys, mods, ui_wants_keys=self.gps_typing())
        ac.brake = max(ac.brake, self.hardware.brake_cmd)
        ac.brake_l, ac.brake_r = self.hardware.brake_l, self.hardware.brake_r   # frenos de pie: cada rueda
        sdt = dt * w.sim_rate            # tiempo simulado (el instructor puede acelerarlo)
        w.step(dt)
        evs = list(w.events)
        w.events.clear()
        for ev, data in evs:
            self.audio.on_event(ev, data)
            if ev == "ritmo_normal":
                self.flash("Tiempo a ritmo normal: cerca del suelo", 3)
            elif ev == "choque":
                self.instructor("¡Accidente! " + data["reason"])
                self.recorder.mark(w, data["reason"])
            elif ev == "contacto":
                self.recorder.mark(w, "contacto " + data.get("gear", ""))
        if w.ap.disconnect_alert > 2.4:
            self.audio.play("ap_off")
        if self.lesson is not None:
            self.lesson.update(sdt, w, evs)
            if getattr(self.lesson, "switch_to", None):
                self.lesson_scene_switch()
                return
            for text, voice in self.lesson.messages:
                if voice == "callout":
                    self.voice.say(text, key="co" + text, min_gap=2.0)
                else:
                    self.instructor(text, voice)
            self.lesson.messages.clear()
            if self.lesson.done and self.done_t is None:
                self.done_t = time.time()
        if ac.crashed and self.crash_t is None:
            self.crash_t = time.time()
        self.update_radio()
        self.poll_voice_input()
        self.recorder.sample(sdt, w)
        self.audio.update(w, self.camera.mode == "cabina")

    # ------------------------------------------------------------ repetición
    def enter_replay(self):
        a = self.recorder.array()
        if a is None or len(a) < 20:
            self.flash("Aún no hay datos para la repetición")
            return
        self.replay = dict(t=max(a[0, 0], a[-1, 0] - 60.0), t0=a[0, 0], t1=a[-1, 0], speed=1.0, paused=False,
                           prev_state=self.state, cam=self.camera.mode)
        self.camera.set_mode("exterior")
        self.audio.silence()
        self.state = "replay"

    def update_replay(self, dt, events):
        r = self.replay
        for ev in events:
            if ev.type == pygame.KEYDOWN:
                if ev.key in (pygame.K_ESCAPE, pygame.K_r):
                    self.camera.set_mode(r["cam"])
                    self.state = r["prev_state"] if r["prev_state"] != "flight" else "flight"
                    self.replay = None
                    return
                if ev.key == pygame.K_SPACE:
                    r["paused"] = not r["paused"]
                if ev.key == pygame.K_LEFT:
                    r["t"] = max(r["t0"], r["t"] - 10)
                if ev.key == pygame.K_RIGHT:
                    r["t"] = min(r["t1"], r["t"] + 10)
                if ev.key == pygame.K_UP:
                    r["speed"] = min(8.0, r["speed"] * 2)
                if ev.key == pygame.K_DOWN:
                    r["speed"] = max(0.25, r["speed"] / 2)
                if ev.key in (pygame.K_2, pygame.K_3, pygame.K_4):
                    self.camera.set_mode(MODES[ev.key - pygame.K_1])
            elif ev.type == pygame.MOUSEMOTION and ev.buttons[2]:
                self.camera.look(math.radians(ev.rel[0] * 0.25), math.radians(-ev.rel[1] * 0.25))
        if not r["paused"]:
            r["t"] += dt * r["speed"]
            if r["t"] >= r["t1"]:
                r["t"] = r["t1"]
                r["paused"] = True

    # ------------------------------------------------------------ bucle
    def run(self):
        last = time.perf_counter()
        frames = 0
        while self.running:
            now = time.perf_counter()
            dt = min(now - last, 0.1)
            last = now
            t_start = now
            events = pygame.event.get()
            for ev in events:
                if ev.type == pygame.QUIT:
                    self.running = False
                elif ev.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN):
                    self._mouse_t = time.time()
                elif ev.type == pygame.MOUSEWHEEL and self.state in ("flight", "replay"):
                    pass
                elif ev.type == pygame.JOYDEVICEREMOVED:
                    self.reload_joysticks()      # en seguida: no seguir leyendo un mando que ya no está
                elif ev.type == pygame.JOYDEVICEADDED:
                    self._joy_reload_t = now + 0.4    # Windows avisa uno a uno: se esperan los demás
            if self._joy_reload_t is not None and now >= self._joy_reload_t:
                self._joy_reload_t = None
                self.reload_joysticks()
            self.hardware.on_events(events)      # pulsos de las perillas giratorias de la consola, uno a uno
            for ev in events:
                if ev.type == pygame.WINDOWCLOSE and self.instr_win is not None and getattr(ev, "window", None) is self.instr_win:
                    self.settings["pantalla_instr"] = "no"
                    self.apply_instrument_screen()
            self.ui.begin(events)
            self.update_remote(dt)
            self.update_atc_link(dt)
            if self.udp is not None:
                self.udp.update(dt, self)
            self.frame(dt, events)
            pygame.display.flip()
            self.latency.mark_frame()            # retardo interno: mandos leídos → imagen entregada
            self.draw_instrument_window()
            self._pace(time.perf_counter() - t_start, dt)
            self.clock.tick(self.fps_cap)
            self.fps = self.fps * 0.95 + 0.05 / max(dt, 1e-3)
            frames += 1
            if self.autotest and self.autotest(self, frames):
                break
        self.save_settings()
        if self.udp is not None:
            self.udp.stop()
        if self.atc_bridge is not None:
            self.atc_bridge.stop()
        self.voice.stop()
        pygame.quit()

    def _pace(self, work, dt):
        """Limitador adaptativo: si el equipo no sostiene 60 FPS se fija a 30 FPS estables
        (un ritmo uniforme se ve fluido; uno irregular se ve tembloroso)."""
        mode = self.settings.get("fluidez", "auto")
        if mode == "60":
            self.fps_cap = 60
            return
        if mode == "30":
            self.fps_cap = 30
            return
        self._work_avg = self._work_avg * 0.95 + work * 1000 * 0.05
        # resolución dinámica: antes de bajar a 30 FPS se reduce un poco la resolución del paisaje 3D
        # (hasta el 65 % de la elegida) y se recupera cuando sobra tiempo
        base = self.QUALITY[self.quality_level()][0]
        lo = base * 0.65
        r = self.renderer
        self._res_timer = getattr(self, "_res_timer", 0.0) + dt
        if self.state == "flight" and self._res_timer > 1.2:
            if self.fps_cap == 60 and self._work_avg > 14.0 and r.rscale > lo + 0.01:
                r.set_quality(max(lo, r.rscale - 0.07), r.samples)
                self._res_timer = 0.0
                self._cap_timer = 0.0
                return
            if self._work_avg < 10.5 and r.rscale < base - 0.01:
                r.set_quality(min(base, r.rscale + 0.05), r.samples)
                self._res_timer = 0.0
        if self.fps_cap == 60 and self._work_avg > 15.5 and r.rscale > lo + 0.01 and self.state == "flight":
            return
        if self.fps_cap == 60 and self._work_avg > 15.5:
            self._cap_timer += dt
            if self._cap_timer > 1.5:
                self.fps_cap, self._cap_timer = 30, 0.0
        elif self.fps_cap == 30 and self._work_avg < 10.0:
            self._cap_timer += dt
            if self._cap_timer > 6.0:
                self.fps_cap, self._cap_timer = 60, 0.0
        else:
            self._cap_timer = 0.0

    def _ui_events(self):
        """Transición suave al cambiar de pantalla y sonidos al abrir o cerrar ventanas y al aparecer avisos."""
        key = (self.state, getattr(self, "menu_page", ""), getattr(self.instr_display, "editing", False))
        prev = getattr(self, "_ui_key", None)
        if prev is not None and key != prev and not (prev[0] == "flight" and key[0] == "flight"):
            self._fade_t = time.time()
            self.audio.play("ui_open" if key[0] in ("pause", "instructor", "debrief", "menu") else "ui_close", 0.8)
        self._ui_key = key
        pops = (self.show_radio, self.show_check, self.show_help)
        prevp = getattr(self, "_pops", pops)
        for a, b in zip(prevp, pops):
            if a != b:
                self.audio.play("ui_open" if b else "ui_close", 0.8)
                break
        self._pops = pops
        if self.state == "flight":
            s = self.world.ac.sys
            alert = bool(s.fire_level > 0.01 or s.smoke_level > 0.05 or s.failures.get("door") or self.world.ac.crashed)
            if alert and not getattr(self, "_alert_prev", False):
                self.audio.play("ui_alert", 1.0)
            self._alert_prev = alert

    def _draw_fade(self):
        t0 = getattr(self, "_fade_t", None)
        if t0 is None:
            return
        k = (time.time() - t0) / 0.35
        if k >= 1:
            self._fade_t = None
            return
        a = int(230 * (1 - k) ** 2)
        veil = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
        veil.fill((2, 8, 16, a))
        y = int(self.H * k)
        pygame.draw.line(veil, (0, 220, 255, min(255, a + 40)), (0, y), (self.W, y), 2)
        self.overlay.blit(veil, (0, 0))

    def frame(self, dt, events):
        self.overlay.fill((0, 0, 0, 0))
        self._ui_events()
        self.poll_location()
        self.poll_live_weather()
        st = self.state
        if st == "flight":
            self.update_flight(dt, events)
            self.draw_flight(dt)
        elif st == "pause":
            self.hardware.update(0.0, self.world, self)       # el botón de pausa también reanuda
            self.draw_flight(0.0, paused=True)
            self.screen_pause(events)
        elif st == "instructor":
            self.draw_flight(0.0, paused=True)
            self.screen_instructor(events)
        elif st == "replay":
            self.update_replay(dt, events)
            self.draw_replay(dt)
        elif st == "debrief":
            self.draw_menu_scene(dt)
            self.screen_debrief(events)
        else:
            self.draw_menu_scene(dt)
            self.screen_menu(events)
        if self.loc_job is not None:
            self.draw_loc_progress()
        if not self.world.is_school and st in ("menu", "flight", "debrief"):
            self.fonts.blit(self.overlay, geo.ATTRIBUTION, (12, self.H - 18), 11, (225, 230, 235),
                            anchor="topleft") if st != "flight" or self.camera.mode != "cabina" else None
        self.ui.draw_tooltip(self.overlay)
        if self.flash_msg and time.time() < self.flash_msg[1]:
            self.draw_toast(self.flash_msg[0], self.flash_msg[1] - time.time())
        w = self.world
        if st in ("flight", "pause") and (w.frozen or w.sim_rate > 1):
            parts = (["CONGELADO: " + ", ".join(w.FREEZES[k] for k in w.frozen)] if w.frozen else []) + \
                    ([f"TIEMPO ×{w.sim_rate}"] if w.sim_rate > 1 else [])
            txt = "   ·   ".join(parts)
            tw, th = self.fonts.get(14, True).size(txt)
            chip = pygame.Rect(0, 0, tw + 28, th + 12)
            chip.midtop = (self.W / 2, 4 if not (self._bar_rect is not None and self._bar_visible())
                           else self._bar_rect.bottom + 6)
            panel_box(self.overlay, chip, 8, (40, 30, 6, 225), border=(255, 200, 60))
            self.fonts.blit(self.overlay, txt, chip.center, 14, COL["yellow"], bold=True, anchor="center")
        covered = self.show_help or self.show_controls or self.state == "debrief"   # paneles grandes encima
        if self.settings.get("mostrar_fps") and not covered:
            st = self.latency.stats()
            txt = f"{self.fps:4.0f} FPS" + (f"  ·  retardo interno {st[0]:.0f} ms (95 %: {st[1]:.0f}) · peor caso "
                                             f"{self.latency.worst_case(st[1], self.fps):.0f} ms" if st else "")
            scene = getattr(self, "_scene_rect", None) if self.state in ("flight", "pause") else None
            scene = scene or pygame.Rect(0, 0, self.W, self.H)
            tw, th = self.fonts.get(12).size(txt)
            chip = pygame.Rect(0, 0, tw + 20, th + 8)
            chip.bottomright = (scene.right - 10, scene.bottom - 8)
            panel_box(self.overlay, chip, 6, (6, 14, 24, 200), border=None)
            self.fonts.blit(self.overlay, txt, chip.center, 12, (170, 200, 220), anchor="center")
        self._draw_fade()
        self.renderer.draw_overlay(self.overlay)

    # ------------------------------------------------------------ dibujo de vuelo
    def panel_height(self):
        return int(self.H * (0.45 if self.panel.mode == "glass" else 0.40))

    def _mouse_ray_body(self):
        """Rayo del ratón en ejes del avión (para pulsar el tablero 3D)."""
        r = self.renderer
        if r.last_view is None:
            return None
        x, y, w, h = r.last_viewport
        mx, my = self.ui.mouse
        nx = 2.0 * (mx - x) / w - 1.0
        ny = 1.0 - 2.0 * (my - (self.H - y - h)) / h
        inv = np.linalg.inv(r.last_proj @ r.last_view)
        p0 = inv @ np.array([nx, ny, -1.0, 1.0])
        p1 = inv @ np.array([nx, ny, 1.0, 1.0])
        p0, p1 = p0[:3] / p0[3], p1[:3] / p1[3]
        ac = self.world.ac
        R = ac.R
        o = R.T @ (self.camera.eye - ac.pos)
        d = R.T @ (p1 - p0)
        return o, d / np.linalg.norm(d)

    def draw_panel3d(self, paused):
        """Dibuja el tablero en su textura y lo hace interactivo mediante el rayo del ratón."""
        from render.cockpit3d import PANEL_TEX
        W3, H3 = PANEL_TEX
        if self.panel_surf3d is None:
            self.panel_surf3d = pygame.Surface((W3, H3 + 40), pygame.SRCALPHA)
            self.compass_surf = pygame.Surface((200, 80), pygame.SRCALPHA)
        ui = self.ui
        ray = self._mouse_ray_body()
        hit = self.renderer.cockpit.panel_hit(*ray) if ray else None
        saved = (ui.mouse, ui.clicked, ui.right_clicked, ui.tooltip)
        if hit is not None:
            ui.mouse = (int(hit[0]), int(hit[1]))
            if ui.clicked:
                ui.clicked = ui.mouse
            if ui.right_clicked:
                ui.right_clicked = ui.mouse
        else:
            ui.mouse = (-9999, -9999)
            clicked0, right0 = ui.clicked, ui.right_clicked
            ui.clicked = ui.right_clicked = None
        tip0 = ui.tooltip
        self.panel_frame += 1
        busy = hit is not None and (saved[1] or saved[2] or self.ui.wheel or pygame.mouse.get_pressed()[0])
        if busy or self.panel_frame % 3 == 0 or paused:
            self.panel_surf3d.fill((0, 0, 0, 0))
            self.panel.draw(self.panel_surf3d, pygame.Rect(0, 40, W3, H3), self.world, ui, self)
            self.renderer.cockpit.upload_panel(self.panel_surf3d)
            self.compass_surf.fill((18, 18, 20, 255))
            self.panel.g.compass(self.compass_surf, (2, 18, 196, 44), self.world.ind.compass)
            self.renderer.cockpit.upload_compass(self.compass_surf)
        new_tip = ui.tooltip if ui.tooltip != tip0 else None
        if hit is not None:
            ui.mouse = saved[0]
            ui.clicked = saved[1] if ui.clicked else None
            ui.right_clicked = saved[2] if ui.right_clicked else None
            ui.tooltip = new_tip or saved[3]
        else:
            ui.mouse = saved[0]
            ui.clicked, ui.right_clicked = clicked0, right0
        return hit is not None

    def draw_flight(self, dt, paused=False):
        w = self.world
        cam = self.camera
        in_cab = cam.mode == "cabina"
        self.cockpit_style = self.resolve_cockpit_style()     # en "auto" sigue a la consola si se enchufa o quita
        cockpit2d = in_cab and self.cockpit_style == "2d"
        cockpit3d = in_cab and self.cockpit_style == "3d"
        ph = self.panel_height() if cockpit2d else 0
        # un clic en la barra de botones no debe llegar a los mandos de la cabina 3D
        self._bar_click = None
        if self.ui.clicked and self._bar_rect is not None and self._bar_visible() and self._bar_rect.collidepoint(self.ui.clicked):
            self._bar_click, self.ui.clicked = self.ui.clicked, None
        if self.instr_mode() == "unica":
            # cabina física: esta pantalla solo muestra los instrumentos
            self.ctx.screen.use()
            self.ctx.clear(0.02, 0.02, 0.03)
            self.instr_display.draw(self.overlay, w, self.panel)
            if self.instr_display.editing:
                self.instr_display.edit(self.overlay, (0, 0), self.ui)
            if w.ac.crashed:
                self.fonts.blit(self.overlay, "ACCIDENTE — " + w.ac.crash_reason, (self.W / 2, self.H - 40), 20,
                                (255, 120, 100), bold=True, anchor="center")
            if not paused:
                self.draw_popups()
                self.draw_mouse_bar()
            return
        # cabina física con un solo monitor: arriba el paisaje, abajo solo los instrumentos
        ambiente = in_cab and (self.instr_mode() == "ambiente" or self.cockpit_style == "franja")
        if ambiente:
            cockpit2d = cockpit3d = False
            ph = int(self.H * 0.40)
            if getattr(self, "_amb_view", None) is not self.lesson:
                # vista de piloto mirando al frente, con el horizonte a un tercio de la ventana
                self._amb_view = self.lesson
                cam.anim = None
                cam.head_yaw = 0.0
                cam.head_pitch = math.radians(-4.0)
                cam.fov = 80.0
        cam.update(dt if dt else 0.0, w)
        viewport = (0, ph, self.W, self.H - ph)
        self._scene_rect = pygame.Rect(0, 0, self.W, self.H - ph)     # zona del paisaje en pantalla
        rings = self.lesson.rings if self.lesson is not None else []
        over_panel = False
        if cockpit3d:
            blocked = self.show_controls and self.ui.mouse[1] > self.H * 0.40
            saved = (self.ui.clicked, self.ui.right_clicked, self.ui.wheel)
            if blocked:
                self.ui.clicked = self.ui.right_clicked = None
                self.ui.wheel = 0
            over_panel = self.draw_panel3d(paused)
            if blocked:
                self.ui.clicked, self.ui.right_clicked, self.ui.wheel = saved
                over_panel = True
        ac = w.ac
        cp = dict(yoke=(ac.ctl_ail, ac.ctl_elev), show_yoke=self.show_yoke) if cockpit3d else None
        nviews = int(self.settings.get("vistas", 1) or 1)
        if nviews > 1 and in_cab and not cockpit3d and not cockpit2d:
            # vista panorámica: izquierda · frente · derecha, cada una con su parte del campo de visión
            vx, vy, vw, vh = viewport
            ww = vw // nviews
            hfov = cam.fov
            yaw0 = cam.head_yaw
            for i in range(nviews):
                cam.head_yaw = yaw0 + math.radians((i - (nviews - 1) / 2) * hfov)
                cam.update(0.0, w)
                self.renderer.render(cam, (vx + i * ww, vy, ww, vh), extra=dict(rings=rings),
                                     dt=(dt if not paused else 0.0) if i == 0 else 0.0, cockpit=None)
            cam.head_yaw = yaw0
            cam.update(0.0, w)
        else:
            self.renderer.render(cam, viewport, extra=dict(rings=rings), dt=dt if not paused else 0.0, cockpit=cp)
        if in_cab and not cockpit3d:
            # lluvia sobre el parabrisas (solo encima del paisaje)
            if not hasattr(self, "rain_fx"):
                from ui.rain import RainFX
                self.rain_fx = RainFX()
            self.rain_fx.draw(self.overlay, pygame.Rect(0, 0, self.W, self.H - ph), w, dt or 0.0, paused)
        if ambiente:
            sub = self.overlay.subsurface((0, self.H - ph, self.W, ph))
            self.instr_display.draw(sub, w, self.panel)
            if self.instr_display.editing:
                self.instr_display.edit(sub, (0, self.H - ph), self.ui)
        elif cockpit2d:
            self.draw_panel(ph, paused)
        elif not cockpit3d:
            self.draw_hud()
        self.draw_flight_overlays(paused)
        if not paused:
            self.draw_mouse_bar()
        if not paused and not over_panel:
            d = self.ui.scroll(pygame.Rect(0, 0, self.W, self.H - ph))
            if d:
                cam.zoom(d)

    def draw_panel(self, ph, paused):
        rect = pygame.Rect(0, self.H - ph, self.W, ph)
        interacting = self.ui.clicked or self.ui.right_clicked or self.ui.wheel or pygame.mouse.get_pressed()[0]
        self.panel_frame += 1
        if self.panel_cache is None or self.panel_cache.get_size() != (self.W, ph + 40):
            self.panel_cache = pygame.Surface((self.W, ph + 40), pygame.SRCALPHA)
        if interacting or self.panel_frame % 2 == 0 or paused:
            self.panel_cache.fill((0, 0, 0, 0))
            # se dibuja en coordenadas locales y se ajusta el ratón
            ui = self.ui
            ox, oy = 0, self.H - ph - 40
            saved = (ui.mouse, ui.clicked, ui.right_clicked, ui.wheel_pos)
            ui.mouse = (ui.mouse[0] - ox, ui.mouse[1] - oy)
            if ui.clicked:
                ui.clicked = (ui.clicked[0] - ox, ui.clicked[1] - oy)
            if ui.right_clicked:
                ui.right_clicked = (ui.right_clicked[0] - ox, ui.right_clicked[1] - oy)
            tip0 = ui.tooltip
            self.panel.draw(self.panel_cache, pygame.Rect(0, 40, self.W, ph), self.world, ui, self)
            self._panel_tip = ui.tooltip if ui.tooltip != tip0 else None
            ui.mouse = saved[0]
            ui.clicked = saved[1] if ui.clicked else None
            ui.right_clicked = saved[2] if ui.right_clicked else None
        elif getattr(self, "_panel_tip", None) and self.ui.mouse[1] > self.H - ph and not self.ui.tooltip:
            self.ui.tooltip = self._panel_tip
        self.overlay.blit(self.panel_cache, (0, self.H - ph - 40))

    def draw_hud(self):
        s = self.overlay
        f = self.fonts
        w = self.world
        ac = w.ac
        ind = w.ind
        bar = pygame.Rect(0, 0, min(self.W - 40, 980), 64)
        bar.midbottom = (self.W / 2, self.H - 14)
        panel_box(s, bar, 12, (12, 16, 22, 200))
        items = [
            ("VEL", f"{ind.ias:3.0f}", "kt"), ("ALT", f"{ind.alt_ft:5.0f}", "ft"), ("V/S", f"{ind.vs_fpm:+5.0f}", "fpm"),
            ("RUMBO", f"{ac.heading:03.0f}", "°"), ("RPM", f"{ac.sys.engine.rpm:4.0f}", ""),
            ("GASES", f"{ac.sys.engine.throttle * 100:3.0f}", "%"), ("FLAPS", f"{ac.sys.flaps:2.0f}", "°"),
            ("TRIM", f"{ac.trim * 100:+3.0f}", ""), ("AGL", f"{min(ac.agl / FT, 9999):4.0f}", "ft"),
        ]
        cw = bar.w / len(items)
        for i, (lab, val, unit) in enumerate(items):
            cx = bar.x + cw * (i + 0.5)
            f.blit(s, lab, (cx, bar.y + 8), 12, COL["grey"], bold=True, anchor="midtop")
            f.blit(s, val + unit, (cx, bar.y + 26), 22, COL["white"], bold=True, mono=True, anchor="midtop")
        warn = []
        if ac.sys.stall_warning:
            warn.append(("PÉRDIDA", COL["red"]))
        if ac.sys.parking_brake:
            warn.append(("FRENO", COL["amber"]))
        if w.ap.engaged:
            warn.append((f"PA {w.ap.lat}/{w.ap.vert}", COL["green"]))
        x = bar.x
        for txt, col in warn:
            r = f.blit(s, txt, (x, bar.y - 24), 15, col, bold=True)
            x = r.right + 18

    def draw_flight_overlays(self, paused):
        s = self.overlay
        f = self.fonts
        w = self.world
        L = self.lesson
        ph = self.panel_height() if (self.camera.mode == "cabina" and self.cockpit_style == "2d") else 0
        top = (self._bar_rect.bottom + 6) if (self._bar_rect is not None and self._bar_visible() and not paused) else 0
        # caja de la lección
        if L is not None and not isinstance(L, type(None)):
            lines = L.hud(w)
            if lines or not isinstance(L, FreeFlight):
                bw = min(580, self.W * 0.40)
                rows = []
                for kind, txt in lines:
                    sz = 15 if kind == "paso" else 14
                    for ln in f.wrap(txt, sz, bw - 24, bold=kind == "paso")[:2]:
                        rows.append((kind, ln, sz))
                nst = len(getattr(L, "steps", []) or [])
                box = pygame.Rect(14, 14 + top, bw, 36 + 20 * len(rows) + (12 if nst > 1 else 0))
                panel_box(s, box, 10, (4, 14, 24, 205))
                if nst > 1:
                    # barra de pasos segmentada: hechos en cian, el actual parpadea
                    from ui import theme
                    seg_w = (box.w - 24 - (nst - 1) * 3) / nst
                    for k in range(nst):
                        rx = box.x + 12 + k * (seg_w + 3)
                        done = k < L.idx or L.done
                        cur = k == L.idx and not L.done
                        colk = theme.CYAN if done else ((*theme.CYAN, 255 if theme.blink(0.8) else 90) if cur else (30, 60, 78))
                        pygame.draw.rect(s, colk, (rx, box.bottom - 9, max(2, seg_w), 3))
                tag = f"  ·  ACS {L.acs}" if getattr(L, "acs", "") else ""
                f.blit(s, L.title.upper() + tag, (box.x + 12, box.y + 8), 14, COL["accent"], bold=True)
                y = box.y + 30
                for kind, ln, sz in rows:
                    col = {"paso": COL["white"], "ok": COL["green"], "mal": (255, 120, 90)}[kind]
                    f.blit(s, ln, (box.x + 12, y), sz, col, bold=kind == "paso")
                    y += 20
        # mensajes del instructor
        now = time.time()
        y = 16 + top
        for text, t0 in list(self.messages):
            age = now - t0
            if age > 7:
                continue
            a = int(255 * clamp(7 - age, 0, 1))
            x0, x1 = self.free_span(lesson_box=L is not None)
            maxw = int(min(x1 - x0 - 24, self.W * 0.6))
            wl = f.wrap(text, 17, maxw)[:3]
            imgs = [f.render(t, 17, (255, 255, 255)) for t in wl]
            bw = max(i.get_width() for i in imgs) + 24
            box = pygame.Rect(0, 0, bw, 22 * len(imgs) + 12)
            box.midtop = ((x0 + x1) / 2, y)
            panel_box(s, box, 8, (20, 40, 70, min(220, a)), border=(70, 120, 190))
            for k, img in enumerate(imgs):
                img.set_alpha(a)
                s.blit(img, (box.x + 12, box.y + 6 + 22 * k))
            y += box.h + 6
        # estado arriba a la derecha
        mode = MODE_NAMES.get(self.camera.mode, "")
        txt = f"{mode}  ·  {w.weather.describe()}"
        hint = "H: ayuda   K: lista   Esc: menú   I: instructor"
        if self.instr_mode() not in ("ambiente", "unica") and self.cockpit_style != "franja":
            tw = max(f.get(13).size(txt)[0], f.get(12).size(hint)[0])
            panel_box(s, pygame.Rect(self.W - tw - 28, 8 + top, tw + 20, 44), 8, (10, 14, 20, 170), border=None)
            f.blit(s, txt, (self.W - 18, 13 + top), 13, (220, 225, 230), anchor="topright")
            f.blit(s, hint, (self.W - 18, 31 + top), 12, (160, 170, 180), anchor="topright")
        # accidente / fin
        if w.ac.crashed:
            box = pygame.Rect(0, 0, 620, 150)
            box.center = (self.W / 2, (self.H - ph) / 2)
            safe = "a salvo" in w.ac.crash_reason
            panel_box(s, box, 14, (60, 40, 10, 230) if safe else (60, 10, 10, 230), border=(220, 160, 60) if safe else (200, 60, 60))
            f.blit(s, "ATERRIZAJE DE EMERGENCIA" if safe else "ACCIDENTE", (box.centerx, box.y + 18), 32, (255, 230, 230),
                   bold=True, anchor="midtop")
            f.blit(s, w.ac.crash_reason, (box.centerx, box.y + 66), 18, COL["white"], anchor="midtop")
            if self.ui.button(s, (box.centerx - 250, box.bottom - 50, 160, 36), "Reintentar (Ctrl+R)", size=14):
                self.restart_lesson()
            if self.ui.button(s, (box.centerx - 80, box.bottom - 50, 160, 36), "Ver repetición (R)", size=14):
                self.enter_replay()
            if self.ui.button(s, (box.centerx + 90, box.bottom - 50, 160, 36), "Análisis", size=14):
                self.end_flight()
        elif L is not None and L.done and not isinstance(L, FreeFlight):
            box = pygame.Rect(0, 0, 520, 120)
            box.center = (self.W / 2, (self.H - ph) / 2)
            ok = L.success
            panel_box(s, box, 14, (10, 50, 30, 230) if ok else (60, 40, 10, 230))
            f.blit(s, "LECCIÓN COMPLETADA" if ok else "LECCIÓN TERMINADA", (box.centerx, box.y + 16), 26, COL["white"],
                   bold=True, anchor="midtop")
            if self.ui.button(s, (box.centerx - 170, box.bottom - 48, 160, 36), "Ver evaluación", size=15):
                self.end_flight()
            if self.ui.button(s, (box.centerx + 10, box.bottom - 48, 160, 36), "Seguir volando", size=15):
                self.lesson = FreeFlight(self.lesson.start)
                self.lesson.steps = []
        self.draw_popups()
        self.draw_emergency_effects()
        job = getattr(self, "_cont_wait", None)
        if job is not None:
            from ui import theme
            r = pygame.Rect(0, 0, 560, 70)
            r.center = (self.W / 2, self.H * 0.3)
            panel_box(s, r, 10, (4, 14, 24, 235))
            f.blit(s, "PREPARANDO EL ESCENARIO SIGUIENTE (simulación en pausa)", (r.centerx, r.y + 14), 14, theme.CYAN,
                   bold=True, anchor="midtop")
            f.blit(s, job["msg"][:70], (r.centerx, r.y + 40), 13, COL["white"], anchor="midtop")
        if self.auto_start is not None:
            f.blit(s, "Arranque automático en curso…", (self.W / 2, self.H * 0.2), 18, COL["amber"], bold=True, anchor="center")

    def draw_popups(self):
        s = self.overlay
        f = self.fonts
        w = self.world
        if self.show_controls:
            self.controls_screen.draw(s, w, self.ui, self)
        if self.show_help:
            self.draw_help_overlay()
        if self.show_check:
            self.draw_checklist_overlay()
        if self.show_radio:
            self.draw_radio_overlay()
        else:
            self.draw_radio_subtitle()
        if self.voice_in.listening:
            r = pygame.Rect(0, 0, 300, 44)
            r.midtop = (self.W / 2, int(self.H * 0.12))
            panel_box(s, r, 10, (120, 20, 20, 225), border=(255, 120, 100))
            dot = 6 + 3 * math.sin(time.time() * 9)
            pygame.draw.circle(s, (255, 90, 80), (r.x + 26, r.centery), int(dot))
            f.blit(s, "ESCUCHANDO… hable ahora", (r.x + 46, r.centery), 16, COL["white"], bold=True, anchor="midleft")

    # ------------------------------------------------------------ barra para probar con el ratón
    def _bar_visible(self):
        """La barra aparece al mover el ratón y se esconde sola (en la cabina física no estorba)."""
        if self._bar_rect is not None and self._bar_rect.collidepoint(self.ui.mouse):
            return True
        return time.time() - self._mouse_t < 5.0 or self.popups_open()

    def _bar_items(self):
        w = self.world
        cams = MODES
        items = [
            ("Menú", "Pausa y menú (Esc)", False, lambda: (setattr(self, "state", "pause"), self.audio.silence())),
            ("Radio", "Radio: torre, rodadura y ATIS (T)", self.show_radio, lambda: setattr(self, "show_radio", not self.show_radio)),
            ("Hablar", "Hablar a la torre por el micrófono (Ctrl derecho)", self.voice_in.listening, self.push_to_talk),
            ("Tableta", "Listas de verificación, emergencias, peso y plan (K)", self.show_check,
             lambda: setattr(self, "show_check", not self.show_check)),
            ("Instructor", "Estación del instructor: fallas, meteorología, posición (I)", False,
             lambda: (setattr(self, "state", "instructor"), self.audio.silence())),
            ("Pantalla", "Cambiar la pantalla: paisaje + instrumentos, solo instrumentos… (F2)", False,
             self.cycle_instrument_screen),
            ("Mover instr.", "Mover y escalar los instrumentos con el ratón (F3)", self.instr_display.editing,
             self.toggle_instr_editor),
            ("Cámara", "Cabina, exterior, torre o cámara libre (1–4)", False,
             lambda: (self.camera.set_mode(cams[(cams.index(self.camera.mode) + 1) % len(cams)]),
                      self.flash(MODE_NAMES[self.camera.mode], 1.2))),
            ("Arrancar", "Arranque automático del motor (Ctrl+E)", self.auto_start is not None, self.start_engine_auto),
            ("Repetición", "Ver la repetición del vuelo (R)", False, self.enter_replay),
            ("Reiniciar", "Empezar la lección de nuevo (Ctrl+R)", False, self.restart_lesson),
            ("Ayuda", "Todas las teclas (H)", self.show_help, lambda: setattr(self, "show_help", not self.show_help)),
        ]
        return items

    def draw_mouse_bar(self):
        s = self.overlay
        f = self.fonts
        ui = self.ui
        if self._bar_click is not None:
            ui.clicked, self._bar_click = self._bar_click, None
        if not self._bar_visible():
            return
        items = self._bar_items()
        size = 13 if self.W >= 1500 else 12
        pad = 22
        widths = [f.get(size, True).size(lab)[0] + pad for lab, *_ in items]
        gap = 6
        rows, cur, cw = [], [], 0
        for i, wd in enumerate(widths):
            if cur and cw + gap + wd > self.W - 40:
                rows.append(cur)
                cur, cw = [], 0
            cur.append(i)
            cw += wd + (gap if len(cur) > 1 else 0)
        rows.append(cur)
        bh = 32
        total_h = len(rows) * (bh + gap) - gap
        maxw = max(sum(widths[i] for i in r) + gap * (len(r) - 1) for r in rows)
        bar = pygame.Rect(0, 6, maxw + 16, total_h + 12)
        bar.centerx = self.W // 2
        panel_box(s, bar, 10, (10, 14, 20, 205), border=(60, 80, 110))
        self._bar_rect = bar
        y = bar.y + 6
        for r in rows:
            x = bar.centerx - (sum(widths[i] for i in r) + gap * (len(r) - 1)) / 2
            for i in r:
                rect = pygame.Rect(int(x), y, widths[i], bh)
                lab, tip, active, fn = items[i]
                if ui.button(s, rect, lab, active=active, size=size, tip=tip):
                    fn()
                x += widths[i] + gap
            y += bh + gap

    def draw_emergency_effects(self):
        """Humo en cabina, resplandor del fuego, avisos y señales luminosas de la torre."""
        s = self.overlay
        f = self.fonts
        w = self.world
        sysm = w.ac.sys
        t = time.time()
        if sysm.smoke_level > 0.01:
            haze = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            a = int(235 * min(1.0, sysm.smoke_level) ** 0.8)
            haze.fill((150, 150, 148, a))
            s.blit(haze, (0, 0))
        if sysm.fire_level > 0.01:
            # humo negro y resplandor anaranjado que sube desde el morro
            h = int(self.H * (0.18 + 0.5 * sysm.fire_level))
            glow = pygame.Surface((self.W, h), pygame.SRCALPHA)
            for yy in range(0, h, 4):
                k = yy / h
                flick = 0.75 + 0.25 * math.sin(t * 13 + yy * 0.07)
                pygame.draw.rect(glow, (int(255 * flick), int(110 * k), 20, int(150 * k * min(1, sysm.fire_level * 2))),
                                 (0, yy, self.W, 4))
            s.blit(glow, (0, self.H - h))
            smoke = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            smoke.fill((30, 28, 26, int(110 * sysm.fire_level)))
            s.blit(smoke, (0, 0))
        # avisos
        alerts = []
        if sysm.fire_level > 0.01:
            alerts.append(("FUEGO MOTOR", (220, 40, 30)))
        if sysm.smoke_level > 0.05:
            alerts.append(("HUMO EN CABINA", (220, 40, 30)))
        if sysm.failures.get("door"):
            alerts.append(("PUERTA ABIERTA", (230, 160, 20)))
        if sysm.failures.get("fuel_leak") and sysm.fuel_l < w.ac.t.fuel_capacity * 0.25:
            alerts.append(("COMBUSTIBLE BAJO", (230, 160, 20)))
        if alerts:
            from ui import theme
            widths = [f.get(15, True).size(lab)[0] + 64 for lab, _ in alerts]
            scene = getattr(self, "_scene_rect", None) or pygame.Rect(0, 0, self.W, self.H)
            x0, x1 = self.free_span(lesson_box=False)
            x = (x0 + x1) / 2 - (sum(widths) + 10 * (len(widths) - 1)) / 2
            y = min(self.H * 0.27, scene.bottom - 60)
            on = int(t * 2.5) % 2 == 0
            for (lab, col), wd in zip(alerts, widths):
                red = col[1] < 100
                r = pygame.Rect(x, y, wd, 42)
                fill = (70, 10, 10, 235) if red else (60, 40, 4, 235)
                panel_box(s, r, 8, fill, border=col if (on or not red) else (120, 40, 34))
                if red and on:
                    theme.glow(s, r, col, layers=2)
                icon_c = (255, 120, 100) if red else (255, 200, 80)
                theme.icon(s, "emergencia", (r.x + 24, r.centery), 18, icon_c, 2)
                f.blit(s, lab, (r.x + 44, r.centery), 15, (255, 255, 255), bold=True, anchor="midleft")
                x += wd + 10
        # señal luminosa de la torre (falla de radio)
        lt = w.emerg.light
        if lt is not None:
            col, blink = lt
            on = not blink or int(t * 2) % 2 == 0
            c = (60, 255, 90) if col == "verde" else (255, 50, 40)
            r = pygame.Rect(0, self.H * 0.30, 250, 64)
            r.right = self.free_span(lesson_box=False)[1]          # a la izquierda de la tableta si está abierta
            panel_box(s, r, 10, (6, 16, 28, 230), border=c if on else (70, 76, 86))
            if on:
                pygame.draw.circle(s, c, (r.x + 34, r.centery), 18)
                pygame.draw.circle(s, (255, 255, 255), (r.x + 34, r.centery), 7)
            f.blit(s, "SEÑAL DE LA TORRE", (r.x + 64, r.y + 12), 12, COL["grey"], bold=True)
            meaning = {("verde", False): "Autorizado a aterrizar", ("rojo", False): "Ceda el paso, siga en circuito",
                       ("verde", True): "Autorizado a rodar", ("rojo", True): "Libere la pista"}[lt]
            f.blit(s, meaning, (r.x + 64, r.y + 32), 14, COL["white"], bold=True)

    def draw_replay(self, dt):
        r = self.replay
        pose = self.recorder.pose_at(r["t"])
        if pose is None:
            self.state = "flight"
            return
        p, q, row = pose
        self.camera.update(dt, self.world, pose=(p, q))
        self.renderer.render(self.camera, (0, 0, self.W, self.H), pose=(p, q), dt=dt)
        s = self.overlay
        f = self.fonts
        from ui import theme
        box = pygame.Rect(0, 0, min(self.W - 40, 820), 104)
        box.midbottom = (self.W / 2, self.H - 16)
        panel_box(s, box, 12, (8, 16, 28, 228))
        theme.spaced(f, s, "REPETICIÓN", (box.x + 16, box.y + 12), 12, theme.CYAN)
        state = "PAUSA" if r["paused"] else f"×{r['speed']:g}"
        chip = pygame.Rect(box.x + 132, box.y + 8, f.get(12, True).size(state)[0] + 18, 20)
        pygame.draw.rect(s, theme.AMBER if r["paused"] else (16, 44, 62), chip, border_radius=10)
        f.blit(s, state, chip.center, 12, theme.DEEP if r["paused"] else theme.TEXT, bold=True, anchor="center")
        i = Recorder.FIELDS
        vals = [("VEL", f"{row[i.index('ias')]:.0f}", "kt"), ("ALT", f"{row[i.index('alt')]:.0f}", "ft"),
                ("V/S", f"{row[i.index('vs')]:+.0f}", "ft/min"), ("RUMBO", f"{row[i.index('hdg')]:03.0f}", "°")]
        cw = (box.w - 32) / len(vals)
        for k, (lab, v, u) in enumerate(vals):
            x = box.x + 16 + k * cw
            f.blit(s, lab, (x, box.y + 34), 11, theme.TEXT_DIM, bold=True)
            r_ = f.blit(s, v, (x, box.y + 48), 20, theme.TEXT, bold=True, mono=True)
            f.blit(s, u, (r_.right + 4, box.y + 55), 11, theme.TEXT_DIM)
        # línea de tiempo con el tiempo transcurrido y el total
        bar = pygame.Rect(box.x + 64, box.bottom - 20, box.w - 128, 6)
        pygame.draw.rect(s, (24, 44, 60), bar, border_radius=3)
        fr = (r["t"] - r["t0"]) / max(r["t1"] - r["t0"], 1e-3)
        pygame.draw.rect(s, theme.CYAN, (bar.x, bar.y, bar.w * fr, bar.h), border_radius=3)
        pygame.draw.circle(s, theme.TEXT, (int(bar.x + bar.w * fr), bar.centery), 7)

        def mmss(t):
            return f"{int(t // 60)}:{int(t % 60):02d}"
        f.blit(s, mmss(r["t"] - r["t0"]), (bar.x - 10, bar.centery), 12, theme.TEXT, mono=True, anchor="midright")
        f.blit(s, mmss(r["t1"] - r["t0"]), (bar.right + 10, bar.centery), 12, theme.TEXT_DIM, mono=True, anchor="midleft")
        f.blit(s, "Espacio pausa · ←/→ ±10 s · ↑/↓ velocidad · 2/3/4 cámaras · Esc salir",
               (box.right - 16, box.y + 14), 11, theme.TEXT_DIM, anchor="topright")
        if self.ui.hit(bar.inflate(0, 16)):
            r["t"] = r["t0"] + (self.ui.mouse[0] - bar.x) / bar.w * (r["t1"] - r["t0"])

    def draw_menu_scene(self, dt):
        """Fondo de los menús: la foto de assets/fondo_menu.png o, si no hay, la escena 3D."""
        from ui import assets
        self.menu_t += dt
        bg = assets.image("fondo_menu.png")
        if bg is not None:
            # la foto la dibuja la tarjeta gráfica debajo de la interfaz: así los trazos translúcidos se mezclan bien
            iw, ih = bg.get_size()
            k = max(self.W / iw, self.H / ih) * (1.0 + 0.02 * math.sin(self.menu_t * 0.1))
            w, h = iw * k, ih * k
            self.renderer.set_photo(bg, ((self.W - w) / 2, (self.H - h) / 2, w, h))
            self.ctx.screen.use()
            self.ctx.clear(0.0, 0.0, 0.0)
            return
        cam = self.camera
        if cam.mode != "libre":
            cam.set_mode("libre")
        cam.orbit_yaw = math.radians(150) + self.menu_t * 0.05
        cam.orbit_pitch = math.radians(9)
        cam.orbit_dist = 17.0
        cam.update(dt, self.world)
        self.renderer.render(cam, (0, 0, self.W, self.H), dt=dt)
