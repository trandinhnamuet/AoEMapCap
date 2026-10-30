"""Dữ liệu HUD cho trình xem điện thoại (.aoeweb từ phiên bản 2): bảng tỉ số, công nghệ, thông tin unit / công trình,
hàng đợi sinh, bảng lệnh. Cùng nguồn với HUD của trình xem máy tính (replay/viewer.py: _hud_model, _unit_info,
_command_panel); điện thoại chỉ tra bảng và hiển thị.

Trong .aoeweb:
- meta["hud"]: bảng tra
    defs   {def: [dat, utype, cls, máu tối đa, tên, icon]}       units {dat: [tên, icon, utype]}
    techs  {tid: [tên, icon, giây, nơi (dat công trình), nút, [[loại tài nguyên, lượng]]]} (công nghệ nghiên cứu được)
    stats  [bộ chỉ số (dict như rawrec, thêm "name")]           dstats {def: [[mẫu bắt đầu, chỉ số trong stats]]}
    done   {người chơi: [[tid, giờ game ms]]} (giờ xong, theo thứ tự)   civs {người chơi: tên nền văn minh}
    icons  {slp: tên phần}: SLP của interfac.drs (50729 công nghệ, 50730 unit, 50704..50707 công trình theo đời,
           50731 tài nguyên / chỉ số)          step: số mẫu giữa hai mẫu HUD
- phần "h<k>" (zlib, JSON) cho khối mẫu k (cùng khối với "c<k>"): danh sách mẫu HUD
    {"f": mẫu, "p": {người chơi: [đời, dân, dân số, chỗ trống, quân, giết, chết, phá nhà, vàng đã khai thác, cống nạp,
                                  thực, gỗ, vàng, đá, trạng thái (1 thắng, 2 thua, 3 đầu hàng)]},
     "r": {người chơi: [[tid, phần nghìn]]} (đang nghiên cứu),
     "a": {người chơi: [tid]} / "t": {người chơi: [[dat, nơi, nút]]} (có thể nghiên cứu / sinh; mẫu đầu khối và khi đổi),
     "q": [[uid công trình, dat đang sinh (-1 chờ), số trong hàng, dat đầu hàng, phần nghìn]],
     "u": [[uid, def, máu, trạng thái, loại tài nguyên, lượng, kind]] (mẫu đầu khối: toàn bộ; sau: hàng đổi), "x": [uid bỏ]}
- phần "sd" (zlib, JSON): như "u" cho vật thể tĩnh theo bản ghi tĩnh: [[mẫu đầu, 1 nếu toàn bộ, hàng[], bỏ[]]]
"""
import json
import math

import numpy as np

from . import offsets as O

HSTEP = 25                       # mẫu HUD mỗi 25 mẫu (~1 s giờ game); khối mẫu (250) chia hết
ICON_SLPS = (50729, 50730, 50704, 50705, 50706, 50707, 50731)
STATUS = {1: 1, 2: 2}


def _num(v):
    if v is None:
        return None
    v = float(v)
    if not math.isfinite(v):                   # JSON của trình duyệt không nhận NaN / Infinity
        return None
    return int(v) if v.is_integer() else round(v, 2)


def _clean(o):
    """Bộ chỉ số từ bộ nhớ game có thể có NaN (vd min_range): đổi thành None, tuple thành list."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, float):
        return _num(o)
    return o


class HudExport:
    def __init__(self, data, world, chunk):
        from replay.library import civ_name
        self.d, self.w, self.chunk = data, world, chunk
        self.dat = world.dat
        self.strings = getattr(world.resolver, "strings", None)
        self.research = getattr(self.dat, "research", None) or []
        self.chunks = []                 # [[mẫu HUD]]
        self.prev_u = {}                 # uid -> hàng chi tiết đã xuất trong khối hiện tại
        self.prev_a, self.prev_t = {}, {}
        self.dats = set()                # dat id cần tên (hàng đợi, bảng lệnh)
        self.civs = {p.index: civ_name(p.civ) for p in data.players
                     if p.index and (p.addr or p.pid) and p.civ is not None and p.civ > 0}

    # ---- tên ---------------------------------------------------------------------------
    def _str(self, sid):
        if sid and sid > 0 and self.strings is not None:
            v = self.strings.get(sid)
            if v:
                return v
        return None

    def unit_name(self, dat_id, lang=None):
        du = self.dat.units.get(dat_id)
        for sid in (lang, du.lang_name if du is not None else None):
            v = self._str(sid)
            if v:
                return v
        if du is not None and du.name:
            return du.name.replace("_", " ")
        return "?"

    def tech_label(self, r):
        return self._str(r.lang_name) or r.name

    # ---- mẫu ---------------------------------------------------------------------------
    @staticmethod
    def _detail(U):
        """Bảng chi tiết [n, 7] (float64, sắp theo uid, mỗi uid một hàng): uid, def, máu, trạng thái, loại tài nguyên,
        lượng, kind; máu / lượng làm tròn 0,1. So sánh bằng numpy: vật thể tĩnh có hàng chục nghìn hàng mỗi bản ghi
        (cây, mỏ), so từng hàng bằng Python mất vài phút một trận (v17)."""
        M = np.empty((len(U), 7), np.float64)
        for c, name in enumerate(("uid", "def", "hp", "status", "rtype", "ramount", "kind")):
            M[:, c] = U[name]
        M[:, 2] = np.round(M[:, 2], 1)
        M[:, 5] = np.round(M[:, 5], 1)
        M = M[np.argsort(M[:, 0], kind="stable")]
        if len(M) > 1:                             # uid trùng: giữ hàng sau cùng (như dict)
            M = M[np.append(M[1:, 0] != M[:-1, 0], True)]
        return M

    @staticmethod
    def _diff(prev, M):
        """(hàng của M mới / đổi so với prev, uid của prev không còn trong M)."""
        if prev is None or not len(prev):
            return M, np.empty(0)
        pu, mu = prev[:, 0], M[:, 0]
        k = np.minimum(np.searchsorted(pu, mu), len(pu) - 1)
        P = prev[k]
        same = (pu[k] == mu) & np.all((P == M) | (np.isnan(P) & np.isnan(M)), axis=1)
        return M[~same], pu[~np.isin(pu, mu)]

    @staticmethod
    def _rows(M):
        return [[int(u), int(df), _num(hp), int(s), int(rt), _num(ra), int(k)]
                for u, df, hp, s, rt, ra, k in M.tolist()]

    def frame(self, fi, st):
        """Gọi sau st.apply(p, fi) cho mọi mẫu; lấy mẫu HUD mỗi HSTEP mẫu."""
        if fi % HSTEP:
            return
        start = fi % self.chunk == 0
        if start:
            self.chunks.append([])
            self.prev_u, self.prev_a, self.prev_t = None, {}, {}
        d = self.d
        U = st.units()
        rows = self._detail(U)
        ch, gone = self._diff(self.prev_u, rows)
        u_out, gone = self._rows(ch), [int(u) for u in gone.tolist()]
        self.prev_u = rows
        players = d.players_at(st)
        vill = {}
        if len(U):
            _, defs = d.def_arrays()
            di = np.clip(U["def"], 0, defs["n"] - 1)
            alive = (U["kind"] != 25) & (U["status"] < 3) & (U["hp"] > 0)
            v = alive & (defs["utype"][di] == 70) & (defs["cls"][di] == 4)
            for o in U["owner"][v].tolist():
                vill[int(o)] = vill.get(int(o), 0) + 1
        P, R, A, T = {}, {}, {}, {}
        for p in players:
            if p.index == 0 or not (p.addr or p.pid):
                continue
            attrs = p.attrs or ()

            def a(i, attrs=attrs):
                return _num(attrs[i]) if i < len(attrs) else None
            kills, ratio = a(O.ATTR_KILLS), a(O.ATTR_KILL_RATIO)
            stt = 3 if p.ptype == 2 and p.resigned else STATUS.get(p.ptype, 0)
            tribute = a(O.ATTR_TRIBUTE_GIVEN)
            P[p.index] = [a(O.ATTR_AGE), vill.get(p.index, 0), a(O.ATTR_POP), a(O.ATTR_POP_ROOM), a(40), kills,
                          (kills - ratio) if kills is not None and ratio is not None else None, a(O.ATTR_RAZINGS),
                          a(O.ATTR_GOLD_COLLECTED), max(tribute, 0) if tribute is not None else None,
                          a(O.ATTR_FOOD), a(O.ATTR_WOOD), a(O.ATTR_GOLD), a(O.ATTR_STONE), stt]
            res = []
            for tid, sec in sorted((p.researching or {}).items()):
                if 0 <= tid < len(self.research) and self.research[tid].time > 0:
                    res.append([int(tid), int(1000 * max(0.0, min(1.0, sec / self.research[tid].time)))])
            if res:
                R[p.index] = res
            if p.available is not None:
                av = sorted(int(t) for t in p.available)
                if start or self.prev_a.get(p.index) != av:
                    A[p.index] = av
                self.prev_a[p.index] = av
            if p.trainable is not None:
                tr = sorted([int(x), int(y), int(z)] for x, y, z in p.trainable)
                if start or self.prev_t.get(p.index) != tr:
                    T[p.index] = tr
                    self.dats.update(x for x, _y, _z in tr)
                self.prev_t[p.index] = tr
        Q = []
        for uid, pv in st.prod.items():
            if not pv:
                continue
            q, making, _sec, frac = pv
            total = sum(c for _t, c in q)
            head = q[0][0] if q else -1
            Q.append([int(uid), int(making), int(total), int(head),
                      int(1000 * max(0.0, min(1.0, frac or 0.0))) if making >= 0 else 0])
            self.dats.update(x for x in (making, head) if x >= 0)
        s = {"f": fi, "p": P}
        for k, v in (("r", R), ("a", A), ("t", T), ("q", Q), ("u", u_out), ("x", gone)):
            if v:
                s[k] = v
        self.chunks[-1].append(s)

    # ---- kết thúc ----------------------------------------------------------------------
    def statics_detail(self):
        out = []
        prev = None
        for si in range(len(self.d.s_first)):
            _ver, S = self.d.load_statics(si)
            rows = self._detail(S)
            ch, gone = self._diff(prev, rows)
            out.append([int(self.d.s_first[si]), 1 if si == 0 else 0, self._rows(ch), [int(u) for u in gone.tolist()]])
            prev = rows
        return out

    def tables(self):
        d = self.d
        defs = {}
        for i, df in d.defs.items():
            du = self.dat.units.get(df.dat_id)
            defs[int(i)] = [int(df.dat_id), int(df.utype), int(df.cls), _num(df.hp_max or 0),
                            self.unit_name(df.dat_id), int(du.icon_id) if du is not None and du.icon_id is not None else -1]
        units = {}
        for dat_id in sorted(self.dats):
            du = self.dat.units.get(dat_id)
            units[int(dat_id)] = [self.unit_name(dat_id), int(du.icon_id) if du is not None and du.icon_id is not None
                                  else -1, int(du.type) if du is not None else -1]
        techs = {}
        for r in self.research:
            if r.researchable:
                techs[int(r.id)] = [self.tech_label(r), int(r.icon), int(r.time), int(r.location), int(r.button),
                                    [[int(t), int(a)] for t, a in r.costs if a > 0]]
        stats, sidx, dstats = [], {}, {}
        for di, (frames, lst) in d.stats.items():
            ent = []
            dat_id = d.defs[di].dat_id if di in d.defs else -1
            for f, s in zip(frames, lst):
                s = _clean(dict(s))
                s["name"] = self.unit_name(dat_id, s.get("lang"))
                key = json.dumps(s, sort_keys=True, allow_nan=False)
                k = sidx.get(key)
                if k is None:
                    k = sidx[key] = len(stats)
                    stats.append(json.loads(key))
                ent.append([int(f), k])
            dstats[int(di)] = ent
        done = {}
        for idx, tt in d.final_tech_times.items():
            lst = sorted((int(ms), int(t)) for t, ms in tt.items()
                         if 0 <= t < len(self.research) and self.research[t].researchable)
            done[int(idx)] = [[t, ms] for ms, t in lst]
        return {"step": HSTEP, "defs": defs, "units": units, "techs": techs, "stats": stats, "dstats": dstats,
                "done": done, "civs": self.civs}

    def icon_slps(self, game_dir):
        from .gamefiles import read_group
        files = read_group(game_dir, "interface")
        return {sid: files[("slp", sid)] for sid in ICON_SLPS if ("slp", sid) in files}
