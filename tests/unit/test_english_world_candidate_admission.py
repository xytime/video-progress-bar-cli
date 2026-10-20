"""默认片段索引只读原预算；跨运行避让不等于来源黑名单或恢复授权。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-20 | Codex | 覆盖预算回读、片段隔离、损坏停止与原账本不变。 |
"""
import pytest

from video_processing.english_world.candidate_admission import (
    blocked_default_sources, remember_default_task,
)
from video_processing.study_cards.language_protocol import task_identity
from video_processing.study_cards.language_qa import atomic_json


def _evidence(**changes):
    return {"source_sha256": "s" * 64, "caption_sha256": "c" * 64,
            "source_start": 0, "source_end": 40, **changes}


@pytest.mark.parametrize("ledger,reason", [
    ({"attempts": 2, "keys": [], "content_terminal": True}, "REVIEW_TERMINAL"),
    ({"attempts": 3, "keys": []}, "ATTEMPT_BUDGET_EXHAUSTED"),
    ({"attempts": 1, "keys": [], "inflight": True}, "REVIEW_INFLIGHT"),
])
def test_next_run_checks_authoritative_budget_without_mutating_it(tmp_path, ledger, reason):
    evidence = _evidence()
    remember_default_task(tmp_path, youtube_id="8H0dTo_9CFU", evidence=evidence)
    path = tmp_path / "tasks" / task_identity(evidence) / "language_attempts.json"
    atomic_json(path, ledger)
    before = path.read_bytes()
    assert blocked_default_sources(tmp_path)["8H0dTo_9CFU"]["reason"] == reason
    assert path.read_bytes() == before
    # 索引不能缓存 BLOCKED，原账本资格发生变化后必须立即反映。
    atomic_json(path, {"attempts": 1, "keys": []})
    assert blocked_default_sources(tmp_path) == {}


def test_new_task_and_updated_default_input_do_not_inherit_other_segment_budget(tmp_path):
    evidence = _evidence()
    remember_default_task(tmp_path, youtube_id="8H0dTo_9CFU", evidence=evidence)
    assert blocked_default_sources(tmp_path) == {}
    atomic_json(tmp_path / "tasks" / task_identity(evidence) / "language_attempts.json",
                {"attempts": 3, "keys": []})
    remember_default_task(tmp_path, youtube_id="8H0dTo_9CFU",
                          evidence=_evidence(source_start=40, source_end=80))
    assert blocked_default_sources(tmp_path) == {}


@pytest.mark.parametrize("corruption", ["index", "ledger"])
def test_corrupt_evidence_stops_instead_of_blacklisting_or_resetting(tmp_path, corruption):
    evidence = _evidence()
    remember_default_task(tmp_path, youtube_id="8H0dTo_9CFU", evidence=evidence)
    path = (tmp_path / "candidate_admissions/8H0dTo_9CFU.json" if corruption == "index" else
            tmp_path / "tasks" / task_identity(evidence) / "language_attempts.json")
    atomic_json(path, {"attempts": "bad"})
    before = path.read_bytes()
    with pytest.raises(ValueError):
        blocked_default_sources(tmp_path)
    assert path.read_bytes() == before
