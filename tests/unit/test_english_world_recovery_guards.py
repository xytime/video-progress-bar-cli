"""英语世界日更恢复门禁测试。

# Modification History
# | Version | Date | Author | Description |
# | --- | --- | --- | --- |
# | 1.0.0 | 2026-09-03 | Codex | 固化末屏分级与来源通路失败不淘汰候选的恢复边界。 |
"""

import json
from pathlib import Path

from scripts import run_english_world_daily as daily_runner


def test_legacy_runner_applies_eight_note_gate_to_ordinary_screens_only():
    """兼容入口不得把普通屏门禁错误地施加到末屏。"""
    legacy_runner = Path(daily_runner.__file__).with_name("run_english_world_daily_codex.sh")
    prompt = legacy_runner.read_text(encoding="utf-8")

    assert "每个可见阅读屏至少 8 个微笔记" not in prompt
    assert "普通阅读屏至少 8 个微笔记" in prompt
    assert "最后一屏按可见英文词数分档" in prompt


def test_legacy_source_access_failures_do_not_blacklist_the_locked_candidate(tmp_path: Path):
    """DNS、认证和下载故障需要保留候选，避免把基础设施故障误当内容质量失败。"""
    failures = (
        "锁定来源 UIJ1PrQOyLM 后下载时 DNS解析失败，未进入正式渲染。",
        "锁定来源 UIJ1PrQOyLM 后 Cookie失效，未进入正式渲染。",
        "锁定来源 UIJ1PrQOyLM 后 TLS握手失败，未进入正式渲染。",
        "锁定来源 UIJ1PrQOyLM 后下载超时，未进入正式渲染。",
        "锁定来源 UIJ1PrQOyLM 后代理连接被重置，未进入正式渲染。",
        "锁定来源 UIJ1PrQOyLM 后渲染时下载源视频 TLS握手失败。",
        "锁定来源 UIJ1PrQOyLM 后学习卡制作下载字幕 DNS解析失败。",
        "锁定来源 UIJ1PrQOyLM 后 MP4下载源视频 TLS握手失败。",
        "锁定来源 UIJ1PrQOyLM 后音频 QA 下载字幕 DNS解析失败。",
        "锁定来源 UIJ1PrQOyLM 后真实屏幕微笔记门禁失败：词典下载 DNS解析失败。",
        "锁定来源 UIJ1PrQOyLM 后 MP4 无法由 ffprobe 解析：原片下载超时。",
        "锁定来源 UIJ1PrQOyLM 后音频 QA 门禁失败：下载字幕时代理连接被重置。",
    )
    for index, failure in enumerate(failures):
        (tmp_path / f"{index}.delivery-request.json").write_text(
            json.dumps({"kind": "failure", "failure": failure}, ensure_ascii=False),
            encoding="utf-8",
        )

    assert daily_runner._recent_rejected_youtube_ids(tmp_path) == ()


def test_explicit_legacy_quality_failure_blacklists_the_locked_candidate(tmp_path: Path):
    """真正确定性的屏幕质量失败仍要跨运行排除同一来源。"""
    (tmp_path / "quality.delivery-request.json").write_text(
        json.dumps({
            "kind": "failure",
            "failure": "锁定来源 UIJ1PrQOyLM 后，学习卡正式渲染的真实屏幕门禁失败。",
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    assert daily_runner._recent_rejected_youtube_ids(tmp_path) == ("UIJ1PrQOyLM",)
