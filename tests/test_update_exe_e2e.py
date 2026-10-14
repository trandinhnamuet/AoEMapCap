"""Thử tự cập nhật bằng exe đã build (dist\\AoE-Replay.exe): tải, thay exe đang chạy, tự mở lại bản mới, dọn .old.

    python tests/test_update_exe_e2e.py

Chạy trong Video\\_test\\updater\\e2e với bản sao exe; máy chủ HTTP cục bộ đóng vai GitHub (lần đầu báo có v4, sau khi
exe tải xong thì báo v3 để bản mới không cập nhật lặp). Chỉ tắt tiến trình theo đúng đường dẫn exe bản sao.
Hiện cửa sổ bảng chọn trận của AoE-Replay vài giây.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

import psutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from test_updater import Server  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass


def procs_of(exe):
    out = []
    for p in psutil.process_iter(["exe", "pid"]):
        try:
            if p.info["exe"] and os.path.normcase(p.info["exe"]) == os.path.normcase(exe):
                out.append(p)
        except (psutil.Error, OSError):
            pass
    return out


def wait(cond, timeout, what):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = cond()
        if v:
            return v
        time.sleep(0.25)
    raise AssertionError("hết giờ chờ: " + what)


def main():
    d = os.path.join(ROOT, "Video", "_test", "updater", "e2e")
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(os.path.join(d, "Video", "Raw"))
    exe = os.path.join(d, "AoE-Replay.exe")
    shutil.copy(os.path.join(ROOT, "dist", "AoE-Replay.exe"), exe)
    log = os.path.join(d, "Video", "Raw", "_replay.log")
    new = open(exe, "rb").read()
    srv = Server({})
    from test_updater import make_zip, zip_manifest
    zdata = make_zip({"AoE-Replay.exe": new, "AoE-MapCap.exe": b"khong dung"})
    m4 = zip_manifest(srv.url, "99", {"AoE-Replay.exe": new, "AoE-MapCap.exe": b"khong dung"}, zdata)
    from mapcap.version import APP_VERSION

    def manifest():                                      # tải zip xong thì báo đã là bản mới nhất (không cập nhật lặp)
        v = APP_VERSION if srv.hits.get("/AoE-MapCap-win64.zip") else "99"
        return json.dumps(dict(m4, version=v)).encode()
    srv.files.update({"/version.json": manifest, "/AoE-MapCap-win64.zip": zdata})
    env = dict(os.environ, AOEMAPCAP_UPDATE_URL=srv.url + "/version.json", AOEMAPCAP_UPDATE_AUTO="1")
    t0 = time.time()
    first = subprocess.Popen([exe], env=env, cwd=d)
    try:
        wait(lambda: srv.hits.get("/AoE-MapCap-win64.zip"), 60, "exe tải zip bản mới")
        print(f"đã tải bản mới sau {time.time() - t0:.1f} s")
        wait(lambda: first.poll() is not None, 30, "bản cũ thoát")
        print(f"bản cũ thoát (mã {first.returncode}) sau {time.time() - t0:.1f} s")
        ps = wait(lambda: procs_of(exe), 30, "bản mới chạy")
        print(f"bản mới đang chạy: pid {[p.pid for p in ps]}")
        wait(lambda: srv.hits.get("/version.json", 0) >= 2, 60, "bản mới tự kiểm tra lại")
        wait(lambda: not os.path.exists(exe + ".old"), 40, "dọn file .old")
        print(f"đã dọn {os.path.basename(exe)}.old sau {time.time() - t0:.1f} s")
        time.sleep(1.5)
        text = open(log, encoding="utf-8").read()
        print(text.strip())
        assert "đã cập nhật lên v99: khởi động lại" in text
        assert f"phiên bản đang dùng v{APP_VERSION}, mới nhất v{APP_VERSION}" in text
        assert procs_of(exe), "bản mới phải còn chạy (không lỗi khi mở)"
    finally:
        for p in procs_of(exe):
            try:
                p.kill()
            except psutil.Error:
                pass
        srv.close()
    # HTTPS thật tới GitHub từ exe: chưa có bản nào đính kèm version.json -> 404 (TLS vẫn phải thành công)
    env = {k: v for k, v in os.environ.items() if not k.startswith("AOEMAPCAP_")}
    open(log, "w").close()
    p = subprocess.Popen([exe], env=env, cwd=d)
    try:
        wait(lambda: "cập nhật:" in open(log, encoding="utf-8").read(), 40, "kiểm tra GitHub")
        text = open(log, encoding="utf-8").read().strip()
        print(text)
        assert "CERTIFICATE" not in text.upper() and "SSL" not in text.upper(), "lỗi chứng chỉ HTTPS trong exe"
    finally:
        for q in procs_of(exe):
            try:
                q.kill()
            except psutil.Error:
                pass
        p.wait(10)
    print("OK")


if __name__ == "__main__":
    main()
