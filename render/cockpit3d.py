"""Cabina 3D por dentro: tablero con los instrumentos reales, visera, montantes,
techo, puertas, asientos, parabrisas con reflejos y volantes animados.

Toda la geometría está en ejes del avión (x adelante, y derecha, z abajo).
"""
import math

import moderngl
import numpy as np

from sim.mathx import axis_rotation, gl_bytes, translate

from . import geometry as geo

# tablero: plano x = PANEL_X, de y -PW/2..PW/2, z PANEL_TOP..PANEL_BOT
PANEL_X = 1.18
PANEL_W = 1.36
PANEL_TOP = -0.43
PANEL_BOT = 0.023
GLARE_D = 0.17                 # profundidad de la visera (hasta la base del parabrisas)
PANEL_TEX = (1500, 500)        # resolución del tablero dibujado (sin la franja superior de 40 px)
TEX_H = PANEL_TEX[1] + 40      # la superficie incluye 40 px superiores que no se muestran
V_TOP = 40.0 / TEX_H

CABIN_VS = """
#version 330
uniform mat4 u_proj;
uniform mat4 u_view;
uniform mat4 u_model;
in vec3 in_pos;
in vec3 in_norm;
in vec2 in_uv;
out vec3 v_pos;
out vec3 v_norm;
out vec2 v_uv;
out float v_logz;
void main() {
    vec4 wp = u_model * vec4(in_pos, 1.0);
    v_pos = wp.xyz;
    v_norm = mat3(u_model) * in_norm;
    v_uv = in_uv;
    gl_Position = u_proj * u_view * wp;
    v_logz = 1.0 + gl_Position.w;
}
"""

CABIN_FS = """
#version 330
uniform sampler2D u_tex;
uniform vec3 u_campos;
uniform vec3 u_sun;
uniform vec3 u_sun_col;
uniform vec3 u_amb;
uniform float u_logc;
uniform vec3 u_tint;
uniform float u_emissive;
uniform int u_glass;
in vec3 v_pos;
in vec3 v_norm;
in vec2 v_uv;
in float v_logz;
out vec4 f_color;
void main() {
    vec3 n = normalize(v_norm);
    vec3 v = normalize(u_campos - v_pos);
    if (dot(n, v) < 0.0) n = -n;
    if (u_glass == 1) {
        // reflejo del sol y del cielo en el parabrisas
        vec3 r = reflect(-v, n);
        float g = pow(max(dot(r, u_sun), 0.0), 6.0);
        float fres = pow(1.0 - max(dot(n, v), 0.0), 3.0);
        float a = 0.035 + 0.28 * g + 0.10 * fres;
        f_color = vec4(u_sun_col * (0.6 + 1.2 * g) + vec3(0.05), a);
        gl_FragDepth = log2(v_logz) * u_logc * 0.5;
        return;
    }
    vec4 t = texture(u_tex, v_uv);
    if (t.a < 0.5) discard;                 // ventanas recortadas de las fotos
    float diff = max(dot(n, u_sun), 0.0);
    // dentro de la cabina la luz es sobre todo indirecta
    vec3 light = u_amb * 1.05 + u_sun_col * (0.22 + 0.38 * diff);
    vec3 col = t.rgb * u_tint * mix(light, vec3(1.0), u_emissive);
    f_color = vec4(col, t.a);
    gl_FragDepth = log2(v_logz) * u_logc * 0.5;
}
"""


GLARE_ARCH = 0.03               # cuánto sube la visera en el centro


def glareshield_loft(hw, nu=40, nv=14):
    """Malla suave de la visera con normales por vértice.

    Perfil (x, z) en cada sección: sale de debajo del borde superior del tablero, da la vuelta
    a un borde redondeado hacia el piloto y sigue por arriba hasta la base del parabrisas.
    A lo largo de y se arquea en el centro y se estrecha en los extremos."""
    def profile(t, k):
        # t: 0 (bajo el borde) .. 1 (base del parabrisas); k: 0 extremo .. 1 centro
        lip = 0.045 + 0.035 * k                 # cuánto sobresale hacia el piloto
        r = 0.028                               # radio del borde
        top = PANEL_TOP - 0.035 - GLARE_ARCH * k
        if t < 0.45:                            # vuelta del borde (medio círculo)
            a = math.pi * (t / 0.45)
            x = PANEL_X - lip + r - r * math.sin(a) - 0.0
            z = (PANEL_TOP + 0.012) - (1 - math.cos(a)) * 0.5 * ((PANEL_TOP + 0.012) - top)
            return x, z
        u = (t - 0.45) / 0.55                   # superficie superior hasta el parabrisas
        x0 = PANEL_X - lip + r
        x1 = PANEL_X + GLARE_D
        z1 = PANEL_TOP + 0.005
        e = u * u * (3 - 2 * u)
        return x0 + (x1 - x0) * u, top + (z1 - top) * e

    P = np.zeros((nu + 1, nv + 1, 3))
    for i in range(nu + 1):
        y = -hw - 0.01 + (2 * hw + 0.02) * i / nu
        k = math.cos(0.5 * math.pi * min(1.0, abs(y) / (hw + 0.01))) ** 0.6
        for j in range(nv + 1):
            x, z = profile(j / nv, k)
            P[i, j] = (x, y, z)
    # normales suaves
    du = np.gradient(P, axis=0)
    dv = np.gradient(P, axis=1)
    N = np.cross(du, dv)
    N /= np.linalg.norm(N, axis=2, keepdims=True) + 1e-9
    out = []
    for i in range(nu):
        for j in range(nv):
            quad = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
            tri = (quad[0], quad[1], quad[2], quad[0], quad[2], quad[3])
            for (ii, jj) in tri:
                p = P[ii, jj]
                out.append((*p, *N[ii, jj], p[1] / 0.5, (jj / nv) * 0.5))
    # tapas laterales (abanico desde el punto medio del perfil)
    for i in (0, nu):
        c = P[i].mean(axis=0)
        n = (0.0, -1.0 if i == 0 else 1.0, 0.0)
        for j in range(nv):
            for p in (c, P[i, j], P[i, j + 1]):
                out.append((*p, *n, p[0] / 0.5, p[2] / 0.5))
    return out


def compass_center_z(x=PANEL_X + 0.0, h=0.052):
    """Altura del centro de la brújula apoyada sobre la visera (en el centro, k=1)."""
    lip, r = 0.08, 0.028
    top = PANEL_TOP - 0.035 - GLARE_ARCH
    x0, x1, z1 = PANEL_X - lip + r, PANEL_X + GLARE_D, PANEL_TOP + 0.005
    u = min(1.0, max(0.0, (x - x0) / (x1 - x0)))
    e = u * u * (3 - 2 * u)
    return top + (z1 - top) * e - h / 2 + 0.006


class TexMeshBuilder:
    """Geometría con normales y coordenadas de textura (pos3, norm3, uv2)."""

    def __init__(self):
        self.v = []

    def quad(self, a, b, c, d, uv=((0, 0), (1, 0), (1, 1), (0, 1)), tile=None):
        a, b, c, d = (np.asarray(p, float) for p in (a, b, c, d))
        n = np.cross(b - a, d - a)
        n = n / (np.linalg.norm(n) + 1e-9)
        if tile:
            # coordenadas en metros para texturas repetibles
            ex = b - a
            ey = d - a
            lx, ly = np.linalg.norm(ex), np.linalg.norm(ey)
            uv = ((0, 0), (lx / tile, 0), (lx / tile, ly / tile), (0, ly / tile))
        for p, t in ((a, uv[0]), (b, uv[1]), (c, uv[2]), (a, uv[0]), (c, uv[2]), (d, uv[3])):
            self.v.append((*p, *n, *t))

    def box(self, center, size, tile=0.4):
        cx, cy, cz = center
        sx, sy, sz = (s / 2 for s in size)
        P = [(cx - sx, cy - sy, cz - sz), (cx + sx, cy - sy, cz - sz), (cx + sx, cy + sy, cz - sz), (cx - sx, cy + sy, cz - sz),
             (cx - sx, cy - sy, cz + sz), (cx + sx, cy - sy, cz + sz), (cx + sx, cy + sy, cz + sz), (cx - sx, cy + sy, cz + sz)]
        for f in ((0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            self.quad(P[f[0]], P[f[1]], P[f[2]], P[f[3]], tile=tile)

    def rounded_box(self, center, size, radius, n=6, pitch_deg=0.0, pivot=None, tile=0.4):
        """Caja con aristas y esquinas redondeadas (normales suaves), opcionalmente inclinada
        alrededor del eje y (pitch_deg) respecto a 'pivot'."""
        c = np.asarray(center, float)
        half = np.asarray(size, float) / 2
        r = min(radius, *(half * 0.98))
        inner = half - r
        ca, sa = math.cos(math.radians(pitch_deg)), math.sin(math.radians(pitch_deg))
        Ry = np.array([[ca, 0, sa], [0, 1, 0], [-sa, 0, ca]])
        piv = np.asarray(pivot if pivot is not None else center, float)
        g = np.linspace(-1, 1, n + 1)
        faces = []
        for axis in range(3):
            for sign in (-1, 1):
                u_ax, v_ax = [k for k in range(3) if k != axis]
                F = np.zeros((n + 1, n + 1, 3))
                F[..., axis] = sign
                F[..., u_ax] = g[:, None]
                F[..., v_ax] = g[None, :]
                if sign < 0:
                    F = F[::-1]
                faces.append((F, u_ax, v_ax))
        for F, u_ax, v_ax in faces:
            P = F * half
            q = np.clip(P, -inner, inner)
            d = P - q
            nrm = d / (np.linalg.norm(d, axis=2, keepdims=True) + 1e-9)
            pts = q + nrm * r
            pts = (pts + c - piv) @ Ry.T + piv
            nrm = nrm @ Ry.T
            for i in range(n):
                for j in range(n):
                    for (ii, jj) in ((i, j), (i + 1, j), (i + 1, j + 1), (i, j), (i + 1, j + 1), (i, j + 1)):
                        p = pts[ii, jj]
                        uv = (p[u_ax] / tile, p[v_ax] / tile)
                        self.v.append((*p, *nrm[ii, jj], *uv))

    def beam(self, p0, p1, w, h, tile=0.3):
        p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
        ax = p1 - p0
        ax /= np.linalg.norm(ax)
        up = np.array([0, 0, -1.0]) if abs(ax[2]) < 0.9 else np.array([1.0, 0, 0])
        side = np.cross(ax, up)
        side /= np.linalg.norm(side)
        upv = np.cross(side, ax)
        s, u = side * w / 2, upv * h / 2
        V = [p0 - s - u, p0 + s - u, p0 + s + u, p0 - s + u, p1 - s - u, p1 + s - u, p1 + s + u, p1 - s + u]
        for f in ((0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            self.quad(V[f[0]], V[f[1]], V[f[2]], V[f[3]], tile=tile)

    def array(self):
        return np.array(self.v, np.float32) if self.v else np.zeros((3, 8), np.float32)


class Cockpit3D:
    def __init__(self, ctx, load_tex):
        self.ctx = ctx
        self.prog = ctx.program(vertex_shader=CABIN_VS, fragment_shader=CABIN_FS)
        self.tex = {}
        for key, name in (("panel_mat", "panel_material.png"), ("glare", "glareshield.png"),
                          ("interior", "interior_lateral.png"), ("seat", "tela_asiento.png"),
                          ("door", "puerta_cabina.png"), ("roof", "techo_cabina.png"),
                          ("floor", "suelo_cabina.png")):
            t, _ = load_tex(name)
            if t is None:
                t = ctx.texture((1, 1), 4, bytes([60, 62, 66, 255]))
            self.tex[key] = t
        self.photo_walls = all(load_tex(n)[0] is not None for n in ("puerta_cabina.png",))
        self.panel_tex = ctx.texture((PANEL_TEX[0], TEX_H), 4)
        self.panel_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.panel_swz = None
        self.compass_tex = ctx.texture((200, 80), 4)
        self.parts = {}
        self.offset = np.zeros(3)
        self.canopy = False
        self._build()

    def configure(self, t):
        """Adapta la cabina al avión: posición del piloto y cúpula de burbuja (Diamond)."""
        self.offset = np.array([t.eye[0] - 0.55, 0.0, t.eye[2] + 0.62])
        self.canopy = getattr(t, "canopy", False)

    # ------------------------------------------------------------ geometría
    def _mesh(self, key, mb):
        data = mb.array()
        vbo = self.ctx.buffer(data.tobytes())
        vao = self.ctx.vertex_array(self.prog, [(vbo, "3f 3f 2f", "in_pos", "in_norm", "in_uv")])
        self.parts[key] = vao

    def _build(self):
        hw = PANEL_W / 2
        # tablero con los instrumentos (u: izquierda->derecha, v: arriba->abajo en la imagen)
        mb = TexMeshBuilder()
        mb.quad((PANEL_X, -hw, PANEL_TOP), (PANEL_X, hw, PANEL_TOP), (PANEL_X, hw, PANEL_BOT), (PANEL_X, -hw, PANEL_BOT),
                uv=((0, V_TOP), (1, V_TOP), (1, 1), (0, 1)))
        self._mesh("panel", mb)
        # bajo-tablero (material del panel, oscuro)
        mb = TexMeshBuilder()
        mb.quad((PANEL_X + 0.005, -hw, PANEL_BOT - 0.005), (PANEL_X + 0.005, hw, PANEL_BOT - 0.005), (PANEL_X - 0.15, hw, 0.43),
                (PANEL_X - 0.15, -hw, 0.43), tile=0.45)
        for sg in (-1, 1):
            mb.quad((PANEL_X - 0.2, sg * hw, PANEL_TOP), (PANEL_X + GLARE_D, sg * hw, PANEL_TOP), (PANEL_X + GLARE_D, sg * hw, 0.43),
                    (PANEL_X - 0.2, sg * hw, 0.43), tile=0.45)
        self._mesh("kick", mb)
        mb = TexMeshBuilder()
        # montantes del parabrisas y marco superior (plástico interior)
        for sg in (-1, 1):
            mb.beam((PANEL_X + GLARE_D, sg * (hw - 0.02), PANEL_TOP - 0.02), (0.98, sg * 0.64, -1.04), 0.05, 0.04)
        mb.beam((0.98, -0.64, -1.04), (0.98, 0.64, -1.04), 0.08, 0.04)
        self._mesh("frame", mb)
        # postes de las puertas
        mb2 = TexMeshBuilder()
        for sg in (-1, 1):
            # poste de la puerta y marco inferior de la ventana, con cantos redondeados (sin foto de puerta)
            mb2.rounded_box((-0.62, sg * 0.638, -0.335), (0.07, 0.06, 1.37), 0.026, n=5)
            mb2.rounded_box(((-0.62 + PANEL_X) / 2, sg * 0.668, -0.33), (PANEL_X + 0.62, 0.05, 0.045), 0.02, n=5)
        self._mesh("door_frame", mb2)
        # variante con cúpula de burbuja (Diamond): marco delantero fino y arco de la cúpula
        mb = TexMeshBuilder()
        for sg in (-1, 1):
            mb.beam((PANEL_X + GLARE_D, sg * (hw - 0.02), PANEL_TOP - 0.02), (0.70, sg * 0.52, -1.02), 0.035, 0.03)
        arc = [(math.radians(a), ) for a in range(-80, 81, 10)]
        prev = None
        for (a,) in arc:
            p = (-0.55, 0.62 * math.sin(a), -0.30 - 0.78 * math.cos(a))
            if prev is not None:
                mb.beam(prev, p, 0.05, 0.04)
            prev = p
        self._mesh("frame_canopy", mb)
        mb = TexMeshBuilder()
        # visera acolchada: superficie curva (borde redondeado tipo "morro", arqueada en el centro
        # y que baja hacia el parabrisas), sin cantos rectos
        mb.v += glareshield_loft(hw)
        # brújula magnética sobre la visera (pequeña, como la real)
        cz = compass_center_z()
        mb.box((PANEL_X + 0.0, 0.0, cz), (0.06, 0.085, 0.052), tile=0.2)
        self._mesh("glare", mb)
        mb = TexMeshBuilder()
        fx = PANEL_X + 0.0 - 0.031
        cz = compass_center_z()
        mb.quad((fx, -0.04, cz - 0.023), (fx, 0.04, cz - 0.023), (fx, 0.04, cz + 0.021),
                (fx, -0.04, cz + 0.021), uv=((0, 1), (1, 1), (1, 0), (0, 0)))
        self._mesh("compass", mb)
        # techo y puertas (plástico interior)
        mb = TexMeshBuilder()
        mb.quad((-0.9, -0.64, -1.05), (0.99, -0.64, -1.05), (0.99, 0.64, -1.05), (-0.9, 0.64, -1.05), tile=0.6)
        # suelo
        mb.quad((-0.9, -0.68, 0.40), (PANEL_X, -0.68, 0.40), (PANEL_X, 0.68, 0.40), (-0.9, 0.68, 0.40), tile=0.5)
        for sg in (-1, 1):
            y = sg * 0.68
            mb.quad((-0.9, y, -0.33), (PANEL_X, y, -0.33), (PANEL_X, y, 0.40), (-0.9, y, 0.40), tile=0.6)
            # reposabrazos acolchado
            mb.rounded_box((0.05, sg * 0.615, -0.18), (0.55, 0.08, 0.06), 0.028, tile=0.3)
        self._mesh("interior", mb)
        # --- versión con fotos reales: puertas, techo y alfombra
        # puerta: foto completa (ventana recortada) sobre cada pared; en la derecha, en espejo
        xa, xf, zt, zb = -0.95, 1.25, -1.05, 0.40
        mb = TexMeshBuilder()
        # (las texturas se suben invertidas para OpenGL: v=1 es la parte de arriba de la foto)
        y = -0.685
        mb.quad((xa, y, zt), (xf, y, zt), (xf, y, zb), (xa, y, zb), uv=((0, 1), (1, 1), (1, 0), (0, 0)))
        y = 0.685
        mb.quad((xf, y, zt), (xa, y, zt), (xa, y, zb), (xf, y, zb), uv=((0, 1), (1, 1), (1, 0), (0, 0)))
        self._mesh("door", mb)
        mb = TexMeshBuilder()
        mb.quad((-0.9, -0.66, -1.05), (0.99, -0.66, -1.05), (0.99, 0.66, -1.05), (-0.9, 0.66, -1.05),
                uv=((0, 1), (0, 0), (1, 0), (1, 1)))
        self._mesh("roof", mb)
        mb = TexMeshBuilder()
        mb.quad((-0.9, -0.68, 0.40), (PANEL_X, -0.68, 0.40), (PANEL_X, 0.68, 0.40), (-0.9, 0.68, 0.40), tile=0.45)
        mb.quad((-2.0, -0.68, 0.40), (-0.9, -0.68, 0.40), (-0.9, 0.68, 0.40), (-2.0, 0.68, 0.40), tile=0.45)
        self._mesh("floor", mb)
        # parte trasera de la cabina: paredes con ventanillas, techo, mamparo del fondo
        mb = TexMeshBuilder()
        XB, XA = -2.0, -0.95
        mb.quad((XB, -0.66, -1.05), (XA + 0.06, -0.66, -1.05), (XA + 0.06, 0.66, -1.05), (XB, 0.66, -1.05), tile=0.6)
        mb.quad((XB, -0.68, -1.05), (XB, 0.68, -1.05), (XB, 0.68, 0.40), (XB, -0.68, 0.40), tile=0.6)
        for sg in (-1, 1):
            y = sg * 0.685
            wx0, wx1, wz0, wz1 = -1.80, -1.05, -0.95, -0.42          # ventanilla trasera
            for (x0, x1, z0, z1) in ((XB, XA, wz1, 0.40), (XB, XA, -1.05, wz0), (XB, wx0, wz0, wz1), (wx1, XA, wz0, wz1)):
                mb.quad((x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1), tile=0.6)
            # marco redondeado de la ventanilla
            mb.rounded_box(((wx0 + wx1) / 2, sg * 0.672, wz1), (wx1 - wx0 + 0.04, 0.04, 0.04), 0.018, n=4)
            mb.rounded_box(((wx0 + wx1) / 2, sg * 0.672, wz0), (wx1 - wx0 + 0.04, 0.04, 0.04), 0.018, n=4)
        self._mesh("rear", mb)
        # banco trasero
        mb = TexMeshBuilder()
        mb.rounded_box((-1.20, 0.0, 0.13), (0.50, 1.18, 0.14), 0.05, pitch_deg=-4, tile=0.35)
        mb.rounded_box((-1.50, 0.0, -0.22), (0.13, 1.18, 0.62), 0.055, pitch_deg=14, pivot=(-1.46, 0.0, 0.08), tile=0.35)
        self._mesh("rear_seat", mb)
        mb = TexMeshBuilder()
        mb.quad((-0.9, -0.68, 0.40), (PANEL_X + 0.1, -0.68, 0.40), (PANEL_X + 0.1, 0.68, 0.40), (-0.9, 0.68, 0.40), tile=0.5)
        for sg in (-1, 1):
            y = sg * 0.66
            mb.quad((-0.9, y, -0.22), (PANEL_X, y, -0.22), (PANEL_X, y, 0.40), (-0.9, y, 0.40), tile=0.6)
            mb.rounded_box((0.05, sg * 0.615, -0.12), (0.55, 0.08, 0.06), 0.028, tile=0.3)
        self._mesh("interior_canopy", mb)
        # asiento del copiloto y respaldo trasero
        mb = TexMeshBuilder()
        # asiento del copiloto: cojín mullido con el borde delantero algo levantado
        mb.rounded_box((0.06, 0.30, 0.11), (0.50, 0.46, 0.13), 0.05, pitch_deg=-4, tile=0.35)
        # respaldos inclinados hacia atrás (12°) con reposacabezas
        for sy in (0.30, -0.30):
            mb.rounded_box((-0.25, sy, -0.26), (0.13, 0.46, 0.62), 0.055, pitch_deg=12,
                           pivot=(-0.22, sy, 0.05), tile=0.35)
            mb.rounded_box((-0.33, sy, -0.66), (0.10, 0.26, 0.17), 0.045, pitch_deg=12,
                           pivot=(-0.22, sy, 0.05), tile=0.35)
        self._mesh("seat", mb)
        # volante en forma de cuernos de carnero (pivota en su columna)
        mb = TexMeshBuilder()
        mb.beam((0.02, 0.0, 0.0), (0.26, 0.0, 0.0), 0.022, 0.022, tile=0.2)            # columna
        prev = None
        for a in range(-90, 91, 15):                                                     # arco inferior
            ar = math.radians(a)
            p = (0.0, 0.13 * math.sin(ar), 0.035 * math.cos(ar))
            if prev is not None:
                mb.beam(prev, p, 0.022, 0.022, tile=0.2)
            prev = p
        for sg in (-1, 1):
            mb.beam((0.0, sg * 0.13, 0.0), (-0.012, sg * 0.145, -0.085), 0.03, 0.032, tile=0.2)   # empuñaduras
        mb.box((-0.005, 0.0, 0.0), (0.03, 0.06, 0.045), tile=0.2)                        # buje
        self._mesh("yoke", mb)
        # parabrisas (cristal)
        mb = TexMeshBuilder()
        mb.quad((PANEL_X + GLARE_D, -hw, PANEL_TOP + 0.0), (PANEL_X + GLARE_D, hw, PANEL_TOP + 0.0), (0.98, 0.64, -1.04),
                (0.98, -0.64, -1.04))
        self._mesh("glass", mb)

    # ------------------------------------------------------------ tablero
    def upload_panel(self, surf):
        """Sube la imagen del tablero (sin la franja superior de 40 px)."""
        import pygame
        if self.panel_swz is None:
            masks = surf.get_masks()
            self.panel_swz = "BGRA" if masks[:3] == (0xFF0000, 0xFF00, 0xFF) else "RGBA"
            self.panel_tex.swizzle = self.panel_swz
        if surf.get_pitch() == surf.get_width() * 4:
            self.panel_tex.write(surf.get_view("1"))
        else:
            self.panel_tex.write(pygame.image.tobytes(surf, self.panel_swz))

    def upload_compass(self, surf):
        import pygame
        self.compass_tex.write(pygame.image.tobytes(surf, "RGBA", True))

    def panel_hit(self, origin_b, dir_b):
        """Intersección de un rayo (ejes cuerpo) con el tablero -> píxel del tablero o None."""
        if abs(dir_b[0]) < 1e-6:
            return None
        origin_b = origin_b - self.offset
        t = (PANEL_X - origin_b[0]) / dir_b[0]
        if t <= 0:
            return None
        p = origin_b + dir_b * t
        u = (p[1] + PANEL_W / 2) / PANEL_W
        v = (p[2] - PANEL_TOP) / (PANEL_BOT - PANEL_TOP)
        if 0 <= u <= 1 and 0 <= v <= 1:
            return (u * PANEL_TEX[0], 40 + v * PANEL_TEX[1])
        return None

    # ------------------------------------------------------------ dibujo
    def draw(self, view, proj, cam_pos, env, body_M, logc, yoke=(0.0, 0.0), night=0.0, show_yoke=True):
        ctx = self.ctx
        pr = self.prog
        pr["u_proj"].write(gl_bytes(proj))
        pr["u_view"].write(gl_bytes(view))
        pr["u_campos"].value = tuple(float(x) for x in cam_pos)
        pr["u_sun"].value = tuple(float(x) for x in env["sun"])
        pr["u_sun_col"].value = env["sun_col"]
        pr["u_amb"].value = env["amb"]
        pr["u_logc"].value = logc
        pr["u_glass"].value = 0
        pr["u_tex"] = 0
        body_M = body_M @ translate(self.offset)
        pr["u_model"].write(gl_bytes(body_M))

        def part(key, tex, tint=(1, 1, 1), emissive=0.0):
            self.tex[tex].use(0) if tex in self.tex else tex.use(0)
            pr["u_tint"].value = tint
            pr["u_emissive"].value = emissive
            self.parts[key].render()
        # instrumentos retroiluminados de noche, legibles de día
        self.panel_tex.use(0)
        pr["u_tint"].value = (1.0, 1.0, 1.0)
        pr["u_emissive"].value = 0.55 + 0.4 * night
        self.parts["panel"].render()
        part("kick", "panel_mat", (0.9, 0.9, 0.92))
        part("frame_canopy" if self.canopy else "frame", "interior", (0.78, 0.77, 0.75))
        if not self.canopy and not self.photo_walls:
            part("door_frame", "interior", (0.78, 0.77, 0.75))
        part("glare", "glare", (1.0, 1.0, 1.0))
        self.compass_tex.use(0)
        pr["u_tint"].value = (1.0, 1.0, 1.0)
        pr["u_emissive"].value = 0.5 + 0.4 * night
        self.parts["compass"].render()
        if self.canopy or not self.photo_walls:
            part("interior_canopy" if self.canopy else "interior", "interior", (0.82, 0.82, 0.84))
        else:
            # fotos reales: se iluminan poco porque ya traen su propia luz
            part("door", "door", (1.0, 1.0, 1.0), emissive=0.45)
            part("roof", "roof", (0.95, 0.95, 0.95), emissive=0.35)
            part("floor", "floor", (1.0, 1.0, 1.0), emissive=0.2)
        if not self.canopy:
            part("rear", "interior", (0.80, 0.80, 0.82))
            part("rear_seat", "seat", (1.0, 1.0, 1.0))
        part("seat", "seat", (1.0, 1.0, 1.0))
        roll_in, pitch_in = yoke
        for y in ((-0.32, 0.32) if show_yoke else ()):
            M = body_M @ translate((0.92 - pitch_in * 0.07, y, -0.14)) @ axis_rotation((1, 0, 0), roll_in * math.radians(45))
            pr["u_model"].write(gl_bytes(M))
            part("yoke", "panel_mat", (0.42, 0.42, 0.45))
        # parabrisas con reflejos (transparente)
        pr["u_model"].write(gl_bytes(body_M))
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        ctx.fbo.depth_mask = False
        pr["u_glass"].value = 1
        self.parts["glass"].render()
        pr["u_glass"].value = 0
        ctx.fbo.depth_mask = True
        ctx.disable(moderngl.BLEND)
