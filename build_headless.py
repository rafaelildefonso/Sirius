"""Build the Pane-integrated headless backend with safe incremental caching.

Usage:
    python build_headless.py --cached
    python build_headless.py --force
    python build_headless.py --clean --force

Output:
    dist/sirius-headless/sirius-headless.exe
"""

from __future__ import annotations

import hashlib
import importlib.metadata as importlib_metadata
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable


HERE = Path(__file__).resolve().parent
DIST = HERE / "dist"
BUILD = HERE / "build"
WORKPATH = BUILD / "sirius-headless"
SPEC_PATH = BUILD / "sirius-headless.spec"
OUTPUT = DIST / "sirius-headless"
STATE_FILE = HERE / ".headless_build_state.json"
CACHE_SCHEMA = 1
SOURCE_DIRS = ("actions", "agent", "core", "config", "memory", "orchestrator", "persistence")


def _parse_args() -> tuple[bool, bool, bool, str]:
    """Parse the headless build contract."""
    allowed = {"--cached", "--force", "--clean"}
    unknown = [arg for arg in sys.argv[1:] if not arg.startswith("--profile=") and arg not in allowed]
    if unknown:
        raise SystemExit(f"Unknown build argument(s): {', '.join(unknown)}")

    profile = "dev"
    for arg in sys.argv[1:]:
        if arg.startswith("--profile="):
            profile = arg.split("=", 1)[1].strip().lower()
    if profile not in {"dev", "release"}:
        raise SystemExit("--profile must be 'dev' or 'release'")

    # Cached behavior is the default. --force keeps the incremental workpath
    # but always produces a fresh executable.
    return (
        "--cached" in sys.argv or "--force" not in sys.argv,
        "--force" in sys.argv,
        "--clean" in sys.argv,
        profile,
    )


def _check_pyinstaller() -> bool:
    """Return whether PyInstaller is available in the selected environment."""
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        return False
    return True


def _iter_files(paths: Iterable[Path], suffixes: set[str] | None = None) -> Iterable[Path]:
    """Yield source and public asset files while ignoring runtime state."""
    excluded_names = {".env", ".db_key"}
    excluded_suffixes = {".db", ".key", ".crt", ".pyc", ".pyo"}
    for root in paths:
        if root.is_file():
            candidates = [root]
        elif root.is_dir():
            candidates = root.rglob("*")
        else:
            continue
        for candidate in candidates:
            if not candidate.is_file():
                continue
            if any(part in {"__pycache__", ".git", "target", "node_modules"} for part in candidate.parts):
                continue
            if candidate.name in excluded_names or candidate.suffix.lower() in excluded_suffixes:
                continue
            if suffixes is not None and candidate.suffix.lower() not in suffixes:
                continue
            yield candidate


def _environment() -> dict[str, str]:
    """Capture toolchain values that affect PyInstaller output."""
    try:
        pyinstaller_version = importlib_metadata.version("pyinstaller")
    except importlib_metadata.PackageNotFoundError:
        pyinstaller_version = "<missing>"
    return {
        "python": platform.python_version(),
        "python_executable": str(Path(sys.executable).resolve()),
        "platform": platform.platform(),
        "pyinstaller": pyinstaller_version,
    }


def _fingerprint(profile: str) -> tuple[str, dict[str, str]]:
    """Hash headless source, public assets, dependencies and build profile."""
    hasher = hashlib.sha256()
    environment = _environment()
    hasher.update(f"cache-schema:{CACHE_SCHEMA}\n".encode("utf-8"))
    hasher.update(json.dumps({"profile": profile, **environment}, sort_keys=True).encode("utf-8"))

    source_roots = [HERE / directory for directory in SOURCE_DIRS]
    public_roots = [HERE / "assets"]
    tracked_files = list(_iter_files([HERE / "main_headless.py", HERE / "build_headless.py"], suffixes={".py"}))
    tracked_files.extend(_iter_files(source_roots, suffixes={".py"}))
    tracked_files.extend(_iter_files(public_roots))
    tracked_files.extend(_iter_files([HERE / "requirements.txt", HERE / "requirements.lock"]))
    for path in sorted(set(tracked_files)):
        hasher.update(str(path.relative_to(HERE)).encode("utf-8"))
        with path.open("rb") as file:
            while chunk := file.read(8192):
                hasher.update(chunk)
    return hasher.hexdigest(), environment


def _read_state() -> dict[str, object]:
    """Read prior headless build metadata."""
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}


def _remove(path: Path) -> None:
    """Remove one exact generated path."""
    if not path.exists():
        return
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    except OSError as exc:
        raise SystemExit(f"[BUILD] Could not remove {path}: {exc}") from exc


def _write_state(fingerprint: str, environment: dict[str, str], profile: str) -> None:
    """Persist state only after a verified executable exists."""
    STATE_FILE.write_text(
        json.dumps(
            {
                "schema": CACHE_SCHEMA,
                "fingerprint": fingerprint,
                "environment": environment,
                "profile": profile,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _build_command(profile: str) -> list[str]:
    """Return the PyInstaller command without collecting user data."""
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--console",
        "--name",
        "sirius-headless",
        "--distpath",
        str(DIST),
        "--workpath",
        str(BUILD),
        "--specpath",
        str(BUILD),
    ]
    if profile == "dev":
        command.append("--noupx")
    for package in SOURCE_DIRS:
        command.extend(("--collect-submodules", package))
    command.extend(
        [
            "--hidden-import",
            "websockets",
            "--hidden-import",
            "google.genai",
            "--hidden-import",
            "google.generativeai",
            "--hidden-import",
            "sounddevice",
            "--hidden-import",
            "numpy",
            "--hidden-import",
            "sqlite3",
            "--hidden-import",
            "cryptography",
            "--add-data",
            f"assets{os.pathsep}assets",
            str(HERE / "main_headless.py"),
        ]
    )
    return command


def build() -> None:
    """Build the headless executable while preserving PyInstaller analysis data."""
    use_cache, force, clean, profile = _parse_args()
    if not _check_pyinstaller():
        raise SystemExit("[BUILD] PyInstaller is missing. Run 'python setup.py' first.")

    fingerprint, environment = _fingerprint(profile)
    previous = _read_state()
    executable = OUTPUT / "sirius-headless.exe"

    if clean:
        _remove(WORKPATH)
        _remove(SPEC_PATH)
        _remove(OUTPUT)
        previous = {}

    if (
        use_cache
        and not force
        and executable.exists()
        and previous.get("schema") == CACHE_SCHEMA
        and previous.get("fingerprint") == fingerprint
    ):
        print(f"[BUILD] Cached headless executable: {executable}")
        return

    if previous.get("schema") != CACHE_SCHEMA or previous.get("environment") != environment:
        _remove(WORKPATH)

    command = _build_command(profile)
    print(f"[BUILD] Running: {' '.join(command)}")
    result = subprocess.run(command, cwd=HERE)
    if result.returncode != 0:
        raise SystemExit(f"[BUILD] ERROR: PyInstaller exited with code {result.returncode}")

    if not executable.exists():
        raise SystemExit(f"[BUILD] ERROR: Expected executable not found at {executable}")

    _write_state(fingerprint, environment, profile)
    print(f"[BUILD] Success: {executable}")
    print(f"[BUILD] Output directory: {OUTPUT}")


if __name__ == "__main__":
    print("[BUILD] Building Sirius headless backend...")
    build()
    print("[BUILD] Done!")
