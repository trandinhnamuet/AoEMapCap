"""Toàn bản đồ (F3) trận nhiều đội (người dùng 12/11, trận 2v2): sáng mọi chỗ có tầm nhìn của BẤT KỲ người chơi nào,
tối chỗ không ai thấy (trước: chỉ sáng theo đội vừa xem -> nhà đội kia tối dù quân vẫn chạy).

    python tests/test_fullmap_fog.py <trận.aoerec 2v2 / FFA> [thư mục ảnh]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np  # noqa: E402

from replay import viewer as V  # noqa: E402

path = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                          "Video", "_test", "fullmap_fog")
os.makedirs(out, exist_ok=True)
v = V.Viewer(path, None, print, selftest=out)
v._init_window()
v.data.start_index()
v._load_world()
while not v.data.done:
    time.sleep(0.2)
v._tick(0.0, False)
v.playing = False
d = v.data
assert len(d.teams) >= 2 and max(len(t) for t in d.teams) >= 1, d.teams
fogs = []
real = v.gpu.set_fog
v.gpu.set_fog = lambda f: (fogs.append(np.array(f)), real(f))[1]
for frac in (0.3, 0.7):
    v.seek_r(d.duration() * frac)
    v.set_persp(v.rec_team)
    v._settle()
    v.set_persp(None)
    v._settle()
    fog = fogs[-1]
    Vt = v.cursor.state.vis
    for team in d.teams:
        for i in team:
            seen = (Vt & np.uint32(d.players[i].visible_mask)) != 0
            assert seen.any(), (i, "không có tầm nhìn?")
            dark = int((fog[seen] != 255).sum())
            assert dark == 0, f"{d.players[i].name}: {dark} ô có tầm nhìn nhưng tối ở chế độ toàn bản đồ"
    nobody = (Vt & np.uint32(v._all_mask())) == 0
    assert (fog[nobody] < 255).all() and nobody.any()
    print(f"{frac:.0%} trận: toàn bản đồ sáng đủ tầm nhìn {sum(len(t) for t in d.teams)} người "
          f"({int((~nobody).sum())} ô), tối {int(nobody.sum())} ô không ai thấy: OK")
    v._shot(f"toan_ban_do_{int(frac * 100)}")
print("thẻ:", v.persp_label(), "|", v.hud.persp_hits and "có thẻ")
print("OK test_fullmap_fog")
