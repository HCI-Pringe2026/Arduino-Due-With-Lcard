#!/usr/bin/env python3
"""
Arduino Due DAC Controller
PySide6 GUI for real-time control of the Arduino Due two-channel DAC signal generator.
"""

import json
import sys
import threading
import time

import serial
import serial.tools.list_ports
from PySide6.QtCore import (QObject, QTimer, Signal, Slot, Qt)
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QLinearGradient, QPalette
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QComboBox, QPushButton, QSlider, QDoubleSpinBox,
    QGroupBox, QStatusBar, QFrame, QSizePolicy, QSpacerItem, QTabWidget,
    QLineEdit, QTextEdit, QScrollArea
)


# ─────────────────────────── Palette & Fonts ───────────────────────────

DARK_BG      = "#0e1117"
PANEL_BG     = "#161b25"
PANEL_BORDER = "#1f2a3c"
ACCENT_CYAN  = "#00d4ff"
ACCENT_GREEN = "#00ff9d"
ACCENT_AMBER = "#ffb830"
ACCENT_RED   = "#ff4d6d"
TEXT_MAIN    = "#e8edf5"
TEXT_DIM     = "#5a6a82"
BUTTON_BG    = "#1e2d42"
BUTTON_HOV   = "#243550"

FONT_MONO  = "JetBrains Mono, Consolas, monospace"
FONT_LABEL = "Segoe UI, Helvetica Neue, Arial, sans-serif"

SHAPES = ["sine", "square", "triangle", "ramp", "dc"]

DAC_VMIN = 0.55
DAC_VMAX = 2.75

STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {DARK_BG};
    color: {TEXT_MAIN};
    font-family: {FONT_LABEL};
    font-size: 13px;
}}
QGroupBox {{
    background-color: {PANEL_BG};
    border: 1px solid {PANEL_BORDER};
    border-radius: 8px;
    margin-top: 10px;
    padding: 12px 10px 10px 10px;
    font-weight: 600;
    font-size: 11px;
    letter-spacing: 1.5px;
    color: {TEXT_DIM};
    text-transform: uppercase;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: 2px;
    padding: 0 4px;
}}
QPushButton {{
    background-color: {BUTTON_BG};
    color: {TEXT_MAIN};
    border: 1px solid {PANEL_BORDER};
    border-radius: 6px;
    padding: 6px 16px;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}
QPushButton:hover {{
    background-color: {BUTTON_HOV};
    border-color: {ACCENT_CYAN};
    color: {ACCENT_CYAN};
}}
QPushButton:pressed {{
    background-color: {ACCENT_CYAN};
    color: {DARK_BG};
}}
QPushButton:disabled {{
    color: {TEXT_DIM};
    border-color: {PANEL_BORDER};
    background-color: {PANEL_BG};
}}
QPushButton#accent {{
    background-color: {ACCENT_CYAN};
    color: {DARK_BG};
    border-color: {ACCENT_CYAN};
}}
QPushButton#accent:hover {{
    background-color: #33dcff;
    color: {DARK_BG};
}}
QPushButton#danger {{
    background-color: transparent;
    color: {ACCENT_RED};
    border-color: {ACCENT_RED};
}}
QPushButton#danger:hover {{
    background-color: {ACCENT_RED};
    color: white;
}}
QPushButton#green {{
    background-color: transparent;
    color: {ACCENT_GREEN};
    border-color: {ACCENT_GREEN};
}}
QPushButton#green:hover {{
    background-color: {ACCENT_GREEN};
    color: {DARK_BG};
}}
QComboBox {{
    background-color: {BUTTON_BG};
    color: {TEXT_MAIN};
    border: 1px solid {PANEL_BORDER};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 13px;
}}
QComboBox:hover {{
    border-color: {ACCENT_CYAN};
}}
QComboBox QAbstractItemView {{
    background-color: {PANEL_BG};
    color: {TEXT_MAIN};
    border: 1px solid {PANEL_BORDER};
    selection-background-color: {BUTTON_HOV};
}}
QDoubleSpinBox, QSpinBox, QLineEdit {{
    background-color: {BUTTON_BG};
    color: {TEXT_MAIN};
    border: 1px solid {PANEL_BORDER};
    border-radius: 6px;
    padding: 5px 8px;
    font-size: 13px;
    font-family: {FONT_MONO};
}}
QDoubleSpinBox:focus, QSpinBox:focus, QLineEdit:focus {{
    border-color: {ACCENT_CYAN};
}}
QSlider::groove:horizontal {{
    height: 4px;
    background: {PANEL_BORDER};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {ACCENT_CYAN};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT_CYAN};
    border-radius: 2px;
}}
QTextEdit {{
    background-color: #090d13;
    color: {ACCENT_GREEN};
    border: 1px solid {PANEL_BORDER};
    border-radius: 6px;
    font-family: {FONT_MONO};
    font-size: 12px;
    padding: 6px;
}}
QStatusBar {{
    background-color: {PANEL_BG};
    color: {TEXT_DIM};
    border-top: 1px solid {PANEL_BORDER};
    font-size: 12px;
}}
QTabWidget::pane {{
    border: 1px solid {PANEL_BORDER};
    border-radius: 8px;
    background-color: {PANEL_BG};
}}
QTabBar::tab {{
    background-color: {DARK_BG};
    color: {TEXT_DIM};
    border: 1px solid {PANEL_BORDER};
    border-bottom: none;
    padding: 7px 20px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}
QTabBar::tab:selected {{
    color: {ACCENT_CYAN};
    border-bottom: 2px solid {ACCENT_CYAN};
    background-color: {PANEL_BG};
}}
QLabel#title {{
    font-size: 22px;
    font-weight: 700;
    letter-spacing: 2px;
    color: {ACCENT_CYAN};
}}
QLabel#subtitle {{
    font-size: 11px;
    letter-spacing: 3px;
    color: {TEXT_DIM};
    text-transform: uppercase;
}}
QLabel#volt {{
    font-family: {FONT_MONO};
    font-size: 24px;
    font-weight: 700;
    color: {ACCENT_CYAN};
}}
QLabel#volt1 {{
    font-family: {FONT_MONO};
    font-size: 24px;
    font-weight: 700;
    color: {ACCENT_GREEN};
}}
QLabel#status_ok {{
    color: {ACCENT_GREEN};
    font-size: 12px;
    font-weight: 600;
}}
QLabel#status_err {{
    color: {ACCENT_RED};
    font-size: 12px;
    font-weight: 600;
}}
QFrame#sep {{
    color: {PANEL_BORDER};
}}
"""


# ─────────────────────── Serial Worker Thread ────────────────────────

class SerialWorker(QObject):
    received      = Signal(str)
    connected     = Signal()
    disconnected  = Signal()
    error         = Signal(str)

    def __init__(self):
        super().__init__()
        self._port: serial.Serial | None = None
        self._running = False
        self._lock = threading.Lock()

    def open(self, port: str, baud: int = 115200):
        try:
            s = serial.Serial(port, baud, timeout=0.1)
            with self._lock:
                if self._port and self._port.is_open:
                    self._port.close()
                self._port = s
            self._running = True
            t = threading.Thread(target=self._read_loop, daemon=True)
            t.start()
            self.connected.emit()
        except Exception as e:
            self.error.emit(str(e))

    def close(self):
        self._running = False
        with self._lock:
            if self._port and self._port.is_open:
                self._port.close()
                self._port = None
        self.disconnected.emit()

    def send(self, cmd: str):
        with self._lock:
            if self._port and self._port.is_open:
                try:
                    self._port.write((cmd.strip() + "\n").encode())
                except Exception as e:
                    self.error.emit(str(e))

    def _read_loop(self):
        while self._running:
            try:
                with self._lock:
                    port = self._port
                if port and port.is_open:
                    line = port.readline().decode(errors="replace").strip()
                    if line:
                        self.received.emit(line)
                else:
                    time.sleep(0.05)
            except Exception as e:
                self.error.emit(str(e))
                break
        self.disconnected.emit()

    @property
    def is_open(self):
        with self._lock:
            return self._port is not None and self._port.is_open


# ─────────────────────── Waveform Preview Widget ─────────────────────

class WavePreview(QWidget):
    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self.setMinimumSize(180, 60)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._color = QColor(color)
        self._shape = "sine"
        self._freq = 1.0
        self._phase = 0.0
        self._anim_offset = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_wave(self, shape: str, freq: float, phase: float):
        self._shape = shape
        self._freq = freq
        self._phase = phase

    def _tick(self):
        self._anim_offset += 0.04 * max(0.1, min(self._freq, 5.0))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        margin = 4
        pw, ph = w - margin * 2, h - margin * 2

        # Background
        p.fillRect(0, 0, w, h, QColor("#090d13"))

        # Grid lines
        grid_pen = QPen(QColor(PANEL_BORDER), 1)
        p.setPen(grid_pen)
        for i in range(1, 4):
            y = margin + ph * i // 4
            p.drawLine(margin, y, w - margin, y)

        if self._shape == "dc":
            pen = QPen(self._color, 2)
            p.setPen(pen)
            mid = margin + ph // 2
            p.drawLine(margin, mid, w - margin, mid)
            return

        cycles = 2.5
        pen = QPen(self._color, 2)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)

        pts = []
        N = pw
        for i in range(N):
            x = margin + i
            phase = (i / N * cycles + self._anim_offset) % 1.0
            if self._shape == "sine":
                v = 0.5 + 0.5 * __import__("math").sin(6.283185 * phase)
            elif self._shape == "square":
                v = 0.0 if phase < 0.5 else 1.0
            elif self._shape == "triangle":
                v = phase * 2 if phase < 0.5 else (1.0 - phase) * 2
            elif self._shape == "ramp":
                v = phase
            else:
                v = 0.5
            y = margin + ph - int(v * ph)
            pts.append((x, y))

        for i in range(len(pts) - 1):
            p.drawLine(pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1])


# ─────────────────────── Single Channel Panel ─────────────────────────

class ChannelPanel(QGroupBox):
    command_ready = Signal(str)

    def __init__(self, channel: int, color: str, parent=None):
        label = f"DAC {channel}  ·  {'CYAN' if channel == 0 else 'GREEN'}"
        super().__init__(label, parent)
        self.channel = channel
        self.color = color
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # Waveform preview
        self.preview = WavePreview(self.color)
        root.addWidget(self.preview)

        # Voltage readout
        volt_row = QHBoxLayout()
        self.volt_label = QLabel("─.── V")
        self.volt_label.setObjectName("volt" if self.channel == 0 else "volt1")
        self.volt_label.setAlignment(Qt.AlignCenter)
        volt_row.addWidget(self.volt_label)
        root.addLayout(volt_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("sep")
        root.addWidget(sep)

        # Shape selector
        shape_row = QHBoxLayout()
        shape_row.addWidget(QLabel("Shape"))
        self.shape_combo = QComboBox()
        self.shape_combo.addItems([s.capitalize() for s in SHAPES])
        shape_row.addWidget(self.shape_combo, 1)
        root.addLayout(shape_row)

        # Frequency
        freq_row = QHBoxLayout()
        freq_row.addWidget(QLabel("Freq (Hz)"))
        self.freq_spin = QDoubleSpinBox()
        self.freq_spin.setRange(0.01, 100.0)
        self.freq_spin.setValue(1.0)
        self.freq_spin.setDecimals(2)
        self.freq_spin.setSingleStep(0.5)
        freq_row.addWidget(self.freq_spin, 1)
        root.addLayout(freq_row)

        # Amplitude
        amp_row = QHBoxLayout()
        amp_row.addWidget(QLabel("Amp (Vpp)"))
        self.amp_spin = QDoubleSpinBox()
        self.amp_spin.setRange(0.0, DAC_VMAX - DAC_VMIN)
        self.amp_spin.setValue(1.0)
        self.amp_spin.setDecimals(3)
        self.amp_spin.setSingleStep(0.1)
        amp_row.addWidget(self.amp_spin, 1)
        root.addLayout(amp_row)

        # Offset / voltage slider
        off_row = QHBoxLayout()
        off_row.addWidget(QLabel("Offset (V)"))
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(DAC_VMIN, DAC_VMAX)
        self.offset_spin.setValue(1.65)
        self.offset_spin.setDecimals(3)
        self.offset_spin.setSingleStep(0.05)
        off_row.addWidget(self.offset_spin, 1)
        root.addLayout(off_row)

        # Phase
        phase_row = QHBoxLayout()
        phase_row.addWidget(QLabel("Phase (°)"))
        self.phase_spin = QDoubleSpinBox()
        self.phase_spin.setRange(-360.0, 360.0)
        self.phase_spin.setValue(0.0)
        self.phase_spin.setDecimals(1)
        self.phase_spin.setSingleStep(10.0)
        phase_row.addWidget(self.phase_spin, 1)
        root.addLayout(phase_row)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setObjectName("sep")
        root.addWidget(sep2)

        # Action buttons
        btn_row = QHBoxLayout()
        self.apply_btn = QPushButton("▶  Apply")
        self.apply_btn.setObjectName("accent" if self.channel == 0 else "green")
        self.apply_btn.clicked.connect(self._apply)
        btn_row.addWidget(self.apply_btn)

        self.stop_btn = QPushButton("■  Stop")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.clicked.connect(self._stop)
        btn_row.addWidget(self.stop_btn)
        root.addLayout(btn_row)

        # DC direct voltage control
        dc_row = QHBoxLayout()
        dc_row.addWidget(QLabel("DC Voltage"))
        self.dc_spin = QDoubleSpinBox()
        self.dc_spin.setRange(DAC_VMIN, DAC_VMAX)
        self.dc_spin.setValue(1.65)
        self.dc_spin.setDecimals(3)
        self.dc_spin.setSingleStep(0.05)
        dc_row.addWidget(self.dc_spin, 1)
        dc_btn = QPushButton("Set DC")
        dc_btn.clicked.connect(self._set_dc)
        dc_row.addWidget(dc_btn)
        root.addLayout(dc_row)

        # Connect preview updates
        self.shape_combo.currentTextChanged.connect(self._update_preview)
        self.freq_spin.valueChanged.connect(self._update_preview)
        self.phase_spin.valueChanged.connect(self._update_preview)
        self._update_preview()

    def _update_preview(self):
        shape = self.shape_combo.currentText().lower()
        self.preview.set_wave(shape, self.freq_spin.value(), self.phase_spin.value())

    def _apply(self):
        shape = self.shape_combo.currentText().lower()
        freq  = self.freq_spin.value()
        amp   = self.amp_spin.value()
        off   = self.offset_spin.value()
        phase = self.phase_spin.value()
        cmd = f"GEN {self.channel} {shape} {freq:.4f} {amp:.4f} {off:.4f} {phase:.2f}"
        self.command_ready.emit(cmd)

    def _stop(self):
        # Stop only this channel by setting DC to current mid
        self.command_ready.emit("STOP")

    def _set_dc(self):
        v = self.dc_spin.value()
        cmd = f"GEN {self.channel} dc 0 0 {v:.4f} 0"
        self.command_ready.emit(cmd)

    def update_voltage(self, code: int):
        v = DAC_VMIN + (DAC_VMAX - DAC_VMIN) * (code / 4095)
        self.volt_label.setText(f"{v:.3f} V")

    def set_enabled(self, enabled: bool):
        self.apply_btn.setEnabled(enabled)
        self.stop_btn.setEnabled(enabled)


# ─────────────────────── Connection Bar ──────────────────────────────

class ConnectionBar(QWidget):
    connect_clicked    = Signal(str, int)
    disconnect_clicked = Signal()
    refresh_clicked    = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)

        row.addWidget(QLabel("Port"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(180)
        row.addWidget(self.port_combo)

        row.addWidget(QLabel("Baud"))
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["115200", "57600", "9600"])
        row.addWidget(self.baud_combo)

        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setFixedWidth(36)
        self.refresh_btn.clicked.connect(self.refresh_clicked)
        row.addWidget(self.refresh_btn)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("accent")
        self.connect_btn.clicked.connect(self._connect)
        row.addWidget(self.connect_btn)

        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.setObjectName("danger")
        self.disconnect_btn.setEnabled(False)
        self.disconnect_btn.clicked.connect(self.disconnect_clicked)
        row.addWidget(self.disconnect_btn)

        self.ping_btn = QPushButton("Ping")
        self.ping_btn.setEnabled(False)
        row.addWidget(self.ping_btn)

        self.status_label = QLabel("● Disconnected")
        self.status_label.setObjectName("status_err")
        row.addWidget(self.status_label)

        row.addStretch()
        self.refresh_ports()

    def refresh_ports(self):
        self.port_combo.clear()
        ports = [p.device for p in serial.tools.list_ports.comports()]
        if ports:
            self.port_combo.addItems(ports)
        else:
            self.port_combo.addItem("(no ports)")

    def _connect(self):
        port = self.port_combo.currentText()
        baud = int(self.baud_combo.currentText())
        self.connect_clicked.emit(port, baud)

    def set_connected(self, connected: bool):
        self.connect_btn.setEnabled(not connected)
        self.disconnect_btn.setEnabled(connected)
        self.ping_btn.setEnabled(connected)
        if connected:
            self.status_label.setText("● Connected")
            self.status_label.setObjectName("status_ok")
        else:
            self.status_label.setText("● Disconnected")
            self.status_label.setObjectName("status_err")
        # Force style refresh
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)


# ─────────────────── Quick Actions Bar ───────────────────────────────

class QuickBar(QWidget):
    command_ready = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)

        row.addWidget(QLabel("Quick:"))

        zero_btn = QPushButton("Zero All")
        zero_btn.setObjectName("danger")
        zero_btn.clicked.connect(lambda: self.command_ready.emit("ZERO"))
        row.addWidget(zero_btn)

        mid_btn = QPushButton("Mid All")
        mid_btn.clicked.connect(lambda: self.command_ready.emit("MID"))
        row.addWidget(mid_btn)

        stop_btn = QPushButton("Stop Waves")
        stop_btn.clicked.connect(lambda: self.command_ready.emit("STOP"))
        row.addWidget(stop_btn)

        status_btn = QPushButton("Status")
        status_btn.clicked.connect(lambda: self.command_ready.emit("STATUS"))
        row.addWidget(status_btn)

        row.addSpacing(20)
        row.addWidget(QLabel("GEN2 Both →"))

        self.shape0 = QComboBox()
        self.shape0.addItems([s.capitalize() for s in SHAPES])
        row.addWidget(self.shape0)

        self.freq0 = QDoubleSpinBox()
        self.freq0.setRange(0.01, 100)
        self.freq0.setValue(1.0)
        self.freq0.setSuffix(" Hz")
        row.addWidget(self.freq0)

        self.shape1 = QComboBox()
        self.shape1.addItems([s.capitalize() for s in SHAPES])
        self.shape1.setCurrentIndex(1)
        row.addWidget(self.shape1)

        self.freq1 = QDoubleSpinBox()
        self.freq1.setRange(0.01, 100)
        self.freq1.setValue(2.0)
        self.freq1.setSuffix(" Hz")
        row.addWidget(self.freq1)

        gen2_btn = QPushButton("▶ GEN2")
        gen2_btn.setObjectName("accent")
        gen2_btn.clicked.connect(self._gen2)
        row.addWidget(gen2_btn)

        row.addStretch()

    def _gen2(self):
        s0 = self.shape0.currentText().lower()
        f0 = self.freq0.value()
        s1 = self.shape1.currentText().lower()
        f1 = self.freq1.value()
        cmd = f"GEN2 {s0} {f0:.4f} 1.0 1.65 0 {s1} {f1:.4f} 1.0 1.65 0"
        self.command_ready.emit(cmd)


# ─────────────────────── Console Panel ───────────────────────────────

class ConsolePanel(QWidget):
    command_ready = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setSpacing(6)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(220)
        v.addWidget(self.log)

        cmd_row = QHBoxLayout()
        self.cmd_input = QLineEdit()
        self.cmd_input.setPlaceholderText("Type command and press Enter…")
        self.cmd_input.returnPressed.connect(self._send_manual)
        cmd_row.addWidget(self.cmd_input)

        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self._send_manual)
        cmd_row.addWidget(send_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.log.clear)
        cmd_row.addWidget(clear_btn)

        v.addLayout(cmd_row)

    def _send_manual(self):
        text = self.cmd_input.text().strip()
        if text:
            self.append_log(f"→ {text}", ACCENT_CYAN)
            self.command_ready.emit(text)
            self.cmd_input.clear()

    def append_log(self, text: str, color: str = TEXT_MAIN):
        self.log.setTextColor(QColor(color))
        self.log.append(text)
        self.log.setTextColor(QColor(TEXT_MAIN))
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())


# ─────────────────────── Main Window ─────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Arduino Due  ·  DAC Signal Generator")
        self.setMinimumSize(1100, 700)

        self.worker = SerialWorker()
        self.worker.received.connect(self._on_received)
        self.worker.connected.connect(self._on_connected)
        self.worker.disconnected.connect(self._on_disconnected)
        self.worker.error.connect(self._on_error)

        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main = QVBoxLayout(central)
        main.setSpacing(10)
        main.setContentsMargins(14, 14, 14, 10)

        # ── Header ──────────────────────────────────────────
        hdr = QHBoxLayout()
        title_block = QVBoxLayout()
        title = QLabel("DAC CONTROLLER")
        title.setObjectName("title")
        subtitle = QLabel("Arduino Due  ·  12-bit  ·  Dual Channel")
        subtitle.setObjectName("subtitle")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        hdr.addLayout(title_block)
        hdr.addStretch()
        main.addLayout(hdr)

        # ── Connection bar ───────────────────────────────────
        self.conn_bar = ConnectionBar()
        self.conn_bar.connect_clicked.connect(self._connect)
        self.conn_bar.disconnect_clicked.connect(self._disconnect)
        self.conn_bar.refresh_clicked.connect(self.conn_bar.refresh_ports)
        self.conn_bar.ping_btn.clicked.connect(lambda: self._send("PING"))
        main.addWidget(self.conn_bar)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("sep")
        main.addWidget(sep)

        # ── Quick bar ────────────────────────────────────────
        self.quick_bar = QuickBar()
        self.quick_bar.command_ready.connect(self._send)
        main.addWidget(self.quick_bar)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setObjectName("sep")
        main.addWidget(sep2)

        # ── Channel panels ───────────────────────────────────
        channels_row = QHBoxLayout()
        self.ch0 = ChannelPanel(0, ACCENT_CYAN)
        self.ch0.command_ready.connect(self._send)
        self.ch1 = ChannelPanel(1, ACCENT_GREEN)
        self.ch1.command_ready.connect(self._send)
        channels_row.addWidget(self.ch0)
        channels_row.addWidget(self.ch1)
        main.addLayout(channels_row)

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.HLine)
        sep3.setObjectName("sep")
        main.addWidget(sep3)

        # ── Console ──────────────────────────────────────────
        console_box = QGroupBox("Console  ·  Serial Log")
        cb_layout = QVBoxLayout(console_box)
        self.console = ConsolePanel()
        self.console.command_ready.connect(self._send)
        cb_layout.addWidget(self.console)
        main.addWidget(console_box)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Not connected  ·  Select a COM port and click Connect")

        self._set_controls_enabled(False)

    # ── Connection ──────────────────────────────────────────

    def _connect(self, port: str, baud: int):
        self.console.append_log(f"→ Connecting to {port} @ {baud}…", ACCENT_AMBER)
        self.worker.open(port, baud)

    def _disconnect(self):
        self.worker.close()

    @Slot()
    def _on_connected(self):
        self.conn_bar.set_connected(True)
        self.status_bar.showMessage("Connected  ·  Sending PING…")
        self.console.append_log("● Connected", ACCENT_GREEN)
        self._set_controls_enabled(True)
        QTimer.singleShot(200, lambda: self._send("PING"))

    @Slot()
    def _on_disconnected(self):
        self.conn_bar.set_connected(False)
        self.status_bar.showMessage("Disconnected")
        self.console.append_log("● Disconnected", ACCENT_RED)
        self._set_controls_enabled(False)

    @Slot(str)
    def _on_error(self, msg: str):
        self.console.append_log(f"✖ Error: {msg}", ACCENT_RED)
        self.status_bar.showMessage(f"Error: {msg}")

    # ── Send / Receive ──────────────────────────────────────

    def _send(self, cmd: str):
        if self.worker.is_open:
            self.worker.send(cmd)
            self.console.append_log(f"→ {cmd}", ACCENT_CYAN)
        else:
            self.console.append_log("✖ Not connected", ACCENT_RED)

    @Slot(str)
    def _on_received(self, line: str):
        self.console.append_log(f"← {line}", TEXT_MAIN)
        try:
            data = json.loads(line)
            t = data.get("type", "")

            if t == "pong":
                self.status_bar.showMessage(
                    f"Connected  ·  {data.get('board','?')}  ·  "
                    f"{data.get('dac_bits','?')}-bit DAC  ·  "
                    f"{data.get('dac_vmin','?')}…{data.get('dac_vmax','?')} V"
                )

            elif t == "status":
                self.ch0.update_voltage(data.get("dac0_code", 0))
                self.ch1.update_voltage(data.get("dac1_code", 0))

            elif t == "set":
                self.ch0.update_voltage(data.get("dac0", 0))
                self.ch1.update_voltage(data.get("dac1", 0))

            elif t == "wave":
                ch = data.get("channel", {})
                dac = ch.get("dac", -1)
                code = ch.get("low_code", 0)
                if dac == 0:
                    self.ch0.update_voltage(code)
                elif dac == 1:
                    self.ch1.update_voltage(code)

            elif t == "error":
                self.status_bar.showMessage(f"Arduino error: {data.get('message','?')}")

        except json.JSONDecodeError:
            pass  # raw non-JSON line, already shown in console

    # ── Helpers ─────────────────────────────────────────────

    def _set_controls_enabled(self, enabled: bool):
        self.ch0.set_enabled(enabled)
        self.ch1.set_enabled(enabled)

    def closeEvent(self, event):
        self.worker.close()
        super().closeEvent(event)


# ─────────────────────── Entry Point ─────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()