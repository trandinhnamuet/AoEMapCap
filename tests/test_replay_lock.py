"""Chống gian lận bằng replay (replay/lock.py, v33): trận dừng ghi khi ván chưa phân thắng bại bị khoá 60 phút tính từ
mẫu cuối: không mở trình xem, không xuất video, không gửi sang điện thoại; trận ghi tới hết ván mở ngay.

    python tests/test_replay_lock.py [trận_2v2_ghi_tới_hết_ván.aoerec]

Dùng một trận 2v2 thật đã ghi tới hết ván, tạo các bản biến thể chỉ bằng cách viết lại bản ghi tổng kết 'E' cuối file
(hết ván / ai còn đang chơi / giờ mẫu cuối) hoặc cắt bỏ 'E' (ghi dở). Mọi file ở Video\\_test\\replay_lock; không mở
cửa sổ trình xem, không hiện hộp thoại (hàm báo thay bằng hàm ghi lại).
"""
import glob
import os
import shutil
import struct
import sys
import time
import urllib.request
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
os.environ["AOEMAPCAP_TELEMETRY"] = "0"

from mapcap.rawrec import END_MAGIC, _pack, read_end, read_header  # noqa: E402
from replay import lock as L  # noqa: E402
from replay.library import Library, teams_from_header  # noqa: E402

OUT = os.path.join(ROOT, "Video", "_test", "replay_lock")
BASE_NAME = "2026-10-23_004934_tran1.aoerec"


def find_base():
    if len(sys.argv) > 1:
        return sys.argv[1]
    for d in (os.path.join(ROOT, "Video", "Raw"),
              r"C:\Users\Admin\Downloads\AoE-MapCap-win64\AoE-MapCap-win64\Video\Raw"):
        p = os.path.join(d, BASE_NAME)
        if os.path.isfile(p):
            return p
    raise SystemExit(f"không thấy {BASE_NAME}; truyền đường dẫn một trận 2v2 ghi tới hết ván")


def body_and_end(src):
    data = open(src, "rb").read()
    assert data[-16:-8] == END_MAGIC
    pos = struct.unpack("<Q", data[-8:])[0]
    return data[:pos], read_end(src)


def variant(src, name, mutate):
    """Bản sao với 'E' viết lại bằng mutate(end) (None = bỏ 'E': file ghi dở)."""
    body, end = body_and_end(src)
    dst = os.path.join(OUT, name)
    if mutate is None:
        open(dst, "wb").write(body)
    else:
        b = _pack(b"E", mutate(dict(end)))
        open(dst, "wb").write(body + b + END_MAGIC + struct.pack("<Q", len(body)))
    return dst


def main():
    base = find_base()
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    hdr = read_header(base)
    end = read_end(base)
    teams = teams_from_header(hdr)
    assert len(teams) == 2 and all(len(t) == 2 for t in teams) and end.get("game_over"), (teams, end.get("game_over"))
    rec = int(hdr["cur_player_index"])
    mine = next(t for t in teams if rec in t)
    other = next(t for t in teams if rec not in t)
    now = time.time()
    playing = {i: (0, 0) for t in teams for i in t}

    def stopped(e):                     # dừng ghi giữa ván: chưa hết ván, ai cũng đang chơi, mẫu cuối = bây giờ
        e.update(game_over=0, status=dict(playing), at=now - 30, closed=now - 30)
        return e

    def me_out(e):                      # mình bị loại / bỏ cuộc, đồng đội còn đánh
        st = dict(playing)
        st[rec] = (2, 1)
        e.update(game_over=0, status=st, at=now - 30, closed=now - 30)
        return e

    def team_out(e):                    # một đội bị loại hết (chưa kịp cờ hết ván): đã phân thắng bại
        st = dict(playing)
        for i in other:
            st[i] = (2, 0)
        e.update(game_over=0, status=st, at=now - 30, closed=now - 30)
        return e

    def finished_now(e):                # ghi tới hết ván, vừa xong
        e.update(game_over=1, at=now - 30, closed=now - 30)
        return e

    f_done = variant(base, "het_van.aoerec", finished_now)
    f_stop = variant(base, "dung_giua_van.aoerec", stopped)
    f_me = variant(base, "minh_bi_loai.aoerec", me_out)
    f_team = variant(base, "mot_doi_bi_loai.aoerec", team_out)
    f_partial = variant(base, "ghi_do.aoerec", None)

    # ---- luật ------------------------------------------------------------------------------------------------------
    assert L.check(f_done) is None and L.lock_until(f_done) == 0
    assert L.check(f_team) is None, "một đội bị loại hết = đã phân thắng bại"
    for f in (f_stop, f_me):
        u = L.lock_until(f)
        assert abs(u - (now - 30 + L.LOCK_SECONDS)) < 1, (f, u - now)
        msg = L.check(f)
        assert msg and "khoá tới" in msg and "60 phút" in msg, msg
        assert L.check(f, now=u + 1) is None, "hết 60 phút thì mở được"
    print("hết ván / một đội bị loại hết: mở ngay; dừng giữa ván / mình bị loại khi đồng đội còn đánh: khoá 60 phút "
          "từ mẫu cuối, sau đó mở được: OK")
    # ghi dở (không có 'E'): giờ mẫu cuối lấy trong file (trận gốc đã cũ -> hết khoá), không lấy giờ sửa file
    os.utime(f_partial, (now, now))
    u = L.lock_until(f_partial)
    assert u and u < now and L.check(f_partial) is None, (u, now)
    assert L.check(f_partial, now=u - 5) is not None
    print("file ghi dở: tính theo giờ mẫu cuối trong file (sửa giờ file không mở khoá / không khoá nhầm): OK")
    # file trước 2026-10-09 (chưa có trạng thái thắng thua): không khoá
    old = [p for p in glob.glob(os.path.join(ROOT, "Video", "Raw", "*.aoerec")) if "format" not in (read_header(p) or {})]
    if old:
        assert L.lock_until(old[0]) == 0
        print("file định dạng cũ: không khoá: OK")

    # ---- bảng trận: hiện "Khoá tới HH:MM", không tin _matches.json khi mở ------------------------------------------
    for p in (f_done, f_stop, f_me, f_team, f_partial):     # sửa quá 60 s: bảng đệm được, điện thoại liệt kê
        t = time.time() - 120
        os.utime(p, (t, t))
    lib = Library(OUT)
    info = lib.info(f_stop)
    assert abs(info["lock_until"] - (now - 30 + L.LOCK_SECONDS)) < 1
    from replay.picker import MatchTable
    vals, tag = MatchTable._row(info)
    assert vals[3].startswith("🔒 Khoá tới ") and tag == "muted", vals
    vals, tag = MatchTable._row(lib.info(f_done))
    assert "Khoá" not in vals[3], vals
    lib.save()
    cache = os.path.join(OUT, "_matches.json")
    c = json.load(open(cache, encoding="utf-8"))
    hits = []

    def unlock(o):                                      # sửa đệm cho "hết khoá": khi mở vẫn tính lại từ file
        if isinstance(o, dict):
            if "lock_until" in o:
                o["lock_until"] = 0
                hits.append(1)
            for v in o.values():
                unlock(v)
        elif isinstance(o, list):
            for v in o:
                unlock(v)
    unlock(c)
    assert hits, "đệm phải có lock_until"
    json.dump(c, open(cache, "w", encoding="utf-8"))
    assert L.check(f_stop) is not None
    print("bảng trận hiện '🔒 Khoá tới HH:MM'; sửa _matches.json không mở được khoá: OK")

    # ---- chặn ở mọi đường: trình xem, xuất video, giao diện, điện thoại ---------------------------------------------
    from replay import viewer as V
    shown = []
    V.message_box = lambda text, title=None: shown.append(text)
    assert V.main(f_stop) == 2 and shown and "khoá tới" in shown[-1]
    print("trình xem (mọi đường mở: bấm đúp, AoE-Replay.exe, --replay): báo khoá, không mở: OK")
    from mapcap import offline
    try:
        offline.render_raw(f_stop, os.path.join(OUT, "x.mp4"))
        raise AssertionError("xuất video phải bị chặn")
    except RuntimeError as e:
        assert "khoá" in str(e), e
    assert not os.path.exists(os.path.join(OUT, "x.mp4"))
    print("xuất video (cả dòng lệnh --render-raw): bị chặn: OK")

    from mapcap import gui as G
    infos = []
    G.messagebox.showinfo = lambda title, msg: infos.append(msg)

    class Fake:
        appended = []
        _locked = G.App._locked

        def _append(self, m):
            self.appended.append(m)

        def _game_dir_for(self, p):
            raise AssertionError("trận khoá không được tới bước mở trình xem")
    fake = Fake()
    G.App._launch_replay(fake, f_stop)
    G.App.export_video(fake, f_stop)
    assert len(infos) == 2 and all("khoá tới" in m for m in infos), infos
    assert G.App._locked(fake, f_done) is False
    print("giao diện: Xem replay / Mở file khác / Xuất video báo khoá, trận xong vẫn mở: OK")

    from mapcap import mobile_server as M
    names = {m["file"] for m in M.list_matches(OUT)}
    assert "dung_giua_van.aoerec" not in names and "minh_bi_loai.aoerec" not in names, names
    assert {"het_van.aoerec", "mot_doi_bi_loai.aoerec"} <= names, names
    srv, url = M.serve(OUT, None, port=0, token="testlock", log=lambda m: None,
                       cache=os.path.join(OUT, "_phone"), host="127.0.0.1")
    import threading
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base_url = url.rstrip("/")
        j = json.load(urllib.request.urlopen(base_url + "/api/match?f=dung_giua_van.aoerec", timeout=10))
        assert j.get("ready") is False and "khoá tới" in (j.get("error") or ""), j
    finally:
        srv.shutdown()
        srv.exporter.stop()
    print("điện thoại: trận đang khoá không có trong danh sách, hỏi thẳng thì báo khoá, không gửi dữ liệu: OK")
    print("OK test_replay_lock")


if __name__ == "__main__":
    main()
