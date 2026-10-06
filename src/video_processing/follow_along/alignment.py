"""已知原文对齐端口；外部模型环境返回原始证据，不替换作者歌词。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-07 | Codex | 完整词 ID 校验、手工修訂导入与隔离 provider 协议 |
"""
from copy import deepcopy
from pathlib import Path
from typing import Protocol
import json
import subprocess

from .contracts import PipelineError, verify_ref


class StemSeparator(Protocol):
    def separate(self, audio: Path, directory: Path) -> dict: ...


class ForcedAligner(Protocol):
    def align(self, audio: Path, words: list[dict], windows: list[dict], directory: Path) -> dict: ...


class ExternalProvider:
    """显式 argv 的隔离模型进程；固定 input/output JSON 文件协议，无 shell。"""
    def __init__(self, argv: list[str], revision: str, weights_sha256: str, timeout=600):
        if not argv or not Path(argv[0]).is_absolute() or len(weights_sha256) != 64:
            raise PipelineError("INPUT_INVALID", "provider 需要绝对可执行路径和冻结权重哈希")
        self.argv, self.revision, self.weights_sha256, self.timeout = argv, revision, weights_sha256, timeout

    def execute(self, request: dict, directory: Path, pass_fds=()):
        request_path, response_path = directory / "request.json", directory / "response.json"
        request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2))
        with (directory / "provider.log").open("wb") as log:
            try:
                subprocess.run([*self.argv, "--request", str(request_path), "--response", str(response_path)],
                                        stdout=log, stderr=subprocess.STDOUT, timeout=self.timeout, check=True, pass_fds=pass_fds)
            except FileNotFoundError as exc:
                raise PipelineError("DEPENDENCY_UNAVAILABLE", "隔离 provider 不存在") from exc
            except subprocess.TimeoutExpired as exc:
                raise PipelineError("RESOURCE_TIMEOUT", "模型执行超时") from exc
            except subprocess.CalledProcessError as exc:
                raise PipelineError("MODEL_INCOMPATIBLE", f"provider exit={exc.returncode}，见 provider.log") from exc
        try:
            response = json.loads(response_path.read_text())
        except (OSError, ValueError) as exc:
            raise PipelineError("MODEL_INCOMPATIBLE", "provider 缺少有效响应") from exc
        if (response.get("revision") != self.revision or response.get("weights_sha256") != self.weights_sha256
                or not response.get("actual_device")):
            raise PipelineError("MODEL_INCOMPATIBLE", "provider 版本/权重/实际设备证据不匹配")
        return response

    def align(self, audio, words, windows, directory):
        return self.execute({"operation": "align", "audio": str(audio), "words": words, "windows": windows,
                             "revision": self.revision, "weights_sha256": self.weights_sha256}, directory)

    def separate(self, audio, directory):
        return self.execute({"operation": "separate", "audio": str(audio), "revision": self.revision,
                             "weights_sha256": self.weights_sha256}, directory)


def apply_word_results(source, response, evidence_ref):
    plan = deepcopy(source)
    expected = [w["id"] for c in plan["cues"] for w in c["words"]]
    actual = [w["id"] for w in response["words"]]
    if actual != expected:
        raise PipelineError("ALIGNMENT_INCOMPLETE", "provider 丢词、重复词或改词序", sorted(set(expected) ^ set(actual)))
    results = {w["id"]: w for w in response["words"]}
    incomplete = []
    for cue in plan["cues"]:
        for word in cue["words"]:
            value = results[word["id"]]
            if value.get("text") != word["text"]:
                raise PipelineError("ALIGNMENT_INCOMPLETE", "provider 改写原文", [word["id"]])
            word["interval"] = value.get("interval")
            word["timing_status"] = value.get("timing_status", "unaligned")
            word["alignment_score"] = value.get("alignment_score")
            word["evidence_ref"] = evidence_ref
            if word["timing_status"] not in {"manual", "observed"} or not word["interval"]:
                incomplete.append(word["id"])
        if all(w["interval"] for w in cue["words"]):
            cue["interval"] = {"start_tick": cue["words"][0]["interval"]["start_tick"],
                               "end_tick": cue["words"][-1]["interval"]["end_tick"]}
    plan["phase"] = "aligned"
    if incomplete:
        raise PipelineError("ALIGNMENT_INCOMPLETE", "缺词或估算词界需要人工修订", incomplete)
    return plan


def accept_supplied_alignment(plan, root):
    """首版可用已观测/手工词界；必须携带本地哈希证据。"""
    for cue in plan["cues"]:
        for word in cue["words"]:
            if word["timing_status"] not in {"manual", "observed"} or not word["interval"] or not word["evidence_ref"]:
                raise PipelineError("ALIGNMENT_INCOMPLETE", "缺少可信词界或证据；配置隔离 aligner 或导入人工修订", [word["id"]])
            verify_ref(root, word["evidence_ref"])
    accepted = deepcopy(plan)
    for cue in accepted["cues"]:
        if cue["interval"] is None:
            cue["interval"] = {"start_tick":cue["words"][0]["interval"]["start_tick"], "end_tick":cue["words"][-1]["interval"]["end_tick"]}
    return accepted
