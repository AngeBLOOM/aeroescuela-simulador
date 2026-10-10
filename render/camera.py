"""Cámaras: cabina, persecución, torre, órbita libre y repetición."""
import math

import numpy as np

from sim.mathx import clamp, normalize, quat_to_mat

MODES = ["cabina", "exterior", "torre", "libre"]
MODE_NAMES = {"cabina": "Cabina", "exterior": "Exterior", "torre": "Torre de control", "libre": "Cámara libre"}


class Camera:
    def __init__(self):
        self.mode = "cabina"
        self.head_yaw = 0.0
        self.head_pitch = math.radians(-10.0)
        self.fov = 78.0
        self.orbit_yaw = math.radians(200)
        self.orbit_pitch = math.radians(12)
        self.orbit_dist = 22.0
        self.chase_pos = None
        self.chase_fwd = None
        self.eye = np.zeros(3)
        self.fwd = np.array([1.0, 0, 0])
        self.up = np.array([0, 0, -1.0])
        self.near = 0.1
        self.anim = None          # (pitch, yaw, fov) objetivo de una vista predefinida

    def set_mode(self, m):
        self.mode = m
        self.chase_pos = None
        if m == "cabina":
            self.fov = 78.0
        elif m in ("exterior", "libre"):
            self.fov = 60.0

    def toggle_instrument_view(self):
        """Alterna entre la vista exterior normal y mirar al tablero completo."""
        if self.mode != "cabina":
            return
        if self.head_pitch < math.radians(-24):
            self.anim = (math.radians(-12), 0.0, 78.0)
        else:
            self.anim = (math.radians(-33), math.radians(-4), 64.0)

    def look(self, dyaw, dpitch):
        self.anim = None
        if self.mode == "cabina":
            self.head_yaw = clamp(self.head_yaw + dyaw, -math.radians(160), math.radians(160))
            self.head_pitch = clamp(self.head_pitch + dpitch, -math.radians(60), math.radians(70))
        else:
            self.orbit_yaw += dyaw
            self.orbit_pitch = clamp(self.orbit_pitch - dpitch, math.radians(-15), math.radians(85))

    def snap_head(self, yaw_deg=None, pitch_deg=None):
        if yaw_deg is not None:
            self.head_yaw = math.radians(yaw_deg)
        if pitch_deg is not None:
            self.head_pitch = math.radians(pitch_deg)

    def zoom(self, d):
        if self.mode == "cabina":
            self.fov = clamp(self.fov - d * 5.0, 30.0, 115.0)
        else:
            self.orbit_dist = clamp(self.orbit_dist * (0.9 if d > 0 else 1.1), 8.0, 400.0)

    def update(self, dt, world, pose=None):
        """pose = (pos, q) opcional para la repetición."""
        ac = world.ac
        if pose is None:
            pos, R = ac.pos, ac.R
        else:
            pos, R = pose[0], quat_to_mat(pose[1])
        T = world.terrain
        if self.anim is not None and self.mode == "cabina":
            tp, ty, tf = self.anim
            k = min(1.0, dt * 6.0) if dt > 0 else 1.0
            self.head_pitch += (tp - self.head_pitch) * k
            self.head_yaw += (ty - self.head_yaw) * k
            self.fov += (tf - self.fov) * k
            if abs(tp - self.head_pitch) < 0.002 and abs(tf - self.fov) < 0.05:
                self.anim = None
        if self.mode == "cabina":
            eye = pos + R @ np.array(ac.t.eye)
            cy, sy = math.cos(self.head_yaw), math.sin(self.head_yaw)
            cp, sp = math.cos(self.head_pitch), math.sin(self.head_pitch)
            dirb = np.array([cp * cy, cp * sy, -sp])
            fwd = R @ dirb
            up = R @ np.array([0, 0, -1.0])
            self.near = 0.08
        elif self.mode == "exterior":
            hdg = math.atan2(R[1, 0], R[0, 0])
            pitch = math.asin(clamp(-R[2, 0], -1, 1))
            back = np.array([math.cos(hdg), math.sin(hdg), 0.0])
            target = pos - back * self.orbit_dist * math.cos(pitch * 0.6) + np.array([0, 0, -self.orbit_dist * 0.22])
            target[2] += math.sin(pitch * 0.6) * self.orbit_dist
            if self.chase_pos is None:
                self.chase_pos = target.copy()
            k = min(1.0, dt * 4.0)
            self.chase_pos += (target - self.chase_pos) * k
            eye = self.chase_pos.copy()
            fwd = normalize(pos + back * 4.0 - eye)
            up = np.array([0, 0, -1.0])
            self.near = 0.3
        elif self.mode == "torre":
            ap = min(world.airports, key=lambda a: np.hypot(*(a.ref - pos[:2])))
            if world.is_school:
                base = np.array([ap.ref[0] - 60.0, ap.ref[1] + 215.0]) if ap is world.airports[0] else ap.ref + np.array([80.0, -280.0])
            else:
                rw = max(ap.runways, key=lambda r: r.length)
                base = rw.center + rw.right * (rw.width / 2 + 180.0)
            eye = np.array([base[0], base[1], -(T.height(*base) + 22.0)])
            fwd = normalize(pos - eye)
            dist = np.linalg.norm(pos - eye)
            self.fov = clamp(math.degrees(2 * math.atan(30.0 / max(dist, 1.0))), 0.8, 60.0)
            up = np.array([0, 0, -1.0])
            self.near = 0.5
        else:  # libre (órbita)
            cy, sy = math.cos(self.orbit_yaw), math.sin(self.orbit_yaw)
            cp, sp = math.cos(self.orbit_pitch), math.sin(self.orbit_pitch)
            off = np.array([cp * cy, cp * sy, -sp]) * self.orbit_dist
            eye = pos + off
            fwd = normalize(pos - eye)
            up = np.array([0, 0, -1.0])
            self.near = 0.3
        # no atravesar el terreno
        gh = max(T.height(eye[0], eye[1]), 0.0)
        if self.mode != "cabina" and eye[2] > -(gh + 1.5):
            eye[2] = -(gh + 1.5)
            fwd = normalize(pos - eye) if self.mode != "exterior" else fwd
        self.eye, self.fwd, self.up = eye, fwd, up
