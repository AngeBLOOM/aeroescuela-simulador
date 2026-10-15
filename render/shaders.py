"""Shaders GLSL. Todo el mundo está en coordenadas NED (z hacia abajo).

Se usa un búfer de profundidad logarítmico para poder dibujar desde 10 cm
hasta 120 km sin parpadeo entre la pista y el terreno.
"""

COMMON = """
#version 330
uniform mat4 u_proj;
uniform mat4 u_view;
uniform vec3 u_campos;
uniform vec3 u_sun;
uniform vec3 u_sun_col;
uniform vec3 u_amb;
uniform vec3 u_fog_col;
uniform float u_fog_density;
uniform float u_logc;
"""

FOG_FN = """
vec3 apply_fog(vec3 col, vec3 wpos) {
    float d = length(wpos - u_campos);
    float f = exp(-pow(d * u_fog_density, 1.6));
    return mix(u_fog_col, col, clamp(f, 0.0, 1.0));
}
float fog_factor(vec3 wpos) {
    float d = length(wpos - u_campos);
    return clamp(exp(-pow(d * u_fog_density, 1.6)), 0.0, 1.0);
}
"""

# Sombras del Sol con dos mapas de profundidad: el del avión propio (caja pequeña a su alrededor, cada cuadro) y el
# del escenario (hangares, edificios y árboles en ~2,4 km alrededor de la cámara; se rehace al moverse o con el Sol).
# Fuera de las cajas todo queda iluminado.
SHADOW_FN = """
uniform sampler2DShadow u_shmap;
uniform mat4 u_shmat;
uniform float u_sh_on;
uniform sampler2DShadow u_shmap2;
uniform mat4 u_shmat2;
uniform float u_sh2_on;
uniform float u_sh2_texel;
float pcf4(sampler2DShadow m, vec3 q, float spread) {
    vec2 t = spread / vec2(textureSize(m, 0));
    return 0.25 * (texture(m, vec3(q.xy + vec2(-t.x, -t.y), q.z)) + texture(m, vec3(q.xy + vec2(t.x, -t.y), q.z))
                 + texture(m, vec3(q.xy + vec2(-t.x, t.y), q.z)) + texture(m, vec3(q.xy + vec2(t.x, t.y), q.z)));
}
// n: normal de la superficie (para correr el punto y que hangares y edificios no se sombreen a sí mismos)
float sun_shadow_n(vec3 wpos, vec3 n) {
    float s = 1.0;
    if (u_sh_on > 0.0) {
        vec4 p = u_shmat * vec4(wpos, 1.0);
        vec3 q = p.xyz / p.w;
        if (q.x > 0.0 && q.x < 1.0 && q.y > 0.0 && q.y < 1.0 && q.z < 1.0)
            s = 1.0 - u_sh_on * (1.0 - pcf4(u_shmap, q, 1.25));
    }
    if (u_sh2_on > 0.0) {
        float ndl = clamp(dot(n, u_sun), 0.0, 1.0);
        vec3 w2 = wpos + n * (u_sh2_texel * 1.5 * sqrt(1.0 - ndl * ndl)) + u_sun * 0.2;
        vec4 p = u_shmat2 * vec4(w2, 1.0);
        vec3 q = p.xyz / p.w;
        if (q.x > 0.0 && q.x < 1.0 && q.y > 0.0 && q.y < 1.0 && q.z < 1.0) {
            float edge = smoothstep(0.0, 0.1, min(min(q.x, 1.0 - q.x), min(q.y, 1.0 - q.y)));
            s *= 1.0 - u_sh2_on * edge * (1.0 - pcf4(u_shmap2, q, 0.9));
        }
    }
    return s;
}
float sun_shadow(vec3 wpos) { return sun_shadow_n(wpos, u_sun); }
"""

SHADOW_VS = """
#version 330
uniform mat4 u_lmvp;
in vec3 in_pos;
void main() { gl_Position = u_lmvp * vec4(in_pos, 1.0); }
"""
SHADOW_FS = """
#version 330
void main() { }
"""

# ---------------------------------------------------------------- terreno
TERRAIN_VS = COMMON + """
in vec3 in_pos;
in vec3 in_norm;
in vec3 in_col;
out vec3 v_pos;
out vec3 v_norm;
out vec3 v_col;
out float v_logz;
void main() {
    v_pos = in_pos;
    v_norm = in_norm;
    v_col = in_col;
    gl_Position = u_proj * u_view * vec4(in_pos, 1.0);
    v_logz = 1.0 + gl_Position.w;
}
"""

TERRAIN_FS = COMMON + FOG_FN + SHADOW_FN + """
uniform sampler2D u_detail;
uniform sampler2D u_grass;
uniform int u_grass_on;
uniform float u_grass_gain;
uniform int u_sat_on;
uniform sampler2D u_sat0;
uniform sampler2D u_sat1;
uniform sampler2D u_sat2;
uniform vec4 u_rect0;
uniform vec4 u_rect1;
uniform vec4 u_rect2;
uniform int u_water_on;
uniform sampler2D u_water;
uniform vec4 u_wrect;
uniform float u_time;
uniform float u_night;

uniform float u_ll_on;
uniform vec3 u_ll_pos;
uniform vec3 u_ll_dir;
float landing_light(vec3 p) {
    // foco de aterrizaje del avión: cono estrecho que se debilita con la distancia
    if (u_ll_on < 0.01) return 0.0;
    vec3 L = p - u_ll_pos;
    float dl = length(L);
    float c = dot(L / max(dl, 0.01), u_ll_dir);
    return u_ll_on * smoothstep(0.935, 0.985, c) * 2.4 / (1.0 + pow(dl / 170.0, 2.0));
}
in vec3 v_pos;
in vec3 v_norm;
in vec3 v_col;
in float v_logz;
out vec4 f_color;
vec3 lake_color(vec3 base) {
    // agua de lagos y embalses: color profundo, reflejo del cielo según el ángulo y destello del sol
    vec2 uv = v_pos.xy;
    float w1 = texture(u_detail, uv / 90.0 + vec2(u_time * 0.004, u_time * 0.002)).r;
    float w2 = texture(u_detail, uv / 23.0 - vec2(u_time * 0.006, -u_time * 0.003)).g;
    vec3 wn = normalize(vec3((w1 - 0.5) * 0.25, (w2 - 0.5) * 0.25, -1.0));
    vec3 v = normalize(u_campos - v_pos);
    float fres = pow(1.0 - clamp(-v.z, 0.0, 1.0), 4.0);
    vec3 deep = mix(vec3(0.05, 0.17, 0.24), base * 0.55, 0.18);
    vec3 col = mix(deep, u_fog_col * 0.95, 0.22 + 0.6 * fres);
    vec3 r = reflect(-v, wn);
    float spec = pow(max(dot(r, u_sun), 0.0), 120.0);
    return col * (u_amb * 0.6 + u_sun_col * 0.55) + u_sun_col * spec * 1.4;
}
vec2 rect_d(vec2 d, vec4 r) {
    // derivada de las coordenadas de textura de una capa (u = este, v = norte)
    return vec2(d.y / r.w, d.x / r.z);
}
void main() {
    vec3 n = normalize(v_norm);
    float diff = max(dot(n, u_sun), 0.0);
    float shf = sun_shadow(v_pos);
    vec2 uv = v_pos.xy;
    float dist = length(v_pos - u_campos);
    // derivadas calculadas una sola vez: así cada textura se lee solo donde aporta algo (dentro de un if)
    vec2 dx = dFdx(uv);
    vec2 dy = dFdy(uv);
    mat2 R1 = mat2(0.8, -0.6, 0.6, 0.8);
    mat2 R2 = mat2(0.28, 0.96, -0.96, 0.28);
    float nd = 0.5;
    if (dist < 700.0) {
        float d3 = textureGrad(u_detail, R2 * uv / 4.7, R2 * dx / 4.7, R2 * dy / 4.7).b;
        nd = mix(d3, 0.5, smoothstep(120.0, 700.0, dist));
    }
    vec3 lit;
    vec3 alb;
    float urban = 0.0;
    if (u_sat_on == 1) {
        // fotografía satelital real en tres niveles de detalle con transición suave
        vec2 uv0 = vec2((v_pos.y - u_rect0.y) / u_rect0.w, (v_pos.x - u_rect0.x) / u_rect0.z);
        vec2 uv1 = vec2((v_pos.y - u_rect1.y) / u_rect1.w, (v_pos.x - u_rect1.x) / u_rect1.z);
        vec2 uv2 = vec2((v_pos.y - u_rect2.y) / u_rect2.w, (v_pos.x - u_rect2.x) / u_rect2.z);
        vec3 c = textureGrad(u_sat0, uv0, rect_d(dx, u_rect0), rect_d(dy, u_rect0)).rgb;
        float w1 = smoothstep(0.0, 0.06, min(min(uv1.x, 1.0 - uv1.x), min(uv1.y, 1.0 - uv1.y)));
        if (w1 > 0.0)
            c = mix(c, textureGrad(u_sat1, uv1, rect_d(dx, u_rect1), rect_d(dy, u_rect1)).rgb, w1);
        float w2 = smoothstep(0.0, 0.08, min(min(uv2.x, 1.0 - uv2.x), min(uv2.y, 1.0 - uv2.y)));
        if (w2 > 0.0)
            c = mix(c, textureGrad(u_sat2, uv2, rect_d(dx, u_rect2), rect_d(dy, u_rect2)).rgb, w2);
        c = pow(c, vec3(1.08)) * (0.93 + 0.14 * nd);
        lit = c * (u_amb * 1.25 + u_sun_col * (0.32 + 0.45 * diff) * mix(0.3, 1.0, shf));
        alb = c;
        if (u_night > 0.01) {
            // zonas urbanas de la foto (grises claros, poco verdes): de noche se encienden las calles
            float lum = dot(c, vec3(0.333));
            float sat = max(max(c.r, c.g), c.b) - min(min(c.r, c.g), c.b);
            urban = smoothstep(0.24, 0.42, lum) * (1.0 - smoothstep(0.09, 0.2, sat)) * (1.0 - smoothstep(0.0, 0.04, c.g - c.r));
        }
    } else {
        float d1 = textureGrad(u_detail, R1 * uv / 53.0, R1 * dx / 53.0, R1 * dy / 53.0).r;
        float d2 = textureGrad(u_detail, R2 * uv / 431.0, R2 * dx / 431.0, R2 * dy / 431.0).g;
        float d4 = textureGrad(u_detail, uv / 1913.0, dx / 1913.0, dy / 1913.0).r;
        float n1 = mix(d1, 0.5, smoothstep(2500.0, 9000.0, dist));
        vec3 col = v_col * (0.84 + 0.32 * n1) * (0.86 + 0.28 * d2) * (0.9 + 0.2 * d4) * (0.86 + 0.28 * nd);
        lit = col * (u_amb + u_sun_col * diff * shf);
        alb = col;
    }
    if (u_grass_on == 1 && dist < 450.0) {
        float near = 1.0 - smoothstep(40.0, 450.0, dist);
        mat2 R3 = mat2(0.6, 0.8, -0.8, 0.6);
        float g1 = dot(textureGrad(u_grass, uv / 7.0, dx / 7.0, dy / 7.0).rgb, vec3(0.333)) * u_grass_gain;
        float g2 = dot(textureGrad(u_grass, R3 * uv / 29.0, R3 * dx / 29.0, R3 * dy / 29.0).rgb, vec3(0.333)) * u_grass_gain;
        lit *= mix(1.0, g1 * (0.5 + 0.5 * g2), near * (u_sat_on == 1 ? 0.45 : 0.8));
    }
    if (u_water_on == 1) {
        vec2 uvw = vec2((v_pos.y - u_wrect.y) / u_wrect.w, (v_pos.x - u_wrect.x) / u_wrect.z);
        float wm = textureGrad(u_water, uvw, rect_d(dx, u_wrect), rect_d(dy, u_wrect)).r;
        if (wm > 0.02) {
            lit = mix(lit, lake_color(lit), smoothstep(0.2, 0.7, wm));
            urban *= 1.0 - smoothstep(0.2, 0.5, wm);
        }
    }
    if (urban > 0.0) {
        float sp = textureGrad(u_detail, uv / 37.0, dx / 37.0, dy / 37.0).b
                 * textureGrad(u_detail, uv.yx / 11.0, dx.yx / 11.0, dy.yx / 11.0).r;
        float near = 1.0 - smoothstep(1500.0, 9000.0, dist);
        float glow = 0.07 + mix(0.25, 1.6 * smoothstep(0.30, 0.48, sp), near);
        lit += vec3(1.0, 0.64, 0.32) * urban * u_night * glow * 0.55;
    }
    lit += alb * landing_light(v_pos);
    f_color = vec4(apply_fog(lit, v_pos), 1.0);
    gl_FragDepth = log2(v_logz) * u_logc * 0.5;
}
"""

# ---------------------------------------------------------------- agua
WATER_VS = TERRAIN_VS
WATER_FS = COMMON + FOG_FN + """
uniform sampler2D u_detail;
uniform float u_time;
in vec3 v_pos;
in vec3 v_norm;
in vec3 v_col;
in float v_logz;
out vec4 f_color;
void main() {
    vec2 uv = v_pos.xy;
    float w1 = texture(u_detail, uv / 90.0 + vec2(u_time * 0.004, u_time * 0.002)).r;
    float w2 = texture(u_detail, uv / 23.0 - vec2(u_time * 0.006, -u_time * 0.003)).g;
    vec3 n = normalize(vec3((w1 - 0.5) * 0.25, (w2 - 0.5) * 0.25, -1.0));
    vec3 v = normalize(u_campos - v_pos);
    float fres = pow(1.0 - clamp(-v.z, 0.0, 1.0), 4.0);
    vec3 deep = vec3(0.05, 0.18, 0.26);
    vec3 sky = u_fog_col * 0.95;
    vec3 col = mix(deep, sky, 0.25 + 0.6 * fres);
    vec3 r = reflect(-v, n);
    float spec = pow(max(dot(r, u_sun), 0.0), 120.0);
    col = col * (u_amb * 0.6 + u_sun_col * 0.55) + u_sun_col * spec * 1.4;
    f_color = vec4(apply_fog(col, v_pos), 1.0);
    gl_FragDepth = log2(v_logz) * u_logc * 0.5;
}
"""

# ---------------------------------------------------------------- objetos
OBJECT_VS = COMMON + """
uniform mat4 u_model;
in vec3 in_pos;
in vec3 in_norm;
in vec3 in_col;
out vec3 v_pos;
out vec3 v_norm;
out vec3 v_col;
out vec3 v_lpos;
out vec3 v_lnorm;
out float v_logz;
void main() {
    vec4 wp = u_model * vec4(in_pos, 1.0);
    v_pos = wp.xyz;
    v_norm = mat3(u_model) * in_norm;
    v_col = in_col;
    v_lpos = in_pos;
    v_lnorm = in_norm;
    gl_Position = u_proj * u_view * wp;
    v_logz = 1.0 + gl_Position.w;
}
"""

OBJECT_FS = COMMON + FOG_FN + SHADOW_FN + """
uniform vec4 u_tint;
uniform float u_flat;
uniform float u_spec;
uniform int u_skin;
uniform sampler2D u_skin_tex;
in vec3 v_pos;
in vec3 v_norm;
in vec3 v_col;
in vec3 v_lpos;
in vec3 v_lnorm;
in float v_logz;
out vec4 f_color;
void main() {
    vec3 n = normalize(v_norm);
    vec3 v = normalize(u_campos - v_pos);
    if (dot(n, v) < 0.0) n = -n;
    float shf = sun_shadow_n(v_pos, n);
    float diff = max(dot(n, u_sun), 0.0) * shf;
    vec3 h = normalize(u_sun + v);
    float spec = pow(max(dot(n, h), 0.0), 40.0) * u_spec * shf;
    vec3 base = v_col * u_tint.rgb;
    if (u_skin == 1) {
        vec3 w = abs(normalize(v_lnorm));
        w /= (w.x + w.y + w.z + 1e-4);
        float sk = texture(u_skin_tex, v_lpos.yz * 0.6).r * w.x
                 + texture(u_skin_tex, v_lpos.xz * 0.6).r * w.y
                 + texture(u_skin_tex, v_lpos.xy * 0.6).r * w.z;
        float white = smoothstep(0.62, 0.86, min(min(v_col.r, v_col.g), v_col.b));
        base *= mix(1.0, sk / 0.9, white * 0.9);
        spec *= 1.0 + white * 1.5;
    }
    vec3 lit = base * (u_amb + u_sun_col * diff) + u_sun_col * spec;
    lit = mix(lit, base, u_flat);
    f_color = vec4(apply_fog(lit, v_pos), u_tint.a);
    gl_FragDepth = log2(v_logz) * u_logc * 0.5;
}
"""

# ---------------------------------------------------------------- texturizados (pista)
TEX_VS = COMMON + """
uniform mat4 u_model;
in vec3 in_pos;
in vec2 in_uv;
out vec3 v_pos;
out vec2 v_uv;
out float v_logz;
void main() {
    vec4 wp = u_model * vec4(in_pos, 1.0);
    v_pos = wp.xyz;
    v_uv = in_uv;
    gl_Position = u_proj * u_view * wp;
    v_logz = 1.0 + gl_Position.w;
}
"""

TEX_FS = COMMON + FOG_FN + SHADOW_FN + """
uniform sampler2D u_tex;
uniform sampler2D u_detail;
uniform sampler2D u_asph;
uniform int u_asph_on;
uniform float u_asph_gain;
uniform vec4 u_tint;

uniform float u_ll_on;
uniform vec3 u_ll_pos;
uniform vec3 u_ll_dir;
float landing_light(vec3 p) {
    // foco de aterrizaje del avión: cono estrecho que se debilita con la distancia
    if (u_ll_on < 0.01) return 0.0;
    vec3 L = p - u_ll_pos;
    float dl = length(L);
    float c = dot(L / max(dl, 0.01), u_ll_dir);
    return u_ll_on * smoothstep(0.935, 0.985, c) * 2.4 / (1.0 + pow(dl / 170.0, 2.0));
}
in vec3 v_pos;
in vec2 v_uv;
in float v_logz;
out vec4 f_color;
void main() {
    vec4 t = texture(u_tex, v_uv) * u_tint;
    float d = texture(u_detail, v_pos.xy / 9.0).r;
    float d2 = texture(u_detail, v_pos.xy / 71.0).g;
    vec3 base = t.rgb * (0.88 + 0.24 * d) * (0.9 + 0.2 * d2);
    if (u_asph_on == 1) {
        vec3 a1 = texture(u_asph, v_pos.xy / 11.0).rgb * u_asph_gain;
        vec3 a2 = texture(u_asph, mat2(0.8, -0.6, 0.6, 0.8) * v_pos.xy / 57.0).rgb * u_asph_gain;
        vec3 asph = a1 * mix(vec3(1.0), a2, 0.5);
        float paint = smoothstep(0.35, 0.7, dot(t.rgb, vec3(0.333)));
        base = t.rgb * mix(asph, mix(vec3(1.0), asph, 0.45), paint) * (0.95 + 0.1 * d2);
    }
    float diff = max(-u_sun.z, 0.0) * sun_shadow(v_pos);
    vec3 lit = base * (u_amb + u_sun_col * diff + landing_light(v_pos));
    f_color = vec4(apply_fog(lit, v_pos), t.a);
    gl_FragDepth = log2(v_logz) * u_logc * 0.5;
}
"""

# ---------------------------------------------------------------- cielo
SKY_VS = """
#version 330
in vec2 in_pos;
out vec2 v_ndc;
void main() {
    v_ndc = in_pos;
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""

SKY_FS = """
#version 330
uniform mat4 u_inv;
uniform vec3 u_sun;
uniform vec3 u_sun_col;
uniform vec3 u_zenith;
uniform vec3 u_horizon;
uniform vec3 u_ground;
uniform float u_night;
uniform float u_overcast;
uniform vec3 u_moon;
uniform float u_moon_on;
in vec2 v_ndc;
out vec4 f_color;
float hash(vec3 p) {
    p = fract(p * 0.3183099 + vec3(0.1, 0.2, 0.3));
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}
void main() {
    vec4 p = u_inv * vec4(v_ndc, 1.0, 1.0);
    vec3 dir = normalize(p.xyz / p.w);
    float up = -dir.z;
    vec3 col;
    if (up >= 0.0) {
        col = mix(u_horizon, u_zenith, pow(up, 0.55));
    } else {
        col = mix(u_horizon, u_ground, pow(min(-up * 4.0, 1.0), 0.7));
    }
    float sd = max(dot(dir, u_sun), 0.0);
    col += u_sun_col * (pow(sd, 10.0) * 0.22 + pow(sd, 90.0) * 0.4) * (1.0 - u_overcast * 0.8);
    float disk = smoothstep(0.9993, 0.9997, sd);
    col = mix(col, vec3(1.0, 0.97, 0.9) * 1.6, disk * (1.0 - u_overcast) * step(0.0, up + 0.02));
    if (u_night > 0.01 && up > 0.0) {
        vec3 q = floor(dir * 420.0);
        float h = hash(q);
        float star = step(0.9965, h) * (0.4 + 0.6 * hash(q + 7.0));
        col += vec3(star) * u_night * (1.0 - u_overcast) * smoothstep(0.0, 0.15, up);
    }
    if (u_moon_on > 0.01) {
        // Luna con su fase: se ilumina la parte de la esfera que mira al Sol
        float cm = dot(dir, u_moon);
        float R = 0.0085;
        col += vec3(0.55, 0.6, 0.75) * pow(max(cm, 0.0), 900.0) * 0.25 * u_moon_on;
        if (cm > cos(R * 1.05)) {
            vec3 rt = normalize(cross(u_moon, vec3(0.0, 0.0, -1.0)));
            vec3 uv = cross(rt, u_moon);
            vec2 q = vec2(dot(dir, rt), dot(dir, uv)) / R;
            float r2 = dot(q, q);
            float z = sqrt(max(0.0, 1.0 - r2));
            vec3 nrm = q.x * rt + q.y * uv - z * u_moon;
            float lit = smoothstep(-0.06, 0.12, dot(nrm, u_sun));
            float maria = 0.82 + 0.18 * hash(floor(vec3(q * 5.0, 1.0)));
            vec3 mc = mix(col * 1.05 + vec3(0.012, 0.014, 0.02), vec3(0.96, 0.94, 0.86) * maria, lit);
            col = mix(col, mc, u_moon_on * (1.0 - smoothstep(0.92, 1.0, sqrt(r2))));
        }
    }
    f_color = vec4(col, 1.0);
}
"""

# ---------------------------------------------------------------- luces puntuales
LIGHT_VS = COMMON + """
uniform float u_px;
uniform float u_bright;
in vec3 in_pos;
in vec3 in_col;
in float in_size;
out vec3 v_col;
out float v_logz;
out float v_fog;
void main() {
    vec3 tocam = u_campos - in_pos;
    float d = length(tocam);
    // se acerca la luz a la cámara para que el suelo no tape medio destello
    vec3 p = in_pos + tocam / max(d, 0.001) * min(10.0, d * 0.4);
    gl_Position = u_proj * u_view * vec4(p, 1.0);
    v_logz = 1.0 + gl_Position.w;
    v_fog = clamp(exp(-pow(d * u_fog_density * 0.55, 1.6)), 0.0, 1.0);
    float s = in_size * u_px / max(gl_Position.w, 0.1);
    float ps = clamp(s * 2.2, 3.4, 20.0);
    gl_PointSize = ps * mix(0.6, 1.0, u_bright);
    v_col = in_col * (0.5 + 0.9 * u_bright) * clamp(s * 2.2 / 3.4, 0.75, 1.0);
}
"""

LIGHT_FS = COMMON + """
in vec3 v_col;
in float v_logz;
in float v_fog;
out vec4 f_color;
void main() {
    vec2 c = gl_PointCoord * 2.0 - 1.0;
    float r = dot(c, c);
    if (r > 1.0) discard;
    float a = exp(-r * 2.2);
    f_color = vec4(v_col * a * v_fog, 1.0);
    gl_FragDepth = log2(v_logz) * u_logc * 0.5;
}
"""

# ---------------------------------------------------------------- nubes
CLOUD_VS = COMMON + """
uniform vec3 u_right;
uniform vec3 u_up;
uniform float u_nvar;
uniform vec3 u_offset;
in vec2 in_corner;
in vec4 in_center;   // xyz + tamaño
in float in_shade;
in float in_var;
out vec2 v_uv;
out vec3 v_pos;
out float v_shade;
out float v_logz;
void main() {
    vec3 p = in_center.xyz + u_offset + (in_corner.x * u_right + in_corner.y * u_up) * in_center.w;
    v_pos = p;
    vec2 uv = in_corner * 0.5 + 0.5;
    v_uv = vec2((mod(in_var, u_nvar) + uv.x) / u_nvar, uv.y);
    v_shade = in_shade + in_corner.y * 0.18;
    gl_Position = u_proj * u_view * vec4(p, 1.0);
    v_logz = 1.0 + gl_Position.w;
}
"""

CLOUD_FS = COMMON + FOG_FN + """
uniform sampler2D u_tex;
uniform float u_alpha;
uniform float u_dark;
in vec2 v_uv;
in vec3 v_pos;
in float v_shade;
in float v_logz;
out vec4 f_color;
void main() {
    vec4 tx = texture(u_tex, v_uv);
    float a = tx.a * u_alpha;
    float dc = length(v_pos - u_campos);
    a *= smoothstep(30.0, 300.0, dc);
    if (a < 0.01) discard;
    vec3 col = tx.rgb * mix(0.72, 1.0, clamp(v_shade, 0.0, 1.0));
    col = col * (u_amb * 0.95 + u_sun_col * 0.75) * u_dark;
    // a contraluz del Sol: los bordes finos brillan (borde plateado) y el centro grueso se oscurece
    float toward = pow(max(dot(normalize(v_pos - u_campos), u_sun), 0.0), 6.0) * smoothstep(-0.05, 0.1, -u_sun.z);
    float thin = 1.0 - smoothstep(0.15, 0.85, tx.a);
    col = col * (1.0 - 0.22 * toward * (1.0 - thin)) + u_sun_col * toward * (0.18 + 0.85 * thin) * u_dark;
    float f = fog_factor(v_pos);
    col = mix(u_fog_col, col, f);
    f_color = vec4(col * a, a);
    gl_FragDepth = log2(v_logz) * u_logc * 0.5;
}
"""

# ---------------------------------------------------------------- superposición 2D
OVERLAY_VS = """
#version 330
in vec2 in_pos;
out vec2 v_uv;
void main() {
    v_uv = vec2(in_pos.x * 0.5 + 0.5, 0.5 - in_pos.y * 0.5);
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""

OVERLAY_FS = """
#version 330
uniform sampler2D u_tex;
in vec2 v_uv;
out vec4 f_color;
void main() {
    f_color = texture(u_tex, v_uv);
}
"""

# Modelos 3D reales de los aviones (assets/modelos, convertidos con tools/importar_modelo.py): textura de color,
# mismo sol, ambiente, brillo y niebla que los objetos dibujados por código.
MODEL_VS = COMMON + """
uniform mat4 u_model;
in vec3 in_pos;
in vec3 in_norm;
in vec2 in_uv;
in float in_ao;
out vec3 v_pos;
out vec3 v_norm;
out vec2 v_uv;
out float v_ao;
out float v_logz;
void main() {
    vec4 wp = u_model * vec4(in_pos, 1.0);
    v_pos = wp.xyz;
    v_norm = mat3(u_model) * in_norm;
    v_uv = in_uv;
    v_ao = in_ao;
    gl_Position = u_proj * u_view * wp;
    v_logz = 1.0 + gl_Position.w;
}
"""

MODEL_FS = COMMON + FOG_FN + SHADOW_FN + """
uniform sampler2D u_tex;
uniform int u_has_tex;
uniform vec4 u_base;
uniform float u_cutoff;
uniform float u_spec;
uniform vec4 u_tint;
uniform float u_emis;
in vec3 v_pos;
in vec3 v_norm;
in vec2 v_uv;
in float v_ao;
in float v_logz;
out vec4 f_color;
void main() {
    vec4 c = u_base;
    if (u_has_tex == 1) c *= texture(u_tex, v_uv);
    if (c.a < u_cutoff) discard;
    vec3 n = normalize(v_norm);
    vec3 v = normalize(u_campos - v_pos);
    if (dot(n, v) < 0.0) n = -n;
    float shf = sun_shadow_n(v_pos, n);             // sombra de hangares y edificios sobre el avión
    float diff = max(dot(n, u_sun), 0.0) * shf;
    vec3 h = normalize(u_sun + v);
    float spec = pow(max(dot(n, h), 0.0), 48.0) * u_spec * smoothstep(0.35, 0.8, dot(c.rgb, vec3(0.333))) * shf;
    vec3 base = c.rgb * u_tint.rgb;
    // rendijas, uniones y el interior quedan en penumbra (oclusión horneada al importar el modelo)
    float ao = v_ao;
    vec3 lit = base * (u_amb * ao + u_sun_col * diff * mix(1.0, ao, 0.45)) + u_sun_col * spec * ao + base * u_emis;
    f_color = vec4(apply_fog(lit, v_pos), c.a * u_tint.a);
    gl_FragDepth = log2(v_logz) * u_logc * 0.5;
}
"""


# ---------------------------------------------------------------- imagen final (posproceso)
# Resplandor: se extraen las zonas muy claras a 1/4 de resolución y se difuminan en dos pasadas.
POST_VS = """
#version 330
in vec2 in_pos;
out vec2 v_uv;
void main() { v_uv = in_pos * 0.5 + 0.5; gl_Position = vec4(in_pos, 0.0, 1.0); }
"""

BRIGHT_FS = """
#version 330
uniform sampler2D u_tex;
uniform vec2 u_texel;
uniform float u_thr;
in vec2 v_uv;
out vec4 f_color;
vec3 pick(vec2 uv) {
    vec3 c = texture(u_tex, uv).rgb;
    float m = max(max(c.r, c.g), c.b);
    return c * smoothstep(u_thr, u_thr + 0.18, m);
}
void main() {
    // cuatro lecturas bilineales cubren el bloque de 4x4 píxeles de la imagen completa
    vec2 o = u_texel;
    vec3 c = pick(v_uv + vec2(-o.x, -o.y)) + pick(v_uv + vec2(o.x, -o.y)) + pick(v_uv + vec2(-o.x, o.y)) + pick(v_uv + o);
    f_color = vec4(c * 0.25, 1.0);
}
"""

BLUR_FS = """
#version 330
uniform sampler2D u_tex;
uniform vec2 u_dir;
in vec2 v_uv;
out vec4 f_color;
void main() {
    // gaussiana de 9 muestras con 5 lecturas bilineales
    vec3 c = texture(u_tex, v_uv).rgb * 0.2270;
    c += (texture(u_tex, v_uv + u_dir * 1.3846).rgb + texture(u_tex, v_uv - u_dir * 1.3846).rgb) * 0.3162;
    c += (texture(u_tex, v_uv + u_dir * 3.2308).rgb + texture(u_tex, v_uv - u_dir * 3.2308).rgb) * 0.0703;
    f_color = vec4(c, 1.0);
}
"""

COMP_FS = """
#version 330
uniform sampler2D u_tex;
uniform sampler2D u_bloom;
uniform vec4 u_vp;
uniform float u_fx;          // 0: imagen tal cual (pantallas de carga); 1: con efectos
uniform float u_bloom_k;
uniform vec3 u_grade;        // tono de la luz según la hora (cálido al amanecer y al atardecer, frío de noche)
uniform float u_contrast;
uniform float u_sat;
uniform vec3 u_sun_uv;       // posición del Sol en la imagen (x, y) y fuerza del destello (z)
uniform float u_aspect;
out vec4 c;
float sun_seen(vec2 p) {
    vec3 s = texture(u_tex, p).rgb;
    return smoothstep(0.9, 0.985, min(min(s.r, s.g), s.b));
}
void main() {
    vec2 uv = (gl_FragCoord.xy - u_vp.xy) / u_vp.zw;
    vec3 col = texture(u_tex, uv).rgb;
    if (u_fx < 0.5) { c = vec4(col, 1.0); return; }
    col += texture(u_bloom, uv).rgb * u_bloom_k;
    // destello del Sol: solo si el disco se ve (no lo tapan el terreno, el tablero ni las nubes)
    if (u_sun_uv.z > 0.0) {
        vec2 sp = u_sun_uv.xy;
        vec2 e = vec2(0.006, 0.006 * u_aspect);
        float vis = (sun_seen(sp) + sun_seen(sp + vec2(e.x, 0.0)) + sun_seen(sp - vec2(e.x, 0.0))
                   + sun_seen(sp + vec2(0.0, e.y)) + sun_seen(sp - vec2(0.0, e.y))) * 0.2;
        float k = u_sun_uv.z * vis;
        if (k > 0.001) {
            vec2 d = (uv - sp) * vec2(u_aspect, 1.0);
            float r = length(d);
            vec3 sc = vec3(1.0, 0.9, 0.75);
            col += sc * (0.05 * exp(-r * 18.0) + 0.18 * exp(-r * 70.0)) * k;              // halo
            col += sc * exp(-abs(d.y) * 260.0) * exp(-abs(d.x) * 3.2) * 0.22 * k;       // raya horizontal
            vec2 axis = vec2(0.5) - sp;                                                // fantasmas hacia el centro
            for (int i = 0; i < 4; i++) {
                float t = (i == 0) ? 0.55 : (i == 1) ? 1.0 : (i == 2) ? 1.45 : 1.9;
                float rad = (i == 0) ? 0.035 : (i == 1) ? 0.018 : (i == 2) ? 0.06 : 0.026;
                vec3 gc = (i == 0) ? vec3(0.35, 0.55, 1.0) : (i == 1) ? vec3(1.0, 0.7, 0.35)
                        : (i == 2) ? vec3(0.45, 1.0, 0.6) : vec3(0.8, 0.5, 1.0);
                vec2 gp = sp + axis * t;
                float gr = length((uv - gp) * vec2(u_aspect, 1.0));
                col += gc * smoothstep(rad, rad * 0.55, gr) * 0.05 * k;
            }
        }
    }
    // gradación de color: tono de la hora, contraste suave en S y algo más de saturación
    col *= u_grade;
    // hombro suave: lo que pasa de 0,8 se comprime hacia el blanco en vez de recortarse (el Sol y los blancos
    // de la pista no forman manchas planas)
    vec3 over = max(col - 0.8, 0.0);
    col = min(col, 0.8) + 0.2 * (1.0 - exp(-over / 0.2));
    col = mix(col, col * col * (3.0 - 2.0 * col), u_contrast * (1.0 - smoothstep(0.55, 0.95, max(max(col.r, col.g), col.b))));
    float l = dot(col, vec3(0.2126, 0.7152, 0.0722));
    col = mix(vec3(l), col, u_sat);
    // viñeta muy leve y un poco de ruido para que los degradados del cielo no hagan escalones
    vec2 q = uv - 0.5;
    col *= 1.0 - 0.16 * dot(q, q) * 2.0;
    col += (fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233))) * 43758.5453) - 0.5) / 255.0;
    c = vec4(clamp(col, 0.0, 1.0), 1.0);
}
"""


# ---------------------------------------------------------------- árboles (instancias con dos niveles de detalle)
TREE_VS = COMMON + """
uniform float u_time;
uniform float u_wind;
in vec3 in_pos;
in vec3 in_norm;
in vec3 in_col;
in vec3 i_pos;
in float i_scale;
in float i_yaw;
in vec3 i_col;
out vec3 v_pos;
out vec3 v_norm;
out vec3 v_col;
out float v_h;
out float v_logz;
void main() {
    float c = cos(i_yaw), s = sin(i_yaw);
    vec3 p = in_pos * i_scale;
    p = vec3(c * p.x - s * p.y, s * p.x + c * p.y, p.z);
    // la copa se mece con el viento (la base queda quieta)
    float hf = clamp(-in_pos.z, 0.0, 1.0);
    float ph = i_pos.x * 0.07 + i_pos.y * 0.05;
    p.xy += vec2(sin(u_time * 1.6 + ph), cos(u_time * 1.2 + ph * 1.3)) * u_wind * hf * hf * i_scale * 0.012;
    vec3 wp = i_pos + p;
    v_pos = wp;
    v_norm = vec3(c * in_norm.x - s * in_norm.y, s * in_norm.x + c * in_norm.y, in_norm.z);
    v_col = in_col * i_col;
    v_h = hf;
    gl_Position = u_proj * u_view * vec4(wp, 1.0);
    v_logz = 1.0 + gl_Position.w;
}
"""

TREE_FS = COMMON + FOG_FN + SHADOW_FN + """
in vec3 v_pos;
in vec3 v_norm;
in vec3 v_col;
in float v_h;
in float v_logz;
out vec4 f_color;
void main() {
    vec3 n = normalize(v_norm);
    vec3 v = normalize(u_campos - v_pos);
    float shf = sun_shadow_n(v_pos, n);
    // follaje: luz envolvente (la cara en sombra no queda negra) y algo de luz que atraviesa las hojas a contraluz
    float wrap = max((dot(n, u_sun) + 0.4) / 1.4, 0.0);
    float back = pow(max(dot(-v, u_sun), 0.0), 4.0) * 0.3;
    vec3 lit = v_col * (u_amb * (0.7 + 0.3 * v_h) + u_sun_col * (wrap * 0.9 + back) * shf);
    f_color = vec4(apply_fog(lit, v_pos), 1.0);
    gl_FragDepth = log2(v_logz) * u_logc * 0.5;
}
"""

SHADOW_TREE_VS = """
#version 330
uniform mat4 u_lmvp;
in vec3 in_pos;
in vec3 i_pos;
in float i_scale;
in float i_yaw;
void main() {
    float c = cos(i_yaw), s = sin(i_yaw);
    vec3 p = in_pos * i_scale;
    p = vec3(c * p.x - s * p.y, s * p.x + c * p.y, p.z);
    gl_Position = u_lmvp * vec4(i_pos + p, 1.0);
}
"""



# ---------------------------------------------------------------- fachadas con ventanas (edificios y casas)
BLDG_VS = COMMON + """
in vec3 in_pos;
in vec3 in_norm;
in vec3 in_col;
in vec3 in_uvh;      // u a lo largo de la pared (m), v altura sobre el suelo (m), altura del edificio (m)
in float in_style;
out vec3 v_pos;
out vec3 v_norm;
out vec3 v_col;
out vec3 v_uvh;
out float v_style;
out float v_logz;
void main() {
    v_pos = in_pos;
    v_norm = in_norm;
    v_col = in_col;
    v_uvh = in_uvh;
    v_style = in_style;
    gl_Position = u_proj * u_view * vec4(in_pos, 1.0);
    v_logz = 1.0 + gl_Position.w;
}
"""

BLDG_FS = COMMON + FOG_FN + SHADOW_FN + """
uniform float u_night;
in vec3 v_pos;
in vec3 v_norm;
in vec3 v_col;
in vec3 v_uvh;
in float v_style;
in float v_logz;
out vec4 f_color;
float hash2(vec2 p) {                                      // barato (sin senos)
    vec3 q = fract(vec3(p.xyx) * 0.1031);
    q += dot(q, q.yzx + 33.33);
    return fract((q.x + q.y) * q.z);
}
float band(float f, float a, float b, float w) {          // 1 entre a y b, con bordes suavizados de ancho w
    return smoothstep(a - w, a + w, f) * (1.0 - smoothstep(b - w, b + w, f));
}
void main() {
    vec3 n = normalize(v_norm);
    vec3 v = normalize(u_campos - v_pos);
    if (dot(n, v) < 0.0) n = -n;
    float st = floor(v_style);
    float var = fract(v_style);
    float shf = sun_shadow_n(v_pos, n);
    float diff = max(dot(n, u_sun), 0.0) * shf;
    vec3 col;
    if (st > 2.5) {
        // techo: grano suave
        col = v_col * (0.9 + 0.1 * hash2(floor(v_uvh.xy * 0.7))) * (u_amb + u_sun_col * diff);
    } else {
        float x = v_uvh.x;
        float y = v_uvh.y;
        float ht = v_uvh.z;
        bool house = st < 0.5;
        bool glassy = st > 1.5;
        float fh = house ? 2.9 : 3.3;                          // altura de cada piso
        float cw = house ? 3.8 : (glassy ? 2.2 : 3.0);         // ancho de cada módulo de ventana
        float g0 = house ? 0.0 : 4.2;                          // planta baja (comercios) en los edificios
        float wx0 = glassy ? 0.05 : (house ? 0.28 : 0.2);
        float wy0 = glassy ? 0.06 : 0.3;
        float wy1 = glassy ? 0.94 : 0.82;
        vec2 cell = vec2(x / cw, (y - g0) / fh);
        vec2 fw = max(fwidth(cell), vec2(1e-4));
        float far = smoothstep(0.25, 0.7, max(fw.x, fw.y));    // de lejos: el promedio (sin moiré y más liviano)
        float inside = step(0.0, y - g0) * step(y - g0, floor(max(ht - 0.6 - g0, 0.0) / fh) * fh);
        float win = (1.0 - 2.0 * wx0) * (wy1 - wy0) * inside;
        float r = 0.5 + 0.3 * var;
        float slab = 1.0;
        float spec = 0.0;
        vec3 inner = vec3(0.055, 0.07, 0.085);
        float fres = 0.3;
        if (far < 0.999) {
            vec2 f = fract(cell);
            vec2 id = floor(cell);
            float w1 = band(f.x, wx0, 1.0 - wx0, fw.x) * band(f.y, wy0, wy1, fw.y) * inside;
            if (!house && y < g0 && y > 0.0) {                 // vidrieras de la planta baja
                float sx = x / 5.0;
                w1 = band(fract(sx), 0.08, 0.92, fw.x * cw / 5.0) * band(y, 0.45, g0 - 0.7, fw.y * fh);
                id = vec2(floor(sx), -1.0);
            }
            win = mix(w1, win, far);
            r = hash2(id + var * 17.0);
            inner += (r > 0.8 ? vec3(0.22, 0.2, 0.17) * (1.0 - far) : vec3(0.0));   // cortinas claras
            fres = pow(1.0 - max(dot(n, v), 0.0), 3.0);
            vec3 h = normalize(u_sun + v);
            spec = pow(max(dot(n, h), 0.0), 90.0) * shf * (1.0 - far);
            if (!house)
                slab = 1.0 - 0.14 * (1.0 - smoothstep(0.0, 0.05 + fw.y, f.y)) * (1.0 - far) * step(0.0, y - g0);
        }
        // vidrio: refleja el cielo según el ángulo, oscuro por dentro
        vec3 glass = mix(inner, u_fog_col * 0.95, 0.22 + 0.6 * fres);
        if (glassy) glass = mix(glass, vec3(0.18, 0.3, 0.36), 0.35);
        float ao = 0.62 + 0.38 * smoothstep(0.0, 3.0, y);
        vec3 litw = v_col * slab * (u_amb * ao + u_sun_col * diff);
        vec3 litg = glass * (u_amb * 0.6 + u_sun_col * diff * 0.3) + u_sun_col * spec * 1.3;
        win = clamp(win, 0.0, 1.0);
        col = mix(litw, litg, win);
        // de noche se encienden ventanas al azar (cálidas, algunas frías de oficina); de lejos, el promedio
        if (u_night > 0.01) {
            float on = mix(step(0.5 + 0.2 * var, r), 0.4, far) * u_night;
            vec3 lamp = r > 0.9 ? vec3(0.8, 0.88, 1.0) : vec3(1.0, 0.76, 0.45);
            col += lamp * win * on * (0.45 + 0.55 * r) * mix(1.0, 0.55, far);
        }
    }
    f_color = vec4(apply_fog(col, v_pos), 1.0);
    gl_FragDepth = log2(v_logz) * u_logc * 0.5;
}
"""


# ---------------------------------------------------------------- tráfico lejano: el puntito que ve el piloto
# Un avión ligero a 4 km mide menos de un píxel y la imagen lo pierde, pero el ojo lo ve como un punto oscuro contra
# el cielo o el suelo. Este punto (1,5 a 3 px, atenuado por la bruma) deja entrenar el «ver y evitar».
SPECK_VS = COMMON + FOG_FN + """
in vec3 in_pos;
in float in_size;
in float in_alpha;
out float v_alpha;
out float v_logz;
void main() {
    gl_Position = u_proj * u_view * vec4(in_pos, 1.0);
    v_logz = 1.0 + gl_Position.w;
    gl_PointSize = in_size;
    v_alpha = in_alpha * fog_factor(in_pos);
}
"""
SPECK_FS = """
#version 330
uniform float u_logc;
uniform vec3 u_speck_col;
in float v_alpha;
in float v_logz;
out vec4 f_color;
void main() {
    vec2 q = gl_PointCoord * 2.0 - 1.0;
    float a = v_alpha * (1.0 - smoothstep(0.55, 1.0, dot(q, q)));
    if (a < 0.01) discard;
    f_color = vec4(u_speck_col, a);
    gl_FragDepth = log2(v_logz) * u_logc * 0.5;
}
"""
