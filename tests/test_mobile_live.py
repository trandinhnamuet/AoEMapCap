"""Điện thoại tự dựng trận từ file ghi gốc và phát dần (app v7 + máy tính v38; mã app ở repo AoEMapCap-Mobile):
- máy chủ gửi file ghi gốc (api/rec) + gói dữ liệu game (api/gamedata), không phải chuyển trận trước (không tạo .aoeweb);
- trang (Edge ẩn, màn hình điện thoại, CPU chậm 4 lần) có hình và phát được khi trận mới dựng một phần (meta.partial),
  trạng thái ở phần đã dựng khớp bản máy tính chuyển; phát tới cuối phần đã dựng thì chờ rồi chạy tiếp;
- dựng xong: không còn partial, trạng thái mọi mẫu thử khớp bản máy tính chuyển, tự kiểm tra của trình xem qua;
- bộ dựng trên điện thoại hỏng (hoặc máy tính bản cũ): tự quay về cách cũ (máy tính chuyển), vẫn mở được trận;
- trận đang ghi: api/rec trả 409.

    python tests/test_mobile_live.py [file.aoerec] [cpu chậm mấy lần, mặc định 4]
"""
import json
import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
os.environ["AOEMAPCAP_TELEMETRY"] = "0"

from mapcap import mobile_server as MS  # noqa: E402
from mapcap import webexport as WE  # noqa: E402
import test_mobile_web as TW  # noqa: E402

GAME = r"D:\Game\AoE-HD"
SRC = sys.argv[1] if len(sys.argv) > 1 else TW.SRC
THR = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0
OUT = os.path.join(ROOT, "Video", "_test", "mobile_live")
GPU = ("--use-angle=d3d11", "--enable-gpu", "--ignore-gpu-blocklist")


def js_state(b, fi):
    return b.eval(f"""(async () => {{ const v = aoeViewer; await v.state.seek({fi}); const s = v.state;
      const out = []; for (let i = 0; i < s.cap; i++) if (s.valid[i]) out.push([s.uid[i], s.key[i]]);
      let vs = 0; for (let i = 0; i < s.vis.length; i++) vs = (vs + s.vis[i] * (i % 997 + 1)) % 1000000007;
      return [out, vs]; }})()""")


def same_state(b, meta, sec, fi, what):
    js = js_state(b, fi)
    units, vis = TW.web_state(meta, sec, fi)
    assert {u: k for u, k in js[0]} == {u: w[0] for u, w in units.items()}, f"{what}: mẫu {fi} unit khác bản máy tính"
    assert js[1] == TW.vis_sum(vis.tolist()), f"{what}: mẫu {fi} tầm nhìn khác bản máy tính"


def main():
    if MS.web_root() is None:
        print("bỏ qua: cần repo AoE-MapCap-Mobile cạnh repo này (hoặc AOEMAPCAP_MOBILE_WEB)")
        return
    shutil.rmtree(OUT, ignore_errors=True)
    raw, web, ref = os.path.join(OUT, "Raw"), os.path.join(OUT, "Web"), os.path.join(OUT, "ref")
    for d in (raw, web, ref):
        os.makedirs(d)
    src = os.path.join(raw, os.path.basename(SRC))
    shutil.copy2(SRC, src)
    old = time.time() - 7200
    os.utime(src, (old, old))
    name = os.path.basename(src)
    # bản máy tính chuyển (để so), để NGOÀI thư mục bộ đệm của máy chủ
    ref_web = os.path.join(ref, "ref.aoeweb")
    t0 = time.time()
    WE.export_match(src, ref_web, GAME)
    t_pc = time.time() - t0
    meta, sec = TW.read_web(ref_web)
    n = meta["frames"]
    print(f"trận {os.path.getsize(src) / 1e6:.1f} MB, {n} mẫu; máy tính chuyển {t_pc:.1f} s -> {os.path.getsize(ref_web) / 1e6:.1f} MB")

    srv, url = MS.serve(raw, GAME, port=0, token="t", cache=web, host="127.0.0.1", log=lambda m: None)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    # trận đang ghi (file vừa sửa): 409
    rec2 = os.path.join(raw, "dang_ghi.aoerec")
    shutil.copy(src, rec2)
    os.utime(rec2, None)
    try:
        urllib.request.urlopen(url + "api/rec?f=dang_ghi.aoerec")
        raise AssertionError("trận đang ghi phải bị từ chối")
    except urllib.error.HTTPError as e:
        assert e.code == 409, e.code
    os.remove(rec2)
    gd = urllib.request.urlopen(url + "api/gamedata").read()
    assert gd[:8] == b"AOEGD001" and os.path.exists(os.path.join(web, f"gamedata.v{WE.GAMEDATA_VERSION}.pack"))
    rec = urllib.request.urlopen(url + "api/rec?f=" + name).read()
    assert rec == open(src, "rb").read()
    print(f"máy chủ: api/rec gửi đúng file gốc, trận đang ghi 409, api/gamedata {len(gd) / 1e6:.2f} MB: OK")

    b = TW.Browser(915, 412, args=GPU)
    try:
        b.call("Emulation.setDeviceMetricsOverride", width=915, height=412, deviceScaleFactor=2.625, mobile=True)
        b.goto(url)
        b.wait("document.querySelectorAll('.match').length", timeout=120)
        b.eval("fetch('api/sprites').then(r => r.arrayBuffer()).then(b => b.byteLength)")   # gói hình tạo sẵn
        b.call("Emulation.setCPUThrottlingRate", rate=THR)
        t1 = time.time()
        b.goto(url + "?m=" + name)
        b.wait("window.aoeViewer && document.querySelector('#v-status').hidden", timeout=600)
        t_first = time.time() - t1
        st = b.eval("""({live: !!window.aoeLive, partial: !!aoeViewer.m.meta.partial, frames: aoeViewer.m.frames,
                         badge: document.querySelector('.v-build').textContent})""")
        assert st["live"], "phải dùng cách điện thoại tự dựng"
        b.eval("(() => { const v = aoeViewer; v.playing = false; v.setAutoCam(false, true); v.selectUnit(null); return 1; })()")
        assert not [f for f in os.listdir(web) if f.endswith(".aoeweb")], "máy tính không được chuyển trận"
        print(f"[CPU chậm {THR:g}x] có hình sau {t_first:.1f} s: đã dựng {st['frames']}/{n} mẫu, "
              f"partial={st['partial']}, nhãn '{st['badge']}'")
        assert st["partial"] and st["frames"] < n, "trận 20 phút phải có hình khi mới dựng một phần"
        assert "Đang dựng trận" in st["badge"], st
        assert t_first < t_pc * THR, "phải có hình sớm hơn nhiều so với chờ dựng xong"
        # phần đã dựng khớp bản máy tính
        same_state(b, meta, sec, min(st["frames"] - 1, 400), "đang dựng")
        # phát tới cuối phần đã dựng: chờ, có thêm dữ liệu thì chạy tiếp
        b.eval("(() => { const v = aoeViewer; v.seekR(v.m.duration - 0.5); v.setSpeed(6); v.playing = true; })()")
        b.wait("aoeViewer.r >= aoeViewer.m.duration - 0.01 || !aoeViewer.m.meta.partial", timeout=60)
        r0 = b.eval("aoeViewer.r")
        w = b.eval("({playing: aoeViewer.playing, partial: !!aoeViewer.m.meta.partial, badge: document.querySelector('.v-build').textContent})")
        if w["partial"]:
            assert w["playing"], "tới cuối phần đã dựng vẫn ở trạng thái phát (chờ)"
            b.wait(f"aoeViewer.r > {r0} + 1", timeout=300)
            print(f"phát tới cuối phần đã dựng: chờ ('{w['badge']}') rồi chạy tiếp khi có thêm dữ liệu: OK")
        b.eval("(() => { aoeViewer.playing = false; aoeViewer.setSpeed(2); })()")
        # dựng xong
        b.wait("document.body.dataset.built === '1' && !aoeViewer.m.meta.partial", timeout=900)
        t_all = time.time() - t1
        fin = b.eval("({frames: aoeViewer.m.frames, badge: document.querySelector('.v-build').hidden, total: aoeViewer.total, dur: aoeViewer.m.duration})")
        assert fin["frames"] == n and fin["badge"] and abs(fin["total"] - fin["dur"]) < 1e-6, fin
        for fi in (0, n // 5, n // 2, n - 300, n - 1):
            same_state(b, meta, sec, fi, "dựng xong")
        res = b.eval("aoeViewer.selftest()")
        assert max(res["seekMs"]) < 4000 and res["units"][-1] > 0, res
        assert not b.console, b.console[:3]
        b.screenshot(os.path.join(OUT, "xong.png"))
        print(f"[CPU chậm {THR:g}x] dựng xong sau {t_all:.1f} s (máy tính chuyển: {t_pc:.1f} s trên máy này); "
              f"{n} mẫu khớp bản máy tính ở 5 mẫu thử, tự kiểm tra qua: OK")

        # bộ dựng trên điện thoại hỏng -> cách cũ (máy tính chuyển)
        b.call("Emulation.setCPUThrottlingRate", rate=1)
        b.call("Page.addScriptToEvaluateOnNewDocument", source="window.OffscreenCanvas = undefined;")
        b.goto(url + "?m=" + name + "&x=1")
        b.wait("window.aoeViewer && document.querySelector('#v-status').hidden", timeout=600)
        st = b.eval("({live: !!window.aoeLive, partial: !!aoeViewer.m.meta.partial, frames: aoeViewer.m.frames})")
        assert not st["live"] and not st["partial"] and st["frames"] == n, st
        assert [f for f in os.listdir(web) if f.endswith(".aoeweb")], "cách cũ: máy tính chuyển trận"
        print("máy không dựng được tại chỗ: tự quay về cách cũ (máy tính chuyển), mở được trận: OK")
    finally:
        b.close()
        srv.shutdown()
    print("OK test_mobile_live")


if __name__ == "__main__":
    main()
