"""Custom classes: the rules in custom-classes.csv, cluster_custom() and cluster_merged()."""
import pandas as pd
import pytest

from piggy_bank.etica import (COL_DATE, COL_OUT, COL_IN, COL_DESCR, COL_CLASS, CLASS_TODO, MERGED_CSV,
                              load_data, cluster_merged, cluster_custom, read_custom_classes)

ROWS = [
    ('2025-01-01', -100.0, None, 'SOTTOSCRIZIONE TIME DEPOSIT'),
    ('2025-01-02', -1000.0, None, 'Bonifico a Mario per prestito'),
    ('2025-01-02', -1000.0, None, 'AFFITTO'),
    ('2025-01-03', None, 1000.0, 'RIMBORSO PARTITA TIME DEPOSIT'),
    ('2025-01-03', -7.5, None, 'PIZZA'),
    ('2025-01-04', None, 7.5, 'PIZZA restituita'),
]


@pytest.fixture
def statements(write_csv):
    write_csv('a.csv', ROWS)


def classes(write_classes, lines) -> dict:
    """{description: class} after cluster_merged() with these rules."""
    write_classes(lines)
    df = cluster_merged(load_data())
    return dict(zip(df[COL_DESCR], df[COL_CLASS]))


def test_no_rules_file_means_everything_todo(statements):
    df = cluster_merged(load_data())

    assert set(df[COL_CLASS]) == {CLASS_TODO}


def test_class_column_is_appended_and_merged_csv_knows_nothing(statements, write_classes, data_dir):
    write_classes(['*,*,*,PIZZA,food'])
    df_merged = load_data()

    df = cluster_merged(df_merged)

    assert list(df.columns) == [COL_DATE, COL_OUT, COL_IN, COL_DESCR, COL_CLASS]
    assert COL_CLASS not in df_merged.columns  # the input is untouched
    assert COL_CLASS not in (data_dir / MERGED_CSV).read_text()


def test_wildcards_match_description_case_insensitive(statements, write_classes):
    got = classes(write_classes, ['*,*,*,time deposit,investment', '*,*,*,pizza,food'])

    assert got == {'SOTTOSCRIZIONE TIME DEPOSIT': 'investment', 'RIMBORSO PARTITA TIME DEPOSIT': 'investment',
                   'PIZZA': 'food', 'PIZZA restituita': 'food',
                   'Bonifico a Mario per prestito': CLASS_TODO, 'AFFITTO': CLASS_TODO}


def test_exact_rule(statements, write_classes):
    # Date + Out + blank In alone match two movements: the description narrows it to one
    got = classes(write_classes, ['2025-01-02,-1000,,PRESTITO,loan'])

    assert got['Bonifico a Mario per prestito'] == 'loan'
    assert got['AFFITTO'] == CLASS_TODO


def test_exact_rule_may_match_many(statements, write_classes):
    got = classes(write_classes, ['2025-01-02,-1000,,*,big'])

    assert got['Bonifico a Mario per prestito'] == got['AFFITTO'] == 'big'


def test_blank_amount_must_be_blank(statements, write_classes):
    # PIZZA has Out -7.5 and blank In, PIZZA restituita the opposite
    got = classes(write_classes, ['*,,*,pizza,refund'])

    assert got['PIZZA restituita'] == 'refund'
    assert got['PIZZA'] == CLASS_TODO


@pytest.mark.parametrize('rule', ['*,-7.50,*,*,food', '*,-7.5,,,food', '2025-01-03,*,*,PIZZA,food'])
def test_amounts_and_blank_description(statements, write_classes, rule):
    got = classes(write_classes, [rule])

    assert got['PIZZA'] == 'food'
    assert list(got.values()).count('food') == 1


def test_typo_in_class_makes_another_class(statements, write_classes):
    got = classes(write_classes, ['*,*,*,SOTTOSCRIZIONE,investment', '*,*,*,RIMBORSO,investments'])

    assert got['SOTTOSCRIZIONE TIME DEPOSIT'] == 'investment'
    assert got['RIMBORSO PARTITA TIME DEPOSIT'] == 'investments'


def test_first_rule_wins_and_conflicts_are_logged(statements, write_classes, caplog):
    got = classes(write_classes, ['*,*,*,PIZZA,food', '*,*,*,restituita,refund', '*,*,*,PIZZA,food'])

    assert got['PIZZA restituita'] == 'food'
    errors = [r.getMessage() for r in caplog.records if r.levelname == 'ERROR']
    # Line 3 (line 1 is the header) tries to re-classify; line 4 agrees with line 2, which is no error
    assert len(errors) == 1
    assert 'line 3' in errors[0] and "already classified 'food' by line 2" in errors[0]


def test_rule_matching_nothing_is_logged(statements, write_classes, caplog):
    got = classes(write_classes, ['*,*,*,SUSHI,food'])

    assert set(got.values()) == {CLASS_TODO}
    assert 'matches no movement' in caplog.text


@pytest.mark.parametrize('bad', [
    '2025-01-02,-1000,,,Prestito,loan',  # one field too many
    '2025-01-02,-1000,,Prestito',        # one field too few
    '02/01/2025,-1000,,*,loan',          # not YYYY-MM-DD
    ',-1000,,*,loan',                    # blank date
    '*,mille,,*,loan',                   # not a number
    '*,*,*,PIZZA,',                      # blank class
])
def test_malformed_rule_is_skipped(statements, write_classes, caplog, bad):
    got = classes(write_classes, [bad, '*,*,*,PIZZA,food'])

    assert got['PIZZA'] == 'food'
    assert set(got.values()) == {'food', CLASS_TODO}
    assert 'line 2 skipped' in caplog.text


def test_comments_blank_lines_and_spaces(statements, write_classes):
    got = classes(write_classes, ['# a note', '', ' * , * , * , PIZZA , food ', '#*,*,*,AFFITTO,rent'])

    assert got['PIZZA'] == 'food'
    assert got['AFFITTO'] == CLASS_TODO


def test_quoted_description_with_comma(write_csv, write_classes):
    write_csv('a.csv', [('2025-01-01', -1.0, None, 'ROSSI, MARIO')])

    assert classes(write_classes, ['*,*,*,"rossi, mario",friend']) == {'ROSSI, MARIO': 'friend'}


def test_wrong_header_raises(statements, write_classes):
    write_classes(['*,*,*,PIZZA,food'], header='Date,Out,In,Description')

    with pytest.raises(ValueError, match='header'):
        cluster_merged(load_data())


def test_header_after_comments_and_bom(data_dir):
    path = data_dir / 'rules.csv'
    path.write_text('﻿# my rules\nDate,Out,In,Description,Class\n*,*,*,X,x\n', encoding='utf-8')

    rules = read_custom_classes(path)

    assert [(r.line, r.descr, r.cls) for r in rules] == [(3, 'X', 'x')]


def test_empty_data(write_classes):
    write_classes(['*,*,*,PIZZA,food'])
    df = pd.DataFrame(columns=[COL_DATE, COL_OUT, COL_IN, COL_DESCR])

    assert cluster_custom(df).empty
    assert list(cluster_merged(df).columns) == [COL_DATE, COL_OUT, COL_IN, COL_DESCR, COL_CLASS]
