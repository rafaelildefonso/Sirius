"""Full-screen voice assistant UI with orb animation and subtitles."""

from __future__ import annotations

import math
import random
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional


class VoiceAssistantUI:
    """Full-screen dark UI with animated orb and live subtitles."""

    COLORS = {
        "bg": "#0a0a0a",
        "fg": "#00a8ff",
        "fg_light": "#5cd6ff",
        "fg_dim": "#003366",
        "text": "#e0e0e0",
        "text_dim": "#808080",
        "idle": "#00a8ff",
        "recording": "#5cd6ff",
        "processing": "#5cd6ff",
        "playing": "#00a8ff",
        "error": "#ff3333",
    }

    ORB_SIZES = {
        "idle": 120,
        "recording": 80,
        "processing": 100,
        "playing": 120,
        "error": 120,
    }

    def __init__(
        self,
        on_close: Optional[Callable[[], None]] = None,
        on_push: Optional[Callable[[], None]] = None,
        on_release: Optional[Callable[[], None]] = None,
    ):
        self.on_close = on_close
        self.on_push = on_push
        self.on_release = on_release
        self._root: Optional[tk.Tk] = None
        self._subtitle_var: Optional[tk.StringVar] = None
        self._indicator: Optional[tk.Canvas] = None
        self._current_state = "idle"
        self._is_holding = False
        self._orb_size = 120
        self._target_orb_size = 120
        self._orb_pulse = 0.0
        self._animation_id = None
        self._audio_level = 0.0

    def build(self) -> tk.Tk:
        """Build and return the main window."""
        self._root = tk.Tk()
        self._root.title("Jarvis")
        self._root.configure(bg=self.COLORS["bg"])

        # Maximized window (covers screen but keeps taskbar)
        self._root.state('zoomed')
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Bind ESC to close
        self._root.bind("<Escape>", lambda e: self._on_close())

        # ---- Layout ----
        # Center container
        center_frame = tk.Frame(self._root, bg=self.COLORS["bg"])
        center_frame.place(relx=0.5, rely=0.45, anchor=tk.CENTER)

        # Orb canvas
        self._indicator = tk.Canvas(
            center_frame, width=300, height=300,
            highlightthickness=0, bg=self.COLORS["bg"],
        )
        self._indicator.pack(pady=(0, 40))

        # Draw initial orb
        self._orb_oval = self._indicator.create_oval(
            150 - self._orb_size, 150 - self._orb_size,
            150 + self._orb_size, 150 + self._orb_size,
            fill=self.COLORS["idle"], outline="",
        )

        # Subtitle text (single area, centered below orb)
        self._subtitle_var = tk.StringVar(value="")
        self._subtitle_label = tk.Label(
            center_frame,
            textvariable=self._subtitle_var,
            font=("Segoe UI", 26),
            bg=self.COLORS["bg"],
            fg=self.COLORS["text"],
            wraplength=900,
            justify=tk.CENTER,
        )
        self._subtitle_label.pack(pady=(0, 10))

        # Status text (smaller, below subtitle)
        self._status_var = tk.StringVar(value="")
        self._status_label = tk.Label(
            center_frame,
            textvariable=self._status_var,
            font=("Segoe UI", 16),
            bg=self.COLORS["bg"],
            fg=self.COLORS["text_dim"],
        )
        self._status_label.pack(pady=(5, 0))

        # Commands in bottom-right corner
        commands_frame = tk.Frame(self._root, bg=self.COLORS["bg"])
        commands_frame.place(relx=0.98, rely=0.98, anchor=tk.SE)

        commands = tk.Label(
            commands_frame,
            text="ESPAÇO = Falar  •  Ctrl+Shift+ESPAÇO = Background  •  ESC = Sair",
            font=("Segoe UI", 11),
            bg=self.COLORS["bg"],
            fg=self.COLORS["text_dim"],
        )
        commands.pack()

        # Bind keys
        self._root.bind("<KeyPress-space>", self._on_space_press)
        self._root.bind("<KeyRelease-space>", self._on_space_release)
        self._root.bind("<space>", self._on_space_press)

        self._root.focus_force()

        # Start animation loop
        self._animate()

        return self._root

    def _animate(self):
        """Main animation loop - updates orb size and pulse."""
        if not self._root:
            return

        # Smoothly interpolate orb size toward target
        diff = self._target_orb_size - self._orb_size
        self._orb_size += diff * 0.15

        # Calculate pulse based on state
        pulse = 0
        if self._current_state == "recording":
            self._orb_pulse += 0.08
            pulse = math.sin(self._orb_pulse) * 8
        elif self._current_state == "processing":
            self._orb_pulse += 0.12
            pulse = math.sin(self._orb_pulse) * 12
        elif self._current_state == "playing":
            # Voice-reactive pulse - more dramatic
            base_pulse = math.sin(self._orb_pulse) * 10
            voice_pulse = self._audio_level * 50  # Larger amplitude
            pulse = base_pulse + voice_pulse
            self._orb_pulse += 0.2 + (self._audio_level * 0.3)  # Speed varies with voice

        size = self._orb_size + pulse
        cx, cy = 150, 150

        # Update orb
        self._indicator.coords(
            self._orb_oval,
            cx - size, cy - size, cx + size, cy + size,
        )

        # Color based on state
        color = self.COLORS.get(self._current_state, self.COLORS["idle"])
        self._indicator.itemconfig(self._orb_oval, fill=color)

        # Schedule next frame (~30fps)
        self._animation_id = self._root.after(33, self._animate)

    def set_audio_level(self, level: float) -> None:
        """Set audio level for voice animation (0.0 to 1.0)."""
        self._audio_level = max(0.0, min(1.0, level))

    def set_state(self, state: str) -> None:
        """Update UI state."""
        if state not in self.ORB_SIZES:
            state = "idle"

        self._current_state = state
        self._target_orb_size = self.ORB_SIZES.get(state, 120)
        self._orb_pulse = 0.0

        # Status messages
        messages = {
            "idle": "",
            "recording": "ouvindo",
            "processing": "pensando",
            "playing": "",
            "error": "erro",
        }

        if self._status_var is not None:
            self._status_var.set(messages.get(state, ""))

        # Clear subtitle on idle
        if state == "idle" and self._subtitle_var is not None:
            self._subtitle_var.set("")

        if self._root:
            self._root.update_idletasks()

    def set_subtitle(self, text: str) -> None:
        """Set the subtitle text."""
        if self._subtitle_var is not None:
            self._subtitle_var.set(text)
            if self._root:
                self._root.update_idletasks()

    def clear_subtitle(self) -> None:
        """Clear subtitle text."""
        if self._subtitle_var is not None:
            self._subtitle_var.set("")
            if self._root:
                self._root.update_idletasks()

    # Kept for compatibility
    def set_transcription(self, text: str) -> None:
        """Show user text as subtitle."""
        self.set_subtitle(text)

    def set_response(self, text: str) -> None:
        """Show AI response as subtitle."""
        self.set_subtitle(text)

    def _on_space_press(self, event) -> None:
        """Handle space key press - foreground mode."""
        ctrl_pressed = event.state & 0x4
        shift_pressed = event.state & 0x1
        if ctrl_pressed and shift_pressed:
            return
        if not self._is_holding and self.on_push:
            self._is_holding = True
            self.on_push()
        return "break"

    def _on_space_release(self, event) -> None:
        """Handle space key release."""
        if self._is_holding and self.on_release:
            self._is_holding = False
            self.on_release()
        return "break"

    def _on_close(self) -> None:
        """Handle window close."""
        if self._animation_id:
            try:
                self._root.after_cancel(self._animation_id)
            except Exception:
                pass
        if self.on_close:
            self.on_close()
        if self._root:
            self._root.quit()
            self._root.destroy()

    def run(self) -> None:
        """Start the UI main loop."""
        if self._root:
            self._root.mainloop()

    def update(self) -> None:
        """Process pending UI events."""
        if self._root:
            self._root.update_idletasks()
