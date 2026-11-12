"""Báo cáo trận có hack (mapcap/report.py + telemetry/ /v1/report, /api/reports, /api/report/file, /api/report/update)
qua Worker CỤC BỘ (R2 + D1 giả lập, không đụng máy chủ thật):

    cd telemetry
    npx wrangler d1 execute aoe-mapcap-telemetry --local --persist-to <tmp> --file schema.sql -y
    npx wrangler dev --local --persist-to <tmp> --port 8799 --var STATS_PASSWORD:local-test-pw-123
    python tests/test_report.py [http://127.0.0.1:8799] [file.aoerec]

Kiểm: gửi file thật (có tiến độ), danh sách cho admin có đủ thông tin + vi phạm app tự phát hiện, tải lại đúng từng
byte, admin đánh dấu, sai mật khẩu bị chặn, file không phải .aoerec bị từ chối, giới hạn số báo cáo mỗi ngày.
"""
import glob
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8799"
PW = "local-test-pw-123"
os.environ["AOEMAPCAP_REPORT_URL"] = BASE + "/v1/report"
os.environ["AOEMAPCAP_TELEMETRY"] = "0"

from mapcap import report  # noqa: E402
from replay.library import match_info  # noqa: E402


def api(path, data=None, pw=PW):
    req = urllib.request.Request(BASE + path, data=data, headers={"authorization": "Bearer " + pw,
                                                                    "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.read(), dict(r.headers)


def main():
    path = sys.argv[2] if len(sys.argv) > 2 else sorted(glob.glob(os.path.join(ROOT, "Video", "Raw", "*.aoerec")),
                                                        key=os.path.getmtime)[-1]
    info = match_info(path)
    info = dict(info, hack=[{"player": 2, "name": "Nghi Pham", "rule": "L3", "label": "Xoá quân / nhà của người khác",
                             "t": 61000, "detail": "xoá vật thể #123 của P1", "count": 2}])
    prog = []
    rid = report.upload(path, info, suspect="Nghi Pham", note="xoá nhà chính phút 1", progress=lambda a, b: prog.append((a, b)))
    size = os.path.getsize(path)
    assert prog and prog[-1] == (size, size), prog[-3:]
    print(f"gửi báo cáo #{rid}: {size / 1e6:.1f} MB, {len(prog)} lượt tiến độ: OK")

    st, body, _ = api("/api/reports")
    j = json.loads(body)
    r = next(x for x in j["reports"] if x["id"] == rid)
    assert r["suspect"] == "Nghi Pham" and r["note"] == "xoá nhà chính phút 1" and r["hasFile"] and r["size"] == size, r
    assert r["meta"]["hack"][0]["label"].startswith("Xoá") and r["meta"]["players"] and r["meta"]["map"], r["meta"]
    assert j["r2"] and j["storedBytes"] >= size
    print("danh sách admin: người nghi, ghi chú, người chơi, map, vi phạm app phát hiện, cỡ file: OK")

    st, body, hd = api(f"/api/report/file?id={rid}")
    assert hashlib.sha256(body).hexdigest() == hashlib.sha256(open(path, "rb").read()).hexdigest()
    assert "attachment" in hd.get("Content-Disposition", hd.get("content-disposition", ""))
    print("admin tải file: đúng từng byte: OK")

    api("/api/report/update", json.dumps({"id": rid, "status": "hack", "admin_note": "P2 dùng lệnh xoá"}).encode())
    r = next(x for x in json.loads(api("/api/reports")[1])["reports"] if x["id"] == rid)
    assert r["status"] == "hack" and r["admin_note"] == "P2 dùng lệnh xoá", r
    print("admin đánh dấu Có hack + ghi chú: OK")

    for p in ("/api/reports", f"/api/report/file?id={rid}"):
        try:
            api(p, pw="sai-mat-khau")
            raise AssertionError("sai mật khẩu vẫn vào được " + p)
        except urllib.error.HTTPError as e:
            assert e.code == 401, e.code
    print("sai mật khẩu: 401: OK")

    bad = os.path.join(ROOT, "Video", "_test", "not_a_rec.aoerec")
    os.makedirs(os.path.dirname(bad), exist_ok=True)
    open(bad, "wb").write(b"XXXXXXXX" + os.urandom(5000))
    try:
        report.upload(bad, info)
        raise AssertionError("file không phải .aoerec vẫn được nhận")
    except report.ReportError as e:
        assert "aoerec" in str(e), e
    print("file không phải .aoerec: bị từ chối (và xoá khỏi R2): OK")

    n_ok = 1
    small = os.path.join(ROOT, "Video", "_test", "small.aoerec")
    open(small, "wb").write(open(path, "rb").read(200_000))
    err = None
    for _ in range(6):
        try:
            report.upload(small, info)
            n_ok += 1
        except report.ReportError as e:
            err = str(e)
            break
    assert n_ok == 5 and err and "mỗi ngày" in err, (n_ok, err)
    print(f"giới hạn: máy gửi được {n_ok} báo cáo / ngày, lần sau báo '{err}': OK")
    for f in (bad, small):
        os.remove(f)
    print("OK test_report")


if __name__ == "__main__":
    main()
