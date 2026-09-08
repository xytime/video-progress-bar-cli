"""真实 base ASR 与无翻译字幕烧录验收，不访问翻译供应商。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-09-08 | Codex | 固定语音、实际字幕内容/时序、成片音轨和字幕像素验收 |
"""

from PIL import Image, ImageChops

from video_processing.processors.caption_processor import AutoCaptionProcessor
from tests.media_fixtures import (
    assert_subtitles, capture_frame, offline_models, probe_media, run_media, save_media_evidence, speech_video,
)


def test_transcription(speech_video, tmp_path):
    video, record, metadata = speech_video("caption_speech")
    stages = []
    processor = AutoCaptionProcessor(input_path=video, model_size="base", src_lang="en",
                                     target_lang=None, device="cpu", progress_reporter=stages.append)
    output = processor.process()
    subs = assert_subtitles(video.with_suffix(".ass"), record["text"],
                            float(metadata["format"]["duration"]))
    rendered = probe_media(output)
    assert {s["codec_type"] for s in rendered["streams"]} == {"video", "audio"}
    assert abs(float(rendered["format"]["duration"]) - float(metadata["format"]["duration"])) <= .08
    audio_hashes = [run_media(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0",
                              "-c", "copy", "-f", "hash", "-hash", "sha256", "-"]).stdout.strip()
                    for path in (video, output)]
    assert audio_hashes[0].startswith("SHA256=") and audio_hashes[0] == audio_hashes[1]
    assert stages == ["MODEL_LOADING", "AUDIO_EXTRACTING", "TRANSCRIBING", "ASS_GENERATING",
                      "VIDEO_RENDERING", "COMPLETE"]
    midpoint = (subs[0].start + subs[0].end) / 2000
    before = capture_frame(video, midpoint, tmp_path / "before.png")
    after = capture_frame(output, midpoint, tmp_path / "captioned.png")
    with Image.open(before) as a, Image.open(after) as b:
        difference = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
        box = difference.getbbox()
        assert box and box[1] > b.height / 2, "未在画面下方发现实际烧录的字幕"
    save_media_evidence("auto-caption", [video, output, video.with_suffix(".ass"), before, after],
                        {"model": "base", "source_text": record["text"], "stages": stages,
                         "source_audio_sha256": record["sha256"], "subtitle_bbox": box,
                         "audio_packet_hash": audio_hashes[0],
                         "streams": rendered["streams"]})
