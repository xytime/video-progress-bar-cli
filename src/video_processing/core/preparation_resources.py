"""仅预加工的跨代锁、同源锁和进程级资源槽；没有上下文时不改变旧执行行为。

依赖：pipeline_manager / CLI → 本模块 → 标准库 / settings。跨代锁由调度器
创建，子孙沿用同一 open-file-description；任何持有者退出前都不能回旧串行器。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-29 | Codex | 默认关闭的预加工执行上下文、真实 FD 继承与两资源槽。 |
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid

_CURRENT = ContextVar('preparation_execution', default=None)
_PROCESS_SCOPE = None
_INSTALL_LOCK = threading.Lock()
_WAIT_LOCK = threading.Lock()
_WAITERS = 0
_WAIT_STARTED = 0.0
_WAIT_TOTAL = 0.0
PROTOCOL = 1


class PreparationBusy(BaseException):
    """有真实持有者，保留等待态，不是质量失败。"""


class PreparationYielded(BaseException):
    """仅已持久化的完整检查点可抛出；不得进入质量/未知异常分支。"""


YIELD_EXIT_CODE = 76
WAIT_EXIT_CODE = 77


def _event(kind, **data):
    try:
        from ..utils.stage_events import emit_event
        emit_event(kind, **data)
    except ImportError:
        pass


def wait_state():
    with _WAIT_LOCK:
        return {'waiting': bool(_WAITERS), 'seconds': _WAIT_TOTAL +
                (max(0, time.monotonic()-_WAIT_STARTED) if _WAITERS else 0)}


def _waiting(change):
    global _WAITERS, _WAIT_STARTED, _WAIT_TOTAL
    with _WAIT_LOCK:
        if change > 0 and _WAITERS == 0:
            _WAIT_STARTED = time.monotonic()
        _WAITERS += change
        if change < 0 and _WAITERS == 0:
            _WAIT_TOTAL += max(0, time.monotonic()-_WAIT_STARTED)


class DescriptorLease:
    """只 close 不 LOCK_UN；父退出后实际执行子孙仍保留名额。"""
    def __init__(self, path, *, label, owner='', blocking=False):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open('a+')
        try:
            fcntl.flock(self.stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BaseException:
            self.stream.close()
            raise
        self.stream.seek(0)
        self.stream.truncate()
        json.dump(dict(protocol=PROTOCOL, label=label, pid=os.getpid(), owner=owner,
                       started_at=time.time()), self.stream)
        self.stream.flush()

    def descriptor(self):
        return dict(path=str(self.path.resolve()), fd=self.stream.fileno())

    def close(self):
        self.stream.close()


def _validate_descriptor(row):
    """不同 FD 确认锁真的被占用，再确认继承 FD 属于同一锁。"""
    fd, path = row['fd'], Path(row['path'])
    if type(fd) is not int or fd < 3 or not path.is_absolute():
        raise ValueError('invalid preparation descriptor')
    with path.open('r+') as separate:
        own, disk = os.fstat(fd), os.fstat(separate.fileno())
        if (own.st_dev, own.st_ino) != (disk.st_dev, disk.st_ino):
            raise ValueError('preparation descriptor identity mismatch')
        try:
            fcntl.flock(separate, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            raise ValueError('preparation lease is not held')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def active_context():
    return _CURRENT.get() or _PROCESS_SCOPE


class ExecutionScope:
    def __init__(self, output, key, owner, descriptors, *, inherited=False):
        if not re.fullmatch(r'[A-Za-z0-9_-]+:[0-9]+', key):
            raise ValueError('invalid preparation task identity')
        if not re.fullmatch(r'[a-f0-9]{32}', owner):
            raise ValueError('invalid preparation owner token')
        self.output, self.key, self.owner = Path(output).resolve(), key, owner
        self.descriptors = descriptors
        self.owned = []
        self.lane = None
        self.lane_name = None
        self.stage = ''
        self.thread = threading.get_ident()
        self.children = []
        self.inherited = inherited
        self.closed = False
        self.heavy_seconds = 0.0
        self.lane_started = None

    def payload(self):
        descriptors = list(self.descriptors)
        if self.lane is not None:
            descriptors.append(self.lane.descriptor())
        return dict(protocol=PROTOCOL, output=str(self.output), key=self.key,
                    owner=self.owner, descriptors=descriptors,
                    lane=self.lane_name, stage=self.stage)

    def subprocess_options(self, kwargs):
        result = dict(kwargs)
        payload = self.payload()
        env = dict(result.get('env') or _environment())
        env['PREPARATION_EXECUTION_CONTEXT'] = json.dumps(payload)
        result['env'] = env
        result['pass_fds'] = tuple(sorted(set(result.get('pass_fds', ())) |
                                         {row['fd'] for row in payload['descriptors']}))
        return result

    def release_lane(self):
        if self.lane is not None:
            if any(child.poll() is None for child in self.children):
                raise RuntimeError('cannot change resource while a child is still executing')
            if self.lane_name == 'heavy' and self.lane_started is not None:
                self.heavy_seconds += max(0.0, time.monotonic() - self.lane_started)
            _event('resource_released', stage=self.stage, resource=self.lane_name,
                   owner_token=self.owner, duration_seconds=max(0.0, time.monotonic() - self.lane_started))
            self.lane.close()
            self.lane = None
            self.lane_name = None
            self.lane_started = None

    def switch(self, kind, stage):
        if threading.get_ident() != self.thread:
            raise RuntimeError('preparation stages require a single execution thread')
        if kind not in {'heavy', 'network'}:
            raise ValueError('unknown preparation resource')
        if self.lane_name == kind:
            self.stage = stage
            return
        self.release_lane()
        wait_started = time.monotonic()
        _event('resource_wait', stage=stage, resource=kind, owner_token=self.owner)
        directory = self.output / 'preparation_resources'
        directory.mkdir(parents=True, exist_ok=True)
        # 唯一票据的内核锁区分死亡等待者；按创建时间 FIFO，不以 PID 猜存活。
        ticket = DescriptorLease(directory / f'{time.time_ns():020}-{uuid.uuid4().hex}.wait',
                                 label=kind, owner=self.owner)
        _waiting(1)
        try:
            while True:
                earlier = False
                for path in sorted(directory.glob('*.wait')):
                    if path.name >= ticket.path.name:
                        break
                    try:
                        with path.open('r+') as stream:
                            row = json.load(stream)
                            if row.get('label') != kind:
                                continue
                            try:
                                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            except BlockingIOError:
                                earlier = True
                                break
                    except (OSError, ValueError):
                        raise PreparationBusy('resource queue owner cannot be verified')
                if not earlier:
                    try:
                        self.lane = DescriptorLease(directory / f'{kind}.lock', label=kind, owner=self.owner)
                        break
                    except BlockingIOError:
                        pass
                time.sleep(.05)
            self.lane_name, self.stage = kind, stage
            self.lane_started = time.monotonic()
            _event('resource_acquired', stage=stage, resource=kind, owner_token=self.owner,
                   duration_seconds=max(0.0, time.monotonic() - wait_started))
        finally:
            _waiting(-1)
            ticket.path.unlink(missing_ok=True)
            ticket.close()

    def close(self):
        global _PROCESS_SCOPE
        if self.closed:
            return
        self.closed = True
        # 不显式 unlock；任何子孙持有同一 OFD 时，close 仍保留真实占用。
        if self.lane is not None:
            _event('resource_released', stage=self.stage, resource=self.lane_name,
                   owner_token=self.owner, duration_seconds=max(0.0, time.monotonic() - self.lane_started))
            self.lane.close()
            self.lane = None
        owned_fds = {lease.stream.fileno() for lease in self.owned}
        for lease in reversed(self.owned):
            lease.close()
        self.owned.clear()
        if self.inherited:
            for row in self.descriptors:
                if row['fd'] not in owned_fds:
                    os.close(row['fd'])
        self.descriptors.clear()
        if _PROCESS_SCOPE is self:
            _PROCESS_SCOPE = None


def _environment():
    from config.settings import settings
    return settings.maintenance_child_environment()


def install_subprocess_guard():
    """与既有 FFmpeg Popen 包装组合；全部子进程继承在途基础租约。"""
    with _INSTALL_LOCK:
        if getattr(subprocess.Popen, '_preparation_guard', False):
            return
        base = subprocess.Popen

        class PreparationPopen(base):
            _preparation_guard = True

            def __init__(self, args, *positional, **kwargs):
                scope = active_context()
                if scope is not None:
                    if positional or kwargs.get('shell'):
                        raise ValueError('preparation children require explicit argv and keyword options')
                    from .ffmpeg_slot import is_ffmpeg
                    if is_ffmpeg(args, kwargs.get('executable')) and scope.lane_name != 'heavy':
                        # 不能持 network 再等待 heavy，否则另一项 heavy→network 会死锁。
                        # 未显式标注的 FFmpeg 也切换真实阶段，下一 hook 再恢复所需资源。
                        scope.switch('heavy', 'FFMPEG_FALLBACK')
                    kwargs = scope.subprocess_options(kwargs)
                super().__init__(args, *positional, **kwargs)
                if scope is not None:
                    scope.children.append(self)
        subprocess.Popen = PreparationPopen


def setup_execution_context(payload=None):
    """CLI 最早处调用；伪造/丢失继承锁一律拒绝，空配置返回 None。"""
    global _PROCESS_SCOPE
    if _PROCESS_SCOPE is not None:
        return _PROCESS_SCOPE
    if payload is None:
        from config.settings import settings
        payload = getattr(settings, 'preparation_execution_context', '')
    if not payload:
        return None
    row = json.loads(payload) if isinstance(payload, str) else payload
    if row.get('protocol') != PROTOCOL or not row.get('descriptors'):
        raise ValueError('invalid preparation execution context')
    output = Path(row['output']).resolve()
    key, owner = row['key'], row['owner']
    # 先检查身份和受控路径，再触碰/复制调用方描述符。
    ExecutionScope(output, key, owner, [])
    if row.get('lane') not in {None, 'heavy', 'network'}:
        raise ValueError('invalid inherited resource lane')
    expected_first = output / 'pipeline.lock'
    if Path(row['descriptors'][0]['path']).resolve() != expected_first:
        raise ValueError('missing cross-generation fence')
    seen = set()
    for descriptor in row['descriptors']:
        path = Path(descriptor['path']).resolve()
        allowed = path == expected_first or path.parent in {
            output / 'task_locks', output / 'source_locks', output / 'preparation_resources'}
        if not allowed or descriptor['fd'] in seen or path.suffix != '.lock':
            raise ValueError('invalid preparation lease path')
        seen.add(descriptor['fd'])
    if row.get('lane') and Path(row['descriptors'][-1]['path']).resolve() != output / 'preparation_resources' / (row['lane']+'.lock'):
        raise ValueError('inherited resource descriptor mismatch')
    descriptors = []
    try:
        for descriptor in row['descriptors']:
            _validate_descriptor(descriptor)
            descriptors.append(dict(descriptor, fd=os.dup(descriptor['fd'])))
    except BaseException:
        for descriptor in descriptors:
            os.close(descriptor['fd'])
        raise
    # 原始继承 FD 必须关闭，否则 stage 释放 dup 后原 FD 仍会占资源。
    for descriptor in row['descriptors']:
        os.close(descriptor['fd'])
    scope = ExecutionScope(row['output'], row['key'], row['owner'], descriptors, inherited=True)
    scope.stage = str(row.get('stage') or '')
    if row.get('lane'):
        lane_descriptor = scope.descriptors.pop()
        scope.lane = object.__new__(DescriptorLease)
        scope.lane.path = Path(lane_descriptor['path'])
        scope.lane.stream = os.fdopen(lane_descriptor['fd'], 'r+')
        scope.lane_name = row['lane']
        scope.lane_started = time.monotonic()
    _PROCESS_SCOPE = scope
    install_subprocess_guard()
    return scope


@contextmanager
def execution_context(output, key, owner):
    """worker 拿同片/同源锁；必须已经继承调度器的跨代 fence。"""
    scope = active_context()
    if scope is None or (scope.key, scope.owner) != (key, owner):
        raise ValueError('preparation worker requires inherited cohort lease')
    prefix = key.replace(':', '_s').removesuffix('_s0')
    try:
        for path in (Path(output) / 'task_locks' / f'{prefix}.lock',
                     Path(output) / 'source_locks' / f'{key.split(":")[0]}.lock'):
            lease = DescriptorLease(path, label='preparation', owner=owner)
            scope.owned.append(lease)
            scope.descriptors.append(lease.descriptor())
    except BlockingIOError as exc:
        raise PreparationBusy('task or source is already executing') from exc
    token = _CURRENT.set(scope)
    try:
        yield scope
    finally:
        _CURRENT.reset(token)


@contextmanager
def resource_stage(kind, stage=''):
    """阶段间换资源；可嵌套，未配置的新路径无副作用。"""
    scope = active_context()
    if scope is None:
        yield
        return
    previous, previous_stage = scope.lane_name, scope.stage
    scope.switch(kind, stage)
    try:
        yield
    finally:
        if previous is None:
            scope.release_lane()
        elif previous != kind:
            scope.switch(previous, previous_stage)


class PreparationCohort:
    """调度器持旧粗锁作跨代 fence，worker 共享该 FD 而非重复抢锁。"""
    def __init__(self, output):
        self.output = Path(output).resolve()
        self.lease = DescriptorLease(self.output / 'pipeline.lock', label='preparation-cohort')

    def options(self, key, owner, kwargs):
        scope = ExecutionScope(self.output, key, owner, [self.lease.descriptor()])
        return scope.subprocess_options(kwargs)

    def close(self):
        self.lease.close()


def checkpoint_boundary(contract: str, *, validated: bool = True):
    """完整帧/分块快照原子保存后调用；只让行，不降低覆盖或重置累计预算。

量子仅计算本执行者实际持 heavy 的时间。没有竞争者不做无意义回队；
上层以专用退出76传递，旧字幕失败/审核流程不消费该结果。
"""
    scope = active_context()
    if scope is None:
        return
    if not validated or not isinstance(contract, str) or not contract:
        raise ValueError('yield requires a validated checkpoint contract')
    elapsed = scope.heavy_seconds
    if scope.lane_name == 'heavy' and scope.lane_started is not None:
        elapsed += max(0.0, time.monotonic() - scope.lane_started)
    path = scope.output / 'preparation_checkpoints' / (hashlib.sha256(scope.key.encode()).hexdigest() + '.json')
    previous = {}
    try:
        previous = json.loads(path.read_text())
        if previous.get('key') != scope.key:
            raise ValueError('checkpoint task identity mismatch')
    except FileNotFoundError:
        pass
    prior = float(previous.get('cumulative_heavy_seconds', 0))
    increment = max(0.0, elapsed - float(previous.get('turn_heavy_seconds', 0))) if previous.get('owner') == scope.owner else elapsed
    payload = dict(schema=1, key=scope.key, owner=scope.owner, contract=contract,
                   cumulative_heavy_seconds=prior + increment, turn_heavy_seconds=elapsed,
                   updated_at=time.time())
    from ..utils.file_utils import write_json_atomically
    write_json_atomically(path, payload)
    from config.settings import settings
    quantum = float(getattr(settings, 'preparation_quantum_seconds', 300))
    if elapsed < quantum:
        return
    for ticket in (scope.output / 'preparation_resources').glob('*.wait'):
        try:
            with ticket.open('r+') as stream:
                row = json.load(stream)
                if row.get('label') != 'heavy' or row.get('owner') == scope.owner:
                    continue
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    _event('checkpoint_yield', stage=scope.stage, duration_seconds=elapsed,
                           owner_token=scope.owner, contract=contract)
                    raise PreparationYielded('validated checkpoint yielded to a waiting task')
        except (OSError, ValueError):
            continue
