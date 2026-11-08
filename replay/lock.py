"""Chống dùng replay để gian lận khi ván còn đang đánh (người dùng 09/11: "vừa vào trận, xin đối thủ 10, 20 s xong ra
ngoài bấm dừng ghi rồi xem là biết nhà đối thủ ở mấy giờ").

Luật: trận ghi KHÔNG tới lúc ván đã phân thắng bại (dừng ghi giữa chừng, tắt app, đang ghi dở, bị loại / bỏ cuộc trong
ván đồng đội mà đồng đội còn đánh) bị khoá LOCK_SECONDS (60 phút) tính từ mẫu cuối cùng của file. Trong lúc khoá: không
mở trình xem replay, không xuất video, không gửi sang điện thoại. Trận ghi tới hết ván mở được ngay.

"Đã phân thắng bại" (đọc từ bản ghi tổng kết 'E' cuối file): cờ hết ván của game ('go'), hoặc người chơi còn đang
chơi (trạng thái 0) chỉ còn thuộc nhiều nhất một đội (1v1 một người đầu hàng / thua; ván đồng đội một bên bị loại hết).
File không có 'E' (đang ghi, app bị tắt) = chưa phân thắng bại, giờ mẫu cuối lấy từ chính mẫu cuối trong file.

Tính lại từ file mỗi lần mở (không tin _matches.json - người dùng sửa được); thời điểm lấy từ giờ ghi trong file (giờ
máy lúc lấy mẫu), không lấy giờ sửa file. Không chặn được người sửa đồng hồ máy / sửa file nhị phân - mục tiêu là chặn
mẹo dễ, không phải chống gian lận tuyệt đối. File trước 2026-10-09 (chưa có trạng thái thắng thua) không khoá.
"""
import os
import time

from mapcap.rawrec import read_end, read_header

LOCK_SECONDS = 60 * 60


def decided(hdr, end):
    """Ván đã phân thắng bại lúc dừng ghi."""
    if end is None:
        return False
    if end.get("game_over"):
        return True
    from .library import teams_from_header
    status = {int(k): tuple(v) for k, v in (end.get("status") or {}).items()}
    alive = {k for k, team in enumerate(teams_from_header(hdr)) for i in team if status.get(i, (0, 0))[0] == 0}
    return len(alive) <= 1


def until_from(hdr, end, last_at):
    """Thời điểm hết khoá (giây epoch), 0 = không khoá."""
    if hdr is None or "format" not in hdr or decided(hdr, end):
        return 0.0
    last = float(last_at or 0) or float((end or {}).get("closed") or 0) or float(hdr.get("created") or 0)
    return last + LOCK_SECONDS if last else 0.0


def lock_until(path):
    """Hết khoá lúc nào (0 = mở được), tính lại từ file."""
    try:
        hdr = read_header(path)
    except Exception:  # noqa: BLE001  - file hỏng: để trình xem tự báo lỗi đọc
        return 0.0
    if hdr is None or "format" not in hdr:
        return 0.0
    end = read_end(path)
    if decided(hdr, end):
        return 0.0
    if end is not None:
        last_at = end.get("at")
    else:
        from .library import _scan_last_frame
        try:
            last, _n = _scan_last_frame(path)
        except Exception:  # noqa: BLE001
            last = None
        last_at = (last or {}).get("at") or os.path.getmtime(path)
    return until_from(hdr, end, last_at)


def short(until):
    """Chữ ngắn cho bảng trận: 'Khoá tới 21:35'."""
    return "Khoá tới " + time.strftime("%H:%M", time.localtime(until))


def message(until):
    t = time.localtime(until)
    when = time.strftime("%H:%M", t) + ("" if time.strftime("%d%m") == time.strftime("%d%m", t)
                                        else time.strftime(" ngày %d/%m", t))
    return (f"Trận này đang khoá tới {when}.\n\n"
            "Lúc dừng ghi, ván vẫn chưa phân thắng bại (còn người chơi của ít nhất hai đội đang đánh). Để không ai dùng "
            "replay xem bản đồ, nhà đối thủ khi ván còn đang đánh, trận dừng ghi giữa chừng chỉ xem / xuất video / gửi "
            f"sang điện thoại được sau {LOCK_SECONDS // 60} phút kể từ lúc dừng ghi.\n\n"
            "Trận ghi tới hết ván thì xem được ngay.")


def check(path, now=None):
    """None = mở được; không thì câu giải thích (đang khoá tới lúc nào, vì sao)."""
    until = lock_until(path)
    if until and (now if now is not None else time.time()) < until:
        return message(until)
    return None
