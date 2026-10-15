// Thống kê sử dụng AoE-MapCap: Cloudflare Worker + D1 (không server riêng, không tên miền riêng).
//   POST /v1/e            app gửi một lượt: {"id": mã máy UUID, "app": "mapcap"|"replay", "v": phiên bản, "ev": "open"|"match",
//                         "name": tên người chơi (nickname trong game, có thể rỗng / trùng; từ v7)}
//   GET  /stats           trang thống kê (đăng nhập bằng mật khẩu STATS_PASSWORD, đặt bằng `wrangler secret put`)
//   GET  /api/stats       số liệu cho trang thống kê (Authorization: Bearer <mật khẩu>)
// IP lấy từ CF-Connecting-IP (app kết nối bằng IPv4), nước từ request.cf.country. Ngày tính theo giờ Việt Nam.
import { DASHBOARD_HTML } from "./dashboard.js";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const APPS = new Set(["mapcap", "replay"]);
const EVENTS = new Set(["open", "match"]);
const VN = 7 * 3600 * 1000;               // giờ Việt Nam = UTC+7
const PAGE = 50;

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
                     "x-robots-tag": "noindex" },
        });
      }
      if (url.pathname === "/api/stats") return await stats(request, env, url);
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
  await db.batch([
    db.prepare("INSERT INTO events (ts, install, app, version, ev, ip, country, name) VALUES (?, ?, ?, ?, ?, ?, ?, ?)")
      .bind(now, id, app, version, ev, ip, country, name || null),
    db.prepare(
      `INSERT INTO installs (install, first_ts, last_ts, first_ip, last_ip, country, app, version, opens, matches, name)
       VALUES (?1, ?2, ?2, ?3, ?3, ?4, ?5, ?6, ?7, ?8, ?9)
       ON CONFLICT(install) DO UPDATE SET last_ts = ?2, last_ip = ?3, country = ?4, app = ?5, version = ?6,
         opens = opens + ?7, matches = matches + ?8, name = COALESCE(?9, name)`)
      .bind(id, now, ip, country, app, version, ev === "open" ? 1 : 0, ev === "match" ? 1 : 0, name || null),
  ]);
  return json({ ok: true });
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
  const from = rangeStart(range);
  const day = `strftime('%Y-%m-%d', (ts + ${VN}) / 1000, 'unixepoch')`;
  const like = "%" + q.replace(/[%_]/g, "") + "%";
  const qWhere = q ? " AND (e.ip LIKE ?2 OR e.install LIKE ?2 OR e.version LIKE ?2 OR e.name LIKE ?2 OR i.name LIKE ?2)" : "";

  const [summary, newInstalls, daily, versions, apps, countries, kinds, top, recent, recentTotal, players] = await db.batch([
    db.prepare(`SELECT SUM(ev = 'open') AS opens, SUM(ev = 'match') AS matches, COUNT(DISTINCT install) AS installs,
                       COUNT(DISTINCT ip) AS ips FROM events WHERE ts >= ?1`).bind(from),
    db.prepare("SELECT COUNT(*) AS n FROM installs WHERE first_ts >= ?1").bind(from),
    db.prepare(`SELECT ${day} AS date, SUM(ev = 'open') AS opens, COUNT(DISTINCT install) AS installs,
                       SUM(ev = 'match') AS matches FROM events WHERE ts >= ?1 GROUP BY date ORDER BY date`).bind(from),
    db.prepare(`SELECT version AS name, COUNT(DISTINCT install) AS value FROM events WHERE ts >= ?1
                GROUP BY version ORDER BY value DESC LIMIT 10`).bind(from),
    db.prepare(`SELECT app AS name, COUNT(*) AS value FROM events WHERE ts >= ?1 AND ev = 'open'
                GROUP BY app ORDER BY value DESC`).bind(from),
    db.prepare(`SELECT COALESCE(NULLIF(country, ''), '?') AS name, COUNT(DISTINCT install) AS value FROM events
                WHERE ts >= ?1 GROUP BY name ORDER BY value DESC LIMIT 10`).bind(from),
    db.prepare(`SELECT ev AS name, COUNT(*) AS value FROM events WHERE ts >= ?1 GROUP BY ev ORDER BY value DESC`).bind(from),
    db.prepare(`SELECT e.install AS install, SUM(e.ev = 'open') AS opens, SUM(e.ev = 'match') AS matches,
                       COUNT(DISTINCT e.ip) AS ipCount, i.last_ip AS lastIp, i.version AS version, i.app AS app,
                       i.country AS country, i.first_ts AS firstSeen, i.last_ts AS lastSeen, i.name AS name
                FROM events e JOIN installs i ON i.install = e.install WHERE e.ts >= ?1
                GROUP BY e.install ORDER BY opens DESC, lastSeen DESC LIMIT 20`).bind(from),
    db.prepare(`SELECT e.id, e.ts, e.install, e.app, e.version, e.ev, e.ip, e.country,
                       COALESCE(e.name, i.name) AS name, (e.ts = i.first_ts) AS isNew
                FROM events e JOIN installs i ON i.install = e.install
                WHERE e.ts >= ?1${qWhere} ORDER BY e.ts DESC LIMIT ${PAGE} OFFSET ${(page - 1) * PAGE}`)
      .bind(...(q ? [from, like] : [from])),
    db.prepare(`SELECT COUNT(*) AS n FROM events e JOIN installs i ON i.install = e.install WHERE e.ts >= ?1${qWhere}`)
      .bind(...(q ? [from, like] : [from])),
    db.prepare(`SELECT pname AS name, COUNT(*) AS value FROM (
                  SELECT COALESCE(NULLIF(i.name, ''), '(chưa biết)') AS pname
                  FROM events e JOIN installs i ON i.install = e.install WHERE e.ts >= ?1 AND e.ev = 'open')
                GROUP BY pname ORDER BY value DESC LIMIT 10`).bind(from),
  ]);
  const s = summary.results[0] || {};
  const opens = s.opens || 0;
  const fresh = newInstalls.results[0].n || 0;
  return json({
    range,
    summary: { opens, installs: s.installs || 0, ips: s.ips || 0, matches: s.matches || 0, newInstalls: fresh,
               returningOpens: Math.max(0, opens - fresh) },
    daily: daily.results,
    versions: versions.results,
    apps: apps.results,
    countries: countries.results,
    kinds: kinds.results,
    players: players.results,
    topInstalls: top.results,
    recent: recent.results,
    recentTotal: recentTotal.results[0].n || 0,
    page,
    pageSize: PAGE,
    updatedAt: Date.now(),
  });
}
