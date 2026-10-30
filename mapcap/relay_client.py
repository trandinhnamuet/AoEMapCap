"""Máy tính <-> trạm chuyển tiếp Cloudflare (relay/src/index.js): điện thoại khác mạng (4G, Wi-Fi khác) vẫn lấy được
danh sách trận, trận và gói hình từ máy chủ điện thoại (mobile_server) trên máy này.

- Máy tính mở một WebSocket ra ngoài tới wss://<trạm>/r/<phòng>?role=pc (không mở cổng, không cần tường lửa) và giữ
  nó suốt lúc bật "Cho điện thoại xem trận"; rớt thì nối lại (2 s .. 60 s).
- Phòng = mã 24 ký tự bí mật trong <thư mục Web>\\relay.txt, chỉ có trong mã QR. Ai có mã đọc được đúng những gì máy chủ
  điện thoại cho (api/...), như người cùng mạng có địa chỉ.
- Điện thoại gửi {c, r, p: "api/...", k: tín dụng}; máy tính gọi máy chủ điện thoại cục bộ (127.0.0.1) rồi gửi lại
  từng khung nhị phân [u32 c][u32 r][u8 loại][dữ liệu]: 1 = đầu (JSON status / type / size), 2 = 64 KB dữ liệu (mỗi
  khung tốn 1 tín dụng; điện thoại cấp thêm bằng {r, k}), 3 = hết, 4 = lỗi (JSON). Nhờ tín dụng, trạm chỉ giữ tạm
  vài trăm KB dù điện thoại tải chậm.
"""
import http.client
import json
import os
import secrets
import select
import struct
import threading
import time
import urllib.parse

from .version import APP_VERSION

RELAY = "https://aoe-mapcap-relay.aoemapcap.workers.dev"
ROOM_CHARS = "abcdefghjkmnpqrstuvwxyz23456789"
CHUNK = 64 << 10
PING_EVERY = 25                 # giây: giữ kết nối (trạm trả "pong" mà không thức dậy)
IO_TIMEOUT = 60                 # giây: một lần gửi / đọc trên socket không xong thì coi như mất kết nối
CREDIT_WAIT = 120               # giây: điện thoại không cấp thêm tín dụng -> bỏ luồng

HEAD, DATA, END, ERR = 1, 2, 3, 4


def relay_base():
    from .updater import env_override            # bản phát hành bỏ qua biến môi trường kiểm thử
    return (env_override("AOEMAPCAP_RELAY") or RELAY).rstrip("/")


def stable_room(cache):
    """Mã phòng 24 ký tự, cố định giữa các lần bật (điện thoại đã ghép đôi không phải quét lại)."""
    p = os.path.join(cache, "relay.txt")
    try:
        with open(p, encoding="ascii") as f:
            t = f.read().strip()
        if len(t) >= 20 and all(c in ROOM_CHARS for c in t):
            return t
    except OSError:
        pass
    t = "".join(secrets.choice(ROOM_CHARS) for _ in range(24))
    os.makedirs(cache, exist_ok=True)
    with open(p, "w", encoding="ascii") as f:
        f.write(t)
    return t


def pair_url(room, lan=None):
    """Nội dung mã QR: trang trên trạm (camera thường mở được ở mọi mạng), app đọc r = phòng, l = địa chỉ mạng nhà."""
    q = "r=" + room + ("&l=" + urllib.parse.quote(lan, safe=":/") if lan else "")
    return f"{relay_base()}/#{q}"


class RelayClient:
    """Kết nối thường trực tới trạm; state: "connecting" | "online" | "offline: <lý do>"."""

    def __init__(self, room, local, log=print, on_state=None):
        u = urllib.parse.urlsplit(local)                 # http://127.0.0.1:8765/<mã>/
        self.room, self.host, self.port, self.prefix = room, u.hostname, u.port, u.path
        self.log = log
        self.on_state = on_state or (lambda s: None)
        self.state = "connecting"
        self.stopped = False
        self.ws = None
        # mọi thao tác TLS trên socket (gửi của các luồng yêu cầu, đọc của vòng chính) đi qua khoá này: OpenSSL không
        # cho đọc và ghi cùng lúc trên một kết nối từ hai luồng. Trước v18 vòng chính đọc không khoá trong lúc các
        # luồng gửi khung dữ liệu: bản ghi TLS hỏng, Cloudflare cắt kết nối sau vài chục MB ("Connection to remote
        # host was lost"), yêu cầu đang chạy của điện thoại mất.
        self.send_lock = threading.Lock()
        self.cond = threading.Condition()
        self.streams = {}                                 # (c, r) -> {"credit", "cancel"}
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True, name="relay")
        self.thread.start()
        return self

    def stop(self):
        self.stopped = True
        ws = self.ws
        if ws is not None:
            try:
                ws.abort()                               # đóng socket, không ghi TLS (vòng chính có thể đang đọc)
            except Exception:  # noqa: BLE001
                pass
        self._cancel_all()

    def _set(self, state):
        if state != self.state:
            self.state = state
            self.on_state(state)

    # ---- kết nối ---------------------------------------------------------------------
    def _run(self):
        import websocket

        from .updater import ssl_context
        url = relay_base().replace("https://", "wss://", 1).replace("http://", "ws://", 1) + f"/r/{self.room}?role=pc"
        delay = 2
        while not self.stopped:
            self._set("connecting")
            t0 = time.time()
            try:
                ws = websocket.create_connection(url, timeout=20, sslopt={"context": ssl_context()},
                                                 header=[f"User-Agent: AoE-MapCap/{APP_VERSION}"])
                self.ws = ws
                if self.stopped:
                    ws.close()
                    break
                self._set("online")
                self.log("đã kết nối trạm chuyển tiếp (điện thoại khác mạng xem được)")
                self._loop(ws)
                reason = "mất kết nối trạm"
            except Exception as e:  # noqa: BLE001
                reason = str(e) or type(e).__name__
            finally:
                self.ws = None
                self._cancel_all()
            if self.stopped:
                break
            self._set("offline: " + reason)
            if time.time() - t0 > 30:
                delay = 2
            self.log(f"trạm chuyển tiếp: {reason}; thử lại sau {delay} s")
            end = time.time() + delay
            while time.time() < end and not self.stopped:
                time.sleep(0.25)
            delay = min(delay * 2, 60)

    def _loop(self, ws):
        import websocket
        ws.settimeout(IO_TIMEOUT)
        sock = ws.sock
        pending = getattr(sock, "pending", lambda: 0)          # TLS: byte đã giải mã còn trong bộ đệm
        last = time.time()
        while not self.stopped:
            # chờ có dữ liệu mà không giữ khoá (các luồng vẫn gửi được), rồi đọc trong khoá
            ready = bool(getattr(ws.frame_buffer, "recv_buffer", None)) or pending() > 0
            if not ready:
                ready = bool(select.select([sock], [], [], 1.0)[0])
            op = data = None
            if ready:
                try:
                    with self.send_lock:
                        op, data = ws.recv_data()
                except websocket.WebSocketTimeoutException:
                    pass
            if time.time() - last >= PING_EVERY:
                with self.send_lock:
                    ws.send("ping")
                last = time.time()
            if op is None:
                continue
            if op == websocket.ABNF.OPCODE_CLOSE:
                return
            if op != websocket.ABNF.OPCODE_TEXT:
                continue
            text = data.decode("utf-8", "replace")
            if text == "pong":
                continue
            try:
                j = json.loads(text)
                self._handle(j)
            except (ValueError, TypeError, KeyError):
                continue

    def _send(self, c, r, kind, payload=b""):
        ws = self.ws
        if ws is None:
            raise ConnectionError("mất kết nối trạm")
        with self.send_lock:
            ws.send_binary(struct.pack("<IIB", c, r, kind) + payload)

    # ---- yêu cầu của điện thoại ------------------------------------------------------
    def _handle(self, j):
        c = int(j["c"])
        if j.get("closed"):
            with self.cond:
                for key, st in self.streams.items():
                    if key[0] == c:
                        st["cancel"] = True
                self.cond.notify_all()
            return
        key = (c, int(j["r"]))
        if "p" in j:
            with self.cond:
                self.streams[key] = {"credit": max(1, min(int(j.get("k") or 8), 64)), "cancel": False}
            threading.Thread(target=self._stream, args=(key, str(j["p"])), daemon=True, name="relay-req").start()
            return
        with self.cond:
            st = self.streams.get(key)
            if st is None:
                return
            if j.get("x"):
                st["cancel"] = True
            elif j.get("k"):
                st["credit"] += max(0, min(int(j["k"]), 64))
            self.cond.notify_all()

    def _cancel_all(self):
        with self.cond:
            for st in self.streams.values():
                st["cancel"] = True
            self.cond.notify_all()

    def _wait_credit(self, key):
        with self.cond:
            st = self.streams[key]
            end = time.time() + CREDIT_WAIT
            while st["credit"] <= 0 and not st["cancel"] and not self.stopped:
                left = end - time.time()
                if left <= 0:
                    return False
                self.cond.wait(left)
            if st["cancel"] or self.stopped:
                return False
            st["credit"] -= 1
            return True

    @staticmethod
    def allowed(path):
        """Chỉ API của máy chủ điện thoại; trang web điện thoại đã có sẵn (app / trạm)."""
        p = path.split("?", 1)[0]
        return path.startswith("api/") and ".." not in p and "\\" not in p and "//" not in p

    def _stream(self, key, path):
        c, r = key
        conn = None
        try:
            if not self.allowed(path):
                self._send(c, r, ERR, json.dumps({"error": "đường dẫn không được phép"}).encode())
                return
            conn = http.client.HTTPConnection(self.host, self.port, timeout=600)
            conn.request("GET", self.prefix + path, headers={"User-Agent": "relay"})
            resp = conn.getresponse()
            head = {"status": resp.status, "type": resp.getheader("Content-Type") or "application/octet-stream",
                    "size": int(resp.getheader("Content-Length") or -1)}
            self._send(c, r, HEAD, json.dumps(head).encode())
            while True:
                b = resp.read(CHUNK)
                if not b:
                    break
                if not self._wait_credit(key):
                    return
                self._send(c, r, DATA, b)
            self._send(c, r, END)
        except Exception as e:  # noqa: BLE001
            try:
                self._send(c, r, ERR, json.dumps({"error": str(e) or type(e).__name__}).encode())
            except Exception:  # noqa: BLE001
                pass
        finally:
            if conn is not None:
                conn.close()
            with self.cond:
                self.streams.pop(key, None)
