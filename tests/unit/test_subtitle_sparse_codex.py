"""真实预算回调下 Codex 有效修复与稀疏候选交接的集成回归。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-27 | Codex | 有差异提示、未接受候选持久恢复、全片容错与结构硬拒。 |
"""

import copy
import json

import pytest

from video_processing.utils import codex_subtitle_provider as provider
from video_processing.utils.codex_text_provider import CodexTextResult
from video_processing.utils.subtitle_sparse_policy import build_sparse_quality_report


def _data(prompt):
    return json.loads(prompt.split("源字幕 JSON: ", 1)[1].split("\n宿主拒绝", 1)[0])


def _video(count=20):
    segments = [{"text": "The outlook is stable.", "start": index * 2, "end": index * 2 + 2}
                for index in range(count)]
    segments[0]["text"] = "Oil is $115 per barrel."
    return segments


class _StructuredTransport:
    """只替换进程/网络边界；执行前回调、宿主验证和干净缓存时序保持真实。"""

    def __init__(self, generate):
        self.generate = generate
        self.prompts = []
        self.cache = {}
        self.cache_hits = 0

    def __call__(self, prompt, **kwargs):
        key = (kwargs["cache_prompt"], kwargs["cache_contract"])
        if key in self.cache:
            try:
                payload = kwargs["validate"](copy.deepcopy(self.cache[key]))
            except provider.CodexTextError as error:
                del self.cache[key]
                prompt = kwargs["repair_cached_output"](prompt, error)
            else:
                self.cache_hits += 1
                return CodexTextResult(payload, "gpt-5.6-luna", {}, 0, True)
        if kwargs["before_execute"] is not None:
            kwargs["before_execute"]()
        self.prompts.append(prompt)
        raw = self.generate(_data(prompt), len(self.prompts))
        payload = kwargs["validate"](copy.deepcopy(raw))
        self.cache[key] = raw
        return CodexTextResult(payload, "gpt-5.6-luna", {}, 1)


def _rows(data, wrong=True):
    return {"items": [{"id": row["id"], "translation": (
        "油价每桶1150亿美元。" if wrong else "油价每桶115美元。")
        if row["id"] == 0 else "前景保持稳定。", "vocab": []} for row in data]}


def _build(segments, state_dir, **kwargs):
    return provider.build_codex_subtitle_candidate(
        [segment["text"] for segment in segments], "WRONG_SUMMARY_CONTEXT: $115B fund",
        state_dir=state_dir, command="codex", allow_quality_candidate=True, **kwargs,
    )


def test_quality_repair_changes_prompt_and_removes_wrong_full_context(tmp_path, monkeypatch):
    segments = _video(1)
    transport = _StructuredTransport(lambda data, number: _rows(data, wrong=number == 1))
    monkeypatch.setattr(provider, "run_codex_structured", transport)
    candidate = _build(segments, tmp_path)
    assert len(transport.prompts) == 2
    assert "WRONG_SUMMARY_CONTEXT" in transport.prompts[0]
    assert "WRONG_SUMMARY_CONTEXT" not in transport.prompts[1]
    assert transport.prompts[0] != transport.prompts[1]
    assert '"segment_number": 1' in transport.prompts[1]
    assert '"source_signal": "$115"' in transport.prompts[1]
    assert candidate.translations == ["油价每桶115美元。"]
    assert any(entry["strategy"] == "targeted_singleton" and entry["executed"]
               for entry in candidate.repair_history)


def test_sparse_remaining_fact_error_is_complete_but_requires_whole_video_policy(tmp_path, monkeypatch):
    segments = _video()
    transport = _StructuredTransport(lambda data, number: _rows(data))
    monkeypatch.setattr(provider, "run_codex_structured", transport)
    candidate = _build(segments, tmp_path)
    assert len(candidate.translations) == len(segments) == 20
    assert candidate.contract_error_for(20) is None
    report = build_sparse_quality_report(segments, candidate.translations,
                                         repair_history=candidate.repair_history)
    assert report["status"] == "accepted_with_warnings"
    assert report["affected_segments"] == [1]
    assert report["segment_ratio"] == report["duration_ratio"] == 0.05
    assert any(issue["severity"] == "P0" for issue in report["issues"])
    # 拒绝正文从未进干净缓存，只在带单独身份的待全片复核计划中存在。
    assert all(not any(row["id"] == 0 for row in raw["items"]) for raw in transport.cache.values())
    state = json.loads(next((tmp_path / "subtitle-recovery").glob("*.json")).read_text())
    assert state["units"]["0"]["attempts_used"] == 2
    assert state["units"]["0"]["accepted"] is False
    assert state["units"]["0"]["rejected_candidate"]


def test_restart_reuses_pending_without_resetting_or_executing_more_requests(tmp_path, monkeypatch):
    segments = _video()
    transport = _StructuredTransport(lambda data, number: _rows(data))
    monkeypatch.setattr(provider, "run_codex_structured", transport)
    first = _build(segments, tmp_path)
    count = len(transport.prompts)
    state_path = next((tmp_path / "subtitle-recovery").glob("*.json"))
    first_state = json.loads(state_path.read_text())
    second = _build(segments, tmp_path)
    second_state = json.loads(state_path.read_text())
    assert first.translations == second.translations
    assert len(transport.prompts) == count
    assert first_state["requests_used"] == second_state["requests_used"]
    assert second_state["units"]["0"]["attempts_used"] == 2
    assert build_sparse_quality_report(segments, second.translations,
                                       repair_history=second.repair_history)["status"] == "accepted_with_warnings"


def test_one_remaining_fact_error_in_short_video_still_exceeds_tolerance(tmp_path, monkeypatch):
    segments = _video(1)
    transport = _StructuredTransport(lambda data, number: _rows(data))
    monkeypatch.setattr(provider, "run_codex_structured", transport)
    candidate = _build(segments, tmp_path)
    assert len(transport.prompts) == 2
    report = build_sparse_quality_report(segments, candidate.translations,
                                         repair_history=candidate.repair_history)
    assert report["status"] == "needs_repair"
    assert "affected_segment_ratio_exceeded" in report["reasons"]


@pytest.mark.parametrize("malform", ["missing", "duplicate", "empty", "placeholder"])
def test_structure_errors_never_become_complete_quality_candidates(tmp_path, monkeypatch, malform):
    segments = _video(2)

    def generate(data, number):
        raw = _rows(data, wrong=False)
        if malform == "missing":
            raw["items"] = []
        elif malform == "duplicate":
            raw["items"][0]["id"] = 99
        elif malform == "empty":
            raw["items"][0]["translation"] = ""
        else:
            raw["items"][0]["translation"] = "承接上文"
        return raw

    transport = _StructuredTransport(generate)
    monkeypatch.setattr(provider, "run_codex_structured", transport)
    with pytest.raises(provider.CodexTextError, match="subtitle_"):
        _build(segments, tmp_path)
    assert not transport.cache


def test_successful_targeted_repair_has_clean_cache_and_restart_reuses_it(tmp_path, monkeypatch):
    segments = _video()
    zero_singletons = [0]

    def generate(data, number):
        if len(data) == 1 and data[0]["id"] == 0:
            zero_singletons[0] += 1
        return _rows(data, wrong=zero_singletons[0] < 2)

    transport = _StructuredTransport(generate)
    monkeypatch.setattr(provider, "run_codex_structured", transport)
    candidate = _build(segments, tmp_path)
    assert build_sparse_quality_report(segments, candidate.translations,
                                       repair_history=candidate.repair_history)["status"] == "clean"
    count = len(transport.prompts)
    second = _build(segments, tmp_path)
    assert second.translations == candidate.translations
    assert len(transport.prompts) == count
    assert transport.cache_hits > 0
    state = json.loads(next((tmp_path / "subtitle-recovery").glob("*.json")).read_text())
    assert state["units"]["0"]["accepted"] is True
    assert "rejected_candidate" not in state["units"]["0"]


@pytest.mark.parametrize("abort_code", ["request_budget_exhausted", "network_error"])
def test_first_singleton_translation_after_parent_structure_error_is_not_fact_repair(tmp_path, monkeypatch, abort_code):
    segments = _video()

    def generate(data, number):
        raw = _rows(data)
        if len(data) == 5 and data[0]["id"] == 0:
            # 父请求只有结构问题；它从未提供可用于定位金额错误的译文。
            raw["items"][0]["id"] = 99
        return raw

    transport = _StructuredTransport(generate)
    stopped = []

    def before_admission(prompt, **kwargs):
        data = _data(prompt)
        previous = sum(len(_data(item)) == 1 and _data(item)[0]["id"] == 0
                       for item in transport.prompts)
        if len(data) == 1 and data[0]["id"] == 0 and previous:
            # 第二次真正修复尚未获执行许可，不能消费callback或伪造executed证据。
            stopped.append(abort_code)
            raise provider.CodexTextError(abort_code)
        return transport(prompt, **kwargs)

    monkeypatch.setattr(provider, "run_codex_structured", before_admission)
    try:
        candidate = _build(segments, tmp_path)
    except provider.CodexTextError as error:
        assert error.code == abort_code
    else:
        assert candidate.contract_error_for(len(segments)) is None
        report = build_sparse_quality_report(segments, candidate.translations,
                                             repair_history=candidate.repair_history)
        assert report["status"] == "needs_repair"
        assert "effective_repair_required" in report["reasons"]
    assert stopped == [abort_code]
    assert sum(len(_data(item)) == 1 and _data(item)[0]["id"] == 0
               for item in transport.prompts) == 1
    state = json.loads(next((tmp_path/"subtitle-recovery").glob("*.json")).read_text())
    assert state["requests_used"] == 2
    assert not any(entry.get("executed") is True and 1 in entry.get("segment_numbers", [])
                   for entry in state["units"]["0"].get("repair_history", []))


def test_restart_keeps_parent_quality_observation_before_any_child_executes(tmp_path, monkeypatch):
    segments = _video()

    class BeforeChildCrash(BaseException):
        pass

    def generate(data, number):
        return _rows(data, wrong=len(data) > 1 and data[0]["id"] == 0)

    transport = _StructuredTransport(generate)
    armed = [True]

    def interrupted_transport(prompt, **kwargs):
        if len(_data(prompt)) == 1 and armed[0]:
            armed[0] = False
            raise BeforeChildCrash()
        return transport(prompt, **kwargs)

    monkeypatch.setattr(provider, "run_codex_structured", interrupted_transport)
    with pytest.raises(BeforeChildCrash):
        _build(segments, tmp_path)
    state = json.loads(next((tmp_path/"subtitle-recovery").glob("*.json")).read_text())
    assert state["requests_used"] == 1
    assert len(transport.prompts) == 1 and len(_data(transport.prompts[0])) == 5

    candidate = _build(segments, tmp_path)

    assert candidate.contract_error_for(len(segments)) is None
    assert candidate.translations[0] == "油价每桶115美元。"
    assert build_sparse_quality_report(segments, candidate.translations,
                                       repair_history=candidate.repair_history)["status"] == "clean"
    parent_observations = [entry for entry in candidate.repair_history
                           if entry.get("strategy") == "quality_observation"
                           and entry.get("segment_numbers") == [1, 2, 3, 4, 5]]
    assert parent_observations
    assert any(entry.get("translations") == ["油价每桶1150亿美元。", *(["前景保持稳定。"]*4)]
               and any(detail.get("code") == "NUMBER_MAGNITUDE_MISMATCH"
                       and detail.get("segment_number") == 1 for detail in entry.get("details", []))
               for entry in parent_observations)
    assert sum(len(_data(item)) == 5 and _data(item)[0]["id"] == 0
               for item in transport.prompts) == 1


def test_command_start_failure_after_admission_is_not_a_validated_repair(tmp_path, monkeypatch):
    segments = _video()
    transport = _StructuredTransport(lambda data, number: _rows(data))
    admitted_without_result = []

    def command_unavailable(prompt, **kwargs):
        data = _data(prompt)
        if data[0]["id"] == 0 and transport.prompts:
            # 预算已预扣，但 Popen 尚未成功；该次没有可交宿主验证的模型候选。
            kwargs["before_execute"]()
            admitted_without_result.append(prompt)
            raise provider.CodexTextError("command_unavailable")
        return transport(prompt, **kwargs)

    monkeypatch.setattr(provider, "run_codex_structured", command_unavailable)
    try:
        candidate = _build(segments, tmp_path, batch_size=1)
    except provider.CodexTextError as error:
        assert error.code == "command_unavailable"
    else:
        assert candidate.contract_error_for(len(segments)) is None
        report = build_sparse_quality_report(segments, candidate.translations,
                                             repair_history=candidate.repair_history)
        assert report["status"] == "needs_repair"
        assert "effective_repair_required" in report["reasons"]
    assert len(admitted_without_result) == 1 and len(transport.prompts) == 1
    state = json.loads(next((tmp_path/"subtitle-recovery").glob("*.json")).read_text())
    assert state["requests_used"] == state["units"]["0"]["attempts_used"] == 2
    history = state["units"]["0"].get("repair_history", [])
    assert any(entry.get("phase") == "started" and entry.get("executed") is False for entry in history)
    assert not any(entry.get("executed") is True for entry in history)
