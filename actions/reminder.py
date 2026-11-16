"""
reminder.py — Voice/LLM reminder tools backed by the unified `scheduled_tasks`
table. Tasks stored here fire on the PC (persistent toast + UI banner) and on
the companion phone (local exact alarm) via the internal TaskAlarmScheduler.

`recurring_reminder` creates/edits recurring definitions in `recurring_tasks`
that automatically generate concrete tasks on their recurrence days; the PC
owns the definitions and generated tasks sync to the phone via the dashboard
pull endpoint (docs/SYNC.md).
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


def recurring_reminder(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """Tool handler: create/list/delete recurring tasks (PC-side definitions)."""
    from core.recurring_tasks import (
        compute_next_occurrence_iso,
        create_recurring,
        describe_recurring,
        update_recurring,
    )

    action = str(parameters.get("action") or "create").strip().lower()
    try:
        from persistence.repository import Repository

        repo = Repository()

        if action == "list":
            recs = repo.list_recurring_tasks()
            if not recs:
                return "There are no recurring tasks yet."
            lines = []
            for rec in recs:
                state = "ativa" if rec.get("enabled") else "pausada"
                nxt = compute_next_occurrence_iso(rec) if rec.get("enabled") else "—"
                lines.append(f"- {rec['title']} (id={rec['id']}, {state}): {describe_recurring(rec)}; próxima: {nxt}")
            return "Recurring tasks:\n" + "\n".join(lines)

        if action == "delete":
            rec_id = str(parameters.get("id") or parameters.get("recurrence_id") or "").strip()
            if not rec_id:
                return "I need the recurring task id — call this tool with action='list' first."
            if not repo.get_recurring_task(rec_id):
                return f"No recurring task found with id {rec_id}. Call this tool with action='list' to see the ids."
            result = repo.delete_recurring_task(rec_id)
            if player:
                player.write_log(f"[RecurringReminder] [DELETE] {rec_id} ({result['instances_deleted']} pending)")
            return "Recurring task deleted."

        if action == "update":
            rec_id = str(parameters.get("id") or parameters.get("recurrence_id") or "").strip()
            if not rec_id:
                return "I need the recurring task id to update — call this tool with action='list' first."
            payload = {k: v for k, v in parameters.items() if k not in ("action", "id", "recurrence_id")}
            rec = update_recurring(rec_id, payload)
            if player:
                player.write_log(f"[RecurringReminder] [UPDATE] {rec_id}")
            return f"Recurring task updated: {rec['title']} — {describe_recurring(rec)}."

        # create
        payload = {k: v for k, v in parameters.items() if k != "action"}
        rec = create_recurring(payload, source="voice")
        if player:
            player.write_log(f"[RecurringReminder] [OK] {rec['title']} ({rec['recurrence_type']})")
        desc = describe_recurring(rec)
        nxt = rec.get("next_occurrence")
        return f"Recurring task created: '{rec['title']}' ({desc}). Next occurrence: {nxt}."
    except ValueError as e:
        return str(e)
    except Exception as e:
        print(f"[RecurringReminder] [FAIL] {e}")
        return "Something went wrong while creating the recurring task."
