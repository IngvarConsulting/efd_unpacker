"""
EFD Unpacker package.
"""

from importlib import metadata


def get_version() -> str:
    """
    Возвращает версию пакета, если он установлен.
    Для локальной разработки, где дистрибутива нет, возвращает '0.0.0'.
    """
    try:
        return metadata.version("efd_unpacker")
    except metadata.PackageNotFoundError:
        return "0.0.0"


__all__ = ["get_version"]
