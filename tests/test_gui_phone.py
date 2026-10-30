"""Trang "Điện thoại" của app Windows (v14): bật / tắt máy chủ cho app điện thoại, mã QR, menu khay, tự bật.

    python tests/test_gui_phone.py [file.aoerec]

Cấu hình + thư mục riêng trong Video\\_test\\gui_phone; mutex riêng của test; không gửi thống kê, không hỏi cập nhật.
Máy chủ nghe mọi card mạng như bản thật nhưng test chỉ gọi 127.0.0.1; kết nối trạm chuyển tiếp thật (cần Internet). Chạy từ mã nguồn nên không thêm luật tường lửa.
"""
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request

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

SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "Video", "_test", "expand_ui", "Raw",
                                                         "2026-10-22_010104_tran1.aoerec")
GAME = r"D:\Game\AoE-HD"


def local(url):
    return re.sub(r"^http://[^:/]+", "http://127.0.0.1", url)


def get(url, timeout=10):
    return urllib.request.urlopen(local(url), timeout=timeout).read()


def main():
    if not os.path.exists(SRC) or not os.path.isdir(GAME):
        print("bỏ qua: cần trận thật và thư mục game:", SRC, GAME)
        return
    import json
    import tkinter as tk

    import cv2
    import numpy as np

    from mapcap import engine as E
    from mapcap import gui
    from mapcap import relay_client as RC
    out = os.path.join(ROOT, "Video", "_test", "gui_phone")
    shutil.rmtree(out, ignore_errors=True)
    raw = os.path.join(out, "Raw")
    os.makedirs(raw)
    src = os.path.join(raw, os.path.basename(SRC))
    shutil.copy2(SRC, src)
    old = time.time() - 3600
    os.utime(src, (old, old))
    cfg = E.Config(out_dir=out, auto_start=False, game_dir=GAME)
    assert cfg.phone_server is False, "mặc định không tự bật máy chủ điện thoại"
    E.save_config(cfg)
    gui.load_config = lambda: E.load_config(cfg.settings_path())

    def pump(root, s):
        t0 = time.time()
        while time.time() - t0 < s:
            root.update()
            time.sleep(0.02)

    root = tk.Tk()
    app = gui.App(root)
    pump(root, 0.3)
    assert not app._phone_running() and app.btn_phone.cget("text").startswith("Bật")
    assert app.tray is not None and app.tray.phone_label == "Bật cho điện thoại"
    app.show_page("phone")
    pump(root, 0.2)

    # bật: địa chỉ + mã QR đọc ngược ra đúng địa chỉ
    app._phone_start()
    pump(root, 0.2)
    assert app._phone_running(), "không bật được"
    url = app.phone.url
    addr = app.var_phone_addr.get()
    assert re.fullmatch(r"\d+\.\d+\.\d+\.\d+:87\d\d/[a-z2-9]{6}", addr), addr
    assert url == f"http://{addr}/"
    assert app.btn_phone.cget("text") == "Tắt" and app.tray.phone_label == "Tắt cho điện thoại"
    pair = app.phone.pair_url()
    assert pair == f"{RC.RELAY}/#r={app.phone.room}&l={addr}", pair
    img = np.asarray(gui.App.qr_image(pair).convert("L"))
    text, _pts, _ = cv2.QRCodeDetector().detectAndDecode(img)
    assert text == pair, (text, pair)
    t0 = time.time()
    while app.phone.relay_state() != "online" and time.time() - t0 < 40:
        pump(root, 0.2)
    pump(root, 1.2)
    assert app.phone.relay_state() == "online", app.phone.relay_state()
    assert "sẵn sàng" in app.phone_net.cget("text"), app.phone_net.cget("text")
    try:                                                   # ảnh trang để xem bằng mắt
        from PIL import ImageGrab
        root.lift()
        root.attributes("-topmost", True)
        pump(root, 0.5)
        x, y = root.winfo_rootx(), root.winfo_rooty()
        ImageGrab.grab((x, y, x + root.winfo_width(), y + root.winfo_height())).save(os.path.join(out, "phone_page.png"))
        root.attributes("-topmost", False)
    except Exception as e:  # noqa: BLE001
        print("không chụp được trang:", e)
    print(f"bật máy chủ: {url}, mã QR đọc ngược đúng liên kết trạm (phòng + mạng nhà), trạm online: OK")

    # máy chủ trả danh sách trận + trang web (bản có nút Quét mã QR)
    items = json.loads(get(url + "api/matches"))
    assert [i["file"] for i in items] == [os.path.basename(src)], items
    assert b'id="scan-qr"' in get(url)
    print("máy chủ: danh sách trận đúng thư mục Raw của cấu hình, trang web: OK")

    # đang ghi trận: hoãn chuyển trận (không tốn CPU khi đang chơi)
    app._recording = True
    name = urllib.request.quote(os.path.basename(src))
    st = json.loads(get(url + f"api/match?f={name}&check=1"))
    assert st["ready"] is False
    t0 = time.time()
    while not st.get("waiting") and time.time() - t0 < 10:
        time.sleep(0.5)
        st = json.loads(get(url + f"api/match?f={name}&check=1"))
    assert st.get("waiting") and st["progress"] == 0, st
    print("đang ghi trận: máy chủ báo chờ, chưa chuyển trận: OK")

    # menu khay: tắt rồi bật lại (bật thì mở trang Điện thoại)
    app.tray.on_action("phone")
    pump(root, 0.5)
    assert not app._phone_running() and app.var_phone_addr.get() == ""
    try:
        get(url + "api/matches", timeout=3)
        raise AssertionError("máy chủ vẫn trả lời sau khi tắt")
    except (urllib.error.URLError, ConnectionError, OSError):
        pass
    app.show_page("matches")
    app.tray.on_action("phone")
    pump(root, 0.5)
    assert app._phone_running() and app.page == "phone"
    assert app.phone.url == url, "bật lại phải giữ nguyên địa chỉ (mã trong token.txt)"
    assert app.phone.pair_url() == pair, "bật lại phải giữ nguyên phòng (relay.txt): điện thoại không phải quét lại"
    print("menu khay: tắt / bật cho điện thoại, giữ nguyên địa chỉ: OK")

    # tự bật khi mở app
    app.var_phone_auto.set(True)
    app._phone_auto_changed()
    assert E.load_config(cfg.settings_path()).phone_server is True
    app._recording = False
    app._quit()
    assert not app.phone.running
    root2 = tk.Tk()
    app2 = gui.App(root2)
    pump(root2, 2.5)
    assert app2._phone_running() and app2.phone.url == url, "mở app phải tự bật lại máy chủ"
    app2._quit()
    print("tự bật máy chủ khi mở app: OK")
    print("OK test_gui_phone")


if __name__ == "__main__":
    main()
