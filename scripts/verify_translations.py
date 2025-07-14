#!/usr/bin/env python3
"""
Скрипт для проверки включения переводов в готовые сборки
"""

import os
import sys
import zipfile
import tarfile
from pathlib import Path

def check_translations_in_directory(directory: str, platform: str) -> bool:
    """Проверяет наличие переводов в директории сборки"""
    print(f"\n=== Checking {platform} build in {directory} ===")
    
    if not os.path.exists(directory):
        print(f"✗ Directory not found: {directory}")
        return False
    
    # Ищем папку translations
    translations_paths = []
    
    if platform == "macos":
        # macOS .app bundle
        app_path = os.path.join(directory, "EFDUnpacker.app")
        if os.path.exists(app_path):
            translations_paths.extend([
                os.path.join(app_path, "Contents", "Resources", "translations"),
                os.path.join(app_path, "Contents", "Resources", "PyQt6", "Qt6", "translations")
            ])
    elif platform == "linux":
        # Linux executable folder
        translations_paths.append(os.path.join(directory, "EFDUnpacker", "translations"))
        translations_paths.append(os.path.join(directory, "EFDUnpacker", "_internal", "translations"))
    elif platform == "windows":
        # Windows executable folder
        translations_paths.append(os.path.join(directory, "translations"))
        translations_paths.append(os.path.join(directory, "EFDUnpacker", "translations"))
    
    found = False
    for path in translations_paths:
        if os.path.exists(path):
            print(f"✓ Translations found: {path}")
            files = os.listdir(path)
            relevant_files = []
            
            for file in files:
                if file.endswith('.qm'):
                    # Для PyQt6/Qt6/translations проверяем только английские и русские переводы
                    if 'PyQt6/Qt6/translations' in path:
                        if any(lang in file.lower() for lang in ['en', 'ru', 'english', 'russian']):
                            relevant_files.append(file)
                    else:
                        # Для других папок проверяем все .qm файлы
                        relevant_files.append(file)
            
            if relevant_files:
                for file in relevant_files:
                    file_path = os.path.join(path, file)
                    size = os.path.getsize(file_path)
                    print(f"  - {file}: {size} bytes")
                found = True
            else:
                print(f"  - No relevant translation files found")
    
    if not found:
        print(f"✗ No translations found in {directory}")
        print("Directory structure:")
        for root, dirs, files in os.walk(directory):
            level = root.replace(directory, '').count(os.sep)
            indent = ' ' * 2 * level
            print(f"{indent}{os.path.basename(root)}/")
            subindent = ' ' * 2 * (level + 1)
            for d in dirs:
                print(f"{subindent}{d}/")
    
    return found

def check_translations_in_archive(archive_path: str, platform: str) -> bool:
    """Проверяет наличие переводов в архиве"""
    print(f"\n=== Checking {platform} archive: {archive_path} ===")
    
    if not os.path.exists(archive_path):
        print(f"✗ Archive not found: {archive_path}")
        return False
    
    try:
        if archive_path.endswith('.zip'):
            with zipfile.ZipFile(archive_path, 'r') as zip_file:
                translations_files = [f for f in zip_file.namelist() if 'translations' in f and f.endswith('.qm')]
        elif archive_path.endswith('.tar.gz'):
            with tarfile.open(archive_path, 'r:gz') as tar_file:
                translations_files = [f for f in tar_file.getnames() if 'translations' in f and f.endswith('.qm')]
        else:
            print(f"✗ Unsupported archive format: {archive_path}")
            return False
        
        if translations_files:
            print(f"✓ Found {len(translations_files)} translation files:")
            for file in translations_files:
                print(f"  - {file}")
            return True
        else:
            print(f"✗ No translation files found in archive")
            return False
            
    except Exception as e:
        print(f"✗ Error reading archive: {e}")
        return False

def main():
    """Основная функция проверки"""
    print("EFD Unpacker - Translation Verification")
    print("=" * 50)
    
    # Проверяем исходные переводы
    print("\n=== Checking source translations ===")
    if os.path.exists("translations"):
        print("✓ Source translations directory found")
        for file in os.listdir("translations"):
            if file.endswith('.qm'):
                file_path = os.path.join("translations", file)
                size = os.path.getsize(file_path)
                print(f"  - {file}: {size} bytes")
    else:
        print("✗ Source translations directory not found")
        return 1
    
    # Проверяем готовые сборки
    all_good = True
    
    # macOS
    if os.path.exists("dist/EFDUnpacker.app"):
        if not check_translations_in_directory("dist", "macos"):
            all_good = False
    
    # Linux
    if os.path.exists("dist/EFDUnpacker"):
        if not check_translations_in_directory("dist", "linux"):
            all_good = False
    
    # Windows
    if os.path.exists("dist/EFDUnpacker.exe"):
        if not check_translations_in_directory("dist", "windows"):
            all_good = False
    
    # Проверяем архивы
    for archive in os.listdir("dist"):
        if archive.endswith('.zip') or archive.endswith('.tar.gz'):
            platform = "unknown"
            if "macos" in archive:
                platform = "macos"
            elif "linux" in archive:
                platform = "linux"
            elif "windows" in archive:
                platform = "windows"
            
            if not check_translations_in_archive(os.path.join("dist", archive), platform):
                all_good = False
    
    print("\n" + "=" * 50)
    if all_good:
        print("✓ All builds include translations successfully!")
        return 0
    else:
        print("✗ Some builds are missing translations!")
        return 1

if __name__ == '__main__':
    sys.exit(main()) 