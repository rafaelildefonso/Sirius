#!/usr/bin/env python3
"""
Build script for SIRIUS backend (headless, no PyQt6).
Produces dist/sirius-backend/sirius-backend.exe

Usage:
    python build_backend.py --cached --profile=dev
    python build_backend.py --cached --profile=release
    python build_backend.py --clean --force

Output:
    dist/sirius-backend/sirius-backend.exe  (PyInstaller bundle)
    sirius-ui/src-tauri/binaries/sirius-backend-x86_64-pc-windows-msvc.exe  (copied for Tauri sidecar)
"""

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Iterable

BASE_DIR = Path(__file__).resolve().parent
TAURI_BINARIES = BASE_DIR / "sirius-ui" / "src-tauri" / "binaries"
BUILD_DIR = BASE_DIR / "build"
DIST_DIR = BASE_DIR / "dist"
BUILD_STATE_FILE = BASE_DIR / ".backend_build_state.json"
CACHE_SCHEMA = 2
PUBLIC_DATA_DIRS = ("assets",)
SOURCE_CODE_DIRS = (
    "core",
    "actions",
    "agent",
    "dashboard",
    "persistence",
    "plugins",
    "orchestrator",
    "config",
    "memory",
)


def _check_pyinstaller() -> bool:
    try:
        import PyInstaller  # noqa: F401
        return True
    except ImportError:
        return False


def _parse_args() -> tuple[bool, bool, bool, bool, str]:
    """Parse the small, stable command-line contract used by Tauri and CI."""
    allowed = {"--cached", "--force", "--clean", "--no-lint"}
    unknown = [arg for arg in sys.argv[1:] if not arg.startswith("--profile=") and arg not in allowed]
    if unknown:
        raise SystemExit(f"Unknown build argument(s): {', '.join(unknown)}")

    profile = "dev"
    for arg in sys.argv[1:]:
        if arg.startswith("--profile="):
            profile = arg.split("=", 1)[1].strip().lower()
    if profile not in {"dev", "release"}:
        raise SystemExit("--profile must be 'dev' or 'release'")

    return (
        "--cached" in sys.argv,
        "--force" in sys.argv,
        "--clean" in sys.argv,
        "--no-lint" in sys.argv,
        profile,
    )


def _ensure_config_files() -> None:
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


def _copy_data_to_bundle_root(dist_dir: Path) -> None:
    """Copy only public runtime data when this helper is used externally.

    User configuration, credentials, databases and certificates must never be
    copied into a distributable backend bundle.
    """
    print("[*] Copying public data files to bundle root...")
    for rel_dir in PUBLIC_DATA_DIRS:
        src = BASE_DIR / rel_dir
        if not src.is_dir():
            continue
        for item in src.rglob("*"):
            if item.is_file() and not item.name.startswith("__"):
                rel = item.relative_to(BASE_DIR)
                target = dist_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                print(f"    {rel}")

    static_dir = BASE_DIR / "dashboard" / "static"
    if static_dir.is_dir():
        for item in static_dir.rglob("*"):
            if item.is_file() and not item.name.startswith("__"):
                rel = item.relative_to(BASE_DIR)
                target = dist_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                print(f"    {rel}")


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


def _remove_path(path: Path) -> None:
    """Remove one exact build path, preserving unrelated workspace data."""
    if not path.exists():
        return
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    except OSError as exc:
        raise SystemExit(f"[ERRO] Could not remove {path}: {exc}") from exc


def _clean_build_artifacts() -> None:
    """Explicitly remove all PyInstaller output and its incremental work cache."""
    print("[*] Removing build/ and dist/ directories (--clean)...")
    _remove_path(BUILD_DIR)
    _remove_path(DIST_DIR)


def _iter_files(paths: Iterable[Path], suffixes: set[str] | None = None) -> Iterable[Path]:
    """Yield stable, relevant files while excluding runtime/generated state."""
    excluded_names = {".env", ".db_key"}
    excluded_suffixes = {".db", ".key", ".crt", ".pyc", ".pyo"}
    for path in paths:
        if path.is_file():
            candidates = [path]
        elif path.is_dir():
            candidates = path.rglob("*")
        else:
            continue
        for candidate in candidates:
            if not candidate.is_file():
                continue
            if any(part in {"__pycache__", ".git", "node_modules", "target"} for part in candidate.parts):
                continue
            if candidate.name in excluded_names or candidate.suffix.lower() in excluded_suffixes:
                continue
            if suffixes is not None and candidate.suffix.lower() not in suffixes:
                continue
            yield candidate


def _requirements_packages() -> list[str]:
    """Return normalized package names declared by requirements.txt."""
    packages: list[str] = []
    requirements = BASE_DIR / "requirements.txt"
    if not requirements.exists():
        return packages
    for line in requirements.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "http:", "https:")):
            continue
        match = re.match(r"([A-Za-z0-9_.-]+)", line)
        if match:
            packages.append(match.group(1).lower().replace("_", "-"))
    return sorted(set(packages))


def _installed_dependency_versions() -> dict[str, str]:
    """Capture versions that can change PyInstaller's collected graph."""
    names = {"pyinstaller", "ruff", *_requirements_packages()}
    versions: dict[str, str] = {}
    for name in sorted(names):
        try:
            versions[name] = importlib_metadata.version(name)
        except importlib_metadata.PackageNotFoundError:
            versions[name] = "<missing>"
    return versions


def _environment_fingerprint(profile: str) -> dict[str, object]:
    """Return build-environment values that affect the generated executable."""
    return {
        "python": platform.python_version(),
        "python_executable": str(Path(sys.executable).resolve()),
        "platform": platform.platform(),
        "target": _get_target_triple(),
        "profile": profile,
        "dependencies": _installed_dependency_versions(),
    }


def _compute_backend_hash(profile: str) -> tuple[str, dict[str, object]]:
    """Hash source, public data and toolchain state for safe cache reuse."""
    import hashlib

    hasher = hashlib.sha256()
    watch_paths: list[Path] = [
        BASE_DIR / "main.py",
        BASE_DIR / "sirius_backend_launcher.py",
        BASE_DIR / "ws_server.py",
        BASE_DIR / "sirius-backend.spec",
        BASE_DIR / "build_backend.py",
        BASE_DIR / "requirements.txt",
        BASE_DIR / "ruff.toml",
    ]
    if (BASE_DIR / "requirements.lock").exists():
        watch_paths.append(BASE_DIR / "requirements.lock")

    environment = _environment_fingerprint(profile)
    hasher.update(f"cache-schema:{CACHE_SCHEMA}\n".encode("utf-8"))
    hasher.update(json.dumps(environment, sort_keys=True).encode("utf-8"))

    source_paths = [BASE_DIR / folder for folder in SOURCE_CODE_DIRS]
    public_paths = [BASE_DIR / folder for folder in PUBLIC_DATA_DIRS]
    public_paths.append(BASE_DIR / "dashboard" / "static")
    tracked_files = list(_iter_files(watch_paths))
    tracked_files.extend(_iter_files(source_paths, suffixes={".py"}))
    tracked_files.extend(_iter_files(public_paths))

    for path in sorted(set(tracked_files)):
        if path.exists():
            hasher.update(str(path.relative_to(BASE_DIR)).encode("utf-8"))
            with path.open("rb") as file:
                while chunk := file.read(8192):
                    hasher.update(chunk)

    return hasher.hexdigest(), environment


def _read_build_state() -> dict[str, object]:
    """Read cache metadata, returning an empty state for old/incomplete builds."""
    try:
        state = json.loads(BUILD_STATE_FILE.read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}


def _write_build_state(fingerprint: str, environment: dict[str, object]) -> None:
    """Persist cache metadata only after the sidecar was copied successfully."""
    state = {
        "schema": CACHE_SCHEMA,
        "fingerprint": fingerprint,
        "environment": environment,
        "sidecar": str((TAURI_BINARIES / f"sirius-backend-{_get_target_triple()}.exe").relative_to(BASE_DIR)),
    }
    BUILD_STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _workpath_is_reusable(previous_state: dict[str, object], environment: dict[str, object]) -> bool:
    """Decide whether PyInstaller's incremental workpath is compatible."""
    return previous_state.get("schema") == CACHE_SCHEMA and previous_state.get("environment") == environment


def _run_lint() -> None:
    print("[*] Running Ruff linter...")
    try:
        import ruff  # noqa: F401
    except ImportError:
        print("[*] Ruff not found — installing...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "ruff"],
            check=True,
            capture_output=True,
        )
        print("[OK] Ruff installed\n")
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", ".", "--exclude", "Mark-LI"],
        cwd=BASE_DIR,
    )
    if result.returncode != 0:
        print("\n[ERRO] Lint failed. Fix the issues above or skip with --no-lint.")
        sys.exit(1)
    print("[OK] Lint passed\n")


def main() -> None:
    use_cache, force, clean, skip_lint, profile = _parse_args()
    triple = _get_target_triple()
    dst_exe = TAURI_BINARIES / f"sirius-backend-{triple}.exe"

    if not _check_pyinstaller():
        raise SystemExit(
            "[ERRO] PyInstaller is not installed in the selected Python environment. "
            "Run 'python setup.py' once, then retry the build."
        )
    print("[OK] PyInstaller already installed\n")

    current_hash, environment = _compute_backend_hash(profile)
    previous_state = _read_build_state()

    if clean:
        _clean_build_artifacts()
        previous_state = {}

    if (
        use_cache
        and not force
        and dst_exe.exists()
        and previous_state.get("schema") == CACHE_SCHEMA
        and previous_state.get("fingerprint") == current_hash
    ):
        print("=" * 60)
        print("  SIRIUS Backend — Build Script (Cached)")
        print("  Backend source and build environment unchanged.")
        print(f"  Sidecar:    {dst_exe}")
        print("=" * 60)
        return

    print("=" * 60)
    print("  SIRIUS Backend — Build Script")
    print("  Generates headless .exe for Tauri sidecar")
    print("=" * 60)

    if not skip_lint:
        _run_lint()

    _ensure_config_files()

    # A missing state file means the workpath may have been generated by the
    # previous cache contract. Reusing it could leave stale analysis metadata.
    # Once this build succeeds, subsequent compatible builds reuse it.
    if not _workpath_is_reusable(previous_state, environment):
        _remove_path(BUILD_DIR / "sirius-backend")

    spec_file = BASE_DIR / "sirius-backend.spec"
    if not spec_file.exists():
        print("[ERRO] sirius-backend.spec not found!")
        sys.exit(1)

    print("[*] Building sirius-backend.exe...\n")
    env = os.environ.copy()
    env["SIRIUS_BUILD_ROOT"] = str(BASE_DIR)
    env["SIRIUS_BUILD_PROFILE"] = profile
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
        print("[ERRO] dist/sirius-backend.exe not found after build!")
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
        print("       Close any running SIRIUS/Tauri processes and try again.")
        print(f"       You can manually copy: {src_exe} -> {dst_exe}")
        sys.exit(1)

    try:
        _write_build_state(current_hash, environment)
        # Keep the legacy marker for tools that only inspect its existence.
        (BASE_DIR / ".backend_build_hash").write_text(current_hash, encoding="utf-8")
    except OSError as exc:
        print(f"[!] Warning: Could not save build state: {exc}")

    size_mb = src_exe.stat().st_size / (1024 * 1024)
    print("=" * 60)
    print("  BUILD SUCCESSFUL")
    print(f"  Binary:     {src_exe}")
    print(f"  Size:       {size_mb:.1f} MB")
    print(f"  Sidecar:    {dst_exe}")
    print("=" * 60)


if __name__ == "__main__":
    main()
