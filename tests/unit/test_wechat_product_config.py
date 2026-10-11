"""配置激活、不可变快照与真实采用记录的隔离回归。"""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import pytest
from video_processing.core.wechat_product_policy import parse_product_policy
from video_processing.utils.wechat_product_config import load_policy, activate_policy, record_adoption, policy_status
from video_processing.utils.wechat_product_selection import select_required_product
from tests.unit.test_wechat_product_selection import FakePicker
from scripts import wechat_product_config as cli

SEED = Path(__file__).resolve().parents[2] / 'tests/fixtures/wechat_products_v2.json'

@pytest.fixture
def data():
    data = json.loads(SEED.read_text())
    legacy_channel = data['profiles']['wallstreet']
    data['rules'].insert(0, {'id':'wallstreet', 'kind':'channel', 'values':legacy_channel['channel_ids'], 'candidates':legacy_channel['candidates'], 'role':'finance'})
    data.pop('profiles'); data['schema_version'] = 1; data['max_attempts'] = 2
    return data


def test_priority_and_deterministic_fallback(data):
    p = parse_product_policy(data)
    kw = dict(category='新闻', source_channel_id='UCTK_cv-y88CScoudcXnS1Ew')
    assert p.decide(**kw).reason == 'wallstreet'
    assert p.decide(**kw, product_alias='news').candidates[0] == p.products['news'].identity
    assert p.decide(category='资讯').reason == 'news'
    assert p.decide(category='财经/新闻').reason == 'DEFAULT'
    assert p.decide(category='新闻').candidates[-1] == p.products['default'].identity
    with pytest.raises(ValueError):
        p.decide(product_alias='missing')


def test_alias_sharing_and_id_dedup(data):
    data['products']['shared'] = deepcopy(data['products']['default'])
    data['rules'][0]['candidates'] = ['shared', 'default']
    assert len(parse_product_policy(data).decide(source_channel_id='UCTK_cv-y88CScoudcXnS1Ew').candidates) == 1
    data['products']['shared']['title'] = '矛盾版本'
    with pytest.raises(ValueError):
        parse_product_policy(data)


@pytest.mark.parametrize('field,value', [('schema_version',True),('schema_version',2),('timeout_seconds',61),('timeout_seconds',float('nan')),('timeout_seconds',True),('max_attempts',4),('max_attempts',1),('max_attempts',True),('default_candidates',[]),('default_candidates',['missing']),('rules',None)])
def test_invalid_config_rejected(data, field, value):
    data[field] = value
    with pytest.raises(ValueError):
        parse_product_policy(data)


def test_disabled_defaults_conflicting_rules_and_wrong_types(data):
    for mutate in (
        lambda d: d['products']['default'].update(enabled=False),
        lambda d: d['rules'].append(dict(d['rules'][1], id='conflict')),
        lambda d: d['rules'][0].update(kind=[]),
        lambda d: d.update(unrecognized=True),
    ):
        copy = deepcopy(data); mutate(copy)
        with pytest.raises(ValueError):
            parse_product_policy(copy)


def test_atomic_update_freezes_inflight_snapshot_and_invalid_keeps_old(tmp_path, data):
    active, candidate = tmp_path/'active.json', tmp_path/'candidate.json'
    candidate.write_text(json.dumps(data)); old = activate_policy(candidate, active)
    data['version'] = 'new'
    data['default_candidates'] = ['news']
    candidate.write_text(json.dumps(data)); new = activate_policy(candidate, active)
    assert old.decide().candidates[0].product_id != load_policy(active).decide().candidates[0].product_id
    assert old.version != new.version and old.digest != new.digest
    before = active.read_bytes()
    data['default_candidates'] = ['missing']; candidate.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        activate_policy(candidate, active)
    assert active.read_bytes() == before
    with pytest.raises(TypeError):
        old.products['anything'] = old.products['default']


def test_duplicate_json_and_missing_file_block(tmp_path):
    p = tmp_path/'active.json'
    with pytest.raises(FileNotFoundError): load_policy(p)
    p.write_text('{"version":"a","version":"b"}')
    with pytest.raises(ValueError, match='重复'): load_policy(p)


def test_three_attempts_and_reasons_are_recorded(data):
    data['max_attempts'] = 3
    data['default_candidates'] = ['news','default']
    p = parse_product_policy(data); decision = p.decide(category='财经')
    picker = FakePicker([p.products['default'].identity])
    result = select_required_product(decision=decision, picker=picker, clock=picker.clock)
    assert result.binding_confirmed and result.attempts == 3
    assert [r['outcome'] for r in result.attempt_records] == ['TARGET_UNAVAILABLE','TARGET_UNAVAILABLE','BOUND']
    assert result.actual == decision.candidates[-1]


def test_preview_does_not_mark_runtime_adopted(tmp_path, monkeypatch, capsys):
    status = tmp_path/'status.json'; monkeypatch.setattr(cli.settings, 'wechat_product_status_path', status)
    assert cli.main(['--config',str(SEED),'preview','--category','财经']) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview['preview_only'] and preview['platform_availability'] == 'NOT_VERIFIED'
    assert not status.exists()
    assert not policy_status(SEED,status)['adopted_by_last_selection']
    p = load_policy(SEED)
    record_adoption(p,p.decide(),tmp_path/'evidence',status,phase='STARTED')
    assert policy_status(SEED,status)['adopted_by_last_selection']
    payload=json.loads(status.read_text()); payload['config_digest']='old'; status.write_text(json.dumps(payload))
    assert not policy_status(SEED,status)['adopted_by_last_selection']


def test_preview_video_sidecars_and_manual_override(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, 'ROOT', tmp_path)
    (tmp_path/'output').mkdir()
    (tmp_path/'output/test_category.txt').write_text('新闻')
    (tmp_path/'output/test.info.json').write_text('{"channel_id":"UCTK_cv-y88CScoudcXnS1Ew"}')
    assert cli.main(['--config',str(SEED),'preview','--video-id','test','--product-alias','news']) == 0
    result=json.loads(capsys.readouterr().out)
    assert result['matched_rule']=='MANUAL' and result['context']['category']=='新闻'
    assert cli.main(['--config',str(SEED),'preview','--video-id','../../etc']) == 2


def test_receipt_includes_policy_digest_and_attempts(tmp_path):
    from scripts.wechat_uploader import _write_product_selection_receipt
    p=load_policy(SEED); decision=p.decide(category='财经')
    picker=FakePicker([decision.candidates[-1]])
    result=select_required_product(decision=decision,picker=picker,clock=picker.clock)
    _write_product_selection_receipt(tmp_path,required=True,result=result)
    receipt=json.loads((tmp_path/'product_selection_receipt.json').read_text())
    assert receipt['policy']['config_digest']==p.digest
    assert receipt['attempt_records'][0]['outcome']=='TARGET_UNAVAILABLE'
    assert receipt['binding_identity_source']=='FORM_DOM_ACTUAL_ID_AND_TITLE'


def test_invalid_apply_reports_retained_version(tmp_path, data, capsys):
    active=tmp_path/'active.json'; active.write_text(json.dumps(data))
    candidate=tmp_path/'bad.json'; candidate.write_text('{}')
    assert cli.main(['--config',str(active),'apply',str(candidate)]) == 2
    result=json.loads(capsys.readouterr().err)
    assert result['active_version']==data['version'] and result['activated'] is False


def test_submission_receipt_links_native_id_to_frozen_policy(tmp_path):
    from scripts.wechat_uploader import _write_submission_receipt
    p=load_policy(SEED); decision=p.decide()
    picker=FakePicker(decision.candidates)
    result=select_required_product(decision=decision,picker=picker,clock=picker.clock)
    native={'platform_post_id':'fictional-native-post'}
    _write_submission_receipt(tmp_path,native,product_result=result)
    receipt=json.loads((tmp_path/'submission_receipt.json').read_text())
    assert receipt['product_config_digest']==p.digest
    assert receipt['form_product_id']==result.actual.product_id
    assert receipt['platform_post_id']==native['platform_post_id']
    assert 'product_config_digest' not in native


@pytest.mark.parametrize("context", [
    {"content_type": "ENGLISH_WORLD_SHORT"},
    {"source_channel_id": "UCTK_cv-y88CScoudcXnS1Ew"},
    {"content_type": "TED"},
    {"product_topic": "AI"},
    {},
])
def test_all_profiles_accept_catalog_product_outside_legacy_three(context):
    data = json.loads(SEED.read_text())
    item = deepcopy(data["products"]["default"])
    item.update(product_id="fictional-catalog-fourth", title="目录新增商品完整名称")
    data["products"]["fourth"] = item
    for profile in data["profiles"].values():
        profile["candidates"] = ["fourth"]
    data["default_candidates"] = ["fourth"]
    policy = parse_product_policy(data)
    decision = policy.decide(**context)
    picker = FakePicker([policy.products["fourth"].identity])
    result = select_required_product(decision=decision, picker=picker, clock=picker.clock)
    assert result.binding_confirmed
    assert result.actual == policy.products["fourth"].identity
    assert result.decision.config_digest == policy.digest
