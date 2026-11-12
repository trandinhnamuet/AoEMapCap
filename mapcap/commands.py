"""Đọc LỆNH của mọi người chơi trong trận (chỉ đọc bộ nhớ, như phần còn lại của tool).

AoE chạy lệnh theo lượt: lệnh của mọi máy (cả của mình) được xếp vào hàng đợi theo lượt của đối tượng liên lạc
(comm) rồi mới thực thi 1-3 lượt sau (~0,26-0,8 s). Đọc hàng đợi này đều đặn (CommandPoller, mặc định 50 lần/giây
ở luồng riêng) là thấy mọi lệnh trước khi game chạy chúng. Dịch ngược và đo trên trận bot ẩn 2026-11-11
(docs/08, docs/03): 2 030 id unit trong lệnh di chuyển đều thuộc đúng người gửi; ~8 byte/lệnh sau khi nén.

  comm = [0x585DF8]; lượt hiện tại = [comm+0x10C8]; số người chơi của máy này = [comm+0x10E0]
  hàng đợi q = [comm+0x14C4]; mảng ô = [q+0x114]; chỉ số ô lớn nhất đang dùng = [q+4]
  ô 0x1C byte: +0 khoá = 1000 * người gửi + số thứ tự, +4 lượt thực thi, +0xC con trỏ dữ liệu,
               +0x10 người gửi (= chỉ số người chơi trong thế giới), +0x14 kích thước
  Bản sao lệnh của chính máy này có kích thước dư 12 byte (rác) -> tính độ dài thật theo cấu trúc lệnh (cmd_len).

Một lệnh = (lượt thực thi, người gửi, số thứ tự, bytes). Cấu trúc các loại lệnh hay gặp (byte đầu = loại):
  0x00 ra lệnh (đi/đánh/làm): [4] id đích, [8] số unit n, [0xC] x f32, [0x10] y f32, [0x14] n id unit
  0x01 dừng: [1] n, [2] n id unit          0x04 tạo unit (cheat/màn chơi)   0x05 cộng chỉ số/tài nguyên (cheat)
  0x0B đầu hàng: [1] người chơi đầu hàng   0x64 ra quân: [4] id công trình, [8] người chơi, [0xA] dat id unit
  0x65 nghiên cứu: [4] id công trình, [8] người chơi, [0xA] id công nghệ
  0x66 xây: [1] n, [2] người chơi, [4] x, [8] y, [0xC] dat id công trình, [0x14] n id dân
  0x67 lệnh trò chơi: [1] kiểu (1 tốc độ, 4 xây tức thì = cheat STEROIDS, 6 mã cheat)
  0x6A xoá (phím Delete): [4] id vật thể — game KHÔNG kiểm tra vật thể thuộc ai
"""
import struct
import threading
import time

COMM_PTR = 0x585DF8
COMM_TURN = 0x10C8
COMM_MY_PLAYER = 0x10E0
COMM_QUEUE = 0x14C4
Q_MAX_INDEX = 0x4
Q_SLOTS = 0x114
SLOT_SIZE = 0x1C
LOCAL_EXTRA = 12               # bản sao lệnh của chính máy này dài hơn 12 byte
MAX_CMD = 1024                 # byte tối đa giữ lại mỗi lệnh (lệnh lạ / hỏng)

ORDER, STOP, CREATE, ADD_ATTR, RESIGN = 0x00, 0x01, 0x04, 0x05, 0x0B
TRAIN, RESEARCH, BUILD, GAME, DELETE = 0x64, 0x65, 0x66, 0x67, 0x6A
GAME_SPEED, GAME_INSTANT_BUILD, GAME_CHEAT = 1, 4, 6


def cmd_len(data):
    """Độ dài thật của lệnh theo cấu trúc (None = loại không biết, dùng kích thước trong hàng đợi)."""
    if not data:
        return None
    t = data[0]
    try:
        if t == ORDER:
            return 0x14 + 4 * data[8]
        if t == STOP:
            return 2 + 4 * data[1]
        if t in (TRAIN, RESEARCH):
            return 0x10
        if t == BUILD:
            return 0x14 + 4 * data[1]
        if t == DELETE:
            return 8
        if t == RESIGN:
            return 4
    except IndexError:
        return None
    return None


def trim(data, local):
    """Cắt phần rác cuối: theo cấu trúc nếu biết loại, không thì bỏ 12 byte dư của bản sao trên máy mình."""
    n = cmd_len(data)
    if n is None:
        n = len(data) - LOCAL_EXTRA if local and len(data) > LOCAL_EXTRA else len(data)
    return bytes(data[:max(0, min(n, len(data), MAX_CMD))])


def unit_ids(data):
    """[(vai trò, id vật thể)] mà lệnh tác động trực tiếp: 'unit' = unit được ra lệnh, 'building' = công trình
    ra quân / nghiên cứu, 'delete' = vật thể bị xoá. Id âm (unit đã chết lúc gửi) bị bỏ."""
    out = []
    if not data:
        return out
    t = data[0]
    try:
        if t == ORDER:
            n = data[8]
            out = [("unit", i) for i in struct.unpack_from(f"<{n}i", data, 0x14)]
        elif t == STOP:
            n = data[1]
            out = [("unit", i) for i in struct.unpack_from(f"<{n}i", data, 2)]
        elif t == BUILD:
            n = data[1]
            out = [("unit", i) for i in struct.unpack_from(f"<{n}i", data, 0x14)]
        elif t in (TRAIN, RESEARCH):
            out = [("building", struct.unpack_from("<i", data, 4)[0])]
        elif t == DELETE:
            out = [("delete", struct.unpack_from("<i", data, 4)[0])]
    except struct.error:
        return []
    return [(r, i) for r, i in out if i >= 0]


def describe(data):
    """Tên ngắn tiếng Việt của loại lệnh (để ghi nhật ký / chi tiết vi phạm)."""
    if not data:
        return "lệnh rỗng"
    t = data[0]
    names = {ORDER: "ra lệnh", STOP: "dừng", CREATE: "tạo unit", ADD_ATTR: "cộng tài nguyên/chỉ số", RESIGN: "đầu hàng",
             TRAIN: "ra quân", RESEARCH: "nghiên cứu", BUILD: "xây", DELETE: "xoá", 0x06: "cống nạp"}
    if t == GAME and len(data) > 1:
        return {GAME_SPEED: "đổi tốc độ", GAME_INSTANT_BUILD: "xây tức thì (cheat)",
                GAME_CHEAT: "mã cheat"}.get(data[1], f"lệnh trò chơi {data[1]}")
    return names.get(t, f"lệnh 0x{t:02X}")


class CommandPoller:
    """Luồng nền đọc hàng đợi lệnh `period` giây/lần; drain() trả các lệnh mới (mỗi lệnh đúng một lần).

    Mỗi vòng ~6 lần ReadProcessMemory (~2 µs/lần đo được): 50 vòng/giây ~ 0,06 % một nhân."""

    def __init__(self, mem, period=0.02, log=None):
        self.mem = mem
        self.period = period
        self.log = log or (lambda m: None)
        self.lock = threading.Lock()
        self.pending = []
        self.seen = {}                  # (lượt thực thi, khoá) -> lượt thực thi (dọn khi đã qua xa)
        self.turn = 0
        self.my_player = -1
        self.errors = 0
        self.total = 0
        self.stop_ev = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._loop, name="aoe-commands", daemon=True)
        self.thread.start()
        return self

    def stop(self):
        self.stop_ev.set()
        if self.thread is not None:
            self.thread.join(2)

    def _u32(self, a):
        return struct.unpack("<I", self.mem.read(a, 4))[0]

    def poll_once(self):
        """Một lượt đọc; trả số lệnh mới. Lỗi đọc (chưa vào trận, game đang thoát) -> 0."""
        try:
            comm = self._u32(COMM_PTR)
            if not comm:
                return 0
            head = self.mem.read(comm + COMM_TURN, 4)
            turn = struct.unpack("<I", head)[0]
            my = struct.unpack("<i", self.mem.read(comm + COMM_MY_PLAYER, 4))[0]
            q = self._u32(comm + COMM_QUEUE)
            if not q:
                return 0
            hi = self._u32(q + Q_MAX_INDEX)
            arr = self._u32(q + Q_SLOTS)
            if not arr or hi > 4000:
                return 0
            raw = self.mem.read(arr, (hi + 1) * SLOT_SIZE)
        except Exception:  # noqa: BLE001
            self.errors += 1
            return 0
        new = []
        for i in range(hi + 1):
            key, eturn, _b, ptr, sender, size = struct.unpack_from("<IIB3xIII", raw, i * SLOT_SIZE)
            if not size or not ptr or size > 4096 or (eturn, key) in self.seen:
                continue
            try:
                data = self.mem.read(ptr, size)
            except Exception:  # noqa: BLE001
                continue
            self.seen[(eturn, key)] = eturn
            new.append((int(eturn), int(sender), int(key % 1000), trim(data, sender == my)))
        if len(self.seen) > 4000:
            self.seen = {k: v for k, v in self.seen.items() if v >= turn - 20}
        if new:
            new.sort()
            with self.lock:
                self.pending.extend(new)
                self.turn = turn
                self.my_player = my
            self.total += len(new)
        else:
            self.turn = turn
            self.my_player = my
        return len(new)

    def _loop(self):
        while not self.stop_ev.is_set():
            self.poll_once()
            self.stop_ev.wait(self.period)

    def drain(self):
        """Lệnh mới từ lần drain trước (sắp theo lượt thực thi)."""
        with self.lock:
            out, self.pending = self.pending, []
        return out
