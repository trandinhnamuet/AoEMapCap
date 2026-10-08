"""Kiểm thử BulkReader/ListWalker/read_units_bulk/refresh_units với bộ nhớ giả."""
import struct, sys, time
sys.path.insert(0, r"D:\Game\AoE-MapCap")
from mapcap import offsets as O
from mapcap.fastread import BulkReader, ListWalker
from mapcap.game import GameReader
from mapcap.memory import MemoryError_


class FakeMem:
    """Vùng nhớ giả: dict trang 4 KB -> bytes; đọc qua ranh giới trang thiếu -> lỗi."""

    def __init__(self):
        self.pages = {}

    def _ensure(self, addr, size):
        for pg in range(addr >> 12, ((addr + size - 1) >> 12) + 1):
            self.pages.setdefault(pg, bytearray(4096))

    def write(self, addr, data):
        self._ensure(addr, len(data))
        for i, b in enumerate(data):
            a = addr + i
            self.pages[a >> 12][a & 0xFFF] = b

    def read(self, addr, size):
        out = bytearray()
        a = addr
        while a < addr + size:
            pg = self.pages.get(a >> 12)
            if pg is None:
                raise MemoryError_(f"unmapped {a:#x}")
            n = min(4096 - (a & 0xFFF), addr + size - a)
            out += pg[a & 0xFFF:(a & 0xFFF) + n]
            a += n
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
# unitdef giả tại 0x500000: type byte +4 = 90 (cây), name ptr +8 -> 0, id +0x10 = 140
DEF = 0x500000
d = bytearray(0xA0); d[O.UNITDEF_TYPE] = 90; struct.pack_into("<h", d, O.UNITDEF_ID, 140); mem.write(DEF, bytes(d))
DEF2 = 0x500200
d = bytearray(0xA0); d[O.UNITDEF_TYPE] = 70; struct.pack_into("<h", d, O.UNITDEF_ID, 83); mem.write(DEF2, bytes(d))
# 1500 unit rải trong 3 vùng heap, kèm vài unit nằm ở trang không ánh xạ xen giữa
units = []
base_regions = [0x1000000, 0x1200000, 0x3000000]
for i in range(1500):
    base = base_regions[i % 3] + (i // 3) * 0x180
    u = bytearray(O.UNIT_READ_SIZE)
    struct.pack_into("<iII", u, O.UNIT_ID, 1000 + i, DEF if i % 2 else DEF2, 0x700000)
    struct.pack_into("<fff", u, O.UNIT_POS_X, i % 144 + 0.5, (i * 7) % 144 + 0.5, 0.0)
    struct.pack_into("<f", u, O.UNIT_HP, 50.0); u[O.UNIT_STATUS] = 2; u[O.UNIT_ANGLE] = i % 8
    mem.write(base, bytes(u)); units.append(base)
# danh sách liên kết: header tại 0x800000, node 8 byte tại 0x900000.. (thứ tự xáo trộn)
HDR = 0x800000
import random
random.seed(1)
order = units[:]; random.shuffle(order)
nodes = [0x900000 + k * 16 for k in range(len(order))]
for k, (na, ua) in enumerate(zip(nodes, order)):
    nxt = nodes[k + 1] if k + 1 < len(nodes) else 0
    mem.write(na, struct.pack("<II", ua, nxt))
mem.write(HDR, struct.pack("<II", 0, nodes[0]))
# player giả tại 0x700000 với list A header ptr
PL = 0x700000
mem.write(PL + O.PLAYER_LIST_A, struct.pack("<I", HDR)); mem.write(PL + O.PLAYER_LIST_B, struct.pack("<I", 0))

r = GameReader(mem)
calls = {"n": 0}
orig = mem.try_read
def counting(a, n):
    calls["n"] += 1
    return orig(a, n)
mem.try_read = counting

t0 = time.time()
pairs = r.walker.walk_many([(HDR, 1)])
got = r.read_units_bulk(pairs)
dt1 = time.time() - t0
print(f"lần 1: {len(got)} unit, {calls['n']} lần đọc, {dt1*1000:.1f} ms")
calls["n"] = 0
t0 = time.time()
pairs = r.walker.walk_many([(HDR, 1)])
got2 = r.read_units_bulk(pairs)
print(f"lần 2 (cache node): {len(got2)} unit, {calls['n']} lần đọc, {(time.time()-t0)*1000:.1f} ms")
assert len(got) == 1500 and sorted(u.uid for u in got) == list(range(1000, 2500)), "thiếu unit"
assert all(u.hp == 50.0 and u.status == 2 for u in got)
# chèn một unit mới vào giữa chuỗi -> walker phải đọc lẻ node mới
NEWU = 0x3100000; u = bytearray(O.UNIT_READ_SIZE)
struct.pack_into("<iII", u, O.UNIT_ID, 9999, DEF, PL); struct.pack_into("<f", u, O.UNIT_HP, 1.0); u[O.UNIT_STATUS] = 2
mem.write(NEWU, bytes(u))
NEWN = 0x910000; mem.write(NEWN, struct.pack("<II", NEWU, nodes[1])); mem.write(nodes[0], struct.pack("<II", order[0], NEWN))
pairs = r.walker.walk_many([(HDR, 1)]); got3 = r.read_units_bulk(pairs)
assert len(got3) == 1501 and any(x.uid == 9999 for x in got3), "không thấy unit mới"
print("chèn unit mới: OK")
# refresh_units: đổi HP một cây về 0 và status 3 -> is_dead
tree = next(x for x in got3 if x.udef.utype == 90)
mem.write(tree.addr + O.UNIT_HP, struct.pack("<f", 0.0)); mem.write(tree.addr + O.UNIT_STATUS, bytes([3]))
new_units, changed = r.refresh_units([x for x in got3 if x.udef.utype == 90])
dead = [x for x in new_units if x.is_dead]
print(f"refresh: {len(new_units)} unit, {changed} thay đổi, {len(dead)} đã chết (uid {dead[0].uid if dead else '-'})")
assert changed == 1 and len(dead) == 1 and dead[0].uid == tree.uid
print("TẤT CẢ OK")
