#!/usr/bin/env python3
"""Check Arduino Due DAC0/DAC1 by measuring them with LCard E14-140-M-D."""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_TEST_POINTS = [
    (0, 4095),
    (512, 3072),
    (1024, 2048),
    (2048, 1024),
    (3072, 512),
    (4095, 0),
]


@dataclass(frozen=True)
class Measurement:
    voltages: tuple[float, float]
    raw: tuple[float | None, float | None] = (None, None)


@dataclass(frozen=True)
class ResultRow:
    index: int
    code0: int
    code1: int
    expected0: float
    expected1: float
    measured0: float
    measured1: float
    error0: float
    error1: float


class TestFailure(RuntimeError):
    pass


class ArduinoDue:
    def set_dacs(self, dac0: int, dac1: int) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class SimArduinoDue(ArduinoDue):
    def set_dacs(self, dac0: int, dac1: int) -> None:
        print(f"[sim-arduino] SET {dac0} {dac1}")


class SerialArduinoDue(ArduinoDue):
    def __init__(self, port: str, baud: int, timeout_s: float) -> None:
        try:
            import serial
        except ImportError as exc:
            raise TestFailure("PySerial is not installed. Run: py -m pip install -r requirements.txt") from exc

        self.serial = serial.Serial(port=port, baudrate=baud, timeout=0.2, write_timeout=timeout_s)
        time.sleep(2.0)
        self.serial.reset_input_buffer()
        self.serial.reset_output_buffer()
        self._ping(timeout_s)

    def _ping(self, timeout_s: float) -> None:
        deadline = time.monotonic() + timeout_s
        last_error = ""
        while time.monotonic() < deadline:
            self.serial.write(b"PING\n")
            response = self._read_json_line(deadline)
            if response and response.get("type") == "pong":
                return
            if response and response.get("type") == "error":
                last_error = str(response.get("message", ""))
            time.sleep(0.2)
        raise TestFailure(f"Arduino Due did not answer PING on {self.serial.port!r}. {last_error}".strip())

    def _read_json_line(self, deadline: float) -> dict | None:
        while time.monotonic() < deadline:
            raw = self.serial.readline()
            if not raw:
                continue
            try:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                return json.loads(line)
            except json.JSONDecodeError:
                continue
        return None

    def set_dacs(self, dac0: int, dac1: int) -> None:
        deadline = time.monotonic() + 3.0
        self.serial.write(f"SET {dac0} {dac1}\n".encode("ascii"))
        response = self._read_json_line(deadline)
        if not response:
            raise TestFailure("No response from Arduino after SET command")
        if response.get("type") == "error":
            raise TestFailure(f"Arduino rejected SET command: {response.get('message')}")
        if response.get("type") != "set" or int(response.get("dac0", -1)) != dac0 or int(response.get("dac1", -1)) != dac1:
            raise TestFailure(f"Unexpected Arduino response: {response}")

    def close(self) -> None:
        self.serial.close()


class LCardBackend:
    def measure(self) -> Measurement:
        raise NotImplementedError


class SimLCardBackend(LCardBackend):
    def __init__(self, vmin: float, vmax: float, noise_v: float = 0.006) -> None:
        self.vmin = vmin
        self.vmax = vmax
        self.noise_v = noise_v
        self.last_codes = (0, 0)
        self.random = random.Random(140)

    def set_codes(self, code0: int, code1: int) -> None:
        self.last_codes = (code0, code1)

    def measure(self) -> Measurement:
        voltages = []
        for code in self.last_codes:
            nominal = expected_due_voltage(code, self.vmin, self.vmax)
            voltages.append(nominal + self.random.uniform(-self.noise_v, self.noise_v))
        return Measurement((voltages[0], voltages[1]))


class ManualLCardBackend(LCardBackend):
    def measure(self) -> Measurement:
        while True:
            text = input("Enter measured voltages for DAC0,DAC1 in volts: ").strip().replace(";", ",")
            parts = [part.strip() for part in text.split(",") if part.strip()]
            if len(parts) != 2:
                print("Please enter two numbers, for example: 1.234,1.235")
                continue
            try:
                return Measurement((float(parts[0]), float(parts[1])))
            except ValueError:
                print("Could not parse voltage values. Use dot as decimal separator, for example: 1.234,1.235")


class E14HelperBackend(LCardBackend):
    def __init__(self, helper_path: Path, channels: str, samples: int, timeout_s: float) -> None:
        self.helper_path = helper_path
        self.channels = channels
        self.samples = samples
        self.timeout_s = timeout_s

    def measure(self) -> Measurement:
        command = [
            str(self.helper_path),
            "--channels",
            self.channels,
            "--samples",
            str(self.samples),
        ]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
            )
        except FileNotFoundError as exc:
            raise TestFailure(
                f"LCard helper was not found: {self.helper_path}. "
                "Run with --backend manual if you want to enter LGraph measurements manually."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise TestFailure(f"LCard helper timed out after {self.timeout_s:.1f} s") from exc

        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip()
            raise TestFailure(f"LCard helper failed with code {completed.returncode}: {message}")

        lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        if not lines:
            raise TestFailure("LCard helper returned empty output")

        try:
            payload = json.loads(lines[-1])
        except json.JSONDecodeError as exc:
            raise TestFailure(f"LCard helper returned non-JSON output: {lines[-1]}") from exc

        channel_rows = payload.get("channels")
        if not isinstance(channel_rows, list) or len(channel_rows) < 2:
            raise TestFailure(f"LCard helper JSON does not contain two channel rows: {payload}")

        voltages = tuple(float(channel_rows[i]["voltage"]) for i in range(2))
        raw = tuple(float(channel_rows[i]["raw_mean"]) for i in range(2))
        return Measurement((voltages[0], voltages[1]), (raw[0], raw[1]))


def expected_due_voltage(code: int, vmin: float, vmax: float) -> float:
    return vmin + (vmax - vmin) * (code / 4095.0)


def parse_test_points(value: str | None) -> list[tuple[int, int]]:
    if not value:
        return list(DEFAULT_TEST_POINTS)

    points: list[tuple[int, int]] = []
    for part in value.split(","):
        if ":" not in part:
            raise argparse.ArgumentTypeError("test point must use '<dac0>:<dac1>' format")
        left, right = part.split(":", 1)
        dac0 = int(left, 0)
        dac1 = int(right, 0)
        if not 0 <= dac0 <= 4095 or not 0 <= dac1 <= 4095:
            raise argparse.ArgumentTypeError("DAC codes must be in 0..4095")
        points.append((dac0, dac1))
    if len(points) < 3:
        raise argparse.ArgumentTypeError("at least three test points are required")
    return points


def resolve_serial_port(port: str) -> str:
    if port.lower() != "auto":
        return port

    try:
        from serial.tools import list_ports
    except ImportError as exc:
        raise TestFailure("PySerial is not installed. Run: py -m pip install -r requirements.txt") from exc

    ports = list(list_ports.comports())
    if not ports:
        raise TestFailure("No serial ports found. Pass --serial-port COMx explicitly.")

    preferred_tokens = ("arduino", "due", "atmel", "sam-ba", "usb serial")
    for candidate in ports:
        text = " ".join(
            str(item).lower()
            for item in (candidate.device, candidate.description, candidate.manufacturer, candidate.hwid)
            if item
        )
        if any(token in text for token in preferred_tokens):
            return str(candidate.device)

    visible = ", ".join(str(candidate.device) for candidate in ports)
    raise TestFailure(f"Could not auto-detect Arduino Due. Available ports: {visible}")


def run_test(
    arduino: ArduinoDue,
    backend: LCardBackend,
    points: Sequence[tuple[int, int]],
    settle_s: float,
    vmin: float,
    vmax: float,
) -> list[ResultRow]:
    rows: list[ResultRow] = []
    for index, (code0, code1) in enumerate(points, start=1):
        arduino.set_dacs(code0, code1)
        if isinstance(backend, SimLCardBackend):
            backend.set_codes(code0, code1)
        time.sleep(settle_s)

        measurement = backend.measure()
        expected0 = expected_due_voltage(code0, vmin, vmax)
        expected1 = expected_due_voltage(code1, vmin, vmax)
        measured0, measured1 = measurement.voltages
        rows.append(
            ResultRow(
                index=index,
                code0=code0,
                code1=code1,
                expected0=expected0,
                expected1=expected1,
                measured0=measured0,
                measured1=measured1,
                error0=measured0 - expected0,
                error1=measured1 - expected1,
            )
        )
        print(
            f"{index:02d}: DAC0 code={code0:4d} {measured0:7.4f} V "
            f"(err {measured0 - expected0:+.4f}); "
            f"DAC1 code={code1:4d} {measured1:7.4f} V "
            f"(err {measured1 - expected1:+.4f})"
        )
    return rows


def monotonic_ok(rows: Sequence[ResultRow], channel: int, min_delta_v: float) -> bool:
    if channel == 0:
        ordered = sorted((row.code0, row.measured0) for row in rows)
    else:
        ordered = sorted((row.code1, row.measured1) for row in rows)

    for (_, previous), (_, current) in zip(ordered, ordered[1:]):
        if current + min_delta_v < previous:
            return False
    return True


def channel_span(rows: Sequence[ResultRow], channel: int) -> float:
    values = [row.measured0 if channel == 0 else row.measured1 for row in rows]
    return max(values) - min(values)


def summarize(rows: Sequence[ResultRow], tolerance_v: float, min_span_v: float, monotonic_margin_v: float) -> tuple[bool, list[str]]:
    errors0 = [abs(row.error0) for row in rows]
    errors1 = [abs(row.error1) for row in rows]
    failures: list[str] = []

    if max(errors0) > tolerance_v:
        failures.append(f"DAC0 max abs error {max(errors0):.4f} V > tolerance {tolerance_v:.4f} V")
    if max(errors1) > tolerance_v:
        failures.append(f"DAC1 max abs error {max(errors1):.4f} V > tolerance {tolerance_v:.4f} V")

    span0 = channel_span(rows, 0)
    span1 = channel_span(rows, 1)
    if span0 < min_span_v:
        failures.append(f"DAC0 span {span0:.4f} V < minimum {min_span_v:.4f} V")
    if span1 < min_span_v:
        failures.append(f"DAC1 span {span1:.4f} V < minimum {min_span_v:.4f} V")

    if not monotonic_ok(rows, 0, monotonic_margin_v):
        failures.append("DAC0 is not monotonic")
    if not monotonic_ok(rows, 1, monotonic_margin_v):
        failures.append("DAC1 is not monotonic")

    print()
    print("Summary:")
    print(f"  DAC0 max abs error: {max(errors0):.4f} V; span: {span0:.4f} V")
    print(f"  DAC1 max abs error: {max(errors1):.4f} V; span: {span1:.4f} V")
    print(f"  DAC0 error mean/stdev: {statistics.mean([row.error0 for row in rows]):+.4f} / {statistics.pstdev([row.error0 for row in rows]):.4f} V")
    print(f"  DAC1 error mean/stdev: {statistics.mean([row.error1 for row in rows]):+.4f} / {statistics.pstdev([row.error1 for row in rows]):.4f} V")

    return not failures, failures


def write_csv(rows: Sequence[ResultRow], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "index",
                "code0",
                "code1",
                "expected0_v",
                "expected1_v",
                "measured0_v",
                "measured1_v",
                "error0_v",
                "error1_v",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "index": row.index,
                    "code0": row.code0,
                    "code1": row.code1,
                    "expected0_v": f"{row.expected0:.6f}",
                    "expected1_v": f"{row.expected1:.6f}",
                    "measured0_v": f"{row.measured0:.6f}",
                    "measured1_v": f"{row.measured1:.6f}",
                    "error0_v": f"{row.error0:.6f}",
                    "error1_v": f"{row.error1:.6f}",
                }
            )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial-port", default="auto", help="Arduino Due serial port, 'auto', or 'sim'. Default: auto")
    parser.add_argument("--baud", type=int, default=115200, help="Arduino serial baud rate")
    parser.add_argument("--backend", choices=("e14-helper", "manual", "sim"), default="manual", help="Measurement backend")
    parser.add_argument("--helper-path", type=Path, default=Path("build/e14_adc_sample.exe"), help="Path to e14_adc_sample.exe")
    parser.add_argument("--lcard-channels", default="32,33", help="E14 logical ADC channels, default: 32,33 for X1,X2 common ground")
    parser.add_argument("--samples", type=int, default=32, help="ADC samples per channel")
    parser.add_argument("--settle-ms", type=float, default=250.0, help="Delay after SET before measurement")
    parser.add_argument("--timeout-s", type=float, default=8.0, help="Timeout for serial/LCard operations")
    parser.add_argument("--tolerance-v", type=float, default=0.20, help="Absolute voltage tolerance")
    parser.add_argument("--min-span-v", type=float, default=1.8, help="Minimum measured span for each DAC")
    parser.add_argument("--monotonic-margin-v", type=float, default=0.02, help="Allowed monotonicity noise margin")
    parser.add_argument("--due-dac-vmin", type=float, default=0.55, help="Expected Arduino Due DAC voltage at code 0")
    parser.add_argument("--due-dac-vmax", type=float, default=2.75, help="Expected Arduino Due DAC voltage at code 4095")
    parser.add_argument("--points", default=None, help="Comma-separated '<dac0>:<dac1>' test points, e.g. '0:4095,2048:2048,4095:0'")
    parser.add_argument("--csv", type=Path, default=None, help="CSV report path. Default: reports/dac_test_<timestamp>.csv")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    points = parse_test_points(args.points)

    arduino: ArduinoDue
    backend: LCardBackend

    if args.serial_port.lower() == "sim":
        arduino = SimArduinoDue()
    else:
        serial_port = resolve_serial_port(args.serial_port)
        print(f"Using Arduino serial port: {serial_port}")
        arduino = SerialArduinoDue(serial_port, args.baud, args.timeout_s)

    if args.backend == "sim":
        backend = SimLCardBackend(args.due_dac_vmin, args.due_dac_vmax)
    elif args.backend == "manual":
        backend = ManualLCardBackend()
    else:
        backend = E14HelperBackend(args.helper_path, args.lcard_channels, args.samples, args.timeout_s)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = args.csv or Path("reports") / f"dac_test_{timestamp}.csv"

    try:
        rows = run_test(
            arduino=arduino,
            backend=backend,
            points=points,
            settle_s=args.settle_ms / 1000.0,
            vmin=args.due_dac_vmin,
            vmax=args.due_dac_vmax,
        )
        write_csv(rows, csv_path)
        ok, failures = summarize(rows, args.tolerance_v, args.min_span_v, args.monotonic_margin_v)
        print(f"CSV report: {csv_path}")
        if ok:
            print("PASS")
            return 0

        print("FAIL")
        for failure in failures:
            print(f"  - {failure}")
        return 2
    finally:
        arduino.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TestFailure as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
