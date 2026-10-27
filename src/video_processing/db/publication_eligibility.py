"""发布候选与控制台共用的只读资格谓词；不领取、不恢复、不访问平台。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| backlog-v1 | 2026-10-26 | Codex | 共用全部候选门禁、就绪先到先领及有界存量指标刷新。 |
| subtitle-recovery-v1 | 2026-10-27 | Codex | 字幕持久冷却与待修复链在 LIMIT 前共用过滤。 |
"""
import json

from config.settings import settings
from ..scoring import TED_AUTO_PUBLISH_CHANNEL_IDS, compute_policy_score
from .subtitle_recovery import subtitle_recovery_gate_sql


class PublicationEligibilityDAL:
    def _publication_gates(self, *, min_score=75, channel_min_scores=None,
                           ready_only=None, allow_deferred_predecessors=False,
                           source_subtitle_retry_hours=None, excluded_product_tasks=()):
        """每项为通过条件；列表与执行器都用这份 SQL，在 LIMIT 前过滤。"""
        thresholds = dict(settings.auto_publish_channel_min_scores)
        thresholds.update(channel_min_scores or {})
        # 旧调用方传入的演讲线不能覆盖本次已批准的 TED 专属线。
        thresholds.update({cid: settings.ted_publish_score_line for cid in TED_AUTO_PUBLISH_CHANNEL_IDS})
        score = ["(pv.channel_id NOT IN (?,?) AND pv.score >= ?)"]
        score_params = [*TED_AUTO_PUBLISH_CHANNEL_IDS, min_score]
        for cid, line in thresholds.items():
            score.append("(pv.channel_id = ? AND pv.score >= ?)")
            score_params.extend((cid, line))
        if ready_only is True:
            score.append("""EXISTS (SELECT 1 FROM manual_publish_leases lease
                WHERE lease.video_id=pv.id AND lease.platform='wechat'
                  AND lease.claimed_at IS NULL AND lease.revoked_at IS NULL
                  AND COALESCE(lease.lease_state,'ISSUED') IN ('ISSUED','CONSUMED_PREP')
                  AND lease.expires_at>CURRENT_TIMESTAMP
                  AND COALESCE(lease.hard_expires_at,lease.expires_at)>CURRENT_TIMESTAMP
                  AND (lease.prep_deadline_at IS NULL OR lease.prep_deadline_at>CURRENT_TIMESTAMP))""")
        rate_sql, rate_params = self._ted_like_rate_filter()
        terminal = ['PUBLISHED', 'IGNORED', 'COMPLETED', 'HISTORICAL_ARCHIVED']
        if allow_deferred_predecessors:
            terminal.append('WECHAT_DEFERRED')
        return [
            ('STATE', '任务已在检查或状态已变化，等待当前执行结束', "pv.status='PENDING'", ()),
            ('SUBMISSION_PROTECTED', '已有提交意图、回执或历史归档，结果待核实，禁止重投',
             ' AND '.join(f'NOT EXISTS (SELECT 1 FROM {t} p WHERE p.video_id=pv.id)' for t in
                          ('wechat_publications', 'wechat_submission_attempts', 'wechat_publications_historical_archive')), ()),
            ('SOURCE', '浏览素材或独立审批任务不进入普通自动发布',
             "COALESCE(pv.source,'AUTO') NOT IN ('DISCOVERY','COMPLIANCE_REMIX') AND keyword_allowed(pv.source,pv.youtube_id)", ()),
            ('BLACKLIST', '视频或频道已被排除',
             "NOT EXISTS (SELECT 1 FROM recommended_channels c WHERE c.channel_id=pv.channel_id AND c.status='BLACKLISTED') AND NOT EXISTS (SELECT 1 FROM blacklisted_videos b WHERE b.youtube_id=pv.youtube_id)", ()),
            ('CONTENT_REVIEW', '成片已完成，等待人工内容复核通过', 'IFNULL(pv.publication_review_required,0)=0', ()),
            ('SCORE', '低于该频道自动发布线，且无有效的一次人工准入许可', '('+' OR '.join(score)+')', tuple(score_params)),
            ('TED_HISTORY', 'TED历史准入边界前任务保持隔离',
             'NOT (pv.channel_id IN (?,?) AND COALESCE(pv.parent_id,pv.id)<=?)',
             (*TED_AUTO_PUBLISH_CHANNEL_IDS, settings.ted_auto_publish_after_id)),
            ('TED_LIKE_RATE', f'本地源点赞率须严格大于{settings.ted_min_like_rate_pct:g}%；当前未达标或指标缺失，等待指标刷新', rate_sql, rate_params),
            ('RECOVERY_OPERATION', '已在恢复批次内，等待原批次执行',
             "NOT EXISTS (SELECT 1 FROM publishing_recovery_items r WHERE r.video_id=pv.id AND r.state IN ('RESERVED','WAITING','RUNNING'))", ()),
            ('PRODUCT_WAIT', '任务的挂载条件尚未恢复，等待原任务重新检查',
             "'pipeline:'||pv.youtube_id||':'||pv.slice_index NOT IN (SELECT value FROM json_each(?))", (json.dumps(list(excluded_product_tasks)),)),
            ('COPYWRITER_BACKOFF', '文案阶段退避尚未到期',
             'NOT EXISTS (SELECT 1 FROM copywriter_deferred c WHERE c.video_id=pv.id AND c.next_attempt_at>CURRENT_TIMESTAMP)', ()),
            ('SUBTITLE_RECOVERY', '字幕翻译正在冷却或需要修复后恢复',
             subtitle_recovery_gate_sql('pv.id'), ()),
            ('UPLOAD_BACKOFF', '上传前失败退避尚未到期，到期后重检',
             'NOT EXISTS (SELECT 1 FROM wechat_upload_retries r WHERE r.video_id=pv.id AND r.next_attempt_at>CURRENT_TIMESTAMP)', ()),
            ('SOURCE_SUBTITLE', '源字幕检查未通过，等待下一次有界重检',
             "(COALESCE(pv.source_subtitle_status,'PENDING')!='UNAVAILABLE' OR pv.source_subtitle_checked_at<=datetime('now',?))",
             (f'-{max(1,int(settings.source_subtitle_retry_hours if source_subtitle_retry_hours is None else source_subtitle_retry_hours))} hours',)),
            ('PREDECESSOR', '前序切片尚未完成，等待原顺序',
             "(pv.slice_index=0 OR NOT EXISTS (SELECT 1 FROM processed_videos sib WHERE sib.parent_id=pv.parent_id AND sib.slice_index>0 AND sib.slice_index<pv.slice_index AND sib.status NOT IN ("+','.join('?' for _ in terminal)+')))', tuple(terminal)),
        ]

    def get_publication_eligibility(self, video_ids, **options):
        """一次 SELECT、只读且不清租约；不能把这个快照当成上传授权。"""
        if not video_ids:
            return {}
        gates = self._publication_gates(ready_only=True, **options)
        columns = ','.join(f'CASE WHEN ({sql}) THEN 0 ELSE 1 END AS gate_{i}'
                           for i, (_, _, sql, _) in enumerate(gates))
        params = [p for _, _, _, args in gates for p in args]
        with self.get_connection() as c:
            rows = c.execute(f"SELECT pv.id,pv.channel_id,{columns} FROM processed_videos pv LEFT JOIN processed_videos origin ON origin.id=COALESCE(pv.parent_id,pv.id) WHERE pv.id IN ({','.join('?' for _ in video_ids)})", (*params, *video_ids)).fetchall()
        result = {}
        for row in rows:
            blockers = [{'code': code, 'reason': reason} for i, (code, reason, _, _) in enumerate(gates) if row[f'gate_{i}']]
            line = settings.auto_publish_channel_min_scores.get(row['channel_id'], 75)
            for b in blockers:
                if b['code'] == 'SCORE':
                    b['reason'] = f'当前频道自动发布线为{line}分；低于此线且无有效的一次人工准入许可'
            result[row['id']] = dict(eligible=not blockers, blockers=blockers, score_line=line)
        return result

    @staticmethod
    def _ready_metric_condition():
        # 人工锁定仅锁分数，不锁公开统计；所有提交/历史身份始终排除。
        return """pv.status='PENDING' AND pv.preparation_ready=1 AND pv.parent_id IS NULL
            AND pv.source IN ('AUTO','MANUAL') AND pv.channel_id IN (?,?)
            AND pv.id>? AND NOT EXISTS (SELECT 1 FROM blacklisted_videos b WHERE b.youtube_id=pv.youtube_id)
            AND NOT EXISTS (SELECT 1 FROM recommended_channels c WHERE c.channel_id=pv.channel_id AND c.status='BLACKLISTED')
            AND NOT EXISTS (SELECT 1 FROM wechat_publications w WHERE w.video_id=pv.id)
            AND NOT EXISTS (SELECT 1 FROM wechat_submission_attempts a WHERE a.video_id=pv.id)
            AND NOT EXISTS (SELECT 1 FROM wechat_publications_historical_archive h WHERE h.video_id=pv.id)"""

    def get_ready_metric_refresh_candidates(self, limit=5):
        """既有小时任务内最多预留五项，单任务成功/失败均冷却24小时。"""
        with self.get_connection() as c:
            rows = c.execute('SELECT pv.* FROM processed_videos pv WHERE '+self._ready_metric_condition()+" AND (pv.rescore_checked_at IS NULL OR pv.rescore_checked_at<=datetime('now','-24 hours')) ORDER BY COALESCE(pv.rescore_checked_at,pv.publication_ready_at,pv.created_at),pv.id LIMIT ?",
                             (*TED_AUTO_PUBLISH_CHANNEL_IDS, settings.ted_auto_publish_after_id, max(0,min(5,int(limit))))).fetchall()
        return [dict(r) for r in rows]

    def record_ready_metric_refresh(self, youtube_id, slice_index, views, likes):
        """回写前复核身份；保留人工分、资产、就绪时间、审批和全部重试账。"""
        with self.get_connection() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT pv.* FROM processed_videos pv WHERE '+self._ready_metric_condition()+' AND pv.youtube_id=? AND pv.slice_index=?',
                            (*TED_AUTO_PUBLISH_CHANNEL_IDS, settings.ted_auto_publish_after_id, youtube_id, slice_index)).fetchone()
            if row is None:
                return None
            old = int(row['score'] or 0)
            if type(views) is not int or views < 0:
                c.execute('UPDATE processed_videos SET rescore_checked_at=CURRENT_TIMESTAMP WHERE id=?', (row['id'],))
                return old, old
            likes = likes if type(likes) is int and likes >= 0 else None
            video = dict(row, view_count=views, like_count=likes)
            new = old if row['is_manually_scored'] else max(old, compute_policy_score(video, settings))
            c.execute('''UPDATE processed_videos SET view_count=?,like_count=?,score=?,rescore_checked_at=CURRENT_TIMESTAMP,
                score_input_signature=CASE WHEN is_manually_scored=0 THEN ? ELSE score_input_signature END,
                score_computed_at=CASE WHEN is_manually_scored=0 THEN CURRENT_TIMESTAMP ELSE score_computed_at END
                WHERE id=?''', (views, likes, new, self._score_input_signature(row['channel_id'],views,likes),row['id']))
            return old, new
