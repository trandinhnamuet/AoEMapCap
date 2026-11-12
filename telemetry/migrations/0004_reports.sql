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
