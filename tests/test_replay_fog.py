"""Trình xem replay: công trình địch đã thấy không biến mất trong sương mù; bản ghi nhớ (doppelganger) vẽ đúng kiến
trúc nền văn minh.

    python tests/test_replay_fog.py [file.aoerec]

Lỗi người dùng báo 23/10: (1) nhà địch đã thấy, mất tầm nhìn thì biến mất (chỉ còn nền đất) tới khi nhìn lại — game
không phải lúc nào cũng có doppelganger (ruộng: không bao giờ; nhà khác ~nửa số lần); (2) nhà của Carthage vẽ theo
kiến trúc Choson — doppel không có sprite (gid -1), vẽ theo bảng unit chung của empires.dat (giống nhau mọi civ).
Mặc định dùng trận 2v2 Video\\_test\\expand_ui\\Raw\\2026-10-23_003224_tran1.aoerec (bản sao trận thật).
"""
import os
import sys
import time
from types import SimpleNamespace

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

from replay.data import Cursor, ReplayData  # noqa: E402
from replay.viewer import Viewer  # noqa: E402

DEFAULT = os.path.join(ROOT, "Video", "_test", "expand_ui", "Raw", "2026-10-23_003224_tran1.aoerec")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    if not os.path.exists(path):
        print("bỏ qua: không có", path)
        return
    d = ReplayData(path)
    t0 = time.time()
    d.start_index().join()
    assert d.error is None, d.error
    print(f"lập chỉ mục {d.n_frames} mẫu: {time.time() - t0:.1f}s; công trình đã thấy theo đội:",
          [len(s) for s in d.seen])
    rec = d.recorder_index()
    rk = next(k for k, t in enumerate(d.teams) if rec in t)
    _, defs = d.def_arrays()
    fake = SimpleNamespace(data=d)
    cur = Cursor(d)
    n_fog = n_saved = n_dop = n_dop_fixed = 0
    civ_gids = {}
    coarse = set()                        # đối chiếu độc lập: công trình đội thấy ở các mẫu thưa của test
    vm = em = 0
    for i in d.teams[rk]:                 # OR, không cộng: đồng minh có tầm nhìn chung thì mặt nạ trùng bit
        vm |= int(d.players[i].visible_mask)
        em |= int(d.players[i].explored_mask)
    for fi in range(0, d.n_frames, 250):
        cur.seek(fi)
        st = cur.state
        U = st.units()
        if not len(U) or st.vis is None:
            continue
        di = np.clip(U["def"], 0, defs["n"] - 1)
        ut = np.where(U["def"] < defs["n"], defs["utype"][di], -1)
        tx = np.clip(np.floor(U["x"]).astype(int), 0, d.map_w - 1)
        ty = np.clip(np.floor(U["y"]).astype(int), 0, d.map_h - 1)
        vis = (st.vis[ty, tx] & np.uint32(vm)) != 0
        exp = vis | ((st.vis[ty, tx] & np.uint32(em)) != 0)
        k25 = U["kind"] == 25
        dop_tiles = {(int(a), int(b)) for a, b in zip(ty[k25 & ~vis], tx[k25 & ~vis])}
        enemy = np.array([o > 0 and o not in d.teams[rk] for o in U["owner"].tolist()], bool)
        seen = Viewer._seen_mask(fake, U, ut, rk, st.frame)
        coarse.update(U["uid"][(ut == 80) & ~k25 & vis].tolist())
        for i in np.nonzero((ut == 80) & ~k25 & enemy & exp & ~vis)[0].tolist():
            if (int(ty[i]), int(tx[i])) in dop_tiles or int(U["uid"][i]) not in coarse:
                continue
            n_fog += 1                    # công trình địch trong sương mù, game không có doppel ở ô đó
            n_saved += bool(seen[i])      # bản sửa: vẽ nếu đội đã thấy
        need = k25 & (U["gid"] < 0) & (ut == 80)
        if need.any():
            V = Viewer._doppel_sprites(fake, U, U)
            n_dop += int(need.sum())
            n_dop_fixed += int((V["gid"][need] >= 0).sum())
        for o, g, dd in zip(U["owner"][~k25 & (ut == 80)].tolist(), U["gid"][~k25 & (ut == 80)].tolist(),
                            U["def"][~k25 & (ut == 80)].tolist()):
            if d.defs.get(dd) is not None and d.defs[dd].dat_id == 109 and g >= 0:
                civ_gids.setdefault(d.players[o].civ, set()).add(g)
    print(f"công trình địch đội đã thấy, đang trong sương mù, không có doppel: {n_fog} lượt; bản sửa vẽ: {n_saved}")
    print(f"doppel công trình không có sprite: {n_dop}, lấy được sprite công trình thật: {n_dop_fixed}")
    print("sprite nhà chính (BN) theo civ:", {c: sorted(g) for c, g in civ_gids.items()})
    assert n_fog > 0 and n_saved == n_fog, (n_fog, n_saved)
    assert n_dop > 0 and n_dop_fixed >= 0.9 * n_dop, (n_dop, n_dop_fixed)
    if len(civ_gids) >= 2:
        a, b = list(civ_gids.values())[:2]
        if not (a & b):
            print("2 civ khác nhau dùng sprite BN khác nhau (vì thế không được vẽ doppel theo bảng chung): OK")
    print("OK test_replay_fog")


if __name__ == "__main__":
    main()
