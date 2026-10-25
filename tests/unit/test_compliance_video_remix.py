# -*- coding: utf-8 -*-
"""合规二创技能 (compliance-video-remix) 单元测试套件

测试覆盖：
1. 语义脱敏安检守门器 (CensorGuard)：敏感词拦截 (P0/P1/P2/CP) 与合规文本放行；
2. 上沿防遮挡字幕生成器 (SubtitleGenerator)：Alignment: 8, MarginV: 570, 关键词高亮与时间戳转换；
3. 宏观数据卡片与遮罩生成器 (CardGenerator)：980x240 RGBA 尺寸、金边磨砂玻璃板与 1080x1920 前景画框；
4. 9:16 竖屏滤镜链构建器 (VideoCompositor)：split, boxblur, 1080x608 居中原画, 动态卡片时间表达式与 ASS 滤镜；
5. 全流程编排总控演练 (RemixPipeline)：dry-run 只读验证及真实 FFmpeg 小样本。

# Modification History
| Version | Date       | Author      | Description |
| ------- | ---------- | ----------- | ----------- |
| 1.0.0   | 2026-10-25 | Antigravity | 初始创建，实现合规二创技能全套单元测试 |
"""

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from video_processing.compliance_remix import (
    ComplianceCensorGuard,
    ComplianceReport,
    FinancialCardGenerator,
    generate_vertical_frame_overlay,
    TopEdgeSubtitleGenerator,
    AudioMixerEngine,
    VideoCompositor,
    ComplianceVideoRemixPipeline,
)
from video_processing.compliance_remix.subtitle_generator import (
    apply_keyword_highlights,
    seconds_to_ass_time,
)


@pytest.fixture
def temp_workspace():
    """创建临时工作空间，测试后自动销毁。"""
    tmp = tempfile.mkdtemp(prefix="test_compliance_remix_")
    yield Path(tmp)
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def sample_manifest_data():
    """合规的宏观财经双城博弈示例数据。"""
    return {'id': 'synthetic_demo', 'title': '合成市场观察演练', 'description': '合成测试内容', 'cover_title': '合成市场观察演练', 'cover_subtitle': '观察', 'cover_label': '研究', 'category': '财经', 'badge_text': '观察', 'keywords': ['市场'], 'content_hints': ['研究'], 'chapters': [{'index': 1, 'text': '市场关注长期成本。', 'clauses': [['市场关注长期成本。', 3.0]]}], 'cards': [], 'raw_shots': [[0, 3]], 'comparison_table': [{'timestamp_range': '00:00 - 00:03', 'source_english_gist': 'Synthetic source evidence.', 'remix_chinese_commentary': '市场关注长期成本。', 'reframing_rationale': '解释商业成本。'}]}


# ==============================================================================
# 1. 语义脱敏安检守门器测试 (CensorGuard)
# ==============================================================================

def test_censor_guard_pass_clean_macro_text():
    guard = ComplianceCensorGuard()
    clean_text = "金融业占香港 GDP 超过 26%，而新加坡约为 14%。两地掌管资产均突破 5 万亿美元。"
    violations = guard.check_sentence(clean_text)
    assert len(violations) == 0, f"Expected 0 violations for clean finance text, got: {violations}"


def test_censor_guard_blocks_p0_violation():
    guard = ComplianceCensorGuard()
    # 包含敏感政治词汇
    dirty_text = "某组织主张港独并试图颠覆国家政权。"
    violations = guard.check_sentence(dirty_text)
    assert len(violations) > 0
    hit_types = [v.get("type") for v in violations]
    assert "LEGAL_BLOCKLIST" in hit_types


def test_censor_guard_blocks_channel_policy_violation():
    guard = ComplianceCensorGuard()
    # 包含地缘冲突词组（俄乌战争 / 乌克兰+冲突）
    conflict_text = "俄乌战争爆发后，多方就乌克兰冲突展开军事对抗与制裁。"
    violations = guard.check_sentence(conflict_text)
    assert len(violations) > 0
    hit_types = [v.get("type") for v in violations]
    assert "CHANNEL_POLICY" in hit_types


def test_censor_guard_validate_manifest_clean(sample_manifest_data):
    guard = ComplianceCensorGuard()
    report = guard.validate_script_manifest(sample_manifest_data)
    assert report.passed is True
    assert report.total_items_checked > 0
    assert len(report.violations) == 0


def test_censor_guard_validate_manifest_with_violation(sample_manifest_data):
    guard = ComplianceCensorGuard()
    # 注入违规卡片
    bad_manifest = dict(sample_manifest_data)
    bad_manifest["cards"] = [
        {
            "id": "bad_card",
            "tag": "违规指标",
            "title": "港独活动资金流向分析",
            "col1_lbl": "违规项",
            "col1_val": "0",
            "col2_lbl": "数值",
            "col2_val": "100",
        }
    ]
    report = guard.validate_script_manifest(bad_manifest)
    assert report.passed is False
    assert len(report.violations) > 0


# ==============================================================================
# 2. 上沿防遮挡字幕生成器测试 (SubtitleGenerator)
# ==============================================================================

def test_seconds_to_ass_time():
    assert seconds_to_ass_time(0.0) == "0:00:00.00"
    assert seconds_to_ass_time(3.85) == "0:00:03.85"
    assert seconds_to_ass_time(65.12) == "0:01:05.12"
    assert seconds_to_ass_time(3665.45) == "1:01:05.45"


def test_apply_keyword_highlights():
    text = "双方争夺数万亿美元全球资本主导权。"
    keywords = ["数万亿美元", "资本主导权"]
    res = apply_keyword_highlights(text, keywords)
    assert "{\\c&H20D0FF&}数万亿美元{\\c&HFFFFFF&}" in res
    assert "{\\c&H20D0FF&}资本主导权{\\c&HFFFFFF&}" in res


def test_subtitle_generator_structure(temp_workspace):
    gen = TopEdgeSubtitleGenerator()
    header = gen.build_ass_header("Test Title")

    assert "PlayResX: 1080" in header
    assert "PlayResY: 1920" in header
    # 必须保证 Alignment: 8 (Top-Center) 与 MarginV: 570
    assert "8,30,30,570,1" in header or ",8,30,30,570,1" in header

    clauses = [
        (0.0, 3.8, "香港与新加坡是亚洲最大的两大金融枢纽。"),
        (3.8, 8.6, "两地掌管的资产规模双双突破 5 万亿美元大关。"),
    ]
    out_ass = temp_workspace / "subtitles.ass"
    gen.generate_subtitles(clauses, out_ass, keywords=["两大金融枢纽", "5 万亿美元"])

    assert out_ass.exists()
    content = out_ass.read_text(encoding="utf-8")
    assert "Dialogue: 0,0:00:00.00,0:00:03.80,Default" in content
    assert "Dialogue: 0,0:00:03.80,0:00:08.60,Default" in content
    assert "{\\c&H20D0FF&}两大金融枢纽{\\c&HFFFFFF&}" in content


# ==============================================================================
# 3. 宏观数据卡片与遮罩生成器测试 (CardGenerator)
# ==============================================================================

def test_financial_card_generation(temp_workspace):
    gen = FinancialCardGenerator()
    card_path = temp_workspace / "card_test.png"
    res_path = gen.generate_card(
        output_path=card_path,
        tag="宏观对比",
        title="测试指标对比卡片",
        col1_lbl="指标一",
        col1_val="26%",
        col2_lbl="指标二",
        col2_val="14%",
        note="测试注释信息",
    )
    assert res_path.exists()
    img = Image.open(res_path)
    assert img.size == (980, 240)
    assert img.mode == "RGBA"


def test_vertical_frame_overlay_generation(temp_workspace):
    overlay_path = temp_workspace / "vertical_overlay.png"
    res_path = generate_vertical_frame_overlay(
        output_path=overlay_path,
        canvas_w=1080,
        canvas_h=1920,
        video_y=656,
        video_h=608,
        badge_text="◆ 六维时空 ｜ 独家观察",
    )
    assert res_path.exists()
    img = Image.open(res_path)
    assert img.size == (1080, 1920)
    assert img.mode == "RGBA"


# ==============================================================================
# 4. 视频合成器滤镜链构建测试 (VideoCompositor)
# ==============================================================================

def test_video_compositor_filter_complex_construction():
    comp = VideoCompositor(ffmpeg_bin="ffmpeg")
    cards = [(3, 10.0, 20.0), (4, 30.0, 45.0)]
    ass_path = "/path/to/subtitles.ass"

    fc = comp.build_filter_complex(
        cards_with_timings=cards,
        ass_path=ass_path,
        canvas_w=1080,
        canvas_h=1920,
        fg_w=1080,
        fg_h=608,
        fg_y=656,
    )

    # 1. 验证背景模糊与暗化
    assert "boxblur=25:5" in fc
    assert "colorchannelmixer=aa=1.0:rr=0.6:gg=0.6:bb=0.6" in fc
    # 2. 验证居中 16:9 前景叠加于 y=656
    assert "overlay=0:656" in fc
    # 3. 验证顶部遮罩叠加
    assert "overlay=0:0" in fc
    # 4. 验证动态卡片坐标与时间区间
    assert "overlay=50:1310:enable='between(t,10.00,20.00)'" in fc
    assert "overlay=50:1310:enable='between(t,30.00,45.00)'" in fc
    # 5. 验证 ASS 字幕输入
    assert "ass=filename=" in fc


# ==============================================================================
# 5. 全流程编排总控演练测试 (RemixPipeline Dry-Run)
# ==============================================================================

@pytest.mark.asyncio
async def test_compliance_remix_pipeline_dry_run(temp_workspace, sample_manifest_data):
    pipeline = ComplianceVideoRemixPipeline(work_dir=temp_workspace)

    receipt = await pipeline.execute_full_pipeline(
        manifest=sample_manifest_data,
        source_video=temp_workspace / "dummy_raw.mp4",
        dry_run=True,
        upload_now=False,
    )

    assert receipt["status"] == "VALIDATED"
    assert receipt["compliance_checked"] is True
    assert receipt["upload_status"] == "NOT_SUBMITTED"
    assert list(temp_workspace.iterdir()) == []


@pytest.mark.asyncio
async def test_compliance_remix_pipeline_blocked_by_censor(temp_workspace, sample_manifest_data):
    pipeline = ComplianceVideoRemixPipeline(work_dir=temp_workspace)
    bad_manifest = dict(sample_manifest_data)
    bad_manifest["title"] = "港独活动与地缘对抗"

    with pytest.raises(PermissionError) as exc_info:
        await pipeline.execute_full_pipeline(
            manifest=bad_manifest,
            source_video=temp_workspace / "dummy_raw.mp4",
            dry_run=True,
        )
    assert "Compliance check failed" in str(exc_info.value)


# ==============================================================================
# 6. 二创解说生成器与对照表测试 (CommentaryGenerator)
# ==============================================================================

def test_commentary_generator_markdown_render():
    from video_processing.compliance_remix import CommentaryGenerator

    manifest = {
        "title": "香港 vs 新加坡：万亿财富之争",
        "cover_title": "香港 VS 新加坡",
        "cover_subtitle": "谁掌管亚洲万亿财富之争？",
        "cover_label": "深度解局",
        "category": "时政财经",
        "comparison_table": [
            {
                "timestamp_range": "00:00 - 00:30",
                "source_english_gist": "Bloomberg covers wealth fleeing to Singapore.",
                "remix_chinese_commentary": "聚焦两地资管规模（均超5万亿美元）及财税制度博弈。",
                "reframing_rationale": "拉回宏观商业体量与制度成本，剔除地缘政治对立。",
            }
        ],
        "cards": [
            {
                "tag": "宏观基本盘",
                "title": "核心金融体量对比",
                "col1_lbl": "GDP 占比",
                "col1_val": "香港 26% | 新加坡 14%",
                "col2_lbl": "资管体量",
                "col2_val": "均超 5 万亿美元",
                "note": "数据来源两地统计年鉴",
            }
        ],
    }
    md = CommentaryGenerator.render_comparison_markdown(manifest)
    assert "《原片 vs 合规二创解说对照表》" in md
    assert "香港 vs 新加坡：万亿财富之争" in md
    assert "00:00 - 00:30" in md
    assert "Bloomberg covers wealth fleeing to Singapore." in md


# ==============================================================================
# 7. 深度防绕过与边界攻防测试 (Anti-Evasion & Real FFmpeg Verification)
# ==============================================================================

def test_censor_guard_blocks_zero_width_and_dotted_evasion():
    """验证零宽字符与多重点号/符号插入无法绕过安检。"""
    guard = ComplianceCensorGuard()

    # 1. 零宽字符绕过
    zw_text = "试图在特区推进港\u200b独活动。"
    zw_violations = guard.check_sentence(zw_text)
    assert len(zw_violations) > 0, "Zero-width space evasion was not blocked!"
    assert any(v.get("type") == "LEGAL_BLOCKLIST" for v in zw_violations)

    # 2. 点号拆字绕过
    dot_text = "关于俄.乌.战.争与乌克兰.军事冲突的报道。"
    dot_violations = guard.check_sentence(dot_text)
    assert len(dot_violations) > 0, "Dotted separator evasion was not blocked!"
    assert any(v.get("type") == "CHANNEL_POLICY" for v in dot_violations)


def test_censor_guard_manifest_cover_and_metadata_coverage(sample_manifest_data):
    """验证封面标题、副标题、徽标、关键词等外围字段被严格纳管检测。"""
    guard = ComplianceCensorGuard()

    # 1. 封面标题违规
    manifest1 = dict(sample_manifest_data)
    manifest1["cover_title"] = "港独活动全纪录"
    r1 = guard.validate_script_manifest(manifest1)
    assert r1.passed is False
    assert any(v.get("context") == "manifest.cover_title" for v in r1.violations)

    # 2. 关键词列表违规
    manifest2 = dict(sample_manifest_data)
    manifest2["keywords"] = ["正常宏观", "颠覆国家政权"]
    r2 = guard.validate_script_manifest(manifest2)
    assert r2.passed is False
    assert any("keywords" in v.get("context", "") for v in r2.violations)

    # 3. 栏目徽标违规
    manifest3 = dict(sample_manifest_data)
    manifest3["badge_text"] = "◆ 港独观察 ｜ 深度透视"
    r3 = guard.validate_script_manifest(manifest3)
    assert r3.passed is False
    assert any(v.get("context") == "manifest.badge_text" for v in r3.violations)


def test_apply_keyword_highlights_prevents_tag_corruption():
    """验证当高亮关键词与 ASS 内部代码（如 FF / H / 20D0）重叠时，绝不破坏 ASS 标签结构。"""
    text = "香港是亚洲两大金融枢纽。"
    keywords = ["两大金融枢纽", "FF", "20D0", "金融枢纽"]
    hl = apply_keyword_highlights(text, keywords)

    # 验证主关键词完整高亮且标签未被内部二次替换拆解
    assert "{\\c&H20D0FF&}两大金融枢纽{\\c&HFFFFFF&}" in hl
    assert "{\\c&H20D0{\\c" not in hl, "ASS tag was corrupted by recursive substring replace!"


def test_video_compositor_rejects_unverified_nonempty_cache(temp_workspace):
    """旧非空假缓存不能跳过真实源文件验证。"""
    comp = VideoCompositor()
    cache_dir = temp_workspace / "broll_cache"
    clips_dir = cache_dir / "broll_clips"
    clips_dir.mkdir(parents=True)
    (clips_dir / "clip_000.mp4").write_bytes(b"dummy_clip")
    output = temp_workspace / "concat.mp4"
    with pytest.raises((ValueError, FileNotFoundError)):
        comp.extract_and_concat_broll(temp_workspace / "missing.mp4", [(0.0, 2.0)], output, cache_dir, min_duration=12.0)
    assert not output.exists()


def test_video_compositor_real_ffmpeg_rendering_end_to_end(temp_workspace):
    """端到端真实调用本地 FFmpeg 执行 9:16 多图层成片渲染（非 Dry-Run），验证 libass 滤镜装配。"""
    import subprocess
    import imageio_ffmpeg
    from pydub import AudioSegment

    exe = imageio_ffmpeg.get_ffmpeg_exe()
    comp = VideoCompositor(ffmpeg_bin=exe)

    # 1. 0.4 秒无声 B-Roll 源视频
    raw_video = temp_workspace / "mini_raw.mp4"
    cmd_raw = [exe, "-y", "-f", "lavfi", "-i", "color=c=navy:s=1920x1080:d=0.4:r=25", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(raw_video)]
    subprocess.run(cmd_raw, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 2. 0.4 秒无声音频
    audio_path = temp_workspace / "mini_audio.mp3"
    AudioSegment.silent(duration=400).export(str(audio_path), format="mp3")

    # 3. 前景画框
    overlay_path = temp_workspace / "mini_overlay.png"
    generate_vertical_frame_overlay(overlay_path)

    # 4. 数据卡片
    card_gen = FinancialCardGenerator()
    card_path = temp_workspace / "mini_card.png"
    card_gen.generate_card(card_path, "测试", "真实渲染测试", "指标1", "100%", "指标2", "200%")

    # 5. ASS 字幕
    sub_gen = TopEdgeSubtitleGenerator()
    ass_path = temp_workspace / "mini_sub.ass"
    sub_gen.generate_subtitles([(0.0, 0.4, "真实渲染验证通过")], ass_path)

    # 6. 真实执行合成
    output_mp4 = temp_workspace / "rendered_output.mp4"
    out_res = comp.render_final_vertical_video(
        broll_video=raw_video,
        master_audio=audio_path,
        overlay_image=overlay_path,
        cards_info=[(card_path, 0.1, 0.3)],
        ass_subtitles=ass_path,
        output_video=output_mp4,
        preset="ultrafast",
    )

    assert out_res.exists()
    assert out_res.stat().st_size > 5000, f"Rendered MP4 is too small: {out_res.stat().st_size} bytes"
