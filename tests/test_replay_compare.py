"""So ảnh trình xem replay (GPU) với bộ vẽ video (CPU) ở cùng mẫu, cùng góc nhìn người ghi, cùng vùng bản đồ.

    python tests/test_replay_compare.py file.aoerec [chỉ_số_mẫu] [zoom]
Xuất Video/_test/compare.png: trái = video (VideoRenderer), phải = replay; in sai khác trung bình.
"""
import os
import sys
import time

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mapcap.rawrec import RawReader  # noqa: E402
from mapcap.video_render import VideoRenderer  # noqa: E402
from replay import viewer as V  # noqa: E402


def main():
    path = sys.argv[1]
    fi = int(sys.argv[2]) if len(sys.argv) > 2 else 1500
    zoom = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5
    out_dir = os.path.join(ROOT, "Video", "_test")
    v = V.Viewer(path, None, print, selftest=out_dir)
    v._init_window()
    v.data.start_index()
    v._load_world()
    while not v.data.done:
        time.sleep(0.2)
    v._tick(0.0, False)
    d = v.data
    fi = min(fi, d.n_frames - 1)
    v.playing = False
    v.r = d.f_r[fi]
    v._tick(0.0, True)
    fi = v.cursor.frame
    v.set_persp(v.rec_team)
    home = v.player_home(d.recorder_index())
    v.cx, v.cy = home
    v.zoom = v.zoom_target = zoom
    v.hud.show_hud = False
    v.toast = None
    v._hud_dirty = True
    for _ in range(20):
        v._tick(0.0, True)
    v.ctx.finish()
    rep = Image.frombytes("RGB", v.size, v.fbo.read(components=3)).transpose(Image.FLIP_TOP_BOTTOM)
    tlx, tly = v.cam_tl()
    W, H = v.size
    # bộ vẽ video ở tỉ lệ = zoom
    w = v.world
    vr = VideoRenderer(w.dat, w.store, w.pal, width=int(round(w.full_w * zoom)), fog_dim=V.FOG_DIM, outline_alpha=0.35)
    snap = None
    for i, sn in enumerate(RawReader(path).frames()):
        if i == fi:
            snap = sn
            break
    img = vr.render(snap, overlay=False)
    s = vr.scale
    box = (int(round(tlx * s)), int(round(tly * s)), int(round(tlx * s)) + W, int(round(tly * s)) + H)
    vid = img.crop(box)
    a = np.asarray(vid, np.int16)
    b = np.asarray(rep, np.int16)
    diff = np.abs(a - b).mean()
    print(f"mẫu {fi}, zoom {zoom}, tỉ lệ video {s:.4f}: sai khác trung bình {diff:.1f} / 255")
    both = Image.new("RGB", (W * 2 + 8, H), (255, 0, 255))
    both.paste(vid, (0, 0))
    both.paste(rep, (W + 8, 0))
    both.save(os.path.join(out_dir, "compare.png"))
    print("->", os.path.join(out_dir, "compare.png"))


if __name__ == "__main__":
    main()
