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
cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed", "--uac-admin",
       "--name", "AoE-MapCap", "--icon", "assets/app.ico", "--add-data", "assets/app.ico;assets", "--add-data", "assets/fonts;assets/fonts",
       "--add-binary", "vendor/ffmpeg.exe;.", "--hidden-import", "glcontext.wgl",   # trình xem replay (moderngl)
       "--distpath", "dist_gui", "--workpath", "build", "run_app.py"]
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
