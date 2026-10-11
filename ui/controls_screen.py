"""Pantalla de mandos por sistema (tecla O): motor, combustible, eléctrico, luces,
flaps y compensador, y tren. Cada mando se usa con el ratón y actúa sobre el avión.

Las piezas son fotos (assets/mandos/<nombre>.png, con transparencia) generadas con IA;
si una foto no existe se dibuja una versión sencilla por código.
"""
import math
import os

import pygame

from sim.mathx import clamp
from . import assets
from .ui import COL

DIR = "mandos"

PIECES = {
    "perilla_gases": "pomo negro de gases",
    "perilla_mezcla": "pomo rojo de mezcla",
    "perilla_helice": "pomo azul de hélice",
    "llave_magnetos": "llave de contacto",
    "selector_combustible": "manija del selector de combustible",
    "interruptor_arriba": "interruptor en posición encendido",
    "interruptor_abajo": "interruptor en posición apagado",
    "palanca_flaps": "pomo de la palanca de flaps",
    "rueda_trim": "rueda del compensador",
    "palanca_tren": "palanca del tren con pomo de rueda",
    "freno_mano": "tirador del freno de estacionamiento",
}


def sprite(name, size):
    """Foto del mando escalada (o None si todavía no existe)."""
    p = os.path.join(DIR, name + ".png")
    if not os.path.exists(assets.path(p)):
        return None
    return assets.scaled(p, size)


def plate(surf, f, text, center, size=13, col=(235, 235, 230)):
    """Rótulo blanco sobre placa negra, como los de un tablero real."""
    img = f.render(text, size, col, bold=True)
    r = img.get_rect(center=(int(center[0]), int(center[1])))
    bg = r.inflate(12, 6)
    pygame.draw.rect(surf, (12, 12, 13), bg, border_radius=3)
    pygame.draw.rect(surf, (70, 70, 74), bg, 1, border_radius=3)
    surf.blit(img, r)
    return bg


class ControlsScreen:
    def __init__(self, fonts):
        self.f = fonts
        self.tab = 0
        self.drag = None
        self.starter = False

    # ------------------------------------------------------------ pestañas
    def tabs(self, world):
        t = world.ac.t
        tabs = ["MOTOR", "COMBUSTIBLE", "ELÉCTRICO", "LUCES", "FLAPS Y COMPENSADOR"]
        if t.retractable:
            tabs.append("TREN Y FRENOS")
        else:
            tabs.append("FRENOS")
        tabs.append("EMERGENCIA")
        return tabs

    def draw(self, surf, world, ui, app):
        W, H = surf.get_size()
        f = self.f
        self.starter = False
        board = pygame.Rect(16, int(H * 0.40), W - 32, int(H * 0.58))
        # fondo: material del tablero
        mat = assets.tiled("panel_material.png", board.size, 380)
        if mat is not None:
            surf.blit(mat, board.topleft)
            shade = pygame.Surface(board.size, pygame.SRCALPHA)
            shade.fill((0, 0, 0, 70))
            surf.blit(shade, board.topleft)
        else:
            pygame.draw.rect(surf, (48, 50, 54), board)
        pygame.draw.rect(surf, (20, 20, 22), board, 3, border_radius=10)
        tabs = self.tabs(world)
        self.tab = min(self.tab, len(tabs) - 1)
        x = board.x + 12
        for i, name in enumerate(tabs):
            tw = f.get(13, True).size(name)[0] + 26
            r = pygame.Rect(x, board.y + 10, tw, 32)
            if ui.button(surf, r, name, active=i == self.tab, size=13):
                self.tab = i
            x += tw + 6
        f.blit(surf, f"MANDOS · {world.ac.t.short}", (board.right - 16, board.y + 26), 14, COL["accent"], bold=True,
               anchor="midright")
        area = pygame.Rect(board.x + 20, board.y + 56, board.w - 40, board.h - 70)
        if area.w > 1060:                 # en pantallas anchas los mandos se agrupan al centro, no dispersos
            area = pygame.Rect(board.centerx - 530, area.y, 1060, area.h)
        pygame.draw.line(surf, (70, 76, 86), (board.x + 12, board.y + 50), (board.right - 12, board.y + 50))
        page = tabs[self.tab]
        getattr(self, {"MOTOR": "_engine", "COMBUSTIBLE": "_fuel", "ELÉCTRICO": "_elec", "LUCES": "_lights",
                       "FLAPS Y COMPENSADOR": "_flaps", "TREN Y FRENOS": "_gear", "FRENOS": "_gear",
                       "EMERGENCIA": "_emergency"}[page])(
            surf, area, world, ui)
        if not pygame.mouse.get_pressed()[0]:
            self.drag = None
        # el motor de arranque solo gira mientras se mantiene pulsada la llave en ARRANQUE
        app.panel.starter_held = self.starter
        if board.collidepoint(ui.mouse):
            ui.consumed = True
        return board

    # ------------------------------------------------------------ piezas genéricas
    def lever(self, surf, track, value, key, color, sprite_name, label, ui):
        """Palanca en su ranura: arriba = más. Arrastrar o rueda del ratón."""
        f = self.f
        pygame.draw.rect(surf, (8, 8, 9), track, border_radius=track.w // 2)
        pygame.draw.rect(surf, (70, 70, 74), track, 1, border_radius=track.w // 2)
        for k in range(11):                                            # marcas
            y = track.bottom - 10 - k * (track.h - 20) / 10
            pygame.draw.line(surf, (150, 150, 150), (track.right + 6, y), (track.right + (14 if k % 5 == 0 else 9), y), 1)
        ky = track.bottom - 10 - value * (track.h - 20)
        kw, kh = int(track.w * 4.2), int(track.w * 2.4)
        img = sprite(sprite_name, (kw, kh))
        kr = pygame.Rect(0, 0, kw, kh)
        kr.center = (track.centerx, int(ky))
        if img is not None:
            surf.blit(img, kr)
        else:
            sh = kr.move(3, 4)
            pygame.draw.rect(surf, (0, 0, 0), sh, border_radius=kh // 2)
            pygame.draw.rect(surf, color, kr, border_radius=kh // 2)
            hi = pygame.Rect(kr.x + 4, kr.y + 3, kr.w - 8, kr.h // 3)
            pygame.draw.rect(surf, tuple(min(255, c + 60) for c in color), hi, border_radius=kh // 3)
            pygame.draw.rect(surf, (15, 15, 15), kr, 2, border_radius=kh // 2)
        plate(surf, f, label, (track.centerx, track.y - 40), 13)
        f.blit(surf, f"{value * 100:.0f}%", (track.centerx, track.bottom + 16), 13, COL["white"], bold=True, anchor="center")
        area = pygame.Rect(track.x - kw // 2, track.y - 10, track.w + kw, track.h + 20)
        if ui.clicked and area.collidepoint(ui.clicked):
            self.drag = key
            ui.clicked = None
        if self.drag == key and pygame.mouse.get_pressed()[0]:
            value = clamp((track.bottom - 10 - ui.mouse[1]) / (track.h - 20), 0.0, 1.0)
        d = ui.scroll(area)
        if d:
            value = clamp(value + d * 0.03, 0.0, 1.0)
        if ui.hover(area):
            ui.tooltip = f"{label}: arrastre arriba/abajo o use la rueda"
        return value

    def switch(self, surf, center, on, label, ui, tip=None, guard=None):
        """Interruptor de palanca (arriba = encendido). Devuelve True si se pulsó."""
        f = self.f
        cx, cy = int(center[0]), int(center[1])
        w, h = 46, 74
        r = pygame.Rect(0, 0, w, h)
        r.center = (cx, cy)
        img = sprite("interruptor_arriba" if on else "interruptor_abajo", (w, h))
        if img is not None:
            surf.blit(img, r)
        else:
            pygame.draw.circle(surf, (12, 12, 13), (cx, cy), 17)
            pygame.draw.circle(surf, (110, 110, 115), (cx, cy), 17, 2)
            pygame.draw.circle(surf, (60, 60, 64), (cx, cy), 9)
            tip_y = cy - 30 if on else cy + 30
            pygame.draw.line(surf, (215, 215, 220), (cx, cy), (cx, tip_y), 7)
            pygame.draw.circle(surf, (235, 235, 240), (cx, tip_y), 7)
        if guard is not None:
            pygame.draw.rect(surf, guard, r.inflate(14, 10), 3, border_radius=8)
        plate(surf, f, label, (cx, cy + h // 2 + 18), 12)
        f.blit(surf, "ON" if on else "OFF", (cx + w // 2 + 16, cy - 26 if on else cy + 26), 11,
               COL["green"] if on else COL["grey"], bold=True, anchor="center")
        hit = r.inflate(20, 30)
        if ui.hover(hit) and tip:
            ui.tooltip = tip
        return ui.hit(hit)

    def rotary(self, surf, center, radius, positions, index, sprite_name, title, ui, hold_last=False):
        """Mando giratorio (llave de magnetos, selector de combustible). Clic en un rótulo para elegir
        posición; clic en el mando avanza, clic derecho retrocede. Devuelve (nuevo índice, sostenido)."""
        f = self.f
        cx, cy = int(center[0]), int(center[1])
        pygame.draw.circle(surf, (14, 14, 15), (cx, cy), radius + 8)
        pygame.draw.circle(surf, (95, 95, 100), (cx, cy), radius + 8, 3)
        pygame.draw.circle(surf, (30, 30, 32), (cx, cy), radius - 6)
        n = len(positions)
        held = False
        for i, (lab, ang) in enumerate(positions):
            tw = f.get(12, True).size(lab)[0] + 12
            dist = radius + 26 + abs(math.sin(math.radians(ang))) * tw / 2
            p = (cx + math.sin(math.radians(ang)) * dist, cy - math.cos(math.radians(ang)) * dist)
            act = i == index
            r = plate(surf, f, lab, p, 12, COL["yellow"] if act else (230, 230, 225))
            q0 = (cx + math.sin(math.radians(ang)) * (radius + 8), cy - math.cos(math.radians(ang)) * (radius + 8))
            q1 = (cx + math.sin(math.radians(ang)) * (radius + 16), cy - math.cos(math.radians(ang)) * (radius + 16))
            pygame.draw.line(surf, (230, 230, 225), q0, q1, 3)
            if hold_last and i == n - 1:
                if pygame.mouse.get_pressed()[0] and r.inflate(10, 10).collidepoint(ui.mouse):
                    held = True
                    index = i
                ui.hit(r.inflate(10, 10))
            elif ui.hit(r.inflate(10, 10)):
                index = i
        ang = positions[index][1]
        size = int(radius * 2.0)
        img = sprite(sprite_name, (size, size))
        if img is not None:
            rot = pygame.transform.rotozoom(img, -ang, 1.0)
            surf.blit(rot, rot.get_rect(center=(cx, cy)))
        else:
            a = math.radians(ang)
            dx, dy = math.sin(a), -math.cos(a)
            px, py = -dy, dx
            L, w = radius * 0.95, radius * 0.28
            pts = [(cx + dx * L + px * w * 0.6, cy + dy * L + py * w * 0.6), (cx + dx * L - px * w * 0.6, cy + dy * L - py * w * 0.6),
                   (cx - dx * L * 0.7 - px * w, cy - dy * L * 0.7 - py * w), (cx - dx * L * 0.7 + px * w, cy - dy * L * 0.7 + py * w)]
            pygame.draw.polygon(surf, (0, 0, 0), [(x + 3, y + 4) for x, y in pts])
            pygame.draw.polygon(surf, (175, 175, 180), pts)
            pygame.draw.polygon(surf, (60, 60, 64), pts, 2)
            pygame.draw.line(surf, (240, 240, 240), (cx, cy), (cx + dx * L * 0.9, cy + dy * L * 0.9), 3)
        plate(surf, f, title, (cx, cy + radius + 66), 13)
        body = pygame.Rect(cx - radius, cy - radius, 2 * radius, 2 * radius)
        if not (hold_last and held):
            if ui.hit(body):
                index = min(index + 1, n - 1 - (1 if hold_last else 0)) if index < n - 1 - (1 if hold_last else 0) else 0
            elif ui.hit(body, right=True):
                index = max(0, index - 1)
        if ui.hover(body):
            ui.tooltip = f"{title}: clic en un rótulo para elegir · clic en el mando avanza, clic derecho retrocede"
        return index, held

    # ------------------------------------------------------------ páginas
    def _engine(self, surf, area, world, ui):
        ac = world.ac
        t = ac.t
        sysm = ac.sys
        engs = sysm.engines
        x = area.x + 40
        th = area.h - 130
        top = area.y + 78
        names = ["IZQ", "DER"] if len(engs) > 1 else [""]
        # palancas
        for en, nm in zip(engs, names):
            sfx = f" {nm}" if nm else ""
            items = [("GASES" if not t.fadec else "POTENCIA", "throttle", (24, 24, 26), "perilla_gases")]
            if not t.fadec and not t.fixed_pitch:
                items.append(("HÉLICE", "prop_lever", (35, 80, 190), "perilla_helice"))
            if not t.fadec:
                items.append(("MEZCLA", "mixture", (190, 28, 28), "perilla_mezcla"))
            for lab, attr, col, spr in items:
                track = pygame.Rect(x, top, 16, th)
                v = self.lever(surf, track, getattr(en, attr), (id(en), attr), col, spr, lab + sfx, ui)
                setattr(en, attr, v)
                x += 110
            x += 20
        # encendido
        x += 40
        cx = x + 120
        cy = area.y + area.h * 0.42
        if t.fadec:
            for i, (en, nm) in enumerate(zip(engs, names)):
                if self.switch(surf, (cx + i * 120, cy - 20), en.magnetos > 0, ("MOTOR " + nm).strip(), ui,
                               tip="Interruptor maestro del motor (ENGINE MASTER)", guard=(170, 30, 30)):
                    en.magnetos = 0 if en.magnetos > 0 else 3
            r = pygame.Rect(0, 0, 150, 50)
            r.center = (cx + (60 if len(engs) > 1 else 0), cy + 120)
            held = pygame.mouse.get_pressed()[0] and r.collidepoint(ui.mouse)
            pygame.draw.rect(surf, (150, 30, 26) if held else (90, 24, 22), r, border_radius=8)
            pygame.draw.rect(surf, (20, 20, 20), r, 2, border_radius=8)
            self.f.blit(surf, "ARRANQUE", r.center, 15, COL["white"], bold=True, anchor="center")
            ui.hit(r)
            if held:
                self.starter = True
            if ui.hover(r):
                ui.tooltip = "Mantener pulsado para arrancar (motor de arranque)"
        else:
            e = engs[0]
            pos = [("OFF", -60), ("DER", -25), ("IZQ", 10), ("AMBOS", 45), ("ARRANQUE", 85)]
            idx = e.magnetos if not getattr(self, "_starting", False) else 4
            idx, held = self.rotary(surf, (cx, cy), 52, pos, idx, "llave_magnetos", "MAGNETOS", ui, hold_last=True)
            self._starting = held
            if held:
                e.magnetos = 3
                self.starter = True
            else:
                e.magnetos = min(idx, 3)
        # indicadores del motor
        ix = cx + 260
        f = self.f
        for k, (lab, val) in enumerate([("RPM", " / ".join(f"{en.rpm:.0f}" for en in engs)),
                                        ("P. ACEITE", " / ".join(f"{en.oil_press:.0f} psi" for en in engs)),
                                        ("FLUJO", f"{sum(en.fuel_flow for en in engs):.1f} L/h")]):
            plate(surf, f, lab, (ix, area.y + 40 + k * 70), 12)
            f.blit(surf, val, (ix, area.y + 66 + k * 70), 18, COL["green"], bold=True, mono=True, anchor="center")

    def _fuel(self, surf, area, world, ui):
        sysm = world.ac.sys
        f = self.f
        cx, cy = area.x + area.w * 0.28, area.y + area.h * 0.45
        pos = [("CERRADO", 180), ("IZQ", -90), ("AMBOS", 0), ("DER", 90)]
        order = [0, 1, 3, 2]                     # índice de la lista -> valor del selector
        idx = order.index(sysm.fuel_selector)
        idx, _ = self.rotary(surf, (cx, cy), 62, pos, idx, "selector_combustible", "SELECTOR DE COMBUSTIBLE", ui)
        sysm.fuel_selector = order[idx]
        if not sysm.twin:
            if self.switch(surf, (area.x + area.w * 0.58, cy - 10), sysm.fuel_pump, "BOMBA COMB.", ui,
                           tip="Bomba eléctrica de combustible"):
                sysm.fuel_pump = not sysm.fuel_pump
        cap = world.ac.t.fuel_capacity
        x0 = area.x + area.w * 0.74
        for i, lab in enumerate(("IZQ", "DER")):
            bar = pygame.Rect(x0 + i * 90, area.y + 40, 40, area.h - 120)
            pygame.draw.rect(surf, (10, 10, 11), bar, border_radius=6)
            lvl = clamp(sysm.fuel_l / 2 / (cap / 2), 0, 1)
            fill = pygame.Rect(bar.x + 4, bar.bottom - 4 - (bar.h - 8) * lvl, bar.w - 8, (bar.h - 8) * lvl)
            pygame.draw.rect(surf, (60, 180, 80) if lvl > 0.15 else (220, 60, 40), fill, border_radius=4)
            plate(surf, f, f"DEP. {lab}", (bar.centerx, bar.bottom + 20), 12)
            f.blit(surf, f"{sysm.fuel_l / 2:.0f} L", (bar.centerx, bar.y - 16), 14, COL["white"], bold=True, anchor="center")

    def _elec(self, surf, area, world, ui):
        sysm = world.ac.sys
        items = [("BAT", "master", "Batería (interruptor maestro)", (170, 30, 30)),
                 ("ALT", "alternator", "Alternador", (170, 30, 30)),
                 ("AVIÓNICA", "avionics", "Bus de aviónica", None),
                 ("CAL. PITOT", "pitot_heat", "Calefacción del pitot", None)]
        n = len(items)
        for i, (lab, attr, tip, guard) in enumerate(items):
            cx = area.x + 90 + i * (area.w - 180) / max(1, n - 1)
            if self.switch(surf, (cx, area.y + area.h * 0.40), getattr(sysm, attr), lab, ui, tip=tip, guard=guard):
                setattr(sysm, attr, not getattr(sysm, attr))
        f = self.f
        y = area.bottom - 34
        f.blit(surf, f"BUS {sysm.bus_volts:4.1f} V    AMPERÍMETRO {sysm.amps:+5.1f} A", (area.centerx, y), 18,
               COL["green"] if sysm.bus_volts > 25 else COL["amber"], bold=True, mono=True, anchor="center")

    def _lights(self, surf, area, world, ui):
        L = world.ac.sys.lights
        items = [("ANTICOLISIÓN", "beacon"), ("NAVEGACIÓN", "nav"), ("ESTROBOS", "strobe"),
                 ("RODAJE", "taxi"), ("ATERRIZAJE", "landing")]
        n = len(items)
        for i, (lab, k) in enumerate(items):
            cx = area.x + 90 + i * (area.w - 180) / (n - 1)
            if self.switch(surf, (cx, area.y + area.h * 0.42), L[k], lab, ui, tip="Luz " + lab.lower()):
                L[k] = not L[k]

    def _flaps(self, surf, area, world, ui):
        ac = world.ac
        sysm = ac.sys
        f = self.f
        st = ac.t.flap_settings
        slot = pygame.Rect(area.x + area.w * 0.18, area.y + 40, 18, area.h - 110)
        pygame.draw.rect(surf, (8, 8, 9), slot, border_radius=9)
        n = len(st)
        ys = [slot.y + 12 + i * (slot.h - 24) / max(1, n - 1) for i in range(n)]
        for i, (v, y) in enumerate(zip(st, ys)):
            r = plate(surf, f, f"{v}°" if v else "ARRIBA", (slot.x - 60, y), 13,
                      COL["yellow"] if sysm.flaps_cmd == i else (230, 230, 225))
            pygame.draw.line(surf, (200, 200, 200), (slot.x - 14, y), (slot.x - 2, y), 2)
            if ui.hit(r.inflate(20, 10)):
                sysm.flaps_cmd = i
        ky = ys[sysm.flaps_cmd]
        kw, kh = 70, 40
        kr = pygame.Rect(0, 0, kw, kh)
        kr.center = (slot.centerx, int(ky))
        img = sprite("palanca_flaps", (kw, kh))
        if img is not None:
            surf.blit(img, kr)
        else:
            pygame.draw.ellipse(surf, (0, 0, 0), kr.move(3, 4))
            pygame.draw.ellipse(surf, (235, 235, 230), kr)
            pygame.draw.ellipse(surf, (90, 90, 90), kr, 2)
        hit = pygame.Rect(slot.x - 40, slot.y, slot.w + 80, slot.h)
        if ui.clicked and hit.collidepoint(ui.clicked):
            self.drag = "flaps"
            ui.clicked = None
        if self.drag == "flaps":
            sysm.flaps_cmd = min(range(n), key=lambda i: abs(ys[i] - ui.mouse[1]))
        f.blit(surf, f"posición real {sysm.flaps:.0f}°", (slot.centerx, slot.bottom + 22), 14, COL["white"], anchor="center")
        plate(surf, f, "FLAPS", (slot.centerx, slot.y - 22), 13)
        # rueda del compensador (gira con la rueda del ratón o arrastrando)
        wr = pygame.Rect(area.x + area.w * 0.55, area.y + 40, 60, area.h - 110)
        pygame.draw.rect(surf, (8, 8, 9), wr.inflate(16, 16), border_radius=10)
        img = sprite("rueda_trim", wr.size)
        off = int(ac.trim * 120) % max(1, wr.h)
        if img is not None:
            surf.set_clip(wr)
            surf.blit(img, (wr.x, wr.y + off))
            surf.blit(img, (wr.x, wr.y + off - wr.h))
            surf.set_clip(None)
        else:
            pygame.draw.rect(surf, (30, 30, 32), wr, border_radius=8)
            surf.set_clip(wr)
            for k in range(-2, 30):
                y = wr.y + (k * 12 + off) % (wr.h + 24) - 12
                pygame.draw.line(surf, (70, 70, 74), (wr.x + 6, y), (wr.right - 6, y), 4)
            surf.set_clip(None)
            shade = pygame.Surface(wr.size, pygame.SRCALPHA)
            for yy in range(wr.h):
                a = int(150 * abs(yy / wr.h - 0.5) * 2)
                pygame.draw.line(shade, (0, 0, 0, a), (0, yy), (wr.w, yy))
            surf.blit(shade, wr)
        # indicador de posición
        ind = pygame.Rect(wr.right + 40, wr.y, 14, wr.h)
        pygame.draw.rect(surf, (10, 10, 11), ind, border_radius=4)
        ty = ind.centery - ac.trim * (ind.h / 2 - 6)
        pygame.draw.polygon(surf, COL["white"], [(ind.right + 2, ty), (ind.right + 16, ty - 8), (ind.right + 16, ty + 8)])
        f.blit(surf, "NARIZ ABAJO", (ind.right + 22, ind.y), 11, COL["grey"], anchor="topleft")
        f.blit(surf, "DESPEGUE", (ind.right + 22, ind.centery), 11, COL["grey"], anchor="midleft")
        f.blit(surf, "NARIZ ARRIBA", (ind.right + 22, ind.bottom), 11, COL["grey"], anchor="bottomleft")
        plate(surf, f, "COMPENSADOR", (wr.centerx, wr.y - 22), 13)
        if ui.clicked and wr.collidepoint(ui.clicked):
            self.drag = ("trim", ui.mouse[1], ac.trim)
            ui.clicked = None
        if isinstance(self.drag, tuple) and self.drag[0] == "trim":
            ac.trim = clamp(self.drag[2] - (ui.mouse[1] - self.drag[1]) / 200.0, -1, 1)
        d = ui.scroll(wr.inflate(40, 20))
        if d:
            ac.trim = clamp(ac.trim - d * 0.04, -1, 1)
        if ui.hover(wr):
            ui.tooltip = "Rueda del compensador: arrastre o use la rueda del ratón"

    def _emergency(self, surf, area, world, ui):
        """Mandos de emergencia: puerta, tren de emergencia, compensador, extintor y transpondedor."""
        f = self.f
        em = world.emerg
        sysm = world.ac.sys
        items = [("CERRAR PUERTA", em.close_door, "Solo por debajo de 80 kt", True),
                 ("EXTENSIÓN EMERGENCIA TREN", em.gear_emergency, "Baja el tren por gravedad", world.ac.t.retractable),
                 ("CORTACIRCUITO COMPENSADOR", em.trim_disconnect, "Desconecta el compensador eléctrico", True),
                 ("EXTINTOR", em.extinguisher, "Descarga el extintor de mano (humo en cabina)", True),
                 ("PARACAÍDAS CAPS", em.deploy_caps, "Tirar de la manija roja del techo (Cirrus)", world.ac.t.id == "sr20")]
        items = [i for i in items if i[3]]
        bw, bh = 300, 70
        for i, (lab, fn, tip, _) in enumerate(items):
            r = pygame.Rect(area.x + 40 + (i % 2) * (bw + 30), area.y + 30 + (i // 2) * (bh + 26), bw, bh)
            active = ((lab.startswith("CORTA") and not sysm.trim_cb) or (lab.startswith("EXTENSIÓN") and sysm.gear_emergency)
                      or (lab == "EXTINTOR" and sysm.extinguisher <= 0))
            pygame.draw.rect(surf, (0, 0, 0), r.move(3, 4), border_radius=10)
            pygame.draw.rect(surf, (150, 30, 26) if not active else (60, 60, 64), r, border_radius=10)
            pygame.draw.rect(surf, (250, 210, 40), r, 3, border_radius=10)
            f.blit(surf, lab, r.center, 15, COL["white"], bold=True, anchor="center")
            if ui.hover(r):
                ui.tooltip = tip
            if ui.hit(r):
                self.msg = fn()
        # transpondedor de emergencia
        x = area.x + 40 + 2 * (bw + 30) + 20
        plate(surf, f, "TRANSPONDEDOR", (x + 110, area.y + 40), 13)
        f.blit(surf, f"{world.xpdr:04d}", (x + 110, area.y + 80), 30, (90, 240, 140), bold=True, mono=True, anchor="center")
        for i, (code, lab) in enumerate(((7700, "7700 EMERGENCIA"), (7600, "7600 SIN RADIO"), (1200, "1200 VFR"))):
            r = pygame.Rect(x, area.y + 110 + i * 46, 220, 38)
            if ui.button(surf, r, lab, active=world.xpdr == code, size=13):
                world.xpdr = code
        if getattr(self, "msg", None):
            f.blit(surf, self.msg, (area.x + 40, area.bottom - 30), 16, COL["amber"], bold=True)

    def _gear(self, surf, area, world, ui):
        ac = world.ac
        sysm = ac.sys
        f = self.f
        if ac.t.retractable:
            slot = pygame.Rect(area.x + area.w * 0.22, area.y + 40, 18, area.h - 120)
            pygame.draw.rect(surf, (8, 8, 9), slot, border_radius=9)
            ky = slot.y + 14 if not sysm.gear_down else slot.bottom - 14
            kr = pygame.Rect(0, 0, 64, 64)
            kr.center = (slot.centerx, ky)
            img = sprite("palanca_tren", kr.size)
            if img is not None:
                surf.blit(img, kr)
            else:
                pygame.draw.circle(surf, (0, 0, 0), (kr.centerx + 3, kr.centery + 4), 30)
                pygame.draw.circle(surf, (235, 235, 230), kr.center, 30)
                pygame.draw.circle(surf, (40, 40, 40), kr.center, 30, 6)
                pygame.draw.circle(surf, (120, 120, 120), kr.center, 9)
            plate(surf, f, "ARRIBA", (slot.x - 56, slot.y + 14), 12)
            plate(surf, f, "ABAJO", (slot.x - 56, slot.bottom - 14), 12)
            plate(surf, f, "TREN", (slot.centerx, slot.y - 22), 13)
            if ui.hit(pygame.Rect(slot.x - 40, slot.y, slot.w + 80, slot.h)):
                sysm.gear_down = not sysm.gear_down
            for i in range(3):
                c = (40, 220, 80) if sysm.gear_pos > 0.99 else ((230, 60, 50) if 0.01 < sysm.gear_pos < 0.99 else (40, 40, 40))
                pygame.draw.circle(surf, c, (int(slot.right + 60 + i * 34), int(area.y + area.h * 0.45)), 13)
                pygame.draw.circle(surf, (15, 15, 15), (int(slot.right + 60 + i * 34), int(area.y + area.h * 0.45)), 13, 2)
        # freno de estacionamiento (tirador)
        cx = area.x + area.w * 0.68
        base = area.y + 60
        pull = 60 if sysm.parking_brake else 0
        pygame.draw.rect(surf, (150, 150, 155), (cx - 5, base, 10, 20 + pull))
        hr = pygame.Rect(0, 0, 120, 44)
        hr.center = (cx, base + 40 + pull)
        img = sprite("freno_mano", hr.size)
        if img is not None:
            surf.blit(img, hr)
        else:
            pygame.draw.rect(surf, (0, 0, 0), hr.move(3, 4), border_radius=10)
            pygame.draw.rect(surf, (190, 40, 30), hr, border_radius=10)
            pygame.draw.rect(surf, (60, 10, 10), hr, 2, border_radius=10)
        plate(surf, f, "FRENO DE ESTACIONAMIENTO", (cx, base - 22), 13)
        f.blit(surf, "PUESTO" if sysm.parking_brake else "QUITADO", (cx, base + 150), 16,
               COL["amber"] if sysm.parking_brake else COL["green"], bold=True, anchor="center")
        if ui.hit(hr.inflate(20, 20)):
            sysm.parking_brake = not sysm.parking_brake
        if ui.hover(hr):
            ui.tooltip = "Clic: tirar / soltar el freno de estacionamiento"
