"""Tauri Desktop Launcher - starts backend and opens Tauri app with voice mode."""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def wait_for_backend(url: str = "http://127.0.0.1:8000/health", timeout: int = 60) -> bool:
    """Poll backend health endpoint until it responds or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            time.sleep(1)
    return False


def start_backend():
    """Start FastAPI backend server."""
    print("🚀 Starting backend server...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "openjarvis.cli", "serve"],
        cwd=Path(__file__).parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if wait_for_backend():
        print("✅ Backend is ready!")
    else:
        print("⚠️  Backend did not start within timeout, continuing anyway...")
    return proc


def start_tauri_dev():
    """Start Tauri dev mode."""
    print("🖥️  Starting Tauri Desktop app...")
    frontend_dir = Path(__file__).parent / "frontend"
    proc = subprocess.Popen(
        "npm run tauri dev",
        cwd=frontend_dir,
        shell=True,
    )
    return proc


def main():
    """Main entry point."""
    # Start backend
    backend_proc = start_backend()
    
    # Start Tauri app
    tauri_proc = start_tauri_dev()
    
    print("\n✅ OpenSirius Desktop running!")
    print("🖥️  App: Tauri window opening...")
    print("🔧 API: http://localhost:8000")
    print("\nPress Ctrl+C to stop")
    
    try:
        # Wait for Tauri to close
        tauri_proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        print("\n🛑 Shutting down...")
        tauri_proc.terminate()
        backend_proc.terminate()


if __name__ == "__main__":
    main()
