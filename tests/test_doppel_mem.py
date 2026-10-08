"""Kiểm thử đọc doppelganger từ bộ nhớ giả: scan_doppels, _finish_doppels, DoppelTracker, scan_tile_units."""
import struct, sys, time
sys.path.insert(0, r"D:\Game\AoE-MapCap")
import numpy as np
from mapcap import offsets as O
from mapcap.game import GameReader, Snapshot, PlayerInfo
from mapcap.memory import MemoryError_
sys.path.insert(0, r"D:\Game\AoE-MapCap\Video\_test")
import importlib.util
spec = importlib.util.spec_from_file_location("tf", r"D:\Game\AoE-MapCap\tests\test_fastread.py")
# chỉ lấy FakeMem (file test kia chạy test của nó khi import -> tự viết lại FakeMem gọn)


class FakeMem:
    def __init__(self):
        self.pages = {}

    def write(self, addr, data):
        for pg in range(addr >> 12, ((addr + len(data) - 1) >> 12) + 1):
            self.pages.setdefault(pg, bytearray(4096))
        for i, b in enumerate(data):
            a = addr + i
            self.pages[a >> 12][a & 0xFFF] = b

    def read(self, addr, size):
        out = bytearray(); a = addr
        while a < addr + size:
            pg = self.pages.get(a >> 12)
            if pg is None:
                raise MemoryError_(f"unmapped {a:#x}")
            n = min(4096 - (a & 0xFFF), addr + size - a)
            out += pg[a & 0xFFF:(a & 0xFFF) + n]; a += n
        return bytes(out)

    def try_read(self, addr, size):
        try:
            return self.read(addr, size)
        except MemoryError_:
            return None

    def u32(self, a): return struct.unpack("<I", self.read(a, 4))[0]
    def u8(self, a): return self.read(a, 1)[0]
    def i16(self, a): return struct.unpack("<h", self.read(a, 2))[0]
    def cstr(self, a, n=64): return "fake"


mem = FakeMem()
DEF_TC = 0x500000      # unitdef công trình (type 80)
d = bytearray(0xA0); d[O.UNITDEF_TYPE] = 80; struct.pack_into("<h", d, O.UNITDEF_ID, 109); d[O.UNITDEF_FOG_VISIBLE] = 1; mem.write(DEF_TC, bytes(d))
DEF_TREE = 0x500200
d = bytearray(0xA0); d[O.UNITDEF_TYPE] = 90; struct.pack_into("<h", d, O.UNITDEF_ID, 140); mem.write(DEF_TREE, bytes(d))
P1, P2 = 0x700000, 0x701000       # người chơi: ta (index 1, pid 1) và địch (index 2, pid 2)
mem.write(P1 + O.PLAYER_ID, struct.pack("<h", 1)); mem.write(P2 + O.PLAYER_ID, struct.pack("<h", 2))


def unit(addr, uid, defp, owner, x, y, kind=None, status=2):
    u = bytearray(0xB0)
    struct.pack_into("<iII", u, O.UNIT_ID, uid, defp, owner)
    struct.pack_into("<fff", u, O.UNIT_POS_X, x + 0.5, y + 0.5, 0.0)
    struct.pack_into("<f", u, O.UNIT_HP, 100.0); u[O.UNIT_STATUS] = status
    u[O.UNIT_TYPE_BYTE] = kind if kind is not None else mem.u8(defp + O.UNITDEF_TYPE)
    mem.write(addr, bytes(u))


# công trình địch thật tại ô (20, 30); doppel của TA về nó cùng ô; 1 cây tĩnh ở ô (5,5); doppel của ĐỊCH (không lấy)
TC = 0x1000000; unit(TC, 4001, DEF_TC, P2, 20, 30)
DOP = 0x1000400; unit(DOP, 77, DEF_TC, P1, 20, 30, kind=25)
extra = bytearray(0xB0 - 0x60)
struct.pack_into("<I", extra, O.UNIT_DOPPEL_ORIG - 0x60, TC); struct.pack_into("<I", extra, O.UNIT_DOPPEL_ORIG_DEF - 0x60, DEF_TC)
struct.pack_into("<i", extra, O.UNIT_DOPPEL_ORIG_OWNER - 0x60, 2); struct.pack_into("<i", extra, O.UNIT_DOPPEL_ORIG_UID - 0x60, 4001)
mem.write(DOP + 0x60, bytes(extra))
DOP_ENEMY = 0x1000800; unit(DOP_ENEMY, 78, DEF_TC, P2, 20, 30, kind=25); mem.write(DOP_ENEMY + 0x60, bytes(extra))
TREE = 0x1000C00; unit(TREE, 9001, DEF_TREE, 0, 5, 5)
# danh sách ô: header {0, first} tại 0x800000; node {unit, next}
def tile_list(hdr, units):
    nodes = [hdr + 0x100 + k * 8 for k in range(len(units))]
    for k, (na, ua) in enumerate(zip(nodes, units)):
        mem.write(na, struct.pack("<II", ua, nodes[k + 1] if k + 1 < len(nodes) else 0))
    mem.write(hdr, struct.pack("<II", 0, nodes[0]))
tile_list(0x800000, [TC, DOP_ENEMY, DOP])
tile_list(0x801000, [TREE])

h = w = 40
tup = np.zeros((h, w), np.uint32); tup[30, 20] = 0x800000; tup[5, 5] = 0x801000
players = [PlayerInfo(0, 0, 0, "Gaia", 0, 0, 0, 0), PlayerInfo(1, P1, 1, "Ta", 0, 1 << 1, 1 << 9, 0), PlayerInfo(2, P2, 2, "Dich", 0, 1 << 2, 1 << 10, 0)]
def mk(visible_at_tc):
    vis = np.zeros((h, w), np.uint32)
    vis[:, :] = players[1].explored_mask
    if visible_at_tc:
        vis[30, 20] |= players[1].visible_mask
    return Snapshot(taken_at=time.time(), time_ms=0, speed=1.0, map_w=w, map_h=h, terrain=np.zeros((h, w), np.uint8),
                    elevation=np.zeros((h, w), np.uint8), shape=np.zeros((h, w), np.uint8), vis_raw=vis, terrain_colors=[],
                    reveal=False, cur_player_index=1, players=players, tile_units_ptr=tup)

r = GameReader(mem)
# 1) scan_doppels trực tiếp
got = r.scan_doppels(mk(False), [(30, 20), (5, 5)])
assert len(got) == 1, got
g = got[0]
assert g.kind == 25 and g.udef.addr == DEF_TC and g.owner_index == 2 and g.orig_uid == 4001 and g.uid < 0, g
print("scan_doppels: 1 doppel của ta, def/màu của địch, orig_uid 4001 -> OK")
# 2) scan_tile_units: không coi doppel là vật thể tĩnh, nhưng trả về qua doppels=
dops = []
statics = r.scan_tile_units(mk(False), known_uids=set(), doppels=dops)
assert [u.uid for u in statics] == [9001] and len(dops) == 1 and dops[0].addr == DOP, (statics, dops)
print("scan_tile_units: 1 cây tĩnh, 1 doppel (bỏ doppel của địch) -> OK")
# 3) tracker: thấy -> mất tầm nhìn -> quét ô vừa mất -> có doppel; nhìn lại -> huỷ
tr = r.doppels
assert tr.update(mk(True)) == []
out = tr.update(mk(False))
assert len(out) == 1 and out[0].addr == DOP and tr.found_total == 1, out
for _ in range(5):
    out = tr.update(mk(False))
assert len(out) == 1 and tr.found_total == 1
out = tr.update(mk(True))
assert out == [] and tr.count() == 0
print("DoppelTracker: tạo khi mất tầm nhìn, giữ ổn định, huỷ khi nhìn lại -> OK")
# 4) doppel bị game huỷ (status 7) trong khi ô vẫn mù -> refresh loại bỏ
tr.update(mk(False)); tr.update(mk(False))
assert tr.count() == 1
mem.write(DOP + O.UNIT_STATUS, bytes([7])); tr.last_refresh = 0
out = tr.update(mk(False))
assert out == [], out
print("refresh: doppel status>=3 bị loại -> OK")
mem.write(DOP + O.UNIT_STATUS, bytes([2]))
# 5) merge từ quét toàn bộ
tr.reset(); tr.update(mk(False))
tr.merge(dops)
assert tr.count() == 1
print("TẤT CẢ OK")
