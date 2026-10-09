"""Kiểm tra replay/world.py: dựng địa hình + bản đồ chỉ số ô, danh sách mảnh sprite; xuất ảnh xem bằng mắt.

    python tests/test_replay_world.py file.aoerec [game_dir]
"""
import os
import sys
import time

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from replay.data import Cursor, ReplayData  # noqa: E402
from replay.world import World, load_graphics  # noqa: E402


def main():
    path = sys.argv[1]
    gdir = sys.argv[2] if len(sys.argv) > 2 else r"D:\Game\AoE-HD"
    out_dir = os.path.join(ROOT, "Video", "_test")
    os.makedirs(out_dir, exist_ok=True)
    d = ReplayData(path)
    d.start_index().join()
    t0 = time.time()
    dat, store, pal = load_graphics(gdir)
    print(f"nạp đồ hoạ {time.time() - t0:.2f} s")
    w = World(d.header, dat, store, pal)
    print("thế giới", w.full_w, w.full_h, "tỉ lệ địa hình", w.ts, "ảnh", w.tex_w, w.tex_h)
    t0 = time.time(); w.build_terrain(); print(f"địa hình {time.time() - t0:.2f} s")
    t0 = time.time(); w.build_index(); print(f"chỉ số ô {time.time() - t0:.2f} s, còn hở {(w.index == w.out_id).sum()} px")
    small = Image.fromarray(w.terrain).resize((w.tex_w // 4, w.tex_h // 4), Image.BOX)
    small.save(os.path.join(out_dir, "replay_terrain.png"))
    cur = Cursor(d)
    cur.seek(d.n_frames // 2)
    U = cur.state.units()
    _, defs = d.def_arrays()
    U = U[w.depth_order(U)]
    t0 = time.perf_counter()
    slot, x0, y0, br, ui = w.instances(U, defs, np.ones(len(U), np.float32))
    t1 = time.perf_counter()
    slot, x0, y0, br, ui = w.instances(U, defs, np.ones(len(U), np.float32))
    t2 = time.perf_counter()
    print(f"{len(U)} unit -> {len(slot)} mảnh; lần đầu {1000 * (t1 - t0):.1f} ms, lần sau {1000 * (t2 - t1):.2f} ms; "
          f"{len(w.slot_keys)} slot sprite")
    si, ver, S = cur.statics()
    S = S[w.depth_order(S)]
    t0 = time.perf_counter()
    s2 = w.instances(S, defs, -np.ones(len(S), np.float32))
    print(f"{len(S)} vật thể tĩnh -> {len(s2[0])} mảnh, {1000 * (time.perf_counter() - t0):.1f} ms")
    # ghép thử bằng CPU một vùng 1600x900 quanh tâm để so với video
    cx, cy = w.full_w // 2, w.full_h // 2
    box = (cx - 800, cy - 450, cx + 800, cy + 450)
    ts = w.ts
    crop = Image.fromarray(w.terrain).crop(tuple(int(v * ts) for v in box)).resize((1600, 900), Image.NEAREST)
    for sl, xs, ys, uix in ((s2[0], s2[1], s2[2], s2[4]), (slot, x0, y0, ui)):
        for s, x, y in zip(sl.tolist(), xs.tolist(), ys.tolist()):
            if box[0] - 300 < x < box[2] and box[1] - 300 < y < box[3]:
                im = store.frame(*w.slot_keys[s])[0]
                crop.paste(im, (int(x - box[0]), int(y - box[1])), im)
    crop.save(os.path.join(out_dir, "replay_crop.png"))
    print("OK ->", out_dir)


if __name__ == "__main__":
    main()
