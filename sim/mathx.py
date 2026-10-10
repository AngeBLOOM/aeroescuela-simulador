"""Utilidades matemáticas: vectores, cuaterniones y matrices.

Convenciones del simulador
--------------------------
* Mundo: NED (x = norte, y = este, z = abajo), metros.
* Cuerpo del avión: x = hacia delante, y = ala derecha, z = hacia abajo.
* Cuaternión [w, x, y, z] que rota vectores del cuerpo al mundo.
* Ángulos de Euler aeronáuticos (alabeo, cabeceo, guiñada) en radianes.
"""
import math

import numpy as np

KT = 0.514444          # m/s por nudo
FT = 0.3048            # m por pie
FPM = FT / 60.0        # m/s por pie/minuto
NM = 1852.0            # m por milla náutica
G = 9.80665


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def lerp(a, b, t):
    return a + (b - a) * t


def smoothstep(e0, e1, x):
    if isinstance(x, np.ndarray):
        t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    else:
        t = clamp((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def wrap180(a):
    """Normaliza grados a (-180, 180]."""
    a = (a + 180.0) % 360.0 - 180.0
    return 180.0 if a == -180.0 else a


def wrap360(a):
    return a % 360.0


def approach(cur, target, rate_dt):
    """Mueve cur hacia target como máximo rate_dt."""
    if cur < target:
        return min(cur + rate_dt, target)
    return max(cur - rate_dt, target)


def vec(x=0.0, y=0.0, z=0.0):
    return np.array([x, y, z], dtype=np.float64)


def length(v):
    return math.sqrt(float(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]))


def normalize(v):
    n = length(v)
    return v / n if n > 1e-12 else v * 0.0


def cross(a, b):
    return np.array([a[1] * b[2] - a[2] * b[1],
                     a[2] * b[0] - a[0] * b[2],
                     a[0] * b[1] - a[1] * b[0]])


# ---------------------------------------------------------------- cuaterniones
def quat_mul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return np.array([
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
    ])


def quat_normalize(q):
    return q / math.sqrt(float(q @ q))


def quat_from_euler(roll, pitch, yaw):
    cr, sr = math.cos(roll / 2), math.sin(roll / 2)
    cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
    cy, sy = math.cos(yaw / 2), math.sin(yaw / 2)
    return np.array([
        cr * cp * cy + sr * sp * sy,
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
    ])


def quat_to_euler(q):
    w, x, y, z = q
    roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    pitch = math.asin(clamp(2 * (w * y - z * x), -1.0, 1.0))
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    return roll, pitch, yaw


def quat_to_mat(q):
    """Matriz 3x3 cuerpo -> mundo."""
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ])


def quat_integrate(q, omega_body, dt):
    p, qq, r = omega_body
    dq = quat_mul(q, np.array([0.0, p, qq, r])) * (0.5 * dt)
    return quat_normalize(q + dq)


def quat_slerp(a, b, t):
    d = float(a @ b)
    if d < 0:
        b = -b
        d = -d
    if d > 0.9995:
        return quat_normalize(a + (b - a) * t)
    th = math.acos(d)
    s = math.sin(th)
    return (a * math.sin((1 - t) * th) + b * math.sin(t * th)) / s


# ------------------------------------------------------------ matrices OpenGL
def perspective(fovy_deg, aspect, near, far):
    f = 1.0 / math.tan(math.radians(fovy_deg) / 2)
    m = np.zeros((4, 4), dtype=np.float64)
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = 2 * far * near / (near - far)
    m[3, 2] = -1.0
    return m


def look_dir(eye, fwd, up):
    """Matriz de vista a partir de posición, dirección y 'arriba' (en NED)."""
    f = normalize(np.asarray(fwd, dtype=np.float64))
    r = normalize(cross(f, up))
    u = cross(r, f)
    m = np.identity(4)
    m[0, :3] = r
    m[1, :3] = u
    m[2, :3] = -f
    m[0, 3] = -float(r @ eye)
    m[1, 3] = -float(u @ eye)
    m[2, 3] = float(f @ eye)
    return m


def look_at(eye, target, up):
    return look_dir(eye, np.asarray(target) - np.asarray(eye), up)


def model_matrix(R, p):
    m = np.identity(4)
    m[:3, :3] = R
    m[:3, 3] = p
    return m


def translate(p):
    m = np.identity(4)
    m[:3, 3] = p
    return m


def axis_rotation(axis, angle):
    a = normalize(np.asarray(axis, dtype=np.float64))
    x, y, z = a
    c, s = math.cos(angle), math.sin(angle)
    C = 1 - c
    m = np.identity(4)
    m[:3, :3] = [[c + x * x * C, x * y * C - z * s, x * z * C + y * s],
                 [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
                 [z * x * C - y * s, z * y * C + x * s, c + z * z * C]]
    return m


def gl_bytes(m):
    """Matriz numpy (fila mayor) -> bytes columna mayor float32 para GLSL."""
    return np.ascontiguousarray(m.T, dtype=np.float32).tobytes()
