"""
Генератор синтетических .efd для негативных тестов.

Формат разбирается в onec_dtools/supply_reader.py: заголовок, блок описаний
поставки, список включённых файлов и следом их содержимое единым потоком,
всё завёрнуто в raw deflate (wbits -15). Держать вредоносные фикстуры в
репозитории незачем — архив собирается в tmp_path во время прогона.
"""

import struct
import zlib
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

# 2020-01-01 в FILETIME: 100-наносекундные интервалы с 1601 года.
FILETIME_2020 = 132223104000000000
# Дата до 1970 года — такие приходят в реальных поставках 1С.
FILETIME_1601 = 0


def wide_string(value: str) -> bytes:
    """Строка в формате .efd: длина в символах, затем UTF-16."""
    encoded = value.encode("utf-16")
    return struct.pack("I", len(encoded) // 2) + encoded


def build_efd(
    entries: Sequence[Tuple[str, bytes]],
    header: int = 1,
    declared_sizes: Optional[Sequence[int]] = None,
    filetime: int = FILETIME_2020,
    supply_info: Iterable[Tuple[str, str, str, str]] = (),
) -> bytes:
    """
    Собирает .efd из пар (имя записи, содержимое).

    declared_sizes позволяет соврать о размере записи — так проверяется
    поведение на усечённом или подделанном архиве. header != 1 имитирует
    чужую версию формата.
    """
    supply_info = list(supply_info)
    head = struct.pack("II", header, len(supply_info))

    for lang, name, provider, description_path in supply_info:
        head += struct.pack("I", 0)
        head += wide_string(lang)
        head += wide_string(name)
        head += wide_string(provider)
        head += wide_string(description_path)

    head += struct.pack("I", len(entries))
    payload = b""
    for index, (name, data) in enumerate(entries):
        declared = declared_sizes[index] if declared_sizes is not None else len(data)
        head += struct.pack("I", 0)
        head += wide_string(name)
        head += struct.pack("Q", filetime)
        head += struct.pack("I", 0)
        head += struct.pack("I", declared)
        payload += data

    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    return compressor.compress(head + payload) + compressor.flush()


def write_efd(path: Path, entries: Sequence[Tuple[str, bytes]], **kwargs) -> str:
    """Собирает архив и кладёт его по указанному пути. Возвращает путь строкой."""
    path.write_bytes(build_efd(entries, **kwargs))
    return str(path)


def unpacked_tree(root: Path) -> List[str]:
    """Отсортированные относительные пути всех распакованных файлов."""
    return sorted(
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    )
