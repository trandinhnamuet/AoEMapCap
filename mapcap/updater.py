"""Tự cập nhật AoE-MapCap.exe / AoE-Replay.exe từ GitHub Releases.

Luồng:
  1. check(): đọc version.json của bản phát hành mới nhất
     (https://github.com/<repo>/releases/latest/download/version.json, do GitHub Actions tạo khi đăng bản).
     Không có mạng / không vào được GitHub -> None: dùng bình thường, không báo gì.
     So APP_VERSION với "version" (có bản mới) và "min_version" (bản này đã ngừng hỗ trợ, bắt buộc cập nhật).
  2. download_all(): exe của mình và exe "anh em" cùng thư mục (AoE-MapCap.exe <-> AoE-Replay.exe, để hai bản
     luôn cùng phiên bản) -> <exe>.new. Từ v5 Release chỉ đính kèm zip: tải zip (kiểm cỡ + SHA-256), giải nén exe cần
     thay (kiểm SHA-256 từng exe theo version.json "zip.files"). version.json v3/v4 có "assets" = exe lẻ.
  3. install(): Windows không cho ghi đè / xoá exe đang chạy nhưng cho đổi tên: <exe> -> <exe>.old, <exe>.new -> <exe>.
     Lỗi giữa chừng thì đổi tên ngược lại mọi file đã đổi (không bao giờ mất exe).
  4. restart(): chạy lại exe (đã là bản mới), thoát bản cũ. Lần mở sau cleanup_old() xoá các <exe>.old.
Chạy từ mã nguồn (không đóng gói) chỉ kiểm tra và báo, không tự thay file.
Biến môi trường (chỉ để kiểm thử): AOEMAPCAP_UPDATE_URL thay địa chỉ version.json, AOEMAPCAP_UPDATE_AUTO=1 tự bấm Cập nhật.
Bản phát hành BỎ QUA các biến này (mã độc quyền thường có thể đặt biến môi trường cho tiến trình Admin), trừ khi cạnh
exe có file aoemapcap-test.flag (chỉ dùng khi kiểm thử). Link tải phải thuộc https://github.com/<repo>/releases/.
"""
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

from .version import APP_VERSION

REPO = "trandinhnamuet/AoEMapCap"
MANIFEST_URL = f"https://github.com/{REPO}/releases/latest/download/version.json"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
EXE_NAMES = {"mapcap": "AoE-MapCap.exe", "replay": "AoE-Replay.exe"}
CHECK_EVERY = 6 * 3600          # giây: kiểm tra lại khi app mở lâu (bộ ghi thường chạy cả buổi)
TIMEOUT = 10


class UpdateError(Exception):
    pass


def vtuple(v):
    """"3" / "v3" / "3.1" -> (3,) / (3,) / (3, 1); không đọc được -> (0,)."""
    nums = re.findall(r"\d+", str(v or ""))
    return tuple(int(n) for n in nums) or (0,)


TEST_FLAG = "aoemapcap-test.flag"
TRUSTED_PREFIX = f"https://github.com/{REPO}/releases/"


def test_overrides_allowed():
    """Biến môi trường kiểm thử chỉ có hiệu lực khi chạy từ mã nguồn hoặc cạnh exe có file cờ kiểm thử."""
    if not getattr(sys, "frozen", False):
        return True
    return os.path.exists(os.path.join(os.path.dirname(os.path.abspath(sys.executable)), TEST_FLAG))


def env_override(name):
    return os.environ.get(name) if test_overrides_allowed() else None


def safe_page(url):
    """Chỉ mở trang https://github.com/... (webbrowser.open trên Windows = startfile: đường dẫn exe sẽ bị chạy)."""
    return url if isinstance(url, str) and url.startswith("https://github.com/") else RELEASES_PAGE


def _check_url(url):
    if not test_overrides_allowed() and not str(url).startswith(TRUSTED_PREFIX):
        raise UpdateError("link tải không thuộc trang phát hành của AoE-MapCap: bỏ qua")


def manifest_url():
    return env_override("AOEMAPCAP_UPDATE_URL") or MANIFEST_URL


def _open(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": f"AoE-MapCap/{APP_VERSION}"})
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_manifest(url=None, timeout=TIMEOUT):
    with _open(url or manifest_url(), timeout) as r:
        m = json.loads(r.read(1 << 20).decode("utf-8"))
    if not isinstance(m, dict) or "version" not in m or not isinstance(m.get("assets"), dict):
        raise UpdateError("version.json không đúng dạng")
    return m


class UpdateInfo:
    """Kết quả kiểm tra: state = "current" | "available" | "required"."""

    def __init__(self, manifest, current=APP_VERSION):
        self.manifest = manifest
        self.current = str(current)
        self.latest = str(manifest.get("version"))
        self.min_version = str(manifest.get("min_version") or "0")
        if vtuple(self.current) < vtuple(self.min_version):
            self.state = "required"
        elif vtuple(self.current) < vtuple(self.latest):
            self.state = "available"
        else:
            self.state = "current"
        self.page = safe_page(manifest.get("page"))

    def notes_since(self):
        """Ghi chú của mọi bản mới hơn bản đang dùng (mới nhất trước)."""
        notes = self.manifest.get("notes") or {}
        lo, hi = vtuple(self.current), vtuple(self.latest)
        vs = sorted((v for v in notes if lo < vtuple(v) <= hi), key=vtuple, reverse=True)
        return "\n\n".join(f"v{v}\n{plain(notes[v])}" for v in vs) or "(không có ghi chú)"


def plain(md):
    """Ghi chú markdown -> chữ thường để hiện trong app (bỏ **đậm**, `mã`, gạch đầu dòng thành •)."""
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", md.strip())
    s = s.replace("`", "")
    return re.sub(r"(?m)^- ", "• ", s)


def check(current=APP_VERSION, url=None, log=None):
    """UpdateInfo, hoặc None khi không kiểm tra được (không mạng, GitHub lỗi...): khi đó dùng bình thường."""
    try:
        return UpdateInfo(fetch_manifest(url), current)
    except Exception as e:  # noqa: BLE001
        if log:
            log(f"không kiểm tra được bản mới ({e}); dùng bình thường")
        return None


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def targets(role, exe_path=None):
    """[(tên asset, đường dẫn exe trên máy)]: exe đang chạy + exe anh em cùng thư mục nếu có."""
    exe_path = os.path.abspath(exe_path or sys.executable)
    out = [(EXE_NAMES[role], exe_path)]
    d = os.path.dirname(exe_path)
    for r, name in EXE_NAMES.items():
        p = os.path.join(d, name)
        if r != role and os.path.isfile(p) and os.path.normcase(p) != os.path.normcase(exe_path):
            out.append((name, p))
    return out


def _check_writable(d):
    probe = os.path.join(d, f".aoemapcap_write_test_{os.getpid()}")
    try:
        with open(probe, "wb") as f:
            f.write(b"x")
        os.remove(probe)
    except OSError as e:
        raise UpdateError(f"không ghi được vào thư mục {d} ({e.strerror or e}). Hãy tải bản mới tại {RELEASES_PAGE}")


def download(url, dst, size, sha256, progress=None, cancel=None, chunk=1 << 18):
    """Tải về dst (qua dst.part), kiểm cỡ + SHA-256. progress(đã tải, tổng). cancel() True -> dừng."""
    _check_url(url)
    part = dst + ".part"
    h = hashlib.sha256()
    done = 0
    try:
        with _open(url, timeout=30) as r, open(part, "wb") as f:
            total = int(size or r.headers.get("Content-Length") or 0)
            while True:
                if cancel and cancel():
                    raise UpdateError("đã huỷ")
                b = r.read(chunk)
                if not b:
                    break
                f.write(b)
                h.update(b)
                done += len(b)
                if progress:
                    progress(done, total)
        if size and done != int(size):
            raise UpdateError(f"tải thiếu ({done} / {size} byte)")
        if sha256 and h.hexdigest().lower() != str(sha256).lower():
            raise UpdateError("file tải về không khớp mã SHA-256 (hỏng hoặc bị thay đổi)")
        os.replace(part, dst)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    return dst


ZIP_TEMP = ".aoemapcap_update.zip"


def download_all(info, role, exe_path=None, progress=None, cancel=None):
    """Tải mọi exe cần thay về <exe>.new. Trả [(exe, exe.new)]. progress(đã tải, tổng, tên).
    Từ v5: Release chỉ có zip -> tải zip (kiểm SHA-256), giải nén đúng exe cần thay (kiểm SHA-256 từng exe).
    version.json cũ (v3, v4) có "assets" = exe lẻ: tải thẳng từng exe."""
    if info.manifest.get("zip"):
        return _download_from_zip(info.manifest["zip"], role, exe_path, progress, cancel)
    assets = info.manifest["assets"]
    todo = [(name, p) for name, p in targets(role, exe_path) if name in assets]
    if not todo:
        raise UpdateError("bản phát hành không có file exe để cập nhật")
    d = os.path.dirname(todo[0][1])
    _check_writable(d)
    need = sum(int(assets[n].get("size") or 0) for n, _p in todo)
    if shutil.disk_usage(d).free < need * 1.2 + (50 << 20):
        raise UpdateError(f"ổ đĩa không đủ chỗ trống (cần ~{need / 1e6:.0f} MB)")
    total = need or 1
    base = 0
    out = []
    try:
        for name, p in todo:
            a = assets[name]
            dst = p + ".new"
            download(a["url"], dst, a.get("size"), a.get("sha256"),
                     progress=(lambda k, _t, b=base, n=name: progress(b + k, total, n)) if progress else None,
                     cancel=cancel)
            out.append((p, dst, a.get("sha256")))
            base += int(a.get("size") or 0)
    except BaseException:
        for x in out:
            try:
                os.remove(x[1])
            except OSError:
                pass
        raise
    return out


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def install(pairs):
    """Thay exe bằng bản .new (đổi tên được cả exe đang chạy). Lỗi thì hoàn tác mọi file đã đổi."""
    undo = []
    try:
        for item in pairs:
            exe, new = item[0], item[1]
            want = item[2] if len(item) > 2 else None
            if want and _sha256_file(new).lower() != str(want).lower():   # kiểm lại ngay trước khi thay (chống tráo .new)
                raise UpdateError(f"{os.path.basename(new)} đã bị thay đổi sau khi tải: không cài")
            old = exe + ".old"
            if os.path.exists(old):
                try:
                    os.remove(old)
                except OSError:                 # .old của lần trước còn đang chạy: dùng tên khác
                    old = f"{exe}.old{int(time.time() * 1000)}"
            os.replace(exe, old)
            undo.append((exe, old, None))
            os.replace(new, exe)
            undo[-1] = (exe, old, True)
    except BaseException:
        for exe, old, placed in reversed(undo):
            try:
                if placed:
                    os.replace(exe, exe + ".new")
                os.replace(old, exe)
            except OSError:
                pass
        raise


def _download_from_zip(z, role, exe_path, progress, cancel):
    files = z.get("files") or {}
    todo = [(name, p) for name, p in targets(role, exe_path) if name in files]
    if not todo:
        raise UpdateError("bản phát hành không có file exe để cập nhật")
    d = os.path.dirname(todo[0][1])
    _check_writable(d)
    need = int(z.get("size") or 0) + sum(int(files[n].get("size") or 0) for n, _p in todo)
    if shutil.disk_usage(d).free < need * 1.2 + (50 << 20):
        raise UpdateError(f"ổ đĩa không đủ chỗ trống (cần ~{need / 1e6:.0f} MB)")
    zpath = os.path.join(d, ZIP_TEMP)
    out = []
    try:
        download(z["url"], zpath, z.get("size"), z.get("sha256"),
                 progress=(lambda k, t: progress(k, t or int(z.get("size") or 1), "AoE-MapCap-win64.zip"))
                 if progress else None, cancel=cancel)
        with zipfile.ZipFile(zpath) as zf:
            by_base = {os.path.basename(i.filename).lower(): i for i in zf.infolist() if not i.is_dir()}
            for name, p in todo:
                meta = files[name]
                info = zf.getinfo(meta["path"]) if meta.get("path") in zf.namelist() else by_base.get(name.lower())
                if info is None:
                    raise UpdateError(f"zip không có {name}")
                dst = p + ".new"
                h = hashlib.sha256()
                with zf.open(info) as src, open(dst, "wb") as f:
                    out.append((p, dst, meta.get("sha256")))
                    for b in iter(lambda: src.read(1 << 20), b""):
                        if cancel and cancel():
                            raise UpdateError("đã huỷ")
                        f.write(b)
                        h.update(b)
                if meta.get("sha256") and h.hexdigest().lower() != str(meta["sha256"]).lower():
                    raise UpdateError(f"{name} trong zip không khớp mã SHA-256")
    except BaseException:
        for x in out:
            try:
                os.remove(x[1])
            except OSError:
                pass
        raise
    finally:
        try:
            os.remove(zpath)
        except OSError:
            pass
    return out


def cleanup_old(exe_path=None):
    """Xoá <exe>.old* / .new / .part còn sót của lần cập nhật trước (exe cũ đã thoát)."""
    if not is_frozen() and exe_path is None:
        return 0
    d = os.path.dirname(os.path.abspath(exe_path or sys.executable))
    n = 0
    leftovers = glob.glob(os.path.join(d, ZIP_TEMP)) + glob.glob(os.path.join(d, ZIP_TEMP + ".part"))
    for name in EXE_NAMES.values():
        leftovers += glob.glob(os.path.join(d, name + ".old*")) + glob.glob(os.path.join(d, name + ".new.part"))
    for p in leftovers:
        try:
            os.remove(p)
            n += 1
        except OSError:
            pass                                 # còn đang chạy (vd AoE-Replay cũ chưa đóng): lần sau xoá
    return n


def restart(args=(), exe_path=None):
    """Chạy lại exe (bản mới) với tham số args. PYINSTALLER_RESET_ENVIRONMENT: bản mới tự giải nén riêng, không
    dùng lại thư mục tạm của bản cũ (thư mục đó bị xoá khi bản cũ thoát)."""
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    for k in list(env):
        if k.startswith("_PYI_") or k == "_MEIPASS2":
            env.pop(k, None)
    exe = os.path.abspath(exe_path or sys.executable)
    return subprocess.Popen([exe] + list(args), env=env, close_fds=True, cwd=os.path.dirname(exe))
