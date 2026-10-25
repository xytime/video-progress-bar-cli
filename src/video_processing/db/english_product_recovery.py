"""英语世界商品故障的一次性具名恢复；保留旧包、旧决定和旧尝试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-25 | Codex | 仅完整未提交证据可换用新商品快照，独立授权在领取时原子消费一次。 |
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


class EnglishProductRecoveryDAL:
    @staticmethod
    def initialize_english_product_recovery(cursor):
        cursor.execute("""CREATE TABLE IF NOT EXISTS english_world_product_recoveries (
            review_id TEXT PRIMARY KEY REFERENCES english_world_review_items(id),
            payload TEXT NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            consumed_at TIMESTAMP DEFAULT NULL,
            attempt_id TEXT DEFAULT NULL
        )""")

    def get_english_world_product_recovery(self, review_id):
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM english_world_product_recoveries WHERE review_id=?",
                               (review_id,)).fetchone()
        return dict(row, payload=json.loads(row['payload'])) if row else None

    def authorize_english_world_product_recovery(self, review_id, *, reason, source_decision, decision):
        """显式操作入口；所有历史访问均须证明未提交，不重置自动重试预算。"""
        from ..english_world.package_integrity import verify_package_hashes
        from ..utils.wechat_product_task import selection_from_task
        from ..core.wechat_product_attachment import ENGLISH_PREFERRED_VERSION

        reason = ' '.join(str(reason or '').split())
        if not reason or len(reason) > 240:
            raise ValueError('商品恢复须有明确原因')
        prior_grant = self.get_english_world_product_recovery(review_id)
        expected_task = 'english-product-recovery:' + review_id + (':technical-retry' if prior_grant else '')
        if (decision.get('task_id') != expected_task
                or decision.get('attachment_version') != ENGLISH_PREFERRED_VERSION
                or decision.get('context', {}).get('review_id') != review_id):
            raise ValueError('商品恢复必须绑定本审核项的新策略快照')
        selection_from_task(decision)
        old_context = dict(source_decision['context'])
        old_context.update(task_id=decision['task_id'],
                           production_task_id=old_context.get('production_task_id') or source_decision['task_id'])
        if decision['context'] != old_context:
            raise ValueError('商品恢复不能改写原生产输入')
        with self.get_connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM english_world_review_items WHERE id=?', (review_id,)).fetchone()
            if (not row or row['state'] != 'SUBMISSION_APPROVED' or row['approval_source'] != ('OPERATOR_RECOVERY' if prior_grant else 'AUTO_POLICY')
                    or row['submission_started_at'] or row['platform_post_id'] or row['platform_state'] or row['platform_url']):
                raise ValueError('商品恢复只允许已批准且明确未提交的自动任务')
            grant = conn.execute('SELECT * FROM english_world_product_recoveries WHERE review_id=?', (review_id,)).fetchone()
            if bool(grant) != bool(prior_grant):
                raise ValueError('商品恢复授权并发变化')
            if grant:
                original_payload = json.loads(grant['payload'])
                if (original_payload.get('technical_retry') or not grant['consumed_at']
                        or grant['expires_at'] <= conn.execute("SELECT datetime('now')").fetchone()[0]
                        or source_decision != original_payload['decision']):
                    raise ValueError('只允许同轮明确未提交故障的一次具名技术续跑')
            for value in (source_decision, decision):
                frozen = conn.execute('SELECT payload FROM product_task_decisions WHERE task_id=?',
                                      (value['task_id'],)).fetchone()
                if not frozen or json.loads(frozen[0]) != value:
                    raise ValueError('商品恢复要求完整冻结的原决定与新决定')
            if source_decision['context'].get('review_id') != review_id:
                raise ValueError('旧商品决定不属于本审核项')
            verify_package_hashes(dict(row))
            attempts = conn.execute('SELECT * FROM english_world_submission_attempts WHERE review_id=?',
                                    (review_id,)).fetchall()
            proof = []
            product_failures = 0
            for attempt in attempts:
                if (attempt['state'] != 'FAILED' or not attempt['finished_at']
                        or attempt['platform_post_id'] or attempt['platform_url']):
                    raise ValueError('历史存在在途、已提交或结果不明尝试，禁止重发')
                for key in ('artifact_sha256', 'manifest_sha256', 'title_sha256', 'copy_sha256',
                            'cover_sha256', 'cover_provenance_sha256'):
                    if attempt[key] != row[key]:
                        raise ValueError('历史尝试与当前原包不一致')
                attempt_source = source_decision
                if grant and attempt['attempt_id'] != grant['attempt_id']:
                    recorded = next((a for a in original_payload['attempts'] if a['attempt_id'] == attempt['attempt_id']), None)
                    if recorded is None:
                        raise ValueError('出现未审计的新尝试')
                    attempt_source = original_payload['source_decision']
                if grant and attempt['attempt_id'] == grant['attempt_id']:
                    if attempt['finished_at'] > conn.execute("SELECT datetime('now','-60 seconds')").fetchone()[0]:
                        raise ValueError('技术续跑须至少间隔一分钟')
                evidence = Path(attempt['evidence_dir'])
                hashes = {}
                if attempt['uploader_exit_code'] == 11 and evidence.is_dir() and not any(evidence.iterdir()):
                    proof.append(dict(attempt_id=attempt['attempt_id'], evidence_dir=str(evidence), session_busy=True))
                    continue
                if attempt['uploader_exit_code'] != 14 or (evidence / 'submission_receipt.json').exists():
                    raise ValueError('历史尝试没有明确的商品阻塞未提交证明')
                data = {}
                for name in ('submission_progress.json', 'product_wait.json', 'product_selection_receipt.json'):
                    raw = (evidence / name).read_bytes()
                    hashes[name] = hashlib.sha256(raw).hexdigest()
                    data[name] = json.loads(raw)
                progress, wait, receipt = (data[n] for n in
                    ('submission_progress.json', 'product_wait.json', 'product_selection_receipt.json'))
                if (progress.get('version') != 1 or progress.get('submit_intent') is not False
                        or progress.get('video') != str(Path(row['mp4_path']).resolve())
                        or wait.get('not_submitted') is not True or wait.get('submission_state') != 'NOT_SUBMITTED'
                        or wait.get('task_key') != attempt_source['task_id']
                        or receipt.get('task_id') != attempt_source['task_id']
                        or wait.get('config_digest') != attempt_source['config_digest']
                        or receipt.get('config_digest') != attempt_source['config_digest']
                        or receipt.get('state') != 'BLOCKED' or receipt.get('binding_confirmed') is not False
                        or receipt.get('reason') not in {'PRODUCT_CLEANUP_BUDGET_EXHAUSTED', 'PRODUCT_CLEANUP_OPERATION_TIMEOUT'}):
                    raise ValueError('商品恢复证据身份或未提交边界不完整')
                product_failures += 1
                proof.append(dict(attempt_id=attempt['attempt_id'], evidence_dir=str(evidence), hashes=hashes))
            if not product_failures:
                raise ValueError('没有可恢复的商品清理故障')
            payload = dict(reason=reason, operator='explicit-user-authorized', source_decision=source_decision,
                           decision=decision, attempts=proof, artifact_sha256=row['artifact_sha256'])
            if grant:
                original_payload['technical_retry'] = payload
                conn.execute('UPDATE english_world_product_recoveries SET payload=? WHERE review_id=? AND payload=?',
                             (json.dumps(original_payload, ensure_ascii=False), review_id, grant['payload']))
                return dict(row)
            conn.execute("""INSERT INTO english_world_product_recoveries(review_id,payload,expires_at)
                VALUES(?,?,datetime('now','+120 minutes'))""", (review_id, json.dumps(payload, ensure_ascii=False)))
            conn.execute("""UPDATE english_world_review_items SET approval_source='OPERATOR_RECOVERY',
                authorization_expires_at=datetime('now','+120 minutes'), error_message=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?""", ('商品修复后具名恢复一轮；旧尝试保留：' + reason, review_id))
            return dict(conn.execute('SELECT * FROM english_world_review_items WHERE id=?', (review_id,)).fetchone())
