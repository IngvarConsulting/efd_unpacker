#!/bin/bash

# Установка строгого режима
set -e

echo "Building EFD Unpacker for macOS..."

# Читаем версию из файла
if [ -f "version.txt" ]; then
    VERSION=$(cat version.txt | tr -d ' \t\n\r')
    echo "Version from version.txt: $VERSION"
else
    echo "Error: version.txt not found."
    echo "This file should be created automatically by GitHub Actions from the git tag."
    echo "For local builds, please create version.txt with the version number."
    echo "Example: echo '1.0.0' > version.txt"
    exit 1
fi

# Генерируем spec файл с правильной версией
echo "Generating spec file with version $VERSION..."
python3 scripts/generate_spec.py

# Проверяем наличие Python
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 not found. Please install Python 3."
    exit 1
fi

# Проверяем версию Python
python_version=$(python3 --version 2>&1)
echo "Found Python: $python_version"

# Проверяем наличие PyInstaller
if ! python3 -c "import PyInstaller" &> /dev/null; then
    echo "Installing PyInstaller..."
    pip3 install pyinstaller
fi

# Проверяем наличие Homebrew
if ! command -v brew &> /dev/null; then
    echo "Error: Homebrew not found. Please install Homebrew first:"
    echo "  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    exit 1
fi

# Проверяем наличие create-dmg
if ! command -v create-dmg &> /dev/null; then
    echo "Installing create-dmg..."
    brew install create-dmg
fi

# Проверяем наличие иконки
if [ ! -f "resources/icon.icns" ]; then
    echo "Warning: resources/icon.icns not found. Using default icon."
    icon_option=""
else
    icon_option="--icon=resources/icon.icns"
    echo "Using custom icon: resources/icon.icns"
fi

# Очищаем предыдущие сборки
echo "Cleaning previous builds..."
if [ -d "build" ]; then
    rm -rf build
fi
if [ -d "dist" ]; then
    rm -rf dist
fi

# Сборка .app используя spec файл
echo "Building .app bundle using spec file..."
pyinstaller --noconfirm EFDUnpacker.spec

if [ $? -ne 0 ]; then
    echo "Error: PyInstaller build failed."
    exit 1
fi

echo "App bundle created successfully"

# Проверяем, что .app создался
if [ ! -d "dist/EFDUnpacker.app" ]; then
    echo "Error: EFDUnpacker.app not found in dist directory."
    exit 1
fi

# Создание DMG
echo "Creating DMG installer..."
create-dmg \
  --volname "EFD Unpacker" \
  --volicon "resources/icon.icns" \
  --window-pos 200 120 \
  --window-size 600 300 \
  --icon-size 100 \
  --icon "EFDUnpacker.app" 175 120 \
  --hide-extension "EFDUnpacker.app" \
  --app-drop-link 425 120 \
  "dist/efd-unpacker-${VERSION}-macos.dmg" \
  "dist/EFDUnpacker.app"

if [ $? -ne 0 ]; then
    echo "Error: DMG creation failed."
    exit 1
fi

# Создание ZIP архива для портативной версии
echo "Creating ZIP archive..."
cd dist
zip -r efd-unpacker-${VERSION}-macos-portable.zip EFDUnpacker.app
cd ..

# Показываем результаты
echo ""
echo "Build completed successfully!"
echo "Files created:"
echo "  - dist/EFDUnpacker.app/ (app bundle)"
echo "  - dist/efd-unpacker-${VERSION}-macos.dmg (installer)"
echo "  - dist/efd-unpacker-${VERSION}-macos-portable.zip (portable version)"

# Показываем размеры файлов
echo ""
echo "File sizes:"
if [ -d "dist/EFDUnpacker.app" ]; then
    app_size=$(du -sh dist/EFDUnpacker.app | cut -f1)
    echo "  App bundle: $app_size"
fi
if [ -f "dist/efd-unpacker-${VERSION}-macos.dmg" ]; then
    dmg_size=$(du -sh dist/efd-unpacker-${VERSION}-macos.dmg | cut -f1)
    echo "  DMG installer: $dmg_size"
fi
if [ -f "dist/efd-unpacker-${VERSION}-macos-portable.zip" ]; then
    zip_size=$(du -sh dist/efd-unpacker-${VERSION}-macos-portable.zip | cut -f1)
    echo "  ZIP archive: $zip_size"
fi

echo ""
echo "You can now distribute:"
echo "  - efd-unpacker-${VERSION}-macos.dmg for easy installation"
echo "  - efd-unpacker-${VERSION}-macos-portable.zip for portable use"
echo ""
echo "File association features:"
echo "  - .efd files will be associated with EFD Unpacker"
echo "  - Double-clicking .efd files will open them in the app"
echo "  - Files will be automatically selected for unpacking"
