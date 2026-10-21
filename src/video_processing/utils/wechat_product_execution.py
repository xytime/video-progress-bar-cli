"""发布器消费冻结商品任务：尝试挂接，失败且表单清空就绪时允许无商品继续。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| english-all-v1 | 2026-10-21 | Codex | 英语世界商品失败不得无商品继续，发表前再次强制绑定核验。 |
| 1.4.0 | 2026-10-12 | Antigravity | 最终核验时清理竞争的旧文章与无挂接回读，防止证据目录复用时相互污染。 |
| 1.3.0 | 2026-10-12 | Codex | 最终实读回执保留平台选中行的挂载 ID，拒绝前后身份变化。 |
| 1.2.0 | 2026-10-12 | Codex | 保留逐次选品结果；允许正式挂商品验收显式要求最终绑定，日常降级规则不变。 |
| 1.1.0 | 2026-10-11 | Codex | 取消商品绑定硬门槛及商品可用性退避；保留提交去重、产物一致性与在途租约。 |
"""
from __future__ import annotations
from pathlib import Path
from dataclasses import replace
from time import monotonic
import time
import hashlib
from video_processing.utils.wechat_product_config import atomic_json, record_adoption
from video_processing.utils.wechat_product_task import selection_from_task
from video_processing.utils.wechat_product_selection import select_optional_product, _Deadline
from video_processing.utils.wechat_product_waits import ProductWaitStore
from video_processing.core.wechat_product_attachment import requires_bound_product


def _wait_row_ready(row: dict, now: float, generation: str | None) -> bool:
    # 旧商品库存/额度等待可以进入表单并安全无商品降级；清理异常不能这样释放。
    if row['submission_state'] != 'NOT_SUBMITTED' or row['state'] == 'VERIFY_SUBMISSION' or row['lease_until'] > now:
        return False
    if row['reason'] in {'PRODUCT_UNAVAILABLE', 'QUOTA_EXHAUSTED', 'LOGIN_REQUIRED'}:
        return True
    if row['state'] == 'BLOCKED':
        return False
    if row['state'] == 'READY_FOR_EXISTING_GATES':
        return True
    if generation is not None and generation != row.get('observed_generation'):
        return True
    return row['state'] in {'WAITING', 'CHECKING'} and row['next_check_at'] <= now


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
    if row is None:
        return True
    if row['artifacts_digest'] != artifacts_digest or row['state'] == 'VERIFY_SUBMISSION':
        return False
    if row['submission_state'] != 'NOT_SUBMITTED' or row['lease_until'] > clock():
        return False
    return _wait_row_ready(row, clock(), observation_generation)


def product_task_preflight(payload: dict, output: Path, artifacts_digest: str, *,
                           observation_generation: str | None = None) -> bool:
    """保留在途/已提交/产物保护；商品身份不可用在表单阶段无商品降级。"""
    return product_wait_ready(payload, output, artifacts_digest, observation_generation=observation_generation)


def blocked_product_task_keys(output: Path, active: Path, *, clock=time.time) -> list[str]:
    """遍历整个等待账本后交给 DAL 在 LIMIT 前排除，避免队首等待饿死后续。"""
    generation = product_observation_generation(active)
    blocked = []
    for row in ProductWaitStore(output / 'wechat_product_waits.json').records():
        if not _wait_row_ready(row, clock(), generation):
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
        observation_generation=generation, count_failed_attempt=True)
    atomic_json(evidence_dir / 'product_wait.json', dict(row, not_submitted=True))


def finalize_product_before_submit(payload: dict | None, picker, evidence_dir: Path, *, require_bound: bool = False) -> bool:
    """最终表单必须与本次选品回执一致，独立保存发表前实读证据。

    不补挂、不推测 ID；商品消失/出现/被替换时均停止发表。
    """
    import json
    readback = evidence_dir / 'product_pre_submit_readback.json'
    readback.unlink(missing_ok=True)
    (evidence_dir / "article_pre_submit_readback.json").unlink(missing_ok=True)
    (evidence_dir / "none_pre_submit_readback.json").unlink(missing_ok=True)
    try:
        require_bound = require_bound or (payload is not None and requires_bound_product(payload))
        receipt = json.loads((evidence_dir / 'product_selection_receipt.json').read_text())
        if payload is not None:
            if any(receipt.get(key) != payload.get(key) for key in ('task_id', 'config_version', 'config_digest')):
                return False
            if receipt.get('required') is not payload['require_product']:
                return False
        actual = picker.read_binding(timeout_ms=3000)
        if not picker.ready_to_submit(timeout_ms=3000) or picker.read_binding(timeout_ms=3000) != actual:
            return False
        if actual is None:
            if require_bound:
                return False
            if (receipt.get('state') not in {'UNBOUND', 'SKIPPED'} or receipt.get('unbound_confirmed') is not True
                    or receipt.get('binding_confirmed') is not False
                    or receipt.get('actual_product_id') or receipt.get('actual_title')):
                return False
        else:
            if (receipt.get('state') != 'BOUND' or receipt.get('binding_confirmed') is not True
                    or receipt.get('unbound_confirmed') is True
                    or (actual.product_id, actual.title) != (receipt.get('actual_product_id'), receipt.get('actual_title'))):
                return False
            if payload is not None:
                if payload['require_product'] is not True or actual not in selection_from_task(payload)[1].candidates:
                    return False
            if (receipt.get('actual_platform_product_id') is not None
                    and receipt['actual_platform_product_id'] != getattr(picker, 'binding_platform_product_id', None)):
                return False
        atomic_json(readback, dict(receipt, final_verified=True, identity_source=getattr(picker, 'binding_identity_source', 'FINAL_FORM_READBACK'),
                                  actual_platform_product_id=getattr(picker, 'binding_platform_product_id', None) if actual else None,
                                  binding_required=bool(require_bound or receipt.get('binding_required'))))
        return True
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
        record_adoption(policy, decision, evidence_dir, status_path, phase='STARTED', task_decision=payload)
        result = select_optional_product(decision=decision, picker=picker,
                                         timeout_seconds=decision.timeout_seconds, clock=clock,
                                         selection_block_reason=payload.get('selection_block_reason'))
        binding_required = requires_bound_product(payload)
        if binding_required and result.state == 'UNBOUND':
            result = replace(result, state='BLOCKED', reason='ENGLISH_WORLD_PRODUCT_REQUIRED')
        receipt = dict(required=True, binding_required=binding_required, binding_confirmed=result.binding_confirmed,
                       unbound_confirmed=result.state == 'UNBOUND', state=result.state,
                       reason=result.reason, actual_product_id=result.actual.product_id if result.actual else None,
                       actual_platform_product_id=getattr(picker, 'binding_platform_product_id', None) if result.actual else None,
                       actual_title=result.actual.title if result.actual else None,
                       requested_product_id=result.requested.product_id, requested_title=result.requested.title,
                       attempts=result.attempts, fallback_reason=result.fallback_reason,
                       attempt_records=list(result.attempt_records), elapsed_seconds=result.elapsed_seconds,
                       config_version=policy.version, config_digest=policy.digest,
                       task_id=payload['task_id'], attachment_reason=payload['reason'])
        atomic_json(evidence_dir / 'product_selection_receipt.json', receipt)
        record_adoption(policy, decision, evidence_dir, status_path, phase=result.state, result=result, task_decision=payload)
        if wait_output is not None and artifacts_digest:
            if not result.submission_allowed:
                _record_product_wait(payload, result, evidence_dir, wait_output, artifacts_digest, generation)
        return result.submission_allowed
    if requires_bound_product(payload):
        raise ValueError('英语世界任务不允许无商品提交')
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
