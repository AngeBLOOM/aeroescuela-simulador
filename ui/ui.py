"""Utilidades de interfaz: fuentes con caché, textos y controles clicables (modo inmediato)."""
import math
import os

import pygame

COL = dict(
    bg=(14, 18, 26),
    panel=(36, 39, 44),
    panel_hi=(52, 56, 62),
    face=(12, 12, 14),
    white=(236, 236, 232),
    grey=(150, 156, 164),
    dim=(96, 102, 110),
    cyan=(40, 210, 255),
    magenta=(236, 60, 236),
    green=(70, 220, 100),
    yellow=(250, 210, 50),
    amber=(255, 170, 30),
    red=(235, 50, 45),
    sky=(40, 120, 220),
    ground=(132, 84, 36),
    accent=(0, 210, 255),
    button=(46, 52, 62),
    button_hi=(64, 74, 90),
    button_on=(34, 120, 70),
)


class Fonts:
    def __init__(self, scale=1.0):
        pygame.font.init()
        self.scale = scale
        self._cache = {}
        self._text = {}
        avail = set(pygame.font.get_fonts())
        self.face_main = next((f for f in ("bahnschrift", "segoeui", "arial", "dejavusans") if f in avail), None)
        self.face_mono = next((f for f in ("consolas", "cascadiamono", "couriernew", "dejavusansmono") if f in avail), None)
        self.face_sym = next((f for f in ("segoeuisymbol", "seguisym", "dejavusans", "arial") if f in avail), None)
        # tipografía técnica para títulos, rótulos y datos: Orbitron (assets/fuentes, licencia OFL) o, si falta, OCR-A
        from .assets import BASE
        p = os.path.join(BASE, "fuentes", "Orbitron.ttf")
        self.tech_path = p if os.path.exists(p) else None
        self.face_tech = next((f for f in ("orbitron", "ocra", "consolas") if f in avail), None)

    def get(self, size, bold=False, mono=False, sym=False, tech=False):
        size = max(8, int(size * self.scale))
        key = (size, bold, mono, sym, tech)
        f = self._cache.get(key)
        if f is None and tech and self.tech_path:
            f = pygame.font.Font(self.tech_path, size)
            f.bold = bold
            self._cache[key] = f
            return f
        if f is None:
            name = self.face_tech if tech else (self.face_sym if sym else (self.face_mono if mono else self.face_main))
            f = pygame.font.SysFont(name, size, bold=bold) if name else pygame.font.Font(None, size)
            self._cache[key] = f
        return f

    def render(self, text, size, color, bold=False, mono=False, tech=False):
        key = (text, size, color, bold, mono, tech)
        s = self._text.get(key)
        if s is None:
            if len(self._text) > 3000:
                self._text.clear()
            font = self.get(size, bold, mono, tech=tech)
            if tech:
                text = self._tech_safe(font, text)
            if any(ord(ch) > 0x2000 for ch in text) and self.face_sym:
                font = self.get(size, bold, False, sym=True)
            s = font.render(text, True, color)
            self._text[key] = s
        return s

    def _tech_safe(self, font, text):
        """La tipografía técnica (OCR-A) no trae tildes ni algunos símbolos: se sustituyen por equivalentes."""
        import unicodedata
        missing = font.metrics("\ue000")[0]
        out = []
        for ch in text:
            m = font.metrics(ch)[0]
            if m != missing or ch == " ":
                out.append(ch)
                continue
            rep = {"°": "'", "º": "'", "·": "-", "•": "-", "›": ">", "‹": "<", "—": "-", "–": "-", "→": ">",
                   "←": "<"}.get(ch)
            if rep is None:
                base = unicodedata.normalize("NFD", ch)[0]
                rep = base if font.metrics(base)[0] != missing else "?"
            out.append(rep)
        return "".join(out)

    def blit(self, surf, text, pos, size=16, color=COL["white"], bold=False, mono=False, anchor="topleft", tech=False):
        img = self.render(str(text), size, color, bold, mono, tech)
        r = img.get_rect(**{anchor: (int(pos[0]), int(pos[1]))})
        surf.blit(img, r)
        return r

    def wrap(self, text, size, width, bold=False):
        f = self.get(size, bold)
        lines = []
        for para in str(text).split("\n"):
            words = para.split(" ")
            cur = ""
            for w in words:
                t = (cur + " " + w).strip()
                if f.size(t)[0] <= width:
                    cur = t
                else:
                    if cur:
                        lines.append(cur)
                    cur = w
            lines.append(cur)
        return lines


class UI:
    """Controles de modo inmediato: cada fotograma se declaran y se consulta el clic."""

    def __init__(self, fonts):
        self.f = fonts
        self.mouse = (0, 0)
        self.clicked = None
        self.right_clicked = None
        self.wheel = 0
        self.wheel_pos = None
        self.down = False
        self.consumed = False
        self.tooltip = None
        self.hot = []
        self.on_click = None              # sonido de clic (lo pone la aplicación)

    def begin(self, events):
        self.clicked = None
        self.right_clicked = None
        self.wheel = 0
        self.consumed = False
        self.tooltip = None
        self.hot = []
        self.mouse = pygame.mouse.get_pos()
        for e in events:
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                self.clicked = e.pos
            elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 3:
                self.right_clicked = e.pos
            elif e.type == pygame.MOUSEWHEEL:
                self.wheel += e.y
                self.wheel_pos = self.mouse

    def hit(self, rect, right=False):
        p = self.right_clicked if right else self.clicked
        if p and pygame.Rect(rect).collidepoint(p):
            if right:
                self.right_clicked = None
            else:
                self.clicked = None
            self.consumed = True
            return True
        return False

    def hover(self, rect):
        return pygame.Rect(rect).collidepoint(self.mouse)

    def scroll(self, rect):
        if self.wheel and pygame.Rect(rect).collidepoint(self.mouse):
            w = self.wheel
            self.wheel = 0
            self.consumed = True
            return w
        return 0

    def button(self, surf, rect, label, active=False, size=15, color=None, enabled=True, tip=None, style="normal"):
        """Botón de la interfaz (estilo futurista: biselado, neón al pasar el ratón)."""
        from . import theme
        rect = pygame.Rect(rect)
        hov = self.hover(rect) and enabled
        if style != "flat":
            theme.button(surf, self.f, rect, label, hov, active, color, enabled, size)
            if hov and tip:
                self.tooltip = tip
            hit = enabled and self.hit(rect)
            if hit and self.on_click:
                self.on_click()
            return hit
        return self.cockpit_button(surf, rect, label, active, size, color, enabled, tip, style)

    def cockpit_button(self, surf, rect, label, active=False, size=15, color=None, enabled=True, tip=None, style="normal"):
        """Botón de cabina (tableros de instrumentos): conserva el aspecto realista."""
        rect = pygame.Rect(rect)
        hov = self.hover(rect) and enabled
        if style == "flat":
            base = (0, 0, 0, 0)
        else:
            base = COL["button_on"] if active else (COL["button_hi"] if hov else COL["button"])
        if color is not None and not active:
            base = color
        if not enabled:
            base = (36, 38, 42)
        pygame.draw.rect(surf, base, rect, border_radius=6)
        pygame.draw.rect(surf, (90, 100, 115) if hov else (64, 70, 80), rect, 1, border_radius=6)
        tc = COL["white"] if enabled else COL["dim"]
        self.f.blit(surf, label, rect.center, size, tc, bold=True, anchor="center")
        if hov and tip:
            self.tooltip = tip
        return enabled and self.hit(rect)

    def toggle(self, surf, rect, label, value, size=12, tip=None):
        rect = pygame.Rect(rect)
        hov = self.hover(rect)
        pygame.draw.rect(surf, (30, 32, 36), rect, border_radius=4)
        pygame.draw.rect(surf, (80, 86, 96) if hov else (58, 62, 70), rect, 1, border_radius=4)
        # interruptor basculante
        sw = pygame.Rect(0, 0, rect.w * 0.34, rect.h * 0.46)
        sw.midtop = (rect.centerx, rect.y + 4)
        pygame.draw.rect(surf, (18, 18, 20), sw, border_radius=3)
        knob = pygame.Rect(sw.x + 2, sw.y + 2, sw.w - 4, sw.h / 2 - 2)
        if not value:
            knob.y = sw.centery
        pygame.draw.rect(surf, COL["green"] if value else (170, 170, 170), knob, border_radius=2)
        self.f.blit(surf, label, (rect.centerx, rect.bottom - 3), size, COL["white"], anchor="midbottom")
        if hov and tip:
            self.tooltip = tip
        return self.hit(rect)

    def slider(self, surf, rect, value, lo, hi, label="", fmt="{:.0f}", size=14):
        from . import theme
        rect = pygame.Rect(rect)
        pygame.draw.polygon(surf, (6, 22, 34, 210), theme.chamfer(rect, 6))
        t = (value - lo) / (hi - lo) if hi > lo else 0
        fill = rect.copy()
        fill.w = int(rect.w * max(0.0, min(1.0, t)))
        if fill.w > 4:
            pygame.draw.polygon(surf, (0, 150, 200, 230), theme.chamfer(fill, 6, "t"))
            pygame.draw.line(surf, theme.CYAN, (fill.right - 2, rect.y + 2), (fill.right - 2, rect.bottom - 3), 3)
        pygame.draw.polygon(surf, (*theme.CYAN, 130), theme.chamfer(rect, 6), 1)
        self.f.blit(surf, f"{label} {fmt.format(value)}".strip(), rect.center, size, COL["white"], anchor="center")
        if pygame.mouse.get_pressed()[0] and rect.collidepoint(self.mouse):
            tt = (self.mouse[0] - rect.x) / rect.w
            self.consumed = True
            return lo + (hi - lo) * max(0.0, min(1.0, tt))
        return None

    def draw_tooltip(self, surf):
        if not self.tooltip:
            return
        from . import theme
        img = self.f.render(self.tooltip, 14, theme.TEXT)
        r = img.get_rect()
        r.inflate_ip(20, 10)
        r.topleft = (self.mouse[0] + 16, self.mouse[1] + 18)
        if r.right > surf.get_width():
            r.right = self.mouse[0] - 6
        if r.bottom > surf.get_height():
            r.bottom = self.mouse[1] - 6
        pts = theme.chamfer(r, 6)
        pygame.draw.polygon(surf, (4, 16, 26, 240), pts)
        pygame.draw.polygon(surf, (*theme.CYAN, 200), pts, 1)
        pygame.draw.line(surf, theme.CYAN, (r.x, r.y + 6), (r.x, r.bottom - 7), 3)
        surf.blit(img, (r.x + 10, r.y + 5))


def polar(c, r, deg):
    """Punto a distancia r del centro c; deg en grados en sentido horario desde arriba."""
    a = math.radians(deg)
    return (c[0] + r * math.sin(a), c[1] - r * math.cos(a))


def panel_box(surf, rect, radius=10, color=None, border=(70, 76, 86)):
    """Panel de la interfaz: cristal oscuro con esquinas recortadas y filetes de neón (ui/theme.py)."""
    from . import theme
    fill = color or (6, 18, 30, 232)
    if len(fill) == 4 and max(fill[:3]) < 45:
        fill = (*fill[:3], max(fill[3], 228))         # paneles oscuros: casi opacos para leerse sobre la foto
    # los bordes grises por defecto pasan a cian; un borde de color propio se respeta
    acc = None if (not border or border == (70, 76, 86)) else border
    theme.holo_panel(surf, rect, fill, bool(border), accent=acc, cut=max(8, min(16, radius + 2)))
