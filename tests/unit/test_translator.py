import ast
from pathlib import Path
import os
import xml.etree.ElementTree as ET

import pytest

from efd_unpacker.application.messages import (
    CORRUPTED_ARCHIVE_REASONS,
    format_unpack_result,
    format_validation_error,
)
from efd_unpacker.application import report
from efd_unpacker.application.report import format_plan
from efd_unpacker.domain.batch import BatchResult
from efd_unpacker.domain.plan import Action, ItemKind, Plan, PlannedItem, SkipReason
from efd_unpacker.domain.errors import (
    FileValidationCode,
    FileValidationError,
    UnpackError,
    UnpackErrorCode,
)
from efd_unpacker.localization import translator as translator_module
from efd_unpacker.localization.translator import Translator

#: Настоящие каталоги: тесты форм проверяют то, что поедет в сборку.
_TRANSLATIONS = Path(__file__).resolve().parents[2] / "translations"


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

    Литеральные вызовы translate(...)/_t(...) берём разбором самого кода, а
    ключи слоя сообщений — прогоном форматтеров по всем членам обоих enum через
    записывающий переводчик. Раньше здесь был ast-обход словарей messages.py,
    но он терял контекст: одна и та же строка живёт в разных контекстах, и
    сверка «есть в ts, нет в коде» на таком экстракторе даёт ложные срабатывания.

    Разбор, а не регулярка: длинная строка в исходнике лежит склейкой из
    нескольких литералов подряд, и регулярка брала от неё только первый кусок.
    Ключ уезжал в ts целиком, а сверка искала обрезанный — и оба направления
    ругались разом, притом на строки, с которыми всё в порядке.
    """
    root = Path(__file__).resolve().parents[2] / "src" / "efd_unpacker"
    keys = set()

    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "attr", None) not in ("translate", "translate_n", "_t"):
                continue
            arguments = node.args
            if len(arguments) < 2:
                continue
            context, source = arguments[0], arguments[1]
            if isinstance(context, ast.Constant) and isinstance(source, ast.Constant):
                keys.add((context.value, source.value))

    keys |= _message_layer_keys()
    keys |= _report_layer_keys()
    keys |= _settings_layer_keys()
    keys |= _window_layer_keys()
    return keys


class RecordingTranslator:
    """Переводчик, запоминающий каждый запрошенный ключ."""

    def __init__(self):
        self.asked = set()

    def translate(self, context, source):
        self.asked.add((context, source))
        return source


    def translate_n(self, context: str, source: str, n: int) -> str:
        """Множественная форма: двойнику достаточно подставить число."""
        return self.translate(context, source).replace("%n", str(n))
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


def _report_layer_keys():
    """
    Всё, что report.py способен спросить.

    Ключи там лежат в таблицах по членам enum, а не в литеральных вызовах, и
    регулярка их не видит. Поэтому план собирается из всех видов, всех причин
    пропуска и отказа, и прогоняется через записывающий переводчик — новый член
    enum без перевода упадёт здесь, а не у пользователя.
    """
    recorder = RecordingTranslator()
    items = [
        PlannedItem(
            kind=kind, title="t", version="1", source=("a",), origin="/d/a",
            destination="/root/sub/%s" % kind.value, bytes_total=1, action=Action.WRITE,
        )
        for kind in ItemKind
    ]
    items += [
        PlannedItem(
            kind=ItemKind.OTHER, title="t", version="", source=("a",), origin="/d/a",
            destination="", bytes_total=0, action=Action.SKIP, reason=reason,
        )
        for reason in SkipReason
    ]
    items.append(
        PlannedItem(
            kind=ItemKind.OTHER, title="t", version="", source=("a",), origin="/d/a",
            destination="", bytes_total=0, action=Action.FAIL,
            failure=UnpackError(UnpackErrorCode.UNEXPECTED, {"error": "x"}),
        )
    )
    plan = Plan(items=tuple(items))
    format_plan(recorder, plan, source_count=1, elapsed=0.0)
    # Второй прогон — с исходом: после распаковки первая колонка и итоговая
    # строка берут другие ключи, и без этого они остались бы без перевода.
    format_plan(
        recorder, plan, source_count=1, elapsed=0.0,
        result=BatchResult(
            written=(items[0],),
            failed=((items[-1], UnpackError(UnpackErrorCode.UNEXPECTED, {})),),
            cancelled=True,
        ),
    )
    return recorder.asked


def _settings_layer_keys():
    """
    Подписи происхождения пути. Лежат в таблице по коду, а не в литеральных
    вызовах, и регулярка их не видит — как и ключи слоя отчёта.
    """
    from efd_unpacker.infrastructure.settings_service import ORIGIN_KEYS

    return {("SettingsService", key) for key in ORIGIN_KEYS.values()}


def _window_layer_keys():
    """
    Ключи окна, которые берутся из таблиц и констант, а не из литералов:
    заголовки колонок, роли каталогов и причины пропуска.
    """
    from efd_unpacker.presentation import ui

    from efd_unpacker.application import report

    keys = {("MainWindow", ui.ROLE_TEMPLATES), ("MainWindow", ui.ROLE_DISTRIBUTIONS)}
    keys |= {("Report", key) for key in ui.REASON_KEYS.values()}
    # Подписи итоговой строки окна: те же ключи, что у отчёта CLI. Берутся из
    # самого отчёта, а не переписываются сюда: переписанный список пережил
    # смену ключей на множественные формы и пять суток показывал их живыми.
    keys |= {("Report", source) for source in (
        report.COUNT_FILES, report.COUNT_TEMPLATES, report.COUNT_DISTRIBUTIONS,
        report.COUNT_OTHER, report.COUNT_SKIPPED, report.COUNT_ERRORS,
    )}
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


BROKEN_CATALOGS = {
    "обрезанный": "<TS><context><name>X</name><message><source>A</source>",
    "мусор": "не xml вовсе",
    "пустой": "",
    "два корня": "<TS><context><name>X</name></context></TS><TS/>",
    # ParseError тут ни при чём: expat поднимает LookupError ещё до разбора.
    "кодировка NOPE": '<?xml version="1.0" encoding="NOPE"?><TS/>',
    "кодировка пустая": '<?xml version="1.0" encoding=""?><TS/>',
    "битая сущность": '<?xml version="1.0"?><TS>&nope;</TS>',
    "нулевой байт": '<?xml version="1.0"?><TS>\x00</TS>',
}


@pytest.mark.parametrize("payload", BROKEN_CATALOGS.values(), ids=list(BROKEN_CATALOGS))
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


def test_catalog_that_cannot_be_read_falls_back_to_english(tmp_path, monkeypatch):
    """
    OSError при чтении — тот же случай: английский UI лучше мёртвого процесса.

    Проверяем подменой парсера, а не правами файла: на Windows chmod(0o000)
    ставит лишь признак «только чтение» и доступ на чтение не отзывает, так
    что настоящая проверка прав там ничего не проверяет.
    """
    create_ts(tmp_path, "ru", "MainWindow", "Unpack", "Распаковать")

    def denied(*_args, **_kwargs):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(translator_module.ET, "parse", denied)
    translator = Translator(lang="ru", translations_dir=str(tmp_path))

    assert translator.translate("MainWindow", "Unpack") == "Unpack"


@pytest.mark.skipif(os.name == "nt", reason="chmod(0o000) на Windows не отзывает чтение")
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root читает что угодно")
def test_catalog_without_read_permission_falls_back_to_english(tmp_path):
    """Тот же откат, но на настоящем отказе прав, а не на подмене."""
    ts_path = tmp_path / "ru.ts"
    create_ts(tmp_path, "ru", "MainWindow", "Unpack", "Распаковать")
    os.chmod(ts_path, 0o000)
    try:
        translator = Translator(lang="ru", translations_dir=str(tmp_path))
        assert translator.translate("MainWindow", "Unpack") == "Unpack"
    finally:
        os.chmod(ts_path, 0o644)


def test_any_parser_failure_is_survivable(tmp_path, monkeypatch):
    """
    Гарантия шире перечня типов: что бы ни поднял парсер, запуск не ломается.

    Список исключений ET.parse открытый — ParseError, LookupError, OSError
    наблюдались на реальных входах, — и перечисление типов в except однажды
    пропустит ещё один и вернёт молчаливое падение на старте.
    """
    create_ts(tmp_path, "ru", "MainWindow", "Unpack", "Распаковать")

    for exception in (RuntimeError("неожиданно"), MemoryError(), RecursionError()):
        monkeypatch.setattr(
            translator_module.ET,
            "parse",
            lambda *_a, _exc=exception, **_k: (_ for _ in ()).throw(_exc),
        )
        assert Translator(lang="ru", translations_dir=str(tmp_path)).translate(
            "MainWindow", "Unpack"
        ) == "Unpack"


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


# --- множественные формы -----------------------------------------------------


@pytest.mark.parametrize(
    "count, expected",
    [(1, "1 файл"), (2, "2 файла"), (5, "5 файлов"),
     (11, "11 файлов"), (21, "21 файл"), (112, "112 файлов")],
)
def test_russian_plural_forms(count, expected):
    """
    Критерий #61: все шесть чисел из задачи.

    Одиннадцать и сто двенадцать здесь не для полноты: на них ошибается
    наивное правило «смотрим последнюю цифру», а именно оно первым приходит
    в голову.
    """
    translator = Translator(lang="ru", translations_dir=str(_TRANSLATIONS))

    assert translator.translate_n("Report", report.COUNT_FILES, count) == expected


@pytest.mark.parametrize(
    "count, expected", [(1, "1 file"), (2, "2 files"), (21, "21 files")]
)
def test_english_has_two_forms(count, expected):
    """У английского форм две, и «1 files» — такая же ошибка, как «1 файлов»."""
    translator = Translator(lang="en", translations_dir=str(_TRANSLATIONS))

    assert translator.translate_n("Report", report.COUNT_FILES, count) == expected


def test_region_in_the_language_code_does_not_lose_the_rule():
    """
    «ru_RU» — тоже русский.

    Свой detect_system_language отдаёт ровно «ru», но Translator — открытый
    конструктор, и код языка с регионом в него попасть может. Без отсечения
    региона он молча свалился бы на английские две формы: «5 файла» вместо
    «5 файлов».

    Проверяется на пяти, а не на двух: на двойке русское правило и
    английское дают один и тот же номер формы, и подмена была бы не видна.
    """
    translator = Translator(lang="ru_RU", translations_dir=str(_TRANSLATIONS))

    assert translator.plural_form(5) == 2, "выбрана форма не по русскому правилу"
    assert translator.translate_n("Report", report.COUNT_FILES, 5) == "5 файлов"


def test_missing_catalog_falls_back_to_the_source_with_the_number(tmp_path):
    """Без перевода строка английская и несклоняемая — но с числом."""
    translator = Translator(lang="xx", translations_dir=str(tmp_path))

    assert translator.translate_n("Report", "%n file(s)", 7) == "7 file(s)"


def test_entry_with_one_form_instead_of_three_is_not_shown_as_empty(tmp_path):
    """
    Пустая форма считается отсутствующей.

    Каталог с пропуском обязан вести себя как каталог без записи: показать
    пустое место вместо слова хуже, чем показать английское.
    """
    (tmp_path / "ru.ts").write_text(
        '<?xml version="1.0" encoding="utf-8"?><TS version="2.1" language="ru_RU">'
        "<context><name>Report</name>"
        '<message numerus="yes"><source>%n file(s)</source><translation>'
        "<numerusform>%n файл</numerusform><numerusform></numerusform>"
        "<numerusform>%n файлов</numerusform></translation></message>"
        "</context></TS>",
        encoding="utf-8",
    )
    translator = Translator(lang="ru", translations_dir=str(tmp_path))

    assert translator.translate_n("Report", "%n file(s)", 1) == "1 файл"
    assert translator.translate_n("Report", "%n file(s)", 2) == "2 file(s)"


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_every_numerus_entry_has_all_its_forms(lang):
    """
    Критерий #61: отсутствующая форма ловится сторожевым тестом.

    Запись с одной формой вместо трёх читается как полноценная и падает не
    на сборке, а у человека — на числе, которое в неё не попало.
    """
    translator = Translator(lang=lang, translations_dir=str(_TRANSLATIONS))
    expected = translator.forms_expected()
    tree = ET.parse(_TRANSLATIONS / ("%s.ts" % lang))

    short = []
    for context in tree.getroot().findall("context"):
        name = context.find("name")
        for message in context.findall("message"):
            if message.get("numerus") != "yes":
                continue
            source = message.find("source")
            forms = message.find("translation").findall("numerusform")
            filled = [form for form in forms if (form.text or "").strip()]
            if len(filled) != expected:
                short.append("[%s] %s: форм %d из %d" % (
                    name.text, source.text, len(filled), expected,
                ))

    assert not short, "\n".join(short)


def test_summary_of_info_reads_as_the_mockup_says():
    """
    Критерий #61: итоговая строка совпадает с макетом по форме.

    Было «шаблонов: 10» — верно при любом числе, но это обход. Стало
    «10 шаблонов», «1 шаблон», «2 шаблона».
    """
    from efd_unpacker.domain.plan import Action, ItemKind, Plan, PlannedItem

    def item(kind, count):
        return [
            PlannedItem(
                kind=kind, title="t", version="1", source=("a",), origin="/d/a",
                destination="/root/x", bytes_total=1, action=Action.WRITE,
            )
            for _ in range(count)
        ]

    plan = Plan(items=tuple(item(ItemKind.SUPPLY, 10) + item(ItemKind.PLATFORM, 4)))
    translator = Translator(lang="ru", translations_dir=str(_TRANSLATIONS))

    summary = report.format_plan(translator, plan, source_count=15, elapsed=0.4)

    assert "15 файлов · 10 шаблонов · 4 дистрибутива" in summary


def test_region_in_the_language_code_finds_the_catalog(tmp_path):
    """
    Каталог ищется и по языку без региона.

    Иначе «ru_RU» давал бы половинчатое поведение: правило форм русское,
    а слова английские, — потому что регион отсекает правило, но не имя файла.
    """
    (tmp_path / "ru.ts").write_text(
        '<?xml version="1.0" encoding="utf-8"?><TS version="2.1" language="ru_RU">'
        "<context><name>Report</name><message><source>files:</source>"
        "<translation>файлов:</translation></message></context></TS>",
        encoding="utf-8",
    )

    assert Translator(lang="ru_RU", translations_dir=str(tmp_path)).translate(
        "Report", "files:"
    ) == "файлов:"


def test_exact_catalog_wins_over_the_base_language(tmp_path):
    """Точный каталог важнее отката: «pt_BR» — не то же, что «pt»."""
    for name, word in (("pt", "base"), ("pt_BR", "exact")):
        (tmp_path / ("%s.ts" % name)).write_text(
            '<?xml version="1.0" encoding="utf-8"?><TS version="2.1">'
            "<context><name>Report</name><message><source>files:</source>"
            "<translation>%s</translation></message></context></TS>" % word,
            encoding="utf-8",
        )

    assert Translator(lang="pt_BR", translations_dir=str(tmp_path)).translate(
        "Report", "files:"
    ) == "exact"
