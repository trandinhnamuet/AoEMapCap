"""Khởi động cùng Windows (ô ở thanh bên của AoE-MapCap, 2026-11-07).

Ghi một dòng vào HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run (của riêng người dùng, không cần quyền admin):
mở máy là AoE-MapCap tự chạy ngầm ở khay hệ thống (--tray) và bật ghi sẵn (--autostart), vào trận là tự ghi - người
dùng không còn quên bật. Ngoài trận bộ ghi chỉ dò tiến trình game 2 giây một lần nên gần như không tốn máy.

Tắt / bật cũng thấy được trong Task Manager > Startup apps (tên AoE-MapCap). Dòng lệnh luôn trỏ tới exe đang chạy:
mỗi lần mở app refresh() ghi lại nếu thư mục app đã bị chuyển chỗ.
"""
import os
import subprocess
import sys

KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "AoE-MapCap"
ARGS = ["--tray", "--autostart"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def supported():
    return sys.platform == "win32"


def command():
    """Dòng lệnh chạy app lúc đăng nhập Windows: exe (bản phát hành) hoặc pythonw run_app.py (chạy từ mã nguồn)."""
    if getattr(sys, "frozen", False):
        argv = [sys.executable]
    else:
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        argv = [pyw if os.path.isfile(pyw) else sys.executable, os.path.join(ROOT, "run_app.py")]
    return subprocess.list2cmdline(argv + ARGS)


def get():
    """Dòng lệnh đang đăng ký (None = chưa bật)."""
    if not supported():
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as k:
            val, _t = winreg.QueryValueEx(k, NAME)
            return str(val)
    except OSError:
        return None


def is_enabled():
    return get() is not None


def set_enabled(on):
    """Bật / tắt; lỗi (registry bị chặn ...) thì ném OSError cho giao diện báo."""
    if not supported():
        raise OSError("chỉ có trên Windows")
    import winreg
    if on:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, NAME, 0, winreg.REG_SZ, command())
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, NAME)
        except FileNotFoundError:
            pass
    return is_enabled()


def refresh():
    """Đang bật mà dòng lệnh không còn trỏ đúng exe này (thư mục app đã chuyển chỗ): ghi lại. Trả về True nếu sửa."""
    cur = get()
    if cur is None or cur == command():
        return False
    try:
        set_enabled(True)
        return True
    except OSError:
        return False
