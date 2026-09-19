"""Phase M6.1 — Characterization Baseline Test Suite

本测试模块建立 2026-09-12 阶段性架构治理 M6.1 的系统行为安全基线 (Characterization Baseline)。
核心原则：Protect existing behavior before improving implementation.

测试分类标准 (Test Classification Standard):
- CONTRACT: 系统不变式与核心调用契约，未来重构必须 100% 保真（如原子事务、凭据校验）。
- SAFETY-REGRESSION: 既有安全守卫与防御纵深回归测试，阻止非法的重试/重置/重投。
- CHARACTERIZATION ONLY: 记录当前生产代码特定流转行为，作为渐进演进的对照基线。
- KNOWN-UNSAFE-BASELINE: 记录已识别的不安全/缺陷行为基线（如 RISK-STATE-001），禁止当作正确行为巩固，待后续 WO 解决。

# Modification History
| Version | Date       | Author                     | Description                                                                 |
|---------|------------|----------------------------|-----------------------------------------------------------------------------|
| 1.1.0   | 2026-09-12 | Gemini_3.8_Flash_planning  | M6.1A 审计校准：修正 INV-006 契约声明为零发布端副作用，澄清切片测试为 W-02 场景基线而非 INV-001 核心证据 |
| 1.0.0   | 2026-09-12 | Gemini_3.8_Flash_planning  | 初始创建 M6.1 特征化测试基线，覆盖 INV-001~INV-008 与 RISK-STATE-001 不安全基线 |
"""

import hashlib
import json
from pathlib import Path
import sqlite3
import unittest.mock as mock
import pytest

from video_processing.db.database import PipelineDB
from video_processing.core.douyin_launch_context import douyin_submission_payload_sha256


# ── Fixtures & Helpers ────────────────────────────────────────────────────────

@pytest.fixture
def char_db(tmp_path: Path):
    """独立的临时 SQLite 数据库，保证每个特征化测试零相互污染。"""
    # [Gemini_3.8_Flash_planning]
    db_path = str(tmp_path / "char_pipeline.db")
    db = PipelineDB(db_path)
    yield db


def _create_synthetic_video(db: PipelineDB, yid: str, *, title: str = "Synthetic Test Video", score: int = 85, slice_index: int = 0):
    """生成确定性的测试视频条目。"""
    # [Gemini_3.8_Flash_planning]
    db.add_video(
        youtube_id=yid,
        title=title,
        channel_id="SyntheticChannel",
        score=score,
        slice_index=slice_index,
    )
    return db.get_video_by_youtube_id(yid, slice_index=slice_index)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestCharacterizationBaseline:
    """系统不变式与基线行为特征化测试集。"""

    def test_inv007_wechat_acceptance_transaction_rollback_on_failure(self, char_db: PipelineDB):
        """[CONTRACT] INV-007: 微信提交受理三表原子性与失败回滚测试。

        契约要求：
        `record_wechat_submission_acceptance` 必须在单一 SQLite 事务内同时写入
        `wechat_publications`、`wechat_submission_attempts` 并更新 `processed_videos.status`。
        若更新 `processed_videos` 时发生故障，事务必须整体回滚，不得留下孤立的 publication 账本。
        """
        # [Gemini_3.8_Flash_planning]
        yid = "synth-wechat-tx-001"
        _create_synthetic_video(char_db, yid, score=90)

        # 注入 SQLite 触发器，在更新 processed_videos 时强制中止事务
        with char_db.get_connection() as conn:
            conn.execute(
                """
                CREATE TRIGGER fail_pv_status_update
                BEFORE UPDATE ON processed_videos
                FOR EACH ROW
                BEGIN
                    SELECT RAISE(ABORT, 'injected transaction failure for INV-007 characterization');
                END;
                """
            )
            conn.commit()

        # 执行受理记录，预期因触发器导致事务失败抛出异常
        with pytest.raises(sqlite3.IntegrityError, match="injected transaction failure"):
            char_db.record_wechat_submission_acceptance(
                yid,
                evidence_path="/tmp/synth_evidence.png",
                error_message="平台已受理提交",
                final_title="测试标题",
            )

        # 验证回滚原子性：三个相关表均不得产生持久化残留
        with char_db.get_connection() as conn:
            pubs = conn.execute("SELECT COUNT(*) AS c FROM wechat_publications").fetchone()["c"]
            attempts = conn.execute("SELECT COUNT(*) AS c FROM wechat_submission_attempts").fetchone()["c"]
            video = conn.execute(
                "SELECT status, error_msg FROM processed_videos WHERE youtube_id = ?",
                (yid,),
            ).fetchone()

        assert pubs == 0, "wechat_publications 必须被回滚"
        assert attempts == 0, "wechat_submission_attempts 必须被回滚"
        assert video["status"] == "PENDING", "processed_videos 状态必须保持回滚前的原始状态"
        assert video["error_msg"] is None

    def test_inv005_douyin_browser_launch_negative_validation_paths(self, char_db: PipelineDB, tmp_path: Path):
        """[CONTRACT] INV-005: 抖音浏览器凭据单次性与防篡改/无效凭据负向路径测试。

        契约要求：
        `begin_douyin_browser_launch` 必须严格校验凭据存在性、token 匹配、payload 摘要一致性，
        且同一凭据绝不允许被二次消费。
        """
        # [Gemini_3.8_Flash_planning]
        yid = "synth-douyin-ticket-001"
        _create_synthetic_video(char_db, yid, score=90)

        video_file = tmp_path / "douyin_asset.mp4"
        copy_file = tmp_path / "douyin_copy.txt"
        title_file = tmp_path / "douyin_title.txt"
        cover_file = tmp_path / "douyin_cover.jpg"

        video_file.write_bytes(b"synthetic video media content")
        copy_file.write_bytes(b"synthetic copy description")
        title_file.write_bytes(b"synthetic video title")
        cover_file.write_bytes(b"synthetic cover image data")

        asset_digest = hashlib.sha256(video_file.read_bytes()).hexdigest()
        payload_digest = douyin_submission_payload_sha256(
            video_path=video_file,
            copy_path=copy_file,
            title_path=title_file,
            cover_path=cover_file,
        )

        pub = char_db.create_douyin_publication(
            yid,
            asset_digest,
            str(video_file.resolve()),
            source_kind="NEW",
        )
        claim = char_db.claim_douyin_publication(pub["id"])
        assert claim is not None
        ticket_id = claim["_douyin_launch_ticket_id"]
        token = claim["_douyin_launch_token"]

        assert char_db.bind_douyin_browser_launch_ticket_payload(
            ticket_id,
            token,
            payload_sha256=payload_digest,
        )

        # 负向用例 1: 不存在的虚假 ticket_id 必须被拒绝
        assert not char_db.begin_douyin_browser_launch(
            "bogus-nonexistent-ticket-id",
            token,
            video_path=str(video_file.resolve()),
            asset_sha256=asset_digest,
            payload_sha256=payload_digest,
            require_new_source=False,
        )

        # 负向用例 2: 伪造/错误的 token 必须被拒绝
        assert not char_db.begin_douyin_browser_launch(
            ticket_id,
            "tampered_token_credential_12345678",
            video_path=str(video_file.resolve()),
            asset_sha256=asset_digest,
            payload_sha256=payload_digest,
            require_new_source=False,
        )

        # 负向用例 3: 篡改后的 payload_sha256 必须被拒绝
        tampered_payload = hashlib.sha256(b"tampered_payload_data").hexdigest()
        assert not char_db.begin_douyin_browser_launch(
            ticket_id,
            token,
            video_path=str(video_file.resolve()),
            asset_sha256=asset_digest,
            payload_sha256=tampered_payload,
            require_new_source=False,
        )

        # 正向用例: 合法凭据首次启动必须成功消费
        assert char_db.begin_douyin_browser_launch(
            ticket_id,
            token,
            video_path=str(video_file.resolve()),
            asset_sha256=asset_digest,
            payload_sha256=payload_digest,
            require_new_source=False,
        )

        # 负向用例 4: 已消费的凭据进行二次启动必须被拒绝 (One-Time Ticket Semantics)
        assert not char_db.begin_douyin_browser_launch(
            ticket_id,
            token,
            video_path=str(video_file.resolve()),
            asset_sha256=asset_digest,
            payload_sha256=payload_digest,
            require_new_source=False,
        )

    def test_inv006_wechat_reconciliation_zero_side_effect_on_sqlite(self, char_db: PipelineDB, monkeypatch):
        """[CONTRACT] INV-006: 微信回查/对账零发布端副作用特征化测试 (Publication-Side-Effect-Free)。

        契约要求：
        `PipelineManager.reconcile_wechat_under_review` 必须杜绝发布端副作用：
        1. 绝不发起新视频投稿、绝不启动发帖浏览器、绝不消耗发帖 Ticket；
        2. 当外部回查结果未决（如超时或非决定性退出码）时，保留原有绑定状态，不触发重置或重传。
        """
        # [Gemini_3.8_Flash_planning]
        from video_processing.pipeline_manager import PipelineManager
        from config.settings import settings

        monkeypatch.setattr(settings, "wechat_review_max_per_run", 5)

        pm = PipelineManager()
        pm.db = char_db

        # 1. 没有任何 BOUND 记录时，执行回查
        settled_empty = pm.reconcile_wechat_under_review()
        assert settled_empty == 0

        # 2. 插入一条待回查的 SUBMITTED_BOUND 视频记录
        yid = "synth-wechat-reconcile-001"
        _create_synthetic_video(char_db, yid, score=90)
        char_db.record_wechat_submission_acceptance(
            yid,
            evidence_path="/tmp/proof_reconcile.png",
            error_message="平台已受理",
            final_title="回查测试视频",
            platform_post_id="post_mock_12345",
        )

        # 模拟外部调用返回非决定性退出码 (例如 99，既非成功0，也非审核中6或驳回8)
        mock_process_result = mock.Mock()
        mock_process_result.returncode = 99
        mock_process_result.stdout = "inconclusive platform response"
        mock_process_result.stderr = ""

        with mock.patch.object(pm, "_run_tracked", return_value=mock_process_result) as tracked_mock:
            settled = pm.reconcile_wechat_under_review()

        assert tracked_mock.called, "回查子进程必须被以 --verify-only 执行"
        assert settled == 0, "未决结果不得标记为已解决 (settled=0)"

        # 验证数据库状态严格保持不变（无副作用）
        video = char_db.get_video_by_youtube_id(yid)
        pubs = char_db.get_wechat_publications_by_states(["SUBMITTED_BOUND"])
        assert len(pubs) == 1
        assert pubs[0]["platform_post_id"] == "post_mock_12345"
        assert pubs[0]["state"] == "SUBMITTED_BOUND"
        assert video["status"] == "SUBMITTED_BOUND"

    def test_inv008_control_plane_hard_reset_fails_closed_against_wechat_ledger(self, char_db: PipelineDB):
        """[SAFETY-REGRESSION] INV-008: 控制面硬重置对微信账本 Fail-Closed 守卫测试。

        契约要求：
        Web 控制面在面对已有提交账本（SUBMITTED_UNBOUND / PUBLISHED 等）的记录时，
        `/api/videos/{yid}/reset-hard` 必须 Fail-Closed 拒绝重置，防止已在平台投递的内容被再次调度。
        """
        # [Gemini_3.8_Flash_planning]
        import web.app
        from fastapi.testclient import TestClient

        yid = "synth-ctrl-plane-guard-001"
        _create_synthetic_video(char_db, yid, score=92)
        char_db.record_wechat_submission_acceptance(
            yid,
            evidence_path="/tmp/guard_proof.png",
            error_message="平台已受理",
            final_title="防重重置视频",
        )
        assert char_db.get_video_by_youtube_id(yid)["status"] == "SUBMITTED_UNBOUND"

        client = TestClient(web.app.app)
        with mock.patch.object(web.app, "db", char_db):
            resp = client.post(f"/api/videos/{yid}/reset-hard")
            data = resp.json()

        assert resp.status_code == 200
        assert data["success"] is False, "已有 SUBMITTED_UNBOUND 账本时必须拒绝硬重置"
        assert char_db.get_video_by_youtube_id(yid)["status"] == "SUBMITTED_UNBOUND", "状态绝不允许被改写为 PENDING"

    def test_risk_state_001_unconstrained_status_mutation_known_unsafe_baseline(self, char_db: PipelineDB):
        """[KNOWN-UNSAFE-BASELINE] RISK-STATE-001: 记录当前底层 update_video_status 缺乏发布账本防线的不安全基线。

        现状事实 (As-Is Behavior):
        当前 `PipelineDB.update_video_status` 直接执行无条件 SQL UPDATE，缺乏状态机跃迁校验与发布账本前置拦截。
        任何外部调用源（如 Telegram Bot 的 direct DB 操作）调用此方法时，均可绕过账本强行将状态重置为 PENDING。

        注意：
        本测试归类为 KNOWN-UNSAFE-BASELINE，仅用于精确记录现有系统的风险基线。
        严禁将此无约束行为视为合法契约；未来 WO-STATE-001 实施后，此行为将被状态机守卫拦截并更正测试。
        """
        # [Gemini_3.8_Flash_planning]
        yid = "synth-unsafe-mutation-001"
        _create_synthetic_video(char_db, yid, score=95)

        # 建立合法发布凭据，主状态为 SUBMITTED_UNBOUND
        char_db.record_wechat_submission_acceptance(
            yid,
            evidence_path="/tmp/unsafe_baseline_proof.png",
            error_message="平台已受理",
            final_title="风险基线视频",
        )
        assert char_db.get_video_by_youtube_id(yid)["status"] == "SUBMITTED_UNBOUND"

        # 模拟 Telegram Bot 等外部调用源直接调用底层 update_video_status
        char_db.update_video_status(yid, "PENDING", error_msg=None)

        # 记录当前实际行为：主状态被成功覆盖为 PENDING，与 publication ledger 发生分叉
        divergent_video = char_db.get_video_by_youtube_id(yid)
        assert divergent_video["status"] == "PENDING"
        with char_db.get_connection() as conn:
            pub = conn.execute("SELECT state FROM wechat_publications WHERE video_id = ?", (divergent_video["id"],)).fetchone()
        assert pub is not None and pub["state"] == "SUBMITTED_UNBOUND"

        # 验证既有修复机制可识别并纠偏此分叉
        repairs = char_db.repair_wechat_submission_status_divergence()
        assert repairs == 1
        assert char_db.get_video_by_youtube_id(yid)["status"] == "SUBMITTED_UNBOUND"

    def test_inv001_workflow_slicing_and_lifecycle_characterization(self, char_db: PipelineDB):
        """[CHARACTERIZATION ONLY] 工作流切片分流与父子生命周期特征化测试 (W-02 场景)。

        特征化行为：
        长视频经切片处理后，父视频状态标记为 SEGMENTED，各切片子任务具备独立的 slice_index 和 parent_id，
        并在后续调度与排重中以 (youtube_id, slice_index) 复合主键独立推进。

        注意：
        本测试仅作为工作流切片分解与复合主键独立调度的特征化基线，不得作为 INV-001 (工作流状态非客观发布事实)
        的核心契约证据。INV-001 的核心证据由 test_wechat_publications 与 test_v7_features 共同支撑。
        """
        # [Gemini_3.8_Flash_planning]
        parent_yid = "synth-parent-slice-001"
        parent = _create_synthetic_video(char_db, parent_yid, title="Parent Long Video", score=88, slice_index=0)
        parent_id = parent["id"]

        # 添加 2 个切片子记录
        char_db.add_video(
            youtube_id=parent_yid,
            title="Slice 1",
            channel_id="SyntheticChannel",
            score=88,
            parent_id=parent_id,
            slice_index=1,
        )
        char_db.add_video(
            youtube_id=parent_yid,
            title="Slice 2",
            channel_id="SyntheticChannel",
            score=88,
            parent_id=parent_id,
            slice_index=2,
        )

        # 更新父任务为 SEGMENTED
        char_db.update_video_status(parent_yid, "SEGMENTED", slice_index=0)

        # 验证父子关系及独立状态
        parent_after = char_db.get_video_by_youtube_id(parent_yid, slice_index=0)
        slice_1 = char_db.get_video_by_youtube_id(parent_yid, slice_index=1)
        slice_2 = char_db.get_video_by_youtube_id(parent_yid, slice_index=2)

        assert parent_after["status"] == "SEGMENTED"
        assert slice_1["parent_id"] == parent_id
        assert slice_2["parent_id"] == parent_id
        assert slice_1["status"] == "PENDING"
        assert slice_2["status"] == "PENDING"
        assert slice_1["id"] != slice_2["id"]

    def test_inv004_asset_sha256_deduplication_contract(self, char_db: PipelineDB, tmp_path: Path):
        """[CONTRACT] INV-004: 媒体指纹 asset_sha256 跨任务排重契约特征化测试。

        契约要求：
        基于媒体真实文件计算的 asset_sha256 在发布确认后形成排重记录，阻止相同媒体资产被重新绑定和重复发布。
        """
        # [Gemini_3.8_Flash_planning]
        yid_orig = "synth-sha-orig-001"
        yid_dup = "synth-sha-dup-002"
        _create_synthetic_video(char_db, yid_orig, score=85)
        _create_synthetic_video(char_db, yid_dup, score=86)

        asset_digest = hashlib.sha256(b"identical media content for sha256 dedup").hexdigest()
        dummy_path = str((tmp_path / "asset.mp4").resolve())

        # 视频 1 创建发布条目并置为 PUBLISHED
        pub_1 = char_db.create_douyin_publication(yid_orig, asset_digest, dummy_path, source_kind="HISTORY")
        assert char_db.update_douyin_publication_state(pub_1["id"], "PUBLISHED")

        # 视频 2 携带相同 asset_digest 尝试创建发布条目
        pub_2 = char_db.create_douyin_publication(yid_dup, asset_digest, dummy_path, source_kind="HISTORY")

        # 契约断言：由于相同 asset_sha256 处于 PUBLISHED 状态，返回已有发布记录而非创建新记录
        assert pub_2["id"] == pub_1["id"]
        assert pub_2["video_id"] == char_db.get_video_by_youtube_id(yid_orig)["id"]
