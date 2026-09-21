# Сборка EFD Unpacker

Документ описывает актуальный build/release контур проекта и официальный набор артефактов.

## Официальная матрица

| Платформа | CI runner | Основные артефакты |
|-----------|-----------|--------------------|
| macOS | `macos-15-intel` + `macos-15` | `.dmg` (x86_64 и arm64) |
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
- Linux: `appimagetool`, `dpkg-deb`, `fakeroot`

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
- основной артефакт `dist/efd-unpacker-<version>-macos-<arch>.dmg`

`<arch>` берётся из `uname -m` сборочной машины. PyInstaller не кросс-компилирует,
поэтому архитектура раннера и есть архитектура бинаря: под каждую нужен свой job.
Universal2 одним проходом невозможен — PyQt5 публикует раздельные колёса под
arm64 и x86_64, и `target_arch='universal2'` падает с `IncompatibleBinaryArchError`.

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

### Что происходит по тегу `v*`

1. `test-suite` — тесты на трёх платформах.
2. `build-linux`, `build-windows`, `build-macos` — сборка артефактов. macOS собирается дважды, под `x86_64` и `arm64`: PyInstaller не кросс-компилирует.
3. Четыре смоук-job — `test-appimage`, `test-deb`, `test-windows-setup`, `test-dmg` — устанавливают собранное и проверяют, что CLI отрабатывает и распаковка даёт непустой результат.
4. `create-release` публикует **не-draft** GitHub Release с файлами из `artifacts/{linux,windows,macos-*}-builds/*`.

Публикация сразу в открытый доступ — намеренное решение (коммит `dc33514`), по этому контуру вышли версии v1.2.9–v1.2.11, и `docs/INSTALL.md` ссылается на страницу релизов. Следствие: **пробный тег создаст публичный релиз**, отдельного «черновикового» прогона сейчас нет.

### Пробный прогон без публикации

Тот же конвейер запускается вручную — собирает и смоук-тестирует всё, но релиз не публикует: job `create-release` условен по `refs/tags/` и при запуске с ветки пропускается.

```bash
gh workflow run build-and-release.yml --ref <ветка> -f version=0.0.0
```

Версию нужно задавать в формате `X.Y.Z`: вне тега `git describe` даёт строку вида `1.2.11-17-g09a0942`, которую WiX не примет, и Windows-сборка упадёт на проверке в `make check`.

Готовые артефакты — во вкладке Actions, в разделе Artifacts у прогона: `linux-builds`, `windows-builds`, `macos-builds-x86_64`, `macos-builds-arm64`.

Этим стоит пользоваться после любой правки в `build-and-release.yml` или в сборочных целях `Makefile`: иначе первый прогон изменений совпадёт с первым релизом.

### Локальная подготовка зависимостей

- `make install-test-deps` — только то, что нужно для `pytest` (используется в `test.yml`).
- `make install-build-deps` — плюс весь packaging-тулинг: rpm, fakeroot, appimagetool, create-dmg, WiX.
- `make install-deps` — синоним `install-build-deps`, оставлен для совместимости.

Версия PyInstaller запинена в `requirements-build.txt`: её обновление регулярно ломает сбор плагинов PyQt5, и это должно быть осознанным коммитом. `appimagetool` качается с проверкой sha256, зафиксированного в `Makefile`.

## Что не считать официальным путём

В `Makefile` могут оставаться вспомогательные packaging-цели для локальных экспериментов. Если они не используются в текущих workflow и не перечислены выше, не стоит документировать их как поддерживаемый способ поставки.

## Локализация

`translations/ru.ts` ведётся **вручную**. `lupdate` и `pylupdate5` к этому проекту неприменимы: приложение не использует Qt-идиомы (`QTranslator`, `self.tr`, `QCoreApplication.translate`), а зовёт собственный `Translator.translate()` и `MainWindow._t()`; часть ключей собирается в f-строках, а сообщения `FileValidator` и `UnpackService` лежат в словарях `application/messages.py` и выбираются по коду ошибки. Статический обход такой код почти не видит и пометит основную массу записей как `obsolete`, то есть обнулит каталог.

`.qm` не собирается и не нужен — `.ts` читается напрямую при старте.

Каталог сверяется с кодом в обе стороны тестами `tests/unit/test_translator.py`: строка в коде без перевода и запись в `ru.ts`, до которой нет ни одной ветки, одинаково роняют CI. Добавили `translate('MainWindow', 'New string')` — добавьте запись в `ru.ts` тем же коммитом.

Записи с атрибутом `type` (`unfinished`, `obsolete`, `vanished`) загрузчик пропускает: черновик не должен доезжать до пользователя. Битый XML каталога не валит приложение — интерфейс откатывается на английский, а `make check` такой файл не пропустит.

## См. также
- [INSTALL.md](INSTALL.md) — установка и запуск
- [CLI.md](CLI.md) — режимы командной строки
- [FILE_ASSOCIATION_GUIDE.md](FILE_ASSOCIATION_GUIDE.md) — ассоциация с `.efd`
