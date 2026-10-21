"""独立英语世界商品正式登记、清单传播及发布契约的真实 DAL 测试。"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from scripts import register_english_world_product as registrar
from scripts import english_world_programmatic_daily as programmatic
from scripts import run_english_world_daily as coordinator
from scripts import submit_english_world_review as submitter
from video_processing.db.database import PipelineDB
from video_processing.english_world.product_production import (
    attach_product_context_to_manifest, production_task_id, start_product_production,
    verify_product_production_context,
)
from video_processing.english_world.package_integrity import calculate_package_hashes
from video_processing.utils.wechat_product_task import product_profile_scope, read_product_task_decision
from video_processing.utils.wechat_product_execution import product_artifacts_digest, product_observation_generation
from video_processing.utils.wechat_product_waits import ProductWaitStore


def source(start=0, end=40):
    return {'content_type': 'ENGLISH_WORLD_SHORT', 'translation_zh': '来源预检中',
            'paragraphs': [{'translation_zh': '来源预检中'}],
            'source_provenance': {'youtube_id': 'Abcdef12345', 'channel_id': 'source-channel',
                                  'source_start_seconds': start, 'source_end_seconds': end,
                                  'view_count': 1000, 'like_count': 1}}


def policy(path):
    path.write_bytes((Path(__file__).resolve().parents[1] / 'fixtures/wechat_products_v2.json').read_bytes())
    return path


def test_stable_identity_normalizes_numeric_bounds_but_separates_source_slices():
    assert production_task_id(source(0, 40)) == production_task_id(source('0.0', '40.000'))
    assert production_task_id(source(0, 40)) != production_task_id(source(40, 80))
    for start, end in [(True, 40), (0, float('nan')), (-1, 40), (40, 40)]:
        with pytest.raises(ValueError, match='区间'):
            production_task_id(source(start, end))


def test_only_auto_formal_production_counts_and_retry_preserves_business_day(tmp_path):
    db = PipelineDB(str(tmp_path / 'pipeline.db'))
    before_midnight = datetime(2026, 10, 10, 15, 59, tzinfo=timezone.utc)
    none = start_product_production(db, source(), product_intent='NONE', now=before_midnight)
    assert db.get_product_production(none['product_context']['task_id']) is None
    assert verify_product_production_context(db, none)['product_intent'] == 'NONE'
    first = start_product_production(db, source(40, 80), now=before_midnight)
    second = start_product_production(db, source(80, 120), now=before_midnight)
    assert first['product_production']['is_first'] is True
    assert second['product_production']['is_first'] is False
    resumed = start_product_production(db, deepcopy(first), now=before_midnight + timedelta(minutes=2))
    assert resumed == first
    next_day = start_product_production(db, source(120, 160), now=before_midnight + timedelta(minutes=2))
    assert next_day['product_production']['is_first'] is True
    assert next_day['product_production']['business_day'] == '2026-10-11'


@pytest.mark.parametrize('field,value', [('translation_zh', '已经开始翻译'),
                                      ('learning_points', [{'word': 'done'}]),
                                      ('publication_text', {'title': '完成包'})])
def test_no_retroactive_registration_of_old_enriched_or_finished_packages(tmp_path, field, value):
    db = PipelineDB(str(tmp_path / 'pipeline.db'))
    payload = dict(source(), **{field: value})
    with pytest.raises(ValueError, match='翻译或词汇富化前'):
        start_product_production(db, payload)
    assert db.get_product_production(production_task_id(payload)) is None


def test_manifest_cannot_claim_another_slice_or_invent_first_record(tmp_path):
    db = PipelineDB(str(tmp_path / 'pipeline.db'))
    registered = start_product_production(db, source())
    changed = deepcopy(registered)
    changed['source_provenance']['source_end_seconds'] = 45
    with pytest.raises(ValueError, match='实际来源片段'):
        verify_product_production_context(db, changed)
    changed = deepcopy(registered)
    changed['product_production']['is_first'] = False
    with pytest.raises(ValueError, match='登记缺失或与清单不一致'):
        verify_product_production_context(db, changed)
    changed = deepcopy(registered)
    changed['product_context']['product_intent'] = 'NONE'
    changed.pop('product_production')
    with pytest.raises(ValueError, match='不得占用自动'):
        verify_product_production_context(db, changed)
    with pytest.raises(ValueError, match='正式制作商品上下文'):
        verify_product_production_context(db, source())


def test_daily_first_scopes_follow_actual_uploader_state_path(tmp_path):
    db = PipelineDB(str(tmp_path / 'pipeline.db'))
    state_a, state_b = tmp_path / 'a/state.json', tmp_path / 'b/state.json'
    now = datetime(2026, 10, 11, 2, tzinfo=timezone.utc)
    first_a = start_product_production(db, source(), state_path=state_a, now=now)
    later_a = start_product_production(db, source(40, 80), state_path=state_a, now=now)
    first_b = start_product_production(db, source(80, 120), state_path=state_b, now=now)
    assert first_a['product_production']['account_id'] == product_profile_scope(state_a)
    assert first_a['product_production']['is_first'] is True
    assert later_a['product_production']['is_first'] is False
    assert first_b['product_production']['is_first'] is True
    assert first_b['product_production']['account_id'] != first_a['product_production']['account_id']
    assert verify_product_production_context(db, first_a, state_path=state_a)
    with pytest.raises(ValueError, match='实际发布会话范围'):
        verify_product_production_context(db, first_a, state_path=state_b)
    with pytest.raises(ValueError, match='实际发布会话范围'):
        start_product_production(db, first_a, state_path=state_b)
    assert not state_a.exists() and not state_b.exists()


def test_first_and_later_publishers_receive_frozen_decision_independent_of_like_rate(tmp_path, monkeypatch):
    db = PipelineDB(str(tmp_path / 'pipeline.db'))
    monkeypatch.setattr(submitter.settings, 'wechat_product_policy_path', policy(tmp_path / 'products.json'))
    now = datetime(2026, 10, 11, 2, tzinfo=timezone.utc)
    for index, expected in enumerate(('ATTACH_ENGLISH_ALL', 'ATTACH_ENGLISH_ALL')):
        timeline = source(index * 40, (index + 1) * 40)
        if index:
            timeline['source_provenance']['like_count'] = 200
        registered = start_product_production(db, timeline, now=now)
        manifest = tmp_path / f'video{index}.manifest.json'
        manifest.write_text('{"content_type":"ENGLISH_WORLD_SHORT"}', encoding='utf-8')
        attach_product_context_to_manifest(db, registered, manifest)
        item = {'manifest_path': str(manifest), 'manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest(),
                'mp4_path': 'video.mp4', 'copy_path': 'copy.txt', 'title_path': 'title.txt',
                'cover_path': 'cover.jpg', 'cover_provenance_path': 'cover.json'}
        decision = submitter._product_task_decision(db, item)
        assert decision['reason'] == expected
        assert decision['require_product'] is True
        command = submitter._english_world_uploader_command(item, tmp_path / f'evidence{index}',
                                                            product_decision=decision)
        frozen = read_product_task_decision(Path(command[command.index('--product-task-decision') + 1]))
        assert frozen['reason'] == expected
        # 重试不因配置替换而改变曾冻结的首条/后续决定。
        assert submitter._product_task_decision(db, item) == decision


def test_missing_registration_never_rewrites_old_manifest_at_submission(tmp_path):
    db = PipelineDB(str(tmp_path / 'pipeline.db'))
    manifest = tmp_path / 'historical.manifest.json'
    manifest.write_text(json.dumps(source()), encoding='utf-8')
    before = manifest.read_bytes()
    item = {'manifest_path': str(manifest), 'manifest_sha256': hashlib.sha256(before).hexdigest()}
    with pytest.raises(ValueError, match='正式制作商品上下文'):
        submitter._product_task_decision(db, item)
    assert manifest.read_bytes() == before
    assert db.get_product_production(production_task_id(source())) is None


def test_legacy_whitelist_is_exact_review_and_manifest_without_retroactive_slot(tmp_path, monkeypatch):
    db = PipelineDB(str(tmp_path / 'pipeline.db'))
    manifest = tmp_path / 'historical.manifest.json'
    manifest.write_text(json.dumps(source()), encoding='utf-8')
    monkeypatch.setattr(submitter.settings, 'wechat_product_policy_path', policy(tmp_path / 'products.json'))
    raw = manifest.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(db, 'is_legacy_product_review',
                        lambda review_id, sha: (review_id, sha) == ('legacy-item', digest), raising=False)
    item = {'id': 'legacy-item', 'manifest_path': str(manifest), 'manifest_sha256': digest}
    decision = submitter._product_task_decision(db, item)
    assert decision['require_product'] is True and decision['reason'] == 'ATTACH_ENGLISH_ALL'
    assert decision['task_id'] == 'legacy-review:legacy-item'
    assert manifest.read_bytes() == raw and db.get_product_production(production_task_id(source())) is None
    # 只有清单缺 context 才允许白名单；已存在但登记缺失的上下文不可降级。
    invalid = dict(source(), product_context={'product_intent': 'AUTO'})
    manifest.write_text(json.dumps(invalid), encoding='utf-8')
    item['manifest_sha256'] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    monkeypatch.setattr(db, 'is_legacy_product_review', lambda *_args: True)
    with pytest.raises(ValueError, match='实际来源片段'):
        submitter._product_task_decision(db, item)
    # 同一审核 ID 换包，即使审核摘要也被更换，仍无法取得旧迁移资格。
    manifest.write_text(json.dumps(source(40, 80)), encoding='utf-8')
    item['manifest_sha256'] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    monkeypatch.setattr(db, 'is_legacy_product_review',
                        lambda review_id, sha: (review_id, sha) == ('legacy-item', digest))
    with pytest.raises(ValueError, match='正式制作商品上下文'):
        submitter._product_task_decision(db, item)


def test_restarted_database_does_not_allow_new_unregistered_package(tmp_path):
    path = tmp_path / 'pipeline.db'
    PipelineDB(str(path))
    db = PipelineDB(str(path))
    manifest = tmp_path / 'new.manifest.json'
    manifest.write_text(json.dumps(source()), encoding='utf-8')
    item = {'id': 'new-item', 'manifest_path': str(manifest),
            'manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest()}
    with pytest.raises(ValueError, match='正式制作商品上下文'):
        submitter._product_task_decision(db, item)
    assert db.get_product_production(production_task_id(source())) is None


def test_shadow_cli_and_prompt_do_not_occupy_formal_production(tmp_path, monkeypatch):
    def forbidden_db():
        raise AssertionError('预演不能打开正式登记账本')
    monkeypatch.setattr(registrar, 'PipelineDB', forbidden_db)
    assert registrar.main(['--timeline', str(tmp_path / 'not-yet-created.json'), '--shadow-only']) == 0
    assert '不得登记' in coordinator._product_production_prompt(shadow_only=True)
    prompt = coordinator._product_production_prompt(product_intent='NONE')
    assert '首次翻译或词汇富化之前' in prompt and 'register_english_world_product.py' in prompt
    assert '"product_intent": "NONE"' in prompt


@pytest.mark.parametrize('shadow,reject_preflight,intent', [
    (False, False, 'AUTO'), (True, False, 'AUTO'), (False, True, 'AUTO'),
    (False, False, 'NONE'), (False, False, 'PRODUCT'),
])
def test_programmatic_formal_registration_follows_safety_and_precedes_draft_without_counting_preview(
    tmp_path, monkeypatch, shadow, reject_preflight, intent,
):
    from video_processing.study_cards import learning_dictionary
    monkeypatch.setattr(programmatic, 'ROOT', tmp_path)
    candidate = {'youtube_id': 'Abcdef12345'}
    monkeypatch.setattr(programmatic, '_discover_candidates', lambda **_kwargs: [candidate])
    monkeypatch.setattr(programmatic, '_download_candidate',
                        lambda _candidate, workspace: (workspace / 'source.mp4', workspace / 'caption.json3', 0, 40))
    monkeypatch.setattr(programmatic, '_initial_timeline', lambda *_args, **_kwargs: source())

    def source_evidence(timeline):
        programmatic.atomic_json(timeline.parent / 'qa/source_evidence.json', {})

    monkeypatch.setattr(programmatic, '_source_evidence', source_evidence)
    monkeypatch.setattr(programmatic, '_require_new_draft_budget', lambda *_args, **_kwargs: None)
    # 本测试验证首次登记时序；CLI 故障切换由 provider 专项测试覆盖。
    monkeypatch.setattr(programmatic.settings, 'english_world_codex_fallback', False)
    monkeypatch.setattr(programmatic, '_frozen_words', lambda _evidence: [{'text': 'source', 'start': 0, 'end': 40}])

    def safety(*_args, **_kwargs):
        if reject_preflight:
            raise programmatic.ProgrammaticDailyError('preflight rejected')

    monkeypatch.setattr(programmatic, '_candidate_safety_preflight', safety)
    monkeypatch.setattr(learning_dictionary, 'dictionary_word_options', lambda *_args: [])
    monkeypatch.setattr(programmatic, '_stage_call', lambda _stage, _workspace, call, **_kwargs: call())
    monkeypatch.setattr(programmatic, '_run', lambda *_args, **_kwargs: None)
    observed = []

    def provider(*_args, **_kwargs):
        timeline = programmatic.read_json(next((tmp_path / 'out').glob('*/timeline.json')))
        db = PipelineDB(str(tmp_path / 'output/pipeline.db'))
        record = db.get_product_production(production_task_id(timeline))
        if _args[0].startswith("你是英语世界的独立候选安全审核员"):
            assert record is None
            return {"state": "PASS", "coverage": "SUFFICIENT", "risk_categories": []}
        assert bool(record) is (not shadow and intent == 'AUTO')
        assert ('product_context' in timeline) is (not shadow)
        if record:
            assert timeline['product_production'] == record and record['is_first'] is True
        observed.append(True)
        raise programmatic.ProgrammaticDailyError('stop at provider boundary')

    monkeypatch.setattr(programmatic, 'run_agy_structured', provider)
    kwargs = {'product_id': '12345', 'product_title': '精确完整书名'} if intent == 'PRODUCT' else {}
    with pytest.raises(programmatic.ProgrammaticDailyError):
        programmatic.run(request=tmp_path / 'request.json', output_root=tmp_path / 'out',
                         shadow_only=shadow, product_intent=intent, **kwargs)
    assert len(observed) == int(not reject_preflight)
    if reject_preflight:
        assert PipelineDB(str(tmp_path / 'output/pipeline.db')).get_product_production(production_task_id(source())) is None


def test_product_wait_keeps_approval_and_backoff_prevents_another_upload(tmp_path, monkeypatch):
    db = PipelineDB(str(tmp_path / 'pipeline.db'))
    monkeypatch.setattr(submitter, '_PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(submitter, 'PipelineDB', lambda: db)
    monkeypatch.setattr(submitter, '_post_status', lambda *_args: None)
    monkeypatch.setattr(submitter, '_require_publish_package', lambda _item: False)
    monkeypatch.setattr(submitter.settings, 'wechat_publishing_paused', False)
    monkeypatch.setattr(submitter.settings, 'enable_wechat_comment_interaction', False)
    monkeypatch.setattr(submitter.settings, 'wechat_product_policy_path', policy(tmp_path / 'products.json'))
    paths = {}
    for field in ('mp4', 'manifest', 'title', 'copy', 'cover', 'cover_provenance'):
        path = tmp_path / f'{field}.fixture'
        path.write_text(field, encoding='utf-8')
        paths[f'{field}_path'] = str(path)
    manifest = start_product_production(db, source(), state_path=tmp_path / 'output/wechat_state.json')
    Path(paths['manifest_path']).write_text(json.dumps(manifest), encoding='utf-8')
    item = db.create_english_world_review_item(title='商品等待', **paths, **calculate_package_hashes(paths))
    db.approve_english_world_submission(item['id'], authorization='TELEGRAM_REVIEW')
    authorization_expires_at = db.get_english_world_review_item(item['id'])['authorization_expires_at']
    calls = []

    def uploader(command, **_kwargs):
        calls.append(command)
        evidence = Path(command[command.index('--evidence-dir') + 1])
        decision = read_product_task_decision(Path(command[command.index('--product-task-decision') + 1]))
        assert decision['context']['review_id'] == item['id']
        row = ProductWaitStore(tmp_path / 'output/wechat_product_waits.json').defer(
            decision['task_id'], reason='AVAILABILITY_UNVERIFIED', config_digest=decision['config_digest'],
            artifacts_digest=product_artifacts_digest(Path(paths['mp4_path']), Path(paths['copy_path']),
                                                     Path(paths['cover_path'])), submission_state='NOT_SUBMITTED',
            observation_generation=product_observation_generation(submitter.settings.wechat_product_policy_path),
        )
        (evidence / 'product_selection_receipt.json').write_text(json.dumps({
            'required': True, 'binding_confirmed': False, 'state': 'BLOCKED',
            'task_id': decision['task_id'], 'config_digest': decision['config_digest'],
        }), encoding='utf-8')
        (evidence / 'product_wait.json').write_text(json.dumps(dict(row, not_submitted=True)), encoding='utf-8')
        (evidence / 'uploaded_preview.png').write_text('已上传预览但尚未点击发表', encoding='utf-8')
        return type('Result', (), {'returncode': submitter.EXIT_PRODUCT_WAIT, 'stderr': ''})()

    monkeypatch.setattr(submitter.subprocess, 'run', uploader)
    assert submitter.submit(item['id']) == submitter.EXIT_DEFERRED
    saved = db.get_english_world_review_item(item['id'])
    assert saved['state'] == 'SUBMISSION_APPROVED' and saved['platform_post_id'] is None
    assert saved['authorization_expires_at'] == authorization_expires_at
    attempt = db.list_english_world_submission_attempts(item['id'])[0]
    assert attempt['uploader_exit_code'] == 14 and attempt['state'] == 'FAILED'
    assert submitter.submit(item['id']) == submitter.EXIT_DEFERRED
    assert len(calls) == 1 and len(db.list_english_world_submission_attempts(item['id'])) == 1


@pytest.mark.parametrize('mutation', ['missing', 'task_id', 'config_digest', 'binding_confirmed',
                                    'not_submitted', 'submission_state', 'submission_receipt'])
def test_ambiguous_product_wait_cannot_restore_approval(tmp_path, mutation):
    db = PipelineDB(str(tmp_path / 'pipeline.db'))
    paths = {}
    for field in ('mp4', 'manifest', 'title', 'copy', 'cover', 'cover_provenance'):
        path = tmp_path / f'{field}.fixture'
        path.write_text(field, encoding='utf-8')
        paths[f'{field}_path'] = str(path)
    item = db.create_english_world_review_item(title='不明等待', **paths, **calculate_package_hashes(paths))
    db.approve_english_world_submission(item['id'], authorization='AUTO_POLICY')
    evidence = tmp_path / 'evidence'
    evidence.mkdir()
    claimed = db.claim_english_world_submission(item['id'], evidence_dir=str(evidence))
    decision = {'require_product': True, 'task_id': 'task-current', 'config_digest': 'frozen'}
    receipt = {'required': True, 'binding_confirmed': False, 'state': 'BLOCKED',
               'task_id': decision['task_id'], 'config_digest': decision['config_digest']}
    wait = {'not_submitted': True, 'submission_state': 'NOT_SUBMITTED', 'reason': 'PRODUCT_UNAVAILABLE',
            'task_key': decision['task_id'], 'config_digest': decision['config_digest']}
    if mutation in ('task_id', 'config_digest'):
        receipt[mutation] = 'different'
    elif mutation == 'binding_confirmed':
        receipt[mutation] = True
    elif mutation in ('not_submitted', 'submission_state'):
        wait[mutation] = False if mutation == 'not_submitted' else 'UNCERTAIN'
    elif mutation == 'submission_receipt':
        (evidence / 'submission_receipt.json').write_text('{"platform_post_id":"export/existing"}')
    if mutation != 'missing':
        (evidence / 'product_selection_receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
    (evidence / 'product_wait.json').write_text(json.dumps(wait), encoding='utf-8')
    assert not submitter._defer_product_wait(db, item['id'], claimed['_attempt_id'], evidence, decision)
    assert db.get_english_world_review_item(item['id'])['state'] == 'SUBMITTING'


@pytest.mark.parametrize('required,mutation,expected', [
    (True, None, 'UNDER_REVIEW'), (False, None, 'UNCERTAIN'),
    (True, 'missing', 'UNCERTAIN'), (False, 'missing', 'UNCERTAIN'),
    (True, 'actual_product_id', 'UNCERTAIN'), (True, 'actual_title', 'UNCERTAIN'),
    (True, 'task_id', 'UNCERTAIN'), (False, 'task_id', 'UNCERTAIN'),
    (True, 'config_digest', 'UNCERTAIN'), (False, 'unbound_confirmed', 'UNCERTAIN'),
    (False, 'actual_product_id', 'UNCERTAIN'), (True, 'required', 'UNCERTAIN'),
    (True, 'unbound_missing', 'UNCERTAIN'), (True, 'unbound_confirmed', 'UNCERTAIN'),
])
def test_product_receipt_conflicts_preserve_native_id_and_stop_reupload(tmp_path, required, mutation, expected):
    db = PipelineDB(str(tmp_path / 'pipeline.db'))
    paths = {}
    for field in ('mp4', 'manifest', 'title', 'copy', 'cover', 'cover_provenance'):
        path = tmp_path / f'{field}.fixture'
        path.write_text(field, encoding='utf-8')
        paths[f'{field}_path'] = str(path)
    item = db.create_english_world_review_item(title='商品回执测试', **paths, **calculate_package_hashes(paths))
    db.approve_english_world_submission(item['id'], authorization='AUTO_POLICY')
    evidence = tmp_path / 'evidence'
    evidence.mkdir()
    claimed = db.claim_english_world_submission(item['id'], evidence_dir=str(evidence))
    (evidence / 'submission_receipt.json').write_text(json.dumps({
        'matched_by': 'same_session_before_after_unique_post_list_object_id_delta',
        'platform_post_id': 'export/current-product-attempt',
    }), encoding='utf-8')
    (evidence / 'original_declaration_receipt.json').write_text(json.dumps({
        'required': False, 'requested': False, 'applied_in_ui': False, 'ui_state': 'NOT_DECLARED',
    }), encoding='utf-8')
    decision = {'attachment_version': 'wechat-english-all-v1', 'require_product': required, 'task_id': 'english-world:current-task', 'config_digest': 'frozen-digest',
                'product_decision': {'candidates': [{'product_id': '12345', 'title': '完整书名'}]}}
    receipt = {'binding_required': True, 'required': required, 'task_id': decision['task_id'], 'config_digest': decision['config_digest'],
               'binding_confirmed': required, 'unbound_confirmed': not required}
    if required:
        receipt.update(actual_product_id='12345', actual_title='完整书名')
    if mutation == 'unbound_missing':
        receipt.pop('unbound_confirmed')
    elif mutation == 'unbound_confirmed' and required:
        receipt[mutation] = True
    elif mutation not in (None, 'missing'):
        receipt[mutation] = False if mutation in ('required', 'unbound_confirmed') else 'different'
    if mutation != 'missing':
        (evidence / 'product_selection_receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
    state, _ = submitter._record_submission_result(
        db, item['id'], attempt_id=claimed['_attempt_id'], code=6, evidence_dir=evidence,
        require_original_declaration=False, product_decision=decision,
    )
    assert state == expected
    saved = db.get_english_world_review_item(item['id'])
    assert saved['platform_post_id'] == 'export/current-product-attempt' and saved['state'] == expected
    assert db.list_english_world_submission_attempts(item['id'])[0]['platform_post_id'] == saved['platform_post_id']
    assert db.claim_english_world_submission(item['id']) is None
    if expected == 'UNCERTAIN':
        assert db.get_next_english_world_douyin_sync_candidate() is None
