"""
Plugin discovery, validation, collision detection, and dispatch.

Discovery runs once (JarvisLive.__init__ calls discover_plugins()); the resulting
PluginRegistry is cached for the process lifetime. Enable/disable state is re-read
from config on every call to get_tool_declarations() / run() / list_for_ui(), so
toggling a plugin does not require restarting the app or re-importing anything.
"""
from __future__ import annotations

import importlib
import inspect
import re
import sys
import time
import traceback
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from memory.config_manager import get_plugin_enabled

_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
_DEFAULT_PARAMS = {"type": "OBJECT", "properties": {}}


@dataclass
class PluginRecord:
    name: str
    description: str = ""
    parameters: dict = field(default_factory=lambda: dict(_DEFAULT_PARAMS))
    run: Optional[Callable] = None
    file: str = ""
    valid: bool = False
    error: str = ""


class PluginRegistry:
    def __init__(self, plugins: dict[str, PluginRecord], logger: Callable[[str], None]):
        self._plugins = plugins          # name -> PluginRecord, VALID entries only
        self._all_records: list[PluginRecord] = []   # valid + invalid, for UI listing
        self._logger = logger

    # -- called by main.py at LiveConnectConfig build time --
    def get_tool_declarations(self) -> list[dict]:
        decls = []
        for name, rec in self._plugins.items():
            if get_plugin_enabled(name):
                decls.append({
                    "name": rec.name,
                    "description": rec.description,
                    "parameters": rec.parameters,
                })
        return decls

    def has(self, name: str) -> bool:
        return name in self._plugins

    # -- called by main.py from _execute_tool's else branch --
    def run(self, name: str, parameters: dict, player=None, session_memory=None) -> str:
        rec = self._plugins.get(name)
        if rec is None or not rec.valid:
            return f"Plugin '{name}' is not available."
        if not get_plugin_enabled(name):
            return f"The '{name}' plugin is currently disabled."
        try:
            return _call_run(rec.run, parameters, player, session_memory) or "Done."
        except Exception as e:
            self._logger(f"Plugin '{name}' crashed during run(): {e}")
            traceback.print_exc()
            return f"Sir, the '{name}' plugin failed: {e}"

    # -- called by ui.py's Plugin Manager overlay --
    def list_for_ui(self) -> list[dict]:
        out = []
        for rec in self._all_records:
            out.append({
                "name": rec.name,
                "description": rec.description,
                "file": rec.file,
                "valid": rec.valid,
                "error": rec.error,
                "enabled": get_plugin_enabled(rec.name) if rec.valid else False,
            })
        return out


def _call_run(run_fn, parameters, player, session_memory):
    """Invoke run() passing only the kwargs it actually declares (or all of them
    if it has **kwargs), so a minimal `def run(parameters):` plugin still works."""
    sig = inspect.signature(run_fn)
    has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    kwargs = {}
    if has_var_kw or "player" in sig.parameters:
        kwargs["player"] = player
    if has_var_kw or "session_memory" in sig.parameters:
        kwargs["session_memory"] = session_memory
    return run_fn(parameters, **kwargs)


def _read_source(path: Path, attempts: int = 6, delay: float = 0.15) -> bytes:
    """Read file bytes with retry. Freshly extracted PyInstaller onefile
    files (_MEIPASS) can be transiently locked by antivirus/bootloader
    handles (Errno 13) right after startup — retrying wins that race."""
    last_exc: Exception = PermissionError(str(path))
    for i in range(attempts):
        try:
            return path.read_bytes()
        except PermissionError as e:      # noqa: PERF203 — retry loop
            last_exc = e
            time.sleep(delay * (i + 1))
    raise last_exc


def _load_module_from_source(module_name: str, path: Path):
    """
    Load a module from a .py file WITHOUT importlib's SourceFileLoader.
    The stock loader opens the file itself and writes a __pycache__ .pyc
    next to it; inside the PyInstaller onefile extraction dir (_MEIxxxxx)
    that write/open fails with PermissionError. Compiling from bytes we
    read ourselves avoids both problems (manual compile never writes cache).
    """
    src  = _read_source(path)
    code = compile(src, str(path), "exec")
    module = types.ModuleType(module_name)
    module.__file__ = str(path)
    module.__package__ = module_name.rpartition(".")[0]
    sys.modules[module_name] = module
    try:
        exec(code, module.__dict__)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _validate(module, filename: str) -> PluginRecord:
    """Returns a PluginRecord; .valid=False + .error set on any problem. Never raises."""
    plugin_meta = getattr(module, "PLUGIN", None)
    if not isinstance(plugin_meta, dict):
        return PluginRecord(name=Path(filename).stem, file=filename,
                             error="Missing PLUGIN dict constant.")

    name = plugin_meta.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        return PluginRecord(name=str(name or Path(filename).stem), file=filename,
                             error="PLUGIN['name'] missing or not a valid identifier "
                                   "(letters/digits/underscore, must start with letter/underscore).")

    description = plugin_meta.get("description")
    if not isinstance(description, str) or not description.strip():
        return PluginRecord(name=name, file=filename,
                             error="PLUGIN['description'] missing or empty.")

    parameters = plugin_meta.get("parameters", _DEFAULT_PARAMS)
    if not isinstance(parameters, dict) or parameters.get("type") != "OBJECT":
        return PluginRecord(name=name, file=filename,
                             error="PLUGIN['parameters'] must be a dict with \"type\": \"OBJECT\".")

    run_fn = getattr(module, "run", None)
    if not callable(run_fn):
        return PluginRecord(name=name, file=filename,
                             error="Missing callable run(parameters, ...) function.")

    return PluginRecord(name=name, description=description.strip(), parameters=parameters,
                         run=run_fn, file=filename, valid=True, error="")


def discover_plugins(plugins_dir: Path, core_tool_names: set[str],
                       logger: Callable[[str], None] = print,
                       bundled_module_names: Optional[list[str]] = None) -> PluginRegistry:
    """
    Scans plugins_dir for *.py files (skips files starting with '_', e.g. __init__.py,
    _template.py, and any shared-helper modules an author prefixes with '_').
    Import errors, validation errors, and name collisions are logged and the offending
    file is skipped — they NEVER raise out of this function and never abort the scan
    of remaining files.
    After the filesystem scan, any names in `bundled_module_names` that weren't loaded
    from the filesystem are attempted via importlib (for frozen mode where plugins
    are bundled in the PYZ instead of shipped as loose .py files).
    """
    plugins_dir.mkdir(parents=True, exist_ok=True)
    valid: dict[str, PluginRecord] = {}
    all_records: list[PluginRecord] = []
    seen_names: set[str] = set()  # names loaded from filesystem

    files = sorted(plugins_dir.glob("*.py"), key=lambda p: p.name)  # deterministic order
    for path in files:
        if path.name.startswith("_"):
            continue
        try:
            module_name = f"plugins.{path.stem}"
            module = _load_module_from_source(module_name, path)

            rec = _validate(module, path.name)

            if rec.valid and rec.name in core_tool_names:
                rec = PluginRecord(name=rec.name, file=path.name,
                                    error=f"Name '{rec.name}' collides with a core tool — rejected.")
            elif rec.valid and rec.name in valid:
                other = valid[rec.name].file
                rec = PluginRecord(name=rec.name, file=path.name,
                                    error=f"Name '{rec.name}' already used by plugin '{other}' — rejected.")

        except Exception as e:
            rec = PluginRecord(name=path.stem, file=path.name,
                                error=f"Failed to load: {e}")
            traceback.print_exc()

        all_records.append(rec)
        if rec.valid:
            valid[rec.name] = rec
            seen_names.add(rec.name)
            logger(f"Plugin loaded: {rec.name} ({path.name})")
        else:
            logger(f"Plugin rejected: {path.name} — {rec.error}")

    # Load bundled modules that weren't provided by the filesystem
    if bundled_module_names:
        for name in bundled_module_names:
            if name in seen_names:
                logger(f"Plugin '{name}' already provided by file, skipping bundled import")
                continue
            try:
                module = importlib.import_module(f"plugins.{name}")
                rec = _validate(module, f"plugins/{name}.py (bundled)")
                if rec.valid and rec.name in core_tool_names:
                    rec = PluginRecord(name=rec.name, file=f"{name}.py (bundled)",
                                        error=f"Name '{rec.name}' collides with a core tool — rejected.")
                elif rec.valid and rec.name in valid:
                    other = valid[rec.name].file
                    rec = PluginRecord(name=rec.name, file=f"{name}.py (bundled)",
                                        error=f"Name '{rec.name}' already used by plugin '{other}' — rejected.")
            except Exception as e:
                rec = PluginRecord(name=name, file=f"{name}.py (bundled)",
                                    error=f"Failed to import bundled plugin: {e}")
                traceback.print_exc()

            all_records.append(rec)
            if rec.valid:
                valid[rec.name] = rec
                logger(f"Plugin loaded (bundled): {rec.name}")
            else:
                logger(f"Plugin rejected (bundled): {name} — {rec.error}")

    registry = PluginRegistry(valid, logger)
    registry._all_records = all_records
    logger(f"Plugin discovery complete: {len(valid)} active, "
           f"{len(all_records) - len(valid)} rejected, {len(all_records)} total.")
    return registry
