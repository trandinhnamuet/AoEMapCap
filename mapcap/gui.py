"""Giao diện điều khiển AoE-MapCap Recorder (tkinter)."""
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .engine import Config, Engine, Logger, load_config, save_config

APP_TITLE = "AoE-MapCap Recorder"


def app_icon_path():
    """assets/app.ico: gói trong exe (_MEIPASS) hoặc thư mục mã nguồn."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(base, "assets", "app.ico")
    return p if os.path.exists(p) else ""


class App:
    def __init__(self, root):
        self.root = root
        root.title(APP_TITLE)
        root.minsize(560, 520)
        try:
            root.iconbitmap(default=app_icon_path())
        except Exception:  # noqa: BLE001
            pass
        self.cfg = load_config()
        self.q = queue.Queue()
        self.engine = None
        self.thread = None
        self.stop_event = None
        self._build()
        self.root.after(200, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- giao diện ---------------------------------------------------------------
    def _build(self):
        pad = {"padx": 8, "pady": 4}
        frm = ttk.LabelFrame(self.root, text="Tuỳ chọn")
        frm.pack(fill="x", padx=10, pady=8)

        self.var_fps = tk.IntVar(value=int(self.cfg.fps))
        self.var_cap = tk.IntVar(value=int(self.cfg.capture_fps))
        self.var_width = tk.IntVar(value=int(self.cfg.video_width))
        self.var_speed = tk.DoubleVar(value=self.cfg.speed)
        self.var_outline = tk.BooleanVar(value=self.cfg.map_outline > 0)
        self.var_fog = tk.StringVar(value="Lưới chấm như game" if self.cfg.fog_style == "dither" else "Làm tối đều")
        self.var_video = tk.BooleanVar(value=self.cfg.record_video)
        self.var_mode = tk.StringVar(value="Ghi dữ liệu thô, dựng video sau trận" if self.cfg.record_mode == "raw" else "Vẽ video ngay trong trận")
        self.var_rwidth = tk.IntVar(value=int(self.cfg.render_width))
        self.var_keep_raw = tk.BooleanVar(value=self.cfg.keep_raw)
        self.var_stills = tk.DoubleVar(value=self.cfg.stills_interval)
        self.var_out = tk.StringVar(value=self.cfg.resolved_out_dir())
        self.var_enc = tk.StringVar(value=self.cfg.encoder)

        r = 0
        ttk.Label(frm, text="FPS video (file mp4)").grid(row=r, column=0, sticky="w", **pad)
        ttk.Spinbox(frm, from_=1, to=60, textvariable=self.var_fps, width=8).grid(row=r, column=1, sticky="w", **pad)
        ttk.Label(frm, text="Nhịp đọc game (lần/giây)").grid(row=r, column=2, sticky="w", **pad)
        ttk.Spinbox(frm, from_=1, to=60, textvariable=self.var_cap, width=8).grid(row=r, column=3, sticky="w", **pad)
        r += 1
        ttk.Label(frm, text="Độ rộng video (px)").grid(row=r, column=0, sticky="w", **pad)
        ttk.Combobox(frm, values=(1280, 1600, 1920, 2560, 3840), textvariable=self.var_width, width=7).grid(row=r, column=1, sticky="w", **pad)
        ttk.Label(frm, text="Tua nhanh khi phát").grid(row=r, column=2, sticky="w", **pad)
        ttk.Combobox(frm, values=(1, 2, 4, 8, 16), textvariable=self.var_speed, width=7).grid(row=r, column=3, sticky="w", **pad)
        r += 1
        ttk.Label(frm, text="Ảnh tĩnh mỗi (phút game, 0 = tắt)").grid(row=r, column=0, sticky="w", **pad)
        ttk.Spinbox(frm, from_=0, to=60, increment=1, textvariable=self.var_stills, width=8).grid(row=r, column=1, sticky="w", **pad)
        ttk.Label(frm, text="Mã hoá").grid(row=r, column=2, sticky="w", **pad)
        ttk.Combobox(frm, values=("auto", "h264_nvenc", "h264_qsv", "h264_amf", "libx264"), textvariable=self.var_enc, width=11).grid(row=r, column=3, sticky="w", **pad)
        r += 1
        ttk.Checkbutton(frm, text="Ghi video", variable=self.var_video).grid(row=r, column=0, sticky="w", **pad)
        ttk.Checkbutton(frm, text="Viền trắng mờ quanh bản đồ", variable=self.var_outline).grid(row=r, column=1, columnspan=2, sticky="w", **pad)
        r += 1
        ttk.Label(frm, text="Sương mù").grid(row=r, column=0, sticky="w", **pad)
        ttk.Combobox(frm, values=("Làm tối đều", "Lưới chấm như game"), textvariable=self.var_fog, width=20,
                     state="readonly").grid(row=r, column=1, columnspan=2, sticky="w", **pad)
        r += 1
        ttk.Label(frm, text="Chế độ").grid(row=r, column=0, sticky="w", **pad)
        ttk.Combobox(frm, values=("Ghi dữ liệu thô, dựng video sau trận", "Vẽ video ngay trong trận"),
                     textvariable=self.var_mode, width=34, state="readonly").grid(row=r, column=1, columnspan=2, sticky="w", **pad)
        r += 1
        ttk.Label(frm, text="Độ rộng video dựng sau trận").grid(row=r, column=0, sticky="w", **pad)
        ttk.Combobox(frm, values=(1920, 2560, 3840, 9216), textvariable=self.var_rwidth, width=7).grid(row=r, column=1, sticky="w", **pad)
        ttk.Checkbutton(frm, text="Giữ file dữ liệu thô", variable=self.var_keep_raw).grid(row=r, column=2, columnspan=2, sticky="w", **pad)
        r += 1
        ttk.Label(frm, text="Thư mục lưu").grid(row=r, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.var_out, width=44).grid(row=r, column=1, columnspan=2, sticky="we", **pad)
        ttk.Button(frm, text="Chọn...", command=self._choose_dir, width=8).grid(row=r, column=3, sticky="w", **pad)
        frm.columnconfigure(1, weight=1)

        ctl = ttk.Frame(self.root)
        ctl.pack(fill="x", padx=10, pady=4)
        self.btn_start = ttk.Button(ctl, text="Bắt đầu ghi", command=self._start, width=16)
        self.btn_start.pack(side="left", padx=4)
        self.btn_stop = ttk.Button(ctl, text="Dừng", command=self._stop, width=10, state="disabled")
        self.btn_stop.pack(side="left", padx=4)
        ttk.Button(ctl, text="Mở thư mục video", command=self._open_dir).pack(side="left", padx=4)
        ttk.Button(ctl, text="Dựng lại video...", command=self._rerender).pack(side="left", padx=4)
        self.lbl_status = ttk.Label(ctl, text="Trạng thái: chưa chạy", foreground="#555")
        self.lbl_status.pack(side="right", padx=6)

        note = ttk.Label(self.root, foreground="#666", wraplength=540, justify="left",
                         text="Chế độ dữ liệu thô: trong trận chỉ đọc game (nhẹ nhất), hết trận tự dựng video ở độ rộng đã chọn; "
                              "file .aoerec trong Video\\Raw dựng lại được bất cứ lúc nào. "
                              "nhịp đọc = số lần đọc game và vẽ mỗi giây (nên bằng FPS để mượt; mỗi lần vẽ ~15 ms ở 1080p). "
                              "Hết trận (rời ra menu, thoát game, hoặc đồng hồ game đứng 3 phút) tự chốt file mp4.")
        note.pack(fill="x", padx=12, pady=2)

        logf = ttk.LabelFrame(self.root, text="Nhật ký")
        logf.pack(fill="both", expand=True, padx=10, pady=8)
        self.txt = tk.Text(logf, height=14, wrap="word", state="disabled", font=("Consolas", 9))
        sb = ttk.Scrollbar(logf, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        self.txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    # ---- hành động ----------------------------------------------------------------
    def _collect(self):
        cfg = self.cfg
        try:
            cfg.fps = float(self.var_fps.get())
            cfg.capture_fps = float(self.var_cap.get())
            cfg.video_width = int(self.var_width.get())
            cfg.speed = float(self.var_speed.get())
            cfg.stills_interval = float(self.var_stills.get())
        except (tk.TclError, ValueError) as e:
            messagebox.showerror(APP_TITLE, f"Giá trị không hợp lệ: {e}")
            return None
        cfg.record_video = bool(self.var_video.get())
        cfg.record_mode = "raw" if self.var_mode.get().startswith("Ghi") else "live"
        try:
            cfg.render_width = int(self.var_rwidth.get())
        except (tk.TclError, ValueError):
            cfg.render_width = 1920
        cfg.keep_raw = bool(self.var_keep_raw.get())
        cfg.map_outline = 0.35 if self.var_outline.get() else 0.0
        cfg.fog_style = "dither" if self.var_fog.get().startswith("Lưới") else "dim"
        cfg.encoder = self.var_enc.get() or "auto"
        out = self.var_out.get().strip()
        cfg.out_dir = "" if os.path.normcase(out) == os.path.normcase(Config().resolved_out_dir()) else out
        cfg.clamp()
        # phản ánh lại giá trị đã giới hạn
        self.var_fps.set(int(cfg.fps)); self.var_cap.set(int(cfg.capture_fps))
        return cfg

    def _start(self):
        cfg = self._collect()
        if cfg is None:
            return
        try:
            save_config(cfg)
        except Exception as e:  # noqa: BLE001
            self._append(f"không lưu được cấu hình: {e}")
        self.stop_event = threading.Event()
        logger = Logger(cfg.log_path(), callback=self.q.put)
        self.engine = Engine(cfg, logger, self.stop_event, status=lambda s: self.q.put(("__status__", s)))
        self.thread = threading.Thread(target=self._run_engine, daemon=True)
        self.thread.start()
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self._append(f"=== bắt đầu: FPS video {int(cfg.fps)}, nhịp đọc {int(cfg.capture_fps)}/s, rộng {cfg.video_width}px, "
                     f"tua x{cfg.speed:g}, lưu tại {cfg.resolved_out_dir()}")

    def _run_engine(self):
        try:
            self.engine.run()
        except Exception as e:  # noqa: BLE001
            import traceback
            self.q.put("LỖI: " + str(e))
            self.q.put(traceback.format_exc()[-1500:])
        finally:
            self.q.put(("__done__", None))

    def _stop(self):
        if self.stop_event:
            self.stop_event.set()
            self._append("đang dừng, chờ chốt video...")
            self.btn_stop.configure(state="disabled")

    def _choose_dir(self):
        d = filedialog.askdirectory(initialdir=self.var_out.get() or os.getcwd(), title="Chọn thư mục lưu video")
        if d:
            self.var_out.set(os.path.normpath(d))

    def _rerender(self):
        """Chọn file .aoerec và dựng lại video với độ rộng/FPS/tốc độ hiện chọn trên giao diện."""
        cfg = self._collect()
        if cfg is None:
            return
        raw_dir = cfg.raw_dir()
        os.makedirs(raw_dir, exist_ok=True)
        path = filedialog.askopenfilename(initialdir=raw_dir, title="Chọn dữ liệu thô của trận",
                                          filetypes=[("Dữ liệu thô AoE-MapCap", "*.aoerec"), ("Tất cả", "*.*")])
        if not path:
            return
        out = os.path.join(cfg.resolved_out_dir(),
                           f"{os.path.splitext(os.path.basename(path))[0]}_{cfg.render_width}px_{int(cfg.fps)}fps"
                           f"{'' if cfg.speed == 1 else f'_x{cfg.speed:g}'}.mp4")
        self._append(f"=== dựng lại {os.path.basename(path)} -> {os.path.basename(out)}")

        def job():
            from .offline import render_raw, cleanup_stale
            try:
                cleanup_stale(cfg.resolved_out_dir(), log=self.q.put)
                render_raw(path, out, width=cfg.render_width, fps=cfg.fps, speed=cfg.speed, fog_dim=cfg.fog_param(),
                           outline=cfg.map_outline, game_dir=cfg.game_dir, workers=cfg.render_workers or None,
                           log=self.q.put, progress=lambda f: self.q.put(("__status__", f"đang dựng {int(f*100)}%")))
                self.q.put(("__status__", "dựng xong"))
            except Exception as e:  # noqa: BLE001
                self.q.put(f"lỗi dựng lại: {e}")
        threading.Thread(target=job, daemon=True).start()

    def _open_dir(self):
        d = self.var_out.get() or Config().resolved_out_dir()
        os.makedirs(d, exist_ok=True)
        try:
            os.startfile(d)  # noqa: S606
        except Exception:  # noqa: BLE001
            subprocess.Popen(["explorer", d])

    # ---- nhật ký ------------------------------------------------------------------
    def _append(self, line):
        self.txt.configure(state="normal")
        self.txt.insert("end", line + "\n")
        n = int(self.txt.index("end-1c").split(".")[0])
        if n > 400:
            self.txt.delete("1.0", f"{n - 400}.0")
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                if isinstance(item, tuple):
                    kind, val = item
                    if kind == "__status__":
                        self.lbl_status.configure(text=f"Trạng thái: {val}")
                    elif kind == "__done__":
                        self.btn_start.configure(state="normal")
                        self.btn_stop.configure(state="disabled")
                        self.lbl_status.configure(text="Trạng thái: đã dừng")
                        self.engine = None
                else:
                    self._append(item)
                    if "lỗi dựng" in item:        # dựng video thất bại: báo rõ, không để người dùng chờ
                        self.lbl_status.configure(text="Trạng thái: dựng video LỖI")
                        messagebox.showerror(APP_TITLE, item)
        except queue.Empty:
            pass
        self.root.after(200, self._poll)

    def _on_close(self):
        from .offline import active_renders
        running = self.engine is not None and self.thread is not None and self.thread.is_alive()
        recording = running and getattr(self.engine, "state", "") == "đang ghi"
        rendering = active_renders() > 0
        if recording and rendering:
            msg = "Đang ghi trận và đang dựng video. Thoát sẽ chốt dữ liệu thô nhưng video đang dựng sẽ dở dang. Thoát?"
        elif recording:
            msg = "Đang ghi trận. Dừng, chốt dữ liệu rồi thoát?"
        elif rendering:
            msg = "Đang dựng video. Thoát bây giờ sẽ mất video đang dựng (có thể dựng lại từ file thô). Thoát?"
        else:
            msg = None
        if msg and not messagebox.askyesno(APP_TITLE, msg):
            return
        if rendering:
            from .offline import abort_all
            abort_all()                     # tắt tiến trình đoạn, xoá thư mục tạm aoerender_*
        if running:
            self.stop_event.set()
            self.thread.join(timeout=30 if recording else 5)
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.25)
    except Exception:  # noqa: BLE001
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
