from PyQt5.QtCore import QSettings
from tr import tr
from os_utils import get_1c_configuration_location_default, get_1c_configuration_location_from_1cestart
import os
from typing import List, Tuple, Optional

class SettingsService:
    def __init__(self) -> None:
        self.settings = QSettings('efd_unpacker', 'settings')

    def get_output_path(self) -> str:
        return self.settings.value('output_path', get_1c_configuration_location_default())

    def set_output_path(self, path: str) -> None:
        self.settings.setValue('output_path', path)

    def get_output_path_items(self, manual_selected_path: Optional[str] = None) -> List[Tuple[str, str]]:
        """
        Возвращает список (path, label) для комбобокса, учитывая manual_selected_path, last_used, from_1cestart, default_path и локализацию.
        """
        last_used = self.get_output_path()
        from_1cestart = get_1c_configuration_location_from_1cestart()
        default_path = get_1c_configuration_location_default()
        seen = set()
        items = []
        # 1. Вручную выбранный путь (если есть и не совпадает с последним использованным)
        if manual_selected_path and os.path.normpath(manual_selected_path) != os.path.normpath(last_used):
            label = f"{manual_selected_path}"
            items.append((manual_selected_path, label))
            seen.add(os.path.normpath(manual_selected_path))
        # 2. Последний использованный
        if last_used:
            label = f"{last_used} {tr('SettingsService', '(last used)')}"
            if os.path.normpath(last_used) not in seen:
                items.append((last_used, label))
                seen.add(os.path.normpath(last_used))
        # 3. Пути из 1cestart
        for path in from_1cestart:
            norm = os.path.normpath(path)
            if norm not in seen:
                items.append((path, path))
                seen.add(norm)
        # 4. По умолчанию
        norm_default = os.path.normpath(default_path)
        if norm_default not in seen:
            items.append((default_path, f"{default_path} {tr('SettingsService', '(default)')}"))
            seen.add(norm_default)
        return items 