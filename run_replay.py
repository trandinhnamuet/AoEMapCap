"""Điểm vào riêng của AoE-Replay (trình xem replay), để chạy/đóng gói tách khỏi AoE-MapCap.

    python run_replay.py [file.aoerec] [--game-dir=...]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    from replay.cli import main
    sys.exit(main(sys.argv[1:]))
