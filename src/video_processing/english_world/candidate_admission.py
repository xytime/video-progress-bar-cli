"""日更默认片段的资格索引；决定仍来自原始审校账本。

只优化自动选题，不给显式选片授权，也不替代下载后的精确输入准入。
索引不缓存 PASS/FAIL，不清零预算，不把模型故障归入内容黑名单。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-20 | Codex | 自动选题前回读默认片段预算，保留原账本与具名片段准入。 |
"""
from pathlib import Path
import re

from ..study_cards.language_protocol import task_identity
from ..study_cards.language_qa import atomic_json, read_json
from ..study_cards.language_review_service import locked, new_draft_admission


MAX_PREFLIGHT_CANDIDATES = 10
YOUTUBE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
INDEX_VERSION = "english-world-default-window-v1"
_IDENTITY_FIELDS = ("source_sha256", "caption_sha256", "source_start", "source_end")


def remember_default_task(language_root: Path, *, youtube_id: str, evidence: dict) -> None:
    """只存已观察到的输入身份；一个来源的最新默认片段对应一个索引文件。"""
    if not YOUTUBE_ID_PATTERN.fullmatch(youtube_id):
        raise ValueError("默认片段索引缺少合法 YouTube ID")
    binding = {field: evidence[field] for field in _IDENTITY_FIELDS}
    key = task_identity(binding)
    path = language_root / "candidate_admissions" / f"{youtube_id}.json"
    with locked(path.with_suffix(".lock")):
        atomic_json(path, {
            "version": INDEX_VERSION, "youtube_id": youtube_id,
            "task_identity": key, "binding": binding,
        })


def blocked_default_sources(language_root: Path) -> dict[str, dict]:
    """每轮回读原预算；索引损坏停止选题，账本不存在则按新任务处理。"""
    blocked = {}
    for path in sorted((language_root / "candidate_admissions").glob("*.json")):
        record = read_json(path)
        video_id = record.get("youtube_id")
        if (record.get("version") != INDEX_VERSION or not isinstance(video_id, str)
                or not YOUTUBE_ID_PATTERN.fullmatch(video_id) or path.stem != video_id
                or task_identity(record["binding"]) != record.get("task_identity")):
            raise ValueError("默认片段资格索引无效")
        key = record["task_identity"]
        admission = new_draft_admission(
            task_dir=language_root / "tasks" / key, cache_dir=language_root / "cache")
        if admission["state"] != "READY":
            blocked[video_id] = {**admission, "task_identity": key}
    return blocked
