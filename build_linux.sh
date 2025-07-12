#!/bin/bash

# Установка строгого режима
set -e

echo "Building EFD Unpacker for Linux..."

# Читаем версию из файла
if [ -f "version.txt" ]; then
    APP_VERSION=$(cat version.txt | tr -d ' \t\n\r')
    echo "Version from version.txt: $APP_VERSION"
else
    echo "Error: version.txt not found."
    echo "This file should be created automatically by GitHub Actions from the git tag."
    echo "For local builds, please create version.txt with the version number."
    echo "Example: echo '1.0.0' > version.txt"
    exit 1
fi

# Определяем дистрибутив
if [ -f /etc/os-release ]; then
    . /etc/os-release
    DISTRO=$NAME
    DISTRO_VERSION=$VERSION_ID
    echo "Detected distribution: $DISTRO $DISTRO_VERSION"
else
    DISTRO="Unknown"
    echo "Warning: Could not detect distribution"
fi

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

# Проверяем наличие иконки
if [ ! -f "resources/icon.png" ]; then
    echo "Warning: resources/icon.png not found. Using default icon."
    icon_option=""
else
    icon_option="--icon=resources/icon.png"
    echo "Using custom icon: resources/icon.png"
fi

# Очищаем предыдущие сборки
echo "Cleaning previous builds..."
if [ -d "build" ]; then
    rm -rf build
fi
if [ -d "dist" ]; then
    rm -rf dist
fi
if [ -d "AppDir" ]; then
    rm -rf AppDir
fi

# Сборка исполняемого файла
echo "Building executable with PyInstaller..."
pyinstaller --noconfirm --onedir --windowed $icon_option --name=EFDUnpacker main.py

if [ $? -ne 0 ]; then
    echo "Error: PyInstaller build failed."
    exit 1
fi

echo "Executable built successfully"

# Проверяем, что исполняемый файл создался
if [ ! -f "dist/EFDUnpacker/EFDUnpacker" ]; then
    echo "Error: EFDUnpacker executable not found in dist directory."
    exit 1
fi

# Создание AppImage (если доступен appimagetool)
if command -v appimagetool &> /dev/null; then
    echo "Creating AppImage..."
    
    # Создаем структуру AppDir
    mkdir -p AppDir/usr/bin
    mkdir -p AppDir/usr/share/applications
    mkdir -p AppDir/usr/share/icons/hicolor/256x256/apps
    
    echo "Created AppDir structure"
    
    # Копируем исполняемый файл
    cp dist/EFDUnpacker/EFDUnpacker AppDir/usr/bin/efd_unpacker
    echo "Copied executable to AppDir/usr/bin/efd_unpacker"
    
    # Копируем иконку если есть
    if [ -f "resources/icon.png" ]; then
        cp resources/icon.png AppDir/usr/share/icons/hicolor/256x256/apps/efd_unpacker.png
        cp resources/icon.png AppDir/efd_unpacker.png
        icon_path="efd_unpacker"
        echo "Copied icon to AppDir/usr/share/icons/hicolor/256x256/apps/efd_unpacker.png and AppDir/efd_unpacker.png"
    else
        icon_path=""
        echo "No icon found, skipping icon copy"
    fi
    
    # Создаем .desktop файл
    echo "Creating .desktop file..."
    cat > AppDir/usr/share/applications/efd_unpacker.desktop << EOF
[Desktop Entry]
Name=EFD Unpacker
Comment=Unpack EFD files
Exec=efd_unpacker %f
Icon=efd_unpacker
Type=Application
Categories=Utility;FileManager;
MimeType=application/x-efd;
Terminal=false
EOF

    echo "Desktop file created at AppDir/usr/share/applications/efd_unpacker.desktop"
    
    # Копируем .desktop файл в корень AppDir (appimagetool ожидает его там)
    cp AppDir/usr/share/applications/efd_unpacker.desktop AppDir/efd_unpacker.desktop
    echo "Copied .desktop file to AppDir/efd_unpacker.desktop"
    
    # Проверка наличия .desktop файла
    if [ ! -f "AppDir/usr/share/applications/efd_unpacker.desktop" ]; then
        echo "ERROR: Desktop file not found!"
        echo "Contents of AppDir/usr/share/applications/:"
        ls -la AppDir/usr/share/applications/
        exit 1
    else
        echo "Desktop file exists and contains:"
        cat AppDir/usr/share/applications/efd_unpacker.desktop
    fi
    
    # Создаем AppRun
    echo "Creating AppRun..."
    cat > AppDir/AppRun << EOF
#!/bin/bash
HERE="\$(dirname "\$(readlink -f "\${0}")")"
export PATH="\${HERE}"/usr/bin/:"\${PATH}"
export LD_LIBRARY_PATH="\${HERE}"/usr/lib/:"\${LD_LIBRARY_PATH}"
exec "\${HERE}"/usr/bin/efd_unpacker "\$@"
EOF
    chmod +x AppDir/AppRun
    echo "AppRun created and made executable"
    
    # Показываем структуру AppDir
    echo "AppDir structure:"
    find AppDir -type f
    echo "Desktop file in root:"
    ls -la AppDir/*.desktop
    
    # Создаем AppImage
    echo "Creating AppImage with appimagetool..."
    appimagetool AppDir dist/efd-unpacker-${APP_VERSION}-linux.AppImage
    
    if [ $? -eq 0 ]; then
        echo "AppImage created successfully"
    else
        echo "Warning: AppImage creation failed"
    fi
else
    echo "Warning: appimagetool not found. Skipping AppImage creation."
    echo "You can install appimagetool from: https://github.com/AppImage/appimagetool"
fi

# Создание DEB пакета (если доступен dpkg-deb)
if command -v dpkg-deb &> /dev/null; then
    echo "Creating DEB package..."
    
    # Создаем структуру пакета
    mkdir -p debian/DEBIAN
    mkdir -p debian/usr/bin
    mkdir -p debian/usr/share/applications
    mkdir -p debian/usr/share/icons/hicolor/256x256/apps
    
    # Копируем файлы
    cp dist/EFDUnpacker/EFDUnpacker debian/usr/bin/efd_unpacker
    if [ -f "resources/icon.png" ]; then
        cp resources/icon.png debian/usr/share/icons/hicolor/256x256/apps/efd_unpacker.png
    fi
    
    # Создаем .desktop файл
    cat > debian/usr/share/applications/efd_unpacker.desktop << EOF
[Desktop Entry]
Name=EFD Unpacker
Comment=Unpack EFD files
Exec=efd_unpacker %f
Icon=efd_unpacker
Type=Application
Categories=Utility;FileManager;
MimeType=application/x-efd;
Terminal=false
EOF
    
    # Создаем control файл
    cat > debian/DEBIAN/control << EOF
Package: efd-unpacker
Version: $APP_VERSION
Section: utils
Priority: optional
Architecture: amd64
Depends: libc6
Maintainer: Ingvar Consulting <info@ingvarconsulting.com>
Description: EFD Unpacker
 A tool for unpacking EFD (Electronic Fiscal Document) files.
 Provides a graphical interface for easy file extraction.
EOF
    
    # Создаем DEB пакет
    mkdir -p dist
    DEB_FILE="dist/efd-unpacker_${APP_VERSION}_amd64.deb"
    dpkg-deb --build debian "$DEB_FILE"
    
    if [ $? -eq 0 ]; then
        echo "DEB package created successfully"
    else
        echo "Warning: DEB package creation failed"
    fi
    
    # Очищаем временные файлы
    rm -rf debian
fi

# Создание RPM пакета (если доступен rpmbuild)
if command -v rpmbuild &> /dev/null; then
    echo "Creating RPM package..."
    
    # Создаем структуру для RPM
    mkdir -p rpmbuild/{BUILD,RPMS,SOURCES,SPECS,SRPMS,BUILDROOT}
    
    # Создаем структуру файлов для RPM
    mkdir -p rpmbuild/BUILDROOT/efd-unpacker-$APP_VERSION-1.x86_64/usr/bin
    mkdir -p rpmbuild/BUILDROOT/efd-unpacker-$APP_VERSION-1.x86_64/usr/share/applications
    mkdir -p rpmbuild/BUILDROOT/efd-unpacker-$APP_VERSION-1.x86_64/usr/share/icons/hicolor/256x256/apps
    
    # Копируем файлы в правильные места
    cp dist/EFDUnpacker/EFDUnpacker rpmbuild/BUILDROOT/efd-unpacker-$APP_VERSION-1.x86_64/usr/bin/efd_unpacker
    chmod +x rpmbuild/BUILDROOT/efd-unpacker-$APP_VERSION-1.x86_64/usr/bin/efd_unpacker
    
    if [ -f "resources/icon.png" ]; then
        cp resources/icon.png rpmbuild/BUILDROOT/efd-unpacker-$APP_VERSION-1.x86_64/usr/share/icons/hicolor/256x256/apps/efd_unpacker.png
    fi
    
    # Создаем .desktop файл
    cat > rpmbuild/BUILDROOT/efd-unpacker-$APP_VERSION-1.x86_64/usr/share/applications/efd_unpacker.desktop << EOF
[Desktop Entry]
Name=EFD Unpacker
Comment=Unpack EFD files
Exec=efd_unpacker %f
Icon=efd_unpacker
Type=Application
Categories=Utility;FileManager;
MimeType=application/x-efd;
Terminal=false
EOF
    
    # Создаем spec файл
    cat > rpmbuild/SPECS/efd-unpacker.spec << EOF
Name:           efd-unpacker
Version:        $APP_VERSION
Release:        1
Summary:        EFD Unpacker - Tool for unpacking EFD files

License:        MIT
URL:            https://github.com/IngvarConsulting/efd_unpacker
Source0:        %{name}-%{version}.tar.gz

BuildArch:      x86_64
Requires:       glibc

%description
EFD Unpacker is a tool for unpacking EFD (Electronic Fiscal Document) files.
It provides a graphical interface for easy file extraction.

%files
%{_bindir}/efd_unpacker
%{_datadir}/applications/efd_unpacker.desktop
%{_datadir}/icons/hicolor/256x256/apps/efd_unpacker.png

%post
update-desktop-database

%postun
update-desktop-database
EOF
    
    # Создаем архив исходников
    tar -czf rpmbuild/SOURCES/efd-unpacker-$APP_VERSION.tar.gz dist/EFDUnpacker/
    
    # Собираем RPM
    rpmbuild --define "_topdir $(pwd)/rpmbuild" -bb rpmbuild/SPECS/efd-unpacker.spec
    
    if [ $? -eq 0 ]; then
        # Находим и копируем созданный RPM файл
        RPM_FILE=$(find rpmbuild/RPMS/x86_64 -name "efd-unpacker-$APP_VERSION-1.x86_64.rpm" -type f)
        if [ -n "$RPM_FILE" ]; then
            cp "$RPM_FILE" dist/
            echo "RPM package created successfully"
        else
            echo "Warning: RPM file not found after build"
        fi
    else
        echo "Warning: RPM package creation failed"
    fi
    
    # Очищаем временные файлы
    rm -rf rpmbuild
fi

# Создание ZIP архива
echo "Creating ZIP archive..."
cd dist
zip -r efd-unpacker-${APP_VERSION}-linux-portable.zip EFDUnpacker/
cd ..

# Создание TAR.GZ архива
echo "Creating TAR.GZ archive..."
cd dist
tar -czf efd-unpacker-${APP_VERSION}-linux-portable.tar.gz EFDUnpacker/
cd ..

# Показываем результаты
echo ""
echo "Build completed successfully!"
echo "Files created:"
echo "  - dist/EFDUnpacker/ (executable folder)"
echo "  - dist/efd-unpacker-${APP_VERSION}-linux-portable.zip (portable version)"
echo "  - dist/efd-unpacker-${APP_VERSION}-linux-portable.tar.gz (portable version)"

if [ -f "dist/efd-unpacker-${APP_VERSION}-linux.AppImage" ]; then
    echo "  - dist/efd-unpacker-${APP_VERSION}-linux.AppImage (AppImage package)"
fi

if [ -f "dist/efd-unpacker_${APP_VERSION}_amd64.deb" ]; then
    echo "  - dist/efd-unpacker_${APP_VERSION}_amd64.deb (Debian package)"
fi

if [ -f "dist/efd-unpacker-$APP_VERSION-1"*.rpm ]; then
    echo "  - dist/efd-unpacker-$APP_VERSION-1*.rpm (RPM package)"
fi

# Показываем размеры файлов
echo ""
echo "File sizes:"
if [ -d "dist/EFDUnpacker" ]; then
    folder_size=$(du -sh dist/EFDUnpacker | cut -f1)
    echo "  Executable folder: $folder_size"
fi
if [ -f "dist/efd-unpacker-${APP_VERSION}-linux-portable.zip" ]; then
    zip_size=$(du -sh dist/efd-unpacker-${APP_VERSION}-linux-portable.zip | cut -f1)
    echo "  ZIP archive: $zip_size"
fi
if [ -f "dist/efd-unpacker-${APP_VERSION}-linux-portable.tar.gz" ]; then
    tar_size=$(du -sh dist/efd-unpacker-${APP_VERSION}-linux-portable.tar.gz | cut -f1)
    echo "  TAR.GZ archive: $tar_size"
fi

