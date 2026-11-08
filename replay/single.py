"""Mỗi lúc chỉ một trình xem replay (người dùng 07/11: mở nhiều trận một lúc làm lag máy).

Trình xem đang mở giữ mutex có tên; trình xem mới mở lên bật sự kiện "đóng" có tên rồi chờ mutex. Trình xem cũ thấy sự
kiện ở khung hình kế (should_close) thì tự thoát như bấm X -> trình xem mới nhận mutex, tắt sự kiện, mở trận. Áp dụng
mọi đường mở (nút Xem replay, Mở file khác, bấm đúp file .aoerec, AoE-Replay.exe) vì nằm trong chính trình xem.

Tên theo phiên Windows (Local\\). Chạy thử đặt AOEMAPCAP_REPLAY_INSTANCE để không đóng trình xem thật của người dùng;
kịch bản tự kiểm tra (--selftest) không tham gia.
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import time

WAIT_OBJECT_0, WAIT_ABANDONED, WAIT_TIMEOUT = 0x0, 0x80, 0x102

if sys.platform == "win32":
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.CreateMutexW.argtypes = [wt.LPVOID, wt.BOOL, wt.LPCWSTR]
    _k32.CreateMutexW.restype = wt.HANDLE
    _k32.CreateEventW.argtypes = [wt.LPVOID, wt.BOOL, wt.BOOL, wt.LPCWSTR]
    _k32.CreateEventW.restype = wt.HANDLE
    for _f in (_k32.SetEvent, _k32.ResetEvent, _k32.ReleaseMutex, _k32.CloseHandle):
        _f.argtypes = [wt.HANDLE]
        _f.restype = wt.BOOL
    _k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    _k32.WaitForSingleObject.restype = wt.DWORD
else:  # pragma: no cover
    _k32 = None


def base_name():
    return os.environ.get("AOEMAPCAP_REPLAY_INSTANCE") or "AoE-MapCap-replay"


class Slot:
    """Quyền "trình xem đang mở". owned = False: không nhận được (trình xem cũ treo) nhưng vẫn cho mở."""

    def __init__(self, mutex, event, owned, closed_other):
        self.mutex, self.event, self.owned, self.closed_other = mutex, event, owned, closed_other

    def should_close(self):
        """Có trình xem mới đang chờ: thoát (gọi mỗi khung hình, không chặn)."""
        return bool(self.owned and self.event and _k32.WaitForSingleObject(self.event, 0) == WAIT_OBJECT_0)

    def release(self):
        if self.mutex:
            if self.owned:
                _k32.ReleaseMutex(self.mutex)
            _k32.CloseHandle(self.mutex)
        if self.event:
            _k32.CloseHandle(self.event)
        self.mutex = self.event = None
        self.owned = False


def take_over(wait_s=10.0, name=None, log=None):
    """Đóng trình xem đang mở (nếu có) rồi nhận quyền. Gọi từ luồng chính (mutex thuộc luồng gọi), trước khi nạp trận
    để trận cũ nhả RAM / CPU trước."""
    if _k32 is None:
        return Slot(None, None, False, False)
    name = name or base_name()
    ev = _k32.CreateEventW(None, True, False, "Local\\" + name + "-close")   # đặt lại bằng tay: chờ tới khi nhận xong
    m = _k32.CreateMutexW(None, False, "Local\\" + name)
    if not m:
        return Slot(None, ev, False, False)
    closed_other = False
    r = _k32.WaitForSingleObject(m, 0)
    if r not in (WAIT_OBJECT_0, WAIT_ABANDONED) and ev:
        closed_other = True
        t0 = time.monotonic()
        while True:                        # bật lại mỗi 250 ms: hai trình xem mở cùng lúc thì trình mở sau cùng thắng
            _k32.SetEvent(ev)
            r = _k32.WaitForSingleObject(m, 250)
            if r in (WAIT_OBJECT_0, WAIT_ABANDONED) or time.monotonic() - t0 >= wait_s:
                break
        if log:
            log(f"đóng trình xem đang mở: {'xong' if r in (WAIT_OBJECT_0, WAIT_ABANDONED) else 'quá giờ'} "
                f"sau {time.monotonic() - t0:.1f} s")
    owned = r in (WAIT_OBJECT_0, WAIT_ABANDONED)
    if ev:
        _k32.ResetEvent(ev)
    return Slot(m, ev, owned, closed_other)
