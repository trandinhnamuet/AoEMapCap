"""Kiểm thử các bản vá bảo mật (2026-10-16).

    python tests/test_security.py

1. File .aoerec chế sẵn (pickle __reduce__ -> chạy lệnh) KHÔNG chạy được mã: read_header / read_end / iter_records /
   ReplayData / match_info đều từ chối; bảng trận vẫn chạy. Bom giải nén bị chặn. Trận thật vẫn đọc bình thường.
2. Bộ cập nhật: bản phát hành (frozen) bỏ qua biến môi trường kiểm thử, chỉ tải link của repo, chỉ mở trang github.com,
   kiểm lại SHA-256 ngay trước khi thay exe (file .new bị tráo -> không cài).
"""
import glob
import os
import pickle
import shutil
import struct
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

from mapcap import safeload, updater  # noqa: E402
from mapcap.rawrec import MAGIC, iter_records, read_end, read_header  # noqa: E402

WORK = os.path.join(ROOT, "Video", "_test", "security")
PWNED = os.path.join(WORK, "pwned.txt")


def evil_payload():
    """pickle (protocol 0) gọi builtins.exec(code) -> ghi pwned.txt nếu bộ đọc không chặn (thay cho lệnh độc thật)."""
    code = f"open({PWNED.replace(os.sep, '/')!r}, 'w').write('pwned')"
    return b"cbuiltins\nexec\n(V" + code.encode("ascii") + b"\ntR."


def make_file(path, payload_raw, tag=b"H"):
    data = zlib.compress(payload_raw)
    with open(path, "wb") as f:
        f.write(MAGIC + tag + struct.pack("<I", len(data)) + data)


def test_malicious_file():
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    raw = evil_payload()
    # bảo đảm payload thật sự độc với pickle thường (kiểm trong thư mục tạm)
    pickle.loads(raw)
    assert os.path.exists(PWNED), "payload thử phải chạy được với pickle thường"
    os.remove(PWNED)
    bad = os.path.join(WORK, "doc.aoerec")
    make_file(bad, raw)
    for fn in (lambda: read_header(bad), lambda: list(iter_records(bad))):
        try:
            r = fn()
        except safeload.UnsafeFileError:
            r = None
        except Exception:  # noqa: BLE001  - lỗi khác cũng được, miễn không chạy mã
            r = None
        assert not r and not os.path.exists(PWNED), "file độc không được chạy mã"
    from replay.data import ReplayData
    try:
        ReplayData(bad)
        raise AssertionError("ReplayData phải từ chối file độc")
    except Exception:  # noqa: BLE001
        pass
    from replay.library import Library, match_info
    try:
        match_info(bad)
    except Exception:  # noqa: BLE001
        pass
    lib = Library(WORK)
    try:
        lib.info(bad)
    except Exception:  # noqa: BLE001
        pass
    assert not os.path.exists(PWNED)
    # 'E' độc ở cuối file (đuôi AOEEND01 trỏ tới)
    data = zlib.compress(raw)
    e = os.path.join(WORK, "doc_e.aoerec")
    with open(e, "wb") as f:
        f.write(MAGIC)
        pos = f.tell()
        f.write(b"E" + struct.pack("<I", len(data)) + data + b"AOEEND01" + struct.pack("<Q", pos))
    try:
        read_end(e)
    except Exception:  # noqa: BLE001
        pass
    assert not os.path.exists(PWNED)
    # bom giải nén: 1 GB số 0 nén còn ~1 MB -> bị chặn trước khi giải hết
    bomb = zlib.compress(b"\0" * (600 << 20), 9)
    try:
        safeload.zlib_loads(bomb)
        raise AssertionError("bom giải nén phải bị chặn")
    except ValueError:
        pass
    print("file .aoerec độc: không chạy được mã (header / đuôi / khối / trình xem / bảng trận), bom giải nén bị chặn: OK")


def test_real_files_still_load():
    files = sorted(glob.glob(os.path.join(ROOT, "dist", "Video", "Raw", "*.aoerec")) +
                   glob.glob(os.path.join(ROOT, "Video", "_test", "format3", "*.aoerec")), key=os.path.getsize)
    if not files:
        print("bỏ qua: không có trận thật")
        return
    for p in files[:3] + files[-1:]:
        h = read_header(p)
        assert h and "players" in h
        n = sum(1 for t, _p in iter_records(p) if t == b"F")
        assert n > 0, p
    print(f"trận thật vẫn đọc đủ ({len(files[:3] + files[-1:])} file, cả định dạng cũ và mới): OK")


def test_updater_hardening():
    frozen = getattr(sys, "frozen", None)
    exe = sys.executable
    os.environ["AOEMAPCAP_UPDATE_URL"] = "http://evil.example/version.json"
    os.environ["AOEMAPCAP_UPDATE_AUTO"] = "1"
    try:
        sys.frozen = True                          # giả lập bản phát hành, không có file cờ kiểm thử cạnh exe
        sys.executable = os.path.join(WORK, "AoE-MapCap.exe")
        assert not updater.test_overrides_allowed()
        assert updater.manifest_url() == updater.MANIFEST_URL, "bản phát hành phải bỏ qua AOEMAPCAP_UPDATE_URL"
        assert updater.env_override("AOEMAPCAP_UPDATE_AUTO") is None
        from mapcap import telemetry
        assert telemetry.endpoint() == telemetry.ENDPOINT
        for url in ("http://evil.example/x.zip", "https://github.com/someone/else/releases/download/v9/x.zip",
                    "file:///C:/Windows/notepad.exe"):
            try:
                updater._check_url(url)
                raise AssertionError("link lạ phải bị từ chối: " + url)
            except updater.UpdateError:
                pass
        updater._check_url("https://github.com/trandinhnamuet/AoEMapCap/releases/download/v8/AoE-MapCap-win64.zip")
        open(os.path.join(WORK, updater.TEST_FLAG), "w").close()                 # có file cờ -> cho phép (kiểm thử)
        assert updater.test_overrides_allowed() and updater.manifest_url() == "http://evil.example/version.json"
        os.remove(os.path.join(WORK, updater.TEST_FLAG))
    finally:
        if frozen is None:
            del sys.frozen
        else:
            sys.frozen = frozen
        sys.executable = exe
        os.environ.pop("AOEMAPCAP_UPDATE_URL", None)
        os.environ.pop("AOEMAPCAP_UPDATE_AUTO", None)
    assert updater.safe_page("C:\\Windows\\System32\\calc.exe") == updater.RELEASES_PAGE
    assert updater.safe_page("https://github.com/trandinhnamuet/AoEMapCap/releases/tag/v8").startswith("https://github.com/")
    i = updater.UpdateInfo({"version": "99", "assets": {}, "page": "\\\\server\\share\\evil.exe"}, "1")
    assert i.page == updater.RELEASES_PAGE
    # .new bị tráo sau khi kiểm SHA lúc tải -> install từ chối, exe cũ giữ nguyên
    import hashlib
    exe_p = os.path.join(WORK, "AoE-MapCap.exe")
    with open(exe_p, "wb") as f:
        f.write(b"ban cu")
    good = b"ban moi"
    with open(exe_p + ".new", "wb") as f:
        f.write(b"MA DOC DA TRAO")
    try:
        updater.install([(exe_p, exe_p + ".new", hashlib.sha256(good).hexdigest())])
        raise AssertionError("file .new bị tráo phải bị từ chối")
    except updater.UpdateError:
        pass
    assert open(exe_p, "rb").read() == b"ban cu" and not os.path.exists(exe_p + ".old")
    with open(exe_p + ".new", "wb") as f:
        f.write(good)
    updater.install([(exe_p, exe_p + ".new", hashlib.sha256(good).hexdigest())])
    assert open(exe_p, "rb").read() == good
    print("bộ cập nhật: bỏ qua biến môi trường kiểm thử, chỉ link repo, chỉ trang github.com, chống tráo .new: OK")


if __name__ == "__main__":
    test_malicious_file()
    test_real_files_still_load()
    test_updater_hardening()
    print("OK")
