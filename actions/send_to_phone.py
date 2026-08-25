"""
send_to_phone.py — Send a message/notification from SIRIUS to the companion
phone app. The message is queued on the dashboard server and delivered at the
phone's next sync cycle (foreground: <=45 s; background: <=15 min).
"""

from __future__ import annotations

from datetime import datetime

MAX_TEXT_LEN = 500


def _sanitise(text: str) -> str:
    return text.replace("\r", "").strip()[:MAX_TEXT_LEN]


def send_to_phone(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """Tool handler: push a message/notification to the user's phone."""
    text = str(parameters.get("message") or parameters.get("text") or "").strip()
    if not text:
        return "I need a message to send to your phone."
    text = _sanitise(text)

    dash = None
    try:
        import main as _main

        dash = getattr(_main, "_DASHBOARD", None)
    except Exception:
        pass
    if dash is None:
        return (
            "I couldn't reach the remote dashboard, so I can't deliver "
            "anything to your phone right now."
        )

    try:
        queued = dash.queue_phone_command({
            "text": text,
            "timestamp": datetime.now().isoformat(),
        })
    except Exception as e:
        print(f"[SendToPhone] [FAIL] {e}")
        return "Something went wrong while queueing the message for your phone."

    if not queued:
        return "No phone is paired with SIRIUS right now, so there's nowhere to send it."

    if player and hasattr(player, "write_log"):
        player.write_log(f"[SendToPhone] [OK] {text[:60]}")
    return "Message sent to your phone."
