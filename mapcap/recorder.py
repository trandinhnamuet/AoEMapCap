"""Ghi video diễn biến trận: đẩy khung RGB vào ffmpeg qua pipe, chốt file khi hết trận."""
import datetime as dt
import os
import queue
import shutil
import subprocess
import sys
import threading
import time

import numpy as np


def find_ffmpeg(extra_dirs=()):
    cands = []
    meipass = getattr(sys, "_MEIPASS", None)          # ffmpeg gói trong exe (PyInstaller onefile)
    if meipass:
        cands.append(os.path.join(meipass, "ffmpeg.exe"))
    exe_dir = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
    cands.append(os.path.join(exe_dir, "ffmpeg.exe"))
    cands.append(os.path.join(os.path.dirname(exe_dir), "ffmpeg.exe"))
    cands.append(os.path.join(os.path.dirname(exe_dir), "vendor", "ffmpeg.exe"))
    for d in extra_dirs:
        cands.append(os.path.join(d, "ffmpeg.exe"))
    for c in cands:
        if os.path.isfile(c):
            return c
    return shutil.which("ffmpeg")


def pick_encoder(ffmpeg, prefer=("h264_nvenc", "h264_qsv", "h264_amf", "libx264"), log=None, size=(64, 64)):
    """Chọn bộ mã hoá đầu tiên thật sự mã hoá được khung thử ĐÚNG KÍCH THƯỚC `size` (driver GPU có thể không hoạt
    động; Quick Sync/NVENC từ chối khung rộng hơn 4096 px nên khi dựng ở 9216 px phải rơi về libx264)."""
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return "libx264"
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    w = max(2, int(size[0]) // 2 * 2)
    h = max(2, int(size[1]) // 2 * 2)
    frame = bytes(w * h * 3)
    for enc in prefer:
        if f" {enc} " not in out:
            continue
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{w}x{h}", "-r", "4", "-i", "-", *ENCODER_ARGS.get(enc, ENCODER_ARGS["libx264"]),
               "-pix_fmt", "yuv420p", "-f", "null", "-"]
        try:
            r = subprocess.run(cmd, input=frame * 2, capture_output=True, timeout=180, creationflags=flags)
            if r.returncode == 0:
                return enc
            if log:
                log(f"bỏ {enc} ở {w}x{h}: {r.stderr.decode('utf-8', 'replace').strip().splitlines()[-1:]}")
        except Exception as e:  # noqa: BLE001
            if log:
                log(f"bỏ {enc}: {e}")
    return "libx264"


ENCODER_ARGS = {
    "h264_nvenc": ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "23", "-b:v", "0"],
    "h264_qsv": ["-c:v", "h264_qsv", "-global_quality", "23"],
    "h264_amf": ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp", "-qp_i", "23", "-qp_p", "23"],
    "libx264": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-threads", "2"],
}


def recover_partials(ffmpeg, video_dir, log=None):
    """Đóng gói lại các file .part.mp4 còn sót do lần chạy trước bị tắt đột ngột."""
    log = log or (lambda m: None)
    if not ffmpeg or not os.path.isdir(video_dir):
        return 0
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    n = 0
    for name in sorted(os.listdir(video_dir)):
        if not name.lower().endswith(".part.mp4"):
            continue
        src = os.path.join(video_dir, name)
        dst = os.path.join(video_dir, name[:-len(".part.mp4")] + ".mp4")
        if os.path.getsize(src) == 0:
            os.remove(src)
            continue
        try:
            r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", src,
                                "-c", "copy", "-movflags", "+faststart", dst],
                               capture_output=True, timeout=300, creationflags=flags)
            if r.returncode == 0 and os.path.getsize(dst) > 0:
                os.remove(src)
                log(f"đã cứu video dở dang: {os.path.basename(dst)}")
                n += 1
        except Exception as e:  # noqa: BLE001
            log(f"không cứu được {name}: {e}")
    return n


class VideoWriter:
    def __init__(self, ffmpeg, path, size, fps, encoder="libx264", log=None):
        self.ffmpeg = ffmpeg
        self.final_path = path
        self.path = path[:-4] + ".part.mp4" if path.lower().endswith(".mp4") else path + ".part"
        self.size = size
        self.fps = fps
        self.log = log or (lambda m: None)
        self.frames = 0
        w, h = size
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", f"{fps}", "-i", "-",
               *ENCODER_ARGS.get(encoder, ENCODER_ARGS["libx264"]),
               "-pix_fmt", "yuv420p", "-movflags", "+frag_keyframe+empty_moov+default_base_moof", self.path]
        # ghi dạng mp4 phân mảnh: nếu tắt đột ngột thì file .part.mp4 vẫn còn xem được
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
        self.encoder = encoder

    def write(self, frame):
        """frame: PIL Image RGB, numpy RGB hoặc bytes RGB24."""
        if self.proc.poll() is not None:
            raise RuntimeError("ffmpeg đã thoát: " + self._err())
        if isinstance(frame, (bytes, bytearray)):
            data = frame
        elif hasattr(frame, "tobytes") and not isinstance(frame, np.ndarray):
            data = frame.tobytes()
        else:
            data = np.ascontiguousarray(frame, dtype=np.uint8).tobytes()
        try:
            self.proc.stdin.write(data)
        except OSError as e:  # BrokenPipe: ffmpeg đã chết (encoder từ chối kích thước, hết đĩa, ...)
            err = self._err().strip() or str(e)
            raise RuntimeError(f"ffmpeg ({self.encoder}) thoát khi đang nhận khung {self.size[0]}x{self.size[1]}: {err[-400:]}")
        self.frames += 1

    def _err(self):
        try:
            return self.proc.stderr.read().decode("utf-8", "replace")[-800:]
        except Exception:
            return ""

    def close(self):
        if self.proc.poll() is None:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
            try:
                self.proc.wait(timeout=120)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        err = self._err()
        if err.strip():
            self.log("ffmpeg: " + err.strip())
        self._finalize()
        return self.frames

    def _finalize(self):
        """Đóng gói lại thành mp4 chuẩn (có bảng chỉ mục) để Windows Explorer và mọi trình phát đọc được."""
        if self.path == self.final_path or not os.path.isfile(self.path):
            return
        if os.path.getsize(self.path) == 0:
            os.remove(self.path)
            return
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", self.path,
               "-c", "copy", "-movflags", "+faststart", self.final_path]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=300, creationflags=flags)
            if r.returncode == 0 and os.path.isfile(self.final_path) and os.path.getsize(self.final_path) > 0:
                os.remove(self.path)
                return
            self.log("không đóng gói lại được: " + r.stderr.decode("utf-8", "replace").strip()[-300:])
        except Exception as e:  # noqa: BLE001
            self.log(f"không đóng gói lại được: {e}")
        # thất bại: giữ nguyên file phân mảnh dưới tên cuối
        try:
            if os.path.isfile(self.final_path):
                os.remove(self.final_path)
            os.replace(self.path, self.final_path)
        except Exception:  # noqa: BLE001
            self.final_path = self.path


class MatchRecorder:
    """Một phiên ghi cho một trận: nhận snapshot theo nhịp, vẽ, ghi ra file video."""

    def __init__(self, renderer, ffmpeg, encoder, out_dir, fps=4.0, speed=1.0, label="tran", log=None):
        self.renderer = renderer
        self.ffmpeg = ffmpeg
        self.encoder = encoder
        self.out_dir = out_dir
        self.fps = fps
        self.speed = speed
        self.label = label
        self.log = log or (lambda m: None)
        self.writer = None
        self.start_real = None
        self.written = 0
        self.last_frame = None
        self.render_times = []
        self.dropped = 0
        self.path = None
        self._queue = None
        self._writer_thread = None
        self._writer_err = None

    @staticmethod
    def _to_bytes(frame):
        if isinstance(frame, (bytes, bytearray)):
            return frame
        if hasattr(frame, "tobytes") and not isinstance(frame, np.ndarray):
            return frame.tobytes()
        return np.ascontiguousarray(frame, dtype=np.uint8).tobytes()

    @staticmethod
    def _size_of(frame):
        if isinstance(frame, np.ndarray):
            return frame.shape[1], frame.shape[0]
        return frame.size

    def start(self, snap):
        self.renderer.reset()
        frame = self.renderer.render(snap)
        os.makedirs(self.out_dir, exist_ok=True)
        self.path = os.path.join(self.out_dir, f"{dt.datetime.now():%Y-%m-%d_%H%M%S}_{self.label}.mp4")
        w, h = self._size_of(frame)
        self.writer = VideoWriter(self.ffmpeg, self.path, (w, h), self.fps * self.speed, self.encoder, self.log)
        self.last_frame = self._to_bytes(frame)
        self._queue = queue.Queue(maxsize=8)
        self._writer_err = None
        self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer_thread.start()
        self._enqueue(self.last_frame)
        self.written = 1
        self.start_real = time.time()
        self.log(f"bắt đầu ghi {self.path} ({w}x{h}, video {self.fps:g} khung/giây, phát x{self.speed:g}, {self.encoder})")

    def _writer_loop(self):
        while True:
            item = self._queue.get()
            if item is None:
                return
            try:
                self.writer.write(item)
            except Exception as e:  # noqa: BLE001
                self._writer_err = e
                return

    def _enqueue(self, data):
        if self._writer_err is not None:
            raise RuntimeError(str(self._writer_err))
        try:
            self._queue.put(data, timeout=5)
        except queue.Full:
            raise RuntimeError("ffmpeg không nhận kịp khung hình")

    def due_frames(self):
        """Số khung video phải có cho tới lúc này theo thời gian thật."""
        return int((time.time() - self.start_real) * self.fps) + 1

    def tick(self, snap):
        t0 = time.time()
        frame = self.renderer.render(snap)
        self.render_times.append(time.time() - t0)
        data = self._to_bytes(frame)
        # lấp các nhịp đã trôi qua bằng khung trước (giữ video đúng thời gian thật)
        due = self.due_frames()
        while self.written < due - 1:
            self._enqueue(self.last_frame)
            self.written += 1
            self.dropped += 1
        self._enqueue(data)
        self.written += 1
        self.last_frame = data

    def stop(self):
        if self.writer is None:
            return None
        try:
            self._queue.put(None, timeout=10)
            self._writer_thread.join(timeout=60)
        except Exception:  # noqa: BLE001
            pass
        n = self.writer.close()
        self.path = self.writer.final_path
        dur = n / (self.fps * self.speed)
        rt = self.render_times
        avg = (sum(rt) / len(rt)) if rt else 0
        self.log(f"đã chốt {self.path}: {n} khung, {dur:.0f}s video, vẽ trung bình {avg*1000:.0f} ms/khung, "
                 f"{self.dropped} khung lấp")
        self.writer = None
        return self.path
