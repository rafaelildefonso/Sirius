"""Shutdown endpoint tests use a fake OS action; no real computer is shut down."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from actions.computer_power import request_shutdown
from dashboard.server import DashboardServer


def _paired_server(monkeypatch):
    # Prevent DashboardServer from consulting the user's external config folder.
    monkeypatch.setattr(DashboardServer, "_load_trusted_devices", lambda self: None)
    server = DashboardServer()
    server._trusted_devices["phone-a"] = {"token": "paired-token-a", "session_key": "ABCDEF"}
    server._device_sessions["paired-token-a"] = {"session_key": "ABCDEF"}
    return server


def test_shutdown_os_call_is_simulated_and_checks_return_code():
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stderr="")

    request_shutdown(runner=runner, system="Windows")
    assert calls == [(["shutdown", "/s", "/t", "30"], {
        "capture_output": True, "text": True, "timeout": 10,
    })]

    def rejected(command, **kwargs):
        return SimpleNamespace(returncode=1, stderr="Access denied")

    try:
        request_shutdown(runner=rejected, system="Windows")
    except RuntimeError as exc:
        assert "Access denied" in str(exc)
    else:
        raise AssertionError("OS rejection must be reported")


def test_shutdown_requires_the_token_for_that_paired_device(monkeypatch):
    server = _paired_server(monkeypatch)
    client = TestClient(server.app)
    invoked = []
    monkeypatch.setattr("actions.computer_power.request_shutdown", lambda: invoked.append(True))

    response = client.post("/api/device/shutdown", headers={
        "X-Device-ID": "phone-a", "Authorization": "Bearer unrelated-token",
    })
    assert response.status_code == 401
    assert not invoked

    response = client.post("/api/device/shutdown", headers={
        "X-Device-ID": "phone-b", "Authorization": "Bearer paired-token-a",
    })
    assert response.status_code == 401
    assert not invoked

    response = client.post("/api/device/shutdown", headers={
        "X-Device-ID": "phone-a", "Authorization": "Bearer paired-token-a",
    })
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert len(invoked) == 1

    repeated = client.post("/api/device/shutdown", headers={
        "X-Device-ID": "phone-a", "Authorization": "Bearer paired-token-a",
    })
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "already_requested"
    assert len(invoked) == 1


def test_shutdown_failure_is_reported_and_can_be_retried(monkeypatch):
    server = _paired_server(monkeypatch)
    client = TestClient(server.app)
    attempts = []

    def fail_once():
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError("OS refused")

    monkeypatch.setattr("actions.computer_power.request_shutdown", fail_once)
    headers = {"X-Device-ID": "phone-a", "Authorization": "Bearer paired-token-a"}

    failed = client.post("/api/device/shutdown", headers=headers)
    assert failed.status_code == 500
    assert failed.json()["status"] == "failed"
    assert "OS refused" in failed.json()["error"]

    accepted = client.post("/api/device/shutdown", headers=headers)
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"
    assert len(attempts) == 2


def test_ai_tool_schemas_have_no_pc_shutdown_option():
    main_source = open("main.py", encoding="utf-8").read()
    planner_source = open("agent/planner.py", encoding="utf-8").read()
    computer_settings_source = open("actions/computer_settings.py", encoding="utf-8").read()
    game_updater_source = open("actions/game_updater.py", encoding="utf-8").read()

    assert "shutdown_when_done" not in main_source + planner_source + game_updater_source
    computer_tool = main_source.split('"name": "computer_settings"', 1)[1].split(
        '"name": "browser_control"', 1
    )[0]
    assert '"shutdown"' not in computer_tool
    assert '"shutdown":' not in computer_settings_source
    assert "def shutdown_computer" not in computer_settings_source
    # shutdown_sirius is intentionally separate and exits the SIRIUS process.
    assert '"name": "shutdown_sirius"' in main_source


def test_generic_runner_guard_blocks_common_explicit_poweroff_commands():
    from actions.system_power_guard import contains_explicit_shutdown, reject_explicit_shutdown

    for sample in (
        "shutdown /s /t 0",
        "shutdown -s -t 0",
        "systemctl poweroff",
        "Stop-Computer -Force",
        "ctypes.windll.user32.ExitWindowsEx(0, 0)",
        "osascript -e 'tell app \"System Events\" to shut down'",
    ):
        assert contains_explicit_shutdown(sample)
        try:
            reject_explicit_shutdown(sample)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Expected shutdown rejection for: {sample}")
