"""Thế giới để vẽ bằng GPU: ảnh địa hình (đã giảm theo ngân sách bộ nhớ), bản đồ chỉ số ô theo pixel (sương mù),
và danh sách mảnh sprite cho unit/vật thể tĩnh.

Toạ độ thế giới = pixel gốc của game trong khung toàn bản đồ của bộ vẽ video ở tỉ lệ 1:
    X = (x + y) * 32          Y = (y - x) * 16 - z * 16 + Y0        (Y0 = (map_w - 1) * 16 + pad_top)
Cách chọn đồ hoạ/khung/hướng/giai đoạn xây dùng lại đúng logic của mapcap.video_render.VideoRenderer.
"""
import os
import time
from types import SimpleNamespace

import numpy as np
from PIL import Image

from mapcap import dat as D
from mapcap import drs
from mapcap.render_full import ELEV_H, TILE_H, TILE_W, SpriteStore, paste
from mapcap.video_render import VideoRenderer

TERRAIN_BUDGET_PX = 48e6        # ảnh địa hình trên GPU tối đa ~48 MP (map 144: gốc 9216 px; map 250: một nửa)
BAND = 1024                     # dựng địa hình theo dải 1024 px gốc rồi thu nhỏ (giống bộ vẽ video: không hở mép ô)
DEAD_TYPES = np.array(VideoRenderer.DEAD_GRAPHIC_TYPES)
TC_DAT_IDS = (109, 71, 141, 142)  # Town Center các đời (DAT AoE1)


class ViewerSpriteStore(SpriteStore):
    """Như SpriteStore nhưng không giữ bản numpy trong SLP._cache (chỉ giữ ảnh PIL): một trận có ~20 nghìn khung
    unit khác nhau, giữ hai bản tốn gấp đôi RAM."""

    def frame(self, slp_id, idx, color_id=0, mirror=False):
        key = (slp_id, idx, color_id, mirror)
        if key in self._img:
            r = self._img[key]
            return r or None
        r = super().frame(slp_id, idx, color_id, mirror)
        s = self._slp.get(slp_id)
        if s:
            s._cache.pop((idx, color_id), None)
        return r

    def cached(self, key):
        return key in self._img


def load_graphics(game_dir):
    palette = np.asarray(drs.load_palette(game_dir), np.uint8)    # mảng numpy: SLP.decode không phải chuyển mỗi lần
    from mapcap.gamefiles import dat_path
    dat = D.load(dat_path(game_dir))
    D.parse_units_by_scan(dat)
    store = ViewerSpriteStore(game_dir, palette)
    return dat, store, palette


class SpriteResolver(VideoRenderer):
    """Dùng lại logic chọn đồ hoạ của bộ vẽ video, nhưng thay vì dán ảnh thì ghi lại lệnh vẽ (sprite, độ lệch)."""

    def __init__(self, dat, store, palette, y0):
        super().__init__(dat, store, palette, width=1, fog_dim=0.43, outline_alpha=0)
        self.scale = 1.0
        self.Y0_full = y0
        self._cmds = None

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
        self._cmds.append(((g.slp_id, fidx, color_id, mirror), X, Y))

    def commands(self, dat_id, gid, frame, angle, gid2, frame2, color, stage, dead, utype, status, hp, hp_max):
        """Danh sách ((slp, khung, màu, lật), X, Y) tương đối so với điểm neo của unit."""
        self._cmds = []
        u = SimpleNamespace(angle=angle, hp=hp, status=status, udef=SimpleNamespace(hp_max=hp_max, dat_id=dat_id))
        if gid >= 0:
            g = self.dat.graphics.get(gid)
            if g is not None:
                self._draw_graphic(None, g, 0.0, 0.0, color, self._angle_frac(u, g), False, frame=frame, abs_frame=stage)
                g2 = self.dat.graphics.get(gid2) if gid2 >= 0 else None
                if g2 is not None:
                    self._draw_graphic(None, g2, 0.0, 0.0, color, self._angle_frac(u, g2), False, frame=frame2)
        else:
            g = self._graphic_for(u.udef, dead)
            if g is not None:
                self._draw_graphic(None, g, 0.0, 0.0, color, self._angle_frac(u, g), False)
        out, self._cmds = self._cmds, None
        return out


# Khoá hình của unit nén vào một int64 (np.unique trên int nhanh hơn ~50 lần so với mảng có cấu trúc).
# Có đồ hoạ game (gid >= 0): gid 12 | frame 10 | angle 4 | gid2 12 | frame2 10 | color 4 | stage 10 bit (giá trị +1).
# Không có (bit 62 = 1): dat_id 12 | angle 4 | color 4 | dead 1.
_G_FIELDS = (("gid", 12), ("frame", 10), ("angle", 4), ("gid2", 12), ("frame2", 10), ("color", 4), ("stage", 10))
_D_FIELDS = (("dat", 12), ("angle", 4), ("color", 4), ("dead", 1))
_NOG = np.int64(1) << np.int64(62)


def _pack(fields, vals):
    k = np.zeros(len(next(iter(vals.values()))), np.int64)
    for name, bits in fields:
        v = np.clip(vals[name].astype(np.int64) + 1, 0, (1 << bits) - 1)
        k = (k << np.int64(bits)) | v
    return k


def _unpack(fields, key):
    out = {}
    for name, bits in reversed(fields):
        out[name] = (key & ((1 << bits) - 1)) - 1
        key >>= bits
    return out


class World:
    def __init__(self, hdr, dat, store, palette, log=None):
        self.log = log or (lambda m: None)
        self.hdr = hdr
        self.dat, self.store, self.pal = dat, store, palette
        self.map_w, self.map_h = int(hdr["map_w"]), int(hdr["map_h"])
        self.elev = np.asarray(hdr["elevation"])
        elev_max = int(self.elev.max()) if self.elev.size else 0
        full_w = (self.map_w + self.map_h) * (TILE_W // 2)
        W, H, _s, self.pad_top, _fw, _fh = VideoRenderer.geometry(self.map_w, self.map_h, elev_max, full_w)
        self.full_w, self.full_h = W, H
        self.Y0 = (self.map_w - 1) * (TILE_H // 2) + self.pad_top
        ts = 1.0
        while W * H * ts * ts > TERRAIN_BUDGET_PX and ts > 0.125:
            ts /= 2
        self.ts = ts
        self.tex_w, self.tex_h = int(round(W * ts)), int(round(H * ts))
        self.resolver = SpriteResolver(dat, store, palette, self.Y0)
        cmap = {c.minimap_color: c.id for c in dat.player_colours}
        players = hdr["players"]
        self.color_lut = np.zeros(max(len(players), 1) + 1, np.uint8)
        for i, p in enumerate(players):
            mm = p[4]
            if i > 0:
                cid = cmap.get(mm)
                self.color_lut[i] = cid if cid is not None else (i - 1) % 8
        n_g = (max(dat.graphics) + 1) if dat.graphics else 1
        self.gtotal = np.ones(n_g, np.int32)
        for gid, g in dat.graphics.items():
            self.gtotal[gid] = max(g.frame_count, 1) * max(g.angle_count, 1)
        # mảnh sprite: (khoá sprite -> slot) và theo khoá hình của unit -> đoạn liên tiếp trong bảng mảnh
        self.slot_of = {}
        self.slot_keys = []
        self.slot_w = []
        self.slot_h = []
        self.deadline = None         # hạn giải mã sprite mới trong khung hình này (perf_counter); None = không giới hạn
        self.deferred = 0            # số khoá hình phải hoãn ở lần dựng gần nhất
        self._prev = None            # (uid đã sắp, start, count) của lần dựng unit trước: dự phòng khi khoá chưa giải mã
        self._pieces = {"slot": [], "dx": [], "dy": []}
        self._piece_np = None
        self._key_span = {}          # khoá hình (int64) -> (start, count)
        self._key_cmds = {}          # khoá hình -> lệnh vẽ (giữ lại khi sprite chưa kịp giải mã)
        self.terrain = None          # uint8 [tex_h, tex_w, 3]
        self.index = None            # uint16 [tex_h, tex_w]
        self.out_id = self.map_w * self.map_h

    # ---- địa hình ------------------------------------------------------------------------
    def _tile_ops(self):
        """Lệnh vẽ địa hình theo thứ tự sâu: (ảnh, x, y) gốc; kèm khoảng y để chia dải."""
        hdr = self.hdr
        terr, shp = hdr["terrain"], hdr["shape"]
        tdx, tdy, tb = hdr.get("tile_dx"), hdr.get("tile_dy"), hdr.get("tile_border")
        w, h = self.map_w, self.map_h
        ys, xs = np.mgrid[0:h, 0:w]
        order = np.lexsort(((xs + ys).ravel(), (ys - xs).ravel()))
        rv = self.resolver
        ops = []
        for k in order.tolist():
            y, x = divmod(k, w)
            tsrc = rv.terrain_source(int(terr[y, x]))
            if tsrc is None:
                continue
            shape = int(shp[y, x])
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
            if tdx is not None:
                px = int(tdx[y, x]); py = int(tdy[y, x]) + self.Y0 - TILE_H // 2
            else:
                px = (x + y) * (TILE_W // 2)
                py = (y - x) * (TILE_H // 2) - int(self.elev[y, x]) * ELEV_H + self.Y0 - TILE_H // 2
            ops.append((im, px - hx, py - hy))
            if tb is not None:
                b = int(tb[y, x])
                if b:
                    bo = self._border_op(b & 0xF, b >> 4, shape, px, py)
                    if bo is not None:
                        ops.append(bo)
        return ops

    def _border_op(self, border_id, config, shape, px, py):
        from mapcap.video_render import BORDER_SUBSTITUTE
        if border_id in BORDER_SUBSTITUTE:
            border_id = BORDER_SUBSTITUTE[border_id]
            if border_id is None:
                return None
        if not (0 <= border_id < len(self.dat.borders)):
            return None
        bd = self.dat.borders[border_id]
        if not bd.enabled or bd.slp_id < 0 or config > 11:
            return None
        fc, ac, fidx = bd.frames[min(shape, 18)][config]
        if fc <= 0:
            fc, ac, fidx = bd.frames[0][config]
            if fc <= 0:
                return None
        fr = self.store.frame(bd.slp_id, fidx)
        if fr is None:
            return None
        im, hx, hy = fr
        return (im, px - hx, py - hy)

    def build_terrain(self, progress=None):
        ops = self._tile_ops()
        ys0 = np.array([o[2] for o in ops])
        ys1 = ys0 + np.array([o[0].height for o in ops])
        W, H = self.full_w, self.full_h
        ts = self.ts
        out = Image.new("RGB", (self.tex_w, self.tex_h), (0, 0, 0))
        band = BAND
        for b0 in range(0, H, band):
            b1 = min(H, b0 + band)
            img = Image.new("RGB", (W, b1 - b0), (0, 0, 0))
            sel = np.nonzero((ys1 > b0) & (ys0 < b1))[0]
            for i in sel.tolist():
                im, x, y = ops[i]
                paste(img, im, x, y - b0)
            if ts != 1.0:
                tw = self.tex_w
                th = int(round(b1 * ts)) - int(round(b0 * ts))
                img = img.resize((tw, max(1, th)), Image.BOX)
            out.paste(img, (0, int(round(b0 * ts))))
            if progress:
                progress(b1 / H)
        self.terrain = np.asarray(out)

    def build_index(self):
        """Mỗi pixel ảnh địa hình thuộc ô nào (uint16; out_id = ngoài bản đồ). Giống VideoRenderer._build_index_map."""
        hdr = self.hdr
        w, h = self.map_w, self.map_h
        Wt, Ht = self.tex_w, self.tex_h
        s = self.ts
        hw, hh = TILE_W * s / 2, TILE_H * s / 2
        sw = int(np.ceil(TILE_W * s)) + 2
        out = self.out_id
        idx = np.full((Ht, Wt), out, np.uint16)
        yy_s, xx_s = np.mgrid[0:int(np.ceil(TILE_H * s)) + 2, 0:sw]
        cx, cy = (sw - 1) / 2, (int(np.ceil(TILE_H * s)) + 1) / 2
        diamond = (np.abs(xx_s - cx) / (hw + 0.6) + np.abs(yy_s - cy) / (hh + 0.6)) <= 1.0
        dh = diamond.shape[0]
        ys_all, xs_all = np.mgrid[0:h, 0:w]
        order = np.lexsort(((xs_all + ys_all).ravel(), (ys_all - xs_all).ravel()))
        tdx, tdy = hdr.get("tile_dx"), hdr.get("tile_dy")
        stamps = {}
        for k in order.tolist():
            y, x = divmod(k, w)
            elev = int(self.elev[y, x])
            if tdx is not None:
                px = int(tdx[y, x]); py = int(tdy[y, x]) + self.Y0 - TILE_H // 2
            else:
                px = (x + y) * (TILE_W // 2); py = (y - x) * (TILE_H // 2) - elev * ELEV_H + self.Y0 - TILE_H // 2
            vx = int(round(px * s)) - 1
            vy = int(round(py * s)) - 1
            skirt = int(round(elev * ELEV_H * s)) + (int(round(ELEV_H * s)) if elev else 0)
            x0, y0 = max(vx, 0), max(vy, 0)
            x1, y1 = min(vx + sw, Wt), min(vy + dh + skirt, Ht)
            if x1 <= x0 or y1 <= y0:
                continue
            stamp = stamps.get(skirt)
            if stamp is None:
                if skirt:
                    stamp = np.zeros((dh + skirt, sw), bool)
                    stamp[:dh] = diamond
                    stamp[dh // 2:dh // 2 + skirt + 1, :] |= diamond[dh // 2]
                    stamp[dh:dh + skirt] = diamond[dh // 2]
                else:
                    stamp = diamond
                stamps[skirt] = stamp
            sub = stamp[y0 - vy:y1 - vy, x0 - vx:x1 - vx]
            idx[y0:y1, x0:x1][sub] = k
        # lấp khe 1-3 px giữa các ô bằng ô kề (bằng lát cắt, không sao chép cả ảnh)
        for _ in range(3):
            holes = idx == out
            if not holes.any():
                break
            for (sy, sx) in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                dst = (slice(max(sy, 0), Ht + min(sy, 0)), slice(max(sx, 0), Wt + min(sx, 0)))
                src = (slice(max(-sy, 0), Ht + min(-sy, 0)), slice(max(-sx, 0), Wt + min(-sx, 0)))
                d = idx[dst]
                hv = holes[dst]
                sv = idx[src]
                fill = hv & (sv != out)
                d[fill] = sv[fill]
                hv &= ~fill
        self.index = idx

    # ---- mảnh sprite ---------------------------------------------------------------------
    def _slot(self, skey):
        s = self.slot_of.get(skey)
        if s is not None:
            return s
        if self.deadline is not None and time.perf_counter() > self.deadline and not self.store.cached(skey):
            return None                                       # hết ngân sách giải mã của khung này: để khung sau
        fr = self.store.frame(*skey)
        if fr is None:
            self.slot_of[skey] = -1
            return -1
        im, hx, hy = fr
        s = len(self.slot_keys)
        self.slot_of[skey] = s
        self.slot_keys.append(skey)
        self.slot_w.append(im.width)
        self.slot_h.append(im.height)
        return s

    def slot_image(self, s):
        """(bytes RGBA, w, h) của slot s."""
        fr = self.store.frame(*self.slot_keys[s])
        im = fr[0]
        return im.tobytes(), im.width, im.height

    def _span(self, key):
        sp = self._key_span.get(key)
        if sp is not None:
            return sp
        cmds = self._key_cmds.get(key)
        if cmds is None:
            if key & (1 << 62):
                f = _unpack(_D_FIELDS, key & ((1 << 62) - 1))
                cmds = self.resolver.commands(f["dat"], -1, -1, f["angle"], -1, -1, f["color"], -1, bool(f["dead"]),
                                              0, 2, 1.0, 0)
            else:
                f = _unpack(_G_FIELDS, key)
                cmds = self.resolver.commands(-1, f["gid"], f["frame"], f["angle"], f["gid2"], f["frame2"], f["color"],
                                              f["stage"], False, 0, 2, 1.0, 0)
            self._key_cmds[key] = cmds
        slots = [self._slot(skey) for skey, _X, _Y in cmds]
        if any(sl is None for sl in slots):
            return None
        P = self._pieces
        start = len(P["slot"])
        for sl, (skey, X, Y) in zip(slots, cmds):
            if sl < 0:
                continue
            _im, hx, hy = self.store.frame(*skey)
            P["slot"].append(sl)
            P["dx"].append(X - hx)
            P["dy"].append(Y - hy)
        sp = (start, len(P["slot"]) - start)
        self._key_span[key] = sp
        self._key_cmds.pop(key, None)
        self._piece_np = None
        return sp

    def _pieces_np(self):
        if self._piece_np is None:
            P = self._pieces
            self._piece_np = (np.array(P["slot"], np.int32), np.array(P["dx"], np.float32),
                              np.array(P["dy"], np.float32))
        return self._piece_np

    def anchors(self, U):
        x, y, z = U["x"].astype(np.float32), U["y"].astype(np.float32), U["z"].astype(np.float32)
        return (x + y) * (TILE_W // 2), (y - x) * (TILE_H // 2) - z * ELEV_H + self.Y0

    def instances(self, U, defs, bright, budget=None):
        """U: mảng unit (đã lọc, đã sắp theo chiều sâu); bright: độ sáng từng unit (-1 = sương mù theo pixel).
        budget: số giây tối đa giải mã sprite mới (None = không giới hạn). Khoá hình chưa kịp giải mã thì unit dùng
        hình của lần dựng trước (theo uid), chưa từng vẽ thì tạm chưa hiện.
        Trả về (slot, x0, y0, bright, unit_idx) cho từng mảnh sprite theo đúng thứ tự vẽ."""
        self.deadline = None if budget is None else time.perf_counter() + budget
        n = len(U)
        if n == 0:
            e = np.zeros(0, np.float32)
            return np.zeros(0, np.int32), e, e, e, np.zeros(0, np.int64)
        di = np.clip(U["def"], 0, defs["n"] - 1)
        utype = np.where(U["def"] < defs["n"], defs["utype"][di], -1)
        dat_id = defs["dat_id"][di]
        hp_max = defs["hp_max"][di]
        gid = U["gid"].astype(np.int32)
        has_g = gid >= 0
        total = self.gtotal[np.clip(gid, 0, len(self.gtotal) - 1)]
        building = has_g & (utype == 80) & (U["status"] == 0) & (hp_max > 0)
        frac = np.clip(U["hp"] / np.maximum(hp_max, 1e-6), 0.0, 0.999)
        stage = np.where(building, np.minimum((frac * total).astype(np.int32), total - 1), -1)
        dead = (~has_g) & np.isin(utype, DEAD_TYPES) & ((U["status"] >= 3) | (U["hp"] <= 0))
        owner = U["owner"].astype(np.int32)
        color = self.color_lut[np.clip(owner, 0, len(self.color_lut) - 1)]
        color = np.where((owner > 0) & (owner < len(self.color_lut)), color, 0)
        key = _pack(_G_FIELDS, {"gid": gid, "frame": U["frame"], "angle": U["angle"], "gid2": U["gid2"],
                                "frame2": U["frame2"], "color": color, "stage": stage})
        key_d = _pack(_D_FIELDS, {"dat": dat_id, "angle": U["angle"], "color": color, "dead": dead}) | _NOG
        key = np.where(has_g, key, key_d)
        uk, inv = np.unique(key, return_inverse=True)
        starts = np.zeros(len(uk), np.int64)
        counts = np.zeros(len(uk), np.int64)
        missing = np.zeros(len(uk), bool)
        for j, k in enumerate(uk.tolist()):
            sp = self._span(k)
            if sp is None:
                missing[j] = True
            else:
                starts[j], counts[j] = sp
        self.deadline = None
        self.deferred = int(missing.sum())
        us, uc = starts[inv], counts[inv]
        if budget is not None:
            miss_u = missing[inv]
            if miss_u.any() and self._prev is not None and len(self._prev[0]):
                pu, ps, pc = self._prev
                uid = U["uid"][miss_u]
                pos = np.clip(np.searchsorted(pu, uid), 0, len(pu) - 1)
                found = pu[pos] == uid
                idx = np.nonzero(miss_u)[0]
                us[idx[found]] = ps[pos[found]]
                uc[idx[found]] = pc[pos[found]]
            o = np.argsort(U["uid"], kind="stable")
            self._prev = (U["uid"][o].copy(), us[o].copy(), uc[o].copy())
        p_slot, p_dx, p_dy = self._pieces_np()
        tot = int(uc.sum())
        if tot == 0:
            e = np.zeros(0, np.float32)
            return np.zeros(0, np.int32), e, e, e, np.zeros(0, np.int64)
        unit_idx = np.repeat(np.arange(n), uc)
        offs = np.cumsum(uc) - uc
        piece = np.arange(tot) - np.repeat(offs, uc) + np.repeat(us, uc)
        ax, ay = self.anchors(U)
        x0 = np.floor(ax[unit_idx] + p_dx[piece] + 0.5)
        y0 = np.floor(ay[unit_idx] + p_dy[piece] + 0.5)
        return p_slot[piece], x0, y0, np.asarray(bright, np.float32)[unit_idx], unit_idx

    # ---- tiện ích ------------------------------------------------------------------------
    def tile_of(self, U):
        tx = np.floor(U["x"]).astype(np.int32)
        ty = np.floor(U["y"]).astype(np.int32)
        inside = (tx >= 0) & (tx < self.map_w) & (ty >= 0) & (ty < self.map_h)
        return np.clip(tx, 0, self.map_w - 1), np.clip(ty, 0, self.map_h - 1), inside

    def depth_order(self, U):
        x, y = U["x"], U["y"]
        return np.lexsort((x + y, y - x))

    def world_of_tile(self, tx, ty):
        """Toạ độ thế giới tâm ô (không tính độ cao)."""
        return (tx + ty + 1) * (TILE_W // 2), (ty - tx) * (TILE_H // 2) + self.Y0

    def player_rgb(self, owner_index):
        cid = int(self.color_lut[owner_index]) if 0 < owner_index < len(self.color_lut) else 0
        return tuple(int(v) for v in self.pal[min(16 * (cid + 1) + 4, 255)])

    def outline(self):
        w, h = self.map_w, self.map_h
        Y0 = self.Y0
        return [(0, Y0), (w * (TILE_W // 2), Y0 - w * (TILE_H // 2)),
                ((w + h) * (TILE_W // 2), Y0 + (h - w) * (TILE_H // 2)), (h * (TILE_W // 2), Y0 + h * (TILE_H // 2))]
