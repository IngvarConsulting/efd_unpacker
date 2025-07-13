# Сборка EFD Unpacker

В этом документе описаны требования, инструкции и опции сборки EFD Unpacker для всех поддерживаемых платформ: Windows, Linux, macOS.

---

## Общие требования
- **Python 3.9+**
- **PyQt5** (см. requirements.txt)
- **onec_dtools** (см. requirements.txt)
- **Git** (для клонирования репозитория)

---

## Сборка для macOS

### Требования
- Python 3
- Homebrew (для установки create-dmg)
- PyInstaller (устанавливается автоматически)
- create-dmg (устанавливается через Homebrew)

### Сборка
```bash
./build_macos.sh
```

### Результаты
- **EFDUnpacker.app** — приложение для macOS
- **efd-unpacker-<версия>-macos.dmg** — установщик с иконками
- **efd-unpacker-<версия>-macos-portable.zip** — портативная версия

---

## Сборка для Linux

### Требования
- Python 3
- PyInstaller (устанавливается автоматически)
- appimagetool (опционально, для AppImage)
- dpkg-deb (опционально, для DEB)
- rpmbuild (опционально, для RPM)

### Сборка
```bash
./build_linux.sh
```

### Результаты
- **EFDUnpacker/** — исполняемая папка
- **efd-unpacker-<версия>-linux-portable.zip** — портативная версия
- **efd-unpacker-<версия>-linux-portable.tar.gz** — альтернативная портативная версия
- **efd-unpacker-<версия>-linux.AppImage** — универсальный пакет (если доступен appimagetool)
- **efd-unpacker-<версия>-linux-amd64.deb** — пакет для Debian/Ubuntu (если доступен dpkg-deb)
- **efd-unpacker-<версия>-linux.x86_64.rpm** — пакет для Red Hat/Fedora (если доступен rpmbuild)

---

## Сборка для Windows

### Требования
- Python 3
- PyInstaller (устанавливается автоматически)
- WiX Toolset (опционально, для MSI)
- PowerShell (для запуска скрипта)

### Сборка
```powershell
.\build_windows.ps1
```

### Опции
- `-SkipMsi` — сборка без MSI установщика
- `-Verbose` — подробный вывод

### Результаты
- **EFDUnpacker/** — исполняемая папка
- **efd-unpacker-<версия>-windows-portable.zip** — портативная версия
- **efd-unpacker-<версия>-windows.msi** — установщик Windows (если доступен WiX Toolset)

---

## Примечания
- Все скрипты сборки автоматически устанавливают необходимые Python-зависимости.
- Для сборки рекомендуется использовать чистое виртуальное окружение Python.
- Для CI/CD используйте соответствующие шаги в GitHub Actions (см. .github/workflows/).

---

## См. также
- [README.md](../README.md) — быстрый старт и структура проекта
- [docs/CLI.md](CLI.md) — CLI-режим
- [docs/FILE_ASSOCIATION_GUIDE.md](FILE_ASSOCIATION_GUIDE.md) — ассоциации файлов 