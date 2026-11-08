"""Trận đang ghi không mở / chép được (v34, luôn ghi + chống xem replay khi ván còn đang đánh).

    python tests/test_rec_exclusive.py

Bộ ghi mở file .aoerec không chia sẻ (rawrec.open_exclusive): trong lúc ghi, đọc / chép / trình xem / bảng trận đều
bị Windows từ chối; đóng file là mở bình thường. Giao diện: Xem replay / Xuất video với trận đang ghi báo "đang được
ghi". File thử ở Video\\_test\\rec_exclusive; không hiện hộp thoại (hàm báo thay bằng hàm ghi lại).
"""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
os.environ["AOEMAPCAP_TELEMETRY"] = "0"

from mapcap import rawrec  # noqa: E402

OUT = os.path.join(ROOT, "Video", "_test", "rec_exclusive")
REAL = os.path.join(ROOT, "Video", "Raw", "2026-10-07_104005_tran1.aoerec")


def main():
    import inspect
    assert "open_exclusive(path)" in inspect.getsource(rawrec.RawWriter.__init__), "bộ ghi phải mở file độc quyền"
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    path = os.path.join(OUT, "dang_ghi.aoerec")
    data = open(REAL, "rb").read()                       # nội dung một trận thật (để sau khi đóng mở được thật)
    f = rawrec.open_exclusive(path)
    try:
        f.write(data)
        f.flush()
        for what, fn in (("đọc", lambda: open(path, "rb").read(1)),
                         ("chép", lambda: shutil.copy(path, os.path.join(OUT, "ban_sao.aoerec"))),
                         ("đổi tên", lambda: os.rename(path, path + ".x"))):
            try:
                fn()
                raise AssertionError(f"{what} file đang ghi phải bị từ chối")
            except PermissionError:
                pass
        assert os.path.getsize(path) == len(data), "xem cỡ / giờ sửa vẫn được (bảng trận, dọn trận)"
        print("đang ghi: đọc / chép / đổi tên bị từ chối, xem cỡ file vẫn được: OK")

        from replay.library import Library
        from replay.picker import MatchTable
        info = Library(OUT).info(path)
        assert info.get("recording"), info
        vals, tag = MatchTable._row(info)
        assert vals[3] == "● Đang ghi" and tag == "muted", vals
        print("bảng trận: hàng '● Đang ghi', xem được khi hết trận: OK")

        from replay import viewer as V
        shown = []
        V.message_box = lambda text, title=None: shown.append(text)
        assert V.main(path) == 2 and shown and "đang được ghi" in shown[-1], shown
        print("trình xem (bấm đúp file, AoE-Replay.exe, --replay): báo đang được ghi, không mở: OK")

        from mapcap import gui as G
        infos = []
        G.messagebox.showinfo = lambda title, msg: infos.append(msg)

        class Eng:
            current_rec_path = path

        class Fake:
            engine = Eng()
            _is_recording_path = G.App._is_recording_path
            _being_recorded = G.App._being_recorded

            def _game_dir_for(self, p):
                raise AssertionError("trận đang ghi không được tới bước mở trình xem")

            class table:
                @staticmethod
                def selected_path():
                    return path
        G.App._launch_replay(Fake(), path)
        G.App._export_selected(Fake())
        assert len(infos) == 2 and all("đang được ghi" in m for m in infos), infos
        print("giao diện: Xem replay / Mở file khác / Xuất video với trận đang ghi: báo, không mở: OK")
    finally:
        f.close()
    assert open(path, "rb").read() == data
    from mapcap.rawrec import read_header
    assert read_header(path) is not None
    print("ghi xong (đóng file): đọc, mở bình thường: OK")
    print("OK test_rec_exclusive")


if __name__ == "__main__":
    main()
