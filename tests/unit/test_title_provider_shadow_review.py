"""标题影子评测脚本测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-24 | Codex | 覆盖影子报告不触发发布且单条 provider 失败可记录。 |
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from scripts import title_provider_shadow_review as review
from video_processing.title_provider import TitleBundle, TitleProviderError


def test_shadow_review_keeps_current_and_records_agy_candidate(monkeypatch):
    monkeypatch.setattr(
        review,
        "generate_agy_title_bundle",
        lambda **kwargs: TitleBundle(
            platform_title="AI重塑律师行业",
            display_title="20美元AI正在重塑律师行业",
            hook_subtitle="高薪法律服务被自动化替代",
        ),
    )
    report = review.build_shadow_report(
        [{
            "youtube_id": "example123",
            "title": "How a $20 AI is Replacing $235,000 Lawyers",
            "description": "An AI subscription changes legal work.",
            "short_title": "AI重塑律师行业",
        }],
        model="gemini-test",
        agy_bin="agy",
        timeout_seconds=30,
    )

    assert report["scope"] == "shadow_only_no_output_or_publication_mutation"
    assert report["sample_count"] == 1
    assert report["rows"][0]["agy"]["titles"]["display_title"] == "20美元AI正在重塑律师行业"
    assert report["rows"][0]["manual_review"]["winner"] == ""


def test_shadow_review_records_single_agy_failure(monkeypatch):
    def fail(**kwargs):
        raise TitleProviderError("timeout")

    monkeypatch.setattr(review, "generate_agy_title_bundle", fail)
    report = review.build_shadow_report(
        [{"youtube_id": "example123", "title": "A valid source title", "description": "", "short_title": "一条合规的标题内容"}],
        model="gemini-test",
        agy_bin="agy",
        timeout_seconds=30,
    )

    assert report["agy_provider_failures"] == 1
    assert report["rows"][0]["agy"] == {"provider_error": "TitleProviderError"}
