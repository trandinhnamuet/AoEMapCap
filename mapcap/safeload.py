"""Đọc an toàn dữ liệu trong file ghi trận .aoerec (file có thể do người khác gửi, app chạy quyền Admin).

pickle thường chạy được mã tuỳ ý khi đọc (vd __reduce__ -> os.system): một file .aoerec chế sẵn gửi qua Zalo sẽ chiếm
quyền Admin của máy mở nó. Ở đây chỉ cho phép đúng các kiểu có trong file ghi thật (kiểm 2026-10-16 bằng pickletools trên
các trận thật: numpy.core.multiarray._reconstruct, numpy.ndarray, numpy.dtype; còn lại là dict/list/tuple/str/số/bytes
không cần tra lớp) cùng vài kiểu vô hại; gặp kiểu khác -> UnpicklingError, không mở file.
Giải nén có giới hạn dung lượng (chặn "bom giải nén" làm treo / hết RAM).
"""
import io
import lzma
import pickle
import zlib

MAX_RAW = 512 << 20                 # 512 MB sau giải nén cho một bản ghi (header bản đồ lớn nhất cỡ vài MB)

ALLOWED = {
    ("numpy.core.multiarray", "_reconstruct"), ("numpy._core.multiarray", "_reconstruct"),
    ("numpy.core.multiarray", "scalar"), ("numpy._core.multiarray", "scalar"),
    ("numpy", "ndarray"), ("numpy", "dtype"),
    ("builtins", "set"), ("builtins", "frozenset"), ("builtins", "complex"),
    ("collections", "OrderedDict"),
}


class UnsafeFileError(pickle.UnpicklingError):
    pass


class _Unpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if (module, name) in ALLOWED:
            return super().find_class(module, name)
        raise UnsafeFileError(f"file ghi trận chứa kiểu dữ liệu không cho phép ({module}.{name}): không mở")


def loads(data):
    """pickle.loads chỉ với các kiểu cho phép."""
    return _Unpickler(io.BytesIO(data)).load()


def zlib_raw(data, limit=MAX_RAW, wbits=zlib.MAX_WBITS):
    d = zlib.decompressobj(wbits)
    raw = d.decompress(data, limit)
    if d.unconsumed_tail:
        raise ValueError("dữ liệu giải nén vượt giới hạn")
    return raw


def lzma_raw(data, limit=MAX_RAW):
    d = lzma.LZMADecompressor()
    raw = d.decompress(data, max_length=limit)
    if not d.eof and not d.needs_input:
        raise ValueError("dữ liệu giải nén vượt giới hạn")
    return raw


def zlib_loads(data):
    return loads(zlib_raw(data))


def lzma_loads(data):
    return loads(lzma_raw(data))
