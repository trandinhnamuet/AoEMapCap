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

from mapcap.retention import load_keep, set_keep

from .library import Library, age3_of, fmt_duration

COLUMNS = (
    ("date", "Ngày", 136, "w"),
    ("name", "Người chơi", 150, "w"),
    ("civ", "Quân", 100, "w"),
    ("result", "Kết quả", 160, "w"),
    ("mode", "Thể thức", 110, "w"),          # "2v1 Random", "4v4 Shang"
    ("kind", "Map", 170, "w"),               # "Hill Country - Large"
    ("age3", "Kích 3", 64, "e"),             # giờ game người ghi kích đời 3
    ("dur", "Thời gian", 80, "e"),
)
COL_MIN = {"date": 124, "name": 88, "civ": 74, "result": 100, "mode": 76, "kind": 88, "age3": 54, "dur": 64}
RESULT_TAG = {"Thắng": "win", "Thua": "lose", "Đầu hàng": "lose", "Cần bản mới": "muted"}
HACK_MARK = "\u26a0 Có hack"     # cột Kết quả của trận có người chơi hack (mapcap/hackcheck)
PREFETCH_AGES = 40               # số trận mới nhất được tính sẵn giờ kích đời ở nền (mở rộng hiện ngay)
SPACER = "::sp"                  # iid dòng trống giữ chỗ cho khung mở rộng: "<đường dẫn>::sp<k>"


def fmt_clock(ms):
    if ms is None:
        return "—"
    s = max(0, int(ms) // 1000)
    return f"{s // 60}:{s % 60:02d}"


PIN_BG_DARK, PIN_BG_LIGHT = "#29241b", "#fffaf0"   # nền dòng trận ghim: ánh vàng rất nhẹ
PIN_EDGE = "#f0c674"                                 # viền 1 px vàng sáng
PIN_GLOW_MIX = (0.30, 0.12)                          # 2 lớp 1 px phía trong: nhạt dần (ánh sáng toả vào trong)


def _mix(a, b, t):
    """Màu a pha t phần sang b (#rrggbb)."""
    pa, pb = (int(a[i:i + 2], 16) for i in (1, 3, 5)), (int(b[i:i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(y + (x - y) * t):02x}" for x, y in zip(pa, pb))


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
        self.prefetch_ok = lambda: True  # giao diện chính: False khi đang ghi trận (không quét file nặng lúc chơi)
        self._pfonts = None
        self.folder = folder
        self._build(show_dir_button)
        self.set_folder(folder)
        self.after(100, self._poll)

    def _build(self, show_dir_button):
        from mapcap import theme
        dark = theme.APPLIED                                  # giao diện tối kiểu XArena (AoE-MapCap)
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))
        self.bar = bar                                        # AoE-MapCap gắn ô Tự dọn trận cũ vào hàng này
        self.dir_caption = ttk.Label(bar, text="Thư mục:", style="Muted.TLabel" if dark else "TLabel")
        self.dir_caption.pack(side="left")
        self.var_dir = tk.StringVar()
        self.dir_label = ttk.Label(bar, textvariable=self.var_dir, style="Muted.TLabel" if dark else "TLabel")
        self.dir_label.pack(side="left", padx=6)
        if show_dir_button:
            ttk.Button(bar, text="Đổi thư mục...", command=self._choose_dir).pack(side="right")
        # hàng trên gọn (bảng ở AoE-MapCap chỉ rộng ~700 px cạnh thanh bên): Làm mới là nút biểu tượng, nhãn "Tìm:"
        refresh = ttk.Button(bar, text="⟳", width=3, command=self.reload)
        refresh.pack(side="right", padx=(4, 0))
        theme.Tip(refresh, "Làm mới danh sách trận")
        self.var_find = tk.StringVar()
        find = ttk.Entry(bar, textvariable=self.var_find, width=20)
        find.pack(side="right", padx=(4, 12))
        theme.Tip(find, "Tìm theo tên người chơi, tên file, map, ngày... (gõ một phần là đủ)")
        ttk.Label(bar, text="Tìm:", style="Muted.TLabel" if dark else "TLabel").pack(side="right")
        self.var_find.trace_add("write", lambda *_: self._refill())
        # lọc chỉ trận đã ghim (người dùng 12/11: trước phải kéo cả bảng tìm dấu ★)
        self.var_pinned_only = tk.BooleanVar(value=False)
        self.pin_check = ttk.Checkbutton(bar, text="★ Trận đã ghim", variable=self.var_pinned_only,
                                         command=self._refill)
        self.pin_check.pack(side="right", padx=(0, 14))
        self._pin_frames = []        # viền sáng đè lên các dòng trận ghim đang thấy (_place_pins)

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(mid, columns=[c[0] for c in COLUMNS], show="headings", selectmode="browse")
        for key, label, w, anchor in COLUMNS:
            self.tree.heading(key, text=label, command=lambda k=key: self._sort(k))
            self.tree.column(key, width=w, anchor=anchor, stretch=key in ("name", "kind"))
        self.tree.tag_configure("win", foreground=theme.C["green"] if dark else "#1b7a1b")
        self.tree.tag_configure("lose", foreground=theme.C["lose"] if dark else "#b02020")
        self.tree.tag_configure("muted", foreground=theme.C["dim"] if dark else "#888888")
        self.tree.tag_configure("hack", foreground="#ff6b6b" if dark else "#c62828")
        if dark:
            self.tree.tag_configure("odd", background=theme.C["bg2"])    # dòng xen kẽ
        sb = ttk.Scrollbar(mid, command=self.tree.yview)
        self.tree.configure(yscrollcommand=lambda a, b: (sb.set(a, b), self._place_expand()))
        self.tree.tag_configure("spacer", background=theme.C["panel"] if dark else "#f4f4f4")
        # trận ghim: nền ánh vàng (tạo sau "odd" nên được ưu tiên) + viền vàng sáng (_place_pins)
        pin_bg = PIN_BG_DARK if dark else PIN_BG_LIGHT
        self.tree.tag_configure("pin", background=pin_bg)
        self._pin_colors = (PIN_EDGE,) + tuple(_mix(PIN_EDGE, pin_bg, t) for t in PIN_GLOW_MIX)
        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<Configure>", lambda e: self.after_idle(self._place_expand), add="+")
        self.tree.bind("<Configure>", lambda e: self._fit_columns(e.width), add="+")
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self._on_double)
        for ev in ("<<TreeviewOpen>>", "<<TreeviewClose>>"):    # mở / đóng dòng chỉ theo chuột phải
            self.tree.bind(ev, lambda e: self.after_idle(self._sync_open))
        self.tree.bind("<Return>", lambda e: self.open_selected())
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._show_detail())
        self.tree.bind("<Delete>", lambda e: self.delete_selected())
        self.var_detail = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.var_detail, style="Detail.TLabel" if dark else "TLabel", justify="left",
                  wraplength=900).pack(fill="x", pady=(8, 0))
        self.var_status = tk.StringVar(value="")
        self.bind("<Configure>", lambda e: self._wrap(e.width))

    def _fit_columns(self, width):
        """Các cột luôn vừa bề rộng bảng (người dùng 12/11: cột Thời gian bị che nửa): rộng thì phần dư cho Người chơi
        và Map, hẹp thì co mọi cột theo tỉ lệ phần co được (không nhỏ hơn COL_MIN)."""
        try:                                      # màn hình phóng to chữ (125 %, 150 %): cột tối thiểu rộng theo
            scale = max(1.0, float(self.tk.call("tk", "scaling")) / (96 / 72))
        except (tk.TclError, ValueError):
            scale = 1.0
        avail = width - 4
        base = {k: w * scale for k, _l, w, _a in COLUMNS}
        mins = {k: COL_MIN.get(k, 50) * scale for k in base}
        try:                                      # tiêu đề cột luôn đọc đủ ("Thời gian" không thành "Thời giar")
            from tkinter import font as tkfont
            hf = tkfont.Font(font=ttk.Style().lookup("Treeview.Heading", "font") or "TkHeadingFont")
            for k, label, _w, _a in COLUMNS:
                mins[k] = max(mins[k], hf.measure(label) + 22)
                base[k] = max(base[k], mins[k])
        except (tk.TclError, ValueError):
            pass
        total = sum(base.values())
        if avail >= total:
            extra = avail - total
            out = dict(base)
            out["name"] += extra / 2
            out["kind"] += extra - extra / 2
        else:
            slack = sum(base[k] - mins[k] for k in base)
            f = max(0.0, 1 - (total - avail) / slack) if slack > 0 else 0.0
            out = {k: mins[k] + (base[k] - mins[k]) * f for k in base}
        for k, w in out.items():
            self.tree.column(k, width=int(w), stretch=False)

    def _wrap(self, width):
        for w in self.winfo_children():
            if isinstance(w, ttk.Label) and str(w.cget("textvariable")) == str(self.var_detail):
                w.configure(wraplength=max(300, width - 20))

    # ---- dữ liệu ---------------------------------------------------------------------------
    def set_folder(self, folder):
        self.folder = folder
        self.var_dir.set(folder)
        self.infos = {}
        self.pinned = load_keep(folder)
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
        # tính sẵn giờ kích đời các trận mới nhất (file cũ chưa có trong 'E' phải quét cả file, 2-6 s mỗi trận):
        # đệm vào _matches.json nên chỉ quét một lần; tạm dừng khi đang ghi trận
        for p in files[:PREFETCH_AGES]:
            np_ = os.path.normpath(p)
            if np_ in self._ages or np_ in self._ages_busy:
                continue
            try:
                if time.time() - os.path.getmtime(p) < 60:
                    continue                          # trận đang ghi / vừa ghi xong
            except OSError:
                continue
            while not self.prefetch_ok():
                if gen != self._gen:
                    return
                time.sleep(2)
            if gen != self._gen:
                return
            try:
                ages = lib.ages(p)
                lib.save()
            except Exception:  # noqa: BLE001
                continue
            self.q.put(("ages", gen, np_, ages))

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
                if "age3" not in info and p in self._ages and "rec_index" in info:
                    info["age3"] = age3_of(self._ages[p], info["rec_index"])
                self.infos[p] = info
                changed = True
                self.var_status.set(f"Đang đọc {k}/{n} trận…")
            elif msg[0] == "ages":
                _, _, p, ages = msg
                self._ages[p] = ages
                self._ages_busy.discard(p)
                info = self.infos.get(p)
                if info is not None and "error" not in info and not info.get("recording") and "age3" not in info:
                    info["age3"] = age3_of(ages, info.get("rec_index"))
                    if self.tree.exists(p):
                        self.tree.set(p, "age3", fmt_clock(info["age3"]))
                if p in self.expanded:
                    self._draw_panel(p)
            elif msg[0] == "done":
                # đọc xong: không ghi câu hướng dẫn "N trận. Bấm đúp…" (người dùng 12/11 bỏ)
                self.var_status.set("" if msg[2] else "Chưa có trận nào được ghi.")
        if changed:
            self._refill()
        try:
            self.after(150, self._poll)
        except tk.TclError:
            pass

    @staticmethod
    def _row(info):
        if info.get("recording"):                  # file đang bị bộ ghi giữ: trận đang đánh
            return (time.strftime("%d/%m/%Y %H:%M", time.localtime(info.get("created", 0))), info["file"], "",
                    "● Đang ghi", "", "xem được khi hết trận", "", ""), "muted"
        if "error" in info:
            return (time.strftime("%d/%m/%Y %H:%M", time.localtime(info.get("created", 0))), info["file"], "",
                    "lỗi đọc file", "", info["error"][:40], "", ""), "muted"
        hacked = bool(info.get("hack"))
        vals = (time.strftime("%d/%m/%Y %H:%M", time.localtime(info["created"])), info["recorder"],
                info["recorder_civ"], (f"{HACK_MARK} · {info['result']}" if hacked else info["result"]),
                f"{info['format']} {info['civ_mode']}", info["map"],
                (fmt_clock(info["age3"]) if "age3" in info else ""), fmt_duration(info["duration_ms"]))
        return vals, ("hack" if hacked else RESULT_TAG.get(info["result"], ""))

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
            if key == "age3":                       # chưa biết / không lên đời 3 xếp cuối
                t = info.get("age3")
                return t if t is not None else (float("-inf") if desc else float("inf"))
            return str(self._row(info)[0][idx]).lower()
        row = 0
        pinned_only = self.var_pinned_only.get()
        for p, info in sorted(self.infos.items(), key=sort_val, reverse=desc):
            if pinned_only and os.path.basename(p) not in self.pinned:
                continue
            if find:
                hay = " ".join([info.get("file", "")] + [pl.get("name", "") for pl in info.get("players", [])] +
                               [str(v) for v in self._row(info)[0]]).lower()
                if find not in hay:
                    continue
            vals, tag = self._row(info)
            pin = os.path.basename(p) in self.pinned
            if pin:                                             # ghim: không tự dọn (mapcap/retention)
                vals = ("★ " + vals[0],) + tuple(vals[1:])
            tags = ((tag,) if tag else ()) + (("pin",) if pin else ("odd",) if row % 2 else ())
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
        if pinned_only and not row:
            self.var_status.set("Chưa có trận ghim." if not self.pinned else "Không có trận ghim khớp.")
        self.after_idle(self._place_pins)

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
        """Mở rộng ngay dưới dòng: chèn dòng trống giữ chỗ rồi đặt khung (một Canvas) đè lên đúng chỗ đó."""
        info = self.infos.get(path)
        if not info or "error" in info or not self.tree.exists(path):
            return
        self._collapse(path)
        ages = self._ages.get(path)
        if ages is None:
            self._load_ages(path)
        teams, row_h = self._panel_layout(info)
        box = tk.Frame(self.tree, bg=self._C("line"), highlightthickness=0, bd=0)
        cv = tk.Canvas(box, bg=self._C("panel"), highlightthickness=0, bd=0)
        bb = self.tree.bbox(path)
        rowh = bb[3] if bb else 30
        n = max(1, -(-(sum(row_h) + 3) // rowh))
        spacers = []
        for k in range(n):
            iid = f"{path}{SPACER}{k}"
            self.tree.insert(path, "end", iid=iid, values=("",) * len(COLUMNS), tags=("spacer",))
            spacers.append(iid)
        self.tree.item(path, open=True)
        self.expanded[path] = {"spacers": spacers, "box": box, "inner": cv, "rowh": rowh, "info": info,
                               "teams": teams, "row_h": row_h, "geom": None, "drawn": None}
        cv.bind("<Configure>", lambda e, p=path: self._draw_panel(p))
        for w in (box, cv):
            w.bind("<Button-3>", lambda e, p=path: self.toggle_expand(p))
            w.bind("<Double-1>", lambda e, p=path: (self.on_open and self.on_open(p), "break")[1])
            w.bind("<MouseWheel>", self._wheel)      # chuột trên khung mở rộng: vẫn cuộn bảng (như Treeview)
        if scroll:
            self.tree.see(spacers[-1])
            self.tree.see(path)
        self.after_idle(self._place_expand)

    def _on_double(self, e):
        """Bấm đúp: chỉ mở replay. "break" chặn hành vi sẵn của Treeview (bấm đúp = mở / đóng dòng con), trước đây
        làm dòng vừa mở replay vừa bung / gập."""
        if self.tree.identify_region(e.x, e.y) in ("cell", "tree"):
            self.open_selected()
        return "break"

    def _sync_open(self):
        """Trạng thái mở của dòng luôn theo khung mở rộng (phím mũi tên / bấm đúp không được bung / gập riêng)."""
        for p in self.tree.get_children():
            want = p in self.expanded
            if bool(self.tree.item(p, "open")) != want:
                self.tree.item(p, open=want)
        self.after_idle(self._place_expand)

    def _wheel(self, e):
        """Bánh xe chuột trên khung mở rộng (widget con riêng, Treeview không nhận): cuộn bảng đúng như Treeview."""
        if e.delta:
            self.tree.yview_scroll(int(-e.delta / 120) or (-1 if e.delta > 0 else 1), "units")
        return "break"

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
        cắt đi. Chỉ gọi place khi vị trí đổi."""
        for st in list(self.expanded.values()):
            box, inner, spacers, rowh = st["box"], st["inner"], st["spacers"], st["rowh"]
            try:
                top = None
                for k, sp in enumerate(spacers):
                    bb = self.tree.bbox(sp)
                    if bb:
                        top = bb[1] - k * rowh
                        break
                geom = None
                if top is not None:
                    total = len(spacers) * rowh
                    y0 = max(top, self._heading_height())
                    y1 = min(top + total, self.tree.winfo_height())
                    if y1 > y0:
                        geom = (y0, y1 - y0, top - y0, total - 1)
                if geom == st["geom"]:
                    continue
                st["geom"] = geom
                if geom is None:
                    box.place_forget()
                    continue
                box.place(x=0, y=geom[0], relwidth=1, height=geom[1])
                inner.place(x=0, y=geom[2], relwidth=1, height=geom[3])
            except tk.TclError:
                pass
        self._place_pins()

    def _pin_frame(self, k):
        """Bộ dải viền thứ k (mỗi lớp 4 cạnh 1 px), tạo khi cần; bấm lên viền = bấm lên dòng."""
        while len(self._pin_frames) <= k:
            parts = []
            for color in self._pin_colors:
                for _side in range(4):
                    f = tk.Frame(self.tree, bg=color, highlightthickness=0, bd=0)
                    f.bind("<Button-1>", lambda e, j=len(self._pin_frames): self._pin_click(j))
                    f.bind("<Double-1>", lambda e, j=len(self._pin_frames): (self._pin_click(j), self.open_selected(),
                                                                              "break")[2])
                    f.bind("<Button-3>", lambda e, j=len(self._pin_frames): self.toggle_expand(self._pin_iid(j)))
                    f.bind("<MouseWheel>", self._wheel)
                    parts.append(f)
            self._pin_frames.append({"parts": parts, "iid": None, "geom": None})
        return self._pin_frames[k]

    def _pin_iid(self, j):
        return self._pin_frames[j]["iid"] if j < len(self._pin_frames) else None

    def _pin_click(self, j):
        iid = self._pin_iid(j)
        if iid and self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self.tree.focus_set()

    def _place_pins(self):
        """Viền vàng 1 px + 2 lớp nhạt dần vào trong quanh các dòng trận ghim đang thấy (Treeview không vẽ viền từng dòng): đặt lại khi
        cuộn / đổi cỡ / lọc; chỉ gọi place khi vị trí đổi."""
        try:
            bottom = self.tree.winfo_height()           # Treeview cuộn theo nguyên dòng: dòng thấy = có bbox
            rows = []
            for iid in self.tree.get_children():
                if os.path.basename(iid) not in self.pinned:
                    continue
                bb = self.tree.bbox(iid)
                if bb and 0 <= bb[1] < bottom:
                    rows.append((iid, (bb[0], bb[1], bb[2], min(bb[3], bottom - bb[1]))))
        except tk.TclError:
            return
        for k, (iid, geom) in enumerate(rows):
            fr = self._pin_frame(k)
            fr["iid"] = iid
            if fr["geom"] == geom:
                continue
            fr["geom"] = geom
            x, y, w, h = geom
            for layer in range(len(self._pin_colors)):
                o, t = layer, 1                             # mỗi lớp 1 px, lớp sau nằm trong lớp trước
                xs, ys, ws, hs = x + o, y + o, w - 2 * o, h - 2 * o
                top, bot, lef, rig = fr["parts"][layer * 4:layer * 4 + 4]
                top.place(x=xs, y=ys, width=ws, height=t)
                bot.place(x=xs, y=ys + hs - t, width=ws, height=t)
                lef.place(x=xs, y=ys, width=t, height=hs)
                rig.place(x=xs + ws - t, y=ys, width=t, height=hs)
        for fr in self._pin_frames[len(rows):]:
            if fr["geom"] is not None:
                fr["geom"], fr["iid"] = None, None
                for f in fr["parts"]:
                    f.place_forget()

    def _fonts(self):
        if self._pfonts is None:
            from tkinter import font as tkfont

            from mapcap import theme
            F = theme.F
            self._pfonts = {"head": tkfont.Font(font=F(8, "bold")), "txt": tkfont.Font(font=F(9)),
                            "bold": tkfont.Font(font=F(9, "bold"))}
        return self._pfonts

    def _panel_layout(self, info):
        """Đội (đã sắp) và chiều cao từng hàng ô đội (2 đội một hàng)."""
        teams = {}
        for pl in info.get("players", []):
            teams.setdefault(pl.get("team", 0), []).append(pl)
        teams = [pls for _t, pls in sorted(teams.items())]
        f = self._fonts()
        head, lh = f["head"].metrics("linespace"), f["txt"].metrics("linespace")
        row_h = []
        for r in range(0, len(teams), 2):
            n = max(len(p) for p in teams[r:r + 2])
            row_h.append(head + n * lh + 6)
        return teams, row_h or [head + 6]

    def _draw_panel(self, path):
        """Vẽ khung mở rộng lên Canvas: mỗi đội một ô (2 ô một hàng), cột Người chơi / Quân / Kích 2 / 3 / 4."""
        st = self.expanded.get(path)
        if st is None:
            return
        cv = st["inner"]
        W, H = cv.winfo_width(), cv.winfo_height()
        ages = self._ages.get(path)
        key = (W, H, id(ages))
        if W < 50 or H < 10 or st["drawn"] == key:
            return
        st["drawn"] = key
        from mapcap import theme
        C = theme.C
        f = self._fonts()
        head_h, lh = f["head"].metrics("linespace"), f["txt"].metrics("linespace")
        teams, row_h = st["teams"], st["row_h"]
        extra = max(0, H - 2 - sum(row_h)) / max(len(row_h), 1)      # giãn đều cho kín các dòng giữ chỗ
        ncol = 2 if len(teams) > 1 else 1
        colw = (W - 8) / ncol
        rec_name = st["info"].get("recorder")
        tw = max(f["head"].measure("Kích 4"), f["bold"].measure("00:00")) + 12
        cv.delete("all")
        y_row = 1
        for r, rh in enumerate(row_h):
            h = rh + extra
            for c in range(ncol):
                k = r * 2 + c
                if k >= len(teams):
                    break
                pls = teams[k]
                x0, x1 = 4 + c * colw + 2, 4 + (c + 1) * colw - 2
                y0, y1 = y_row + 1, y_row + h - 1
                cv.create_rectangle(x0, y0, x1, y1, fill=C["bg2"], outline=C["line2"])
                ty = y0 + (y1 - y0 - (head_h + len(pls) * lh)) / 2
                rx = [x1 - 10 - 2 * tw, x1 - 10 - tw, x1 - 10]            # mép phải cột Kích 2 / 3 / 4
                nx = x0 + 9
                hackers = {e.get("player") for e in st["info"].get("hack") or []}
                namew = max([f["head"].measure("Người chơi")] +
                            [f["bold" if p.get("name") == rec_name or p.get("index") in hackers else "txt"].measure(
                                p.get("name", "?") + ("  ⚠ HACK" if p.get("index") in hackers else "")) for p in pls])
                cx = min(nx + namew + 14, rx[0] - tw - 60)
                cv.create_text(nx, ty, text="Người chơi", anchor="nw", fill=C["dim"], font=f["head"])
                cv.create_text(cx, ty, text="Quân", anchor="nw", fill=C["dim"], font=f["head"])
                for j, h_ in enumerate(("Kích 2", "Kích 3", "Kích 4")):
                    cv.create_text(rx[j], ty, text=h_, anchor="ne", fill=C["gold"] if j == 1 else C["dim"],
                                   font=f["head"])
                for i, pl in enumerate(pls):
                    y = ty + head_h + i * lh
                    me = pl.get("name") == rec_name
                    hk = pl.get("index") in hackers
                    cv.create_text(nx, y, text=pl.get("name", "?") + ("  \u26a0 HACK" if hk else ""), anchor="nw",
                                   fill="#ff6b6b" if hk else (C["gold_hi"] if me else C["text"]),
                                   font=f["bold" if me or hk else "txt"])
                    cv.create_text(cx, y, text=pl.get("civ", ""), anchor="nw", fill=C["muted"], font=f["txt"])
                    a = (ages or {}).get(str(pl.get("index")), {})
                    for j, age in enumerate(("2", "3", "4")):
                        t = (a.get(age) or {}).get("click")
                        txt = "…" if ages is None else fmt_clock(t)
                        col = C["gold_hi"] if j == 1 and t is not None else (C["text"] if t is not None else C["dim"])
                        cv.create_text(rx[j], y, text=txt, anchor="ne", fill=col, font=f["bold" if j == 1 else "txt"])
            y_row += h

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

    def toggle_pin_selected(self):
        """Ghim / bỏ ghim trận đang chọn: trận ghim (★) không bao giờ bị tự dọn. Trả về True nếu giờ đang ghim."""
        p = self.selected_path()
        if not p:
            self.var_status.set("Chọn một trận để ghim.")
            return None
        name = os.path.basename(p)
        on = name not in self.pinned
        try:
            self.pinned = set_keep(self.folder, name, on)
        except OSError as e:
            self.var_status.set(f"Không ghim được: {e}")
            return None
        self._refill()          # không ghi dòng trạng thái: chữ dài tràn hàng nút (người dùng 12/11); ★ + viền là đủ
        self.var_status.set("")
        return on

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


from mapcap.retention import send_to_recycle_bin  # noqa: E402,F401  (giữ tên cũ cho chỗ gọi khác)


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
