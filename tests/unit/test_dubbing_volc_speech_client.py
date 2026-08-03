"""火山豆包语音客户端的协议与缓存测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-03 | Codex | 覆盖声音复刻 2.0 请求头、MP3 解码与缓存复用 |
"""

import base64
import json
from pathlib import Path

from video_processing.dubbing.volc_speech_client import VolcSpeechTTSClient


class _Response:
    status_code = 200
    headers = {"X-Tt-Logid": "test-logid"}

    def __init__(self, frames):
        self.text = "".join(json.dumps(frame, ensure_ascii=False) for frame in frames)

    def json(self):
        return {}


def test_synthesis_uses_icl2_headers_and_reuses_cached_mp3(tmp_path: Path):
    calls = []
    audio = base64.b64encode(b"mp3-bytes").decode("ascii")

    def post(url, *, headers, json):
        calls.append({"url": url, "headers": headers, "payload": json})
        return _Response([
            {"code": 352, "data": audio},
            {"code": 20000000, "message": "OK", "usage": {"text_words": 2}},
        ])

    client = VolcSpeechTTSClient(
        api_key="test-key", resource_id="seed-icl-2.0", voice_id="S_divMm4n62",
        sample_rate=24000, post=post,
    )
    first = client.synthesize("音色验收。", speed=1.08, cache_dir=tmp_path)
    second = client.synthesize("音色验收。", speed=1.08, cache_dir=tmp_path)

    assert first.audio_path.read_bytes() == b"mp3-bytes"
    assert first.cache_key == second.cache_key
    assert first.usage_characters == 2
    assert len(calls) == 1
    assert calls[0]["headers"]["X-Api-Resource-Id"] == "seed-icl-2.0"
    assert calls[0]["payload"]["req_params"]["speaker"] == "S_divMm4n62"
    assert calls[0]["payload"]["req_params"]["audio_params"]["speech_rate"] == 8
