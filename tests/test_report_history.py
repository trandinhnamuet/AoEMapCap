"""Báo cáo hack (người dùng 12/11): hộp thoại chọn được trận (mặc định trận đang chọn, đổi trận thì tóm tắt / vi phạm
app thấy / người bị nghi đổi theo); gửi xong lưu lịch sử trên máy (_report_history.json) và trang "Lịch sử báo cáo" hiện
lại (mã, ngày gửi, trận, người bị nghi, ghi chú; xem lại replay; file đã xoá thì mờ, không mở được).
Không gửi gì lên mạng: report.upload được thay bằng hàm giả.

    python tests/test_report_history.py
Ảnh chụp: Video/_test/report_history/.
"""
import glob
import json
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
os.environ["AOEMAPCAP_UPDATE_URL"] = "http://127.0.0.1:9/version.json"
os.environ["AOEMAPCAP_TELEMETRY"] = "0"
os.environ["AOEMAPCAP_REPORT_URL"] = "http://127.0.0.1:9/v1/report"
os.environ["AOEMAPCAP_INSTANCE"] = f"AoE-MapCap-test-{os.getpid()}"

import tkinter as tk  # noqa: E402

from mapcap import engine as E  # noqa: E402
from mapcap import gui as G  # noqa: E402
from mapcap import report  # noqa: E402

OUT = os.path.join(ROOT, "Video", "_test", "report_history")


class FakeEngine:
    def __init__(self, cfg, logger, stop_event, status=None, progress=None, on_hack=None):
        self.cfg, self.stop_event, self.state, self.current_rec_path = cfg, stop_event, "chờ game", None

    def run(self):
        self.stop_event.wait(60)


def pump(root, s):
    t0 = time.time()
    while time.time() - t0 < s:
        root.update()
        time.sleep(0.02)


def until(root, cond, s=60):
    t0 = time.time()
    while not cond():
        assert time.time() - t0 < s, "hết giờ chờ"
        pump(root, 0.1)


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


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    raw = os.path.join(OUT, "Raw")
    os.makedirs(raw)
    srcs = [p for p in sorted(glob.glob(os.path.join(ROOT, "Video", "Raw", "*.aoerec")), key=os.path.getmtime)
            if os.path.getsize(p) < 20e6][-4:]
    assert len(srcs) >= 3, "cần ít nhất 3 trận thật trong Video/Raw"
    paths = []
    for k, p in enumerate(srcs):
        dst = os.path.join(raw, os.path.basename(p))
        shutil.copy(p, dst)
        os.utime(dst, (time.time() - 3600 * (k + 1),) * 2)
        paths.append(os.path.normpath(dst))

    sent = []

    def fake_upload(path, info, suspect="", note="", progress=None, timeout=60):
        size = os.path.getsize(path)
        for k in range(1, 5):
            time.sleep(0.05)
            progress and progress(size * k // 4, size)
        sent.append((path, suspect, note))
        return 40 + len(sent)
    report.upload = fake_upload

    cfg = E.Config(out_dir=OUT, auto_start=False)
    E.save_config(cfg)
    G.load_config = lambda: E.load_config(cfg.settings_path())
    G.Engine = FakeEngine
    root = tk.Tk()
    app = G.App(root)
    root.geometry("1100x680+40+40")
    try:
        t = app.table.tree
        until(root, lambda: all(t.exists(p) for p in paths) and all(
            app.table.infos.get(p, {}).get("players") for p in paths))
        # trận thứ 3: giả như app đã bắt được hack
        app.table.infos[paths[2]]["hack"] = [{"player": 2, "name": app.table.infos[paths[2]]["players"][-1]["name"],
                                              "rule": "L3", "label": "Xoá quân / nhà của người khác", "t": 61000,
                                              "detail": "xoá vật thể #123", "count": 1}]

        # trang Lịch sử báo cáo: trống
        app.show_page("reports")
        pump(root, 0.4)
        assert not app.rep_tree.get_children() and app.rep_empty.winfo_ismapped()
        assert str(app.btn_rep_play.cget("state")) == "disabled"
        shot(root, "1_lich_su_trong.png")
        print("Lịch sử báo cáo khi chưa gửi: bảng trống + lời hướng dẫn: OK")

        # hộp thoại: mặc định trận đang chọn, đổi được trận
        app.show_page("matches")
        t.selection_set(paths[1])
        pump(root, 0.2)
        dlgs = []
        real = G.ReportDialog
        G.ReportDialog = lambda *a: dlgs.append(real(*a))
        app._report_selected()
        d = dlgs[0]
        assert d.path == paths[1], d.path
        assert sorted(p for p, _l in d.choices) == sorted(paths), d.choices
        newest = max(paths, key=lambda p: app.table.infos[p]["created"])
        cr = [app.table.infos[p]["created"] for p, _l in d.choices]
        assert d.choices[0][0] == newest and cr == sorted(cr, reverse=True), "mới nhất trước"
        assert d.var_match.get() == dict(d.choices)[paths[1]]
        assert "không tự phát hiện" in d.lbl_auto.cget("text")
        lab2 = dict(d.choices)[paths[2]]
        assert lab2.startswith("⚠ "), lab2
        d.var_match.set(lab2)
        d._pick_match()
        pump(root, 0.2)
        hacker = app.table.infos[paths[2]]["hack"][0]["name"]
        assert d.path == paths[2] and d.var_suspect.get() == hacker, (d.path, d.var_suspect.get())
        assert "App đã phát hiện" in d.lbl_auto.cget("text") and os.path.basename(paths[2]) not in d.lbl_meta.cget("text")
        names = [pl["name"] for pl in app.table.infos[paths[2]]["players"]
                 if pl["name"] != app.table.infos[paths[2]]["recorder"]]
        assert list(d.cb_suspect.cget("values")) == names + ["Không rõ"]
        d.txt.insert("1.0", "xoá nhà chính\nphút 1")
        shot(root, "2_hop_thoai.png", d.top)
        print("hộp thoại: chọn trận (mặc định trận đang chọn, ⚠ trận app bắt được), đổi trận -> tóm tắt / người bị nghi "
              "đổi theo: OK")

        d._send()
        assert str(d.cb_match.cget("state")) == "disabled"
        until(root, lambda: "Đã gửi" in d.lbl.cget("text"), 20)
        assert sent == [(paths[2], hacker, "xoá nhà chính\nphút 1")], sent
        hist = json.load(open(report.history_path(OUT), encoding="utf-8"))
        assert hist[0]["id"] == 41 and hist[0]["path"] == os.path.abspath(paths[2]) and hist[0]["auto"], hist[0]
        d.top.destroy()

        # gửi thêm trận khác (không chọn trận trong bảng -> trận mới nhất)
        t.selection_remove(t.selection())
        dlgs.clear()
        app._report_selected()
        d = dlgs[0]
        assert d.path == newest
        d.txt.insert("1.0", "nghi map hack")
        d._send()
        until(root, lambda: "Đã gửi" in d.lbl.cget("text"), 20)
        d.top.destroy()
        G.ReportDialog = real

        app.show_page("reports")
        pump(root, 0.4)
        rows = app.rep_tree.get_children()
        assert len(rows) == 2 and not app.rep_empty.winfo_ismapped()
        v0, v1 = (app.rep_tree.item(r, "values") for r in rows)
        assert v0[1] == "#42" and v1[1] == "#41" and v1[4] == hacker and v1[5] == "xoá nhà chính phút 1", (v0, v1)
        app.rep_tree.selection_set(rows[1])
        pump(root, 0.2)
        det = app.var_rep_detail.get()
        assert os.path.basename(paths[2]) in det and "App đã phát hiện" in det, det
        assert str(app.btn_rep_play.cget("state")) == "normal"
        opened = []
        app._launch_replay = opened.append
        app._report_open()
        assert opened == [os.path.abspath(paths[2])], opened
        shot(root, "3_lich_su.png")
        print("Lịch sử báo cáo: 2 trận (mới nhất trước), mã / người bị nghi / ghi chú, Xem replay mở đúng trận: OK")

        # file trận đã xoá: dòng mờ, không mở được
        os.remove(paths[2])
        app.show_page("matches")
        app.show_page("reports")
        pump(root, 0.3)
        rows = app.rep_tree.get_children()
        assert "gone" in app.rep_tree.item(rows[1], "tags")
        app.rep_tree.selection_set(rows[1])
        pump(root, 0.2)
        assert str(app.btn_rep_play.cget("state")) == "disabled" and "không còn" in app.var_rep_detail.get()
        print("file trận đã xoá: dòng mờ, nút Xem replay tắt, có giải thích: OK")
    finally:
        if getattr(app, "stop_event", None) is not None:
            app.stop_event.set()
        root.destroy()
    print("OK test_report_history")


if __name__ == "__main__":
    main()
