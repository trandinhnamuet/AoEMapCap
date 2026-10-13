"""Build dist\AoE-Replay.exe: trình xem replay chạy riêng (không cần quyền admin, không kèm ffmpeg/bộ ghi).
Giống build.py: exe đang chạy thì xuất ra dist\AoE-Replay.exe.new."""
import os, shutil, subprocess, sys
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
for _s in (sys.stdout, sys.stderr):                 # in tiếng Việt cả khi chuyển hướng ra file (cp1252)
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
NAME = "AoE-Replay"
cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
       "--name", NAME, "--icon", "assets/app.ico", "--add-data", "assets/app.ico;assets",
       "--hidden-import", "glcontext.wgl", "--exclude-module", "mapcap.engine", "--exclude-module", "mapcap.recproc",
       "--distpath", "dist_replay", "--workpath", "build_replay", "run_replay.py"]
r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
if r.returncode != 0:
    print(r.stdout[-2000:], r.stderr[-2000:]); sys.exit(1)
# PyInstaller lặng lẽ bỏ module lỗi cú pháp ("invalid module") -> exe chỉ báo thiếu module lúc chạy: dừng build
_warn = os.path.join("build_replay", "AoE-Replay", "warn-AoE-Replay.txt")
_bad = [l.strip() for l in open(_warn, encoding="utf-8", errors="replace")
        if l.startswith(("invalid module named mapcap", "invalid module named replay"))] if os.path.exists(_warn) else []
if _bad:
    print("LỖI: module không biên dịch được, không tạo exe: " + "; ".join(_bad)); sys.exit(1)
shutil.rmtree("build_replay", ignore_errors=True)
running = f"{NAME}.exe" in subprocess.run(["tasklist"], capture_output=True, text=True).stdout
src = os.path.join("dist_replay", f"{NAME}.exe")
dst = os.path.join("dist", f"{NAME}.exe" + (".new" if running else ""))
os.makedirs("dist", exist_ok=True)
shutil.move(src, dst)
shutil.rmtree("dist_replay", ignore_errors=True)
for spec in (f"{NAME}.spec",):
    if os.path.exists(spec):
        os.remove(spec)
print(("exe ĐANG CHẠY -> ghi ra " if running else "đã build ") + dst, f"{os.path.getsize(dst)/1e6:.1f} MB")
