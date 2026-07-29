"""MiniMax 配音适配器的缓存与实际字幕时间轴测试。"""

import json
from pathlib import Path

from video_processing.dubbing.minimax_client import MiniMaxTTSClient


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def test_synthesis_caches_audio_and_downloaded_actual_subtitles(tmp_path: Path):
    calls = []

    def urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        if request.full_url.startswith("https://api.minimaxi.com"):
            return _Response({
                "base_resp": {"status_code": 0},
                "data": {"audio": "52494646", "subtitle_file": "https://subtitle.example/test"},
                "extra_info": {"usage_characters": 4},
            })
        return _Response([{"text": "你好", "time_begin": 0, "time_end": 600}])

    client = MiniMaxTTSClient(api_key="test-key", model="speech-2.8-turbo", voice_id="voice", urlopen=urlopen)
    first = client.synthesize("你好", speed=1.08, cache_dir=tmp_path)
    second = client.synthesize("你好", speed=1.08, cache_dir=tmp_path)

    assert first.audio_path.read_bytes() == bytes.fromhex("52494646")
    assert first.subtitles[0]["time_end"] == 600
    assert first.cache_key == second.cache_key
    assert len(calls) == 2
