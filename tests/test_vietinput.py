"""Bộ gõ tiếng Việt trong app (mapcap/vietinput.py): Telex + VNI ghép đúng từ, gõ lặp thì gỡ dấu, giữ chữ hoa; gắn vào
tk.Text / ttk.Entry (ô ghi chú Báo cáo hack - người dùng 13/11: app chạy quyền Admin nên UniKey quyền thường không gõ
được); bộ gõ ngoài gửi được chữ có dấu thì app thôi tự ghép.

    python tests/test_vietinput.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

from mapcap import vietinput as V  # noqa: E402


def typed(keys, method="telex", modern=False):
    """Gõ lần lượt các phím như VietInput._key làm (từ = chuỗi chữ cái liền trước con trỏ)."""
    out = ""
    for ch in keys:
        n = 0
        while n < len(out) and n < V.MAX_WORD and out[len(out) - 1 - n].isalpha():
            n += 1
        word = out[len(out) - n:] if n else ""
        new = V.compose(word, ch, method, modern) if word else None
        out = out + ch if new is None else out[:len(out) - n] + new
    return out


TELEX = {
    "tieengs vieetj": "tiếng việt", "hoaf": "hòa", "thuyr": "thủy", "nguyeenx": "nguyễn", "dduwowngf": "đường",
    "nguwowif": "người", "nguowif": "người", "muaw": "mưa", "muwaf": "mừa", "hoawcj": "hoặc", "quaans": "quấn",
    "gias": "giá", "gif": "gì", "xoas": "xóa", "toans": "toán", "khoong": "không", "luuw": "lưu", "raats": "rất",
    "DDaay": "Đây", "AS": "Á", "Vieejt": "Việt", "hack xoas nhaf chinhs phuts 12": "hack xóa nhà chính phút 12",
    "quaan ddichj ddieeuf khieenr thus": "quân địch điều khiển thú", "taif nguyeen tawng baats thuwowngf": "tài nguyên tăng bất thường",
    "ass": "as", "aaa": "aa", "ddd": "dd", "eee": "ee", "ooo": "oo", "aww": "aw", "xoasz": "xoa", "banr ddoof": "bản đồ",
    "cuwowpx": "cưỡp", "uwowc": "ươc", "bieets": "biết", "khuyeen": "khuyên", "quyeets": "quyết", "gioir": "giỏi",
    "nghieeng": "nghiêng", "chuwa": "chưa", "thuwaf": "thừa", "sz": "sz", "123": "123", "p2 xoas": "p2 xóa",
}
MODERN = {"hoaf": "hoà", "thuyr": "thuỷ", "xoas": "xoá", "toans": "toán", "quyeets": "quyết"}
VNI = {
    "tie6ng1 vie65t": "tiếng việt", "d9u7o7ng2": "đường", "ngu7o7i2": "người", "hoa2": "hòa", "hoa85c": "hoặc",
    "mu7a": "mưa", "kho6ng": "không", "D9a6y": "Đây", "a11": "a1", "a66": "a6", "d99": "d9", "phu1t 12": "phút 12",
    "nha2 chi1nh": "nhà chính", "to1an": "tóan", "toan1": "toán",
}


def main():
    bad = []
    for table, method, modern in ((TELEX, "telex", False), (MODERN, "telex", True), (VNI, "vni", False)):
        for keys, want in table.items():
            got = typed(keys, method, modern)
            if got != want:
                bad.append((method, modern, keys, got, want))
    assert not bad, bad
    print(f"ghép dấu: {len(TELEX)} chuỗi Telex, {len(MODERN)} kiểu bỏ dấu mới, {len(VNI)} chuỗi VNI: OK")
    m, md = V.unikey_settings()
    assert m in ("telex", "vni") and isinstance(md, bool)
    print("đọc thiết lập UniKey trên máy:", m, "| bỏ dấu kiểu mới" if md else "| bỏ dấu kiểu cũ")

    # gắn vào ô nhập thật (cửa sổ ẩn, không hiện lên màn hình)
    import tkinter as tk
    from tkinter import ttk
    root = tk.Tk()
    root.withdraw()
    try:
        txt = tk.Text(root)
        ent = ttk.Entry(root)
        on = [True]
        vi_t = V.attach(txt, enabled=lambda: on[0], method="telex", modern=False)
        vi_e = V.attach(ent, method="telex", modern=False)

        class Ev:
            def __init__(self, ch, state=0):
                self.char, self.state = ch, state

        def press(vi, w, s):
            for ch in s:
                if vi._key(Ev(ch)) != "break":
                    w.insert("insert", ch)

        press(vi_t, txt, "xoas nhaf chinhs\nphuts 12 ddieeuf khieenr")
        assert txt.get("1.0", "end-1c") == "xóa nhà chính\nphút 12 điều khiển", repr(txt.get("1.0", "end-1c"))
        txt.mark_set("insert", "1.3")                      # con trỏ giữa dòng: sau "xóa"
        press(vi_t, txt, "x")
        assert txt.get("1.0", "1.end") == "xõa nhà chính", txt.get("1.0", "1.end")
        on[0] = False                                      # tắt ô tích Gõ tiếng Việt
        txt.mark_set("insert", "end-1c")
        press(vi_t, txt, " aa")
        assert txt.get("1.0", "end-1c").endswith(" aa")
        press(vi_e, ent, "ddaay laf")
        assert ent.get() == "đây là", ent.get()
        assert vi_e._key(Ev("a", 0x4)) is None             # Ctrl+A không bị ăn
        vi_e._key(Ev("ư"))                                 # bộ gõ ngoài gửi được chữ có dấu -> thôi tự ghép
        ent.insert("insert", " ")
        press(vi_e, ent, "aa")
        assert ent.get().endswith(" aa") and vi_e.external
        print("gắn vào tk.Text / ttk.Entry: ghép tại con trỏ, nhiều dòng, tắt bằng ô tích, Ctrl+phím giữ nguyên, bộ gõ ngoài "
              "hoạt động thì thôi tự ghép: OK")
    finally:
        root.destroy()
    print("OK test_vietinput")


if __name__ == "__main__":
    main()
