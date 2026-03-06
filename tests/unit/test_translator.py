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
