"""Vẽ Snapshot thành ảnh toàn bản đồ (kiểu minimap phóng to, dạng thoi isometric)."""
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import offsets as O
from .game import Snapshot

FOG_DIM = 0.65          # hệ số sáng của vùng đã khám phá nhưng ngoài tầm nhìn (1.0 = giống minimap game)
UNEXPLORED = (0, 0, 0)


def _font(size):
    for name in ("segoeui.ttf", "arial.ttf", "tahoma.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


class Renderer:
    def __init__(self, palette, tile_w=16, elevation=True, show_units=True, legend=True, fog_dim=FOG_DIM):
        self.pal = palette
        self.fog_dim = fog_dim
        self.tile_w = max(4, int(tile_w) // 2 * 2)
        self.tile_h = self.tile_w // 2
        self.elevation = elevation
        self.show_units = show_units
        self.legend = legend

    # toạ độ ô -> pixel tâm ô. Ngang ~ (x + y), dọc ~ (y - x): khớp cách vẽ diam_map của game.
    def tile_center(self, x, y, elev, w, h):
        cx = (x + y) * self.tile_w / 2 + self.tile_w / 2
        cy = (y - x + (w - 1)) * self.tile_h / 2 + self.tile_h / 2 + self.top_pad
        if self.elevation:
            cy -= elev * self.tile_h / 2
        return cx, cy

    def render(self, snap: Snapshot) -> Image.Image:
        w, h = snap.map_w, snap.map_h
        self.top_pad = (int(snap.elevation.max()) * self.tile_h // 2 + 2) if self.elevation else 2
        img_w = int((w + h) * self.tile_w / 2) + 2
        img_h = int((w + h) * self.tile_h / 2) + self.top_pad + 2
        img = Image.new("RGB", (img_w, img_h), UNEXPLORED)
        draw = ImageDraw.Draw(img)

        explored = snap.explored()
        visible = snap.visible()
        pal = self.pal
        hw, hh = self.tile_w / 2, self.tile_h / 2

        # địa hình: vẽ từ trên màn hình xuống (theo y - x tăng) để ô phía trước che ô phía sau.
        # Ô có độ cao được kéo "váy" xuống tới mặt đất để không hở khe đen giữa các bậc.
        order = sorted(((y - x, x + y, x, y) for y in range(h) for x in range(w)))
        for _, _, x, y in order:
            if not explored[y, x]:
                continue
            t = int(snap.terrain[y, x])
            ci = O.SHAPE_TO_COLOR_INDEX.get(int(snap.shape[y, x]), 1)
            col = pal[snap.terrain_colors[t][ci]]
            if not visible[y, x]:
                col = tuple(int(c * self.fog_dim) for c in col)
            elev = int(snap.elevation[y, x])
            cx, cy = self.tile_center(x, y, elev, w, h)
            drop = elev * hh if self.elevation else 0
            if drop:
                side = tuple(int(c * 0.8) for c in col)
                draw.polygon([(cx - hw, cy), (cx, cy + hh), (cx + hw, cy),
                              (cx + hw, cy + drop), (cx, cy + hh + drop), (cx - hw, cy + drop)], fill=side)
            draw.polygon([(cx, cy - hh), (cx + hw, cy), (cx, cy + hh), (cx - hw, cy)], fill=col)

        if self.show_units:
            self._draw_units(draw, snap, explored, visible)

        if self.legend:
            img = self._add_legend(img, snap)
        return img

    def _unit_color(self, snap, u):
        d = u.udef
        if d.mm_mode == 3:
            return self.pal[d.mm_color]
        pl = snap.players[u.owner_index] if u.owner_index < len(snap.players) else None
        if pl is None or u.owner_index == 0:
            # Gaia: game truyền màu 0xFF (không có trong palette) -> vẽ trắng
            return self.pal[d.mm_color] if d.mm_color else (255, 255, 255)
        return self.pal[pl.mm_color]

    def _draw_units(self, draw, snap, explored, visible):
        w, h = snap.map_w, snap.map_h
        small = max(2, self.tile_w // 5)
        big = max(3, self.tile_w // 2)
        # công trình vẽ trước, unit sống vẽ sau để nổi lên trên
        def prio(u):
            return 0 if u.udef.utype == O.UNIT_TYPE_BUILDING else (1 if u.udef.utype != O.UNIT_TYPE_LIVING else 2)
        for u in sorted(snap.units, key=prio):
            d = u.udef
            if d.mm_mode == 0:
                continue
            tx, ty = int(u.x), int(u.y)
            if not (0 <= tx < w and 0 <= ty < h):
                continue
            if not visible[ty, tx]:
                if not (explored[ty, tx] and d.fog_visible):
                    continue
            elev = int(snap.elevation[ty, tx])
            cx, cy = self.tile_center(u.x - 0.5, u.y - 0.5, elev, w, h)
            col = self._unit_color(snap, u)
            r = big if d.utype == O.UNIT_TYPE_BUILDING else small
            if d.utype == O.UNIT_TYPE_BUILDING:
                draw.rectangle([cx - r, cy - r / 2, cx + r, cy + r / 2], fill=col, outline=(0, 0, 0))
            elif d.utype == O.UNIT_TYPE_LIVING:
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col, outline=(0, 0, 0))
            else:
                draw.rectangle([cx - r, cy - r, cx + r, cy + r], fill=col)

    def _add_legend(self, img, snap):
        font = _font(max(12, self.tile_w))
        line_h = font.size + 6
        rows = 1 + sum(1 for p in snap.players if p.index != 0)
        pad = 8
        legend_h = rows * line_h + pad * 2
        out = Image.new("RGB", (img.width, img.height + legend_h), (24, 24, 24))
        out.paste(img, (0, legend_h))
        d = ImageDraw.Draw(out)
        cur = snap.cur_player
        title = f"Thời gian game {snap.time_str()}   bản đồ {snap.map_w}x{snap.map_h}   " \
                f"góc nhìn: {cur.name if cur else '?'}   tốc độ x{snap.speed:.1f}"
        d.text((pad, pad), title, fill=(240, 240, 240), font=font)
        y = pad + line_h
        for p in snap.players:
            if p.index == 0:
                continue
            col = self.pal[p.mm_color]
            d.rectangle([pad, y + 3, pad + font.size, y + 3 + font.size], fill=col, outline=(255, 255, 255))
            d.text((pad * 2 + font.size, y), f"{p.name}  ({p.unit_count} đối tượng)", fill=(230, 230, 230), font=font)
            y += line_h
        return out
