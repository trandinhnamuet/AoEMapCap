"""Nhắn qua lại giữa admin và người gửi báo cáo hack (2026-11-14), chạy với Worker cục bộ:

    cd telemetry && npx wrangler d1 migrations apply aoe-mapcap-telemetry --local && npx wrangler dev --local --port 8799
    python tests/test_report_chat.py http://127.0.0.1:8799

- máy chủ: app gửi báo cáo -> /v1/report/status trả trạng thái + tin; admin nhắn (/api/report/message, cần mật khẩu) ->
  app thấy; app trả lời (/v1/report/reply) -> trang admin thấy; máy khác (mã máy khác) không đọc / không trả lời được;
- giao diện: trang Lịch sử báo cáo có cột "Admin trả lời", khung tin nhắn, số tin chưa đọc ở thanh bên (xem rồi thì hết),
  gửi trả lời từ app.
Mật khẩu admin đọc từ telemetry/.dev.vars (không in ra).
"""
import glob
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
WORKER = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8799"
os.environ["AOEMAPCAP_UPDATE_URL"] = "http://127.0.0.1:9/version.json"
os.environ["AOEMAPCAP_TELEMETRY"] = "0"
os.environ["AOEMAPCAP_INSTANCE"] = f"AoE-MapCap-test-{os.getpid()}"
os.environ["AOEMAPCAP_REPORT_URL"] = WORKER + "/v1/report"

import tkinter as tk  # noqa: E402

from mapcap import engine as E  # noqa: E402
from mapcap import gui as G  # noqa: E402
from mapcap import report, telemetry  # noqa: E402

OUT = os.path.join(ROOT, "Video", "_test", "report_chat")


def admin_pw():
    for line in open(os.path.join(ROOT, "telemetry", ".dev.vars"), encoding="utf-8"):
        if line.strip().startswith("STATS_PASSWORD"):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("thiếu STATS_PASSWORD trong telemetry/.dev.vars")


def call(path, body=None, pw=None):
    req = urllib.request.Request(WORKER + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={**({"authorization": "Bearer " + pw} if pw else {}),
                                          "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


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


def until(root, cond, s=30):
    t0 = time.time()
    while not cond():
        assert time.time() - t0 < s, "hết giờ chờ"
        pump(root, 0.1)


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(os.path.join(OUT, "Raw"))
    me = str(uuid.uuid4())
    telemetry.install_id = lambda: me
    src = min((p for p in glob.glob(os.path.join(ROOT, "Video", "Raw", "*.aoerec")) if os.path.getsize(p) > 2e5),
              key=os.path.getsize)
    path = os.path.join(OUT, "Raw", os.path.basename(src))
    shutil.copy2(src, path)
    pw = admin_pw()

    # ---- 1. máy chủ -----------------------------------------------------------------------------------------
    info = {"recorder": "Nguoi Bao", "map": "Hill Country", "duration_ms": 600000, "players": [{"name": "A"}, {"name": "B"}]}
    rid = report.upload(path, info, suspect="B", note="app báo oan tôi")
    st = report.fetch_status()
    assert st == {rid: {"status": "new", "msgs": []}}, st
    assert call("/api/report/message", {"id": rid, "text": "x"})[0] == 401, "nhắn của admin phải cần mật khẩu"
    code, j = call("/api/report/message", {"id": rid, "text": "Đã xem: báo oan thật, bản v42 đã sửa.\nCảm ơn bạn."}, pw)
    assert code == 200 and j["msg"]["who"] == "admin", (code, j)
    assert call("/api/report/update", {"id": rid, "status": "clean", "admin_note": "ghi chú riêng"}, pw)[0] == 200
    st = report.fetch_status()[rid]
    assert st["status"] == "clean" and [m["who"] for m in st["msgs"]] == ["admin"] and "v42" in st["msgs"][0]["text"] \
        and "\n" in st["msgs"][0]["text"], st
    assert "ghi chú riêng" not in json.dumps(st, ensure_ascii=False), "ghi chú riêng của admin không được gửi cho người dùng"
    m = report.send_reply(rid, "Cảm ơn admin, tôi đã cập nhật.")
    assert m["who"] == "user"
    # máy khác: không thấy báo cáo này, không trả lời thay được
    other = str(uuid.uuid4())
    telemetry.install_id = lambda: other
    assert report.fetch_status() == {}
    try:
        report.send_reply(rid, "giả mạo")
        raise AssertionError("máy khác không được trả lời thay")
    except report.ReportError:
        pass
    telemetry.install_id = lambda: me
    code, j = call("/api/reports", pw=pw)
    row = next(r for r in j["reports"] if r["id"] == rid)
    assert [(x["who"], x["text"][:8]) for x in row["msgs"]] == [("admin", "Đã xem: "), ("user", "Cảm ơn a")], row["msgs"]
    print("máy chủ: admin nhắn (cần mật khẩu) -> app thấy trạng thái + tin; app trả lời -> trang admin thấy; máy khác "
          "không đọc / không trả lời được; ghi chú riêng của admin không gửi đi: OK")

    # ---- 2. giao diện ---------------------------------------------------------------------------------------
    cfg = E.Config(out_dir=OUT, auto_start=False)
    E.save_config(cfg)
    report.add_history(cfg.resolved_out_dir(), rid, path, info, "B", "app báo oan tôi", "")
    G.load_config = lambda: E.load_config(cfg.settings_path())
    G.Engine = FakeEngine
    root = tk.Tk()
    app = G.App(root)
    root.geometry("1100x760+40+20")
    try:
        nav = app.nav["reports"][3]
        app._reports_fetch()                                   # như lúc mở app: tải nền, chưa mở trang
        until(root, lambda: "●" in nav.cget("text"))
        assert nav.cget("text").endswith("● 1"), nav.cget("text")
        app.show_page("reports")
        until(root, lambda: "Admin" in app.rep_chat.get("1.0", "end"))
        tv = app.rep_tree
        iid = tv.selection()[0]
        assert "Không hack" in tv.set(iid, "admin") and "1 tin" in tv.set(iid, "admin"), tv.set(iid, "admin")
        chat = app.rep_chat.get("1.0", "end")
        assert "bản v42 đã sửa" in chat and "Cảm ơn admin" in chat and "Admin đánh dấu: Không hack" in chat, chat
        until(root, lambda: "●" not in nav.cget("text"))       # đang xem = đã đọc
        assert report.load_seen(cfg.resolved_out_dir()).get(rid), "phải nhớ tin đã đọc"
        app.rep_reply.insert("1.0", "Tôi gửi thêm từ app")
        app._report_reply()
        until(root, lambda: "Tôi gửi thêm từ app" in app.rep_chat.get("1.0", "end"))
        assert not app.rep_reply.get("1.0", "end").strip()
        code, j = call("/api/reports", pw=pw)
        row = next(r for r in j["reports"] if r["id"] == rid)
        assert row["msgs"][-1]["who"] == "user" and row["msgs"][-1]["text"] == "Tôi gửi thêm từ app", row["msgs"]
        # admin nhắn thêm khi người dùng đang ở trang khác -> lại có dấu chưa đọc
        app.show_page("log")
        call("/api/report/message", {"id": rid, "text": "Tin thứ hai"}, pw)
        app._reports_fetch()
        until(root, lambda: nav.cget("text").endswith("● 1"))
        print("giao diện: cột Admin trả lời, khung tin nhắn, dấu chưa đọc ở thanh bên (xem thì hết, có tin mới thì hiện lại), "
              "gửi trả lời từ app: OK")
    finally:
        if getattr(app, "stop_event", None) is not None:
            app.stop_event.set()
        try:
            app._phone_stop()
        except Exception:  # noqa: BLE001
            pass
        root.destroy()
    print("OK test_report_chat")


if __name__ == "__main__":
    main()
