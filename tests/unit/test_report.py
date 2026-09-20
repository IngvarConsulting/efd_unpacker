"""
Тесты показа плана.

Таблица и JSON рисуют одно и то же значение. Проверяется то, на что опирается
потребитель: у человека — выравнивание и понятные слова, у машины — стабильные
ключи, которые не меняются вслед за языком интерфейса.
"""

import json

import pytest

from efd_unpacker.application.report import JSON_SCHEMA, format_json, format_plan, human_bytes
from efd_unpacker.domain.errors import UnpackError, UnpackErrorCode
from efd_unpacker.domain.plan import Action, ItemKind, Plan, PlannedItem, SkipReason


class Passthrough:
    """Переводчик, отдающий исходную строку: тест про формат, а не про язык."""

    def translate(self, _context, source):
        return source


    def translate_n(self, context: str, source: str, n: int) -> str:
        """Множественная форма: двойнику достаточно подставить число."""
        return self.translate(context, source).replace("%n", str(n))
def item(**kwargs):
    defaults = dict(
        kind=ItemKind.SUPPLY, title="Бухгалтерия", version="3.0.1", source=("a.zip",),
        origin="/d/a.zip", destination="/root/tmplts/1c/Acc/3_0_1",
        bytes_total=1024, action=Action.WRITE,
        file_count=2,
    )
    defaults.update(kwargs)
    return PlannedItem(**defaults)


def plan(*items):
    return Plan(items=tuple(items))


class _Result:
    """Результат батча в объёме, который нужен отчёту."""

    def __init__(self, written=(), failed=(), skipped=(), cancelled=False):
        self.written = written
        self.failed = failed
        self.skipped = skipped
        self.cancelled = cancelled

    @property
    def bytes_written(self):
        return sum(entry.bytes_total for entry in self.written)


def _rows(text):
    """
    Только строки таблицы.

    По вхождению «template» фильтровать нельзя: итоговая строка содержит
    «templates:» и попадала бы в выборку.
    """
    return [line for line in text.splitlines() if line.startswith("template ")]


# --- размеры -----------------------------------------------------------------


@pytest.mark.parametrize(
    "size, expected",
    [
        (0, "0B"),
        (1023, "1023B"),
        (1024, "1.0K"),
        (10 * 1024, "10K"),
        (135 * 1024 ** 2, "135M"),
        (int(2.3 * 1024 ** 3), "2.3G"),
    ],
)
def test_size_is_short_and_keeps_a_digit_where_it_distinguishes(size, expected):
    assert human_bytes(size) == expected


# --- таблица -----------------------------------------------------------------


def test_columns_are_aligned_across_rows():
    text = format_plan(
        Passthrough(),
        plan(item(title="Короткое"), item(title="Очень длинное наименование")),
        source_count=1,
        elapsed=0.5,
    )
    rows = _rows(text)

    assert len(rows) == 2
    assert len({row.index("3.0.1") for row in rows}) == 1, "колонка версии разъехалась"


def test_size_column_is_right_aligned():
    text = format_plan(
        Passthrough(),
        plan(item(bytes_total=10 * 1024), item(bytes_total=135 * 1024 ** 2)),
        source_count=1,
        elapsed=0.1,
    )
    rows = _rows(text)

    # Ширины разные намеренно: «10K» и «135M» при выравнивании влево встали бы
    # по левому краю и отличить rjust от ljust стало бы невозможно.
    assert [row.rstrip().split()[-2] for row in rows] == ["10K", "135M"]
    assert len({row.index("10K") + 3 for row in rows[:1]} | {row.index("135M") + 4 for row in rows[1:]}) == 1
    assert len({row.index("3_0_1") for row in rows}) == 1, "колонка назначения разъехалась"


def test_skipped_row_shows_the_reason_instead_of_the_kind():
    """
    Пользователь ищет глазами, что не поедет.

    «distribution» в строке, которая никуда не распакуется, вводит в
    заблуждение, поэтому исход вытесняет вид.
    """
    text = format_plan(
        Passthrough(),
        plan(item(kind=ItemKind.PLATFORM, action=Action.SKIP,
                  reason=SkipReason.RAR_TOOL_MISSING, destination="", bytes_total=0)),
        source_count=1,
        elapsed=0.1,
    )

    assert "skipped" in text and "no program for .rar" in text
    assert "distribution" not in text.split("\n\n")[0]


def test_failed_row_shows_the_error_text():
    text = format_plan(
        Passthrough(),
        plan(item(action=Action.FAIL, destination="", bytes_total=0,
                  failure=UnpackError(UnpackErrorCode.NESTING_TOO_DEEP, {}))),
        source_count=1,
        elapsed=0.1,
    )

    assert "error" in text
    assert "too many nested archives" in text


def test_common_prefix_is_printed_once_and_stripped_from_rows():
    text = format_plan(
        Passthrough(),
        plan(
            item(destination="/home/u/1cv8/tmplts/1c/A/1_0"),
            item(destination="/home/u/1cv8/dist/platform/8_3"),
        ),
        source_count=2,
        elapsed=0.1,
    )

    assert text.startswith("paths: /home/u/1cv8\n")
    assert "tmplts/1c/A/1_0" in text
    assert "/home/u/1cv8/tmplts" not in text


def test_single_destination_keeps_the_full_path():
    """Выносить общее начало не из чего — путь должен остаться целым."""
    text = format_plan(Passthrough(), plan(item()), source_count=1, elapsed=0.1)

    assert "paths:" not in text
    assert "/root/tmplts/1c/Acc/3_0_1" in text


def test_identical_destinations_do_not_leave_an_empty_column():
    """
    Общее начало совпало с путём целиком — «куда» превратилось бы в пробел.

    Так бывает, когда один и тот же шаблон найден в двух файлах.
    """
    text = format_plan(
        Passthrough(),
        plan(item(destination="/root/tmplts/1c/A/1_0"), item(destination="/root/tmplts/1c/A/1_0")),
        source_count=2,
        elapsed=0.1,
    )

    assert "1_0" in text
    for line in _rows(text):
        assert line.rstrip().endswith("1_0")


def test_summary_counts_every_outcome():
    text = format_plan(
        Passthrough(),
        plan(
            item(),
            item(kind=ItemKind.PLATFORM),
            item(kind=ItemKind.OTHER, action=Action.SKIP, reason=SkipReason.NOTHING_FOUND,
                 destination="", bytes_total=0),
            item(kind=ItemKind.OTHER, action=Action.FAIL, destination="", bytes_total=0,
                 failure=UnpackError(UnpackErrorCode.UNEXPECTED, {})),
        ),
        source_count=4,
        elapsed=0.42,
    )
    summary = text.splitlines()[-1]

    assert "4 file(s)" in summary
    assert "1 template(s)" in summary
    assert "1 distribution(s)" in summary
    assert "1 skipped" in summary
    assert "1 error(s)" in summary
    assert "0.4s" in summary


def test_empty_plan_still_prints_a_summary():
    text = format_plan(Passthrough(), plan(), source_count=0, elapsed=0.0)

    assert "0 file(s)" in text


# --- JSON --------------------------------------------------------------------


def test_json_keys_are_enum_values_not_translations():
    """
    Ключи kind/action/reason разбирает машина.

    Локализованная строка здесь означала бы, что вывод меняется вместе с языком
    интерфейса, и потребитель ломается при смене локали.
    """
    document = json.loads(
        format_json(
            plan(item(kind=ItemKind.PLATFORM, action=Action.SKIP,
                      reason=SkipReason.ALREADY_INSTALLED)),
            source_count=1, elapsed=0.1,
        )
    )
    entry = document["items"][0]

    assert document["schema"] == JSON_SCHEMA
    assert entry["kind"] == "platform"
    assert entry["action"] == "skip"
    assert entry["reason"] == "already_installed"


def test_json_carries_sizes_counts_and_destination():
    document = json.loads(format_json(plan(item()), source_count=1, elapsed=0.25))
    entry = document["items"][0]

    assert entry["bytes"] == 1024
    assert entry["files"] == 2
    assert entry["destination"] == "/root/tmplts/1c/Acc/3_0_1"
    assert entry["source"] == ["a.zip"]
    assert document["totals"] == {
        "files": 1, "items": 1, "write": 1, "skip": 0, "fail": 0,
        "bytes": 1024, "seconds": 0.25,
    }


def test_json_reports_the_error_code_for_failures():
    document = json.loads(
        format_json(
            plan(item(action=Action.FAIL, destination="", bytes_total=0,
                      failure=UnpackError(UnpackErrorCode.UNSAFE_ENTRY, {"entry": "../x"}))),
            source_count=1, elapsed=0.1,
        )
    )
    entry = document["items"][0]

    assert entry["action"] == "fail"
    assert entry["error"]["code"] == UnpackErrorCode.UNSAFE_ENTRY.value
    assert entry["error"]["details"]["entry"] == "../x"


def test_json_survives_details_that_are_not_plain_values():
    """Детали ошибки собирались для человека; сериализатор не должен падать."""
    document = json.loads(
        format_json(
            plan(item(action=Action.FAIL, destination="", bytes_total=0,
                      failure=UnpackError(UnpackErrorCode.UNEXPECTED, {"error": ValueError("x")}))),
            source_count=1, elapsed=0.1,
        )
    )

    assert document["items"][0]["error"]["details"]["error"] == "x"


def test_json_omits_reason_and_error_when_there_are_none():
    """Пустые ключи заставляют потребителя различать «нет» и «пусто»."""
    entry = json.loads(format_json(plan(item()), source_count=1, elapsed=0.1))["items"][0]

    assert "reason" not in entry
    assert "error" not in entry


def test_json_is_stable_for_the_same_plan():
    same = plan(item(), item(kind=ItemKind.PLATFORM))

    assert format_json(same, 2, 0.1) == format_json(same, 2, 0.1)


def test_summary_counts_failures_that_happened_while_writing():
    """
    После исполнения отказы считаются по результату, а не по плану.

    В плане отмечены только отказы осмотра, поэтому прогон, где не записалось
    ничего, печатал «errors: 0» — и расходился с --json, который уже брал
    число из результата.
    """
    written, failed = item(title="A"), item(title="B")
    text = format_plan(
        Passthrough(), plan(written, failed), source_count=2, elapsed=0.1,
        result=_Result(written=(written,),
                       failed=((failed, UnpackError(UnpackErrorCode.PERMISSION)),)),
    )
    summary = text.splitlines()[-1]

    assert "1 error(s)" in summary
    assert "written:" in summary


def test_outcome_key_separates_files_with_the_same_name():
    """
    Два входных файла с одинаковым именем в разных каталогах дают одну тропу
    и одно назначение. Без origin в ключе исход одного затирал исход другого,
    и в отчёте оказывался чужой результат.
    """
    first = item(title="A", origin="/x/demo.zip", source=("demo.zip", "1cv8.efd"))
    second = item(title="B", origin="/y/demo.zip", source=("demo.zip", "1cv8.efd"))
    text = format_plan(
        Passthrough(), plan(first, second), source_count=2, elapsed=0.1,
        result=_Result(written=(first,),
                       failed=((second, UnpackError(UnpackErrorCode.PERMISSION)),)),
    )

    rows = [line for line in text.splitlines() if line.startswith(("written", "error"))]
    assert len(rows) == 2
    assert rows[0].startswith("written") and "A" in rows[0]
    assert rows[1].startswith("error") and "B" in rows[1]


def test_template_emptied_by_the_filter_is_counted_as_skipped():
    """
    Шаблон, у которого фильтр унёс единственную конфигурацию, в «templates»
    попадать не должен: на диск он не поедет.

    Счётчики читают исход элемента, а не его вид, — и эта правка проверяет
    ровно то, что они не разойдутся с тем, что лежит на диске.
    """
    current = plan(
        item(title="Демо", action=Action.SKIP, reason=SkipReason.FILTERED_OUT, bytes_total=0),
        item(title="Комплексная автоматизация"),
    )

    table = format_plan(Passthrough(), current, source_count=1, elapsed=0.1)
    machine = json.loads(format_json(current, source_count=1, elapsed=0.1))

    assert "1 template(s)" in table
    assert "1 skipped" in table
    # В JSON ключи по исходу, а не по виду: write/skip/fail.
    assert machine["totals"]["write"] == 1
    assert machine["totals"]["skip"] == 1
    # Объём — только то, что поедет: пропущенный шаблон в него не входит.
    assert machine["totals"]["bytes"] == 1024
