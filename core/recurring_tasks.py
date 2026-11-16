"""
recurring_tasks.py — Recurring task engine.

Recurring definitions live in the `recurring_tasks` table (daily / specific
weekdays / every-N-days / day-of-month). A background daemon generates the
concrete instance in `scheduled_tasks` for each generation day:

  1. If a generation run already happened today, skip.
  2. Delete the previous pending/notified instance of the same recurrence
     (prevents duplicate tasks when the next day arrives).
  3. Create today's instance — timed ('HH:MM' -> due_at) or a period
     (date-range lasting `period_days`, reusing the date-range pipeline).
  4. If the recurrence missed a day while SIRIUS was offline (only generates
     for days <= today), catch up by generating the most recent missed
     occurrence — mirroring the delayed-fire behavior of one-off reminders.
  5. Done/dismissed instances are never touched (history, auto-cleaned after
     7 days by cleanup_finished_scheduled_tasks).

Scheduled tasks created here carry `source='recurring'` and
`recurrence_id=<definition id>`, so they flow to the companion phone through
the regular device pull sync.
"""

from __future__ import annotations

import calendar
import logging
import threading
from datetime import date, datetime, time, timedelta
from typing import Optional

logger = logging.getLogger("core.recurring_tasks")

CHECK_INTERVAL_SECS = 60
MAX_CATCHUP_LOOKBACK_DAYS = 730

RECURRENCE_TYPES = ("daily", "weekly", "interval", "monthly")

WEEKDAY_ALIASES: dict[str, int] = {
    "mon": 0, "monday": 0, "segunda": 0, "seg": 0,
    "tue": 1, "tues": 1, "tuesday": 1, "ter": 1, "terca": 1, "terça": 1,
    "wed": 2, "wednesday": 2, "qua": 2, "quarta": 2,
    "thu": 3, "thursday": 3, "qui": 3, "quinta": 3,
    "fri": 4, "friday": 4, "sex": 4, "sexta": 4,
    "sat": 5, "saturday": 5, "sab": 5, "sabado": 5, "sábado": 5,
    "sun": 6, "sunday": 6, "dom": 6, "domingo": 6,
}

# Default time when a timed instance has no explicit time (used by the voice tool).
DEFAULT_TIME_OF_DAY = "09:00"

# ---------------------------------------------------------------------------
# Parsing / normalisation helpers (shared by REST API and the voice tool)
# ---------------------------------------------------------------------------

def parse_weekdays(value) -> Optional[list[int]]:
    """Accept a list ('mon','wed'... / ints 0-6) or comma/space string; return
    a sorted list of Python weekday indices (0=Monday) or None if invalid."""
    if value is None:
        return None
    items: list[str] = []
    if isinstance(value, (list, tuple)):
        items = [str(v).strip().lower() for v in value]
    else:
        cleaned = str(value).strip().strip("[]")
        if not cleaned:
            return None
        items = [p.strip().lower() for p in cleaned.replace(";", ",").split(",") if p.strip()]
    days: set[int] = set()
    for item in items:
        if item.isdigit():
            idx = int(item)
            if 0 <= idx <= 6:
                days.add(idx)
        else:
            idx = WEEKDAY_ALIASES.get(item)
            if idx is not None:
                days.add(idx)
    if not days:
        return None
    return sorted(days)


def normalize_time_of_day(value) -> Optional[str]:
    """Normalize 'HH:MM' (accepts '9:00', 2400h-like '0900'). Returns None if invalid."""
    if value is None:
        return None
    text = str(value).strip().replace("h", ":")
    if text.isdigit() and len(text) in (3, 4):
        text = f"{text[:-2].zfill(2)}:{text[-2:]}"
    try:
        hh, mm = text.split(":")
        hh, mm = int(hh), int(mm)
    except (ValueError, AttributeError):
        return None
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return f"{hh:02d}:{mm:02d}"


def _parse_date(value) -> Optional[date]:
    if not value:
        return None
    text = str(value).strip()
    # Companion versions before the ISO contract used YYYYMMDD for recurring
    # date fields. Keep accepting that format so queued definitions migrate.
    if len(text) == 8 and text.isdigit():
        try:
            return datetime.strptime(text, "%Y%m%d").date()
        except ValueError:
            return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_created_date(rec: dict) -> Optional[date]:
    raw = rec.get("created_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw)).date()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Occurrence rules
# ---------------------------------------------------------------------------

def is_generation_day(rec: dict, day: date) -> bool:
    """True if a new instance must be generated on `day` for this definition."""
    start_from = _parse_date(rec.get("start_from")) or _parse_created_date(rec)
    if start_from and day < start_from:
        return False
    end_date = _parse_date(rec.get("end_date"))
    if end_date and day > end_date:
        return False

    rtype = str(rec.get("recurrence_type") or "").lower()
    if rtype == "daily":
        return True
    if rtype == "weekly":
        weekdays = rec.get("weekdays")
        return bool(weekdays) and day.weekday() in weekdays
    if rtype == "interval":
        interval = max(1, int(rec.get("interval_days") or 1))
        anchor = start_from
        if anchor is None:
            return False
        return (day - anchor).days >= 0 and (day - anchor).days % interval == 0
    if rtype == "monthly":
        month_day = int(rec.get("month_day") or 1)
        last_day = calendar.monthrange(day.year, day.month)[1]
        return day.day == min(month_day, last_day)
    return False


def compute_next_generation_day(rec: dict, from_day: date, max_days: int = 400) -> Optional[date]:
    """First generation day D with from_day <= D (or None)."""
    start_from = _parse_date(rec.get("start_from"))
    first = max(from_day, start_from) if start_from else from_day
    candidate = first
    for _ in range(max_days):
        if is_generation_day(rec, candidate):
            return candidate
        candidate += timedelta(days=1)
    return None


def compute_next_occurrence_iso(rec: dict, from_day: Optional[date] = None) -> Optional[str]:
    """ISO date of the next upcoming generated instance (for UI/tool display)."""
    ref = from_day if from_day is not None else date.today() + timedelta(days=1)
    nxt = compute_next_generation_day(rec, ref)
    return nxt.isoformat() if nxt else None


# ---------------------------------------------------------------------------
# Payload-based create/update (used by dashboard REST and the voice tool)
# ---------------------------------------------------------------------------

def create_recurring(
    payload: dict,
    source: str = "pc",
    device_id: Optional[str] = None,
    rec_id: Optional[str] = None,
) -> dict:
    """Validate a payload and persist a new recurring definition.

    Raises ValueError with a user-facing message when the payload is invalid.
    Returns the stored definition dict."""
    from persistence.repository import Repository

    if not isinstance(payload, dict):
        raise ValueError("Invalid payload")

    title = str(payload.get("title") or payload.get("message") or "").strip()
    if not title:
        raise ValueError("Title is required")

    rtype = str(payload.get("recurrence_type") or payload.get("type") or "").strip().lower()
    aliases = {"day": "daily", "todos os dias": "daily", "everyday": "daily",
               "week": "weekly", "semanal": "weekly",
               "interval": "interval", "intervalo": "interval",
               "month": "monthly", "mensal": "monthly"}
    rtype = aliases.get(rtype, rtype)
    if rtype not in RECURRENCE_TYPES:
        raise ValueError(
            "recurrence_type must be one of: " + ", ".join(RECURRENCE_TYPES)
        )

    weekdays = parse_weekdays(payload.get("weekdays"))
    interval_days = payload.get("interval_days")
    month_day = payload.get("month_day")
    time_of_day = normalize_time_of_day(
        payload.get("time_of_day") or payload.get("time")
    )
    period_days = payload.get("period_days")
    try:
        period_days = int(period_days or 0)
    except (TypeError, ValueError):
        raise ValueError("period_days must be a number")
    period_days = max(0, min(365, period_days))

    if rtype == "weekly" and not weekdays:
        raise ValueError("weekly recurrence requires weekdays (e.g. 'mon,wed')")
    if rtype == "interval":
        try:
            interval_days = int(interval_days or payload.get("every_days") or 0)
        except (TypeError, ValueError):
            raise ValueError("interval_days must be a number")
        if interval_days < 1:
            raise ValueError("interval_days must be at least 1")
    if rtype == "monthly":
        try:
            month_day = int(month_day or 0)
        except (TypeError, ValueError):
            raise ValueError("month_day must be a number")
        if not 1 <= month_day <= 31:
            raise ValueError("month_day must be between 1 and 31")
    if not time_of_day:
        time_of_day = DEFAULT_TIME_OF_DAY if period_days == 0 else None

    def _clean_date(name: str) -> Optional[str]:
        value = payload.get(name)
        if not value:
            return None
        parsed = _parse_date(value)
        if parsed is None:
            raise ValueError(f"{name} must be a YYYY-MM-DD date")
        return parsed.isoformat()

    start_from = _clean_date("start_from")
    end_date = _clean_date("end_date")

    rec = Repository().add_recurring_task(
        title=title,
        recurrence_type=rtype,
        weekdays=weekdays if rtype == "weekly" else None,
        interval_days=interval_days if rtype == "interval" else None,
        month_day=month_day if rtype == "monthly" else None,
        time_of_day=time_of_day,
        period_days=period_days,
        notes=(str(payload.get("notes")).strip() or None) if payload.get("notes") else None,
        start_from=start_from,
        end_date=end_date,
        source=source,
        device_id=device_id or None,
        sirius_call_enabled=bool(payload.get("sirius_call_enabled", False)),
        rec_id=rec_id or payload.get("id"),
    )
    if source != "mobile":
        get_generator().kick()
    rec["next_occurrence"] = compute_next_occurrence_iso(rec)
    return rec


def update_recurring(rec_id: str, payload: dict) -> dict:
    """Partial edit of a recurring definition (mirrors update_scheduled_task)."""
    from persistence.repository import Repository

    if not isinstance(payload, dict):
        raise ValueError("Invalid payload")
    repo = Repository()
    existing = repo.get_recurring_task(rec_id)
    if not existing:
        raise ValueError("Recurring task not found")

    kwargs: dict = {}
    if payload.get("title") is not None:
        title = str(payload["title"]).strip()
        if not title:
            raise ValueError("Title cannot be empty")
        kwargs["title"] = title
    if "notes" in payload:
        kwargs["notes"] = str(payload.get("notes")).strip() or None
    if payload.get("weekdays") is not None:
        weekdays = parse_weekdays(payload.get("weekdays"))
        if not weekdays:
            raise ValueError("weekdays invalid (use e.g. 'mon,wed' or 0-6)")
        kwargs["weekdays"] = weekdays
    if payload.get("interval_days") is not None:
        try:
            kwargs["interval_days"] = max(1, int(payload["interval_days"]))
        except (TypeError, ValueError):
            raise ValueError("interval_days must be a number")
    if payload.get("month_day") is not None:
        try:
            md = int(payload["month_day"])
        except (TypeError, ValueError):
            raise ValueError("month_day must be a number")
        if not 1 <= md <= 31:
            raise ValueError("month_day must be between 1 and 31")
        kwargs["month_day"] = md
    if payload.get("time_of_day") is not None or payload.get("time") is not None:
        t = normalize_time_of_day(payload.get("time_of_day") or payload.get("time"))
        if t is None:
            raise ValueError("time_of_day must be HH:MM (24h)")
        kwargs["time_of_day"] = t
    if payload.get("period_days") is not None:
        try:
            kwargs["period_days"] = max(0, min(365, int(payload["period_days"])))
        except (TypeError, ValueError):
            raise ValueError("period_days must be a number")
    if payload.get("start_from") is not None:
        d = _parse_date(payload["start_from"])
        if d is None:
            raise ValueError("start_from must be a YYYY-MM-DD date")
        kwargs["start_from"] = d.isoformat()
    if payload.get("end_date") is not None:
        d = _parse_date(payload["end_date"])
        if d is None:
            raise ValueError("end_date must be a YYYY-MM-DD date")
        kwargs["end_date"] = d.isoformat()
    if payload.get("enabled") is not None:
        kwargs["enabled"] = bool(payload["enabled"])
    if payload.get("sirius_call_enabled") is not None:
        kwargs["sirius_call_enabled"] = str(payload["sirius_call_enabled"]).lower() in ("1", "true", "yes")
    if payload.get("source") == "mobile":
        kwargs["source"] = "mobile"

    if kwargs and not repo.update_recurring_task(rec_id, **kwargs):
        raise ValueError("Could not update recurring task")

    if existing.get("source") != "mobile":
        get_generator().kick()
    rec = repo.get_recurring_task(rec_id)
    rec["next_occurrence"] = compute_next_occurrence_iso(rec)  # type: ignore[union-attr]
    return rec


def describe_recurring(rec: dict) -> str:
    """Human-friendly recurrence description (PT-BR, for toasts/tool replies)."""
    rtype = rec.get("recurrence_type")
    names = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    base = {
        "daily": "todos os dias",
        "weekly": "",
        "interval": f"a cada {rec.get('interval_days', 1)} dia(s)",
        "monthly": f"todo dia {rec.get('month_day', 1)} do mês",
    }.get(rtype, rtype or "")
    if rtype == "weekly":
        days = rec.get("weekdays") or []
        base = "toda " + ", ".join(names[d] for d in days) if days else base
    if rec.get("period_days"):
        base += f", período de {rec['period_days']} dia(s)"
    elif rec.get("time_of_day"):
        base += f", às {rec['time_of_day']}"
    return base


# ---------------------------------------------------------------------------
# Generator daemon
# ---------------------------------------------------------------------------

def _default_on_generate(instance: dict) -> None:
    """Notify pipeline for freshly generated period instances that already
    started today (the midnight DateRangeNotifier already missed them).
    Timed instances are left to the TaskAlarmScheduler 10s tick."""
    if not instance.get("is_date_range"):
        return
    today = date.today().isoformat()
    start = str(instance.get("start_date") or "")[:10]
    end = str(instance.get("end_date") or "9999-12-31")[:10]
    if not (start <= today <= end):
        return
    try:
        import ws_server

        ws_server.notify_date_range_task_alarm(instance)
        from persistence.repository import Repository

        Repository().mark_scheduled_task_notified(instance["id"])
    except Exception as e:
        logger.error("Failed to notify generated period task %s: %s", instance.get("id"), e)


class RecurringTaskGenerator:
    """Daemon thread that materializes recurring definitions into scheduled tasks."""

    def __init__(
        self,
        repo=None,
        on_generate=None,
        check_interval: int = CHECK_INTERVAL_SECS,
    ):
        self._repo = repo
        self._on_generate = on_generate or _default_on_generate
        self._interval = check_interval
        self._stop_event = threading.Event()
        self._kick_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def repo(self):
        if self._repo is None:
            from persistence.repository import Repository

            self._repo = Repository()
        return self._repo

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._kick_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="recurring-tasks")
        self._thread.start()
        logger.info("RecurringTaskGenerator started (every %ss)", self._interval)

    def stop(self) -> None:
        self._stop_event.set()
        self._kick_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def kick(self) -> None:
        """Wake the loop right away (called after create/update from portals)."""
        self._kick_event.set()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as e:
                logger.error("Recurring task generation tick failed: %s", e)
            # Wake early when a create/update requires immediate generation.
            self._kick_event.wait(self._interval)
            self._kick_event.clear()

    def generate_blocking(self) -> int:
        """One synchronous generation pass (mainly used at startup/testing)."""
        return self._tick()

    # -- core ---------------------------------------------------------------

    def _tick(self) -> int:
        today = date.today()
        generated = 0
        try:
            recs = self.repo.list_recurring_tasks(enabled_only=True)
        except Exception as e:
            logger.error("Could not list recurring tasks: %s", e)
            return 0
        for rec in recs:
            try:
                # Mobile-owned definitions are materialized on the phone so
                # recurrence notifications never depend on the PC being online.
                if rec.get("source") == "mobile":
                    continue
                if self._process(rec, today):
                    generated += 1
            except Exception as e:
                logger.error("Recurring generation failed for %s: %s", rec.get("id"), e)
        return generated

    def _process(self, rec: dict, today: date) -> bool:
        """Generate the next missing instance for one definition. Returns True if created."""
        last = _parse_date(rec.get("last_generated_date"))
        if last == today:
            return False

        base = self._resolve_generation_day(rec, last, today)
        if base is None:
            return False

        instance = self._generate_instance(rec, base, last, today)
        if instance is not None:
            past = " (atrasada)" if base < today else ""
            logger.info(
                "Generated %s instance %s for '%s'%s",
                rec.get("recurrence_type"), instance.get("id"), rec.get("title"), past,
            )
        return instance is not None

    def _resolve_generation_day(self, rec: dict, last: Optional[date], today: date) -> Optional[date]:
        """Which day's instance should exist right now?

        The single-instance model (one pending instance per recurrence) means
        the newest unclosed generation day <= today is always the candidate —
        this covers both the regular "a new generation day arrived" case and
        catch-up when SIRIUS was offline on previous generation days.
        """
        window_start = last + timedelta(days=1) if last else None
        return self._latest_generation_day(rec, start=window_start, end=today)

    def _latest_generation_day(self, rec: dict, start: Optional[date] = None, end: Optional[date] = None) -> Optional[date]:
        """Most recent generation day within the window (bounded for safety)."""
        if end is None:
            return None
        if start is None:
            anchor = _parse_date(rec.get("start_from")) or _parse_created_date(rec)
            if anchor:
                start = min(anchor, end)
            else:
                return None
        if (end - start).days > MAX_CATCHUP_LOOKBACK_DAYS:
            start = end - timedelta(days=MAX_CATCHUP_LOOKBACK_DAYS)
        latest = None
        day = start
        while day <= end:
            if is_generation_day(rec, day):
                latest = day
            day += timedelta(days=1)
        return latest

    def _generate_instance(self, rec: dict, base: date, last: Optional[date], today: date) -> Optional[dict]:
        """Delete the stale pending instance, create the new one, bookkeeping."""
        rec_id = rec["id"]

        # First-ever generation happening on creation day with the time already
        # gone: push the first occurrence to the next generation day instead of
        # firing an instant late alarm. (Definitions created earlier behave like
        # offline catch-up and fire — same as one-off reminders.)
        if last is None and base == today and _parse_created_date(rec) == today:
            period_days = int(rec.get("period_days") or 0)
            if period_days == 0 and rec.get("time_of_day"):
                hh, mm = rec["time_of_day"].split(":")
                if datetime.combine(base, time(int(hh), int(mm))) < datetime.now():
                    return None

        # Rule from the product spec: when the next generation day arrives, the
        # previous pending instance of the same recurrence is removed so tasks
        # are never duplicated. Completed ones stay as history.
        removed = self.repo.delete_pending_recurrence_instances(rec_id)

        period_days = int(rec.get("period_days") or 0)
        notes = rec.get("notes")

        if period_days > 0:
            end = base + timedelta(days=period_days - 1)
            instance = self.repo.add_scheduled_task(
                title=rec["title"],
                due_at=None,
                notes=notes,
                source="recurring",
                start_date=base.isoformat(),
                end_date=end.isoformat(),
                is_date_range=True,
                recurrence_id=rec_id,
                sirius_call_enabled=False,
            )
        else:
            hh, mm = (rec.get("time_of_day") or DEFAULT_TIME_OF_DAY).split(":")
            due = datetime.combine(base, time(int(hh), int(mm))).isoformat()
            instance = self.repo.add_scheduled_task(
                title=rec["title"],
                due_at=due,
                notes=notes,
                source="recurring",
                recurrence_id=rec_id,
                sirius_call_enabled=bool(rec.get("sirius_call_enabled")),
            )

        # last_generated_date is the *run* date (real today), while `base` is the
        # generated instance's day — the catch-up window is bounded by it.
        self.repo.set_recurring_last_generated(rec_id, date.today().isoformat())

        try:
            self._on_generate(instance)
        except Exception as e:
            logger.error("on_generate failed for %s: %s", instance.get("id"), e)

        if removed:
            logger.debug("Removed %s stale instance(s) for recurrence %s", removed, rec_id)
        return instance


# --------------------------------------------------------------------------
# Module-level singleton (same pattern as task_alarm.py / date_range_notifier)
# --------------------------------------------------------------------------

_generator: Optional[RecurringTaskGenerator] = None
_singleton_lock = threading.Lock()


def get_generator() -> RecurringTaskGenerator:
    global _generator
    if _generator is None:
        with _singleton_lock:
            if _generator is None:
                _generator = RecurringTaskGenerator()
    return _generator


def start_recurring() -> RecurringTaskGenerator:
    gen = get_generator()
    gen.generate_blocking()  # catch up right away if a day was missed while offline
    gen.start()
    return gen
