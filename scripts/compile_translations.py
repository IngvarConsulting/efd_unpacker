#!/usr/bin/env python3
"""
Скрипт для автоматической компиляции переводов из .ts в .qm файлы
"""

import os
import sys
import subprocess
from pathlib import Path
from typing import Optional

def find_lrelease() -> Optional[str]:
    """Ищет lrelease в системе"""
    # Популярные пути для lrelease
    common_paths = [
        "lrelease",
        "lrelease-qt6",
        "lrelease-qt5",
        "/usr/bin/lrelease",
        "/usr/local/bin/lrelease",
        "/opt/homebrew/bin/lrelease",
        "C:\\Qt\\6.6.0\\msvc2019_64\\bin\\lrelease.exe",
        "C:\\Qt\\6.5.0\\msvc2019_64\\bin\\lrelease.exe",
        "C:\\Qt\\6.4.0\\msvc2019_64\\bin\\lrelease.exe",
    ]
    
    for path in common_paths:
        try:
            result = subprocess.run([path, "-version"], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                print(f"Found lrelease: {path}")
                print(f"Version: {result.stdout.strip()}")
                return path
        except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
            continue
    
    return None

def compile_translations(translations_dir: str, lrelease_path: str) -> bool:
    """Компилирует все .ts файлы в .qm"""
    success = True
    
    for ts_file in Path(translations_dir).glob("*.ts"):
        qm_file = ts_file.with_suffix('.qm')
        
        print(f"Compiling {ts_file.name}...")
        
        try:
            result = subprocess.run([lrelease_path, str(ts_file)], 
                                  capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                if qm_file.exists():
                    size = qm_file.stat().st_size
                    print(f"✓ Successfully compiled {ts_file.name} -> {qm_file.name} ({size} bytes)")
                else:
                    print(f"✗ Compilation succeeded but {qm_file.name} not found")
                    success = False
            else:
                print(f"✗ Failed to compile {ts_file.name}")
                print(f"Error: {result.stderr}")
                success = False
                
        except subprocess.TimeoutExpired:
            print(f"✗ Timeout compiling {ts_file.name}")
            success = False
        except Exception as e:
            print(f"✗ Error compiling {ts_file.name}: {e}")
            success = False
    
    return success

def main():
    """Основная функция"""
    print("EFD Unpacker - Translation Compiler")
    print("=" * 40)
    
    # Проверяем наличие папки translations
    translations_dir = "translations"
    if not os.path.exists(translations_dir):
        print(f"Error: {translations_dir} directory not found")
        return 1
    
    # Ищем lrelease
    lrelease_path = find_lrelease()
    if not lrelease_path:
        print("Error: lrelease not found")
        print("Please install Qt Linguist tools:")
        print("  - macOS: brew install qt6")
        print("  - Ubuntu/Debian: sudo apt-get install qttools6-dev-tools")
        print("  - Windows: Install Qt with Qt Linguist")
        return 1
    
    # Компилируем переводы
    print(f"\nCompiling translations in {translations_dir}...")
    if compile_translations(translations_dir, lrelease_path):
        print("\n✓ All translations compiled successfully!")
        
        # Показываем результат
        print("\nCompiled files (will be included in builds):")
        for qm_file in Path(translations_dir).glob("*.qm"):
            size = qm_file.stat().st_size
            print(f"  - {qm_file.name}: {size} bytes")
        
        # Показываем файлы, которые НЕ будут включены
        ts_files = list(Path(translations_dir).glob("*.ts"))
        if ts_files:
            print("\nSource files (NOT included in builds):")
            for ts_file in ts_files:
                size = ts_file.stat().st_size
                print(f"  - {ts_file.name}: {size} bytes")
        
        return 0
    else:
        print("\n✗ Some translations failed to compile!")
        return 1

if __name__ == '__main__':
    sys.exit(main()) 