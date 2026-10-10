"""Lluvia sobre el parabrisas: hilos de agua que salen del centro de la vista en vuelo (como cuando se
atraviesa la lluvia) y gotas que caen y resbalan por el cristal cuando el avión está parado o va despacio."""
import math
import random

import pygame


class RainFX:
    def __init__(self):
        self.rng = random.Random(3)
        self.streaks = []           # [ángulo, radio, largo, alfa]
        self.drops = []             # [x, y, radio, vida, velocidad]

    def draw(self, surf, rect, world, dt, paused=False):
        rain = float(getattr(world.atmo, "rain_here", 0.0))
        if rain < 0.03:
            self.streaks.clear()
            self.drops.clear()
            return
        ac = world.ac
        tas = max(0.0, ac.tas)
        night = 1.0 if (world.weather.hour % 24 < 6.3 or world.weather.hour % 24 > 18.6) else 0.0
        cx, cy = rect.centerx, rect.y + rect.h * 0.42
        rmax = math.hypot(rect.w, rect.h) * 0.6
        rng = self.rng
        dt = 0.0 if paused else dt
        # hilos de lluvia: cuantos más cuanto más llueve y más rápido se va
        fast = min(1.0, tas / 35.0)
        want = int(rain * 320 * (0.35 + 0.65 * fast))
        while len(self.streaks) < want:
            self.streaks.append([rng.uniform(0, 2 * math.pi), rng.uniform(20, rmax), rng.uniform(14, 40), rng.uniform(40, 95)])
        del self.streaks[want:]
        col = (150, 160, 175) if night else (205, 212, 222)
        spd = 120 + tas * 14
        for s in self.streaks:
            a, r, ln, al = s
            r += spd * dt * (0.25 + r / 260.0)
            if r > rmax:
                s[0], r, s[2], s[3] = rng.uniform(0, 2 * math.pi), rng.uniform(10, 60), rng.uniform(14, 40), rng.uniform(40, 95)
                a, ln, al = s[0], s[2], s[3]
            s[1] = r
            # en tierra y despacio la lluvia cae casi vertical
            ca, sa = math.cos(a), math.sin(a)
            x0, y0 = cx + ca * r, cy + sa * r
            k = ln * (0.4 + r / rmax) * (0.3 + 0.7 * fast)
            dx, dy = ca * k * fast, sa * k * fast + (1 - fast) * ln
            if rect.collidepoint(x0, y0):
                pygame.draw.line(surf, (*col, int(al * (0.6 + 0.4 * rain))), (x0, y0), (x0 + dx, y0 + dy), 1)
        # gotas en el cristal: aparecen, engordan y resbalan (el viento las barre en vuelo)
        want_d = int(rain * 90 * (1.0 - 0.8 * fast))
        while len(self.drops) < want_d:
            self.drops.append([rng.uniform(rect.x, rect.right), rng.uniform(rect.y, rect.bottom), rng.uniform(1.5, 4.0),
                               rng.uniform(1.0, 5.0), 0.0])
        del self.drops[want_d:]
        for d in self.drops:
            d[3] -= dt
            if d[2] > 3.2:
                d[4] = min(90.0, d[4] + 60 * dt)
            d[1] += d[4] * dt
            d[0] -= fast * 300 * dt
            if d[3] <= 0 or d[1] > rect.bottom or d[0] < rect.x:
                d[:] = [rng.uniform(rect.x, rect.right), rng.uniform(rect.y, rect.bottom), rng.uniform(1.5, 4.0),
                        rng.uniform(1.0, 5.0), 0.0]
            p = (int(d[0]), int(d[1]))
            rr = max(1, int(d[2]))
            pygame.draw.circle(surf, (*col, 70), p, rr)
            pygame.draw.circle(surf, (235, 240, 248, 110), (p[0] - rr // 3, p[1] - rr // 3), max(1, rr // 3))
