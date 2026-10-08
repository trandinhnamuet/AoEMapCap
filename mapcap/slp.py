"""Giải mã SLP (định dạng sprite RLE của engine Genie, phiên bản 2.0N) thành ảnh RGBA numpy.

Mỗi frame trả về (rgba uint8[h, w, 4], hotspot_x, hotspot_y).
Màu quân: pixel "player color" v -> palette[16 * (color_id + 1) + v].
Bóng (shadow) vẽ thành đen bán trong suốt.
"""
import struct

import numpy as np

SHADOW_ALPHA = 110


class SLP:
    def __init__(self, data):
        self.data = data
        self.version = data[:4]
        self.num_frames = struct.unpack_from("<i", data, 4)[0]
        self.frames = []
        for k in range(self.num_frames):
            cmd_off, outline_off, pal_off, props, w, h, hx, hy = struct.unpack_from("<IIIIiiii", data, 32 + 32 * k)
            self.frames.append((cmd_off, outline_off, w, h, hx, hy))
        self._cache = {}

    def frame_size(self, idx):
        _, _, w, h, hx, hy = self.frames[idx]
        return w, h, hx, hy

    def decode(self, idx, palette, color_id=0):
        """Trả về (rgba, hx, hy). palette: list 256 (r,g,b)."""
        key = (idx, color_id)
        if key in self._cache:
            return self._cache[key]
        cmd_off, outline_off, w, h, hx, hy = self.frames[idx]
        pal = np.asarray(palette, dtype=np.uint8)
        img = np.zeros((max(h, 0), max(w, 0), 4), np.uint8)
        d = self.data
        pc_base = 16 * (color_id + 1)
        for row in range(h):
            left, right = struct.unpack_from("<HH", d, outline_off + row * 4)
            if left == 0x8000 or right == 0x8000:
                continue
            p = struct.unpack_from("<I", d, cmd_off + row * 4)[0]
            x = left
            line = img[row]
            while True:
                cmd = d[p]; p += 1
                low = cmd & 0x0F
                if low == 0x0F:                       # end of row
                    break
                if low in (0x00, 0x04, 0x08, 0x0C):    # lesser draw
                    n = cmd >> 2
                    px = np.frombuffer(d, np.uint8, n, p); p += n
                    if x + n <= w:
                        line[x:x + n, :3] = pal[px]; line[x:x + n, 3] = 255
                    x += n
                elif low in (0x01, 0x05, 0x09, 0x0D):  # lesser skip
                    n = cmd >> 2
                    if n == 0:
                        n = d[p]; p += 1
                    x += n
                elif low == 0x02:                      # greater draw
                    n = ((cmd & 0xF0) << 4) + d[p]; p += 1
                    px = np.frombuffer(d, np.uint8, n, p); p += n
                    if x + n <= w:
                        line[x:x + n, :3] = pal[px]; line[x:x + n, 3] = 255
                    x += n
                elif low == 0x03:                      # greater skip
                    n = ((cmd & 0xF0) << 4) + d[p]; p += 1
                    x += n
                elif low == 0x06:                      # player color draw
                    n = cmd >> 4
                    if n == 0:
                        n = d[p]; p += 1
                    px = np.frombuffer(d, np.uint8, n, p).astype(np.int32); p += n
                    idxs = np.clip(px + pc_base, 0, 255)
                    if x + n <= w:
                        line[x:x + n, :3] = pal[idxs]; line[x:x + n, 3] = 255
                    x += n
                elif low == 0x07:                      # fill
                    n = cmd >> 4
                    if n == 0:
                        n = d[p]; p += 1
                    c = d[p]; p += 1
                    if x + n <= w:
                        line[x:x + n, :3] = pal[c]; line[x:x + n, 3] = 255
                    x += n
                elif low == 0x0A:                      # player color fill
                    n = cmd >> 4
                    if n == 0:
                        n = d[p]; p += 1
                    c = min(d[p] + pc_base, 255); p += 1
                    if x + n <= w:
                        line[x:x + n, :3] = pal[c]; line[x:x + n, 3] = 255
                    x += n
                elif low == 0x0B:                      # shadow
                    n = cmd >> 4
                    if n == 0:
                        n = d[p]; p += 1
                    if x + n <= w:
                        seg = line[x:x + n]
                        empty = seg[:, 3] == 0
                        seg[empty, :3] = 0; seg[empty, 3] = SHADOW_ALPHA
                        seg[~empty, :3] = (seg[~empty, :3].astype(np.uint16) * 100 // 255).astype(np.uint8)
                    x += n
                elif low == 0x0E:                      # extended
                    if cmd in (0x4E, 0x5E):            # outline 1 pixel (player color / black)
                        if x < w:
                            line[x, :3] = pal[min(pc_base + 4, 255)] if cmd == 0x4E else 0; line[x, 3] = 255
                        x += 1
                    elif cmd in (0x6E, 0x7E):          # outline span
                        n = d[p]; p += 1
                        if x + n <= w:
                            line[x:x + n, :3] = pal[min(pc_base + 4, 255)] if cmd == 0x6E else 0; line[x:x + n, 3] = 255
                        x += n
                    elif cmd in (0x0E, 0x1E, 0x2E, 0x3E):  # render hints: bỏ qua
                        pass
                    elif cmd in (0x8E, 0x9E, 0xAE, 0xBE):  # dither / premultiplied: bỏ qua an toàn
                        pass
                    else:
                        pass
                else:
                    break
        res = (img, hx, hy)
        self._cache[key] = res
        return res
