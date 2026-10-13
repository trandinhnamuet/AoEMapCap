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
SAME_SOUND_GAP = 0.06       # cùng một id âm thanh không phát lại trong 0,06 s (đỡ chồng tiếng khi đông quân)
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
        self._prev_all = set()       # mọi uid của mẫu trước (nhận ra unit vừa sinh)
        self._prev_all_checked = set()
        self.files = {}
        if pygame is None:
            return
        try:
            from mapcap.gamefiles import read_group
            self.files = read_group(game_dir, "sounds")      # sound.drs (AoE-HD) / data2 + data sounds.drs (AOE1R)
            if not self.files:
                self.log("không thấy sound.drs / sounds.drs của game: tắt âm thanh")
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
        self._prev_all = set()

    # ---- sự kiện từ hoạt ảnh ----------------------------------------------------------------
    @staticmethod
    def _angle_index(g, angle):
        """Hướng của sprite như lúc vẽ (trước khi lật hình); game dùng đúng chỉ số này, vượt số hướng thì về 0."""
        n = max(g.angle_count, 1)
        if n <= 1:
            return 0
        frac = ((angle + 6) % 8) / 8.0 if n == 8 else ((angle / n) if angle < n else 0.0)
        a = int(frac * n) % n
        return a if a < len(g.angle_sounds) else 0

    @staticmethod
    def frame_sounds(g, angle, pf, f):
        """Đúng logic game (hàm 0x4A6C20, gọi khi vẽ sprite 0x4166E0 lúc khung đổi), khung cũ pf -> khung mới f:
        - tiếng chung (sound_id): khung cũ = 0, hoặc quay vòng (f < pf) mà f != 0;
        - tiếng theo hướng: mỗi mục (khung kf, tiếng) phát khi pf <= kf < f; quay vòng thì kf >= pf hoặc kf < f."""
        out = []
        if pf == f:
            return out
        if g.sound_id >= 0 and (pf == 0 or (f < pf and f != 0)):
            out.append(g.sound_id)
        if g.angle_sounds:
            for kf, ks in g.angle_sounds[Audio._angle_index(g, angle)]:
                hit = (pf <= kf < f) if pf < f else (kf >= pf or kf < f)
                if hit and ks >= 0:
                    out.append(ks)
        return out

    def update(self, frame, U, bright, view_rect, active, team_owners=(), dat_units=None, defs=None, all_units=None):
        """U: unit đang vẽ (mảng có gid/frame/angle/uid/x/y/z), bright: độ sáng (1 = đang thấy);
        view_rect: (x0, y0, x1, y1) thế giới đang nhìn; active: đang phát ở tốc độ cho phép nghe;
        team_owners: chủ unit được nghe tiếng "sinh ra" (game chỉ phát cho người đang chơi)."""
        jump = frame - self._prev_frame
        self._prev_frame = frame
        # mọi uid của mẫu trước luôn cập nhật (kể cả khi tua / không nghe) để không nhầm unit cũ là unit mới sinh
        self._prev_all_checked = self._prev_all
        self._prev_all = set(all_units["uid"].tolist()) if all_units is not None and len(all_units) else set()
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
        ay = (y - x) * 16.0 - z * 16.0 + getattr(self, "y0", 0.0)
        vis = np.asarray(bright) >= 1.0
        inside = (np.abs(ax - cx) <= half) & (np.abs(ay - cy) <= hy) & vis & (gid >= 0)
        played = 0
        graphics = self.dat.graphics
        # unit mới sinh ra của người chơi được nghe (tiếng "train sound" của def, game chỉ phát cho người đang chơi)
        A = all_units
        prev_all = self._prev_all_checked
        if team_owners and dat_units is not None and defs is not None and A is not None and len(A) and prev_all:
            new = np.array([u not in prev_all for u in A["uid"].tolist()], bool)
            new &= np.isin(A["owner"], list(team_owners)) & (A["kind"] != 25)
            if new.any():
                di = np.clip(A["def"][new], 0, defs["n"] - 1)
                for dat_id in set(defs["dat_id"][di].tolist()):
                    du = dat_units.get(int(dat_id))
                    if du is not None and du.type == 70 and du.train_sound >= 0 and self.play(du.train_sound, 0.5, 0.8):
                        played += 1
        idx = np.nonzero(inside)[0]
        if len(idx) > 400:                       # quá đông: 400 unit gần tâm
            d = np.abs(ax[idx] - cx) + 2 * np.abs(ay[idx] - cy)
            idx = idx[np.argsort(d)[:400]]
        np.random.shuffle(idx)
        for i in idx.tolist():
            g = graphics.get(int(gid[i]))
            if g is None or (g.sound_id < 0 and not g.angle_sounds):
                continue
            pg, pf = prev.get(int(uid[i]), (-1, -1))
            f = int(fr[i])
            if pg != gid[i]:
                pf = 0                           # sprite mới: game bắt đầu ở khung 0
            sids = self.frame_sounds(g, int(U["angle"][i]), pf, f)
            if not sids:
                continue
            pan = 0.5 + 0.5 * float((ax[i] - cx) / max(half, 1.0))
            dist = abs(float(ax[i] - cx)) / max(half, 1.0) + abs(float(ay[i] - cy)) / max(hy, 1.0)
            for sid in sids:
                if self.play(sid, pan, 1.0 - 0.45 * min(1.0, dist / 2)):
                    played += 1
            if played >= MAX_NEW_PER_TICK:
                break
        return played
