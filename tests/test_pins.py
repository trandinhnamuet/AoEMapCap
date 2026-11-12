"""Trận ghim (người dùng 12/11): ô tích "★ Trận đã ghim" lọc chỉ trận ghim, dòng ghim có nền ánh vàng + viền vàng
sáng 2 lớp (đi theo khi cuộn), chú thích trên nút ★ Ghim; thư mục lưu ở đầu trang Cài đặt (hàng trên bảng chỉ còn nút
Mở thư mục); hàng nút dưới bảng không bị che ở cửa sổ 980 px.

    python tests/test_pins.py
Ảnh chụp: Video/_test/pins/.
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
os.environ["AOEMAPCAP_UPDATE_URL"] = "http://127.0.0.1:9/version.json"
os.environ["AOEMAPCAP_TELEMETRY"] = "0"
os.environ["AOEMAPCAP_INSTANCE"] = f"AoE-MapCap-test-{os.getpid()}"

import tkinter as tk  # noqa: E402

from mapcap import engine as E  # noqa: E402
from mapcap import gui as G  # noqa: E402
from mapcap.retention import set_keep  # noqa: E402

OUT = os.path.join(ROOT, "Video", "_test", "pins")


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


def shot(root, name):
    try:
        from PIL import ImageGrab
        root.lift()
        root.attributes("-topmost", True)
        pump(root, 0.5)
        x, y = root.winfo_rootx(), root.winfo_rooty()
        ImageGrab.grab((x, y, x + root.winfo_width(), y + root.winfo_height())).save(os.path.join(OUT, name))
        root.attributes("-topmost", False)
    except Exception as e:  # noqa: BLE001
        print("không chụp được:", e)


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    raw = os.path.join(OUT, "Raw")
    os.makedirs(raw)
    srcs = [p for p in sorted(glob.glob(os.path.join(ROOT, "Video", "Raw", "*.aoerec")), key=os.path.getmtime)
            if os.path.getsize(p) < 20e6][-8:]
    assert len(srcs) >= 4, "cần ít nhất 4 trận thật trong Video/Raw"
    paths = []
    for k, p in enumerate(srcs):
        dst = os.path.join(raw, os.path.basename(p))
        shutil.copy(p, dst)
        os.utime(dst, (time.time() - 3600 * (k + 1),) * 2)
        paths.append(os.path.normpath(dst))
    pinned = {paths[1], paths[4 if len(paths) > 4 else 3]}
    for p in pinned:
        set_keep(raw, os.path.basename(p), True)

    cfg = E.Config(out_dir=OUT, auto_start=False)
    E.save_config(cfg)
    G.load_config = lambda: E.load_config(cfg.settings_path())
    G.Engine = FakeEngine
    root = tk.Tk()
    app = G.App(root)
    root.geometry("980x640+40+40")
    try:
        tb = app.table
        t = tb.tree
        until(root, lambda: all(t.exists(p) for p in paths))
        pump(root, 0.5)
        for p in paths:
            assert ("pin" in t.item(p, "tags")) == (p in pinned), (p, t.item(p, "tags"))
            assert t.set(p, "date").startswith("★ ") == (p in pinned)
        vis = [p for p in pinned if t.bbox(p)]
        on = [fr for fr in tb._pin_frames if fr["geom"] is not None]
        assert sorted(fr["iid"] for fr in on) == sorted(vis), (on, vis)
        for fr in on:
            assert all(f.winfo_ismapped() for f in fr["parts"])
            bb = t.bbox(fr["iid"])
            assert fr["geom"][1] == bb[1], (fr["geom"], bb)
        assert all(len(fr["parts"]) == 12 for fr in on)
        print(f"dòng ghim: nền 'pin' + ★, viền 1 px + 2 lớp sáng vào trong quanh {len(on)} dòng đang thấy: OK")
        shot(root, "1_tat_ca.png")

        # cuộn: viền đi theo dòng
        t.yview_moveto(1.0)
        pump(root, 0.4)
        for fr in tb._pin_frames:
            if fr["geom"] is not None:
                assert fr["geom"][1] == t.bbox(fr["iid"])[1]

        # lọc chỉ trận ghim
        tb.var_pinned_only.set(True)
        tb._refill()
        pump(root, 0.4)
        assert sorted(t.get_children()) == sorted(pinned), t.get_children()
        assert sum(fr["geom"] is not None for fr in tb._pin_frames) == len(pinned)
        print("ô ★ Trận đã ghim: chỉ còn", len(pinned), "trận ghim: OK")
        shot(root, "2_chi_tran_ghim.png")

        # bỏ ghim một trận khi đang lọc -> biến khỏi bảng, viền gỡ
        p0 = sorted(pinned)[0]
        t.selection_set(p0)
        app._pin_selected()
        pump(root, 0.4)
        assert tb.var_status.get() == "", tb.var_status.get()
        assert not t.exists(p0) and len(t.get_children()) == len(pinned) - 1
        assert sum(fr["geom"] is not None for fr in tb._pin_frames) == len(pinned) - 1
        tb.var_find.set("khongcoten-xyz")
        pump(root, 0.3)
        assert not t.get_children() and "khớp" in tb.var_status.get(), tb.var_status.get()
        assert all(fr["geom"] is None for fr in tb._pin_frames)
        tb.var_find.set("")
        tb.var_pinned_only.set(False)
        tb._refill()
        pump(root, 0.3)
        assert len(t.get_children()) == len(paths)
        print("bỏ ghim khi đang lọc / tìm không khớp: bảng + viền cập nhật: OK")

        # hàng trên: không còn đường dẫn, có nút Mở thư mục; hàng nút dưới vừa cửa sổ 980 px
        assert not tb.dir_label.winfo_ismapped() and app.btn_open_dir.master is app.btn_pin.master
        st = app.status_lbl
        right = root.winfo_rootx() + root.winfo_width()
        tb.var_status.set("8 trận. Bấm đúp hoặc Enter để xem; chuột phải để xem 2 đội; rất dài rất dài rất dài")
        pump(root, 0.3)
        assert st.winfo_reqwidth() <= st.winfo_width() + 1 and st.cget("text").endswith("…"), (st.cget("text"), st.winfo_width(), st.winfo_reqwidth(), st.winfo_rootx(), right, st.master.winfo_width())
        assert st.winfo_rootx() + st.winfo_width() <= right
        tb.var_status.set("8 trận")
        pump(root, 0.2)
        assert st.cget("text") == "8 trận"
        rw = root.winfo_width()
        right = root.winfo_rootx() + root.winfo_width()
        for w in app.btn_pin.master.winfo_children() + tb.bar.winfo_children():
            if isinstance(w, tk.ttk.Button) or w.winfo_ismapped():
                assert w.winfo_ismapped() and w.winfo_rootx() + w.winfo_width() <= right, (w, w.cget("text"))
                if isinstance(w, tk.ttk.Button):     # không bị co (ttk co nút khi thiếu chỗ thay vì đẩy ra ngoài)
                    assert w.winfo_width() >= w.winfo_reqwidth(), (w.cget("text"), w.winfo_width(), w.winfo_reqwidth())
        # cột Ngày đọc đủ cả khi có "★ "
        from tkinter import font as tkfont
        f = tkfont.Font(font=tk.ttk.Style().lookup("Treeview", "font") or "TkDefaultFont")
        cols = [c[0] for c in __import__("replay.picker", fromlist=["COLUMNS"]).COLUMNS]
        used = sum(t.column(k, "width") for k in cols)
        assert used <= t.winfo_width(), ("cột tràn bảng", used, t.winfo_width(), [t.column(k, "width") for k in cols])
        for p in pinned - {p0}:
            assert f.measure(t.set(p, "date")) + 8 <= t.column("date", "width"), t.column("date", "width")
        print(f"cửa sổ {rw} px: nút hàng dưới / hàng trên không bị che: OK")

        # Cài đặt: thẻ đầu tiên là Thư mục lưu trận
        app.show_page("settings")
        pump(root, 0.5)
        ents = [w for w in tb._descendants(app.pages["settings"]) if isinstance(w, tk.ttk.Entry)
                and str(w.cget("textvariable")) == str(app.var_out)]
        assert len(ents) == 1, ents
        e = ents[0]
        others = [w for w in tb._descendants(app.pages["settings"]) if isinstance(w, (tk.ttk.Spinbox,))]
        assert all(e.winfo_rooty() < w.winfo_rooty() for w in others)
        print("Cài đặt: Thư mục lưu trận ở đầu trang: OK")
        shot(root, "3_cai_dat.png")
    finally:
        if getattr(app, "stop_event", None) is not None:
            app.stop_event.set()
        root.destroy()
    print("OK test_pins")


if __name__ == "__main__":
    main()
