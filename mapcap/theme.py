"""Giao diện tối kiểu XArena cho AoE-MapCap (tkinter / ttk).

Bảng màu lấy từ ảnh giao diện XArena (C:\\Program Files\\XArena\\data\\flutter_assets): nền than tối, đỏ máu chuyển
sắc (#c00820 -> #680000), viền vàng kim (#c09058) cho mục nổi bật / đang chọn, font Roboto (đóng gói trong
assets/fonts, giấy phép Apache 2.0). Nút chính là ảnh PIL (đỏ chuyển sắc, viền vàng) dùng làm phần tử ảnh của ttk.

    theme.apply(root)        -> nạp font, đặt kiểu ttk, thanh tiêu đề Windows tối
    theme.C                  -> bảng màu
    theme.F(size, weight)    -> font
"""
import ctypes
import os
import sys
import tkinter as tk
from tkinter import ttk

C = {
    "bg": "#16161b",          # nền cửa sổ
    "bg2": "#1d1d23",         # nền phụ (hàng chẵn, ô nhập)
    "panel": "#202027",       # thẻ
    "panel2": "#28282f",      # thẻ nổi / tiêu đề bảng
    "sidebar": "#101014",
    "line": "#33333c",
    "line2": "#2a2a31",
    "text": "#ececf0",
    "muted": "#9a9aa6",
    "dim": "#6c6c78",
    "red": "#c00820",
    "red_hi": "#e01a30",
    "red_lo": "#680000",
    "red_sel": "#3a0c12",     # nền dòng / mục đang chọn
    "gold": "#c09058",
    "gold_hi": "#e2b878",
    "green": "#4cc779",
    "lose": "#ff6b6b",
    "field": "#111116",
}
FAMILY = "Roboto"
_fonts_loaded = False
APPLIED = False               # đã áp giao diện tối (bảng trận đổi màu chữ thắng/thua, dòng xen kẽ)
_images = []                  # giữ tham chiếu PhotoImage (tk không giữ)


def _assets_dir():
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets")


def load_fonts():
    """Nạp Roboto riêng cho tiến trình này (AddFontResourceEx FR_PRIVATE), không cài vào máy."""
    global _fonts_loaded, FAMILY
    if _fonts_loaded:
        return
    _fonts_loaded = True
    d = os.path.join(_assets_dir(), "fonts")
    ok = False
    try:
        for f in ("Roboto-Regular.ttf", "Roboto-Medium.ttf", "Roboto-Bold.ttf"):
            p = os.path.join(d, f)
            if os.path.exists(p) and ctypes.windll.gdi32.AddFontResourceExW(p, 0x10, 0):
                ok = True
    except Exception:  # noqa: BLE001
        ok = False
    if not ok:
        FAMILY = "Segoe UI"


def F(size=10, weight="normal"):
    return (FAMILY, size, weight)


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _button_image(top, bottom, border, w=48, h=34, r=6, glow=None):
    """Ảnh nút bo góc: nền chuyển sắc dọc top -> bottom, viền 1 px; tk.PhotoImage (cần PIL)."""
    from PIL import Image, ImageDraw, ImageTk
    s = 3                                                   # vẽ to rồi thu nhỏ cho mịn góc
    im = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    grad = Image.new("RGBA", (w * s, h * s))
    t, b = _rgb(top), _rgb(bottom)
    gd = ImageDraw.Draw(grad)
    for y in range(h * s):
        k = y / max(1, h * s - 1)
        gd.line([(0, y), (w * s, y)], fill=tuple(int(t[i] + (b[i] - t[i]) * k) for i in range(3)) + (255,))
    mask = Image.new("L", (w * s, h * s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w * s - 1, h * s - 1], radius=r * s, fill=255)
    im.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, w * s - 1, h * s - 1], radius=r * s, outline=_rgb(border) + (255,), width=s)
    if glow:                                                # vạch sáng mảnh phía trên (như nút XArena)
        d.line([(r * s, s * 2), (w * s - r * s, s * 2)], fill=_rgb(glow) + (110,), width=s)
    im = im.resize((w, h), Image.LANCZOS)
    ph = ImageTk.PhotoImage(im)
    _images.append(ph)
    return ph


def _check_image(checked, size=18):
    """Ô tích: vuông bo góc tối viền xám; đã tích = đỏ chuyển sắc viền vàng + dấu ✓ trắng."""
    from PIL import Image, ImageDraw, ImageTk
    s = 4
    im = Image.new("RGBA", (size * s, size * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    box = [s, s, size * s - s - 1, size * s - s - 1]
    if checked:
        d.rounded_rectangle(box, radius=4 * s, fill=_rgb("#b80c1e") + (255,), outline=_rgb(C["gold"]) + (255,), width=s)
        d.line([(5 * s, 9.5 * s), (8 * s, 12.5 * s), (13.5 * s, 6 * s)], fill=(255, 255, 255, 255), width=int(2.2 * s),
               joint="curve")
    else:
        d.rounded_rectangle(box, radius=4 * s, fill=_rgb(C["field"]) + (255,), outline=_rgb("#4a4a54") + (255,), width=s)
    im = im.resize((size, size), Image.LANCZOS)
    ph = ImageTk.PhotoImage(im)
    _images.append(ph)
    return ph


def _dark_titlebar(root):
    """Windows 10/11: thanh tiêu đề tối (DWMWA_USE_IMMERSIVE_DARK_MODE) + màu tiêu đề trùng nền (Windows 11)."""
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
        dwm = ctypes.windll.dwmapi
        on = ctypes.c_int(1)
        for attr in (20, 19):
            if dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), ctypes.sizeof(on)) == 0:
                break
        r, g, b = _rgb(C["sidebar"])
        color = ctypes.c_int(r | (g << 8) | (b << 16))
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(color), ctypes.sizeof(color))
    except Exception:  # noqa: BLE001
        pass


def dark_window(win):
    """Áp nền tối + thanh tiêu đề tối cho Toplevel (hộp thoại)."""
    try:
        win.configure(bg=C["bg"])
    except tk.TclError:
        pass
    win.after(10, lambda: _dark_titlebar(win))


def apply(root):
    global APPLIED
    APPLIED = True
    load_fonts()
    root.configure(bg=C["bg"])
    st = ttk.Style(root)
    st.theme_use("clam")
    base = F(10)
    # font mặc định qua các font tên sẵn của Tk (không dùng option_add("*Font"): nó đè font riêng của từng kiểu ttk)
    from tkinter import font as tkfont
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont", "TkTooltipFont"):
        try:
            tkfont.nametofont(name).configure(family=FAMILY, size=10)
        except tk.TclError:
            pass
    for k, v in (("*TCombobox*Listbox.background", C["field"]), ("*TCombobox*Listbox.foreground", C["text"]),
                 ("*TCombobox*Listbox.selectBackground", C["red_sel"]), ("*TCombobox*Listbox.selectForeground", "#fff"),
                 ("*TCombobox*Listbox.font", base), ("*Toplevel.background", C["bg"])):
        root.option_add(k, v)
    st.configure(".", background=C["bg"], foreground=C["text"], font=base, bordercolor=C["line"],
                 lightcolor=C["panel2"], darkcolor=C["bg"], troughcolor=C["field"], focuscolor=C["gold"],
                 selectbackground=C["red_sel"], selectforeground="#ffffff", fieldbackground=C["field"],
                 insertcolor=C["text"], arrowcolor=C["muted"])
    st.map(".", foreground=[("disabled", C["dim"])])
    # ---- khung, chữ
    st.configure("TFrame", background=C["bg"])
    st.configure("Card.TFrame", background=C["panel"])
    st.configure("Side.TFrame", background=C["sidebar"])
    st.configure("Notice.TFrame", background="#2b2112")
    st.configure("TLabel", background=C["bg"], foreground=C["text"])
    st.configure("Card.TLabel", background=C["panel"], foreground=C["text"])
    st.configure("Muted.TLabel", background=C["bg"], foreground=C["muted"])
    st.configure("CardMuted.TLabel", background=C["panel"], foreground=C["muted"])
    st.configure("CardTitle.TLabel", background=C["panel"], foreground="#ffffff", font=F(12, "bold"))
    st.configure("Title.TLabel", background=C["bg"], foreground="#ffffff", font=F(18, "bold"))
    st.configure("Notice.TLabel", background="#2b2112", foreground=C["gold_hi"], font=F(10, "bold"))
    st.configure("Detail.TLabel", background=C["bg"], foreground=C["muted"])
    # ---- nút: chính (đỏ chuyển sắc viền vàng), phụ (tối viền xám, rê chuột viền vàng)
    try:
        red = _button_image("#d0182c", "#7a0612", C["gold"], glow="#ff8080")
        red_h = _button_image("#e8283c", "#900818", C["gold_hi"], glow="#ffa0a0")
        red_p = _button_image("#8a0a16", "#5a0008", C["gold"])
        red_d = _button_image("#3a3a42", "#2c2c33", "#45454e")
        sec = _button_image("#2c2c34", "#24242b", "#44444e")
        sec_h = _button_image("#34343d", "#2a2a32", C["gold"])
        sec_p = _button_image("#202027", "#1b1b21", C["gold"])
        sec_d = _button_image("#24242a", "#202026", "#34343c")
        st.element_create("Accent.Button.border", "image", red, ("disabled", red_d), ("pressed", red_p),
                          ("active", red_h), border=(8, 8, 8, 8), sticky="nsew")
        st.element_create("Sec.Button.border", "image", sec, ("disabled", sec_d), ("pressed", sec_p),
                          ("active", sec_h), border=(8, 8, 8, 8), sticky="nsew")
        for name, el in (("Accent.TButton", "Accent.Button.border"), ("TButton", "Sec.Button.border")):
            st.layout(name, [(el, {"sticky": "nsew", "children": [
                ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})]})])
    except Exception:  # noqa: BLE001  - thiếu PIL: nút phẳng
        st.configure("Accent.TButton", background=C["red"])
    st.configure("TButton", foreground=C["text"], padding=(14, 6), font=F(10), anchor="center")
    st.map("TButton", foreground=[("disabled", C["dim"])])
    st.configure("Accent.TButton", foreground="#ffffff", padding=(18, 7), font=F(11, "bold"), anchor="center")
    st.map("Accent.TButton", foreground=[("disabled", C["dim"])])
    # ---- ô nhập
    for w in ("TEntry", "TSpinbox", "TCombobox"):
        st.configure(w, fieldbackground=C["field"], foreground=C["text"], bordercolor=C["line"], lightcolor=C["field"],
                     darkcolor=C["field"], insertcolor=C["text"], padding=(8, 5), arrowsize=14, background=C["panel2"])
        st.map(w, bordercolor=[("focus", C["gold"])], lightcolor=[("focus", C["gold"])],
               fieldbackground=[("readonly", C["field"]), ("disabled", C["bg2"])],
               foreground=[("disabled", C["dim"])], background=[("active", C["panel2"])])
    st.configure("Search.TEntry", padding=(10, 6))
    # ---- ô tích (ảnh: ô tối / ô đỏ có dấu ✓)
    try:
        off, on = _check_image(False), _check_image(True)
        st.element_create("Dark.Checkbutton.indicator", "image", off, ("selected", on), width=28, sticky="w")
        for name in ("TCheckbutton", "Card.TCheckbutton"):
            st.layout(name, [("Checkbutton.padding", {"sticky": "nswe", "children": [
                ("Dark.Checkbutton.indicator", {"side": "left", "sticky": ""}),
                ("Checkbutton.label", {"side": "left", "sticky": "nswe", "expand": 1})]})])
    except Exception:  # noqa: BLE001
        pass
    for w, bg in (("TCheckbutton", C["bg"]), ("Card.TCheckbutton", C["panel"])):
        st.configure(w, background=bg, foreground=C["text"], indicatorbackground=C["field"], indicatorforeground="#fff",
                     indicatormargin=(0, 0, 8, 0), padding=(2, 4, 2, 4), focuscolor=bg)
        st.configure(w + ".label", padding=(10, 0, 0, 0))
        st.map(w, indicatorbackground=[("selected", C["red"]), ("active", C["panel2"])],
               background=[("active", bg)], foreground=[("disabled", C["dim"])])
    # ---- bảng
    st.configure("Treeview", background=C["panel"], fieldbackground=C["panel"], foreground=C["text"], rowheight=30,
                 bordercolor=C["line2"], lightcolor=C["panel"], darkcolor=C["panel"], font=F(10))
    st.map("Treeview", background=[("selected", C["red_sel"])], foreground=[("selected", "#ffffff")])
    st.configure("Treeview.Heading", background=C["panel2"], foreground=C["muted"], relief="flat", font=F(9, "bold"),
                 padding=(8, 7), bordercolor=C["line2"], lightcolor=C["panel2"], darkcolor=C["panel2"])
    st.map("Treeview.Heading", background=[("active", "#32323a")], foreground=[("active", C["gold_hi"])])
    # ---- thanh cuộn, tiến độ
    for w in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
        st.configure(w, background="#34343c", troughcolor=C["bg"], bordercolor=C["bg"], lightcolor="#34343c",
                     darkcolor="#34343c", arrowcolor=C["muted"], gripcount=0, relief="flat")
        st.map(w, background=[("active", "#44444e")])
    st.configure("Horizontal.TProgressbar", background=C["red"], troughcolor=C["field"], bordercolor=C["line"],
                 lightcolor=C["red_hi"], darkcolor=C["red_lo"])
    st.configure("TLabelframe", background=C["panel"], bordercolor=C["line"])
    st.configure("TLabelframe.Label", background=C["panel"], foreground=C["gold_hi"], font=F(10, "bold"))
    _dark_titlebar(root)
    return st


def text_widget_colors():
    """Màu cho tk.Text (nhật ký, ghi chú cập nhật)."""
    return {"bg": C["field"], "fg": "#d2d2da", "insertbackground": C["text"], "selectbackground": C["red_sel"],
            "relief": "flat", "highlightthickness": 1, "highlightbackground": C["line"], "highlightcolor": C["gold"],
            "borderwidth": 0}


def gradient_photo(w, h, left, right, glow_at=0.85, spread=1 / 3):
    """Ảnh nền ngang cho đầu trang: tối bên trái, ánh đỏ phía phải (giống băng rôn XArena)."""
    from PIL import Image, ImageDraw, ImageFilter, ImageTk
    w, h = max(2, int(w)), max(2, int(h))
    im = Image.new("RGB", (w, h), _rgb(left))
    glow = Image.new("RGB", (w, h), _rgb(left))     # ngoài vùng ánh đỏ giữ đúng màu nền (nút không bị viền khung)
    d = ImageDraw.Draw(glow)
    cx = int(w * glow_at)
    r = int(w * spread)
    d.ellipse([cx - r, -h, cx + r, h * 2], fill=_rgb(right))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=max(8, h // 2)))
    im = Image.blend(im, glow, 0.55)
    ImageDraw.Draw(im).line([(0, h - 1), (w, h - 1)], fill=_rgb(C["gold"]), width=1)
    ph = ImageTk.PhotoImage(im)
    _images.append(ph)
    if len(_images) > 64:
        del _images[:16]
    return ph
