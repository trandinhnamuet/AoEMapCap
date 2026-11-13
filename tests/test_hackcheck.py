"""Bộ luật phát hiện hack (mapcap/hackcheck.py) trên mẫu giả lập: mỗi luật một ca vi phạm và các ca hợp lệ dễ
báo nhầm (cống nạp, AI do máy chủ điều khiển, unit vừa bị dụ, unit vừa mở, phòng bật cheat).

    python tests/test_hackcheck.py
"""
import os
import struct
import sys
from types import SimpleNamespace as NS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

from mapcap import commands as C  # noqa: E402
from mapcap.hackcheck import Detector, cheats_allowed  # noqa: E402


def unit(uid, owner, dat=83, kind=0):
    return NS(uid=uid, owner_index=owner, kind=kind, udef=NS(dat_id=dat), is_dead=False)


def player(i, res=(200, 200, 150, 0), avail=(), train=((83, 109, 1),)):
    return NS(index=i, name=f"Nguoi{i}", attrs=tuple(float(x) for x in res) + (4.0,), available=frozenset(avail),
              researching={}, trainable=frozenset(train))


def order(ids, target=-1):
    return struct.pack("<BxxxiB3xff", C.ORDER, target, len(ids), 10.0, 10.0) + struct.pack(f"<{len(ids)}i", *ids)


def delete(uid):
    return struct.pack("<Bxxxi", C.DELETE, uid)


def train(building, dat, pl=1):
    return struct.pack("<BxxxiBxhi", C.TRAIN, building, pl, dat, -1)


def research(building, tech, pl=1):
    return struct.pack("<BxxxiBxhi", C.RESEARCH, building, pl, tech, -1)


def resign(who):
    return bytes([C.RESIGN, who, who, 0])


class World:
    """Trận giả: P1, P2 là người (tự gửi lệnh), P3 là máy (AI, không bao giờ tự gửi lệnh), Gaia = 0."""

    def __init__(self, match=None):
        self.t = 0
        self.units = [unit(100, 1), unit(101, 1), unit(150, 1, dat=109), unit(200, 2), unit(201, 2), unit(250, 2, dat=109),
                      unit(300, 3), unit(350, 3, dat=109), unit(900, 0, dat=65)]          # 900 = linh dương (Gaia)
        self.players = [NS(index=0, name="Gaia", attrs=(), available=None, researching=None, trainable=None),
                        player(1, avail=(10, 11)), player(2), player(3)]
        self.det = Detector(match if match is not None else {"cheats": 0})

    def step(self, cmds=(), dt=40):
        self.t += dt
        snap = NS(time_ms=self.t, players=self.players, units=list(self.units), cmds=list(cmds), match=None)
        return self.det.feed(snap)

    def run(self, ms, cmds_every=None):
        out = []
        for _ in range(int(ms / 40)):
            out += self.step(cmds_every() if cmds_every else ())
        return out


def rules(evs):
    return sorted({(e["player"], e["rule"]) for e in evs})


def humans():
    """P1 và P2 gửi lệnh bình thường (để Detector biết họ là người thật)."""
    return [(0, 1, 2, order([100])), (0, 2, 2, order([200]))]


def test_clean_game():
    w = World()
    w.step(humans())
    evs = w.run(30_000, lambda: [(0, 1, 2, order([100, 101], target=200)), (0, 2, 2, order([200, 201], target=900))])
    evs += w.step([(0, 1, 3, train(150, 83)), (0, 1, 4, research(150, 10)), (0, 1, 5, delete(101))])
    # P3 là máy: máy chủ (P1) gửi lệnh thay cho unit của P3 -> không phải hack
    evs += w.step([(0, 1, 6, order([300])), (0, 1, 7, train(350, 83, pl=3)), (0, 1, 8, resign(3))])
    evs += w.run(10_000) + w.det.finish()
    assert not evs, evs
    print("trận sạch (ra lệnh quân mình, đánh địch, xoá nhà mình, AI do máy chủ điều khiển): không báo: OK")


def test_l1_l2_l3_l4():
    w = World()
    w.step(humans())
    evs = w.step([(0, 2, 3, order([900], target=100))])                 # P2 lùa linh dương (Gaia)
    assert rules(evs) == [(2, "L1")], evs
    evs = w.step([(0, 2, 4, order([100, 101], target=900))])            # P2 điều khiển quân P1
    evs += w.step([(0, 2, 5, delete(150))])                             # P2 xoá nhà P1
    evs += w.step([(0, 2, 6, resign(1))])                               # P2 bắt P1 đầu hàng
    assert rules(evs) == [(2, "L2"), (2, "L3")], evs      # L4 đã tắt (báo oan, v41)
    e = w.det.summary()
    assert [x["rule"] for x in e] == ["L1", "L2", "L3"] and all(x["name"] == "Nguoi2" for x in e), e
    print("L1 lùa thú, L2 điều khiển quân người khác, L3 xoá nhà người khác, L4 ép đầu hàng: OK")


def test_victim_unknown_until_human():
    """Chủ vật thể chưa từng gửi lệnh: chờ; khi người đó gửi lệnh (người thật) mới báo, giữ giờ vi phạm gốc."""
    w = World()
    w.step([(0, 2, 2, order([200]))])                                   # chỉ P2 đã gửi lệnh
    evs = w.step([(0, 2, 3, delete(100))])
    t0 = w.t
    assert not evs
    w.run(2000)
    evs = w.step([(0, 1, 2, order([100]))])                             # P1 hoá ra là người
    assert rules(evs) == [(2, "L3")] and evs[0]["t"] == t0, evs
    print("chủ vật thể chưa rõ người/máy: chờ, rõ là người thì báo đúng giờ vi phạm: OK")


def test_conversion_grace():
    w = World()
    w.step(humans())
    w.units[3] = unit(200, 1)                                           # unit 200 của P2 vừa bị P1 dụ
    w.run(400)
    evs = w.step([(0, 2, 3, order([200]))])                             # P2 vẫn bấm unit cũ
    assert not evs, evs
    w.run(6000)
    evs = w.step([(0, 2, 4, order([200]))])
    assert rules(evs) == [(2, "L2")], evs
    print("unit vừa bị dụ: lệnh của chủ cũ trong 5 giây không tính, sau đó tính: OK")


def test_l5_cheat_commands():
    w = World()
    w.step(humans())
    evs = w.step([(0, 1, 3, bytes([C.GAME, C.GAME_CHEAT, 1, 0, 0x14, 0])), (0, 2, 3, bytes([C.ADD_ATTR, 2, 0, 0]))])
    assert rules(evs) == [(1, "L5"), (2, "L5")], evs
    w2 = World({"cheats": 1})
    w2.step(humans())
    assert not w2.step([(0, 1, 3, bytes([C.GAME, C.GAME_CHEAT, 1, 0, 0x14, 0]))])
    assert cheats_allowed({"raw": bytes([0, 0, 1])}) and not cheats_allowed({"raw": bytes(3)})
    print("L5 lệnh cheat khi phòng không bật cheat (phòng bật cheat thì không báo): OK")


def test_l7_locked():
    w = World()
    w.step(humans())
    evs = w.step([(0, 1, 3, research(150, 99))])                        # công nghệ 99 chưa mở
    assert rules(evs) == [(1, "L7")], evs
    w.step([(0, 1, 4, train(150, 75))])                                 # unit 75 chưa mở ...
    assert not w.run(3000)
    w.players[1].trainable = frozenset({(83, 109, 1), (75, 12, 1)})     # ... 3 s sau mới thấy mở: hợp lệ
    assert not w.run(5000)
    w.step([(0, 2, 3, train(250, 37, pl=2))])                           # P2 ra ngựa chưa mở, không bao giờ mở
    evs = w.run(7000)
    assert rules(evs) == [(2, "L7")], evs
    print("L7 nghiên cứu / ra quân thứ chưa mở (unit vừa mở trong vài giây thì không báo): OK")


def test_resources():
    w = World()
    w.step(humans())
    w.run(12_000)
    w.players[1].attrs = (1200.0, 200.0, 150.0, 0.0, 4.0)               # +1000 thực trong 1 giây, không ai trả
    evs = w.run(1200)
    assert rules(evs) == [(1, "S2")], evs
    # cống nạp: P2 nhận 1000 vàng, P1 bị trừ 1250 (kèm phí) -> không báo
    w.players[2].attrs = (200.0, 200.0, 150.0, 1000.0, 4.0)
    w.players[1].attrs = (1200.0, 200.0, 150.0, -1250.0, 4.0)
    assert not w.run(1200)
    w.players[2].attrs = (2_000_000.0, 200.0, 150.0, 1000.0, 4.0)
    evs = w.run(200)
    assert (2, "S1") in rules(evs), evs
    w2 = World()
    w2.step(humans())
    w2.players[1].attrs = (5000.0, 5000.0, 5000.0, 5000.0, 4.0)         # 10 giây đầu: tài nguyên khởi điểm
    assert not w2.run(3000)
    print("S1 tài nguyên > 1.000.000, S2 tăng >= 1000/giây (cống nạp và tài nguyên khởi điểm không báo): OK")


def test_cheat_units():
    w = World()
    w.step(humans())
    w.units.append(unit(500, 2, dat=372))                               # xe BIGDADDY
    w.units.append(unit(501, 0, dat=274))                               # của Gaia: bỏ qua
    evs = w.run(2000)
    assert rules(evs) == [(2, "S3")] and "BIGDADDY" in evs[0]["detail"], evs
    print("S3 unit chỉ cheat mới có: OK")


def test_commands_trim():
    o = order([5, 6])
    assert C.trim(o + b"rac rac rac!", True) == o and C.cmd_len(o) == len(o)
    assert C.trim(bytes([0x6C]) + bytes(23), True) == bytes([0x6C]) + bytes(11)      # loại lạ: bỏ 12 byte dư
    assert C.unit_ids(order([5, -1, 7])) == [("unit", 5), ("unit", 7)]
    assert C.unit_ids(delete(9)) == [("delete", 9)]
    print("cắt rác cuối lệnh / đọc id trong lệnh: OK")


if __name__ == "__main__":
    test_commands_trim()
    test_clean_game()
    test_l1_l2_l3_l4()
    test_victim_unknown_until_human()
    test_conversion_grace()
    test_l5_cheat_commands()
    test_l7_locked()
    test_resources()
    test_cheat_units()
    print("OK test_hackcheck")
