"""Logic thời điểm phát âm thanh đồ hoạ phải khớp hàm 0x4A6C20 của game (xem replay/audio.py)."""
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from replay.audio import Audio  # noqa: E402

g = SimpleNamespace(sound_id=7, angle_sounds=[[(3, 11), (8, 12)]] * 8, angle_count=8, frame_count=10, mirroring_mode=0)
fs = Audio.frame_sounds
assert fs(g, 0, 5, 5) == []                       # khung không đổi: không phát
assert fs(g, 0, 0, 1) == [7]                      # rời khung 0: tiếng chung
assert fs(g, 0, 1, 2) == []
assert fs(g, 0, 2, 4) == [11]                     # chạy qua khung 3
assert fs(g, 0, 3, 4) == [11]                     # pf <= kf < f (pf = 3)
assert fs(g, 0, 4, 9) == [12]
assert fs(g, 0, 9, 1) == [7]                      # quay vòng, f != 0: tiếng chung; kf 3, 8 không thuộc [9..) hay [..1)
assert fs(g, 0, 9, 0) == []                       # quay về đúng khung 0: chưa phát (phát khi rời khung 0)
assert fs(g, 0, 7, 4) == [7, 11, 12]              # quay vòng: kf >= 7 (8) hoặc kf < 4 (3)
g2 = SimpleNamespace(sound_id=-1, angle_sounds=[[(0, 5)]], angle_count=1, frame_count=4, mirroring_mode=0)
assert fs(g2, 3, 0, 1) == [5]                     # mục khung 0: phát khi rời khung 0
print("OK")
