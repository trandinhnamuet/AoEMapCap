"""HUD của trình xem replay, vẽ bằng pygame lên một Surface trong suốt cỡ cửa sổ (đưa lên GPU thành 1 texture).

Bố cục theo replay LMHT: đồng hồ + tỉ số đội ở giữa trên, thanh thời gian dưới cùng (U), bảng tỉ số giữa dưới (O,
X đổi cột), minimap góc phải dưới, bảng công nghệ người chơi đang chọn bên phải (C), trợ giúp (?).
"""
import os

import pygame

from mapcap import offsets as O

AGE_VI = {0: "Du mục", 1: "Đời 1", 2: "Đời 2", 3: "Đời 3", 4: "Đời 4"}

from .keys import KEYS_HELP  # noqa: E402
GOLD = (255, 214, 120)
WHITE = (240, 240, 240)
GREY = (170, 170, 170)
PANEL = (8, 10, 14, 200)


def _font_path(bold=False):
    d = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for name in (("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


def fmt_ms(ms):
    s = max(0, int(ms) // 1000)
    return f"{s // 3600}:{(s // 60) % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def pil_to_surface(im):
    if im is None:
        return None
    im = im.convert("RGBA")
    return pygame.image.frombytes(im.tobytes(), im.size, "RGBA")


class Hud:
    KEYS_HELP = KEYS_HELP

    def __init__(self):
        self.show_hud = True
        self.show_score = True
        self.score_mode = 0          # 0 kinh tế, 1 quân sự
        self.show_timeline = True
        self.show_techs = False
        self.show_help = False
        self.show_minimap = True
        self.size = (0, 0)
        self._fonts = {}
        self._text_cache = {}
        self.icons = {}              # attr -> Surface (tài nguyên)
        self.tech_icon = None        # hàm (icon_id, size) -> Surface hoặc None
        self.slp_icon = None         # hàm (slp id interfac.drs, khung) -> Surface hoặc None
        self.bar_art = None          # hàm (bộ giao diện 0..4) -> Surface 1920 x 126 thanh dưới của game
        self._bar_cache = {}
        # vùng bấm (cập nhật mỗi lần vẽ)
        self.r_timeline = None
        self.r_play = None
        self.r_help = None           # nút "Phím tắt (Esc)" trên thanh thời gian
        self.r_settings = None       # nút ⚙ Cài đặt trên thanh thời gian (người dùng 12/11)
        self.show_settings = False
        self.r_settings_panel = None
        self.settings_hits = []      # [(Rect, hành động)] các nút trong bảng Cài đặt
        self.hover_pos = None        # vị trí chuột (tô sáng nút trong bảng Cài đặt)
        self.r_minimap = None
        self.score_rows = []         # [(Rect, index người chơi)]
        self.hover_timeline = None   # tỉ lệ 0..1 khi chuột trên thanh thời gian
        self.cmd_hits = []           # [(Rect, chữ gợi ý)] các nút bảng lệnh công trình vừa vẽ
        self.hover_cmd = None        # chỉ số nút đang rê chuột
        self.persp_hits = []         # (Rect, khoá) các thẻ góc nhìn góc phải trên

    # ---- chữ --------------------------------------------------------------------------
    def font(self, size, bold=False):
        key = (size, bold)
        f = self._fonts.get(key)
        if f is None:
            p = _font_path(bold)
            f = pygame.font.Font(p, size) if p else pygame.font.Font(None, size)
            self._fonts[key] = f
        return f

    def text(self, s, size, color=WHITE, bold=False, shadow=True):
        key = (s, size, color, bold, shadow)
        surf = self._text_cache.get(key)
        if surf is None:
            if len(self._text_cache) > 3000:
                self._text_cache.clear()
            f = self.font(size, bold)
            t = f.render(s, True, color)
            if shadow:
                sh = f.render(s, True, (0, 0, 0))
                surf = pygame.Surface((t.get_width() + 1, t.get_height() + 1), pygame.SRCALPHA)
                surf.blit(sh, (1, 1))
                surf.blit(t, (0, 0))
            else:
                surf = t
            self._text_cache[key] = surf
        return surf

    @staticmethod
    def panel(dst, rect, color=PANEL, border=None, radius=6):
        r = pygame.Rect(rect)
        s = pygame.Surface(r.size, pygame.SRCALPHA)
        pygame.draw.rect(s, color, s.get_rect(), border_radius=radius)
        if border:
            pygame.draw.rect(s, border, s.get_rect(), 1, border_radius=radius)
        dst.blit(s, r.topleft)

    # ---- bố cục -------------------------------------------------------------------------
    def layout(self, size, world_aspect):
        W, H = size
        self.size = size
        self.u = max(0.6, H / 1080)
        u = self.u
        self.tl_h = int(46 * u)
        mm_w = int(min(W * 0.2, 380 * u))
        # trong thanh dưới có ảnh của game: minimap nằm đúng ô hình thoi của ảnh (219 x 109 trên ảnh 1920 x 126)
        mm_w = int(W * 219 / 1920)          # (trong thanh dưới chung: thấp hơn cho thấy nhiều bản đồ)
        mm_h = int(mm_w * world_aspect)
        bottom = H - (self.tl_h + int(8 * u) if self.show_timeline and self.show_hud else int(8 * u))
        self.r_minimap = pygame.Rect(W - mm_w - int(10 * u), bottom - mm_h - int(6 * u), mm_w, mm_h)
        self.bottom = bottom

    def minimap_rect(self):
        return self.r_minimap if (self.show_hud and self.show_minimap) else None

    # ---- vẽ ---------------------------------------------------------------------------
    def render(self, m):
        """m: model (SimpleNamespace) từ viewer. Trả về Surface RGBA cỡ cửa sổ."""
        W, H = self.size
        surf = pygame.Surface((W, H), pygame.SRCALPHA)
        self.score_rows = []
        self.r_timeline = self.r_play = self.r_help = self.r_persp = self.r_settings = None
        self.r_settings_panel = None
        self.persp_hits = []
        self.settings_hits = []
        if m.loading is not None:
            self._loading(surf, m)
            return surf
        if self.show_hud:
            self._top(surf, m)
            self._bottom_bar(surf, m)
            if self.show_timeline:
                self._timeline(surf, m)
            if getattr(m, "persp_card", None):
                self._persp_card(surf, m.persp_card)
            if self.show_techs:
                self._techs(surf, m)
            if self.show_settings and self.show_timeline and getattr(m, "settings", None):
                self._settings(surf, m.settings)
        if m.toast:
            t = self.text(m.toast, int(22 * self.u), GOLD, bold=True)
            y = int(96 * self.u) if self.show_hud else int(20 * self.u)
            r = pygame.Rect(0, 0, t.get_width() + int(28 * self.u), t.get_height() + int(10 * self.u))
            r.midtop = (W // 2, y)
            self.panel(surf, r)
            surf.blit(t, t.get_rect(center=r.center))
        if self.show_help:
            self._help(surf)
        return surf

    def _persp_card(self, surf, card):
        """Góc phải trên: mỗi người chơi một thẻ nhỏ (người dùng 12/11), thẻ sáng viền vàng = đang xem tầm nhìn người
        đó; bấm thẻ để xem tầm nhìn người đó (bấm lại: cả đội), thẻ Toàn bản đồ = F3."""
        W, _H = self.size
        u = self.u
        pad = int(8 * u)
        title = self.text(card["title"], int(14 * u), GOLD, bold=True)
        sub = self.text(card["sub"], int(12 * u), GREY) if card.get("sub") else None
        rows = []
        for cd in card["cards"]:
            name = self.text(cd["name"], int(15 * u), cd["rgb"] if cd["active"] or cd["key"][0] == "all" else
                             tuple(int(v * 0.75) for v in cd["rgb"]), bold=cd["active"])
            civ = self.text(cd["civ"], int(12 * u), GREY) if cd["civ"] else None
            rows.append((cd, name, civ))
        ch = max(int(26 * u), max(nm.get_height() for _c, nm, _v in rows) + int(6 * u))
        cw = max(nm.get_width() + (cv.get_width() + int(10 * u) if cv else 0) for _c, nm, cv in rows) + int(26 * u)
        cw = max(cw, title.get_width(), sub.get_width() if sub else 0, int(150 * u))
        gap, tgap = int(4 * u), int(7 * u)
        h = pad + title.get_height() + (sub.get_height() if sub else 0) + int(6 * u)
        prev_team = None
        for cd, _n, _c in rows:
            h += ch + (tgap if prev_team is not None and cd["team"] != prev_team else gap)
            prev_team = cd["team"]
        h += pad - gap
        r = pygame.Rect(W - cw - 2 * pad - int(8 * u), int(6 * u), cw + 2 * pad, h)
        self.panel(surf, r, border=(120, 110, 80))
        y = r.y + pad
        surf.blit(title, (r.x + pad, y))
        y += title.get_height()
        if sub:
            surf.blit(sub, (r.x + pad, y))
            y += sub.get_height()
        y += int(6 * u)
        prev_team = None
        self.persp_hits = []
        for cd, name, civ in rows:
            if prev_team is not None and cd["team"] != prev_team:
                y += tgap - gap
            prev_team = cd["team"]
            cr = pygame.Rect(r.x + pad, y, cw, ch)
            if cd["active"]:
                self.panel(surf, cr, (70, 58, 26, 240), border=GOLD, radius=5)
            else:
                self.panel(surf, cr, (22, 22, 26, 225), border=(70, 66, 56), radius=5)
            if cd["key"][0] == "pl":
                pygame.draw.rect(surf, cd["rgb"], pygame.Rect(cr.x + int(5 * u), cr.y + int(5 * u), int(5 * u),
                                                              cr.h - int(10 * u)), border_radius=2)
            surf.blit(name, name.get_rect(midleft=(cr.x + int(16 * u), cr.centery)))
            if civ:
                surf.blit(civ, civ.get_rect(midright=(cr.right - int(8 * u), cr.centery)))
            self.persp_hits.append((cr, cd["key"]))
            y += ch + gap
        self.r_persp = r

    def _loading(self, surf, m):
        W, H = self.size
        u = self.u
        lines = m.loading
        w = int(620 * u)
        h = int((40 + 52 * len(lines)) * u)
        r = pygame.Rect(0, 0, w, h)
        r.center = (W // 2, H // 2)
        self.panel(surf, r, border=(120, 110, 80))
        y = r.y + int(20 * u)
        for label, frac in lines:
            surf.blit(self.text(label, int(20 * u)), (r.x + int(24 * u), y))
            y += int(28 * u)
            bar = pygame.Rect(r.x + int(24 * u), y, w - int(48 * u), int(8 * u))
            pygame.draw.rect(surf, (60, 60, 60), bar, border_radius=4)
            if frac is not None:
                b2 = bar.copy()
                b2.width = int(bar.width * max(0.0, min(1.0, frac)))
                pygame.draw.rect(surf, GOLD, b2, border_radius=4)
            y += int(24 * u)

    def _top(self, surf, m):
        W, _H = self.size
        u = self.u
        clock = self.text(fmt_ms(m.time_ms), int(30 * u), WHITE, bold=True)
        sub = f"{m.speed_label}   ·   {m.persp_label}" + ("   ·   TẠM DỪNG" if m.paused else "") + \
            ("   ·   HẾT TRẬN" if getattr(m, "game_over", False) else "")
        st = self.text(sub, int(15 * u), GOLD if m.paused else GREY)
        sides = []
        if len(m.teams) == 2:
            for k, team in enumerate(m.teams):
                kills = sum(int(p["kills"] or 0) for p in team)
                pop = sum(int(p["pop"] or 0) for p in team)
                sides.append(self.text(f"Đội {k + 1}   Kill {kills}   Dân số {pop}", int(17 * u), team[0]["rgb"] if team else WHITE, bold=True))
        inner = max(clock.get_width(), st.get_width())
        side_w = max([s.get_width() for s in sides] + [0])
        w = inner + 2 * side_w + int(80 * u)
        h = int(62 * u)
        r = pygame.Rect(0, int(6 * u), w, h)
        r.centerx = W // 2
        self.panel(surf, r, border=(120, 110, 80))
        surf.blit(clock, clock.get_rect(midtop=(r.centerx, r.y + int(2 * u))))
        surf.blit(st, st.get_rect(midbottom=(r.centerx, r.bottom - int(4 * u))))
        if len(sides) == 2:
            surf.blit(sides[0], sides[0].get_rect(midleft=(r.x + int(16 * u), r.centery)))
            surf.blit(sides[1], sides[1].get_rect(midright=(r.right - int(16 * u), r.centery)))

    def _timeline(self, surf, m):
        W, H = self.size
        u = self.u
        r = pygame.Rect(int(10 * u), H - self.tl_h - int(6 * u), W - int(20 * u), self.tl_h)
        self.panel(surf, r, border=(120, 110, 80))
        # nút phát
        pb = pygame.Rect(r.x + int(8 * u), r.y + int(7 * u), r.h - int(14 * u), r.h - int(14 * u))
        self.r_play = pb
        c = pb.center
        s = pb.h // 2 - int(3 * u)
        if m.paused:
            pygame.draw.polygon(surf, WHITE, [(c[0] - s // 2, c[1] - s), (c[0] - s // 2, c[1] + s), (c[0] + s, c[1])])
        else:
            pygame.draw.rect(surf, WHITE, (c[0] - s + 1, c[1] - s, int(s * 0.7), 2 * s))
            pygame.draw.rect(surf, WHITE, (c[0] + int(s * 0.3), c[1] - s, int(s * 0.7), 2 * s))
        x = pb.right + int(10 * u)
        t1 = self.text(m.speed_label, int(16 * u), GOLD, bold=True)
        surf.blit(t1, t1.get_rect(midleft=(x, r.centery)))
        x += max(t1.get_width(), int(48 * u)) + int(8 * u)
        t2 = self.text(f"{fmt_ms(m.time_ms)} / {fmt_ms(m.total_ms)}", int(16 * u))
        surf.blit(t2, t2.get_rect(midleft=(x, r.centery)))
        x += t2.get_width() + int(16 * u)
        th = self.text("Phím tắt (Esc)", int(15 * u), GOLD)
        hb = pygame.Rect(0, 0, th.get_width() + int(18 * u), r.h - int(14 * u))
        hb.midright = (r.right - int(8 * u), r.centery)
        pygame.draw.rect(surf, (60, 55, 40), hb, border_radius=5)
        pygame.draw.rect(surf, (120, 110, 80), hb, 1, border_radius=5)
        surf.blit(th, th.get_rect(center=hb.center))
        self.r_help = hb
        # nút ⚙ Cài đặt (bánh răng vẽ tay: phông chữ không chắc có ký tự ⚙)
        tg = self.text("Cài đặt", int(15 * u), GOLD)
        gs = hb.h
        gb = pygame.Rect(0, 0, gs + tg.get_width() + int(8 * u), hb.h)
        gb.midright = (hb.x - int(8 * u), r.centery)
        on = self.show_settings
        pygame.draw.rect(surf, (110, 88, 40) if on else (60, 55, 40), gb, border_radius=5)
        pygame.draw.rect(surf, GOLD if on else (120, 110, 80), gb, 1, border_radius=5)
        self._gear(surf, (gb.x + gs // 2 + int(2 * u), gb.centery), int(gs * 0.30), GOLD)
        surf.blit(tg, tg.get_rect(midleft=(gb.x + gs + int(1 * u), gb.centery)))
        self.r_settings = gb
        bar = pygame.Rect(x, r.centery - int(4 * u), gb.x - x - int(16 * u), int(8 * u))
        self.r_timeline = bar.inflate(0, int(24 * u))
        pygame.draw.rect(surf, (50, 50, 50), bar, border_radius=4)
        if m.indexed < 1.0:
            b = bar.copy(); b.width = int(bar.width * m.indexed)
            pygame.draw.rect(surf, (90, 90, 90), b, border_radius=4)
        else:
            pygame.draw.rect(surf, (90, 90, 90), bar, border_radius=4)
        frac = m.r / m.duration if m.duration > 0 else 0.0
        b = bar.copy(); b.width = int(bar.width * frac)
        pygame.draw.rect(surf, GOLD, b, border_radius=4)
        for (er, rgb, age) in m.events:
            if m.duration > 0:
                ex = bar.x + int(bar.width * er / m.duration)
                pygame.draw.line(surf, rgb, (ex, bar.y - int(6 * u)), (ex, bar.bottom + int(6 * u)), max(1, int(2 * u)))
        pygame.draw.circle(surf, WHITE, (bar.x + int(bar.width * frac), bar.centery), int(7 * u))
        if self.hover_timeline is not None and m.hover_ms is not None:
            hx = bar.x + int(bar.width * self.hover_timeline)
            tt = self.text(fmt_ms(m.hover_ms), int(15 * u), WHITE, bold=True)
            rr = pygame.Rect(0, 0, tt.get_width() + int(12 * u), tt.get_height() + int(6 * u))
            rr.midbottom = (hx, r.y - int(4 * u))
            rr.clamp_ip(pygame.Rect(0, 0, W, H))
            self.panel(surf, rr)
            surf.blit(tt, tt.get_rect(center=rr.center))

    @staticmethod
    def _gear(surf, c, rad, color):
        """Biểu tượng bánh răng: 8 răng + vành + lỗ giữa."""
        import math
        cx, cy = c
        tw = max(2, int(rad * 0.42))
        for k in range(8):
            a = k * math.pi / 4
            x, y = cx + math.cos(a) * rad * 1.05, cy + math.sin(a) * rad * 1.05
            pygame.draw.circle(surf, color, (int(x), int(y)), tw // 2 + 1)
        pygame.draw.circle(surf, color, (cx, cy), int(rad * 0.88))
        pygame.draw.circle(surf, (60, 55, 40), (cx, cy), max(2, int(rad * 0.38)))

    def _settings(self, surf, rows):
        """Bảng Cài đặt replay (nút ⚙ trên thanh thời gian, người dùng 12/11): mỗi hàng một nhãn + các nút chọn; nút
        đang bật viền vàng. Đặt sát trên nút ⚙, căn phải; hàng dài thì xuống dòng."""
        W, H = self.size
        u = self.u
        pad, gap, ch = int(14 * u), int(6 * u), int(30 * u)
        fs = int(15 * u)
        labels = [self.text(row["label"], fs, GREY) for row in rows]
        lw = max(t.get_width() for t in labels) + int(16 * u)
        maxw = min(W - int(40 * u), int(760 * u))
        title = self.text("Cài đặt replay", int(18 * u), WHITE, bold=True)
        # đo trước: vị trí từng nút (xuống dòng khi vượt maxw)
        lay, y, need_w = [], title.get_height() + int(12 * u), 0
        for row, lab in zip(rows, labels):
            x0 = lw
            x, items = x0, []
            for it in row["items"]:
                t = self.text(it["text"], fs, GOLD if it.get("active") else WHITE, bold=bool(it.get("active")))
                w = t.get_width() + int(20 * u)
                if x > x0 and x + w > maxw - 2 * pad:
                    x, y = x0, y + ch + gap
                items.append((pygame.Rect(x, y, w, ch), t, it))
                x += w + gap
                need_w = max(need_w, x - gap)
            lay.append((lab, items, y))
            y += ch + int(10 * u)
        w = max(need_w, title.get_width()) + 2 * pad
        h = y - int(10 * u) + 2 * pad
        r = pygame.Rect(0, 0, w, h)
        gb = self.r_settings
        bottom = gb.y - int(14 * u) if gb else H - self.tl_h - int(14 * u)
        bt = getattr(self, "bar_top", None)            # trên thanh dưới (minimap vẽ GPU đè lên mọi thứ trong thanh)
        if self.show_hud and bt is not None and bt - int(8 * u) - h >= 0:
            bottom = min(bottom, bt - int(8 * u))
        r.bottomright = ((gb.right if gb else W - int(10 * u)), bottom)
        r.clamp_ip(pygame.Rect(0, 0, W, H))
        self.panel(surf, r, (8, 10, 14, 238), border=(120, 110, 80), radius=8)
        surf.blit(title, (r.x + pad, r.y + pad))
        hits = []
        for (lab, items, ry), row in zip(lay, rows):
            surf.blit(lab, lab.get_rect(midleft=(r.x + pad, r.y + pad + ry + ch // 2)))
            for br, t, it in items:
                b = br.move(r.x + pad, r.y + pad)
                hov = self.hover_pos is not None and b.collidepoint(self.hover_pos)
                if it.get("active"):
                    self.panel(surf, b, (90, 72, 30, 245), border=GOLD, radius=5)
                else:
                    self.panel(surf, b, (52, 50, 44, 245) if hov else (30, 30, 34, 235),
                               border=(150, 140, 100) if hov else (80, 76, 64), radius=5)
                surf.blit(t, t.get_rect(center=b.center))
                hits.append((b, it["act"]))
        self.settings_hits = hits
        self.r_settings_panel = r

    ECO_COLS = [("Đời", "age"), ("Dân", "vill"), ("Time", "popcap"), ("food", O.ATTR_FOOD),
                ("wood", O.ATTR_WOOD), ("gold", O.ATTR_GOLD), ("stone", O.ATTR_STONE)]
    MIL_COLS = [("Quân", "army"), ("Kill", "kills"), ("Chết", "deaths"), ("Phá nhà", "razings"),
                ("Công nghệ", "ntech"), ("Vàng KT", "gold_mined"), ("Bơm", "tribute")]
    RES_LABEL = {O.ATTR_FOOD: "Thực", O.ATTR_WOOD: "Gỗ", O.ATTR_GOLD: "Vàng", O.ATTR_STONE: "Đá"}

    BAR_BG = (12, 12, 14, 232)
    UNIT_RESERVE = 540            # bề rộng (x u) dành sẵn cho thẻ unit bên trái thanh dưới
    BAR_EDGE = (150, 135, 90)
    BAR_SEP = (90, 85, 70)

    def _bottom_bar(self, surf, m):
        """Một thanh thông tin chung ở cạnh dưới như giao diện trong game (người dùng 05/11): trái = thông tin unit
        đang chọn, giữa = bảng người chơi, phải = minimap; liền với thanh thời gian bên dưới. Cao bằng phần cao nhất
        (minimap / bảng người chơi; unit có bảng lệnh dài thì thanh cao lên)."""
        W, H = self.size
        u = self.u
        pad = int(5 * u)
        mm = self.r_minimap if self.show_minimap else None
        art = self._bar_surface(getattr(m, "bar_style", None), W)
        # vùng ngang của bảng người chơi (từ chỗ dành cho thẻ unit tới minimap) + chiều cao bảng được phép (bằng ảnh
        # thanh dưới của game) -> bảng nhiều người chia 2 cột thay vì làm thanh cao gấp đôi
        if mm is None:
            sb_right = W - pad
        elif art is not None:
            sb_right = int(W * 1692 / 1920) - pad
        else:
            sb_right = W - mm.w - 2 * pad - int(4 * u)
        self._sb_span = (int(self.UNIT_RESERVE * u), sb_right)
        self._sb_max_h = int(round(126 * W / 1920)) - 2 * pad
        sb = self._scoreboard(surf, m, measure=True) if self.show_score and m.teams else None
        base_h = int(round(126 * W / 1920)) if art is not None else 0      # cao như thanh dưới của game
        self.bar_inner_h = base_h - 2 * pad                                 # thẻ unit cố vừa chiều cao này
        ui = self._unit_info(surf, m, measure=True) if m.unit_info else None
        hs = [x[1] + 2 * pad for x in (ui, sb) if x] + ([mm.h + int(8 * u)] if mm is not None else []) + [base_h]
        if not any(hs):
            return
        bar_h = max(hs)
        top = self.bottom - bar_h
        self.bar_top = top
        bg = pygame.Surface((W, H - top), pygame.SRCALPHA)
        bg.fill(self.BAR_BG)
        surf.blit(bg, (0, top))
        art_top = top
        if art is not None:
            art_h = art.get_height()
            art_top = top + bar_h - art_h                    # ảnh giữ chiều cao gốc ở đáy thanh
            if bar_h > art_h:
                # thanh cao hơn ảnh (bảng lệnh của nhà...): phần trên lấp bằng dải hoa văn giữa ảnh (bỏ ô chân dung
                # và ô minimap), không kéo dãn ảnh
                key = ("fill", id(art), bar_h - art_h)
                if key not in self._bar_cache:
                    band = art.subsurface(pygame.Rect(int(W * 140 / 1920), int(art_h * 0.15), int(W * 1540 / 1920), int(art_h * 0.7)))
                    self._bar_cache[key] = pygame.transform.smoothscale(band, (W, bar_h - art_h))
                surf.blit(self._bar_cache[key], (0, top))
            surf.blit(art, (0, art_top))
        pygame.draw.line(surf, self.BAR_EDGE, (0, top), (W, top), max(1, int(2 * u)))
        y = top + pad
        left_end = pad
        if ui:
            self.panel(surf, pygame.Rect(pad // 2, top + pad // 2, ui[0] + pad, bar_h - pad), (8, 10, 14, 170), radius=4)
            left_end = pad + ui[0] + 2 * pad
        right_end = W - pad
        if mm is not None:
            if art is not None:
                # ô hình thoi của ảnh: x 1692-1910, y 7-115 trên ảnh 1920 x 126 (giữ tỉ lệ bản đồ, đặt giữa ô)
                bx0, bx1 = W * 1692 / 1920, W * 1911 / 1920
                ah = bar_h - (art_top - top)
                by0, by1 = art_top + ah * 7 / 126, art_top + ah * 116 / 126
                bw, bh = bx1 - bx0, by1 - by0
                s = min(bw / mm.w, bh / mm.h)
                mm.size = (int(mm.w * s), int(mm.h * s))
                mm.center = (int((bx0 + bx1) / 2), int((by0 + by1) / 2))
                right_end = int(bx0) - pad
            else:
                mm.topleft = (W - mm.w - pad - int(2 * u), y + int(2 * u))
                pygame.draw.rect(surf, (120, 110, 80), mm.inflate(int(4 * u), int(4 * u)), 1)
                right_end = mm.x - int(2 * u) - pad
        if sb:
            # vị trí cố định (người dùng 05/11): giữa vùng từ chỗ dành sẵn cho thẻ unit tới minimap, theo bề rộng lớn
            # nhất của hai chế độ bảng -> không xê dịch khi chọn / bỏ chọn unit hay đổi Kinh tế / Quân sự
            sm = self.score_mode
            sw = sb[0]
            try:
                self.score_mode = 1 - sm
                o = self._scoreboard(surf, m, measure=True)
                sw = max(sw, o[0]) if o else sw
            finally:
                self.score_mode = sm
            l_res = int(self.UNIT_RESERVE * u)
            x = l_res + max(0, (right_end - l_res - sw) // 2)
            x = max(x, left_end) if ui and left_end > l_res else x     # (thẻ quá rộng: tránh đè, hiếm)
            self.sb_x = x
            self.panel(surf, pygame.Rect(x - pad, top + pad // 2, sb[0] + 2 * pad, bar_h - pad), (8, 10, 14, 170), radius=4)
            self._scoreboard(surf, m, pos=(x, y))
        if ui:
            self._unit_info(surf, m, pos=(pad, y))

    def _bar_surface(self, style, W):
        """Ảnh thanh dưới của game theo bộ giao diện, kéo theo chiều rộng cửa sổ (None: không có đồ hoạ game)."""
        if self.bar_art is None or style is None:
            return None
        key = (style, W)
        if key not in self._bar_cache:
            try:
                im = self.bar_art(style)
            except Exception:  # noqa: BLE001
                im = None
            if im is not None:
                im = pygame.transform.smoothscale(im, (W, int(round(126 * W / 1920))))
            self._bar_cache[key] = im
        return self._bar_cache[key]

    def _cell(self, p, key):
        if key == "age":
            a = p["age"]
            return AGE_VI.get(int(a), str(int(a))) if a is not None else "-"
        if key == "popcap":
            return "-" if p["pop"] is None else f"{int(p['pop'])}/{int(p['pop'] + (p['room'] or 0))}"
        if isinstance(key, int):
            v = p["attrs"][key] if key < len(p["attrs"]) else None
            return "-" if v is None else str(int(v))
        v = p.get(key)
        return "-" if v is None else str(int(v))

    SHORT_LABEL = {"Công nghệ": "C.nghệ", "Thời đại": "T.đại", "Phá nhà": "Phá"}
    SPLIT_GAP = 14                # (x u) khoảng giữa hai cột của bảng chia đôi

    def _sb_layout(self, m):
        """Bố cục bảng người chơi. Một cột (dòng tên đội + từng người) khi vừa chiều cao thanh dưới của game; không vừa
        (2v2 trở lên, đánh tự do từ 4 người) thì chia 2 cột cạnh nhau (người dùng 07/11: 5-8 người làm thanh chồng 2
        tầng): mỗi cột một hàng tiêu đề + tối đa 4 người, cắt ở ranh giới đội nếu được, tên đội ghi ở hàng tiêu đề."""
        u = self.u
        cols = self.ECO_COLS if self.score_mode == 0 else self.MIL_COLS
        grouped = any(len(t) > 1 for t in m.teams)        # mỗi người một đội (đánh tự do): không cần dòng tên đội
        flat = [(k, p) for k, t in enumerate(m.teams) for p in t]
        n_rows = len(flat) + (len(m.teams) if grouped else 0) + 1
        row_h = int(25 * u)
        one_h = n_rows * row_h + int(12 * u)
        max_h = getattr(self, "_sb_max_h", None)
        L = {"cols": cols, "grouped": grouped, "fs": int(16 * u), "row_h": row_h, "split": False}
        if max_h is None or one_h <= max_h or len(flat) < 2:
            L.update(name_w=int(250 * u), col_w=int(78 * u), h=one_h)
            L["w"] = L["name_w"] + L["col_w"] * len(cols) + int(20 * u)
            return L
        # chia 2 cột: cắt ở ranh giới đội nếu cột dài nhất vẫn vừa chiều cao (hàng >= 19 px), gần nửa nhất; không thì
        # chia đều (7v1, 5v3: một đội nằm ở cả hai cột, có vạch giữa hai đội)
        n = len(flat)
        half = (n + 1) // 2
        cap = max(half, (max_h - int(12 * u)) // max(1, int(19 * u)) - 1)
        cut = half
        acc = 0
        best = None
        for t in m.teams[:-1]:
            acc += len(t)
            if 0 < acc < n and max(acc, n - acc) <= cap and (best is None or abs(acc - half) < abs(best - half)):
                best = acc
        if best is not None:
            cut = best
        parts = [flat[:cut], flat[cut:]]
        rows = max(len(p) for p in parts) + 1
        row_h = max(int(16 * u), min(int(25 * u), (max_h - int(12 * u)) // rows))
        fs = max(int(11 * u), min(int(16 * u), int(row_h * 0.72)))
        l_res, right = getattr(self, "_sb_span", (0, self.size[0]))
        gap = int(self.SPLIT_GAP * u)
        cw = min(int(250 * u) + int(78 * u) * len(cols) + int(20 * u), (right - l_res - gap) // 2)
        inner = cw - int(20 * u)
        col_w = max(int(36 * u), min(int(78 * u), (inner - int(165 * u)) // len(cols)))
        name_w = max(int(90 * u), inner - col_w * len(cols))
        cw = name_w + col_w * len(cols) + int(20 * u)
        L.update(split=True, parts=parts, row_h=row_h, fs=fs, name_w=name_w, col_w=col_w, cw=cw, gap=gap,
                 w=2 * cw + gap, h=rows * row_h + int(12 * u))
        return L

    def _fit(self, s, size, maxw, color=WHITE, bold=False, min_size=None):
        """Chữ vừa bề rộng maxw: thu nhỏ cỡ chữ (tới min_size) rồi mới cắt bớt kèm "…"."""
        t = self.text(s, size, color, bold=bold)
        if t.get_width() <= maxw:
            return t
        lo = min_size or max(8, int(size * 0.8))
        for sz in range(size - 1, lo - 1, -1):
            t = self.text(s, sz, color, bold=bold)
            if t.get_width() <= maxw:
                return t
        while len(s) > 1 and t.get_width() > maxw:
            s = s[:-1]
            t = self.text(s.rstrip() + "…", lo, color, bold=bold)
        return t

    def _scoreboard(self, surf, m, measure=False, pos=None):
        """measure: chỉ trả về (rộng, cao); pos: góc trên trái trong thanh dưới (không vẽ khung riêng)."""
        if not m.teams:
            return None
        W, _H = self.size
        u = self.u
        L = self._sb_layout(m)
        w, h = L["w"], L["h"]
        avail_right = (self.r_minimap.x - int(12 * u)) if self.show_minimap else W
        x0 = max(int(10 * u), min((W - w) // 2, avail_right - w))
        y0 = self.bottom - h - int(6 * u)
        if measure:
            return w, h
        if pos is not None:
            x0, y0 = pos
        r = pygame.Rect(x0, y0, w, h)
        if pos is None:
            self.panel(surf, r, border=(120, 110, 80))
        title = "Kinh tế" if self.score_mode == 0 else "Quân sự"
        # một cỡ chữ cho cả cột (chữ dài như "Công cụ" không nhỏ hơn "Đồ đá" ở hàng bên cạnh)
        room = L["col_w"] - int(4 * u)
        L["cell_fs"] = {}
        for _label, ck in L["cols"]:
            sz = L["fs"]
            for team in m.teams:
                for p in team:
                    while sz > max(8, int(L["fs"] * 0.8)) and self.text(self._cell(p, ck), sz).get_width() > room:
                        sz -= 1
            L["cell_fs"][ck] = sz
        if not L["split"]:
            y = self._sb_header(surf, L, x0, y0 + int(6 * u), f"{title}  (X đổi)")
            for k, team in enumerate(m.teams):
                if L["grouped"]:
                    row_h = L["row_h"]
                    pygame.draw.line(surf, (90, 85, 70), (x0 + int(8 * u), y + row_h // 2), (r.right - int(8 * u), y + row_h // 2))
                    t = self.text(f"Đội {k + 1}", int(14 * u), GREY, bold=True)
                    tr = t.get_rect(midleft=(x0 + int(10 * u), y + row_h // 2))
                    pygame.draw.rect(surf, (8, 10, 14), tr.inflate(int(8 * u), 0))
                    surf.blit(t, tr)
                    y += row_h
                for p in team:
                    self._sb_row(surf, m, L, x0, y, w, p)
                    y += L["row_h"]
            return
        # hai cột cạnh nhau: tên đội ở hàng tiêu đề; đội đổi giữa cột thì kẻ một vạch giữa hai hàng
        cw = L["cw"]
        for c, part in enumerate(L["parts"]):
            cx = x0 + c * (cw + L["gap"])
            if c:
                pygame.draw.line(surf, self.BAR_SEP, (cx - L["gap"] // 2, y0 + int(4 * u)),
                                 (cx - L["gap"] // 2, y0 + h - int(4 * u)))
            teams = sorted({k for k, _p in part})
            label = (f"Đội {teams[0] + 1}" if len(teams) == 1 else f"Đội {teams[0] + 1}–{teams[-1] + 1}") \
                if L["grouped"] and teams else ""
            head = (f"{title} · {label}" if c == 0 else label) if label else (title if c == 0 else "")
            y = self._sb_header(surf, L, cx, y0 + int(6 * u), head)
            prev = None
            for k, p in part:
                if L["grouped"] and prev is not None and k != prev:
                    pygame.draw.line(surf, self.BAR_EDGE, (cx + int(6 * u), y), (cx + cw - int(6 * u), y), max(1, int(2 * u)))
                prev = k
                self._sb_row(surf, m, L, cx, y, cw, p)
                y += L["row_h"]

    def _sb_header(self, surf, L, x0, y, head):
        """Hàng tiêu đề: chữ ở ô tên + nhãn / biểu tượng các cột. Trả về y của hàng kế."""
        u = self.u
        fs, row_h, col_w = L["fs"], L["row_h"], L["col_w"]
        if head:
            surf.blit(self._fit(head, fs, L["name_w"] - int(12 * u), GOLD, bold=True), (x0 + int(10 * u), y + int(2 * u)))
        x = x0 + L["name_w"]
        for label, key in L["cols"]:
            ic = self.icons.get(key) if isinstance(key, int) else None
            if ic is not None:
                s = pygame.transform.smoothscale(ic, (int(ic.get_width() * row_h * 0.8 / ic.get_height()), int(row_h * 0.8)))
                surf.blit(s, s.get_rect(center=(x + col_w // 2, y + row_h // 2)))
            else:
                lab = self.RES_LABEL.get(key, label) if isinstance(key, int) else label
                room = col_w - int(4 * u)
                if lab in self.SHORT_LABEL and self.text(lab, max(8, int(fs * 0.8)), GOLD).get_width() > room:
                    lab = self.SHORT_LABEL[lab]                  # cột hẹp (bảng chia 2 cột): nhãn ngắn thay vì "…"
                t = self._fit(lab, fs, room, GOLD)
                surf.blit(t, t.get_rect(center=(x + col_w // 2, y + row_h // 2)))
            x += col_w
        return y + row_h

    def _sb_row(self, surf, m, L, x0, y, w, p):
        """Một hàng người chơi (ô màu, [phím] tên, civ / trạng thái nếu còn chỗ, các cột số)."""
        u = self.u
        fs, row_h, name_w, col_w = L["fs"], L["row_h"], L["name_w"], L["col_w"]
        rr = pygame.Rect(x0 + int(4 * u), y, w - int(8 * u), row_h)
        if p["index"] == m.selected:
            self.panel(surf, rr, (255, 214, 120, 50), radius=4)
        self.score_rows.append((rr, p["index"]))
        sqs = min(row_h - int(10 * u), int(15 * u))
        sq = pygame.Rect(x0 + int(10 * u), y + (row_h - sqs) // 2, sqs, sqs)
        pygame.draw.rect(surf, p["rgb"], sq)
        pygame.draw.rect(surf, WHITE, sq, 1)
        key = p.get("hotkey")
        nm = (f"[{key}] " if key else "") + p["name"]
        civ = p.get("civ") or ""
        stt = p.get("status")
        if stt:
            civ = stt.upper()
        name_room = x0 + name_w - int(4 * u) - (sq.right + int(8 * u))
        t = self._fit(nm, fs, name_room, GREY if stt in ("thua", "đầu hàng") else WHITE, bold=p["index"] == m.selected)
        surf.blit(t, (sq.right + int(8 * u), y + (row_h - t.get_height()) // 2))
        if civ:
            col = (120, 220, 120) if stt == "thắng" else (230, 110, 100) if stt else GREY
            tc = self.text(civ, min(int(13 * u), fs - int(2 * u)), col, bold=bool(stt))
            cx = sq.right + int(14 * u) + t.get_width()
            if cx + tc.get_width() < x0 + name_w - int(4 * u):
                surf.blit(tc, (cx, y + (row_h - tc.get_height()) // 2 + 1))
        x = x0 + name_w
        for _label, ck in L["cols"]:
            t = self._fit(self._cell(p, ck), L.get("cell_fs", {}).get(ck, fs), col_w - int(4 * u))
            surf.blit(t, t.get_rect(center=(x + col_w // 2, y + row_h // 2)))
            x += col_w

    def _techs(self, surf, m):
        W, _H = self.size
        u = self.u
        if m.sel_player is None:
            return
        cols = 6
        icon = int(44 * u)
        cell_w = icon + int(18 * u)
        cell_h = icon + int(22 * u)
        techs = m.techs[-cols * 7:]
        n_rows = max(1, (len(techs) + cols - 1) // cols)
        w = cols * cell_w + int(20 * u)
        resg = getattr(m, "researching", []) or []
        res_h = len(resg) * int(40 * u) + (int(8 * u) if resg else 0)
        h = int(36 * u) + res_h + n_rows * cell_h + int(8 * u)
        top = int(76 * u) if self.r_persp is None else max(int(76 * u), self.r_persp.bottom + int(6 * u))
        r = pygame.Rect(W - w - int(10 * u), top, w, h)      # dưới thẻ góc nhìn
        self.panel(surf, r, border=(120, 110, 80))
        surf.blit(self.text(f"Công nghệ · {m.sel_player['name']}", int(16 * u), m.sel_player["rgb"], bold=True),
                  (r.x + int(10 * u), r.y + int(6 * u)))
        yy = r.y + int(34 * u)
        for name, frac, icon_id in resg:                 # đang nghiên cứu: icon + tên + % + thanh tiến độ
            ic = self.tech_icon(icon_id, int(32 * u)) if self.tech_icon else None
            cx = r.x + int(10 * u)
            if ic is not None:
                surf.blit(ic, (cx, yy))
                cx += ic.get_width() + int(8 * u)
            t = self.text(f"{name}  {int(frac * 100)}%", int(14 * u), GOLD, True)
            surf.blit(t, (cx, yy))
            bar = pygame.Rect(cx, yy + t.get_height() + int(2 * u), r.right - cx - int(10 * u), int(7 * u))
            pygame.draw.rect(surf, (50, 50, 50), bar)
            b2 = bar.copy(); b2.width = int(bar.width * frac)
            pygame.draw.rect(surf, GOLD, b2)
            yy += int(40 * u)
        if resg:
            yy += int(8 * u)
        if not techs and not resg:
            surf.blit(self.text("(chưa có)", int(15 * u), GREY), (r.x + int(10 * u), yy + int(2 * u)))
        for k, (t, name, icon_id) in enumerate(techs):
            cx = r.x + int(10 * u) + (k % cols) * cell_w
            cy = yy + (k // cols) * cell_h
            ic = self.tech_icon(icon_id, icon) if self.tech_icon else None
            if ic is not None:
                surf.blit(ic, (cx + (cell_w - icon) // 2, cy))
            else:
                pygame.draw.rect(surf, GREY, (cx + (cell_w - icon) // 2, cy, icon, icon), 1)
                surf.blit(self.text(name[:7], int(11 * u)), (cx + 4, cy + 4))
            ts = self.text(fmt_ms(t), int(12 * u), GREY)
            surf.blit(ts, ts.get_rect(midtop=(cx + cell_w // 2, cy + icon + 1)))

    # icon chỉ số của game (interfac.drs 50731): 7 kiếm = công, 8 áo giáp = giáp, 9 đồng hồ cát = tốc đánh,
    # 10 khiên = giáp xuyên; khung 6 (bia tầm bắn) kích cỡ lạ 319x192 nên tầm dùng chữ
    STAT_ICONS = {"attack": (50731, 7), "armor": (50731, 8), "reload": (50731, 9), "pierce": (50731, 10),
                  "res0": (50731, 2), "res1": (50731, 0), "res2": (50731, 1), "res3": (50731, 3)}   # thực, gỗ, đá, vàng

    def _stat_icon(self, key, size):
        cache = self.__dict__.setdefault("_stat_icon_cache", {})
        k = (key, size)
        if k not in cache:
            cache[k] = None
            spec = self.STAT_ICONS.get(key)
            if spec is not None and self.slp_icon is not None:
                im = self.slp_icon(*spec)
                if im is not None:
                    w = max(1, int(round(im.get_width() * size / im.get_height())))
                    cache[k] = pygame.transform.smoothscale(im, (w, size))
        return cache[k]

    def _unit_info(self, surf, m, measure=False, pos=None):
        """Bảng thông tin unit kiểu trong game. Cột trái: chân dung, tên, chủ, thanh máu (còn / mất), tài nguyên, chỉ
        số có icon. Cột phải (công trình): tiến độ nghiên cứu / hàng sinh quân, hoặc bảng lệnh 2 x 5 khi nhà đang rảnh
        — đặt bên cạnh thay vì xếp chồng để thẻ không cao hơn thanh dưới của game (người dùng 05/11)."""
        u = self.u * 0.78                     # (gọn trong thanh dưới chung: người dùng 05/11 thấy quá to)
        info = m.unit_info
        fs = int(16 * u)
        icon = info.get("icon")
        port = int(64 * u)
        m12 = int(12 * u)
        head = [self.text(info["name"], int(20 * u), WHITE, True)]
        if info.get("owner"):
            head.append(self.text(info["owner"], int(15 * u), info["rgb"], True))
        hp = info.get("hp")
        stats = info.get("stats") or []
        cols = 3
        row_h = int(28 * u)
        ic_sz = int(22 * u)
        stat_s = []                           # (icon hoặc nhãn, giá trị) dựng sẵn để đo cột vừa nội dung
        for key, label, val in stats:
            ic = self._stat_icon(key, ic_sz) if key else None
            lab = ic if ic is not None else self.text(label, int(14 * u), GREY)
            stat_s.append((lab, ic is not None, self.text(val, fs, WHITE, True)))
        cell_w = max([lb.get_width() + int((6 if isic else 8) * u) + vt.get_width() for lb, isic, vt in stat_s] + [0]) \
            + int(18 * u)
        n_rows = (len(stats) + cols - 1) // cols
        extra = [self.text(s, int(14 * u), GREY) for s in info.get("lines", [])]
        res = info.get("res")
        progress = info.get("progress") or []
        queue = info.get("queue")
        cmd = info.get("cmd")
        if progress or queue:                 # đang nâng cấp / sinh quân: không cần danh sách có thể làm
            cmd = None
        # ---- cột trái
        res_h = row_h if res else 0
        top_h = max(port, sum(s.get_height() for s in head) + (int(30 * u) if hp else 0)) + int(16 * u)
        a_h = top_h + res_h + n_rows * row_h + sum(e.get_height() for e in extra) + int(8 * u)
        # thanh máu ngắn gọn (người dùng 05/11: quá dài): vừa chữ số máu, không kéo theo bề rộng thẻ
        hp_t = None
        if hp:
            cur, mx = hp
            hp_t = self.text(f"{int(round(cur))} / {int(mx)}", int(13 * u), WHITE, True)
        hp_w = max(int(150 * u), hp_t.get_width() + int(16 * u)) if hp_t else 0
        head_w = max([sh.get_width() for sh in head] + [hp_w])
        a_w = max([m12 + port + m12 + head_w + m12, int(230 * u)]
                  + ([cols * cell_w - int(18 * u) + 2 * m12] if stats else []) + [e.get_width() + 2 * m12 for e in extra])
        # ---- cột phải
        gap = int(4 * u)
        prog_t = [self.text(f"{label}  {int(frac * 100)}%", int(14 * u), WHITE) for label, frac, _i in progress]
        q_t = None
        if queue:
            q_t = self.text(f"Đang sinh: {queue['name']}  {int(queue['frac'] * 100)}%", int(15 * u), WHITE, True)
        cmd_rows = 0
        if cmd and cmd["slots"]:
            cmd_rows = max((b - 1) // 5 for b, _v in cmd["slots"]) + 1
        cmd_note = self.text(cmd["note"], int(12 * u), GREY) if cmd and cmd.get("note") else None
        note_h = cmd_note.get_height() + int(4 * u) if cmd_note else 0
        avail = max(a_h, int(getattr(self, "bar_inner_h", 0) or 0))   # cao thẻ được phép (thanh dưới của game)
        cell = 0
        if cmd_rows:
            cell = max(int(24 * u), min(int(46 * u), (avail - int(16 * u) - note_h) // cmd_rows - gap))
        b_h = len(progress) * int(36 * u) + (int(52 * u) if queue else 0) + cmd_rows * (cell + gap) + note_h
        b_w = 0
        if b_h:
            b_h += int(16 * u)
            b_w = max([int(260 * u)] + [t.get_width() + int(30 * u) + int(8 * u) for t in prog_t]
                      + ([q_t.get_width() + int(54 * u)] if q_t else [])
                      + ([5 * (cell + gap)] if cmd_rows else []) + ([cmd_note.get_width()] if cmd_note else [])) + 2 * m12
        w = a_w + b_w
        h = max(a_h, b_h)
        if measure:
            return w, h
        r = pygame.Rect(int(10 * u), self.bottom - h - int(6 * u), w, h) if pos is None else pygame.Rect(pos[0], pos[1], w, h)
        if pos is None:
            self.panel(surf, r, (8, 10, 14, 225), border=(150, 135, 90))
        a_right = r.x + a_w
        x = r.x + m12
        y = r.y + int(8 * u)
        pr = pygame.Rect(x, y, port, port)
        pygame.draw.rect(surf, (30, 30, 30), pr)
        if icon is not None:
            surf.blit(pygame.transform.smoothscale(icon, (port, port)), pr)
        pygame.draw.rect(surf, info["rgb"], pr, max(1, int(2 * u)))
        tx = pr.right + m12
        ty = y
        for s in head:
            surf.blit(s, (tx, ty))
            ty += s.get_height()
        if hp:
            cur, mx = hp
            bar = pygame.Rect(tx, ty + int(6 * u), min(hp_w, a_right - tx - m12), int(14 * u))
            frac = max(0.0, min(1.0, cur / mx)) if mx else 0.0
            pygame.draw.rect(surf, (120, 25, 25), bar)
            b2 = bar.copy(); b2.width = int(bar.width * frac)
            pygame.draw.rect(surf, (50, 190, 60) if frac > 0.5 else (220, 190, 40) if frac > 0.25 else (220, 70, 40), b2)
            pygame.draw.rect(surf, (0, 0, 0), bar, 1)
            surf.blit(hp_t, hp_t.get_rect(center=bar.center))
        y = r.y + top_h
        if res:
            ic = self._stat_icon(res[0], int(22 * u))
            cx = r.x + m12
            if ic is not None:
                surf.blit(ic, (cx, y + (row_h - ic.get_height()) // 2))
                cx += ic.get_width() + int(8 * u)
            t = self.text(res[1], int(17 * u), GOLD, True)
            surf.blit(t, (cx, y + (row_h - t.get_height()) // 2))
            y += row_h
        for k, (lab, isic, vt) in enumerate(stat_s):
            cx = r.x + m12 + (k % cols) * cell_w
            cy = y + (k // cols) * row_h
            surf.blit(lab, (cx, cy + (row_h - lab.get_height()) // 2))
            lx = cx + lab.get_width() + int((6 if isic else 8) * u)
            surf.blit(vt, (lx, cy + (row_h - vt.get_height()) // 2))
        y += n_rows * row_h
        for e in extra:
            surf.blit(e, (r.x + m12, y))
            y += e.get_height()
        # ---- cột phải
        self.cmd_hits = []
        if not b_w:
            return
        pygame.draw.line(surf, (90, 85, 70), (a_right, r.y + int(8 * u)), (a_right, r.bottom - int(8 * u)))
        bx = a_right + m12
        y = r.y + int(8 * u)
        for (label, frac, icon_id), t in zip(progress, prog_t):
            ic = self.tech_icon(icon_id, int(30 * u)) if self.tech_icon else None
            cx = bx
            if ic is not None:
                surf.blit(ic, (cx, y + int(2 * u)))
                cx += ic.get_width() + int(8 * u)
            surf.blit(t, (cx, y))
            bar = pygame.Rect(cx, y + t.get_height() + int(2 * u), r.right - cx - m12, int(7 * u))
            pygame.draw.rect(surf, (50, 50, 50), bar)
            b2 = bar.copy(); b2.width = int(bar.width * frac)
            pygame.draw.rect(surf, GOLD, b2)
            y += int(36 * u)
        if queue:                                         # đang sinh: icon unit + số trong hàng + thanh tiến độ
            qi = int(44 * u)
            box = pygame.Rect(bx, y + int(2 * u), qi, qi)
            pygame.draw.rect(surf, (30, 30, 30), box)
            if queue.get("icon") is not None:
                surf.blit(pygame.transform.smoothscale(queue["icon"], (qi, qi)), box)
            pygame.draw.rect(surf, (150, 135, 90), box, 1)
            if queue["count"] > 1:                         # số trên góc icon như nút trong game
                ct = self.text(str(queue["count"]), int(16 * u), WHITE, True)
                surf.blit(ct, ct.get_rect(bottomright=(box.right - int(2 * u), box.bottom)))
            tx = box.right + int(10 * u)
            surf.blit(q_t, (tx, y + int(2 * u)))
            bar = pygame.Rect(tx, y + int(4 * u) + q_t.get_height(), r.right - tx - m12, int(7 * u))
            t2 = self.text(f"Hàng đợi: {queue['count']}", int(13 * u), GREY)
            surf.blit(t2, (tx, bar.bottom + int(2 * u)))
            pygame.draw.rect(surf, (50, 50, 50), bar)
            b2 = bar.copy(); b2.width = int(bar.width * queue["frac"])
            pygame.draw.rect(surf, (90, 200, 90), b2)
            y += int(52 * u)
        if cmd_rows:                                      # bảng lệnh 2 x 5 như trong game: nút b -> hàng (b-1)//5, cột (b-1)%5
            mouse = pygame.mouse.get_pos()
            for b, (kind, ic, label, cost) in cmd["slots"]:
                k = b - 1
                box = pygame.Rect(bx + (k % 5) * (cell + gap), y + (k // 5) * (cell + gap), cell, cell)
                pygame.draw.rect(surf, (30, 30, 30), box)
                if ic is not None:
                    surf.blit(pygame.transform.smoothscale(ic, (cell, cell)), box)
                else:
                    t = self.text(label[:6], int(11 * u), WHITE)
                    surf.blit(t, t.get_rect(center=box.center))
                hov = box.collidepoint(mouse)
                pygame.draw.rect(surf, GOLD if hov else ((150, 135, 90) if kind == "tech" else (110, 130, 160)), box,
                                 max(1, int(2 * u)) if hov else 1)
                self.cmd_hits.append((box, label + (f"  ({cost})" if cost else "")))
            y += cmd_rows * (cell + gap)
        if cmd_note is not None:
            surf.blit(cmd_note, (bx, y))
        if self.hover_cmd is not None and self.hover_cmd < len(self.cmd_hits):
            box, tip = self.cmd_hits[self.hover_cmd]
            t = self.text(tip, int(14 * u), WHITE, True)
            tr = pygame.Rect(0, 0, t.get_width() + int(12 * u), t.get_height() + int(8 * u))
            tr.bottomleft = (box.x, box.y - int(4 * u))
            self.panel(surf, tr, (8, 10, 14, 240), border=GOLD)
            surf.blit(t, (tr.x + int(6 * u), tr.y + int(4 * u)))

    def _help(self, surf):
        W, H = self.size
        u = self.u
        fs = int(17 * u)
        keys = [self.text(k, fs, GOLD, bold=True) for k, _ in self.KEYS_HELP]
        descs = [self.text(d, fs) for _, d in self.KEYS_HELP]
        kw = max(s.get_width() for s in keys)
        row_h = int(28 * u)
        w = kw + max(s.get_width() for s in descs) + int(70 * u)
        h = row_h * len(keys) + int(64 * u)
        r = pygame.Rect(0, 0, w, h)
        r.center = (W // 2, H // 2)
        self.panel(surf, r, (8, 10, 14, 235), border=(120, 110, 80))
        surf.blit(self.text("Phím tắt", int(20 * u), WHITE, bold=True),
                  (r.x + int(24 * u), r.y + int(14 * u)))
        y = r.y + int(52 * u)
        for k, d in zip(keys, descs):
            surf.blit(k, (r.x + int(24 * u), y))
            surf.blit(d, (r.x + int(44 * u) + kw, y))
            y += row_h
