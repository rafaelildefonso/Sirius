"""
Window and application control for Windows.
Provides tools to manage open windows, focus apps, send keystrokes, etc.
"""

import subprocess
import time
from typing import List, Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class WindowInfo:
    """Information about a window."""
    title: str
    handle: int
    process_name: str
    is_minimized: bool
    is_maximized: bool


class WindowController:
    """Controller for managing windows and applications on Windows."""
    
    def __init__(self):
        self.platform = self._detect_platform()
        
    def _detect_platform(self) -> str:
        """Detect the operating system."""
        import sys
        if sys.platform == "win32":
            return "windows"
        elif sys.platform == "darwin":
            return "macos"
        else:
            return "linux"
    
    def list_running_apps(self) -> List[WindowInfo]:
        """List all running applications with visible windows."""
        if self.platform == "windows":
            return self._list_windows_windows()
        elif self.platform == "macos":
            return self._list_windows_macos()
        else:
            return self._list_windows_linux()
    
    def _list_windows_windows(self) -> List[WindowInfo]:
        """List windows on Windows using pywin32."""
        try:
            import win32gui
            import win32process
            import psutil
            
            windows = []
            
            def callback(hwnd, extra):
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if title:  # Only include windows with titles
                        try:
                            # Get process info
                            _, pid = win32process.GetWindowThreadProcessId(hwnd)
                            process = psutil.Process(pid)
                            process_name = process.name()
                            
                            # Get window state
                            placement = win32gui.GetWindowPlacement(hwnd)
                            is_minimized = placement[1] == win32con.SW_SHOWMINIMIZED
                            is_maximized = placement[1] == win32con.SW_SHOWMAXIMIZED
                            
                            windows.append(WindowInfo(
                                title=title,
                                handle=hwnd,
                                process_name=process_name,
                                is_minimized=is_minimized,
                                is_maximized=is_maximized
                            ))
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                return True
            
            import win32con
            win32gui.EnumWindows(callback, None)
            return windows
            
        except ImportError:
            # Fallback using tasklist
            return self._list_windows_fallback()
    
    def _list_windows_fallback(self) -> List[WindowInfo]:
        """Fallback method using tasklist command."""
        try:
            result = subprocess.run(
                ["tasklist", "/fo", "csv", "/nh"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore"
            )
            
            windows = []
            for line in result.stdout.strip().split("\n"):
                parts = line.split('","')
                if len(parts) >= 2:
                    process_name = parts[0].replace('"', '')
                    windows.append(WindowInfo(
                        title=process_name,
                        handle=0,
                        process_name=process_name,
                        is_minimized=False,
                        is_maximized=False
                    ))
            return windows
            
        except Exception as e:
            return []
    
    def _list_windows_macos(self) -> List[WindowInfo]:
        """List windows on macOS (placeholder)."""
        # TODO: Implement using AppleScript or pyobjc
        return []
    
    def _list_windows_linux(self) -> List[WindowInfo]:
        """List windows on Linux using xdotool or wmctrl."""
        try:
            # Try xdotool
            result = subprocess.run(
                ["xdotool", "search", "--class", ".*"],
                capture_output=True,
                text=True
            )
            
            windows = []
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    try:
                        window_id = int(line.strip())
                        # Get window title
                        title_result = subprocess.run(
                            ["xdotool", "getwindowname", str(window_id)],
                            capture_output=True,
                            text=True
                        )
                        title = title_result.stdout.strip()
                        
                        if title:
                            windows.append(WindowInfo(
                                title=title,
                                handle=window_id,
                                process_name="unknown",
                                is_minimized=False,
                                is_maximized=False
                            ))
                    except ValueError:
                        continue
            
            return windows
            
        except FileNotFoundError:
            return []
    
    def find_window(self, app_name: str) -> Optional[WindowInfo]:
        """Find a window by application name (partial match)."""
        app_lower = app_name.lower().strip()
        windows = self.list_running_apps()
        
        # First try exact partial match in title or process name
        for window in windows:
            if (app_lower in window.title.lower() or 
                app_lower in window.process_name.lower()):
                return window
        
        # Try with common variations (case insensitive, no spaces)
        app_no_space = app_lower.replace(" ", "")
        for window in windows:
            title_lower = window.title.lower().replace(" ", "")
            process_lower = window.process_name.lower().replace(" ", "")
            if (app_no_space in title_lower or 
                app_no_space in process_lower or
                title_lower in app_no_space or
                process_lower in app_no_space):
                return window
        
        # Try without .exe extension
        if app_lower.endswith(".exe"):
            app_no_exe = app_lower[:-4]
            for window in windows:
                if (app_no_exe in window.title.lower() or 
                    app_no_exe in window.process_name.lower()):
                    return window
        
        # Debug: print all windows if not found
        if not windows:
            print(f"[WindowController] No windows found")
        else:
            print(f"[WindowController] Looking for '{app_name}', found windows:")
            for w in windows[:10]:  # First 10
                print(f"  - Title: '{w.title}', Process: '{w.process_name}'")
        
        return None
    
    def focus_window(self, app_name: str) -> bool:
        """Bring a window to the foreground."""
        window = self.find_window(app_name)
        if not window:
            return False
        
        if self.platform == "windows":
            return self._focus_window_windows(window.handle)
        elif self.platform == "macos":
            return self._focus_window_macos(window.title)
        else:
            return self._focus_window_linux(window.handle)
    
    def _focus_window_windows(self, hwnd: int) -> bool:
        """Focus window on Windows."""
        try:
            import win32gui
            import win32con
            
            # Restore if minimized
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            
            # Bring to front
            win32gui.SetForegroundWindow(hwnd)
            return True
            
        except ImportError:
            # Fallback to alt-tab hack
            return False
    
    def _focus_window_macos(self, window_title: str) -> bool:
        """Focus window on macOS using AppleScript."""
        try:
            script = f'''
            tell application "System Events"
                tell process "{window_title}"
                    set frontmost to true
                end tell
            end tell
            '''
            subprocess.run(["osascript", "-e", script], capture_output=True)
            return True
        except:
            return False
    
    def _focus_window_linux(self, window_id: int) -> bool:
        """Focus window on Linux using xdotool."""
        try:
            subprocess.run(
                ["xdotool", "windowactivate", str(window_id)],
                capture_output=True,
                check=True
            )
            return True
        except:
            return False
    
    def close_window(self, app_name: str) -> bool:
        """Close a window/application."""
        window = self.find_window(app_name)
        if not window:
            # Try to kill by process name
            return self._kill_process(app_name)
        
        if self.platform == "windows":
            return self._close_window_windows(window.handle)
        elif self.platform == "macos":
            return self._close_window_macos(window.title)
        else:
            return self._close_window_linux(window.handle)
    
    def _close_window_windows(self, hwnd: int) -> bool:
        """Close window on Windows."""
        try:
            import win32gui
            import win32con
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            return True
        except ImportError:
            return False
    
    def _close_window_macos(self, window_title: str) -> bool:
        """Close window on macOS."""
        try:
            script = f'''
            tell application "{window_title}"
                quit
            end tell
            '''
            subprocess.run(["osascript", "-e", script], capture_output=True)
            return True
        except:
            return False
    
    def _close_window_linux(self, window_id: int) -> bool:
        """Close window on Linux."""
        try:
            subprocess.run(
                ["xdotool", "windowclose", str(window_id)],
                capture_output=True,
                check=True
            )
            return True
        except:
            return False
    
    def _kill_process(self, process_name: str) -> bool:
        """Kill a process by name."""
        try:
            if self.platform == "windows":
                subprocess.run(["taskkill", "/f", "/im", process_name], 
                             capture_output=True, check=True)
            else:
                subprocess.run(["pkill", "-f", process_name], 
                             capture_output=True, check=True)
            return True
        except:
            return False
    
    def minimize_window(self, app_name: str) -> bool:
        """Minimize a window."""
        window = self.find_window(app_name)
        if not window:
            return False
        
        if self.platform == "windows":
            try:
                import win32gui
                import win32con
                win32gui.ShowWindow(window.handle, win32con.SW_MINIMIZE)
                return True
            except ImportError:
                return False
        elif self.platform == "linux":
            try:
                subprocess.run(
                    ["xdotool", "windowminimize", str(window.handle)],
                    capture_output=True,
                    check=True
                )
                return True
            except:
                return False
        return False
    
    def maximize_window(self, app_name: str) -> bool:
        """Maximize a window."""
        window = self.find_window(app_name)
        if not window:
            return False
        
        if self.platform == "windows":
            try:
                import win32gui
                import win32con
                win32gui.ShowWindow(window.handle, win32con.SW_MAXIMIZE)
                return True
            except ImportError:
                return False
        elif self.platform == "linux":
            try:
                # xdotool doesn't have direct maximize, use wmctrl
                subprocess.run(
                    ["wmctrl", "-i", "-r", str(window.handle), "-b", "add,maximized_vert,maximized_horz"],
                    capture_output=True,
                    check=True
                )
                return True
            except:
                return False
        return False
    
    def send_keys(self, keys: str) -> bool:
        """Send keystrokes to the currently focused window."""
        try:
            import pyautogui
            pyautogui.write(keys, interval=0.01)
            return True
        except ImportError:
            # Fallback to platform-specific methods
            if self.platform == "windows":
                return self._send_keys_windows(keys)
            elif self.platform == "linux":
                return self._send_keys_linux(keys)
            return False
    
    def _send_keys_windows(self, keys: str) -> bool:
        """Send keys on Windows."""
        try:
            # Use WScript.Shell for simple typing
            import win32com.client
            shell = win32com.client.Dispatch("WScript.Shell")
            shell.SendKeys(keys)
            return True
        except:
            return False
    
    def _send_keys_linux(self, keys: str) -> bool:
        """Send keys on Linux using xdotool."""
        try:
            subprocess.run(
                ["xdotool", "type", keys],
                capture_output=True,
                check=True
            )
            return True
        except:
            return False
    
    def send_hotkey(self, *keys: str) -> bool:
        """Send a hotkey combination (e.g., 'ctrl', 's')."""
        try:
            import pyautogui
            pyautogui.hotkey(*keys)
            return True
        except ImportError:
            return False
    
    def get_active_window(self) -> Optional[WindowInfo]:
        """Get information about the currently active window."""
        if self.platform == "windows":
            try:
                import win32gui
                import win32process
                import psutil
                
                hwnd = win32gui.GetForegroundWindow()
                if hwnd:
                    title = win32gui.GetWindowText(hwnd)
                    try:
                        _, pid = win32process.GetWindowThreadProcessId(hwnd)
                        process = psutil.Process(pid)
                        process_name = process.name()
                    except:
                        process_name = "unknown"
                    
                    return WindowInfo(
                        title=title,
                        handle=hwnd,
                        process_name=process_name,
                        is_minimized=False,
                        is_maximized=False
                    )
            except ImportError:
                pass
        
        return None


# Singleton instance
_controller: Optional[WindowController] = None


def get_controller() -> WindowController:
    """Get the singleton window controller instance."""
    global _controller
    if _controller is None:
        _controller = WindowController()
    return _controller
