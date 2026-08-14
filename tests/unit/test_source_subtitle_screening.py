"""选题前只读源字幕筛查回归测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-08-14 | Codex | 覆盖完整选题字幕筛查的 fail-closed P1 拦截。 |
| 1.0.0 | 2026-08-14 | Codex | 覆盖 VTT 解析与涉中台地缘政治字幕的选题拦截。 |
"""

from video_processing.utils import source_subtitle_screening as screening_module
from video_processing.utils.source_subtitle_screening import _parse_webvtt


def test_parse_webvtt_returns_deduplicated_plain_text():
    raw = (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:01.000\n"
        "<c.green>Hello &amp; welcome</c>\n\n"
        "00:00:01.000 --> 00:00:02.000\n"
        "Hello &amp; welcome\n\n"
        "00:00:02.000 --> 00:00:03.000\n"
        "China's ambitions towards Taiwan raise national security risks.\n"
    )

    text = _parse_webvtt(raw)

    assert text.splitlines() == [
        "Hello & welcome",
        "China's ambitions towards Taiwan raise national security risks.",
    ]


def test_source_screening_suspends_geopolitical_subtitle(monkeypatch):
    class FakeResponse:
        def read(self):
            return (
                b"WEBVTT\n\n00:00:00.000 --> 00:00:03.000\n"
                b"China's ambitions towards Taiwan raise national security risks.\n"
            )

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        screening_module,
        "_read_video_metadata",
        lambda *_: {
            "id": "subtitle-test",
            "title": "Semiconductor supply chain",
            "automatic_captions": {"en": [{"ext": "vtt", "url": "https://example.test/source.vtt"}]},
        },
    )
    monkeypatch.setattr(screening_module, "urlopen", lambda *_args, **_kwargs: FakeResponse())

    result = screening_module.screen_youtube_source_subtitles("https://youtu.be/subtitle-test")

    assert result.passed is False
    assert result.result is not None
    assert result.result.level == "P1"
    assert result.result.matched == "china_taiwan_geopolitical_security"
