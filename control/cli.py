"""Control Arduino Due DAC0/DAC1 signal generator firmware."""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Sequence


DAC_VMIN = 0.55
DAC_VMAX = 2.75
DEFAULT_OFFSET_V = 1.65


class SignalError(RuntimeError):
    pass


def resolve_serial_port(port: str) -> str:
    if port.lower() != "auto":
        return port

    try:
        from serial.tools import list_ports
    except ImportError as exc:
        raise SignalError("PySerial is not installed. Run: py -m pip install -r requirements.txt") from exc

    ports = list(list_ports.comports())
    if not ports:
        raise SignalError("No serial ports found. Pass --serial-port COMx explicitly.")

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
    raise SignalError(f"Could not auto-detect Arduino Due. Available ports: {visible}")


class DueSerial:
    def __init__(self, port: str, baud: int, timeout_s: float) -> None:
        try:
            import serial
        except ImportError as exc:
            raise SignalError("PySerial is not installed. Run: py -m pip install -r requirements.txt") from exc

        self.timeout_s = timeout_s
        self.serial = serial.Serial(port=port, baudrate=baud, timeout=0.2, write_timeout=timeout_s)
        time.sleep(2.0)
        self.serial.reset_input_buffer()
        self.serial.reset_output_buffer()
        self.command("PING", min_responses=1)

    def close(self) -> None:
        self.serial.close()

    def command(self, text: str, min_responses: int = 1) -> list[dict]:
        deadline = time.monotonic() + self.timeout_s
        self.serial.write((text.strip() + "\n").encode("ascii"))

        responses: list[dict] = []
        while time.monotonic() < deadline:
            raw = self.serial.readline()
            if not raw:
                if len(responses) >= min_responses:
                    return responses
                continue

            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                print(f"Arduino: {line}")
                continue

            if payload.get("type") == "error":
                raise SignalError(f"Arduino rejected command {text!r}: {payload.get('message')}")
            responses.append(payload)
            if len(responses) >= min_responses:
                return responses

        raise SignalError(f"Timeout waiting for Arduino response to {text!r}")


def validate_code(value: int, name: str) -> None:
    if not 0 <= value <= 4095:
        raise SignalError(f"{name} must be in 0..4095")


def validate_wave(shape: str, freq_hz: float, amplitude_vpp: float, offset_v: float, name: str) -> None:
    if shape != "dc" and not (0.0 < freq_hz <= 100.0):
        raise SignalError(f"{name}: freq must be in 0..100 Hz")
    if shape == "dc" and not (0.0 <= freq_hz <= 100.0):
        raise SignalError(f"{name}: freq must be in 0..100 Hz")
    if amplitude_vpp < 0.0:
        raise SignalError(f"{name}: amplitude must be >= 0")
    if not (DAC_VMIN <= offset_v <= DAC_VMAX):
        raise SignalError(f"{name}: offset must be in {DAC_VMIN:.2f}..{DAC_VMAX:.2f} V")
    if shape != "dc":
        low_v = offset_v - amplitude_vpp * 0.5
        high_v = offset_v + amplitude_vpp * 0.5
        if low_v < DAC_VMIN or high_v > DAC_VMAX:
            raise SignalError(
                f"{name}: offset +/- amplitude/2 gives {low_v:.3f}..{high_v:.3f} V, "
                f"but Arduino Due DAC is about {DAC_VMIN:.2f}..{DAC_VMAX:.2f} V"
            )


def print_responses(responses: Sequence[dict]) -> None:
    for response in responses:
        print(json.dumps(response, ensure_ascii=False))


def wait_and_maybe_stop(due: DueSerial, duration_s: float, stop_after: bool) -> None:
    if duration_s <= 0:
        return
    print(f"Signal is running for {duration_s:.1f} s. Watch DAC0/DAC1 in LGraph.")
    time.sleep(duration_s)
    if stop_after:
        print_responses(due.command("STOP"))


def add_common_wave_args(parser: argparse.ArgumentParser, suffix: str = "") -> None:
    parser.add_argument(f"--shape{suffix}", choices=("sine", "square", "triangle", "ramp", "dc"), default="sine")
    parser.add_argument(f"--freq{suffix}", type=float, default=1.0, help="Frequency in Hz")
    parser.add_argument(
        f"--amp{suffix}",
        f"--amplitude{suffix}-vpp",
        dest=f"amplitude{suffix}_vpp",
        type=float,
        default=1.0,
        help="Peak-to-peak amplitude in volts",
    )
    parser.add_argument(f"--offset{suffix}", f"--offset{suffix}-v", dest=f"offset{suffix}_v", type=float, default=DEFAULT_OFFSET_V)
    parser.add_argument(f"--phase{suffix}", type=float, default=0.0, help="Phase in degrees")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial-port", default="auto", help="Arduino Due serial port, for example COM7. Default: auto")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--timeout-s", type=float, default=5.0)

    subparsers = parser.add_subparsers(dest="action", required=True)

    set_parser = subparsers.add_parser("set", help="Set static DAC codes")
    set_parser.add_argument("--dac0", type=int, required=True)
    set_parser.add_argument("--dac1", type=int, required=True)

    setv_parser = subparsers.add_parser("setv", help="Set static DAC voltages using DC generator mode")
    setv_parser.add_argument("--dac0", type=float, required=True, help="DAC0 voltage, about 0.55..2.75 V")
    setv_parser.add_argument("--dac1", type=float, required=True, help="DAC1 voltage, about 0.55..2.75 V")

    subparsers.add_parser("zero", help="Set DAC0 and DAC1 to code 0")
    subparsers.add_parser("mid", help="Set DAC0 and DAC1 to code 2048")
    subparsers.add_parser("stop", help="Stop waveform generation and keep last output codes")
    subparsers.add_parser("status", help="Read current generator settings")

    wave_parser = subparsers.add_parser("wave", help="Configure one channel or both channels with the same voltage waveform")
    wave_parser.add_argument("--dac", choices=("0", "1", "both"), default="both")
    add_common_wave_args(wave_parser)
    wave_parser.add_argument("--duration-s", type=float, default=0.0)
    wave_parser.add_argument("--stop-after", action="store_true")

    dual_parser = subparsers.add_parser("dual", help="Configure DAC0 and DAC1 independently in one synchronized command")
    add_common_wave_args(dual_parser, "0")
    add_common_wave_args(dual_parser, "1")
    dual_parser.add_argument("--duration-s", type=float, default=0.0)
    dual_parser.add_argument("--stop-after", action="store_true")

    wave_code_parser = subparsers.add_parser("wave-code", help="Legacy mode: set waveform using raw 12-bit DAC codes")
    wave_code_parser.add_argument("--dac", choices=("0", "1", "both"), default="both")
    wave_code_parser.add_argument("--shape", choices=("sine", "square", "triangle", "ramp"), default="sine")
    wave_code_parser.add_argument("--freq", type=float, default=1.0)
    wave_code_parser.add_argument("--low", type=int, default=0)
    wave_code_parser.add_argument("--high", type=int, default=4095)
    wave_code_parser.add_argument("--phase", type=float, default=0.0)
    wave_code_parser.add_argument("--duration-s", type=float, default=0.0)
    wave_code_parser.add_argument("--stop-after", action="store_true")

    return parser


def run_action(due: DueSerial, args: argparse.Namespace) -> int:
    if args.action == "set":
        validate_code(args.dac0, "dac0")
        validate_code(args.dac1, "dac1")
        print_responses(due.command(f"SET {args.dac0} {args.dac1}"))
    elif args.action == "setv":
        validate_wave("dc", 0.0, 0.0, args.dac0, "dac0")
        validate_wave("dc", 0.0, 0.0, args.dac1, "dac1")
        print_responses(due.command(f"GEN2 dc 0 0 {args.dac0:.6f} 0 dc 0 0 {args.dac1:.6f} 0", min_responses=2))
    elif args.action == "zero":
        print_responses(due.command("ZERO"))
    elif args.action == "mid":
        print_responses(due.command("MID"))
    elif args.action == "stop":
        print_responses(due.command("STOP"))
    elif args.action == "status":
        print_responses(due.command("STATUS"))
    elif args.action == "wave":
        validate_wave(args.shape, args.freq, args.amplitude_vpp, args.offset_v, args.dac)
        min_responses = 2 if args.dac == "both" else 1
        command = (
            f"GEN {args.dac} {args.shape} {args.freq:.6f} "
            f"{args.amplitude_vpp:.6f} {args.offset_v:.6f} {args.phase:.3f}"
        )
        print_responses(due.command(command, min_responses=min_responses))
        wait_and_maybe_stop(due, args.duration_s, args.stop_after)
    elif args.action == "dual":
        validate_wave(args.shape0, args.freq0, args.amplitude0_vpp, args.offset0_v, "dac0")
        validate_wave(args.shape1, args.freq1, args.amplitude1_vpp, args.offset1_v, "dac1")
        command = (
            f"GEN2 {args.shape0} {args.freq0:.6f} {args.amplitude0_vpp:.6f} {args.offset0_v:.6f} {args.phase0:.3f} "
            f"{args.shape1} {args.freq1:.6f} {args.amplitude1_vpp:.6f} {args.offset1_v:.6f} {args.phase1:.3f}"
        )
        print_responses(due.command(command, min_responses=2))
        wait_and_maybe_stop(due, args.duration_s, args.stop_after)
    elif args.action == "wave-code":
        validate_code(args.low, "low")
        validate_code(args.high, "high")
        if args.freq <= 0.0 or args.freq > 100.0:
            raise SignalError("freq must be in 0..100 Hz")
        min_responses = 2 if args.dac == "both" else 1
        command = f"WAVE {args.dac} {args.shape} {args.freq:.6f} {args.low} {args.high} {args.phase:.3f}"
        print_responses(due.command(command, min_responses=min_responses))
        wait_and_maybe_stop(due, args.duration_s, args.stop_after)
    else:
        raise SignalError(f"Unknown action: {args.action}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    port = resolve_serial_port(args.serial_port)
    print(f"Using Arduino serial port: {port}")

    due = DueSerial(port, args.baud, args.timeout_s)
    try:
        return run_action(due, args)
    finally:
        due.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SignalError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
