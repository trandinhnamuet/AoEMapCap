"""Mỗi lúc một trình xem replay (replay/single.py, v32): mở trận mới thì trình xem đang mở tự đóng.

    python tests/test_replay_single.py [file.aoerec] [--game-dir=D:\\Game\\AoE-HD]

1) Trong một tiến trình (mutex thuộc luồng nên mỗi luồng như một trình xem): nhận quyền, trình mới đóng trình cũ, hai
   trình mới cùng lúc thì trình sau cùng thắng, trình cũ treo thì trình mới vẫn mở sau thời gian chờ.
2) Hai tiến trình trình xem thật (run_app.py --replay, cửa sổ hiện vài giây): mở trình thứ hai thì trình thứ nhất thoát.
Tên mutex riêng (AOEMAPCAP_REPLAY_INSTANCE) nên không đóng trình xem thật đang mở của người dùng; tiến trình test chỉ
dừng theo PID. Trận được chép vào Video\\_test\\replay_single (nhật ký _replay.log ghi ở đó).
"""
import os
import shutil
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
NAME = f"AoE-MapCap-replay-test-{os.getpid()}"
os.environ["AOEMAPCAP_REPLAY_INSTANCE"] = NAME
os.environ["AOEMAPCAP_TELEMETRY"] = "0"
os.environ["AOEMAPCAP_UPDATE_URL"] = "http://127.0.0.1:9/version.json"

from replay import single as S  # noqa: E402

OUT = os.path.join(ROOT, "Video", "_test", "replay_single")


class FakeViewer(threading.Thread):
    """Một "trình xem" trên luồng riêng: nhận quyền rồi chạy vòng khung hình tới khi should_close (hoặc hết giờ)."""

    def __init__(self, tag, events, ignore_close=False, life=15):
        super().__init__(daemon=True)
        self.tag, self.events, self.ignore, self.life = tag, events, ignore_close, life
        self.slot = None
        self.ready = threading.Event()

    def run(self):
        self.slot = S.take_over(wait_s=2.0 if self.tag.startswith("vội") else 10.0)
        self.events.append((self.tag, "mở", self.slot.owned, self.slot.closed_other))
        self.ready.set()
        t0 = time.monotonic()
        while time.monotonic() - t0 < self.life:
            if not self.ignore and self.slot.should_close():
                break
            time.sleep(1 / 60)
        self.events.append((self.tag, "đóng"))
        self.slot.release()


def unit():
    ev = []
    a = FakeViewer("A", ev)
    a.start()
    assert a.ready.wait(3)
    assert ev[-1] == ("A", "mở", True, False), ev
    time.sleep(0.3)
    assert a.is_alive(), "không có trình mới thì không tự đóng"
    b = FakeViewer("B", ev)
    t0 = time.monotonic()
    b.start()
    assert b.ready.wait(5)
    dt = time.monotonic() - t0
    a.join(2)
    assert not a.is_alive() and ("A", "đóng") in ev and ev.index(("A", "đóng")) < ev.index(("B", "mở", True, True)), ev
    assert dt < 1.0, dt
    time.sleep(0.3)
    assert b.is_alive() and not b.slot.should_close(), "sự kiện đóng phải được tắt sau khi nhận quyền"
    print(f"trình mới đóng trình cũ rồi nhận quyền ({dt * 1000:.0f} ms), trình mới không tự đóng: OK")

    c, d = FakeViewer("C", ev), FakeViewer("D", ev)
    c.start()
    d.start()
    assert c.ready.wait(5) and d.ready.wait(5)
    b.join(2)
    assert not b.is_alive()
    time.sleep(0.5)
    alive = [t for t in (c, d) if t.is_alive()]
    assert len(alive) == 1 and alive[0].slot.owned, ev[-6:]
    print("hai trình mở cùng lúc: chỉ còn một trình (trình sau cùng), không cái nào chờ 10 s: OK")
    last = alive[0]

    hung = FakeViewer("treo", ev, ignore_close=True, life=8)
    hung.start()
    assert hung.ready.wait(12)
    last.join(2)
    assert not last.is_alive() and hung.slot.owned
    late = FakeViewer("vội", ev)
    t0 = time.monotonic()
    late.start()
    assert late.ready.wait(5)
    dt = time.monotonic() - t0
    assert 1.8 <= dt < 3.5 and late.slot.owned is False, (dt, ev[-1])
    assert hung.is_alive(), "trình treo không bị giết"
    print(f"trình cũ không phản hồi: trình mới vẫn mở sau {dt:.1f} s chờ: OK")
    hung.join(10)
    late.join(20)


def end_to_end(rec, game_dir):
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    path = os.path.join(OUT, os.path.basename(rec))
    shutil.copy2(rec, path)
    cmd = [sys.executable, os.path.join(ROOT, "run_app.py"), "--replay", path, f"--game-dir={game_dir}"]
    log = os.path.join(OUT, "_replay.log")
    p1 = subprocess.Popen(cmd)
    p2 = None
    try:
        time.sleep(8)                                   # trình thứ nhất đã mở cửa sổ, đang xem
        assert p1.poll() is None, "trình xem thứ nhất thoát sớm (xem _replay.log)"
        t0 = time.monotonic()
        p2 = subprocess.Popen(cmd)
        while p1.poll() is None and time.monotonic() - t0 < 15:
            time.sleep(0.1)
        dt = time.monotonic() - t0
        assert p1.poll() == 0, f"trình xem thứ nhất không tự đóng (mã {p1.poll()})"
        time.sleep(4)
        assert p2.poll() is None, "trình xem thứ hai phải đang mở"
        txt = open(log, encoding="utf-8").read()
        assert "mở trận khác: đóng trận đang xem" in txt and "đóng trình xem đang mở: xong" in txt, txt[-800:]
        print(f"hai trình xem thật: mở trận thứ hai thì trận thứ nhất đóng sau {dt:.1f} s (thoát bình thường), "
              "trận thứ hai vẫn mở: OK")
    finally:
        for p in (p1, p2):
            if p is not None and p.poll() is None:
                p.terminate()                           # chỉ tiến trình test này mở (theo PID)
                p.wait(10)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    gd = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--game-dir=")), r"D:\Game\AoE-HD")
    rec = args[0] if args else os.path.join(ROOT, "Video", "Raw", "2026-10-07_104005_tran1.aoerec")
    unit()
    end_to_end(rec, gd)
    print("OK test_replay_single")


if __name__ == "__main__":
    main()
