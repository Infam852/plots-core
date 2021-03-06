from pathlib import Path
import re

from datetime import datetime, timedelta
import sys
import matplotlib.pyplot as plt
import pandas as pd

import utils

HEADER_LINE = 'NAME'
TIMESTAMP_LINE = ':'
N_THREADS = 12

DROP_NFS = ['nr_gnb']  # do not plot these nfs
COLORS = ['r', 'g', 'b', 'c', 'm', 'y', 'k',
          'lime', 'dodgerblue', 'peru', 'indigo',
          'crimson', 'slategray']

BEFORE_TEST_TIME = 5
AFTER_TEST_TIME = 10

def read_docker_stats(start_time, end_time, docker_stats_file):
    df_dict = {
        'timestamp': [],
        'nf_name': [],
        'cpu': [],
        'mem': [],
        'net_io_tx': [],
        'net_io_rx': [],
        'block_io_tx': [],
        'block_io_rx': [],
    }

    NUMERIC_RES_REGEX = '^\d+\.?\d*'
    pattern = re.compile('([\d.]+)\s*(\w+)')

    def _append_row(timestamp, nf_name, cpu, mem, net_io, block_io):
        def _parse_value_with_unit(raw_val: str):
            raw_val = raw_val.strip()
            val, unit = pattern.match(raw_val).groups()
            val = float(val)
            if unit == 'kB':
                val *= 1000
            elif unit == 'kiB':
                val *= 1024
            elif unit == 'MB':
                val *= 1000*1000
            elif unit == 'MiB':
                val *= 1024*1024
            return val

        cpu = float(cpu[:-1]) / N_THREADS  # docker stats reports %/1cpu
        mem = re.findall(NUMERIC_RES_REGEX, mem)[0]
        mem = float(mem.split('MiB')[0])
        net_io_tx, net_io_rx = net_io.split('/')
        net_io_tx = _parse_value_with_unit(net_io_tx)
        net_io_rx = _parse_value_with_unit(net_io_rx)
        block_io_tx, block_io_rx = block_io.split('/')
        block_io_tx = _parse_value_with_unit(block_io_tx)
        block_io_rx = _parse_value_with_unit(block_io_rx)
        df_dict['timestamp'].append(timestamp)
        df_dict['nf_name'].append(nf_name)
        df_dict['cpu'].append(cpu)
        df_dict['mem'].append(mem)  # MiB
        df_dict['net_io_tx'].append(net_io_tx)
        df_dict['net_io_rx'].append(net_io_rx)
        df_dict['block_io_tx'].append(block_io_tx)
        df_dict['block_io_rx'].append(block_io_rx)


    last_timestamp = datetime(1000, 1, 1, 12, 30)
    TIME_FORMAT = '%H:%M:%S.%f'

    with open(docker_stats_file, 'r') as ds_fd:
        for line in ds_fd:
            line = line.strip()

            # stop processing if test ended
            if last_timestamp > end_time:
                break

            # parse line
            if HEADER_LINE in line:
                continue
            elif TIMESTAMP_LINE in line:
                last_timestamp = datetime.strptime(line, TIME_FORMAT) + timedelta(0, 1)
                continue
            elif not line:
                continue
            elif last_timestamp < start_time:
                continue

            nf_name, cpu, mem, net_io, block_io, _ = tuple(
                map(lambda s: s.strip(), line.split(',')))
            _append_row(last_timestamp, nf_name, cpu, mem, net_io, block_io)

    df = pd.DataFrame.from_dict(df_dict)
    df['net_io_tx_per_s'] = df.groupby('nf_name')['net_io_tx'].diff().fillna(0)
    df['net_io_rx_per_s'] = df.groupby('nf_name')['net_io_rx'].diff().fillna(0)
    # with pd.option_context('display.max_rows', None, 'display.max_columns', None):
    #     print(df[df['nf_name'] == 'amf'][['timestamp', 'net_io_tx_per_s', 'net_io_tx']])
    return df


def plot(df, nf_names, y, title, ylabel, save=False, yerr='cpu_err'):
    _, ax = plt.subplots(1)
    for idx, nf_name in enumerate(nf_names):
        if nf_name in DROP_NFS:
            continue

        nf_stats= df[df['nf_name_'] == nf_name]
        nf_stats.plot(
            x='delta_mean',
            y=y,
            label=nf_name,
            ax=ax,
            color=utils.get_color(nf_name),
            fmt='--',
            title=title,
            xlabel='Czas [s]',
            ylabel=ylabel,
            yerr=yerr,
            capsize=2,
        )
    if save:
        fn = title.replace(' ', '_')
        plt.savefig(f'{fn}.png')
    plt.show()


def _to_ms_numeric_timedelta(delta):
    return delta.astype('timedelta64[us]') / 1e6


def read_sample(sample_dir: Path, end_time_extra_time: int = 5):
    docker_stats_file = utils.find_in_iterdir(sample_dir, 'docker_stats')
    general_file = utils.find_in_iterdir(sample_dir, 'general')
    start_time, n_ues, duration = utils.read_general_file(general_file, n_iterations_line='N_ITERATIONS')  #N_ITERATIONS DURATION
    start_time = start_time - timedelta(0, BEFORE_TEST_TIME)
    end_time = start_time + timedelta(0, duration + AFTER_TEST_TIME)

    df = read_docker_stats(start_time, end_time, docker_stats_file)
    first_timestamp = df['timestamp'].iloc[0]
    df['delta'] = _to_ms_numeric_timedelta(df['timestamp'] - first_timestamp)
    df = df.drop('timestamp', axis=1)
    df.index.name = 'index'
    return df


def prepare_df(test_dir: Path):

    def _get_number_of_samples(df, uniq_name):
        df = df[df['nf_name'] == uniq_name]
        df = df[df['delta'] == 0]
        return len(df)

    stat_df = utils.concat_multiple_logs(test_dir, read_sample).fillna(0)  # long format
    tidy_df = stat_df.groupby(['index', 'nf_name']).agg(['mean', 'std']).reset_index()
    n_samples = _get_number_of_samples(stat_df, 'amf')
    tidy_df['cpu', 'ci_lower'], tidy_df['cpu', 'ci_upper'], tidy_df['cpu', 'err'] = utils.calc_conf_int(tidy_df, 'cpu', n_samples)
    tidy_df['mem', 'ci_lower'], tidy_df['mem', 'ci_upper'], tidy_df['mem', 'err'] = utils.calc_conf_int(tidy_df, 'mem', n_samples)
    utils.add_stat_err(tidy_df, 'net_io_tx_per_s', n_samples)
    utils.add_stat_err(tidy_df, 'net_io_rx_per_s', n_samples)
    return tidy_df


test_dir_20_30 = Path('..', 'containers', 'test-connect-ues', '20_30')
test_dir_10_30 = Path('..', 'containers', 'test-connect-ues', '10_30')

save = False
TEST_IDLE_DIR =  Path('..', 'containers', 'test-idle')
df_idle = prepare_df(TEST_IDLE_DIR)
# df_20_30 = prepare_df(test_dir_20_30)
# df_10_30 = prepare_df(test_dir_10_30)
# nf_names = df_10_30['nf_name'].unique()
# nf_names = df_20_30['nf_name'].unique()
# df_10_30 = df_10_30[~df_10_30['nf_name'].str.contains('ue')]
# df_10_30 = df_10_30[~df_10_30['nf_name'].str.contains('gnb')]
# df_20_30 = df_20_30[~df_20_30['nf_name'].str.contains('ue')]
# df_20_30 = df_20_30[~df_20_30['nf_name'].str.contains('gnb')]
mean_df = df_idle.groupby('nf_name').mean()
mean_df.columns = mean_df.columns.map('_'.join)
# df_10_30.columns = df_10_30.columns.map('_'.join)
# df_20_30.columns = df_20_30.columns.map('_'.join)
mean_df.to_csv('mean_idle_docker.csv')

# print(df.columns)
# with pd.option_context('display.max_rows', None, 'display.max_columns', None):
#     print(df_20_30[df_20_30['nf_name_'] == 'ausf'])
# plot(df_10_30, nf_names, 'cpu_mean', f'Por??wnanie obci????enia procesora [docker,10ue]', 'Obci????enie systemu [%]', save=save)
# plot(df_20_30, nf_names, 'cpu_mean', f'Por??wnanie obci????enia procesora [docker,20ue]', 'Obci????enie systemu [%]', save=save)
# plot(df_10_30, nf_names, 'net_io_tx_per_s_mean', f'Por??wnanie obci????enia procesora [docker,10ue,tx]', 'Tx [B/s]', yerr='net_io_tx_per_s_err', save=save)
# plot(df_10_30, nf_names, 'net_io_rx_per_s_mean', f'Por??wnanie obci????enia procesora [docker,10ue,rx]', 'Rx [B/s]', yerr='net_io_rx_per_s_err', save=save)
# plot(df_20_30, nf_names, 'net_io_tx_per_s_mean', f'Por??wnanie obci????enia interfejs??w docker 20ue tx', 'Tx [B/s]', yerr='net_io_tx_per_s_err', save=save)
# plot(df_20_30, nf_names, 'net_io_rx_per_s_mean', f'Por??wnanie obci????enia interfejs??w docker 20ue rx', 'Rx [B/s]', yerr='net_io_rx_per_s_err', save=save)
