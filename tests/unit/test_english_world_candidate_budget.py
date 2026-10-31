"""日更候选扩容必须贯通真实请求写入与宿主读取，禁止只修改提示词。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-14 | Codex | 八个淘汰来源可写入并消费，第九个仍有界拒绝。 |
"""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest
from video_processing.english_world.candidate_admission import MAX_PREFLIGHT_CANDIDATES

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("count", [MAX_PREFLIGHT_CANDIDATES, MAX_PREFLIGHT_CANDIDATES + 1])
def test_candidate_budget_round_trips_through_recorder_and_host(tmp_path, count):
    spec = importlib.util.spec_from_file_location("candidate_budget_runner", ROOT / "scripts/run_english_world_daily.py")
    runner = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runner
    spec.loader.exec_module(runner)
    ids = [f"video{i:06d}" for i in range(count)]
    request = tmp_path / "request.json"
    command = [sys.executable, str(ROOT / "scripts/record_english_world_delivery_request.py"),
               "--request", str(request), "--title", "fixture", "--failure", "no suitable source"]
    for source_id in ids:
        command.extend(["--rejected-youtube-id", source_id])
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if count == MAX_PREFLIGHT_CANDIDATES:
        assert result.returncode == 0, result.stderr
        assert runner._read_delivery_request(request, ROOT)["rejected_youtube_ids"] == ids
    else:
        assert result.returncode != 0 and not request.exists()
        request.write_text(json.dumps({"kind": "failure", "title": "fixture", "failure": "no source",
                                       "rejected_youtube_ids": ids}))
        with pytest.raises(ValueError, match=f"最多 {MAX_PREFLIGHT_CANDIDATES} 项"):
            runner._read_delivery_request(request, ROOT)
