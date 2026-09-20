"""
Тесты записи по плану.

План — значение без потоков, поэтому источник открывается заново по
`item.origin`. Здесь проверяется, что открывается именно тот источник и что
на диск ложится ровно обещанное планом.
"""

import io
import os
import zipfile

import pytest

from efd_unpacker.application.executor import Writers
from efd_unpacker.application.inspector import inspect_all
from efd_unpacker.domain.errors import UnpackError, UnpackErrorCode
from efd_unpacker.domain.plan import PlanSettings, build_plan
from efd_unpacker.domain.unpack_service import UnpackService
from tests.efd_builder import build_efd


def _zip_bytes(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in files:
            archive.writestr(name, data)
    return buffer.getvalue()


def _supply(entries, name="Демо"):
    return build_efd(entries, supply_info=[("ru", name, "1С", "")])


#: Порядок и состав подобраны так, чтобы различать похожие ошибки:
#: .dt стоит НЕ последним — иначе пропуск без перемотки потока остался бы
#: незаметным; ReadMe.txt отличает правило «выбросить .dt» от правила
#: «оставить только .cf и манифест».
TWO_TEMPLATES = [
    ("1c/A/1_0/1cv8.mft", b"m"),
    ("1c/A/1_0/1cv8.dt", b"DATA-A-LONGER-THAN-THE-REST"),
    ("1c/A/1_0/1cv8.cf", b"CONFIG-A"),
    ("1c/A/1_0/ReadMe.txt", b"read me"),
    ("1c/B/2_0/1cv8.mft", b"m"),
    ("1c/B/2_0/1cv8.cf", b"CONFIG-B"),
]


def _plan_for(tmp_path, archive_bytes, name="src.zip", only_configuration=False):
    path = tmp_path / name
    path.write_bytes(archive_bytes)
    roots = PlanSettings(
        templates_root=str(tmp_path / "t"),
        distributions_root=str(tmp_path / "d"),
        only_configuration=only_configuration,
    )
    return build_plan(inspect_all([str(path)]), roots), roots


def _tree(root):
    return sorted(
        os.path.relpath(os.path.join(base, name), root).replace("\\", "/")
        for base, _dirs, files in os.walk(root) for name in files
    )


# --- поставки ----------------------------------------------------------------


def test_each_template_is_written_on_its_own(tmp_path):
    """
    Один .efd несёт несколько шаблонов, и каждый — отдельный элемент плана.

    Записывать при этом надо только свой: иначе два элемента дважды разложили
    бы один и тот же архив.
    """
    plan, roots = _plan_for(tmp_path, _zip_bytes([("1cv8.efd", _supply(TWO_TEMPLATES))]))
    writers = Writers(UnpackService(), roots.templates_root)

    writers.unpack_supply(plan.items[0])

    assert _tree(roots.templates_root) == [
        "1c/A/1_0/1cv8.cf", "1c/A/1_0/1cv8.dt", "1c/A/1_0/1cv8.mft", "1c/A/1_0/ReadMe.txt",
    ], "записан не только свой шаблон"


def test_only_configuration_drops_the_data_dump(tmp_path):
    """
    `--only cf` выбрасывает .dt и ничего больше.

    Правило одно на план и на исполнение: когда их было два, план обещал
    2.1 МБ, а записывалось 376 КБ.
    """
    plan, roots = _plan_for(
        tmp_path, _zip_bytes([("1cv8.efd", _supply(TWO_TEMPLATES))]), only_configuration=True
    )
    writers = Writers(UnpackService(), roots.templates_root, only_configuration=True)

    for planned in plan.to_write:
        writers.unpack_supply(planned)

    written = _tree(roots.templates_root)
    assert "1c/A/1_0/1cv8.dt" not in written
    # ReadMe остаётся: правило «выбросить выгрузку», а не «оставить только
    # конфигурацию». Без него 1С покажет неполный шаблон.
    assert "1c/A/1_0/ReadMe.txt" in written
    # Содержимое, а не только имя: пропуск записи без перемотки потока даёт
    # файл нужного размера, но с чужими байтами.
    assert (tmp_path / "t" / "1c" / "A" / "1_0" / "1cv8.cf").read_bytes() == b"CONFIG-A"


def test_promised_size_matches_what_lands_on_disk(tmp_path):
    """
    План обещает объём, исполнение обязано его сдержать.

    Расхождение здесь означает, что фильтры плана и исполнителя разошлись —
    именно так и случилось, пока правило было записано дважды.
    """
    plan, roots = _plan_for(
        tmp_path, _zip_bytes([("1cv8.efd", _supply(TWO_TEMPLATES))]), only_configuration=True
    )
    writers = Writers(UnpackService(), roots.templates_root, only_configuration=True)

    for planned in plan.to_write:
        writers.unpack_supply(planned)

    on_disk = sum(
        os.path.getsize(os.path.join(base, name))
        for base, _dirs, files in os.walk(roots.templates_root) for name in files
    )
    assert on_disk == plan.bytes_to_write


def test_missing_source_is_a_domain_error(tmp_path):
    """Файл исчез между осмотром и записью — отказ с кодом, а не исключение."""
    plan, roots = _plan_for(tmp_path, _zip_bytes([("1cv8.efd", _supply(TWO_TEMPLATES))]))
    os.remove(tmp_path / "src.zip")
    writers = Writers(UnpackService(), roots.templates_root)

    with pytest.raises(UnpackError) as caught:
        writers.unpack_supply(plan.items[0])

    assert caught.value.code is UnpackErrorCode.FILE_NOT_FOUND


# --- прочие файлы ------------------------------------------------------------


def test_distribution_files_keep_their_structure(tmp_path):
    plan, roots = _plan_for(tmp_path, _zip_bytes([
        ("setup-full-8.3.27.2342-x86_64.run", b"installer"),
        ("docs/readme.txt", b"hi"),
    ]))
    writers = Writers(UnpackService(), roots.templates_root)

    writers.extract_other(plan.items[0])

    assert _tree(roots.distributions_root) == [
        "platform/8.3.27.2342/full-x86_64/docs/readme.txt",
        "platform/8.3.27.2342/full-x86_64/setup-full-8.3.27.2342-x86_64.run",
    ]


def test_missing_entry_is_not_reported_as_success(tmp_path):
    """
    План обещал состав. Положить половину и промолчать нельзя.
    """
    plan, roots = _plan_for(tmp_path, _zip_bytes([
        ("setup-full-8.3.27.2342-x86_64.run", b"installer"),
        ("extra.bin", b"x"),
    ]))
    writers = Writers(UnpackService(), roots.templates_root)
    # Источник подменяется на тот, где одной записи нет.
    (tmp_path / "src.zip").write_bytes(
        _zip_bytes([("setup-full-8.3.27.2342-x86_64.run", b"installer")])
    )

    with pytest.raises(UnpackError) as caught:
        writers.extract_other(plan.items[0])

    assert caught.value.code is UnpackErrorCode.CORRUPTED_ARCHIVE


# --- прерывание --------------------------------------------------------------


def test_interrupted_run_leaves_written_files_whole(tmp_path):
    """
    Критерий #53: прерывание оставляет уже записанные файлы целыми.

    Атомарная запись из #7 работает и в батче: каждый файл появляется на месте
    целиком через os.replace, поэтому на диске нет ни одного обрезанного.
    """
    plan, roots = _plan_for(tmp_path, _zip_bytes([
        ("setup-full-8.3.27.2342-x86_64.run", b"a" * 5000),
        ("second.bin", b"b" * 5000),
        ("third.bin", b"c" * 5000),
    ]))
    calls = []

    writers = Writers(
        UnpackService(), roots.templates_root,
        cancel_check=lambda: calls.append(1) or len(calls) > 4,
    )

    with pytest.raises(UnpackError) as caught:
        writers.extract_other(plan.items[0])

    assert caught.value.code is UnpackErrorCode.CANCELLED
    for base, _dirs, files in os.walk(roots.distributions_root):
        for name in files:
            full = os.path.join(base, name)
            assert not name.startswith(".efd-"), "остался временный файл"
            assert os.path.getsize(full) == 5000, "файл записан наполовину"


def test_cancellation_leaves_no_partial_file(tmp_path):
    """Обрыв посреди файла не должен оставить обрезанный кусок на его месте."""
    plan, roots = _plan_for(tmp_path, _zip_bytes([
        ("setup-full-8.3.27.2342-x86_64.run", b"a" * 5000),
    ]))
    writers = Writers(UnpackService(), roots.templates_root, cancel_check=lambda: True)

    with pytest.raises(UnpackError):
        writers.extract_other(plan.items[0])

    assert _tree(roots.distributions_root) == []


def test_skipped_entry_does_not_shift_the_stream(tmp_path):
    """
    Пропущенную запись надо перешагнуть в потоке, а не просто не писать.

    Данные записей лежат подряд: без перемотки следующая читается со сдвигом
    и получает чужие байты при правильном размере — молчаливая порча.
    """
    plan, roots = _plan_for(
        tmp_path, _zip_bytes([("1cv8.efd", _supply(TWO_TEMPLATES))]), only_configuration=True
    )
    writers = Writers(UnpackService(), roots.templates_root, only_configuration=True)

    for planned in plan.to_write:
        writers.unpack_supply(planned)

    base = tmp_path / "t" / "1c" / "A" / "1_0"
    assert base.joinpath("1cv8.cf").read_bytes() == b"CONFIG-A"
    assert base.joinpath("ReadMe.txt").read_bytes() == b"read me"


@pytest.mark.skipif(
    os.name == "nt", reason="на Windows замена файла только для чтения запрещена и ядром"
)
def test_existing_read_only_file_is_replaced(tmp_path):
    """
    Запись идёт через os.replace, а не через копирование поверх.

    Наблюдаемая разница: файл только для чтения в доступном каталоге
    заменяется (право даёт каталог, а не файл), а копирование поверх такого
    файла отказало бы. Это не редкость — шаблоны 1С после установки часто
    лежат без права записи.
    """
    plan, roots = _plan_for(tmp_path, _zip_bytes([
        ("setup-full-8.3.27.2342-x86_64.run", "новая версия".encode("utf-8")),
    ]))
    target = os.path.join(
        roots.distributions_root, "platform", "8.3.27.2342", "full-x86_64",
        "setup-full-8.3.27.2342-x86_64.run",
    )
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as handle:
        handle.write("старая версия".encode("utf-8"))
    os.chmod(target, 0o444)

    Writers(UnpackService(), roots.templates_root).extract_other(plan.items[0])

    with open(target, "rb") as handle:
        assert handle.read() == "новая версия".encode("utf-8")
