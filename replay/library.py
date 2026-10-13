"""Thư viện trận: đọc nhanh thông tin tóm tắt của các file .aoerec (người ghi, quân, kết quả, ngày, 4v4/1v1, thể thức)
để hiện danh sách chọn trận. Kết quả lưu đệm trong `_matches.json` cạnh các file (theo tên + cỡ + giờ sửa).

File ghi từ 2026-10-09 có thiết lập ván (header 'match'), trạng thái thắng/thua và bản ghi tổng kết 'E' ở cuối; file
cũ chỉ suy ra được đội (từ tầm nhìn chia sẻ) và thể thức (cùng một quân hay không), kết quả = không rõ.
"""
import json
import os
import struct
import time

from mapcap.rawrec import FORMAT_VERSION, MAGIC, file_version, read_end, read_header

CACHE_NAME = "_matches.json"
CACHE_VERSION = 5                 # 3: tên quân tiếng Anh; 4: đội có người bỏ cuộc đầu tiên là đội thua

CIV_NAMES = {1: "Egyptian", 2: "Greek", 3: "Babylonian", 4: "Assyrian", 5: "Minoan", 6: "Hittite", 7: "Phoenician",
             8: "Sumerian", 9: "Persian", 10: "Shang", 11: "Yamato", 12: "Choson", 13: "Roman", 14: "Carthaginian",
             15: "Palmyran", 16: "Macedonian"}          # tên tiếng Anh như cộng đồng vẫn gọi (theo yêu cầu 2026-10-09)
# tên tiếng Anh đúng như language.dll của game (chuỗi 10602..10610, 10611..10616)
MAP_TYPES = ["Small Islands", "Large Islands", "Coastal", "Inland", "Highland", "Continental", "Mediterranean",
             "Hill Country", "Narrows"]
_MAP_TYPES_VI = ["Quần đảo nhỏ", "Quần đảo lớn", "Bờ biển", "Nội địa", "Đất cao", "Lục địa", "Địa Trung Hải",
             "Đồi cao", "Cửa biển hẹp"]
MAP_SIZES = ["Tiny", "Small", "Medium", "Large", "Huge", "Gigantic"]
RESULT_TEXT = {1: "Thắng", 2: "Thua"}


def civ_name(c):
    return CIV_NAMES.get(int(c), f"#{c}") if c is not None and c >= 0 else "?"


def real_player_rows(hdr):
    """[(index, tên, civ, mask thấy)] của người chơi thật (bỏ Gaia và ô trống)."""
    out = []
    civs = hdr.get("civs") or []
    for p in hdr.get("players", []):
        idx, addr, pid, name, mm, exp_mask, vis_mask, ptype = p[:8]
        if idx == 0 or not (addr or pid):
            continue
        out.append((idx, name, civs[idx] if idx < len(civs) else -1, vis_mask))
    return out


def teams_from_header(hdr):
    """List đội (mỗi đội là list index người chơi). Ưu tiên đội trong thiết lập ván (file mới); không có thì gom người
    chơi dùng chung tầm nhìn (mask 'đang thấy' giao nhau); không chia sẻ -> mỗi người một đội."""
    rows = real_player_rows(hdr)
    match = hdr.get("match") or {}
    st = match.get("teams")
    if st and len(st) >= max((r[0] for r in rows), default=0):
        groups = {}
        for idx, *_ in rows:
            t = st[idx - 1]
            groups.setdefault(("t", t) if t > 0 else ("p", idx), []).append(idx)
        return sorted(groups.values(), key=lambda g: g[0])
    parent = {r[0]: r[0] for r in rows}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a in rows:
        for b in rows:
            if a[0] < b[0] and (a[3] & b[3]):
                parent[find(b[0])] = find(a[0])
    groups = {}
    for r in rows:
        groups.setdefault(find(r[0]), []).append(r[0])
    return sorted(groups.values(), key=lambda g: g[0])


def team_format(teams):
    """'4v4', '1v1', '2v2v2', 'FFA 8' (mỗi người một đội, trên 2 người)."""
    sizes = [len(t) for t in teams]
    if not sizes:
        return "?"
    if len(sizes) > 2 and max(sizes) == 1:
        return f"FFA {len(sizes)}"
    return "v".join(str(s) for s in sorted(sizes, reverse=True))


def civ_mode(civs):
    """Thể thức: mọi người cùng một quân -> tên quân (vd 'Shang'); khác nhau -> 'Random'."""
    cs = [c for c in civs if c is not None and c > 0]
    if not cs:
        return "?"
    if len(set(cs)) == 1:
        return civ_name(cs[0])
    return "Random"


def _scan_last_frame(path):
    """File chưa có bản ghi tổng kết: lướt đầu các bản ghi (không giải nén) tới mẫu cuối, giải nén mẫu đó."""
    import pickle
    import zlib
    last = None
    n_frames = 0
    size = os.path.getsize(path)
    with open(path, "rb", buffering=1 << 16) as f:
        f.seek(len(MAGIC))
        pos = len(MAGIC)
        while pos + 5 <= size:
            head = f.read(5)
            if len(head) < 5:
                break
            n = struct.unpack("<I", head[1:])[0]
            if pos + 5 + n > size:
                break
            if head[:1] in (b"F", b"B"):
                last = (head[:1], pos + 5, n)
                if head[:1] == b"F":
                    n_frames += 1
            pos += 5 + n
            f.seek(pos)
        if last is None:
            return None, 0
        f.seek(last[1])
        try:
            raw = f.read(last[2])
            if last[0] == b"B":                     # định dạng 3: mẫu cuối nằm trong khối cuối
                from mapcap.rawrec import decode_block, iter_records
                lastf = [p for t, p in decode_block(raw) if t == b"F"]
                n_frames = sum(1 for t, _p in iter_records(path) if t == b"F")
                return (lastf[-1] if lastf else None), n_frames
            return pickle.loads(zlib.decompress(raw)), n_frames
        except Exception:  # noqa: BLE001
            return None, n_frames


def first_out(path):
    """Người đầu tiên bị game đánh dấu thua trong trận: (index, time_ms, đã đầu hàng) hoặc None.
    Đầu hàng = trạng thái 2 kèm cờ đầu hàng; rớt mạng/bị loại = trạng thái 2 không có cờ.
    Định dạng 3: lấy ngay từ 'E'.pstat_log; file cũ / ghi dở: đọc 'pstat' của các mẫu."""
    end = read_end(path)
    if end is not None and "pstat_log" in end:
        events = [(int(t), int(i), (int(s), int(r))) for t, i, s, r in end["pstat_log"]]
    else:
        events = None
    if events is not None:
        by_t = {}
        for t, i, v in events:
            by_t.setdefault(t, []).append((i, v))
        for t in sorted(by_t):
            outs = [(i, v) for i, v in by_t[t] if v[0] == 2]
            if outs:
                outs.sort(key=lambda o: -int(o[1][1]))
                i, v = outs[0]
                return i, t, bool(v[1])
        return None
    from mapcap.rawrec import iter_records
    try:
        for tag, pl in iter_records(path):
            if tag != b"F":
                continue
            ps = pl.get("pstat")
            if not ps:
                continue
            outs = [(int(i), v) for i, v in ps.items() if v and v[0] == 2]
            if outs:
                # cùng một mẫu: ưu tiên người đầu hàng (người kia thường bị game xử thua theo)
                outs.sort(key=lambda o: -int(o[1][1]))
                i, v = outs[0]
                return i, int(pl.get("t", 0)), bool(v[1])
    except Exception:  # noqa: BLE001
        return None
    return None


def match_info(path):
    """Thông tin tóm tắt (dict JSON được) của một file .aoerec."""
    hdr = read_header(path)
    if hdr is None:
        raise ValueError("không đọc được header")
    end = read_end(path)
    rows = real_player_rows(hdr)
    teams = teams_from_header(hdr)
    rec = int(hdr.get("cur_player_index", -1))
    names = {r[0]: r[1] for r in rows}
    civs = {r[0]: r[2] for r in rows}
    team_of = {i: k for k, t in enumerate(teams) for i in t}
    match = hdr.get("match") or {}
    status = {}
    reason = None
    if end is not None:
        t_end = end.get("t", 0)
        n_frames = end.get("frames", 0)
        status = {int(k): tuple(v) for k, v in (end.get("status") or {}).items()}
        reason = end.get("reason")
        game_over = end.get("game_over", 0)
    elif file_version(hdr) > FORMAT_VERSION:
        n_frames, t_end, game_over = 0, 0, None
    else:
        last, n_frames = _scan_last_frame(path)
        t_end = last.get("t", 0) if last else 0
        game_over = None
    out = None
    if file_version(hdr) > FORMAT_VERSION:
        result = "Cần bản mới"                    # file của bản mới hơn: không đoán nội dung, chỉ báo cập nhật
    elif "format" in hdr:
        # luật (người dùng, 2026-10-10): đội có người đầu tiên đầu hàng / rớt mạng là đội thua, kể cả khi
        # ván chưa kết thúc chính thức lúc dừng ghi
        try:
            out = first_out(path)
        except OSError:
            out = None
        st, res = status.get(rec, (0, 0))
        lose_team = team_of.get(out[0]) if out is not None else None
        if lose_team is not None and team_of.get(rec) == lose_team:
            result = "Đầu hàng" if (out[0] == rec and out[2]) or (st == 2 and res) else "Thua"
        elif lose_team is not None and len(teams) == 2 and rec in team_of:
            result = "Thắng"
        elif st == 1:
            result = "Thắng"
        elif st == 2:
            result = "Đầu hàng" if res else "Thua"
        elif end is None:
            result = "Ghi dở"
        else:
            result = "Chưa phân thắng bại"
    else:
        result = "Không rõ"                       # file trước 2026-10-09 chưa ghi trạng thái thắng/thua
    mt = match.get("map_type")
    ms = match.get("map_size")
    map_kind = MAP_TYPES[mt] if isinstance(mt, int) and 0 <= mt < len(MAP_TYPES) else ""
    if isinstance(ms, int) and 0 <= ms < len(MAP_SIZES):
        map_kind = (map_kind + " - " if map_kind else "") + MAP_SIZES[ms]
    if not map_kind:
        map_kind = f"{hdr.get('map_w')}x{hdr.get('map_h')}"
    players = []
    lose_team = team_of.get(out[0]) if out is not None else None
    for k, t in enumerate(teams):
        for i in t:
            st, res = status.get(i, (0, 0))
            if lose_team is not None and st == 0:          # ván dừng trước khi game tự kết luận
                if k == lose_team:
                    st = 2
                elif len(teams) == 2:
                    st = 1
            players.append({"index": i, "name": names.get(i, "?"), "civ": civ_name(civs.get(i)), "team": k + 1,
                            "status": st, "resigned": res})
    return {
        "file": os.path.basename(path),
        "created": hdr.get("created") or os.path.getmtime(path),
        "recorder": names.get(rec, "?"),
        "recorder_civ": civ_name(civs.get(rec)),
        "recorder_team": team_of.get(rec, 0) + 1,
        "result": result,
        "format": team_format(teams),
        "civ_mode": civ_mode(list(civs.values())),
        "map": map_kind,
        "duration_ms": int(t_end),
        "frames": int(n_frames),
        "players": players,
        "reason": reason,
        "game_over": game_over,
        "new_format": "format" in hdr,
        "first_out": None if out is None else {"index": out[0], "name": names.get(out[0], "?"), "t_ms": out[1],
                                                "kind": "đầu hàng" if out[2] else "rớt mạng / bị loại"},
    }


class Library:
    """Danh sách trận của một thư mục, có đệm."""

    def __init__(self, folder):
        self.folder = folder
        self.cache_path = os.path.join(folder, CACHE_NAME)
        self.cache = {}
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("version") == CACHE_VERSION:
                self.cache = data.get("files", {})
        except (OSError, ValueError):
            pass
        self._dirty = False

    def files(self):
        try:
            names = [n for n in os.listdir(self.folder) if n.lower().endswith(".aoerec")]
        except OSError:
            return []
        return sorted((os.path.join(self.folder, n) for n in names), key=os.path.getmtime, reverse=True)

    def cached(self, path):
        e = self.cache.get(os.path.basename(path))
        if e is None:
            return None
        try:
            st = os.stat(path)
        except OSError:
            return None
        if e.get("size") != st.st_size or abs(e.get("mtime", 0) - st.st_mtime) > 1e-3:
            return None
        return e.get("info")

    def info(self, path):
        """Thông tin của file (từ đệm nếu còn đúng); lỗi -> dict có 'error'."""
        c = self.cached(path)
        if c is not None:
            return c
        try:
            info = match_info(path)
        except Exception as e:  # noqa: BLE001
            info = {"file": os.path.basename(path), "error": str(e), "created": os.path.getmtime(path)}
        try:
            st = os.stat(path)
            # file đang ghi dở (sửa trong 10 giây gần đây) thì không đệm
            if time.time() - st.st_mtime > 10:
                self.cache[os.path.basename(path)] = {"size": st.st_size, "mtime": st.st_mtime, "info": info}
                self._dirty = True
        except OSError:
            pass
        return info

    def save(self):
        if not self._dirty:
            return
        live = {os.path.basename(p) for p in self.files()}
        files = {k: v for k, v in self.cache.items() if k in live}
        try:
            tmp = self.cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"version": CACHE_VERSION, "files": files}, f, ensure_ascii=False)
            os.replace(tmp, self.cache_path)
            self._dirty = False
        except OSError:
            pass


def fmt_duration(ms):
    s = max(0, int(ms) // 1000)
    return f"{s // 3600}:{(s // 60) % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"
