"""Kiểm tra replay/data.py: trạng thái sau khi tua (điểm mốc + áp mẫu) phải trùng với đọc tuần tự bằng RawReader.

    python tests/test_replay_data.py [file.aoerec]
"""
import glob
import os
import random
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mapcap.rawrec import RawReader  # noqa: E402
from replay.data import Cursor, ReplayData  # noqa: E402


def main():
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        files = sorted(glob.glob(os.path.join(ROOT, "dist", "Video", "Raw", "*.aoerec")), key=os.path.getsize)
        path = files[len(files) // 2]
    print("file", os.path.basename(path), f"{os.path.getsize(path) / 1e6:.1f} MB")
    d = ReplayData(path)
    t0 = time.time()
    d.start_index().join()
    assert d.error is None, d.error
    n = d.n_frames
    print(f"lập chỉ mục {n} mẫu trong {time.time() - t0:.2f} s, {len(d.keys)} điểm mốc, {len(d.s_rec)} bản ghi tĩnh, "
          f"thời gian phát {d.duration():.0f} s, game {d.f_t[-1] / 1000:.0f} s")
    print("đội:", [[d.players[i].name for i in t] for t in d.teams])
    random.seed(1)
    targets = sorted(random.sample(range(min(n, 1500)), min(6, n)))
    want = {}
    for i, snap in enumerate(RawReader(path).frames()):
        if i in targets:
            want[i] = ({u.uid: (u.x, u.y, u.hp, u.gid) for u in snap.units}, snap.vis_raw.copy(),
                       [p.attrs for p in snap.players])
        if i >= targets[-1]:
            break
    cur = Cursor(d)
    order = list(reversed(targets)) + targets            # tua lùi rồi tiến
    for fi in order:
        t1 = time.perf_counter()
        cur.seek(fi)
        dt = time.perf_counter() - t1
        arr = cur.state.units()
        got = {int(u["uid"]): (float(u["x"]), float(u["y"]), float(u["hp"]), int(u["gid"])) for u in arr}
        wu, wv, wa = want[fi]
        assert set(got) == set(wu), (fi, len(got), len(wu))
        for uid, v in wu.items():
            assert np.allclose(got[uid], v), (fi, uid, got[uid], v)
        assert np.array_equal(cur.state.vis, wv), fi
        pl = d.players_at(cur.state)
        for p, a in zip(pl, wa):
            assert tuple(p.attrs) == tuple(a), (fi, p.index)
        print(f"  mẫu {fi}: {len(got)} unit khớp, tua {dt * 1000:.1f} ms")
    si, ver, st = cur.statics()
    print("vật thể tĩnh tại mẫu cuối:", si, ver, len(st))
    print("OK")


if __name__ == "__main__":
    main()
