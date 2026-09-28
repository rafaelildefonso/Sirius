"""
orchestrator/pane_client.py — Python wrapper to send commands to the Pane CLI (runpane).

Used by Sirius actions to create panes, list agents, and query panel status.
"""
import json
import shutil
import subprocess
from typing import Any, Dict, List, Optional


class PaneClient:
    """Wrapper para enviar comandos ao Pane via runpane CLI."""

    def __init__(self, daemon_url: str = "http://127.0.0.1:8080"):
        self.daemon_url = daemon_url
        self.cli_path = shutil.which("runpane") or "runpane"

    def _run_cli(self, args: List[str]) -> Dict[str, Any]:
        """Execute a runpane CLI command and return parsed JSON output."""
        cmd = [self.cli_path] + args + ["--json"]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            if result.stdout.strip():
                return json.loads(result.stdout)
            return {"success": True}
        except FileNotFoundError:
            return {"success": False, "error": "runpane CLI not found on PATH"}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "runpane command timed out"}
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"Invalid JSON from runpane: {e}"}
        except subprocess.CalledProcessError as e:
            return {"success": False, "error": f"runpane failed: {e.stderr[:200]}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def create_pane(
        self,
        repo: str = "active",
        name: str = "sirius-workspace",
        agent: str = "claude",
        prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new Pane (workspace) in the given repository."""
        args = [
            "panes", "create",
            "--repo", repo,
            "--name", name,
            "--agent", agent,
            "--yes",
        ]
        if prompt:
            args.extend(["--prompt", prompt])
        return self._run_cli(args)

    def list_panes(self) -> List[Dict[str, Any]]:
        """List all active panes."""
        res = self._run_cli(["panes", "list"])
        if isinstance(res, dict):
            return res.get("panes", [])
        return []

    def list_panels(self, pane_id: str) -> List[Dict[str, Any]]:
        """List all panels (tabs) inside a pane."""
        res = self._run_cli(["panels", "list", "--pane", pane_id])
        if isinstance(res, dict):
            return res.get("panels", [])
        return []

    def screen_panel(self, panel_id: str, limit: int = 80) -> Dict[str, Any]:
        """Get the terminal screen content of a panel."""
        return self._run_cli([
            "panels", "screen",
            "--panel", panel_id,
            "--limit", str(limit),
        ])

    def doctor(self) -> Dict[str, Any]:
        """Run runpane doctor to check daemon status."""
        return self._run_cli(["doctor"])
