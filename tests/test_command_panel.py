"""Bảng lệnh công trình khi xem replay: quân sinh được + công nghệ có thể nghiên cứu, như người chơi thấy.

    python tests/test_command_panel.py

1. GameReader.read_trainable trên bộ nhớ giả (như hàm 0x4F3160 của game: loại >= 70, +0x52 bật, +0x15C = nhà).
2. Ghi 'pav' / 'ptr' vào .aoerec rồi đọc lại đúng ở mọi mẫu, cả khi tua (điểm mốc).
3. Viewer._command_panel với empires.dat thật: nhà BS (Storage Pit) đã nâng Tool Working thì ô 6 là Metal Working;
   file cũ (không có 'pav') suy từ DAT; quân theo nhà và ô.
"""
import os
import pickle
import struct
import sys
import time
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

from mapcap import offsets as O  # noqa: E402
from mapcap.game import GameReader  # noqa: E402

SNAP = r"D:\Game\AoE-HD\Screenshot\FullMap\2026-09-18_131113_now.snap"
OUT = os.path.join(ROOT, "Video", "_test", "command_panel")
HD = r"D:\Game\AoE-HD"


def test_read_trainable():
    P, tab = 0x7000000, 0x7100000
    defs = {0x7200000: (70, 83, 109, 1, 1),        # dân: nhà chính, ô 1, đã mở
            0x7300000: (70, 73, 12, 1, 1),         # Clubman: nhà lính, ô 1, đã mở
            0x7400000: (70, 74, 12, 2, 0),         # Swordsman: chưa mở
            0x7500000: (80, 12, 118, 3, 1),        # công trình (loại 80): dân xây, vẫn tính như game (>= 70)
            0x7600000: (30, 200, -1, 0, 1)}        # loại 30: không phải unit sinh được
    mem = {P + O.PLAYER_UNITDEF_COUNT: struct.pack("<hIh", len(defs) + 1, tab, 0)}   # +0x22 số lượng, +0x24 con trỏ
    ptrs = list(defs) + [0]                        # có cả ô trống (con trỏ 0) như mảng thật
    mem[tab] = struct.pack(f"<{len(ptrs)}I", *ptrs)
    for a, (typ, did, loc, btn, en) in defs.items():
        b = bytearray(O.UNITDEF_BUTTON + 1)
        b[O.UNITDEF_TYPE] = typ
        struct.pack_into("<h", b, O.UNITDEF_ID, did)
        struct.pack_into("<h", b, O.UNITDEF_TRAIN_LOCATION, loc)
        struct.pack_into("<b", b, O.UNITDEF_BUTTON, btn)
        mem[a] = bytes(b)
        mem[a + O.UNITDEF_ENABLED] = bytes([en])

    class Bulk:
        def read_many(self, addrs, size):
            return {x: mem[x][:size] for x in addrs if x in mem}

    class Mem:
        def try_read(self, x, n):
            v = mem.get(x)
            return v[:n] if v is not None and len(v) >= n else None

    stub = SimpleNamespace(bulk=Bulk(), mem=Mem())
    players = [SimpleNamespace(index=0, addr=0, trainable=None), SimpleNamespace(index=1, addr=P, trainable=None)]
    GameReader.read_trainable(stub, players)
    assert players[0].trainable is None
    assert players[1].trainable == frozenset({(83, 109, 1), (73, 12, 1), (12, 118, 3)}), players[1].trainable
    mem[0x7400000 + O.UNITDEF_ENABLED] = b"\x01"          # nâng cấp mở Swordsman
    GameReader.read_trainable(stub, players)
    assert (74, 12, 2) in players[1].trainable
    print("read_trainable (bộ nhớ giả, như hàm 0x4F3160): OK")


def test_record_roundtrip():
    from mapcap.rawrec import RawWriter
    from replay.data import ReplayData
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "cmd.aoerec")
    snap0 = pickle.load(open(SNAP, "rb"))
    idx = next(p.index for p in snap0.players if p.index > 0)
    wr = RawWriter(path)
    t0 = time.time()
    n = 400
    for k in range(n):
        s = pickle.loads(pickle.dumps(snap0))
        s.taken_at, s.time_ms = t0 + k / 25.0, snap0.time_ms + k * 40
        for p in s.players:
            p.available = None
            p.trainable = None
            if p.index == idx:
                p.available = frozenset({46, 40}) if k < 200 else frozenset({51, 43})    # Tool Working -> Metal Working
                if k % 50 == 0:                                                         # đọc 2 s/lần
                    p.trainable = frozenset({(83, 109, 1)}) if k < 300 else frozenset({(83, 109, 1), (73, 12, 1)})
        if k == 0:
            wr.start(s)
        else:
            wr.add_frame(s)
    wr.close("stop")
    d = ReplayData(path)
    d.start_index().join()
    assert d.error is None and d.n_frames == n, (d.error, d.n_frames)
    from replay.data import FrameState
    for fi, av, tr in ((10, {46, 40}, {(83, 109, 1)}), (250, {51, 43}, {(83, 109, 1)}), (399, {51, 43}, {(83, 109, 1), (73, 12, 1)})):
        st = FrameState(d.map_w, d.map_h)
        k = max(x for x in d.keys if x <= fi)                # tua: điểm mốc rồi áp các mẫu sau
        st.restore(d.keys[k])
        for j in range(k + 1, fi + 1):
            st.apply(d.read_frame(j), j)
        pl = d.players_at(st)[idx]
        assert pl.available == frozenset(av) and pl.trainable == frozenset(tr), (fi, pl.available, pl.trainable)
    print("ghi pav/ptr chỉ khi đổi, đọc lại đúng cả khi tua: OK")


def test_command_panel():
    if not os.path.isdir(HD):
        print("bỏ qua bảng lệnh: không có thư mục AoE-HD")
        return
    from mapcap import dat as D, gamefiles
    from replay.viewer import Viewer
    dat = D.load(gamefiles.dat_path(HD))
    D.parse_units_by_scan(dat)

    def make(pl):
        v = SimpleNamespace()
        v.data = SimpleNamespace(players_at=lambda st: [SimpleNamespace(), pl])
        v.cursor = SimpleNamespace(state=None)
        v.world = SimpleNamespace(dat=dat, resolver=SimpleNamespace(_tech_label=lambda r: r.name))
        v.hud = SimpleNamespace(tech_icon=None)
        v._unit_name = lambda dfi, stats: dat.units[dfi.dat_id].name
        v._dat_icon = lambda did, owner: None
        v._prereq_ok = Viewer._prereq_ok
        return v

    def labels(panel):
        return {b: lab for b, (_k, _i, lab, _c) in panel["slots"]}

    # file mới: đúng danh sách game ghi lại (trạng thái 1)
    pl = SimpleNamespace(trainable=frozenset({(83, 109, 1), (73, 12, 1)}), techs=frozenset({101, 102, 39, 46}),
                         researching={}, available=frozenset({51, 40, 41, 42, 47}))
    bs = Viewer._command_panel(make(pl), 103, 1)
    lab = labels(bs)
    assert lab[6] == "Metal Working" and lab[7].startswith("Leather Armor - Soldiers") and lab[10] == "Bronze Shield", lab
    assert bs["note"] is None and all(c for _b, (_k, _i, _l, c) in bs["slots"]), bs   # có giá
    assert labels(Viewer._command_panel(make(pl), 12, 1)) == {1: "Soldier-Inf1"}           # nhà lính: Clubman ô 1
    assert labels(Viewer._command_panel(make(pl), 109, 1))[1] == "Man"
    # file cũ: suy từ DAT — Tool Working xong thì ô 6 là Metal Working (đã lên đời đồ đồng)
    old = SimpleNamespace(trainable=None, available=None, techs=frozenset({101, 102, 39, 74, 75, 46}), researching={})
    p2 = Viewer._command_panel(make(old), 103, 1)
    l2 = labels(p2)
    assert l2[6] == "Metal Working" and l2[7] == "Leather Armor - Soldiers" and p2["note"], (l2, p2["note"])
    old2 = SimpleNamespace(trainable=None, available=None, techs=frozenset({101, 39, 74}), researching={46: 10.0})
    l3 = labels(Viewer._command_panel(make(old2), 103, 1))
    assert 6 not in l3 and l3[7] == "Leather Armor - Soldiers", l3                   # đang nghiên cứu Tool Working
    print("bảng lệnh: nhà BS ô 6 Metal Working sau Tool Working, giáp +2 ô 7/8, nhà lính / nhà chính, file cũ: OK")


if __name__ == "__main__":
    test_read_trainable()
    test_record_roundtrip()
    test_command_panel()
    print("OK")
