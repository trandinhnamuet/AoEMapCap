"""The recorder process dies at the end of a match (its "done" message lost, like the user's game 3 of 05/11): the
NEXT matches of the same session must still be recorded. Before the fix one such death set record_video = False and
6 of 9 games were never recorded. Everything game-side is faked; no game is needed.

    python tests/test_recorder_dies.py"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

import mapcap.engine as E  # noqa: E402

T0 = time.time()
# the game: match 1 from 1 s to 4 s, menu, match 2 from 5 s to 8 s, menu, match 3 from 9 s to 12 s; exits at 13 s
MATCHES = [(1, 4), (5, 8), (9, 12)]
GAME_END = 13


def now():
    return time.time() - T0


def match_at():
    for i, (a, b) in enumerate(MATCHES):
        if a <= now() < b:
            return i, (now() - a)
    return None, 0


class FakeProc:
    pid = 4242
    info = {"name": "EMPIRESX.EXE"}

    def exe(self):
        return r"C:\nowhere\EMPIRESX.EXE"


class FakeMem:
    def __init__(self, pid):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def alive(self):
        return now() < GAME_END


class FakeDoppels:
    def reset(self):
        pass

    def count(self):
        return 0


class FakeReader:
    def __init__(self, mem):
        self.doppels = FakeDoppels()

    def in_game(self):
        return match_at()[0] is not None

    def game_time_ms(self):
        return int(match_at()[1] * 1000) + 1000

    def snapshot(self):
        return object()


class FakeStatics:
    def __init__(self, *a, **k):
        pass

    def reset(self):
        pass

    def ensure_first(self, snap):
        pass

    def attach(self, snap):
        pass


started = []          # (match index, recorder)


class FakeRP:
    def __init__(self, die_early):
        self.t0 = time.time()
        self.die_early = die_early
        self.done_n = None
        self.error = None
        self.thread = None

    def alive(self):
        # the first recorder dies 1.5 s into its match without a "done" (lost message / crash)
        return not (self.die_early and time.time() - self.t0 > 1.5)


class FakeRecorder:
    def __init__(self, cfg, raw_dir, out_dir, label, log, gdir, pid, stills):
        self.label = label
        self.rp = None

    def start(self, snap):
        idx = match_at()[0]
        self.rp = FakeRP(die_early=(len(started) == 0))
        started.append((idx, self))

    def stop(self):
        return None

    def stat_line(self, span):
        return "stat"


E.find_game_process = lambda exclude=(): FakeProc() if now() < GAME_END else None
E.ProcessMemory = FakeMem
E.check_build = lambda pm: (1, 1)
E.GameReader = FakeReader
E.StaticObjects = FakeStatics
E.ProcRecorder = FakeRecorder
E.valid_game_dir = lambda d: False
E.resolve_game_dir = lambda *h: None
E.find_ffmpeg = lambda *a, **k: None

if __name__ == "__main__":
    cfg = E.Config()
    cfg.record_mode, cfg.reader_process, cfg.stills_interval, cfg.render_after = "raw", True, 0, False
    cfg.out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Video", "_test", "recdies")
    lines = []
    stop = threading.Event()
    eng = E.Engine(cfg, lambda m: lines.append(m), stop_event=stop)
    th = threading.Thread(target=eng.run, daemon=True)
    th.start()
    time.sleep(GAME_END + 1.5)
    stop.set()
    th.join(10)
    per_match = {}
    for idx, _r in started:
        per_match[idx] = per_match.get(idx, 0) + 1
    print("recorders started per match:", per_match)
    print("\n".join(l for l in lines if "tiến trình ghi" in l or "bỏ ghi" in l))
    assert per_match.get(1, 0) >= 1 and per_match.get(2, 0) >= 1, "matches after the recorder death must be recorded"
    assert per_match.get(0, 0) >= 2, "the match whose recorder died goes on in a new file"
    print("OK")
