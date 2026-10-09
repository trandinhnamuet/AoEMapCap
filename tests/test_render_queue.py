"""Hai lượt dựng chồng nhau chạy tuần tự (xếp hàng); khi đang có trận tiến trình đoạn ghim vào E-core và trả lại khi
hết trận; abort_all huỷ cả lượt đang chờ; tiến độ báo qua progress(frac, text)."""
import os, sys, time, threading, subprocess
sys.path.insert(0, r"D:\Game\AoE-MapCap")
import psutil
from mapcap import offline
from mapcap.offline import render_raw, set_in_game, _in_game_cpus

P = lambda m: print(m, flush=True)
rec = r"D:\Game\AoE-MapCap\Video\_test\raw\test_tran1.aoerec"
if not os.path.isfile(rec):
    subprocess.run([sys.executable, r"D:\Game\AoE-MapCap\tests\test_raw.py"], check=True)
vdir = os.path.dirname(rec)
GD = r"D:\Game\AoE-HD"
n_cpu = os.cpu_count()
all_cpus = list(range(n_cpu))
P(f"CPU logic: {n_cpu}, E-core khi có trận: {_in_game_cpus()}")

# 1) xếp hàng: lượt 2 phải chờ lượt 1, cả hai xong; log lượt 2 có dòng "chờ lượt dựng trước"
logs = {1: [], 2: []}
prog = {1: [], 2: []}
order = []
def run(i):
    out = os.path.join(vdir, f"queue{i}.mp4")
    render_raw(rec, out, width=640, fps=25, game_dir=GD, workers=1, log=logs[i].append,
               progress=lambda f, s: prog[i].append(s))
    order.append(i)
t1 = threading.Thread(target=run, args=(1,)); t1.start(); time.sleep(0.5)
t2 = threading.Thread(target=run, args=(2,)); t2.start()
t1.join(120); t2.join(240)
assert order == [1, 2], order
assert any("chờ lượt dựng trước" in m for m in logs[2]) and not any("chờ lượt dựng trước" in m for m in logs[1])
assert prog[2] and prog[2][0].startswith("chờ lượt dựng trước"), prog[2][:2]
assert all(os.path.getsize(os.path.join(vdir, f"queue{i}.mp4")) > 0 for i in (1, 2))
P("xếp hàng OK")

# 2) affinity: đang có trận -> con ghim E-core; hết trận -> trả lại mọi lõi (kiểm tra trong lúc dựng)
if _in_game_cpus():
    set_in_game(True)
    res = {}
    def run3():
        try:
            render_raw(rec, os.path.join(vdir, "aff.mp4"), width=1280, fps=25, game_dir=GD, workers=1, log=lambda m: None)
            res["ok"] = True
        except Exception as e:  # noqa: BLE001
            res["err"] = str(e)
    t3 = threading.Thread(target=run3); t3.start()
    for _ in range(100):
        if offline._JOBS and offline._JOBS[0].get("affinity"):
            break
        time.sleep(0.1)
    job = offline._JOBS[0]
    pid = job["procs"][0].pid
    aff = psutil.Process(pid).cpu_affinity()
    P(f"affinity khi có trận: {aff}")
    assert aff == _in_game_cpus(), aff
    set_in_game(False)
    for _ in range(40):
        if job.get("affinity") == ():
            break
        time.sleep(0.1)
    aff2 = psutil.Process(pid).cpu_affinity() if psutil.pid_exists(pid) else all_cpus
    P(f"affinity hết trận: {aff2}")
    assert sorted(aff2) == all_cpus, aff2
    t3.join(180)
    assert res.get("ok"), res
    P("affinity OK")
else:
    P("máy < 12 luồng: bỏ qua kiểm tra affinity")

# 3) abort_all huỷ lượt đang chờ lẫn lượt đang chạy
res = {}
def run4(i):
    try:
        render_raw(rec, os.path.join(vdir, f"ab{i}.mp4"), width=640, fps=25, game_dir=GD, workers=1, log=lambda m: None)
        res[i] = "ok"
    except RuntimeError as e:
        res[i] = str(e)
t4 = threading.Thread(target=run4, args=(1,)); t4.start()
for _ in range(100):
    if offline._JOBS:
        break
    time.sleep(0.1)
t5 = threading.Thread(target=run4, args=(2,)); t5.start(); time.sleep(1.5)
n = offline.abort_all(log=P)
t4.join(30); t5.join(30)
P(f"abort_all: {n} lượt chạy, kết quả {res}")
assert n == 1 and "huỷ" in res.get(1, "") and "huỷ" in res.get(2, ""), res
assert not offline._JOBS and offline.active_renders() == 0
# sau abort_all vẫn dựng được lượt mới
render_raw(rec, os.path.join(vdir, "after.mp4"), width=640, fps=25, game_dir=GD, workers=1, log=lambda m: None)
assert os.path.getsize(os.path.join(vdir, "after.mp4")) > 0
for f in ("queue1", "queue2", "aff", "ab1", "ab2", "after"):
    try:
        os.remove(os.path.join(vdir, f + ".mp4"))
    except OSError:
        pass
P("OK test_render_queue")
