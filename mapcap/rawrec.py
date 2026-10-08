"""Dữ liệu thô của trận (.aoerec): ghi trạng thái game theo từng mẫu, dựng video sau.

File = chuỗi bản ghi [type u8][len u32][zlib(pickle(payload))]. Có thể đọc dở (tắt đột ngột).
  'H' header : bản đồ tĩnh, người chơi, cấu hình
  'D' defs   : bảng định nghĩa unit mới xuất hiện (addr -> trường)
  'S' statics: danh sách vật thể tĩnh (thay thế toàn bộ) khi thay đổi
  'F' frame  : time_ms, taken_at, vis_raw (XOR với mẫu trước, nén), unit thay đổi/xoá
"""
import pickle
import struct
import time
import zlib

import numpy as np

from .game import PlayerInfo, Snapshot, UnitDefInfo, UnitInfo

MAGIC = b"AOEREC01"
UNIT_DT = np.dtype([("uid", "<i4"), ("def", "<i4"), ("owner", "<i2"), ("angle", "u1"), ("status", "u1"),
                    ("flags", "u1"), ("kind", "u1"), ("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("hp", "<f4"),
                    ("gid", "<i2"), ("frame", "<i2"), ("gid2", "<i2"), ("frame2", "<i2")])


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
        return arr

    def _write(self, tag, payload):
        b = _pack(tag, payload)
        self.f.write(b)
        self.bytes += len(b)

    def start(self, snap: Snapshot, meta=None):
        hdr = {
            "map_w": snap.map_w, "map_h": snap.map_h, "reveal": snap.reveal, "cur_player_index": snap.cur_player_index,
            "players": [(p.index, p.addr, p.pid, p.name, p.mm_color, p.explored_mask, p.visible_mask, p.ptype) for p in snap.players],
            "civs": [p.civ for p in snap.players],
            "terrain": snap.terrain, "elevation": snap.elevation, "shape": snap.shape,
            "tile_dx": snap.tile_dx, "tile_dy": snap.tile_dy, "tile_border": snap.tile_border,
            "terrain_colors": snap.terrain_colors, "speed": snap.speed, "meta": meta or {}, "created": time.time(),
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
        self._write(b"S", {"version": ver, "units": arr})
        self.static_version = ver

    def add_frame(self, snap: Snapshot):
        self._maybe_statics(snap)
        new_defs = []
        arr = self._units_array(snap.units, new_defs)
        if new_defs:
            self._write(b"D", new_defs)
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
        rec = {"t": snap.time_ms, "at": snap.taken_at, "full_vis": full_vis, "vis": vis_delta,
               "full_units": full_units, "units": changed, "removed": removed}
        if pstate:
            rec["pstate"] = pstate
        self._write(b"F", rec)
        self.frames += 1

    def close(self):
        try:
            self.f.close()
        except Exception:  # noqa: BLE001
            pass
        return self.frames


class RawReader:
    """Đọc tuần tự .aoerec; frames() sinh Snapshot đầy đủ cho từng mẫu."""

    def __init__(self, path):
        self.path = path
        self.header = None
        self.defs = {}               # index -> UnitDefInfo
        self.statics = []
        self.static_version = 0

    def records(self):
        with open(self.path, "rb") as f:
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
                    return                      # file bị cắt (tắt đột ngột): dừng ở bản ghi cuối còn nguyên
                try:
                    yield tag, pickle.loads(zlib.decompress(data))
                except Exception:  # noqa: BLE001
                    return

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
            elif tag == b"F" and hdr is not None:
                w, h = hdr["map_w"], hdr["map_h"]
                raw = np.frombuffer(zlib.decompress(payload["vis"]), np.uint32).reshape(h, w)
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
