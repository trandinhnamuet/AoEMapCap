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
    from .viewer import main as viewer_main
    return viewer_main(os.path.abspath(path), game_dir, selftest)
