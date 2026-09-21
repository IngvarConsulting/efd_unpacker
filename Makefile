# EFD Unpacker Makefile

.PHONY: help clean lint test-cov build-macos build-linux build-windows test install-deps install-test-deps install-build-deps create-version generate-release-notes check generate-spec create-linux-archives create-windows-zip create-macos-zip

# Определяем ОС
ifeq ($(OS),Windows_NT)
    PLATFORM := windows
    PYTHON := python
    PYI_DATASEP := ;
else
    UNAME_S := $(shell uname -s)
    ifeq ($(UNAME_S),Darwin)
        PLATFORM := macos
        PYTHON := python3
        PYI_DATASEP := :
        # PyInstaller не кросс-компилирует: архитектура раннера и есть
        # архитектура бинаря. Кладём её в имя артефакта, чтобы сборки с
        # arm64- и intel-раннеров не перезаписывали друг друга.
        MACOS_ARCH := $(shell uname -m)
    else
        PLATFORM := linux
        PYTHON := python3
        PYI_DATASEP := :
    endif
endif

# appimagetool берётся из continuous: единственный нумерованный релиз
# AppImageKit — тег 13 от 2020 года, откат на него это деградация.
# Хэш перепинивается осознанным коммитом при обновлении.
APPIMAGETOOL_URL := https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
APPIMAGETOOL_SHA256 := b90f4a8b18967545fda78a445b27680a1642f1ef9488ced28b65398f2be7add2

help:
	@echo "EFD Unpacker - Доступные команды:"
	@echo "  install-deps            - Установить зависимости для разработки"
	@echo "  create-version          - Создать version.txt из git тега"
	@echo "  clean                   - Очистить артефакты сборки"
	@echo "  build-macos             - Собрать для macOS (.dmg)"
	@echo "  build-linux             - Собрать для Linux (.AppImage, .deb)"
	@echo "  build-windows           - Собрать для Windows (setup.exe)"
	@echo "  test                    - Запустить тесты"
	@echo "  generate-spec           - Сгенерировать PyInstaller spec файл"
	@echo "  generate-release-notes  - Сгенерировать заметки о выпуске из истории git"
	@echo "  check                   - Проверить готовность к сборке"
	@echo ""
	@echo "Текущая платформа: $(PLATFORM)"
	@echo "Python: $(PYTHON)"

# Две ловушки этого рецепта, обе уже стоили отладки:
#   1. Тело целиком исполняется как sh -c '...', поэтому ОДИНАРНАЯ КАВЫЧКА
#      внутри рвёт внешнее экранирование. Путь к файлу передаём аргументом,
#      а не литералом в кавычках.
#   2. Символ # внутри строки с продолжением через обратный слеш комментирует
#      остаток всей логической строки, а не до конца физической.
check:
	@sh -c '\
	FAILED=0; \
	echo "=== Проверка готовности к сборке ==="; \
	echo "Платформа: $(PLATFORM)"; \
	echo "Python: $$($(PYTHON) --version 2>&1)"; \
	echo ""; \
	echo "Зависимости:"; \
	$(PYTHON) -c "import PyInstaller" 2>/dev/null && echo "✓ PyInstaller" || { echo "✗ PyInstaller"; FAILED=1; }; \
	command -v $(PYTHON) >/dev/null 2>&1 && echo "✓ Python" || { echo "✗ Python"; FAILED=1; }; \
	if [ "$(PLATFORM)" = "macos" ]; then \
	  command -v create-dmg >/dev/null 2>&1 && echo "✓ create-dmg" || { echo "✗ create-dmg"; FAILED=1; }; \
	fi; \
	if [ "$(PLATFORM)" = "linux" ]; then \
	  command -v appimagetool >/dev/null 2>&1 && echo "✓ appimagetool" || { echo "✗ appimagetool"; FAILED=1; }; \
	  command -v dpkg-deb >/dev/null 2>&1 && echo "✓ dpkg-deb" || { echo "✗ dpkg-deb"; FAILED=1; }; \
	  command -v fakeroot >/dev/null 2>&1 && echo "✓ fakeroot" || { echo "✗ fakeroot"; FAILED=1; }; \
	fi; \
	if [ "$(PLATFORM)" = "windows" ]; then \
	  command -v candle >/dev/null 2>&1 && echo "✓ candle" || { echo "✗ candle"; FAILED=1; }; \
	  command -v light >/dev/null 2>&1 && echo "✓ light" || { echo "✗ light"; FAILED=1; }; \
	  command -v sed >/dev/null 2>&1 && echo "✓ sed" || { echo "✗ sed"; FAILED=1; }; \
	  command -v sh >/dev/null 2>&1 && echo "✓ sh" || { echo "✗ sh"; FAILED=1; }; \
	fi; \
	echo ""; \
	echo "Файлы проекта:"; \
	[ -f version.txt ] && echo "✓ Version file" || { echo "✗ Version file"; FAILED=1; }; \
	[ -d translations ] && echo "✓ Translations dir" || { echo "✗ Translations dir"; FAILED=1; }; \
	$(PYTHON) -c "import sys, xml.etree.ElementTree as ET; ET.parse(sys.argv[1])" translations/ru.ts 2>/dev/null && echo "✓ Translations XML" || { echo "✗ Translations XML"; FAILED=1; }; \
	if [ "$(PLATFORM)" = "windows" ]; then \
	  VERSION=$$(cat version.txt); \
	  printf "%s" "$$VERSION" | grep -Eq "^[0-9]+\\.[0-9]+\\.[0-9]+(\\.[0-9]+)?$$" && echo "✓ MSI/Burn version" || { echo "✗ MSI/Burn version ($$VERSION)"; FAILED=1; }; \
	fi; \
	echo ""; \
	if [ $$FAILED -eq 1 ]; then \
		echo "✗ Есть ошибки!"; \
		exit 1; \
	else \
		echo "✓ Все проверки пройдены успешно!"; \
	fi'

build-macos: clean create-version check generate-spec
	@echo "Building for macOS..."
	@$(MAKE) build-macos-app
	@$(MAKE) create-macos-dmg

build-linux: clean create-version check generate-spec
	@echo "Building for Linux..."
	@$(MAKE) build-linux-executable
	@$(MAKE) create-linux-appimage
	@$(MAKE) create-linux-deb

build-windows: clean create-version check generate-spec
	@echo "Building for Windows..."
	@$(MAKE) build-windows-executable
	@$(MAKE) create-windows-msi
	@$(MAKE) create-windows-setup

test:
	@echo "Running tests..."
	$(PYTHON) -m pytest tests/ -v

# Отдельная цель: порог покрытия не должен блокировать выпуск релиза, поэтому
# build-and-release.yml остаётся на голом `test`, а гейт живёт в test.yml.
# COV_MIN стоит на пару пунктов ниже фактического минимума по раннерам —
# запас на платформенные ветки, которые на одной ОС не выполняются.
COV_MIN ?= 80

test-cov:
	@echo "Running tests with coverage (min $(COV_MIN)%)..."
	$(PYTHON) -m pytest tests/ -q \
		--cov=src/efd_unpacker --cov-report=term-missing --cov-fail-under=$(COV_MIN)

lint:
	@echo "Running ruff..."
	$(PYTHON) -m ruff check src tests

generate-spec:
	@echo "Generating EFDUnpacker.spec from template..."
	@VERSION=$$(cat version.txt); \
	sed -e "s#{{VERSION}}#$$VERSION#g" \
	    installer/EFDUnpacker.spec.in > EFDUnpacker.spec; \
	
generate-release-notes:
	@echo "Generating release notes..."
	$(PYTHON) scripts/generate_release_notes.py > release_notes.md
	
# Зависимости разделены намеренно: test.yml незачем тянуть весь packaging-тулинг
# (sudo apt-get, brew, choco), а разработчику на ноутбуке — тем более.
install-test-deps:
	@echo "Installing test dependencies..."
	$(PYTHON) -m pip install --upgrade pip setuptools wheel
	$(PYTHON) -m pip install --only-binary=:all: -r requirements.txt
	$(PYTHON) -m pip install --only-binary=:all: -r requirements-test.txt
	@set -e; \
	if [ "$(PLATFORM)" = "linux" ]; then \
		sudo apt-get update; \
		sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
			libegl1 libglib2.0-0 libfontconfig1 libxkbcommon0 libgl1 libdbus-1-3; \
	fi

install-build-deps: install-test-deps
	@echo "Installing build dependencies..."
	$(PYTHON) -m pip install --only-binary=:all: -r requirements-build.txt
	@set -e; \
	if [ "$(PLATFORM)" = "linux" ]; then \
		sudo apt-get update; \
		sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
			fuse libfuse2 binutils fakeroot dpkg-dev zip patchelf zsync \
			curl coreutils xz-utils file lintian; \
		if ! command -v appimagetool >/dev/null 2>&1; then \
			curl -fL --proto '=https' --tlsv1.2 --retry 3 \
				-o /tmp/appimagetool \
				"$(APPIMAGETOOL_URL)"; \
			echo "$(APPIMAGETOOL_SHA256)  /tmp/appimagetool" | sha256sum -c -; \
			sudo mv /tmp/appimagetool /usr/local/bin/appimagetool; \
			sudo chmod +x /usr/local/bin/appimagetool; \
		fi; \
	fi
	@set -e; \
	if [ "$(PLATFORM)" = "macos" ]; then \
		brew list create-dmg >/dev/null 2>&1 || brew install create-dmg; \
	fi
	@set -e; \
	if [ "$(PLATFORM)" = "windows" ]; then \
		choco install zip -y; \
		choco install wixtoolset -y; \
	fi

# Обратная совместимость: старое имя цели.
install-deps: install-build-deps

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

# Linux build commands
build-linux-executable:
	@echo "Building Linux executable with PyInstaller..."
	pyinstaller --noconfirm --onefile --name=efd_unpacker \
		--paths src \
		--add-data "translations$(PYI_DATASEP)translations" \
		--add-data "resources$(PYI_DATASEP)resources" \
		main.py
	@if [ ! -f "dist/efd_unpacker" ]; then \
		echo "Error: efd_unpacker executable not found in dist directory."; \
		exit 1; \
	fi
	
create-linux-appimage:
	@echo "Creating Linux AppImage..."
	@set -e; \
	if ! command -v appimagetool >/dev/null 2>&1; then \
		echo "Error: appimagetool not found."; exit 1; \
	fi; \
	VERSION=$$(cat version.txt); \
	rm -rf AppDir; \
	mkdir -p AppDir/usr/bin AppDir/usr/share/applications \
		AppDir/usr/share/icons/hicolor/1024x1024/apps AppDir/usr/share/doc/efd-unpacker; \
	cp dist/efd_unpacker AppDir/usr/bin/efd_unpacker; \
	if [ -f "resources/icon.png" ]; then \
		cp resources/icon.png AppDir/usr/share/icons/hicolor/1024x1024/apps/efd_unpacker.png; \
		cp resources/icon.png AppDir/efd_unpacker.png; \
	fi; \
	cp installer/linux/efd_unpacker.desktop AppDir/usr/share/applications/; \
	cp AppDir/usr/share/applications/efd_unpacker.desktop AppDir/; \
	cp installer/linux/AppRun AppDir/; \
	cp installer/linux/copyright AppDir/usr/share/doc/efd-unpacker/copyright; \
	chmod +x AppDir/AppRun; \
	appimagetool AppDir "dist/efd-unpacker-$$VERSION-linux.AppImage"; \
	rm -rf AppDir; \
	test -f "dist/efd-unpacker-$$VERSION-linux.AppImage"

create-linux-deb:
	@echo "Creating Linux DEB package..."
	@set -e; \
	if ! command -v dpkg-deb >/dev/null 2>&1; then \
		echo "Error: dpkg-deb not found."; exit 1; \
	fi; \
	VERSION=$$(cat version.txt); \
	DOCDIR=debian/usr/share/doc/efd-unpacker; \
	rm -rf debian; \
	mkdir -p debian/DEBIAN debian/usr/bin debian/usr/share/applications \
		debian/usr/share/icons/hicolor/1024x1024/apps debian/usr/share/mime/packages "$$DOCDIR"; \
	cp dist/efd_unpacker debian/usr/bin/efd_unpacker; \
	if [ -f "resources/icon.png" ]; then \
		cp resources/icon.png debian/usr/share/icons/hicolor/1024x1024/apps/efd_unpacker.png; \
	fi; \
	cp installer/linux/efd_unpacker.desktop debian/usr/share/applications/; \
	cp installer/linux/mime-info.xml debian/usr/share/mime/packages/; \
	cp installer/linux/copyright "$$DOCDIR/copyright"; \
	printf 'efd-unpacker (%s) unstable; urgency=medium\n\n  * See https://github.com/IngvarConsulting/efd_unpacker/releases\n\n -- Ingvar Consulting LLC <i@ingvar.pro>  %s\n' \
		"$$VERSION" "$$(date -R)" > "$$DOCDIR/changelog"; \
	gzip -9n "$$DOCDIR/changelog"; \
	cp installer/linux/control debian/DEBIAN/; \
	sed -i "s/VERSION_PLACEHOLDER/$$VERSION/g" debian/DEBIAN/control; \
	cp installer/linux/postinst installer/linux/postrm debian/DEBIAN/; \
	chmod 0755 debian/DEBIAN/postinst debian/DEBIAN/postrm; \
	chmod 0755 debian/usr/bin/efd_unpacker; \
	find debian/usr/share -type f -exec chmod 0644 {} +; \
	find debian/usr -type d -exec chmod 0755 {} +; \
	fakeroot dpkg-deb -Zxz --build debian "dist/efd-unpacker-$$VERSION-linux-amd64.deb"; \
	rm -rf debian; \
	test -f "dist/efd-unpacker-$$VERSION-linux-amd64.deb"

create-linux-archives:
	@echo "Creating Linux portable archives..."
	cd dist && zip -r efd-unpacker-$$(cat ../version.txt)-linux-portable.zip efd_unpacker
	cd dist && tar -czf efd-unpacker-$$(cat ../version.txt)-linux-portable.tar.gz efd_unpacker
	
# Windows build commands
# --console + --hide-console hide-early вместо --windowed: у windowed-сборки нет
# stdout, поэтому --help и [OK]/[ERROR] из CLI-режима уходили в никуда, хотя
# docs/CLI.md их обещает, а установщик кладёт каталог в PATH. hide-early прячет
# консоль, только когда процесс ей владеет (запуск из проводника, ярлыка или по
# ассоциации .efd); при запуске из открытой консоли она остаётся, и вывод виден.
# Опция требует PyInstaller >= 6.0 — он запинен в install-deps.
build-windows-executable:
	@echo "Building Windows executable with PyInstaller..."
	pyinstaller --noconfirm --onefile --console --hide-console hide-early $(if $(wildcard resources/icon.ico),--icon=resources/icon.ico,) \
		--paths src \
		--add-data "translations$(PYI_DATASEP)translations" \
		--add-data "resources$(PYI_DATASEP)resources" \
		--name=EFDUnpacker main.py
	@if [ ! -f "dist/EFDUnpacker.exe" ]; then \
		echo "Error: EFDUnpacker.exe not found in dist directory."; \
		exit 1; \
	fi

create-windows-zip:
	@echo "Creating Windows portable ZIP archive..."
	@if ! command -v zip >/dev/null 2>&1; then \
		echo "Error: 'zip' not found. Установите zip через Chocolatey: choco install zip -y"; \
		exit 1; \
	fi
	@VERSION=$$(cat version.txt); \
	cd dist && zip -r efd-unpacker-$$VERSION-windows-portable.zip EFDUnpacker.exe && cd ..

create-windows-msi:
	@echo "Creating Windows MSI installer..."
	@if command -v candle >/dev/null 2>&1 && command -v light >/dev/null 2>&1; then \
		echo "WiX Toolset found, creating MSI installer..."; \
		VERSION=$$(cat version.txt); \
		sed "s/VERSION_PLACEHOLDER/$$VERSION/g" installer/windows/installer.wxs > installer/windows/installer_temp.wxs; \
		candle installer/windows/installer_temp.wxs -out installer/windows/installer.wixobj; \
		if [ $$? -eq 0 ]; then \
			light installer/windows/installer.wixobj -out dist/efd-unpacker-$$VERSION-windows.msi; \
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

create-windows-setup:
	@echo "Creating Windows setup bundle..."
	@if command -v candle >/dev/null 2>&1 && command -v light >/dev/null 2>&1; then \
		echo "WiX Toolset found, creating setup.exe bundle..."; \
		VERSION=$$(cat version.txt); \
		if [ ! -f "dist/efd-unpacker-$$VERSION-windows.msi" ]; then \
			echo "Error: Windows MSI not found. Run create-windows-msi first."; \
			exit 1; \
		fi; \
		sed "s/VERSION_PLACEHOLDER/$$VERSION/g" installer/windows/bundle.wxs > installer/windows/bundle_temp.wxs; \
		candle -ext WixBalExtension installer/windows/bundle_temp.wxs -out installer/windows/bundle.wixobj; \
		if [ $$? -eq 0 ]; then \
			light -ext WixBalExtension installer/windows/bundle.wixobj -out dist/efd-unpacker-$$VERSION-windows-setup.exe; \
			if [ $$? -eq 0 ]; then \
				echo "Windows setup bundle created successfully"; \
			else \
				echo "Error: WiX bundle linking failed."; \
				exit 1; \
			fi; \
		else \
			echo "Error: WiX bundle compilation failed."; \
			exit 1; \
		fi; \
		rm -f installer/windows/bundle_temp.wxs installer/windows/bundle.wixobj; \
	else \
		echo "Warning: WiX Toolset not found. Skipping setup.exe creation."; \
		echo "Download from: https://wixtoolset.org/releases/"; \
		echo "Or install via Chocolatey: choco install wixtoolset"; \
	fi

# macOS build commands
build-macos-app:
	@echo "Building macOS app with PyInstaller..."
	pyinstaller --noconfirm EFDUnpacker.spec
	@if [ ! -d "dist/EFDUnpacker.app" ]; then \
		echo "Error: EFDUnpacker.app not found in dist directory."; \
		exit 1; \
	fi
	@BUILT=$$(lipo -archs "dist/EFDUnpacker.app/Contents/MacOS/EFDUnpacker"); \
	if [ "$$BUILT" != "$(MACOS_ARCH)" ]; then \
		echo "Error: built $$BUILT, expected $(MACOS_ARCH). PyInstaller не кросс-компилирует —"; \
		echo "       проверьте, что python и колёса совпадают с архитектурой машины."; \
		exit 1; \
	fi; \
	echo "Built for $$BUILT"

create-macos-dmg:
	@echo "Creating DMG installer..."
	@VERSION=$$(cat version.txt | tr -d ' \t\n\r'); \
	STAGING_DIR="build/dmg-root"; \
	rm -rf "$$STAGING_DIR"; \
	mkdir -p "$$STAGING_DIR"; \
	ditto "dist/EFDUnpacker.app" "$$STAGING_DIR/EFDUnpacker.app"; \
	SANDBOX_FLAG=""; \
	if [ "$$CI" = "true" ]; then \
		SANDBOX_FLAG="--sandbox-safe"; \
	fi; \
	create-dmg \
		$$SANDBOX_FLAG \
		--volname "EFD Unpacker" \
		--volicon "resources/icon.icns" \
		--window-pos 200 120 \
		--window-size 600 300 \
		--icon-size 100 \
		--icon "EFDUnpacker.app" 175 120 \
		--hide-extension "EFDUnpacker.app" \
		--app-drop-link 425 120 \
		"dist/efd-unpacker-$${VERSION}-macos-$(MACOS_ARCH).dmg" \
		"$$STAGING_DIR"

create-macos-zip:
	@echo "Creating macOS portable ZIP archive..."
	@VERSION=$$(cat version.txt); \
	cd dist && zip -r efd-unpacker-$$VERSION-macos-portable.zip EFDUnpacker.app && cd ..
