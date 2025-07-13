# Система локализации EFD Unpacker

## Обзор

EFD Unpacker использует Qt Translation (QTranslator) для локализации интерфейса. Система автоматически определяет язык операционной системы и загружает соответствующие переводы.

## Структура файлов

- `translations/ru.ts` - Файл переводов для русского языка (Qt Linguist)
- `translations/ru.qm` - Скомпилированный файл переводов для русского языка

## Автоматическое определение языка

Приложение автоматически определяет системный язык при запуске:
- Использует стандартную Qt локаль (`QLocale.system()`)
- Поддерживает русский (`ru`) и английский (`en`) языки
- Если системный язык не поддерживается, используется английский язык
- Язык определяется при каждом запуске, настройки не сохраняются

## Определение системного языка

Система использует стандартный Qt механизм:
- `QLocale.system()` для получения системной локали
- Анализ имени локали и языка для определения поддерживаемого языка
- Fallback на английский язык для неподдерживаемых языков

## Использование в коде

### В UI классах
```python
# Простая строка
self.setWindowTitle(self.tr('EFD Unpacker'))

# Строка с параметрами
self.label.setText(self.tr('%1').replace('%1', file_path))
```

### В сервисах
```python
from PyQt6.QtCore import QCoreApplication

# Простая строка
message = QCoreApplication.translate('UnpackService', 'File not found')

# Строка с параметрами
message = QCoreApplication.translate('UnpackService', 'Unexpected error: %1').replace('%1', str(error))
```

## Добавление нового языка

1. Создайте файл `translations/xx.ts` (где xx - код языка)
2. Добавьте переводы в формате Qt Linguist
3. Скомпилируйте в `.qm` файл:
   ```bash
   lrelease translations/xx.ts -qm translations/xx.qm
   ```
4. Добавьте поддержку языка в `main.py`:
   ```python
   if lang not in ('ru', 'en', 'xx'):
       lang = 'en'
   ```

## Добавление новых строк

1. Добавьте строку в код с `self.tr()` или `QCoreApplication.translate()`
2. Обновите `.ts` файлы с помощью `lupdate`:
   ```bash
   lupdate main.py ui.py unpack_service.py -ts translations/ru.ts
   ```
3. Отредактируйте переводы в Qt Linguist
4. Скомпилируйте в `.qm` файлы

## Компиляция переводов

### Установка инструментов
- **macOS:** `brew install qt5-tools`
- **Ubuntu/Debian:** `sudo apt install qttools5-dev-tools`
- **Windows:** Установите Qt через официальный инсталлятор

### Команды
```bash
# Обновление .ts файлов
lupdate main.py ui.py unpack_service.py -ts translations/ru.ts

# Компиляция в .qm
lrelease translations/ru.ts -qm translations/ru.qm
```

## Fallback механизм

Если перевод не найден для текущего языка, Qt автоматически использует исходную строку (английскую).

## Контексты переводов

- `MainWindow` - Основной интерфейс приложения
- `UnpackService` - Сообщения сервиса распаковки
