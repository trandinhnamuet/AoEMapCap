"""Báo cáo trận có hack: gửi file .aoerec lên máy chủ (Cloudflare Worker telemetry/, lưu ở R2) để admin xem lại
trận, xác định ai hack, hack gì (làm dữ liệu thêm luật cho mapcap/hackcheck). Chỉ gửi khi người dùng bấm "Báo cáo
hack" và xác nhận; gửi: file trận, mã máy (như thống kê), phiên bản, tên trong game, người bị nghi + ghi chú, tóm tắt
trận (người chơi, map, thời lượng, vi phạm app tự phát hiện).

AOEMAPCAP_REPORT_URL thay địa chỉ nhận (kiểm thử; bản phát hành chỉ nhận khi cạnh exe có aoemapcap-test.flag).
"""
import http.client
import json
import os
import time
import urllib.parse

from .version import APP_VERSION

ENDPOINT = "https://aoe-mapcap-telemetry.aoemapcap.workers.dev/v1/report"
MAX_BYTES = 95 * 1024 * 1024          # máy chủ nhận tối đa (Worker gói miễn phí: thân request <= 100 MB)
CHUNK = 256 * 1024


class ReportError(Exception):
    pass


def endpoint():
    from .updater import env_override
    return env_override("AOEMAPCAP_REPORT_URL") or ENDPOINT


def build_meta(info):
    """Tóm tắt trận (từ replay.library.match_info) gửi kèm, giới hạn cỡ để vừa tham số URL."""
    from replay.library import fmt_duration
    hack = [{"name": str(e.get("name", ""))[:40], "label": str(e.get("label", ""))[:60], "rule": e.get("rule"),
             "t": e.get("t"), "detail": str(e.get("detail", ""))[:80], "count": e.get("count", 1)}
            for e in (info.get("hack") or [])[:20]]
    return {"map": str(info.get("map", ""))[:60], "duration": fmt_duration(info.get("duration_ms", 0)),
            "result": info.get("result"), "recorder": str(info.get("recorder", ""))[:40], "format": info.get("format"),
            "players": [{"name": str(p.get("name", ""))[:40], "civ": p.get("civ"), "team": p.get("team"),
                         "index": p.get("index")} for p in (info.get("players") or [])[:8]],
            "hack": hack, "cmds": info.get("cmds", 0)}


def upload(path, info, suspect="", note="", progress=None, timeout=60):
    """Gửi file; progress(byte đã gửi, tổng). Trả mã báo cáo. Lỗi -> ReportError (thông điệp tiếng Việt)."""
    from . import telemetry
    size = os.path.getsize(path)
    if size > MAX_BYTES:
        raise ReportError(f"file trận {size / 1e6:.0f} MB, máy chủ chỉ nhận tối đa {MAX_BYTES >> 20} MB")
    q = urllib.parse.urlencode({
        "id": telemetry.install_id(), "v": APP_VERSION, "file": os.path.basename(path)[:120],
        "name": str(info.get("recorder", ""))[:40], "suspect": suspect[:120], "note": note[:1000],
        "meta": json.dumps(build_meta(info), ensure_ascii=False, separators=(",", ":"))})
    u = urllib.parse.urlsplit(endpoint())
    conn_cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
    conn = conn_cls(u.hostname, u.port, timeout=timeout)
    try:
        conn.putrequest("POST", f"{u.path}?{q}")
        conn.putheader("Content-Type", "application/octet-stream")
        conn.putheader("Content-Length", str(size))
        conn.putheader("User-Agent", f"AoE-MapCap/{APP_VERSION}")
        conn.endheaders()
        sent = 0
        with open(path, "rb") as f:
            while True:
                b = f.read(CHUNK)
                if not b:
                    break
                conn.send(b)
                sent += len(b)
                if progress:
                    progress(sent, size)
        r = conn.getresponse()
        body = r.read().decode("utf-8", "replace")
    except PermissionError:
        raise ReportError("trận này đang được ghi: gửi được khi trận kết thúc") from None
    except (OSError, http.client.HTTPException) as e:
        raise ReportError(f"không gửi được (mạng): {e}") from None
    finally:
        conn.close()
    try:
        j = json.loads(body)
    except ValueError:
        j = {}
    if r.status != 200 or not j.get("ok"):
        raise ReportError(j.get("error") or f"máy chủ trả lỗi {r.status}")
    return j.get("id")


# ---- lịch sử báo cáo trên máy (trang "Lịch sử báo cáo"; người dùng 12/11) ---------------------------------------
HISTORY_FILE = "_report_history.json"     # cạnh _settings.ini (thư mục lưu), không gửi đi đâu
HISTORY_MAX = 500


def history_path(folder):
    return os.path.join(folder, HISTORY_FILE)


def load_history(folder):
    """Các báo cáo đã gửi từ máy này, mới nhất trước. File hỏng / chưa có -> []."""
    try:
        with open(history_path(folder), encoding="utf-8") as f:
            items = json.load(f)
        items = [x for x in items if isinstance(x, dict)]
    except (OSError, ValueError, TypeError):
        return []
    return sorted(items, key=lambda x: x.get("ts", 0), reverse=True)


def add_history(folder, rid, path, info, suspect="", note="", auto=""):
    """Ghi thêm một báo cáo vừa gửi thành công (ghi file tạm rồi thay, không mất lịch sử nếu tắt máy giữa chừng)."""
    from replay.library import fmt_duration
    entry = {"id": rid, "ts": int(time.time()), "file": os.path.basename(path), "path": os.path.abspath(path),
             "created": info.get("created", 0), "map": str(info.get("map", "")),
             "duration": fmt_duration(info.get("duration_ms", 0)), "format": info.get("format", ""),
             "players": [str(p.get("name", "")) for p in info.get("players") or []],
             "suspect": suspect, "note": note, "auto": auto}
    items = [entry] + load_history(folder)
    os.makedirs(folder, exist_ok=True)
    tmp = history_path(folder) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items[:HISTORY_MAX], f, ensure_ascii=False, indent=1)
    os.replace(tmp, history_path(folder))
    return entry
