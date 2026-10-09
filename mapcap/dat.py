"""Đọc empires.dat (Rise of Rome, "VER 3.7"): màu quân, đồ hoạ (graphics), địa hình, viền, unit.

Bố cục theo định dạng Genie thế hệ 1 (tham chiếu bộ chuyển đổi openage cho ROR), đã đối chiếu
bằng tên chuỗi trong file thật của bản AoE-HD.
"""
import re
import struct
import zlib
from dataclasses import dataclass, field


class Reader:
    def __init__(self, data):
        self.d = data
        self.p = 0

    def i8(self):  v = struct.unpack_from("<b", self.d, self.p)[0]; self.p += 1; return v
    def u8(self):  v = self.d[self.p]; self.p += 1; return v
    def i16(self): v = struct.unpack_from("<h", self.d, self.p)[0]; self.p += 2; return v
    def u16(self): v = struct.unpack_from("<H", self.d, self.p)[0]; self.p += 2; return v
    def i32(self): v = struct.unpack_from("<i", self.d, self.p)[0]; self.p += 4; return v
    def f32(self): v = struct.unpack_from("<f", self.d, self.p)[0]; self.p += 4; return v
    def skip(self, n): self.p += n
    def chars(self, n):
        s = self.d[self.p:self.p + n]; self.p += n
        return s.split(b"\0")[0].decode("latin1")
    def arr(self, fmt, n):
        v = struct.unpack_from(f"<{n}{fmt}", self.d, self.p); self.p += struct.calcsize(f"<{n}{fmt}"); return list(v)


@dataclass
class PlayerColour:
    id: int
    name: str
    minimap_color: int
    type: int


@dataclass
class GraphicDelta:
    graphic_id: int
    offset_x: int
    offset_y: int
    display_angle: int


@dataclass
class Graphic:
    id: int
    name: str
    filename: str
    slp_id: int
    layer: int
    player_color: int
    replay: int
    coords: list
    frame_count: int
    angle_count: int
    mirroring_mode: int
    sequence_type: int
    deltas: list = field(default_factory=list)


@dataclass
class ElevationGraphic:
    frame_count: int
    angle_count: int
    shape_id: int


@dataclass
class Terrain:
    id: int
    enabled: int
    name: str
    name2: str
    slp_id: int
    minimap_colors: tuple
    is_animated: int
    animation_frames: int
    elevation_graphics: list
    terrain_replacement_id: int
    terrain_to_draw: int
    dims: tuple
    borders: list


@dataclass
class TerrainBorder:
    id: int
    enabled: int
    name: str
    slp_id: int
    frames: list          # 19 x 12 (frame_count, angle_count, shape_id)
    draw_tile: int
    underlay_terrain: int
    border_style: int


@dataclass
class UnitDef:
    id: int
    type: int
    name: str
    class_id: int
    standing_graphic: int
    dying_graphic: int
    radius_x: float
    radius_y: float
    dead_unit_id: int
    icon_id: int
    lang_name: int = -1      # id chuỗi tên trong language.dll


@dataclass
class Research:
    id: int
    name: str
    lang_name: int
    time: int               # giây nghiên cứu
    location: int           # DAT id công trình nghiên cứu (-1 = không nghiên cứu được)
    rtype: int
    icon: int
    costs: list             # [(loại tài nguyên, số lượng)]
    required: list          # id công nghệ cần trước

    @property
    def researchable(self):
        return self.location >= 0 and self.time > 0 and self.lang_name != 0


@dataclass
class DatFile:
    version: str
    player_colours: list
    graphics: dict          # id -> Graphic
    terrains: list
    borders: list
    tile_sizes: list
    units: dict             # dat id -> UnitDef (từ nền văn minh 0 = Gaia, đủ mọi unit)
    civ_units: dict         # civ index -> {id: UnitDef}
    research: list = field(default_factory=list)     # index = id công nghệ (parse_research)
    civ_names: list = field(default_factory=list)    # index = civ id (0 = Gaia)


def load(path):
    raw = open(path, "rb").read()
    data = zlib.decompress(raw, -15)
    return parse(data)


def parse(d):
    r = Reader(d)
    version = r.chars(8)
    tr_count = r.i16()
    terrain_count = r.i16()
    r.skip(4 * tr_count)                    # terrain restriction pointers
    for _ in range(tr_count):
        r.skip(4 * terrain_count)           # passability floats

    # ---- màu quân
    n = r.i16()
    colours = []
    for _ in range(n):
        name = r.chars(30)
        cid = r.i32()
        mm = r.u8()
        typ = r.u8()
        colours.append(PlayerColour(cid, name, mm, typ))

    # ---- âm thanh (bỏ nội dung)
    n = r.i16()
    for _ in range(n):
        r.i32()                             # id
        items = r.i16()
        r.i32()                             # cache time
        for _ in range(items):
            r.chars(13); r.i32(); r.i16()   # filename, resource id, probability

    # ---- đồ hoạ
    n = r.i16()
    ptrs = r.arr("i", n)
    graphics = {}
    for gid, ptr in enumerate(ptrs):
        if not ptr:
            continue
        name = r.chars(21)
        filename = r.chars(13)
        slp_id = r.i32()
        r.i8()                              # is_loaded
        r.i8()                              # old_color_flag
        layer = r.i8()
        player_color = r.i16()
        replay = r.i8()
        coords = r.arr("h", 4)
        delta_count = r.i16()
        sound_id = r.i16()
        attack_sound_used = r.i8()
        frame_count = r.i16()
        angle_count = r.i16()
        r.f32()                             # speed_adjust
        r.f32()                             # frame_rate
        r.f32()                             # replay_delay
        sequence_type = r.i8()
        id_ = r.i16()
        mirroring_mode = r.i8()
        g = Graphic(gid, name, filename, slp_id, layer, player_color, replay, coords,
                    frame_count, angle_count, mirroring_mode, sequence_type)
        for _ in range(delta_count):
            dg = r.i16(); r.i16(); r.i32()
            ox = r.i16(); oy = r.i16(); da = r.i16(); r.i16()
            g.deltas.append(GraphicDelta(dg, ox, oy, da))
        if attack_sound_used:
            r.skip(angle_count * 12)
        graphics[gid] = g

    # ---- khối địa hình
    r.i32()                                 # map pointer
    r.i32()                                 # unknown
    r.i32(); r.i32()                        # map width/height
    r.i32(); r.i32()                        # world width/height
    tile_sizes = [tuple(r.arr("h", 3)) for _ in range(19)]
    r.i16()                                 # padding
    terrains = []
    for tid in range(32):
        b = r.p
        enabled = d[b]
        name = d[b + 2:b + 15].split(b"\0")[0].decode("latin1")
        name2 = d[b + 15:b + 28].split(b"\0")[0].decode("latin1")
        slp_id = struct.unpack_from("<i", d, b + 28)[0]
        colors = tuple(d[b + 40:b + 45])
        is_animated = d[b + 47]
        animation_frames = struct.unpack_from("<h", d, b + 48)[0]
        elev = [ElevationGraphic(*struct.unpack_from("<hhh", d, b + 0x46 + 6 * k)) for k in range(17)]
        replacement = struct.unpack_from("<h", d, b + 0xac)[0]
        to_draw = struct.unpack_from("<h", d, b + 0xb8)[0]
        dims = tuple(struct.unpack_from("<hh", d, b + 0xba))
        borders = list(struct.unpack_from("<32h", d, b + 0xbe))
        terrains.append(Terrain(tid, enabled, name, name2, slp_id, colors, is_animated, animation_frames,
                                elev, replacement, to_draw, dims, borders))
        r.p = b + 0x198
    borders_ = []
    for bid in range(16):
        b = r.p
        enabled = d[b]
        name = d[b + 2:b + 15].split(b"\0")[0].decode("latin1")
        slp_id = struct.unpack_from("<i", d, b + 28)[0]
        frames = [[tuple(struct.unpack_from("<hhh", d, b + 66 + (sh * 12 + di) * 6)) for di in range(12)] for sh in range(19)]
        draw_tile, underlay, style = struct.unpack_from("<hhh", d, b + 66 + 19 * 12 * 6)
        borders_.append(TerrainBorder(bid, enabled, name, slp_id, frames, draw_tile, underlay, style))
        r.p = b + 0x5a0
    # phần còn lại của khối địa hình
    r.i32()                                 # map row/col offsets ptr... (ROR: several ints)
    r.skip(4 * 2)                           # map min/max x/y
    r.skip(4 * 4 + 2 * 3)                   # unknowns (đủ dùng; unit đọc bằng resync dưới)
    dat = DatFile(version, colours, graphics, terrains, borders_, tile_sizes, {}, {})
    dat._reader_pos = r.p
    dat._data = d
    return dat


def parse_units_by_scan(dat):
    """Quét bảng unit của mọi nền văn minh theo chữ ký bản ghi (không cần bố cục phần riêng từng loại).

    Bản ghi unit (phần chung) dài 144 + 5*n byte (n = số đồ hoạ hư hại), sau đó là tên (name_len byte,
    kết thúc \0) rồi id2 == id1. Trả về dict dat_id -> UnitDef của lần xuất hiện đầu (nền văn minh 0);
    dat.civ_units[civ] giữ bảng riêng từng nền văn minh.
    """
    d = dat._data
    units, civ_units = {}, {}
    types = {10, 20, 25, 30, 40, 60, 70, 80, 90}
    p = dat._reader_pos
    civ_idx = -1
    last_id = -1
    n_bytes = len(d)
    while p < n_bytes - 160:
        typ = d[p]
        if typ in types:
            nlen = d[p + 1] | (d[p + 2] << 8)
            if 2 <= nlen <= 40:
                ndmg = d[p + 137]
                if ndmg <= 6:
                    name_at = p + 144 + 5 * ndmg
                    name = d[name_at:name_at + nlen]
                    if len(name) == nlen and name[-1] == 0 and all(32 <= c < 127 for c in name[:-1]):
                        id1 = struct.unpack_from("<h", d, p + 3)[0]
                        id2 = struct.unpack_from("<h", d, name_at + nlen)[0]
                        if id1 == id2 and 0 <= id1 < 5000:
                            (lang_name, lang_create, cls, standing, dying, undead) = struct.unpack_from("<6h", d, p + 5)
                            rx, ry, rz = struct.unpack_from("<fff", d, p + 25)
                            dead_unit, = struct.unpack_from("<h", d, p + 39)
                            icon, = struct.unpack_from("<h", d, p + 43)
                            if id1 < last_id:
                                civ_idx += 1
                            elif civ_idx < 0:
                                civ_idx = 0
                            last_id = id1
                            u = UnitDef(id1, typ, name[:-1].decode("latin1"), cls, standing, dying, rx, ry, dead_unit, icon, lang_name)
                            civ_units.setdefault(civ_idx, {})[id1] = u
                            units.setdefault(id1, u)
                            p = name_at + nlen + 2
                            continue
        p += 1
    dat.units = units
    dat.civ_units = civ_units
    parse_research(dat)
    parse_civ_names(dat)
    return units


RESEARCH_FIXED = 52     # required[4] i16, 3 x (type i16, amount i16, flag u8), reqn i16, location i16, lang name/desc u16,
                        # time i16, effect i16, type i16, icon i16, button i8, help i32, tech tree i32, hotkey i32


def parse_research(dat):
    """Bảng công nghệ nằm cuối empires.dat (RoR: 127 mục). Tìm mục 'Tool Age' rồi lùi về đầu bảng."""
    d = dat._data

    def rec(q):
        if q + RESEARCH_FIXED + 2 > len(d):
            return None
        nl = struct.unpack_from("<H", d, q + RESEARCH_FIXED)[0]
        if nl > 40:
            return None
        nm = d[q + RESEARCH_FIXED + 2:q + RESEARCH_FIXED + 2 + nl]
        if nl and (len(nm) != nl or nm[-1] != 0 or not all(32 <= c < 127 for c in nm[:-1])):
            return None
        return nl, (nm[:-1].decode("latin1") if nl else "")

    def parse_from(s, maxn=600):
        q = s
        out = []
        while len(out) < maxn:
            r = rec(q)
            if r is None:
                break
            out.append((q, r[1]))
            q += RESEARCH_FIXED + 2 + r[0]
        return out, q

    hits = [m.start() for m in re.finditer(re.escape(b"Tool Age\x00"), d)]
    if not hits:
        return []
    tool = max(hits) - 2 - RESEARCH_FIXED
    start = None
    for s in range(tool - 40000, tool + 1):
        recs, _ = parse_from(s)
        if any(q == tool for q, _ in recs):
            start = s
            break
    if start is None:
        return []
    recs, _ = parse_from(start)
    out = []
    for i, (q, name) in enumerate(recs):
        req = [x for x in struct.unpack_from("<4h", d, q) if x >= 0]
        costs = [(t, a) for t, a, _f in (struct.unpack_from("<hhB", d, q + 8 + 5 * k) for k in range(3)) if t >= 0]
        _reqn, loc, ln, _ld, t, _eff, typ, icon = struct.unpack_from("<hhHHhhhh", d, q + 23)
        out.append(Research(i, name, ln, t, loc, typ, icon, costs, req))
    dat.research = out
    return out


def parse_civ_names(dat):
    """Tên nền văn minh: các khối civ cách đều nhau; khối 0 là Gaia (tên rỗng)."""
    d = dat._data
    e = d.find(b"Egyptian\x00")
    g = d.find(b"Greek\x00")
    if e < 0 or g < 0 or g <= e:
        return []
    stride = g - e
    names = ["Gaia"]
    for i in range(16):
        q = e + i * stride
        nm = d[q:q + 20].split(b"\x00")[0].decode("latin1")
        if not nm or not all(32 <= ord(c) < 127 for c in nm):
            break
        names.append(nm)
    dat.civ_names = names
    return names
