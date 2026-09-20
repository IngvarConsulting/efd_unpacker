import os
import unittest
from unittest.mock import MagicMock, patch

import pytest

from PyQt5.QtCore import QSettings

from efd_unpacker.infrastructure import settings_service as settings_service_module
from efd_unpacker.infrastructure.settings_service import SETTINGS_VERSION, SettingsService


class DummyTranslator:
    def translate(self, _context: str, source: str) -> str:
        return f"tr:{source}"


class TestSettingsService(unittest.TestCase):
    def setUp(self) -> None:
        self.translator = DummyTranslator()

    @patch("efd_unpacker.infrastructure.settings_service.QSettings")
    @patch("efd_unpacker.infrastructure.settings_service.get_1c_configuration_location_default")
    def test_get_output_path_default(self, mock_default, mock_settings) -> None:
        mock_default.return_value = "/default/path"
        instance = MagicMock()
        instance.value.return_value = "/default/path"
        mock_settings.return_value = instance

        service = SettingsService(self.translator)
        result = service.get_output_path()

        self.assertEqual(result, "/default/path")
        instance.value.assert_called_once()

    @patch("efd_unpacker.infrastructure.settings_service.QSettings")
    def test_set_output_path(self, mock_settings) -> None:
        instance = MagicMock()
        mock_settings.return_value = instance
        service = SettingsService(self.translator)
        service.set_output_path("/new/path")
        # Вместе с путём пишется версия набора ключей: по ней следующее
        # изменение отличит настройки 2.0 от оставшихся с 1.x.
        instance.setValue.assert_any_call("output_path", "/new/path")
        instance.setValue.assert_any_call("settings_version", SETTINGS_VERSION)

    @patch("efd_unpacker.infrastructure.settings_service.get_1c_configuration_location_default")
    @patch("efd_unpacker.infrastructure.settings_service.get_1c_configuration_location_from_1cestart")
    @patch("efd_unpacker.infrastructure.settings_service.QSettings")
    def test_get_output_path_items(self, mock_settings, mock_from_1c, mock_default) -> None:
        instance = MagicMock()
        instance.value.return_value = "/last/path"
        mock_settings.return_value = instance
        mock_from_1c.return_value = ["/path/one"]
        mock_default.return_value = "/default/path"

        service = SettingsService(self.translator)
        items = service.get_output_path_items("/manual/path")

        by_origin = {choice.origin: choice for choice in items}
        self.assertEqual(by_origin["manual"].path, "/manual/path")
        self.assertEqual(by_origin["last_used"].path, "/last/path")
        self.assertEqual(by_origin["from_1cestart"].path, "/path/one")
        self.assertEqual(by_origin["default"].path, "/default/path")
        # Выбранному вручную пояснять нечего, у остальных происхождение видно.
        self.assertEqual(by_origin["manual"].label, "/manual/path")
        self.assertIn("tr:used last time", by_origin["last_used"].label)
        self.assertIn("tr:from 1cestart.cfg", by_origin["from_1cestart"].label)
        self.assertIn("tr:by default", by_origin["default"].label)


if __name__ == "__main__":
    unittest.main()


def test_non_string_setting_falls_back_to_default(tmp_path, monkeypatch):
    """
    Регресс #18: QSettings отдаёт то, что лежит в файле. Конфиг, правленный
    извне, даёт list, а os.path.normpath дальше роняет запуск ещё до
    window.show() — без окна и без сообщения.
    """
    ini = tmp_path / "settings.ini"
    ini.write_text("[General]\noutput_path=/home/u/Templates, old/tmplts\n", encoding="utf-8")
    settings = QSettings(str(ini), QSettings.IniFormat)
    assert not isinstance(settings.value("output_path"), str), "иначе тест проверяет не то"

    monkeypatch.setattr(
        settings_service_module, "get_1c_configuration_location_default", lambda: "/default/tmplts"
    )
    monkeypatch.setattr(
        settings_service_module, "get_1c_configuration_location_from_1cestart", lambda: []
    )
    service = SettingsService(translator=_DummyTranslator(), settings=settings)

    assert service.get_output_path() == "/default/tmplts"
    # Происхождение именно «по умолчанию»: сохранённого значения нет — оно
    # отвергнуто как не-строка, — и помечать откат как «использовался прошлый
    # раз» было бы враньём.
    items = service.get_output_path_items()
    assert [(choice.path, choice.origin) for choice in items] == [
        ("/default/tmplts", "default")
    ]


def test_string_setting_is_used_as_is(tmp_path, monkeypatch):
    ini = tmp_path / "settings.ini"
    ini.write_text("[General]\noutput_path=/home/u/Templates\n", encoding="utf-8")
    settings = QSettings(str(ini), QSettings.IniFormat)

    monkeypatch.setattr(
        settings_service_module, "get_1c_configuration_location_default", lambda: "/default/tmplts"
    )
    service = SettingsService(translator=_DummyTranslator(), settings=settings)

    assert service.get_output_path() == "/home/u/Templates"


class _DummyTranslator:
    def translate(self, _context, source):
        return source


# --- два каталога ------------------------------------------------------------


def _service(tmp_path, monkeypatch, contents="[General]\n", default="/default/tmplts"):
    ini = tmp_path / "settings.ini"
    ini.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(
        settings_service_module, "get_1c_configuration_location_default", lambda: default
    )
    monkeypatch.setattr(
        settings_service_module, "get_1c_configuration_location_from_1cestart", lambda: []
    )
    return SettingsService(
        translator=_DummyTranslator(), settings=QSettings(str(ini), QSettings.IniFormat)
    )


def test_distributions_follow_the_templates_root(tmp_path, monkeypatch):
    """
    Критерий #55: сменили каталог шаблонов — dist поехал следом.

    Значение вычисляемое, а не скопированное однажды: записанное при первой
    настройке, оно так и указывало бы на прежнего соседа.
    """
    service = _service(tmp_path, monkeypatch)

    service.set_output_path("/srv/1c/tmplts")
    assert service.get_distributions_path() == os.path.normpath("/srv/1c/dist")

    service.set_output_path("/mnt/other/tmplts")
    assert service.get_distributions_path() == os.path.normpath("/mnt/other/dist")


def test_explicit_distributions_root_stops_following(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    service.set_output_path("/srv/1c/tmplts")
    service.set_distributions_path("/data/дистрибутивы")

    service.set_output_path("/mnt/other/tmplts")

    assert service.get_distributions_path() == "/data/дистрибутивы"
    assert service.distributions_path_is_explicit() is True


def test_clearing_the_explicit_root_returns_to_following(tmp_path, monkeypatch):
    """
    Отсутствие ключа значит «не настроено», а не выдуманный каталог.

    Иначе от своего выбора нельзя было бы отказаться — только сменить его на
    другой такой же.
    """
    service = _service(tmp_path, monkeypatch)
    service.set_output_path("/srv/1c/tmplts")
    service.set_distributions_path("/data/дистрибутивы")

    service.set_distributions_path("")

    assert service.distributions_path_is_explicit() is False
    assert service.get_distributions_path() == os.path.normpath("/srv/1c/dist")


@pytest.mark.parametrize(
    "templates_root, expected",
    [
        # Ожидания через normpath: путь возвращается каноническим.
        ("/tmplts", os.path.normpath("/dist")),
        (os.path.join(os.sep, "srv", "шаблоны"), os.path.join(os.sep, "srv", "dist")),
        (os.sep, os.path.join(os.sep, "dist")),
    ],
)
def test_unusual_templates_roots_do_not_break_the_computation(
    tmp_path, monkeypatch, templates_root, expected
):
    """Критерий #55: корень и каталог с другим именем не роняют приложение."""
    service = _service(tmp_path, monkeypatch)
    service.set_output_path(templates_root)

    assert service.get_distributions_path() == expected


def test_non_string_distributions_setting_falls_back_to_the_computed_one(tmp_path, monkeypatch):
    """
    Критерий #55: защита из #18 распространяется на новый ключ.

    Правленный извне конфиг даёт list, и os.path.normpath дальше роняет запуск
    до появления окна.
    """
    service = _service(
        tmp_path, monkeypatch,
        contents="[General]\noutput_path=/srv/1c/tmplts\ndist_path=/a/one, /a/two\n",
    )
    assert not isinstance(service.settings.value("dist_path"), str), "иначе тест проверяет не то"

    assert service.get_distributions_path() == os.path.normpath("/srv/1c/dist")
    assert service.distributions_path_is_explicit() is False


def test_settings_from_1x_are_read_without_losing_the_output_path(tmp_path, monkeypatch):
    """
    Критерий #55: настройки 1.x читаются без потери output_path.

    В 1.x ключа версии не было вовсе, и переносить нечего — в 2.0 только
    добавились ключи. Проверяем, что это действительно так, а не на словах.
    """
    service = _service(
        tmp_path, monkeypatch, contents="[General]\noutput_path=/Volumes/Share/tmplts\n"
    )

    assert service.settings.value("settings_version") is None, "иначе это не настройки 1.x"
    assert service.get_output_path() == "/Volumes/Share/tmplts"
    assert service.get_distributions_path() == os.path.normpath("/Volumes/Share/dist")


def test_fresh_profile_does_not_claim_a_path_was_used_before(tmp_path, monkeypatch):
    """
    На чистом профиле единственный вариант — «по умолчанию».

    get_output_path отдаёт вычисленное умолчание и когда ничего не сохранено;
    пометить его как «использовался прошлый раз» значит соврать, а запись про
    умолчание при этом пропадала как дубль.
    """
    service = _service(tmp_path, monkeypatch)

    items = service.get_output_path_items()

    assert [(choice.path, choice.origin) for choice in items] == [
        ("/default/tmplts", "default")
    ]
    assert service.output_path_is_stored() is False


def test_saved_path_becomes_the_last_used_one(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    service.set_output_path("/Volumes/Share/tmplts")

    items = service.get_output_path_items()

    assert [(choice.path, choice.origin) for choice in items] == [
        ("/Volumes/Share/tmplts", "last_used"),
        ("/default/tmplts", "default"),
    ]
