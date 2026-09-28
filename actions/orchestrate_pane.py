"""
actions/orchestrate_pane.py — Manage Pane worktrees, agents, and sessions.

This action allows the Sirius AI to create panes, list active panes,
and query panel status via the runpane CLI.
"""
from typing import Any, Callable, Dict, Optional

from orchestrator.pane_client import PaneClient

_client: Optional[PaneClient] = None


def _get_client() -> PaneClient:
    global _client
    if _client is None:
        _client = PaneClient()
    return _client


def orchestrate_pane(
    parameters: Dict[str, Any],
    player: Any = None,
    speak: Optional[Callable] = None,
) -> str:
    """Execute a Pane orchestration action.

    Supported actions:
        create_pane  — Create a new pane with a worktree and agent
        list_panes   — List all active panes
        list_panels  — List panels inside a specific pane
        screen_panel — Get terminal screen of a panel
        doctor       — Check runpane daemon status
    """
    action = parameters.get("action", "list_panes").lower().strip()
    client = _get_client()

    if action == "create_pane":
        repo = parameters.get("repo", "active")
        name = parameters.get("name", "sirius-workspace")
        agent = parameters.get("agent", "claude")
        prompt = parameters.get("prompt")

        result = client.create_pane(repo=repo, name=name, agent=agent, prompt=prompt)

        if result.get("success"):
            pane_id = result.get("pane_id", result.get("id", "unknown"))
            msg = f"Pane '{name}' criado com sucesso (id: {pane_id}). Agente: {agent}."
            if speak:
                speak(msg)
            return msg
        else:
            error = result.get("error", "unknown error")
            msg = f"Falha ao criar pane '{name}': {error}"
            if speak:
                speak(msg)
            return msg

    elif action == "list_panes":
        panes = client.list_panes()
        if not panes:
            return "Nenhum pane ativo no momento."
        lines = ["Panes ativos:"]
        for p in panes:
            name = p.get("name", "unnamed")
            agent = p.get("agent", "?")
            repo = p.get("repo", "?")
            lines.append(f"  - {name} (agente: {agent}, repo: {repo})")
        result_text = "\n".join(lines)
        if speak:
            speak(f"{len(panes)} panes ativos encontrados.")
        return result_text

    elif action == "list_panels":
        pane_id = parameters.get("pane_id", "")
        if not pane_id:
            return "Erro: pane_id é obrigatório para list_panels."
        panels = client.list_panels(pane_id)
        if not panels:
            return f"Nenhum painel encontrado no pane {pane_id}."
        lines = [f"Painéis no pane {pane_id}:"]
        for p in panels:
            panel_id = p.get("id", "?")
            agent = p.get("agent", "?")
            lines.append(f"  - {panel_id} (agente: {agent})")
        return "\n".join(lines)

    elif action == "screen_panel":
        panel_id = parameters.get("panel_id", "")
        if not panel_id:
            return "Erro: panel_id é obrigatório para screen_panel."
        limit = parameters.get("limit", 80)
        result = client.screen_panel(panel_id, limit=limit)
        if result.get("success"):
            screen = result.get("screen", result.get("output", ""))
            return f"Tela do painel {panel_id}:\n{screen}"
        return f"Erro ao obter tela do painel {panel_id}: {result.get('error', 'unknown')}"

    elif action == "doctor":
        result = client.doctor()
        if result.get("success"):
            return f"Runpane daemon OK: {result.get('output', 'healthy')}"
        return f"Runpane daemon error: {result.get('error', 'unknown')}"

    return f"Ação '{action}' não reconhecida. Use: create_pane, list_panes, list_panels, screen_panel, doctor."
