"""Build dist\AoE-MapCap.exe. KHÔNG ghi đè khi exe đang chạy (tiến trình con sẽ đọc archive sai -> zlib error):
khi đó xuất ra dist\AoE-MapCap.exe.new và báo để đổi tên sau."""
import os, shutil, subprocess, sys
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed", "--uac-admin",
       "--name", "AoE-MapCap", "--icon", "assets/app.ico", "--add-data", "assets/app.ico;assets",
       "--add-binary", "vendor/ffmpeg.exe;.", "--distpath", "dist_gui", "--workpath", "build", "run_app.py"]
r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
if r.returncode != 0:
    print(r.stdout[-2000:], r.stderr[-2000:]); sys.exit(1)
shutil.rmtree("build", ignore_errors=True)
running = "AoE-MapCap.exe" in subprocess.run(["tasklist"], capture_output=True, text=True).stdout
src = os.path.join("dist_gui", "AoE-MapCap.exe")
dst = os.path.join("dist", "AoE-MapCap.exe" + (".new" if running else ""))
os.makedirs("dist", exist_ok=True)
shutil.move(src, dst)
shutil.rmtree("dist_gui", ignore_errors=True)
print(("exe ĐANG CHẠY -> ghi ra " if running else "đã build ") + dst, f"{os.path.getsize(dst)/1e6:.1f} MB")
