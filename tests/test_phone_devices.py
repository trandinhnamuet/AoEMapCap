"""Trang Điện thoại của app Windows (v39): điện thoại đã liên kết, trận đã lên điện thoại, chọn trận để gửi thêm.

- máy chủ: app điện thoại gửi cid / tên máy khi hỏi danh sách -> ghi vào sổ (phones.json), lấy file ghi -> "đang dựng",
  báo trận đã lưu (api/saved) -> "đã lưu"; trận chọn gửi có push = true trong danh sách tới khi máy đó báo đã lưu;
  yêu cầu qua trạm (User-Agent relay) ghi đường Internet; app bản cũ (không cid) không vào sổ;
- giao diện: bảng máy đã liên kết + bảng trận (trạng thái từng trận), nút Gửi lên điện thoại / Bỏ chờ gửi / Quên máy;
  sổ còn nguyên sau khi tắt / bật lại.

    python tests/test_phone_devices.py
Ảnh: Video/_test/phone_devices/.
"""
import glob
import json
import os
import shutil
import sys
import threading
import time
import urllib.parse
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

import tkinter as tk  # noqa: E402

from mapcap import engine as E  # noqa: E402
from mapcap import gui as G  # noqa: E402
from mapcap import mobile_server as MS  # noqa: E402

GAME = r"D:\Game\AoE-HD"
OUT = os.path.join(ROOT, "Video", "_test", "phone_devices")


class FakeEngine:
    def __init__(self, cfg, logger, stop_event, status=None, progress=None, on_hack=None):
        self.cfg, self.stop_event, self.state, self.current_rec_path = cfg, stop_event, "chờ game", None

    def run(self):
        self.stop_event.wait(60)


def get(url, ua=None):
    req = urllib.request.Request(url, headers={"User-Agent": ua} if ua else {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


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
            if 0.8e6 < os.path.getsize(p) < 9e6][-4:]
    assert len(srcs) >= 3, "cần ít nhất 3 trận thật trong Video/Raw"
    names = []
    for p in srcs:
        d = os.path.join(raw, os.path.basename(p))
        shutil.copy2(p, d)
        os.utime(d, (time.time() - 7200,) * 2)
        names.append(os.path.basename(p))

    # ---- 1. máy chủ + sổ điện thoại -------------------------------------------------------------------
    web = os.path.join(OUT, "Web")
    srv, url = MS.serve(raw, GAME, port=0, token="t", cache=web, host="127.0.0.1", log=lambda m: None)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    ph = srv.phones
    items = json.loads(get(url + "api/matches"))                          # app bản cũ: không cid
    assert len(items) == len(names) and not ph.snapshot()[0] and not any(i.get("push") for i in items)
    q = "cid=abc123xyz&dev=" + urllib.parse.quote("Samsung SM-A546E") + "&app=10"
    json.loads(get(url + "api/matches?" + q))
    devs, push = ph.snapshot()
    assert len(devs) == 1 and devs[0]["name"] == "Samsung SM-A546E" and devs[0]["app"] == 10 and devs[0]["via"] == "lan" \
        and devs[0]["online"] and not devs[0]["saved"], devs
    # lấy file ghi -> đang dựng; báo đã lưu -> đã lưu
    assert get(url + f"api/rec?f={names[0]}&cid=abc123xyz") == open(os.path.join(raw, names[0]), "rb").read()
    assert names[0] in ph.snapshot()[0][0]["got"]
    assert json.loads(get(url + "api/saved?cid=abc123xyz&f=" + urllib.parse.quote(names[0])))["ok"]
    d = ph.snapshot()[0][0]
    assert names[0] in d["saved"] and names[0] not in d["got"], d
    # chọn trận gửi: push = true tới khi máy báo đã lưu
    ph.set_push([names[1], names[0]], True)
    items = json.loads(get(url + "api/matches?" + q))
    assert {i["file"] for i in items if i.get("push")} == {names[1]}, "trận đã có trên máy không gửi lại"
    get(url + "api/saved?cid=abc123xyz&reset=1&f=" + urllib.parse.quote(names[0] + "|" + names[1]))
    assert not ph.snapshot()[1] and not any(i.get("push") for i in json.loads(get(url + "api/matches?" + q)))
    # máy thứ hai qua trạm chuyển tiếp; danh sách đầy đủ (reset) bỏ trận đã xoá bên điện thoại
    json.loads(get(url + "api/matches?cid=second0002&dev=Pixel%208&app=10", ua="relay"))
    get(url + "api/saved?cid=abc123xyz&reset=1&f=" + urllib.parse.quote(names[1]))
    devs = {d["cid"]: d for d in ph.snapshot()[0]}
    assert devs["second0002"]["via"] == "relay" and list(devs["abc123xyz"]["saved"]) == [names[1]]
    # mã máy lạ / sai dạng bị bỏ qua; api/saved không cid -> 404
    json.loads(get(url + "api/matches?cid=../x&dev=bad"))
    assert len(ph.snapshot()[0]) == 2
    try:
        get(url + "api/saved?f=x.aoerec")
        raise AssertionError("api/saved thiếu cid phải 404")
    except urllib.error.HTTPError as e:
        assert e.code == 404
    srv.shutdown()
    srv.server_close()
    j = json.load(open(os.path.join(web, "phones.json"), encoding="utf-8"))
    assert set(j["devices"]) == {"abc123xyz", "second0002"}
    print("máy chủ: ghi máy đã liên kết (tên, bản app, đường kết nối), trận đang dựng / đã lưu, trận chọn gửi (push) tới khi "
          "máy báo đã lưu, lưu ra phones.json: OK")

    # ---- 2. giao diện ---------------------------------------------------------------------------------
    cfg = E.Config(out_dir=OUT, auto_start=False)
    E.save_config(cfg)
    G.load_config = lambda: E.load_config(cfg.settings_path())
    G.Engine = FakeEngine
    root = tk.Tk()
    app = G.App(root)
    root.geometry("1100x760+40+20")
    try:
        t = app.table.tree
        until(root, lambda: len(t.get_children()) >= len(names))
        app.show_page("phone")
        pump(root, 0.5)
        dv, mv = app.phone_devs, app.phone_matches
        assert set(dv.get_children()) == {"abc123xyz", "second0002"}, dv.get_children()
        assert "Samsung SM-A546E (app v10)" in dv.set("abc123xyz", "name") and dv.set("abc123xyz", "n") == "1"
        assert dv.set("second0002", "via") == "Qua Internet" and dv.set("abc123xyz", "via") == "Mạng nhà (Wi-Fi)"
        assert set(mv.get_children()) == set(names)
        assert mv.set(names[1], "st").startswith("✔ Đã lưu: Samsung") and mv.set(names[2], "st") == "Chưa gửi"
        # bộ lọc: đã lưu / chưa lưu
        app.var_phone_filter.set("Đã lưu trên điện thoại")
        app._phone_lists()
        assert set(mv.get_children()) == {names[1]}, mv.get_children()
        assert "1 / " in app.phone_count.cget("text") and "1 trận đã lưu" in app.phone_count.cget("text")
        app.var_phone_filter.set("Chưa lưu trên điện thoại")
        app._phone_lists()
        assert set(mv.get_children()) == set(names) - {names[1]}
        app.var_phone_filter.set("Tất cả trận")
        app._phone_lists()
        # lăn chuột trên bảng trận: chỉ bảng cuộn, trang không cuộn theo
        outer = app.pages["phone"]
        cv = [w for w in outer.winfo_children() if w.winfo_class() == "Canvas"][0]
        root.geometry("1100x520+40+20")
        pump(root, 0.4)
        y0 = cv.yview()[0]
        mv.event_generate("<Enter>")
        outer.event_generate("<Enter>")
        pump(root, 0.1)
        mv.focus_set()
        mv.event_generate("<MouseWheel>", delta=-240)
        pump(root, 0.2)
        assert cv.yview()[0] == y0, ("lăn trên bảng làm cuộn cả trang", y0, cv.yview())
        app.phone_dev_note.event_generate("<MouseWheel>", delta=-240)      # đối chứng: lăn ở chỗ khác thì trang cuộn
        pump(root, 0.2)
        assert cv.yview()[0] > y0, ("lăn ngoài bảng phải cuộn trang (đối chứng)", y0, cv.yview())
        root.geometry("1100x760+40+20")
        pump(root, 0.3)
        # chọn 2 trận -> Gửi lên điện thoại
        mv.selection_set([names[2], names[0]])
        app._phone_push(True)
        pump(root, 0.3)
        assert mv.set(names[2], "st") == "Chờ điện thoại kết nối để lấy" and mv.set(names[0], "st") == "Chờ điện thoại kết nối để lấy"
        assert app._phones().snapshot()[1] == {names[2], names[0]}
        assert "2 trận" in app.phone_push_msg.cget("text")
        if os.environ.get("AOEMAPCAP_TEST_SHOTS") == "1":   # chụp màn hình đưa cửa sổ lên trên cùng: chỉ khi được bật rõ ràng
            shot(root, "dien_thoai.png")
        mv.selection_set([names[0]])
        app._phone_push(False)
        pump(root, 0.2)
        assert mv.set(names[0], "st") == "Chưa gửi" and app._phones().snapshot()[1] == {names[2]}
        # quên một máy
        dv.selection_set("second0002")
        app._phone_forget()
        pump(root, 0.2)
        assert set(dv.get_children()) == {"abc123xyz"}
        j = json.load(open(os.path.join(web, "phones.json"), encoding="utf-8"))
        assert set(j["devices"]) == {"abc123xyz"} and j["push"] == [names[2]]
        print("giao diện: bảng máy đã liên kết + bảng trận theo trạng thái, Gửi lên điện thoại / Bỏ chờ gửi / Quên máy, lưu "
              "ra file: OK")
    finally:
        if getattr(app, "stop_event", None) is not None:
            app.stop_event.set()
        try:
            app._phone_stop()
        except Exception:  # noqa: BLE001
            pass
        root.destroy()
    print("OK test_phone_devices")


if __name__ == "__main__":
    main()
