-- v7 (2026-10-15): tên người chơi (nickname trong game, lấy từ trận đã ghi; cho phép trùng) theo từng lượt và theo máy.
ALTER TABLE events ADD COLUMN name TEXT;
ALTER TABLE installs ADD COLUMN name TEXT;
