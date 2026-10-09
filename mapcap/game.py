"""Đọc trạng thái ván chơi từ bộ nhớ thành một Snapshot."""
import struct
import threading
import time
from dataclasses import dataclass, field

import numpy as np

from . import offsets as O
from .fastread import BulkReader, ListWalker
from .memory import ProcessMemory, MemoryError_


@dataclass
class UnitDefInfo:
    addr: int
    utype: int
    name: str
    dat_id: int
    cls: int
    fog_visible: bool
    mm_mode: int
    mm_color: int
    hp_max: int = 0           # def+0x26


@dataclass
class UnitInfo:
    uid: int
    x: float
    y: float
    z: float
    owner_index: int          # index trong bảng người chơi
    udef: UnitDefInfo
    flags: int
    angle: int = 0            # hướng quay 0..7 (unit+0x35)
    hp: float = 1.0           # máu hiện tại (unit+0x30); cây hết máu -> đổi sang hình "đã đốn"
    status: int = 2           # unit+0x48: 2 = bình thường, >=3 = đang chết/đã đốn
    addr: int = 0             # địa chỉ struct unit trong game (để đọc lại nhanh)
    kind: int = 0             # unit+0x4E: loại đối tượng; 25 = doppelganger (bản ghi nhớ trong sương mù)
    orig_uid: int = -1        # doppelganger: id vật thể gốc
    gid: int = -1             # id đồ hoạ DAT mà game đang vẽ (sprite chính); -1 = chưa đọc được
    frame: int = -1           # khung hiện tại của sprite chính (-1: sprite tĩnh / không có)
    gid2: int = -1            # sprite phụ (lửa khói, hiệu ứng) nếu có
    frame2: int = -1
    res_type: int = -1        # unit+0x4C loại tài nguyên đang chứa (0 thực, 1 gỗ, 2 đá, 3 vàng)
    res_amount: float = 0.0   # unit+0x44 lượng còn lại (cây, xác thú, bụi quả, ruộng, mỏ) / đang mang (dân)

    @property
    def is_dead(self):
        return self.status >= 3 or self.hp <= 0.0

    @property
    def is_doppel(self):
        return self.kind == O.UNIT_KIND_DOPPEL


@dataclass
class PlayerInfo:
    index: int
    addr: int
    pid: int
    name: str
    mm_color: int             # palette index màu trên minimap
    explored_mask: int
    visible_mask: int
    ptype: int
    unit_count: int = 0
    civ: int = -1             # id nền văn minh (0 Gaia, 1 Egyptian ... 16 Macedonian); -1 chưa đọc được
    attrs: tuple = ()         # thuộc tính float (PLAYER+0x50): 0 thực, 1 gỗ, 2 đá, 3 vàng, 11 dân số...
    techs: frozenset = None   # id công nghệ đã nghiên cứu xong; None = chưa đọc được
    tech_times: dict = None   # id công nghệ -> time_ms game lúc lần đầu thấy đã xong (tích luỹ từ đầu bản ghi)
    researching: dict = None  # id công nghệ đang nghiên cứu -> giây đã nghiên cứu (trạng thái 2)
    resigned: int = 0         # PLAYER+0x81: 1 = đã đầu hàng (ptype = PLAYER+0x80: 0 đang chơi, 1 thắng, 2 thua)
    diplomacy: tuple = ()     # PLAYER+0xB0 int32 theo từng người chơi (thái độ ngoại giao, giá trị thô)

    @property
    def game_status(self):
        return self.ptype

    def attr(self, k, default=None):
        return self.attrs[k] if k is not None and 0 <= k < len(self.attrs) else default


@dataclass
class Snapshot:
    taken_at: float
    time_ms: int
    speed: float
    map_w: int
    map_h: int
    terrain: np.ndarray       # uint8 [h, w] id địa hình
    elevation: np.ndarray     # uint8 [h, w]
    shape: np.ndarray         # uint8 [h, w]
    vis_raw: np.ndarray       # uint32 [h, w]
    terrain_colors: list      # 32 x (c_b4, c_b5, c_b6) palette index
    reveal: bool
    cur_player_index: int
    players: list = field(default_factory=list)
    units: list = field(default_factory=list)
    addrs: dict = field(default_factory=dict)
    tile_dx: np.ndarray = None   # int16 [h, w] toạ độ vẽ ô do game tính (byte +0)
    tile_dy: np.ndarray = None   # int16 [h, w] (byte +2)
    tile_border: np.ndarray = None  # uint8 [h, w] byte +6: (config << 4) | border_id
    tile_units_ptr: np.ndarray = None  # uint32 [h, w] con trỏ danh sách vật thể trên ô (+0x10)
    static_units: list = None      # vật thể gắn với ô (cây rừng...), vẽ thành lớp riêng trong video
    static_version: int = 0        # tăng mỗi lần quét lại -> bộ vẽ video dựng lại lớp tĩnh
    game_over: int = 0             # GLOBAL+0x1D: 1 khi ván đã kết thúc
    match: dict = None             # thiết lập ván (GameReader.match_settings), đọc một lần mỗi trận
    def_stats: dict = None         # địa chỉ def -> chỉ số (công, giáp, tầm...); chỉ có ở mẫu vừa đọc lại (3 s/lần)

    @property
    def cur_player(self):
        return self.players[self.cur_player_index] if 0 <= self.cur_player_index < len(self.players) else None

    def explored(self):
        p = self.cur_player
        if self.reveal or p is None:
            return np.ones_like(self.vis_raw, dtype=bool)
        return (self.vis_raw & np.uint32(p.explored_mask)) != 0

    def visible(self):
        p = self.cur_player
        if self.reveal or p is None:
            return np.ones_like(self.vis_raw, dtype=bool)
        return (self.vis_raw & np.uint32(p.visible_mask)) != 0

    def time_str(self):
        s = self.time_ms // 1000
        return f"{s // 3600:02d}:{(s // 60) % 60:02d}:{s % 60:02d}"


class DoppelTracker:
    """Theo dõi doppelganger (bản ghi nhớ trong sương mù) của người chơi hiện tại, đúng như game:
    game tạo doppel khi ô có vật thể (công trình, cây, mỏ...) rơi vào sương mù và tự huỷ khi ô được nhìn lại.
    Mỗi mẫu chỉ quét danh sách vật thể của các ô VỪA mất tầm nhìn (vài ô) nên rẻ; quét toàn bộ do
    StaticObjects cung cấp định kỳ qua merge()."""

    PENDING_FRAMES = 30      # còn quét lại ô bao nhiêu mẫu sau khi mất tầm nhìn (game tạo doppel ở tick sau)
    STAGGER = 3              # mỗi ô đang chờ chỉ quét 1 trong 3 mẫu

    def __init__(self, reader):
        self.reader = reader
        self.lock = threading.Lock()
        self.units = {}
        self.pending = {}
        self.prev_visible = None
        self.frame = 0
        self.found_total = 0
        self.last_refresh = 0.0

    def reset(self):
        with self.lock:
            self.units = {}          # addr -> UnitInfo (kind 25, udef/owner đã là của vật thể gốc)
            self.pending = {}        # (y, x) -> số mẫu còn quét
            self.prev_visible = None
            self.frame = 0
            self.found_total = 0
            self.last_refresh = 0.0

    def count(self):
        return len(self.units)

    def update(self, snap):
        p = snap.cur_player
        if p is None or snap.reveal or not p.addr:
            return []
        vis = (snap.vis_raw & np.uint32(p.visible_mask)) != 0
        self.frame += 1
        with self.lock:
            if self.prev_visible is not None and self.prev_visible.shape == vis.shape:
                lost = self.prev_visible & ~vis
                if snap.tile_units_ptr is not None:
                    lost &= snap.tile_units_ptr != 0        # ô không có vật thể thì không thể có doppel
                for y, x in zip(*np.nonzero(lost)):
                    self.pending[(int(y), int(x))] = self.PENDING_FRAMES
            self.prev_visible = vis
            h, w = vis.shape
            for a, u in list(self.units.items()):           # game huỷ doppel khi chủ nhìn lại ô
                ty, tx = int(u.y), int(u.x)
                if not (0 <= ty < h and 0 <= tx < w) or vis[ty, tx]:
                    del self.units[a]
            tiles = [t for t, n in self.pending.items() if n == self.PENDING_FRAMES or (n + self.frame) % self.STAGGER == 0]
            for t in list(self.pending):
                self.pending[t] -= 1
                if self.pending[t] <= 0:
                    del self.pending[t]
        if tiles:
            found = self.reader.scan_doppels(snap, tiles)
            with self.lock:
                for u in found:
                    if u.addr not in self.units:
                        self.found_total += 1
                    self.units[u.addr] = u
        now = time.time()
        if self.units and now - self.last_refresh >= 2.0:  # doppel bị huỷ, bộ nhớ dùng lại -> loại
            self.last_refresh = now
            with self.lock:
                cur = list(self.units.values())
            raws = self.reader.bulk.read_many([u.addr for u in cur], O.UNIT_READ_SIZE)
            with self.lock:
                for u in cur:
                    raw = raws.get(u.addr)
                    if (raw is None or len(raw) < O.UNIT_READ_SIZE or raw[O.UNIT_TYPE_BYTE] != O.UNIT_KIND_DOPPEL
                            or raw[O.UNIT_STATUS] >= 3):
                        self.units.pop(u.addr, None)
        with self.lock:
            return list(self.units.values())

    def merge(self, found):
        """Nhận kết quả quét toàn bộ ô: thêm doppel chưa biết."""
        with self.lock:
            for u in found:
                if u.addr not in self.units:
                    self.units[u.addr] = u
                    self.found_total += 1


class GameReader:
    def __init__(self, mem: ProcessMemory):
        self.mem = mem
        self._def_cache = {}
        self.bulk = BulkReader(mem)
        self.walker = ListWalker(mem, self.bulk)
        self.doppels = DoppelTracker(self)
        self._sprite_gid = {}        # địa chỉ RGE_Sprite -> id đồ hoạ DAT (tĩnh suốt ván)
        self._tech_times = {}        # index người chơi -> {id công nghệ: time_ms lần đầu thấy xong}
        self.read_sprites = True

    @staticmethod
    def _parse_unit(raw, ua, owner, udef):
        uid = struct.unpack_from("<i", raw, O.UNIT_ID)[0]
        x, y, z = struct.unpack_from("<fff", raw, O.UNIT_POS_X)
        hp = struct.unpack_from("<f", raw, O.UNIT_HP)[0]
        kind = raw[O.UNIT_TYPE_BYTE]
        if kind == O.UNIT_KIND_DOPPEL:
            uid = -(ua >> 2)          # id riêng, âm, ổn định theo địa chỉ (id của game cho doppel không dùng được)
        return UnitInfo(uid=uid, x=x, y=y, z=z, owner_index=owner, udef=udef, flags=raw[O.UNIT_FLAGS],
                        angle=raw[O.UNIT_ANGLE] & 7, hp=hp, status=raw[O.UNIT_STATUS], addr=ua, kind=kind,
                        res_type=struct.unpack_from("<h", raw, O.UNIT_RES_TYPE)[0],
                        res_amount=struct.unpack_from("<f", raw, O.UNIT_RES_AMOUNT)[0])

    def _finish_doppels(self, units, players):
        """Doppelganger: thay unitdef/màu bằng của vật thể gốc (đọc thêm phần +0x8C..+0xB0)."""
        dps = [u for u in units if u.kind == O.UNIT_KIND_DOPPEL]
        if not dps:
            return units
        pid_to_index = {p.pid: p.index for p in players}
        raws = self.bulk.read_many([u.addr for u in dps], O.UNIT_DOPPEL_READ_SIZE)
        out = []
        for u in units:
            if u.kind != O.UNIT_KIND_DOPPEL:
                out.append(u)
                continue
            raw = raws.get(u.addr)
            if raw is None or len(raw) < O.UNIT_DOPPEL_READ_SIZE:
                continue
            odef = struct.unpack_from("<I", raw, O.UNIT_DOPPEL_ORIG_DEF)[0]
            oowner = struct.unpack_from("<i", raw, O.UNIT_DOPPEL_ORIG_OWNER)[0]
            u.orig_uid = struct.unpack_from("<i", raw, O.UNIT_DOPPEL_ORIG_UID)[0]
            if odef and odef != u.udef.addr:
                try:
                    u.udef = self.unit_def(odef)
                except MemoryError_:
                    pass
            u.owner_index = pid_to_index.get(oowner, u.owner_index)
            out.append(u)
        return out

    # ---- cấp thấp ------------------------------------------------------------
    def settings(self):
        return self.mem.u32(O.SETTINGS_PTR)

    def global_ptr(self):
        s = self.settings()
        return self.mem.u32(s + O.SETTINGS_GLOBAL) if s else 0

    def in_game(self):
        """True khi có thế giới game và bản đồ đã nạp."""
        g = self.global_ptr()
        if not g:
            return False
        m = self.mem.u32(g + O.GLOBAL_MAPINFO)
        if not m:
            return False
        w = self.mem.i16(m + O.MAP_SIZE_X)
        h = self.mem.i16(m + O.MAP_SIZE_Y)
        return 8 <= w <= 512 and 8 <= h <= 512 and self.mem.i16(g + O.GLOBAL_PLAYER_COUNT) > 0

    def game_time_ms(self):
        g = self.global_ptr()
        return self.mem.u32(g + O.GLOBAL_TIME_MS) if g else None

    # ---- unit def ------------------------------------------------------------
    STATS_EVERY = 3.0          # giây: đọc lại chỉ số mọi def đã gặp (bắt nâng cấp công nghệ)

    def def_stats(self, addrs):
        """Chỉ số của các def (đã nâng cấp theo công nghệ của người chơi sở hữu bản sao def): dict addr -> dict."""
        addrs = list(addrs)
        raws = self.bulk.read_many(addrs, O.UNITDEF_STATS_SIZE)
        lists = []
        out = {}
        for a in addrs:
            raw = raws.get(a)
            if raw is None or len(raw) < O.UNITDEF_STATS_SIZE:
                raw = self.mem.try_read(a, O.UNITDEF_STATS_SIZE)
            if not raw or len(raw) < O.UNITDEF_STATS_SIZE:
                continue
            utype = raw[O.UNITDEF_TYPE]
            st = {"lang": struct.unpack_from("<h", raw, O.UNITDEF_LANG_NAME)[0],
                  "hp": struct.unpack_from("<h", raw, O.UNITDEF_HP)[0],
                  "los": round(struct.unpack_from("<f", raw, O.UNITDEF_LOS)[0], 3)}
            if utype >= 20:
                st["speed"] = round(struct.unpack_from("<f", raw, O.UNITDEF_SPEED)[0], 3)
            if utype >= 50:                          # 50 combat, 60 missile, 70, 80 đều kế thừa loại 50
                f = lambda off: round(struct.unpack_from("<f", raw, off)[0], 3)  # noqa: E731
                h = lambda off: struct.unpack_from("<h", raw, off)[0]  # noqa: E731
                st.update({"armor0": raw[O.UNITDEF_BASE_ARMOR], "range": f(O.UNITDEF_MAX_RANGE),
                           "min_range": f(O.UNITDEF_MIN_RANGE), "reload": f(O.UNITDEF_RELOAD),
                           "accuracy": h(O.UNITDEF_ACCURACY), "d_melee": h(O.UNITDEF_DISP_MELEE_ARMOR),
                           "d_attack": h(O.UNITDEF_DISP_ATTACK), "d_range": f(O.UNITDEF_DISP_RANGE),
                           "d_reload": f(O.UNITDEF_DISP_RELOAD)})
                for key, cnt_off, ptr_off in (("attacks", O.UNITDEF_ATTACK_COUNT, O.UNITDEF_ATTACKS),
                                              ("armors", O.UNITDEF_ARMOR_COUNT, O.UNITDEF_ARMORS)):
                    n = h(cnt_off)
                    ptr = struct.unpack_from("<I", raw, ptr_off)[0]
                    st[key] = []
                    if 0 < n <= 32 and ptr:
                        lists.append((a, key, ptr, n))
            if utype >= 70:
                h = lambda off: struct.unpack_from("<h", raw, off)[0]  # noqa: E731
                st["train"] = h(O.UNITDEF_TRAIN_TIME)
                st["d_pierce"] = h(O.UNITDEF_DISP_PIERCE)
                st["costs"] = [(h(O.UNITDEF_COSTS + 6 * k), h(O.UNITDEF_COSTS + 6 * k + 2)) for k in range(3)
                               if h(O.UNITDEF_COSTS + 6 * k) >= 0 and h(O.UNITDEF_COSTS + 6 * k + 2) > 0]
            out[a] = st
        if lists:
            lraws = self.bulk.read_many([p for _a, _k, p, _n in lists], 4 * 32)
            for a, key, ptr, n in lists:
                b = lraws.get(ptr)
                if b is None or len(b) < 4 * n:
                    b = self.mem.try_read(ptr, 4 * n)
                if b and len(b) >= 4 * n:
                    vals = struct.unpack_from(f"<{2 * n}h", b)
                    out[a][key] = [(vals[2 * k], vals[2 * k + 1]) for k in range(n)]
        return out

    def maybe_def_stats(self):
        """Mỗi STATS_EVERY giây (hoặc khi có def mới): chỉ số mọi def đã gặp; ngược lại None."""
        now = time.time()
        known = len(self._def_cache)
        if now - getattr(self, "_stats_t", 0.0) < self.STATS_EVERY and known == getattr(self, "_stats_n", -1):
            return None
        self._stats_t, self._stats_n = now, known
        try:
            return self.def_stats(self._def_cache.keys())
        except Exception:  # noqa: BLE001
            return None

    def unit_def(self, addr):
        d = self._def_cache.get(addr)
        if d is not None:
            return d
        raw = self.mem.read(addr, O.UNITDEF_READ_SIZE)
        name_ptr = struct.unpack_from("<I", raw, O.UNITDEF_NAME)[0]
        d = UnitDefInfo(
            addr=addr,
            utype=raw[O.UNITDEF_TYPE],
            name=self.mem.cstr(name_ptr, 64) if name_ptr else "",
            dat_id=struct.unpack_from("<h", raw, O.UNITDEF_ID)[0],
            cls=struct.unpack_from("<h", raw, O.UNITDEF_CLASS)[0],
            fog_visible=raw[O.UNITDEF_FOG_VISIBLE] != 0,
            mm_mode=raw[O.UNITDEF_MINIMAP_MODE],
            mm_color=raw[O.UNITDEF_MINIMAP_COLOR],
            hp_max=struct.unpack_from("<h", raw, O.UNITDEF_HP)[0],
        )
        self._def_cache[addr] = d
        return d

    # ---- danh sách unit -------------------------------------------------------
    def iter_list(self, header_ptr, limit=50000):
        if not header_ptr:
            return
        node = self.mem.u32(header_ptr + O.LIST_FIRST)
        n = 0
        while node and n < limit:
            unit, nxt = struct.unpack("<II", self.mem.read(node, 8))
            if unit:
                yield unit
            node = nxt
            n += 1

    def read_unit(self, addr, owner_index):
        raw = self.mem.read(addr, O.UNIT_READ_SIZE)
        defp = struct.unpack_from("<I", raw, O.UNIT_DEF)[0]
        if not defp:
            return None
        return self._parse_unit(raw, addr, owner_index, self.unit_def(defp))

    # ---- vật thể gắn với ô (cây rừng, đá, ... không nằm trong danh sách người chơi) --------
    def _looks_like_unit(self, addr):
        try:
            if not (0x10000 <= addr < 0x7FFF0000):
                return False
            defp = self.mem.u32(addr + O.UNIT_DEF)
            if not (0x10000 <= defp < 0x7FFF0000):
                return False
            return self.mem.u8(defp + O.UNITDEF_TYPE) in (10, 20, 25, 30, 40, 60, 70, 80, 90)
        except MemoryError_:
            return False

    def iter_tile_list(self, ptr, limit=64):
        """Duyệt danh sách vật thể của một ô. Tự nhận dạng con trỏ là node hay header."""
        if not ptr:
            return
        try:
            a, b = struct.unpack("<II", self.mem.read(ptr, 8))
        except MemoryError_:
            return
        if self._looks_like_unit(a):
            node = ptr
        else:
            node = b if b else a
        n = 0
        while node and n < limit:
            try:
                unit, nxt = struct.unpack("<II", self.mem.read(node, 8))
            except MemoryError_:
                return
            if unit and self._looks_like_unit(unit):
                yield unit
            node = nxt
            n += 1

    def scan_tile_units(self, snap, known_uids=None, owner_of=None, doppels=None):
        """Đọc vật thể trên mọi ô có danh sách; trả về list UnitInfo chưa có trong known_uids.

        owner_of: dict địa chỉ PLAYER -> index; nếu None thì suy từ snap.players.
        doppels: nếu là list thì nhận thêm doppelganger của người chơi hiện tại (đã hoàn thiện def/màu gốc).
        """
        if snap.tile_units_ptr is None:
            return []
        if owner_of is None:
            owner_of = {p.addr: p.index for p in snap.players if p.addr}
        known = set(known_uids or ())
        cur = snap.cur_player
        cur_addr = cur.addr if cur else 0
        raw_dops = []
        out = []
        seen_addr = set()
        ys, xs = np.nonzero(snap.tile_units_ptr)
        for y, x in zip(ys.tolist(), xs.tolist()):
            for ua in self.iter_tile_list(int(snap.tile_units_ptr[y, x])):
                if ua in seen_addr:
                    continue
                seen_addr.add(ua)
                try:
                    raw = self.mem.read(ua, O.UNIT_READ_SIZE)
                except MemoryError_:
                    continue
                uid, defp, ownerp = struct.unpack_from("<iII", raw, O.UNIT_ID)
                if not defp:
                    continue
                if raw[O.UNIT_TYPE_BYTE] == O.UNIT_KIND_DOPPEL:
                    # bản ghi nhớ trong sương mù: không phải vật thể tĩnh; chỉ lấy của người chơi hiện tại
                    if doppels is not None and ownerp == cur_addr and cur is not None:
                        try:
                            raw_dops.append(self._parse_unit(raw, ua, cur.index, self.unit_def(defp)))
                        except MemoryError_:
                            pass
                    continue
                if uid in known:
                    continue
                udef = self.unit_def(defp)
                if udef.utype in (60, 70, 80):      # unit sống, công trình, đạn: đã có trong danh sách người chơi
                    continue
                out.append(self._parse_unit(raw, ua, owner_of.get(ownerp, 0), udef))
        if doppels is not None and raw_dops:
            doppels.extend(self._finish_doppels(raw_dops, snap.players))
        return out

    def scan_doppels(self, snap, tiles):
        """Đọc doppelganger của người chơi hiện tại trên các ô (y, x) cho trước."""
        p = snap.cur_player
        if p is None or not p.addr or snap.tile_units_ptr is None:
            return []
        out = []
        seen = set()
        h, w = snap.tile_units_ptr.shape
        for (y, x) in tiles:
            if not (0 <= y < h and 0 <= x < w):
                continue
            ptr = int(snap.tile_units_ptr[y, x])
            if not ptr:
                continue
            for ua in self.iter_tile_list(ptr):
                if ua in seen:
                    continue
                seen.add(ua)
                try:
                    raw = self.mem.read(ua, O.UNIT_READ_SIZE)
                except MemoryError_:
                    continue
                if raw[O.UNIT_TYPE_BYTE] != O.UNIT_KIND_DOPPEL:
                    continue
                defp, ownerp = struct.unpack_from("<II", raw, O.UNIT_DEF)
                if ownerp != p.addr or not defp:
                    continue
                try:
                    out.append(self._parse_unit(raw, ua, p.index, self.unit_def(defp)))
                except MemoryError_:
                    continue
        return self._finish_doppels(out, snap.players)

    def refresh_units(self, units):
        """Đọc lại máu/trạng thái/định nghĩa của các UnitInfo đã biết (đọc gộp). Trả về (list mới, số thay đổi).
        Unit không còn đọc được thì bị loại."""
        addrs = [u.addr for u in units if u.addr]
        raws = self.bulk.read_many(addrs, O.UNIT_READ_SIZE)
        out = []
        changed = 0
        for u in units:
            raw = raws.get(u.addr)
            if raw is None or len(raw) < O.UNIT_READ_SIZE:
                changed += 1
                continue
            uid, defp = struct.unpack_from("<iI", raw, O.UNIT_ID)
            if uid != u.uid or not defp:
                changed += 1            # ô nhớ đã dùng cho unit khác
                continue
            try:
                udef = self.unit_def(defp) if defp != u.udef.addr else u.udef
            except MemoryError_:
                continue
            nu = self._parse_unit(raw, u.addr, u.owner_index, udef)
            if nu.is_dead != u.is_dead or nu.udef is not u.udef or int(nu.res_amount) != int(u.res_amount):
                changed += 1            # kể cả gỗ/thực/vàng còn lại đổi -> bản ghi vật thể tĩnh mới
            out.append(nu)
        return out, changed

    def _read_techs(self, raw, paddr):
        """Tập id công nghệ đã nghiên cứu xong (trạng thái 3) của người chơi; None nếu không đọc được."""
        try:
            obj = struct.unpack_from("<I", raw, O.PLAYER_RESEARCH)[0]
            if not obj:
                return None
            hdr = self.mem.try_read(obj, 8)
            if not hdr:
                return None
            arr = struct.unpack_from("<I", hdr, O.RESEARCH_STATES)[0]
            n = struct.unpack_from("<h", hdr, O.RESEARCH_COUNT)[0]
            if not arr or not (0 < n <= 1024):
                return None
            data = self.mem.try_read(arr, n * O.RESEARCH_ENTRY_SIZE)
            if not data:
                return None
            st = np.frombuffer(data, np.int16)[O.RESEARCH_ENTRY_STATE // 2::O.RESEARCH_ENTRY_SIZE // 2]
            prog = np.frombuffer(data, np.float32)[O.RESEARCH_ENTRY_PROGRESS // 4::O.RESEARCH_ENTRY_SIZE // 4]
            active = np.nonzero(st == O.RESEARCH_STATE_ACTIVE)[0].tolist()
            self._researching = {int(t): round(float(prog[t]), 1) for t in active}
            return frozenset(np.nonzero(st == O.RESEARCH_STATE_DONE)[0].tolist())
        except (MemoryError_, struct.error):
            return None

    # ---- tên người chơi -------------------------------------------------------
    def player_names(self, g, count):
        names = {}
        try:
            gi = self.mem.u32(g + O.GLOBAL_GAMEINFO)
            obj = self.mem.u32(gi + O.GAMEINFO_NAMES_OBJ) if gi else 0
            if obj:
                own = self.mem.i32(obj + O.NAMES_OWN_INDEX)
                table = self.mem.u32(obj + O.NAMES_TABLE)
                n = self.mem.u16(obj + O.NAMES_COUNT)
                for i in range(min(count, n + 1, 16)):
                    if i == own:
                        names[i] = self.mem.cstr(obj + O.NAMES_OWN_NAME, 64)
                    elif table:
                        names[i] = self.mem.cstr(table + i * O.NAMES_ENTRY_SIZE, 64)
        except MemoryError_:
            pass
        return names

    # ---- snapshot -------------------------------------------------------------
    def match_settings(self, g, count):
        """Thiết lập ván (bản đồ, đội, nền văn minh chọn, tài nguyên...), đọc một lần cho mỗi GLOBAL."""
        cache = getattr(self, "_match_cache", None)
        if cache is not None and cache[0] == g:
            return cache[1]
        info = None
        try:
            s = self.settings()
            blk = self.mem.read(s + O.SETTINGS_READ_START, O.SETTINGS_READ_END - O.SETTINGS_READ_START)

            def b(off):
                return blk[off - O.SETTINGS_READ_START]

            def i32(off):
                return struct.unpack_from("<i", blk, off - O.SETTINGS_READ_START)[0]
            n = max(0, count - 1)
            info = {
                "random_game": self.mem.i32(s + O.SETTINGS_RANDOM_GAME), "random_map": self.mem.i32(s + O.SETTINGS_RANDOM_MAP),
                "map_type": i32(O.SETTINGS_MAP_TYPE), "map_size": i32(O.SETTINGS_MAP_SIZE),
                "victory": i32(O.SETTINGS_VICTORY), "victory_value": i32(O.SETTINGS_VICTORY_VALUE),
                "resources": i32(O.SETTINGS_RESOURCES), "start_age": i32(O.SETTINGS_START_AGE),
                "reveal_map": b(O.SETTINGS_REVEAL_MAP), "full_tech": b(O.SETTINGS_FULL_TECH),
                "deathmatch": b(O.SETTINGS_DEATHMATCH), "flag_ae4": b(O.SETTINGS_FLAG_AE4),
                # mảng theo người chơi 1..n (chỉ số 0 của mảng = người chơi 1)
                "teams": [b(O.SETTINGS_TEAMS + k) - 1 for k in range(n)],
                "civs": [b(O.SETTINGS_CIVS + k) for k in range(n)],
                "slots": [b(O.SETTINGS_PLAYERS + k) for k in range(n)],
                "raw": bytes(blk),                     # giữ nguyên khối để phân tích sau (368 byte)
            }
        except Exception:  # noqa: BLE001
            info = None
        self._match_cache = (g, info)
        return info

    def snapshot(self, with_units=True):
        self.bulk.begin_frame()
        try:
            return self._snapshot(with_units)
        finally:
            self.bulk.end_frame()

    def _snapshot(self, with_units=True):
        mem = self.mem
        g = self.global_ptr()
        if not g:
            raise MemoryError_("chưa vào trận (GLOBAL = 0)")
        m = mem.u32(g + O.GLOBAL_MAPINFO)
        if not m:
            raise MemoryError_("chưa có bản đồ (MAPINFO = 0)")
        w = mem.i16(m + O.MAP_SIZE_X)
        h = mem.i16(m + O.MAP_SIZE_Y)
        if not (8 <= w <= 512 and 8 <= h <= 512):
            raise MemoryError_(f"kích cỡ bản đồ bất thường {w}x{h}")
        time_ms = mem.u32(g + O.GLOBAL_TIME_MS)
        speed = mem.f32(g + O.GLOBAL_SPEED)

        # địa hình
        rows = mem.ptrs(mem.u32(m + O.MAP_TILE_ROWS), h)
        terrain = np.zeros((h, w), np.uint8)
        elevation = np.zeros((h, w), np.uint8)
        shape = np.zeros((h, w), np.uint8)
        tile_dx = np.zeros((h, w), np.int16)
        tile_dy = np.zeros((h, w), np.int16)
        tile_border = np.zeros((h, w), np.uint8)
        tile_units_ptr = np.zeros((h, w), np.uint32)
        row_raws = self.bulk.read_many([rp for rp in rows if rp], w * O.TILE_SIZE)
        for y, rp in enumerate(rows):
            raw = row_raws.get(rp) if rp else None
            if raw is None:
                raw = mem.read(rp, w * O.TILE_SIZE)
            arr = np.frombuffer(raw, np.uint8).reshape(w, O.TILE_SIZE)
            tb = arr[:, O.TILE_TERRAIN]
            terrain[y] = tb & 0x1F
            elevation[y] = tb >> 5
            shape[y] = arr[:, O.TILE_SHAPE]
            i16 = np.frombuffer(raw, np.int16).reshape(w, O.TILE_SIZE // 2)
            tile_dx[y] = i16[:, 0]
            tile_dy[y] = i16[:, 1]
            tile_border[y] = arr[:, O.TILE_BORDER]
            tile_units_ptr[y] = np.frombuffer(raw, np.uint32).reshape(w, O.TILE_SIZE // 4)[:, O.TILE_UNITS_LIST // 4]

        # màu minimap của 32 địa hình
        tdefs = mem.read(m + O.MAP_TERRAIN_DEFS, 32 * O.TERRAIN_DEF_SIZE)
        terrain_colors = [tuple(tdefs[t * O.TERRAIN_DEF_SIZE + c] for c in O.TERRAIN_MINIMAP_COLORS) for t in range(32)]
        reveal = mem.u8(m + O.MAP_REVEAL_FLAG) != 0

        # tầm nhìn
        vrows = mem.ptrs(O.VISIBILITY_ROWS, h)
        vis = np.zeros((h, w), np.uint32)
        vrow_raws = self.bulk.read_many([rp for rp in vrows if rp], w * 4)
        for y, rp in enumerate(vrows):
            if rp:
                raw = vrow_raws.get(rp)
                if raw is None:
                    raw = mem.read(rp, w * 4)
                vis[y] = np.frombuffer(raw, np.uint32)

        # người chơi
        count = mem.i16(g + O.GLOBAL_PLAYER_COUNT)
        count = max(0, min(count, 16))
        table = mem.u32(g + O.GLOBAL_PLAYERS)
        pptrs = mem.ptrs(table, count) if table and count else ()
        cur_id = mem.i16(g + O.GLOBAL_CUR_PLAYER_ID)
        names = self.player_names(g, count)
        players = []
        praws = self.bulk.read_many([p for p in pptrs if p], O.PLAYER_READ_SIZE)
        for i, p in enumerate(pptrs):
            raw = praws.get(p) if p else None
            if not p or raw is None or len(raw) < O.PLAYER_READ_SIZE:
                players.append(PlayerInfo(i, 0, i, names.get(i, f"P{i}"), 0, 0, 0, 0))
                continue
            pid = struct.unpack_from("<h", raw, O.PLAYER_ID)[0]
            cptr = struct.unpack_from("<I", raw, O.PLAYER_COLOR_PTR)[0]
            mm_color = mem.u8(cptr + O.PLAYER_COLOR_MINIMAP) if cptr else 0
            pl = PlayerInfo(
                index=i, addr=p, pid=pid, name=names.get(i, f"P{i}"), mm_color=mm_color,
                explored_mask=struct.unpack_from("<I", raw, O.PLAYER_EXPLORED_MASK)[0],
                visible_mask=struct.unpack_from("<I", raw, O.PLAYER_VISIBLE_MASK)[0],
                ptype=raw[O.PLAYER_GAME_STATUS])
            pl.resigned = raw[O.PLAYER_RESIGNED]
            nd = max(0, min(count, (O.PLAYER_EXPLORED_MASK - O.PLAYER_DIPLOMACY) // 4))
            pl.diplomacy = struct.unpack_from(f"<{nd}i", raw, O.PLAYER_DIPLOMACY) if nd else ()
            n_attr = struct.unpack_from("<h", raw, O.PLAYER_ATTR_COUNT)[0]
            aptr = struct.unpack_from("<I", raw, O.PLAYER_ATTRS)[0]
            if 0 < n_attr <= 512 and aptr:
                n = min(n_attr, O.ATTR_READ_MAX)
                ab = mem.try_read(aptr, 4 * n)
                if ab:
                    pl.attrs = struct.unpack_from(f"<{n}f", ab)
            if O.PLAYER_CIV is not None:
                pl.civ = raw[O.PLAYER_CIV]
            self._researching = None
            pl.techs = self._read_techs(raw, p)
            pl.researching = self._researching
            if pl.techs is not None:
                tt = self._tech_times.setdefault(i, {})
                for tid in pl.techs:
                    if tid not in tt:
                        tt[tid] = time_ms
                pl.tech_times = dict(tt)
            players.append(pl)
        cur_index = next((pl.index for pl in players if pl.pid == cur_id), cur_id if 0 <= cur_id < len(players) else 0)

        snap = Snapshot(taken_at=time.time(), time_ms=time_ms, speed=speed, map_w=w, map_h=h,
                        terrain=terrain, elevation=elevation, shape=shape, vis_raw=vis,
                        terrain_colors=terrain_colors, reveal=reveal, cur_player_index=cur_index,
                        players=players, addrs={"settings": self.settings(), "global": g, "mapinfo": m},
                        tile_dx=tile_dx, tile_dy=tile_dy, tile_border=tile_border, tile_units_ptr=tile_units_ptr)
        snap.game_over = mem.u8(g + O.GLOBAL_GAME_OVER)
        snap.match = self.match_settings(g, count)

        if with_units:
            headers = []
            hdr_ptrs = {}
            for pl in players:
                if pl.addr:
                    for off in (O.PLAYER_LIST_B, O.PLAYER_LIST_A):
                        hdr_ptrs[(pl.index, off)] = pl.addr + off
            hb = self.bulk.read_many(list(hdr_ptrs.values()), 4)
            for (idx, off), a in hdr_ptrs.items():
                b = hb.get(a)
                if b:
                    h = struct.unpack("<I", b)[0]
                    if h:
                        headers.append((h, idx))
            pairs = self.walker.walk_many(headers)
            seen = set()
            addrs = []
            for ua, idx in pairs:
                if ua in seen:
                    continue
                seen.add(ua)
                addrs.append((ua, idx))
            for u in self.read_units_bulk(addrs):
                if u.kind == O.UNIT_KIND_DOPPEL:
                    # đối tượng loại 25 trong danh sách người chơi (thấy ở AI) không phải ký ức sương mù của ta;
                    # doppelganger thật nằm trong danh sách vật thể của ô, DoppelTracker lấy (đã đối chiếu test thật)
                    continue
                snap.units.append(u)
                players[u.owner_index].unit_count += 1
            snap.units.extend(self.doppels.update(snap))
            snap.def_stats = self.maybe_def_stats()
        return snap

    UNIT_RAW_DT = np.dtype({
        "names": ["uid", "defp", "ownerp", "splist", "hp", "angle", "flags", "x", "y", "z", "status", "kind",
                  "ramount", "rtype"],
        "formats": ["<i4", "<u4", "<u4", "<u4", "<f4", "u1", "u1", "<f4", "<f4", "<f4", "u1", "u1", "<f4", "<i2"],
        "offsets": [O.UNIT_ID, O.UNIT_DEF, O.UNIT_OWNER, O.UNIT_SPRITE_LIST, O.UNIT_HP, O.UNIT_ANGLE, O.UNIT_FLAGS,
                    O.UNIT_POS_X, O.UNIT_POS_Y, O.UNIT_POS_Z, O.UNIT_STATUS, O.UNIT_TYPE_BYTE, O.UNIT_RES_AMOUNT,
                    O.UNIT_RES_TYPE],
        "itemsize": O.UNIT_READ_SIZE})

    @staticmethod
    def _stack(raws, addrs, size):
        """Ghép các bản ghi (dict addr->bytes) theo thứ tự addrs thành mảng uint8 (N, size); thiếu -> hàng 0 và mask."""
        n = len(addrs)
        buf = bytearray(n * size)
        ok = np.zeros(n, bool)
        for i, a in enumerate(addrs):
            b = raws.get(a)
            if b is not None and len(b) >= size:
                buf[i * size:(i + 1) * size] = b[:size]
                ok[i] = True
        return np.frombuffer(bytes(buf), np.uint8).reshape(n, size), ok

    def read_units_bulk(self, addrs):
        """Đọc nhiều unit bằng ít lần ReadProcessMemory; phân tích bằng numpy."""
        if not addrs:
            return []
        ua = [a for a, _ in addrs]
        owners = [o for _, o in addrs]
        blk, ok = self.bulk.gather(ua, O.UNIT_READ_SIZE)
        rec = blk.view(self.UNIT_RAW_DT).reshape(-1)
        defps = rec["defp"]
        udefs = {}
        for d in np.unique(defps[ok]).tolist():
            if d:
                try:
                    udefs[d] = self.unit_def(d)
                except MemoryError_:
                    pass
        out = []
        lists = []
        uid = rec["uid"].tolist(); hp = rec["hp"].tolist(); ang = rec["angle"].tolist(); fl = rec["flags"].tolist()
        xs = rec["x"].tolist(); ys = rec["y"].tolist(); zs = rec["z"].tolist(); st = rec["status"].tolist()
        kd = rec["kind"].tolist(); sl = rec["splist"].tolist(); dp = defps.tolist()
        ram = rec["ramount"].tolist(); rty = rec["rtype"].tolist()
        for i in range(len(ua)):
            if not ok[i]:
                continue
            udef = udefs.get(dp[i])
            if udef is None:
                continue
            k = kd[i]
            u = UnitInfo(uid=(-(ua[i] >> 2) if k == O.UNIT_KIND_DOPPEL else uid[i]), x=xs[i], y=ys[i], z=zs[i],
                         owner_index=owners[i], udef=udef, flags=fl[i], angle=ang[i] & 7, hp=hp[i], status=st[i],
                         addr=ua[i], kind=k, res_type=rty[i], res_amount=ram[i])
            out.append(u)
            lists.append(sl[i])
        if self.read_sprites:
            self.attach_sprites(out, lists)
        return out

    def attach_sprites(self, units, list_ptrs):
        """Gắn (gid, frame) của sprite chính và sprite phụ đầu tiên cho từng unit: 4 lượt read_many (hầu hết trúng bộ
        đệm khoảng) và phân tích bằng numpy: list -> node đầu -> sprite node -> RGE_Sprite (id đồ hoạ cache)."""
        n = len(units)
        if n == 0:
            return
        lp = np.asarray(list_ptrs, np.uint64)
        has = lp != 0
        hb, hok = self.bulk.gather(lp, 8)
        node1 = np.where(hok, hb[:, O.SPRLIST_HEAD:O.SPRLIST_HEAD + 4].copy().view("<u4").reshape(-1), 0).astype(np.uint64)
        nb, nok = self.bulk.gather(node1, O.SPRNODE_SIZE)
        sn1 = np.where(nok, nb[:, O.SPRNODE_OBJ:O.SPRNODE_OBJ + 4].copy().view("<u4").reshape(-1), 0).astype(np.uint64)
        node2 = np.where(nok, nb[:, O.SPRNODE_NEXT:O.SPRNODE_NEXT + 4].copy().view("<u4").reshape(-1), 0).astype(np.uint64)
        if (node2 != 0).any():
            nb2, nok2 = self.bulk.gather(node2, O.SPRNODE_SIZE)
            sn2 = np.where(nok2, nb2[:, O.SPRNODE_OBJ:O.SPRNODE_OBJ + 4].copy().view("<u4").reshape(-1), 0).astype(np.uint64)
        else:
            sn2 = np.zeros(n, np.uint64)
        def parse_snodes(sn):
            sb, sok = self.bulk.gather(sn, O.SPRITENODE_READ_SIZE)
            spr = np.where(sok, sb[:, O.SPRITENODE_SPRITE:O.SPRITENODE_SPRITE + 4].copy().view("<u4").reshape(-1), 0)
            kind = sb[:, O.SPRITENODE_KIND]
            frame = sb[:, O.SPRITENODE_FRAME:O.SPRITENODE_FRAME + 2].copy().view("<i2").reshape(-1)
            frame = np.where(sok & (kind == 2), frame, -1)
            return spr, frame

        spr1, fr1 = parse_snodes(sn1)
        spr2, fr2 = parse_snodes(sn2)
        # id đồ hoạ: cache theo địa chỉ RGE_Sprite, đọc lẻ sprite mới (hiếm)
        need = [int(a) for a in np.unique(np.concatenate([spr1[spr1 != 0], spr2[spr2 != 0]])).tolist() if a not in self._sprite_gid]
        if need:
            sraws = self.bulk.read_many(need, O.SPRITE_READ_SIZE)
            for a in need:
                b = sraws.get(a)
                self._sprite_gid[a] = struct.unpack_from("<h", b, O.SPRITE_GRAPHIC_ID)[0] if b and len(b) >= O.SPRITE_READ_SIZE else -1
        g = self._sprite_gid
        s1 = spr1.tolist(); s2 = spr2.tolist(); f1 = fr1.tolist(); f2 = fr2.tolist()
        for i, u in enumerate(units):
            if s1[i]:
                u.gid, u.frame = g.get(s1[i], -1), f1[i]
            if s2[i]:
                u.gid2, u.frame2 = g.get(s2[i], -1), f2[i]

