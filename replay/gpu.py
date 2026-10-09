"""Vẽ bằng OpenGL 3.3 (moderngl).

- Địa hình: một texture (mipmap) phủ cả thế giới; sương mù tính theo pixel: bản đồ chỉ số ô (uint16) -> độ sáng ô.
- Sprite (vật thể tĩnh, unit): atlas là texture mảng 2048x2048 (mipmap), mỗi mảnh một instance, vẽ theo thứ tự sâu.
  Vật thể tĩnh dùng sương mù theo pixel (giống lớp tĩnh của video), unit dùng độ sáng riêng (đang thấy / ghi nhớ).
- Màu đã nhân alpha (pixel trong suốt = 0) nên lọc mipmap không viền đen; trộn ONE, ONE_MINUS_SRC_ALPHA.
"""
import numpy as np
import moderngl

_COMMON = """
#version 330
uniform vec2 cam;        // góc trên trái của khung nhìn (toạ độ thế giới)
uniform float zoom;      // pixel màn hình / pixel thế giới
uniform vec2 view;       // kích thước vùng vẽ (px)
vec4 to_clip(vec2 w) {
    vec2 s = (w - cam) * zoom;
    return vec4(s.x / view.x * 2.0 - 1.0, 1.0 - s.y / view.y * 2.0, 0.0, 1.0);
}
"""

_FOG = """
uniform usampler2D idxmap;   // chỉ số ô của từng pixel ảnh địa hình
uniform sampler2D fogtex;    // độ sáng từng ô (map_w x map_h)
uniform float ts;            // tỉ lệ ảnh địa hình / thế giới
uniform int map_w;
uniform int n_tiles;
float fog_at(vec2 w) {
    ivec2 sz = textureSize(idxmap, 0);
    ivec2 p = clamp(ivec2(floor(w * ts)), ivec2(0), sz - 1);
    int id = int(texelFetch(idxmap, p, 0).r);
    if (id >= n_tiles) return 0.0;
    return texelFetch(fogtex, ivec2(id % map_w, id / map_w), 0).r;
}
"""

TERRAIN_VS = _COMMON + """
in vec2 in_pos;
out vec2 v_world;
void main() { v_world = in_pos; gl_Position = to_clip(in_pos); }
"""

TERRAIN_FS = "#version 330\n" + _FOG + """
uniform sampler2D terrain;
uniform vec2 tex_size;
in vec2 v_world;
out vec4 f_color;
void main() {
    vec3 c = texture(terrain, v_world * ts / tex_size).rgb;
    f_color = vec4(c * fog_at(v_world), 1.0);
}
"""

SPRITE_VS = _COMMON + """
in vec2 in_corner;
in vec2 i_pos;
in vec2 i_size;
in vec4 i_uv;
in float i_layer;
in float i_bright;
out vec2 v_uv;
out vec2 v_world;
flat out float v_layer;
flat out float v_bright;
void main() {
    vec2 w = i_pos + in_corner * i_size;
    v_world = w;
    v_uv = mix(i_uv.xy, i_uv.zw, in_corner);
    v_layer = i_layer;
    v_bright = i_bright;
    gl_Position = to_clip(w);
}
"""

SPRITE_FS = "#version 330\n" + _FOG + """
uniform sampler2DArray atlas;
in vec2 v_uv;
in vec2 v_world;
flat in float v_layer;
flat in float v_bright;
out vec4 f_color;
void main() {
    vec4 c = texture(atlas, vec3(v_uv, v_layer));
    if (c.a < 0.004) discard;
    float b = v_bright < 0.0 ? fog_at(v_world) : v_bright;
    f_color = vec4(c.rgb * b, c.a);
}
"""

DOT_VS = _COMMON + """
in vec2 in_corner;
in vec2 i_center;
in float i_half;
in vec4 i_color;
out vec4 v_color;
void main() {
    vec4 p = to_clip(i_center);
    vec2 d = (in_corner * 2.0 - 1.0) * i_half;
    p.xy += vec2(d.x / view.x * 2.0, -d.y / view.y * 2.0);
    v_color = i_color;
    gl_Position = p;
}
"""

DOT_FS = """
#version 330
in vec4 v_color;
out vec4 f_color;
void main() { f_color = vec4(v_color.rgb * v_color.a, v_color.a); }
"""

LINE_VS = _COMMON + """
in vec2 in_pos;
void main() { gl_Position = to_clip(in_pos); }
"""

LINE_FS = """
#version 330
uniform vec4 color;
out vec4 f_color;
void main() { f_color = vec4(color.rgb * color.a, color.a); }
"""

HUD_VS = """
#version 330
in vec2 in_corner;
out vec2 v_uv;
void main() { v_uv = in_corner; gl_Position = vec4(in_corner.x * 2.0 - 1.0, 1.0 - in_corner.y * 2.0, 0.0, 1.0); }
"""

HUD_FS = """
#version 330
uniform sampler2D hud;
in vec2 v_uv;
out vec4 f_color;
void main() { vec4 c = texture(hud, v_uv); f_color = vec4(c.rgb * c.a, c.a); }
"""

PAGE = 2048
ALIGN = 8           # ô atlas canh 8 px và chừa 8 px trống: mipmap tới mức 3 không lẫn sang ô bên cạnh
MIP_LEVELS = 3
MAX_LAYERS = 8      # tối đa 8 lớp 2048x2048 (128 MB + mipmap); đầy thì dồn lại, chỉ giữ sprite đang dùng


class Atlas:
    """Atlas sprite trên GPU, đưa lên theo nhu cầu (ensure); đầy thì thêm lớp, tới MAX_LAYERS thì dồn lại."""

    def __init__(self, ctx, layers=MAX_LAYERS):
        self.ctx = ctx
        self.tex = None
        self.cap = 0
        self.uv = np.zeros((0, 4), np.float32)
        self.lay = np.zeros(0, np.float32)
        self.size = np.zeros((0, 2), np.float32)
        self.placed = np.zeros(0, bool)
        self.pos = np.zeros((0, 3), np.int32)
        self.last_used = np.zeros(0, np.int64)
        self.tick = 0
        self.generation = 0          # tăng khi vị trí sprite cũ đổi (dồn lại) -> các lô phải dựng lại uv
        self.dirty = False
        self.pinned = np.zeros(0, np.int64)   # slot của lớp vật thể tĩnh: luôn giữ khi dồn
        self._make(layers)

    def _make(self, layers):
        if self.tex is not None:
            self.tex.release()
        # nền trong suốt bắt buộc (khe giữa các ô atlas phải = 0 để mipmap không lẫn màu)
        self.tex = self.ctx.texture_array((PAGE, PAGE, layers), 4, bytes(PAGE * PAGE * 4 * layers))
        self.tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.NEAREST)
        self.layers = layers
        self._shelf = [0, 0, 0, 0]   # layer, x, y, chiều cao hàng

    def _grow_cap(self, n):
        if n <= self.cap:
            return
        cap = max(n, self.cap * 2, 1024)
        for name, shape, dt in (("uv", (cap, 4), np.float32), ("lay", (cap,), np.float32), ("size", (cap, 2), np.float32),
                                ("placed", (cap,), bool), ("pos", (cap, 3), np.int32), ("last_used", (cap,), np.int64)):
            old = getattr(self, name)
            new = np.zeros(shape, dt)
            new[:len(old)] = old
            setattr(self, name, new)
        self.cap = cap

    def _alloc(self, w, h):
        cw = (w + ALIGN + ALIGN - 1) // ALIGN * ALIGN
        ch = (h + ALIGN + ALIGN - 1) // ALIGN * ALIGN
        if cw > PAGE or ch > PAGE:
            return False
        lay, x, y, rh = self._shelf
        if x + cw > PAGE:
            x, y, rh = 0, y + rh, 0
        if y + ch > PAGE:
            lay, x, y, rh = lay + 1, 0, 0, 0
        if lay >= self.layers:
            return None
        self._shelf = [lay, x + cw, y, max(rh, ch)]
        return lay, x, y

    def _place(self, world, slots):
        """Xếp và đưa lên các slot; trả về danh sách slot không còn chỗ."""
        left = []
        for s in slots:
            w, h = world.slot_w[s], world.slot_h[s]
            r = self._alloc(w, h)
            if r is False:
                continue                         # sprite lớn hơn trang atlas: bỏ
            if r is None:
                left.append(s)
                continue
            lay, x, y = r
            data, _w, _h = world.slot_image(s)
            self.tex.write(data, viewport=(x, y, lay, w, h, 1))
            self.placed[s] = True
            self.pos[s] = (lay, x, y)
            self.uv[s] = (x / PAGE, y / PAGE, (x + w) / PAGE, (y + h) / PAGE)
            self.lay[s] = lay
            self.size[s] = (w, h)
        if slots:
            self.dirty = True
        return left

    def ensure(self, world, slots):
        """Bảo đảm các slot (mảng, có thể chứa -1) đã nằm trên GPU."""
        self._grow_cap(len(world.slot_keys))
        self.tick += 1
        u = np.unique(slots[slots >= 0]) if len(slots) else np.zeros(0, np.int64)
        if len(u) == 0:
            return
        self.last_used[u] = self.tick
        need = u[~self.placed[u]].tolist()
        if not need:
            return
        need.sort(key=lambda s: -world.slot_h[s])
        left = self._place(world, need)
        while left:
            if self.layers < MAX_LAYERS:
                # thêm lớp: tạo texture mới, giữ nguyên vị trí cũ, đưa lại toàn bộ
                old = np.nonzero(self.placed[:len(world.slot_keys)])[0].tolist()
                shelf = self._shelf
                self._make(min(MAX_LAYERS, self.layers * 2))
                self._shelf = shelf
                for s in old:
                    lay, x, y = self.pos[s]
                    data, w, h = world.slot_image(s)
                    self.tex.write(data, viewport=(int(x), int(y), int(lay), w, h, 1))
                left = self._place(world, left)
            else:
                # dồn lại: chỉ giữ slot vừa dùng ở lần này + lớp tĩnh, xếp lại từ đầu
                keep = set(u.tolist()) | set(self.pinned.tolist())
                keep = sorted(keep, key=lambda s: -world.slot_h[s])
                self.placed[:] = False
                self.size[:] = 0
                self._make(self.layers)
                self.generation += 1
                left = self._place(world, keep)
                if left:
                    break                         # tập đang dùng lớn hơn cả atlas: bỏ phần thừa

    def finish(self):
        if self.dirty:
            self.tex.build_mipmaps(0, MIP_LEVELS)
            self.dirty = False


class SpriteBatch:
    """Lô instance sprite (một VBO), dựng từ (slot, x0, y0, bright)."""

    def __init__(self, ctx, prog, corner_vbo):
        self.ctx, self.prog = ctx, prog
        self.corner = corner_vbo
        self.vbo = ctx.buffer(reserve=40 * 1024, dynamic=True)
        self.vao = None
        self.count = 0
        self.cap = 1024
        self.last = None
        self.gen = -1

    def set(self, atlas, slot, x0, y0, bright):
        self.last = (slot, x0, y0, bright)
        self.gen = atlas.generation
        ok = slot >= 0
        if not ok.all():
            slot, x0, y0, bright = slot[ok], x0[ok], y0[ok], bright[ok]
        n = len(slot)
        inst = np.empty((n, 10), np.float32)
        if n:
            inst[:, 0] = x0
            inst[:, 1] = y0
            inst[:, 2:4] = atlas.size[slot]
            inst[:, 4:8] = atlas.uv[slot]
            inst[:, 8] = atlas.lay[slot]
            inst[:, 9] = bright
        if n > self.cap or self.vao is None:
            self.cap = max(n, self.cap * 2)
            self.vbo.orphan(self.cap * 40)
            if self.vao is not None:
                self.vao.release()
            self.vao = self.ctx.vertex_array(self.prog, [
                (self.corner, "2f", "in_corner"),
                (self.vbo, "2f 2f 4f 1f 1f/i", "i_pos", "i_size", "i_uv", "i_layer", "i_bright"),
            ])
        if n:
            self.vbo.write(inst.tobytes())
        self.count = n

    def draw(self):
        if self.count and self.vao is not None:
            self.vao.render(moderngl.TRIANGLE_STRIP, vertices=4, instances=self.count)


class GPU:
    def __init__(self, ctx: moderngl.Context):
        self.ctx = ctx
        self.p_terrain = ctx.program(vertex_shader=TERRAIN_VS, fragment_shader=TERRAIN_FS)
        self.p_sprite = ctx.program(vertex_shader=SPRITE_VS, fragment_shader=SPRITE_FS)
        self.p_dot = ctx.program(vertex_shader=DOT_VS, fragment_shader=DOT_FS)
        self.p_line = ctx.program(vertex_shader=LINE_VS, fragment_shader=LINE_FS)
        self.p_hud = ctx.program(vertex_shader=HUD_VS, fragment_shader=HUD_FS)
        self.corner = ctx.buffer(np.array([0, 0, 1, 0, 0, 1, 1, 1], np.float32).tobytes())
        self.hud_vao = ctx.vertex_array(self.p_hud, [(self.corner, "2f", "in_corner")])
        self.atlas = Atlas(ctx)
        self.statics = SpriteBatch(ctx, self.p_sprite, self.corner)
        self.units = SpriteBatch(ctx, self.p_sprite, self.corner)
        self.dot_vbo = ctx.buffer(reserve=28 * 256, dynamic=True)
        self.dot_cap = 256
        self.dot_vao = None
        self.dot_count = 0
        self.line_vbo = ctx.buffer(reserve=8 * 64, dynamic=True)
        self.line_vao = ctx.vertex_array(self.p_line, [(self.line_vbo, "2f", "in_pos")])
        self.terrain_tex = None
        self.idx_tex = None
        self.fog_tex = None
        self.terrain_vao = None
        self.hud_tex = None
        self.world = None

    # ---- tải thế giới ------------------------------------------------------------------
    def load_world(self, world):
        ctx = self.ctx
        self.world = world
        th, tw = world.terrain.shape[:2]
        self.terrain_tex = ctx.texture((tw, th), 3, np.ascontiguousarray(world.terrain).tobytes(), alignment=1)
        self.terrain_tex.build_mipmaps()
        self.terrain_tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        try:
            self.terrain_tex.anisotropy = 4.0
        except Exception:  # noqa: BLE001
            pass
        self.idx_tex = ctx.texture((tw, th), 1, np.ascontiguousarray(world.index).tobytes(), dtype="u2", alignment=2)
        self.idx_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        self.fog_tex = ctx.texture((world.map_w, world.map_h), 1, dtype="f1", alignment=1)
        self.fog_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        W, H = world.full_w, world.full_h
        quad = np.array([0, 0, W, 0, 0, H, W, H], np.float32)
        self.terrain_vbo = ctx.buffer(quad.tobytes())
        self.terrain_vao = ctx.vertex_array(self.p_terrain, [(self.terrain_vbo, "2f", "in_pos")])
        self.outline = np.array(world.outline(), np.float32)
        for p in (self.p_terrain, self.p_sprite):
            p["idxmap"].value = 1
            p["fogtex"].value = 2
            p["ts"].value = world.ts
            p["map_w"].value = world.map_w
            p["n_tiles"].value = world.map_w * world.map_h
        self.p_terrain["terrain"].value = 0
        self.p_terrain["tex_size"].value = (tw, th)
        self.p_sprite["atlas"].value = 3
        # bản đồ chỉ số và ảnh địa hình đã nằm trên GPU: giải phóng bản CPU (~100–200 MB)
        world.terrain = None
        world.index = None

    def set_fog(self, bright_u8):
        self.fog_tex.write(np.ascontiguousarray(bright_u8, np.uint8).tobytes())

    def _refresh_batches(self):
        for b in (self.statics, self.units):
            if b.last is not None and b.gen != self.atlas.generation:
                self.atlas.ensure(self.world, b.last[0])
                b.set(self.atlas, *b.last)

    def set_statics(self, slot, x0, y0, bright):
        self.atlas.pinned = np.unique(slot[slot >= 0]) if len(slot) else np.zeros(0, np.int64)
        self.atlas.ensure(self.world, slot)
        self.statics.set(self.atlas, slot, x0, y0, bright)
        self._refresh_batches()

    def set_units(self, slot, x0, y0, bright):
        self.atlas.ensure(self.world, slot)
        self.units.set(self.atlas, slot, x0, y0, bright)
        self._refresh_batches()

    def set_dots(self, centers, halves, colors):
        n = len(centers)
        data = np.empty((n, 7), np.float32)
        if n:
            data[:, 0:2] = centers
            data[:, 2] = halves
            data[:, 3:7] = colors
        if n > self.dot_cap or self.dot_vao is None:
            self.dot_cap = max(n, self.dot_cap * 2)
            self.dot_vbo.orphan(self.dot_cap * 28)
            if self.dot_vao is not None:
                self.dot_vao.release()
            self.dot_vao = self.ctx.vertex_array(self.p_dot, [
                (self.corner, "2f", "in_corner"),
                (self.dot_vbo, "2f 1f 4f/i", "i_center", "i_half", "i_color")])
        if n:
            self.dot_vbo.write(data.tobytes())
        self.dot_count = n

    # ---- vẽ ----------------------------------------------------------------------------------
    def _cam(self, cam, zoom, view):
        for p in (self.p_terrain, self.p_sprite, self.p_dot, self.p_line):
            p["cam"].value = (float(cam[0]), float(cam[1]))
            p["zoom"].value = float(zoom)
            p["view"].value = (float(view[0]), float(view[1]))

    def _bind(self, zoom):
        # phóng to quá 1:1 giữ nét pixel; ảnh địa hình đã giảm một nửa (map lớn) thì nội suy cho đỡ vỡ ô
        crisp = zoom >= 1.0 and self.world.ts >= 1.0
        self.terrain_tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.NEAREST if crisp else moderngl.LINEAR)
        self.terrain_tex.use(0)
        self.idx_tex.use(1)
        self.fog_tex.use(2)
        self.atlas.tex.use(3)

    def draw_world(self, cam, zoom, view, outline_alpha=0.35, statics=True, units=True):
        ctx = self.ctx
        self.atlas.finish()
        self._cam(cam, zoom, view)
        self._bind(zoom)
        ctx.disable(moderngl.BLEND)
        self.terrain_vao.render(moderngl.TRIANGLE_STRIP)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
        if statics:
            self.statics.draw()
        if units:
            self.units.draw()
        if outline_alpha > 0:
            self.draw_lines(self.outline, (outline_alpha, outline_alpha, outline_alpha, 1.0), loop=True)

    def draw_dots(self):
        if self.dot_count and self.dot_vao is not None:
            self.ctx.enable(moderngl.BLEND)
            self.ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
            self.dot_vao.render(moderngl.TRIANGLE_STRIP, vertices=4, instances=self.dot_count)

    def draw_lines(self, pts, color, loop=False):
        pts = np.asarray(pts, np.float32)
        self.line_vbo.orphan(max(pts.nbytes, 8))
        self.line_vbo.write(pts.tobytes())
        self.p_line["color"].value = tuple(float(c) for c in color)
        self.ctx.enable(moderngl.BLEND)
        self.ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
        self.line_vao.render(moderngl.LINE_LOOP if loop else moderngl.LINE_STRIP, vertices=len(pts))

    def set_cam(self, cam, zoom, view):
        self._cam(cam, zoom, view)

    def draw_hud(self, surf_bytes, size, changed):
        w, h = size
        if self.hud_tex is None or self.hud_tex.size != (w, h):
            if self.hud_tex is not None:
                self.hud_tex.release()
            self.hud_tex = self.ctx.texture((w, h), 4)
            self.hud_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            changed = True
        if changed and surf_bytes is not None:
            self.hud_tex.write(surf_bytes)
        self.hud_tex.use(4)
        self.p_hud["hud"].value = 4
        self.ctx.enable(moderngl.BLEND)
        self.ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
        self.hud_vao.render(moderngl.TRIANGLE_STRIP)
