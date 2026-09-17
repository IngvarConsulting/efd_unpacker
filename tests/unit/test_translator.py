import ast
import re
from pathlib import Path
import os
import xml.etree.ElementTree as ET

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
    Ключи, которые приложение запрашивает в рантайме.

    messages.py собирает их из словарей, поэтому literal-строки берём AST-обходом,
    а вызовы translate(...)/_t(...) — регуляркой.
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

    # messages.py: значения словарей кодов ошибок и причин повреждения.
    messages = root / "application" / "messages.py"
    tree = ast.parse(messages.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    keys.add((None, value.value))
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "key":
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        keys.add((None, node.value.value))
    return keys


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
