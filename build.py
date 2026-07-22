#!/usr/bin/env python3
"""
Build script for SIRIUS — creates a standalone Windows executable.

Usage:
    python build.py

Requirements:
    - Python 3.11+ with venv activated
    - PyInstaller (auto-installed if missing)

Output:
    dist/SIRIUS/SIRIUS.exe
"""

import json
import os
import subprocess
import sys
import time
import shutil
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def _check_pyinstaller():
    try:
        import PyInstaller  # noqa: F401
        return True
    except ImportError:
        return False


def _install_pyinstaller():
    print("[*] Installing PyInstaller...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "pyinstaller"],
        check=True,
    )
    print("[OK] PyInstaller installed\n")


def _ensure_config_files():
    config_dir = BASE_DIR / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    configs = config_dir / "configs.json"
    if not configs.exists():
        print("[*] Creating default config/configs.json template...")
        _configs_template = {
            "os_system": "windows",
            "assistant_mode": "gemini",
            "stt_engine": "whisper",
            "stt_language": "auto",
            "stt_model": "medium",
            "llm_provider": "gemini",
            "llm_url": "http://localhost:11434",
            "llm_model": "qwen2.5:7b",
            "tts_engine": "kokoro",
            "elevenlabs_api_key": "",
            "tts_voice": "af_heart",
            "tts_speed": "1.2",
        }
        configs.write_text(json.dumps(_configs_template, indent=2), encoding="utf-8")

    api_keys = config_dir / "api_keys.json"
    if not api_keys.exists():
        print("[*] Creating default config/api_keys.json template...")
        _template = {
            "gemini_api_key": "",
            "openrouter_api_key": "",
            "tavily_api_key": "",
            "serpapi_key": "",
            "os_system": "windows",
        }
        api_keys.write_text(json.dumps(_template, indent=2), encoding="utf-8")

    perms = config_dir / "permissions.json"
    if not perms.exists():
        print("[*] Creating default config/permissions.json...")
        perms.write_text("{}\n", encoding="utf-8")

    workspaces = config_dir / "workspaces.json"
    if not workspaces.exists():
        print("[*] Creating empty config/workspaces.json...")
        workspaces.write_text("{}\n", encoding="utf-8")

    memory_dir = BASE_DIR / "memory"
    long_term = memory_dir / "long_term.json"
    if not long_term.exists():
        print("[*] Creating empty memory/long_term.json...")
        memory_dir.mkdir(parents=True, exist_ok=True)
        long_term.write_text(
            json.dumps(
                {
                    "identity": {},
                    "preferences": {},
                    "projects": {},
                    "relationships": {},
                    "wishes": {},
                    "notes": {},
                },
                indent=2,
            ),
            encoding="utf-8",
        )


def _ask_keep_credentials() -> bool:
    """Ask whether existing credentials should be bundled. Never modifies source files."""
    dotenv_path = BASE_DIR / ".env"
    api_keys_path = BASE_DIR / "config" / "api_keys.json"
    has_creds = dotenv_path.exists() or api_keys_path.exists()
    if not has_creds:
        return False
    print("[?] Use existing credentials (.env + api_keys.json) in the build?")
    answer = input("    (y/N): ").strip().lower()
    if answer == "y":
        print("[*] Keeping existing credentials.")
        return True
    print("[*] Using clean template (no credentials in build).")
    return False


def _ensure_icon() -> Path | None:
    """Convert face.png -> face.ico for embedding as app icon."""
    import io
    import struct
    png = BASE_DIR / "face.png"
    ico = BASE_DIR / "face.ico"
    if not png.exists():
        return None
    if ico.exists() and ico.stat().st_mtime >= png.stat().st_mtime:
        return ico
    try:
        from PIL import Image
        img = Image.open(png).convert("RGBA")
        sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        png_frames = []
        for w, h in sizes:
            resized = img.resize((w, h), Image.LANCZOS)
            buf = io.BytesIO()
            resized.save(buf, format="PNG")
            png_frames.append(buf.getvalue())
        count = len(sizes)
        offset = 6 + count * 16
        dir_entries = []
        for i, (w, h) in enumerate(sizes):
            data = png_frames[i]
            dir_entries.append(struct.pack("<BBBBHHII",
                w if w < 256 else 0, h if h < 256 else 0,
                0, 0, 1, 32, len(data), offset))
            offset += len(data)
        with open(ico, "wb") as f:
            f.write(struct.pack("<HHH", 0, 1, count))
            for e in dir_entries:
                f.write(e)
            for d in png_frames:
                f.write(d)
        print(f"[*] Created {ico.name} (multi-res: 16×16 to 256×256)")
        return ico
    except Exception as e:
        print(f"[!] Failed to convert face.png to ICO: {e}")
        return None


_CREDENTIALS_TEMPLATE = {
    "gemini_api_key": "",
    "openrouter_api_key": "",
    "tavily_api_key": "",
    "serpapi_key": "",
    "os_system": "windows",
}


def _copy_data_to_bundle_root(dist_dir: Path, keep_credentials: bool):
    """Copy data files to bundle root so frozen modules can find them via sys.executable.parent."""
    print("[*] Copying data files to bundle root...")

    dotenv_src = BASE_DIR / ".env"
    dotenv_dst = dist_dir / ".env"
    if dotenv_src.exists():
        if keep_credentials:
            shutil.copy2(dotenv_src, dotenv_dst)
            print(f"    .env (with credentials)")
        else:
            dotenv_dst.write_text("# .env template - configure your keys\n", encoding="utf-8")
            print(f"    .env (clean template)")

    for rel_dir in ["config", "core", "memory"]:
        src = BASE_DIR / rel_dir
        dst = dist_dir / rel_dir
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            for item in src.iterdir():
                if item.suffix in (".json", ".txt", ".png") and not item.name.startswith("__"):
                    if item.name == "api_keys.json" and not keep_credentials:
                        (dst / item.name).write_text(
                            json.dumps(_CREDENTIALS_TEMPLATE, indent=2), encoding="utf-8"
                        )
                        print(f"    {rel_dir}/{item.name} (clean template)")
                    else:
                        shutil.copy2(item, dst / item.name)
                        print(f"    {rel_dir}/{item.name}")
    # Also copy face.png and face.ico to root
    for fname in ("face.png", "face.ico"):
        src = BASE_DIR / fname
        if src.exists():
            shutil.copy2(src, dist_dir / fname)
            print(f"    {fname}")

def _kill_sirius_processes():
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-Process SIRIUS -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue"],
        capture_output=True,
    )
    time.sleep(2)

def _clean_build_artifacts():
    _kill_sirius_processes()
    for d in ["build", "dist"]:
        p = BASE_DIR / d
        if not p.exists():
            continue
        print(f"[*] Removing stale {d}/ directory...")
        for attempt in range(5):
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Remove-Item -LiteralPath '{p}' -Recurse -Force -ErrorAction SilentlyContinue"],
                capture_output=True,
            )
            if not p.exists():
                break
            if attempt < 4:
                wait = 2 ** attempt
                print(f"    Retrying in {wait}s... (attempt {attempt + 1})")
                time.sleep(wait)
        if p.exists():
            print(f"[ERRO] Could not remove {d}/ after 5 attempts.")
            print(f"    Please close any programs accessing this folder and try again.")
            print(f"    You can manually delete: {p}")
            sys.exit(1)


def main():
    print("=" * 60)
    print("  SIRIUS — Build Script")
    print("  Generates a standalone .exe via PyInstaller")
    print("=" * 60)

    if not _check_pyinstaller():
        _install_pyinstaller()
    else:
        print("[OK] PyInstaller already installed\n")

    ico_path = _ensure_icon()
    if ico_path:
        print(f"[OK] App icon: {ico_path.name}")
    else:
        print("[!] face.png not found — app will run without custom icon.")
        print("    Place a square PNG named 'face.png' in the project root if desired.\n")

    _ensure_config_files()

    keep_credentials = _ask_keep_credentials()

    _clean_build_artifacts()

    spec_file = BASE_DIR / "sirius.spec"
    if not spec_file.exists():
        print("[ERRO] sirius.spec not found!")
        sys.exit(1)

    print("[*] Building SIRIUS executable...\n")
    env = os.environ.copy()
    env["SIRIUS_BUILD_ROOT"] = str(BASE_DIR)
    if ico_path:
        env["SIRIUS_BUILD_ICON"] = str(ico_path)
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "-y", str(spec_file)],
        cwd=BASE_DIR,
        env=env,
    )

    print()
    if result.returncode == 0:
        standalone = BASE_DIR / "dist" / "SIRIUS.exe"
        if standalone.exists():
            standalone.unlink()
        dist_dir = BASE_DIR / "dist" / "SIRIUS"
        _copy_data_to_bundle_root(dist_dir, keep_credentials)
        print("=" * 60)
        print("  BUILD SUCCESSFUL")
        print(f"  Output: {dist_dir / 'SIRIUS.exe'}")
        print("=" * 60)
    else:
        print("[ERRO] Build failed. Check the output above for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
