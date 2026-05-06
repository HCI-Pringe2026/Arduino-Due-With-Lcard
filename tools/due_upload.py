#!/usr/bin/env python3
"""Compile and upload the Arduino Due DAC generator firmware via arduino-cli."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SKETCH = PROJECT_ROOT / "firmware" / "due_dac_selftest"
PROGRAMMING_PORT_FQBN = "arduino:sam:arduino_due_x_dbg"
NATIVE_PORT_FQBN = "arduino:sam:arduino_due_x"


class UploadError(RuntimeError):
    pass


def arduino_cli_candidates() -> list[Path]:
    candidates: list[Path] = []
    from_path = shutil.which("arduino-cli")
    if from_path:
        candidates.append(Path(from_path))

    if sys.platform == "win32":
        bases: list[Path] = []
        if os.environ.get("PROGRAMFILES"):
            bases.append(Path(os.environ["PROGRAMFILES"]) / "Arduino IDE")
        if os.environ.get("PROGRAMFILES(X86)"):
            bases.append(Path(os.environ["PROGRAMFILES(X86)"]) / "Arduino IDE")
        if os.environ.get("LOCALAPPDATA"):
            bases.append(Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Arduino IDE")

        for base in bases:
            candidates.extend(
                [
                    base / "resources" / "app" / "lib" / "backend" / "resources" / "arduino-cli.exe",
                    base / "resources" / "app" / "node_modules" / "arduino-ide-extension" / "build" / "arduino-cli.exe",
                ]
            )

    return candidates


def resolve_arduino_cli(value: str) -> Path:
    if value.lower() != "auto":
        path = Path(value)
        if not path.exists():
            raise UploadError(f"arduino-cli was not found: {path}")
        return path

    for candidate in arduino_cli_candidates():
        if candidate.exists():
            return candidate

    raise UploadError(
        "arduino-cli was not found. Install Arduino CLI or Arduino IDE 2.x, "
        "or pass --arduino-cli C:\\path\\to\\arduino-cli.exe"
    )


def resolve_serial_port(port: str) -> str:
    if port.lower() != "auto":
        return port

    try:
        from serial.tools import list_ports
    except ImportError as exc:
        raise UploadError("PySerial is not installed. Run: py -m pip install -r requirements.txt") from exc

    ports = list(list_ports.comports())
    preferred_tokens = ("arduino", "due", "atmel", "sam-ba", "usb serial")
    for candidate in ports:
        text = " ".join(
            str(item).lower()
            for item in (candidate.device, candidate.description, candidate.manufacturer, candidate.hwid)
            if item
        )
        if any(token in text for token in preferred_tokens):
            return str(candidate.device)

    visible = ", ".join(str(candidate.device) for candidate in ports) or "none"
    raise UploadError(f"Could not auto-detect Arduino Due port. Available ports: {visible}")


def run(command: Sequence[str], verbose: bool) -> None:
    print("+ " + " ".join(str(part) for part in command))
    completed = subprocess.run(command, text=True)
    if completed.returncode != 0:
        raise UploadError(f"Command failed with exit code {completed.returncode}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arduino-cli", default="auto", help="Path to arduino-cli.exe or 'auto'")
    parser.add_argument("--sketch", type=Path, default=DEFAULT_SKETCH)
    parser.add_argument("--port", default="auto", help="COM port, for example COM7, or 'auto'")
    parser.add_argument("--fqbn", default=PROGRAMMING_PORT_FQBN, help="Arduino FQBN")
    parser.add_argument("--native", action="store_true", help="Use Arduino Due Native USB Port FQBN")
    parser.add_argument("--skip-core-install", action="store_true", help="Do not run core update-index/install")
    parser.add_argument("--compile-only", action="store_true")
    parser.add_argument("--upload-only", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    arduino_cli = resolve_arduino_cli(args.arduino_cli)
    sketch = args.sketch.resolve()
    fqbn = NATIVE_PORT_FQBN if args.native else args.fqbn

    if not sketch.exists():
        raise UploadError(f"Sketch directory was not found: {sketch}")
    if args.compile_only and args.upload_only:
        raise UploadError("--compile-only and --upload-only cannot be used together")

    if not args.skip_core_install:
        run([str(arduino_cli), "core", "update-index"], args.verbose)
        run([str(arduino_cli), "core", "install", "arduino:sam"], args.verbose)

    if not args.upload_only:
        command = [str(arduino_cli), "compile", "--fqbn", fqbn, str(sketch)]
        if args.verbose:
            command.append("--verbose")
        run(command, args.verbose)

    if not args.compile_only:
        port = resolve_serial_port(args.port)
        command = [str(arduino_cli), "upload", "-p", port, "--fqbn", fqbn, str(sketch)]
        if args.verbose:
            command.append("--verbose")
        run(command, args.verbose)

    print("Done")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except UploadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
