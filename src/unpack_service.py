import onec_dtools
from tr import tr
from typing import Tuple

class UnpackService:
    @staticmethod
    def unpack(input_file: str, output_dir: str) -> Tuple[bool, str]:
        try:
            with open(input_file, 'rb') as f:
                supply_reader = onec_dtools.SupplyReader(f)
                supply_reader.unpack(output_dir)
            return True, tr('UnpackService', 'Unpacking completed successfully')
        except FileNotFoundError:
            return False, tr('UnpackService', 'File not found')
        except PermissionError:
            return False, tr('UnpackService', 'Permission error')
        except Exception as e:
            return False, tr('UnpackService', 'Unexpected error: %1').replace('%1', str(e))
