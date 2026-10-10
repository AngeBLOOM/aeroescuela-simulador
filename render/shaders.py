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

TERRAIN_FS = COMMON + FOG_FN + """
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
        lit = c * (u_amb * 1.25 + u_sun_col * (0.32 + 0.45 * diff));
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
        lit = col * (u_amb + u_sun_col * diff);
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

OBJECT_FS = COMMON + FOG_FN + """
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
    float diff = max(dot(n, u_sun), 0.0);
    vec3 h = normalize(u_sun + v);
    float spec = pow(max(dot(n, h), 0.0), 40.0) * u_spec;
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

TEX_FS = COMMON + FOG_FN + """
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
    float diff = max(-u_sun.z, 0.0);
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
