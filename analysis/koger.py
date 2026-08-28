#!/usr/bin/env python3

"""
Когерентный анализ EEG-эпох, полученных при фотостимуляции.

Вход:
    одна или несколько директорий с файлами вида:
        *step_*.txt

Пример:
    python koger.py \
        --folder "experiments/Казаков А" "experiments/Казаков Е"

Структура фотостимуляции:

    DAC0:
        dac0_f1
        dac0_f2

    DAC1:
        dac1_f1
        dac1_f2

Для каждой эпохи сохраняются все четыре частоты.
"""

import argparse
import csv
import io
import json
import re
import sys
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.interpolate import interp1d


# ============================================================================
# Configuration
# ============================================================================

STEP_FILE_PATTERN = re.compile(
    r".*step_\d+.*\.txt$",
    re.IGNORECASE,
)

DAC_FREQUENCY_KEYS = (
    "dac0_f1",
    "dac0_f2",
    "dac1_f1",
    "dac1_f2",
)


# ============================================================================
# File loading
# ============================================================================


def unescape_pandas_quoted(value: str) -> str:
    """
    Убирает экранирование кавычек, используемое pandas/CSV.

    Например:

        '"text with ""quotes""'

    превращается в:

        'text with "quotes"'
    """

    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        value = value[1:-1].replace('""', '"')

    return value


def load_metadata_and_data(
    file_path: Path,
) -> tuple[dict, pd.DataFrame]:
    """
    Читает файл формата:

        metadata...
        # DATA
        column1    column2    ...
        value      value      ...

    Metadata и данные обрабатываются отдельно.
    """

    content = file_path.read_text(
        encoding="utf-8",
    )

    if "# DATA" not in content:
        raise ValueError(f"В файле {file_path} отсутствует секция '# DATA'")

    meta_part, data_part = content.split(
        "# DATA",
        1,
    )

    # ------------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------------

    metadata = {}

    reader = csv.reader(
        io.StringIO(meta_part.strip()),
        delimiter="\t",
    )

    for row in reader:
        if not row or len(row) < 2 or row[0].startswith("#"):
            continue

        key = row[0].strip()

        value = "\t".join(row[1:]).strip()

        value = unescape_pandas_quoted(value)

        metadata[key] = value


    if not data_part.strip():
        raise ValueError(f"После '# DATA' нет данных: {file_path}")

    df = pd.read_csv(
        io.StringIO(data_part.strip()),
        sep="\t",
        engine="python",
    )

    if df.empty:
        raise ValueError(f"Таблица данных пуста: {file_path}")

    return metadata, df


# ============================================================================
# Metadata
# ============================================================================


def get_required_float(
    metadata: dict,
    key: str,
) -> float:
    """
    Получает обязательное числовое значение metadata.
    """

    value = metadata.get(key)

    if value is None or value == "":
        raise ValueError(f"В metadata отсутствует {key}")

    try:
        result = float(value)
    except ValueError as exc:
        raise ValueError(f"{key} имеет некорректное значение: {value!r}") from exc

    if not np.isfinite(result):
        raise ValueError(f"{key} имеет нечисловое значение: {value!r}")

    return result


def extract_step_info(
    metadata: dict,
) -> dict:
    """
    Извлекает информацию о конкретном шаге.

    Возвращает:

        step_index
        app_timestamp_start

        dac0_f1
        dac0_f2
        dac1_f1
        dac1_f2

        duration
    """

    try:
        step_index = int(metadata["export_step_index"])
    except (KeyError, ValueError) as exc:
        raise ValueError("Некорректный export_step_index") from exc

    # ------------------------------------------------------------------------
    # Находим timestamp начала конкретного шага
    # ------------------------------------------------------------------------

    events_json = metadata.get(
        "stim_events_json",
        "[]",
    )

    try:
        events = json.loads(events_json)
    except json.JSONDecodeError as exc:
        raise ValueError("Не удалось разобрать stim_events_json") from exc

    start_time = None

    for event in events:
        if event.get("step_index") == step_index:
            start_time = event.get("app_timestamp")
            break

    if start_time is None:
        raise ValueError(f"Не найдено событие для шага {step_index} в stim_events_json")

    try:
        start_time = float(start_time)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Некорректный app_timestamp: {start_time!r}") from exc

    # ------------------------------------------------------------------------
    # Частоты фотостимуляции
    # ------------------------------------------------------------------------

    dac0_f1 = get_required_float(
        metadata,
        "export_step_dac0_f1_hz",
    )

    dac0_f2 = get_required_float(
        metadata,
        "export_step_dac0_f2_hz",
    )

    dac1_f1 = get_required_float(
        metadata,
        "export_step_dac1_f1_hz",
    )

    dac1_f2 = get_required_float(
        metadata,
        "export_step_dac1_f2_hz",
    )

    # Частота должна быть положительной.
    frequencies = {
        "dac0_f1": dac0_f1,
        "dac0_f2": dac0_f2,
        "dac1_f1": dac1_f1,
        "dac1_f2": dac1_f2,
    }

    for name, frequency in frequencies.items():
        if frequency <= 0:
            raise ValueError(f"{name} должна быть > 0, получено {frequency}")

    duration = float(
        metadata.get(
            "export_step_duration_s",
            0,
        )
    )

    return {
        "step_index": step_index,
        "app_timestamp_start": start_time,
        "dac0_f1": dac0_f1,
        "dac0_f2": dac0_f2,
        "dac1_f1": dac1_f1,
        "dac1_f2": dac1_f2,
        "duration": duration,
    }


# ============================================================================
# File discovery
# ============================================================================


def collect_files(
    folder_paths: list[str],
) -> list[Path]:
    """
    Находит step-файлы во всех переданных директориях.

    Пример:

        --folder dir1 dir2 dir3
    """

    files = set()

    for folder_name in folder_paths:
        folder = Path(folder_name)

        if not folder.exists():
            raise FileNotFoundError(f"Директория не существует: {folder}")

        if not folder.is_dir():
            raise NotADirectoryError(f"Не является директорией: {folder}")

        for file_path in folder.iterdir():
            if file_path.is_file() and STEP_FILE_PATTERN.match(file_path.name):
                files.add(file_path)

    return sorted(files)


# ============================================================================
# Sampling rate
# ============================================================================


def validate_sampling_rate(
    metadata: dict,
    reference_fs: float | None,
    file_path: Path,
) -> float:
    """
    Проверяет частоту дискретизации файла.
    """

    fs = get_required_float(
        metadata,
        "lsl_nominal_srate_hz",
    )

    if fs <= 0:
        raise ValueError(
            f"Некорректная частота дискретизации {fs} Hz в {file_path.name}"
        )

    if reference_fs is None:
        return fs

    if not np.isclose(
        fs,
        reference_fs,
    ):
        raise ValueError(
            "Разная частота дискретизации:\n"
            f"  эталон: {reference_fs} Hz\n"
            f"  {file_path.name}: {fs} Hz"
        )

    return reference_fs


# ============================================================================
# Channels
# ============================================================================


def find_signal_columns(
    df: pd.DataFrame,
) -> list[str]:
    """
    Возвращает доступные EEG-каналы.

    Приоритет:

        filtered_*
        ↓
        raw_*
    """

    filtered = [column for column in df.columns if column.startswith("filtered_")]

    if filtered:
        return filtered

    raw = [column for column in df.columns if column.startswith("raw_")]

    if raw:
        return raw

    raise ValueError("В файле нет каналов filtered_* или raw_*")


def select_channels(
    df: pd.DataFrame,
    channels: list[int] | None,
) -> list[str]:
    """
    Выбирает каналы по индексам.
    """

    available = find_signal_columns(df)

    if channels is None:
        return available

    invalid = [index for index in channels if index < 0 or index >= len(available)]

    if invalid:
        raise ValueError(
            f"Некорректные индексы каналов: {invalid}. "
            f"Доступно каналов: {len(available)}"
        )

    return [available[index] for index in channels]


# ============================================================================
# Epoch loading
# ============================================================================


def load_epochs(
    files: list[Path],
    channels: list[int] | None,
):
    """
    Загружает все эпохи.

    Каждая эпоха содержит:

        time
        data
        step
        file
    """

    epochs = []

    reference_fs = None
    channel_names = None

    for file_path in files:
        print(f"\nОбработка: {file_path}")

        try:
            metadata, df = load_metadata_and_data(file_path)

            step = extract_step_info(metadata)

        except Exception as exc:
            print(
                f"Ошибка metadata: {exc}",
                file=sys.stderr,
            )

            continue

        # --------------------------------------------------------------------
        # Sampling rate
        # --------------------------------------------------------------------

        try:
            reference_fs = validate_sampling_rate(
                metadata,
                reference_fs,
                file_path,
            )
        except Exception as exc:
            print(
                f"Ошибка fs: {exc}",
                file=sys.stderr,
            )

            continue

        # --------------------------------------------------------------------
        # Timestamp
        # --------------------------------------------------------------------

        if "app_timestamp" not in df.columns:
            print(
                f"В {file_path.name} отсутствует app_timestamp",
                file=sys.stderr,
            )

            continue

        # --------------------------------------------------------------------
        # Channels
        # --------------------------------------------------------------------

        try:
            if channel_names is None:
                channel_names = select_channels(
                    df,
                    channels,
                )

            else:
                missing = [
                    channel for channel in channel_names if channel not in df.columns
                ]

                if missing:
                    raise ValueError(f"Отсутствуют каналы: {missing}")

        except Exception as exc:
            print(
                f"Ошибка каналов: {exc}",
                file=sys.stderr,
            )

            continue

        # --------------------------------------------------------------------
        # Time
        # --------------------------------------------------------------------

        time_absolute = pd.to_numeric(
            df["app_timestamp"],
            errors="coerce",
        ).to_numpy(dtype=float)

        time_relative = time_absolute - step["app_timestamp_start"]

        # --------------------------------------------------------------------
        # Signal
        # --------------------------------------------------------------------

        data = (
            df[channel_names]
            .apply(
                pd.to_numeric,
                errors="coerce",
            )
            .to_numpy(dtype=float)
        )

        if len(time_relative) == 0:
            print(
                f"Нет отсчётов: {file_path.name}",
                file=sys.stderr,
            )
            continue

        # --------------------------------------------------------------------
        # Epoch
        # --------------------------------------------------------------------

        epochs.append(
            {
                "time": time_relative,
                "data": data,
                "step": step,
                "file": file_path,
            }
        )

        print(f"  step: {step['step_index']}")

        print(f"  samples: {len(time_relative)}")

        print(f"  fs: {reference_fs:.3f} Hz")

        print(f"  DAC0: {step['dac0_f1']:.3f} + {step['dac0_f2']:.3f} Hz")

        print(f"  DAC1: {step['dac1_f1']:.3f} + {step['dac1_f2']:.3f} Hz")

    if not epochs:
        raise RuntimeError("Не удалось загрузить ни одной эпохи.")

    return (
        epochs,
        reference_fs,
        channel_names,
    )


# ============================================================================
# Stimulation configuration
# ============================================================================


def validate_stimulation_frequencies(
    epochs: list[dict],
):
    """
    Проверяет, что все эпохи имеют одинаковую
    конфигурацию фотостимуляции.
    """

    reference = np.array(
        [epochs[0]["step"][name] for name in DAC_FREQUENCY_KEYS],
        dtype=float,
    )

    for epoch in epochs[1:]:
        current = np.array(
            [epoch["step"][name] for name in DAC_FREQUENCY_KEYS],
            dtype=float,
        )

        if not np.allclose(
            current,
            reference,
        ):
            raise ValueError(
                "Частоты фотостимуляции "
                "различаются между эпохами.\n"
                f"Эталон: {reference}\n"
                f"{epoch['file'].name}: {current}"
            )

    return {name: reference[index] for index, name in enumerate(DAC_FREQUENCY_KEYS)}


# ============================================================================
# Interpolation
# ============================================================================


def interpolate_epochs(
    epochs: list[dict],
    time_grid: np.ndarray,
    n_channels: int,
) -> np.ndarray:
    """
    Интерполирует все эпохи на общую временную сетку.

    Каждый канал обрабатывается независимо.

    Это важно: NaN в одном EEG-канале не должны
    удалять соответствующий отсчёт из остальных каналов.
    """

    result = np.full(
        (
            len(epochs),
            len(time_grid),
            n_channels,
        ),
        np.nan,
        dtype=float,
    )

    for epoch_index, epoch in enumerate(epochs):
        time = epoch["time"]
        data = epoch["data"]

        for channel_index in range(n_channels):
            signal = data[
                :,
                channel_index,
            ]

            valid = np.isfinite(time) & np.isfinite(signal)

            if np.sum(valid) < 2:
                continue

            valid_time = time[valid]
            valid_signal = signal[valid]

            # Сортировка нужна для interp1d.
            order = np.argsort(valid_time)

            valid_time = valid_time[order]

            valid_signal = valid_signal[order]

            # Убираем одинаковые timestamp.
            unique_time, unique_indices = np.unique(
                valid_time,
                return_index=True,
            )

            unique_signal = valid_signal[unique_indices]

            if len(unique_time) < 2:
                continue

            interpolator = interp1d(
                unique_time,
                unique_signal,
                kind="linear",
                bounds_error=False,
                fill_value=np.nan,
            )

            result[
                epoch_index,
                :,
                channel_index,
            ] = interpolator(time_grid)

    return result


# ============================================================================
# Time-domain statistics
# ============================================================================


def calculate_statistics(
    epochs_interp: np.ndarray,
):
    """
    Рассчитывает:

        average
        standard deviation
        SEM
        количество валидных эпох

    Размер всех результатов:

        (time, channel)
    """

    with warnings.catch_warnings():
        warnings.simplefilter(
            "ignore",
            RuntimeWarning,
        )

        average = np.nanmean(
            epochs_interp,
            axis=0,
        )

        std = np.nanstd(
            epochs_interp,
            axis=0,
            ddof=1,
        )

    count_valid = np.sum(
        np.isfinite(epochs_interp),
        axis=0,
    )

    sem = np.divide(
        std,
        np.sqrt(count_valid),
        out=np.full_like(
            std,
            np.nan,
        ),
        where=count_valid > 1,
    )

    return (
        average,
        std,
        sem,
        count_valid,
    )


# ============================================================================
# Complex frequency analysis
# ============================================================================


def complex_amplitude(
    time: np.ndarray,
    signal: np.ndarray,
    frequency: float,
) -> complex:
    """
    Оценивает комплексную амплитуду компоненты frequency.

    Используется:

        C = 2/N * Σ x(t) exp(-j 2πft)

    Тогда:

        |C|       -> амплитуда
        angle(C)  -> фаза

    Это позволяет работать с амплитудой и фазой
    как с единым комплексным коэффициентом.
    """

    valid = np.isfinite(time) & np.isfinite(signal)

    time = time[valid]
    signal = signal[valid]

    if len(signal) < 2:
        return np.nan + 1j * np.nan

    reference = np.exp(-2j * np.pi * frequency * time)

    return 2.0 / len(signal) * np.sum(signal * reference)


def coherent_average(
    coefficients: np.ndarray,
) -> complex:
    """
    Когерентное усреднение комплексных коэффициентов.

        C_coherent = mean(C_i)

    Амплитуда:

        |C_coherent|

    В отличие от:

        mean(|C_i|)

    """

    valid = np.isfinite(coefficients.real) & np.isfinite(coefficients.imag)

    coefficients = coefficients[valid]

    if len(coefficients) == 0:
        return np.nan + 1j * np.nan

    return np.mean(coefficients)


def phase_coherence(
    coefficients: np.ndarray,
) -> float:
    """
    Inter-trial phase coherence:

        R =
        |Σ C_i|
        --------
         Σ |C_i|

    Значения:

        1 -> полностью согласованные фазы
        0 -> фазы полностью разбросаны
    """

    valid = np.isfinite(coefficients.real) & np.isfinite(coefficients.imag)

    coefficients = coefficients[valid]

    if len(coefficients) == 0:
        return np.nan

    amplitudes = np.abs(coefficients)

    denominator = np.sum(amplitudes)

    if denominator == 0:
        return np.nan

    return float(np.abs(np.sum(coefficients)) / denominator)


def analyze_frequencies(
    epochs: list[dict],
    frequencies: dict,
    channel_names: list[str],
):
    """
    Анализирует четыре частоты фотостимуляции.

    Для каждой частоты и каждого канала
    рассчитываются:

        complex coefficients
        coherent amplitude
        coherent phase
        phase coherence
    """

    n_epochs = len(epochs)
    n_channels = len(channel_names)

    results = {}

    for frequency_name in DAC_FREQUENCY_KEYS:
        frequency = frequencies[frequency_name]

        coefficients = np.full(
            (
                n_epochs,
                n_channels,
            ),
            np.nan + 1j * np.nan,
            dtype=complex,
        )

        for epoch_index, epoch in enumerate(epochs):
            for channel_index in range(n_channels):
                coefficients[
                    epoch_index,
                    channel_index,
                ] = complex_amplitude(
                    epoch["time"],
                    epoch["data"][
                        :,
                        channel_index,
                    ],
                    frequency,
                )

        coherent = np.array(
            [
                coherent_average(
                    coefficients[
                        :,
                        channel_index,
                    ]
                )
                for channel_index in range(n_channels)
            ]
        )

        coherence = np.array(
            [
                phase_coherence(
                    coefficients[
                        :,
                        channel_index,
                    ]
                )
                for channel_index in range(n_channels)
            ]
        )

        results[frequency_name] = {
            "frequency": frequency,
            "coefficients": coefficients,
            "coherent": coherent,
            "amplitude": np.abs(coherent),
            "phase": np.angle(
                coherent,
                deg=True,
            ),
            "coherence": coherence,
        }

    return results


# ============================================================================
# Plotting
# ============================================================================


def plot_average(
    time_grid: np.ndarray,
    average: np.ndarray,
    sem: np.ndarray,
    channel_names: list[str],
    n_epochs: int,
    window: float,
):
    """
    Строит временное усреднение по эпохам.

    ВАЖНО:

    Это временное epoch averaging.

    Оно не является фазовым когерентным накоплением
    на частотах DAC само по себе.
    """

    half_window = window / 2.0

    fig, ax = plt.subplots(figsize=(12, 6))

    for channel_index, channel_name in enumerate(channel_names):
        ax.plot(
            time_grid,
            average[
                :,
                channel_index,
            ],
            label=channel_name,
        )

        ax.fill_between(
            time_grid,
            average[
                :,
                channel_index,
            ]
            - sem[
                :,
                channel_index,
            ],
            average[
                :,
                channel_index,
            ]
            + sem[
                :,
                channel_index,
            ],
            alpha=0.2,
        )

    ax.axvline(
        0,
        linestyle="--",
        linewidth=0.8,
        label="Начало стимула",
    )

    ax.set_xlabel("Время относительно начала стимула, с")

    ax.set_ylabel("Амплитуда, В")

    ax.set_title(f"Усреднение EEG-эпох ({n_epochs} эпох, окно ±{half_window:.3f} с)")

    ax.legend()
    ax.grid(
        True,
        alpha=0.3,
    )

    fig.tight_layout()

    return fig


# ============================================================================
# Frequency results
# ============================================================================


def print_frequency_results(
    results: dict,
    channel_names: list[str],
):
    """
    Выводит результаты частотного анализа.
    """

    print()
    print("=" * 80)
    print("КОГЕРЕНТНЫЙ ЧАСТОТНЫЙ АНАЛИЗ")
    print("=" * 80)

    for frequency_name in DAC_FREQUENCY_KEYS:
        result = results[frequency_name]

        print()
        print(f"{frequency_name}: {result['frequency']:.6f} Hz")

        print(f"{'Channel':<25}{'Amplitude':>15}{'Phase':>15}{'Coherence':>15}")

        print("-" * 70)

        for index, channel_name in enumerate(channel_names):
            amplitude = result["amplitude"][index]

            phase = result["phase"][index]

            coherence = result["coherence"][index]

            print(
                f"{channel_name:<25}{amplitude:>15.6g}{phase:>14.3f}°{coherence:>15.3f}"
            )


# ============================================================================
# Main processing
# ============================================================================


def process_folders(
    folder_paths: list[str],
    window: float,
    channels: list[int] | None = None,
):
    """
    Полный pipeline обработки:

        folders
          ↓
        step files
          ↓
        metadata + data
          ↓
        epoch alignment by app_timestamp
          ↓
        interpolation
          ↓
        time-domain averaging
          ↓
        frequency-domain analysis
    """

    files = collect_files(folder_paths)

    if not files:
        raise FileNotFoundError("В указанных директориях не найдено файлов step_*.txt.")

    print(f"Найдено файлов: {len(files)}")

    (
        epochs,
        fs,
        channel_names,
    ) = load_epochs(
        files,
        channels,
    )

    print()
    print(f"Успешно загружено эпох: {len(epochs)}")

    print(f"Частота дискретизации: {fs:.3f} Hz")

    print("Каналы: " + ", ".join(channel_names))

    # ------------------------------------------------------------------------
    # Проверка конфигурации стимуляции
    # ------------------------------------------------------------------------

    frequencies = validate_stimulation_frequencies(epochs)

    print()
    print("Конфигурация фотостимуляции:")

    for name in DAC_FREQUENCY_KEYS:
        print(f"  {name}: {frequencies[name]:.6f} Hz")

    # ------------------------------------------------------------------------
    # Time grid
    # ------------------------------------------------------------------------

    half_window = window / 2.0

    n_points = int(np.ceil(window * fs)) + 1

    time_grid = np.linspace(
        -half_window,
        half_window,
        n_points,
    )

    # ------------------------------------------------------------------------
    # Interpolation
    # ------------------------------------------------------------------------

    epochs_interp = interpolate_epochs(
        epochs,
        time_grid,
        len(channel_names),
    )

    # ------------------------------------------------------------------------
    # Time-domain statistics
    # ------------------------------------------------------------------------

    (
        average,
        std,
        sem,
        count_valid,
    ) = calculate_statistics(epochs_interp)

    # ------------------------------------------------------------------------
    # Frequency-domain analysis
    # ------------------------------------------------------------------------

    frequency_results = analyze_frequencies(
        epochs,
        frequencies,
        channel_names,
    )

    # ------------------------------------------------------------------------
    # Plot
    # ------------------------------------------------------------------------

    fig = plot_average(
        time_grid,
        average,
        sem,
        channel_names,
        len(epochs),
        window,
    )

    return (
        fig,
        average,
        sem,
        time_grid,
        channel_names,
        frequency_results,
        count_valid,
    )


# ============================================================================
# CLI
# ============================================================================


def main():

    parser = argparse.ArgumentParser(
        description=("Когерентный анализ EEG при фотостимуляции.")
    )

    parser.add_argument(
        "--folder",
        "-d",
        nargs="+",
        required=True,
        metavar="DIR",
        help=("Одна или несколько директорий с файлами step_*.txt."),
    )

    parser.add_argument(
        "--window",
        "-w",
        type=float,
        default=0.4,
        help=("Длина временного окна в секундах. По умолчанию: 0.4."),
    )

    parser.add_argument(
        "--channels",
        "-c",
        nargs="+",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Индексы каналов. "
            "По умолчанию используются "
            "все filtered_* каналы, "
            "либо raw_*."
        ),
    )

    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        metavar="FILE",
        help=("Сохранить график в указанный файл."),
    )

    parser.add_argument(
        "--no-show",
        action="store_true",
        help=("Не открывать интерактивное окно графика."),
    )

    args = parser.parse_args()

    if args.window <= 0:
        parser.error("--window должен быть больше 0.")

    try:
        (
            fig,
            average,
            sem,
            time_grid,
            channel_names,
            frequency_results,
            count_valid,
        ) = process_folders(
            args.folder,
            args.window,
            args.channels,
        )

        print_frequency_results(
            frequency_results,
            channel_names,
        )

        if args.output:
            fig.savefig(
                args.output,
                dpi=150,
                bbox_inches="tight",
            )

            print()
            print(f"График сохранён: {args.output}")

        if not args.no_show:
            plt.show()

    except KeyboardInterrupt:
        print(
            "\nОперация прервана.",
            file=sys.stderr,
        )

        sys.exit(130)

    except Exception as exc:
        print(
            f"\nОшибка: {exc}",
            file=sys.stderr,
        )

        sys.exit(1)


if __name__ == "__main__":
    main()
