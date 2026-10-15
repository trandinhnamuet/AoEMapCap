-- Thống kê sử dụng AoE-MapCap (Cloudflare D1). Giờ lưu theo ms UTC; trang thống kê gom ngày theo giờ Việt Nam.
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,            -- ms UTC lúc nhận
  install TEXT NOT NULL,          -- mã máy (UUID ngẫu nhiên tạo lần đầu chạy)
  app TEXT NOT NULL,              -- mapcap | replay
  version TEXT NOT NULL,          -- APP_VERSION
  ev TEXT NOT NULL,               -- open (mở app) | match (ghi xong một trận)
  ip TEXT,                        -- IP người gọi (CF-Connecting-IP; app kết nối bằng IPv4)
  country TEXT                    -- mã nước theo Cloudflare
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
  matches INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS installs_last ON installs(last_ts);
