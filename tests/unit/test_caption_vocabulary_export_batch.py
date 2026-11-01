"""生词导出使用真实离线词典，验证批量加载与原逐词结果一致。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 复现每词重建词典及全表扫描，验证首现语境、缺词兜底和已有音标词性不变。 |
"""
import csv
import json

import pytest

from video_processing.processors.caption_processor import AutoCaptionProcessor
from video_processing.db.database import PipelineDB
from video_processing.vocabulary import leveler as dictionary


@pytest.fixture
def wordlists(tmp_path):
    root = tmp_path / 'wordlists'
    root.mkdir()
    for name, fields, rows in [
        ('exam-wordlists.csv', ['word', 'pos', 'exam', 'phonetic', 'translation'],
         [['base', 'n.', 'cet4', 'beɪs', 'n. 基础']]),
        ('cefr-enhanced.csv', ['word', 'level', 'exam', 'pos', 'phonetic', 'translation', 'definition'], []),
        ('ecdict.csv', ['word', 'phonetic', 'definition', 'translation', 'pos', 'exchange'], [
            ['zephyr', 'ˈzefə', 'a gentle wind', 'n. 和风', 'n.', ''],
            ['quiescent', 'kwaɪˈesənt', 'at rest', 'adj. 静止的', 'adj.', ''],
            ['obfuscation', 'ɒbfʌˈskeɪʃn', 'obscuring', 'n. 混淆', 'n.', ''],
        ]),
    ]:
        with (root / name).open('w', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(fields)
            writer.writerows(rows)
    return root


def _segments():
    return [dict(start=1, end=5, text='A quiescent zephyr avoids obfuscation.',
                 zh_text='静止的和风避开了混淆。',
                 vocab={'zephyr': '和风', 'quiescent': '静止的', 'obfuscation': '混淆',
                        'unknown phrase': '未知短语'},
                 vocab_phonetics={'zephyr': 'operator IPA'}),
            dict(start=7, end=9, text='A second zephyr.', zh_text='第二阵和风。',
                 vocab={'Zephyr': '后出现的词义'})]


def test_export_batches_real_dictionary_scans_without_changing_values(tmp_path, wordlists, monkeypatch):
    real_leveler = dictionary.VocabularyLeveler
    expected = dict.fromkeys(_segments()[0]['vocab'])
    # 原逐词语义作为独立基线，仍调用真实 leveler 和原词注规范化。
    monkeypatch.setattr(dictionary, 'VocabularyLeveler',
                        lambda **kw: real_leveler(wordlists, **kw))
    for word in expected:
        expected[word] = AutoCaptionProcessor._enrich_single_vocab(
            word, 'operator IPA' if word == 'zephyr' else '', '', None,
            context=_segments()[0]['text'])
    assert expected['quiescent'][0] == 'kwaɪˈesənt'
    assert expected['obfuscation'][1] == 'n.'
    created, scanned = [], []
    real_read = dictionary._read_csv

    def create(**kwargs):
        result = real_leveler(wordlists, **kwargs)
        created.append(result)
        return result

    def read(path):
        scanned.append(path.name)
        yield from real_read(path)

    monkeypatch.setattr(dictionary, 'VocabularyLeveler', create)
    monkeypatch.setattr(dictionary, '_read_csv', read)
    source = tmp_path / 'export_batch.mp4'
    source.touch()
    processor = AutoCaptionProcessor(source)
    result = json.loads(processor.export_vocabulary_json(_segments()).read_text())
    assert [item['word'] for item in result['items']] == list(expected)
    for item in result['items']:
        assert (item['phonetic'], item['pos'], item['level']) == expected[item['word']]
        assert item['meaning_zh'] == _segments()[0]['vocab'][item['word']]
        assert item['start'] == 1 and item['end'] == 5
        assert item['context_sentence'] == _segments()[0]['text']
    assert len(created) == 1
    assert scanned.count('ecdict.csv') == 1
    assert scanned.count('exam-wordlists.csv') == 1
    assert scanned.count('cefr-enhanced.csv') == 1


def test_complete_metadata_does_not_load_dictionary(tmp_path, monkeypatch):
    def reject(**kwargs):
        pytest.fail('完整音标和词性无需扫描词典')
    monkeypatch.setattr(dictionary, 'VocabularyLeveler', reject)
    source = tmp_path / 'metadata_complete.mp4'
    source.touch()
    segments = [dict(start=0, end=1, text='A zephyr.', zh_text='一阵和风。',
                     vocab={'zephyr': '和风'}, vocab_phonetics={'zephyr': 'operator IPA'},
                     vocab_pos={'zephyr': 'n.'}, vocab_levels={'zephyr': 'provided'})]
    result = json.loads(AutoCaptionProcessor(source).export_vocabulary_json(segments).read_text())
    assert result['items'][0]['phonetic'] == 'operator IPA'
    assert result['items'][0]['pos'] == 'n.'
    assert result['items'][0]['level'] == 'provided'


def test_unavailable_dictionary_keeps_export_and_heuristic_fallback(tmp_path, monkeypatch):
    def missing(**kwargs):
        raise FileNotFoundError('offline wordlists absent')
    monkeypatch.setattr(dictionary, 'VocabularyLeveler', missing)
    source = tmp_path / 'missing_dictionary.mp4'
    source.touch()
    segments = [dict(start=0, end=1, text='An unknown phrase.', zh_text='未知短语。',
                     vocab={'unknown phrase': '未知短语'}, vocab_levels={'unknown phrase': 7})]
    result = json.loads(AutoCaptionProcessor(source).export_vocabulary_json(segments).read_text())
    assert result['items'][0]['pos'] == 'phr.'
    assert result['items'][0]['phonetic'] == ''
    assert result['items'][0]['level'] == 7


@pytest.mark.parametrize('stem,slice_index', [('macro_econ', 0), ('macro_econ_s1', 1)])
def test_export_synchronizes_real_database_without_touching_other_slice(tmp_path, stem, slice_index, monkeypatch):
    from video_processing.db import database
    db = PipelineDB(str(tmp_path / 'vocabulary.db'))
    monkeypatch.setattr(database, 'PipelineDB', lambda: db)
    for index in (0, 1):
        assert db.add_video('macro_econ', title='fixture', channel_id='fixture', slice_index=index)
    source = tmp_path / (stem + '.mp4')
    source.touch()
    exported = AutoCaptionProcessor(source).export_vocabulary_json([])
    assert exported and json.loads(exported.read_text())['items'] == []
    assert db.get_vocabulary_json_path('macro_econ', slice_index=slice_index) == str(exported)
    assert not db.get_vocabulary_json_path('macro_econ', slice_index=1-slice_index)
