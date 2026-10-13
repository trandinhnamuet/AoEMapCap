"""Hai cách xếp file game (AoE-HD gộp / AOE1R data + data2) và dấu nhận dạng bản exe đọc được.

    python tests/test_gamefiles.py [thư mục AoE-HD] [thư mục AOE1R]

Dùng hai bộ cài thật (mặc định D:\\Game\\AoE-HD và D:\\Game\\AOE1R, hoặc bản XArena); thiếu bộ nào thì bỏ qua phần đó.
Chỉ đọc file, không chạy game.
"""
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

from mapcap import gamefiles  # noqa: E402
from mapcap.memory import BUILD_SIGNATURE, check_build  # noqa: E402


def first_dir(*cands):
    for d in cands:
        if d and os.path.isdir(os.path.join(d, "data")):
            return d
    return None


HD = first_dir(sys.argv[1] if len(sys.argv) > 1 else None, r"D:\Game\AoE-HD", r"C:\Program Files\XArena\Game\AoE-HD")
R1 = first_dir(sys.argv[2] if len(sys.argv) > 2 else None, r"D:\Game\AOE1R", r"C:\Program Files\XArena\Game\AOE1R")


class FileMemory:
    """Giả ProcessMemory: đọc theo địa chỉ ảo từ file exe (image base cố định, không ASLR)."""

    def __init__(self, path):
        self.b = open(path, "rb").read()
        b = self.b
        pe = struct.unpack_from("<I", b, 0x3C)[0]
        n = struct.unpack_from("<H", b, pe + 6)[0]
        opt = struct.unpack_from("<H", b, pe + 20)[0]
        self.base = struct.unpack_from("<I", b, pe + 24 + 28)[0]
        self.secs = []
        o = pe + 24 + opt
        for _ in range(n):
            vsz, va, rsz, raw = struct.unpack_from("<IIII", b, o + 8)
            self.secs.append((va, rsz, raw))
            o += 40

    def try_read(self, va, size):
        for sva, rsz, raw in self.secs:
            if self.base + sva <= va < self.base + sva + rsz:
                k = raw + va - self.base - sva
                return self.b[k:k + size]
        return None


def test_layouts():
    if not (HD and R1):
        print("bỏ qua: thiếu bộ cài AoE-HD hoặc AOE1R")
        return
    for d in (HD, R1):
        assert gamefiles.valid_game_dir(d), d
    assert gamefiles.layout_name(HD) == "AoE-HD" and gamefiles.layout_name(R1).startswith("Rise of Rome")
    assert os.path.normcase(gamefiles.dat_path(HD)) == os.path.normcase(os.path.join(HD, "data", "empires.dat"))
    assert os.path.normcase(gamefiles.dat_path(R1)) == os.path.normcase(os.path.join(R1, "data2", "empires.dat"))
    assert all(os.path.getsize(p) >= 1024 for p in gamefiles.drs_paths(HD, "graphics"))      # bỏ data2 64 byte
    assert [os.path.basename(p).lower() for p in gamefiles.drs_paths(R1, "graphics")] == \
        ["graphics.drs", "graphics.drs", "terrain.drs", "border.drs"]
    g_hd, g_r1 = gamefiles.read_group(HD, "graphics"), gamefiles.read_group(R1, "graphics")
    assert set(g_hd) == set(g_r1) and all(g_hd[k] == g_r1[k] for k in g_hd), "đồ hoạ AOE1R gộp phải = graphic.drs HD"
    s_hd, s_r1 = gamefiles.read_group(HD, "sounds"), gamefiles.read_group(R1, "sounds")
    assert len(s_r1) >= 180 and all(s_hd.get(k) == v for k, v in s_r1.items())
    from mapcap import drs
    p_hd, p_r1 = drs.load_palette(HD), drs.load_palette(R1)
    assert len(p_hd) == len(p_r1) == 256 and sum(a != b for a, b in zip(p_hd, p_r1)) <= 10
    print(f"cách xếp file: AoE-HD + AOE1R nhận được, đồ hoạ {len(g_r1)} SLP trùng, âm thanh {len(s_r1)}: OK")


def test_viewer_loads_aoe1r():
    if not R1:
        print("bỏ qua: không có AOE1R")
        return
    from replay.viewer import find_game_dir, valid_game_dir
    from replay.world import load_graphics
    assert valid_game_dir(R1) and find_game_dir({"meta": {"game_dir": R1}}) == R1
    dat, store, palette = load_graphics(R1)
    assert len(dat.graphics) == 941
    n = sum(1 for g in list(dat.graphics.values())[:200] if g.slp_id >= 0 and store.slp(g.slp_id) is not None)
    assert n > 150, n
    print(f"trình xem nạp đồ hoạ từ AOE1R: {len(dat.graphics)} đồ hoạ, {n}/200 SLP mở được: OK")


def test_build_signature():
    exes = []
    for d, names in ((HD, ("EMPIRESX.EXE", "EMPIRESX_HD.EXE", "empires.exe")), (R1, ("Empiresx.exe", "Empiresx_n.exe"))):
        if d:
            exes += [(os.path.join(d, n), True) for n in names if os.path.isfile(os.path.join(d, n))]
    if R1 and os.path.isfile(os.path.join(R1, "Empires.exe")):
        exes.append((os.path.join(R1, "Empires.exe"), False))
    if not exes:
        print("bỏ qua: không có exe game")
        return
    for path, ok in exes:
        hit, total = check_build(FileMemory(path))
        assert total == len(BUILD_SIGNATURE)
        assert (hit == total) if ok else (hit == 0), (path, hit)
    print(f"dấu nhận dạng exe: {sum(ok for _p, ok in exes)} bản đọc được 6/6, "
          f"{sum(not ok for _p, ok in exes)} bản không hỗ trợ 0/6: OK")


def test_missing():
    d = os.path.join(ROOT, "Video", "_test", "gamefiles_empty")
    os.makedirs(os.path.join(d, "data2"), exist_ok=True)
    with open(os.path.join(d, "data2", "graphic.drs"), "wb") as f:
        f.write(b"\0" * 64)                                  # như file rỗng của AoE-HD
    assert not gamefiles.valid_game_dir(d) and not gamefiles.valid_game_dir("") and not gamefiles.valid_game_dir(None)
    assert gamefiles.dat_path(d) is None and gamefiles.drs_paths(d, "graphics") == []
    assert any(c.endswith("AOE1R") for c in gamefiles.GAME_DIR_CANDIDATES)
    print("thư mục thiếu dữ liệu -> không nhận: OK")


if __name__ == "__main__":
    test_layouts()
    test_viewer_loads_aoe1r()
    test_build_signature()
    test_missing()
    print("OK")
