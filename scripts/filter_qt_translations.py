#!/usr/bin/env python3
"""
Скрипт для фильтрации переводов Qt, оставляя только русский и английский языки
"""

import os
import shutil
import glob
from pathlib import Path
from typing import List, Set

def get_qt_translation_paths(app_path: str) -> List[str]:
    """Получает пути к папкам с переводами Qt в .app bundle"""
    paths = []
    
    # Пути в Resources
    resources_paths = [
        os.path.join(app_path, "Contents", "Resources", "PyQt6", "Qt6", "translations"),
        os.path.join(app_path, "Contents", "Frameworks", "PyQt6", "Qt6", "translations"),
    ]
    
    for path in resources_paths:
        if os.path.exists(path):
            paths.append(path)
    
    return paths

def get_allowed_languages() -> Set[str]:
    """Возвращает разрешенные языки"""
    return {'en', 'ru', 'english', 'russian'}

def is_allowed_translation(filename: str) -> bool:
    """Проверяет, является ли файл перевода разрешенным"""
    allowed_langs = get_allowed_languages()
    
    # Проверяем различные паттерны имен файлов Qt
    filename_lower = filename.lower()
    
    # qt_ru.qm, qt_en.qm
    if filename_lower.startswith('qt_') and any(lang in filename_lower for lang in allowed_langs):
        return True
    
    # qtbase_ru.qm, qtbase_en.qm
    if filename_lower.startswith('qtbase_') and any(lang in filename_lower for lang in allowed_langs):
        return True
    
    # qt_help_ru.qm, qt_help_en.qm
    if filename_lower.startswith('qt_help_') and any(lang in filename_lower for lang in allowed_langs):
        return True
    
    return False

def filter_qt_translations(app_path: str, dry_run: bool = False) -> dict:
    """Фильтрует переводы Qt, оставляя только русский и английский"""
    results = {
        'total_files': 0,
        'kept_files': 0,
        'removed_files': 0,
        'removed_size': 0,
        'kept_size': 0
    }
    
    translation_paths = get_qt_translation_paths(app_path)
    
    if not translation_paths:
        print(f"✗ No Qt translation directories found in {app_path}")
        return results
    
    print(f"Found Qt translation directories:")
    for path in translation_paths:
        print(f"  - {path}")
    
    for translations_dir in translation_paths:
        if not os.path.exists(translations_dir):
            continue
            
        print(f"\nProcessing: {translations_dir}")
        
        # Получаем все .qm файлы
        qm_files = glob.glob(os.path.join(translations_dir, "*.qm"))
        results['total_files'] += len(qm_files)
        
        if not qm_files:
            print("  No .qm files found")
            continue
        
        print(f"  Found {len(qm_files)} translation files")
        
        for qm_file in qm_files:
            filename = os.path.basename(qm_file)
            file_size = os.path.getsize(qm_file)
            
            if is_allowed_translation(filename):
                results['kept_files'] += 1
                results['kept_size'] += file_size
                print(f"    ✓ KEEP: {filename} ({file_size} bytes)")
            else:
                results['removed_files'] += 1
                results['removed_size'] += file_size
                print(f"    ✗ REMOVE: {filename} ({file_size} bytes)")
                
                if not dry_run:
                    try:
                        os.remove(qm_file)
                        print(f"      → Deleted {filename}")
                    except Exception as e:
                        print(f"      → Error deleting {filename}: {e}")
    
    return results

def main():
    """Основная функция"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Filter Qt translations to keep only Russian and English')
    parser.add_argument('--app-path', default='dist/EFDUnpacker.app', 
                       help='Path to the .app bundle (default: dist/EFDUnpacker.app)')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Show what would be removed without actually removing files')
    
    args = parser.parse_args()
    
    print("EFD Unpacker - Qt Translation Filter")
    print("=" * 50)
    
    if not os.path.exists(args.app_path):
        print(f"✗ App bundle not found: {args.app_path}")
        print("Please build the app first or specify the correct path with --app-path")
        return 1
    
    if args.dry_run:
        print("DRY RUN MODE - No files will be actually removed")
    
    print(f"Filtering Qt translations in: {args.app_path}")
    print("Keeping only: Russian (ru) and English (en) translations")
    
    results = filter_qt_translations(args.app_path, dry_run=args.dry_run)
    
    print("\n" + "=" * 50)
    print("SUMMARY:")
    print(f"  Total Qt translation files: {results['total_files']}")
    print(f"  Kept files: {results['kept_files']}")
    print(f"  Removed files: {results['removed_files']}")
    print(f"  Kept size: {results['kept_size']:,} bytes ({results['kept_size']/1024:.1f} KB)")
    print(f"  Removed size: {results['removed_size']:,} bytes ({results['removed_size']/1024:.1f} KB)")
    
    if results['removed_size'] > 0:
        savings_percent = (results['removed_size'] / (results['kept_size'] + results['removed_size'])) * 100
        print(f"  Size reduction: {savings_percent:.1f}%")
    
    if args.dry_run:
        print("\nTo actually apply the changes, run without --dry-run")
    else:
        print("\n✓ Qt translations filtered successfully!")
    
    return 0

if __name__ == '__main__':
    import sys
    sys.exit(main()) 