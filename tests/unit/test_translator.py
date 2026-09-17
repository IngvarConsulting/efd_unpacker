import re
from pathlib import Path
import os
import xml.etree.ElementTree as ET

import pytest

from efd_unpacker.application.messages import (
    CORRUPTED_ARCHIVE_REASONS,
    format_unpack_result,
    format_validation_error,
)
from efd_unpacker.domain.errors import (
    FileValidationCode,
    FileValidationError,
    UnpackError,
    UnpackErrorCode,
)
from efd_unpacker.localization.translator import Translator


def create_ts(tmpdir, lang, context, source, translation):
    ts_path = os.path.join(tmpdir, f"{lang}.ts")
    root = ET.Element("TS")
    ctx = ET.SubElement(root, "context")
    name = ET.SubElement(ctx, "name")
    name.text = context
    msg = ET.SubElement(ctx, "message")
    src = ET.SubElement(msg, "source")
    src.text = source
    trn = ET.SubElement(msg, "translation")
    trn.text = translation
    tree = ET.ElementTree(root)
    tree.write(ts_path, encoding="utf-8", xml_declaration=True)
    return ts_path


def test_translator_returns_translation(tmp_path):
    create_ts(tmp_path, "ru", "TestContext", "Hello", "Привет")
    translator = Translator(lang="ru", translations_dir=str(tmp_path))
    assert translator.translate("TestContext", "Hello") == "Привет"


def test_translator_fallback(tmp_path):
    create_ts(tmp_path, "ru", "TestContext", "Hello", "Привет")
    translator = Translator(lang="ru", translations_dir=str(tmp_path))
    assert translator.translate("Other", "Unknown") == "Unknown"


def test_translator_falls_back_for_empty_translation(tmp_path):
    create_ts(tmp_path, "ru", "TestContext", "Hello", "")
    translator = Translator(lang="ru", translations_dir=str(tmp_path))
    assert translator.translate("TestContext", "Hello") == "Hello"


def _source_keys():
    """
    Пары (context, source), которые приложение может запросить в рантайме.

    Литеральные вызовы translate(...)/_t(...) берём регуляркой, а ключи слоя
    сообщений — прогоном самих форматтеров по всем членам обоих enum через
    записывающий переводчик. Раньше здесь был ast-обход словарей messages.py,
    но он терял контекст: одна и та же строка живёт в разных контекстах, и
    сверка «есть в ts, нет в коде» на таком экстракторе даёт ложные срабатывания.
    """
    root = Path(__file__).resolve().parents[2] / "src" / "efd_unpacker"
    keys = set()

    call_pattern = re.compile(
        r'(?:translate|_t)\(\s*["\']([^"\']+)["\']\s*,\s*["\']((?:[^"\'\\]|\\.)*)["\']',
        re.S,
    )
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for context, source in call_pattern.findall(text):
            keys.add((context, source))

    keys |= _message_layer_keys()
    return keys


class RecordingTranslator:
    """Переводчик, запоминающий каждый запрошенный ключ."""

    def __init__(self):
        self.asked = set()

    def translate(self, context, source):
        self.asked.add((context, source))
        return source


def _message_layer_keys():
    """Всё, что messages.py способен спросить: по члену enum и по причине порчи."""
    recorder = RecordingTranslator()
    for code in FileValidationCode:
        format_validation_error(recorder, FileValidationError(code, {"error": "x"}))
    format_validation_error(recorder, FileValidationError(UnpackErrorCode.UNEXPECTED))
    format_unpack_result(recorder, success=True)
    for code in UnpackErrorCode:
        format_unpack_result(recorder, success=False, error=UnpackError(code, {"error": "x"}))
    for reason in CORRUPTED_ARCHIVE_REASONS:
        format_unpack_result(
            recorder,
            success=False,
            error=UnpackError(UnpackErrorCode.CORRUPTED_ARCHIVE, {"reason": reason}),
        )
    return recorder.asked


def _catalog():
    """Пары (контекст, source) -> (translation, type) из ru.ts."""
    ts_path = Path(__file__).resolve().parents[2] / "translations" / "ru.ts"
    tree = ET.parse(ts_path)
    catalog = {}
    for context in tree.getroot().findall("context"):
        name_element = context.find("name")
        name = name_element.text if name_element is not None else ""
        for message in context.findall("message"):
            source_element = message.find("source")
            translation_element = message.find("translation")
            source = source_element.text if source_element is not None else ""
            catalog[(name, source)] = (
                translation_element.text if translation_element is not None else None,
                translation_element.get("type") if translation_element is not None else None,
            )
    return catalog


def test_every_runtime_string_has_a_russian_translation():
    """Пропавший перевод раньше не ломал ни один тест и уезжал в релиз."""
    catalog = _catalog()
    by_source = {source: value for (_context, source), value in catalog.items()}

    missing = []
    for context, source in sorted(_source_keys(), key=lambda pair: (pair[0] or "", pair[1])):
        if source == "EFD Unpacker":
            continue  # название приложения не переводится намеренно
        if context is not None:
            entry = catalog.get((context, source))
        else:
            entry = by_source.get(source)
        if entry is None:
            missing.append(f"нет перевода: [{context or '*'}] {source}")
            continue
        translation, kind = entry
        if not translation:
            missing.append(f"пустой перевод: [{context or '*'}] {source}")
        elif kind == "unfinished":
            missing.append(f"unfinished: [{context or '*'}] {source}")

    assert not missing, "\n".join(missing)


def test_catalog_has_no_entries_without_a_branch_in_the_code():
    """
    Обратная сторона дрейфа: запись в ru.ts, до которой нет ни одной ветки.

    Прямое направление ловит тест выше, а эта сторона раньше не проверялась
    ничем — так в каталоге и накопились шесть мёртвых записей MainWindow,
    оставшихся после переезда сообщений в FileValidator и UnpackService.
    """
    live = _source_keys()
    dead = sorted(key for key in _catalog() if key not in live)

    assert not dead, "нет ни одной ветки в коде:\n" + "\n".join(
        f"  [{context}] {source}" for context, source in dead
    )


# --- устойчивость загрузчика -------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        "<TS><context><name>X</name><message><source>A</source>",
        "не xml вовсе",
        "",
        "<TS><context><name>X</name></context></TS><TS/>",
    ],
    ids=["обрезанный", "мусор", "пустой", "два корня"],
)
def test_broken_catalog_falls_back_to_english_instead_of_killing_the_process(tmp_path, payload):
    """
    Регресс: ET.parse стоял без обработки ошибок, а вызывается он в main.py
    до создания QApplication. Битый ru.ts означал, что окно не появится вообще,
    молча на сборках Windows и macOS — обе без консоли.
    """
    (tmp_path / "ru.ts").write_text(payload, encoding="utf-8")

    translator = Translator(lang="ru", translations_dir=str(tmp_path))

    assert translator.translate("MainWindow", "Unpack") == "Unpack"


def test_broken_catalog_does_not_keep_stale_entries(tmp_path):
    """Повторная загрузка битого файла обязана оставить словарь пустым."""
    create_ts(tmp_path, "ru", "MainWindow", "Unpack", "Распаковать")
    translator = Translator(lang="ru", translations_dir=str(tmp_path))
    assert translator.translate("MainWindow", "Unpack") == "Распаковать"

    (tmp_path / "ru.ts").write_text("<TS><context>", encoding="utf-8")
    translator.load()

    assert translator.translate("MainWindow", "Unpack") == "Unpack"


def test_unreadable_catalog_falls_back_to_english(tmp_path):
    """OSError при чтении — тот же случай: английский UI лучше мёртвого процесса."""
    ts_path = tmp_path / "ru.ts"
    create_ts(tmp_path, "ru", "MainWindow", "Unpack", "Распаковать")
    os.chmod(ts_path, 0o000)
    try:
        translator = Translator(lang="ru", translations_dir=str(tmp_path))
        assert translator.translate("MainWindow", "Unpack") == "Unpack"
    finally:
        os.chmod(ts_path, 0o644)


@pytest.mark.parametrize("draft_type", ["unfinished", "obsolete", "vanished"])
def test_draft_translations_are_not_shown_to_the_user(tmp_path, draft_type):
    """
    Регресс: атрибут type не читался, и черновик с непустым текстом показывался
    как готовый перевод. lrelease такие записи в .qm не кладёт, но здесь .ts
    читается напрямую, и фильтровать их больше некому.
    """
    ts_path = tmp_path / "ru.ts"
    ts_path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<TS><context><name>MainWindow</name><message>"
        "<source>Unpack</source>"
        f'<translation type="{draft_type}">ЧЕРНОВИК</translation>'
        "</message></context></TS>",
        encoding="utf-8",
    )

    translator = Translator(lang="ru", translations_dir=str(tmp_path))

    assert translator.translate("MainWindow", "Unpack") == "Unpack"


def test_finished_translation_without_type_is_used(tmp_path):
    """Фильтр черновиков не должен задевать обычные записи."""
    create_ts(tmp_path, "ru", "MainWindow", "Unpack", "Распаковать")

    translator = Translator(lang="ru", translations_dir=str(tmp_path))

    assert translator.translate("MainWindow", "Unpack") == "Распаковать"


def test_real_catalog_has_no_draft_entries_left():
    """После чистки в ru.ts не должно остаться ни одного type=... ."""
    ts_path = Path(__file__).resolve().parents[2] / "translations" / "ru.ts"
    drafts = [
        (context.find("name").text, message.find("source").text, message.find("translation").get("type"))
        for context in ET.parse(ts_path).getroot().findall("context")
        for message in context.findall("message")
        if message.find("translation") is not None and message.find("translation").get("type")
    ]

    assert not drafts, drafts
