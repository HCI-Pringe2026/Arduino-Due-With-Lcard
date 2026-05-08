"""
dual_sine_controller.py
PySide6 desktop app for controlling the Arduino Due dual-sine DAC firmware.

Requirements:
    pip install PySide6 pyserial numpy matplotlib

Usage:
    python dual_sine_controller.py
"""

import sys
import json
import time
import threading
from collections import deque

import numpy as np
import serial
import serial.tools.list_ports

from PySide6.QtCore import (
    Qt, QTimer, Signal, QObject, QThread, Slot
)
from PySide6.QtGui import (
    QColor, QFont, QPalette, QFontDatabase, QTextCursor
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QDoubleSpinBox, QSpinBox, QPushButton,
    QComboBox, QGroupBox, QStatusBar, QFrame, QSizePolicy,
    QSplitter, QSlider, QCheckBox, QTextEdit, QLineEdit, QTabWidget
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# ── Palette ───────────────────────────────────────────────────────────────────
COLORS = {
    "bg":        "#0d0f14",
    "surface":   "#161921",
    "surface2":  "#1e2330",
    "border":    "#2a3045",
    "accent":    "#00e5ff",
    "accent2":   "#ff6b35",
    "accent3":   "#7c3aed",
    "text":      "#e2e8f0",
    "text_dim":  "#64748b",
    "green":     "#22c55e",
    "red":       "#ef4444",
    "yellow":    "#facc15",
    "sine1":     "#00e5ff",
    "sine2":     "#ff6b35",
    "combined":  "#a78bfa",
}

STYLE = f"""
QMainWindow, QWidget {{
    background-color: {COLORS['bg']};
    color: {COLORS['text']};
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 12px;
}}
QGroupBox {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    margin-top: 20px;
    padding: 12px 8px 8px 8px;
    font-size: 11px;
    font-weight: bold;
    color: {COLORS['text_dim']};
    letter-spacing: 1px;
    text-transform: uppercase;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
}}
QDoubleSpinBox, QSpinBox {{
    background-color: {COLORS['surface2']};
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    color: {COLORS['text']};
    padding: 4px 8px;
    min-width: 90px;
    font-family: 'JetBrains Mono', monospace;
}}
QDoubleSpinBox:focus, QSpinBox:focus {{
    border: 1px solid {COLORS['accent']};
}}
QComboBox {{
    background-color: {COLORS['surface2']};
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    color: {COLORS['text']};
    padding: 4px 8px;
    min-width: 160px;
}}
QComboBox::drop-down {{ border: none; }}
QComboBox QAbstractItemView {{
    background-color: {COLORS['surface2']};
    color: {COLORS['text']};
    selection-background-color: {COLORS['border']};
}}
QPushButton {{
    background-color: {COLORS['surface2']};
    border: 1px solid {COLORS['border']};
    border-radius: 5px;
    color: {COLORS['text']};
    padding: 7px 18px;
    font-weight: bold;
    letter-spacing: 0.5px;
}}
QPushButton:hover {{
    border-color: {COLORS['accent']};
    color: {COLORS['accent']};
}}
QPushButton:disabled {{
    background-color: {COLORS['surface']};
    border-color: {COLORS['border']};
    color: {COLORS['text_dim']};
}}
QPushButton#start_btn {{
    background-color: #163a20;
    border-color: {COLORS['green']};
    color: {COLORS['green']};
}}
QPushButton#start_btn:hover {{ background-color: #1e4d29; }}
QPushButton#start_btn:disabled {{
    background-color: {COLORS['surface']};
    border-color: {COLORS['border']};
    color: {COLORS['text_dim']};
}}
QPushButton#stop_btn {{
    background-color: #3a1616;
    border-color: {COLORS['red']};
    color: {COLORS['red']};
}}
QPushButton#stop_btn:hover {{ background-color: #4d1e1e; }}
QPushButton#stop_btn:disabled {{
    background-color: {COLORS['surface']};
    border-color: {COLORS['border']};
    color: {COLORS['text_dim']};
}}
QPushButton#connect_btn {{
    background-color: #162a3a;
    border-color: {COLORS['accent']};
    color: {COLORS['accent']};
}}
QPushButton#clear_btn {{
    background-color: {COLORS['surface2']};
    border-color: {COLORS['border']};
    padding: 4px 10px;
    font-size: 10px;
}}
QLabel#section_label {{
    color: {COLORS['accent']};
    font-size: 10px;
    letter-spacing: 2px;
    font-weight: bold;
}}
QStatusBar {{
    background-color: {COLORS['surface']};
    border-top: 1px solid {COLORS['border']};
    color: {COLORS['text_dim']};
    font-size: 11px;
}}
QTextEdit {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    color: {COLORS['text']};
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 11px;
    selection-background-color: {COLORS['border']};
}}
QLineEdit {{
    background-color: {COLORS['surface2']};
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    color: {COLORS['text']};
    padding: 4px 8px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
}}
QLineEdit:focus {{ border-color: {COLORS['accent']}; }}
QTabWidget::pane {{
    border: 1px solid {COLORS['border']};
    background-color: {COLORS['surface']};
    border-radius: 4px;
}}
QTabBar::tab {{
    background-color: {COLORS['surface2']};
    border: 1px solid {COLORS['border']};
    padding: 5px 14px;
    color: {COLORS['text_dim']};
    font-size: 10px;
    letter-spacing: 1px;
}}
QTabBar::tab:selected {{
    background-color: {COLORS['surface']};
    color: {COLORS['accent']};
    border-bottom-color: {COLORS['surface']};
}}
QFrame#divider {{
    background-color: {COLORS['border']};
    max-height: 1px;
}}
QCheckBox {{
    color: {COLORS['text_dim']};
    font-size: 11px;
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {COLORS['border']};
    border-radius: 3px;
    background: {COLORS['surface2']};
}}
QCheckBox::indicator:checked {{
    background: {COLORS['accent']};
    border-color: {COLORS['accent']};
}}
"""

# ── Serial worker ─────────────────────────────────────────────────────────────
class SerialWorker(QObject):
    message_received = Signal(str)   # raw line from board
    error_occurred   = Signal(str)
    connected        = Signal(bool)

    def __init__(self):
        super().__init__()
        self._port: serial.Serial | None = None
        self._lock = threading.Lock()

    def open(self, port: str, baud: int = 115200) -> bool:
        try:
            with self._lock:
                if self._port and self._port.is_open:
                    self._port.close()
                self._port = serial.Serial(port, baud, timeout=0.1)
                time.sleep(2)
                self._port.reset_input_buffer()
            self.connected.emit(True)
            return True
        except Exception as e:
            self.error_occurred.emit(str(e))
            self.connected.emit(False)
            return False

    def close(self):
        with self._lock:
            if self._port and self._port.is_open:
                self._port.close()
        self.connected.emit(False)

    def send(self, cmd: str) -> str | None:
        """Send a command and return the first non-empty response line (≤300 ms)."""
        with self._lock:
            if not self._port or not self._port.is_open:
                return None
            try:
                self._port.reset_input_buffer()   # flush stale bytes
                self._port.write((cmd.strip() + "\n").encode())
                deadline = time.time() + 0.3
                while time.time() < deadline:
                    line = self._port.readline().decode(errors="replace").strip()
                    if line:
                        self.message_received.emit(f"← {line}")
                        return line
                return None
            except Exception as e:
                self.error_occurred.emit(str(e))
                return None

    def drain(self) -> list[str]:
        """Non-blocking read of all available lines (used for debug telemetry)."""
        lines = []
        with self._lock:
            if not self._port or not self._port.is_open:
                return lines
            try:
                while self._port.in_waiting:
                    line = self._port.readline().decode(errors="replace").strip()
                    if line:
                        lines.append(line)
            except Exception:
                pass
        return lines

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._port is not None and self._port.is_open


# ── Waveform canvas ───────────────────────────────────────────────────────────
class WaveformCanvas(FigureCanvas):
    def __init__(self):
        self.fig = Figure(figsize=(6, 3), facecolor=COLORS["bg"])
        super().__init__(self.fig)
        self.ax = self.fig.add_subplot(111)
        self._style_axes()
        self.setMinimumHeight(180)

    def _style_axes(self):
        ax = self.ax
        ax.set_facecolor(COLORS["surface"])
        for spine in ax.spines.values():
            spine.set_color(COLORS["border"])
        ax.tick_params(colors=COLORS["text_dim"], labelsize=8)
        ax.xaxis.label.set_color(COLORS["text_dim"])
        ax.yaxis.label.set_color(COLORS["text_dim"])
        ax.set_ylim(-0.1, 3.4)
        ax.set_xlabel("time (ms)", fontsize=8)
        ax.set_ylabel("V", fontsize=8)
        self.fig.tight_layout(pad=1.2)

    def update_plot(self, a1, f1, p1_deg, a2, f2, p2_deg, dc, sr, gain_max):
        self.ax.cla()
        self._style_axes()

        f_min    = min(f1, f2) if min(f1, f2) > 0 else max(f1, f2)

        # Adaptive duration: show enough periods to see the full shape.
        # At low frequencies keep ≥3 periods visible; cap total at 50 ms for high freqs.
        if f_min > 0:
            period = 1.0 / f_min
            if period < 0.005:          # f > 200 Hz  → standard 2-period view, ≤50 ms
                duration = min(2.0 * period, 0.05)
            elif period < 0.05:         # 20–200 Hz   → show 3 periods
                duration = 3.0 * period
            else:                       # < 20 Hz     → show 4 periods, cap at 4 s
                duration = min(4.0 * period, 4.0)
        else:
            duration = 0.05
        t = np.linspace(0, duration, max(int(sr * duration), 2000))

        p1 = np.radians(p1_deg)
        p2 = np.radians(p2_deg)

        denom = np.sin(np.pi * (f2 - f1) * t + np.pi / 2)
        with np.errstate(divide="ignore", invalid="ignore"):
            env = np.where(np.abs(denom) < 1e-9,
                           gain_max,
                           np.clip(np.abs(1.0 / denom), 0, gain_max))

        sines    = a1 * np.sin(2*np.pi*f1*t + p1) + a2 * np.sin(2*np.pi*f2*t + p2)
        combined = np.clip(dc + env * sines, 0, 3.3)
        t_ms     = t * 1000

        self.ax.plot(t_ms, dc + a1*np.sin(2*np.pi*f1*t+p1),
                     color=COLORS["sine1"], lw=0.8, alpha=0.35, label="Sine 1")
        self.ax.plot(t_ms, dc + a2*np.sin(2*np.pi*f2*t+p2),
                     color=COLORS["sine2"], lw=0.8, alpha=0.35, label="Sine 2")

        env_top = np.clip(dc + env*(np.abs(a1)+np.abs(a2)), 0, 3.3)
        env_bot = np.clip(dc - env*(np.abs(a1)+np.abs(a2)), 0, 3.3)
        self.ax.fill_between(t_ms, env_bot, env_top, color=COLORS["combined"], alpha=0.07)
        self.ax.plot(t_ms, env_top, color=COLORS["combined"], lw=0.6, alpha=0.4, ls="--")
        self.ax.plot(t_ms, env_bot, color=COLORS["combined"], lw=0.6, alpha=0.4, ls="--")
        self.ax.plot(t_ms, combined, color=COLORS["combined"], lw=1.6, label="Combined")

        self.ax.axhline(3.3, color=COLORS["red"],    lw=0.5, ls="--", alpha=0.5)
        self.ax.axhline(0,   color=COLORS["border"], lw=0.5, ls="--")
        self.ax.legend(loc="upper right", fontsize=7,
                       facecolor=COLORS["surface"], edgecolor=COLORS["border"],
                       labelcolor=COLORS["text"])
        self.ax.set_xlabel("time (ms)", fontsize=8)
        self.ax.set_ylabel("Voltage (V)", fontsize=8)
        self.ax.set_title(
            f"peak {float(np.max(combined)):.3f} V  |  "
            f"trough {float(np.min(combined)):.3f} V  |  gain cap ×{gain_max:.1f}",
            fontsize=8, color=COLORS["text_dim"])
        self.fig.tight_layout(pad=1.2)
        self.draw()


# ── Debug telemetry canvas (scrolling voltage + envelope) ────────────────────
class TelemetryCanvas(FigureCanvas):
    """
    Sliding-window telemetry chart using matplotlib blitting for low-overhead updates.

    Strategy:
    - Axes chrome (spines, ticks, labels, legends, static hlines) is drawn ONCE
      and cached as a background bitmap via copy_from_bbox().
    - On each new sample only the animated line artists are redrawn via blit(),
      which avoids re-layouting the figure entirely.
    - A pending-data queue fed from the serial thread is drained by a QTimer on
      the GUI thread (no cross-thread canvas calls).
    - The background is invalidated and redrawn whenever the widget is resized.
    """

    WINDOW = 70          # visible sliding-window width (samples)

    def __init__(self):
        self.fig = Figure(figsize=(5, 2.2), facecolor=COLORS["bg"])
        super().__init__(self.fig)
        self.ax_v   = self.fig.add_subplot(211)
        self.ax_env = self.fig.add_subplot(212)

        self._v_buf      = deque(maxlen=self.WINDOW)
        self._env_buf    = deque(maxlen=self.WINDOW)
        self._peak_buf   = deque(maxlen=self.WINDOW)
        self._trough_buf = deque(maxlen=self.WINDOW)

        # Pending data pushed from the drain thread; consumed by _flush_timer
        self._pending: list[tuple] = []
        self._pending_lock = threading.Lock()

        self._bg_v   = None   # cached background bitmaps
        self._bg_env = None
        self._initialized = False

        self.setMinimumHeight(160)
        self._build_static_elements()

        # Flush pending data at ~20 Hz on the GUI thread
        self._flush_timer = QTimer()
        self._flush_timer.timeout.connect(self._flush_pending)
        self._flush_timer.start(50)

    # ── Static chrome (drawn once) ────────────────────────────────────────────
    def _build_static_elements(self):
        """Draw all non-animated chrome and create the animated line objects."""
        for ax in (self.ax_v, self.ax_env):
            ax.set_facecolor(COLORS["surface"])
            for sp in ax.spines.values():
                sp.set_color(COLORS["border"])
            ax.tick_params(colors=COLORS["text_dim"], labelsize=7)
            ax.set_xlim(0, self.WINDOW - 1)

        self.ax_v.set_ylim(-0.05, 3.45)
        self.ax_v.set_ylabel("V", fontsize=7, color=COLORS["text_dim"])
        self.ax_v.axhline(3.3, color=COLORS["red"], lw=0.4, ls=":", alpha=0.5)

        self.ax_env.set_ylabel("gain", fontsize=7, color=COLORS["text_dim"])
        self.ax_env.set_xlabel("samples (last 70)", fontsize=7, color=COLORS["text_dim"])

        self.fig.tight_layout(pad=0.8, h_pad=0.4)

        # Animated lines — created once, data updated in place
        (self._line_v,)      = self.ax_v.plot([], [], color=COLORS["combined"],
                                               lw=1.0, label="V_out", animated=True)
        (self._line_peak,)   = self.ax_v.plot([], [], color=COLORS["red"],
                                               lw=0.6, ls="--", alpha=0.6,
                                               label="peak", animated=True)
        (self._line_trough,) = self.ax_v.plot([], [], color=COLORS["sine1"],
                                               lw=0.6, ls="--", alpha=0.6,
                                               label="trough", animated=True)
        (self._line_env,)    = self.ax_env.plot([], [], color=COLORS["sine2"],
                                                 lw=1.0, label="envelope", animated=True)

        # Static legends (non-animated, drawn as part of background)
        self.ax_v.legend(loc="upper right", fontsize=6,
                         facecolor=COLORS["surface"], edgecolor=COLORS["border"],
                         labelcolor=COLORS["text"])
        self.ax_env.legend(loc="upper right", fontsize=6,
                           facecolor=COLORS["surface"], edgecolor=COLORS["border"],
                           labelcolor=COLORS["text"])

    def _cache_background(self):
        """Full draw then snapshot the static background for blitting."""
        self.draw()
        self._bg_v   = self.copy_from_bbox(self.ax_v.bbox)
        self._bg_env = self.copy_from_bbox(self.ax_env.bbox)
        self._initialized = True

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        # Invalidate cache so it gets rebuilt on next blit cycle
        self._initialized = False

    # ── Data ingestion (called from any thread) ───────────────────────────────
    def push(self, v, env, peak, trough):
        with self._pending_lock:
            self._pending.append((v, env, peak, trough))

    # ── GUI-thread flush ──────────────────────────────────────────────────────
    def _flush_pending(self):
        with self._pending_lock:
            if not self._pending:
                return
            batch = self._pending
            self._pending = []

        for v, env, peak, trough in batch:
            self._v_buf.append(v)
            self._env_buf.append(env)
            self._peak_buf.append(peak)
            self._trough_buf.append(trough)

        self._blit_update()

    def _blit_update(self):
        if not self._initialized:
            self._cache_background()

        x = list(range(len(self._v_buf)))

        self._line_v.set_data(x, list(self._v_buf))
        self._line_peak.set_data(x, list(self._peak_buf))
        self._line_trough.set_data(x, list(self._trough_buf))
        self._line_env.set_data(x, list(self._env_buf))

        # Auto-scale env y-axis without full redraw
        if self._env_buf:
            env_max = max(self._env_buf)
            self.ax_env.set_ylim(0, max(env_max * 1.15, 0.1))

        # Restore static background, draw only the animated lines, blit
        self.restore_region(self._bg_v)
        self.ax_v.draw_artist(self._line_v)
        self.ax_v.draw_artist(self._line_peak)
        self.ax_v.draw_artist(self._line_trough)
        self.blit(self.ax_v.bbox)

        self.restore_region(self._bg_env)
        self.ax_env.draw_artist(self._line_env)
        self.blit(self.ax_env.bbox)

    # ── Clear ─────────────────────────────────────────────────────────────────
    def clear(self):
        with self._pending_lock:
            self._pending = []
        self._v_buf.clear()
        self._env_buf.clear()
        self._peak_buf.clear()
        self._trough_buf.clear()
        self._initialized = False
        self._cache_background()


# ── Helpers ───────────────────────────────────────────────────────────────────
def make_spinbox(min_val, max_val, decimals, step, value, suffix="") -> QDoubleSpinBox:
    sb = QDoubleSpinBox()
    sb.setRange(min_val, max_val)
    sb.setDecimals(decimals)
    sb.setSingleStep(step)
    sb.setValue(value)
    if suffix:
        sb.setSuffix(f"  {suffix}")
    return sb


# ── Main window ───────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    # Signal so serial thread can safely append text to the console
    _console_append = Signal(str, str)   # (text, css_color)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dual-Sine DAC Controller  //  Arduino Due  v3.0")
        self.resize(1100, 760)
        self.serial = SerialWorker()
        self.serial.error_occurred.connect(self._on_serial_error)
        self.serial.connected.connect(self._on_connected)
        self.serial.message_received.connect(self._log_rx)
        self._console_append.connect(self._append_console)
        self._running = False
        self._build_ui()

        # Preview refresh timer (4 fps — purely local math)
        self._preview_timer = QTimer(self)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self._preview_timer.start(250)

        # Telemetry drain timer — poll serial for unsolicited debug JSON
        self._drain_timer = QTimer(self)
        self._drain_timer.timeout.connect(self._drain_serial)
        self._drain_timer.start(50)   # 20 Hz poll

        # Clip counters for stats panel
        self._total_clip_hi = 0
        self._total_clip_lo = 0

    # ── UI construction ───────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # Left panel
        left = QVBoxLayout()
        left.setSpacing(10)
        left.addWidget(self._build_connection_box())
        left.addWidget(self._build_sine_box("SINE  1", "1", COLORS["sine1"]))
        left.addWidget(self._build_sine_box("SINE  2", "2", COLORS["sine2"]))
        left.addWidget(self._build_global_box())
        left.addWidget(self._build_transport_box())
        left.addStretch()

        left_w = QWidget(); left_w.setLayout(left); left_w.setFixedWidth(360)

        # Right panel: tabbed (Preview / Debug)
        right = QVBoxLayout()
        right.setSpacing(8)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_preview_tab(), "PREVIEW")
        self.tabs.addTab(self._build_debug_tab(),   "DEBUG  CONSOLE")

        right.addWidget(self.tabs, 1)
        self._build_stats_panel(right)

        right_w = QWidget(); right_w.setLayout(right)

        root.addWidget(left_w)
        root.addWidget(right_w, 1)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Disconnected")

    def _build_preview_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 4, 4, 4)
        lbl = QLabel("WAVEFORM  PREVIEW")
        lbl.setObjectName("section_label")
        v.addWidget(lbl)
        self.canvas = WaveformCanvas()
        v.addWidget(self.canvas, 1)
        return w

    def _build_debug_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(6)

        # ── Telemetry chart ───────────────────────────────────────────────────
        telem_label = QLabel("LIVE  TELEMETRY  (from board, ~10 Hz)")
        telem_label.setObjectName("section_label")
        v.addWidget(telem_label)

        self.telem_canvas = TelemetryCanvas()
        v.addWidget(self.telem_canvas)

        # ── Debug stats bar ───────────────────────────────────────────────────
        stats_frame = QFrame()
        stats_frame.setStyleSheet(
            f"QFrame {{ background:{COLORS['surface']}; border:1px solid {COLORS['border']};"
            f"border-radius:4px; }}")
        sg = QGridLayout(stats_frame)
        sg.setContentsMargins(10, 6, 10, 6)
        sg.setHorizontalSpacing(20)

        def dstat(label, attr, col):
            lb = QLabel(label)
            lb.setStyleSheet(f"color:{COLORS['text_dim']};font-size:10px;letter-spacing:1px;")
            vl = QLabel("—")
            vl.setStyleSheet(f"color:{COLORS['text']};font-family:'JetBrains Mono';font-size:11px;")
            setattr(self, attr, vl)
            sg.addWidget(lb, 0, col)
            sg.addWidget(vl, 1, col)

        dstat("ISR µs",   "dstat_isr",     0)
        dstat("CLIP ↑",   "dstat_cliphi",  1)
        dstat("CLIP ↓",   "dstat_cliplo",  2)
        dstat("SAMPLES",  "dstat_samps",   3)
        dstat("ENV GAIN", "dstat_env",     4)
        v.addWidget(stats_frame)

        # ── Raw serial log ────────────────────────────────────────────────────
        log_header = QHBoxLayout()
        log_lbl = QLabel("SERIAL  LOG")
        log_lbl.setObjectName("section_label")
        log_header.addWidget(log_lbl)
        log_header.addStretch()

        self.dbg_checkbox = QCheckBox("Board telemetry (DBG ON)")
        self.dbg_checkbox.setChecked(False)
        self.dbg_checkbox.toggled.connect(self._toggle_dbg)
        log_header.addWidget(self.dbg_checkbox)

        self.autoscroll_cb = QCheckBox("Auto-scroll")
        self.autoscroll_cb.setChecked(True)
        log_header.addWidget(self.autoscroll_cb)

        clear_btn = QPushButton("CLEAR")
        clear_btn.setObjectName("clear_btn")
        clear_btn.clicked.connect(self._clear_console)
        log_header.addWidget(clear_btn)
        v.addLayout(log_header)

        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setMinimumHeight(120)
        v.addWidget(self.console, 1)

        # Manual command input
        cmd_row = QHBoxLayout()
        self.cmd_input = QLineEdit()
        self.cmd_input.setPlaceholderText("Send raw command, e.g.  STATUS  or  DBG ON")
        self.cmd_input.returnPressed.connect(self._send_manual_cmd)
        cmd_row.addWidget(self.cmd_input, 1)
        send_btn = QPushButton("SEND")
        send_btn.setFixedWidth(64)
        send_btn.clicked.connect(self._send_manual_cmd)
        cmd_row.addWidget(send_btn)
        v.addLayout(cmd_row)

        return w

    def _build_connection_box(self) -> QGroupBox:
        box = QGroupBox("CONNECTION")
        lay = QHBoxLayout(box)
        lay.setSpacing(6)

        self.port_combo = QComboBox()
        self._refresh_ports()
        lay.addWidget(self.port_combo)

        refresh_btn = QPushButton("⟳")
        refresh_btn.setFixedWidth(32)
        refresh_btn.clicked.connect(self._refresh_ports)
        lay.addWidget(refresh_btn)

        self.connect_btn = QPushButton("CONNECT")
        self.connect_btn.setObjectName("connect_btn")
        self.connect_btn.clicked.connect(self._toggle_connect)
        lay.addWidget(self.connect_btn)
        return box

    def _build_sine_box(self, title: str, idx: str, color: str) -> QGroupBox:
        box = QGroupBox(title)
        box.setStyleSheet(f"QGroupBox {{ border-color: {color}44; }}")
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)

        def row(label, widget):
            r = grid.rowCount()
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color:{COLORS['text_dim']};font-size:11px;")
            grid.addWidget(lbl, r, 0)
            grid.addWidget(widget, r, 1)

        if idx == "1":
            self.amp1   = make_spinbox(0, 1.65,  3, 0.05,  0.5,   "V")
            self.freq1  = make_spinbox(0, 5000,  2, 10.0,  100.0, "Hz")
            self.phase1 = make_spinbox(-360, 360, 1, 5.0,  0.0,   "°")
            for c in (self.amp1, self.freq1, self.phase1):
                c.valueChanged.connect(self._param_changed)
            row("Amplitude", self.amp1)
            row("Frequency", self.freq1)
            row("Phase",     self.phase1)
        else:
            self.amp2   = make_spinbox(0, 1.65,  3, 0.05,  0.5,   "V")
            self.freq2  = make_spinbox(0, 5000,  2, 10.0,  200.0, "Hz")
            self.phase2 = make_spinbox(-360, 360, 1, 5.0,  0.0,   "°")
            for c in (self.amp2, self.freq2, self.phase2):
                c.valueChanged.connect(self._param_changed)
            row("Amplitude", self.amp2)
            row("Frequency", self.freq2)
            row("Phase",     self.phase2)
        return box

    def _build_global_box(self) -> QGroupBox:
        box = QGroupBox("GLOBAL")
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)

        def row(label, widget):
            r = grid.rowCount()
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color:{COLORS['text_dim']};font-size:11px;")
            grid.addWidget(lbl, r, 0)
            grid.addWidget(widget, r, 1)

        self.dc_offset   = make_spinbox(0, 3.3,   3, 0.05, 1.65,  "V")
        self.sample_rate = QSpinBox()
        self.sample_rate.setRange(100, 100000)
        self.sample_rate.setValue(10000)
        self.sample_rate.setSuffix("  Hz")
        self.sample_rate.setSingleStep(1000)
        self.gain_max    = make_spinbox(1.0, 20.0, 1, 0.5,  4.0,  "×")

        for c in (self.dc_offset, self.sample_rate, self.gain_max):
            c.valueChanged.connect(self._param_changed)

        row("DC Offset",   self.dc_offset)
        row("Sample Rate", self.sample_rate)
        row("Max Env Gain", self.gain_max)

        self.clip_label = QLabel("")
        self.clip_label.setStyleSheet(f"color:{COLORS['red']};font-size:10px;")
        grid.addWidget(self.clip_label, grid.rowCount(), 0, 1, 3)
        return box

    def _build_transport_box(self) -> QGroupBox:
        box = QGroupBox("TRANSPORT")
        lay = QHBoxLayout(box)
        lay.setSpacing(8)

        self.apply_btn = QPushButton("APPLY")
        self.apply_btn.clicked.connect(self._apply_all)
        self.apply_btn.setEnabled(False)

        self.start_btn = QPushButton("▶  START")
        self.start_btn.setObjectName("start_btn")
        self.start_btn.clicked.connect(self._start)
        self.start_btn.setEnabled(False)

        self.stop_btn = QPushButton("■  STOP")
        self.stop_btn.setObjectName("stop_btn")
        self.stop_btn.clicked.connect(self._stop)
        self.stop_btn.setEnabled(False)

        lay.addWidget(self.apply_btn)
        lay.addWidget(self.start_btn)
        lay.addWidget(self.stop_btn)
        return box

    def _build_stats_panel(self, layout: QVBoxLayout):
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background:{COLORS['surface']}; border:1px solid {COLORS['border']};"
            f"border-radius:6px; }}")
        grid = QGridLayout(frame)
        grid.setContentsMargins(12, 8, 12, 8)
        grid.setHorizontalSpacing(24)

        def stat(label, attr, col):
            lb = QLabel(label)
            lb.setStyleSheet(f"color:{COLORS['text_dim']};font-size:10px;letter-spacing:1px;")
            vl = QLabel("—")
            vl.setStyleSheet(f"color:{COLORS['text']};font-family:'JetBrains Mono';font-size:12px;")
            setattr(self, attr, vl)
            grid.addWidget(lb, 0, col)
            grid.addWidget(vl, 1, col)

        stat("PEAK",    "stat_peak",    0)
        stat("TROUGH",  "stat_trough",  1)
        stat("VRANGE",  "stat_range",   2)
        stat("NYQUIST", "stat_nyquist", 3)
        layout.addWidget(frame)

    # ── Port helpers ──────────────────────────────────────────────────────────
    def _refresh_ports(self):
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for p in ports:
            self.port_combo.addItem(p.device)
        if not ports:
            self.port_combo.addItem("(no ports found)")

    def _get_params(self) -> dict:
        return {
            "a1": self.amp1.value(),   "f1": self.freq1.value(),
            "p1": self.phase1.value(), "a2": self.amp2.value(),
            "f2": self.freq2.value(),  "p2": self.phase2.value(),
            "dc": self.dc_offset.value(),
            "sr": self.sample_rate.value(),
            "gain_max": self.gain_max.value(),
        }

    def _check_clipping(self, p: dict) -> str:
        g = p["gain_max"]
        hi = p["dc"] + g * (p["a1"] + p["a2"])
        lo = p["dc"] - g * (p["a1"] + p["a2"])
        w = []
        if hi > 3.3: w.append(f"⚠ peak up to +{hi:.3f} V (clamped)")
        if lo < 0.0: w.append(f"⚠ trough down to {lo:.3f} V (clamped)")
        return "  ".join(w)

    # ── Preview refresh ───────────────────────────────────────────────────────
    def _refresh_preview(self):
        p = self._get_params()
        self.clip_label.setText(self._check_clipping(p))
        self.canvas.update_plot(
            a1=p["a1"], f1=p["f1"], p1_deg=p["p1"],
            a2=p["a2"], f2=p["f2"], p2_deg=p["p2"],
            dc=p["dc"], sr=p["sr"], gain_max=p["gain_max"])

        t = np.linspace(0, 0.1, 50000)
        denom = np.sin(np.pi * (p["f2"] - p["f1"]) * t + np.pi / 2)
        with np.errstate(divide="ignore", invalid="ignore"):
            env = np.where(np.abs(denom) < 1e-9, p["gain_max"],
                           np.clip(np.abs(1.0 / denom), 0, p["gain_max"]))
        s = np.clip(p["dc"] + env * (
            p["a1"] * np.sin(2*np.pi*p["f1"]*t + np.radians(p["p1"])) +
            p["a2"] * np.sin(2*np.pi*p["f2"]*t + np.radians(p["p2"]))), 0, 3.3)

        self.stat_peak.setText(f"{np.max(s):.3f} V")
        self.stat_trough.setText(f"{np.min(s):.3f} V")
        self.stat_range.setText(f"{np.max(s)-np.min(s):.3f} V")
        self.stat_nyquist.setText(f"{p['sr']/2:.0f} Hz")

    # ── Serial telemetry drain (20 Hz) ────────────────────────────────────────
    def _drain_serial(self):
        for raw in self.serial.drain():
            self._process_incoming(raw)

    def _process_incoming(self, raw: str):
        """Route an unsolicited line to the console and/or telemetry chart."""
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            self._log(raw, COLORS["text_dim"])
            return

        if d.get("dbg"):
            # Update live telemetry chart
            self.telem_canvas.push(
                v      = float(d.get("v",      0)),
                env    = float(d.get("env",    0)),
                peak   = float(d.get("peak",   0)),
                trough = float(d.get("trough", 0)),
            )
            # Update debug stat labels
            self._total_clip_hi += int(d.get("clipHi", 0))
            self._total_clip_lo += int(d.get("clipLo", 0))
            self.dstat_isr.setText(f"{d.get('isrUs', '?')} µs")
            self.dstat_cliphi.setText(str(self._total_clip_hi))
            self.dstat_cliplo.setText(str(self._total_clip_lo))
            self.dstat_samps.setText(str(d.get("samps", "?")))
            self.dstat_env.setText(f"{float(d.get('env', 0)):.3f}")

            # Highlight clips in red if nonzero this window
            clip_color = COLORS["red"] if (d.get("clipHi", 0) or d.get("clipLo", 0)) \
                         else COLORS["text_dim"]
            for lbl in (self.dstat_cliphi, self.dstat_cliplo):
                lbl.setStyleSheet(f"color:{clip_color};font-family:'JetBrains Mono';font-size:11px;")

            # Log to console with compact format
            self._log(
                f"[DBG] V={d['v']:.3f}V  env={d['env']:.3f}  "
                f"peak={d['peak']:.3f}  trough={d['trough']:.3f}  "
                f"clip↑={d['clipHi']}  clip↓={d['clipLo']}  "
                f"ISR={d['isrUs']}µs  n={d['samps']}",
                COLORS["text_dim"])

        elif d.get("status"):
            self._log(f"[STATUS] {json.dumps(d)}", COLORS["accent"])
        else:
            self._log(f"[JSON] {raw}", COLORS["text_dim"])

    # ── Console helpers ───────────────────────────────────────────────────────
    def _log(self, text: str, color: str = COLORS["text"]):
        ts = time.strftime("%H:%M:%S")
        self._console_append.emit(f"[{ts}] {text}", color)

    def _log_rx(self, text: str):
        # Fired by SerialWorker.message_received (responses to commands we sent)
        self._log(text, COLORS["green"])

    @Slot(str, str)
    def _append_console(self, text: str, color: str):
        cursor = self.console.textCursor()

        # Sliding window: trim oldest lines when over 70
        doc = self.console.document()
        if doc.blockCount() >= 70:
            trim_cursor = QTextCursor(doc.begin())
            trim_cursor.select(QTextCursor.BlockUnderCursor)
            trim_cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
            trim_cursor.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor)
            trim_cursor.removeSelectedText()

        cursor.movePosition(QTextCursor.End)
        fmt = cursor.charFormat()
        fmt.setForeground(QColor(color))
        cursor.setCharFormat(fmt)
        cursor.insertText(text + "\n")
        if self.autoscroll_cb.isChecked():
            self.console.setTextCursor(cursor)
            self.console.ensureCursorVisible()

    def _clear_console(self):
        self.console.clear()
        self.telem_canvas.clear()
        self._total_clip_hi = 0
        self._total_clip_lo = 0
        for attr in ("dstat_isr", "dstat_cliphi", "dstat_cliplo",
                     "dstat_samps", "dstat_env"):
            getattr(self, attr).setText("—")

    def _send_manual_cmd(self):
        cmd = self.cmd_input.text().strip()
        if not cmd:
            return
        self._log(f"→ {cmd}", COLORS["accent2"])
        resp = self._send(cmd)
        if resp is None:
            self._log("(no response / not connected)", COLORS["red"])
        self.cmd_input.clear()

    def _toggle_dbg(self, enabled: bool):
        cmd = "DBG ON" if enabled else "DBG OFF"
        self._log(f"→ {cmd}", COLORS["accent2"])
        resp = self._send(cmd)
        if resp and "OK" in resp:
            if not enabled:
                self.telem_canvas.clear()

    # ── Serial actions ────────────────────────────────────────────────────────
    def _toggle_connect(self):
        if self.serial.is_open:
            self._stop()
            self.serial.close()
            self._log("Disconnected.", COLORS["text_dim"])
        else:
            port = self.port_combo.currentText()
            if port and "no ports" not in port:
                self.status_bar.showMessage(f"Connecting to {port} …")
                self._log(f"Connecting to {port} @ 115200 …", COLORS["accent"])
                ok = self.serial.open(port)
                if ok:
                    self.status_bar.showMessage(f"Connected  ·  {port}  @  115200 baud")
                    self._log(f"Connected to {port}.", COLORS["green"])

    def _param_changed(self):
        pass   # preview updates via timer; board updated only on APPLY

    def _send(self, cmd: str) -> str | None:
        resp = self.serial.send(cmd)
        if resp:
            self.status_bar.showMessage(f"← {resp}")
        return resp

    def _apply_all(self):
        if not self.serial.is_open:
            return
        p = self._get_params()
        cmds = [
            f"SET A1 {p['a1']:.4f}", f"SET F1 {p['f1']:.4f}",
            f"SET P1 {p['p1']:.2f}", f"SET A2 {p['a2']:.4f}",
            f"SET F2 {p['f2']:.4f}", f"SET P2 {p['p2']:.2f}",
            f"SET DC {p['dc']:.4f}", f"SET GM {p['gain_max']:.2f}",
            f"SET SR {int(p['sr'])}",
        ]
        self._log("Applying parameters…", COLORS["accent"])
        for cmd in cmds:
            self._log(f"  → {cmd}", COLORS["accent2"])
            self._send(cmd)
        self.status_bar.showMessage("Parameters applied.")
        self._log("Parameters applied.", COLORS["green"])

    def _start(self):
        self._apply_all()
        time.sleep(0.05)   # let Due finish ACKing all SET commands
        self._log("→ START", COLORS["green"])
        resp = self._send("START")
        if resp and "OK" in resp:
            self._running = True
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.status_bar.showMessage("▶ Running")
            self._log("▶ Running", COLORS["green"])
            # Auto-enable debug telemetry if checkbox is on
            if self.dbg_checkbox.isChecked():
                self._send("DBG ON")

    def _stop(self):
        self._log("→ STOP", COLORS["red"])
        resp = self._send("STOP")
        self._running = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_bar.showMessage("■ Stopped")
        self._log("■ Stopped", COLORS["red"])
        if self.dbg_checkbox.isChecked():
            self._send("DBG OFF")

    # ── Connected slot ────────────────────────────────────────────────────────
    @Slot(bool)
    def _on_connected(self, connected: bool):
        if connected:
            self.connect_btn.setText("DISCONNECT")
            self.apply_btn.setEnabled(True)
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
        else:
            self.connect_btn.setText("CONNECT")
            self.apply_btn.setEnabled(False)
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self._running = False

    @Slot(str)
    def _on_serial_error(self, msg: str):
        self.status_bar.showMessage(f"Serial error: {msg}")
        self._log(f"Serial error: {msg}", COLORS["red"])

    def closeEvent(self, event):
        if self.serial.is_open:
            self._send("DBG OFF")
        self._stop()
        self.serial.close()
        super().closeEvent(event)


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.Window,          QColor(COLORS["bg"]))
    palette.setColor(QPalette.WindowText,      QColor(COLORS["text"]))
    palette.setColor(QPalette.Base,            QColor(COLORS["surface"]))
    palette.setColor(QPalette.AlternateBase,   QColor(COLORS["surface2"]))
    palette.setColor(QPalette.Text,            QColor(COLORS["text"]))
    palette.setColor(QPalette.Button,          QColor(COLORS["surface2"]))
    palette.setColor(QPalette.ButtonText,      QColor(COLORS["text"]))
    palette.setColor(QPalette.Highlight,       QColor(COLORS["accent"]))
    palette.setColor(QPalette.HighlightedText, QColor(COLORS["bg"]))
    app.setPalette(palette)
    app.setStyleSheet(STYLE)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
