"""Registrador de datos de vuelo (caja negra) para repetición y análisis posterior."""
import numpy as np

from .mathx import FT


class Recorder:
    FIELDS = ("t", "x", "y", "z", "qw", "qx", "qy", "qz", "ias", "alt", "vs", "hdg", "roll", "pitch", "rpm",
              "flaps", "agl", "gs", "elev", "ail", "rud", "thr")

    def __init__(self, rate=10.0, max_s=1800):
        self.rate = rate
        self.max_n = int(max_s * rate)
        self.clear()

    def clear(self):
        self.rows = []
        self.acc = 0.0
        self.events = []

    def sample(self, dt, world):
        self.acc += dt
        if self.acc < 1.0 / self.rate:
            return
        self.acc = 0.0
        ac = world.ac
        self.rows.append((world.sim_time, ac.pos[0], ac.pos[1], ac.pos[2], *ac.q, world.ind.ias, world.ind.alt_ft,
                          world.ind.vs_fpm, ac.heading, np.degrees(ac.roll), np.degrees(ac.pitch),
                          ac.sys.engine.rpm, ac.sys.flaps, ac.agl / FT, ac.gs, ac.ctl_elev, ac.ctl_ail, ac.ctl_rud,
                          ac.sys.engine.throttle))
        if len(self.rows) > self.max_n:
            self.rows = self.rows[::2]
            self.rate /= 2

    def mark(self, world, text):
        self.events.append((world.sim_time, text))

    def array(self):
        if not self.rows:
            return None
        return np.array(self.rows, dtype=np.float64)

    def col(self, name):
        a = self.array()
        if a is None:
            return np.zeros(0)
        return a[:, self.FIELDS.index(name)]

    def pose_at(self, t):
        """Interpola posición y cuaternión para la repetición."""
        a = self.array()
        if a is None:
            return None
        ts = a[:, 0]
        i = int(np.searchsorted(ts, t))
        i = max(1, min(i, len(ts) - 1))
        t0, t1 = ts[i - 1], ts[i]
        f = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
        f = min(max(f, 0.0), 1.0)
        p = a[i - 1, 1:4] * (1 - f) + a[i, 1:4] * f
        q0 = a[i - 1, 4:8]
        q1 = a[i, 4:8]
        if q0 @ q1 < 0:
            q1 = -q1
        q = q0 * (1 - f) + q1 * f
        q /= np.linalg.norm(q)
        return p, q, a[i]

    def save_csv(self, path):
        a = self.array()
        if a is None:
            return False
        np.savetxt(path, a, delimiter=";", header=";".join(self.FIELDS), comments="", fmt="%.4f")
        return True
