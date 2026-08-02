# -*- coding: utf-8 -*-
"""离线词汇考试分级测试。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-03 | Codex | 覆盖最低考试标签优先级、词形还原、超纲兜底与文本批量分析。 |
"""

from __future__ import annotations

from pathlib import Path
import sys

from click.testing import CliRunner

_src_root = Path(__file__).parent.parent.parent / "src"
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

from cli.commands.vocab_level import vocab_level  # noqa: E402
from video_processing.vocabulary import FriendlyTag, VocabularyLeveler  # noqa: E402


def _write_wordlists(base: Path) -> None:
    base.mkdir(exist_ok=True)
    (base / "exam-wordlists.csv").write_text(
        "\n".join([
            "word,pos,exam,phonetic,translation",
            "corporate,a.,\"CET-4,CET-6\",'kɔːpərət,\"a. 公司的, 企业的\"",
            "job,n.,\"中考,高考\",dʒɒb,\"n. 工作, 职业\"",
            "cut,v.,\"中考,高考\",kʌt,\"v. 削减, 切割\"",
            "tariff,n.,CET-6,'tærif,\"n. 关税, 价目表\"",
        ]),
        encoding="utf-8",
    )
    (base / "cefr-enhanced.csv").write_text(
        "\n".join([
            "word,level,exam,pos,phonetic,translation,definition",
            "corporate,B2,FCE/B2,a.,'kɔːpərət,\"a. 公司的, 企业的\",of a corporation",
            "job,A1,KET/A1,n.,dʒɒb,\"n. 工作, 职业\",work",
            "resilience,C2,Master/C2,n.,rɪˈzɪliəns,\"n. 恢复力, 弹性\",recovery ability",
        ]),
        encoding="utf-8",
    )
    (base / "ecdict.csv").write_text(
        "\n".join([
            "word,phonetic,definition,translation,pos,collins,oxford,tag,bnc,frq,exchange,detail,audio",
            "jobs,dʒɒbz,work entries,n. 工作（job的复数形式）,,,,,0,0,0:job/1:s,,",
            "cutting,kʌtɪŋ,cutting action,v. 削减；切割（cut的ing形式）,,,,,0,0,0:cut/1:i,,",
            "esoteric,,known by few,adj. 深奥的,,,,,0,0,,,",
        ]),
        encoding="utf-8",
    )


def test_recommended_level_uses_the_lowest_custom_exam_priority(tmp_path: Path) -> None:
    _write_wordlists(tmp_path)
    result = VocabularyLeveler(tmp_path).analyze_word(
        "corporate",
        context="Amazon is cutting corporate jobs.",
    )

    assert result.recommended_level == "CET-4"
    assert result.covered_syllabi == ("CET-4", "FCE", "CET-6")
    assert result.friendly_tag == FriendlyTag.PROGRESSIVE
    assert result.context_meaning_zh == "adj. 公司的；企业的"


def test_basic_word_combines_ket_and_middle_school(tmp_path: Path) -> None:
    _write_wordlists(tmp_path)
    result = VocabularyLeveler(tmp_path).analyze_word("job")

    assert result.recommended_level == "KET"
    assert result.covered_syllabi == ("KET", "中考", "高考")
    assert result.friendly_tag == FriendlyTag.BASIC


def test_exchange_lemma_maps_inflected_forms_before_lookup(tmp_path: Path) -> None:
    _write_wordlists(tmp_path)
    leveler = VocabularyLeveler(tmp_path)

    jobs = leveler.analyze_word("jobs")
    cutting = leveler.analyze_word("cutting")

    assert jobs.lemma == "job"
    assert jobs.recommended_level == "KET"
    assert cutting.lemma == "cut"
    assert cutting.recommended_level == "中考"
    assert cutting.context_meaning_zh.startswith("v. 削减")


def test_exchange_parser_ignores_numeric_internal_markers(tmp_path: Path) -> None:
    _write_wordlists(tmp_path)
    result = VocabularyLeveler(tmp_path).analyze_word("s3")

    assert result.lemma == "s"
    assert result.recommended_level == "Master"
    assert result.source == "unknown"


def test_ecdict_only_word_is_treated_as_master_fallback(tmp_path: Path) -> None:
    _write_wordlists(tmp_path)
    result = VocabularyLeveler(tmp_path).analyze_word("esoteric")

    assert result.recommended_level == "Master"
    assert result.covered_syllabi == ("Master",)
    assert result.friendly_tag == FriendlyTag.NEWS_ADVANCED
    assert result.source == "ecdict-fallback"


def test_text_analysis_deduplicates_targets_in_order(tmp_path: Path) -> None:
    _write_wordlists(tmp_path)
    results = VocabularyLeveler(tmp_path).analyze_text("Jobs and corporate jobs face tariff pressure.")

    assert [result.word for result in results] == ["jobs", "corporate", "face", "tariff", "pressure"]
    assert results[0].lemma == "job"
    assert results[1].recommended_level == "CET-4"
    assert results[3].friendly_tag == FriendlyTag.NEWS_ADVANCED


def test_cli_outputs_json(tmp_path: Path) -> None:
    _write_wordlists(tmp_path)
    result = CliRunner().invoke(
        vocab_level,
        ["corporate", "--text", "Amazon is cutting corporate jobs.", "--wordlist-dir", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert '"word": "corporate"' in result.output
    assert '"recommended_level": "CET-4"' in result.output
