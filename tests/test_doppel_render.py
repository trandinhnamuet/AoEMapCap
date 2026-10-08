"""Kiểm thử bộ vẽ với doppelganger (kind 25) đọc từ game."""
import sys, pickle, copy
sys.path.insert(0, r"D:\Game\AoE-MapCap")
import numpy as np
from PIL import Image
from mapcap import dat as D, drs
from mapcap.render_full import SpriteStore
from mapcap.video_render import VideoRenderer
sp = r"D:\Game\AoE-MapCap\Video\_test"
snap = pickle.load(open(r"D:\Game\AoE-HD\Screenshot\FullMap\2026-09-18_131113_now.snap", "rb"))
pal = drs.load_palette(); dat = D.load(r"D:\Game\AoE-HD\data\empires.dat"); D.parse_units_by_scan(dat)
store = SpriteStore(r"D:\Game\AoE-HD", pal)
def new_vr():
    return VideoRenderer(dat, store, pal, width=1920, log=lambda m: None)
p = snap.cur_player; h, w = snap.terrain.shape; yy, xx = np.mgrid[0:h, 0:w]
tc = next(u for u in snap.units if u.udef.name == "Town_Center1" and u.owner_index == p.index)
# công trình địch thật và doppel của ta về nó, cùng ô
enemy = copy.copy(tc); enemy.uid = 777777; enemy.owner_index = 2; enemy.x, enemy.y = tc.x + 12, tc.y + 2
dop = copy.copy(enemy); dop.uid = -123456; dop.kind = 25
ex, ey = int(enemy.x), int(enemy.y)
def mk(see, real, doppel):
    s = pickle.loads(pickle.dumps(snap))
    s.units = s.units + ([enemy] if real else []) + ([dop] if doppel else [])
    vis = s.vis_raw.copy(); m = ((xx - ex) ** 2 + (yy - ey) ** 2) < 25
    vis[m] |= np.uint32(p.explored_mask | p.visible_mask)
    if not see:
        vis[m] &= ~np.uint32(p.visible_mask)
    s.vis_raw = vis; return s
def px(vr, img):
    s = vr.scale; X = int((enemy.x + enemy.y) * 32 * s); Y = int(((enemy.y - enemy.x) * 16 + vr.Y0_full) * s)
    return int(np.asarray(img)[Y - 12:Y + 4, X - 16:X + 16].sum())
def render(see, real, doppel):
    vr = new_vr(); img = vr.render(mk(see, real, doppel), overlay=False); return px(vr, img), img, vr
fog_empty, _, _ = render(False, False, False)
vis_empty, _, _ = render(True, False, False)
vis_real, _, _ = render(True, True, False)
fog_real, _, _ = render(False, True, False)            # công trình thật trong mù (fog_visible) -> vẽ mờ
fog_dop, img_dop, vr = render(False, False, True)        # chỉ doppel, ô mù -> vẽ mờ
fog_both, _, _ = render(False, True, True)               # cả hai: chỉ vẽ doppel (một lần)
vis_dop, _, _ = render(True, False, True)                # doppel ở ô nhìn thấy -> không vẽ
print(f"đất mù {fog_empty} | đất sáng {vis_empty} | nhà sáng {vis_real} | nhà thật mù {fog_real} | doppel mù {fog_dop} | cả hai mù {fog_both} | doppel ô sáng {vis_dop}")
# công trình có fog_visible = 0 (đọc từ game): trong sương mù game không vẽ vật thể thật, chỉ vẽ doppelganger
assert fog_real == fog_empty, "công trình thật (fog_visible=0) không được vẽ trong sương mù"
assert fog_dop > fog_empty and fog_dop == fog_both, "doppel phải vẽ mờ trong sương mù, và chỉ vẽ một lần khi có cả vật thể thật"
assert vis_dop == vis_empty, "doppel ở ô nhìn thấy không được vẽ"
assert vis_real > vis_empty
# dự phòng mô phỏng: tắt mặc định -> công trình biến mất khi ta không có doppel; bật -> giữ lại
vr2 = new_vr(); vr2.render(mk(True, True, False), overlay=False); a = px(vr2, vr2.render(mk(False, False, False), overlay=False))
vr3 = new_vr(); vr3.emulate_ghosts = True; vr3.render(mk(True, True, False), overlay=False); b = px(vr3, vr3.render(mk(False, False, False), overlay=False))
print(f"không doppel, nhà mất trong mù: mặc định {a} (đất mù {fog_empty}), mô phỏng {b}")
assert a == fog_empty and b == fog_dop
s = vr.scale; X = int((enemy.x + enemy.y) * 32 * s); Y = int(((enemy.y - enemy.x) * 16 + vr.Y0_full) * s)
img_dop.crop((X - 120, Y - 70, X + 120, Y + 50)).resize((1200, 600), Image.NEAREST).save(fr"{sp}\doppel_tc.png")
print("OK")
