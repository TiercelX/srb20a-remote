import os
import re
from pathlib import Path


def config_path():
    base = Path(os.environ['APPDATA']) if os.name == 'nt' and os.environ.get('APPDATA') else Path.home() / '.config'
    return base / 'srb20a-remote' / 'address.txt'


def get_address():
    value = os.environ.get('SRB20A_ADDRESS', '').strip()
    path = config_path()
    if not value and path.is_file():
        value = path.read_text(encoding='utf-8').strip()
    if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', value):
        raise ValueError('Set SRB20A_ADDRESS or configure the Bluetooth address in the app')
    return value.upper()


def save_address(value):
    if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', value.strip()):
        raise ValueError('Invalid Bluetooth address; expected 00:11:22:33:44:55')
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.strip().upper() + '\n', encoding='utf-8')
