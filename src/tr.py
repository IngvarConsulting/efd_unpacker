import os
import xml.etree.ElementTree as ET

class Translator:
    def __init__(self, lang='en', translations_dir='translations'):
        self.translations = {}
        self.lang = lang
        self.translations_dir = translations_dir
        self._load_translations()

    def _load_translations(self):
        self.translations = {}
        ts_path = os.path.join(self.translations_dir, f'{self.lang}.ts')
        if not os.path.isfile(ts_path):
            return
        tree = ET.parse(ts_path)
        root = tree.getroot()
        for ctx in root.findall('context'):
            name_elem = ctx.find('name')
            context_name = name_elem.text if name_elem is not None else ''
            for msg in ctx.findall('message'):
                source_elem = msg.find('source')
                translation_elem = msg.find('translation')
                source = source_elem.text if source_elem is not None else ''
                translation = translation_elem.text if translation_elem is not None else ''
                self.translations[(context_name, source)] = translation

    def tr(self, context, source):
        return self.translations.get((context, source), source)

# Глобальный экземпляр (язык можно будет менять динамически)
translator = Translator(lang='ru')

def tr(context, source):
    return translator.tr(context, source) 