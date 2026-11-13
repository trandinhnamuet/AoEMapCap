"""Vỏ app điện thoại v9 (repo AoE-MapCap-Mobile), chạy "trong app" giả lập như test_mobile_app (Edge ẩn):
- thanh menu dưới 4 mục (Trận / Máy tính / Cài đặt / Hướng dẫn), trang Hướng dẫn mô tả cơ chế;
- ghép đôi xong: danh sách đủ lịch sử đấu theo ngày, nhãn đã lưu / chưa lưu; tự lưu các trận 2 ngày gần nhất (trận cũ
  hơn không lưu); đổi cài đặt lưu lại;
- bấm mục Máy tính KHÔNG mất liên kết (thẻ trạng thái), chỉ Bỏ liên kết mới xoá;
- máy tính tắt: lịch sử vẫn hiện đủ, trận chưa lưu báo cần bật máy tính (không mở), trận đã lưu mở được;
- trình xem: viền trắng mép bản đồ, chạm đội / người chơi trong bảng đổi tầm nhìn, máy quay tự động khoá theo unit và
  tắt khi tự kéo máy quay.

    python tests/test_mobile_shell.py
Ảnh: Video/_test/mobile_shell/.
"""
import glob
import os
import shutil
import sys
import threading
import time
from http.server import ThreadingHTTPServer

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
from replay.library import match_info  # noqa: E402
import test_mobile_app as TA  # noqa: E402
from test_mobile_web import Browser  # noqa: E402

GAME = r"D:\Game\AoE-HD"
OUT = os.path.join(ROOT, "Video", "_test", "mobile_shell")
HOST = TA.HOST


def pick_matches():
    """2 trận ghi trong 2 ngày gần nhất + 2 trận cũ hơn (theo giờ ghi trong file), file nhỏ cho nhanh."""
    now = time.time()
    new, old = [], []
    for p in sorted(glob.glob(os.path.join(ROOT, "Video", "Raw", "*.aoerec")), key=os.path.getmtime, reverse=True):
        if not (0.8e6 < os.path.getsize(p) < 9e6):
            continue
        try:
            i = match_info(p)
        except Exception:  # noqa: BLE001
            continue
        if "error" in i or not i.get("frames"):
            continue
        (new if now - i["created"] < 2 * 86400 - 3600 else old).append(p)
        if len(new) >= 2 and len(old) >= 2:
            break
    return new[:2], old[:2]


def main():
    if MS.web_root() is None:
        print("bỏ qua: cần repo AoE-MapCap-Mobile cạnh repo này")
        return
    new, old = pick_matches()
    if len(new) < 2 or len(old) < 2:
        print(f"bỏ qua: cần 2 trận ghi trong 2 ngày gần nhất + 2 trận cũ hơn trong Video/Raw (có {len(new)} + {len(old)})")
        return
    shutil.rmtree(OUT, ignore_errors=True)
    raw, web = os.path.join(OUT, "Raw"), os.path.join(OUT, "Web")
    os.makedirs(raw)
    os.makedirs(web)
    for p in new + old:
        d = os.path.join(raw, os.path.basename(p))
        shutil.copy2(p, d)
        os.utime(d, (time.time() - 7200,) * 2)
    names_new = [os.path.basename(p) for p in new]
    names_old = [os.path.basename(p) for p in old]

    pc, _ = MS.serve(raw, GAME, port=0, token="t", cache=web, host="127.0.0.1", log=lambda m: None)
    threading.Thread(target=pc.serve_forever, daemon=True).start()
    port = pc.server_address[1]
    shell = ThreadingHTTPServer(("127.0.0.1", 0), TA.shell_handler())
    shell.daemon_threads = True
    threading.Thread(target=shell.serve_forever, daemon=True).start()
    origin = f"http://{HOST}:{shell.server_address[1]}"
    b = Browser(412, 860, args=[f"--host-resolver-rules=MAP {HOST} 127.0.0.1", "--no-proxy-server",
                                f"--unsafely-treat-insecure-origin-as-secure={origin}"])
    shot = lambda n: b.screenshot(os.path.join(OUT, n))  # noqa: E731
    try:
        b.call("Emulation.setDeviceMetricsOverride", width=412, height=860, deviceScaleFactor=2, mobile=True)
        b.call("Page.addScriptToEvaluateOnNewDocument", source="""window.AoEApp = {
            scanQr() { setTimeout(() => window.onQrResult(localStorage.getItem('test.qr'), null), 50); },
            versionCode() { return 9; } };""")
        home = origin + "/app/index.html"
        b.goto(home)
        # 1. chưa liên kết: mở ở trang Máy tính; thanh menu dưới 4 mục
        b.wait("!document.querySelector('#setup').hidden", timeout=30)
        tabs = b.eval("[...document.querySelectorAll('#tabs button')].map(x => x.textContent.trim())")
        assert tabs == ["Trận", "Máy tính", "Cài đặt", "Hướng dẫn"], tabs
        assert b.eval("document.querySelector('#link-card').hidden") and not b.eval("document.querySelector('#scan-qr').hidden")
        shot("1_may_tinh_chua_lien_ket.png")
        b.eval("document.querySelector('#tabs [data-tab=about]').click(); 1")
        about = b.eval("document.querySelector('#about').innerText")
        for w in ("Cơ chế hoạt động", "file ghi", "tự dựng", "trạm chuyển tiếp", "đã lưu", "Bỏ liên kết"):
            assert w in about, w
        assert b.eval("document.querySelector('#page-title').textContent") == "Hướng dẫn"
        shot("2_huong_dan.png")
        b.eval("document.querySelector('#tabs [data-tab=list]').click(); 1")
        assert "Chưa liên kết máy tính" in b.eval("document.querySelector('#matches').innerText")
        print("chưa liên kết: mở ở trang Máy tính, thanh menu dưới 4 mục, trang Hướng dẫn mô tả cơ chế: OK")

        # 2. ghép đôi bằng mã QR -> về danh sách: đủ 4 trận, theo ngày, nhãn chưa lưu
        b.eval(f"localStorage.setItem('test.qr', 'http://127.0.0.1:{port}/t/'); document.querySelector('#pc-btn').click(); 1")
        b.eval("document.querySelector('#scan-qr').click(); 1")
        b.wait("!document.querySelector('#list').hidden && document.querySelectorAll('.match').length === 4", timeout=60)
        assert b.eval("document.querySelectorAll('.day').length") >= 2
        assert "● Máy tính" in b.eval("document.querySelector('#pc-state').textContent")
        # 3. tự lưu 2 trận trong 2 ngày gần nhất; 2 trận cũ không lưu
        b.wait("!document.querySelector('#auto-note').hidden", timeout=30)
        shot("3_danh_sach_dang_tu_luu.png")
        t0 = time.time()
        b.wait("document.querySelectorAll('.match .tag.saved').length === 2", timeout=600)
        st = b.eval("""[...document.querySelectorAll('.match')].map(e => [e.dataset.file, !!e.querySelector('.tag.saved')])""")
        assert {f for f, s in st if s} == set(names_new), st
        keys = b.eval("caches.open('aoe-web-1').then(c => c.keys()).then(k => k.map(r => decodeURIComponent(new URL(r.url).pathname)))")
        for n in names_new:
            assert "/m/" + n in keys and "/i/" + n in keys, keys
        for n in names_old:
            assert "/m/" + n not in keys
        assert "/l/list" in keys and "/s/gamedata1" in keys and "/s/sprites" in keys
        assert "2 đã lưu" in b.eval("document.querySelector('#list-count').textContent")
        shot("4_danh_sach_da_luu.png")
        print(f"ghép đôi: 4 trận theo ngày; tự lưu đúng 2 trận của 2 ngày gần nhất ({time.time() - t0:.0f} s), 2 trận cũ để nguyên: OK")

        # 3b. danh sách dạng bảng như máy tính, đổi qua lại; máy tính biết máy này + trận đã lưu; trận máy tính chọn gửi
        b.eval("document.querySelector('#list-view [data-v=table]').click(); 1")
        heads = b.eval("[...document.querySelectorAll('table.mt th')].map(x => x.textContent)")
        assert heads == ["Ngày", "Người chơi", "Quân", "Kết quả", "Thể thức", "Map", "Kích 3", "Thời gian", "Lưu"], heads
        assert b.eval("document.querySelectorAll('table.mt tbody tr.match').length") == 4
        assert b.eval("document.querySelectorAll('table.mt .tag.saved').length") == 2 and b.eval("localStorage.getItem('aoe.view')") == "table"
        shot("4b_danh_sach_dang_bang.png")
        b.eval("document.querySelector('#list-view [data-v=cards]').click(); 1")
        assert not b.eval("!!document.querySelector('table.mt')") and b.eval("document.querySelectorAll('.match').length") == 4
        t1 = time.time()
        while time.time() - t1 < 20:
            devs = pc.phones.snapshot()[0]
            if devs and set(devs[0]["saved"]) == set(names_new):
                break
            time.sleep(0.5)
        assert len(devs) == 1 and set(devs[0]["saved"]) == set(names_new) and devs[0]["app"] == 9 and devs[0]["via"] == "lan", devs
        pc.phones.set_push([names_old[0]], True)                     # người dùng chọn "Gửi lên điện thoại" trên máy tính
        b.goto(home)
        b.wait("document.querySelectorAll('.match .tag.saved').length === 3", timeout=600)
        t1 = time.time()
        while pc.phones.snapshot()[1] and time.time() - t1 < 20:
            time.sleep(0.5)
        assert not pc.phones.snapshot()[1] and names_old[0] in pc.phones.snapshot()[0][0]["saved"]
        print("dạng bảng 9 cột như máy tính (đổi qua lại, nhớ lựa chọn); máy tính ghi nhận máy + 2 trận đã lưu; trận máy tính "
              "chọn gửi được tự lưu về (dù ngoài 2 ngày): OK")

        # 4. bấm mục Máy tính: không mất liên kết
        link0 = b.eval("[localStorage.getItem('aoe.pc'), localStorage.getItem('aoe.room')]")
        b.eval("document.querySelector('#pc-btn').click(); 1")
        b.wait("!document.querySelector('#link-card').hidden", timeout=10)
        assert "Đang kết nối được" in b.eval("document.querySelector('#link-state').textContent")
        assert "Mạng nhà" in b.eval("document.querySelector('#link-via').textContent")
        shot("5_may_tinh_da_lien_ket.png")
        b.eval("document.querySelector('#link-retry').click(); 1")
        time.sleep(1.5)
        b.eval("document.querySelector('#tabs [data-tab=list]').click(); 1")
        assert b.eval("document.querySelectorAll('.match').length") == 4
        assert b.eval("[localStorage.getItem('aoe.pc'), localStorage.getItem('aoe.room')]") == link0 and link0[0]
        b.goto(home)
        b.wait("!document.querySelector('#list').hidden && document.querySelectorAll('.match').length === 4", timeout=60)
        print("bấm mục Máy tính / kiểm tra kết nối / mở lại app: liên kết giữ nguyên, danh sách vẫn đủ: OK")

        # 5. Cài đặt: đổi là lưu
        b.eval("document.querySelector('#tabs [data-tab=settings]').click(); 1")
        b.wait("document.querySelector('#st-matches').textContent.includes('3 trận')", timeout=10)
        assert b.eval("document.querySelector('#set-auto').checked && document.querySelector('#set-days').value === '2'")
        assert "v9" in b.eval("document.querySelector('#app-ver').textContent")
        b.eval("""(() => { const s = document.querySelector('#set-days'); s.value = '7'; s.dispatchEvent(new Event('change'));
                  const m = document.querySelector('#set-max'); m.value = '1000'; m.dispatchEvent(new Event('change'));
                  const a = document.querySelector('#set-auto'); a.checked = false; a.dispatchEvent(new Event('change')); })()""")
        assert b.eval("[localStorage.getItem('aoe.autoDays'), localStorage.getItem('aoe.maxMB'), localStorage.getItem('aoe.auto')]") == ["7", "1000", "0"]
        shot("6_cai_dat.png")
        print("Cài đặt: tự lưu / số ngày / giới hạn dung lượng đổi là lưu; hiện số trận đã lưu, phiên bản: OK")

        # 6. máy tính tắt: lịch sử đủ, trận chưa lưu báo, trận đã lưu mở được
        pc.shutdown()
        pc.server_close()
        t_off = time.time()
        b.goto(home)
        b.wait("document.querySelector('#pc-state') && /Đang kiểm tra|Máy tính tắt/.test(document.querySelector('#pc-state').textContent)", timeout=20)
        b.wait("document.querySelectorAll('.match').length === 4 && !document.querySelector('#list-note').hidden", timeout=90)
        t_off = time.time() - t_off
        assert "Máy tính tắt" in b.eval("document.querySelector('#pc-state').textContent")
        assert t_off < 12, f"mở app phải biết máy tính tắt trong vài giây, mất {t_off:.1f} s"
        shot("7_ngoai_tuyen.png")
        b.eval(f"""[...document.querySelectorAll('.match')].find(e => e.dataset.file === {names_old[1]!r}).click(); 1""")
        b.wait("!document.querySelector('#dlg').hidden", timeout=10)
        txt = b.eval("document.querySelector('#dlg-text').textContent")
        assert "chưa lưu file ghi" in txt and "bật máy tính" in txt, txt
        assert b.eval("location.search") == ""
        shot("8_tran_chua_luu.png")
        b.eval("document.querySelector('#dlg-ok').click(); 1")
        b.eval("document.querySelector('#pc-btn').click(); 1")
        assert "Không kết nối được" in b.eval("document.querySelector('#link-state').textContent")
        assert b.eval("[localStorage.getItem('aoe.pc'), localStorage.getItem('aoe.room')]") == link0
        b.eval("document.querySelector('#tabs [data-tab=list]').click(); 1")
        # máy tính bật lại: trạng thái tự đổi (không phải mở lại app / bấm gì)
        pc, _ = MS.serve(raw, GAME, port=port, token="t", cache=web, host="127.0.0.1", log=lambda m: None)
        threading.Thread(target=pc.serve_forever, daemon=True).start()
        t_on = time.time()
        b.wait("document.querySelector('#pc-state').textContent.includes('Máy tính bật') && document.querySelector('#list-note').hidden", timeout=60)
        print(f"trạng thái máy tính luôn hiện: mở app biết máy tính tắt sau {t_off:.1f} s; máy tính bật lại thì tự đổi sang bật sau "
              f"{time.time() - t_on:.0f} s: OK")
        b.eval(f"""[...document.querySelectorAll('.match')].find(e => e.dataset.file === {names_new[0]!r}).click(); 1""")
        b.wait("location.search.startsWith('?m=') && window.aoeViewer && document.querySelector('#v-status').hidden", timeout=120)
        assert not b.eval("!!window.aoeLive") and not b.eval("!!aoeViewer.m.meta.partial")
        print("máy tính tắt: lịch sử vẫn đủ 4 trận, trận chưa lưu báo cần bật máy tính, trận đã lưu mở từ bộ nhớ: OK")

        # 7. trình xem: viền bản đồ, chạm người chơi / đội đổi tầm nhìn, máy quay tự động
        st = b.eval("({playing: aoeViewer.playing, auto: aoeViewer.autoCam})")
        assert st == {"playing": True, "auto": True}, f"mở trận phải tự phát + máy quay tự động bật sẵn: {st}"
        b.eval("(() => { const v = aoeViewer; v.playing = false; v.setAutoCam(false, true); v.selectUnit(null); return 1; })()")
        px = b.eval("""(() => { const v = aoeViewer, R = v.R, gl = R.gl; v.setPersp(null); v.fitView(); v._loop(performance.now());
          const [x, y] = R.outline[0]; const c = v.cam;
          const sx = Math.round((x - c.x) * c.zoom + v.canvas.width / 2 + (R.outline[1][0] - x) * 0.3 * c.zoom);
          const sy = Math.round((y - c.y) * c.zoom + v.canvas.height / 2 + (R.outline[1][1] - y) * 0.3 * c.zoom);
          let best = 0; const p = new Uint8Array(4);
          for (let dx = -3; dx <= 3; dx++) for (let dy = -3; dy <= 3; dy++) {
            gl.readPixels(sx + dx, v.canvas.height - 1 - (sy + dy), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, p);
            best = Math.max(best, Math.min(p[0], p[1], p[2])); }
          return best; })()""")
        assert px > 120, f"không thấy viền sáng ở mép bản đồ (độ sáng {px})"
        shot("9_trinh_xem_vien.png")
        b.eval("document.querySelector('.v-tools [data-a=score]').click(); 1")
        b.wait("document.querySelectorAll('.v-score tr[data-pl]').length > 1", timeout=30)
        res = b.eval("""(() => { const v = aoeViewer, M = v.m.meta; const rows = [...document.querySelectorAll('.v-score tr[data-pl]')];
          const last = rows[rows.length - 1]; const idx = +last.dataset.pl; last.click();
          const k = M.teams.findIndex(t => t.players.includes(idx));
          const team = document.querySelector('.v-score tr[data-team]');
          let viaTeam = null; if (team) { team.click(); viaTeam = [+team.dataset.team, v.persp]; }
          return {k, persp: viaTeam ? k : v.persp, sel: v.selected, idx, viaTeam}; })()""")
        assert res["persp"] == res["k"] and res["sel"] == res["idx"], res
        if res["viaTeam"]:
            assert res["viaTeam"][0] == res["viaTeam"][1], res
        assert not b.eval("!!document.querySelector('.v-tools [data-a=fit]')"), "nút Toàn cảnh đã bỏ"
        # nút Bản đồ tắt / bật được minimap thật (trước v11 CSS của khung vẽ chính đè mất hidden); hàng nút tầm nhìn nằm
        # dưới minimap, không rộng hơn minimap; thẻ unit hẹp bằng nửa trước (<= 110 px)
        lay = b.eval("""(() => { const g = s => getComputedStyle(document.querySelector(s)).display;
          const r = s => { const q = document.querySelector(s).getBoundingClientRect(); return [Math.round(q.left), Math.round(q.top), Math.round(q.right), Math.round(q.bottom)]; };
          const on = g('.v-mini'), mini = r('.v-mini'), persp = r('.v-persp');
          document.querySelector('.v-tools [data-a=mini]').click(); const off = g('.v-mini'), perspOff = r('.v-persp');
          document.querySelector('.v-tools [data-a=mini]').click();
          return {on, off, back: g('.v-mini'), mini, persp, perspOff}; })()""")
        assert lay["on"] != "none" and lay["off"] == "none" and lay["back"] != "none", lay
        assert lay["persp"][1] >= lay["mini"][3] and lay["persp"][0] >= lay["mini"][0] - 1 and lay["persp"][2] <= lay["mini"][2] + 1, lay
        assert lay["perspOff"][1] < lay["persp"][1], "minimap ẩn thì hàng nút tầm nhìn lên chỗ minimap"
        b.eval("document.querySelector('.v-tools [data-a=auto]').click(); 1")
        b.eval("(() => { const v = aoeViewer; v.setPersp(null); v.seekR(v.m.duration * 0.3); v.setSpeed(5); v.playing = true; })()")
        b.wait("aoeViewer.autoCam && aoeViewer.follow && aoeViewer.sel && aoeViewer.sel.kind === 'u'", timeout=60)
        lab = b.eval("aoeViewer._dir.label")
        assert b.eval("document.querySelector('.v-tools [data-a=auto]').classList.contains('on')")
        shot("10_may_quay_tu_dong.png")
        b.eval("""(() => { const c = aoeViewer.canvas, r = c.getBoundingClientRect(); const o = {pointerId: 1, bubbles: true, clientX: r.left + 200, clientY: r.top + 400};
          c.setPointerCapture = () => {}; c.dispatchEvent(new PointerEvent('pointerdown', o));
          c.dispatchEvent(new PointerEvent('pointermove', {...o, clientX: o.clientX + 60, clientY: o.clientY + 40}));
          c.dispatchEvent(new PointerEvent('pointerup', {...o, clientX: o.clientX + 60, clientY: o.clientY + 40})); })()""")
        assert not b.eval("aoeViewer.autoCam") and not b.eval("aoeViewer.follow")
        # v12: minimap sát mép trên; nút Ẩn / ? ở thanh thời gian, nút Máu ở cột nút
        v12 = b.eval("""(() => { const q = s => !!document.querySelector(s);
          return {top: Math.round(document.querySelector('.v-mini').getBoundingClientRect().top),
            hideBar: q('.v-bottom [data-a=hide]'), helpBar: q('.v-bottom [data-a=help]'),
            hideTools: q('.v-tools [data-a=hide]'), helpTools: q('.v-tools [data-a=help]'), hp: q('.v-tools [data-a=hp]')}; })()""")
        assert v12 == {"top": 0, "hideBar": True, "helpBar": True, "hideTools": False, "helpTools": False, "hp": True}, v12
        # thanh thời gian: vừa kéo máy quay -> đang hiện; 5 s không kéo / không dùng thanh -> mờ dần rồi ẩn; chạm chỗ trống
        # -> hiện / ẩn; kéo máy quay -> hiện lại; đang dừng thì không tự ẩn
        bar = "document.querySelector('.v-bottom')"
        assert not b.eval(bar + ".classList.contains('gone')"), "vừa kéo máy quay thì thanh thời gian phải hiện"
        b.eval("(() => { const v = aoeViewer; v.seekR(v.m.duration * 0.3); v.setSpeed(3); v.playing = true; v._barT = performance.now() - 4000; })()")
        b.wait(bar + ".classList.contains('gone')", timeout=10)
        b.wait("+getComputedStyle(" + bar + ").opacity < 0.05", timeout=5)
        assert "opacity" in b.eval("getComputedStyle(" + bar + ").transitionProperty"), "ẩn phải có hiệu ứng mờ dần"
        tap = """(() => { const v = aoeViewer, c = v.canvas, r = c.getBoundingClientRect(); v._pick = () => null;
          const o = {pointerId: 1, bubbles: true, clientX: r.left + 150, clientY: r.top + 300};
          c.dispatchEvent(new PointerEvent('pointerdown', o)); c.dispatchEvent(new PointerEvent('pointerup', o)); })()"""
        b.eval(tap)
        b.wait("!" + bar + ".classList.contains('gone')", timeout=5)
        time.sleep(0.5)
        b.eval(tap)
        b.wait(bar + ".classList.contains('gone')", timeout=5)
        b.eval("""(() => { const c = aoeViewer.canvas, r = c.getBoundingClientRect(); const o = {pointerId: 1, bubbles: true, clientX: r.left + 200, clientY: r.top + 400};
          c.dispatchEvent(new PointerEvent('pointerdown', o));
          c.dispatchEvent(new PointerEvent('pointermove', {...o, clientX: o.clientX + 60, clientY: o.clientY + 40}));
          c.dispatchEvent(new PointerEvent('pointerup', {...o, clientX: o.clientX + 60, clientY: o.clientY + 40})); })()""")
        assert not b.eval(bar + ".classList.contains('gone')"), "kéo máy quay phải hiện lại thanh thời gian"
        b.eval("(() => { const v = aoeViewer; v.playing = false; v._barT = performance.now() - 9000; delete v._pick; })()")
        time.sleep(1.0)
        assert not b.eval(bar + ".classList.contains('gone')"), "đang dừng thì thanh thời gian không tự ẩn"
        # unit đang chọn: hình thoi màu người chơi (không phải vòng tròn vàng) + thanh máu trên đầu
        selc = b.eval("""(() => { const v = aoeViewer, st = v.state; v.setPersp(null); v._loop(performance.now());
          const i = v.drawn.find(i => { const r = v.hs && v.hs.units.get(st.uid[i]); return st.owner[i] > 0 && r && r[2] > 5 && r[3] === 2; });
          if (i === undefined) return null;
          v.selectUnit({kind: 'u', uid: st.uid[i], owner: st.owner[i]}); v.follow = true;
          return v.m.meta.players.find(p => p.index === st.owner[i]).color; })()""")
        assert selc, "không có unit nào để chọn"
        try:
            b.wait("!document.querySelector('.v-hpbar').hidden && !document.querySelector('.v-mark').hidden", timeout=20)
        except TimeoutError:
            print(b.eval("(() => { const v = aoeViewer; return JSON.stringify({sel: v.sel, selHp: v._selHp || null, mark: document.querySelector('.v-mark').hidden, hs: !!v.hs, ok: v.hud.ok, hudFrame: v._hudFrame, frame: v.state.frame, hide: v.show.hide, row: v.hs && v.sel ? (v.hs.units.get(v.sel.uid) || null) : null, info: document.querySelector('.v-info').innerText.slice(0, 80)}); })()"))
            raise
        mk = b.eval("""(() => { const m = document.querySelector('.v-mark'), s = getComputedStyle(m), r = m.getBoundingClientRect();
          const h = document.querySelector('.v-hpbar').getBoundingClientRect();
          const d = document.createElement('i'); d.style.color = '%s'; document.body.appendChild(d); const want = getComputedStyle(d).color; d.remove();
          return {poly: !!m.querySelector('polygon'), radius: s.borderTopLeftRadius, border: s.borderTopWidth, same: s.color === want,
            ratio: Math.round(r.width / r.height * 10) / 10, above: h.bottom <= r.top + r.height / 2, hw: Math.round(h.width), hh: Math.round(h.height)}; })()""" % selc)
        assert mk["poly"] and mk["radius"] == "0px" and mk["border"] == "0px" and mk["same"] and mk["ratio"] == 2.0 and mk["above"] \
            and 28 <= mk["hw"] <= 116 and mk["hh"] <= 6, mk
        shot("11_chon_unit_hinh_thoi_thanh_mau.png")
        # nút Máu: thanh máu trên đầu mọi unit (khung vẽ phủ có điểm ảnh xanh), thanh riêng của unit đang chọn nhường chỗ
        b.eval("document.querySelector('.v-tools [data-a=hp]').click(); 1")
        b.wait("""(() => { const c = document.querySelector('.v-hpall'); if (c.hidden || !c.width) return false;
          const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0;
          for (let i = 0; i < d.length; i += 4) if (d[i + 1] > 180 && d[i] < 90 && d[i + 3] > 200) n++;
          return n > 40; })()""", timeout=20)
        assert b.eval("document.querySelector('.v-hpbar').hidden && document.querySelector('.v-tools [data-a=hp]').classList.contains('on')")
        shot("12_thanh_mau_moi_unit.png")
        b.eval("document.querySelector('.v-tools [data-a=hp]').click(); aoeViewer.selectUnit(null); 1")
        assert b.eval("document.querySelector('.v-hpall').hidden")
        b.eval("document.querySelector('.v-bottom [data-a=help]').click(); 1")
        assert not b.eval("document.querySelector('.v-help').hidden")
        b.eval("document.querySelector('.v-help').click(); 1")
        print("v12: minimap sát mép trên; thanh thời gian tự ẩn mờ dần sau 5 s, chạm chỗ trống ẩn / hiện, kéo máy quay hiện lại; "
              "unit chọn = hình thoi màu người chơi + thanh máu; nút Máu hiện thanh máu mọi unit; Ẩn / ? ở thanh thời gian: OK")
        assert not b.console, b.console[:3]
        print(f"trình xem: viền trắng mép bản đồ (độ sáng {px}), chạm người chơi / đội -> tầm nhìn đội đó, máy quay tự động "
              f"khoá theo unit ('{lab}') và tắt khi tự kéo: OK")

        # 8. Bỏ liên kết: chỉ lúc này liên kết mới mất; trận đã lưu vẫn còn
        b.goto(home)
        b.wait("document.querySelectorAll('.match').length === 4", timeout=60)
        b.eval("document.querySelector('#pc-btn').click(); 1")
        b.eval("document.querySelector('#link-remove').click(); 1")
        b.wait("!document.querySelector('#dlg').hidden", timeout=10)
        b.eval("document.querySelector('#dlg-act').click(); 1")
        b.wait("document.querySelector('#link-card').hidden", timeout=10)
        assert b.eval("[localStorage.getItem('aoe.pc'), localStorage.getItem('aoe.room')]") == [None, None]
        b.eval("document.querySelector('#tabs [data-tab=list]').click(); 1")
        b.wait("document.querySelectorAll('.match .tag.saved').length === 3", timeout=20)
        print("Bỏ liên kết: liên kết xoá, lịch sử + 3 trận đã lưu vẫn còn: OK")
    finally:
        b.close()
        try:
            pc.shutdown()
        except Exception:  # noqa: BLE001
            pass
        shell.shutdown()
    print("OK test_mobile_shell")


if __name__ == "__main__":
    main()
