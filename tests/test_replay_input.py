"""Kiểm tra phím tắt và chuột của trình xem replay bằng sự kiện giả lập (cửa sổ ẩn, không đụng chuột/phím thật).

    python tests/test_replay_input.py file.aoerec
"""
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pygame  # noqa: E402

from replay import viewer as V  # noqa: E402


def key(v, k, mod=0, uni=""):
    v._key(pygame.event.Event(pygame.KEYDOWN, key=k, mod=mod, unicode=uni))
    v._tick(1 / 60, True)


def click(v, pos, button=1, move_to=None):
    v._mouse_down(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=button))
    if move_to is not None:
        rel = (move_to[0] - pos[0], move_to[1] - pos[1])
        v._mouse_motion(pygame.event.Event(pygame.MOUSEMOTION, pos=move_to, rel=rel, buttons=(1, 0, 0)))
        pos = move_to
    v._mouse_up(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=button))
    v._tick(1 / 60, True)


def main():
    path = sys.argv[1]
    v = V.Viewer(path, None, lambda m: None, selftest=os.path.join(ROOT, "Video", "_test"))
    v._init_window()
    v.data.start_index()
    v._load_world()
    while not v.data.done:
        time.sleep(0.1)
    v._tick(0.0, False)
    d = v.data
    for _ in range(3):
        v._tick(1 / 60, True)
    v.playing = False
    v.seek_r(d.duration() * 0.5)
    v._tick(1 / 60, True)

    # phát / tạm dừng, tốc độ
    key(v, pygame.K_p); assert v.playing
    key(v, pygame.K_p); assert not v.playing
    key(v, pygame.K_EQUALS); key(v, pygame.K_EQUALS); assert v.speed() == 4.0, v.speed()
    key(v, pygame.K_MINUS); assert v.speed() == 2.0
    key(v, pygame.K_0); assert v.speed() == 1.0
    for _ in range(5):
        key(v, pygame.K_MINUS)
    assert v.speed() == 0.25
    key(v, pygame.K_0)
    # lùi / tiến 15 giây giờ game
    t0 = d.f_t[v.cursor.frame]
    key(v, pygame.K_BACKSPACE)
    t1 = d.f_t[v.cursor.frame]
    assert 14000 <= t0 - t1 <= 16500, (t0, t1)
    key(v, pygame.K_j)
    t2 = d.f_t[v.cursor.frame]
    assert abs(t2 - t0) <= 1500, (t0, t2)
    # tầm nhìn
    key(v, pygame.K_F1); assert v.persp == 0
    if len(d.teams) > 1:
        key(v, pygame.K_F2); assert v.persp == 1
    key(v, pygame.K_F3); assert v.persp is None
    key(v, pygame.K_f); assert v.persp == v.last_team
    key(v, pygame.K_f); assert v.persp is None
    seen = set()
    for _ in range(len(d.teams) + 1):
        key(v, pygame.K_v)
        seen.add(v.persp)
    assert seen == set([None] + list(range(len(d.teams)))), seen
    key(v, pygame.K_F3)
    # chọn người chơi, Space về nhà chính
    k0 = next(iter(v._key_sel))
    key(v, k0); assert v.selected == v._key_sel[k0]
    for _ in range(60):
        v._tick(1 / 60, True)
    home = v.player_home(v.selected)
    v.cx, v.cy = 0, 0
    key(v, pygame.K_SPACE)
    for _ in range(90):
        v._tick(1 / 60, True)
    assert abs(v.cx - home[0]) < 5 and abs(v.cy - home[1]) < 5, (v.cx, v.cy, home)
    # HUD
    h = v.hud
    for k, attr in ((pygame.K_o, "show_score"), (pygame.K_u, "show_timeline"), (pygame.K_c, "show_techs"),
                    (pygame.K_m, "show_minimap"), (pygame.K_h, "show_hud")):
        before = getattr(h, attr)
        key(v, k); assert getattr(h, attr) != before, attr
        key(v, k); assert getattr(h, attr) == before, attr
    m0 = h.score_mode
    key(v, pygame.K_x); assert h.score_mode != m0
    key(v, pygame.K_SLASH, pygame.KMOD_SHIFT, "?"); assert h.show_help
    key(v, pygame.K_ESCAPE); assert not h.show_help
    key(v, pygame.K_ESCAPE); assert h.show_help            # Esc bật bảng phím tắt
    key(v, pygame.K_ESCAPE); assert not h.show_help
    # zoom quanh con trỏ: điểm dưới con trỏ giữ nguyên
    key(v, pygame.K_HOME)
    for _ in range(60):
        v._tick(1 / 60, True)
    sx, sy = 700, 400
    w0 = v.screen_to_world(sx, sy)
    v.zoom_at(V.ZOOM_STEP ** 3, sx, sy)
    for _ in range(90):
        v._tick(1 / 60, True)
    w1 = v.screen_to_world(sx, sy)
    assert abs(w0[0] - w1[0]) < 2 and abs(w0[1] - w1[1]) < 2, (w0, w1)
    assert abs(v.zoom - v.zoom_target) < 1e-3
    # kéo chuột di chuyển máy quay
    cx0 = v.cx
    click(v, (800, 400), move_to=(900, 400))
    assert abs((cx0 - v.cx) - 100 / v.zoom) < 1.0, (cx0, v.cx)
    # cuộn bằng mép màn hình (giả lập vị trí chuột)
    real_pos, real_focus = pygame.mouse.get_pos, pygame.mouse.get_focused
    pygame.mouse.get_pos = lambda: (v.size[0] - 1, 300)
    pygame.mouse.get_focused = lambda: True
    cx0 = v.cx
    for _ in range(30):
        v._tick(1 / 60, True)
    pygame.mouse.get_pos, pygame.mouse.get_focused = real_pos, real_focus
    assert v.cx - cx0 > 300 / v.zoom, (cx0, v.cx)
    # thanh thời gian: bấm giữa thanh -> giữa trận
    v.hud.show_hud = True
    v.hud.show_timeline = True
    v._on_resize()
    v._hud_dirty = True
    v._tick(1 / 60, True)
    bar = v.hud.r_timeline
    click(v, (bar.x + bar.w // 4, bar.centery))
    assert abs(v.r / d.duration() - 0.25) < 0.02, v.r / d.duration()
    # nút "Phím tắt (Esc)" trên thanh thời gian, bấm chuột bất kì đâu thì đóng
    click(v, v.hud.r_help.center); assert v.hud.show_help
    click(v, (600, 300)); assert not v.hud.show_help
    # nút phát
    pb = v.hud.r_play
    click(v, pb.center); assert v.playing
    click(v, pb.center); assert not v.playing
    # minimap: bấm -> máy quay tới điểm đó
    mm = v.hud.minimap_rect()
    click(v, mm.center)
    w = v.world
    assert abs(v.cx - w.full_w / 2) < w.full_w * 0.01 and abs(v.cy - w.full_h / 2) < w.full_h * 0.02, (v.cx, v.cy)
    # bấm vào unit -> bảng thông tin
    v.zoom = v.zoom_target = 1.0
    home = v.player_home(v.selected)
    v.cx, v.cy = home
    v._tick(1 / 60, True)
    v._built_version = -1
    v._tick(1 / 60, True)
    slot, x0, y0, ui = v.inst
    atl = v.gpu.atlas
    tlx, tly = v.cam_tl()
    picked = None
    for j in range(len(slot) - 1, -1, -1):
        if slot[j] < 0:
            continue
        ww, hh = atl.size[slot[j]]
        sx, sy = (x0[j] + ww / 2 - tlx) * v.zoom, (y0[j] + hh / 2 - tly) * v.zoom
        if 50 < sx < v.size[0] - 50 and 150 < sy < v.size[1] - 400:
            click(v, (int(sx), int(sy)))
            if v.sel_unit is not None:
                picked = v.sel_unit
                break
    assert picked is not None, "không chọn được unit nào"
    info = v._unit_info()
    print("chọn unit:", info["name"], "-", info["owner"], info["lines"])
    v.fit_view()                                          # bấm chỗ trống (ngoài bản đồ) -> đóng bảng unit
    for _ in range(60):
        v._tick(1 / 60, True)
    click(v, (40, 140)); assert v.sel_unit is None
    # chuột giữa -> xem cả bản đồ
    click(v, (500, 300), button=2)
    for _ in range(60):
        v._tick(1 / 60, True)
    assert abs(v.zoom - v.fit_zoom()) < 1e-3
    # cửa sổ có API toàn màn hình
    win = pygame.Window.from_display_module()
    assert hasattr(win, "set_fullscreen") and hasattr(win, "set_windowed")
    v._shot("8_sau_test_phim")
    v.data.close()
    pygame.quit()
    print("OK")


if __name__ == "__main__":
    main()
