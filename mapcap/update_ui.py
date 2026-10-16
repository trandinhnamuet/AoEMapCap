"""Giao diện tự cập nhật (tkinter), dùng chung cho AoE-MapCap và AoE-Replay.

- Có bản mới: thanh báo phía trên cửa sổ "Có bản mới vN" + Có gì mới / Cập nhật / Để sau.
- Bản đang dùng thấp hơn min_version: cửa sổ chặn "Bản này đã ngừng hỗ trợ" chỉ có Cập nhật ngay / Thoát.
- Đang bận (đang ghi trận, đang xuất video): không tải, không khởi động lại; chờ xong việc rồi mới chạy.
- Không có mạng: không hiện gì, dùng bình thường.
"""
import os
import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from . import updater


class UpdateController:
    def __init__(self, root, bar_parent, role, app_title, log=None, is_busy=None, before_restart=None,
                 restart_args=None, bar_before=None, on_block=None):
        """bar_parent: khung chứa thanh báo (pack ở trên, trước bar_before nếu có).
        is_busy() -> chuỗi lý do đang bận hoặc "" ; before_restart() -> False để huỷ khởi động lại;
        restart_args() -> tham số cho exe mới."""
        self.root = root
        self.role = role
        self.title = app_title
        self.log = log or (lambda m: None)
        self.is_busy = is_busy or (lambda: "")
        self.before_restart = before_restart or (lambda: True)
        self.restart_args = restart_args or (lambda: [])
        self.on_block = on_block or (lambda: None)    # gọi khi hiện cửa sổ "bản này đã ngừng hỗ trợ"
        self.q = queue.Queue()
        self.info = None
        self.dismissed = None            # phiên bản người dùng bấm "Để sau"
        self.pending = False             # đã bấm Cập nhật nhưng đang bận: chờ
        self.working = False
        self.cancel_flag = False
        self.block_win = None
        from . import theme
        self.dark = theme.APPLIED                       # giao diện tối kiểu XArena (AoE-MapCap)
        self.bar = ttk.Frame(bar_parent, style="Notice.TFrame" if self.dark else "TFrame",
                             padding=(14, 8) if self.dark else 0)
        self._bar_before = bar_before
        if self.dark:
            self.lbl = ttk.Label(self.bar, text="", style="Notice.TLabel")
        else:
            self.lbl = ttk.Label(self.bar, text="", foreground="#0b5394")
        self.lbl.pack(side="left", padx=(4, 10))
        self.pb = ttk.Progressbar(self.bar, length=220, mode="determinate", maximum=1000)
        self.btn_later = ttk.Button(self.bar, text="Để sau", command=self._later)
        self.btn_update = ttk.Button(self.bar, text="Cập nhật", command=self.begin_update,
                                     style="Accent.TButton" if self.dark else "TButton")
        self.btn_notes = ttk.Button(self.bar, text="Có gì mới", command=self.show_notes)
        self.btn_cancel = ttk.Button(self.bar, text="Huỷ", command=self._cancel)
        for b in (self.btn_later, self.btn_update, self.btn_notes):
            b.pack(side="right", padx=3)

    # ---- kiểm tra ----------------------------------------------------------------------
    def start(self, delay_ms=2500):
        try:
            n = updater.cleanup_old()
            if n:
                self.log(f"đã xoá {n} file exe cũ của lần cập nhật trước")
        except Exception:  # noqa: BLE001
            pass
        self.root.after(delay_ms, self._check_async)
        self.root.after(300, self._poll)
        self.root.after(20000, updater.cleanup_old)    # vừa cập nhật: exe cũ có thể chưa thoát hẳn lúc mở bản mới

    def _check_async(self):
        def job():
            self.q.put(("checked", updater.check(log=self.log)))
        threading.Thread(target=job, name="update-check", daemon=True).start()
        self.root.after(int(updater.CHECK_EVERY * 1000), self._check_async)

    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "checked":
                    self._on_checked(item[1])
                elif kind == "progress":
                    self._show_progress(*item[1:])
                elif kind == "downloaded":
                    self._on_downloaded(item[1])
                elif kind == "failed":
                    self._on_failed(item[1])
        except queue.Empty:
            pass
        if self.pending and not self.working and not self.is_busy():
            self.pending = False
            self.log("hết bận: bắt đầu cập nhật")
            self._download()
        if self.info is not None and self.info.state == "required" and self.block_win is None and not self.is_busy():
            self._show_block()
        self.root.after(1000 if self.pending else 300, self._poll)

    def _on_checked(self, info):
        if info is None:
            return
        self.info = info
        self.log(f"phiên bản đang dùng v{info.current}, mới nhất v{info.latest}"
                 + (f", tối thiểu v{info.min_version}" if info.state == "required" else ""))
        if info.state == "available" and self.dismissed != info.latest and not self.working:
            self._show_bar(f"Có bản mới v{info.latest} (đang dùng v{info.current}).")
        if info.state != "current" and updater.env_override("AOEMAPCAP_UPDATE_AUTO") == "1":
            self.begin_update()                    # chỉ dùng khi kiểm thử exe: tự bấm Cập nhật
        # "required": _poll hiện cửa sổ chặn khi không bận

    # ---- thanh báo -------------------------------------------------------------------
    def _show_bar(self, text):
        self.lbl.configure(text=text)
        if not self.bar.winfo_ismapped():
            kw = {"before": self._bar_before} if self._bar_before is not None else {}
            self.bar.pack(fill="x", padx=24 if self.dark else 12, pady=(12, 0) if self.dark else (0, 4), **kw)

    def _later(self):
        if self.info is not None:
            self.dismissed = self.info.latest
        self.pending = False
        self.bar.pack_forget()

    def show_notes(self, parent=None):
        if self.info is None:
            return
        top = tk.Toplevel(parent or self.root)
        top.title(f"Có gì mới — v{self.info.latest}")
        top.geometry("640x420")
        from . import theme
        if self.dark:
            theme.dark_window(top)
        txt = tk.Text(top, wrap="word", font=theme.F(10) if self.dark else ("Segoe UI", 10), padx=12, pady=10,
                      **(theme.text_widget_colors() if self.dark else {}))
        sb = ttk.Scrollbar(top, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        bot = ttk.Frame(top)
        bot.pack(side="bottom", fill="x", padx=8, pady=8)
        sb.pack(side="right", fill="y")
        txt.pack(fill="both", expand=True)
        txt.insert("end", self.info.notes_since())
        txt.configure(state="disabled")
        ttk.Button(bot, text="Đóng", command=top.destroy).pack(side="right")
        ttk.Button(bot, text="Mở trang phát hành", command=lambda: webbrowser.open(self.info.page)).pack(side="right", padx=6)

    # ---- cập nhật ----------------------------------------------------------------------
    def begin_update(self):
        if self.info is None or self.working:
            return
        if not updater.is_frozen():
            messagebox.showinfo(self.title, "Đang chạy từ mã nguồn: hãy cập nhật mã (git pull) hoặc tải bản mới.\n"
                                + self.info.page)
            return
        busy = self.is_busy()
        if busy:
            self.pending = True
            self._show_bar(f"{busy}: sẽ tự cập nhật lên v{self.info.latest} ngay khi xong.")
            self.log(f"chờ cập nhật: {busy}")
            return
        self._download()

    def _download(self):
        self.working = True
        self.cancel_flag = False
        self._set_working_ui(True)
        info = self.info

        def job():
            try:
                pairs = updater.download_all(
                    info, self.role,
                    progress=lambda done, total, name: self.q.put(("progress", done, total, name)),
                    cancel=lambda: self.cancel_flag)
                self.q.put(("downloaded", pairs))
            except Exception as e:  # noqa: BLE001
                self.q.put(("failed", e))
        threading.Thread(target=job, name="update-download", daemon=True).start()
        self.log(f"đang tải v{info.latest}...")

    def _set_working_ui(self, on):
        if on:
            self._show_bar(f"Đang tải v{self.info.latest}...")
            for b in (self.btn_later, self.btn_update, self.btn_notes):
                b.pack_forget()
            self.btn_cancel.pack(side="right", padx=3)
            self.pb.pack(side="right", padx=6)
            self.pb["value"] = 0
        else:
            self.pb.pack_forget()
            self.btn_cancel.pack_forget()
            for b in (self.btn_later, self.btn_update, self.btn_notes):
                b.pack(side="right", padx=3)
        if self.block_win is not None:
            self.block_win.set_working(on)

    def _show_progress(self, done, total, name):
        frac = done / max(total, 1)
        text = f"Đang tải v{self.info.latest}: {done / 1e6:.0f} / {total / 1e6:.0f} MB ({name})"
        self.lbl.configure(text=text)
        self.pb["value"] = int(frac * 1000)
        if self.block_win is not None:
            self.block_win.set_progress(frac, text)

    def _cancel(self):
        self.cancel_flag = True

    def _on_failed(self, e):
        self.working = False
        self._set_working_ui(False)
        if str(e) == "đã huỷ":
            self._show_bar(f"Đã huỷ tải. Có bản mới v{self.info.latest}.")
            return
        self.log(f"cập nhật lỗi: {e}")
        self._show_bar(f"Cập nhật lỗi. Có bản mới v{self.info.latest}.")
        messagebox.showerror(self.title, f"Không cập nhật được:\n{e}\n\nCó thể tải tay tại:\n{self.info.page}",
                             parent=self.block_win.top if self.block_win is not None else self.root)

    def _on_downloaded(self, pairs):
        busy = self.is_busy()
        if busy:                                   # vừa có trận mới trong lúc tải: chờ xong rồi mới thay + khởi động lại
            self.lbl.configure(text=f"Đã tải xong v{self.info.latest}. {busy}: sẽ khởi động lại khi xong.")
            self.root.after(2000, lambda: self._on_downloaded(pairs))
            return
        if not self.before_restart():
            self.working = False
            self._set_working_ui(False)
            return
        try:
            updater.install(pairs)
        except Exception as e:  # noqa: BLE001
            self._on_failed(updater.UpdateError(f"không thay được file exe: {e}"))
            return
        self.log(f"đã cập nhật lên v{self.info.latest}: khởi động lại")
        try:
            updater.restart(self.restart_args())
        except Exception as e:  # noqa: BLE001
            messagebox.showinfo(self.title, f"Đã cập nhật lên v{self.info.latest}. Hãy mở lại ứng dụng.\n({e})")
        self.root.after(200, self.root.destroy)

    # ---- bắt buộc cập nhật -----------------------------------------------------------
    def _show_block(self):
        self.bar.pack_forget()
        self.block_win = BlockDialog(self)
        try:
            self.on_block()
        except Exception:  # noqa: BLE001
            pass


class BlockDialog:
    """Bản đang dùng đã ngừng hỗ trợ: chỉ còn Cập nhật ngay / Thoát (đóng cửa sổ = thoát)."""

    def __init__(self, ctl):
        self.ctl = ctl
        info = ctl.info
        top = self.top = tk.Toplevel(ctl.root)
        top.title(f"{ctl.title} — cần cập nhật")
        top.geometry("620x420")
        top.transient(ctl.root)
        top.protocol("WM_DELETE_WINDOW", self._quit)
        from . import theme
        if ctl.dark:
            theme.dark_window(top)
        ttk.Label(top, text=f"Bản v{info.current} đã ngừng hỗ trợ. Hãy cập nhật lên v{info.latest} để tiếp tục dùng.",
                  font=theme.F(12, "bold") if ctl.dark else ("Segoe UI", 11, "bold"), wraplength=580).pack(
            fill="x", padx=12, pady=(12, 6))
        txt = tk.Text(top, wrap="word", font=theme.F(10) if ctl.dark else ("Segoe UI", 10), height=12, padx=10, pady=8,
                      **(theme.text_widget_colors() if ctl.dark else {}))
        txt.insert("end", info.notes_since())
        txt.configure(state="disabled")
        txt.pack(fill="both", expand=True, padx=12)
        self.lbl = ttk.Label(top, text="")
        self.lbl.pack(fill="x", padx=12, pady=(6, 0))
        self.pb = ttk.Progressbar(top, mode="determinate", maximum=1000)
        bot = ttk.Frame(top)
        bot.pack(side="bottom", fill="x", padx=12, pady=10)
        self.btn_quit = ttk.Button(bot, text="Thoát", command=self._quit)
        self.btn_quit.pack(side="right")
        self.btn_go = ttk.Button(bot, text="Cập nhật ngay", command=ctl.begin_update,
                                 style="Accent.TButton" if ctl.dark else "TButton")
        self.btn_go.pack(side="right", padx=6)
        self.btn_cancel = ttk.Button(bot, text="Huỷ tải", command=ctl._cancel)
        ttk.Button(bot, text="Mở trang phát hành", command=lambda: webbrowser.open(info.page)).pack(side="left")
        try:
            top.grab_set()                          # chặn cửa sổ chính
        except tk.TclError:
            pass
        top.lift()
        top.focus_force()

    def set_working(self, on):
        if on:
            self.btn_go.configure(state="disabled")
            self.btn_cancel.pack(side="right", padx=6)
            self.pb.pack(fill="x", padx=12, pady=(4, 0), before=self.lbl)
        else:
            self.btn_go.configure(state="normal")
            self.btn_cancel.pack_forget()
            self.pb.pack_forget()
            self.lbl.configure(text="")

    def set_progress(self, frac, text):
        self.pb["value"] = int(frac * 1000)
        self.lbl.configure(text=text)

    def _quit(self):
        self.ctl.cancel_flag = True
        if self.ctl.before_restart():
            self.ctl.root.after(100, self.ctl.root.destroy)
