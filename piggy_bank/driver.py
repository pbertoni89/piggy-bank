#!/usr/bin/env python3
"""Headless (deprecated) counterpart of the GUI: prints a summary of each view in DEFAULT_VIEWS.

A view is the set of classes it excludes, the same as unchecking class checkboxes in the GUI."""

from piggy_bank.etica import *

init_logging(True)

logging.info('Loading data from %s', DATA_DIR)

# - - - Load and classify data
_df_all = cluster_merged(load_data())

print(f"Total rows in processed data: {_df_all.shape[0]}")
_counts = _df_all[COL_CLASS].value_counts()
print('Classes: ' + ', '.join(f'{c}: {_counts[c]}' for c in sorted_classes(_counts.index)))

# - - - Process data: one filtered view per excluded-classes tuple, each with its own running total and OLS
for _exclude in DEFAULT_VIEWS:
    _df_view, _m, _q = build_view(_df_all, exclude=_exclude)
    print_view_summary(_df_view, view_label(_exclude), _m)
