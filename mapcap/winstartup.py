"""Khởi động cùng Windows (ô ở thanh bên của AoE-MapCap).

Mở máy là AoE-MapCap tự chạy ngầm ở khay hệ thống (--tray) và bật ghi sẵn (--autostart), vào trận là tự ghi - người dùng
không còn quên bật. Ngoài trận bộ ghi chỉ dò tiến trình game 2 giây một lần nên gần như không tốn máy.

Cách đăng ký: một tác vụ Task Scheduler "AoE-MapCap" chạy lúc người dùng đăng nhập, **quyền cao nhất** (không hỏi UAC).
v30-v31 dùng khoá HKCU\\...\\CurrentVersion\\Run nhưng exe đòi quyền Administrator (uac_admin, để đọc game chạy quyền
admin) mà Windows bỏ qua mọi lệnh trong Run cần nâng quyền: nhật ký Shell-Core ghi "Finished execution of command
'AoE-MapCap.exe --tray --autostart' (PID 0)" - không chạy (người dùng 08/11). refresh() chuyển dòng Run cũ sang tác vụ.

schtasks in ra theo bảng mã của console (chữ Việt trong đường dẫn thành "?"), nên không so đường dẫn đọc lại: mô tả của
tác vụ mang dấu vân tay ASCII của dòng lệnh (_tag) để biết thư mục app đã chuyển chỗ hay chưa. Tạo tác vụ bằng tệp XML
UTF-16 nên đường dẫn có dấu vẫn đúng.

Không nháy màn hình chờ (người dùng 09/11: "nháy 1 lần trên màn hình rồi biến mất"): bộ nạp exe một file (PyInstaller)
hiện màn hình chờ trước cả khi mã Python chạy, chỉ tắt được bằng biến môi trường PYINSTALLER_SUPPRESS_SPLASH_SCREEN=1
mà tác vụ không đặt được. Nên tác vụ chạy trình khởi chạy nhỏ AoE-MapCap-start.exe (launcher/autostart.c, đóng gói trong
exe như ffmpeg, giải nén ra %LOCALAPPDATA%\\AoE-MapCap\\autostart\\AoE-MapCap-start-<sha12>.exe, kiểm SHA-256 mỗi lần mở
app): đặt biến đó rồi chạy "<AoE-MapCap.exe>" --tray --autostart. Đổi bản launcher -> tên mới -> dấu vân tay đổi ->
refresh() đăng ký lại. Cùng mức tin cậy với exe chính (cả hai nằm trong thư mục người dùng ghi được).
"""
import ctypes
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from xml.sax.saxutils import escape



def _test_name(var, default):
    """Tên thay khi kiểm thử (chạy từ mã nguồn, hoặc exe có file cờ aoemapcap-test.flag cạnh bên - như updater): exe thử
    không được đăng ký lại / xoá tác vụ thật của người dùng."""
    try:
        from .updater import env_override
        return env_override(var) or default
    except Exception:  # noqa: BLE001
        return default


TASK = _test_name("AOEMAPCAP_STARTUP_TASK", "AoE-MapCap")    # tác vụ ở thư mục gốc của Task Scheduler
ARGS = ["--tray", "--autostart"]
LEGACY_KEY = _test_name("AOEMAPCAP_STARTUP_RUNKEY", r"Software\Microsoft\Windows\CurrentVersion\Run")  # cách cũ v30-v31
LEGACY_NAME = "AoE-MapCap"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_NO_WINDOW = 0x08000000                                     # CREATE_NO_WINDOW: không chớp cửa sổ console


def supported():
    return sys.platform == "win32"


LAUNCHER = "AoE-MapCap-start.exe"


def _bundled_launcher():
    meipass = getattr(sys, "_MEIPASS", None)
    p = os.path.join(meipass, "autostart", LAUNCHER) if meipass else None
    return p if p and os.path.isfile(p) else None


def launcher_path(src=None):
    """Trình khởi chạy đã giải nén (kiểm SHA-256, thiếu / sai thì ghi lại; xoá bản cũ khác SHA). None nếu exe không
    mang theo (chạy từ mã nguồn, bản build thiếu) hoặc không ghi được."""
    src = src or _bundled_launcher()
    if not src:
        return None
    data = open(src, "rb").read()
    sha = hashlib.sha256(data).hexdigest()
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or os.path.expanduser("~")
    folder = os.path.join(base, "AoE-MapCap", "autostart")
    dst = os.path.join(folder, f"AoE-MapCap-start-{sha[:12]}.exe")
    try:
        ok = os.path.isfile(dst) and hashlib.sha256(open(dst, "rb").read()).hexdigest() == sha
        if not ok:
            os.makedirs(folder, exist_ok=True)
            with open(dst + ".part", "wb") as f:
                f.write(data)
            os.replace(dst + ".part", dst)
        for n in os.listdir(folder):                         # bản launcher cũ (tác vụ đã trỏ sang bản mới)
            if n.startswith("AoE-MapCap-start-") and os.path.join(folder, n) != dst:
                try:
                    os.remove(os.path.join(folder, n))
                except OSError:
                    pass
    except OSError:
        return None
    return dst


def _workdir():
    return os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else ROOT


def _argv():
    """Chương trình + tham số chạy lúc đăng nhập: bản phát hành = trình khởi chạy (không màn hình chờ) với dòng lệnh
    exe chính (không có trình khởi chạy thì exe trực tiếp); chạy từ mã nguồn = pythonw run_app.py."""
    if getattr(sys, "frozen", False):
        la = launcher_path()
        return (la, [sys.executable] + ARGS) if la else (sys.executable, ARGS)
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return (pyw if os.path.isfile(pyw) else sys.executable), [os.path.join(ROOT, "run_app.py")] + ARGS


def command():
    prog, args = _argv()
    return subprocess.list2cmdline([prog] + args)


def _tag():
    return "aoemapcap-cmd-" + hashlib.sha1(command().encode("utf-8")).hexdigest()[:16]


def _elevated():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def _schtasks(*args):
    return subprocess.run(["schtasks", *args], capture_output=True, creationflags=_NO_WINDOW, timeout=30)


def _err(r):
    return (r.stderr or r.stdout or b"").decode("mbcs", "replace").strip() or f"mã {r.returncode}"


def _xml():
    prog, args = _argv()
    user = escape(f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}")
    level = "HighestAvailable" if _elevated() else "LeastPrivilege"     # exe luôn chạy admin -> quyền cao nhất
    desc = ("AoE-MapCap: mở máy là chạy ngầm ở khay hệ thống và bật ghi trận (ô Khởi động cùng Windows trong app). "
            + _tag())
    return f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>{escape(desc)}</Description></RegistrationInfo>
  <Triggers>
    <LogonTrigger><Enabled>true</Enabled><UserId>{user}</UserId><Delay>PT10S</Delay></LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author"><UserId>{user}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>{level}</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>false</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>4</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec><Command>{escape(prog)}</Command><Arguments>{escape(subprocess.list2cmdline(args))}</Arguments>
      <WorkingDirectory>{escape(_workdir())}</WorkingDirectory></Exec>
  </Actions>
</Task>
'''


def _query():
    """XML của tác vụ (chữ ngoài bảng mã console thành "?"), None nếu chưa có."""
    if not supported():
        return None
    r = _schtasks("/Query", "/TN", TASK, "/XML")
    return r.stdout.decode("mbcs", "replace") if r.returncode == 0 else None


def _task_enabled(text):
    m = re.search(r"<Settings>(.*?)</Settings>", text or "", re.S)
    return bool(text) and not (m and re.search(r"<Enabled>\s*false\s*</Enabled>", m.group(1), re.I))


def get():
    """Dòng lệnh của tác vụ đang đăng ký (chữ có dấu có thể thành "?"), None nếu chưa bật."""
    text = _query()
    if not _task_enabled(text):
        return None
    c = re.search(r"<Command>(.*?)</Command>", text, re.S)
    a = re.search(r"<Arguments>(.*?)</Arguments>", text, re.S)
    return ((c.group(1) if c else "") + (" " + a.group(1) if a else "")).strip()


def is_enabled():
    return _task_enabled(_query())


def _legacy_exists():
    if not supported():
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, LEGACY_KEY) as k:
            winreg.QueryValueEx(k, LEGACY_NAME)
            return True
    except OSError:
        return False


def _remove_legacy():
    """Xoá dòng Run của v30-v31 (không tác dụng với exe cần quyền admin). True nếu đã có."""
    if not _legacy_exists():
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, LEGACY_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, LEGACY_NAME)
    except OSError:
        pass
    return True


def set_enabled(on):
    """Bật / tắt; lỗi (không đủ quyền, Task Scheduler bị tắt ...) thì ném OSError cho giao diện báo."""
    if not supported():
        raise OSError("chỉ có trên Windows")
    _remove_legacy()
    if on:
        fd, path = tempfile.mkstemp(prefix="aoemapcap_task_", suffix=".xml")
        try:
            with os.fdopen(fd, "w", encoding="utf-16") as f:
                f.write(_xml())
            r = _schtasks("/Create", "/TN", TASK, "/XML", path, "/F")
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        if r.returncode != 0:
            raise OSError(_err(r))
    elif _query() is not None:
        r = _schtasks("/Delete", "/TN", TASK, "/F")
        if r.returncode != 0:
            raise OSError(_err(r))
    return is_enabled()


def refresh():
    """Mỗi lần mở app (bản exe): chuyển dòng Run cũ (v30-v31) sang tác vụ; tác vụ đang bật mà trỏ chỗ cũ (thư mục app
    đã chuyển) thì đăng ký lại. Trả về True nếu đã sửa."""
    legacy = _remove_legacy()
    text = _query()
    try:
        if text is None:
            if legacy:                                    # v30-v31 đã bật (nhưng không chạy được): bật đúng cách
                set_enabled(True)
                return True
            return False
        if _task_enabled(text) and _tag() not in text:
            set_enabled(True)
            return True
    except OSError:
        return False
    return legacy
