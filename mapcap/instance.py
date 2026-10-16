"""Chỉ một cửa sổ AoE-MapCap mỗi phiên Windows (bấm X là chạy ngầm ở khay: mở exe lần nữa không được tạo bộ ghi thứ
hai). Mutex có tên giữ quyền "đang chạy"; lần mở sau bật sự kiện có tên -> bản đang chạy hiện lại cửa sổ.
Sau tự cập nhật, bản mới chờ bản cũ thoát hẳn (wait_s) rồi mới nhận quyền."""
import ctypes
import ctypes.wintypes as wt
import threading

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateMutexW.argtypes = [wt.LPVOID, wt.BOOL, wt.LPCWSTR]
kernel32.CreateMutexW.restype = wt.HANDLE
kernel32.CreateEventW.argtypes = [wt.LPVOID, wt.BOOL, wt.BOOL, wt.LPCWSTR]
kernel32.CreateEventW.restype = wt.HANDLE
kernel32.OpenEventW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
kernel32.OpenEventW.restype = wt.HANDLE
kernel32.SetEvent.argtypes = [wt.HANDLE]
kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
kernel32.WaitForSingleObject.restype = wt.DWORD
kernel32.ReleaseMutex.argtypes = [wt.HANDLE]
kernel32.CloseHandle.argtypes = [wt.HANDLE]

WAIT_OBJECT_0, WAIT_ABANDONED, WAIT_TIMEOUT = 0x0, 0x80, 0x102
EVENT_MODIFY_STATE = 0x0002


def base_name():
    from .updater import env_override                  # đổi tên chỉ khi chạy thử (mã nguồn / file cờ test)
    return env_override("AOEMAPCAP_INSTANCE") or "AoE-MapCap-gui"


class Instance:
    """Quyền "đang chạy" + sự kiện "hiện cửa sổ". acquire() trả về Instance hoặc None (đã có bản khác đang chạy).
    Mutex thuộc luồng gọi acquire (luồng chính), giải phóng bằng release() hoặc khi tiến trình thoát."""

    def __init__(self, name, mutex, event):
        self.name, self.mutex, self.event = name, mutex, event
        self._watch = None
        self._stop = False

    @classmethod
    def acquire(cls, wait_s=0.0, name=None):
        name = name or base_name()
        m = kernel32.CreateMutexW(None, False, "Local\\" + name)
        if not m:                                  # bị từ chối = bản khác (quyền cao hơn) đang giữ; lỗi khác: cứ chạy
            return None if ctypes.get_last_error() == 5 else cls(name, None, None)
        r = kernel32.WaitForSingleObject(m, int(wait_s * 1000))
        if r not in (WAIT_OBJECT_0, WAIT_ABANDONED):
            kernel32.CloseHandle(m)
            return None
        ev = kernel32.CreateEventW(None, False, False, "Local\\" + name + "-show")   # tự đặt lại sau mỗi lần chờ
        return cls(name, m, ev)

    def watch(self, on_show):
        """Luồng nền: mỗi lần có bản khác mở lên (signal_show) gọi on_show() (hàm nhận tự đưa về luồng giao diện)."""
        def loop():
            while not self._stop and self.event:
                if kernel32.WaitForSingleObject(self.event, 500) == WAIT_OBJECT_0 and not self._stop:
                    try:
                        on_show()
                    except Exception:  # noqa: BLE001
                        pass
        self._watch = threading.Thread(target=loop, name="instance-show", daemon=True)
        self._watch.start()

    def release(self):
        self._stop = True
        if self._watch:
            self._watch.join(2)
        if self.mutex:
            kernel32.ReleaseMutex(self.mutex)
            kernel32.CloseHandle(self.mutex)
            self.mutex = None
        if self.event:
            kernel32.CloseHandle(self.event)
            self.event = None


def signal_show(name=None):
    """Báo bản đang chạy hiện cửa sổ lên. True nếu gửi được."""
    name = name or base_name()
    h = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, "Local\\" + name + "-show")
    if not h:
        return False
    try:
        return bool(kernel32.SetEvent(h))
    finally:
        kernel32.CloseHandle(h)
