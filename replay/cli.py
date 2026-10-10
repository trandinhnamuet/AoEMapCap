"""Dòng lệnh của AoE-Replay (dùng chung cho run_replay.py, python -m replay và run_app.py --replay).

    <file.aoerec>            mở file (không có thì hiện bảng các trận đã ghi để chọn)
    --folder=<thư mục>       thư mục chứa .aoerec cho bảng chọn trận (mặc định Video\Raw cạnh exe)
    --game-dir=<thư mục>     thư mục game AoE-HD để lấy đồ hoạ (mặc định: ghi trong file, rồi các chỗ quen thuộc)
    --selftest=<thư mục>     chạy kịch bản tự kiểm tra trên cửa sổ ẩn, lưu ảnh vào thư mục
"""
import os


def main(argv):
    import sys
    for st in (sys.stdout, sys.stderr):          # exe --windowed: console cp1252 không in được tiếng Việt
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    path = game_dir = selftest = folder = None
    for a in argv:
        if a.startswith("--game-dir="):
            game_dir = a[len("--game-dir="):] or None
        elif a.startswith("--folder="):
            folder = a[len("--folder="):] or None
        elif a.startswith("--selftest="):
            selftest = a[len("--selftest="):]
        elif not a.startswith("--") and path is None:
            path = a
    if path is None:
        from .picker import pick_match
        path = pick_match(folder)
        if not path:
            return 0
    from .viewer import main as viewer_main, find_game_dir, valid_game_dir
    if not selftest:
        try:
            from mapcap.rawrec import read_header
            hdr = read_header(path)
        except Exception:  # noqa: BLE001
            hdr = None
        if find_game_dir(hdr, game_dir) is None:          # máy không có game ở chỗ quen thuộc: hỏi thư mục
            import tkinter as tk
            from tkinter import filedialog, messagebox
            root = tk.Tk()
            root.withdraw()
            d = filedialog.askdirectory(title="Chọn thư mục game AoE-HD (để lấy hình ảnh, âm thanh của game)")
            if not d or not valid_game_dir(d):
                if d:
                    messagebox.showerror("AoE-Replay", "Thư mục này không có data\empires.dat và data\graphic.drs của AoE-HD.")
                root.destroy()
                return 1
            root.destroy()
            game_dir = d
    return viewer_main(os.path.abspath(path), game_dir, selftest)
