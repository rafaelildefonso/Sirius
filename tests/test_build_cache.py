from __future__ import annotations

import sys
from pathlib import Path

import build_backend
import build_headless


def test_backend_fingerprint_is_stable() -> None:
    first, first_environment = build_backend._compute_backend_hash("dev")
    second, second_environment = build_backend._compute_backend_hash("dev")

    assert first == second
    assert first_environment == second_environment


def test_source_fingerprint_files_exclude_runtime_data(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    secret = tmp_path / "api_keys.json"
    database = tmp_path / "memory.db"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    secret.write_text("{\"token\": \"secret\"}\n", encoding="utf-8")
    database.write_bytes(b"database")

    files = list(build_backend._iter_files([tmp_path], suffixes={".py"}))

    assert files == [source]


def test_workpath_requires_matching_environment() -> None:
    environment = {"python": "3.11", "profile": "dev"}
    state = {"schema": build_backend.CACHE_SCHEMA, "environment": environment}

    assert build_backend._workpath_is_reusable(state, environment)
    assert not build_backend._workpath_is_reusable(state, {"python": "3.12", "profile": "dev"})


def test_parse_args_supports_profiles(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["build_backend.py", "--cached", "--profile=release"])

    use_cache, force, clean, skip_lint, profile = build_backend._parse_args()

    assert use_cache
    assert not force
    assert not clean
    assert not skip_lint
    assert profile == "release"


def test_headless_fingerprint_is_stable() -> None:
    first, first_environment = build_headless._fingerprint("dev")
    second, second_environment = build_headless._fingerprint("dev")

    assert first == second
    assert first_environment == second_environment
