"""Dữ liệu thô của trận (.aoerec): ghi trạng thái game theo từng mẫu, dựng video sau.

File = chuỗi bản ghi [type u8][len u32][zlib(pickle(payload))]. Có thể đọc dở (tắt đột ngột).
  'H' header : bản đồ tĩnh, người chơi, cấu hình
  'D' defs   : bảng định nghĩa unit mới xuất hiện (addr -> trường)
  'S' statics: danh sách vật thể tĩnh (thay thế toàn bộ) khi thay đổi
  'F' frame  : time_ms, taken_at, vis_raw (XOR với mẫu trước, nén), unit thay đổi/xoá
             (từ 2026-10-09 thêm 'pstat' {index: (trạng thái thắng/thua, đã đầu hàng)} khi đổi, 'go' = cờ hết ván,
              'prs' {index: {id công nghệ: giây đã nghiên cứu}} khi đổi; unit có thêm rtype/ramount;
              từ 2026-10-10 'prod' {uid công trình: ((dat id, số lượng)...), dat id đang sinh, giây, tỉ lệ) | None};
              từ 2026-10-13 'pav' {index: id công nghệ có thể nghiên cứu}, 'ptr' {index: ((dat id, nhà sinh, nút)...)}
              = bảng lệnh của công trình như người chơi thấy, chỉ khi đổi)
  'U' stats  : {index def: chỉ số} khi chỉ số đổi (công, giáp, tầm, tốc độ... đã nâng cấp), từ 2026-10-09
  'E' end    : tổng kết khi đóng file (giờ cuối, số mẫu, trạng thái cuối từng người chơi, lý do dừng)
Sau 'E' là đuôi 16 byte: END_MAGIC + offset u64 của bản ghi 'E' -> đọc tổng kết không phải quét cả file.
Header từ 2026-10-09 có thêm 'match' (thiết lập ván), 'diplomacy' và 'resigned' theo người chơi.
Bộ đọc cũ gặp đuôi coi như bản ghi cụt và dừng đúng chỗ; gặp 'E' thì bỏ qua (không phải 'F').

Định dạng 3 (2026-10-12, file nhỏ hơn ~5 lần, không bỏ dữ liệu nào):
  'B' block  : lzma(preset 1, pickle([(tag, payload), ...])) gom ~50 mẫu (2 s) cùng các bản ghi D/S/Q/U xen giữa,
               nén chung nên tận dụng việc các mẫu liền nhau gần giống nhau (nhỏ hơn ~3,9 lần, nén nhanh hơn zlib từng
               mẫu). Chỉ 'H' và 'E' còn là bản ghi zlib riêng ở ngoài.
  'Q' statics delta: {"version", "units": vật thể tĩnh mới/đổi, "removed": uid đã mất}; 'S' toàn bộ chỉ ghi lần đầu và
               mỗi 60 s (điểm bắt đầu khi tua). Trước đây mỗi lần một cây bớt gỗ là ghi lại cả ~4 400 vật thể.
  'E' thêm "pstat_log" [(t, index, trạng thái, đầu hàng)] để danh sách trận không phải đọc cả file.
Dùng iter_records() để đọc tuần tự (tự mở khối 'B'); file định dạng 1-2 vẫn đọc bình thường.
"""
import lzma
import os
import pickle
import struct
import time
import zlib

import numpy as np

from .game import PlayerInfo, Snapshot, UnitDefInfo, UnitInfo
from . import safeload

MAGIC = b"AOEREC01"
END_MAGIC = b"AOEEND01"
FORMAT_VERSION = 3               # 1: bản đầu; 2: thêm match/pstat/E (2026-10-09); 3: khối 'B' + 'Q' (2026-10-12)
BLOCK_FRAMES = 50                # số mẫu mỗi khối nén chung (~2 s ở 25 mẫu/giây; tắt đột ngột mất tối đa chừng này)
LZMA_PRESET = 1                  # đo trên trận thật: preset 1 nhỏ ~ preset 6 (3,9x so với 4,1x) mà nhanh hơn 13 lần
STATIC_FULL_EVERY = 60.0         # giây: ghi lại toàn bộ vật thể tĩnh (điểm tựa khi tua), giữa chừng chỉ ghi phần đổi


def file_version(hdr):
    """Định dạng của file theo header (lấy số lớn hơn giữa "format" và "container"; file rất cũ = 1)."""
    hdr = hdr or {}
    return int(max(hdr.get("container") or 0, hdr.get("format") or 1))


NEWER_FORMAT_MSG = ("File này được ghi bằng bản AoE-MapCap mới hơn (định dạng {v}), bản đang dùng chỉ đọc được tới "
                    "định dạng {mine}. Hãy cập nhật AoE-MapCap: "
                    "https://github.com/trandinhnamuet/AoEMapCap/releases")


def decode_block(data):
    """Danh sách (tag, payload) bên trong một khối 'B'."""
    return safeload.lzma_loads(data)          # chỉ kiểu cho phép (file có thể do người khác gửi)


def iter_records(path):
    """Đọc tuần tự mọi bản ghi (tag, payload) của file; khối 'B' được mở ra theo đúng thứ tự. Dừng êm ở bản ghi cụt."""
    with open(path, "rb", buffering=1 << 16) as f:
        if f.read(len(MAGIC)) != MAGIC:
            raise ValueError("không phải file .aoerec")
        while True:
            head = f.read(5)
            if len(head) < 5:
                return
            tag = head[:1]
            n = struct.unpack("<I", head[1:])[0]
            data = f.read(n)
            if len(data) < n:
                return                          # file bị cắt (tắt đột ngột): dừng ở bản ghi cuối còn nguyên
            try:
                if tag == b"B":
                    for t, p in decode_block(data):
                        yield t, p
                else:
                    yield tag, safeload.zlib_loads(data)
            except Exception:  # noqa: BLE001
                return
UNIT_DT = np.dtype([("uid", "<i4"), ("def", "<i4"), ("owner", "<i2"), ("angle", "u1"), ("status", "u1"),
                    ("flags", "u1"), ("kind", "u1"), ("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("hp", "<f4"),
                    ("gid", "<i2"), ("frame", "<i2"), ("gid2", "<i2"), ("frame2", "<i2"),
                    ("rtype", "<i2"), ("ramount", "<f4")])     # rtype/ramount từ 2026-10-09 (file cũ: -1 / 0)


AGE_TECHS = {101: 2, 102: 3, 103: 4}               # Tool / Bronze / Iron Age -> đời 2 / 3 / 4
AGE_RESEARCH_MS = {101: 120_000, 102: 140_000, 103: 160_000}   # thời gian nghiên cứu (đo trên trận thật 18/10)


class AgeTracker:
    """Giờ game lúc kích (bắt đầu nghiên cứu) và lúc xong từng đời của mỗi người chơi.
    Kích = lần đầu thấy công nghệ lên đời trong danh sách đang nghiên cứu, trừ số giây đã chạy (XArena gọi là
    "kích đời 3"); không thấy lúc đang nghiên cứu (file cũ) thì suy từ lúc xong trừ thời gian nghiên cứu."""

    def __init__(self):
        self.click = {}              # (index, tech) -> ms
        self.done = {}

    def researching(self, t, idx, cur):
        for tid, el in (cur or {}).items():
            if tid in AGE_TECHS and (idx, tid) not in self.click:
                self.click[(idx, tid)] = max(0, int(t - float(el) * 1000))

    def finished(self, t, idx, techs):
        for tid in AGE_TECHS:
            if techs and tid in techs and (idx, tid) not in self.done:
                self.done[(idx, tid)] = int(t)

    def result(self):
        """{"index": {"2": {"click": ms, "done": ms hoặc None}, ...}} (khoá chuỗi: lưu JSON được)."""
        out = {}
        for (idx, tid) in set(self.click) | set(self.done):
            done = self.done.get((idx, tid))
            click = self.click.get((idx, tid))
            if click is None and done is not None:
                click = max(0, done - AGE_RESEARCH_MS[tid])
            out.setdefault(str(idx), {})[str(AGE_TECHS[tid])] = {"click": click, "done": done}
        return out


def scan_ages(path):
    """Quét cả file (file ghi trước khi 'E' có "ages"): ~5 s cho trận 40 phút."""
    tr = AgeTracker()
    for tag, pl in iter_records(path):
        if tag != b"F":
            continue
        t = pl.get("t", 0)
        for idx, cur in (pl.get("prs") or {}).items():
            tr.researching(t, int(idx), cur)
        for idx, (_attrs, techs) in (pl.get("pstate") or {}).items():
            if techs is not None:
                tr.finished(t, int(idx), techs)
    return tr.result()


def _pack(tag, payload):
    data = zlib.compress(pickle.dumps(payload, protocol=4), 6)
    return tag + struct.pack("<I", len(data)) + data


class RawWriter:
    def __init__(self, path):
        self.path = path
        self.f = open(path, "wb")
        self.f.write(MAGIC)
        self.def_index = {}          # def addr -> index
        self.prev_vis = None
        self.prev_units = None       # structured array mẫu trước
        self.prev_pstate = {}        # index -> (attrs, techs) mẫu trước
        self.frames = 0
        self.static_version = None
        self.bytes = len(MAGIC)
        self.prev_pstat = {}         # index -> (trạng thái, đã đầu hàng)
        self.prev_prs = {}           # index -> {id công nghệ đang nghiên cứu: giây}
        self.prev_prod = {}          # uid công trình -> (hàng đợi, đang sinh, giây, tỉ lệ)
        self.prev_pav = {}           # index -> công nghệ có thể nghiên cứu (đã ghi)
        self.prev_ptr = {}           # index -> unit đã mở (dat id, nhà sinh, nút) (đã ghi)
        self.prev_go = 0
        self.def_stats = {}          # địa chỉ def -> chỉ số mới nhất đọc được
        self.written_stats = {}      # index def -> chỉ số đã ghi
        self.last_t = 0
        self.last_at = 0.0
        self.block = []              # bản ghi chờ nén chung thành khối 'B'
        self.block_frames = 0
        self.prev_statics = None     # mảng vật thể tĩnh đã ghi (để chỉ ghi phần đổi)
        self.static_full_at = 0.0
        self.pstat_log = []          # [(t, index, trạng thái, đầu hàng)] — ghi vào 'E'
        self.ages = AgeTracker()     # kích / lên đời -> 'E'["ages"] (bảng trận mở rộng)
        self.raw_bytes = 0           # cỡ pickle trước khi nén (thống kê)

    def _def_id(self, d: UnitDefInfo, new_defs):
        i = self.def_index.get(d.addr)
        if i is None:
            i = len(self.def_index)
            self.def_index[d.addr] = i
            new_defs.append((i, d.addr, d.utype, d.name, d.dat_id, d.cls, d.fog_visible, d.mm_mode, d.mm_color, d.hp_max))
        return i

    def _units_array(self, units, new_defs):
        n = len(units)
        arr = np.empty(n, UNIT_DT)
        if n == 0:
            return arr
        di = self.def_index
        defs = []
        for u in units:
            i = di.get(u.udef.addr)
            if i is None:
                i = self._def_id(u.udef, new_defs)
            defs.append(i)
        arr["uid"] = [u.uid for u in units]
        arr["def"] = defs
        arr["owner"] = [u.owner_index for u in units]
        arr["angle"] = [u.angle for u in units]
        arr["status"] = [u.status for u in units]
        arr["flags"] = [u.flags for u in units]
        arr["kind"] = [u.kind for u in units]
        arr["x"] = [u.x for u in units]
        arr["y"] = [u.y for u in units]
        arr["z"] = [u.z for u in units]
        arr["hp"] = [u.hp for u in units]
        arr["gid"] = [u.gid for u in units]
        arr["frame"] = [u.frame for u in units]
        arr["gid2"] = [u.gid2 for u in units]
        arr["frame2"] = [u.frame2 for u in units]
        arr["rtype"] = [getattr(u, "res_type", -1) for u in units]
        arr["ramount"] = [round(float(getattr(u, "res_amount", 0.0) or 0.0), 1) for u in units]
        return arr

    def _write(self, tag, payload):
        if tag in (b"H", b"E"):                       # header / tổng kết: bản ghi zlib riêng ở ngoài khối
            self._flush_block()
            b = _pack(tag, payload)
            self.f.write(b)
            self.bytes += len(b)
            return
        self.block.append((tag, payload))
        if tag == b"F":
            self.block_frames += 1
            if self.block_frames >= BLOCK_FRAMES:
                self._flush_block()

    def _flush_block(self):
        if not self.block:
            return
        raw = pickle.dumps(self.block, protocol=4)
        data = lzma.compress(raw, preset=LZMA_PRESET)
        b = b"B" + struct.pack("<I", len(data)) + data
        self.f.write(b)
        self.bytes += len(b)
        self.raw_bytes += len(raw)
        self.block = []
        self.block_frames = 0

    def start(self, snap: Snapshot, meta=None):
        hdr = {
            "map_w": snap.map_w, "map_h": snap.map_h, "reveal": snap.reveal, "cur_player_index": snap.cur_player_index,
            "players": [(p.index, p.addr, p.pid, p.name, p.mm_color, p.explored_mask, p.visible_mask, p.ptype) for p in snap.players],
            "civs": [p.civ for p in snap.players],
            "terrain": snap.terrain, "elevation": snap.elevation, "shape": snap.shape,
            "tile_dx": snap.tile_dx, "tile_dy": snap.tile_dy, "tile_border": snap.tile_border,
            "terrain_colors": snap.terrain_colors, "speed": snap.speed, "meta": meta or {}, "created": time.time(),
            "format": FORMAT_VERSION, "container": FORMAT_VERSION, "match": getattr(snap, "match", None),
            "diplomacy": [tuple(getattr(p, "diplomacy", ()) or ()) for p in snap.players],
            "resigned": [int(getattr(p, "resigned", 0) or 0) for p in snap.players],
        }
        self._write(b"H", hdr)
        self.add_frame(snap)

    def _maybe_statics(self, snap):
        ver = getattr(snap, "static_version", None)
        units = getattr(snap, "static_units", None)
        if units is None or ver == self.static_version:
            return
        new_defs = []
        arr = self._units_array(units, new_defs)
        if new_defs:
            self._write(b"D", new_defs)
        now = getattr(snap, "taken_at", time.time())
        prev = self.prev_statics
        if prev is None or now - self.static_full_at >= STATIC_FULL_EVERY:
            self._write(b"S", {"version": ver, "units": arr})
            self.static_full_at = now
        else:
            changed, removed = _diff_units(prev, arr)
            self._write(b"Q", {"version": ver, "units": changed, "removed": removed})
        self.prev_statics = arr
        self.static_version = ver

    def add_frame(self, snap: Snapshot):
        self._maybe_statics(snap)
        new_defs = []
        arr = self._units_array(snap.units, new_defs)
        if new_defs:
            self._write(b"D", new_defs)
        ds = getattr(snap, "def_stats", None)
        if ds:
            self.def_stats.update(ds)
        if ds or new_defs:
            changed_stats = {}
            for addr, idx in self.def_index.items():
                st = self.def_stats.get(addr)
                if st is not None and self.written_stats.get(idx) != st:
                    changed_stats[idx] = st
                    self.written_stats[idx] = st
            if changed_stats:
                self._write(b"U", changed_stats)
        vis = snap.vis_raw
        if self.prev_vis is None:
            vis_delta = zlib.compress(vis.tobytes(), 6)
            full_vis = True
        else:
            vis_delta = zlib.compress(np.bitwise_xor(vis, self.prev_vis).tobytes(), 6)
            full_vis = False
        self.prev_vis = vis.copy()
        # unit: chỉ ghi những bản ghi khác mẫu trước + danh sách uid đã mất
        if self.prev_units is None or len(self.prev_units) == 0:
            changed = arr
            removed = np.zeros(0, "<i4")
            full_units = True
        else:
            prev = self.prev_units
            # so khớp theo uid bằng numpy: sắp xếp prev, tìm vị trí của từng uid hiện tại
            order = np.argsort(prev["uid"], kind="stable")
            puid = prev["uid"][order]
            pos = np.searchsorted(puid, arr["uid"])
            pos_c = np.minimum(pos, len(puid) - 1)
            found = puid[pos_c] == arr["uid"]
            same = np.zeros(len(arr), bool)
            if found.any():
                prev_rows = prev[order[pos_c[found]]]
                cur_rows = arr[found]
                eq = np.ones(found.sum(), bool)
                for name in UNIT_DT.names:
                    eq &= prev_rows[name] == cur_rows[name]
                same[np.nonzero(found)[0]] = eq
            changed = arr[~same]
            removed = np.setdiff1d(prev["uid"], arr["uid"], assume_unique=False).astype("<i4")
            full_units = False
        self.prev_units = arr
        # trạng thái người chơi (tài nguyên, công nghệ): chỉ ghi người chơi có thay đổi
        pstate = {}
        for p in snap.players:
            cur = (tuple(p.attrs), None if p.techs is None else tuple(sorted(p.techs)))
            if self.prev_pstate.get(p.index) != cur:
                pstate[p.index] = cur
                self.prev_pstate[p.index] = cur
                if p.techs is not None:
                    self.ages.finished(snap.time_ms, p.index, p.techs)
        rec = {"t": snap.time_ms, "at": snap.taken_at, "full_vis": full_vis, "vis": vis_delta,
               "full_units": full_units, "units": changed, "removed": removed}
        if pstate:
            rec["pstate"] = pstate
        prs = {}
        for p in snap.players:
            cur = dict(getattr(p, "researching", None) or {})
            if self.prev_prs.get(p.index, {}) != cur:
                prs[p.index] = cur
                self.prev_prs[p.index] = cur
                self.ages.researching(snap.time_ms, p.index, cur)
        if prs:
            rec["prs"] = prs                           # công nghệ đang nghiên cứu -> giây đã chạy
        # bảng lệnh công trình (2026-10-13): công nghệ có thể nghiên cứu + unit đã mở, chỉ khi đổi
        pav, ptr = {}, {}
        for p in snap.players:
            av = getattr(p, "available", None)
            if av is not None and self.prev_pav.get(p.index) != av:
                pav[p.index] = tuple(sorted(av))
                self.prev_pav[p.index] = av
            tr = getattr(p, "trainable", None)
            if tr is not None and self.prev_ptr.get(p.index) != tr:
                ptr[p.index] = tuple(sorted(tr))
                self.prev_ptr[p.index] = tr
        if pav:
            rec["pav"] = pav
        if ptr:
            rec["ptr"] = ptr
        prod = getattr(snap, "production", None)
        if prod is not None:                           # hàng đợi sinh unit: chỉ ghi công trình đổi (None = hết hàng)
            ch = {uid: v for uid, v in prod.items() if self.prev_prod.get(uid) != v}
            ch.update({uid: None for uid in self.prev_prod if uid not in prod})
            if ch:
                rec["prod"] = ch
            self.prev_prod = dict(prod)
        pstat = {}
        for p in snap.players:
            cur = (int(p.ptype), int(getattr(p, "resigned", 0) or 0))
            if self.prev_pstat.get(p.index, (0, 0)) != cur:
                pstat[p.index] = cur
                self.prev_pstat[p.index] = cur
                self.pstat_log.append((snap.time_ms, p.index) + cur)
        if pstat:
            rec["pstat"] = pstat
        go = int(getattr(snap, "game_over", 0) or 0)
        if go != self.prev_go:
            rec["go"] = go
            self.prev_go = go
        self.last_t, self.last_at = snap.time_ms, snap.taken_at
        self._write(b"F", rec)
        self.frames += 1

    def close(self, reason=None):
        """Đóng file; ghi bản ghi tổng kết 'E' + đuôi để danh sách trận đọc nhanh."""
        try:
            if self.frames:
                pos = self.bytes
                self._flush_block()
                pos = self.bytes
                self._write(b"E", {"t": self.last_t, "at": self.last_at, "frames": self.frames,
                                   "status": dict(self.prev_pstat), "game_over": self.prev_go, "reason": reason,
                                   "closed": time.time(), "pstat_log": list(self.pstat_log),
                                   "ages": self.ages.result()})
                self.f.write(END_MAGIC + struct.pack("<Q", pos))
                self.bytes += 16
        except Exception:  # noqa: BLE001
            pass
        try:
            self.f.close()
        except Exception:  # noqa: BLE001
            pass
        return self.frames


def _diff_units(prev, arr):
    """(hàng mới/đổi của arr so với prev theo uid, uid có trong prev mà không còn trong arr)."""
    if prev is None or len(prev) == 0:
        return arr, np.zeros(0, "<i4")
    order = np.argsort(prev["uid"], kind="stable")
    puid = prev["uid"][order]
    pos = np.clip(np.searchsorted(puid, arr["uid"]), 0, len(puid) - 1)
    found = puid[pos] == arr["uid"]
    same = np.zeros(len(arr), bool)
    if found.any():
        prow = prev[order[pos[found]]]
        crow = arr[found]
        eq = np.ones(found.sum(), bool)
        for name in arr.dtype.names:
            eq &= prow[name] == crow[name]
        same[np.nonzero(found)[0]] = eq
    removed = np.setdiff1d(prev["uid"], arr["uid"]).astype("<i4")
    return arr[~same], removed


def read_header(path):
    """Bản ghi 'H' đầu file (None nếu hỏng)."""
    with open(path, "rb") as f:
        if f.read(len(MAGIC)) != MAGIC:
            return None
        head = f.read(5)
        if len(head) < 5 or head[:1] != b"H":
            return None
        n = struct.unpack("<I", head[1:])[0]
        data = f.read(n)
        if len(data) < n:
            return None
        return safeload.zlib_loads(data)


def read_end(path):
    """Bản ghi tổng kết 'E' qua đuôi file (None nếu file cũ / ghi dở)."""
    try:
        size = os.path.getsize(path)
        if size < len(MAGIC) + 16:
            return None
        with open(path, "rb") as f:
            f.seek(size - 16)
            tail = f.read(16)
            if tail[:8] != END_MAGIC:
                return None
            pos = struct.unpack("<Q", tail[8:])[0]
            f.seek(pos)
            head = f.read(5)
            if head[:1] != b"E":
                return None
            n = struct.unpack("<I", head[1:])[0]
            return safeload.zlib_loads(f.read(n))
    except Exception:  # noqa: BLE001
        return None


class RawReader:
    """Đọc tuần tự .aoerec; frames() sinh Snapshot đầy đủ cho từng mẫu."""

    def __init__(self, path):
        self.path = path
        self.header = None
        self.defs = {}               # index -> UnitDefInfo
        self.statics = []
        self.static_version = 0

    def records(self):
        return iter_records(self.path)

    def _apply_defs(self, lst):
        for rec in lst:
            (i, addr, utype, name, dat_id, cls, fogvis, mm_mode, mm_color) = rec[:9]
            hp_max = rec[9] if len(rec) > 9 else 0
            self.defs[i] = UnitDefInfo(addr, utype, name, dat_id, cls, bool(fogvis), mm_mode, mm_color, hp_max)

    def _units_from_array(self, arr):
        out = []
        defs = self.defs
        names = arr.dtype.names or ()
        has_kind = "kind" in names                        # file cũ dùng trường "pad"
        has_gfx = "gid" in names                          # từ 2026-10-07 chiều: sprite/khung của game
        for rec in arr:
            d = defs.get(int(rec["def"]))
            if d is None:
                continue
            u = UnitInfo(uid=int(rec["uid"]), x=float(rec["x"]), y=float(rec["y"]), z=float(rec["z"]),
                         owner_index=int(rec["owner"]), udef=d, flags=int(rec["flags"]), angle=int(rec["angle"]),
                         hp=float(rec["hp"]), status=int(rec["status"]), kind=int(rec["kind"]) if has_kind else 0)
            if has_gfx:
                u.gid, u.frame, u.gid2, u.frame2 = int(rec["gid"]), int(rec["frame"]), int(rec["gid2"]), int(rec["frame2"])
            if "ramount" in names:
                u.res_type, u.res_amount = int(rec["rtype"]), float(rec["ramount"])
            out.append(u)
        return out

    def count_frames(self):
        n = 0
        for tag, _ in self.records():
            if tag == b"F":
                n += 1
        return n

    def frames(self):
        hdr = None
        vis = None
        units = {}                   # uid -> structured record (np.void)
        players = []
        tech_times = {}              # index -> {id công nghệ: time_ms}; tích luỹ từ đầu file nên đúng ở mọi đoạn dựng
        for tag, payload in self.records():
            if tag == b"H":
                hdr = payload
                self.header = hdr
                players = [PlayerInfo(*p) for p in hdr["players"]]
                for p, civ in zip(players, hdr.get("civs", [])):
                    p.civ = civ
            elif tag == b"D":
                self._apply_defs(payload)
            elif tag == b"S":
                self.static_version = payload["version"]
                self.statics = self._units_from_array(payload["units"])
            elif tag == b"Q":                            # vật thể tĩnh: chỉ phần đổi so với bản trước
                self.static_version = payload["version"]
                cur = {u.uid: u for u in self.statics}
                for uid in payload["removed"].tolist():
                    cur.pop(int(uid), None)
                for u in self._units_from_array(payload["units"]):
                    cur[u.uid] = u
                self.statics = list(cur.values())
            elif tag == b"F" and hdr is not None:
                w, h = hdr["map_w"], hdr["map_h"]
                raw = np.frombuffer(safeload.zlib_raw(payload["vis"], h * w * 4), np.uint32).reshape(h, w)
                vis = raw.copy() if payload["full_vis"] or vis is None else np.bitwise_xor(vis, raw)
                if payload["full_units"]:
                    units = {int(r["uid"]): r for r in payload["units"]}
                else:
                    for u in payload["removed"].tolist():
                        units.pop(int(u), None)
                    for r in payload["units"]:
                        units[int(r["uid"])] = r
                for idx, (attrs, techs) in payload.get("pstate", {}).items():
                    if 0 <= idx < len(players):
                        players[idx].attrs = tuple(attrs)
                        players[idx].techs = None if techs is None else frozenset(techs)
                        if techs is not None:
                            tt = tech_times.setdefault(idx, {})
                            for tid in techs:
                                if tid not in tt:
                                    tt[tid] = payload["t"]          # giờ game lúc lần đầu thấy xong
                            players[idx].tech_times = dict(tt)
                arr = np.array(list(units.values()), UNIT_DT) if units else np.zeros(0, UNIT_DT)
                snap = Snapshot(taken_at=payload["at"], time_ms=payload["t"], speed=hdr.get("speed", 1.0),
                                map_w=w, map_h=h, terrain=hdr["terrain"], elevation=hdr["elevation"], shape=hdr["shape"],
                                vis_raw=vis, terrain_colors=hdr["terrain_colors"], reveal=hdr["reveal"],
                                cur_player_index=hdr["cur_player_index"], players=players,
                                units=self._units_from_array(arr), addrs={}, tile_dx=hdr["tile_dx"], tile_dy=hdr["tile_dy"],
                                tile_border=hdr["tile_border"])
                snap.static_units = self.statics
                snap.static_version = self.static_version
                for p in players:
                    p.unit_count = 0
                for u in snap.units:
                    if 0 <= u.owner_index < len(players):
                        players[u.owner_index].unit_count += 1
                yield snap


def compact_file(path, progress=None):
    """Nén lại một file cũ tại chỗ (định dạng < 3): ghi bản mới ra file tạm, kiểm tra đủ số mẫu và tổng kết rồi mới
    thay file gốc. Trả về (cỡ cũ, cỡ mới) hoặc None nếu đã là định dạng mới / không chắc an toàn."""
    hdr = read_header(path)
    if hdr is None or int(hdr.get("container", 0) or 0) >= FORMAT_VERSION:
        return None
    tmp = path + ".nen.tmp"
    try:
        old, new = recompress(path, tmp, progress)
        n_old = sum(1 for t, _ in iter_records(path) if t == b"F")
        n_new = sum(1 for t, _ in iter_records(tmp) if t == b"F")
        if n_old != n_new or (read_end(path) is not None) != (read_end(tmp) is not None) or new >= old:
            os.remove(tmp)
            return None
        st = os.stat(path)
        os.replace(tmp, path)
        os.utime(path, (st.st_atime, st.st_mtime))      # giữ giờ sửa (bảng trận sắp theo ngày)
        return old, new
    except Exception:  # noqa: BLE001
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def recompress(src, dst, progress=None):
    """Chuyển file .aoerec bất kỳ sang định dạng 3 (khối 'B' + 'Q'), không bỏ dữ liệu nào.
    Trả về (cỡ cũ, cỡ mới). File ghi dở (không có 'E') giữ nguyên là ghi dở."""
    size = os.path.getsize(src)
    w = RawWriter(dst)
    end = None
    last_at = 0.0
    prev_ps = {}
    n = 0
    try:
        for tag, p in iter_records(src):
            if tag == b"H":
                p = dict(p)
                p["format"] = max(int(p.get("format", 1)), FORMAT_VERSION) if "format" in p else p.get("format")
                if p["format"] is None:
                    del p["format"]                  # file rất cũ: không có thông tin thắng/thua, giữ nguyên ý nghĩa
                p["container"] = FORMAT_VERSION      # đã ở dạng khối nén (kể cả file rất cũ không có "format")
                w._write(b"H", p)
            elif tag == b"S":
                arr = p["units"]
                if w.prev_statics is None or last_at - w.static_full_at >= STATIC_FULL_EVERY:
                    w._write(b"S", p)
                    w.static_full_at = last_at
                else:
                    changed, removed = _diff_units(w.prev_statics, arr)
                    w._write(b"Q", {"version": p.get("version"), "units": changed, "removed": removed})
                w.prev_statics = arr
            elif tag == b"Q":
                w._write(b"Q", p)
            elif tag == b"F":
                last_at = p.get("at", last_at)
                for idx, v in (p.get("pstat") or {}).items():
                    if prev_ps.get(idx) != tuple(v):
                        prev_ps[idx] = tuple(v)
                        w.pstat_log.append((p.get("t", 0), idx) + tuple(v))
                for idx, cur in (p.get("prs") or {}).items():
                    w.ages.researching(p.get("t", 0), int(idx), cur)
                for idx, (_attrs, techs) in (p.get("pstate") or {}).items():
                    if techs is not None:
                        w.ages.finished(p.get("t", 0), int(idx), techs)
                w._write(b"F", p)
                w.frames += 1
                n += 1
                if progress and (n & 255) == 0:
                    progress(n)
            elif tag == b"E":
                end = dict(p)
            elif tag in (b"D", b"U"):
                w._write(tag, p)
        w._flush_block()
        if end is not None:
            end.setdefault("pstat_log", list(w.pstat_log))
            end.setdefault("ages", w.ages.result())
            pos = w.bytes
            w._write(b"E", end)
            w.f.write(END_MAGIC + struct.pack("<Q", pos))
            w.bytes += 16
    finally:
        w.f.close()
    return size, os.path.getsize(dst)
