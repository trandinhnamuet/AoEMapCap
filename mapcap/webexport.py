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
        return np.array([self.id_of(k) for k in keys.tolist()], np.uint32)

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


def export_match(path, out_path, game_dir, log=None, progress=None):
    """Chuyển một trận .aoerec -> .aoeweb. Trả về dict thống kê (cỡ, thời gian)."""
    from replay.data import ReplayData, normalize_units
    from replay.library import match_info
    from replay.world import World, load_graphics
    log = log or (lambda m: None)
    t0 = time.time()
    d = ReplayData(path)
    try:
        d._index()
        if d.n_frames == 0:
            raise ValueError("trận không có mẫu nào")
        dat, store, pal = load_graphics(game_dir)
        w = World(d.header, dat, store, pal)
        sections = {}
        blobs = []
        pos = [0]

        def add(name, b):
            sections[name] = [pos[0], len(b)]
            blobs.append(b)
            pos[0] += len(b)

        terr, tiles, idx_info, idx = _terrain(w)
        for k, (rect, jpg) in enumerate(tiles):
            add(f"t{k}", jpg)
        terr["tiles"] = [{"x": r[0], "y": r[1], "w": r[2], "h": r[3], "section": f"t{k}"}
                         for k, (r, _j) in enumerate(tiles)]
        add("index", _z(idx.astype("<u2").tobytes()))
        idx_info["section"] = "index"
        t_terrain = time.time() - t0

        keys = _Keys(w, store)
        maker = _RowMaker(d, w, keys)
        from .webhud import HudExport
        hud = HudExport(d, w, CHUNK)
        n = d.n_frames
        H, Wm = d.map_h, d.map_w
        # trạng thái theo uid: hàng đã xuất gần nhất (bỏ qua mẫu đổi máu / tài nguyên mà hình, vị trí không đổi)
        from replay.data import FrameState
        st = FrameState(Wm, H)
        cur = {}                                   # uid -> bytes hàng ROW_DT
        prev_vis = None
        chunks = []
        buf = None
        for fi in range(n):
            p = d.read_frame(fi)
            st.apply(p, fi)
            hud.frame(fi, st)
            full = fi % CHUNK == 0
            if full:
                if buf is not None:
                    chunks.append(buf)
                buf = [struct.pack("<I", min(CHUNK, n - fi))]
            removed = []
            if full or p.get("full_units"):
                U = st.units()
                R = maker.rows(U)
                if p.get("full_units") and not full:
                    alive = set(U["uid"].tolist())
                    removed = [u for u in cur if u not in alive]
                cur = {int(r["uid"]): r.tobytes() for r in R}
                out = R
            else:
                ch = normalize_units(p.get("units"))
                rem = p.get("removed")
                if rem is not None and len(rem):
                    for u in rem.tolist():
                        if cur.pop(int(u), None) is not None:
                            removed.append(int(u))
                R = maker.rows(ch)
                keep = []
                for i, r in enumerate(R):
                    b = r.tobytes()
                    u = int(r["uid"])
                    if cur.get(u) != b:
                        cur[u] = b
                        keep.append(i)
                out = R[keep]
            V = st.vis
            parts = [struct.pack("<BI", 1 if full else 0, len(out)), _rows_bytes(out),
                     struct.pack("<I", len(removed)), np.array(removed, "<i4").tobytes()]
            if full or prev_vis is None:
                parts += [struct.pack("<I", V.size), V.astype("<u4").tobytes()]
            else:
                ch_idx = np.flatnonzero(V != prev_vis)
                parts += [struct.pack("<I", len(ch_idx)), ch_idx.astype("<u4").tobytes(),
                          V.ravel()[ch_idx].astype("<u4").tobytes()]
            prev_vis = V.copy()
            buf.append(b"".join(parts))
            if progress and (fi & 255) == 0:
                progress(fi / n)
        chunks.append(buf)
        for k, c in enumerate(chunks):
            add(f"c{k}", _z(b"".join(c)))
        for k, c in enumerate(hud.chunks):
            add(f"h{k}", _z(json.dumps(c, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")))
        t_frames = time.time() - t0 - t_terrain

        # vật thể tĩnh: bản ghi đầu toàn bộ, sau đó chỉ phần đổi (kể cả các bản 'S' toàn bộ của file gốc)
        srecs = []
        scur = {}
        for si in range(len(d.s_first)):
            _ver, S = d.load_statics(si)
            R = maker.rows(S)
            new = {int(r["uid"]): r.tobytes() for r in R}
            if si == 0:
                out, rem = R, []
            else:
                keep = [i for i, r in enumerate(R) if scur.get(int(r["uid"])) != new[int(r["uid"])]]
                out = R[keep]
                rem = [u for u in scur if u not in new]
            scur = new
            srecs.append(struct.pack("<iBI", d.s_first[si], 1 if si == 0 else 0, len(out)) + _rows_bytes(out) +
                         struct.pack("<I", len(rem)) + np.array(rem, "<i4").tobytes())
        add("statics", _z(struct.pack("<I", len(srecs)) + b"".join(srecs)))

        add("times", _z(np.array(d.f_t, "<i4").tobytes() + np.array(d.f_r, "<f4").tobytes()))
        sb = b""
        for seen in d.seen:
            items = sorted(seen.items())
            sb += struct.pack("<I", len(items)) + np.array([u for u, _f in items], "<i4").tobytes() + \
                np.array([f for _u, f in items], "<i4").tobytes()
        add("seen", _z(sb))
        add("keys", _z(keys.to_bytes()))
        add("sd", _z(json.dumps(hud.statics_detail(), separators=(",", ":"), allow_nan=False).encode("utf-8")))
        hud_meta = hud.tables()
        hud_meta["icons"] = {}
        for sid, b in hud.icon_slps(game_dir).items():
            add(f"i{sid}", b)
            hud_meta["icons"][str(sid)] = f"i{sid}"

        info = match_info(path)
        hdr = d.header
        rec = d.recorder_index()
        rec_team = next((k for k, t in enumerate(d.teams) if rec in t), -1)
        teams = []
        for k, t in enumerate(d.teams):
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
            "version": WEB_VERSION, "file": os.path.basename(path), "info": info,
            "map_w": Wm, "map_h": H, "full_w": w.full_w, "full_h": w.full_h, "Y0": w.Y0,
            "reveal": bool(hdr.get("reveal")), "fog_dim": FOG_DIM, "frames": n, "chunk": CHUNK,
            "chunks": len(chunks), "terrain": terr, "index": idx_info, "players": players, "teams": teams,
            "rec_team": rec_team, "ages": [[r, i, a] for r, i, a in d.age_events()],
            "keys": len(keys.spans), "pieces": len(keys.pieces), "sections": sections, "hud": hud_meta,
            "civs": {str(k): v for k, v in hud.civs.items()},
        }
        js = json.dumps(meta, ensure_ascii=False, allow_nan=False).encode("utf-8")
        tmp = out_path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(MAGIC + struct.pack("<I", len(js)) + js)
            for b in blobs:
                f.write(b)
        os.replace(tmp, out_path)
        stats = {"seconds": round(time.time() - t0, 1), "terrain_s": round(t_terrain, 1),
                 "frames_s": round(t_frames, 1), "size": os.path.getsize(out_path), "src_size": d.size,
                 "frames": n, "keys": len(keys.spans), "pieces": len(keys.pieces)}
        log(f"xuất web {os.path.basename(path)}: {stats}")
        return stats
    finally:
        d.close()


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
