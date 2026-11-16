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
    monkeypatch.setattr(note_organizer, "_AI_COOLDOWN_UNTIL", 0.0)
    # Keep these filesystem behavior tests isolated from a developer's live
    # Sirius database while exercising the same delivery-ledger contract.
    deliveries = {}

    def get_delivery(source_uuid):
        return deliveries.get(source_uuid)

    def record_delivery(source_uuid, fingerprint, result):
        if source_uuid:
            deliveries[source_uuid] = (fingerprint, result)

    monkeypatch.setattr(note_organizer, "_delivery_for_uuid", get_delivery)
    monkeypatch.setattr(note_organizer, "_record_delivery", record_delivery)


class _FakeLlm:
    def __init__(self, response: str):
        self.response = response

    def generate(self, _prompt: str) -> str:
        return self.response


class _FailingLlm:
    def generate(self, _prompt: str) -> str:
        raise RuntimeError("model unavailable")


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


def test_classification_available_before_sync_writes_normalized_searchable_tags(tmp_path):
    notes = tmp_path / "Anotações"
    notes.mkdir()
    target = notes / "Ideias.md"
    target.touch()
    result = _organize(
        tmp_path, title="Projeto", content="Anotação sobre IA", category="ideia",
        ai_summary="Resumo curto", ai_tags=["#Inteligência Artificial", "inteligência   artificial", "IA/Produto?"],
        source_uuid="note-before-classification",
        llm_client=_FakeLlm('{"file":"Ideias.md"}'),
    )
    saved = target.read_text(encoding="utf-8")
    assert result.target == target
    assert "> 💡 Resumo curto" in saved
    assert "#inteligência-artificial" in saved
    assert "#ia/Produto" not in saved  # tags are normalized to lowercase
    assert "#ia/produto" in saved
    assert saved.count("#inteligência-artificial") == 1


def test_late_classification_updates_original_document_without_copying_note(tmp_path):
    notes = tmp_path / "Anotações"
    notes.mkdir()
    target = notes / "Reuniões.md"
    target.touch()
    kwargs = dict(title="Reunião", content="Decisões sobre o projeto Sirius", category="reunião",
                  source_uuid="late-classification-uuid")

    initial = _organize(tmp_path, **kwargs, llm_client=_FakeLlm('{"file":"Reuniões.md"}'))
    updated = _organize(
        tmp_path, **kwargs, ai_summary="Decisões e próximos passos", ai_tags=["projeto", "sirius"],
        llm_client=_FakeLlm('{"file":"Reuniões.md"}'),
    )
    repeated = _organize(
        tmp_path, **kwargs, ai_summary="Decisões e próximos passos", ai_tags=["projeto", "sirius"],
        llm_client=_FakeLlm('{"file":"Reuniões.md"}'),
    )
    saved = target.read_text(encoding="utf-8")
    assert initial.target == updated.target == repeated.target == target
    assert updated.duplicate and repeated.duplicate
    assert saved.count("## Reunião") == 1
    assert saved.count("Decisões sobre o projeto Sirius") == 1
    assert saved.count("<!-- sirius-classification:late-classification-uuid -->") == 1
    assert "#projeto #sirius" in saved


def test_unmatched_note_uses_one_inbox_not_a_title_file(tmp_path):
    notes = tmp_path / "Anotações"
    notes.mkdir()
    (notes / "Cursos.md").write_text("", encoding="utf-8")
    result = _organize(tmp_path, title="IA binária", content="tokens 0 ou 1", category="ideia",
                       llm_client=_FakeLlm('{"file":""}'))
    assert result.target == notes / "Caixa de entrada.md"
    assert result.target.exists()
    assert not (notes / "IA binária.md").exists()


def test_invalid_ai_destination_falls_back_to_strong_title_category_and_tags_match(tmp_path):
    notes = tmp_path / "Anotações"
    notes.mkdir()
    target = notes / "Saúde Mental.md"
    target.touch()
    result = _organize(
        tmp_path, title="Ansiedade no trabalho", content="Como reduzir o estresse", category="saúde",
        ai_tags=["saúde mental", "ansiedade"],
        llm_client=_FakeLlm('{"file":"arquivo-que-nao-existe.md"}'),
    )
    assert result.target == target


def test_gemma_unavailable_uses_confident_keyword_match(tmp_path):
    notes = tmp_path / "Anotações"
    notes.mkdir()
    target = notes / "Psicologia.md"
    target.touch()
    result = _organize(
        tmp_path, title="Psicologia e saúde mental", content="ansiedade e comportamento", category="estudo",
        ai_tags=["psicologia"], llm_client=_FailingLlm(),
    )
    assert result.target == target


def test_invalid_ai_json_uses_confident_keyword_match(tmp_path):
    notes = tmp_path / "Anotações"
    notes.mkdir()
    target = notes / "Carreira.md"
    target.touch()
    result = _organize(
        tmp_path, title="Transição de carreira", content="novo projeto profissional", category="trabalho",
        ai_tags=["carreira"], llm_client=_FakeLlm("resposta que não é JSON"),
    )
    assert result.target == target


def test_no_suitable_document_uses_inbox(tmp_path):
    notes = tmp_path / "Anotações"
    notes.mkdir()
    (notes / "Viagens.md").touch()
    result = _organize(
        tmp_path, title="Pagamento do condomínio", content="Vencimento do boleto", category="financeiro",
        ai_tags=["condomínio"], llm_client=_FakeLlm('{"file":""}'),
    )
    assert result.target == notes / "Caixa de entrada.md"


def test_configured_notes_subpath_is_used(tmp_path, monkeypatch):
    notes = tmp_path / "Knowledge" / "Notes"
    notes.mkdir(parents=True)
    target = notes / "Projetos.md"
    target.touch()
    monkeypatch.setattr(note_organizer, "_get_config", lambda key, default="": "Knowledge/Notes" if key == "obsidian_notes_subpath" else default)
    result = _organize(
        tmp_path, title="Sirius", content="Projeto Sirius", category="projeto",
        llm_client=_FakeLlm('{"file":"Projetos.md"}'),
    )
    assert result.target == target


def test_retry_after_delivery_ack_loss_is_idempotent(tmp_path):
    notes = tmp_path / "Anotações"
    notes.mkdir()
    target = notes / "Ideias.md"
    target.touch()
    kwargs = dict(title="Ideia", content="Uma ideia curta", category="ideia", source_uuid="retry-uuid",
                  llm_client=_FakeLlm('{"file":"Ideias.md"}'))

    async def concurrent_delivery():
        return await asyncio.gather(
            note_organizer.organize_note(vault_path=str(tmp_path), **kwargs),
            note_organizer.organize_note(vault_path=str(tmp_path), **kwargs),
        )

    first, second = asyncio.run(concurrent_delivery())
    third = _organize(tmp_path, **kwargs)
    saved = target.read_text(encoding="utf-8")
    assert first.target == second.target == third.target == target
    assert second.duplicate and third.duplicate
    assert saved.count("Uma ideia curta") == 1


def test_images_are_registered_only_in_images_document(tmp_path):
    paths = note_organizer.save_images(str(tmp_path), [("foto?.png", b"png")])
    notes = tmp_path / "Anotações"
    images = notes / "Imagens.md"
    assert len(paths) == 1 and paths[0].exists()
    assert paths[0].parent.name == "_attachments"
    body = images.read_text(encoding="utf-8")
    assert "![](_attachments/foto_.png)" in body
