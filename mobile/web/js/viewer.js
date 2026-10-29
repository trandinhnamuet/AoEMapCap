// Trình xem một trận: phát / tua, đổi tầm nhìn đội, kéo / chụm để di chuyển và zoom máy quay.
// Logic chọn unit theo tầm nhìn giống replay/viewer.py (_rebuild).
import { F_BLD, F_DOP, F_DOPOK, F_FOGVIS, F_HIDE, Match, State } from "./format.js";
import { Renderer } from "./gl.js";

const SPEEDS = [0.5, 1, 2, 4, 8, 16];
const DECODE_BUDGET_MS = 8;        // giải mã sprite mới tối đa mỗi khung hình; còn lại để khung sau

export function fmtClock(ms) {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, ss = s % 60;
  const p = n => String(n).padStart(2, "0");
  return h ? `${h}:${p(m)}:${p(ss)}` : `${p(m)}:${p(ss)}`;
}

export class Viewer {
  constructor(root, matchBuf, pack, opts = {}) {
    this.root = root;
    this.pack = pack;
    this.opts = opts;
    this.buf = matchBuf;
  }

  async init() {
    this.m = await Match.open(this.buf);
    const M = this.m.meta;
    this.state = new State(this.m);
    this.canvas = this.root.querySelector("canvas");
    this.R = new Renderer(this.canvas);
    this.R.setPalette(this.pack.palette);
    const blobOf = name => new Blob([this.m.section(name)], { type: "image/jpeg" });
    await this.R.setTerrain(M, blobOf);
    this.R.setIndex(M, this.m.index);
    this.fog = new Uint8Array(M.map_w * M.map_h);
    this.fogDim = Math.round(M.fog_dim * 255);
    this.persp = M.rec_team >= 0 ? M.rec_team : null;
    this.r = 0;
    this.playing = false;
    this.speedIdx = 1;
    this.inst = { statics: new Float32Array(10 * 4096), units: new Float32Array(10 * 4096) };
    this.dirtyUnits = true; this.dirtyStatics = true; this.dirtyFog = true;
    this.lastStaticsKey = null;
    this.frameMs = [];
    this._resize();
    this.fitView();
    await this.state.seek(0);
    this._buildUi();
    this._bindInput();
    new ResizeObserver(() => { this._resize(); this.needDraw = true; }).observe(this.canvas);
    this.needDraw = true;
    this._last = performance.now();
    requestAnimationFrame(t => this._loop(t));
  }

  // ---- máy quay ----------------------------------------------------------------
  _resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const c = this.canvas;
    const w = Math.max(1, Math.round(c.clientWidth * dpr)), h = Math.max(1, Math.round(c.clientHeight * dpr));
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
    this.dpr = dpr;
  }

  fitZoom() {
    const M = this.m.meta, c = this.canvas;
    return Math.min(c.width / M.full_w, c.height / M.full_h) * 0.98;
  }

  fitView() {
    const M = this.m.meta;
    this.cam = { x: M.full_w / 2, y: M.full_h / 2, zoom: this.fitZoom() };
    this.needDraw = true;
  }

  zoomAt(factor, sx, sy) {       // sx, sy: pixel khung vẽ
    const c = this.cam, W = this.canvas.width, H = this.canvas.height;
    const z = Math.min(4, Math.max(this.fitZoom() * 0.9, c.zoom * factor));
    const wx = c.x + (sx - W / 2) / c.zoom, wy = c.y + (sy - H / 2) / c.zoom;
    c.zoom = z;
    c.x = wx - (sx - W / 2) / z; c.y = wy - (sy - H / 2) / z;
    this._clamp();
  }

  _clamp() {
    const M = this.m.meta, c = this.cam;
    c.x = Math.min(M.full_w, Math.max(0, c.x));
    c.y = Math.min(M.full_h, Math.max(0, c.y));
    this.needDraw = true;
  }

  // ---- dựng lại dữ liệu vẽ -------------------------------------------------------------
  _teamMasks() {
    const t = this.m.meta.teams[this.persp];
    return [t.vm >>> 0, t.em >>> 0];
  }

  _buildFog() {
    const V = this.state.vis, fog = this.fog;
    if (this.persp === null) { fog.fill(255); }
    else {
      const [vm, em] = this._teamMasks();
      const rev = this.m.meta.reveal;
      const dim = this.fogDim;
      for (let i = 0; i < V.length; i++) {
        const v = V[i];
        fog[i] = (v & vm) ? 255 : ((v & em) || rev) ? dim : 0;
      }
    }
    this.R.setFog(fog);
  }

  // mảnh sprite của một khoá -> ghi vào out; trả về số mảnh, -1 nếu chưa giải mã kịp
  _emit(out, n, key, ax, ay, bright, deadline) {
    const m = this.m, atlas = this.R.atlas;
    const s = m.kStart[key], c = m.kCount[key];
    for (let j = 0; j < c; j++) {
      const p = s + j;
      const ak = m.pSlp[p] * 65536 + m.pFrame[p];
      let e = atlas.map.get(ak);
      if (e === undefined) {
        if (performance.now() > deadline) { this.deferred++; return n; }
        const slp = this.pack.slp(m.pSlp[p]);
        const img = slp ? slp.decode(m.pFrame[p]) : null;
        e = img ? atlas.add(ak, img) : null;
        if (e === undefined) {                               // atlas đầy: xoá, dựng lại cả hai lô
          atlas.clear(); this.dirtyStatics = true; this.deferred++;
          return n;
        }
        if (!img) atlas.map.set(ak, null);
      }
      if (!e) continue;
      if ((n + 1) * 10 > out.length) return -2 - n;          // cần mảng lớn hơn
      const o = n * 10;
      out[o] = Math.floor(ax + m.pDx[p] + 0.5); out[o + 1] = Math.floor(ay + m.pDy[p] + 0.5);
      out[o + 2] = e.w; out[o + 3] = e.h;
      out[o + 4] = e.x; out[o + 5] = e.y; out[o + 6] = e.layer; out[o + 7] = m.pMirror[p];
      out[o + 8] = m.pColor[p]; out[o + 9] = bright;
      n++;
    }
    return n;
  }

  _fill(name, items, deadline) {
    // items: mảng [key, ax, ay, bright] đã sắp theo thứ tự vẽ
    for (;;) {
      let out = this.inst[name], n = 0, grow = false;
      for (let i = 0; i < items.length; i += 4) {
        const r = this._emit(out, n, items[i], items[i + 1], items[i + 2], items[i + 3], deadline);
        if (r < -1) { grow = true; break; }
        n = r;
      }
      if (!grow) { this.R.setBatch(name, out, n); return; }
      this.inst[name] = new Float32Array(out.length * 2);
    }
  }

  _anchor(x, y, z) {
    return [(x + y) * 32, (y - x) * 16 - z * 16 + this.m.meta.Y0];
  }

  _rebuildStatics(deadline) {
    const S = this.state.statics;
    const rows = [];
    for (const [, r] of S) {
      if (r[5] & (F_HIDE | F_DOP)) continue;
      rows.push(r);
    }
    rows.sort((a, b) => (a[2] - a[1]) - (b[2] - b[1]) || (a[1] + a[2]) - (b[1] + b[2]));
    const items = new Float64Array(rows.length * 4);
    rows.forEach((r, i) => {
      const [ax, ay] = this._anchor(r[1], r[2], r[3]);
      items.set([r[0], ax, ay, -1], i * 4);
    });
    const before = this.deferred;
    this._fill("statics", items, deadline);
    this.dirtyStatics = this.deferred > before;
  }

  _rebuildUnits(deadline) {
    const st = this.state, M = this.m.meta;
    const mw = M.map_w, mh = M.map_h;
    const V = st.vis;
    const idx = [];
    let vm = 0, em = 0;
    const rec = this.persp !== null && this.persp === M.rec_team;
    if (this.persp !== null) [vm, em] = this._teamMasks();
    const seen = this.persp !== null ? this.m.seen[this.persp] : null;
    const rev = M.reveal;
    // ô có bản ghi nhớ (doppelganger) đang thay vật thể thật
    let D = null;
    if (rec) {
      D = new Set();
      for (let i = 0; i < st.cap; i++) {
        if (!st.valid[i]) continue;
        const f = st.flags[i];
        if ((f & F_DOP) && (f & F_DOPOK) && !(f & F_HIDE)) {
          const t = Math.floor(st.y[i]) * mw + Math.floor(st.x[i]);
          if (!(V[t] & vm)) D.add(t);
        }
      }
    }
    const bright = [];
    for (let i = 0; i < st.cap; i++) {
      if (!st.valid[i]) continue;
      const f = st.flags[i];
      if (f & F_HIDE) continue;
      const k25 = (f & F_DOP) !== 0;
      let b = 1;
      if (this.persp === null) { if (k25) continue; }
      else {
        const tx = Math.min(mw - 1, Math.max(0, Math.floor(st.x[i])));
        const ty = Math.min(mh - 1, Math.max(0, Math.floor(st.y[i])));
        const t = ty * mw + tx;
        const vT = (V[t] & vm) !== 0;
        const eT = vT || (V[t] & em) !== 0 || rev;
        let fv = (f & F_FOGVIS) !== 0;
        if (!fv && (f & F_BLD) && seen) { const s = seen.get(st.uid[i]); fv = s !== undefined && s <= st.frame; }
        let keep;
        if (rec) keep = (k25 && (f & F_DOPOK) && !vT) || (!k25 && (vT || (eT && fv && !D.has(t))));
        else keep = !k25 && (vT || (eT && fv));
        if (!keep) continue;
        b = vT && !k25 ? 1 : M.fog_dim;
      }
      idx.push(i);
      bright.push(b);
    }
    const order = idx.map((_, k) => k);
    order.sort((a, b) => {
      const ia = idx[a], ib = idx[b];
      return (st.y[ia] - st.x[ia]) - (st.y[ib] - st.x[ib]) || (st.x[ia] + st.y[ia]) - (st.x[ib] + st.y[ib]);
    });
    const items = new Float64Array(order.length * 4);
    order.forEach((k, j) => {
      const i = idx[k];
      const [ax, ay] = this._anchor(st.x[i], st.y[i], st.z[i]);
      items[j * 4] = st.key[i]; items[j * 4 + 1] = ax; items[j * 4 + 2] = ay; items[j * 4 + 3] = bright[k];
    });
    this.unitCount = order.length;
    const before = this.deferred;
    this._fill("units", items, deadline);
    this.dirtyUnits = this.deferred > before;
  }

  // ---- phát lại -------------------------------------------------------------------------
  get speed() { return SPEEDS[this.speedIdx]; }

  seekR(r) {
    this.r = Math.max(0, Math.min(this.m.duration, r));
    this.needSeek = true;
  }

  setPersp(p) {
    this.persp = p;
    this.dirtyFog = this.dirtyUnits = true;
    this._updateUi();
  }

  _loop(now) {
    const dt = Math.min(0.25, (now - this._last) / 1000);
    this._last = now;
    if (this.playing) {
      this.r += dt * this.speed;
      if (this.r >= this.m.duration) { this.r = this.m.duration; this.playing = false; this._updateUi(); }
      this.needSeek = true;
    }
    if (this.needSeek && !this.seeking) {
      this.needSeek = false;
      const fi = this.m.frameAtR(this.r);
      if (fi !== this.state.frame) {
        this.seeking = true;
        this.state.seek(fi).then(changed => {
          this.seeking = false;
          if (changed) { this.dirtyUnits = this.dirtyFog = true; }
        }).catch(e => { this.seeking = false; this._error(e); });
      }
    }
    const t0 = performance.now();
    const deadline = t0 + DECODE_BUDGET_MS;
    this.deferred = 0;
    let rebuilt = false;
    if (this.dirtyFog) { this._buildFog(); this.dirtyFog = false; rebuilt = true; }
    const skey = this.state.sVersion + ":" + this.R.atlas.generation;
    if (this.dirtyStatics || skey !== this.lastStaticsKey) {
      this.lastStaticsKey = skey;
      this._rebuildStatics(deadline);
      rebuilt = true;
    }
    if (this.R.atlas.generation !== this.unitGen) { this.unitGen = this.R.atlas.generation; this.dirtyUnits = true; }
    if (this.dirtyUnits || this.dirtyStatics) { this._rebuildUnits(deadline); rebuilt = true; }
    if (rebuilt || this.needDraw) {
      this.R.draw(this.cam);
      this.needDraw = false;
      this.frameMs.push(performance.now() - t0);
      if (this.frameMs.length > 600) this.frameMs.shift();
    }
    if (this.ui) this._tickUi();
    requestAnimationFrame(t => this._loop(t));
  }

  _error(e) {
    console.error(e);
    if (this.opts.onError) this.opts.onError(e);
  }

  // ---- giao diện -----------------------------------------------------------------------
  _buildUi() {
    const M = this.m.meta, root = this.root;
    const q = s => root.querySelector(s);
    this.ui = { time: q(".v-time"), play: q(".v-play"), speed: q(".v-speed"), seek: q(".v-seek"),
                persp: q(".v-persp"), ages: q(".v-ages") };
    const u = this.ui;
    u.seek.max = 1000;
    u.play.onclick = () => { if (this.r >= this.m.duration) this.r = 0; this.playing = !this.playing; this._updateUi(); };
    u.speed.onclick = () => { this.speedIdx = (this.speedIdx + 1) % SPEEDS.length; this._updateUi(); };
    u.seek.oninput = () => { this.seekR(u.seek.value / 1000 * this.m.duration); this.scrubbing = true; };
    u.seek.onchange = () => { this.scrubbing = false; };
    // tầm nhìn: Toàn bản đồ, Đội 1, Đội 2...
    u.persp.innerHTML = "";
    const opts = [[null, "Toàn map"]];
    M.teams.forEach((t, k) => opts.push([k, "Đội " + (k + 1)]));
    for (const [p, label] of opts) {
      const b = document.createElement("button");
      b.textContent = label;
      b.dataset.p = p === null ? "" : p;
      if (p !== null) {
        const dots = M.teams[p].players.map(i => M.players.find(x => x.index === i)).filter(Boolean)
          .map(pl => `<i style="background:${pl.color}"></i>`).join("");
        b.innerHTML = `${dots}<span>${label}</span>`;
      }
      b.onclick = () => this.setPersp(p);
      u.persp.appendChild(b);
    }
    // vạch lên đời trên thanh thời gian
    u.ages.innerHTML = "";
    const dur = this.m.duration || 1;
    for (const [r, idx, age] of M.ages) {
      const pl = M.players.find(x => x.index === idx);
      const s = document.createElement("i");
      s.style.left = (r / dur * 100) + "%";
      s.style.background = pl ? pl.color : "#fff";
      s.title = `${pl ? pl.name : idx}: đời ${age}`;
      u.ages.appendChild(s);
    }
    this._updateUi();
  }

  _updateUi() {
    const u = this.ui;
    if (!u) return;
    u.play.textContent = this.playing ? "❚❚" : "▶";
    u.speed.textContent = this.speed + "x";
    for (const b of u.persp.children) b.classList.toggle("on", b.dataset.p === (this.persp === null ? "" : String(this.persp)));
  }

  _tickUi() {
    const u = this.ui;
    const fi = Math.max(0, this.state.frame);
    const txt = fmtClock(this.m.t[fi]);
    if (u.time.textContent !== txt) u.time.textContent = txt;
    if (!this.scrubbing) u.seek.value = Math.round(this.r / (this.m.duration || 1) * 1000);
  }

  _bindInput() {
    const c = this.canvas;
    const pts = new Map();
    let pinch = null, lastTap = 0;
    c.addEventListener("pointerdown", e => {
      c.setPointerCapture(e.pointerId);
      pts.set(e.pointerId, [e.clientX, e.clientY]);
      if (pts.size === 2) {
        const [a, b] = [...pts.values()];
        pinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]), zoom: this.cam.zoom };
      }
      const now = performance.now();
      if (pts.size === 1 && now - lastTap < 300) {               // chạm đúp: phóng to 2 lần quanh điểm chạm
        const r = c.getBoundingClientRect();
        this.zoomAt(2, (e.clientX - r.left) * this.dpr, (e.clientY - r.top) * this.dpr);
      }
      lastTap = now;
    });
    c.addEventListener("pointermove", e => {
      const p = pts.get(e.pointerId);
      if (!p) return;
      const prev = [...pts.values()];
      const mid0 = prev.reduce((s, q) => [s[0] + q[0] / prev.length, s[1] + q[1] / prev.length], [0, 0]);
      pts.set(e.pointerId, [e.clientX, e.clientY]);
      const cur = [...pts.values()];
      const mid1 = cur.reduce((s, q) => [s[0] + q[0] / cur.length, s[1] + q[1] / cur.length], [0, 0]);
      const z = this.cam.zoom / this.dpr;
      this.cam.x -= (mid1[0] - mid0[0]) / z;
      this.cam.y -= (mid1[1] - mid0[1]) / z;
      if (pinch && pts.size === 2) {
        const [a, b] = cur;
        const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
        const r = c.getBoundingClientRect();
        const f = (pinch.zoom * d / pinch.d) / this.cam.zoom;
        this.zoomAt(f, (mid1[0] - r.left) * this.dpr, (mid1[1] - r.top) * this.dpr);
      }
      this._clamp();
    });
    const up = e => { pts.delete(e.pointerId); if (pts.size < 2) pinch = null; };
    c.addEventListener("pointerup", up);
    c.addEventListener("pointercancel", up);
    c.addEventListener("wheel", e => {
      e.preventDefault();
      const r = c.getBoundingClientRect();
      this.zoomAt(Math.pow(1.0015, -e.deltaY), (e.clientX - r.left) * this.dpr, (e.clientY - r.top) * this.dpr);
    }, { passive: false });
    window.addEventListener("keydown", e => {
      if (e.key === " " || e.key === "p") { this.ui.play.click(); e.preventDefault(); }
      else if (e.key === "Home") this.fitView();
      else if (e.key === "F1") { this.setPersp(0); e.preventDefault(); }
      else if (e.key === "F2" && this.m.meta.teams.length > 1) { this.setPersp(1); e.preventDefault(); }
      else if (e.key === "F3") { this.setPersp(null); e.preventDefault(); }
    });
  }

  // ---- tự kiểm tra: tua nhiều chỗ, đo thời gian dựng + vẽ -----------------------------------
  async selftest() {
    const out = { frames: this.m.frames, units: [], seekMs: [], buildMs: [] };
    const dur = this.m.duration;
    for (const frac of [0.1, 0.35, 0.6, 0.9]) {
      const t0 = performance.now();
      await this.state.seek(this.m.frameAtR(dur * frac));
      out.seekMs.push(+(performance.now() - t0).toFixed(1));
      this.dirtyUnits = this.dirtyFog = true;
      // dựng tới khi hết sprite chờ giải mã
      for (let k = 0; k < 40 && (this.dirtyUnits || this.dirtyStatics || this.dirtyFog); k++) {
        const t1 = performance.now();
        this.deferred = 0;
        if (this.dirtyFog) { this._buildFog(); this.dirtyFog = false; }
        this._rebuildStatics(t1 + 1e9);
        this._rebuildUnits(t1 + 1e9);
        this.R.draw(this.cam);
        out.buildMs.push(+(performance.now() - t1).toFixed(1));
      }
      out.units.push(this.unitCount);
    }
    // phát x8 trong 3 s: đo khung
    this.frameMs = [];
    this.speedIdx = 4; this.playing = true;
    await new Promise(r => setTimeout(r, 3000));
    this.playing = false;
    const f = [...this.frameMs].sort((a, b) => a - b);
    out.play = { n: f.length, median: f[f.length >> 1], p95: f[Math.floor(f.length * 0.95)] };
    out.atlasLayers = this.R.atlas.layer + 1;
    return out;
  }
}
