"""Tự dọn trận cũ (mapcap/retention.py, v19) + dòng thông báo trên trang Trận đã ghi.

    python tests/test_retention.py

Phần logic: thư mục tạm với file giả, giờ sửa đặt lùi; "1 GB" thu nhỏ còn 1 KB (retention.GB) để file nhỏ.
Phần giao diện: app thật với cấu hình + thư mục riêng (Video\\_test\\retention), mutex riêng, không gửi thống kê,
không hỏi cập nhật; hàm Thùng rác thay bằng xoá thường (không đổ file test vào Thùng rác của máy).
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
os.environ["AOEMAPCAP_UPDATE_URL"] = "http://127.0.0.1:9/version.json"
os.environ["AOEMAPCAP_TELEMETRY"] = "0"
os.environ["AOEMAPCAP_INSTANCE"] = f"AoE-MapCap-test-{os.getpid()}"

from mapcap import retention as RT  # noqa: E402

OUT = os.path.join(ROOT, "Video", "_test", "retention")
DAY = 86400


def make(raw, name, size, age_days):
    p = os.path.join(raw, name)
    with open(p, "wb") as f:
        f.write(b"x" * size)
    t = time.time() - age_days * DAY
    os.utime(p, (t, t))
    return p


def fake_delete(path):
    os.remove(path)
    return True, ""


def setup(raw):
    shutil.rmtree(os.path.dirname(raw), ignore_errors=True)
    os.makedirs(raw)
    web = RT.web_cache_dir(raw)
    os.makedirs(web)
    # 4 trận cũ (40-37 ngày) + 2 trận mới, mỗi trận 300 byte; tổng 1800 byte
    names = []
    for k, age in enumerate((40, 39, 38, 37, 2, 1)):
        names.append(os.path.basename(make(raw, f"2026-09-{10 + k:02d}_tran{k}.aoerec", 300, age)))
    open(os.path.join(web, os.path.splitext(names[1])[0] + ".v2.aoeweb"), "wb").write(b"w")   # đi cùng trận 1
    w = os.path.join(web, "khong_con_tran.v2.aoeweb")                                          # trận gốc đã mất
    open(w, "wb").write(b"w")
    return names


def logic():
    raw = os.path.join(OUT, "logic", "Raw")
    names = setup(raw)
    RT.GB = 1024
    # dưới ngưỡng: giữ hết dù cũ
    todo, total, after = RT.plan(raw, 2000, 30)
    assert todo == [] and total == 1800, (todo, total)
    # vượt ngưỡng 1000: bỏ cũ nhất trước tới khi <= 1000 (3 trận), trận mới không đụng
    todo, total, after = RT.plan(raw, 1000, 30)
    assert [os.path.basename(p) for p, _ in todo] == names[:3] and after == 900, (todo, after)
    # ghim trận cũ nhất: bỏ qua, lấy trận kế; thời hạn 38 ngày: chỉ trận cũ hơn 38 ngày
    RT.set_keep(raw, names[0], True)
    todo, _t, after = RT.plan(raw, 1000, 30)
    assert [os.path.basename(p) for p, _ in todo] == names[1:4] and after == 900, todo
    todo, _t, _a = RT.plan(raw, 1000, 38.5)
    assert [os.path.basename(p) for p, _ in todo] == names[1:2], todo
    # trận đang ghi: không dọn
    busy = os.path.join(raw, names[1])
    todo, _t, _a = RT.plan(raw, 1000, 30, busy=lambda p: os.path.normcase(p) == os.path.normcase(busy))
    assert names[1] not in [os.path.basename(p) for p, _ in todo]
    # chạy: xoá 3 trận + bản điện thoại đi cùng + bản điện thoại mồ côi
    lines = []
    res = RT.run(raw, 1000, 30, log=lines.append, delete=fake_delete)
    assert res["deleted"] == names[1:4] and res["freed"] == 900 and res["web"] == 1, res
    left = sorted(os.listdir(raw))
    assert left == sorted([names[0], names[4], names[5], RT.KEEP_FILE]), left
    assert os.listdir(RT.web_cache_dir(raw)) == [], os.listdir(RT.web_cache_dir(raw))
    assert any("đã chuyển 3 trận" in s for s in lines), lines
    st = RT.status(raw, 1000, 30)
    assert st["count"] == 3 and st["bytes"] == 900 and st["plan"] == [] and st["keep"] == 1, st
    assert st["free"] and st["free"] > 0
    RT.GB = 1 << 30
    assert RT.fmt_size(int(1.94 * (1 << 30))) == "1,9 GB" and RT.fmt_size(350 << 20) == "350 MB"
    print("logic: dưới ngưỡng giữ hết, vượt ngưỡng bỏ cũ nhất tới khi về dưới, thời hạn, ghim, trận đang ghi, "
          "bản điện thoại đi cùng / mồ côi: OK")


def gui():
    import tkinter as tk

    from mapcap import engine as E
    from mapcap import gui as G
    out = os.path.join(OUT, "gui")
    raw = os.path.join(out, "Raw")
    names = setup(raw)
    RT.GB = 1024
    RT.send_to_recycle_bin = fake_delete
    RT.set_keep(raw, names[0], True)
    cfg = E.Config(out_dir=out, auto_start=False)
    assert cfg.auto_clean and cfg.clean_limit_gb == 5.0 and cfg.clean_days == 30 and not cfg.clean_agreed
    cfg.clean_limit_gb = 1.0                     # 1 "GB" = 1 KB trong test
    E.save_config(cfg)
    G.load_config = lambda: E.load_config(cfg.settings_path())

    def pump(root, s):
        t0 = time.time()
        while time.time() - t0 < s:
            root.update()
            time.sleep(0.02)

    def until(root, cond, s=10):
        t0 = time.time()
        while not cond():
            assert time.time() - t0 < s, "hết giờ chờ"
            pump(root, 0.1)

    root = tk.Tk()
    app = G.App(root)
    pump(root, 0.3)
    app._clean_check()
    until(root, lambda: app._clean_st is not None)
    pump(root, 0.3)
    txt = app.clean_msg.cget("text")
    assert "sẽ chuyển 3 trận" in txt and app.clean_btns.winfo_ismapped(), txt
    assert len([n for n in os.listdir(raw) if n.endswith(".aoerec")]) == 6, "chưa đồng ý thì chưa dọn"
    try:
        from PIL import ImageGrab
        root.lift()
        root.attributes("-topmost", True)
        pump(root, 0.5)
        x, y = root.winfo_rootx(), root.winfo_rooty()
        ImageGrab.grab((x, y, x + root.winfo_width(), y + root.winfo_height())).save(os.path.join(out, "hoi.png"))
        root.attributes("-topmost", False)
    except Exception as e:  # noqa: BLE001
        print("không chụp được:", e)
    print("lần đầu: dòng thông báo hỏi (sẽ chuyển 3 trận ...), chưa xoá gì: OK")

    app._clean_agree()
    until(root, lambda: not app._clean_busy and "Vừa dọn" in app.clean_msg.cget("text"))
    left = sorted(n for n in os.listdir(raw) if n.endswith(".aoerec"))
    assert left == sorted([names[0], names[4], names[5]]), left
    assert E.load_config(cfg.settings_path()).clean_agreed
    assert not app.clean_btns.winfo_ismapped()
    log = app.txt.get("1.0", "end")
    assert "đã chuyển 3 trận" in log, log[-500:]
    print("Đồng ý dọn: chuyển 3 trận cũ nhất (giữ trận ghim ★ + trận mới), ghi Nhật ký, lần sau tự dọn không hỏi: OK")

    # ghim từ bảng: dấu ★
    pump(root, 1.0)
    p = os.path.normpath(os.path.join(raw, names[4]))
    until(root, lambda: app.table.tree.exists(p))
    app.table.tree.selection_set(p)
    app._pin_selected()
    pump(root, 0.3)
    assert str(app.table.tree.item(p, "values")[0]).startswith("★"), app.table.tree.item(p, "values")
    assert names[4] in RT.load_keep(raw)
    print("ghim trận trong bảng: dấu ★, lưu _keep.json: OK")

    # tắt ngay trên dòng thông báo
    app.var_clean.set(False)
    app._clean_toggled()
    until(root, lambda: not app._clean_busy and app.clean_msg.cget("text").startswith("TẮT"))
    assert E.load_config(cfg.settings_path()).auto_clean is False
    print("tắt tự dọn ngay trên dòng thông báo (lưu cấu hình): OK")

    # ổ đĩa sắp đầy
    RT.LOW_DISK_BYTES = 1 << 60
    app._clean_check()
    until(root, lambda: not app._clean_busy and app.disk_msg.winfo_ismapped())
    assert "sắp đầy" in app.disk_msg.cget("text") and "sắp đầy" in app.txt.get("1.0", "end")
    try:
        from PIL import ImageGrab
        root.lift()
        root.attributes("-topmost", True)
        pump(root, 0.5)
        x, y = root.winfo_rootx(), root.winfo_rooty()
        ImageGrab.grab((x, y, x + root.winfo_width(), y + root.winfo_height())).save(os.path.join(out, "o_day.png"))
        root.attributes("-topmost", False)
    except Exception as e:  # noqa: BLE001
        print("không chụp được:", e)
    print("ổ đĩa sắp đầy: cảnh báo đỏ trên trang + Nhật ký: OK")

    # Cài đặt: ngưỡng / thời hạn lưu được
    app.show_page("settings")
    try:
        from PIL import ImageGrab
        root.lift()
        root.attributes("-topmost", True)
        pump(root, 0.5)
        x, y = root.winfo_rootx(), root.winfo_rooty()
        ImageGrab.grab((x, y, x + root.winfo_width(), y + root.winfo_height())).save(os.path.join(out, "cai_dat.png"))
        cv = app.pages["settings"].winfo_children()[0]
        cv.yview_moveto(1.0)
        pump(root, 0.3)
        ImageGrab.grab((x, y, x + root.winfo_width(), y + root.winfo_height())).save(os.path.join(out, "cai_dat2.png"))
        root.attributes("-topmost", False)
    except Exception as e:  # noqa: BLE001
        print("không chụp được:", e)
    app.var_clean_limit.set(7)
    app.var_clean_days.set(14)
    app.var_clean.set(True)
    app._save_settings()
    c2 = E.load_config(cfg.settings_path())
    assert (c2.clean_limit_gb, c2.clean_days, c2.auto_clean) == (7.0, 14, True), (c2.clean_limit_gb, c2.clean_days)
    print("Cài đặt: bật / tắt, ngưỡng GB, số ngày lưu được: OK")
    app._quit()


if __name__ == "__main__":
    logic()
    gui()
    print("OK test_retention")
