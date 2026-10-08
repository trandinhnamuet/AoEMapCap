"""Thử ống nối tiến trình ghi: gắn vào chính python (không phải game) -> con phải báo lỗi gọn và thoát; cha không treo."""
import os, sys, time, multiprocessing
sys.path.insert(0, r"D:/Game/AoE-MapCap")

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from mapcap.engine import Config
    from mapcap.recproc import RecorderProcess
    msgs = []
    rp = RecorderProcess(os.getpid(), Config(), r"D:/Game/AoE-MapCap/Video/_test/rp_test.aoerec", r"D:/Game/AoE-HD", log=msgs.append)
    t0 = time.time(); rp.start()
    while rp.alive() and time.time() - t0 < 30:
        time.sleep(0.2)
    print("alive:", rp.alive(), "| error:", (rp.error or "")[:160].replace("\n", " "), "| logs:", msgs[:2])
    print("stop ->", rp.stop(5))
    assert not rp.alive() and rp.error, "con phải báo lỗi khi không phải game"
    print("OK")
