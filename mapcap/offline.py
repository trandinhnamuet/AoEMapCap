"""Dựng video từ dữ liệu thô (.aoerec), chia đoạn chạy song song nhiều tiến trình rồi nối lại."""
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

import numpy as np

from . import dat as D
from . import drs
from .rawrec import RawReader
from .recorder import ENCODER_ARGS, VideoWriter, find_ffmpeg, pick_encoder
from .render_full import SpriteStore
from .video_render import VideoRenderer
from . import gamefiles

_ACTIVE = 0
_ACTIVE_LOCK = threading.Lock()
_JOBS = []          # các lượt dựng đang chạy: {"procs": [...], "tmp_dir": ...}
TMP_PREFIX = "aoerender_"
_QUEUE = threading.Lock()       # các lượt dựng chạy tuần tự (hai lượt chồng nhau = 16 tiến trình con)
_ABORT_GEN = 0                  # tăng mỗi lần abort_all: lượt đang xếp hàng thấy đổi thì huỷ
_IN_GAME = False                # đang có trận: tiến trình dựng ghim vào E-core, nhường P-core cho game + bộ đọc
RENDER_CPUS_IN_GAME = "auto"    # "auto" = CPU logic 8.. (sau 8 luồng P-core) khi máy >= 12 luồng; "8-15"; "" = không ghim
PROGRESS_EXT = ".progress"
OWNER_FILE = "owner.pid"
CHILD_LOG = "_mapcap_child.log"


def active_renders():
    """Số lần dựng video (render_raw) đang chạy trong tiến trình này."""
    return _ACTIVE


def set_in_game(flag):
    """Engine báo đang có trận hay không; lượt dựng đang chạy đổi affinity ngay ở vòng lặp kế."""
    global _IN_GAME
    _IN_GAME = bool(flag)


def configure_affinity(spec):
    global RENDER_CPUS_IN_GAME
    RENDER_CPUS_IN_GAME = spec if spec is not None else "auto"


def _in_game_cpus():
    """Danh sách CPU logic cho tiến trình dựng khi đang có trận; [] = không ghim."""
    n = os.cpu_count() or 0
    spec = (RENDER_CPUS_IN_GAME or "").strip().lower()
    if spec == "auto":
        return list(range(8, n)) if n >= 12 else []
    cpus = set()
    for part in spec.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                cpus.update(range(int(a), int(b) + 1))
            else:
                cpus.add(int(part))
        except ValueError:
            pass
    return sorted(c for c in cpus if 0 <= c < n)


def _apply_affinity(job):
    """Ghim tiến trình đoạn (và ffmpeg con) vào E-core khi đang có trận, trả lại mọi lõi khi không."""
    want = tuple(_in_game_cpus()) if _IN_GAME else ()
    if job.get("affinity") == want:
        return
    try:
        import psutil
    except ImportError:
        return
    cpus = list(want) or list(range(os.cpu_count() or 1))
    for p in job["procs"]:
        if p.poll() is not None:
            continue
        try:
            pr = psutil.Process(p.pid)
            for q in [pr] + pr.children(recursive=True):
                q.cpu_affinity(cpus)
        except Exception:  # noqa: BLE001
            pass
    job["affinity"] = want


def abort_all(log=None):
    """Tắt mọi tiến trình dựng đoạn đang chạy và xoá thư mục tạm của chúng (gọi khi thoát chương trình).
    Lượt đang xếp hàng chờ cũng bị huỷ."""
    global _ABORT_GEN
    _ABORT_GEN += 1
    with _ACTIVE_LOCK:
        jobs = list(_JOBS)
    for job in jobs:
        job["aborted"] = True
        _kill_procs(job["procs"])
        _remove_tmp(job["tmp_dir"])
        if log:
            log(f"đã huỷ lượt dựng dở, xoá {os.path.basename(job['tmp_dir'])}")
    return len(jobs)


def _kill_procs(procs):
    """Tắt các tiến trình đoạn cùng toàn bộ con của chúng (ffmpeg đang giữ file .part.mp4) rồi chờ chúng kết thúc."""
    kids = []
    for p in procs:
        if p.poll() is not None:
            continue
        try:
            import psutil
            kids += psutil.Process(p.pid).children(recursive=True)
        except Exception:  # noqa: BLE001
            pass
        try:
            p.terminate()
        except OSError:
            pass
    for k in kids:
        try:
            k.kill()
        except Exception:  # noqa: BLE001
            pass
    for p in procs:
        try:
            p.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass
    for k in kids:
        try:
            k.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass


def _remove_tmp(d):
    """Xoá thư mục tạm; thử vài lần vì ffmpeg con có thể còn giữ file .part.mp4 một lát sau khi bị tắt."""
    for _ in range(10):
        shutil.rmtree(d, ignore_errors=True)
        if not os.path.isdir(d):
            return True
        time.sleep(0.5)
    return not os.path.isdir(d)


def _pid_alive(pid, since):
    """Tiến trình pid còn chạy và đã tồn tại từ trước thời điểm `since` (tránh pid được cấp lại)."""
    if pid <= 0:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid) and psutil.Process(pid).create_time() <= since + 2
    except Exception:  # noqa: BLE001
        return False


def cleanup_stale(video_dir, log=None, max_age_hours=1.0):
    """Xoá thư mục tạm aoerender_* bỏ lại bởi lượt dựng đã chết: có owner.pid mà tiến trình cha không còn, hoặc không
    có owner.pid (bản cũ) và không file nào được ghi trong max_age_hours. Trả về số thư mục đã xoá."""
    n = 0
    if not os.path.isdir(video_dir):
        return 0
    for name in os.listdir(video_dir):
        d = os.path.join(video_dir, name)
        if not name.startswith(TMP_PREFIX) or not os.path.isdir(d):
            continue
        owner = os.path.join(d, OWNER_FILE)
        try:
            if os.path.isfile(owner):
                try:
                    pid = int(open(owner, encoding="utf-8").read().strip() or 0)
                except ValueError:
                    pid = 0
                dead = pid != os.getpid() and not _pid_alive(pid, os.path.getmtime(owner))
            else:
                files = [os.path.join(d, f) for f in os.listdir(d)]
                newest = max([os.path.getmtime(f) for f in files] + [os.path.getmtime(d)])
                dead = time.time() - newest > max_age_hours * 3600
        except OSError:
            continue
        if dead and _remove_tmp(d):
            n += 1
            if log:
                log(f"đã xoá thư mục tạm bỏ lại: {name}")
    return n


class _Progress:
    """Gộp file tiến độ của các tiến trình đoạn -> (phần trăm, dòng chữ có ước lượng thời gian còn lại).
    Tốc độ lấy theo cửa sổ 90 s gần nhất; khi các đoạn còn đang phát lại dữ liệu (chưa ghi khung) thì báo riêng."""

    def __init__(self, n_out, n_parts, t_start):
        self.n_out = max(1, n_out)
        self.n_parts = max(1, n_parts)
        self.t_start = t_start
        self.hist = []          # (t, tổng khung đã ghi)

    @staticmethod
    def _fmt(sec):
        sec = int(max(0, sec))
        return f"{sec // 60} phút {sec % 60:02d} giây" if sec >= 60 else f"{sec} giây"

    def update(self, prog_files):
        written = 0
        replay = 0.0
        for pf in prog_files:
            try:
                a, b = open(pf, encoding="utf-8").read().split()
                replay += float(a)
                written += int(b)
            except (OSError, ValueError):
                pass
        now = time.time()
        self.hist.append((now, written))
        self.hist = [h for h in self.hist if now - h[0] <= 90] or self.hist[-1:]
        frac = min(1.0, written / self.n_out)
        pct = f"{frac * 100:.0f}%"
        elapsed = now - self.t_start
        (t0, w0) = self.hist[0]
        rate = (written - w0) / (now - t0) if now - t0 >= 5 and written > w0 else 0.0
        if written == 0:
            text = (f"đang dựng 0% - chuẩn bị dữ liệu {replay / self.n_parts * 100:.0f}% "
                    f"({self._fmt(elapsed)} đã qua)")
        elif rate > 0:
            # các đoạn còn phát lại sẽ góp tốc độ sau; ước lượng này hơi bi quan lúc đầu và tự chỉnh dần
            eta = (self.n_out - written) / rate
            text = (f"đang dựng {pct} ({written}/{self.n_out} khung, {rate:.1f} khung/giây) - "
                    f"còn khoảng {self._fmt(eta)}, đã qua {self._fmt(elapsed)}")
        else:
            text = f"đang dựng {pct} ({written}/{self.n_out} khung), đã qua {self._fmt(elapsed)}"
        return frac, text


def _child_error(tmp_dir):
    """Dòng lỗi cuối tiến trình con ghi vào _mapcap_child.log trong thư mục tạm (nếu có)."""
    p = os.path.join(tmp_dir, CHILD_LOG)
    try:
        lines = [ln.strip() for ln in open(p, encoding="utf-8", errors="replace").read().splitlines() if ln.strip()]
    except OSError:
        return ""
    return lines[-1][-400:] if lines else ""


def _frame_times(frames_at, fps, speed):
    """Ánh xạ khung video (đều theo thời gian thật) -> chỉ số mẫu gần nhất trước đó."""
    if not frames_at:
        return []
    t0 = frames_at[0]
    dur = frames_at[-1] - t0
    n_out = int(dur * fps) + 1
    idx = []
    j = 0
    for k in range(n_out):
        t = t0 + k / fps
        while j + 1 < len(frames_at) and frames_at[j + 1] <= t:
            j += 1
        idx.append(j)
    return idx


def scan_times(rec_path):
    """Lấy danh sách taken_at của các mẫu (đọc nhanh, không dựng Snapshot)."""
    return scan_info(rec_path)[0]


def scan_info(rec_path):
    """(danh sách taken_at, số bản ghi doppelganger từ game trong file, header)."""
    rd = RawReader(rec_path)
    times = []
    n_dop = 0
    hdr = None
    for tag, payload in rd.records():
        if tag == b"H":
            hdr = payload
        elif tag == b"F":
            times.append(payload["at"])
            arr = payload.get("units")
            if arr is not None and len(arr) and "kind" in (arr.dtype.names or ()):
                n_dop += int((arr["kind"] == 25).sum())
    return times, n_dop, hdr


def output_size(hdr, width):
    """Kích thước khung video (W, H) mà VideoRenderer sẽ tạo cho file thô có header hdr ở độ rộng width."""
    elev = np.asarray(hdr.get("elevation", 0))
    elev_max = int(elev.max()) if elev.size else 0
    W, H, *_ = VideoRenderer.geometry(int(hdr["map_w"]), int(hdr["map_h"]), elev_max, width)
    return W, H


def render_chunk(rec_path, out_mp4, k0, k1, width, fps, speed, fog_dim, outline, game_dir, ffmpeg, encoder,
                 emulate_ghosts=False, log=None):
    """Dựng các khung video [k0, k1) của file thô ra một mp4 (một tiến trình)."""
    log = log or (lambda m: None)
    times = scan_times(rec_path)
    idx_map = _frame_times(times, fps, speed)
    if not idx_map:
        return 0
    k1 = min(k1, len(idx_map))
    need_first = idx_map[k0]
    need_last = idx_map[k1 - 1]
    palette = drs.load_palette(game_dir)
    dat = D.load(gamefiles.dat_path(game_dir))
    D.parse_units_by_scan(dat)
    store = SpriteStore(game_dir, palette)
    vr = VideoRenderer(dat, store, palette, width=width, fog_dim=fog_dim, log=lambda m: None, outline_alpha=outline)
    vr.emulate_ghosts = bool(emulate_ghosts)
    writer = None
    written = 0
    k = k0
    frame_bytes = None
    rd = RawReader(rec_path)
    prog_path = out_mp4 + PROGRESS_EXT
    t_prog = 0.0

    def report(replay_frac, force=False):
        nonlocal t_prog
        now = time.time()
        if force or now - t_prog >= 1.0:
            t_prog = now
            try:
                with open(prog_path, "w", encoding="utf-8") as f:
                    f.write(f"{replay_frac:.4f} {written}")
            except OSError:
                pass

    for si, snap in enumerate(rd.frames()):
        if si < need_first:
            if need_first and (si & 31) == 0:
                report(si / need_first)
            continue
        if si > need_last:
            break
        # khung video nào dùng mẫu si?
        if k < k1 and idx_map[k] == si:
            img = vr.render(snap)
            frame_bytes = img.tobytes()
            if writer is None:
                writer = VideoWriter(ffmpeg, out_mp4, img.size, fps * speed, encoder, log)
            while k < k1 and idx_map[k] == si:
                writer.write(frame_bytes)
                written += 1
                k += 1
            report(1.0)
        elif k < k1 and idx_map[k] < si:
            # mẫu cần đã qua (không xảy ra vì idx tăng dần), bỏ qua an toàn
            k += 1
    if writer is not None:
        writer.close()
    report(1.0, force=True)
    return written


def render_raw(rec_path, out_mp4, width=1920, fps=25.0, speed=1.0, fog_dim=0.43, outline=0.35, game_dir=None,
               workers=None, log=None, progress=None):
    """Dựng toàn bộ video: chia đoạn, chạy song song bằng chính exe/python này, nối bằng ffmpeg.
    Đếm số lần dựng đang chạy để giao diện biết khi nào thoát sẽ làm mất video."""
    global _ACTIVE
    with _ACTIVE_LOCK:
        _ACTIVE += 1
    try:
        waited = False
        gen0 = _ABORT_GEN
        while not _QUEUE.acquire(timeout=1.0):
            if _ABORT_GEN != gen0:
                raise RuntimeError("lượt dựng bị huỷ (chương trình thoát)")
            if not waited:
                waited = True
                (log or (lambda m: None))(f"chờ lượt dựng trước xong rồi mới dựng {os.path.basename(out_mp4)}")
                if progress:
                    progress(0.0, "chờ lượt dựng trước xong...")
        if _ABORT_GEN != gen0:          # lượt trước bị huỷ và nhả khoá đúng lúc ta lấy được
            _QUEUE.release()
            raise RuntimeError("lượt dựng bị huỷ (chương trình thoát)")
        try:
            return _render_raw_impl(rec_path, out_mp4, width, fps, speed, fog_dim, outline, game_dir, workers, log, progress)
        finally:
            _QUEUE.release()
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE -= 1


def _render_raw_impl(rec_path, out_mp4, width=1920, fps=25.0, speed=1.0, fog_dim=0.43, outline=0.35, game_dir=None,
               workers=None, log=None, progress=None):
    log = log or (lambda m: None)
    t_start = time.time()
    rec_path = os.path.abspath(rec_path)
    out_mp4 = os.path.abspath(out_mp4)        # đường dẫn tương đối lẫn dấu / và \ làm ffmpeg concat không mở được list
    ffmpeg = find_ffmpeg([game_dir] if game_dir else ())
    if not ffmpeg:
        raise RuntimeError("không tìm thấy ffmpeg")
    if getattr(sys, "frozen", False):
        # exe bị ghi đè khi đang chạy -> tiến trình con đọc archive sai (zlib "incorrect header check")
        try:
            import psutil
            if os.path.getmtime(sys.executable) > psutil.Process().create_time() + 1:
                raise RuntimeError("file exe đã bị thay thế sau khi chương trình khởi động; hãy mở lại chương trình rồi bấm "
                                   "'Dựng lại video...' trên file thô")
        except ImportError:
            pass
    times, n_dop, hdr = scan_info(rec_path)
    if not times or hdr is None:
        raise RuntimeError("file thô không có mẫu nào")
    size = output_size(hdr, width)
    encoder = pick_encoder(ffmpeg, log=log, size=size)   # thử ở đúng kích thước: Quick Sync/NVENC từ chối > 4096 px
    if encoder == "libx264" and size[0] > 4096:
        encoder = "libx264_big"
    emulate = n_dop == 0
    log(f"bản ghi nhớ sương mù: {n_dop} doppelganger đọc từ game" if n_dop else
        "dữ liệu không có doppelganger của game: dùng mô phỏng công trình đã thấy")
    n_out = len(_frame_times(times, fps, speed))
    if workers is None:
        workers = max(1, min(8, (os.cpu_count() or 4) - 1))
    workers = max(1, min(workers, max(1, n_out // 200)))
    # mỗi tiến trình đoạn giữ nhiều lớp ảnh cỡ khung + libx264; 8 tiến trình ở 9216 px trên máy 16 GB làm libx264
    # không cấp phát được ("Could not open encoder") -> giới hạn số tiến trình theo RAM trống
    try:
        import psutil
        per_worker = size[0] * size[1] * 3 * 27     # đo 9216x4690: vẽ ~2 GB + libx264_big ~1,3 GB = 3,3 GB ~ 26 lần khung RGB
        fit = max(1, int(psutil.virtual_memory().available * 0.8 // per_worker))
        if fit < workers:
            log(f"RAM trống {psutil.virtual_memory().available / 2**30:.1f} GB chỉ đủ {fit} tiến trình ở {size[0]}x{size[1]} "
                f"(~{per_worker / 2**30:.1f} GB mỗi tiến trình), giảm từ {workers}")
            workers = fit
    except ImportError:
        pass
    chunk = math.ceil(n_out / workers)
    log(f"dựng video: {n_out} khung {size[0]}x{size[1]} từ {len(times)} mẫu, {fps:g} fps, {workers} tiến trình, mã hoá {encoder}"
        + (f", ghim CPU {_in_game_cpus()} vì đang có trận" if _IN_GAME and _in_game_cpus() else ""))
    tmp_dir = tempfile.mkdtemp(prefix=TMP_PREFIX, dir=os.path.dirname(out_mp4) or None)
    with open(os.path.join(tmp_dir, OWNER_FILE), "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    parts = []
    procs = []
    job = {"procs": procs, "tmp_dir": tmp_dir, "aborted": False}
    with _ACTIVE_LOCK:
        _JOBS.append(job)
    try:
        return _run_chunks(job, rec_path, out_mp4, width, fps, speed, fog_dim, outline, game_dir, ffmpeg, encoder,
                           emulate, workers, chunk, n_out, times, log, progress, t_start)
    except BaseException:
        _kill_procs(procs)                   # lỗi hay huỷ: không để tiến trình đoạn (và ffmpeg của nó) chạy mồ côi
        _remove_tmp(tmp_dir)
        raise
    finally:
        with _ACTIVE_LOCK:
            if job in _JOBS:
                _JOBS.remove(job)


def _run_chunks(job, rec_path, out_mp4, width, fps, speed, fog_dim, outline, game_dir, ffmpeg, encoder, emulate,
                workers, chunk, n_out, times, log, progress, t_start):
    tmp_dir = job["tmp_dir"]
    parts = []
    procs = job["procs"]
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    for i in range(workers):
        k0, k1 = i * chunk, min(n_out, (i + 1) * chunk)
        if k0 >= k1:
            break
        part = os.path.join(tmp_dir, f"part{i:02d}.mp4")
        parts.append(part)
        if getattr(sys, "frozen", False):
            cmd = [sys.executable]
        else:
            cmd = [sys.executable, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "run_app.py")]
        cmd += ["--render-chunk", rec_path, part, str(k0), str(k1), str(width), str(fps), str(speed), str(fog_dim),
                str(outline), game_dir or "", ffmpeg, encoder, "1" if emulate else "0"]
        procs.append(subprocess.Popen(cmd, creationflags=flags | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)))
    tracker = _Progress(n_out, len(parts), t_start)
    t_ui = 0.0
    t_log = time.time()
    while True:
        alive = [p for p in procs if p.poll() is None]
        failed = [p for p in procs if p.poll() not in (None, 0)]
        if job.get("aborted"):
            raise RuntimeError("lượt dựng bị huỷ (chương trình thoát)")
        if failed:
            # dừng ngay, không chờ các đoạn khác chạy hết (có thể hàng chục phút) rồi mới báo
            detail = _child_error(tmp_dir)
            try:   # giữ lại traceback của tiến trình con cạnh video (thư mục tạm sẽ bị xoá)
                src = os.path.join(tmp_dir, CHILD_LOG)
                if os.path.isfile(src):
                    with open(os.path.join(os.path.dirname(tmp_dir), CHILD_LOG), "a", encoding="utf-8") as f:
                        f.write(open(src, encoding="utf-8", errors="replace").read())
            except OSError:
                pass
            raise RuntimeError(f"tiến trình dựng đoạn lỗi (mã {failed[0].returncode})"
                               + (f": {detail}" if detail else "; xem _mapcap_child.log"))
        now = time.time()
        if now - t_ui >= 1.0:
            t_ui = now
            _apply_affinity(job)
            frac, text = tracker.update([p + PROGRESS_EXT for p in parts])
            if progress:
                progress(frac, text)
            if now - t_log >= 60:
                t_log = now
                log(text)
        if not alive:
            break
        time.sleep(0.5)
    if progress:
        progress(1.0, "đang nối các đoạn video...")
    parts = [p for p in parts if os.path.isfile(p) and os.path.getsize(p) > 0]
    if not parts:
        raise RuntimeError("không có đoạn video nào được tạo")
    lst = os.path.join(tmp_dir, "list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for p in parts:
            f.write("file '" + p.replace("'", "'\\''") + "'\n")
    r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                        "-c", "copy", "-movflags", "+faststart", out_mp4], capture_output=True, creationflags=flags)
    if r.returncode != 0:
        raise RuntimeError("nối video lỗi: " + r.stderr.decode("utf-8", "replace")[-300:])
    _remove_tmp(tmp_dir)
    log(f"đã dựng {out_mp4} ({n_out} khung, {time.time() - t_start:.0f}s)")
    return out_mp4
