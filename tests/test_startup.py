"""Khởi động nhanh: ffmpeg đóng gói dạng .xz chỉ giải nén khi cần (recorder.bundled_ffmpeg / find_ffmpeg)."""
import hashlib
import lzma
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mapcap import recorder  # noqa: E402

tmp = tempfile.mkdtemp(prefix="aoestartup_")
mei = os.path.join(tmp, "mei")
os.makedirs(mei)
payload = open(os.path.join(os.environ["WINDIR"], "System32", "PING.EXE"), "rb").read()
sha = hashlib.sha256(payload).hexdigest()
with lzma.open(os.path.join(mei, "ffmpeg.exe.xz"), "wb") as f:
    f.write(payload)
open(os.path.join(mei, "ffmpeg.exe.sha256"), "w", encoding="ascii").write(sha + "  ffmpeg.exe\n")
os.environ["LOCALAPPDATA"] = os.path.join(tmp, "local")
sys._MEIPASS = mei
try:
    # chưa giải nén + không cần: không tạo gì, không dò ffmpeg chỗ khác
    assert recorder.find_ffmpeg(extract=False) is None
    assert not os.path.exists(os.environ["LOCALAPPDATA"])
    # cần: giải nén đúng nội dung
    p = recorder.find_ffmpeg()
    assert p and os.path.basename(p) == f"ffmpeg-{sha[:12]}.exe" and open(p, "rb").read() == payload, p
    assert not os.path.exists(p + ".part")
    # đã có sẵn: extract=False vẫn trả về (tiến trình mới phải kiểm lại SHA)
    recorder._FFMPEG_OK.clear()
    assert recorder.find_ffmpeg(extract=False) == p
    # file giải nén bị sửa: kiểm SHA thấy sai -> giải nén lại
    recorder._FFMPEG_OK.clear()
    open(p, "wb").write(b"MZ bad")
    assert recorder.find_ffmpeg() == p and open(p, "rb").read() == payload
    # gói bị hỏng (SHA không khớp): không dùng, không để lại .part
    recorder._FFMPEG_OK.clear()
    os.remove(p)
    open(os.path.join(mei, "ffmpeg.exe.sha256"), "w", encoding="ascii").write("0" * 64 + "\n")
    bad = recorder.bundled_ffmpeg(True)
    assert bad is None and not os.listdir(os.path.dirname(p)), os.listdir(os.path.dirname(p))
    print("bundled ffmpeg ok")
finally:
    del sys._MEIPASS
    shutil.rmtree(tmp, ignore_errors=True)

# tiến trình con / chế độ không cửa sổ: tắt màn hình chờ ngay (run_app.CHILD_FLAGS)
import run_app  # noqa: E402
for a in ("--replay", "--render-chunk", "--render-raw", "--render-still", "--nogui", "--multiprocessing-fork"):
    assert a.startswith(run_app.CHILD_FLAGS)
assert not "--autostart".startswith(run_app.CHILD_FLAGS)
run_app.close_splash()                        # chạy từ mã nguồn: không có pyi_splash, không lỗi
print("OK test_startup")
