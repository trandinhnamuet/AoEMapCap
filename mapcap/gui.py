"""Giao diện AoE-MapCap (tkinter): ghi trận và xem replay là chính; xuất video là tuỳ chọn.

Giao diện tối kiểu XArena (mapcap/theme.py): thanh bên trái (logo, Trận đã ghi / Cài đặt / Nhật ký, trạng thái ghi),
đầu trang chuyển sắc đỏ-đen kèm khối trạng thái ghi (luôn ghi khi app đang mở, từ v34 không có nút bật / tắt), các trang:
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


def report_choices(infos, is_busy=None):
    """Trận báo cáo được (đọc được, không đang ghi), mới nhất trước: [(đường dẫn, nhãn)]. Trận app đã thấy hack có ⚠."""
    import time

    from replay.library import fmt_duration
    out = []
    for p, info in infos.items():
        if "error" in info or info.get("recording") or not info.get("players") or (is_busy and is_busy(p)):
            continue
        names = ", ".join(pl.get("name", "?") for pl in info["players"])
        label = (("⚠ " if info.get("hack") else "") + time.strftime("%d/%m/%Y %H:%M", time.localtime(info.get(
            "created", 0))) + f" · {info.get('map', '')} · {fmt_duration(info.get('duration_ms', 0))} · {names}")
        out.append((info.get("created", 0), p, label[:150]))
    return [(p, lb) for _c, p, lb in sorted(out, key=lambda x: x[0], reverse=True)]


class ReportDialog:
    """Hộp thoại "Báo cáo hack": chọn trận (người dùng 12/11), người bị nghi, ghi chú, gửi file trận lên máy chủ
    (thanh tiến độ). Gửi xong lưu vào lịch sử trên máy (trang Lịch sử báo cáo)."""

    def __init__(self, app, path, info=None):
        self.app = app
        self.choices = report_choices(app.table.infos, app._is_recording_path)
        if path not in dict(self.choices) and self.choices:
            path = self.choices[0][0]
        self.path = path
        self.info = app.table.infos.get(path) or info or {}
        C = theme.C
        top = self.top = tk.Toplevel(app.root)
        top.title("Báo cáo trận có hack")
        top.configure(bg=C["bg"])
        top.transient(app.root)
        top.resizable(False, False)
        theme.dark_window(top)
        pad = {"padx": 16}
        tk.Label(top, text="Báo cáo trận có hack", font=theme.F(14, "bold"), bg=C["bg"], fg="#ffffff",
                 anchor="w").pack(fill="x", pady=(14, 8), **pad)
        tk.Label(top, text="Trận", font=theme.F(10, "bold"), bg=C["bg"], fg=C["text"], anchor="w").pack(fill="x", **pad)
        self.var_match = tk.StringVar(value=dict(self.choices).get(path, ""))
        self.cb_match = ttk.Combobox(top, textvariable=self.var_match, values=[lb for _p, lb in self.choices],
                                     state="readonly", height=16)
        self.cb_match.pack(fill="x", pady=(4, 2), **pad)
        self.cb_match.bind("<<ComboboxSelected>>", lambda e: self._pick_match())
        self.lbl_meta = tk.Label(top, text="", font=theme.F(10), bg=C["bg"], fg=C["muted"], anchor="w")
        self.lbl_meta.pack(fill="x", **pad)
        self.lbl_auto = tk.Label(top, text="", font=theme.F(10), bg=C["bg"], anchor="w", justify="left",
                                 wraplength=520)
        self.lbl_auto.pack(fill="x", pady=(6, 8), **pad)
        tk.Label(top, text="Người bị nghi hack", font=theme.F(10, "bold"), bg=C["bg"], fg=C["text"],
                 anchor="w").pack(fill="x", **pad)
        self.var_suspect = tk.StringVar(value="Không rõ")
        self.cb_suspect = ttk.Combobox(top, textvariable=self.var_suspect, values=["Không rõ"], state="readonly")
        self.cb_suspect.pack(fill="x", pady=(4, 10), **pad)
        tk.Label(top, text="Ghi chú (hack gì, phút thứ mấy...)", font=theme.F(10, "bold"), bg=C["bg"], fg=C["text"],
                 anchor="w").pack(fill="x", **pad)
        self.txt = tk.Text(top, height=4, width=62, wrap="word", font=theme.F(10), padx=8, pady=6,
                           **theme.text_widget_colors())
        self.txt.pack(fill="x", pady=(4, 8), **pad)                # thẳng hàng với nhãn và ô chọn ở trên
        tk.Label(top, text="Gửi lên máy chủ của AoE-MapCap: file trận này, mã máy, phiên bản, tên trong game của bạn và "
                           "nội dung ở trên. Admin xem lại trận để xác định hack và bổ sung luật phát hiện.",
                 font=theme.F(9), bg=C["bg"], fg=C["muted"], anchor="w", justify="left", wraplength=520).pack(fill="x", **pad)
        self.pb = ttk.Progressbar(top, mode="determinate", maximum=1000)
        self.lbl = tk.Label(top, text="", font=theme.F(10), bg=C["bg"], fg=C["muted"], anchor="w")
        self.lbl.pack(fill="x", pady=(6, 0), **pad)
        bot = tk.Frame(top, bg=C["bg"])
        bot.pack(fill="x", pady=12, **pad)
        self.btn_close = ttk.Button(bot, text="Huỷ", command=top.destroy)
        self.btn_close.pack(side="right")
        self.btn_send = ttk.Button(bot, text="Gửi báo cáo", style="Accent.TButton", command=self._send)
        self.btn_send.pack(side="right", padx=8)
        self.q = queue.Queue()
        self._set_match(self.path)
        top.grab_set()

    def _pick_match(self):
        lb = self.var_match.get()
        p = next((p for p, x in self.choices if x == lb), None)
        if p and p != self.path:
            self._set_match(p)

    def _set_match(self, path):
        """Đổi trận đang báo cáo: dòng tóm tắt, vi phạm app tự thấy, danh sách người bị nghi (gợi ý người app bắt được)."""
        from replay.library import fmt_duration, hack_text
        self.path = path
        info = self.info = self.app.table.infos.get(path) or self.info or {}
        C = theme.C
        if not path:
            self.lbl_meta.configure(text="Chưa có trận nào báo cáo được.")
            self.btn_send.configure(state="disabled")
            return
        size = os.path.getsize(path) / 1e6 if os.path.exists(path) else 0
        self.lbl_meta.configure(text=f"{info.get('map', '')} · {fmt_duration(info.get('duration_ms', 0))} · "
                                     f"{info.get('format', '')} · file {size:.1f} MB")
        auto = hack_text(info)
        self.lbl_auto.configure(text=("App đã phát hiện: " + auto) if auto else
                                "App không tự phát hiện vi phạm nào trong trận này.",
                                fg="#ff6b6b" if auto else C["muted"])
        names = [pl.get("name", "?") for pl in info.get("players", []) if pl.get("name") != info.get("recorder")]
        hackers = list(dict.fromkeys(e.get("name") for e in info.get("hack") or []))
        self.cb_suspect.configure(values=names + ["Không rõ"])
        self.var_suspect.set(hackers[0] if hackers else (names[0] if len(names) == 1 else "Không rõ"))

    def _send(self):
        suspect = self.var_suspect.get().strip()
        note = self.txt.get("1.0", "end").strip()
        if suspect == "Không rõ":
            suspect = ""
        if not suspect and not note:
            messagebox.showinfo("Báo cáo hack", "Hãy chọn người bị nghi hoặc ghi chú hack gì.", parent=self.top)
            return
        self.btn_send.configure(state="disabled")
        self.cb_match.configure(state="disabled")
        self._sent = (self.path, self.info, suspect, note)
        self.pb.pack(fill="x", padx=16, pady=(6, 0), before=self.lbl)
        self.lbl.configure(text="Đang gửi…")

        def run():
            from . import report
            try:
                rid = report.upload(self.path, self.info, suspect, note,
                                    progress=lambda a, b: self.q.put(("p", a, b)))
                self.q.put(("ok", rid))
            except report.ReportError as e:
                self.q.put(("err", str(e)))
            except Exception as e:  # noqa: BLE001
                self.q.put(("err", repr(e)))
        threading.Thread(target=run, daemon=True).start()
        self._poll()

    def _poll(self):
        try:
            while True:
                m = self.q.get_nowait()
                if m[0] == "p":
                    self.pb["value"] = 1000 * m[1] / max(m[2], 1)
                    self.lbl.configure(text=f"Đang gửi {m[1] / 1e6:.1f} / {m[2] / 1e6:.1f} MB…")
                elif m[0] == "ok":
                    self.lbl.configure(text=f"Đã gửi báo cáo #{m[1]}. Cảm ơn bạn!", fg=theme.C["green"])
                    self.btn_close.configure(text="Đóng")
                    self.app._append(f"đã gửi báo cáo hack #{m[1]}: {os.path.basename(self.path)}")
                    self.app._report_sent(m[1], *self._sent)
                    return
                elif m[0] == "err":
                    self.lbl.configure(text="Không gửi được: " + m[1], fg="#ff6b6b")
                    self.btn_send.configure(state="normal")
                    self.cb_match.configure(state="readonly")
                    self.app._append("báo cáo hack lỗi: " + m[1])
                    return
        except queue.Empty:
            pass
        except tk.TclError:
            return
        try:
            self.top.after(150, self._poll)
        except tk.TclError:
            pass


_ALARM = None


def _alarm_wav():
    """Chuông cảnh báo hack: 3 cặp nốt cao-thấp (~1,1 s), WAV 16 bit tạo trong bộ nhớ."""
    global _ALARM
    if _ALARM is None:
        import io
        import math
        import struct as st
        import wave
        rate = 22050
        frames = bytearray()
        for _k in range(3):
            for f in (1320.0, 880.0):
                n = int(rate * 0.16)
                for i in range(n):
                    env = min(1.0, i / 200.0, (n - i) / 400.0)
                    frames += st.pack("<h", int(14000 * env * math.sin(2 * math.pi * f * i / rate)))
            frames += b"\0\0" * int(rate * 0.05)
        bio = io.BytesIO()
        with wave.open(bio, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(bytes(frames))
        _ALARM = bio.getvalue()
    return _ALARM


def play_alarm():
    """Phát chuông (luồng riêng: winsound SND_MEMORY không chạy nền được). Lỗi âm thanh thì bỏ qua."""
    def run():
        try:
            import winsound
            winsound.PlaySound(_alarm_wav(), winsound.SND_MEMORY | winsound.SND_NODEFAULT)
        except Exception:  # noqa: BLE001
            pass
    if os.environ.get("AOEMAPCAP_MUTE") != "1":
        threading.Thread(target=run, daemon=True).start()


class App:
    PAGES = (("matches", "", "Trận đã ghi", "Xem lại trận: tua, đổi góc nhìn, xuất video khi cần"),
             ("phone", "", "Điện thoại", "Xem lại trận trên điện thoại Android ở bất kỳ mạng nào: quét mã QR để kết nối"),
             ("settings", "", "Cài đặt", "Ghi trận, thư mục lưu, xuất video, thống kê sử dụng"),
             ("reports", "\ue7c1", "Lịch sử báo cáo", "Các trận bạn đã báo cáo hack từ máy này"),
             ("keys", "\ue765", "Phím tắt", "Phím điều khiển khi xem replay"),
             ("log", "", "Nhật ký", "Hoạt động của bộ ghi, xuất video và cập nhật"),
             ("feedback", "\ue939", "Góp ý", "Gửi ý kiến, báo lỗi cho tác giả trên trang Thảo luận (GitHub Discussions)"))
    FEEDBACK_URL = "https://github.com/trandinhnamuet/AoEMapCap/discussions"

    def __init__(self, root):
        self.root = root
        self._base_title = f"{APP_TITLE} v{APP_VERSION} — ghi trận và xem replay"
        root.title(self._base_title)
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
        self._stopping = False       # bộ ghi đang chốt dữ liệu để dừng (thoát / áp dụng cài đặt / bị chặn)
        self._quitting = False       # đang thoát hẳn: không tự bật lại bộ ghi
        self._apply_pending = False  # cài đặt mới chờ hết trận mới bật lại bộ ghi
        self._restart_soon = False
        self._rec_since = None       # time.monotonic() lúc bắt đầu ghi trận đang ghi
        self._pulse = False
        self._mode = None
        self.tray = None             # biểu tượng khay hệ thống (_start_tray)
        self.renders = {}            # label -> dòng tiến độ của lượt xuất video đang chạy
        self.engine = None
        self.thread = None
        self.stop_event = None
        self.phone = None            # máy chủ cho app điện thoại (mobile_server.PhoneServer), tạo khi bật lần đầu
        self._recording = False      # đang ghi trận: máy chủ điện thoại hoãn chuyển trận (tốn CPU)
        self._was_rec = False        # vừa hết trận -> kiểm tra tự dọn trận cũ
        self._clean_busy = False     # đang quét / dọn ở luồng nền (mapcap/retention)
        self._clean_st = None        # tình trạng quét gần nhất
        self._low_disk = False
        self.var_clean = tk.BooleanVar(value=self.cfg.auto_clean)
        self.var_hack_sound = tk.BooleanVar(value=self.cfg.hack_sound)
        self.hack_events = []        # vi phạm phát hiện trong trận đang ghi (thẻ cảnh báo góc phải trên)
        self.hack_card = None
        self.var_clean_usage = tk.StringVar(value="")
        self._build()
        self.root.after(200, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        from .update_ui import UpdateController
        self._restart_recording = False
        self.updater = UpdateController(root, self.main, "mapcap", APP_TITLE, log=lambda m: self.q.put("cập nhật: " + m),
                                        is_busy=self._busy_reason, before_restart=self._before_update_restart,
                                        restart_args=self._restart_args,
                                        bar_before=self.content, on_block=self._on_update_block)
        self.updater.start()
        self.tray = None
        self._tray_hint_shown = False
        self._start_tray()
        root.bind("<Destroy>", lambda e: self._stop_tray() if e.widget is root else None, add="+")
        from . import telemetry                         # thống kê sử dụng: một lượt mỗi lần mở app (có mạng)
        telemetry.send("mapcap", "open", self.cfg.telemetry, raw_dir=self.cfg.raw_dir())
        if self.cfg.phone_server:
            self.root.after(1500, lambda: self._phone_start(quiet=True))
        self.root.after(4000, self._clean_timer)
        self._winstart_init()

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
        tk.Label(names, text=f"PHIÊN BẢN v{APP_VERSION}", bg=C["sidebar"], fg=C["gold"],
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
            ic.pack(side="left", pady=7, padx=(8, 0))      # 7 mục vẫn vừa trên các ô tích ở cửa sổ cao 600 px
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
        self.lbl_status.bind("<Configure>", lambda e: self.lbl_status.configure(wraplength=max(80, e.width - 4)))
        self._build_side_opts(side)

        # dải màu trên cùng: đỏ = đang ghi trận, vàng = bộ ghi bật (chờ game / chờ trận), xám = không ghi
        self.strip = tk.Frame(self.main, bg=C["line"], height=4)
        self.strip.pack(fill="x")
        # đầu trang: nền chuyển sắc đỏ-đen, tiêu đề trang, trạng thái ghi + nút bật/tắt
        self.head = tk.Canvas(self.main, height=96, bg=C["bg"], highlightthickness=0)
        self.head.pack(fill="x")
        self._head_bg = self.head.create_image(0, 0, anchor="nw")
        self._head_title = self.head.create_text(30, 34, anchor="w", text="", fill="#ffffff", font=theme.F(20, "bold"))
        self._head_sub = self.head.create_text(31, 64, anchor="w", text="", fill=C["muted"], font=theme.F(10))
        btns = tk.Frame(self.head, bg=C["bg"])
        self.chip = tk.Frame(btns, bg=C["panel"], highlightthickness=1, highlightbackground=C["line"])
        self.chip.pack(side="left", padx=(0, 10))
        self.chip_dot = tk.Canvas(self.chip, width=16, height=16, bg=C["panel"], highlightthickness=0)
        self.chip_dot.pack(side="left", padx=(12, 0), pady=9)
        self.chip_dot_id = self.chip_dot.create_oval(2, 2, 15, 15, fill=C["dim"], outline="")
        chip_txt = tk.Frame(self.chip, bg=C["panel"])
        chip_txt.pack(side="left", padx=(9, 14), pady=4)
        self.chip_title = tk.Label(chip_txt, text="KHÔNG GHI", bg=C["panel"], fg=C["muted"], font=theme.F(12, "bold"),
                                   anchor="w", width=18)
        self.chip_title.pack(anchor="w")
        self.chip_sub = tk.Label(chip_txt, text="", bg=C["panel"], fg=C["muted"], font=theme.F(9), anchor="w", width=34,
                                 justify="left")
        self.chip_sub.pack(anchor="w")
        self._chip_parts = (self.chip, self.chip_dot, chip_txt, self.chip_title, self.chip_sub)
        # không có nút Bắt đầu / Dừng ghi (v34, người dùng 09/11): app đang mở là luôn ghi, để không ai dừng ghi giữa
        # trận rồi mở replay xem bản đồ / nhà đối thủ khi ván còn đang đánh
        self._head_btns = self.head.create_window(0, 48, anchor="e", window=btns)
        self.head.bind("<Configure>", self._layout_head)

        self.content = tk.Frame(self.main, bg=C["bg"])
        self.content.pack(fill="both", expand=True, padx=24, pady=(16, 18))
        self.pages = {}
        self._build_matches()
        self._build_phone()
        self._build_settings()
        self._build_reports()
        self._build_keys()
        self._build_log()
        self._build_feedback()
        self.show_page("matches")
        self._refresh_status()
        self.root.after(500, self._tick)

    def _build_side_opts(self, side):
        """Đáy thanh bên, ngay trên thẻ Trạng thái: ô Khởi động cùng Windows + ô Tự dọn trận cũ (người dùng 07/11). Sau
        chữ mỗi ô có biểu tượng (i): rê chuột lên ô hoặc biểu tượng để đọc giải thích (theme.Tip)."""
        from . import winstartup
        C = theme.C
        box = tk.Frame(side, bg=C["sidebar"])
        box.pack(side="bottom", fill="x", padx=(14, 6))
        mdl = "Segoe MDL2 Assets" in tkfont.families()

        def row(text, var, cmd, tip):
            r = tk.Frame(box, bg=C["sidebar"])
            r.pack(fill="x")
            cb = ttk.Checkbutton(r, text=text, variable=var, command=cmd, style="Side.TCheckbutton")
            cb.pack(side="left")
            ic = tk.Label(r, text="\ue946" if mdl else "\u24d8", font=("Segoe MDL2 Assets", 10) if mdl else theme.F(11),
                          bg=C["sidebar"], fg=C["muted"], cursor="question_arrow")
            ic.pack(side="left", padx=(1, 0))
            ic.bind("<Enter>", lambda e: ic.configure(fg=C["gold_hi"]), add="+")
            ic.bind("<Leave>", lambda e: ic.configure(fg=C["muted"]), add="+")
            return cb, ic, theme.Tip(cb, tip), theme.Tip(ic, tip)

        self.var_winstart = tk.BooleanVar(value=winstartup.is_enabled())
        self.start_cb, self.start_icon, self.start_tip, self.start_icon_tip = row(
            "Khởi động cùng Windows", self.var_winstart, self._winstart_toggled, self._winstart_text)
        self.hack_cb, self.hack_icon, self.hack_tip, self.hack_icon_tip = row(
            "Báo âm thanh khi có hack", self.var_hack_sound, self._hack_sound_toggled, self._hack_sound_text)
        self.clean_text = ""                                   # mô tả + tình trạng tự dọn (chú thích khi rê chuột)
        self.clean_cb, self.clean_icon, self.clean_tip, self.clean_icon_tip = row(
            "Tự dọn trận cũ", self.var_clean, self._clean_toggled, lambda: self.clean_text)

    def _winstart_text(self):
        on = bool(self.var_winstart.get())
        return ("Khởi động cùng Windows đang " + ("BẬT" if on else "TẮT") + ".\n"
                "Bật: mở máy là AoE-MapCap tự chạy ngầm ở khay hệ thống (góc phải thanh tác vụ) và bật ghi sẵn, vào trận "
                "là tự ghi. Không sợ quên mở app mà mất trận.\n"
                "Ngoài trận app không làm gì nên không tốn tài nguyên, không nặng máy, chỉ nhẹ như Vietkey.\n"
                "Bật / tắt ngay tại ô này (Windows chạy app bằng tác vụ AoE-MapCap trong Task Scheduler, có quyền quản trị để "
                "đọc được game, không hỏi UAC).")

    def _hack_sound_text(self):
        on = bool(self.var_hack_sound.get())
        return ("Báo âm thanh khi phát hiện hack đang " + ("BẬT" if on else "TẮT") + ".\n"
                "Trong trận, AoE-MapCap đọc lệnh và tài nguyên của mọi người chơi và so với danh sách luật: điều khiển "
                "thú hoặc quân người khác, xoá nhà / quân người khác, ép người khác đầu hàng, lệnh cheat khi phòng không "
                "bật cheat, ra quân / nâng cấp thứ chưa mở, tài nguyên vượt 1.000.000 hoặc tăng đột biến >= 1000 trong "
                "1 giây, unit chỉ cheat mới có.\n"
                "Phát hiện: phát chuông cảnh báo (ô này), hiện thẻ cảnh báo ở góc phải trên cửa sổ app và đánh dấu "
                "trận trong danh sách Trận đã ghi.")

    def _hack_sound_toggled(self):
        self.cfg.hack_sound = bool(self.var_hack_sound.get())
        self._save_cfg()
        self._append("báo âm thanh khi phát hiện hack: " + ("BẬT" if self.cfg.hack_sound else "TẮT"))
        if self.cfg.hack_sound:
            play_alarm()                                   # nghe thử

    # ---- phát hiện hack (mapcap/hackcheck) ----------------------------------------------
    def _on_hack(self, ev):
        """Vi phạm mới (luồng chính, từ hàng đợi): nhật ký + chuông + thẻ cảnh báo + thông báo khay."""
        from .hackcheck import fmt_time
        line = f"{ev.get('name')} - {ev.get('label')} ({ev.get('detail')}) lúc {fmt_time(ev.get('t', 0))}"
        self._append("PHÁT HIỆN HACK: " + line)
        if ev.get("file") and ev.get("file") != getattr(self, "_hack_file", None):
            self._hack_file = ev.get("file")
            self.hack_events = []                          # trận mới: thẻ chỉ liệt kê vi phạm của trận này
        self.hack_events.append(ev)
        if self.cfg.hack_sound:
            play_alarm()
        self._show_hack_card()
        if self.tray is not None and not self._window_visible():
            try:
                self.tray.balloon("AoE-MapCap: phát hiện hack", line[:250])
            except Exception:  # noqa: BLE001
                pass
        self.table.reload()

    def _window_visible(self):
        try:
            return self.root.state() != "withdrawn" and bool(self.root.winfo_viewable())
        except tk.TclError:
            return False

    def _show_hack_card(self):
        """Thẻ cảnh báo ở góc phải trên cửa sổ app: mỗi người chơi hack một dòng (tên + các loại hack + giờ game)."""
        from .hackcheck import fmt_time
        C = theme.C
        if self.hack_card is not None:
            try:
                self.hack_card.destroy()
            except tk.TclError:
                pass
        card = tk.Frame(self.root, bg="#3a0d0d", highlightthickness=2, highlightbackground="#e53935")
        head = tk.Frame(card, bg="#3a0d0d")
        head.pack(fill="x", padx=10, pady=(8, 2))
        tk.Label(head, text="\u26a0  Phát hiện hack", font=theme.F(12, "bold"), bg="#3a0d0d", fg="#ff6b6b").pack(side="left")
        close = tk.Label(head, text="\u2715", font=theme.F(11), bg="#3a0d0d", fg=C["muted"], cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self._hide_hack_card())
        by = {}
        for ev in self.hack_events:
            by.setdefault((ev.get("player"), ev.get("name")), []).append(ev)
        self.hack_lines = []
        for (_p, name), evs in by.items():
            kinds = "; ".join(f"{e.get('label')} ({fmt_time(e.get('t', 0))})" for e in evs)
            lb = tk.Label(card, text=f"{name}: {kinds}", font=theme.F(10), bg="#3a0d0d", fg="#ffd7d7",
                          justify="left", anchor="w", wraplength=340)
            lb.pack(fill="x", padx=12, pady=1)
            self.hack_lines.append(lb.cget("text"))
        tk.Label(card, text="Trận này được đánh dấu có hack trong Trận đã ghi.", font=theme.F(9), bg="#3a0d0d",
                 fg=C["muted"], anchor="w").pack(fill="x", padx=12, pady=(2, 8))
        card.place(relx=1.0, x=-14, y=14, anchor="ne")
        card.lift()
        self.hack_card = card

    def _hide_hack_card(self):
        if self.hack_card is not None:
            try:
                self.hack_card.destroy()
            except tk.TclError:
                pass
            self.hack_card = None

    def _winstart_toggled(self):
        from . import winstartup
        want = bool(self.var_winstart.get())
        try:
            on = winstartup.set_enabled(want)
        except OSError as e:
            on = winstartup.is_enabled()
            messagebox.showerror(APP_TITLE, f"Không đổi được Khởi động cùng Windows: {e}")
        self.var_winstart.set(on)
        if not self.cfg.win_startup_init:
            self.cfg.win_startup_init = True               # người dùng đã tự chọn: không tự bật lại
            self._save_cfg()
        self._append("khởi động cùng Windows: " + ("BẬT (mở máy là tự chạy ngầm + bật ghi)" if on else "TẮT"))

    def _winstart_init(self):
        """Bản exe: lần mở đầu tiên tự bật Khởi động cùng Windows (mặc định bật: tránh quên mở app mà không ghi được
        trận), các lần sau chỉ sửa đường dẫn nếu thư mục app đã chuyển chỗ. Chạy từ mã nguồn (test) không tự bật."""
        from . import winstartup
        if not getattr(sys, "frozen", False) or not winstartup.supported():
            return
        try:
            if not self.cfg.win_startup_init:
                self.cfg.win_startup_init = True
                winstartup.set_enabled(True)
                self._save_cfg()
                self._append("khởi động cùng Windows: BẬT (mặc định; tắt bằng ô ở góc dưới thanh bên)")
            elif winstartup.refresh():
                self._append("khởi động cùng Windows: đăng ký lại tác vụ khởi động (đường dẫn app mới / chuyển từ cách cũ)")
        except OSError as e:
            self._append(f"khởi động cùng Windows: không ghi được ({e})")
        self.var_winstart.set(winstartup.is_enabled())

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
        if key == "reports":                      # file trận có thể đã bị xoá / dọn từ lần trước
            self._fill_reports()
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
        self._build_clean_bar(tab)
        ttk.Button(bot, text="▶  Xem replay", style="Accent.TButton", command=self.table.open_selected).pack(side="left")
        ttk.Style().configure("Bar.TButton", padding=(12, 6), width=-6)  # rộng theo chữ (mặc định tối thiểu 11 ký tự)
        for text, cmd in (("Xuất video...", self._export_selected), ("Mở file khác...", self._open_other),
                          ("Mở thư mục", self._open_dir), ("Xoá trận", self.table.delete_selected),
                          ("★ Ghim", self._pin_selected)):
            b = ttk.Button(bot, text=text, command=cmd, style="Bar.TButton")
            b.pack(side="left", padx=(6, 0))
            if cmd == self._open_dir:
                self.btn_open_dir = b
                theme.Tip(b, lambda: "Mở " + self.table.var_dir.get() + " (đổi trong Cài đặt)")
            if cmd == self._pin_selected:
                self.btn_pin = b
                theme.Tip(b, "Ghim trận đang chọn để giữ mãi: Tự dọn trận cũ không bao giờ xoá trận ghim (vẫn tự "
                             "xoá được bằng nút Xoá trận). Trận ghim có dấu ★ và viền vàng sáng; tích \"★ Trận đã ghim\" "
                             "ở trên bảng để chỉ xem các trận ghim. Bấm lại để bỏ ghim.")
        theme.Tip(self.table.pin_check, "Chỉ hiện các trận đã ghim ★")
        # Báo cáo hack: hàng trên, ngay trái nút Làm mới (hàng nút dưới đã kín ở cửa sổ 980 px)
        entry = next((w for w in self.table.bar.winfo_children() if isinstance(w, ttk.Entry)), None)
        self.btn_report = ttk.Button(self.table.bar, text="\u2691 Báo cáo hack", command=self._report_selected)
        self.btn_report.pack(side="right", padx=(4, 0), **({"before": entry} if entry is not None else {}))
        self.table.is_busy = self._is_recording_path
        self.table.prefetch_ok = lambda: self._mode_now() != "rec"   # không quét trận cũ ở nền khi đang ghi
        # dòng trạng thái: bên trái hàng trên bảng (hàng nút dưới đã kín ở cửa sổ 980 px); chữ dài tự rút gọn "…"
        # (không tràn), rê chuột xem đủ
        self.status_lbl = ttk.Label(self.table.bar, text="", style="Muted.TLabel", anchor="w", width=1)
        self.status_lbl.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.status_lbl.bind("<Configure>", lambda e: self._fit_status(), add="+")
        self.table.var_status.trace_add("write", lambda *_: self._fit_status())
        theme.Tip(self.status_lbl, lambda: self.table.var_status.get()
                  if self.status_lbl.cget("text") != self.table.var_status.get() else "")

    def _fit_status(self):
        from tkinter import font as tkfont
        full = self.table.var_status.get()
        lbl = self.status_lbl
        w = lbl.winfo_width() - 4
        f = tkfont.Font(font=ttk.Style().lookup("Muted.TLabel", "font") or "TkDefaultFont")
        txt = full
        if w > 1 and f.measure(txt) > w:
            while txt and f.measure(txt.rstrip() + "…") > w:
                txt = txt[:-1]
            txt = txt.rstrip() + "…" if txt else ""
        if lbl.cget("text") != txt:
            lbl.configure(text=txt)

    # ---- báo cáo trận có hack (mapcap/report: file lên máy chủ, admin xem ở trang thống kê) -------------
    def _report_selected(self):
        """Mở hộp thoại báo cáo, chọn sẵn trận đang chọn trong bảng (đổi được trận ngay trong hộp thoại)."""
        if not report_choices(self.table.infos, self._is_recording_path):
            messagebox.showinfo(APP_TITLE, "Chưa có trận nào báo cáo được (trận đang ghi báo cáo được khi kết thúc).")
            return
        ReportDialog(self, self.table.selected_path())

    def _report_sent(self, rid, path, info, suspect, note):
        from replay.library import hack_text

        from . import report
        try:
            report.add_history(self.cfg.resolved_out_dir(), rid, path, info, suspect, note, hack_text(info))
        except OSError as e:
            self._append(f"không lưu được lịch sử báo cáo: {e}")
        self._fill_reports()

    # ---- trang Lịch sử báo cáo (người dùng 12/11): các trận máy này đã báo cáo hack ---------------
    REPORT_COLS = (("ts", "Ngày gửi", 128, "w"), ("id", "Mã", 56, "center"), ("match", "Trận", 128, "w"),
                   ("map", "Map", 150, "w"), ("suspect", "Người bị nghi", 130, "w"), ("note", "Ghi chú", 200, "w"))

    def _build_reports(self):
        import time
        C = theme.C
        tab = tk.Frame(self.content, bg=C["bg"])
        self.pages["reports"] = tab
        bot = ttk.Frame(tab)
        bot.pack(side="bottom", fill="x", pady=(12, 0))
        self.btn_rep_play = ttk.Button(bot, text="▶  Xem replay", style="Accent.TButton",
                                       command=self._report_open)
        self.btn_rep_play.pack(side="left")
        ttk.Button(bot, text="⚑ Báo cáo trận khác...", style="Bar.TButton",
                   command=lambda: self._report_selected()).pack(side="left", padx=(6, 0))
        self.var_rep_detail = tk.StringVar(value="")
        ttk.Label(tab, textvariable=self.var_rep_detail, style="Detail.TLabel", justify="left",
                  wraplength=700).pack(side="bottom", fill="x", pady=(8, 0))
        mid = ttk.Frame(tab)
        mid.pack(fill="both", expand=True)
        tv = self.rep_tree = ttk.Treeview(mid, columns=[c[0] for c in self.REPORT_COLS], show="headings",
                                          selectmode="browse")
        for key, label, w, anchor in self.REPORT_COLS:
            tv.heading(key, text=label)
            tv.column(key, width=w, anchor=anchor, stretch=key in ("map", "note"))
        tv.tag_configure("odd", background=C["bg2"])
        tv.tag_configure("gone", foreground=C["dim"])
        sb = ttk.Scrollbar(mid, command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.rep_empty = tk.Label(tv, text="Chưa gửi báo cáo nào.\nỞ trang Trận đã ghi, chọn trận rồi bấm "
                                  "⚑ Báo cáo hack: trận đã gửi sẽ hiện ở đây.", bg=C["panel"], fg=C["muted"],
                                  font=theme.F(10), justify="center")
        tv.bind("<<TreeviewSelect>>", lambda e: self._report_detail())
        tv.bind("<Double-1>", lambda e: self._report_open())
        tv.bind("<Return>", lambda e: self._report_open())
        self._rep_items = {}
        self._fmt_t = lambda t: time.strftime("%d/%m/%Y %H:%M", time.localtime(t)) if t else ""
        self._fill_reports()

    def _fill_reports(self):
        from . import report
        tv = self.rep_tree
        tv.delete(*tv.get_children())
        self._rep_items = {}
        items = report.load_history(self.cfg.resolved_out_dir())
        for k, it in enumerate(items):
            iid = f"r{k}"
            self._rep_items[iid] = it
            note = " ".join(str(it.get("note", "")).split())
            gone = not os.path.exists(it.get("path", ""))
            tags = (("odd",) if k % 2 else ()) + (("gone",) if gone else ())
            tv.insert("", "end", iid=iid, tags=tags, values=(
                self._fmt_t(it.get("ts")), f"#{it.get('id')}" if it.get("id") is not None else "",
                self._fmt_t(it.get("created")), it.get("map", ""), it.get("suspect") or "Không rõ", note))
        if items:
            self.rep_empty.place_forget()
            tv.selection_set("r0")
            tv.focus("r0")
        else:
            self.rep_empty.place(relx=0.5, rely=0.45, anchor="center")
        self._report_detail()

    def _report_detail(self):
        sel = self.rep_tree.selection()
        it = self._rep_items.get(sel[0]) if sel else None
        if not it:
            self.var_rep_detail.set("")
            self.btn_rep_play.configure(state="disabled")
            return
        gone = not os.path.exists(it.get("path", ""))
        parts = [it.get("file", ""), f"{it.get('format', '')} · {it.get('duration', '')}".strip(" ·"),
                 "Người chơi: " + ", ".join(it.get("players") or [])]
        if it.get("auto"):
            parts.append("App đã phát hiện: " + it["auto"])
        if it.get("note"):
            parts.append("Ghi chú: " + " ".join(str(it["note"]).split()))
        if gone:
            parts.append("File trận không còn trên máy (đã xoá / dọn / đổi thư mục): không xem lại được.")
        self.var_rep_detail.set("   ·   ".join(p for p in parts if p))
        self.btn_rep_play.configure(state="disabled" if gone else "normal")

    def _report_open(self):
        sel = self.rep_tree.selection()
        it = self._rep_items.get(sel[0]) if sel else None
        if it and os.path.exists(it.get("path", "")):
            self._launch_replay(it["path"])

    # ---- điện thoại: máy chủ trong mạng nhà cho app Android (docs/13) ----------------------
    def _build_phone(self):
        C = theme.C
        tab = tk.Frame(self.content, bg=C["bg"])
        self.pages["phone"] = tab
        self.var_phone_auto = tk.BooleanVar(value=self.cfg.phone_server)
        self.var_phone_addr = tk.StringVar(value="")
        body = self._card(tab, "Cho điện thoại xem trận")
        self.phone_qr = tk.Label(body, bg=C["panel"])
        self.phone_qr.pack(side="left", anchor="n", padx=(0, 22))
        right = tk.Frame(body, bg=C["panel"])
        right.pack(side="left", fill="both", expand=True, anchor="n")
        self.phone_state = tk.Label(right, text="", bg=C["panel"], fg="#ffffff", font=theme.F(12, "bold"), anchor="w")
        self.phone_state.pack(fill="x")
        self.phone_net = tk.Label(right, text="", bg=C["panel"], fg=C["muted"], font=theme.F(10), anchor="w",
                                  justify="left", wraplength=600)
        self.phone_net.pack(fill="x", pady=(4, 0))
        row = tk.Frame(right, bg=C["panel"])
        row.pack(fill="x", pady=(10, 6))
        self.btn_phone = ttk.Button(row, text="", command=self._phone_toggle, width=24)
        self.btn_phone.pack(side="left")
        ttk.Checkbutton(row, text="Tự bật khi mở AoE-MapCap", variable=self.var_phone_auto, style="Card.TCheckbutton",
                        command=self._phone_auto_changed).pack(side="left", padx=(16, 0))
        row = tk.Frame(right, bg=C["panel"])
        row.pack(fill="x", pady=(4, 10))
        ttk.Label(row, text="Địa chỉ trong mạng nhà (nhập tay)", style="Card.TLabel").pack(side="left")
        self.phone_entry = ttk.Entry(row, textvariable=self.var_phone_addr, width=30, state="readonly")
        self.phone_entry.pack(side="left", padx=(10, 6))
        ttk.Button(row, text="Sao chép", command=self._phone_copy).pack(side="left")
        steps = ("1. Điện thoại dùng 4G hay Wi-Fi nào cũng được; máy tính cần có Internet và để AoE-MapCap mở.\n"
                 "2. Chưa có app: quét mã bằng camera điện thoại. Trang mở ra xem trận được ngay và có nút Tải app "
                 "(Android 8 trở lên).\n"
                 "3. Đã có app: mở app AoE-MapCap, bấm Quét mã QR (chỉ cần quét một lần). Trận đã mở được lưu trên "
                 "điện thoại, xem được cả khi máy tính tắt.")
        ttk.Label(right, text=steps, style="Card.TLabel", justify="left", wraplength=600).pack(fill="x", anchor="w")
        ttk.Label(right, text="Hình game lấy từ bộ cài game trên máy này và chỉ gửi sang điện thoại của bạn: cùng "
                              "mạng thì gửi thẳng, khác mạng thì đi qua trạm chuyển tiếp của AoE-MapCap (không lưu lại). "
                              "Mã QR là chìa khoá vào máy này, đừng chia sẻ. Lần đầu mở một trận, máy tính cần khoảng một phút để chuẩn bị; khi đang ghi trận, việc "
                              "chuẩn bị đợi tới hết trận để không làm game giật.",
                  style="CardMuted.TLabel", justify="left", wraplength=600).pack(fill="x", anchor="w", pady=(10, 0))
        self._phone_refresh()

    def _phone_running(self):
        return self.phone is not None and self.phone.running

    def _phone_toggle(self):
        if self._phone_running():
            self._phone_stop()
        else:
            self._phone_start()

    def _ask_game_dir(self):
        """Hỏi thư mục game (khi không tự tìm được); lưu vào cấu hình. None nếu bỏ qua / sai."""
        from .engine import valid_game_dir
        d = filedialog.askdirectory(title="Chọn thư mục game AoE-HD / AOE1R (có thư mục data bên trong)")
        if not d or not valid_game_dir(d):
            if d:
                messagebox.showerror(APP_TITLE, "Thư mục này không có dữ liệu game AoE-HD / AOE1R "
                                     "(empires.dat, graphic.drs hoặc graphics.drs trong data / data2).")
            return None
        self.cfg.game_dir = os.path.normpath(d)
        self._save_cfg()
        return d

    def _phone_start(self, quiet=False):
        """quiet: tự bật lúc mở app, không hỏi / không hiện hộp lỗi (ghi vào Nhật ký)."""
        from .engine import resolve_game_dir
        gd = resolve_game_dir(self.cfg.game_dir)
        if gd is None:
            if quiet:
                self._append("điện thoại: chưa biết thư mục game, chưa bật (bật trong mục Điện thoại)")
                return
            gd = self._ask_game_dir()
            if gd is None:
                return
        raw = self.cfg.raw_dir()
        os.makedirs(raw, exist_ok=True)
        try:
            if self.phone is None:
                from .mobile_server import PhoneServer
                self.phone = PhoneServer(log=lambda m: self.q.put("điện thoại: " + m))
                self.root.after(1000, self._phone_tick)
            url = self.phone.start(raw, gd, busy=lambda: self._recording)
        except Exception as e:  # noqa: BLE001
            self._append(f"điện thoại: không bật được: {e}")
            if not quiet:
                messagebox.showerror(APP_TITLE, f"Không bật được máy chủ cho điện thoại: {e}")
            return
        self._append(f"=== điện thoại: đã bật, địa chỉ {url}")
        self._phone_refresh()

    def _phone_stop(self):
        if self.phone is not None:
            self.phone.stop()
            self._append("=== điện thoại: đã tắt")
        self._phone_refresh()

    def _phone_auto_changed(self):
        self.cfg.phone_server = bool(self.var_phone_auto.get())
        self._save_cfg()

    def _phone_copy(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.var_phone_addr.get())

    @staticmethod
    def qr_image(text, size=232):
        """Mã QR (thư viện qrcode chỉ để lấy ma trận; vẽ bằng PIL, phóng to số nguyên lần cho sắc nét)."""
        import qrcode
        from PIL import Image
        q = qrcode.QRCode(border=3, error_correction=qrcode.constants.ERROR_CORRECT_M)
        q.add_data(text)
        q.make(fit=True)
        m = q.get_matrix()
        n = len(m)
        img = Image.new("L", (n, n), 255)
        img.putdata([0 if v else 255 for r in m for v in r])
        k = max(1, size // n)
        return img.resize((n * k, n * k), Image.NEAREST)

    def _qr_photo(self, text):
        from PIL import ImageTk
        return ImageTk.PhotoImage(self.qr_image(text))

    def _phone_refresh(self):
        C = theme.C
        on = self._phone_running()
        if on:
            self.phone_state.configure(text="ĐANG BẬT — quét mã bên trái bằng điện thoại", fg=C["gold_hi"])
            self.btn_phone.configure(text="Tắt", style="TButton")
            self.var_phone_addr.set(self.phone.address())
            try:
                self._phone_img = self._qr_photo(self.phone.pair_url())
            except Exception as e:  # noqa: BLE001  - thiếu thư viện qrcode: vẫn nhập tay được
                self._phone_img = None
                self._append(f"điện thoại: không tạo được mã QR: {e}")
        else:
            self.phone_state.configure(text="Đang tắt", fg=C["muted"])
            self.btn_phone.configure(text="Bật cho điện thoại xem trận", style="Accent.TButton")
            self.var_phone_addr.set("")
            self._phone_img = None
        self._phone_net_refresh()
        if self._phone_img is None:
            from PIL import Image, ImageTk
            self._phone_img = ImageTk.PhotoImage(Image.new("RGB", (232, 232), C["panel2"]))
        self.phone_qr.configure(image=self._phone_img)
        if self.tray is not None:
            self.tray.phone_label = "Tắt cho điện thoại" if on else "Bật cho điện thoại"

    def _phone_net_refresh(self):
        """Dòng trạng thái kết nối qua Internet (trạm chuyển tiếp, mapcap/relay_client.py)."""
        C = theme.C
        if not self._phone_running():
            self.phone_net.configure(text="")
            return
        st = self.phone.relay_state()
        if st == "online":
            text, fg = "Qua Internet: sẵn sàng. Điện thoại dùng 4G hay Wi-Fi khác đều xem được.", C["green"]
        elif st == "connecting":
            text, fg = "Qua Internet: đang kết nối…", C["muted"]
        else:
            why = st.split(":", 1)[1].strip() if ":" in st else ""
            text = ("Qua Internet: chưa kết nối được" + (f" ({why[:80]})" if why else "") +
                    ". Đang thử lại; trong lúc đó điện thoại cùng Wi-Fi vẫn xem được.")
            fg = C["lose"]
        if self.phone_net.cget("text") != text:
            self.phone_net.configure(text=text, fg=fg)

    def _phone_tick(self):
        try:
            self._phone_net_refresh()
        except tk.TclError:
            return                                        # cửa sổ đã đóng
        self.root.after(1000, self._phone_tick)

    def _scroll_page(self, key):
        """Trang cuộn được (nội dung dài hơn cửa sổ, vd Cài đặt từ v28): trả về khung để đặt nội dung."""
        C = theme.C
        outer = tk.Frame(self.content, bg=C["bg"])
        self.pages[key] = outer
        cv = tk.Canvas(outer, bg=C["bg"], highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(outer, command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(6, 0))
        cv.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(cv, bg=C["bg"])
        win = cv.create_window(0, 0, window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))

        def wheel(e):
            if inner.winfo_height() > cv.winfo_height():
                cv.yview_scroll(int(-e.delta / 120) or (-1 if e.delta > 0 else 1), "units")
        outer.bind("<Enter>", lambda e: outer.bind_all("<MouseWheel>", wheel))
        outer.bind("<Leave>", lambda e: outer.unbind_all("<MouseWheel>"))
        return inner

    def _build_settings(self):
        tab = self._scroll_page("settings")
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
        self.var_tele = tk.BooleanVar(value=cfg.telemetry)
        self.var_tray = tk.BooleanVar(value=cfg.close_to_tray)
        self.var_clean_limit = tk.DoubleVar(value=cfg.clean_limit_gb)
        self.var_clean_days = tk.IntVar(value=int(cfg.clean_days))

        fd = self._card(tab, "Thư mục lưu trận")
        ttk.Entry(fd, textvariable=self.var_out, width=60).grid(row=0, column=0, sticky="we", pady=6, padx=(0, 10))
        ttk.Button(fd, text="Chọn...", command=self._choose_dir).grid(row=0, column=1, sticky="w", pady=6)
        ttk.Button(fd, text="Mở thư mục", command=self._open_dir).grid(row=0, column=2, sticky="w", pady=6,
                                                                       padx=(8, 0))
        ttk.Label(fd, text="Trận ghi nằm trong thư mục con Raw; đổi thư mục rồi bấm Lưu cài đặt",
                  style="CardMuted.TLabel").grid(row=1, column=0, columnspan=3, sticky="w")
        fd.columnconfigure(0, weight=1)

        rec = self._card(tab, "Ghi trận")
        ttk.Label(rec, text="Nhịp đọc game (lần/giây)", style="Card.TLabel").grid(row=0, column=0, sticky="w", **pad)
        ttk.Spinbox(rec, from_=1, to=60, textvariable=self.var_cap, width=8).grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(rec, text="25 = mượt như game; thấp hơn thì file nhỏ hơn", style="CardMuted.TLabel").grid(
            row=0, column=2, sticky="w", **pad)
        ttk.Checkbutton(rec, text="Bấm X: chạy ngầm ở khay hệ thống (góc phải thanh tác vụ), vẫn ghi trận",
                        variable=self.var_tray, style="Card.TCheckbutton").grid(row=3, column=0, columnspan=4,
                                                                                sticky="w", pady=(10, 2))
        ttk.Checkbutton(rec, text="Gửi thống kê sử dụng (mã máy ngẫu nhiên, tên người chơi, phiên bản, IP; không gửi trận đấu)",
                        variable=self.var_tele, style="Card.TCheckbutton").grid(row=4, column=0, columnspan=4,
                                                                                sticky="w", pady=2)
        rec.columnconfigure(2, weight=1)

        cl = self._card(tab, "Dọn trận cũ")
        ttk.Checkbutton(cl, text="Tự dọn trận cũ (chuyển vào Thùng rác, khôi phục được; trận đã ghim ★ không bao giờ bị dọn)",
                        variable=self.var_clean, style="Card.TCheckbutton", command=self._clean_toggled).grid(
            row=0, column=0, columnspan=6, sticky="w", pady=(0, 6))
        ttk.Label(cl, text="Khi tổng trận vượt", style="Card.TLabel").grid(row=1, column=0, sticky="w", **pad)
        ttk.Spinbox(cl, from_=0.5, to=10000, increment=1, textvariable=self.var_clean_limit, width=7).grid(
            row=1, column=1, sticky="w", pady=6)
        ttk.Label(cl, text="GB, dọn các trận cũ hơn", style="Card.TLabel").grid(row=1, column=2, sticky="w", padx=8)
        ttk.Spinbox(cl, from_=1, to=3650, textvariable=self.var_clean_days, width=6).grid(row=1, column=3, sticky="w",
                                                                                      pady=6)
        ttk.Label(cl, text="ngày (cũ nhất trước, tới khi về dưới ngưỡng)", style="Card.TLabel").grid(
            row=1, column=4, sticky="w", padx=8)
        ttk.Button(cl, text="Kiểm tra / dọn ngay", command=self._clean_check).grid(
            row=1, column=5, sticky="e", pady=6)
        ttk.Label(cl, textvariable=self.var_clean_usage, style="CardMuted.TLabel", justify="left").grid(
            row=2, column=0, columnspan=6, sticky="w", pady=(4, 0))
        # Nén trận cũ: chuyển từ hàng nút dưới bảng Trận đã ghi (hàng đó tràn ở cửa sổ hẹp)
        ttk.Button(cl, text="Nén trận cũ", command=self._compact_old).grid(row=3, column=0, sticky="w", pady=(10, 0))
        ttk.Label(cl, text="Trận ghi bằng bản cũ nhỏ đi khoảng 5 lần, không mất dữ liệu", style="CardMuted.TLabel").grid(
            row=3, column=1, columnspan=5, sticky="w", padx=10, pady=(10, 0))
        cl.columnconfigure(4, weight=1)

        self._build_rules_card(tab)

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
        ttk.Label(bot, text="Cài đặt ghi trận có hiệu lực ngay khi đang không trong trận (đang trong trận: từ lúc hết trận).",
                  style="Muted.TLabel").pack(
            side="left", padx=14)

    def _build_feedback(self):
        """Trang Góp ý (người dùng 07/11): ý kiến / báo lỗi đăng ở GitHub Discussions của dự án, tác giả xem danh sách và
        trả lời ở đó. Nút mở sẵn trang viết bài đúng mục (Q&A = báo lỗi, Ideas = góp ý), điền sẵn phiên bản app +
        Windows; nút sao chép Nhật ký để dán vào bài."""
        C = theme.C
        tab = tk.Frame(self.content, bg=C["bg"])
        self.pages["feedback"] = tab

        def para(parent, text, fg, pady):
            """Đoạn chữ xuống dòng theo bề rộng thật của thẻ (cửa sổ nhỏ không bị cắt)."""
            lbl = tk.Label(parent, text=text, bg=C["panel"], fg=fg, font=theme.F(10), justify="left", anchor="w",
                           wraplength=760)
            lbl.bind("<Configure>", lambda e: lbl.configure(wraplength=max(200, e.width - 4)))
            lbl.pack(fill="x", pady=pady)

        body = self._card(tab, "Gửi ý kiến / báo lỗi")
        para(body, "Ý kiến và báo lỗi được đăng ở trang Thảo luận của AoE-MapCap trên GitHub. Tác giả đọc và trả lời ở "
                   "đó; bạn cũng xem được lỗi người khác đã báo, ý kiến tương tự để bình luận thêm.", C["text"], 0)
        steps = ("1.  Bấm Báo lỗi hoặc Góp ý bên dưới: trình duyệt mở sẵn trang viết bài, đã điền phiên bản app và Windows.",
                 "2.  Đăng nhập GitHub (chưa có tài khoản thì bấm Sign up, miễn phí, chỉ cần email).",
                 "3.  Viết tiêu đề và mô tả (tiếng Việt thoải mái), kéo thả ảnh chụp màn hình vào ô viết nếu có, rồi bấm "
                 "Start discussion.")
        for t in steps:
            para(body, t, C["muted"], (6, 0))
        row = tk.Frame(body, bg=C["panel"])
        row.pack(fill="x", pady=(16, 0))
        self.btn_bug = ttk.Button(row, text="Báo lỗi", style="Accent.TButton", width=14,
                                  command=lambda: self._feedback_open("bug"))
        self.btn_bug.pack(side="left")
        self.btn_idea = ttk.Button(row, text="Góp ý", width=14, command=lambda: self._feedback_open("idea"))
        self.btn_idea.pack(side="left", padx=(10, 0))
        self.btn_fb_list = ttk.Button(row, text="Xem các ý kiến đã gửi", command=lambda: self._feedback_open("list"))
        self.btn_fb_list.pack(side="left", padx=(10, 0))
        self.btn_copy_log = ttk.Button(row, text="Sao chép Nhật ký", command=self._feedback_copy_log)
        self.btn_copy_log.pack(side="left", padx=(10, 0))
        self.fb_msg = tk.Label(body, text="", bg=C["panel"], fg=C["gold_hi"], font=theme.F(10), anchor="w")
        self.fb_msg.pack(fill="x", pady=(8, 0))

        tips = self._card(tab, "Báo lỗi dễ sửa hơn khi có")
        for t in ("•  Lỗi xảy ra lúc nào, bạn đã bấm gì, mong đợi điều gì.",
                  "•  Ảnh chụp màn hình (Win + Shift + S rồi dán thẳng vào ô viết).",
                  "•  Nhật ký của app: bấm Sao chép Nhật ký rồi dán vào bài.",
                  "•  Lỗi khi xem lại một trận: đính kèm file trận (.aoerec, nén .zip nếu lớn; nút Mở thư mục ở trang Trận "
                  "đã ghi)."):
            para(tips, t, C["muted"], (0, 4))

    @staticmethod
    def _system_info():
        import platform
        win = platform.version()                                   # vd 10.0.26200
        try:
            build = int(win.split(".")[2])
            name = "Windows 11" if build >= 22000 else f"Windows {platform.release()}"
        except (IndexError, ValueError):
            name = f"Windows {platform.release()}"
        return f"AoE-MapCap v{APP_VERSION}, {name} ({win})"

    def _feedback_url(self, kind):
        """Đường dẫn trang Thảo luận: list = danh sách; bug / idea = trang viết bài đúng mục, điền sẵn tiêu đề + mẫu."""
        from urllib.parse import urlencode
        if kind == "list":
            return self.FEEDBACK_URL
        info = self._system_info()
        if kind == "bug":
            q = {"category": "q-a", "title": "[Lỗi] ",
                 "body": "**Lỗi gì:**\n\n\n**Các bước để gặp lỗi:**\n1. \n2. \n\n**Mong đợi:**\n\n\n"
                         "**Nhật ký** (trang Góp ý > Sao chép Nhật ký, dán vào đây):\n\n\n---\n" + info}
        else:
            q = {"category": "ideas", "title": "[Góp ý] ",
                 "body": "**Ý kiến / tính năng mong muốn:**\n\n\n**Vì sao hữu ích:**\n\n\n---\n" + info}
        return self.FEEDBACK_URL + "/new?" + urlencode(q)

    def _feedback_open(self, kind):
        import webbrowser
        url = self._feedback_url(kind)
        try:
            ok = webbrowser.open(url)
        except Exception:  # noqa: BLE001
            ok = False
        if not ok:
            self.root.clipboard_clear()
            self.root.clipboard_append(url)
            self.fb_msg.configure(text="Không mở được trình duyệt: đã sao chép đường dẫn, dán vào trình duyệt.")
        self._append(f"góp ý: mở {self.FEEDBACK_URL}" + ("" if kind == "list" else f" ({kind})"))

    def _feedback_copy_log(self):
        log = self.txt.get("1.0", "end").strip()
        lines = log.splitlines()[-300:]                       # đủ ngữ cảnh, vừa một bài viết
        text = self._system_info() + "\n```\n" + "\n".join(lines) + "\n```"
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.fb_msg.configure(text=f"Đã sao chép {len(lines)} dòng Nhật ký: dán (Ctrl+V) vào bài viết.")

    def _build_rules_card(self, tab):
        """Cài đặt -> Phát hiện hack (người dùng 12/11): danh sách luật app dùng để đánh dấu người chơi hack."""
        from .hackcheck import RULE_DETAILS, RULES
        C = theme.C
        card = self._card(tab, "Phát hiện hack")
        intro = tk.Label(card, text="Trong lúc ghi trận, app kiểm tra lệnh và chỉ số của mọi người chơi theo các luật dưới đây. "
                            "Vi phạm một luật là người đó bị đánh dấu hack: báo bằng chuông (ô Báo âm thanh khi có hack ở "
                            "thanh bên), thẻ cảnh báo trong app, và trận được đánh dấu ⚠ Có hack. Phòng bật cheat thì "
                            "L5, S1-S3 không tính.", bg=C["panel"], fg=C["muted"], font=theme.F(9), justify="left",
                 anchor="w", wraplength=600)
        intro.grid(row=0, column=0, columnspan=3, sticky="we", pady=(0, 8))
        self.rule_rows = []
        for r, (code, label) in enumerate(RULES.items(), start=1):
            tk.Label(card, text=code, bg=C["panel"], fg=C["gold_hi"], font=theme.F(10, "bold"), anchor="nw").grid(
                row=r, column=0, sticky="nw", padx=(0, 12), pady=3)
            tk.Label(card, text=label, bg=C["panel"], fg=C["text"], font=theme.F(10, "bold"), anchor="nw",
                     justify="left").grid(row=r, column=1, sticky="nw", padx=(0, 16), pady=3)
            d = tk.Label(card, text=RULE_DETAILS.get(code, ""), bg=C["panel"], fg=C["muted"], font=theme.F(9),
                         anchor="nw", justify="left", wraplength=420)
            d.grid(row=r, column=2, sticky="nwe", pady=3)
            self.rule_rows.append((code, label, d))
        card.columnconfigure(2, weight=1)

        def rewrap(e):
            intro.configure(wraplength=max(300, e.width - 8))
            w = max(240, e.width - 330)
            for _c, _l, d in self.rule_rows:
                d.configure(wraplength=w)
        card.bind("<Configure>", rewrap, add="+")

    def _build_keys(self):
        """Tab Phím tắt (người dùng 11/11): phím điều khiển trình xem replay, cùng danh sách với bảng Esc trong replay."""
        from replay.keys import KEYS_HELP
        C = theme.C
        tab = tk.Frame(self.content, bg=C["bg"])
        self.pages["keys"] = tab
        txt = tk.Text(tab, wrap="word", font=theme.F(10), padx=18, pady=14, cursor="arrow", spacing1=3, spacing3=3,
                      **theme.text_widget_colors())
        sb = ttk.Scrollbar(tab, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.tag_configure("key", foreground=C["gold_hi"], font=theme.F(10, "bold"))
        txt.tag_configure("note", foreground=C["muted"])
        kf = tkfont.Font(font=theme.F(10, "bold"))
        kw = max(kf.measure(k) for k, _d in KEYS_HELP) + 28
        txt.configure(tabs=(kw,))
        txt.tag_configure("row", lmargin2=kw)
        txt.insert("end", "Trong lúc xem replay bấm Esc hoặc ? để hiện bảng này ngay trên màn hình.\n\n", "note")
        for k, d in KEYS_HELP:
            txt.insert("end", k, ("key", "row"))
            txt.insert("end", "\t" + d + "\n", "row")
        txt.configure(state="disabled")
        txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y", padx=(4, 0))
        self.keys_text = txt

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
        cfg.telemetry = bool(self.var_tele.get())
        cfg.close_to_tray = bool(self.var_tray.get())
        try:
            cfg.clean_limit_gb = float(self.var_clean_limit.get())
            cfg.clean_days = int(self.var_clean_days.get())
        except (tk.TclError, ValueError) as e:
            messagebox.showerror(APP_TITLE, f"Giá trị không hợp lệ: {e}")
            return None
        cfg.auto_clean = bool(self.var_clean.get())
        cfg.hack_sound = bool(self.var_hack_sound.get())
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
        self.var_clean_limit.set(cfg.clean_limit_gb)
        self.var_clean_days.set(cfg.clean_days)
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
        if self._phone_running() and os.path.normcase(new_raw) != os.path.normcase(self.phone.folder):
            self._phone_start()                         # máy chủ điện thoại theo thư mục lưu mới
        self._append("đã lưu cài đặt")
        self._clean_check()                             # ngưỡng / thời hạn / thư mục có thể đã đổi
        if self.engine is not None:                     # áp dụng cho bộ ghi: bật lại khi đang không trong trận
            self._apply_pending = True
            self._apply_settings_when_idle()

    def _apply_settings_when_idle(self):
        """Cài đặt mới cho bộ ghi: dừng rồi bật lại ngay nếu đang ngoài trận; đang ghi trận thì chờ hết trận."""
        if not getattr(self, "_apply_pending", False) or self.engine is None or self._stopping:
            return
        if self._mode_now() == "rec":
            return                                      # gọi lại từ _refresh_status khi hết trận
        self._apply_pending = False
        self._append("=== áp dụng cài đặt mới: bật lại bộ ghi")
        self._restart_soon = True
        self._stop()

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
                             progress=lambda label, text: self.q.put(("__progress__", label, text)),
                             on_hack=lambda ev: self.q.put(("__hack__", ev)))
        self.thread = threading.Thread(target=self._run_engine, daemon=True)
        import time
        self._engine_started = time.monotonic()
        self.thread.start()
        self._stopping = False
        self.state_text = "chờ game"
        self._refresh_status()
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
        """Bật bộ ghi (app đang mở là luôn ghi, v34). Bỏ qua khi đã chạy, đang thoát, hoặc bản này đã bị chặn vì quá
        cũ (cửa sổ chặn chỉ còn Cập nhật / Thoát)."""
        if self.engine is not None or self._quitting or getattr(getattr(self, "updater", None), "block_win", None) is not None:
            return
        self._append("=== bật bộ ghi (AoE-MapCap đang mở là luôn ghi trận)")
        self._start()

    def _engine_done(self):
        """Bộ ghi đã dừng. Luôn ghi: bật lại (ngay nếu vừa áp dụng cài đặt, 3 s nếu dừng ngoài ý muốn), trừ khi đang
        thoát / chuẩn bị cài bản mới / bản đã bị chặn."""
        soon = getattr(self, "_restart_soon", False)
        self._restart_soon = False
        if self._quitting or self._restart_recording or getattr(getattr(self, "updater", None), "block_win", None) is not None:
            return
        if soon:
            self.root.after(300, self._auto_start)
            return
        import time
        quick = time.monotonic() - getattr(self, "_engine_started", 0.0) < 30      # vừa bật đã dừng: lỗi lặp lại
        self._fail_streak = getattr(self, "_fail_streak", 0) + 1 if quick else 1
        delay = min(60, 3 * 2 ** (self._fail_streak - 1))                          # 3, 6, 12, ... tối đa 60 s
        self._append(f"bộ ghi dừng ngoài ý muốn: bật lại sau {delay} giây")
        self.root.after(delay * 1000, self._auto_start)

    def _on_update_block(self):
        """Bản này đã ngừng hỗ trợ: dừng bộ ghi đang chờ game (cửa sổ chặn chỉ còn Cập nhật / Thoát)."""
        if self.engine is not None and self.stop_event and not self._busy_reason():
            self._stop()

    def _stop(self):
        if self.stop_event:
            self.stop_event.set()
            self._append("=== yêu cầu dừng ghi: đang chốt dữ liệu trận (nếu có)...")
            self._stopping = True
            self._refresh_status()

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
            d = self._ask_game_dir()
        return d

    def _being_recorded(self, path):
        """Trận đang ghi: chưa cho xem / xuất (ván còn đang đánh, v34). File cũng bị bộ ghi giữ độc quyền."""
        if not self._is_recording_path(path):
            return False
        messagebox.showinfo(APP_TITLE, "Trận này đang được ghi: xem lại / xuất video được khi trận kết thúc.")
        return True

    def _launch_replay(self, path):
        if self._being_recorded(path):
            return
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

    # ---- tự dọn trận cũ (mapcap/retention) -----------------------------------------------
    CLEAN_EVERY_MS = 30 * 60 * 1000

    def _build_clean_bar(self, tab):
        """Tự dọn trận cũ trên trang Trận đã ghi, không lấy thêm chiều cao của bảng (ô bật / tắt ở đáy thanh bên,
        _build_side_opts). Cảnh báo ổ sắp đầy là chữ đỏ ngắn đầu hàng trên bảng (chi tiết khi rê chuột). Chỉ
        lúc chờ đồng ý lần dọn đầu mới có một dòng hỏi (Đồng ý / Tắt) phía trên bảng, trả lời xong thì mất."""
        C = theme.C
        bar = self.table.bar
        # đường dẫn thư mục: ở đầu trang Cài đặt (người dùng 12/11); nút Mở thư mục ở hàng nút dưới bảng
        self.table.dir_caption.pack_forget()
        self.table.dir_label.pack_forget()
        self.disk_text = ""
        self.disk_msg = tk.Label(bar, text="", bg=C["bg"], fg=C["lose"], font=theme.F(10, "bold"), anchor="e")
        self.disk_tip = theme.Tip(self.disk_msg, lambda: self.disk_text)
        # dòng hỏi trước lần dọn đầu (chỉ hiện khi đang chờ trả lời)
        ask = tk.Frame(tab, bg=C["panel"], highlightthickness=1, highlightbackground=C["gold"])
        self.clean_btns = ask
        ttk.Button(ask, text="Tắt tự dọn", command=self._clean_decline).pack(side="right", padx=(6, 10), pady=6)
        ttk.Button(ask, text="Đồng ý dọn", style="Accent.TButton", command=self._clean_agree).pack(side="right", pady=6)
        self.clean_ask = tk.Label(ask, text="", bg=C["panel"], fg=C["gold_hi"], font=theme.F(10), anchor="w",
                                  justify="left", wraplength=600)
        self.clean_ask.pack(side="left", fill="x", expand=True, padx=(12, 8))
        ask.bind("<Configure>", lambda e: self.clean_ask.configure(wraplength=max(260, e.width - 300)))

    def _pin_selected(self):
        on = self.table.toggle_pin_selected()
        if on is not None:
            self._clean_check()

    def _clean_toggled(self):
        """Bật / tắt tự dọn (ô ở trang Trận đã ghi hoặc Cài đặt): lưu ngay."""
        self.cfg.auto_clean = bool(self.var_clean.get())
        if self.cfg.auto_clean:
            self.cfg.clean_agreed = False             # bật lại: lần dọn đầu vẫn hỏi trước
        self._save_cfg()
        self._append("tự dọn trận cũ: " + ("BẬT" if self.cfg.auto_clean else "TẮT (trận được giữ mãi)"))
        self._clean_check()

    def _clean_agree(self):
        self.cfg.clean_agreed = True
        self._save_cfg()
        self._clean_check()

    def _clean_decline(self):
        self.var_clean.set(False)
        self._clean_toggled()

    def _clean_timer(self):
        self._clean_check()
        self.root.after(self.CLEAN_EVERY_MS, self._clean_timer)

    def _clean_check(self):
        """Quét thư mục trận ở luồng nền; dọn nếu bật + đã đồng ý + không đang ghi trận (kết quả về qua self.q)."""
        if self._clean_busy:
            return
        from . import retention
        cfg = self.cfg
        raw = cfg.raw_dir()
        limit = int(cfg.clean_limit_gb * retention.GB)
        days = int(cfg.clean_days)
        do = cfg.auto_clean and cfg.clean_agreed and self._mode_now() != "rec"
        self._clean_busy = True

        def work():
            res = None
            try:
                if do:
                    res = retention.run(raw, limit, days, busy=self._is_recording_path, log=self.q.put)
                st = retention.status(raw, limit, days, busy=self._is_recording_path)
            except Exception as e:  # noqa: BLE001
                st = {"error": str(e)}
            self.q.put(("__clean__", st, res))
        threading.Thread(target=work, daemon=True, name="auto-clean").start()

    def _clean_result(self, st, res):
        import time

        from . import retention
        self._clean_busy = False
        self._clean_st = st
        if res and (res["deleted"] or res["web"]):
            self.table.reload()
        cfg = self.cfg
        C = theme.C
        if "error" in st:
            self.clean_text = f"Không đọc được thư mục trận: {st['error']}"
            return
        used = f"Hiện có {st['count']} trận, {retention.fmt_size(st['bytes'])}"
        if st.get("keep"):
            used += f" ({st['keep']} trận ghim ★)"
        lim, days = retention.fmt_size(int(cfg.clean_limit_gb * retention.GB)), cfg.clean_days
        pending = cfg.auto_clean and not cfg.clean_agreed and st["plan"]
        if res and res["deleted"]:
            self._clean_last = (f"Lần dọn gần nhất ({time.strftime('%H:%M %d/%m')}): {len(res['deleted'])} trận "
                                f"({retention.fmt_size(res['freed'])}).")
        if not cfg.auto_clean:
            text = f"Tự dọn trận cũ đang TẮT: trận được giữ mãi.\n{used}."
        else:
            text = (f"Tự dọn trận cũ đang BẬT: khi tổng trận vượt {lim}, trận cũ hơn {days} ngày được chuyển vào Thùng "
                    f"rác (khôi phục được), cũ nhất trước. Trận ghim ★ không bao giờ bị dọn.\n{used}.")
            if pending:
                text += "\nĐang chờ bạn đồng ý lần dọn đầu."
        if getattr(self, "_clean_last", ""):
            text += "\n" + self._clean_last
        self.clean_text = text + "\nĐổi ngưỡng / số ngày trong Cài đặt."
        if pending:
            self.clean_ask.configure(
                text=f"Tổng trận đã vượt {lim}: chuyển {len(st['plan'])} trận cũ hơn {days} ngày "
                     f"({retention.fmt_size(st['plan_bytes'])}) vào Thùng rác? Khôi phục được; trận ghim ★ được giữ.")
            if not self.clean_btns.winfo_manager():
                self.clean_btns.pack(side="top", fill="x", pady=(0, 10), before=self.table)
        else:
            self.clean_btns.pack_forget()
        self.var_clean_usage.set(f"{used}; trận cũ nhất: "
                                 f"{time.strftime('%d/%m/%Y', time.localtime(st['oldest'])) if st['oldest'] else '—'}.")
        # ổ đĩa sắp đầy
        free = st.get("free")
        low = free is not None and free < retention.LOW_DISK_BYTES
        if low:
            drive = os.path.splitdrive(os.path.abspath(cfg.raw_dir()))[0] or cfg.raw_dir()
            msg = (f"⚠ Ổ {drive} sắp đầy: chỉ còn {retention.fmt_size(free)} trống. Trận mới có thể không ghi được — "
                   f"hãy xoá bớt trận / giảm ngưỡng tự dọn trong Cài đặt, hoặc đổi thư mục lưu sang ổ khác.")
            self.disk_text = msg
            self.disk_msg.configure(text=f"⚠ Ổ {drive} sắp đầy")
            if not self.disk_msg.winfo_manager():
                self.disk_msg.pack(side="left", padx=(0, 10),         # xếp đầu: hàng hẹp thì ô khác nhường chỗ
                                   before=self.table.bar.pack_slaves()[0])
            if not self._low_disk:
                self._append("cảnh báo: " + msg)
        else:
            self.disk_msg.pack_forget()
        self._low_disk = low

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
        if self._being_recorded(p):
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
                    elif kind == "__hack__":           # tiến trình ghi phát hiện hack (mapcap/hackcheck)
                        self._on_hack(item[1])
                    elif kind == "__tray__":           # từ luồng khay / bản mở sau (instance.signal_show)
                        self._tray_action(item[1])
                    elif kind == "__clean__":          # tình trạng tự dọn (luồng nền)
                        self._clean_result(item[1], item[2])
                    elif kind == "__done__":
                        self._append("=== bộ ghi đã dừng")
                        self.state_text = "đã dừng"
                        self.engine = None
                        self._stopping = False
                        self._refresh_status()
                        self.table.reload()
                        self._engine_done()
                elif item == "__reload_table__":
                    self.table.reload()
                else:
                    self._append(item)
                    if "đã chốt dữ liệu thô" in item or "ghi dữ liệu thô" in item:
                        self.table.reload()            # trận mới bắt đầu / vừa chốt: cập nhật bảng
                    if "lỗi dựng" in item:            # xuất video thất bại: báo rõ, không để người dùng chờ
                        self.state_text = "xuất video LỖI"
                        self._refresh_status()
                        self._show_window()
                        messagebox.showerror(APP_TITLE, item)
        except queue.Empty:
            pass
        self.root.after(200, self._poll)

    # chế độ hiển thị: rec = đang ghi trận | armed = bộ ghi bật, chờ game/trận | stopping = đang dừng | off = không ghi
    MODE_LOOK = {
        "rec": ("ĐANG GHI TRẬN", "red_hi"),
        "armed": ("ĐANG GHI", "gold"),
        "stopping": ("ĐANG DỪNG…", "muted"),
        "off": ("KHÔNG GHI", "dim"),
    }
    WAIT_TEXT = {"chờ game": "Sẽ tự ghi khi vào trận", "trong game, chờ trận": "Đã thấy game — vào trận là tự ghi"}
    IDLE_SHORT = "Ngoài trận không làm gì, nhẹ như Vietkey"
    IDLE_LONG = "Ngoài trận không làm gì nên không tốn tài nguyên, không nặng máy, chỉ nhẹ như Vietkey."

    def _mode_now(self):
        if self.engine is None:
            return "off"
        if self._stopping:
            return "stopping"
        if getattr(self.engine, "state", "") == "đang ghi" or (self.state_text or "").strip() == "đang ghi":
            return "rec"
        return "armed"

    def _refresh_status(self):
        """Trạng thái ghi ở 4 chỗ cùng lúc: dải màu trên cùng, nhãn lớn + nút trên đầu trang, thẻ thanh bên, tiêu đề
        cửa sổ. Dòng nhỏ ở thanh bên = tiến độ từng lượt xuất video / nén đang chạy."""
        import time
        C = theme.C
        mode = self._mode_now()
        self._recording = mode == "rec"
        if self._was_rec and mode != "rec":
            self.root.after(30000, self._clean_check)
        self._was_rec = mode == "rec"
        st = (self.state_text or "").strip()
        title, color = self.MODE_LOOK[mode][:2]
        if mode == "rec":
            if self._rec_since is None:
                self._rec_since = time.monotonic()
            s = int(time.monotonic() - self._rec_since)
            sub = f"Đã ghi {s // 3600:d}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"Đã ghi {s // 60:02d}:{s % 60:02d}"
        else:
            self._rec_since = None
            off = ("Bản này đã ngừng hỗ trợ: bấm Cập nhật để ghi tiếp"
                   if getattr(getattr(self, "updater", None), "block_win", None) is not None else "Đang bật bộ ghi…")
            sub = {"armed": self.WAIT_TEXT.get(st, "Sẽ tự ghi khi vào trận"), "stopping": "Đang chốt dữ liệu trận…",
                   "off": off}[mode]
        side_sub = sub
        if mode == "armed":                          # bộ ghi bật, ngoài trận: chỉ dò game 2 giây một lần
            side_sub = f"{sub}. {self.IDLE_LONG}"
            sub = f"{sub}\n{self.IDLE_SHORT}"
        if mode != self._mode:                       # đổi màu cả khối chỉ khi đổi chế độ
            self._mode = mode
            chip_bg = {"rec": C["red_lo"], "armed": C["panel"], "stopping": C["panel"], "off": C["panel"]}[mode]
            edge = {"rec": C["red_hi"], "armed": C["gold"], "stopping": C["line"], "off": C["line"]}[mode]
            for w in self._chip_parts:
                w.configure(bg=chip_bg)
            self.chip.configure(highlightbackground=edge, highlightcolor=edge)
            self.chip_title.configure(fg="#ffffff" if mode == "rec" else (C["gold_hi"] if mode == "armed" else C["muted"]))
            self.chip_sub.configure(fg="#f0c8cc" if mode == "rec" else C["muted"])
            self.strip.configure(bg={"rec": C["red_hi"], "armed": C["gold"], "stopping": C["line"], "off": C["line"]}[mode])
            self.root.title(("● ĐANG GHI — " if mode == "rec" else "") + self._base_title)
        self.chip_title.configure(text=title)
        self.chip_sub.configure(text=sub)
        dot = C[color] if mode != "rec" or not self._pulse else "#ffffff"
        self.chip_dot.itemconfigure(self.chip_dot_id, fill=dot)
        # thẻ trạng thái ở thanh bên: cùng chế độ
        side = {"rec": "Đang ghi trận", "armed": "Đang ghi", "stopping": "Đang dừng…", "off": "Không ghi"}[mode]
        if st == "xuất video LỖI":
            side = "Xuất video LỖI"
        self.lbl_state.configure(text=side, fg="#ffffff" if mode in ("rec", "armed") else C["muted"])
        self.dot.itemconfigure(self.dot_id, fill=dot)
        extra = [f"{k}: {v}" for k, v in self.renders.items()]
        self.lbl_status.configure(text="\n".join(extra) if extra else side_sub)
        if self.tray is not None:
            self.tray.update(f"AoE-MapCap — {side}\n{sub}", {"rec": "rec", "armed": "armed"}.get(mode))
        if self._apply_pending and mode == "armed":
            self.root.after(0, self._apply_settings_when_idle)      # hết trận: áp dụng cài đặt đã lưu

    def _tick(self):
        """Nhịp 0,5 s: chấm đỏ nhấp nháy + đồng hồ khi đang ghi trận."""
        if self._mode_now() == "rec":
            self._pulse = not self._pulse
            self._refresh_status()
        elif self._pulse:
            self._pulse = False
            self._refresh_status()
        self.root.after(500, self._tick)

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

    # ---- khay hệ thống: bấm X là chạy ngầm ------------------------------------------------
    def _start_tray(self):
        try:
            from .tray import Tray
            t = Tray(app_icon_path(), lambda act: self.q.put(("__tray__", act)), "AoE-MapCap")
            self.tray = t if t.start() else None
        except Exception as e:  # noqa: BLE001  - không có khay thì bấm X là thoát như cũ
            self.tray = None
            self.q.put(f"khay hệ thống: không dùng được ({e})")

    def _stop_tray(self):
        if self.tray is not None:
            self.tray.stop()

    def _tray_action(self, act):
        if act == "open":
            self._show_window()
        elif act == "phone":
            self._phone_toggle()
            if self._phone_running():                  # bật từ khay: mở trang có mã QR
                self.show_page("phone")
                self._show_window()
        elif act == "quit":
            self._quit()

    def _show_window(self):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)       # đưa lên trên cửa sổ khác rồi bỏ "luôn trên cùng"
            self.root.after(300, lambda: self.root.attributes("-topmost", False))
            self.root.focus_force()
        except tk.TclError:
            pass

    def _hidden(self):
        try:
            return self.root.state() == "withdrawn"
        except tk.TclError:
            return False

    def _restart_args(self):
        """Tham số cho bản mới sau tự cập nhật: chờ bản này thoát hẳn; đang ghi thì ghi tiếp; đang ẩn thì vẫn ẩn."""
        return (["--autostart"] if self._restart_recording else []) + ["--wait-instance"] + \
            (["--tray"] if self._hidden() and self.tray is not None else [])

    def _on_close(self):
        """Nút X: có khay thì ẩn cửa sổ (vẫn ghi trận), thoát hẳn bằng menu khay -> Thoát."""
        if self.tray is not None and self.tray.ok and self.var_tray.get():
            self.root.withdraw()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.balloon("AoE-MapCap vẫn chạy ngầm",
                                  "Vẫn tự ghi trận. Bấm biểu tượng ở đây để mở lại, bấm phải -> Thoát để tắt hẳn.")
            return
        self._quit()

    def _quit(self):
        from .offline import active_renders
        running = self.engine is not None and self.thread is not None and self.thread.is_alive()
        recording = running and getattr(self.engine, "state", "") == "đang ghi"
        rendering = active_renders() > 0
        if recording:                       # v34: thoát giữa trận = dừng ghi giữa trận -> không cho
            self._show_window()
            messagebox.showinfo(APP_TITLE, "Đang ghi trận: AoE-MapCap chỉ thoát được khi trận kết thúc.\n\n"
                                "App luôn ghi trọn trận để không ai dừng ghi giữa chừng rồi mở replay xem bản đồ / nhà "
                                "đối thủ khi ván còn đang đánh.")
            return
        if rendering:
            msg = "Đang xuất video. Thoát bây giờ sẽ mất video đang xuất (xuất lại được từ trận đã ghi). Thoát?"
        else:
            msg = None
        if msg:
            self._show_window()
        if msg and not messagebox.askyesno(APP_TITLE, msg):
            return
        self._quitting = True
        if rendering:
            from .offline import abort_all
            abort_all()                     # tắt tiến trình đoạn, xoá thư mục tạm aoerender_*
        if running:
            self.stop_event.set()
            self.thread.join(timeout=30 if recording else 5)
        if self._phone_running():
            self.phone.stop()
        self.root.destroy()


def main():
    from . import instance
    inst = instance.Instance.acquire(wait_s=60 if "--wait-instance" in sys.argv else 0)
    if inst is None:                          # đã có AoE-MapCap đang chạy (có thể đang ẩn ở khay): hiện nó lên
        shown = instance.signal_show()
        _close_splash()
        if not shown:
            r = tk.Tk()
            r.withdraw()
            messagebox.showinfo(APP_TITLE, "AoE-MapCap đang chạy (biểu tượng ở khay hệ thống, góc phải thanh tác vụ).")
            r.destroy()
        return
    tray_start = "--tray" in sys.argv         # khởi động cùng Windows / tự cập nhật lúc đang ẩn ở khay
    if tray_start:
        _close_splash()                       # chạy ngầm: không màn hình chờ
    root = tk.Tk()
    if tray_start:
        root.withdraw()                       # ẩn ngay từ đầu: không nháy cửa sổ lúc dựng giao diện (người dùng 09/11)
    try:
        root.tk.call("tk", "scaling", 1.25)
    except Exception:  # noqa: BLE001
        pass
    app = App(root)
    inst.watch(lambda: app.q.put(("__tray__", "open")))
    if tray_start and app.tray is None:
        root.deiconify()                      # không có khay hệ thống: phải hiện cửa sổ, không thì app vô hình
    schedule_autostart(app, sys.argv)
    root.update_idletasks()
    _close_splash()                           # cửa sổ chính đã dựng xong: tắt màn hình chờ của exe
    try:
        root.mainloop()
    finally:
        app._stop_tray()
        inst.release()


def _close_splash():
    try:
        import pyi_splash
        pyi_splash.close()
    except Exception:  # noqa: BLE001  - chạy từ mã nguồn: không có màn hình chờ
        pass


def schedule_autostart(app, argv, delay_ms=800):
    """Mở app là bật bộ ghi (v34: luôn ghi khi app đang mở, không còn tuỳ chọn tắt). argv giữ cho tương thích
    (--autostart của tác vụ đăng nhập / bản cũ khởi động lại sau cập nhật)."""
    app.root.after(delay_ms, app._auto_start)
    return True


if __name__ == "__main__":
    main()
