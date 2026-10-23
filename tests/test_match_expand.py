"""Bảng trận mở rộng (chuột phải): mở nhiều trận cùng lúc, thu gọn từng trận, cuộn chuột khi con trỏ nằm trên khung
mở rộng vẫn cuộn bảng (lỗi người dùng báo 23/10: khung là widget riêng nên Treeview không nhận bánh xe chuột).

    python tests/test_match_expand.py [thư mục chứa .aoerec]

Mặc định Video\\_test\\expand_ui\\Raw (bản sao trận thật); cần >= 15 trận để bảng cuộn được. Hiện cửa sổ vài giây.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

import tkinter as tk  # noqa: E402

from mapcap import theme  # noqa: E402
from replay.picker import SPACER, MatchTable  # noqa: E402

FOLDER = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "Video", "_test", "expand_ui", "Raw")


def main():
    if not os.path.isdir(FOLDER) or len([n for n in os.listdir(FOLDER) if n.endswith(".aoerec")]) < 15:
        print("bỏ qua: cần thư mục có >= 15 trận:", FOLDER)
        return
    root = tk.Tk()
    theme.apply(root)
    root.geometry("1100x520+40+40")
    opened = []
    t = MatchTable(root, FOLDER, on_open=opened.append)
    t.pack(fill="both", expand=True)

    def pump(s):
        t0 = time.time()
        while time.time() - t0 < s:
            root.update()
            time.sleep(0.02)

    t0 = time.time()
    while len(t.tree.get_children()) < 15 and time.time() - t0 < 60:
        pump(0.2)
    kids = t.tree.get_children()
    # tính sẵn giờ kích đời ở nền: mở rộng là có ngay
    t0 = time.time()
    while not (kids[0] in t._ages and kids[2] in t._ages) and time.time() - t0 < 120:
        pump(0.2)
    assert kids[0] in t._ages and kids[2] in t._ages, "giờ kích đời phải được tính sẵn ở nền"
    print(f"tính sẵn giờ kích đời ở nền: {len(t._ages)} trận sau {time.time() - t0:.1f}s")
    t1 = time.perf_counter()
    t.toggle_expand(kids[0])
    root.update()
    t2 = time.perf_counter()
    t.toggle_expand(kids[2])
    pump(1.0)
    print(f"mở rộng một trận: {(t2 - t1) * 1000:.0f} ms")
    assert t2 - t1 < 0.5
    assert set(t.expanded) == {kids[0], kids[2]}, "mở được nhiều trận cùng lúc"
    assert all(SPACER in c for c in t.tree.get_children(kids[0]))
    # bánh xe chuột trên một nhãn trong khung mở rộng
    label = t.expanded[kids[0]]["inner"]                  # khung mở rộng (Canvas)
    top0 = t.tree.yview()[0]
    for _ in range(3):
        label.event_generate("<MouseWheel>", delta=-120)
    pump(0.3)
    top1 = t.tree.yview()[0]
    assert top1 > top0, f"cuộn xuống khi chuột trên khung mở rộng: {top0} -> {top1}"
    label2 = t.expanded[kids[2]]["inner"]
    for _ in range(3):
        label2.event_generate("<MouseWheel>", delta=120)
    pump(0.3)
    assert t.tree.yview()[0] < top1, "cuộn lên"
    print(f"cuộn chuột trên khung mở rộng: {top0:.3f} -> {top1:.3f} -> {t.tree.yview()[0]:.3f}: OK")
    # bấm đúp: chỉ mở replay, không bung / gập dòng
    t.tree.yview_moveto(0)
    pump(0.3)
    import ctypes                          # Tk không giả lập được bấm đúp: bấm chuột thật (cửa sổ đưa lên trên cùng)
    u32 = ctypes.windll.user32
    root.attributes("-topmost", True)
    root.focus_force()
    pump(0.3)
    for k in (kids[1], kids[0]):
        bb = t.tree.bbox(k)
        u32.SetCursorPos(t.tree.winfo_rootx() + bb[0] + 60, t.tree.winfo_rooty() + bb[1] + bb[3] // 2)
        for _ in range(2):
            u32.mouse_event(0x2, 0, 0, 0, 0)
            u32.mouse_event(0x4, 0, 0, 0, 0)
        pump(0.5)
    assert opened == [kids[1], kids[0]], opened
    assert set(t.expanded) == {kids[0], kids[2]}, t.expanded
    assert not t.tree.item(kids[1], "open") and t.tree.item(kids[0], "open")
    assert t.expanded[kids[0]]["geom"] is not None, "khung vẫn hiện sau bấm đúp"
    print("bấm đúp: mở replay, không bung / gập: OK")
    t.toggle_expand(kids[0])
    pump(0.2)
    assert set(t.expanded) == {kids[2]} and not t.tree.get_children(kids[0])
    t.toggle_expand(kids[2])
    assert not t.expanded
    print("thu gọn từng trận: OK")
    t.stop()
    root.destroy()
    print("OK test_match_expand")


if __name__ == "__main__":
    main()
