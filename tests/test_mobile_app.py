"""Phần "trong app Android" của mobile/web, chạy trên máy tính không cần điện thoại:
một máy chủ Python đóng vai vỏ Android (MainActivity: /app/ = mobile/web, /pc/<ip:cổng>/<mã>/... chuyển tiếp sang
http://<ip:cổng>/<mã>/...), Edge chạy ẩn coi nó là appassets.androidplatform.net (trang an toàn để có Cache Storage).
Kiểm:
1. chưa có địa chỉ -> màn hình kết nối; nhập sai báo lỗi; quét mã QR (AoEApp giả: mã lạ báo lỗi, mã của máy tính
   -> danh sách trận);
2. mở trận: tải gói hình + trận qua đường chuyển tiếp, lưu vào Cache Storage; quay lại thấy nhãn "đã lưu";
   mở app từ trình duyệt (?pair=) đổi địa chỉ; trang của máy tính trên trình duyệt Android có nút Tải app / Mở trong app;
3. tắt máy chủ máy tính: danh sách hiện trận đã lưu + ghi chú, mở trận từ bộ nhớ điện thoại.

    python tests/test_mobile_app.py [file.aoerec]
Edge chạy ẩn bằng hồ sơ riêng trong thư mục tạm, tắt theo PID; không đụng game hay trình duyệt của người dùng.
"""
import os
import shutil
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from test_mobile_web import GAME, OUT, SRC, Browser  # noqa: E402

from mapcap import mobile_server as MS  # noqa: E402
from mapcap import webexport as WE  # noqa: E402

HOST = "appassets.androidplatform.net"


def shell_handler():
    """Giống MainActivity.shouldInterceptRequest / proxy."""
    web = MS.web_root()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="text/plain; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            if self.path.startswith("/pc/"):
                try:
                    r = urllib.request.urlopen("http://" + self.path[4:], timeout=60)
                except urllib.error.HTTPError as e:
                    r = e
                except OSError as e:
                    return self._send(502, ("không kết nối được máy tính: %s" % e).encode())
                self.send_response(r.status if hasattr(r, "status") else r.code)
                self.send_header("Content-Type", r.headers.get("Content-Type", "application/octet-stream"))
                if r.headers.get("Content-Length"):
                    self.send_header("Content-Length", r.headers["Content-Length"])
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                shutil.copyfileobj(r, self.wfile)
                return
            if not self.path.startswith("/app/"):
                return self._send(404, b"")
            rel = self.path[5:].split("?", 1)[0] or "index.html"
            p = os.path.normpath(os.path.join(web, rel))
            if not p.startswith(web) or not os.path.isfile(p):
                return self._send(404, b"")
            with open(p, "rb") as f:
                self._send(200, f.read(), MS.TYPES.get(os.path.splitext(p)[1], "application/octet-stream"))
    return H


def main():
    if not os.path.exists(SRC) or not os.path.isdir(GAME):
        print("bỏ qua: cần trận thật và thư mục game:", SRC, GAME)
        return
    raw = os.path.join(OUT, "Raw")
    web = os.path.join(OUT, "Web")
    os.makedirs(raw, exist_ok=True)
    os.makedirs(web, exist_ok=True)
    src = os.path.join(raw, os.path.basename(SRC))
    if not os.path.exists(src):
        shutil.copy2(SRC, src)
    out = os.path.join(web, os.path.splitext(os.path.basename(src))[0] + f".v{WE.WEB_VERSION}.aoeweb")
    if not os.path.exists(out) or os.path.getmtime(out) < os.path.getmtime(WE.__file__):
        print("chuyển:", WE.export_match(src, out, GAME))
    old = os.path.getmtime(out) - 3600
    os.utime(src, (old, old))

    pc, _ = MS.serve(raw, GAME, port=0, token="t", cache=web, host="127.0.0.1", log=print)
    threading.Thread(target=pc.serve_forever, daemon=True).start()
    shell = ThreadingHTTPServer(("127.0.0.1", 0), shell_handler())
    shell.daemon_threads = True
    threading.Thread(target=shell.serve_forever, daemon=True).start()
    origin = f"http://{HOST}:{shell.server_address[1]}"
    b = Browser(412, 860, args=[f"--host-resolver-rules=MAP {HOST} 127.0.0.1", "--no-proxy-server",
                                f"--unsafely-treat-insecure-origin-as-secure={origin}"])
    name = os.path.basename(src)
    pc_up = True
    port = pc.server_address[1]
    try:
        # vỏ app giả: máy quét QR trả nội dung đặt sẵn trong localStorage
        b.call("Page.addScriptToEvaluateOnNewDocument", source="""window.AoEApp = {
            scanQr() { setTimeout(() => window.onQrResult(localStorage.getItem('test.qr'), null), 50); },
            versionCode() { return 1; } };""")
        # 1. kết nối
        b.goto(origin + "/app/index.html")
        b.wait("!document.querySelector('#setup').hidden", timeout=30)
        assert not b.eval("document.querySelector('#scan-qr').hidden"), "phải có nút Quét mã QR trong app"
        assert b.eval("!!self.caches && isSecureContext"), "trang phải là nguồn an toàn để có Cache Storage"
        b.eval("document.querySelector('#pc-addr').value = '127.0.0.1:1/t';"
               "document.querySelector('#setup-form').requestSubmit(); 1")
        b.wait("document.querySelector('#setup-msg').className.includes('err') &&"
               "document.querySelector('#setup-msg').textContent.includes('Không kết nối')", timeout=30)
        b.eval("localStorage.setItem('test.qr', 'WIFI:S:nha;;'); document.querySelector('#scan-qr').click(); 1")
        b.wait("document.querySelector('#setup-msg').textContent.includes('không phải của AoE-MapCap')", timeout=10)
        b.eval(f"localStorage.setItem('test.qr', 'HTTP://127.0.0.1:{port}/T/'); document.querySelector('#scan-qr').click(); 1")
        b.wait("!document.querySelector('#list').hidden && document.querySelectorAll('.match').length", timeout=60)
        assert b.eval("localStorage.getItem('aoe.pc')") == f"127.0.0.1:{port}/t"
        assert not b.eval("document.querySelector('#pc-btn').hidden")
        b.screenshot(os.path.join(OUT, "app_list.png"))
        print("màn hình kết nối: địa chỉ sai báo lỗi, mã QR lạ báo lỗi, quét mã máy tính -> danh sách trận: OK")

        # 2. mở trận, lưu trên máy
        b.eval("document.querySelector('.match').click(); 1")
        b.wait("location.search.startsWith('?m=') && window.aoeViewer && document.querySelector('#v-status').hidden",
               timeout=180)
        b.screenshot(os.path.join(OUT, "app_viewer.png"))
        keys = b.eval("(async () => (await (await caches.open('aoe-web-1')).keys())"
                      ".map(r => new URL(r.url).pathname))()")
        enc = urllib.request.quote(name, safe="")
        assert set(keys) >= {"/s/sprites", "/m/" + enc, "/i/" + enc}, keys
        info = b.eval(f"(async () => (await (await caches.open('aoe-web-1')).match('/i/{enc}')).json())()")
        assert info["file"] == name and info["info"] and info["info"].get("players"), info
        b.eval("document.querySelector('#back').click(); 1")
        b.wait("!document.querySelector('#list').hidden && !!document.querySelector('.match .saved')", timeout=60)
        print("mở trận, lưu gói hình + trận trên máy, quay lại thấy 'đã lưu': OK")

        # mở app từ trình duyệt: aoemapcap://pair?a=... -> MainActivity tải trang ?pair=...
        b.eval("localStorage.setItem('aoe.pc', '10.9.9.9:1/zzz'); 1")
        b.goto(origin + "/app/index.html?pair=" + urllib.request.quote(f"127.0.0.1:{port}/t", safe=""))
        b.wait("!document.querySelector('#list').hidden && document.querySelectorAll('.match').length"
               " && location.search === ''", timeout=60)
        assert b.eval("localStorage.getItem('aoe.pc')") == f"127.0.0.1:{port}/t"
        print("mở app từ trình duyệt (?pair=): đổi địa chỉ máy tính: OK")

        # quét QR bằng camera thường -> trang của máy tính trong Chrome Android: mời tải / mở app
        b.call("Emulation.setUserAgentOverride",
               userAgent="Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/130.0 Mobile Safari/537.36")
        b.goto(f"http://127.0.0.1:{port}/t/")
        b.wait("!document.querySelector('#app-banner').hidden && document.querySelectorAll('.match').length", timeout=60)
        href = b.eval("document.querySelector('#app-open').href")
        assert href.startswith(f"intent://pair?a=127.0.0.1%3A{port}%2Ft#Intent;scheme=aoemapcap;"
                               "package=io.github.trandinhnamuet.aoemapcap;"), href
        b.screenshot(os.path.join(OUT, "browser_banner.png"))
        print("trình duyệt Android: nút Tải app / Mở trong app (intent đúng địa chỉ): OK")

        # 3. máy tính tắt
        pc.shutdown()
        pc.server_close()
        pc_up = False
        b.goto(origin + "/app/index.html")
        b.wait("!document.querySelector('#list-note').hidden && document.querySelectorAll('.match').length", timeout=60)
        b.screenshot(os.path.join(OUT, "app_offline.png"))
        b.eval("document.querySelector('.match').click(); 1")
        b.wait("window.aoeViewer && document.querySelector('#v-status').hidden", timeout=120)
        res = b.eval("aoeViewer.selftest()")
        assert res["units"][-1] > 0, res
        print("máy tính tắt: danh sách trận đã lưu, mở trận từ bộ nhớ điện thoại: OK")
        assert not [c for c in b.console if c.startswith("EXC")], b.console
    finally:
        b.close()
        if pc_up:
            pc.shutdown()
        shell.shutdown()
    print("OK test_mobile_app")


if __name__ == "__main__":
    main()
