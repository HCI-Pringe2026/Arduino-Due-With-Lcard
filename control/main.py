"""
dual_sine_controller.py
PySide6 desktop app for controlling the Arduino Due dual-sine DAC firmware.

Requirements:
    pip install PySide6 pyserial numpy pylsl pandas scipy

Usage:
    python dual_sine_controller.py
"""

import sys
import json
import re
import time
import threading
from dataclasses import dataclass
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
    from scipy.signal import butter, filtfilt, iirnotch, lfilter, sosfilt, sosfiltfilt

    SCIPY_IMPORT_ERROR = None
except Exception as e:  # pragma: no cover - depends on local installation
    butter = filtfilt = iirnotch = lfilter = sosfilt = sosfiltfilt = None
    SCIPY_IMPORT_ERROR = e

from PySide6.QtCore import QTimer, Signal, QObject, Slot, Qt
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
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
)

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
QTableWidget {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    color: {COLORS['text']};
    gridline-color: {COLORS['border']};
    selection-background-color: {COLORS['surface2']};
    selection-color: {COLORS['text']};
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 13px;
}}
QHeaderView::section {{
    background-color: {COLORS['surface2']};
    border: 1px solid {COLORS['border']};
    color: {COLORS['accent']};
    padding: 8px;
    font-weight: bold;
}}
QProgressBar {{
    background-color: {COLORS['surface2']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    color: {COLORS['text']};
    min-height: 34px;
    text-align: center;
    font-weight: bold;
}}
QProgressBar::chunk {{
    background-color: {COLORS['accent']};
    border-radius: 5px;
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


# ── Sequence model ────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SequenceStep:
    f1: float
    f2: float | None
    seconds: float


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
        self.setWindowTitle("Контроллер двух синусов  //  Arduino Due  v3.0")
        self.resize(1100, 760)
        self.serial = SerialWorker()
        self.serial.error_occurred.connect(self._on_serial_error)
        self.serial.connected.connect(self._on_connected)
        self.serial.message_received.connect(self._log_rx)
        self._console_append.connect(self._append_console)
        self._lsl_worker_error.connect(self._on_lsl_worker_error)
        self._running = False
        self.sequence_steps: list[SequenceStep] = []
        self.sequence_file_path: str | None = None
        self._sequence_index = 0
        self._sequence_timer = QTimer(self)
        self._sequence_timer.setSingleShot(True)
        self._sequence_timer.timeout.connect(self._run_next_sequence_step)
        self._sequence_progress_timer = QTimer(self)
        self._sequence_progress_timer.timeout.connect(self._update_sequence_progress)
        self._auto_apply_timer = QTimer(self)
        self._auto_apply_timer.setSingleShot(True)
        self._auto_apply_timer.timeout.connect(self._auto_apply_params)
        self._sequence_total_duration = 0.0
        self._sequence_total_start_time: float | None = None
        self._sequence_stage_duration = 0.0
        self._sequence_stage_start_time: float | None = None
        self._sequence_stage_number = 0
        self._sequence_a2_restore_needed = False

        self.lsl_streams = []
        self.lsl_inlet = None
        self.lsl_stream_meta: dict = {}
        self.lsl_channel_names: list[str] = []
        self.lsl_worker: LSLRecordingWorker | None = None
        self.lsl_samples: list[dict] = []
        self.lsl_sample_lock = threading.Lock()
        self._record_sequence_steps: list[SequenceStep] = []
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

        # Signal stats refresh timer (4 fps — purely local math)
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._refresh_signal_stats)
        self._stats_timer.start(250)

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
        left.addWidget(self._build_sine_box("СИНУС  1", "1", COLORS["sine1"]))
        left.addWidget(self._build_sine_box("СИНУС  2", "2", COLORS["sine2"]))
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
        self.tabs.addTab(self._build_preview_tab(), "ПРЕДПРОСМОТР")
        self.tabs.addTab(self._build_debug_tab(), "ОТЛАДКА")
        self.tabs.addTab(self._build_lsl_tab(), "LSL  ЗАПИСЬ")

        right.addWidget(self.tabs, 1)
        self._build_stats_panel(right)

        right_w = QWidget()
        right_w.setLayout(right)

        root.addWidget(left_w)
        root.addWidget(right_w, 1)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Отключено")

    def _build_preview_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(10)

        lbl = QLabel("ТАБЛИЦА  ЭТАПОВ")
        lbl.setObjectName("section_label")
        v.addWidget(lbl)

        self.sequence_table = QTableWidget(0, 4)
        self.sequence_table.setHorizontalHeaderLabels(
            ["№ этапа", "Частота 1", "Частота 2", "Оставшееся время"]
        )
        self.sequence_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.sequence_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.sequence_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sequence_table.verticalHeader().setVisible(False)
        self.sequence_table.setAlternatingRowColors(False)
        header = self.sequence_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        v.addWidget(self.sequence_table, 1)

        self.stage_time_label = QLabel("ТЕКУЩИЙ  ЭТАП")
        self.stage_time_label.setObjectName("section_label")
        v.addWidget(self.stage_time_label)
        self.stage_time_bar = QProgressBar()
        self.stage_time_bar.setRange(0, 1000)
        self.stage_time_bar.setValue(0)
        self.stage_time_bar.setTextVisible(True)
        self.stage_time_bar.setFormat("Этап: ожидание")
        v.addWidget(self.stage_time_bar)

        self.total_time_label = QLabel("ВЕСЬ  ЭКСПЕРИМЕНТ")
        self.total_time_label.setObjectName("section_label")
        v.addWidget(self.total_time_label)
        self.total_time_bar = QProgressBar()
        self.total_time_bar.setRange(0, 1000)
        self.total_time_bar.setValue(0)
        self.total_time_bar.setTextVisible(True)
        self.total_time_bar.setFormat("Эксперимент: ожидание")
        v.addWidget(self.total_time_bar)
        return w

    def _build_debug_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(6)

        telem_label = QLabel("ПОКАЗАТЕЛИ  С  ПЛАТЫ  (~10 Гц)")
        telem_label.setObjectName("section_label")
        v.addWidget(telem_label)

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

        dstat("ISR, мкс", "dstat_isr", 0)
        dstat("КЛИП ↑", "dstat_cliphi", 1)
        dstat("КЛИП ↓", "dstat_cliplo", 2)
        dstat("ОТСЧЕТЫ", "dstat_samps", 3)
        dstat("УСИЛ. ОГИБ.", "dstat_env", 4)
        v.addWidget(stats_frame)

        # ── Raw serial log ────────────────────────────────────────────────────
        log_header = QHBoxLayout()
        log_lbl = QLabel("ЖУРНАЛ  SERIAL")
        log_lbl.setObjectName("section_label")
        log_header.addWidget(log_lbl)
        log_header.addStretch()

        self.dbg_checkbox = QCheckBox("Телеметрия платы (DBG ON)")
        self.dbg_checkbox.setChecked(False)
        self.dbg_checkbox.toggled.connect(self._toggle_dbg)
        log_header.addWidget(self.dbg_checkbox)

        self.autoscroll_cb = QCheckBox("Автопрокрутка")
        self.autoscroll_cb.setChecked(True)
        log_header.addWidget(self.autoscroll_cb)

        clear_btn = QPushButton("ОЧИСТИТЬ")
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
        self.cmd_input.setPlaceholderText("Отправить команду, например STATUS или DBG ON")
        self.cmd_input.returnPressed.connect(self._send_manual_cmd)
        cmd_row.addWidget(self.cmd_input, 1)
        send_btn = QPushButton("ОТПР.")
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

        lsl_label = QLabel("LSL  ПОТОК")
        lsl_label.setObjectName("section_label")
        v.addWidget(lsl_label)

        stream_box = QGroupBox("ПОДКЛЮЧЕНИЕ")
        stream_grid = QGridLayout(stream_box)
        stream_grid.setHorizontalSpacing(8)
        stream_grid.setVerticalSpacing(6)

        self.lsl_stream_combo = QComboBox()
        self.lsl_stream_combo.setMinimumWidth(360)
        self.lsl_stream_combo.currentIndexChanged.connect(self._update_lsl_stream_preview)
        self.lsl_stream_combo.activated.connect(self._connect_selected_lsl_stream)
        stream_grid.addWidget(self.lsl_stream_combo, 0, 0, 1, 3)

        self.lsl_refresh_btn = QPushButton("ОБНОВИТЬ")
        self.lsl_refresh_btn.clicked.connect(self._refresh_lsl_streams)
        stream_grid.addWidget(self.lsl_refresh_btn, 1, 0)

        self.lsl_connect_check = QCheckBox("Отключено")
        self.lsl_connect_check.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.lsl_connect_check.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        stream_grid.addWidget(self.lsl_connect_check, 1, 1, 1, 2)

        self.lsl_status_label = QLabel("Отключено")
        self.lsl_status_label.setStyleSheet(
            f"color:{COLORS['text_dim']};font-size:11px;background-color:transparent;"
        )
        stream_grid.addWidget(self.lsl_status_label, 2, 0, 1, 3)

        self.lsl_meta_text = QTextEdit()
        self.lsl_meta_text.setReadOnly(True)
        self.lsl_meta_text.setMaximumHeight(120)
        stream_grid.addWidget(self.lsl_meta_text, 3, 0, 1, 3)
        v.addWidget(stream_box)

        filter_label = QLabel("ФИЛЬТРЫ  ЗАПИСИ")
        filter_label.setObjectName("section_label")
        v.addWidget(filter_label)

        filter_box = QGroupBox("ФИЛЬТРЫ")
        filter_grid = QGridLayout(filter_box)
        filter_grid.setHorizontalSpacing(10)
        filter_grid.setVerticalSpacing(6)

        self.bandpass_enabled = QCheckBox("Полосовой")
        self.bandpass_enabled.setChecked(True)
        filter_grid.addWidget(self.bandpass_enabled, 0, 0)

        self.bandpass_low = make_spinbox(0.01, 5000.0, 2, 0.5, 0.5, "Гц")
        self.bandpass_high = make_spinbox(0.01, 5000.0, 2, 1.0, 40.0, "Гц")
        self.bandpass_order = QSpinBox()
        self.bandpass_order.setRange(1, 12)
        self.bandpass_order.setValue(4)
        filter_grid.addWidget(QLabel("Низ"), 1, 0)
        filter_grid.addWidget(self.bandpass_low, 1, 1)
        filter_grid.addWidget(QLabel("Верх"), 2, 0)
        filter_grid.addWidget(self.bandpass_high, 2, 1)
        filter_grid.addWidget(QLabel("Порядок"), 3, 0)
        filter_grid.addWidget(self.bandpass_order, 3, 1)

        self.notch_enabled = QCheckBox("Режекторный")
        self.notch_enabled.setChecked(True)
        filter_grid.addWidget(self.notch_enabled, 0, 2)

        self.notch_freq = make_spinbox(0.01, 5000.0, 2, 1.0, 50.0, "Гц")
        self.notch_q = make_spinbox(0.1, 500.0, 1, 1.0, 30.0, "Q")
        filter_grid.addWidget(QLabel("Частота"), 1, 2)
        filter_grid.addWidget(self.notch_freq, 1, 3)
        filter_grid.addWidget(QLabel("Q"), 2, 2)
        filter_grid.addWidget(self.notch_q, 2, 3)

        self.recording_status_label = QLabel("Запись: ожидание")
        self.recording_status_label.setStyleSheet(
            f"color:{COLORS['text_dim']};font-size:11px;background-color:transparent;"
        )
        filter_grid.addWidget(self.recording_status_label, 4, 0, 1, 4)

        self.export_last_btn = QPushButton("ЭКСПОРТ ПОСЛЕДНЕЙ ЗАПИСИ В TXT")
        self.export_last_btn.clicked.connect(self._export_lsl_recording)
        self.export_last_btn.setEnabled(False)
        filter_grid.addWidget(self.export_last_btn, 5, 0, 1, 4)
        v.addWidget(filter_box)
        v.addStretch()

        self._refresh_lsl_streams()
        return w

    def _build_connection_box(self) -> QGroupBox:
        box = QGroupBox("ПОДКЛЮЧЕНИЕ")
        lay = QHBoxLayout(box)
        lay.setSpacing(6)

        self.port_combo = QComboBox()
        self._refresh_ports()
        self.port_combo.activated.connect(self._connect_selected_serial_port)
        lay.addWidget(self.port_combo)

        refresh_btn = QPushButton("⟳")
        refresh_btn.setFixedWidth(32)
        refresh_btn.clicked.connect(self._refresh_ports)
        lay.addWidget(refresh_btn)

        self.serial_connect_check = QCheckBox("Отключено")
        self.serial_connect_check.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.serial_connect_check.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lay.addWidget(self.serial_connect_check)
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
            self.amp1 = make_spinbox(0, 1.65, 3, 0.05, 0.5, "В")
            self.freq1 = make_spinbox(0, 5000, 2, 10.0, 100.0, "Гц")
            self.phase1 = make_spinbox(-360, 360, 1, 5.0, 0.0, "°")
            for c in (self.amp1, self.freq1, self.phase1):
                c.valueChanged.connect(self._param_changed)
            row("Амплитуда", self.amp1)
            row("Частота", self.freq1)
            row("Фаза", self.phase1)
        else:
            self.amp2 = make_spinbox(0, 1.65, 3, 0.05, 0.5, "В")
            self.freq2 = make_spinbox(0, 5000, 2, 10.0, 200.0, "Гц")
            self.phase2 = make_spinbox(-360, 360, 1, 5.0, 0.0, "°")
            for c in (self.amp2, self.freq2, self.phase2):
                c.valueChanged.connect(self._param_changed)
            row("Амплитуда", self.amp2)
            row("Частота", self.freq2)
            row("Фаза", self.phase2)
        return box

    def _build_sequence_box(self) -> QGroupBox:
        box = QGroupBox("ФАЙЛ  ЧАСТОТ")
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        self.sequence_path_edit = QLineEdit()
        self.sequence_path_edit.setReadOnly(True)
        self.sequence_path_edit.setPlaceholderText("Файл последовательности не загружен")
        grid.addWidget(self.sequence_path_edit, 0, 0, 1, 2)

        self.sequence_status = QLabel("Формат: F1 секунды или F1 F2 секунды")
        self.sequence_status.setStyleSheet(
            f"color:{COLORS['text_dim']};font-size:10px;background-color:transparent;"
        )
        grid.addWidget(self.sequence_status, 1, 0, 1, 2)

        self.sequence_load_btn = QPushButton("ЗАГРУЗИТЬ")
        self.sequence_load_btn.clicked.connect(self._load_sequence_file)
        grid.addWidget(self.sequence_load_btn, 2, 0)

        self.sequence_clear_btn = QPushButton("СБРОС")
        self.sequence_clear_btn.setObjectName("clear_btn")
        self.sequence_clear_btn.clicked.connect(self._clear_sequence_file)
        self.sequence_clear_btn.setEnabled(False)
        grid.addWidget(self.sequence_clear_btn, 2, 1)
        return box

    def _build_global_box(self) -> QGroupBox:
        box = QGroupBox("ОБЩИЕ")
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

        self.dc_offset = make_spinbox(0, 3.3, 3, 0.05, 1.65, "В")
        self.sample_rate = QSpinBox()
        self.sample_rate.setRange(100, 10000)
        self.sample_rate.setValue(1000)
        self.sample_rate.setSuffix("  Гц")
        self.sample_rate.setSingleStep(1000)
        self.gain_max = make_spinbox(1.0, 20.0, 1, 0.5, 4.0, "×")

        for c in (self.dc_offset, self.sample_rate, self.gain_max):
            c.valueChanged.connect(self._param_changed)

        row("DC смещение", self.dc_offset)
        row("Частота дискр.", self.sample_rate)
        row("Макс. огиб.", self.gain_max)

        self.clip_label = QLabel("")
        self.clip_label.setStyleSheet(
            f"color:{COLORS['red']};font-size:10px;background-color:transparent;"
        )
        grid.addWidget(self.clip_label, grid.rowCount(), 0, 1, 3)
        return box

    def _build_transport_box(self) -> QGroupBox:
        box = QGroupBox("УПРАВЛЕНИЕ")
        lay = QHBoxLayout(box)
        lay.setSpacing(8)

        self.start_btn = QPushButton("▶  СТАРТ")
        self.start_btn.setObjectName("start_btn")
        self.start_btn.clicked.connect(self._start)
        self.start_btn.setEnabled(False)

        self.stop_btn = QPushButton("■  СТОП")
        self.stop_btn.setObjectName("stop_btn")
        self.stop_btn.clicked.connect(self._stop)
        self.stop_btn.setEnabled(False)

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

        stat("ПИК", "stat_peak", 0)
        stat("МИНИМУМ", "stat_trough", 1)
        stat("РАЗМАХ", "stat_range", 2)
        stat("НАЙКВИСТ", "stat_nyquist", 3)
        layout.addWidget(frame)

    # ── Port helpers ──────────────────────────────────────────────────────────
    def _refresh_ports(self):
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for p in ports:
            self.port_combo.addItem(p.device)
        if not ports:
            self.port_combo.addItem("(порты не найдены)")

    def _connect_selected_serial_port(self, idx: int | None = None):
        port = self.port_combo.currentText()
        if not port or "no ports" in port or "порты не найдены" in port:
            self._log("Serial-порт не выбран.", COLORS["yellow"])
            self._set_serial_checkbox(False)
            return

        if self.serial.is_open:
            if self._running or self._recording_active:
                self._stop(reason="Serial переключен")
            else:
                self.serial.close()

        self.status_bar.showMessage(f"Подключение к {port} …")
        self._log(f"Подключение к {port} @ 115200 …", COLORS["accent"])
        ok = self.serial.open(port)
        if ok:
            self.status_bar.showMessage(f"Подключено  ·  {port}  @  115200 бод")
            self._log(f"Подключено к {port}.", COLORS["green"])
        else:
            self._set_serial_checkbox(False)

    # ── LSL helpers ──────────────────────────────────────────────────────────
    def _refresh_lsl_streams(self):
        self.lsl_stream_combo.clear()
        self.lsl_streams = []

        if resolve_streams is None:
            msg = f"pylsl недоступен: {LSL_IMPORT_ERROR}"
            self.lsl_stream_combo.addItem("(pylsl недоступен)")
            self.lsl_status_label.setText(msg)
            self._set_lsl_checkbox(False, enabled=False)
            self.lsl_meta_text.setPlainText(msg)
            return

        try:
            self.lsl_status_label.setText("Поиск LSL-потоков...")
            QApplication.processEvents()
            self.lsl_streams = resolve_streams(wait_time=1.0)
        except Exception as e:
            self.lsl_status_label.setText(f"Ошибка обновления LSL: {e}")
            self._log(f"Ошибка обновления LSL: {e}", COLORS["red"])
            self._set_lsl_checkbox(False, enabled=False)
            return

        if not self.lsl_streams:
            self.lsl_stream_combo.addItem("(LSL-потоки не найдены)")
            self.lsl_status_label.setText("LSL-потоки не найдены")
            self._set_lsl_checkbox(False, enabled=False)
            self.lsl_meta_text.clear()
            return

        for info in self.lsl_streams:
            meta = self._read_lsl_stream_meta(info)
            self.lsl_stream_combo.addItem(
                f"{meta['name']} | {meta['type']} | "
                f"{meta['channel_count']} кан. | {meta['nominal_srate_hz']} Гц"
            )
        self.lsl_status_label.setText(f"Найдено LSL-потоков: {len(self.lsl_streams)}")
        self._set_lsl_checkbox(self.lsl_inlet is not None, enabled=True)
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
                    f"имя: {meta['name']}",
                    f"тип: {meta['type']}",
                    f"source_id: {meta['source_id']}",
                    f"uid: {meta['uid']}",
                    f"каналов: {meta['channel_count']}",
                    f"частота_дискретизации_Гц: {meta['nominal_srate_hz']}",
                    f"формат_канала: {meta['channel_format']}",
                    f"имена_каналов: {', '.join(names)}",
                ]
            )
        )

    def _connect_lsl_stream(self):
        if StreamInlet is None:
            self._log(f"Не удалось подключить LSL: {LSL_IMPORT_ERROR}", COLORS["red"])
            self._set_lsl_checkbox(False, enabled=False)
            return
        idx = self.lsl_stream_combo.currentIndex()
        if idx < 0 or idx >= len(self.lsl_streams):
            self._log("Сначала выберите LSL-поток.", COLORS["yellow"])
            self._set_lsl_checkbox(False, enabled=bool(self.lsl_streams))
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
            self._log(f"Ошибка подключения LSL: {e}", COLORS["red"])
            self.lsl_status_label.setText(f"Ошибка подключения LSL: {e}")
            self._set_lsl_checkbox(False, enabled=True)
            return

        self._set_lsl_checkbox(True, enabled=True)
        self.lsl_refresh_btn.setEnabled(False)
        self.lsl_status_label.setText(
            f"Подключено: {self.lsl_stream_meta['name']} | "
            f"{self.lsl_stream_meta['channel_count']} кан. | "
            f"{self.lsl_stream_meta['nominal_srate_hz']} Гц"
        )
        self._log(f"LSL-поток подключен: {self.lsl_stream_meta['name']}", COLORS["green"])

    def _connect_selected_lsl_stream(self, idx: int | None = None):
        if self.lsl_inlet is not None:
            self._disconnect_lsl_stream()
        self._connect_lsl_stream()

    def _disconnect_lsl_stream(self):
        if self._recording_active or self._running:
            self._log("LSL отключен во время эксперимента.", COLORS["red"])
            self._stop(reason="LSL отключен")

        if self.lsl_inlet is not None:
            try:
                self.lsl_inlet.close_stream()
            except Exception:
                pass
        self.lsl_inlet = None
        self.lsl_stream_meta = {}
        self.lsl_channel_names = []
        self._set_lsl_checkbox(False, enabled=bool(self.lsl_streams))
        self.lsl_refresh_btn.setEnabled(True)
        self.lsl_status_label.setText("Отключено")
        self._log("LSL-поток отключен.", COLORS["text_dim"])

    def _toggle_lsl_connection(self, checked: bool):
        if checked:
            self._connect_lsl_stream()
        else:
            self._disconnect_lsl_stream()

    def _set_lsl_checkbox(self, checked: bool, enabled: bool = True):
        self.lsl_connect_check.blockSignals(True)
        self.lsl_connect_check.setChecked(checked)
        self.lsl_connect_check.setText("Подключено" if checked else "Отключено")
        self.lsl_connect_check.setEnabled(True)
        self.lsl_connect_check.blockSignals(False)

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
            self._log("Остановите генерацию перед загрузкой файла частот.", COLORS["yellow"])
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Загрузить последовательность частот",
            "",
            "Текстовые файлы (*.txt *.csv);;Все файлы (*)",
        )
        if not path:
            return

        try:
            steps = self._parse_sequence_file(path)
        except ValueError as e:
            self._log(f"Ошибка файла частот: {e}", COLORS["red"])
            self.status_bar.showMessage("Ошибка файла частот")
            return

        self.sequence_steps = steps
        self.sequence_file_path = path
        self._sequence_index = 0
        total_seconds = self._sequence_total_seconds()
        self.sequence_path_edit.setText(Path(path).name)
        self.sequence_path_edit.setToolTip(path)
        self.sequence_status.setText(
            f"Шагов: {len(steps)} | всего: {total_seconds:.3f} с | частоты UI игнорируются"
        )
        self.sequence_clear_btn.setEnabled(True)
        self._set_frequency_controls_enabled(False)
        self._populate_sequence_table()
        self._reset_sequence_progress(total_seconds)
        self.tabs.setCurrentIndex(0)
        self._log(
            f"Файл частот загружен: {path} ({len(steps)} шагов, {total_seconds:.3f} с)",
            COLORS["green"],
        )

    def _clear_sequence_file(self):
        if self._running:
            self._log("Остановите генерацию перед сбросом файла частот.", COLORS["yellow"])
            return
        self.sequence_steps = []
        self.sequence_file_path = None
        self._sequence_index = 0
        self.sequence_path_edit.clear()
        self.sequence_path_edit.setToolTip("")
        self.sequence_status.setText("Формат: F1 секунды или F1 F2 секунды")
        self.sequence_clear_btn.setEnabled(False)
        self._set_frequency_controls_enabled(True)
        self._populate_sequence_table()
        self._reset_sequence_progress()
        self._log("Файл частот сброшен. Поля F1/F2 снова активны.", COLORS["text_dim"])

    def _parse_sequence_file(self, path: str) -> list[SequenceStep]:
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
                if len(parts) not in (2, 3):
                    errors.append(
                        f"строка {line_no}: ожидалось 2 или 3 значения (F1 секунды или F1 F2 секунды), получено {len(parts)}"
                    )
                    continue

                try:
                    values = [float(p) for p in parts]
                except ValueError:
                    errors.append(f"строка {line_no}: значения должны быть числами")
                    continue

                if len(values) == 2:
                    f1, seconds = values
                    f2 = None
                else:
                    f1, f2, seconds = values

                if not (0 <= f1 <= 5000) or (f2 is not None and not (0 <= f2 <= 5000)):
                    errors.append(f"строка {line_no}: частоты должны быть в диапазоне 0..5000 Гц")
                    continue
                if seconds <= 0:
                    errors.append(f"строка {line_no}: длительность должна быть больше 0")
                    continue
                steps.append(SequenceStep(f1=f1, f2=f2, seconds=seconds))

        if errors:
            preview = "; ".join(errors[:5])
            if len(errors) > 5:
                preview += f"; ... и еще {len(errors) - 5}"
            raise ValueError(preview)
        if not steps:
            raise ValueError("в файле нет строк последовательности")
        return steps

    def _set_frequency_controls_enabled(self, enabled: bool):
        for widget in (self.freq1, self.freq2):
            widget.setEnabled(enabled)

    def _sequence_total_seconds(self) -> float:
        return sum(step.seconds for step in self.sequence_steps)

    def _format_seconds(self, seconds: float) -> str:
        seconds = max(0.0, float(seconds))
        total = int(round(seconds))
        hours, rem = divmod(total, 3600)
        minutes, secs = divmod(rem, 60)
        if hours:
            return f"{hours:d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    def _format_step_frequency(self, value: float | None) -> str:
        if value is None:
            return "выкл."
        return f"{value:.4f} Гц"

    def _make_sequence_table_item(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        return item

    def _populate_sequence_table(self):
        self.sequence_table.setRowCount(len(self.sequence_steps))
        for row, step in enumerate(self.sequence_steps):
            values = [
                str(row + 1),
                self._format_step_frequency(step.f1),
                self._format_step_frequency(step.f2),
                self._format_seconds(step.seconds),
            ]
            for col, value in enumerate(values):
                self.sequence_table.setItem(row, col, self._make_sequence_table_item(value))
            self.sequence_table.setRowHeight(row, 38)
        self._style_sequence_table()

    def _set_sequence_remaining(self, step_no: int, text: str):
        row = step_no - 1
        if row < 0 or row >= self.sequence_table.rowCount():
            return
        item = self.sequence_table.item(row, 3)
        if item is not None:
            item.setText(text)

    def _reset_sequence_table_remaining(self):
        for row, step in enumerate(self.sequence_steps):
            item = self.sequence_table.item(row, 3)
            if item is not None:
                item.setText(self._format_seconds(step.seconds))

    def _style_sequence_table(
        self,
        current_step_no: int | None = None,
        completed_until: int = 0,
    ):
        for row in range(self.sequence_table.rowCount()):
            step_no = row + 1
            if current_step_no == step_no:
                bg = QColor(COLORS["accent"])
                fg = QColor(COLORS["bg"])
            elif step_no <= completed_until:
                bg = QColor(COLORS["surface2"])
                fg = QColor(COLORS["text_dim"])
            else:
                bg = QColor(COLORS["surface"])
                fg = QColor(COLORS["text"])
            for col in range(self.sequence_table.columnCount()):
                item = self.sequence_table.item(row, col)
                if item is not None:
                    item.setBackground(bg)
                    item.setForeground(fg)

    def _reset_sequence_progress(self, total_seconds: float = 0.0):
        self._sequence_progress_timer.stop()
        self._sequence_total_duration = float(total_seconds)
        self._sequence_total_start_time = None
        self._sequence_stage_duration = 0.0
        self._sequence_stage_start_time = None
        self._sequence_stage_number = 0
        self.stage_time_bar.setValue(0)
        self.stage_time_bar.setFormat("Этап: ожидание")
        self._reset_sequence_table_remaining()
        self._style_sequence_table()
        if total_seconds > 0:
            self.total_time_bar.setValue(0)
            self.total_time_bar.setFormat(
                f"Эксперимент: всего {self._format_seconds(total_seconds)}"
            )
        else:
            self.total_time_bar.setValue(0)
            self.total_time_bar.setFormat("Эксперимент: ожидание")

    def _begin_sequence_stage_progress(self, step_no: int, total_steps: int, seconds: float):
        now = time.monotonic()
        if self._sequence_total_start_time is None:
            self._sequence_total_start_time = now
        self._sequence_stage_start_time = now
        self._sequence_stage_duration = float(seconds)
        self._sequence_stage_number = step_no
        self._set_sequence_remaining(step_no - 1, "00:00")
        self._style_sequence_table(current_step_no=step_no, completed_until=step_no - 1)
        self._sequence_progress_timer.start(200)
        self._update_sequence_progress(total_steps=total_steps)

    def _update_sequence_progress(self, total_steps: int | None = None):
        if self._sequence_stage_start_time is None or self._sequence_total_start_time is None:
            return

        now = time.monotonic()
        stage_elapsed = now - self._sequence_stage_start_time
        stage_remaining = max(0.0, self._sequence_stage_duration - stage_elapsed)
        total_elapsed = now - self._sequence_total_start_time
        total_remaining = max(0.0, self._sequence_total_duration - total_elapsed)
        total_steps = total_steps or len(self.sequence_steps)

        stage_value = 0
        if self._sequence_stage_duration > 0:
            stage_value = int(
                (min(stage_elapsed, self._sequence_stage_duration) / self._sequence_stage_duration)
                * 1000
            )
        total_value = 0
        if self._sequence_total_duration > 0:
            total_value = int(
                (min(total_elapsed, self._sequence_total_duration) / self._sequence_total_duration)
                * 1000
            )

        self.stage_time_bar.setValue(max(0, min(1000, stage_value)))
        self.total_time_bar.setValue(max(0, min(1000, total_value)))
        self.stage_time_bar.setFormat(
            f"Этап {self._sequence_stage_number}/{total_steps}: "
            f"осталось {self._format_seconds(stage_remaining)}"
        )
        self.total_time_bar.setFormat(
            f"Эксперимент: осталось {self._format_seconds(total_remaining)}"
        )
        self._set_sequence_remaining(
            self._sequence_stage_number,
            self._format_seconds(stage_remaining),
        )

    def _finish_sequence_progress(self):
        self._sequence_progress_timer.stop()
        self.stage_time_bar.setValue(1000)
        self.total_time_bar.setValue(1000)
        self.stage_time_bar.setFormat("Этап: завершен")
        self.total_time_bar.setFormat("Эксперимент: завершен")
        for row in range(self.sequence_table.rowCount()):
            item = self.sequence_table.item(row, 3)
            if item is not None:
                item.setText("00:00")
        self._style_sequence_table(completed_until=len(self.sequence_steps))
        self._sequence_stage_start_time = None
        self._sequence_total_start_time = None

    def _stop_sequence_progress(self):
        self._sequence_progress_timer.stop()
        if self._sequence_stage_start_time is not None:
            self._update_sequence_progress()
            self.stage_time_bar.setFormat(self.stage_time_bar.format() + " (остановлено)")
            self.total_time_bar.setFormat(self.total_time_bar.format() + " (остановлено)")
            self._sequence_stage_start_time = None
            self._sequence_total_start_time = None

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
            self.status_bar.showMessage("Подключите LSL-поток перед стартом")
            self._log("Подключите LSL-поток перед стартом.", COLORS["red"])
            return False

        missing = []
        for name, err in (
            ("pandas", PANDAS_IMPORT_ERROR),
            ("scipy", SCIPY_IMPORT_ERROR),
        ):
            if err is not None:
                missing.append(f"{name}: {err}")
        if missing:
            self.status_bar.showMessage("Не установлены зависимости экспорта/фильтров")
            self._log("Не установлены зависимости: " + " | ".join(missing), COLORS["red"])
            return False

        cfg = self._get_filter_config()
        fs = float(self.lsl_stream_meta.get("nominal_srate_hz", 0.0) or 0.0)
        if fs <= 0:
            self._log("LSL-поток должен иметь положительную частоту дискретизации.", COLORS["red"])
            self.status_bar.showMessage("Некорректная частота дискретизации LSL")
            return False

        nyquist = fs / 2.0
        if cfg["bandpass_enabled"]:
            if cfg["bandpass_low_hz"] <= 0:
                self._log("Нижняя частота полосового фильтра должна быть больше 0.", COLORS["red"])
                return False
            if cfg["bandpass_low_hz"] >= cfg["bandpass_high_hz"]:
                self._log("Нижняя частота полосового фильтра должна быть меньше верхней.", COLORS["red"])
                return False
            if cfg["bandpass_high_hz"] >= nyquist:
                self._log(
                    f"Верхняя частота полосового фильтра должна быть ниже Найквиста ({nyquist:.3f} Гц).",
                    COLORS["red"],
                )
                return False

        if cfg["notch_enabled"]:
            if cfg["notch_hz"] <= 0:
                self._log("Частота режекторного фильтра должна быть больше 0.", COLORS["red"])
                return False
            if cfg["notch_hz"] >= nyquist:
                self._log(
                    f"Частота режекторного фильтра должна быть ниже Найквиста ({nyquist:.3f} Гц).",
                    COLORS["red"],
                )
                return False
            if cfg["notch_q"] <= 0:
                self._log("Q режекторного фильтра должен быть больше 0.", COLORS["red"])
                return False
        return True

    def _set_current_stim(self, step_index: int, f1: float, f2: float | None):
        f2_value = np.nan if f2 is None else float(f2)
        event = {
            "step_index": int(step_index),
            "f1_hz": float(f1),
            "f2_hz": f2_value,
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

    def _begin_lsl_recording(self, step_index: int, f1: float, f2: float | None) -> bool:
        if self.lsl_inlet is None:
            self._log("Не удалось начать запись: LSL-поток не подключен.", COLORS["red"])
            return False

        if self.lsl_worker and self.lsl_worker.is_alive():
            self.lsl_worker.stop()
            self.lsl_worker.join(timeout=1.0)

        if self.lsl_samples:
            self._log("Предыдущая LSL-запись сброшена перед новым экспериментом.", COLORS["yellow"])

        with self.lsl_sample_lock:
            self.lsl_samples.clear()
        self.export_last_btn.setEnabled(False)
        with self._stim_lock:
            self._stim_events = []

        self._record_sequence_steps = list(self.sequence_steps)
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
        self.recording_status_label.setText("Запись: идет")
        self.lsl_worker.start()
        self._log("LSL-запись начата.", COLORS["green"])
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
        self.recording_status_label.setText(f"Запись: остановлена | отсчетов: {count}")
        self.export_last_btn.setEnabled(bool(count))
        if count:
            self._log(f"LSL-запись остановлена: отсчетов {count}.", COLORS["green"])
        else:
            self._log("LSL-запись остановлена: отсчеты не получены.", COLORS["yellow"])

        if export and count:
            self._export_lsl_recording()

    @Slot(str)
    def _on_lsl_worker_error(self, msg: str):
        self._log(f"Ошибка LSL-записи: {msg}", COLORS["red"])
        self.status_bar.showMessage(f"Ошибка LSL-записи: {msg}")
        if self._running:
            self._stop(reason="ошибка LSL-записи")

    def _export_lsl_recording(self):
        with self.lsl_sample_lock:
            records = list(self.lsl_samples)
        if not records:
            self._log("Нет LSL-данных для экспорта.", COLORS["yellow"])
            return

        default_name = f"experiment_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        dialog_title = (
            "Сохранить базовое имя экспортов по этапам"
            if self._record_sequence_steps
            else "Сохранить экспорт эксперимента"
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            dialog_title,
            str(Path.cwd() / default_name),
            "Текстовый файл (*.txt)",
        )
        if not path:
            self._log("Экспорт отменен. Запись остается в памяти до следующего старта.", COLORS["yellow"])
            self.status_bar.showMessage("Экспорт отменен")
            return
        if not path.lower().endswith(".txt"):
            path += ".txt"

        try:
            if self._record_sequence_steps:
                saved_paths = self._export_sequence_step_logs(path, records)
            else:
                data_df, metadata_df = self._build_export_frames(records)
                self._write_txt_export(path, data_df, metadata_df)
                saved_paths = [path]
        except Exception as e:
            self._log(f"Ошибка экспорта: {e}", COLORS["red"])
            self.status_bar.showMessage(f"Ошибка экспорта: {e}")
            return

        if len(saved_paths) == 1:
            self._log(f"Экспорт сохранен: {saved_paths[0]}", COLORS["green"])
            self.status_bar.showMessage(f"Экспорт сохранен: {saved_paths[0]}")
        else:
            self._log(f"Экспорт сохранен по этапам: {len(saved_paths)} файлов.", COLORS["green"])
            for saved_path in saved_paths:
                self._log(f"  {saved_path}", COLORS["text_dim"])
            self.status_bar.showMessage(f"Экспорт сохранен: {len(saved_paths)} файлов")

    def _export_sequence_step_logs(self, base_path: str, records: list[dict]) -> list[str]:
        saved_paths = []
        total_steps = len(self._record_sequence_steps)
        records_by_step: dict[int, list[dict]] = {idx: [] for idx in range(1, total_steps + 1)}
        for rec in records:
            try:
                step_idx = int(rec.get("stim_step_index", -1))
            except (TypeError, ValueError):
                step_idx = -1
            if step_idx in records_by_step:
                records_by_step[step_idx].append(rec)

        for step_no, step in enumerate(self._record_sequence_steps, 1):
            step_records = records_by_step.get(step_no, [])
            metadata_extra = {
                "export_split_by_step": True,
                "export_step_index": step_no,
                "export_step_total": total_steps,
                "export_step_f1_hz": step.f1,
                "export_step_f2_hz": np.nan if step.f2 is None else step.f2,
                "export_step_duration_s": step.seconds,
                "export_step_records": len(step_records),
            }
            data_df, metadata_df = self._build_export_frames(step_records, metadata_extra)
            step_path = self._step_export_path(base_path, step_no, total_steps)
            self._write_txt_export(step_path, data_df, metadata_df)
            saved_paths.append(step_path)
        return saved_paths

    def _step_export_path(self, base_path: str, step_no: int, total_steps: int) -> str:
        path = Path(base_path)
        suffix = path.suffix or ".txt"
        digits = max(2, len(str(total_steps)))
        return str(path.with_name(f"{path.stem}_step_{step_no:0{digits}d}{suffix}"))

    def _build_export_frames(self, records: list[dict], metadata_extra: dict | None = None):
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
        start_app = self._record_start_app_time
        if start_app is None:
            start_app = records[0]["app_timestamp"] if records else np.nan
        row_count = len(records)

        def repeat(value):
            return [value] * row_count

        data = {
            "record_elapsed_s": [r["app_timestamp"] - start_app for r in records],
            "lsl_timestamp": [r["lsl_timestamp"] for r in records],
            "app_timestamp": [r["app_timestamp"] for r in records],
            "stim_step_index": [r["stim_step_index"] for r in records],
            "stim_f1_hz": [r["stim_f1_hz"] for r in records],
            "stim_f2_hz": [r["stim_f2_hz"] for r in records],
            "lsl_stream_name": repeat(stream_meta.get("name", "")),
            "lsl_stream_type": repeat(stream_meta.get("type", "")),
            "lsl_source_id": repeat(stream_meta.get("source_id", "")),
            "lsl_nominal_srate_hz": repeat(nominal_fs),
            "lsl_effective_srate_hz": repeat(effective_fs),
            "bandpass_enabled": repeat(cfg["bandpass_enabled"]),
            "bandpass_low_hz": repeat(cfg["bandpass_low_hz"]),
            "bandpass_high_hz": repeat(cfg["bandpass_high_hz"]),
            "bandpass_order": repeat(cfg["bandpass_order"]),
            "notch_enabled": repeat(cfg["notch_enabled"]),
            "notch_hz": repeat(cfg["notch_hz"]),
            "notch_q": repeat(cfg["notch_q"]),
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
                ((self._record_end_app_time or records[-1]["app_timestamp"]) - start_app)
                if records and np.isfinite(start_app)
                else 0.0
            ),
            "stim_sequence_file": self.sequence_file_path or "",
            "record_sequence_steps_json": self._json_value(
                self._sequence_steps_to_metadata(self._record_sequence_steps)
            ),
            "stim_events_json": self._json_value(self._stim_events),
            "lsl_stream_meta_json": self._json_value(stream_meta),
            "lsl_channel_names_json": self._json_value(channel_names),
            "filter_config_json": self._json_value(cfg),
            "filter_notes_json": self._json_value(filter_notes),
            "arduino_params_json": self._json_value(p),
            "serial_port": self.port_combo.currentText(),
            "serial_baud": 115200,
        }
        if metadata_extra:
            metadata.update(metadata_extra)
        metadata_df = pd.DataFrame(
            [{"key": key, "value": value} for key, value in metadata.items()]
        )
        return data_df, metadata_df

    def _sequence_steps_to_metadata(self, steps: list[SequenceStep]) -> list[dict]:
        return [
            {
                "step_index": idx,
                "f1_hz": step.f1,
                "f2_hz": np.nan if step.f2 is None else step.f2,
                "duration_s": step.seconds,
            }
            for idx, step in enumerate(steps, 1)
        ]

    def _json_value(self, value) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)

    def _apply_recording_filters(self, raw: np.ndarray, fs: float, cfg: dict):
        notes = []
        filtered = np.nan_to_num(raw.astype(np.float64, copy=True), nan=0.0, posinf=0.0, neginf=0.0)
        if raw.shape[0] == 0:
            notes.append("no samples for this export segment; filtered columns are empty")
            return filtered, notes
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

    def _write_txt_export(self, path: str, data_df, metadata_df):
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("# METADATA\n")
            metadata_df.to_csv(f, sep="\t", index=False, lineterminator="\n")
            f.write("\n# DATA\n")
            data_df.to_csv(f, sep="\t", index=False, lineterminator="\n")

    def _check_clipping(self, p: dict) -> str:
        g = p["gain_max"]
        hi = p["dc"] + g * (p["a1"] + p["a2"])
        lo = p["dc"] - g * (p["a1"] + p["a2"])
        w = []
        if hi > 3.3:
            w.append(f"⚠ пик до +{hi:.3f} В (ограничение)")
        if lo < 0.0:
            w.append(f"⚠ минимум до {lo:.3f} В (ограничение)")
        return "  ".join(w)

    # ── Signal stats refresh ──────────────────────────────────────────────────
    def _refresh_signal_stats(self):
        p = self._get_params()
        self.clip_label.setText(self._check_clipping(p))

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

        self.stat_peak.setText(f"{np.max(s):.3f} В")
        self.stat_trough.setText(f"{np.min(s):.3f} В")
        self.stat_range.setText(f"{np.max(s)-np.min(s):.3f} В")
        self.stat_nyquist.setText(f"{p['sr']/2:.0f} Гц")

    # ── Serial telemetry drain (20 Hz) ────────────────────────────────────────
    def _drain_serial(self):
        for raw in self.serial.drain():
            self._process_incoming(raw)

    def _process_incoming(self, raw: str):
        """Route an unsolicited line to the console and debug stat labels."""
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            self._log(raw, COLORS["text_dim"])
            return

        if d.get("dbg"):
            self._total_clip_hi += int(d.get("clipHi", 0))
            self._total_clip_lo += int(d.get("clipLo", 0))
            self.dstat_isr.setText(f"{d.get('isrUs', '?')} мкс")
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
                f"[DBG] V={d['v']:.3f}В  огиб={d['env']:.3f}  "
                f"пик={d['peak']:.3f}  мин={d['trough']:.3f}  "
                f"клип↑={d['clipHi']}  клип↓={d['clipLo']}  "
                f"ISR={d['isrUs']}мкс  n={d['samps']}",
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
            self._log("(нет ответа / не подключено)", COLORS["red"])
        self.cmd_input.clear()

    def _toggle_dbg(self, enabled: bool):
        cmd = "DBG ON" if enabled else "DBG OFF"
        self._log(f"→ {cmd}", COLORS["accent2"])
        resp = self._send(cmd)

    # ── Serial actions ────────────────────────────────────────────────────────
    def _toggle_connect(self, checked: bool):
        if not checked:
            if not self.serial.is_open:
                self._set_serial_checkbox(False)
                return
            self._stop()
            self.serial.close()
            self._log("Отключено.", COLORS["text_dim"])
        else:
            port = self.port_combo.currentText()
            if port and "no ports" not in port and "порты не найдены" not in port:
                self.status_bar.showMessage(f"Подключение к {port} …")
                self._log(f"Подключение к {port} @ 115200 …", COLORS["accent"])
                ok = self.serial.open(port)
                if ok:
                    self.status_bar.showMessage(f"Подключено  ·  {port}  @  115200 бод")
                    self._log(f"Подключено к {port}.", COLORS["green"])
                else:
                    self._set_serial_checkbox(False)
            else:
                self._log("Serial-порт не выбран.", COLORS["yellow"])
                self._set_serial_checkbox(False)

    def _param_changed(self):
        if self._running and self.sequence_steps:
            return
        if self.serial.is_open:
            self._auto_apply_timer.start(350)

    def _auto_apply_params(self):
        if not self.serial.is_open:
            return
        self._apply_params(
            include_frequencies=not bool(self.sequence_steps),
            header="Автоприменение параметров…",
        )

    def _set_serial_checkbox(self, checked: bool):
        self.serial_connect_check.blockSignals(True)
        self.serial_connect_check.setChecked(checked)
        self.serial_connect_check.setText("Подключено" if checked else "Отключено")
        self.serial_connect_check.blockSignals(False)

    def _send(self, cmd: str) -> str | None:
        resp = self.serial.send(cmd)
        if resp:
            self.status_bar.showMessage(f"← {resp}")
        return resp

    def _apply_all(self):
        self._apply_params(include_frequencies=not bool(self.sequence_steps))
        if self.sequence_steps:
            self._log(
                "Поля частот UI игнорируются, потому что загружен файл последовательности.",
                COLORS["text_dim"],
            )

    def _apply_params(
        self,
        include_frequencies: bool = True,
        f1: float | None = None,
        f2: float | None = None,
        header: str = "Применение параметров…",
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
        self.status_bar.showMessage("Параметры применены.")
        self._log("Параметры применены.", COLORS["green"])
        return True

    def _apply_sequence_step_params(
        self,
        step: SequenceStep,
        include_static: bool,
        header: str | None = None,
    ) -> bool:
        if not self.serial.is_open:
            return False

        p = self._get_params()
        a2_cmd = "SET A2 0.0000" if step.f2 is None else f"SET A2 {p['a2']:.4f}"
        if step.f2 is None:
            self._sequence_a2_restore_needed = True

        if include_static:
            cmds = [
                f"SET A1 {p['a1']:.4f}",
                f"SET F1 {step.f1:.4f}",
                f"SET P1 {p['p1']:.2f}",
                a2_cmd,
            ]
            if step.f2 is not None:
                cmds.append(f"SET F2 {step.f2:.4f}")
            cmds.extend(
                [
                    f"SET P2 {p['p2']:.2f}",
                    f"SET DC {p['dc']:.4f}",
                    f"SET GM {p['gain_max']:.2f}",
                    f"SET SR {int(p['sr'])}",
                ]
            )
        else:
            cmds = [f"SET F1 {step.f1:.4f}", a2_cmd]
            if step.f2 is not None:
                cmds.append(f"SET F2 {step.f2:.4f}")

        if header:
            self._log(header, COLORS["accent"])
        for cmd in cmds:
            self._log(f"  → {cmd}", COLORS["accent2"])
            self._send(cmd)
        return True

    def _restore_sequence_second_signal(self):
        if not self._sequence_a2_restore_needed or not self.serial.is_open:
            self._sequence_a2_restore_needed = False
            return
        cmd = f"SET A2 {self.amp2.value():.4f}"
        self._log(f"  → {cmd} (восстановление Синуса 2)", COLORS["accent2"])
        self._send(cmd)
        self._sequence_a2_restore_needed = False

    def _start(self):
        if self.sequence_steps:
            self._start_sequence()
            return

        if not self._validate_lsl_recording_ready():
            return

        self._auto_apply_timer.stop()
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
            self.status_bar.showMessage("▶ Выполняется")
            self._log("▶ Выполняется", COLORS["green"])
            # Auto-enable debug telemetry if checkbox is on
            if self.dbg_checkbox.isChecked():
                self._send("DBG ON")

    def _start_sequence(self):
        if not self.serial.is_open or not self.sequence_steps:
            return
        if not self._validate_lsl_recording_ready():
            return

        self._auto_apply_timer.stop()
        self._sequence_index = 0
        self._sequence_a2_restore_needed = False
        self._reset_sequence_progress(self._sequence_total_seconds())
        self._running = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.sequence_load_btn.setEnabled(False)
        self.sequence_clear_btn.setEnabled(False)
        name = Path(self.sequence_file_path).name if self.sequence_file_path else "sequence"
        self.status_bar.showMessage(f"▶ Выполняется последовательность: {name}")
        self._log(
            f"Старт последовательности: {name} ({len(self.sequence_steps)} шагов)",
            COLORS["green"],
        )
        self._run_next_sequence_step()

    def _run_next_sequence_step(self):
        if not self._running:
            return
        if not self.serial.is_open:
            self._abort_sequence("serial-порт отключен")
            return

        if self._sequence_index >= len(self.sequence_steps):
            self._finish_sequence()
            return

        step = self.sequence_steps[self._sequence_index]
        step_no = self._sequence_index + 1
        total = len(self.sequence_steps)
        f2_text = "выкл." if step.f2 is None else f"{step.f2:.4f} Гц"
        self._log(
            f"[SEQ {step_no}/{total}] F1={step.f1:.4f} Гц  F2={f2_text}  "
            f"длительность={step.seconds:.3f} с",
            COLORS["accent"],
        )

        if self._sequence_index == 0:
            ok = self._apply_sequence_step_params(
                step,
                include_static=True,
                header="Применение параметров последовательности…",
            )
            if not ok:
                self._abort_sequence("serial-порт не подключен")
                return
            time.sleep(0.05)  # let Due finish ACKing all SET commands
            self._log("→ START", COLORS["green"])
            resp = self._send("START")
            if not resp or "OK" not in resp:
                self._abort_sequence("команда START не подтверждена")
                return
            if not self._begin_lsl_recording(step_index=step_no, f1=step.f1, f2=step.f2):
                self._abort_sequence("LSL-запись не началась")
                return
            if self.dbg_checkbox.isChecked():
                self._send("DBG ON")
        else:
            if not self._apply_sequence_step_params(step, include_static=False):
                self._abort_sequence("serial-порт не подключен")
                return
            self._set_current_stim(step_no, step.f1, step.f2)

        self._begin_sequence_stage_progress(step_no, total, step.seconds)
        self._sequence_index += 1
        self._sequence_timer.start(max(1, int(step.seconds * 1000)))

    def _finish_sequence(self):
        self._log("Последовательность завершена.", COLORS["green"])
        self._stop()
        self._finish_sequence_progress()
        self.status_bar.showMessage("Последовательность завершена")

    def _abort_sequence(self, reason: str):
        self._log(f"Последовательность прервана: {reason}.", COLORS["red"])
        self._sequence_timer.stop()
        self._stop_sequence_progress()
        if self.serial.is_open:
            self._log("→ STOP", COLORS["red"])
            self._send("STOP")
            self._restore_sequence_second_signal()
        if self._recording_active:
            self._stop_lsl_recording(export=True)
        self._running = False
        self._sequence_index = 0
        self.start_btn.setEnabled(self.serial.is_open)
        self.stop_btn.setEnabled(False)
        self.sequence_load_btn.setEnabled(True)
        self.sequence_clear_btn.setEnabled(bool(self.sequence_steps))
        self.status_bar.showMessage(f"Последовательность прервана: {reason}")

    def _stop(self, checked=False, export: bool = True, reason: str = "Остановлено"):
        self._sequence_timer.stop()
        self._auto_apply_timer.stop()
        if self.sequence_steps:
            self._stop_sequence_progress()
        self._log("→ STOP", COLORS["red"])
        if self.serial.is_open:
            self._send("STOP")
            if self.sequence_steps:
                self._restore_sequence_second_signal()
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
            self._set_serial_checkbox(True)
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self._auto_apply_timer.start(200)
        else:
            if self._running or self._recording_active:
                self._stop(reason="Serial отключен")
            self._sequence_timer.stop()
            self._set_serial_checkbox(False)
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.sequence_load_btn.setEnabled(True)
            self.sequence_clear_btn.setEnabled(bool(self.sequence_steps))
            self._running = False

    @Slot(str)
    def _on_serial_error(self, msg: str):
        self.status_bar.showMessage(f"Ошибка Serial: {msg}")
        self._log(f"Ошибка Serial: {msg}", COLORS["red"])

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
def _show_main_window(win: MainWindow, app: QApplication):
    if not sys.platform.startswith("linux"):
        win.showMaximized()
        return

    def apply_linux_maximized():
        screen = win.screen() or app.primaryScreen()
        if screen is not None:
            win.setGeometry(screen.availableGeometry())
        win.setWindowState(win.windowState() | Qt.WindowState.WindowMaximized)
        win.showMaximized()

    screen = app.primaryScreen()
    if screen is not None:
        win.setGeometry(screen.availableGeometry())

    win.show()
    apply_linux_maximized()
    QTimer.singleShot(0, apply_linux_maximized)
    QTimer.singleShot(150, apply_linux_maximized)
    QTimer.singleShot(500, apply_linux_maximized)


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
    _show_main_window(win, app)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
