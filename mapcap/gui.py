"""Giao diện AoE-MapCap (tkinter): ghi trận và xem replay là chính; xuất video là tuỳ chọn.

Giao diện tối kiểu XArena (mapcap/theme.py): thanh bên trái (logo, Trận đã ghi / Cài đặt / Nhật ký, trạng thái ghi),
đầu trang chuyển sắc đỏ-đen kèm nút ● Bắt đầu ghi / ■ Dừng ghi, các trang:
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
from tkinter import font as tkfont

from . import theme
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
        theme.dark_window(top)
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
        ttk.Label(frm, style="Muted.TLabel", wraplength=380, justify="left",
                  text="9216 = kích cỡ gốc của game (rất nặng, chỉ libx264). Video lưu vào thư mục Video, "
                       "tiến độ hiện ở thanh trạng thái.").grid(row=len(rows) + 1, column=0, columnspan=2, sticky="w", **pad)
        bot = ttk.Frame(top)
        bot.pack(fill="x", padx=12, pady=(0, 10))
        ttk.Button(bot, text="Huỷ", command=top.destroy).pack(side="right", padx=4)
        ttk.Button(bot, text="Xuất video", style="Accent.TButton", command=self._ok).pack(side="right", padx=4)
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
    PAGES = (("matches", "", "Trận đã ghi", "Xem lại trận như replay Liên Minh Huyền Thoại, xuất video khi cần"),
             ("settings", "", "Cài đặt", "Ghi trận, thư mục lưu, xuất video, thống kê sử dụng"),
             ("log", "", "Nhật ký", "Hoạt động của bộ ghi, xuất video và cập nhật"))

    def __init__(self, root):
        self.root = root
        root.title(f"{APP_TITLE} v{APP_VERSION} — ghi trận và xem replay")
        root.minsize(980, 600)
        root.geometry("1200x720")
        try:
            root.iconbitmap(default=app_icon_path())
        except Exception:  # noqa: BLE001
            pass
        theme.apply(root)
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
        self.updater = UpdateController(root, self.main, "mapcap", APP_TITLE, log=lambda m: self.q.put("cập nhật: " + m),
                                        is_busy=self._busy_reason, before_restart=self._before_update_restart,
                                        restart_args=lambda: ["--autostart"] if self._restart_recording else [],
                                        bar_before=self.content, on_block=self._on_update_block)
        self.updater.start()
        from . import telemetry                         # thống kê sử dụng: một lượt mỗi lần mở app (có mạng)
        telemetry.send("mapcap", "open", self.cfg.telemetry, raw_dir=self.cfg.raw_dir())

    # ---- giao diện: thanh bên trái + đầu trang + các trang (kiểu XArena) ------------------
    def _build(self):
        C = theme.C
        side = tk.Frame(self.root, bg=C["sidebar"], width=232)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Frame(self.root, bg=C["line2"], width=1).pack(side="left", fill="y")
        self.main = tk.Frame(self.root, bg=C["bg"])
        self.main.pack(side="left", fill="both", expand=True)

        # logo + tên
        logo = tk.Frame(side, bg=C["sidebar"])
        logo.pack(fill="x", padx=18, pady=(20, 18))
        self._logo = self._logo_image(40)
        if self._logo is not None:
            tk.Label(logo, image=self._logo, bg=C["sidebar"]).pack(side="left")
        names = tk.Frame(logo, bg=C["sidebar"])
        names.pack(side="left", padx=(10, 0))
        tk.Label(names, text="AoE-MapCap", bg=C["sidebar"], fg="#ffffff", font=theme.F(14, "bold")).pack(anchor="w")
        tk.Label(names, text=f"PHIÊN BẢN {APP_VERSION}", bg=C["sidebar"], fg=C["gold"],
                 font=theme.F(8, "bold")).pack(anchor="w")
        tk.Frame(side, bg=C["line2"], height=1).pack(fill="x", padx=18, pady=(0, 12))

        # mục điều hướng
        icon_font = ("Segoe MDL2 Assets", 13) if "Segoe MDL2 Assets" in tkfont.families() else None
        self.nav = {}
        for key, glyph, label, _sub in self.PAGES:
            item = tk.Frame(side, bg=C["sidebar"], cursor="hand2")
            item.pack(fill="x", padx=10, pady=2)
            bar = tk.Frame(item, bg=C["sidebar"], width=3)
            bar.pack(side="left", fill="y")
            ic = tk.Label(item, text=glyph if icon_font else "•", font=icon_font or theme.F(12), bg=C["sidebar"],
                          fg=C["muted"], width=3)
            ic.pack(side="left", pady=10, padx=(8, 0))
            tx = tk.Label(item, text=label, font=theme.F(11, "bold"), bg=C["sidebar"], fg=C["muted"], anchor="w")
            tx.pack(side="left", fill="x", expand=True, padx=(4, 0))
            self.nav[key] = (item, bar, ic, tx)
            for w in (item, ic, tx):
                w.bind("<Button-1>", lambda e, k=key: self.show_page(k))
                w.bind("<Enter>", lambda e, k=key: self._nav_hover(k, True))
                w.bind("<Leave>", lambda e, k=key: self._nav_hover(k, False))

        # trạng thái ghi (đáy thanh bên)
        stat = tk.Frame(side, bg=C["panel"], highlightthickness=1, highlightbackground=C["line"])
        stat.pack(side="bottom", fill="x", padx=14, pady=16)
        tk.Label(stat, text="TRẠNG THÁI", bg=C["panel"], fg=C["dim"], font=theme.F(8, "bold")).pack(
            anchor="w", padx=12, pady=(10, 2))
        row = tk.Frame(stat, bg=C["panel"])
        row.pack(fill="x", padx=12, pady=(0, 4))
        self.dot = tk.Canvas(row, width=12, height=12, bg=C["panel"], highlightthickness=0)
        self.dot.pack(side="left")
        self.dot_id = self.dot.create_oval(2, 2, 11, 11, fill=C["dim"], outline="")
        self.lbl_state = tk.Label(row, text="Chưa ghi", bg=C["panel"], fg="#ffffff", font=theme.F(11, "bold"))
        self.lbl_state.pack(side="left", padx=(8, 0))
        self.lbl_status = tk.Label(stat, text="", bg=C["panel"], fg=C["muted"], font=theme.F(9), justify="left",
                                   anchor="w", wraplength=190)
        self.lbl_status.pack(fill="x", padx=12, pady=(0, 10))

        # đầu trang: nền chuyển sắc đỏ-đen, tiêu đề trang, nút ghi
        self.head = tk.Canvas(self.main, height=96, bg=C["bg"], highlightthickness=0)
        self.head.pack(fill="x")
        self._head_bg = self.head.create_image(0, 0, anchor="nw")
        self._head_title = self.head.create_text(30, 34, anchor="w", text="", fill="#ffffff", font=theme.F(20, "bold"))
        self._head_sub = self.head.create_text(31, 64, anchor="w", text="", fill=C["muted"], font=theme.F(10))
        btns = tk.Frame(self.head, bg=C["bg"])
        self.btn_start = ttk.Button(btns, text="●  Bắt đầu ghi", style="Accent.TButton", command=self._start)
        self.btn_start.pack(side="left", padx=4)
        self.btn_stop = ttk.Button(btns, text="■  Dừng ghi", command=self._stop, state="disabled")
        self.btn_stop.pack(side="left", padx=4)
        self._head_btns = self.head.create_window(0, 48, anchor="e", window=btns)
        self.head.bind("<Configure>", self._layout_head)

        self.content = tk.Frame(self.main, bg=C["bg"])
        self.content.pack(fill="both", expand=True, padx=24, pady=(16, 18))
        self.pages = {}
        self._build_matches()
        self._build_settings()
        self._build_log()
        self.show_page("matches")
        self._refresh_status()

    def _logo_image(self, size):
        try:
            from PIL import Image, ImageTk
            im = Image.open(app_icon_path())
            im = im.convert("RGBA").resize((size, size), Image.LANCZOS)
            return ImageTk.PhotoImage(im)
        except Exception:  # noqa: BLE001
            return None

    def _layout_head(self, e):
        w, h = e.width, e.height
        try:
            ph = theme.gradient_photo(w, h, theme.C["bg"], "#5a0a12", glow_at=0.4, spread=0.24)  # góc phải tối: nút liền nền
            self.head.itemconfigure(self._head_bg, image=ph)
            self._head_photo = ph
        except Exception:  # noqa: BLE001
            pass
        self.head.coords(self._head_btns, w - 26, h // 2)

    def _nav_hover(self, key, on):
        if key == getattr(self, "page", None):
            return
        item, bar, ic, tx = self.nav[key]
        bg = "#1a1a20" if on else theme.C["sidebar"]
        for w in (item, ic, tx):
            w.configure(bg=bg)
        bar.configure(bg=bg)
        tx.configure(fg="#ffffff" if on else theme.C["muted"])

    def show_page(self, key):
        C = theme.C
        self.page = key
        for k, (item, bar, ic, tx) in self.nav.items():
            sel = k == key
            bg = C["red_sel"] if sel else C["sidebar"]
            for w in (item, ic, tx):
                w.configure(bg=bg)
            bar.configure(bg=C["red"] if sel else C["sidebar"])
            ic.configure(fg=C["gold_hi"] if sel else C["muted"])
            tx.configure(fg="#ffffff" if sel else C["muted"])
        for k, f in self.pages.items():
            if k == key:
                f.pack(fill="both", expand=True)
            else:
                f.pack_forget()
        _k, _g, title, sub = next(p for p in self.PAGES if p[0] == key)
        self.head.itemconfigure(self._head_title, text=title)
        self.head.itemconfigure(self._head_sub, text=sub)

    def _card(self, parent, title=None, **pack):
        C = theme.C
        card = tk.Frame(parent, bg=C["panel"], highlightthickness=1, highlightbackground=C["line2"])
        card.pack(fill="x", **(pack or {"pady": (0, 14)}))
        if title:
            hd = tk.Frame(card, bg=C["panel"])
            hd.pack(fill="x", padx=18, pady=(14, 6))
            tk.Frame(hd, bg=C["red"], width=3, height=16).pack(side="left", padx=(0, 10))
            ttk.Label(hd, text=title, style="CardTitle.TLabel").pack(side="left")
        body = tk.Frame(card, bg=C["panel"])
        body.pack(fill="x", padx=18, pady=(4, 16))
        return body

    def _build_matches(self):
        from replay.picker import MatchTable
        tab = tk.Frame(self.content, bg=theme.C["bg"])
        self.pages["matches"] = tab
        raw_dir = self.cfg.raw_dir()
        os.makedirs(raw_dir, exist_ok=True)
        bot = ttk.Frame(tab)
        bot.pack(side="bottom", fill="x", pady=(12, 0))
        self.table = MatchTable(tab, raw_dir, self._launch_replay, show_dir_button=False)
        self.table.pack(fill="both", expand=True)
        ttk.Button(bot, text="▶  Xem replay", style="Accent.TButton", command=self.table.open_selected).pack(side="left")
        for text, cmd in (("Xuất video...", self._export_selected), ("Mở file khác...", self._open_other),
                          ("Mở thư mục", self._open_dir), ("Xoá trận", self.table.delete_selected),
                          ("Nén trận cũ", self._compact_old)):
            ttk.Button(bot, text=text, command=cmd).pack(side="left", padx=(8, 0))
        self.table.is_busy = self._is_recording_path
        ttk.Label(bot, textvariable=self.table.var_status, style="Muted.TLabel").pack(side="right")

    def _build_settings(self):
        tab = tk.Frame(self.content, bg=theme.C["bg"])
        self.pages["settings"] = tab
        pad = {"padx": (0, 14), "pady": 6}
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
        self.var_auto = tk.BooleanVar(value=cfg.auto_start)
        self.var_tele = tk.BooleanVar(value=cfg.telemetry)

        rec = self._card(tab, "Ghi trận")
        ttk.Label(rec, text="Nhịp đọc game (lần/giây)", style="Card.TLabel").grid(row=0, column=0, sticky="w", **pad)
        ttk.Spinbox(rec, from_=1, to=60, textvariable=self.var_cap, width=8).grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(rec, text="25 = mượt như game; thấp hơn thì file nhỏ hơn", style="CardMuted.TLabel").grid(
            row=0, column=2, sticky="w", **pad)
        ttk.Label(rec, text="Thư mục lưu", style="Card.TLabel").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(rec, textvariable=self.var_out, width=60).grid(row=1, column=1, columnspan=2, sticky="we", **pad)
        ttk.Button(rec, text="Chọn...", command=self._choose_dir).grid(row=1, column=3, sticky="w", pady=6)
        ttk.Checkbutton(rec, text="Tự bắt đầu ghi khi mở AoE-MapCap (không cần bấm ● Bắt đầu ghi)",
                        variable=self.var_auto, style="Card.TCheckbutton").grid(row=2, column=0, columnspan=4,
                                                                                sticky="w", pady=(10, 2))
        ttk.Checkbutton(rec, text="Gửi thống kê sử dụng (mã máy ngẫu nhiên, tên người chơi, phiên bản, IP; không gửi trận đấu)",
                        variable=self.var_tele, style="Card.TCheckbutton").grid(row=3, column=0, columnspan=4,
                                                                                sticky="w", pady=2)
        rec.columnconfigure(2, weight=1)

        vid = self._card(tab, "Xuất video (tuỳ chọn)")
        ttk.Checkbutton(vid, text="Tự xuất video sau mỗi trận (tốn CPU sau trận; mặc định tắt — dùng nút Xuất video... khi cần)",
                        variable=self.var_render_after, style="Card.TCheckbutton").grid(row=0, column=0, columnspan=4,
                                                                                        sticky="w", pady=(0, 6))
        rows = [("Độ rộng (px)", ttk.Combobox(vid, values=(1920, 2560, 3840, 9216), textvariable=self.var_rwidth, width=9)),
                ("FPS", ttk.Spinbox(vid, from_=1, to=60, textvariable=self.var_fps, width=8)),
                ("Tua nhanh", ttk.Combobox(vid, values=(1, 2, 4, 8, 16), textvariable=self.var_speed, width=9)),
                ("Mã hoá", ttk.Combobox(vid, values=("auto", "h264_nvenc", "h264_qsv", "h264_amf", "libx264"),
                                        textvariable=self.var_enc, width=12)),
                ("Sương mù", ttk.Combobox(vid, values=FOG_LABELS, textvariable=self.var_fog, width=20, state="readonly"))]
        for k, (label, w) in enumerate(rows):
            r, c = 1 + k // 2, (k % 2) * 2
            ttk.Label(vid, text=label, style="Card.TLabel").grid(row=r, column=c, sticky="w", **pad)
            w.grid(row=r, column=c + 1, sticky="w", **pad)
        ttk.Checkbutton(vid, text="Viền trắng mờ quanh bản đồ", variable=self.var_outline,
                        style="Card.TCheckbutton").grid(row=3, column=2, columnspan=2, sticky="w", pady=6)

        bot = ttk.Frame(tab)
        bot.pack(fill="x", pady=(4, 0))
        ttk.Button(bot, text="Lưu cài đặt", style="Accent.TButton", command=self._save_settings).pack(side="left")
        ttk.Label(bot, text="Cài đặt có hiệu lực từ lần Bắt đầu ghi tiếp theo.", style="Muted.TLabel").pack(
            side="left", padx=14)

    def _build_log(self):
        tab = tk.Frame(self.content, bg=theme.C["bg"])
        self.pages["log"] = tab
        self.txt = tk.Text(tab, height=14, wrap="word", state="disabled", font=("Consolas", 10), padx=12, pady=10,
                           **theme.text_widget_colors())
        sb = ttk.Scrollbar(tab, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        self.txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y", padx=(4, 0))

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
            subprocess.Popen([os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "explorer.exe"), d])

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

    STATE_LOOK = {"đang ghi": ("ĐANG GHI TRẬN", "red_hi"), "chờ game": ("Đang chờ game", "gold"),
                  "đã dừng": ("Đã dừng", "dim"), "chưa ghi": ("Chưa ghi", "dim")}

    def _refresh_status(self):
        """Thanh bên: chấm màu + trạng thái ghi; dòng nhỏ = tiến độ từng lượt xuất video / nén đang chạy."""
        st = (self.state_text or "").strip()
        label, color = self.STATE_LOOK.get(st, (st[:1].upper() + st[1:] if st else "Chưa ghi", "muted"))
        self.lbl_state.configure(text=label, fg="#ffffff" if color != "dim" else theme.C["muted"])
        self.dot.itemconfigure(self.dot_id, fill=theme.C[color])
        extra = [f"{k}: {v}" for k, v in self.renders.items()]
        self.lbl_status.configure(text="\n".join(extra) if extra else
                                  ("Mở game AoE-HD / AOE1R là tự ghi" if st == "chờ game" else ""))

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
