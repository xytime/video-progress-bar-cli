"""字幕占位符事故的结构性回归，含真实时间槽的最小样本。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-09 | Codex | 覆盖占位、误伤、ASS 缺失及烧录路径校验 |
"""

import pysubs2
import pytest

from video_processing.utils.subtitle_content_contract import (
    bilingual_ass_contract_error, is_translation_placeholder,
)
from video_processing.utils.subtitle_translation_provider import (
    SubtitleTranslationCandidate, apply_translation_candidate,
)


@pytest.mark.parametrize("text", ["（承接上文）", "承接上文", "【同上】", r"{\fs32}（承接\N上文）"])
def test_placeholder_is_not_translation(text):
    candidate = SubtitleTranslationCandidate("Gemini", ["正常译文", text])
    assert not candidate.is_usable_for(2)
    assert candidate.contract_error_for(2) == "translation_placeholder: index=1"
    segments = [{"zh_text": "original"}, {}]
    with pytest.raises(ValueError, match="translation_placeholder"):
        apply_translation_candidate(segments, candidate)
    assert segments == [{"zh_text": "original"}, {}]


@pytest.mark.parametrize("text", ["这句话承接上文的讨论。", "同上周相比，收益率上涨。", "上文提到的政策已经改变。"])
def test_real_sentences_not_rejected(text):
    assert not is_translation_placeholder(text)


def test_extra_translation_cannot_be_silently_truncated():
    assert not SubtitleTranslationCandidate("Gemini", ["一", "二"]).is_usable_for(1)


def write_ass(path, chinese="（承接上文）"):
    subs = pysubs2.SSAFile()
    subs.append(pysubs2.SSAEvent(
        start=7200, end=11600,
        text=r"{\fnGeorgia}But in this video, you're going to understand exactly why the 10-year Treasury is sitting"
             + r"\N{\fnHiragino Sans GB}" + chinese,
    ))
    subs.save(str(path))


@pytest.mark.parametrize("chinese", ["（承接上文）", r"（承接\N上文）"])
def test_real_failure_slot_rejected_from_ass(tmp_path, chinese):
    path = tmp_path / "Q-4-pNP4NKE.ass"
    write_ass(path, chinese)
    assert "@7.20s" in bilingual_ass_contract_error(path)


def test_valid_ass_accepted(tmp_path):
    path = tmp_path / "good.ass"
    write_ass(path, "但通过这段视频，你会明白十年期国债为何处于这一水平")
    assert bilingual_ass_contract_error(path) is None


@pytest.mark.parametrize("contents", [None, "garbage", "[Events]\n", b"\xff"])
def test_missing_or_malformed_ass_not_verified(tmp_path, contents):
    path = tmp_path / "bad.ass"
    if isinstance(contents, bytes):
        path.write_bytes(contents)
    elif contents is not None:
        path.write_text(contents)
    assert bilingual_ass_contract_error(path)
