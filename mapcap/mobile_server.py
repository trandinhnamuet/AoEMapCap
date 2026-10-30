"""Máy chủ trong mạng nhà cho app / trình xem trên điện thoại: phục vụ trang mobile/web, danh sách trận,
trận đã chuyển sang .aoeweb (chuyển lần đầu khi điện thoại mở) và gói hình game.

App Windows bật / tắt bằng trang "Điện thoại" (PhoneServer, từ v14); chạy riêng để thử:
    python -m mapcap.mobile_server [--folder=Video\\Raw] [--game-dir=...] [--port=8765]

Địa chỉ có một mã ngẫu nhiên (http://<ip máy>:8765/<mã>/) để máy khác trong mạng không đoán được. Khác mạng (từ v16):
PhoneServer giữ thêm kết nối tới trạm chuyển tiếp Cloudflare (relay_client), mã QR trỏ tới trang trên trạm. Gói hình là
đồ hoạ từ bộ cài game của chính người dùng: chỉ đi từ máy tính sang điện thoại (qua trạm khi khác mạng), không lưu ở
máy chủ nào.
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

    def __init__(self, folder, cache, game_dir, log, busy=None):
        self.folder, self.cache, self.game_dir, self.log = folder, cache, game_dir, log
        self.busy = busy or (lambda: False)      # đang ghi trận: hoãn chuyển (tốn CPU) tới khi hết trận
        self.stopped = False
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
                st = self.state[name] = {"progress": 0.0, "error": None, "waiting": False}
                self.q.put(name)
            return dict(st)

    def stop(self):
        self.stopped = True
        self.q.put(None)

    def _run(self):
        import time
        while True:
            name = self.q.get()
            if name is None:
                return
            st = self.state[name]
            try:
                while self.busy() and not self.stopped:
                    st["waiting"] = True
                    time.sleep(3)
                st["waiting"] = False
                if self.stopped:
                    return
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
                    return self._send(200, {"ready": False, "progress": st["progress"], "error": st["error"],
                                            "waiting": st.get("waiting", False)})
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


class _Server(ThreadingHTTPServer):
    """Cổng độc quyền: trên Windows SO_REUSEADDR (mặc định của HTTPServer) cho hai máy chủ cùng nghe một cổng."""
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def serve(folder, game_dir, port=8765, token=None, log=print, cache=None, host="0.0.0.0", busy=None):
    cache = cache or os.path.join(os.path.dirname(os.path.abspath(folder)), "Web")
    token = token or stable_token(cache)
    exporter = Exporter(folder, cache, game_dir, log, busy)
    try:
        srv = _Server((host, port), make_handler(token, folder, exporter, log))
    except OSError:
        exporter.stop()
        raise
    srv.exporter = exporter
    srv.cache, srv.token = cache, token
    url = f"http://{lan_ip() if host == '0.0.0.0' else host}:{srv.server_address[1]}/{token}/"
    return srv, url


FIREWALL_RULE = "AoE-MapCap (điện thoại, mạng nhà)"


def allow_firewall(log=print):
    """Exe (chạy quyền Admin) tự thêm luật tường lửa: chỉ máy cùng mạng (LocalSubnet) được vào, mọi loại mạng (Wi-Fi nhà
    hay bị Windows đặt là "Công cộng"). Không có luật thì Windows chặn điện thoại hoặc hiện hộp hỏi. Chạy từ mã nguồn:
    bỏ qua (python.exe dùng hộp hỏi của Windows)."""
    if not getattr(sys, "frozen", False) or os.name != "nt":
        return False
    import subprocess
    exe = sys.executable
    nw = 0x08000000                                     # CREATE_NO_WINDOW
    try:
        cur = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule", f"name={FIREWALL_RULE}", "verbose"],
                             capture_output=True, text=True, errors="replace", creationflags=nw, timeout=15).stdout
        if exe.lower() in cur.lower():
            return True
        subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={FIREWALL_RULE}"],
                       capture_output=True, creationflags=nw, timeout=15)
        r = subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule", f"name={FIREWALL_RULE}", "dir=in",
                            "action=allow", f"program={exe}", "protocol=TCP", "remoteip=localsubnet", "profile=any",
                            "enable=yes"], capture_output=True, text=True, errors="replace", creationflags=nw, timeout=15)
        if r.returncode != 0:
            log("tường lửa: không thêm được luật cho điện thoại: " + (r.stdout or r.stderr).strip()[:200])
            return False
        log("tường lửa: đã cho phép điện thoại cùng mạng kết nối")
        return True
    except (OSError, subprocess.SubprocessError) as e:
        log(f"tường lửa: {e}")
        return False


class PhoneServer:
    """Máy chủ cho điện thoại do app Windows bật / tắt. Cổng 8765 (bận thì 8766..8774); mã cố định trong
    <thư mục Web>\\token.txt nên địa chỉ không đổi giữa các lần bật (trừ khi IP máy đổi)."""

    PORTS = range(8765, 8775)

    def __init__(self, log=print, on_relay=None):
        self.log = log
        self.on_relay = on_relay or (lambda s: None)   # trạng thái trạm chuyển tiếp đổi (gọi từ luồng khác)
        self.srv = None
        self.url = None
        self.folder = None
        self.relay = None
        self.room = None

    @property
    def running(self):
        return self.srv is not None

    def start(self, folder, game_dir, busy=None, cache=None):
        self.stop()
        last = None
        for port in self.PORTS:
            try:
                srv, url = serve(folder, game_dir, port, log=self.log, cache=cache, busy=busy)
                break
            except OSError as e:
                last = e
        else:
            raise OSError(f"không mở được cổng {self.PORTS.start}-{self.PORTS.stop - 1}: {last}")
        threading.Thread(target=srv.serve_forever, daemon=True, name="phone-server").start()
        threading.Thread(target=allow_firewall, args=(self.log,), daemon=True).start()
        self.srv, self.url, self.folder = srv, url, folder
        from .relay_client import RelayClient, stable_room
        self.room = stable_room(srv.cache)
        self.relay = RelayClient(self.room, f"http://127.0.0.1:{srv.server_address[1]}/{srv.token}/", self.log,
                                 self.on_relay).start()
        return url

    def stop(self):
        relay, self.relay = self.relay, None
        if relay is not None:
            relay.stop()
        srv, self.srv, self.url = self.srv, None, None
        if srv is not None:
            srv.shutdown()
            srv.server_close()
            srv.exporter.stop()

    def address(self):
        """Địa chỉ ngắn để nhập tay trong app: 192.168.1.5:8765/abc123."""
        return self.url.split("//", 1)[1].rstrip("/") if self.url else ""

    def pair_url(self):
        """Nội dung mã QR: trang trên trạm chuyển tiếp + mã phòng + địa chỉ mạng nhà (app thử mạng nhà trước)."""
        from .relay_client import pair_url
        return pair_url(self.room, self.address()) if self.url else ""

    def relay_state(self):
        return self.relay.state if self.relay is not None else "offline"


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
