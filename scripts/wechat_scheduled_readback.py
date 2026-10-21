"""只处理新调度器收到的原生回执，绝不扫描历史数据库或重发作品。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-21 | Codex | 新投稿最多 1/6/24 小时三次核对，增强版由既有 heartbeat 独占处理。 |
"""
import json
import subprocess
import time
from pathlib import Path

from video_processing.core.wechat_request_guard import WeChatRequestGuard, WeChatRequestDeferred
from video_processing.core.task_lease import TaskLease, TaskLeaseBusy


def reconcile_new_submissions(root: Path) -> bool:
    state_path = root / 'output/wechat_state.json'
    guard = WeChatRequestGuard(state_path)
    try:
        guard.check()
    except WeChatRequestDeferred:
        return False
    publications = guard.snapshot().get('schedule', {}).get('publications', {})
    for native_id, item in publications.items():
        if item.get('heartbeat_managed') or item.get('state') == 'PUBLISHED':
            continue
        checks = item.get('checks', 0)
        if checks >= 3 or time.time() > item['at'] + 86460:
            if item.get('state') != 'FINAL_STATE_UNVERIFIED':
                guard.record_publication_state(native_id, 'FINAL_STATE_UNVERIFIED')
            continue
        if time.time() < item['at'] + (3600, 21600, 86400)[checks]:
            continue
        receipt = Path(item.get('receipt_path', ''))
        metadata = item.get('metadata', {})
        if not receipt.is_file() or not metadata.get('copy_path'):
            continue
        try:
            bound = json.loads(receipt.read_text())
            if bound.get('platform_post_id') != native_id:
                continue
            with TaskLease(root / 'output/wechat_publish_priority.lock', stage='新投稿有界核对'):
                guard.admission('状态核对', native_id, 'wechat_scheduled_readback.py')
                evidence = receipt.parent / 'scheduled_readback' / str(time.time_ns())
                evidence.mkdir(parents=True)
                command = [str(root / '.venv/bin/python'), str(root / 'scripts/wechat_uploader.py'),
                           '--state', str(state_path), '--verify-only', '--platform-post-id', native_id,
                           '--identity-receipt', str(receipt), '--copy', metadata['copy_path'],
                           '--evidence-dir', str(evidence), '--fail-fast-login', '--no-original-declaration']
                if metadata.get('title_path'):
                    command += ['--title-file', metadata['title_path']]
                with (evidence / 'uploader.log').open('w') as log:
                    result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, timeout=600)
                (evidence / 'attempt.json').write_text(json.dumps({'returncode': result.returncode}))
                readback = evidence / 'management_readback.json'
                if readback.is_file():
                    observed = json.loads(readback.read_text())
                    if observed.get('platform_post_id') == native_id:
                        guard.record_publication_state(native_id, observed.get('state', 'UNCERTAIN'))
                return True
        except (WeChatRequestDeferred, TaskLeaseBusy):
            return False
    return False
