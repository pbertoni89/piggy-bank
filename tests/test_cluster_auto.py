"""Automatic classes: cluster_auto() and its place in cluster_merged(). Embeddings are faked (conftest)."""
import re
from pathlib import Path

import pandas as pd
import pytest

from piggy_bank import etica
from piggy_bank.etica import (COL_DESCR, COL_CLASS, CLASS_TODO, AUTO_N_CLUSTERS, AUTO_SEED,
                              load_data, cluster_auto, cluster_merged, auto_class_name)

DESCRIPTIONS = ['PAGAMENTO POS ESSELUNGA', 'PAGAMENTO POS CONAD', 'PAGAMENTO POS COOP',
                'PRELIEVO BANCOMAT 4455', 'PRELIEVO BANCOMAT 9911',
                'ADDEBITO SDD ENEL', 'ADDEBITO SDD TIM']


def auto(descriptions, classes=None, **kwargs) -> pd.Series:
    df = pd.DataFrame({COL_DESCR: descriptions})
    if classes is None:
        classes = [None] * len(descriptions)
    return cluster_auto(df, pd.Series(classes, index=df.index, dtype=object), **kwargs)


def test_groups_similar_descriptions_and_names_them_by_keywords():
    got = auto(DESCRIPTIONS, n_clusters=3)

    assert dict(zip(DESCRIPTIONS, got)) == {
        'PAGAMENTO POS ESSELUNGA': '[a1] pagamento/conad', 'PAGAMENTO POS CONAD': '[a1] pagamento/conad',
        'PAGAMENTO POS COOP': '[a1] pagamento/conad',
        'PRELIEVO BANCOMAT 4455': '[a2] bancomat/prelievo', 'PRELIEVO BANCOMAT 9911': '[a2] bancomat/prelievo',
        # Words under 5 letters (SDD, ENEL, TIM) never name a class
        'ADDEBITO SDD ENEL': '[a3] addebito', 'ADDEBITO SDD TIM': '[a3] addebito'}


def test_only_fills_unclassified_rows():
    classes = ['food', None, None, 'cash', None, None, None]

    got = auto(DESCRIPTIONS, classes, n_clusters=2)

    assert got[0] == 'food' and got[3] == 'cash'
    assert all(re.fullmatch(r'\[a\d\]( .+)?', c) for i, c in enumerate(got) if classes[i] is None)


def test_input_is_untouched():
    classes = pd.Series([None] * len(DESCRIPTIONS), dtype=object)

    cluster_auto(pd.DataFrame({COL_DESCR: DESCRIPTIONS}), classes, n_clusters=3)

    assert classes.isna().all()


def test_zero_clusters_turns_it_off():
    assert auto(DESCRIPTIONS, n_clusters=0).isna().all()


def test_k_capped_at_distinct_descriptions(caplog):
    got = auto(['A B C', 'A B C', 'X Y Z'], n_clusters=5)

    assert got.nunique() == 2
    assert 'Only 2 distinct' in caplog.text


def test_numbered_by_size_zero_padded():
    # 10 clusters: names sort alphabetically in size order ([a01] .. [a10])
    descriptions = [f'WORD{chr(65 + i)} THING{chr(65 + i)}' for i in range(10)] + ['WORDA THINGA'] * 3

    got = auto(descriptions, n_clusters=10)

    assert got[0].startswith('[a01] ')  # the largest cluster
    assert sorted({re.match(r'\[a\d+\]', c).group() for c in got}) == [f'[a{i:02d}]' for i in range(1, 11)]


@pytest.mark.parametrize('k, n, name', [(9, 3, '[a3] x'), (10, 3, '[a03] x'), (100, 3, '[a003] x'),
                                         (100, 100, '[a100] x'), (1000, 42, '[a0042] x')])
def test_name_padding(k, n, name):
    assert auto_class_name(n, k, ['x']) == name


def test_short_words_never_name_a_class():
    assert set(auto(['BONIFICO DEL CRO PER', 'BONIFICO DEL CRO CON'], n_clusters=1)) == {'[a1] bonifico'}


def test_no_words_only_numbers():
    assert set(auto(['123 456', '789 012'], n_clusters=2)) == {'[a1]', '[a2]'}


def test_seed_is_kmeans_random_state(monkeypatch):
    seeds = []
    from sklearn import cluster
    real = cluster.KMeans
    monkeypatch.setattr(cluster, 'KMeans', lambda **kw: seeds.append(kw['random_state']) or real(**kw))

    auto(DESCRIPTIONS, n_clusters=3, seed=7)

    assert seeds == [7]


def test_cluster_merged_custom_rules_first(write_csv, write_classes):
    write_csv('a.csv', [('2025-01-02', -1.0, None, d) for d in DESCRIPTIONS])
    write_classes(['*,*,*,esselunga,food'])

    df = cluster_merged(load_data(), n_clusters=2)

    got = dict(zip(df[COL_DESCR], df[COL_CLASS]))
    assert got['PAGAMENTO POS ESSELUNGA'] == 'food'
    assert CLASS_TODO not in got.values()
    assert {c for d, c in got.items() if d != 'PAGAMENTO POS ESSELUNGA'} <= set(auto(DESCRIPTIONS[1:], n_clusters=2))


def test_cluster_merged_zero_clusters_leaves_todo(write_csv):
    write_csv('a.csv', [('2025-01-02', -1.0, None, d) for d in DESCRIPTIONS])

    assert set(cluster_merged(load_data(), n_clusters=0)[COL_CLASS]) == {CLASS_TODO}


def test_defaults_match_classes_ui():
    """etica's defaults (driver, notebook) are the GUI's: the spin box values in classes.ui."""
    ui = (Path(etica.__file__).parent / 'ui' / 'classes.ui').read_text()

    def spin_value(name):
        return int(re.search(rf'name="{name}">\s*<property name="value">\s*<number>(\d+)</number>', ui).group(1))

    assert (spin_value('qsb_settings_classes_num'), spin_value('qsb_settings_seed')) == (AUTO_N_CLUSTERS, AUTO_SEED)


def test_embeddings_are_cached(monkeypatch):
    """The real embed_texts() encodes each distinct text once, ever."""
    encoded = []

    class FakeModel:
        def encode(self, texts, **kwargs):
            encoded.append(list(texts))
            return [[float(len(t)), 1.0] for t in texts]

    monkeypatch.undo()  # the real embed_texts, not conftest's fake
    monkeypatch.setattr(etica, '_auto_model', FakeModel())
    monkeypatch.setattr(etica, '_auto_embeddings', {})

    first = etica.embed_texts(['a', 'bb', 'a'])
    second = etica.embed_texts(['bb', 'ccc'])

    assert encoded == [['a', 'bb'], ['ccc']]
    assert first.tolist() == [[1.0, 1.0], [2.0, 1.0], [1.0, 1.0]]
    assert second.tolist() == [[2.0, 1.0], [3.0, 1.0]]
