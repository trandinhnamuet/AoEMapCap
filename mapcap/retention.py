"""Tự dọn trận cũ (từ v19, yêu cầu người dùng 06/11): khi tổng dung lượng file ghi (.aoerec) vượt ngưỡng (mặc định 5 GB),
trận cũ hơn thời hạn (mặc định 30 ngày) được chuyển vào Thùng rác, cũ nhất trước, tới khi tổng về dưới ngưỡng. Dưới
ngưỡng thì giữ hết dù cũ bao lâu. Người dùng bật / tắt và đổi ngưỡng, thời hạn trong Cài đặt (Config.auto_clean,
clean_limit_gb, clean_days); lần đầu có trận cần dọn, giao diện hỏi trước (Config.clean_agreed).

Không bao giờ dọn: trận đã ghim (★, danh sách trong <thư mục Raw>\\_keep.json, đi theo thư mục), trận đang ghi, file sửa
trong 60 s gần nhất. Bản chuẩn bị cho điện thoại (<thư mục lưu>\\Web\\*.aoeweb) bị xoá cùng trận gốc và tự bỏ khi cũ
hơn WEB_CACHE_DAYS (cần thì máy tính chuẩn bị lại). Video đã xuất không bị đụng tới.
"""
import json
import os
import shutil
import time

GB = 1 << 30
DEFAULT_LIMIT_GB = 5.0
DEFAULT_DAYS = 30
LOW_DISK_BYTES = 5 * GB          # ổ lưu trận còn dưới mức này: cảnh báo trên giao diện + Nhật ký
WEB_CACHE_DAYS = 14
KEEP_FILE = "_keep.json"
RECENT_S = 60                    # file vừa sửa (có thể đang ghi): không dọn


def send_to_recycle_bin(path):
    """Đưa file vào Thùng rác của Windows (SHFileOperationW + FOF_ALLOWUNDO). Trả về (ok, lỗi)."""
    if os.name != "nt":
        try:
            os.remove(path)
            return True, ""
        except OSError as e:
            return False, str(e)
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", ctypes.c_uint), ("pFrom", ctypes.c_wchar_p),
                    ("pTo", ctypes.c_wchar_p), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", ctypes.c_wchar_p)]
    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    op = SHFILEOPSTRUCTW(None, FO_DELETE, os.path.abspath(path) + "\0", None,
                         FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI, False, None, None)
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0 or op.fAnyOperationsAborted or os.path.exists(path):
        return False, f"mã lỗi {rc}"
    return True, ""


# ---- ghim ---------------------------------------------------------------------------------------------------
def load_keep(raw_dir):
    """Tên file các trận đã ghim (không tự dọn)."""
    try:
        with open(os.path.join(raw_dir, KEEP_FILE), encoding="utf-8") as f:
            return set(json.load(f).get("keep", []))
    except (OSError, ValueError, AttributeError):
        return set()


def set_keep(raw_dir, name, on):
    keep = load_keep(raw_dir)
    if on:
        keep.add(name)
    else:
        keep.discard(name)
    p = os.path.join(raw_dir, KEEP_FILE)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"keep": sorted(keep)}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    return keep


# ---- quét / kế hoạch ----------------------------------------------------------------------------------------
def scan(raw_dir):
    """[(đường dẫn, cỡ, giờ sửa)] các file .aoerec, cũ nhất trước."""
    out = []
    try:
        for e in os.scandir(raw_dir):
            if e.is_file() and e.name.lower().endswith(".aoerec"):
                st = e.stat()
                out.append((e.path, st.st_size, st.st_mtime))
    except OSError:
        return []
    return sorted(out, key=lambda r: r[2])


def plan(raw_dir, limit_bytes, days, busy=None, now=None, files=None):
    """Kế hoạch dọn: (danh sách (đường dẫn, cỡ) sẽ chuyển vào Thùng rác, tổng hiện tại, tổng sau khi dọn).
    Chỉ khi tổng vượt ngưỡng; chỉ trận cũ hơn `days` ngày, cũ nhất trước, dừng khi tổng về dưới ngưỡng."""
    now = time.time() if now is None else now
    files = scan(raw_dir) if files is None else files
    total = sum(s for _p, s, _m in files)
    after = total
    out = []
    if total <= limit_bytes:
        return out, total, after
    keep = load_keep(raw_dir)
    cutoff = now - days * 86400
    for p, size, mtime in files:
        if after <= limit_bytes or mtime >= cutoff:
            break
        if os.path.basename(p) in keep or now - mtime < RECENT_S or (busy and busy(p)):
            continue
        out.append((p, size))
        after -= size
    return out, total, after


def web_cache_dir(raw_dir):
    return os.path.join(os.path.dirname(os.path.abspath(raw_dir)), "Web")


def _web_files(raw_dir, stem):
    d = web_cache_dir(raw_dir)
    try:
        return [os.path.join(d, n) for n in os.listdir(d) if n.startswith(stem + ".") and n.endswith(".aoeweb")]
    except OSError:
        return []


def stale_web_cache(raw_dir, now=None):
    """Bản chuẩn bị cho điện thoại không còn trận gốc hoặc cũ hơn WEB_CACHE_DAYS."""
    now = time.time() if now is None else now
    d = web_cache_dir(raw_dir)
    out = []
    try:
        entries = list(os.scandir(d))
    except OSError:
        return out
    for e in entries:
        if not (e.is_file() and e.name.endswith(".aoeweb")):
            continue
        stem = e.name.split(".v")[0] if ".v" in e.name else os.path.splitext(e.name)[0]
        src = os.path.join(raw_dir, stem + ".aoerec")
        try:
            if not os.path.exists(src) or now - e.stat().st_mtime > WEB_CACHE_DAYS * 86400:
                out.append(e.path)
        except OSError:
            continue
    return out


def disk_free(path):
    """Số byte còn trống trên ổ chứa path (None nếu không đọc được)."""
    p = os.path.abspath(path)
    while p and not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return None


def fmt_size(n):
    """1,9 GB / 350 MB (dấu phẩy thập phân như giao diện tiếng Việt)."""
    if n >= GB:
        return f"{n / GB:.1f} GB".replace(".", ",")
    return f"{max(0, round(n / (1 << 20)))} MB"


def status(raw_dir, limit_bytes, days, busy=None, now=None):
    """Tình trạng để hiện trên giao diện: số trận, tổng, trận cũ nhất, kế hoạch dọn, chỗ trống trên ổ."""
    now = time.time() if now is None else now
    files = scan(raw_dir)
    todo, total, after = plan(raw_dir, limit_bytes, days, busy, now, files)
    return {"count": len(files), "bytes": total, "oldest": files[0][2] if files else None,
            "plan": todo, "plan_bytes": total - after, "free": disk_free(raw_dir), "keep": len(load_keep(raw_dir))}


def run(raw_dir, limit_bytes, days, busy=None, log=None, delete=None, now=None):
    """Dọn theo kế hoạch + bỏ bản chuẩn bị điện thoại cũ. Trả về {"deleted", "freed", "failed", "web"}."""
    log = log or (lambda m: None)
    delete = delete or send_to_recycle_bin
    todo, _total, _after = plan(raw_dir, limit_bytes, days, busy, now)
    deleted, freed, failed = [], 0, []
    for p, size in todo:
        ok, err = delete(p)
        if ok:
            deleted.append(os.path.basename(p))
            freed += size
            for w in _web_files(raw_dir, os.path.splitext(os.path.basename(p))[0]):
                try:
                    os.remove(w)
                except OSError:
                    pass
        else:
            failed.append((os.path.basename(p), err))
    web = 0
    for w in stale_web_cache(raw_dir, now):
        try:
            os.remove(w)
            web += 1
        except OSError:
            pass
    if deleted:
        log(f"tự dọn trận cũ: đã chuyển {len(deleted)} trận ({fmt_size(freed)}) cũ hơn {days} ngày vào Thùng rác: "
            + ", ".join(deleted[:10]) + (" ..." if len(deleted) > 10 else ""))
    for name, err in failed:
        log(f"tự dọn trận cũ: không chuyển được {name} vào Thùng rác: {err}")
    if web:
        log(f"tự dọn: bỏ {web} bản chuẩn bị cho điện thoại đã cũ (cần thì máy tính chuẩn bị lại)")
    return {"deleted": deleted, "freed": freed, "failed": failed, "web": web}
