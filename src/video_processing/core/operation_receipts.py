"""控制台只读回执：授权保存与投稿动作各自保留证据边界。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0 | 2026-10-25 | Codex | 精确任务授权回读和本地投稿动作分类，不查询平台或改变投稿状态。 |
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def review_receipt(db, youtube_id: str, slice_index: int = 0) -> dict:
    row = db.get_manual_review_receipt(youtube_id, slice_index)
    if not row:
        return {'state': 'NOT_FOUND', 'approval': None}
    approval = row if row.get('id') else None
    enabled = bool(row.get('bypass_censorship'))
    fields = ('id', 'created_at', 'level', 'decision', 'input_hash', 'rule_pack_version',
              'source_field', 'review_stage', 'platform')
    return {'state': 'SAVED' if approval and enabled else 'UNVERIFIED' if enabled else 'NOT_SAVED',
            'youtube_id': youtube_id, 'slice_index': slice_index, 'video_id': row['task_id'],
            'bypass_enabled': enabled, 'task_status': row.get('task_status'),
            'approval': {key: approval.get(key) for key in fields} if approval else None}


def submission_feedback(output: Path, youtube_id: str, slice_index: int = 0,
                        *, evidence_dir: Path | None = None) -> dict:
    """只认可最新本次、同成片、提交意图和点击返回均存在的本地证据。"""
    unknown = {'kind': 'RESULT_UNKNOWN', 'label': '投稿结果待核实',
               'message': '提交结果尚无确证，请人工核实；已停止自动重传。'}
    if not re.fullmatch(r'[A-Za-z0-9_-]+', youtube_id) or slice_index < 0:
        return unknown
    prefix = youtube_id + (f'_s{slice_index}' if slice_index else '')
    root = output / 'wechat_evidence' / prefix
    try:
        if evidence_dir is None:
            attempts = [p for p in root.iterdir() if p.name.isdigit() and p.is_dir()]
            evidence_dir = max(attempts, key=lambda p: int(p.name)) if attempts else root / 'missing'
        if (not root.resolve().is_relative_to(output.resolve())
                or not evidence_dir.resolve().is_relative_to(root.resolve())):
            return unknown
        for name in ('submission_attempt.json', 'submission_progress.json'):
            path = evidence_dir / name
            if not path.resolve().is_relative_to(evidence_dir.resolve()) or path.stat().st_size > 262144:
                return unknown
        attempt = json.loads((evidence_dir / 'submission_attempt.json').read_text())
        progress = json.loads((evidence_dir / 'submission_progress.json').read_text())
        video = Path(attempt['video']).resolve()
        allowed = {output / f'{prefix}_vertical.mp4', output / f'{prefix}_vertical_interactive.mp4'}
        if (video not in {p.resolve() for p in allowed} or progress.get('video') != attempt['video']
                or progress.get('submit_intent') is not True
                or attempt.get('submit_click_returned') is not True
                or attempt.get('manual_confirmation_required') is not True
                or attempt.get('automatic_result_queries') is not False
                or attempt.get('draft_requested') is not False
                or attempt.get('platform_result') != 'UNVERIFIED'):
            return unknown
        return {'kind': 'MANUAL_CONFIRMATION_REQUIRED', 'label': '等待人工确认投稿结果',
                'message': '已执行发表操作；按当前策略不自动查询结果。请在视频号确认，勿重复投稿。',
                'submit_click_returned': True, 'automatic_result_queries': False,
                'recorded_at': attempt.get('recorded_at'), 'evidence': evidence_dir.name}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return unknown
