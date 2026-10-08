"""AoE-MapCap Recorder: chạy nền, tự ghi video diễn biến từng trận và chụp ảnh ở mốc phút.

Cấu hình đọc từ mapcap.ini cạnh file exe (tự tạo nếu chưa có).
"""
import configparser
import datetime as dt
import os
import sys
import threading
import time

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import psutil

from . import dat as D
from . import drs
from .game import GameReader
from .memory import ProcessMemory, MemoryError_, find_game_process
from .recorder import MatchRecorder, find_ffmpeg, pick_encoder, recover_partials
from .render_full import FullRenderer, SpriteStore
from .video_render import VideoRenderer

DEFAULT_INI = """[mapcap]
; Thư mục game (chứa data\\empires.dat, data\\graphic.drs)
game_dir = D:\\Game\\AoE-HD
; Thư mục lưu video và ảnh
out_dir = D:\\Game\\AoE-HD\\Screenshot\\FullMap
; Bề ngang video (px). 1920 = Full HD. Chiều cao tự tính theo bản đồ.
video_width = 1920
; Số khung ghi mỗi giây thật (1..10). 4 là cân bằng.
fps = 4
; Tốc độ phát lại: 1 = thời gian thật, 8 = tua nhanh 8 lần
speed = 1
; Độ sáng vùng ngoài tầm nhìn (game dùng 0.43)
fog_dim = 0.43
; Ghi video: 1 bật, 0 tắt
record_video = 1
; Chụp ảnh tĩnh chi tiết mỗi N phút game (0 = tắt)
stills_interval = 5
; Tỉ lệ ảnh tĩnh (1 = kích cỡ gốc 64 px/ô, 0.5 = một nửa)
stills_scale = 0.5
; Coi là hết trận khi đồng hồ game đứng yên quá N giây (pause dài cũng tính)
frozen_end_seconds = 180
; Mã hoá: auto / h264_nvenc / h264_qsv / h264_amf / libx264
encoder = auto
; Quét lại cây rừng, đá... gắn với ô đất mỗi N giây (chúng không nằm trong danh sách người chơi)
static_rescan_seconds = 10
; Viền trắng mờ quanh ranh giới bản đồ trong video: 0 = tắt, 0.35 = mờ, 1 = trắng đậm
map_outline = 0.35
"""


_LOG_FILE = None


def log(msg):
    line = f"[{dt.datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    global _LOG_FILE
    try:
        if _LOG_FILE is None:
            _LOG_FILE = open(os.path.join(app_dir(), "mapcap.log"), "a", encoding="utf-8")
        _LOG_FILE.write(line + os.linesep)
        _LOG_FILE.flush()
    except Exception:  # noqa: BLE001
        pass


def app_dir():
    return os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__)))


def load_config():
    path = os.path.join(app_dir(), "mapcap.ini")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(DEFAULT_INI)
        log(f"đã tạo cấu hình mặc định {path}")
    cp = configparser.ConfigParser()
    cp.read(path, encoding="utf-8")
    s = cp["mapcap"]
    cfg = dict(
        game_dir=s.get("game_dir", r"D:\Game\AoE-HD"),
        out_dir=s.get("out_dir", r"D:\Game\AoE-HD\Screenshot\FullMap"),
        video_width=max(320, s.getint("video_width", 1920)),
        fps=min(10.0, max(0.5, s.getfloat("fps", 4))),
        speed=max(0.1, s.getfloat("speed", 1)),
        fog_dim=min(1.0, max(0.0, s.getfloat("fog_dim", 0.43))),
        record_video=s.getboolean("record_video", True),
        stills_interval=max(0.0, s.getfloat("stills_interval", 5)),
        stills_scale=min(1.0, max(0.1, s.getfloat("stills_scale", 0.5))),
        frozen_end_seconds=max(30, s.getint("frozen_end_seconds", 180)),
        encoder=s.get("encoder", "auto"),
        static_rescan_seconds=max(2.0, s.getfloat("static_rescan_seconds", 10)),
        map_outline=min(1.0, max(0.0, s.getfloat("map_outline", 0.35))),
    )
    return cfg, path


def lower_priority():
    try:
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass


class StaticObjects:
    """Vật thể gắn với ô đất (cây rừng, mỏ...) không có trong danh sách người chơi; quét ở luồng riêng."""

    def __init__(self, reader, rescan_seconds):
        self.reader = reader
        self.rescan_seconds = rescan_seconds
        self.units = []
        self.version = 0
        self.last_scan = 0.0
        self.busy = False
        self.lock = threading.Lock()

    def reset(self):
        with self.lock:
            self.units = []
            self.version += 1
        self.last_scan = 0.0

    def maybe_rescan(self, snap):
        if self.busy or time.time() - self.last_scan < self.rescan_seconds:
            return
        self.busy = True
        known = {u.uid for u in snap.units}
        threading.Thread(target=self._scan, args=(snap, known), daemon=True).start()

    def _scan(self, snap, known):
        try:
            t0 = time.time()
            units = self.reader.scan_tile_units(snap, known_uids=known)
            with self.lock:
                changed = len(units) != len(self.units) or {u.uid for u in units} != {u.uid for u in self.units}
                self.units = units
                if changed:
                    self.version += 1
            if self.last_scan == 0.0:
                log(f"quét vật thể theo ô: {len(units)} vật thể tĩnh ({time.time() - t0:.2f}s)")
            self.last_scan = time.time()
        except Exception as e:  # noqa: BLE001
            log(f"lỗi quét vật thể theo ô: {e}")
            self.last_scan = time.time()
        finally:
            self.busy = False

    def merge(self, snap):
        """Ảnh tĩnh: gộp vào snap.units (vẽ chung, đúng thứ tự sâu)."""
        known = {u.uid for u in snap.units}
        with self.lock:
            extra = [u for u in self.units if u.uid not in known]
        snap.units.extend(extra)
        return len(extra)

    def attach(self, snap):
        """Video: gắn thành lớp riêng, bộ vẽ chỉ dựng lại khi danh sách đổi (tiết kiệm ~4000 sprite/khung)."""
        with self.lock:
            snap.static_units = list(self.units)
            snap.static_version = self.version


class StillsWorker:
    """Chụp ảnh tĩnh chi tiết trong luồng riêng để không chặn nhịp video."""

    def __init__(self, renderer, out_dir):
        self.renderer = renderer
        self.out_dir = out_dir
        self.busy = False

    def submit(self, snap, label):
        if self.busy:
            log("bỏ qua ảnh tĩnh: lần trước chưa xong")
            return
        self.busy = True
        threading.Thread(target=self._run, args=(snap, label), daemon=True).start()

    def _run(self, snap, label):
        try:
            t0 = time.time()
            img = self.renderer.render(snap)
            os.makedirs(self.out_dir, exist_ok=True)
            path = os.path.join(self.out_dir, f"{dt.datetime.now():%Y-%m-%d_%H%M%S}_{label}.png")
            img.save(path)
            log(f"đã lưu ảnh {path} ({time.time() - t0:.1f}s)")
        except Exception as e:  # noqa: BLE001
            log(f"lỗi chụp ảnh tĩnh: {e}")
        finally:
            self.busy = False


def run():
    cfg, ini_path = load_config()
    log(f"AoE-MapCap Recorder. Cấu hình: {ini_path}")
    lower_priority()

    ffmpeg = find_ffmpeg([cfg["game_dir"]])
    if cfg["record_video"] and not ffmpeg:
        log("KHÔNG tìm thấy ffmpeg.exe. Đặt ffmpeg.exe cạnh file này hoặc cài ffmpeg vào PATH. Chỉ chụp ảnh tĩnh.")
        cfg["record_video"] = False
    encoder = None
    if cfg["record_video"]:
        encoder = cfg["encoder"] if cfg["encoder"] != "auto" else pick_encoder(ffmpeg, log=log)
        log(f"ffmpeg: {ffmpeg}  mã hoá: {encoder}")
        video_dir = os.path.join(cfg["out_dir"], "Video")
        recover_partials(ffmpeg, video_dir, log)
        log(f"video lưu tại: {video_dir}")

    palette = drs.load_palette(cfg["game_dir"])
    dat = D.load(os.path.join(cfg["game_dir"], "data", "empires.dat"))
    D.parse_units_by_scan(dat)
    store = SpriteStore(cfg["game_dir"], palette)
    vrender = VideoRenderer(dat, store, palette, width=cfg["video_width"], fog_dim=cfg["fog_dim"], log=log,
                                outline_alpha=cfg["map_outline"])
    stills = None
    if cfg["stills_interval"] > 0:
        srender = FullRenderer(dat, store, palette, scale=cfg["stills_scale"], fog_dim=cfg["fog_dim"], log=lambda m: None)
        stills = StillsWorker(srender, cfg["out_dir"])
    interval_ms = int(cfg["stills_interval"] * 60_000)
    frame_dt = 1.0 / cfg["fps"]

    while True:
        proc = None
        shown = False
        while proc is None:
            proc = find_game_process()
            if proc is None:
                if not shown:
                    log("chờ game (EMPIRESX*.EXE / empires.exe)...")
                    shown = True
                time.sleep(2)
        log(f"thấy game: {proc.info['name']} (pid {proc.pid})")
        # dữ liệu đồ hoạ lấy theo thư mục của chính game đang chạy (nếu có), để khớp bản đang chơi
        try:
            gdir = os.path.dirname(proc.exe())
            if os.path.isfile(os.path.join(gdir, "data", "empires.dat")) and os.path.normcase(gdir) != os.path.normcase(cfg["game_dir"]):
                log(f"game chạy từ {gdir}, nạp lại dữ liệu đồ hoạ từ đó")
                palette = drs.load_palette(gdir)
                dat = D.load(os.path.join(gdir, "data", "empires.dat")); D.parse_units_by_scan(dat)
                store = SpriteStore(gdir, palette)
                vrender = VideoRenderer(dat, store, palette, width=cfg["video_width"], fog_dim=cfg["fog_dim"], log=log,
                                outline_alpha=cfg["map_outline"])
                if stills is not None:
                    stills.renderer = FullRenderer(dat, store, palette, scale=cfg["stills_scale"], fog_dim=cfg["fog_dim"], log=lambda m: None)
                cfg["game_dir"] = gdir
        except Exception as e:  # noqa: BLE001
            log(f"không đọc được thư mục game đang chạy ({e}), dùng cấu hình")
        try:
            mem = ProcessMemory(proc.pid)
        except MemoryError_ as e:
            log(str(e))
            log("Game đang chạy với quyền Administrator: hãy đóng tool và chạy lại bằng chuột phải > Run as administrator.")
            time.sleep(10)
            continue
        reader = GameReader(mem)
        statics = StaticObjects(reader, cfg["static_rescan_seconds"])
        game_no = 0
        rec = None
        last_mark = -1
        last_time = None
        last_time_change = time.time()
        in_game_prev = False
        next_tick = time.time()
        test_seconds = float(os.environ.get("MAPCAP_TEST_SECONDS", "0") or 0)
        t_start = time.time()
        try:
          with mem:
            while mem.alive():
                if test_seconds and time.time() - t_start > test_seconds:
                    log("hết thời gian thử nghiệm")
                    if rec:
                        rec.stop(); rec = None
                    return
                try:
                    in_game = reader.in_game()
                    t = reader.game_time_ms() if in_game else None
                except MemoryError_:
                    in_game, t = False, None

                if in_game and not in_game_prev:
                    game_no += 1
                    last_mark = -1
                    last_time = None
                    statics.reset()
                    log(f"vào trận #{game_no}")
                if in_game_prev and not in_game:
                    log("rời trận")
                    if rec:
                        rec.stop(); rec = None
                in_game_prev = in_game

                if in_game and t is not None:
                    if last_time is not None and t + 60_000 < last_time:
                        log("đồng hồ game reset: trận mới")
                        if rec:
                            rec.stop(); rec = None
                        game_no += 1
                        last_mark = -1
                        statics.reset()
                    if t != last_time:
                        last_time_change = time.time()
                    last_time = t
                    frozen = time.time() - last_time_change
                    if rec and frozen > cfg["frozen_end_seconds"]:
                        log(f"đồng hồ đứng {frozen:.0f}s: coi là hết trận")
                        rec.stop(); rec = None
                        last_mark = 10 ** 9      # không chụp tiếp cho tới trận mới
                    try:
                        if rec is None and cfg["record_video"] and t > 0 and frozen < cfg["frozen_end_seconds"] and last_mark < 10 ** 9:
                            snap = reader.snapshot()
                            if statics.last_scan == 0.0:
                                statics._scan(snap, {u.uid for u in snap.units})
                            statics.attach(snap)
                            rec = MatchRecorder(vrender, ffmpeg, encoder, os.path.join(cfg["out_dir"], "Video"), fps=cfg["fps"],
                                                speed=cfg["speed"], label=f"tran{game_no}", log=log)
                            rec.start(snap)
                            next_tick = time.time() + frame_dt
                        elif rec is not None and time.time() >= next_tick:
                            snap = reader.snapshot()
                            statics.maybe_rescan(snap)
                            statics.attach(snap)
                            rec.tick(snap)
                            next_tick += frame_dt
                            if time.time() > next_tick:          # trễ: bỏ nhịp, không dồn
                                next_tick = time.time() + frame_dt
                            if rec.written % int(cfg["fps"] * 60) == 0:
                                rt = rec.render_times[-int(cfg["fps"] * 60):]
                                log(f"ghi {rec.written} khung, vẽ {sum(rt)/len(rt)*1000:.0f} ms/khung, "
                                    f"game {snap.time_str()}")
                        if stills and interval_ms > 0 and last_mark < 10 ** 9:
                            mark = t // interval_ms
                            if mark >= 1 and mark > last_mark:
                                last_mark = mark
                                s_snap = reader.snapshot()
                                if statics.last_scan == 0.0:
                                    statics._scan(s_snap, {u.uid for u in s_snap.units})
                                statics.merge(s_snap)
                                stills.submit(s_snap, f"tran{game_no}_{int(mark * cfg['stills_interval']):02d}p")
                    except MemoryError_ as e:
                        log(f"lỗi đọc bộ nhớ: {e}")
                    except RuntimeError as e:
                        log(f"lỗi ghi video: {e}")
                        if rec:
                            try:
                                rec.stop()
                            except Exception:  # noqa: BLE001
                                pass
                            rec = None
                        if encoder != "libx264":
                            encoder = "libx264"
                            log("chuyển sang mã hoá libx264 (CPU)")
                        else:
                            cfg["record_video"] = False
                            log("tắt ghi video cho phiên này")
                time.sleep(0.02 if rec else 0.5)
        finally:
            if rec:
                rec.stop()
                rec = None
        log("game đã thoát")


def main():
    try:
        run()
    except KeyboardInterrupt:
        log("dừng.")
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        log(f"LỖI: {e}")
        if sys.stdin and sys.stdin.isatty():
            input("Nhấn Enter để đóng...")


if __name__ == "__main__":
    main()
