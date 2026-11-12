"""Bảng Trận đã ghi có cột Kích 3 (giữa Map và Thời gian), tên cột Ngày / Thời gian; tab Phím tắt; bảng chỉ số replay
cột Đời / Time, thời đại Đời 1-4 (người dùng 11/11).

    python tests/test_keys_age3.py
Ảnh chụp: Video/_test/keys_age3/.
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
from mapcap import rawrec  # noqa: E402
from replay import picker as P  # noqa: E402
from replay.keys import KEYS_HELP  # noqa: E402

OUT = os.path.join(ROOT, "Video", "_test", "keys_age3")


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


def test_hud_labels():
    from replay import hud as H
    assert [c[0] for c in H.Hud.ECO_COLS[:3]] == ["Đời", "Dân", "Time"], H.Hud.ECO_COLS[:3]
    assert [H.AGE_VI[k] for k in (1, 2, 3, 4)] == ["Đời 1", "Đời 2", "Đời 3", "Đời 4"]
    assert H.Hud.KEYS_HELP is KEYS_HELP
    print("bảng chỉ số replay: cột Đời / Dân / Time, thời đại Đời 1-4: OK")


def main():
    test_hud_labels()
    shutil.rmtree(OUT, ignore_errors=True)
    raw = os.path.join(OUT, "Raw")
    os.makedirs(raw)
    srcs = [p for p in sorted(glob.glob(os.path.join(ROOT, "Video", "Raw", "*.aoerec")), key=os.path.getmtime)
            if os.path.getsize(p) < 20e6 and (rawrec.read_end(p) or {}).get("ages")][-3:]
    assert srcs, "cần trận thật có 'ages' trong 'E'"
    want = {}
    for p in srcs:
        dst = os.path.join(raw, os.path.basename(p))
        shutil.copy(p, dst)
        os.utime(dst, (time.time() - 3600, time.time() - 3600))
        hdr = rawrec.read_header(p)
        a = (rawrec.read_end(p)["ages"].get(str(hdr.get("cur_player_index")), {}).get("3") or {}).get("click")
        want[os.path.normpath(dst)] = P.fmt_clock(a)

    cols = [c[0] for c in P.COLUMNS]
    assert cols.index("age3") == cols.index("kind") + 1 and cols.index("dur") == cols.index("age3") + 1, cols
    cfg = E.Config(out_dir=OUT, auto_start=False)
    E.save_config(cfg)
    G.load_config = lambda: E.load_config(cfg.settings_path())
    G.Engine = FakeEngine
    root = tk.Tk()
    app = G.App(root)
    root.geometry("1200x720+40+40")
    try:
        t = app.table.tree
        assert [t.heading(k, "text") for k in ("date", "age3", "dur")] == ["Ngày", "Kích 3", "Thời gian"]
        until(root, lambda: all(t.exists(p) for p in want))
        got = {p: t.set(p, "age3") for p in want}
        assert got == want, (got, want)
        print("Trận đã ghi: cột Ngày / ... / Map / Kích 3 / Thời gian, Kích 3 =", list(got.values()), ": OK")
        app.table._sort("age3")
        pump(root, 0.3)
        shot(root, "tran_da_ghi.png")

        app.show_page("keys")
        pump(root, 0.5)
        txt = app.keys_text.get("1.0", "end")
        for k, d in KEYS_HELP:
            assert d in txt and k in txt, (k, d)
        assert app.pages["keys"].winfo_ismapped()
        shot(root, "phim_tat.png")
        print(f"tab Phím tắt: {len(KEYS_HELP)} dòng, cùng danh sách bảng Esc trong replay: OK")
    finally:
        if getattr(app, "stop_event", None) is not None:
            app.stop_event.set()
        root.destroy()
    print("OK test_keys_age3")


if __name__ == "__main__":
    main()
