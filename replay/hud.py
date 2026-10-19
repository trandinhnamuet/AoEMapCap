"""HUD của trình xem replay, vẽ bằng pygame lên một Surface trong suốt cỡ cửa sổ (đưa lên GPU thành 1 texture).

Bố cục theo replay LMHT: đồng hồ + tỉ số đội ở giữa trên, thanh thời gian dưới cùng (U), bảng tỉ số giữa dưới (O,
X đổi cột), minimap góc phải dưới, bảng công nghệ người chơi đang chọn bên phải (C), trợ giúp (?).
"""
import os

import pygame

from mapcap import offsets as O

AGE_VI = {0: "Du mục", 1: "Đồ đá", 2: "Công cụ", 3: "Đồ đồng", 4: "Đồ sắt"}
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
    KEYS_HELP = [
        ("P", "phát / tạm dừng"),
        ("-  /  =", "chậm / nhanh (0,25x … 16x);  0: tốc độ thường"),
        ("Backspace  /  J", "lùi / tiến 15 giây (giờ game)"),
        ("F1  /  F2  /  F3", "tầm nhìn đội 1 / đội 2 / toàn bản đồ  (F4–F8: đội 3–7)"),
        ("V  /  F", "đổi vòng tầm nhìn  /  bật-tắt sương mù"),
        ("1–5  /  Q–T", "chọn người chơi đội 1 / đội 2 (đưa máy quay tới nhà chính)"),
        ("Space", "đưa máy quay về người chơi đang chọn"),
        ("O  /  X", "bảng tỉ số  /  đổi cột kinh tế ↔ quân sự"),
        ("C", "bảng công nghệ của người chơi đang chọn"),
        ("U  /  H  /  M", "thanh thời gian  /  ẩn toàn bộ HUD  /  minimap"),
        ("Lăn chuột", "zoom quanh con trỏ;  Home / bấm chuột giữa: xem cả bản đồ"),
        ("Chuột ra mép, mũi tên, kéo chuột", "di chuyển máy quay"),
        ("Bấm vào unit", "xem thông tin + khoá máy quay theo unit;  bấm chỗ trống để đóng"),
        ("L", "bật / tắt khoá máy quay theo unit đang chọn (tự di chuyển máy quay cũng bỏ khoá)"),
        ("S", "bật / tắt âm thanh (nghe theo những gì máy quay đang nhìn, tốc độ tối đa x2)"),
        ("F11  /  Alt+Enter", "bật / tắt toàn màn hình"),
        ("Esc  /  ?", "bật / tắt bảng này (bấm chuột bất kì đâu cũng đóng)"),
    ]

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
        # vùng bấm (cập nhật mỗi lần vẽ)
        self.r_timeline = None
        self.r_play = None
        self.r_help = None           # nút "Phím tắt (Esc)" trên thanh thời gian
        self.r_minimap = None
        self.score_rows = []         # [(Rect, index người chơi)]
        self.hover_timeline = None   # tỉ lệ 0..1 khi chuột trên thanh thời gian
        self.cmd_hits = []           # [(Rect, chữ gợi ý)] các nút bảng lệnh công trình vừa vẽ
        self.hover_cmd = None        # chỉ số nút đang rê chuột

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
        mm_w = int(min(W * 0.24, 460 * u))
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
        self.r_timeline = self.r_play = self.r_help = None
        if m.loading is not None:
            self._loading(surf, m)
            return surf
        if self.show_hud:
            self._top(surf, m)
            if self.show_timeline:
                self._timeline(surf, m)
            if self.show_minimap:
                r = self.r_minimap
                self.panel(surf, r.inflate(int(8 * self.u), int(8 * self.u)), (8, 10, 14, 230), border=(120, 110, 80))
            if self.show_score:
                self._scoreboard(surf, m)
            if self.show_techs:
                self._techs(surf, m)
            if m.unit_info:
                self._unit_info(surf, m)
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
        bar = pygame.Rect(x, r.centery - int(4 * u), hb.x - x - int(16 * u), int(8 * u))
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

    ECO_COLS = [("Thời đại", "age"), ("Dân", "vill"), ("Dân số", "popcap"), ("food", O.ATTR_FOOD),
                ("wood", O.ATTR_WOOD), ("gold", O.ATTR_GOLD), ("stone", O.ATTR_STONE)]
    MIL_COLS = [("Quân", "army"), ("Kill", "kills"), ("Chết", "deaths"), ("Phá nhà", "razings"),
                ("Công nghệ", "ntech"), ("Vàng KT", "gold_mined"), ("Bơm", "tribute")]
    RES_LABEL = {O.ATTR_FOOD: "Thực", O.ATTR_WOOD: "Gỗ", O.ATTR_GOLD: "Vàng", O.ATTR_STONE: "Đá"}

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

    def _scoreboard(self, surf, m):
        if not m.teams:
            return
        W, _H = self.size
        u = self.u
        cols = self.ECO_COLS if self.score_mode == 0 else self.MIL_COLS
        fs = int(16 * u)
        row_h = int(25 * u)
        name_w = int(250 * u)
        col_w = int(78 * u)
        grouped = any(len(t) > 1 for t in m.teams)        # mỗi người một đội (đánh tự do): không cần dòng tên đội
        n_rows = sum(len(t) for t in m.teams) + (len(m.teams) if grouped else 0) + 1
        w = name_w + col_w * len(cols) + int(20 * u)
        h = n_rows * row_h + int(12 * u)
        avail_right = (self.r_minimap.x - int(12 * u)) if self.show_minimap else W
        x0 = max(int(10 * u), min((W - w) // 2, avail_right - w))
        y0 = self.bottom - h - int(6 * u)
        r = pygame.Rect(x0, y0, w, h)
        self.panel(surf, r, border=(120, 110, 80))
        y = y0 + int(6 * u)
        title = "Kinh tế" if self.score_mode == 0 else "Quân sự"
        surf.blit(self.text(f"{title}  (X đổi)", fs, GOLD, bold=True), (x0 + int(10 * u), y + int(2 * u)))
        x = x0 + name_w
        for label, key in cols:
            ic = self.icons.get(key) if isinstance(key, int) else None
            if ic is not None:
                s = pygame.transform.smoothscale(ic, (int(ic.get_width() * row_h * 0.8 / ic.get_height()), int(row_h * 0.8)))
                surf.blit(s, s.get_rect(center=(x + col_w // 2, y + row_h // 2)))
            else:
                lab = self.RES_LABEL.get(key, label) if isinstance(key, int) else label
                t = self.text(lab, fs, GOLD)
                surf.blit(t, t.get_rect(center=(x + col_w // 2, y + row_h // 2)))
            x += col_w
        y += row_h
        for k, team in enumerate(m.teams):
            if grouped:
                pygame.draw.line(surf, (90, 85, 70), (x0 + int(8 * u), y + row_h // 2), (r.right - int(8 * u), y + row_h // 2))
                t = self.text(f"Đội {k + 1}", int(14 * u), GREY, bold=True)
                tr = t.get_rect(midleft=(x0 + int(10 * u), y + row_h // 2))
                pygame.draw.rect(surf, (8, 10, 14), tr.inflate(int(8 * u), 0))
                surf.blit(t, tr)
                y += row_h
            for p in team:
                rr = pygame.Rect(x0 + int(4 * u), y, w - int(8 * u), row_h)
                if p["index"] == m.selected:
                    self.panel(surf, rr, (255, 214, 120, 50), radius=4)
                self.score_rows.append((rr, p["index"]))
                sq = pygame.Rect(x0 + int(10 * u), y + int(5 * u), row_h - int(10 * u), row_h - int(10 * u))
                pygame.draw.rect(surf, p["rgb"], sq)
                pygame.draw.rect(surf, WHITE, sq, 1)
                key = p.get("hotkey")
                nm = (f"[{key}] " if key else "") + p["name"]
                civ = p.get("civ") or ""
                stt = p.get("status")
                if stt:
                    civ = stt.upper()
                t = self.text(nm, fs, GREY if stt in ("thua", "đầu hàng") else WHITE, bold=p["index"] == m.selected)
                surf.blit(t, (sq.right + int(8 * u), y + (row_h - t.get_height()) // 2))
                if civ:
                    col = (120, 220, 120) if stt == "thắng" else (230, 110, 100) if stt else GREY
                    tc = self.text(civ, int(13 * u), col, bold=bool(stt))
                    cx = sq.right + int(14 * u) + t.get_width()
                    if cx + tc.get_width() < x0 + name_w - int(4 * u):
                        surf.blit(tc, (cx, y + (row_h - tc.get_height()) // 2 + 1))
                x = x0 + name_w
                for _label, ck in cols:
                    t = self.text(self._cell(p, ck), fs)
                    surf.blit(t, t.get_rect(center=(x + col_w // 2, y + row_h // 2)))
                    x += col_w
                y += row_h

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
        r = pygame.Rect(W - w - int(10 * u), int(76 * u), w, h)
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

    def _unit_info(self, surf, m):
        """Bảng thông tin unit kiểu trong game: chân dung, tên, chủ, thanh máu (còn / mất), chỉ số có icon."""
        u = self.u
        info = m.unit_info
        fs = int(16 * u)
        icon = info.get("icon")
        port = int(64 * u)
        head = [self.text(info["name"], int(20 * u), WHITE, True)]
        if info.get("owner"):
            head.append(self.text(info["owner"], int(15 * u), info["rgb"], True))
        hp = info.get("hp")
        stats = info.get("stats") or []
        cols = 2
        cell_w = int(170 * u)
        row_h = int(28 * u)
        n_rows = (len(stats) + cols - 1) // cols
        extra = [self.text(s, int(14 * u), GREY) for s in info.get("lines", [])]
        res = info.get("res")
        progress = info.get("progress") or []
        res_h = row_h if res else 0
        prog_h = len(progress) * int(36 * u)
        queue = info.get("queue")
        if queue:
            prog_h += int(52 * u)
        cmd = info.get("cmd")
        cell = int(46 * u)
        gap = int(4 * u)
        cmd_rows = 0
        if cmd and cmd["slots"]:
            cmd_rows = max((b - 1) // 5 for b, _v in cmd["slots"]) + 1
        cmd_note = self.text(cmd["note"], int(12 * u), GREY) if cmd and cmd.get("note") else None
        cmd_h = (cmd_rows * (cell + gap) + int(10 * u) if cmd_rows else 0) + (cmd_note.get_height() + int(4 * u) if cmd_note else 0)
        prog_h += cmd_h
        w = max([int(12 * u) + port + int(12 * u) + max(s.get_width() for s in head) + int(16 * u),
                 cols * cell_w + int(24 * u), int(360 * u), 5 * (cell + gap) + int(24 * u)]
                + [e.get_width() + int(24 * u) for e in extra + ([cmd_note] if cmd_note else [])])
        top_h = max(port, sum(s.get_height() for s in head) + (int(30 * u) if hp else 0)) + int(16 * u)
        h = top_h + res_h + n_rows * row_h + prog_h + sum(e.get_height() for e in extra) + int(12 * u)
        r = pygame.Rect(int(10 * u), self.bottom - h - int(6 * u), w, h)
        self.panel(surf, r, (8, 10, 14, 225), border=(150, 135, 90))
        x = r.x + int(12 * u)
        y = r.y + int(8 * u)
        pr = pygame.Rect(x, y, port, port)
        pygame.draw.rect(surf, (30, 30, 30), pr)
        if icon is not None:
            surf.blit(pygame.transform.smoothscale(icon, (port, port)), pr)
        pygame.draw.rect(surf, info["rgb"], pr, max(1, int(2 * u)))
        tx = pr.right + int(12 * u)
        ty = y
        for s in head:
            surf.blit(s, (tx, ty))
            ty += s.get_height()
        if hp:
            cur, mx = hp
            bar = pygame.Rect(tx, ty + int(6 * u), r.right - tx - int(12 * u), int(14 * u))
            frac = max(0.0, min(1.0, cur / mx)) if mx else 0.0
            pygame.draw.rect(surf, (120, 25, 25), bar)
            b2 = bar.copy(); b2.width = int(bar.width * frac)
            pygame.draw.rect(surf, (50, 190, 60) if frac > 0.5 else (220, 190, 40) if frac > 0.25 else (220, 70, 40), b2)
            pygame.draw.rect(surf, (0, 0, 0), bar, 1)
            lost = max(0, int(round(mx - cur)))
            t = self.text(f"{int(round(cur))} / {int(mx)}" + (f"   (mất {lost})" if lost else ""), int(13 * u), WHITE, True)
            surf.blit(t, t.get_rect(center=bar.center))
        y = r.y + top_h
        if res:
            ic = self._stat_icon(res[0], int(22 * u))
            cx = r.x + int(12 * u)
            if ic is not None:
                surf.blit(ic, (cx, y + (row_h - ic.get_height()) // 2))
                cx += ic.get_width() + int(8 * u)
            t = self.text(res[1], int(17 * u), GOLD, True)
            surf.blit(t, (cx, y + (row_h - t.get_height()) // 2))
            y += row_h
        for k, (key, label, val) in enumerate(stats):
            cx = r.x + int(12 * u) + (k % cols) * cell_w
            cy = y + (k // cols) * row_h
            ic = self._stat_icon(key, int(22 * u)) if key else None
            if ic is not None:
                surf.blit(ic, (cx, cy + (row_h - ic.get_height()) // 2))
                lx = cx + ic.get_width() + int(6 * u)
            else:
                lt = self.text(label, int(14 * u), GREY)
                surf.blit(lt, (cx, cy + (row_h - lt.get_height()) // 2))
                lx = cx + lt.get_width() + int(8 * u)
            vt = self.text(val, fs, WHITE, True)
            surf.blit(vt, (lx, cy + (row_h - vt.get_height()) // 2))
        y += n_rows * row_h
        for label, frac, icon_id in progress:
            ic = self.tech_icon(icon_id, int(30 * u)) if self.tech_icon else None
            cx = r.x + int(12 * u)
            if ic is not None:
                surf.blit(ic, (cx, y + int(2 * u)))
                cx += ic.get_width() + int(8 * u)
            t = self.text(f"{label}  {int(frac * 100)}%", int(14 * u), WHITE)
            surf.blit(t, (cx, y))
            bar = pygame.Rect(cx, y + t.get_height() + int(2 * u), r.right - cx - int(12 * u), int(7 * u))
            pygame.draw.rect(surf, (50, 50, 50), bar)
            b2 = bar.copy(); b2.width = int(bar.width * frac)
            pygame.draw.rect(surf, GOLD, b2)
            y += int(36 * u)
        if queue:                                         # đang sinh: icon unit + số trong hàng + thanh tiến độ
            qi = int(44 * u)
            cx = r.x + int(12 * u)
            box = pygame.Rect(cx, y + int(2 * u), qi, qi)
            pygame.draw.rect(surf, (30, 30, 30), box)
            if queue.get("icon") is not None:
                surf.blit(pygame.transform.smoothscale(queue["icon"], (qi, qi)), box)
            pygame.draw.rect(surf, (150, 135, 90), box, 1)
            if queue["count"] > 1:                         # số trên góc icon như nút trong game
                ct = self.text(str(queue["count"]), int(16 * u), WHITE, True)
                surf.blit(ct, ct.get_rect(bottomright=(box.right - int(2 * u), box.bottom)))
            tx = box.right + int(10 * u)
            t = self.text(f"Đang sinh: {queue['name']}  {int(queue['frac'] * 100)}%", int(15 * u), WHITE, True)
            surf.blit(t, (tx, y + int(2 * u)))
            bar = pygame.Rect(tx, y + int(4 * u) + t.get_height(), r.right - tx - int(12 * u), int(7 * u))
            t2 = self.text(f"Hàng đợi: {queue['count']}", int(13 * u), GREY)
            surf.blit(t2, (tx, bar.bottom + int(2 * u)))
            pygame.draw.rect(surf, (50, 50, 50), bar)
            b2 = bar.copy(); b2.width = int(bar.width * queue["frac"])
            pygame.draw.rect(surf, (90, 200, 90), b2)
            y += int(52 * u)
        self.cmd_hits = []
        if cmd_rows:                                      # bảng lệnh 2 x 5 như trong game: nút b -> hàng (b-1)//5, cột (b-1)%5
            y += int(6 * u)
            x0 = r.x + int(12 * u)
            mouse = pygame.mouse.get_pos()
            for b, (kind, ic, label, cost) in cmd["slots"]:
                k = b - 1
                box = pygame.Rect(x0 + (k % 5) * (cell + gap), y + (k // 5) * (cell + gap), cell, cell)
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
            y += cmd_rows * (cell + gap) + int(4 * u)
        if cmd_note is not None:
            surf.blit(cmd_note, (r.x + int(12 * u), y))
            y += cmd_note.get_height() + int(4 * u)
        for e in extra:
            surf.blit(e, (r.x + int(12 * u), y))
            y += e.get_height()
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
