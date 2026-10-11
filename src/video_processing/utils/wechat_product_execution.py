"""发布器消费冻结商品任务：NONE 清空并核验；要求商品只在精确绑定后通过。"""
from __future__ import annotations
from pathlib import Path
from time import monotonic
import time
import hashlib
from video_processing.utils.wechat_product_config import atomic_json, record_adoption
from video_processing.utils.wechat_product_task import selection_from_task
from video_processing.utils.wechat_product_selection import select_required_product, _Deadline
from video_processing.utils.wechat_product_waits import ProductWaitStore


def product_artifacts_digest(video: Path, copy: Path, cover: Path) -> str:
    digest = hashlib.sha256()
    for role, path in (('video', video), ('copy', copy), ('cover', cover)):
        digest.update(role.encode())
        with Path(path).open('rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block)
    return digest.hexdigest()


def product_observation_generation(active: Path) -> str:
    digest = hashlib.sha256()
    for path in (active, active.with_name('wechat_product_catalog.json')):
        digest.update(path.name.encode())
        digest.update(path.read_bytes() if path.exists() else b'MISSING')
    return digest.hexdigest()


def product_wait_ready(payload: dict, output: Path, artifacts_digest: str, *, clock=time.time,
                       observation_generation: str | None = None) -> bool:
    """只读退避检查；已有受理状态由外层原有领取/去重门禁处理。"""
    row = next((r for r in ProductWaitStore(output / 'wechat_product_waits.json').records()
                if r['task_key'] == payload['task_id']), None)
    if payload.get('selection_block_reason'):
        return False
    if row is None:
        return True
    if row['artifacts_digest'] != artifacts_digest or row['state'] in {'BLOCKED', 'VERIFY_SUBMISSION'}:
        return False
    if row['submission_state'] != 'NOT_SUBMITTED' or row['lease_until'] > clock():
        return False
    if row['state'] == 'READY_FOR_EXISTING_GATES':
        return True
    if observation_generation and observation_generation != row.get('observed_generation'):
        return True
    if row['state'] == 'CHECK_LIMIT':
        return False
    return row['submission_state'] == 'NOT_SUBMITTED' and row['lease_until'] <= clock() and row['next_check_at'] <= clock()


def product_task_preflight(payload: dict, output: Path, artifacts_digest: str, *,
                           observation_generation: str | None = None) -> bool:
    """确定尚未开浏览器时记录身份阻断；不修改业务快照或替换人工商品。"""
    reason = payload.get('selection_block_reason')
    if reason:
        store = ProductWaitStore(output / 'wechat_product_waits.json')
        old = next((r for r in store.records() if r['task_key'] == payload['task_id']), None)
        if old is None:
            policy, _ = selection_from_task(payload)
            import json
            store.defer(payload['task_id'], reason=reason, config_digest=payload['config_digest'],
                        artifacts_digest=artifacts_digest, submission_state='NOT_SUBMITTED',
                        wait_policy=json.loads(policy.serialized).get('wait_policy'),
                        observation_generation=observation_generation)
        return False
    return product_wait_ready(payload, output, artifacts_digest, observation_generation=observation_generation)


def blocked_product_task_keys(output: Path, active: Path, *, clock=time.time) -> list[str]:
    """遍历整个等待账本后交给 DAL 在 LIMIT 前排除，避免队首等待饿死后续。"""
    generation = product_observation_generation(active)
    blocked = []
    for row in ProductWaitStore(output / 'wechat_product_waits.json').records():
        if row['state'] == 'READY_FOR_EXISTING_GATES':
            continue
        changed = generation != row.get('observed_generation')
        if (row['submission_state'] != 'NOT_SUBMITTED' or row['state'] in {'BLOCKED', 'VERIFY_SUBMISSION'}
                or row['lease_until'] > clock()
                or (not changed and (row['state'] == 'CHECK_LIMIT' or row['next_check_at'] > clock()))):
            blocked.append(row['task_key'])
    return blocked


def _wait_reason(result):
    if result.reason == 'DEFAULT_PRODUCT_NOT_BOUND' and result.attempt_records and all(r['outcome'] == 'TARGET_UNAVAILABLE' for r in result.attempt_records):
        return 'PRODUCT_UNAVAILABLE'
    if result.reason in {'PRODUCT_OPERATION_TIMEOUT', 'PRODUCT_SELECTION_BUDGET_EXHAUSTED', 'FORM_NOT_READY'}:
        return 'AVAILABILITY_UNVERIFIED'
    return result.reason


def _record_product_wait(payload, result, evidence_dir, output, artifacts_digest, generation):
    reason = _wait_reason(result)
    policy, _ = selection_from_task(payload)
    import json
    configured = json.loads(policy.serialized)
    row = ProductWaitStore(output / 'wechat_product_waits.json').defer(
        payload['task_id'], reason=reason, config_digest=payload['config_digest'],
        artifacts_digest=artifacts_digest, submission_state='NOT_SUBMITTED', wait_policy=configured.get('wait_policy'),
        observation_generation=generation)
    atomic_json(evidence_dir / 'product_wait.json', dict(row, not_submitted=True))


def verify_product_before_submit(payload: dict, picker) -> bool:
    """遮罩/声明操作结束后最后一次回读，不进行选择或补挂。"""
    try:
        binding = picker.read_binding(timeout_ms=3000)
        if not picker.ready_to_submit(timeout_ms=3000):
            return False
        if payload['require_product'] is False:
            return binding is None and picker.read_binding(timeout_ms=3000) is None
        _, decision = selection_from_task(payload)
        return binding in decision.candidates and picker.read_binding(timeout_ms=3000) == binding
    except Exception:
        return False


def record_pre_submit_product_block(payload: dict, evidence_dir: Path, status_path: Path,
                                    output: Path, artifacts_digest: str, reason: str) -> None:
    """仅由明确尚未点击发表的分支调用；不可把已受理或不明结果回队。"""
    if (evidence_dir / 'submission_receipt.json').exists():
        raise ValueError('已有提交回执，必须先核验原作品')
    from types import SimpleNamespace
    _record_product_wait(payload, SimpleNamespace(reason=reason, attempt_records=()),
                         evidence_dir, output, artifacts_digest, payload.get('_observation_generation'))
    receipt = dict(required=True, binding_confirmed=False, unbound_confirmed=False, state='BLOCKED',
                   phase='BLOCKED', reason=reason, task_id=payload['task_id'],
                   config_version=payload['config_version'], config_digest=payload['config_digest'],
                   publisher_capability=payload['publisher_capability'])
    atomic_json(evidence_dir / 'product_selection_receipt.json', receipt)
    atomic_json(evidence_dir / 'product_policy_adoption.json', receipt)
    atomic_json(status_path, receipt)


def execute_product_task(payload: dict, picker, evidence_dir: Path, status_path: Path, *, clock=monotonic,
                         wait_output: Path | None = None, artifacts_digest: str | None = None) -> bool:
    generation = payload.get('_observation_generation')
    atomic_json(evidence_dir / 'product_task_decision.json', payload)
    if payload['require_product'] is True:
        policy, decision = selection_from_task(payload)
        if payload.get('selection_block_reason'):
            if wait_output is not None and artifacts_digest:
                product_task_preflight(payload, wait_output, artifacts_digest, observation_generation=generation)
            atomic_json(evidence_dir / 'product_selection_receipt.json', dict(required=True,
                binding_confirmed=False, unbound_confirmed=False, state='BLOCKED', reason=payload['selection_block_reason'],
                task_id=payload['task_id'], config_digest=payload['config_digest']))
            return False
        check = None
        if wait_output is not None and artifacts_digest:
            store = ProductWaitStore(wait_output / 'wechat_product_waits.json')
            old = next((r for r in store.records() if r['task_key'] == payload['task_id']), None)
            if old and old['state'] != 'READY_FOR_EXISTING_GATES':
                check = store.claim_check(payload['task_id'], current_config_digest=payload['config_digest'],
                                          current_artifacts_digest=artifacts_digest, observation_generation=generation)
                if check is None:
                    atomic_json(evidence_dir / 'product_selection_receipt.json', dict(required=True,
                        binding_confirmed=False, unbound_confirmed=False, state='BLOCKED', reason='PRODUCT_WAIT_BACKOFF',
                        task_id=payload['task_id'], config_digest=payload['config_digest']))
                    atomic_json(evidence_dir / 'product_wait.json', dict(old, not_submitted=True))
                    return False
        record_adoption(policy, decision, evidence_dir, status_path, phase='STARTED', task_decision=payload)
        result = select_required_product(decision=decision, picker=picker,
                                         timeout_seconds=decision.timeout_seconds, clock=clock)
        receipt = dict(required=True, binding_confirmed=result.binding_confirmed, unbound_confirmed=False, state=result.state,
                       reason=result.reason, actual_product_id=result.actual.product_id if result.actual else None,
                       actual_title=result.actual.title if result.actual else None,
                       requested_product_id=result.requested.product_id, requested_title=result.requested.title,
                       attempts=result.attempts, fallback_reason=result.fallback_reason,
                       config_version=policy.version, config_digest=policy.digest,
                       task_id=payload['task_id'], attachment_reason=payload['reason'])
        atomic_json(evidence_dir / 'product_selection_receipt.json', receipt)
        record_adoption(policy, decision, evidence_dir, status_path, phase=result.state, result=result, task_decision=payload)
        if wait_output is not None and artifacts_digest:
            if check:
                reason = _wait_reason(result)
                store.finish_check(payload['task_id'], check['lease_token'], available=result.binding_confirmed, reason=reason)
            if not result.binding_confirmed:
                _record_product_wait(payload, result, evidence_dir, wait_output, artifacts_digest, generation)
        return result.binding_confirmed
    if payload['require_product'] is not False:
        raise ValueError('未知商品决定不能默认跳过')
    budget = _Deadline(10, clock)
    try:
        current = picker.read_binding(timeout_ms=budget.remaining_ms())
        if current is not None:
            if not picker.cancel_and_clear(timeout_ms=budget.remaining_ms()):
                raise ValueError('CANNOT_CONFIRM_CLEARED')
        if picker.read_binding(timeout_ms=budget.remaining_ms()) is not None:
            raise ValueError('RESIDUAL_LINK_AFTER_CANCEL')
        if not picker.ready_to_submit(timeout_ms=budget.remaining_ms()):
            raise ValueError('FORM_NOT_READY')
        if picker.read_binding(timeout_ms=budget.remaining_ms()) is not None:
            raise ValueError('BINDING_CHANGED_BEFORE_SUBMIT')
        budget.remaining_ms()
    except Exception as exc:
        atomic_json(evidence_dir / 'product_selection_receipt.json', {
            'required': False, 'binding_confirmed': False, 'unbound_confirmed': False,
            'state': 'BLOCKED', 'reason': type(exc).__name__, 'task_id': payload['task_id']})
        return False
    receipt = dict(required=False, binding_confirmed=False, unbound_confirmed=True, state='SKIPPED',
                   reason=payload['reason'], task_id=payload['task_id'], config_digest=payload.get('config_digest'),
                   config_version=payload.get('config_version'), publisher_capability=payload['publisher_capability'])
    atomic_json(evidence_dir / 'product_selection_receipt.json', receipt)
    atomic_json(evidence_dir / 'product_policy_adoption.json', dict(receipt, phase='SKIPPED', context=payload['context']))
    atomic_json(status_path, dict(receipt, phase='SKIPPED', context=payload['context']))
    return True
