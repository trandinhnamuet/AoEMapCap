"""Vòng lặp chính: theo dõi đồng hồ game và lưu ảnh toàn bản đồ tại các mốc phút.

Cách dùng (chạy trong thư mục D:\\Game\\AoE-MapCap):
    python -m mapcap.main                 # mốc 5, 10, 15, ... phút
    python -m mapcap.main --interval 2    # mỗi 2 phút game
    python -m mapcap.main --now           # chụp ngay một ảnh rồi thoát (để kiểm tra)
    python -m mapcap.main --tile 24       # ô to hơn (ảnh lớn hơn)
"""
import argparse
import datetime as dt
import os
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
import time

from . import drs
from . import dat as D
from .game import GameReader
from .memory import ProcessMemory, MemoryError_, find_game_process
from .render import Renderer
from .render_full import FullRenderer, SpriteStore

DEFAULT_OUT = r"D:\Game\AoE-HD\Screenshot\FullMap"


def log(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def capture(reader, renderer, out_dir, label, with_units=True, save_snap=False):
    t0 = time.time()
    snap = reader.snapshot(with_units=with_units)
    if with_units:
        known = {u.uid for u in snap.units}
        snap.units.extend(reader.scan_tile_units(snap, known_uids=known))
    os.makedirs(out_dir, exist_ok=True)
    stem = f"{dt.datetime.now():%Y-%m-%d_%H%M%S}_{label}"
    if save_snap:
        import pickle
        with open(os.path.join(out_dir, stem + ".snap"), "wb") as f:
            pickle.dump(snap, f)
    img = renderer.render(snap)
    elapsed = time.time() - t0
    path = os.path.join(out_dir, stem + ".png")
    img.save(path)
    cur = snap.cur_player
    log(f"đã lưu {path}  (game {snap.time_str()}, {snap.map_w}x{snap.map_h}, "
        f"{len(snap.units)} đối tượng, góc nhìn {cur.name if cur else '?'}, {elapsed:.1f}s)")
    return snap, path


def wait_for_game():
    shown = False
    while True:
        p = find_game_process()
        if p is not None:
            return p
        if not shown:
            log("chưa thấy game chạy (EMPIRESX*.EXE / empires.exe), đang chờ...")
            shown = True
        time.sleep(2)


def run(args):
    palette = drs.load_palette(args.game_dir)
    if args.mode == "mini":
        renderer = Renderer(palette, tile_w=args.tile, elevation=not args.flat, show_units=not args.no_units,
                            fog_dim=args.fog_dim)
    else:
        t0 = time.time()
        dat = D.load(os.path.join(args.game_dir, "data", "empires.dat"))
        D.parse_units_by_scan(dat)
        store = SpriteStore(args.game_dir, palette)
        renderer = FullRenderer(dat, store, palette, scale=args.scale, fog_dim=args.fog_dim,
                                default_angle=args.angle, use_tile_offsets=not args.no_tile_offsets, log=log)
        log(f"đã nạp dữ liệu đồ hoạ ({len(dat.graphics)} graphics, {len(dat.units)} unit) trong {time.time() - t0:.1f}s")
    interval_ms = int(args.interval * 60_000)

    while True:
        proc = wait_for_game()
        log(f"thấy game: {proc.info['name']} (pid {proc.pid})")
        try:
            mem = ProcessMemory(proc.pid)
        except MemoryError_ as e:
            log(str(e))
            time.sleep(5)
            continue
        reader = GameReader(mem)
        game_no = 0
        last_mark = -1
        last_time = None
        in_game_prev = False
        with mem:
            while mem.alive():
                try:
                    in_game = reader.in_game()
                    t = reader.game_time_ms() if in_game else None
                except MemoryError_:
                    in_game, t = False, None

                if in_game and not in_game_prev:
                    game_no += 1
                    last_mark = -1
                    log(f"vào trận #{game_no}")
                if in_game_prev and not in_game:
                    log("rời trận")
                in_game_prev = in_game

                if in_game and t is not None:
                    if last_time is not None and t + 60_000 < last_time:
                        # đồng hồ quay lại: ván mới
                        game_no += 1
                        last_mark = -1
                        log(f"đồng hồ game reset, coi là trận #{game_no}")
                    last_time = t
                    if args.now:
                        capture(reader, renderer, args.out, "now", save_snap=args.save_snap)
                        return 0
                    mark = t // interval_ms
                    if mark >= 1 and mark > last_mark:
                        # chỉ chụp mốc hiện tại (bỏ qua mốc đã trôi qua nếu tool bật muộn)
                        last_mark = mark
                        minutes = int(mark * args.interval)
                        try:
                            capture(reader, renderer, args.out, f"tran{game_no}_{minutes:02d}p", save_snap=args.save_snap)
                        except MemoryError_ as e:
                            log(f"lỗi đọc bộ nhớ khi chụp: {e}")
                elif args.now:
                    log("game đang chạy nhưng chưa vào trận, chờ...")
                time.sleep(1.0)
        log("game đã thoát")
        if args.now:
            return 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="AoE-MapCap: tự chụp toàn bản đồ theo mốc phút game")
    ap.add_argument("--interval", type=float, default=5.0, help="khoảng cách mốc (phút game), mặc định 5")
    ap.add_argument("--out", default=DEFAULT_OUT, help="thư mục lưu ảnh")
    ap.add_argument("--game-dir", default=drs.DEFAULT_GAME_DIR, help="thư mục game (để lấy palette)")
    ap.add_argument("--mode", choices=("full", "mini"), default="full",
                    help="full = sprite thật của game (mặc định); mini = kiểu minimap phóng to")
    ap.add_argument("--scale", type=float, default=0.5, help="tỉ lệ thu ảnh ở chế độ full (1 = kích cỡ gốc 64px/ô), mặc định 0.5")
    ap.add_argument("--angle", type=int, default=0, help="hướng đứng mặc định của unit 0..7 (chế độ full)")
    ap.add_argument("--no-tile-offsets", action="store_true", help="không dùng toạ độ vẽ ô do game tính (chế độ full)")
    ap.add_argument("--tile", type=int, default=16, help="chế độ mini: bề ngang một ô (px), mặc định 16")
    ap.add_argument("--flat", action="store_true", help="không dịch ô theo độ cao")
    ap.add_argument("--no-units", action="store_true", help="chỉ vẽ địa hình")
    ap.add_argument("--fog-dim", type=float, default=0.43, help="độ sáng vùng ngoài tầm nhìn 0..1 (1 = không làm tối); game dùng ~0.43")
    ap.add_argument("--now", action="store_true", help="chụp ngay một ảnh rồi thoát")
    ap.add_argument("--save-snap", action="store_true", help="lưu thêm file .snap (dữ liệu thô) để vẽ lại sau bằng render_snap.py")
    args = ap.parse_args(argv)
    try:
        return run(args) or 0
    except KeyboardInterrupt:
        log("dừng.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
