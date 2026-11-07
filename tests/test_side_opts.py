"""Thanh bên AoE-MapCap (v30): ô Khởi động cùng Windows + ô Tự dọn trận cũ ngay trên thẻ Trạng thái, biểu tượng (i)
sau chữ (rê chuột đọc giải thích); trạng thái bộ ghi bật ngoài trận là "Đang ghi" + "sẽ tự ghi khi vào trận, ngoài trận
nhẹ như Vietkey".

    python tests/test_side_opts.py

Không đụng khởi động thật của Windows: winstartup.KEY trỏ sang khoá thử HKCU\\Software\\AoE-MapCap-test\\Run (xoá khi
xong). Engine giả (không dò / đọc game), cấu hình + ảnh chụp ở Video\\_test\\side_opts, mutex riêng, không gửi thống kê.
"""
import os
import shutil
import sys
import threading
import time
import winreg

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
from mapcap import winstartup as WS  # noqa: E402

OUT = os.path.join(ROOT, "Video", "_test", "side_opts")
TEST_KEY = r"Software\AoE-MapCap-test\Run"
REAL_KEY = WS.KEY
WS.KEY = TEST_KEY


class FakeEngine:
    def __init__(self, cfg, logger, stop_event, status=None, progress=None):
        self.cfg, self.stop_event, self.state, self.current_rec_path = cfg, stop_event, "chờ game", None
        self.status = status

    def run(self):
        if self.status:
            self.status("chờ game")
        self.stop_event.wait(30)


def pump(root, s):
    t0 = time.time()
    while time.time() - t0 < s:
        root.update()
        time.sleep(0.02)


def until(root, cond, s=5):
    t0 = time.time()
    while not cond():
        assert time.time() - t0 < s, "hết giờ chờ"
        pump(root, 0.05)


def tip_text(tip):
    return tip.win.winfo_children()[0].winfo_children()[0].cget("text")


def shot(root, app, name, tips=()):
    try:
        from PIL import ImageGrab
        root.lift()
        root.attributes("-topmost", True)
        for t in tips:
            if t.win is not None:
                t.win.attributes("-topmost", False)
                t.win.attributes("-topmost", True)
                t.win.lift()
        pump(root, 0.5)
        x, y = root.winfo_rootx(), root.winfo_rooty()
        ImageGrab.grab((x, y, x + root.winfo_width(), y + root.winfo_height())).save(os.path.join(OUT, name))
        root.attributes("-topmost", False)
    except Exception as e:  # noqa: BLE001
        print("không chụp được:", e)


def make_app():
    cfg = E.Config(out_dir=OUT, auto_start=False)
    if os.path.isfile(cfg.settings_path()):
        cfg = E.load_config(cfg.settings_path())
    E.save_config(cfg)
    G.load_config = lambda: E.load_config(cfg.settings_path())
    G.Engine = FakeEngine
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.25)                # như gui.main()
    except tk.TclError:
        pass
    app = G.App(root)
    root.geometry("1200x720+40+40")
    pump(root, 0.6)
    return root, app, cfg


def close(root, app):
    if app.stop_event:
        app.stop_event.set()
    if app.thread:
        app.thread.join(5)
    app._stop_tray()
    root.destroy()


def clear_test_key():
    for k in (TEST_KEY, r"Software\AoE-MapCap-test"):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, k)
        except OSError:
            pass


def main():
    assert REAL_KEY == r"Software\Microsoft\Windows\CurrentVersion\Run"
    real_before = None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REAL_KEY) as k:
            real_before = winreg.QueryValueEx(k, WS.NAME)[0]
    except OSError:
        pass
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    clear_test_key()
    try:
        run(real_before)
    finally:
        clear_test_key()


def run(real_before):
    # ---- "nhẹ như Vietkey": dò game lúc chờ (2 s một lần) phải rẻ ---------------------------------------------------
    import psutil
    from mapcap import memory as M
    t = time.process_time()
    for _ in range(20):
        M.find_game_process()
    per = (time.process_time() - t) / 20
    assert per < 0.05, f"dò game tốn {per:.3f} s CPU mỗi lượt (trước v30 ~1 s: ~40% một nhân lúc chờ game)"
    snap = dict(M.process_names())
    ps = {p.pid: p.info["name"] for p in psutil.process_iter(["name"])}
    same = [pid for pid in set(snap) & set(ps) if pid > 4 and snap[pid] == ps[pid]]
    assert len(same) >= 0.95 * len(ps), (len(same), len(ps))
    assert M._is_game_name("EMPIRESX.EXE") and M._is_game_name("Empiresx_HD.exe") and M._is_game_name("empires.exe")
    assert not M._is_game_name("EmpiresSetup.exe") and not M._is_game_name("AoE-MapCap.exe")
    print(f"dò game lúc chờ: {per * 1000:.1f} ms CPU mỗi lượt (2 s một lần), tên tiến trình khớp psutil: OK")

    # ---- winstartup: dòng lệnh đúng exe / run_app.py + --tray --autostart -------------------------------------------
    cmd = WS.command()
    assert cmd.endswith("--tray --autostart") and "run_app.py" in cmd, cmd
    old_frozen, old_exe = getattr(sys, "frozen", None), sys.executable
    sys.frozen, sys.executable = True, r"C:\Program Files\AoE MapCap\AoE-MapCap.exe"
    try:
        assert WS.command() == r'"C:\Program Files\AoE MapCap\AoE-MapCap.exe" --tray --autostart', WS.command()
    finally:
        sys.executable = old_exe
        if old_frozen is None:
            del sys.frozen
    assert not WS.is_enabled()
    assert WS.set_enabled(True) and WS.get() == cmd
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, TEST_KEY, 0, winreg.KEY_SET_VALUE) as k:   # app bị chuyển chỗ
        winreg.SetValueEx(k, WS.NAME, 0, winreg.REG_SZ, r'"D:\cu\AoE-MapCap.exe" --tray --autostart')
    assert WS.refresh() and WS.get() == cmd and not WS.refresh()
    assert not WS.set_enabled(False) and WS.get() is None
    WS.set_enabled(False)                                   # tắt khi đã tắt: không lỗi
    print("winstartup: dòng lệnh exe / mã nguồn, bật / tắt, sửa đường dẫn khi app chuyển chỗ: OK")

    # ---- thanh bên: hai ô trên thẻ Trạng thái, (i) sau chữ, không bị cắt ----------------------------------------------
    root, app, cfg = make_app()
    side = app.lbl_state.master.master.master                # row -> thẻ Trạng thái -> thanh bên
    stat = app.lbl_state.master.master
    assert app.start_cb.master.master.master is side and app.clean_cb.master.master.master is side
    for cb, ic in ((app.start_cb, app.start_icon), (app.clean_cb, app.clean_icon)):
        assert cb.winfo_ismapped() and ic.winfo_ismapped()
        assert cb.winfo_width() >= cb.winfo_reqwidth(), f"ô {cb.cget('text')} bị cắt"
        assert ic.winfo_rootx() >= cb.winfo_rootx() + cb.winfo_width() - 2, "biểu tượng phải ngay sau chữ"
        assert ic.winfo_rootx() + ic.winfo_width() <= side.winfo_rootx() + side.winfo_width(), "biểu tượng tràn thanh bên"
        assert cb.winfo_rooty() + cb.winfo_height() <= stat.winfo_rooty(), "ô phải nằm trên thẻ Trạng thái"
    assert app.start_cb.winfo_rooty() < app.clean_cb.winfo_rooty()
    nav_bottom = max(it.winfo_rooty() + it.winfo_height() for it, *_ in app.nav.values())
    assert nav_bottom <= app.start_cb.winfo_rooty(), "ô đè lên mục điều hướng"
    assert app.var_winstart.get() is False and app.clean_cb.instate(["selected"])
    print("thanh bên: Khởi động cùng Windows + Tự dọn trận cũ trên thẻ Trạng thái, (i) ngay sau chữ, không bị cắt: OK")

    # ---- rê chuột lên (i): giải thích ------------------------------------------------------------------------------
    assert app.start_icon_tip.win is None
    app.start_icon.event_generate("<Enter>")
    until(root, lambda: app.start_icon_tip.win is not None)
    t = tip_text(app.start_icon_tip)
    assert "đang TẮT" in t and "khay hệ thống" in t and "Vietkey" in t, t
    shot(root, app, "ro_chuot_khoi_dong.png", (app.start_icon_tip,))
    app.start_icon.event_generate("<Leave>")
    pump(root, 0.2)
    assert app.start_icon_tip.win is None
    app._clean_check()
    until(root, lambda: app._clean_st is not None and "Tự dọn" in app.clean_text)
    app.clean_icon.event_generate("<Enter>")
    until(root, lambda: app.clean_icon_tip.win is not None)
    t = tip_text(app.clean_icon_tip)
    assert "đang BẬT" in t, t
    shot(root, app, "ro_chuot_tu_don.png", (app.clean_icon_tip,))
    app.clean_icon.event_generate("<Leave>")
    pump(root, 0.2)
    print("rê chuột lên (i) / ô: hiện giải thích, rời chuột thì ẩn: OK")

    # ---- bấm ô Khởi động cùng Windows: ghi / xoá khoá (thử), lưu đã chọn ---------------------------------------------
    app.start_cb.invoke()
    assert app.var_winstart.get() is True and WS.get() == WS.command()
    assert E.load_config(cfg.settings_path()).win_startup_init, "đã tự chọn: không tự bật lại lần sau"
    app.start_icon.event_generate("<Enter>")
    until(root, lambda: app.start_icon_tip.win is not None)
    assert "đang BẬT" in tip_text(app.start_icon_tip)
    app.start_icon.event_generate("<Leave>")
    app.start_cb.invoke()
    assert app.var_winstart.get() is False and WS.get() is None
    assert "khởi động cùng Windows: TẮT" in app.txt.get("1.0", "end")
    print("bấm ô: bật ghi dòng khởi động (--tray --autostart), tắt thì xoá, ghi Nhật ký: OK")

    # ---- trạng thái: không ghi -> Đang ghi (bộ ghi bật, ngoài trận) ---------------------------------------------------
    assert app.lbl_state.cget("text") == "Không ghi"
    app._start()
    until(root, lambda: app.chip_title.cget("text") == "ĐANG GHI")
    pump(root, 0.4)
    assert app.lbl_state.cget("text") == "Đang ghi"
    sub = app.chip_sub.cget("text")
    assert sub == "Sẽ tự ghi khi vào trận\nNgoài trận không làm gì, nhẹ như Vietkey", sub
    side_txt = app.lbl_status.cget("text")
    assert side_txt.startswith("Sẽ tự ghi khi vào trận.") and "không tốn tài nguyên" in side_txt \
        and "không nặng máy" in side_txt and "Vietkey" in side_txt, side_txt
    assert stat.winfo_rooty() + stat.winfo_height() <= side.winfo_rooty() + side.winfo_height()
    assert app.chip_sub.winfo_width() >= app.chip_sub.winfo_reqwidth()
    assert len(app.tray.tip if app.tray is not None else "") < 128
    shot(root, app, "dang_ghi.png")
    app.engine.state = "trong game, chờ trận"
    app.state_text = "trong game, chờ trận"
    app._refresh_status()
    assert app.chip_sub.cget("text").startswith("Đã thấy game — vào trận là tự ghi\n")
    app.engine.state = app.state_text = "đang ghi"
    app._refresh_status()
    assert app.chip_title.cget("text") == "ĐANG GHI TRẬN" and app.lbl_state.cget("text") == "Đang ghi trận"
    assert "Vietkey" not in app.chip_sub.cget("text")
    app.engine.state = app.state_text = "chờ game"
    app._refresh_status()
    print("trạng thái: ĐANG GHI / Đang ghi + sẽ tự ghi khi vào trận, ngoài trận nhẹ như Vietkey; trong trận vẫn ĐANG GHI TRẬN: OK")

    # ---- bản exe: lần đầu tự bật, lần sau theo người dùng ---------------------------------------------------------
    cfg2 = E.load_config(cfg.settings_path())
    app.cfg.win_startup_init = False
    sys.frozen = True
    try:
        app._winstart_init()
        assert WS.is_enabled() and app.var_winstart.get() is True, "bản exe lần đầu phải tự bật"
        assert E.load_config(cfg.settings_path()).win_startup_init
        app.start_cb.invoke()                                # người dùng tắt
        assert not WS.is_enabled()
        app._winstart_init()                                 # mở lại app: không tự bật lại
        assert not WS.is_enabled() and app.var_winstart.get() is False
    finally:
        del sys.frozen
    assert cfg2.auto_clean
    print("bản exe: lần mở đầu tự bật khởi động cùng Windows, người dùng tắt thì lần sau giữ tắt: OK")
    close(root, app)

    # khoá thật của Windows không bị đụng
    real_after = None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REAL_KEY) as k:
            real_after = winreg.QueryValueEx(k, WS.NAME)[0]
    except OSError:
        pass
    assert real_after == real_before, (real_before, real_after)
    print("khởi động thật của Windows không đổi: OK")
    print("OK test_side_opts")


if __name__ == "__main__":
    threading.excepthook = lambda a: None
    main()
