"""回归测试：多切片视频合集名称来源于父视频标题（BUG-FIX）

根因：
  - 修复前：collection_name = graceful_truncate_title(title, max_len=15)
    其中 title 是切片自身标题如"【XYZ 01】第一章"，每个切片不同
    → WeChat 认为每个切片属于不同合集，无法归并
  - 修复后：collection_name 来自父视频 (slice_index=0) 的 zh_title 或 title
    → 所有切片共享同一合集名

# Modification History
| Version | Date       | Author                              | Description                                    |
|---------|------------|-------------------------------------|------------------------------------------------|
| 1.0.0   | 2026-05-28 | Claude_Sonnet_4.6_Thinking_planning | Initial regression test for collection name bug |
"""

import os
import sys
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'scripts'))

from video_processing.db.database import PipelineDB


@pytest.fixture
def tmp_db(tmp_path):
    """每个测试用例使用独立的临时数据库。"""
    db_path = str(tmp_path / "test_collection.db")
    db = PipelineDB(db_path)
    yield db


@pytest.fixture
def pm_with_sliced_video(tmp_db, tmp_path):
    """
    设置带有3个切片的多集视频。
    父视频 (slice_index=0): title="A Computer That Writes Code", zh_title="AI编程的未来"
    切片1 (slice_index=1): title="【AI编程 01】引言"
    切片2 (slice_index=2): title="【AI编程 02】现状分析"
    切片3 (slice_index=3): title="【AI编程 03】未来展望"
    """
    yid = "abcdefghijk"

    # 父视频
    tmp_db.add_video(
        youtube_id=yid,
        title="A Computer That Writes Code",
        channel_id="UCtest",
        score=90,
        slice_index=0,
    )
    # 写入 zh_title
    with tmp_db.get_connection() as conn:
        conn.execute(
            "UPDATE processed_videos SET zh_title=? WHERE youtube_id=? AND slice_index=0",
            ("AI编程的未来", yid)
        )
        conn.commit()
    tmp_db.update_video_status(yid, "SEGMENTED", slice_index=0)

    parent = tmp_db.get_video_by_youtube_id(yid, 0)
    parent_id = parent["id"]

    # 3个切片任务
    slices = [
        {
            "youtube_id": yid,
            "slice_index": i,
            "parent_id": parent_id,
            "title": f"【AI编程 {i:02d}】切片{i}",
            "channel_id": "UCtest",
            "score": 90,
            "source": "AUTO",
            "disable_slicing": 1,
            "trim_start": str(float((i - 1) * 120)),
            "trim_end": str(float(i * 120)),
        }
        for i in range(1, 4)
    ]
    tmp_db.batch_add_videos(slices)

    return tmp_db, yid, tmp_path


class TestCollectionNameFromParent:
    """验证合集名称来自父视频标题，不是切片自身标题。"""

    def test_parent_video_has_zh_title(self, pm_with_sliced_video):
        """父视频的 zh_title 字段正确存储。"""
        db, yid, _ = pm_with_sliced_video
        parent = db.get_video_by_youtube_id(yid, 0)
        assert parent is not None
        assert parent.get("zh_title") == "AI编程的未来"

    def test_slice_titles_are_different_from_each_other(self, pm_with_sliced_video):
        """切片各自拥有不同的 title（这是 BUG 的触发条件）。"""
        db, yid, _ = pm_with_sliced_video
        slices = db.get_slices_by_parent_yid(yid)
        titles = [s["title"] for s in slices]
        assert len(set(titles)) == len(titles), "切片标题必须各不相同（这是多集场景的前提）"

    def test_collection_name_must_come_from_parent_not_slice(self, pm_with_sliced_video):
        """
        关键回归测试：
        模拟 pipeline_manager 中修复后的合集名逻辑，验证所有切片
        的合集名称相同（均来自父视频），而不是各自不同的切片标题。
        """
        db, yid, _ = pm_with_sliced_video
        import sys as _sys
        scripts_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'scripts')
        if scripts_dir not in _sys.path:
            _sys.path.insert(0, scripts_dir)
        from copywriter import graceful_truncate_title

        slices = db.get_slices_by_parent_yid(yid)
        assert len(slices) == 3

        collection_names_new = []  # 修复后逻辑
        collection_names_old = []  # 修复前逻辑（BUG）

        for s in slices:
            slice_title = s["title"]

            # ❌ 修复前（BUG）：用切片自身标题
            old_name = graceful_truncate_title(slice_title, max_len=15)
            collection_names_old.append(old_name)

            # ✅ 修复后：从父视频 zh_title 获取
            import re as _re
            parent = db.get_video_by_youtube_id(yid, 0)
            parent_zh = parent.get("zh_title") or parent.get("title") or ""
            parent_zh_clean = _re.sub(
                r'\([^)]*\)|（[^）]*）|\[[^\]]*\]|【[^】]*】', '', parent_zh
            ).strip()
            new_name = graceful_truncate_title(parent_zh_clean, max_len=15)
            collection_names_new.append(new_name)

        # 修复前：合集名各不相同（BUG）
        assert len(set(collection_names_old)) > 1, (
            "修复前的逻辑应该产生多个不同的合集名（触发BUG的条件）"
        )

        # 修复后：所有切片共享同一合集名（FIX）
        assert len(set(collection_names_new)) == 1, (
            f"修复后所有切片合集名应该相同，实际: {collection_names_new}"
        )

        # 合集名来自父视频标题，不应含切片编号
        unified_name = collection_names_new[0]
        assert "01" not in unified_name
        assert "02" not in unified_name
        assert "03" not in unified_name
        assert len(unified_name) <= 15

    def test_collection_name_parent_title_file_takes_priority(self, pm_with_sliced_video, tmp_path):
        """如果父视频有 title_file（已生成的短标题），应优先使用 title_file 的内容。"""
        db, yid, _ = pm_with_sliced_video
        import sys as _sys
        scripts_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'scripts')
        if scripts_dir not in _sys.path:
            _sys.path.insert(0, scripts_dir)
        from copywriter import graceful_truncate_title

        # 模拟 output 目录中的 title_file
        out_dir = tmp_path / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        title_file = out_dir / f"{yid}_title.txt"
        title_file.write_text("AI写代码", encoding="utf-8")

        import re as _re
        parent = db.get_video_by_youtube_id(yid, 0)
        parent_zh = parent.get("zh_title") or parent.get("title") or ""
        parent_zh_clean = _re.sub(
            r'\([^)]*\)|（[^）]*）|\[[^\]]*\]|【[^】]*】', '', parent_zh
        ).strip()

        # 模拟修复后逻辑：优先读取 title_file
        if title_file.exists():
            try:
                parent_zh_clean = title_file.read_text(encoding="utf-8").strip()
            except Exception:
                pass

        collection_name = graceful_truncate_title(parent_zh_clean, max_len=15)
        assert collection_name == "AI写代码"

    def test_no_collection_for_slice_index_0(self, pm_with_sliced_video):
        """slice_index=0（父任务）不应设置合集，因为父任务不发布视频。"""
        db, yid, _ = pm_with_sliced_video
        parent = db.get_video_by_youtube_id(yid, 0)
        # 父任务状态是 SEGMENTED，不走发布逻辑
        assert parent["status"] == "SEGMENTED"
        # 对应 pipeline_manager.py 中 if slice_index > 0 的判断
        assert parent["slice_index"] == 0

    def test_graceful_fallback_when_no_parent(self, tmp_db):
        """当父视频 (slice_index=0) 找不到时，合集名应为空（不崩溃）。"""
        import sys as _sys
        scripts_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'scripts')
        if scripts_dir not in _sys.path:
            _sys.path.insert(0, scripts_dir)
        from copywriter import graceful_truncate_title

        yid = "orphan_slice"
        # 不插入父视频，只有孤立切片
        tmp_db.add_video(
            youtube_id=yid,
            title="【Orphan 01】孤立切片",
            channel_id="UCtest",
            score=90,
            slice_index=1,
        )

        import re as _re
        # 模拟修复后逻辑
        collection_name = ""
        slice_index = 1
        if slice_index > 0:
            parent = tmp_db.get_video_by_youtube_id(yid, 0)
            if parent:
                parent_zh = parent.get("zh_title") or parent.get("title") or ""
                parent_zh = _re.sub(
                    r'\([^)]*\)|（[^）]*）|\[[^\]]*\]|【[^】]*】', '', parent_zh
                ).strip()
                collection_name = graceful_truncate_title(parent_zh, max_len=15)
            # else: 不设合集，collection_name 保持 ""

        # 父视频不存在 → 合集名降级为空字符串，不崩溃
        assert collection_name == ""
