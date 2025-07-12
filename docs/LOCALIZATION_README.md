# Система локализации EFD Unpacker

## Структура файлов

- `localization.py` - Основной файл с переводами
- `language_manager.py` - Менеджер для управления языками

## Автоматическое определение языка

Приложение автоматически определяет системный язык при запуске:
- Если системный язык поддерживается (русский или английский), он используется
- Если системный язык не поддерживается, используется английский язык
- Настройки языка не сохраняются между запусками

## Использование

### Получение переведенной строки

```python
from localization import loc

# Простая строка
title = loc.get('window_title')

# Строка с параметрами
message = loc.get('file_selected', file_path='/path/to/file')
```

### Переключение языка

```python
from language_manager import language_manager

# Установить английский язык
language_manager.set_language('en')

# Получить текущий язык
current_lang = language_manager.get_current_language()

# Получить список доступных языков
languages = language_manager.get_available_languages()
```

## Добавление нового языка

1. Откройте файл `localization.py`
2. Добавьте новый язык в словарь `translations`:

```python
'tr': {  # Турецкий язык
    'window_title': 'EFD Unpacker',
    'drag_drop_hint': 'Dosyayı buraya sürükleyin veya çift tıklayın',
    # ... остальные переводы
}
```

3. Добавьте язык в `language_manager.py`:

```python
self.available_languages = {
    'ru': 'Русский',
    'en': 'English',
    'tr': 'Türkçe'  # Новый язык
}
```

## Добавление новых строк

1. Добавьте ключ в словарь переводов в `localization.py`
2. Добавьте переводы для всех поддерживаемых языков
3. Используйте `loc.get('new_key')` в коде

## Форматирование строк

Для строк с параметрами используйте форматирование Python:

```python
# В localization.py
'file_selected': 'Файл выбран:\n{file_path}'

# В коде
loc.get('file_selected', file_path='/path/to/file')
```

## Fallback механизм

Если перевод не найден для текущего языка, система автоматически использует английский перевод. Если и английский перевод отсутствует, возвращается ключ строки.

## Определение системного языка

Система использует модуль `locale` Python для определения системного языка:
- Получает системную локаль через `locale.getdefaultlocale()`
- Извлекает код языка (первые 2 символа)
- Проверяет поддержку языка в списке доступных
- Использует английский как fallback 