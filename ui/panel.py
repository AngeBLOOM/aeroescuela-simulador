"""Panel de instrumentos de la cabina (analógico o de cristal) con mandos clicables."""
import math
import time

import pygame

from sim.mathx import FT, KT, clamp
from .gauges import Gauges, bar_gauge
from . import assets
from .glass import GlassCockpit
from .ui import COL, panel_box


def lcd(f, surf, rect, text, size=20, color=(120, 235, 255), sub=None):
    rect = pygame.Rect(rect)
    pygame.draw.rect(surf, (6, 10, 14), rect, border_radius=4)
    pygame.draw.rect(surf, (60, 66, 74), rect, 1, border_radius=4)
    f.blit(surf, text, (rect.centerx, rect.centery + (0 if not sub else 3)), size, color, mono=True, bold=True, anchor="center")
    if sub:
        f.blit(surf, sub, (rect.x + 4, rect.y + 1), 10, (130, 140, 150))


class CockpitPanel:
    def __init__(self, fonts):
        self.f = fonts
        self.g = Gauges(fonts)
        self.glass = GlassCockpit(fonts)
        self.mode = "analog"
        self.bg_cache = {}
        self.starter_held = False
        self.hobbs = 1234.5
        self.timer_start = None
        self.timer_acc = 0.0

    # ------------------------------------------------------------ fondo
    def _background(self, rect):
        key = (rect.size, self.mode)
        bg = self.bg_cache.get(key)
        if bg is None:
            w, h = rect.size
            bg = pygame.Surface((w, h + 40), pygame.SRCALPHA)
            mat = assets.tiled("panel_material.png", (w, h + 40), 420)
            if mat is not None:
                bg.blit(mat, (0, 0))
                # luz de cabina: más clara arriba, penumbra abajo y en los lados
                shade = pygame.Surface((w, h + 40), pygame.SRCALPHA)
                for y in range(h + 40):
                    t = y / (h + 40)
                    pygame.draw.line(shade, (0, 0, 0, int(20 + 95 * t * t)), (0, y), (w, y))
                for x in range(0, w, 4):
                    e = abs(x / w - 0.5) * 2
                    pygame.draw.line(shade, (0, 0, 0, int(55 * e ** 3)), (x, 0), (x, h + 40), 4)
                bg.blit(shade, (0, 0))
            else:
                for y in range(h + 40):
                    t = y / (h + 40)
                    c = (int(44 - 14 * t), int(47 - 14 * t), int(52 - 14 * t), 255)
                    pygame.draw.line(bg, c, (0, y), (w, y))
            # visera (glareshield) curvada
            pts = [(0, 40)]
            for i in range(41):
                x = w * i / 40
                pts.append((x, 40 - 34 * math.sin(math.pi * i / 40) ** 0.6))
            pts.append((w, 40))
            gs = assets.tiled("glareshield.png", (w, 60), 300)
            if gs is not None:
                mask = pygame.Surface((w, 60), pygame.SRCALPHA)
                pygame.draw.polygon(mask, (255, 255, 255, 255), pts)
                pygame.draw.polygon(mask, (255, 255, 255, 255), [(0, 40), (w, 40), (w, 54), (0, 54)])
                tex = pygame.Surface((w, 60), pygame.SRCALPHA)
                tex.blit(gs, (0, 0))
                tex.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
                # sombra que proyecta la visera sobre el tablero
                for k in range(16):
                    pygame.draw.line(bg, (0, 0, 0, max(0, 120 - k * 8)), (0, 54 + k), (w, 54 + k))
                bg.blit(tex, (0, 0))
                pygame.draw.lines(bg, (60, 62, 66, 255), False, pts[1:-1], 2)
            else:
                pygame.draw.polygon(bg, (24, 25, 28, 255), pts)
                pygame.draw.polygon(bg, (24, 25, 28, 255), [(0, 40), (w, 40), (w, 54), (0, 54)])
                pygame.draw.lines(bg, (70, 72, 78, 255), False, pts[1:-1], 2)
            self.bg_cache[key] = bg
        return bg

    # ------------------------------------------------------------ dibujo
    def draw(self, surf, rect, world, ui, app):
        rect = pygame.Rect(rect)
        surf.blit(self._background(rect), (rect.x, rect.y - 40))
        s = min(rect.h / 340.0, rect.w / 1450.0)
        self.s = s
        top = rect.y + 16 * s
        ac = world.ac
        sysm = ac.sys
        # brújula magnética sobre la visera
        cw, chh = 150 * s, 28 * s
        self.g.compass(surf, (rect.centerx - cw / 2 - 260 * s, rect.y - 22 * s, cw, chh), world.ind.compass)
        self.starter_held = False
        if self.mode == "glass":
            right_x = self._glass_area(surf, rect, top, s, world, ui)
        else:
            right_x = self._analog_area(surf, rect, top, s, world, ui)
        self._right_area(surf, rect, top, s, right_x, world, ui, app)
        self._switch_row(surf, rect, s, world, ui)

    # ------------------------------------------------------------ analógico
    def _analog_area(self, surf, rect, top, s, world, ui):
        ac = world.ac
        ind = world.ind
        sysm = ac.sys
        e = sysm.engine
        g = self.g
        x0 = rect.x + 8 * s
        # motor
        tr = int(46 * s)
        tc = (x0 + 72 * s, top + 8 * s + tr)
        if ac.t.fixed_pitch:
            g.tach(surf, tc, tr, e.rpm, hours=self.hobbs + world.stats["flight_time"] / 3600)
        else:
            g.tach(surf, tc, tr, e.rpm, green=(2000, 2700), hours=self.hobbs + world.stats["flight_time"] / 3600)
        by = top + 16 * s + 2 * tr
        bw = 140 * s
        bh = 25 * s
        cap = ac.t.fuel_capacity / 2
        items = [
            ("COMB IZQ (L)", sysm.fuel_l / 2, 0, cap, (cap * 0.15, cap), ""),
            ("COMB DER (L)", sysm.fuel_l / 2, 0, cap, (cap * 0.15, cap), ""),
            ("TEMP ACEITE °F", e.oil_temp, 50, 260, (100, 245), ""),
            ("PRES ACEITE PSI", e.oil_press, 0, 115, (50, 90), ""),
            ("EGT °F", e.egt, 800, 1650, (1150, 1550), ""),
            ("VACÍO inHg", sysm.vacuum, 2, 7, (4.5, 5.5), ""),
        ]
        if not ac.t.fixed_pitch:
            items.insert(2, ("ADMISIÓN inHg", e.map_inhg, 10, 35, (15, 25), ""))
        for i, (lab, v, lo, hi, gr, u) in enumerate(items[:7]):
            bar_gauge(self.f, surf, (x0, by + i * bh, bw, bh - 4 * s), lab, v, lo, hi, gr,
                      fmt="{:.1f}" if hi < 40 else "{:.0f}")
        # seis instrumentos básicos
        r = int(62 * s)
        sp = 2 * r + 10 * s
        cx0 = x0 + 160 * s + r
        y1 = top + 8 * s + r
        y2 = y1 + 2 * r + 12 * s
        powered = sysm.electric_ok
        g.asi(surf, (cx0, y1), r, ind.ias, ac.t.v)
        g.attitude(surf, (cx0 + sp, y1), r, ind.ai_roll, ind.ai_pitch, flag=sysm.gyro_spin < 0.5)
        g.altimeter(surf, (cx0 + 2 * sp, y1), r, ind.alt_ft, world.kollsman)
        g.turn_coord(surf, (cx0, y2), r, ind.turn_rate, ind.slip, powered)
        g.heading(surf, (cx0 + sp, y2), r, ind.dg, world.ap.hdg_bug)
        g.vsi(surf, (cx0 + 2 * sp, y2), r, ind.vs_fpm)
        # interacción: rueda del ratón sobre instrumentos
        alt_rect = (cx0 + 2 * sp - r, y1 - r, 2 * r, 2 * r)
        d = ui.scroll(alt_rect)
        if d:
            world.kollsman = clamp(world.kollsman + d, 940, 1060)
        if ui.hit(alt_rect, right=True):
            world.kollsman = world.weather.qnh_hpa
        dg_rect = (cx0 + sp - r, y2 - r, 2 * r, 2 * r)
        d = ui.scroll(dg_rect)
        if d:
            world.ap.hdg_bug = (world.ap.hdg_bug + d * (5 if abs(d) == 1 else 1)) % 360
        if ui.hit(dg_rect, right=True):
            world.ind.dg_drift = 0.0          # alinear el direccional con la brújula
        if ui.hover(alt_rect):
            ui.tooltip = "Rueda: ajustar altímetro (hPa) · Clic derecho: poner QNH"
        if ui.hover(dg_rect):
            ui.tooltip = "Rueda: marcador de rumbo · Clic derecho: alinear con la brújula"
        # CDI de NAV1 y NAV2
        cr = int(52 * s)
        cx = cx0 + 2 * sp + r + 14 * s + cr
        src1 = world.nav_source()
        for nav, yy, title in ((src1, y1, "GPS" if src1 is world.gps else "NAV 1"), (world.nav2, y2, "NAV 2")):
            rr = (cx - cr, yy - cr, 2 * cr, 2 * cr)
            if nav is world.nav2 and world.show_adf:
                g.adf(surf, (cx, yy), cr, world.adf)
                d = ui.scroll(rr)
                if d:
                    world.adf.tune(d * (10 if pygame.key.get_mods() & pygame.KMOD_SHIFT else 1))
                if ui.hover(rr):
                    ui.tooltip = "Rueda: sintonizar el ADF (kHz; Mayús: de 10 en 10) · Clic derecho: volver a NAV 2"
            elif nav is world.gps:
                g.cdi(surf, (cx, yy), cr, nav, title)
                d = ui.scroll(rr)
                if d and nav.obs_mode:
                    nav.set_obs(True, nav.obs_course + d * 2)
                if ui.hover(rr):
                    ui.tooltip = ("Rueda: curso del modo OBS del GPS" if nav.obs_mode else
                                  "CDI en GPS: sigue el plan de vuelo (F7: volver a VLOC)")
            else:
                g.cdi(surf, (cx, yy), cr, nav, title)
                d = ui.scroll(rr)
                if d:
                    nav.obs = (nav.obs + d * 2) % 360
                if ui.hover(rr):
                    ui.tooltip = "Rueda: girar el OBS (curso)" + (" · Clic derecho: ver el ADF" if nav is world.nav2 else "")
            if nav is world.nav2 and ui.hit(rr, right=True):
                world.show_adf = not world.show_adf
        return cx + cr + 16 * s

    # ------------------------------------------------------------ cristal
    def _glass_area(self, surf, rect, top, s, world, ui):
        x0 = rect.x + 8 * s
        h = rect.bottom - 44 * s - top
        right_need = (300 + 175 + 52 * (2 if world.ac.t.fixed_pitch else 3) + 100) * s
        avail = rect.w - x0 - right_need - 24 * s
        frame = assets.image("pantalla_g1000_marco.png")
        if frame is None:
            pw = int(min(h * 1.5, avail * 0.53))
            mw = int(min(h * 1.35, avail - pw - 10 * s))
            pfd = pygame.Rect(x0, top + 2 * s, pw, int(h))
            mfd = pygame.Rect(pfd.right + 10 * s, pfd.y, mw, int(h))
            self.glass.pfd(surf, pfd, world, ui)
            self.glass.mfd(surf, mfd, world, ui)
            return mfd.right + 14 * s
        # marco físico con bordes finos (9 porciones); la pantalla ocupa el hueco central
        insets = assets.hole_insets("pantalla_g1000_marco.png") or (92, 54, 92, 128)
        bs = 0.30 * s
        L, T, R, B = (v * bs for v in insets)
        fh = h + 4 * s
        fw_p = min((fh - T - B) * 1.48 + L + R, avail * 0.54)
        fw_m = min((fh - T - B) * 1.40 + L + R, avail - fw_p - 6 * s)
        x = x0 - 6 * s
        right = x
        for fw, kind in ((fw_p, "pfd"), (fw_m, "mfd")):
            fr = pygame.Rect(x, top - 2 * s, fw, fh)
            scr = pygame.Rect(fr.x + L, fr.y + T, fr.w - L - R, fr.h - T - B)
            if kind == "pfd":
                self.glass.pfd(surf, scr, world, ui)
            else:
                self.glass.mfd(surf, scr, world, ui)
            img = assets.nine_slice("pantalla_g1000_marco.png", fr.size, insets, bs)
            surf.blit(img, fr.topleft)
            x = fr.right + 6 * s
            right = fr.right
        return right + 12 * s

    # ------------------------------------------------------------ radios, PA y mandos
    def _right_area(self, surf, rect, top, s, x, world, ui, app):
        f = self.f
        ac = world.ac
        sysm = ac.sys
        av = sysm.avionics_ok
        w = 300 * s
        y = top + 4 * s
        rh = 34 * s
        # COM
        def radio(label, act, stby, fmt, tune_fn, swap_fn, yy, ident=None):
            lab_r = pygame.Rect(x, yy, 46 * s, rh)
            f.blit(surf, label, (lab_r.x, lab_r.centery), int(13), COL["grey"], bold=True, anchor="midleft")
            a = pygame.Rect(x + 50 * s, yy, 100 * s, rh)
            b = pygame.Rect(x + 186 * s, yy, 100 * s, rh)
            if av:
                lcd(f, surf, a, fmt.format(act), int(19 * s + 4), (90, 240, 140), sub=ident)
                lcd(f, surf, b, fmt.format(stby), int(17 * s + 3), (120, 200, 255))
            else:
                lcd(f, surf, a, "", 18)
                lcd(f, surf, b, "", 18)
            sw = pygame.Rect(x + 154 * s, yy + 5 * s, 28 * s, rh - 10 * s)
            if ui.cockpit_button(surf, sw, "⇄", size=14, tip="Intercambiar activa/reserva"):
                swap_fn()
            d = ui.scroll(b)
            if d:
                tune_fn(d)
            if ui.hover(b):
                ui.tooltip = "Rueda: sintonizar frecuencia de reserva"

        def com_tune(d):
            world.com_standby = round(clamp(world.com_standby + d * 0.025, 118.0, 136.975), 3)

        def com_swap():
            world.com_freq, world.com_standby = world.com_standby, world.com_freq

        def nav_tune(nv):
            def fn(d):
                f_ = round((nv.standby + d * 0.05) * 20) / 20
                nv.standby = 108.0 if f_ > 117.95 else (117.95 if f_ < 108.0 else f_)
            return fn
        radio("COM 1", world.com_freq, world.com_standby, "{:.3f}", com_tune, com_swap, y)
        radio("NAV 1", world.nav1.freq, world.nav1.standby, "{:.2f}", nav_tune(world.nav1), world.nav1.swap,
              y + rh + 6 * s, world.nav1.ident if world.nav1.station else None)
        y2 = y + 2 * (rh + 6 * s)
        if world.show_adf:
            adf = world.adf

            def adf_tune(d):
                step = 10 if pygame.key.get_mods() & pygame.KMOD_SHIFT else 1
                f_ = round(adf.standby + d * step)
                adf.standby = float(190 if f_ > 1750 else (1750 if f_ < 190 else f_))
            radio("ADF", adf.freq, adf.standby, "{:.0f}", adf_tune, adf.swap, y2, adf.ident if adf.station else None)
        else:
            radio("NAV 2", world.nav2.freq, world.nav2.standby, "{:.2f}", nav_tune(world.nav2), world.nav2.swap,
                  y2, world.nav2.ident if world.nav2.station else None)
        lab2 = pygame.Rect(x, y2, 46 * s, rh)
        if ui.hit(lab2) or ui.hit(lab2, right=True):
            world.show_adf = not world.show_adf
        if ui.hover(lab2):
            ui.tooltip = "Clic: cambiar entre NAV 2 y ADF (radiofaro NDB, en kHz)"
        # transpondedor
        yy = y + 3 * (rh + 6 * s)
        f.blit(surf, "XPDR", (x, yy + rh / 2), 13, COL["grey"], bold=True, anchor="midleft")
        xr = pygame.Rect(x + 50 * s, yy, 100 * s, rh)
        lcd(f, surf, xr, f"{world.xpdr:04d}" if av else "", int(19 * s + 4), (90, 240, 140), sub="ALT" if av else None)
        if ui.cockpit_button(surf, (x + 154 * s, yy + 5 * s, 132 * s, rh - 10 * s), "IDENT", size=13, tip="Identificación del transpondedor"):
            app.flash("IDENT enviado")
        # piloto automático
        yy += rh + 10 * s
        ap = world.ap
        apr = pygame.Rect(x, yy, w - 14 * s, 40 * s)
        pygame.draw.rect(surf, (10, 12, 14), apr, border_radius=5)
        pygame.draw.rect(surf, (70, 76, 86), apr, 1, border_radius=5)
        if av:
            lat = ap.lat if ap.engaged or ap.fd else ""
            armed = ("NAV" if not ap.gs_armed else "LOC") if ap.nav_armed else ""
            vert = ap.vert if ap.engaged else ""
            f.blit(surf, ("AP " if ap.engaged else "   ") + lat, (apr.x + 8, apr.y + 4), 15, COL["green"], mono=True, bold=True)
            if armed:
                f.blit(surf, armed, (apr.x + 8, apr.y + 21), 12, COL["white"], mono=True)
            txt = vert
            if vert == "VS":
                txt += f" {ap.vs_sel:+.0f}"
            f.blit(surf, txt, (apr.centerx - 10, apr.y + 4), 15, COL["green"], mono=True, bold=True)
            if ap.alt_armed or ap.gs_armed:
                f.blit(surf, "ALTS" if ap.alt_armed else "GS", (apr.centerx - 10, apr.y + 21), 12, COL["white"], mono=True)
            f.blit(surf, f"{ap.alt_sel:5.0f} FT", (apr.right - 8, apr.y + 4), 15, (120, 200, 255), mono=True, bold=True,
                   anchor="topright")
            f.blit(surf, f"RUMBO {ap.hdg_bug:03.0f}", (apr.right - 8, apr.y + 21), 12, (255, 170, 60), mono=True,
                   anchor="topright")
        d = ui.scroll(apr)
        if d:
            ap.alt_sel = clamp(ap.alt_sel + d * 100, 0, 17500)
        if ui.hover(apr):
            ui.tooltip = "Rueda: altitud seleccionada"
        yy += 44 * s
        bw = (w - 14 * s - 6 * 6 * s) / 7
        btns = [("AP", ap.engaged, lambda: ap.toggle(ac), "Conectar/desconectar piloto automático (Z)"),
                ("HDG", ap.lat == "HDG", lambda: ap.set_hdg(ac), "Mantener rumbo del marcador (X)"),
                ("NAV", ap.lat == "NAV" or (ap.nav_armed and not ap.gs_armed), lambda: ap.set_nav(ac, False), "Seguir VOR/LOC de NAV1"),
                ("APR", ap.lat == "APR" or ap.gs_armed, lambda: ap.set_nav(ac, True), "Aproximación ILS (LOC + senda)"),
                ("ALT", ap.vert == "ALT", lambda: ap.set_alt(ac), "Mantener altitud (C)"),
                ("VS", ap.vert == "VS", lambda: ap.set_vs(ac), "Velocidad vertical"),
                ("▲▼", False, None, "Rueda: ajustar VS / cabeceo")]
        for i, (lab, act, fn, tip) in enumerate(btns):
            r_ = pygame.Rect(x + i * (bw + 6 * s), yy, bw, 28 * s)
            if ui.cockpit_button(surf, r_, lab, active=act and av, size=13, enabled=av, tip=tip) and fn:
                fn()
            if lab == "▲▼":
                d = ui.scroll(r_)
                if d:
                    ap.adjust_vs(d * 100)
        # anunciadores
        yy += 36 * s
        ann = [
            ("VOLT", sysm.master and sysm.bus_volts < 24.5, COL["red"]),
            ("ACEITE", sysm.engine.oil_press < 20 and sysm.master, COL["red"]),
            ("VACÍO", sysm.vacuum < 3.0 and sysm.master, COL["amber"]),
            ("COMB", sysm.fuel_l < 20 and sysm.master, COL["amber"]),
            ("PÉRD", sysm.stall_warning, COL["red"]),
            ("FRENO", sysm.parking_brake and sysm.master, COL["amber"]),
        ]
        aw = (w - 14 * s - 5 * 4 * s) / 6
        for i, (lab, on, col) in enumerate(ann):
            r_ = pygame.Rect(x + i * (aw + 4 * s), yy, aw, 20 * s)
            pygame.draw.rect(surf, col if on else (30, 30, 32), r_, border_radius=3)
            f.blit(surf, lab, r_.center, 10, (10, 10, 10) if on else (90, 90, 90), bold=True, anchor="center")
        mk = world.nav1.marker if av else None
        yy += 26 * s
        for i, (m, col) in enumerate((("O", (60, 120, 255)), ("M", (255, 190, 40)), ("I", (240, 240, 240)))):
            r_ = pygame.Rect(x + i * 30 * s, yy, 26 * s, 18 * s)
            on = mk == m and (time.time() * 3) % 1 < 0.6
            pygame.draw.rect(surf, col if on else (30, 30, 32), r_, border_radius=3)
            f.blit(surf, m, r_.center, 11, (10, 10, 10) if on else (80, 80, 80), bold=True, anchor="center")
        # cronómetro
        tr = pygame.Rect(x + 100 * s, yy, 90 * s, 18 * s)
        el = self.timer_acc + (time.time() - self.timer_start if self.timer_start else 0.0)
        lcd(f, surf, tr, f"{int(el // 60):02d}:{int(el % 60):02d}", 13, (240, 240, 240))
        if ui.hit(tr):
            if self.timer_start:
                self.timer_acc += time.time() - self.timer_start
                self.timer_start = None
            else:
                self.timer_start = time.time()
        if ui.hit(tr, right=True):
            self.timer_start = None
            self.timer_acc = 0.0
        if ui.hover(tr):
            ui.tooltip = "Cronómetro: clic iniciar/parar, clic derecho reiniciar"
        oat = ac.temp_k - 273.15 if hasattr(ac, "temp_k") else 15.0
        f.blit(surf, f"OAT {oat:+.0f}°C", (x + 200 * s, yy + 9 * s), 12, COL["grey"], anchor="midleft")

        # palancas
        lx = x + w + 6 * s
        self._levers(surf, lx, top, s, rect, world, ui)

    def _levers(self, surf, lx, top, s, rect, world, ui):
        f = self.f
        ac = world.ac
        sysm = ac.sys
        e = sysm.engine
        h = rect.bottom - 52 * s - top
        if ac.t.fadec:
            if sysm.twin:
                levers = [("POT IZQ", sysm.engines[0].throttle, (20, 20, 22), "throttle", sysm.engines[0]),
                          ("POT DER", sysm.engines[1].throttle, (20, 20, 22), "throttle", sysm.engines[1])]
            else:
                levers = [("POTENCIA", e.throttle, (20, 20, 22), "throttle", e)]
        else:
            levers = [("GASES", e.throttle, (20, 20, 22), "throttle", e)]
            if not ac.t.fixed_pitch:
                levers.append(("HÉLICE", e.prop_lever, (40, 90, 200), "prop", e))
            levers.append(("MEZCLA", e.mixture, (200, 30, 30), "mixture", e))
        for i, (lab, val, col, key, e) in enumerate(levers):
            tx = lx + 16 * s + i * 52 * s
            track = pygame.Rect(tx, top + 34 * s, 14 * s, h - 52 * s)
            pygame.draw.rect(surf, (12, 12, 14), track, border_radius=6)
            ky = track.bottom - val * track.h
            knob = pygame.Rect(0, 0, 38 * s, 20 * s)
            knob.center = (track.centerx, ky)
            pygame.draw.rect(surf, col, knob, border_radius=8)
            pygame.draw.rect(surf, (200, 200, 200), knob, 1, border_radius=8)
            f.blit(surf, lab, (track.centerx, top + 4 * s), 11, COL["grey"], bold=True, anchor="midtop")
            f.blit(surf, f"{val * 100:.0f}%", (track.centerx, track.bottom + 4 * s), 11, COL["white"], anchor="midtop")
            area = track.inflate(36 * s, 20 * s)
            if pygame.mouse.get_pressed()[0] and area.collidepoint(ui.mouse):
                v = clamp((track.bottom - ui.mouse[1]) / track.h, 0.0, 1.0)
                setattr(e, {"throttle": "throttle", "prop": "prop_lever", "mixture": "mixture"}[key], v)
                ui.consumed = True
            d = ui.scroll(area)
            if d:
                attr = {"throttle": "throttle", "prop": "prop_lever", "mixture": "mixture"}[key]
                setattr(e, attr, clamp(getattr(e, attr) + d * 0.02, 0.0, 1.0))
        # flaps
        fx = lx + 16 * s + len(levers) * 52 * s + 6 * s
        f.blit(surf, "FLAPS", (fx + 26 * s, top + 4 * s), 11, COL["grey"], bold=True, anchor="midtop")
        settings = ac.t.flap_settings
        for i, st in enumerate(settings):
            r_ = pygame.Rect(fx, top + 22 * s + i * 30 * s, 52 * s, 24 * s)
            act = sysm.flaps_cmd == i
            if ui.cockpit_button(surf, r_, f"{st}°" if st else "ARR", active=act, size=12):
                sysm.flaps_cmd = i
        fy = top + 22 * s + len(settings) * 30 * s + 2 * s
        f.blit(surf, f"pos {sysm.flaps:.0f}°", (fx + 26 * s, fy), 11, COL["white"], anchor="midtop")
        # compensador
        ty = fy + 22 * s
        f.blit(surf, "TRIM", (fx + 26 * s, ty), 11, COL["grey"], bold=True, anchor="midtop")
        tr = pygame.Rect(fx + 18 * s, ty + 16 * s, 16 * s, 64 * s)
        pygame.draw.rect(surf, (12, 12, 14), tr, border_radius=4)
        for k in range(9):
            yk = tr.y + 4 + k * (tr.h - 8) / 8
            pygame.draw.line(surf, (60, 60, 64), (tr.x + 2, yk), (tr.right - 2, yk), 1)
        ty0 = tr.centery - ac.trim * (tr.h / 2 - 4)
        pygame.draw.polygon(surf, COL["white"], [(tr.right + 2, ty0), (tr.right + 10 * s, ty0 - 5 * s), (tr.right + 10 * s, ty0 + 5 * s)])
        f.blit(surf, "ARR", (tr.x - 3, tr.y), 9, COL["dim"], anchor="topright")
        f.blit(surf, "ABJ", (tr.x - 3, tr.bottom), 9, COL["dim"], anchor="bottomright")
        d = ui.scroll(tr.inflate(30 * s, 10 * s))
        if d:
            ac.trim = clamp(ac.trim - d * 0.04, -1, 1)
        # freno de estacionamiento y tren
        px = fx + 66 * s
        if ui.cockpit_button(surf, (px, top + 22 * s, 86 * s, 30 * s), "FRENO EST.", active=sysm.parking_brake, size=11,
                     tip="Freno de estacionamiento (B)"):
            sysm.parking_brake = not sysm.parking_brake
        sel = {0: "CERRADO", 1: "IZQ", 2: "DER", 3: "AMBOS"}[sysm.fuel_selector]
        if ui.cockpit_button(surf, (px, top + 58 * s, 86 * s, 30 * s), f"COMB: {sel}", size=11, tip="Selector de combustible"):
            sysm.fuel_selector = (sysm.fuel_selector - 1) % 4 if sysm.fuel_selector else 3
        if ac.t.retractable:
            gr = pygame.Rect(px, top + 96 * s, 86 * s, 40 * s)
            if ui.cockpit_button(surf, gr, "TREN " + ("ABAJO" if sysm.gear_down else "ARRIBA"), active=sysm.gear_down, size=11,
                         tip="Palanca del tren (G)"):
                sysm.gear_down = not sysm.gear_down
            for i in range(3):
                c = COL["green"] if sysm.gear_pos > 0.99 else (COL["red"] if 0.01 < sysm.gear_pos < 0.99 else (30, 30, 30))
                pygame.draw.circle(surf, c, (int(px + 18 * s + i * 25 * s), int(gr.bottom + 12 * s)), int(7 * s))
        # carga de combustible y tiempo
        ff = sum(en.fuel_flow for en in sysm.engines)
        mins = sysm.fuel_l / max(ff, 1.0) * 60 if ff > 1 else 0
        f.blit(surf, f"Comb. {sysm.fuel_l:.0f} L", (px, top + 160 * s), 12, COL["white"])
        f.blit(surf, f"Flujo {ff:.1f} L/h", (px, top + 176 * s), 12, COL["grey"])
        if ac.t.fadec:
            loads = " / ".join(f"{en.load:.0f}%" for en in sysm.engines)
            f.blit(surf, f"Carga {loads}", (px, top + 208 * s), 12, COL["green"])
        if mins:
            f.blit(surf, f"Autonomía {int(mins // 60)}h{int(mins % 60):02d}", (px, top + 192 * s), 12, COL["grey"])

    # ------------------------------------------------------------ interruptores
    def _switch_row(self, surf, rect, s, world, ui):
        ac = world.ac
        sysm = ac.sys
        e = sysm.engine
        h = 40 * s
        y = rect.bottom - h - 4 * s
        x = rect.x + 8 * s
        sw = 62 * s
        if ac.t.fadec:
            # interruptores ENGINE MASTER (uno por motor); en OFF el motor se para y la hélice se embandera
            names = ["MOTOR IZQ", "MOTOR DER"] if sysm.twin else ["MOTOR"]
            for en, nm in zip(sysm.engines, names):
                r_ = pygame.Rect(x, y, 70 * s, h)
                on = en.magnetos > 0
                if ui.toggle(surf, r_, nm, on, size=10,
                             tip="Interruptor maestro del motor (en OFF: motor parado y hélice embanderada)"):
                    en.magnetos = 0 if on else 3
                x += 74 * s
            x += 4 * s
        else:
            mags = ["OFF", "DER", "IZQ", "AMBOS"]
            r_ = pygame.Rect(x, y, 96 * s, h)
            pygame.draw.rect(surf, (26, 27, 30), r_, border_radius=6)
            pygame.draw.rect(surf, (90, 90, 96), r_, 1, border_radius=6)
            self.f.blit(surf, "MAGNETOS", (r_.centerx, r_.y + 3), 10, COL["grey"], bold=True, anchor="midtop")
            self.f.blit(surf, mags[e.magnetos], (r_.centerx, r_.bottom - 4), 15, COL["white"], bold=True, anchor="midbottom")
            if ui.hit(r_):
                e.magnetos = (e.magnetos + 1) % 4
            if ui.hit(r_, right=True):
                e.magnetos = (e.magnetos - 1) % 4
            if ui.hover(r_):
                ui.tooltip = "Clic: girar llave de magnetos · Clic derecho: atrás"
            x += 100 * s
        st = pygame.Rect(x, y, 82 * s, h)
        held = pygame.mouse.get_pressed()[0] and st.collidepoint(ui.mouse)
        pygame.draw.rect(surf, (140, 40, 30) if held else (70, 30, 28), st, border_radius=6)
        self.f.blit(surf, "ARRANQUE", st.center, 13, COL["white"], bold=True, anchor="center")
        if held:
            self.starter_held = True
            ui.consumed = True
        if ui.hover(st):
            ui.tooltip = "Mantener pulsado para arrancar el motor"
        ui.hit(st)
        x += 90 * s
        L = sysm.lights
        items = [
            ("BAT/ALT", sysm.master, lambda: setattr(sysm, "master", not sysm.master), "Interruptor maestro"),
            ("AVIÓNICA", sysm.avionics, lambda: setattr(sysm, "avionics", not sysm.avionics), "Bus de aviónica"),
        ]
        if not sysm.twin:
            items.append(("BOMBA", sysm.fuel_pump, lambda: setattr(sysm, "fuel_pump", not sysm.fuel_pump), "Bomba eléctrica de combustible"))
        items += [
            ("BEACON", L["beacon"], lambda: L.__setitem__("beacon", not L["beacon"]), "Luz anticolisión"),
            ("ATERRIZ", L["landing"], lambda: L.__setitem__("landing", not L["landing"]), "Luz de aterrizaje (L)"),
            ("TAXI", L["taxi"], lambda: L.__setitem__("taxi", not L["taxi"]), "Luz de rodaje"),
            ("NAV", L["nav"], lambda: L.__setitem__("nav", not L["nav"]), "Luces de navegación"),
            ("STROBE", L["strobe"], lambda: L.__setitem__("strobe", not L["strobe"]), "Luces estroboscópicas"),
            ("PITOT", sysm.pitot_heat, lambda: setattr(sysm, "pitot_heat", not sysm.pitot_heat), "Calefacción del pitot"),
        ]
        if sysm.twin:
            items = items[:-2]
        if ac.t.carburetor:
            items.append(("CALEF CARB", sysm.carb_heat, lambda: setattr(sysm, "carb_heat", not sysm.carb_heat),
                          "Calefacción al carburador (F6): úsela si bajan las rpm o el motor va irregular"))
        for lab, val, fn, tip in items:
            if ui.toggle(surf, (x, y, sw, h), lab, val, size=10, tip=tip):
                fn()
            x += sw + 4 * s
        # botón de modo de cabina
        r_ = pygame.Rect(rect.right - 150 * s, y, 142 * s, h)
        lab = "CABINA: G1000" if self.mode == "glass" else "CABINA: CLÁSICA"
        if ui.cockpit_button(surf, r_, lab, size=12, tip="Cambiar entre instrumentos clásicos y cabina de cristal (Tab)"):
            self.mode = "glass" if self.mode == "analog" else "analog"
