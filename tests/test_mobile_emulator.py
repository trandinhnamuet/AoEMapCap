"""App Android thật (APK debug, repo AoE-MapCap-Mobile) trên máy ảo Android (AVD aoe35): ghép đôi với máy chủ điện thoại
của máy tính qua mạng nhà (10.0.2.2), mở một trận CHƯA lưu -> app tải file ghi gốc, tự dựng trong luồng nền của WebView,
có hình khi mới dựng một phần, dựng xong thì lưu vào bộ nhớ app; trạng thái khớp bản máy tính chuyển; mở lại từ bộ nhớ
khi máy tính tắt.

    python tests/test_mobile_emulator.py <trận.aoerec> [apk debug]
Không có apk: build bằng Gradle (gradle.bat -p android assembleDebug). KHÔNG chạy khi người dùng đang chơi game.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
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
MOBILE = os.environ.get("AOEMAPCAP_MOBILE") or os.path.join(os.path.dirname(ROOT), "AoE-MapCap-Mobile")
SDK = os.path.join(os.environ["LOCALAPPDATA"], "Android", "Sdk")
ADB = os.path.join(SDK, "platform-tools", "adb.exe")
EMU = os.path.join(SDK, "emulator", "emulator.exe")
GRADLE = os.path.join(os.environ["USERPROFILE"], ".gradle-dist", "gradle-8.11.1", "bin", "gradle.bat")
PKG = "io.github.trandinhnamuet.aoemapcap"
OUT = os.path.join(ROOT, "Video", "_test", "mobile_emulator")
AVD = "aoe35"


def sh(*a, timeout=120, check=True):
    r = subprocess.run(a, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(a[:4])}: {r.stdout[-400:]} {r.stderr[-400:]}")
    return r.stdout.strip()


def adb(*a, **k):
    return sh(ADB, *a, **k)


def playing():
    out = subprocess.run(["tasklist"], capture_output=True, text=True).stdout.lower()
    return any(x in out for x in ("empiresx", "aoesolo", "league of legends"))


class Page:
    """WebView của app qua DevTools (adb forward)."""

    def __init__(self):
        import websocket
        pid = adb("shell", "pidof", PKG)
        socks = adb("shell", "cat /proc/net/unix")
        name = next(m.group(1) for m in re.finditer(r"@(webview_devtools_remote_\d+)", socks) if m.group(1).endswith("_" + pid))
        adb("forward", "tcp:9333", "localabstract:" + name)
        tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json"))
        page = next(t for t in tabs if t.get("type") == "page")
        self.ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=300, suppress_origin=True)
        self._id = 0
        self.errors = []
        self.call("Runtime.enable")

    def call(self, method, **params):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("method") == "Runtime.exceptionThrown":
                self.errors.append(json.dumps(msg["params"]["exceptionDetails"])[:400])
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def eval(self, expr, await_promise=True):
        r = self.call("Runtime.evaluate", expression=expr, awaitPromise=await_promise, returnByValue=True)
        if "exceptionDetails" in r:
            raise RuntimeError(json.dumps(r["exceptionDetails"])[:600])
        return r.get("result", {}).get("value")

    def wait(self, expr, timeout=120):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                if self.eval(expr, await_promise=False):
                    return True
            except RuntimeError:
                pass
            time.sleep(0.3)
        raise TimeoutError(f"chờ quá {timeout}s: {expr} | {self.eval('document.title', False)!r} {self.errors[-2:]}")

    def close(self):
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass
        adb("forward", "--remove", "tcp:9333", check=False)


def main():
    if playing():
        print("bỏ qua: người dùng đang chơi game")
        return 2
    src0 = sys.argv[1]
    apk = sys.argv[2] if len(sys.argv) > 2 else None
    shutil.rmtree(OUT, ignore_errors=True)
    raw, web, ref = (os.path.join(OUT, x) for x in ("Raw", "Web", "ref"))
    for d in (raw, web, ref):
        os.makedirs(d)
    src = os.path.join(raw, os.path.basename(src0))
    shutil.copy2(src0, src)
    os.utime(src, (time.time() - 7200,) * 2)
    name = os.path.basename(src)
    if apk is None:
        env = dict(os.environ, ANDROID_HOME=SDK)
        t0 = time.time()
        r = subprocess.run([GRADLE, "-p", os.path.join(MOBILE, "android"), "assembleDebug", "-PversionCode=7", "--no-daemon", "-q"],
                           capture_output=True, text=True, env=env, timeout=1200)
        assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
        apk = os.path.join(MOBILE, "android", "app", "build", "outputs", "apk", "debug", "app-debug.apk")
        print(f"build APK debug: {time.time() - t0:.0f} s, {os.path.getsize(apk) / 1e6:.2f} MB")
    ref_web = os.path.join(ref, "ref.aoeweb")
    WE.export_match(src, ref_web, GAME)
    meta, sec = TW.read_web(ref_web)
    n = meta["frames"]

    emu = None
    if "emulator-" not in adb("devices"):
        emu = subprocess.Popen([EMU, "-avd", AVD, "-no-window", "-no-audio", "-no-boot-anim", "-gpu", "host", "-no-snapshot-save"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        adb("wait-for-device", timeout=300)
        t0 = time.time()
        while adb("shell", "getprop", "sys.boot_completed", check=False) != "1":
            assert time.time() - t0 < 400, "máy ảo không khởi động xong"
            time.sleep(2)
        print("máy ảo:", adb("shell", "getprop", "ro.build.version.release"), "| WebView:",
              (re.search(r"versionName=(\S+)", adb("shell", "dumpsys", "package", "com.google.android.webview", check=False)) or [None, "?"])[1])
        adb("uninstall", PKG, check=False)
        adb("install", "-r", apk, timeout=300)

        srv, url = MS.serve(raw, GAME, port=0, token="t", cache=web, host="127.0.0.1", log=lambda m: None)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]
        urllib.request.urlopen(url + "api/sprites").read()          # gói hình + gói dữ liệu game tạo sẵn
        urllib.request.urlopen(url + "api/gamedata").read()
        adb("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", f"aoemapcap://pair?a=10.0.2.2:{port}/t", PKG)
        time.sleep(4)
        p = Page()
        try:
            p.wait("document.querySelectorAll('.match').length > 0", timeout=120)
            print("ghép đôi qua mạng nhà (10.0.2.2), danh sách trận hiện: OK")
            t1 = time.time()
            p.eval("document.querySelector('.match').click()", await_promise=False)
            time.sleep(1.5)
            p.close()
            p = Page()                                           # trang ?m= là trang mới
            phases, last = [], None                              # các bước trước khi có hình: (giây, thông báo)
            while True:
                assert time.time() - t1 < 600, "quá 600 s chưa có hình"
                try:                                             # trang đang chuyển: kết nối DevTools có thể rớt, nối lại
                    if p.eval("!!(window.aoeViewer && document.querySelector('#v-status').hidden)", await_promise=False):
                        break
                    txt = p.eval("document.querySelector('#v-status').textContent", await_promise=False) or ""
                except Exception:  # noqa: BLE001
                    p.close()
                    time.sleep(1)
                    p = Page()
                    continue
                txt = re.sub(r"[\d,.]+ ?(%|MB)", "…", txt)
                if txt != last:
                    phases.append((round(time.time() - t1, 1), txt))
                    last = txt
                time.sleep(0.2)
            t_first = time.time() - t1
            print("các bước trước khi có hình:", phases)
            print("thời gian trong app (ms từ lúc mở trận):", p.eval("window.aoeTimes"))
            st = p.eval("({live: !!window.aoeLive, partial: !!aoeViewer.m.meta.partial, frames: aoeViewer.m.frames, "
                        "badge: document.querySelector('.v-build').textContent, canvas: [aoeViewer.canvas.width, aoeViewer.canvas.height]})")
            assert st["live"], "app phải tự dựng trận"
            assert not [f for f in os.listdir(web) if f.endswith(".aoeweb")], "máy tính không được chuyển trận"
            print(f"có hình sau {t_first:.1f} s (gồm tải gói hình 22,6 MB + gói dữ liệu game + file ghi qua mạng máy ảo): "
                  f"đã dựng {st['frames']}/{n} mẫu, partial={st['partial']}, nhãn '{st['badge']}', khung vẽ {st['canvas']}")
            p.eval("(() => { aoeViewer.setSpeed(4); aoeViewer.playing = true; })()")
            time.sleep(6)
            fm = p.eval("(() => { const a = aoeViewer.frameMs.slice(-200).sort((x, y) => x - y); return {n: a.length, "
                        "p50: +a[a.length >> 1].toFixed(1), p95: +a[Math.floor(a.length * .95)].toFixed(1), r: +aoeViewer.r.toFixed(1)}; })()")
            print("phát x4 trong lúc đang dựng: thời gian dựng khung (ms)", fm)
            p.eval("(() => { aoeViewer.playing = false; })()")
            p.wait("document.body.dataset.built === '1' && !aoeViewer.m.meta.partial", timeout=1500)
            t_all = time.time() - t1
            for fi in (0, n // 4, n // 2, n - 1):
                js = p.eval(f"""(async () => {{ const v = aoeViewer; await v.state.seek({fi}); const s = v.state;
                  const out = []; for (let i = 0; i < s.cap; i++) if (s.valid[i]) out.push([s.uid[i], s.key[i]]);
                  let vs = 0; for (let i = 0; i < s.vis.length; i++) vs = (vs + s.vis[i] * (i % 997 + 1)) % 1000000007;
                  return [out, vs]; }})()""")
                units, vis = TW.web_state(meta, sec, fi)
                assert {u: k for u, k in js[0]} == {u: w[0] for u, w in units.items()}, f"mẫu {fi}: unit khác bản máy tính"
                assert js[1] == TW.vis_sum(vis.tolist()), f"mẫu {fi}: tầm nhìn khác"
            keys = p.eval("caches.open('aoe-web-1').then(c => c.keys()).then(k => k.map(r => new URL(r.url).pathname))")
            enc = urllib.request.quote(name, safe="")
            assert {"/s/sprites", "/s/gamedata1", "/m/" + enc, "/i/" + enc} <= set(keys), keys
            assert not p.errors, p.errors[:3]
            print("thời gian trong app (ms):", p.eval("window.aoeTimes"))
            print(f"dựng xong sau {t_all:.1f} s; {n} mẫu khớp bản máy tính ở 4 mẫu thử; đã lưu trận + gói dữ liệu game trong app: OK")
            # máy tính tắt: mở lại từ bộ nhớ app
            srv.shutdown()
            srv.server_close()
            p.eval("location.reload()", await_promise=False)
            time.sleep(2)
            p.close()
            p = Page()
            p.wait("window.aoeViewer && document.querySelector('#v-status').hidden", timeout=300)
            st = p.eval("({live: !!window.aoeLive, partial: !!aoeViewer.m.meta.partial, frames: aoeViewer.m.frames})")
            assert not st["live"] and not st["partial"] and st["frames"] == n, st
            print("máy tính tắt: mở lại trận từ bộ nhớ app: OK")
        finally:
            p.close()
    finally:
        if emu is not None:
            adb("emu", "kill", check=False)
            try:
                emu.wait(60)
            except subprocess.TimeoutExpired:
                emu.kill()
    print("OK test_mobile_emulator")
    return 0


if __name__ == "__main__":
    sys.exit(main())
