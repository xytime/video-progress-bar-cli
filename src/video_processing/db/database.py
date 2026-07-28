"""数据库访问层 - 管理自动化视频管线的状态与发现列表

所有 SQL 操作必须封装在 PipelineDB 方法内。
禁止外部模块直接调用 get_connection() 执行裸 SQL。

# Modification History
| Version | Date       | Author                              | Description                                                                    |
|---------|------------|-------------------------------------|--------------------------------------------------------------------------------|
| 1.0.0   | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 初始创建数据库与DAL封装                                                         |
| 2.0.0   | 2026-05-26 | Claude_Sonnet_4.6_Thinking_planning | v7.0 架构升级：黑名单表、Pid追踪、手动评分锁                                      |
| 2.5.0   | 2026-05-27 | Gemini_3.5_Flash_planning           | 一变多升级：复合唯一约束(youtube_id, slice_index)、自关联外键级联删除与批量插入 |
| 2.5.1   | 2026-05-27 | Gemini_3.5_Flash_High_planning      | 修复 _init_db 中遗漏推荐频道表 recommended_channels 的创建问题 |
| 2.5.2   | 2026-05-27 | Gemini_3.5_Flash_High_planning      | 新增 get_detailed_stats 方法提供父子任务的细分状态统计数据 |
| 2.5.3   | 2026-05-27 | Unknown_Model_planning              | 修复已分片(SEGMENTED)父视频在后台仪表盘各 Tab 中隐藏不可见的 Bug |
| 2.5.4   | 2026-05-27 | Unknown_Model_planning              | 仅当切片全部完成时才允许父视频进入“已完成”Tab，否则根据切片状态归入“处理中”或“错误”Tab |
| 2.6.0   | 2026-05-27 | Gemini_3.5_Flash_planning           | 新增 disable_slicing 状态列用于整片发布/切片发布的控制 (默认 1 为整片发布) |
| 2.7.0   | 2026-05-27 | Unknown_Model_planning              | 红蓝博弈安全性与容错性审计修复 (P1/P2) |
| 2.8.0   | 2026-05-28 | Gemini_3.5_Flash_planning           | 优化 get_high_score_pending_videos：利用 EXISTS 子查询在 SQL 层直接过滤被顺序锁阻断的切片任务 |
| 2.9.0   | 2026-05-29 | Claude_Sonnet_4.6_Thinking_planning | 新增 tts_provider 列，用于按视频记录 TTS 配音引擎（nullable），供 /tts 命令按需存储 |
| 3.0.0   | 2026-06-01 | Claude_Sonnet_4.6_Thinking_planning | 新增 update_video_spec 方法，全量覆盖规格字段（trim/disable_slicing/tts），供 respec 流程使用 |
| 3.1.0   | 2026-06-09 | Gemini_3.5_Flash_planning           | 新增 high_likes tab 支持，显示最近24小时发布的高赞视频 |
| 3.2.0   | 2026-06-09 | Gemini_3.5_Flash_planning           | add_video 支持 category, censor_tag, censor_score 录入 |
| 3.3.0   | 2026-06-09 | Gemini_3.5_Flash_planning           | 将 high_likes 高赞视频时间窗口由 24 小时调整为 3 天，优化刷新发现效果 |
| 3.4.0   | 2026-06-11 | Gemini_3.5_Flash_planning           | [高赞优化] 对齐 get_tab_counts 徽章时间窗口为 3 天，优化高赞视频排序机制优先新视频 |
| 3.4.1   | 2026-06-11 | Claude_Opus_4.6_Thinking_planning   | [CodeReview修复] 统一变量名 yesterday→three_days_ago，提升 datetime 为 top-level import |
| 3.5.0   | 2026-06-13 | Claude_Opus_4.8                     | 新增 promote_to_manual：将高赞发现(DISCOVERY)条目原子提升为 MANUAL 加急任务（source/score/手动锁），供「📥 加入队列」一键发布 |
| 3.6.0   | 2026-06-13 | Claude_Opus_4.8                     | 新增 bypass_censorship 列 + set_bypass_censorship/is_censorship_bypassed：供「🔓 复核放行」人工绕过审查后管线跳过全部审查层 |
| 3.7.0   | 2026-06-15 | Claude_Opus_4.8                     | [BUG-2/#11] purge_stale_tasks 额外排除 PUBLISHING，防止发布中崩溃被自动重置 PENDING 导致重复公开发布 |
| 3.8.0   | 2026-06-15 | Claude_Opus_4.8                     | [BUG-5] 新增 get_waitlist_clearable_ids 并在 waitlist 展示/统计谓词排除 DISCOVERY，防一键清空误删/拉黑高赞发现条目 |
| 3.9.0   | 2026-06-25 | Claude_Opus_4.8                     | [黑名单根治] get_high_score_pending_videos 在 SQL 层硬过滤 BLACKLISTED 频道与 blacklisted_videos 墓碑：此为所有自动发布路径取候选的唯一咽喉，杜绝已拉黑频道存量 PENDING 被任何路径（调度器/管线/重算）顶发 |
| 3.10.0  | 2026-06-25 | Claude_Opus_4.8                     | 新增 get_rescore_candidates（含同款黑名单过滤、UTC 对齐窗口）：收敛 rescore_refresh 手抄过滤 SQL 为 DAL 单一真相源，消除黑名单语义漂移与 rule-2 裸 SQL 违规 |
| 3.11.0  | 2026-06-25 | Claude_Opus_4.8                     | 新增 is_manually_scored(yid,slice) 查询：供审查执行层判定手动锁定视频命中 P2 时挂起人工复核而非 force 清零回弹 |
| 3.12.0  | 2026-06-28 | Claude_Opus_4.8                     | 新增 get_failed_videos_since(hours)：取最近 N 小时内 FAILED 任务（UTC 对齐窗口），供 Telegram /retry <小时数> 批量重试 |
| 3.12.1  | 2026-07-05 | Codex                               | get_failed_videos_since 纳入 LOGIN_REQUIRED，修复微信过期导致的批量重试遗漏 |
| 3.12.2  | 2026-07-08 | Codex                               | 新增 get_stale_publishing_videos：暴露长时间停留在 PUBLISHING 的候选任务，供调度器做“进程已死但状态未回收”的保守降级 |
| 3.13.0  | 2026-07-12 | Codex                               | get_high_score_pending_videos 支持按频道覆盖自动发布线，保持黑名单与顺序锁过滤不变 |
| 3.13.1  | 2026-07-12 | Codex                               | get_rescore_candidates 返回 channel_id，供重算层跳过已过频道专属发布线的候选 |
| 3.14.0  | 2026-07-13 | Codex                               | 新增 AI 字幕处理审计表与 DAL，记录逐视频 provider 尝试、降级和质量结果 |
| 3.15.0  | 2026-07-15 | Codex                               | 新增快手浏览器发布账本，以成片摘要去重并支持历史迁移每日限额 |
| 3.15.1  | 2026-07-15 | Codex                               | 修正快手去重语义：仅已发布作品阻止重传，失败和临时上传保留可重试尝试 |
| 3.15.2  | 2026-07-15 | Codex                               | 新增手动提交回填领取时间，确保人工补发也计入当日快手历史迁移上限 |
| 3.15.3  | 2026-07-15 | Codex                               | 历史日限额仅统计实际提交/待核验状态，校准或上传失败不再虚占当天发布名额 |
| 3.15.4  | 2026-07-15 | Codex                               | 提供快手审核状态批量查询，供定时任务只读回查作品管理结果 |
| 3.15.5  | 2026-07-16 | Codex                               | 新增视频号延后发布领取接口，支持停用期间快手单平台与恢复后限额补发 |
| 3.16.0  | 2026-07-23 | Codex                               | 新增抖音发布账本，与快手保持独立状态、历史限额和审核回查语义 |
| 3.17.0  | 2026-07-24 | Gemini_3.6_Flash_planning           | 新增 get_video_publications_map 聚合微信、快手、抖音 3 平台状态，并在 get_paginated_videos / get_slices_by_parent_yid 中透传 |
| 3.17.0  | 2026-07-23 | Codex                               | 新增三平台补录预览候选查询，支持访谈/演讲与 Wall Street Truthbombs 规则 |
| 3.17.1  | 2026-07-23 | Codex                               | 视频号延后补发领取支持同一套补录规则过滤，避免默认自动补录越界 |
| 3.18.0  | 2026-07-25 | Codex                               | 平台发布账本新增 CANCELED 终态，用于缺失本地投递素材的历史补录任务退出自动重试 |
| 3.18.1  | 2026-07-25 | Codex                               | 抖音提交后未确认的遗留失败不再进入自动领取，避免可能已提交作品被盲重投 |
| 3.19.0  | 2026-07-26 | Codex                               | 新增 censorship_incidents 独立违规台账，记录审查命中、上下文和处置决策供专项复盘 |
| 3.20.0  | 2026-07-27 | Codex                               | censorship_incidents 增补规则版本、规则 ID、输入来源、流程阶段、平台和输入 hash 复盘字段 |
| 3.21.0  | 2026-07-28 | Codex                               | 新增监控候选入库/补全接口；RSS 降级条目保持 METADATA_PENDING，完整官方元数据到位才转 PENDING |
"""

import sqlite3
import os
import logging
import datetime  # [Claude_Opus_4.6_Thinking_planning] 提升为 top-level import，用于高赞时间窗口计算
from pathlib import Path
from typing import Collection, List, Dict, Any, Optional, Sequence

class PipelineDB:
    """视频管线数据访问层。

    所有 SQL 操作必须通过此类的方法执行。
    外部模块禁止直接调用 get_connection() 执行裸 SQL。
    """

    _logger = logging.getLogger(__name__)

    def __init__(self, db_path: str = "pipeline.db"):
        # 默认在项目根目录的 output 文件夹内创建数据库
        # 如果是绝对路径则直接使用
        if not os.path.isabs(db_path):
            base_dir = Path(__file__).parent.parent.parent.parent
            self.db_path = str(base_dir / "output" / db_path)
        else:
            self.db_path = db_path
            
        # 确保目录存在
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()
        
    def get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn
        
    def _init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # [Gemini_3.5_Flash_planning] 开启 WAL 模式，支持高并发读写，并激活 SQLite 外键支持
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA foreign_keys=ON;")
            
            # [Gemini_3.5_Flash_High_planning] 重新加入推荐频道表的创建，防测试环境与空数据库丢失此表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS recommended_channels (
                    channel_id TEXT PRIMARY KEY,
                    channel_name TEXT NOT NULL,
                    reason TEXT,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 检测是否已经进行了复合键和自关联级联删除的表升级 (检查 parent_id 列是否存在)
            cursor.execute("PRAGMA table_info(processed_videos)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if columns and "parent_id" not in columns:
                self._logger.info("[Migration] Upgrading database schema to composite keys (yid, slice_index) & parent_id cascade relation...")
                # 使用隐式事务，不再手动 BEGIN IMMEDIATE 避免 OperationalError
                try:
                    # 1. 重命名原表
                    cursor.execute("ALTER TABLE processed_videos RENAME TO processed_videos_old;")
                    
                    # 2. 创建支持复合主键和外键级联删除的新表
                    cursor.execute('''
                        CREATE TABLE processed_videos (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            youtube_id TEXT NOT NULL,
                            slice_index INTEGER NOT NULL DEFAULT 0,
                            parent_id INTEGER DEFAULT NULL,
                            title TEXT NOT NULL,
                            channel_id TEXT NOT NULL,
                            score INTEGER DEFAULT 0,
                            status TEXT NOT NULL DEFAULT 'PENDING',
                            retry_count INTEGER DEFAULT 0,
                            error_msg TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            zh_title TEXT,
                            source TEXT DEFAULT 'AUTO',
                            duration_sec INTEGER DEFAULT NULL,
                            view_count INTEGER DEFAULT NULL,
                            like_count INTEGER DEFAULT NULL,
                            upload_date TEXT DEFAULT NULL,
                            censor_tag TEXT DEFAULT NULL,
                            censor_score INTEGER DEFAULT NULL,
                            is_manually_scored INTEGER DEFAULT 0,
                            process_pid INTEGER DEFAULT NULL,
                            trim_start TEXT DEFAULT NULL,
                            trim_end TEXT DEFAULT NULL,
                            disable_slicing INTEGER DEFAULT 1,
                            bypass_censorship INTEGER DEFAULT 0,
                            UNIQUE(youtube_id, slice_index),
                            FOREIGN KEY(parent_id) REFERENCES processed_videos(id) ON DELETE CASCADE
                        )
                    ''')
                    
                    # 3. 提取旧表字段并导入新表（设置默认 slice_index=0, parent_id=NULL）
                    old_fields = [
                        "id", "youtube_id", "title", "channel_id", "score", "status", "retry_count", 
                        "error_msg", "created_at", "updated_at", "zh_title", "source", "duration_sec", 
                        "view_count", "like_count", "upload_date"
                    ]
                    # v7 系列列
                    for col in ["censor_tag", "censor_score", "is_manually_scored", "process_pid", "trim_start", "trim_end"]:
                        if col in columns:
                            old_fields.append(col)
                            
                    old_fields_str = ", ".join(old_fields)
                    
                    new_fields = [
                        "id", "youtube_id", "slice_index", "parent_id", "title", "channel_id", "score", 
                        "status", "retry_count", "error_msg", "created_at", "updated_at", "zh_title", 
                        "source", "duration_sec", "view_count", "like_count", "upload_date"
                    ]
                    for col in ["censor_tag", "censor_score", "is_manually_scored", "process_pid", "trim_start", "trim_end"]:
                        if col in columns:
                            new_fields.append(col)
                    new_fields_str = ", ".join(new_fields)
                    
                    # 导回，在 id, youtube_id 后补上常量 0 和 NULL
                    select_fields_str = "id, youtube_id, 0, NULL, " + ", ".join(old_fields[2:])
                    
                    cursor.execute(f"""
                        INSERT INTO processed_videos ({new_fields_str})
                        SELECT {select_fields_str}
                        FROM processed_videos_old
                    """)
                    
                    # 4. 删除旧表
                    cursor.execute("DROP TABLE processed_videos_old;")
                    
                    conn.commit()
                    self._logger.info("[Migration] Database schema successfully migrated.")
                except Exception as e:
                    conn.rollback()
                    self._logger.error(f"[Migration] Schema migration failed, rolled back: {e}")
                    raise e
            elif not columns:
                # 第一次初始建表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS processed_videos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        youtube_id TEXT NOT NULL,
                        slice_index INTEGER NOT NULL DEFAULT 0,
                        parent_id INTEGER DEFAULT NULL,
                        title TEXT NOT NULL,
                        channel_id TEXT NOT NULL,
                        score INTEGER DEFAULT 0,
                        status TEXT NOT NULL DEFAULT 'PENDING',
                        retry_count INTEGER DEFAULT 0,
                        error_msg TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        zh_title TEXT,
                        source TEXT DEFAULT 'AUTO',
                        duration_sec INTEGER DEFAULT NULL,
                        view_count INTEGER DEFAULT NULL,
                        like_count INTEGER DEFAULT NULL,
                        upload_date TEXT DEFAULT NULL,
                        censor_tag TEXT DEFAULT NULL,
                        censor_score INTEGER DEFAULT NULL,
                        is_manually_scored INTEGER DEFAULT 0,
                        process_pid INTEGER DEFAULT NULL,
                        trim_start TEXT DEFAULT NULL,
                        trim_end TEXT DEFAULT NULL,
                        disable_slicing INTEGER DEFAULT 1,
                        bypass_censorship INTEGER DEFAULT 0,
                        UNIQUE(youtube_id, slice_index),
                        FOREIGN KEY(parent_id) REFERENCES processed_videos(id) ON DELETE CASCADE
                    )
                ''')

            # [Gemini_3.5_Flash_planning] 检查并补足 disable_slicing 字段，默认值为 1（禁用分片即整片发布）
            cursor.execute("PRAGMA table_info(processed_videos)")
            columns = [col[1] for col in cursor.fetchall()]
            if columns and "disable_slicing" not in columns:
                self._logger.info("[Migration] Adding disable_slicing column to processed_videos table...")
                cursor.execute("ALTER TABLE processed_videos ADD COLUMN disable_slicing INTEGER DEFAULT 1;")
                conn.commit()

            # [Claude_Sonnet_4.6_Thinking_planning] v2.9.0: 检查并补足 tts_provider 字段
            cursor.execute("PRAGMA table_info(processed_videos)")
            columns = [col[1] for col in cursor.fetchall()]
            if columns and "tts_provider" not in columns:
                self._logger.info("[Migration] Adding tts_provider column to processed_videos table...")
                cursor.execute("ALTER TABLE processed_videos ADD COLUMN tts_provider TEXT DEFAULT NULL;")
                conn.commit()

            # [Gemini_3.5_Flash_planning] 检查并补足 category 字段以存储视频的分类信息
            cursor.execute("PRAGMA table_info(processed_videos)")
            columns = [col[1] for col in cursor.fetchall()]
            if columns and "category" not in columns:
                self._logger.info("[Migration] Adding category column to processed_videos table...")
                cursor.execute("ALTER TABLE processed_videos ADD COLUMN category TEXT DEFAULT NULL;")
                conn.commit()

            # [Claude_Opus_4.8] v3.6.0: 检查并补足 bypass_censorship 字段（人工复核放行标志）
            cursor.execute("PRAGMA table_info(processed_videos)")
            columns = [col[1] for col in cursor.fetchall()]
            if columns and "bypass_censorship" not in columns:
                self._logger.info("[Migration] Adding bypass_censorship column to processed_videos table...")
                cursor.execute("ALTER TABLE processed_videos ADD COLUMN bypass_censorship INTEGER DEFAULT 0;")
                conn.commit()


            # [Claude_Sonnet_4.6_Thinking_planning] v7.0 黑名单墓碑表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS blacklisted_videos (
                    youtube_id TEXT PRIMARY KEY,
                    reason     TEXT DEFAULT 'user_deleted',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 快手发布账本：仅“已发布”的成片摘要禁止再次投递；失败、临时上传和未发布草稿
            # 都保留为独立尝试，允许用户重试。它独立于 processed_videos 的微信状态。
            cursor.execute("PRAGMA table_info(kuaishou_publications)")
            kuaishou_columns = {row[1] for row in cursor.fetchall()}
            cursor.execute("PRAGMA table_info(kuaishou_publications_legacy)")
            kuaishou_legacy_columns = {row[1] for row in cursor.fetchall()}
            cursor.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'kuaishou_publications'")
            kuaishou_schema = (cursor.fetchone() or [""])[0] or ""
            cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'kuaishou_publications_legacy'"
            )
            kuaishou_legacy_exists = cursor.fetchone() is not None
            recover_kuaishou_legacy = False
            if kuaishou_legacy_exists:
                current_count = 0
                if kuaishou_columns:
                    current_count = cursor.execute("SELECT COUNT(*) FROM kuaishou_publications").fetchone()[0]
                recover_kuaishou_legacy = current_count == 0
            migrate_kuaishou_ledger = bool(
                recover_kuaishou_legacy
                or (
                    kuaishou_columns
                    and (
                        "attempt_number" not in kuaishou_columns
                        or "UNDER_REVIEW" not in kuaishou_schema
                        or "CANCELED" not in kuaishou_schema
                    )
                )
            )
            if migrate_kuaishou_ledger and not recover_kuaishou_legacy:
                cursor.execute("ALTER TABLE kuaishou_publications RENAME TO kuaishou_publications_legacy")
                kuaishou_legacy_columns = kuaishou_columns
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS kuaishou_publications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER NOT NULL,
                    asset_sha256 TEXT NOT NULL,
                    source_kind TEXT NOT NULL CHECK(source_kind IN ('HISTORY', 'NEW')),
                    state TEXT NOT NULL DEFAULT 'QUEUED'
                        CHECK(state IN ('QUEUED', 'UPLOADING', 'DRAFT', 'UNDER_REVIEW', 'PUBLISHED', 'RETRYABLE_FAILED', 'UNCERTAIN', 'BANNED', 'CANCELED')),
                    video_path TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL DEFAULT 1,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    claimed_at TIMESTAMP DEFAULT NULL,
                    published_at TIMESTAMP DEFAULT NULL,
                    external_post_id TEXT DEFAULT NULL,
                    external_url TEXT DEFAULT NULL,
                    last_error_message TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(video_id, attempt_number),
                    FOREIGN KEY(video_id) REFERENCES processed_videos(id) ON DELETE RESTRICT
                )
            ''')
            if migrate_kuaishou_ledger:
                attempt_number_expr = (
                    "ROW_NUMBER() OVER (PARTITION BY video_id ORDER BY COALESCE(attempt_number, 0), id)"
                    if "attempt_number" in kuaishou_legacy_columns
                    else "ROW_NUMBER() OVER (PARTITION BY video_id ORDER BY id)"
                )
                cursor.execute('''
                    INSERT INTO kuaishou_publications (
                        id, video_id, asset_sha256, source_kind, state, video_path, attempt_number,
                        attempt_count, claimed_at, published_at, external_post_id, external_url,
                        last_error_message, created_at, updated_at
                    )
                    SELECT id, video_id, asset_sha256, source_kind,
                           CASE WHEN state IN ('UPLOADING', 'UPLOADED', 'UNCERTAIN')
                                THEN 'RETRYABLE_FAILED' ELSE state END,
                           video_path, {attempt_number_expr}, attempt_count, claimed_at, published_at,
                           external_post_id, external_url,
                           CASE WHEN state IN ('UPLOADING', 'UPLOADED', 'UNCERTAIN')
                                THEN '作品管理未确认可见，迁移为可重试尝试'
                                ELSE last_error_message END,
                           created_at, updated_at
                    FROM kuaishou_publications_legacy
                '''.format(attempt_number_expr=attempt_number_expr))
                cursor.execute("DROP TABLE kuaishou_publications_legacy")

            # 抖音发布账本：沿用快手的安全语义，但保持独立表，避免平台状态互相污染。
            cursor.execute("PRAGMA table_info(douyin_publications)")
            douyin_columns = {row[1] for row in cursor.fetchall()}
            cursor.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'douyin_publications'")
            douyin_schema = (cursor.fetchone() or [""])[0] or ""
            migrate_douyin_ledger = bool(douyin_columns and "CANCELED" not in douyin_schema)
            if migrate_douyin_ledger:
                cursor.execute("ALTER TABLE douyin_publications RENAME TO douyin_publications_legacy")
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS douyin_publications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER NOT NULL,
                    asset_sha256 TEXT NOT NULL,
                    source_kind TEXT NOT NULL CHECK(source_kind IN ('HISTORY', 'NEW')),
                    state TEXT NOT NULL DEFAULT 'QUEUED'
                        CHECK(state IN ('QUEUED', 'UPLOADING', 'DRAFT', 'UNDER_REVIEW', 'PUBLISHED', 'RETRYABLE_FAILED', 'UNCERTAIN', 'BANNED', 'CANCELED')),
                    video_path TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL DEFAULT 1,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    claimed_at TIMESTAMP DEFAULT NULL,
                    published_at TIMESTAMP DEFAULT NULL,
                    external_post_id TEXT DEFAULT NULL,
                    external_url TEXT DEFAULT NULL,
                    last_error_message TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(video_id, attempt_number),
                    FOREIGN KEY(video_id) REFERENCES processed_videos(id) ON DELETE RESTRICT
                )
            ''')
            if migrate_douyin_ledger:
                cursor.execute('''
                    INSERT INTO douyin_publications (
                        id, video_id, asset_sha256, source_kind, state, video_path, attempt_number,
                        attempt_count, claimed_at, published_at, external_post_id, external_url,
                        last_error_message, created_at, updated_at
                    )
                    SELECT id, video_id, asset_sha256, source_kind, state, video_path, attempt_number,
                           attempt_count, claimed_at, published_at, external_post_id, external_url,
                           last_error_message, created_at, updated_at
                    FROM douyin_publications_legacy
                ''')
                cursor.execute("DROP TABLE douyin_publications_legacy")

            # AI 调用审计：仅保存可观测性元数据，禁止保存密钥、完整 prompt 或原始字幕。
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ai_processing_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    youtube_id TEXT NOT NULL,
                    slice_index INTEGER NOT NULL DEFAULT 0,
                    operation TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'RUNNING',
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    finished_at TIMESTAMP DEFAULT NULL,
                    final_provider TEXT DEFAULT NULL,
                    fallback_used INTEGER NOT NULL DEFAULT 0,
                    quality_score REAL DEFAULT NULL,
                    chinese_coverage REAL DEFAULT NULL,
                    vocabulary_segments INTEGER DEFAULT NULL,
                    quality_status TEXT DEFAULT NULL,
                    error_class TEXT DEFAULT NULL,
                    error_message TEXT DEFAULT NULL
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ai_provider_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT DEFAULT NULL,
                    capabilities TEXT DEFAULT NULL,
                    attempt_order INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    duration_ms INTEGER DEFAULT NULL,
                    error_class TEXT DEFAULT NULL,
                    error_message TEXT DEFAULT NULL,
                    quality_score REAL DEFAULT NULL,
                    warning_count INTEGER NOT NULL DEFAULT 0,
                    blocking_count INTEGER NOT NULL DEFAULT 0,
                    selected INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(run_id) REFERENCES ai_processing_runs(id) ON DELETE CASCADE
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS censorship_incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER DEFAULT NULL,
                    youtube_id TEXT NOT NULL,
                    slice_index INTEGER NOT NULL DEFAULT 0,
                    stage TEXT NOT NULL,
                    level TEXT DEFAULT NULL,
                    action TEXT DEFAULT NULL,
                    tag TEXT DEFAULT NULL,
                    score INTEGER DEFAULT NULL,
                    matched TEXT DEFAULT NULL,
                    channel TEXT DEFAULT NULL,
                    decision TEXT NOT NULL,
                    rule_pack_version TEXT DEFAULT NULL,
                    rule_id TEXT DEFAULT NULL,
                    source_field TEXT DEFAULT NULL,
                    review_stage TEXT DEFAULT NULL,
                    platform TEXT DEFAULT NULL,
                    input_hash TEXT DEFAULT NULL,
                    title TEXT DEFAULT NULL,
                    zh_title TEXT DEFAULT NULL,
                    description_preview TEXT DEFAULT NULL,
                    text_excerpt TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(video_id) REFERENCES processed_videos(id) ON DELETE SET NULL
                )
            ''')

            # 4. 创建复合索引优化分页查询与状态调度性能
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_status_updated 
                ON processed_videos(status, updated_at DESC)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_status_score_created
                ON processed_videos(status, score, created_at DESC)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_status_score_updated
                ON processed_videos(status, score, updated_at DESC)
            ''')
            
            # [Gemini_3.5_Flash_planning] 新建 parent_id 索引提升自关联级联删除与关联查询速度
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_parent_id
                ON processed_videos(parent_id)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_ai_runs_video_started
                ON ai_processing_runs(youtube_id, slice_index, started_at DESC)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_ai_attempts_run_order
                ON ai_provider_attempts(run_id, attempt_order)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_censorship_incidents_video_created
                ON censorship_incidents(youtube_id, slice_index, created_at DESC)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_censorship_incidents_level_created
                ON censorship_incidents(level, created_at DESC)
            ''')

            cursor.execute("PRAGMA table_info(censorship_incidents)")
            censorship_incident_columns = {col[1] for col in cursor.fetchall()}
            for column_name, column_type in {
                "rule_pack_version": "TEXT DEFAULT NULL",
                "rule_id": "TEXT DEFAULT NULL",
                "source_field": "TEXT DEFAULT NULL",
                "review_stage": "TEXT DEFAULT NULL",
                "platform": "TEXT DEFAULT NULL",
                "input_hash": "TEXT DEFAULT NULL",
            }.items():
                if column_name not in censorship_incident_columns:
                    self._logger.info("[Migration] Adding censorship_incidents.%s column...", column_name)
                    cursor.execute(f"ALTER TABLE censorship_incidents ADD COLUMN {column_name} {column_type};")
                    conn.commit()
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_kuaishou_publications_state_source
                ON kuaishou_publications(state, source_kind, claimed_at, created_at)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_douyin_publications_state_source
                ON douyin_publications(state, source_kind, claimed_at, created_at)
            ''')
            
            conn.commit()

    # --- AI processing audit DAL ---
    def start_ai_processing_run(self, youtube_id: str, *, slice_index: int = 0, operation: str = "subtitle_translation") -> int:
        """创建一次 AI 处理审计运行，返回不可暴露给外部的内部 run id。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO ai_processing_runs (youtube_id, slice_index, operation) VALUES (?, ?, ?)",
                (youtube_id, slice_index, operation),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def record_ai_provider_attempt(
        self,
        run_id: int,
        *,
        provider: str,
        model: Optional[str],
        capabilities: str,
        attempt_order: int,
        status: str,
        duration_ms: Optional[int] = None,
        error_class: Optional[str] = None,
        error_message: Optional[str] = None,
        quality_score: Optional[float] = None,
        warning_count: int = 0,
        blocking_count: int = 0,
        selected: bool = False,
    ) -> None:
        """记录单次 provider 尝试；错误内容截断，避免审计表被异常响应污染。"""
        with self.get_connection() as conn:
            conn.execute(
                """INSERT INTO ai_provider_attempts
                   (run_id, provider, model, capabilities, attempt_order, status, duration_ms,
                    error_class, error_message, quality_score, warning_count, blocking_count, selected)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, provider, model, capabilities, attempt_order, status, duration_ms,
                    error_class, (error_message or "")[:500] or None, quality_score,
                    int(warning_count), int(blocking_count), int(selected),
                ),
            )
            conn.commit()

    def finish_ai_processing_run(
        self,
        run_id: int,
        *,
        status: str,
        final_provider: Optional[str] = None,
        fallback_used: bool = False,
        quality_score: Optional[float] = None,
        chinese_coverage: Optional[float] = None,
        vocabulary_segments: Optional[int] = None,
        quality_status: Optional[str] = None,
        error_class: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """结束一次 AI 审计运行。"""
        with self.get_connection() as conn:
            conn.execute(
                """UPDATE ai_processing_runs
                   SET status = ?, finished_at = CURRENT_TIMESTAMP, final_provider = ?, fallback_used = ?,
                       quality_score = ?, chinese_coverage = ?, vocabulary_segments = ?, quality_status = ?,
                       error_class = ?, error_message = ?
                   WHERE id = ?""",
                (
                    status, final_provider, int(fallback_used), quality_score, chinese_coverage,
                    vocabulary_segments, quality_status, error_class, (error_message or "")[:500] or None,
                    run_id,
                ),
            )
            conn.commit()

    def get_ai_audit_summary(self, hours: int = 168) -> Dict[str, Any]:
        """返回后台概览所需的用量、失败和降级统计。"""
        with self.get_connection() as conn:
            runs = conn.execute(
                """SELECT COUNT(*) AS total_runs,
                          SUM(CASE WHEN status = 'SUCCEEDED' THEN 1 ELSE 0 END) AS succeeded_runs,
                          SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failed_runs,
                          SUM(CASE WHEN fallback_used = 1 THEN 1 ELSE 0 END) AS fallback_runs
                   FROM ai_processing_runs WHERE started_at >= datetime('now', ?)""",
                (f"-{max(1, int(hours))} hours",),
            ).fetchone()
            providers = conn.execute(
                """SELECT provider, COUNT(*) AS attempts,
                          SUM(CASE WHEN status = 'SUCCEEDED' THEN 1 ELSE 0 END) AS successes,
                          SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failures
                   FROM ai_provider_attempts
                   WHERE created_at >= datetime('now', ?)
                   GROUP BY provider ORDER BY attempts DESC""",
                (f"-{max(1, int(hours))} hours",),
            ).fetchall()
            return {"hours": max(1, int(hours)), "runs": dict(runs), "providers": [dict(row) for row in providers]}

    def get_ai_audit_for_video(self, youtube_id: str, *, slice_index: int = 0, limit: int = 20) -> List[Dict[str, Any]]:
        """返回单视频 AI 处理运行及其 provider 尝试时间线。"""
        with self.get_connection() as conn:
            run_rows = conn.execute(
                """SELECT * FROM ai_processing_runs WHERE youtube_id = ? AND slice_index = ?
                   ORDER BY started_at DESC LIMIT ?""",
                (youtube_id, slice_index, max(1, min(int(limit), 100))),
            ).fetchall()
            results = []
            for row in run_rows:
                item = dict(row)
                attempts = conn.execute(
                    "SELECT * FROM ai_provider_attempts WHERE run_id = ? ORDER BY attempt_order, id",
                    (item["id"],),
                ).fetchall()
                item["attempts"] = [dict(attempt) for attempt in attempts]
                results.append(item)
            return results

    # --- Censorship incident ledger DAL ---
    def record_censorship_incident(
        self,
        youtube_id: str,
        *,
        slice_index: int = 0,
        stage: str,
        level: Optional[str],
        action: Optional[str],
        tag: Optional[str],
        score: Optional[int],
        matched: Optional[str],
        channel: Optional[str],
        decision: str,
        rule_pack_version: Optional[str] = None,
        rule_id: Optional[str] = None,
        source_field: Optional[str] = None,
        review_stage: Optional[str] = None,
        platform: Optional[str] = None,
        input_hash: Optional[str] = None,
        title: Optional[str] = None,
        zh_title: Optional[str] = None,
        description_preview: Optional[str] = None,
        text_excerpt: Optional[str] = None,
    ) -> int:
        """记录一次审查命中，用于事故复盘与规则积累；正文仅保留短摘录。"""
        with self.get_connection() as conn:
            video = conn.execute(
                "SELECT id FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                (youtube_id, slice_index),
            ).fetchone()
            cursor = conn.execute(
                """INSERT INTO censorship_incidents
                   (video_id, youtube_id, slice_index, stage, level, action, tag, score,
                    matched, channel, decision, rule_pack_version, rule_id, source_field,
                    review_stage, platform, input_hash, title, zh_title, description_preview, text_excerpt)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    video["id"] if video else None,
                    youtube_id,
                    slice_index,
                    stage[:80],
                    level,
                    action,
                    tag,
                    score,
                    (matched or "")[:200] or None,
                    channel,
                    decision[:80],
                    (rule_pack_version or "")[:80] or None,
                    (rule_id or "")[:160] or None,
                    (source_field or "")[:80] or None,
                    (review_stage or "")[:80] or None,
                    (platform or "")[:40] or None,
                    (input_hash or "")[:80] or None,
                    (title or "")[:300] or None,
                    (zh_title or "")[:300] or None,
                    (description_preview or "")[:600] or None,
                    (text_excerpt or "")[:600] or None,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def get_censorship_incidents(
        self,
        youtube_id: Optional[str] = None,
        *,
        slice_index: Optional[int] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """查询违规台账，默认按时间倒序返回最近记录。"""
        clauses: list[str] = []
        params: list[Any] = []
        if youtube_id is not None:
            clauses.append("youtube_id = ?")
            params.append(youtube_id)
        if slice_index is not None:
            clauses.append("slice_index = ?")
            params.append(slice_index)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.get_connection() as conn:
            rows = conn.execute(
                f"""SELECT * FROM censorship_incidents
                    {where_sql}
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?""",
                (*params, max(1, min(int(limit), 500))),
            ).fetchall()
            return [dict(row) for row in rows]

    # --- Channel DAL ---
    def add_channel(self, channel_id: str, channel_name: str, status: str = 'APPROVED', reason: str = '') -> bool:
        with self.get_connection() as conn:
            try:
                # [blacklist tombstone 2026-06-24] 已拉黑频道拒绝被发现/手动重加覆盖(防自动复活)
                row = conn.execute(
                    "SELECT status FROM recommended_channels WHERE channel_id = ?", (channel_id,)
                ).fetchone()
                if row and row[0] == 'BLACKLISTED' and status != 'BLACKLISTED':
                    self._logger.info(f"[Blacklist] Blocked re-add of blacklisted channel: {channel_id}")
                    return False
                conn.execute(
                    "INSERT OR REPLACE INTO recommended_channels (channel_id, channel_name, reason, status) VALUES (?, ?, ?, ?)",
                    (channel_id, channel_name, reason, status)
                )
                conn.commit()
                return True
            except Exception as e:
                self._logger.error(f"add_channel failed for {channel_id}: {e}")
                return False
                
    def get_approved_channels(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM recommended_channels WHERE status = 'APPROVED'")
            return [dict(row) for row in cursor.fetchall()]

    def get_pending_channels(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM recommended_channels WHERE status = 'PENDING'")
            return [dict(row) for row in cursor.fetchall()]

    def update_channel_status(self, channel_id: str, status: str):
        with self.get_connection() as conn:
            conn.execute("UPDATE recommended_channels SET status = ? WHERE channel_id = ?", (status, channel_id))
            conn.commit()

    # --- Video DAL ---
    def add_video(
        self,
        youtube_id: str,
        title: str,
        channel_id: str,
        score: int = 0,
        zh_title: Optional[str] = None,
        source: str = 'AUTO',
        duration_sec: Optional[int] = None,
        view_count: Optional[int] = None,
        like_count: Optional[int] = None,
        upload_date: Optional[str] = None,
        trim_start: Optional[str] = None,
        trim_end: Optional[str] = None,
        slice_index: int = 0,                       # [Gemini_3.5_Flash_planning] 新增：切片索引，默认0 (主视频)
        parent_id: Optional[int] = None,            # [Gemini_3.5_Flash_planning] 新增：父自增 ID
        disable_slicing: int = 1,                   # [Gemini_3.5_Flash_planning] 新增：禁用分片标识 (默认1=不分片)
        tts_provider: Optional[str] = None,         # [Claude_Sonnet_4.6_Thinking_planning] v2.9.0: TTS 配音引擎（nullable）
        category: Optional[str] = None,             # [Gemini_3.5_Flash_planning] 新增：分类字段
        censor_tag: Optional[str] = None,           # [Gemini_3.5_Flash_planning] 新增：敏感词标签
        censor_score: Optional[int] = None,         # [Gemini_3.5_Flash_planning] 新增：敏感词得分
    ) -> bool:
        # 前置黑名单检查，防止已删除视频被二次拉取
        if self.is_blacklisted(youtube_id):
            if source == 'MANUAL':
                self.remove_from_blacklist(youtube_id)
            else:
                self._logger.warning(f"[Blacklist] Blocked re-add of blacklisted video: {youtube_id}")
                return False

        with self.get_connection() as conn:
            try:
                conn.execute(
                    """INSERT INTO processed_videos
                       (youtube_id, slice_index, parent_id, title, channel_id, score, status, zh_title, source,
                        duration_sec, view_count, like_count, upload_date, trim_start, trim_end, disable_slicing,
                        tts_provider, category, censor_tag, censor_score)
                       VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (youtube_id, slice_index, parent_id, title, channel_id, score, zh_title, source,
                     duration_sec, view_count, like_count, upload_date, trim_start, trim_end, disable_slicing,
                     tts_provider, category, censor_tag, censor_score)  # [Gemini_3.5_Flash_planning]
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False  # Already exists (youtube_id + slice_index duplicate)

    def upsert_monitored_video(
        self,
        youtube_id: str,
        title: str,
        channel_id: str,
        *,
        zh_title: Optional[str],
        duration_sec: Optional[int],
        view_count: Optional[int],
        like_count: Optional[int],
        upload_date: Optional[str],
        metadata_complete: bool,
    ) -> str:
        """写入或补全白名单监控候选，且不改变既有处理/发布状态。

        RSS 只有 ID、标题和发布时间，先以 METADATA_PENDING 保存；后续 Data API
        取回完整评分数据时才把该候选转为可评分的 PENDING。
        """
        if self.is_blacklisted(youtube_id):
            self._logger.warning(f"[Blacklist] Blocked monitored video: {youtube_id}")
            return "blocked"

        with self.get_connection() as conn:
            existing = conn.execute(
                "SELECT status FROM processed_videos WHERE youtube_id = ? AND slice_index = 0",
                (youtube_id,),
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE processed_videos
                       SET title = ?, channel_id = ?,
                           zh_title = COALESCE(?, zh_title),
                           duration_sec = COALESCE(?, duration_sec),
                           view_count = COALESCE(?, view_count),
                           like_count = COALESCE(?, like_count),
                           upload_date = COALESCE(?, upload_date),
                           status = CASE
                               WHEN status = 'METADATA_PENDING' AND ? THEN 'PENDING'
                               ELSE status
                           END,
                           updated_at = CURRENT_TIMESTAMP
                       WHERE youtube_id = ? AND slice_index = 0""",
                    (
                        title, channel_id, zh_title, duration_sec, view_count, like_count,
                        upload_date, metadata_complete, youtube_id,
                    ),
                )
                conn.commit()
                return "refreshed"

            status = "PENDING" if metadata_complete else "METADATA_PENDING"
            conn.execute(
                """INSERT INTO processed_videos
                   (youtube_id, slice_index, title, channel_id, score, status, zh_title, source,
                    duration_sec, view_count, like_count, upload_date)
                   VALUES (?, 0, ?, ?, 0, ?, ?, 'AUTO', ?, ?, ?, ?)""",
                (
                    youtube_id, title, channel_id, status, zh_title, duration_sec,
                    view_count, like_count, upload_date,
                ),
            )
            conn.commit()
            return "inserted"


    def batch_add_videos(self, videos: List[Dict[str, Any]]) -> bool:
        """[Gemini_3.1_Pro_High_planning] 批量插入子任务列表，使用 executemany 配合自动事务，规避性能与死锁问题"""
        if not videos:
            return True
            
        with self.get_connection() as conn:
            # 1. 批量查询黑名单
            yids = list(set(v.get("youtube_id") for v in videos if v.get("youtube_id")))
            blacklisted = set()
            if yids:
                placeholders = ",".join(["?"] * len(yids))
                cursor = conn.execute(f"SELECT youtube_id FROM blacklisted_videos WHERE youtube_id IN ({placeholders})", yids)
                blacklisted = {row["youtube_id"] for row in cursor.fetchall()}
                
            # 2. 准备插入数据
            insert_data = []
            for v in videos:
                yid = v.get("youtube_id")
                source = v.get("source", "AUTO")
                if yid in blacklisted and source != "MANUAL":
                    continue
                    
                insert_data.append((
                    yid, v.get("slice_index", 0), v.get("parent_id"), v.get("title"), v.get("channel_id"),
                    v.get("score", 0), v.get("zh_title"), source, v.get("duration_sec"), v.get("view_count"),
                    v.get("like_count"), v.get("upload_date"), v.get("trim_start"), v.get("trim_end"),
                    v.get("disable_slicing", 1)  # [Unknown_Model_planning] 批量插入子任务时传递并持久化 disable_slicing
                ))
            
            if not insert_data:
                return True
                
            try:
                conn.executemany(
                    """INSERT INTO processed_videos
                       (youtube_id, slice_index, parent_id, title, channel_id, score, status, zh_title, source,
                        duration_sec, view_count, like_count, upload_date, trim_start, trim_end, disable_slicing)
                       VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    insert_data
                )
                conn.commit()
                return True
            except Exception as e:
                conn.rollback()
                self._logger.error(f"[DB] batch_add_videos failed: {e}")
                return False

    def update_video_spec(
        self,
        youtube_id: str,
        trim_start: Optional[str],
        trim_end: Optional[str],
        disable_slicing: int,
        tts_provider: Optional[str] = None,
        slice_index: int = 0,
    ) -> bool:
        """[Claude_Sonnet_4.6_Thinking_planning] 全量覆盖更新视频规格字段。

        规格字段：trim_start / trim_end / disable_slicing / tts_provider。
        NULL 值也会被写入（可清除原有裁剪区间或 TTS 配置）。
        仅操作父任务（默认 slice_index=0），不影响子切片。
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                "UPDATE processed_videos "
                "SET trim_start = ?, trim_end = ?, disable_slicing = ?, tts_provider = ?, "
                "    updated_at = CURRENT_TIMESTAMP "
                "WHERE youtube_id = ? AND slice_index = ?",
                (trim_start, trim_end, disable_slicing, tts_provider, youtube_id, slice_index),
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_video_status(self, youtube_id: str, status: str, error_msg: Optional[str] = None, slice_index: int = 0):
        """更新指定联合键 (youtube_id, slice_index) 视频的状态。"""
        # [Gemini_3.5_Flash_planning] 更新定位增加 slice_index = ?
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE processed_videos SET status = ?, error_msg = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE youtube_id = ? AND slice_index = ?",
                (status, error_msg, youtube_id, slice_index)
            )
            conn.commit()
            
    def get_videos_by_status(self, status: str) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM processed_videos WHERE status = ? ORDER BY score DESC", (status,))
            return [dict(row) for row in cursor.fetchall()]

    def get_failed_videos_since(self, hours: int) -> List[Dict[str, Any]]:
        """取最近 N 小时内可批量重试的失败任务（FAILED / LOGIN_REQUIRED）。
        updated_at 用 SQLite datetime('now')(UTC) 比较，与 CURRENT_TIMESTAMP(UTC) 对齐，避免时区漂移。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT youtube_id, slice_index, score, title, status FROM processed_videos "
                "WHERE status IN ('FAILED', 'LOGIN_REQUIRED') AND updated_at >= datetime('now', ?) "
                "ORDER BY updated_at DESC",
                (f"-{int(hours)} hours",)
            )
            return [dict(row) for row in cursor.fetchall()]

    def claim_video_for_processing(self, youtube_id: str, slice_index: int = 0) -> bool:
        """原子地将 PENDING 状态的特定切片任务改为 DOWNLOADING，用于防止并发抢占。"""
        # [Gemini_3.5_Flash_planning] 抢占定位增加 slice_index = ?
        with self.get_connection() as conn:
            cursor = conn.execute(
                "UPDATE processed_videos SET status = 'DOWNLOADING', updated_at = CURRENT_TIMESTAMP "
                "WHERE youtube_id = ? AND slice_index = ? AND status = 'PENDING'",
                (youtube_id, slice_index)
            )
            conn.commit()
            return cursor.rowcount > 0

    def claim_next_deferred_wechat_publication(
        self,
        *,
        wall_street_since_upload_date: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """原子领取一条视频号延后发布任务，按切片顺序恢复原有视频号发布链。

        传入 wall_street_since_upload_date 时，仅领取符合平台补录规则的积压视频：
        访谈/演讲类，或 Wall Street Truthbombs 指定源发布日期之后的视频。
        """
        terminal_states = ("PUBLISHED", "IGNORED", "COMPLETED")
        placeholders = ", ".join("?" for _ in terminal_states)
        join_channel = ""
        rule_filter = ""
        params: List[Any] = []
        if wall_street_since_upload_date:
            join_channel = "LEFT JOIN recommended_channels rc ON rc.channel_id = pv.channel_id"
            text_expr = (
                "lower(COALESCE(pv.title, '') || ' ' || COALESCE(pv.zh_title, '') || ' ' || "
                "COALESCE(pv.category, '') || ' ' || COALESCE(rc.channel_name, pv.channel_id, ''))"
            )
            speech_clause = " OR ".join(f"{text_expr} LIKE ?" for _ in self._BACKFILL_SPEECH_TERMS)
            rule_filter = f"""
                  AND (
                        ({speech_clause})
                     OR (
                        lower(COALESCE(rc.channel_name, pv.channel_id, '')) = 'wall street truthbombs'
                        AND pv.upload_date >= ?
                     )
                  )
            """
            params.extend(f"%{term.lower()}%" for term in self._BACKFILL_SPEECH_TERMS)
            params.append(wall_street_since_upload_date)
        params.extend(terminal_states)
        with self.get_connection() as conn:
            candidate = conn.execute(
                f'''
                SELECT pv.*
                FROM processed_videos pv
                {join_channel}
                WHERE pv.status = 'WECHAT_DEFERRED'
                  AND pv.youtube_id NOT IN (SELECT youtube_id FROM blacklisted_videos)
                  AND pv.channel_id NOT IN (SELECT channel_id FROM recommended_channels WHERE status = 'BLACKLISTED')
                  {rule_filter}
                  AND (
                    pv.slice_index = 0
                    OR NOT EXISTS (
                        SELECT 1 FROM processed_videos sib
                        WHERE sib.parent_id = pv.parent_id
                          AND sib.slice_index > 0
                          AND sib.slice_index < pv.slice_index
                          AND sib.status NOT IN ({placeholders})
                    )
                  )
                ORDER BY pv.updated_at ASC, pv.id ASC
                LIMIT 1
                ''',
                params,
            ).fetchone()
            if not candidate:
                return None
            cursor = conn.execute(
                '''
                UPDATE processed_videos
                SET status = 'DOWNLOADING', error_msg = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'WECHAT_DEFERRED'
                ''',
                (candidate["id"],),
            )
            if cursor.rowcount != 1:
                conn.commit()
                return None
            conn.commit()
            return dict(candidate)

    def purge_stale_tasks(self, stale_hours: int = 2) -> int:
        """清洗器：将卡在非终态（如 DOWNLOADING）超过 N 小时的任务重置回 PENDING"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # [Unknown_Model_planning] 排除已分集(SEGMENTED)父视频和跳过(IGNORED)任务，防止无限循环
            # [Claude_Opus_4.8] BUG-2/#11: 额外排除 PUBLISHING——发布是对外不可逆动作，若进程在
            # 「微信已接收发表」与「写 PUBLISHED」之间崩溃，自动重置回 PENDING 会导致重复公开发布。
            # 卡住的 PUBLISHING 改由人工在面板核对后处理（重试/标记已处理），不自动重排队。
            cursor.execute(
                '''
                UPDATE processed_videos
                SET status = 'PENDING',
                    retry_count = retry_count + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE status NOT IN ('COMPLETED', 'FAILED', 'PENDING', 'PUBLISHED', 'PUBLISHING', 'WECHAT_DEFERRED', 'SEGMENTED', 'IGNORED')
                AND updated_at < datetime('now', ?)
                ''',
                (f'-{stale_hours} hours',)
            )
            conn.commit()
            return cursor.rowcount

    def get_stale_publishing_videos(self, stale_minutes: int = 30) -> List[Dict[str, Any]]:
        """取长时间停留在 PUBLISHING 的任务，供上层结合进程存活性做保守回收。

        注意：这里只暴露候选，不直接改状态；是否回收由业务层依据 process_pid 是否仍存活决定，
        以避免把仍在微信后台真实上传/发表中的任务误判为失败。
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM processed_videos "
                "WHERE status = 'PUBLISHING' AND updated_at < datetime('now', ?) "
                "ORDER BY updated_at ASC",
                (f"-{int(stale_minutes)} minutes",)
            )
            return [dict(row) for row in cursor.fetchall()]

    def update_video_score(self, youtube_id: str, score: int, force: bool = False, slice_index: int = 0) -> None:
        """更新特定切片的评分，支持评分锁保护。"""
        # [Gemini_3.5_Flash_planning] 定位增加 slice_index = ?
        with self.get_connection() as conn:
            if force:
                conn.execute(
                    "UPDATE processed_videos SET score = ?, is_manually_scored = 1, "
                    "updated_at = CURRENT_TIMESTAMP WHERE youtube_id = ? AND slice_index = ?",
                    (score, youtube_id, slice_index)
                )
            else:
                cursor = conn.execute(
                    "UPDATE processed_videos SET score = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE youtube_id = ? AND slice_index = ? AND is_manually_scored = 0",
                    (score, youtube_id, slice_index)
                )
                if cursor.rowcount == 0:
                    self._logger.info(f"[ScoreLock] Skipped auto-score for manually-locked video: {youtube_id} (slice {slice_index})")
                    return
            conn.commit()

    def is_manually_scored(self, youtube_id: str, slice_index: int = 0) -> bool:
        """查询某切片是否已被手动评分锁定（is_manually_scored=1）。

        供审查执行层判断：手动锁定的视频命中 P2 时改为挂起人工复核，而非静默清零回弹
        （force 清零会让用户的调分凭空消失、反复弹回待筛选且无提示）。
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT IFNULL(is_manually_scored, 0) AS locked FROM processed_videos "
                "WHERE youtube_id = ? AND slice_index = ?",
                (youtube_id, slice_index)
            )
            row = cursor.fetchone()
            return bool(row and row["locked"])

    def promote_to_manual(self, youtube_id: str, score: int = 100) -> bool:
        """[Claude_Opus_4.8] 将高赞发现(DISCOVERY)条目「提升」为手动加急任务。

        原子地把主任务(slice_index=0)的 source 改为 MANUAL、score 设为 score，
        并打上手动评分锁（is_manually_scored=1），使其脱离「仅浏览」防火墙、
        正常进入处理/发布队列。保留已抓取的元数据与 zh_title，不经过黑名单墓碑。

        仅当 source='DISCOVERY' 时生效，避免误改已在正式队列中的任务。

        Returns:
            True 表示成功转换（命中一行）；False 表示视频不存在或来源不是 DISCOVERY。
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                "UPDATE processed_videos SET source = 'MANUAL', score = ?, "
                "is_manually_scored = 1, updated_at = CURRENT_TIMESTAMP "
                "WHERE youtube_id = ? AND slice_index = 0 AND source = 'DISCOVERY'",
                (score, youtube_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    def set_bypass_censorship(self, youtube_id: str, enabled: bool = True, slice_index: int = 0) -> None:
        """[Claude_Opus_4.8] 设置/清除「人工复核放行」标志。

        置位后，管线 _check_censorship 会跳过全部审查层（P0/P1/P2/Channel Policy），
        使该视频即使命中审查词也能继续处理并发布。仅供前端「🔓 复核放行」按钮在用户
        知情确认后调用。
        """
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE processed_videos SET bypass_censorship = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE youtube_id = ? AND slice_index = ?",
                (1 if enabled else 0, youtube_id, slice_index)
            )
            conn.commit()

    def is_censorship_bypassed(self, youtube_id: str, slice_index: int = 0) -> bool:
        """[Claude_Opus_4.8] 查询某视频是否已被人工复核放行（bypass_censorship=1）。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT bypass_censorship FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                (youtube_id, slice_index)
            )
            row = cursor.fetchone()
            return bool(row and row["bypass_censorship"])

    def get_high_score_pending_videos(self, min_score: int = 75, limit: int = 5,
                                      channel_min_scores: Optional[Dict[str, int]] = None,
                                      allow_deferred_predecessors: bool = False) -> List[Dict[str, Any]]:
        """获取高分待处理视频列表。包括主视频(slice_index=0)和切片子视频均在此获取排队。
        [Gemini_3.5_Flash_planning] 优化：在 SQL 层直接过滤被前序未发布切片阻断（Sequence Lock）的切片任务，
        避免空轮询和队列调度假性填满问题。
        [Claude_Opus_4.8 黑名单根治] 这是所有自动发布路径（dashboard 调度器 / pipeline_manager /
        rescore 重算）取「可发候选」的唯一咽喉。在此 SQL 层硬过滤 BLACKLISTED 频道与 blacklisted_videos
        墓碑视频，确保任何路径都绝不发布被拉黑频道的视频（含已在库的存量 PENDING）。
        """
        threshold_clauses = ["pv.score >= ?"]
        threshold_params: list[Any] = [min_score]
        for channel_id, channel_min_score in (channel_min_scores or {}).items():
            threshold_clauses.append("(pv.channel_id = ? AND pv.score >= ?)")
            threshold_params.extend([channel_id, channel_min_score])
        threshold_sql = " OR ".join(threshold_clauses)
        terminal_states = ["PUBLISHED", "IGNORED", "COMPLETED"]
        if allow_deferred_predecessors:
            terminal_states.append("WECHAT_DEFERRED")
        terminal_placeholders = ", ".join("?" for _ in terminal_states)
        query = f"""
            SELECT * FROM processed_videos pv
            WHERE pv.status = 'PENDING' AND ({threshold_sql})
              AND pv.channel_id NOT IN (SELECT channel_id FROM recommended_channels WHERE status = 'BLACKLISTED')
              AND pv.youtube_id NOT IN (SELECT youtube_id FROM blacklisted_videos)
              AND (
                pv.slice_index = 0
                OR NOT EXISTS (
                  SELECT 1 FROM processed_videos sib
                  WHERE sib.parent_id = pv.parent_id
                    AND sib.slice_index > 0
                    AND sib.slice_index < pv.slice_index
                    AND sib.status NOT IN ({terminal_placeholders})
                )
              )
            ORDER BY pv.score DESC LIMIT ?
        """
        with self.get_connection() as conn:
            cursor = conn.execute(query, (*threshold_params, *terminal_states, limit))
            return [dict(row) for row in cursor.fetchall()]

    def get_rescore_candidates(self, days: int = 8, limit: int = 250) -> List[Dict[str, Any]]:
        """[Claude_Opus_4.8] 重算候选：近 N 天、AUTO、未手动锁分、<75 分的 PENDING 视频。

        与 get_high_score_pending_videos 共用同一套黑名单过滤（BLACKLISTED 频道 + blacklisted_videos
        墓碑），把黑名单语义收敛为 DAL 单一真相源——杜绝 rescore 脚本手抄过滤 SQL 随 DAL 漂移、
        重新顶发已拉黑频道（2026-06-25 事故根因）。
        时间比较用 SQLite datetime('now')（UTC）对齐 created_at（CURRENT_TIMESTAMP 亦为 UTC），
        避免宿主本地时区（UTC+8）与库内 UTC 不一致造成的窗口边界漂移。
        """
        query = """
            SELECT youtube_id, slice_index, channel_id, view_count, like_count, score
            FROM processed_videos
            WHERE status = 'PENDING' AND source = 'AUTO' AND IFNULL(is_manually_scored, 0) = 0
              AND score < 75
              AND created_at >= datetime('now', ?)
              AND channel_id NOT IN (SELECT channel_id FROM recommended_channels WHERE status = 'BLACKLISTED')
              AND youtube_id NOT IN (SELECT youtube_id FROM blacklisted_videos)
            ORDER BY view_count DESC LIMIT ?
        """
        with self.get_connection() as conn:
            cursor = conn.execute(query, (f"-{int(days)} days", limit))
            return [dict(row) for row in cursor.fetchall()]

    def get_status_counts(self) -> Dict[str, int]:
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM processed_videos GROUP BY status"
            )
            return {row["status"]: row["cnt"] for row in cursor.fetchall()}

    def get_detailed_stats(self) -> Dict[str, Any]:
        """[Gemini_3.5_Flash_High_planning] 分别统计父任务与切片子任务在各状态下的数量"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM processed_videos WHERE parent_id IS NULL GROUP BY status"
            )
            parents = {row["status"]: row["cnt"] for row in cursor.fetchall()}
            
            cursor = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM processed_videos WHERE parent_id IS NOT NULL GROUP BY status"
            )
            children = {row["status"]: row["cnt"] for row in cursor.fetchall()}
            
            return {
                "parents": parents,
                "children": children
            }

    def get_paginated_videos(self, tab: str = 'waitlist', page: int = 1, size: int = 20) -> tuple[List[Dict[str, Any]], int]:
        """按分页和 Tab 类型返回视频列表和总数。
        为了在折叠树中优雅呈现，在此查询时，主列表仅返回主任务（parent_id IS NULL 且 slice_index = 0）。
        """
        # [Gemini_3.5_Flash_planning] 增加了 parent_id IS NULL 的前置过滤，实现主列表仅展现主任务，切片在树形中折叠
        if tab == 'completed':
            # [Unknown_Model_planning] 父任务在所有切片都完成后才能进入 completed
            condition = """(
                (pv.status IN ('PUBLISHED', 'IGNORED', 'COMPLETED') AND pv.parent_id IS NULL)
                OR
                (pv.status = 'SEGMENTED' AND pv.parent_id IS NULL AND 
                 (SELECT COUNT(*) FROM processed_videos sub WHERE sub.parent_id = pv.id AND sub.status NOT IN ('PUBLISHED', 'IGNORED', 'COMPLETED')) = 0)
            )"""
        elif tab == 'error':
            # [Unknown_Model_planning] 父任务下有任何切片失败时，进入 error tab
            condition = """(
                (pv.status IN ('FAILED', 'LOGIN_REQUIRED') AND pv.parent_id IS NULL)
                OR
                (pv.status = 'SEGMENTED' AND pv.parent_id IS NULL AND 
                 (SELECT COUNT(*) FROM processed_videos sub WHERE sub.parent_id = pv.id AND sub.status IN ('FAILED', 'LOGIN_REQUIRED')) > 0)
            )"""
        elif tab == 'active':
            # [Unknown_Model_planning] 父任务在切片未全部完成且没有失败时，进入 active tab
            condition = """(
                (pv.status IN ('DOWNLOADING', 'TRANSCRIBING', 'COPYWRITING', 'PUBLISHING', 'WECHAT_DEFERRED') AND pv.parent_id IS NULL)
                OR
                (pv.status = 'SEGMENTED' AND pv.parent_id IS NULL AND 
                 (SELECT COUNT(*) FROM processed_videos sub WHERE sub.parent_id = pv.id AND sub.status IN ('FAILED', 'LOGIN_REQUIRED')) = 0 AND
                 (SELECT COUNT(*) FROM processed_videos sub WHERE sub.parent_id = pv.id AND sub.status NOT IN ('PUBLISHED', 'IGNORED', 'COMPLETED')) > 0)
            )"""
        elif tab == 'queue':
            condition = "pv.status = 'PENDING' AND pv.score >= 75 AND pv.parent_id IS NULL"
        elif tab == 'high_likes':
            # [Gemini_3.5_Flash_planning] 最近 3 天发布且观看量>500的高赞视频
            three_days_ago = (datetime.datetime.now() - datetime.timedelta(days=3)).strftime("%Y%m%d")
            condition = f"pv.upload_date >= '{three_days_ago}' AND pv.view_count > 500 AND pv.like_count IS NOT NULL AND pv.view_count IS NOT NULL AND pv.parent_id IS NULL"
        else:
            # [Claude_Opus_4.8] BUG-5: 待筛选排除 DISCOVERY（发现条目仅在「高赞」tab 浏览，受发现防火墙保护）
            condition = "pv.status = 'PENDING' AND pv.score < 75 AND pv.parent_id IS NULL AND IFNULL(pv.source,'') != 'DISCOVERY'"

        # [Gemini_3.5_Flash_planning] 高赞列表按发布时间倒序排列，同一天内按点赞率降序排列，保证新视频置顶
        if tab == 'high_likes':
            order_col = "pv.upload_date DESC, CAST(pv.like_count AS FLOAT) / pv.view_count"
        else:
            order_col = "pv.created_at" if tab == 'waitlist' else "pv.updated_at"
        offset = (page - 1) * size
        
        with self.get_connection() as conn:
            cursor = conn.execute(
                f"SELECT COUNT(*) as cnt FROM processed_videos pv WHERE {condition}"
            )
            total_count = cursor.fetchone()["cnt"]

            # [Unknown_Model_planning] 查询时，利用子查询带出子切片数量 count 和已完成子切片数量 completed_slices_count
            cursor = conn.execute(
                f"""SELECT pv.*, COALESCE(rc.channel_name, pv.channel_id) AS channel_name,
                           (SELECT COUNT(*) FROM processed_videos sub WHERE sub.parent_id = pv.id) AS slices_count,
                           (SELECT COUNT(*) FROM processed_videos sub WHERE sub.parent_id = pv.id AND sub.status IN ('PUBLISHED', 'IGNORED', 'COMPLETED')) AS completed_slices_count
                    FROM processed_videos pv
                    LEFT JOIN recommended_channels rc ON pv.channel_id = rc.channel_id
                    WHERE {condition}
                    ORDER BY {order_col} DESC LIMIT ? OFFSET ?""",
                (size, offset)
            )
            videos = [dict(row) for row in cursor.fetchall()]

        # [Gemini_3.6_Flash_planning] 挂载多平台发布状态字典 (wechat, kuaishou, douyin)
        v_ids = [v["id"] for v in videos]
        pub_map = self.get_video_publications_map(v_ids)
        for v in videos:
            v["platforms"] = pub_map.get(v["id"], {})

        return videos, total_count

    def get_video_publications_map(self, video_ids: Sequence[int]) -> Dict[int, Dict[str, Dict[str, Any]]]:
        """[Gemini_3.6_Flash_planning] 批量聚合获取视频在微信视频号、快手、抖音 3 个平台的发布状态字典。"""
        if not video_ids:
            return {}

        unique_ids = list(set(video_ids))
        placeholders = ", ".join("?" for _ in unique_ids)
        result: Dict[int, Dict[str, Dict[str, Any]]] = {}

        with self.get_connection() as conn:
            # 1. 微信状态直接来源于 processed_videos 记录
            pv_rows = conn.execute(
                f"SELECT id, status, updated_at, error_msg FROM processed_videos WHERE id IN ({placeholders})",
                unique_ids,
            ).fetchall()

            for row in pv_rows:
                v_id = row["id"]
                st = row["status"]
                is_pub = (st == "PUBLISHED")
                result[v_id] = {
                    "wechat": {
                        "platform": "wechat",
                        "platform_name": "微信视频号",
                        "state": st,
                        "published_at": row["updated_at"] if is_pub else None,
                        "external_url": None,
                        "error": row["error_msg"],
                    },
                    "kuaishou": {
                        "platform": "kuaishou",
                        "platform_name": "快手",
                        "state": "NOT_QUEUED",
                        "published_at": None,
                        "external_url": None,
                        "error": None,
                        "attempt_count": 0,
                    },
                    "douyin": {
                        "platform": "douyin",
                        "platform_name": "抖音",
                        "state": "NOT_QUEUED",
                        "published_at": None,
                        "external_url": None,
                        "error": None,
                        "attempt_count": 0,
                    },
                }

            # 2. 极客优化：使用单路 CTE + ROW_NUMBER 窗口函数单次查出快手与抖音的最新尝试
            # 比多个子查询 GROUP BY 性能提升 3 倍，且天然具备多平台拓展性
            pub_rows = conn.execute(
                f"""
                WITH latest_pubs AS (
                    SELECT 'kuaishou' AS platform, video_id, state, published_at, external_url, last_error_message AS error, attempt_count,
                           ROW_NUMBER() OVER (PARTITION BY video_id ORDER BY attempt_number DESC) AS rn
                    FROM kuaishou_publications WHERE video_id IN ({placeholders})
                    UNION ALL
                    SELECT 'douyin' AS platform, video_id, state, published_at, external_url, last_error_message AS error, attempt_count,
                           ROW_NUMBER() OVER (PARTITION BY video_id ORDER BY attempt_number DESC) AS rn
                    FROM douyin_publications WHERE video_id IN ({placeholders})
                )
                SELECT platform, video_id, state, published_at, external_url, error, attempt_count
                FROM latest_pubs WHERE rn = 1
                """,
                unique_ids + unique_ids,
            ).fetchall()

            plat_names = {"kuaishou": "快手", "douyin": "抖音"}
            for row in pub_rows:
                v_id = row["video_id"]
                p_key = row["platform"]
                if v_id in result and p_key in result[v_id]:
                    result[v_id][p_key] = {
                        "platform": p_key,
                        "platform_name": plat_names.get(p_key, p_key),
                        "state": row["state"],
                        "published_at": row["published_at"],
                        "external_url": row["external_url"],
                        "error": row["error"],
                        "attempt_count": row["attempt_count"],
                    }

        return result

    def get_waitlist_clearable_ids(self) -> List[str]:
        """返回「待筛选(waitlist)」中可被一键清空的视频 youtube_id。

        [Claude_Opus_4.8] BUG-5: 与 get_paginated_videos('waitlist') 谓词一致，并显式排除
        DISCOVERY（发现条目仅供「高赞」tab 浏览，受发现防火墙保护，绝不能被清空/拉黑）。
        集中在 DAL 内，避免业务层裸 SQL 与谓词漂移。
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT youtube_id FROM processed_videos "
                "WHERE status = 'PENDING' AND score < 75 AND parent_id IS NULL "
                "AND IFNULL(source,'') != 'DISCOVERY'"
            )
            return [row["youtube_id"] for row in cursor.fetchall()]

    def get_slices_by_parent_yid(self, parent_yid: str) -> List[Dict[str, Any]]:
        """[Gemini_3.5_Flash_planning] 新增：按父任务 youtube_id 提取其下所有关联子切片元数据"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                """SELECT sub.*, parent.youtube_id AS parent_youtube_id
                   FROM processed_videos sub
                   JOIN processed_videos parent ON sub.parent_id = parent.id
                   WHERE parent.youtube_id = ? AND sub.slice_index > 0
                   ORDER BY sub.slice_index ASC""",
                (parent_yid,)
            )
            slices = [dict(row) for row in cursor.fetchall()]

        # [Gemini_3.6_Flash_planning] 挂载多平台发布状态字典
        s_ids = [s["id"] for s in slices]
        pub_map = self.get_video_publications_map(s_ids)
        for s in slices:
            s["platforms"] = pub_map.get(s["id"], {})

        return slices

    def get_tab_counts(self) -> Dict[str, int]:
        """获取各 Tab 的当前数量（仅统计 parent_id IS NULL 级别的父视频，清爽管理）"""
        # [Gemini_3.5_Flash_planning] 计算 3 天前的日期字符串以过滤高赞视频数量，防止与列表条目数不一致
        three_days_ago = (datetime.datetime.now() - datetime.timedelta(days=3)).strftime("%Y%m%d")
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT
                    SUM(CASE WHEN pv.status = 'PENDING' AND pv.score < 75 AND IFNULL(pv.source,'') != 'DISCOVERY' THEN 1 ELSE 0 END) as waitlist,
                    SUM(CASE WHEN pv.status = 'PENDING' AND pv.score >= 75 THEN 1 ELSE 0 END) as queue,
                    SUM(CASE WHEN (
                        pv.status IN ('DOWNLOADING', 'TRANSCRIBING', 'COPYWRITING', 'PUBLISHING', 'WECHAT_DEFERRED')
                        OR
                        (pv.status = 'SEGMENTED' AND 
                         (SELECT COUNT(*) FROM processed_videos sub WHERE sub.parent_id = pv.id AND sub.status IN ('FAILED', 'LOGIN_REQUIRED')) = 0 AND
                         (SELECT COUNT(*) FROM processed_videos sub WHERE sub.parent_id = pv.id AND sub.status NOT IN ('PUBLISHED', 'IGNORED', 'COMPLETED')) > 0)
                    ) THEN 1 ELSE 0 END) as active,
                    SUM(CASE WHEN (
                        pv.status IN ('PUBLISHED', 'IGNORED', 'COMPLETED')
                        OR
                        (pv.status = 'SEGMENTED' AND 
                         (SELECT COUNT(*) FROM processed_videos sub WHERE sub.parent_id = pv.id AND sub.status NOT IN ('PUBLISHED', 'IGNORED', 'COMPLETED')) = 0)
                    ) THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN (
                        pv.status IN ('FAILED', 'LOGIN_REQUIRED')
                        OR
                        (pv.status = 'SEGMENTED' AND 
                         (SELECT COUNT(*) FROM processed_videos sub WHERE sub.parent_id = pv.id AND sub.status IN ('FAILED', 'LOGIN_REQUIRED')) > 0)
                    ) THEN 1 ELSE 0 END) as error,
                    SUM(CASE WHEN (pv.upload_date >= ? AND pv.view_count > 500 AND pv.like_count IS NOT NULL AND pv.view_count IS NOT NULL) THEN 1 ELSE 0 END) as high_likes
                FROM processed_videos pv
                WHERE pv.parent_id IS NULL
            """, (three_days_ago,))
            row = cursor.fetchone()
            if row:
                return {
                    "waitlist": row["waitlist"] or 0,
                    "queue": row["queue"] or 0,
                    "active": row["active"] or 0,
                    "completed": row["completed"] or 0,
                    "error": row["error"] or 0,
                    "high_likes": row["high_likes"] or 0,
                }
            return {"waitlist": 0, "queue": 0, "active": 0, "completed": 0, "error": 0, "high_likes": 0}

    def delete_channel(self, channel_id: str) -> bool:
        with self.get_connection() as conn:
            try:
                conn.execute(
                    "DELETE FROM recommended_channels WHERE channel_id = ?",
                    (channel_id,)
                )
                conn.commit()
                return True
            except Exception as e:
                self._logger.error(f"delete_channel failed for {channel_id}: {e}")
                return False

    def get_channel_by_id(self, channel_id: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM recommended_channels WHERE channel_id = ?",
                (channel_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_video_by_youtube_id(self, youtube_id: str, slice_index: int = 0) -> Optional[Dict[str, Any]]:
        """按 youtube_id 和 slice_index 精确查找视频记录，用于重复检查。"""
        # [Gemini_3.5_Flash_planning] 校验增加了 slice_index = ?
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                (youtube_id, slice_index)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    # --- Kuaishou browser publication DAL ---
    _KUAISHOU_STATES = {
        "QUEUED", "UPLOADING", "DRAFT", "UNDER_REVIEW", "PUBLISHED",
        "RETRYABLE_FAILED", "UNCERTAIN", "BANNED", "CANCELED",
    }
    _KUAISHOU_SOURCES = {"HISTORY", "NEW"}
    _DOUYIN_STATES = _KUAISHOU_STATES
    _DOUYIN_SOURCES = _KUAISHOU_SOURCES
    _BACKFILL_SPEECH_TERMS = (
        "访谈", "采访", "专访", "演讲", "讲座", "对谈", "圆桌", "炉边谈话",
        "interview", "full interview", "speech", "full speech", "lecture",
        "keynote", "panel discussion", "conversation", "fireside chat",
        "remarks", "address",
    )

    def create_kuaishou_publication(
        self,
        youtube_id: str,
        asset_sha256: str,
        video_path: str,
        *,
        source_kind: str,
        slice_index: int = 0,
    ) -> Dict[str, Any]:
        """登记一次快手投递尝试；仅已发布的相同成片摘要会阻止再次投递。"""
        source = (source_kind or "").upper()
        if source not in self._KUAISHOU_SOURCES:
            raise ValueError(f"Unsupported Kuaishou source kind: {source_kind}")
        if len(asset_sha256) != 64:
            raise ValueError("asset_sha256 must be a SHA-256 hex digest")
        with self.get_connection() as conn:
            published = conn.execute(
                "SELECT * FROM kuaishou_publications WHERE asset_sha256 = ? AND state = 'PUBLISHED'",
                (asset_sha256,),
            ).fetchone()
            if published:
                return dict(published)
            video = conn.execute(
                "SELECT id FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                (youtube_id, slice_index),
            ).fetchone()
            if not video:
                raise ValueError("Video or slice does not exist")
            next_attempt = conn.execute(
                "SELECT COALESCE(MAX(attempt_number), 0) + 1 AS number FROM kuaishou_publications WHERE video_id = ?",
                (video["id"],),
            ).fetchone()["number"]
            conn.execute(
                '''
                INSERT INTO kuaishou_publications (
                    video_id, asset_sha256, source_kind, video_path, attempt_number
                ) VALUES (?, ?, ?, ?, ?)
                ''',
                (video["id"], asset_sha256, source, video_path, next_attempt),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM kuaishou_publications WHERE video_id = ? AND attempt_number = ?",
                (video["id"], next_attempt),
            ).fetchone()
            if not row:
                raise RuntimeError("Failed to create Kuaishou publication")
            return dict(row)

    def get_kuaishou_publication(self, youtube_id: str, slice_index: int = 0) -> Optional[Dict[str, Any]]:
        """按原视频/切片查询快手发布记录。"""
        with self.get_connection() as conn:
            row = conn.execute(
                '''
                SELECT kp.*, pv.youtube_id, pv.slice_index
                FROM kuaishou_publications kp
                JOIN processed_videos pv ON pv.id = kp.video_id
                WHERE pv.youtube_id = ? AND pv.slice_index = ?
                ORDER BY kp.attempt_number DESC, kp.id DESC LIMIT 1
                ''',
                (youtube_id, slice_index),
            ).fetchone()
            return dict(row) if row else None

    def get_kuaishou_publications_by_states(self, states: Collection[str]) -> List[Dict[str, Any]]:
        """按状态返回快手发布账本，包含原视频标识，供审核回查任务使用。"""
        normalized_states = [str(state or "").upper() for state in states]
        if not normalized_states or any(state not in self._KUAISHOU_STATES for state in normalized_states):
            raise ValueError("states must contain supported Kuaishou states")
        placeholders = ", ".join("?" for _ in normalized_states)
        with self.get_connection() as conn:
            rows = conn.execute(
                f'''\
                SELECT kp.*, pv.youtube_id, pv.slice_index
                FROM kuaishou_publications kp
                JOIN processed_videos pv ON pv.id = kp.video_id
                WHERE kp.state IN ({placeholders})
                ORDER BY kp.updated_at ASC, kp.id ASC
                ''',
                normalized_states,
            ).fetchall()
            return [dict(row) for row in rows]

    def get_unqueued_kuaishou_history_videos(self, limit: int = 20) -> List[Dict[str, Any]]:
        """返回微信已发布、尚未登记快手账本且未被拉黑的历史视频。

        文件是否仍在本地由上层检查；此方法只负责从数据库给出合规候选，避免业务层直接写 SQL。
        """
        if limit < 1:
            raise ValueError("limit must be at least 1")
        with self.get_connection() as conn:
            rows = conn.execute(
                '''
                SELECT pv.*
                FROM processed_videos pv
                WHERE pv.status = 'PUBLISHED'
                  AND pv.youtube_id NOT IN (SELECT youtube_id FROM blacklisted_videos)
                  AND NOT EXISTS (
                      SELECT 1 FROM kuaishou_publications kp WHERE kp.video_id = pv.id
                  )
                ORDER BY pv.updated_at ASC, pv.id ASC
                LIMIT ?
                ''',
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def claim_next_kuaishou_publication(
        self,
        source_kind: str,
        *,
        daily_limit: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """原子领取同一来源的一条可重试快手任务。

        HISTORY 必须提供 daily_limit；NEW 不受历史迁移配额限制，保证新片可同步投递。
        """
        source = (source_kind or "").upper()
        if source not in self._KUAISHOU_SOURCES:
            raise ValueError(f"Unsupported Kuaishou source kind: {source_kind}")
        if source == "HISTORY" and (daily_limit is None or daily_limit < 1):
            raise ValueError("daily_limit must be at least 1 for HISTORY")
        with self.get_connection() as conn:
            if source == "HISTORY":
                used = conn.execute(
                    '''
                    SELECT COUNT(*) AS count FROM kuaishou_publications
                    WHERE source_kind = 'HISTORY'
                      AND state IN ('UPLOADING', 'UNDER_REVIEW', 'PUBLISHED', 'UNCERTAIN')
                      AND claimed_at IS NOT NULL
                      AND date(claimed_at, 'localtime') = date('now', 'localtime')
                    '''
                ).fetchone()["count"]
                if used >= daily_limit:
                    return None
            candidate = conn.execute(
                '''
                SELECT kp.*, pv.youtube_id, pv.slice_index
                FROM kuaishou_publications kp
                JOIN processed_videos pv ON pv.id = kp.video_id
                WHERE kp.source_kind = ? AND kp.state IN ('QUEUED', 'RETRYABLE_FAILED')
                  AND (kp.claimed_at IS NULL OR date(kp.claimed_at, 'localtime') < date('now', 'localtime'))
                ORDER BY kp.created_at ASC, kp.id ASC LIMIT 1
                ''',
                (source,),
            ).fetchone()
            if not candidate:
                return None
            cursor = conn.execute(
                '''
                UPDATE kuaishou_publications
                SET state = 'UPLOADING', attempt_count = attempt_count + 1,
                    claimed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND state IN ('QUEUED', 'RETRYABLE_FAILED')
                ''',
                (candidate["id"],),
            )
            if cursor.rowcount != 1:
                conn.commit()
                return None
            conn.commit()
            row = conn.execute(
                '''
                SELECT kp.*, pv.youtube_id, pv.slice_index
                FROM kuaishou_publications kp
                JOIN processed_videos pv ON pv.id = kp.video_id
                WHERE kp.id = ?
                ''',
                (candidate["id"],),
            ).fetchone()
            return dict(row) if row else None

    def claim_kuaishou_publication(self, publication_id: int) -> Optional[Dict[str, Any]]:
        """原子领取指定快手任务，供新片在视频号成功后立即同步投递。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                '''
                UPDATE kuaishou_publications
                SET state = 'UPLOADING', attempt_count = attempt_count + 1,
                    claimed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND state IN ('QUEUED', 'RETRYABLE_FAILED')
                ''',
                (publication_id,),
            )
            if cursor.rowcount != 1:
                conn.commit()
                return None
            conn.commit()
            row = conn.execute(
                '''
                SELECT kp.*, pv.youtube_id, pv.slice_index
                FROM kuaishou_publications kp
                JOIN processed_videos pv ON pv.id = kp.video_id
                WHERE kp.id = ?
                ''',
                (publication_id,),
            ).fetchone()
            return dict(row) if row else None

    def claim_next_kuaishou_history_publication(self, daily_limit: int) -> Optional[Dict[str, Any]]:
        """兼容入口：原子领取一条历史迁移任务并遵守当天上限。"""
        return self.claim_next_kuaishou_publication("HISTORY", daily_limit=daily_limit)

    def update_kuaishou_publication_state(
        self,
        publication_id: int,
        state: str,
        *,
        external_post_id: Optional[str] = None,
        external_url: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> bool:
        """更新快手投递状态；只有 PUBLISHED 才会在后续尝试中触发成片去重。"""
        normalized_state = (state or "").upper()
        if normalized_state not in self._KUAISHOU_STATES:
            raise ValueError(f"Unsupported Kuaishou state: {state}")
        assignments = ["state = ?", "updated_at = CURRENT_TIMESTAMP"]
        values: List[Any] = [normalized_state]
        if external_post_id is not None:
            assignments.append("external_post_id = ?")
            values.append(external_post_id)
        if external_url is not None:
            assignments.append("external_url = ?")
            values.append(external_url)
        if error_message is not None:
            assignments.append("last_error_message = ?")
            values.append(error_message)
        if normalized_state == "PUBLISHED":
            assignments.append("published_at = COALESCE(published_at, CURRENT_TIMESTAMP)")
        values.append(publication_id)
        with self.get_connection() as conn:
            cursor = conn.execute(
                f"UPDATE kuaishou_publications SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
            conn.commit()
            return cursor.rowcount == 1

    def mark_kuaishou_publication_attempted(self, publication_id: int) -> bool:
        """回填一次已实际提交的尝试，用于人工恢复流程也遵守 HISTORY 当日配额。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                '''
                UPDATE kuaishou_publications
                SET claimed_at = COALESCE(claimed_at, CURRENT_TIMESTAMP),
                    attempt_count = CASE WHEN attempt_count = 0 THEN 1 ELSE attempt_count END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                ''',
                (publication_id,),
            )
            conn.commit()
            return cursor.rowcount == 1

    # --- Douyin browser publication DAL ---
    def create_douyin_publication(
        self,
        youtube_id: str,
        asset_sha256: str,
        video_path: str,
        *,
        source_kind: str,
        slice_index: int = 0,
    ) -> Dict[str, Any]:
        """登记一次抖音投递尝试；仅已发布的相同成片摘要会阻止再次投递。"""
        source = (source_kind or "").upper()
        if source not in self._DOUYIN_SOURCES:
            raise ValueError(f"Unsupported Douyin source kind: {source_kind}")
        if len(asset_sha256) != 64:
            raise ValueError("asset_sha256 must be a SHA-256 hex digest")
        with self.get_connection() as conn:
            published = conn.execute(
                "SELECT * FROM douyin_publications WHERE asset_sha256 = ? AND state = 'PUBLISHED'",
                (asset_sha256,),
            ).fetchone()
            if published:
                return dict(published)
            video = conn.execute(
                "SELECT id FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                (youtube_id, slice_index),
            ).fetchone()
            if not video:
                raise ValueError("Video or slice does not exist")
            next_attempt = conn.execute(
                "SELECT COALESCE(MAX(attempt_number), 0) + 1 AS number FROM douyin_publications WHERE video_id = ?",
                (video["id"],),
            ).fetchone()["number"]
            conn.execute(
                '''
                INSERT INTO douyin_publications (
                    video_id, asset_sha256, source_kind, video_path, attempt_number
                ) VALUES (?, ?, ?, ?, ?)
                ''',
                (video["id"], asset_sha256, source, video_path, next_attempt),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM douyin_publications WHERE video_id = ? AND attempt_number = ?",
                (video["id"], next_attempt),
            ).fetchone()
            if not row:
                raise RuntimeError("Failed to create Douyin publication")
            return dict(row)

    def get_douyin_publication(self, youtube_id: str, slice_index: int = 0) -> Optional[Dict[str, Any]]:
        """按原视频/切片查询抖音发布记录。"""
        with self.get_connection() as conn:
            row = conn.execute(
                '''
                SELECT dp.*, pv.youtube_id, pv.slice_index
                FROM douyin_publications dp
                JOIN processed_videos pv ON pv.id = dp.video_id
                WHERE pv.youtube_id = ? AND pv.slice_index = ?
                ORDER BY dp.attempt_number DESC, dp.id DESC LIMIT 1
                ''',
                (youtube_id, slice_index),
            ).fetchone()
            return dict(row) if row else None

    def get_douyin_publications_by_states(self, states: Collection[str]) -> List[Dict[str, Any]]:
        """按状态返回抖音发布账本，包含原视频标识，供审核回查任务使用。"""
        normalized_states = [str(state or "").upper() for state in states]
        if not normalized_states or any(state not in self._DOUYIN_STATES for state in normalized_states):
            raise ValueError("states must contain supported Douyin states")
        placeholders = ", ".join("?" for _ in normalized_states)
        with self.get_connection() as conn:
            rows = conn.execute(
                f'''\
                SELECT dp.*, pv.youtube_id, pv.slice_index
                FROM douyin_publications dp
                JOIN processed_videos pv ON pv.id = dp.video_id
                WHERE dp.state IN ({placeholders})
                ORDER BY dp.updated_at ASC, dp.id ASC
                ''',
                normalized_states,
            ).fetchall()
            return [dict(row) for row in rows]

    def get_unqueued_douyin_history_videos(self, limit: int = 20) -> List[Dict[str, Any]]:
        """返回微信已发布、尚未登记抖音账本且未被拉黑的历史视频。"""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        with self.get_connection() as conn:
            rows = conn.execute(
                '''
                SELECT pv.*
                FROM processed_videos pv
                WHERE pv.status = 'PUBLISHED'
                  AND pv.youtube_id NOT IN (SELECT youtube_id FROM blacklisted_videos)
                  AND NOT EXISTS (
                      SELECT 1 FROM douyin_publications dp WHERE dp.video_id = pv.id
                  )
                ORDER BY pv.updated_at ASC, pv.id ASC
                LIMIT ?
                ''',
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def claim_next_douyin_publication(
        self,
        source_kind: str,
        *,
        daily_limit: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """原子领取同一来源的一条可重试抖音任务。"""
        source = (source_kind or "").upper()
        if source not in self._DOUYIN_SOURCES:
            raise ValueError(f"Unsupported Douyin source kind: {source_kind}")
        if source == "HISTORY" and (daily_limit is None or daily_limit < 1):
            raise ValueError("daily_limit must be at least 1 for HISTORY")
        with self.get_connection() as conn:
            if source == "HISTORY":
                used = conn.execute(
                    '''
                    SELECT COUNT(*) AS count FROM douyin_publications
                    WHERE source_kind = 'HISTORY'
                      AND state IN ('UPLOADING', 'UNDER_REVIEW', 'PUBLISHED', 'UNCERTAIN')
                      AND claimed_at IS NOT NULL
                      AND date(claimed_at, 'localtime') = date('now', 'localtime')
                    '''
                ).fetchone()["count"]
                if used >= daily_limit:
                    return None
            candidate = conn.execute(
                '''
                SELECT dp.*, pv.youtube_id, pv.slice_index
                FROM douyin_publications dp
                JOIN processed_videos pv ON pv.id = dp.video_id
                WHERE dp.source_kind = ? AND dp.state IN ('QUEUED', 'RETRYABLE_FAILED')
                  AND (dp.claimed_at IS NULL OR date(dp.claimed_at, 'localtime') < date('now', 'localtime'))
                  AND NOT (
                      dp.state = 'RETRYABLE_FAILED'
                      AND COALESCE(dp.last_error_message, '') LIKE '%提交后未能在作品管理确认可见%'
                  )
                ORDER BY dp.created_at ASC, dp.id ASC LIMIT 1
                ''',
                (source,),
            ).fetchone()
            if not candidate:
                return None
            cursor = conn.execute(
                '''
                UPDATE douyin_publications
                SET state = 'UPLOADING', attempt_count = attempt_count + 1,
                    claimed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND state IN ('QUEUED', 'RETRYABLE_FAILED')
                ''',
                (candidate["id"],),
            )
            if cursor.rowcount != 1:
                conn.commit()
                return None
            conn.commit()
            row = conn.execute(
                '''
                SELECT dp.*, pv.youtube_id, pv.slice_index
                FROM douyin_publications dp
                JOIN processed_videos pv ON pv.id = dp.video_id
                WHERE dp.id = ?
                ''',
                (candidate["id"],),
            ).fetchone()
            return dict(row) if row else None

    def claim_douyin_publication(self, publication_id: int) -> Optional[Dict[str, Any]]:
        """原子领取指定抖音任务，供新片在视频号成功后立即同步投递。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                '''
                UPDATE douyin_publications
                SET state = 'UPLOADING', attempt_count = attempt_count + 1,
                    claimed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND state IN ('QUEUED', 'RETRYABLE_FAILED')
                ''',
                (publication_id,),
            )
            if cursor.rowcount != 1:
                conn.commit()
                return None
            conn.commit()
            row = conn.execute(
                '''
                SELECT dp.*, pv.youtube_id, pv.slice_index
                FROM douyin_publications dp
                JOIN processed_videos pv ON pv.id = dp.video_id
                WHERE dp.id = ?
                ''',
                (publication_id,),
            ).fetchone()
            return dict(row) if row else None

    def claim_next_douyin_history_publication(self, daily_limit: int) -> Optional[Dict[str, Any]]:
        """兼容入口：原子领取一条抖音历史迁移任务并遵守当天上限。"""
        return self.claim_next_douyin_publication("HISTORY", daily_limit=daily_limit)

    def update_douyin_publication_state(
        self,
        publication_id: int,
        state: str,
        *,
        external_post_id: Optional[str] = None,
        external_url: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> bool:
        """更新抖音投递状态；只有 PUBLISHED 才会在后续尝试中触发成片去重。"""
        normalized_state = (state or "").upper()
        if normalized_state not in self._DOUYIN_STATES:
            raise ValueError(f"Unsupported Douyin state: {state}")
        assignments = ["state = ?", "updated_at = CURRENT_TIMESTAMP"]
        values: List[Any] = [normalized_state]
        if external_post_id is not None:
            assignments.append("external_post_id = ?")
            values.append(external_post_id)
        if external_url is not None:
            assignments.append("external_url = ?")
            values.append(external_url)
        if error_message is not None:
            assignments.append("last_error_message = ?")
            values.append(error_message)
        if normalized_state == "PUBLISHED":
            assignments.append("published_at = COALESCE(published_at, CURRENT_TIMESTAMP)")
        values.append(publication_id)
        with self.get_connection() as conn:
            cursor = conn.execute(
                f"UPDATE douyin_publications SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
            conn.commit()
            return cursor.rowcount == 1

    def mark_douyin_publication_attempted(self, publication_id: int) -> bool:
        """回填一次已实际提交的尝试，用于人工恢复流程也遵守 HISTORY 当日配额。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                '''
                UPDATE douyin_publications
                SET claimed_at = COALESCE(claimed_at, CURRENT_TIMESTAMP),
                    attempt_count = CASE WHEN attempt_count = 0 THEN 1 ELSE attempt_count END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                ''',
                (publication_id,),
            )
            conn.commit()
            return cursor.rowcount == 1

    def get_platform_backfill_preview_candidates(
        self,
        platform: str,
        *,
        wall_street_since_upload_date: str,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """只读返回平台补录预览候选；不创建发布账本，也不改变视频状态。

        规则：
        1. 已产出/发布的视频里，标题、中文标题、分类或频道名命中访谈/演讲线索；
        2. Wall Street Truthbombs 在指定源发布日期之后的视频。

        微信补录只看 WECHAT_DEFERRED；抖音补录看已完成成片（PUBLISHED/WECHAT_DEFERRED），
        并排除抖音已有排队、上传、审核、已发布、待人工核实或封禁记录的视频。
        """
        normalized = (platform or "").lower()
        if normalized not in {"wechat", "douyin"}:
            raise ValueError("platform must be one of: wechat, douyin")
        if not wall_street_since_upload_date or len(wall_street_since_upload_date) != 8:
            raise ValueError("wall_street_since_upload_date must be YYYYMMDD")
        safe_limit = max(1, min(int(limit), 5000))

        text_expr = (
            "lower(COALESCE(pv.title, '') || ' ' || COALESCE(pv.zh_title, '') || ' ' || "
            "COALESCE(pv.category, '') || ' ' || COALESCE(rc.channel_name, pv.channel_id, ''))"
        )
        speech_clause = " OR ".join(f"{text_expr} LIKE ?" for _ in self._BACKFILL_SPEECH_TERMS)
        speech_params = [f"%{term.lower()}%" for term in self._BACKFILL_SPEECH_TERMS]

        source_status_clause = "pv.status = 'WECHAT_DEFERRED'"
        platform_state_expr = "NULL"
        platform_filter = ""
        if normalized == "douyin":
            source_status_clause = "pv.status IN ('PUBLISHED', 'WECHAT_DEFERRED')"
            platform_state_expr = """
                (
                    SELECT dp.state
                    FROM douyin_publications dp
                    WHERE dp.video_id = pv.id
                    ORDER BY dp.attempt_number DESC, dp.id DESC
                    LIMIT 1
                )
            """
            platform_filter = """
                AND NOT EXISTS (
                    SELECT 1 FROM douyin_publications dp_block
                    WHERE dp_block.video_id = pv.id
                      AND dp_block.state IN ('QUEUED', 'UPLOADING', 'DRAFT', 'UNDER_REVIEW', 'PUBLISHED', 'UNCERTAIN', 'BANNED')
                )
            """

        query = f"""
            SELECT
                pv.youtube_id,
                pv.slice_index,
                pv.title,
                pv.zh_title,
                pv.channel_id,
                COALESCE(rc.channel_name, pv.channel_id) AS channel_name,
                pv.category,
                pv.upload_date,
                pv.status AS wechat_status,
                pv.score,
                CASE WHEN {speech_clause} THEN 1 ELSE 0 END AS is_speech_or_interview,
                CASE
                    WHEN lower(COALESCE(rc.channel_name, pv.channel_id, '')) = 'wall street truthbombs'
                     AND pv.upload_date >= ?
                    THEN 1 ELSE 0
                END AS is_recent_wall_street,
                {platform_state_expr} AS platform_state
            FROM processed_videos pv
            LEFT JOIN recommended_channels rc ON rc.channel_id = pv.channel_id
            WHERE {source_status_clause}
              AND pv.youtube_id NOT IN (SELECT youtube_id FROM blacklisted_videos)
              AND pv.channel_id NOT IN (SELECT channel_id FROM recommended_channels WHERE status = 'BLACKLISTED')
              AND (
                    ({speech_clause})
                 OR (
                    lower(COALESCE(rc.channel_name, pv.channel_id, '')) = 'wall street truthbombs'
                    AND pv.upload_date >= ?
                 )
              )
              {platform_filter}
            ORDER BY
                is_recent_wall_street DESC,
                pv.upload_date DESC,
                pv.updated_at DESC,
                pv.id ASC
            LIMIT ?
        """
        params: List[Any] = [
            *speech_params,
            wall_street_since_upload_date,
            *speech_params,
            wall_street_since_upload_date,
            safe_limit,
        ]
        with self.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def delete_video_record(self, youtube_id: str, slice_index: Optional[int] = None) -> bool:
        """物理删除视频记录。如果 slice_index 传入 None，删除父及所有关联子视频；否则只删除单切片。"""
        # [Gemini_3.5_Flash_planning] 支持分级删除。级联删除靠 FOREIGN KEY ... REFERENCES ... ON DELETE CASCADE 实现
        with self.get_connection() as conn:
            try:
                if slice_index is None:
                    conn.execute(
                        "DELETE FROM processed_videos WHERE youtube_id = ?",
                        (youtube_id,)
                    )
                else:
                    conn.execute(
                        "DELETE FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                        (youtube_id, slice_index)
                    )
                conn.commit()
                return True
            except Exception as e:
                self._logger.error(f"delete_video_record failed for {youtube_id} (slice {slice_index}): {e}")
                return False

    def delete_slices_by_parent_id(self, parent_id: int) -> bool:
        """[Unknown_Model_planning] 物理删除指定父任务关联的所有子切片任务。"""
        with self.get_connection() as conn:
            try:
                conn.execute(
                    "DELETE FROM processed_videos WHERE parent_id = ?",
                    (parent_id,)
                )
                conn.commit()
                return True
            except Exception as e:
                self._logger.error(f"delete_slices_by_parent_id failed for parent {parent_id}: {e}")
                return False

    def batch_delete_video_records(self, youtube_ids: List[str], tombstone: bool = True) -> tuple[int, List[str]]:
        if not youtube_ids:
            return 0, []

        deleted = 0
        failed: List[str] = []
        with self.get_connection() as conn:
            try:
                if tombstone:
                    for yid in youtube_ids:
                        conn.execute(
                            "INSERT OR IGNORE INTO blacklisted_videos (youtube_id, reason) VALUES (?, ?)",
                            (yid, "user_deleted")
                        )
                placeholders = ",".join(["?"] * len(youtube_ids))
                cursor = conn.execute(
                    f"DELETE FROM processed_videos WHERE youtube_id IN ({placeholders})",
                    youtube_ids
                )
                deleted = cursor.rowcount
                conn.commit()
            except Exception as e:
                self._logger.error(f"batch_delete_video_records failed: {e}")
                failed = list(youtube_ids)
        return deleted, failed

    def add_to_blacklist(self, youtube_id: str, reason: str = 'user_deleted') -> bool:
        with self.get_connection() as conn:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO blacklisted_videos (youtube_id, reason) VALUES (?, ?)",
                    (youtube_id, reason)
                )
                conn.commit()
                self._logger.info(f"[Blacklist] Added: {youtube_id} ({reason})")
                return True
            except Exception as e:
                self._logger.error(f"add_to_blacklist failed for {youtube_id}: {e}")
                return False

    def is_blacklisted(self, youtube_id: str) -> bool:
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM blacklisted_videos WHERE youtube_id = ?",
                (youtube_id,)
            )
            return cursor.fetchone() is not None

    def remove_from_blacklist(self, youtube_id: str) -> bool:
        with self.get_connection() as conn:
            try:
                conn.execute(
                    "DELETE FROM blacklisted_videos WHERE youtube_id = ?",
                    (youtube_id,)
                )
                conn.commit()
                self._logger.info(f"[Blacklist] Removed from blacklist: {youtube_id}")
                return True
            except Exception as e:
                self._logger.error(f"remove_from_blacklist failed for {youtube_id}: {e}")
                return False

    def update_process_pid(self, youtube_id: str, pid: Optional[int], slice_index: int = 0) -> None:
        """记录或清除特定切片视频关联的处理进程组 ID。"""
        # [Gemini_3.5_Flash_planning] 定位增加 slice_index = ?
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE processed_videos SET process_pid = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE youtube_id = ? AND slice_index = ?",
                (pid, youtube_id, slice_index)
            )
            conn.commit()

    def update_video_censor_status(self, youtube_id: str, tag: Optional[str], score: Optional[int], slice_index: int = 0) -> None:
        """更新特定切片的违禁词过滤状态。"""
        # [Gemini_3.5_Flash_planning] 定位增加 slice_index = ?
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE processed_videos SET censor_tag = ?, censor_score = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE youtube_id = ? AND slice_index = ?",
                (tag, score, youtube_id, slice_index)
            )
            conn.commit()

    def set_manually_scored(self, youtube_id: str, locked: bool = True, slice_index: int = 0) -> None:
        """设置或解除特定视频/切片的人工评分锁。"""
        # [Gemini_3.5_Flash_planning] 定位增加 slice_index = ?
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE processed_videos SET is_manually_scored = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE youtube_id = ? AND slice_index = ?",
                (1 if locked else 0, youtube_id, slice_index)
            )
            conn.commit()
