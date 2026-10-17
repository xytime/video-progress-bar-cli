"""CIA 误匹配回归：两条生产公开元数据、真实缩写保护、持久原因重评。"""
import hashlib
import json
from pathlib import Path

import pytest

from config.settings import settings
from tests.topic_candidate_fixtures import tracker, run, video
from video_processing import censor_engine as censor
from video_processing.core.topic_candidates import eligibility
from video_processing.scoring import compute_policy_score
from video_processing.utils.topic_search import ExistingTopicRules


CASES = json.loads((Path(__file__).parents[1] / 'fixtures/topic_cia_regression.json').read_text())


@pytest.mark.parametrize('text', [
    'diferencias', 'oficial', 'ciencia', 'ciência', 'evidencia', 'referências',
    'sequenciamento', 'social', 'especial', 'c i actual', 'éCIA', 'CIAção',
    'cia_foo', 'CIA2', 'c\u0301ia',
])
def test_latin_word_substrings_are_not_cia(text):
    assert not censor.check_channel_policy(zh_text=text, en_text=text).hit
    assert not any(r['term'] == 'CIA' for r in censor.scan_all_matches(text, text))


@pytest.mark.parametrize('text', [
    'CIA', 'cia', '(CIA)', '美国CIA调查', '美国ＣＩＡ调查', 'C I A', 'C\tI\nA',
    '美国Ｃ　Ｉ　Ａ调查', 'oficial, but CIA investigation', 'CIA/中情局',
])
def test_real_cia_and_existing_obfuscation_stay_blocked(text):
    result = censor.check_channel_policy(zh_text=text, en_text=text)
    assert result.hit and result.level == 'CP' and result.matched == 'CIA'
    assert any(r['term'] == 'CIA' and r['layer'] == 'CP' for r in censor.scan_all_matches(text, text))


@pytest.mark.parametrize('case,score', zip(CASES, (82, 85)))
def test_exact_candidates_pass_metadata_without_whitelist(case, score):
    meta = case['metadata']
    assert ExistingTopicRules().check(meta) is None
    assert eligibility(meta, ExistingTopicRules().check, {}, 180)[0] == 'CHECKABLE'
    assert compute_policy_score(dict(view_count=meta['views'], like_count=meta['likes'],
                                    channel_id=meta['channel_id']), settings) == score
    assert eligibility(meta, ExistingTopicRules().check, {'channel_blocked': True}, 180)[0] == 'RESTRICTED'
    assert eligibility({**meta, 'duration': 179}, ExistingTopicRules().check, {}, 180)[0] == 'RESTRICTED'
    assert eligibility({**meta, 'duration': 1801}, ExistingTopicRules().check, {}, 180)[0] == 'RESTRICTED'
    assert ExistingTopicRules().check({**meta, 'title': '法轮功'}).startswith('P0')


def test_reason_is_actual_field_original_excerpt_and_version():
    rules = ExistingTopicRules()
    description = 'oficial ' + 'x' * 300 + ' 美国Ｃ Ｉ Ａ调查 <img onerror=alert(1)>'
    reason = rules.check(dict(title='健康科学', description=description))
    assert reason.startswith('CP / 频道内容策略')
    assert '命中词：CIA' in reason and '来源：原始描述' in reason
    assert 'Ｃ Ｉ Ａ' in reason and 'oficial' not in reason
    assert '规则版本：' + rules.version() in reason
    assert len(reason) < 300
    title_reason = rules.check(dict(title='美国CIA调查', description='普通说明'))
    assert '来源：标题' in title_reason and '原始描述' not in title_reason


def test_cross_field_cooccurrence_keeps_combined_check():
    reason = ExistingTopicRules().check(dict(title='伊朗', description='战争'))
    assert '跨字段共现' in reason and '伊朗' in reason and '战争' in reason


def test_matcher_revision_invalidates_previous_rule_fingerprint():
    bl, cp = censor._load_external_rules()
    old = hashlib.sha256(json.dumps(dict(blocklist=bl, channel_policy=cp), ensure_ascii=False,
                                   sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:16]
    assert ExistingTopicRules().version() != old


def test_cached_false_restriction_rechecks_without_request(tracker):
    tracker.rules.hit = 'CP / 🚫 频道策略限制'
    run(tracker)
    old = tracker.candidates()['candidates'][0]
    calls = list(tracker.adapter.calls)
    tracker.rules = ExistingTopicRules()
    current = tracker.candidates()['candidates'][0]
    stored = tracker.db.topic_candidate(current['key'])
    assert old['eligibility'] == 'RESTRICTED'
    assert current['eligibility'] == stored['eligibility'] == 'CHECKABLE'
    assert current['content_version'] != old['content_version']
    assert stored['rule_version'] == tracker.rules.version()
    assert calls == tracker.adapter.calls


def test_corrected_candidate_uses_normal_automatic_admission(tracker, monkeypatch):
    from tests.unit.test_keyword_collection import enable, admit
    tracker.rules = ExistingTopicRules()
    item = video(title='La posición oficial: ciencia y diferencias')
    item['statistics'] = dict(viewCount='3416', likeCount='110')
    tracker.adapter.items = [item]
    enable(tracker)
    admit(tracker, monkeypatch)
    assert tracker.tick(verify_runtime=False) == 'SEARCH'
    tracker.tick(verify_runtime=False)
    main = tracker.db.get_video_by_youtube_id(item['id'])
    ledger = tracker.db.keyword_admission_ledger()
    assert main['source'] == 'KEYWORD' and main['score'] == 82
    assert len(ledger) == 1 and ledger[0]['video_id'] == main['id']
    assert not main['is_manually_scored']
