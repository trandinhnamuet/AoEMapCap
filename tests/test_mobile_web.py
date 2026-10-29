"""Trình xem web cho điện thoại (mobile/web) + bộ chuyển .aoeweb (mapcap/webexport.py) trên trận thật:
1. chuyển trận, đọc lại file .aoeweb bằng Python theo đúng cách trình xem web đọc: unit (uid, vị trí) và tầm nhìn ở
   các mẫu ngẫu nhiên khớp tuyệt đối với trình xem máy tính (replay.data Cursor);
2. máy chủ mạng nhà (mapcap/mobile_server.py, chỉ 127.0.0.1) + Edge chạy ẩn (DevTools): trang danh sách trận, mở trận,
   trạng thái JS ở các mẫu ngẫu nhiên khớp Python, tự kiểm tra (tua, dựng, phát x8);
3. ảnh trình xem web so với bộ vẽ video máy tính ở cùng mẫu, cùng góc nhìn, zoom 1: sai khác trung bình nhỏ.

    python tests/test_mobile_web.py [file.aoerec]
Edge chạy ẩn bằng hồ sơ riêng trong thư mục tạm, tắt theo PID; không đụng game hay trình duyệt của người dùng.
"""
import base64
import json
import os
import random
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zlib

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

from mapcap import webexport as WE  # noqa: E402

SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "Video", "_test", "expand_ui", "Raw",
                                                         "2026-10-22_010104_tran1.aoerec")
GAME = r"D:\Game\AoE-HD"
OUT = os.path.join(ROOT, "Video", "_test", "mobile_web")
EDGE = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe"]


class Browser:
    """Edge / Chrome chạy ẩn, điều khiển qua DevTools (websocket-client). Hồ sơ riêng trong thư mục tạm."""

    def __init__(self, width=1280, height=720, args=()):
        import websocket
        exe = next((p for p in EDGE if os.path.exists(p)), None)
        if exe is None:
            raise RuntimeError("không thấy Edge / Chrome")
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()
        self.dir = tempfile.mkdtemp(prefix="aoeweb_cdp_")
        self.proc = subprocess.Popen(
            [exe, "--headless=new", f"--remote-debugging-port={self.port}", f"--user-data-dir={self.dir}",
             f"--window-size={width},{height}", "--no-first-run", "--no-default-browser-check",
             "--remote-allow-origins=*", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", *args],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ws_url = None
        for _ in range(100):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json"))
                page = next((t for t in tabs if t.get("type") == "page"), None)
                if page:
                    ws_url = page["webSocketDebuggerUrl"]
                    break
            except OSError:
                pass
            time.sleep(0.1)
        if not ws_url:
            self.close()
            raise RuntimeError("Edge không mở cổng DevTools")
        self.ws = websocket.create_connection(ws_url, timeout=180)
        self._id = 0
        self.console = []
        self.call("Runtime.enable")
        self.call("Page.enable")

    def call(self, method, **params):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("method") == "Runtime.exceptionThrown":
                self.console.append("EXC " + json.dumps(msg["params"]["exceptionDetails"])[:500])
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def eval(self, expr, await_promise=True):
        r = self.call("Runtime.evaluate", expression=expr, awaitPromise=await_promise, returnByValue=True)
        if "exceptionDetails" in r:
            raise RuntimeError(json.dumps(r["exceptionDetails"])[:800])
        return r.get("result", {}).get("value")

    def goto(self, url):
        self.call("Page.navigate", url=url)

    def wait(self, expr, timeout=120):
        t0 = time.time()
        while time.time() - t0 < timeout:
            v = self.eval(expr, await_promise=False)
            if v:
                return v
            time.sleep(0.25)
        raise TimeoutError(f"chờ quá {timeout}s: {expr} {self.console[-5:]}")

    def screenshot(self, path):
        r = self.call("Page.captureScreenshot", format="png")
        with open(path, "wb") as f:
            f.write(base64.b64decode(r["data"]))

    def close(self):
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass
        if self.proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True)
        shutil.rmtree(self.dir, ignore_errors=True)


def read_web(path):
    """Đọc .aoeweb như mobile/web/js/format.js."""
    b = open(path, "rb").read()
    assert b[:8] == WE.MAGIC
    n = struct.unpack_from("<I", b, 8)[0]
    meta = json.loads(b[12:12 + n])
    base = 12 + n

    def sec(name):
        o, ln = meta["sections"][name]
        return b[base + o:base + o + ln]
    return meta, sec


def _rows(buf, p):
    n = struct.unpack_from("<I", buf, p)[0]
    p += 4
    out = {}
    for name in WE.ROW_DT.names:
        dt = WE.ROW_DT[name]
        out[name] = np.frombuffer(buf, dt, n, p)
        p += n * dt.itemsize
    return out, p


def web_state(meta, sec, fi):
    """Unit {uid: (khoá, x, y, z, chủ, cờ)} và tầm nhìn tại mẫu fi."""
    C = meta["chunk"]
    ci = fi // C
    buf = zlib.decompress(sec(f"c{ci}"))
    nf = struct.unpack_from("<I", buf, 0)[0]
    p = 4
    units, vis = {}, None
    for k in range(nf):
        full = buf[p]
        p += 1
        R, p = _rows(buf, p)
        nr = struct.unpack_from("<I", buf, p)[0]
        p += 4
        rem = np.frombuffer(buf, "<i4", nr, p)
        p += 4 * nr
        nv = struct.unpack_from("<I", buf, p)[0]
        p += 4
        if full:
            units = {}
            vis = np.frombuffer(buf, "<u4", nv, p).copy()
            p += 4 * nv
        else:
            ix = np.frombuffer(buf, "<u4", nv, p)
            p += 4 * nv
            vis[ix] = np.frombuffer(buf, "<u4", nv, p)
            p += 4 * nv
        for u in rem.tolist():
            units.pop(u, None)
        for i in range(len(R["uid"])):
            units[int(R["uid"][i])] = tuple(R[nm][i].item() for nm in WE.ROW_DT.names[1:])
        if ci * C + k == fi:
            return units, vis
    raise AssertionError("thiếu mẫu")


def vis_sum(vals):
    s = 0
    for i, v in enumerate(vals):
        s = (s + v * (i % 997 + 1)) % 1000000007
    return s


def main():
    if not os.path.exists(SRC) or not os.path.isdir(GAME):
        print("bỏ qua: cần trận thật và thư mục game:", SRC, GAME)
        return
    raw = os.path.join(OUT, "Raw")
    web = os.path.join(OUT, "Web")
    os.makedirs(raw, exist_ok=True)
    os.makedirs(web, exist_ok=True)
    src = os.path.join(raw, os.path.basename(SRC))
    if not os.path.exists(src):
        shutil.copy2(SRC, src)
    out = os.path.join(web, os.path.splitext(os.path.basename(src))[0] + f".v{WE.WEB_VERSION}.aoeweb")
    if not os.path.exists(out) or os.path.getmtime(out) < os.path.getmtime(WE.__file__):
        print("chuyển:", WE.export_match(src, out, GAME))
    meta, sec = read_web(out)

    # 1. khớp tuyệt đối với trình xem máy tính
    from replay.data import Cursor, ReplayData
    d = ReplayData(src)
    d._index()
    cur = Cursor(d)
    rnd = random.Random(7)
    frames = [0] + sorted(rnd.sample(range(1, d.n_frames - 1), 6)) + [d.n_frames - 1]
    for fi in frames:
        units, vis = web_state(meta, sec, fi)
        cur.seek(fi)
        U = cur.state.units()
        assert set(units) == set(U["uid"].tolist()), f"mẫu {fi}: tập unit khác"
        for u in U[::max(1, len(U) // 50)]:
            w = units[int(u["uid"])]
            assert (w[1], w[2], w[3]) == (u["x"].item(), u["y"].item(), u["z"].item()), (fi, u, w)
        assert np.array_equal(vis, cur.state.vis.ravel()), f"mẫu {fi}: tầm nhìn khác"
    print(f"đọc lại .aoeweb khớp trình xem máy tính ở {len(frames)} mẫu: OK")

    # 2. trang web trong Edge chạy ẩn, máy chủ chỉ nghe 127.0.0.1
    from mapcap import mobile_server as MS
    old = os.path.getmtime(out) - 3600
    os.utime(src, (old, old))                       # trận cũ hơn file đã chuyển, không phải "đang ghi"
    srv, url = MS.serve(raw, GAME, port=0, token="t", cache=web, host="127.0.0.1", log=print)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    name = os.path.basename(src)
    b = Browser(1280, 720)
    try:
        b.goto(url)
        assert b.wait("document.querySelectorAll('.match').length", timeout=60) >= 1
        b.screenshot(os.path.join(OUT, "list.png"))
        b.goto(url + "?m=" + name)
        b.wait("window.aoeViewer && document.querySelector('#v-status').hidden", timeout=120)
        for fi in frames[1:5]:
            js = b.eval(f"""(async () => {{ const v = aoeViewer; await v.state.seek({fi}); const s = v.state;
              const out = []; for (let i = 0; i < s.cap; i++) if (s.valid[i]) out.push([s.uid[i], s.key[i]]);
              let vs = 0; for (let i = 0; i < s.vis.length; i++) vs = (vs + s.vis[i] * (i % 997 + 1)) % 1000000007;
              return [out, vs]; }})()""")
            units, vis = web_state(meta, sec, fi)
            assert {u: k for u, k in js[0]} == {u: w[0] for u, w in units.items()}, f"JS mẫu {fi}: unit khác"
            assert js[1] == vis_sum(vis.tolist()), f"JS mẫu {fi}: tầm nhìn khác"
        print("trạng thái trong trình duyệt khớp Python: OK")
        res = b.eval("aoeViewer.selftest()")
        print("tự kiểm tra (SwiftShader, không GPU):", res)
        assert max(res["seekMs"]) < 2000 and res["units"][-1] > 0

        # 3. ảnh so với bộ vẽ video
        fi = d.n_frames // 2
        b.eval("document.querySelector('.v-top').style.display='none';"
               "document.querySelector('.v-bottom').style.display='none'; 1")
        r = b.eval(f"""(async () => {{ const v = aoeViewer; v.playing = false; v.setPersp(v.m.meta.rec_team);
          v.r = v.m.r[{fi}]; await v.state.seek({fi}); v.dirtyUnits = v.dirtyFog = true;
          const s = v.state; let sx = 0, sy = 0, n = 0;
          const me = v.m.meta.players.find(p => p.name === v.m.meta.info.recorder).index;
          for (let i = 0; i < s.cap; i++) if (s.valid[i] && (s.flags[i] & 2) && s.owner[i] === me) {{
            sx += s.x[i]; sy += s.y[i]; n++; }}
          const [ax, ay] = v._anchor(sx / n, sy / n, 0);
          v.cam.x = Math.round(ax); v.cam.y = Math.round(ay); v.cam.zoom = 1; v.needDraw = true;
          return [v.cam.x, v.cam.y, v.canvas.width, v.canvas.height]; }})()""")
        time.sleep(1.0)
        b.wait("!aoeViewer.dirtyUnits && !aoeViewer.dirtyStatics && !aoeViewer.dirtyFog", timeout=60)
        time.sleep(0.5)
        b.screenshot(os.path.join(OUT, "web.png"))
        assert not [c for c in b.console if c.startswith("EXC")], b.console
    finally:
        b.close()
        srv.shutdown()
    from PIL import Image

    from mapcap.rawrec import RawReader
    from mapcap.video_render import VideoRenderer
    from replay.world import World, load_graphics
    dat, store, pal = load_graphics(GAME)
    w = World(d.header, dat, store, pal)
    vr = VideoRenderer(dat, store, pal, width=w.full_w, fog_dim=WE.FOG_DIM, outline_alpha=0.35)
    snap = next(sn for i, sn in enumerate(RawReader(src).frames()) if i == fi)
    img = vr.render(snap, overlay=False)
    cx, cy, cw, ch = r
    x0, y0 = int(cx - cw / 2), int(cy - ch / 2)
    vid = img.crop((x0, y0, x0 + cw, y0 + ch))
    webimg = Image.open(os.path.join(OUT, "web.png")).convert("RGB").crop((0, 0, cw, ch))
    both = Image.new("RGB", (cw * 2 + 8, ch), (255, 0, 255))
    both.paste(vid, (0, 0))
    both.paste(webimg, (cw + 8, 0))
    both.save(os.path.join(OUT, "compare.png"))
    diff = np.abs(np.asarray(vid, np.int16) - np.asarray(webimg, np.int16)).mean()
    print(f"ảnh web so với bộ vẽ video (mẫu {fi}, zoom 1): sai khác trung bình {diff:.1f} / 255 "
          f"-> {os.path.join(OUT, 'compare.png')}")
    assert diff < 15, diff
    d.close()
    print("OK test_mobile_web")


if __name__ == "__main__":
    main()
