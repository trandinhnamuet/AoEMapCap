"""Thông tin trận ghi thêm từ 2026-10-09: thiết lập ván, trạng thái thắng/thua, bản ghi tổng kết 'E' + đuôi file;
tương thích bộ đọc cũ; thư viện trận (bảng chọn) và cửa sổ chọn trận (ẩn, không hiện lên màn hình).

    python tests/test_matchinfo.py
"""
import copy
import glob
import os
import pickle
import struct
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mapcap import offsets as O  # noqa: E402
from mapcap.game import GameReader  # noqa: E402
from mapcap.offline import scan_info  # noqa: E402
from mapcap.rawrec import END_MAGIC, RawReader, RawWriter, read_end, read_header  # noqa: E402
from replay.data import Cursor, ReplayData  # noqa: E402
from replay.library import Library, match_info  # noqa: E402

SNAP = r"D:\Game\AoE-HD\Screenshot\FullMap\2026-09-18_131113_now.snap"


def test_match_settings_parse():
    """GameReader.match_settings đọc đúng các trường từ khối SETTINGS (bộ nhớ giả)."""
    base = 0x1000000
    blk = bytearray(O.SETTINGS_READ_END)

    def put_i32(off, v):
        struct.pack_into("<i", blk, off, v)
    put_i32(O.SETTINGS_RANDOM_GAME, 0); put_i32(O.SETTINGS_RANDOM_MAP, 1)
    put_i32(O.SETTINGS_MAP_TYPE, 5); put_i32(O.SETTINGS_MAP_SIZE, 4); put_i32(O.SETTINGS_RESOURCES, 0)
    put_i32(O.SETTINGS_START_AGE, 1); put_i32(O.SETTINGS_VICTORY, 0)
    blk[O.SETTINGS_REVEAL_MAP] = 0; blk[O.SETTINGS_DEATHMATCH] = 0
    for k, t in enumerate([2, 3, 2, 3]):
        blk[O.SETTINGS_TEAMS + k] = t
        blk[O.SETTINGS_CIVS + k] = 10

    class Mem:
        def read(self, a, n):
            return bytes(blk[a - base:a - base + n])

        def i32(self, a):
            return struct.unpack_from("<i", blk, a - base)[0]

    class Stub:
        mem = Mem()

        def settings(self):
            return base
    info = GameReader.match_settings(Stub(), 0x777, 5)
    assert info["map_type"] == 5 and info["map_size"] == 4 and info["start_age"] == 1, info
    assert info["teams"] == [1, 2, 1, 2] and info["civs"] == [10] * 4 and info["random_map"] == 1, info
    print("match_settings: OK", {k: v for k, v in info.items() if k != "raw"})


def test_def_stats_parse():
    """GameReader.def_stats đọc đúng công/giáp/tầm/tốc độ từ bộ nhớ giả theo offset dịch ngược."""
    base, alist, rlist = 0x2000000, 0x2100000, 0x2200000
    mem_bytes = {}
    d = bytearray(O.UNITDEF_STATS_SIZE)
    d[O.UNITDEF_TYPE] = 70
    struct.pack_into("<h", d, O.UNITDEF_LANG_NAME, 5170)
    struct.pack_into("<h", d, O.UNITDEF_HP, 35)
    struct.pack_into("<f", d, O.UNITDEF_LOS, 7.0)
    struct.pack_into("<f", d, O.UNITDEF_SPEED, 1.2)
    d[O.UNITDEF_BASE_ARMOR] = 0
    struct.pack_into("<h", d, O.UNITDEF_ATTACK_COUNT, 1); struct.pack_into("<I", d, O.UNITDEF_ATTACKS, alist)
    struct.pack_into("<h", d, O.UNITDEF_ARMOR_COUNT, 2); struct.pack_into("<I", d, O.UNITDEF_ARMORS, rlist)
    struct.pack_into("<f", d, O.UNITDEF_MAX_RANGE, 7.0); struct.pack_into("<f", d, O.UNITDEF_RELOAD, 1.4)
    struct.pack_into("<h", d, O.UNITDEF_ACCURACY, 80)
    struct.pack_into("<h", d, O.UNITDEF_DISP_ATTACK, 3); struct.pack_into("<h", d, O.UNITDEF_DISP_MELEE_ARMOR, 0)
    struct.pack_into("<f", d, O.UNITDEF_DISP_RANGE, 7.0); struct.pack_into("<h", d, O.UNITDEF_DISP_PIERCE, 0)
    struct.pack_into("<h", d, O.UNITDEF_TRAIN_TIME, 30)
    struct.pack_into("<3h", d, O.UNITDEF_COSTS, 0, 40, 1); struct.pack_into("<3h", d, O.UNITDEF_COSTS + 6, 3, 20, 1)
    struct.pack_into("<3h", d, O.UNITDEF_COSTS + 12, -1, 0, 0)
    mem_bytes[base] = bytes(d)
    mem_bytes[alist] = struct.pack("<2h", 3, 4) + bytes(124)
    mem_bytes[rlist] = struct.pack("<4h", 4, 1, 3, 2) + bytes(120)

    class Bulk:
        def read_many(self, addrs, size):
            return {a: mem_bytes[a][:size] for a in addrs if a in mem_bytes}

    class Mem:
        def try_read(self, a, n):
            return mem_bytes.get(a, b"")[:n] or None

    class Stub:
        bulk = Bulk()
        mem = Mem()
    st = GameReader.def_stats(Stub(), [base])[base]
    assert st["hp"] == 35 and st["lang"] == 5170 and st["attacks"] == [(3, 4)], st
    assert st["armors"] == [(4, 1), (3, 2)] and st["range"] == 7.0 and st["reload"] == 1.4 and st["d_attack"] == 3, st
    assert st["costs"] == [(0, 40), (3, 20)] and st["train"] == 30 and abs(st["speed"] - 1.2) < 1e-6, st
    print("def_stats: OK", st)
    return st


def make_recording(path):
    snap0 = pickle.load(open(SNAP, "rb"))
    rec_idx = snap0.cur_player_index
    real = [p.index for p in snap0.players if p.index != 0 and (p.addr or p.pid)]
    enemy = next(i for i in real if i != rec_idx)
    wr = RawWriter(path)
    t_wall = time.time()
    for k in range(300):
        s = pickle.loads(pickle.dumps(snap0))
        s.taken_at = t_wall + k / 25.0
        s.time_ms = snap0.time_ms + k * 40
        s.match = {"map_type": 5, "map_size": 4, "teams": [0] * 8, "civs": [10] * 8, "raw": b"\0" * 8}
        for p in s.players:
            p.ptype, p.resigned = 0, 0
            p.civ = 10 if p.index else 0                 # snapshot thử nghiệm cũ chưa có civ
        if k >= 120:                                   # đối thủ đầu hàng ở mẫu 120
            s.players[enemy].ptype, s.players[enemy].resigned = 2, 1
        if k >= 200:                                   # người ghi thắng, hết ván ở mẫu 200
            s.players[rec_idx].ptype = 1
            s.game_over = 1
        trees = [u for u in s.units if u.udef.utype == 90][:40]
        for j, u in enumerate(s.units):
            if u.udef.utype == 70:                     # dân mang gỗ tăng dần
                u.res_type, u.res_amount = 1, float(k % 10)
        for j, t in enumerate(trees):
            t.res_type, t.res_amount = 1, 40.0 - (k // 30)
        s.static_units = trees
        s.static_version = k // 30
        if any(u.udef.utype == 70 for u in s.units) and k < 250:
            s.players[rec_idx].researching = {101: round(k * 0.1, 1)}  # Tool Age đang nghiên cứu ở nhà chính
        else:
            s.players[rec_idx].researching = {}
        if k in (0, 150):                              # chỉ số def (ở mẫu 150: công +2 như vừa nâng cấp)
            s.def_stats = {}
            for u in s.units:
                if u.udef.utype == 70:
                    s.def_stats[u.udef.addr] = {"lang": 5131, "hp": u.udef.hp_max or 25, "los": 4.0, "speed": 1.1,
                                                "armor0": 0, "attacks": [(4, 3 + (2 if k else 0))], "armors": [(3, 1)],
                                                "range": 0.0, "min_range": 0.0, "reload": 1.5, "accuracy": 0,
                                                "d_melee": 0, "d_attack": 3, "d_range": 0.0, "d_reload": 1.5,
                                                "train": 20, "d_pierce": 0, "costs": [(0, 50)]}
        if k == 0:
            wr.start(s)
        else:
            wr.add_frame(s)
    wr.close("stop")
    return rec_idx, enemy


def test_recording(tmp):
    path = os.path.join(tmp, "2026-10-09_000000_tran1.aoerec")
    rec_idx, enemy = make_recording(path)
    hdr = read_header(path)
    assert hdr["format"] == 2 and hdr["match"]["map_type"] == 5, hdr.get("match")
    with open(path, "rb") as f:
        f.seek(-16, 2)
        assert f.read(8) == END_MAGIC
    end = read_end(path)
    assert end["frames"] == 300 and end["reason"] == "stop" and end["game_over"] == 1, end
    assert end["status"][rec_idx] == (1, 0) and end["status"][enemy] == (2, 1), end["status"]
    # bộ đọc cũ: vẫn đọc đủ 300 mẫu, bỏ qua 'E' và đuôi
    n = sum(1 for _ in RawReader(path).frames())
    assert n == 300, n
    times, _ndop, _h = scan_info(path)
    assert len(times) == 300
    # trình xem: trạng thái theo thời điểm
    d = ReplayData(path)
    d.start_index().join()
    assert d.error is None and d.n_frames == 300
    c = Cursor(d)
    for fi, want_enemy, want_rec, go in ((50, 0, 0, 0), (150, 2, 0, 0), (250, 2, 1, 1), (100, 0, 0, 0)):
        c.seek(fi)
        pl = d.players_at(c.state)
        assert pl[enemy].ptype == want_enemy and pl[rec_idx].ptype == want_rec and c.state.go == go, \
            (fi, pl[enemy].ptype, pl[rec_idx].ptype, c.state.go)
    assert pl[enemy].resigned == 0
    c.seek(299)
    assert d.players_at(c.state)[enemy].resigned == 1
    c.seek(100)
    pr = d.players_at(c.state)[rec_idx].researching
    assert pr == {101: 10.0}, pr
    U = c.state.units()
    vill = U[(U["rtype"] == 1) & (U["ramount"] < 20)]          # dân (cây trong danh sách unit có 31..40)
    assert len(vill) and float(vill["ramount"].max()) == 0.0, vill["ramount"][:5]   # mẫu 100: 100 % 10 = 0
    c.seek(105)
    U = c.state.units()
    assert float(U[(U["rtype"] == 1) & (U["ramount"] < 20)]["ramount"].max()) == 5.0
    _si, _v, S = c.statics()
    if len(S):
        assert set(np.round(S["ramount"]).tolist()) <= {40.0, 39.0, 38.0, 37.0, 36.0, 35.0, 34.0, 33.0, 32.0, 31.0}, S["ramount"][:5]
    assert d.stats, "không có bản ghi chỉ số 'U'"
    di = next(iter(d.stats))
    assert d.stats_at(di, 10)["attacks"] == [(4, 3)] and d.stats_at(di, 200)["attacks"] == [(4, 5)], d.stats[di]
    d.close()
    info = match_info(path)
    assert info["result"] == "Thắng" and info["civ_mode"] == "Shang" and info["map"] == "Lục địa · Rất lớn", info
    assert info["duration_ms"] == 299 * 40 + pickle.load(open(SNAP, "rb")).time_ms, info["duration_ms"]
    print("bản ghi mới: OK", {k: info[k] for k in ("recorder", "recorder_civ", "result", "format", "civ_mode", "map")})
    # ghi dở (không có 'E'): cắt bỏ đuôi
    cut = os.path.join(tmp, "2026-10-09_000001_tran1.aoerec")
    data = open(path, "rb").read()
    epos = struct.unpack("<Q", data[-8:])[0]
    open(cut, "wb").write(data[:epos])
    info2 = match_info(cut)
    assert info2["result"] == "Ghi dở" and info2["frames"] == 300, info2
    print("file ghi dở: OK", info2["result"], info2["frames"])
    return path


def test_library(tmp):
    old = time.time() - 3600                           # file sửa trong 10 s gần đây (đang ghi) không được đệm
    for p in glob.glob(os.path.join(tmp, "*.aoerec")):
        os.utime(p, (old, old))
    lib = Library(tmp)
    files = lib.files()
    infos = [lib.info(p) for p in files]
    lib.save()
    assert os.path.exists(os.path.join(tmp, "_matches.json"))
    lib2 = Library(tmp)
    for p in files:
        assert lib2.cached(p) is not None, p
    print("thư viện:", [(i["file"], i.get("result")) for i in infos])


def test_picker(tmp):
    import tkinter as tk
    from replay.picker import PickerWindow
    root = tk.Tk()
    root.withdraw()
    opened = []
    w = PickerWindow(root, tmp, opened.append)
    w.top.withdraw()
    t_end = time.time() + 20
    while time.time() < t_end and "trận." not in w.var_status.get():
        root.update()
        time.sleep(0.05)
    rows = w.tree.get_children()
    assert len(rows) == len(Library(tmp).files()), (len(rows), w.var_status.get())
    w._sort("dur"); w._sort("name"); w._sort("date")
    w.var_find.set("khongcoai")
    root.update()
    assert len(w.tree.get_children()) == 0
    w.var_find.set("")
    root.update()
    w.tree.selection_set(w.tree.get_children()[0])
    w._show_detail()
    assert "Đội" in w.var_detail.get(), w.var_detail.get()
    w._open()
    assert opened and opened[0].endswith(".aoerec")
    print("cửa sổ chọn trận: OK", len(rows), "dòng; chi tiết:", w.var_detail.get()[:90])
    root.destroy()


def main():
    tmp = os.path.join(ROOT, "Video", "_test", "matchinfo")
    os.makedirs(tmp, exist_ok=True)
    for f in glob.glob(os.path.join(tmp, "*")):
        os.remove(f)
    test_match_settings_parse()
    test_def_stats_parse()
    test_recording(tmp)
    # thêm một file cũ thật (nếu có) để thư viện trộn cả hai loại
    olds = sorted(glob.glob(os.path.join(ROOT, "dist", "Video", "Raw", "*.aoerec")), key=os.path.getsize)
    if olds:
        info = match_info(olds[0])
        assert info["result"] == "Không rõ" and not info["new_format"], info
        print("file cũ:", info["file"], info["format"], info["civ_mode"], info["result"])
    test_library(tmp)
    test_picker(tmp)
    print("OK")


if __name__ == "__main__":
    main()
