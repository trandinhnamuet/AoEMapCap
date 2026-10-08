"""Điểm vào cho AoE-MapCap Recorder.

    run_app.py            -> giao diện
    run_app.py --nogui    -> chạy dòng lệnh với cấu hình đã lưu (Video\\_settings.ini)
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _log_child_error(kind, exc, out_path):
    """Ghi lỗi của tiến trình con vào <thư mục đích>/_mapcap_child.log (không hiện hộp thoại PyInstaller)."""
    import traceback, datetime
    try:
        d = os.path.dirname(os.path.abspath(out_path)) if out_path else os.getcwd()
        with open(os.path.join(d, "_mapcap_child.log"), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {kind} lỗi: {exc!r}" + chr(10))
            f.write(traceback.format_exc() + chr(10))
    except Exception:  # noqa: BLE001
        pass

def main():
    import multiprocessing
    multiprocessing.freeze_support()          # tiến trình ghi (recproc) khi đóng gói PyInstaller
    if "--render-chunk" in sys.argv:
        i = sys.argv.index("--render-chunk")
        a = sys.argv[i + 1:i + 14]
        rec, out, k0, k1, width, fps, speed, fog, outline, gdir, ffmpeg, enc = a[:12]
        emulate = len(a) > 12 and a[12] == "1"
        try:
            from mapcap.offline import render_chunk
            render_chunk(rec, out, int(k0), int(k1), int(width), float(fps), float(speed), fog, float(outline),
                         gdir or None, ffmpeg, enc, emulate_ghosts=emulate)
        except BaseException as e:  # noqa: BLE001  - tiến trình con không được bật hộp thoại lỗi của PyInstaller
            _log_child_error("render-chunk", e, out)
            sys.exit(3)
        return
    if "--render-raw" in sys.argv:
        for _s in (sys.stdout, sys.stderr):
            try:
                _s.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass
        i = sys.argv.index("--render-raw")
        rec = sys.argv[i + 1]
        out = sys.argv[i + 2] if len(sys.argv) > i + 2 and not sys.argv[i + 2].startswith("--") else os.path.splitext(rec)[0] + ".mp4"
        kw = {}
        for a in sys.argv[1:]:
            if a.startswith("--width="): kw["width"] = int(a[8:])
            if a.startswith("--fog="): kw["fog_dim"] = a[6:]          # số hoặc 'dither'
            elif a.startswith("--fps="): kw["fps"] = float(a[6:])
            elif a.startswith("--speed="): kw["speed"] = float(a[8:])
            elif a.startswith("--workers="): kw["workers"] = int(a[10:])
            elif a.startswith("--game-dir="): kw["game_dir"] = a[11:]
        from mapcap.engine import load_config
        from mapcap.offline import render_raw
        cfg = load_config()
        kw.setdefault("game_dir", cfg.game_dir)
        render_raw(rec, out, log=print, **kw)
        return
    if "--render-still" in sys.argv:
        i = sys.argv.index("--render-still")
        try:
            from mapcap.engine import render_still_cli
            render_still_cli(*sys.argv[i + 1:i + 6])
        except BaseException as e:  # noqa: BLE001
            _log_child_error("render-still", e, sys.argv[i + 2] if len(sys.argv) > i + 2 else "")
            sys.exit(3)
        return
    if "--nogui" in sys.argv:
        for _s in (sys.stdout, sys.stderr):
            try:
                _s.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass
        from mapcap.engine import Engine, Logger, load_config
        cfg = load_config()
        for a in sys.argv[1:]:
            if a.startswith("--fps="):
                cfg.fps = float(a[6:])
            elif a.startswith("--capture="):
                cfg.capture_fps = float(a[10:])
            elif a.startswith("--width="):
                cfg.video_width = int(a[8:])
        cfg.clamp()
        stop = threading.Event()
        try:
            Engine(cfg, Logger(cfg.log_path()), stop).run()
        except KeyboardInterrupt:
            stop.set()
        return
    from mapcap.gui import main as gui_main
    gui_main()


if __name__ == "__main__":
    main()
