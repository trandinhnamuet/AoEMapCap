"""Đọc bộ nhớ tiến trình game (chỉ đọc, không ghi, không inject)."""
import ctypes
import ctypes.wintypes as wt
import struct

import psutil

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

GAME_EXE_PREFIXES = ("empiresx", "empires")

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.OpenProcess.restype = wt.HANDLE
_k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_k32.ReadProcessMemory.restype = wt.BOOL
_k32.ReadProcessMemory.argtypes = [wt.HANDLE, wt.LPCVOID, wt.LPVOID, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
_k32.CloseHandle.argtypes = [wt.HANDLE]


class MemoryError_(Exception):
    pass


def find_game_process(exclude=()):
    """Trả về psutil.Process của game đang chạy, hoặc None. exclude: pid bỏ qua (exe không hỗ trợ)."""
    for p in psutil.process_iter(["name", "exe"]):
        name = (p.info["name"] or "").lower()
        if name.endswith(".exe") and name[:-4].startswith(GAME_EXE_PREFIXES):
            if name.startswith("empires") and "setup" not in name and p.pid not in exclude:
                return p
    return None


# Dấu nhận dạng bản exe tool đọc được (Rise of Rome 1.0, image base cố định): các lệnh trong mã game trỏ tới đúng 2
# biến tool dùng (SETTINGS_PTR 0x585E88, VISIBILITY_ROWS 0x7D70C8). Kiểm 2026-10-13: khớp đủ 6/6 ở 15 bản
# (AoE-HD EMPIRESX / _HD / _HDR / empires.exe / patch EMPIRESX1..4; AOE1R Empiresx / _n / _r), 0/6 ở Empires.exe của
# AOE1R (Age of Empires gốc, không có Rise of Rome).
BUILD_SIGNATURE = ((0x4037AA, 0x585E88), (0x481323, 0x585E88), (0x48CCCE, 0x585E88), (0x4B05E8, 0x585E88),
                   (0x41356A, 0x7D70C8), (0x427369, 0x7D70C8))


def check_build(pm):
    """(số chỗ khớp, tổng số) của dấu nhận dạng trong bộ nhớ game. 0 = chương trình khác hẳn, không đọc được."""
    hit = 0
    for va, val in BUILD_SIGNATURE:
        b = pm.try_read(va, 4)
        if b is not None and len(b) == 4 and struct.unpack("<I", b)[0] == val:
            hit += 1
    return hit, len(BUILD_SIGNATURE)


class ProcessMemory:
    def __init__(self, pid):
        self.pid = pid
        self.h = _k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not self.h:
            err = ctypes.get_last_error()
            raise MemoryError_(f"OpenProcess(pid={pid}) thất bại, mã lỗi Windows {err}. "
                               "Nếu game chạy với quyền Administrator thì tool cũng phải chạy Administrator.")

    def close(self):
        if self.h:
            _k32.CloseHandle(self.h)
            self.h = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def alive(self):
        return psutil.pid_exists(self.pid)

    def read(self, addr, size):
        if addr <= 0 or addr > 0x7FFFFFFF or size <= 0:
            raise MemoryError_(f"địa chỉ không hợp lệ {addr:#x} size {size}")
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t(0)
        ok = _k32.ReadProcessMemory(self.h, ctypes.c_void_p(addr), buf, size, ctypes.byref(got))
        if not ok or got.value != size:
            raise MemoryError_(f"ReadProcessMemory({addr:#x}, {size}) thất bại, lỗi {ctypes.get_last_error()}")
        return buf.raw

    def try_read(self, addr, size):
        try:
            return self.read(addr, size)
        except MemoryError_:
            return None

    def u8(self, a):  return self.read(a, 1)[0]
    def u16(self, a): return struct.unpack("<H", self.read(a, 2))[0]
    def i16(self, a): return struct.unpack("<h", self.read(a, 2))[0]
    def u32(self, a): return struct.unpack("<I", self.read(a, 4))[0]
    def i32(self, a): return struct.unpack("<i", self.read(a, 4))[0]
    def f32(self, a): return struct.unpack("<f", self.read(a, 4))[0]

    def cstr(self, addr, maxlen=128, encoding="cp1252"):
        if not addr:
            return ""
        data = self.try_read(addr, maxlen)
        if data is None:
            # gần biên trang: đọc từng khúc nhỏ
            out = b""
            while len(out) < maxlen:
                chunk = self.try_read(addr + len(out), 16)
                if chunk is None:
                    break
                out += chunk
                if b"\0" in chunk:
                    break
            data = out
        end = data.find(b"\0")
        if end >= 0:
            data = data[:end]
        return data.decode(encoding, errors="replace")

    def ptrs(self, addr, count):
        return struct.unpack(f"<{count}I", self.read(addr, count * 4))
