"""python -m replay [file.aoerec] [--game-dir=...]"""
import sys

from .cli import main

sys.exit(main(sys.argv[1:]))
