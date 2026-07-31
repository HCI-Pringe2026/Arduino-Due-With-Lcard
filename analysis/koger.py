#!/usr/bin/env python3
"""
Когерентное накопление по папке с файлами отдельных шагов.
Считывает все файлы вида *step_*.txt, выравнивает их по началу шага
(используя app_timestamp из stim_events_json) и усредняет сигналы.
"""

import argparse
import sys
import json
import io
import csv
from pathlib import Path
import re
import warnings

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.interpolate import interp1d


def unescape_pandas_quoted(val: str) -> str:
    """Снимает экранирование pandas: убирает внешние кавычки и заменяет "" на "."""
    if len(val) >= 2 and val.startswith('"') and val.endswith('"'):
        val = val[1:-1].replace('""', '"')
    return val

def load_metadata_and_data(file_path: str):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    if '# DATA' not in content:
        raise ValueError(f"В файле {file_path} нет секции '# DATA'")
    meta_part, data_part = content.split('# DATA', 1)

    # Парсим метаданные с учётом экранирования кавычек
    metadata = {}
    reader = csv.reader(io.StringIO(meta_part.strip()), delimiter='\t')
    for row in reader:
        if not row or len(row) < 2 or row[0].startswith('#'):
            continue
        key = row[0].strip()
        value = '\t'.join(row[1:]).strip()  # на случай, если значение содержит табуляцию
        # Снимаем pandas-экранирование
        value = unescape_pandas_quoted(value)
        metadata[key] = value

    # Данные читаем через pandas, он сам разберёт TSV
    df = pd.read_csv(
        io.StringIO(data_part.strip()),
        sep='\t',
        engine='python',
        on_bad_lines='warn'
    )
    return metadata, df


def extract_step_info(metadata: dict) -> dict:
    """
    Извлекает номер шага, время начала (app_timestamp) из stim_events_json.
    """
    step_idx = int(metadata.get('export_step_index', -1))
    if step_idx == -1:
        raise ValueError("В метаданных нет export_step_index")

    events_json = metadata.get('stim_events_json', '[]')
    try:
        events = json.loads(events_json)
    except json.JSONDecodeError:
        raise ValueError("Не удалось разобрать stim_events_json")

    # Находим событие для данного шага
    start_time = None
    for ev in events:
        if ev.get('step_index') == step_idx:
            start_time = ev.get('app_timestamp')
            break
    if start_time is None:
        raise ValueError(f"Не найдено событие для шага {step_idx} в stim_events_json")

    return {
        'step_index': step_idx,
        'app_timestamp_start': start_time,
        'dac0_f1': float(metadata.get('export_step_dac0_f1_hz', 0)),
        'dac0_f2': float(metadata.get('export_step_dac0_f2_hz', 0)),
        'dac1_f1': float(metadata.get('export_step_dac1_f1_hz', 0)),
        'dac1_f2': float(metadata.get('export_step_dac1_f2_hz', 0)),
        'duration': float(metadata.get('export_step_duration_s', 0)),
    }


def process_folder(folder_path: str, window: float, channels: list[int] = None):
    """
    Основная функция: обрабатывает все файлы в папке, собирает эпохи и усредняет.
    """
    folder = Path(folder_path)
    if not folder.is_dir():
        raise NotADirectoryError(f"{folder_path} не является папкой")

    # Находим все файлы, содержащие "step_" в имени и .txt
    file_pattern = re.compile(r'.*step_\d+.*\.txt$', re.IGNORECASE)
    files = [f for f in folder.iterdir() if f.is_file() and file_pattern.search(f.name)]
    if not files:
        raise FileNotFoundError(f"В папке {folder_path} не найдено файлов шагов")

    print(f"Найдено файлов: {len(files)}")

    # Сначала прочитаем первый файл, чтобы определить каналы и частоту
    first_meta, first_df = load_metadata_and_data(files[0])
    # Определяем частоту
    fs_str = first_meta.get('lsl_nominal_srate_hz', '500.0')
    fs = float(fs_str)
    print(f"Частота дискретизации: {fs:.2f} Гц")

    # Каналы
    all_cols = first_df.columns
    filtered_cols = [c for c in all_cols if c.startswith('filtered_')]
    raw_cols = [c for c in all_cols if c.startswith('raw_')]
    if channels is not None:
        if filtered_cols:
            channel_names = [filtered_cols[i] for i in channels if i < len(filtered_cols)]
        elif raw_cols:
            channel_names = [raw_cols[i] for i in channels if i < len(raw_cols)]
        else:
            raise ValueError("Нет каналов с префиксом filtered_ или raw_.")
        if not channel_names:
            raise ValueError("Указанные номера каналов выходят за пределы.")
    else:
        channel_names = filtered_cols if filtered_cols else raw_cols
    n_channels = len(channel_names)
    print(f"Выбраны каналы: {', '.join(channel_names)}")

    # Собираем все эпохи
    all_epochs = []  # каждый элемент: (t_rel, signal_matrix)
    step_infos = []

    for file_path in files:
        try:
            meta, df = load_metadata_and_data(file_path)
            step_info = extract_step_info(meta)
            step_infos.append(step_info)
        except Exception as e:
            print(f"Ошибка при обработке {file_path.name}: {e}", file=sys.stderr)
            continue

        # Проверяем наличие колонки app_timestamp
        if 'app_timestamp' not in df.columns:
            print(f"В файле {file_path.name} нет app_timestamp, пропускаем", file=sys.stderr)
            continue

        t_abs = df['app_timestamp'].values.astype(float)
        t_rel = t_abs - step_info['app_timestamp_start']

        # Выбираем каналы
        data = df[channel_names].values.astype(float)

        # Сохраняем эпоху (все точки)
        all_epochs.append((t_rel, data))
        print(f"  Шаг {step_info['step_index']}: {len(t_rel)} отсчётов, длительность {t_rel[-1] - t_rel[0]:.3f} с")

    if not all_epochs:
        raise RuntimeError("Не удалось загрузить ни одной эпохи")

    # Теперь строим общую временную сетку для усреднения
    # Окно: от -window/2 до window/2
    half = window / 2.0
    n_points = int(np.ceil(window * fs)) + 1
    time_grid = np.linspace(-half, half, n_points)

    # Интерполируем каждую эпоху на эту сетку
    epochs_interp = np.full((len(all_epochs), n_points, n_channels), np.nan)

    for i, (t_rel, data) in enumerate(all_epochs):
        # Удаляем NaN в данных (если есть)
        valid = ~np.isnan(data).any(axis=1)
        if not np.any(valid):
            continue
        t_win = t_rel[valid]
        data_win = data[valid, :]

        # Проверяем, что есть точки в нужном диапазоне
        if len(t_win) < 2:
            continue
        # Ограничиваем интерполяцию только точками внутри окна
        mask = (t_win >= -half) & (t_win <= half)
        if not np.any(mask):
            continue
        t_win = t_win[mask]
        data_win = data_win[mask, :]
        if len(t_win) < 2:
            continue

        for ch in range(n_channels):
            # Убираем NaN внутри этого канала
            valid_ch = ~np.isnan(data_win[:, ch])
            if np.sum(valid_ch) < 2:
                continue
            interp = interp1d(t_win[valid_ch], data_win[valid_ch, ch],
                              kind='linear', bounds_error=False,
                              fill_value=np.nan)
            epochs_interp[i, :, ch] = interp(time_grid)

    # Усреднение
        # Усреднение по эпохам (ось 0)
        # Усреднение по эпохам (ось 0)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        avg = np.nanmean(epochs_interp, axis=0)          # (n_points, n_channels)
        std = np.nanstd(epochs_interp, axis=0)           # (n_points, n_channels)

    # Количество валидных эпох в каждой временной точке (по всем каналам)
    count_valid = np.sum(~np.isnan(epochs_interp[:, :, 0]), axis=0)
    count_valid_safe = np.where(count_valid == 0, np.nan, count_valid)[:, np.newaxis]
    sem = std / np.sqrt(count_valid_safe)                # broadcasting корректно         # broadcasting корректно

    # Построение графика
    fig, ax = plt.subplots(figsize=(12, 6))
    for ch in range(n_channels):
        ax.plot(time_grid, avg[:, ch], label=channel_names[ch])
        ax.fill_between(time_grid,
                         avg[:, ch] - sem[:, ch],
                         avg[:, ch] + sem[:, ch],
                         alpha=0.2)

    ax.axvline(0, color='black', linestyle='--', linewidth=0.8, label='Начало стимула')
    ax.set_xlabel('Время относительно начала шага, с')
    ax.set_ylabel('Амплитуда, В')
    ax.set_title(f'Когерентное накопление ({len(all_epochs)} шагов, окно ±{half:.3f} с)')
    ax.legend()
    ax.grid(True, alpha=0.3)

    return fig, avg, sem, time_grid, channel_names


def main():
    parser = argparse.ArgumentParser(
        description="Когерентное накопление по папке с файлами отдельных шагов."
    )
    parser.add_argument('--folder', '-d', required=True,
                        help='Путь к папке с файлами шагов')
    parser.add_argument('--window', '-w', type=float, default=0.4,
                        help='Длительность окна в секундах (по умолчанию 0.4, т.е. ±0.2 с)')
    parser.add_argument('--channels', '-c', nargs='+', type=int, default=None,
                        help='Номера каналов для отображения')
    parser.add_argument('--output', '-o', type=str, default=None,
                        help='Путь для сохранения графика (PNG)')
    parser.add_argument('--no-show', action='store_true',
                        help='Не показывать график интерактивно')
    args = parser.parse_args()

    try:
        fig, avg, sem, time_grid, channel_names = process_folder(
            args.folder, args.window, args.channels
        )
    except Exception as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        plt.savefig(args.output, dpi=150, bbox_inches='tight')
        print(f"График сохранён в {args.output}")
    if not args.no_show:
        plt.show()


if __name__ == '__main__':
    main()
