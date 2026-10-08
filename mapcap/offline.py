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

_ACTIVE = 0
_ACTIVE_LOCK = threading.Lock()
_JOBS = []          # các lượt dựng đang chạy: {"procs": [...], "tmp_dir": ...}
TMP_PREFIX = "aoerender_"
OWNER_FILE = "owner.pid"
CHILD_LOG = "_mapcap_child.log"


def active_renders():
    """Số lần dựng video (render_raw) đang chạy trong tiến trình này."""
    return _ACTIVE


def abort_all(log=None):
    """Tắt mọi tiến trình dựng đoạn đang chạy và xoá thư mục tạm của chúng (gọi khi thoát chương trình)."""
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
    dat = D.load(os.path.join(game_dir, "data", "empires.dat"))
    D.parse_units_by_scan(dat)
    store = SpriteStore(game_dir, palette)
    vr = VideoRenderer(dat, store, palette, width=width, fog_dim=fog_dim, log=lambda m: None, outline_alpha=outline)
    vr.emulate_ghosts = bool(emulate_ghosts)
    writer = None
    written = 0
    k = k0
    frame_bytes = None
    rd = RawReader(rec_path)
    for si, snap in enumerate(rd.frames()):
        if si < need_first:
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
        elif k < k1 and idx_map[k] < si:
            # mẫu cần đã qua (không xảy ra vì idx tăng dần), bỏ qua an toàn
            k += 1
    if writer is not None:
        writer.close()
    return written


def render_raw(rec_path, out_mp4, width=1920, fps=25.0, speed=1.0, fog_dim=0.43, outline=0.35, game_dir=None,
               workers=None, log=None, progress=None):
    """Dựng toàn bộ video: chia đoạn, chạy song song bằng chính exe/python này, nối bằng ffmpeg.
    Đếm số lần dựng đang chạy để giao diện biết khi nào thoát sẽ làm mất video."""
    global _ACTIVE
    with _ACTIVE_LOCK:
        _ACTIVE += 1
    try:
        return _render_raw_impl(rec_path, out_mp4, width, fps, speed, fog_dim, outline, game_dir, workers, log, progress)
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
    emulate = n_dop == 0
    log(f"bản ghi nhớ sương mù: {n_dop} doppelganger đọc từ game" if n_dop else
        "dữ liệu không có doppelganger của game: dùng mô phỏng công trình đã thấy")
    n_out = len(_frame_times(times, fps, speed))
    if workers is None:
        workers = max(1, min(8, (os.cpu_count() or 4) - 1))
    workers = max(1, min(workers, max(1, n_out // 200)))
    chunk = math.ceil(n_out / workers)
    log(f"dựng video: {n_out} khung {size[0]}x{size[1]} từ {len(times)} mẫu, {fps:g} fps, {workers} tiến trình, mã hoá {encoder}")
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
    done = 0
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
        d = len(procs) - len(alive)
        if d != done:
            done = d
            if progress:
                progress(done / len(procs))
        if not alive:
            break
        time.sleep(0.5)
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
