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
