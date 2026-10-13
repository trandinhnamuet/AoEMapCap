"""Kiểm thử bộ tự cập nhật (mapcap/updater.py, mapcap/update_ui.py), release/make_release.py và báo file định dạng mới hơn.

    python tests/test_updater.py

Máy chủ HTTP cục bộ (127.0.0.1) đóng vai GitHub; exe "đang chạy" là bản sao PING.EXE trong Video\\_test\\updater
(tự tắt theo PID, không đụng tiến trình nào khác). Không cần mạng.
"""
import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

from mapcap import updater  # noqa: E402

WORK = os.path.join(ROOT, "Video", "_test", "updater")


class Server:
    """Phục vụ {đường dẫn: bytes}; đếm lượt tải."""

    def __init__(self, files):
        self.files = files
        self.hits = {}
        srv = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                srv.hits[self.path] = srv.hits.get(self.path, 0) + 1
                data = srv.files.get(self.path)
                if data is None:
                    self.send_error(404)
                    return
                if callable(data):
                    data = data()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


def manifest(url, version, assets, min_version="1", notes=None):
    return {"version": version, "tag": f"v{version}", "min_version": min_version, "page": url + "/page",
            "notes": notes or {"2": "- **Bản 2**", "3": "- bản `3`", "4": "- **Bản 4**: mới"},
            "assets": {n: {"url": url + "/" + n, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()}
                       for n, b in assets.items()}}


def fresh_dir(name):
    d = os.path.join(WORK, name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    return d


def test_versions():
    assert updater.vtuple("v3") == (3,) and updater.vtuple("3.1") == (3, 1) and updater.vtuple(None) == (0,)
    m = {"version": "4", "min_version": "1", "assets": {}, "notes": {"3": "- a", "4": "- **b**", "5": "c"}}
    i = updater.UpdateInfo(m, "3")
    assert i.state == "available" and i.notes_since() == "v4\n• b", i.notes_since()
    assert updater.UpdateInfo(m, "4").state == "current"
    assert updater.UpdateInfo(m, "10").state == "current"                  # so theo số, không theo chữ
    assert updater.UpdateInfo(dict(m, min_version="4"), "3").state == "required"
    print("so phiên bản / ghi chú: OK")


def test_offline():
    t0 = time.time()
    msgs = []
    assert updater.check(url="http://127.0.0.1:9/version.json", log=msgs.append) is None
    assert msgs and "dùng bình thường" in msgs[0] and time.time() - t0 < 12
    srv = Server({"/version.json": b"<html>not json"})
    assert updater.check(url=srv.url + "/version.json") is None             # trả về lỗi dạng: cũng coi như không có
    srv.close()
    print("không mạng / version.json hỏng -> dùng bình thường: OK")


def test_update_running_exe():
    d = fresh_dir("swap")
    me = os.path.join(d, "AoE-MapCap.exe")
    sib = os.path.join(d, "AoE-Replay.exe")
    shutil.copy(r"C:\Windows\System32\PING.EXE", me)
    with open(sib, "wb") as f:
        f.write(b"replay cu")
    proc = subprocess.Popen([me, "-n", "30", "127.0.0.1"], stdout=subprocess.DEVNULL, creationflags=0x08000000)
    try:
        time.sleep(0.5)
        new_me, new_sib = os.urandom(3_000_000), b"replay moi" * 1000
        srv = Server({})
        m = manifest(srv.url, "4", {"AoE-MapCap.exe": new_me, "AoE-Replay.exe": new_sib})
        srv.files.update({"/version.json": json.dumps(m).encode(), "/AoE-MapCap.exe": new_me,
                          "/AoE-Replay.exe": new_sib})
        info = updater.check("3", url=srv.url + "/version.json")
        assert info is not None and info.state == "available"
        assert [n for n, _p in updater.targets("mapcap", me)] == ["AoE-MapCap.exe", "AoE-Replay.exe"]
        seen = []
        pairs = updater.download_all(info, "mapcap", me, progress=lambda a, b, n: seen.append((a, b, n)))
        assert seen[-1][0] == seen[-1][1] == len(new_me) + len(new_sib)
        updater.install(pairs)
        assert open(me, "rb").read() == new_me and open(sib, "rb").read() == new_sib
        assert proc.poll() is None                                     # exe cũ vẫn chạy tiếp sau khi bị đổi tên
        assert os.path.exists(me + ".old")
        assert updater.cleanup_old(me) >= 1 and os.path.exists(me + ".old")   # còn chạy: chưa xoá được
        srv.close()
    finally:
        proc.kill()
        proc.wait()
    time.sleep(0.3)
    updater.cleanup_old(me)
    assert not os.path.exists(me + ".old") and not os.path.exists(sib + ".old")
    print("tải + kiểm SHA-256 + thay exe đang chạy + exe anh em + dọn .old: OK")


def test_bad_hash_cancel_rollback():
    d = fresh_dir("bad")
    me = os.path.join(d, "AoE-Replay.exe")
    with open(me, "wb") as f:
        f.write(b"ban cu")
    good = b"x" * 2_000_000
    srv = Server({"/AoE-Replay.exe": b"y" * 2_000_000})                  # nội dung khác mã SHA-256 trong manifest
    m = manifest(srv.url, "4", {"AoE-Replay.exe": good})
    info = updater.UpdateInfo(m, "3")
    try:
        updater.download_all(info, "replay", me)
        raise AssertionError("phải báo lỗi SHA-256")
    except updater.UpdateError as e:
        assert "SHA-256" in str(e), e
    assert sorted(os.listdir(d)) == ["AoE-Replay.exe"] and open(me, "rb").read() == b"ban cu"
    srv.files["/AoE-Replay.exe"] = good
    try:
        updater.download_all(info, "replay", me, cancel=lambda: True)
        raise AssertionError("phải dừng khi huỷ")
    except updater.UpdateError as e:
        assert str(e) == "đã huỷ"
    assert sorted(os.listdir(d)) == ["AoE-Replay.exe"]
    srv.close()
    # hoàn tác: file thứ hai lỗi khi thay -> file thứ nhất trả về như cũ
    a, b = os.path.join(d, "AoE-Replay.exe"), os.path.join(d, "AoE-MapCap.exe")
    with open(b, "wb") as f:
        f.write(b"mapcap cu")
    with open(a + ".new", "wb") as f:
        f.write(b"replay moi")
    try:
        updater.install([(a, a + ".new"), (b, b + ".new")])               # b.new không có
        raise AssertionError("phải lỗi")
    except OSError:
        pass
    assert open(a, "rb").read() == b"ban cu" and open(b, "rb").read() == b"mapcap cu"
    assert not os.path.exists(a + ".old") and not os.path.exists(b + ".old")
    print("sai SHA-256 / huỷ / lỗi giữa chừng -> giữ nguyên exe cũ: OK")


def test_make_release():
    sys.path.insert(0, os.path.join(ROOT, "release"))
    import make_release
    d = fresh_dir("rel")
    for n in make_release.EXES:
        with open(os.path.join(d, n), "wb") as f:
            f.write(n.encode() * 100)
    out = os.path.join(d, "version.json")
    make_release.manifest("v3", d, out)
    m = json.load(open(out, encoding="utf-8"))
    assert m["version"] == "3" and m["tag"] == "v3" and set(m["notes"]) >= {"1", "2", "3"}
    assert m["assets"]["AoE-Replay.exe"]["url"].endswith("/releases/download/v3/AoE-Replay.exe")
    assert m["assets"]["AoE-MapCap.exe"]["size"] == len(b"AoE-MapCap.exe" * 100)
    i = updater.UpdateInfo(m, "1")
    assert i.state == "available" and i.notes_since().startswith("v3\n• Tự cập nhật") and "\n\nv2\n" in i.notes_since()
    make_release.bodies("v3", os.path.join(d, "bodies"), zip_sha="abc", commit="c0ffee")
    b3 = open(os.path.join(d, "bodies", "v3.md"), encoding="utf-8").read()
    b1 = open(os.path.join(d, "bodies", "v1.md"), encoding="utf-8").read()
    assert "## Có gì mới trong v3" in b3 and "`abc`" in b3 and "c0ffee" in b3 and "Đây là bản cũ" not in b3
    assert "Đây là bản cũ" in b1 and "abc" not in b1 and "tự báo có bản mới" not in b1
    with open(os.path.join(ROOT, "mapcap", "version.py"), encoding="utf-8") as f:
        assert 'APP_VERSION = "3"' in f.read()
    print("make_release: version.json + mô tả các bản: OK")


def test_newer_format_file():
    import glob
    from mapcap.rawrec import MAGIC, _pack, read_header
    from replay.data import ReplayData
    from replay.library import match_info
    src = min(glob.glob(os.path.join(ROOT, "dist", "Video", "Raw", "*.aoerec")) +
              glob.glob(os.path.join(ROOT, "Video", "_test", "format3", "*.aoerec")), key=os.path.getsize)
    hdr = read_header(src)
    hdr["container"] = 99
    with open(src, "rb") as f:
        f.seek(len(MAGIC))
        n = int.from_bytes(f.read(5)[1:], "little")
        f.seek(n, 1)
        rest = f.read(1 << 20)
    dst = os.path.join(fresh_dir("newer"), "moi.aoerec")
    with open(dst, "wb") as f:
        f.write(MAGIC + _pack(b"H", hdr) + rest)
    try:
        ReplayData(dst)
        raise AssertionError("phải báo cần bản mới")
    except ValueError as e:
        assert "mới hơn" in str(e) and "định dạng 99" in str(e), e
    assert match_info(dst)["result"] == "Cần bản mới"
    print("file của bản mới hơn: trình xem + bảng trận báo cần cập nhật: OK")


def test_ui():
    import tkinter as tk
    from tkinter import ttk
    from mapcap import update_ui
    root = tk.Tk()
    root.withdraw()
    body = ttk.Frame(root)
    body.pack(fill="both", expand=True)
    busy = {"v": "Đang ghi trận"}
    srv = Server({})
    m = manifest(srv.url, "4", {"AoE-MapCap.exe": b"z"})
    srv.files["/version.json"] = lambda: json.dumps(m).encode()
    os.environ["AOEMAPCAP_UPDATE_URL"] = srv.url + "/version.json"
    try:
        ctl = update_ui.UpdateController(root, root, "mapcap", "Test", is_busy=lambda: busy["v"], bar_before=body)
        ctl.start(delay_ms=10)
        t0 = time.time()
        while ctl.info is None and time.time() - t0 < 10:
            root.update()
            time.sleep(0.02)
        assert ctl.info is not None and ctl.info.state == "available"
        assert ctl.bar.winfo_manager() == "pack" and "v4" in ctl.lbl.cget("text")
        frozen = updater.is_frozen
        updater.is_frozen = lambda: True
        started = []
        ctl._download = lambda: started.append(1)
        ctl.begin_update()                                            # đang ghi: chỉ hẹn, chưa tải
        assert ctl.pending and not started and "sẽ tự cập nhật" in ctl.lbl.cget("text")
        busy["v"] = ""
        t0 = time.time()
        while not started and time.time() - t0 < 5:
            root.update()
            time.sleep(0.05)
        assert started, "hết bận phải tự bắt đầu tải"
        updater.is_frozen = frozen
        ctl._later()
        assert ctl.bar.winfo_manager() == ""
        # bắt buộc cập nhật: chỉ hiện khi không bận
        m["min_version"] = "4"
        busy["v"] = "Đang ghi trận"
        ctl._on_checked(updater.check("3"))
        for _ in range(10):
            root.update()
            time.sleep(0.05)
        assert ctl.info.state == "required" and ctl.block_win is None
        busy["v"] = ""
        t0 = time.time()
        while ctl.block_win is None and time.time() - t0 < 5:
            root.update()
            time.sleep(0.05)
        assert ctl.block_win is not None and "ngừng hỗ trợ" in ctl.block_win.top.title() + str(
            [w.cget("text") for w in ctl.block_win.top.winfo_children() if isinstance(w, ttk.Label)])
    finally:
        os.environ.pop("AOEMAPCAP_UPDATE_URL", None)
        srv.close()
        root.destroy()
    print("giao diện: thanh báo, chờ hết bận, Để sau, cửa sổ bắt buộc: OK")


def test_compile_all():
    """Mọi file mã biên dịch được (PyInstaller lặng lẽ bỏ module lỗi cú pháp -> exe báo thiếu module khi chạy)."""
    bad = []
    for d in ("mapcap", "replay", "release", "."):
        for name in os.listdir(os.path.join(ROOT, d)):
            if name.endswith(".py"):
                p = os.path.join(ROOT, d, name)
                try:
                    compile(open(p, encoding="utf-8").read(), p, "exec")
                except SyntaxError as e:
                    bad.append(f"{p}:{e.lineno}: {e.msg}")
    assert not bad, "\n".join(bad)
    print("biên dịch toàn bộ mã: OK")


if __name__ == "__main__":
    test_compile_all()
    test_versions()
    test_offline()
    test_update_running_exe()
    test_bad_hash_cancel_rollback()
    test_make_release()
    test_newer_format_file()
    test_ui()
    print("OK")
