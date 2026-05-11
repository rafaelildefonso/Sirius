#!/usr/bin/env python3
"""Voice assistant entry point - launched by Tauri desktop app."""

import sys
import os

# Add voice_assistant to path
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

try:
    from voice_assistant.main import VoiceAssistant
    
    print("=" * 50)
    print("Sirius Voice Assistant")
    print("=" * 50)
    
    assistant = VoiceAssistant()
    assistant.run()
    
except KeyboardInterrupt:
    print("\n[INFO] Interrupted by user")
except Exception as e:
    print(f"\n[ERROR] {e}")
    import traceback
    traceback.print_exc()
    input("\nPress Enter to exit...")
