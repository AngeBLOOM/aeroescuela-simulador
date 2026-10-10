"""Globo terráqueo holográfico del menú: los continentes se dibujan con los puntos de los ~48.000 aeropuertos
reales (OurAirports), con meridianos y paralelos, y el globo gira suavemente hasta el aeropuerto elegido."""
import math
import time

import numpy as np
import pygame

from . import theme


class Globe:
    def __init__(self, airport_db, max_points=9000):
        self.pts = None
        self.big = None
        self.lon = -30.0
        self.lat = 10.0
        self.target = None
        self.label = ""
        self._last = time.time()
        try:
            if airport_db.airports is None:
                airport_db.ensure()
            rows = list(airport_db.airports.values())
            lat = np.array([float(r["latitude_deg"]) for r in rows])
            lon = np.array([float(r["longitude_deg"]) for r in rows])
            big = np.array([r.get("type") in ("large_airport", "medium_airport") for r in rows])
            rng = np.random.default_rng(3)
            keep = big | (rng.random(len(rows)) < max_points / max(1, len(rows)))
            self.pts = self._xyz(lat[keep], lon[keep])
            self.big = big[keep]
        except Exception as ex:
            print("Globo sin aeropuertos:", ex)
        # retícula de meridianos y paralelos
        self.grid = []
        for lo in range(-180, 180, 30):
            la = np.linspace(-85, 85, 40)
            self.grid.append(self._xyz(la, np.full_like(la, lo)))
        for la0 in range(-60, 61, 30):
            lo = np.linspace(-180, 180, 73)
            self.grid.append(self._xyz(np.full_like(lo, la0), lo))

    @staticmethod
    def _xyz(lat, lon):
        la = np.radians(lat)
        lo = np.radians(lon)
        return np.stack([np.cos(la) * np.sin(lo), np.sin(la), np.cos(la) * np.cos(lo)], axis=1)

    def set_target(self, lat, lon, label):
        self.target = (float(lat), float(lon))
        self.label = label

    def _rot(self, v):
        """Gira para que (self.lat, self.lon) quede en el centro del disco."""
        lo = math.radians(self.lon)
        la = math.radians(self.lat)
        x = v[:, 0] * math.cos(-lo) + v[:, 2] * math.sin(-lo)
        z = -v[:, 0] * math.sin(-lo) + v[:, 2] * math.cos(-lo)
        y = v[:, 1]
        y2 = y * math.cos(la) - z * math.sin(la)
        z2 = y * math.sin(la) + z * math.cos(la)
        return x, y2, z2

    def draw(self, surf, fonts, center, radius):
        now = time.time()
        dt = min(0.1, now - self._last)
        self._last = now
        cx, cy = center
        # rotación: hacia el aeropuerto elegido, con un ligero vaivén
        if self.target is not None:
            tla, tlo = self.target
            tlo += 8.0 * math.sin(now * 0.25)
            dlo = (tlo - self.lon + 540) % 360 - 180
            self.lon += dlo * min(1.0, dt * 1.6)
            self.lat += (tla * 0.8 - self.lat) * min(1.0, dt * 1.6)
        else:
            self.lon += dt * 6.0
        # halo y disco
        for k in range(4, 0, -1):
            pygame.draw.circle(surf, (*theme.CYAN, 10 * k), (cx, cy), radius + k * 4, 2)
        pygame.draw.circle(surf, (2, 18, 30, 170), (cx, cy), radius)
        pygame.draw.circle(surf, (*theme.CYAN, 160), (cx, cy), radius, 1)
        # retícula (solo la cara visible)
        for line in self.grid:
            x, y, z = self._rot(line)
            vis = z > 0
            px = cx + x * radius
            py = cy - y * radius
            seg = []
            for i in range(len(px)):
                if vis[i]:
                    seg.append((px[i], py[i]))
                elif len(seg) > 1:
                    pygame.draw.lines(surf, (0, 160, 210, 28), False, seg, 1)
                    seg = []
                else:
                    seg = []
            if len(seg) > 1:
                pygame.draw.lines(surf, (0, 160, 210, 28), False, seg, 1)
        # puntos de los aeropuertos (continentes)
        if self.pts is not None:
            x, y, z = self._rot(self.pts)
            vis = z > 0.05
            px = (cx + x[vis] * radius).astype(int)
            py = (cy - y[vis] * radius).astype(int)
            zz = z[vis]
            big = self.big[vis]
            for i in range(len(px)):
                a = int(60 + 150 * zz[i])
                if big[i]:
                    surf.fill((120, 255, 230, a), (px[i], py[i], 2, 2))
                else:
                    surf.fill((0, 190, 240, int(a * 0.7)), (px[i], py[i], 1, 1))
        # brillo especular y terminador
        pygame.draw.arc(surf, (*theme.CYAN, 70), (cx - radius + 6, cy - radius + 6, radius * 2 - 12, radius * 2 - 12),
                        math.radians(100), math.radians(170), 2)
        # marcador del aeropuerto elegido
        if self.target is not None:
            v = self._xyz(np.array([self.target[0]]), np.array([self.target[1]]))
            x, y, z = self._rot(v)
            if z[0] > 0:
                mx, my = int(cx + x[0] * radius), int(cy - y[0] * radius)
                ph = (now * 1.4) % 1.0
                pygame.draw.circle(surf, (*theme.AMBER, int(220 * (1 - ph))), (mx, my), int(6 + 22 * ph), 2)
                pygame.draw.circle(surf, theme.AMBER, (mx, my), 4)
                # línea de rótulo
                lx, ly = mx + 34, my - 30
                pygame.draw.lines(surf, (*theme.AMBER, 220), False, [(mx + 4, my - 4), (lx, ly), (lx + 120, ly)], 1)
                fonts.blit(surf, self.label, (lx + 4, ly - 2), 12, theme.AMBER, tech=True, anchor="bottomleft")
