# EFD Unpacker Makefile

.PHONY: help clean compile-translations verify-translations build-macos build-linux build-windows build-all test install-deps install-ci-deps setup-ci create-version generate-release-notes

# Определяем ОС
ifeq ($(OS),Windows_NT)
    PLATFORM := windows
    PYTHON := python
else
    UNAME_S := $(shell uname -s)
    ifeq ($(UNAME_S),Darwin)
        PLATFORM := macos
        PYTHON := python3
    else
        PLATFORM := linux
        PYTHON := python3
    endif
endif

help:
	@echo "EFD Unpacker - Доступные команды:"
	@echo ""
	@echo "  install-deps            - Установить зависимости для разработки"
	@echo "  install-ci-deps         - Установить зависимости для CI"
	@echo "  setup-ci                - Настроить среду CI (зависимости + переводы)"
	@echo "  create-version          - Создать version.txt из git тега"
	@echo "  compile-translations    - Скомпилировать .ts файлы в .qm"
	@echo "  verify-translations     - Проверить переводы в сборках"
	@echo "  filter-qt-translations  - Оставить только русский и английский переводы Qt"
	@echo "  clean                   - Очистить артефакты сборки"
	@echo ""
	@echo "  build-macos             - Собрать для macOS"
	@echo "  build-linux             - Собрать для Linux"
	@echo "  build-windows           - Собрать для Windows"
	@echo ""
	@echo "  test                    - Запустить тесты"
	@echo "  generate-release-notes  - Сгенерировать заметки о выпуске из истории git"
	@echo ""
	@echo "Текущая платформа: $(PLATFORM)"
	@echo "Python: $(PYTHON)"

# Установка зависимостей для разработки
install-deps:
	@echo "Installing development dependencies..."
	$(PYTHON) -m pip install --upgrade pip setuptools wheel
	pip install --prefer-binary -r requirements.txt
	@if [ -f requirements-test.txt ]; then \
		pip install --prefer-binary -r requirements-test.txt; \
	fi

# Установка зависимостей для CI
install-ci-deps:
	@echo "Installing CI dependencies for $(PLATFORM)..."
	@echo "Installing PyInstaller for builds..."
	pip install pyinstaller
	@if [ "$(PLATFORM)" = "linux" ]; then \
		echo "Installing Linux dependencies..."; \
		sudo apt-get update; \
		sudo apt-get install -y qt6-l10n-tools qttools5-dev-tools zip unzip wget libxcb-xinerama0 libxcb-shape0 libxkbcommon-x11-0 libxcb-keysyms1 libxcb-icccm4 libxcb-xkb1 libxcb-image0 libxcb-render-util0 dpkg-dev rpm; \
		apt-get install -y qt6-base-dev qt6-base-dev-tools qt6-tools-dev qt6-tools-dev-tools qt6-l10n-tools; \
		ln -sf /usr/bin/qmake6 /usr/bin/qmake; \
		echo "Installing appimagetool..."; \
		wget -O appimagetool "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"; \
		chmod +x appimagetool; \
		mv appimagetool /usr/local/bin/; \
	elif [ "$(PLATFORM)" = "macos" ]; then \
		echo "Installing macOS dependencies..."; \
		brew install create-dmg qt6; \
	elif [ "$(PLATFORM)" = "windows" ]; then \
		echo "Installing Windows dependencies..."; \
		echo "Installing WiX Toolset..."; \
		choco install wixtoolset --yes; \
		echo "Installing Qt Linguist tools..."; \
		choco install qt6-tools --yes; \
		echo "Qt Linguist tools installed successfully"; \
		# Добавляем lrelease.exe в PATH, если найден после установки через choco
		set LRELEASE_PATH="C:\\ProgramData\\chocolatey\\lib\\qt6-tools\\tools\\Qt6\\bin" && \
		if exist %LRELEASE_PATH%\\lrelease.exe ( \
		  set "PATH=%LRELEASE_PATH%;%PATH%" && \
		  echo "[DEBUG] lrelease.exe найден и добавлен в PATH: %LRELEASE_PATH%" \
		) else ( \
		  echo "[DEBUG] lrelease.exe не найден в %LRELEASE_PATH%" \
		); \
		where lrelease.exe || echo "[DEBUG] lrelease.exe не найден в PATH"; \
	fi
	@echo "CI dependencies installation completed for $(PLATFORM)"

# Настройка CI среды
setup-ci: install-ci-deps install-deps compile-translations
	@echo "CI environment setup complete"

# Создание version.txt из git тега
create-version:
	@echo "Creating version.txt from git tag..."
	@if [ -n "$(GITHUB_REF)" ]; then \
		VERSION=$$(echo $(GITHUB_REF) | sed 's/refs\/tags\/v//'); \
		if [ -z "$$VERSION" ]; then VERSION="dev"; fi; \
		echo "$$VERSION" > version.txt; \
		echo "Created version.txt with version: $$VERSION"; \
	elif [ -n "$(GITHUB_REF_NAME)" ]; then \
		VERSION=$$(echo $(GITHUB_REF_NAME) | sed 's/v//'); \
		echo "$$VERSION" > version.txt; \
		echo "Created version.txt with version: $$VERSION"; \
	else \
		echo "GITHUB_REF not set, using current git tag or 'dev'"; \
		VERSION=$$(git describe --tags --abbrev=0 2>/dev/null | sed 's/v//' || echo "dev"); \
		echo "$$VERSION" > version.txt; \
		echo "Created version.txt with version: $$VERSION"; \
	fi

clean:
	@echo "Cleaning build artifacts..."
	rm -rf build/
	rm -rf dist/
	rm -rf __pycache__/
	rm -rf .pytest_cache/
	rm -rf .coverage
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	rm -f EFDUnpacker.spec
	rm -f version.txt
	rm -f release_notes.md
	rm -f translations/*.qm

compile-translations: 
	@echo "Compiling translations..."
	@echo "[DEBUG] Поиск lrelease в системе:" && \
	  which lrelease || echo "[DEBUG] lrelease не найден в PATH"; \
	  ls -l /usr/lib/qt6/bin/lrelease 2>/dev/null || echo "[DEBUG] /usr/lib/qt6/bin/lrelease не найден"; \
	  ls -l /usr/lib/qt5/bin/lrelease 2>/dev/null || echo "[DEBUG] /usr/lib/qt5/bin/lrelease не найден"; \
	  ls -l /usr/bin/lrelease 2>/dev/null || echo "[DEBUG] /usr/bin/lrelease не найден"; \
	  ls -l /usr/local/bin/lrelease 2>/dev/null || echo "[DEBUG] /usr/local/bin/lrelease не найден"; \
	  echo "PATH=$$PATH"; \
	$(PYTHON) scripts/compile_translations.py

verify-translations:
	@echo "Verifying translations in builds..."
	$(PYTHON) scripts/verify_translations.py

filter-qt-translations:
	@echo "Filtering Qt translations (keeping only Russian and English)..."
	$(PYTHON) scripts/filter_qt_translations.py

# Linux build commands
build-linux-executable:
	@echo "Building Linux executable with PyInstaller..."
	pyinstaller --noconfirm EFDUnpacker.spec
	@if [ ! -f "dist/EFDUnpacker/EFDUnpacker" ]; then \
		echo "Error: EFDUnpacker executable not found in dist directory."; \
		exit 1; \
	fi
	@echo "Linux executable built successfully"

create-linux-appimage:
	@echo "Creating Linux AppImage..."
	@if command -v appimagetool >/dev/null 2>&1; then \
		mkdir -p AppDir/usr/bin AppDir/usr/share/applications AppDir/usr/share/icons/hicolor/256x256/apps; \
		cp dist/EFDUnpacker/EFDUnpacker AppDir/usr/bin/efd_unpacker; \
		if [ -d "dist/EFDUnpacker/translations" ]; then \
			mkdir -p AppDir/usr/bin/translations; \
			cp dist/EFDUnpacker/translations/*.qm AppDir/usr/bin/translations/; \
		fi; \
		if [ -f "resources/icon.png" ]; then \
			cp resources/icon.png AppDir/usr/share/icons/hicolor/256x256/apps/efd_unpacker.png; \
			cp resources/icon.png AppDir/efd_unpacker.png; \
		fi; \
		cp installer/linux/efd_unpacker.desktop AppDir/usr/share/applications/; \
		cp AppDir/usr/share/applications/efd_unpacker.desktop AppDir/; \
		cp installer/linux/AppRun AppDir/; \
		chmod +x AppDir/AppRun; \
		appimagetool AppDir dist/efd-unpacker-$$(cat version.txt)-linux.AppImage; \
		rm -rf AppDir; \
		echo "AppImage created successfully"; \
	else \
		echo "Warning: appimagetool not found. Skipping AppImage creation."; \
	fi

create-linux-deb:
	@echo "Creating Linux DEB package..."
	@if command -v dpkg-deb >/dev/null 2>&1; then \
		mkdir -p debian/DEBIAN debian/usr/bin debian/usr/share/applications debian/usr/share/icons/hicolor/256x256/apps debian/usr/share/mime/packages; \
		cp dist/EFDUnpacker/EFDUnpacker debian/usr/bin/efd_unpacker; \
		if [ -d "dist/EFDUnpacker/translations" ]; then \
			mkdir -p debian/usr/bin/translations; \
			cp dist/EFDUnpacker/translations/*.qm debian/usr/bin/translations/; \
		fi; \
		if [ -f "resources/icon.png" ]; then \
			cp resources/icon.png debian/usr/share/icons/hicolor/256x256/apps/efd_unpacker.png; \
		fi; \
		cp installer/linux/efd_unpacker.desktop debian/usr/share/applications/; \
		cp installer/linux/mime-info.xml debian/usr/share/mime/packages/; \
		cp installer/linux/control debian/DEBIAN/; \
		sed -i "s/VERSION_PLACEHOLDER/$$(cat version.txt)/g" debian/DEBIAN/control; \
		cp installer/linux/postinst debian/DEBIAN/; \
		cp installer/linux/prerm debian/DEBIAN/; \
		chmod +x debian/DEBIAN/postinst debian/DEBIAN/prerm; \
		dpkg-deb --build debian dist/efd-unpacker-$$(cat version.txt)-linux-amd64.deb; \
		rm -rf debian; \
		echo "DEB package created successfully"; \
	else \
		echo "Warning: dpkg-deb not found. Skipping DEB package creation."; \
	fi

create-linux-rpm:
	@echo "Creating Linux RPM package..."
	@if command -v rpmbuild >/dev/null 2>&1; then \
		mkdir -p rpmbuild/BUILD rpmbuild/BUILDROOT rpmbuild/RPMS rpmbuild/SOURCES rpmbuild/SPECS; \
		mkdir -p rpm_temp/usr/bin rpm_temp/usr/share/applications rpm_temp/usr/share/icons/hicolor/256x256/apps rpm_temp/usr/share/mime/packages; \
		cp dist/EFDUnpacker/EFDUnpacker rpm_temp/usr/bin/efd_unpacker; \
		if [ -d "dist/EFDUnpacker/translations" ]; then \
			mkdir -p rpm_temp/usr/bin/translations; \
			cp dist/EFDUnpacker/translations/*.qm rpm_temp/usr/bin/translations/; \
		fi; \
		if [ -f "resources/icon.png" ]; then \
			cp resources/icon.png rpm_temp/usr/share/icons/hicolor/256x256/apps/efd_unpacker.png; \
		fi; \
		cp installer/linux/efd_unpacker.desktop rpm_temp/usr/share/applications/; \
		cp installer/linux/mime-info.xml rpm_temp/usr/share/mime/packages/; \
		cp installer/linux/efd-unpacker.spec.in rpmbuild/SPECS/efd-unpacker.spec; \
		sed -i "s/VERSION_PLACEHOLDER/$$(cat version.txt)/g" rpmbuild/SPECS/efd-unpacker.spec; \
		tar -czf rpmbuild/SOURCES/efd-unpacker-$$(cat version.txt).tar.gz -C rpm_temp .; \
		rpmbuild --define "_topdir $(PWD)/rpmbuild" -bb rpmbuild/SPECS/efd-unpacker.spec; \
		cp rpmbuild/RPMS/*/efd-unpacker-*.rpm dist/; \
		rm -rf rpmbuild rpm_temp; \
		echo "RPM package created successfully"; \
	else \
		echo "Warning: rpmbuild not found. Skipping RPM package creation."; \
	fi

create-linux-archives:
	@echo "Creating Linux portable archives..."
	cd dist && zip -r efd-unpacker-$$(cat ../version.txt)-linux-portable.zip EFDUnpacker/
	cd dist && tar -czf efd-unpacker-$$(cat ../version.txt)-linux-portable.tar.gz EFDUnpacker/
	@echo "Linux archives created successfully"

show-linux-results:
	@echo ""
	@echo "Linux build completed successfully!"
	@echo "Files created:"
	@echo "  - dist/EFDUnpacker/ (executable directory)"
	@if [ -f "dist/efd-unpacker-$$(cat version.txt)-linux.AppImage" ]; then \
		echo "  - dist/efd-unpacker-$$(cat version.txt)-linux.AppImage (AppImage)"; \
	fi
	@if [ -f "dist/efd-unpacker-$$(cat version.txt)-linux-amd64.deb" ]; then \
		echo "  - dist/efd-unpacker-$$(cat version.txt)-linux-amd64.deb (DEB package)"; \
	fi
	@if [ -f "dist/efd-unpacker-$$(cat version.txt)-linux-*.rpm" ]; then \
		echo "  - dist/efd-unpacker-$$(cat version.txt)-linux-*.rpm (RPM package)"; \
	fi
	@echo "  - dist/efd-unpacker-$$(cat version.txt)-linux-portable.zip (portable ZIP)"
	@echo "  - dist/efd-unpacker-$$(cat version.txt)-linux-portable.tar.gz (portable TAR.GZ)"
	@echo ""
	@echo "File sizes:"
	@if [ -d "dist/EFDUnpacker" ]; then \
		exe_size=$$(du -sh dist/EFDUnpacker | cut -f1); \
		echo "  Executable directory: $$exe_size"; \
	fi
	@if [ -f "dist/efd-unpacker-$$(cat version.txt)-linux.AppImage" ]; then \
		appimage_size=$$(du -sh dist/efd-unpacker-$$(cat version.txt)-linux.AppImage | cut -f1); \
		echo "  AppImage: $$appimage_size"; \
	fi
	@if [ -f "dist/efd-unpacker-$$(cat version.txt)-linux-amd64.deb" ]; then \
		deb_size=$$(du -sh dist/efd-unpacker-$$(cat version.txt)-linux-amd64.deb | cut -f1); \
		echo "  DEB package: $$deb_size"; \
	fi
	@if [ -f "dist/efd-unpacker-$$(cat version.txt)-linux-portable.zip" ]; then \
		zip_size=$$(du -sh dist/efd-unpacker-$$(cat version.txt)-linux-portable.zip | cut -f1); \
		echo "  ZIP archive: $$zip_size"; \
	fi
	@if [ -f "dist/efd-unpacker-$$(cat version.txt)-linux-portable.tar.gz" ]; then \
		tar_size=$$(du -sh dist/efd-unpacker-$$(cat version.txt)-linux-portable.tar.gz | cut -f1); \
		echo "  TAR.GZ archive: $$tar_size"; \
	fi

# Windows build commands
build-windows-executable:
	@echo "Building Windows executable with PyInstaller..."
	pyinstaller --noconfirm --onefile --windowed $(if $(wildcard resources/icon.ico),--icon=resources/icon.ico,) --name=EFDUnpacker --add-data="translations/*.qm;translations" src/main.py
	@if [ ! -f "dist/EFDUnpacker.exe" ]; then \
		echo "Error: EFDUnpacker.exe not found in dist directory."; \
		exit 1; \
	fi
	@echo "Windows executable built successfully"

create-windows-msi:
	@echo "Creating Windows MSI installer..."
	@if command -v candle >/dev/null 2>&1 && command -v light >/dev/null 2>&1; then \
		echo "WiX Toolset found, creating MSI installer..."; \
		VERSION=$$(cat version.txt); \
		sed "s/VERSION_PLACEHOLDER/$$VERSION/g" installer/windows/installer.wxs > installer/windows/installer_temp.wxs; \
		candle installer/windows/installer_temp.wxs -out installer/windows/installer.wixobj; \
		if [ $$? -eq 0 ]; then \
			light installer/windows/installer.wixobj -out dist/efd-unpacker-$$VERSION-windows.msi -ext WixUIExtension -loc installer/windows/installer_en.wxl -loc installer/windows/installer_ru.wxl; \
			if [ $$? -eq 0 ]; then \
				echo "MSI installer created successfully"; \
			else \
				echo "Error: WiX linking failed."; \
				exit 1; \
			fi; \
		else \
			echo "Error: WiX compilation failed."; \
			exit 1; \
		fi; \
		rm -f installer/windows/installer_temp.wxs installer/windows/installer.wixobj; \
	else \
		echo "Warning: WiX Toolset not found. Skipping MSI installer creation."; \
		echo "Download from: https://wixtoolset.org/releases/"; \
		echo "Or install via Chocolatey: choco install wixtoolset"; \
	fi

create-windows-zip:
	@echo "Creating Windows portable ZIP archive..."
	@VERSION=$$(cat version.txt); \
	cd dist && zip -r efd-unpacker-$$VERSION-windows-portable.zip EFDUnpacker.exe translations/ && cd ..
	@echo "Windows ZIP archive created successfully"

show-windows-results:
	@echo ""
	@echo "Windows build completed successfully!"
	@echo "Files created:"
	@echo "  - dist/EFDUnpacker.exe (executable)"
	@VERSION=$$(cat version.txt); \
	if [ -f "dist/efd-unpacker-$$VERSION-windows.msi" ]; then \
		echo "  - dist/efd-unpacker-$$VERSION-windows.msi (installer)"; \
	fi
	@echo "  - dist/efd-unpacker-$$VERSION-windows-portable.zip (portable version)"
	@echo ""
	@echo "File sizes:"
	@if [ -f "dist/EFDUnpacker.exe" ]; then \
		exe_size=$$(du -sh dist/EFDUnpacker.exe | cut -f1); \
		echo "  Executable: $$exe_size"; \
	fi
	@VERSION=$$(cat version.txt); \
	if [ -f "dist/efd-unpacker-$$VERSION-windows.msi" ]; then \
		msi_size=$$(du -sh dist/efd-unpacker-$$VERSION-windows.msi | cut -f1); \
		echo "  MSI installer: $$msi_size"; \
	fi
	@if [ -f "dist/efd-unpacker-$$VERSION-windows-portable.zip" ]; then \
		zip_size=$$(du -sh dist/efd-unpacker-$$VERSION-windows-portable.zip | cut -f1); \
		echo "  ZIP archive: $$zip_size"; \
	fi
	@echo ""
	@echo "You can now distribute:"
	@if [ -f "dist/efd-unpacker-$$VERSION-windows.msi" ]; then \
		echo "  - efd-unpacker-$$VERSION-windows.msi for easy installation"; \
	fi
	@echo "  - efd-unpacker-$$VERSION-windows-portable.zip for portable use"
	@echo ""
	@echo "File association features:"
	@echo "  - .efd files will be associated with EFD Unpacker"
	@echo "  - Double-clicking .efd files will open them in the app"
	@echo "  - Files will be automatically selected for unpacking"

build-macos: clean create-version compile-translations check generate-spec
	@echo "Building for macOS..."
	@$(MAKE) build-macos-app
	@$(MAKE) filter-qt-translations
	@$(MAKE) create-macos-dmg
	@$(MAKE) create-macos-zip
	@$(MAKE) show-macos-results
	@$(MAKE) verify-translations

build-linux: clean create-version compile-translations check generate-spec
	@echo "Building for Linux..."
	@$(MAKE) build-linux-executable
	@$(MAKE) create-linux-appimage
	@$(MAKE) create-linux-deb
	@$(MAKE) create-linux-rpm
	@$(MAKE) create-linux-archives
	@$(MAKE) show-linux-results
	@$(MAKE) verify-translations

build-windows: clean create-version compile-translations check generate-spec
	@echo "Building for Windows..."
	@$(MAKE) build-windows-executable
	@$(MAKE) create-windows-msi
	@$(MAKE) create-windows-zip
	@$(MAKE) show-windows-results
	@$(MAKE) verify-translations

test:
	@echo "Running tests..."
	$(PYTHON) -m pytest tests/ -v

generate-release-notes:
	@echo "Generating release notes..."
	$(PYTHON) scripts/generate_release_notes.py > release_notes.md
	@echo "Release notes generated: release_notes.md"

# Проверка готовности к сборке
check:
	@echo "=== Проверка готовности к сборке ==="
	@echo "Платформа: $(PLATFORM)"
	@echo "Python: $(shell $(PYTHON) --version 2>&1)"
	@echo ""
	@echo "Зависимости:"
	@echo "  PyInstaller: $(shell $(PYTHON) -c 'import PyInstaller; print("✓")' 2>/dev/null || echo "✗")"
	@echo "  Python: $(shell command -v python3 >/dev/null && echo "✓" || echo "✗")"
	@echo ""
	@echo "Файлы проекта:"
	@echo "  Version file: $(shell [ -f version.txt ] && echo "✓" || echo "✗")"
	@echo "  Translations dir: $(shell [ -d translations ] && echo "✓" || echo "✗")"
	@echo "  Translations (ru.qm): $(shell [ -f translations/ru.qm ] && echo "✓" || echo "✗")"
	@echo ""
	@echo "Проверка критических файлов:"
	@if [ ! -f "version.txt" ]; then \
		echo "  ✗ Error: version.txt not found. Run 'make create-version' first."; \
		exit 1; \
	else \
		echo "  ✓ version.txt found"; \
	fi
	@if [ ! -d "translations" ]; then \
		echo "  ✗ Error: translations directory not found."; \
		exit 1; \
	else \
		echo "  ✓ translations directory found"; \
	fi
	@if [ ! -f "translations/ru.qm" ]; then \
		echo "  ✗ Error: translations/ru.qm not found. Run 'make translations' first."; \
		exit 1; \
	else \
		echo "  ✓ translations/ru.qm found"; \
	fi
	@echo ""
	@echo "Проверка платформо-специфичных зависимостей:"
	@if [ "$(PLATFORM)" = "macos" ]; then \
		if ! command -v brew &> /dev/null; then \
			echo "  ✗ Error: Homebrew not found. Please install Homebrew first:"; \
			echo "    /bin/bash -c \$$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"; \
			exit 1; \
		else \
			echo "  ✓ Homebrew found"; \
		fi; \
		if ! command -v create-dmg &> /dev/null; then \
			echo "  ✗ Error: create-dmg not found. Run 'make install-ci-deps' first."; \
			exit 1; \
		else \
			echo "  ✓ create-dmg found"; \
		fi; \
	fi
	@echo ""
	@echo "✓ Все проверки пройдены успешно!"



generate-spec:
	@echo "Generating PyInstaller spec file..."
	$(PYTHON) scripts/generate_spec.py


# macOS сборка - отдельные этапы
build-macos-app:
	@echo "Building .app bundle using spec file..."
	@$(MAKE) check-macos-icon
	pyinstaller --noconfirm EFDUnpacker.spec
	@if [ ! -d "dist/EFDUnpacker.app" ]; then \
		echo "Error: EFDUnpacker.app not found in dist directory."; \
		exit 1; \
	fi
	@echo "App bundle created successfully"

check-macos-icon:
	@if [ ! -f "resources/icon.icns" ]; then \
		echo "Warning: resources/icon.icns not found. Using default icon."; \
	else \
		echo "Using custom icon: resources/icon.icns"; \
	fi

create-macos-dmg:
	@echo "Creating DMG installer..."
	@VERSION=$$(cat version.txt | tr -d ' \t\n\r'); \
	create-dmg \
		--volname "EFD Unpacker" \
		--volicon "resources/icon.icns" \
		--window-pos 200 120 \
		--window-size 600 300 \
		--icon-size 100 \
		--icon "EFDUnpacker.app" 175 120 \
		--hide-extension "EFDUnpacker.app" \
		--app-drop-link 425 120 \
		"dist/efd-unpacker-$${VERSION}-macos.dmg" \
		"dist/EFDUnpacker.app"

create-macos-zip:
	@echo "Creating ZIP archive..."
	@VERSION=$$(cat version.txt | tr -d ' \t\n\r'); \
	cd dist && zip -r efd-unpacker-$${VERSION}-macos-portable.zip EFDUnpacker.app && cd ..

show-macos-results:
	@echo ""
	@echo "Build completed successfully!"
	@echo "Files created:"
	@echo "  - dist/EFDUnpacker.app/ (app bundle)"
	@VERSION=$$(cat version.txt | tr -d ' \t\n\r'); \
	if [ -f "dist/efd-unpacker-$${VERSION}-macos.dmg" ]; then \
		echo "  - dist/efd-unpacker-$${VERSION}-macos.dmg (installer)"; \
	fi
	@echo "  - dist/efd-unpacker-$${VERSION}-macos-portable.zip (portable version)"
	@echo ""
	@echo "File sizes:"
	@if [ -d "dist/EFDUnpacker.app" ]; then \
		app_size=$$(du -sh dist/EFDUnpacker.app | cut -f1); \
		echo "  App bundle: $$app_size"; \
	fi
	@VERSION=$$(cat version.txt | tr -d ' \t\n\r'); \
	if [ -f "dist/efd-unpacker-$${VERSION}-macos.dmg" ]; then \
		dmg_size=$$(du -sh dist/efd-unpacker-$${VERSION}-macos.dmg | cut -f1); \
		echo "  DMG installer: $$dmg_size"; \
	fi
	@if [ -f "dist/efd-unpacker-$${VERSION}-macos-portable.zip" ]; then \
		zip_size=$$(du -sh dist/efd-unpacker-$${VERSION}-macos-portable.zip | cut -f1); \
		echo "  ZIP archive: $$zip_size"; \
	fi
	@echo ""
	@echo "You can now distribute:"
	@if [ -f "dist/efd-unpacker-$${VERSION}-macos.dmg" ]; then \
		echo "  - efd-unpacker-$${VERSION}-macos.dmg for easy installation"; \
	fi
	@echo "  - efd-unpacker-$${VERSION}-macos-portable.zip for portable use"
	@echo ""
	@echo "File association features:"
	@echo "  - .efd files will be associated with EFD Unpacker"
	@echo "  - Double-clicking .efd files will open them in the app"
	@echo "  - Files will be automatically selected for unpacking" 