"""Khay hệ thống + một bản duy nhất (mapcap/tray.py, mapcap/instance.py).

    python tests/test_tray.py

Gắn một biểu tượng thật vào khay vài giây (rồi gỡ), mô phỏng bấm chuột bằng tin nhắn; mutex / sự kiện dùng tên riêng
của test (không đụng AoE-MapCap đang chạy). Phần cuối: App bấm X -> ẩn xuống khay, vẫn chạy bộ ghi; mở lại / Thoát.
"""
import os
import shutil
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
os.environ["AOEMAPCAP_UPDATE_URL"] = "http://127.0.0.1:9/version.json"
os.environ["AOEMAPCAP_TELEMETRY"] = "0"
os.environ["AOEMAPCAP_INSTANCE"] = f"AoE-MapCap-test-{os.getpid()}"

from mapcap import instance, tray  # noqa: E402


def wait(cond, s=3.0):
    t0 = time.time()
    while time.time() - t0 < s:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_tray():
    got = []
    t = tray.Tray(os.path.join(ROOT, "assets", "app.ico"), got.append, "AoE-MapCap — thử")
    assert t.start() and t.ok and t.hwnd, "không gắn được biểu tượng vào khay"
    assert all(t.icons.get(k) for k in (None, "armed", "rec")), t.icons
    t.update("AoE-MapCap — Đang ghi trận 00:05", "rec", "Dừng ghi")
    assert t.kind == "rec" and t.toggle_label == "Dừng ghi"
    tray.user32.SendMessageW(t.hwnd, tray.WM_TRAY, 0, tray.WM_LBUTTONUP)     # bấm trái
    assert got == ["open"], got
    tray.user32.SendMessageW(t.hwnd, tray.WM_TRAY, 0, 0x0200)                # rê chuột: không làm gì
    assert got == ["open"]
    t.stop()
    assert not t._thread.is_alive() and t.hwnd is None
    print("khay: gắn / đổi chấm màu + dòng rê chuột / bấm mở / gỡ: OK")


def test_instance():
    a = instance.Instance.acquire()
    assert a, "lần đầu phải nhận được quyền"
    shown = []
    a.watch(lambda: shown.append(1))
    res = {}
    th = threading.Thread(target=lambda: res.setdefault("b", instance.Instance.acquire()))
    th.start()
    th.join()
    assert res["b"] is None, "bản thứ hai không được chạy song song"
    assert instance.signal_show() and wait(lambda: shown), "bản thứ hai mở lên phải hiện cửa sổ bản đang chạy"
    # sau cập nhật: bản mới chờ bản cũ thoát rồi nhận quyền
    th = threading.Thread(target=lambda: res.__setitem__("c", instance.Instance.acquire(wait_s=5)))
    th.start()
    time.sleep(0.4)
    assert "c" not in res
    a.release()
    th.join(6)
    assert res.get("c"), "bản mới phải nhận quyền khi bản cũ thoát"
    res["c"].release()
    assert not instance.signal_show(), "không còn bản nào chạy"
    print("một bản duy nhất: chặn bản thứ hai + báo hiện cửa sổ, chờ bản cũ thoát khi cập nhật: OK")


def test_app_close_to_tray():
    import tkinter as tk

    from mapcap import engine as E
    from mapcap import gui
    out = os.path.join(ROOT, "Video", "_test", "gui_tray")
    shutil.rmtree(out, ignore_errors=True)
    stopped = []

    class FakeEngine:
        def __init__(self, cfg, logger, stop_event, status=None, progress=None):
            self.stop_event, self.state, self.current_rec_path = stop_event, "đang ghi", None

        def run(self):
            self.stop_event.wait(30)
            stopped.append(1)

    cfg = E.Config(out_dir=out, auto_start=False)
    assert cfg.close_to_tray is True, "mặc định bấm X là chạy ngầm"
    E.save_config(cfg)
    gui.load_config = lambda: E.load_config(cfg.settings_path())
    gui.Engine = FakeEngine
    root = tk.Tk()
    app = gui.App(root)

    def pump(s):
        t0 = time.time()
        while time.time() - t0 < s:
            root.update()
            time.sleep(0.02)

    assert app.tray is not None and app.tray.ok
    app._start()
    app.state_text = "đang ghi"
    pump(0.6)
    assert app.tray.kind == "rec" and "Đang ghi trận" in app.tray.tip and app.tray.toggle_label == "Dừng ghi", \
        (app.tray.kind, app.tray.tip)
    app._on_close()                                      # bấm X
    pump(0.3)
    assert root.state() == "withdrawn" and app.thread.is_alive() and not app.stop_event.is_set(), \
        "bấm X: ẩn cửa sổ, vẫn ghi"
    app.tray.on_action("open")                           # bấm biểu tượng ở khay (từ luồng khay)
    pump(0.5)
    assert root.state() == "normal"
    app._on_close()
    pump(0.2)
    app.tray.on_action("toggle")                         # menu khay: Dừng ghi
    pump(0.8)
    assert app.stop_event.is_set() and app.engine is None and stopped
    assert app.tray.kind is None and app.tray.toggle_label == "Bắt đầu ghi"
    app.tray.on_action("toggle")                         # menu khay: Bắt đầu ghi
    pump(0.3)
    assert app.engine is not None and app.thread.is_alive()
    app.engine.state = "chờ game"
    app.q.put(("__status__", "chờ game"))
    pump(0.7)
    assert app.tray.kind == "armed"
    app.var_tray.set(False)                              # tắt trong Cài đặt: bấm X là thoát như cũ
    app._save_settings()
    assert E.load_config(cfg.settings_path()).close_to_tray is False
    destroyed = []
    root.bind("<Destroy>", lambda e: destroyed.append(1) if e.widget is root else None, add="+")
    app._on_close()
    assert destroyed and app.tray._thread is None or not app.tray._thread.is_alive()
    print("App: bấm X ẩn xuống khay vẫn ghi, mở lại, menu bắt đầu/dừng ghi, tắt tuỳ chọn thì thoát: OK")


if __name__ == "__main__":
    test_tray()
    test_instance()
    test_app_close_to_tray()
    print("OK test_tray")
