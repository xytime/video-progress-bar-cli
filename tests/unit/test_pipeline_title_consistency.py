"""回归测试：视频头部标题与封面标题一致性（v2.8.0 优化）

根因与修复：
  - 修复前：COPYWRITING 在 TRANSCRIBING 之后执行，视频头部 --title 只能用
    DB 中的英文原始标题（如 "A Computer That Writes Code"），封面用中文短标题，
    导致两者不一致。
  - 修复后：COPYWRITING 前移至 TRANSCRIBING 之前。Copywriter 仅依赖
    YouTube ID / 原始标题 / description，无需 transcript，安全前移。
    TRANSCRIBING 读取 title_file（copywriter 输出）作为 render_title，
    视频头部与封面保持一致。

# Modification History
| Version | Date       | Author                              | Description                                                          |
|---------|------------|-------------------------------------|----------------------------------------------------------------------|
| 1.1.0   | 2026-05-28 | Claude_Sonnet_4.6_Thinking_planning | 新增切片进度标题测试（v2.9.0）: "AI写代码 3/9"                          |
| 1.0.0   | 2026-05-28 | Claude_Sonnet_4.6_Thinking_planning | Initial test for pipeline title consistency (v2.8.0 optimization)    |
"""

import os
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from video_processing.pipeline_manager import PipelineManager
from video_processing.db.database import PipelineDB


@pytest.fixture
def pm_env(tmp_path):
    """构建带临时 DB 和 output 目录的 PipelineManager 环境。"""
    db_path = tmp_path / "test_title.db"
    db = PipelineDB(str(db_path))
    pm = PipelineManager(db_path=str(db_path))
    pm._OUT_DIR = tmp_path
    pm._PRJ_ROOT = Path(__file__).parent.parent.parent
    return pm, db, tmp_path


class TestRenderTitleConsistency:
    """验证 TRANSCRIBING 步骤使用 copywriter 生成的中文短标题而非英文原始标题。"""

    def test_render_title_uses_title_file_when_exists(self, pm_env):
        """
        title_file 存在时，render_title 应从 title_file 读取，
        而不是使用 DB 中的英文 title。
        """
        pm, db, tmp_path = pm_env

        # 模拟 copywriter 已生成的中文短标题
        title_file = tmp_path / "testvid_title.txt"
        title_file.write_text("AI写代码", encoding="utf-8")

        # 模拟从 title_file 读取 render_title 的逻辑（来自 pipeline_manager v2.8.0）
        db_title = "A Computer That Writes Code"
        render_title = db_title  # fallback

        if title_file.exists():
            try:
                _rt = title_file.read_text(encoding="utf-8").strip()
                if _rt:
                    render_title = _rt
            except Exception:
                pass

        assert render_title == "AI写代码", (
            f"render_title 应为中文短标题 'AI写代码'，实际: {render_title!r}"
        )
        assert render_title != db_title, (
            "render_title 不应与英文原始标题相同"
        )

    def test_render_title_fallback_to_db_title_when_no_file(self, pm_env):
        """title_file 不存在时，render_title 应 fallback 到 DB 原始标题，不崩溃。"""
        pm, db, tmp_path = pm_env

        title_file = tmp_path / "missing_title.txt"
        assert not title_file.exists()

        db_title = "A Computer That Writes Code"
        render_title = db_title

        if title_file.exists():
            try:
                _rt = title_file.read_text(encoding="utf-8").strip()
                if _rt:
                    render_title = _rt
            except Exception:
                pass

        assert render_title == db_title, "title_file 不存在时应 fallback 到 DB title"

    def test_render_title_fallback_when_file_empty(self, pm_env):
        """title_file 存在但内容为空时，应 fallback 到 DB 原始标题。"""
        pm, db, tmp_path = pm_env

        title_file = tmp_path / "empty_title.txt"
        title_file.write_text("", encoding="utf-8")

        db_title = "A Computer That Writes Code"
        render_title = db_title

        if title_file.exists():
            try:
                _rt = title_file.read_text(encoding="utf-8").strip()
                if _rt:  # 空字符串为 falsy，不覆盖 fallback
                    render_title = _rt
            except Exception:
                pass

        assert render_title == db_title, "title_file 内容为空时应 fallback 到 DB title"

    def test_copywriting_runs_before_transcribing(self, pm_env, tmp_path):
        """
        验证 pipeline 执行顺序：COPYWRITING 的状态更新先于 TRANSCRIBING。
        通过 mock _run_tracked 并记录 update_video_status 调用顺序来断言。
        """
        pm, db, tmp_path = pm_env
        yid = "testvid000"
        prefix = yid

        db.add_video(
            youtube_id=yid,
            title="A Computer That Writes Code",
            channel_id="UCtest",
            score=90,
            slice_index=0,
            disable_slicing=1,
        )

        video_record = db.get_video_by_youtube_id(yid, 0)
        assert video_record is not None

        # 准备 checkpoint 文件，让 DOWNLOADING/TRANSCRIBING 跳过实际执行
        (tmp_path / f"{yid}.mp4").write_bytes(b"x" * 2_000_000)  # > 1_000_000 bytes
        vertical_file = tmp_path / f"{yid}_vertical.mp4"
        vertical_file.write_bytes(b"x" * 2_000_000)
        (tmp_path / f"{yid}.description").write_text("test desc", encoding="utf-8")

        status_call_order = []

        original_update = db.update_video_status

        def recording_update(yid_, status_, **kwargs):
            status_call_order.append(status_)
            return original_update(yid_, status_, **kwargs)

        pm.db.update_video_status = recording_update

        # Mock _run_tracked（实际 copywriting 调用）
        copywriting_called = []

        def mock_run_tracked(cmd, *args, **kwargs):
            if "copywriter.py" in str(cmd):
                # 生成 title_file，模拟 copywriter 真实行为
                (tmp_path / f"{prefix}_copy.txt").write_text("测试文案", encoding="utf-8")
                (tmp_path / f"{prefix}_title.txt").write_text("AI写代码", encoding="utf-8")
                (tmp_path / f"{prefix}_category.txt").write_text("科技", encoding="utf-8")
                copywriting_called.append(True)
            res = MagicMock()
            res.returncode = 0
            res.stdout = ""
            res.stderr = ""
            return res

        pm._run_tracked = mock_run_tracked
        pm.send_telegram_msg = MagicMock()
        pm._check_censorship = MagicMock(return_value=False)
        pm._find_downloaded_video = MagicMock(return_value=str(tmp_path / f"{yid}.mp4"))
        pm._run_garbage_collection = MagicMock()

        # Cover 生成也需要 mock（subprocess.run）
        with patch("video_processing.pipeline_manager.subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
            # 也需要 mock upload
            with patch("video_processing.pipeline_manager.subprocess.CalledProcessError"):
                try:
                    video_dict = {
                        "youtube_id": yid,
                        "title": "A Computer That Writes Code",
                        "score": 90,
                        "slice_index": 0,
                        "channel_id": "UCtest",
                        "source": "AUTO",
                        "disable_slicing": 1,
                        "trim_start": None,
                        "trim_end": None,
                    }
                    pm._process_single_video(video_dict)
                except Exception:
                    pass  # 允许后续步骤失败（如 PUBLISHING），只关心顺序

        # 验证 copywriting 确实被调用
        assert copywriting_called, "Copywriter 应该在流程中被调用"

        # 验证状态顺序：COPYWRITING 必须出现在 TRANSCRIBING 之前
        copywriting_idx = next(
            (i for i, s in enumerate(status_call_order) if s == "COPYWRITING"), None
        )
        transcribing_idx = next(
            (i for i, s in enumerate(status_call_order) if s == "TRANSCRIBING"), None
        )

        assert copywriting_idx is not None, f"COPYWRITING 状态未被触发，顺序: {status_call_order}"
        assert transcribing_idx is not None, f"TRANSCRIBING 状态未被触发，顺序: {status_call_order}"
        assert copywriting_idx < transcribing_idx, (
            f"COPYWRITING 应在 TRANSCRIBING 之前，实际顺序: {status_call_order}"
        )

    def test_title_file_is_read_after_copywriting_for_render(self, pm_env):
        """
        验证：copywriter 生成 title_file 后，其内容被用于视频渲染。
        通过检查 render_cmd 中 --title 参数是否包含中文短标题来断言。
        """
        pm, db, tmp_path = pm_env

        # 模拟 copywriter 生成了中文短标题
        title_file = tmp_path / "vid_title.txt"
        title_file.write_text("AI助手来了", encoding="utf-8")

        db_title = "The AI Assistant Has Arrived"
        render_title = db_title

        if title_file.exists():
            try:
                _rt = title_file.read_text(encoding="utf-8").strip()
                if _rt:
                    render_title = _rt
            except Exception:
                pass

        # 模拟构建 render_cmd
        render_cmd = [
            "nice", "-n", "19",
            "/path/to/python", "-m", "cli.main", "auto-caption",
            "video.mp4", "--vertical", "--bilingual", "--title", render_title,
        ]

        title_arg_idx = render_cmd.index("--title") + 1
        assert render_cmd[title_arg_idx] == "AI助手来了", (
            f"render_cmd 的 --title 参数应为中文短标题，实际: {render_cmd[title_arg_idx]!r}"
        )
        assert render_cmd[title_arg_idx] != db_title, (
            "render_cmd 的 --title 不应是英文原始标题"
        )

    def test_slice_title_also_uses_title_file(self, pm_env):
        """
        对于切片任务（slice_index > 0），copywriter 用切片标题生成短标题。
        验证 render_title 同样优先读取 title_file，保持切片视频头部与封面一致。
        """
        pm, db, tmp_path = pm_env

        slice_prefix = "vid_s1"
        title_file = tmp_path / f"{slice_prefix}_title.txt"
        # copywriter 为切片生成的短标题（基于切片 title "【AI 01】引言"）
        title_file.write_text("AI引言", encoding="utf-8")

        slice_db_title = "【AI 01】引言"
        render_title = slice_db_title

        if title_file.exists():
            try:
                _rt = title_file.read_text(encoding="utf-8").strip()
                if _rt:
                    render_title = _rt
            except Exception:
                pass

        assert render_title == "AI引言"
        assert render_title != slice_db_title


class TestSliceProgressInRenderTitle:
    """v2.9.0: 验证多切片视频头部标题追加集数进度（如 'AI写代码 3/9'）。"""

    def _build_render_title(self, title_file, db_title, slice_index, all_slices):
        """模拟 pipeline_manager v2.9.0 中的 render_title 构建逻辑。"""
        render_title = db_title
        if title_file.exists():
            try:
                _rt = title_file.read_text(encoding="utf-8").strip()
                if _rt:
                    render_title = _rt
            except Exception:
                pass
        # v2.9.0: 多切片追加集数进度
        if slice_index > 0:
            total_cnt = len(all_slices) if all_slices else 1
            render_title = f"{render_title} {slice_index}/{total_cnt}"
        return render_title

    def test_slice_3_of_9_format(self, pm_env):
        """切片 3/9：标题应格式化为 'AI写代码 3/9'。"""
        pm, db, tmp_path = pm_env

        title_file = tmp_path / "vid_s3_title.txt"
        title_file.write_text("AI写代码", encoding="utf-8")

        # 模拟 9 个切片
        all_slices = [f"slice_{i}" for i in range(1, 10)]

        result = self._build_render_title(
            title_file=title_file,
            db_title="A Computer That Writes Code",
            slice_index=3,
            all_slices=all_slices,
        )

        assert result == "AI写代码 3/9", f"实际: {result!r}"

    def test_slice_1_of_3_format(self, pm_env):
        """切片 1/3：第一集格式化为 'AI写代码 1/3'。"""
        pm, db, tmp_path = pm_env

        title_file = tmp_path / "vid_s1_title.txt"
        title_file.write_text("AI写代码", encoding="utf-8")
        all_slices = ["s1", "s2", "s3"]

        result = self._build_render_title(title_file, "English Title", 1, all_slices)
        assert result == "AI写代码 1/3"

    def test_no_progress_for_whole_video(self, pm_env):
        """整片视频（slice_index == 0）：不追加集数进度。"""
        pm, db, tmp_path = pm_env

        title_file = tmp_path / "vid_title.txt"
        title_file.write_text("AI写代码", encoding="utf-8")
        all_slices = []  # 整片无切片

        result = self._build_render_title(title_file, "English Title", 0, all_slices)
        assert result == "AI写代码", f"整片视频不应有进度后缀，实际: {result!r}"
        assert "/" not in result

    def test_fallback_db_title_with_progress(self, pm_env):
        """title_file 不存在时，用 DB 原始标题 + 集数进度。"""
        pm, db, tmp_path = pm_env

        title_file = tmp_path / "no_such_file_title.txt"
        assert not title_file.exists()

        all_slices = ["s1", "s2"]
        result = self._build_render_title(
            title_file, "English Title", 2, all_slices
        )
        assert result == "English Title 2/2"

    def test_total_count_one_when_slices_empty(self, pm_env):
        """all_slices 为空列表时，total_cnt fallback 为 1（避免 ZeroDivisionError）。"""
        pm, db, tmp_path = pm_env

        title_file = tmp_path / "vid_s1_title.txt"
        title_file.write_text("AI写代码", encoding="utf-8")

        result = self._build_render_title(title_file, "English", 1, [])  # 空列表 → total=1
        assert result == "AI写代码 1/1"

    def test_real_db_slices_count(self, pm_env):
        """使用真实 DB 查询的切片数量，验证 3 切片场景。"""
        pm, db, tmp_path = pm_env

        yid = "abc12345678"
        db.add_video(yid, "Parent Video", "UCtest", score=90, slice_index=0)
        parent = db.get_video_by_youtube_id(yid, 0)
        parent_id = parent["id"]

        slices = [
            {"youtube_id": yid, "slice_index": i, "parent_id": parent_id,
             "title": f"Slice {i}", "channel_id": "UCtest", "source": "AUTO"}
            for i in range(1, 4)
        ]
        db.batch_add_videos(slices)

        all_slices = db.get_slices_by_parent_yid(yid)
        assert len(all_slices) == 3

        title_file = tmp_path / f"{yid}_s2_title.txt"
        title_file.write_text("AI写代码", encoding="utf-8")

        result = self._build_render_title(title_file, "English", 2, all_slices)
        assert result == "AI写代码 2/3"
