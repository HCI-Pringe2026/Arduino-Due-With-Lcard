"""
dual_sine_controller.py
PySide6 desktop app for controlling the Arduino Due dual-sine DAC firmware.

Requirements:
    pip install PySide6 pyserial numpy matplotlib pylsl pandas openpyxl scipy

Usage:
    python dual_sine_controller.py
"""

import sys
import json
import re
import time
import threading
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np
import serial
import serial.tools.list_ports

try:
    import pylsl
    from pylsl import StreamInlet, local_clock, resolve_streams

    LSL_IMPORT_ERROR = None
except Exception as e:  # pragma: no cover - depends on local installation
    pylsl = None
    StreamInlet = None
    local_clock = None
    resolve_streams = None
    LSL_IMPORT_ERROR = e

try:
    import pandas as pd

    PANDAS_IMPORT_ERROR = None
except Exception as e:  # pragma: no cover - depends on local installation
    pd = None
    PANDAS_IMPORT_ERROR = e

try:
    import openpyxl as _openpyxl  # noqa: F401

    OPENPYXL_IMPORT_ERROR = None
except Exception as e:  # pragma: no cover - depends on local installation
    OPENPYXL_IMPORT_ERROR = e

try:
    from scipy.signal import butter, filtfilt, iirnotch, lfilter, sosfilt, sosfiltfilt

    SCIPY_IMPORT_ERROR = None
except Exception as e:  # pragma: no cover - depends on local installation
    butter = filtfilt = iirnotch = lfilter = sosfilt = sosfiltfilt = None
    SCIPY_IMPORT_ERROR = e

from PySide6.QtCore import QTimer, Signal, QObject, Slot
from PySide6.QtGui import QColor, QPalette, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QDoubleSpinBox,
    QSpinBox,
    QPushButton,
    QComboBox,
    QGroupBox,
    QStatusBar,
    QFrame,
    QCheckBox,
    QTextEdit,
    QLineEdit,
    QTabWidget,
    QFileDialog,
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# ── Palette ───────────────────────────────────────────────────────────────────
COLORS = {
    "bg": "#0d0f14",
    "surface": "#161921",
    "surface2": "#1e2330",
    "border": "#2a3045",
    "accent": "#00e5ff",
    "accent2": "#ff6b35",
    "accent3": "#7c3aed",
    "text": "#e2e8f0",
    "text_dim": "#64748b",
    "green": "#22c55e",
    "red": "#ef4444",
    "yellow": "#facc15",
    "sine1": "#00e5ff",
    "sine2": "#ff6b35",
    "combined": "#a78bfa",
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
QPushButton:pressed {{
    background-color: {COLORS['surface']};
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
QPushButton#start_btn:pressed {{ background-color: #0f2415; }}
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
QPushButton#stop_btn:pressed {{ background-color: #240f0f; }}
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
QPushButton#connect_btn:hover {{ background-color: #1e3a4d; }}
QPushButton#connect_btn:pressed {{ background-color: #0f1f2e; border-color: {COLORS['accent']}; }}
QPushButton#clear_btn {{
    background-color: {COLORS['surface2']};
    border-color: {COLORS['border']};
    padding: 4px 10px;
    font-size: 10px;
}}
QPushButton#clear_btn:hover {{
    background-color: {COLORS['border']};
    border-color: {COLORS['text_dim']};
    color: {COLORS['text']};
}}
QPushButton#clear_btn:pressed {{ background-color: {COLORS['surface']}; }}
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
    message_received = Signal(str)  # raw line from board
    error_occurred = Signal(str)
    connected = Signal(bool)

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
                self._port.reset_input_buffer()  # flush stale bytes
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

        f_min = min(f1, f2) if min(f1, f2) > 0 else max(f1, f2)

        # Adaptive duration: show enough periods to see the full shape.
        # At low frequencies keep ≥3 periods visible; cap total at 50 ms for high freqs.
        if f_min > 0:
            period = 1.0 / f_min
            if period < 0.005:  # f > 200 Hz  → standard 2-period view, ≤50 ms
                duration = min(2.0 * period, 0.05)
            elif period < 0.05:  # 20–200 Hz   → show 3 periods
                duration = 3.0 * period
            else:  # < 20 Hz     → show 4 periods, cap at 4 s
                duration = min(4.0 * period, 4.0)
        else:
            duration = 0.05
        t = np.linspace(0, duration, max(int(sr * duration), 2000))

        p1 = np.radians(p1_deg)
        p2 = np.radians(p2_deg)

        denom = np.sin(np.pi * (f2 - f1) * t + np.pi / 2)
        with np.errstate(divide="ignore", invalid="ignore"):
            env = np.where(
                np.abs(denom) < 1e-9,
                gain_max,
                np.clip(np.abs(1.0 / denom), 0, gain_max),
            )

        sines = a1 * np.sin(2 * np.pi * f1 * t + p1) + a2 * np.sin(
            2 * np.pi * f2 * t + p2
        )
        combined = np.clip(dc + env * sines, 0, 3.3)
        t_ms = t * 1000

        self.ax.plot(
            t_ms,
            dc + a1 * np.sin(2 * np.pi * f1 * t + p1),
            color=COLORS["sine1"],
            lw=0.8,
            alpha=0.35,
            label="Sine 1",
        )
        self.ax.plot(
            t_ms,
            dc + a2 * np.sin(2 * np.pi * f2 * t + p2),
            color=COLORS["sine2"],
            lw=0.8,
            alpha=0.35,
            label="Sine 2",
        )

        env_top = np.clip(dc + env * (np.abs(a1) + np.abs(a2)), 0, 3.3)
        env_bot = np.clip(dc - env * (np.abs(a1) + np.abs(a2)), 0, 3.3)
        self.ax.fill_between(
            t_ms, env_bot, env_top, color=COLORS["combined"], alpha=0.07
        )
        self.ax.plot(
            t_ms, env_top, color=COLORS["combined"], lw=0.6, alpha=0.4, ls="--"
        )
        self.ax.plot(
            t_ms, env_bot, color=COLORS["combined"], lw=0.6, alpha=0.4, ls="--"
        )
        self.ax.plot(t_ms, combined, color=COLORS["combined"], lw=1.6, label="Combined")

        self.ax.axhline(3.3, color=COLORS["red"], lw=0.5, ls="--", alpha=0.5)
        self.ax.axhline(0, color=COLORS["border"], lw=0.5, ls="--")
        self.ax.legend(
            loc="upper right",
            fontsize=7,
            facecolor=COLORS["surface"],
            edgecolor=COLORS["border"],
            labelcolor=COLORS["text"],
        )
        self.ax.set_xlabel("time (ms)", fontsize=8)
        self.ax.set_ylabel("Voltage (V)", fontsize=8)
        self.ax.set_title(
            f"peak {float(np.max(combined)):.3f} V  |  "
            f"trough {float(np.min(combined)):.3f} V  |  gain cap ×{gain_max:.1f}",
            fontsize=8,
            color=COLORS["text_dim"],
        )
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

    WINDOW = 70  # visible sliding-window width (samples)

    def __init__(self):
        self.fig = Figure(figsize=(5, 2.2), facecolor=COLORS["bg"])
        super().__init__(self.fig)
        self.ax_v = self.fig.add_subplot(211)
        self.ax_env = self.fig.add_subplot(212)

        self._v_buf = deque(maxlen=self.WINDOW)
        self._env_buf = deque(maxlen=self.WINDOW)
        self._peak_buf = deque(maxlen=self.WINDOW)
        self._trough_buf = deque(maxlen=self.WINDOW)

        # Pending data pushed from the drain thread; consumed by _flush_timer
        self._pending: list[tuple] = []
        self._pending_lock = threading.Lock()

        self._bg_v = None  # cached background bitmaps
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
        self.ax_env.set_xlabel(
            "samples (last 70)", fontsize=7, color=COLORS["text_dim"]
        )

        self.fig.tight_layout(pad=0.8, h_pad=0.4)

        # Animated lines — created once, data updated in place
        (self._line_v,) = self.ax_v.plot(
            [], [], color=COLORS["combined"], lw=1.0, label="V_out", animated=True
        )
        (self._line_peak,) = self.ax_v.plot(
            [],
            [],
            color=COLORS["red"],
            lw=0.6,
            ls="--",
            alpha=0.6,
            label="peak",
            animated=True,
        )
        (self._line_trough,) = self.ax_v.plot(
            [],
            [],
            color=COLORS["sine1"],
            lw=0.6,
            ls="--",
            alpha=0.6,
            label="trough",
            animated=True,
        )
        (self._line_env,) = self.ax_env.plot(
            [], [], color=COLORS["sine2"], lw=1.0, label="envelope", animated=True
        )

        # Static legends (non-animated, drawn as part of background)
        self.ax_v.legend(
            loc="upper right",
            fontsize=6,
            facecolor=COLORS["surface"],
            edgecolor=COLORS["border"],
            labelcolor=COLORS["text"],
        )
        self.ax_env.legend(
            loc="upper right",
            fontsize=6,
            facecolor=COLORS["surface"],
            edgecolor=COLORS["border"],
            labelcolor=COLORS["text"],
        )

    def _cache_background(self):
        """Full draw then snapshot the static background for blitting."""
        self.draw()
        self._bg_v = self.copy_from_bbox(self.ax_v.bbox)
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


def safe_column_name(name: str, fallback: str) -> str:
    clean = re.sub(r"[^0-9A-Za-z_]+", "_", str(name).strip()).strip("_")
    return clean or fallback


def unique_column_names(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    unique = []
    for name in names:
        count = seen.get(name, 0)
        seen[name] = count + 1
        unique.append(name if count == 0 else f"{name}_{count + 1}")
    return unique


class LSLRecordingWorker(threading.Thread):
    def __init__(self, inlet, sample_lock, samples, stim_getter, error_signal):
        super().__init__(daemon=True)
        self.inlet = inlet
        self.sample_lock = sample_lock
        self.samples = samples
        self.stim_getter = stim_getter
        self.error_signal = error_signal
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        while not self._stop_event.is_set():
            try:
                chunk, timestamps = self.inlet.pull_chunk(timeout=0.05, max_samples=256)
            except Exception as e:
                self.error_signal.emit(str(e))
                break

            if not chunk:
                continue

            if len(timestamps) != len(chunk):
                timestamps = [np.nan] * len(chunk)

            rows = []
            for sample, lsl_ts in zip(chunk, timestamps):
                stim = self.stim_getter()
                rows.append(
                    {
                        "lsl_timestamp": float(lsl_ts) if lsl_ts else np.nan,
                        "app_timestamp": time.time(),
                        "sample": [float(v) for v in sample],
                        "stim_step_index": stim["step_index"],
                        "stim_f1_hz": stim["f1_hz"],
                        "stim_f2_hz": stim["f2_hz"],
                    }
                )

            with self.sample_lock:
                self.samples.extend(rows)


# ── Main window ───────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    # Signal so serial thread can safely append text to the console
    _console_append = Signal(str, str)  # (text, css_color)
    _lsl_worker_error = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dual-Sine DAC Controller  //  Arduino Due  v3.0")
        self.resize(1100, 760)
        self.serial = SerialWorker()
        self.serial.error_occurred.connect(self._on_serial_error)
        self.serial.connected.connect(self._on_connected)
        self.serial.message_received.connect(self._log_rx)
        self._console_append.connect(self._append_console)
        self._lsl_worker_error.connect(self._on_lsl_worker_error)
        self._running = False
        self.sequence_steps: list[tuple[float, float, float]] = []
        self.sequence_file_path: str | None = None
        self._sequence_index = 0
        self._sequence_timer = QTimer(self)
        self._sequence_timer.setSingleShot(True)
        self._sequence_timer.timeout.connect(self._run_next_sequence_step)

        self.lsl_streams = []
        self.lsl_inlet = None
        self.lsl_stream_meta: dict = {}
        self.lsl_channel_names: list[str] = []
        self.lsl_worker: LSLRecordingWorker | None = None
        self.lsl_samples: list[dict] = []
        self.lsl_sample_lock = threading.Lock()
        self._stim_lock = threading.Lock()
        self._stim_events: list[dict] = []
        self._current_stim = {
            "step_index": -1,
            "f1_hz": np.nan,
            "f2_hz": np.nan,
        }
        self._recording_active = False
        self._record_start_app_time: float | None = None
        self._record_end_app_time: float | None = None
        self._build_ui()

        # Preview refresh timer (4 fps — purely local math)
        self._preview_timer = QTimer(self)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self._preview_timer.start(250)

        # Telemetry drain timer — poll serial for unsolicited debug JSON
        self._drain_timer = QTimer(self)
        self._drain_timer.timeout.connect(self._drain_serial)
        self._drain_timer.start(50)  # 20 Hz poll

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
        left.addWidget(self._build_sequence_box())
        left.addWidget(self._build_global_box())
        left.addWidget(self._build_transport_box())
        left.addStretch()

        left_w = QWidget()
        left_w.setLayout(left)
        left_w.setFixedWidth(360)

        # Right panel: tabbed (Preview / Debug)
        right = QVBoxLayout()
        right.setSpacing(8)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_preview_tab(), "PREVIEW")
        self.tabs.addTab(self._build_debug_tab(), "DEBUG  CONSOLE")
        self.tabs.addTab(self._build_lsl_tab(), "LSL  RECORDING")

        right.addWidget(self.tabs, 1)
        self._build_stats_panel(right)

        right_w = QWidget()
        right_w.setLayout(right)

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
            f"border-radius:4px; }}"
        )
        sg = QGridLayout(stats_frame)
        sg.setContentsMargins(10, 6, 10, 6)
        sg.setHorizontalSpacing(20)

        def dstat(label, attr, col):
            lb = QLabel(label)
            lb.setStyleSheet(
                f"color:{COLORS['text_dim']};font-size:10px;letter-spacing:1px;"
            )
            vl = QLabel("—")
            vl.setStyleSheet(
                f"color:{COLORS['text']};font-family:'JetBrains Mono';font-size:11px;"
            )
            setattr(self, attr, vl)
            sg.addWidget(lb, 0, col)
            sg.addWidget(vl, 1, col)

        dstat("ISR µs", "dstat_isr", 0)
        dstat("CLIP ↑", "dstat_cliphi", 1)
        dstat("CLIP ↓", "dstat_cliplo", 2)
        dstat("SAMPLES", "dstat_samps", 3)
        dstat("ENV GAIN", "dstat_env", 4)
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

    def _build_lsl_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(8)

        lsl_label = QLabel("LSL  STREAM")
        lsl_label.setObjectName("section_label")
        v.addWidget(lsl_label)

        stream_box = QGroupBox("CONNECTION")
        stream_grid = QGridLayout(stream_box)
        stream_grid.setHorizontalSpacing(8)
        stream_grid.setVerticalSpacing(6)

        self.lsl_stream_combo = QComboBox()
        self.lsl_stream_combo.setMinimumWidth(360)
        self.lsl_stream_combo.currentIndexChanged.connect(self._update_lsl_stream_preview)
        stream_grid.addWidget(self.lsl_stream_combo, 0, 0, 1, 3)

        self.lsl_refresh_btn = QPushButton("REFRESH")
        self.lsl_refresh_btn.clicked.connect(self._refresh_lsl_streams)
        stream_grid.addWidget(self.lsl_refresh_btn, 1, 0)

        self.lsl_connect_btn = QPushButton("CONNECT")
        self.lsl_connect_btn.clicked.connect(self._connect_lsl_stream)
        stream_grid.addWidget(self.lsl_connect_btn, 1, 1)

        self.lsl_disconnect_btn = QPushButton("DISCONNECT")
        self.lsl_disconnect_btn.clicked.connect(self._disconnect_lsl_stream)
        self.lsl_disconnect_btn.setEnabled(False)
        stream_grid.addWidget(self.lsl_disconnect_btn, 1, 2)

        self.lsl_status_label = QLabel("Disconnected")
        self.lsl_status_label.setStyleSheet(
            f"color:{COLORS['text_dim']};font-size:11px;background-color:transparent;"
        )
        stream_grid.addWidget(self.lsl_status_label, 2, 0, 1, 3)

        self.lsl_meta_text = QTextEdit()
        self.lsl_meta_text.setReadOnly(True)
        self.lsl_meta_text.setMaximumHeight(120)
        stream_grid.addWidget(self.lsl_meta_text, 3, 0, 1, 3)
        v.addWidget(stream_box)

        filter_label = QLabel("RECORDING  FILTERS")
        filter_label.setObjectName("section_label")
        v.addWidget(filter_label)

        filter_box = QGroupBox("FILTERS")
        filter_grid = QGridLayout(filter_box)
        filter_grid.setHorizontalSpacing(10)
        filter_grid.setVerticalSpacing(6)

        self.bandpass_enabled = QCheckBox("Bandpass")
        self.bandpass_enabled.setChecked(True)
        filter_grid.addWidget(self.bandpass_enabled, 0, 0)

        self.bandpass_low = make_spinbox(0.01, 5000.0, 2, 0.5, 0.5, "Hz")
        self.bandpass_high = make_spinbox(0.01, 5000.0, 2, 1.0, 40.0, "Hz")
        self.bandpass_order = QSpinBox()
        self.bandpass_order.setRange(1, 12)
        self.bandpass_order.setValue(4)
        filter_grid.addWidget(QLabel("Low"), 1, 0)
        filter_grid.addWidget(self.bandpass_low, 1, 1)
        filter_grid.addWidget(QLabel("High"), 2, 0)
        filter_grid.addWidget(self.bandpass_high, 2, 1)
        filter_grid.addWidget(QLabel("Order"), 3, 0)
        filter_grid.addWidget(self.bandpass_order, 3, 1)

        self.notch_enabled = QCheckBox("Notch")
        self.notch_enabled.setChecked(True)
        filter_grid.addWidget(self.notch_enabled, 0, 2)

        self.notch_freq = make_spinbox(0.01, 5000.0, 2, 1.0, 50.0, "Hz")
        self.notch_q = make_spinbox(0.1, 500.0, 1, 1.0, 30.0, "Q")
        filter_grid.addWidget(QLabel("Freq"), 1, 2)
        filter_grid.addWidget(self.notch_freq, 1, 3)
        filter_grid.addWidget(QLabel("Q"), 2, 2)
        filter_grid.addWidget(self.notch_q, 2, 3)

        self.recording_status_label = QLabel("Recording: idle")
        self.recording_status_label.setStyleSheet(
            f"color:{COLORS['text_dim']};font-size:11px;background-color:transparent;"
        )
        filter_grid.addWidget(self.recording_status_label, 4, 0, 1, 4)

        self.export_last_btn = QPushButton("EXPORT LAST")
        self.export_last_btn.clicked.connect(self._export_lsl_recording)
        self.export_last_btn.setEnabled(False)
        filter_grid.addWidget(self.export_last_btn, 5, 0, 1, 4)
        v.addWidget(filter_box)
        v.addStretch()

        self._refresh_lsl_streams()
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
            lbl.setStyleSheet(
                f"color:{COLORS['text_dim']};font-size:14px;background-color:transparent;"
            )
            grid.addWidget(lbl, r, 0)
            grid.addWidget(widget, r, 1)

        if idx == "1":
            self.amp1 = make_spinbox(0, 1.65, 3, 0.05, 0.5, "V")
            self.freq1 = make_spinbox(0, 5000, 2, 10.0, 100.0, "Hz")
            self.phase1 = make_spinbox(-360, 360, 1, 5.0, 0.0, "°")
            for c in (self.amp1, self.freq1, self.phase1):
                c.valueChanged.connect(self._param_changed)
            row("Amplitude", self.amp1)
            row("Frequency", self.freq1)
            row("Phase", self.phase1)
        else:
            self.amp2 = make_spinbox(0, 1.65, 3, 0.05, 0.5, "V")
            self.freq2 = make_spinbox(0, 5000, 2, 10.0, 200.0, "Hz")
            self.phase2 = make_spinbox(-360, 360, 1, 5.0, 0.0, "°")
            for c in (self.amp2, self.freq2, self.phase2):
                c.valueChanged.connect(self._param_changed)
            row("Amplitude", self.amp2)
            row("Frequency", self.freq2)
            row("Phase", self.phase2)
        return box

    def _build_sequence_box(self) -> QGroupBox:
        box = QGroupBox("SEQUENCE  FILE")
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        self.sequence_path_edit = QLineEdit()
        self.sequence_path_edit.setReadOnly(True)
        self.sequence_path_edit.setPlaceholderText("No sequence file loaded")
        grid.addWidget(self.sequence_path_edit, 0, 0, 1, 2)

        self.sequence_status = QLabel("Format: F1  F2  seconds")
        self.sequence_status.setStyleSheet(
            f"color:{COLORS['text_dim']};font-size:10px;background-color:transparent;"
        )
        grid.addWidget(self.sequence_status, 1, 0, 1, 2)

        self.sequence_load_btn = QPushButton("LOAD")
        self.sequence_load_btn.clicked.connect(self._load_sequence_file)
        grid.addWidget(self.sequence_load_btn, 2, 0)

        self.sequence_clear_btn = QPushButton("CLEAR")
        self.sequence_clear_btn.setObjectName("clear_btn")
        self.sequence_clear_btn.clicked.connect(self._clear_sequence_file)
        self.sequence_clear_btn.setEnabled(False)
        grid.addWidget(self.sequence_clear_btn, 2, 1)
        return box

    def _build_global_box(self) -> QGroupBox:
        box = QGroupBox("GLOBAL")
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)

        def row(label, widget):
            r = grid.rowCount()
            lbl = QLabel(label)
            lbl.setStyleSheet(
                f"color:{COLORS['text_dim']};font-size:14px;background-color:transparent;"
            )
            grid.addWidget(lbl, r, 0)
            grid.addWidget(widget, r, 1)

        self.dc_offset = make_spinbox(0, 3.3, 3, 0.05, 1.65, "V")
        self.sample_rate = QSpinBox()
        self.sample_rate.setRange(100, 10000)
        self.sample_rate.setValue(1000)
        self.sample_rate.setSuffix("  Hz")
        self.sample_rate.setSingleStep(1000)
        self.gain_max = make_spinbox(1.0, 20.0, 1, 0.5, 4.0, "×")

        for c in (self.dc_offset, self.sample_rate, self.gain_max):
            c.valueChanged.connect(self._param_changed)

        row("DC Offset", self.dc_offset)
        row("Sample Rate", self.sample_rate)
        row("Max Env Gain", self.gain_max)

        self.clip_label = QLabel("")
        self.clip_label.setStyleSheet(
            f"color:{COLORS['red']};font-size:10px;background-color:transparent;"
        )
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
            f"border-radius:6px; }}"
        )
        grid = QGridLayout(frame)
        grid.setContentsMargins(12, 8, 12, 8)
        grid.setHorizontalSpacing(24)

        def stat(label, attr, col):
            lb = QLabel(label)
            lb.setStyleSheet(
                f"color:{COLORS['text_dim']};font-size:10px;letter-spacing:1px;"
            )
            vl = QLabel("—")
            vl.setStyleSheet(
                f"color:{COLORS['text']};font-family:'JetBrains Mono';font-size:12px;"
            )
            setattr(self, attr, vl)
            grid.addWidget(lb, 0, col)
            grid.addWidget(vl, 1, col)

        stat("PEAK", "stat_peak", 0)
        stat("TROUGH", "stat_trough", 1)
        stat("VRANGE", "stat_range", 2)
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

    # ── LSL helpers ──────────────────────────────────────────────────────────
    def _refresh_lsl_streams(self):
        self.lsl_stream_combo.clear()
        self.lsl_streams = []

        if resolve_streams is None:
            msg = f"pylsl unavailable: {LSL_IMPORT_ERROR}"
            self.lsl_stream_combo.addItem("(pylsl unavailable)")
            self.lsl_status_label.setText(msg)
            self.lsl_connect_btn.setEnabled(False)
            self.lsl_meta_text.setPlainText(msg)
            return

        try:
            self.lsl_status_label.setText("Searching LSL streams...")
            QApplication.processEvents()
            self.lsl_streams = resolve_streams(wait_time=1.0)
        except Exception as e:
            self.lsl_status_label.setText(f"LSL refresh error: {e}")
            self._log(f"LSL refresh error: {e}", COLORS["red"])
            self.lsl_connect_btn.setEnabled(False)
            return

        if not self.lsl_streams:
            self.lsl_stream_combo.addItem("(no LSL streams found)")
            self.lsl_status_label.setText("No LSL streams found")
            self.lsl_connect_btn.setEnabled(False)
            self.lsl_meta_text.clear()
            return

        for info in self.lsl_streams:
            meta = self._read_lsl_stream_meta(info)
            self.lsl_stream_combo.addItem(
                f"{meta['name']} | {meta['type']} | "
                f"{meta['channel_count']} ch | {meta['nominal_srate_hz']} Hz"
            )
        self.lsl_status_label.setText(f"Found {len(self.lsl_streams)} LSL stream(s)")
        self.lsl_connect_btn.setEnabled(self.lsl_inlet is None)
        self._update_lsl_stream_preview()

    def _update_lsl_stream_preview(self):
        idx = self.lsl_stream_combo.currentIndex()
        if idx < 0 or idx >= len(self.lsl_streams):
            return
        meta = self._read_lsl_stream_meta(self.lsl_streams[idx])
        names = self._read_lsl_channel_names(self.lsl_streams[idx], meta["channel_count"])
        self.lsl_meta_text.setPlainText(
            "\n".join(
                [
                    f"name: {meta['name']}",
                    f"type: {meta['type']}",
                    f"source_id: {meta['source_id']}",
                    f"uid: {meta['uid']}",
                    f"channels: {meta['channel_count']}",
                    f"nominal_srate_hz: {meta['nominal_srate_hz']}",
                    f"channel_format: {meta['channel_format']}",
                    f"channel_names: {', '.join(names)}",
                ]
            )
        )

    def _connect_lsl_stream(self):
        if StreamInlet is None:
            self._log(f"Cannot connect LSL: {LSL_IMPORT_ERROR}", COLORS["red"])
            return
        idx = self.lsl_stream_combo.currentIndex()
        if idx < 0 or idx >= len(self.lsl_streams):
            self._log("Select an LSL stream first.", COLORS["yellow"])
            return

        try:
            info = self.lsl_streams[idx]
            self.lsl_inlet = StreamInlet(info, max_buflen=60)
            self.lsl_stream_meta = self._read_lsl_stream_meta(info)
            self.lsl_channel_names = self._read_lsl_channel_names(
                info, self.lsl_stream_meta["channel_count"]
            )
        except Exception as e:
            self.lsl_inlet = None
            self.lsl_stream_meta = {}
            self.lsl_channel_names = []
            self._log(f"LSL connect error: {e}", COLORS["red"])
            self.lsl_status_label.setText(f"LSL connect error: {e}")
            return

        self.lsl_connect_btn.setEnabled(False)
        self.lsl_disconnect_btn.setEnabled(True)
        self.lsl_refresh_btn.setEnabled(False)
        self.lsl_status_label.setText(
            f"Connected: {self.lsl_stream_meta['name']} | "
            f"{self.lsl_stream_meta['channel_count']} ch | "
            f"{self.lsl_stream_meta['nominal_srate_hz']} Hz"
        )
        self._log(f"Connected LSL stream: {self.lsl_stream_meta['name']}", COLORS["green"])

    def _disconnect_lsl_stream(self):
        if self._recording_active or self._running:
            self._log("LSL disconnected during experiment.", COLORS["red"])
            self._stop(reason="LSL disconnected")

        if self.lsl_inlet is not None:
            try:
                self.lsl_inlet.close_stream()
            except Exception:
                pass
        self.lsl_inlet = None
        self.lsl_stream_meta = {}
        self.lsl_channel_names = []
        self.lsl_connect_btn.setEnabled(bool(self.lsl_streams))
        self.lsl_disconnect_btn.setEnabled(False)
        self.lsl_refresh_btn.setEnabled(True)
        self.lsl_status_label.setText("Disconnected")
        self._log("LSL stream disconnected.", COLORS["text_dim"])

    def _read_lsl_stream_meta(self, info) -> dict:
        def read(method_name: str, default):
            try:
                return getattr(info, method_name)()
            except Exception:
                return default

        protocol_version = ""
        library_version = ""
        if pylsl is not None:
            for attr, target in (
                ("protocol_version", "protocol_version"),
                ("library_version", "library_version"),
            ):
                try:
                    value = getattr(pylsl, attr)()
                except Exception:
                    value = ""
                if target == "protocol_version":
                    protocol_version = value
                else:
                    library_version = value

        return {
            "name": read("name", ""),
            "type": read("type", ""),
            "source_id": read("source_id", ""),
            "uid": read("uid", ""),
            "channel_count": int(read("channel_count", 0) or 0),
            "nominal_srate_hz": float(read("nominal_srate", 0.0) or 0.0),
            "channel_format": read("channel_format", ""),
            "lsl_protocol_version": protocol_version,
            "lsl_library_version": library_version,
        }

    def _read_lsl_channel_names(self, info, channel_count: int) -> list[str]:
        names = []
        try:
            ch = info.desc().child("channels").child("channel")
            while ch is not None and not ch.empty():
                label = ch.child_value("label") or ch.child_value("name")
                if label:
                    names.append(label)
                ch = ch.next_sibling()
        except Exception:
            names = []

        while len(names) < channel_count:
            names.append(f"ch_{len(names) + 1}")
        return names[:channel_count]

    def _get_params(self) -> dict:
        return {
            "a1": self.amp1.value(),
            "f1": self.freq1.value(),
            "p1": self.phase1.value(),
            "a2": self.amp2.value(),
            "f2": self.freq2.value(),
            "p2": self.phase2.value(),
            "dc": self.dc_offset.value(),
            "sr": self.sample_rate.value(),
            "gain_max": self.gain_max.value(),
        }

    def _load_sequence_file(self):
        if self._running:
            self._log("Stop output before loading a sequence file.", COLORS["yellow"])
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load frequency sequence",
            "",
            "Text files (*.txt *.csv);;All files (*)",
        )
        if not path:
            return

        try:
            steps = self._parse_sequence_file(path)
        except ValueError as e:
            self._log(f"Sequence file error: {e}", COLORS["red"])
            self.status_bar.showMessage("Sequence file error")
            return

        self.sequence_steps = steps
        self.sequence_file_path = path
        self._sequence_index = 0
        total_seconds = sum(step[2] for step in steps)
        self.sequence_path_edit.setText(Path(path).name)
        self.sequence_path_edit.setToolTip(path)
        self.sequence_status.setText(
            f"{len(steps)} steps | {total_seconds:.3f} s total | UI F1/F2 ignored"
        )
        self.sequence_clear_btn.setEnabled(True)
        self._set_frequency_controls_enabled(False)
        self._log(
            f"Loaded sequence file: {path} ({len(steps)} steps, {total_seconds:.3f} s)",
            COLORS["green"],
        )

    def _clear_sequence_file(self):
        if self._running:
            self._log("Stop output before clearing the sequence file.", COLORS["yellow"])
            return
        self.sequence_steps = []
        self.sequence_file_path = None
        self._sequence_index = 0
        self.sequence_path_edit.clear()
        self.sequence_path_edit.setToolTip("")
        self.sequence_status.setText("Format: F1  F2  seconds")
        self.sequence_clear_btn.setEnabled(False)
        self._set_frequency_controls_enabled(True)
        self._log("Sequence file cleared. UI F1/F2 are active again.", COLORS["text_dim"])

    def _parse_sequence_file(self, path: str) -> list[tuple[float, float, float]]:
        steps = []
        errors = []
        with open(path, "r", encoding="utf-8-sig") as f:
            for line_no, raw in enumerate(f, 1):
                line = raw.strip()
                if not line or line.startswith("#") or line.startswith("//"):
                    continue
                line = re.split(r"\s+#|\s+//", line, maxsplit=1)[0].strip()
                if not line:
                    continue

                parts = [p for p in re.split(r"[\s,;]+", line) if p]
                if len(parts) != 3:
                    errors.append(
                        f"line {line_no}: expected 3 values (F1 F2 seconds), got {len(parts)}"
                    )
                    continue

                try:
                    f1, f2, seconds = (float(p) for p in parts)
                except ValueError:
                    errors.append(f"line {line_no}: values must be numbers")
                    continue

                if not (0 <= f1 <= 5000 and 0 <= f2 <= 5000):
                    errors.append(f"line {line_no}: frequencies must be 0..5000 Hz")
                    continue
                if seconds <= 0:
                    errors.append(f"line {line_no}: seconds must be greater than 0")
                    continue
                steps.append((f1, f2, seconds))

        if errors:
            preview = "; ".join(errors[:5])
            if len(errors) > 5:
                preview += f"; ... and {len(errors) - 5} more"
            raise ValueError(preview)
        if not steps:
            raise ValueError("file has no sequence rows")
        return steps

    def _set_frequency_controls_enabled(self, enabled: bool):
        for widget in (self.freq1, self.freq2):
            widget.setEnabled(enabled)

    def _get_filter_config(self) -> dict:
        return {
            "bandpass_enabled": self.bandpass_enabled.isChecked(),
            "bandpass_low_hz": self.bandpass_low.value(),
            "bandpass_high_hz": self.bandpass_high.value(),
            "bandpass_order": self.bandpass_order.value(),
            "notch_enabled": self.notch_enabled.isChecked(),
            "notch_hz": self.notch_freq.value(),
            "notch_q": self.notch_q.value(),
        }

    def _validate_lsl_recording_ready(self) -> bool:
        if self.lsl_inlet is None:
            self.status_bar.showMessage("Connect an LSL stream before START")
            self._log("Connect an LSL stream before START.", COLORS["red"])
            return False

        missing = []
        for name, err in (
            ("pandas", PANDAS_IMPORT_ERROR),
            ("openpyxl", OPENPYXL_IMPORT_ERROR),
            ("scipy", SCIPY_IMPORT_ERROR),
        ):
            if err is not None:
                missing.append(f"{name}: {err}")
        if missing:
            self.status_bar.showMessage("Missing export/filter dependencies")
            self._log("Missing dependencies: " + " | ".join(missing), COLORS["red"])
            return False

        cfg = self._get_filter_config()
        fs = float(self.lsl_stream_meta.get("nominal_srate_hz", 0.0) or 0.0)
        if fs <= 0:
            self._log("LSL stream must provide a positive nominal sampling rate.", COLORS["red"])
            self.status_bar.showMessage("Invalid LSL sampling rate")
            return False

        nyquist = fs / 2.0
        if cfg["bandpass_enabled"]:
            if cfg["bandpass_low_hz"] <= 0:
                self._log("Bandpass low frequency must be greater than 0.", COLORS["red"])
                return False
            if cfg["bandpass_low_hz"] >= cfg["bandpass_high_hz"]:
                self._log("Bandpass low frequency must be below high frequency.", COLORS["red"])
                return False
            if cfg["bandpass_high_hz"] >= nyquist:
                self._log(
                    f"Bandpass high frequency must be below Nyquist ({nyquist:.3f} Hz).",
                    COLORS["red"],
                )
                return False

        if cfg["notch_enabled"]:
            if cfg["notch_hz"] <= 0:
                self._log("Notch frequency must be greater than 0.", COLORS["red"])
                return False
            if cfg["notch_hz"] >= nyquist:
                self._log(
                    f"Notch frequency must be below Nyquist ({nyquist:.3f} Hz).",
                    COLORS["red"],
                )
                return False
            if cfg["notch_q"] <= 0:
                self._log("Notch Q must be greater than 0.", COLORS["red"])
                return False
        return True

    def _set_current_stim(self, step_index: int, f1: float, f2: float):
        event = {
            "step_index": int(step_index),
            "f1_hz": float(f1),
            "f2_hz": float(f2),
            "app_timestamp": time.time(),
            "lsl_timestamp": float(local_clock()) if local_clock else np.nan,
        }
        with self._stim_lock:
            self._current_stim = {
                "step_index": event["step_index"],
                "f1_hz": event["f1_hz"],
                "f2_hz": event["f2_hz"],
            }
            self._stim_events.append(event)

    def _get_current_stim(self) -> dict:
        with self._stim_lock:
            return dict(self._current_stim)

    def _begin_lsl_recording(self, step_index: int, f1: float, f2: float) -> bool:
        if self.lsl_inlet is None:
            self._log("Cannot start recording: LSL stream is not connected.", COLORS["red"])
            return False

        if self.lsl_worker and self.lsl_worker.is_alive():
            self.lsl_worker.stop()
            self.lsl_worker.join(timeout=1.0)

        if self.lsl_samples:
            self._log("Previous recorded LSL data discarded for a new experiment.", COLORS["yellow"])

        with self.lsl_sample_lock:
            self.lsl_samples.clear()
        self.export_last_btn.setEnabled(False)
        with self._stim_lock:
            self._stim_events = []

        self._record_start_app_time = time.time()
        self._record_end_app_time = None
        self._set_current_stim(step_index, f1, f2)

        try:
            self.lsl_inlet.flush()
        except Exception:
            pass

        self.lsl_worker = LSLRecordingWorker(
            inlet=self.lsl_inlet,
            sample_lock=self.lsl_sample_lock,
            samples=self.lsl_samples,
            stim_getter=self._get_current_stim,
            error_signal=self._lsl_worker_error,
        )
        self._recording_active = True
        self.recording_status_label.setText("Recording: active")
        self.lsl_worker.start()
        self._log("LSL recording started.", COLORS["green"])
        return True

    def _stop_lsl_recording(self, export: bool = True):
        worker = self.lsl_worker
        if worker is not None:
            worker.stop()
            worker.join(timeout=1.5)
            self.lsl_worker = None

        if self._recording_active:
            self._record_end_app_time = time.time()
        self._recording_active = False

        with self.lsl_sample_lock:
            count = len(self.lsl_samples)
        self.recording_status_label.setText(f"Recording: stopped | {count} samples")
        self.export_last_btn.setEnabled(bool(count))
        if count:
            self._log(f"LSL recording stopped: {count} samples.", COLORS["green"])
        else:
            self._log("LSL recording stopped: no samples captured.", COLORS["yellow"])

        if export and count:
            self._export_lsl_recording()

    @Slot(str)
    def _on_lsl_worker_error(self, msg: str):
        self._log(f"LSL recording error: {msg}", COLORS["red"])
        self.status_bar.showMessage(f"LSL recording error: {msg}")
        if self._running:
            self._stop(reason="LSL recording error")

    def _export_lsl_recording(self):
        with self.lsl_sample_lock:
            records = list(self.lsl_samples)
        if not records:
            self._log("No LSL data to export.", COLORS["yellow"])
            return

        default_name = f"experiment_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save experiment export",
            str(Path.cwd() / default_name),
            "Excel workbook (*.xlsx)",
        )
        if not path:
            self._log("Export canceled. Recorded data remains in memory until next START.", COLORS["yellow"])
            self.status_bar.showMessage("Export canceled")
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"

        try:
            data_df, metadata_df = self._build_export_frames(records)
            self._write_xlsx_export(path, data_df, metadata_df)
        except Exception as e:
            self._log(f"Export failed: {e}", COLORS["red"])
            self.status_bar.showMessage(f"Export failed: {e}")
            return

        self._log(f"Export saved: {path}", COLORS["green"])
        self.status_bar.showMessage(f"Export saved: {path}")

    def _build_export_frames(self, records: list[dict]):
        cfg = self._get_filter_config()
        stream_meta = dict(self.lsl_stream_meta)
        nominal_fs = float(stream_meta.get("nominal_srate_hz", 0.0) or 0.0)
        max_sample_len = max((len(r["sample"]) for r in records), default=0)
        channel_count = max(int(stream_meta.get("channel_count", 0) or 0), max_sample_len)
        channel_names = list(self.lsl_channel_names)
        while len(channel_names) < channel_count:
            channel_names.append(f"ch_{len(channel_names) + 1}")
        channel_names = channel_names[:channel_count]
        safe_names = unique_column_names(
            [safe_column_name(name, f"ch_{i + 1}") for i, name in enumerate(channel_names)]
        )

        raw = np.full((len(records), channel_count), np.nan, dtype=np.float64)
        for row_idx, rec in enumerate(records):
            sample = rec["sample"]
            n = min(len(sample), channel_count)
            if n:
                raw[row_idx, :n] = sample[:n]

        filtered, filter_notes = self._apply_recording_filters(raw, nominal_fs, cfg)
        effective_fs = self._compute_effective_srate(records, nominal_fs)
        start_app = self._record_start_app_time or records[0]["app_timestamp"]

        data = {
            "record_elapsed_s": [r["app_timestamp"] - start_app for r in records],
            "lsl_timestamp": [r["lsl_timestamp"] for r in records],
            "app_timestamp": [r["app_timestamp"] for r in records],
            "stim_step_index": [r["stim_step_index"] for r in records],
            "stim_f1_hz": [r["stim_f1_hz"] for r in records],
            "stim_f2_hz": [r["stim_f2_hz"] for r in records],
            "lsl_stream_name": stream_meta.get("name", ""),
            "lsl_stream_type": stream_meta.get("type", ""),
            "lsl_source_id": stream_meta.get("source_id", ""),
            "lsl_nominal_srate_hz": nominal_fs,
            "lsl_effective_srate_hz": effective_fs,
            "bandpass_enabled": cfg["bandpass_enabled"],
            "bandpass_low_hz": cfg["bandpass_low_hz"],
            "bandpass_high_hz": cfg["bandpass_high_hz"],
            "bandpass_order": cfg["bandpass_order"],
            "notch_enabled": cfg["notch_enabled"],
            "notch_hz": cfg["notch_hz"],
            "notch_q": cfg["notch_q"],
        }
        for idx, name in enumerate(safe_names):
            data[f"raw_{name}"] = raw[:, idx]
            data[f"filtered_{name}"] = filtered[:, idx]
        data_df = pd.DataFrame(data)

        p = self._get_params()
        metadata = {
            "export_created_at": datetime.now().isoformat(timespec="seconds"),
            "record_start_app_timestamp": self._record_start_app_time,
            "record_end_app_timestamp": self._record_end_app_time,
            "record_samples": len(records),
            "record_duration_s": (
                (self._record_end_app_time or records[-1]["app_timestamp"]) - start_app
            ),
            "stim_sequence_file": self.sequence_file_path or "",
            "stim_events_json": self._json_value(self._stim_events),
            "lsl_stream_meta_json": self._json_value(stream_meta),
            "lsl_channel_names_json": self._json_value(channel_names),
            "filter_config_json": self._json_value(cfg),
            "filter_notes_json": self._json_value(filter_notes),
            "arduino_params_json": self._json_value(p),
            "serial_port": self.port_combo.currentText(),
            "serial_baud": 115200,
        }
        metadata_df = pd.DataFrame(
            [{"key": key, "value": value} for key, value in metadata.items()]
        )
        return data_df, metadata_df

    def _json_value(self, value) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)

    def _apply_recording_filters(self, raw: np.ndarray, fs: float, cfg: dict):
        notes = []
        filtered = np.nan_to_num(raw.astype(np.float64, copy=True), nan=0.0, posinf=0.0, neginf=0.0)
        if np.isnan(raw).any():
            notes.append("missing raw samples were filled with 0 for filtering")

        if cfg["bandpass_enabled"]:
            sos = butter(
                int(cfg["bandpass_order"]),
                [cfg["bandpass_low_hz"], cfg["bandpass_high_hz"]],
                btype="bandpass",
                fs=fs,
                output="sos",
            )
            try:
                filtered = sosfiltfilt(sos, filtered, axis=0)
                notes.append("bandpass applied with sosfiltfilt")
            except ValueError as e:
                filtered = sosfilt(sos, filtered, axis=0)
                notes.append(f"bandpass fallback to causal sosfilt: {e}")

        if cfg["notch_enabled"]:
            b, a = iirnotch(cfg["notch_hz"], cfg["notch_q"], fs=fs)
            try:
                filtered = filtfilt(b, a, filtered, axis=0)
                notes.append("notch applied with filtfilt")
            except ValueError as e:
                filtered = lfilter(b, a, filtered, axis=0)
                notes.append(f"notch fallback to causal lfilter: {e}")

        if not cfg["bandpass_enabled"] and not cfg["notch_enabled"]:
            notes.append("filters disabled; filtered columns equal raw columns with missing values filled")
        return filtered, notes

    def _compute_effective_srate(self, records: list[dict], nominal_fs: float) -> float:
        stamps = [
            r["lsl_timestamp"]
            for r in records
            if isinstance(r.get("lsl_timestamp"), float) and np.isfinite(r["lsl_timestamp"])
        ]
        if len(stamps) >= 2 and stamps[-1] > stamps[0]:
            return (len(stamps) - 1) / (stamps[-1] - stamps[0])
        return nominal_fs

    def _write_xlsx_export(self, path: str, data_df, metadata_df):
        rows_per_sheet = 1_048_000
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            if len(data_df) <= rows_per_sheet:
                data_df.to_excel(writer, sheet_name="data", index=False)
            else:
                for sheet_idx, start in enumerate(range(0, len(data_df), rows_per_sheet), 1):
                    chunk = data_df.iloc[start : start + rows_per_sheet]
                    chunk.to_excel(writer, sheet_name=f"data_{sheet_idx}", index=False)
            metadata_df.to_excel(writer, sheet_name="metadata", index=False)

    def _check_clipping(self, p: dict) -> str:
        g = p["gain_max"]
        hi = p["dc"] + g * (p["a1"] + p["a2"])
        lo = p["dc"] - g * (p["a1"] + p["a2"])
        w = []
        if hi > 3.3:
            w.append(f"⚠ peak up to +{hi:.3f} V (clamped)")
        if lo < 0.0:
            w.append(f"⚠ trough down to {lo:.3f} V (clamped)")
        return "  ".join(w)

    # ── Preview refresh ───────────────────────────────────────────────────────
    def _refresh_preview(self):
        p = self._get_params()
        self.clip_label.setText(self._check_clipping(p))
        self.canvas.update_plot(
            a1=p["a1"],
            f1=p["f1"],
            p1_deg=p["p1"],
            a2=p["a2"],
            f2=p["f2"],
            p2_deg=p["p2"],
            dc=p["dc"],
            sr=p["sr"],
            gain_max=p["gain_max"],
        )

        t = np.linspace(0, 0.1, 50000)
        denom = np.sin(np.pi * (p["f2"] - p["f1"]) * t + np.pi / 2)
        with np.errstate(divide="ignore", invalid="ignore"):
            env = np.where(
                np.abs(denom) < 1e-9,
                p["gain_max"],
                np.clip(np.abs(1.0 / denom), 0, p["gain_max"]),
            )
        s = np.clip(
            p["dc"]
            + env
            * (
                p["a1"] * np.sin(2 * np.pi * p["f1"] * t + np.radians(p["p1"]))
                + p["a2"] * np.sin(2 * np.pi * p["f2"] * t + np.radians(p["p2"]))
            ),
            0,
            3.3,
        )

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
                v=float(d.get("v", 0)),
                env=float(d.get("env", 0)),
                peak=float(d.get("peak", 0)),
                trough=float(d.get("trough", 0)),
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
            clip_color = (
                COLORS["red"]
                if (d.get("clipHi", 0) or d.get("clipLo", 0))
                else COLORS["text_dim"]
            )
            for lbl in (self.dstat_cliphi, self.dstat_cliplo):
                lbl.setStyleSheet(
                    f"color:{clip_color};font-family:'JetBrains Mono';font-size:11px;"
                )

            # Log to console with compact format
            self._log(
                f"[DBG] V={d['v']:.3f}V  env={d['env']:.3f}  "
                f"peak={d['peak']:.3f}  trough={d['trough']:.3f}  "
                f"clip↑={d['clipHi']}  clip↓={d['clipLo']}  "
                f"ISR={d['isrUs']}µs  n={d['samps']}",
                COLORS["text_dim"],
            )

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
        for attr in (
            "dstat_isr",
            "dstat_cliphi",
            "dstat_cliplo",
            "dstat_samps",
            "dstat_env",
        ):
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
        pass  # preview updates via timer; board updated only on APPLY

    def _send(self, cmd: str) -> str | None:
        resp = self.serial.send(cmd)
        if resp:
            self.status_bar.showMessage(f"← {resp}")
        return resp

    def _apply_all(self):
        self._apply_params(include_frequencies=not bool(self.sequence_steps))
        if self.sequence_steps:
            self._log(
                "Frequency UI fields ignored because a sequence file is loaded.",
                COLORS["text_dim"],
            )

    def _apply_params(
        self,
        include_frequencies: bool = True,
        f1: float | None = None,
        f2: float | None = None,
        header: str = "Applying parameters…",
    ) -> bool:
        if not self.serial.is_open:
            return False
        p = self._get_params()
        target_f1 = p["f1"] if f1 is None else f1
        target_f2 = p["f2"] if f2 is None else f2
        cmds = [
            f"SET A1 {p['a1']:.4f}",
            f"SET P1 {p['p1']:.2f}",
            f"SET A2 {p['a2']:.4f}",
            f"SET P2 {p['p2']:.2f}",
            f"SET DC {p['dc']:.4f}",
            f"SET GM {p['gain_max']:.2f}",
            f"SET SR {int(p['sr'])}",
        ]
        if include_frequencies:
            cmds.insert(1, f"SET F1 {target_f1:.4f}")
            cmds.insert(4, f"SET F2 {target_f2:.4f}")

        self._log(header, COLORS["accent"])
        for cmd in cmds:
            self._log(f"  → {cmd}", COLORS["accent2"])
            self._send(cmd)
        self.status_bar.showMessage("Parameters applied.")
        self._log("Parameters applied.", COLORS["green"])
        return True

    def _start(self):
        if self.sequence_steps:
            self._start_sequence()
            return

        if not self._validate_lsl_recording_ready():
            return

        if not self._apply_params():
            return
        time.sleep(0.05)  # let Due finish ACKing all SET commands
        self._log("→ START", COLORS["green"])
        resp = self._send("START")
        if resp and "OK" in resp:
            p = self._get_params()
            if not self._begin_lsl_recording(step_index=0, f1=p["f1"], f2=p["f2"]):
                self._send("STOP")
                return
            self._running = True
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.status_bar.showMessage("▶ Running")
            self._log("▶ Running", COLORS["green"])
            # Auto-enable debug telemetry if checkbox is on
            if self.dbg_checkbox.isChecked():
                self._send("DBG ON")

    def _start_sequence(self):
        if not self.serial.is_open or not self.sequence_steps:
            return
        if not self._validate_lsl_recording_ready():
            return

        self._sequence_index = 0
        self._running = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.sequence_load_btn.setEnabled(False)
        self.sequence_clear_btn.setEnabled(False)
        name = Path(self.sequence_file_path).name if self.sequence_file_path else "sequence"
        self.status_bar.showMessage(f"▶ Running sequence: {name}")
        self._log(
            f"Starting sequence: {name} ({len(self.sequence_steps)} steps)",
            COLORS["green"],
        )
        self._run_next_sequence_step()

    def _run_next_sequence_step(self):
        if not self._running:
            return
        if not self.serial.is_open:
            self._abort_sequence("serial port disconnected")
            return

        if self._sequence_index >= len(self.sequence_steps):
            self._finish_sequence()
            return

        f1, f2, seconds = self.sequence_steps[self._sequence_index]
        step_no = self._sequence_index + 1
        total = len(self.sequence_steps)
        self._log(
            f"[SEQ {step_no}/{total}] F1={f1:.4f} Hz  F2={f2:.4f} Hz  "
            f"duration={seconds:.3f} s",
            COLORS["accent"],
        )

        if self._sequence_index == 0:
            ok = self._apply_params(
                include_frequencies=True,
                f1=f1,
                f2=f2,
                header="Applying sequence parameters…",
            )
            if not ok:
                self._abort_sequence("serial port is not connected")
                return
            time.sleep(0.05)  # let Due finish ACKing all SET commands
            self._log("→ START", COLORS["green"])
            resp = self._send("START")
            if not resp or "OK" not in resp:
                self._abort_sequence("START was not acknowledged")
                return
            if not self._begin_lsl_recording(step_index=step_no, f1=f1, f2=f2):
                self._abort_sequence("LSL recording did not start")
                return
            if self.dbg_checkbox.isChecked():
                self._send("DBG ON")
        else:
            for cmd in (f"SET F1 {f1:.4f}", f"SET F2 {f2:.4f}"):
                self._log(f"  → {cmd}", COLORS["accent2"])
                self._send(cmd)
            self._set_current_stim(step_no, f1, f2)

        self._sequence_index += 1
        self._sequence_timer.start(max(1, int(seconds * 1000)))

    def _finish_sequence(self):
        self._log("Sequence complete.", COLORS["green"])
        self._stop()
        self.status_bar.showMessage("Sequence complete")

    def _abort_sequence(self, reason: str):
        self._log(f"Sequence aborted: {reason}.", COLORS["red"])
        self._sequence_timer.stop()
        if self.serial.is_open:
            self._log("→ STOP", COLORS["red"])
            self._send("STOP")
        if self._recording_active:
            self._stop_lsl_recording(export=True)
        self._running = False
        self._sequence_index = 0
        self.start_btn.setEnabled(self.serial.is_open)
        self.stop_btn.setEnabled(False)
        self.sequence_load_btn.setEnabled(True)
        self.sequence_clear_btn.setEnabled(bool(self.sequence_steps))
        self.status_bar.showMessage(f"Sequence aborted: {reason}")

    def _stop(self, checked=False, export: bool = True, reason: str = "Stopped"):
        self._sequence_timer.stop()
        self._log("→ STOP", COLORS["red"])
        if self.serial.is_open:
            self._send("STOP")
        if self._recording_active or self.lsl_worker is not None:
            self._stop_lsl_recording(export=export)
        self._running = False
        self._sequence_index = 0
        self.start_btn.setEnabled(self.serial.is_open)
        self.stop_btn.setEnabled(False)
        self.sequence_load_btn.setEnabled(True)
        self.sequence_clear_btn.setEnabled(bool(self.sequence_steps))
        self.status_bar.showMessage(f"■ {reason}")
        self._log(f"■ {reason}", COLORS["red"])
        if self.dbg_checkbox.isChecked() and self.serial.is_open:
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
            if self._running or self._recording_active:
                self._stop(reason="Serial disconnected")
            self._sequence_timer.stop()
            self.connect_btn.setText("CONNECT")
            self.apply_btn.setEnabled(False)
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.sequence_load_btn.setEnabled(True)
            self.sequence_clear_btn.setEnabled(bool(self.sequence_steps))
            self._running = False

    @Slot(str)
    def _on_serial_error(self, msg: str):
        self.status_bar.showMessage(f"Serial error: {msg}")
        self._log(f"Serial error: {msg}", COLORS["red"])

    def closeEvent(self, event):
        if self.serial.is_open:
            self._send("DBG OFF")
        self._stop(export=False)
        if self.lsl_inlet is not None:
            try:
                self.lsl_inlet.close_stream()
            except Exception:
                pass
        self.serial.close()
        super().closeEvent(event)


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(COLORS["bg"]))
    palette.setColor(QPalette.WindowText, QColor(COLORS["text"]))
    palette.setColor(QPalette.Base, QColor(COLORS["surface"]))
    palette.setColor(QPalette.AlternateBase, QColor(COLORS["surface2"]))
    palette.setColor(QPalette.Text, QColor(COLORS["text"]))
    palette.setColor(QPalette.Button, QColor(COLORS["surface2"]))
    palette.setColor(QPalette.ButtonText, QColor(COLORS["text"]))
    palette.setColor(QPalette.Highlight, QColor(COLORS["accent"]))
    palette.setColor(QPalette.HighlightedText, QColor(COLORS["bg"]))
    app.setPalette(palette)
    app.setStyleSheet(STYLE)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
