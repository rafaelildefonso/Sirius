"""``jarvis dev`` — start development environment with Tauri + Ollama."""

from __future__ import annotations

import platform
import subprocess
import sys
import time
from pathlib import Path

import click
from rich.console import Console


def is_ollama_running() -> bool:
    """Check if Ollama server is running."""
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def start_ollama() -> subprocess.Popen | None:
    """Start Ollama server."""
    console = Console()
    console.print("[yellow]Ollama not running. Starting Ollama server...[/yellow]")
    
    try:
        # Start ollama serve in background
        if platform.system() == "Windows":
            proc = subprocess.Popen(
                ["ollama", "serve"],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            proc = subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        
        # Wait for Ollama to be ready
        console.print("[yellow]Waiting for Ollama to start...[/yellow]")
        for _ in range(30):  # Wait up to 30 seconds
            time.sleep(1)
            if is_ollama_running():
                console.print("[green]Ollama is ready![/green]")
                return proc
        
        console.print("[red]Ollama failed to start within 30 seconds[/red]")
        return None
    except FileNotFoundError:
        console.print("[red]Ollama not found. Please install Ollama first.[/red]")
        console.print("  Visit: https://ollama.com/download")
        return None
    except Exception as e:
        console.print(f"[red]Error starting Ollama: {e}[/red]")
        return None


@click.command()
@click.option("--skip-ollama", is_flag=True, help="Skip checking/starting Ollama")
@click.option("--no-tauri", is_flag=True, help="Start only backend, no Tauri")
def dev(skip_ollama: bool, no_tauri: bool) -> None:
    """Start development environment with Tauri frontend and Ollama.
    
    This command will:
    1. Check if Ollama is running (start it if not)
    2. Start the backend server
    3. Start the Tauri development app
    """
    console = Console()
    project_root = Path(__file__).parent.parent.parent.parent
    frontend_dir = project_root / "frontend"
    
    # Check if frontend directory exists
    if not no_tauri and not frontend_dir.exists():
        console.print(f"[red]Frontend directory not found: {frontend_dir}[/red]")
        sys.exit(1)
    
    ollama_proc = None
    backend_proc = None
    tauri_proc = None
    
    try:
        # Step 1: Check/Start Ollama
        if not skip_ollama:
            if is_ollama_running():
                console.print("[green]Ollama is already running[/green]")
            else:
                ollama_proc = start_ollama()
                if ollama_proc is None:
                    console.print("[yellow]Continuing without Ollama...[/yellow]")
        
        # Step 2: Start Backend Server
        console.print("[cyan]Starting backend server...[/cyan]")
        backend_cmd = [sys.executable, "-m", "openjarvis.cli", "serve"]
        backend_proc = subprocess.Popen(
            backend_cmd,
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        
        # Wait a bit for backend to start
        time.sleep(3)
        
        # Check if backend is still running
        if backend_proc.poll() is not None:
            stdout, stderr = backend_proc.communicate()
            console.print("[red]Backend failed to start:[/red]")
            if stderr:
                console.print(f"[red]{stderr.decode()}[/red]")
            sys.exit(1)
        
        console.print("[green]Backend server started[/green]")
        
        if no_tauri:
            console.print("[cyan]Backend running at http://localhost:8000[/cyan]")
            console.print("[yellow]Press Ctrl+C to stop[/yellow]")
            try:
                backend_proc.wait()
            except KeyboardInterrupt:
                pass
            return
        
        # Step 3: Start Tauri Dev
        console.print("[cyan]Starting Tauri development app...[/cyan]")
        
        # Check if npm is available
        try:
            npm_cmd = "npm --version" if platform.system() == "Windows" else ["npm", "--version"]
            subprocess.run(
                npm_cmd,
                check=True,
                capture_output=True,
                shell=platform.system() == "Windows"
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            console.print("[red]npm not found. Please install Node.js first.[/red]")
            console.print("  Visit: https://nodejs.org/")
            sys.exit(1)
        
        # Start Tauri (use string command on Windows with shell=True)
        if platform.system() == "Windows":
            tauri_cmd = "npm run tauri dev"
        else:
            tauri_cmd = ["npm", "run", "tauri", "dev"]
        
        tauri_proc = subprocess.Popen(
            tauri_cmd,
            cwd=frontend_dir,
            shell=platform.system() == "Windows",
        )
        
        console.print("[green]Tauri dev started![/green]")
        console.print("[cyan]Waiting for app to open...[/cyan]")
        
        # Wait for Tauri to finish (user closes the window)
        try:
            tauri_proc.wait()
        except KeyboardInterrupt:
            pass
        
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down...[/yellow]")
    finally:
        # Cleanup
        if tauri_proc and tauri_proc.poll() is None:
            console.print("[yellow]Stopping Tauri...[/yellow]")
            tauri_proc.terminate()
            tauri_proc.wait()
        
        if backend_proc and backend_proc.poll() is None:
            console.print("[yellow]Stopping backend...[/yellow]")
            backend_proc.terminate()
            backend_proc.wait()
        
        if ollama_proc and ollama_proc.poll() is None:
            console.print("[yellow]Stopping Ollama...[/yellow]")
            ollama_proc.terminate()
            ollama_proc.wait()
        
        console.print("[green]All services stopped.[/green]")


__all__ = ["dev"]
