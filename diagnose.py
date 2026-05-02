#!/usr/bin/env python3
"""Diagnose OpenJarvis issues."""

import subprocess
import sys
import time
import urllib.request
import json
from pathlib import Path

def check_backend():
    """Check if backend is running."""
    print("🔍 Checking backend...")
    try:
        req = urllib.request.Request('http://localhost:8000/health', method='GET')
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            print(f"✅ Backend is running: {data}")
            return True
    except Exception as e:
        print(f"❌ Backend not responding: {e}")
        return False

def check_models():
    """Check if models endpoint works."""
    print("\n🔍 Checking models API...")
    try:
        req = urllib.request.Request('http://localhost:8000/v1/models', method='GET')
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            print(f"✅ Models endpoint working")
            print(f"   Models: {data.get('models', [])}")
            return True
    except Exception as e:
        print(f"❌ Models endpoint failed: {e}")
        return False

def check_voice_assistant():
    """Check if voice assistant can start."""
    print("\n🔍 Checking voice assistant...")
    voice_script = Path(__file__).parent / "voice-assistant.py"
    
    if not voice_script.exists():
        print(f"❌ voice-assistant.py not found at {voice_script}")
        return False
    
    print(f"✅ voice-assistant.py found at {voice_script}")
    
    # Check imports
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from voice_assistant.main import VoiceAssistant
        print("✅ Voice assistant imports working")
        return True
    except Exception as e:
        print(f"❌ Voice assistant import failed: {e}")
        return False

def start_backend_temp():
    """Try to start backend temporarily."""
    print("\n🚀 Attempting to start backend...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "openjarvis.cli", "serve"],
        cwd=Path(__file__).parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(5)
    return proc

def main():
    print("=" * 50)
    print("OpenJarvis Diagnostic Tool")
    print("=" * 50)
    
    # Check backend
    backend_ok = check_backend()
    
    if not backend_ok:
        print("\n⚠️  Backend not running. Starting temporarily...")
        backend_proc = start_backend_temp()
        backend_ok = check_backend()
    
    # Check models
    if backend_ok:
        check_models()
    
    # Check voice assistant
    check_voice_assistant()
    
    print("\n" + "=" * 50)
    print("Diagnosis complete!")
    print("=" * 50)
    
    if not backend_ok:
        print("\n💡 To start normally:")
        print("   uv run python run-tauri.py")
        print("   or")
        print("   uv run python -m openjarvis.cli serve")

if __name__ == "__main__":
    main()
