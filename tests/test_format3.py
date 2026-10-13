"""Định dạng 3 (khối 'B' + vật thể tĩnh 'Q'): chuyển một trận thật sang định dạng mới rồi so từng chi tiết với bản gốc
(unit, tầm nhìn, thuộc tính, vật thể tĩnh, hàng đợi, nghiên cứu, chỉ số def, thắng/thua) ở nhiều mẫu ngẫu nhiên.

    python tests/test_format3.py [file.aoerec]
"""
import glob
import os
import random
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mapcap.rawrec import RawReader, read_end, read_header, recompress  # noqa: E402
from replay.data import Cursor, ReplayData  # noqa: E402
from replay.library import first_out, match_info  # noqa: E402


def same_units(a, b):
    a = a[np.argsort(a["uid"], kind="stable")]
    b = b[np.argsort(b["uid"], kind="stable")]
    return len(a) == len(b) and a.tobytes() == b.tobytes()


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else max(glob.glob(os.path.join(ROOT, "dist", "Video", "Raw", "*.aoerec")),
                                                    key=os.path.getmtime)
    out_dir = os.path.join(ROOT, "Video", "_test", "format3")
    os.makedirs(out_dir, exist_ok=True)
    dst = os.path.join(out_dir, os.path.basename(src))
    t0 = time.time()
    old, new = recompress(src, dst)
    print(f"{os.path.basename(src)}: {old / 1e6:.1f} MB -> {new / 1e6:.1f} MB ({old / new:.1f} lần), {time.time() - t0:.1f} s")
    a, b = ReplayData(src), ReplayData(dst)
    ta = time.time(); a.start_index().join(); ta = time.time() - ta
    tb = time.time(); b.start_index().join(); tb = time.time() - tb
    print(f"lập chỉ mục: gốc {ta:.1f} s, mới {tb:.1f} s; mẫu {a.n_frames} / {b.n_frames}")
    assert a.error is None and b.error is None and a.n_frames == b.n_frames
    assert a.f_t == b.f_t and a.f_at == b.f_at and a.f_r == b.f_r
    assert len(a.s_rec) == len(b.s_rec) and a.s_first == b.s_first
    import pickle                                   # so bằng pickle: chỉ số có thể chứa NaN (NaN != NaN)
    assert set(a.stats) == set(b.stats) and all(pickle.dumps(a.stats[k]) == pickle.dumps(b.stats[k]) for k in a.stats)
    assert {k: v.__dict__ for k, v in a.defs.items()} == {k: v.__dict__ for k, v in b.defs.items()}
    ca, cb = Cursor(a), Cursor(b)
    random.seed(7)
    picks = sorted(random.sample(range(a.n_frames), 25)) + [a.n_frames - 1, 0]
    t_seek = []
    for fi in picks + list(reversed(picks)):
        ca.seek(fi)
        t1 = time.perf_counter(); cb.seek(fi); t_seek.append(time.perf_counter() - t1)
        sa, sb = ca.state, cb.state
        assert same_units(sa.units(), sb.units()), fi
        assert np.array_equal(sa.vis, sb.vis), fi
        assert sa.pstate == sb.pstate and sa.tech_times == sb.tech_times and sa.pstat == sb.pstat, fi
        assert sa.prs == sb.prs and sa.prod == sb.prod and sa.go == sb.go, fi
        ia, va, xa = ca.statics()
        ib, vb, xb = cb.statics()
        assert ia == ib and va == vb and same_units(xa, xb), (fi, ia, len(xa), len(xb))
    print(f"so {len(picks) * 2} lần tua: khớp tuyệt đối; tua bản mới trung bình {1000 * np.mean(t_seek):.0f} ms, "
          f"tối đa {1000 * max(t_seek):.0f} ms")
    # bộ đọc tuần tự (dùng khi xuất video) cho cùng kết quả
    na = sum(1 for _ in RawReader(src).records())
    nb_f = sum(1 for t, _ in RawReader(dst).records() if t == b"F")
    assert nb_f == a.n_frames, (nb_f, a.n_frames)
    ia, ib = match_info(src), match_info(dst)
    for k in ("recorder", "recorder_civ", "result", "format", "civ_mode", "map", "duration_ms", "frames"):
        assert ia[k] == ib[k], (k, ia[k], ib[k])
    assert first_out(src) == first_out(dst), (first_out(src), first_out(dst))
    assert read_header(dst).get("format") == 3 or "format" not in read_header(src)
    print("thông tin trận khớp:", {k: ib[k] for k in ("result", "format", "civ_mode", "map")}, "first_out", first_out(dst))
    print("OK")


if __name__ == "__main__":
    main()
