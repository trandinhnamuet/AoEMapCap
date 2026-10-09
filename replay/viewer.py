"""Cửa sổ xem replay: vòng lặp chính, máy quay, phím tắt kiểu replay LMHT, phát/tua theo dữ liệu .aoerec."""
import math
import os
import sys
import threading
import time
import traceback
from types import SimpleNamespace

import numpy as np

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402
import moderngl  # noqa: E402

from . import APP_NAME  # noqa: E402
from .data import Cursor, ReplayData  # noqa: E402
from .gpu import GPU  # noqa: E402
from .hud import Hud, fmt_ms, pil_to_surface  # noqa: E402
from .library import civ_name  # noqa: E402
from .world import TC_DAT_IDS, World, load_graphics  # noqa: E402

SPEEDS = [0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0]
FOG_DIM = 0.43             # độ sáng vùng sương mù (giống video: 43 %)
EDGE_PX = 6                # chuột cách mép cửa sổ <= 6 px thì cuộn máy quay
PAN_SPEED = 1500.0         # px màn hình / giây khi cuộn bằng mép hoặc phím mũi tên
ZOOM_MAX = 4.0
ZOOM_STEP = 1.25           # mỗi nấc lăn chuột
ZOOM_TAU = 0.07            # hằng số thời gian của zoom mượt (s)
FLY_TAU = 0.12
JUMP_MS = 15000            # Backspace / J: 15 giây giờ game
HUD_PERIOD = 0.1           # làm mới HUD khi đang phát (s)
DECODE_BUDGET = 0.008      # tối đa 8 ms giải mã sprite unit mới mỗi khung (phần còn lại để khung sau)
GAME_DIR_CANDIDATES = (r"C:\Program Files\XArena\Game\AoE-HD", r"D:\Game\AoE-HD")
SEL_KEYS_TEAM = ([pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5],
                 [pygame.K_q, pygame.K_w, pygame.K_e, pygame.K_r, pygame.K_t])
SEL_LABEL_TEAM = (["1", "2", "3", "4", "5"], ["Q", "W", "E", "R", "T"])
SEL_KEYS_FFA = [pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5, pygame.K_6, pygame.K_7, pygame.K_8]
PERSP_KEYS = {pygame.K_F1: 0, pygame.K_F2: 1, pygame.K_F4: 2, pygame.K_F5: 3, pygame.K_F6: 4, pygame.K_F7: 5, pygame.K_F8: 6}


def valid_game_dir(d):
    return bool(d) and os.path.exists(os.path.join(d, "data", "graphic.drs")) and \
        os.path.exists(os.path.join(d, "data", "empires.dat"))


def find_game_dir(hdr, explicit=None):
    meta = (hdr or {}).get("meta") or {}
    for d in (explicit, meta.get("game_dir"), *GAME_DIR_CANDIDATES):
        if valid_game_dir(d):
            return d
    return None


def _app_icon():
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(base, "assets", "app.ico")
    return p if os.path.exists(p) else None


def _dpi_aware():
    if sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:  # noqa: BLE001
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass


def message_box(text, title=APP_NAME):
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
            return
        except Exception:  # noqa: BLE001
            pass
    print(text, file=sys.stderr)


class Viewer:
    def __init__(self, path, game_dir=None, log=None, selftest=None):
        self.selftest = selftest     # thư mục ảnh: chạy kịch bản tự kiểm tra trên cửa sổ ẩn (không đụng chuột/phím)
        self.path = os.path.abspath(path)
        self.log = log or (lambda m: None)
        self.data = ReplayData(self.path)
        self.game_dir = find_game_dir(self.data.header, game_dir)
        if not self.game_dir:
            raise RuntimeError("Không tìm thấy thư mục game AoE-HD (cần data\\graphic.drs, data\\empires.dat) để lấy đồ hoạ.")
        self.cursor = Cursor(self.data)
        self.world = None
        self.world_err = None
        self.world_progress = 0.0
        self.hud = Hud()
        # phát lại
        self.r = 0.0
        self.playing = True
        self.speed_i = SPEEDS.index(1.0)
        # tầm nhìn: None = toàn bản đồ, k = đội k
        teams = self.data.teams
        rec = self.data.recorder_index()
        self.rec_team = next((k for k, t in enumerate(teams) if rec in t), 0 if teams else None)
        self.persp = self.rec_team         # mở replay theo góc nhìn đội của người ghi (F3 để xem toàn bản đồ)
        self.last_team = self.rec_team
        self.selected = None
        self.sel_unit = None         # uid unit đang xem thông tin
        # máy quay
        self.cx = self.cy = 0.0
        self.zoom = self.zoom_target = 0.1
        self.zoom_anchor = None
        self.fly = None
        self.drag = None             # (kiểu, điểm bắt đầu, đã kéo?)
        self.fullscreen = False
        # trạng thái dựng lại
        self._built_version = -1
        self._built_persp = object()
        self._static_si = -2
        self._hud_t = 0.0
        self._hud_dirty = True
        self._hud_surface = None
        self.toast = None
        self.toast_until = 0.0
        self.unit_rows = None
        self.inst = None
        self._events = None
        self._deferred = 0
        self._key_sel = {}
        self._hotkey_of = {}
        self._make_sel_keys()

    # ---- khởi tạo ---------------------------------------------------------------------
    def _make_sel_keys(self):
        teams = self.data.teams
        if len(teams) == 2:
            for k in range(2):
                for j, idx in enumerate(teams[k][:5]):
                    self._key_sel[SEL_KEYS_TEAM[k][j]] = idx
                    self._hotkey_of[idx] = SEL_LABEL_TEAM[k][j]
        else:
            for j, p in enumerate(self.data.real_players()[:8]):
                self._key_sel[SEL_KEYS_FFA[j]] = p.index
                self._hotkey_of[p.index] = str(j + 1)

    def _load_world(self):
        try:
            dat, store, pal = load_graphics(self.game_dir)
            w = World(self.data.header, dat, store, pal, log=self.log)
            w.build_terrain(progress=lambda f: setattr(self, "world_progress", 0.85 * f))
            w.build_index()
            self.world_progress = 1.0
            self.world = w
        except Exception as e:  # noqa: BLE001
            self.world_err = e
            self.log("lỗi dựng bản đồ: " + traceback.format_exc())

    def _init_window(self):
        _dpi_aware()
        pygame.init()
        pygame.display.set_caption(f"{APP_NAME} — {os.path.basename(self.path)}")
        ico = _app_icon()
        if ico:
            try:
                from PIL import Image
                im = Image.open(ico).convert("RGBA")
                pygame.display.set_icon(pygame.image.frombytes(im.tobytes(), im.size, "RGBA"))
            except Exception:  # noqa: BLE001
                pass
        try:
            dw, dh = pygame.display.get_desktop_sizes()[0]
        except Exception:  # noqa: BLE001
            dw, dh = 1920, 1080
        size = (int(dw * 0.85), int(dh * 0.85))
        flags = pygame.OPENGL | pygame.DOUBLEBUF | pygame.RESIZABLE
        if self.selftest:
            size, flags = (640, 360), pygame.OPENGL | pygame.DOUBLEBUF | pygame.HIDDEN
        try:
            pygame.display.set_mode(size, flags, vsync=1)
        except pygame.error:
            pygame.display.set_mode(size, flags)
        self.size = pygame.display.get_window_size()
        self.ctx = moderngl.create_context()
        self.fbo = self.ctx.screen
        if self.selftest:
            self.size = (1920, 1080)
            self.fbo = self.ctx.simple_framebuffer(self.size)
        self.gpu = GPU(self.ctx)
        self.log(f"OpenGL: {self.ctx.info.get('GL_RENDERER')} {self.ctx.info.get('GL_VERSION')}")
        self.hud.layout(self.size, 0.5)

    def _on_world_ready(self):
        w = self.world
        self.gpu.load_world(w)
        self.hud.layout(self.size, w.full_h / w.full_w)
        rv = w.resolver
        icons = rv._res_icons(64) or {}
        self.hud.icons = {k: pil_to_surface(v) for k, v in icons.items()}
        cache = {}

        def tech_icon(icon_id, size):
            key = (icon_id, size)
            if key not in cache:
                cache[key] = pil_to_surface(rv._tech_icon(icon_id, size))
            return cache[key]
        self.hud.tech_icon = tech_icon

        def slp_icon(sid, frame):
            s = rv._interfac_slp(sid)
            if s is None or not (0 <= frame < len(s.frames)):
                return None
            from PIL import Image
            rgba, _hx, _hy = s.decode(frame, w.pal)
            return pil_to_surface(Image.fromarray(rgba))
        self.hud.slp_icon = slp_icon
        self.fit_view()
        self.zoom = self.zoom_target
        self.set_toast("Nhấn Esc để xem phím tắt", 6.0)

    # ---- máy quay ----------------------------------------------------------------------
    def fit_zoom(self):
        w = self.world
        W, H = self.size
        return min(W / w.full_w, H / w.full_h) * 0.98

    def fit_view(self):
        w = self.world
        self.cx, self.cy = w.full_w / 2, w.full_h / 2
        self.zoom_target = self.fit_zoom()
        self.zoom_anchor = None
        self.fly = None

    def cam_tl(self, zoom=None, cx=None, cy=None):
        z = zoom or self.zoom
        W, H = self.size
        return (self.cx if cx is None else cx) - W / 2 / z, (self.cy if cy is None else cy) - H / 2 / z

    def screen_to_world(self, sx, sy):
        tx, ty = self.cam_tl()
        return tx + sx / self.zoom, ty + sy / self.zoom

    def zoom_at(self, factor, sx, sy):
        zmin = self.fit_zoom() * 0.9
        self.zoom_target = max(zmin, min(ZOOM_MAX, self.zoom_target * factor))
        self.zoom_anchor = (sx, sy) + self.screen_to_world(sx, sy)

    def _clamp_cam(self):
        w = self.world
        self.cx = max(0.0, min(float(w.full_w), self.cx))
        self.cy = max(0.0, min(float(w.full_h), self.cy))

    def _update_camera(self, dt):
        # zoom mượt giữ điểm dưới con trỏ
        if abs(self.zoom - self.zoom_target) > 1e-5 * self.zoom_target:
            a = 1.0 - math.exp(-dt / ZOOM_TAU)
            nz = self.zoom + (self.zoom_target - self.zoom) * a
            if abs(nz - self.zoom_target) < 1e-4 * self.zoom_target:
                nz = self.zoom_target
            if self.zoom_anchor is not None:
                sx, sy, wx, wy = self.zoom_anchor
                W, H = self.size
                self.cx = wx - sx / nz + W / 2 / nz
                self.cy = wy - sy / nz + H / 2 / nz
            self.zoom = nz
        # cuộn bằng phím mũi tên và mép màn hình
        vx = vy = 0.0
        keys = pygame.key.get_pressed()
        if keys[pygame.K_LEFT]:
            vx -= 1
        if keys[pygame.K_RIGHT]:
            vx += 1
        if keys[pygame.K_UP]:
            vy -= 1
        if keys[pygame.K_DOWN]:
            vy += 1
        if pygame.mouse.get_focused() and self.drag is None:
            mx, my = pygame.mouse.get_pos()
            W, H = self.size
            if mx <= EDGE_PX:
                vx -= 1
            elif mx >= W - 1 - EDGE_PX:
                vx += 1
            if my <= EDGE_PX:
                vy -= 1
            elif my >= H - 1 - EDGE_PX:
                vy += 1
        if vx or vy:
            sp = PAN_SPEED * (2.0 if (pygame.key.get_mods() & pygame.KMOD_SHIFT) else 1.0)
            self.cx += max(-1, min(1, vx)) * sp * dt / self.zoom
            self.cy += max(-1, min(1, vy)) * sp * dt / self.zoom
            self.fly = None
            self.zoom_anchor = None if self.zoom == self.zoom_target else self.zoom_anchor
        if self.fly is not None:
            a = 1.0 - math.exp(-dt / FLY_TAU)
            fx, fy = self.fly
            self.cx += (fx - self.cx) * a
            self.cy += (fy - self.cy) * a
            if abs(fx - self.cx) < 1 and abs(fy - self.cy) < 1:
                self.fly = None
        self._clamp_cam()

    def fly_to(self, wx, wy, zoom=None):
        self.fly = (wx, wy)
        self.zoom_anchor = None
        if zoom is not None:
            self.zoom_target = zoom

    # ---- người chơi -------------------------------------------------------------------
    def player_home(self, idx):
        """Toạ độ thế giới nhà chính (Town Center) của người chơi, hoặc trọng tâm unit."""
        U = self.cursor.state.units()
        if len(U) == 0:
            return None
        _, defs = self.data.def_arrays()
        di = np.clip(U["def"], 0, defs["n"] - 1)
        mine = (U["owner"] == idx) & (U["kind"] != 25)
        tc = mine & np.isin(defs["dat_id"][di], TC_DAT_IDS)
        sel = tc if tc.any() else mine
        if not sel.any():
            return None
        ax, ay = self.world.anchors(U[sel])
        if tc.any():
            return float(ax[0]), float(ay[0])
        return float(np.median(ax)), float(np.median(ay))

    def select_player(self, idx, jump=True):
        self.selected = idx
        self._hud_dirty = True
        p = self.data.players[idx]
        self.set_toast(f"Đang chọn: {p.name}")
        if jump:
            home = self.player_home(idx)
            if home is not None:
                self.fly_to(*home, zoom=max(self.zoom_target, 0.6))

    def set_toast(self, text, secs=1.6):
        self.toast = text
        self.toast_until = time.time() + secs
        self._hud_dirty = True

    def persp_label(self):
        if self.persp is None:
            return "Tầm nhìn: toàn bản đồ"
        team = self.data.teams[self.persp]
        names = ", ".join(self.data.players[i].name for i in team[:3]) + ("…" if len(team) > 3 else "")
        return f"Tầm nhìn: Đội {self.persp + 1} ({names})"

    def set_persp(self, p):
        if p is not None and not (0 <= p < len(self.data.teams)):
            return
        self.persp = p
        if p is not None:
            self.last_team = p
        self.set_toast(self.persp_label())

    # ---- phát lại ---------------------------------------------------------------------
    def speed(self):
        return SPEEDS[self.speed_i]

    def speed_label(self):
        s = self.speed()
        return f"x{s:g}".replace(".", ",")

    def seek_r(self, r):
        d = self.data
        if d.n_frames == 0:
            return
        self.r = max(0.0, min(r, d.f_r[d.n_frames - 1]))
        self._hud_dirty = True

    def jump_game_ms(self, delta):
        d = self.data
        n = d.n_frames
        if n == 0:
            return
        fi = max(0, min(n - 1, self.cursor.frame))
        t = d.f_t[fi] + delta
        nf = d.frame_at_game_ms(t)
        self.seek_r(d.f_r[nf])
        self.set_toast(("Lùi" if delta < 0 else "Tiến") + f" {abs(delta) // 1000} giây")

    def _advance(self, dt):
        d = self.data
        n = d.n_frames
        if n == 0:
            return
        end = d.f_r[n - 1]
        if self.playing:
            self.r += dt * self.speed()
            if self.r >= end:
                self.r = end
                if d.done:
                    self.playing = False
                    self._hud_dirty = True
        fi = d.frame_at_r(self.r)
        self.cursor.seek(fi)

    # ---- dựng lại dữ liệu vẽ -------------------------------------------------------------
    def _team_masks(self, k):
        vm = em = 0
        for i in self.data.teams[k]:
            p = self.data.players[i]
            vm |= p.visible_mask
            em |= p.explored_mask
        return vm, em

    def _rebuild(self):
        w = self.world
        st = self.cursor.state
        if st.vis is None:
            return
        d = self.data
        _, defs = d.def_arrays()
        V = st.vis
        if self.persp is None:
            fog = np.full(V.shape, 255, np.uint8)
            visT = expT = None
        else:
            vm, em = self._team_masks(self.persp)
            vis = (V & np.uint32(vm)) != 0
            exp = vis | ((V & np.uint32(em)) != 0) | bool(d.header.get("reveal"))
            fog = np.where(vis, 255, np.where(exp, int(round(FOG_DIM * 255)), 0)).astype(np.uint8)
        self.gpu.set_fog(fog)
        # vật thể tĩnh (cây, mỏ...): chỉ dựng lại khi bản ghi tĩnh đổi
        si, _ver, S = self.cursor.statics()
        if si != self._static_si:
            self._static_si = si
            if len(S):
                tx, ty, inside = w.tile_of(S)
                di = np.clip(S["def"], 0, defs["n"] - 1)
                ut = defs["utype"][di]
                keep = inside & (S["kind"] != 25) & ~((ut == 60) & (S["gid"] < 0))
                S = S[keep]
                S = S[w.depth_order(S)]
            slot, x0, y0, br, sui = w.instances(S, defs, -np.ones(len(S), np.float32))
            self.gpu.set_statics(slot, x0, y0, br)
            self.static_rows = S
            self.static_inst = (slot, x0, y0, sui)
        # unit
        U = st.units()
        if len(U):
            tx, ty, inside = w.tile_of(U)
            di = np.clip(U["def"], 0, defs["n"] - 1)
            ut = np.where(U["def"] < defs["n"], defs["utype"][di], -1)
            fogvis = defs["fogvis"][di]
            keep = inside & ~((ut == 60) & (U["gid"] < 0))
            k25 = U["kind"] == 25
            if self.persp is None:
                keep &= ~k25
                bright = np.ones(len(U), np.float32)
            else:
                vT = vis[ty, tx]
                eT = exp[ty, tx]
                if self.persp == self.rec_team:
                    # bản ghi nhớ sương mù của game (doppelganger): vẽ thay vật thể thật ở ô đó
                    dop = k25 & (ut != 25) & ~vT & inside
                    D = np.zeros(V.shape, bool)
                    D[ty[dop], tx[dop]] = True
                    normal = ~k25 & (vT | (eT & fogvis & ~D[ty, tx]))
                    keep &= dop | normal
                else:
                    # không có bản ghi nhớ của đội này: công trình trong vùng đã khám phá vẽ mờ (gần đúng)
                    keep &= ~k25 & (vT | (eT & (fogvis | (ut == 80))))
                bright = np.where(vT & ~k25, 1.0, FOG_DIM).astype(np.float32)
            U, bright, ut = U[keep], bright[keep], ut[keep]
            order = w.depth_order(U)
            U, bright, ut = U[order], bright[order], ut[order]
        else:
            bright = np.zeros(0, np.float32)
            ut = np.zeros(0, np.int16)
        slot, x0, y0, br, ui = w.instances(U, defs, bright, budget=DECODE_BUDGET)
        self.gpu.set_units(slot, x0, y0, br)
        self._deferred = w.deferred
        self.unit_rows = U
        self.inst = (slot, x0, y0, ui)
        # minimap: chấm màu người chơi
        own = (U["owner"] > 0) if len(U) else np.zeros(0, bool)
        if own.any():
            Ud = U[own]
            ax, ay = w.anchors(Ud)
            ay = ay - 16.0
            cols = np.array([w.player_rgb(int(o)) + (255,) for o in range(len(w.color_lut))], np.float32) / 255.0
            c = cols[np.clip(Ud["owner"], 0, len(cols) - 1)].copy()
            c[:, 3] = np.where(bright[own] >= 1.0, 1.0, 0.55)
            half = np.where(ut[own] == 80, 2.6, 1.6).astype(np.float32)
            self.gpu.set_dots(np.stack([ax, ay], 1), half, c)
        else:
            self.gpu.set_dots(np.zeros((0, 2), np.float32), np.zeros(0, np.float32), np.zeros((0, 4), np.float32))

    # ---- chọn unit ---------------------------------------------------------------------
    def _pick_in(self, inst, rows, wx, wy):
        if inst is None or rows is None or not len(inst[0]):
            return None
        slot, x0, y0, ui = inst
        atlas = self.gpu.atlas
        ok = (slot >= 0) & (slot < len(atlas.size))
        sz = atlas.size[np.clip(slot, 0, max(len(atlas.size) - 1, 0))]
        hit = ok & (x0 <= wx) & (wx < x0 + sz[:, 0]) & (y0 <= wy) & (wy < y0 + sz[:, 1])
        store = self.world.store
        for j in np.nonzero(hit)[0][::-1].tolist():
            im = store.frame(*self.world.slot_keys[int(slot[j])])[0]
            px, py = int(wx - x0[j]), int(wy - y0[j])
            if 0 <= px < im.width and 0 <= py < im.height and im.getpixel((px, py))[3] > 0:
                return int(rows[ui[j]]["uid"])
        return None

    def pick_unit(self, sx, sy):
        """Unit dưới con trỏ: ('u', uid) cho unit, ('s', uid) cho vật thể tĩnh (cây, mỏ), hoặc None."""
        if self.world is None:
            return None
        wx, wy = self.screen_to_world(sx, sy)
        uid = self._pick_in(self.inst, self.unit_rows, wx, wy)
        if uid is not None:
            return ("u", uid)
        uid = self._pick_in(getattr(self, "static_inst", None), getattr(self, "static_rows", None), wx, wy)
        return ("s", uid) if uid is not None else None

    def _selected_row(self):
        """Bản ghi (np.void) của unit đang chọn tại mẫu hiện tại, hoặc None."""
        if self.sel_unit is None:
            return None
        kind, uid = self.sel_unit
        if kind == "u":
            st = self.cursor.state
            i = st.pos.get(uid)
            return st.arr[i] if i is not None and st.valid[i] else None
        _si, _ver, S = self.cursor.statics()
        k = np.nonzero(S["uid"] == uid)[0] if len(S) else []
        return S[int(k[0])] if len(k) else None

    def _unit_name(self, dfi, stats):
        w = self.world
        du = w.dat.units.get(dfi.dat_id) if dfi is not None else None
        strings = getattr(w.resolver, "strings", None)
        for sid in ((stats or {}).get("lang"), du.lang_name if du is not None else None):
            if sid and sid > 0 and strings is not None:
                v = strings.get(sid)
                if v:
                    return v
        if du is not None and du.name:
            return du.name.replace("_", " ")
        return dfi.name if dfi is not None and dfi.name else "?"

    @staticmethod
    def _fmt_num(v):
        return f"{v:.1f}".rstrip("0").rstrip(".").replace(".", ",") if isinstance(v, float) else str(v)

    def _unit_info(self):
        """Thông tin unit đang chọn, như bảng thông tin trong game."""
        if self.sel_unit is None or self.world is None:
            return None
        u = self._selected_row()
        if u is None:
            return {"name": "(unit không còn)", "owner": "", "rgb": (200, 200, 200), "stats": [], "lines": [],
                    "hp": None, "icon": None}
        w = self.world
        def_idx = int(u["def"])
        dfi = self.data.defs.get(def_idx)
        stats = self.data.stats_at(def_idx, max(self.cursor.frame, 0))
        owner = int(u["owner"])
        p = self.data.players[owner] if 0 <= owner < len(self.data.players) else None
        hp = float(u["hp"])
        hp_max = float((stats or {}).get("hp") or (dfi.hp_max if dfi else 0) or 0)
        utype = dfi.utype if dfi is not None else 0
        rows = []
        lines = []
        if stats is not None and "attacks" in stats:
            atk = max([a for _c, a in stats["attacks"]] + [0])
            pierce_atk = [a for c, a in stats["attacks"] if c == 3]
            melee = max([stats.get("armor0", 0)] + [a for c, a in stats.get("armors", []) if c != 3])
            pierce = max([0] + [a for c, a in stats.get("armors", []) if c == 3])

            def plus(cur, base):
                return f"{self._fmt_num(base)}+{self._fmt_num(cur - base)}" if base is not None and cur > base else self._fmt_num(cur)
            if atk > 0:
                rows.append(("attack", "Công", plus(atk, stats.get("d_attack") if stats.get("d_attack", 0) > 0 else None)))
            rows.append(("armor", "Giáp", plus(melee, stats.get("d_melee"))))
            if pierce or pierce_atk or "d_pierce" in stats:
                rows.append(("pierce", "Giáp xuyên", plus(pierce, stats.get("d_pierce"))))
            rng = stats.get("range", 0) or 0
            if rng >= 1.0:
                rows.append(("range", "Tầm", plus(round(rng, 1), round(stats.get("d_range") or 0, 1) or None)))
            if atk > 0 and stats.get("reload"):
                rows.append(("reload", "Tốc đánh", f"{self._fmt_num(round(stats['reload'], 2))} giây"))
        if stats is not None:
            if stats.get("speed"):
                rows.append((None, "Tốc chạy", self._fmt_num(round(stats["speed"], 2))))
            if stats.get("los"):
                rows.append((None, "Tầm nhìn", self._fmt_num(round(stats["los"], 1))))
            if stats.get("accuracy") and stats.get("range", 0) >= 1.0:
                rows.append((None, "Chính xác", f"{stats['accuracy']}%"))
        elif utype in (50, 60, 70, 80):
            lines.append("Công/giáp chỉ có ở trận ghi từ 09/10/2026")
        # tài nguyên còn lại (cây, xác thú, bụi quả, ruộng, mỏ) / đang mang (dân) — file từ 2026-10-09
        res = None
        if "rtype" in (u.dtype.names or ()) and int(u["rtype"]) in (0, 1, 2, 3):
            amt = float(u["ramount"])
            kind_name = {0: "thực", 1: "gỗ", 2: "đá", 3: "vàng"}[int(u["rtype"])]
            carrier = utype == 70
            if carrier:
                if amt >= 0.5:
                    res = ("res%d" % int(u["rtype"]), f"Đang mang {int(amt)} {kind_name}")
            else:
                res = ("res%d" % int(u["rtype"]), f"Còn lại {int(amt)} {kind_name}")
        progress = []
        if utype == 80 and p is not None and int(u["status"]) == 2:
            pl = self.data.players_at(self.cursor.state)[owner]
            research = getattr(self.world.dat, "research", None) or []
            for tid, sec in sorted((pl.researching or {}).items()):
                if 0 <= tid < len(research) and research[tid].location == dfi.dat_id and research[tid].time > 0:
                    r = research[tid]
                    progress.append((f"Nghiên cứu: {self.world.resolver._tech_label(r)}",
                                     max(0.0, min(1.0, sec / r.time)), r.icon))
        if int(u["kind"]) == 25:
            lines.append("Hình ghi nhớ trong sương mù")
        elif int(u["status"]) >= 3 or hp <= 0:
            lines.append("Đã chết / đã cạn")
        elif int(u["status"]) == 0 and utype == 80:
            lines.append(f"Đang xây: {int(100 * max(hp, 0) / hp_max) if hp_max else 0}%")
        civ = civ_name(p.civ) if p is not None and p.civ and p.civ > 0 else ""
        owner_txt = (p.name if p and owner > 0 else "Gaia") + (f"  ·  {civ}" if civ and owner > 0 else "")
        return {"name": self._unit_name(dfi, stats), "owner": owner_txt,
                "rgb": w.player_rgb(owner) if owner > 0 else (200, 200, 200), "stats": rows, "lines": lines,
                "res": res, "progress": progress,
                "hp": (max(hp, 0.0), hp_max) if hp_max > 0 else None,
                "icon": self._unit_icon(dfi, owner)}

    def _unit_icon(self, dfi, owner):
        """Icon chân dung của unit/công trình (interfac.drs: 50730 unit, 50704..50707 công trình theo đời)."""
        if dfi is None:
            return None
        du = self.world.dat.units.get(dfi.dat_id)
        if du is None or du.icon_id is None or du.icon_id < 0:
            return None
        cache = self.__dict__.setdefault("_icon_cache", {})
        age = 1
        if dfi.utype == 80 and 0 < owner < len(self.data.players):
            st = self.cursor.state.pstate.get(owner)
            if st and len(st[0]) > 6:
                age = int(st[0][6])
        sid = 50704 + max(0, min(3, age - 1)) if dfi.utype == 80 else 50730
        cid = int(self.world.color_lut[owner]) if 0 < owner < len(self.world.color_lut) else 0
        key = (sid, du.icon_id, cid)
        if key not in cache:
            im = None
            s = self.world.resolver._interfac_slp(sid)
            if s is not None and 0 <= du.icon_id < len(s.frames):
                try:
                    from PIL import Image
                    rgba, _hx, _hy = s.decode(du.icon_id, self.world.pal, cid)
                    if rgba.shape[0] > 2:
                        im = pil_to_surface(Image.fromarray(rgba))
                except Exception:  # noqa: BLE001
                    im = None
            cache[key] = im
        return cache[key]

    # ---- HUD ---------------------------------------------------------------------------
    def _hud_model(self):
        d = self.data
        loading = None
        if self.world is None:
            loading = [("Đang dựng bản đồ từ đồ hoạ game…", self.world_progress),
                       ("Đang lập chỉ mục dữ liệu trận…", d.progress())]
            if self.world_err is not None:
                loading = [(f"Lỗi dựng bản đồ: {self.world_err}", 0.0)]
        st = self.cursor.state
        fi = max(0, st.frame)
        n = d.n_frames
        m = SimpleNamespace(loading=loading, toast=self.toast if time.time() < self.toast_until else None)
        if loading is not None:
            return m
        m.time_ms = d.f_t[fi] if n else 0
        m.total_ms = d.f_t[n - 1] if n else 0
        m.r = self.r
        m.duration = d.f_r[n - 1] if n else 0.0
        if not d.done and n:
            m.indexed = d.progress()
            m.duration = max(m.duration / max(m.indexed, 1e-3), m.duration)
        else:
            m.indexed = 1.0
        m.paused = not self.playing
        m.speed_label = self.speed_label()
        m.persp_label = self.persp_label() + ("" if d.done else f"   ·   lập chỉ mục {int(d.progress() * 100)}%")
        m.hover_ms = None
        if self.hud.hover_timeline is not None and n:
            r = self.hud.hover_timeline * m.duration
            m.hover_ms = d.f_t[d.frame_at_r(r)]
        if self._events is None and d.done and self.world is not None:
            self._events = [(r, self.world.player_rgb(i), age) for r, i, age in d.age_events()]
        m.events = self._events or []
        players = d.players_at(st)
        U = st.units()
        vill = np.zeros(len(players) + 1, np.int64)
        if len(U):
            _, defs = d.def_arrays()
            di = np.clip(U["def"], 0, defs["n"] - 1)
            alive = (U["kind"] != 25) & (U["status"] < 3) & (U["hp"] > 0)
            v = alive & (defs["utype"][di] == 70) & (defs["cls"][di] == 4)
            if v.any():
                cnt = np.bincount(np.clip(U["owner"][v], 0, len(players)), minlength=len(players) + 1)
                vill[:len(cnt)] = cnt[:len(vill)]
        rv = self.world.resolver
        research = getattr(rv.dat, "research", None) or []
        rows = {}
        for p in players:
            if p.index == 0 or not (p.addr or p.pid):
                continue
            a = p.attr
            kills = a(20)
            ratio = a(44)
            ntech = None
            if p.techs is not None:
                ntech = sum(1 for t in p.techs if t < len(research) and research[t].researchable)
            rows[p.index] = {"index": p.index, "name": p.name, "civ": civ_name(p.civ) if p.civ and p.civ > 0 else "",
                             "rgb": self.world.player_rgb(p.index), "attrs": p.attrs or (), "pop": a(11),
                             "room": a(4), "age": a(6), "vill": int(vill[p.index]), "army": a(40), "kills": kills,
                             "deaths": (kills - ratio) if kills is not None and ratio is not None else None,
                             "razings": a(43), "ntech": ntech, "gold_mined": a(49),
                             "tribute": max(a(53), 0) if a(53) is not None else None,
                             "hotkey": self._hotkey_of.get(p.index),
                             "status": {1: "thắng", 2: "đầu hàng" if p.resigned else "thua"}.get(p.ptype)}
        m.teams = [[rows[i] for i in t if i in rows] for t in d.teams]
        m.selected = self.selected
        m.sel_player = rows.get(self.selected)
        m.game_over = bool(st.go)
        m.techs = []
        m.researching = []
        if self.selected is not None:
            p = players[self.selected]
            for tid, sec in sorted((p.researching or {}).items()):
                if 0 <= tid < len(research) and research[tid].time > 0:
                    m.researching.append((rv._tech_label(research[tid]), max(0.0, min(1.0, sec / research[tid].time)),
                                          research[tid].icon))
            if p.techs is not None:
                items = []
                for tid in p.techs:
                    if tid < len(research) and research[tid].researchable:
                        items.append((p.tech_times.get(tid, m.time_ms), rv._tech_label(research[tid]), research[tid].icon))
                m.techs = sorted(items)
        m.unit_info = self._unit_info()
        return m

    def _draw_hud(self, force=False):
        now = time.time()
        if force or self._hud_dirty or self._hud_surface is None or (now - self._hud_t >= HUD_PERIOD and
                                                                     (self.playing or self.world is None)) \
                or (self.toast and now >= self.toast_until):
            if self.toast and now >= self.toast_until:
                self.toast = None
            surf = self.hud.render(self._hud_model())
            self._hud_surface = pygame.image.tobytes(surf, "RGBA")
            self._hud_t = now
            self._hud_dirty = False
            changed = True
        else:
            changed = False
        self.gpu.draw_hud(self._hud_surface, self.size, changed)

    # ---- vẽ ------------------------------------------------------------------------------
    def _render(self):
        ctx = self.ctx
        W, H = self.size
        self.fbo.use()
        ctx.viewport = (0, 0, W, H)
        ctx.clear(0.0, 0.0, 0.0, 1.0)
        if self.world is not None and self.gpu.terrain_vao is not None:
            self.gpu.draw_world(self.cam_tl(), self.zoom, (W, H))
            self._draw_selection()
        self._draw_hud()
        mm = self.hud.minimap_rect() if self.world is not None else None
        if mm is not None:
            w = self.world
            mz = min(mm.w / w.full_w, mm.h / w.full_h)
            tlx = w.full_w / 2 - mm.w / 2 / mz
            tly = w.full_h / 2 - mm.h / 2 / mz
            ctx.viewport = (mm.x, H - mm.y - mm.h, mm.w, mm.h)
            self.gpu.draw_world((tlx, tly), mz, (mm.w, mm.h), outline_alpha=0.5, statics=False, units=False)
            self.gpu.draw_dots()
            ax, ay = self.cam_tl()
            bx, by = ax + W / self.zoom, ay + H / self.zoom
            self.gpu.draw_lines([(ax, ay), (bx, ay), (bx, by), (ax, by)], (1, 1, 1, 0.9), loop=True)
            ctx.viewport = (0, 0, W, H)

    def _draw_selection(self):
        """Hình thoi màu người chơi dưới chân unit đang chọn (như vòng chọn trong game)."""
        u = self._selected_row() if self.sel_unit is not None else None
        if u is None:
            return
        ax, ay = self.world.anchors(np.array([u], dtype=u.dtype))
        ax, ay = float(ax[0]), float(ay[0])
        dfi = self.data.defs.get(int(u["def"]))
        du = self.world.dat.units.get(dfi.dat_id) if dfi is not None else None
        r = max(0.25, min(3.0, float(max(du.radius_x, du.radius_y)) if du is not None else 0.3))
        hx, hy = 32.0 * r * 1.6, 16.0 * r * 1.6
        owner = int(u["owner"])
        rgb = self.world.player_rgb(owner) if owner > 0 else (230, 230, 230)
        col = tuple(c / 255 for c in rgb) + (1.0,)
        z = max(self.zoom, 1e-3)
        for k in range(3):                       # 3 nét lồng nhau ~ 1 px màn hình mỗi nét: vòng chọn dày, dễ thấy
            e = k / z
            self.gpu.draw_lines([(ax - hx - 2 * e, ay), (ax, ay - hy - e), (ax + hx + 2 * e, ay), (ax, ay + hy + e)],
                                col, loop=True)

    # ---- sự kiện -------------------------------------------------------------------------
    def _minimap_to_world(self, pos):
        mm = self.hud.minimap_rect()
        w = self.world
        mz = min(mm.w / w.full_w, mm.h / w.full_h)
        tlx = w.full_w / 2 - mm.w / 2 / mz
        tly = w.full_h / 2 - mm.h / 2 / mz
        return tlx + (pos[0] - mm.x) / mz, tly + (pos[1] - mm.y) / mz

    def _timeline_seek(self, x):
        bar = self.hud.r_timeline
        if bar is None:
            return
        frac = max(0.0, min(1.0, (x - bar.x) / max(1, bar.w)))
        m_dur = self.data.duration()
        if not self.data.done:
            m_dur = m_dur / max(self.data.progress(), 1e-3)
        self.seek_r(frac * m_dur)

    def toggle_fullscreen(self):
        """Toàn màn hình kiểu 'desktop' (không đổi độ phân giải, không mất ngữ cảnh OpenGL); giữ chuột trong cửa sổ
        để cuộn bằng mép màn hình chạy cả khi có nhiều màn hình."""
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                win = pygame.Window.from_display_module()
            if self.fullscreen:
                win.set_windowed()
                win.mouse_grabbed = False
            else:
                win.set_fullscreen(desktop=True)
                win.mouse_grabbed = True
            self.fullscreen = not self.fullscreen
        except Exception as e:  # noqa: BLE001
            self.log(f"không đổi được chế độ toàn màn hình: {e}")
        self._on_resize()

    def _on_resize(self):
        if not self.selftest:
            self.size = pygame.display.get_window_size()
        aspect = (self.world.full_h / self.world.full_w) if self.world else 0.5
        self.hud.layout(self.size, aspect)
        self._hud_dirty = True

    def _key(self, ev):
        k = ev.key
        mods = ev.mod
        hud = self.hud
        if k == pygame.K_RETURN and (mods & pygame.KMOD_ALT) or k == pygame.K_F11:
            self.toggle_fullscreen()
        elif k == pygame.K_ESCAPE:
            hud.show_help = not hud.show_help         # Esc: bảng phím tắt (thoát toàn màn hình bằng F11 / Alt+Enter)
        elif k == pygame.K_p:
            self.playing = not self.playing
            if self.playing and self.data.n_frames and self.r >= self.data.f_r[-1] and self.data.done:
                self.r = 0.0
        elif k in (pygame.K_MINUS, pygame.K_KP_MINUS, pygame.K_UNDERSCORE):
            self.speed_i = max(0, self.speed_i - 1)
            self.set_toast(f"Tốc độ {self.speed_label()}")
        elif k in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
            self.speed_i = min(len(SPEEDS) - 1, self.speed_i + 1)
            self.set_toast(f"Tốc độ {self.speed_label()}")
        elif k in (pygame.K_0, pygame.K_KP0):
            self.speed_i = SPEEDS.index(1.0)
            self.set_toast("Tốc độ x1")
        elif k == pygame.K_BACKSPACE:
            self.jump_game_ms(-JUMP_MS)
        elif k == pygame.K_j:
            self.jump_game_ms(JUMP_MS)
        elif k == pygame.K_F3:
            self.set_persp(None)
        elif k in PERSP_KEYS:
            self.set_persp(PERSP_KEYS[k])
        elif k == pygame.K_v:
            seq = [None] + list(range(len(self.data.teams)))
            i = seq.index(self.persp) if self.persp in seq else 0
            self.set_persp(seq[(i + 1) % len(seq)])
        elif k == pygame.K_f:
            self.set_persp(self.last_team if self.persp is None else None)
        elif k == pygame.K_SPACE:
            if self.selected is not None:
                home = self.player_home(self.selected)
                if home is not None:
                    self.fly_to(*home)
        elif k in self._key_sel and not (mods & (pygame.KMOD_CTRL | pygame.KMOD_ALT)):
            self.select_player(self._key_sel[k])
        elif k == pygame.K_o:
            hud.show_score = not hud.show_score
        elif k == pygame.K_x:
            hud.score_mode = 1 - hud.score_mode
            hud.show_score = True
        elif k == pygame.K_c:
            hud.show_techs = not hud.show_techs
            if hud.show_techs and self.selected is None and self.data.teams:
                self.selected = self.data.teams[self.rec_team or 0][0]
        elif k == pygame.K_u:
            hud.show_timeline = not hud.show_timeline
            self._on_resize()
        elif k == pygame.K_h:
            hud.show_hud = not hud.show_hud
            self._on_resize()
        elif k == pygame.K_m:
            hud.show_minimap = not hud.show_minimap
        elif k in (pygame.K_SLASH, pygame.K_QUESTION) or ev.unicode == "?":
            hud.show_help = not hud.show_help
        elif k == pygame.K_HOME:
            self.fit_view()
        self._hud_dirty = True

    def _mouse_down(self, ev):
        hud = self.hud
        pos = ev.pos
        if hud.show_help:
            hud.show_help = False
            self._hud_dirty = True
            return
        if ev.button == 1:
            if hud.r_help is not None and hud.r_help.collidepoint(pos):
                hud.show_help = True
                self._hud_dirty = True
                return
            if hud.r_play is not None and hud.r_play.collidepoint(pos):
                self.playing = not self.playing
                self._hud_dirty = True
                return
            if hud.r_timeline is not None and hud.r_timeline.collidepoint(pos):
                self.drag = ("timeline", pos, True)
                self._timeline_seek(pos[0])
                return
            for r, idx in hud.score_rows:
                if r.collidepoint(pos):
                    self.select_player(idx)
                    return
        mm = hud.minimap_rect()
        if mm is not None and mm.collidepoint(pos) and ev.button in (1, 3):
            self.drag = ("minimap", pos, True)
            self.cx, self.cy = self._minimap_to_world(pos)
            self.fly = None
            self.zoom_anchor = None
            return
        if ev.button in (1, 2, 3):
            self.drag = ("world", pos, False, ev.button)

    def _mouse_up(self, ev):
        d = self.drag
        self.drag = None
        if d is None:
            return
        if d[0] == "world" and not d[2]:
            if d[3] == 1:
                self.sel_unit = self.pick_unit(*ev.pos)
                self._hud_dirty = True
            elif d[3] == 2:
                self.fit_view()

    def _mouse_motion(self, ev):
        hud = self.hud
        bar = hud.r_timeline
        hov = None
        if bar is not None and bar.collidepoint(ev.pos):
            hov = max(0.0, min(1.0, (ev.pos[0] - bar.x) / max(1, bar.w)))
        if hov != hud.hover_timeline:
            hud.hover_timeline = hov
            self._hud_dirty = True
        d = self.drag
        if d is None:
            return
        if d[0] == "timeline":
            self._timeline_seek(ev.pos[0])
        elif d[0] == "minimap":
            self.cx, self.cy = self._minimap_to_world(ev.pos)
            self._clamp_cam()
        elif d[0] == "world":
            if not d[2]:
                if abs(ev.pos[0] - d[1][0]) + abs(ev.pos[1] - d[1][1]) < 5:
                    return
                self.drag = ("world", d[1], True, d[3])
            self.cx -= ev.rel[0] / self.zoom
            self.cy -= ev.rel[1] / self.zoom
            self.fly = None
            self.zoom_anchor = None
            self._clamp_cam()

    # ---- vòng lặp ------------------------------------------------------------------------
    def run(self):
        self._init_window()
        self.data.start_index()
        threading.Thread(target=self._load_world, name="replay-world", daemon=True).start()
        clock = pygame.time.Clock()
        running = True
        ready = False
        t_prev = time.perf_counter()
        while running:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = False
                elif ev.type in (pygame.VIDEORESIZE, pygame.WINDOWSIZECHANGED):
                    self._on_resize()
                elif not ready:
                    continue
                elif ev.type == pygame.KEYDOWN:
                    self._key(ev)
                elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button in (1, 2, 3):
                    self._mouse_down(ev)
                elif ev.type == pygame.MOUSEBUTTONUP and ev.button in (1, 2, 3):
                    self._mouse_up(ev)
                elif ev.type == pygame.MOUSEMOTION:
                    self._mouse_motion(ev)
                elif ev.type == pygame.MOUSEWHEEL:
                    mx, my = pygame.mouse.get_pos()
                    mm = self.hud.minimap_rect()
                    if mm is None or not mm.collidepoint((mx, my)):
                        step = ev.precise_y if getattr(ev, "precise_y", 0) else ev.y
                        self.zoom_at(ZOOM_STEP ** step, mx, my)
            now = time.perf_counter()
            dt = min(0.1, now - t_prev)
            t_prev = now
            ready = self._tick(dt, ready)
            pygame.display.flip()
            clock.tick(240)
        self.data.close()
        pygame.quit()

    def _tick(self, dt, ready):
        if not ready and self.world is not None and self.data.n_frames > 0:
            self._on_world_ready()
            ready = True
        if ready:
            self._advance(dt)
            self._update_camera(dt)
            if self.cursor.version != self._built_version or self.persp != self._built_persp or self._deferred:
                self._rebuild()
                self._built_version = self.cursor.version
                self._built_persp = self.persp
                if not self.playing:
                    self._hud_dirty = True
        self._render()
        return ready

    # ---- tự kiểm tra (cửa sổ ẩn, vẽ vào framebuffer riêng, lưu ảnh) -----------------------------
    def _shot(self, name):
        from PIL import Image
        self.ctx.finish()
        data = self.fbo.read(components=3)
        im = Image.frombytes("RGB", self.size, data).transpose(Image.FLIP_TOP_BOTTOM)
        p = os.path.join(self.selftest, f"replay_{name}.png")
        im.save(p)
        self.log(f"ảnh {p}")

    def _settle(self, n=40, dt=1 / 60):
        for _ in range(n):
            self._tick(dt, True)

    def run_selftest(self):
        os.makedirs(self.selftest, exist_ok=True)
        self._init_window()
        self.data.start_index()
        t0 = time.time()
        self._load_world()
        self.log(f"dựng bản đồ {time.time() - t0:.1f} s; chờ lập chỉ mục...")
        while not self.data.done:
            time.sleep(0.2)
        self.log(f"lập chỉ mục xong {self.data.n_frames} mẫu")
        self._tick(0.0, False)
        d = self.data
        self.playing = False
        self.seek_r(d.duration() * 0.6)
        self._settle()
        self._shot("0_mac_dinh_doi_nguoi_ghi")
        self.set_persp(None)
        self._settle()
        self._shot("1_toan_ban_do")
        self.set_persp(0)
        self._settle()
        self._shot("2_doi1")
        self.set_persp(1 if len(d.teams) > 1 else 0)
        self._settle()
        self._shot("3_doi2")
        self.set_persp(None)
        first = d.teams[0][0]
        self.select_player(first)
        self.hud.show_techs = True
        self.fly = None
        home = self.player_home(first)
        if home:
            self.cx, self.cy = home
        self.zoom = self.zoom_target = 1.0
        self._settle()
        self._shot("4_zoom1_nha_chinh")
        self.zoom = self.zoom_target = 3.0
        self.hud.score_mode = 1
        self._hud_dirty = True
        self._settle()
        self._shot("5_zoom3_quan_su")
        self.hud.show_help = True
        self._hud_dirty = True
        self._settle(5)
        self._shot("6_tro_giup")
        self.hud.show_help = False
        # bảng thông tin unit: chọn một unit của người chơi (ưu tiên quân/dân) gần nhà chính
        U = self.unit_rows
        if U is not None and len(U):
            _, defs = d.def_arrays()
            ut = defs["utype"][np.clip(U["def"], 0, defs["n"] - 1)]
            cand = np.nonzero((U["owner"] > 0) & (ut == 70) & (U["kind"] != 25))[0]
            if len(cand):
                pick = U[int(cand[len(cand) // 2])]
                self.sel_unit = ("u", int(pick["uid"]))
                ax, ay = self.world.anchors(np.array([pick], dtype=pick.dtype))
                self.cx, self.cy = float(ax[0]), float(ay[0])
                self.zoom = self.zoom_target = 2.0
                self.hud.show_score = False
                self._hud_dirty = True
                self._settle(10)
                self._shot("8_thong_tin_unit")
                # nhà chính của người ghi (tiến độ nghiên cứu) và một cây (gỗ còn lại)
                rec = d.recorder_index()
                tc = np.nonzero((U["owner"] == rec) & np.isin(defs["dat_id"][np.clip(U["def"], 0, defs["n"] - 1)],
                                                               TC_DAT_IDS))[0]
                if len(tc):
                    pick = U[int(tc[0])]
                    self.sel_unit = ("u", int(pick["uid"]))
                    ax, ay = self.world.anchors(np.array([pick], dtype=pick.dtype))
                    self.cx, self.cy = float(ax[0]), float(ay[0])
                    self._hud_dirty = True
                    self._settle(10)
                    self._shot("9_nha_chinh_nghien_cuu")
                S = getattr(self, "static_rows", None)
                if S is not None and len(S):
                    pick = S[len(S) // 2]
                    self.sel_unit = ("s", int(pick["uid"]))
                    ax, ay = self.world.anchors(np.array([pick], dtype=pick.dtype))
                    self.cx, self.cy = float(ax[0]), float(ay[0])
                    self._hud_dirty = True
                    self._settle(10)
                    self._shot("10_cay_go_con_lai")
                self.sel_unit = None
                self.hud.show_score = True
        # đo hiệu năng khi phát ở các tốc độ (giờ thật)
        self.zoom = self.zoom_target = self.fit_zoom()
        self.cx, self.cy = self.world.full_w / 2, self.world.full_h / 2
        for sp in (1.0, 8.0):
            self.speed_i = SPEEDS.index(sp)
            self.seek_r(d.duration() * 0.3)
            self.playing = True
            times = []
            t_end = time.perf_counter() + 3.0
            t_prev = time.perf_counter()
            while time.perf_counter() < t_end:
                now = time.perf_counter()
                dt = now - t_prev
                t_prev = now
                a = time.perf_counter()
                self._tick(dt, True)
                self.ctx.finish()
                times.append(time.perf_counter() - a)
            ts = np.array(times) * 1000
            self.log(f"phát x{sp:g}: {len(ts)} khung/3 s, trung vị {np.median(ts):.1f} ms, "
                     f"p95 {np.percentile(ts, 95):.1f} ms, tối đa {ts.max():.1f} ms")
        self.playing = False
        self._shot("7_sau_khi_phat")
        self.data.close()
        pygame.quit()


def main(path, game_dir=None, selftest=None):
    log_path = os.path.join(os.path.dirname(os.path.abspath(path)), "_replay.log")

    def log(msg):
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
        except OSError:
            pass
    if selftest:
        _log = log

        def log(msg):                               # tự kiểm tra: ghi cả ra console (nếu có)
            _log(msg)
            try:
                print(msg, flush=True)
            except Exception:  # noqa: BLE001
                pass
    try:
        v = Viewer(path, game_dir, log, selftest=selftest)
        if selftest:
            v.run_selftest()
        else:
            v.run()
    except Exception as e:  # noqa: BLE001
        log("lỗi: " + traceback.format_exc())
        if selftest:
            return 1
        message_box(f"Không mở được replay:\n{e}\n\nChi tiết trong {log_path}")
        return 1
    return 0
