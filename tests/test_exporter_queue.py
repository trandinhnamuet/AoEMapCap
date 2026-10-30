"""Hàng đợi chuyển trận cho điện thoại (mobile_server.Exporter, v18), bằng bộ chuyển giả (không cần trận thật):

- trận được hỏi gần nhất làm trước; trận không ai hỏi nữa bị bỏ giữa chừng khi có trận khác chờ (trước v18: trận chọn
  sau đứng ở 0% tới khi mọi trận chọn trước chuyển xong);
- trận khác đang chuyển: báo "ahead"; đang ghi trận: báo "waiting", trận đang chuyển tạm dừng;
- chuyển sẵn trận mới nhất lúc rảnh, bỏ khi có trận được hỏi hoặc bắt đầu ghi trận;
- tắt máy chủ: dừng trận đang chuyển dở.

    python tests/test_exporter_queue.py
"""
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

from mapcap import mobile_server as MS  # noqa: E402

STEPS, STEP_S = 40, 0.05                       # một trận giả: 2 s
runs = []                                      # (tên, "xong" | "bỏ")


def fake_export(src, out, game_dir, log=None, progress=None):
    name = os.path.basename(src)
    try:
        for i in range(STEPS):
            progress(i / STEPS)
            time.sleep(STEP_S)
    except BaseException:
        runs.append((name, "bỏ"))
        raise
    with open(out, "wb") as f:
        f.write(b"x")
    runs.append((name, "xong"))


def wait(cond, s=10, what=""):
    t0 = time.time()
    while not cond():
        if time.time() - t0 > s:
            raise AssertionError("hết giờ chờ: " + what)
        time.sleep(0.05)


def main():
    MS.export_match = fake_export
    base = os.path.join(ROOT, "Video", "_test", "exporter_queue")
    shutil.rmtree(base, ignore_errors=True)
    raw, cache = os.path.join(base, "Raw"), os.path.join(base, "Web")
    os.makedirs(raw)
    old = time.time() - 3600
    for k, n in enumerate(("a.aoerec", "b.aoerec", "c.aoerec")):
        p = os.path.join(raw, n)
        open(p, "wb").close()
        os.utime(p, (old + k, old + k))            # c mới nhất

    # 1. chọn a, quay ra chọn b: a bị bỏ khi không ai hỏi, b làm ngay
    busy = [False]
    ex = MS.Exporter(raw, cache, "", lambda m: None, busy=lambda: busy[0])
    ex.STALE = 0.5
    ex.request("a.aoerec")
    wait(lambda: ex.cur == "a.aoerec", what="bắt đầu a")
    t0 = time.time()
    st = ex.request("b.aoerec")
    assert st["ahead"] and not st["waiting"], st
    while not ex.ready("b.aoerec"):
        ex.request("b.aoerec")                     # điện thoại hỏi lại mỗi lúc
        time.sleep(0.1)
        assert time.time() - t0 < 6, "b phải xong mà không chờ a"
    assert ("a.aoerec", "bỏ") in runs and not ex.ready("a.aoerec"), runs
    print(f"bỏ trận không ai chờ, trận mới chọn xong sau {time.time() - t0:.1f} s: OK")

    # 2. đang ghi trận: báo chờ, trận đang chuyển tạm dừng rồi chạy tiếp khi hết trận
    ex.request("a.aoerec")
    wait(lambda: ex.cur == "a.aoerec" and ex.state["a.aoerec"]["progress"] > 0.2, what="a chạy")
    busy[0] = True
    time.sleep(0.3)
    st = ex.request("a.aoerec")
    p1 = st["progress"]
    time.sleep(1.0)
    st = ex.request("a.aoerec")
    assert st["waiting"] and st["progress"] == p1, (st, p1)
    assert ex.request("c.aoerec")["waiting"], "trận khác cũng phải báo đang ghi trận"
    busy[0] = False
    ex.state.pop("c.aoerec", None)
    while not ex.ready("a.aoerec"):
        ex.request("a.aoerec")
        time.sleep(0.1)
    print("đang ghi trận: báo chờ, tạm dừng, hết trận chạy tiếp: OK")
    ex.stop()

    # 3. chuyển sẵn trận mới nhất lúc rảnh; dừng khi bắt đầu ghi; dừng khi có trận được hỏi
    for n in os.listdir(cache):
        os.remove(os.path.join(cache, n))
    runs.clear()
    MS.Exporter.PREFETCH_EVERY = 0.2               # luồng đọc giá trị này ngay khi tạo
    ex = MS.Exporter(raw, cache, "", lambda m: None, busy=lambda: busy[0], prefetch=True)
    wait(lambda: ex.cur == "c.aoerec", what="chuyển sẵn c")
    busy[0] = True
    wait(lambda: ("c.aoerec", "bỏ") in runs, what="bỏ chuyển sẵn khi ghi trận")
    time.sleep(0.6)
    assert ex.cur is None, "đang ghi trận: không chuyển sẵn"
    busy[0] = False
    wait(lambda: ex.cur == "c.aoerec", what="chuyển sẵn lại c")
    runs.clear()
    ex.request("a.aoerec")
    wait(lambda: ex.cur == "a.aoerec", s=3, what="a chen trước c")
    assert runs == [("c.aoerec", "bỏ")], runs
    while not ex.ready("a.aoerec"):
        ex.request("a.aoerec")
        time.sleep(0.1)
    wait(lambda: ex.ready("c.aoerec"), what="chuyển sẵn c sau a")
    print("chuyển sẵn trận mới nhất lúc rảnh, nhường trận được hỏi / lúc ghi trận: OK")

    # 4. tắt máy chủ giữa chừng: dừng chuyển
    runs.clear()
    ex.request("b.aoerec")
    wait(lambda: ex.cur == "b.aoerec", what="b chạy")
    ex.stop()
    wait(lambda: ("b.aoerec", "bỏ") in runs, s=3, what="tắt thì dừng chuyển")
    assert not ex.ready("b.aoerec"), runs
    print("tắt máy chủ: dừng trận đang chuyển: OK")
    print("OK test_exporter_queue")


if __name__ == "__main__":
    main()
