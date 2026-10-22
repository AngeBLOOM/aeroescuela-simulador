"""GPS: base de datos, «Directo a», desvío lateral y escala del CDI, curso magnético, modo OBS, y un vuelo con el piloto
automático en NAV siguiendo un plan de tres puntos con la secuencia automática de tramos."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim.mathx import FT, NM, wrap180
from sim.world import World

fallos = []


def check(ok, msg):
    print(("  ok   " if ok else "  FALLO ") + msg)
    if not ok:
        fallos.append(msg)


def airborne(w, north, east, hdg, agl_ft=3000):
    ac = w.ac
    gh = w.terrain.surface_height(north, east)
    ac.place_in_air(north, east, gh + agl_ft * FT, hdg, 100)
    w.step(1 / 60)
    return ac


print("Base de datos")
w = World("c172")
g = w.gps
ids = {(p.ident, p.kind) for p in g.database()}
check({("ESC", "APT"), ("VNT", "APT"), ("ESC", "VOR"), ("VNT", "VOR"), ("ES", "NDB"), ("VN", "NDB")} <= ids,
      f"aeródromos, VOR y NDB del escenario: {len(ids)} puntos")
near = g.nearest(3)
check(near[0][1] <= near[1][1] <= near[2][1], "los más cercanos, ordenados por distancia")

print("Directo a")
ac = airborne(w, 0.0, 0.0, 0)
vnt = g.find("VNT", "APT")
g.direct_to(vnt)
w.step(1 / 60)
dx, dy = vnt.pos[0] - ac.pos[0], vnt.pos[1] - ac.pos[1]
check(abs(g.dis_nm - math.hypot(dx, dy) / NM) < 0.05, f"distancia {g.dis_nm:.2f} NM")
check(abs(wrap180(g.dtk - math.degrees(math.atan2(dy, dx)))) < 1.0 and g.to_from == "TO" and abs(g.cdi) < 0.05,
      f"curso {g.dtk:03.0f}°, TO, aguja centrada")
ac.pos[1] += 1 * NM * math.cos(math.radians(g.dtk))      # 1 NM a la derecha del curso (hacia el este con curso ~N)
ac.pos[0] -= 1 * NM * math.sin(math.radians(g.dtk))
w.step(1 / 60)
check(abs(g.xtk_nm - 1.0) < 0.05 and g.scale == "TERM" and abs(g.cdi + 1.0) < 0.03,
      f"1 NM a la derecha: XTK {g.xtk_nm:+.2f} NM, aguja {g.cdi:+.2f} (escala terminal de 1 NM: destino a < 30 NM)")
ac.pos[1] -= 0.5 * NM * math.cos(math.radians(g.dtk))
ac.pos[0] += 0.5 * NM * math.sin(math.radians(g.dtk))
w.step(1 / 60)
check(abs(g.cdi + 0.5) < 0.03, f"0,5 NM a la derecha: aguja a media escala ({g.cdi:+.2f})")
w.set_magvar(-13)
w.step(1 / 60)
check(abs(wrap180(g.dtk - (math.degrees(math.atan2(dy, dx)) + 13))) < 1.5, f"con 13° W el curso es magnético: {g.dtk:03.0f}°")
w.set_magvar(0)

print("Modo OBS")
g.set_obs(True, 90)
w.step(1 / 60)
crs = math.radians(90)
rel = ac.pos[:2] - vnt.pos
xtk = -(rel[0] * math.sin(crs) - rel[1] * math.cos(crs)) / NM
check(g.dtk == 90 and abs(g.xtk_nm - xtk) < 0.05, f"curso 090 hacia VNT: XTK {g.xtk_nm:+.1f} NM")
g.set_obs(False)

print("Plan de vuelo con el piloto automático (NAV en GPS)")
w = World("c172")
g = w.gps
ac = airborne(w, -3000.0, 0.0, 0, agl_ft=6000)        # por encima de los cerros de Valle Norte
for ident, kind in (("ESC", "VOR"), ("VN", "NDB"), ("VNT", "APT")):
    g.add(g.find(ident, kind))
w.cdi_src = "GPS"
w.ap.engage(ac)
w.ap.set_alt(ac)
w.ap.lat = "HDG"
w.ap.hdg_bug = round(math.degrees(math.atan2(g.plan[0].pos[1] - ac.pos[1], g.plan[0].pos[0] - ac.pos[0]))) % 360
w.ap.set_nav(ac)
seq, closest = [], {}
for i in range(60 * 60 * 15):
    cmd = w.apply_autopilot(1 / 60)
    if cmd is not None:
        ac.ctl_elev, ac.ctl_ail = cmd
    w.step(1 / 60)
    t = g.target
    if t is not None:
        closest[t.ident] = min(closest.get(t.ident, 1e9), g.dis_nm)
    if not seq or seq[-1] != g.active:
        seq.append(g.active)
    if g.active == 2 and g.dis_nm < 0.5:
        break
check(seq == [0, 1, 2], f"la secuencia de tramos avanza sola: {seq}")
check(w.ap.lat == "NAV", f"el piloto automático sigue al GPS en NAV ({w.ap.lat})")
check(not ac.crashed and closest.get("ESC", 9) < 1.6 and closest.get("VN", 9) < 1.6 and g.dis_nm < 0.6,
      "pasa cerca de cada punto: " + ", ".join(f"{k} {v:.2f} NM" for k, v in closest.items()))
check(w.nav_source() is g, "el HSI y el piloto automático usan el GPS con el selector en GPS")

print("Quitar, activar y borrar")
g.activate(0)
check(g.active == 0 and g.ident == "ESC", "activar el primer tramo")
g.remove(0)
check([p.ident for p in g.plan] == ["VN", "VNT"] and g.ident == "VN", f"quitar un punto: {[p.ident for p in g.plan]}")
g.clear()
w.step(1 / 60)
check(not g.valid and g.ident == "----", "plan borrado: sin guía")

print("Escribir un identificador (teclado del G1000)")
import pygame                                                   # noqa: E402
from ui.glass import GlassCockpit                               # noqa: E402

r = g.search("VN")
check([p.ident for p, _, _ in r][:3] and all(p.ident.startswith("VN") for p, _, _ in r) and
      [d for _, d, _ in r] == sorted(d for _, d, _ in r), f"«VN»: {[f'{p.ident} {p.kind}' for p, _, _ in r]}")
name = next(a.name for a in w.airports if a.ident == "VNT")
frag = name.split()[-1][:5]
check(any(p.ident == "VNT" for p, _, _ in g.search(frag)), f"por el nombre: «{frag}» encuentra VNT ({name})")
ids_of = lambda rows: [(p.ident, p.kind) for p, _, _ in rows]                     # noqa: E731
check(ids_of(g.search("")) == ids_of(g.nearest(12)) and g.search("ZZZQ") == [],
      "vacío: los cercanos; sin coincidencias: nada")
check(ids_of(g.search("ES"))[0] == ("ES", "NDB"), f"la coincidencia exacta primero: «ES» → {ids_of(g.search('ES'))[:2]}")

gc = GlassCockpit.__new__(GlassCockpit)                         # solo la lógica del teclado, sin dibujar
gc.gps_page, gc.gps_query = "dto", ""
for ch in "vnt":
    gc.gps_key(g, ord(ch), ch)
gc.gps_key(g, pygame.K_BACKSPACE, "")
gc.gps_key(g, ord("t"), "t")
check(gc.gps_query == "VNT", f"teclear v-n-t, borrar y t: «{gc.gps_query}»")
check(not gc.gps_key(g, pygame.K_F7, ""), "F7 no es para el GPS: sigue cambiando el CDI")
gc.gps_key(g, pygame.K_RETURN, "\r")
check(g.direct is not None and g.direct.ident == "VNT" and gc.gps_page is None and gc.gps_query == "",
      "Enter: directo a VNT y la lista se cierra")
gc.gps_page = "add"
for ch in "es":
    gc.gps_key(g, ord(ch), ch)
gc.gps_key(g, pygame.K_RETURN, "\r")
check([p.ident for p in g.plan] == ["ES"] and gc.gps_page == "fpl", f"añadir al plan «ES»: {[p.ident for p in g.plan]}")
gc.gps_page = "dto"
gc.gps_key(g, ord("x"), "x")
gc.gps_key(g, pygame.K_ESCAPE, "")
check(gc.gps_page is None and gc.gps_query == "", "Esc cierra la lista sin elegir")

print("\nFALLOS: " + "; ".join(fallos) if fallos else "\nTODO OK")
sys.exit(1 if fallos else 0)
