"""英语世界全阶段改造针对性测试与失败样本回归。

涵盖：
1. ASR 原始证据落盘与无依据零宽词阻断；
2. 封面双语引句抽取与对齐加固（缩写点防截断与闭合校验）；
3. 正文段落语法分段边界保护（介词、冠词、专名防撕裂）；
4. 离线词典音标规范化管道（保留原始音标、替换已确认字符、保留歧义符号）；
5. 主控接入 Revision 1 修订机制。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.1 | 2026-09-23 | Codex | 纠正无声学依据的测试预期，验证原证据保留、跨目录复核及双语封面重冻结。 |
| 1.0.0 | 2026-09-23 | Antigravity | 初始创建：覆盖 5 个阶段改造的回归与边界反向阻断测试。 |
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from video_processing.study_cards.caption_evidence import repair_asr_word_timestamps
from src.cover.english_world import (
    _first_sentence,
    _validate_quote_closure,
    build_english_world_cover_payload,
    validate_english_world_cover_payload,
)
from src.video_processing.study_cards.learning_dictionary import (
    normalize_phonetic,
    attach_evidence,
)
from scripts.english_world_programmatic_daily import (
    _is_safe_cut_position,
    _paragraph_word_ranges,
    _revision_draft_prompt,
    _apply_revision_draft,
)


# ─────────────────────────────────────────────────────────────────────────────
# 阶段 1：ASR 原始证据落盘与无依据零宽词阻断
# ─────────────────────────────────────────────────────────────────────────────

def test_isolated_zero_width_gap_is_not_an_acoustic_end():
    raw = [{"word": "The", "start": 1.0, "end": 1.0},
           {"word": "United", "start": 1.2, "end": 1.5}]
    with pytest.raises(ValueError, match="UNCERTAIN"):
        repair_asr_word_timestamps(raw, 3.0)
    assert raw[0]["end"] == 1.0


def test_repair_asr_word_timestamps_slice_tail_zero_width_fails():
    """验证处于切片尾部的零宽词无后续边界时，严格遵循协议阻断，不可猜测。"""
    raw = [
        {"word": "Before", "start": 0.0, "end": 0.5},
        {"word": "The", "start": 1.0, "end": 1.0},  # 切片末尾
    ]
    with pytest.raises(ValueError, match="UNCERTAIN: 零宽 ASR 词没有可证明的后续边界"):
        repair_asr_word_timestamps(raw, 2.0)


def test_repair_asr_word_timestamps_adjacent_time_regression_fails():
    """验证后随邻词时间倒退或重叠时阻断，不可非法推断。"""
    raw = [
        {"word": "The", "start": 1.0, "end": 1.0},
        {"word": "Next", "start": 0.9, "end": 1.2},  # 倒退
    ]
    with pytest.raises(ValueError, match="UNCERTAIN: 零宽 ASR 词没有可证明的后续边界"):
        repair_asr_word_timestamps(raw, 2.0)


# ─────────────────────────────────────────────────────────────────────────────
# 阶段 2：封面双语引句抽取与对齐加固
# ─────────────────────────────────────────────────────────────────────────────

def test_first_sentence_preserves_abbreviations():
    """验证常见英文缩写点（U.S., U.N., Co., Dr. 等）不被误当作句末截断。"""
    # 真实失败样本：昨日 14:00 封面截断为 several U .
    text1 = "In several U.S. states, new education laws have been passed. They will take effect next month."
    assert _first_sentence(text1) == "In several U.S. states, new education laws have been passed."

    text2 = "Apple Co. announced record earnings yesterday. Analysts were surprised."
    assert _first_sentence(text2) == "Apple Co. announced record earnings yesterday."

    text3 = "Led by Dr. Smith, the U.N. committee met at 5 p.m. to discuss the treaty. Further talks will continue."
    assert _first_sentence(text3) == "Led by Dr. Smith, the U.N. committee met at 5 p.m. to discuss the treaty."

    # 包含分词空格点的情况
    text4 = "several U . S . states passed the law. Everyone agreed."
    assert _first_sentence(text4) == "several U . S . states passed the law."


def test_validate_quote_closure_blocks_corrupted_and_truncated_quotes():
    """验证封面引语闭合校验能有效阻断专名截断、悬空词及未闭合标点。"""
    # 阻断单字母专名缩写截断 (如 several U .)
    with pytest.raises(ValueError, match="截断在单字母专名缩写处"):
        _validate_quote_closure("In several U.", "在几个州。")

    with pytest.raises(ValueError, match="包含残缺专有名词碎片"):
        _validate_quote_closure("several U organizations agreed.", "几个组织同意了。")

    # 阻断专名内部截断 (如 Ku Klux)
    with pytest.raises(ValueError, match="专有名词内部截断"):
        _validate_quote_closure("Garments worn by the Ku Klux.", "三K党所穿的服饰。")

    with pytest.raises(ValueError, match="专有名词内部截断"):
        _validate_quote_closure("Across the United.", "遍及美国。")

    # 阻断以悬空介词/连词结尾
    with pytest.raises(ValueError, match="以悬空语法词结尾"):
        _validate_quote_closure("The uniforms were worn by", "制服被穿着。")

    with pytest.raises(ValueError, match="以悬空语法词结尾"):
        _validate_quote_closure("The results are sobering and", "结果发人深省并且。")

    # 阻断双引号未闭合
    with pytest.raises(ValueError, match="双引号未闭合"):
        _validate_quote_closure('He said, "This is critical.', "他说这是关键的。")

    # 阻断规模极端不匹配
    with pytest.raises(ValueError, match="语义范围不匹配"):
        _validate_quote_closure("This is an extraordinarily long English quote that describes economic developments in detail.", "简短。")


def test_build_english_world_cover_payload_passes_valid_quote():
    """验证正常双语引语能够顺利构建并通过封面载荷校验。"""
    timeline = {
        "headline_zh": "美国多州出台新法",
        "english_text": "In several U.S. states, new education laws have taken effect. Many teachers expressed support.",
        "translation_zh": "在几个美国州，新的教育法律已经生效。许多教师表示支持。",
        "source_provenance": {"publisher": "ABC News"},
        "learning_points": [
            {"word": "education", "phonetic": "ˌedʒuˈkeɪʃn", "context_meaning_zh": "教育", "recommended_level": "中考"},
            {"word": "support", "phonetic": "səˈpɔːt", "context_meaning_zh": "支持", "recommended_level": "高考"},
        ],
    }
    payload = build_english_world_cover_payload(timeline)
    assert payload["quote_en"] == "In several U.S. states, new education laws have taken effect."
    assert payload["quote_zh"] == "在几个美国州，新的教育法律已经生效。"
    assert validate_english_world_cover_payload(payload)["content_type"] == "ENGLISH_WORLD_SHORT"


# ─────────────────────────────────────────────────────────────────────────────
# 阶段 3：正文段落语法分段边界保护
# ─────────────────────────────────────────────────────────────────────────────

def test_paragraph_word_ranges_protects_prepositions_and_entities():
    """验证分段算法绝不在介词短语（如 worn by）、冠词及专名内部（如 Ku Klux Klan）硬切。"""
    # 构造跨越切分阈值的测试词序列
    words_prefix = [{"text": f"word{i}"} for i in range(28)]
    # 在临界点放置敏感语法结构
    sensitive = [
        {"text": "garments"},
        {"text": "worn"},
        {"text": "by"},
        {"text": "the"},
        {"text": "Ku"},
        {"text": "Klux"},
        {"text": "Klan"},
        {"text": "in"},
        {"text": "the"},
        {"text": "1920s."},
    ]
    words_suffix = [{"text": f"post{i}"} for i in range(30)]
    all_words = words_prefix + sensitive + words_suffix

    ranges = _paragraph_word_ranges(all_words, maximum=32)

    # 验证所有断点安全
    for begin, end in ranges:
        if end < len(all_words):
            # 断点处的切分
            cut_idx = end
            prev_word = all_words[cut_idx - 1]["text"].lower().strip(".,!?;:")
            next_word = all_words[cut_idx]["text"].lower().strip(".,!?;:")

            # 绝不可在 by 与 the 之间断开
            assert not (prev_word == "by" and next_word == "the")
            # 绝不可在 the 与 Ku 之间断开
            assert not (prev_word == "the" and next_word == "ku")
            # 绝不可在 Ku 与 Klux 之间断开
            assert not (prev_word == "ku" and next_word == "klux")
            # 绝不可在 Klux 与 Klan 之间断开
            assert not (prev_word == "klux" and next_word == "klan")

    # 验证完整覆盖无遗漏无重叠
    assert ranges[0][0] == 0
    assert ranges[-1][1] == len(all_words)
    for i in range(len(ranges) - 1):
        assert ranges[i][1] == ranges[i + 1][0]


def test_is_safe_cut_position_rules():
    """针对性验证边界保护规则判定。"""
    words = [
        {"text": "worn"},
        {"text": "by"},
        {"text": "the"},
        {"text": "Ku"},
        {"text": "Klux"},
        {"text": "Klan"},
        {"text": "members."},
    ]
    # k=1: worn | by -> 介词短语内部 -> 不安全
    assert not _is_safe_cut_position(words, 1)
    # k=2: worn by | the -> 切在 by 后 -> 不安全
    assert not _is_safe_cut_position(words, 2)
    # k=3: by the | Ku -> 切在 the 后 -> 不安全
    assert not _is_safe_cut_position(words, 3)
    # k=4: the Ku | Klux -> 专名内部 -> 不安全
    assert not _is_safe_cut_position(words, 4)
    # k=5: Ku Klux | Klan -> 专名内部 -> 不安全
    assert not _is_safe_cut_position(words, 5)
    # k=6: Ku Klux Klan | members. -> 专名之后 -> 安全
    assert _is_safe_cut_position(words, 6)

    # 额外验证：开引号后/闭括号引号前绝不硬切
    words_quotes = [{"text": 'said: "'}, {"text": 'This'}, {"text": 'is'}, {"text": 'great.'}, {"text": '")'}]
    assert not _is_safe_cut_position(words_quotes, 1)  # said: " | This -> 紧接开引号后切
    assert not _is_safe_cut_position(words_quotes, 4)  # great. | ") -> 闭引号前切


# ─────────────────────────────────────────────────────────────────────────────
# 阶段 4：离线词典音标规范化管道
# ─────────────────────────────────────────────────────────────────────────────

def test_normalize_phonetic_cyrillic_schwa_and_leading_dots():
    """验证已确认字符替换及歧义点号保留，保留规则审计。"""
    # 真实样本：非标准西里尔字符
    raw_1 = "'s\u04d9:fis"
    norm_1, rules_1 = normalize_phonetic(raw_1)
    assert norm_1 == "'s\u0259:fis"
    assert rules_1 == ["replace_cyrillic_schwa"]

    # 真实样本：前导点格式损坏
    raw_2 = ".ˈæpl"
    norm_2, rules_2 = normalize_phonetic(raw_2)
    assert norm_2 == ".ˈæpl"
    assert rules_2 == ["unresolved_legacy_punctuation"]

    # 组合样本：前导点 + 西里尔 schwa + 尾部多余点
    raw_3 = "..əˈbav."
    norm_3, rules_3 = normalize_phonetic(raw_3)
    assert norm_3 == "..əˈbav."
    assert "unresolved_legacy_punctuation" in rules_3


def test_attach_evidence_retains_raw_and_normalized_phonetics(tmp_path, monkeypatch):
    """验证词典证据装配保留 raw_phonetic, normalized_phonetic, normalization_rules。"""
    (tmp_path / "ecdict.csv").write_text(
        "word,phonetic,definition,translation,exchange\n"
        "surface,.'s\u04d9:fis,surface,n.表面,\n",
        encoding="utf-8",
    )

    class FakeLeveler:
        def __init__(self, directory):
            assert directory == tmp_path

        def analyze_word(self, word):
            return SimpleNamespace(recommended_level="中考", source="test")

    import sys
    try:
        import src.video_processing.vocabulary.leveler as s_lev
        monkeypatch.setattr(s_lev, "VocabularyLeveler", FakeLeveler)
    except ImportError:
        pass
    try:
        import video_processing.vocabulary.leveler as v_lev
        monkeypatch.setattr(v_lev, "VocabularyLeveler", FakeLeveler)
    except ImportError:
        pass

    payload = {
        "words": [{"text": "surface"}],
        "learning_points": [{"word": "surface", "word_index": 0, "context_meaning_zh": "表面"}],
    }

    result = attach_evidence(payload, tmp_path)
    point = result["learning_points"][0]

    assert point["phonetic"] == ".'s\u0259:fis"
    assert point["raw_phonetic"] == ".'s\u04d9:fis"
    assert point["normalized_phonetic"] == ".'s\u0259:fis"
    assert "replace_cyrillic_schwa" in point["normalization_rules"]
    assert "unresolved_legacy_punctuation" in point["normalization_rules"]


# ─────────────────────────────────────────────────────────────────────────────
# 阶段 5：主控接入协议允许的 Revision 1 修订机制
# ─────────────────────────────────────────────────────────────────────────────

def test_revision_draft_prompt_contains_feedback():
    """验证 revision draft prompt 将审校反馈注入给模型。"""
    words = [{"text": "We"}, {"text": "are"}, {"text": "learning"}]
    ranges = [(0, 3)]
    timeline = {
        "headline_zh": "旧标题",
        "paragraphs": [{"translation_zh": "我们正在学习"}],
        "learning_points": [{"word_index": 2, "word": "learning", "context_meaning_zh": "学习"}],
    }
    findings = [{
        "check": "TRANSLATION_FIDELITY",
        "target": "paragraph:0",
        "evidence": "漏译语境词",
        "suggestion": "请将翻译修订为更准确的表达",
    }]

    prompt = _revision_draft_prompt(words, ranges, timeline, findings)
    assert "review_feedback" in prompt
    assert "请将翻译修订为更准确的表达" in prompt
    assert "revision=1" in prompt


def test_apply_revision_draft_generates_valid_editorial_changes():
    """验证修订初稿应用后生成合规的 editorial_changes 记录。"""
    timeline = {
        "headline_zh": "旧标题",
        "words": [{"text": "We"}, {"text": "study"}, {"text": "deeply"}, {"text": "daily"}],
        "paragraphs": [{"english_text": "We study deeply daily", "translation_zh": "我们每天研究"}],
        "learning_points": [
            {"word_index": 1, "word": "study", "context_meaning_zh": "研究"},
            {"word_index": 2, "word": "deeply", "context_meaning_zh": "深刻地"},
            {"word_index": 3, "word": "daily", "context_meaning_zh": "每日"},
        ],
    }
    draft = {
        "headline_zh": "新标题精读",
        "headline_en": "New Study",
        "translations": [{"paragraph_index": 0, "translation_zh": "我们每天深入学习"}],
        "learning_points": [
            {"word_index": 1, "pos": "v.", "context_meaning_zh": "深入学习"},
            {"word_index": 2, "pos": "adv.", "context_meaning_zh": "深刻地"},
            {"word_index": 3, "pos": "adv.", "context_meaning_zh": "每日"},
        ],
    }
    actionable = [
        {"target": "headline", "suggestion": "标题过于简略"},
        {"target": "paragraph:0", "suggestion": "翻译需要更地道"},
        {"target": "word:1", "suggestion": "语境义应为深入学习"},
    ]

    timeline["source_provenance"] = {"source_start_seconds": 10, "source_end_seconds": 20}
    updated_timeline, changes = _apply_revision_draft(timeline, draft, actionable)

    assert updated_timeline["headline_zh"] == "新标题精读"
    assert updated_timeline["paragraphs"][0]["translation_zh"] == "我们每天深入学习"
    assert len(changes) >= 3

    kinds = {c["kind"] for c in changes}
    assert "headline" in kinds
    assert "translation" in kinds
    assert "vocabulary" in kinds

    # 验证每个变更均具备必填字段
    for c in changes:
        assert c["kind"]
        assert c["before"]
        assert c["after"]
        assert c["evidence"]


@pytest.mark.parametrize("second_start", [0.0, 0.1])
def test_zero_width_group_without_positive_shared_anchor_stays_uncertain(second_start):
    raw = [{"word": "The", "start": 0.0, "end": 0.0},
           {"word": "White", "start": second_start, "end": second_start},
           {"word": "House", "start": 0.5, "end": 0.8}]
    with pytest.raises(ValueError, match="UNCERTAIN"):
        repair_asr_word_timestamps(raw, 2.0)


def test_first_sentence_with_capitalized_proper_nouns_following_abbreviation():
    """验证缩写点（U.S., U.N., Co. 等）后接大写专有名词时绝不中途误截断。"""
    cases = [
        (
            "The U.S. Supreme Court announced new rules yesterday. More details will follow.",
            "The U.S. Supreme Court announced new rules yesterday.",
        ),
        (
            "The U.S. Federal Reserve raised interest rates. Markets fell.",
            "The U.S. Federal Reserve raised interest rates.",
        ),
        (
            "In the U.N. Security Council, debate was fierce. Talks will resume tomorrow.",
            "In the U.N. Security Council, debate was fierce.",
        ),
        (
            "Apple Co. CEO Tim Cook spoke today. The stock rallied.",
            "Apple Co. CEO Tim Cook spoke today.",
        ),
    ]
    for text, expected in cases:
        assert _first_sentence(text) == expected


def test_validate_quote_closure_catches_short_truncated_quotes_and_chinese_brackets():
    """验证封面引语闭合校验能拦截过短截断碎片、未闭合书名号及悬空缩写。"""
    # 拦截类似 "The U.S." 这种仅 2 词的截断碎片
    with pytest.raises(ValueError, match="过短或不是完整句"):
        _validate_quote_closure("The U.S.", "美国国会今天宣布通过了该法案。")

    # 拦截中文书名号未闭合
    with pytest.raises(ValueError, match="中文引语引号或括号未闭合"):
        _validate_quote_closure(
            "In several U.S. states, new education laws have taken effect.",
            "在几个美国州，《新教育法 已经正式生效。",
        )

    # 拦截在介词短语缩写处残缺
    with pytest.raises(ValueError, match="在专名缩写处残缺"):
        _validate_quote_closure("by the U.S.", "由美国完成。")


def test_attach_evidence_missing_phonetic_raises_value_error(tmp_path, monkeypatch):
    """验证词条及其词元在词典中均无音标时，抛出明确的 ValueError 而非 KeyError。"""
    (tmp_path / "ecdict.csv").write_text(
        "word,phonetic,definition,translation,exchange\n"
        "foobar,,,n.未定义词,\n",
        encoding="utf-8",
    )

    class FakeLeveler:
        def __init__(self, directory):
            pass

        def analyze_word(self, word):
            return SimpleNamespace(recommended_level="中考", source="test")

    import sys
    try:
        import src.video_processing.vocabulary.leveler as s_lev
        monkeypatch.setattr(s_lev, "VocabularyLeveler", FakeLeveler)
    except ImportError:
        pass
    try:
        import video_processing.vocabulary.leveler as v_lev
        monkeypatch.setattr(v_lev, "VocabularyLeveler", FakeLeveler)
    except ImportError:
        pass

    payload = {
        "words": [{"text": "foobar"}],
        "learning_points": [{"word": "foobar", "word_index": 0, "context_meaning_zh": "测试词"}],
    }

    with pytest.raises(ValueError, match="本机词典没有 foobar 或其词元的音标"):
        attach_evidence(payload, tmp_path)


def test_generate_editorial_changes_syncs_with_density_pruning():
    """验证当 Revision 1 草稿中的词条经试算排版剪裁后，变更审计记录只保留最终保留的词条。"""
    from scripts.english_world_programmatic_daily import _generate_editorial_changes

    old_timeline = {
        "headline_zh": "旧标题",
        "paragraphs": [{"translation_zh": "旧翻译"}],
        "learning_points": [{"word_index": 0, "word": "apple", "context_meaning_zh": "苹果"}],
    }
    # 模拟经过 _fit_learning_point_density 剪裁后的最终 timeline
    # 假设模型原本想加 banana 和 cherry，但 cherry 密度超限被修剪掉，最终只有 apple 和 banana
    new_timeline = {
        "headline_zh": "新标题精读",
        "paragraphs": [{"translation_zh": "新翻译"}],
        "learning_points": [
            {"word_index": 0, "word": "apple", "context_meaning_zh": "苹果"},
            {"word_index": 1, "word": "banana", "context_meaning_zh": "香蕉"},
        ],
    }
    actionable = [{"target": "headline", "suggestion": "优化标题"}]
    new_timeline["source_provenance"] = {"source_start_seconds": 10, "source_end_seconds": 20}
    changes = _generate_editorial_changes(old_timeline, new_timeline, actionable)

    # 验证变更中只有 apple(未变不记)、banana(新增)，绝不出现已被剪裁的 cherry
    vocab_changes = [c for c in changes if c["kind"] == "vocabulary"]
    assert len(vocab_changes) == 1
    assert "banana" in vocab_changes[0]["after"]


def test_source_evidence_saves_raw_asr_before_repair_failure(tmp_path, monkeypatch):
    """验证转写证据流程在 repair_asr_word_timestamps 失败抛出异常前，raw_words 已安全落盘。"""
    from scripts.english_world_language import source_evidence

    timeline_file = tmp_path / "timeline.json"
    source_video = tmp_path / "source/source.mp4"
    source_video.parent.mkdir(parents=True, exist_ok=True)
    source_video.write_bytes(b"dummy_video_bytes")

    caption_file = tmp_path / "source/caption.json"
    caption_file.write_text(json.dumps({
        "events": [
            {"tStartMs": 0, "dDurationMs": 2000, "segs": [{"utf8": "hello world"}]}
        ]
    }), encoding="utf-8")

    model_file = tmp_path / "small.pt"
    model_file.write_bytes(b"dummy_model_bytes")

    timeline_data = {
        "english_text": "hello world",
        "source_provenance": {
            "source_video": "source/source.mp4",
            "caption_artifact": "source/caption.json",
            "source_start_seconds": 0.0,
            "source_end_seconds": 2.0,
        },
    }
    timeline_file.write_text(json.dumps(timeline_data), encoding="utf-8")

    # Mock ffmpeg run
    class FakeCompletedProcess:
        returncode = 0
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: FakeCompletedProcess())

    # Mock whisper transcribe to return a zero-width word at the tail (which will fail repair)
    class FakeWhisperModel:
        def transcribe(self, audio, **kwargs):
            return {
                "text": "hello world",
                "segments": [
                    {
                        "words": [
                            {"word": "hello", "start": 0.0, "end": 0.5},
                            {"word": "world", "start": 1.0, "end": 1.0},  # 末尾零宽词，必抛 UNCERTAIN
                        ]
                    }
                ],
            }

    import sys
    monkeypatch.setattr("whisper.load_model", lambda *args, **kwargs: FakeWhisperModel())

    with pytest.raises(ValueError, match="UNCERTAIN: 零宽 ASR 词没有可证明的后续边界"):
        source_evidence(timeline_file, model_file)

    # 验证现场证据 source_asr_raw.json 已落盘且内容完整
    raw_path = tmp_path / "qa/source_asr_raw.json"
    assert raw_path.exists(), "source_asr_raw.json 必须在 repair 之前先原子落盘"
    raw_data = json.loads(raw_path.read_text(encoding="utf-8"))
    assert raw_data["asr_text"] == "hello world"
    assert len(raw_data["raw_words"]) == 2
    assert raw_data["raw_words"][1] == {"word": "world", "start": 1.0, "end": 1.0}




def test_cover_pairs_complete_paragraph_and_refreezes_revision():
    from scripts.english_world_programmatic_daily import _freeze_publication
    from copy import deepcopy
    en = "The company cleared a hurdle after it reached a settlement with several U . S . states."
    zh = "公司跨过了一道障碍。它与美国几个州达成了和解。"
    timeline = {"language_contract": "english-world-language-v1", "headline_zh": "公司达成和解",
                "english_text": en, "translation_zh": zh,
                "paragraphs": [{"english_text": en, "translation_zh": zh}],
                "learning_points": [], "source_provenance": {"publisher": "Source"}}
    _freeze_publication(timeline)
    old = deepcopy(timeline["publication_text"])
    assert old["cover_payload"]["quote_zh"] == zh
    assert old["cover_payload"]["quote_en"] == en
    timeline["headline_zh"] = "公司跨过障碍"
    timeline["paragraphs"][0]["translation_zh"] = "这家公司跨过了一道障碍。它与美国几个州达成了和解。"
    # 渲染入口仍消费原冻结载荷；编辑入口必须显式生成新载荷。
    assert build_english_world_cover_payload(timeline) == old["cover_payload"]
    _freeze_publication(timeline)
    assert timeline["publication_text"]["cover_payload"]["title"] == "公司跨过障碍"
    assert timeline["publication_text"]["cover_payload"]["quote_zh"] == timeline["paragraphs"][0]["translation_zh"]


def test_paragraph_never_falls_back_to_an_unsafe_cut():
    from scripts.english_world_programmatic_daily import ProgrammaticDailyError
    with pytest.raises(ProgrammaticDailyError, match="安全分段"):
        _paragraph_word_ranges([{"text": "the"}] * 90)


def test_pos_only_revision_is_audited_with_source_and_exact_word_target():
    from scripts.english_world_programmatic_daily import _generate_editorial_changes
    from copy import deepcopy
    old = {"source_provenance": {"source_start_seconds": 12, "source_end_seconds": 42},
           "learning_points": [{"word_index": 1, "word": "key", "pos": "n.", "context_meaning_zh": "关键"}]}
    new = deepcopy(old)
    new["learning_points"][0]["pos"] = "adj."
    changes = _generate_editorial_changes(old, new, [
        {"target": "word:10", "suggestion": "wrong target"},
        {"target": "word:1:key", "suggestion": "correct target"}])
    assert len(changes) == 1
    assert "adj." in changes[0]["after"]
    assert "12.000–42.000s" in changes[0]["evidence"]
    assert "wrong target" not in changes[0]["evidence"]
    assert "correct target" in changes[0]["evidence"]


@pytest.mark.parametrize("medium_passes", [True, False])
def test_medium_recheck_is_once_per_source_and_preserves_raw(tmp_path, monkeypatch, medium_passes):
    from scripts import english_world_language as language
    from video_processing.study_cards.language_protocol import atomic_json, read_json, file_digest
    source, caption = tmp_path / "source.mp4", tmp_path / "caption.json"
    source.write_bytes(b"source")
    caption.write_bytes(b"caption")
    small, medium = tmp_path / "small.pt", tmp_path / "medium.pt"
    small.write_bytes(b"small")
    medium.write_bytes(b"medium")
    payload = {"english_text": "The team agreed.", "source_provenance": {
        "source_video": str(source), "caption_artifact": str(caption),
        "source_start_seconds": 10, "source_end_seconds": 20}}
    timeline = tmp_path / "first/timeline.json"
    atomic_json(timeline, payload)
    calls = []

    def transcribe(path, model):
        calls.append(model.name)
        binding = {"source_sha256": file_digest(source), "caption_sha256": file_digest(caption),
                   "model_sha256": file_digest(model), "source_start": 10, "source_end": 20,
                   "caption_parser_version": language.PARSER_VERSION}
        raw = {**binding, "raw_words": [{"word": "The", "start": 0, "end": 0}],
               "asr_text": "The team agreed.", "sample_rate": 16000, "channels": 1}
        atomic_json(path.parent / "qa/source_asr_raw.json", raw)
        if model == small or not medium_passes:
            raise ValueError("UNCERTAIN: zero width")
        atomic_json(path.parent / "qa/source_evidence.json", {
            **binding, "asr_text": "The team agreed.", "asr_words": [{"word": "The", "start": 0, "end": .2}],
            "alignment_status": "PASS", "sample_rate": 16000, "channels": 1})

    monkeypatch.setattr(language, "source_evidence", transcribe)
    tasks = tmp_path / "tasks"
    if medium_passes:
        language.source_evidence_with_recheck(timeline, small, medium, tasks)
    else:
        with pytest.raises(ValueError, match="UNCERTAIN"):
            language.source_evidence_with_recheck(timeline, small, medium, tasks)
    assert calls == ["small.pt", "medium.pt"]
    receipt = read_json(next(tasks.glob("*/source_recheck.json")))
    assert receipt["small_raw"]["raw_words"][0]["end"] == 0
    assert receipt["status"] == ("PASS" if medium_passes else "FAIL")
    # 新目录也必须读取同一来源任务的结果，不能重新发起模型计算。
    moved = tmp_path / "second/timeline.json"
    atomic_json(moved, payload)
    if medium_passes:
        language.source_evidence_with_recheck(moved, small, medium, tasks)
        assert read_json(moved.parent / "qa/source_asr_raw.json")["model_sha256"] == file_digest(medium)
    else:
        with pytest.raises(ValueError, match="禁止换目录"):
            language.source_evidence_with_recheck(moved, small, medium, tasks)
    assert calls == ["small.pt", "medium.pt"]


def test_revision_cannot_spend_review_on_an_unchanged_failed_target():
    from scripts.english_world_programmatic_daily import _generate_editorial_changes, ProgrammaticDailyError
    from copy import deepcopy
    old = {"headline_zh": "旧标题", "source_provenance": {"source_start_seconds": 10, "source_end_seconds": 20},
           "paragraphs": [{"english_text": "The team agreed.", "translation_zh": "队伍同意。"}]}
    new = deepcopy(old)
    new["headline_zh"] = "新标题"
    with pytest.raises(ProgrammaticDailyError, match="未改变审校指出的目标"):
        _generate_editorial_changes(old, new, [{"check": "TRANSLATION_ACCURACY", "target": "paragraph:0",
                                               "status": "FAIL", "severity": "P1", "suggestion": "修正翻译"}])


def test_review_cli_records_fresh_completion_and_local_failure(tmp_path, monkeypatch):
    import sys
    from scripts import english_world_language as language
    from video_processing.study_cards import language_review_service as service
    from video_processing.study_cards.language_protocol import atomic_json, read_json, digest
    timeline = tmp_path / "timeline.json"
    atomic_json(timeline, {})
    atomic_json(tmp_path / "qa/source_evidence.json", {"source_sha256": "source", "caption_sha256": "caption",
                                                       "source_start": 0, "source_end": 20})
    report = {"state": "FAIL", "cache_hit": False, "attempts": 1}
    atomic_json(tmp_path / "qa/language_qa.json", report)
    monkeypatch.setattr(sys, "argv", ["english_world_language.py", "review", "--timeline", str(timeline)])
    monkeypatch.setattr(language, "prepare", lambda *a: None)
    monkeypatch.setattr(service, "review", lambda *a, **k: dict(report, cache_hit=True))
    assert language.main() == 2
    receipt = read_json(tmp_path / "qa/review_execution.json")
    assert receipt["status"] == "COMPLETED"
    assert receipt["report_sha256"] == digest(report)  # 缓存读回可能保留更早的原始报告字节。
    def broken_prepare(*a):
        raise ValueError("词典证据过期")
    monkeypatch.setattr(language, "prepare", broken_prepare)
    assert language.main() == 2
    assert read_json(tmp_path / "qa/review_execution.json")["status"] == "ERROR"
    assert read_json(tmp_path / "qa/language_qa.json") == report
