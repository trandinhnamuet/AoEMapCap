"""Thống kê sử dụng: phía app (mapcap/telemetry.py) và Worker chạy cục bộ (telemetry/, wrangler dev + D1 cục bộ).

    python tests/test_telemetry.py

Không gửi gì lên máy chủ thật: phía app gửi tới máy chủ HTTP cục bộ; Worker chạy bằng `wrangler dev --local`
(cần Node + npm install trong telemetry/; thiếu thì bỏ qua phần Worker). Tắt wrangler theo PID của nó.
"""
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

from mapcap import telemetry  # noqa: E402

WORK = os.path.join(ROOT, "Video", "_test", "telemetry")
TELE = os.path.join(ROOT, "telemetry")
DEV_PORT = 8799
DEV_PW = "local-test-password"


def test_install_id_and_switch():
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    old = os.environ.get("APPDATA")
    os.environ["APPDATA"] = WORK
    try:
        a = telemetry.install_id()
        uuid.UUID(a)
        assert telemetry.install_id() == a, "mã máy phải giữ nguyên giữa các lần mở"
        assert open(os.path.join(WORK, "AoE-MapCap", "install_id"), encoding="ascii").read().strip() == a
        with open(os.path.join(WORK, "AoE-MapCap", "install_id"), "w") as f:
            f.write("khong-phai-uuid")
        b = telemetry.install_id()
        assert b != a and uuid.UUID(b)
    finally:
        if old is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = old
    env = os.environ.pop("AOEMAPCAP_TELEMETRY", None)
    try:
        assert telemetry.enabled() is False, "chạy từ mã nguồn mặc định không gửi"
        os.environ["AOEMAPCAP_TELEMETRY"] = "1"
        assert telemetry.enabled(False) is True
        os.environ["AOEMAPCAP_TELEMETRY"] = "0"
        assert telemetry.enabled(True) is False and telemetry.send("mapcap") is None
    finally:
        os.environ.pop("AOEMAPCAP_TELEMETRY", None)
        if env is not None:
            os.environ["AOEMAPCAP_TELEMETRY"] = env
    ini = os.path.join(WORK, "_settings.ini")
    with open(ini, "w", encoding="utf-8") as f:
        f.write("[mapcap]\ntelemetry = 0\n")
    assert telemetry.flag_from_settings(ini) is False and telemetry.flag_from_settings(ini + ".x") is True
    print("mã máy lưu %APPDATA%, bật/tắt theo môi trường / Cài đặt: OK")


def test_send_payload():
    got = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("content-length") or 0)
            got.append((self.client_address[0], json.loads(self.rfile.read(n)), self.headers.get("user-agent")))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ["AOEMAPCAP_TELEMETRY"] = "1"
    os.environ["AOEMAPCAP_TELEMETRY_URL"] = f"http://127.0.0.1:{srv.server_address[1]}/v1/e"
    try:
        telemetry.send("replay", "open", wait=True)
        telemetry.send("mapcap", "match", wait=True)
    finally:
        os.environ.pop("AOEMAPCAP_TELEMETRY", None)
        os.environ.pop("AOEMAPCAP_TELEMETRY_URL", None)
        srv.shutdown()
    assert len(got) == 2, got
    ip, p, ua = got[0]
    from mapcap.version import APP_VERSION
    assert p == {"id": telemetry.install_id(), "app": "replay", "v": APP_VERSION, "ev": "open"}, p
    assert got[1][1]["ev"] == "match" and ua.startswith("AoE-MapCap/")
    assert set(p) == {"id", "app", "v", "ev"}, "không gửi gì ngoài mã máy, app, phiên bản, loại"
    # không mạng: không treo, không lỗi
    os.environ["AOEMAPCAP_TELEMETRY"] = "1"
    os.environ["AOEMAPCAP_TELEMETRY_URL"] = "http://127.0.0.1:9/v1/e"
    try:
        t0 = time.time()
        msgs = []
        telemetry.send("mapcap", log=msgs.append, wait=True)
        assert time.time() - t0 < 8 and msgs and "không gửi được" in msgs[0]
    finally:
        os.environ.pop("AOEMAPCAP_TELEMETRY", None)
        os.environ.pop("AOEMAPCAP_TELEMETRY_URL", None)
    print("gửi đúng 4 trường (mã máy, app, phiên bản, loại), không mạng thì bỏ qua: OK")


def _get(url, pw=None):
    req = urllib.request.Request(url, headers={"authorization": "Bearer " + pw} if pw else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_worker_local():
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    if not npx or not os.path.isdir(os.path.join(TELE, "node_modules")):
        print("bỏ qua Worker cục bộ: chưa có Node / npm install trong telemetry/")
        return
    state = os.path.join(TELE, ".wrangler", "state-test")
    shutil.rmtree(state, ignore_errors=True)
    env = dict(os.environ, WRANGLER_SEND_METRICS="false")
    subprocess.run([npx, "wrangler", "d1", "execute", "aoe-mapcap-telemetry", "--local", "--persist-to", state,
                    "--file=schema.sql", "-y"], cwd=TELE, env=env, capture_output=True, check=True)
    dev = subprocess.Popen([npx, "wrangler", "dev", "--local", "--port", str(DEV_PORT), "--persist-to", state],
                           cwd=TELE, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{DEV_PORT}"
    try:
        t0 = time.time()
        while True:
            try:
                urllib.request.urlopen(base + "/", timeout=2).read()
                break
            except Exception:  # noqa: BLE001
                if time.time() - t0 > 60:
                    raise AssertionError("wrangler dev không lên")
                time.sleep(1)
        assert _get(base + "/api/stats")[0] == 401, "không mật khẩu phải bị chặn"
        assert _get(base + "/api/stats", "sai-mat-khau")[0] == 401
        os.environ["AOEMAPCAP_TELEMETRY"] = "1"
        os.environ["AOEMAPCAP_TELEMETRY_URL"] = base + "/v1/e"
        try:
            telemetry.send("mapcap", "open", wait=True)
            telemetry.send("mapcap", "open", wait=True)          # trùng trong 5 s -> bỏ
            telemetry.send("mapcap", "match", wait=True)
            telemetry.send("replay", "open", wait=True)          # khác loại -> nhận
        finally:
            os.environ.pop("AOEMAPCAP_TELEMETRY", None)
            os.environ.pop("AOEMAPCAP_TELEMETRY_URL", None)
        bad = urllib.request.Request(base + "/v1/e", data=b'{"id":"x","app":"mapcap","v":"6","ev":"open"}',
                                     headers={"content-type": "application/json"})
        try:
            urllib.request.urlopen(bad, timeout=10)
            raise AssertionError("dữ liệu sai phải bị từ chối")
        except urllib.error.HTTPError as e:
            assert e.code == 400
        st, d = _get(base + "/api/stats?range=today", DEV_PW)
        assert st == 200, (st, d)
        s = d["summary"]
        assert s == {"opens": 2, "installs": 1, "ips": 1, "matches": 1, "newInstalls": 1, "returningOpens": 1}, s
        assert d["recentTotal"] == 3 and d["recent"][-1]["isNew"] == 1 and d["recent"][0]["isNew"] == 0
        assert {r["name"] for r in d["apps"]} == {"mapcap", "replay"} and d["daily"][0]["opens"] == 2
        assert d["topInstalls"][0]["opens"] == 2 and d["topInstalls"][0]["matches"] == 1
        st, d2 = _get(base + "/api/stats?range=all&q=" + telemetry.install_id()[:8], DEV_PW)
        assert d2["recentTotal"] == 3
        st, d3 = _get(base + "/api/stats?range=all&q=khongco", DEV_PW)
        assert d3["recentTotal"] == 0 and d3["summary"]["opens"] == 2, "tìm kiếm chỉ lọc bảng từng lượt"
        with urllib.request.urlopen(base + "/stats", timeout=10) as r:
            html = r.read().decode("utf-8")
        assert "Thống kê sử dụng AoE-MapCap" in html and "chart.umd.min.js" in html
    finally:
        subprocess.run(["taskkill", "/PID", str(dev.pid), "/T", "/F"], capture_output=True)
        shutil.rmtree(state, ignore_errors=True)
    print("Worker cục bộ: nhận lượt, bỏ trùng 5 s, đếm trận, máy mới / quay lại, mật khẩu, tìm kiếm, trang /stats: OK")


if __name__ == "__main__":
    test_install_id_and_switch()
    test_send_payload()
    test_worker_local()
    print("OK")
