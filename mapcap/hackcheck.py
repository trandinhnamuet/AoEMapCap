"""Phát hiện hack trong trận theo danh sách luật (người dùng duyệt 2026-11-11).

Chạy trên từng mẫu (Snapshot có .cmds = lệnh mới đọc từ hàng đợi, mapcap/commands.py): trong tiến trình ghi lúc
đang chơi (báo ngay: âm thanh + thông báo trên app) và khi quét lại file .aoerec (analyze_file). Kết quả tổng hợp
ghi vào bản ghi 'E' của file ("hack") để danh sách trận đánh dấu trận có người hack.

Luật theo LỆNH (người gửi = người chơi gửi lệnh qua mạng, không giả mạo được):
  L1 ra lệnh cho thú / vật thể Gaia
  L2 ra lệnh cho unit / công trình của người chơi khác
  L3 xoá vật thể của người chơi khác (lệnh Delete, game không kiểm tra chủ)
  L4 lệnh đầu hàng mang số của người chơi khác
  L5 lệnh cheat (tạo unit, cộng tài nguyên, xây tức thì, mã cheat) khi phòng KHÔNG bật cho phép cheat
  L7 ra quân / nghiên cứu thứ người đó chưa mở
Luật theo TRẠNG THÁI (khi phòng không bật cheat):
  S1 tài nguyên bất kỳ vượt 1.000.000
  S2 tài nguyên tăng >= 1000 trong 1 giây mà không người nào bị trừ tương ứng (không phải cống nạp)
  S3 có unit chỉ cheat mới có (xe hơi, Photon Man, Medusa, lính hạt nhân...)

Chống báo nhầm:
  - Lệnh của máy (AI) do máy chủ phòng gửi thay: L2/L3/L4 chỉ kết luận khi chủ vật thể bị tác động TỰ gửi lệnh
    (người thật); chưa rõ thì giữ chờ, hết trận vẫn chưa rõ (= AI) thì bỏ.
  - Unit vừa đổi chủ (bị phù thuỷ dụ) trong 5 giây: lệnh của chủ cũ không tính.
  - L7: danh sách unit đã mở chỉ đọc 2 s/lần -> chờ 6 s rồi mới kết luận.
"""
import collections

from . import commands as C

RULES = {
    "L1": "Điều khiển thú / vật thể Gaia",
    "L2": "Điều khiển quân / nhà của người khác",
    "L3": "Xoá quân / nhà của người khác",
    "L4": "Ép người khác đầu hàng",
    "L5": "Dùng lệnh cheat (phòng không bật cheat)",
    "L7": "Ra quân / nâng cấp thứ chưa mở",
    "S1": "Tài nguyên vượt 1.000.000",
    "S2": "Tài nguyên tăng đột biến không rõ nguồn",
    "S3": "Có unit chỉ cheat mới có",
}
# giải thích từng luật (tab Cài đặt -> Phát hiện hack)
RULE_DETAILS = {
    "L1": "Ra lệnh cho thú rừng, cây, mỏ... (vật thể của Gaia). Người chơi thường không chọn và ra lệnh được.",
    "L2": "Ra lệnh di chuyển / đánh / dừng cho quân hoặc nhà của người chơi khác (kể cả đồng minh).",
    "L3": "Gửi lệnh xoá quân / nhà không phải của mình.",
    "L4": "Gửi lệnh đầu hàng thay cho người chơi khác.",
    "L5": "Gửi lệnh cheat (tạo unit, thêm tài nguyên, xây tức thì...) trong phòng không bật cheat.",
    "L7": "Ra quân hoặc nghiên cứu công nghệ mà người đó chưa mở được (chưa đủ đời / thiếu nhà / văn minh không có).",
    "S1": "Một loại tài nguyên bất kì vượt 1.000.000.",
    "S2": "Tài nguyên tăng từ 1.000 trở lên trong 1 giây mà không phải do được cống nạp.",
    "S3": "Có unit chỉ ra được bằng cheat (lính hạt nhân, Photon Man, Medusa, xe BIGDADDY...).",
}
RES_NAMES = {0: "thực phẩm", 1: "gỗ", 2: "đá", 3: "vàng"}
S1_LIMIT = 1_000_000
S2_JUMP = 1000.0
S2_WINDOW_MS = 1000
S2_WARMUP_MS = 10_000          # bỏ qua 10 giây đầu (tài nguyên khởi điểm)
OWNER_GRACE_MS = 5000          # unit đổi chủ trong chừng này: lệnh của chủ cũ không tính
L7_WAIT_MS = 6000              # chờ bảng quân đã mở (đọc 2 s/lần) trước khi kết luận
L7_AVAIL_MS = 6000             # công nghệ phải 'có thể nghiên cứu' trong chừng này trước lệnh
OWNER_EVERY = 5                # cập nhật bảng chủ vật thể mỗi chừng này mẫu
S3_EVERY = 25                  # quét unit cheat mỗi chừng này mẫu (~1 s)
UNIT_KIND_DOPPEL = 25
# DAT id unit không có trong cây công nghệ của trận ngẫu nhiên, chỉ ra được bằng cheat (empires.dat AoE-HD):
# lính hạt nhân (E=MC2 TROOPER), Photon Man, Medusa, Juggernaut, xe BIGDADDY / BIG MOMMA, em bé, Saint Francis,
# lính máy (Soldier_Mech), Mirror Tower, tàu vũ trụ
CHEAT_UNITS = {248: "lính hạt nhân", 274: "Photon Man", 298: "Medusa", 297: "Juggernaut", 372: "xe BIGDADDY",
               397: "xe BIG MOMMA", 398: "em bé cheat", 394: "Saint Francis", 386: "lính máy", 383: "Mirror Tower",
               337: "tàu vũ trụ"}


def cheats_allowed(match):
    """Phòng có bật 'cho phép cheat' không (byte TRIBE_Game+0x982 trong khối thiết lập đã ghi)."""
    if not match:
        return False
    if "cheats" in match:
        return bool(match["cheats"])
    raw = match.get("raw")
    if raw and len(raw) > 2:
        return bool(raw[0x982 - 0x980])
    return False


class Detector:
    def __init__(self, match=None, log=None):
        self.match = match
        self.cheats = cheats_allowed(match)
        self.log = log or (lambda m: None)
        self.names = {}                      # index -> tên
        self.owner = {}                      # uid -> (chủ, giờ đổi chủ ms, chủ trước)
        self.senders = set()                 # người chơi đã tự gửi lệnh (người thật)
        self.found = {}                      # (index, luật) -> sự kiện tổng hợp
        self.pending = []                    # vi phạm chờ xác nhận (L2/L3/L4 chờ biết người thật; L7 chờ bảng quân)
        self.res_hist = collections.defaultdict(collections.deque)   # index -> deque[(t, (f, w, s, g))]
        self.avail_hist = collections.defaultdict(collections.deque)  # index -> deque[(t, set công nghệ)]
        self.trainable = collections.defaultdict(set)                 # index -> dat id unit đã thấy mở
        self.n = 0
        self.t = 0
        self.cmd_count = 0

    # ---- kết quả ---------------------------------------------------------------------------
    def _report(self, index, rule, t, detail):
        key = (index, rule)
        ev = self.found.get(key)
        if ev is not None:
            ev["count"] += 1
            return None
        ev = {"player": int(index), "name": self.names.get(index, f"P{index}"), "rule": rule, "label": RULES[rule],
              "t": int(t), "detail": detail, "count": 1}
        self.found[key] = ev
        self.log(f"PHÁT HIỆN HACK: {ev['name']} - {ev['label']} ({detail}) lúc {fmt_time(t)}")
        return dict(ev)

    def summary(self):
        """Danh sách vi phạm (mỗi người chơi + luật một mục, lần đầu và số lần), theo thời gian."""
        return sorted((dict(e) for e in self.found.values()), key=lambda e: (e["t"], e["player"], e["rule"]))

    def hackers(self):
        return sorted({e["player"] for e in self.found.values()})

    # ---- mỗi mẫu ---------------------------------------------------------------------------
    def feed(self, snap):
        """Xử lý một mẫu; trả các vi phạm MỚI (lần đầu của mỗi người chơi + luật)."""
        self.n += 1
        t = int(snap.time_ms or 0)
        self.t = t
        for p in snap.players:
            if p.index > 0:
                self.names[p.index] = (p.name or "").strip() or f"P{p.index}"
        if self.match is None and getattr(snap, "match", None):
            self.match = snap.match
            self.cheats = cheats_allowed(self.match)
        out = []
        if self.n == 1 or self.n % OWNER_EVERY == 0:
            self._update_owners(snap.units, t)
        self._track_players(snap, t)
        cmds = getattr(snap, "cmds", None) or ()
        if cmds:
            self.cmd_count += len(cmds)
            for _turn, sender, _seq, _data in cmds:
                if sender > 0:
                    self.senders.add(sender)
            look = None
            for turn, sender, seq, data in cmds:
                if look is None:
                    look = self._lookup(snap.units)
                out.extend(self._check_cmd(sender, bytes(data), t, look))
        out.extend(self._resolve_pending(t, final=False))
        if not self.cheats:
            out.extend(self._check_resources(snap, t))
            if self.n % S3_EVERY == 1:
                out.extend(self._check_cheat_units(snap.units, t))
        return [e for e in out if e]

    def finish(self):
        """Hết trận: xử lý nốt các vi phạm đang chờ; trả các vi phạm mới."""
        return [e for e in self._resolve_pending(self.t + 10 ** 9, final=True) if e]

    # ---- chủ vật thể -------------------------------------------------------------------------
    def _update_owners(self, units, t):
        own = self.owner
        for u in units:
            if getattr(u, "kind", 0) == UNIT_KIND_DOPPEL:
                continue
            o = own.get(u.uid)
            if o is None:
                own[u.uid] = (u.owner_index, -10 ** 9, None)
            elif o[0] != u.owner_index:
                own[u.uid] = (u.owner_index, t, o[0])

    def _lookup(self, units):
        """Chủ hiện tại của vật thể theo mẫu này (đủ mọi unit, kể cả vừa sinh)."""
        cur = {}
        for u in units:
            if getattr(u, "kind", 0) != UNIT_KIND_DOPPEL:
                cur[u.uid] = u.owner_index
        return cur

    def _owner_of(self, uid, look, t):
        """(chủ, chủ cũ nếu vừa đổi trong OWNER_GRACE_MS) hoặc (None, None) nếu không biết vật thể."""
        o = look.get(uid)
        rec = self.owner.get(uid)
        if o is None:
            if rec is None:
                return None, None
            o = rec[0]
        prev = rec[2] if rec is not None and rec[0] == o and t - rec[1] <= OWNER_GRACE_MS else None
        return o, prev

    # ---- luật theo lệnh ----------------------------------------------------------------------
    def _check_cmd(self, sender, data, t, look):
        out = []
        if not data or sender <= 0:
            return out
        typ = data[0]
        name = C.describe(data)
        # L5: lệnh cheat khi phòng không bật cheat
        if not self.cheats and (typ in (C.CREATE, C.ADD_ATTR) or
                                (typ == C.GAME and len(data) > 1 and data[1] in (C.GAME_INSTANT_BUILD, C.GAME_CHEAT))):
            out.append(self._report(sender, "L5", t, f"lệnh {name}"))
        # L4: đầu hàng thay người khác
        if typ == C.RESIGN and len(data) > 1 and data[1] != sender:
            self.pending.append({"kind": "victim", "rule": "L4", "sender": sender, "victim": int(data[1]), "t": t,
                                 "detail": f"đầu hàng thay P{data[1]}"})
        # L1 / L2 / L3: tác động vật thể không phải của mình
        for role, uid in C.unit_ids(data):
            owner, prev = self._owner_of(uid, look, t)
            if owner is None or owner == sender or prev == sender:
                continue
            if owner == 0:
                rule = "L3" if role == "delete" else "L1"
                out.append(self._report(sender, rule, t, f"{name} vật thể Gaia #{uid}"))
            else:
                rule = "L3" if role == "delete" else "L2"
                self.pending.append({"kind": "victim", "rule": rule, "sender": sender, "victim": owner, "t": t,
                                     "detail": f"{name} vật thể #{uid} của P{owner}"})
        # L7: ra quân / nghiên cứu thứ chưa mở (của chính người gửi)
        if typ == C.TRAIN and len(data) >= 0x0C:
            did = int.from_bytes(data[0xA:0xC], "little", signed=True)
            self.pending.append({"kind": "train", "rule": "L7", "sender": sender, "dat": did, "t": t,
                                 "detail": f"ra quân dat id {did} chưa mở"})
        if typ == C.RESEARCH and len(data) >= 0x0C:
            tech = int.from_bytes(data[0xA:0xC], "little", signed=True)
            if not self._tech_was_available(sender, tech, t):
                hist = self.avail_hist.get(sender)
                if hist:                                    # chỉ khi đã đọc được bảng công nghệ của người này
                    out.append(self._report(sender, "L7", t, f"nghiên cứu công nghệ {tech} chưa mở"))
        return out

    def _resolve_pending(self, t, final):
        out, keep = [], []
        for p in self.pending:
            if p["kind"] == "victim":
                if p["victim"] in self.senders:          # chủ vật thể là người thật -> vi phạm
                    out.append(self._report(p["sender"], p["rule"], p["t"], p["detail"]))
                elif not final:
                    keep.append(p)
                # hết trận mà chủ vẫn chưa từng gửi lệnh: máy (AI) do máy chủ điều khiển -> bỏ
            elif p["kind"] == "train":
                tr = self.trainable.get(p["sender"])
                if tr and p["dat"] in tr:
                    continue
                if t - p["t"] >= L7_WAIT_MS:
                    if tr:                               # chỉ kết luận khi đã đọc được bảng quân của người này
                        out.append(self._report(p["sender"], "L7", p["t"], p["detail"]))
                else:
                    keep.append(p)
        self.pending = keep
        return out

    def _tech_was_available(self, index, tech, t):
        hist = self.avail_hist.get(index)
        if not hist:
            return True
        return any(tech in s for tt, s in hist if t - tt <= L7_AVAIL_MS)

    # ---- trạng thái người chơi ---------------------------------------------------------------
    def _track_players(self, snap, t):
        for p in snap.players:
            if p.index <= 0:
                continue
            av = getattr(p, "available", None)
            rs = getattr(p, "researching", None)
            if av is not None:
                s = set(av) | set(rs or ())
                h = self.avail_hist[p.index]
                if not h or h[-1][1] != s or t - h[-1][0] > 2000:
                    h.append((t, s))
                while h and t - h[0][0] > L7_AVAIL_MS + 2000:
                    h.popleft()
            tr = getattr(p, "trainable", None)
            if tr:
                self.trainable[p.index].update(d for d, _loc, _btn in tr)

    def _check_resources(self, snap, t):
        out = []
        now = {}
        for p in snap.players:
            if p.index <= 0 or not p.attrs or len(p.attrs) < 4:
                continue
            now[p.index] = tuple(float(x) for x in p.attrs[:4])
            for r in range(4):
                if now[p.index][r] > S1_LIMIT:
                    out.append(self._report(p.index, "S1", t, f"{RES_NAMES[r]} {now[p.index][r]:,.0f}"))
        past = {}
        for idx, cur in now.items():
            h = self.res_hist[idx]
            h.append((t, cur))
            while len(h) > 1 and t - h[1][0] >= S2_WINDOW_MS:
                h.popleft()
            past[idx] = h[0]
        if t < S2_WARMUP_MS:
            return out
        for idx, cur in now.items():
            t0, old = past[idx]
            if t - t0 > S2_WINDOW_MS * 3 or t0 < S2_WARMUP_MS - S2_WINDOW_MS:
                continue
            for r in range(4):
                gain = cur[r] - old[r]
                if gain < S2_JUMP:
                    continue
                paid = sum(max(0.0, past[j][1][r] - now[j][r]) for j in now if j != idx)
                if paid >= gain * 0.9:                   # người khác bị trừ tương ứng: cống nạp
                    continue
                out.append(self._report(idx, "S2", t, f"+{gain:,.0f} {RES_NAMES[r]} trong {(t - t0) / 1000:.1f} s"))
        return out

    def _check_cheat_units(self, units, t):
        out = []
        for u in units:
            if u.owner_index <= 0 or getattr(u, "kind", 0) == UNIT_KIND_DOPPEL:
                continue
            did = getattr(u.udef, "dat_id", -1) if u.udef is not None else -1
            if did in CHEAT_UNITS and not u.is_dead:
                out.append(self._report(u.owner_index, "S3", t, CHEAT_UNITS[did]))
        return out


def fmt_time(ms):
    s = max(0, int(ms) // 1000)
    return f"{s // 3600:d}:{(s // 60) % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def analyze_file(path, log=None):
    """Quét lại cả file .aoerec theo cùng bộ luật; trả (summary, số lệnh đã xét). File cũ chưa có lệnh vẫn xét được
    các luật theo trạng thái."""
    from .rawrec import RawReader
    rr = RawReader(path)
    det = None
    for snap in rr.frames():
        if det is None:
            det = Detector((rr.header or {}).get("match"), log=log)
        det.feed(snap)
    if det is None:
        return [], 0
    det.finish()
    return det.summary(), det.cmd_count
