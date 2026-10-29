// Màn hình danh sách trận + mở trình xem. Hai cách chạy:
// - trình duyệt mở thẳng máy chủ AoE-MapCap trên máy tính (http://<ip>:8765/<mã>/): nguồn là chính máy chủ đó;
// - app Android: trang nằm trong app (https://appassets.androidplatform.net/app/), địa chỉ máy tính lấy bằng quét mã
//   QR trên app Windows (AoEApp.scanQr), mở app từ trình duyệt (aoemapcap://pair -> ?pair=) hoặc nhập tay; app chuyển
//   tiếp /pc/<ip:cổng>/<mã>/... sang http://<ip:cổng>/<mã>/... (cùng nguồn, không vướng CORS / mixed content).
//   Gói hình và trận đã mở được lưu trên điện thoại (Cache Storage) để xem khi máy tính tắt.
import { SpritePack } from "./sprites.js";
import { fmtClock, Viewer } from "./viewer.js";

const IN_APP = location.hostname === "appassets.androidplatform.net";
const PC_KEY = "aoe.pc";
const MAX_SAVED = 40;           // số trận giữ trên điện thoại, bỏ trận mở lâu nhất
const REPO = "trandinhnamuet/AoEMapCap";
const APP_PKG = "io.github.trandinhnamuet.aoemapcap";
const RELEASES = `https://github.com/${REPO}/releases`;

// bản app Android mới nhất (Release tag mobile-v<N>, không phải "latest" của bản Windows); null nếu không hỏi được
async function latestApp() {
  try {
    const r = await fetch(`https://api.github.com/repos/${REPO}/releases?per_page=30`);
    if (!r.ok) return null;
    let best = null;
    for (const rel of await r.json()) {
      const m = /^mobile-v(\d+)$/.exec(rel.tag_name || "");
      const apk = m && !rel.draft && (rel.assets || []).find(a => a.name === "AoE-MapCap.apk");
      if (apk && (!best || +m[1] > best.code)) best = { code: +m[1], url: apk.browser_download_url, tag: rel.tag_name };
    }
    return best;
  } catch { return null; }
}

// trận + gói hình lưu trên máy (Cache Storage chỉ có ở trang https, tức là trong app)
class Store {
  static async open() {
    if (!self.caches) return null;
    try { return new Store(await caches.open("aoe-web-1")); } catch { return null; }
  }
  constructor(c) { this.c = c; }
  async get(key) {
    const r = await this.c.match(key);
    return r ? r.arrayBuffer() : null;
  }
  async put(key, buf) {
    try { await this.c.put(key, new Response(buf)); return true; }
    catch (e) { console.warn("không lưu được", key, e); return false; }
  }
  async saved() {               // [{file, info, at}] mới mở trước
    const out = [];
    for (const req of await this.c.keys()) {
      if (!new URL(req.url).pathname.startsWith("/i/")) continue;
      const r = await this.c.match(req);
      try { out.push(await r.json()); } catch { /* bỏ bản hỏng */ }
    }
    return out.sort((a, b) => b.at - a.at);
  }
  async saveMatch(file, buf, info) {
    const k = encodeURIComponent(file);
    if (!await this.put("/m/" + k, buf)) return;
    await this.put("/i/" + k, new TextEncoder().encode(JSON.stringify({ file, info, at: Date.now() })));
    for (const old of (await this.saved()).slice(MAX_SAVED)) {
      const ok = encodeURIComponent(old.file);
      await this.c.delete("/m/" + ok); await this.c.delete("/i/" + ok);
    }
  }
  async touch(file) {
    const k = "/i/" + encodeURIComponent(file);
    const r = await this.c.match(k);
    if (!r) return;
    const j = await r.json(); j.at = Date.now();
    await this.put(k, new TextEncoder().encode(JSON.stringify(j)));
  }
}

class Source {
  constructor(base, store) { this.base = base; this.store = store; }
  async list() {
    if (!this.base) throw new Error("chưa nhập địa chỉ máy tính");
    const r = await fetch(this.base + "api/matches", { cache: "no-store" });
    if (!r.ok) throw new Error("máy tính trả lỗi " + r.status);
    return r.json();
  }
  async _download(url, onProgress) {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error("tải lỗi " + r.status);
    const total = +r.headers.get("Content-Length") || 0;
    const reader = r.body.getReader();
    const parts = [];
    let got = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      parts.push(value); got += value.length;
      if (onProgress && total) onProgress(got / total);
    }
    return await new Blob(parts).arrayBuffer();
  }
  // máy tính chuyển trận sang .aoeweb lần đầu (vài chục giây): hỏi lại tới khi xong
  async _fetchMatch(file, onStatus) {
    if (!this.base) throw new Error("chưa nhập địa chỉ máy tính");
    const url = this.base + "api/match?f=" + encodeURIComponent(file);
    for (;;) {
      const r = await fetch(url + "&check=1", { cache: "no-store" });
      if (!r.ok) throw new Error("không kết nối được máy tính (" + r.status + ")");
      const j = await r.json();
      if (j.error) throw new Error(j.error);
      if (j.ready) break;
      onStatus && onStatus(j.waiting ? "Máy tính đang ghi trận: sẽ chuẩn bị trận này khi hết trận…"
        : "Máy tính đang chuẩn bị trận… " + Math.round((j.progress || 0) * 100) + "%");
      await new Promise(res => setTimeout(res, 1000));
    }
    return this._download(url, f => onStatus && onStatus("Đang tải trận… " + Math.round(f * 100) + "%"));
  }
  async match(file, info, onStatus) {
    if (this.store) {
      const b = await this.store.get("/m/" + encodeURIComponent(file));
      if (b) { this.store.touch(file); return b; }
    }
    const buf = await this._fetchMatch(file, onStatus);
    if (this.store) await this.store.saveMatch(file, buf, info);
    return buf;
  }
  async sprites(onStatus) {
    if (this.store) {
      const b = await this.store.get("/s/sprites");
      if (b) return b;
    }
    if (!this.base) throw new Error("chưa nhập địa chỉ máy tính");
    const buf = await this._download(this.base + "api/sprites",
      f => onStatus && onStatus("Đang tải hình game từ máy tính (một lần)… " + Math.round(f * 100) + "%"));
    if (this.store) await this.store.put("/s/sprites", buf);
    return buf;
  }
}

const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
let packPromise = null;

function show(id) {
  for (const el of document.querySelectorAll(".screen")) el.hidden = el.id !== id;
}

function resultClass(res) {
  return res === "Thắng" ? "win" : (res === "Thua" || res === "Đầu hàng") ? "lose" : "";
}

// "192.168.1.5:8765/abc123", có hoặc không có http:// và dấu / cuối -> "192.168.1.5:8765/abc123"
function parseAddr(t) {
  const m = /^([\w.-]+)(?::(\d{1,5}))?\/([A-Za-z0-9_-]+)$/.exec(t.trim().replace(/^https?:\/\//i, "").replace(/\/+$/, ""));
  return m ? `${m[1]}:${m[2] || 8765}/${m[3].toLowerCase()}` : null;
}

// thử kết nối rồi lưu địa chỉ; tải lại trang để mọi phần dùng nguồn mới
async function connect(addr, store) {
  const msg = $("#setup-msg");
  msg.textContent = "Đang kết nối " + addr + "…"; msg.className = "msg";
  try { await new Source("/pc/" + addr + "/", store).list(); }
  catch (err) {
    msg.textContent = "Không kết nối được " + addr + " (" + err.message + "). Kiểm tra: AoE-MapCap trên máy tính đã " +
      "bật mục Điện thoại, điện thoại và máy tính cùng Wi-Fi.";
    msg.className = "msg err";
    return false;
  }
  localStorage.setItem(PC_KEY, addr);
  location.replace(location.pathname);
  return true;
}

function showSetup(store) {
  show("setup");
  const inp = $("#pc-addr"), msg = $("#setup-msg");
  inp.value = localStorage.getItem(PC_KEY) || "";
  msg.textContent = ""; msg.className = "msg";
  $("#setup-offline").hidden = !store;
  $("#setup-offline").onclick = () => showList(new Source(null, store));
  const app = window.AoEApp;
  $("#scan-qr").hidden = !(app && app.scanQr);
  $("#scan-qr").onclick = () => {
    msg.textContent = "Đang mở máy quét…"; msg.className = "msg";
    // app gọi lại: (nội dung mã, null) | (null, lỗi) | (null, null) = huỷ
    window.onQrResult = (text, err) => {
      if (err) { msg.textContent = "Không quét được: " + err + ". Có thể nhập tay bên dưới."; msg.className = "msg err"; return; }
      if (text == null) { msg.textContent = ""; return; }
      const addr = parseAddr(text);
      if (!addr) { msg.textContent = "Mã QR này không phải của AoE-MapCap."; msg.className = "msg err"; return; }
      inp.value = addr;
      connect(addr, store);
    };
    app.scanQr();
  };
  $("#setup-form").onsubmit = e => {
    e.preventDefault();
    const addr = parseAddr(inp.value);
    if (!addr) { msg.textContent = "Địa chỉ dạng 192.168.1.5:8765/abc123"; msg.className = "msg err"; return; }
    connect(addr, store);
  };
}

// trình duyệt trên Android (quét QR bằng camera thường): mời tải / mở app
async function appBanner(home) {
  if (!/Android/i.test(navigator.userAgent)) return;
  const addr = location.host + home.replace(/[^/]*$/, "").replace(/\/$/, "");
  const ban = $("#app-banner");
  const dl = $("#app-dl");
  dl.href = RELEASES;
  $("#app-open").href = `intent://pair?a=${encodeURIComponent(addr)}#Intent;scheme=aoemapcap;package=${APP_PKG};` +
    `S.browser_fallback_url=${encodeURIComponent(RELEASES)};end`;
  ban.hidden = false;
  const last = await latestApp();
  if (last) dl.href = last.url;
}

// trong app: có bản mới hơn thì báo (hỏi GitHub tối đa một lần mỗi lần mở app)
async function checkUpdate() {
  const app = window.AoEApp;
  if (!app || !app.versionCode || sessionStorage.getItem("aoe.upd")) return;
  sessionStorage.setItem("aoe.upd", "1");
  const last = await latestApp();
  if (!last || last.code <= +app.versionCode()) return;
  const n = $("#update-note");
  n.innerHTML = `Có bản app mới (${esc(last.tag)}). <a href="${esc(last.url)}">Tải về</a>`;
  n.hidden = false;
}

async function showList(src) {
  show("list");
  const box = $("#matches"), note = $("#list-note");
  note.hidden = true;
  box.innerHTML = `<div class="msg">Đang tải danh sách…</div>`;
  let items, err = null;
  try { items = await src.list(); } catch (e) { err = e; }
  const saved = src.store ? await src.store.saved() : [];
  const have = new Set(saved.map(s => s.file));
  if (err) {
    if (!saved.length) { box.innerHTML = `<div class="msg err">${esc(err.message)}</div>`; return; }
    items = saved.map(s => ({ file: s.file, info: s.info }));
    note.textContent = "Không kết nối được máy tính: chỉ hiện trận đã lưu trên điện thoại.";
    note.hidden = false;
  }
  if (!items.length) { box.innerHTML = `<div class="msg">Chưa có trận nào.</div>`; return; }
  box.innerHTML = "";
  for (const it of items) {
    const i = it.info || {};
    const d = new Date((i.created || 0) * 1000);
    const date = d.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" }) + " " +
      d.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
    const teams = {};
    for (const p of i.players || []) (teams[p.team] = teams[p.team] || []).push(p);
    const tl = Object.keys(teams).sort().map(k => `<div class="team">${teams[k].map(p =>
      `<span class="${p.name === i.recorder ? "me" : ""}">${esc(p.name)}<em>${esc(p.civ)}</em></span>`).join("")}</div>`)
      .join(`<div class="vs">vs</div>`);
    const el = document.createElement("button");
    el.className = "match";
    el.innerHTML = `<div class="row1"><b class="res ${resultClass(i.result)}">${esc(i.result)}</b>
      <span>${esc(i.format)} · ${esc(i.map)}</span><span class="dur">${fmtClock(i.duration_ms || 0)}</span></div>
      <div class="row2">${tl}</div><div class="row3">${date}${have.has(it.file) ? `<span class="saved">đã lưu</span>` : ""}</div>`;
    el.onclick = () => {
      if (!IN_APP) return openMatch(src, it.file, it.info);
      // trong app: sang trang trận để nút Back của Android quay về danh sách
      sessionStorage.setItem("aoe.open", JSON.stringify(it));
      location.href = "?m=" + encodeURIComponent(it.file);
    };
    box.appendChild(el);
  }
}

async function openMatch(src, file, info, selftest) {
  show("viewer");
  const status = $("#v-status");
  status.hidden = false;
  const say = t => { status.textContent = t; };
  try {
    if (!packPromise) packPromise = src.sprites(say).then(b => new SpritePack(b));
    const pack = await packPromise;
    const buf = await src.match(file, info, say);
    say("Đang dựng bản đồ…");
    const v = new Viewer($("#viewer"), buf, pack, { onError: e => say("Lỗi: " + e.message) });
    await v.init();
    status.hidden = true;
    window.aoeViewer = v;
    if (selftest) {
      const res = await v.selftest();
      const pre = document.createElement("pre");
      pre.id = "selftest";
      pre.textContent = JSON.stringify(res);
      document.body.appendChild(pre);
      document.title = "SELFTEST " + JSON.stringify(res);
    }
  } catch (e) {
    console.error(e);
    packPromise = null;
    say("Lỗi: " + e.message);
    document.title = "ERROR " + e.message;
  }
}

async function main() {
  window.addEventListener("error", e => { document.title = "ERROR " + e.message; });
  const q = new URLSearchParams(location.search);
  const home = location.pathname;
  $("#back").onclick = () => { if (IN_APP && history.length > 1) history.back(); else location.href = home; };
  if (!IN_APP) {
    const src = new Source(home.replace(/[^/]*$/, ""), null);
    if (q.get("m")) openMatch(src, q.get("m"), null, q.get("selftest"));
    else { showList(src); appBanner(home); }
    return;
  }
  const store = await Store.open();
  if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});
  const addr = localStorage.getItem(PC_KEY);
  const src = new Source(addr ? "/pc/" + addr + "/" : null, store);
  $("#pc-btn").hidden = false;
  $("#pc-btn").onclick = () => showSetup(store);
  if (q.get("m")) {
    let info = null;
    try {
      const it = JSON.parse(sessionStorage.getItem("aoe.open")) || {};
      if (it.file === q.get("m")) info = it.info || null;
    } catch { /* không có */ }
    openMatch(src, q.get("m"), info);
  } else if (q.get("pair")) {            // mở từ trình duyệt: aoemapcap://pair?a=<địa chỉ>
    const a = parseAddr(q.get("pair"));
    showSetup(store);
    if (a) { $("#pc-addr").value = a; connect(a, store); }
  } else if (!addr) showSetup(store);
  else { showList(src); checkUpdate(); }
  // Back từ trang trận có thể khôi phục nguyên trang cũ (bfcache): vẽ lại danh sách cho nhãn "đã lưu" mới
  window.addEventListener("pageshow", e => {
    if (e.persisted && !q.get("m") && !$("#list").hidden) showList(src);
  });
}

main();
