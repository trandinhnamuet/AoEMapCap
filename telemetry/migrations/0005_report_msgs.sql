-- Nhắn qua lại giữa admin và người gửi báo cáo hack (2026-11-14): admin viết ở trang /stats, app tải về theo mã máy
-- (tab Lịch sử báo cáo) và gửi trả lời. admin_note của bảng reports vẫn là ghi chú riêng của admin, không gửi đi.
CREATE TABLE IF NOT EXISTS report_msgs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  report INTEGER NOT NULL,          -- reports.id
  ts INTEGER NOT NULL,              -- ms UTC
  who TEXT NOT NULL,                -- 'admin' | 'user'
  text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS report_msgs_report ON report_msgs (report, id);
