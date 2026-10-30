"""HUD của trình xem điện thoại (.aoeweb phiên bản 2: mapcap/webhud.py + mobile/web/js/hud.js) trên trận thật:
1. bảng tỉ số (kinh tế / quân sự): số dân, tài nguyên, giết... khớp dữ liệu trận đọc bằng Python (replay.data) ở cùng mẫu;
2. công nghệ người chơi đang chọn: danh sách đã xong khớp giờ xong; đang nghiên cứu có %;
3. chạm vào unit (chọn bằng toạ độ màn hình như ngón tay): thông tin tên / máu / công giáp; chạm vào nhà: hàng đợi sinh,
   bảng lệnh (nâng cấp còn làm được);
4. nút −15s / +15s, tốc độ, khoá máy quay, ẩn HUD, minimap, trợ giúp; ảnh từng màn hình trong Video\\_test\\mobile_hud.

    python tests/test_mobile_hud.py [file.aoerec]
Máy chủ mạng nhà chỉ 127.0.0.1; Edge chạy ẩn, tắt theo PID.
"""
import json
import os
import shutil
import sys
import threading
import time
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ["AOEMAPCAP_TELEMETRY"] = "0"

from test_mobile_web import GAME, SRC, Browser  # noqa: E402

from mapcap import mobile_server as MS  # noqa: E402
from mapcap import offsets as O  # noqa: E402

OUT = os.path.join(ROOT, "Video", "_test", "mobile_hud")


def py_players(src, fi):
    """Số liệu người chơi tại mẫu fi đọc thẳng từ .aoerec (như replay/viewer.py _hud_model)."""
    from replay.data import FrameState, ReplayData
    d = ReplayData(src)
    try:
        d._index()
        st = FrameState(d.map_w, d.map_h)
        for f in range(fi + 1):
            st.apply(d.read_frame(f), f)
        out = {}
        for p in d.players_at(st):
            if p.index and (p.addr or p.pid) and p.attrs:
                out[p.index] = {"food": int(p.attrs[O.ATTR_FOOD]), "wood": int(p.attrs[O.ATTR_WOOD]),
                                "pop": int(p.attrs[O.ATTR_POP]), "kills": int(p.attrs[O.ATTR_KILLS]),
                                "research": sorted((p.researching or {}).keys())}
        return out
    finally:
        d.close()


def main():
    if not os.path.exists(SRC) or not os.path.isdir(GAME):
        print("bỏ qua: cần trận thật và thư mục game:", SRC, GAME)
        return
    os.makedirs(OUT, exist_ok=True)
    raw = os.path.join(OUT, "Raw")
    os.makedirs(raw, exist_ok=True)
    src = os.path.join(raw, os.path.basename(SRC))
    if not os.path.exists(src):
        shutil.copy2(SRC, src)
    old = time.time() - 3600
    os.utime(src, (old, old))
    cache = os.path.join(OUT, "Web")
    os.makedirs(cache, exist_ok=True)
    sp = os.path.join(ROOT, "Video", "_test", "mobile_web", "Web", "sprites.pack")
    if os.path.exists(sp) and not os.path.exists(os.path.join(cache, "sprites.pack")):
        shutil.copy2(sp, cache)
    pc, url = MS.serve(raw, GAME, port=0, token="t", cache=cache, host="127.0.0.1", log=print)
    threading.Thread(target=pc.serve_forever, daemon=True).start()
    name = os.path.basename(src)
    b = Browser(412, 860)
    shots = []

    def shot(n):
        p = os.path.join(OUT, n + ".png")
        b.screenshot(p)
        shots.append(p)

    try:
        b.goto(url + "?m=" + urllib.parse.quote(name))
        # máy tính chuyển trận lần đầu: hỏi lại tới khi xong (trang tự làm)
        b.wait("window.aoeViewer && document.querySelector('#v-status').hidden", timeout=300)
        V = "aoeViewer"
        assert b.eval(f"{V}.hud.ok"), "file .aoeweb phải có dữ liệu HUD (phiên bản 2)"
        # tới 60% trận
        b.eval(f"{V}.seekR({V}.m.duration * 0.6); 1")
        b.wait(f"{V}.state.frame > 0 && Math.abs({V}.m.r[{V}.state.frame] - {V}.m.duration * 0.6) < 1")
        time.sleep(0.5)
        shot("01_viewer")

        # 1. bảng tỉ số
        b.eval("document.querySelector('.v-tools [data-a=score]').click(); 1")
        b.wait("document.querySelectorAll('.v-score tr[data-pl]').length >= 2", timeout=20)
        hf = b.eval(f"{V}.hs.f")
        rows = b.eval("[...document.querySelectorAll('.v-score tr[data-pl]')].map(r => [+r.dataset.pl, "
                      "[...r.querySelectorAll('td')].map(t => t.textContent)])")
        py = py_players(src, hf)
        for idx, cells in rows:
            # cột kinh tế: tên, thời đại, dân, dân số, thực, gỗ, vàng, đá
            assert cells[4] == str(py[idx]["food"]) and cells[5] == str(py[idx]["wood"]), (idx, cells, py[idx])
            assert cells[3].split("/")[0] == str(py[idx]["pop"]), (idx, cells, py[idx])
        shot("02_score_eco")
        b.eval("document.querySelector('.v-score [data-x=\"1\"]').click(); 1")
        b.wait("document.querySelector('.v-score [data-x=\"1\"]').classList.contains('on')")
        rows = b.eval("[...document.querySelectorAll('.v-score tr[data-pl]')].map(r => [+r.dataset.pl, "
                      "[...r.querySelectorAll('td')].map(t => t.textContent)])")
        for idx, cells in rows:
            assert cells[2] == str(py[idx]["kills"]), (idx, cells, py[idx])
        shot("03_score_mil")
        print(f"bảng tỉ số (mẫu {hf}): thực, gỗ, dân số, giết khớp dữ liệu trận đọc bằng Python: OK")

        # 2. công nghệ: chọn người chơi bằng chạm vào hàng
        first = rows[0][0]
        b.eval(f"document.querySelector('.v-score tr[data-pl=\"{first}\"]').click(); 1")
        b.eval("document.querySelector('.v-tools [data-a=score]').click();"
               "document.querySelector('.v-tools [data-a=techs]').click(); 1")
        b.eval(f"{V}.seekR({V}.m.duration * 0.92); 1")               # trận ngắn: công nghệ đầu tiên xong ~ 11 phút
        b.wait(f"Math.abs({V}.m.r[{V}.state.frame] - {V}.m.duration * 0.92) < 1 && {V}.hs && {V}.hs.f > {hf}", timeout=30)
        time.sleep(0.5)
        b.wait("!document.querySelector('.v-techs').hidden && !!document.querySelector('.v-techs .sub')", timeout=20)
        tms = b.eval(f"{V}.m.t[{V}.state.frame]")
        n_done = b.eval("document.querySelectorAll('.v-techs .tc').length")
        want = b.eval(f"{V}.hud.done({first}, {tms}).length")
        assert n_done == want and n_done > 0, (n_done, want)
        assert b.eval("document.querySelectorAll('.v-techs img.ic').length") > 0, "phải có icon công nghệ của game"
        shot("04_techs")
        print(f"công nghệ người chơi {first}: {n_done} công nghệ đã xong, icon từ interfac.drs: OK")
        b.eval("document.querySelector('.v-tools [data-a=techs]').click(); 1")

        # 3. chạm vào unit / nhà: chọn bằng toạ độ màn hình qua _pick (như ngón tay)
        pick = b.eval(f"""(() => {{
          const v = {V}, st = v.state, H = v.hud.H, hs = v.hs;
          const out = {{unit: null, bld: null}};
          const W = v.canvas.width, Hh = v.canvas.height;
          for (const i of v.drawn) {{
            const row = hs.units.get(st.uid[i]);
            if (!row || !st.owner[i]) continue;
            const D = H.defs[row[1]]; if (!D) continue;
            const [X, Y] = v._screenOf(st.x[i], st.y[i], st.z[i]);
            if (X < 40 || Y < 120 || X > W - 40 || Y > Hh - 200) continue;
            if (D[1] === 80 && row[3] === 2 && !out.bld && hs.q.get(st.uid[i])) out.bld = [st.uid[i], X, Y - 28 * v.cam.zoom];
            if (D[1] === 70 && !out.unit) out.unit = [st.uid[i], X, Y - 16 * v.cam.zoom];
          }}
          return out;
        }})()""")
        if not pick["bld"] or not pick["unit"]:
            # cần zoom vào nhà chính người chơi đầu tiên để thấy unit / nhà
            b.eval(f"{V}.flyHome({first}); {V}.cam.zoom = 1.2 * {V}.dpr; {V}._clamp(); 1")
            time.sleep(1.0)
            b.eval(f"{V}.dirtyUnits = true; 1")
            time.sleep(0.5)
        assert pick is not None
        for kind in ("unit", "bld"):
            got = b.eval(f"""(() => {{
              const v = {V}, st = v.state, H = v.hud.H, hs = v.hs;
              const W = v.canvas.width, Hh = v.canvas.height;
              for (const i of v.drawn) {{
                const row = hs.units.get(st.uid[i]);
                if (!row || !st.owner[i]) continue;
                const D = H.defs[row[1]]; if (!D) continue;
                const [X, Y] = v._screenOf(st.x[i], st.y[i], st.z[i]);
                if (X < 20 || Y < 60 || X > W - 20 || Y > Hh - 60) continue;
                const ok = "{kind}" === "bld" ? (D[1] === 80 && row[3] === 2) : D[1] === 70;
                if (!ok) continue;
                const hit = v._pick(X, Y - ("{kind}" === "bld" ? 28 : 16) * v.cam.zoom);
                if (!hit || hit.uid !== st.uid[i]) continue;
                v.selectUnit(hit);
                // nhà: chọn nhà có bảng lệnh (sinh quân / nâng cấp), như Nhà chính
                if ("{kind}" === "bld" && !document.querySelectorAll('.v-info .cmd button').length) continue;
                return [st.uid[i], D[4]];
              }}
              return null;
            }})()""")
            assert got, f"không chạm trúng {kind} nào"
            b.wait(f"!document.querySelector('.v-info').hidden && document.querySelector('.v-info .ph b') "
                   f"&& document.querySelector('.v-info .ph b').textContent !== ''", timeout=20)
            time.sleep(0.4)
            info = b.eval("document.querySelector('.v-info').innerText")
            assert got[1] in info or "(unit" not in info, (got, info)
            assert "/" in info, f"thiếu thanh máu: {info}"
            if kind == "bld":
                ncmd = b.eval("document.querySelectorAll('.v-info .cmd button').length")
                print(f"chạm vào nhà {got[1]}: thông tin + {ncmd} ô bảng lệnh"
                      + (" + hàng đợi sinh" if "Đang sinh" in info else "") + ": OK")
                shot("06_building")
            else:
                assert "Giáp" in info, info
                assert b.eval(f"{V}.follow"), "chạm vào unit phải khoá máy quay theo unit"
                print(f"chạm vào unit {got[1]}: tên, máu, công / giáp, khoá máy quay: OK")
                shot("05_unit")

        # 4. nút điều khiển
        f0 = b.eval(f"{V}.state.frame")
        t0 = b.eval(f"{V}.m.t[{V}.state.frame]")
        b.eval("document.querySelector('.v-jb').click(); 1")
        b.wait(f"{V}.state.frame !== {f0}")
        dt = b.eval(f"{V}.m.t[{V}.state.frame]") - t0
        assert -16000 <= dt <= -14000, dt
        b.eval("document.querySelector('.v-fast').click(); document.querySelector('.v-fast').click(); 1")
        assert b.eval(f"{V}.speed") == 4, b.eval(f"{V}.speed")
        b.eval("document.querySelector('.v-speed').click(); 1")
        assert b.eval(f"{V}.speed") == 1
        b.eval("document.querySelector('.v-slow').click(); 1")
        assert b.eval(f"{V}.speed") == 0.5
        assert not b.eval("document.querySelector('.v-mini').hidden"), "minimap mặc định bật"
        b.eval("document.querySelector('.v-tools [data-a=help]').click(); 1")
        assert not b.eval("document.querySelector('.v-help').hidden")
        shot("07_help")
        b.eval("document.querySelector('.v-help').click(); document.querySelector('.v-tools [data-a=hide]').click(); 1")
        assert b.eval("document.querySelector('.v-top').hidden && document.querySelector('.v-tools').hidden "
                      "&& !document.querySelector('.v-unhide').hidden")
        shot("08_hidden")
        b.eval("document.querySelector('.v-unhide').click(); 1")
        assert not b.eval("document.querySelector('.v-top').hidden")
        print("−15s lùi 15 giây giờ game, tốc độ − / + / 1x, minimap, trợ giúp, ẩn / hiện HUD: OK")
        # phát x8 vài giây với HUD mở: không lỗi
        b.eval("document.querySelector('.v-tools [data-a=score]').click(); document.querySelector('.v-fast').click();"
               "document.querySelector('.v-fast').click(); document.querySelector('.v-fast').click();"
               "document.querySelector('.v-play').click(); 1")
        time.sleep(4)
        b.eval("document.querySelector('.v-play').click(); 1")
        shot("09_playing")
        errs = [c for c in b.console if c.startswith("EXC")]
        assert not errs, errs
        print("phát x4 với bảng tỉ số mở: không lỗi JS: OK")
    finally:
        b.close()
        pc.shutdown()
    print("ảnh:", OUT)
    print("OK test_mobile_hud")


if __name__ == "__main__":
    main()
