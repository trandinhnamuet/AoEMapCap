"""Thống kê sử dụng: mỗi lần mở app (có mạng) gửi một lượt lên Cloudflare Worker (telemetry/ trong repo).

Gửi: mã máy (UUID ngẫu nhiên tạo lần đầu, lưu %APPDATA%\\AoE-MapCap\\install_id để tải lại zip / tự cập nhật vẫn giữ),
app (mapcap / replay), phiên bản, loại (open = mở app, match = ghi xong một trận), tên người chơi (từ v7: nickname
của người ghi trong trận đã ghi gần nhất, nhớ ở %APPDATA%\\AoE-MapCap\\player_name; chưa biết thì rỗng). IP do phía
nhận ghi; app kết nối bằng IPv4 để IP ghi lại là IPv4. Không gửi nội dung trận đấu hay gì khác.
Chạy ngầm, chờ tối đa 6 giây; không mạng / lỗi thì bỏ qua. Tắt trong Cài đặt ("Gửi thống kê sử dụng") hoặc biến môi
trường AOEMAPCAP_TELEMETRY=0. Chạy từ mã nguồn (không đóng gói) thì không gửi trừ khi AOEMAPCAP_TELEMETRY=1.
AOEMAPCAP_TELEMETRY_URL thay địa chỉ nhận (kiểm thử).
"""
import http.client
import json
import os
import socket
import ssl
import sys
import threading
import urllib.parse
import uuid

from .version import APP_VERSION

ENDPOINT = "https://aoe-mapcap-telemetry.aoemapcap.workers.dev/v1/e"   # Cloudflare Worker (telemetry/)
TIMEOUT = 6


def endpoint():
    return os.environ.get("AOEMAPCAP_TELEMETRY_URL") or ENDPOINT


def enabled(cfg_enabled=True):
    env = os.environ.get("AOEMAPCAP_TELEMETRY")
    if env is not None:
        return env.strip() not in ("0", "false", "no", "")
    if not getattr(sys, "frozen", False):
        return False                            # chạy từ mã nguồn / test: không làm bẩn số liệu thật
    return bool(cfg_enabled)


def flag_from_settings(path):
    """Cờ "telemetry" trong Video\\_settings.ini (AoE-Replay chạy riêng không nạp Config của AoE-MapCap)."""
    try:
        import configparser
        cp = configparser.ConfigParser()
        cp.read(path, encoding="utf-8")
        v = cp.get("mapcap", "telemetry", fallback="1")
        return v.strip().lower() in ("1", "true", "yes", "on")
    except Exception:  # noqa: BLE001
        return True


def _name_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "AoE-MapCap", "player_name")


def name_from_header(hdr):
    """Tên (nickname) của người ghi trận từ header .aoerec: người chơi ở cur_player_index."""
    try:
        cur = int(hdr.get("cur_player_index", -1))
        for p in hdr.get("players") or ():
            if int(p[0]) == cur:
                return str(p[3] or "").strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


def remember_name(name):
    name = (name or "").strip()[:40]
    if not name:
        return
    try:
        os.makedirs(os.path.dirname(_name_path()), exist_ok=True)
        with open(_name_path(), "w", encoding="utf-8") as f:
            f.write(name)
    except OSError:
        pass


def last_name(raw_dir=None):
    """Tên người chơi đã nhớ; chưa có thì lấy từ trận ghi mới nhất trong raw_dir (và nhớ lại); không có thì ""."""
    try:
        with open(_name_path(), encoding="utf-8") as f:
            v = f.read().strip()
        if v:
            return v
    except OSError:
        pass
    if raw_dir and os.path.isdir(raw_dir):
        try:
            from .rawrec import read_header
            files = sorted((os.path.join(raw_dir, f) for f in os.listdir(raw_dir) if f.endswith(".aoerec")),
                           key=os.path.getmtime, reverse=True)
            for p in files[:5]:
                v = name_from_header(read_header(p) or {})
                if v:
                    remember_name(v)
                    return v
        except Exception:  # noqa: BLE001
            pass
    return ""


def _id_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "AoE-MapCap", "install_id")


def install_id():
    """Mã máy: đọc từ %APPDATA%\\AoE-MapCap\\install_id, chưa có thì tạo UUID ngẫu nhiên và lưu."""
    p = _id_path()
    try:
        with open(p, encoding="ascii") as f:
            v = f.read().strip()
        uuid.UUID(v)
        return v
    except (OSError, ValueError):
        pass
    v = str(uuid.uuid4())
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="ascii") as f:
            f.write(v)
    except OSError:
        pass                                    # không ghi được: vẫn gửi, lần sau sẽ thành mã khác
    return v


class _IPv4HTTPSConnection(http.client.HTTPSConnection):
    """Kết nối HTTPS chỉ qua IPv4 (để phía nhận ghi được IPv4), vẫn kiểm chứng chỉ theo tên miền."""

    def connect(self):
        infos = socket.getaddrinfo(self.host, self.port, socket.AF_INET, socket.SOCK_STREAM)
        err = None
        for _fam, _t, _p, _c, addr in infos:
            try:
                sock = socket.create_connection(addr, self.timeout)
                break
            except OSError as e:
                err = e
        else:
            raise err or OSError("không có địa chỉ IPv4")
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _post(url, payload, timeout=TIMEOUT):
    u = urllib.parse.urlsplit(url)
    data = json.dumps(payload).encode("utf-8")
    headers = {"content-type": "application/json", "user-agent": f"AoE-MapCap/{APP_VERSION}"}
    if u.scheme == "https":
        conn = _IPv4HTTPSConnection(u.hostname, u.port or 443, timeout=timeout, context=ssl.create_default_context())
    else:
        conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=timeout)
    try:
        conn.request("POST", u.path or "/", body=data, headers=headers)
        r = conn.getresponse()
        r.read(4096)
        return r.status
    finally:
        conn.close()


def send(app, ev="open", cfg_enabled=True, log=None, wait=False, name=None, raw_dir=None):
    """Gửi một lượt (chạy ngầm). app: "mapcap" | "replay"; ev: "open" | "match". name: tên người chơi (None = tên đã
    nhớ, hoặc từ trận mới nhất trong raw_dir). wait=True: chờ xong (kiểm thử)."""
    if name:
        remember_name(name)
    if not enabled(cfg_enabled):
        return None

    def job():
        try:
            nm = name or last_name(raw_dir)
            st = _post(endpoint(), {"id": install_id(), "app": app, "v": APP_VERSION, "ev": ev, "name": nm})
            if log and st != 200:
                log(f"thống kê: máy chủ trả {st}")
        except Exception as e:  # noqa: BLE001  - không mạng / bị chặn: bỏ qua, không ảnh hưởng app
            if log:
                log(f"thống kê: không gửi được ({e.__class__.__name__})")
    t = threading.Thread(target=job, name="telemetry", daemon=True)
    t.start()
    if wait:
        t.join(TIMEOUT + 2)
    return t
