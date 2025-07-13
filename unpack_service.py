import onec_dtools
from localization import loc

class UnpackService:
    @staticmethod
    def unpack(input_file: str, output_dir: str) -> tuple[bool, str]:
        try:
            with open(input_file, 'rb') as f:
                supply_reader = onec_dtools.SupplyReader(f)
                supply_reader.unpack(output_dir)
            return True, loc.get('unpack_success')
        except FileNotFoundError:
            return False, loc.get('file_not_found_error')
        except PermissionError:
            return False, loc.get('permission_error')
        except Exception as e:
            return False, loc.get('unexpected_error', error=str(e)) 