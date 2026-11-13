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

RULES_V = 2          # đời bộ luật ghi trong từng vi phạm ("v"); 2 = v42: S2 trừ hoàn tiền, L7 chỉ khi lệnh có tác dụng
L4_ON = False        # luật L4 báo oan (xem _check_cmd); bản ghi cũ có L4 cũng bị bỏ qua khi đọc (drop_false)


def drop_false(events):
    """Bỏ các vi phạm của luật đã tắt vì báo oan (L4) khỏi danh sách đọc từ file ghi cũ."""
    out = []
    for e in events or []:
        e = e or {}
        rule, new = e.get("rule"), int(e.get("v") or 0) >= RULES_V
        if rule == "L4" and not L4_ON:
            continue
        # kết luận của bản trước v42: S2 (chưa trừ hoàn tiền) và L7 nghiên cứu (báo cả lệnh bấm sớm) không đáng tin
        if not new and (rule == "S2" or (rule == "L7" and str(e.get("detail", "")).startswith("nghiên cứu"))):
            continue
        out.append(e)
    return out


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
S2_WAIT_MS = 1500              # chờ chừng này rồi mới kết luận S2 (hàng đợi sinh quân chỉ đọc 0,5 s/lần)
S2_REFUND_MS = 1500            # dấu hiệu hoàn tiền trong khoảng này quanh lúc tăng -> không phải hack
REFUND_EVERY = 5               # đếm công trình mỗi 5 mẫu
S2_WARMUP_MS = 10_000          # bỏ qua 10 giây đầu (tài nguyên khởi điểm)
OWNER_GRACE_MS = 5000          # unit đổi chủ trong chừng này: lệnh của chủ cũ không tính
L7_WAIT_MS = 6000              # chờ bảng quân đã mở (đọc 2 s/lần) trước khi kết luận
L7_OPEN_MS = 3000              # công nghệ mở ra trong chừng này SAU lệnh vẫn là hợp lệ (bấm sớm, bảng đọc trễ)
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
        # Dấu hiệu game HOÀN TIỀN cho người chơi (không phải hack): huỷ nghiên cứu đang chạy, huỷ hàng đợi sinh quân,
        # huỷ / mất công trình, hết ván. Báo cáo 8, 9 ngày 13/11: huỷ nghiên cứu được trả lại 1750 thực + 800 vàng,
        # hết ván game trả lại hàng đợi của nhiều người cùng lúc -> S2 báo oan.
        self.refund = collections.defaultdict(collections.deque)      # index -> deque[giờ game ms]
        self.prev_rs = {}                    # index -> set công nghệ đang nghiên cứu
        self.prev_queue = {}                 # index -> tổng số unit trong hàng đợi (lần đọc gần nhất)
        self.prev_bld = {}                   # index -> số công trình
        self.prev_t = None
        self.same_t = 0
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
              "t": int(t), "detail": detail, "count": 1, "v": RULES_V}
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
        self._track_refunds(snap, t)
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
        # TẮT từ v41 (13/11): mọi báo cáo L4 đều oan - lệnh đầu hàng mang số người khác xuất hiện cả trong trận bình thường
        # (nghi do game tự gửi thay người rớt mạng / thoát). Chưa có cách phân biệt nên không kết luận.
        if L4_ON and typ == C.RESIGN and len(data) > 1 and data[1] != sender:
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
            # Từ v42: chỉ kết luận khi lệnh CÓ TÁC DỤNG (công nghệ bắt đầu nghiên cứu / xong) dù chưa hề mở. Trước đây báo
            # ngay lúc thấy lệnh -> oan cho người bấm liên tục nút lên đời trong lúc chờ đủ điều kiện (báo cáo 1, 6, 10
            # ngày 12-13/11: lệnh tới sớm 0,2 s trước khi nút mở, game bỏ qua lệnh đó).
            if self.avail_hist.get(sender):                 # chỉ khi đã đọc được bảng công nghệ của người này
                self.pending.append({"kind": "tech", "rule": "L7", "sender": sender, "tech": tech, "t": t,
                                     "detail": f"nghiên cứu công nghệ {tech} chưa mở"})
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
            elif p["kind"] == "res":
                if final:
                    continue                             # hết ván ngay sau khi tăng: game trả lại hàng đợi -> bỏ
                if t - p["t"] < S2_WAIT_MS:
                    keep.append(p)
                elif not any(p["t0"] - S2_REFUND_MS <= x <= p["t"] + S2_REFUND_MS for x in self.refund.get(p["sender"], ())):
                    out.append(self._report(p["sender"], p["rule"], p["t"], p["detail"]))
            elif p["kind"] == "tech":
                v = self._tech_verdict(p["sender"], p["tech"], p["t"], t)
                if v is None and not final:
                    keep.append(p)
                elif v:
                    out.append(self._report(p["sender"], p["rule"], p["t"], p["detail"]))
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

    def _tech_verdict(self, index, tech, t0, now):
        """Lệnh nghiên cứu lúc t0: False = hợp lệ / vô hại, True = vi phạm, None = chưa đủ dữ liệu (chờ thêm).
        Hợp lệ: công nghệ 'có thể nghiên cứu' (hoặc đã đang nghiên cứu / đã xong) ở bất kì lúc nào trong
        [t0 - L7_AVAIL_MS, t0 + L7_OPEN_MS]. Vi phạm: không hề mở mà sau lệnh lại bắt đầu nghiên cứu / xong.
        Không mở và cũng không có tác dụng gì (game bỏ qua lệnh): vô hại."""
        hist = self.avail_hist.get(index)
        if not hist:
            return False
        started = False
        for tt, av, act in hist:
            if tt < t0 - L7_AVAIL_MS:
                continue
            if tt <= t0 + L7_OPEN_MS and (tech in av or (tt <= t0 and tech in act)):
                return False
            if tt > t0 and tech in act:
                started = True
        if now - t0 < L7_WAIT_MS:
            return None
        return started

    # ---- trạng thái người chơi ---------------------------------------------------------------
    def _track_players(self, snap, t):
        for p in snap.players:
            if p.index <= 0:
                continue
            av = getattr(p, "available", None)
            rs = getattr(p, "researching", None)
            if av is not None:
                s = frozenset(av)
                act = frozenset(rs or ()) | frozenset(getattr(p, "techs", None) or ())    # đang nghiên cứu / đã xong
                h = self.avail_hist[p.index]
                if not h or h[-1][1] != s or h[-1][2] != act or t - h[-1][0] > 2000:
                    h.append((t, s, act))
                while h and t - h[0][0] > L7_AVAIL_MS + L7_WAIT_MS + 2000:
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
                # chưa kết luận ngay: chờ S2_WAIT_MS xem có dấu hiệu hoàn tiền không (_resolve_pending)
                if (idx, "S2") in self.found:
                    self._report(idx, "S2", t, "")                       # đã kết luận trước đó: chỉ đếm thêm
                elif not any(p["kind"] == "res" and p["sender"] == idx and p["r"] == r for p in self.pending):
                    self.pending.append({"kind": "res", "rule": "S2", "sender": idx, "r": r, "t": t, "t0": t0,
                                         "detail": f"+{gain:,.0f} {RES_NAMES[r]} trong {(t - t0) / 1000:.1f} s"})
        return out

    def _track_refunds(self, snap, t):
        mark = lambda idx: self.refund[idx].append(t)                    # noqa: E731
        # đồng hồ game đứng >= 10 mẫu liền (0,4 s): tạm dừng / hết ván. Một hai mẫu trùng giờ là bình thường.
        self.same_t = self.same_t + 1 if self.prev_t is not None and t <= self.prev_t else 0
        stopped = self.same_t >= 10
        self.prev_t = t
        for p in snap.players:
            if p.index <= 0:
                continue
            if stopped or getattr(p, "ptype", 0) or getattr(p, "resigned", 0):
                mark(p.index)
            rs = getattr(p, "researching", None)
            if rs is not None:
                cur = set(rs)
                gone = self.prev_rs.get(p.index, set()) - cur - set(getattr(p, "techs", None) or ())
                if gone:                                                 # rời hàng nghiên cứu mà không xong = huỷ
                    mark(p.index)
                self.prev_rs[p.index] = cur
        units = None
        prod = getattr(snap, "production", None)
        if prod is not None:                                             # hàng đợi sinh quân: tụt >= 2 unit một lúc = huỷ
            units = {u.uid: u.owner_index for u in snap.units}
            tot = collections.Counter()
            for uid, v in prod.items():
                if not v:
                    continue
                o = units.get(uid, (self.owner.get(uid) or (0,))[0])
                tot[o] += sum(int(n) for _d, n in (v[0] or ())) + (1 if len(v) > 1 and v[1] is not None and v[1] >= 0 else 0)
            for idx in set(tot) | set(self.prev_queue):
                if idx > 0 and self.prev_queue.get(idx, 0) - tot.get(idx, 0) >= 2:
                    mark(idx)
            self.prev_queue = dict(tot)
        if self.n % REFUND_EVERY == 0:                                   # công trình mất đi (huỷ móng, xoá nhà, bị phá)
            bld = collections.Counter()
            for u in snap.units:
                if u.owner_index > 0 and getattr(u, "kind", 0) != UNIT_KIND_DOPPEL \
                        and getattr(u.udef, "utype", 0) == 80 and not getattr(u, "is_dead", False):
                    bld[u.owner_index] += 1
            for idx, n in self.prev_bld.items():
                if bld.get(idx, 0) < n:
                    mark(idx)
            self.prev_bld = dict(bld)
        for h in self.refund.values():
            while h and t - h[0] > 4 * S2_REFUND_MS + 2000:
                h.popleft()

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
