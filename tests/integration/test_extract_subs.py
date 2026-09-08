"""真实 CLI → tiny ASR → SRT/ASS 验收；仅使用固定合成语音。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-05 | Codex | 初始 CLI 媒体集成验收 |
| 1.1.0 | 2026-09-08 | Codex | 固定音频与独立目录；缺依赖失败；验证完整词序、时序与双格式一致性 |
"""

from click.testing import CliRunner

from cli.main import cli
from tests.media_fixtures import (
    assert_subtitles, offline_models, save_media_evidence, speech_video,
)


def test_extract_subs_command(speech_video):
    video, record, metadata = speech_video("extract_speech")
    results = []
    for output_format in ("srt", "ass"):
        result = CliRunner().invoke(cli, ["extract-subs", str(video), "--model", "tiny",
                                         "--device", "cpu", "--format", output_format])
        assert result.exit_code == 0, result.output
        assert "Success! Subtitles saved to:" in result.output
        path = video.with_suffix(f".{output_format}")
        subs = assert_subtitles(path, record["text"], float(metadata["format"]["duration"]))
        results.append([(s.start, s.end, s.plaintext) for s in subs.events])
    assert results[0] == results[1]
    save_media_evidence("extract-subs", [video, video.with_suffix(".srt"), video.with_suffix(".ass")],
                        {"model": "tiny", "source_text": record["text"], "events": results[0],
                         "source_audio_sha256": record["sha256"], "streams": metadata["streams"]})
