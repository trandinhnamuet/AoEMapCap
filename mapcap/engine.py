"""Bộ máy ghi: chờ game, theo dõi trận, ghi video và ảnh. Dùng chung cho GUI và dòng lệnh."""
import configparser
import datetime as dt
import os
import sys
import threading
import time
from dataclasses import dataclass, asdict, fields

import psutil

from . import dat as D
from . import drs
from .game import GameReader
from .memory import ProcessMemory, MemoryError_, check_build, find_game_process, has_window
from .recorder import MatchRecorder, find_ffmpeg, pick_encoder, recover_partials
from .rawrec import RawWriter
from .render_full import FullRenderer, SpriteStore
from .video_render import VideoRenderer
from . import gamefiles


from .gamefiles import GAME_DIR_CANDIDATES  # noqa: E402,F401  - AoE-HD và AOE1R (XArena cài cạnh nhau)


def valid_game_dir(d):
    """Thư mục game dùng được để lấy đồ hoạ: kiểu AoE-HD (data\\graphic.drs...) hoặc AOE1R (data + data2)."""
    from .gamefiles import valid_game_dir as _valid
    return _valid(d)


def resolve_game_dir(*hints):
    """Thư mục game: các gợi ý (cấu hình, header file ghi) -> game đang chạy -> các chỗ cài quen thuộc; None nếu không có."""
    for d in hints:
        if valid_game_dir(d):
            return d
    try:
        p = find_game_process()
        if p is not None:
            d = os.path.dirname(p.exe())
            if valid_game_dir(d):
                return d
    except Exception:  # noqa: BLE001
        pass
    for d in GAME_DIR_CANDIDATES:
        if valid_game_dir(d):
            return d
    return None


def base_dir():
    """Thư mục chứa exe (khi đóng gói) hoặc thư mục dự án."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass
class Config:
    game_dir: str = ""                       # thư mục game; tự nhận từ game đang chạy rồi lưu lại (rỗng = chưa biết)
    out_dir: str = ""                        # rỗng = <thư mục exe>\Video
    video_width: int = 1920
    fps: float = 25.0                        # khung/giây của file video
    capture_fps: float = 25.0                # số lần đọc game và vẽ mỗi giây thật (khung còn lại lấp bằng khung trước)
    speed: float = 1.0                       # tua nhanh khi phát
    fog_dim: float = 0.43
    fog_style: str = "dim"                  # dim = làm tối đều (mặc định); dither = lưới chấm như game
    map_outline: float = 0.35
    record_video: bool = True
    stills_interval: float = 0.0             # phút game; 0 = tắt (từ v3 mặc định tắt: chỉ ghi dữ liệu trận)
    stills_scale: float = 0.5
    frozen_end_seconds: int = 180
    encoder: str = "auto"
    static_rescan_seconds: float = 60.0      # quét lại toàn bộ ô để tìm vật thể tĩnh mới
    static_refresh_seconds: float = 2.0      # đọc lại máu/trạng thái vật thể tĩnh (cây bị đốn -> hình gốc cây)
    record_mode: str = "raw"                 # raw = ghi dữ liệu thô trong trận, dựng video sau; live = vẽ ngay
    render_after: bool = False               # raw: tự dựng video khi hết trận (từ v3 mặc định tắt; xuất video khi cần)
    render_width: int = 1920                 # raw: độ rộng video dựng tự động
    render_workers: int = 0                  # raw: số tiến trình dựng (0 = tự chọn)
    keep_raw: bool = True                    # raw: giữ file .aoerec sau khi dựng
    reader_process: bool = True              # raw: đọc + ghi trong tiến trình riêng (GIL riêng, nhịp đều hơn)
    render_cpus_in_game: str = "auto"        # CPU cho tiến trình dựng khi đang có trận: auto = E-core (8..), "8-15", "" = không ghim
    auto_start: bool = True                  # mở AoE-MapCap là tự bắt đầu ghi (chờ game), không cần bấm (2026-10-13)
    telemetry: bool = True                   # gửi thống kê sử dụng: mã máy ngẫu nhiên, phiên bản, IP (2026-10-15)
    close_to_tray: bool = True               # bấm X: ẩn xuống khay hệ thống, vẫn ghi trận; Thoát ở menu khay (2026-10-16)
    phone_server: bool = False               # mở app là bật máy chủ cho app điện thoại (trang Điện thoại, v14)
    config_version: int = 3                  # tăng khi đổi mặc định quan trọng (v2: nhịp đọc = FPS;
                                             # v3: chỉ ghi dữ liệu trận, không tự dựng video / ảnh tĩnh)

    def fog_param(self):
        """Tham số sương mù cho bộ vẽ: 'dither' hoặc số fog_dim."""
        return "dither" if str(self.fog_style).lower().startswith("dit") else self.fog_dim

    def resolved_out_dir(self):
        return self.out_dir or os.path.join(base_dir(), "Video")

    def stills_dir(self):
        return os.path.join(self.resolved_out_dir(), "Anh")

    def raw_dir(self):
        return os.path.join(self.resolved_out_dir(), "Raw")

    def settings_path(self):
        return os.path.join(self.resolved_out_dir(), "_settings.ini")

    def log_path(self):
        return os.path.join(self.resolved_out_dir(), "_mapcap.log")

    def clamp(self):
        self.video_width = max(640, min(7680, int(self.video_width)))
        self.fps = max(1.0, min(60.0, float(self.fps)))
        self.capture_fps = max(0.5, min(self.fps, float(self.capture_fps)))
        self.speed = max(0.1, min(64.0, float(self.speed)))
        self.fog_dim = max(0.0, min(1.0, float(self.fog_dim)))
        self.map_outline = max(0.0, min(1.0, float(self.map_outline)))
        self.stills_interval = 0.0           # bỏ chụp ảnh toàn bản đồ định kỳ (yêu cầu 2026-10-09); xem replay thay thế
        self.stills_scale = max(0.1, min(1.0, float(self.stills_scale)))
        self.frozen_end_seconds = max(30, int(self.frozen_end_seconds))
        self.static_rescan_seconds = max(10.0, float(self.static_rescan_seconds))
        self.static_refresh_seconds = max(0.5, float(self.static_refresh_seconds))
        self.record_mode = "live" if str(self.record_mode).lower().startswith("live") else "raw"
        self.fog_style = "dither" if str(self.fog_style).lower().startswith("dit") else "dim"
        self.render_width = max(640, min(9216, int(self.render_width)))
        self.render_workers = max(0, min(32, int(self.render_workers)))
        return self


def load_config(path=None):
    cfg = Config()
    path = path or cfg.settings_path()
    if os.path.isfile(path):
        cp = configparser.ConfigParser()
        cp.read(path, encoding="utf-8")
        if cp.has_section("mapcap"):
            s = cp["mapcap"]
            for f in fields(Config):
                if f.name not in s:
                    continue
                raw = s.get(f.name)
                try:
                    if f.type is bool:
                        setattr(cfg, f.name, raw.strip().lower() in ("1", "true", "yes", "on"))
                    else:
                        setattr(cfg, f.name, f.type(raw))
                except (TypeError, ValueError):
                    pass
            ver = int(s.get("config_version", "1") or 1) if s.get("config_version", "").strip().isdigit() else 1
            if ver < 2:                            # cấu hình bản cũ: nâng nhịp đọc lên bằng FPS
                cfg.capture_fps = cfg.fps
            if ver < 3:                            # v3: xem replay là chính, video chỉ xuất khi cần
                cfg.render_after = False
                cfg.stills_interval = 0.0
                cfg.record_mode = "raw"
                cfg.keep_raw = True
                cfg.record_video = True
            cfg.config_version = 3
    return cfg.clamp()


def save_config(cfg, path=None):
    path = path or cfg.settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cp = configparser.ConfigParser()
    cp["mapcap"] = {k: ("1" if v is True else "0" if v is False else str(v)) for k, v in asdict(cfg).items()}
    with open(path, "w", encoding="utf-8") as f:
        cp.write(f)


class Logger:
    def __init__(self, path, callback=None):
        self.path = path
        self.callback = callback
        self._f = None

    def __call__(self, msg):
        line = f"[{dt.datetime.now():%H:%M:%S}] {msg}"
        try:
            print(line, flush=True)
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._f is None:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                self._f = open(self.path, "a", encoding="utf-8")
            self._f.write(line + os.linesep)
            self._f.flush()
        except Exception:  # noqa: BLE001
            pass
        if self.callback:
            try:
                self.callback(line)
            except Exception:  # noqa: BLE001
                pass


class StaticObjects:
    """Vật thể gắn với ô đất (cây rừng, mỏ...) không có trong danh sách người chơi.

    - Quét toàn bộ ô (chậm, ~0.2-0.5 s) lúc vào trận và mỗi rescan_seconds.
    - Giữa hai lần quét, đọc lại gộp máu/trạng thái của các vật thể đã biết mỗi refresh_seconds (~10 ms)
      để cây bị đốn đổi sang hình thân cây đổ / gốc cây.
    """

    def __init__(self, reader, rescan_seconds, log, refresh_seconds=2.0):
        self.reader = reader
        self.rescan_seconds = rescan_seconds
        self.refresh_seconds = refresh_seconds
        self.log = log
        self.units = []
        self.version = 0
        self.last_scan = 0.0
        self.last_refresh = 0.0
        self.busy = False
        self.lock = threading.Lock()

    def reset(self):
        with self.lock:
            self.units = []
            self.version += 1
        self.last_scan = 0.0
        self.last_refresh = 0.0

    def ensure_first(self, snap):
        if self.last_scan == 0.0 and not self.busy:
            self._scan(snap, {u.uid for u in snap.units})

    def maybe_rescan(self, snap):
        if self.busy:
            return
        now = time.time()
        if now - self.last_scan >= self.rescan_seconds:
            self.busy = True
            known = {u.uid for u in snap.units}
            threading.Thread(target=self._scan, args=(snap, known), daemon=True).start()
        elif now - self.last_refresh >= self.refresh_seconds:
            self.busy = True
            threading.Thread(target=self._refresh, daemon=True).start()

    def _state_key(self, units):
        return frozenset((u.uid, u.is_dead, u.udef.addr) for u in units)

    def _scan(self, snap, known):
        self.busy = True
        try:
            t0 = time.time()
            doppels = []
            units = self.reader.scan_tile_units(snap, known_uids=known, doppels=doppels)
            self.reader.doppels.merge(doppels)
            with self.lock:
                changed = self._state_key(units) != self._state_key(self.units)
                self.units = units
                if changed:
                    self.version += 1
            if self.last_scan == 0.0:
                self.log(f"quét vật thể theo ô: {len(units)} vật thể tĩnh ({time.time() - t0:.2f}s)")
            self.last_scan = time.time()
            self.last_refresh = self.last_scan
        except Exception as e:  # noqa: BLE001
            self.log(f"lỗi quét vật thể theo ô: {e}")
            self.last_scan = time.time()
        finally:
            self.busy = False

    def _refresh(self):
        try:
            with self.lock:
                cur = list(self.units)
            units, changed = self.reader.refresh_units(cur)
            with self.lock:
                self.units = units
                if changed:
                    self.version += 1
            self.last_refresh = time.time()
        except Exception as e:  # noqa: BLE001
            self.log(f"lỗi đọc lại vật thể tĩnh: {e}")
            self.last_refresh = time.time()
        finally:
            self.busy = False

    def merge(self, snap):
        known = {u.uid for u in snap.units}
        with self.lock:
            snap.units.extend(u for u in self.units if u.uid not in known)

    def attach(self, snap):
        known = {u.uid for u in snap.units}
        with self.lock:
            units = self.units
            ver = self.version
        extra = [u for u in units if u.uid not in known]
        if len(extra) != len(units):
            ver = ver * 1000 + len(extra)      # danh sách thực tế khác -> buộc dựng lại lớp tĩnh
        snap.static_units = extra
        snap.static_version = ver


class StillsWorker:
    """Chụp ảnh tĩnh chi tiết ở TIẾN TRÌNH riêng (không tranh GIL/CPU với luồng video)."""

    def __init__(self, out_dir, log, game_dir, scale, fog_dim):
        self.out_dir = out_dir
        self.log = log
        self.game_dir = game_dir
        self.scale = scale
        self.fog_dim = fog_dim
        self.procs = []

    def submit(self, snap, label):
        import pickle
        import subprocess
        self.procs = [pr for pr in self.procs if pr.poll() is None]
        if len(self.procs) >= 2:
            self.log("bỏ qua ảnh tĩnh: còn 2 ảnh đang xử lý")
            return
        try:
            tmp_dir = os.path.join(self.out_dir, "_tmp")
            os.makedirs(tmp_dir, exist_ok=True)
            pkl = os.path.join(tmp_dir, f"{label}_{int(time.time())}.snap")
            with open(pkl, "wb") as f:
                pickle.dump(snap, f, protocol=pickle.HIGHEST_PROTOCOL)
            out_png = os.path.join(self.out_dir, f"{dt.datetime.now():%Y-%m-%d_%H%M%S}_{label}.png")
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--render-still", pkl, out_png, self.game_dir, str(self.scale), str(self.fog_dim)]
            else:
                cmd = [sys.executable, os.path.join(base_dir(), "run_app.py"), "--render-still", pkl, out_png,
                       self.game_dir, str(self.scale), str(self.fog_dim)]
            flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            pr = subprocess.Popen(cmd, creationflags=flags | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))
            self.procs.append(pr)
            self.log(f"đang chụp ảnh tĩnh {os.path.basename(out_png)} (tiến trình riêng)")
        except Exception as e:  # noqa: BLE001
            self.log(f"lỗi chụp ảnh tĩnh: {e}")


def render_still_cli(pkl, out_png, game_dir, scale, fog_dim):
    """Điểm vào tiến trình con: vẽ ảnh tĩnh từ file .snap rồi xoá file tạm."""
    import pickle
    snap = pickle.load(open(pkl, "rb"))
    palette = drs.load_palette(game_dir)
    dat = D.load(gamefiles.dat_path(game_dir))
    D.parse_units_by_scan(dat)
    store = SpriteStore(game_dir, palette)
    # Dùng chung bộ vẽ video (doppelganger, sprite/khung game, giai đoạn xây, sương mù lưới chấm, HUD) để ảnh tĩnh
    # không lệch so với video; độ rộng = kích cỡ gốc * scale (0.5 -> 4608 px với bản đồ 144).
    width = max(640, int(round(snap.map_w * 64 * float(scale))))
    vr = VideoRenderer(dat, store, palette, width=width, fog_dim=fog_dim, log=lambda m: None)
    img = vr.render(snap, overlay=True)
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    img.save(out_png)
    # chỉ xoá file tạm do chính tool tạo trong thư mục _tmp
    if os.path.basename(os.path.dirname(os.path.abspath(pkl))) == "_tmp":
        try:
            os.remove(pkl)
        except OSError:
            pass


class SnapshotReader:
    """Đọc snapshot ở luồng riêng theo nhịp capture_fps; giữ bản mới nhất."""

    def __init__(self, reader, statics, interval, log):
        self.reader = reader
        self.statics = statics
        self.interval = interval
        self.log = log
        self.latest = None
        self.seq = 0
        self.err = None
        self.cond = threading.Condition()
        self.stop = threading.Event()
        self.read_times = []
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self.thread.start()

    def _loop(self):
        nxt = time.time()
        while not self.stop.is_set():
            t0 = time.time()
            try:
                snap = self.reader.snapshot()
                self.statics.maybe_rescan(snap)
                self.statics.attach(snap)
                with self.cond:
                    self.latest = snap
                    self.seq += 1
                    self.cond.notify_all()
            except MemoryError_ as e:
                self.err = e
            self.read_times.append(time.time() - t0)
            if len(self.read_times) > 500:
                del self.read_times[:250]
            nxt += self.interval
            delay = nxt - time.time()
            if delay > 0:
                self.stop.wait(delay)
            else:
                nxt = time.time()

    def wait_new(self, last_seq, timeout=1.0):
        with self.cond:
            if self.seq == last_seq:
                self.cond.wait(timeout)
            return self.latest, self.seq

    def close(self):
        self.stop.set()
        self.thread.join(timeout=5)


class RawMatchRecorder:
    """Ghi dữ liệu thô (.aoerec) trong trận; hết trận có thể tự dựng video ở tiến trình riêng.
    Cùng giao diện với MatchRecorder: start/tick/stop, written/dropped/render_times."""

    def __init__(self, cfg, raw_dir, video_dir, label, log, game_dir, on_render_done=None):
        self.cfg = cfg
        self.raw_dir = raw_dir
        self.video_dir = video_dir
        self.label = label
        self.log = log
        self.game_dir = game_dir
        self.on_render_done = on_render_done
        self.on_progress = None       # callable(frac, text) -> trạng thái GUI (Engine gán)
        self.writer = None
        self.path = None
        self.written = 0
        self.dropped = 0
        self.render_times = []
        self.start_real = None

    def start(self, snap):
        os.makedirs(self.raw_dir, exist_ok=True)
        self.path = os.path.join(self.raw_dir, f"{dt.datetime.now():%Y-%m-%d_%H%M%S}_{self.label}.aoerec")
        self.writer = RawWriter(self.path)
        self.writer.start(snap, meta={"game_dir": self.game_dir, "capture_fps": self.cfg.capture_fps})
        self.start_real = time.time()
        self.written = 1
        self.log(f"ghi dữ liệu thô {self.path} ({self.cfg.capture_fps:g} mẫu/giây)")

    def tick(self, snap):
        t0 = time.time()
        self.writer.add_frame(snap)
        self.render_times.append(time.time() - t0)
        self.written += 1

    def stop(self):
        if self.writer is None:
            return None
        n = self.writer.close()
        mb = self.writer.bytes / 1e6
        dur = time.time() - self.start_real if self.start_real else 0
        self.log(f"đã chốt dữ liệu thô {os.path.basename(self.path)}: {n} mẫu, {dur:.0f}s, {mb:.0f} MB")
        self.writer = None
        if self.cfg.render_after and n > 1:
            threading.Thread(target=self._render, daemon=True).start()
        return self.path

    def _render(self):
        from .offline import render_raw
        out = os.path.join(self.video_dir, os.path.splitext(os.path.basename(self.path))[0] + ".mp4")
        try:
            self.log(f"bắt đầu dựng video {os.path.basename(out)} ({self.cfg.render_width}px, {self.cfg.fps:g} fps)...")
            render_raw(self.path, out, width=self.cfg.render_width, fps=self.cfg.fps, speed=self.cfg.speed,
                       fog_dim=self.cfg.fog_param(), outline=self.cfg.map_outline, game_dir=self.game_dir,
                       workers=self.cfg.render_workers or None, log=self.log, progress=self.on_progress)
            if not self.cfg.keep_raw:
                try:
                    os.remove(self.path)
                except OSError:
                    pass
            if self.on_render_done:
                self.on_render_done(out)
        except Exception as e:  # noqa: BLE001
            self.log(f"lỗi dựng video: {e}")
        finally:
            if self.on_progress:
                self.on_progress(1.0, None)


class ProcRecorder(RawMatchRecorder):
    """Ghi dữ liệu thô bằng tiến trình riêng (recproc.RecorderProcess); dựng video sau trận như RawMatchRecorder."""

    def __init__(self, cfg, raw_dir, video_dir, label, log, game_dir, pid, stills=None, on_render_done=None):
        super().__init__(cfg, raw_dir, video_dir, label, log, game_dir, on_render_done)
        self.pid = pid
        self.stills = stills
        self.rp = None

    def start(self, snap):
        from .recproc import RecorderProcess
        os.makedirs(self.raw_dir, exist_ok=True)
        self.path = os.path.join(self.raw_dir, f"{dt.datetime.now():%Y-%m-%d_%H%M%S}_{self.label}.aoerec")
        self.rp = RecorderProcess(self.pid, self.cfg, self.path, self.game_dir, self.log, on_still=self._on_still)
        self.rp.start()
        self.start_real = time.time()
        self.written = 1
        self.log(f"ghi dữ liệu thô {self.path} ({self.cfg.capture_fps:g} mẫu/giây, tiến trình riêng)")

    def _on_still(self, name, snap):
        if self.stills is not None:
            self.stills.submit(snap, name)

    def request_still(self, name):
        if self.rp is not None:
            self.rp.request_still(name)

    def tick(self, snap):
        pass

    def stat_line(self, seconds):
        s = self.rp.minute_summary(int(seconds)) if self.rp else {}
        self.written = s.get("written", self.written)
        gm = s.get("game_ms", 0) // 1000
        return (f"mẫu {s.get('written', 0)} (tiến trình riêng), đọc {s.get('read_ms', 0):.0f} ms (snapshot {s.get('snap_ms', 0):.0f} ms, CPU {s.get('cpu_ms', 0):.0f} ms, {s.get('threads', 0)} luồng, "
                f"{s.get('calls', 0):.0f} lượt/{s.get('mb', 0):.1f} MB mỗi giây), ghi mẫu {s.get('write_ms', 0):.0f} ms, "
                f"{s.get('rate', 0):.1f} mẫu thật/giây, {s.get('units', 0)} unit, game {gm // 3600:02d}:{(gm // 60) % 60:02d}:{gm % 60:02d}, "
                f"ghi nhớ sương mù {s.get('dop', 0)} (tổng {s.get('dop_total', 0)})")

    def stop(self):
        if self.rp is None:
            return None
        n = self.rp.stop()
        self.rp = None
        dur = time.time() - self.start_real if self.start_real else 0
        mb = os.path.getsize(self.path) / 1e6 if os.path.exists(self.path) else 0
        self.log(f"đã chốt dữ liệu thô {os.path.basename(self.path)}: {n} mẫu, {dur:.0f}s, {mb:.0f} MB")
        if self.cfg.render_after and (n or 0) > 1:
            threading.Thread(target=self._render, daemon=True).start()
        return self.path


def _close_reader(sreader):
    if sreader is not None:
        try:
            sreader.close()
        except Exception:  # noqa: BLE001
            pass
    return None


class Engine:
    """Vòng lặp ghi. Gọi run() trong luồng riêng; set stop_event để dừng an toàn."""

    def __init__(self, cfg: Config, log, stop_event=None, status=None, progress=None):
        self.cfg = cfg
        self.log = log
        self.stop_event = stop_event or threading.Event()
        self.status = status or (lambda s: None)
        # progress(label, text): tiến độ dựng video từng trận (text None = xong); mặc định đẩy vào status
        self.progress = progress or (lambda label, text: self.status(f"dựng {label}: {text}") if text else None)
        self.state = "idle"

    def _set(self, s):
        self.state = s
        self.status(s)
        from .offline import set_in_game
        set_in_game(s == "đang ghi")

    @property
    def current_rec_path(self):
        """File .aoerec đang ghi (None nếu không có trận đang ghi) — giao diện không cho xoá file này."""
        rec = getattr(self, "_rec", None)
        return getattr(rec, "path", None) if rec is not None else None

    def _stop_rec(self, rec):
        """Chốt trận đang ghi và nhớ lại file của phiên (để tóm tắt khi dừng)."""
        if getattr(self, "_rec", None) is rec:
            self._rec = None
        path = rec.stop()
        if path:
            self.session_files.append(path)
            from . import telemetry                     # thống kê: ghi xong một trận
            try:                                        # tên người ghi (nickname) của trận vừa ghi
                from .rawrec import read_header
                nm = telemetry.name_from_header(read_header(path) or {})
            except Exception:  # noqa: BLE001
                nm = ""
            telemetry.send("mapcap", "match", self.cfg.telemetry, name=nm or None, raw_dir=self.cfg.raw_dir())
        return path

    def run(self):
        """Chạy vòng ghi; khi kết thúc (dừng theo yêu cầu, lỗi, hết thời gian thử) luôn ghi một dòng tóm tắt."""
        self.session_files = []
        t0 = time.time()
        reason = "lỗi"
        try:
            self._run()
            reason = "theo yêu cầu" if self.stop_event.is_set() else "vòng ghi kết thúc"
        finally:
            n = len(self.session_files)
            mins = (time.time() - t0) / 60
            if n:
                names = ", ".join(os.path.basename(p) for p in self.session_files[-5:])
                self.log(f"đã dừng ghi ({reason}) sau {mins:.0f} phút: phiên này ghi {n} trận ({names}); "
                         f"xem ở thẻ Trận đã ghi")
            else:
                self.log(f"đã dừng ghi ({reason}) sau {mins:.0f} phút: chưa ghi trận nào")
            self._set("đã dừng")

    def _run(self):
        cfg = self.cfg
        log = self.log
        out_dir = cfg.resolved_out_dir()
        os.makedirs(out_dir, exist_ok=True)
        try:
            psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        except Exception:  # noqa: BLE001
            pass

        # chế độ dữ liệu thô chỉ cần ffmpeg khi tự xuất video sau trận (hoặc còn .part.mp4 cần đóng gói lại):
        # không thì không giải nén ffmpeg (87 MB) mỗi lần bắt đầu ghi
        need_ffmpeg = cfg.record_mode == "live" or cfg.render_after
        try:
            has_parts = any(n.lower().endswith(".part.mp4") for n in os.listdir(out_dir))
        except OSError:
            has_parts = False
        ffmpeg = find_ffmpeg([cfg.game_dir] if cfg.game_dir else [], extract=need_ffmpeg or has_parts)
        encoder = None
        record_video = cfg.record_video
        if record_video and need_ffmpeg and not ffmpeg:
            if cfg.record_mode == "live":
                log("KHÔNG tìm thấy ffmpeg. Chỉ chụp ảnh tĩnh.")
                record_video = False
            else:
                log("KHÔNG tìm thấy ffmpeg: vẫn ghi dữ liệu trận, không tự xuất video.")
                cfg.render_after = False
        if record_video and need_ffmpeg and ffmpeg:
            encoder = cfg.encoder if cfg.encoder != "auto" else pick_encoder(ffmpeg, log=log)
            log(f"mã hoá video: {encoder}")
        if record_video:
            log("chế độ: " + ("vẽ video thời gian thực" if cfg.record_mode == "live" else
                              "ghi dữ liệu trận (xem bằng Xem replay)" + (", tự xuất video sau trận" if cfg.render_after else "")))
        if ffmpeg:
            recover_partials(ffmpeg, out_dir, log)
        from .offline import cleanup_stale, configure_affinity
        cleanup_stale(out_dir, log)
        configure_affinity(cfg.render_cpus_in_game)
        log(f"dữ liệu lưu tại: {out_dir}")

        # Ghi dữ liệu trận không cần đồ hoạ; chỉ chế độ vẽ video ngay trong trận / ảnh tĩnh mới nạp (khi đã thấy game).
        gfx = {"dir": cfg.game_dir if valid_game_dir(cfg.game_dir) else None, "video": None}
        interval_ms = int(cfg.stills_interval * 60_000)
        frame_dt = 1.0 / cfg.capture_fps
        test_seconds = float(os.environ.get("MAPCAP_TEST_SECONDS", "0") or 0)
        t_start = time.time()
        unsupported = set()            # pid game có exe không đọc được: không ghi, chờ game khác
        abandoned = set()              # pid game không cửa sổ đã bỏ để sang game khác (vd treo khi khởi động)

        while not self.stop_event.is_set():
            self._set("chờ game")
            proc = None
            shown = False
            while proc is None and not self.stop_event.is_set():
                abandoned = {p for p in abandoned if psutil.pid_exists(p)}
                proc = find_game_process(exclude=unsupported | abandoned)
                if proc is None:
                    if not shown:
                        log("chờ game (EMPIRESX*.EXE / empires.exe)...")
                        shown = True
                    if test_seconds and time.time() - t_start > test_seconds:
                        return
                    self.stop_event.wait(2)
            if self.stop_event.is_set():
                log("nhận lệnh dừng khi đang chờ game")
                return
            log(f"thấy game: {proc.info['name']} (pid {proc.pid})")
            hit = None
            try:
                with ProcessMemory(proc.pid) as pm:
                    hit, total = check_build(pm)
            except Exception:  # noqa: BLE001  - chưa mở được (quyền admin...): để bước ghi báo lỗi như cũ
                pass
            if hit == 0:                       # chương trình khác hẳn (vd Empires.exe = AoE gốc không có Rise of Rome)
                log(f"{proc.info['name']} không phải bản Age of Empires: Rise of Rome 1.0 mà tool đọc được "
                    "(AoE-HD, AOE1R Empiresx.exe): không ghi trận này. Hãy chạy game bằng EMPIRESX.EXE / Empiresx.exe.")
                unsupported.add(proc.pid)
                continue
            if hit is not None and hit < total:
                log(f"cảnh báo: exe chỉ khớp {hit}/{total} dấu nhận dạng của bản đã kiểm; vẫn thử ghi")
            try:
                gdir = os.path.dirname(proc.exe())
                if valid_game_dir(gdir):
                    if os.path.normcase(gdir) != os.path.normcase(gfx["dir"] or ""):
                        log(f"game chạy từ {gdir} ({gamefiles.layout_name(gdir)})")
                        gfx = {"dir": gdir, "video": None}
                    if os.path.normcase(cfg.game_dir or "") != os.path.normcase(gdir):
                        cfg.game_dir = gdir              # nhớ lại cho Xem replay / Xuất video
                        try:
                            save_config(cfg)
                        except Exception:  # noqa: BLE001
                            pass
            except Exception as e:  # noqa: BLE001
                log(f"không đọc được thư mục game đang chạy ({e})")
            if gfx["dir"] is None:
                gfx["dir"] = resolve_game_dir()
                if gfx["dir"] is None:
                    log("không xác định được thư mục game (vẫn ghi được; khi xem replay sẽ cần chỉ thư mục game)")
            if gfx["video"] is None and gfx["dir"] and (cfg.record_mode == "live" or cfg.stills_interval > 0):
                try:
                    gfx = self._load_graphics(gfx["dir"])
                except Exception as e:  # noqa: BLE001
                    log(f"không nạp được đồ hoạ từ {gfx['dir']} ({e}): chuyển sang chỉ ghi dữ liệu")
                    cfg.record_mode = "raw"
            try:
                mem = ProcessMemory(proc.pid)
            except MemoryError_ as e:
                log(str(e))
                log("Game đang chạy với quyền Administrator: hãy chạy tool bằng Run as administrator.")
                self.stop_event.wait(10)
                continue

            reader = GameReader(mem)
            statics = StaticObjects(reader, cfg.static_rescan_seconds, log, cfg.static_refresh_seconds)
            stills = StillsWorker(cfg.stills_dir(), log, gfx["dir"], cfg.stills_scale, cfg.fog_param()) if cfg.stills_interval > 0 else None
            vrender = gfx["video"]
            game_no = 0
            rec = None
            last_mark = -1
            last_time = None
            last_time_change = time.time()
            in_game_prev = False
            next_tick = time.time()
            sreader = None
            last_seq = 0
            last_ticks = 0
            next_log = 0.0
            next_switch_check = time.time() + 5
            switched = False
            try:
                with mem:
                    while mem.alive() and not self.stop_event.is_set():
                        if test_seconds and time.time() - t_start > test_seconds:
                            log("hết thời gian thử nghiệm")
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
                            reader.doppels.reset()
                            log(f"vào trận #{game_no}")
                        if in_game_prev and not in_game:
                            log("rời trận")
                            if rec:
                                self._stop_rec(rec); rec = None; sreader = _close_reader(sreader)
                            self._set("trong game, chờ trận")
                        in_game_prev = in_game

                        if in_game and t is not None:
                            if last_time is not None and t + 60_000 < last_time:
                                log("đồng hồ game reset: trận mới")
                                if rec:
                                    self._stop_rec(rec); rec = None; sreader = _close_reader(sreader)
                                    self._set("trong game, chờ trận")
                                game_no += 1
                                last_mark = -1
                                statics.reset()
                                reader.doppels.reset()
                            if t != last_time:
                                last_time_change = time.time()
                            last_time = t
                            frozen = time.time() - last_time_change
                            if rec and frozen > cfg.frozen_end_seconds:
                                log(f"đồng hồ đứng {frozen:.0f}s: coi là hết trận")
                                self._stop_rec(rec); rec = None; sreader = _close_reader(sreader)
                                self._set("trong game, chờ trận")
                                last_mark = 10 ** 9
                            try:
                                if rec is None and record_video and t > 0 and frozen < cfg.frozen_end_seconds and last_mark < 10 ** 9:
                                    snap = reader.snapshot()
                                    statics.ensure_first(snap)
                                    statics.attach(snap)
                                    if cfg.record_mode == "raw" and cfg.reader_process:
                                        rec = ProcRecorder(cfg, cfg.raw_dir(), out_dir, f"tran{game_no}", log, gfx["dir"], proc.pid, stills)
                                        rec.on_progress = (lambda lb: (lambda f, s: self.progress(lb, s)))(f"tran{game_no}")
                                    elif cfg.record_mode == "raw":
                                        rec = RawMatchRecorder(cfg, cfg.raw_dir(), out_dir, f"tran{game_no}", log, gfx["dir"])
                                        rec.on_progress = (lambda lb: (lambda f, s: self.progress(lb, s)))(f"tran{game_no}")
                                    else:
                                        rec = MatchRecorder(vrender, ffmpeg, encoder, out_dir, fps=cfg.fps,
                                                            speed=cfg.speed, label=f"tran{game_no}", log=log)
                                    rec.start(snap)
                                    self._rec = rec
                                    if isinstance(rec, ProcRecorder):
                                        sreader = None
                                    else:
                                        sreader = SnapshotReader(reader, statics, frame_dt, log)
                                        sreader.start()
                                    last_seq = 0
                                    last_ticks = 0
                                    next_log = time.time() + 60
                                    self._set("đang ghi")
                                elif rec is not None and isinstance(rec, ProcRecorder):
                                    self.stop_event.wait(0.25)
                                    if not rec.rp.alive() and rec.rp.done_n is None:
                                        log("tiến trình ghi đã kết thúc bất thường" + (f": {rec.rp.error}" if rec.rp.error else ""))
                                        self._stop_rec(rec); rec = None
                                        record_video = False
                                    elif time.time() >= next_log:
                                        now = time.time()
                                        span = now - (next_log - 60)
                                        next_log = now + 60
                                        log(rec.stat_line(span))
                                elif rec is not None:
                                    snap, seq = sreader.wait_new(last_seq, timeout=0.5)
                                    if snap is not None and seq != last_seq:
                                        last_seq = seq
                                        rec.tick(snap)
                                    if sreader.err is not None:
                                        e = sreader.err; sreader.err = None
                                        log(f"lỗi đọc bộ nhớ: {e}")
                                    if time.time() >= next_log:
                                        now = time.time()
                                        span = now - (next_log - 60)
                                        next_log = now + 60
                                        n_ticks = len(rec.render_times) - last_ticks
                                        rt = rec.render_times[-max(n_ticks, 1):]
                                        rd = sreader.read_times[-max(n_ticks, 1):]
                                        last_ticks = len(rec.render_times)
                                        what = "ghi mẫu" if cfg.record_mode == "raw" else "vẽ"
                                        log(f"{'mẫu' if cfg.record_mode == 'raw' else 'khung'} {rec.written} ({rec.dropped} lấp), đọc {sum(rd)/max(len(rd),1)*1000:.0f} ms, "
                                            f"{what} {sum(rt)/max(len(rt),1)*1000:.0f} ms, {n_ticks/max(span,1):.1f} mẫu thật/giây, game {snap.time_str() if snap else '?'}, "
                                            f"ghi nhớ sương mù {reader.doppels.count()} (tổng {reader.doppels.found_total})")
                                if stills and interval_ms > 0 and last_mark < 10 ** 9:
                                    mark = t // interval_ms
                                    if mark >= 1 and mark > last_mark:
                                        last_mark = mark
                                        name = f"tran{game_no}_{int(mark * cfg.stills_interval):02d}p"
                                        if isinstance(rec, ProcRecorder):
                                            rec.request_still(name)      # tiến trình ghi gửi snapshot về, không đọc trùng
                                        else:
                                            s_snap = reader.snapshot()
                                            statics.ensure_first(s_snap)
                                            statics.merge(s_snap)
                                            stills.submit(s_snap, name)
                            except MemoryError_ as e:
                                log(f"lỗi đọc bộ nhớ: {e}")
                            except RuntimeError as e:
                                log(f"lỗi ghi video: {e}")
                                sreader = _close_reader(sreader)
                                if rec:
                                    try:
                                        self._stop_rec(rec)
                                    except Exception:  # noqa: BLE001
                                        pass
                                    rec = None
                                if encoder != "libx264":
                                    encoder = "libx264"
                                    log("chuyển sang mã hoá libx264 (CPU)")
                                else:
                                    record_video = False
                                    log("tắt ghi video cho phiên này")
                        elif not in_game:
                            self._set("trong game, chờ trận")
                        if rec is None and not in_game and time.time() >= next_switch_check:
                            # chưa vào trận mà có game khác, game đang bám lại không có cửa sổ: sang game kia
                            next_switch_check = time.time() + 5
                            other = find_game_process(exclude=unsupported | abandoned | {proc.pid})
                            if other is not None and not has_window(proc.pid):
                                log(f"game pid {proc.pid} không có cửa sổ, có game khác (pid {other.pid}): chuyển sang")
                                abandoned.add(proc.pid)
                                switched = True
                                break
                        if rec is None:
                            self.stop_event.wait(0.5)
            finally:
                sreader = _close_reader(sreader)
                if rec and self.stop_event.is_set():
                    log("nhận lệnh dừng: đang chốt trận đang ghi...")
                if rec:
                    self._stop_rec(rec)
                    rec = None
            if self.stop_event.is_set():
                log("đã dừng theo yêu cầu")
                return
            if not switched:
                log("game đã thoát")
        self._set("đã dừng")

    def _load_graphics(self, gdir):
        cfg = self.cfg
        t0 = time.time()
        palette = drs.load_palette(gdir)
        dat = D.load(gamefiles.dat_path(gdir))
        D.parse_units_by_scan(dat)
        store = SpriteStore(gdir, palette)
        video = VideoRenderer(dat, store, palette, width=cfg.video_width, fog_dim=cfg.fog_param(), log=self.log,
                              outline_alpha=cfg.map_outline)
        self.log(f"đã nạp dữ liệu đồ hoạ từ {gdir} ({len(dat.graphics)} graphics, {len(dat.units)} unit, {time.time() - t0:.1f}s)")
        return {"dir": gdir, "video": video}
