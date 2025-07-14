# CI Make Guide

Этот документ описывает использование `make` команд в CI/CD pipeline для гарантированного включения переводов в сборки.

## Обзор

Все CI workflow теперь используют `make` команды для:
- Установки зависимостей и настройки среды
- Проверки готовности к сборке
- Компиляции переводов
- Сборки с гарантированным включением переводов
- Проверки включения переводов в готовые артефакты

## Команды make в CI

### Основные команды

```bash
# Установка зависимостей для разработки
make install-deps

# Установка CI-специфичных зависимостей
make install-ci-deps

# Полная настройка CI среды (зависимости + версия + переводы)
make setup-ci

# Создание version.txt из git тега
make create-version

# Компиляция переводов из .ts в .qm
make translations

# Сборка для текущей платформы (с автоматической компиляцией переводов)
make ci-build

# Проверка включения переводов в готовые сборки
make verify-translations

# Запуск тестов
make test
```

### CI-specific команды

- `make setup-ci` - полная настройка CI среды (зависимости + версия + переводы)
- `make install-ci-deps` - установка платформо-зависимых зависимостей
- `make ci-build` - оптимизированная сборка для CI среды
- `make create-version` - создание version.txt из git тега или переменной окружения

## Workflow файлы

### build-and-release.yml

Основной workflow для создания релизов:

```yaml
- name: Setup CI environment
  run: make setup-ci

- name: Build with guaranteed translations
  run: make ci-build

- name: Verify translations in build
  run: make verify-translations
```

### test.yml

Тестовый workflow:

```yaml
- name: Setup CI environment
  run: make setup-ci

- name: Run tests with make
  run: make test
```

## Установка зависимостей

### Автоматическая установка через make

```bash
# Установка всех зависимостей для CI
make setup-ci

# Или по отдельности:
make install-ci-deps  # Системные зависимости
make install-deps     # Python зависимости
make create-version   # Создание version.txt
```

### Ручная установка

#### Linux (Ubuntu)
```bash
sudo apt-get update
sudo apt-get install -y qttools6-dev-tools
sudo apt-get install -y zip unzip libxcb-xinerama0 libxcb-shape0 libxkbcommon-x11-0 libxcb-keysyms1 libxcb-icccm4 libxcb-xkb1 libxcb-image0 libxcb-render-util0 dpkg-dev rpm
```

#### macOS
```bash
brew install qt6 create-dmg
```

#### Windows
Qt Linguist tools должны быть установлены в системе или доступны в PATH.

## Проверки в CI

### 1. Настройка среды
`make setup-ci` выполняет:
- Установку системных зависимостей (`install-ci-deps`)
- Установку Python зависимостей (`install-deps`)
- Создание version.txt (`create-version`)

### 2. Проверка готовности
`make check` проверяет:
- Наличие Python
- Установку PyInstaller
- Наличие файлов переводов
- Наличие version.txt

### 3. Компиляция переводов
`make translations` автоматически:
- Ищет lrelease в системе
- Компилирует .ts файлы в .qm
- Проверяет успешность компиляции

### 4. Сборка с гарантиями
`make ci-build`:
- Автоматически компилирует переводы если нужно
- Запускает соответствующий build скрипт
- Включает переводы в сборку

### 5. Проверка результата
`make verify-translations` проверяет:
- Наличие переводов в готовых артефактах
- Корректность файлов переводов
- Включение в архивы и установщики

## Логирование

Все команды make выводят подробную информацию:
- ✓ Успешные операции
- ✗ Ошибки
- Размеры файлов переводов
- Пути к найденным файлам

## Обработка ошибок

Если любая из команд make завершается с ошибкой:
1. CI workflow останавливается
2. Выводится подробная информация об ошибке
3. Артефакты не загружаются

Это гарантирует, что в релиз попадают только сборки с корректно включенными переводами.

## Локальная разработка

Для локальной разработки используйте те же команды:

```bash
# Быстрая настройка среды
make setup-ci

# Или пошагово:
make install-deps
make translations
make build
make verify-translations
```

## Переменные окружения

### GITHUB_REF
Используется для создания version.txt из git тега:
- `refs/tags/v1.2.3` → `1.2.3`
- Если не установлена, используется текущий git тег или `dev`

### PLATFORM
Автоматически определяется make:
- `linux` - для Ubuntu/Debian
- `macos` - для macOS
- `windows` - для Windows

