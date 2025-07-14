#!/usr/bin/env python3
"""
Скрипт для генерации EFDUnpacker.spec с версией из version.txt
"""

import os

def read_version() -> str:
    """Читает версию из файла version.txt"""
    # Получаем путь к корню проекта (на уровень выше scripts/)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    version_file = os.path.join(project_root, 'version.txt')
    
    if os.path.exists(version_file):
        with open(version_file, 'r') as f:
            return f.read().strip()
    else:
        print("Error: version.txt not found")
        exit(1)

def verify_translations(project_root: str) -> None:
    """Проверяет наличие папки translations и .qm файлов"""
    translations_dir = os.path.join(project_root, 'translations')
    
    if not os.path.exists(translations_dir):
        print("Error: translations directory not found")
        print(f"Expected path: {translations_dir}")
        exit(1)
    
    ru_qm = os.path.join(translations_dir, 'ru.qm')
    if not os.path.exists(ru_qm):
        print("Warning: translations/ru.qm not found")
        print("Please compile ru.ts to ru.qm using lrelease")
        print("Example: lrelease translations/ru.ts")
        exit(1)
    
    print(f"✓ Translations verified: {translations_dir}")
    print(f"  - ru.qm: {os.path.getsize(ru_qm)} bytes")

def generate_spec(version: str) -> None:
    """Генерирует spec файл с указанной версией"""
    # Получаем путь к корню проекта
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # Проверяем translations перед генерацией spec
    verify_translations(project_root)
    
    # Находим все .qm файлы в папке translations
    translations_dir = os.path.join(project_root, 'translations')
    qm_files = []
    for file in os.listdir(translations_dir):
        if file.endswith('.qm'):
            qm_files.append(f"('{os.path.join(translations_dir, file)}', 'translations')")
    
    datas_section = ',\n        '.join(qm_files) if qm_files else "('translations', 'translations')"
    
    spec_content = f'''# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['{os.path.join(project_root, "src/main.py")}'],
    pathex=[],
    binaries=[],
    datas=[
        {datas_section},
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='EFDUnpacker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='EFDUnpacker',
)

app = BUNDLE(
    coll,
    name='EFDUnpacker.app',
    icon='{os.path.join(project_root, "resources/icon.icns")}',
    bundle_identifier='com.efd.unpacker',
    info_plist={{
        'CFBundleName': 'EFD Unpacker',
        'CFBundleDisplayName': 'EFD Unpacker',
        'CFBundleIdentifier': 'com.efd.unpacker',
        'CFBundleVersion': '{version}',
        'CFBundleShortVersionString': '{version}',
        'CFBundlePackageType': 'APPL',
        'CFBundleSignature': '????',
        'CFBundleExecutable': 'EFDUnpacker',
        'CFBundleIconFile': 'icon.icns',
        'CFBundleDocumentTypes': [
            {{
                'CFBundleTypeExtensions': ['efd'],
                'CFBundleTypeName': 'EFD File',
                'CFBundleTypeRole': 'Viewer',
                'CFBundleTypeIconFile': 'icon.icns',
                'CFBundleTypeDescription': 'EFD (Enterprise File Distribution) archive file',
                'LSHandlerRank': 'Owner',
                'LSItemContentTypes': ['com.efd.unpacker.efd-file'],
            }}
        ],
        'UTExportedTypeDeclarations': [
            {{
                'UTTypeIdentifier': 'com.efd.unpacker.efd-file',
                'UTTypeDescription': 'EFD Archive File',
                'UTTypeConformsTo': ['public.data', 'public.archive'],
                'UTTypeTagSpecification': {{
                    'public.filename-extension': 'efd',
                    'public.mime-type': 'application/x-efd',
                }}
            }}
        ],
        'CFBundleURLTypes': [
            {{
                'CFBundleURLName': 'EFD File Handler',
                'CFBundleURLSchemes': ['efd'],
            }}
        ],
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.13.0',
    }},
)
'''
    
    # Сохраняем spec файл в корне проекта
    spec_file = os.path.join(project_root, 'EFDUnpacker.spec')
    with open(spec_file, 'w') as f:
        f.write(spec_content)
    
    print(f"Generated EFDUnpacker.spec with version {version}")
    print(f"Included .qm files: {[f.split('/')[-1] for f in qm_files]}")

if __name__ == '__main__':
    version = read_version()
    generate_spec(version) 