"""Đọc bộ nhớ nhanh: gom địa chỉ thành khoảng lớn để giảm số lần ReadProcessMemory,
và nhớ chuỗi node danh sách liên kết giữa các lần đọc (tránh lần theo từng con trỏ)."""
import struct

from .memory import MemoryError_


class RegionMap:
    """Bản đồ các vùng bộ nhớ đã commit, đọc được của tiến trình game (VirtualQueryEx), làm mới định kỳ.
    Dùng để cắt các khoảng đọc gộp đúng ranh giới vùng -> không bao giờ đọc trúng trang chưa commit (tránh phải
    đọc lẻ từng bản ghi khi một khoảng lớn thất bại)."""

    REFRESH = 5.0

    def __init__(self, mem):
        self.mem = mem
        self.starts = []
        self.ends = []
        self.t = 0.0
        self.ok = hasattr(mem, "h") and mem.h

    _k32 = None
    _MBI = None

    @classmethod
    def _api(cls):
        if cls._k32 is None:
            import ctypes
            from ctypes import wintypes

            class MBI(ctypes.Structure):
                _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                            ("AllocationProtect", wintypes.DWORD), ("RegionSize", ctypes.c_size_t),
                            ("State", wintypes.DWORD), ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD)]
            k32 = ctypes.windll.kernel32
            k32.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(MBI), ctypes.c_size_t]
            k32.VirtualQueryEx.restype = ctypes.c_size_t
            cls._k32, cls._MBI = k32, MBI          # định nghĩa MỘT lần: argtypes gắn với đúng lớp MBI này
        return cls._k32, cls._MBI

    def refresh(self, force=False):
        import time
        if not self.ok or (not force and time.time() - self.t < self.REFRESH):
            return
        import ctypes
        k32, MBI = self._api()
        starts, ends = [], []
        addr = 0
        mbi = MBI()
        readable = {0x02, 0x04, 0x08, 0x20, 0x40, 0x80}
        while addr < 0x7FFF0000:
            if not k32.VirtualQueryEx(self.mem.h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
                break
            base = mbi.BaseAddress or 0
            if mbi.State == 0x1000 and (mbi.Protect & 0xFF) in readable and not (mbi.Protect & 0x100):
                if ends and ends[-1] == base:
                    ends[-1] = base + mbi.RegionSize      # nối vùng liền kề
                else:
                    starts.append(base)
                    ends.append(base + mbi.RegionSize)
            addr = base + mbi.RegionSize
        if starts:
            self.starts, self.ends = starts, ends
        self.t = time.time()

    def region_end(self, addr):
        """Kết thúc vùng đọc được chứa addr, hoặc None nếu không biết."""
        if not self.starts:
            return None
        import bisect
        i = bisect.bisect_right(self.starts, addr) - 1
        if i >= 0 and self.starts[i] <= addr < self.ends[i]:
            return self.ends[i]
        return None


class BulkReader:
    """Đọc N bản ghi cùng kích cỡ tại các địa chỉ rời rạc bằng ít lần gọi nhất.
    Các khoảng gộp được cắt theo ranh giới vùng commit (RegionMap) nên gần như không có khoảng thất bại."""

    SPAN_GAP = 0x20000        # hai địa chỉ cách nhau <= 128 KB thì chung một khoảng đệm
    SPAN_MAX_TOTAL = 96 << 20  # tổng bộ đệm tối đa mỗi mẫu

    def __init__(self, mem, gap=0x4000, max_span=0x400000, mode="gap"):
        self.mem = mem
        self.gap = gap
        self.max_span = max_span
        self.mode = mode          # "gap": gom theo khoảng cách địa chỉ; "page": gom theo trang 4 KB
        self.regions = RegionMap(mem)
        self.calls = 0            # thống kê: số lần ReadProcessMemory
        self.bytes = 0
        # bộ đệm khoảng (span cache): đầu mỗi mẫu đọc một lần các khoảng heap chứa mọi đối tượng đã hỏi ở mẫu
        # trước; read_many lấy từ bộ đệm, chỉ đọc lẻ địa chỉ mới. Số lượt gọi mỗi mẫu ~ số khoảng (vài chục).
        import threading
        self._lock = threading.Lock()
        self._spans = []          # [(start, end)]
        self._bufs = []           # [(start, end, bytes)] của mẫu hiện tại
        self._seen = set()        # địa chỉ (đã làm tròn 4 KB) hỏi trong mẫu này -> dựng khoảng cho mẫu sau
        self.frame_active = False

    def begin_frame(self):
        """Đọc lại các khoảng đệm cho mẫu mới (một lượt gọi mỗi khoảng)."""
        self.regions.refresh()
        bufs = []
        for start, end in self._spans:
            rend = self.regions.region_end(start)
            if rend is not None and end > rend:
                end = rend
            if end <= start:
                continue
            b = self.mem.try_read(start, end - start)
            self.calls += 1
            if b is not None:
                self.bytes += len(b)
                bufs.append((start, end, b))
        with self._lock:
            self._bufs = bufs
            self._seen = set()
            self.frame_active = True

    def end_frame(self):
        """Dựng lại danh sách khoảng từ các địa chỉ đã hỏi trong mẫu (dùng cho mẫu sau)."""
        with self._lock:
            pages = sorted(self._seen)
            self.frame_active = False
        spans = []
        total = 0
        i = 0
        n = len(pages)
        while i < n:
            start = pages[i] & ~0xFFF
            rend = self.regions.region_end(start)
            j = i
            while (j + 1 < n and pages[j + 1] - pages[j] <= self.SPAN_GAP
                   and (rend is None or pages[j + 1] + 0x1000 <= rend)
                   and pages[j + 1] + 0x1000 - start <= self.max_span):
                j += 1
            end = (pages[j] & ~0xFFF) + 0x1000
            if rend is not None and end > rend:
                end = rend
            if end > start and total + (end - start) <= self.SPAN_MAX_TOTAL:
                spans.append((start, end))
                total += end - start
            i = j + 1
        self._spans = spans

    def _from_cache(self, addr, size):
        import bisect
        bufs = self._bufs
        if not bufs:
            return None
        lo, hi = 0, len(bufs)
        while lo < hi:                      # tìm khoảng chứa addr (bufs sắp theo start)
            mid = (lo + hi) // 2
            if bufs[mid][0] <= addr:
                lo = mid + 1
            else:
                hi = mid
        k = lo - 1
        if k >= 0:
            start, end, b = bufs[k]
            if start <= addr and addr + size <= end:
                off = addr - start
                return b[off:off + size]
        return None

    def gather(self, addrs, size):
        """Trả về (mảng uint8 (N, size), mask ok) cho dãy địa chỉ (list/ndarray) — lấy từ bộ đệm khoảng bằng numpy,
        địa chỉ thiếu thì read_many rồi điền vào. Địa chỉ 0 -> hàng rỗng, ok=False."""
        import numpy as np
        a = np.asarray(addrs, dtype=np.uint64).reshape(-1)
        n = len(a)
        out = np.zeros((n, size), np.uint8)
        ok = np.zeros(n, bool)
        if n == 0:
            return out, ok
        valid = a != 0
        if self.frame_active and self._bufs:
            self._note(a[valid].tolist(), size)
            starts = np.array([b[0] for b in self._bufs], np.uint64)
            ends = np.array([b[1] for b in self._bufs], np.uint64)
            k = np.searchsorted(starts, a, side="right") - 1
            kk = np.clip(k, 0, len(starts) - 1)
            hit = valid & (k >= 0) & (a >= starts[kk]) & (a + np.uint64(size) <= ends[kk])
            for bi in np.unique(kk[hit]).tolist():
                sel = np.nonzero(hit & (kk == bi))[0]
                buf = np.frombuffer(self._bufs[bi][2], np.uint8)
                offs = (a[sel] - starts[bi]).astype(np.int64)
                idx = offs[:, None] + np.arange(size, dtype=np.int64)[None, :]
                out[sel] = buf[idx]
            ok[hit] = True
        miss = np.nonzero(valid & ~ok)[0]
        if len(miss):
            raws = self.read_many(a[miss].tolist(), size)
            for i in miss.tolist():
                b = raws.get(int(a[i]))
                if b is not None and len(b) >= size:
                    out[i] = np.frombuffer(b[:size], np.uint8)
                    ok[i] = True
        return out, ok

    def _note(self, addrs, size):
        with self._lock:
            for a in addrs:
                self._seen.add(a & ~0xFFF)
                if ((a + size - 1) & ~0xFFF) != (a & ~0xFFF):
                    self._seen.add((a + size - 1) & ~0xFFF)

    def _read_gap(self, addrs, size, out):
        n = len(addrs)
        i = 0
        while i < n:
            start = addrs[i]
            rend = self.regions.region_end(start)
            if rend is not None and start + size > rend:
                i += 1
                continue
            j = i
            while (j + 1 < n and addrs[j + 1] - addrs[j] <= self.gap
                   and addrs[j + 1] + size - start <= self.max_span
                   and (rend is None or addrs[j + 1] + size <= rend)):
                j += 1
            end = addrs[j] + size
            buf = self.mem.try_read(start, end - start)
            self.calls += 1
            if buf is None:
                self.regions.refresh(force=True)
                for k in range(i, j + 1):
                    b = self.mem.try_read(addrs[k], size)
                    self.calls += 1
                    if b is not None:
                        out[addrs[k]] = b
                        self.bytes += size
            else:
                self.bytes += len(buf)
                for k in range(i, j + 1):
                    off = addrs[k] - start
                    out[addrs[k]] = buf[off:off + size]
            i = j + 1
        return out

    PAGE = 0x1000
    JOIN_PAGES = 2            # nối hai cụm trang nếu cách nhau <= 2 trang trống (giảm số lần gọi, tốn ít byte)

    def read_many(self, addrs, size):
        """Trả về dict addr -> bytes (len == size); địa chỉ không đọc được thì vắng mặt.

        Gộp theo TRANG 4 KB mà các bản ghi chạm tới (không theo khoảng cách địa chỉ) nên số byte đọc tỉ lệ với số
        trang thật sự có dữ liệu, không phình theo khoảng trống giữa các đối tượng trên heap."""
        out = {}
        if not addrs:
            return out
        self.regions.refresh()
        addrs = sorted(set(addrs))
        if self.frame_active:
            self._note(addrs, size)
            miss = []
            for a in addrs:
                b = self._from_cache(a, size)
                if b is None:
                    miss.append(a)
                else:
                    out[a] = b
            if not miss:
                return out
            addrs = miss
        if self.mode == "gap":
            return self._read_gap(addrs, size, out)
        P = self.PAGE
        # các trang chạm tới
        pages = set()
        for a in addrs:
            pages.update(range(a >> 12, ((a + size - 1) >> 12) + 1))
        pages = sorted(pages)
        # cụm trang liên tiếp (cho phép lỗ nhỏ), cắt theo vùng commit và max_span
        runs = []
        i = 0
        n = len(pages)
        while i < n:
            j = i
            rstart = pages[i] * P
            rend_limit = self.regions.region_end(rstart)
            while (j + 1 < n and pages[j + 1] - pages[j] <= 1 + self.JOIN_PAGES
                   and (pages[j + 1] + 1) * P - rstart <= self.max_span
                   and (rend_limit is None or (pages[j + 1] + 1) * P <= rend_limit)):
                j += 1
            runs.append((rstart, (pages[j] + 1) * P))
            i = j + 1
        # đọc từng cụm
        bufs = []
        for rs, re_ in runs:
            buf = self.mem.try_read(rs, re_ - rs)
            self.calls += 1
            if buf is None:
                self.regions.refresh(force=True)
                bufs.append((rs, re_, None))
            else:
                self.bytes += len(buf)
                bufs.append((rs, re_, buf))
        # gán bản ghi vào cụm (hai danh sách đã sắp xếp)
        k = 0
        for a in addrs:
            while k < len(bufs) and bufs[k][1] <= a:
                k += 1
            if k >= len(bufs) or a < bufs[k][0] or a + size > bufs[k][1]:
                b = self.mem.try_read(a, size)
                self.calls += 1
                if b is not None:
                    out[a] = b
                    self.bytes += size
                continue
            rs, re_, buf = bufs[k]
            if buf is None:
                b = self.mem.try_read(a, size)
                self.calls += 1
                if b is not None:
                    out[a] = b
                    self.bytes += size
            else:
                off = a - rs
                out[a] = buf[off:off + size]
        return out


class ListWalker:
    """Duyệt danh sách liên kết (header -> [+4] node đầu; node: [0] unit, [4] next) với cache chuỗi node.

    Mỗi lần walk(): đọc gộp tất cả node đã biết, rồi đi theo chuỗi từ node đầu; node lạ mới đọc lẻ.
    """

    def __init__(self, mem, bulk: BulkReader):
        self.mem = mem
        self.bulk = bulk
        self.cache = {}          # header_ptr -> list node addr đã thấy lần trước

    def walk_many(self, headers, limit=60000):
        """headers: list (header_ptr, tag). Trả về list (unit_addr, tag), giữ thứ tự duyệt."""
        if not headers:
            return []
        firsts = {}
        hdr_addrs = [h + 4 for h, _ in headers if h]
        hb = self.bulk.read_many(hdr_addrs, 4)
        for h, _ in headers:
            if h and (h + 4) in hb:
                firsts[h] = struct.unpack("<I", hb[h + 4])[0]
        known_nodes = set()
        for h, _ in headers:
            known_nodes.update(self.cache.get(h, ()))
        node_bytes = self.bulk.read_many(list(known_nodes), 8) if known_nodes else {}
        result = []
        for h, tag in headers:
            node = firsts.get(h, 0)
            visited = []
            n = 0
            while node and n < limit:
                b = node_bytes.get(node)
                if b is None:
                    b = self.mem.try_read(node, 8)
                    if b is None:
                        break
                    node_bytes[node] = b
                unit, nxt = struct.unpack("<II", b)
                visited.append(node)
                if unit:
                    result.append((unit, tag))
                node = nxt
                n += 1
            self.cache[h] = visited
        return result
