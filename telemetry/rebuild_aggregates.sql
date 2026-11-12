-- Dựng lại toàn bộ bảng tổng hợp (migrations/0003_aggregates.sql) từ bảng events - nguồn gốc của mọi số liệu.
-- Dùng lúc chuyển sang bảng tổng hợp (2026-11-10) và bất cứ khi nào nghi số tổng hợp lệch:
--   npx wrangler d1 execute aoe-mapcap-telemetry --remote --file rebuild_aggregates.sql
-- Chạy một lần tốn khoảng (số lượt x vài) dòng đọc. Cùng quy ước với src/index.js ingest: ngày giờ Việt Nam
-- (ts + 7 giờ), tên người chơi chỉ tính lượt "match" = tên trong lượt, không có thì tên đã biết của máy, rỗng bỏ qua.
DELETE FROM day_total;
DELETE FROM day_install;
DELETE FROM install_ip;
DELETE FROM name_total;
DELETE FROM day_name;

INSERT INTO day_total (date, opens, matches, installs, new_installs)
SELECT strftime('%Y-%m-%d', (ts + 25200000) / 1000, 'unixepoch') AS d, SUM(ev = 'open'), SUM(ev = 'match'),
       COUNT(DISTINCT install), 0
FROM events GROUP BY d;

UPDATE day_total SET new_installs = (
  SELECT COUNT(*) FROM installs WHERE strftime('%Y-%m-%d', (first_ts + 25200000) / 1000, 'unixepoch') = day_total.date);

INSERT INTO day_install (date, install, opens, matches)
SELECT strftime('%Y-%m-%d', (ts + 25200000) / 1000, 'unixepoch') AS d, install, SUM(ev = 'open'), SUM(ev = 'match')
FROM events GROUP BY d, install;

INSERT INTO install_ip (install, ip, last_ts)
SELECT install, COALESCE(ip, ''), MAX(ts) FROM events GROUP BY install, COALESCE(ip, '');

INSERT INTO name_total (name, matches, last_ts)
SELECT pname, COUNT(*), MAX(ts) FROM (
  SELECT COALESCE(NULLIF(TRIM(e.name), ''), NULLIF(TRIM(i.name), ''), '') AS pname, e.ts AS ts
  FROM events e JOIN installs i ON i.install = e.install WHERE e.ev = 'match')
WHERE pname <> '' GROUP BY pname;

INSERT INTO day_name (date, name, matches)
SELECT d, pname, COUNT(*) FROM (
  SELECT strftime('%Y-%m-%d', (e.ts + 25200000) / 1000, 'unixepoch') AS d,
         COALESCE(NULLIF(TRIM(e.name), ''), NULLIF(TRIM(i.name), ''), '') AS pname
  FROM events e JOIN installs i ON i.install = e.install WHERE e.ev = 'match')
WHERE pname <> '' GROUP BY d, pname;
