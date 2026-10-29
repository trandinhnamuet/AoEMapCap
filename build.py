"""Build dist\AoE-MapCap.exe. KHÔNG ghi đè khi exe đang chạy (tiến trình con sẽ đọc archive sai -> zlib error):
khi đó xuất ra dist\AoE-MapCap.exe.new và báo để đổi tên sau."""
import os, shutil, subprocess, sys
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
for _s in (sys.stdout, sys.stderr):                 # in tiếng Việt cả khi chuyển hướng ra file (cp1252)
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
# Khởi động nhanh (2026-10-16): exe một file giải nén MỌI THỨ ra thư mục tạm mỗi lần mở (trước đây ~181 MB / 1 060 file,
# ~2,5 s). Giảm: ffmpeg (87,6 MB, chỉ dùng khi xuất video) gói dạng .xz -> recorder.bundled_ffmpeg giải nén khi cần;
# bỏ PIL._avif (7,9 MB, không dùng); bỏ dữ liệu múi giờ / thông điệp của Tcl/Tk (~650 file nhỏ, tkinter không dùng);
# màn hình chờ (splash) hiện ngay khi mở, đóng khi cửa sổ chính sẵn sàng.
import hashlib
import lzma
os.makedirs("build_assets", exist_ok=True)
_ff = os.path.join("vendor", "ffmpeg.exe")
_xz = os.path.join("build_assets", "ffmpeg.exe.xz")
_sha = hashlib.sha256(open(_ff, "rb").read()).hexdigest()
if not (os.path.exists(_xz) and open(_xz + ".src", encoding="ascii").read() == _sha if os.path.exists(_xz + ".src") else False):
    with open(_ff, "rb") as f, lzma.open(_xz, "wb", preset=6) as g:
        shutil.copyfileobj(f, g, 1 << 20)
    open(_xz + ".src", "w", encoding="ascii").write(_sha)
open(os.path.join("build_assets", "ffmpeg.exe.sha256"), "w", encoding="ascii").write(_sha + "  ffmpeg.exe\n")
from make_splash import make_splash  # noqa: E402
make_splash(os.path.join("build_assets", "splash.png"))
SPEC = f"""# sinh bởi build.py — không sửa tay
DROP = ('_tcl_data/tzdata', '_tcl_data/msgs', '_tk_data/msgs', '_tk_data/images', '_tcl_data/http1.0', '_tcl_data/opt0.4')
a = Analysis(['run_app.py'], pathex=[], binaries=[],
             datas=[('assets/app.ico', 'assets'), ('assets/fonts', 'assets/fonts'),
                    ('build_assets/ffmpeg.exe.xz', '.'), ('build_assets/ffmpeg.exe.sha256', '.'),
                    ('mobile/web', 'mobile/web')],     # trang cho điện thoại (mapcap/mobile_server.py, v14)
             hiddenimports=['glcontext.wgl'], excludes=['PIL._avif', 'PIL.AvifImagePlugin', 'tkinter.test'],
             noarchive=False)
a.datas = [d for d in a.datas if not d[0].replace('\\\\', '/').startswith(DROP)]
pyz = PYZ(a.pure)
splash = Splash('build_assets/splash.png', binaries=a.binaries, datas=a.datas, text_pos=None, minify_script=True,
                always_on_top=False)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, splash, splash.binaries, [], name='AoE-MapCap', debug=False,
          strip=False, upx=False, console=False, uac_admin=True, icon=['assets/app.ico'])
"""
open("AoE-MapCap.spec", "w", encoding="utf-8").write(SPEC)
cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", "dist_gui", "--workpath", "build",
       "AoE-MapCap.spec"]
r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
if r.returncode != 0:
    print(r.stdout[-2000:], r.stderr[-2000:]); sys.exit(1)
# PyInstaller lặng lẽ bỏ module lỗi cú pháp ("invalid module") -> exe chỉ báo thiếu module lúc chạy: dừng build
_warn = os.path.join("build", "AoE-MapCap", "warn-AoE-MapCap.txt")
_bad = [l.strip() for l in open(_warn, encoding="utf-8", errors="replace")
        if l.startswith(("invalid module named mapcap", "invalid module named replay"))] if os.path.exists(_warn) else []
if _bad:
    print("LỖI: module không biên dịch được, không tạo exe: " + "; ".join(_bad)); sys.exit(1)
shutil.rmtree("build", ignore_errors=True)
running = "AoE-MapCap.exe" in subprocess.run(["tasklist"], capture_output=True, text=True).stdout
src = os.path.join("dist_gui", "AoE-MapCap.exe")
dst = os.path.join("dist", "AoE-MapCap.exe" + (".new" if running else ""))
os.makedirs("dist", exist_ok=True)
shutil.move(src, dst)
shutil.rmtree("dist_gui", ignore_errors=True)
print(("exe ĐANG CHẠY -> ghi ra " if running else "đã build ") + dst, f"{os.path.getsize(dst)/1e6:.1f} MB")
