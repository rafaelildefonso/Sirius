"""
build_headless.py — Build the Sirius headless backend for Pane integration.

Compiles main_headless.py into a standalone executable using PyInstaller.
Output: dist/sirius-headless/sirius-headless.exe

Usage:
    python build_headless.py
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIST = HERE / "dist"
BUILD = HERE / "build"
OUTPUT = DIST / "sirius-headless"


def clean():
    """Remove previous build artifacts."""
    for d in (BUILD, DIST / "sirius-headless.spec"):
        if d.is_dir():
            shutil.rmtree(d)
        elif d.is_file():
            d.unlink()

    spec_file = HERE / "sirius-headless.spec"
    if spec_file.exists():
        spec_file.unlink()


def build():
    """Run PyInstaller to build the headless backend."""
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--console",  # Keep console for logging
        "--name", "sirius-headless",
        "--distpath", str(DIST),
        "--workpath", str(BUILD),
        # Collect all required packages
        "--collect-all", "actions",
        "--collect-all", "agent",
        "--collect-all", "core",
        "--collect-all", "config",
        "--collect-all", "memory",
        "--collect-all", "orchestrator",
        "--collect-all", "persistence",
        # Hidden imports that PyInstaller may miss
        "--hidden-import", "websockets",
        "--hidden-import", "google.genai",
        "--hidden-import", "google.generativeai",
        "--hidden-import", "sounddevice",
        "--hidden-import", "numpy",
        "--hidden-import", "sqlite3",
        "--hidden-import", "cryptography",
        # Data files
        "--add-data", f"assets{Path.pathsep}assets",
        "--add-data", f"config{Path.pathsep}config",
        str(HERE / "main_headless.py"),
    ]

    print(f"[BUILD] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(HERE))

    if result.returncode != 0:
        print(f"[BUILD] ERROR: PyInstaller exited with code {result.returncode}")
        sys.exit(1)

    # Verify output
    exe = OUTPUT / "sirius-headless.exe"
    if not exe.exists():
        # Check alternative paths
        alt_exe = DIST / "sirius-headless" / "sirius-headless.exe"
        if alt_exe.exists():
            print(f"[BUILD] Found executable at {alt_exe}")
        else:
            print(f"[BUILD] ERROR: Expected executable not found at {exe}")
            sys.exit(1)
    else:
        print(f"[BUILD] Success: {exe}")

    print(f"[BUILD] Output directory: {OUTPUT}")


if __name__ == "__main__":
    print("[BUILD] Building Sirius headless backend...")
    clean()
    build()
    print("[BUILD] Done!")
