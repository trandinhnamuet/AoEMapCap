"""Chọn đúng tiến trình game: bỏ qua bản chụp lỗi 0 luồng (Windows Error Reporting tạo khi game crash, cùng tên
EMPIRESX.EXE); game đã thoát mà handle của bộ ghi còn giữ thì alive() = False.

    python tests/test_game_pick.py

Tạo lại đúng tình huống 18/10 bằng tiến trình thật: một tiến trình con (python ngủ) + bản chụp của nó bằng
PssCaptureSnapshot(PSS_CAPTURE_VA_CLONE) (cách WER chụp game crash: tiến trình mới, 0 luồng, cùng bộ nhớ).
Chỉ đụng tiến trình test tự tạo (tắt theo PID).
"""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

import psutil  # noqa: E402

from mapcap import memory  # noqa: E402

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = wt.HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.PssCaptureSnapshot.argtypes = [wt.HANDLE, wt.DWORD, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
k32.PssCaptureSnapshot.restype = wt.DWORD
k32.PssQuerySnapshot.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
k32.PssQuerySnapshot.restype = wt.DWORD
k32.PssFreeSnapshot.argtypes = [wt.HANDLE, wt.HANDLE]
k32.GetProcessId.argtypes = [wt.HANDLE]
k32.GetProcessId.restype = wt.DWORD
PROCESS_ALL_ACCESS = 0x1FFFFF
PSS_CAPTURE_VA_CLONE = 0x1
PSS_QUERY_VA_CLONE_INFORMATION = 1


def va_clone(h):
    snap = wt.HANDLE()
    err = k32.PssCaptureSnapshot(h, PSS_CAPTURE_VA_CLONE, 0, ctypes.byref(snap))
    assert err == 0, f"PssCaptureSnapshot lỗi {err}"
    clone = wt.HANDLE()
    err = k32.PssQuerySnapshot(snap, PSS_QUERY_VA_CLONE_INFORMATION, ctypes.byref(clone), ctypes.sizeof(clone))
    assert err == 0, f"PssQuerySnapshot lỗi {err}"
    return snap, k32.GetProcessId(clone)


def as_game(pid):
    """psutil.Process thật nhưng tên giả là EMPIRESX.EXE (như process_iter trả về)."""
    p = psutil.Process(pid)
    p.info = {"name": "EMPIRESX.EXE", "exe": ""}
    return p


def main():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    h = k32.OpenProcess(PROCESS_ALL_ACCESS, False, child.pid)
    snap = None
    try:
        time.sleep(0.5)
        snap, clone_pid = va_clone(h)
        cp = psutil.Process(clone_pid)
        print(f"bản chụp pid {clone_pid}: tên {cp.name()}, {cp.num_threads()} luồng, trạng thái {cp.status()}")
        assert psutil.pid_exists(clone_pid), "bản chụp phải 'tồn tại' như PID 18156 hôm 18/10"
        assert cp.num_threads() == 0
        assert not memory.process_runs(clone_pid) and memory.process_runs(child.pid)

        # bộ ghi cũ: alive() = pid_exists -> True mãi; bản mới: False
        pm = memory.ProcessMemory(clone_pid)
        assert not pm.alive(), "bám vào bản chụp: alive() phải False"
        pm.close()
        print("alive() với bản chụp 0 luồng: False (bản cũ: True mãi): OK")

        # chọn game: bản chụp đứng trước trong danh sách vẫn bị bỏ qua
        orig_iter = memory.psutil.process_iter
        memory.psutil.process_iter = lambda attrs=None: iter([as_game(clone_pid), as_game(child.pid)])
        try:
            got = memory.find_game_process()
            assert got is not None and got.pid == child.pid, got
            assert memory.find_game_process(exclude={child.pid}) is None
        finally:
            memory.psutil.process_iter = orig_iter
        print("find_game_process bỏ qua bản chụp, chọn game thật: OK")

        # game thật thoát trong khi bộ ghi còn giữ handle: alive() biết ngay
        pm = memory.ProcessMemory(child.pid)
        assert pm.alive()
        child.kill()
        child.wait(10)
        t0 = time.time()
        while pm.alive() and time.time() - t0 < 3:
            time.sleep(0.05)
        assert not pm.alive(), "game đã thoát: alive() phải False dù handle còn mở"
        print(f"game thoát khi handle còn mở: alive() False sau {time.time() - t0:.2f}s "
              f"(pid_exists lúc này: {psutil.pid_exists(child.pid)}): OK")
        pm.close()
    finally:
        if snap is not None:
            k32.PssFreeSnapshot(wt.HANDLE(0xFFFFFFFFFFFFFFFF), snap)   # GetCurrentProcess(): giải phóng bản chụp
        if child.poll() is None:
            child.kill()
        k32.CloseHandle(h)

    # has_window: tiến trình này chưa có cửa sổ -> có sau khi tạo Tk
    assert not memory.has_window(os.getpid())
    import tkinter as tk
    root = tk.Tk()
    root.update()
    assert memory.has_window(os.getpid())
    root.withdraw()
    root.update()
    assert not memory.has_window(os.getpid())
    root.destroy()
    print("has_window: OK")
    print("OK test_game_pick")


if __name__ == "__main__":
    main()
