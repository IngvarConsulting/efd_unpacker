#!/usr/bin/env python3
"""
Запуск efd_unpacker из исходников.
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from efd_unpacker.application.main import main as efd_main

if __name__ == "__main__":
    efd_main()
