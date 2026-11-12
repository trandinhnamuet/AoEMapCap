"""Trang Góp ý (v31): nút Báo lỗi / Góp ý mở trang viết bài ở GitHub Discussions (đúng mục, điền sẵn phiên bản app +
Windows), Xem các ý kiến đã gửi, Sao chép Nhật ký.

    python tests/test_feedback.py

Không mở trình duyệt (webbrowser.open thay bằng hàm ghi lại). Engine giả, cấu hình + ảnh ở Video\\_test\\feedback, mutex
riêng, không gửi thống kê. Thêm --online: kiểm trang Discussions công khai trả về 200 và có hai mục q-a / ideas.
"""
import os
import shutil
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse

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
import webbrowser  # noqa: E402

from mapcap import engine as E  # noqa: E402
from mapcap import gui as G  # noqa: E402
from mapcap.version import APP_VERSION  # noqa: E402

OUT = os.path.join(ROOT, "Video", "_test", "feedback")
OPENED = []


def pump(root, s):
    t0 = time.time()
    while time.time() - t0 < s:
        root.update()
        time.sleep(0.02)


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


def online():
    import ssl
    import urllib.request
    import certifi
    ctx = ssl.create_default_context(cafile=certifi.where())
    req = urllib.request.Request(G.App.FEEDBACK_URL, headers={"User-Agent": "AoE-MapCap-test"})
    with urllib.request.urlopen(req, context=ctx, timeout=20) as r:
        html = r.read().decode("utf-8", "replace")
        assert r.status == 200
    for slug in ("q-a", "ideas"):
        assert f"/discussions/categories/{slug}" in html, f"thiếu mục {slug}"
    print("trang Discussions công khai, có mục Q&A và Ideas: OK")


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    webbrowser.open = lambda url, *a, **k: OPENED.append(url) or True
    cfg = E.Config(out_dir=OUT, auto_start=False)
    E.save_config(cfg)
    G.load_config = lambda: E.load_config(cfg.settings_path())
    root = tk.Tk()
    root.tk.call("tk", "scaling", 1.25)
    app = G.App(root)
    root.geometry("1200x720+40+40")
    pump(root, 0.6)

    # mục Góp ý trên thanh bên, mở trang
    item, _bar, _ic, tx = app.nav["feedback"]
    assert tx.cget("text") == "Góp ý / Báo lỗi"
    item.event_generate("<Button-1>")
    pump(root, 0.4)
    assert app.page == "feedback" and app.pages["feedback"].winfo_ismapped()
    for b in (app.btn_bug, app.btn_idea, app.btn_fb_list, app.btn_copy_log):
        assert b.winfo_ismapped() and b.winfo_width() >= b.winfo_reqwidth(), b.cget("text")
    shot(root, "gop_y.png")
    print("thanh bên có mục Góp ý, trang hiện đủ nút: OK")

    # đường dẫn
    app.btn_fb_list.invoke()
    assert OPENED[-1] == "https://github.com/trandinhnamuet/AoEMapCap/discussions", OPENED
    for btn, cat, title in ((app.btn_bug, "q-a", "[Lỗi] "), (app.btn_idea, "ideas", "[Góp ý] ")):
        btn.invoke()
        u = urlparse(OPENED[-1])
        q = parse_qs(u.query, keep_blank_values=True)
        assert u.scheme == "https" and u.netloc == "github.com" and u.path == "/trandinhnamuet/AoEMapCap/discussions/new", u
        assert q["category"] == [cat] and q["title"] == [title], q
        body = q["body"][0]
        assert f"AoE-MapCap v{APP_VERSION}, Windows" in body, body
        assert len(OPENED[-1]) < 2000, len(OPENED[-1])
    assert "góp ý: mở" in app.txt.get("1.0", "end")
    print(f"Báo lỗi -> mục Q&A, Góp ý -> mục Ideas, điền sẵn tiêu đề + mẫu + phiên bản ({app._system_info()}): OK")

    # sao chép Nhật ký
    app._append("dòng nhật ký thử 123")
    app.btn_copy_log.invoke()
    clip = root.clipboard_get()
    assert clip.startswith(f"AoE-MapCap v{APP_VERSION}") and "dòng nhật ký thử 123" in clip and clip.endswith("```")
    assert "Đã sao chép" in app.fb_msg.cget("text")
    shot(root, "da_sao_chep.png")
    print("Sao chép Nhật ký: phiên bản + nhật ký trong khung ```, báo đã sao chép: OK")

    # trình duyệt không mở được: sao chép đường dẫn
    webbrowser.open = lambda url, *a, **k: False
    app.btn_fb_list.invoke()
    assert root.clipboard_get() == G.App.FEEDBACK_URL and "đã sao chép đường dẫn" in app.fb_msg.cget("text")
    print("không mở được trình duyệt: sao chép đường dẫn + báo: OK")

    # cửa sổ nhỏ nhất: mục điều hướng không đè ô ở đáy thanh bên
    root.geometry("980x600+40+40")
    pump(root, 0.6)
    nav_bottom = max(it.winfo_rooty() + it.winfo_height() for it, *_ in app.nav.values())
    assert nav_bottom <= app.start_cb.winfo_rooty(), (nav_bottom, app.start_cb.winfo_rooty())
    page = app.pages["feedback"]
    for b in (app.btn_bug, app.btn_idea, app.btn_fb_list, app.btn_copy_log):
        assert b.winfo_height() >= b.winfo_reqheight() and b.winfo_width() >= b.winfo_reqwidth(), \
            f"nút {b.cget('text')} bị ép ở cửa sổ nhỏ nhất"
    last = page.winfo_children()[-1]
    assert last.winfo_rooty() + last.winfo_reqheight() <= page.winfo_rooty() + page.winfo_height() + 1, "trang bị cắt đáy"
    shot(root, "min_600.png")
    print("cửa sổ 980x600: 5 mục điều hướng không đè hai ô + thẻ Trạng thái: OK")
    app._stop_tray()
    root.destroy()
    if "--online" in sys.argv:
        online()
    print("OK test_feedback")


if __name__ == "__main__":
    threading.excepthook = lambda a: None
    main()
