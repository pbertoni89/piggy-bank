#!/usr/bin/env python3
"""Headless (deprecated) counterpart of the GUI: prints a summary of each view in DEFAULT_VIEWS.

A view is a (bl, inv) pair of filter modes, the same as the GUI All/Force/Veto radio buttons."""

from piggy_bank.etica import *

init_logging(True)

logging.info('Loading data from %s', DATA_DIR)

# - - - Load data
_df_all = load_data()

print(f"Total rows in processed data: {_df_all.shape[0]}")
print(f"Blacklisted: {_df_all[COL_BL].sum()}, Investments: {_df_all[COL_INV].sum()}")

# - - - Process data: one filtered view per (bl, inv) pair, each with its own running total and OLS
for _bl, _inv in DEFAULT_VIEWS:
    _df_view, _m, _q = build_view(_df_all, bl=_bl, inv=_inv)
    print_view_summary(_df_view, view_label(_bl, _inv), _m)
