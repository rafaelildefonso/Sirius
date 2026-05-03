#!/usr/bin/env python3
"""
Sirius Voice Assistant - Standalone launcher
Usage: python voice-assistant.py
"""

import sys
import os
from pathlib import Path
import subprocess

def main():
    # 1. Trampoline: ensure we are running from the .venv python if it exists
    project_root = Path(__file__).parent.absolute()
    venv_python = project_root / ".venv" / "Scripts" / "python.exe"
    
    # If .venv exists and we are not using it, restart ourselves using it
    if venv_python.exists():
        # Use normpath to ensure paths are comparable on Windows
        current_exe = os.path.normpath(sys.executable).lower()
        target_exe = os.path.normpath(str(venv_python)).lower()
        
        if current_exe != target_exe:
            print(f"[Launcher] Current Python: {current_exe}")
            print(f"[Launcher] Target Python: {target_exe}")
            print(f"[Launcher] Switching to virtual environment...")
            try:
                # Transfer control to the venv python
                args = [str(venv_python)] + sys.argv
                print(f"[Launcher] Executing: {' '.join(args)}")
                sys.exit(subprocess.call(args))
            except Exception as e:
                print(f"[Launcher] Failed to switch to venv: {e}. Continuing.")

    # 2. Add root to path and start
    sys.path.insert(0, str(project_root))
    
    from voice_assistant.main import main as assistant_main
    assistant_main()

if __name__ == "__main__":
    main()
