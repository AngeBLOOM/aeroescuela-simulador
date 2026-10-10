"""Instrumentos analógicos dibujados con pygame (esferas en caché + agujas por fotograma)."""
import math

import pygame

from sim.mathx import clamp
from . import assets
from .ui import COL, polar

BEZEL = (58, 60, 64)
FACE = (14, 14, 16)
MARK = (235, 235, 230)


def arc_band(surf, c, r_in, r_out, d0, d1, color, steps=None):
    if d1 < d0:
        d0, d1 = d1, d0
    steps = steps or max(4, int(abs(d1 - d0) / 3))
    pts = [polar(c, r_out, d0 + (d1 - d0) * i / steps) for i in range(steps + 1)]
    pts += [polar(c, r_in, d1 - (d1 - d0) * i / steps) for i in range(steps + 1)]
    pygame.draw.polygon(surf, color, pts)


def needle(surf, c, deg, length, width, color, tail=0.0):
    p_tip = polar(c, length, deg)
    t = polar(c, tail, deg + 180) if tail else c
    poly = [p_tip, polar(c, width / 2, deg + 90), polar(t, width / 2, deg + 90),
            polar(t, width / 2, deg - 90), polar(c, width / 2, deg - 90)]
    pygame.draw.polygon(surf, color, poly)
    pygame.draw.aalines(surf, color, True, poly)


def ticks(surf, c, r, d0, d1, n, length, width, color=MARK):
    for i in range(n + 1):
        d = d0 + (d1 - d0) * i / n
        pygame.draw.line(surf, color, polar(c, r, d), polar(c, r - length, d), width)


class Gauges:
    def __init__(self, fonts):
        self.f = fonts
        self.cache = {}

    # ------------------------------------------------------------ utilidades
    def _blank(self, r):
        s = pygame.Surface((2 * r + 4, 2 * r + 4), pygame.SRCALPHA)
        c = (r + 2, r + 2)
        dial = assets.scaled("esfera_vacia.png", (2 * r * 0.97, 2 * r * 0.97))
        if dial is not None:
            pygame.draw.circle(s, (6, 6, 7), c, int(r * 0.97))
            s.blit(dial, dial.get_rect(center=c))
        else:
            pygame.draw.circle(s, BEZEL, c, r + 1)
            pygame.draw.circle(s, (30, 31, 34), c, r - 1)
            pygame.draw.circle(s, FACE, c, int(r * 0.93))
        return s, c

    def _mask(self, r):
        key = ("mask", r)
        m = self.cache.get(key)
        if m is None:
            m = pygame.Surface((2 * r + 4, 2 * r + 4), pygame.SRCALPHA)
            m.fill((255, 255, 255, 0))
            pygame.draw.circle(m, (255, 255, 255, 255), (r + 2, r + 2), int(r * 0.93))
            self.cache[key] = m
        return m

    def _text(self, surf, txt, pos, size, color=MARK, bold=False, anchor="center"):
        return self.f.blit(surf, txt, pos, size, color, bold=bold, anchor=anchor)

    def _face(self, name, r, painter):
        key = (name, r)
        s = self.cache.get(key)
        if s is None:
            s, c = self._blank(r)
            painter(s, c, r)
            s = assets._fast(s)
            self.cache[key] = s
        return s

    def _glass(self, surf, pos, r):
        """Cristal con reflejo y marco metálico con tornillos encima del instrumento."""
        key = ("cover", r)
        cover = self.cache.get(key)
        if cover is None:
            refl = assets.scaled("vidrio_reflejo.png", (2 * r * 0.96, 2 * r * 0.96))
            bez = assets.scaled("bisel_redondo.png", (r * 2.41, r * 2.41))     # hueco del aro = 0,95·r
            if refl is not None and bez is not None:
                cover = pygame.Surface(bez.get_size(), pygame.SRCALPHA)
                c = (cover.get_width() // 2, cover.get_height() // 2)
                cover.blit(refl, refl.get_rect(center=c))
                cover.blit(bez, (0, 0))
                cover = assets._fast(cover)
            else:
                cover = False
            self.cache[key] = cover
        if cover:
            surf.blit(cover, cover.get_rect(center=(int(pos[0]), int(pos[1]))))
            return
        key = ("glass", r)
        g = self.cache.get(key)
        if g is None:
            g = pygame.Surface((2 * r + 4, 2 * r + 4), pygame.SRCALPHA)
            for i in range(10):
                a = int(10 - i)
                pygame.draw.circle(g, (255, 255, 255, a), (int(r * 0.75), int(r * 0.6)), int(r * (0.5 - i * 0.03)))
            pygame.draw.circle(g, (0, 0, 0, 0), (r + 2, r + 2), r - 1, 1)
            self.cache[key] = g
        surf.blit(g, (pos[0] - r - 2, pos[1] - r - 2))

    def _place(self, surf, face, pos, r):
        surf.blit(face, (pos[0] - r - 2, pos[1] - r - 2))

    def _fastify(self):
        for k, v in list(self.cache.items()):
            if isinstance(v, pygame.Surface):
                self.cache[k] = assets._fast(v)

    # ------------------------------------------------------------ velocímetro
    @staticmethod
    def asi_ang(v):
        v = clamp(v, 20, 200)
        return -160 + (v - 20) / 180 * 320

    def asi(self, surf, pos, r, ias, vs):
        def paint(s, c, r):
            A = self.asi_ang
            arc_band(s, c, r * 0.80, r * 0.86, A(vs["vs0"]), A(vs["vfe"]), (240, 240, 240))
            arc_band(s, c, r * 0.86, r * 0.93, A(vs["vs1"]), A(vs["vno"]), (40, 180, 70))
            arc_band(s, c, r * 0.86, r * 0.93, A(vs["vno"]), A(vs["vne"]), (240, 200, 40))
            d = A(vs["vne"])
            pygame.draw.line(s, (230, 40, 30), polar(c, r * 0.93, d), polar(c, r * 0.72, d), max(2, r // 25))
            for v in range(20, 201, 10):
                L = r * (0.14 if v % 20 == 0 else 0.08)
                pygame.draw.line(s, MARK, polar(c, r * 0.93, A(v)), polar(c, r * 0.93 - L, A(v)), 2 if v % 20 == 0 else 1)
                if v % 20 == 0 and v >= 40:
                    self._text(s, str(v), polar(c, r * 0.62, A(v)), int(r * 0.2), MARK, bold=True)
            self._text(s, "NUDOS", (c[0], c[1] + r * 0.32), int(r * 0.13), (200, 200, 200))
            self._text(s, "VELOCIDAD", (c[0], c[1] - r * 0.28), int(r * 0.12), (200, 200, 200))
        self._place(surf, self._face("asi", r, paint), pos, r)
        needle(surf, pos, self.asi_ang(ias), r * 0.86, r * 0.07, (245, 245, 245), tail=r * 0.18)
        pygame.draw.circle(surf, (40, 40, 40), pos, int(r * 0.08))
        self._glass(surf, pos, r)

    # ------------------------------------------------------------ horizonte
    def attitude(self, surf, pos, r, roll, pitch, flag=False):
        size = 2 * r + 4
        g = pygame.Surface((size, size), pygame.SRCALPHA)
        c = (r + 2, r + 2)
        k = r * 0.038                         # px por grado de cabeceo
        pd = clamp(math.degrees(pitch), -40, 40)
        cr, sr = math.cos(roll), math.sin(roll)

        def rot(x, y):
            return (c[0] + x * cr + y * sr, c[1] - x * sr + y * cr)
        off = pd * k
        big = r * 3
        sky = [rot(-big, -big), rot(big, -big), rot(big, off), rot(-big, off)]
        gnd = [rot(-big, off), rot(big, off), rot(big, big), rot(-big, big)]
        pygame.draw.polygon(g, (36, 125, 220), sky)
        pygame.draw.polygon(g, (150, 92, 40), gnd)
        pygame.draw.line(g, (255, 255, 255), rot(-big, off), rot(big, off), 2)
        for p in range(-30, 31, 5):
            if p == 0:
                continue
            y = off - p * k
            w = r * (0.28 if p % 10 == 0 else 0.13)
            col = (255, 255, 255)
            pygame.draw.line(g, col, rot(-w, y), rot(w, y), 2 if p % 10 == 0 else 1)
            if p % 10 == 0:
                for sx in (-1, 1):
                    q = rot(sx * (w + r * 0.12), y)
                    self.f.blit(g, str(abs(p)), q, int(r * 0.12), col, anchor="center")
        # índice de alabeo (rota con la tarjeta)
        tip = rot(0, -r * 0.78)
        pygame.draw.polygon(g, (255, 255, 255), [tip, rot(-r * 0.06, -r * 0.68), rot(r * 0.06, -r * 0.68)])
        g.blit(self._mask(r), (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        # escala de alabeo fija
        for d, L in ((0, 0.12), (10, 0.07), (20, 0.07), (30, 0.12), (45, 0.08), (60, 0.12),
                     (-10, 0.07), (-20, 0.07), (-30, 0.12), (-45, 0.08), (-60, 0.12)):
            pygame.draw.line(g, (255, 255, 255), polar(c, r * 0.92, d), polar(c, r * (0.92 - L), d), 2)
        pygame.draw.polygon(g, (255, 140, 30), [polar(c, r * 0.8, 0), polar(polar(c, r * 0.92, 0), r * 0.06, -90),
                                                 polar(polar(c, r * 0.92, 0), r * 0.06, 90)])
        # avión de referencia
        yc = (255, 160, 20)
        w = r * 0.42
        pygame.draw.line(g, yc, (c[0] - w, c[1]), (c[0] - r * 0.12, c[1]), 4)
        pygame.draw.line(g, yc, (c[0] + r * 0.12, c[1]), (c[0] + w, c[1]), 4)
        pygame.draw.lines(g, yc, False, [(c[0] - r * 0.12, c[1]), (c[0], c[1] + r * 0.08), (c[0] + r * 0.12, c[1])], 4)
        pygame.draw.circle(g, yc, c, 3)
        pygame.draw.circle(surf, BEZEL, pos, r + 1)
        surf.blit(g, (pos[0] - r - 2, pos[1] - r - 2))
        if flag:
            self._text(surf, "OFF", (pos[0] + r * 0.45, pos[1] + r * 0.5), int(r * 0.16), (240, 60, 40), bold=True)
        self._glass(surf, pos, r)

    # ------------------------------------------------------------ altímetro
    def altimeter(self, surf, pos, r, alt, kollsman):
        def paint(s, c, r):
            for i in range(50):
                d = i * 7.2
                L = r * (0.15 if i % 5 == 0 else 0.07)
                pygame.draw.line(s, MARK, polar(c, r * 0.93, d), polar(c, r * 0.93 - L, d), 2 if i % 5 == 0 else 1)
            for i in range(10):
                self._text(s, str(i), polar(c, r * 0.64, i * 36), int(r * 0.24), MARK, bold=True)
            self._text(s, "ALT", (c[0], c[1] - r * 0.3), int(r * 0.13), (200, 200, 200))
            self._text(s, "100 FT", (c[0] - r * 0.02, c[1] + r * 0.28), int(r * 0.1), (200, 200, 200))
            win = pygame.Rect(0, 0, r * 0.5, r * 0.2)
            win.center = (c[0] + r * 0.48, c[1])
            pygame.draw.rect(s, (0, 0, 0), win)
            pygame.draw.rect(s, (90, 90, 90), win, 1)
        self._place(surf, self._face("alt", r, paint), pos, r)
        win = pygame.Rect(0, 0, r * 0.5, r * 0.2)
        win.center = (pos[0] + r * 0.48, pos[1])
        self._text(surf, f"{kollsman:.0f}", win.center, int(r * 0.15), (255, 255, 255), bold=True)
        a = max(alt, -1000)
        needle(surf, pos, (a % 10000) / 10000 * 360, r * 0.5, r * 0.11, (240, 240, 240))
        needle(surf, pos, (a % 100000) / 100000 * 360, r * 0.86, r * 0.025, (240, 240, 240))
        tri = polar(pos, r * 0.86, (a % 100000) / 100000 * 360)
        pygame.draw.circle(surf, (240, 240, 240), tri, max(2, int(r * 0.04)))
        needle(surf, pos, (a % 1000) / 1000 * 360, r * 0.84, r * 0.06, (250, 250, 250), tail=r * 0.15)
        pygame.draw.circle(surf, (40, 40, 40), pos, int(r * 0.07))
        self._glass(surf, pos, r)

    # ------------------------------------------------------------ coordinador
    def turn_coord(self, surf, pos, r, rate, slip, powered=True):
        def paint(s, c, r):
            for d in (-90, 90, -110, 110):
                pygame.draw.line(s, MARK, polar(c, r * 0.9, d), polar(c, r * 0.74, d), 3)
            self._text(s, "L", polar(c, r * 0.62, -112), int(r * 0.16), MARK, bold=True)
            self._text(s, "R", polar(c, r * 0.62, 112), int(r * 0.16), MARK, bold=True)
            self._text(s, "COORDINADOR", (c[0], c[1] - r * 0.52), int(r * 0.11), (200, 200, 200))
            self._text(s, "2 MIN", (c[0], c[1] + r * 0.28), int(r * 0.11), (200, 200, 200))
            tube = pygame.Rect(0, 0, r * 0.9, r * 0.2)
            tube.center = (c[0], c[1] + r * 0.56)
            pygame.draw.rect(s, (220, 220, 200), tube, border_radius=int(r * 0.1))
            pygame.draw.line(s, (20, 20, 20), (c[0] - r * 0.1, tube.top), (c[0] - r * 0.1, tube.bottom), 2)
            pygame.draw.line(s, (20, 20, 20), (c[0] + r * 0.1, tube.top), (c[0] + r * 0.1, tube.bottom), 2)
        self._place(surf, self._face("tc", r, paint), pos, r)
        ang = clamp(rate / 3.0 * 20.0, -35, 35)
        cr, sr = math.cos(math.radians(ang)), math.sin(math.radians(ang))

        def rot(x, y):
            return (pos[0] + x * cr - y * sr, pos[1] + x * sr + y * cr)
        w = r * 0.62
        col = (245, 245, 245)
        pygame.draw.line(surf, col, rot(-w, 0), rot(w, 0), max(3, r // 18))
        pygame.draw.circle(surf, col, (int(pos[0]), int(pos[1])), int(r * 0.1))
        pygame.draw.line(surf, col, rot(0, -r * 0.1), rot(0, -r * 0.22), 3)
        pygame.draw.line(surf, col, rot(-r * 0.16, -r * 0.2), rot(r * 0.16, -r * 0.2), 3)
        bx = pos[0] + clamp(slip, -1.0, 1.0) * r * 0.36
        pygame.draw.circle(surf, (10, 10, 10), (int(bx), int(pos[1] + r * 0.56)), int(r * 0.085))
        if not powered:
            self._text(surf, "OFF", (pos[0] - r * 0.45, pos[1] + r * 0.2), int(r * 0.15), (240, 60, 40), bold=True)
        self._glass(surf, pos, r)

    # ------------------------------------------------------------ direccional
    def _card(self, r, kind="dg"):
        key = ("card", kind, r)
        s = self.cache.get(key)
        if s is None:
            size = 2 * r + 4
            s = pygame.Surface((size, size), pygame.SRCALPHA)
            c = (r + 2, r + 2)
            labels = {0: "N", 30: "3", 60: "6", 90: "E", 120: "12", 150: "15", 180: "S", 210: "21",
                      240: "24", 270: "W", 300: "30", 330: "33"}
            for d in range(0, 360, 5):
                L = r * (0.14 if d % 10 == 0 else 0.07)
                pygame.draw.line(s, MARK, polar(c, r * 0.9, d), polar(c, r * 0.9 - L, d), 2 if d % 10 == 0 else 1)
            for d, t in labels.items():
                img = self.f.render(t, int(r * (0.22 if t in "NESW" else 0.18)), MARK if t not in "NESW" else (255, 255, 255), bold=True)
                img = pygame.transform.rotozoom(img, -d, 1.0)
                q = polar(c, r * 0.6, d)
                s.blit(img, img.get_rect(center=(int(q[0]), int(q[1]))))
            self.cache[key] = s
        return s

    def _rot_card(self, r, ang):
        """Tarjeta de rumbo girada, en caché por medio grado (girar cuesta mucho)."""
        q = round(ang * 2) / 2.0 % 360
        key = ("rot", r, q)
        c = self.cache.get(key)
        if c is None:
            c = pygame.transform.rotozoom(self._card(r), q, 1.0)
            if sum(1 for k in self.cache if k[0] == "rot") > 900:
                for k in [k for k in self.cache if k[0] == "rot"][:300]:
                    del self.cache[k]
            self.cache[key] = c
        return c

    def heading(self, surf, pos, r, hdg, bug=None, label="RUMBO"):
        self._place(surf, self._face("dg", r, lambda s, c, r: None), pos, r)
        card = self._rot_card(r, hdg)
        surf.blit(card, card.get_rect(center=(int(pos[0]), int(pos[1]))))
        if bug is not None:
            d = bug - hdg
            p = polar(pos, r * 0.88, d)
            pygame.draw.polygon(surf, (255, 150, 30), [polar(p, r * 0.08, d - 90), polar(p, r * 0.08, d + 90),
                                                         polar(polar(pos, r * 0.76, d), r * 0.04, d + 90),
                                                         polar(polar(pos, r * 0.76, d), r * 0.04, d - 90)])
        # avión fijo y línea de fe
        col = (255, 160, 30)
        pygame.draw.line(surf, col, (pos[0], pos[1] - r * 0.4), (pos[0], pos[1] + r * 0.3), 4)
        pygame.draw.line(surf, col, (pos[0] - r * 0.3, pos[1] - r * 0.08), (pos[0] + r * 0.3, pos[1] - r * 0.08), 4)
        pygame.draw.line(surf, col, (pos[0] - r * 0.12, pos[1] + r * 0.26), (pos[0] + r * 0.12, pos[1] + r * 0.26), 3)
        pygame.draw.polygon(surf, col, [(pos[0], pos[1] - r * 0.9), (pos[0] - r * 0.06, pos[1] - r * 0.98),
                                        (pos[0] + r * 0.06, pos[1] - r * 0.98)])
        self._glass(surf, pos, r)

    # ------------------------------------------------------------ variómetro
    @staticmethod
    def vsi_ang(v):
        v = clamp(v, -2000, 2000)
        return -90 + v / 2000 * 170

    def vsi(self, surf, pos, r, vs):
        def paint(s, c, r):
            A = self.vsi_ang
            for v in range(-2000, 2001, 100):
                L = r * (0.15 if v % 500 == 0 else 0.07)
                pygame.draw.line(s, MARK, polar(c, r * 0.93, A(v)), polar(c, r * 0.93 - L, A(v)), 2 if v % 500 == 0 else 1)
            for v, t in ((0, "0"), (500, ".5"), (1000, "1"), (1500, "1.5"), (2000, "2"), (-500, ".5"), (-1000, "1"), (-1500, "1.5")):
                self._text(s, t, polar(c, r * 0.62, A(v)), int(r * 0.19), MARK, bold=True)
            self._text(s, "SUBIR", (c[0] + r * 0.05, c[1] - r * 0.32), int(r * 0.11), (200, 200, 200))
            self._text(s, "BAJAR", (c[0] + r * 0.05, c[1] + r * 0.32), int(r * 0.11), (200, 200, 200))
            self._text(s, "x1000 FT/MIN", (c[0] + r * 0.1, c[1]), int(r * 0.09), (200, 200, 200))
        self._place(surf, self._face("vsi", r, paint), pos, r)
        needle(surf, pos, self.vsi_ang(vs), r * 0.86, r * 0.06, (250, 250, 250), tail=r * 0.15)
        pygame.draw.circle(surf, (40, 40, 40), pos, int(r * 0.07))
        self._glass(surf, pos, r)

    # ------------------------------------------------------------ tacómetro
    @staticmethod
    def tach_ang(rpm):
        return -135 + clamp(rpm, 0, 3500) / 3500 * 270

    def tach(self, surf, pos, r, rpm, green=(2100, 2700), red=2700, hours=0.0):
        def paint(s, c, r):
            A = self.tach_ang
            arc_band(s, c, r * 0.86, r * 0.93, A(green[0]), A(green[1]), (40, 180, 70))
            pygame.draw.line(s, (230, 40, 30), polar(c, r * 0.93, A(red)), polar(c, r * 0.74, A(red)), 3)
            for v in range(0, 3501, 100):
                L = r * (0.14 if v % 500 == 0 else 0.07)
                pygame.draw.line(s, MARK, polar(c, r * 0.93, A(v)), polar(c, r * 0.93 - L, A(v)), 2 if v % 500 == 0 else 1)
                if v % 500 == 0:
                    self._text(s, str(v // 100), polar(c, r * 0.62, A(v)), int(r * 0.2), MARK, bold=True)
            self._text(s, "RPM", (c[0], c[1] - r * 0.3), int(r * 0.13), (200, 200, 200))
            self._text(s, "x100", (c[0], c[1] - r * 0.17), int(r * 0.1), (200, 200, 200))
        self._place(surf, self._face(("tach", green, red), r, paint), pos, r)
        hb = pygame.Rect(0, 0, r * 0.62, r * 0.17)
        hb.center = (pos[0], pos[1] + r * 0.3)
        pygame.draw.rect(surf, (0, 0, 0), hb)
        self._text(surf, f"{hours:06.1f}", hb.center, int(r * 0.12), (230, 230, 230), bold=True)
        needle(surf, pos, self.tach_ang(rpm), r * 0.86, r * 0.07, (250, 250, 250), tail=r * 0.15)
        pygame.draw.circle(surf, (40, 40, 40), pos, int(r * 0.08))
        self._glass(surf, pos, r)

    # ------------------------------------------------------------ CDI / ILS
    def cdi(self, surf, pos, r, nav, title="NAV 1"):
        face = self.cache.get(("cdiface", r))
        if face is None:
            face, _ = self._blank(r)
            self.cache[("cdiface", r)] = face
        self._place(surf, face, pos, r)
        card = self._rot_card(r, nav.obs)
        surf.blit(card, card.get_rect(center=(int(pos[0]), int(pos[1]))))
        pygame.draw.circle(surf, FACE, pos, int(r * 0.42))
        pygame.draw.polygon(surf, (255, 255, 255), [(pos[0], pos[1] - r * 0.92), (pos[0] - r * 0.06, pos[1] - r * 0.8),
                                                     (pos[0] + r * 0.06, pos[1] - r * 0.8)])
        dot = r * 0.075
        for i in range(-5, 6):
            if i:
                pygame.draw.circle(surf, MARK, (int(pos[0] + i * dot), int(pos[1])), 2)
        valid = nav.valid
        if valid:
            x = pos[0] + nav.cdi * 5 * dot
            pygame.draw.line(surf, (255, 255, 255), (x, pos[1] - r * 0.4), (x, pos[1] + r * 0.4), 3)
            if nav.is_loc:
                for i in range(-5, 6):
                    if i:
                        pygame.draw.circle(surf, MARK, (int(pos[0]), int(pos[1] - i * dot)), 2)
                if nav.gs_valid:
                    y = pos[1] - nav.gs * 5 * dot
                    pygame.draw.line(surf, (255, 255, 255), (pos[0] - r * 0.4, y), (pos[0] + r * 0.4, y), 3)
                else:
                    self._text(surf, "GS", (pos[0] + r * 0.28, pos[1] - r * 0.25), int(r * 0.13), (240, 60, 40), bold=True)
            tf = nav.to_from
            if tf:
                self._text(surf, "TO" if tf == "TO" else "FR", (pos[0] + r * 0.24, pos[1] + r * 0.22), int(r * 0.13),
                           (255, 255, 255), bold=True)
        else:
            pygame.draw.rect(surf, (210, 40, 30), (pos[0] - r * 0.36, pos[1] + r * 0.12, r * 0.3, r * 0.17))
            self._text(surf, "NAV", (pos[0] - r * 0.21, pos[1] + r * 0.205), int(r * 0.12), (255, 255, 255), bold=True)
        self._text(surf, title, (pos[0], pos[1] - r * 0.27), int(r * 0.11), (180, 180, 180))
        self._text(surf, f"{nav.obs:03.0f}", (pos[0], pos[1] + r * 0.31), int(r * 0.12), (220, 220, 220), bold=True)
        if nav.dme_nm is not None:
            self._text(surf, f"{nav.ident} {nav.dme_nm:4.1f} NM", (pos[0], pos[1] + r * 1.12), int(r * 0.16), COL["green"], bold=True)
        self._glass(surf, pos, r)

    # ------------------------------------------------------------ ADF
    def adf(self, surf, pos, r, adf, card=0.0, title="ADF"):
        """ADF de rosa fija: la aguja amarilla marca hacia el NDB respecto al morro (rosa en 0 = arriba)."""
        face = self.cache.get(("cdiface", r))
        if face is None:
            face, _ = self._blank(r)
            self.cache[("cdiface", r)] = face
        self._place(surf, face, pos, r)
        rose = self._rot_card(r, card)
        surf.blit(rose, rose.get_rect(center=(int(pos[0]), int(pos[1]))))
        pygame.draw.polygon(surf, (255, 255, 255), [(pos[0], pos[1] - r * 0.92), (pos[0] - r * 0.06, pos[1] - r * 0.8),
                                                     (pos[0] + r * 0.06, pos[1] - r * 0.8)])
        self._text(surf, title, (pos[0], pos[1] - r * 0.3), int(r * 0.11), (180, 180, 180))
        col = (255, 205, 40)
        needle(surf, pos, adf.relative, r * 0.78, r * 0.07, col, tail=r * 0.62)
        pygame.draw.circle(surf, (40, 40, 40), pos, int(r * 0.08))
        txt = f"{adf.freq:.0f} kHz {adf.ident}" + (f" {adf.dist_nm:4.1f} NM" if adf.valid else "")
        self._text(surf, txt, (pos[0], pos[1] + r * 1.12), int(r * 0.16), COL["green"] if adf.valid else (200, 120, 60),
                   bold=True)
        self._glass(surf, pos, r)

    # ------------------------------------------------------------ brújula
    def compass(self, surf, rect, hdg):
        rect = pygame.Rect(rect)
        pygame.draw.rect(surf, (20, 20, 22), rect, border_radius=6)
        pygame.draw.rect(surf, (90, 90, 90), rect, 1, border_radius=6)
        clip = surf.get_clip()
        inner = rect.inflate(-6, -6)
        surf.set_clip(inner)
        px_per_deg = inner.w / 60.0
        base = int(hdg) - 40
        for d in range(base - base % 5, int(hdg) + 41, 5):
            x = inner.centerx + (d - hdg) * px_per_deg
            dd = d % 360
            L = 8 if dd % 10 == 0 else 4
            pygame.draw.line(surf, (230, 230, 230), (x, inner.bottom - 2), (x, inner.bottom - 2 - L), 1)
            if dd % 30 == 0:
                lab = {0: "N", 90: "E", 180: "S", 270: "W"}.get(dd, str(dd // 10))
                self.f.blit(surf, lab, (x, inner.top + 1), 15, (240, 240, 240), bold=True, anchor="midtop")
        surf.set_clip(clip)
        pygame.draw.line(surf, (255, 120, 30), (rect.centerx, rect.top + 2), (rect.centerx, rect.bottom - 2), 2)


def bar_gauge(f, surf, rect, label, value, lo, hi, green, unit="", fmt="{:.0f}", red=None, yellow=None):
    rect = pygame.Rect(rect)
    vtxt = fmt.format(value) + (" " + unit if unit else "")
    vimg = f.render(vtxt, 12, (240, 240, 240), bold=True)
    room = rect.w - vimg.get_width() - 4
    lab = label
    while lab and f.get(11).size(lab)[0] > room:
        lab = lab[:-1]
    f.blit(surf, lab, (rect.x, rect.y + 1), 11, (190, 195, 200))
    surf.blit(vimg, vimg.get_rect(topright=(rect.right, rect.y)))
    bar = pygame.Rect(rect.x, rect.y + 16, rect.w, max(6, min(rect.h - 18, 16)))      # barra fina aunque haya sitio
    pygame.draw.rect(surf, (12, 12, 14), bar, border_radius=3)

    def X(v):
        return bar.x + (clamp(v, lo, hi) - lo) / (hi - lo) * bar.w
    g0, g1 = green
    pygame.draw.rect(surf, (40, 170, 70), (X(g0), bar.y + 1, X(g1) - X(g0), bar.h - 2))
    if yellow:
        pygame.draw.rect(surf, (230, 190, 40), (X(yellow[0]), bar.y + 1, X(yellow[1]) - X(yellow[0]), bar.h - 2))
    if red is not None:
        pygame.draw.line(surf, (230, 40, 30), (X(red), bar.y - 1), (X(red), bar.bottom), 2)
    x = X(value)
    pygame.draw.rect(surf, (255, 255, 255), (x - 2, bar.y - 2, 4, bar.h + 4))
