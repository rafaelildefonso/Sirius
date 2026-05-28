import json
import os
import platform
import subprocess
import time
from pathlib import Path
import sys

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

try:
    import win32gui
    import win32process
    _WIN32 = True
except ImportError:
    _WIN32 = False

_SYSTEM = platform.system()

def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    # This assumes we are in actions/workspaces.py, so parent is actions/, parent.parent is root
    return Path(__file__).resolve().parent.parent

_CONFIG_PATH = _get_base_dir() / "config" / "workspaces.json"

def _load_workspaces() -> dict:
    if not _CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_workspaces(data: dict):
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(data, indent=4), encoding="utf-8")

def _get_running_apps_windows():
    if not _WIN32 or not _PSUTIL:
        return []
    
    running_exes = set()
    def enum_windows_proc(hwnd, lParam):
        if win32gui.IsWindowVisible(hwnd):
            text = win32gui.GetWindowText(hwnd)
            # Filter out background/system windows
            if text and text not in ["Program Manager", "Settings", "Microsoft Text Input Application"]:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                try:
                    proc = psutil.Process(pid)
                    exe_path = proc.exe()
                    name = proc.name().lower()
                    
                    # Skip common system/assistant processes
                    if name not in ["explorer.exe", "taskmgr.exe", "python.exe", "py.exe", "conhost.exe"]:
                        # Avoid adding the same app multiple times (e.g. multiple windows of same app)
                        running_exes.add(exe_path)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
    win32gui.EnumWindows(enum_windows_proc, None)
    return list(running_exes)

def workspaces(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    Manages workspaces (groups of applications).
    Parameters:
        action: "save" | "open" | "list" | "delete"
        name: Name of the workspace (e.g. "trabalho", "estudo")
    """
    action = parameters.get("action", "open").lower().strip()
    name = parameters.get("name", "default").lower().strip()
    
    if action == "save":
        if _SYSTEM != "Windows":
            return "Save workspace is currently only supported on Windows."
        
        apps = _get_running_apps_windows()
        if not apps:
            return "No open applications found to save. Make sure your apps are not minimized or background processes."
            
        data = _load_workspaces()
        data[name] = apps
        _save_workspaces(data)
        return f"Workspace '{name}' salvo com sucesso contendo {len(apps)} aplicativos."

    elif action == "open":
        data = _load_workspaces()
        if name not in data:
            return f"O espaço de trabalho '{name}' não foi encontrado. Você pode salvá-lo dizendo 'salve este espaço de trabalho como {name}'."
            
        apps = data[name]
        opened = []
        already_running = []
        
        # Get currently running exes for smart "only open if not running" logic
        current_exes = set()
        if _PSUTIL:
            for p in psutil.process_iter(['exe']):
                try:
                    if p.info['exe']:
                        current_exes.add(p.info['exe'].lower())
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

        for app_path in apps:
            app_name = Path(app_path).name
            if app_path.lower() in current_exes:
                already_running.append(app_name)
                continue
                
            try:
                if _SYSTEM == "Windows":
                    _console_apps = {"cmd.exe", "powershell.exe", "pwsh.exe", "git-bash.exe", "wsl.exe"}
                    base = os.path.basename(app_path).lower()
                    if base in _console_apps:
                        flags = subprocess.CREATE_NEW_CONSOLE
                    else:
                        flags = subprocess.CREATE_NO_WINDOW
                    subprocess.Popen(app_path, creationflags=flags)
                else:
                    subprocess.Popen(app_path, shell=True)
                opened.append(app_name)
                time.sleep(0.5) # Brief pause between launches
            except Exception as e:
                print(f"[Workspaces] Failed to open {app_path}: {e}")
                
        res = f"Espaço de trabalho '{name}' processado."
        if opened:
            res += f"\nAbrindo: {', '.join(opened)}"
        if already_running:
            res += f"\nJá estavam abertos: {', '.join(already_running)}"
        
        if player:
            player.write_log(f"[Workspaces] Opened {name}")
            
        return res

    elif action == "list":
        data = _load_workspaces()
        if not data:
            return "Nenhum espaço de trabalho salvo ainda."
        return "Espaços de trabalho salvos: " + ", ".join(data.keys())

    elif action == "delete":
        data = _load_workspaces()
        if name in data:
            del data[name]
            _save_workspaces(data)
            return f"Espaço de trabalho '{name}' removido."
        return f"Espaço de trabalho '{name}' não encontrado."

    return f"Ação '{action}' não reconhecida para workspaces."
