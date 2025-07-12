import os
import sys
import subprocess
import platform

def get_default_unpack_dir():
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