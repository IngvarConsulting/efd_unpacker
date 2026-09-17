import codecs
import logging
import os
import sys
import subprocess
import platform
from typing import Dict, List

logger = logging.getLogger(__name__)

CONFIG_TEMPLATES_KEY = 'ConfigurationTemplatesLocation='

# BOM однозначно задаёт кодировку. Кодек utf-16 (в отличие от utf-16le)
# сам снимает BOM и сам определяет порядок байт.
_BOM_ENCODINGS = (
    (codecs.BOM_UTF8, 'utf-8-sig'),
    (codecs.BOM_UTF16_LE, 'utf-16'),
    (codecs.BOM_UTF16_BE, 'utf-16'),
)

# Перебор без BOM: платформа 1С пишет конфиг и в utf-8, и в cp1251,
# и в utf-16 без сигнатуры.
_FALLBACK_ENCODINGS = ('utf-8', 'cp1251', 'utf-16-le', 'utf-16-be')

def get_1c_configuration_location_default() -> str:
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

def get_1c_configuration_location_from_1cestart() -> List[str]:
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
        if not os.path.isfile(config_path):
            continue
        try:
            with open(config_path, 'rb') as handle:
                raw = handle.read()
        except OSError as exc:
            logger.warning("Не удалось прочитать %s: %s", config_path, exc)
            continue
        for value in _locations_from_text(_decode_config(raw)):
            if value not in locations:
                locations.append(value)
    return locations


def _decode_config(raw: bytes) -> str:
    """
    Декодирует 1cestart.cfg, выбирая кодировку по результату, а не по отсутствию ошибки.

    Прежний перебор останавливался на первом кодеке, который не бросил исключение,
    а utf-16le не бросает почти никогда: любая последовательность чётной длины
    декодируется в иероглифы. Поэтому корректно разбирался только utf-8, а cp1251
    проходил через раз — в зависимости от чётности размера файла. Критерий теперь
    прямой: в тексте должен найтись сам ключ.
    """
    encodings = []
    for bom, encoding in _BOM_ENCODINGS:
        if raw.startswith(bom):
            encodings.append(encoding)
            break
    encodings.extend(_FALLBACK_ENCODINGS)

    fallback = ""
    for encoding in encodings:
        try:
            text = raw.decode(encoding)
        except UnicodeError:
            continue
        if CONFIG_TEMPLATES_KEY in text:
            return text
        if not fallback:
            fallback = text
    return fallback


def _locations_from_text(text: str) -> List[str]:
    """Значения ConfigurationTemplatesLocation из уже декодированного текста."""
    found = []
    for line in text.splitlines():
        # lstrip до strip: \ufeff не пробельный, и utf-16le оставлял BOM в начале
        # первой строки, из-за чего она не проходила проверку префикса.
        line = line.lstrip('\ufeff').strip()
        if line.startswith(CONFIG_TEMPLATES_KEY):
            value = line.split('=', 1)[1]
            if value:
                found.append(value)
    return found

def child_environment() -> Dict[str, str]:
    """
    Окружение для системной команды открытия папки.

    Бутлоадер onefile-сборки PyInstaller указывает LD_LIBRARY_PATH на каталог
    распаковки, а оригинал кладёт в LD_LIBRARY_PATH_ORIG. Без восстановления
    дочерний gio/kioclient/gtk-launch подхватывает оттуда Qt и libstdc++ вместо
    системных и падает с symbol lookup error.
    """
    env = os.environ.copy()
    original = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if original is None:
        env.pop("LD_LIBRARY_PATH", None)
    else:
        env["LD_LIBRARY_PATH"] = original
    return env


def open_folder(path: str) -> bool:
    """Открывает указанный путь в системном файловом менеджере."""
    if not os.path.exists(path):
        return False
    # abspath, а не разделитель опций "--": xdg-open его не понимает и отвечает
    # `unexpected option` с кодом 1. Абсолютный путь не может начинаться с дефиса.
    target = os.path.abspath(path)
    try:
        if platform.system() == "Windows":
            os.startfile(target)  # type: ignore[attr-defined]
            return True
        command = "open" if platform.system() == "Darwin" else "xdg-open"
        # Код возврата раньше не читался: xdg-open отвечает 3 или 4, когда
        # ассоциации inode/directory нет, а пользователь видел «открыл».
        result = subprocess.run([command, target], env=child_environment())
        if result.returncode != 0:
            logger.warning("%s вернул код %s для %s", command, result.returncode, target)
            return False
        return True
    except Exception as exc:
        logger.warning("Не удалось открыть папку %s: %s", target, exc)
        return False
