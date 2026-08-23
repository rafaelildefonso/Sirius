# config/__init__.py
from core.config_loader import get_os as _get_os
from core.config_loader import is_linux as _is_linux
from core.config_loader import is_mac as _is_mac
from core.config_loader import is_windows as _is_windows


def get_config() -> dict:
    from core.config_loader import get_all_config
    return get_all_config()


def get_os() -> str:
    return _get_os()

def is_windows() -> bool: return _is_windows()
def is_mac()     -> bool: return _is_mac()
def is_linux()   -> bool: return _is_linux()
