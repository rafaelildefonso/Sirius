from __future__ import annotations

import json
import math
import os
import platform
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

from PyQt6.QtCore import (
    QEasingCurve, QMimeData, QObject, QPointF, QRectF, QSize, Qt,
    QTimer, QUrl, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QDragEnterEvent, QDropEvent, QFont,
    QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
    QRadialGradient, QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
    QTextEdit, QVBoxLayout, QWidget, QProgressBar,
)

import qtawesome as qta

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR   = _base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"

_DEFAULT_W, _DEFAULT_H = 980, 700
_MIN_W,     _MIN_H     = 820, 580
_LEFT_W  = 148
_RIGHT_W = 340

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"


class C:
    BG        = "#050505"
    PANEL     = "#0c0c0c"
    PANEL2    = "#121212"
    BORDER    = "#1a1a1a"
    BORDER_B  = "#252525"
    BORDER_A  = "#1e1e1e"
    PRI       = "#00aaff"
    PRI_DIM   = "#004466"
    PRI_GHO   = "rgba(0, 170, 255, 0.05)"
    ACC       = "#ff6b00"
    ACC2      = "#ffcc00"
    GREEN     = "#00ff88"
    GREEN_D   = "#00aa55"
    GREEN_DIM = "#004422"
    RED       = "#ff3355"
    MUTED_C   = "#ff3366"
    TEXT      = "#e0f0ff"
    TEXT_DIM  = "#506070"
    TEXT_MED  = "#8090a0"
    WHITE     = "#ffffff"
    DARK      = "#020202"
    BAR_BG    = "#111111"


def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h); c.setAlpha(a); return c

class _SysMetrics:
    def __init__(self):
        self.cpu  = 0.0
        self.mem  = 0.0
        self.net  = 0.0   
        self.gpu  = -1.0  
        self.tmp  = -1.0  
        self._lock = threading.Lock()
        self._last_net = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._running = True
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def _loop(self):
        while self._running:
            try:
                self._update()
            except Exception:
                pass
            time.sleep(1.5)

    def _update(self):
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent

        nc  = psutil.net_io_counters()
        now = time.time()
        dt  = now - self._last_net_t
        if dt > 0:
            sent = (nc.bytes_sent - self._last_net.bytes_sent) / dt
            recv = (nc.bytes_recv - self._last_net.bytes_recv) / dt
            net  = (sent + recv) / (1024 * 1024)
        else:
            net = 0.0
        self._last_net   = nc
        self._last_net_t = now

        gpu = self._get_gpu()

        tmp = self._get_temp()

        with self._lock:
            self.cpu = cpu
            self.mem = mem
            self.net = net
            self.gpu = gpu
            self.tmp = tmp

    def _get_gpu(self) -> float:
        _nw = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        # NVIDIA
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2,
                creationflags=_nw,
            )
            if r.returncode == 0:
                vals = [float(v.strip()) for v in r.stdout.strip().split("\n") if v.strip()]
                if vals:
                    return sum(vals) / len(vals)
        except Exception:
            pass

        # AMD (Linux)
        if _OS == "Linux":
            try:
                r = subprocess.run(
                    ["rocm-smi", "--showuse", "--csv"],
                    capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0:
                    for line in r.stdout.strip().split("\n"):
                        parts = line.split(",")
                        if len(parts) >= 2:
                            try:
                                return float(parts[1].strip().replace("%", ""))
                            except ValueError:
                                pass
            except Exception:
                pass

            # Intel GPU (Linux)
            try:
                r = subprocess.run(
                    ["intel_gpu_top", "-J", "-s", "500"],
                    capture_output=True, text=True, timeout=1
                )
                if r.returncode == 0 and "Render/3D" in r.stdout:
                    import re
                    m = re.search(r'"busy":\s*([\d.]+)', r.stdout)
                    if m:
                        return float(m.group(1))
            except Exception:
                pass

        # macOS — powermetrics (GPU Engine)
        if _OS == "Darwin":
            try:
                r = subprocess.run(
                    ["sudo", "-n", "powermetrics", "-n", "1", "-i", "500",
                     "--samplers", "gpu_power"],
                    capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0 and "GPU" in r.stdout:
                    import re
                    m = re.search(r'GPU\s+Active:\s+([\d.]+)%', r.stdout)
                    if m:
                        return float(m.group(1))
            except Exception:
                pass

        return -1.0

    def _get_temp(self) -> float:
        try:
            temps = psutil.sensors_temperatures()
            candidates = ["coretemp", "k10temp", "cpu_thermal", "acpitz",
                          "cpu-thermal", "zenpower", "it8688"]
            for name in candidates:
                if name in temps:
                    entries = temps[name]
                    if entries:
                        return entries[0].current
            for entries in temps.values():
                if entries:
                    return entries[0].current
        except Exception:
            pass
        if _OS == "Darwin":
            try:
                r = subprocess.run(
                    ["osx-cpu-temp"], capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0:
                    import re
                    m = re.search(r"([\d.]+)", r.stdout)
                    if m:
                        return float(m.group(1))
            except Exception:
                pass

        if _OS == "Windows":
            try:
                r = subprocess.run(
                    ["powershell", "-Command",
                     "(Get-WmiObject MSAcpi_ThermalZoneTemperature -Namespace root/wmi).CurrentTemperature"],
                    capture_output=True, text=True, timeout=3,
                    creationflags=_nw,
                )
                if r.returncode == 0 and r.stdout.strip():
                    raw = float(r.stdout.strip().split("\n")[0])
                    return (raw / 10.0) - 273.15
            except Exception:
                pass

        return -1.0

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu": self.cpu,
                "mem": self.mem,
                "net": self.net,
                "gpu": self.gpu,
                "tmp": self.tmp,
            }


_metrics = _SysMetrics()

class HudCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.muted    = False
        self.speaking = False
        self.state    = "INITIALISING"
        self.voice_level = 0.0 # 0.0 to 1.0

        self._tick       = 0
        self._scale      = 1.0
        self._tgt_scale  = 1.0
        self._halo       = 40.0
        self._tgt_halo   = 40.0
        self._last_t     = time.time()
        self._dots: list[dict] = []
        self._init_dots()

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._tmr.start(16)

    def _init_dots(self):
        # Create a double ring of dots
        for r_factor in [0.38, 0.42]:
            count = 60 if r_factor > 0.4 else 50
            for i in range(count):
                angle = (i / count) * 2 * math.pi
                self._dots.append({
                    "angle": angle,
                    "r_factor": r_factor,
                    "base_size": random.uniform(1.2, 2.5),
                    "phase": random.uniform(0, 2 * math.pi)
                })

    def _step(self):
        self._tick += 1
        now = time.time()
        if now - self._last_t > (0.15 if self.speaking else 0.6):
            if self.speaking:
                self._tgt_scale = random.uniform(1.02, 1.06)
                self._tgt_halo  = random.uniform(60, 85)
            elif self.muted:
                self._tgt_scale = 1.0
                self._tgt_halo  = 10
            elif self.state == "LISTENING" and self.voice_level > 0.05:
                # React to user voice
                self._tgt_scale = 1.0 + self.voice_level * 0.15
                self._tgt_halo  = 30 + self.voice_level * 60
            else:
                self._tgt_scale = 1.0
                self._tgt_halo  = 30
            self._last_t = now

        sp = 0.2 if self.speaking else 0.08
        self._scale += (self._tgt_scale - self._scale) * sp
        self._halo  += (self._tgt_halo  - self._halo)  * sp

        self._blink = (self._tick // 30) % 2 == 0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), qcol(C.BG))

        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        fw = min(W, H)

        # Subtle background glow
        grad = QRadialGradient(cx, cy, fw * 0.5)
        g_alpha = int(self._halo * 0.6)
        grad.setColorAt(0, qcol(C.PRI_DIM, g_alpha))
        grad.setColorAt(1, Qt.GlobalColor.transparent)
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(0, 0, W, H))

        # Dotted Ring
        p.setPen(Qt.PenStyle.NoPen)
        for dot in self._dots:
            # Oscillation
            osc = math.sin(self._tick * 0.05 + dot["phase"])
            size = dot["base_size"] * (1.0 + 0.3 * osc)
            if self.speaking:
                size *= random.uniform(1.2, 1.8)
            elif self.state == "LISTENING" and self.voice_level > 0.05:
                # Dots jitter/grow with voice
                size *= (1.0 + self.voice_level * 1.5 * random.random())
            
            # Position
            r = fw * dot["r_factor"] * self._scale
            # Adding a bit of "drift" to the dots
            drift_ang = dot["angle"] + self._tick * 0.002
            dx = cx + r * math.cos(drift_ang)
            dy = cy + r * math.sin(drift_ang)
            
            # Opacity and Color
            alpha = int(180 + 75 * osc)
            if self.muted: alpha //= 3
            
            # Use Green for user voice
            if self.state == "LISTENING" and self.voice_level > 0.05:
                p.setBrush(QBrush(qcol(C.GREEN, alpha)))
            else:
                p.setBrush(QBrush(qcol(C.PRI, alpha)))
            
            p.drawEllipse(QPointF(dx, dy), size, size)

        # status text - Move to Center
        sy = cy - 13
        if self.muted:
            ico, txt, hexcol = "fa5s.microphone-slash", "MUTED",     C.MUTED_C
        elif self.speaking:
            ico, txt, hexcol = "fa5s.circle",           "SPEAKING",  C.ACC
        elif self.state == "THINKING":
            ico, txt, hexcol = "fa5s.gem",              "THINKING",  C.ACC2
        elif self.state == "PROCESSING":
            ico, txt, hexcol = "fa5s.play",             "PROCESSING",C.ACC2
        elif self.state == "LISTENING":
            ico, txt, hexcol = "fa5s.circle",           "LISTENING", C.GREEN
        else:
            ico, txt, hexcol = "fa5s.circle",           self.state,  C.PRI

        # draw background pill
        p.setBrush(QBrush(qcol(C.BG, 160)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(cx - 60, sy, 120, 26), 4, 4)

        col = qcol(hexcol)
        icol = qta.icon(ico, color=hexcol,
                        opacity=0.6 if self._blink and self.state not in ("SPEAKING",) else 1.0)
        icol.paint(p, QRectF(cx - 54, sy + 3, 18, 20).toRect(),
                   Qt.AlignmentFlag.AlignCenter)

        p.setPen(QPen(col, 1))
        p.setFont(QFont("Inter", 10, QFont.Weight.Bold))
        p.drawText(QRectF(cx - 30, sy, 86, 26),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, txt)

        # (Waveform removed as requested)

class MetricBar(QWidget):

    def __init__(self, label: str, color: str = C.PRI, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = color
        self._value = 0.0       # 0–100
        self._text  = "--"
        self.setFixedHeight(38)
        self.setMinimumWidth(80)

    def set_value(self, pct: float, text: str):
        self._value = max(0.0, min(100.0, pct))
        self._text  = text
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        # Background track
        p.setBrush(QBrush(qcol(C.PANEL2)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(1, 1, W - 2, H - 2), 6, 6)

        bar_h   = 3
        bar_y   = H - bar_h - 6
        bar_w   = W - 16
        bar_x   = 8
        fill_w  = int(bar_w * self._value / 100)

        p.setBrush(QBrush(qcol(C.BAR_BG)))
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 1.5, 1.5)

        bar_col = qcol(C.RED) if self._value > 85 else (qcol(C.ACC) if self._value > 65 else qcol(self._color))

        if fill_w > 0:
            p.setBrush(QBrush(bar_col))
            p.drawRoundedRect(QRectF(bar_x, bar_y, fill_w, bar_h), 1.5, 1.5)

        p.setFont(QFont("Inter", 8))
        p.setPen(QPen(qcol(C.TEXT_MED), 1))
        p.drawText(QRectF(10, 4, 100, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._label)

        p.setFont(QFont("Inter", 8, QFont.Weight.Bold))
        p.setPen(QPen(bar_col if self._text != "--" else qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(0, 4, W - 10, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._text)

class LogWidget(QTextEdit):
    _sig = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Inter", 9, QFont.Weight.Medium))
        self.setStyleSheet(f"""
            QTextEdit {{
                background: transparent;
                color: {C.TEXT};
                border: none;
                padding: 4px;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B};
                border-radius: 2px;
            }}
        """)
        self._queue: list[str] = []
        self._typing  = False
        self._text    = ""
        self._pos     = 0
        self._tag     = "sys"
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._sig.connect(self._enqueue)

    def append_log(self, text: str):
        self._sig.emit(text)

    def _enqueue(self, text: str):
        self._queue.append(text)
        if not self._typing:
            self._next()

    def _next(self):
        if not self._queue:
            self._typing = False
            return
        self._typing = True
        self._text   = self._queue.pop(0)
        self._pos    = 0
        tl = self._text.lower()
        if   tl.startswith("you:"):    self._tag = "you"
        elif tl.startswith("sirius:"): self._tag = "ai"
        elif tl.startswith("file:"):   self._tag = "file"
        elif "err" in tl:              self._tag = "err"
        else:                          self._tag = "sys"
        self._tmr.start(6)

    def _step(self):
        if self._pos < len(self._text):
            ch  = self._text[self._pos]
            cur = self.textCursor()
            fmt = cur.charFormat()
            col = {
                "you":  qcol(C.WHITE),
                "ai":   qcol(C.PRI),
                "err":  qcol(C.RED),
                "file": qcol(C.GREEN),
                "sys":  qcol(C.ACC2),
            }.get(self._tag, qcol(C.TEXT))
            fmt.setForeground(QBrush(col))
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText(ch, fmt)
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            self._pos += 1
        else:
            self._tmr.stop()
            cur = self.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText("\n")
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            QTimer.singleShot(20, self._next)

_FILE_ICONS = {
    "image":   ("fa5s.image",          "#00d4ff"),
    "video":   ("fa5s.video",          "#ff6b00"),
    "audio":   ("fa5s.music",          "#cc44ff"),
    "pdf":     ("fa5s.file-pdf",       "#ff4444"),
    "word":    ("fa5s.file-word",      "#4488ff"),
    "excel":   ("fa5s.file-excel",     "#44bb44"),
    "code":    ("fa5s.code",           "#ffcc00"),
    "archive": ("fa5s.file-archive",   "#ff8844"),
    "pptx":    ("fa5s.file-powerpoint","#ff6622"),
    "text":    ("fa5s.file-alt",       "#aaaaaa"),
    "data":    ("fa5s.cogs",           "#88ddff"),
    "unknown": ("fa5s.paperclip",      "#888888"),
}
_EXT_TO_CAT = {
    **dict.fromkeys(["jpg","jpeg","png","gif","webp","bmp","tiff","svg","ico"], "image"),
    **dict.fromkeys(["mp4","avi","mov","mkv","wmv","flv","webm","m4v"],         "video"),
    **dict.fromkeys(["mp3","wav","ogg","m4a","aac","flac","wma","opus"],        "audio"),
    **dict.fromkeys(["pdf"],                                                     "pdf"),
    **dict.fromkeys(["doc","docx"],                                              "word"),
    **dict.fromkeys(["xls","xlsx","ods"],                                        "excel"),
    **dict.fromkeys(["ppt","pptx"],                                              "pptx"),
    **dict.fromkeys(["py","js","ts","jsx","tsx","html","css","java","c","cpp",
                     "cs","go","rs","rb","php","swift","kt","sh","sql","lua"],   "code"),
    **dict.fromkeys(["zip","rar","tar","gz","7z","bz2","xz"],                   "archive"),
    **dict.fromkeys(["txt","md","rst","log"],                                    "text"),
    **dict.fromkeys(["csv","tsv","json","xml"],                                  "data"),
}

def _file_category(path: Path) -> str:
    return _EXT_TO_CAT.get(path.suffix.lower().lstrip("."), "unknown")

def _fmt_size(size: int) -> str:
    if   size < 1024:    return f"{size} B"
    elif size < 1024**2: return f"{size/1024:.1f} KB"
    elif size < 1024**3: return f"{size/1024**2:.1f} MB"
    else:                return f"{size/1024**3:.1f} GB"


class FileDropZone(QWidget):
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(85)
        self._current_file: str | None = None
        self._hovering  = False
        self._drag_over = False
        self._dash_offset = 0.0
        self._anim_tmr = QTimer(self)
        self._anim_tmr.timeout.connect(self._animate)
        self._anim_tmr.start(40)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._canvas = _DropCanvas(self)
        layout.addWidget(self._canvas)

    def _animate(self):
        self._dash_offset = (self._dash_offset + 0.8) % 20
        self._canvas.update()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drag_over = True; self._canvas.update()

    def dragLeaveEvent(self, e):
        self._drag_over = False; self._canvas.update()

    def dropEvent(self, e: QDropEvent):
        self._drag_over = False
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).is_file():
                self._set_file(path)
        self._canvas.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._browse()

    def enterEvent(self, e):
        self._hovering = True; self._canvas.update()

    def leaveEvent(self, e):
        self._hovering = False; self._canvas.update()

    def current_file(self) -> str | None:
        return self._current_file

    def clear_file(self):
        self._current_file = None; self._canvas.update()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a file for SIRIUS", str(Path.home()),
            "All Files (*.*);;"
            "Images (*.jpg *.jpeg *.png *.gif *.webp *.bmp *.svg);;"
            "Documents (*.pdf *.docx *.txt *.md *.pptx);;"
            "Data (*.csv *.xlsx *.json *.xml);;"
            "Code (*.py *.js *.ts *.html *.css *.java *.cpp *.go);;"
            "Audio (*.mp3 *.wav *.ogg *.m4a *.aac *.flac);;"
            "Video (*.mp4 *.avi *.mov *.mkv *.wmv *.webm);;"
            "Archives (*.zip *.rar *.tar *.gz *.7z)",
        )
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self._current_file = path
        self._canvas.update()
        self.file_selected.emit(path)


class _DropCanvas(QWidget):
    def __init__(self, zone: FileDropZone):
        super().__init__(zone)
        self._z = zone

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        z    = self._z
        W, H = self.width(), self.height()
        pad  = 6
        rect = QRectF(pad, pad, W - pad * 2, H - pad * 2)

        bg_col = qcol("#151515" if z._drag_over else ("#0f0f0f" if z._hovering else C.PANEL))
        p.setBrush(QBrush(bg_col)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 10, 10)

        if z._current_file:   border_col = qcol(C.GREEN, 150)
        elif z._drag_over:    border_col = qcol(C.PRI, 180)
        elif z._hovering:     border_col = qcol(C.BORDER_B, 180)
        else:                 border_col = qcol(C.BORDER, 100)

        pen = QPen(border_col, 1, Qt.PenStyle.SolidLine) # Solid line for cleaner look
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 10, 10)

        if z._current_file:   self._paint_file(p, W, H)
        elif z._drag_over:    self._paint_drag_over(p, W, H)
        else:                 self._paint_idle(p, W, H, z._hovering)

    def _paint_idle(self, p, W, H, hover):
        cx, cy = W / 2, H / 2
        col = qcol(C.TEXT_MED if not hover else C.PRI)
        p.setFont(QFont("Inter", 9))
        p.setPen(QPen(col, 1))
        p.drawText(QRectF(0, 0, W, H), Qt.AlignmentFlag.AlignCenter,
                   "Drop file  or  Browse")

    def _paint_drag_over(self, p, W, H):
        cx, cy = W / 2, H / 2
        qta.icon("fa5s.arrow-down", color=C.PRI).paint(
            p, QRectF(cx - 16, cy - 28, 32, 32).toRect())
        p.setFont(QFont("Inter", 8, QFont.Weight.Medium))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy + 12, W, 16), Qt.AlignmentFlag.AlignCenter, "Release to load")

    def _paint_file(self, p, W, H):
        path = Path(self._z._current_file)
        cat  = _file_category(path)
        icon_name, icon_col = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size_str = _fmt_size(path.stat().st_size)
        ext_str  = path.suffix.upper().lstrip(".") or "FILE"

        block_x, block_w = 10, 60
        icol = qta.icon(icon_name, color=icon_col)
        icol.paint(p, QRectF(block_x + 4, 10, 52, 52).toRect())

        tx = block_x + block_w + 6
        tw = W - tx - 38

        p.setFont(QFont("Inter", 8, QFont.Weight.Medium))
        p.setPen(QPen(qcol(C.WHITE), 1))
        name = path.name if len(path.name) <= 34 else path.name[:31] + "..."
        p.drawText(QRectF(tx, H * 0.18, tw, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)

        p.setFont(QFont("Inter", 7))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(tx, H * 0.18 + 18, tw, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{ext_str}  ·  {size_str}")

        p.setFont(QFont("Courier New", 6))
        p.setPen(QPen(qcol("#1e5c6a"), 1))
        par = str(path.parent)
        if len(par) > 42: par = "…" + par[-41:]
        p.drawText(QRectF(tx, H * 0.18 + 34, tw, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, par)

        qta.icon("fa5s.times", color=qcol(C.RED, 180).name()).paint(
            p, QRectF(W - 32, 6, 24, 62).toRect())

    def mousePressEvent(self, e):
        z = self._z
        if z._current_file and e.pos().x() > self.width() - 34:
            z.clear_file()
        else:
            z.mousePressEvent(e)


class SetupOverlay(QWidget):
    done = pyqtSignal(str, str, str) # Added or_key

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SetupOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)

        detected = {"darwin": "mac", "windows": "windows"}.get(
            _OS.lower(), "linux"
        )
        self._sel_os = detected

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 22, 30, 22)
        layout.setSpacing(8)

        def _lbl(txt, font_size=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont("Courier New", font_size,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        init_title = QHBoxLayout(); init_title.setSpacing(8)
        init_icon = QLabel()
        init_icon.setPixmap(qta.icon("fa5s.cog").pixmap(18, 18))
        init_icon.setStyleSheet("background: transparent;")
        init_title.addWidget(init_icon)
        init_title.addWidget(_lbl("INITIALISATION REQUIRED", 13, True))
        init_title.addStretch()
        layout.addLayout(init_title)
        layout.addWidget(_lbl("Configure SIRIUS before first boot.", 9, color=C.PRI_DIM))
        layout.addSpacing(6)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep)
        layout.addSpacing(4)

        layout.addWidget(_lbl("GEMINI API KEY", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText("AIza…")
        self._key_input.setFont(QFont("Courier New", 10))
        self._key_input.setFixedHeight(32)
        self._key_input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d12; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        layout.addWidget(self._key_input)
        layout.addSpacing(8)

        layout.addWidget(_lbl("OPENROUTER API KEY (Optional for memory)", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        self._or_input = QLineEdit()
        self._or_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._or_input.setPlaceholderText("sk-or-…")
        self._or_input.setFont(QFont("Courier New", 10))
        self._or_input.setFixedHeight(32)
        self._or_input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d12; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        layout.addWidget(self._or_input)
        layout.addSpacing(12)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep2)
        layout.addSpacing(4)

        layout.addWidget(_lbl("OPERATING SYSTEM", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        det_name = {"windows": "Windows", "mac": "macOS", "linux": "Linux"}[detected]
        layout.addWidget(_lbl(f"Auto-detected: {det_name}", 8, color=C.ACC2,
                               align=Qt.AlignmentFlag.AlignLeft))

        os_row = QHBoxLayout(); os_row.setSpacing(6)
        self._os_btns: dict[str, QPushButton] = {}
        for key, label, ico in [("windows","Windows", "fa5b.windows"),
                                ("mac","macOS",    "fa5b.apple"),
                                ("linux","Linux",  "fa5b.linux")]:
            btn = QPushButton(label)
            btn.setIcon(qta.icon(ico))
            btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            btn.setFixedHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._sel(k))
            os_row.addWidget(btn)
            self._os_btns[key] = btn
        layout.addLayout(os_row)
        self._sel(detected)
        layout.addSpacing(12)

        init_btn = QPushButton("INITIALISE SYSTEMS")
        init_btn.setIcon(qta.icon("fa5s.arrow-right"))
        init_btn.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        init_btn.setFixedHeight(36)
        init_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        init_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C.PRI_GHO}; border: 1px solid {C.PRI};
            }}
        """)
        init_btn.clicked.connect(self._submit)
        layout.addWidget(init_btn)

    def _sel(self, key: str):
        self._sel_os = key
        pal = {"windows":(C.PRI,"#001a22"),"mac":(C.ACC2,"#1a1400"),"linux":(C.GREEN,"#001a0d")}
        for k, btn in self._os_btns.items():
            if k == key:
                fg, bg = pal[k]
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {fg}; color: {bg};
                        border: none; border-radius: 3px; font-weight: bold;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: #000d12; color: {C.TEXT_DIM};
                        border: 1px solid {C.BORDER}; border-radius: 3px;
                    }}
                    QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
                """)

    def _submit(self):
        key = self._key_input.text().strip()
        or_key = self._or_input.text().strip()
        if not key:
            self._key_input.setStyleSheet(
                self._key_input.styleSheet() +
                f" QLineEdit {{ border: 1px solid {C.RED}; }}"
            )
            return
        self.done.emit(key, or_key, self._sel_os)


# ─────────────────────────────────────────────────────────────────────────────
# ToggleSwitch – animated pill-style boolean switch
# ─────────────────────────────────────────────────────────────────────────────
class ToggleSwitch(QWidget):
    """Smooth animated toggle switch (pill style)."""
    toggled = pyqtSignal(bool)

    def __init__(self, checked: bool = True, parent=None):
        super().__init__(parent)
        self._checked = checked
        self._pos     = 1.0 if checked else 0.0
        self._target  = self._pos
        self.setFixedSize(46, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)

    def set_checked(self, v: bool):
        if v == self._checked:
            return
        self._checked = v
        self._target  = 1.0 if v else 0.0
        if not self._tmr.isActive():
            self._tmr.start(16)

    def is_checked(self) -> bool:
        return self._checked

    def _step(self):
        diff = self._target - self._pos
        if abs(diff) < 0.03:
            self._pos = self._target
            self._tmr.stop()
        else:
            self._pos += diff * 0.25
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._checked = not self._checked
            self._target  = 1.0 if self._checked else 0.0
            if not self._tmr.isActive():
                self._tmr.start(16)
            self.toggled.emit(self._checked)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        r    = H / 2
        # Interpolate track colour
        c_off = QColor(C.BORDER_B)
        c_on  = QColor(C.GREEN_D)
        t     = self._pos
        track = QColor(
            int(c_off.red()   + (c_on.red()   - c_off.red())   * t),
            int(c_off.green() + (c_on.green() - c_off.green()) * t),
            int(c_off.blue()  + (c_on.blue()  - c_off.blue())  * t),
        )
        p.setBrush(QBrush(track))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(0, 0, W, H), r, r)
        mg = 3
        kd = H - mg * 2
        kx = mg + self._pos * (W - kd - mg * 2)
        p.setBrush(QBrush(qcol(C.WHITE)))
        p.drawEllipse(QRectF(kx, mg, kd, kd))


# ─────────────────────────────────────────────────────────────────────────────
# SettingsOverlay  –  redesigned with sidebar (Geral / Permissões)
# ─────────────────────────────────────────────────────────────────────────────
class SettingsOverlay(QWidget):
    done = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SettingsOverlay {{
                background: rgba(5, 8, 14, 252);
                border: 1px solid {C.BORDER_B};
                border-radius: 10px;
            }}
        """)
        self._perm_toggles: dict = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────
        hdr = QWidget()
        hdr.setFixedHeight(46)
        hdr.setStyleSheet(f"""
            background: {C.DARK};
            border-top-left-radius: 10px;
            border-top-right-radius: 10px;
            border-bottom: 1px solid {C.BORDER};
        """)
        hdr_lay = QHBoxLayout(hdr)
        hdr_lay.setContentsMargins(18, 0, 12, 0)
        title_icon = QLabel()
        title_icon.setPixmap(qta.icon("fa5s.cog").pixmap(18, 18))
        title_icon.setStyleSheet("background: transparent;")
        hdr_lay.addWidget(title_icon)
        title_lbl = QLabel("CONFIGURAÇÕES")
        title_lbl.setFont(QFont("Inter", 10, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        hdr_lay.addWidget(title_lbl)
        hdr_lay.addStretch()
        close_btn = QPushButton()
        close_btn.setIcon(qta.icon("fa5s.times"))
        close_btn.setFixedSize(28, 28)
        close_btn.setFont(QFont("Inter", 9))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_DIM}; border: none; border-radius: 4px; }}
            QPushButton:hover {{ color: {C.RED}; background: rgba(255,51,85,0.10); }}
        """)
        close_btn.clicked.connect(self._save)
        hdr_lay.addWidget(close_btn)
        root.addWidget(hdr)

        # ── Body: Sidebar + Stack ──────────────────────────────
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # Sidebar
        sidebar = QWidget()
        sidebar.setFixedWidth(120)
        sidebar.setStyleSheet(f"""
            background: {C.PANEL};
            border-right: 1px solid {C.BORDER};
            border-bottom-left-radius: 10px;
        """)
        sb_lay = QVBoxLayout(sidebar)
        sb_lay.setContentsMargins(8, 14, 8, 14)
        sb_lay.setSpacing(5)
        self._tabs: dict = {}
        for key, ico, label in [
            ("general",     "fa5s.cog", "GERAL"),
            ("permissions", "fa5s.shield-alt", "PERMISSÕES"),
        ]:
            btn = QPushButton(f"  {label}")
            btn.setIcon(qta.icon(ico))
            btn.setFixedHeight(36)
            btn.setFont(QFont("Inter", 7, QFont.Weight.Bold))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._switch_tab(k))
            sb_lay.addWidget(btn)
            self._tabs[key] = btn
        sb_lay.addStretch()
        body.addWidget(sidebar)

        # Content stack
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: transparent;")
        body.addWidget(self._stack, stretch=1)
        root.addLayout(body, stretch=1)

        # Build pages
        self._stack.addWidget(self._build_general_page())
        self._stack.addWidget(self._build_permissions_page())
        self._switch_tab("general")
        self._load()

    # ── Tab switching ──────────────────────────────────────────
    def _switch_tab(self, key: str):
        self._stack.setCurrentIndex({"general": 0, "permissions": 1}.get(key, 0))
        for k, btn in self._tabs.items():
            if k == key:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {C.PRI_GHO}; color: {C.PRI};
                        border: 1px solid {C.PRI_DIM}; border-radius: 6px; text-align: left;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: transparent; color: {C.TEXT_DIM};
                        border: 1px solid transparent; border-radius: 6px; text-align: left;
                    }}
                    QPushButton:hover {{ background: {C.PANEL2}; color: {C.TEXT_MED}; }}
                """)

    # ── General page ───────────────────────────────────────────
    def _build_general_page(self) -> QWidget:
        page = QWidget(); page.setStyleSheet("background: transparent;")
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea {{ border: none; background: transparent; }}
            QScrollBar:vertical {{ background: #080808; width: 6px; border-radius: 3px; }}
            QScrollBar::handle:vertical {{ background: {C.BORDER}; border-radius: 3px; }}
            QScrollBar::handle:vertical:hover {{ background: {C.PRI}; }}
        """)
        content = QWidget(); content.setStyleSheet("background: transparent;")
        layout  = QVBoxLayout(content)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        def _lbl(txt, sz=8, bold=False, color=C.TEXT_DIM, align=Qt.AlignmentFlag.AlignLeft):
            w = QLabel(txt); w.setAlignment(align)
            w.setFont(QFont("Inter", sz, QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        def _inp(password=True, ph=""):
            e = QLineEdit()
            if password: e.setEchoMode(QLineEdit.EchoMode.Password)
            e.setFont(QFont("Courier New", 9))
            e.setFixedHeight(30); e.setPlaceholderText(ph)
            e.setStyleSheet(f"""
                QLineEdit {{ background: #080808; color: {C.TEXT};
                    border: 1px solid {C.BORDER}; border-radius: 4px; padding: 4px 8px; }}
                QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
            """)
            return e

        def _sep():
            f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
            f.setStyleSheet(f"color: {C.BORDER}; margin: 6px 0;"); return f

        layout.addWidget(_lbl("GEMINI API KEY", bold=True, color=C.PRI))
        self._key_input = _inp(ph="AIza…")
        layout.addWidget(self._key_input)

        layout.addWidget(_lbl("OPENROUTER API KEY"))
        self._or_input = _inp(ph="sk-or-…")
        layout.addWidget(self._or_input)

        layout.addWidget(_sep())
        layout.addWidget(_lbl("DEEP RESEARCH APIs (Opcional)", bold=True, color=C.ACC2))
        layout.addWidget(_lbl("TAVILY API KEY"))
        self._tavily_input = _inp(ph="Opcional - para busca avançada")
        layout.addWidget(self._tavily_input)
        layout.addWidget(_lbl("SERPAPI KEY"))
        self._serpapi_input = _inp(ph="Opcional - para Google Places/Maps")
        layout.addWidget(self._serpapi_input)

        layout.addWidget(_sep())
        layout.addWidget(_lbl("SISTEMA OPERACIONAL", bold=True, color=C.TEXT_MED))
        os_row = QHBoxLayout(); os_row.setSpacing(5)
        self._os_btns = {}
        for k, v, ico in [("windows","Win", "fa5b.windows"),
                          ("mac","Mac",    "fa5b.apple"),
                          ("linux","Lin",  "fa5b.linux")]:
            btn = QPushButton(v); btn.setFixedHeight(28)
            btn.setIcon(qta.icon(ico))
            btn.setFont(QFont("Inter", 7, QFont.Weight.Medium))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, x=k: self._set_os(x))
            os_row.addWidget(btn); self._os_btns[k] = btn
        layout.addLayout(os_row)

        layout.addWidget(_sep())
        layout.addWidget(_lbl("INTEGRAÇÕES", bold=True, color=C.ACC2))
        layout.addWidget(_lbl("GOOGLE CLIENT ID"))
        self._g_id = _inp(password=False)
        layout.addWidget(self._g_id)
        layout.addWidget(_lbl("GOOGLE CLIENT SECRET"))
        self._g_secret = _inp()
        layout.addWidget(self._g_secret)

        self._g_btn = QPushButton("Connect Google Account")
        self._g_btn.setFixedHeight(30)
        self._g_btn.setFont(QFont("Inter", 8))
        self._g_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._g_btn.setStyleSheet(f"""
            QPushButton {{ background: {C.PANEL2}; color: {C.WHITE};
                border: 1px solid {C.BORDER_B}; border-radius: 4px; }}
            QPushButton:hover {{ background: {C.PRI_DIM}; border: 1px solid {C.PRI}; }}
        """)
        self._g_btn.clicked.connect(self._google_auth)
        layout.addWidget(self._g_btn)
        g_status_row = QHBoxLayout(); g_status_row.setSpacing(6)
        self._g_status_icon = QLabel()
        self._g_status_icon.setFixedSize(14, 14)
        self._g_status_icon.setStyleSheet("background: transparent;")
        g_status_row.addWidget(self._g_status_icon)
        self._g_status = QLabel("Not connected")
        self._g_status.setFont(QFont("Inter", 7))
        self._g_status.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        g_status_row.addWidget(self._g_status)
        g_status_row.addStretch()
        layout.addLayout(g_status_row)

        layout.addStretch()
        save_btn = QPushButton("SALVAR E FECHAR")
        save_btn.setFixedHeight(34); save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setFont(QFont("Inter", 8, QFont.Weight.Bold))
        save_btn.setStyleSheet(f"""
            QPushButton {{ background: {C.PRI}; color: {C.BG}; border: none; border-radius: 4px; }}
            QPushButton:hover {{ background: {C.WHITE}; }}
        """)
        save_btn.clicked.connect(self._save)
        layout.addWidget(save_btn)

        scroll.setWidget(content)
        outer = QVBoxLayout(page); outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        return page

    # ── Permissions page ───────────────────────────────────────
    def _build_permissions_page(self) -> QWidget:
        from config.permissions import PERMISSION_META, get_permissions
        page = QWidget(); page.setStyleSheet("background: transparent;")
        outer = QVBoxLayout(page); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)

        # Top bar with bulk-toggle buttons
        top = QWidget()
        top.setStyleSheet(f"background: {C.PANEL}; border-bottom: 1px solid {C.BORDER};")
        top_lay = QHBoxLayout(top); top_lay.setContentsMargins(16, 8, 16, 8)
        desc = QLabel("Controle o que o Sirius pode fazer no seu computador.")
        desc.setFont(QFont("Inter", 7))
        desc.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        top_lay.addWidget(desc, stretch=1)
        for label, color, val in [("Marcar Todos", C.GREEN, True), ("Desmarcar Todos", C.RED, False)]:
            b = QPushButton(label); b.setFixedHeight(24)
            b.setFont(QFont("Inter", 7, QFont.Weight.Medium))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(f"""
                QPushButton {{ background: transparent; color: {color};
                    border: 1px solid {color}44; border-radius: 4px; padding: 0 8px; }}
                QPushButton:hover {{ background: {color}22; border: 1px solid {color}; }}
            """)
            b.clicked.connect(lambda _, v=val: self._toggle_all(v))
            top_lay.addWidget(b)
        outer.addWidget(top)

        # Scrollable list
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea {{ border: none; background: transparent; }}
            QScrollBar:vertical {{ background: #080808; width: 6px; border-radius: 3px; }}
            QScrollBar::handle:vertical {{ background: {C.BORDER}; border-radius: 3px; }}
            QScrollBar::handle:vertical:hover {{ background: {C.PRI}; }}
        """)
        content = QWidget(); content.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(content)
        lay.setContentsMargins(12, 10, 12, 12); lay.setSpacing(7)
        perms = get_permissions()
        for perm_key, meta in PERMISSION_META.items():
            lay.addWidget(self._build_perm_row(perm_key, meta, perms.get(perm_key, True)))
        lay.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)
        return page

    def _build_perm_row(self, perm_key: str, meta: dict, enabled: bool) -> QWidget:
        row = QWidget()
        row.setFixedHeight(64)
        row.setStyleSheet(f"""
            QWidget {{ background: {C.PANEL2}; border: 1px solid {C.BORDER}; border-radius: 8px; }}
            QWidget:hover {{ border: 1px solid {C.BORDER_B}; }}
        """)
        lay = QHBoxLayout(row); lay.setContentsMargins(12, 0, 12, 0); lay.setSpacing(10)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon(meta.get("icon", "fa5s.circle")).pixmap(24, 24))
        icon_lbl.setFixedWidth(32)
        icon_lbl.setStyleSheet("background: transparent;")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(icon_lbl)

        txt_col = QVBoxLayout(); txt_col.setSpacing(2)
        name_lbl = QLabel(meta.get("label", perm_key))
        name_lbl.setFont(QFont("Inter", 8, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        desc_lbl = QLabel(meta.get("description", ""))
        desc_lbl.setFont(QFont("Inter", 7))
        desc_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        txt_col.addWidget(name_lbl); txt_col.addWidget(desc_lbl)
        lay.addLayout(txt_col, stretch=1)

        toggle = ToggleSwitch(checked=enabled)
        toggle.toggled.connect(lambda v, k=perm_key: self._on_perm_toggle(k, v))
        lay.addWidget(toggle)
        self._perm_toggles[perm_key] = toggle
        return row

    def _on_perm_toggle(self, perm_key: str, value: bool):
        from config.permissions import get_permissions, save_permissions
        perms = get_permissions(); perms[perm_key] = value; save_permissions(perms)

    def _toggle_all(self, value: bool):
        from config.permissions import get_permissions, save_permissions
        perms = get_permissions()
        for k in perms: perms[k] = value
        save_permissions(perms)
        for toggle in self._perm_toggles.values(): toggle.set_checked(value)

    # ── OS selection ───────────────────────────────────────────
    def _set_os(self, key: str):
        self._os_name = key
        for k, b in self._os_btns.items():
            if k == key:
                b.setStyleSheet(f"background: {C.PRI}; color: {C.BG}; border: none; border-radius: 3px;")
            else:
                b.setStyleSheet(f"background: #080808; color: {C.TEXT_DIM}; border: 1px solid {C.BORDER}; border-radius: 3px;")

    # ── Load / Save ────────────────────────────────────────────
    def _load(self):
        if API_FILE.exists():
            try:
                d = json.loads(API_FILE.read_text(encoding="utf-8"))
                self._key_input.setText(d.get("gemini_api_key", ""))
                self._or_input.setText(d.get("openrouter_api_key", ""))
                self._tavily_input.setText(d.get("tavily_api_key", ""))
                self._serpapi_input.setText(d.get("serpapi_key", ""))
                self._set_os(d.get("os_system", "windows"))
                g = d.get("google_creds", {})
                self._g_id.setText(g.get("client_id", ""))
                self._g_secret.setText(g.get("client_secret", ""))
                if (BASE_DIR / "config" / "google_token.json").exists():
                    self._g_status_icon.setPixmap(qta.icon("fa5s.check-circle", color=C.GREEN).pixmap(14, 14))
                    self._g_status.setText("Google Connected")
                    self._g_status.setStyleSheet(f"color: {C.GREEN};")
            except Exception:
                pass

    def _google_auth(self):
        self._save_keys_only()
        self._g_status_icon.setPixmap(qta.icon("fa5s.spinner").pixmap(14, 14))
        self._g_status.setText("Authorizing in browser...")
        self._g_status.setStyleSheet(f"color: {C.ACC2};")
        QApplication.processEvents()
        def _run():
            from core.google_auth import run_auth_flow
            ok, msg = run_auth_flow()
            if ok:
                self._g_status_icon.setPixmap(qta.icon("fa5s.check-circle", color=C.GREEN).pixmap(14, 14))
                self._g_status.setText(msg)
                self._g_status.setStyleSheet(f"color: {C.GREEN};")
            else:
                self._g_status_icon.setPixmap(qta.icon("fa5s.times-circle", color=C.RED).pixmap(14, 14))
                self._g_status.setText(msg)
                self._g_status.setStyleSheet(f"color: {C.RED};")
        threading.Thread(target=_run, daemon=True).start()

    def _save(self):
        self._save_keys_only()
        self.done.emit()
        self.hide()

    def _save_keys_only(self):
        key      = self._key_input.text().strip()
        os_name  = getattr(self, "_os_name", "windows")
        g_id     = self._g_id.text().strip()
        g_secret = self._g_secret.text().strip()
        d = {}
        if API_FILE.exists():
            try: d = json.loads(API_FILE.read_text(encoding="utf-8"))
            except Exception: pass
        d["gemini_api_key"]    = key
        d["openrouter_api_key"] = self._or_input.text().strip()
        d["tavily_api_key"]    = self._tavily_input.text().strip()
        d["serpapi_key"]       = self._serpapi_input.text().strip()
        d["os_system"]         = os_name
        d["google_creds"]      = {"client_id": g_id, "client_secret": g_secret}
        os.makedirs(CONFIG_DIR, exist_ok=True)
        API_FILE.write_text(json.dumps(d, indent=4), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# PermissionRequestDialog  –  runtime permission popup
# ─────────────────────────────────────────────────────────────────────────────
class PermissionRequestDialog(QWidget):
    """Floating card shown when a tool's permission is currently disabled."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            PermissionRequestDialog {{
                background: rgba(6, 10, 18, 248);
                border: 1px solid {C.PRI_DIM};
                border-radius: 12px;
            }}
        """)
        self._callback = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(8)

        # Header row
        hdr_row = QHBoxLayout()
        self._icon_lbl = QLabel()
        self._icon_lbl.setPixmap(qta.icon("fa5s.key").pixmap(28, 28))
        self._icon_lbl.setStyleSheet("background: transparent;")
        self._icon_lbl.setFixedWidth(34)
        hdr_row.addWidget(self._icon_lbl)
        hdr_txt = QVBoxLayout(); hdr_txt.setSpacing(1)
        title_lbl = QLabel("SOLICITAÇÃO DE PERMISSÃO")
        title_lbl.setFont(QFont("Inter", 8, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr_txt.addWidget(title_lbl)
        self._sub_lbl = QLabel("")
        self._sub_lbl.setFont(QFont("Inter", 7))
        self._sub_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        hdr_txt.addWidget(self._sub_lbl)
        hdr_row.addLayout(hdr_txt, stretch=1)
        lay.addLayout(hdr_row)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};")
        lay.addWidget(sep)

        self._perm_lbl = QLabel("")
        self._perm_lbl.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        self._perm_lbl.setStyleSheet(f"color: {C.WHITE}; background: transparent;")
        lay.addWidget(self._perm_lbl)

        self._detail_lbl = QLabel("")
        self._detail_lbl.setFont(QFont("Inter", 7))
        self._detail_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._detail_lbl.setWordWrap(True)
        lay.addWidget(self._detail_lbl)

        # Action buttons
        btn_row = QHBoxLayout(); btn_row.setSpacing(6)
        for label, color, decision in [
            ("Permitir uma vez", C.PRI,   "once"),
            ("Permitir sempre",  C.GREEN, "always"),
            ("Recusar",          C.RED,   "deny"),
        ]:
            btn = QPushButton(label)
            btn.setFixedHeight(28)
            btn.setFont(QFont("Inter", 7, QFont.Weight.Medium))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {color};
                    border: 1px solid {color}55; border-radius: 5px; padding: 0 8px;
                }}
                QPushButton:hover {{ background: {color}22; border: 1px solid {color}; }}
            """)
            btn.clicked.connect(lambda _, d=decision: self._respond(d))
            btn_row.addWidget(btn)
        lay.addLayout(btn_row)
        self.hide()

    def request(self, perm_key: str, label: str, tool_name: str, callback):
        """Populate and show the dialog."""
        try:
            from config.permissions import PERMISSION_META
            meta = PERMISSION_META.get(perm_key, {})
            icon_name = meta.get("icon", "fa5s.key")
            desc = meta.get("description", "")
        except Exception:
            icon_name, desc = "fa5s.key", ""
        self._icon_lbl.setPixmap(qta.icon(icon_name).pixmap(28, 28))
        self._sub_lbl.setText(f"Ferramenta: {tool_name}")
        self._perm_lbl.setText(f'"{label}"')
        self._detail_lbl.setText(desc)
        self._callback = callback
        self.show()
        self.raise_()

    def _respond(self, decision: str):
        self.hide()
        if self._callback:
            cb, self._callback = self._callback, None
            cb(decision)


class MainWindow(QMainWindow):
    _log_sig   = pyqtSignal(str)
    _state_sig = pyqtSignal(str)
    _perm_sig  = pyqtSignal(str, str, str)  # perm_key, label, tool_name

    def __init__(self):
        super().__init__()
        self.setWindowTitle("SIRIUS")
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.resize(_DEFAULT_W, _DEFAULT_H)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width()  - _DEFAULT_W) // 2,
            (screen.height() - _DEFAULT_H) // 2,
        )

        self.on_text_command  = None
        self._muted           = False
        self._current_file: str | None = None

        central = QWidget()
        central.setStyleSheet(f"background: {C.BG};")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.hud = HudCanvas()
        self.hud.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        body.addWidget(self.hud, stretch=5)

        self._right_panel = self._build_right_panel()
        body.addWidget(self._right_panel, stretch=0)

        root.addLayout(body, stretch=1)
        root.addWidget(self._build_footer())

        self._settings_overlay: SettingsOverlay | None = None
        self._perm_dialog:      PermissionRequestDialog | None = None
        self._perm_event  = threading.Event()
        self._perm_result = "deny"
        self._perm_sig.connect(self._show_perm_request)

        self._set_icon()
        self._log_sig.connect(self._log.append_log)
        self._state_sig.connect(self._apply_state)

        self._overlay: SetupOverlay | None = None
        self._ready = self._check_config()
        if not self._ready:
            self._show_setup()

        self._clock_tmr = QTimer(self)
        self._clock_tmr.timeout.connect(self._tick_clock)
        self._clock_tmr.start(1000)
        self._tick_clock()

        sc_mute = QShortcut(QKeySequence("F4"), self)
        sc_mute.activated.connect(self._toggle_mute)
        sc_full = QShortcut(QKeySequence("F11"), self)
        sc_full.activated.connect(self._toggle_fullscreen)

    def _set_icon(self):
        from PyQt6.QtGui import QIcon
        base = _base_dir()
        for name in ("face.ico", "face.png"):
            p = base / name
            if p.exists():
                self.setWindowIcon(QIcon(str(p)))
                break

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._overlay and self._overlay.isVisible():
            ow, oh = 460, 390
            cw = self.centralWidget()
            self._overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )
        if self._settings_overlay and self._settings_overlay.isVisible():
            ow, oh = 600, 560
            cw = self.centralWidget()
            self._settings_overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )
        if self._perm_dialog and self._perm_dialog.isVisible():
            pw, ph = 420, 168
            cw = self.centralWidget()
            self._perm_dialog.setGeometry(
                (cw.width() - pw) // 2,
                cw.height() - ph - 26,
                pw, ph,
            )


    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(60)
        w.setStyleSheet(f"background: {C.DARK};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(20, 0, 20, 0)

        def _badge(txt, color=C.TEXT_MED):
            l = QLabel(txt)
            l.setFont(QFont("Courier New", 8))
            l.setStyleSheet(f"color: {color}; background: transparent;")
            return l

        lay.addStretch()

        mid = QVBoxLayout(); mid.setSpacing(1)
        lay.addLayout(mid)
        lay.addStretch()

        right_col = QVBoxLayout(); right_col.setSpacing(2)
        self._clock_lbl = QLabel("00:00:00")
        self._clock_lbl.setFont(QFont("Inter", 12, QFont.Weight.Bold))
        self._clock_lbl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        self._clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._clock_lbl)
        self._date_lbl = QLabel("")
        self._date_lbl.setFont(QFont("Inter", 7))
        self._date_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self._date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._date_lbl)
        lay.addLayout(right_col)
        return w

    def _tick_clock(self):
        self._clock_lbl.setText(time.strftime("%H:%M:%S"))
        self._date_lbl.setText(time.strftime("%a %d %b %Y"))

    def _build_right_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(_RIGHT_W)
        w.setStyleSheet(f"background: {C.PANEL};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        def _sec(txt):
            row = QHBoxLayout(); row.setSpacing(6)
            ico = QLabel()
            ico.setPixmap(qta.icon("fa5s.caret-right").pixmap(8, 12))
            ico.setStyleSheet("background: transparent;")
            row.addWidget(ico)
            l = QLabel(txt)
            l.setFont(QFont("Inter", 7, QFont.Weight.Medium))
            l.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
            row.addWidget(l)
            row.addStretch()
            w = QWidget()
            w.setLayout(row)
            return w

        lay.addWidget(_sec("LOGS"))
        self._log = LogWidget()
        lay.addWidget(self._log, stretch=1)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        lay.addWidget(_sec("FILE UPLOAD"))
        self._drop_zone = FileDropZone()
        self._drop_zone.file_selected.connect(self._on_file_selected)
        lay.addWidget(self._drop_zone)

        file_hint_row = QHBoxLayout(); file_hint_row.setSpacing(6)
        self._file_icon_lbl = QLabel()
        self._file_icon_lbl.setFixedSize(16, 16)
        self._file_icon_lbl.setStyleSheet("background: transparent;")
        file_hint_row.addWidget(self._file_icon_lbl)
        self._file_hint = QLabel("No file loaded — drop or click above to upload")
        self._file_hint.setFont(QFont("Inter", 7))
        self._file_hint.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._file_hint.setWordWrap(True)
        file_hint_row.addWidget(self._file_hint, stretch=1)
        lay.addLayout(file_hint_row)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep2)

        lay.addWidget(_sec("COMMAND INPUT"))
        lay.addLayout(self._build_input_row())

        self._mute_btn = QPushButton("MICROPHONE ACTIVE")
        self._mute_btn.setFixedHeight(30)
        self._mute_btn.setFont(QFont("Inter", 8, QFont.Weight.Medium))
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._toggle_mute)
        self._style_mute_btn()
        lay.addWidget(self._mute_btn)

        fs_btn = QPushButton("FULLSCREEN  [F11]")
        fs_btn.setIcon(qta.icon("fa5s.expand"))
        fs_btn.setFixedHeight(26)
        fs_btn.setFont(QFont("Inter", 7))
        fs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        fs_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{
                color: {C.PRI}; border: 1px solid {C.BORDER_B};
            }}
        """)
        fs_btn.clicked.connect(self._toggle_fullscreen)
        lay.addWidget(fs_btn)

        return w

    def _build_input_row(self) -> QHBoxLayout:
        row = QHBoxLayout(); row.setSpacing(5)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a command or question…")
        self._input.setFont(QFont("Inter", 9))
        self._input.setFixedHeight(30)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d14; color: {C.WHITE};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 3px 7px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        self._input.returnPressed.connect(self._send)
        row.addWidget(self._input)

        send = QPushButton()
        send.setIcon(qta.icon("fa5s.arrow-right", color=C.PRI))
        send.setFixedSize(32, 32)
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL2}; color: {C.PRI};
                border: none; border-radius: 4px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; }}
        """)
        send.clicked.connect(self._send)
        row.addWidget(send)
        return row

    def _build_footer(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(22)
        w.setStyleSheet(f"background: {C.DARK}; border-top: 1px solid {C.BORDER};")
        lay = QHBoxLayout(w); lay.setContentsMargins(14, 0, 14, 0)

        def _fl(txt, color=C.TEXT_MED):
            l = QLabel(txt); l.setFont(QFont("Inter", 7))
            l.setStyleSheet(f"color: {color}; background: transparent;")
            return l

        lay.addWidget(_fl("[F4] Mute  ·  [F11] Fullscreen"))
        lay.addStretch()
        lay.addWidget(_fl(""))
        lay.addStretch()

        self._settings_btn = QPushButton()
        self._settings_btn.setIcon(qta.icon("fa5s.cog", color=C.TEXT_MED))
        self._settings_btn.setFixedSize(18, 18)
        self._settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._settings_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: none; padding: 0;
            }}
            QPushButton:hover {{ color: {C.PRI}; }}
        """)
        self._settings_btn.clicked.connect(self._show_settings)
        lay.addWidget(self._settings_btn)

        return w

    def _show_settings(self):
        if not self._settings_overlay:
            self._settings_overlay = SettingsOverlay(self.centralWidget())
            self._settings_overlay.hide()

        cw = self.centralWidget()
        ow, oh = 600, 560
        self._settings_overlay.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        self._settings_overlay.show()
        self._settings_overlay.raise_()

    def _show_perm_request(self, perm_key: str, label: str, tool_name: str):
        """Called on the main thread via signal. Shows the PermissionRequestDialog."""
        if not self._perm_dialog:
            self._perm_dialog = PermissionRequestDialog(self.centralWidget())
        pw, ph = 420, 168
        cw = self.centralWidget()
        self._perm_dialog.setGeometry(
            (cw.width() - pw) // 2,
            cw.height() - ph - 26,
            pw, ph,
        )
        def _callback(decision: str):
            self._perm_result = decision
            self._perm_event.set()
        self._perm_dialog.request(perm_key, label, tool_name, _callback)

    def _on_file_selected(self, path: str):
        self._current_file = path
        p    = Path(path)
        cat  = _file_category(p)
        icon_name, _ = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size = _fmt_size(p.stat().st_size)
        px = qta.icon(icon_name).pixmap(16, 16)
        self._file_icon_lbl.setPixmap(px)
        self._file_hint.setText(f"{p.name}  ·  {size}  ·  Tell SIRIUS what to do with it")
        self._log.append_log(f"FILE: {p.name} ({size}) loaded")
        if self.on_text_command:
            msg = (
                f"[FILE_UPLOADED] path={path} | name={p.name} | "
                f"type={p.suffix.lstrip('.')} | size={size} | "
                f"Briefly tell the user you can see the file '{p.name}' "
                f"({size}) has been uploaded and ask what they'd like to do with it."
            )
            threading.Thread(target=self.on_text_command, args=(msg,), daemon=True).start()

    def _toggle_mute(self):
        self._muted = not self._muted
        self.hud.muted = self._muted
        self._style_mute_btn()
        if self._muted:
            self._apply_state("MUTED")
            self._log.append_log("SYS: Microphone muted.")
        else:
            self._apply_state("LISTENING")
            self._log.append_log("SYS: Microphone active.")

    def _style_mute_btn(self):
        if self._muted:
            self._mute_btn.setText("MICROPHONE MUTED")
            self._mute_btn.setIcon(qta.icon("fa5s.microphone-slash", color=C.MUTED_C))
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #140006; color: {C.MUTED_C};
                    border: 1px solid {C.MUTED_C}; border-radius: 3px;
                }}
            """)
        else:
            self._mute_btn.setText("MICROPHONE ACTIVE")
            self._mute_btn.setIcon(qta.icon("fa5s.microphone", color=C.GREEN))
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #00140a; color: {C.GREEN};
                    border: 1px solid {C.GREEN}; border-radius: 3px;
                }}
                QPushButton:hover {{ background: #001f10; }}
            """)

    def _send(self):
        txt = self._input.text().strip()
        if not txt: return
        self._input.clear()
        self._log.append_log(f"You: {txt}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(txt,), daemon=True).start()

    def _apply_state(self, state: str):
        self.hud.state    = state
        self.hud.speaking = (state == "SPEAKING")

    def _check_config(self) -> bool:
        if not API_FILE.exists(): return False
        try:
            d = json.loads(API_FILE.read_text(encoding="utf-8"))
            return bool(d.get("gemini_api_key")) and bool(d.get("os_system"))
        except Exception:
            return False

    def _show_setup(self):
        ov = SetupOverlay(self.centralWidget())
        cw = self.centralWidget()
        ow, oh = 460, 390
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.done.connect(self._on_setup_done)
        ov.show()
        self._overlay = ov

    def _on_setup_done(self, key: str, or_key: str, os_name: str):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        API_FILE.write_text(
            json.dumps({
                "gemini_api_key": key,
                "openrouter_api_key": or_key,
                "os_system": os_name
            }, indent=4),
            encoding="utf-8",
        )
        self._ready = True
        if self._overlay:
            self._overlay.hide()
            self._overlay = None
        self._apply_state("LISTENING")
        self._log.append_log(f"System: Initialised. OS={os_name.upper()}. SIRIUS online.")

class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app
    def mainloop(self):
        self._app.exec()
    def protocol(self, *_):
        pass


class SiriusUI:
    def __init__(self):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")

        # Set application-level window icon
        from PyQt6.QtGui import QIcon
        base = _base_dir()
        for name in ("face.ico", "face.png"):
            p = base / name
            if p.exists():
                self._app.setWindowIcon(QIcon(str(p)))
                break

        self._win = MainWindow()
        self._win.show()
        self.root = _RootShim(self._app)

    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        if v != self._win._muted:
            self._win._toggle_mute()

    @property
    def current_file(self) -> str | None:
        return self._win._drop_zone.current_file()

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def set_voice_level(self, level: float):
        """Sets the user voice level (0.0 to 1.0) for visual feedback."""
        if hasattr(self._win, "hud"):
            self._win.hud.voice_level = level

    def write_log(self, text: str):
        self._win._log_sig.emit(text)

    def wait_for_api_key(self):
        while not self._win._ready:
            time.sleep(0.1)

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")

    def ask_permission_sync(self, perm_key: str, label: str, tool_name: str) -> str:
        """Block a background thread until the user responds to a permission request.
        Returns: 'once' | 'always' | 'deny'.  Times out (deny) after 60 seconds."""
        self._win._perm_event.clear()
        self._win._perm_result = "deny"
        self._win._perm_sig.emit(perm_key, label, tool_name)
        self._win._perm_event.wait(timeout=60)
        return self._win._perm_result
