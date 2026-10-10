"""Âm thanh khi xem replay: phát lại âm thanh của game theo hoạt ảnh các unit trong khung nhìn.

Không cần dữ liệu ghi thêm: mỗi mẫu đã có đồ hoạ (gid) và khung (frame) game đang vẽ cho từng unit; empires.dat cho
biết đồ hoạ nào có âm thanh:
  - `sound_id`: phát mỗi khi hoạt ảnh bắt đầu / lặp lại (chết, nổ, công trình sập, ...)
  - `angle_sounds`: theo hướng, phát khi hoạt ảnh chạy qua khung chỉ định (đòn đánh, bắn tên, chặt cây, đào mỏ...)
Âm thanh là các WAV trong data\\sound.drs; mỗi id âm thanh có vài biến thể chọn ngẫu nhiên theo xác suất.
Chỉ nghe unit trong khung nhìn (và đang thấy theo tầm nhìn đang chọn), âm lượng/trái-phải theo vị trí trên màn hình.
Máy không có thiết bị âm thanh: tự tắt, không ảnh hưởng phần còn lại.
"""
import io
import os
import random
import time

import numpy as np

try:
    import pygame
except Exception:  # noqa: BLE001
    pygame = None

MAX_NEW_PER_TICK = 6        # tối đa số âm thanh mới mỗi lần cập nhật
SAME_SOUND_GAP = 0.12       # cùng một id âm thanh không phát lại trong 0,12 s (đỡ chồng tiếng khi đông quân)
MAX_JUMP_FRAMES = 6         # nhảy quá 6 mẫu (tua, tốc độ cao) thì không phát, chỉ cập nhật trạng thái
HEAR_WIDTH = 3600.0         # chỉ nghe trong vùng rộng tối đa 3600 px thế giới quanh tâm màn hình (khi zoom xa)


class Audio:
    def __init__(self, dat, game_dir, log=None):
        self.log = log or (lambda m: None)
        self.ok = False
        self.enabled = True
        self.volume = 0.7
        self.dat = dat
        self._cache = {}
        self._last = {}
        self._prev = {}              # uid -> (gid, frame)
        self._prev_frame = -1
        self.files = {}
        if pygame is None:
            return
        try:
            from mapcap.drs import read_drs
            p = os.path.join(game_dir, "data", "sound.drs")
            self.files = read_drs(p) if os.path.exists(p) else {}
            if not self.files:
                self.log("không thấy data\\sound.drs: tắt âm thanh")
                return
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=1024)
            pygame.mixer.set_num_channels(24)
            self.ok = True
        except Exception as e:  # noqa: BLE001
            self.log(f"không khởi tạo được âm thanh ({e}): tắt âm thanh")
            self.ok = False

    # ---- tài nguyên ---------------------------------------------------------------------
    def _sound(self, res):
        s = self._cache.get(res)
        if s is None:
            data = self.files.get(("wav", res))
            s = False
            if data:
                try:
                    s = pygame.mixer.Sound(file=io.BytesIO(data))
                except Exception:  # noqa: BLE001
                    s = False
            self._cache[res] = s
        return s or None

    def _pick(self, sound_id):
        items = self.dat.sounds.get(sound_id) if hasattr(self.dat, "sounds") else None
        if not items:
            return None
        avail = [(res, max(1, prob)) for _fn, res, prob in items if ("wav", res) in self.files]
        if not avail:
            return None
        r = random.uniform(0, sum(p for _r, p in avail))
        for res, p in avail:
            r -= p
            if r <= 0:
                return res
        return avail[-1][0]

    def play(self, sound_id, pan=0.5, vol=1.0):
        if not (self.ok and self.enabled):
            return False
        now = time.time()
        if now - self._last.get(sound_id, 0.0) < SAME_SOUND_GAP:
            return False
        res = self._pick(sound_id)
        snd = self._sound(res) if res is not None else None
        if snd is None:
            return False
        ch = pygame.mixer.find_channel()
        if ch is None:
            return False
        v = max(0.0, min(1.0, vol * self.volume))
        pan = max(0.0, min(1.0, pan))
        ch.set_volume(v * min(1.0, 2 * (1 - pan)), v * min(1.0, 2 * pan))
        ch.play(snd)
        self._last[sound_id] = now
        return True

    def toggle(self):
        self.enabled = not self.enabled
        if not self.enabled and self.ok:
            pygame.mixer.stop()
        return self.enabled

    def reset(self):
        """Sau khi tua: quên trạng thái hoạt ảnh (không phát tiếng cho bước nhảy)."""
        self._prev = {}
        self._prev_frame = -1

    # ---- sự kiện từ hoạt ảnh ----------------------------------------------------------------
    def _angle_index(self, g, angle):
        n = max(g.angle_count, 1)
        if n == 8:
            a = (angle + 6) % 8
        else:
            a = angle if angle < n else 0
        if g.mirroring_mode and n > 1 and a > n // 2:
            a = n - a
        return a

    def update(self, frame, U, bright, view_rect, active):
        """U: unit đang vẽ (mảng có gid/frame/angle/uid/x/y/z), bright: độ sáng (1 = đang thấy);
        view_rect: (x0, y0, x1, y1) thế giới đang nhìn; active: đang phát ở tốc độ cho phép nghe."""
        jump = frame - self._prev_frame
        self._prev_frame = frame
        if U is None or not len(U):
            self._prev = {}
            return 0
        uid = U["uid"]
        gid = U["gid"].astype(np.int32)
        fr = U["frame"].astype(np.int32)
        prev = self._prev
        self._prev = dict(zip(uid.tolist(), zip(gid.tolist(), fr.tolist())))
        if not (self.ok and self.enabled and active) or not (0 < jump <= MAX_JUMP_FRAMES) or not prev:
            return 0
        x0, y0, x1, y1 = view_rect
        cx = (x0 + x1) / 2
        half = min((x1 - x0) / 2, HEAR_WIDTH / 2)
        hy = min((y1 - y0) / 2, HEAR_WIDTH / 4)
        cy = (y0 + y1) / 2
        x, y, z = U["x"].astype(np.float32), U["y"].astype(np.float32), U["z"].astype(np.float32)
        ax = (x + y) * 32.0
        ay = (y - x) * 16.0 - z * 16.0          # bỏ Y0: chỉ so tương đối, cộng lại dưới đây
        ay = ay + getattr(self, "y0", 0.0)
        inside = (np.abs(ax - cx) <= half) & (np.abs(ay - cy) <= hy) & (np.asarray(bright) >= 1.0) & (gid >= 0)
        played = 0
        graphics = self.dat.graphics
        idx = np.nonzero(inside)[0]
        if len(idx) > 400:                       # quá đông: lấy ngẫu nhiên 400 unit gần tâm
            d = np.abs(ax[idx] - cx) + 2 * np.abs(ay[idx] - cy)
            idx = idx[np.argsort(d)[:400]]
        np.random.shuffle(idx)
        for i in idx.tolist():
            g = graphics.get(int(gid[i]))
            if g is None or (g.sound_id < 0 and not g.angle_sounds):
                continue
            pg, pf = prev.get(int(uid[i]), (-1, -1))
            f = int(fr[i])
            sid = -1
            if g.angle_sounds:
                lst = g.angle_sounds[min(self._angle_index(g, int(U["angle"][i])), len(g.angle_sounds) - 1)]
                for kf, ks in lst:
                    if pg != gid[i]:
                        hit = pf < 0 and f >= kf and f - kf <= 2 or (pg >= 0 and f >= kf and f - kf <= 2)
                    elif f >= pf:
                        hit = pf < kf <= f
                    else:                        # lặp lại vòng hoạt ảnh
                        hit = kf > pf or kf <= f
                    if hit:
                        sid = ks
                        break
            if sid < 0 and g.sound_id >= 0:
                if pg != gid[i] or f < pf:
                    sid = g.sound_id
            if sid < 0:
                continue
            pan = 0.5 + 0.5 * float((ax[i] - cx) / max(half, 1.0))
            dist = abs(float(ax[i] - cx)) / max(half, 1.0) + abs(float(ay[i] - cy)) / max(hy, 1.0)
            if self.play(sid, pan, 1.0 - 0.45 * min(1.0, dist / 2)):
                played += 1
                if played >= MAX_NEW_PER_TICK:
                    break
        return played
