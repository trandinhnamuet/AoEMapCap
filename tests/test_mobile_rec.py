"""Bộ chuyển trên điện thoại (repo AoEMapCap-Mobile: web/js/rec/*.js, chạy bằng Node qua tools/rec_build.mjs) cho ra đúng dữ liệu như bộ chuyển của máy tính
(mapcap/webexport.WebBuilder) từ cùng file ghi trận:
- mọi phần .aoeweb giống từng byte sau giải nén (khối mẫu, khoá hình, vật thể tĩnh, giờ, công trình đã thấy, chỉ số ô,
  icon), HUD + chi tiết tĩnh giống sau khi đọc JSON, meta giống (trừ vị trí các phần);
- ảnh địa hình (trước khi nén JPEG) giống từng điểm ảnh; trình xem đọc cả hai như nhau (tests/aoeweb_compare.py).

    python tests/test_mobile_rec.py [file.aoerec ...]
"""
import json
import os
import subprocess
import sys
import time
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
os.environ["AOEMAPCAP_TELEMETRY"] = "0"

GAME = r"D:\Game\AoE-HD"
# mã app điện thoại ở repo riêng (AoEMapCap-Mobile), mặc định nằm cạnh repo này
MOBILE = os.environ.get("AOEMAPCAP_MOBILE") or os.path.join(os.path.dirname(ROOT), "AoE-MapCap-Mobile")
SRCS = sys.argv[1:] or [os.path.join(ROOT, "Video", "_test", "expand_ui", "Raw", "2026-10-22_010104_tran1.aoerec")]
OUT = os.path.join(ROOT, "Video", "_test", "mobile_rec")


def python_build(src):
    from mapcap import webexport as WE
    from replay.library import match_info
    from replay.world import load_graphics
    t0 = time.time()
    b = None
    for tag, pl, _f in WE._records(src):
        if b is None:
            b = WE.WebBuilder(pl, load_graphics(GAME), GAME, info=match_info(src), keep_terrain=True)
            continue
        b.feed(tag, pl)
    data = b.finish(os.path.basename(src))
    return data, b.w.terrain_rgb, time.time() - t0


def main():
    import numpy as np

    import aoeweb_compare as C
    from mapcap import webexport as WE
    from replay.library import match_info
    os.makedirs(OUT, exist_ok=True)
    spr = os.path.join(OUT, "sprites.pack")
    gdp = os.path.join(OUT, "gamedata.pack")
    if not os.path.exists(spr):
        WE.export_sprites(GAME, spr)
    print("gói dữ liệu game:", WE.export_gamedata(GAME, gdp))
    for src in SRCS:
        name = os.path.splitext(os.path.basename(src))[0]
        info = os.path.join(OUT, name + ".info.json")
        json.dump(match_info(src), open(info, "w", encoding="utf-8"), ensure_ascii=False)
        py, rgb, t_py = python_build(src)
        js_out = os.path.join(OUT, name + ".js.aoeweb")
        raw = os.path.join(OUT, name + ".terrain.rgb")
        r = subprocess.run(["node", os.path.join(MOBILE, "tools", "rec_build.mjs"), src, spr, gdp, js_out, raw, info],
                           capture_output=True, text=True, encoding="utf-8", timeout=1800)
        if r.returncode:
            print(r.stdout, r.stderr)
            raise AssertionError("bộ chuyển JS lỗi")
        st = json.loads(r.stdout.strip().splitlines()[-1])
        js = open(js_out, "rb").read()
        # ảnh địa hình
        jr = np.frombuffer(open(raw, "rb").read(), np.uint8).reshape(rgb.shape)
        bad = int((jr != rgb).any(axis=2).sum())
        assert bad == 0, f"địa hình khác ở {bad} điểm ảnh"
        # từng phần (sau giải nén), trừ ảnh JPEG
        mp, sp = C.load(py)
        mj, sj = C.load(js)
        assert set(sp) == set(sj), set(sp) ^ set(sj)
        for k in sp:
            if k[0] == "t" and k[1:].isdigit():
                continue
            if k[0] == "i" and k[1:].isdigit():
                a, b = sp[k], sj[k]
            else:
                a, b = zlib.decompress(sp[k]), zlib.decompress(sj[k])
            if k.startswith("h") or k == "sd":
                a, b = json.loads(a), json.loads(b)
            if a != b:
                raise AssertionError(f"phần {k} khác")
        for k in set(mp) | set(mj):
            if k in ("sections",):
                continue
            if json.dumps(mp.get(k), sort_keys=True) != json.dumps(mj.get(k), sort_keys=True):
                raise AssertionError(f"meta.{k} khác: {str(mp.get(k))[:300]} | {str(mj.get(k))[:300]}")
        d = C.compare(py, js, skip_meta=("sections",))
        assert not d, d
        print(f"{name}: {mp['frames']} mẫu, {mp['keys']} khoá hình: điện thoại (Node) {st['seconds']} s "
              f"(địa hình {st['terrain_s']} s), máy tính {t_py:.1f} s; mọi phần giống từng byte, địa hình giống từng "
              f"điểm ảnh ({rgb.shape[1]}x{rgb.shape[0]}): OK")
    print("OK test_mobile_rec")


if __name__ == "__main__":
    main()
