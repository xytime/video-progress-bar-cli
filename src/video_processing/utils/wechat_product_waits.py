"""商品等待记录与有界检查资格；不上传、不发表、不替代授权或作品去重门禁。"""
from __future__ import annotations
from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
import time
from uuid import uuid4
from video_processing.utils.wechat_product_config import atomic_json, _unique_object

from video_processing.core.wechat_product_wait_policy import DEFAULT_WAIT_POLICY, WAIT_REASONS, validate_wait_policy


class ProductWaitStore:
    """两种发布入口共用持久化账本；claim 只允许重新核验，不赋予上传资格。"""
    def __init__(self, path: Path, *, clock=time.time):
        self.path = path
        self.clock = clock

    def _read(self):
        if not self.path.exists():
            return {'schema_version': 1, 'tasks': {}}
        data = json.loads(self.path.read_text(), object_pairs_hook=_unique_object)
        if not isinstance(data, dict) or data.get('schema_version') != 1 or not isinstance(data.get('tasks'), dict):
            raise ValueError('等待账本损坏，不能恢复任务')
        return data

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = self._read()
            yield data
            atomic_json(self.path, data)

    def records(self):
        return sorted(self._read()['tasks'].values(), key=lambda r:r['updated_at'], reverse=True)

    def defer(self, task_key: str, *, reason: str, config_digest: str, artifacts_digest: str,
              submission_state: str, wait_policy=None, observation_generation: str | None = None):
        if not task_key or len(task_key) > 200 or not config_digest or not artifacts_digest:
            raise ValueError('等待记录需要稳定任务标识、策略摘要和产物摘要')
        policy = validate_wait_policy(wait_policy or DEFAULT_WAIT_POLICY)
        now = self.clock()
        with self._locked() as data:
            old = data['tasks'].get(task_key, {})
            checks = old.get('checks', 0)
            # 只有确定尚未提交才允许自动重新检查；结果不明必须先查原作品。
            state = 'WAITING' if reason in WAIT_REASONS else 'BLOCKED'
            if submission_state != 'NOT_SUBMITTED':
                state = 'VERIFY_SUBMISSION'
            if old.get('state') == 'VERIFY_SUBMISSION':
                state = 'VERIFY_SUBMISSION'
            if checks >= policy['max_checks'] and state == 'WAITING':
                state = 'CHECK_LIMIT'
            row = dict(task_key=task_key, reason=reason, state=state, checks=checks,
                       config_digest=config_digest, artifacts_digest=artifacts_digest,
                       submission_state=submission_state, wait_policy=policy,
                       next_check_at=now + min(policy['max_seconds'], policy['base_seconds'] * 2**min(checks,30)),
                       updated_at=now, lease_token=None, lease_until=0,
                       observed_generation=observation_generation or old.get('observed_generation'))
            data['tasks'][task_key] = row
        return row

    def claim_check(self, task_key: str, *, current_config_digest: str, current_artifacts_digest: str,
                    observation_generation: str | None = None):
        now = self.clock()
        with self._locked() as data:
            row = data['tasks'].get(task_key)
            if not row or row['state'] not in {'WAITING','CHECK_LIMIT','CHECKING'}:
                return None
            if row['submission_state'] != 'NOT_SUBMITTED':
                return None
            if current_artifacts_digest != row['artifacts_digest']:
                row.update(state='BLOCKED', reason='ARTIFACTS_CHANGED', updated_at=now)
                return None
            if row['lease_until'] > now:
                return None
            changed = current_config_digest != row['config_digest'] or (observation_generation is not None and observation_generation != row['observed_generation'])
            if not changed and (row['state'] == 'CHECK_LIMIT' or now < row['next_check_at']):
                return None
            if changed:
                row['checks'] = 0
            if row['checks'] >= row['wait_policy']['max_checks']:
                row.update(state='CHECK_LIMIT', updated_at=now)
                return None
            token = uuid4().hex
            row.update(state='CHECKING', checks=row['checks']+1, lease_token=token,
                       lease_until=now+row['wait_policy']['lease_seconds'], updated_at=now,
                       config_digest=current_config_digest, observed_generation=observation_generation or row['observed_generation'])
            # 崩溃也保留退避，不能因租期短而每分钟反复检查。
            row['next_check_at'] = now + min(row['wait_policy']['max_seconds'], row['wait_policy']['base_seconds']*2**min(row['checks'],30))
            return dict(row, check_only=True, upload_authorized=False)

    def finish_check(self, task_key: str, token: str, *, available: bool, reason: str):
        now = self.clock()
        with self._locked() as data:
            row = data['tasks'][task_key]
            if row['lease_token'] != token or row['state'] != 'CHECKING' or row['lease_until'] <= now:
                raise ValueError('检查租期失效，不能覆盖较新的执行结果')
            if available:
                state = 'READY_FOR_EXISTING_GATES'
            elif reason not in WAIT_REASONS:
                state = 'BLOCKED'
            else:
                state = 'CHECK_LIMIT' if row['checks'] >= row['wait_policy']['max_checks'] else 'WAITING'
            row.update(state=state, reason=reason, updated_at=now, lease_token=None, lease_until=0)
            return dict(row, upload_authorized=False)
