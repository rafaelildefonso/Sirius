import dashboard.server as server
import persistence.repository as repository


class FakeRepository:
    def __init__(self, task):
        self.task = task
        self.add_calls = 0
        self.update_kwargs = None

    def get_scheduled_task(self, task_id):
        return self.task if self.task and task_id == self.task["id"] else None

    def add_scheduled_task(self, **kwargs):
        self.add_calls += 1
        self.task = {"id": kwargs["task_id"], **kwargs, "status": "pending"}
        return self.task

    def complete_scheduled_task(self, task_id):
        return False

    def update_scheduled_task(self, task_id, **kwargs):
        self.update_kwargs = kwargs
        self.task.update(
            {key: value for key, value in kwargs.items() if key != "clear_notes"}
        )
        if kwargs.get("clear_notes"):
            self.task["notes"] = None
        return True


def test_quick_task_retry_returns_existing_task(monkeypatch):
    task = {
        "id": "task-1",
        "title": "Revisar",
        "due_at": "2026-11-07T18:00:00",
        "status": "pending",
    }
    repo = FakeRepository(task)
    monkeypatch.setattr(repository, "Repository", lambda: repo)

    result = server._create_quick_task(
        {"id": "task-1", "title": "Revisar", "due_at": "2026-11-07T18:00:00"}
    )

    assert result == task
    assert repo.add_calls == 0


def test_quick_task_sync_persists_simulated_call_preference(monkeypatch):
    repo = FakeRepository(None)
    monkeypatch.setattr(repository, "Repository", lambda: repo)

    result = server._create_quick_task(
        {
            "id": "task-call-1",
            "title": "Dentista",
            "due_at": "2026-11-15T09:00:00",
            "sirius_call_enabled": True,
        }
    )

    assert result["sirius_call_enabled"] is True


def test_task_edit_sync_updates_simulated_call_preference(monkeypatch):
    repo = FakeRepository({
        "id": "task-call-2",
        "title": "Dentista",
        "due_at": "2026-11-15T09:00:00",
        "status": "pending",
        "sirius_call_enabled": False,
    })
    monkeypatch.setattr(repository, "Repository", lambda: repo)

    ok, _, new_task = server._edit_quick_task({
        "task_id": "task-call-2",
        "sirius_call_enabled": True,
    })

    assert ok is True
    assert new_task["sirius_call_enabled"] is True


def test_legacy_date_range_quick_task_is_inferred(monkeypatch):
    repo = FakeRepository(None)
    monkeypatch.setattr(repository, "Repository", lambda: repo)

    result = server._create_quick_task(
        {
            "id": "range-1",
            "title": "Enviar relatório",
            # Older app versions omitted is_date_range for queued ranges.
            "start_date": "2026-11-08T00:00:00.000",
            "end_date": "2026-11-10T00:00:00.000",
        }
    )

    assert result is not None
    assert result["is_date_range"] is True
    assert result["due_at"] is None
    assert result["start_date"] == "2026-11-08"
    assert result["end_date"] == "2026-11-10"


def test_quick_task_accepts_legacy_unix_millisecond_due_at(monkeypatch):
    repo = FakeRepository(None)
    monkeypatch.setattr(repository, "Repository", lambda: repo)

    result = server._create_quick_task(
        {
            "id": "unix-1",
            "title": "Ligar para cliente",
            "due_at": 1794139200000,
        }
    )

    assert result is not None
    assert result["due_at"].startswith("2026-11-08T")


def test_legacy_camel_case_nested_quick_task_is_accepted(monkeypatch):
    repo = FakeRepository(None)
    monkeypatch.setattr(repository, "Repository", lambda: repo)

    result = server._create_quick_task(
        {
            "task": {
                "remoteId": "nested-1",
                "name": "Reunião",
                "dueAt": "2026-11-08T14:00:00.000",
            }
        }
    )

    assert result is not None
    assert result["id"] == "nested-1"
    assert result["title"] == "Reunião"


def test_done_retry_succeeds_when_task_is_already_done(monkeypatch):
    repo = FakeRepository({"id": "task-1", "status": "done"})
    monkeypatch.setattr(repository, "Repository", lambda: repo)

    assert server._update_quick_task("task-1", "done") is True


def test_edit_retry_succeeds_when_done_task_already_has_requested_values(
    monkeypatch,
):
    task = {
        "id": "task-1",
        "title": "Revisar",
        "due_at": "2026-11-07T18:00:00",
        "notes": None,
        "status": "done",
    }
    repo = FakeRepository(task)
    monkeypatch.setattr(repository, "Repository", lambda: repo)

    ok, old_task, new_task = server._edit_quick_task(
        {
            "task_id": "task-1",
            "title": "Revisar",
            "due_at": "2026-11-07T18:00:00",
            "notes": None,
        }
    )

    assert ok is True
    assert old_task == task
    assert new_task == task


def test_task_edit_can_clear_notes(monkeypatch):
    task = {
        "id": "task-1",
        "title": "Revisar",
        "due_at": "2026-11-07T18:00:00",
        "notes": "remover",
        "status": "pending",
    }
    repo = FakeRepository(task)
    monkeypatch.setattr(repository, "Repository", lambda: repo)

    ok, _, new_task = server._edit_quick_task(
        {
            "task_id": "task-1",
            "title": "Revisar",
            "due_at": "2026-11-07T18:00:00",
            "notes": None,
        }
    )

    assert ok is True
    assert repo.update_kwargs["clear_notes"] is True
    assert new_task["notes"] is None
