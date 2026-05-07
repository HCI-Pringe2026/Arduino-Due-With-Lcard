#!/usr/bin/env python3
"""PySide GUI for Arduino Due beatless sum-of-two-sines DAC0 generator."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass
from typing import Sequence

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


DAC_VMIN = 0.55
DAC_VMAX = 2.75
DEFAULT_OFFSET = 1.65
EMU_PORT = "EMU"


@dataclass(frozen=True)
class GeneratorParams:
    f1_hz: float
    a1: float
    phase1_deg: float
    f2_hz: float
    a2: float
    phase2_deg: float
    output_vpp: float
    offset_v: float
    epsilon: float


class SerialError(RuntimeError):
    pass


def voltage_to_code(voltage: float) -> int:
    clipped = max(DAC_VMIN, min(DAC_VMAX, voltage))
    return round((clipped - DAC_VMIN) / (DAC_VMAX - DAC_VMIN) * 4095.0)


def code_to_voltage(code: int) -> float:
    return DAC_VMIN + (DAC_VMAX - DAC_VMIN) * (max(0, min(4095, code)) / 4095.0)


def validate_params(params: GeneratorParams) -> None:
    if not (0.0 <= params.f1_hz <= 100.0 and 0.0 <= params.f2_hz <= 100.0):
        raise ValueError("Частоты должны быть в диапазоне 0..100 Гц")
    if params.a1 < 0.0 or params.a2 < 0.0 or params.a1 + params.a2 <= 0.0:
        raise ValueError("Хотя бы одна относительная амплитуда синуса должна быть больше нуля")
    if not (0.001 <= params.epsilon <= 1.0):
        raise ValueError("Epsilon должен быть в диапазоне 0.001..1.0")
    low = params.offset_v - params.output_vpp * 0.5
    high = params.offset_v + params.output_vpp * 0.5
    if low < DAC_VMIN or high > DAC_VMAX:
        raise ValueError(f"Выход выходит за диапазон DAC0: {low:.3f}..{high:.3f} В")


class SerialClient:
    def __init__(self) -> None:
        self.serial = None

    @staticmethod
    def list_ports() -> list[str]:
        try:
            from serial.tools import list_ports
        except ImportError as exc:
            raise SerialError("PySerial не установлен. Выполните: py -m pip install -r requirements.txt") from exc
        return [str(port.device) for port in list_ports.comports()]

    def connect(self, port: str, baud: int = 115200) -> dict:
        try:
            import serial
        except ImportError as exc:
            raise SerialError("PySerial не установлен. Выполните: py -m pip install -r requirements.txt") from exc

        self.close()
        ser = serial.Serial()
        ser.port = port
        ser.baudrate = baud
        ser.timeout = 0.25
        ser.write_timeout = 2.0
        ser.dtr = False
        ser.rts = False
        ser.open()
        ser.setDTR(False)
        ser.setRTS(False)
        self.serial = ser

        time.sleep(2.0)
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        return self.command("PING")

    def close(self) -> None:
        if self.serial is not None:
            self.serial.close()
            self.serial = None

    def is_connected(self) -> bool:
        return self.serial is not None and self.serial.is_open

    def command(self, text: str, timeout_s: float = 3.0) -> dict:
        if not self.is_connected():
            raise SerialError("Arduino не подключена")

        assert self.serial is not None
        deadline = time.monotonic() + timeout_s
        self.serial.write((text.strip() + "\n").encode("ascii"))

        last_line = ""
        while time.monotonic() < deadline:
            raw = self.serial.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            last_line = line
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("type") == "error":
                raise SerialError(str(payload.get("message", "Arduino вернула ошибку")))
            return payload
        raise SerialError(f"Нет ответа от Arduino. Последняя строка: {last_line!r}")


class EmulatorClient:
    def __init__(self) -> None:
        self.connected = False
        self.running = False
        self.params = GeneratorParams(10.1, 1.0, 0.0, 10.6, 1.0, 0.0, 1.8, DEFAULT_OFFSET, 0.02)
        self.start_time = time.monotonic()
        self.current_code = voltage_to_code(DEFAULT_OFFSET)

    def connect(self, port: str, baud: int = 115200) -> dict:
        del baud
        if port != EMU_PORT:
            raise SerialError(f"Эмулятор подключается только к порту {EMU_PORT}")
        self.connected = True
        return self.command("PING")

    def close(self) -> None:
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected

    def command(self, text: str, timeout_s: float = 3.0) -> dict:
        del timeout_s
        if not self.connected:
            raise SerialError("Эмулятор не подключен")

        parts = text.strip().split()
        if not parts:
            raise SerialError("Пустая команда")

        command = parts[0].upper()
        if command == "PING":
            return {
                "type": "pong",
                "board": "Arduino Due Emulator",
                "mode": "sum_sine_beatless",
                "dac": "DAC0",
                "dac_vmin": DAC_VMIN,
                "dac_vmax": DAC_VMAX,
                "emulated": True,
            }
        if command == "CONFIG":
            self.params = self.parse_config(parts[1:])
            self.start_time = time.monotonic()
            self.current_code = voltage_to_code(self.params.offset_v)
            return self.status_payload("configured")
        if command == "START":
            self.running = True
            self.start_time = time.monotonic()
            return self.status_payload("started")
        if command == "STOP":
            self.running = False
            self.current_code = voltage_to_code(self.params.offset_v)
            return self.status_payload("stopped")
        if command == "STATUS":
            return self.status_payload("status")

        raise SerialError(f"Неизвестная команда эмулятора: {parts[0]}")

    def parse_config(self, args: list[str]) -> GeneratorParams:
        if len(args) != 9:
            raise SerialError("CONFIG ожидает 9 аргументов")
        try:
            params = GeneratorParams(
                f1_hz=float(args[0]),
                a1=float(args[1]),
                phase1_deg=float(args[2]),
                f2_hz=float(args[3]),
                a2=float(args[4]),
                phase2_deg=float(args[5]),
                output_vpp=float(args[6]),
                offset_v=float(args[7]),
                epsilon=float(args[8]),
            )
            validate_params(params)
            return params
        except ValueError as exc:
            raise SerialError(str(exc)) from exc

    def status_payload(self, payload_type: str) -> dict:
        if self.running:
            elapsed = time.monotonic() - self.start_time
            self.current_code = voltage_to_code(corrected_value(self.params, elapsed))
        voltage = code_to_voltage(self.current_code)
        return {
            "type": payload_type,
            "running": self.running,
            "dac": "DAC0",
            "dac_code": self.current_code,
            "dac_voltage_v": round(voltage, 6),
            "f1_hz": self.params.f1_hz,
            "a1": self.params.a1,
            "phase1_deg": self.params.phase1_deg,
            "f2_hz": self.params.f2_hz,
            "a2": self.params.a2,
            "phase2_deg": self.params.phase2_deg,
            "output_vpp": self.params.output_vpp,
            "offset_v": self.params.offset_v,
            "epsilon": self.params.epsilon,
            "emulated": True,
        }


def corrected_value(params: GeneratorParams, t: float) -> float:
    theta1 = 2.0 * math.pi * params.f1_hz * t + math.radians(params.phase1_deg)
    theta2 = 2.0 * math.pi * params.f2_hz * t + math.radians(params.phase2_deg)
    raw = params.a1 * math.sin(theta1) + params.a2 * math.sin(theta2)
    envelope_sq = params.a1 * params.a1 + params.a2 * params.a2 + 2.0 * params.a1 * params.a2 * math.cos(theta2 - theta1)
    envelope = math.sqrt(max(0.0, envelope_sq))
    normalized = raw / max(envelope, params.epsilon)
    normalized = max(-1.0, min(1.0, normalized))
    return params.offset_v + params.output_vpp * 0.5 * normalized


def raw_value(params: GeneratorParams, t: float) -> float:
    theta1 = 2.0 * math.pi * params.f1_hz * t + math.radians(params.phase1_deg)
    theta2 = 2.0 * math.pi * params.f2_hz * t + math.radians(params.phase2_deg)
    raw = params.a1 * math.sin(theta1) + params.a2 * math.sin(theta2)
    scale = max(params.a1 + params.a2, 1e-9)
    return params.offset_v + params.output_vpp * 0.5 * raw / scale


class WavePreview(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.params = GeneratorParams(10.1, 1.0, 0.0, 10.6, 1.0, 0.0, 1.8, DEFAULT_OFFSET, 0.02)
        self.seconds = 2.0
        self.setMinimumHeight(280)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_params(self, params: GeneratorParams, seconds: float) -> None:
        self.params = params
        self.seconds = max(0.05, seconds)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(12, 12, -12, -12)
        painter.fillRect(self.rect(), QColor(18, 22, 28))

        grid_pen = QPen(QColor(55, 64, 76), 1)
        painter.setPen(grid_pen)
        for i in range(6):
            y = rect.top() + i * rect.height() / 5.0
            painter.drawLine(rect.left(), int(y), rect.right(), int(y))
        for i in range(11):
            x = rect.left() + i * rect.width() / 10.0
            painter.drawLine(int(x), rect.top(), int(x), rect.bottom())

        def map_point(index: int, value: float, count: int) -> tuple[int, int]:
            x = rect.left() + index * rect.width() / max(1, count - 1)
            normalized = (value - DAC_VMIN) / (DAC_VMAX - DAC_VMIN)
            y = rect.bottom() - normalized * rect.height()
            return int(x), int(y)

        count = max(300, min(2400, int(self.seconds * 900)))
        raw_points = [map_point(i, raw_value(self.params, i * self.seconds / (count - 1)), count) for i in range(count)]
        corrected_points = [map_point(i, corrected_value(self.params, i * self.seconds / (count - 1)), count) for i in range(count)]

        painter.setPen(QPen(QColor(140, 92, 92), 1))
        for p0, p1 in zip(raw_points, raw_points[1:]):
            painter.drawLine(*p0, *p1)

        painter.setPen(QPen(QColor(80, 180, 255), 2))
        for p0, p1 in zip(corrected_points, corrected_points[1:]):
            painter.drawLine(*p0, *p1)

        painter.setPen(QPen(QColor(210, 215, 222), 1))
        painter.drawText(rect.left(), rect.top() - 2, f"{DAC_VMAX:.2f} V")
        painter.drawText(rect.left(), rect.bottom() + 14, f"{DAC_VMIN:.2f} V")
        painter.drawText(rect.right() - 150, rect.top() - 2, "blue: corrected, red: raw")


class MainWindow(QMainWindow):
    def __init__(self, start_emulator: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("Arduino Due DAC0: sum of two sines without beats")
        self.serial: SerialClient | EmulatorClient = SerialClient()
        self.start_emulator = start_emulator

        self.port_combo = QComboBox()
        self.refresh_button = QPushButton("Обновить")
        self.connect_button = QPushButton("Подключить")
        self.disconnect_button = QPushButton("Отключить")
        self.connection_label = QLabel("Не подключено")

        self.f1 = self.double_box(0.0, 100.0, 10.1, 0.1, 4)
        self.a1 = self.double_box(0.0, 10.0, 1.0, 0.1, 4)
        self.p1 = self.double_box(-3600.0, 3600.0, 0.0, 5.0, 2)
        self.f2 = self.double_box(0.0, 100.0, 10.6, 0.1, 4)
        self.a2 = self.double_box(0.0, 10.0, 1.0, 0.1, 4)
        self.p2 = self.double_box(-3600.0, 3600.0, 0.0, 5.0, 2)
        self.output_vpp = self.double_box(0.0, DAC_VMAX - DAC_VMIN, 1.8, 0.05, 4)
        self.offset_v = self.double_box(DAC_VMIN, DAC_VMAX, DEFAULT_OFFSET, 0.01, 4)
        self.epsilon = self.double_box(0.001, 1.0, 0.02, 0.005, 4)
        self.preview_seconds = self.double_box(0.1, 30.0, 4.0, 0.5, 2)

        self.apply_button = QPushButton("Отправить параметры")
        self.start_button = QPushButton("Старт")
        self.apply_start_button = QPushButton("Отправить и старт")
        self.stop_button = QPushButton("Стоп")
        self.status_button = QPushButton("Статус")
        self.auto_preview = QCheckBox("Автообновление графика")
        self.auto_preview.setChecked(True)

        self.preview = WavePreview()
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)

        self.build_layout()
        self.bind_events()
        self.refresh_ports()
        if self.start_emulator:
            index = self.port_combo.findText(EMU_PORT)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
            QTimer.singleShot(0, self.connect_serial)
        self.update_preview()

        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(150)
        self.preview_timer.timeout.connect(self.update_preview)
        self.preview_timer.start()

    @staticmethod
    def double_box(low: float, high: float, value: float, step: float, decimals: int) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(low, high)
        box.setValue(value)
        box.setSingleStep(step)
        box.setDecimals(decimals)
        box.setKeyboardTracking(False)
        return box

    def build_layout(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        main = QGridLayout(root)

        connection = QGroupBox("Подключение")
        connection_layout = QGridLayout(connection)
        connection_layout.addWidget(QLabel("COM-порт"), 0, 0)
        connection_layout.addWidget(self.port_combo, 0, 1)
        connection_layout.addWidget(self.refresh_button, 0, 2)
        connection_layout.addWidget(self.connect_button, 1, 0)
        connection_layout.addWidget(self.disconnect_button, 1, 1)
        connection_layout.addWidget(self.connection_label, 1, 2)

        sine1 = QGroupBox("Синус 1")
        sine1_layout = QFormLayout(sine1)
        sine1_layout.addRow("Частота, Гц", self.f1)
        sine1_layout.addRow("Амплитуда, отн.", self.a1)
        sine1_layout.addRow("Фаза, град", self.p1)

        sine2 = QGroupBox("Синус 2")
        sine2_layout = QFormLayout(sine2)
        sine2_layout.addRow("Частота, Гц", self.f2)
        sine2_layout.addRow("Амплитуда, отн.", self.a2)
        sine2_layout.addRow("Фаза, град", self.p2)

        output = QGroupBox("Выход DAC0")
        output_layout = QFormLayout(output)
        output_layout.addRow("Амплитуда, Vpp", self.output_vpp)
        output_layout.addRow("Смещение, В", self.offset_v)
        output_layout.addRow("Epsilon", self.epsilon)
        output_layout.addRow("Окно графика, с", self.preview_seconds)
        output_layout.addRow(self.auto_preview)

        buttons = QHBoxLayout()
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.apply_start_button)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(self.status_button)

        left = QVBoxLayout()
        left.addWidget(connection)
        left.addWidget(sine1)
        left.addWidget(sine2)
        left.addWidget(output)
        left.addLayout(buttons)
        left.addStretch(1)

        main.addLayout(left, 0, 0)
        main.addWidget(self.preview, 0, 1)
        main.addWidget(self.log, 1, 0, 1, 2)
        main.setColumnStretch(1, 1)
        main.setRowStretch(0, 1)
        self.resize(1180, 760)

    def bind_events(self) -> None:
        self.refresh_button.clicked.connect(self.refresh_ports)
        self.connect_button.clicked.connect(self.connect_serial)
        self.disconnect_button.clicked.connect(self.disconnect_serial)
        self.apply_button.clicked.connect(self.apply_config)
        self.start_button.clicked.connect(self.start)
        self.apply_start_button.clicked.connect(self.apply_and_start)
        self.stop_button.clicked.connect(self.stop)
        self.status_button.clicked.connect(self.status)

        for box in (self.f1, self.a1, self.p1, self.f2, self.a2, self.p2, self.output_vpp, self.offset_v, self.epsilon, self.preview_seconds):
            box.valueChanged.connect(lambda _value: self.update_preview())

    def refresh_ports(self) -> None:
        current = self.port_combo.currentText()
        self.port_combo.clear()
        ports = [EMU_PORT]
        try:
            ports.extend(SerialClient.list_ports())
        except SerialError as exc:
            self.log.appendPlainText(f"INFO: реальные COM-порты не прочитаны: {exc}")
        self.port_combo.addItems(ports)
        if current:
            index = self.port_combo.findText(current)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)

    def params(self) -> GeneratorParams:
        params = GeneratorParams(
            self.f1.value(),
            self.a1.value(),
            self.p1.value(),
            self.f2.value(),
            self.a2.value(),
            self.p2.value(),
            self.output_vpp.value(),
            self.offset_v.value(),
            self.epsilon.value(),
        )
        low = params.offset_v - params.output_vpp * 0.5
        high = params.offset_v + params.output_vpp * 0.5
        del low, high
        validate_params(params)
        return params

    def config_command(self) -> str:
        p = self.params()
        return (
            f"CONFIG {p.f1_hz:.6f} {p.a1:.6f} {p.phase1_deg:.3f} "
            f"{p.f2_hz:.6f} {p.a2:.6f} {p.phase2_deg:.3f} "
            f"{p.output_vpp:.6f} {p.offset_v:.6f} {p.epsilon:.6f}"
        )

    def update_preview(self) -> None:
        if not self.auto_preview.isChecked():
            return
        try:
            self.preview.set_params(self.params(), self.preview_seconds.value())
        except ValueError:
            return

    def connect_serial(self) -> None:
        port = self.port_combo.currentText().strip()
        if not port:
            self.show_error("COM-порт не выбран")
            return
        try:
            self.serial.close()
            self.serial = EmulatorClient() if port == EMU_PORT else SerialClient()
            response = self.serial.connect(port)
            self.connection_label.setText(f"Подключено: {port}")
            self.log_json(response)
        except SerialError as exc:
            self.show_error(exc)

    def disconnect_serial(self) -> None:
        self.serial.close()
        self.connection_label.setText("Не подключено")

    def apply_config(self) -> None:
        try:
            response = self.serial.command(self.config_command())
            self.log_json(response)
        except (SerialError, ValueError) as exc:
            self.show_error(exc)

    def start(self) -> None:
        try:
            response = self.serial.command("START")
            self.log_json(response)
        except SerialError as exc:
            self.show_error(exc)

    def apply_and_start(self) -> None:
        try:
            self.log_json(self.serial.command(self.config_command()))
            self.log_json(self.serial.command("START"))
        except (SerialError, ValueError) as exc:
            self.show_error(exc)

    def stop(self) -> None:
        try:
            response = self.serial.command("STOP")
            self.log_json(response)
        except SerialError as exc:
            self.show_error(exc)

    def status(self) -> None:
        try:
            response = self.serial.command("STATUS")
            self.log_json(response)
        except SerialError as exc:
            self.show_error(exc)

    def log_json(self, payload: dict) -> None:
        self.log.appendPlainText(json.dumps(payload, ensure_ascii=False))

    def show_error(self, error: object) -> None:
        message = str(error)
        self.log.appendPlainText(f"ERROR: {message}")
        QMessageBox.warning(self, "Ошибка", message)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.serial.close()
        super().closeEvent(event)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emu", action="store_true", help="Запустить GUI сразу подключенным к встроенному эмулятору Arduino")
    args, qt_args = parser.parse_known_args(list(argv if argv is not None else sys.argv[1:]))

    app = QApplication([sys.argv[0], *qt_args])
    window = MainWindow(start_emulator=args.emu)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
