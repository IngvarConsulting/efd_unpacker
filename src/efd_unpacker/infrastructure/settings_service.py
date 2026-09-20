"""
Хранение путей между запусками.

Два каталога: шаблоны, путь к которым диктует 1С, и дистрибутивы, путь к
которым выбираем мы. Второй по умолчанию не задан вовсе — он ВЫЧИСЛЯЕТСЯ от
первого при каждом чтении. Поэтому смена каталога шаблонов уводит за собой и
дистрибутивы, а скопированное однажды значение так бы и осталось указывать на
старое место.
"""

import os
from dataclasses import dataclass
from typing import List, Optional

from PyQt5.QtCore import QSettings

from ..localization.translator import Translator
from .os_utils import (
    get_1c_configuration_location_default,
    get_1c_configuration_location_from_1cestart,
    get_distributions_location_default,
)

OUTPUT_KEY = "output_path"
DIST_KEY = "dist_path"
VERSION_KEY = "settings_version"

#: Версия набора ключей. 1.x версии не знала вовсе; в 2.0 добавились dist_path
#: и этот ключ, а старые значения читаются как есть — переносить нечего.
#: Номер нужен следующему изменению, которое захочет отличить одно от другого.
SETTINGS_VERSION = 2

#: Коды происхождения пути. Стабильные: по ним окно решает, что показать, и
#: они не должны меняться вслед за языком интерфейса.
ORIGIN_MANUAL = "manual"
ORIGIN_LAST_USED = "last_used"
ORIGIN_FROM_1CESTART = "from_1cestart"
ORIGIN_DEFAULT = "default"

ORIGIN_KEYS = {
    ORIGIN_LAST_USED: "used last time",
    ORIGIN_FROM_1CESTART: "from 1cestart.cfg",
    ORIGIN_DEFAULT: "by default",
}


@dataclass(frozen=True)
class PathChoice:
    """
    Вариант каталога вместе с тем, откуда он взялся.

    Происхождение показывается человеку: выбирая между тремя похожими путями,
    он ориентируется не на их вид, а на то, откуда каждый появился.
    """

    path: str
    origin: str
    label: str


class SettingsService:
    """Инфраструктурный сервис хранения путей."""

    def __init__(self, translator: Translator, settings: Optional[QSettings] = None) -> None:
        self.translator = translator
        self.settings = settings or QSettings("efd_unpacker", "settings")

    # --- каталог шаблонов ----------------------------------------------------

    def get_output_path(self) -> str:
        return self._stored(OUTPUT_KEY) or get_1c_configuration_location_default()

    def output_path_is_stored(self) -> bool:
        """Выбирал ли пользователь каталог шаблонов хоть раз."""
        return self._stored(OUTPUT_KEY) is not None

    def set_output_path(self, path: str) -> None:
        self.settings.setValue(OUTPUT_KEY, path)
        self.settings.setValue(VERSION_KEY, SETTINGS_VERSION)

    # --- каталог дистрибутивов ----------------------------------------------

    def get_distributions_path(self) -> str:
        """
        Заданный явно либо вычисленный от каталога шаблонов.

        Вычисление при каждом чтении, а не однократная запись: иначе смена
        каталога шаблонов оставила бы дистрибутивы у прежнего соседа.
        """
        return self._stored(DIST_KEY) or get_distributions_location_default(
            self.get_output_path()
        )

    def set_distributions_path(self, path: Optional[str]) -> None:
        """
        Пустое значение возвращает каталог к вычисляемому.

        Отсутствие ключа значит «не настроено», а не выдуманный каталог: так
        пользователь может отказаться от своего выбора, а не только сменить его.
        """
        if path:
            self.settings.setValue(DIST_KEY, path)
        else:
            self.settings.remove(DIST_KEY)
        self.settings.setValue(VERSION_KEY, SETTINGS_VERSION)

    def distributions_path_is_explicit(self) -> bool:
        """Задан ли каталог дистрибутивов вручную. Окну нужно для подписи."""
        return self._stored(DIST_KEY) is not None

    # --- варианты для выбора -------------------------------------------------

    def get_output_path_items(self, manual_selected_path: Optional[str] = None) -> List[PathChoice]:
        """
        Варианты каталога шаблонов в порядке убывания уместности.

        Порядок тот же, что был в 1.x: выбранный руками, использованный
        прошлый раз, прочитанные из 1cestart.cfg, вычисленный по умолчанию.
        Новое здесь только одно — у каждого варианта видно происхождение.
        """
        last_used = self.get_output_path()
        choices: List[PathChoice] = []
        seen = set()

        def add(path: str, origin: str) -> None:
            if not path:
                return
            key = os.path.normpath(path)
            if key in seen:
                return
            seen.add(key)
            choices.append(PathChoice(path=path, origin=origin, label=self._label(path, origin)))

        if manual_selected_path and (
            os.path.normpath(manual_selected_path) != os.path.normpath(last_used)
        ):
            add(manual_selected_path, ORIGIN_MANUAL)
        if self.output_path_is_stored():
            # Только когда путь действительно сохранён. На чистом профиле
            # get_output_path отдаёт вычисленное умолчание, и помечать его как
            # «использовался прошлый раз» — враньё: им ещё ни разу не
            # пользовались, а запись про умолчание пропадала как дубль.
            add(last_used, ORIGIN_LAST_USED)
        for path in get_1c_configuration_location_from_1cestart():
            add(path, ORIGIN_FROM_1CESTART)
        add(get_1c_configuration_location_default(), ORIGIN_DEFAULT)

        return choices

    def _label(self, path: str, origin: str) -> str:
        """Путь и происхождение. У выбранного вручную пояснять нечего."""
        key = ORIGIN_KEYS.get(origin)
        if key is None:
            return path
        return "%s — %s" % (path, self.translator.translate("SettingsService", key))

    # --- чтение ---------------------------------------------------------------

    def _stored(self, key: str) -> Optional[str]:
        """
        Сохранённое значение ключа, если это непустая строка, иначе None.

        QSettings отдаёт то, что лежит в файле: конфиг, правленный извне,
        миграция или REG_MULTI_SZ дают list, а os.path.normpath дальше роняет
        запуск ещё до window.show() — без окна и без сообщения.
        ','.join тут нельзя: Qt при разборе срезает пробел после запятой,
        и склейка даст молча неверный каталог вместо честного отката.

        None, а не умолчание: вызывающему нужно отличать «не настроено» от
        «настроено ровно так же, как по умолчанию».
        """
        value = self.settings.value(key, None)
        if not isinstance(value, str) or not value:
            return None
        return value
