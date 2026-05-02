#!/usr/bin/env python3
"""
Jarvis Voice Assistant - Standalone launcher
Usage: python voice-assistant.py
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from voice_assistant.main import main

if __name__ == "__main__":
    main()
