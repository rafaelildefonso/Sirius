"""Extract real Windows .exe icons and return them as base64 PNG data URLs.

Used by the WS server to enrich app-usage stats so the frontend can render
the actual icon of each most-used app. Results are cached per app name.
"""
from __future__ import annotations

import base64
import io
import threading
from pathlib import Path
from typing import Dict, List, Optional

import psutil

_ICON_DIM = 32

_cache: Dict[str, Optional[str]] = {}
_lock = threading.Lock()


def get_app_icons(app_names: List[str]) -> Dict[str, Optional[str]]:
    """Resolve icons for several app names with a single process scan."""
    result: Dict[str, Optional[str]] = {}
    misses: List[str] = []
    for raw in app_names or []:
        key = (raw or "").strip().lower()
        if not key:
            continue
        with _lock:
            if key in _cache:
                result[key] = _cache[key]
            else:
                misses.append(key)
    if misses:
        exe_map = _resolve_exe_paths(misses)
        for key in misses:
            icon: Optional[str] = None
            exe_path = exe_map.get(key)
            if exe_path:
                icon = _extract_from_exe(exe_path)
            with _lock:
                _cache[key] = icon
            result[key] = icon
    return result


def clear_icon_cache() -> None:
    with _lock:
        _cache.clear()


def _resolve_exe_paths(app_names: List[str]) -> Dict[str, str]:
    wanted = {n.lower() for n in app_names}
    found: Dict[str, str] = {}
    try:
        for proc in psutil.process_iter(["name", "exe"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if name not in wanted or name in found:
                    continue
                exe = proc.info.get("exe")
                if exe:
                    found[name] = exe
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except Exception:
        pass
    # Fallback: apps instalados mas não rodando — App Paths no registro.
    import winreg
    roots = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
    )
    for name in list(wanted - set(found)):
        if not name.endswith(".exe"):
            continue
        for root, path in roots:
            try:
                with winreg.OpenKey(root, rf"{path}\{name}") as key:
                    value = winreg.QueryValue(key, None)
                    if value and Path(value).is_file():
                        found[name] = value
                        break
            except OSError:
                continue
    return found


def _extract_from_exe(exe_path: str) -> Optional[str]:
    try:
        import win32con
        import win32gui
        import win32ui
        from PIL import Image
    except ImportError:
        return None

    hicon = None
    bmp = None
    mem_dc = None
    screen_dc = None
    try:
        large, small = win32gui.ExtractIconEx(exe_path, 0, 1)
        candidates = large or small or []
        if not candidates:
            return None
        hicon = candidates[0]

        screen_dc = win32ui.CreateDCFromHandle(win32gui.GetDC(0))
        mem_dc = screen_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(screen_dc, _ICON_DIM, _ICON_DIM)
        mem_dc.SelectObject(bmp)
        win32gui.DrawIconEx(
            mem_dc.GetHandleOutput(), 0, 0, hicon,
            _ICON_DIM, _ICON_DIM, 0, None, win32con.DI_NORMAL,
        )
        info = bmp.GetInfo()
        raw = bmp.GetBitmapBits(True)
        img = Image.frombuffer(
            "RGBA",
            (info["bmWidth"], info["bmHeight"]),
            raw,
            "raw",
            "BGRA",
            0,
            1,
        )
        # Ícones sem canal alfa ficam invisíveis (alpha=0) — compõe sobre fundo escuro.
        alpha_extrema = img.getchannel("A").getextrema()
        if alpha_extrema[1] == 0:
            bg = Image.new("RGBA", img.size, (26, 26, 30, 255))
            opaque = img.copy()
            opaque.putalpha(255)
            img = Image.alpha_composite(bg, opaque)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return None
    finally:
        if hicon is not None:
            try:
                win32gui.DestroyIcon(hicon)
            except Exception:
                pass
        for handle_cleanup in (
            lambda: win32gui.DeleteObject(bmp.GetHandle()) if bmp else None,
            lambda: mem_dc.DeleteDC() if mem_dc else None,
            lambda: screen_dc.DeleteDC() if screen_dc else None,
        ):
            try:
                handle_cleanup()
            except Exception:
                pass
