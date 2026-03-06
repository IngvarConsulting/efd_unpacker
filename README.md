[![Test Suite](https://github.com/IngvarConsulting/efd_unpacker/actions/workflows/test.yml/badge.svg)](https://github.com/IngvarConsulting/efd_unpacker/actions/workflows/test.yml)

# EFD Unpacker

**EFD Unpacker** — кроссплатформенное приложение для распаковки файлов EFD (Enterprise File Distribution) с GUI и двумя CLI-сценариями: открыть файл в форме или распаковать его без GUI.

## Основные возможности
- Распаковка `.efd` на Windows, Linux и macOS
- GUI на PyQt5 с drag and drop и файловыми ассоциациями
- Headless CLI для автоматизации
- Английский интерфейс по умолчанию и русский на системах с русской локалью

## Официальные релизные артефакты
- **macOS**: `.dmg`
- **Windows**: `setup.exe`
- **Linux**: `.AppImage`, `.deb`

Промежуточные `.app`, `.exe` и вспомогательные packaging-таргеты существуют для сборки, но не считаются основными пользовательскими артефактами релиза.

## Документация
- [Установка](docs/INSTALL.md)
- [CLI](docs/CLI.md)
- [Ассоциации файлов и интеграция с ОС](docs/FILE_ASSOCIATION_GUIDE.md)
- [Сборка и релизный контур](docs/BUILD.md)
- [Локализация приложения](docs/LOCALIZATION_README.md)
- [Конвенция коммитов](docs/COMMIT_CONVENTION.md)

## Лицензия
MIT. См. [LICENSE](LICENSE).

## Поддержка
- [Issues](https://github.com/IngvarConsulting/efd_unpacker/issues)
