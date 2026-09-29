#!/usr/bin/env python3
"""SIRIUS backend launcher — sets WS_UI=1 and runs main().

In frozen (PyInstaller onefile) mode, initializes %LOCALAPPDATA%/SIRIUS/
with default config files on first run, then sets SIRIUS_DATA_DIR.
Also initializes the persistence database on startup.
"""
import os
import shutil
import sys
from pathlib import Path

# ── Nuclear: force CREATE_NO_WINDOW on EVERY subprocess call on Windows ───────
if sys.platform == "win32":
    import subprocess as _subprocess
    _orig_popen = _subprocess.Popen
    class _Popen(_orig_popen):
        def __init__(self, *args, **kwargs):
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | 0x08000000
            kwargs.pop("startupinfo", None)
            super().__init__(*args, **kwargs)
    _subprocess.Popen = _Popen

# -- Same AppUserModelID as Tauri so Windows groups both processes in Task Manager --
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "com.rafaelildefonso.sirius"
        )
    except Exception:
        pass

# Fix Windows console encoding for Unicode output (browser automation, etc.)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


def _migrate_from_roaming(data_dir: Path):
    """Copy existing data from old Roaming location to new Local location."""
    old_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "SIRIUS"
    if old_dir == data_dir:
        return
    try:
        old_data_exists = old_dir.is_dir()
    except OSError as e:
        print(f"[LAUNCHER] Warning: cannot access legacy data at {old_dir} - {e}")
        return
    if not old_data_exists:
        return
    try:
        target_exists = data_dir.exists()
    except OSError as e:
        print(f"[LAUNCHER] Warning: cannot inspect data directory {data_dir} - {e}")
        return
    if target_exists:
        return
    print(f"[LAUNCHER] Migrating existing data from {old_dir} to {data_dir}")
    try:
        shutil.copytree(old_dir, data_dir, dirs_exist_ok=True)
        print("[LAUNCHER] Migration complete")
    except Exception as e:
        print(f"[LAUNCHER] Warning: migration failed - {e}")


def _usable_data_directory(path: Path) -> bool:
    """Return whether *path* can be created and listed by this user.

    Some Windows installations retain an old %LOCALAPPDATA%\\SIRIUS directory
    with an ACL owned by another account or a previous elevated install.  Merely
    calling ``Path.exists`` on such a directory raises PermissionError and used
    to prevent the backend from ever starting.
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
        with os.scandir(path):
            pass
        return True
    except OSError as e:
        print(f"[LAUNCHER] Data directory unavailable: {path} - {e}")
        return False


def _select_data_dir() -> Path:
    """Choose a persistent writable data directory without requiring elevation."""
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "SIRIUS"
    if _usable_data_directory(local):
        return local

    roaming = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "SIRIUS"
    if _usable_data_directory(roaming):
        print(f"[LAUNCHER] Using fallback data directory: {roaming}")
        return roaming

    home_fallback = Path.home() / ".sirius"
    if _usable_data_directory(home_fallback):
        print(f"[LAUNCHER] Using final fallback data directory: {home_fallback}")
        return home_fallback

    raise RuntimeError("No writable SIRIUS data directory is available.")


def _init_data_dir():
    """Set up persistent data directory (%LOCALAPPDATA%/SIRIUS) for configs and memory.

    On first run, copies sanitized defaults from the PyInstaller bundle
    (assets/defaults) to the persistent location. User data is never replaced.
    Sets SIRIUS_DATA_DIR so config_loader.py picks it up.
    """
    data_dir = _select_data_dir()
    os.environ["SIRIUS_DATA_DIR"] = str(data_dir)
    print(f"[LAUNCHER] SIRIUS_DATA_DIR={data_dir}")

    if not getattr(sys, "frozen", False):
        print(f"[LAUNCHER] Dev mode — using existing files at {data_dir}")
        return

    _migrate_from_roaming(data_dir)

    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir is None:
        return
    bundle_dir = Path(bundle_dir)

    defaults_root = bundle_dir / "assets" / "defaults"
    for subdir in ("config", "memory"):
        src = defaults_root / subdir
        dst = data_dir / subdir
        if not src.is_dir():
            continue
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            if not item.is_file() or item.name.startswith("__"):
                continue
            target = dst / item.name
            # Never overwrite configuration, credentials or memory created by
            # an earlier installation or by the user.
            if target.exists():
                continue
            try:
                shutil.copy2(item, target)
                print(f"[LAUNCHER] Created default {subdir}/{item.name}")
            except PermissionError as e:
                print(f"[LAUNCHER] Warning: could not copy {item.name} - {e}")
            except OSError as e:
                print(f"[LAUNCHER] Warning: error copying {item.name} - {e}")


def _init_database():
    """Initialize the persistence database on startup (dev / frozen)."""
    try:
        from persistence.database import Database
        Database.get_instance()
        db_path = Database.get_instance().db_path
        db_exists = db_path.exists()
        print(f"[LAUNCHER] Database initialized at {db_path} (exists={db_exists})")
    except ImportError as e:
        print(f"[LAUNCHER] Database init FAILED — missing import: {e}")
        print("[LAUNCHER] Check that 'persistence' package and 'cryptography' are bundled in the build.")
    except Exception as e:
        print(f"[LAUNCHER] Warning: database initialization deferred - {e}")


def _sync_json_to_db():
    """Import any existing JSON memory into the DB on startup."""
    try:
        from memory.memory_manager import sync_json_to_db
        count = sync_json_to_db()
        if count:
            print(f"[LAUNCHER] Synced {count} memory entries from JSON to DB")
    except Exception as e:
        print(f"[LAUNCHER] Warning: JSON sync deferred - {e}")


_init_data_dir()
_init_database()
_sync_json_to_db()

os.environ["SIRIUS_WS_UI"] = "1"

_this_dir = Path(__file__).resolve().parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from main import main

main()
