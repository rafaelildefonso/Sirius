"""Full-screen voice assistant UI with orb animation and subtitles."""

from __future__ import annotations

import math
import random
import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, Optional


class VoiceAssistantUI:
    """Full-screen dark UI with animated orb and live subtitles."""

    COLORS = {
        "bg": "#050505",
        "fg": "#00d2ff",
        "fg_light": "#92fe9d",
        "fg_dim": "#004e92",
        "text": "#f0f0f0",
        "text_dim": "#a0a0a0",
        "idle": "#00d2ff",
        "recording": "#92fe9d",
        "processing": "#f39c12",
        "playing": "#00d2ff",
        "error": "#ff4b2b",
    }

    ORB_SIZES = {
        "idle": 120,
        "listening": 150,
        "recording": 160,
        "processing": 130,
        "playing": 170,
        "error": 120,
    }

    def __init__(
        self,
        on_close: Optional[Callable[[], None]] = None,
        on_push: Optional[Callable[[], None]] = None,
        on_release: Optional[Callable[[], None]] = None,
        on_live_toggle: Optional[Callable[[bool], None]] = None,
        on_background_toggle: Optional[Callable[[bool], None]] = None,
        on_settings: Optional[Callable[[], None]] = None,
    ):
        self.on_close = on_close
        self.on_push = on_push
        self.on_release = on_release
        self._on_live_toggle_callback = on_live_toggle
        self._on_background_toggle = on_background_toggle
        self._on_settings = on_settings
        self._is_background_mode = False
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
        self._waveform_data = [0.0] * 50
        self._live_mode = False
        self._is_fullscreen = False

    def build(self) -> tk.Tk:
        """Build and return the main window."""
        self._root = tk.Tk()
        self._root.title("Sirius")
        self._root.configure(bg=self.COLORS["bg"])

        # Maximized window (covers screen but keeps taskbar)
        self._root.state('zoomed')
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Bind ESC to close and F11 to toggle fullscreen
        self._root.bind("<Escape>", lambda e: self._on_close())
        self._root.bind("<F11>", self._toggle_fullscreen)

        # Set window icon
        try:
            import os
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(current_dir)
            icon_path = os.path.join(project_root, "frontend", "public", "favicon.ico")
            if os.path.exists(icon_path):
                self._root.iconbitmap(icon_path)
        except Exception:
            pass

        # ---- Layout ----
        # Center container
        center_frame = tk.Frame(self._root, bg=self.COLORS["bg"])
        center_frame.place(relx=0.5, rely=0.45, anchor=tk.CENTER)

        # Orb canvas
        self._indicator = tk.Canvas(
            center_frame, width=1200, height=600,
            highlightthickness=0, bg=self.COLORS["bg"],
        )
        self._indicator.pack(pady=(0, 20))

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

        # Settings and Live mode buttons
        buttons_row = tk.Frame(commands_frame, bg=self.COLORS["bg"])
        buttons_row.pack(side=tk.TOP, pady=(0, 8))

        # Settings button (for clap detection config)
        self._settings_button = tk.Button(
            buttons_row,
            text="⚙️",
            font=("Segoe UI", 11),
            bg=self.COLORS["bg"],
            fg=self.COLORS["text_dim"],
            activebackground=self.COLORS["bg"],
            activeforeground=self.COLORS["fg_light"],
            bd=0,
            cursor="hand2",
            command=self._on_settings_click,
        )
        self._settings_button.pack(side=tk.LEFT, padx=(0, 10))

        # Live mode toggle button
        self._live_button = tk.Button(
            buttons_row,
            text="🔴 LIVE",
            font=("Segoe UI", 11, "bold"),
            bg=self.COLORS["bg"],
            fg=self.COLORS["text_dim"],
            activebackground=self.COLORS["bg"],
            activeforeground=self.COLORS["recording"],
            bd=0,
            cursor="hand2",
            command=self._toggle_live_mode,
        )
        self._live_button.pack(side=tk.LEFT)

        commands = tk.Label(
            commands_frame,
            text="ESPAÇO = Falar  •  L = Live  •  Shift+Esc = Background  •  ESC = Sair",
            font=("Segoe UI", 11),
            bg=self.COLORS["bg"],
            fg=self.COLORS["text_dim"],
        )
        commands.pack()

        # Bind keys
        self._root.bind("<KeyPress-space>", self._on_space_press)
        self._root.bind("<KeyRelease-space>", self._on_space_release)
        self._root.bind("<space>", self._on_space_press)
        self._root.bind("<l>", lambda e: self._toggle_live_mode())
        self._root.bind("<L>", lambda e: self._toggle_live_mode())
        self._root.bind("<Shift-Escape>", self._on_shift_escape)

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
        elif self._current_state == "idle":
            self._orb_pulse += 0.05
            pulse = math.sin(self._orb_pulse) * 4
        
        size = self._orb_size + pulse
        cx, cy = 600, 300

        # Color based on state
        color = self.COLORS.get(self._current_state, self.COLORS["idle"])

        # Draw waveform visualizer
        # Always draw, but intensity varies by state
        self._draw_waveform(color)

        # Schedule next frame (~30fps)
        self._animation_id = self._root.after(33, self._animate)

    def _draw_waveform(self, state_color: str):
        """Draw Siri-style waveform based on audio level."""
        self._indicator.delete("wave")
        cx, cy = 600, 300
        
        # Shift waveform data and add new point
        self._waveform_data.pop(0)
        self._waveform_data.append(self._audio_level)
        
        # Draw multi-colored waves
        # Use state color as primary, and variations for depth
        r, g, b = self._hex_to_rgb(state_color)
        wave_colors = [
            state_color,
            f"#{int(r*0.7):02x}{int(g*0.7):02x}{int(b*0.7):02x}", # Darker
            f"#{min(255, int(r*1.3)):02x}{min(255, int(g*1.3)):02x}{min(255, int(b*1.3)):02x}" # Lighter
        ]
        
        for i, color in enumerate(wave_colors):
            points = []
            offset = i * 1.2 # Different phase offset
            amp_mult = 1.0 - (i * 0.25)
            freq = 0.3 + (i * 0.1)
            
            # Width of the waveform
            width_span = 550
            
            for x_idx in range(len(self._waveform_data)):
                # Normalized x from -1 to 1
                nx = (x_idx / (len(self._waveform_data) - 1)) * 2 - 1
                
                # Gaussian-like envelope to taper the ends
                envelope = math.exp(-4 * nx**2)
                
                x = cx + nx * width_span
                
                # Current amplitude point
                amp = self._waveform_data[x_idx]
                
                # Sine wave modulation with time offset
                sine = math.sin(x_idx * freq + self._orb_pulse + offset)
                
                # Base movement + audio reaction
                base_motion = math.sin(self._orb_pulse * 0.5 + offset) * (10 if self._current_state != "idle" else 4)
                
                # If idle, use a tiny fixed amplitude for 'breathing' effect
                effective_amp = amp if self._current_state != "idle" else 0.02
                
                y_offset = (effective_amp * 250 + base_motion) * sine * amp_mult * envelope
                
                points.extend([x, cy + y_offset])
            
            if len(points) >= 4:
                # Use thicker lines for the background waves
                w = 5 if i == 0 else 3
                self._indicator.create_line(
                    points, fill=color, width=w, smooth=True, tags="wave"
                )

    def _hex_to_rgb(self, hex_color: str) -> tuple[int, int, int]:
        """Convert hex color string to RGB tuple."""
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

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
            "listening": "aguardando",
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

    def _toggle_live_mode(self) -> None:
        """Toggle live mode on/off."""
        self._live_mode = not self._live_mode
        self._update_live_button()
        if self._on_live_toggle_callback:
            self._on_live_toggle_callback(self._live_mode)

    def _update_live_button(self) -> None:
        """Update live button appearance based on state."""
        if self._live_mode:
            self._live_button.config(
                text="🔴 LIVE ON",
                fg=self.COLORS["recording"],
            )
        else:
            self._live_button.config(
                text="⚪ LIVE OFF",
                fg=self.COLORS["text_dim"],
            )

    def set_live_mode(self, enabled: bool) -> None:
        """Set live mode state programmatically."""
        if self._live_mode != enabled:
            self._live_mode = enabled
            self._update_live_button()

    def is_live_mode(self) -> bool:
        """Check if live mode is enabled."""
        return self._live_mode

    def _on_shift_escape(self, event=None) -> None:
        """Handle Shift+Escape to toggle background mode."""
        self._is_background_mode = not self._is_background_mode
        if self._is_background_mode:
            self.minimize_to_background()
        else:
            self.restore_from_background()
        if self._on_background_toggle:
            self._on_background_toggle(self._is_background_mode)
        return "break"

    def minimize_to_background(self) -> None:
        """Minimize/hide window to background mode."""
        if self._root:
            self._root.withdraw()  # Hide window
            print(" Minimizado para background (2 palmas para voltar)")

    def restore_from_background(self) -> None:
        """Restore window from background to foreground."""
        if self._root:
            self._root.deiconify()  # Show window
            self._root.state('zoomed')
            self._root.focus_force()
            self._root.lift()
            self._is_background_mode = False
            print(" Restaurado ao primeiro plano")

    def _toggle_fullscreen(self, event=None) -> str:
        """Toggle true full-screen mode."""
        self._is_fullscreen = not self._is_fullscreen
        if self._root:
            self._root.attributes("-fullscreen", self._is_fullscreen)
            if not self._is_fullscreen:
                self._root.state('zoomed')
        return "break"

    def set_background_mode(self, enabled: bool) -> None:
        """Set background mode state programmatically."""
        if self._is_background_mode != enabled:
            self._is_background_mode = enabled
            if enabled:
                self.minimize_to_background()
            else:
                self.restore_from_background()

    def is_background_mode(self) -> bool:
        """Check if in background mode."""
        return self._is_background_mode

    def on_background_toggle(self, callback: Optional[Callable[[bool], None]]) -> None:
        """Set callback for background mode toggle."""
        self._on_background_toggle = callback

    def _on_settings_click(self) -> None:
        """Handle settings button click."""
        if self._on_settings:
            self._on_settings()

    def open_clap_settings(
        self,
        current_config: Dict[str, float],
        on_save: Callable[[Dict[str, float]], None],
        audio_level_callback: Optional[Callable[[], float]] = None,
        on_start_test: Optional[Callable[[], None]] = None,
        on_stop_test: Optional[Callable[[], None]] = None,
        on_calibrate: Optional[Callable[[], None]] = None,
    ) -> None:
        """Open clap detection settings window with audio meter."""
        settings_window = tk.Toplevel(self._root)
        settings_window.title("Configuração de Palmas")
        settings_window.configure(bg=self.COLORS["bg"])
        settings_window.geometry("500x650")
        settings_window.resizable(False, False)

        # Center on screen
        settings_window.transient(self._root)
        settings_window.grab_set()

        # Title
        title = tk.Label(
            settings_window,
            text="⚙️ Configuração de Detecção de Palmas",
            font=("Segoe UI", 14, "bold"),
            bg=self.COLORS["bg"],
            fg=self.COLORS["fg_light"],
        )
        title.pack(pady=(20, 10))

        # Audio Meter Frame
        meter_frame = tk.Frame(settings_window, bg=self.COLORS["bg"])
        meter_frame.pack(fill=tk.X, padx=30, pady=10)

        meter_label = tk.Label(
            meter_frame,
            text="Medidor de Áudio (bata palmas para testar)",
            font=("Segoe UI", 11),
            bg=self.COLORS["bg"],
            fg=self.COLORS["text"],
        )
        meter_label.pack()

        # Test button frame
        test_frame = tk.Frame(meter_frame, bg=self.COLORS["bg"])
        test_frame.pack(pady=(5, 0))

        test_active = tk.BooleanVar(value=False)

        def toggle_test():
            if test_active.get():
                # Stop test
                test_active.set(False)
                test_btn.config(text="🎤 Iniciar Teste", bg=self.COLORS["fg"])
                if on_stop_test:
                    on_stop_test()
            else:
                # Start test
                test_active.set(True)
                test_btn.config(text="⏹️ Parar Teste", bg=self.COLORS["recording"])
                if on_start_test:
                    on_start_test()

        test_btn = tk.Button(
            test_frame,
            text="🎤 Iniciar Teste",
            font=("Segoe UI", 10, "bold"),
            bg=self.COLORS["fg"],
            fg=self.COLORS["bg"],
            activebackground=self.COLORS["fg_light"],
            activeforeground=self.COLORS["bg"],
            bd=0,
            cursor="hand2",
            command=toggle_test,
        )
        test_btn.pack()

        test_hint = tk.Label(
            test_frame,
            text="Clique para ativar o microfone e ver o nível das palmas",
            font=("Segoe UI", 9),
            bg=self.COLORS["bg"],
            fg=self.COLORS["text_dim"],
        )
        test_hint.pack(pady=(2, 0))

        # Calibrate Button
        calibrate_btn = tk.Button(
            meter_frame,
            text="🎯 Auto-Calibrar (Bata 3 palmas)",
            font=("Segoe UI", 10, "bold"),
            bg="#f1c40f",
            fg=self.COLORS["bg"],
            activebackground="#f39c12",
            activeforeground=self.COLORS["bg"],
            bd=0,
            cursor="hand2",
            command=on_calibrate,
        )
        calibrate_btn.pack(pady=(10, 0))

        # Canvas for audio meter
        meter_canvas = tk.Canvas(
            meter_frame,
            width=400,
            height=40,
            bg=self.COLORS["fg_dim"],
            highlightthickness=0,
        )
        meter_canvas.pack(pady=10)

        meter_bar = meter_canvas.create_rectangle(
            0, 0, 0, 40,
            fill=self.COLORS["fg"],
            outline="",
        )

        meter_text = meter_canvas.create_text(
            200, 20,
            text="-60.0 dB",
            font=("Segoe UI", 12, "bold"),
            fill=self.COLORS["text"],
        )

        # Threshold indicator line
        threshold_line = meter_canvas.create_line(
            0, 0, 0, 40,
            fill=self.COLORS["recording"],
            width=2,
            dash=(4, 4),
        )

        # Sliders Frame
        sliders_frame = tk.Frame(settings_window, bg=self.COLORS["bg"])
        sliders_frame.pack(fill=tk.BOTH, expand=True, padx=30, pady=10)

        def create_slider(parent, label, from_, to, default, resolution=1):
            frame = tk.Frame(parent, bg=self.COLORS["bg"])
            frame.pack(fill=tk.X, pady=5)

            lbl = tk.Label(
                frame,
                text=label,
                font=("Segoe UI", 10),
                bg=self.COLORS["bg"],
                fg=self.COLORS["text"],
                anchor="w",
            )
            lbl.pack(fill=tk.X)

            value_var = tk.DoubleVar(value=default)

            slider = tk.Scale(
                frame,
                from_=from_,
                to=to,
                resolution=resolution,
                orient=tk.HORIZONTAL,
                variable=value_var,
                bg=self.COLORS["bg"],
                fg=self.COLORS["text"],
                highlightthickness=0,
                troughcolor=self.COLORS["fg_dim"],
                activebackground=self.COLORS["fg_light"],
            )
            slider.pack(fill=tk.X)

            value_label = tk.Label(
                frame,
                textvariable=value_var,
                font=("Segoe UI", 9),
                bg=self.COLORS["bg"],
                fg=self.COLORS["text_dim"],
            )
            value_label.pack()

            return value_var

        # Create sliders
        threshold_var = create_slider(
            sliders_frame,
            "Threshold (dB) - mais negativo = mais sensível",
            -50, -5,
            current_config.get("threshold_db", -20.0),
            1,
        )

        min_interval_var = create_slider(
            sliders_frame,
            "Intervalo Mínimo entre Palmas (ms)",
            100, 500,
            current_config.get("min_interval_ms", 200),
            10,
        )

        max_interval_var = create_slider(
            sliders_frame,
            "Intervalo Máximo entre Palmas (ms)",
            500, 2000,
            current_config.get("max_interval_ms", 1000),
            10,
        )

        min_duration_var = create_slider(
            sliders_frame,
            "Duração Mínima da Palma (ms)",
            10, 100,
            current_config.get("min_duration_ms", 30),
            5,
        )

        max_duration_var = create_slider(
            sliders_frame,
            "Duração Máxima da Palma (ms)",
            100, 500,
            current_config.get("max_duration_ms", 200),
            5,
        )

        # Update threshold indicator
        def update_threshold_line(*args):
            # Map dB to pixels: -50dB = 0px, -5dB = 400px
            threshold_db = threshold_var.get()
            x = int((threshold_db + 50) / 45 * 400)
            meter_canvas.coords(threshold_line, x, 0, x, 40)

        threshold_var.trace_add("write", update_threshold_line)
        update_threshold_line()

        # Audio meter update
        def update_meter():
            if settings_window.winfo_exists() and audio_level_callback:
                try:
                    level_db = audio_level_callback()
                    # Map dB to bar width: -60dB = 0px, 0dB = 400px
                    bar_width = max(0, min(400, int((level_db + 60) / 60 * 400)))
                    meter_canvas.coords(meter_bar, 0, 0, bar_width, 40)
                    meter_canvas.itemconfig(meter_text, text=f"{level_db:.1f} dB")

                    # Color based on level
                    if level_db > threshold_var.get():
                        meter_canvas.itemconfig(meter_bar, fill=self.COLORS["recording"])
                    else:
                        meter_canvas.itemconfig(meter_bar, fill=self.COLORS["fg"])
                except Exception:
                    pass
            if settings_window.winfo_exists():
                settings_window.after(50, update_meter)

        update_meter()

        # Buttons Frame
        buttons_frame = tk.Frame(settings_window, bg=self.COLORS["bg"])
        buttons_frame.pack(fill=tk.X, padx=30, pady=20)

        def on_save_click():
            config = {
                "threshold_db": threshold_var.get(),
                "min_interval_ms": min_interval_var.get(),
                "max_interval_ms": max_interval_var.get(),
                "min_duration_ms": min_duration_var.get(),
                "max_duration_ms": max_duration_var.get(),
            }
            on_save(config)
            settings_window.destroy()

        def on_cancel():
            settings_window.destroy()

        save_btn = tk.Button(
            buttons_frame,
            text="💾 Salvar",
            font=("Segoe UI", 11, "bold"),
            bg=self.COLORS["fg"],
            fg=self.COLORS["bg"],
            activebackground=self.COLORS["fg_light"],
            activeforeground=self.COLORS["bg"],
            bd=0,
            cursor="hand2",
            command=on_save_click,
        )
        save_btn.pack(side=tk.LEFT, padx=(0, 10))

        cancel_btn = tk.Button(
            buttons_frame,
            text="❌ Cancelar",
            font=("Segoe UI", 11),
            bg=self.COLORS["text_dim"],
            fg=self.COLORS["bg"],
            activebackground=self.COLORS["text"],
            activeforeground=self.COLORS["bg"],
            bd=0,
            cursor="hand2",
            command=on_cancel,
        )
        cancel_btn.pack(side=tk.LEFT)

        # Cleanup when window is closed
        def on_closing():
            if test_active.get() and on_stop_test:
                on_stop_test()
            settings_window.destroy()

        settings_window.protocol("WM_DELETE_WINDOW", on_closing)
