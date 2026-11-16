# -*- coding: utf-8 -*-
"""Tests for the recurring task definitions + generator (core/recurring_tasks.py)."""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.recurring_tasks import (
    RecurringTaskGenerator,
    create_recurring,
    is_generation_day,
    normalize_time_of_day,
    parse_weekdays,
)
from persistence.database import Database
from persistence.repository import Repository


@pytest.fixture
def db_path() -> Iterator[Path]:
    tmp = tempfile.mktemp(suffix=".db")
    yield Path(tmp)
    try:
        os.unlink(tmp)
    except OSError:
        pass
    try:
        os.unlink(tmp + "-wal")
    except OSError:
        pass
    try:
        os.unlink(tmp + "-shm")
    except OSError:
        pass


@pytest.fixture
def db(db_path: Path) -> Database:
    Database.reset_instance()
    return Database.get_instance(db_path=db_path)


@pytest.fixture
def repo(db: Database) -> Repository:
    return Repository(db=db)


@pytest.fixture
def gen(repo: Repository) -> RecurringTaskGenerator:
    """Generator wired to the tmp DB with no notification side effects."""
    return RecurringTaskGenerator(repo=repo, on_generate=lambda task: None)


def _backdate_created(repo: Repository, rec_id: str, days_ago: int) -> None:
    created = (date.today() - timedelta(days=days_ago)).isoformat() + "T07:00:00"
    repo.db.execute("UPDATE recurring_tasks SET created_at = ? WHERE id = ?", (created, rec_id))
    repo.db.commit()


# ---------------------------------------------------------------------------
# Payload parsing helpers
# ---------------------------------------------------------------------------

def test_parse_weekdays_flexible():
    assert parse_weekdays("mon,fri") == [0, 4]
    assert parse_weekdays(["sabado", "dom"]) == [5, 6]
    assert parse_weekdays("0, 3, 6") == [0, 3, 6]
    assert parse_weekdays("xyz") is None
    assert parse_weekdays("") is None


def test_normalize_time_of_day():
    assert normalize_time_of_day("09:30") == "09:30"
    assert normalize_time_of_day("9:05") == "09:05"
    assert normalize_time_of_day("0800") == "08:00"
    assert normalize_time_of_day("24:00") is None
    assert normalize_time_of_day("abc") is None


def test_create_recurring_validation(repo):
    with pytest.raises(ValueError):
        create_recurring({"title": "x", "recurrence_type": "weekly"})
    with pytest.raises(ValueError):
        create_recurring({"title": "x", "recurrence_type": "monthly", "month_day": 40})
    with pytest.raises(ValueError):
        create_recurring({"title": "", "recurrence_type": "daily", "time": "09:00"})
    with pytest.raises(ValueError):
        create_recurring({"title": "x", "recurrence_type": "interval", "interval_days": 0})


def test_mobile_recurring_definition_keeps_its_local_id(repo):
    rec = create_recurring(
        {
            "id": "mobile-recurring-id",
            "title": "Phone task",
            "recurrence_type": "daily",
            "time_of_day": "09:00",
            "start_from": date.today().isoformat(),
        },
        source="mobile",
        rec_id="mobile-recurring-id",
    )

    assert rec["id"] == "mobile-recurring-id"
    assert rec["source"] == "mobile"


def test_mobile_compact_recurring_dates_are_accepted(repo):
    rec = create_recurring(
        {
            "id": "legacy-date-recurring",
            "title": "Tarefa legada",
            "recurrence_type": "daily",
            "period_days": 2,
            "start_from": "20261108",
            "end_date": "20261110",
        },
        source="mobile",
        rec_id="legacy-date-recurring",
    )

    assert rec["start_from"] == "2026-11-08"
    assert rec["end_date"] == "2026-11-10"


# ---------------------------------------------------------------------------
# Occurrence rules
# ---------------------------------------------------------------------------

def test_generation_rules_per_type(repo):
    # daily
    rec = repo.add_recurring_task(title="Daily", recurrence_type="daily")
    assert is_generation_day(rec, date(2026, 11, 15))

    # weekly mon/fri
    rec = repo.add_recurring_task(
        title="Weekly",
        recurrence_type="weekly",
        weekdays=[0, 4],
        start_from="2026-11-01",
    )
    assert is_generation_day(rec, date(2026, 11, 2))   # Monday
    assert is_generation_day(rec, date(2026, 11, 6))   # Friday
    assert not is_generation_day(rec, date(2026, 11, 1))  # Sunday

    # interval anchored on start_from
    rec = repo.add_recurring_task(
        title="Interval", recurrence_type="interval",
        interval_days=3, start_from="2026-11-01",
    )
    assert is_generation_day(rec, date(2026, 11, 1))
    assert is_generation_day(rec, date(2026, 11, 7))
    assert not is_generation_day(rec, date(2026, 11, 5))
    assert not is_generation_day(rec, date(2026, 10, 31))  # before anchor

    # monthly, clamped to the month length (31 -> Feb 28)
    rec = repo.add_recurring_task(title="Monthly", recurrence_type="monthly", month_day=31)
    assert is_generation_day(rec, date(2026, 11, 30))  # Nov has 30 days -> 30
    assert is_generation_day(rec, date(2027, 2, 28))   # Feb 2027 -> 28
    assert not is_generation_day(rec, date(2026, 11, 15))


# ---------------------------------------------------------------------------
# Instance generation
# ---------------------------------------------------------------------------

def test_daily_first_run_future_time_generates_today(repo, gen):
    rec = repo.add_recurring_task(
        title="Future", recurrence_type="daily",
        time_of_day=(datetime.now() + timedelta(hours=2)).strftime("%H:%M"),
    )
    assert gen.generate_blocking() == 1
    tasks = [t for t in repo.list_scheduled_tasks() if t["recurrence_id"] == rec["id"]]
    assert len(tasks) == 1
    task = tasks[0]
    assert task["status"] == "pending"
    assert task["source"] == "recurring"
    assert date.fromisoformat(task["due_at"][:10]) == date.today()
    assert task["due_at"][11:16] == rec["time_of_day"]


def test_daily_creation_day_time_passed_waits_for_tomorrow(repo, gen):
    rec = repo.add_recurring_task(
        title="Late", recurrence_type="daily",
        time_of_day=(datetime.now() - timedelta(hours=2)).strftime("%H:%M"),
    )
    gen.generate_blocking()
    assert not [t for t in repo.list_scheduled_tasks() if t["recurrence_id"] == rec["id"]]


def test_offline_catchup_generates_most_recent_day_once(repo, gen):
    rec = repo.add_recurring_task(
        title="Catchup", recurrence_type="daily", time_of_day="08:00",
        start_from=(date.today() - timedelta(days=5)).isoformat(),
    )
    _backdate_created(repo, rec["id"], days_ago=5)  # definition is 5 days old
    gen.generate_blocking()
    tasks = [t for t in repo.list_scheduled_tasks() if t["recurrence_id"] == rec["id"]]
    assert len(tasks) == 1
    assert tasks[0]["due_at"][:10] == date.today().isoformat()
    # running again must not duplicate
    gen.generate_blocking()
    tasks = [t for t in repo.list_scheduled_tasks() if t["recurrence_id"] == rec["id"]]
    assert len(tasks) == 1


def test_new_day_removes_previous_pending_keeps_done(repo, gen):
    rec = repo.add_recurring_task(
        title="NoDup", recurrence_type="daily",
        time_of_day=(datetime.now() + timedelta(hours=2)).strftime("%H:%M"),
    )
    gen.generate_blocking()
    tasks = [t for t in repo.list_scheduled_tasks() if t["recurrence_id"] == rec["id"]]
    done_id = tasks[0]["id"]
    repo.complete_scheduled_task(done_id)

    # A stale pending instance from an earlier day is removed when the new
    # generation runs; the completed one stays as history.
    stale = repo.add_scheduled_task(
        "stale", due_at=(date.today() - timedelta(days=1)).isoformat(),
        source="recurring", recurrence_id=rec["id"],
    )
    repo.set_recurring_last_generated(rec["id"], (date.today() - timedelta(days=1)).isoformat())
    gen.generate_blocking()

    tasks = [t for t in repo.list_scheduled_tasks() if t["recurrence_id"] == rec["id"]]
    ids = {t["id"] for t in tasks}
    assert done_id in ids            # done instance preserved (history)
    assert stale["id"] not in ids    # pending instance removed
    pending = [t for t in tasks if t["status"] == "pending"]
    assert len(pending) == 1
    assert pending[0]["due_at"][:10] == date.today().isoformat()


def test_period_instance_uses_date_range_pipeline(repo, gen):
    rec = repo.add_recurring_task(
        title="Period", recurrence_type="weekly", weekdays=[date.today().weekday()],
        period_days=2,
    )
    gen.generate_blocking()
    tasks = [t for t in repo.list_scheduled_tasks() if t["recurrence_id"] == rec["id"]]
    assert len(tasks) == 1
    task = tasks[0]
    assert task["is_date_range"] == 1
    assert task["due_at"] is None
    assert task["start_date"] == date.today().isoformat()
    assert task["end_date"] == (date.today() + timedelta(days=1)).isoformat()


def test_mobile_owned_recurring_definition_is_not_generated_on_pc(repo, gen):
    repo.add_recurring_task(
        title="Mobile owned",
        recurrence_type="daily",
        time_of_day="09:00",
        source="mobile",
    )

    assert gen.generate_blocking() == 0
    assert not [
        task for task in repo.list_scheduled_tasks()
        if task.get("source") == "recurring"
    ]


def test_delete_recurring_removes_definition_and_pending(repo, gen):
    rec = repo.add_recurring_task(
        title="DelMe", recurrence_type="daily",
        time_of_day=(datetime.now() + timedelta(hours=2)).strftime("%H:%M"),
    )
    gen.generate_blocking()
    result = repo.delete_recurring_task(rec["id"])
    assert result["definition_deleted"] is True
    assert result["instances_deleted"] >= 1
    assert repo.get_recurring_task(rec["id"]) is None
    assert not [t for t in repo.list_scheduled_tasks() if t["recurrence_id"] == rec["id"]]


def test_disabled_recurrence_is_skipped(repo, gen):
    rec = repo.add_recurring_task(
        title="Paused", recurrence_type="daily", time_of_day="08:00",
        start_from=(date.today() - timedelta(days=5)).isoformat(),
        enabled=False,
    )
    gen.generate_blocking()
    assert not [t for t in repo.list_scheduled_tasks() if t["recurrence_id"] == rec["id"]]
