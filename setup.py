"""Bootstrap the SIRIUS Python environment without repeated installations."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
SETUP_STATE = ROOT / ".runtime_setup_state.json"
REQUIREMENTS = ROOT / "requirements.txt"
LOCKFILE = ROOT / "requirements.lock"


def _requirements_file() -> Path:
    """Prefer the reproducible lockfile when it exists."""
    return LOCKFILE if LOCKFILE.exists() else REQUIREMENTS


def _requirements_hash(path: Path) -> str:
    """Hash dependency declarations for idempotent environment setup."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _environment_state(requirements_file: Path) -> dict[str, str]:
    """Build the setup marker for this interpreter and dependency input."""
    return {
        "python": platform.python_version(),
        "executable": str(Path(sys.executable).resolve()),
        "requirements": str(requirements_file.relative_to(ROOT)),
        "requirements_hash": _requirements_hash(requirements_file),
    }


def _read_state() -> dict[str, Any]:
    """Read the setup marker, treating missing or invalid state as stale."""
    try:
        value = json.loads(SETUP_STATE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}


def _run(command: list[str]) -> None:
    """Run a setup command with the current interpreter and fail clearly."""
    print(f"[*] Running: {' '.join(command)}")
    subprocess.run(command, cwd=ROOT, check=True)


def _check_pywin32() -> None:
    """Warn when pywin32's optional post-install step was not available."""
    if platform.system() != "Windows":
        return
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        postinstall = Path(sys.executable).parent / "pywin32_postinstall.py"
        print(
            "\n[WARN] pywin32 did not install correctly — desktop shortcut creation "
            "may use a slower fallback.\n"
            "    Try fixing it manually with:\n"
            f'    "{sys.executable}" -m pip install --force-reinstall pywin32\n'
            f'    "{postinstall}" -install\n'
        )


def main() -> int:
    """Install dependencies only when the environment fingerprint changes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="reinstall dependencies and browsers")
    parser.add_argument("--skip-playwright", action="store_true", help="do not install Playwright browsers")
    parser.add_argument("--check", action="store_true", help="check setup without changing files")
    args = parser.parse_args()

    requirements_file = _requirements_file()
    if not requirements_file.exists():
        print(f"[ERROR] Dependency file not found: {requirements_file}")
        return 1

    expected = _environment_state(requirements_file)
    state = _read_state()
    dependencies_current = state.get("environment") == expected
    browsers_current = bool(state.get("playwright_browsers"))

    if args.check:
        print("[OK] Python environment is current." if dependencies_current else "[!] Python dependencies require setup.")
        if args.skip_playwright:
            return 0 if dependencies_current else 1
        print("[OK] Playwright browsers are marked current." if browsers_current else "[!] Playwright browsers require setup.")
        return 0 if dependencies_current and browsers_current else 1

    if args.force or not dependencies_current:
        print(f"[*] Installing dependencies from {requirements_file.name}...")
        _run([
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            str(requirements_file),
            "--disable-pip-version-check",
        ])
    else:
        print("[OK] Python dependencies already match the dependency file.")

    playwright_current = browsers_current and dependencies_current
    if not args.skip_playwright and (args.force or not browsers_current or not dependencies_current):
        print("[*] Installing Playwright browsers...")
        _run([sys.executable, "-m", "playwright", "install"])
        playwright_current = True
    elif args.skip_playwright:
        print("[!] Playwright browser installation skipped.")
    else:
        print("[OK] Playwright browsers already installed.")

    SETUP_STATE.write_text(
        json.dumps(
            {"environment": expected, "playwright_browsers": playwright_current},
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    _check_pywin32()
    print("\n[OK] Setup complete! Run 'python main.py' to start SIRIUS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

