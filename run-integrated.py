"""Integrated launcher - runs backend and opens web UI with voice mode option."""

from __future__ import annotations

import subprocess
import sys
import time
import webbrowser
from pathlib import Path


def start_backend():
    """Start FastAPI backend server."""
    print("🚀 Starting backend server...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "openjarvis.cli", "serve"],
        cwd=Path(__file__).parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(3)  # Wait for server to start
    return proc


def start_frontend_dev():
    """Start frontend dev server."""
    print("🌐 Starting frontend dev server...")
    frontend_dir = Path(__file__).parent / "frontend"
    proc = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=frontend_dir,
        shell=True,
    )
    time.sleep(5)
    return proc


def open_browser():
    """Open web interface in browser."""
    webbrowser.open("http://localhost:5173")


def run_voice_mode():
    """Run voice assistant mode."""
    print("🎙️ Starting Voice Mode...")
    # Import and run voice assistant
    sys.path.insert(0, str(Path(__file__).parent))
    from voice_assistant.main import VoiceAssistant

    assistant = VoiceAssistant()
    try:
        assistant.run()
    except KeyboardInterrupt:
        assistant.stop()


def main():
    """Main entry point."""
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("OpenJarvis Launcher")
    root.geometry("500x400")
    root.configure(bg="#0a0a0a")

    # Title
    tk.Label(
        root,
        text="OpenJarvis",
        font=("Segoe UI", 32, "bold"),
        bg="#0a0a0a",
        fg="#00a8ff",
    ).pack(pady=(40, 10))

    tk.Label(
        root,
        text="Escolha como deseja usar:",
        font=("Segoe UI", 12),
        bg="#0a0a0a",
        fg="#808080",
    ).pack(pady=(0, 30))

    # Backend process holder
    backend_proc = [None]
    frontend_proc = [None]

    def launch_web():
        """Launch web interface."""
        root.destroy()
        backend_proc[0] = start_backend()
        frontend_proc[0] = start_frontend_dev()
        open_browser()
        print("\n✅ OpenJarvis running!")
        print("🌐 Web: http://localhost:5173")
        print("🔧 API: http://localhost:8000")
        print("\nPress Ctrl+C to stop")
        try:
            if backend_proc[0]:
                backend_proc[0].wait()
        except KeyboardInterrupt:
            if backend_proc[0]:
                backend_proc[0].terminate()
            if frontend_proc[0]:
                frontend_proc[0].terminate()

    def launch_voice():
        """Launch voice mode."""
        root.destroy()
        backend_proc[0] = start_backend()
        print("\n✅ Backend running!")
        print("🎙️ Starting Voice Assistant...\n")
        run_voice_mode()
        if backend_proc[0]:
            backend_proc[0].terminate()

    def launch_both():
        """Launch both web and voice."""
        root.destroy()
        backend_proc[0] = start_backend()
        frontend_proc[0] = start_frontend_dev()
        open_browser()
        print("\n✅ OpenJarvis running with both modes!")
        print("🌐 Web: http://localhost:5173")
        print("🎙️ Voice: Press SPACE in the window to talk")
        print("\nPress Ctrl+C to stop")
        run_voice_mode()
        if backend_proc[0]:
            backend_proc[0].terminate()
        if frontend_proc[0]:
            frontend_proc[0].terminate()

    # Button frame
    frame = tk.Frame(root, bg="#0a0a0a")
    frame.pack(expand=True)

    # Web Mode
    tk.Button(
        frame,
        text="🌐 Modo Web",
        font=("Segoe UI", 14),
        bg="#00a8ff",
        fg="white",
        activebackground="#0088cc",
        bd=0,
        padx=40,
        pady=12,
        cursor="hand2",
        command=launch_web,
    ).pack(pady=(0, 10), fill=tk.X)

    # Voice Mode
    tk.Button(
        frame,
        text="🎙️ Modo Voz (Tela Cheia)",
        font=("Segoe UI", 14),
        bg="#1a1a2e",
        fg="#e0e0e0",
        activebackground="#2a2a3e",
        bd=0,
        padx=40,
        pady=12,
        cursor="hand2",
        command=launch_voice,
    ).pack(pady=(0, 10), fill=tk.X)

    # Both Modes
    tk.Button(
        frame,
        text="⚡ Ambos (Web + Voz)",
        font=("Segoe UI", 12),
        bg="#0a0a0a",
        fg="#808080",
        activebackground="#1a1a2e",
        bd=1,
        padx=40,
        pady=10,
        cursor="hand2",
        command=launch_both,
    ).pack(pady=(0, 20), fill=tk.X)

    # Exit
    tk.Button(
        frame,
        text="Sair",
        font=("Segoe UI", 11),
        bg="#0a0a0a",
        fg="#606060",
        activebackground="#1a1a2e",
        bd=0,
        padx=20,
        pady=5,
        cursor="hand2",
        command=root.destroy,
    ).pack(pady=(10, 0))

    root.mainloop()


if __name__ == "__main__":
    main()
