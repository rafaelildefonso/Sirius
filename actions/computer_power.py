"""Explicit OS power requests used by trusted, non-AI interfaces only."""

from __future__ import annotations

import platform
import subprocess
from collections.abc import Callable


def request_shutdown(
    runner: Callable[..., object] = subprocess.run,
    system: str | None = None,
) -> None:
    """Ask the OS to shut down; raise if it rejects the request.

    A delayed shutdown gives the user a short window to react if the button was
    pressed accidentally. This function is called only by the paired-device
    endpoint, never through the model's tool dispatcher.
    """
    os_name = (system or platform.system()).lower()
    if os_name == "windows":
        command = ["shutdown", "/s", "/t", "30"]
    elif os_name == "darwin":
        command = ["osascript", "-e", 'tell application "System Events" to shut down']
    elif os_name == "linux":
        command = ["systemctl", "poweroff"]
    else:
        raise RuntimeError(f"Unsupported operating system: {os_name}")

    result = runner(command, capture_output=True, text=True, timeout=10)
    if getattr(result, "returncode", 1) != 0:
        detail = getattr(result, "stderr", "") or "Operating system rejected the request"
        raise RuntimeError(str(detail).strip())

