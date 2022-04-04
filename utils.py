from datetime import datetime
from pathlib import Path
from typing import Callable
import numpy as np
import scipy.stats
import pandas as pd


def find_in_iterdir(dir_path: Path, fn_part: str) -> Path:
    dir_path = Path(dir_path)
    return next(
        path for path in dir_path.iterdir()
        if fn_part in str(path)
    )


def _strip_seconds(line: str):
    return line.strip()[:-1] if line.strip().endswith('s') else line.strip()


def read_general_file(path, n_ues_line = 'N_UES', n_iterations_line = 'N_ITERATIONS'):
    timestamp_line = 'started'
    timestamp = ''
    n_ues = '-1'
    n_iterations = '-1'
    with open(path, 'r') as fd:
        for line in fd.readlines():
            if timestamp_line in line:
                timestamp = line[:8].replace('-', ':')
                timestamp = datetime.strptime(timestamp, '%H:%M:%S')
            elif n_ues_line in line:
                n_ues = int(line.split(':')[1].strip())
            elif n_iterations_line in line:
                n_iterations = int(_strip_seconds(line.split(':')[1]))
    return timestamp, n_ues, n_iterations


def calc_conf_int(df, col, n_samples, confidence = 0.05):
    # n = len(df[df['nf_name'] == 'amf'])
    h = df[col, 'std'] * scipy.stats.t.ppf((1 + confidence) / 2., n_samples-1)
    m = df[col, 'mean']
    return m - h, m + h


def concat_multiple_logs(test_dir: Path, read_sample_func: Callable):
    stat_df = pd.DataFrame()
    for sample_dir in test_dir.iterdir():
        # garbage
        if not sample_dir.name.startswith('test'):
            print(f'[DEBUG] skip {sample_dir}...')
            continue

        print(f'[DEBUG] read {sample_dir}.........')
        df = read_sample_func(sample_dir)
        stat_df = pd.concat((stat_df, df))
    return stat_df
