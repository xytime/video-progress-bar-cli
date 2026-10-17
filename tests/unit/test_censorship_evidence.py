"""审计证据不能改变门禁；回放必须绑定原输入、规则及实际 VTT cue。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-17 | Codex | 锁定历史片段仍拦截、真实词时间、漂移降级及 GET 无写入。 |
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from config.settings import settings
from video_processing import censor_engine
from video_processing.censorship_evidence import blocklist_inputs, review_evidence
from video_processing.censorship_service import CensorshipService
from video_processing.db.database import PipelineDB
from video_processing.utils.file_utils import read_webvtt_cues, read_webvtt_text

FIXTURE = Path(__file__).parents[1] / 'fixtures/censorship/6134-historical-excerpt.vtt'


def evidence_fixture():
    video = dict(title='Pneumonic plague history', zh_title='', description='')
    subtitle = read_webvtt_text([FIXTURE])
    zh, en = blocklist_inputs(**video, subtitle=subtitle)
    result = censor_engine.check_text(zh, en)
    incident = dict(id=203, stage='blocklist', level=result.level, matched=result.matched,
                    channel=result.channel, rule_id='blocklist.P0.en.china_sensitive_negative_news',
                    rule_pack_version=censor_engine.current_rules_fingerprint(), review_stage='source_subtitle_preflight',
                    input_hash=CensorshipService._input_hash(*video.values(), f'{zh}\n{en}'))
    return video, subtitle, incident


def test_historical_hit_stays_p0_and_has_actual_pair_and_times():
    video, subtitle, incident = evidence_fixture()
    assert incident['level'] == 'P0'
    assert incident['matched'] == 'china_sensitive_negative_news'
    evidence = review_evidence(video, [incident], subtitle, [FIXTURE])
    assert evidence['status'] == 'VERIFIED_REPLAY'
    assert [term['actual'] for term in evidence['terms']] == ['China', 'killed']
    assert evidence['gap'] == 87 and evidence['max_gap'] == 240
    assert evidence['terms'][0]['locations'][0]['start'] == '00:06:21.280'
    assert evidence['terms'][1]['locations'][0]['start'] == '00:06:23.699'
    assert '1910' in evidence['context'] and 'pneumonic' in evidence['context']
    # 历史上下文不构成新豁免；混入当代报道也仍按相同规则拦截。
    assert censor_engine.check_text(en_text=subtitle + '\nToday China reported people killed.').level == 'P0'


@pytest.mark.parametrize('change', ['text', 'missing', 'version', 'hash', 'result', 'no_audit'])
def test_changed_or_missing_evidence_never_claims_original_hit(change):
    video, subtitle, incident = evidence_fixture()
    if change == 'text': video['description'] = 'changed'
    if change == 'missing': subtitle = ''
    if change == 'version': incident['rule_pack_version'] = 'old'
    if change == 'hash': incident['input_hash'] = None
    if change == 'result': incident['matched'] = 'other_rule'
    evidence = review_evidence(video, [] if change == 'no_audit' else [incident], subtitle, [FIXTURE])
    assert evidence['status'] == 'UNAVAILABLE'
    assert 'terms' not in evidence and 'context' not in evidence


def test_unknown_timing_is_not_fabricated():
    video, subtitle, incident = evidence_fixture()
    evidence = review_evidence(video, [incident], subtitle)
    assert evidence['status'] == 'VERIFIED_REPLAY'
    assert all(not term['locations'] for term in evidence['terms'])
    assert '不推测' in evidence['timing_note']


@pytest.mark.parametrize('text', ['China reported people killed.', 'Ｃｈｉｎａ\t reported\npeople KILLED.', '中国 事故死亡'])
def test_normalization_and_real_rule_share_identical_spans(text):
    result = censor_engine.check_text(zh_text=text, en_text=text)
    detail = censor_engine.explain_blocklist_hit(text, result)
    assert detail and detail['gap'] <= detail['max_gap']
    assert all(text[left:right] for left, right in detail['raw_spans'])


def test_vtt_truncation_entities_order_and_overlap_remain_unchanged(tmp_path):
    vtt = tmp_path / 'source.vtt'
    vtt.write_text('WEBVTT\n\nSTYLE\nignore\n\n00:00:01.000 --> 00:00:03.000 align:start\n<c>China &amp; people</c>\n\n00:00:02.000 --> 00:00:04.000\nChina &amp; people killed\n\n')
    assert read_webvtt_text([vtt]) == 'China & people\nChina & people killed'
    assert read_webvtt_text([vtt], max_chars=1) == 'China & people'
    assert read_webvtt_cues([vtt])[1]['start'] == '00:00:02.000'
    vtt.write_text('WEBVTT\n\n00:00:01.000 -->\nChina killed\n\n')
    assert read_webvtt_text([vtt]) == 'China killed'
    assert read_webvtt_cues([vtt])[0]['end'] == ''


def test_metadata_hit_does_not_borrow_subtitle_timestamp():
    video, subtitle, _ = evidence_fixture()
    video['title'] = 'China killed people'
    zh, en = blocklist_inputs(**video, subtitle=subtitle)
    result = censor_engine.check_text(zh, en)
    detail = censor_engine.explain_blocklist_hit(en, result)
    assert detail['raw_spans'][0][0] == 0
    incident = dict(id=204, stage='blocklist', level=result.level, matched=result.matched,
                    channel=result.channel, rule_pack_version=censor_engine.current_rules_fingerprint(),
                    input_hash=CensorshipService._input_hash(*video.values(), f'{zh}\n{en}'))
    evidence = review_evidence(video, [incident], subtitle, [FIXTURE])
    assert evidence['status'] == 'VERIFIED_REPLAY'
    assert all(term['source'] == '标题／描述' and not term['locations'] for term in evidence['terms'])


def test_service_new_excerpt_and_readonly_review_do_not_resume(tmp_path, monkeypatch):
    from web import app as web_app
    video, subtitle, _ = evidence_fixture()
    db = PipelineDB(str(tmp_path / 'pipeline.db'))
    db.add_video('evidence-case', video['title'], 'channel', score=85, source='KEYWORD')
    monkeypatch.setattr(settings, 'enable_censorship_engine', True)
    monkeypatch.setattr(settings, 'enable_channel_policy_filter', False)
    monkeypatch.setattr(settings, 'enable_blacklist_tombstone', True)
    assert CensorshipService(db, lambda _: None).check('evidence-case', **video, subtitle_text=subtitle,
                                                    stage='source_subtitle_preflight')
    original = db.get_video_by_youtube_id('evidence-case')
    incidents = db.get_censorship_incidents('evidence-case')
    assert 'China' in incidents[0]['text_excerpt'] and 'killed' in incidents[0]['text_excerpt']
    (tmp_path / 'evidence-case_source_subtitle.en.vtt').write_bytes(FIXTURE.read_bytes())
    monkeypatch.setattr(web_app, 'db', db)
    monkeypatch.setattr(web_app, '_OUT_DIR', tmp_path)
    with TestClient(web_app.app) as client:
        for _ in range(2):
            response = client.get('/api/videos/evidence-case/censor-keywords').json()
            assert response['evidence']['status'] == 'VERIFIED_REPLAY'
    assert db.get_video_by_youtube_id('evidence-case') == original
    assert db.get_censorship_incidents('evidence-case') == incidents
    assert original['status'] == 'FAILED' and original['bypass_censorship'] == 0
    assert db.is_blacklisted('evidence-case')
    assert not db.has_manual_p0_approval('evidence-case')
