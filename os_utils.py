import os
import sys
import subprocess
import platform
import locale

# Добавляем импорт ctypes только для Windows
if sys.platform.startswith('win'):
    import ctypes

def get_1c_configuration_location_default():
    """Возвращает путь к каталогу распаковки по умолчанию в зависимости от ОС."""
    if sys.platform.startswith('win'):
        appdata = os.environ.get('APPDATA')
        if appdata:
            return os.path.join(appdata, '1C', '1cv8', 'tmplts')
        else:
            return os.path.join(os.getcwd(), 'tmplts')
    else:
        home = os.path.expanduser('~')
        return os.path.join(home, '.1cv8', '1C', '1cv8', 'tmplts')

def get_1c_configuration_location_from_1cestart():
    """
    Возвращает массив значений ConfigurationTemplatesLocation из файла 1cestart.cfg.
    
    Проверяет все возможные расположения файла для разных ОС:
    - Linux/macOS: ~/.1C/1cestart/1cestart.cfg
    - Windows (для пользователя): %APPDATA%\1C\1CEStart\1cestart.cfg
    - Windows (для всех пользователей): %ALLUSERSPROFILE%\1C\1CEStart\1cestart.cfg
    
    Returns:
        list: Массив путей к каталогам шаблонов конфигураций
    """
    locations = []
    config_paths = []
    if sys.platform.startswith('win'):
        appdata = os.environ.get('APPDATA')
        allusersprofile = os.environ.get('ALLUSERSPROFILE')
        if appdata:
            config_paths.append(os.path.join(appdata, '1C', '1CEStart', '1cestart.cfg'))
        if allusersprofile:
            config_paths.append(os.path.join(allusersprofile, '1C', '1CEStart', '1cestart.cfg'))
    else:
        home = os.path.expanduser('~')
        config_paths.append(os.path.join(home, '.1C', '1cestart', '1cestart.cfg'))
    for config_path in config_paths:
        if os.path.isfile(config_path):
            encodings_to_try = ['utf-8-sig', 'utf-16le', 'utf-8', 'cp1251']
            for encoding in encodings_to_try:
                try:
                    with open(config_path, 'r', encoding=encoding) as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith('ConfigurationTemplatesLocation='):
                                value = line.split('=', 1)[1]
                                if value and value not in locations:
                                    locations.append(value)
                    break
                except (UnicodeDecodeError, IOError):
                    continue
    return locations

def open_folder(path):
    """Открывает указанный путь в системном файловом менеджере."""
    if not os.path.exists(path):
        return False
    try:
        if platform.system() == "Windows":
            subprocess.run(["explorer", path])
        elif platform.system() == "Darwin":  # macOS
            subprocess.run(["open", path])
        else:  # Linux
            subprocess.run(["xdg-open", path])
        return True
    except Exception:
        return False

def get_default_language():
    """Определяет системный язык по умолчанию для текущей ОС."""
    if sys.platform == "darwin": # macOS
        try:
            output = subprocess.run(['defaults', 'read', '-g', 'AppleLanguages'], capture_output=True, text=True, check=True)
            # Получаем первый язык из списка, убираем кавычки
            lang_code = output.stdout.strip().split(',')[0].strip('\" ')
            # На macOS коды могут быть типа 'en' или 'en-US'. Нам нужны только первые 2 символа.
            return lang_code.split('-')[0].lower()
        except Exception:
            return 'en' # Fallback
    elif sys.platform.startswith('win'): # Windows
        try:
            # GetUserDefaultUILanguage() возвращает LCID, который нужно преобразовать в код языка
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            # Преобразуем LCID в строку локали, например, '0419' (русский)
            # Затем можно использовать Mapping из ISO-639-1
            # Или просто использовать первые 2 символа, если WiXToolSet принимает только их
            lang_code = hex(lang_id)[2:].zfill(4) # Преобразовать в HEX и дополнить нулями
            # Простой маппинг для основных языков
            if lang_code.startswith('0419'): # Русский
                return 'ru'
            elif lang_code.startswith('0409'): # Английский (США)
                return 'en'
            else:
                # Если неизвестный код, пробуем получить из него язык
                return locale.windows_locale[lang_id].split('_')[0].lower() # Это будет работать, если Windows-locale установлен
        except Exception:
            return 'en' # Fallback
    else: # Linux и другие Unix-подобные
        try:
            # locale.getdefaultlocale()[0] возвращает строку типа 'ru_RU.UTF-8' или 'en_US.UTF-8'
            system_locale = locale.getdefaultlocale()[0]
            if system_locale:
                return system_locale.split('_')[0].lower()
        except Exception:
            pass
        # Fallback
        return 'en' 