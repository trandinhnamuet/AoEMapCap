"""Máy chủ tạm trong mạng nhà cho bản thử trình xem trên điện thoại: phục vụ trang mobile/web, danh sách trận,
trận đã chuyển sang .aoeweb (chuyển lần đầu khi điện thoại mở) và gói hình game.

    python -m mapcap.mobile_server [--folder=Video\\Raw] [--game-dir=...] [--port=8765]

Địa chỉ có một mã ngẫu nhiên (http://<ip máy>:8765/<mã>/) để máy khác trong mạng không đoán được. Gói hình là đồ hoạ
từ bộ cài game của chính người dùng: chỉ đi trong mạng nhà, không lên máy chủ nào.
"""
import json
import mimetypes
import os
import queue
import secrets
import socket
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .webexport import WEB_VERSION, export_match, export_sprites

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml"}


def web_root():
    base = getattr(sys, "_MEIPASS", ROOT)
    return os.path.join(base, "mobile", "web")


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))          # UDP: không gửi gói nào, chỉ để hệ điều hành chọn card mạng
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class Exporter:
    """Hàng đợi chuyển trận (một luồng: chuyển tốn CPU, không chạy song song với nhau)."""

    def __init__(self, folder, cache, game_dir, log):
        self.folder, self.cache, self.game_dir, self.log = folder, cache, game_dir, log
        os.makedirs(cache, exist_ok=True)
        self.q = queue.Queue()
        self.state = {}               # tên file -> {"progress", "error"}
        self.lock = threading.Lock()
        threading.Thread(target=self._run, daemon=True, name="web-export").start()

    def out_path(self, name):
        return os.path.join(self.cache, os.path.splitext(name)[0] + f".v{WEB_VERSION}.aoeweb")

    def ready(self, name):
        src = os.path.join(self.folder, name)
        out = self.out_path(name)
        try:
            return os.path.getmtime(out) >= os.path.getmtime(src)
        except OSError:
            return False

    def request(self, name):
        with self.lock:
            st = self.state.get(name)
            if st is None or st.get("error"):
                st = self.state[name] = {"progress": 0.0, "error": None}
                self.q.put(name)
            return dict(st)

    def _run(self):
        while True:
            name = self.q.get()
            st = self.state[name]
            try:
                if not self.ready(name):
                    export_match(os.path.join(self.folder, name), self.out_path(name), self.game_dir, log=self.log,
                                 progress=lambda f: st.__setitem__("progress", 0.1 + 0.85 * f))
                st["progress"] = 1.0
            except Exception as e:  # noqa: BLE001
                self.log(f"lỗi chuyển {name}: {e!r}")
                st["error"] = str(e) or repr(e)
            finally:
                with self.lock:
                    if not st.get("error"):
                        self.state.pop(name, None)

    def sprites(self):
        p = os.path.join(self.cache, "sprites.pack")
        with self.lock:
            if not os.path.exists(p):
                export_sprites(self.game_dir, p)
        return p


def make_handler(token, folder, exporter, log):
    prefix = f"/{token}/"

    class H(BaseHTTPRequestHandler):
        server_version = "AoE-MapCap"

        def log_message(self, fmt, *args):
            pass

        def _send(self, code, body, ctype="application/json", extra=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _file(self, path, ctype, cache=False):
            size = os.path.getsize(path)
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "max-age=86400" if cache else "no-cache")
            self.end_headers()
            with open(path, "rb") as f:
                while True:
                    b = f.read(1 << 20)
                    if not b:
                        break
                    self.wfile.write(b)

        def _match_name(self, qs):
            name = os.path.basename((qs.get("f") or [""])[0])
            if not name.lower().endswith(".aoerec") or not os.path.isfile(os.path.join(folder, name)):
                return None
            return name

        def do_GET(self):  # noqa: N802
            u = urllib.parse.urlsplit(self.path)
            if u.path == f"/{token}":
                self.send_response(302)
                self.send_header("Location", prefix)
                self.end_headers()
                return
            if not u.path.startswith(prefix):
                return self._send(404, b"", "text/plain")
            rel = u.path[len(prefix):]
            qs = urllib.parse.parse_qs(u.query)
            try:
                if rel == "api/matches":
                    return self._send(200, list_matches(folder))
                if rel == "api/match":
                    name = self._match_name(qs)
                    if name is None:
                        return self._send(404, {"error": "không thấy trận"})
                    if exporter.ready(name):
                        if "check" in qs:
                            return self._send(200, {"ready": True})
                        return self._file(exporter.out_path(name), "application/octet-stream")
                    st = exporter.request(name)
                    return self._send(200, {"ready": False, "progress": st["progress"], "error": st["error"]})
                if rel == "api/sprites":
                    return self._file(exporter.sprites(), "application/octet-stream", cache=True)
                rel = rel or "index.html"
                base = os.path.realpath(web_root())
                path = os.path.realpath(os.path.join(base, *rel.split("/")))
                if not path.startswith(base + os.sep) or not os.path.isfile(path):
                    return self._send(404, b"", "text/plain")
                ext = os.path.splitext(path)[1].lower()
                return self._file(path, TYPES.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream")
            except (ConnectionError, BrokenPipeError):
                pass
            except Exception as e:  # noqa: BLE001
                log(f"lỗi máy chủ {rel}: {e!r}")
                try:
                    self._send(500, {"error": str(e)})
                except OSError:
                    pass

    return H


def list_matches(folder):
    import time

    from replay.library import Library
    lib = Library(folder)
    out = []
    for p in lib.files():
        try:
            if time.time() - os.path.getmtime(p) < 60:
                continue                                  # trận đang ghi
            info = lib.info(p)
        except Exception:  # noqa: BLE001
            continue
        if info and "error" not in info and info.get("frames", 0) > 0:
            out.append({"file": os.path.basename(p), "info": info})
    lib.save()
    return out


TOKEN_CHARS = "abcdefghjkmnpqrstuvwxyz23456789"   # bỏ i l o 0 1 cho dễ đọc / gõ trên điện thoại


def stable_token(cache):
    """Mã 6 ký tự, lưu trong thư mục bộ đệm: app điện thoại nhớ địa chỉ, chạy lại máy chủ không phải nhập lại."""
    p = os.path.join(cache, "token.txt")
    try:
        with open(p, encoding="ascii") as f:
            t = f.read().strip()
        if len(t) >= 6 and all(c in TOKEN_CHARS for c in t):
            return t
    except OSError:
        pass
    t = "".join(secrets.choice(TOKEN_CHARS) for _ in range(6))
    os.makedirs(cache, exist_ok=True)
    with open(p, "w", encoding="ascii") as f:
        f.write(t)
    return t


def serve(folder, game_dir, port=8765, token=None, log=print, cache=None, host="0.0.0.0"):
    cache = cache or os.path.join(os.path.dirname(os.path.abspath(folder)), "Web")
    token = token or stable_token(cache)
    exporter = Exporter(folder, cache, game_dir, log)
    srv = ThreadingHTTPServer((host, port), make_handler(token, folder, exporter, log))
    srv.daemon_threads = True
    url = f"http://{lan_ip() if host == '0.0.0.0' else host}:{srv.server_address[1]}/{token}/"
    return srv, url


def main(argv=None):
    import argparse

    from .gamefiles import GAME_DIR_CANDIDATES, valid_game_dir
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", default=os.path.join(ROOT, "Video", "Raw"))
    ap.add_argument("--game-dir", default=None)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--token", default=None)
    ap.add_argument("--host", default="0.0.0.0", help="127.0.0.1: chỉ máy này (thử nghiệm)")
    ap.add_argument("--cache", default=None)
    a = ap.parse_args(argv)
    game_dir = a.game_dir or next((d for d in GAME_DIR_CANDIDATES if valid_game_dir(d)), None)
    if not game_dir:
        print("không thấy thư mục game, dùng --game-dir=")
        return 2
    srv, url = serve(a.folder, game_dir, a.port, a.token, cache=a.cache, host=a.host)
    print("Mở trên điện thoại (cùng Wi-Fi):", url, flush=True)
    print("Trong app AoE-MapCap nhập:", url.split("//", 1)[1].rstrip("/"), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
