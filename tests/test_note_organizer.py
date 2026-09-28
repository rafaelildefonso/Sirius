"""Behaviour tests for companion note routing without vault-content reads."""
import asyncio
from pathlib import Path

import pytest

from actions import note_organizer


@pytest.fixture(autouse=True)
def _default_notes_subpath(monkeypatch):
    # Tests use the conventional subfolder independent of a developer's local
    # Obsidian configuration.
    monkeypatch.setattr(note_organizer, "_get_config", lambda _key, default="": default)


class _FakeLlm:
    def __init__(self, response: str):
        self.response = response

    def generate(self, _prompt: str) -> str:
        return self.response


def _organize(tmp_path: Path, **kwargs):
    return asyncio.run(note_organizer.organize_note(vault_path=str(tmp_path), **kwargs))


def test_appends_plain_markdown_to_selected_existing_document(tmp_path, monkeypatch):
    notes = tmp_path / "Anotações"
    notes.mkdir()
    target = notes / "Ideias.md"
    target.write_text("conteúdo existente", encoding="utf-8")

    def fail_if_read(*_args, **_kwargs):
        raise AssertionError("o organizador não pode ler documentos existentes")

    monkeypatch.setattr(Path, "read_text", fail_if_read)
    result = _organize(tmp_path, title="IA binária", content="tokens 0 ou 1", category="ideia",
                       llm_client=_FakeLlm('{"file":"Ideias.md","summary":"x","tags":["ia"]}'))

    assert result.target == target
    saved = target.open(encoding="utf-8").read()
    assert "## IA binária" in saved
    assert "tokens 0 ou 1" in saved
    assert "title:" not in saved and "ai_summary:" not in saved and "tags:" not in saved


def test_unmatched_note_uses_one_inbox_not_a_title_file(tmp_path):
    notes = tmp_path / "Anotações"
    notes.mkdir()
    (notes / "Cursos.md").write_text("", encoding="utf-8")
    result = _organize(tmp_path, title="IA binária", content="tokens 0 ou 1", category="ideia",
                       llm_client=_FakeLlm('{"file":""}'))
    assert result.target == notes / "Caixa de entrada.md"
    assert result.target.exists()
    assert not (notes / "IA binária.md").exists()


def test_images_are_registered_only_in_images_document(tmp_path):
    paths = note_organizer.save_images(str(tmp_path), [("foto?.png", b"png")])
    notes = tmp_path / "Anotações"
    images = notes / "Imagens.md"
    assert len(paths) == 1 and paths[0].exists()
    assert paths[0].parent.name == "_attachments"
    body = images.read_text(encoding="utf-8")
    assert "![](_attachments/foto_.png)" in body
