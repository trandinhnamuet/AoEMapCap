"""Bộ vẽ đầy đủ: dựng lại bản đồ bằng sprite thật của game (địa hình, công trình, unit, tài nguyên).

Hệ toạ độ ảnh (khớp minimap và diam_map của game):
    X = (x + y) * 32          Y = (y - x) * 16 - z * 16
với (x, y) là toạ độ thế giới (cột, hàng), z độ cao theo bậc. Ô 64x32 px, một bậc độ cao = 16 px.
"""
import os
import time

import numpy as np
from PIL import Image, ImageDraw

from . import dat as D
from . import offsets as O
from .drs import read_drs
from .game import Snapshot
from .render import _font
from .slp import SLP

TILE_W, TILE_H, ELEV_H = 64, 32, 16

# ANGLE_NOTE: byte hướng của unit trong game: 0=E(+x+y), 1=SE(+y), 2=S, 3=SW(-x), 4=W, 5=NW(-y), 6=N, 7=NE(+x)
# (góc radian = (idx+1)*pi/4 theo atan2(dy, dx)). Bộ frame trong SLP: 0=S, 1=SW, 2=W, 3=NW, 4=N, 5=NE, 6=E, 7=SE.
# => set = (idx + 6) % 8.


class SpriteStore:
    def __init__(self, game_dir, palette):
        self.game_dir = game_dir
        self.files = read_drs(os.path.join(game_dir, "data", "graphic.drs"))
        self.pal = palette
        self._slp = {}
        self._img = {}

    def slp(self, slp_id):
        s = self._slp.get(slp_id)
        if s is None:
            data = self.files.get(("slp", slp_id))
            s = SLP(data) if data else False
            self._slp[slp_id] = s
        return s or None

    def frame(self, slp_id, idx, color_id=0, mirror=False):
        """Trả về (PIL RGBA, hx, hy) hoặc None."""
        key = (slp_id, idx, color_id, mirror)
        r = self._img.get(key)
        if r is not None:
            return r or None
        s = self.slp(slp_id)
        if s is None or not (0 <= idx < s.num_frames):
            self._img[key] = False
            return None
        rgba, hx, hy = s.decode(idx, self.pal, color_id)
        if rgba.size == 0:
            self._img[key] = False
            return None
        if mirror:
            rgba = rgba[:, ::-1]
            hx = rgba.shape[1] - 1 - hx
        im = Image.fromarray(np.ascontiguousarray(rgba), "RGBA")
        r = (im, hx, hy)
        self._img[key] = r
        return r


def paste(dst, src, x, y):
    """Ghép RGBA src lên dst (RGBA hoặc RGB) tại (x, y) với cắt biên."""
    w, h = src.size
    W, H = dst.size
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + w, W), min(y + h, H)
    if x1 <= x0 or y1 <= y0:
        return
    if dst.mode != "RGBA":
        if x0 == x and y0 == y and x1 == x + w and y1 == y + h:
            dst.paste(src, (x, y), src)
        else:
            c = src.crop((x0 - x, y0 - y, x1 - x, y1 - y))
            dst.paste(c, (x0, y0), c)
        return
    if x0 == x and y0 == y and x1 == x + w and y1 == y + h:
        dst.alpha_composite(src, dest=(x, y))
    else:
        dst.alpha_composite(src.crop((x0 - x, y0 - y, x1 - x, y1 - y)), dest=(x0, y0))


class FullRenderer:
    def __init__(self, dat: D.DatFile, store: SpriteStore, palette, scale=1.0, fog_dim=0.43, legend=True,
                 default_angle=0, use_tile_offsets=True, log=None):
        self.dat = dat
        self.store = store
        self.pal = palette
        self.scale = scale
        self.fog_dim = fog_dim
        self.legend = legend
        self.default_angle = default_angle
        self.use_tile_offsets = use_tile_offsets
        self.log = log or (lambda m: None)
        self.colour_by_minimap = {c.minimap_color: c.id for c in dat.player_colours if c.type != 0 or c.id < 8}

    # ---- tiện ích -------------------------------------------------------------
    def player_color_id(self, snap, owner_index):
        if owner_index <= 0 or owner_index >= len(snap.players):
            return 0
        pl = snap.players[owner_index]
        cid = self.colour_by_minimap.get(pl.mm_color)
        if cid is None:
            cid = (owner_index - 1) % 8
        return cid

    def terrain_source(self, tid):
        """Trả về bản ghi địa hình có SLP thật (đi theo terrain_to_draw)."""
        t = self.dat.terrains[tid]
        for _ in range(4):
            if t.slp_id >= 0:
                return t
            nxt = t.terrain_to_draw if t.terrain_to_draw >= 0 else t.terrain_replacement_id
            if nxt < 0 or nxt == t.id:
                break
            t = self.dat.terrains[nxt]
        return t if t.slp_id >= 0 else None

    # ---- vẽ ---------------------------------------------------------------------
    def render(self, snap: Snapshot) -> Image.Image:
        t0 = time.time()
        w, h = snap.map_w, snap.map_h
        elev_max = int(snap.elevation.max())
        pad_top = ELEV_H * (elev_max + 2) + 8
        pad_bottom = 96
        img_w = (w + h) * (TILE_W // 2)
        Y0 = (w - 1) * (TILE_H // 2) + pad_top       # Y của điểm (0,0) mặt đất
        img_h = (w + h) * (TILE_H // 2) + pad_top + pad_bottom
        img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 255))

        explored = snap.explored()
        visible = snap.visible()

        # --- địa hình: thứ tự vẽ từ trên xuống (y - x tăng), trong hàng theo x + y
        use_off = self.use_tile_offsets and snap.tile_dx is not None
        n_tiles = 0
        for d in range(-(w - 1), h):                 # d = y - x
            for s in range(abs(d), w + h - 1 - abs(d) + 1, 2):   # s = x + y cùng tính chẵn lẻ với d
                x = (s - d) // 2
                y = (s + d) // 2
                if not (0 <= x < w and 0 <= y < h):
                    continue
                if not explored[y, x]:
                    continue
                tid = int(snap.terrain[y, x])
                tsrc = self.terrain_source(tid)
                if tsrc is None:
                    continue
                shape = int(snap.shape[y, x])
                eg = tsrc.elevation_graphics[shape] if shape < 17 else tsrc.elevation_graphics[0]
                if shape == 0 or eg.frame_count <= 0:
                    rows, cols = tsrc.dims if tsrc.dims[0] > 0 and tsrc.dims[1] > 0 else (1, 1)
                    fidx = (y % rows) * cols + (x % cols)
                    fidx = min(fidx, max(tsrc.elevation_graphics[0].frame_count, 1) - 1)
                else:
                    fidx = eg.shape_id
                fr = self.store.frame(tsrc.slp_id, fidx)
                if fr is None:
                    continue
                im, hx, hy = fr
                elev = int(snap.elevation[y, x])
                if use_off:
                    px = int(snap.tile_dx[y, x])
                    py = int(snap.tile_dy[y, x]) + Y0 - TILE_H // 2
                else:
                    px = (x + y) * (TILE_W // 2)
                    py = (y - x) * (TILE_H // 2) - elev * ELEV_H + Y0 - TILE_H // 2
                paste(img, im, px - hx, py - hy)
                n_tiles += 1
                if snap.tile_border is not None:
                    b = int(snap.tile_border[y, x])
                    if b:
                        self._draw_border(img, b & 0xF, b >> 4, shape, px, py)
        t1 = time.time()

        # --- vật thể
        n_obj = self._draw_objects(img, snap, explored, visible, Y0)
        t2 = time.time()

        # --- sương mù (áp lên cả địa hình và vật thể trong vùng ngoài tầm nhìn)
        if self.fog_dim < 1.0 and not (visible | ~explored).all():
            self._apply_fog(img, snap, explored, visible, Y0)
        t3 = time.time()
        self.log(f"render: {n_tiles} ô {t1 - t0:.1f}s, {n_obj} vật thể {t2 - t1:.1f}s, sương mù {t3 - t2:.1f}s")

        out = img.convert("RGB")
        if self.scale != 1.0:
            out = out.resize((max(1, int(out.width * self.scale)), max(1, int(out.height * self.scale))), Image.LANCZOS)
        if self.legend:
            out = self._add_legend(out, snap)
        return out

    # Viền kiểu 1 (mảnh rời) chưa rõ cách ghép -> thay bằng viền kiểu 0 tương đương
    BORDER_SUBSTITUTE = {6: 4, 7: None}

    def _draw_border(self, img, border_id, config, shape, px, py):
        if border_id in self.BORDER_SUBSTITUTE:
            border_id = self.BORDER_SUBSTITUTE[border_id]
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
        paste(img, im, px - hx, py - hy)

    def _fog_stamp(self):
        """Mặt nạ hình thoi 65x33 kèm 'váy' 2 bậc độ cao bên dưới (uint8: 0 = tối, 255 = giữ)."""
        st = getattr(self, "_stamp", None)
        if st is not None:
            return st
        hw, hh = TILE_W // 2, TILE_H // 2
        H = TILE_H + 1 + ELEV_H * 2
        m = np.full((H, TILE_W + 1), 255, np.uint8)
        yy, xx = np.mgrid[0:H, 0:TILE_W + 1]
        inside_top = (np.abs(xx - hw) / hw + np.abs(yy - hh) / hh) <= 1.0 + 1e-6
        skirt = (yy > hh) & (np.abs(xx - hw) / hw + np.abs(np.minimum(yy, hh + ELEV_H * 2) - (hh + ELEV_H * 2)) / hh <= 1.0 + 1e-6)
        m[inside_top | skirt] = 0
        self._stamp = m
        return m

    def _apply_fog(self, img, snap, explored, visible, Y0):
        """Nhân độ sáng vùng đã khám phá nhưng không nhìn thấy."""
        w, h = snap.map_w, snap.map_h
        W, Himg = img.size
        mask = np.zeros((Himg, W), np.uint8)          # 0 = không tối, 1 = tối
        stamp = self._fog_stamp() == 0
        sh, sw = stamp.shape
        hw, hh = TILE_W // 2, TILE_H // 2
        ys, xs = np.nonzero(explored & ~visible)
        use_off = snap.tile_dx is not None
        for y, x in zip(ys.tolist(), xs.tolist()):
            if use_off:
                px = int(snap.tile_dx[y, x]); py = int(snap.tile_dy[y, x]) + Y0 - hh
            else:
                px = (x + y) * hw; py = (y - x) * hh - int(snap.elevation[y, x]) * ELEV_H + Y0 - hh
            x0, y0 = max(px, 0), max(py, 0)
            x1, y1 = min(px + sw, W), min(py + sh, Himg)
            if x1 <= x0 or y1 <= y0:
                continue
            mask[y0:y1, x0:x1] |= stamp[y0 - py:y1 - py, x0 - px:x1 - px]
        arr = np.asarray(img).copy()
        sel = mask.astype(bool)
        arr[sel, :3] = (arr[sel, :3].astype(np.uint16) * int(self.fog_dim * 256) >> 8).astype(np.uint8)
        img.paste(Image.fromarray(arr, "RGBA"))

    # ---- vật thể ------------------------------------------------------------------
    def _graphic_for_unit(self, snap, u):
        """Chọn bản ghi Graphic (từ empires.dat) cho unit."""
        udef = self.dat.units.get(u.udef.dat_id)
        if udef is None or udef.standing_graphic < 0:
            return None
        return self.dat.graphics.get(udef.standing_graphic)

    def _draw_graphic(self, img, g, X, Y, color_id, angle_frac, depth=0, frame_no=0):
        """Vẽ graphic g (kể cả delta) với tâm tại (X, Y)."""
        if g is None or depth > 3:
            return 0
        n = 0
        if g.deltas:
            for dl in g.deltas:
                if dl.graphic_id == -1:
                    n += self._draw_graphic_main(img, g, X + dl.offset_x, Y + dl.offset_y, color_id, angle_frac, frame_no)
                else:
                    sub = self.dat.graphics.get(dl.graphic_id)
                    n += self._draw_graphic(img, sub, X + dl.offset_x, Y + dl.offset_y, color_id, angle_frac, depth + 1, frame_no)
        else:
            n += self._draw_graphic_main(img, g, X, Y, color_id, angle_frac, frame_no)
        return n

    def _draw_graphic_main(self, img, g, X, Y, color_id, angle_frac, frame_no):
        if g.slp_id < 0:
            return 0
        s = self.store.slp(g.slp_id)
        if s is None:
            return 0
        frames = max(g.frame_count, 1)
        angles = max(g.angle_count, 1)
        a = int(angle_frac * angles) % angles if angles > 1 else 0
        mirror = False
        if g.mirroring_mode and angles > 1:
            half = angles // 2
            if a > half:
                a = angles - a
                mirror = True
        fidx = a * frames + (frame_no % frames)
        if fidx >= s.num_frames:
            fidx = min(frame_no % frames, s.num_frames - 1)
        fr = self.store.frame(g.slp_id, fidx, color_id, mirror)
        if fr is None:
            return 0
        im, hx, hy = fr
        paste(img, im, X - hx, Y - hy)
        return 1

    def _draw_objects(self, img, snap, explored, visible, Y0):
        w, h = snap.map_w, snap.map_h
        items = []
        for u in snap.units:
            d = u.udef
            tx, ty = int(u.x), int(u.y)
            if not (0 <= tx < w and 0 <= ty < h):
                continue
            if not visible[ty, tx]:
                if not (explored[ty, tx] and d.fog_visible):
                    continue
            if d.utype in (60,):                        # đạn bay
                continue
            # thứ tự sâu: hàng chéo (y - x) rồi cột; công trình lấy mép trước theo bán kính
            udef = self.dat.units.get(d.dat_id)
            r = max(udef.radius_x, udef.radius_y) if udef else 0.2
            depth = (u.y - u.x) + r * 0.0
            items.append((depth, u.x + u.y, u))
        items.sort(key=lambda t: (t[0], t[1]))
        n = 0
        for _, _, u in items:
            g = self._graphic_for_unit(snap, u)
            if g is None:
                continue
            X = int(round((u.x + u.y) * (TILE_W // 2)))
            Y = int(round((u.y - u.x) * (TILE_H // 2) - u.z * ELEV_H + Y0))
            cid = self.player_color_id(snap, u.owner_index)
            ang = getattr(u, 'angle', None)
            if ang is None:
                ang = self.default_angle
            if g.angle_count == 8:
                angle_frac = ((ang + 6) % 8) / 8.0      # xem chú thích ANGLE_NOTE
            else:
                # công trình/tài nguyên: byte hướng dùng thẳng làm chỉ số biến thể (vd nhà chính theo thời đại)
                angle_frac = (ang / max(g.angle_count, 1)) if ang < max(g.angle_count, 1) else 0.0
            n += self._draw_graphic(img, g, X, Y, cid, angle_frac)
        return n

    def _add_legend(self, img, snap):
        font = _font(max(14, int(24 * max(self.scale, 0.5))))
        line_h = font.size + 6
        rows = 1 + sum(1 for p in snap.players if p.index != 0)
        pad = 10
        legend_h = rows * line_h + pad * 2
        out = Image.new("RGB", (img.width, img.height + legend_h), (24, 24, 24))
        out.paste(img, (0, legend_h))
        d = ImageDraw.Draw(out)
        cur = snap.cur_player
        d.text((pad, pad), f"Thời gian game {snap.time_str()}   bản đồ {snap.map_w}x{snap.map_h}   "
                           f"góc nhìn: {cur.name if cur else '?'}   tốc độ x{snap.speed:.1f}",
               fill=(240, 240, 240), font=font)
        y = pad + line_h
        for p in snap.players:
            if p.index == 0:
                continue
            cid = self.player_color_id(snap, p.index)
            col = self.pal[min(16 * (cid + 1) + 4, 255)]
            d.rectangle([pad, y + 3, pad + font.size, y + 3 + font.size], fill=col, outline=(255, 255, 255))
            d.text((pad * 2 + font.size, y), f"{p.name}  ({p.unit_count} đối tượng)", fill=(230, 230, 230), font=font)
            y += line_h
        return out
