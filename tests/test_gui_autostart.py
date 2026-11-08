"""Mở AoE-MapCap là luôn bật bộ ghi (v34: không còn nút / tuỳ chọn bật tắt ghi - người dùng 09/11, chống dừng ghi giữa
trận để xem bản đồ); không bật khi bản này đã bị chặn vì quá cũ.

    python tests/test_gui_autostart.py

Engine giả (chỉ chờ lệnh dừng): không dò, không đọc game thật. Cấu hình ghi vào Video\_test\gui_autostart.
Hiện cửa sổ AoE-MapCap vài giây.
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

os.environ["AOEMAPCAP_UPDATE_URL"] = "http://127.0.0.1:9/version.json"     # không mạng: không có thanh cập nhật

import tkinter as tk  # noqa: E402

from mapcap import engine as E  # noqa: E402
from mapcap import gui  # noqa: E402

OUT = os.path.join(ROOT, "Video", "_test", "gui_autostart")
STARTED = []


class FakeEngine:
    def __init__(self, cfg, logger, stop_event, status=None, progress=None):
        self.cfg, self.stop_event, self.state, self.current_rec_path = cfg, stop_event, "chờ game", None
        STARTED.append(self)

    def run(self):
        self.stop_event.wait(30)


def make_app(auto):
    cfg = E.Config(out_dir=OUT, auto_start=auto)
    E.save_config(cfg)
    gui.load_config = lambda: E.load_config(cfg.settings_path())
    gui.Engine = FakeEngine
    root = tk.Tk()
    return root, gui.App(root)


def pump(root, seconds):
    t0 = time.time()
    while time.time() - t0 < seconds:
        root.update()
        time.sleep(0.02)


def close(root, app):
    if app.stop_event:
        app.stop_event.set()
    if app.thread:
        app.thread.join(5)
    root.destroy()


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    for auto in (True, False):                             # auto_start cũ (kể cả đã tắt) không còn tác dụng
        STARTED.clear()
        root, app = make_app(auto)
        assert not hasattr(app, "var_auto"), "Cài đặt không còn ô Tự bắt đầu ghi"
        assert gui.schedule_autostart(app, [], delay_ms=50)
        pump(root, 1.0)
        assert len(STARTED) == 1 and app.engine is STARTED[0], f"mở app phải luôn bật bộ ghi (auto_start={auto})"
        app._auto_start()                                  # gọi lại khi đang ghi: không chạy engine thứ hai
        assert len(STARTED) == 1
        close(root, app)
    print("mở app luôn bật bộ ghi (cấu hình cũ tắt tự ghi cũng vậy), không chạy trùng: OK")

    STARTED.clear()
    root, app = make_app(True)
    app.updater.block_win = object()                       # bản đã bị chặn vì quá cũ
    gui.schedule_autostart(app, [], delay_ms=50)
    pump(root, 0.6)
    assert not STARTED, "bản bị chặn không được ghi"
    app.updater.block_win = None
    app._auto_start()
    pump(root, 0.3)
    assert len(STARTED) == 1 and not app.stop_event.is_set()
    app.updater.block_win = object()
    app._on_update_block()                                 # hiện cửa sổ chặn khi đang chờ game -> dừng bộ ghi
    assert app.stop_event.is_set()
    pump(root, 4.0)
    assert len(STARTED) == 1 and app.engine is None, "bị chặn: không tự bật lại"
    assert "ngừng hỗ trợ" in app.chip_sub.cget("text"), app.chip_sub.cget("text")
    close(root, app)
    print("bản bị chặn: không ghi, đang chờ game thì dừng, không tự bật lại, báo cần cập nhật: OK")
    print("OK")


if __name__ == "__main__":
    threading.excepthook = lambda a: None
    main()
