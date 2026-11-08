"""Khởi động cùng Windows không nháy gì trên màn hình (v33): chạy exe THẬT đã build và ghi lại mọi cửa sổ hiện lên.

    python build.py --test-no-uac            (exe không đòi UAC -> dist_test\\AoE-MapCap.exe)
    python tests/test_tray_start.py [dist_test\\AoE-MapCap.exe]

Ba lượt, mỗi lượt theo dõi 15 ms một lần mọi cửa sổ đang hiện của tiến trình exe thử (theo đường dẫn exe):
  1. qua trình khởi chạy (như tác vụ đăng nhập): AoE-MapCap-start.exe "<exe>" --tray --autostart -> KHÔNG cửa sổ nào hiện,
     app vẫn chạy ở khay và bật ghi (nhật ký "chờ game");
  2. exe --tray --autostart trực tiếp (v32 chạy thế này): ghi lại cái gì nháy (màn hình chờ của bộ nạp);
  3. mở bình thường: màn hình chờ + cửa sổ chính vẫn hiện (không làm hỏng lúc mở tay).
Exe chép vào Video\\_test\\tray_start\\app cạnh file cờ aoemapcap-test.flag (mới nhận biến môi trường thử): mutex riêng,
không thống kê, không hỏi cập nhật, tác vụ khởi động tên riêng (không đụng tác vụ thật). Chỉ dừng tiến trình thử theo PID.
"""
import ctypes
import ctypes.wintypes as wt
import os
import shutil
import subprocess
import sys
import time

import psutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
OUT = os.path.join(ROOT, "Video", "_test", "tray_start")
APP = os.path.join(OUT, "app")
LAUNCHER = os.path.join(ROOT, "build_assets", "AoE-MapCap-start.exe")
u32 = ctypes.WinDLL("user32", use_last_error=True)
ENUM = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def windows():
    """[(pid, class, title, (w, h))] cửa sổ cấp cao đang hiện, có kích thước."""
    out = []

    def cb(h, _):
        if u32.IsWindowVisible(h):
            r = wt.RECT()
            u32.GetWindowRect(h, ctypes.byref(r))
            w, hh = r.right - r.left, r.bottom - r.top
            if w > 1 and hh > 1:
                pid = wt.DWORD()
                u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
                cls = ctypes.create_unicode_buffer(128)
                u32.GetClassNameW(h, cls, 128)
                tl = ctypes.create_unicode_buffer(256)
                u32.GetWindowTextW(h, tl, 256)
                out.append((pid.value, cls.value, tl.value, (w, hh)))
        return True
    u32.EnumWindows(ENUM(cb), 0)
    return out


def test_pids(exe):
    exe = os.path.normcase(os.path.abspath(exe))
    pids = set()
    for p in psutil.process_iter(["name", "exe"]):
        try:
            if p.info["name"] and p.info["name"].lower() in ("aoe-mapcap.exe", "aoe-mapcap-start.exe") and \
                    p.info["exe"] and os.path.normcase(p.info["exe"]) in (exe, os.path.normcase(LAUNCHER)):
                pids.add(p.pid)
        except psutil.Error:
            pass
    return pids


def stop(exe):
    for pid in test_pids(exe):
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    t0 = time.time()
    while test_pids(exe) and time.time() - t0 < 10:
        time.sleep(0.2)


def watch(cmd, exe, seconds, env):
    """Chạy cmd, theo dõi cửa sổ của tiến trình thử trong `seconds` giây. Trả về {(class, title): (lần đầu, số lần thấy)}."""
    seen = {}
    t0 = time.time()
    subprocess.Popen(cmd, env=env, cwd=APP)
    pids = set()
    last_scan = 0
    while time.time() - t0 < seconds:
        now = time.time()
        if now - last_scan > 0.1:
            pids |= test_pids(exe)
            last_scan = now
        for pid, cls, title, size in windows():
            if pid in pids:
                k = (cls, title)
                first, n, sz = seen.get(k, (now - t0, 0, size))
                seen[k] = (first, n + 1, sz)
        time.sleep(0.015)
    return seen


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "dist_test", "AoE-MapCap.exe")
    assert os.path.isfile(src), f"chưa build: {src} (python build.py --test-no-uac)"
    assert os.path.isfile(LAUNCHER), LAUNCHER
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(os.path.join(APP, "Video"))
    exe = os.path.join(APP, "AoE-MapCap.exe")
    shutil.copy2(src, exe)
    open(os.path.join(APP, "aoemapcap-test.flag"), "w").write("test\n")
    with open(os.path.join(APP, "Video", "_settings.ini"), "w", encoding="utf-8") as f:
        f.write("[mapcap]\nconfig_version = 3\nauto_start = 1\ntelemetry = 0\nclose_to_tray = 1\nwin_startup_init = 1\n"
                "auto_clean = 0\n")
    env = dict(os.environ, AOEMAPCAP_INSTANCE=f"AoE-MapCap-test-{os.getpid()}", AOEMAPCAP_TELEMETRY="0",
               AOEMAPCAP_UPDATE_URL="http://127.0.0.1:9/version.json",
               AOEMAPCAP_STARTUP_TASK=f"AoE-MapCap-test-{os.getpid()}",
               AOEMAPCAP_STARTUP_RUNKEY=r"Software\AoE-MapCap-test\Run")
    env.pop("PYINSTALLER_SUPPRESS_SPLASH_SCREEN", None)
    log = os.path.join(APP, "Video", "_mapcap.log")
    try:
        # chạy một lần cho Defender quét xong exe mới (lần đầu chậm bất thường), rồi mới đo
        watch([exe, "--tray"], exe, 8, env)
        stop(exe)

        # như Task Scheduler: Command = launcher, Arguments nguyên văn (không bọc thêm nháy)
        seen = watch(f'"{LAUNCHER}" ' + subprocess.list2cmdline([exe, "--tray", "--autostart"]), exe, 12, env)
        alive = test_pids(exe)
        txt = open(log, encoding="utf-8", errors="replace").read() if os.path.exists(log) else ""
        stop(exe)
        print("1) qua trình khởi chạy:", seen or "không cửa sổ nào hiện")
        assert not seen, f"có cửa sổ nháy lên: {seen}"
        assert alive, "app không chạy"
        assert "chờ game" in txt, "app không bật ghi (--autostart)"
        print("   app chạy ngầm ở khay, đã bật ghi (chờ game), không nháy gì: OK")

        seen = watch([exe, "--tray", "--autostart"], exe, 12, env)
        stop(exe)
        print("2) exe --tray trực tiếp (v32):", seen or "không cửa sổ nào hiện")

        seen = watch([exe], exe, 12, env)
        stop(exe)
        print("3) mở bình thường:", seen)
        titles = " | ".join(t for (_c, t) in seen)
        assert any("AoE-MapCap" in t and "ghi trận" in t for (_c, t) in seen), "mở tay phải hiện cửa sổ chính: " + titles
        print("   mở tay vẫn hiện màn hình chờ / cửa sổ chính: OK")
    finally:
        stop(exe)
    print("OK test_tray_start")


if __name__ == "__main__":
    main()
