"""华尔街 A/B 持久账本。依赖：db → 标准库；由 PipelineDB 提供连接。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.2 | 2026-10-10 | Codex | 仅恢复微信上传前明确登录退出的同一尝试，保留次数和证据并延迟重试。 |
| 1.1.1 | 2026-10-10 | Codex | 人工身份恢复审计，以及首次观察时间经平台证据校准；不重新提交。 |
| 1.1.0 | 2026-10-10 | Codex | 封面就绪原子入队、具名漏单恢复及普通 A 强回读衔接。 |
| 1.0.1 | 2026-10-09 | Codex | 修复后可立即重试加工，禁止重置正在执行或已完成任务 |
| 1.0.0 | 2026-10-09 | Codex | 独立二创身份、租约、不可重传提交边界及作品级指标 |
"""
from __future__ import annotations

import datetime as dt
import json
import math
import time
import uuid

CHANNEL_ID = "UCTK_cv-y88CScoudcXnS1Ew"
EXPERIMENT = "wallstreet-editorial-mobile-2"
TEMPLATE = "insight-editorial-mobile-2"
PLATFORMS = {"wechat", "douyin"}


class WallstreetExperimentDAL:
    """SQL 全部留在 DAL；A 的既有账本不修改，B 使用独立发布实体。"""

    @staticmethod
    def _migrate_editorial_launch_tickets(conn):
        """仅扩充 ticket 来源约束；无反向外键，旧 token/尝试及列原样保留。"""
        row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='douyin_browser_launch_tickets'").fetchone()
        if not row or "EDITORIAL" in row[0]:
            return
        sql = row[0].replace("douyin_browser_launch_tickets", "editorial_ticket_migration", 1)
        sql = sql.replace("'DUBBING'", "'DUBBING', 'EDITORIAL'")
        conn.execute(sql)
        columns = [r[1] for r in conn.execute("PRAGMA table_info(douyin_browser_launch_tickets)")]
        names = ",".join('"'+name+'"' for name in columns)
        conn.execute(f"INSERT INTO editorial_ticket_migration ({names}) SELECT {names} FROM douyin_browser_launch_tickets")
        conn.execute("DROP TABLE douyin_browser_launch_tickets")
        conn.execute("ALTER TABLE editorial_ticket_migration RENAME TO douyin_browser_launch_tickets")

    @staticmethod
    def _init_wallstreet_experiment(conn):
        statements = [
            """CREATE TABLE IF NOT EXISTS wallstreet_identity_recoveries (
                publication_id INTEGER NOT NULL, previous_id TEXT NOT NULL, recovered_id TEXT NOT NULL,
                evidence_path TEXT NOT NULL, operator_confirmation TEXT NOT NULL, verified_at REAL NOT NULL,
                PRIMARY KEY(publication_id,previous_id,recovered_id),
                FOREIGN KEY(publication_id) REFERENCES wallstreet_version_publications(id) ON DELETE RESTRICT)""",
            """CREATE TABLE IF NOT EXISTS wallstreet_experiment (
                name TEXT PRIMARY KEY, state TEXT NOT NULL CHECK(state IN ('ACTIVE','PAUSED')),
                activated_at REAL NOT NULL, delay_hours REAL NOT NULL, review_pairs INTEGER NOT NULL,
                template TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS wallstreet_pairs (
                id INTEGER PRIMARY KEY, experiment TEXT NOT NULL, video_id INTEGER NOT NULL UNIQUE,
                mode TEXT NOT NULL CHECK(mode IN ('PAIRED','B_ONLY')), created_at REAL NOT NULL,
                template TEXT NOT NULL, inputs_json TEXT NOT NULL, package_json TEXT,
                state TEXT NOT NULL DEFAULT 'QUEUED'
                  CHECK(state IN ('QUEUED','RENDERING','RETRY','READY','CANCELED')),
                lease_token TEXT, lease_until REAL, attempts INTEGER NOT NULL DEFAULT 0,
                next_run_at REAL NOT NULL DEFAULT 0, last_error TEXT,
                FOREIGN KEY(video_id) REFERENCES processed_videos(id) ON DELETE RESTRICT)""",
            """CREATE TABLE IF NOT EXISTS wallstreet_version_publications (
                id INTEGER PRIMARY KEY, pair_id INTEGER NOT NULL,
                variant TEXT NOT NULL CHECK(variant IN ('A','B')),
                platform TEXT NOT NULL CHECK(platform IN ('wechat','douyin')), account TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'WAITING'
                  CHECK(state IN ('WAITING','SUBMITTING','UNCERTAIN','UNDER_REVIEW','PUBLISHED','REJECTED','CANCELED')),
                platform_post_id TEXT, public_at REAL, public_time_basis TEXT,
                evidence_path TEXT, package_sha256 TEXT, video_path TEXT, asset_sha256 TEXT,
                attempt_token TEXT, attempt_count INTEGER NOT NULL DEFAULT 0,
                next_readback_at REAL NOT NULL DEFAULT 0, last_error TEXT,
                UNIQUE(pair_id,variant,platform,account), UNIQUE(platform,account,platform_post_id),
                FOREIGN KEY(pair_id) REFERENCES wallstreet_pairs(id) ON DELETE RESTRICT)""",
            """CREATE TABLE IF NOT EXISTS wallstreet_metric_snapshots (
                publication_id INTEGER NOT NULL, platform_post_id TEXT NOT NULL,
                horizon_hours INTEGER NOT NULL CHECK(horizon_hours IN (24,72,168)),
                captured_at REAL NOT NULL, evidence_path TEXT NOT NULL, values_json TEXT NOT NULL,
                PRIMARY KEY(publication_id,horizon_hours),
                FOREIGN KEY(publication_id) REFERENCES wallstreet_version_publications(id) ON DELETE RESTRICT)""",
        ]
        for statement in statements:
            conn.execute(statement)

    def set_wallstreet_experiment(self, *, active: bool, delay_hours: float = 6, review_pairs: int = 20):
        if not math.isfinite(delay_hours) or delay_hours < 0 or review_pairs < 1:
            raise ValueError("无效的配对参数")
        with self.get_connection() as conn:
            conn.execute("""INSERT INTO wallstreet_experiment VALUES (?,?,?,?,?,?)
                ON CONFLICT(name) DO UPDATE SET state=excluded.state""",
                (EXPERIMENT, "ACTIVE" if active else "PAUSED", time.time(), delay_hours, review_pairs, TEMPLATE))
        return self.get_wallstreet_experiment()

    def get_wallstreet_experiment(self):
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM wallstreet_experiment WHERE name=?", (EXPERIMENT,)).fetchone()
            return dict(row) if row else None

    def wallstreet_uses_normal_a(self, youtube_id, slice_index=0):
        with self.get_connection() as conn:
            return bool(conn.execute("""SELECT 1 FROM processed_videos v
                LEFT JOIN wallstreet_pairs p ON p.video_id=v.id
                WHERE v.youtube_id=? AND v.slice_index=? AND v.channel_id=?
                  AND (p.id IS NOT NULL OR EXISTS(SELECT 1 FROM wallstreet_experiment e
                    WHERE e.name=? AND e.state='ACTIVE' AND
                      (v.publication_ready_at IS NULL OR
                       (julianday(v.publication_ready_at)-2440587.5)*86400 >= e.activated_at)))""",
                (youtube_id, slice_index, CHANNEL_ID, EXPERIMENT)).fetchone())

    def enroll_wallstreet_video(self, youtube_id, *, slice_index=0, inputs=None, b_only=False,
                               accounts=None, mark_ready=False):
        """A 就绪后原子纳入；明确 B 单条请求可纳入历史但复用唯一的同一 B。"""
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if mark_ready:
                self._mark_ready_in_connection(conn, youtube_id, slice_index)
            return self._enroll_wallstreet_in_connection(conn, youtube_id, slice_index=slice_index,
                inputs=inputs, b_only=b_only, accounts=accounts)

    def recover_wallstreet_pair(self, youtube_id, *, slice_index=0, inputs=None, accounts=None):
        """具名补入启用后漏掉的配对，保留 A 投稿账本与既有 B 身份；绝不重新发布 A。"""
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            return self._enroll_wallstreet_in_connection(conn, youtube_id, slice_index=slice_index,
                inputs=inputs, accounts=accounts, recover_submitted=True)

    def _enroll_wallstreet_in_connection(self, conn, youtube_id, *, slice_index=0, inputs=None,
                                        b_only=False, accounts=None, recover_submitted=False):
        accounts = accounts or {"wechat": "default", "douyin": "default"}
        if not accounts or not set(accounts) <= PLATFORMS or not all(accounts.values()):
            raise ValueError("无效的平台/账号")
        row = conn.execute("SELECT * FROM processed_videos WHERE youtube_id=? AND slice_index=?",
                               (youtube_id, slice_index)).fetchone()
        if not row or row["channel_id"] != CHANNEL_ID:
            return None
        existing = conn.execute("SELECT * FROM wallstreet_pairs WHERE video_id=?", (row["id"],)).fetchone()
        if existing:
            return dict(existing)
        config = conn.execute("SELECT * FROM wallstreet_experiment WHERE name=? AND state='ACTIVE'",
                              (EXPERIMENT,)).fetchone()
        if not b_only:
            if not config or not row["preparation_ready"] or row["source"] == "DISCOVERY":
                return None
            ready = row["publication_ready_at"]
            if not ready or dt.datetime.fromisoformat(ready).replace(tzinfo=dt.timezone.utc).timestamp() < config["activated_at"]:
                return None
            submitted = conn.execute("""SELECT 1 FROM wechat_submission_attempts WHERE video_id=?
                UNION ALL SELECT 1 FROM wechat_publications WHERE video_id=?
                UNION ALL SELECT 1 FROM douyin_publications WHERE video_id=? LIMIT 1""",
                (row["id"], row["id"], row["id"])).fetchone()
            if row["publication_review_required"]:
                return None
            if recover_submitted:
                bound = conn.execute("""SELECT 1 FROM wechat_publications WHERE video_id=?
                    AND platform_post_id IS NOT NULL AND platform_post_id!=''
                    AND evidence_path IS NOT NULL AND evidence_path!=''
                    AND state IN ('SUBMITTED_BOUND','UNDER_REVIEW','PUBLISHED')""", (row["id"],)).fetchone()
                if not bound:
                    return None
            elif submitted:
                return None
        cursor = conn.execute("""INSERT INTO wallstreet_pairs
            (experiment,video_id,mode,created_at,template,inputs_json) VALUES (?,?,?,?,?,?)""",
            (EXPERIMENT, row["id"], "B_ONLY" if b_only else "PAIRED", time.time(), TEMPLATE,
             json.dumps(inputs or {}, ensure_ascii=False, sort_keys=True)))
        pair_id = cursor.lastrowid
        for platform, account in accounts.items():
            for variant in (("B",) if b_only else ("A", "B")):
                conn.execute("""INSERT INTO wallstreet_version_publications
                    (pair_id,variant,platform,account) VALUES (?,?,?,?)""", (pair_id, variant, platform, account))
        return dict(conn.execute("SELECT * FROM wallstreet_pairs WHERE id=?", (pair_id,)).fetchone())

    def recover_wallstreet_normal_a_identity(self, publication_id, *, previous_id, recovered_id,
                                           evidence_path, operator_confirmation):
        """仅供已人工核对完整原生预览的具名恢复；CAS 两本账，仍须独立公开回读。"""
        if not all(isinstance(x, str) and x.strip() for x in
                   (previous_id, recovered_id, evidence_path, operator_confirmation)) or previous_id == recovered_id:
            raise ValueError('恢复必须具备不同的新旧身份及人工确认证据')
        with self.get_connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute("""SELECT pub.*,p.video_id FROM wallstreet_version_publications pub
                JOIN wallstreet_pairs p ON p.id=pub.pair_id WHERE pub.id=?
                AND pub.variant='A' AND pub.platform='wechat' AND p.mode='PAIRED'""", (publication_id,)).fetchone()
            if not row or row['state'] not in ('UNCERTAIN','UNDER_REVIEW') or row['platform_post_id'] != previous_id:
                raise ValueError('普通 A 原身份或恢复状态不匹配')
            changed = conn.execute("""UPDATE wechat_publications SET platform_post_id=?,updated_at=CURRENT_TIMESTAMP
                WHERE video_id=? AND platform_post_id=? AND state IN ('SUBMITTED_BOUND','UNDER_REVIEW')""",
                (recovered_id,row['video_id'],previous_id)).rowcount
            if changed != 1:
                raise ValueError('普通提交账本原身份不匹配')
            conn.execute("""INSERT INTO wallstreet_identity_recoveries VALUES (?,?,?,?,?,?)""",
                (publication_id,previous_id,recovered_id,evidence_path,operator_confirmation,time.time()))
            conn.execute("""UPDATE wallstreet_version_publications SET platform_post_id=?,
                next_readback_at=0,evidence_path=? WHERE id=?""", (recovered_id,evidence_path,publication_id))
            return True

    def sync_wallstreet_normal_a(self, publication_id):
        """仅将强回读确认的同一 A ID 同步到普通账本，解开普通抖音的前置条件。"""
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("""SELECT * FROM wallstreet_version_publications pub
                JOIN wallstreet_pairs p ON p.id=pub.pair_id WHERE pub.id=?
                AND pub.variant='A' AND pub.platform='wechat' AND pub.state='PUBLISHED'""",
                (publication_id,)).fetchone()
            if not row or not row['platform_post_id'] or not row['evidence_path']:
                return False
            changed = conn.execute("""UPDATE wechat_publications SET state='PUBLISHED',
                evidence_path=?,confirmed_at=COALESCE(confirmed_at,CURRENT_TIMESTAMP),
                last_reconciled_at=CURRENT_TIMESTAMP,last_error_message=NULL,updated_at=CURRENT_TIMESTAMP
                WHERE video_id=? AND platform_post_id=?
                AND state IN ('SUBMITTED_BOUND','UNDER_REVIEW','PUBLISHED')""",
                (row['evidence_path'],row['video_id'],row['platform_post_id'])).rowcount
            if changed:
                conn.execute("""UPDATE processed_videos SET status='PUBLISHED',error_msg=NULL,
                    updated_at=CURRENT_TIMESTAMP WHERE id=?
                    AND status IN ('SUBMITTED_BOUND','UNDER_REVIEW','PUBLISHED')""", (row['video_id'],))
            return bool(changed)

    def get_wallstreet_pairs(self):
        with self.get_connection() as conn:
            return [dict(r) for r in conn.execute("""SELECT p.*,v.youtube_id,v.slice_index,v.title,v.zh_title
                FROM wallstreet_pairs p JOIN processed_videos v ON v.id=p.video_id ORDER BY p.id""")]

    def get_wallstreet_publications(self, pair_id=None):
        with self.get_connection() as conn:
            return [dict(r) for r in conn.execute("""SELECT pub.*,p.mode,p.package_json,p.video_id,
                v.youtube_id,v.slice_index FROM wallstreet_version_publications pub
                JOIN wallstreet_pairs p ON p.id=pub.pair_id JOIN processed_videos v ON v.id=p.video_id
                WHERE (? IS NULL OR p.id=?) ORDER BY pub.id""", (pair_id, pair_id))]

    def wallstreet_pinned_sources(self):
        with self.get_connection() as conn:
            return {r[0] for r in conn.execute("""SELECT DISTINCT v.youtube_id FROM wallstreet_pairs p
                JOIN processed_videos v ON v.id=p.video_id WHERE p.state!='CANCELED'
                  AND (p.state!='READY' OR EXISTS(SELECT 1 FROM wallstreet_version_publications pub
                    WHERE pub.pair_id=p.id AND pub.variant='B'
                      AND pub.state NOT IN ('PUBLISHED','REJECTED','CANCELED')))""")}

    def claim_wallstreet_render(self, *, now=None, lease_seconds=7200):
        now = time.time() if now is None else now
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("""SELECT * FROM wallstreet_pairs WHERE
                ((state IN ('QUEUED','RETRY') AND next_run_at<=?) OR
                 (state='RENDERING' AND lease_until<?)) ORDER BY id LIMIT 1""", (now, now)).fetchone()
            if not row:
                return None
            token = uuid.uuid4().hex
            conn.execute("""UPDATE wallstreet_pairs SET state='RENDERING',lease_token=?,lease_until=?,
                attempts=attempts+1 WHERE id=?""", (token, now+lease_seconds, row["id"]))
            return dict(conn.execute("SELECT * FROM wallstreet_pairs WHERE id=?", (row["id"],)).fetchone())

    def retry_wallstreet_render(self, pair_id):
        """仅调度失败加工；不触碰提交状态、尝试计数或有效执行租约。"""
        with self.get_connection() as conn:
            return conn.execute("""UPDATE wallstreet_pairs SET next_run_at=0
                WHERE id=? AND state='RETRY' AND lease_token IS NULL""", (pair_id,)).rowcount == 1

    def renew_wallstreet_render(self, pair_id, lease_token, lease_seconds, *, now=None):
        now = time.time() if now is None else now
        with self.get_connection() as conn:
            return conn.execute("""UPDATE wallstreet_pairs SET lease_until=? WHERE id=?
                AND state='RENDERING' AND lease_token=? AND lease_until>=?""",
                (now+lease_seconds,pair_id,lease_token,now)).rowcount == 1

    def finish_wallstreet_render(self, pair_id, lease_token, *, package=None, error=None, now=None):
        now = time.time() if now is None else now
        with self.get_connection() as conn:
            cursor = conn.execute("""UPDATE wallstreet_pairs SET state=?,package_json=?,last_error=?,
                next_run_at=?,lease_token=NULL,lease_until=NULL WHERE id=? AND state='RENDERING'
                  AND lease_token=? AND lease_until>=?""",
                ("READY" if package else "RETRY", json.dumps(package, ensure_ascii=False) if package else None,
                 error, now+900, pair_id, lease_token, now))
            return cursor.rowcount == 1

    def observe_wallstreet_publication(self, publication_id, *, state, platform_post_id=None,
                                      evidence_path, public_at=None, time_basis="first_observed_public",
                                      attempt_token=None, error=None):
        """管理页证据显式绑定作品 ID；晚到/错误尝试不能改写另一提交。"""
        if state not in {"UNCERTAIN","UNDER_REVIEW","PUBLISHED","REJECTED","CANCELED"}:
            raise ValueError("不允许以观察重置提交边界")
        if not evidence_path or (state == "PUBLISHED" and not platform_post_id):
            raise ValueError("公开记录必须有平台作品 ID 与回读证据")
        if time_basis not in {"platform", "first_observed_public"}:
            raise ValueError("无效的公开时间依据")
        if public_at is not None and (not isinstance(public_at,(int,float)) or isinstance(public_at,bool)
                or not math.isfinite(public_at) or not 0 < public_at <= time.time()):
            raise ValueError('无效的公开时间')
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute("SELECT * FROM wallstreet_version_publications WHERE id=?", (publication_id,)).fetchone()
            if not current:
                raise ValueError("发布实体不存在")
            if current["platform_post_id"] and platform_post_id and current["platform_post_id"] != platform_post_id:
                raise ValueError("作品 ID 不匹配，禁止覆盖")
            if attempt_token and current["attempt_token"] != attempt_token:
                raise ValueError("提交尝试不匹配")
            if current["state"] == "PUBLISHED" and state != "PUBLISHED":
                return False
            timestamp = public_at if public_at is not None else time.time()
            if time_basis == 'platform' and public_at is None:
                raise ValueError('平台时间必须有明确时间戳')
            calibrate = state == 'PUBLISHED' and time_basis == 'platform' and current['public_time_basis'] == 'first_observed_public'
            conn.execute("""UPDATE wallstreet_version_publications SET state=?,platform_post_id=COALESCE(?,platform_post_id),
                evidence_path=?,public_at=CASE WHEN ? THEN ? WHEN ?='PUBLISHED' THEN COALESCE(public_at,?) ELSE public_at END,
                public_time_basis=CASE WHEN ? THEN ? WHEN ?='PUBLISHED' THEN COALESCE(public_time_basis,?) ELSE public_time_basis END,
                next_readback_at=?,last_error=? WHERE id=?""",
                (state, platform_post_id, evidence_path, calibrate,timestamp,state,timestamp,calibrate,time_basis,state,time_basis,
                 time.time()+1800, error, publication_id))
            return True

    def claim_wallstreet_submission(self, publication_id, *, package_sha256, video_path, asset_sha256,
                                    evidence_path, now=None):
        """先提交意图再启动上传；进程中断后不自动把 SUBMITTING 回队。"""
        now = time.time() if now is None else now
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("""SELECT pub.*,p.mode,p.state AS render_state FROM wallstreet_version_publications pub
                JOIN wallstreet_pairs p ON p.id=pub.pair_id WHERE pub.id=?""", (publication_id,)).fetchone()
            if not row or row["variant"] != "B" or row["state"] != "WAITING" or row["render_state"] != "READY" or now < row['next_readback_at']:
                return None
            if row["mode"] == "PAIRED":
                a = conn.execute("""SELECT * FROM wallstreet_version_publications WHERE pair_id=?
                    AND variant='A' AND platform=? AND account=?""", (row["pair_id"],row["platform"],row["account"])).fetchone()
                config = conn.execute("SELECT * FROM wallstreet_experiment WHERE name=?", (EXPERIMENT,)).fetchone()
                if not a or a["state"] != "PUBLISHED" or not a["public_at"] or not config or now < a["public_at"] + config["delay_hours"]*3600:
                    return None
            for digest in (package_sha256, asset_sha256):
                if not self._is_sha256_digest(digest):
                    raise ValueError("缺少成片/投稿包指纹")
            token = uuid.uuid4().hex
            conn.execute("""UPDATE wallstreet_version_publications SET state='SUBMITTING',attempt_token=?,
                attempt_count=attempt_count+1,package_sha256=?,video_path=?,asset_sha256=?,evidence_path=? WHERE id=?""",
                (token,package_sha256,video_path,asset_sha256,evidence_path,publication_id))
            result = dict(conn.execute("SELECT * FROM wallstreet_version_publications WHERE id=?", (publication_id,)).fetchone())
            if row["platform"] == "douyin":
                result.update(self._insert_douyin_browser_launch_ticket(conn, source_type="EDITORIAL",
                    source_ref=f'{publication_id}:{result["attempt_count"]}', video_path=video_path,
                    asset_sha256=asset_sha256, payload_sha256=package_sha256))
            return result

    def recover_wallstreet_wechat_login_exit(self, publication_id, *, attempt_token,
                                            uploader_exit_code, evidence_path, retry_after_seconds=1800):
        """退出码 2 专用于文件上传前登录失败；其他未知结果绝不恢复。"""
        if uploader_exit_code != 2 or not attempt_token or not evidence_path or retry_after_seconds < 0:
            raise ValueError('缺少上传前登录退出的明确证据')
        with self.get_connection() as conn:
            return conn.execute("""UPDATE wallstreet_version_publications
                SET state='WAITING',attempt_token=NULL,evidence_path=?,next_readback_at=?,
                    last_error='上传前登录失败；未上传，可重新领取'
                WHERE id=? AND variant='B' AND platform='wechat'
                  AND state IN ('SUBMITTING','UNCERTAIN') AND platform_post_id IS NULL AND attempt_token=?""",
                (evidence_path,time.time()+retry_after_seconds,publication_id,attempt_token)).rowcount == 1

    def recover_unstarted_wallstreet_douyin(self, *, min_age_seconds=1800):
        """只恢复未打开浏览器的抖音尝试；先撤销票据，使迟到子进程失效。"""
        if min_age_seconds < 60:
            raise ValueError('恢复等待期至少 60 秒')
        with self.get_connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            rows = conn.execute("""SELECT pub.id,t.ticket_id FROM wallstreet_version_publications pub
                JOIN douyin_browser_launch_tickets t
                  ON t.source_type='EDITORIAL' AND t.source_ref=CAST(pub.id AS TEXT)||':'||CAST(pub.attempt_count AS TEXT)
                WHERE pub.platform='douyin' AND pub.variant='B' AND pub.state IN ('SUBMITTING','UNCERTAIN')
                  AND t.launch_started_at IS NULL AND t.prelaunch_canceled_at IS NULL
                  AND datetime(t.issued_at)<=datetime('now', ?)""", (f'-{min_age_seconds} seconds',)).fetchall()
            recovered = 0
            for row in rows:
                if self._cancel_unstarted_douyin_browser_ticket(conn,row['ticket_id'],'二创尝试超时，确认浏览器未启动'):
                    conn.execute("""UPDATE wallstreet_version_publications SET state='WAITING',attempt_token=NULL,
                        next_readback_at=0,last_error='浏览器未启动，票据已撤销，可安全重新领取' WHERE id=?""",(row['id'],))
                    recovered += 1
            return recovered

    def record_wallstreet_metrics(self, publication_id, *, platform_post_id, horizon_hours,
                                 captured_at, values, evidence_path):
        if horizon_hours not in {24,72,168} or not evidence_path or not math.isfinite(captured_at):
            raise ValueError("快照缺少时点或证据")
        for key, value in values.items():
            if key not in {"views","likes","comments","shares","favorites","completion_rate","average_watch_seconds","follows"}:
                raise ValueError("未知指标")
            if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value < 0):
                raise ValueError("指标应为非负真实读数或缺失")
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM wallstreet_version_publications WHERE id=?", (publication_id,)).fetchone()
            if not row or row["platform_post_id"] != platform_post_id or row["state"] != "PUBLISHED":
                raise ValueError("快照必须绑定同一已公开作品")
            if captured_at < row["public_at"]:
                raise ValueError("采集时间早于公开确认")
            conn.execute("""INSERT INTO wallstreet_metric_snapshots VALUES (?,?,?,?,?,?)
                ON CONFLICT(publication_id,horizon_hours) DO UPDATE SET captured_at=excluded.captured_at,
                evidence_path=excluded.evidence_path,values_json=excluded.values_json
                WHERE excluded.captured_at>=wallstreet_metric_snapshots.captured_at""",
                (publication_id,platform_post_id,horizon_hours,captured_at,evidence_path,json.dumps(values,sort_keys=True)))

    def get_wallstreet_metrics_report(self):
        with self.get_connection() as conn:
            rows = [dict(r) for r in conn.execute("""SELECT p.id AS pair_id,v.youtube_id,pub.variant,
                pub.platform,pub.account,pub.platform_post_id,pub.state,pub.public_at,pub.public_time_basis,
                m.horizon_hours,m.captured_at,m.evidence_path,m.values_json
                FROM wallstreet_pairs p JOIN processed_videos v ON v.id=p.video_id
                JOIN wallstreet_version_publications pub ON pub.pair_id=p.id
                LEFT JOIN wallstreet_metric_snapshots m ON m.publication_id=pub.id
                ORDER BY p.id,pub.platform,m.horizon_hours,pub.variant""")]
        for row in rows:
            values = json.loads(row.pop("values_json") or "{}")
            required = [values.get(k) for k in ("views","likes","comments","shares")]
            row["values"] = values
            row["interaction_rate"] = sum(required[1:])/required[0] if all(x is not None for x in required) and required[0] > 0 else None
            row["observed_age_hours"] = (row["captured_at"]-row["public_at"])/3600 if row["captured_at"] and row["public_at"] else None
        return rows
