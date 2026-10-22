"""Cabina de cristal estilo G1000: PFD (pantalla primaria) y MFD (mapa móvil + motor)."""
import math
import time

import numpy as np
import pygame

from sim.mathx import FT, KT, NM, clamp, wrap180
from .ui import COL, polar

CYAN = (0, 220, 255)
MAG = (240, 70, 240)
GREEN = (60, 230, 90)
WHITE = (240, 240, 240)
TAPE_BG = (40, 44, 52, 170)


class GlassCockpit:
    def __init__(self, fonts):
        self.f = fonts
        self.map_img = None
        self.map_scaled = None
        self.map_key = None
        self.map_range_nm = 10
        self.taws = True
        self.taws_img = None
        self.taws_time = 0.0
        self.track = []
        self.track_t = 0.0
        self.rose_cache = {}
        self.gps_page = None        # lista abierta en el mapa: None, "dto", "fpl" o "add"
        self.gps_query = ""         # identificador que se escribe con el teclado en D→ / añadir (vacío: los cercanos)
        self.gps_cursor = 0         # fila elegida con la perilla FMS de la consola
        self.gps_newchar = False    # la próxima vuelta de la perilla FMS pequeña empieza una letra nueva

    # ================================================================ PFD
    def pfd(self, surf, rect, world, ui):
        ac = world.ac
        ind = world.ind
        sysm = ac.sys
        f = self.f
        rect = pygame.Rect(rect)
        pygame.draw.rect(surf, (8, 8, 10), rect.inflate(4, 4), border_radius=3)
        if not sysm.electric_ok or sysm.failures["pfd"]:
            pygame.draw.rect(surf, (2, 2, 3), rect)
            if sysm.failures["pfd"] and sysm.electric_ok:
                f.blit(surf, "PFD FALLA — use instrumentos de reserva", rect.center, 16, COL["red"], bold=True, anchor="center")
            return
        clip = surf.get_clip()
        surf.set_clip(rect)
        h = rect.h
        c = (rect.centerx, rect.y + h * 0.36)
        ppd = h / 46.0
        roll, pitch = ac.roll, ac.pitch
        cr, sr = math.cos(roll), math.sin(roll)

        def rot(x, y):
            return (c[0] + x * cr + y * sr, c[1] - x * sr + y * cr)
        off = math.degrees(pitch) * ppd
        big = rect.w * 2
        pygame.draw.polygon(surf, (30, 110, 220), [rot(-big, -big), rot(big, -big), rot(big, off), rot(-big, off)])
        pygame.draw.polygon(surf, (130, 82, 30), [rot(-big, off), rot(big, off), rot(big, big), rot(-big, big)])
        pygame.draw.line(surf, WHITE, rot(-big, off), rot(big, off), 2)
        # escalera de cabeceo
        pd = math.degrees(pitch)
        lad_clip = pygame.Rect(0, 0, rect.w * 0.42, h * 0.62)
        lad_clip.center = c
        surf.set_clip(lad_clip.clip(rect))
        for p in range(-50, 51, 5):
            if p == 0 or abs(p - pd) > 20:
                continue
            y = off - p * ppd
            w = rect.w * (0.07 if p % 10 == 0 else 0.035)
            pygame.draw.line(surf, WHITE, rot(-w, y), rot(w, y), 2)
            if p % 10 == 0:
                for sx in (-1, 1):
                    f.blit(surf, str(abs(p)), rot(sx * (w + 16), y), 13, WHITE, bold=True, anchor="center")
        surf.set_clip(rect)
        # arco de alabeo
        R = h * 0.33
        for d in (-60, -45, -30, -20, -10, 0, 10, 20, 30, 45, 60):
            L = 12 if d % 30 == 0 else 7
            pygame.draw.line(surf, WHITE, polar(c, R, d), polar(c, R + L, d), 2)
        pts = [polar(c, R, d) for d in range(-60, 61, 3)]
        pygame.draw.aalines(surf, WHITE, False, pts)
        tip = rot(0, -R)
        pygame.draw.polygon(surf, WHITE, [tip, rot(-9, -R + 14), rot(9, -R + 14)])
        slip = clamp(ind.slip, -1.2, 1.2) * 14
        pygame.draw.polygon(surf, WHITE, [rot(-9 + slip, -R + 17), rot(9 + slip, -R + 17), rot(11 + slip, -R + 22), rot(-11 + slip, -R + 22)])
        # director de vuelo
        ap = world.ap
        if ap.engaged or ap.fd:
            fr = ap.cmd_roll - roll
            fp = (math.degrees(ap.cmd_pitch) - pd) * ppd
            cf, sf = math.cos(-fr), math.sin(-fr)

            def frot(x, y):
                return (c[0] + x * cf + y * sf, c[1] - fp - x * sf + y * cf)
            for sx in (-1, 1):
                pygame.draw.polygon(surf, MAG, [frot(sx * 6, 4), frot(sx * 70, 26), frot(sx * 70, 18)])
        # símbolo del avión
        yel = (255, 210, 0)
        pygame.draw.polygon(surf, yel, [c, (c[0] - 70, c[1] + 26), (c[0] - 46, c[1] + 26)])
        pygame.draw.polygon(surf, yel, [c, (c[0] + 70, c[1] + 26), (c[0] + 46, c[1] + 26)])
        pygame.draw.rect(surf, yel, (c[0] - 120, c[1] - 3, 34, 6))
        pygame.draw.rect(surf, yel, (c[0] + 86, c[1] - 3, 34, 6))

        self._speed_tape(surf, rect, world)
        self._alt_tape(surf, rect, world)
        self._hsi(surf, rect, world, ui)
        self._top_bar(surf, rect, world)
        # datos inferiores
        oat = ac.temp_k - 273.15 if hasattr(ac, "temp_k") else 15
        bl = pygame.Rect(rect.x + 6, rect.bottom - 54, 142, 48)
        pygame.draw.rect(surf, (0, 0, 0, 190), bl, border_radius=4)
        f.blit(surf, f"OAT {oat:+.0f}°C", (bl.x + 6, bl.y + 4), 13, WHITE, mono=True)
        wind = world.atmo.mean_wind(ac.agl)
        wspd = math.hypot(wind[0], wind[1]) / KT
        wdir = (math.degrees(math.atan2(-wind[1], -wind[0]))) % 360
        f.blit(surf, f"{wdir:03.0f}°/{wspd:2.0f}KT", (bl.x + 6, bl.y + 24), 13, WHITE, mono=True)
        rel = math.radians(wdir + 180 - ac.heading)
        wc = (bl.right - 18, bl.y + 30)
        if wspd > 1:
            tip = (wc[0] + 13 * math.sin(rel), wc[1] - 13 * math.cos(rel))
            tail = (wc[0] - 13 * math.sin(rel), wc[1] + 13 * math.cos(rel))
            pygame.draw.line(surf, WHITE, tail, tip, 2)
            pygame.draw.circle(surf, WHITE, tip, 3)
        # radioaltímetro y avisos
        if ind.radar_alt_ft < 2500 and not ac.on_ground:
            f.blit(surf, f"RA {ind.radar_alt_ft:4.0f}", (c[0], c[1] + h * 0.085), 16, GREEN, mono=True, bold=True, anchor="center")
        if sysm.stall_warning:
            f.blit(surf, "PÉRDIDA", (c[0], c[1] - h * 0.2), 22, (255, 40, 40), bold=True, anchor="center")
        mk = world.nav1.marker
        if mk:
            colm = {"O": (60, 120, 255), "M": (255, 190, 40), "I": WHITE}[mk]
            mr = pygame.Rect(rect.right - 152, rect.y + h * 0.18, 26, 22)
            pygame.draw.rect(surf, colm, mr)
            f.blit(surf, mk, mr.center, 14, (0, 0, 0), bold=True, anchor="center")
        tr = getattr(world, "traffic", None)
        if tr is not None and tr.ta_alert:
            tb = pygame.Rect(0, 0, 118, 26)
            tb.midtop = (c[0] - rect.w * 0.2, self._tape_y(rect))
            pygame.draw.rect(surf, (255, 210, 0), tb, border_radius=3)
            f.blit(surf, "TRÁFICO", tb.center, 16, (0, 0, 0), bold=True, anchor="center")
        if getattr(ap, "minspd", False) and ap.engaged:
            f.blit(surf, "MINSPD", (rect.x + 58, self._tape_y(rect) - 4), 14, (255, 200, 0), bold=True, anchor="midbottom")
        if ap.disconnect_alert > 0 and int(ap.disconnect_alert * 3) % 2 == 0:
            f.blit(surf, "AP OFF", (c[0], rect.y + (34 if rect.w < 560 else self.BAR_H + 8)), 18, (255, 200, 0), bold=True, anchor="midtop")
        surf.set_clip(clip)

    def _speed_tape(self, surf, rect, world):
        f = self.f
        ac = world.ac
        v = world.ind.ias
        vs = ac.t.v
        h = rect.h
        ty = self._tape_y(rect)
        tape = pygame.Rect(rect.x + 22, ty, 64, rect.y + h * 0.62 - ty)
        s = pygame.Surface(tape.size, pygame.SRCALPHA)
        s.fill(TAPE_BG)
        ppk = tape.h / 60.0
        cy = tape.h / 2
        lo = int(v - 32) // 5 * 5
        for k in range(lo, lo + 70, 5):
            if k < 20:
                continue
            y = cy - (k - v) * ppk
            L = 12 if k % 10 == 0 else 6
            pygame.draw.line(s, WHITE, (tape.w - L, y), (tape.w, y), 2)
            if k % 10 == 0:
                f.blit(s, str(k), (tape.w - 16, y), 15, WHITE, mono=True, bold=True, anchor="midright")

        def band(a, b, col, x0=0, wd=6):
            y0 = cy - (b - v) * ppk
            y1 = cy - (a - v) * ppk
            pygame.draw.rect(s, col, (tape.w - wd - x0, y0, wd, y1 - y0))
        band(vs["vs0"], vs["vfe"], (240, 240, 240), 0, 4)
        if "vmc" in vs:
            y_ = cy - (vs["vmc"] - v) * ppk
            pygame.draw.line(s, (230, 40, 30), (tape.w - 14, y_), (tape.w, y_), 3)
            y_ = cy - (vs["vyse"] - v) * ppk
            pygame.draw.line(s, (60, 120, 255), (tape.w - 14, y_), (tape.w, y_), 3)
        band(vs["vs1"], vs["vno"], (40, 190, 70), 5)
        band(vs["vno"], vs["vne"], (240, 200, 40), 5)
        band(vs["vne"], 300, (230, 40, 30), 5)
        band(0, vs["vs0"], (230, 40, 30), 0, 4)
        # tendencia de 6 s
        tr = clamp(world.ind.ias_trend, -30, 30)
        if abs(tr) > 1:
            pygame.draw.line(s, MAG, (tape.w - 3, cy), (tape.w - 3, cy - tr * ppk), 3)
        # marcas de velocidades V
        for lab, key in (("R", "vr"), ("X", "vx"), ("Y", "vy"), ("G", "vglide")):
            y = cy - (vs[key] - v) * ppk
            if 0 < y < tape.h:
                f.blit(s, lab, (tape.w + 0, y), 11, CYAN, bold=True, anchor="midleft")
        surf.blit(s, tape)
        box = pygame.Rect(tape.x - 2, tape.centery - 17, tape.w + 4, 34)
        pygame.draw.rect(surf, (0, 0, 0), box)
        pygame.draw.rect(surf, WHITE, box, 1)
        col = WHITE if v >= vs["vs0"] or ac.on_ground else (255, 60, 60)
        f.blit(surf, f"{v:3.0f}", (box.right - 8, box.centery), 24, col, mono=True, bold=True, anchor="midright")
        tas = ac.tas / KT
        tb = pygame.Rect(tape.x - 2, tape.bottom + 2, tape.w + 4, 22)
        pygame.draw.rect(surf, (0, 0, 0), tb)
        f.blit(surf, f"TAS {tas:3.0f}KT", tb.center, 12, WHITE, mono=True, anchor="center")


    def _alt_tape(self, surf, rect, world):
        f = self.f
        ac = world.ac
        ap = world.ap
        alt = world.ind.alt_ft
        h = rect.h
        ty = self._tape_y(rect)
        tape = pygame.Rect(rect.right - 140, ty, 80, rect.y + h * 0.62 - ty)
        s = pygame.Surface(tape.size, pygame.SRCALPHA)
        s.fill(TAPE_BG)
        ppf = tape.h / 600.0
        cy = tape.h / 2
        lo = int(alt - 400) // 20 * 20
        for k in range(lo, lo + 820, 20):
            y = cy - (k - alt) * ppf
            L = 12 if k % 100 == 0 else 6
            pygame.draw.line(s, WHITE, (0, y), (L, y), 2)
            if k % 100 == 0:
                f.blit(s, str(k), (16, y), 15, WHITE, mono=True, bold=True, anchor="midleft")
        yb = clamp(cy - (ap.alt_sel - alt) * ppf, 0, tape.h)
        pygame.draw.polygon(s, CYAN, [(0, yb - 9), (8, yb - 9), (8, yb - 3), (3, yb), (8, yb + 3), (8, yb + 9), (0, yb + 9)])
        # terreno (radioaltímetro)
        gy = cy + world.ind.radar_alt_ft * ppf
        if gy < tape.h:
            for k in range(int(gy), int(tape.h), 6):
                pygame.draw.line(s, (200, 140, 30), (0, k), (tape.w, k + 6), 1)
        surf.blit(s, tape)
        sel = pygame.Rect(tape.x, tape.y - 26, tape.w, 22)
        pygame.draw.rect(surf, (0, 0, 0), sel)
        f.blit(surf, f"{ap.alt_sel:5.0f}", sel.center, 15, CYAN, mono=True, bold=True, anchor="center")
        box = pygame.Rect(tape.x - 4, tape.centery - 17, tape.w + 8, 34)
        pygame.draw.rect(surf, (0, 0, 0), box)
        pygame.draw.rect(surf, WHITE, box, 1)
        f.blit(surf, f"{alt:5.0f}", (box.right - 6, box.centery), 22, WHITE, mono=True, bold=True, anchor="midright")
        bb = pygame.Rect(tape.x, tape.bottom + 2, tape.w, 22)
        pygame.draw.rect(surf, (0, 0, 0), bb)
        f.blit(surf, f"{world.kollsman:.0f} hPa", bb.center, 13, CYAN, mono=True, anchor="center")
        # indicador de desviación vertical (como el del G1000): rombo verde con la senda del ILS, magenta con la del
        # GPS en una aproximación RNAV; el rombo arriba del centro = la senda está arriba: subir
        nav = world.nav_source()
        if getattr(nav, "gs_valid", False):
            col = MAG if nav is world.gps else GREEN
            vd = pygame.Rect(tape.x - 22, tape.centery - tape.h * 0.3, 16, tape.h * 0.6)
            pygame.draw.rect(surf, (0, 0, 0), vd)
            for k in (-2, -1, 1, 2):
                pygame.draw.circle(surf, WHITE, (vd.centerx, int(vd.centery + k * vd.h / 5)), 3, 1)
            pygame.draw.line(surf, WHITE, (vd.x, vd.centery), (vd.right, vd.centery), 1)
            yy = vd.centery - clamp(nav.gs, -1.0, 1.0) * vd.h * 0.4
            pygame.draw.polygon(surf, col, [(vd.centerx, yy - 7), (vd.right - 1, yy), (vd.centerx, yy + 7), (vd.x + 1, yy)])
            f.blit(surf, "V" if nav is world.gps else "G", (vd.centerx, vd.y - 2), 12, col, bold=True, anchor="midbottom")
        # variómetro
        vt = pygame.Rect(tape.right + 6, tape.y + 10, 36, tape.h - 20)
        vsurf = pygame.Surface(vt.size, pygame.SRCALPHA)
        vsurf.fill(TAPE_BG)
        vc = vt.h / 2

        def vy(v):
            v = clamp(v, -2000, 2000)
            return vc - math.copysign(math.sqrt(abs(v) / 2000), v) * (vt.h / 2 - 6)
        for v in (-2000, -1000, -500, 0, 500, 1000, 2000):
            pygame.draw.line(vsurf, WHITE, (0, vy(v)), (8, vy(v)), 2)
            if v:
                f.blit(vsurf, str(abs(v) // 1000) if abs(v) >= 1000 else ".5", (11, vy(v)), 11, WHITE, anchor="midleft")
        if ap.vert == "VS" and ap.engaged:
            yb2 = vy(ap.vs_sel)
            pygame.draw.rect(vsurf, CYAN, (0, yb2 - 4, 6, 8))
        surf.blit(vsurf, vt)
        vs = world.ind.vs_fpm
        y = vt.y + vy(vs)
        pr = pygame.Rect(vt.x + 2, y - 10, 52, 20)
        pygame.draw.polygon(surf, (0, 0, 0), [(pr.x - 6, pr.centery), (pr.x, pr.y), (pr.right, pr.y), (pr.right, pr.bottom), (pr.x, pr.bottom)])
        f.blit(surf, f"{int(round(vs / 50) * 50):+d}" if abs(vs) > 50 else "0", pr.center, 12, WHITE, mono=True, anchor="center")

    def _rose(self, r):
        s = self.rose_cache.get(r)
        if s is None:
            size = 2 * r + 4
            s = pygame.Surface((size, size), pygame.SRCALPHA)
            c = (r + 2, r + 2)
            pygame.draw.circle(s, (30, 30, 34, 225), c, r)
            for d in range(0, 360, 5):
                L = 12 if d % 10 == 0 else 6
                pygame.draw.line(s, WHITE, polar(c, r - 1, d), polar(c, r - 1 - L, d), 2 if d % 10 == 0 else 1)
            labels = {0: "N", 30: "3", 60: "6", 90: "E", 120: "12", 150: "15", 180: "S", 210: "21", 240: "24", 270: "W", 300: "30", 330: "33"}
            for d, t in labels.items():
                img = self.f.render(t, 16, WHITE, bold=True)
                img = pygame.transform.rotozoom(img, -d, 1.0)
                q = polar(c, r - 28, d)
                s.blit(img, img.get_rect(center=(int(q[0]), int(q[1]))))
            self.rose_cache[r] = s
        return s

    def _hsi(self, surf, rect, world, ui):
        f = self.f
        ac = world.ac
        nav = world.nav_source()
        gps = nav is world.gps
        h = rect.h
        # rosa completa abajo, como en el G1000 real (antes quedaba cortada por el borde inferior)
        r = int(h * 0.21)
        c = (rect.centerx, rect.bottom - r - 6)
        hdg = (ac.heading - world.magvar) % 360          # el AHRS del G1000 da rumbo magnético
        q = round(hdg * 2) / 2.0 % 360
        key = (r, q)
        rc = getattr(self, "_rose_rot", None)
        if rc is None:
            rc = self._rose_rot = {}
        rose = rc.get(key)
        if rose is None:
            if len(rc) > 600:
                rc.clear()
            rose = rc[key] = pygame.transform.rotozoom(self._rose(r), q, 1.0)
        surf.blit(rose, rose.get_rect(center=(int(c[0]), int(c[1]))))
        # marcador de rumbo
        d = world.ap.hdg_bug - hdg
        p = polar(c, r - 2, d)
        pygame.draw.polygon(surf, CYAN, [polar(p, 9, d - 90), polar(p, 9, d + 90), polar(polar(c, r - 12, d), 4, d + 90),
                                         polar(polar(c, r - 12, d), 4, d - 90)])
        # aguja de curso
        crs = nav.obs if not nav.is_loc else (nav.station.course - world.magvar) % 360
        dc = crs - hdg
        col = MAG if gps else GREEN                       # G1000: aguja magenta con GPS, verde con VOR/LOC
        pygame.draw.line(surf, col, polar(c, r - 26, dc), polar(c, r * 0.42, dc), 4)
        pygame.draw.polygon(surf, col, [polar(c, r - 18, dc), polar(polar(c, r - 32, dc), 8, dc - 90), polar(polar(c, r - 32, dc), 8, dc + 90)])
        pygame.draw.line(surf, col, polar(c, -(r - 26), dc), polar(c, -r * 0.42, dc), 4)
        for i in (-2, -1, 1, 2):
            pygame.draw.circle(surf, WHITE, [int(v) for v in polar(polar(c, 0, dc), i * r * 0.14, dc + 90)], 4, 1)
        if nav.valid:
            dev = nav.cdi * 2 * r * 0.14
            base = polar(c, dev, dc + 90)
            pygame.draw.line(surf, col, polar(base, r * 0.38, dc), polar(base, -r * 0.38, dc), 4)
            if nav.to_from:
                tf = polar(c, r * 0.28, dc if nav.to_from == "TO" else dc + 180)
                pygame.draw.polygon(surf, WHITE, [polar(tf, 8, dc if nav.to_from == "TO" else dc + 180),
                                                  polar(tf, 7, dc + 120), polar(tf, 7, dc - 120)])
        # aguja de marcación 2 (ADF): doble línea cian hacia el NDB
        adf = world.adf
        if adf.valid:
            a = adf.relative
            for off in (-3, 3):
                pygame.draw.line(surf, CYAN, polar(polar(c, r * 0.5, a), off, a + 90),
                                 polar(polar(c, r - 22, a), off, a + 90), 2)
                pygame.draw.line(surf, CYAN, polar(polar(c, -r * 0.5, a), off, a + 90),
                                 polar(polar(c, -(r - 22), a), off, a + 90), 2)
            pygame.draw.polygon(surf, CYAN, [polar(c, r - 14, a), polar(polar(c, r - 26, a), 7, a - 90),
                                             polar(polar(c, r - 26, a), 7, a + 90)], 2)
        bb = pygame.Rect(rect.right - 126, rect.bottom - 102, 120, 46)
        pygame.draw.rect(surf, (0, 0, 0), bb, border_radius=4)
        f.blit(surf, f"BRG2 ADF {adf.ident}", (bb.x + 6, bb.y + 4), 13, CYAN, mono=True, bold=True)
        f.blit(surf, f"{adf.freq:4.0f}k " + (f"{adf.dist_nm:4.1f}NM" if adf.valid else "  --NM"), (bb.x + 6, bb.y + 24), 13,
               WHITE, mono=True)
        # avión en el centro
        pygame.draw.line(surf, WHITE, (c[0], c[1] - 16), (c[0], c[1] + 14), 3)
        pygame.draw.line(surf, WHITE, (c[0] - 14, c[1] - 4), (c[0] + 14, c[1] - 4), 3)
        # caja de rumbo
        box = pygame.Rect(0, 0, 58, 24)
        box.midbottom = (c[0], c[1] - r - 2)
        pygame.draw.rect(surf, (0, 0, 0), box)
        pygame.draw.rect(surf, WHITE, box, 1)
        f.blit(surf, f"{hdg:03.0f}°", box.center, 16, WHITE, mono=True, bold=True, anchor="center")
        # información NAV
        info = pygame.Rect(rect.x + 6, rect.bottom - 106, 142, 46)
        pygame.draw.rect(surf, (0, 0, 0), info, border_radius=4)
        src = "GPS " + ("OBS" if nav.obs_mode else nav.scale) if gps else ("LOC1" if nav.is_loc else "VOR1")
        f.blit(surf, f"{src} {nav.ident}", (info.x + 6, info.y + 4), 13, MAG if gps else GREEN, mono=True, bold=True)
        dme = f"{nav.dme_nm:5.1f} NM" if nav.dme_nm is not None else "--.- NM"
        f.blit(surf, f"{'DTK' if gps else 'CRS'}{crs:03.0f} {dme}", (info.x + 6, info.y + 24), 13, WHITE, mono=True)
        hb = pygame.Rect(rect.right - 126, rect.bottom - 52, 120, 46)
        pygame.draw.rect(surf, (0, 0, 0), hb, border_radius=4)
        f.blit(surf, f"HDG {world.ap.hdg_bug:03.0f}°", (hb.x + 6, hb.y + 4), 13, CYAN, mono=True, bold=True)
        f.blit(surf, f"GS {ac.gs / KT:3.0f}KT", (hb.x + 6, hb.y + 24), 13, WHITE, mono=True)
        if gps and nav.obs_mode:
            d = ui.scroll(info)
            if d:
                nav.set_obs(True, nav.obs_course + d)
            if ui.hover(info):
                ui.tooltip = "Rueda: curso del modo OBS del GPS"
        d = ui.scroll(pygame.Rect(c[0] - r, c[1] - r, 2 * r, r))
        if d:
            world.ap.hdg_bug = (world.ap.hdg_bug + d * 5) % 360

    def _top_bar(self, surf, rect, world):
        """Barra superior del PFD. En la pantalla ancha (la de la consola) va en dos filas, como en el G1000: NAV 1 y
        NAV 2 a la izquierda y COM 1, ADF y transpondedor a la derecha, cada radio con su frecuencia activa (verde) y
        la de reserva (blanca); la radio que se está sintonizando con las perillas lleva un recuadro cian."""
        f = self.f
        ap = world.ap
        narrow = rect.w < 560
        bar = pygame.Rect(rect.x, rect.y, rect.w, 26 if narrow else self.BAR_H)
        pygame.draw.rect(surf, (0, 0, 0), bar)
        pygame.draw.line(surf, (60, 66, 76), (bar.x, bar.bottom - 1), (bar.right, bar.bottom - 1))
        # en PFD estrechos (panel 2D) letra más chica, sin el rótulo NAV1/COM1 y los modos del PA más juntos
        fs, fa = (11, 12) if narrow else (13, 15)
        mid = bar.centerx
        k = bar.w / 640.0                                # posiciones proporcionales al ancho
        if narrow:
            f.blit(surf, f"{world.nav1.freq:6.2f}", (bar.x + 6, bar.centery), fs, GREEN, mono=True, anchor="midleft")
            f.blit(surf, f"{world.com_freq:7.3f}", (bar.right - 6, bar.centery), fs, GREEN, mono=True, anchor="midright")
            ya = bar.centery
        else:
            ya = bar.y + 11
            self._radio_rows(surf, bar, world)
            k *= 0.78                                    # los modos del PA entre las radios de la primera fila
        if ap.engaged or ap.fd:
            f.blit(surf, ap.lat, (mid - 70 * k, ya), fa, GREEN, mono=True, bold=True, anchor="center")
            if ap.nav_armed and not narrow:
                f.blit(surf, "LOC" if ap.gs_armed else "VOR", (mid - 120 * k, ya), fs, WHITE, mono=True, anchor="center")
            f.blit(surf, "AP" if ap.engaged else "FD", (mid, ya), fa, GREEN, mono=True, bold=True, anchor="center")
            vt = ap.vert + ("" if narrow else
                            (f" {ap.vs_sel:+.0f}FPM" if ap.vert == "VS" else (f" {ap.alt_sel:.0f}FT" if ap.vert == "ALT" else "")))
            f.blit(surf, vt, (mid + 70 * k, ya), fa, GREEN, mono=True, bold=True, anchor="center")
            if (ap.alt_armed or ap.gs_armed) and not narrow:
                f.blit(surf, "ALTS" if ap.alt_armed else "GS", (mid + 170 * k, ya), fs, WHITE, mono=True, anchor="center")

    BAR_H = 44                  # alto de la barra superior de dos filas

    def _tape_y(self, rect):
        """Borde superior de las cintas de velocidad y altitud: debajo de la barra superior y de la altitud elegida."""
        return rect.y + (rect.h * 0.1 if rect.w < 560 else max(rect.h * 0.1, self.BAR_H + 28))

    def _radio_rows(self, surf, bar, world):
        f = self.f
        sel = getattr(world, "radio_sel", None)
        fn = f.get(13, mono=True)
        gap = 10

        def pair(x, y, label, act, stb, key, right=False):
            """Rótulo, activa y reserva; con right=True se escribe de derecha a izquierda desde x."""
            parts = [(label, COL["grey"]), (act, GREEN), (stb, WHITE)]
            if right:
                parts = [(act, GREEN), (stb, WHITE), (label, COL["grey"])]
                x -= sum(fn.size(t)[0] for t, _ in parts) + gap * 2
            for t, c in parts:
                w = fn.size(t)[0]
                f.blit(surf, t, (x, y), 13, c, mono=True, anchor="midleft")
                if t == stb and key == sel:              # radio que mueven las perillas compartidas
                    pygame.draw.rect(surf, CYAN, (x - 3, y - 9, w + 6, 18), 1, border_radius=2)
                x += w + gap
            return x

        y1, y2 = bar.y + 11, bar.y + 32
        pair(bar.x + 6, y1, "NAV1", f"{world.nav1.freq:6.2f}", f"{world.nav1.standby:6.2f}", "nav1")
        pair(bar.x + 6, y2, "NAV2", f"{world.nav2.freq:6.2f}", f"{world.nav2.standby:6.2f}", "nav2")
        pair(bar.right - 6, y1, "COM1", f"{world.com_freq:7.3f}", f"{world.com_standby:7.3f}", "com1", right=True)
        # transpondedor: código (el dígito que se está cambiando, subrayado) y modo; IDENT durante 18 s
        code = f"{int(world.xpdr):04d}"
        ident = world.sim_time - getattr(world, "xpdr_ident_t", -99.0) < 18.0
        mode = "IDNT" if ident else ("ALT" if world.ac.sys.avionics_ok else "STBY")
        x = bar.right - 6 - fn.size(f"{code} {mode}")[0]
        f.blit(surf, "XPDR", (x - gap - fn.size("XPDR")[0], y2), 13, COL["grey"], mono=True, anchor="midleft")
        f.blit(surf, code, (x, y2), 13, GREEN, mono=True, anchor="midleft")
        dg = getattr(world, "xpdr_digit", None)
        if dg is not None:
            cw = fn.size("0")[0]
            pygame.draw.line(surf, CYAN, (x + dg * cw, y2 + 8), (x + (dg + 1) * cw - 1, y2 + 8), 2)
        f.blit(surf, mode, (x + fn.size(code + " ")[0], y2), 13, (255, 200, 0) if ident else WHITE, mono=True, anchor="midleft")
        xa = x - gap - fn.size("XPDR")[0] - 18
        pair(xa, y2, "ADF", f"{world.adf.freq:4.0f}", f"{world.adf.standby:4.0f}", "adf", right=True)

    # ================================================================ MFD
    def _build_map(self, world):
        T = world.terrain
        col = T.colors.copy()
        h = T.h
        gx, gy = np.gradient(h, T.cell)
        shade = np.clip(1.0 + (-gx * 0.7 - gy * 0.7) * 2.0, 0.55, 1.35)[..., None]
        col = col * shade
        water = h < 0
        col[water] = np.array([0.08, 0.2, 0.42])
        img = (np.clip(col, 0, 1) * 255).astype(np.uint8)
        # filas = norte (i), columnas = este (j) -> pantalla: x = este, y = -norte
        arr = np.transpose(img, (1, 0, 2))[:, ::-1, :]
        self.map_img = pygame.surfarray.make_surface(arr)
        self.map_heights = h
        self.map_m_per_px = T.cell
        self.map_half = T.half

    def _taws(self, world):
        h = self.map_heights
        alt = world.ac.alt_msl
        rgba = np.zeros(h.shape + (4,), np.uint8)
        red = h > alt - 30
        yel = (h > alt - 150) & ~red
        rgba[yel] = (230, 200, 0, 90)
        rgba[red] = (230, 30, 20, 140)
        arr = np.transpose(rgba, (1, 0, 2))[:, ::-1, :]
        s = pygame.Surface(arr.shape[:2], pygame.SRCALPHA)
        pygame.surfarray.pixels3d(s)[...] = arr[..., :3]
        pygame.surfarray.pixels_alpha(s)[...] = arr[..., 3]
        self.taws_img = s

    # ------------------------------------------------------------ GPS: elegir y escribir puntos
    def gps_typing(self):
        """La lista D→ o «añadir al plan» está abierta: el teclado escribe en el GPS y no mueve el avión."""
        return self.gps_page in ("dto", "add")

    def gps_choose(self, gps, wp):
        if self.gps_page == "dto":
            gps.direct_to(wp)
        else:
            gps.add(wp)
        self.gps_page = "fpl" if self.gps_page == "add" else None
        self.gps_query = ""

    def gps_key(self, gps, key, text):
        """Una tecla con la lista abierta: letras y números escriben, Retroceso borra, Enter elige el primer punto que
        coincide y Esc cierra. Devuelve True si la tecla era para el GPS."""
        if key == pygame.K_ESCAPE:
            self.gps_page, self.gps_query = None, ""
            return True
        if key == pygame.K_BACKSPACE:
            self.gps_query = self.gps_query[:-1]
            return True
        if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            found = gps.search(self.gps_query, 1) if self.gps_query else []
            if found:
                self.gps_choose(gps, found[0][0])
            return True
        if text and (text.isalnum() or text in " -") and len(self.gps_query) < 12:
            self.gps_query += text.upper()
            return True
        return False

    # ------------------------------------------------------------ combustible (franja de motor del MFD)
    def _fuel_block(self, surf, r, world, compact=False):
        """Medidor de combustible: un tanque a cada lado con su nivel en color (verde, amarillo por debajo del 25 %,
        rojo por debajo del 12 %), litros de cada uno, total, consumo y autonomía, con aviso de reserva por debajo de
        45 minutos. En pantallas chicas, versión compacta: dos barras y una línea con total y autonomía."""
        f = self.f
        ac = world.ac
        sysm = ac.sys
        cap = ac.t.fuel_capacity / 2
        tank = sysm.fuel_l / 2                           # el selector en AMBOS reparte el consumo entre los dos tanques
        flow = sum(en.fuel_flow for en in sysm.engines)
        endur_h = sysm.fuel_l / flow if flow > 1.0 else None
        frac = tank / cap if cap > 0 else 0.0
        col = (40, 190, 80) if frac > 0.25 else ((235, 190, 40) if frac > 0.12 else (235, 50, 40))
        reserve = endur_h is not None and endur_h < 0.75
        pygame.draw.rect(surf, (6, 8, 12), r, border_radius=4)
        pygame.draw.rect(surf, (235, 50, 40) if reserve else (60, 66, 76), r, 1, border_radius=4)
        if compact:
            lh = max(10, (r.h - 6) / 3)
            for i, lab in enumerate(("I", "D")):
                yb = r.y + 3 + i * lh
                f.blit(surf, lab, (r.x + 4, yb + lh / 2), 10, COL["grey"], bold=True, anchor="midleft")
                bar = pygame.Rect(r.x + 14, yb + 2, r.w * 0.52, lh - 4)
                pygame.draw.rect(surf, (24, 28, 34), bar)
                pygame.draw.rect(surf, col, (bar.x, bar.y, bar.w * clamp(frac, 0, 1), bar.h))
                f.blit(surf, f"{tank:.0f}L", (r.right - 3, yb + lh / 2), 11, WHITE, mono=True, bold=True, anchor="midright")
            if endur_h is not None:
                txt = ("RES " if reserve else "") + f"{int(endur_h)}h{int(endur_h % 1 * 60):02d}"
            else:
                txt = "MOTOR OFF"
            f.blit(surf, txt, (r.centerx, r.y + 3 + 2.5 * lh), 11, (235, 50, 40) if reserve else (120, 220, 255),
                   mono=True, bold=True, anchor="center")
            return
        f.blit(surf, "COMBUSTIBLE", (r.centerx, r.y + 4), 12, COL["grey"], bold=True, anchor="midtop")
        # un tanque en el centro de cada mitad, con su nombre y sus litros debajo (nada se sale del recuadro)
        gw, gh = r.w * 0.24, r.h * 0.38
        for i, lab in enumerate(("IZQ", "DER")):
            cx = r.x + r.w * (0.25 + 0.5 * i)
            g = pygame.Rect(cx - gw / 2, r.y + 20, gw, gh)
            pygame.draw.rect(surf, (24, 28, 34), g, border_radius=3)
            fill = pygame.Rect(g.x, g.bottom - g.h * clamp(frac, 0, 1), g.w, g.h * clamp(frac, 0, 1))
            pygame.draw.rect(surf, col, fill, border_radius=3)
            pygame.draw.rect(surf, (120, 128, 140), g, 1, border_radius=3)
            for k in (0.25, 0.5, 0.75):
                yk = g.bottom - g.h * k
                pygame.draw.line(surf, (120, 128, 140), (g.right, yk), (g.right + 3, yk), 1)
            f.blit(surf, f"{lab} {tank:.0f} L", (cx, g.bottom + 3), 13, WHITE, mono=True, bold=True, anchor="midtop")
        yy = r.y + 20 + gh + 20
        f.blit(surf, f"TOTAL {sysm.fuel_l:.0f} L · {sysm.fuel_l / 3.785:.0f} gal", (r.centerx, yy), 12, WHITE,
               mono=True, bold=True, anchor="midtop")
        if endur_h is not None:
            hh, mm = int(endur_h), int(endur_h % 1 * 60)
            txt = f"AUTONOMÍA {hh} h {mm:02d}" + (" · RES" if reserve else "")
            blink = reserve and int(time.time() * 2) % 2 == 0
            f.blit(surf, txt, (r.centerx, yy + 16), 12, (235, 50, 40) if reserve and not blink else
                   ((255, 120, 100) if reserve else (120, 220, 255)), mono=True, bold=True, anchor="midtop")
            f.blit(surf, f"{flow:.1f} L/h", (r.centerx, yy + 32), 11, COL["grey"], mono=True, anchor="midtop")
        else:
            f.blit(surf, "motor parado", (r.centerx, yy + 16), 12, COL["grey"], anchor="midtop")

    # ------------------------------------------------------------ GPS desde la consola (teclas y perillas del G1000)
    ALPH = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    MAP_RANGES = [2, 5, 10, 20, 40]

    def _approaches(self, world):
        from sim import rnav
        ac = world.ac
        return sorted(rnav.for_world(world), key=lambda a: math.hypot(a.airport.ref[0] - ac.pos[0], a.airport.ref[1] - ac.pos[1]))

    def _gps_rows(self, world):
        """Filas elegibles con la perilla FMS en la página abierta."""
        gps = world.gps
        if self.gps_page in ("dto", "add"):
            return [r[0] for r in gps.search(self.gps_query, 12)]
        if self.gps_page == "apr":
            return self._approaches(world)
        if self.gps_page == "fpl":
            return list(gps.plan) + ["+", "RNAV", "BORRAR"]
        return []

    def gps_open(self, page):
        """Tecla D→ (dto), FPL (fpl) o PROC (apr): abre la página, o la cierra si ya estaba abierta."""
        self.gps_page = None if self.gps_page == page else page
        self.gps_query, self.gps_cursor, self.gps_newchar = "", 0, False

    def gps_fms(self, world, big=0, small=0, push=False):
        """Perilla FMS. En D→ / añadir, la pequeña deletrea el identificador (cambia la última letra; pulsar la perilla
        pasa a la siguiente) y la grande recorre los puntos que coinciden. En el plan y en RNAV, cualquiera de las dos
        mueve el cursor."""
        if self.gps_page is None:
            return
        typing = self.gps_page in ("dto", "add")
        if typing and push:
            if self.gps_query and len(self.gps_query) < 6:
                self.gps_newchar = True
            return
        if typing and small:
            A = self.ALPH
            if not self.gps_query or self.gps_newchar:
                self.gps_query += A[0] if small > 0 else A[-1]
                self.gps_newchar = False
            else:
                c = self.gps_query[-1]
                i = A.index(c) if c in A else 0
                self.gps_query = self.gps_query[:-1] + A[(i + small) % len(A)]
            self.gps_cursor = 0
            return
        n = len(self._gps_rows(world))
        if n:
            self.gps_cursor = (self.gps_cursor + (big or small)) % n

    def gps_enter(self, world):
        """ENT: elige la fila del cursor."""
        rows = self._gps_rows(world)
        if not rows:
            return
        row = rows[min(self.gps_cursor, len(rows) - 1)]
        gps = world.gps
        if self.gps_page in ("dto", "add"):
            self.gps_choose(gps, row)
        elif self.gps_page == "apr":
            from sim import rnav
            gps.load_approach(row, *rnav.entry(row, world.ac.pos))
            self.gps_page, self.gps_cursor = "fpl", 0
        elif row == "+":
            self.gps_open("add")
        elif row == "RNAV":
            self.gps_open("apr")
        elif row == "BORRAR":
            gps.clear()
            self.gps_cursor = 0
        else:
            gps.activate(self.gps_cursor)

    def gps_clr(self, world):
        """CLR: borra la última letra (o cierra si no hay nada escrito); en el plan quita el punto del cursor."""
        if self.gps_page in ("dto", "add") and self.gps_query:
            self.gps_query, self.gps_newchar, self.gps_cursor = self.gps_query[:-1], False, 0
        elif self.gps_page == "fpl" and self.gps_cursor < len(world.gps.plan):
            world.gps.remove(self.gps_cursor)
            self.gps_cursor = min(self.gps_cursor, max(0, len(world.gps.plan) - 1))
        else:
            self.gps_page, self.gps_query, self.gps_cursor = None, "", 0

    def _first_row(self, n, vis):
        """Primera fila que se dibuja en una lista más larga que la caja, para que el cursor siempre se vea."""
        return max(0, min(self.gps_cursor - vis + 1, n - vis))

    def map_range_step(self, d):
        """Perilla RANGE: + aleja el mapa, − lo acerca."""
        opts = self.MAP_RANGES
        i = opts.index(self.map_range_nm) if self.map_range_nm in opts else 2
        self.map_range_nm = opts[int(clamp(i + d, 0, len(opts) - 1))]

    def _gps_keys(self, surf, mp, world, ui):
        """Teclas del GPS en el mapa: D→ (directo a), FPL (plan de vuelo), OBS y selector CDI GPS/VLOC; y sus
        listas, que se eligen con el ratón: los puntos más cercanos o, al escribir un identificador con el teclado,
        los que coinciden (core.App.gps_typing)."""
        f = self.f
        gps = world.gps
        # fila de teclas encima de la de TAWS, repartida en el ancho del mapa (en pantallas estrechas el mapa es angosto)
        y = mp.bottom - 54
        bw = (mp.w - 16 - 12) / 4
        narrow = mp.w < 360
        keys = [("D→", "dto", "Directo a: teclee el identificador o elija un punto cercano"),
                ("FPL", "fpl", "Plan de vuelo: añadir (tecleando o de la lista), activar y quitar puntos")]
        x = mp.x + 8
        for lab, page, tip in keys:
            if ui.cockpit_button(surf, (x, y, bw, 22), lab, active=self.gps_page == page, size=11, tip=tip):
                self.gps_page = None if self.gps_page == page else page
                self.gps_query = ""
            x += bw + 4
        if ui.cockpit_button(surf, (x, y, bw, 22), "OBS", active=gps.obs_mode, size=11,
                             tip="Modo OBS: curso elegido hacia el punto activo (rueda sobre la caja GPS del HSI)"):
            gps.set_obs(not gps.obs_mode, gps.dtk if gps.valid else None)
        x += bw + 4
        if ui.cockpit_button(surf, (x, y, bw, 22), world.cdi_src if narrow else "CDI " + world.cdi_src,
                             active=world.cdi_src == "GPS", size=11,
                             tip="CDI: qué siguen el HSI y el piloto automático (NAV): GPS o VLOC (radio NAV 1) · F7"):
            world.cdi_src = "GPS" if world.cdi_src == "VLOC" else "VLOC"
        if self.gps_page is None:
            return
        box = (pygame.Rect(mp.x + 4, mp.y + 44, mp.w - 8, mp.h - 104) if narrow else
               pygame.Rect(mp.x + mp.w * 0.42, mp.y + 44, mp.w * 0.56, mp.h - 104))
        pygame.draw.rect(surf, (6, 10, 16), box, border_radius=6)
        pygame.draw.rect(surf, (90, 100, 120), box, 1, border_radius=6)
        rh = 22
        yy = box.y + 6
        if self.gps_page in ("dto", "add"):
            f.blit(surf, "DIRECTO A" if self.gps_page == "dto" else "AÑADIR AL PLAN", (box.x + 8, yy), 13, MAG, bold=True)
            yy += rh
            # línea de escritura: el identificador (o parte del nombre) que se teclea; con el cursor parpadeando
            cursor = "_" if int(pygame.time.get_ticks() / 500) % 2 == 0 else " "
            hint = self.gps_query + cursor if self.gps_query else ("Escriba: " if not narrow else "") + "ID…" + cursor
            f.blit(surf, hint, (box.x + 8, yy + 2), 12, WHITE if self.gps_query else COL["grey"], mono=True, bold=True)
            if ui.hover(box):
                ui.tooltip = "Teclee un identificador (VLC, SVBS…) o parte del nombre · Enter: el primero · Esc: cerrar"
            yy += rh
            results = gps.search(self.gps_query, 12)
            if not results:
                f.blit(surf, "Ningún punto coincide", (box.x + 8, yy + 2), 11, COL["grey"])
            first = self._first_row(len(results), max(3, int((box.bottom - yy - 8) / rh)))
            for i, (wp, dis, brg) in list(enumerate(results))[first:first + max(3, int((box.bottom - yy - 8) / rh))]:
                lab = f"{wp.ident} {dis:.1f}" if narrow else f"{wp.ident:5s} {wp.kind:3s} {dis:5.1f} NM {brg:03.0f}°"
                if ui.cockpit_button(surf, (box.x + 6, yy, box.w - 12, rh - 2), lab, size=11, active=i == self.gps_cursor,
                                     tip=f"{wp.kind} {wp.name} · {dis:.1f} NM · rumbo {brg:03.0f}°"):
                    self.gps_choose(gps, wp)
                yy += rh
        elif self.gps_page == "apr":
            from sim import rnav
            f.blit(surf, "APROXIMACIÓN RNAV", (box.x + 8, yy), 13, MAG, bold=True)
            yy += rh
            f.blit(surf, "Entrenamiento: no publicadas", (box.x + 8, yy), 11, (255, 200, 0))
            yy += rh - 4
            ac = world.ac
            aprs = sorted(rnav.for_world(world), key=lambda a: math.hypot(a.airport.ref[0] - ac.pos[0],
                                                                           a.airport.ref[1] - ac.pos[1]))
            vis = max(1, int((box.bottom - yy - 8) / rh))
            first = self._first_row(len(aprs), vis)
            for i, apr in list(enumerate(aprs))[first:first + vis]:
                if ui.cockpit_button(surf, (box.x + 6, yy, box.w - 12, rh - 2), apr.short, size=11,
                                     active=i == self.gps_cursor,
                                     tip=f"{apr.title} · desde el IAF del lado por el que llega · DA "
                                         f"{apr.da_ft:.0f} ft (LPV), MDA {apr.mda_ft:.0f} ft (LNAV)"):
                    gps.load_approach(apr, *rnav.entry(apr, ac.pos))
                    self.gps_page = "fpl"
                yy += rh
        else:
            title = "PLAN DE VUELO" + (f" · {gps.approach.short}" if gps.approach is not None and not narrow else "")
            f.blit(surf, title, (box.x + 8, yy), 13, MAG, bold=True)
            yy += rh
            if not gps.plan:
                f.blit(surf, "Vacío: añada puntos con «+ Añadir».", (box.x + 8, yy + 2), 11, COL["grey"])
                yy += rh
            vis = max(1, int((box.bottom - yy - 2 * rh) / rh) + 1)
            first = self._first_row(len(gps.plan), vis) if self.gps_cursor < len(gps.plan) else max(0, len(gps.plan) - vis)
            for i, wp in list(enumerate(gps.plan))[first:]:
                on = i == gps.active and gps.direct is None
                if i == self.gps_cursor:      # fila elegida con la perilla FMS
                    pygame.draw.rect(surf, COL["button_on"], (box.x + 4, yy, box.w - 70, rh - 2), border_radius=4)
                f.blit(surf, ("▶ " if on else "  ") + (wp.ident if narrow else f"{wp.ident} {wp.kind}"), (box.x + 8, yy + 3),
                       12, MAG if on else WHITE, mono=True, bold=on)
                if ui.cockpit_button(surf, (box.right - 62, yy, 28, rh - 2), "▶", size=10,
                                     tip="Activar el tramo hacia este punto"):
                    gps.activate(i)
                if ui.cockpit_button(surf, (box.right - 32, yy, 26, rh - 2), "×", size=11, tip="Quitar del plan"):
                    gps.remove(i)
                    break
                yy += rh
                if yy > box.bottom - 2 * rh:
                    break
            by = box.bottom - rh - 4
            third = (box.w - 20) / 3
            cur = self.gps_cursor - len(gps.plan)       # 0, 1 o 2: uno de los botones de abajo, elegido con la perilla
            if ui.cockpit_button(surf, (box.x + 6, by, third, rh - 2), "+" if narrow else "+ Añadir", size=11,
                                 active=cur == 0, tip="Añadir un punto (tecleando o de la lista)"):
                self.gps_page = "add"
                self.gps_query = ""
            if ui.cockpit_button(surf, (box.x + 10 + third, by, third, rh - 2), "RNAV", size=11, active=cur == 1,
                                 tip="Cargar una aproximación RNAV (GPS) de entrenamiento"):
                self.gps_page = "apr"
            if ui.cockpit_button(surf, (box.x + 14 + 2 * third, by, third, rh - 2), "Borrar", size=11, active=cur == 2):
                gps.clear()

    def mfd(self, surf, rect, world, ui):
        f = self.f
        ac = world.ac
        sysm = ac.sys
        e = sysm.engine
        rect = pygame.Rect(rect)
        pygame.draw.rect(surf, (8, 8, 10), rect.inflate(4, 4), border_radius=3)
        if not sysm.electric_ok:
            pygame.draw.rect(surf, (2, 2, 3), rect)
            return
        if self.map_img is None:
            self._build_map(world)
        now = time.time()
        if now - self.track_t > 2.0:
            self.track_t = now
            self.track.append((ac.pos[0], ac.pos[1]))
            self.track = self.track[-400:]
        # franja de motor
        es = pygame.Rect(rect.x, rect.y, int(rect.w * 0.27), rect.h)
        pygame.draw.rect(surf, (12, 14, 18), es)
        x, y, w = es.x + 6, es.y + 6, es.w - 12
        # arcos de RPM (uno por motor)
        engs = sysm.engines
        rmax = 2300.0 if ac.t.fadec else 2700.0
        nE = len(engs)
        for i, en in enumerate(engs):
            c = (es.x + es.w * (i + 0.5) / nE, y + 46)
            rr = 38 if nE == 1 else 30
            for a0, a1, col in ((-120, 60, (40, 180, 70)), (60, 120, (230, 40, 30))):
                for d in range(a0, a1, 3):
                    pygame.draw.line(surf, col, polar(c, rr, d), polar(c, rr - 6, d), 3)
            ang = -120 + clamp(en.rpm / rmax, 0, 1.15) * 240
            pygame.draw.line(surf, WHITE, c, polar(c, rr - 2, ang), 3)
            f.blit(surf, f"{en.rpm:4.0f}", (c[0], c[1] + 12), 15 if nE == 1 else 13, WHITE, mono=True, bold=True, anchor="center")
            lab = "RPM" if nE == 1 else ("RPM I" if i == 0 else "RPM D")
            f.blit(surf, lab, (c[0], c[1] + 28), 11, COL["grey"], anchor="center")
        from .gauges import bar_gauge
        y = c[1] + 40
        cap = ac.t.fuel_capacity / 2
        rows = [("FLUJO L/H", sum(en.fuel_flow for en in sysm.engines), 0, 70 * len(sysm.engines), (5, 50 * len(sysm.engines))),
                ("P ACEITE", e.oil_press, 0, 115, (50, 90)),
                ("T ACEITE", e.oil_temp, 50, 260, (100, 245)),
                ("EGT °F", e.egt, 800, 1650, (1150, 1550)),
                ("CHT °F", e.cht, 100, 500, (200, 435)),
                ("VOLTS", sysm.bus_volts, 20, 32, (24.5, 29.5))]
        if ac.t.fadec:
            if sysm.twin:
                rows[0:0] = [("CARGA I %", sysm.engines[0].load, 0, 100, (0, 100)),
                             ("CARGA D %", sysm.engines[1].load, 0, 100, (0, 100))]
                rows = [r_ for r_ in rows if r_[0] not in ("EGT °F", "CHT °F")]
            else:
                rows.insert(0, ("CARGA %", e.load, 0, 100, (0, 100)))
        elif not ac.t.fixed_pitch:
            rows.insert(0, ("MAN IN", e.map_inhg, 10, 35, (15, 25)))
        # bloque de combustible al pie: grande en pantallas amplias (la de instrumentos de la consola) y compacto en las
        # chicas (panel 2D), siempre dejando al menos 15 px a cada barra de motor
        compact = es.w < 170 or es.bottom - y < 330
        fb = 62 if compact else max(150, int(es.h * 0.34))
        fb = min(fb, max(40, int(es.bottom - y - 4 - 15 * len(rows))))
        rh = (es.bottom - fb - y - 4) / len(rows)
        for lab, v, lo, hi, gr in rows:
            bar_gauge(f, surf, (x, y, w, rh - 3), lab, v, lo, hi, gr, fmt="{:.1f}" if hi < 40 else "{:.0f}")
            y += rh
        self._fuel_block(surf, pygame.Rect(es.x + 4, es.bottom - fb, es.w - 8, fb - 4), world, compact)
        # mapa móvil
        mp = pygame.Rect(es.right + 4, rect.y, rect.right - es.right - 4, rect.h)
        rng_m = self.map_range_nm * NM
        scale = mp.h / (2 * rng_m) * self.map_m_per_px       # px de pantalla por px de mapa
        key = (self.map_range_nm, mp.size)
        if self.map_key != key:
            self.map_key = key
            sz = (int(self.map_img.get_width() * scale), int(self.map_img.get_height() * scale))
            self.map_scaled = pygame.transform.smoothscale(self.map_img, sz) if max(sz) < 9000 else None
            self.taws_scaled = None
        if self.taws and now - self.taws_time > 1.0:
            self.taws_time = now
            self._taws(world)
            sz = (int(self.taws_img.get_width() * scale), int(self.taws_img.get_height() * scale))
            self.taws_scaled = pygame.transform.scale(self.taws_img, sz) if max(sz) < 9000 else None
        clip = surf.get_clip()
        surf.set_clip(mp)
        pygame.draw.rect(surf, (8, 22, 50), mp)
        ppm = mp.h / (2 * rng_m)

        def to_px(nx, ey):
            return (mp.centerx + ey * ppm - ac.pos[1] * ppm, mp.centery - nx * ppm + ac.pos[0] * ppm)
        if self.map_scaled is not None:
            ox, oy = to_px(self.map_half, -self.map_half)
            surf.blit(self.map_scaled, (ox, oy))
            if self.taws and getattr(self, "taws_scaled", None) is not None:
                surf.blit(self.taws_scaled, (ox, oy))
        # meteorología por satélite (como NEXRAD): la tormenta en verde, amarillo y rojo
        wx = world.weather
        if getattr(wx, "storm", False):
            lay = pygame.Surface(mp.size, pygame.SRCALPHA)
            c = to_px(wx.storm_n, wx.storm_e)
            c = (c[0] - mp.x, c[1] - mp.y)
            for k, col in ((2.4, (40, 200, 60, 110)), (1.3, (240, 220, 30, 150)), (0.8, (230, 40, 30, 190)),
                           (0.35, (220, 40, 220, 200))):
                rr = wx.storm_r * k * ppm
                pts = [(c[0] + math.cos(a) * rr * (0.85 + 0.15 * math.sin(a * 3 + k)),
                        c[1] + math.sin(a) * rr * (0.85 + 0.15 * math.cos(a * 2 + k))) for a in
                       [i * math.pi / 12 for i in range(24)]]
                pygame.draw.polygon(lay, col, pts)
            surf.blit(lay, mp.topleft)
            f.blit(surf, "NEXRAD", (mp.x + 8, mp.y + 42), 12, (90, 220, 90), bold=True)
        # aeródromos y radioayudas
        for apt in world.airports:
            for rw in apt.runways:
                a = to_px(*rw.threshold)
                b = to_px(*rw.far_end)
                pygame.draw.line(surf, WHITE, a, b, max(3, int(rw.width * ppm)))
            p = to_px(*apt.ref)
            pygame.draw.circle(surf, CYAN, p, 10, 2)
            f.blit(surf, apt.ident, (p[0] + 12, p[1] - 18), 13, WHITE, bold=True)
        for nv in world.navaids:
            if nv.kind == "VOR":
                p = to_px(*nv.pos)
                pts = [polar(p, 8, d) for d in range(30, 390, 60)]
                pygame.draw.polygon(surf, CYAN, pts, 2)
                f.blit(surf, nv.ident, (p[0] + 10, p[1] + 2), 12, CYAN, bold=True)
            elif nv.kind == "NDB":
                p = to_px(*nv.pos)
                for d in range(0, 360, 45):
                    pygame.draw.circle(surf, (200, 120, 220), [int(v) for v in polar(p, 7, d)], 2)
                pygame.draw.circle(surf, (200, 120, 220), p, 2)
                f.blit(surf, nv.ident, (p[0] + 10, p[1] + 2), 12, (200, 120, 220), bold=True)
            elif nv.kind == "ILS":
                a = to_px(*nv.threshold)
                b = to_px(*(nv.threshold - nv.dir * 10 * NM))
                pygame.draw.line(surf, (60, 200, 80), a, b, 1)
        # ruta planificada (magenta, como el plan de vuelo del G1000)
        route = getattr(world, "route", None)
        if route:
            pts = [to_px(p[0], p[1]) for p in route]
            pygame.draw.lines(surf, MAG, False, pts, 4)
            for q in pts[1:-1]:
                pygame.draw.circle(surf, MAG, q, 7, 2)
        # plan de vuelo del GPS: tramos en blanco, el activo en magenta (como el G1000)
        gps = world.gps
        if gps.plan:
            pts = [to_px(*wp.pos) for wp in gps.plan]
            if len(pts) > 1:
                pygame.draw.lines(surf, WHITE, False, pts, 2)
        tgt = gps.target
        if tgt is not None and gps.valid:
            if gps.obs_mode:
                crs = math.radians(world.true(gps.obs_course))
                a = to_px(*(tgt.pos - np.array([math.cos(crs), math.sin(crs)]) * 20 * NM))
                b = to_px(*(tgt.pos + np.array([math.cos(crs), math.sin(crs)]) * 20 * NM))
            else:
                a, b = to_px(*gps.leg_from()), to_px(*tgt.pos)
            pygame.draw.line(surf, MAG, a, b, 4)
        for i, wp in enumerate(gps.plan + ([gps.direct] if gps.direct is not None else [])):
            q = to_px(*wp.pos)
            on = wp is tgt
            pygame.draw.circle(surf, MAG if on else WHITE, q, 6, 0 if on else 2)
            f.blit(surf, wp.ident, (q[0] + 9, q[1] - 22), 13, MAG if on else WHITE, bold=True)
        # traza
        if len(self.track) > 1:
            pts = [to_px(*p) for p in self.track] + [to_px(ac.pos[0], ac.pos[1])]
            pygame.draw.lines(surf, MAG, False, pts, 2)
        # tráfico (símbolos TIS/TAS: rombo blanco = otro tráfico, círculo amarillo = aviso)
        tr = getattr(world, "traffic", None)
        if tr is not None:
            ta = tr.ta_alert[0] if tr.ta_alert else None
            for p in tr.planes:
                q = to_px(p.pos[0], p.pos[1])
                if not mp.collidepoint(q):
                    continue
                rel = round((p.alt_ft - ac.alt_msl / FT) / 100)
                if p is ta:
                    pygame.draw.circle(surf, (255, 210, 0), q, 7)
                    col = (255, 210, 0)
                else:
                    pts = [(q[0], q[1] - 7), (q[0] + 6, q[1]), (q[0], q[1] + 7), (q[0] - 6, q[1])]
                    near = abs(rel) <= 12 and math.hypot(p.pos[0] - ac.pos[0], p.pos[1] - ac.pos[1]) < 6 * NM
                    pygame.draw.polygon(surf, WHITE, pts, 0 if near else 2)
                    col = WHITE
                if not p.on_ground:
                    lab = f"{rel:+03d}" if rel else "00"
                    ty = q[1] - 20 if rel > 0 else q[1] + 9
                    f.blit(surf, lab, (q[0], ty), 12, col, mono=True, bold=True, anchor="midtop")
                    if abs(p.vs) > 2.5:
                        ax = q[0] + 11
                        up = p.vs > 0
                        pygame.draw.line(surf, col, (ax, q[1] - 6), (ax, q[1] + 6), 2)
                        tip = (ax, q[1] - 7) if up else (ax, q[1] + 7)
                        pygame.draw.polygon(surf, col, [tip, (ax - 4, tip[1] + (5 if up else -5)), (ax + 4, tip[1] + (5 if up else -5))])
        # anillo de alcance
        pygame.draw.circle(surf, (200, 200, 200), mp.center, int(mp.h * 0.25), 1)
        f.blit(surf, f"{self.map_range_nm / 2:g}", (mp.centerx + mp.h * 0.18, mp.centery - mp.h * 0.18), 12, WHITE)
        # avión
        d = ac.heading
        c = mp.center
        pts = [polar(c, 12, d), polar(c, 8, d + 140), polar(c, 2, d + 180), polar(c, 8, d - 140)]
        pygame.draw.polygon(surf, WHITE, pts)
        pygame.draw.line(surf, WHITE, polar(c, 10, d - 90), polar(c, 10, d + 90), 3)
        tp = polar(c, ac.gs * 120 * ppm, ac.track)
        pygame.draw.line(surf, (255, 255, 255), c, tp, 1)
        surf.set_clip(clip)
        f.blit(surf, "N↑", (mp.x + 8, mp.y + 6), 14, WHITE, bold=True)
        if not world.is_school:
            f.blit(surf, "© Esri, Maxar · OurAirports", (mp.x + 6, mp.bottom - 44), 10, (230, 230, 230))
        f.blit(surf, f"{self.map_range_nm} NM", (mp.right - 8, mp.y + 6), 14, WHITE, bold=True, anchor="topright")
        if gps.valid:
            ete = gps.ete_s
            if mp.w < 360:
                txt = f"→{gps.ident} {gps.dis_nm:.1f}NM {gps.dtk:03.0f}°"
            else:
                txt = (f"→ {gps.ident}  {gps.dis_nm:4.1f} NM  DTK {gps.dtk:03.0f}°" +
                       (f"  ETE {int(ete // 60)}:{int(ete % 60):02d}" if ete is not None else ""))
            f.blit(surf, txt, (mp.x + 8, mp.y + 24), 12, MAG, mono=True, bold=True)
        tb = pygame.Rect(mp.right - 70, mp.bottom - 28, 62, 22)
        if ui.cockpit_button(surf, tb, "TAWS", active=self.taws, size=12, tip="Alerta de terreno (amarillo: a menos de 500 ft, rojo: a menos de 100 ft)"):
            self.taws = not self.taws
        self._gps_keys(surf, mp, world, ui)
        d = ui.scroll(mp)
        if d:
            opts = [2, 5, 10, 20, 40]
            i = opts.index(self.map_range_nm) if self.map_range_nm in opts else 2
            self.map_range_nm = opts[clamp(i - d, 0, len(opts) - 1)]
        if ui.hover(mp):
            ui.tooltip = "Rueda: escala del mapa"
