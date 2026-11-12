-- Thống kê sử dụng AoE-MapCap (Cloudflare D1). Giờ lưu theo ms UTC; trang thống kê gom ngày theo giờ Việt Nam.
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,            -- ms UTC lúc nhận
  install TEXT NOT NULL,          -- mã máy (UUID ngẫu nhiên tạo lần đầu chạy)
  app TEXT NOT NULL,              -- mapcap | replay
  version TEXT NOT NULL,          -- APP_VERSION
  ev TEXT NOT NULL,               -- open (mở app) | match (ghi xong một trận)
  ip TEXT,                        -- IP người gọi (CF-Connecting-IP; app kết nối bằng IPv4)
  country TEXT,                   -- mã nước theo Cloudflare
  name TEXT                       -- tên người chơi (nickname, lấy từ trận đã ghi; cho phép trùng) — từ v7
);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS events_install_ts ON events(install, ts);

CREATE TABLE IF NOT EXISTS installs (
  install TEXT PRIMARY KEY,
  first_ts INTEGER NOT NULL,
  last_ts INTEGER NOT NULL,
  first_ip TEXT,
  last_ip TEXT,
  country TEXT,
  app TEXT,
  version TEXT,
  opens INTEGER NOT NULL DEFAULT 0,
  matches INTEGER NOT NULL DEFAULT 0,
  name TEXT                       -- tên người chơi gần nhất của máy — từ v7
);
CREATE INDEX IF NOT EXISTS installs_last ON installs(last_ts);

-- 2026-11-10: bảng tổng hợp để trang thống kê không quét bảng events (mỗi lần xem từng tốn ~19 dòng đọc cho MỖI lượt đã
-- lưu -> sẽ vượt 5 triệu dòng đọc / ngày của gói miễn phí D1). Cập nhật ngay lúc nhận lượt (src/index.js ingest);
-- dữ liệu cũ điền bằng rebuild_aggregates.sql. WITHOUT ROWID: khoá chính chính là bảng -> mỗi lần cập nhật ghi 1 dòng.
-- Ngày = ngày giờ Việt Nam (UTC+7), dạng 'YYYY-MM-DD'.

-- mỗi ngày một dòng: lượt mở, trận ghi, số máy dùng trong ngày, số máy dùng lần đầu
CREATE TABLE IF NOT EXISTS day_total (
  date TEXT PRIMARY KEY,
  opens INTEGER NOT NULL DEFAULT 0,
  matches INTEGER NOT NULL DEFAULT 0,
  installs INTEGER NOT NULL DEFAULT 0,
  new_installs INTEGER NOT NULL DEFAULT 0
) WITHOUT ROWID;

-- mỗi máy mỗi ngày có dùng một dòng (bảng Máy dùng nhiều nhất theo kỳ)
CREATE TABLE IF NOT EXISTS day_install (
  date TEXT NOT NULL,
  install TEXT NOT NULL,
  opens INTEGER NOT NULL DEFAULT 0,
  matches INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (date, install)
) WITHOUT ROWID;

-- mỗi cặp máy + IP một dòng, giờ dùng gần nhất (số IP khác nhau theo kỳ, số IP của từng máy)
CREATE TABLE IF NOT EXISTS install_ip (
  install TEXT NOT NULL,
  ip TEXT NOT NULL,
  last_ts INTEGER NOT NULL,
  PRIMARY KEY (install, ip)
) WITHOUT ROWID;

-- tên người chơi (nickname trong trận ghi): tổng trận + theo ngày (bảng xếp hạng, ô Tên trong game)
CREATE TABLE IF NOT EXISTS name_total (
  name TEXT PRIMARY KEY,
  matches INTEGER NOT NULL DEFAULT 0,
  last_ts INTEGER NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS day_name (
  date TEXT NOT NULL,
  name TEXT NOT NULL,
  matches INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (date, name)
) WITHOUT ROWID;

-- Báo cáo trận có hack (app AoE-MapCap, nút "Báo cáo hack" ở trang Trận đã ghi; 2026-11-11).
-- File .aoerec lưu ở R2 (binding REPORTS, khoá r2key); bảng này giữ thông tin để admin xem trên trang /stats.
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,              -- lúc nhận (ms UTC)
  install TEXT NOT NULL,            -- mã máy người báo
  name TEXT,                        -- tên trong game của người báo (người ghi trận)
  ip TEXT,
  country TEXT,
  version TEXT,
  file TEXT,                        -- tên file trên máy người báo
  size INTEGER NOT NULL DEFAULT 0,  -- byte
  r2key TEXT,                       -- NULL = file đã bị xoá khỏi R2 (dọn bớt khi gần hết dung lượng)
  suspect TEXT,                     -- người chơi bị nghi hack (người báo chọn / ghi)
  note TEXT,                        -- ghi chú của người báo
  meta TEXT,                        -- JSON: người chơi, map, thời lượng, vi phạm app tự phát hiện ("hack")
  status TEXT NOT NULL DEFAULT 'new',  -- new | hack | clean | unsure (admin đánh dấu sau khi xem)
  admin_note TEXT                   -- admin ghi: ai hack, hack gì (làm dữ liệu thêm luật)
);
CREATE INDEX IF NOT EXISTS reports_ts ON reports (ts);
CREATE INDEX IF NOT EXISTS reports_install_ts ON reports (install, ts);
