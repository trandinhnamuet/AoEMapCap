"""Kiểm tra xử lý lỗi khi dựng video: chọn encoder theo kích thước thật (Quick Sync từ chối > 4096 px), VideoWriter báo
lỗi rõ khi ffmpeg chết, render_raw dừng ngay và xoá thư mục tạm khi một đoạn lỗi, cleanup_stale dọn aoerender_* chết."""
import os, sys, time, glob, subprocess
sys.path.insert(0, r"D:\Game\AoE-MapCap")
import numpy as np
from mapcap.recorder import find_ffmpeg, pick_encoder, VideoWriter
from mapcap import offline
from mapcap.offline import render_raw, cleanup_stale, scan_info, output_size, TMP_PREFIX, OWNER_FILE

P = lambda m: print(m, flush=True)
ffmpeg = find_ffmpeg([r"D:\Game\AoE-HD"])
assert ffmpeg, "không có ffmpeg"
rec = r"D:\Game\AoE-MapCap\Video\_test\raw\test_tran1.aoerec"
if not os.path.isfile(rec):
    subprocess.run([sys.executable, r"D:\Game\AoE-MapCap\tests\test_raw.py"], check=True)
times, n_dop, hdr = scan_info(rec)
size_big = output_size(hdr, 9216)
size_hd = output_size(hdr, 1920)
P(f"kích thước khung: 1920 -> {size_hd}, 9216 -> {size_big}")
assert size_hd[0] == 1920 and size_big[0] == 9216 and size_big[1] % 2 == 0

# 1) chọn encoder theo kích thước: ở 9216 px không được chọn mã hoá phần cứng (QSV/NVENC từ chối), ở 1080p vẫn như trước
t0 = time.time(); enc_big = pick_encoder(ffmpeg, log=P, size=size_big); t1 = time.time()
enc_hd = pick_encoder(ffmpeg, log=P, size=size_hd)
P(f"encoder 9216px: {enc_big} ({t1 - t0:.1f}s), 1080p: {enc_hd}")
assert enc_big == "libx264", enc_big
assert enc_hd in ("h264_qsv", "h264_nvenc", "h264_amf", "libx264")

# 2) VideoWriter: ffmpeg chết (QSV ở 9216 px) -> RuntimeError có tên encoder và kích thước, không BrokenPipeError
out = r"D:\Game\AoE-MapCap\Video\_test\fail_test.mp4"
wr = VideoWriter(ffmpeg, out, size_big, 25, "h264_qsv", log=P)
frame = bytes(size_big[0] * size_big[1] * 3)
err = None
try:
    for _ in range(40):
        wr.write(frame)
        time.sleep(0.05)
except RuntimeError as e:
    err = str(e)
except BrokenPipeError as e:
    raise AssertionError(f"vẫn lọt BrokenPipeError: {e}")
P(f"lỗi VideoWriter: {err}")
assert err and "h264_qsv" in err and f"{size_big[0]}x{size_big[1]}" in err
try:
    wr.close()
except Exception:  # noqa: BLE001
    pass
for f in glob.glob(out[:-4] + "*"):
    os.remove(f)

# 3) render_raw với game_dir sai -> mọi đoạn lỗi; phải báo lỗi nhanh (không chờ) và không để lại aoerender_*
vdir = os.path.dirname(rec)
before = set(glob.glob(os.path.join(vdir, TMP_PREFIX + "*")))
t0 = time.time()
try:
    render_raw(rec, os.path.join(vdir, "fail.mp4"), width=640, fps=25, game_dir=r"D:\khong_ton_tai", workers=2, log=P)
    raise AssertionError("phải lỗi")
except RuntimeError as e:
    P(f"render_raw lỗi như mong đợi sau {time.time() - t0:.1f}s: {e}")
    assert "đoạn lỗi" in str(e)
after = set(glob.glob(os.path.join(vdir, TMP_PREFIX + "*")))
assert after == before, f"còn thư mục tạm: {after - before}"
assert offline.active_renders() == 0 and not offline._JOBS

# 4) cleanup_stale: thư mục có owner.pid chết -> xoá; owner là tiến trình này -> giữ; không owner nhưng mới -> giữ;
#    không owner và cũ -> xoá
d_dead = os.path.join(vdir, TMP_PREFIX + "dead"); os.makedirs(d_dead, exist_ok=True)
open(os.path.join(d_dead, OWNER_FILE), "w").write("999999")
open(os.path.join(d_dead, "part00.part.mp4"), "wb").write(b"x")
d_mine = os.path.join(vdir, TMP_PREFIX + "mine"); os.makedirs(d_mine, exist_ok=True)
open(os.path.join(d_mine, OWNER_FILE), "w").write(str(os.getpid()))
d_new = os.path.join(vdir, TMP_PREFIX + "noowner_new"); os.makedirs(d_new, exist_ok=True)
open(os.path.join(d_new, "part00.mp4"), "wb").write(b"x")
d_old = os.path.join(vdir, TMP_PREFIX + "noowner_old"); os.makedirs(d_old, exist_ok=True)
f_old = os.path.join(d_old, "part00.mp4"); open(f_old, "wb").write(b"x")
old_t = time.time() - 2 * 3600
os.utime(f_old, (old_t, old_t)); os.utime(d_old, (old_t, old_t))
n = cleanup_stale(vdir, log=P)
P(f"cleanup_stale xoá {n}")
assert not os.path.isdir(d_dead) and not os.path.isdir(d_old), "phải xoá thư mục chết/cũ"
assert os.path.isdir(d_mine) and os.path.isdir(d_new), "không được xoá thư mục đang dùng/mới"
assert n == 2
import shutil
shutil.rmtree(d_mine); shutil.rmtree(d_new)

# 5) abort_all khi đang dựng: tiến trình đoạn bị tắt, thư mục tạm bị xoá, render_raw kết thúc bằng lỗi "huỷ"
import threading
res = {}
def run():
    try:
        render_raw(rec, os.path.join(vdir, "abort.mp4"), width=640, fps=25, game_dir=r"D:\Game\AoE-HD", workers=2, log=P)
        res["ok"] = True
    except RuntimeError as e:
        res["err"] = str(e)
th = threading.Thread(target=run); th.start()
for _ in range(100):
    if offline._JOBS:
        break
    time.sleep(0.1)
assert offline._JOBS, "lượt dựng chưa bắt đầu"
procs = list(offline._JOBS[0]["procs"]); tmp = offline._JOBS[0]["tmp_dir"]
time.sleep(1.0)
n = offline.abort_all(log=P)
th.join(timeout=30)
P(f"abort_all huỷ {n}, kết quả: {res}")
assert n == 1 and "huỷ" in res.get("err", ""), res
assert all(p.poll() is not None for p in procs), "tiến trình đoạn vẫn chạy"
assert not os.path.isdir(tmp), "thư mục tạm còn"
assert not os.path.isfile(os.path.join(vdir, "abort.mp4"))
P("OK test_render_fail")
