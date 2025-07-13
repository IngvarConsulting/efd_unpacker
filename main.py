#!/usr/bin/env python3
"""
Точка входа в приложение EFD Unpacker
"""

import sys
import os

# Добавляем src/ в PYTHONPATH
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from main import main as efd_main

if __name__ == "__main__":
    efd_main() 