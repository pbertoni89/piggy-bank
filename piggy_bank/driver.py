#!/usr/bin/env python3

from piggy_bank.etica import *

logging.basicConfig(format='[%(levelname)8s]    %(message)s', level=logging.DEBUG)

logging.info('Loading data from %s', DATA_DIR)

# - - - Load data
_df_all = load_data()

print(f"Total rows in processed data: {_df_all.shape[0]}")
print(_df_all.head())

# Filter dataframes using the newly added 'Blacklisted' column
_df_net = _df_all[_df_all['Blacklisted'] == 0].copy().drop(columns=['Blacklisted'])
_df_blk = _df_all[_df_all['Blacklisted'] == 1].copy().drop(columns=['Blacklisted'])

print(f'Net entries: {_df_net.shape[0]}')
print(f'Blacklisted entries: {_df_blk.shape[0]}')

# - - - Process data

_df_net = compute_importo(_df_net)
_df_net, _m_net, _q_net = compute_ols(_df_net)
print(_df_net)

_df_all = compute_importo(_df_all)
_df_all, _m_mov, _q_mov = compute_ols(_df_all)
print(_df_all)

_df_blk = compute_importo(_df_blk)
_df_blk, _m_blk, _q_blk = compute_ols(_df_blk)
