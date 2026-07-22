#!/usr/bin/env python3
"""SIRIUS backend launcher — sets WS_UI=1 and runs main().

In frozen (PyInstaller onefile) mode, initializes %LOCALAPPDATA%/SIRIUS/
with default config files on first run, then sets SIRIUS_DATA_DIR.
Also initializes the persistence database on startup.
"""
import os
import sys
import shutil
import threading
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


def _migrate_from_roaming(data_dir: Path):
    """Copy existing data from old Roaming location to new Local location."""
    old_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "SIRIUS"
    if not old_dir.exists() or not old_dir.is_dir():
        return
    if data_dir.exists():
        return
    print(f"[LAUNCHER] Migrating existing data from {old_dir} to {data_dir}")
    try:
        shutil.copytree(old_dir, data_dir, dirs_exist_ok=True)
        print(f"[LAUNCHER] Migration complete")
    except Exception as e:
        print(f"[LAUNCHER] Warning: migration failed - {e}")


def _init_data_dir():
    """Set up persistent data directory (%LOCALAPPDATA%/SIRIUS) for configs and memory.

    On first run, copies default configs from the PyInstaller bundle (sys._MEIPASS)
    to the persistent location. Sets SIRIUS_DATA_DIR so config_loader.py picks it up.
    """
    localappdata = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    data_dir = localappdata / "SIRIUS"
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

    def _needs_populate(d: Path) -> bool:
        if not d.exists():
            return True
        return not any(d.iterdir())

    for subdir in ("config", "memory"):
        src = bundle_dir / subdir
        dst = data_dir / subdir
        if src.is_dir() and _needs_populate(dst):
            dst.mkdir(parents=True, exist_ok=True)
            for item in src.iterdir():
                if item.is_file() and not item.name.startswith("__"):
                    try:
                        shutil.copy2(item, dst / item.name)
                        print(f"[LAUNCHER] Created default {subdir}/{item.name}")
                    except PermissionError as e:
                        print(f"[LAUNCHER] Warning: could not copy {item.name} - {e}")
                    except Exception as e:
                        print(f"[LAUNCHER] Warning: error copying {item.name} - {e}")

    env_src = bundle_dir / ".env"
    env_dst = data_dir / ".env"
    if env_src.exists() and not env_dst.exists():
        try:
            shutil.copy2(env_src, env_dst)
            print(f"[LAUNCHER] Created default .env")
        except PermissionError as e:
            print(f"[LAUNCHER] Warning: could not copy .env - {e}. Creating empty .env instead.")
            env_dst.write_text("", encoding="utf-8")
        except Exception as e:
            print(f"[LAUNCHER] Warning: error copying .env - {e}")


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
        print(f"[LAUNCHER] Check that 'persistence' package and 'cryptography' are bundled in the build.")
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
