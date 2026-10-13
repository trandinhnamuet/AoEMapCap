"""Đọc file DRS của game để lấy palette 256 màu (interfac.drs, id 50500)."""
import os
import struct

DEFAULT_GAME_DIR = r"D:\Game\AoE-HD"
MAIN_PALETTE_ID = 50500


def read_drs(path):
    b = open(path, "rb").read()
    ntables, _first = struct.unpack_from("<ii", b, 56)
    files = {}
    for t in range(ntables):
        o = 64 + t * 12
        ext = b[o + 1:o + 4][::-1].decode("latin1")
        toff, nfiles = struct.unpack_from("<ii", b, o + 4)
        for k in range(nfiles):
            fid, foff, fsize = struct.unpack_from("<iii", b, toff + k * 12)
            files[(ext, fid)] = b[foff:foff + fsize]
    return files


def parse_jasc_pal(data):
    lines = data.decode("latin1").splitlines()
    assert lines[0].strip() == "JASC-PAL", "không phải palette JASC"
    n = int(lines[2].strip())
    pal = []
    for ln in lines[3:3 + n]:
        r, g, bl = (int(x) for x in ln.split()[:3])
        pal.append((r, g, bl))
    while len(pal) < 256:
        pal.append((0, 0, 0))
    return pal


def load_palette(game_dir=DEFAULT_GAME_DIR, pal_id=MAIN_PALETTE_ID):
    from .gamefiles import read_group                 # interfac.drs: data2\ rồi data\ (AoE-HD hoặc AOE1R)
    files = read_group(game_dir, "interface")
    if ("bin", pal_id) not in files:
        raise FileNotFoundError(f"không thấy bảng màu {pal_id} trong interfac.drs của {game_dir}")
    return parse_jasc_pal(files[("bin", pal_id)])
