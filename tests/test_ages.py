"""Thời điểm kích / lên đời 2, 3, 4 (bảng trận mở rộng bằng chuột phải).

    python tests/test_ages.py [file.aoerec]

AgeTracker: kích = lần đầu thấy đang nghiên cứu trừ giây đã chạy; không thấy (file cũ) thì suy từ lúc xong trừ thời
gian nghiên cứu. Trận thật: nén lại (recompress) ghi "ages" vào 'E' đúng bằng quét cả file; Library.ages đệm vào
_matches.json (lần sau không quét). Không đụng thư mục trận của người dùng (làm trên bản sao trong Video\\_test).
"""
import glob
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

from mapcap import rawrec  # noqa: E402
from replay import library  # noqa: E402

OUT = os.path.join(ROOT, "Video", "_test", "ages")


def test_tracker():
    tr = rawrec.AgeTracker()
    tr.researching(600_000, 1, {102: 2.5, 15: 10.0})      # Bronze đang chạy 2,5 s lúc 10:00 -> kích 9:57,5
    tr.researching(601_000, 1, {102: 3.5})                 # lần sau không đổi
    tr.finished(737_500, 1, frozenset({101, 102}))
    tr.finished(500_000, 2, frozenset({101}))              # file cũ: chỉ biết lúc xong -> kích = xong - 120 s
    r = tr.result()
    assert r["1"]["3"] == {"click": 597_500, "done": 737_500}, r
    assert r["1"]["2"] == {"click": 737_500 - 120_000, "done": 737_500}, r
    assert r["2"]["2"] == {"click": 380_000, "done": 500_000} and "3" not in r["2"], r
    print("AgeTracker: kích từ danh sách đang nghiên cứu, file cũ suy từ lúc xong: OK")


def test_real(src):
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    t0 = time.time()
    scanned = rawrec.scan_ages(src)
    print(f"quét {os.path.basename(src)}: {time.time() - t0:.1f}s, {len(scanned)} người chơi có lên đời")
    assert scanned, "trận thật phải có người lên đời 2"
    for idx, ages in scanned.items():
        for age, v in ages.items():
            if v["done"] is not None and v["click"] is not None:
                gap = v["done"] - v["click"]
                want = {"2": 120_000, "3": 140_000, "4": 160_000}[age]
                assert abs(gap - want) <= 2_000, (idx, age, v)      # đúng thời gian nghiên cứu của game
    dst = os.path.join(OUT, os.path.basename(src))
    rawrec.recompress(src, dst)
    end = rawrec.read_end(dst)
    if end is not None:
        assert end["ages"] == scanned, "nén lại phải ghi ages vào 'E' đúng bằng quét"
        print("recompress ghi 'ages' vào 'E' khớp quét cả file: OK")
    # Library: lần đầu quét / đọc 'E', đệm vào _matches.json; lần sau lấy từ đệm
    cp = os.path.join(OUT, "copy_" + os.path.basename(src))
    shutil.copy2(src, cp)
    lib = library.Library(OUT)
    for p in lib.files():
        lib.info(p)
    lib.cache[os.path.basename(cp)]["mtime"] = os.stat(cp).st_mtime      # bản sao vừa chép: coi như đã ổn định
    a1 = lib.ages(cp)
    lib.save()
    t0 = time.time()
    lib2 = library.Library(OUT)
    a2 = lib2.ages(cp)
    assert a1 == a2 == scanned and time.time() - t0 < 0.5, "lần sau phải lấy từ _matches.json"
    print("Library.ages đệm trong _matches.json: OK")


if __name__ == "__main__":
    test_tracker()
    src = sys.argv[1] if len(sys.argv) > 1 else None
    if src is None:
        cands = sorted(glob.glob(os.path.join(ROOT, "Video", "Raw", "*.aoerec")), key=os.path.getmtime, reverse=True)
        cands = [c for c in cands if os.path.getsize(c) > 2_000_000]
        src = cands[0] if cands else None
    if src:
        test_real(src)
    else:
        print("bỏ qua phần trận thật: không có file .aoerec")
    print("OK test_ages")
