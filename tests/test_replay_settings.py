"""Nút ⚙ Cài đặt trên thanh thời gian replay (người dùng 12/11): bấm mở bảng (máy quay tự động, tầm nhìn, tốc độ, âm
thanh, bảng hiện / ẩn, toàn màn hình, bảng phím tắt); bấm từng nút đổi đúng trạng thái; bấm ngoài / Esc đóng bảng;
bảng nằm trong màn hình, trên thanh thời gian.

    python tests/test_replay_settings.py <trận.aoerec> [thư mục ảnh]
"""
import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import pygame  # noqa: E402

from replay import viewer as V  # noqa: E402

path = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                          "Video", "_test", "replay_settings")
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
v.seek_r(d.duration() * 0.5)
v._settle()


def click(pos, button=1):
    v._mouse_down(SimpleNamespace(pos=pos, button=button))
    v._mouse_up(SimpleNamespace(pos=pos, button=button))
    v._settle(3)


def btn(pred):
    for r, act in hud.settings_hits:
        if pred(act):
            return r.center
    raise AssertionError("không thấy nút")


assert hud.r_settings is not None and hud.r_help is not None
assert hud.r_settings.right < hud.r_help.x and hud.r_timeline.right < hud.r_settings.x, "⚙ giữa thanh tua và Phím tắt"
click(hud.r_settings.center)
assert hud.show_settings and hud.settings_hits, "bấm ⚙ phải mở bảng"
P = hud.r_settings_panel
W, H = v.size
assert P.x >= 0 and P.y >= 0 and P.right <= W and P.bottom <= hud.r_settings.y, (P, hud.r_settings)
mmr = hud.minimap_rect()
assert mmr is None or not P.colliderect(mmr), ("bản đồ nhỏ (vẽ GPU) đè lên bảng", P, mmr)
acts = [a for _r, a in hud.settings_hits]
for want in (("auto", True), ("persp", None), ("persp", 0), ("persp", 1), ("speed", 0), ("sound", True), ("score",),
             ("minimap",), ("techs",), ("fullscreen",), ("help",)):
    assert want in acts, (want, acts)
v._mouse_motion(SimpleNamespace(pos=btn(lambda a: a == ("speed", 4)), rel=(0, 0), buttons=(0, 0, 0)))
v._settle(3)
v._shot("s1_bang_cai_dat")
print("bấm ⚙: bảng Cài đặt mở, trong màn hình, trên thanh thời gian; đủ", len(acts), "nút: OK")

click(btn(lambda a: a == ("auto", True)))
assert v.auto_cam and hud.show_settings, "bật máy quay tự động, bảng vẫn mở"
click(btn(lambda a: a == ("auto", False)))
assert not v.auto_cam
click(btn(lambda a: a == ("speed", V.SPEEDS.index(4.0))))
assert v.speed() == 4.0
click(btn(lambda a: a == ("persp", 1)))
assert v.persp == 1 and v.persp_pl is None
click(btn(lambda a: a == ("persp", None)))
assert v.persp is None
mm = hud.show_minimap
click(btn(lambda a: a == ("minimap",)))
assert hud.show_minimap != mm
click(btn(lambda a: a == ("minimap",)))
sc = hud.show_score
click(btn(lambda a: a == ("score",)))
assert hud.show_score != sc
click(btn(lambda a: a == ("score",)))
# nút đang bật có viền vàng: trạng thái trong mô hình khớp
m = v._settings_model()
act = {it["act"]: it["active"] for row in m for it in row["items"]}
assert act[("speed", V.SPEEDS.index(4.0))] and act[("persp", None)] and act[("auto", False)]
print("bấm nút: máy quay tự động bật / tắt, tốc độ x4, tầm nhìn đội 2 -> toàn bản đồ, bản đồ nhỏ, bảng chỉ số: OK")

# bấm trong bảng (chỗ trống) không đóng; bấm ngoài đóng và không chọn unit / không kéo bản đồ
click((P.x + 4, P.y + 4))
assert hud.show_settings
sel = v.selected
click((W // 2, H // 3))
assert not hud.show_settings and v.selected == sel and v.drag is None
# Esc đóng bảng trước (không mở bảng phím tắt)
click(hud.r_settings.center)
assert hud.show_settings
v._key(SimpleNamespace(key=pygame.K_ESCAPE, mod=0, unicode=""))
v._settle(2)
assert not hud.show_settings and not hud.show_help
# bấm lại ⚙ khi đang mở: đóng
click(hud.r_settings.center)
click(hud.r_settings.center)
assert not hud.show_settings
# Bảng phím tắt
click(hud.r_settings.center)
click(btn(lambda a: a == ("help",)))
assert hud.show_help and not hud.show_settings
v._shot("s2_bang_phim_tat")
print("bấm trong bảng: giữ; bấm ngoài / Esc / bấm lại ⚙: đóng; Bảng phím tắt: mở bảng Esc: OK")
print("OK test_replay_settings")
