"""Dữ liệu replay: mở .aoerec, lập chỉ mục bản ghi, điểm mốc để tua, trạng thái game tại từng mẫu.

Không dính tới đồ hoạ. Định dạng file xem mapcap/rawrec.py: [tag u8][len u32][zlib(pickle)], các mẫu 'F' chỉ ghi
phần thay đổi so với mẫu trước nên muốn tới mẫu k phải áp dần từ một điểm mốc (toàn trạng thái) <= k.
"""
import bisect
import mmap
import os
import pickle
import struct
import threading
import time
import zlib

import numpy as np

from mapcap.game import PlayerInfo, UnitDefInfo
from mapcap.rawrec import FORMAT_VERSION, MAGIC, NEWER_FORMAT_MSG, UNIT_DT, decode_block, file_version
from mapcap import safeload

KEY_EVERY = 125          # điểm mốc mỗi 125 mẫu (~5 s ở 25 mẫu/giây): tua tới bất kì đâu áp tối đa 124 mẫu
SEEN_EVERY = 5                    # mẫu: đánh dấu công trình đội đã thấy (5 mẫu = 0,2 s)
PAUSE_GAP = 1.0          # đồng hồ game đứng yên quá 1 s (game tạm dừng) thì không tính vào thời gian phát
MAX_STEP = 0.5           # một bước giữa hai mẫu tính tối đa 0,5 s (bộ ghi có lúc khựng)


def normalize_units(arr):
    """Mảng unit của file cũ (trường 'pad', thiếu gid/frame) -> đúng UNIT_DT."""
    if arr is None:
        return np.zeros(0, UNIT_DT)
    if arr.dtype == UNIT_DT:
        return arr
    out = np.zeros(len(arr), UNIT_DT)
    names = arr.dtype.names or ()
    for n in UNIT_DT.names:
        if n in names:
            out[n] = arr[n]
        elif n in ("gid", "frame", "gid2", "frame2", "rtype"):
            out[n] = -1
    return out


def _apply_static_delta(arr, changed, removed):
    """Áp bản ghi 'Q': bỏ uid đã mất và bản cũ của uid đổi, thêm bản mới."""
    drop = changed["uid"]
    if removed is not None and len(removed):
        drop = np.concatenate([drop, np.asarray(removed, drop.dtype)])
    keep = ~np.isin(arr["uid"], drop) if len(drop) else np.ones(len(arr), bool)
    return np.concatenate([arr[keep], changed]) if len(changed) else arr[keep]


class KeyState:
    __slots__ = ("frame", "t", "at", "units", "vis", "pstate", "tech_times", "pstat", "go", "prs", "prod", "pav", "ptr")

    def __init__(self, frame, t, at, units, vis, pstate, tech_times, pstat, go, prs=None, prod=None, pav=None, ptr=None):
        self.prs = prs or {}
        self.prod = prod or {}
        self.pav = pav or {}
        self.ptr = ptr or {}
        self.frame, self.t, self.at = frame, t, at
        self.units, self.vis, self.pstate, self.tech_times = units, vis, pstate, tech_times
        self.pstat, self.go = pstat, go


class FrameState:
    """Trạng thái đầy đủ tại một mẫu. Unit giữ trong mảng có chỗ trống (cập nhật tại chỗ, O(số unit đổi))."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self._reset_units(np.zeros(0, UNIT_DT))
        self.vis = None
        self.pstate = {}             # index người chơi -> (attrs, techs)
        self.tech_times = {}         # index -> {id công nghệ: giờ game lần đầu thấy xong}
        self.pstat = {}              # index -> (0 đang chơi / 1 thắng / 2 thua, đã đầu hàng) — file từ 2026-10-09
        self.prod = {}               # uid công trình -> (hàng đợi, dat id đang sinh, giây, tỉ lệ) — file từ 2026-10-10
        self.go = 0                  # 1 = ván đã kết thúc
        self.prs = {}                # index -> {id công nghệ đang nghiên cứu: giây đã chạy}
        self.pav = {}                # index -> frozenset id công nghệ "có thể nghiên cứu" (trạng thái 1) — file từ 2026-10-13
        self.ptr = {}                # index -> frozenset (dat id, nhà sinh, nút) unit đã mở — file từ 2026-10-13
        self.frame = -1
        self.t = 0
        self.at = 0.0

    def _reset_units(self, units):
        n = len(units)
        cap = max(1024, 1 << int(np.ceil(np.log2(max(n, 1) * 2))))
        self.arr = np.zeros(cap, UNIT_DT)
        self.valid = np.zeros(cap, bool)
        self.arr[:n] = units
        self.valid[:n] = True
        self.pos = {int(u): i for i, u in enumerate(units["uid"].tolist())}
        self.free = list(range(cap - 1, n - 1, -1))

    def _grow(self):
        cap = len(self.arr)
        arr = np.zeros(cap * 2, UNIT_DT)
        arr[:cap] = self.arr
        valid = np.zeros(cap * 2, bool)
        valid[:cap] = self.valid
        self.arr, self.valid = arr, valid
        self.free.extend(range(cap * 2 - 1, cap - 1, -1))

    def apply(self, p, frame):
        raw = np.frombuffer(safeload.zlib_raw(p["vis"], self.h * self.w * 4), np.uint32).reshape(self.h, self.w)
        if p["full_vis"] or self.vis is None:
            self.vis = raw.copy()
        else:
            np.bitwise_xor(self.vis, raw, out=self.vis)
        ch = normalize_units(p.get("units"))
        if p.get("full_units"):
            self._reset_units(ch)
        else:
            pos, valid, free = self.pos, self.valid, self.free
            rem = p.get("removed")
            if rem is not None and len(rem):
                for uid in rem.tolist():
                    i = pos.pop(uid, None)
                    if i is not None:
                        valid[i] = False
                        free.append(i)
            if len(ch):
                idx = []
                for uid in ch["uid"].tolist():
                    i = pos.get(uid)
                    if i is None:
                        if not free:
                            self._grow()
                            valid = self.valid
                        i = self.free.pop()
                        pos[uid] = i
                        valid[i] = True
                    idx.append(i)
                self.arr[idx] = ch
        for idx, (attrs, techs) in p.get("pstate", {}).items():
            self.pstate[idx] = (tuple(attrs), None if techs is None else frozenset(techs))
            if techs is not None:
                tt = self.tech_times.setdefault(idx, {})
                for tid in techs:
                    tt.setdefault(tid, p["t"])
        if "pstat" in p:
            self.pstat.update(p["pstat"])
        if "go" in p:
            self.go = p["go"]
        if "prs" in p:
            self.prs.update(p["prs"])
        for idx, v in p.get("pav", {}).items():
            self.pav[idx] = frozenset(v)
        for idx, v in p.get("ptr", {}).items():
            self.ptr[idx] = frozenset(tuple(x) for x in v)
        for uid, v in p.get("prod", {}).items():
            if v is None:
                self.prod.pop(uid, None)
            else:
                self.prod[uid] = v
        self.frame = frame
        self.t = p["t"]
        self.at = p["at"]

    def units(self):
        """Mảng unit đang sống (bản sao gọn)."""
        return self.arr[self.valid]

    def snapshot(self):
        return KeyState(self.frame, self.t, self.at, self.units(), self.vis.copy(), dict(self.pstate),
                        {k: dict(v) for k, v in self.tech_times.items()}, dict(self.pstat), self.go,
                        {k: dict(v) for k, v in self.prs.items()}, dict(self.prod), dict(self.pav), dict(self.ptr))

    def restore(self, k: KeyState):
        self._reset_units(k.units)
        self.vis = k.vis.copy()
        self.pstate = dict(k.pstate)
        self.tech_times = {i: dict(v) for i, v in k.tech_times.items()}
        self.pstat, self.go = dict(k.pstat), k.go
        self.prs = {i: dict(v) for i, v in k.prs.items()}
        self.prod = dict(getattr(k, "prod", {}) or {})
        self.pav = dict(getattr(k, "pav", {}) or {})
        self.ptr = dict(getattr(k, "ptr", {}) or {})
        self.frame, self.t, self.at = k.frame, k.t, k.at


class ReplayData:
    """Mở file, đọc header ngay; lập chỉ mục phần còn lại trong luồng nền (start_index)."""

    def __init__(self, path):
        self.path = os.path.abspath(path)
        self._fh = open(self.path, "rb")
        self.size = os.path.getsize(self.path)
        if self.size < len(MAGIC) + 5:
            raise ValueError("file rỗng hoặc hỏng")
        self.mm = mmap.mmap(self._fh.fileno(), 0, access=mmap.ACCESS_READ)
        if self.mm[:len(MAGIC)] != MAGIC:
            raise ValueError("không phải file .aoerec")
        self.header = None
        self.defs = {}               # index -> UnitDefInfo
        self._def_ver = 0
        self.f_off = []              # (offset dữ liệu, độ dài) của từng mẫu
        self.f_t = []                # giờ game (ms)
        self.f_at = []               # giờ thật lúc đọc mẫu (s)
        self.f_r = []                # thời gian phát (s): giờ thật, bỏ các đoạn game tạm dừng
        self.s_first = []            # bản ghi vật thể tĩnh: áp dụng từ mẫu thứ ...
        self.s_rec = []              # vị trí bản ghi: (offset, độ dài) hoặc ('B', khối, thứ tự)
        self.s_kind = []             # b"S" toàn bộ / b"Q" chỉ phần đổi (định dạng 3)
        self.blocks = []             # (offset, độ dài) các khối 'B'
        self._block_cache = {}
        self._st_cache = None        # (chỉ số bản ghi tĩnh, phiên bản, mảng) dựng gần nhất
        self._idx_pos = 0
        self.keys = {}               # chỉ số mẫu -> KeyState
        self.stats = {}              # index def -> ([mẫu bắt đầu có hiệu lực], [chỉ số]) (file từ 2026-10-09)
        self.done = False
        self.error = None
        self.index_seconds = 0.0
        self.final_tech_times = {}   # index -> {id công nghệ: giờ game}, có khi lập chỉ mục xong
        self._pos = len(MAGIC)
        self._read_header()
        self.players = self._make_players()
        from .library import teams_from_header
        self.teams = teams_from_header(self.header)
        # công trình (type 80) mỗi đội đã thấy: uid -> mẫu đầu tiên thấy (dựng khi lập chỉ mục). Game không phải lúc
        # nào cũng có doppelganger cho công trình đã thấy (ruộng: không bao giờ; nhà khác: khoảng một nửa, đo trận
        # 23/10) -> trình xem vẽ công trình thật mờ trong sương mù nếu đội đã thấy nó.
        self.seen = [dict() for _ in self.teams]
        self._team_vm = []
        for t in self.teams:
            vm = 0
            for i in t:
                if 0 <= i < len(self.players):
                    vm |= int(self.players[i].visible_mask)
            self._team_vm.append(vm)

    # ---- đọc bản ghi -------------------------------------------------------------------
    def _record_at(self, pos):
        if pos + 5 > self.size:
            return None
        tag = self.mm[pos:pos + 1]
        n = struct.unpack_from("<I", self.mm, pos + 1)[0]
        if pos + 5 + n > self.size:
            return None                       # file bị cắt (tắt đột ngột): dừng ở bản ghi cuối còn nguyên
        return tag, pos + 5, n

    def _load(self, off, n):
        return safeload.zlib_loads(self.mm[off:off + n])

    def _read_header(self):
        r = self._record_at(self._pos)
        if r is None or r[0] != b"H":
            raise ValueError("file thiếu header")
        self.header = self._load(r[1], r[2])
        v = file_version(self.header)
        if v > FORMAT_VERSION:                  # file của bản mới hơn: báo cập nhật thay vì mở ra trống
            raise ValueError(NEWER_FORMAT_MSG.format(v=v, mine=FORMAT_VERSION))
        self._pos = r[1] + r[2]
        self.map_w, self.map_h = int(self.header["map_w"]), int(self.header["map_h"])

    def _apply_defs(self, lst):
        for rec in lst:
            (i, addr, utype, name, dat_id, cls, fogvis, mm_mode, mm_color) = rec[:9]
            hp_max = rec[9] if len(rec) > 9 else 0
            self.defs[i] = UnitDefInfo(addr, utype, name, dat_id, cls, bool(fogvis), mm_mode, mm_color, hp_max)
        self._def_ver += 1

    def start_index(self):
        th = threading.Thread(target=self._index_safe, name="replay-index", daemon=True)
        th.start()
        return th

    def _index_safe(self):
        try:
            self._index()
        except Exception as e:  # noqa: BLE001
            self.error = e
        finally:
            self.done = True

    def _index(self):
        """Đọc tuần tự cả file: vị trí từng mẫu (bản ghi ngoài (off, n) hoặc trong khối ('B', khối, thứ tự)),
        điểm mốc, bản ghi vật thể tĩnh ('S' toàn bộ / 'Q' phần đổi), chỉ số def."""
        t0 = time.time()
        st = FrameState(self.map_w, self.map_h)
        pos = self._pos
        acc = {"r": 0.0, "frozen": 0.0}

        def one(tag, get, loc):
            if tag == b"D":
                self._apply_defs(get())
            elif tag in (b"S", b"Q"):
                self.s_first.append(len(self.f_off))
                self.s_rec.append(loc)
                self.s_kind.append(tag)
            elif tag == b"U":
                fi_next = len(self.f_off)
                for idx, stv in get().items():
                    self.stats.setdefault(int(idx), ([], []))
                    self.stats[int(idx)][0].append(fi_next)
                    self.stats[int(idx)][1].append(stv)
            elif tag == b"F":
                p = get()
                fi = len(self.f_off)
                st.apply(p, fi)
                if fi % KEY_EVERY == 0:
                    self.keys[fi] = st.snapshot()
                if fi % SEEN_EVERY == 0:
                    self._mark_seen(st, fi)
                if fi:
                    dr = min(max(p["at"] - self.f_at[-1], 0.0), MAX_STEP)
                    if p["t"] == self.f_t[-1]:
                        acc["frozen"] += dr
                        if acc["frozen"] > PAUSE_GAP:
                            dr = 0.0
                    else:
                        acc["frozen"] = 0.0
                    acc["r"] += dr
                self.f_t.append(int(p["t"]))
                self.f_at.append(float(p["at"]))
                self.f_r.append(acc["r"])
                self.f_off.append(loc)               # thêm cuối cùng: luồng chính thấy mẫu thì mọi thứ đã sẵn

        while True:
            rec = self._record_at(pos)
            if rec is None:
                break
            tag, off, n = rec
            pos = off + n
            try:
                if tag == b"B":
                    inner = decode_block(self.mm[off:off + n])
                    bi = len(self.blocks)
                    self.blocks.append((off, n))
                    for k, (t, p) in enumerate(inner):
                        one(t, (lambda p=p: p), ("B", bi, k))
                elif tag in (b"D", b"S", b"Q", b"U", b"F"):
                    one(tag, (lambda off=off, n=n: self._load(off, n)), (off, n))
            except Exception:  # noqa: BLE001
                break
            self._idx_pos = pos
            if (len(self.f_off) & 63) == 0:
                time.sleep(0)                        # nhường GIL cho luồng vẽ
        self.final_tech_times = {k: dict(v) for k, v in st.tech_times.items()}
        self.index_seconds = time.time() - t0

    def _mark_seen(self, st, fi):
        """Công trình nằm trên ô đang nhìn thấy của từng đội: ghi mẫu đầu tiên thấy."""
        if st.vis is None or not any(self._team_vm):
            return
        U = st.arr[st.valid]
        if not len(U):
            return
        _v, defs = self.def_arrays()
        n = defs["n"]
        d = U["def"]
        ut = np.where((d >= 0) & (d < n), defs["utype"][np.clip(d, 0, n - 1)], -1)
        B = U[(ut == 80) & (U["owner"] > 0) & (U["kind"] != 25)]
        if not len(B):
            return
        tx = np.clip(np.floor(B["x"]).astype(np.int32), 0, self.map_w - 1)
        ty = np.clip(np.floor(B["y"]).astype(np.int32), 0, self.map_h - 1)
        bits = st.vis[ty, tx]
        for k, vm in enumerate(self._team_vm):
            hit = (bits & np.uint32(vm)) != 0
            if hit.any():
                seen = self.seen[k]
                for uid in B["uid"][hit].tolist():
                    if uid not in seen:
                        seen[uid] = fi

    def _block(self, bi):
        """Nội dung khối 'B' thứ bi (giữ 6 khối gần nhất đã giải nén)."""
        c = self._block_cache
        v = c.get(bi)
        if v is None:
            off, n = self.blocks[bi]
            v = decode_block(self.mm[off:off + n])
            if len(c) >= 6:
                c.pop(next(iter(c)))
            c[bi] = v
        return v

    def _get(self, loc):
        if loc[0] == "B":
            return self._block(loc[1])[loc[2]][1]
        return self._load(*loc)

    # ---- truy vấn -----------------------------------------------------------------------
    @property
    def n_frames(self):
        return len(self.f_off)

    def progress(self):
        """Tỉ lệ file đã lập chỉ mục (theo byte)."""
        if self.done:
            return 1.0
        if not self.f_off:
            return 0.0
        return min(1.0, self._idx_pos / self.size)

    def read_frame(self, fi):
        return self._get(self.f_off[fi])

    def duration(self):
        return self.f_r[-1] if self.f_r else 0.0

    def frame_at_r(self, r):
        n = self.n_frames
        if n == 0:
            return 0
        return max(0, min(n - 1, bisect.bisect_right(self.f_r, r, 0, n) - 1))

    def frame_at_game_ms(self, t):
        n = self.n_frames
        if n == 0:
            return 0
        return max(0, min(n - 1, bisect.bisect_left(self.f_t, t, 0, n)))

    def statics_index(self, fi):
        """Chỉ số bản ghi vật thể tĩnh có hiệu lực tại mẫu fi (-1 nếu chưa có)."""
        return bisect.bisect_right(self.s_first, fi) - 1

    def stats_at(self, def_idx, fi):
        """Chỉ số (công, giáp, tầm...) của def tại mẫu fi, hoặc None (file cũ / chưa đọc được)."""
        ent = self.stats.get(int(def_idx))
        if not ent:
            return None
        k = bisect.bisect_right(ent[0], fi) - 1
        return ent[1][max(k, 0)]

    def load_statics(self, si):
        """(phiên bản, mảng) vật thể tĩnh sau bản ghi tĩnh thứ si: bản 'S' toàn bộ gần nhất <= si rồi áp các 'Q'."""
        c = self._st_cache
        if c is not None and c[0] == si:
            return c[1], c[2]
        kinds = self.s_kind
        if c is not None and c[0] < si and all(kinds[k] == b"Q" for k in range(c[0] + 1, si + 1)):
            j, ver, arr = c
        else:
            j = si
            while j > 0 and kinds[j] != b"S":
                j -= 1
            p = self._get(self.s_rec[j])
            ver, arr = p.get("version", j), normalize_units(p.get("units"))
        for k in range(j + 1, si + 1):
            p = self._get(self.s_rec[k])
            ver = p.get("version", k)
            arr = _apply_static_delta(arr, normalize_units(p.get("units")), p.get("removed"))
        self._st_cache = (si, ver, arr)
        return ver, arr

    def def_arrays(self):
        """Bảng tra theo index def (cho xử lý unit bằng numpy). Trả về (phiên bản, dict mảng)."""
        cache = getattr(self, "_def_cache", None)
        if cache is not None and cache[0] == self._def_ver:
            return cache
        keys = list(self.defs)                  # luồng lập chỉ mục có thể đang thêm def
        n = (max(keys) + 1) if keys else 1
        utype = np.full(n, -1, np.int16)
        fogvis = np.zeros(n, bool)
        dat_id = np.full(n, -1, np.int32)
        cls = np.full(n, -1, np.int16)
        hp_max = np.zeros(n, np.float32)
        for i, d in list(self.defs.items()):
            utype[i], fogvis[i], dat_id[i], cls[i], hp_max[i] = d.utype, d.fog_visible, d.dat_id, d.cls, d.hp_max or 0
        self._def_cache = (self._def_ver, {"utype": utype, "fogvis": fogvis, "dat_id": dat_id, "cls": cls,
                                           "hp_max": hp_max, "n": n})
        return self._def_cache

    # ---- người chơi, đội -----------------------------------------------------------------
    def _make_players(self):
        hdr = self.header
        players = [PlayerInfo(*p) for p in hdr["players"]]
        for p, civ in zip(players, hdr.get("civs", [])):
            p.civ = civ
        return players

    def real_players(self):
        return [p for p in self.players if p.index != 0 and (p.addr or p.pid)]

    AGE_TECHS = {101: 2, 102: 3, 103: 4}     # Tool / Bronze / Iron Age -> thời đại (thuộc tính 6: 1 = đồ đá)

    def age_events(self):
        """[(thời gian phát r, index người chơi, thời đại mới)] từ giờ hoàn thành công nghệ lên đời."""
        out = []
        for idx, tt in self.final_tech_times.items():
            for tid, age in self.AGE_TECHS.items():
                t = tt.get(tid)
                if t is not None and t > 0:
                    out.append((self.f_r[self.frame_at_game_ms(t)], idx, age))
        return sorted(out)

    def recorder_index(self):
        return int(self.header.get("cur_player_index", -1))

    def players_at(self, st: FrameState):
        """Bản sao người chơi kèm tài nguyên/công nghệ tại trạng thái st."""
        out = []
        for p in self.players:
            q = PlayerInfo(p.index, p.addr, p.pid, p.name, p.mm_color, p.explored_mask, p.visible_mask, p.ptype)
            q.civ = p.civ
            ps = st.pstate.get(p.index)
            if ps is not None:
                q.attrs, q.techs = ps
            q.tech_times = dict(st.tech_times.get(p.index, {}))
            q.researching = dict(st.prs.get(p.index, {}))
            q.available = st.pav.get(p.index)          # None: file trước 2026-10-13 (trình xem tự suy ra)
            q.trainable = st.ptr.get(p.index)
            ps = st.pstat.get(p.index)
            if ps is not None:
                q.ptype, q.resigned = ps
            else:
                q.ptype, q.resigned = 0, 0
            out.append(q)
        return out

    def close(self):
        try:
            self.mm.close()
            self._fh.close()
        except Exception:  # noqa: BLE001
            pass


class Cursor:
    """Con trỏ phát lại: giữ FrameState, tua tới mẫu bất kì bằng điểm mốc + áp mẫu."""

    def __init__(self, data: ReplayData):
        self.data = data
        self.state = FrameState(data.map_w, data.map_h)
        self.version = 0             # tăng mỗi lần trạng thái đổi
        self._si = -2
        self._statics = (None, np.zeros(0, UNIT_DT))

    @property
    def frame(self):
        return self.state.frame

    def seek(self, fi):
        d = self.data
        n = d.n_frames
        if n == 0:
            return False
        fi = max(0, min(n - 1, int(fi)))
        st = self.state
        if fi == st.frame:
            return False
        if fi < st.frame or st.frame < 0 or fi - st.frame > KEY_EVERY:
            k = (fi // KEY_EVERY) * KEY_EVERY
            while k > 0 and k not in d.keys:
                k -= KEY_EVERY
            key = d.keys.get(k)
            if key is not None and (fi < st.frame or key.frame > st.frame):
                st.restore(key)
        while st.frame < fi:
            st.apply(d.read_frame(st.frame + 1), st.frame + 1)
        self.version += 1
        return True

    def statics(self):
        """(chỉ số bản ghi, phiên bản, mảng) vật thể tĩnh tại mẫu hiện tại."""
        si = self.data.statics_index(max(self.state.frame, 0))
        if si != self._si:
            self._si = si
            self._statics = self.data.load_statics(si) if si >= 0 else (None, np.zeros(0, UNIT_DT))
        return si, self._statics[0], self._statics[1]
