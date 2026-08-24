"""Unit tests for copywriter module.

# Modification History
| Version | Date       | Author                     | Description |
|---------|------------|----------------------------|-------------|
| 1.0.0   | 2026-05-26 | Gemini_3.5_Flash_planning  | Initial creation of copywriter tests |
| 1.1.0   | 2026-05-26 | Gemini_2.5_Pro_planning    | 新增P0回归测试: ①零分fallback, ②英文子串污染, ③音乐7用例覆盖率 |
| 1.2.0   | 2026-05-27 | Gemini_3.5_Flash_planning  | 新增 graceful_truncate_title 测试用例（括号剔除与最左侧语义段优先） |
| 1.3.0   | 2026-06-22 | Claude_Opus_4.8            | [🅲] 新增 _apply_post_processing 兜底纠偏测试（营销词/网络梗替换、干净文本不变） |
| 1.4.0   | 2026-07-05 | Codex                      | 新增 copywriter 事实保真守门器测试：P0 阻断、正确募资语义放行 |
| 1.5.0   | 2026-07-05 | Codex                      | 新增 *_copy_quality.json 审计报告落盘测试 |
| 1.6.0   | 2026-07-05 | Codex                      | 覆盖标题/文案字段间术语一致性 warning |
| 1.7.0   | 2026-07-05 | Codex                      | 覆盖标题/文案金额单位漂移 warning |
| 1.8.0   | 2026-07-05 | Codex                      | 覆盖文案生成 prompt 注入 TranslationContext 事实与术语提示 |
| 1.9.0   | 2026-07-05 | Codex                      | 覆盖 copy quality report 写入 quality_context |
| 1.10.0  | 2026-07-06 | Codex                      | 覆盖 copy quality report 写入受保护英文实体 |
| 1.11.0  | 2026-07-06 | Codex                      | 覆盖标题/文案 warning-aware 候选仲裁 |
| 1.12.0  | 2026-07-06 | Codex                      | 覆盖文案 prompt 复用共享翻译硬约束且不带字幕段落规则 |
| 1.13.0  | 2026-08-03 | Codex                      | 回归覆盖：降级标题不得截为“为什么只有 9”，仲裁拒绝语义不完整候选 |
| 1.14.0  | 2026-08-05 | Codex                      | 覆盖文案金额数量级仅告警、不阻断的运营策略 |
| 1.15.0  | 2026-08-24 | Codex                      | 覆盖双标题灰度下缺失封面标题的兜底候选必须失败关闭。 |
"""
import json
import sys
import pytest
from pathlib import Path

# Add src/ and root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.copywriter import (
    classify_category, DEFAULT_CATEGORY, graceful_truncate_title,
    extract_headline_workaround, _apply_post_processing,
    _build_wechat_prompt, _guard_wechat_content_quality,
    _select_wechat_content_candidate, _translate_fallback,
)
from video_processing.utils.text_utils import verbatim_overlap_ratio


# ── 原有功能测试 ─────────────────────────────────────────────────────────────

def test_classify_category_music():
    """[Gemini_3.5_Flash_planning] 测试歌曲/音乐分类匹配"""
    assert classify_category("Beautiful new song by Adele", "Check out this amazing guitar acoustic cover pop music") == "娱乐"
    assert classify_category("周杰伦最新单曲演唱会", "经典吉他翻唱弹奏") == "娱乐"


def test_classify_category_gaming():
    """[Gemini_3.5_Flash_planning] 测试游戏分类匹配"""
    assert classify_category("Minecraft Let's Play Episode 1", "Gameplay walkthrough on Steam") == "游戏"
    assert classify_category("英雄联盟总决赛实况", "主机电竞手游攻略") == "游戏"


def test_classify_category_tech():
    """[Gemini_3.5_Flash_planning] 测试科技分类匹配"""
    assert classify_category("GPT-5 architecture and training details", "A new AI robot algorithm") == "科技"
    assert classify_category("英伟达最新芯片发布会", "前沿人工智能算法开发") == "科技"


def test_classify_category_finance():
    """[Gemini_3.5_Flash_planning] 测试财经分类匹配"""
    assert classify_category("Stock market crash today", "Investment strategies for Bitcoin and cryptocurrency") == "财经"


# ── P0 回归测试 (v1.7.0 修复) ────────────────────────────────────────────────

def test_zero_score_fallback_to_default():
    """[Gemini_2.5_Pro_planning] P0①: 零分时应 fallback 到 DEFAULT_CATEGORY 而非字典首键。
    修复前：max() 按 Python 字典插入顺序返回 '财经'（字典第一个定义的类别）。
    """
    result = classify_category("Untitled Video 2024", "")
    assert result == DEFAULT_CATEGORY, (
        f"Expected DEFAULT_CATEGORY ({DEFAULT_CATEGORY!r}) on zero-score input, got {result!r}. "
        "Bug: max() was returning the first dict key (财经) due to insertion order."
    )

    result2 = classify_category("XYZ QWERTY ZZZ", "")
    assert result2 == DEFAULT_CATEGORY, f"Got {result2!r} for fully unknown content"


def test_no_substring_contamination_cat_in_education():
    """[Gemini_2.5_Pro_planning] P0②: 'cat' 不应污染 'education' 导致生活类得分。
    修复前：text.count('cat') 命中 'educ-cat-ion'，给生活类错误加分。
    """
    result = classify_category("Stanford education lecture series", "Advanced university curriculum")
    assert result == "教育", (
        f"Expected 教育 but got {result!r}. "
        "Bug: 'cat' in 'education' was adding score to 生活 via substring match."
    )


def test_no_substring_contamination_war_in_software():
    """[Gemini_2.5_Pro_planning] P0②: 'war' 不应污染 'software/hardware' 给时事类加分。
    修复前：text.count('war') 分别命中 'soft-war-e' 和 'hard-war-e'，给时事类+2分，
    导致科技相关视频被误判为时事。
    """
    result = classify_category("software hardware chip developer", "coding programming AI algorithm")
    assert result == "科技", (
        f"Expected 科技 but got {result!r}. "
        "Bug: 'war' in 'software'/'hardware' was adding score to 时事."
    )


@pytest.mark.parametrize("title,desc", [
    ("The Weeknd - Blinding Lights (Official Video)", "Directed by Anton Tammi. Official music video."),
    ("Ed Sheeran - Shape of You", "Official audio from the album Divide."),
    ("Billie Eilish - bad guy", "bad guy from the debut album When We All Fall Asleep, Where Do We Go?"),
    ("Coldplay - Yellow (Live at Glastonbury)", "Live performance from 2024 world tour."),
    ("Taylor Swift - Anti-Hero", "Anti-Hero from the album Midnights. Written and directed by Taylor Swift."),
    ("Mozart Piano Sonata No.11", "Classical performance by Lang Lang at Carnegie Hall."),
    ("Imagine Dragons - Believer", "Hits collection from the rock band Imagine Dragons."),
])
def test_music_video_coverage_p0(title, desc):
    """[Gemini_2.5_Pro_planning] P0③: 真实音乐视频标题必须被正确识别为娱乐类。
    修复前 7 个用例仅 1 个通过（14%），修复后应全部通过（100%）。
    修复方案：扩充娱乐关键词库 album/track/band/official/audio/live/remix/rock/classical 等。
    """
    result = classify_category(title, desc)
    assert result == "娱乐", (
        f"Music video misclassified: {title!r} → {result!r} (expected 娱乐). "
        "Fix: expanded 娱乐 keyword list with album/track/band/official/audio/live/remix etc."
    )


# ── 优雅截断测试 ─────────────────────────────────────────────────────────────

def test_graceful_truncate_title_stoic():
    """[Gemini_3.5_Flash_planning] 测试过滤括号和最左侧语义优先。
    输入：你越不关心，情绪就越快乐（尝试一下看看）——斯多葛哲学
    预期：应剔除括号、选择最左侧且符合长度（6-16）的 '你越不关心，情绪就越快乐'，而非无条件向右倾斜。
    """
    title = "你越不关心，情绪就越快乐（尝试一下看看）——斯多葛哲学"
    # 该标题长度：27
    # 过滤括号后：你越不关心，情绪就越快乐——斯多葛哲学 (19)
    # 分词结果：['你越不关心', '，', '情绪就越快乐', '——', '斯多葛哲学']
    # Contiguous 拼接符合长度的有：
    # - '你越不关心，情绪就越快乐' (12字) -> 起始位置 0
    # - '情绪就越快乐——斯多葛哲学' (11字) -> 起始位置 2
    # 按照首部优先（起始位置升序），应选择 '你越不关心，情绪就越快乐'
    truncated = graceful_truncate_title(title, max_len=16, min_len=6)
    assert truncated == "你越不关心，情绪就越快乐", f"Expected '你越不关心，情绪就越快乐', got {truncated!r}"


def test_graceful_truncate_title_parentheses_only():
    """[Gemini_3.5_Flash_planning] 测试当括号内容去除后长度已经合规时，直接返回去除后的结果。"""
    title = "这是一款非常好的产品(非常推荐大家购买它)"
    # 去除括号后: 这是一款非常好的产品 (10字)，合规 [6, 16]
    truncated = graceful_truncate_title(title, max_len=16, min_len=6)
    assert truncated == "这是一款非常好的产品"


def test_extract_headline_workaround():
    """[Gemini_3.1_Pro_High_planning] v1.10.0 测试降级方案正则提取主干语义标题"""
    # 模式1: 发言人在前
    c, s = extract_headline_workaround("联邦银行老板表示，人工智能要做好准备，但不一定要惊慌 7.30")
    assert c == "人工智能要做好准备，但不一定要惊慌"
    assert s == "联邦银行老板表示"

    # 模式2: 发言人在后
    c, s = extract_headline_workaround("这真是一件大好事，马斯克指出")
    assert c == "这真是一件大好事"
    assert s == "马斯克指出"
    
    # 模式3: 冒号主题
    c, s = extract_headline_workaround("最新研判：A股将迎来长期大牛市")
    assert c == "A股将迎来长期大牛市"
    assert s == "最新研判"

    # 长度安全网测试：提取出的主干少于5个字，应当放弃提取
    c, s = extract_headline_workaround("专家表示，你好")
    assert c == "专家表示，你好"  # 原样返回
    assert s == ""


def test_post_processing_replaces_marketing_and_slang():
    """[Claude_Opus_4.8] 🅲: 残留的营销词/网络梗应被兜底替换为通顺表达。"""
    title, sub = _apply_post_processing("爆款Python秘籍", "保姆级教程YYDS")
    assert "爆款" not in title and "秘籍" not in title
    assert "保姆级" not in sub and "YYDS" not in sub
    assert title == "高阶Python指南"
    assert sub == "详尽教程顶级"


def test_post_processing_leaves_clean_text_untouched():
    """[Claude_Opus_4.8] 🅲: 干净文案不应被改动。"""
    title, sub = _apply_post_processing("AI如何改写代码", "程序员必备工具")
    assert title == "AI如何改写代码"
    assert sub == "程序员必备工具"


def test_wechat_prompt_includes_translation_context_for_fund_close():
    title = "MGX closes $49 billion AI fund"
    description = (
        "MGX announced the final close of Fund I at $49 billion, "
        "exceeding its initial $45 billion target."
    )

    prompt = _build_wechat_prompt(title, description)

    assert "【事实与术语上下文】" in prompt
    assert "final close" in prompt
    assert "完成募集" in prompt or "最终关账" in prompt
    assert "Treat the global context as hard constraints" in prompt
    assert "Preserve event direction, entity names, money flow, and numeric magnitude" in prompt
    assert "not 关闭/撤退" in prompt
    assert "$49B" in prompt
    assert "Do not merge, split, omit, or reorder subtitle segments" not in prompt


# ── 🅴 反搬运：原创度（逐字照搬）信号 ────────────────────────────────────────

def test_overlap_identical_is_high():
    s = "This phone has a brand new titanium frame and improved battery life."
    assert verbatim_overlap_ratio(s, s) > 0.9


def test_overlap_distinct_is_zero():
    a = "全新钛金属边框，续航大幅提升的国产旗舰手机深度体验"
    b = "A completely unrelated cooking tutorial about making pasta sauce."
    assert verbatim_overlap_ratio(a, b) == 0.0


def test_overlap_cross_language_copy_vs_english_desc_low():
    """中文原创文案 vs 英文源描述：逐字照搬比例应≈0（达到反搬运预期）。"""
    copy = "三分钟看懂这款旗舰手机的钛金属边框与续航升级，值得收藏分享。"
    desc = "The new flagship features a titanium frame and much better battery."
    assert verbatim_overlap_ratio(copy, desc) < 0.1


def test_overlap_partial_echo_detected():
    """文案中段照搬了描述的一长串 → 比例应明显>0。"""
    desc = "introducing the titanium frame with aerospace grade aluminum alloy chassis"
    copy = "重磅新品 introducing the titanium frame with aerospace grade 这就是亮点"
    assert verbatim_overlap_ratio(copy, desc) >= 0.3


def test_overlap_short_inputs_return_zero():
    assert verbatim_overlap_ratio("短", "短文本", min_run=8) == 0.0


def test_graceful_truncate_title_dangling_reporting_clause():
    """[Gemini_3.1_Pro_High_planning] v1.10.0 测试悬空动词/连词惩罚算法"""
    # 如果不惩罚“表示”，原本由于它在最左边，且长度足够，会被优先选中
    title = "联邦银行老板表示，人工智能要做好准备，但不一定要惊慌"
    truncated = graceful_truncate_title(title, max_len=16, min_len=6)
    # 因为“联邦银行老板表示”结尾有“表示”被重度惩罚(score+100)
    # “但是不一定要惊慌”以“但是”/“但”开头被中度惩罚(score+50)
    # 最终应选择中间正常的“人工智能要做好准备”
    assert truncated == "人工智能要做好准备"


def test_translate_fallback_recovers_complete_question_headline(monkeypatch):
    """机器翻译降级时，不能把《奥德赛》新闻截成“为什么只有 9”。"""
    monkeypatch.setattr(
        "scripts.copywriter._translate_text",
        lambda text, **_kwargs: (
            "为什么只有 9 个加拿大银幕可以按照诺兰的意图放映《奥德赛》"
            if text.startswith("Why only") else ""
        ),
    )

    content = _translate_fallback(
        "Why only 9 Canadian screens can show The Odyssey as Nolan intended",
        "",
    )

    assert content["short_title"] == "《奥德赛》加拿大仅9块银幕"


def test_copy_candidate_selector_rejects_incomplete_question_fragment(tmp_path):
    """即使降级候选没有翻译质量告警，也不得覆盖完整的主模型短标题。"""
    complete = {
        "short_title": "诺兰《奥德赛》",
        "hook_subtitle": "加拿大仅9块银幕可按导演意图放映",
        "copy": "加拿大只有9块银幕可以按照诺兰的意图放映《奥德赛》。",
        "category": "娱乐",
    }
    incomplete = {**complete, "short_title": "为什么只有 9"}

    selected = _select_wechat_content_candidate(
        "Why only 9 Canadian screens can show The Odyssey as Nolan intended",
        "",
        [("fallback", lambda: incomplete), ("gemini-test", lambda: complete)],
        audit_path=tmp_path / "odyssey_copy_quality.json",
    )

    assert selected["short_title"] == "诺兰《奥德赛》"
    report = json.loads((tmp_path / "odyssey_copy_quality.json").read_text(encoding="utf-8"))
    assert report["events"][0]["status"] == "rejected"
    assert "semantic_title_guard" in report["events"][0]


def test_copy_candidate_selector_requires_display_title_when_dual_title_enabled(monkeypatch, tmp_path):
    """双标题灰度中，翻译兜底不得以缺失封面标题的方式通过。"""
    monkeypatch.setattr("scripts.copywriter.settings.enable_dual_title_display", True)
    missing_display = {
        "short_title": "人工智能的虚假承诺",
        "hook_subtitle": "",
        "copy": "视频讨论人工智能宣传与现实之间的落差。",
        "category": "科技",
    }
    complete = {
        **missing_display,
        "short_title": "AI承诺争议",
        "display_title": "人工智能承诺为何受到质疑",
    }

    selected = _select_wechat_content_candidate(
        "The false promises of AI",
        "The video examines overhyped claims about artificial intelligence.",
        [("fallback", lambda: missing_display), ("gemini-test", lambda: complete)],
        audit_path=tmp_path / "dual_title_copy_quality.json",
    )

    assert selected["display_title"] == "人工智能承诺为何受到质疑"
    report = json.loads((tmp_path / "dual_title_copy_quality.json").read_text(encoding="utf-8"))
    assert report["events"][0]["status"] == "rejected"
    assert "display_title" in report["events"][0]["title_contract"]


# ── 文案事实保真守门器 ───────────────────────────────────────────────────────

def test_copy_guard_blocks_fundraising_as_market_exit():
    title = "The Money Just SOUNDED Its FINAL ALARM!"
    description = (
        "MGX announced the final close of Fund I at $49 billion, "
        "exceeding its initial $45 billion target."
    )
    content = {
        "short_title": "490亿主权基金撤退",
        "hook_subtitle": "主权基金离场",
        "copy": "这只主权投资基金选择退出市场，AI资金开始撤退。",
    }

    with pytest.raises(ValueError, match="WeChat copy quality guard blocked"):
        _guard_wechat_content_quality(title, description, content)


def test_copy_guard_allows_fundraising_complete_copy():
    title = "The Money Just SOUNDED Its FINAL ALARM!"
    description = (
        "MGX announced the final close of Fund I at $49 billion, "
        "exceeding its initial $45 billion target."
    )
    content = {
        "short_title": "AI基金超募",
        "hook_subtitle": "490亿美元完成募集",
        "copy": "MGX一期基金最终募集规模达490亿美元，超过原定450亿美元目标。",
    }

    _guard_wechat_content_quality(title, description, content)


def test_copy_guard_writes_quality_report_for_pass(tmp_path):
    title = "The Money Just SOUNDED Its FINAL ALARM!"
    description = (
        "MGX announced the final close of Fund I at $49 billion, "
        "exceeding its initial $45 billion target."
    )
    content = {
        "short_title": "AI基金超募",
        "hook_subtitle": "490亿美元完成募集",
        "copy": "MGX一期基金最终募集规模达490亿美元，超过原定450亿美元目标。",
        "category": "财经",
    }
    audit_path = tmp_path / "Z2z34FFT81c_copy_quality.json"

    _guard_wechat_content_quality(title, description, content, audit_path=audit_path, provider="unit")

    report = json.loads(audit_path.read_text(encoding="utf-8"))
    assert report["provider"] == "unit"
    assert report["status"] == "passed"
    assert report["action"] == "accept"
    assert report["content"]["short_title"] == "AI基金超募"
    assert report["quality_context"]["facts"]
    assert report["quality_context"]["entities"] == ["MGX"]
    assert any("final close" in note for note in report["quality_context"]["term_notes"])
    assert report["blocking_issues"] == []


def test_copy_guard_warns_for_field_level_term_drift(tmp_path):
    title = "The Money Just SOUNDED Its FINAL ALARM!"
    description = (
        "MGX announced the final close of Fund I at $49 billion, "
        "exceeding its initial $45 billion target."
    )
    content = {
        "short_title": "AI基金超募",
        "hook_subtitle": "490亿美元完成募集",
        "copy": "MGX在强劲投资者需求后关闭了这只基金，市场仍在加码AI。",
        "category": "财经",
    }
    audit_path = tmp_path / "Z2z34FFT81c_copy_quality.json"

    _guard_wechat_content_quality(title, description, content, audit_path=audit_path, provider="unit")

    report = json.loads(audit_path.read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["blocking_issues"] == []
    assert "TERM_CONSISTENCY_FUND_CLOSE_DRIFT" in {
        issue["code"] for issue in report["warning_issues"]
    }


def test_copy_guard_warns_for_amount_unit_drift(tmp_path):
    title = "MGX closes $49 billion AI fund"
    description = "MGX announced the final close of Fund I at $49 billion."
    content = {
        "short_title": "AI基金490亿美元",
        "hook_subtitle": "完成募集",
        "copy": "MGX一期基金最终募集规模达490亿美元，但正文另一处写成49亿美元。",
        "category": "财经",
    }
    audit_path = tmp_path / "Z2z34FFT81c_copy_quality.json"

    _guard_wechat_content_quality(title, description, content, audit_path=audit_path, provider="unit")

    report = json.loads(audit_path.read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert "AMOUNT_CONSISTENCY_UNIT_DRIFT" in {
        issue["code"] for issue in report["warning_issues"]
    }


def test_copy_guard_downgrades_amount_mismatch_to_warning(tmp_path):
    """文案含多个金额事实时，金额量级信号应告警而非停止整个发布链路。"""
    title = "Michael Burry sees a $20B AI trap"
    description = "The stock traded at $0.2 before the earnings release."
    content = {
        "short_title": "200亿美元AI陷阱",
        "hook_subtitle": "迈克尔·伯里盯上高估值",
        "copy": "伯里关注的AI风险规模达到200亿美元，市场需要复核估值与股价信号。",
        "category": "财经",
    }
    audit_path = tmp_path / "numeric_warning_copy_quality.json"

    _guard_wechat_content_quality(title, description, content, audit_path=audit_path, provider="unit")

    report = json.loads(audit_path.read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["blocking_issues"] == []
    mismatch = next(
        issue for issue in report["warning_issues"]
        if issue["code"] == "NUMBER_MAGNITUDE_MISMATCH"
    )
    assert mismatch["severity"] == "P1"


def test_copy_guard_writes_quality_report_for_block(tmp_path):
    title = "The Money Just SOUNDED Its FINAL ALARM!"
    description = (
        "MGX announced the final close of Fund I at $49 billion, "
        "exceeding its initial $45 billion target."
    )
    content = {
        "short_title": "490亿主权基金撤退",
        "hook_subtitle": "主权基金离场",
        "copy": "这只主权投资基金选择退出市场，AI资金开始撤退。",
        "category": "财经",
    }
    audit_path = tmp_path / "Z2z34FFT81c_copy_quality.json"

    with pytest.raises(ValueError, match="WeChat copy quality guard blocked"):
        _guard_wechat_content_quality(title, description, content, audit_path=audit_path, provider="unit")

    report = json.loads(audit_path.read_text(encoding="utf-8"))
    assert report["status"] == "blocked"
    assert report["action"] == "fail"
    assert report["blocking_issues"][0]["code"] == "FINANCE_EVENT_DIRECTION_REVERSAL"


def test_copy_candidate_selector_prefers_clean_fallback_after_warning(tmp_path):
    title = "MGX closes $49 billion AI fund"
    description = "MGX announced that it has closed its Fund I at $49 billion."
    warning_content = {
        "short_title": "AI基金490亿美元",
        "hook_subtitle": "完成募集",
        "copy": "MGX在强劲投资者需求后关闭了这只基金，市场仍在加码AI。",
        "category": "财经",
    }
    clean_content = {
        "short_title": "AI基金超募",
        "hook_subtitle": "490亿美元完成募集",
        "copy": "MGX一期基金最终募集规模达490亿美元。",
        "category": "财经",
    }
    audit_path = tmp_path / "Z2z34FFT81c_copy_quality.json"

    selected = _select_wechat_content_candidate(
        title,
        description,
        [
            ("gemini-test", lambda: warning_content),
            ("fallback", lambda: clean_content),
        ],
        audit_path=audit_path,
    )

    assert selected == clean_content
    report = json.loads(audit_path.read_text(encoding="utf-8"))
    assert [event["provider"] for event in report["events"]] == ["gemini-test", "fallback"]
    assert [event["selected"] for event in report["events"]] == [False, True]
    assert report["events"][0]["warning_issues"][0]["code"] == "TERM_CONSISTENCY_FUND_CLOSE_DRIFT"


def test_copy_candidate_selector_keeps_warning_candidate_when_fallback_blocked(tmp_path):
    title = "MGX closes $49 billion AI fund"
    description = "MGX announced that it has closed its Fund I at $49 billion."
    warning_content = {
        "short_title": "AI基金490亿美元",
        "hook_subtitle": "完成募集",
        "copy": "MGX在强劲投资者需求后关闭了这只基金，市场仍在加码AI。",
        "category": "财经",
    }
    blocked_content = {
        "short_title": "490亿主权基金撤退",
        "hook_subtitle": "主权基金离场",
        "copy": "这只主权投资基金选择退出市场，AI资金开始撤退。",
        "category": "财经",
    }
    audit_path = tmp_path / "Z2z34FFT81c_copy_quality.json"

    selected = _select_wechat_content_candidate(
        title,
        description,
        [
            ("gemini-test", lambda: warning_content),
            ("fallback", lambda: blocked_content),
        ],
        audit_path=audit_path,
    )

    assert selected == warning_content
    report = json.loads(audit_path.read_text(encoding="utf-8"))
    assert [event["provider"] for event in report["events"]] == ["gemini-test", "fallback"]
    assert [event["selected"] for event in report["events"]] == [True, False]
    assert report["events"][1]["action"] == "fail"
    assert report["events"][1]["blocking_issues"][0]["code"] == "FINANCE_EVENT_DIRECTION_REVERSAL"
