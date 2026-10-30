"""Số phiên bản của AoE-MapCap / AoE-Replay: tăng 1 mỗi lần phát hành (tag v<N> trên GitHub).

Khi build bản phát hành, GitHub Actions ghi lại dòng APP_VERSION theo tag (vd tag v3 -> "3").
Bộ tự cập nhật (mapcap/updater.py) so số này với version.json của bản phát hành mới nhất.
"""
APP_VERSION = "15"
