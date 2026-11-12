"""Tự cập nhật bản sửa lỗi quan trọng (auto_below) bằng exe THẬT, không ai bấm gì.

    python build.py --test-no-uac              (dist_test\\AoE-MapCap.exe, không đòi UAC)
    python tests/test_auto_update_e2e.py

Bản sao exe ở Video\\_test\\updater\\auto_e2e cạnh file cờ aoemapcap-test.flag (mới nhận biến môi trường thử), chạy
ẩn ở khay (--tray) như lúc khởi động cùng Windows. Máy chủ HTTP cục bộ đóng vai GitHub: version.json báo v99 với
auto_below = 99 (KHÔNG đặt AOEMAPCAP_UPDATE_AUTO, tức không có ai bấm Cập nhật); tải zip xong thì báo đã mới nhất (không
lặp). Kiểm: tự tải (không có cờ tự bấm), thay exe, bản cũ thoát, bản mới tự mở lại với --tray (vẫn ẩn, không
cửa sổ nào hiện), không tải lặp, tự kiểm tra lại.
Mutex / tác vụ khởi động tên riêng, không thống kê; chỉ tắt tiến trình theo đúng đường dẫn exe bản sao.
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import shutil
import subprocess
import sys
import time

import psutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, ROOT)
from test_updater import Server, make_zip, zip_manifest  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
u32 = ctypes.WinDLL("user32")
ENUM = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def procs_of(exe):
    out = []
    for p in psutil.process_iter(["exe", "pid"]):
        try:
            if p.info["exe"] and os.path.normcase(p.info["exe"]) == os.path.normcase(exe):
                out.append(p)
        except (psutil.Error, OSError):
            pass
    return out


def visible_windows(pids):
    found = []

    def cb(h, _):
        if u32.IsWindowVisible(h):
            pid = wt.DWORD()
            u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value in pids:
                t = ctypes.create_unicode_buffer(200)
                u32.GetWindowTextW(h, t, 200)
                found.append(t.value)
        return True
    u32.EnumWindows(ENUM(cb), 0)
    return found


def wait(cond, timeout, what):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = cond()
        if r:
            return r
        time.sleep(0.3)
    raise AssertionError("quá giờ chờ: " + what)


def main():
    src = os.path.join(ROOT, "dist_test", "AoE-MapCap.exe")
    assert os.path.isfile(src), "chưa build: python build.py --test-no-uac"
    d = os.path.join(ROOT, "Video", "_test", "updater", "auto_e2e")
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(os.path.join(d, "Video"))
    exe = os.path.join(d, "AoE-MapCap.exe")
    shutil.copy(src, exe)
    open(os.path.join(d, "aoemapcap-test.flag"), "w").close()
    with open(os.path.join(d, "Video", "_settings.ini"), "w", encoding="utf-8") as f:
        f.write("[mapcap]\nconfig_version = 3\ntelemetry = 0\nclose_to_tray = 1\nwin_startup_init = 1\nauto_clean = 0\n")
    new = open(exe, "rb").read()
    srv = Server({})
    zdata = make_zip({"AoE-MapCap.exe": new})
    m = dict(zip_manifest(srv.url, "99", {"AoE-MapCap.exe": new}, zdata), auto_below="99")
    from mapcap.version import APP_VERSION

    def manifest():                                       # tải zip xong thì báo đã mới nhất (không cập nhật lặp)
        v = APP_VERSION if srv.hits.get("/AoE-MapCap-win64.zip") else "99"
        return json.dumps(dict(m, version=v, auto_below=v)).encode()
    srv.files.update({"/version.json": manifest, "/AoE-MapCap-win64.zip": zdata})
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AOEMAPCAP_", "PYINSTALLER_"))}
    env.update(AOEMAPCAP_UPDATE_URL=srv.url + "/version.json", AOEMAPCAP_TELEMETRY="0",
               AOEMAPCAP_INSTANCE=f"AoE-MapCap-test-{os.getpid()}",
               AOEMAPCAP_STARTUP_TASK=f"AoE-MapCap-test-{os.getpid()}",
               AOEMAPCAP_STARTUP_RUNKEY=r"Software\AoE-MapCap-test\Run")
    t0 = time.time()
    first = subprocess.Popen([exe, "--tray"], env=env, cwd=d)
    try:
        wait(lambda: srv.hits.get("/AoE-MapCap-win64.zip"), 90, "exe tự tải zip bản mới (không ai bấm)")
        print(f"tự tải bản mới sau {time.time() - t0:.1f} s (không bấm gì)")
        wait(lambda: first.poll() is not None, 40, "bản cũ thoát")
        print(f"bản cũ thoát (mã {first.returncode}) sau {time.time() - t0:.1f} s")
        ps = wait(lambda: procs_of(exe), 40, "bản mới chạy")
        print(f"bản mới đang chạy: pid {[p.pid for p in ps]}")
        wait(lambda: srv.hits.get("/version.json", 0) >= 2, 90, "bản mới tự kiểm tra lại")
        wait(lambda: not os.path.exists(exe + ".old"), 60, "dọn file .old")
        time.sleep(3)
        procs = procs_of(exe)
        assert procs, "bản mới phải còn chạy"
        cmd = " ".join(" ".join(p.cmdline()) for p in procs)
        assert "--tray" in cmd and "--wait-instance" in cmd, cmd
        assert srv.hits.get("/AoE-MapCap-win64.zip") == 1, "bản mới không được tải lặp lại"
        shown = visible_windows({p.pid for p in procs})
        assert not shown, f"bản mới mở lại vẫn phải ẩn ở khay, nhưng hiện: {shown}"
        print("bản mới mở lại vẫn ẩn ở khay (không cửa sổ nào hiện): OK")
    finally:
        for p in procs_of(exe):
            try:
                p.kill()
            except psutil.Error:
                pass
        srv.close()
    print("OK test_auto_update_e2e")


if __name__ == "__main__":
    main()
