# Сборка EFD Unpacker

Документ описывает актуальный build/release контур проекта и официальный набор артефактов.

## Официальная матрица

| Платформа | CI runner | Основные артефакты |
|-----------|-----------|--------------------|
| macOS | `macos-15-intel` | `.dmg` |
| Windows | `windows-2022` | `setup.exe` |
| Linux | `ubuntu-22.04` | `.AppImage`, `.deb` |

Именно этот набор публикуется и smoke-тестируется в GitHub Actions.

## Требования

- Python 3.9+
- зависимости из `requirements.txt`
- PyInstaller
- Git

Платформенные дополнения:
- macOS: `create-dmg`
- Windows: WiX Toolset для внутреннего `MSI` и итогового `setup.exe`
- Linux: `appimagetool`, `dpkg-deb`

## Локальная подготовка

```bash
make install-deps
make create-version
```

`make install-deps` ставит Python-зависимости и необходимые системные утилиты для текущей платформы.

## Основные цели Makefile

```bash
# macOS
make build-macos

# Linux
make build-linux

# Windows
make build-windows
```

## Что создаёт сборка

### macOS
- промежуточный `dist/EFDUnpacker.app`
- основной артефакт `dist/efd-unpacker-<version>-macos.dmg`

### Windows
- промежуточный `dist/EFDUnpacker.exe`
- промежуточный `dist/efd-unpacker-<version>-windows.msi`
- основной артефакт `dist/efd-unpacker-<version>-windows-setup.exe`

### Linux
- промежуточный `dist/efd_unpacker`
- основные артефакты:
  - `dist/efd-unpacker-<version>-linux.AppImage`
  - `dist/efd-unpacker-<version>-linux-amd64.deb`

## CI и релизы

Текущие workflow:
- `.github/workflows/test.yml` — тесты на Windows, Linux и macOS
- `.github/workflows/build-and-release.yml` — сборка и smoke-тест артефактов по тегу `v*`

Важно:
- tag workflow сейчас **собирает и проверяет** артефакты;
- автоматическая публикация GitHub Release в workflow пока отключена и требует отдельного включения.

## Что не считать официальным путём

В `Makefile` могут оставаться вспомогательные packaging-цели для локальных экспериментов. Если они не используются в текущих workflow и не перечислены выше, не стоит документировать их как поддерживаемый способ поставки.

## См. также
- [INSTALL.md](INSTALL.md) — установка и запуск
- [CLI.md](CLI.md) — режимы командной строки
- [LOCALIZATION_README.md](LOCALIZATION_README.md) — локализация приложения
