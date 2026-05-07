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

import numpy as np
import serial
import serial.tools.list_ports

from PySide6.QtCore import (
    Qt, QTimer, Signal, QObject, QThread, Slot
)
from PySide6.QtGui import (
    QColor, QFont, QPalette, QFontDatabase
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QDoubleSpinBox, QSpinBox, QPushButton,
    QComboBox, QGroupBox, QStatusBar, QFrame, QSizePolicy,
    QSplitter, QSlider, QCheckBox
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt

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
QPushButton#start_btn {{
    background-color: #163a20;
    border-color: {COLORS['green']};
    color: {COLORS['green']};
}}
QPushButton#start_btn:hover {{
    background-color: #1e4d29;
}}
QPushButton#stop_btn {{
    background-color: #3a1616;
    border-color: {COLORS['red']};
    color: {COLORS['red']};
}}
QPushButton#stop_btn:hover {{
    background-color: #4d1e1e;
}}
QPushButton#connect_btn {{
    background-color: #162a3a;
    border-color: {COLORS['accent']};
    color: {COLORS['accent']};
}}
QLabel#section_label {{
    color: {COLORS['accent']};
    font-size: 10px;
    letter-spacing: 2px;
    font-weight: bold;
}}
QLabel#value_label {{
    color: {COLORS['text']};
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
}}
QStatusBar {{
    background-color: {COLORS['surface']};
    border-top: 1px solid {COLORS['border']};
    color: {COLORS['text_dim']};
    font-size: 11px;
}}
QSplitter::handle {{
    background-color: {COLORS['border']};
}}
QFrame#divider {{
    background-color: {COLORS['border']};
    max-height: 1px;
}}
"""

# ── Serial worker (runs in its own thread) ────────────────────────────────────
class SerialWorker(QObject):
    message_received = Signal(str)
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
                time.sleep(2)   # wait for Due to reboot after DTR
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
        """Send a command and return the first response line (blocking, ≤300 ms)."""
        with self._lock:
            if not self._port or not self._port.is_open:
                return None
            try:
                self._port.write((cmd.strip() + "\n").encode())
                deadline = time.time() + 0.3
                while time.time() < deadline:
                    line = self._port.readline().decode(errors="replace").strip()
                    if line:
                        return line
                return None
            except Exception as e:
                self.error_occurred.emit(str(e))
                return None

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._port is not None and self._port.is_open


# ── Preview canvas ─────────────────────────────────────────────────────────────
class WaveformCanvas(FigureCanvas):
    def __init__(self):
        self.fig = Figure(figsize=(6, 3), facecolor=COLORS["bg"])
        super().__init__(self.fig)
        self.ax = self.fig.add_subplot(111)
        self._style_axes()
        self.setMinimumHeight(200)

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
        ax.axhline(0,   color=COLORS["border"], linewidth=0.5, linestyle="--")
        ax.axhline(3.3, color=COLORS["red"],    linewidth=0.5, linestyle="--", alpha=0.6)
        self.fig.tight_layout(pad=1.2)

    def update_plot(self, a1, f1, p1_deg, a2, f2, p2_deg, dc, sr):
        self.ax.cla()
        self._style_axes()

        # Show at least 2 cycles of the slower frequency, capped to 50 ms
        f_min = min(f1, f2) if min(f1, f2) > 0 else max(f1, f2)
        duration = min(2.0 / f_min if f_min > 0 else 0.05, 0.05)
        t = np.linspace(0, duration, max(int(sr * duration), 1000))

        p1 = np.radians(p1_deg)
        p2 = np.radians(p2_deg)

        s1 = a1 * np.sin(2 * np.pi * f1 * t + p1)
        s2 = a2 * np.sin(2 * np.pi * f2 * t + p2)
        combined = np.clip(dc + s1 + s2, 0, 3.3)

        t_ms = t * 1000

        self.ax.plot(t_ms, dc + s1,    color=COLORS["sine1"],    lw=1.0,
                     alpha=0.6, label="Sine 1")
        self.ax.plot(t_ms, dc + s2,    color=COLORS["sine2"],    lw=1.0,
                     alpha=0.6, label="Sine 2")
        self.ax.plot(t_ms, combined,   color=COLORS["combined"], lw=1.5,
                     label="Combined")
        self.ax.axhline(3.3, color=COLORS["red"], lw=0.5, ls="--", alpha=0.5)
        self.ax.axhline(0,   color=COLORS["border"], lw=0.5, ls="--")
        self.ax.legend(loc="upper right", fontsize=7,
                       facecolor=COLORS["surface"], edgecolor=COLORS["border"],
                       labelcolor=COLORS["text"])
        self.ax.set_xlabel("time (ms)", fontsize=8)
        self.ax.set_ylabel("Voltage (V)", fontsize=8)

        peak = float(np.max(combined))
        trough = float(np.min(combined))
        self.ax.set_title(
            f"peak {peak:.3f} V  |  trough {trough:.3f} V",
            fontsize=8, color=COLORS["text_dim"]
        )
        self.fig.tight_layout(pad=1.2)
        self.draw()


# ── Parameter row helper ───────────────────────────────────────────────────────
def make_spinbox(min_val, max_val, decimals, step, value, suffix="") -> QDoubleSpinBox:
    sb = QDoubleSpinBox()
    sb.setRange(min_val, max_val)
    sb.setDecimals(decimals)
    sb.setSingleStep(step)
    sb.setValue(value)
    if suffix:
        sb.setSuffix(f"  {suffix}")
    return sb


# ── Main window ────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dual-Sine DAC Controller  //  Arduino Due")
        self.resize(1000, 680)
        self.serial = SerialWorker()
        self.serial.error_occurred.connect(self._on_serial_error)
        self.serial.connected.connect(self._on_connected)
        self._running = False
        self._build_ui()

        # Preview auto-refresh
        self._preview_timer = QTimer(self)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self._preview_timer.start(250)   # 4 fps is plenty for preview

    # ── UI construction ───────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # Left panel: controls
        left = QVBoxLayout()
        left.setSpacing(10)

        left.addWidget(self._build_connection_box())
        left.addWidget(self._build_sine_box("SINE  1", "1", COLORS["sine1"]))
        left.addWidget(self._build_sine_box("SINE  2", "2", COLORS["sine2"]))
        left.addWidget(self._build_global_box())
        left.addWidget(self._build_transport_box())
        left.addStretch()

        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setFixedWidth(360)

        # Right panel: preview
        right = QVBoxLayout()
        right.setSpacing(8)

        preview_label = QLabel("WAVEFORM  PREVIEW")
        preview_label.setObjectName("section_label")
        right.addWidget(preview_label)

        self.canvas = WaveformCanvas()
        right.addWidget(self.canvas, 1)

        self._build_stats_panel(right)

        right_widget = QWidget()
        right_widget.setLayout(right)

        root.addWidget(left_widget)
        root.addWidget(right_widget, 1)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Disconnected")

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

        def row(label, widget, unit=""):
            r = grid.rowCount()
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
            grid.addWidget(lbl, r, 0)
            grid.addWidget(widget, r, 1)
            if unit:
                u = QLabel(unit)
                u.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 10px;")
                grid.addWidget(u, r, 2)

        if idx == "1":
            self.amp1  = make_spinbox(0, 1.65, 3, 0.05,  0.5,  "V")
            self.freq1 = make_spinbox(0, 5000, 2, 10.0,  100.0, "Hz")
            self.phase1 = make_spinbox(-360, 360, 1, 5.0, 0.0,  "°")
            for ctrl in (self.amp1, self.freq1, self.phase1):
                ctrl.valueChanged.connect(self._param_changed)
            row("Amplitude", self.amp1)
            row("Frequency", self.freq1)
            row("Phase",     self.phase1)
        else:
            self.amp2  = make_spinbox(0, 1.65, 3, 0.05,  0.5,   "V")
            self.freq2 = make_spinbox(0, 5000, 2, 10.0,  200.0, "Hz")
            self.phase2 = make_spinbox(-360, 360, 1, 5.0, 0.0,  "°")
            for ctrl in (self.amp2, self.freq2, self.phase2):
                ctrl.valueChanged.connect(self._param_changed)
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
            lbl.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
            grid.addWidget(lbl, r, 0)
            grid.addWidget(widget, r, 1)

        self.dc_offset = make_spinbox(0, 3.3, 3, 0.05, 1.65, "V")
        self.sample_rate = QSpinBox()
        self.sample_rate.setRange(100, 100000)
        self.sample_rate.setValue(10000)
        self.sample_rate.setSuffix("  Hz")
        self.sample_rate.setSingleStep(1000)

        for ctrl in (self.dc_offset, self.sample_rate):
            ctrl.valueChanged.connect(self._param_changed)

        row("DC Offset",   self.dc_offset)
        row("Sample Rate", self.sample_rate)

        # Clipping warning
        self.clip_label = QLabel("")
        self.clip_label.setStyleSheet(f"color: {COLORS['red']}; font-size: 10px;")
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
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
            }}
        """)
        grid = QGridLayout(frame)
        grid.setContentsMargins(12, 8, 12, 8)
        grid.setHorizontalSpacing(24)

        def stat(label, attr, col):
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 10px; letter-spacing: 1px;")
            val = QLabel("—")
            val.setStyleSheet(f"color: {COLORS['text']}; font-family: 'JetBrains Mono'; font-size: 12px;")
            setattr(self, attr, val)
            grid.addWidget(lbl, 0, col)
            grid.addWidget(val, 1, col)

        stat("PEAK",    "stat_peak",    0)
        stat("TROUGH",  "stat_trough",  1)
        stat("VRANGE",  "stat_range",   2)
        stat("NYQUIST", "stat_nyquist", 3)

        layout.addWidget(frame)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _refresh_ports(self):
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for p in ports:
            self.port_combo.addItem(p.device)
        if not ports:
            self.port_combo.addItem("(no ports found)")

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
        }

    def _check_clipping(self, p: dict) -> str:
        worst_case = p["dc"] + p["a1"] + p["a2"]
        worst_low  = p["dc"] - p["a1"] - p["a2"]
        warnings = []
        if worst_case > 3.3:
            warnings.append(f"⚠ peak may clip (+{worst_case - 3.3:.3f} V clamped)")
        if worst_low < 0:
            warnings.append(f"⚠ trough may clip ({worst_low:.3f} V clamped)")
        return "  ".join(warnings)

    def _refresh_preview(self):
        p = self._get_params()
        warn = self._check_clipping(p)
        self.clip_label.setText(warn)
        self.canvas.update_plot(
            a1=p["a1"], f1=p["f1"], p1_deg=p["p1"],
            a2=p["a2"], f2=p["f2"], p2_deg=p["p2"],
            dc=p["dc"], sr=p["sr"],
        )

        # Update stats
        t = np.linspace(0, 0.1, 50000)
        s = np.clip(
            p["dc"]
            + p["a1"] * np.sin(2 * np.pi * p["f1"] * t + np.radians(p["p1"]))
            + p["a2"] * np.sin(2 * np.pi * p["f2"] * t + np.radians(p["p2"])),
            0, 3.3
        )
        self.stat_peak.setText(f"{np.max(s):.3f} V")
        self.stat_trough.setText(f"{np.min(s):.3f} V")
        self.stat_range.setText(f"{np.max(s) - np.min(s):.3f} V")
        nyq = p["sr"] / 2
        self.stat_nyquist.setText(f"{nyq:.0f} Hz")

    # ── Serial actions ────────────────────────────────────────────────────────
    def _toggle_connect(self):
        if self.serial.is_open:
            self._stop()
            self.serial.close()
        else:
            port = self.port_combo.currentText()
            if port and "no ports" not in port:
                self.status_bar.showMessage(f"Connecting to {port} …")
                ok = self.serial.open(port)
                if ok:
                    self.status_bar.showMessage(f"Connected  ·  {port}  @  115200 baud")

    def _param_changed(self):
        # Visual feedback — user must press APPLY to send
        pass

    def _send(self, cmd: str):
        resp = self.serial.send(cmd)
        if resp:
            self.status_bar.showMessage(f"← {resp}")
        return resp

    def _apply_all(self):
        if not self.serial.is_open:
            return
        p = self._get_params()
        cmds = [
            f"SET A1 {p['a1']:.4f}",
            f"SET F1 {p['f1']:.4f}",
            f"SET P1 {p['p1']:.2f}",
            f"SET A2 {p['a2']:.4f}",
            f"SET F2 {p['f2']:.4f}",
            f"SET P2 {p['p2']:.2f}",
            f"SET DC {p['dc']:.4f}",
            f"SET SR {int(p['sr'])}",
        ]
        for cmd in cmds:
            self._send(cmd)
        self.status_bar.showMessage("Parameters applied.")

    def _start(self):
        self._apply_all()
        resp = self._send("START")
        if resp and "OK" in resp:
            self._running = True
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.status_bar.showMessage("▶ Running")

    def _stop(self):
        resp = self._send("STOP")
        self._running = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_bar.showMessage("■ Stopped")

    # ── Slots ─────────────────────────────────────────────────────────────────
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

    def closeEvent(self, event):
        self._stop()
        self.serial.close()
        super().closeEvent(event)


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Dark palette baseline so native widgets inherit it
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