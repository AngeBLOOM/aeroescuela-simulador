"""Prueba automática de la aplicación completa: recorre pantallas y toma capturas."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pygame

OUT = sys.argv[1] if len(sys.argv) > 1 else "."
PLAN = sys.argv[2].split(",") if len(sys.argv) > 2 else ["menu", "lessons", "flight_analog", "flight_glass", "chase", "pause", "instructor", "debrief"]


def shot(app, name):
    data = app.ctx.screen.read(components=3)
    img = pygame.image.frombytes(data, (app.W, app.H), "RGB", True)
    pygame.image.save(img, os.path.join(OUT, f"app_{name}.png"))
    print("captura", name, f"fps~{app.fps:.0f}")


state = {"i": 0, "f0": 0}


def step(app, frame):
    i = state["i"]
    if i >= len(PLAN):
        return True
    name = PLAN[i]
    f = frame - state["f0"]
    if f == 1:
        from sim.lessons import LESSONS, LESSONS_BY_ID as LB, FreeFlight
        if name == "menu":
            app.state, app.menu_page = "menu", "main"
        elif name == "lessons":
            app.menu_page = "lessons"
        elif name == "free":
            app.state, app.menu_page = "menu", "free"
        elif name == "logbook":
            app.menu_page = "logbook"
        elif name == "diag":
            app.state, app.menu_page = "menu", "hardware"
            app.hw_tab = "diag"
        elif name == "hardware":
            app.state, app.menu_page = "menu", "hardware"
        elif name == "sens":
            app.state, app.menu_page = "menu", "hardware"
            app.hw_tab = "sens"
        elif name == "settings":
            app.menu_page = "settings"
        elif name == "flight_analog":
            app.panel.mode = "analog"
            app.start_lesson(LB['despegue'])
        elif name == "flight_glass":
            app.panel.mode = "glass"
            app.start_lesson(FreeFlight("final3"))
        elif name == "chase":
            app.camera.set_mode("exterior")
        elif name == "pause":
            app.state = "pause"
        elif name == "instructor":
            app.state = "instructor"
        elif name == "fallas":
            app.state = "instructor"; app.instr_tab = "fallas"
        elif name == "debrief":
            app.state = "flight"
            app.end_flight()
        elif name == "cold":
            app.panel.mode = "analog"
            app.start_lesson(LB['arranque'])
            app.show_check = True
        elif name == "final":
            app.panel.mode = "analog"
            app.start_lesson(LB['final'])
        elif name == "circuito":
            app.start_lesson(LB['circuito'])
        elif name == "da42cab":
            app.start_lesson(LB["vmc"])
        elif name == "da40cab":
            app.world.set_aircraft("da40")
            app.start_lesson(FreeFlight("final3"))
        elif name == "pa28rcab":
            app.world.set_aircraft("pa28r")
            app.panel.mode = "analog"
            app.start_lesson(FreeFlight("final3"))
        elif name == "pista":
            app.start_lesson(FreeFlight("pista"))
            app.camera.set_mode("exterior")
        elif name == "p2d":
            app.cockpit_mode = "2d"; app.panel.mode = "analog"; app.camera.set_mode("cabina")
        elif name == "glass2d":
            app.cockpit_mode = "2d"; app.panel.mode = "glass"
        elif name == "p3d":
            app.cockpit_mode = "3d"; app.panel.mode = "analog"
            app.camera.head_pitch = -0.21; app.camera.fov = 78.0
        elif name == "mirarder":
            app.camera.anim = None; app.camera.head_yaw = 1.75; app.camera.head_pitch = -0.35; app.camera.fov = 85.0
        elif name == "mirarizq":
            app.camera.anim = None; app.camera.head_yaw = -1.3; app.camera.head_pitch = -0.4; app.camera.fov = 85.0
        elif name == "miraratras":
            app.camera.anim = None; app.camera.head_yaw = 2.5; app.camera.head_pitch = -0.25; app.camera.fov = 85.0
        elif name.startswith("mandos"):
            app.show_controls = True
            app.controls_screen.tab = int(name[6:] or 0)
        elif name in ("instr_unica", "instr_glass"):
            app.settings["pantalla_instr"] = "unica"
            if name == "instr_glass":
                app.world.set_aircraft("da42"); app.start_lesson(FreeFlight("final3"))
        elif name == "ambiente":
            app.settings["pantalla_instr"] = "ambiente"
        elif name.startswith("lluvia_"):
            app.world.weather.rain = float(name[7:])
            app.world.atmo.rain_here = app.world.weather.rain
        elif name == "tormenta":
            # cumulonimbo a 7 km delante del avión
            import math as _m
            ac = app.world.ac
            h = _m.radians(ac.heading - 15)
            w = app.world.weather
            w.storm, w.storm_r = True, 2500.0
            w.storm_n, w.storm_e = ac.pos[0] + _m.cos(h) * 7000, ac.pos[1] + _m.sin(h) * 7000
            w.cloud_cover = 0.5
        elif name == "rayo":
            app.world.atmo.flash = 1.0
        elif name == "foco":
            app.world.ac.sys.lights["landing"] = True
        elif name.startswith("jetver"):
            # un avión de línea delante del alumno, para ver el modelo (jetver = en vuelo, jetver_t = en tierra)
            import math as _m
            import numpy as _np
            app.settings["pantalla_instr"] = "no"
            wx = app.world.weather
            wx.cloud_cover, wx.visibility_m = 0.2, 30000
            app.camera.set_mode("exterior")
            tr = app.world.traffic
            j = tr.spawn_jet("llegada") or [p for p in tr.planes if p.jet][0]
            ac = app.world.ac
            h = _m.radians(ac.heading)
            if name == "jetver":
                j.pos = ac.pos + _np.array([_m.cos(h) * 180 - _m.sin(h) * 40, _m.sin(h) * 180 + _m.cos(h) * 40, -8.0])
                j.heading = (ac.heading + 60) % 360
            else:
                j.on_ground, j.state, j.speed = True, "espera", 0.0
                gh = app.world.terrain.height(ac.pos[0] + _m.cos(h) * 90, ac.pos[1] + _m.sin(h) * 90)
                j.pos = _np.array([ac.pos[0] + _m.cos(h) * 90, ac.pos[1] + _m.sin(h) * 90, -(gh + j.gear_h)])
                j.heading = (ac.heading + 130) % 360
                j.wait_t = 1e9
        elif name.startswith("fluidez"):
            app.settings["fluidez"] = name[7:] or "auto"
            print("escala", app.renderer.rscale)
        elif name == "escala":
            print("escala", app.renderer.rscale, "fps_cap", app.fps_cap)
        elif name.startswith("fecha_"):
            import datetime as _dt
            app.world.weather.date = _dt.date.fromisoformat(name[6:])
        elif name.startswith("rumbo_"):
            # gira el avión (en vuelo) hacia un rumbo para mirar otra parte del cielo
            import math as _m
            ac = app.world.ac
            ac.place_in_air(ac.pos[0], ac.pos[1], ac.alt_msl, float(name[6:]), 95)
        elif name.startswith("hora_"):
            # cambia la hora del vuelo en curso: hora_20.5
            app.world.weather.hour = float(name[5:])
        elif name.startswith("amb_"):
            # vista de la cabina física: paisaje arriba, solo instrumentos abajo
            app.settings["pantalla_instr"] = "ambiente"
            app.world.set_aircraft(name[4:])
            app.panel.mode = getattr(app.world.ac.t, "default_cockpit", "analog")
            app.start_lesson(FreeFlight("final3"))
        elif name.startswith("ext_"):
            app.settings["pantalla_instr"] = "no"
            app.world.set_aircraft(name[4:])
            app.start_lesson(FreeFlight("pista"))
            app.camera.set_mode("libre")
            app.camera.orbit_yaw = 2.4; app.camera.orbit_pitch = 0.18; app.camera.orbit_dist = 16
        elif name == "peso":
            app.settings["pantalla_instr"] = "no"
            app.show_check = True
            app.efb_auto = False
            app.efb_tab = 99; app.efb_manual = {}; app.efb_emerg = None
        elif name == "informe":
            app.state = "flight"
            app.end_flight()
            from app import students
            students.open_file = lambda p: print("informe:", p)
            app.make_flight_report = app.make_flight_report
            import app.students as st
            p = st.flight_report(os.path.join(OUT, "informe_vuelo.html"), app.student, app.lesson.title, app.world.ac.t.name,
                                 app.world.place_name, app.result, app.recorder.array(), app.recorder.FIELDS, 60, 1)
            p2 = st.student_report(os.path.join(OUT, "ficha.html"), app.progress, __import__("sim.lessons", fromlist=["x"]).LESSONS)
            print("informes", p, p2)
        elif name == "remote":
            import json, urllib.request
            app.settings["instructor_red"] = True
            app.apply_remote()
            r = app.remote
            print("URL", r.url, "codigo", r.code)
            state["remote"] = r
        elif name == "remote2":
            import json, urllib.request
            r = state["remote"]
            def call(path, body=None, code=None):
                req = urllib.request.Request("http://127.0.0.1:8765" + path, data=None if body is None else json.dumps(body).encode(),
                                             headers={"X-Codigo": code or r.code, "Content-Type": "application/json"})
                try:
                    return json.loads(urllib.request.urlopen(req, timeout=5).read())
                except Exception as ex:
                    return str(ex)
            print("sin codigo:", call("/api/estado", code="0000" if r.code != "0000" else "1111"))
            d = call("/api/estado")
            e = d["estado"]
            print("estado:", e["leccion"], e["estado"], round(e["ias"]), round(e["alt"]), "lecciones", len(d["catalogo"]["lecciones"]))
            print("cmd:", call("/api/cmd", {"c": "falla", "k": "door", "cuando": "ahora"}))
            print("cmd:", call("/api/cmd", {"c": "leccion", "id": "fuego"}))
            html = urllib.request.urlopen("http://127.0.0.1:8765/", timeout=5).read()
            print("pagina", len(html), "bytes")
        elif name == "remote3":
            print("tras ordenes:", app.lesson.title, "puerta", app.world.ac.sys.failures["door"])
        elif name == "pano":
            app.settings["pantalla_instr"] = "ambiente"; app.settings["vistas"] = 3
        elif name == "pano_off":
            app.settings["vistas"] = 1; app.settings["pantalla_instr"] = "no"
        elif name == "editor":
            app.settings["pantalla_instr"] = "unica"
            app.instr_display.editing = True
            app.instr_display.sel = "ai"
        elif name == "instr_off":
            app.instr_display.editing = False
            app.settings["pantalla_instr"] = "no"
        elif name == "fuegoon":
            app.settings["pantalla_instr"] = "no"
            app.start_lesson(LB["fuego"])
            app.world.emerg.trigger("fire"); app.world.ac.sys.fire_level = 0.45
            app.show_check = True
        elif name == "humoon":
            app.world.ac.sys.fire_level = 0.0; app.world.ac.sys.failures["fire"] = False
            app.world.emerg.trigger("smoke"); app.world.ac.sys.smoke_level = 0.35
        elif name == "instrfallas":
            app.state = "instructor"; app.instr_tab = "fallas"
        elif name == "instrcontrol":
            app.world.freeze("alt", True); app.world.set_rate(2)
            app.state = "instructor"; app.instr_tab = "control"
        elif name == "congelado":
            app.state = "flight"
        elif name == "aviso":
            app.flash("Transpondedor 1200 (VFR)", 6)
        elif name in ("gps", "gps_fpl", "gps_dto"):
            if name == "gps":
                app.cockpit_mode = "2d"; app.panel.mode = "glass"; app.settings["pantalla_instr"] = "no"
                app.start_lesson(FreeFlight("crucero"))
                g = app.world.gps
                for ident, kind in (("ESC", "VOR"), ("VN", "NDB"), ("VNT", "APT")):
                    p = g.find(ident, kind)
                    if p is not None:
                        g.add(p)
                app.world.cdi_src = "GPS"
            app.panel.glass.gps_page = {"gps": None, "gps_fpl": "fpl", "gps_dto": "dto"}[name]
        elif name == "c152":
            app.cockpit_mode = "2d"; app.panel.mode = "analog"; app.settings["pantalla_instr"] = "no"
            app.world.set_aircraft("c152")
            app.start_lesson(LB["hielo_carb"])
            app.world.ac.sys.carb_heat = True
        elif name == "adf":
            app.cockpit_mode = "2d"; app.panel.mode = "analog"; app.settings["pantalla_instr"] = "no"
            app.start_lesson(FreeFlight("final10"))
            app.world.show_adf = True
        elif name == "instr":
            app.camera.toggle_instrument_view()
        elif name == "realmenu":
            app.menu_page = "location"
        elif name == "madrid":
            app.panel.mode = "glass"
            app.switch_world(__import__("sim.geo", fromlist=["x"]).build_location("LEMD", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datos"), db=app.geo_db))
            app.start_lesson(LB["final"])
        elif name == "school":
            app.switch_world(None)
            app.state = "menu"
        elif name == "radio":
            app.panel.mode = "glass"
            app.cockpit_mode = "3d"
            app.start_lesson(FreeFlight("punto_espera"))
            app.world.com_freq = app.world.freqs["TWR"]
            app.show_radio = True
            app.radio_select(1)
        elif name == "trafico":
            app.panel.mode = "glass"
            app.cockpit_mode = "2d"
            app.start_lesson(FreeFlight("viento_cola"))
            app.show_radio = False
        elif name == "torre":
            app.cockpit_mode = "3d"
            app.start_lesson(FreeFlight("plataforma"))
            app.camera.set_mode("torre")
        elif name == "ils":
            app.panel.mode = "glass"
            app.start_lesson(LB['ils'])
        elif name.startswith("L_"):
            # cualquier lección o misión por su id: L_svbs_amerizaje
            app.settings["pantalla_instr"] = "ambiente"
            app.start_lesson(LB[name[2:]])
        elif name == "lista_final":
            # lista de lecciones desplazada hasta el final (misiones de Base Sucre)
            app.state, app.menu_page = "menu", "lessons"
            app.lesson_scroll = 10 ** 6
            app.selected_lesson = len(LESSONS) - 3
        elif name == "barra":
            app.settings["pantalla_instr"] = "ambiente"
            app.start_lesson(LB['circuito'])
    if name == "barra" and f < 88:
        import time as _t
        app._mouse_t = _t.time()
    if name == "rayo" and f >= 80:
        app.world.atmo.flash = 1.0
    if f == 90:
        shot(app, name)
        state["i"] += 1
        state["f0"] = frame
    return False


from app.core import App
import app.core as _core
_orig_init = App.__init__


def _init(self, *a, **k):
    _orig_init(self, *a, **k)
    # las pruebas no deben escribir en la bitácora real del alumno
    from app.progress import Progress
    self.progress = Progress(os.path.join(OUT, "progreso_prueba.json"))
    self.save_settings = lambda: None


App.__init__ = _init
App(autotest=step).run()
