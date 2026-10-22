"""复用评论页只读证据，修复已投稿但未绑定作品的互动发现断点。

依赖：scripts -> interaction.publication_reconciliation -> db；浏览器通过显式端口注入。
只有 >=30 字符完整文案在本地待办和原生列表中均唯一时才补齐身份。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-23 | Codex | 基于现有评论页证据的唯一全文匹配与 CAS 补绑定。 |
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path


def reconcile_observed_publications(db, receipt_path: Path, output_dir: Path) -> list[dict]:
    """不重新上传、不猜标题、不改已绑定作品；保留原始投稿证据指针。"""
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    if receipt.get('adapter_contract') not in {
        'wechat-comment-v3-scoped-author-readback', 'wechat-comment-catalog-v1',
    }:
        return []
    now = datetime.now(timezone.utc)
    try:
        recorded = datetime.fromisoformat(receipt['recorded_at'])
        if recorded.tzinfo is None or not timedelta(0) <= now - recorded <= timedelta(minutes=15):
            return []
    except (KeyError, TypeError, ValueError):
        return []
    observed = receipt.get('observed_posts', {})
    if not isinstance(observed, dict) or not observed:
        return []
    normalize = lambda value: ' '.join(str(value or '').split())
    cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).strftime('%Y-%m-%d %H:%M:%S')
    rows = db.get_wechat_publications_by_states([
        'SUBMITTED_UNBOUND', 'UNCERTAIN', 'SUBMITTED_BOUND', 'PUBLISHED'])
    candidates = []
    for row in rows:
        created = str(row.get('created_at') or '')
        if created < cutoff or created > recorded.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'):
            continue
        prefix = str(row['youtube_id'])
        if row.get('slice_index'):
            prefix += '_s' + str(row['slice_index'])
        copy_path = output_dir / (prefix + '_copy.txt')
        if not copy_path.is_file():
            continue
        try:
            content = copy_path.read_text(encoding='utf-8')
        except (OSError, UnicodeError):
            continue
        candidates.append((row, copy_path, normalize(content)))
    counts = Counter(text for _, _, text in candidates)
    results = []
    for row, copy_path, text in candidates:
        if row.get('platform_post_id') or len(text) < 30 or counts[text] != 1:
            continue
        matches = [pid for pid, description in observed.items() if normalize(description) == text]
        if len(matches) != 1:
            continue
        evidence = receipt_path.parent / ('publication_binding_' + str(row['id']) + '.json')
        payload = {
            'publication_id': row['id'], 'platform_post_id': matches[0],
            'matched_by': 'unique_exact_comment_scene_description',
            'source_receipt': str(receipt_path),
            'source_receipt_sha256': hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            'copy_path': str(copy_path), 'copy_sha256': hashlib.sha256(copy_path.read_bytes()).hexdigest(),
            'previous_evidence_path': row.get('evidence_path'),
        }
        if evidence.exists():
            continue
        with evidence.open('x', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        bound = db.bind_observed_wechat_publication(row['id'], matches[0], str(evidence))
        if bound:
            results.append(payload)
    return results


def recover_idle_publications(db, browser, output_dir: Path) -> list[dict]:
    """无首评任务时仍发现待绑定作品；同一待办集合最多半小时读取一次目录。"""
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=3)).strftime('%Y-%m-%d %H:%M:%S')
    rows = db.get_wechat_publications_by_states([
        'SUBMITTED_UNBOUND', 'UNCERTAIN', 'SUBMITTED_BOUND', 'PUBLISHED'])
    pending = sorted(int(row['id']) for row in rows
                     if not row.get('platform_post_id') and str(row.get('created_at') or '') >= cutoff)
    anchors = [row for row in rows if row.get('platform_post_id')]
    if not pending or not anchors:
        return []
    marker = output_dir / '.interaction_catalog_scan.json'
    if marker.is_file():
        try:
            previous = json.loads(marker.read_text(encoding='utf-8'))
            age = now - datetime.fromisoformat(previous['checked_at'])
            if previous.get('pending') == pending and age < timedelta(minutes=30):
                return []
        except (ValueError, KeyError, OSError, TypeError):
            pass
    anchor = max(anchors, key=lambda row: int(row['id']))
    status, evidence, error = browser.discover_publications(
        str(anchor['platform_post_id']), output_dir / 'wechat_evidence' / 'interaction_catalog')
    if status != 'CATALOG_OBSERVED' or not evidence:
        return []
    receipt = Path(evidence).parent / 'receipt.json'
    recovered = reconcile_observed_publications(db, receipt, output_dir)
    temp = marker.with_suffix('.tmp')
    temp.write_text(json.dumps({'checked_at': now.isoformat(), 'pending': pending,
                               'receipt': str(receipt)}, ensure_ascii=False), encoding='utf-8')
    temp.replace(marker)
    return recovered
