"""Xuất trận `.aoerec` sang định dạng `.aoeweb` cho trình xem trên điện thoại (mobile/web), và gói hình game.

Trình xem web không chạy lại logic chọn đồ hoạ của game: máy tính tính sẵn "khoá hình" của mỗi unit (đồ hoạ, khung,
hướng, màu, giai đoạn xây...) bằng đúng mã của trình xem máy tính (replay.world), và bảng khoá -> mảnh sprite
(slp, khung, màu, lật, độ lệch). Điện thoại chỉ giải mã SLP từ gói hình và vẽ.

File `.aoeweb` (mọi số nguyên little-endian):
    "AOEWEB01" | u32 độ dài JSON | JSON (utf-8) | các phần nhị phân: JSON["sections"][tên] = [vị trí tính từ
    đầu vùng dữ liệu (ngay sau JSON), cỡ]
Phần "z" = nén zlib (trình duyệt mở bằng DecompressionStream("deflate")); ảnh địa hình là JPEG.
    times   z: i32 giờ game[n] | f32 thời gian phát[n]
    keys    z: u32 đầu[k] | u16 số mảnh[k] | mảnh: i32 slp | u16 khung | u8 màu | u8 lật | i16 dx | i16 dy
    seen    z: mỗi đội: u32 số | i32 uid[] | i32 mẫu[]
    statics z: chuỗi bản ghi: i32 mẫu bắt đầu | u8 toàn bộ? | u32 số hàng | hàng... | u32 số bỏ | i32 uid[]
    index   z: u16 [h][w] chỉ số ô theo pixel (ở tỉ lệ index.scale); out = map_w * map_h
    cN      z: khối CHUNK mẫu; mẫu đầu là điểm mốc (toàn bộ unit + tầm nhìn), các mẫu sau chỉ phần đổi
    hN, sd, i<slp> (từ phiên bản 2): dữ liệu HUD (bảng tỉ số, công nghệ, thông tin unit), xem mapcap/webhud.py
Một khối: u32 số mẫu, rồi từng mẫu:
    u8 đầy đủ? | u32 số hàng unit | hàng (cột): i32 uid[] u32 khoá[] f32 x[] f32 y[] f32 z[] u8 chủ[] u8 cờ[]
    | u32 số bỏ | i32 uid[] | u32 số ô tầm nhìn đổi | (đầy đủ: u32 vis[h*w]) hoặc u32 ô[] u32 giá trị mới[]
Cờ hàng: 1 doppelganger, 2 công trình, 4 hiện trong sương mù (fog_visible), 8 không vẽ, 16 doppel thay vật thể thật.
"""
import io
import json
import os
import struct
import time
import zlib

import numpy as np

from .rawrec import UNIT_DT

MAGIC = b"AOEWEB01"
WEB_VERSION = 2                 # 2: thêm dữ liệu HUD (webhud)
CHUNK = 250                     # mẫu mỗi khối (10 s): tua = mở một khối + áp tối đa 249 mẫu
TERRAIN_BUDGET = 12e6           # ảnh địa hình trên điện thoại tối đa ~12 MP
TILE = 2048                     # cắt ảnh địa hình thành ô 2048 px (mọi GPU điện thoại đều nhận)
INDEX_SCALE_DIV = 2             # bản đồ chỉ số ô: nhỏ hơn ảnh địa hình 2 lần (đủ cho mép sương mù)
F_DOP, F_BLD, F_FOGVIS, F_HIDE, F_DOPOK = 1, 2, 4, 8, 16
ROW_DT = np.dtype([("uid", "<i4"), ("key", "<u4"), ("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("owner", "u1"),
                   ("flags", "u1")])
_ROW_V = np.dtype((np.void, ROW_DT.itemsize))   # một hàng ROW_DT như một khối byte (so sánh cả hàng)

SPR_MAGIC = b"AOESPR01"
FOG_DIM = 0.43                  # như replay.viewer.FOG_DIM (không import viewer: kéo theo pygame / moderngl)


def _z(b):
    return zlib.compress(b, 6)


def _rows_bytes(R):
    """Hàng ROW_DT -> bytes theo cột (nén tốt hơn theo hàng)."""
    return b"".join(np.ascontiguousarray(R[n]).tobytes() for n in ROW_DT.names)


class _Keys:
    """Khoá hình int64 -> số thứ tự gọn; bảng mảnh sprite của từng khoá."""

    def __init__(self, world, store):
        self.world, self.store = world, store
        self.ids = {}
        self.spans = []                    # (đầu, số mảnh)
        self.pieces = []                   # (slp, khung, màu, lật, dx, dy)
        self.hot = {}

    def _hotspot(self, slp_id, idx, mirror):
        k = (slp_id, idx, mirror)
        v = self.hot.get(k)
        if v is None:
            s = self.store.slp(slp_id)
            v = False
            if s is not None and 0 <= idx < s.num_frames:
                w, h, hx, hy = s.frame_size(idx)
                if w > 0 and h > 0:
                    v = (w - 1 - hx if mirror else hx, hy)
            self.hot[k] = v
        return v

    def id_of(self, key):
        i = self.ids.get(key)
        if i is None:
            i = len(self.spans)
            self.ids[key] = i
            start = len(self.pieces)
            for (slp_id, idx, color, mirror), X, Y in self.world.key_commands(key):
                hs = self._hotspot(slp_id, idx, mirror)
                if hs:
                    self.pieces.append((slp_id, idx, color, int(mirror), int(round(X - hs[0])), int(round(Y - hs[1]))))
            self.spans.append((start, len(self.pieces) - start))
        return i

    def ids_of(self, keys):
        # vật thể tĩnh: hàng chục nghìn hàng, vài trăm khoá; cấp số theo thứ tự gặp đầu như trước
        u, first, inv = np.unique(keys, return_index=True, return_inverse=True)
        ids = np.empty(len(u), np.uint32)
        for j in np.argsort(first, kind="stable").tolist():
            ids[j] = self.id_of(u[j].item())
        return ids[inv.ravel()]

    def to_bytes(self):
        n = len(self.spans)
        sp = np.array(self.spans, np.int64).reshape(n, 2)
        pc = np.array(self.pieces, np.int64).reshape(len(self.pieces), 6)
        out = struct.pack("<II", n, len(self.pieces))
        out += sp[:, 0].astype("<u4").tobytes() + sp[:, 1].astype("<u2").tobytes()
        out += pc[:, 0].astype("<i4").tobytes() + pc[:, 1].astype("<u2").tobytes() + pc[:, 2].astype("u1").tobytes()
        out += pc[:, 3].astype("u1").tobytes() + pc[:, 4].astype("<i2").tobytes() + pc[:, 5].astype("<i2").tobytes()
        return out


class _RowMaker:
    """Mảng UNIT_DT -> hàng ROW_DT (khoá hình, cờ). Doppelganger không có sprite (gid -1) mượn sprite công trình thật
    cùng def (đúng kiến trúc nền văn minh), như replay.viewer._doppel_sprites."""

    def __init__(self, data, world, keys):
        self.data, self.world, self.keys = data, world, keys
        self.dop_at = {}                   # (def, x, y) -> (gid, frame) công trình thật
        self.dop_def = {}                  # def -> (gid, frame) gần nhất

    def rows(self, U):
        _v, defs = self.data.def_arrays()
        n = len(U)
        R = np.zeros(n, ROW_DT)
        if n == 0:
            return R
        w = self.world
        di = np.clip(U["def"], 0, defs["n"] - 1)
        ok_def = (U["def"] >= 0) & (U["def"] < defs["n"])
        ut = np.where(ok_def, defs["utype"][di], -1)
        k25 = U["kind"] == 25
        real_b = ok_def & (ut == 80) & ~k25 & (U["gid"] >= 0)
        if real_b.any():
            B = U[real_b]
            for dd, x, y, g, f in zip(B["def"].tolist(), B["x"].tolist(), B["y"].tolist(), B["gid"].tolist(),
                                      B["frame"].tolist()):
                self.dop_at[(dd, int(x), int(y))] = (g, f)
                self.dop_def[dd] = (g, f)
        need = k25 & (U["gid"] < 0)
        if need.any():
            U = U.copy()
            for i in np.nonzero(need)[0].tolist():
                dd = int(U["def"][i])
                gf = self.dop_at.get((dd, int(U["x"][i]), int(U["y"][i]))) or self.dop_def.get(dd)
                if gf is not None:
                    U["gid"][i], U["frame"][i] = gf
        tx, ty, inside = w.tile_of(U)
        R["uid"] = U["uid"]
        R["key"] = self.keys.ids_of(w.unit_keys(U, defs))
        R["x"], R["y"], R["z"] = U["x"], U["y"], U["z"]
        R["owner"] = np.clip(U["owner"], 0, 255)
        fl = np.zeros(n, np.uint8)
        fl |= np.where(k25, F_DOP, 0).astype(np.uint8)
        fl |= np.where(ut == 80, F_BLD, 0).astype(np.uint8)
        fl |= np.where(defs["fogvis"][di] & ok_def, F_FOGVIS, 0).astype(np.uint8)
        fl |= np.where(~inside | ((ut == 60) & (U["gid"] < 0)), F_HIDE, 0).astype(np.uint8)
        fl |= np.where(k25 & (ut != 25), F_DOPOK, 0).astype(np.uint8)
        R["flags"] = fl
        return R


def _terrain(world, budget=TERRAIN_BUDGET):
    """Dựng ảnh địa hình ở tỉ lệ vừa ngân sách điện thoại, cắt ô JPEG; bản đồ chỉ số ô nhỏ hơn 2 lần."""
    from PIL import Image
    W, H = world.full_w, world.full_h
    ts = 0.5
    while W * H * ts * ts > budget and ts > 1 / 16:
        ts /= 2
    world.ts = ts
    world.tex_w, world.tex_h = int(round(W * ts)), int(round(H * ts))
    world.build_terrain()
    img = Image.fromarray(world.terrain)
    tiles = []
    for y in range(0, world.tex_h, TILE):
        for x in range(0, world.tex_w, TILE):
            t = img.crop((x, y, min(x + TILE, world.tex_w), min(y + TILE, world.tex_h)))
            b = io.BytesIO()
            t.save(b, "JPEG", quality=88)
            tiles.append(((x, y, t.width, t.height), b.getvalue()))
    terr = {"scale": ts, "w": world.tex_w, "h": world.tex_h}
    if getattr(world, "keep_rgb", False):
        world.terrain_rgb = world.terrain          # test: so với bộ chuyển trên điện thoại (trước khi nén JPEG)
    world.terrain = None
    its = ts / INDEX_SCALE_DIV
    world.ts = its
    world.tex_w, world.tex_h = int(round(W * its)), int(round(H * its))
    world.build_index()
    idx = world.index
    world.index = None
    return terr, tiles, {"scale": its, "w": int(idx.shape[1]), "h": int(idx.shape[0])}, idx


def _palette_rgb(world, owner):
    r, g, b = world.player_rgb(owner)
    return "#%02x%02x%02x" % (r, g, b)


def _records(path):
    """(tag, payload, vị trí byte đã đọc tới) của mọi bản ghi theo thứ tự file, khối 'B' mở ra tại chỗ. Dừng êm ở bản
    ghi cụt / hỏng (như ReplayData._index)."""
    from . import safeload
    from .rawrec import MAGIC as REC_MAGIC, decode_block
    with open(path, "rb") as f:
        data = f.read()
    if data[:len(REC_MAGIC)] != REC_MAGIC:
        raise ValueError("không phải file .aoerec")
    pos = len(REC_MAGIC)
    size = len(data)
    while pos + 5 <= size:
        tag = data[pos:pos + 1]
        n = struct.unpack_from("<I", data, pos + 1)[0]
        if pos + 5 + n > size:
            return
        raw = data[pos + 5:pos + 5 + n]
        pos += 5 + n
        try:
            if tag == b"B":
                inner = decode_block(raw)
            elif tag in (b"H", b"D", b"S", b"Q", b"U", b"F"):
                inner = [(tag, safeload.zlib_loads(raw))]
            else:
                continue
        except Exception:  # noqa: BLE001
            return
        for t, pl in inner:
            yield t, pl, pos / size


class _Stream:
    """Dữ liệu trận đọc tuần tự một lượt (không mở file như replay.data.ReplayData): defs, chỉ số, bản ghi tĩnh, giờ
    từng mẫu, công trình mỗi đội đã thấy. Dùng lại các hàm của ReplayData (cùng tên trường)."""

    def __init__(self, header):
        from replay.data import ReplayData
        from replay.library import teams_from_header
        self._rd = ReplayData
        self.header = header
        self.map_w, self.map_h = int(header["map_w"]), int(header["map_h"])
        self.defs = {}
        self._def_ver = 0
        self.f_off, self.f_t, self.f_at, self.f_r = [], [], [], []
        self.s_first = []
        self.stats = {}
        self.final_tech_times = {}
        self.players = ReplayData._make_players(self)
        self.teams = teams_from_header(header)
        self.seen = [dict() for _ in self.teams]
        self._team_vm = []
        for t in self.teams:
            vm = 0
            for i in t:
                if 0 <= i < len(self.players):
                    vm |= int(self.players[i].visible_mask)
            self._team_vm.append(vm)

    n_frames = property(lambda self: len(self.f_off))

    def __getattr__(self, name):                 # _apply_defs, def_arrays, _mark_seen, players_at, age_events...
        f = getattr(self._rd, name)
        return f.__get__(self, type(self)) if callable(f) else f


class WebBuilder:
    """.aoerec -> .aoeweb trong MỘT lượt đọc tuần tự các bản ghi (feed), giống hệt bộ chuyển trên điện thoại
    (mobile/web/js/rec/build.js, cùng thứ tự xử lý, cùng kết quả từng byte trừ ảnh JPEG địa hình): mỗi bản ghi tĩnh
    'S' / 'Q' xuất ngay khi gặp (áp từ mẫu kế tiếp), mỗi mẫu 'F' áp vào trạng thái rồi xuất ngay.
    Trước v19: lập chỉ mục cả file (ReplayData._index) rồi đọc lại từng mẫu, vật thể tĩnh xuất sau cùng."""

    def __init__(self, header, graphics, game_dir, info=None, log=None, keep_terrain=False):
        from replay.data import FrameState
        from replay.world import World
        from .webhud import HudExport
        dat, store, pal = graphics
        self.log = log or (lambda m: None)
        self.game_dir, self.info = game_dir, info
        self.d = d = _Stream(header)
        self.w = w = World(header, dat, store, pal)
        w.keep_rgb = keep_terrain
        self.sections, self.blobs, self.pos = {}, [], 0
        terr, tiles, self.idx_info, idx = _terrain(w)
        for k, (rect, jpg) in enumerate(tiles):
            self._add(f"t{k}", jpg)
        terr["tiles"] = [{"x": r[0], "y": r[1], "w": r[2], "h": r[3], "section": f"t{k}"}
                         for k, (r, _j) in enumerate(tiles)]
        self.terr = terr
        self._add("index", _z(idx.astype("<u2").tobytes()))
        self.idx_info["section"] = "index"
        self.keys = _Keys(w, store)
        self.maker = _RowMaker(d, w, keys=self.keys)
        self.hud = HudExport(d, w, CHUNK)
        self.st = FrameState(d.map_w, d.map_h)
        self.acc_r = 0.0                         # thời gian phát (giờ thật, bỏ đoạn tạm dừng)
        self.frozen = 0.0
        self.broken = False                      # bản ghi hỏng: dừng ở đó như ReplayData._index
        self.cur = {}                            # uid -> bytes hàng ROW_DT đã xuất gần nhất
        self.prev_vis = None
        self.chunks = []                         # khối đã đủ (bytes, chưa nén)
        self.buf = None                          # các mẫu của khối đang dựng
        self.statics = None                      # mảng vật thể tĩnh hiện tại (UNIT_DT)
        self.scur = None                         # hàng tĩnh đã xuất, sắp theo uid
        self.srecs = []

    def _add(self, name, b):
        self.sections[name] = [self.pos, len(b)]
        self.blobs.append(b)
        self.pos += len(b)

    def feed(self, tag, p):
        if self.broken:
            return
        try:
            if tag == b"D":
                self.d._apply_defs(p)
            elif tag in (b"S", b"Q"):
                self._static(tag, p)
            elif tag == b"U":
                fi_next = self.d.n_frames
                for idx, stv in p.items():
                    e = self.d.stats.setdefault(int(idx), ([], []))
                    e[0].append(fi_next)
                    e[1].append(stv)
            elif tag == b"F":
                self._frame(p)
        except _Broken:
            self.broken = True

    def _static(self, tag, p):
        from replay.data import _apply_static_delta, normalize_units
        d = self.d
        first = d.n_frames
        d.s_first.append(first)
        units = normalize_units(p.get("units"))
        if tag == b"S" or self.statics is None:
            self.statics = units
        else:
            self.statics = _apply_static_delta(self.statics, units, p.get("removed"))
        S = self.statics
        R = self.maker.rows(S)
        scur = self.scur
        if scur is None:
            out, rem = R, []
        else:
            pu = scur["uid"]
            if len(pu):
                k = np.minimum(np.searchsorted(pu, R["uid"]), len(pu) - 1)
                same = (pu[k] == R["uid"]) & (scur.view(_ROW_V)[k] == R.view(_ROW_V))
            else:
                same = np.zeros(len(R), bool)
            out = R[~same]                         # giữ thứ tự hàng (điện thoại vẽ theo thứ tự khi trùng chỗ)
            rem = pu[~np.isin(pu, R["uid"])].tolist()
        self.scur = R[np.argsort(R["uid"], kind="stable")]
        self.srecs.append(struct.pack("<iBI", first, 0 if self.srecs else 1, len(out)) + _rows_bytes(out) +
                          struct.pack("<I", len(rem)) + np.array(rem, "<i4").tobytes())
        self.hud.static(first, S)

    def _frame(self, p):
        from replay.data import MAX_STEP, PAUSE_GAP, SEEN_EVERY, normalize_units
        d, st = self.d, self.st
        fi = d.n_frames
        try:
            st.apply(p, fi)
            if fi % SEEN_EVERY == 0:
                d._mark_seen(st, fi)
            t, at = int(p["t"]), float(p["at"])
        except Exception as e:  # noqa: BLE001
            raise _Broken() from e
        if fi:
            dr = min(max(at - d.f_at[-1], 0.0), MAX_STEP)
            if t == d.f_t[-1]:
                self.frozen += dr
                if self.frozen > PAUSE_GAP:
                    dr = 0.0
            else:
                self.frozen = 0.0
            self.acc_r += dr
        d.f_t.append(t)
        d.f_at.append(at)
        d.f_r.append(self.acc_r)
        d.f_off.append(None)
        self.hud.frame(fi, st)
        full = fi % CHUNK == 0
        if full:
            self._flush_chunk()
            self.buf = []
        removed = []
        if full or p.get("full_units"):
            U = st.units()
            R = self.maker.rows(U)
            if p.get("full_units") and not full:
                alive = set(U["uid"].tolist())
                removed = [u for u in self.cur if u not in alive]
            self.cur = {int(r["uid"]): r.tobytes() for r in R}
            out = R
        else:
            ch = normalize_units(p.get("units"))
            rem = p.get("removed")
            if rem is not None and len(rem):
                for u in rem.tolist():
                    if self.cur.pop(int(u), None) is not None:
                        removed.append(int(u))
            R = self.maker.rows(ch)
            keep = []
            for i, r in enumerate(R):
                b = r.tobytes()
                u = int(r["uid"])
                if self.cur.get(u) != b:
                    self.cur[u] = b
                    keep.append(i)
            out = R[keep]
        V = st.vis
        parts = [struct.pack("<BI", 1 if full else 0, len(out)), _rows_bytes(out),
                 struct.pack("<I", len(removed)), np.array(removed, "<i4").tobytes()]
        if full or self.prev_vis is None:
            parts += [struct.pack("<I", V.size), V.astype("<u4").tobytes()]
        else:
            ch_idx = np.flatnonzero(V != self.prev_vis)
            parts += [struct.pack("<I", len(ch_idx)), ch_idx.astype("<u4").tobytes(),
                      V.ravel()[ch_idx].astype("<u4").tobytes()]
        self.prev_vis = V.copy()
        self.buf.append(b"".join(parts))

    def _flush_chunk(self):
        if self.buf:
            self.chunks.append(struct.pack("<I", len(self.buf)) + b"".join(self.buf))
        self.buf = None

    def finish(self, file_name):
        """Bytes của file .aoeweb."""
        d, w, hud = self.d, self.w, self.hud
        n = d.n_frames
        if n == 0:
            raise ValueError("trận không có mẫu nào")
        self._flush_chunk()
        d.final_tech_times = {k: dict(v) for k, v in self.st.tech_times.items()}
        for k, c in enumerate(self.chunks):
            self._add(f"c{k}", _z(c))
        for k, c in enumerate(hud.chunks):
            self._add(f"h{k}", _z(json.dumps(c, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                                  .encode("utf-8")))
        self._add("statics", _z(struct.pack("<I", len(self.srecs)) + b"".join(self.srecs)))
        self._add("times", _z(np.array(d.f_t, "<i4").tobytes() + np.array(d.f_r, "<f4").tobytes()))
        sb = b""
        for seen in d.seen:
            items = sorted(seen.items())
            sb += struct.pack("<I", len(items)) + np.array([u for u, _f in items], "<i4").tobytes() + \
                np.array([f for _u, f in items], "<i4").tobytes()
        self._add("seen", _z(sb))
        self._add("keys", _z(self.keys.to_bytes()))
        self._add("sd", _z(json.dumps(hud.sd, separators=(",", ":"), allow_nan=False).encode("utf-8")))
        hud_meta = hud.tables()
        hud_meta["icons"] = {}
        for sid, b in hud.icon_slps(self.game_dir).items():
            self._add(f"i{sid}", b)
            hud_meta["icons"][str(sid)] = f"i{sid}"
        hdr = d.header
        rec = d.recorder_index()
        rec_team = next((k for k, t in enumerate(d.teams) if rec in t), -1)
        teams = []
        for t in d.teams:
            vm = em = 0
            for i in t:
                vm |= int(d.players[i].visible_mask)
                em |= int(d.players[i].explored_mask)
            teams.append({"players": list(t), "vm": vm, "em": em})
        players = []
        for p in d.players:
            if p.index == 0:
                continue
            players.append({"index": p.index, "name": p.name, "color": _palette_rgb(w, p.index),
                            "color_id": int(w.color_lut[p.index]) if p.index < len(w.color_lut) else 0})
        meta = {
            "version": WEB_VERSION, "file": file_name, "info": self.info,
            "map_w": d.map_w, "map_h": d.map_h, "full_w": w.full_w, "full_h": w.full_h, "Y0": w.Y0,
            "reveal": bool(hdr.get("reveal")), "fog_dim": FOG_DIM, "frames": n, "chunk": CHUNK,
            "chunks": len(self.chunks), "terrain": self.terr, "index": self.idx_info, "players": players,
            "teams": teams, "rec_team": rec_team, "ages": [[r, i, a] for r, i, a in d.age_events()],
            "keys": len(self.keys.spans), "pieces": len(self.keys.pieces), "sections": self.sections,
            "hud": hud_meta, "civs": {str(k): v for k, v in hud.civs.items()},
        }
        js = json.dumps(meta, ensure_ascii=False, allow_nan=False).encode("utf-8")
        return MAGIC + struct.pack("<I", len(js)) + js + b"".join(self.blobs)


class _Broken(Exception):
    pass


def export_match(path, out_path, game_dir, log=None, progress=None):
    """Chuyển một trận .aoerec -> .aoeweb (một lượt, WebBuilder). Trả về dict thống kê. progress(0..1) theo phần file
    đã đọc."""
    from replay.library import match_info
    from replay.world import load_graphics
    log = log or (lambda m: None)
    prog = progress or (lambda f: None)
    t0 = time.time()
    b = None
    n = 0
    for tag, pl, frac in _records(path):
        if b is None:
            if tag != b"H":
                raise ValueError("file thiếu header")
            b = WebBuilder(pl, load_graphics(game_dir), game_dir, info=match_info(path), log=log)
            prog(0.05)
            continue
        b.feed(tag, pl)
        if tag == b"F":
            n += 1
            if (n & 255) == 0:
                prog(0.05 + 0.9 * frac)
    if b is None:
        raise ValueError("file thiếu header")
    data = b.finish(os.path.basename(path))
    tmp = out_path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, out_path)
    stats = {"seconds": round(time.time() - t0, 1), "size": len(data), "src_size": os.path.getsize(path),
             "frames": b.d.n_frames, "keys": len(b.keys.spans), "pieces": len(b.keys.pieces)}
    log(f"xuất web {os.path.basename(path)}: {stats}")
    return stats


def export_sprites(game_dir, out_path):
    """Gói hình cho điện thoại: mọi SLP của nhóm đồ hoạ + bảng màu, lấy từ chính bộ cài game của người dùng.
    Chỉ truyền thẳng giữa máy tính và điện thoại của họ, không đưa lên máy chủ hay cửa hàng ứng dụng.
        "AOESPR01" | u32 độ dài JSON | JSON {"version", "palette": [[r,g,b]*256], "slp": {id: [vị trí, cỡ]}} | dữ liệu
    (vị trí tính từ đầu vùng dữ liệu, ngay sau JSON)
    """
    from . import drs
    from .gamefiles import read_group
    files = read_group(game_dir, "graphics")
    pal = drs.load_palette(game_dir)
    slps = sorted((fid, b) for (ext, fid), b in files.items() if ext == "slp")
    index = {}
    off = 0
    for fid, b in slps:
        index[str(fid)] = [off, len(b)]
        off += len(b)
    meta = {"version": 1, "palette": [list(map(int, c)) for c in pal], "slp": index}
    js = json.dumps(meta, separators=(",", ":")).encode("utf-8")
    tmp = out_path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(SPR_MAGIC + struct.pack("<I", len(js)) + js)
        for _fid, b in slps:
            f.write(b)
    os.replace(tmp, out_path)
    return {"slp": len(slps), "size": os.path.getsize(out_path)}


GD_MAGIC = b"AOEGD001"
GAMEDATA_VERSION = 1


def export_gamedata(game_dir, out_path):
    """Gói dữ liệu game cho bộ chuyển trên điện thoại (mobile/web/js/rec/build.js), tạo một lần như gói hình: bảng đồ
    hoạ / unit / địa hình / viền / công nghệ / màu quân của empires.dat, chuỗi tên của language*.dll, SLP icon của
    interfac.drs. Cùng nguồn với WebBuilder (load_graphics) nên điện thoại chuyển trận ra đúng như máy tính.
        "AOEGD001" | u32 độ dài JSON | JSON | dữ liệu (icon: JSON["icons"][slp] = [vị trí, cỡ])
    """
    from replay.library import CIV_NAMES
    from replay.world import load_graphics
    from .lang import GameStrings
    from .webhud import ICON_SLPS
    from .gamefiles import read_group
    dat, _store, _pal = load_graphics(game_dir)
    strings = GameStrings(game_dir)
    st = {}
    for sid in range(1, 65536):
        v = strings.get(sid)
        if v:
            st[str(sid)] = v
    meta = {
        "version": GAMEDATA_VERSION,
        "colours": [[c.id, c.minimap_color] for c in dat.player_colours],
        "graphics": {str(g.id): [g.slp_id, g.frame_count, g.angle_count, g.mirroring_mode,
                                 [[dl.graphic_id, dl.offset_x, dl.offset_y] for dl in g.deltas]]
                     for g in dat.graphics.values()},
        "units": {str(u.id): [u.type, u.standing_graphic, u.dying_graphic, -1 if u.icon_id is None else u.icon_id,
                              u.lang_name, u.name] for u in dat.units.values()},
        "terrains": [[t.id, t.slp_id, t.terrain_to_draw, t.terrain_replacement_id, list(t.dims),
                      [[e.frame_count, e.angle_count, e.shape_id] for e in t.elevation_graphics]] for t in dat.terrains],
        "borders": [[b.enabled, b.slp_id, [[list(c) for c in row] for row in b.frames]] for b in dat.borders],
        "research": [[r.id, r.name, r.lang_name, r.time, r.location, r.icon, r.button, [list(c) for c in r.costs]]
                     for r in dat.research],
        "strings": st,
        "civs": {str(k): v for k, v in CIV_NAMES.items()},
    }
    files = read_group(game_dir, "interface")
    blobs, icons, off = [], {}, 0
    for sid in ICON_SLPS:
        b = files.get(("slp", sid))
        if b:
            icons[str(sid)] = [off, len(b)]
            blobs.append(b)
            off += len(b)
    meta["icons"] = icons
    js = json.dumps(meta, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    tmp = out_path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(GD_MAGIC + struct.pack("<I", len(js)) + js + b"".join(blobs))
    os.replace(tmp, out_path)
    return {"size": os.path.getsize(out_path), "graphics": len(meta["graphics"]), "units": len(meta["units"]),
            "strings": len(st)}
