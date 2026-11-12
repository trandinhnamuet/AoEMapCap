"""Replay (người dùng 12/11, lượt 3): số Chết đếm mọi unit chết (cả tự xoá / thú giết), cột Phù được, Đào vàng; bấm thẻ
người chơi góc phải trên tới nhà người đó; thẻ góc nhìn không còn dòng "chỗ tối..."; bảng công nghệ góc trái trên;
H / U / O ẩn hiện bằng trượt ra cạnh màn hình + mờ dần.

    python tests/test_replay_batch3.py <trận 2v2 có phù / giao tranh> [thư mục ảnh]
"""
import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import pygame  # noqa: E402

from replay import viewer as V  # noqa: E402
from replay.hud import Hud  # noqa: E402

path = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                          "Video", "_test", "replay_batch3")
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
hud = v.hud
W, H = v.size

# ---- chỉ số: chết / phù được ----------------------------------------------------------------
assert [c[0] for c in Hud.MIL_COLS] == ["Quân", "Kill", "Chết", "Phù được", "Công nghệ", "Đào vàng", "Bơm"]
v.seek_r(d.duration())
v._settle(5)
st = v.cursor.state
lost, conv = dict(st.lost), dict(st.conv)
kills = {i: int(st.pstate[i][0][20]) for i in st.pstate if i > 0 and len(st.pstate[i][0]) > 20}
print("chết", lost, "phù được", conv, "kill", kills)
for k, team in enumerate(d.teams):
    other = [i for t in d.teams if t is not team for i in t]
    dead = sum(lost.get(i, 0) for i in team)
    k_other = sum(kills.get(i, 0) for i in other)
    assert dead >= k_other - sum(conv.get(i, 0) for i in other) - 2, (k, dead, k_other)
assert sum(conv.values()) > 0, "trận thử cần có phù"
# tua lùi / tới giữa trận: đếm theo điểm mốc = đếm tuần tự
v.seek_r(d.duration() * 0.6)
v._settle(3)
mid = dict(v.cursor.state.lost)
v.seek_r(d.duration() * 0.2)
v._settle(3)
v.seek_r(d.duration() * 0.6)
v._settle(3)
assert dict(v.cursor.state.lost) == mid and all(mid.get(i, 0) <= lost.get(i, 0) for i in mid)
m = v._hud_model()
row = next(p for t in m.teams for p in t if p["index"] == max(conv, key=conv.get))
assert row["deaths"] == v.cursor.state.lost.get(row["index"], 0) and "conv" in row
print("Chết = mọi unit chết (≥ kill của đội kia), Phù được, tua tới / lui đếm giống nhau: OK")

# ---- thẻ góc nhìn: không dòng phụ; bấm thẻ người chơi -> tới nhà -------------------------------------
v._settle(5)
assert m.persp_card["sub"] is None
v.fit_view()
v._settle(30)
target = d.teams[-1][-1]
r = next(r for r, k in hud.persp_hits if k == ("pl", target))
v._mouse_down(SimpleNamespace(pos=r.center, button=1))
v._settle(90)
home = v.player_home(target)
assert v.persp_pl == target and v.selected == target
assert abs(v.cx - home[0]) < 40 and abs(v.cy - home[1]) < 40, ((v.cx, v.cy), home)
print("bấm thẻ người chơi: xem tầm nhìn người đó + máy quay tới nhà chính: OK")

# ---- bảng công nghệ góc trái trên -----------------------------------------------------------------
v._key(SimpleNamespace(key=pygame.K_c, mod=0, unicode="c"))
v._settle(30)
assert hud.show_techs and hud.r_techs is not None and hud.r_techs.x < W * 0.1 and hud.r_techs.y < H * 0.1, hud.r_techs
v._shot("t1_cong_nghe_trai_tren")
print("bảng công nghệ: góc trái trên", hud.r_techs, ": OK")
v._key(SimpleNamespace(key=pygame.K_c, mod=0, unicode="c"))
v._settle(30)


# ---- H / U / O: trượt + mờ dần --------------------------------------------------------------------
def key(k):
    v._key(SimpleNamespace(key=k, mod=0, unicode=""))


mm0 = hud.minimap_rect().copy()
tl0 = hud.r_timeline.copy()
key(pygame.K_h)
v._settle(7)                          # ~0,12 s: đang trượt
a = hud.anim["bar"]
assert 0.2 < a < 0.8, a
mm1 = hud.minimap_rect()
assert mm1 is not None and mm1.y > mm0.y, (mm0, mm1)
v._shot("h1_dang_an")
v._settle(30)
assert hud.anim["bar"] == 0 and hud.anim["top"] == 0 and hud.minimap_rect() is None and hud.r_timeline is None
key(pygame.K_h)
v._settle(30)
assert hud.anim["bar"] == 1 and hud.minimap_rect() == mm0 and hud.r_timeline == tl0
print("H: thanh dưới + bản đồ nhỏ trượt xuống, mờ dần, hiện lại đúng chỗ: OK")

key(pygame.K_u)
v._settle(7)
assert 0 < hud.anim["tl"] < 1 and hud.minimap_rect().y > mm0.y
v._settle(30)
assert hud.r_timeline is None and hud.minimap_rect().y > mm0.y
key(pygame.K_u)
v._settle(30)
assert hud.r_timeline == tl0 and hud.minimap_rect() == mm0
print("U: thanh thời gian trượt xuống, thanh dưới hạ dần theo: OK")

key(pygame.K_o)
v._settle(7)
assert 0 < hud.anim["score"] < 1
v._shot("o1_dang_an_bang")
v._settle(30)
assert hud.anim["score"] == 0 and not hud.score_rows
key(pygame.K_o)
v._settle(30)
assert hud.anim["score"] == 1 and hud.score_rows
print("O: bảng chỉ số trượt xuống + mờ, hiện lại: OK")
print("OK test_replay_batch3")
