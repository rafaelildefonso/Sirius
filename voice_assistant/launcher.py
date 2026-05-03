"""Integrated launcher - starts backend server and provides voice/UI modes."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
import webbrowser
from typing import Optional


def start_backend() -> Optional[subprocess.Popen]:
    """Start the FastAPI backend server."""
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "openjarvis.cli", "serve"],
            cwd=r"c:\Users\faely\PROJETOS\jarvis",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Wait a moment for server to start
        time.sleep(2)
        return proc
    except Exception as e:
        print(f"Failed to start backend: {e}")
        return None


def start_voice_assistant():
    """Start the voice assistant in full-screen mode."""
    from voice_assistant.main import VoiceAssistant

    assistant = VoiceAssistant()
    try:
        assistant.run()
    except KeyboardInterrupt:
        assistant.stop()
    except Exception as e:
        print(f"Voice assistant error: {e}")


def start_web_interface():
    """Open the web interface in browser."""
    webbrowser.open("http://localhost:8000")


def main():
    """Main entry point - provides menu to choose mode."""
    import tkinter as tk
    from tkinter import ttk

    # Start backend server in background
    print("Starting backend server...")
    backend_proc = start_backend()
    if not backend_proc:
        print("ERROR: Could not start backend")
        input("Press Enter to exit...")
        return

    print("Backend started! Choose your interface:")

    # Create selection UI
    root = tk.Tk()
    root.title("OpenSirius Launcher")
    root.geometry("400x350")
    root.configure(bg="#0a0a0a")

    # Style
    style = ttk.Style()
    style.configure("TFrame", background="#0a0a0a")

    # Title
    tk.Label(
        root,
        text="OpenSirius",
        font=("Segoe UI", 28, "bold"),
        bg="#0a0a0a",
        fg="#00a8ff",
    ).pack(pady=(30, 10))

    tk.Label(
        root,
        text="Escolha como usar:",
        font=("Segoe UI", 12),
        bg="#0a0a0a",
        fg="#808080",
    ).pack(pady=(0, 20))

    # Button frame
    btn_frame = tk.Frame(root, bg="#0a0a0a")
    btn_frame.pack(expand=True)

    def launch_voice():
        root.destroy()
        print("Starting Voice Assistant...")
        start_voice_assistant()
        # When voice assistant ends, stop backend
        if backend_proc:
            backend_proc.terminate()

    def launch_web():
        root.destroy()
        print("Opening Web Interface...")
        start_web_interface()
        # Keep backend running, user can close console
        print("\nBackend running at http://localhost:8000")
        print("Press Ctrl+C to stop")
        try:
            backend_proc.wait()
        except KeyboardInterrupt:
            backend_proc.terminate()

    def launch_both():
        """Launch web interface and keep voice ready."""
        start_web_interface()
        # Show a small indicator that voice is available
        voice_window = tk.Toplevel(root)
        voice_window.title("Voice Ready")
        voice_window.geometry("300x100")
        voice_window.configure(bg="#0a0a0a")
        tk.Label(
            voice_window,
            text="Pressione ESPAÇO para falar",
            font=("Segoe UI", 14),
            bg="#0a0a0a",
            fg="#00a8ff",
        ).pack(expand=True)

        # Start voice in background thread
        def voice_thread():
            start_voice_assistant()

        threading.Thread(target=voice_thread, daemon=True).start()

    # Voice Mode button
    tk.Button(
        btn_frame,
        text="🎙️ Modo Voz (Tela Cheia)",
        font=("Segoe UI", 14),
        bg="#00a8ff",
        fg="white",
        activebackground="#0088cc",
        activeforeground="white",
        bd=0,
        padx=20,
        pady=10,
        cursor="hand2",
        command=launch_voice,
    ).pack(pady=(0, 10), fill=tk.X)

    # Web Mode button
    tk.Button(
        btn_frame,
        text="🌐 Modo Web (Navegador)",
        font=("Segoe UI", 14),
        bg="#1a1a2e",
        fg="#e0e0e0",
        activebackground="#2a2a3e",
        activeforeground="white",
        bd=0,
        padx=20,
        pady=10,
        cursor="hand2",
        command=launch_web,
    ).pack(pady=(0, 10), fill=tk.X)

    # Exit button
    tk.Button(
        btn_frame,
        text="Sair",
        font=("Segoe UI", 12),
        bg="#0a0a0a",
        fg="#808080",
        activebackground="#1a1a2e",
        activeforeground="white",
        bd=1,
        padx=20,
        pady=5,
        cursor="hand2",
        command=lambda: (backend_proc.terminate(), root.destroy()),
    ).pack(pady=(20, 0))

    root.mainloop()


if __name__ == "__main__":
    main()
