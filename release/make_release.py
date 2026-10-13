"""Công cụ phát hành, dùng trong .github/workflows/release.yml (chạy được ở máy để thử).

    python release/make_release.py set-version v3
        ghi APP_VERSION = "3" vào mapcap/version.py (trước khi build)
    python release/make_release.py manifest v3 <thư mục có 2 exe> <ra version.json>
        version.json cho bộ tự cập nhật: phiên bản, min_version (release/policy.json), link + cỡ + SHA-256 từng exe,
        ghi chú mọi bản <= v3
    python release/make_release.py bodies v3 <thư mục ra> [--zip-sha=...] [--commit=...]
        mô tả trang Release cho mọi bản có ghi chú release/notes/v<N>.md: <thư mục ra>/v<N>.md
        (workflow đăng bản hiện tại với mô tả này và sửa lại mô tả các bản cũ cho đồng bộ)
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTES = os.path.join(ROOT, "release", "notes")
REPO = os.environ.get("GITHUB_REPOSITORY") or "trandinhnamuet/AoEMapCap"
EXES = ("AoE-MapCap.exe", "AoE-Replay.exe")
ZIP = "AoE-MapCap-win64.zip"


def tag_version(tag):
    m = re.fullmatch(r"v(\d+(?:\.\d+)*)", tag.strip())
    if not m:
        raise SystemExit(f"tag phải có dạng v<N> (vd v3), nhận: {tag!r}")
    return m.group(1)


def vkey(v):
    return tuple(int(x) for x in v.split("."))


def all_notes():
    """{"3": nội dung, ...} từ release/notes/v<N>.md."""
    out = {}
    for f in os.listdir(NOTES):
        m = re.fullmatch(r"v(\d+(?:\.\d+)*)\.md", f)
        if m:
            with open(os.path.join(NOTES, f), encoding="utf-8") as fh:
                out[m.group(1)] = fh.read().strip()
    return out


def set_version(tag):
    v = tag_version(tag)
    p = os.path.join(ROOT, "mapcap", "version.py")
    s = open(p, encoding="utf-8").read()
    s2 = re.sub(r'^APP_VERSION = ".*"$', f'APP_VERSION = "{v}"', s, count=1, flags=re.M)
    if s2 == s and f'APP_VERSION = "{v}"' not in s:
        raise SystemExit("không tìm thấy dòng APP_VERSION trong mapcap/version.py")
    open(p, "w", encoding="utf-8").write(s2)
    print(f"APP_VERSION = {v}")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def manifest(tag, exe_dir, out):
    v = tag_version(tag)
    with open(os.path.join(ROOT, "release", "policy.json"), encoding="utf-8") as f:
        policy = json.load(f)
    min_v = str(policy.get("min_version") or "1")
    if vkey(min_v) > vkey(v):
        raise SystemExit(f"min_version {min_v} lớn hơn bản đang phát hành {v}")
    notes = {k: t for k, t in all_notes().items() if vkey(k) <= vkey(v)}
    if v not in notes:
        raise SystemExit(f"thiếu ghi chú release/notes/v{v}.md")
    assets = {}
    for name in EXES:
        p = os.path.join(exe_dir, name)
        assets[name] = {"url": f"https://github.com/{REPO}/releases/download/{tag}/{name}",
                        "size": os.path.getsize(p), "sha256": sha256(p)}
    m = {"version": v, "tag": tag, "min_version": min_v,
         "published": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
         "page": f"https://github.com/{REPO}/releases/tag/{tag}", "notes": notes, "assets": assets}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)
    print(f"{out}: v{v}, min v{min_v}, " + ", ".join(f"{n} {a['size'] / 1e6:.1f} MB" for n, a in assets.items()))


def _commit_of(tag):
    try:
        return subprocess.run(["git", "rev-list", "-n", "1", tag], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def body(v, current, zip_sha="", commit=""):
    notes = all_notes()[v]
    tag = f"v{v}"
    lines = [f"## Có gì mới trong {tag}", "", notes, "", "## Tải về", "",
             f"- Tải **{ZIP}**, giải nén, mở `AoE-MapCap.exe` (ghi trận + bảng trận đã ghi) hoặc `AoE-Replay.exe` "
             "(chỉ xem replay)."]
    if vkey(v) >= (3,):
        lines.append("- Đang dùng từ v3 trở lên: app tự báo có bản mới, bấm **Cập nhật** là xong, không cần tải lại.")
    if not current:
        lines.append(f"- Đây là bản cũ. Bản mới nhất: https://github.com/{REPO}/releases/latest")
    lines.append(f"- Hướng dẫn: https://github.com/{REPO}#readme")
    lines.append("")
    commit = commit or _commit_of(tag)
    if commit:
        lines.append(f"Build trên GitHub Actions từ commit {commit}. Kiểm nguồn gốc exe: "
                     f"`gh attestation verify AoE-MapCap.exe -R {REPO}`")
    lines.append(f"SHA-256 của zip: `{zip_sha}`" if zip_sha else f"SHA-256 của zip: xem file `{ZIP}.sha256` đính kèm.")
    return "\n".join(lines) + "\n"


def bodies(tag, out_dir, zip_sha="", commit=""):
    cur = tag_version(tag)
    os.makedirs(out_dir, exist_ok=True)
    for v in sorted(all_notes(), key=vkey):
        if vkey(v) > vkey(cur):
            continue
        is_cur = v == cur
        p = os.path.join(out_dir, f"v{v}.md")
        with open(p, "w", encoding="utf-8") as f:
            f.write(body(v, is_cur, zip_sha if is_cur else "", commit if is_cur else ""))
        print(p)


def main(argv):
    if not argv:
        raise SystemExit(__doc__)
    cmd, args = argv[0], [a for a in argv[1:] if not a.startswith("--")]
    opts = dict(a[2:].split("=", 1) for a in argv[1:] if a.startswith("--") and "=" in a)
    if cmd == "set-version":
        set_version(args[0])
    elif cmd == "manifest":
        manifest(args[0], args[1], args[2])
    elif cmd == "bodies":
        bodies(args[0], args[1], opts.get("zip-sha", ""), opts.get("commit", ""))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    main(sys.argv[1:])
