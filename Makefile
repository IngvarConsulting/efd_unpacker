# EFD Unpacker Makefile

.PHONY: help clean compile-translations build-macos build-linux build-windows test install-deps create-version generate-release-notes check generate-spec create-linux-archives create-windows-zip create-macos-zip verify-translations

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
	@echo "  install-deps            - Установить зависимости для разработки"
	@echo "  create-version          - Создать version.txt из git тега"
	@echo "  compile-translations    - Скомпилировать .ts файлы в .qm (требует lrelease из qttools5-dev-tools)"
	@echo "  clean                   - Очистить артефакты сборки"
	@echo "  build-macos             - Собрать для macOS (portable .zip, .dmg)"
	@echo "  build-linux             - Собрать для Linux (portable .zip/.tar.gz, AppImage, .deb, .rpm)"
	@echo "  build-windows           - Собрать для Windows (portable .zip, .msi)"
	@echo "  test                    - Запустить тесты"
	@echo "  generate-spec           - Сгенерировать PyInstaller spec файл"
	@echo "  generate-release-notes  - Сгенерировать заметки о выпуске из истории git"
	@echo "  verify-translations     - Проверить переводы в сборках"
	@echo "  check                   - Проверить готовность к сборке"
	@echo ""
	@echo "Текущая платформа: $(PLATFORM)"
	@echo "Python: $(PYTHON)"

check:
	@if [ "$(PLATFORM)" = "windows" ]; then chcp 65001 >nul; fi
	@sh -c '\
	FAILED=0; \
	echo "=== Проверка готовности к сборке ==="; \
	echo "Платформа: $(PLATFORM)"; \
	echo "Python: $$($(PYTHON) --version 2>&1)"; \
	echo ""; \
	echo "Зависимости:"; \
	$(PYTHON) -c "import PyInstaller" 2>/dev/null && echo "✓ PyInstaller" || { echo "✗ PyInstaller"; FAILED=1; }; \
	command -v python3 >/dev/null && echo "✓ Python" || { echo "✗ Python"; FAILED=1; }; \
	echo ""; \
	echo "Файлы проекта:"; \
	[ -f version.txt ] && echo "✓ Version file" || { echo "✗ Version file"; FAILED=1; }; \
	[ -d translations ] && echo "✓ Translations dir" || { echo "✗ Translations dir"; FAILED=1; }; \
	[ -f translations/ru.qm ] && echo "✓ Translations (ru.qm)" || { echo "✗ Translations (ru.qm)"; FAILED=1; }; \
	echo ""; \
	if [ $$FAILED -eq 1 ]; then \
		echo "✗ Есть ошибки!"; \
		exit 1; \
	else \
		echo "✓ Все проверки пройдены успешно!"; \
	fi'

build-macos: clean create-version compile-translations check generate-spec
	@echo "Building for macOS..."
	@$(MAKE) build-macos-app
	@$(MAKE) create-macos-zip
	@$(MAKE) create-macos-dmg
	@$(MAKE) verify-translations

build-linux: clean create-version compile-translations check generate-spec
	@echo "Building for Linux..."
	@$(MAKE) build-linux-executable
	@$(MAKE) create-linux-archives
	@$(MAKE) create-linux-appimage
	@$(MAKE) create-linux-deb
	@$(MAKE) create-linux-rpm
	@$(MAKE) verify-translations

build-windows: clean create-version compile-translations check generate-spec
	@echo "Building for Windows..."
	@$(MAKE) build-windows-executable
	@$(MAKE) create-windows-zip
	@$(MAKE) create-windows-msi
	@$(MAKE) verify-translations

test:
	@echo "Running tests..."
	$(PYTHON) -m pytest tests/ -v

generate-spec:
	@echo "Generating EFDUnpacker.spec from template..."
	@VERSION=$$(cat version.txt); \
	QM_FILES=$$(for f in translations/*.qm; do printf "('%s', 'translations'), " "$$f"; done | sed 's/, $$//'); \
	sed -e "s#{{QM_FILES}}#$$QM_FILES#" \
	    -e "s#{{VERSION}}#$$VERSION#g" \
	    installer/EFDUnpacker.spec.in > EFDUnpacker.spec; \
	
generate-release-notes:
	@echo "Generating release notes..."
	$(PYTHON) scripts/generate_release_notes.py > release_notes.md
	
install-deps:
	@echo "Installing development dependencies..."
	$(PYTHON) -m pip install --upgrade pip setuptools wheel PyInstaller
	$(PYTHON) -m pip install --only-binary=:all: -r requirements.txt
	$(PYTHON) -m pip install --only-binary=:all: -r requirements-test.txt;
	@if [ "$(PLATFORM)" = "linux" ]; then \
		sudo apt-get update; \
		sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
			libegl1 libglib2.0-0 libfontconfig1 libxkbcommon0 libgl1 libdbus-1-3 qtbase5-dev qttools5-dev-tools; \
	fi
	@if [ "$(PLATFORM)" = "macos" ]; then \
		brew list qt@5 >/dev/null 2>&1 || brew install qt@5; \
		brew link --force qt@5; \
	fi
	@if [ "$(PLATFORM)" = "windows" ]; then \
		choco install qt5-default -y; \
		set "QTPATH=%ProgramFiles%\\Qt\\5.15.2\\mingw81_64\\bin"; \
		set "PATH=%QTPATH%;%PATH%"; \
		echo "[INFO] lrelease.exe должен быть доступен: %QTPATH%"; \
	fi

create-version:
	@echo "Creating version.txt from git tag or commit..."
	@if [ -n "$(VERSION)" ]; then \
		VER="$(VERSION)"; \
	elif git describe --tags --exact-match >/dev/null 2>&1; then \
		VER=$$(git describe --tags --exact-match | sed 's/^v//'); \
	elif git describe --tags >/dev/null 2>&1; then \
		VER=$$(git describe --tags --always | sed 's/^v//'); \
	else \
		VER="dev"; \
	fi; \
	echo "$$VER" > version.txt; \
	
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
	@command -v lrelease >/dev/null 2>&1 || { echo "[ERROR] lrelease not found! Please install Qt Linguist tools (lrelease)."; exit 1; }
	@echo "Compiling translations with lrelease..."
	@for ts in translations/*.ts; do \
	  lrelease "$$ts" -qm "translations/$$(basename $$ts .ts).qm"; \
	done

verify-translations:
	@echo "Verifying translations in builds..."
	$(PYTHON) scripts/verify_translations.py

# Linux build commands
build-linux-executable:
	@echo "Building Linux executable with PyInstaller..."
	pyinstaller --noconfirm EFDUnpacker.spec
	@if [ ! -f "dist/EFDUnpacker/EFDUnpacker" ]; then \
		echo "Error: EFDUnpacker executable not found in dist directory."; \
		exit 1; \
	fi
	
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
	else \
		echo "Warning: rpmbuild not found. Skipping RPM package creation."; \
	fi

create-linux-archives:
	@echo "Creating Linux portable archives..."
	cd dist && zip -r efd-unpacker-$$(cat ../version.txt)-linux-portable.zip EFDUnpacker/
	cd dist && tar -czf efd-unpacker-$$(cat ../version.txt)-linux-portable.tar.gz EFDUnpacker/
	
# Windows build commands
build-windows-executable:
	@echo "Building Windows executable with PyInstaller..."
	pyinstaller --noconfirm --onefile --windowed $(if $(wildcard resources/icon.ico),--icon=resources/icon.ico,) --name=EFDUnpacker --add-data="translations/*.qm;translations" main.py
	@if [ ! -f "dist/EFDUnpacker.exe" ]; then \
		echo "Error: EFDUnpacker.exe not found in dist directory."; \
		exit 1; \
	fi

create-windows-zip:
	@echo "Creating Windows portable ZIP archive..."
	@VERSION=$$(cat version.txt); \
	cd dist && zip -r efd-unpacker-$$VERSION-windows-portable.zip EFDUnpacker.exe translations/ && cd ..

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

# macOS build commands
build-macos-app:
	@echo "Building macOS app with PyInstaller..."
	pyinstaller --noconfirm --windowed --name=EFDUnpacker --icon=resources/icon.icns --add-data="translations/*.qm:translations" main.py
	@if [ ! -d "dist/EFDUnpacker.app" ]; then \
		echo "Error: EFDUnpacker.app not found in dist directory."; \
		exit 1; \
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
	@echo "Creating macOS portable ZIP archive..."
	@VERSION=$$(cat version.txt); \
	cd dist && zip -r efd-unpacker-$$VERSION-macos-portable.zip EFDUnpacker.app translations/ && cd ..