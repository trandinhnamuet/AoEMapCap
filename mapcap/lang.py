"""Chuỗi hiển thị của game từ language*.dll (bảng string resource).

AoE-HD có languagev.dll (tiếng Việt, mã TCVN3/ABC) và language.dll (tiếng Anh). Windows trả chuỗi ANSI đã
được map qua cp1252 nên phải đổi ngược về byte rồi giải mã TCVN3.
"""
import ctypes
import os

_LOAD_LIBRARY_AS_DATAFILE = 0x2
_LOAD_LIBRARY_AS_IMAGE_RESOURCE = 0x20

# TCVN3 (ABC): byte -> ký tự Unicode (chỉ phần >= 0xA1; các byte khác giữ nguyên ASCII)
_TCVN3 = {
    0xA1: "Ă", 0xA2: "Â", 0xA3: "Ê", 0xA4: "Ô", 0xA5: "Ơ", 0xA6: "Ư", 0xA7: "Đ",
    0xA8: "ă", 0xA9: "â", 0xAA: "ê", 0xAB: "ô", 0xAC: "ơ", 0xAD: "ư", 0xAE: "đ",
    0xB5: "à", 0xB6: "ả", 0xB7: "ã", 0xB8: "á", 0xB9: "ạ",
    0xBA: "ằ", 0xBB: "ẳ", 0xBC: "ẵ", 0xBD: "ắ", 0xBE: "ặ",
    0xC7: "ầ", 0xC8: "ẩ", 0xC9: "ẫ", 0xCA: "ấ", 0xCB: "ậ",
    0xCC: "è", 0xCD: "ẻ", 0xCE: "ẽ", 0xD0: "é", 0xD1: "ẹ",
    0xD2: "ề", 0xD3: "ể", 0xD4: "ễ", 0xD5: "ế", 0xD6: "ệ",
    0xD7: "ì", 0xD8: "ỉ", 0xDC: "ĩ", 0xDD: "í", 0xDE: "ị",
    0xDF: "ò", 0xE1: "ỏ", 0xE2: "õ", 0xE3: "ó", 0xE4: "ọ",
    0xE5: "ồ", 0xE6: "ổ", 0xE7: "ỗ", 0xE8: "ố", 0xE9: "ộ",
    0xEA: "ờ", 0xEB: "ở", 0xEC: "ỡ", 0xED: "ớ", 0xEE: "ợ",
    0xEF: "ù", 0xF0: "ủ", 0xF1: "ũ", 0xF2: "ú", 0xF3: "ụ",
    0xF5: "ừ", 0xF6: "ử", 0xF7: "ữ", 0xF8: "ứ", 0xF9: "ự",
    0xFA: "ỳ", 0xFB: "ỷ", 0xFC: "ỹ", 0xFD: "ý", 0xFE: "ỵ",
}


def tcvn3_to_unicode(s):
    """s là chuỗi Windows đã map cp1252 từ byte ANSI; trả về Unicode tiếng Việt."""
    try:
        b = s.encode("cp1252")
    except UnicodeEncodeError:
        b = s.encode("latin1", "replace")
    return "".join(_TCVN3.get(c, chr(c)) for c in b)


class GameStrings:
    """Đọc chuỗi theo id; ưu tiên languagev.dll (Việt), rồi language.dll (Anh)."""

    def __init__(self, game_dir, prefer_vietnamese=True):
        self.handles = []           # (handle, is_tcvn3)
        self.cache = {}
        order = ["languagev.dll", "language.dll"] if prefer_vietnamese else ["language.dll", "languagev.dll"]
        if os.name == "nt":
            k32 = ctypes.windll.kernel32
            for name in order:
                p = os.path.join(game_dir, name)
                if os.path.exists(p):
                    h = k32.LoadLibraryExW(p, None, _LOAD_LIBRARY_AS_DATAFILE | _LOAD_LIBRARY_AS_IMAGE_RESOURCE)
                    if h:
                        self.handles.append((h, name.lower().startswith("languagev")))
        self._buf = ctypes.create_unicode_buffer(1024) if os.name == "nt" else None

    def get(self, sid, default=None):
        if sid is None or sid <= 0 or not self.handles:
            return default
        if sid in self.cache:
            return self.cache[sid]
        u32 = ctypes.windll.user32
        val = default
        for h, tcvn in self.handles:
            n = u32.LoadStringW(h, int(sid), self._buf, 1024)
            if n:
                s = self._buf.value
                val = tcvn3_to_unicode(s) if tcvn else s
                break
        self.cache[sid] = val
        return val
