# -*- coding: utf-8 -*-
"""scratch/test_respec_e2e.py — Respec 规格覆盖端到端服务实测

这个脚本通过请求正在运行的 FastAPI 后端服务 (http://localhost:8765)，
对 respec 规格覆盖接口进行全方位黑盒/白盒测试：
1. 验证不存在的视频 ID
2. 验证 PENDING 任务规格更新
3. 验证 活跃状态任务 强杀原进程（优雅处理不存在的 PID）并重置触发
4. 验证 终态保护（已发布 PUBLISHED）任务拒绝覆盖规格
5. 验证 TTS 覆盖与参数更新

# Modification History
| Version | Date       | Author                     | Description |
| ------- | ---------- | -------------------------- | ----------- |
| 1.0.0   | 2026-06-01 | Gemini_3.5_Flash_planning  | 初始创建，实测 FastAPI 接口与数据库更新 |
"""

import sys
import httpx
from pathlib import Path

# 将 src/ 注入路径
PRJ_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PRJ_ROOT / "src"))

from video_processing.db.database import PipelineDB

BASE_URL = "http://localhost:8765"
TEST_YID = "test_respec_e2e_yid"


def setup_db():
    db = PipelineDB()
    # 确保清除历史测试脏数据
    db.delete_video_record(TEST_YID)
    return db


def cleanup_db(db):
    db.delete_video_record(TEST_YID)


def main():
    db = setup_db()
    print("🚀 开始 Respec 功能端到端实测...")

    try:
        # ──────────────────────────────────────────────────────────────────────
        # 1. 验证不存在的视频 ID
        # ──────────────────────────────────────────────────────────────────────
        print("\n[测试项 1] 请求不存在的视频...")
        resp = httpx.post(f"{BASE_URL}/api/videos/non_existent_yid/respec", json={
            "trim_start": "0",
            "trim_end": "10"
        })
        assert resp.status_code == 200, f"Status code: {resp.status_code}"
        data = resp.json()
        assert data["success"] is False
        assert data["error"] == "视频不存在"
        print("  ✅ 通过：不存在视频被正确拦截")

        # ──────────────────────────────────────────────────────────────────────
        # 2. 验证 PENDING 任务规格更新
        # ──────────────────────────────────────────────────────────────────────
        print("\n[测试项 2] 对 PENDING 状态任务执行 respec...")
        # 插入一个 PENDING 视频
        db.add_video(
            youtube_id=TEST_YID,
            title="Respec E2E Test Video",
            channel_id="UCtest123",
            trim_start=None,
            trim_end=None,
            disable_slicing=1,
            tts_provider=None
        )

        resp = httpx.post(f"{BASE_URL}/api/videos/{TEST_YID}/respec", json={
            "trim_start": "0:30",
            "trim_end": "1:45",
            "disable_slicing": True,
            "tts_provider": "cosyvoice"
        })
        assert resp.status_code == 200, f"Status code: {resp.status_code}"
        data = resp.json()
        print(f"DEBUG Response: {data}")
        assert data["success"] is True
        assert data["trim_start"] == "0:30"
        assert data["trim_end"] == "1:45"
        assert data["tts_provider"] == "cosyvoice"
        assert data["was_stopped"] is False  # PENDING 状态不涉及强杀进程

        # 校验数据库更新结果
        video = db.get_video_by_youtube_id(TEST_YID)
        print(f"DEBUG Database video: {dict(video) if video else None}")
        assert video is not None
        assert video["trim_start"] == "0:30"
        assert video["trim_end"] == "1:45"
        assert video["disable_slicing"] == 1
        assert video["tts_provider"] == "cosyvoice"
        assert video["status"] == "DOWNLOADING"  # 已被 claim 准备处理，所以为 DOWNLOADING
        print("  ✅ 通过：PENDING 状态规格覆盖与参数存储成功")

        # ──────────────────────────────────────────────────────────────────────
        # 3. 验证 活跃状态任务（如 DOWNLOADING）下的强杀与重置
        # ──────────────────────────────────────────────────────────────────────
        print("\n[测试项 3] 对 DOWNLOADING 状态任务执行 respec...")
        # 修改视频状态为 DOWNLOADING，并设置一个模拟 process_pid (例如 999999)
        db.update_video_status(TEST_YID, "DOWNLOADING")
        db.update_process_pid(TEST_YID, 999999)

        resp = httpx.post(f"{BASE_URL}/api/videos/{TEST_YID}/respec", json={
            "trim_start": "1:00",
            "trim_end": "2:30",
            "disable_slicing": False,
            "tts_provider": None
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["trim_start"] == "1:00"
        assert data["trim_end"] == "2:30"
        assert data["tts_provider"] is None
        assert data["was_stopped"] is True  # 触发了停止活跃任务逻辑

        # 校验数据库更新结果
        video = db.get_video_by_youtube_id(TEST_YID)
        assert video["trim_start"] == "1:00"
        assert video["trim_end"] == "2:30"
        assert video["disable_slicing"] == 0
        assert video["tts_provider"] is None
        assert video["status"] == "DOWNLOADING"  # 重新触发后再次被 claim，为 DOWNLOADING
        # process_pid 不应该再包含已被清理的 PID
        assert video["process_pid"] is None or video["process_pid"] == ""
        print("  ✅ 通过：活跃任务进程优雅强杀与重置规格成功")

        # ──────────────────────────────────────────────────────────────────────
        # 4. 验证 终态保护（PUBLISHED / SEGMENTED / IGNORED / COMPLETED）
        # ──────────────────────────────────────────────────────────────────────
        print("\n[测试项 4] 验证终态保护（以 PUBLISHED 为例）...")
        db.update_video_status(TEST_YID, "PUBLISHED")

        resp = httpx.post(f"{BASE_URL}/api/videos/{TEST_YID}/respec", json={
            "trim_start": "2:00",
            "trim_end": "3:00"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "无法覆盖规格" in data["error"]
        assert "终态保护" in data["error"]

        # 检查数据库规格，应保持原样（仍为 1:00 到 2:30）
        video = db.get_video_by_youtube_id(TEST_YID)
        assert video["trim_start"] == "1:00"
        assert video["trim_end"] == "2:30"
        assert video["status"] == "PUBLISHED"
        print("  ✅ 通过：终态保护生效，拒绝非法覆盖")

    except AssertionError as e:
        print(f"❌ 测试断言失败: {e}")
        cleanup_db(db)
        sys.exit(1)
    except Exception as e:
        print(f"❌ 测试发生意外异常: {e}")
        cleanup_db(db)
        sys.exit(1)

    cleanup_db(db)
    print("\n🎉 所有 Respec 端到端实测用例全部通过！[100% 成功]")


if __name__ == "__main__":
    main()
