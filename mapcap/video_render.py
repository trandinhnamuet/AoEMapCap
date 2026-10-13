"""Bộ vẽ tăng dần cho video, tối ưu cho 25 khung thật mỗi giây.

Các lớp giữ giữa các khung:
  terrain_full   : địa hình ở kích cỡ gốc (RGBA), chỉ vẽ thêm ô mới khám phá
  base           : terrain thu nhỏ + vật thể tĩnh (cây rừng, mỏ) ở kích cỡ video (RGB)
  fogged_base    : base đã nhân hệ số sương mù theo từng ô; cập nhật theo ô đổi trạng thái
  index_map      : chỉ số ô cho từng pixel video, dựng từ chính hình thoi đã vẽ (kể cả độ cao)

Mỗi khung: chép fogged_base, cập nhật ô đổi trạng thái, ghép unit động nhìn thấy, viền, chữ.
"""
import os
import time

import numpy as np
from PIL import Image, ImageChops, ImageDraw

from . import dat as D
from .render import _font
from . import offsets as O
from .lang import GameStrings
from .render_full import SpriteStore, TILE_W, TILE_H, ELEV_H, paste

BORDER_SUBSTITUTE = {6: 4, 7: None}
FULL_REFRESH_TILES = 2500      # đổi nhiều ô hơn mức này thì nhân lại toàn khung


class ScaledSprites:
    """Cache sprite đã thu nhỏ theo tỉ lệ video (kèm bản tối cho vật thể trong sương mù)."""

    def __init__(self, store: SpriteStore, scale, fog_dim, dither=True):
        self.store = store
        self.scale = scale
        self.fog_dim = fog_dim
        self.dither = dither
        self._cache = {}

    def frame(self, slp_id, idx, color_id=0, mirror=False, fogged=0):
        """fogged: 0 bình thường; 1 làm tối (chế độ dim); 2/3 lưới chấm với parity 0/1 của điểm dán."""
        key = (slp_id, idx, color_id, mirror, fogged)
        r = self._cache.get(key)
        if r is not None:
            return r or None
        if fogged:
            base = self.frame(slp_id, idx, color_id, mirror, 0)
            if base is None:
                self._cache[key] = False
                return None
            im, hx, hy = base
            if fogged == 1:
                rgb = Image.merge("RGB", im.split()[:3]).point(lambda v: int(v * self.fog_dim))
                im2 = Image.merge("RGBA", (*rgb.split(), im.split()[3]))
            else:
                a = np.array(im)
                yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
                odd = ((yy + xx + (fogged - 2)) & 1) == 1       # điểm lẻ của màn hình -> đen (như game)
                a[odd, :3] = 0
                im2 = Image.fromarray(a, "RGBA")
            r = (im2, hx, hy)
            self._cache[key] = r
            return r
        fr = self.store.frame(slp_id, idx, color_id, mirror)
        if fr is None:
            self._cache[key] = False
            return None
        im, hx, hy = fr
        s = self.scale
        if s != 1.0:
            nw, nh = max(1, round(im.width * s)), max(1, round(im.height * s))
            im = im.resize((nw, nh), Image.BOX if s < 1 else Image.NEAREST)
            hx, hy = hx * s, hy * s
        r = (im, hx, hy)
        self._cache[key] = r
        return r


def paste_rgb(dst, src, x, y):
    """Ghép sprite RGBA lên ảnh RGB tại (x, y) với cắt biên."""
    w, h = src.size
    W, H = dst.size
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + w, W), min(y + h, H)
    if x1 <= x0 or y1 <= y0:
        return
    if x0 == x and y0 == y and x1 == x + w and y1 == y + h:
        dst.paste(src, (x, y), src)
    else:
        c = src.crop((x0 - x, y0 - y, x1 - x, y1 - y))
        dst.paste(c, (x0, y0), c)


class VideoRenderer:
    @staticmethod
    def parse_fog(value):
        """fog_dim có thể là số (làm tối đều) hoặc 'dither' (lưới chấm như game). Trả về (dim, dither)."""
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ("dither", "luoi", "lưới", "grid", "checker"):
                return 0.43, True
            try:
                return float(v), False
            except ValueError:
                return 0.43, False
        return float(value), False

    def __init__(self, dat: D.DatFile, store: SpriteStore, palette, width=1920, fog_dim=0.43, log=None,
                 outline_alpha=0.35):
        fog_dim, self.FOG_DITHER = self.parse_fog(fog_dim)   # mặc định làm tối đều; 'dither' = lưới chấm như game
        self.dat = dat
        self.pal = palette
        self.fog_dim = fog_dim
        self.outline_alpha = outline_alpha
        self.width_target = width
        self.log = log or (lambda m: None)
        self.store = store
        self.colour_by_minimap = {c.minimap_color: c.id for c in dat.player_colours}
        self._font = None
        self._font_small = None
        self._gfx_cache = {}
        try:
            self.strings = GameStrings(getattr(store, 'game_dir', None) or '')
        except Exception:  # noqa: BLE001
            self.strings = None
        self.reset()

    def reset(self):
        self.map_w = self.map_h = 0
        self.scale = 1.0
        self.terrain_full = None
        self.terrain_layer = None
        self.base = None
        self.fogged_base = None
        self.static_layer = None
        self.static_version = -1
        self.base_dirty = True
        self.pending_regions = []
        self.drawn = None
        self.index_map = None
        self.tile_bbox = None
        self.prev_cls = None
        self.legend_img = None
        self.tech_done = {}          # id công nghệ -> time_ms hoàn thành (người chơi hiện tại)
        self.deaths = {}             # owner index -> tập uid unit sống đã thấy chết (bảng Dead)
        self.outline_pts = None
        self.sprites = None
        self.seen_buildings = {}     # (chỉ dùng khi emulate_ghosts) công trình đã thấy, vẽ mờ trong sương mù
        self.emulate_ghosts = getattr(self, "emulate_ghosts", False)  # dự phòng khi dữ liệu không có doppelganger của game
        self.last_stats = (0, 0, 0.0, 0.0, 0.0, 0.0)

    # ---- hình học ---------------------------------------------------------------
    @staticmethod
    def geometry(map_w, map_h, elev_max, width_target):
        """(W, H, scale, pad_top, full_w, full_h) của khung video cho bản đồ map_w x map_h, độ cao tối đa elev_max.
        Dùng trước khi dựng (chọn encoder theo kích thước thật) và trong _setup."""
        full_w = (map_w + map_h) * (TILE_W // 2)
        s = width_target / full_w
        pad_top = ELEV_H * (elev_max + 2) + 8
        full_h = (map_w + map_h) * (TILE_H // 2) + pad_top + 40
        W = int(round(full_w * s)) // 2 * 2
        H = int(round(full_h * s)) // 2 * 2
        return W, H, s, pad_top, full_w, full_h

    def _setup(self, snap):
        w, h = snap.map_w, snap.map_h
        elev_max = int(snap.elevation.max()) if snap.elevation.size else 0
        W, H, s, self.pad_top, full_w, full_h = self.geometry(w, h, elev_max, self.width_target)
        self.scale = s
        self.Y0_full = (w - 1) * (TILE_H // 2) + self.pad_top
        self.size = (W, H)
        self.full_size = (full_w, full_h)
        self.map_w, self.map_h = w, h
        self.sprites = ScaledSprites(self.store, s, self.fog_dim, self.FOG_DITHER)
        yy, xx = np.mgrid[0:H, 0:W]
        self.checker_odd = ((yy + xx) & 1).astype(bool)   # điểm lẻ màn hình
        # RGB (không alpha): resize/paste không phải chuyển đổi premultiply toàn ảnh 46 MP mỗi lần
        self.terrain_full = Image.new("RGB", (full_w, full_h), (0, 0, 0))
        self.terrain_layer = Image.new("RGB", (W, H), (0, 0, 0))
        self.drawn = np.zeros((h, w), bool)
        self.base = None
        self.fogged_base = None
        self.base_dirty = True
        self.pending_regions = []
        self.prev_cls = None
        self._build_index_map(snap)
        self._setup_outline(w, h)
        self.legend_img = None
        self.log(f"video renderer: {w}x{h} -> {W}x{H} (tỉ lệ {s:.3f})")

    def _build_index_map(self, snap):
        """Mỗi pixel video thuộc ô nào: đóng dấu hình thoi từng ô (kèm váy độ cao) theo thứ tự sâu,
        dùng đúng toạ độ vẽ của game nên khớp địa hình kể cả trên đồi."""
        w, h = snap.map_w, snap.map_h
        W, H = self.size
        s = self.scale
        hw, hh = TILE_W * s / 2, TILE_H * s / 2
        sw = int(np.ceil(TILE_W * s)) + 2
        idx_map = np.full((H, W), w * h, np.int32)        # w*h = ngoài bản đồ
        bbox = np.zeros((h * w, 4), np.int32)
        # dấu thoi: kích cỡ (sh, sw) với váy cao ELEV_H*scale*elev
        yy_s, xx_s = np.mgrid[0:int(np.ceil(TILE_H * s)) + 2, 0:sw]
        cx, cy = (sw - 1) / 2, (int(np.ceil(TILE_H * s)) + 1) / 2
        diamond = (np.abs(xx_s - cx) / (hw + 0.6) + np.abs(yy_s - cy) / (hh + 0.6)) <= 1.0
        dh = diamond.shape[0]
        ys_all, xs_all = np.mgrid[0:h, 0:w]
        order = np.lexsort(((xs_all + ys_all).ravel(), (ys_all - xs_all).ravel()))
        xs_f, ys_f = xs_all.ravel()[order], ys_all.ravel()[order]
        use_off = snap.tile_dx is not None
        for x, y in zip(xs_f.tolist(), ys_f.tolist()):
            elev = int(snap.elevation[y, x])
            if use_off:
                px = int(snap.tile_dx[y, x]); py = int(snap.tile_dy[y, x]) + self.Y0_full - TILE_H // 2
            else:
                px = (x + y) * (TILE_W // 2); py = (y - x) * (TILE_H // 2) - elev * ELEV_H + self.Y0_full - TILE_H // 2
            vx = int(round(px * s)) - 1
            vy = int(round(py * s)) - 1
            skirt = int(round(elev * ELEV_H * s)) + (int(round(ELEV_H * s)) if elev else 0)
            tid = y * w + x
            x0, y0 = max(vx, 0), max(vy, 0)
            x1, y1 = min(vx + sw, W), min(vy + dh + skirt, H)
            if x1 <= x0 or y1 <= y0:
                bbox[tid] = (0, 0, 0, 0)
                continue
            if skirt:
                stamp = np.zeros((dh + skirt, sw), bool)
                stamp[:dh] = diamond
                stamp[dh // 2:dh // 2 + skirt + 1, :] |= diamond[dh // 2]  # phần váy rộng bằng đường giữa
                stamp[dh:dh + skirt] = diamond[dh // 2]
            else:
                stamp = diamond
            sub = stamp[y0 - vy:y1 - vy, x0 - vx:x1 - vx]
            region = idx_map[y0:y1, x0:x1]
            region[sub] = tid
            bbox[tid] = (x0, y0, x1, y1)
        # lấp khe: pixel chưa thuộc ô nào nhưng có ô kề thì lấy ô kề (3 lượt, đủ cho khe 1-3 px)
        out = w * h
        for _ in range(3):
            holes = idx_map == out
            if not holes.any():
                break
            for dy, dx in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                src = np.roll(idx_map, (dy, dx), axis=(0, 1))
                fill = holes & (src != out)
                idx_map[fill] = src[fill]
                holes &= ~fill
        self.index_map = idx_map
        self.index_flat = idx_map.ravel()
        self.tile_bbox = bbox
        # mở rộng bbox từng ô thêm 3 px để bao cả pixel lấp khe
        W, H = self.size
        nz = (bbox[:, 2] > bbox[:, 0])
        bbox[nz, 0] = np.maximum(bbox[nz, 0] - 3, 0); bbox[nz, 1] = np.maximum(bbox[nz, 1] - 3, 0)
        bbox[nz, 2] = np.minimum(bbox[nz, 2] + 3, W); bbox[nz, 3] = np.minimum(bbox[nz, 3] + 3, H)

    def _setup_outline(self, w, h):
        self.outline_pts = None
        if self.outline_alpha <= 0:
            return
        s = self.scale
        Y0 = self.Y0_full
        corners = [(0, Y0), (w * (TILE_W // 2), Y0 - w * (TILE_H // 2)),
                   ((w + h) * (TILE_W // 2), Y0 + (h - w) * (TILE_H // 2)), (h * (TILE_W // 2), Y0 + h * (TILE_H // 2))]
        pts = [(x * s, y * s) for x, y in corners]
        off = 2.0
        self.outline_pts = [(pts[0][0] - off, pts[0][1]), (pts[1][0], pts[1][1] - off),
                            (pts[2][0] + off, pts[2][1]), (pts[3][0], pts[3][1] + off)]
        g = int(255 * self.outline_alpha)
        self.outline_color = (g, g, g)

    def terrain_source(self, tid):
        t = self.dat.terrains[tid]
        for _ in range(4):
            if t.slp_id >= 0:
                return t
            nxt = t.terrain_to_draw if t.terrain_to_draw >= 0 else t.terrain_replacement_id
            if nxt < 0 or nxt == t.id:
                break
            t = self.dat.terrains[nxt]
        return t if t.slp_id >= 0 else None

    def tile_pos_full(self, snap, x, y):
        if snap.tile_dx is not None:
            px = int(snap.tile_dx[y, x]); py = int(snap.tile_dy[y, x]) + self.Y0_full - TILE_H // 2
        else:
            px = (x + y) * (TILE_W // 2)
            py = (y - x) * (TILE_H // 2) - int(snap.elevation[y, x]) * ELEV_H + self.Y0_full - TILE_H // 2
        return px, py

    def _downscale_region(self, x0, y0, x1, y1):
        """Thu nhỏ vùng [x0,x1)x[y0,y1) (toạ độ gốc) vào terrain_layer; trả về vùng video đã cập nhật."""
        s = self.scale
        FW, FH = self.full_size
        W, H = self.size
        vx0 = max(0, int(np.floor(x0 * s)) - 1); vy0 = max(0, int(np.floor(y0 * s)) - 1)
        vx1 = min(W, int(np.ceil(x1 * s)) + 1); vy1 = min(H, int(np.ceil(y1 * s)) + 1)
        if vx1 <= vx0 or vy1 <= vy0:
            return None
        # dùng box số thực để lưới nguồn khớp chính xác lưới đích -> kết quả không phụ thuộc kích cỡ vùng
        region = self.terrain_full.resize((vx1 - vx0, vy1 - vy0), Image.BOX,
                                          box=(vx0 / s, vy0 / s, min(FW, vx1 / s), min(FH, vy1 / s)))
        self.terrain_layer.paste(region, (vx0, vy0))
        return (vx0, vy0, vx1, vy1)

    # ---- lớp địa hình ---------------------------------------------------------------
    def _update_terrain(self, snap, explored):
        new = explored & ~self.drawn
        if not new.any():
            return 0
        # vẽ lại cả ô lân cận đã vẽ để giữ đúng thứ tự chồng lấp của ô dốc
        grow = new.copy()
        grow[1:, :] |= new[:-1, :]; grow[:-1, :] |= new[1:, :]
        grow[:, 1:] |= new[:, :-1]; grow[:, :-1] |= new[:, 1:]
        grow[1:, 1:] |= new[:-1, :-1]; grow[:-1, :-1] |= new[1:, 1:]
        grow[1:, :-1] |= new[:-1, 1:]; grow[:-1, 1:] |= new[1:, :-1]
        redraw = grow & (new | self.drawn)
        ys, xs = np.nonzero(redraw)
        order = np.lexsort((xs + ys, ys - xs))
        boxes = []
        n = 0
        for i in order:
            x, y = int(xs[i]), int(ys[i])
            tsrc = self.terrain_source(int(snap.terrain[y, x]))
            if tsrc is None:
                continue
            shape = int(snap.shape[y, x])
            eg = tsrc.elevation_graphics[shape] if shape < 17 else tsrc.elevation_graphics[0]
            if shape == 0 or eg.frame_count <= 0:
                rows, cols = tsrc.dims if tsrc.dims[0] > 0 and tsrc.dims[1] > 0 else (1, 1)
                fidx = min((y % rows) * cols + (x % cols), max(tsrc.elevation_graphics[0].frame_count, 1) - 1)
            else:
                fidx = eg.shape_id
            fr = self.store.frame(tsrc.slp_id, fidx)
            if fr is None:
                continue
            im, hx, hy = fr
            px, py = self.tile_pos_full(snap, x, y)
            paste(self.terrain_full, im, px - hx, py - hy)
            boxes.append((px - hx, py - hy, px - hx + im.width, py - hy + im.height))
            if snap.tile_border is not None:
                b = int(snap.tile_border[y, x])
                if b:
                    self._draw_border(b & 0xF, b >> 4, shape, px, py)
            n += 1
        self.drawn |= new
        if boxes:
            vboxes = []
            if len(boxes) <= 120:
                for bx in boxes:
                    vb = self._downscale_region(*bx)
                    if vb:
                        vboxes.append(vb)
            else:
                arr = np.array(boxes)
                vb = self._downscale_region(int(arr[:, 0].min()), int(arr[:, 1].min()), int(arr[:, 2].max()), int(arr[:, 3].max()))
                if vb:
                    vboxes.append(vb)
            self.pending_regions.extend(vboxes)
        return n

    def _draw_border(self, border_id, config, shape, px, py):
        if border_id in BORDER_SUBSTITUTE:
            border_id = BORDER_SUBSTITUTE[border_id]
            if border_id is None:
                return
        if not (0 <= border_id < len(self.dat.borders)):
            return
        bd = self.dat.borders[border_id]
        if not bd.enabled or bd.slp_id < 0 or config > 11:
            return
        fc, ac, fidx = bd.frames[min(shape, 18)][config]
        if fc <= 0:
            fc, ac, fidx = bd.frames[0][config]
            if fc <= 0:
                return
        fr = self.store.frame(bd.slp_id, fidx)
        if fr is None:
            return
        im, hx, hy = fr
        paste(self.terrain_full, im, px - hx, py - hy)

    # ---- đối tượng ------------------------------------------------------------------
    def player_color_id(self, snap, owner_index):
        if owner_index <= 0 or owner_index >= len(snap.players):
            return 0
        cid = self.colour_by_minimap.get(snap.players[owner_index].mm_color)
        return cid if cid is not None else (owner_index - 1) % 8

    DEAD_GRAPHIC_TYPES = (10, 20, 30, 90)    # cây, bụi, cá, mỏ...: hết máu -> dùng đồ hoạ "dying" (vd thân cây đổ)

    def _graphic_for(self, udef_info, dead=False):
        key = (udef_info.dat_id, dead)
        g = self._gfx_cache.get(key)
        if g is None:
            udef = self.dat.units.get(udef_info.dat_id)
            g = False
            if udef is not None:
                gid = udef.dying_graphic if (dead and udef.dying_graphic >= 0) else udef.standing_graphic
                if gid >= 0:
                    g = self.dat.graphics.get(gid) or False
            self._gfx_cache[key] = g
        return g or None

    def _draw_graphic(self, img, g, X, Y, color_id, angle_frac, fogged=False, depth=0, frame=-1, abs_frame=-1):
        """frame: khung trong bộ hướng (từ game); abs_frame: chỉ số khung tuyệt đối trong SLP (giai đoạn xây)."""
        if g is None or depth > 3:
            return
        if g.deltas:
            for dl in g.deltas:
                ox, oy = dl.offset_x * self.scale, dl.offset_y * self.scale
                if dl.graphic_id == -1:
                    self._draw_main(img, g, X + ox, Y + oy, color_id, angle_frac, fogged, frame, abs_frame)
                else:
                    self._draw_graphic(img, self.dat.graphics.get(dl.graphic_id), X + ox, Y + oy, color_id, angle_frac,
                                       fogged, depth + 1, frame, abs_frame)
        else:
            self._draw_main(img, g, X, Y, color_id, angle_frac, fogged, frame, abs_frame)

    def _draw_main(self, img, g, X, Y, color_id, angle_frac, fogged, frame=-1, abs_frame=-1):
        if g.slp_id < 0:
            return
        s = self.store.slp(g.slp_id)
        if s is None:
            return
        frames = max(g.frame_count, 1)
        angles = max(g.angle_count, 1)
        mirror = False
        if abs_frame >= 0:
            fidx = abs_frame
        else:
            a = int(angle_frac * angles) % angles if angles > 1 else 0
            if g.mirroring_mode and angles > 1:
                half = angles // 2
                if a > half:
                    a = angles - a
                    mirror = True
            f = frame if 0 <= frame < frames else 0
            fidx = a * frames + f
        if fidx >= s.num_frames:
            fidx = 0
        px, py = int(round(X)), int(round(Y))
        fog_key = 0
        if fogged:
            fog_key = (2 + ((px + py) & 1)) if self.FOG_DITHER else 1
        fr = self.sprites.frame(g.slp_id, fidx, color_id, mirror, fog_key)
        if fr is None:
            return
        im, hx, hy = fr
        # parity của điểm dán thật (sau khi trừ hotspot) quyết định biến thể lưới chấm
        dx, dy = int(round(X - hx)), int(round(Y - hy))
        if fog_key >= 2 and ((dx + dy) & 1) != ((px + py) & 1):
            fr = self.sprites.frame(g.slp_id, fidx, color_id, mirror, 2 + ((dx + dy) & 1))
            if fr is None:
                return
            im, hx, hy = fr
            dx, dy = int(round(X - hx)), int(round(Y - hy))
        if img.mode == "RGB":
            paste_rgb(img, im, dx, dy)
        else:
            paste(img, im, dx, dy)

    def _game_graphic(self, u):
        """Đồ hoạ game đang vẽ cho unit (gid từ sprite list), hoặc None nếu bản ghi không có."""
        gid = getattr(u, "gid", -1)
        if gid is None or gid < 0:
            return None
        return self.dat.graphics.get(gid)

    def _construction_frame(self, u, g):
        """Công trình đang xây (status 0): khung = tiến độ máu * tổng số khung của đồ hoạ xây dựng."""
        hp_max = getattr(u.udef, "hp_max", 0) or 0
        if u.status != 0 or hp_max <= 0:
            return -1
        total = max(g.frame_count, 1) * max(g.angle_count, 1)
        stage = int(max(0.0, min(0.999, u.hp / hp_max)) * total)
        return min(stage, total - 1)

    def _unit_xy(self, u):
        s = self.scale
        return (u.x + u.y) * (TILE_W // 2) * s, ((u.y - u.x) * (TILE_H // 2) - u.z * ELEV_H + self.Y0_full) * s

    def _angle_frac(self, u, g):
        ang = getattr(u, "angle", 0) or 0
        if g.angle_count == 8:
            return ((ang + 6) % 8) / 8.0
        n = max(g.angle_count, 1)
        return (ang / n) if ang < n else 0.0

    def _remember_buildings(self, snap, units, visible):
        """Giống doppelganger của game: công trình (type 80) đã thấy được giữ lại; khi ô có tầm nhìn trở lại
        mà công trình không còn thì mới xoá. Trả về list công trình cần vẽ mờ (không có trong units hiện tại)."""
        w, h = snap.map_w, snap.map_h
        present = {}
        for u in units:
            if u.udef.utype == 80:
                tx, ty = int(u.x), int(u.y)
                if 0 <= tx < w and 0 <= ty < h and visible[ty, tx]:
                    self.seen_buildings[u.uid] = u
                present[u.uid] = u
        ghosts = []
        for uid, b in list(self.seen_buildings.items()):
            tx, ty = int(b.x), int(b.y)
            if not (0 <= tx < w and 0 <= ty < h):
                del self.seen_buildings[uid]
                continue
            if visible[ty, tx]:
                if uid not in present:
                    del self.seen_buildings[uid]      # nhìn lại thấy đã mất
                continue
            # ô không nhìn thấy: vẽ bản ghi nhớ (kể cả khi công trình vẫn còn trong danh sách game,
            # để không lộ thay đổi mới như game thật)
            ghosts.append(b)
        return ghosts

    def _draw_unit_list(self, img, snap, units, explored, visible, fog_aware=False):
        w, h = snap.map_w, snap.map_h
        items = []
        ghost_uids = set()
        doppel_tiles = set()
        if fog_aware:
            # Doppelganger đọc từ game (kind 25): bản ghi nhớ của ta về vật thể trong ô đã rơi vào sương mù.
            # Game vẽ nó thay cho vật thể thật ở ô đó (0x451FD0) và huỷ khi ô được nhìn lại.
            for u in units:
                if u.kind == 25 and u.udef.utype != 25:
                    tx, ty = int(u.x), int(u.y)
                    if 0 <= tx < w and 0 <= ty < h and not visible[ty, tx]:
                        doppel_tiles.add((tx, ty))
            if self.emulate_ghosts and not doppel_tiles:
                for b in self._remember_buildings(snap, units, visible):
                    ghost_uids.add(b.uid)
                    items.append((b.y - b.x, b.x + b.y, b, True))
        for u in units:
            d = u.udef
            tx, ty = int(u.x), int(u.y)
            if not (0 <= tx < w and 0 <= ty < h):
                continue
            if u.uid in ghost_uids:
                continue
            if d.utype == 60 and getattr(u, "gid", -1) < 0:
                continue                                  # đạn chỉ vẽ khi có sprite thật từ game
            vis = visible[ty, tx]
            if u.kind == 25:
                if vis or not fog_aware or d.utype == 25:
                    continue                      # chỉ vẽ trong sương mù; def chưa gắn được gốc thì bỏ
                items.append((u.y - u.x, u.x + u.y, u, True))
                continue
            if not vis:
                if not (explored[ty, tx] and d.fog_visible):
                    continue
                if (tx, ty) in doppel_tiles:
                    continue                      # có bản ghi nhớ ở ô này: game vẽ bản ghi nhớ, không vẽ vật thể thật
            items.append((u.y - u.x, u.x + u.y, u, (not vis) and fog_aware))
        items.sort(key=lambda t: (t[0], t[1]))
        n = 0
        for _, _, u, fogged in items:
            color = self.player_color_id(snap, u.owner_index)
            X, Y = self._unit_xy(u)
            g = self._game_graphic(u)
            if g is not None:
                abs_frame = self._construction_frame(u, g) if u.udef.utype == 80 else -1
                self._draw_graphic(img, g, X, Y, color, self._angle_frac(u, g), fogged, frame=getattr(u, "frame", -1), abs_frame=abs_frame)
                g2 = self.dat.graphics.get(u.gid2) if getattr(u, "gid2", -1) >= 0 else None
                if g2 is not None:
                    self._draw_graphic(img, g2, X, Y, color, self._angle_frac(u, g2), fogged, frame=getattr(u, "frame2", -1))
                n += 1
                continue
            dead = u.udef.utype in self.DEAD_GRAPHIC_TYPES and getattr(u, "is_dead", False)
            g = self._graphic_for(u.udef, dead)
            if g is None:
                continue
            self._draw_graphic(img, g, X, Y, color, self._angle_frac(u, g), fogged)
            n += 1
        return n

    def _update_static_layer(self, snap):
        units = getattr(snap, "static_units", None)
        ver = getattr(snap, "static_version", 0)
        if units is None:
            if self.static_layer is not None:
                self.static_layer = None
                self.base_dirty = True
            return
        if self.static_layer is not None and ver == self.static_version:
            return
        layer = Image.new("RGBA", self.size, (0, 0, 0, 0))
        ok = np.ones((snap.map_h, snap.map_w), bool)
        self._draw_unit_list(layer, snap, units, ok, ok)
        self.static_layer = layer
        self.static_version = ver
        self.base_dirty = True

    # ---- sương mù tăng dần --------------------------------------------------------------
    def _tile_classes(self, snap, explored, visible):
        cls = np.zeros(explored.shape, np.uint8)
        cls[explored] = 1
        cls[visible] = 2
        return cls

    def _factor_table(self, cls):
        fog = 255 if self.FOG_DITHER else int(round(self.fog_dim * 255))
        lut = np.array([0, fog, 255], np.uint8)
        t = lut[cls.ravel()]
        return np.append(t, np.uint8(0)).astype(np.uint8)   # ô "ngoài bản đồ" = đen (giữ uint8 cho PIL)

    def _fog_factor(self, table, cls, sub_idx, x0, y0):
        """Hệ số sáng từng pixel của vùng (sub_idx = index_map cắt tại x0,y0); lưới chấm: điểm lẻ trong ô
        sương mù = 0."""
        fac = np.take(table, sub_idx)
        if self.FOG_DITHER:
            ctab = np.append(cls.ravel().astype(np.uint8), np.uint8(0))
            pix_cls = np.take(ctab, sub_idx)
            h, w = sub_idx.shape
            odd = self.checker_odd[y0:y0 + h, x0:x0 + w]
            fac = np.where((pix_cls == 1) & odd, np.uint8(0), fac).astype(np.uint8)
        return fac

    def _rebuild_fogged(self, cls):
        """Nhân lại toàn khung (khi nền đổi hoặc quá nhiều ô đổi)."""
        fac = self._fog_factor(self._factor_table(cls), cls, self.index_map, 0, 0)
        fac_img = Image.fromarray(fac, "L").convert("RGB")
        self.fogged_base = ImageChops.multiply(self.base, fac_img)
        self.prev_cls = cls.copy()

    def _refresh_regions(self, regions, cls):
        """Cập nhật base và fogged_base chỉ trong các vùng video cho trước (địa hình mới khám phá)."""
        table = self._factor_table(cls)
        for (x0, y0, x1, y1) in regions:
            if x1 <= x0 or y1 <= y0:
                continue
            box = (x0, y0, x1, y1)
            b = self.terrain_layer.crop(box)
            if self.static_layer is not None:
                b.paste(self.static_layer.crop(box), (0, 0), self.static_layer.crop(box))
            self.base.paste(b, (x0, y0))
            fac = self._fog_factor(table, cls, self.index_map[y0:y1, x0:x1], x0, y0)
            fac_img = Image.fromarray(fac, "L").convert("RGB")
            self.fogged_base.paste(ImageChops.multiply(b, fac_img), (x0, y0))

    def _update_fogged(self, cls):
        """Chỉ nhân lại vùng của các ô đổi lớp."""
        changed = np.nonzero((cls != self.prev_cls).ravel())[0]
        if len(changed) == 0:
            return 0
        if len(changed) > FULL_REFRESH_TILES:
            self._rebuild_fogged(cls)
            return len(changed)
        table = self._factor_table(cls)
        W, H = self.size
        for tid in changed.tolist():
            x0, y0, x1, y1 = self.tile_bbox[tid]
            if x1 <= x0 or y1 <= y0:
                continue
            sub_idx = self.index_map[y0:y1, x0:x1]
            fac = self._fog_factor(table, cls, sub_idx, x0, y0)
            fac_img = Image.fromarray(fac, "L").convert("RGB")
            region = ImageChops.multiply(self.base.crop((x0, y0, x1, y1)), fac_img)
            self.fogged_base.paste(region, (x0, y0))
        self.prev_cls = cls.copy()
        return len(changed)

    # ---- khung hình ---------------------------------------------------------------
    def render(self, snap, overlay=True):
        """Trả về PIL Image RGB kích cỡ video."""
        if self.terrain_full is None or (snap.map_w, snap.map_h) != (self.map_w, self.map_h):
            self._setup(snap)
        t0 = time.time()
        explored = snap.explored()
        visible = snap.visible()
        cls = self._tile_classes(snap, explored, visible)
        n_new = self._update_terrain(snap, explored)
        self._update_static_layer(snap)
        if self.base_dirty or self.base is None:
            b = self.terrain_layer.copy()
            if self.static_layer is not None:
                b.paste(self.static_layer, (0, 0), self.static_layer)
            self.base = b
            self.base_dirty = False
            self.pending_regions = []
            self._rebuild_fogged(cls)
            n_fog = -1
        else:
            n_fog = self._update_fogged(cls)
            if self.pending_regions:
                self._refresh_regions(self.pending_regions, cls)
                self.pending_regions = []
        t1 = time.time()
        frame = self.fogged_base.copy()
        n_obj = self._draw_unit_list(frame, snap, snap.units, explored, visible, fog_aware=True)
        t2 = time.time()
        if self.outline_pts is not None:
            ImageDraw.Draw(frame).polygon(self.outline_pts, outline=self.outline_color)
        if overlay:
            self._overlay(frame, snap)
        t3 = time.time()
        self.last_stats = (n_new, n_obj, t1 - t0, t2 - t1, t3 - t2, n_fog)
        return frame

    # ---- HUD ---------------------------------------------------------------------
    RES_ITEMS = (("Gỗ", O.ATTR_WOOD, (222, 184, 135)), ("Thực", O.ATTR_FOOD, (255, 120, 90)),
                 ("Vàng", O.ATTR_GOLD, (255, 215, 0)), ("Đá", O.ATTR_STONE, (200, 200, 200)))
    RES_ICON_SLP = 50731                       # interfac.drs: icon thanh tài nguyên của game
    TECH_ICON_SLP = 50729                      # interfac.drs: icon công nghệ (frame = icon id trong DAT)
    TECH_COLS = 6                              # số icon mỗi hàng ở bảng công nghệ

    def _interfac_slp(self, sid):
        cache = getattr(self, "_interfac_cache", None)
        if cache is None:
            cache = self._interfac_cache = {}
        if sid in cache:
            return cache[sid]
        s = None
        try:
            from .gamefiles import read_group
            from .slp import SLP
            gdir = getattr(self.store, "game_dir", None)
            files = read_group(gdir, "interface") if gdir else {}
            data = files.get(("slp", sid))
            s = SLP(data) if data else None
        except Exception as e:  # noqa: BLE001
            self.log(f"không nạp được interfac.drs slp {sid}: {e}")
        cache[sid] = s
        return s

    def _tech_icon(self, icon_id, size):
        """Icon công nghệ cỡ size x size (cache) hoặc None."""
        cache = getattr(self, "_tech_icon_cache", None)
        if cache is None:
            cache = self._tech_icon_cache = {}
        key = (icon_id, size)
        if key in cache:
            return cache[key]
        im = None
        s = self._interfac_slp(self.TECH_ICON_SLP)
        if s is not None and 0 <= icon_id < len(s.frames):
            try:
                rgba, _hx, _hy = s.decode(icon_id, self.pal)
                if rgba.shape[0] > 2 and rgba.shape[1] > 2:
                    im = Image.fromarray(rgba).resize((size, size), Image.LANCZOS)
            except Exception:  # noqa: BLE001
                im = None
        cache[key] = im
        return im
    RES_ICON_FRAMES = {O.ATTR_WOOD: 0, O.ATTR_STONE: 1, O.ATTR_FOOD: 2, O.ATTR_GOLD: 3}

    def _res_icons(self, height):
        """Icon tài nguyên của game, cao `height` px (cache). Trả về dict attr -> ảnh RGBA hoặc {} nếu không có."""
        cache = getattr(self, "_res_icon_cache", None)
        if cache is not None and cache[0] == height:
            return cache[1]
        icons = {}
        try:
            from .gamefiles import read_group
            from .slp import SLP
            gdir = getattr(self.store, "game_dir", None)
            files = read_group(gdir, "interface") if gdir else {}
            data = files.get(("slp", self.RES_ICON_SLP))
            if data:
                s = SLP(data)
                for attr, f in self.RES_ICON_FRAMES.items():
                    rgba, _hx, _hy = s.decode(f, self.pal)
                    im = Image.fromarray(rgba)
                    w = max(1, int(round(im.width * height / im.height)))
                    icons[attr] = im.resize((w, height), Image.LANCZOS)
        except Exception as e:  # noqa: BLE001
            self.log(f"không nạp được icon tài nguyên: {e}")
        self._res_icon_cache = (height, icons)
        return icons
    CIV_VI = {"Egyptian": "Ai Cập", "Greek": "Hy Lạp", "Babylonian": "Babylon", "Assyrian": "Assyria",
              "Minoan": "Minoa", "Hittite": "Hittite", "Phoenician": "Phoenicia", "Sumerian": "Sumeria",
              "Persian": "Ba Tư", "Shang": "Shang", "Yamato": "Yamato", "Choson": "Choson", "Roman": "Roma",
              "Carthage": "Carthage", "Palmyra": "Palmyra", "Macedonian": "Macedonia"}

    def _fonts(self):
        if self._font is None:
            base = max(12, int(self.size[0] / 90))
            self._font = _font(base)
            self._font_small = _font(max(10, int(base * 0.85)))
        return self._font, self._font_small

    @staticmethod
    def _tw(font, text):
        try:
            return font.getlength(text)
        except AttributeError:
            return font.getbbox(text)[2]

    def _panel(self, frame, x, y, w, h, alpha=170):
        box = Image.new("RGBA", (max(1, int(w)), max(1, int(h))), (0, 0, 0, alpha))
        frame.paste(box, (int(x), int(y)), box)

    @staticmethod
    def _text(d, x, y, s, font, fill=(255, 255, 255)):
        d.text((x + 1, y + 1), s, fill=(0, 0, 0), font=font)
        d.text((x, y), s, fill=fill, font=font)

    CIV_STRING_ID = {13: 10246, 14: 10247, 15: 10249, 16: 10248}   # 1..12 -> 10230 + civ

    def _civ_label(self, snap, p):
        if p.civ <= 0:
            return ""
        sid = self.CIV_STRING_ID.get(p.civ, 10230 + p.civ if p.civ <= 12 else None)
        if self.strings is not None:
            v = self.strings.get(sid)
            if v:
                return v
        names = getattr(self.dat, "civ_names", None) or []
        if p.civ < len(names):
            en = names[p.civ]
            return self.CIV_VI.get(en, en)
        return ""

    def _tech_label(self, r):
        if self.strings is not None:
            v = self.strings.get(r.lang_name)
            if v:
                return v
        return r.name

    def _player_rows(self, snap):
        return [p for p in snap.players if p.index != 0 and (p.addr or p.pid)]

    def _completed_techs(self, snap):
        """Danh sách (time_ms, tên) công nghệ người chơi hiện tại đã nghiên cứu, theo thứ tự hoàn thành."""
        cur = snap.cur_player
        if cur is None or cur.techs is None:
            return None
        research = getattr(self.dat, "research", None) or []
        times = getattr(cur, "tech_times", None) or {}    # giờ hoàn thành thật (tích luỹ từ đầu bản ghi)
        for tid in cur.techs:
            if tid not in self.tech_done and tid < len(research) and research[tid].researchable:
                self.tech_done[tid] = times.get(tid, snap.time_ms)
            elif tid in self.tech_done and tid in times and self.tech_done[tid] != times[tid]:
                self.tech_done[tid] = times[tid]
        gone = [tid for tid in self.tech_done if tid not in cur.techs]
        for tid in gone:
            del self.tech_done[tid]
        items = sorted(self.tech_done.items(), key=lambda kv: kv[1])
        return [(t, self._tech_label(research[tid]), research[tid].icon) for tid, t in items]

    def _overlay(self, frame, snap):
        font, small = self._fonts()
        W, H = frame.size
        pad = 8
        lh = font.size + 4
        cur = snap.cur_player
        d = ImageDraw.Draw(frame)

        # ---- trên trái: đồng hồ, góc nhìn, tài nguyên của người chơi hiện tại
        line1 = f"{snap.time_str()}   góc nhìn: {cur.name if cur else '?'}"
        if cur is not None and cur.attrs:
            pop, room = cur.attr(O.ATTR_POP), cur.attr(O.ATTR_POP_ROOM)
            if pop is not None and room is not None:
                line1 += f"   dân số {int(pop)}/{int(pop + room)}"
        parts = []
        if cur is not None and cur.attrs:
            for label, k, col in self.RES_ITEMS:
                v = cur.attr(k)
                parts.append((label, k, f"{int(v):d}" if v is not None else "-", col))
        icon_h = int(lh * 1.15)
        icons = self._res_icons(icon_h) if parts else {}
        gap = font.size // 2
        def part_w(label, k, val):
            ic = icons.get(k)
            return (ic.width + gap if ic is not None else self._tw(font, label + " ")) + self._tw(font, val) + font.size
        w1 = self._tw(font, line1)
        w2 = sum(part_w(a, k, b) for a, k, b, _ in parts)
        row_h = max(lh, icon_h + 2) if icons else lh
        self._panel(frame, 0, 0, max(w1, w2) + 2 * pad, lh + (row_h if parts else 0) + pad)
        self._text(d, pad, 3, line1, font)
        x = pad
        y2 = 3 + lh
        for label, k, val, col in parts:
            ic = icons.get(k)
            if ic is not None:
                frame.paste(ic, (int(x), int(y2 + (row_h - ic.height) // 2)), ic)
                x += ic.width + gap
            else:
                self._text(d, x, y2 + (row_h - lh) // 2, label, font, col)
                x += self._tw(font, label + " ")
            self._text(d, x, y2 + (row_h - lh) // 2, val, font)
            x += self._tw(font, val) + font.size

        # ---- trên phải: công nghệ đã nghiên cứu (icon game, giờ hoàn thành dưới icon)
        techs = self._completed_techs(snap)
        if techs is not None:
            title = "Công nghệ đã nghiên cứu"
            icon = max(24, int(small.size * 2.4))
            cell_w = max(icon, int(self._tw(small, "00:00:00"))) + 6
            cell_h = icon + small.size + 6
            cols = self.TECH_COLS
            rows_t = techs[-cols * 6:]                      # tối đa 6 hàng gần nhất
            n_rows = (len(rows_t) + cols - 1) // cols
            w = max(self._tw(font, title) + 2 * pad, cell_w * cols + 2 * pad)
            h = lh + n_rows * cell_h + pad
            x0 = W - w
            self._panel(frame, x0, 0, w, h)
            self._text(d, x0 + pad, 3, title, font, (255, 230, 150))
            for k, (t, name, icon_id) in enumerate(rows_t):
                cx = x0 + pad + (k % cols) * cell_w
                cy = 3 + lh + (k // cols) * cell_h
                im = self._tech_icon(icon_id, icon)
                if im is not None:
                    frame.paste(im, (int(cx + (cell_w - icon) // 2), int(cy)), im)
                else:
                    d.rectangle([cx + 2, cy, cx + cell_w - 4, cy + icon], outline=(200, 200, 200))
                    self._text(d, cx + 4, cy + 2, name[:8], small)
                ts = self._fmt_ms(t)
                self._text(d, cx + (cell_w - self._tw(small, ts)) // 2, cy + icon + 2, ts, small)

        # ---- dưới phải: chú giải người chơi + nền văn minh
        rows = self._player_rows(snap)
        if self.legend_img is None:
            labels = [(p, f"{p.name}" + (f"  ·  {self._civ_label(snap, p)}" if self._civ_label(snap, p) else "")) for p in rows]
            w = max([self._tw(font, s) for _, s in labels] + [80]) + font.size + 3 * pad
            h = lh * len(labels) + pad
            leg = Image.new("RGBA", (int(w), int(h)), (0, 0, 0, 170))
            dl = ImageDraw.Draw(leg)
            y = pad // 2
            for p, s in labels:
                cid = self.player_color_id(snap, p.index)
                col = self.pal[min(16 * (cid + 1) + 4, 255)]
                dl.rectangle([pad, y + 2, pad + font.size - 2, y + font.size], fill=col, outline=(255, 255, 255))
                dl.text((pad + font.size + 5, y + 1), s, fill=(0, 0, 0), font=font)
                dl.text((pad + font.size + 4, y), s, fill=(240, 240, 240), font=font)
                y += lh
            self.legend_img = leg
        lw, lhh = self.legend_img.size
        frame.paste(self.legend_img, (W - lw, H - lhh), self.legend_img)

        # ---- dưới trái: bảng thống kê từng người chơi
        if rows and any(p.attrs for p in rows):
            vill = {p.index: 0 for p in rows}
            for u in snap.units:
                if u.udef.utype != 70 or u.kind == 25:
                    continue
                if u.is_dead:
                    self.deaths.setdefault(u.owner_index, set()).add(u.uid)   # game không có thuộc tính 'đã mất'
                elif u.udef.cls == 4 and u.owner_index in vill:
                    vill[u.owner_index] += 1
            cols = ["Dân", "Dân số", "Kill", "Dead", "Vàng KT", "Bơm"]
            name_w = max([self._tw(small, p.name) for p in rows] + [60]) + small.size + pad
            col_w = max(self._tw(small, c) for c in cols) + 2 * pad
            w = name_w + col_w * len(cols) + pad
            h = (small.size + 4) * (len(rows) + 1) + pad
            y0 = H - h
            self._panel(frame, 0, y0, w, h)
            y = y0 + pad // 2
            x = pad + name_w
            for c in cols:
                self._text(d, x, y, c, small, (255, 230, 150))
                x += col_w
            y += small.size + 4
            for p in rows:
                cid = self.player_color_id(snap, p.index)
                col = self.pal[min(16 * (cid + 1) + 4, 255)]
                d.rectangle([pad, y + 2, pad + small.size - 3, y + small.size - 1], fill=col, outline=(255, 255, 255))
                self._text(d, pad + small.size + 2, y, p.name, small)
                pop = p.attr(O.ATTR_POP)
                kills = p.attr(O.ATTR_KILLS)
                ratio = p.attr(O.ATTR_KILL_RATIO)
                gold = p.attr(O.ATTR_GOLD_COLLECTED)
                trib = p.attr(O.ATTR_TRIBUTE_GIVEN)
                if kills is not None and ratio is not None:
                    deaths = int(round(kills - ratio))          # game: kill ratio = kill - loss
                else:
                    deaths = len(self.deaths.get(p.index, ()))  # dự phòng: đếm từ luồng unit
                vals = [str(vill[p.index]), "-" if pop is None else str(int(pop)),
                        "-" if kills is None else str(int(kills)), str(deaths),
                        "-" if gold is None else str(int(gold)), "-" if trib is None else str(int(max(trib, 0)))]
                x = pad + name_w
                for v in vals:
                    self._text(d, x, y, v, small)
                    x += col_w
                y += small.size + 4

    @staticmethod
    def _fmt_ms(ms):
        s = int(ms) // 1000
        return f"{s // 3600:02d}:{(s // 60) % 60:02d}:{s % 60:02d}"
