# EFD Unpacker

**EFD Unpacker** — кроссплатформенное приложение для распаковки файлов EFD с удобным графическим интерфейсом и поддержкой автоматизации через командную строку.

## Основные возможности
- Распаковка файлов EFD (.efd) на Windows, Linux и macOS
- Удобный графический интерфейс (PyQt5)
- Drag & Drop, интеграция с ОС, ассоциации файлов
- CLI-режим для автоматизации и CI/CD
- Локализация интерфейса (русский, английский)

## Быстрый старт

### Установка зависимостей
```bash
pip install -r requirements.txt
```

### Запуск GUI
```bash
python main.py
```

### CLI-режим (без GUI)
```bash
EFDUnpacker unpack /path/to/file.efd -tmplts /path/to/output_dir
```
Подробнее: [docs/CLI.md](docs/CLI.md)

## Документация
- [CLI-режим (автоматизация)](docs/CLI.md)
- [Ассоциации файлов и интеграция с ОС](docs/FILE_ASSOCIATION_GUIDE.md)
- [Сборка и требования](docs/BUILD.md)
- [Локализация](docs/LOCALIZATION_README.md)
- [Конвенция коммитов](docs/COMMIT_CONVENTION.md)

## Лицензия
MIT. См. файл [LICENSE](LICENSE).

## Поддержка
- [Issues](https://github.com/IngvarConsulting/efd_unpacker/issues)
- [Документация](docs/)
