"""Global hotkey handling using pynput."""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from pynput import keyboard


class PushToTalkHandler:
    """Handles push-to-talk hotkey (Ctrl+Shift+Space for background)."""

    def __init__(
        self,
        on_push: Callable[[], None],
        on_release: Callable[[], None],
        hotkey: str = "ctrl+shift+space",
    ):
        self.on_push = on_push
        self.on_release = on_release
        self.hotkey = hotkey
        self._pressed = set()
        self._is_holding = False
        self._listener: Optional[keyboard.Listener] = None
        self._running = False

        # Parse hotkey combination
        self._hotkey_parts = set(hotkey.lower().split("+"))

    def _on_press(self, key) -> bool:
        """Handle key press."""
        try:
            key_name = None
            if hasattr(key, 'char') and key.char:
                key_name = key.char.lower()
            elif hasattr(key, 'name') and key.name:
                key_name = key.name.lower()

            if key_name:
                self._pressed.add(key_name)

            # Check if hotkey combo is active
            if self._hotkey_parts.issubset(self._pressed) and not self._is_holding:
                self._is_holding = True
                self.on_push()

        except Exception as e:
            print(f"Hotkey press error: {e}")

        return True  # Continue listening

    def _on_release(self, key) -> bool:
        """Handle key release."""
        try:
            key_name = None
            if hasattr(key, 'char') and key.char:
                key_name = key.char.lower()
            elif hasattr(key, 'name') and key.name:
                key_name = key.name.lower()

            if key_name and key_name in self._pressed:
                self._pressed.remove(key_name)

            # Check if hotkey was released
            if self._is_holding and not self._hotkey_parts.issubset(self._pressed):
                self._is_holding = False
                self.on_release()

        except Exception as e:
            print(f"Hotkey release error: {e}")

        return True  # Continue listening

    def start(self) -> None:
        """Start listening for hotkeys."""
        if self._running:
            return

        self._running = True
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.start()

    def stop(self) -> None:
        """Stop listening."""
        self._running = False
        if self._listener:
            self._listener.stop()
            self._listener = None

    def is_running(self) -> bool:
        """Check if listener is active."""
        return self._running and self._listener is not None and self._listener.is_alive()
