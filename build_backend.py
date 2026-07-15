#!/usr/bin/env python3
"""
Build script for SIRIUS backend (headless, no PyQt6).
Produces dist/sirius-backend/sirius-backend.exe

Usage:
    python build_backend.py

Output:
    dist/sirius-backend/sirius-backend.exe  (PyInstaller bundle)
    sirius-ui/src-tauri/binaries/sirius-backend-x86_64-pc-windows-msvc.exe  (copied for Tauri sidecar)
"""

import json
import os
import subprocess
import shutil
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
TAURI_BINARIES = BASE_DIR / "sirius-ui" / "src-tauri" / "binaries"


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
        configs.write_text(json.dumps({
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
        }, indent=2), encoding="utf-8")

    for fname in ["api_keys.json", "permissions.json", "workspaces.json"]:
        fpath = config_dir / fname
        if not fpath.exists():
            print(f"[*] Creating default config/{fname}...")
            obj = {} if fname != "api_keys.json" else {
                "gemini_api_key": "",
                "openrouter_api_key": "",
                "tavily_api_key": "",
                "serpapi_key": "",
                "os_system": "windows",
            }
            fpath.write_text(json.dumps(obj, indent=2), encoding="utf-8")

    memory_dir = BASE_DIR / "memory"
    long_term = memory_dir / "long_term.json"
    if not long_term.exists():
        print("[*] Creating empty memory/long_term.json...")
        memory_dir.mkdir(parents=True, exist_ok=True)
        long_term.write_text(json.dumps({
            "identity": {}, "preferences": {}, "projects": {},
            "relationships": {}, "wishes": {}, "notes": {},
        }, indent=2), encoding="utf-8")


def _copy_data_to_bundle_root(dist_dir: Path):
    print("[*] Copying data files to bundle root...")
    for rel_dir in ["config", "core", "memory"]:
        src = BASE_DIR / rel_dir
        dst = dist_dir / rel_dir
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            for item in src.iterdir():
                if item.suffix in (".json", ".txt", ".png") and not item.name.startswith("__"):
                    shutil.copy2(item, dst / item.name)
                    print(f"    {rel_dir}/{item.name}")
    for rel_file in ["ws_server.py"]:
        src = BASE_DIR / rel_file
        if src.exists():
            shutil.copy2(src, dist_dir / rel_file)
            print(f"    {rel_file}")
    for rel_dir in ["dashboard"]:
        src = BASE_DIR / rel_dir
        dst = dist_dir / rel_dir
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            for item in src.rglob("*"):
                if item.is_file() and not item.name.startswith("__"):
                    rel = item.relative_to(src)
                    (dst / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dst / rel)
                    print(f"    {rel_dir}/{rel}")
    for fname in (".env",):
        src = BASE_DIR / fname
        if src.exists():
            shutil.copy2(src, dist_dir / fname)
            print(f"    {fname}")


def _get_target_triple() -> str:
    """Detect Windows target triple for Tauri sidecar naming."""
    try:
        import platform
        arch = platform.machine().lower()
        if arch in ("amd64", "x86_64"):
            return "x86_64-pc-windows-msvc"
        elif arch == "arm64":
            return "aarch64-pc-windows-msvc"
        return f"{arch}-pc-windows-msvc"
    except Exception:
        return "x86_64-pc-windows-msvc"


def _clean_build_artifacts():
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
                time.sleep(2 ** attempt)
        if p.exists():
            print(f"[ERRO] Could not remove {d}/ after 5 attempts.")
            print(f"    Manually delete: {p}")
            sys.exit(1)


def _compute_backend_hash() -> str:
    import hashlib
    hasher = hashlib.sha256()
    
    # Watch files
    watch_paths = [
        BASE_DIR / "main.py",
        BASE_DIR / "sirius_backend_launcher.py",
        BASE_DIR / "ws_server.py",
        BASE_DIR / "sirius-backend.spec",
        BASE_DIR / "requirements.txt",
    ]
    
    # Watch directories recursively
    for folder in ["core", "actions", "agent"]:
        folder_path = BASE_DIR / folder
        if folder_path.is_dir():
            for root, _, files in os.walk(folder_path):
                for file in sorted(files):
                    if file.endswith((".py", ".txt")):
                        watch_paths.append(Path(root) / file)
                        
    for path in sorted(watch_paths):
        if path.exists():
            hasher.update(str(path.relative_to(BASE_DIR)).encode("utf-8"))
            try:
                with open(path, "rb") as f:
                    while chunk := f.read(8192):
                        hasher.update(chunk)
            except Exception:
                pass
                
    return hasher.hexdigest()


def main():
    use_cache = "--cached" in sys.argv
    triple = _get_target_triple()
    dst_exe = TAURI_BINARIES / f"sirius-backend-{triple}.exe"
    
    hash_file = BASE_DIR / ".backend_build_hash"
    current_hash = _compute_backend_hash()
    
    if use_cache and hash_file.exists() and dst_exe.exists():
        try:
            saved_hash = hash_file.read_text(encoding="utf-8").strip()
            if saved_hash == current_hash:
                print("=" * 60)
                print("  SIRIUS Backend — Build Script (Cached)")
                print("  Backend source unchanged. Skipping PyInstaller build.")
                print(f"  Sidecar:    {dst_exe}")
                print("=" * 60)
                return
        except Exception:
            pass

    print("=" * 60)
    print("  SIRIUS Backend — Build Script")
    print("  Generates headless .exe for Tauri sidecar")
    print("=" * 60)

    if not _check_pyinstaller():
        _install_pyinstaller()
    else:
        print("[OK] PyInstaller already installed\n")

    _ensure_config_files()
    _clean_build_artifacts()

    spec_file = BASE_DIR / "sirius-backend.spec"
    if not spec_file.exists():
        print("[ERRO] sirius-backend.spec not found!")
        sys.exit(1)

    print("[*] Building sirius-backend.exe...\n")
    env = os.environ.copy()
    env["SIRIUS_BUILD_ROOT"] = str(BASE_DIR)
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "-y", str(spec_file)],
        cwd=BASE_DIR,
        env=env,
    )

    print()
    if result.returncode != 0:
        print("[ERRO] Build failed. Check output above.")
        sys.exit(1)

    src_exe = BASE_DIR / "dist" / "sirius-backend.exe"
    if not src_exe.exists():
        print(f"[ERRO] dist/sirius-backend.exe not found after build!")
        sys.exit(1)

    # Copy single binary to Tauri sidecar location
    triple = _get_target_triple()
    TAURI_BINARIES.mkdir(parents=True, exist_ok=True)
    dst_exe = TAURI_BINARIES / f"sirius-backend-{triple}.exe"

    # Kill any process holding the destination before attempting copy
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Get-Process | Where-Object {{ $_.Path -like '*{dst_exe.name}*' -or $_.Modules.FileName -like '*{dst_exe.name}*' }} | Stop-Process -Force"],
        capture_output=True
    )
    import time
    time.sleep(1)

    for attempt in range(10):
        try:
            if dst_exe.exists():
                dst_exe.unlink()
            shutil.copy2(src_exe, dst_exe)
            print(f"\n[OK] Copied to Tauri sidecar: {dst_exe}")
            break
        except PermissionError:
            if attempt < 3:
                print(f"[!] Retrying copy to {dst_exe.name} (attempt {attempt+2})...")
                time.sleep(1.5)
    else:
        print(f"[ERRO] Could not copy to {dst_exe} after 10 attempts.")
        print(f"       Close any running SIRIUS/Tauri processes and try again.")
        print(f"       You can manually copy: {src_exe} -> {dst_exe}")
        sys.exit(1)

    try:
        hash_file.write_text(current_hash, encoding="utf-8")
    except Exception as e:
        print(f"[!] Warning: Could not save build hash: {e}")

    size_mb = src_exe.stat().st_size / (1024 * 1024)
    print("=" * 60)
    print(f"  BUILD SUCCESSFUL")
    print(f"  Binary:     {src_exe}")
    print(f"  Size:       {size_mb:.1f} MB")
    print(f"  Sidecar:    {dst_exe}")
    print("=" * 60)


if __name__ == "__main__":
    main()
