import os
import sys
import subprocess
import platform
import locale
import re

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
