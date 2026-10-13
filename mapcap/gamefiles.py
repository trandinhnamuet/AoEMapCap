"""Tìm file dữ liệu của game trong thư mục cài, cho cả hai cách xếp file đang có:

  AoE-HD (đã gộp)        : data\\graphic.drs, data\\interfac.drs, data\\sound.drs, data\\empires.dat
                           (data2\\graphic.drs, data2\\interfac.drs là file rỗng 64 byte: bỏ qua)
  AOE1R / Rise of Rome gốc: data2\\ = phần Rise of Rome (ưu tiên, như game), data\\ = Age of Empires gốc:
                           graphics.drs + terrain.drs + border.drs, interfac.drs, sounds.drs; empires.dat ở data2\\
                           (data\\empires.dat của AOE1R là bản AoE gốc, không dùng được cho Rise of Rome)

Đối chiếu 2026-10-13 (D:\\Game\\AoE-HD với D:\\Game\\AOE1R): graphic.drs của HD = 4 file đồ hoạ AOE1R gộp lại (764/764 SLP
giống từng byte); 189 âm thanh AOE1R đều có y hệt trong sound.drs của HD; empires.dat: 940/941 đồ hoạ, 363 unit giống;
bảng màu 50500 lệch 9 sắc đỏ/cam (HD chỉnh màu). Nên dùng thư mục nào cũng vẽ được trận của bản kia.
"""
import os

from .drs import read_drs

# chỗ cài quen thuộc (XArena cài cả hai bản cạnh nhau), dò khi file ghi / cấu hình không cho biết thư mục game
GAME_DIR_CANDIDATES = tuple(os.path.join(root, name)
                            for root in (r"C:\Program Files\XArena\Game", r"C:\Program Files (x86)\XArena\Game",
                                         r"D:\XArena\Game", r"D:\Game", r"C:\Game")
                            for name in ("AoE-HD", "AOE1R"))
SUBDIRS = ("data2", "data")                                   # thứ tự ưu tiên như game: phần mở rộng trước
GROUPS = {
    "graphics": ("graphic.drs", "graphics.drs", "terrain.drs", "border.drs"),
    "interface": ("interfac.drs",),
    "sounds": ("sound.drs", "sounds.drs"),
}
_MIN_DRS = 1024                                               # bỏ file DRS rỗng (AoE-HD có data2\\*.drs 64 byte)
_MIN_DAT = 100_000


def _file(game_dir, sub, name):
    p = os.path.join(game_dir, sub, name)
    return p if os.path.isfile(p) else None


def drs_paths(game_dir, group):
    """Các file DRS của nhóm (graphics / interface / sounds), ưu tiên trước."""
    if not game_dir:
        return []
    out = []
    for sub in SUBDIRS:
        for name in GROUPS[group]:
            p = _file(game_dir, sub, name)
            if p and os.path.getsize(p) >= _MIN_DRS:
                out.append(p)
    return out


def read_group(game_dir, group):
    """{(loại, id): bytes} gộp mọi file DRS của nhóm; trùng id thì file ưu tiên hơn thắng."""
    files = {}
    for p in reversed(drs_paths(game_dir, group)):
        files.update(read_drs(p))
    return files


def dat_path(game_dir):
    """empires.dat của Rise of Rome: data2\\ nếu có (AOE1R), không thì data\\ (AoE-HD)."""
    if not game_dir:
        return None
    for sub in SUBDIRS:
        p = _file(game_dir, sub, "empires.dat")
        if p and os.path.getsize(p) >= _MIN_DAT:
            return p
    return None


def valid_game_dir(d):
    """Thư mục game vẽ được replay: có empires.dat, đồ hoạ và giao diện (kiểu AoE-HD hoặc AOE1R)."""
    try:
        return bool(d) and dat_path(d) is not None and bool(drs_paths(d, "graphics")) and \
            bool(drs_paths(d, "interface"))
    except OSError:
        return False


def layout_name(d):
    if _file(d, "data", "graphic.drs"):
        return "AoE-HD"
    return "Rise of Rome (data + data2)"
