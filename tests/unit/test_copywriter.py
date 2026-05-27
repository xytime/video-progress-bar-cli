"""Unit tests for copywriter module.

# Modification History
| Version | Date       | Author                     | Description |
|---------|------------|----------------------------|-------------|
| 1.0.0   | 2026-05-26 | Gemini_3.5_Flash_planning  | Initial creation of copywriter tests |
| 1.1.0   | 2026-05-26 | Gemini_2.5_Pro_planning    | 新增P0回归测试: ①零分fallback, ②英文子串污染, ③音乐7用例覆盖率 |
| 1.2.0   | 2026-05-27 | Gemini_3.5_Flash_planning  | 新增 graceful_truncate_title 测试用例（括号剔除与最左侧语义段优先） |
"""
import sys
import pytest
from pathlib import Path

# Add src/ and root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.copywriter import classify_category, DEFAULT_CATEGORY, graceful_truncate_title


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
