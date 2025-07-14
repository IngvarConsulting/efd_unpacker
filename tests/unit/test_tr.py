import os
import tempfile
import shutil
import xml.etree.ElementTree as ET
import pytest
from src.tr import Translator, tr

def create_test_ts(tmpdir, lang, context, source, translation):
    ts_path = os.path.join(tmpdir, f'{lang}.ts')
    root = ET.Element('TS')
    ctx = ET.SubElement(root, 'context')
    name = ET.SubElement(ctx, 'name')
    name.text = context
    msg = ET.SubElement(ctx, 'message')
    src = ET.SubElement(msg, 'source')
    src.text = source
    trn = ET.SubElement(msg, 'translation')
    trn.text = translation
    tree = ET.ElementTree(root)
    tree.write(ts_path, encoding='utf-8', xml_declaration=True)
    return ts_path

def test_tr_returns_translation(tmp_path):
    # Arrange
    lang = 'ru'
    context = 'TestContext'
    source = 'Hello'
    translation = 'Привет'
    create_test_ts(tmp_path, lang, context, source, translation)
    translator = Translator(lang=lang, translations_dir=str(tmp_path))
    # Act
    result = translator.tr(context, source)
    # Assert
    assert result == translation

def test_tr_returns_source_if_not_found(tmp_path):
    lang = 'ru'
    context = 'TestContext'
    source = 'Hello'
    translation = 'Привет'
    create_test_ts(tmp_path, lang, context, source, translation)
    translator = Translator(lang=lang, translations_dir=str(tmp_path))
    # Act
    result = translator.tr('OtherContext', 'OtherText')
    # Assert
    assert result == 'OtherText' 