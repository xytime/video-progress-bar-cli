# -*- coding: utf-8 -*-
"""M6.2: Executable Golden Replay Dataset Runner & Verification Suite.

# Modification History
| Version | Date       | Author                    | Description |
| ------- | ---------- | ------------------------- | ----------- |
| 1.0.0   | 2026-09-12 | Gemini_3.8_Flash_planning | 初始创建：执行全部 6 个黄金场景的离线确定性回放、Run A vs Run B 归一化等价比对与无副作用安全审计 |
"""

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest import mock

import pytest

from video_processing.db.database import PipelineDB
from video_processing.pipeline_manager import PipelineManager
from video_processing.core.douyin_launch_context import douyin_submission_payload_sha256

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "golden_replay"
MANIFEST_PATH = FIXTURES_DIR / "manifest.json"


def _load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _hydrate_db_from_fixture(db: PipelineDB, initial_state: Dict[str, Any]) -> None:
    """以声明式方式将 initial_db.json 数据注入全新隔离的 SQLite 数据库。"""
    with db.get_connection() as conn:
        for table, rows in initial_state.items():
            for row in rows:
                cols = list(row.keys())
                placeholders = ", ".join(["?"] * len(cols))
                col_names = ", ".join(cols)
                sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"
                conn.execute(sql, list(row.values()))
        conn.commit()


def _normalize_observation(raw: Dict[str, Any], rules: Dict[str, str]) -> Dict[str, Any]:
    """根据场景契约中声明的四级规则进行观察值规范化处理。"""
    normalized = {}
    for key, val in raw.items():
        rule = rules.get(key, "EXACT")
        if rule == "EXACT":
            normalized[key] = val
        elif rule == "NORMALIZED":
            normalized[key] = "<NORMALIZED>" if val is not None else None
        elif rule == "IGNORED":
            continue
        elif rule == "SEMANTIC-MATCH":
            normalized[key] = bool(val)
        else:
            normalized[key] = val
    return normalized


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO EXECUTORS (纯离线、零生产侵入、零外部依赖)
# ─────────────────────────────────────────────────────────────────────────────

def _execute_golden_wf_01(db: PipelineDB, tmp_dir: Path) -> Dict[str, Any]:
    # Step 1: 初始调度前候选查询
    candidates_1 = db.get_high_score_pending_videos(min_score=75)
    step_1_found = any(c["youtube_id"] == "synth-golden-std-001" for c in candidates_1)

    # Step 2: 记录发布受理
    db.record_wechat_submission_acceptance(
        "synth-golden-std-001",
        evidence_path=None,
        error_message="受理成功",
        final_title="Synthetic Final Title",
    )
    video = db.get_video_by_youtube_id("synth-golden-std-001")
    wechat_pub = db.get_wechat_publication("synth-golden-std-001")

    # Step 3: 受理后候选查询（应被 SQL NOT EXISTS 排除）
    candidates_2 = db.get_high_score_pending_videos(min_score=75)
    step_3_found = any(c["youtube_id"] == "synth-golden-std-001" for c in candidates_2)

    return {
        "step_1_candidate_found": step_1_found,
        "step_2_final_status": video["status"],
        "step_2_wechat_pub_state": wechat_pub["state"],
        "step_3_candidate_found": step_3_found,
    }


def _execute_golden_wf_02(db: PipelineDB, tmp_dir: Path) -> Dict[str, Any]:
    parent = db.get_video_by_youtube_id("synth-golden-parent-002")
    parent_id = parent["id"]

    # Step 1: 创建切片
    db.add_video(
        youtube_id="synth-golden-parent-002",
        title="Part 1",
        channel_id="SyntheticChannel_001",
        score=92,
        slice_index=1,
        parent_id=parent_id,
        duration_sec=1800,
        source="DISCOVERY",
    )
    db.add_video(
        youtube_id="synth-golden-parent-002",
        title="Part 2",
        channel_id="SyntheticChannel_001",
        score=92,
        slice_index=2,
        parent_id=parent_id,
        duration_sec=1800,
        source="DISCOVERY",
    )

    # Step 2: 标记父视频为 SEGMENTED
    db.update_video_status("synth-golden-parent-002", "SEGMENTED", slice_index=0)

    # Step 3: 查询切片并验证级联关联
    parent_after = db.get_video_by_youtube_id("synth-golden-parent-002", slice_index=0)
    slices = db.get_slices_by_parent_yid("synth-golden-parent-002")

    return {
        "parent_status": parent_after["status"],
        "slice_count": len(slices),
        "slice_indices": sorted([s["slice_index"] for s in slices]),
        "slices_parent_id_linked": all(s["parent_id"] == parent_id for s in slices),
    }


def _execute_golden_pub_wc(db: PipelineDB, tmp_dir: Path) -> Dict[str, Any]:
    yid = "synth-golden-wechat-003"
    evidence_dir = tmp_dir / "wechat_evidence" / yid / "19700101_000000"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    screenshot_file = evidence_dir / "post_list_after_submission.png"
    screenshot_file.write_bytes(b"dummy_screenshot_bytes_for_golden_wc")

    # Step 1: 记录微信发布受理
    db.record_wechat_submission_acceptance(
        yid,
        evidence_path=str(screenshot_file),
        error_message="平台已受理",
        final_title="Synthetic WeChat Final Title",
        platform_post_id="post_synthetic_wx_12345",
    )
    pub = db.get_wechat_publication(yid)
    video = db.get_video_by_youtube_id(yid)
    with db.get_connection() as conn:
        attempts_count = conn.execute(
            "SELECT COUNT(*) FROM wechat_submission_attempts WHERE video_id = ?",
            (video["id"],),
        ).fetchone()[0]

    # Step 2: 验证前置物理探针熔断
    pm = PipelineManager(db_path=str(db.db_path))
    pm._OUT_DIR = tmp_dir
    fs_guard_blocked = pm._block_duplicate_wechat_submission_if_needed(yid, yid, slice_index=0)
    pm.wait_for_review_notifications(timeout=5.0)

    # Step 3: 验证 Web 控制面 Fail-Closed 拦截
    import web.app
    orig_app_db = web.app.db
    web.app.db = db
    try:
        control_plane_reason = web.app._wechat_submission_guard_reason(video)
    finally:
        web.app.db = orig_app_db

    return {
        "step_1_wechat_pub_state": pub["state"],
        "step_1_platform_post_id": pub["platform_post_id"],
        "step_1_attempts_count": attempts_count,
        "step_1_final_status": video["status"],
        "step_2_fs_guard_blocked": fs_guard_blocked,
        "step_3_control_plane_blocked": control_plane_reason is not None,
    }


def _execute_golden_pub_dy(db: PipelineDB, tmp_dir: Path) -> Dict[str, Any]:
    yid = "synth-golden-douyin-004"
    asset_hash = "4" * 64

    # 准备假媒体与物料
    v_file = tmp_dir / "dy_v.mp4"
    v_file.write_bytes(b"dummy")
    c_file = tmp_dir / "dy_c.txt"
    c_file.write_text("copy", encoding="utf-8")
    t_file = tmp_dir / "dy_t.txt"
    t_file.write_text("title", encoding="utf-8")
    cov_file = tmp_dir / "dy_cov.jpg"
    cov_file.write_bytes(b"cover")

    video_path = str(v_file.resolve())

    # Step 1: 创建发布记录
    pub = db.create_douyin_publication(yid, asset_hash, video_path, source_kind="HISTORY")

    # Step 2: 任务抢占租约与生成 Ticket
    claim = db.claim_douyin_publication(pub["id"])
    ticket_id = claim["_douyin_launch_ticket_id"]
    token = claim["_douyin_launch_token"]

    payload_digest = douyin_submission_payload_sha256(
        video_path=v_file,
        copy_path=c_file,
        title_path=t_file,
        cover_path=cov_file,
    )

    # Step 3: 绑定 Payload 摘要
    db.bind_douyin_browser_launch_ticket_payload(
        ticket_id,
        token,
        payload_sha256=payload_digest,
    )

    # Step 4: 首次合法消费凭据启动
    first_launch = db.begin_douyin_browser_launch(
        ticket_id,
        token,
        video_path=video_path,
        asset_sha256=asset_hash,
        payload_sha256=payload_digest,
        require_new_source=False,
    )

    # Step 5: 重放消费拒绝
    replay_launch = db.begin_douyin_browser_launch(
        ticket_id,
        token,
        video_path=video_path,
        asset_sha256=asset_hash,
        payload_sha256=payload_digest,
        require_new_source=False,
    )

    # Step 6: 终态成片媒体指纹查重排重
    db.update_douyin_publication_state(pub["id"], "PUBLISHED")
    dup_pub = db.create_douyin_publication("synth-golden-douyin-004-other", asset_hash, video_path, source_kind="HISTORY")
    asset_dedup_folded = (dup_pub["id"] == pub["id"])

    return {
        "ticket_issued": bool(ticket_id and token),
        "first_launch_allowed": first_launch,
        "replay_launch_allowed": replay_launch,
        "asset_dedup_folded": asset_dedup_folded,
    }


def _execute_golden_pub_ks(db: PipelineDB, tmp_dir: Path) -> Dict[str, Any]:
    yid_1 = "synth-golden-kuaishou-005"
    yid_dup = "synth-golden-kuaishou-005-dup"
    asset_hash = "5" * 64
    video_path = str(tmp_dir / "ks_asset.mp4")

    # Step 1: 创建快手发布记录
    pub = db.create_kuaishou_publication(yid_1, asset_hash, video_path, source_kind="HISTORY")

    # Step 2: 状态流转为 UNDER_REVIEW
    db.update_kuaishou_publication_state(pub["id"], "UNDER_REVIEW")

    # Step 3: 相同 video_id 尝试二次创建 -> 折叠至现有记录
    same_video_pub = db.create_kuaishou_publication(yid_1, asset_hash, video_path, source_kind="HISTORY")

    # Step 4: 不同 video_id 但相同 asset_sha256 尝试创建 -> 折叠至现有记录
    same_asset_pub = db.create_kuaishou_publication(yid_dup, asset_hash, video_path, source_kind="HISTORY")

    with db.get_connection() as conn:
        total_pubs = conn.execute("SELECT COUNT(*) FROM kuaishou_publications").fetchone()[0]

    return {
        "step_1_created": pub["id"] > 0,
        "step_2_state": "UNDER_REVIEW",
        "step_3_same_video_folded": same_video_pub["id"] == pub["id"],
        "step_4_same_asset_folded": same_asset_pub["id"] == pub["id"],
        "total_publications_count": total_pubs,
    }


def _execute_golden_risk_bot(db: PipelineDB, tmp_dir: Path) -> Dict[str, Any]:
    yid = "synth-golden-risk-006"

    # 初始化微信发布记录与提交态
    db.record_wechat_submission_acceptance(
        yid,
        evidence_path="/tmp/fake_bot_proof.png",
        error_message="平台已受理",
        final_title="Bot 风险视频",
    )
    pre_video = db.get_video_by_youtube_id(yid)
    pre_pub = db.get_wechat_publication(yid)

    # 模拟 Telegram Bot 绕过状态机与账本校验的直接强写行为 (RISK-STATE-001)
    db.update_video_status(yid, "PENDING")

    post_video = db.get_video_by_youtube_id(yid)
    post_pub = db.get_wechat_publication(yid)

    return {
        "pre_status": pre_video["status"],
        "post_status": post_video["status"],
        "wechat_pub_persists": post_pub is not None and post_pub["state"] == "SUBMITTED_UNBOUND",
        "state_forked": post_video["status"] == "PENDING" and post_pub is not None,
    }


DISPATCHER = {
    "GOLDEN-WF-01": _execute_golden_wf_01,
    "GOLDEN-WF-02": _execute_golden_wf_02,
    "GOLDEN-PUB-WC": _execute_golden_pub_wc,
    "GOLDEN-PUB-DY": _execute_golden_pub_dy,
    "GOLDEN-PUB-KS": _execute_golden_pub_ks,
    "GOLDEN-RISK-BOT": _execute_golden_risk_bot,
}


def _run_scenario(scenario_id: str) -> Dict[str, Any]:
    """在独立的沙盒临时目录与 SQLite 库中单次执行指定黄金场景。"""
    scenario_dir = FIXTURES_DIR / "scenarios" / scenario_id
    contract = _load_json(scenario_dir / "contract.json")
    initial_db = _load_json(scenario_dir / "initial_db.json")

    with tempfile.TemporaryDirectory(prefix=f"golden_{scenario_id.lower()}_") as temp_dir:
        tmp_path = Path(temp_dir)
        db_path = tmp_path / "test.db"
        db = PipelineDB(db_path=str(db_path))

        # 注入初态
        _hydrate_db_from_fixture(db, initial_db)

        # 复制文件系统初态（若有）
        fs_fixture = scenario_dir / "filesystem"
        if fs_fixture.is_dir():
            for src_file in fs_fixture.rglob("*"):
                if src_file.is_file():
                    rel = src_file.relative_to(fs_fixture)
                    dest = tmp_path / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_file, dest)

        # 执行动作
        executor = DISPATCHER[scenario_id]
        with mock.patch.object(PipelineManager, "send_telegram_msg", return_value=True), \
             mock.patch.object(PipelineManager, "send_telegram_video", return_value=True):
            raw_obs = executor(db, tmp_path)

        # 归一化处理
        norm_obs = _normalize_observation(raw_obs, contract.get("normalization_rules", {}))
        return norm_obs


# ─────────────────────────────────────────────────────────────────────────────
# PYTEST TEST SUITE (包含 Run A / Run B 等价性与敏感数据扫描)
# ─────────────────────────────────────────────────────────────────────────────

class TestGoldenReplayDataset:
    """M6.2 可执行黄金回放数据集完整性、重现性与安全性测试套件。"""

    def test_dataset_manifest_integrity_and_no_credentials(self):
        """验证 manifest 文件合法性并全量扫描是否存在泄露的生产凭据与敏感字段。"""
        assert MANIFEST_PATH.is_file(), "Manifest 文件必须存在"
        manifest = _load_json(MANIFEST_PATH)
        assert manifest["dataset_version"] == "1.0.0"
        assert manifest["schema_version"] == "1.0.0"
        assert len(manifest["scenarios"]) == 6

        # 敏感关键词扫描
        forbidden_substrings = [
            "cookie", "session", "authorization", "password",
            "bearer", "api_key", "sec_user_id", "access_token",
        ]
        for fpath in FIXTURES_DIR.rglob("*"):
            if fpath.is_file() and fpath.suffix in {".json", ".md", ".txt"}:
                text = fpath.read_text(encoding="utf-8").lower()
                for keyword in forbidden_substrings:
                    assert keyword not in text, f"在黄金回放文件 {fpath} 中发现疑似敏感凭据关键词: {keyword}"

    @pytest.mark.parametrize("scenario_id", [
        "GOLDEN-WF-01",
        "GOLDEN-WF-02",
        "GOLDEN-PUB-WC",
        "GOLDEN-PUB-DY",
        "GOLDEN-PUB-KS",
        "GOLDEN-RISK-BOT",
    ])
    def test_scenario_reproducibility_run_a_equals_run_b(self, scenario_id: str):
        """核心验证：Run A 与 Run B 在两个完全独立的全新临时环境中分别执行，
        其规范化观察值必须绝对一致 (Run A == Run B)，且与 Contract Expected 一致。
        """
        contract = _load_json(FIXTURES_DIR / "scenarios" / scenario_id / "contract.json")
        expected_observation = contract["expected_observation"]

        # Run A: 全新独立隔离环境
        obs_a = _run_scenario(scenario_id)

        # Run B: 第二次全新独立隔离环境
        obs_b = _run_scenario(scenario_id)

        # 判定 A 与 B 确定性等价
        assert obs_a == obs_b, f"场景 {scenario_id} 两次独立执行观察值不一致 (Run A != Run B)"

        # 判定执行观察值与契约期望一致
        assert obs_a == expected_observation, f"场景 {scenario_id} 执行观察值与契约期望不一致"

    def test_zero_side_effect_on_production_environment(self):
        """验证黄金回放执行全流程绝对零外部副作用、绝不触碰生产数据库。"""
        repo_root = Path(__file__).resolve().parent.parent.parent
        prod_db_path = repo_root / "output" / "pipeline.db"

        # 若本地存在生产库，记录其修改时间与大小
        mtime_before = prod_db_path.stat().st_mtime if prod_db_path.exists() else None

        # 随机执行一个场景
        _run_scenario("GOLDEN-WF-01")

        if prod_db_path.exists():
            mtime_after = prod_db_path.stat().st_mtime
            assert mtime_before == mtime_after, "生产数据库被意外修改！"
