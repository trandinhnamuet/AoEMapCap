"""Giao diện phát hiện hack + báo cáo (AoE-MapCap, 2026-11-11):
  - ô "Báo âm thanh khi có hack" ở thanh bên (lưu cấu hình, bật lên thì nghe thử);
  - tiến trình ghi báo vi phạm -> nhật ký + chuông (nếu bật) + thẻ cảnh báo góc phải trên, mỗi người chơi một dòng;
  - trận có hack: cột Kết quả "⚠ Có hack" (chữ đỏ), khung mở rộng ghi "⚠ HACK" sau tên;
  - nút "Báo cáo hack" mở hộp thoại, chọn sẵn người app đã phát hiện; gửi tới Worker cục bộ nếu đang chạy.

    python tests/test_hack_ui.py [http://127.0.0.1:8799]

Engine giả, thư mục Video\\_test\\hack_ui (file trận = bản sao trận bot có thêm "hack" ở 'E'), không phát âm thanh thật,
không đụng khởi động cùng Windows thật (tác vụ / khoá Run tên riêng), không gửi thống kê. Ảnh chụp trong thư mục đó.
"""
import glob
import os
import shutil
import struct
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
os.environ["AOEMAPCAP_UPDATE_URL"] = "http://127.0.0.1:9/version.json"
os.environ["AOEMAPCAP_TELEMETRY"] = "0"
os.environ["AOEMAPCAP_INSTANCE"] = f"AoE-MapCap-test-{os.getpid()}"
WORKER = sys.argv[1] if len(sys.argv) > 1 else ""
if WORKER:
    os.environ["AOEMAPCAP_REPORT_URL"] = WORKER + "/v1/report"

import tkinter as tk  # noqa: E402

from mapcap import engine as E  # noqa: E402
from mapcap import gui as G  # noqa: E402
from mapcap import rawrec  # noqa: E402
from mapcap import winstartup as WS  # noqa: E402

WS.LEGACY_KEY = r"Software\AoE-MapCap-test\Run"
WS.TASK = f"AoE-MapCap-test-{os.getpid()}"
OUT = os.path.join(ROOT, "Video", "_test", "hack_ui")
HACK = [{"player": 2, "name": "Nghi Pham", "rule": "L3", "label": "Xoá quân / nhà của người khác", "t": 61000,
         "detail": "xoá vật thể #123 của P1", "count": 3},
        {"player": 2, "name": "Nghi Pham", "rule": "L1", "label": "Điều khiển thú / vật thể Gaia", "t": 95000,
         "detail": "ra lệnh vật thể Gaia #900", "count": 1}]


class FakeEngine:
    def __init__(self, cfg, logger, stop_event, status=None, progress=None, on_hack=None):
        self.cfg, self.stop_event, self.state, self.current_rec_path = cfg, stop_event, "chờ game", None
        self.status, self.on_hack = status, on_hack

    def run(self):
        self.stop_event.wait(60)


def pump(root, s):
    t0 = time.time()
    while time.time() - t0 < s:
        root.update()
        time.sleep(0.02)


def until(root, cond, s=8):
    t0 = time.time()
    while not cond():
        assert time.time() - t0 < s, "hết giờ chờ"
        pump(root, 0.05)


def shot(root, name, win=None):
    try:
        from PIL import ImageGrab
        w = win or root
        w.lift()
        w.attributes("-topmost", True)
        pump(root, 0.5)
        x, y = w.winfo_rootx(), w.winfo_rooty()
        ImageGrab.grab((x, y, x + w.winfo_width(), y + w.winfo_height())).save(os.path.join(OUT, name))
        w.attributes("-topmost", False)
    except Exception as e:  # noqa: BLE001
        print("không chụp được:", e)


def with_hack(src, dst, hack):
    """Bản sao file trận, thêm "hack" vào bản ghi tổng kết 'E' (như bộ ghi mới ghi)."""
    data = open(src, "rb").read()
    assert data[-16:-8] == rawrec.END_MAGIC
    pos = struct.unpack("<Q", data[-8:])[0]
    end = rawrec.read_end(src)
    end = dict(end, hack=hack)
    rec = rawrec._pack(b"E", end)
    open(dst, "wb").write(data[:pos] + rec + rawrec.END_MAGIC + struct.pack("<Q", pos))


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    raw = os.path.join(OUT, "Raw")
    os.makedirs(raw)
    srcs = [p for p in sorted(glob.glob(os.path.join(ROOT, "Video", "Raw", "*.aoerec")), key=os.path.getmtime)
            if rawrec.read_end(p) is not None and os.path.getsize(p) < 20e6][-2:]
    assert len(srcs) == 2, srcs
    hacked = os.path.join(raw, "2026-11-11_100000_tran1.aoerec")
    with_hack(srcs[-1], hacked, HACK)
    shutil.copy(srcs[0], os.path.join(raw, "2026-11-11_090000_tran1.aoerec"))
    assert rawrec.read_end(hacked)["hack"] == HACK

    alarms = []
    G.play_alarm = lambda: alarms.append(time.time())
    cfg = E.Config(out_dir=OUT, auto_start=False)
    E.save_config(cfg)
    G.load_config = lambda: E.load_config(cfg.settings_path())
    G.Engine = FakeEngine
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.25)
    except tk.TclError:
        pass
    app = G.App(root)
    root.geometry("1200x720+40+40")
    pump(root, 0.8)
    try:
        # ---- ô âm thanh ở thanh bên ------------------------------------------------------------------------------
        assert app.hack_cb.cget("text") == "Báo âm thanh khi có hack" and app.var_hack_sound.get()
        assert "lệnh" in app._hack_sound_text() and "BẬT" in app._hack_sound_text()
        app.var_hack_sound.set(False)
        app._hack_sound_toggled()
        assert not E.load_config(cfg.settings_path()).hack_sound and not alarms
        app.var_hack_sound.set(True)
        app._hack_sound_toggled()
        assert E.load_config(cfg.settings_path()).hack_sound and len(alarms) == 1, "bật lại thì nghe thử"
        print("ô 'Báo âm thanh khi có hack': lưu cấu hình, bật lên nghe thử: OK")

        # ---- tiến trình ghi báo vi phạm ---------------------------------------------------------------------------
        app._start()
        until(root, lambda: app.engine is not None)
        app.engine.on_hack(dict(HACK[0], file="tran5.aoerec"))
        app.engine.on_hack({"player": 3, "name": "Ke Gian", "rule": "S2", "label": "Tài nguyên tăng đột biến không rõ nguồn",
                            "t": 300000, "detail": "+5,000 vàng trong 1.0 s", "count": 1, "file": "tran5.aoerec"})
        until(root, lambda: len(app.hack_events) == 2)
        assert len(alarms) == 3, alarms
        assert app.hack_card is not None and app.hack_card.winfo_ismapped()
        assert any("Nghi Pham" in t and "Xoá" in t for t in app.hack_lines) and any("Ke Gian" in t for t in app.hack_lines)
        log = app.txt.get("1.0", "end")
        assert "PHÁT HIỆN HACK: Nghi Pham - Xoá quân / nhà của người khác" in log
        assert app.hack_card.winfo_rootx() + app.hack_card.winfo_width() <= root.winfo_rootx() + root.winfo_width()
        shot(root, "the_canh_bao.png")
        # trận mới: thẻ chỉ còn vi phạm của trận mới; tắt âm thanh thì không kêu
        app.var_hack_sound.set(False)
        app._hack_sound_toggled()
        app.engine.on_hack(dict(HACK[1], file="tran6.aoerec"))
        until(root, lambda: len(app.hack_events) == 1 and app.hack_events[0]["rule"] == "L1")
        assert len(alarms) == 3 and len(app.hack_lines) == 1
        app._hide_hack_card()
        assert app.hack_card is None
        app.var_hack_sound.set(True)
        app._hack_sound_toggled()
        print("vi phạm -> nhật ký + chuông + thẻ góc phải trên (mỗi người một dòng, trận mới làm mới thẻ, tắt tiếng): OK")

        # ---- danh sách trận ----------------------------------------------------------------------------------------
        app.show_page("matches")
        app.table.reload()
        until(root, lambda: hacked in app.table.infos and len(app.table.infos) == 2, 30)
        pump(root, 0.5)
        vals = app.table.tree.item(hacked, "values")
        assert "⚠ Có hack" in vals[3] and "hack" in app.table.tree.item(hacked, "tags"), vals
        other = [p for p in app.table.infos if p != hacked][0]
        assert "hack" not in app.table.tree.item(other, "values")[3].lower()
        shot(root, "danh_sach.png")
        print("trận có hack: cột Kết quả '⚠ Có hack' chữ đỏ, trận khác không: OK")

        # ---- hộp thoại báo cáo -------------------------------------------------------------------------------------
        app.table.tree.selection_set(hacked)
        app.table.tree.focus(hacked)
        pump(root, 0.2)
        dlgs = []
        real = G.ReportDialog
        G.ReportDialog = lambda *a: dlgs.append(real(*a))
        app._report_selected()
        assert dlgs
        d = dlgs[0]
        assert d.var_suspect.get() == "Nghi Pham", d.var_suspect.get()
        d.txt.insert("1.0", "xoá nhà chính của tôi phút 1")
        pump(root, 0.4)
        shot(root, "bao_cao.png", d.top)
        if WORKER:
            d._send()
            until(root, lambda: "Đã gửi" in d.lbl.cget("text") or "Không gửi" in d.lbl.cget("text"), 60)
            assert "Đã gửi báo cáo #" in d.lbl.cget("text"), d.lbl.cget("text")
            shot(root, "bao_cao_da_gui.png", d.top)
            print("gửi báo cáo tới Worker cục bộ: " + d.lbl.cget("text") + ": OK")
        d.top.destroy()
        print("hộp thoại Báo cáo hack: chọn sẵn người app phát hiện, có ghi chú: OK")
    finally:
        if app.stop_event:
            app.stop_event.set()
        if app.thread:
            app.thread.join(5)
        app._stop_tray()
        root.destroy()
    print("OK test_hack_ui")


if __name__ == "__main__":
    main()
