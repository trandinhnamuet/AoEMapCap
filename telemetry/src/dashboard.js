// Trang thống kê sử dụng AoE-MapCap: theo phong cách trang "Nhật ký truy cập" của trecome-nextjs (/admin/visitors):
// Space Grotesk / Be Vietnam Pro / JetBrains Mono, xanh #0A66FF, thẻ trắng viền #E8E8E8, chip dạng viên thuốc,
// 6 ô KPI, biểu đồ đường theo ngày (2 đường #2a78d6 / #eb6834), danh sách thanh, bảng tìm kiếm + phân trang 50 dòng.
// Không dùng dấu ` hay ${ trong phần script của trang (cả trang nằm trong một template literal).
export const DASHBOARD_HTML = `<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Thống kê AoE-MapCap</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600&family=JetBrains+Mono:wght@400;500&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js" integrity="sha384-bs/nf9FbdNouRbMiFcrcZfLXYPKiPaGVGplVbv7dLGECccEXDW+S3zjqSKR5ZEaD" crossorigin="anonymous" referrerpolicy="no-referrer"></script>
<style>
:root{
  --blue:#0A66FF;--blue-600:#0556DA;--blue-700:#043FA8;--blue-50:#EAF2FF;
  --ink:#0A0A0A;--ink-2:#1A1A1A;--ink-3:#3D3D3D;--muted:#6B6B6B;--muted-2:#9A9A9A;
  --line:#E8E8E8;--line-2:#F0F0F0;--bg:#FFFFFF;--bg-soft:#FAFAFA;
  --r-sm:8px;--r-md:12px;--r-lg:20px;--r-pill:999px;
  --shadow-sm:0 1px 2px rgba(10,10,10,.04),0 1px 1px rgba(10,10,10,.03);
  --shadow-md:0 8px 24px rgba(10,10,10,.06),0 2px 6px rgba(10,10,10,.04);
  --f-display:"Space Grotesk","Be Vietnam Pro",system-ui,sans-serif;
  --f-body:"Be Vietnam Pro","Space Grotesk",system-ui,sans-serif;
  --f-mono:"JetBrains Mono",ui-monospace,monospace;
  --s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#8b5cf6;
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg-soft);color:var(--ink-2);font-family:var(--f-body)}
.an-root{min-height:100vh;padding:32px 0 80px}
.an-wrap{max-width:1240px;margin:0 auto;padding:0 24px}
.an-head{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap;margin-bottom:28px}
.an-head h1{font-family:var(--f-display);font-size:32px;line-height:1.15;margin:0 0 6px;color:var(--ink)}
.an-head p{margin:0;font-size:14px;color:var(--muted)}
.an-actions{display:flex;gap:8px;flex-wrap:wrap}
.an-btn,.an-chip{background:#fff;border:1px solid var(--line);border-radius:var(--r-pill);padding:9px 18px;font-size:14px;
  color:var(--ink-3);cursor:pointer;font-family:var(--f-body);text-decoration:none}
.an-btn:hover,.an-chip:hover{border-color:#cfd9e8}
.an-btn:disabled{opacity:.5;cursor:default}
.an-chip[aria-pressed=true]{background:var(--blue);border-color:var(--blue);color:#fff;font-weight:600}
.an-filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px}
.an-banner{background:#fff6f5;border:1px solid #f3c8c2;color:#8c2f22;border-radius:var(--r-md);padding:14px 18px;margin-bottom:18px;font-size:14px}
.an-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin-bottom:14px}
.an-kpi{background:#fff;border:1px solid var(--line);border-radius:var(--r-md);padding:20px;box-shadow:var(--shadow-sm)}
.an-kpi .l{font-size:13px;color:var(--muted)}
.an-kpi .v{font-family:var(--f-display);font-size:30px;letter-spacing:-.01em;margin:6px 0 4px;color:var(--ink)}
.an-kpi .h{font-size:12.5px;color:var(--muted-2)}
.an-card{background:#fff;border:1px solid var(--line);border-radius:var(--r-md);padding:22px;box-shadow:var(--shadow-sm);margin-bottom:14px;min-width:0}
.an-card h2{font-family:var(--f-display);font-size:17px;margin:0 0 2px;color:var(--ink)}
.an-hint{font-size:12.5px;color:var(--muted-2);margin-bottom:18px}
.an-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(320px,100%),1fr));gap:14px;margin-bottom:0}
details.an-card{padding:0}
details.an-card>summary{list-style:none;cursor:pointer;padding:22px;display:flex;justify-content:space-between;align-items:center;gap:12px}
details.an-card>summary::-webkit-details-marker{display:none}
details.an-card>summary .an-hint{margin-bottom:0}
details.an-card>summary:hover h2{color:var(--blue-700)}
.an-caret{flex:none;width:32px;height:32px;border:1px solid var(--line);border-radius:var(--r-pill);display:grid;place-items:center;
  color:var(--muted);font-size:14px;transition:transform .15s}
details[open] .an-caret{transform:rotate(180deg)}
details.an-card .an-fold{padding:0 22px 22px}
.an-legend{display:flex;gap:18px;font-size:13px;color:var(--ink-3);margin-bottom:10px}
.an-legend i{display:inline-block;width:12px;height:3px;border-radius:2px;vertical-align:middle;margin-right:6px}
.an-chart{position:relative;height:300px}
.bl{display:flex;flex-direction:column;gap:2px}
.bl .row{position:relative;display:flex;justify-content:space-between;gap:12px;padding:10px 12px;border-radius:var(--r-sm);font-size:13.5px;overflow:hidden}
.bl .row::before{content:"";position:absolute;inset:0 auto 0 0;width:var(--w);background:color-mix(in srgb,var(--s1) 14%,transparent);border-radius:0 4px 4px 0}
.bl .row:hover::before{background:color-mix(in srgb,var(--s1) 22%,transparent)}
.bl .row span{position:relative}
.bl .name{color:var(--ink-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bl .val{font-family:var(--f-mono);font-size:12.5px;white-space:nowrap}
.bl .val em{font-style:normal;color:var(--muted-2);margin-left:6px}
.an-empty{text-align:center;color:var(--muted);padding:18px 0;font-size:13.5px}
.an-tablewrap{overflow-x:auto}
.an-reports{white-space:normal}.an-reports td{vertical-align:top}.an-reports td[data-l="Trận"]{min-width:200px;max-width:280px}
.an-reports td[data-l="Nghi ai"],.an-reports td[data-l="App phát hiện"]{max-width:240px}.rp-dl{white-space:nowrap}.rp-admin{min-width:210px}.rp-admin .an-field{width:100%;box-sizing:border-box;margin:0 0 6px}
table{width:100%;border-collapse:collapse;font-size:13px;white-space:nowrap}
th{text-align:left;font-size:12px;text-transform:uppercase;letter-spacing:.03em;font-weight:600;color:var(--muted-2);padding:0 14px 10px 0;border-bottom:1px solid var(--line)}
td{padding:11px 14px 11px 0;border-bottom:1px solid var(--line-2);color:var(--ink-2);vertical-align:top}
tr:hover td{background:var(--bg-soft)}
.mono{font-family:var(--f-mono);font-size:12.5px}
.dim{color:var(--muted-2)}
td small{display:block;font-size:11.5px;color:var(--muted-2)}
.an-tag{display:inline-block;padding:2px 9px;border-radius:var(--r-pill);font-size:11.5px;font-weight:600;margin-left:6px}
.an-tag.new{background:#e8f6ee;color:#0f7a4d}.an-tag.back{background:var(--blue-50);color:var(--blue-700)}
.an-tag.match{background:#fff1e8;color:#a5481a}
th.an-sort{cursor:pointer;user-select:none;white-space:nowrap}
th.an-sort:hover{color:var(--ink-3)}
th.an-sort[aria-sort]{color:var(--blue-700)}
th.an-sort .ar{display:inline-block;margin-left:4px;font-size:10px;color:var(--blue)}
.an-sortbar{display:none;align-items:center;gap:8px;margin:0 0 6px;font-size:13px;color:var(--muted)}
.an-sortbar select{border:1px solid var(--line);border-radius:var(--r-pill);padding:6px 12px;font:inherit;color:var(--ink-2);background:#fff}
.an-tablehead{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}
.an-search{flex:1 1 240px;max-width:360px;border:1px solid var(--line);border-radius:var(--r-pill);padding:9px 16px;font-size:14px;font-family:var(--f-body);outline:none}
.an-search:focus,.an-field:focus{border-color:var(--blue)}
.an-pager{display:flex;align-items:center;justify-content:flex-end;gap:12px;margin-top:14px;font-size:13px;color:var(--muted)}
.an-state{max-width:620px;margin:80px auto;background:#fff;border:1px solid var(--line);border-radius:var(--r-lg);padding:40px;box-shadow:var(--shadow-md)}
.an-state h1{font-family:var(--f-display);font-size:26px;margin:0 0 8px}
.an-state p{color:var(--muted);font-size:14px;margin:0 0 20px}
.an-field{width:100%;padding:14px 16px;border:1px solid var(--line);border-radius:var(--r-sm);font-size:15px;font-family:var(--f-body);outline:none;margin-bottom:12px}
.an-submit{width:100%;padding:14px;border:0;border-radius:var(--r-sm);background:var(--blue);color:#fff;font-weight:600;font-size:15px;cursor:pointer;font-family:var(--f-body)}
.an-submit:hover{background:var(--blue-600)}
.an-err{color:#c0392b;font-size:13.5px;margin-top:10px;min-height:1em}
.sk{height:120px;border-radius:var(--r-md);margin-bottom:14px;background:linear-gradient(90deg,var(--line-2) 25%,#f7f7f7 50%,var(--line-2) 75%);background-size:200% 100%;animation:sh 1.4s infinite}
@keyframes sh{0%{background-position:200% 0}100%{background-position:-200% 0}}
@media (max-width:640px){
  .an-root{padding:18px 0 48px}
  .an-wrap{padding:0 16px}
  .an-head{margin-bottom:16px;align-items:flex-start}
  .an-head h1{font-size:24px}
  .an-head p{font-size:13px}
  .an-btn,.an-chip{padding:8px 14px;font-size:13.5px}
  .an-filters{flex-wrap:nowrap;overflow-x:auto;margin:0 -16px 14px;padding:0 16px 2px;scrollbar-width:none}
  .an-filters::-webkit-scrollbar{display:none}
  .an-chip{flex:none}
  .an-kpis{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
  .an-kpi{padding:14px}
  .an-kpi .l{font-size:12.5px}
  .an-kpi .v{font-size:24px;margin:4px 0 2px}
  .an-kpi .h{font-size:11.5px}
  .an-card{padding:16px}
  details.an-card>summary{padding:16px}
  details.an-card .an-fold{padding:0 16px 16px}
  .an-chart{height:230px}
  .an-legend{flex-wrap:wrap;gap:6px 14px;font-size:12.5px}
  .an-search{max-width:none;flex-basis:100%}
  .an-pager{justify-content:space-between}
  .an-kpis .an-kpi:last-child:nth-child(odd){grid-column:1/-1}
  /* bảng thành thẻ: mỗi hàng một khối, không cuộn ngang */
  .an-sortbar{display:flex}
  .an-tablewrap{overflow:visible}
  table,tbody,tr,td{display:block;width:auto}
  thead{display:none}
  table{white-space:normal}
  tr{padding:10px 0;border-bottom:1px solid var(--line)}
  tr:hover td{background:none}
  td{padding:0;border:0}
  td small{display:inline;margin-left:6px}
  td.an-empty{text-align:center;padding:14px 0}
  td.lead{font-weight:600;font-size:14.5px;color:var(--ink)}
  /* Máy dùng nhiều nhất: tên trên cùng, các ô còn lại 2 cột (nhãn nhỏ trên giá trị) */
  .an-top tr{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 14px}
  .an-top td::before{content:attr(data-l);display:block;color:var(--muted-2);font-size:11.5px;margin-bottom:1px;
    font-family:var(--f-body);font-weight:400}
  .an-top td.lead,.an-top td.an-empty{grid-column:1/-1}
  .an-top td.lead::before,.an-top td.an-empty::before{content:none}
  /* Từng lượt: dòng 1 tên + mã máy + nhãn, dòng 2 thời điểm · IP · phiên bản · sự kiện · quốc gia */
  .an-recent tr{display:flex;flex-wrap:wrap;align-items:baseline;gap:3px 12px}
  .an-recent td{font-size:12.5px}
  .an-recent td.lead{flex-basis:100%;font-size:14px}
  .an-recent td.an-empty{flex-basis:100%}
  .an-recent td[data-l="Ứng dụng"]{display:none}
  .an-state{margin:24px 16px;padding:24px}
}
</style>
</head>
<body>
<div class="an-root"><div class="an-wrap" id="app">
  <div class="sk"></div><div class="sk" style="height:340px"></div>
</div></div>
<script>
(function () {
  var KEY = "aoe_stats_pw";
  var state = { range: "7d", page: 1, q: "", data: null, loading: false, chart: null, topOpen: false,
                tSort: { key: "matches", dir: "desc" }, rSort: { key: "ts", dir: "desc" } };
  // cột của hai bảng: [khoá, nhãn, kiểu] - chữ: bấm lần đầu xếp A-Z, số / thời gian: lớn trước
  var TOP_COLS = [["name", "Người chơi", "text"], ["matches", "Trận ghi", "num"], ["opens", "Lượt mở", "num"],
                  ["install", "Mã máy", "text"], ["lastIp", "IP gần nhất", "ip"], ["version", "Phiên bản", "num"],
                  ["firstSeen", "Lần đầu", "num"], ["lastSeen", "Lần cuối", "num"]];
  var REC_COLS = [["ts", "Thời điểm", "num"], ["ip", "IP", "text"], ["name", "Máy", "text"], ["app", "Ứng dụng", "text"],
                  ["version", "Phiên bản", "num"], ["ev", "Sự kiện", "text"], ["country", "Quốc gia", "text"]];
  function colOf(cols, key) { for (var k = 0; k < cols.length; k++) if (cols[k][0] === key) return cols[k]; return cols[0]; }
  function sortHead(cols, cur, table) {
    return cols.map(function (c) {
      var on = c[0] === cur.key;
      return '<th class="an-sort" data-t="' + table + '" data-k="' + c[0] + '"' +
        (on ? ' aria-sort="' + (cur.dir === "asc" ? "ascending" : "descending") + '"' : '') + ' title="Bấm để sắp xếp">' +
        c[1] + (on ? '<span class="ar">' + (cur.dir === "asc" ? "▲" : "▼") + '</span>' : '') + '</th>';
    }).join("");
  }
  function sortBar(cols, cur, table) {          // điện thoại: không có hàng tiêu đề -> ô chọn
    return '<div class="an-sortbar">Sắp xếp <select data-t="' + table + '">' + cols.map(function (c) {
      return ['desc', 'asc'].map(function (d) {
        var sel = c[0] === cur.key && d === cur.dir;
        return '<option value="' + c[0] + ' ' + d + '"' + (sel ? ' selected' : '') + '>' + c[1] + ' ' + (d === "asc" ? "↑" : "↓") + '</option>';
      }).join("");
    }).join("") + '</select></div>';
  }
  function sortWord(cols, cur) {
    var c = colOf(cols, cur.key);
    return "xếp theo " + c[1].toLowerCase() + " " + (cur.dir === "asc" ? (c[2] === "text" ? "A→Z" : "tăng dần") :
                                                      (c[2] === "text" ? "Z→A" : "giảm dần"));
  }
  function ipKey(ip) {
    var p = String(ip || "").split(".");
    return p.length === 4 ? p.map(function (x) { return ("00" + x).slice(-3); }).join(".") : String(ip || "");
  }
  function sortTop(rows) {
    var c = colOf(TOP_COLS, state.tSort.key), sign = state.tSort.dir === "asc" ? 1 : -1;
    function val(r) {
      var v = r[c[0]];
      if (c[2] === "num") return Number(v) || 0;
      if (c[2] === "ip") return ipKey(v);
      return String(v || "").toLocaleLowerCase("vi");
    }
    return rows.slice().sort(function (a, b) {
      var x = val(a), y = val(b);
      var d = typeof x === "number" ? x - y : x.localeCompare(y, "vi");
      return d ? d * sign : (b.matches - a.matches) || (b.opens - a.opens);
    });
  }
  var app = document.getElementById("app");
  var fmt = new Intl.NumberFormat("vi-VN");
  var TZ = "Asia/Ho_Chi_Minh";
  // nhớ mật khẩu trên trình duyệt này (localStorage): nhập một lần mỗi máy; Đăng xuất hoặc sai mật khẩu thì xoá
  function pw() { try { return localStorage.getItem(KEY) || ""; } catch (e) { return ""; } }
  function setPw(v) { try { if (v) localStorage.setItem(KEY, v); else localStorage.removeItem(KEY); } catch (e) {} }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function dt(ms, withYear) {
    // "dd/mm/yyyy HH:MM" (bảng máy) hoặc "dd/mm HH:MM:SS" (từng lượt), giờ Việt Nam
    if (!ms) return "";
    var p = {};
    new Intl.DateTimeFormat("en-GB", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit",
      minute: "2-digit", second: "2-digit", hour12: false }).formatToParts(new Date(ms)).forEach(function (x) { p[x.type] = x.value; });
    return withYear ? p.day + "/" + p.month + "/" + p.year + " " + p.hour + ":" + p.minute
                    : p.day + "/" + p.month + " " + p.hour + ":" + p.minute + ":" + p.second;
  }
  function appName(a) { return a === "mapcap" ? "AoE-MapCap" : a === "replay" ? "AoE-Replay" : a; }
  function evName(e) { return e === "open" ? "Mở app" : e === "match" ? "Ghi xong trận" : e; }

  function login(msg) {
    app.innerHTML = '<div class="an-state"><h1>Thống kê sử dụng AoE-MapCap</h1>' +
      '<p>Nhập mật khẩu trang thống kê. Trình duyệt này sẽ nhớ, lần sau không cần nhập lại (bấm Đăng xuất để quên).</p>' +
      '<form id="lf"><input class="an-field" id="lp" type="password" placeholder="Mật khẩu" autofocus>' +
      '<button class="an-submit">Đăng nhập</button><div class="an-err">' + esc(msg || "") + '</div></form></div>';
    document.getElementById("lf").onsubmit = function (e) {
      e.preventDefault(); setPw(document.getElementById("lp").value); load();
    };
  }

  // recentOnly: tìm / sắp xếp / chuyển trang chỉ lấy lại bảng Từng lượt (part=recent), giữ nguyên phần còn lại
  // của trang - đỡ tốn hạn mức đọc D1 (mỗi lần lấy cả trang chạy ~10 truy vấn)
  function load(recentOnly) {
    if (!pw()) return login();
    if (recentOnly && !state.data) recentOnly = false;
    state.loading = true; paintBusy();
    var u = "/api/stats?range=" + encodeURIComponent(state.range) + "&page=" + state.page +
            "&sort=" + encodeURIComponent(state.rSort.key) + "&dir=" + state.rSort.dir +
            "&q=" + encodeURIComponent(state.q) + (recentOnly ? "&part=recent" : "");
    fetch(u, { headers: { authorization: "Bearer " + pw() } }).then(function (r) {
      if (r.status === 401) { setPw(""); throw { login: true }; }
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || r.status); return j; });
    }).then(function (j) {
      if (recentOnly) {
        ["recent", "recentTotal", "recentCapped", "page", "pageSize", "sort", "dir", "updatedAt"].forEach(function (k) {
          state.data[k] = j[k];
        });
      } else {
        state.data = j;
        loadReports();
      }
      state.error = null; state.loading = false; render();
    })
      .catch(function (e) {
        state.loading = false;
        if (e && e.login) return login("Sai mật khẩu.");
        state.error = String(e && e.message || e); render();
      });
  }
  // báo cáo trận có hack (app gửi file .aoerec; /api/reports): admin xem, tải file, đánh dấu ai hack / hack gì
  function loadReports() {
    fetch("/api/reports", { headers: { authorization: "Bearer " + pw() } }).then(function (r) { return r.json(); })
      .then(function (j) { state.reports = j; render(); })
      .catch(function (e) { state.reports = { error: String(e && e.message || e) }; render(); });
  }
  var REPORT_STATUS = [["new", "Chưa xem"], ["hack", "Có hack"], ["clean", "Không hack"], ["unsure", "Chưa chắc"]];
  function mb(b) { return (b / 1048576).toLocaleString("vi-VN", { maximumFractionDigits: 1 }) + " MB"; }
  function reportsCard() {
    var R = state.reports;
    if (!R) return '<div class="an-card"><h2>Báo cáo hack</h2><div class="an-hint">Đang tải…</div></div>';
    if (R.error) return '<div class="an-card"><h2>Báo cáo hack</h2><div class="an-banner">' + esc(R.error) + '</div></div>';
    var rows = R.reports || [];
    var h = '<div class="an-card" id="reports"><h2>Báo cáo hack</h2><div class="an-hint">Người chơi bấm "Báo cáo hack" ở một trận ' +
      'trong app: file trận lưu trên Cloudflare R2 (' + mb(R.storedBytes || 0) + ' / ' + mb(R.storeLimit || 0) +
      ', đầy thì xoá file cũ nhất) · ' + fmt.format(R.total || 0) + ' báo cáo' +
      (R.r2 ? '' : ' · <b>máy chủ chưa bật R2</b>') + ' · tải file rồi mở bằng AoE-MapCap (Xem replay) để xem ai hack, hack gì</div>' +
      '<div class="an-tablewrap"><table class="an-recent an-reports"><thead><tr><th>Thời điểm</th><th>Người báo</th><th>Trận</th>' +
      '<th>Nghi ai / ghi chú</th><th>App tự phát hiện</th><th>File</th><th>Admin đánh dấu</th></tr></thead><tbody>';
    h += rows.length ? rows.map(function (r) {
      var m = r.meta || {};
      var auto = (m.hack || []).map(function (e) { return esc(e.name) + ': ' + esc(e.label) + (e.detail ? ' <small>(' + esc(e.detail) + ')</small>' : ''); }).join('<br>');
      var players = (m.players || []).map(function (p) { return esc(p.name) + (p.civ ? ' (' + esc(p.civ) + ')' : ''); }).join(' · ');
      return '<tr data-id="' + r.id + '"><td class="dim" data-l="Thời điểm">' + dt(r.ts, true) + '</td><td class="lead" data-l="Người báo"><span>' +
        esc(r.name || '(chưa biết)') + ' <span class="mono dim" title="' + esc(r.install) + '">' + esc(String(r.install).slice(0, 8)) + '</span>' +
        '<small>v' + esc(r.version) + (r.country ? ' · ' + esc(r.country) : '') + '</small></span></td><td data-l="Trận"><span>' +
        esc(m.map || '') + (m.duration ? ' · ' + esc(m.duration) : '') + '<small>' + players + '</small></span></td>' +
        '<td data-l="Nghi ai"><span><b>' + esc(r.suspect || '') + '</b><small>' + esc(r.note || '') + '</small></span></td>' +
        '<td data-l="App phát hiện">' + (auto || '<span class="dim">không</span>') + '</td>' +
        '<td data-l="File" title="' + esc(r.file || '') + '">' + (r.hasFile ? '<button class="an-btn rp-dl" data-id="' + r.id + '">Tải ' + mb(r.size) + '</button>'
                                          : '<span class="dim">đã xoá</span>') + '</td>' +
        '<td data-l="Admin" class="rp-admin"><select class="an-field rp-st">' + REPORT_STATUS.map(function (s) {
          return '<option value="' + s[0] + '"' + (r.status === s[0] ? ' selected' : '') + '>' + s[1] + '</option>'; }).join('') +
        '</select><textarea class="an-field rp-note" rows="2" placeholder="Ai hack, hack gì (để thêm luật)">' + esc(r.admin_note || '') +
        '</textarea><button class="an-btn rp-save">Lưu</button></td></tr>';
    }).join('') : '<tr><td colspan="7" class="an-empty">Chưa có báo cáo nào</td></tr>';
    return h + '</tbody></table></div></div>';
  }
  function bindReports() {
    Array.prototype.forEach.call(document.querySelectorAll(".rp-dl"), function (b) {
      b.onclick = function () {
        var id = b.getAttribute("data-id"); b.disabled = true; b.textContent = "Đang tải…";
        fetch("/api/report/file?id=" + id, { headers: { authorization: "Bearer " + pw() } }).then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          var cd = r.headers.get("content-disposition") || "", m = /filename="([^"]+)"/.exec(cd);
          return r.blob().then(function (bl) { return [bl, m ? m[1] : "bao-cao-" + id + ".aoerec"]; });
        }).then(function (x) {
          var a = document.createElement("a"); a.href = URL.createObjectURL(x[0]); a.download = x[1];
          document.body.appendChild(a); a.click(); a.remove();
          setTimeout(function () { URL.revokeObjectURL(a.href); }, 60000);
          b.disabled = false; b.textContent = "Đã tải";
        }).catch(function (e) { b.disabled = false; b.textContent = "Lỗi: " + (e && e.message || e); });
      };
    });
    Array.prototype.forEach.call(document.querySelectorAll(".rp-save"), function (b) {
      b.onclick = function () {
        var tr = b.closest("tr");
        b.disabled = true; b.textContent = "Đang lưu…";
        fetch("/api/report/update", { method: "POST", headers: { authorization: "Bearer " + pw(), "content-type": "application/json" },
          body: JSON.stringify({ id: Number(tr.getAttribute("data-id")), status: tr.querySelector(".rp-st").value,
                                 admin_note: tr.querySelector(".rp-note").value }) })
          .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); b.disabled = false; b.textContent = "Đã lưu"; })
          .catch(function (e) { b.disabled = false; b.textContent = "Lỗi: " + (e && e.message || e); });
      };
    });
  }
  function paintBusy() { var b = document.getElementById("rf"); if (b) { b.disabled = true; b.textContent = "Đang tải…"; } }

  function kpi(l, v, h) {
    return '<div class="an-kpi"><div class="l">' + l + '</div><div class="v">' + fmt.format(v || 0) +
           '</div><div class="h">' + h + '</div></div>';
  }
  // thứ hạng trước tên: 3 người đầu là huy chương
  function ranked(rows) {
    var medal = ["\ud83e\udd47 ", "\ud83e\udd48 ", "\ud83e\udd49 "];
    return rows.map(function (r, k) { return { name: (medal[k] || (k + 1) + ". ") + r.name, value: r.value }; });
  }
  function barList(title, hint, rows, unit, label) {
    var max = 0, tot = 0;
    rows.forEach(function (r) { max = Math.max(max, r.value); tot += r.value; });
    var body = rows.length ? rows.map(function (r) {
      var w = max ? (r.value / max * 100) : 0;
      var pct = tot ? Math.round(r.value / tot * 100) : 0;
      return '<div class="row" style="--w:' + w.toFixed(1) + '%"><span class="name">' + esc(label ? label(r.name) : r.name) +
             '</span><span class="val">' + fmt.format(r.value) + ' ' + unit + '<em>' + pct + '%</em></span></div>';
    }).join("") : '<div class="an-empty">Chưa có dữ liệu trong kỳ này</div>';
    return '<div class="an-card"><h2>' + title + '</h2><div class="an-hint">' + hint + '</div><div class="bl">' + body + '</div></div>';
  }

  function render() {
    var d = state.data;
    var ranges = [["today", "Hôm nay"], ["7d", "7 ngày"], ["28d", "28 ngày"], ["90d", "90 ngày"], ["all", "Tất cả"]];
    var h = '<div class="an-head"><div><h1>Thống kê sử dụng <span style="white-space:nowrap">AoE-MapCap</span></h1><p>Mỗi lần mở app có mạng gửi một lượt ' +
      '(mã máy ngẫu nhiên, tên người chơi, phiên bản, IP) · lưu trên Cloudflare D1' +
      (d ? ' · cập nhật ' + new Intl.DateTimeFormat("vi-VN", { timeZone: TZ, hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date(d.updatedAt)) : '') +
      '</p></div><div class="an-actions"><button class="an-btn" id="rf">Làm mới</button>' +
      '<button class="an-btn" id="lo">Đăng xuất</button></div></div>';
    if (state.error) h += '<div class="an-banner"><b>Không lấy được số liệu.</b> ' + esc(state.error) + '</div>';
    h += '<div class="an-filters">' + ranges.map(function (r) {
      return '<button class="an-chip" data-r="' + r[0] + '" aria-pressed="' + (state.range === r[0]) + '">' + r[1] + '</button>';
    }).join("") + '</div>';
    if (d) {
      var s = d.summary;
      h += '<div class="an-kpis">' +
        kpi("Lượt mở app", s.opens, "tổng số lần mở AoE-MapCap / AoE-Replay") +
        kpi("Máy duy nhất", s.installs, "đếm theo mã máy") +
        kpi("Tên trong game", s.names, "nickname có trận ghi") +
        kpi("Địa chỉ IP", s.ips, "số IP khác nhau") +
        kpi("Trận đã ghi", s.matches, "AoE-MapCap ghi xong") +
        kpi("Máy mới", s.newInstalls, "lần đầu dùng app") +
        kpi("Lượt quay lại", s.returningOpens, "lượt mở của máy đã dùng") + '</div>';
      h += '<div class="an-card"><h2>Diễn biến theo ngày</h2><div class="an-hint">' +
        (d.daily.length < 2 ? 'Mới có dữ liệu của một ngày — cần từ hai ngày trở lên mới vẽ được đường' :
         'Một máy có thể mở app nhiều lần') + '</div>' +
        '<div class="an-legend"><span><i style="background:var(--s1)"></i>Lượt mở app</span>' +
        '<span><i style="background:var(--s2)"></i>Máy duy nhất</span><span><i style="background:var(--s3)"></i>Trận đã ghi</span>' +
        '<span><i style="background:var(--s4)"></i>Máy mới</span></div>' +
        '<div class="an-chart"><canvas id="ch"></canvas></div></div>';
      // từ v6 chỉ còn AoE-MapCap.exe: bỏ ô "Ứng dụng", xếp 2 hàng (Người chơi, Phiên bản) / (Quốc gia, Loại sự kiện)
      h += '<div class="an-grid">' + barList("Bảng xếp hạng", "Số trận ghi trong kỳ theo tên người chơi (nickname, cho phép trùng) · top 10",
        ranked(d.players || []), "trận") +
        barList("Phiên bản", "Máy dùng trong kỳ, theo phiên bản hiện tại của máy", d.versions, "máy", function (n) { return "v" + n; }) + '</div>';
      h += '<div class="an-grid">' + barList("Quốc gia", "Máy dùng trong kỳ, theo Cloudflare", d.countries, "máy") +
        barList("Loại sự kiện", "Mở app / ghi xong trận", d.kinds, "lượt", evName) + '</div>';
      // xếp theo số trận ghi (chỉ số quan trọng nhất), mặc định gập; mở / gập được nhớ qua các lần tải lại
      h += '<details class="an-card" id="top"' + (state.topOpen ? ' open' : '') + '><summary><div><h2>Máy dùng nhiều nhất</h2>' +
        '<div class="an-hint">Top 20 theo số trận ghi trong kỳ · ' + sortWord(TOP_COLS, state.tSort) + ' · bấm để ' +
        (state.topOpen ? 'gập' : 'mở') + '</div></div><span class="an-caret">▾</span></summary>' +
        '<div class="an-fold">' + sortBar(TOP_COLS, state.tSort, "top") + '<div class="an-tablewrap"><table class="an-top"><thead><tr>' +
        sortHead(TOP_COLS, state.tSort, "top") + '</tr></thead><tbody>' +
        (d.topInstalls.length ? sortTop(d.topInstalls).map(function (r) {
          return '<tr><td class="lead" data-l="Người chơi">' + (r.name ? esc(r.name) : '<span class="dim">(chưa biết)</span>') +
            '</td><td data-l="Trận ghi"><b>' + fmt.format(r.matches) + '</b></td><td data-l="Lượt mở">' + fmt.format(r.opens) +
            '</td><td class="mono" data-l="Mã máy" title="' + esc(r.install) + '">' + esc(r.install.slice(0, 8)) +
            '</td><td class="mono" data-l="IP gần nhất"><span>' + esc(r.lastIp) +
            (r.ipCount > 1 ? '<small>' + r.ipCount + ' IP khác nhau</small>' : '') + '</span></td><td data-l="Phiên bản"><span>v' + esc(r.version) +
            '<small>' + esc(appName(r.app)) + (r.country ? ' · ' + esc(r.country) : '') + '</small></span></td><td class="dim" data-l="Lần đầu">' +
            dt(r.firstSeen, true) + '</td><td class="dim" data-l="Lần cuối">' + dt(r.lastSeen, true) + '</td></tr>';
        }).join("") : '<tr><td colspan="8" class="an-empty">Chưa có dữ liệu trong kỳ này</td></tr>') + '</tbody></table></div></div></details>';
      var pages = Math.max(1, Math.ceil(d.recentTotal / d.pageSize));
      h += '<div class="an-card"><div class="an-tablehead"><div><h2>Từng lượt</h2><div class="an-hint">' +
        (state.rSort.key === "ts" && state.rSort.dir === "desc" ? "Mới nhất trước" : sortWord(REC_COLS, state.rSort)) + ' · ' +
        (d.recentCapped ? 'hơn ' : '') + fmt.format(d.recentTotal) + ' bản ghi</div></div><input class="an-search" id="sq" placeholder="Tìm theo tên người chơi, IP, mã máy hoặc phiên bản…" value="' +
        esc(state.q) + '"></div>' + sortBar(REC_COLS, state.rSort, "rec") + '<div class="an-tablewrap"><table class="an-recent"><thead><tr>' +
        sortHead(REC_COLS, state.rSort, "rec") + '</tr></thead><tbody>' +
        (d.recent.length ? d.recent.map(function (r) {
          var tag = r.ev === "match" ? '<span class="an-tag match">trận</span>' :
                    r.isNew ? '<span class="an-tag new">mới</span>' : '<span class="an-tag back">quay lại</span>';
          return '<tr><td class="dim" data-l="Thời điểm">' + dt(r.ts) + '</td><td class="mono" data-l="IP">' + esc(r.ip) +
            '</td><td class="lead" data-l="Máy"><span>' + (r.name ? esc(r.name) + ' ' : '') + '<span class="mono dim" title="' +
            esc(r.install) + '">' + esc(r.install.slice(0, 8)) + '</span>' + tag + '</span></td><td data-l="Ứng dụng">' +
            esc(appName(r.app)) + '</td><td data-l="Phiên bản">v' + esc(r.version) + '</td><td data-l="Sự kiện">' +
            esc(evName(r.ev)) + '</td><td class="dim" data-l="Quốc gia">' + esc(r.country) + '</td></tr>';
        }).join("") : '<tr><td colspan="7" class="an-empty">Không có bản ghi nào khớp</td></tr>') +
        '</tbody></table></div><div class="an-pager"><button class="an-btn" id="pv"' + (state.page <= 1 ? ' disabled' : '') +
        '>← Trước</button><span>Trang ' + state.page + ' / ' + pages + '</span><button class="an-btn" id="nx"' +
        (state.page >= pages ? ' disabled' : '') + '>Sau →</button></div></div>';
      h += reportsCard();
    }
    app.innerHTML = h;
    document.getElementById("rf").onclick = function () { load(); };   // làm mới cả trang
    document.getElementById("lo").onclick = function () { setPw(""); state.data = null; login(); };
    Array.prototype.forEach.call(document.querySelectorAll(".an-chip"), function (b) {
      b.onclick = function () { state.range = b.getAttribute("data-r"); state.page = 1; load(); };
    });
    if (!d) return;
    bindReports();
    var top = document.getElementById("top");
    top.addEventListener("toggle", function () {
      state.topOpen = top.open;
      var hint = top.querySelector("summary .an-hint");
      hint.textContent = hint.textContent.replace(/bấm để (mở|gập)$/, "bấm để " + (top.open ? "gập" : "mở"));
    });
    function setSort(table, key, dir) {
      var cur = table === "top" ? state.tSort : state.rSort;
      var cols = table === "top" ? TOP_COLS : REC_COLS;
      if (!dir) dir = cur.key === key ? (cur.dir === "asc" ? "desc" : "asc") : (colOf(cols, key)[2] === "text" ? "asc" : "desc");
      cur.key = key;
      cur.dir = dir;
      if (table === "top") render();            // có sẵn cả 20 dòng: xếp ngay trên trình duyệt
      else { state.page = 1; load(true); }      // phân trang: máy chủ xếp trên toàn bộ bản ghi
    }
    Array.prototype.forEach.call(document.querySelectorAll("th.an-sort"), function (th) {
      th.onclick = function () { setSort(th.getAttribute("data-t"), th.getAttribute("data-k")); };
    });
    Array.prototype.forEach.call(document.querySelectorAll(".an-sortbar select"), function (sel) {
      sel.onchange = function () { var v = sel.value.split(" "); setSort(sel.getAttribute("data-t"), v[0], v[1]); };
    });
    var sq = document.getElementById("sq"), timer = null;
    sq.oninput = function () {
      clearTimeout(timer);
      timer = setTimeout(function () { state.q = sq.value.trim(); state.page = 1; load(true); }, 400);
    };
    if (state.q) { sq.focus(); sq.setSelectionRange(sq.value.length, sq.value.length); }
    var pv = document.getElementById("pv"), nx = document.getElementById("nx");
    pv.onclick = function () { state.page--; load(true); };
    nx.onclick = function () { state.page++; load(true); };
    drawChart(d.daily);
  }

  function drawChart(daily) {
    if (state.chart) { state.chart.destroy(); state.chart = null; }
    var el = document.getElementById("ch");
    if (!el || typeof Chart === "undefined") return;
    var labels = daily.map(function (r) { var p = r.date.split("-"); return p[2] + "/" + p[1]; });
    function ds(label, key, color) {
      return { label: label, data: daily.map(function (r) { return r[key] || 0; }), borderColor: color, backgroundColor: color,
               borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, pointHoverBorderColor: "#fff", pointHoverBorderWidth: 2,
               tension: 0.35 };
    }
    state.chart = new Chart(el, {
      type: "line",
      data: { labels: labels, datasets: [ds("Lượt mở app", "opens", "#2a78d6"), ds("Máy duy nhất", "installs", "#eb6834"),
                                          ds("Trận đã ghi", "matches", "#1baf7a"), ds("Máy mới", "newInstalls", "#8b5cf6")] },
      options: {
        maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        plugins: { legend: { display: false }, tooltip: { backgroundColor: "#fff", titleColor: "#0A0A0A", bodyColor: "#3D3D3D",
          borderColor: "#E8E8E8", borderWidth: 1, padding: 12, cornerRadius: 8, boxWidth: 12, boxHeight: 3,
          titleFont: { weight: "700" }, bodyFont: { family: "JetBrains Mono" } } },
        scales: {
          x: { grid: { display: false }, border: { color: "#E8E8E8" }, ticks: { color: "#9A9A9A", font: { size: 12 } } },
          y: { beginAtZero: true, border: { display: false }, grid: { color: "#F0F0F0" },
               ticks: { color: "#9A9A9A", precision: 0, font: { size: 12 },
                        callback: function (v) { return v >= 1000 ? (v / 1000).toLocaleString("vi-VN", { maximumFractionDigits: 1 }) + "k" : v; } } }
        }
      }
    });
  }

  load();
})();
</script>
</body>
</html>`;
