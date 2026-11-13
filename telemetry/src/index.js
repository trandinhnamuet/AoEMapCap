// Thống kê sử dụng AoE-MapCap: Cloudflare Worker + D1 (không server riêng, không tên miền riêng).
//   POST /v1/e            app gửi một lượt: {"id": mã máy UUID, "app": "mapcap"|"replay", "v": phiên bản, "ev": "open"|"match",
//                         "name": tên người chơi (nickname trong game, có thể rỗng / trùng; từ v7)}
//   GET  /stats           trang thống kê (đăng nhập bằng mật khẩu STATS_PASSWORD, đặt bằng `wrangler secret put`)
//   GET  /api/stats       số liệu cho trang thống kê (Authorization: Bearer <mật khẩu>)
//   POST /v1/report       app gửi một trận bị nghi có hack (thân = file .aoerec, thông tin ở tham số URL; 2026-11-11):
//                         file vào R2 (binding REPORTS), thông tin vào bảng reports (migrations/0004)
//   GET  /api/reports     danh sách báo cáo; GET /api/report/file?id= tải file; POST /api/report/update đánh dấu
//                         (admin, cùng mật khẩu)
// IP lấy từ CF-Connecting-IP (app kết nối bằng IPv4), nước từ request.cf.country. Ngày tính theo giờ Việt Nam.
import { DASHBOARD_HTML } from "./dashboard.js";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const APPS = new Set(["mapcap", "replay"]);
const EVENTS = new Set(["open", "match"]);
const VN = 7 * 3600 * 1000;               // giờ Việt Nam = UTC+7
const PAGE = 50;
const SEARCH_CAP = 1000;                   // tìm trong bảng Từng lượt: đếm tối đa chừng này (không quét hết)
const REPORT_MAX = 95 * 1024 * 1024;       // byte tối đa một file báo cáo (Worker gói miễn phí nhận thân <= 100 MB)
const REPORT_STORE = 8 * 1024 ** 3;        // tổng dung lượng giữ trên R2 (gói miễn phí 10 GB): xoá file cũ nhất TRƯỚC khi
                                           // lưu file mới nên không bao giờ vượt; 2 GB dư cho các lượt gửi cùng lúc
const REPORT_ALL_PER_DAY = 100;            // cả hệ thống tối đa chừng này báo cáo / 24 giờ (giữ số lượt ghi R2 nhỏ)
const REPORT_PER_DAY = 5;                  // mỗi máy tối đa chừng này báo cáo / 24 giờ (chống gửi dồn)
const REPORT_IP_PER_DAY = 10;
const STATUSES = new Set(["new", "hack", "clean", "unsure"]);

const json = (data, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    try {
      if (url.pathname === "/v1/e" && request.method === "POST") return await ingest(request, env);
      if (url.pathname === "/stats" || url.pathname === "/stats/") {
        return new Response(DASHBOARD_HTML, {
          headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store",
                     "x-robots-tag": "noindex", "x-frame-options": "DENY", "referrer-policy": "no-referrer",
                     "x-content-type-options": "nosniff",
                     // chỉ chạy script của trang + Chart.js (đã kiểm SRI), chỉ gọi API cùng nguồn
                     "content-security-policy": "default-src 'none'; script-src 'unsafe-inline' https://cdnjs.cloudflare.com; " +
                       "style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; " +
                       "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'" },
        });
      }
      if (url.pathname === "/api/stats") return await stats(request, env, url);
      if (url.pathname === "/v1/report" && request.method === "POST") return await reportUpload(request, env, url);
      if (url.pathname === "/api/reports") return await reportList(request, env);
      if (url.pathname === "/v1/report/status" && request.method === "GET") return await reportStatus(env, url);
      if (url.pathname === "/v1/report/reply" && request.method === "POST") return await reportReply(request, env);
      if (url.pathname === "/api/report/message" && request.method === "POST") return await reportMessage(request, env);
      if (url.pathname === "/api/report/file") return await reportFile(request, env, url);
      if (url.pathname === "/api/report/update" && request.method === "POST") return await reportUpdate(request, env);
      if (url.pathname === "/") return new Response("AoE-MapCap telemetry\n", { headers: { "content-type": "text/plain" } });
      return new Response("not found\n", { status: 404 });
    } catch (e) {
      return json({ error: String(e && e.message || e) }, 500);
    }
  },
};

async function ingest(request, env) {
  let body;
  try {
    body = await request.json();
  } catch {
    return json({ ok: false, error: "bad json" }, 400);
  }
  const id = String(body.id || "");
  const app = String(body.app || "");
  const version = String(body.v || "").slice(0, 16);
  const ev = String(body.ev || "open");
  if (!UUID.test(id) || !APPS.has(app) || !version || !EVENTS.has(ev)) return json({ ok: false, error: "bad event" }, 400);
  // tên người chơi: bỏ ký tự điều khiển, tối đa 40 ký tự; rỗng = chưa biết (giữ tên cũ của máy)
  const name = String(body.name || "").replace(/[\u0000-\u001f\u007f]/g, "").trim().slice(0, 40);
  const ip = request.headers.get("cf-connecting-ip") || "";
  const country = (request.cf && request.cf.country) || "";
  const now = Date.now();
  const db = env.DB;
  // chống gửi dồn: cùng máy + cùng app + cùng loại trong 5 s, hoặc một IP quá 120 lượt / phút -> bỏ (vẫn trả ok)
  const dup = await db.prepare("SELECT 1 FROM events WHERE install = ? AND app = ? AND ev = ? AND ts > ? LIMIT 1")
    .bind(id, app, ev, now - 5000).first();
  if (dup) return json({ ok: true, dropped: "dup" });
  const burst = await db.prepare("SELECT COUNT(*) AS n FROM events WHERE ip = ? AND ts > ?").bind(ip, now - 60000).first();
  if (burst && burst.n > 120) return json({ ok: true, dropped: "rate" });
  // bảng tổng hợp (migrations/0003): máy mới? lần đầu trong ngày? tên người chơi của trận (không có thì tên đã biết)
  const prev = await db.prepare("SELECT last_ts, name FROM installs WHERE install = ?").bind(id).first();
  const day = vnDay(now);
  const newDay = !prev || vnDay(prev.last_ts) !== day;
  const isOpen = ev === "open" ? 1 : 0;
  const isMatch = ev === "match" ? 1 : 0;
  const pname = isMatch ? (name || String((prev && prev.name) || "").trim()) : "";
  const agg = [
    db.prepare(`INSERT INTO day_total (date, opens, matches, installs, new_installs) VALUES (?1, ?2, ?3, ?4, ?5)
                ON CONFLICT(date) DO UPDATE SET opens = opens + ?2, matches = matches + ?3, installs = installs + ?4,
                  new_installs = new_installs + ?5`)
      .bind(day, isOpen, isMatch, newDay ? 1 : 0, prev ? 0 : 1),
    db.prepare(`INSERT INTO day_install (date, install, opens, matches) VALUES (?1, ?2, ?3, ?4)
                ON CONFLICT(date, install) DO UPDATE SET opens = opens + ?3, matches = matches + ?4`)
      .bind(day, id, isOpen, isMatch),
    db.prepare(`INSERT INTO install_ip (install, ip, last_ts) VALUES (?1, ?2, ?3)
                ON CONFLICT(install, ip) DO UPDATE SET last_ts = ?3`).bind(id, ip, now),
  ];
  if (pname) {
    agg.push(
      db.prepare(`INSERT INTO name_total (name, matches, last_ts) VALUES (?1, 1, ?2)
                  ON CONFLICT(name) DO UPDATE SET matches = matches + 1, last_ts = ?2`).bind(pname, now),
      db.prepare(`INSERT INTO day_name (date, name, matches) VALUES (?1, ?2, 1)
                  ON CONFLICT(date, name) DO UPDATE SET matches = matches + 1`).bind(day, pname));
  }
  await db.batch([
    db.prepare("INSERT INTO events (ts, install, app, version, ev, ip, country, name) VALUES (?, ?, ?, ?, ?, ?, ?, ?)")
      .bind(now, id, app, version, ev, ip, country, name || null),
    db.prepare(
      `INSERT INTO installs (install, first_ts, last_ts, first_ip, last_ip, country, app, version, opens, matches, name)
       VALUES (?1, ?2, ?2, ?3, ?3, ?4, ?5, ?6, ?7, ?8, ?9)
       ON CONFLICT(install) DO UPDATE SET last_ts = ?2, last_ip = ?3, country = ?4, app = ?5, version = ?6,
         opens = opens + ?7, matches = matches + ?8, name = COALESCE(?9, name)`)
      .bind(id, now, ip, country, app, version, isOpen, isMatch, name || null),
    ...agg,
  ]);
  return json({ ok: true });
}

// ngày giờ Việt Nam 'YYYY-MM-DD' của một thời điểm (ms UTC)
function vnDay(ts) {
  return new Date(Number(ts) + VN).toISOString().slice(0, 10);
}

function authorized(request, env) {
  const pw = env.STATS_PASSWORD || "";
  const h = request.headers.get("authorization") || "";
  return pw.length >= 8 && h === "Bearer " + pw;
}

function rangeStart(range) {
  // ngày theo giờ Việt Nam (như trang trecome: "Hôm nay" = từ 0:00 hôm nay, "7 ngày" = 6 ngày trước + hôm nay)
  if (range === "all") return 0;
  const days = { today: 1, "7d": 7, "28d": 28, "90d": 90 }[range] || 7;
  const vnNow = Date.now() + VN;
  const vnMidnight = vnNow - (vnNow % 86400000);
  return vnMidnight - (days - 1) * 86400000 - VN;
}

async function stats(request, env, url) {
  if (!authorized(request, env)) return json({ error: "unauthorized" }, 401);
  const db = env.DB;
  const range = url.searchParams.get("range") || "7d";
  const page = Math.max(1, parseInt(url.searchParams.get("page") || "1", 10) || 1);
  const q = (url.searchParams.get("q") || "").trim().slice(0, 64);
  // bảng Từng lượt sắp theo cột người xem bấm (chỉ cột trong danh sách trắng -> không chèn SQL được)
  const SORT = { ts: "e.ts", ip: "e.ip", name: "COALESCE(NULLIF(e.name, ''), i.name, '')", app: "e.app",
                 version: "CAST(e.version AS INTEGER)", ev: "e.ev", country: "e.country" };
  const sortKey = Object.hasOwn(SORT, url.searchParams.get("sort") || "") ? url.searchParams.get("sort") : "ts";
  const sortDir = url.searchParams.get("dir") === "asc" ? "asc" : "desc";
  const from = rangeStart(range);
  const like = "%" + q.replace(/[%_]/g, "") + "%";
  const qWhere = q ? " AND (e.ip LIKE ?2 OR e.install LIKE ?2 OR e.version LIKE ?2 OR e.name LIKE ?2 OR i.name LIKE ?2)" : "";

  // Mỗi lần xem chỉ đọc bảng tổng hợp (migrations/0003, cập nhật lúc nhận lượt): số dòng đọc theo số ngày / số máy /
  // số tên trong kỳ, không theo tổng số lượt đã lưu (trước 2026-11-10: ~19 dòng đọc cho mỗi lượt mỗi lần xem).
  // Kỳ "Tất cả" lấy thẳng bảng installs / name_total (đã có tổng). Bảng Từng lượt: trang 50 dòng theo chỉ mục ts;
  // part=recent (tìm / sắp xếp / chuyển trang) chỉ chạy phần này.
  const all = range === "all";
  const fromDay = vnDay(from);
  const like2 = q ? [from, like] : [from];
  const recentStmt = db.prepare(`SELECT e.id, e.ts, e.install, e.app, e.version, e.ev, e.ip, e.country,
                       COALESCE(e.name, i.name) AS name, (e.ts = i.first_ts) AS isNew
                FROM events e JOIN installs i ON i.install = e.install
                WHERE e.ts >= ?1${qWhere} ORDER BY ${SORT[sortKey]} ${sortDir.toUpperCase()}, e.ts DESC, e.id DESC
                LIMIT ${PAGE} OFFSET ${(page - 1) * PAGE}`).bind(...like2);
  // tổng số bản ghi: không tìm -> cộng từ day_total; có tìm -> đếm tối đa SEARCH_CAP + 1 dòng (báo "hơn ...")
  const countStmt = q
    ? db.prepare(`SELECT COUNT(*) AS n FROM (SELECT 1 FROM events e JOIN installs i ON i.install = e.install
                  WHERE e.ts >= ?1${qWhere} LIMIT ${SEARCH_CAP + 1})`).bind(...like2)
    : db.prepare("SELECT COALESCE(SUM(opens + matches), 0) AS n FROM day_total WHERE date >= ?1").bind(fromDay);
  const recentOut = (recent, total) => ({
    recent: recent.results,
    recentTotal: Math.min(total.results[0].n || 0, q ? SEARCH_CAP : Infinity),
    recentCapped: !!q && (total.results[0].n || 0) > SEARCH_CAP,
    page,
    pageSize: PAGE,
    sort: sortKey,
    dir: sortDir,
    updatedAt: Date.now(),
  });
  if (url.searchParams.get("part") === "recent") {
    const [recent, total] = await db.batch([recentStmt, countStmt]);
    return json({ range, ...recentOut(recent, total) });
  }

  const [summary, ips, active, daily, versions, countries, top, players, names, recent, total] = await db.batch([
    db.prepare(`SELECT COALESCE(SUM(opens), 0) AS opens, COALESCE(SUM(matches), 0) AS matches,
                       COALESCE(SUM(new_installs), 0) AS newInstalls FROM day_total WHERE date >= ?1`).bind(fromDay),
    db.prepare("SELECT COUNT(DISTINCT ip) AS n FROM install_ip WHERE last_ts >= ?1").bind(from),
    db.prepare("SELECT COUNT(*) AS n FROM installs WHERE last_ts >= ?1").bind(from),
    db.prepare(`SELECT date, opens, installs, matches, new_installs AS newInstalls FROM day_total
                WHERE date >= ?1 ORDER BY date`).bind(fromDay),
    // máy dùng trong kỳ, theo phiên bản / nước hiện tại của máy (mỗi máy tính một lần)
    db.prepare(`SELECT version AS name, COUNT(*) AS value FROM installs WHERE last_ts >= ?1
                GROUP BY version ORDER BY value DESC LIMIT 10`).bind(from),
    db.prepare(`SELECT COALESCE(NULLIF(country, ''), '?') AS name, COUNT(*) AS value FROM installs WHERE last_ts >= ?1
                GROUP BY COALESCE(NULLIF(country, ''), '?') ORDER BY value DESC LIMIT 10`).bind(from),
    all
      ? db.prepare(`SELECT install, opens, matches, last_ip AS lastIp, version, app, country, first_ts AS firstSeen,
                           last_ts AS lastSeen, name,
                           (SELECT COUNT(*) FROM install_ip p WHERE p.install = i.install) AS ipCount
                    FROM installs i ORDER BY matches DESC, opens DESC, last_ts DESC LIMIT 20`)
      : db.prepare(`SELECT d.install AS install, SUM(d.opens) AS opens, SUM(d.matches) AS matches, i.last_ip AS lastIp,
                           i.version AS version, i.app AS app, i.country AS country, i.first_ts AS firstSeen,
                           i.last_ts AS lastSeen, i.name AS name,
                           (SELECT COUNT(*) FROM install_ip p WHERE p.install = d.install AND p.last_ts >= ?2) AS ipCount
                    FROM day_install d JOIN installs i ON i.install = d.install WHERE d.date >= ?1
                    GROUP BY d.install ORDER BY matches DESC, opens DESC, lastSeen DESC LIMIT 20`).bind(fromDay, from),
    // bảng xếp hạng số trận ghi theo tên người chơi + số tên khác nhau có trận trong kỳ
    all
      ? db.prepare("SELECT name, matches AS value FROM name_total ORDER BY matches DESC LIMIT 10")
      : db.prepare(`SELECT name, SUM(matches) AS value FROM day_name WHERE date >= ?1
                    GROUP BY name ORDER BY value DESC LIMIT 10`).bind(fromDay),
    all
      ? db.prepare("SELECT COUNT(*) AS n FROM name_total")
      : db.prepare("SELECT COUNT(DISTINCT name) AS n FROM day_name WHERE date >= ?1").bind(fromDay),
    recentStmt,
    countStmt,
  ]);
  const s = summary.results[0] || {};
  const opens = s.opens || 0;
  const fresh = s.newInstalls || 0;
  return json({
    range,
    summary: { opens, installs: active.results[0].n || 0, ips: ips.results[0].n || 0, matches: s.matches || 0,
               newInstalls: fresh, names: names.results[0].n || 0, returningOpens: Math.max(0, opens - fresh) },
    daily: daily.results,
    versions: versions.results,
    apps: [],                                  // ô Ứng dụng bỏ từ v6 (chỉ còn AoE-MapCap.exe)
    countries: countries.results,
    kinds: [{ name: "match", value: s.matches || 0 }, { name: "open", value: opens }]
      .filter((k) => k.value > 0).sort((x, y) => y.value - x.value),
    players: players.results,
    topInstalls: top.results,
    ...recentOut(recent, total),
  });
}

// ---------------------------------------------------------------------------------------------------------------
// Báo cáo trận có hack (2026-11-11): app gửi cả file .aoerec để admin xem lại trận, ai hack, hack gì.
const clean = (v, n) => String(v || "").replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, n);

async function reportUpload(request, env, url) {
  if (!env.REPORTS) return json({ ok: false, error: "máy chủ chưa bật lưu file (R2)" }, 503);
  const id = String(url.searchParams.get("id") || "");
  const version = clean(url.searchParams.get("v"), 16);
  const size = parseInt(request.headers.get("content-length") || "0", 10);
  if (!UUID.test(id) || !version) return json({ ok: false, error: "thiếu mã máy / phiên bản" }, 400);
  if (!(size > 16) || size > REPORT_MAX) return json({ ok: false, error: `file phải nhỏ hơn ${REPORT_MAX >> 20} MB` }, 413);
  const ip = request.headers.get("cf-connecting-ip") || "";
  const country = (request.cf && request.cf.country) || "";
  const now = Date.now();
  const db = env.DB;
  const lim = await db.prepare(`SELECT SUM(install = ?1) AS mine, SUM(ip = ?2) AS byip, COUNT(*) AS n FROM reports
                                WHERE ts > ?3`).bind(id, ip, now - 86400000).first();
  if (lim && (lim.n || 0) >= REPORT_ALL_PER_DAY)
    return json({ ok: false, error: "máy chủ đã nhận đủ báo cáo hôm nay, vui lòng gửi lại ngày mai" }, 429);
  if (lim && ((lim.mine || 0) >= REPORT_PER_DAY || (lim.byip || 0) >= REPORT_IP_PER_DAY))
    return json({ ok: false, error: `mỗi máy chỉ gửi được ${REPORT_PER_DAY} báo cáo mỗi ngày` }, 429);
  let meta = {};
  try {
    meta = JSON.parse(url.searchParams.get("meta") || "{}");
  } catch {
    meta = {};
  }
  const metaText = JSON.stringify(meta).slice(0, 8000);
  const store = Number(env.REPORT_STORE_TEST) || REPORT_STORE;   // biến chỉ dùng khi test cục bộ
  await trimReports(env, store - size);       // chừa chỗ cho file này trước khi lưu
  const key = `r/${new Date(now).toISOString().slice(0, 10)}/${now}-${id.slice(0, 8)}.aoerec`;
  // thân request đi thẳng vào R2 (không giữ cả file trong bộ nhớ Worker); kiểm chữ ký file sau khi lưu
  const obj = await env.REPORTS.put(key, request.body, { httpMetadata: { contentType: "application/octet-stream" } });
  const head = await env.REPORTS.get(key, { range: { offset: 0, length: 8 } });
  const magic = head ? new TextDecoder().decode(await head.arrayBuffer()) : "";
  if (magic !== "AOEREC01") {
    await env.REPORTS.delete(key);
    return json({ ok: false, error: "không phải file .aoerec" }, 400);
  }
  const stored = obj && obj.size ? obj.size : size;
  const row = await db.prepare(`INSERT INTO reports (ts, install, name, ip, country, version, file, size, r2key, suspect, note, meta)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id`)
    .bind(now, id, clean(url.searchParams.get("name"), 40) || null, ip, country, version,
          clean(url.searchParams.get("file"), 120), stored, key, clean(url.searchParams.get("suspect"), 120) || null,
          clean(url.searchParams.get("note"), 1000) || null, metaText).first();
  await trimReports(env, store, row.id);      // lượt gửi cùng lúc: dọn lại lần nữa
  return json({ ok: true, id: row.id });
}

// xoá file của báo cáo cũ nhất (dòng thông tin vẫn còn) tới khi tổng dung lượng trên R2 <= limit
async function trimReports(env, limit, keepId = null) {
  const db = env.DB;
  const tot = await db.prepare("SELECT COALESCE(SUM(size), 0) AS b FROM reports WHERE r2key IS NOT NULL").first();
  let over = (tot && tot.b || 0) - limit;
  while (over > 0) {
    const old = await db.prepare("SELECT id, r2key, size FROM reports WHERE r2key IS NOT NULL ORDER BY ts LIMIT 50").all();
    const rows = (old.results || []).filter((r) => r.id !== keepId);
    if (!rows.length) break;
    for (const r of rows) {
      if (over <= 0) break;
      await env.REPORTS.delete(r.r2key);
      await db.prepare("UPDATE reports SET r2key = NULL WHERE id = ?").bind(r.id).run();
      over -= r.size;
    }
    if (rows.length < 50) break;
  }
}

async function reportList(request, env) {
  if (!authorized(request, env)) return json({ error: "unauthorized" }, 401);
  const rows = await env.DB.prepare(`SELECT id, ts, install, name, ip, country, version, file, size, (r2key IS NOT NULL) AS hasFile,
                                            suspect, note, meta, status, admin_note
                                     FROM reports ORDER BY ts DESC LIMIT 200`).all();
  const tot = await env.DB.prepare("SELECT COUNT(*) AS n, COALESCE(SUM(CASE WHEN r2key IS NOT NULL THEN size END), 0) AS b FROM reports").first();
  const msgs = await msgsOf(env, (rows.results || []).map((r) => r.id));
  return json({ reports: (rows.results || []).map((r) => ({ ...r, meta: safeJson(r.meta), msgs: msgs.get(r.id) || [] })),
                total: tot.n, storedBytes: tot.b, storeLimit: REPORT_STORE, r2: !!env.REPORTS });
}

// ---- nhắn qua lại admin <-> người gửi báo cáo (2026-11-14) -------------------------------------------------------
const MSG_MAX = 1000;              // kí tự mỗi tin
const MSG_USER_PER_DAY = 30;       // tin người dùng gửi mỗi máy mỗi ngày

async function msgsOf(env, ids) {
  const out = new Map();
  for (let i = 0; i < ids.length; i += 50) {
    const part = ids.slice(i, i + 50);
    const rs = await env.DB.prepare(`SELECT id, report, ts, who, text FROM report_msgs WHERE report IN (${part.map(() => "?").join(",")})
                                     ORDER BY id`).bind(...part).all();
    for (const m of rs.results || []) {
      if (!out.has(m.report)) out.set(m.report, []);
      out.get(m.report).push({ id: m.id, ts: m.ts, who: m.who, text: m.text });
    }
  }
  return out;
}

// app: trạng thái + tin nhắn của các báo cáo do máy này gửi (mã máy là thứ xác nhận, như lúc gửi báo cáo)
async function reportStatus(env, url) {
  const install = String(url.searchParams.get("id") || "");
  if (!UUID.test(install)) return json({ ok: false, error: "thiếu mã máy" }, 400);
  const rows = await env.DB.prepare("SELECT id, status FROM reports WHERE install = ? ORDER BY ts DESC LIMIT 200").bind(install).all();
  const list = rows.results || [];
  const msgs = await msgsOf(env, list.map((r) => r.id));
  return json({ ok: true, reports: list.map((r) => ({ id: r.id, status: r.status, msgs: msgs.get(r.id) || [] })) });
}

// app: người gửi báo cáo trả lời admin
async function reportReply(request, env) {
  let b;
  try {
    b = await request.json();
  } catch {
    return json({ ok: false, error: "bad json" }, 400);
  }
  const install = String(b.id || "");
  const rid = parseInt(b.report || 0, 10);
  const text = String(b.text || "").replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, " ").trim().slice(0, MSG_MAX);
  if (!UUID.test(install) || !rid || !text) return json({ ok: false, error: "thiếu nội dung" }, 400);
  const r = await env.DB.prepare("SELECT id FROM reports WHERE id = ? AND install = ?").bind(rid, install).first();
  if (!r) return json({ ok: false, error: "không tìm thấy báo cáo của máy này" }, 404);
  const now = Date.now();
  const lim = await env.DB.prepare(`SELECT COUNT(*) AS n FROM report_msgs m JOIN reports r ON r.id = m.report
                                    WHERE r.install = ? AND m.who = 'user' AND m.ts > ?`).bind(install, now - 86400000).first();
  if (lim && (lim.n || 0) >= MSG_USER_PER_DAY) return json({ ok: false, error: "hôm nay đã gửi quá nhiều tin, vui lòng gửi lại ngày mai" }, 429);
  const row = await env.DB.prepare("INSERT INTO report_msgs (report, ts, who, text) VALUES (?, ?, 'user', ?) RETURNING id")
    .bind(rid, now, text).first();
  return json({ ok: true, msg: { id: row.id, ts: now, who: "user", text } });
}

// trang /stats: admin nhắn cho người gửi báo cáo
async function reportMessage(request, env) {
  if (!authorized(request, env)) return json({ error: "unauthorized" }, 401);
  let b;
  try {
    b = await request.json();
  } catch {
    return json({ error: "bad json" }, 400);
  }
  const rid = parseInt(b.id || 0, 10);
  const text = String(b.text || "").replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, " ").trim().slice(0, MSG_MAX);
  if (!rid || !text) return json({ error: "thiếu nội dung" }, 400);
  const now = Date.now();
  const row = await env.DB.prepare("INSERT INTO report_msgs (report, ts, who, text) VALUES (?, ?, 'admin', ?) RETURNING id")
    .bind(rid, now, text).first();
  return json({ ok: true, msg: { id: row.id, ts: now, who: "admin", text } });
}

function safeJson(t) {
  try {
    return JSON.parse(t || "{}");
  } catch {
    return {};
  }
}

async function reportFile(request, env, url) {
  if (!authorized(request, env)) return json({ error: "unauthorized" }, 401);
  const id = parseInt(url.searchParams.get("id") || "0", 10);
  const r = await env.DB.prepare("SELECT r2key, file FROM reports WHERE id = ?").bind(id).first();
  if (!r || !r.r2key || !env.REPORTS) return json({ error: "không còn file" }, 404);
  const obj = await env.REPORTS.get(r.r2key);
  if (!obj) return json({ error: "không còn file" }, 404);
  const name = (r.file || `bao-cao-${id}.aoerec`).replace(/[^\w.\-]/g, "_");
  return new Response(obj.body, { headers: { "content-type": "application/octet-stream", "cache-control": "no-store",
                                             "content-disposition": `attachment; filename="${name}"`,
                                             "content-length": String(obj.size) } });
}

async function reportUpdate(request, env) {
  if (!authorized(request, env)) return json({ error: "unauthorized" }, 401);
  let b;
  try {
    b = await request.json();
  } catch {
    return json({ error: "bad json" }, 400);
  }
  const id = parseInt(b.id || 0, 10);
  const status = STATUSES.has(b.status) ? b.status : "new";
  await env.DB.prepare("UPDATE reports SET status = ?, admin_note = ? WHERE id = ?")
    .bind(status, clean(b.admin_note, 2000) || null, id).run();
  return json({ ok: true });
}
