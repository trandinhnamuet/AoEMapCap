"""Bảng các trận đã ghi (tkinter), thay cho hộp chọn file.

    MatchTable(parent, folder, on_open)    -> khung bảng (nhúng vào giao diện chính AoE-MapCap)
    PickerWindow(master, folder, on_open)  -> cửa sổ riêng chứa bảng + nút
    pick_match(folder) -> đường dẫn hoặc None  (AoE-Replay chạy riêng, tự tạo Tk)
"""
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk

from .library import Library, fmt_duration

COLUMNS = (
    ("date", "Ngày đánh", 120, "w"),
    ("name", "Người chơi", 150, "w"),
    ("civ", "Quân", 100, "w"),
    ("result", "Kết quả", 160, "w"),
    ("mode", "Thể thức", 110, "w"),          # "2v1 Random", "4v4 Shang"
    ("kind", "Map", 170, "w"),               # "Hill Country - Large"
    ("dur", "Thời lượng", 80, "e"),
)
RESULT_TAG = {"Thắng": "win", "Thua": "lose", "Đầu hàng": "lose", "Cần bản mới": "muted"}
SPACER = "::sp"                  # iid dòng trống giữ chỗ cho khung mở rộng: "<đường dẫn>::sp<k>"


def fmt_clock(ms):
    if ms is None:
        return "—"
    s = max(0, int(ms) // 1000)
    return f"{s // 60}:{s % 60:02d}"


class MatchTable(ttk.Frame):
    """Bảng trận: đọc thông tin ở luồng nền, sắp theo cột, lọc theo tên, dòng chi tiết đội hình."""

    def __init__(self, parent, folder, on_open=None, show_dir_button=True):
        super().__init__(parent)
        self.on_open = on_open
        self.is_busy = None          # hàm(path) -> True nếu trận đang được ghi (không cho xoá)
        self.q = queue.Queue()
        self.infos = {}
        self.sort_key = ("date", True)
        self._gen = 0
        self.expanded = {}           # đường dẫn trận đang mở rộng (chuột phải) -> {spacers, box, inner, rowh}
        self._head_h = None
        self._ages = {}              # đường dẫn -> kích / lên đời (đọc ở luồng nền, đệm trong _matches.json)
        self._ages_busy = set()
        self.folder = folder
        self._build(show_dir_button)
        self.set_folder(folder)
        self.after(100, self._poll)

    def _build(self, show_dir_button):
        from mapcap import theme
        dark = theme.APPLIED                                  # giao diện tối kiểu XArena (AoE-MapCap)
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text="Thư mục:", style="Muted.TLabel" if dark else "TLabel").pack(side="left")
        self.var_dir = tk.StringVar()
        ttk.Label(bar, textvariable=self.var_dir, style="Muted.TLabel" if dark else "TLabel").pack(side="left", padx=6)
        if show_dir_button:
            ttk.Button(bar, text="Đổi thư mục...", command=self._choose_dir).pack(side="right")
        ttk.Button(bar, text="Làm mới", command=self.reload).pack(side="right", padx=(4, 0))
        self.var_find = tk.StringVar()
        ttk.Entry(bar, textvariable=self.var_find, width=22).pack(side="right", padx=(4, 12))
        ttk.Label(bar, text="Tìm tên người chơi:", style="Muted.TLabel" if dark else "TLabel").pack(side="right")
        self.var_find.trace_add("write", lambda *_: self._refill())

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(mid, columns=[c[0] for c in COLUMNS], show="headings", selectmode="browse")
        for key, label, w, anchor in COLUMNS:
            self.tree.heading(key, text=label, command=lambda k=key: self._sort(k))
            self.tree.column(key, width=w, anchor=anchor, stretch=key in ("name", "kind"))
        self.tree.tag_configure("win", foreground=theme.C["green"] if dark else "#1b7a1b")
        self.tree.tag_configure("lose", foreground=theme.C["lose"] if dark else "#b02020")
        self.tree.tag_configure("muted", foreground=theme.C["dim"] if dark else "#888888")
        if dark:
            self.tree.tag_configure("odd", background=theme.C["bg2"])    # dòng xen kẽ
        sb = ttk.Scrollbar(mid, command=self.tree.yview)
        self.tree.configure(yscrollcommand=lambda a, b: (sb.set(a, b), self._place_expand()))
        self.tree.tag_configure("spacer", background=theme.C["panel"] if dark else "#f4f4f4")
        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<Configure>", lambda e: self.after_idle(self._place_expand), add="+")
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.open_selected())
        self.tree.bind("<Return>", lambda e: self.open_selected())
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._show_detail())
        self.tree.bind("<Delete>", lambda e: self.delete_selected())
        self.var_detail = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.var_detail, style="Detail.TLabel" if dark else "TLabel", justify="left",
                  wraplength=900).pack(fill="x", pady=(8, 0))
        self.var_status = tk.StringVar(value="")
        self.bind("<Configure>", lambda e: self._wrap(e.width))

    def _wrap(self, width):
        for w in self.winfo_children():
            if isinstance(w, ttk.Label) and str(w.cget("textvariable")) == str(self.var_detail):
                w.configure(wraplength=max(300, width - 20))

    # ---- dữ liệu ---------------------------------------------------------------------------
    def set_folder(self, folder):
        self.folder = folder
        self.var_dir.set(folder)
        self.infos = {}
        self.tree.delete(*self.tree.get_children())
        self.reload()

    def reload(self):
        self._gen += 1
        gen = self._gen
        threading.Thread(target=self._load, args=(self.folder, gen), daemon=True).start()

    def _load(self, folder, gen):
        lib = Library(folder)
        files = lib.files()
        self.q.put(("count", gen, len(files), [os.path.normpath(p) for p in files]))
        for i, p in enumerate(files):
            if gen != self._gen:
                return
            self.q.put(("info", gen, os.path.normpath(p), lib.info(p), i + 1, len(files)))
        lib.save()
        self.q.put(("done", gen, len(files)))

    def _poll(self):
        changed = False
        while True:
            try:
                msg = self.q.get_nowait()
            except queue.Empty:
                break
            if msg[1] != self._gen:
                continue
            if msg[0] == "count":
                live = set(msg[3])
                for p in list(self.infos):
                    if p not in live:
                        del self.infos[p]
                        changed = True
                self.var_status.set("Chưa có trận nào được ghi." if msg[2] == 0 else f"Đang đọc {msg[2]} trận…")
            elif msg[0] == "info":
                _, _, p, info, k, n = msg
                self.infos[p] = info
                changed = True
                self.var_status.set(f"Đang đọc {k}/{n} trận…")
            elif msg[0] == "ages":
                _, _, p, ages = msg
                self._ages[p] = ages
                self._ages_busy.discard(p)
                if p in self.expanded:
                    self._expand(p)
            elif msg[0] == "done":
                self.var_status.set(f"{msg[2]} trận. Bấm đúp hoặc Enter để xem; chuột phải để xem 2 đội; "
                                    "bấm tiêu đề cột để sắp xếp."
                                    if msg[2] else "Chưa có trận nào được ghi.")
        if changed:
            self._refill()
        try:
            self.after(150, self._poll)
        except tk.TclError:
            pass

    @staticmethod
    def _row(info):
        if "error" in info:
            return (time.strftime("%d/%m/%Y %H:%M", time.localtime(info.get("created", 0))), info["file"], "",
                    "lỗi đọc file", "", info["error"][:40], ""), "muted"
        vals = (time.strftime("%d/%m/%Y %H:%M", time.localtime(info["created"])), info["recorder"],
                info["recorder_civ"], info["result"], f"{info['format']} {info['civ_mode']}", info["map"],
                fmt_duration(info["duration_ms"]))
        return vals, RESULT_TAG.get(info["result"], "")

    def _refill(self):
        sel_path = self.selected_path()
        keep = list(self.expanded)
        self._collapse()
        self.tree.delete(*self.tree.get_children())
        find = self.var_find.get().strip().lower()
        key, desc = self.sort_key
        idx = [c[0] for c in COLUMNS].index(key)

        def sort_val(item):
            _p, info = item
            if key == "date":
                return info.get("created", 0)
            if key == "dur":
                return info.get("duration_ms", 0)
            return str(self._row(info)[0][idx]).lower()
        row = 0
        for p, info in sorted(self.infos.items(), key=sort_val, reverse=desc):
            if find:
                hay = " ".join([info.get("file", "")] + [pl.get("name", "") for pl in info.get("players", [])] +
                               [str(v) for v in self._row(info)[0]]).lower()
                if find not in hay:
                    continue
            vals, tag = self._row(info)
            tags = ((tag,) if tag else ()) + (("odd",) if row % 2 else ())
            self.tree.insert("", "end", iid=p, values=vals, tags=tags)
            row += 1
        if sel_path and self.tree.exists(sel_path):
            self.tree.selection_set(sel_path)
        elif self.tree.get_children():
            first = self.tree.get_children()[0]
            self.tree.selection_set(first)
            self.tree.focus(first)
        for k in keep:
            if self.tree.exists(k):
                self._expand(k, scroll=False)
        self._show_detail()

    def _sort(self, key):
        k, desc = self.sort_key
        self.sort_key = (key, not desc if k == key else key in ("date", "dur"))
        self._refill()

    def _show_detail(self):
        info = self.infos.get(self.selected_path() or "")
        if not info or "error" in info:
            self.var_detail.set("")
            return
        by_team = {}
        for pl in info.get("players", []):
            st = {1: " (thắng)", 2: " (đầu hàng)" if pl.get("resigned") else " (thua)"}.get(pl.get("status"), "")
            by_team.setdefault(pl["team"], []).append(f"{pl['name']} – {pl['civ']}{st}")
        teams = "   |   ".join(f"Đội {t}: " + ", ".join(v) for t, v in sorted(by_team.items()))
        note = "" if info.get("new_format") else "   (file ghi trước 09/10/2026: chưa có kết quả và thiết lập ván)"
        self.var_detail.set(f"{info['file']}   ·   {teams}{note}")

    def selected_path(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return sel[0].split(SPACER)[0]

    # ---- mở rộng (chuột phải): 2 đội, quân, lúc kích đời; mở được nhiều trận cùng lúc ----------
    def _on_right_click(self, e):
        row = self.tree.identify_row(e.y)
        if not row:
            return
        path = row.split(SPACER)[0]
        self.tree.selection_set(path)
        self.tree.focus(path)
        self.toggle_expand(path)

    def toggle_expand(self, path=None):
        path = path or self.selected_path()
        if path:
            self._collapse(path) if path in self.expanded else self._expand(path)

    def _collapse(self, path=None):
        """Thu gọn một trận (path) hoặc tất cả (None)."""
        for p in ([path] if path else list(self.expanded)):
            st = self.expanded.pop(p, None)
            if st is None:
                continue
            for sp in st["spacers"]:
                if self.tree.exists(sp):
                    self.tree.delete(sp)
            st["box"].destroy()

    def _load_ages(self, path):
        if path in self._ages or path in self._ages_busy:
            return
        self._ages_busy.add(path)
        gen = self._gen

        def job():
            try:
                lib = Library(os.path.dirname(path))
                ages = lib.ages(path)
                lib.save()
            except Exception:  # noqa: BLE001  - file hỏng / đang ghi: chỉ không có giờ lên đời
                ages = {}
            self.q.put(("ages", gen, path, ages))
        threading.Thread(target=job, daemon=True).start()

    def _expand(self, path, scroll=True):
        """Mở rộng ngay dưới dòng: chèn dòng trống giữ chỗ rồi đặt khung nội dung đè lên đúng chỗ đó."""
        info = self.infos.get(path)
        if not info or "error" in info or not self.tree.exists(path):
            return
        self._collapse(path)
        ages = self._ages.get(path)
        if ages is None:
            self._load_ages(path)
        box = tk.Frame(self.tree, bg=self._C("line"), highlightthickness=0)
        inner = tk.Frame(box, bg=self._C("panel"))
        self._build_expand(inner, info, ages)
        inner.update_idletasks()
        bb = self.tree.bbox(path)
        rowh = bb[3] if bb else 30
        n = max(1, -(-(inner.winfo_reqheight() + 1) // rowh))
        spacers = []
        for k in range(n):
            iid = f"{path}{SPACER}{k}"
            self.tree.insert(path, "end", iid=iid, values=("",) * len(COLUMNS), tags=("spacer",))
            spacers.append(iid)
        self.tree.item(path, open=True)
        self.expanded[path] = {"spacers": spacers, "box": box, "inner": inner, "rowh": rowh}
        for w in [inner] + self._descendants(inner):
            w.bind("<Button-3>", lambda e, p=path: self.toggle_expand(p))
            w.bind("<Double-1>", lambda e, p=path: self.on_open and self.on_open(p))
        if scroll:
            self.tree.see(spacers[-1])
            self.tree.see(path)
        self.after_idle(self._place_expand)

    @staticmethod
    def _descendants(w):
        out = []
        for c in w.winfo_children():
            out.append(c)
            out.extend(MatchTable._descendants(c))
        return out

    @staticmethod
    def _C(key):
        from mapcap import theme
        return theme.C[key]

    def _heading_height(self):
        """Đáy hàng tiêu đề cột: bỏ qua viền trên rồi đi hết vùng "heading" (đo một lần)."""
        if self._head_h is None:
            y = 0
            while y < 40 and self.tree.identify_region(30, y) != "heading":
                y += 1
            while y < 120 and self.tree.identify_region(30, y) == "heading":
                y += 1
            if y >= 120 or y < 5:
                return 30
            self._head_h = y
        return self._head_h

    def _place_expand(self):
        """Đặt từng khung đè lên các dòng giữ chỗ của nó (gọi lại khi cuộn / đổi cỡ); phần lấn lên tiêu đề cột thì
        cắt đi."""
        for st in list(self.expanded.values()):
            box, inner, spacers, rowh = st["box"], st["inner"], st["spacers"], st["rowh"]
            try:
                top = None
                for k, sp in enumerate(spacers):
                    bb = self.tree.bbox(sp)
                    if bb:
                        top = bb[1] - k * rowh
                        break
                if top is None:
                    box.place_forget()
                    continue
                total = len(spacers) * rowh
                y0 = max(top, self._heading_height())
                y1 = min(top + total, self.tree.winfo_height())
                if y1 <= y0:
                    box.place_forget()
                    continue
                box.place(x=0, y=y0, relwidth=1, height=y1 - y0)
                inner.place(x=0, y=top - y0, relwidth=1, height=total - 1)
            except tk.TclError:
                pass

    def _build_expand(self, inner, info, ages):
        """Hai đội cạnh nhau (2 đội một hàng): Người chơi / Quân / Kích đời 2 / 3 / 4; khung giãn đều theo số dòng."""
        from mapcap import theme
        C = theme.C
        F = theme.F
        bg2 = C["bg2"]
        grid = tk.Frame(inner, bg=C["panel"])
        grid.pack(fill="both", expand=True, padx=4, pady=1)
        teams = {}
        for pl in info.get("players", []):
            teams.setdefault(pl.get("team", 0), []).append(pl)
        rec_name = info.get("recorder")
        for k, (_team, pls) in enumerate(sorted(teams.items())):
            box = tk.Frame(grid, bg=bg2, highlightthickness=1, highlightbackground=C["line2"])
            box.grid(row=k // 2, column=k % 2, sticky="nsew", padx=2, pady=1)
            grid.columnconfigure(k % 2, weight=1, uniform="team")
            grid.rowconfigure(k // 2, weight=1)
            tb = tk.Frame(box, bg=bg2)
            tb.pack(fill="x", expand=True, padx=8, pady=1)
            heads = ("Người chơi", "Quân", "Kích 2", "Kích 3", "Kích 4")
            for c, h in enumerate(heads):
                tk.Label(tb, text=h, bg=bg2, fg=C["gold"] if c == 3 else C["dim"], font=F(8, "bold"), bd=0, pady=0,
                         anchor="w" if c < 2 else "e").grid(row=0, column=c, sticky="we", padx=(0, 10))
            tb.columnconfigure(0, weight=1)
            for r, pl in enumerate(pls, start=1):
                a = (ages or {}).get(str(pl.get("index")), {})
                me = pl.get("name") == rec_name
                tk.Label(tb, text=pl.get("name", "?"), bg=bg2, fg=C["gold_hi"] if me else C["text"], bd=0, pady=0,
                         font=F(9, "bold" if me else "normal"), anchor="w").grid(row=r, column=0, sticky="we",
                                                                                 padx=(0, 10))
                tk.Label(tb, text=pl.get("civ", ""), bg=bg2, fg=C["muted"], font=F(9), bd=0, pady=0, anchor="w").grid(
                    row=r, column=1, sticky="we", padx=(0, 10))
                for c, age in ((2, "2"), (3, "3"), (4, "4")):
                    t = (a.get(age) or {}).get("click")
                    txt = "…" if ages is None else fmt_clock(t)
                    tk.Label(tb, text=txt, bg=bg2, fg=C["gold_hi"] if c == 3 and t is not None else
                             (C["text"] if t is not None else C["dim"]), font=F(9, "bold" if c == 3 else "normal"),
                             bd=0, pady=0, anchor="e").grid(row=r, column=c, sticky="we", padx=(0, 10))

    def open_selected(self):
        p = self.selected_path()
        if p and self.on_open:
            self.on_open(p)

    def _choose_dir(self):
        d = filedialog.askdirectory(parent=self, initialdir=self.folder, title="Chọn thư mục chứa file .aoerec")
        if d:
            self.set_folder(os.path.normpath(d))

    def delete_selected(self):
        """Xoá trận đang chọn (đưa file vào Thùng rác, hỏi lại trước). Không xoá trận đang ghi."""
        from tkinter import messagebox
        p = self.selected_path()
        if not p:
            return False
        info = self.infos.get(p, {})
        busy = self.is_busy(p) if self.is_busy else False
        try:
            busy = busy or (time.time() - os.path.getmtime(p) < 15)
        except OSError:
            pass
        if busy:
            messagebox.showinfo("Xoá trận", "Trận này đang được ghi, chưa xoá được.", parent=self)
            return False
        desc = f"{time.strftime('%d/%m/%Y %H:%M', time.localtime(info.get('created', 0)))} · {info.get('recorder', '')} · " \
               f"{info.get('format', '')} {info.get('civ_mode', '')} · {info.get('result', '')}"
        if not messagebox.askyesno("Xoá trận", f"Xoá trận này?\n\n{desc}\n{os.path.basename(p)}\n\n"
                                   "File được đưa vào Thùng rác (khôi phục được).", parent=self, icon="warning"):
            return False
        ok, err = send_to_recycle_bin(p)
        if not ok:
            messagebox.showerror("Xoá trận", f"Không xoá được: {err}", parent=self)
            return False
        nxt = self.tree.next(p) or self.tree.prev(p)
        self.infos.pop(p, None)
        self._refill()
        if nxt and self.tree.exists(nxt):
            self.tree.selection_set(nxt)
            self.tree.focus(nxt)
        self.var_status.set(f"Đã xoá {os.path.basename(p)} (trong Thùng rác).")
        return True

    def stop(self):
        self._gen += 1


def _log_update(msg):
    """Nhật ký cập nhật của AoE-Replay: Video\\Raw\\_replay.log cạnh exe (cùng chỗ log của trình xem)."""
    try:
        import datetime
        with open(os.path.join(default_folder(), "_replay.log"), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] cập nhật: {msg}\n")
    except Exception:  # noqa: BLE001
        pass


class PickerWindow:
    """Cửa sổ riêng: bảng trận + nút Xem replay / Mở file khác / Đóng."""

    def __init__(self, master, folder, on_open, title="Chọn trận để xem replay", standalone=False):
        self.standalone = standalone
        self.result = None
        self.on_open = on_open
        self.top = master if standalone else tk.Toplevel(master)
        self.top.title(title)
        self.top.minsize(760, 380)
        self.top.geometry("1000x540")
        self.table = MatchTable(self.top, folder, self._open)
        self.table.pack(fill="both", expand=True, padx=10, pady=(8, 4))
        bot = ttk.Frame(self.top)
        bot.pack(fill="x", padx=10, pady=(4, 10))
        ttk.Label(bot, textvariable=self.table.var_status, foreground="#666").pack(side="left")
        ttk.Button(bot, text="Đóng", command=self._close).pack(side="right", padx=4)
        ttk.Button(bot, text="Mở file khác...", command=self._open_other).pack(side="right", padx=4)
        ttk.Button(bot, text="Xem replay", command=self.table.open_selected).pack(side="right", padx=4)
        ttk.Button(bot, text="Xoá trận", command=self.table.delete_selected).pack(side="right", padx=4)
        self.top.protocol("WM_DELETE_WINDOW", self._close)

    # tương thích với mã/test cũ
    @property
    def tree(self):
        return self.table.tree

    @property
    def var_status(self):
        return self.table.var_status

    @property
    def var_find(self):
        return self.table.var_find

    @property
    def var_detail(self):
        return self.table.var_detail

    def set_folder(self, folder):
        self.table.set_folder(folder)

    def _sort(self, key):
        self.table._sort(key)

    def _show_detail(self):
        self.table._show_detail()

    def _open(self, path=None):
        path = path or self.table.selected_path()
        if not path:
            return
        if self.standalone:
            self.result = path
            self.top.destroy()
        elif self.on_open:
            self.on_open(path)

    def _open_other(self):
        p = filedialog.askopenfilename(parent=self.top, initialdir=self.table.folder, title="Chọn dữ liệu trận",
                                       filetypes=[("Dữ liệu thô AoE-MapCap", "*.aoerec"), ("Tất cả", "*.*")])
        if p:
            self._open(p)

    def _close(self):
        self.table.stop()
        self.top.destroy()


def send_to_recycle_bin(path):
    """Đưa file vào Thùng rác của Windows (SHFileOperationW + FOF_ALLOWUNDO). Trả về (ok, lỗi)."""
    if os.name != "nt":
        try:
            os.remove(path)
            return True, ""
        except OSError as e:
            return False, str(e)
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", ctypes.c_uint), ("pFrom", ctypes.c_wchar_p),
                    ("pTo", ctypes.c_wchar_p), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", ctypes.c_wchar_p)]
    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    op = SHFILEOPSTRUCTW(None, FO_DELETE, os.path.abspath(path) + "\0", None,
                         FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI, False, None, None)
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0 or op.fAnyOperationsAborted or os.path.exists(path):
        return False, f"mã lỗi {rc}"
    return True, ""


def app_icon():
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(base, "assets", "app.ico")
    return p if os.path.exists(p) else ""


def default_folder():
    """Thư mục Video\\Raw cạnh exe / thư mục làm việc, nếu có."""
    base = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else sys.argv[0]))
    for d in (os.path.join(base, "Video", "Raw"), os.path.join(os.getcwd(), "Video", "Raw"),
              os.path.join(base, "dist", "Video", "Raw")):
        if os.path.isdir(d):
            return d
    return base


def pick_match(folder=None, check_update=False):
    """check_update: AoE-Replay.exe chạy riêng thì bảng chọn trận kiểm tra / tự cập nhật (AoE-MapCap tự lo phần mình)."""
    root = tk.Tk()
    try:
        if app_icon():
            root.iconbitmap(default=app_icon())
    except Exception:  # noqa: BLE001
        pass
    from mapcap.version import APP_VERSION
    w = PickerWindow(root, folder or default_folder(), None, title=f"AoE-Replay v{APP_VERSION} — chọn trận",
                     standalone=True)
    if check_update:
        from mapcap.update_ui import UpdateController
        UpdateController(root, root, "replay", "AoE-Replay", log=_log_update,
                         restart_args=lambda: [f"--folder={folder}"] if folder else [],
                         bar_before=w.table).start()
    root.mainloop()
    return w.result
