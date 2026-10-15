"""Giao diện AoE-MapCap (tkinter): ghi trận và xem replay là chính; xuất video là tuỳ chọn.

Bố cục: thanh trên (trạng thái, Bắt đầu ghi / Dừng) + ba thẻ:
  Trận đã ghi : bảng trận (replay.picker.MatchTable) -> Xem replay / Xuất video... / Mở file khác / Mở thư mục
  Cài đặt     : ghi trận (nhịp đọc, thư mục lưu) và xuất video (tự xuất sau trận, độ rộng, FPS, ...)
  Nhật ký     : log của bộ ghi và các lượt xuất video
"""
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .engine import Config, Engine, Logger, load_config, save_config
from .version import APP_VERSION

APP_TITLE = "AoE-MapCap"


def app_icon_path():
    """assets/app.ico: gói trong exe (_MEIPASS) hoặc thư mục mã nguồn."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(base, "assets", "app.ico")
    return p if os.path.exists(p) else ""


FOG_LABELS = ("Làm tối đều", "Lưới chấm như game")


class ExportDialog:
    """Hộp thoại xuất video cho một trận: độ rộng, FPS, tua nhanh, sương mù, viền, mã hoá."""

    def __init__(self, app, path):
        self.app = app
        self.path = path
        cfg = app.cfg
        top = self.top = tk.Toplevel(app.root)
        top.title("Xuất video — " + os.path.basename(path))
        top.transient(app.root)
        top.resizable(False, False)
        try:
            top.iconbitmap(app_icon_path())
        except Exception:  # noqa: BLE001
            pass
        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(top)
        frm.pack(fill="both", padx=12, pady=10)
        self.v_width = tk.IntVar(value=int(cfg.render_width))
        self.v_fps = tk.IntVar(value=int(cfg.fps))
        self.v_speed = tk.DoubleVar(value=cfg.speed)
        self.v_fog = tk.StringVar(value=FOG_LABELS[1] if cfg.fog_style == "dither" else FOG_LABELS[0])
        self.v_outline = tk.BooleanVar(value=cfg.map_outline > 0)
        self.v_enc = tk.StringVar(value=cfg.encoder)
        rows = [
            ("Độ rộng video (px)", ttk.Combobox(frm, values=(1920, 2560, 3840, 9216), textvariable=self.v_width, width=10)),
            ("FPS", ttk.Spinbox(frm, from_=1, to=60, textvariable=self.v_fps, width=8)),
            ("Tua nhanh (1 = thời gian thật)", ttk.Combobox(frm, values=(1, 2, 4, 8, 16), textvariable=self.v_speed, width=10)),
            ("Sương mù", ttk.Combobox(frm, values=FOG_LABELS, textvariable=self.v_fog, width=20, state="readonly")),
            ("Mã hoá", ttk.Combobox(frm, values=("auto", "h264_nvenc", "h264_qsv", "h264_amf", "libx264"),
                                    textvariable=self.v_enc, width=12)),
        ]
        for r, (label, widget) in enumerate(rows):
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", **pad)
            widget.grid(row=r, column=1, sticky="w", **pad)
        ttk.Checkbutton(frm, text="Viền trắng mờ quanh bản đồ", variable=self.v_outline).grid(
            row=len(rows), column=0, columnspan=2, sticky="w", **pad)
        ttk.Label(frm, foreground="#666", wraplength=380, justify="left",
                  text="9216 = kích cỡ gốc của game (rất nặng, chỉ libx264). Video lưu vào thư mục Video, "
                       "tiến độ hiện ở thanh trạng thái.").grid(row=len(rows) + 1, column=0, columnspan=2, sticky="w", **pad)
        bot = ttk.Frame(top)
        bot.pack(fill="x", padx=12, pady=(0, 10))
        ttk.Button(bot, text="Huỷ", command=top.destroy).pack(side="right", padx=4)
        ttk.Button(bot, text="Xuất video", command=self._ok).pack(side="right", padx=4)
        top.grab_set()

    def _ok(self):
        cfg = self.app.cfg
        try:
            cfg.render_width = int(self.v_width.get())
            cfg.fps = float(self.v_fps.get())
            cfg.speed = float(self.v_speed.get())
        except (tk.TclError, ValueError) as e:
            messagebox.showerror(APP_TITLE, f"Giá trị không hợp lệ: {e}", parent=self.top)
            return
        cfg.fog_style = "dither" if self.v_fog.get() == FOG_LABELS[1] else "dim"
        cfg.map_outline = 0.35 if self.v_outline.get() else 0.0
        cfg.encoder = self.v_enc.get() or "auto"
        cfg.clamp()
        self.app._save_cfg()
        self.app._sync_settings_from_cfg()
        self.top.destroy()
        self.app.export_video(self.path)


class App:
    def __init__(self, root):
        self.root = root
        root.title(f"{APP_TITLE} v{APP_VERSION} — ghi trận và xem replay")
        root.minsize(900, 560)
        root.geometry("1080x640")
        try:
            root.iconbitmap(default=app_icon_path())
        except Exception:  # noqa: BLE001
            pass
        self.cfg = load_config()
        self.q = queue.Queue()
        self.state_text = "chưa ghi"
        self.renders = {}            # label -> dòng tiến độ của lượt xuất video đang chạy
        self.engine = None
        self.thread = None
        self.stop_event = None
        self._build()
        self.root.after(200, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        from .update_ui import UpdateController
        self._restart_recording = False
        self.updater = UpdateController(root, root, "mapcap", APP_TITLE, log=lambda m: self.q.put("cập nhật: " + m),
                                        is_busy=self._busy_reason, before_restart=self._before_update_restart,
                                        restart_args=lambda: ["--autostart"] if self._restart_recording else [],
                                        bar_before=self.nb, on_block=self._on_update_block)
        self.updater.start()
        from . import telemetry                         # thống kê sử dụng: một lượt mỗi lần mở app (có mạng)
        telemetry.send("mapcap", "open", self.cfg.telemetry)

    # ---- giao diện ---------------------------------------------------------------
    def _build(self):
        style = ttk.Style()
        try:
            style.configure("Big.TButton", font=("Segoe UI", 11, "bold"), padding=(14, 6))
            style.configure("Title.TLabel", font=("Segoe UI", 15, "bold"))
        except tk.TclError:
            pass
        head = ttk.Frame(self.root)
        head.pack(fill="x", padx=12, pady=(10, 4))
        ttk.Label(head, text=f"AoE-MapCap v{APP_VERSION}", style="Title.TLabel").pack(side="left")
        self.btn_stop = ttk.Button(head, text="■ Dừng ghi", command=self._stop, state="disabled")
        self.btn_stop.pack(side="right", padx=4)
        self.btn_start = ttk.Button(head, text="● Bắt đầu ghi", style="Big.TButton", command=self._start)
        self.btn_start.pack(side="right", padx=4)
        self.lbl_status = ttk.Label(head, text="Trạng thái: chưa ghi", foreground="#555")
        self.lbl_status.pack(side="left", padx=16)

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=12, pady=(4, 10))
        self._build_matches()
        self._build_settings()
        self._build_log()

    def _build_matches(self):
        from replay.picker import MatchTable
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  Trận đã ghi  ")
        raw_dir = self.cfg.raw_dir()
        os.makedirs(raw_dir, exist_ok=True)
        self.table = MatchTable(tab, raw_dir, self._launch_replay, show_dir_button=False)
        self.table.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        bot = ttk.Frame(tab)
        bot.pack(fill="x", padx=8, pady=(4, 8))
        ttk.Button(bot, text="▶ Xem replay", style="Big.TButton", command=self.table.open_selected).pack(side="left")
        ttk.Button(bot, text="Xuất video...", command=self._export_selected).pack(side="left", padx=8)
        ttk.Button(bot, text="Mở file khác...", command=self._open_other).pack(side="left")
        ttk.Button(bot, text="Mở thư mục", command=self._open_dir).pack(side="left", padx=8)
        ttk.Button(bot, text="Xoá trận", command=self.table.delete_selected).pack(side="left")
        ttk.Button(bot, text="Nén trận cũ", command=self._compact_old).pack(side="left", padx=8)
        self.table.is_busy = self._is_recording_path
        ttk.Label(bot, textvariable=self.table.var_status, foreground="#666").pack(side="right")

    def _build_settings(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  Cài đặt  ")
        pad = {"padx": 8, "pady": 4}
        cfg = self.cfg
        self.var_cap = tk.IntVar(value=int(cfg.capture_fps))
        self.var_out = tk.StringVar(value=cfg.resolved_out_dir())
        self.var_render_after = tk.BooleanVar(value=cfg.render_after)
        self.var_rwidth = tk.IntVar(value=int(cfg.render_width))
        self.var_fps = tk.IntVar(value=int(cfg.fps))
        self.var_speed = tk.DoubleVar(value=cfg.speed)
        self.var_fog = tk.StringVar(value=FOG_LABELS[1] if cfg.fog_style == "dither" else FOG_LABELS[0])
        self.var_outline = tk.BooleanVar(value=cfg.map_outline > 0)
        self.var_enc = tk.StringVar(value=cfg.encoder)

        rec = ttk.LabelFrame(tab, text="Ghi trận")
        rec.pack(fill="x", padx=8, pady=(10, 6))
        ttk.Label(rec, text="Nhịp đọc game (lần/giây)").grid(row=0, column=0, sticky="w", **pad)
        ttk.Spinbox(rec, from_=1, to=60, textvariable=self.var_cap, width=8).grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(rec, text="25 = mượt như game; thấp hơn thì file nhỏ hơn", foreground="#666").grid(
            row=0, column=2, sticky="w", **pad)
        ttk.Label(rec, text="Thư mục lưu").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(rec, textvariable=self.var_out, width=60).grid(row=1, column=1, columnspan=2, sticky="we", **pad)
        ttk.Button(rec, text="Chọn...", command=self._choose_dir, width=8).grid(row=1, column=3, sticky="w", **pad)
        self.var_auto = tk.BooleanVar(value=cfg.auto_start)
        ttk.Checkbutton(rec, text="Tự bắt đầu ghi khi mở AoE-MapCap (không cần bấm ● Bắt đầu ghi)",
                        variable=self.var_auto).grid(row=2, column=0, columnspan=4, sticky="w", **pad)
        self.var_tele = tk.BooleanVar(value=cfg.telemetry)
        ttk.Checkbutton(rec, text="Gửi thống kê sử dụng (mã máy ngẫu nhiên, phiên bản, IP; không gửi tên hay trận đấu)",
                        variable=self.var_tele).grid(row=3, column=0, columnspan=4, sticky="w", **pad)
        rec.columnconfigure(2, weight=1)

        vid = ttk.LabelFrame(tab, text="Xuất video (tuỳ chọn)")
        vid.pack(fill="x", padx=8, pady=6)
        ttk.Checkbutton(vid, text="Tự xuất video sau mỗi trận (tốn CPU sau trận; mặc định tắt — dùng nút Xuất video... khi cần)",
                        variable=self.var_render_after).grid(row=0, column=0, columnspan=4, sticky="w", **pad)
        ttk.Label(vid, text="Độ rộng (px)").grid(row=1, column=0, sticky="w", **pad)
        ttk.Combobox(vid, values=(1920, 2560, 3840, 9216), textvariable=self.var_rwidth, width=8).grid(
            row=1, column=1, sticky="w", **pad)
        ttk.Label(vid, text="FPS").grid(row=1, column=2, sticky="w", **pad)
        ttk.Spinbox(vid, from_=1, to=60, textvariable=self.var_fps, width=8).grid(row=1, column=3, sticky="w", **pad)
        ttk.Label(vid, text="Tua nhanh").grid(row=2, column=0, sticky="w", **pad)
        ttk.Combobox(vid, values=(1, 2, 4, 8, 16), textvariable=self.var_speed, width=8).grid(
            row=2, column=1, sticky="w", **pad)
        ttk.Label(vid, text="Mã hoá").grid(row=2, column=2, sticky="w", **pad)
        ttk.Combobox(vid, values=("auto", "h264_nvenc", "h264_qsv", "h264_amf", "libx264"), textvariable=self.var_enc,
                     width=11).grid(row=2, column=3, sticky="w", **pad)
        ttk.Label(vid, text="Sương mù").grid(row=3, column=0, sticky="w", **pad)
        ttk.Combobox(vid, values=FOG_LABELS, textvariable=self.var_fog, width=20, state="readonly").grid(
            row=3, column=1, sticky="w", **pad)
        ttk.Checkbutton(vid, text="Viền trắng mờ quanh bản đồ", variable=self.var_outline).grid(
            row=3, column=2, columnspan=2, sticky="w", **pad)

        bot = ttk.Frame(tab)
        bot.pack(fill="x", padx=8, pady=8)
        ttk.Button(bot, text="Lưu cài đặt", command=self._save_settings).pack(side="left")
        ttk.Label(bot, foreground="#666", text="Cài đặt có hiệu lực từ lần Bắt đầu ghi tiếp theo.").pack(side="left", padx=12)

    def _build_log(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  Nhật ký  ")
        self.txt = tk.Text(tab, height=14, wrap="word", state="disabled", font=("Consolas", 9))
        sb = ttk.Scrollbar(tab, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        self.txt.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        sb.pack(side="right", fill="y", pady=8)

    # ---- cài đặt -------------------------------------------------------------------
    def _collect(self):
        cfg = self.cfg
        try:
            cfg.capture_fps = float(self.var_cap.get())
            cfg.render_width = int(self.var_rwidth.get())
            cfg.fps = float(self.var_fps.get())
            cfg.speed = float(self.var_speed.get())
        except (tk.TclError, ValueError) as e:
            messagebox.showerror(APP_TITLE, f"Giá trị không hợp lệ: {e}")
            return None
        cfg.render_after = bool(self.var_render_after.get())
        cfg.auto_start = bool(self.var_auto.get())
        cfg.telemetry = bool(self.var_tele.get())
        cfg.record_mode = "raw"
        cfg.record_video = True
        cfg.keep_raw = True
        cfg.map_outline = 0.35 if self.var_outline.get() else 0.0
        cfg.fog_style = "dither" if self.var_fog.get() == FOG_LABELS[1] else "dim"
        cfg.encoder = self.var_enc.get() or "auto"
        out = self.var_out.get().strip()
        cfg.out_dir = "" if os.path.normcase(out) == os.path.normcase(Config().resolved_out_dir()) else out
        cfg.fps = max(cfg.fps, cfg.capture_fps)      # nhịp đọc không vượt FPS (Config.clamp)
        cfg.clamp()
        self.var_cap.set(int(cfg.capture_fps))
        return cfg

    def _sync_settings_from_cfg(self):
        cfg = self.cfg
        self.var_rwidth.set(int(cfg.render_width))
        self.var_fps.set(int(cfg.fps))
        self.var_speed.set(cfg.speed)
        self.var_fog.set(FOG_LABELS[1] if cfg.fog_style == "dither" else FOG_LABELS[0])
        self.var_outline.set(cfg.map_outline > 0)
        self.var_enc.set(cfg.encoder)

    def _save_cfg(self):
        try:
            save_config(self.cfg)
        except Exception as e:  # noqa: BLE001
            self._append(f"không lưu được cấu hình: {e}")

    def _save_settings(self):
        if self._collect() is None:
            return
        self._save_cfg()
        new_raw = self.cfg.raw_dir()
        if os.path.normcase(new_raw) != os.path.normcase(self.table.folder):
            os.makedirs(new_raw, exist_ok=True)
            self.table.set_folder(new_raw)
        self._append("đã lưu cài đặt")

    def _choose_dir(self):
        d = filedialog.askdirectory(initialdir=self.var_out.get() or os.getcwd(), title="Chọn thư mục lưu dữ liệu")
        if d:
            self.var_out.set(os.path.normpath(d))

    # ---- ghi trận ------------------------------------------------------------------
    def _start(self):
        cfg = self._collect()
        if cfg is None:
            return
        self._save_cfg()
        self.stop_event = threading.Event()
        logger = Logger(cfg.log_path(), callback=self.q.put)
        self.engine = Engine(cfg, logger, self.stop_event, status=lambda s: self.q.put(("__status__", s)),
                             progress=lambda label, text: self.q.put(("__progress__", label, text)))
        self.thread = threading.Thread(target=self._run_engine, daemon=True)
        self.thread.start()
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self._append(f"=== bắt đầu ghi: nhịp đọc {int(cfg.capture_fps)}/s, lưu tại {cfg.raw_dir()}"
                     + ("; tự xuất video sau trận" if cfg.render_after else ""))

    def _run_engine(self):
        try:
            self.engine.run()
        except Exception as e:  # noqa: BLE001
            import traceback
            self.q.put("LỖI: " + str(e))
            self.q.put(traceback.format_exc()[-1500:])
        finally:
            self.q.put(("__done__", None))

    def _auto_start(self):
        """Tự bắt đầu ghi lúc mở app (trừ khi đã đang ghi, hoặc bản này đã bị chặn vì quá cũ)."""
        if self.engine is not None or getattr(self.updater, "block_win", None) is not None:
            return
        self._append("=== tự bắt đầu ghi khi mở app (tắt trong thẻ Cài đặt)")
        self._start()

    def _on_update_block(self):
        """Bản này đã ngừng hỗ trợ: dừng bộ ghi đang chờ game (cửa sổ chặn chỉ còn Cập nhật / Thoát)."""
        if self.engine is not None and self.stop_event and not self._busy_reason():
            self._stop()

    def _stop(self):
        if self.stop_event:
            self.stop_event.set()
            self._append("=== yêu cầu dừng ghi: đang chốt dữ liệu trận (nếu có)...")
            self.btn_stop.configure(state="disabled")

    # ---- trận đã ghi -----------------------------------------------------------------
    def _game_dir_for(self, path):
        """Thư mục game để lấy đồ hoạ cho file ghi: cấu hình -> ghi trong file -> game đang chạy -> chỗ cài quen thuộc."""
        from .engine import resolve_game_dir
        meta_dir = None
        try:
            from .rawrec import read_header
            meta_dir = ((read_header(path) or {}).get("meta") or {}).get("game_dir")
        except Exception:  # noqa: BLE001
            pass
        d = resolve_game_dir(self.cfg.game_dir, meta_dir)
        if d is None:
            d = filedialog.askdirectory(title="Chọn thư mục game AoE-HD / AOE1R (có thư mục data bên trong)")
            from .engine import valid_game_dir
            if not d or not valid_game_dir(d):
                if d:
                    messagebox.showerror(APP_TITLE, "Thư mục này không có dữ liệu game AoE-HD / AOE1R "
                                         "(empires.dat, graphic.drs hoặc graphics.drs trong data / data2).")
                return None
            self.cfg.game_dir = os.path.normpath(d)
            self._save_cfg()
        return d

    def _launch_replay(self, path):
        gd = self._game_dir_for(path)
        if gd is None:
            return
        args = ["--replay", os.path.abspath(path), f"--game-dir={gd}"]
        if getattr(sys, "frozen", False):
            cmd = [sys.executable] + args
        else:
            cmd = [sys.executable, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "run_app.py")] + args
        try:
            subprocess.Popen(cmd, close_fds=True)
            self._append(f"=== mở replay {os.path.basename(path)}")
        except OSError as e:
            messagebox.showerror(APP_TITLE, f"Không mở được trình xem replay: {e}")

    def _compact_old(self):
        """Nén các trận ghi bằng bản cũ sang định dạng mới (nhỏ hơn ~5 lần, không mất dữ liệu), chạy nền."""
        from .rawrec import read_header, FORMAT_VERSION
        folder = self.table.folder
        files = []
        for n in sorted(os.listdir(folder)):
            p = os.path.join(folder, n)
            if n.lower().endswith(".aoerec") and not self._is_recording_path(p):
                try:
                    h = read_header(p)
                except Exception:  # noqa: BLE001
                    h = None
                if h is not None and int(h.get("container", 0) or 0) < FORMAT_VERSION:
                    files.append(p)
        if not files:
            messagebox.showinfo(APP_TITLE, "Không có trận nào cần nén (mọi trận đã ở định dạng mới).")
            return
        total = sum(os.path.getsize(p) for p in files)
        if not messagebox.askyesno(APP_TITLE, f"Nén {len(files)} trận cũ ({total / 1e6:.0f} MB)?\n\n"
                                   "Dữ liệu giữ nguyên, file nhỏ đi khoảng 5 lần. Mỗi trận mất vài giây đến nửa phút; "
                                   "file chỉ được thay sau khi kiểm tra đủ dữ liệu."):
            return

        def job():
            from .rawrec import compact_file
            saved = 0
            for k, p in enumerate(files):
                self.q.put(("__progress__", "nén trận cũ", f"{k + 1}/{len(files)} {os.path.basename(p)}"))
                try:
                    r = compact_file(p)
                    if r:
                        saved += r[0] - r[1]
                        self.q.put(f"đã nén {os.path.basename(p)}: {r[0] / 1e6:.0f} MB -> {r[1] / 1e6:.0f} MB")
                    else:
                        self.q.put(f"bỏ qua {os.path.basename(p)} (không cần / không chắc an toàn)")
                except Exception as e:  # noqa: BLE001
                    self.q.put(f"không nén được {os.path.basename(p)}: {e}")
            self.q.put(f"=== nén xong {len(files)} trận, tiết kiệm {saved / 1e6:.0f} MB")
            self.q.put(("__progress__", "nén trận cũ", None))
            self.q.put("__reload_table__")
        threading.Thread(target=job, daemon=True).start()

    def _is_recording_path(self, path):
        """File đang được bộ ghi viết (không cho xoá)."""
        eng = self.engine
        rec = getattr(eng, "current_rec_path", None) if eng is not None else None
        return bool(rec) and os.path.normcase(os.path.abspath(rec)) == os.path.normcase(os.path.abspath(path))

    def _open_other(self):
        p = filedialog.askopenfilename(initialdir=self.table.folder, title="Chọn dữ liệu trận",
                                       filetypes=[("Dữ liệu thô AoE-MapCap", "*.aoerec"), ("Tất cả", "*.*")])
        if p:
            self._launch_replay(p)

    def _export_selected(self):
        p = self.table.selected_path()
        if not p:
            messagebox.showinfo(APP_TITLE, "Chọn một trận trong bảng trước.")
            return
        ExportDialog(self, p)

    def export_video(self, path):
        """Dựng video từ file .aoerec với cài đặt xuất video hiện tại (chạy nền, tiến độ ở thanh trạng thái)."""
        cfg = self.cfg
        out = os.path.join(cfg.resolved_out_dir(),
                           f"{os.path.splitext(os.path.basename(path))[0]}_{cfg.render_width}px_{int(cfg.fps)}fps"
                           f"{'' if cfg.speed == 1 else f'_x{cfg.speed:g}'}.mp4")
        self._append(f"=== xuất video {os.path.basename(path)} -> {os.path.basename(out)}")
        label = os.path.splitext(os.path.basename(path))[0]
        game_dir = self._game_dir_for(path)
        if game_dir is None:
            return
        self.renders[label] = "chuẩn bị..."
        self._refresh_status()

        def job():
            from .offline import render_raw, cleanup_stale
            try:
                cleanup_stale(cfg.resolved_out_dir(), log=self.q.put)
                render_raw(path, out, width=cfg.render_width, fps=cfg.fps, speed=cfg.speed, fog_dim=cfg.fog_param(),
                           outline=cfg.map_outline, game_dir=game_dir, workers=cfg.render_workers or None,
                           log=self.q.put, progress=lambda f, s: self.q.put(("__progress__", label, s)))
                self.q.put(f"xuất video xong: {out}")
            except Exception as e:  # noqa: BLE001
                self.q.put(f"lỗi dựng lại: {e}")
            finally:
                self.q.put(("__progress__", label, None))
        threading.Thread(target=job, daemon=True).start()

    def _open_dir(self):
        d = self.cfg.resolved_out_dir()
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
                    kind = item[0]
                    if kind == "__status__":
                        self.state_text = item[1]
                        self._refresh_status()
                    elif kind == "__progress__":      # (label, text); text None = lượt dựng đó kết thúc
                        label, text = item[1], item[2]
                        if text is None:
                            self.renders.pop(label, None)
                        else:
                            self.renders[label] = text
                        self._refresh_status()
                    elif kind == "__done__":
                        self._append("=== đã dừng ghi")
                        self.btn_start.configure(state="normal")
                        self.btn_stop.configure(state="disabled")
                        self.state_text = "đã dừng"
                        self._refresh_status()
                        self.engine = None
                        self.table.reload()
                elif item == "__reload_table__":
                    self.table.reload()
                else:
                    self._append(item)
                    if "đã chốt dữ liệu thô" in item or "ghi dữ liệu thô" in item:
                        self.table.reload()            # trận mới bắt đầu / vừa chốt: cập nhật bảng
                    if "lỗi dựng" in item:            # xuất video thất bại: báo rõ, không để người dùng chờ
                        self.state_text = "xuất video LỖI"
                        self._refresh_status()
                        messagebox.showerror(APP_TITLE, item)
        except queue.Empty:
            pass
        self.root.after(200, self._poll)

    def _refresh_status(self):
        """Nhãn trạng thái = trạng thái ghi + tiến độ từng lượt xuất video đang chạy."""
        parts = [self.state_text] + [f"xuất video {k}: {v}" for k, v in self.renders.items()]
        self.lbl_status.configure(text="Trạng thái: " + " | ".join(p for p in parts if p))

    # ---- tự cập nhật ------------------------------------------------------------------
    def _busy_reason(self):
        """Lý do chưa được cập nhật / khởi động lại ("" = rảnh)."""
        from .offline import active_renders
        running = self.engine is not None and self.thread is not None and self.thread.is_alive()
        if running and (getattr(self.engine, "state", "") == "đang ghi" or self.engine.current_rec_path):
            return "Đang ghi trận"
        if active_renders() > 0:
            return "Đang xuất video"
        return ""

    def _before_update_restart(self):
        """Trước khi chạy bản mới: dừng bộ ghi đang chờ game (bản mới tự bật lại bằng --autostart)."""
        running = self.engine is not None and self.thread is not None and self.thread.is_alive()
        self._restart_recording = running
        if running:
            self.stop_event.set()
            self.thread.join(timeout=30)
        return True

    def _on_close(self):
        from .offline import active_renders
        running = self.engine is not None and self.thread is not None and self.thread.is_alive()
        recording = running and getattr(self.engine, "state", "") == "đang ghi"
        rendering = active_renders() > 0
        if recording and rendering:
            msg = "Đang ghi trận và đang xuất video. Thoát sẽ chốt dữ liệu trận nhưng video đang xuất sẽ dở dang. Thoát?"
        elif recording:
            msg = "Đang ghi trận. Dừng, chốt dữ liệu rồi thoát?"
        elif rendering:
            msg = "Đang xuất video. Thoát bây giờ sẽ mất video đang xuất (xuất lại được từ trận đã ghi). Thoát?"
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
    app = App(root)
    schedule_autostart(app, sys.argv)
    root.mainloop()


def schedule_autostart(app, argv, delay_ms=800):
    """Mở app là tự bắt đầu ghi (Cài đặt: "Tự bắt đầu ghi..."); --autostart: khởi động lại sau khi cập nhật."""
    if app.cfg.auto_start or "--autostart" in argv:
        app.root.after(delay_ms, app._auto_start)
        return True
    return False


if __name__ == "__main__":
    main()
