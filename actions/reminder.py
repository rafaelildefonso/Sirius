"""
reminder.py — Voice/LLM reminder tool backed by the unified `scheduled_tasks`
table. Tasks stored here fire on the PC (persistent toast + UI banner) and on
the companion phone (local exact alarm) via the internal TaskAlarmScheduler.
"""

from __future__ import annotations

from datetime import datetime

MAX_TITLE_LEN = 200


def _sanitise(text: str, max_len: int = MAX_TITLE_LEN) -> str:
    return (
        text.replace("\n", " ")
            .replace("\r", "")
            .strip()
    )[:max_len]


def reminder(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """Tool handler: schedule a reminder at a specific date/time."""
    date_str = parameters.get("date", "").strip()
    time_str = parameters.get("time", "").strip()
    message  = parameters.get("message", "Reminder").strip()

    if not date_str or not time_str:
        return "I need both a date and a time to set a reminder."

    try:
        target_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        return "I couldn't parse that date or time. Please use YYYY-MM-DD and HH:MM."

    if target_dt <= datetime.now():
        return "That time has already passed — I can't set a reminder in the past."

    title = _sanitise(message)

    try:
        from persistence.repository import Repository

        task = Repository().add_scheduled_task(
            title=title,
            due_at=target_dt.isoformat(),
            source="voice",
        )
    except Exception as e:
        print(f"[Reminder] [FAIL] Could not store reminder: {e}")
        return "Something went wrong while scheduling the reminder."

    # Kick the scheduler so very short reminders (< poll interval) still work.
    try:
        from core.task_alarm import get_scheduler

        get_scheduler().fire_now(task["id"])
    except Exception:
        pass

    if player:
        player.write_log(f"[Reminder] [OK] {date_str} {time_str} — {title[:40]}")

    friendly_time = target_dt.strftime("%B %d at %I:%M %p")
    return f"Reminder set for {friendly_time}."
