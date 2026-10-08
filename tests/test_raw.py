"""Ghi 300 mẫu giả (12 s ở 25/s) ra .aoerec rồi dựng video song song; kiểm tra kích cỡ và số khung."""
import os, sys, time, pickle, copy, subprocess, glob
sys.path.insert(0, r"D:\Game\AoE-MapCap")
import numpy as np
from mapcap.rawrec import RawWriter, RawReader
from mapcap.offline import render_raw, scan_times

snap0 = pickle.load(open(r"D:\Game\AoE-HD\Screenshot\FullMap\2026-09-18_131113_now.snap", "rb"))
out_dir = r"D:\Game\AoE-MapCap\Video\_test\raw"
os.makedirs(out_dir, exist_ok=True)
for f in glob.glob(out_dir + r"\*"):
    os.remove(f)
rec = os.path.join(out_dir, "test_tran1.aoerec")
p = snap0.cur_player
h, w = snap0.terrain.shape; yy, xx = np.mgrid[0:h, 0:w]
trees = [u for u in snap0.units if "tree" in u.udef.name.lower()] or snap0.units[:3]
statics = []
for i in range(800):
    t = copy.copy(trees[i % len(trees)]); t.x, t.y, t.uid = (i * 7) % w + 0.5, (i * 13) % h + 0.5, 10_000_000 + i; statics.append(t)
wr = RawWriter(rec)
t_wall = time.time()
times = []
for k in range(300):
    s = pickle.loads(pickle.dumps(snap0))
    s.taken_at = t_wall + k / 25.0
    s.time_ms = snap0.time_ms + k * 40
    for u in s.units:
        if u.udef.utype == 70:
            u.x += k * 0.03; u.angle = (k // 10) % 8
    vis = snap0.vis_raw.copy()
    r = 10 + k * 0.1
    vis[((xx - 100) ** 2 + (yy - 70) ** 2) < r ** 2] |= np.uint32(p.explored_mask | p.visible_mask)
    s.vis_raw = vis
    s.static_units = statics
    s.static_version = 1 if k < 150 else 2            # đổi 1 lần giữa chừng
    if k == 150:
        statics = statics[:-50]
        s.static_units = statics
    t0 = time.time()
    if k == 0:
        wr.start(s)
    else:
        wr.add_frame(s)
    times.append(time.time() - t0)
n = wr.close()
sz = os.path.getsize(rec)
print(f"ghi {n} mẫu: {sz/1e6:.1f} MB ({sz/n/1024:.1f} KB/mẫu), thời gian ghi TB {sum(times)/len(times)*1000:.1f} ms, max {max(times)*1000:.0f} ms")
# đọc lại
rd = RawReader(rec); cnt = 0; last = None
for snap in rd.frames():
    cnt += 1; last = snap
print(f"đọc lại {cnt} mẫu; mẫu cuối: {len(last.units)} unit, {len(last.static_units)} tĩnh, time {last.time_str()}")
assert cnt == 300 and len(last.static_units) == 750
# dựng video 1080p 25 fps với 3 tiến trình
t0 = time.time()
out = os.path.join(out_dir, "test_tran1.mp4")
render_raw(rec, out, width=1920, fps=25, speed=1.0, game_dir=r"D:\Game\AoE-HD", workers=3, log=print)
print(f"dựng xong {time.time()-t0:.1f}s")
print(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_entries", "stream=nb_read_frames,r_frame_rate,width,height", "-of", "default=nw=1", out], capture_output=True, text=True).stdout.strip().replace("\n", " "))
# ảnh khung giữa để soi
subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "6", "-i", out, "-frames:v", "1", os.path.join(out_dir, "mid.png")])
print("OK")
