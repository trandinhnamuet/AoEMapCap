"""Thẻ người chơi góc phải trên (bấm = xem tầm nhìn người đó, thẻ Toàn bản đồ = F3) và máy quay tự động (phím A):
phát x8 trên trận thật, máy quay phải nhảy tới chỗ giao tranh ít nhất một lần.

    python tests/test_replay_cards.py <trận.aoerec có giao tranh> [thư mục ảnh]
"""
import os, sys, time
sys.path.insert(0, r"D:\Game\AoE-MapCap")
sys.stdout.reconfigure(encoding="utf-8")
from types import SimpleNamespace
import numpy as np
import pygame
from replay import viewer as V
path = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(r"D:\Game\AoE-MapCap", "Video", "_test", "replay_cards")
os.makedirs(out, exist_ok=True)
v = V.Viewer(path, None, print, selftest=out)
v._init_window(); v.data.start_index(); v._load_world()
while not v.data.done: time.sleep(0.2)
v._tick(0.0, False); v.playing = False
d = v.data
print("teams", d.teams, "rec_team", v.rec_team)
v.seek_r(d.duration() * 0.5); v._settle()
v._shot("c0_mac_dinh")
# bấm thẻ người chơi thứ 2 của đội người ghi (hoặc người đầu đội khác)
hits = v.hud.persp_hits
print("thẻ:", [k for _r, k in hits])
pl = [k for _r, k in hits if k[0] == "pl"]
target = pl[1][1] if len(pl) > 1 else pl[0][1]
r = next(r for r, k in hits if k == ("pl", target))
ev = SimpleNamespace(pos=r.center, button=1)
v._mouse_down(ev); v._settle()
print("sau bấm:", v.persp, v.persp_pl, v.persp_label())
assert v.persp_pl == target
v._shot("c1_bam_the_nguoi_choi")
r = next(r for r, k in v.hud.persp_hits if k == ("all", None))
v._mouse_down(SimpleNamespace(pos=r.center, button=1)); v._settle()
assert v.persp is None; print("thẻ Toàn bản đồ:", v.persp_label())
# máy quay tự động: toàn bản đồ, phát x8 30 giây thật mô phỏng
v.set_auto_cam(True)
v.seek_r(d.duration() * 0.55); v._settle(5)
v.speed_i = V.SPEEDS.index(8.0); v.playing = True
jumps = []
last = None
for i in range(60 * 20):
    v._tick(1 / 60, True)
    if v._dir_cell != last:
        last = v._dir_cell
        jumps.append((round(d.f_t[v.cursor.state.frame] / 1000), last))
    if i in (300, 900):
        v._shot(f"c2_auto_{i}")
print("máy quay tự động nhảy:", jumps[:20], "tổng", len(jumps))
assert jumps and v.auto_cam, "máy quay tự động không tới chỗ giao tranh nào"
# đầu trận (chưa có giao tranh): luôn khoá theo một unit, có lúc xem nhà đang xây (người dùng 12/11)
v.playing = False
fi = int(np.searchsorted(d.f_t[:d.n_frames], 40_000)); v.seek_r(d.f_r[fi]); v._settle(5)
v.set_auto_cam(True); v.speed_i = V.SPEEDS.index(4.0); v.playing = True
unlocked, modes = 0, set()
for i in range(60 * 30):
    v._tick(1 / 60, True)
    unlocked += (i > 5 and not v.follow)
    modes.add(v._dir_mode)
print("đầu trận: khung không khoá", unlocked, "chế độ", modes)
assert unlocked == 0, "máy quay tự động phải luôn khoá theo một unit"
assert "house" in modes or "build" in modes, "đầu trận phải có lúc xem nhà đang xây"
assert "work" in modes
v._take_camera()
assert not v.auto_cam, "tự kéo máy quay phải tắt máy quay tự động"
print("OK test_replay_cards")
