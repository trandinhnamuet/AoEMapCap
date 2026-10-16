"""Biểu tượng ở khay hệ thống (góc phải thanh tác vụ) bằng Win32 Shell_NotifyIcon qua ctypes, không cần thư viện thêm.

Bấm X trên cửa sổ AoE-MapCap -> ẩn cửa sổ, app vẫn chạy và ghi trận; biểu tượng có chấm màu theo trạng thái (đỏ = đang
ghi, vàng = sẵn sàng), rê chuột thấy trạng thái + đồng hồ. Bấm trái: mở lại cửa sổ; bấm phải: menu Mở / Bắt đầu-Dừng ghi
/ Thoát. Cửa sổ ẩn + vòng nhận tin nhắn chạy ở luồng riêng; lệnh từ menu đưa về luồng Tk qua hàm on_action (hàng đợi).
"""
import ctypes
import ctypes.wintypes as wt
import io
import threading

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
HICON = wt.HANDLE

WM_DESTROY, WM_CLOSE, WM_COMMAND, WM_NULL = 0x0002, 0x0010, 0x0111, 0x0000
WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_RBUTTONUP, WM_CONTEXTMENU = 0x0202, 0x0203, 0x0205, 0x007B
WM_APP = 0x8000
WM_TRAY = WM_APP + 1
NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETVERSION = 0, 1, 2, 4
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO, NIF_SHOWTIP = 0x1, 0x2, 0x4, 0x10, 0x80
NIIF_INFO = 0x1
MF_STRING, MF_SEPARATOR, MF_GRAYED = 0x0, 0x800, 0x1
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80
SM_CXSMICON = 49
ID_OPEN, ID_TOGGLE, ID_QUIT = 1, 2, 3


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", HICON), ("hCursor", wt.HANDLE),
                ("hbrBackground", wt.HANDLE), ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR),
                ("hIconSm", HICON)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT), ("uFlags", wt.UINT),
                ("uCallbackMessage", wt.UINT), ("hIcon", HICON), ("szTip", wt.WCHAR * 128), ("dwState", wt.DWORD),
                ("dwStateMask", wt.DWORD), ("szInfo", wt.WCHAR * 256), ("uVersion", wt.UINT),
                ("szInfoTitle", wt.WCHAR * 64), ("dwInfoFlags", wt.DWORD), ("guidItem", ctypes.c_byte * 16),
                ("hBalloonIcon", HICON)]


user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
user32.CreateWindowExW.restype = wt.HWND
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = wt.ATOM
user32.UnregisterClassW.argtypes = [wt.LPCWSTR, wt.HINSTANCE]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.SendMessageW.restype = LRESULT
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.DestroyWindow.argtypes = [wt.HWND]
user32.CreatePopupMenu.restype = wt.HMENU
user32.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
user32.SetMenuDefaultItem.argtypes = [wt.HMENU, wt.UINT, wt.UINT]
user32.TrackPopupMenu.argtypes = [wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.LPVOID]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.DestroyMenu.argtypes = [wt.HMENU]
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
user32.RegisterWindowMessageW.argtypes = [wt.LPCWSTR]
user32.RegisterWindowMessageW.restype = wt.UINT
user32.CreateIconFromResourceEx.argtypes = [ctypes.c_void_p, wt.DWORD, wt.BOOL, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                            wt.UINT]
user32.CreateIconFromResourceEx.restype = HICON
user32.DestroyIcon.argtypes = [HICON]
shell32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconW.restype = wt.BOOL
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.GetModuleHandleW.restype = wt.HMODULE

DOT = {"rec": (224, 26, 48), "armed": (226, 184, 120)}


def make_icon(ico_path, dot=None):
    """HICON cỡ khay từ app.ico, góc phải dưới có chấm màu (dot = 'rec' / 'armed' / None). Ảnh PNG đưa thẳng cho
    CreateIconFromResourceEx (Windows Vista+ nhận PNG)."""
    from PIL import Image, ImageDraw
    size = max(16, user32.GetSystemMetrics(SM_CXSMICON)) * 2      # vẽ to rồi để Windows thu nhỏ: nét chấm mịn
    size = min(size, 64)
    im = Image.open(ico_path).convert("RGBA").resize((size, size), Image.LANCZOS)
    if dot in DOT:
        d = ImageDraw.Draw(im)
        r = size * 0.27
        cx = cy = size - r - 1
        d.ellipse([cx - r - size * 0.06, cy - r - size * 0.06, cx + r + size * 0.06, cy + r + size * 0.06],
                  fill=(16, 16, 20, 255))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=DOT[dot] + (255,))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    data = buf.getvalue()
    cbuf = ctypes.create_string_buffer(data, len(data))
    small = user32.GetSystemMetrics(SM_CXSMICON) or 16
    return user32.CreateIconFromResourceEx(cbuf, len(data), True, 0x00030000, small, small, 0)


class Tray:
    """on_action(name): 'open' | 'toggle' | 'quit' — gọi từ luồng khay, hàm nhận phải tự đưa về luồng giao diện."""

    def __init__(self, ico_path, on_action, tooltip="AoE-MapCap"):
        self.ico_path = ico_path
        self.on_action = on_action
        self.tip = tooltip
        self.toggle_label = "Bắt đầu ghi"
        self.hwnd = None
        self.icons = {}
        self.kind = None
        self.ready = threading.Event()
        self.ok = False
        self._lock = threading.Lock()
        self._thread = None
        self._cls = f"AoEMapCapTray{id(self)}"

    # ---- vòng đời -------------------------------------------------------------------
    def start(self, timeout=5):
        self._thread = threading.Thread(target=self._run, name="tray", daemon=True)
        self._thread.start()
        self.ready.wait(timeout)
        return self.ok

    def stop(self):
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(3)

    def _run(self):
        try:
            for k in (None, "armed", "rec"):
                try:
                    self.icons[k] = make_icon(self.ico_path, k)
                except Exception:  # noqa: BLE001
                    self.icons[k] = None
            self._wndproc = WNDPROC(self._proc)              # giữ tham chiếu: không để bị dọn khi đang dùng
            hinst = kernel32.GetModuleHandleW(None)
            wc = WNDCLASSEXW(cbSize=ctypes.sizeof(WNDCLASSEXW), lpfnWndProc=self._wndproc, hInstance=hinst,
                             lpszClassName=self._cls)
            if not user32.RegisterClassExW(ctypes.byref(wc)):
                return
            self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
            self.hwnd = user32.CreateWindowExW(0, self._cls, "AoE-MapCap tray", 0, 0, 0, 0, 0, None, None, hinst, None)
            if not self.hwnd:
                return
            self.ok = self._notify(NIM_ADD, NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP)
            nid = self._nid(0)
            nid.uVersion = 4                                 # NOTIFYICON_VERSION_4
            shell32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(nid))
            self.ready.set()
            msg = wt.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            self.ok = False
            self.ready.set()
            for h in self.icons.values():
                if h:
                    user32.DestroyIcon(h)
            try:
                user32.UnregisterClassW(self._cls, kernel32.GetModuleHandleW(None))
            except Exception:  # noqa: BLE001
                pass
            self.hwnd = None

    # ---- Shell_NotifyIcon -------------------------------------------------------------
    def _nid(self, flags):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = flags
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self.icons.get(self.kind) or self.icons.get(None)
        nid.szTip = self.tip[:127]
        return nid

    def _notify(self, op, flags, title=None, text=None):
        if not self.hwnd:
            return False
        with self._lock:
            nid = self._nid(flags)
            if title is not None:
                nid.szInfoTitle = title[:63]
                nid.szInfo = (text or "")[:255]
                nid.dwInfoFlags = NIIF_INFO
            return bool(shell32.Shell_NotifyIconW(op, ctypes.byref(nid)))

    def update(self, tooltip=None, kind=None, toggle_label=None):
        """Đổi dòng rê chuột / chấm màu biểu tượng ('rec', 'armed', None) / chữ mục Bắt đầu-Dừng ghi của menu."""
        if toggle_label:
            self.toggle_label = toggle_label
        changed = False
        if tooltip is not None and tooltip != self.tip:
            self.tip = tooltip
            changed = True
        if kind != self.kind:
            self.kind = kind
            changed = True
        if changed:
            self._notify(NIM_MODIFY, NIF_ICON | NIF_TIP | NIF_SHOWTIP)

    def balloon(self, title, text):
        """Thông báo nhỏ của Windows cạnh khay (vd lần đầu ẩn xuống khay)."""
        return self._notify(NIM_MODIFY, NIF_INFO, title, text)

    # ---- tin nhắn ------------------------------------------------------------------
    def _proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAY:
                ev = lparam & 0xFFFF                          # NOTIFYICON_VERSION_4: sự kiện ở word thấp
                if ev in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    self.on_action("open")
                elif ev in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self._menu()
                return 0
            if msg == getattr(self, "_taskbar_created", -1) and msg:   # explorer khởi động lại: gắn lại biểu tượng
                self._notify(NIM_ADD, NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP)
                return 0
            if msg == WM_CLOSE:
                self._notify(NIM_DELETE, 0)
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
        except Exception:  # noqa: BLE001  - lỗi trong hàm gọi lại không được làm sập tiến trình
            pass
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _menu(self):
        m = user32.CreatePopupMenu()
        user32.AppendMenuW(m, MF_STRING, ID_OPEN, "Mở AoE-MapCap")
        user32.AppendMenuW(m, MF_STRING, ID_TOGGLE, self.toggle_label)
        user32.AppendMenuW(m, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(m, MF_STRING, ID_QUIT, "Thoát")
        user32.SetMenuDefaultItem(m, ID_OPEN, 0)
        pt = wt.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self.hwnd)                # để menu tự đóng khi bấm ra ngoài
        cmd = user32.TrackPopupMenu(m, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY, pt.x, pt.y, 0, self.hwnd, None)
        user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(m)
        act = {ID_OPEN: "open", ID_TOGGLE: "toggle", ID_QUIT: "quit"}.get(cmd)
        if act:
            self.on_action(act)
