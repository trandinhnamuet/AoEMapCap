"""Xem trận khi điện thoại khác mạng (v16): máy chủ điện thoại trên máy này + trạm chuyển tiếp Cloudflare THẬT
(relay/src/index.js, mapcap/relay_client.py) + Edge chạy ẩn đóng vai điện thoại mở trang trên trạm (quét mã QR bằng
camera thường). Mọi dữ liệu trận đi máy này -> Cloudflare -> Edge, không qua mạng nhà.
Kiểm:
1. mã QR = https://<trạm>/#r=<phòng>&l=<địa chỉ mạng nhà>; máy tính báo "online";
2. trang trên trạm: mã phòng rời khỏi thanh địa chỉ, danh sách trận, mở trận (gói hình + trận qua trạm), lưu trên máy,
   tự kiểm tra trình xem; dải "Tải app / Mở trong app" (UA Android) có intent pair?r=...;
3. yêu cầu ngoài api/ bị máy tính từ chối; tín dụng giữ luồng (trạm không giữ quá ~1 MB);
4. tắt máy tính: trang báo máy tính chưa sẵn sàng, vẫn xem trận đã lưu.

    python tests/test_relay.py [file.aoerec]
Cần Internet. Phòng ngẫu nhiên riêng cho lần chạy (thư mục Video\\_test\\relay). Edge chạy ẩn, tắt theo PID.
"""
import json
import os
import shutil
import sys
import time
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ["AOEMAPCAP_TELEMETRY"] = "0"

from test_mobile_web import GAME, SRC, Browser  # noqa: E402

from mapcap import mobile_server as MS  # noqa: E402
from mapcap import relay_client as RC  # noqa: E402

OUT = os.path.join(ROOT, "Video", "_test", "relay")


def wait_state(phone, want, timeout=40):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if phone.relay_state() == want:
            return True
        time.sleep(0.2)
    raise AssertionError(f"trạm: {phone.relay_state()} (chờ {want})")


def raw_relay_checks(room):
    """Gọi thẳng trạm như điện thoại: đường ngoài api/ bị từ chối; không cấp thêm tín dụng thì máy tính dừng gửi."""
    import struct

    import websocket

    from mapcap.updater import ssl_context
    ws = websocket.create_connection(RC.relay_base().replace("https", "wss") + f"/r/{room}?role=phone",
                                     sslopt={"context": ssl_context()}, timeout=30)
    assert json.loads(ws.recv()) == {"hello": 1, "pc": True}
    ws.send(json.dumps({"r": 1, "p": "index.html", "k": 4}))
    op, b = ws.recv_data()
    r, kind = struct.unpack_from("<IB", b)
    assert r == 1 and kind == RC.ERR, (r, kind, b[:80])
    ws.send(json.dumps({"r": 2, "p": "api/sprites", "k": 3}))
    got, t0 = [], time.time()
    ws.settimeout(4)
    try:
        while True:
            op, b = ws.recv_data()
            got.append(struct.unpack_from("<IB", b)[1])
    except websocket.WebSocketTimeoutException:
        pass
    assert got[0] == RC.HEAD and got.count(RC.DATA) == 3, got        # 3 tín dụng -> đúng 3 khung rồi chờ
    ws.send(json.dumps({"r": 2, "k": 2}))
    ws.settimeout(10)
    more = [struct.unpack_from("<IB", ws.recv_data()[1])[1] for _ in range(2)]
    assert more == [RC.DATA, RC.DATA], more
    ws.send(json.dumps({"r": 2, "x": 1}))
    ws.close()
    print("trạm: đường ngoài api/ bị từ chối; tín dụng giữ luồng (3 rồi dừng, +2 thì gửi thêm 2): OK")


def main():
    if not os.path.exists(SRC) or not os.path.isdir(GAME):
        print("bỏ qua: cần trận thật và thư mục game:", SRC, GAME)
        return
    shutil.rmtree(OUT, ignore_errors=True)
    raw = os.path.join(OUT, "Raw")
    os.makedirs(raw)
    src = os.path.join(raw, os.path.basename(SRC))
    shutil.copy2(SRC, src)
    old = time.time() - 3600
    os.utime(src, (old, old))
    web_cache = os.path.join(ROOT, "Video", "_test", "mobile_web", "Web")     # gói hình / trận đã chuyển (nếu có)
    cache = os.path.join(OUT, "Web")
    if os.path.isdir(web_cache):
        shutil.copytree(web_cache, cache, ignore=shutil.ignore_patterns("token.txt", "relay.txt"))

    phone = MS.PhoneServer(log=lambda m: print("  [pc]", m))
    phone.start(raw, GAME, cache=cache)
    b = None
    try:
        url = phone.pair_url()
        u = urllib.parse.urlsplit(url)
        q = urllib.parse.parse_qs(u.fragment)
        assert url.startswith(RC.RELAY + "/#r="), url
        assert q["r"] == [phone.room] and len(phone.room) == 24 and q["l"] == [phone.address()], (url, q)
        wait_state(phone, "online")
        print(f"máy tính: kết nối trạm, mã QR {url[:60]}…: OK")
        raw_relay_checks(phone.room)

        b = Browser(412, 860)
        b.call("Emulation.setUserAgentOverride",
               userAgent="Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/130.0 Mobile Safari/537.36")
        b.goto(url)
        b.wait("!document.querySelector('#list').hidden && document.querySelectorAll('.match').length", timeout=90)
        assert b.eval("location.hash") == "", "mã phòng phải rời khỏi thanh địa chỉ"
        assert b.eval("localStorage.getItem('aoe.room')") == phone.room
        href = b.eval("document.querySelector('#app-open').href")
        assert href.startswith(f"intent://pair?r={phone.room}&l=") and not b.eval("document.querySelector('#app-banner').hidden"), href
        b.screenshot(os.path.join(OUT, "cloud_list.png"))
        print("trang trên trạm: danh sách trận qua Internet, dải Tải app / Mở trong app (intent r=phòng): OK")

        t0 = time.time()
        b.eval("document.querySelector('.match').click(); 1")
        b.wait("location.search.startsWith('?m=') && window.aoeViewer && document.querySelector('#v-status').hidden",
               timeout=600)
        dt = time.time() - t0
        res = b.eval("aoeViewer.selftest()")
        assert res["units"][-1] > 0, res
        keys = b.eval("(async () => (await (await caches.open('aoe-web-1')).keys())"
                      ".map(r => new URL(r.url).pathname))()")
        enc = urllib.parse.quote(os.path.basename(src), safe="")
        assert set(keys) >= {"/s/sprites", "/m/" + enc, "/i/" + enc}, keys
        size = sum(os.path.getsize(os.path.join(cache, f)) for f in os.listdir(cache) if f.endswith((".pack", ".aoeweb")))
        b.screenshot(os.path.join(OUT, "cloud_viewer.png"))
        print(f"mở trận qua trạm: {size / 1e6:.1f} MB trong {dt:.0f} s (gồm chuẩn bị trận nếu chưa có), lưu trên máy, "
              "trình xem tự kiểm tra: OK")

        phone.stop()
        b.goto(RC.RELAY + "/")
        b.wait("!document.querySelector('#list-note').hidden && document.querySelectorAll('.match').length", timeout=60)
        note = b.eval("document.querySelector('#list-note').textContent")
        assert "trận đã lưu" in note, note
        b.eval("document.querySelector('.match').click(); 1")
        b.wait("window.aoeViewer && document.querySelector('#v-status').hidden", timeout=120)
        b.screenshot(os.path.join(OUT, "cloud_offline.png"))
        print("tắt máy tính: trang hiện trận đã lưu, mở được từ bộ nhớ điện thoại: OK")
        assert not [c for c in b.console if c.startswith("EXC")], b.console
    finally:
        if b is not None:
            b.close()
        phone.stop()
    print("OK test_relay")


if __name__ == "__main__":
    main()
