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


def build_launcher():
    """launcher/autostart.c -> build_assets/AoE-MapCap-start.exe (trình khởi chạy lúc đăng nhập, mapcap/winstartup.py).
    MSVC (vswhere + vcvars64, có sẵn trên máy build GitHub) nếu có, không thì zig cc (pip install ziglang)."""
    import tempfile
    src = os.path.join(ROOT, "launcher", "autostart.c")
    out = os.path.join(ROOT, "build_assets", "AoE-MapCap-start.exe")
    if os.path.exists(out):
        os.remove(out)
    vswhere = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Microsoft Visual Studio",
                           "Installer", "vswhere.exe")
    if os.path.isfile(vswhere):
        inst = subprocess.run([vswhere, "-latest", "-products", "*", "-requires",
                               "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
                              capture_output=True, text=True).stdout.strip()
        vcvars = os.path.join(inst, "VC", "Auxiliary", "Build", "vcvars64.bat") if inst else ""
        if os.path.isfile(vcvars):
            obj = os.path.join(ROOT, "build_assets", "autostart.obj")      # không để "\\" cuối (cl đọc \\" = dấu nháy)
            bat = os.path.join(tempfile.mkdtemp(prefix="aoelauncher_"), "cc.bat")
            open(bat, "w", encoding="ascii").write(
                f'@call "{vcvars}" >nul\r\n@cl /nologo /O1 /W3 /GS /MT /DUNICODE /D_UNICODE /Fo"{obj}" "{src}" '
                f'/link /SUBSYSTEM:WINDOWS kernel32.lib /OUT:"{out}"\r\n')
            r = subprocess.run(["cmd", "/d", "/c", bat], capture_output=True, text=True, errors="replace")
            if r.returncode == 0 and os.path.isfile(out):
                return "MSVC"
            print("MSVC lỗi:", r.stdout[-1500:], r.stderr[-800:])
    try:
        import ziglang  # noqa: F401
        r = subprocess.run([sys.executable, "-m", "ziglang", "cc", "-target", "x86_64-windows-gnu", "-O2", "-s",
                            "-municode", "-mwindows", src, "-o", out], capture_output=True, text=True, errors="replace")
        if r.returncode == 0 and os.path.isfile(out):
            return "zig"
        print("zig lỗi:", r.stdout[-1500:], r.stderr[-800:])
    except ImportError:
        pass
    print("LỖI: không biên dịch được launcher/autostart.c (cần MSVC hoặc pip install ziglang)")
    sys.exit(1)


print("trình khởi chạy lúc đăng nhập:", build_launcher())
TEST_NO_UAC = "--test-no-uac" in sys.argv          # chỉ để thử (không hỏi UAC), ra dist_test\, không thay dist\
SPEC = f"""# sinh bởi build.py — không sửa tay
DROP = ('_tcl_data/tzdata', '_tcl_data/msgs', '_tk_data/msgs', '_tk_data/images', '_tcl_data/http1.0', '_tcl_data/opt0.4')
a = Analysis(['run_app.py'], pathex=[], binaries=[],
             datas=[('assets/app.ico', 'assets'), ('assets/fonts', 'assets/fonts'),
                    ('build_assets/ffmpeg.exe.xz', '.'), ('build_assets/ffmpeg.exe.sha256', '.'),
                    ('build_assets/AoE-MapCap-start.exe', 'autostart')],  # khởi động cùng Windows không màn hình chờ
             hiddenimports=['glcontext.wgl'], excludes=['PIL._avif', 'PIL.AvifImagePlugin', 'tkinter.test'],
             noarchive=False)
a.datas = [d for d in a.datas if not d[0].replace('\\\\', '/').startswith(DROP)]
pyz = PYZ(a.pure)
splash = Splash('build_assets/splash.png', binaries=a.binaries, datas=a.datas, text_pos=None, minify_script=True,
                always_on_top=False)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, splash, splash.binaries, [], name='AoE-MapCap', debug=False,
          strip=False, upx=False, console=False, uac_admin={not TEST_NO_UAC}, icon=['assets/app.ico'])
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
if TEST_NO_UAC:
    dst = os.path.join("dist_test", "AoE-MapCap.exe")
    if os.path.exists(dst):
        os.remove(dst)
os.makedirs(os.path.dirname(dst), exist_ok=True)
shutil.move(src, dst)
shutil.rmtree("dist_gui", ignore_errors=True)
print(("bản thử (không UAC) " if TEST_NO_UAC else "exe ĐANG CHẠY -> ghi ra " if running else "đã build ") + dst,
      f"{os.path.getsize(dst)/1e6:.1f} MB")
