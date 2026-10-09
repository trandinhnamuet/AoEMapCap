"""Ghi dữ liệu thô trong một TIẾN TRÌNH riêng (GIL riêng) để luồng đọc game không tranh CPU với giao diện,
ghi file hay ảnh tĩnh của tiến trình chính.

Tiến trình con: mở bộ nhớ game theo pid, đọc snapshot theo nhịp capture_fps (kèm vật thể tĩnh, doppelganger),
ghi .aoerec, mỗi giây gửi thống kê về cha qua Pipe; nhận lệnh ("stop",) và ("still", tên) (gửi lại snapshot để cha
chụp ảnh tĩnh). Giao thức: tuple (loại, ...) qua multiprocessing.Connection.
"""
import multiprocessing as mp
import os
import pickle
import threading
import time


def recorder_main(conn, pid, cfg_dict, raw_path, game_dir):
    """Thân tiến trình con."""
    import psutil
    from .engine import Config, StaticObjects
    from .game import GameReader
    from .memory import MemoryError_, ProcessMemory
    from .rawrec import RawWriter

    def log(m):
        try:
            conn.send(("log", m))
        except Exception:  # noqa: BLE001
            pass

    try:
        try:
            pr = psutil.Process()
            pr.nice(psutil.ABOVE_NORMAL_PRIORITY_CLASS)   # tiến trình đọc cần nhịp đều
            # CPU lai (Intel P/E-core): Windows hay xếp tiến trình nền lên E-core chậm gấp đôi; ghim vào các CPU đầu
            # (P-core) nếu máy có >= 12 CPU logic.
            n_cpu = os.cpu_count() or 1
            if n_cpu >= 12:
                pr.cpu_affinity(list(range(min(8, n_cpu))))
        except Exception:  # noqa: BLE001
            pass
        cfg = Config(**cfg_dict)
        mem = ProcessMemory(pid)
        reader = GameReader(mem)
        statics = StaticObjects(reader, cfg.static_rescan_seconds, log, cfg.static_refresh_seconds)
        snap = reader.snapshot()
        statics.ensure_first(snap)
        statics.attach(snap)
        os.makedirs(os.path.dirname(raw_path), exist_ok=True)
        writer = RawWriter(raw_path)
        writer.start(snap, meta={"game_dir": game_dir, "capture_fps": cfg.capture_fps, "reader_process": True})
        interval = 1.0 / max(cfg.capture_fps, 1.0)
        nxt = time.time()
        written = 1
        read_t = []
        write_t = []
        snap_t = []
        cpu_t = []
        import queue
        wq = queue.Queue(maxsize=8)
        wstop = object()

        def writer_loop():
            while True:
                item = wq.get()
                if item is wstop:
                    return
                tw = time.time()
                try:
                    writer.add_frame(item)
                except Exception as e:  # noqa: BLE001
                    log(f"lỗi ghi mẫu: {e}")
                write_t.append(time.time() - tw)
        wthread = threading.Thread(target=writer_loop, daemon=True)
        wthread.start()
        try:
            pr = psutil.Process()
            log(f"tiến trình ghi pid {pr.pid}: ưu tiên {pr.nice()}, affinity {pr.cpu_affinity()}, luồng {pr.num_threads()}")
        except Exception as e:  # noqa: BLE001
            log(f"không đọc được thông tin tiến trình: {e}")
        last_stat = time.time()
        n_since = 0
        errors = 0
        running = True
        reason = "stop"
        while running:
            # lệnh từ cha
            while conn.poll():
                cmd = conn.recv()
                if cmd[0] == "stop":
                    running = False
                    break
                if cmd[0] == "still":
                    try:
                        conn.send(("still", cmd[1], snap))
                    except Exception as e:  # noqa: BLE001
                        log(f"không gửi được ảnh tĩnh: {e}")
            if not running:
                break
            t0 = time.time()
            c0 = time.process_time()
            try:
                snap = reader.snapshot()
                ts = time.time()
                cpu_t.append(time.process_time() - c0)
                statics.maybe_rescan(snap)
                statics.attach(snap)
                t1 = time.time()
                snap_t.append(ts - t0)
                wq.put(snap)                      # ghi ở luồng riêng (zlib nhả GIL) để không chặn lượt đọc kế
                read_t.append(t1 - t0)
                written += 1
                n_since += 1
            except MemoryError_ as e:
                errors += 1
                if errors <= 3 or errors % 100 == 0:
                    log(f"lỗi đọc bộ nhớ ({errors}): {e}")
                if not mem.alive():
                    log("game đã thoát, dừng ghi")
                    reason = "game_exit"
                    break
            now = time.time()
            if now - last_stat >= 1.0:
                span = now - last_stat
                conn.send(("stat", {
                    "written": written, "rate": n_since / span,
                    "read_ms": sum(read_t) / max(len(read_t), 1) * 1000, "write_ms": sum(write_t) / max(len(write_t), 1) * 1000,
                    "snap_ms": sum(snap_t) / max(len(snap_t), 1) * 1000, "cpu_ms": sum(cpu_t) / max(len(cpu_t), 1) * 1000, "threads": psutil.Process().num_threads(), "calls": reader.bulk.calls, "mb": reader.bulk.bytes / 1e6,
                    "game_ms": snap.time_ms, "dop": reader.doppels.count(), "dop_total": reader.doppels.found_total,
                    "units": len(snap.units), "errors": errors,
                }))
                read_t.clear()
                write_t.clear()
                snap_t.clear()
                cpu_t.clear()
                reader.bulk.calls = 0
                reader.bulk.bytes = 0
                n_since = 0
                last_stat = now
            nxt += interval
            delay = nxt - time.time()
            if delay > 0:
                time.sleep(delay)
            else:
                nxt = time.time()
        wq.put(wstop)
        wthread.join(30)
        n = writer.close(reason)
        conn.send(("done", n))
    except Exception as e:  # noqa: BLE001
        import traceback
        try:
            conn.send(("error", f"{e!r}\n{traceback.format_exc()[-600:]}"))
        except Exception:  # noqa: BLE001
            pass
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


class RecorderProcess:
    """Phía cha: khởi chạy/dừng tiến trình ghi, gom thống kê, chuyển ảnh tĩnh và log về."""

    def __init__(self, pid, cfg, raw_path, game_dir, log, on_still=None):
        self.pid = pid
        self.cfg = cfg
        self.raw_path = raw_path
        self.game_dir = game_dir
        self.log = log
        self.on_still = on_still
        self.stat = {"written": 0, "rate": 0.0, "read_ms": 0.0, "write_ms": 0.0, "game_ms": 0, "dop": 0, "dop_total": 0,
                     "units": 0, "errors": 0}
        self.stat_hist = []
        self.done_n = None
        self.error = None
        self.ctx = mp.get_context("spawn")
        self.parent_conn, self.child_conn = self.ctx.Pipe()
        self.proc = None
        self.thread = None
        self.lock = threading.Lock()

    def start(self):
        from dataclasses import asdict
        self.proc = self.ctx.Process(target=recorder_main, name="aoe-recorder",
                                     args=(self.child_conn, self.pid, asdict(self.cfg), self.raw_path, self.game_dir), daemon=True)
        self.proc.start()
        self.child_conn.close()
        self.thread = threading.Thread(target=self._drain, daemon=True)
        self.thread.start()

    def _drain(self):
        while True:
            try:
                msg = self.parent_conn.recv()
            except (EOFError, OSError):
                break
            kind = msg[0]
            if kind == "stat":
                with self.lock:
                    self.stat = msg[1]
                    self.stat_hist.append(msg[1])
                    if len(self.stat_hist) > 600:
                        del self.stat_hist[:300]
            elif kind == "log":
                self.log(msg[1])
            elif kind == "still":
                if self.on_still:
                    try:
                        self.on_still(msg[1], msg[2])
                    except Exception as e:  # noqa: BLE001
                        self.log(f"lỗi ảnh tĩnh: {e}")
            elif kind == "done":
                self.done_n = msg[1]
            elif kind == "error":
                self.error = msg[1]
                self.log(f"tiến trình ghi lỗi: {msg[1]}")

    def request_still(self, name):
        try:
            self.parent_conn.send(("still", name))
        except Exception as e:  # noqa: BLE001
            self.log(f"không yêu cầu được ảnh tĩnh: {e}")

    def alive(self):
        return self.proc is not None and self.proc.is_alive()

    def stop(self, timeout=30.0):
        """Gửi lệnh dừng, chờ tiến trình chốt file. Trả về số mẫu đã ghi (None nếu không rõ)."""
        if self.proc is None:
            return None
        try:
            self.parent_conn.send(("stop",))
        except Exception:  # noqa: BLE001
            pass
        self.proc.join(timeout)
        if self.proc.is_alive():
            self.log("tiến trình ghi không dừng kịp, buộc dừng")
            self.proc.terminate()
            self.proc.join(5)
        try:
            self.parent_conn.close()
        except Exception:  # noqa: BLE001
            pass
        if self.thread:
            self.thread.join(5)
        return self.done_n if self.done_n is not None else self.stat.get("written")

    def minute_summary(self, n_last):
        """Trung bình các thống kê 1 giây gần nhất."""
        with self.lock:
            h = self.stat_hist[-n_last:] if n_last > 0 else []
        if not h:
            return self.stat
        avg = dict(self.stat)
        for k in ("rate", "read_ms", "write_ms", "snap_ms", "calls", "mb", "cpu_ms"):
            if k not in h[0]:
                continue
            avg[k] = sum(s[k] for s in h) / len(h)
        return avg
