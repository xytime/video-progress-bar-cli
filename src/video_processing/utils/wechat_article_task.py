"""共享任务文章契约：冻结一次，上传器只消费冻结快照。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-12 | Antigravity | 完善任务契约审计字段：增加配置版本、SHA-256 摘要与强制挂接标识 (require_article)。 |
| 1.0.0 | 2026-10-12 | Codex | 初始实现：文章任务决策冻结、读取与 CLI 参数生成。 |
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from video_processing.core.wechat_article_policy import is_valid_mp_article_url
from video_processing.utils.wechat_product_config import atomic_json

PUBLISHER_CAPABILITY = "wechat-article-task-v1"


def load_article_policy(policy_path: Path) -> dict:
    """加载公众号文章配置文件并返回配置内容及摘要。"""
    path = Path(policy_path)
    if not path.exists():
        return {"version": "1.0.0", "digest": "MISSING", "articles": {}}
    try:
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        data = json.loads(content.decode("utf-8"))
        data["digest"] = digest
        data.setdefault("version", "1.0.0")
        return data
    except Exception:
        return {"version": "1.0.0", "digest": "CORRUPT", "articles": {}}


def get_article_for_video(video_id: str, policy_path: Path) -> dict | None:
    """按视频 ID 或前缀查找对应的公众号文章目标。"""
    config = load_article_policy(policy_path)
    articles = config.get("articles", {})
    if not isinstance(articles, dict):
        return None
    # 优先精确匹配，再尝试匹配不带切片序号的前缀
    entry = articles.get(video_id)
    if not entry and "_s" in video_id:
        parent_id = video_id.split("_s")[0]
        entry = articles.get(parent_id)
    if not isinstance(entry, dict):
        return None
    url = entry.get("url")
    if not is_valid_mp_article_url(url):
        return None
    return {
        "url": url.strip(),
        "title": str(entry.get("title") or "").strip(),
        "require_article": bool(entry.get("require_article", False)),
        "config_version": str(config.get("version", "1.0.0")),
        "config_digest": str(config.get("digest", "")),
    }


def freeze_task_article_decision(
    task_id: str,
    article_info: dict | None,
    *,
    policy_path: Path | None = None,
) -> dict | None:
    """将单次任务的文章挂接决策冻结为快照字典。"""
    if not article_info:
        return None
    url = article_info.get("url")
    if not is_valid_mp_article_url(url):
        return None

    config_version = article_info.get("config_version", "1.0.0")
    config_digest = article_info.get("config_digest", "")
    if policy_path is not None and not config_digest:
        policy = load_article_policy(policy_path)
        config_version = policy.get("version", "1.0.0")
        config_digest = policy.get("digest", "")

    return {
        "task_id": task_id,
        "url": url.strip(),
        "title": str(article_info.get("title") or "").strip(),
        "require_article": bool(article_info.get("require_article", False)),
        "config_version": str(config_version),
        "config_digest": str(config_digest),
        "publisher_capability": PUBLISHER_CAPABILITY,
    }


def write_article_task_arguments(decision: dict, evidence_dir: Path) -> list[str]:
    """将文章决策写入任务证据目录并返回上传器命令行参数。"""
    target_dir = Path(evidence_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    decision_path = target_dir / "article_task_decision.json"
    atomic_json(decision_path, decision)
    return ["--article-task-decision", str(decision_path)]


def read_article_task_decision(path: Path) -> dict:
    """读取并验证文章决策 JSON。"""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("文章任务契约必须是 JSON 对象")
    if payload.get("publisher_capability") != PUBLISHER_CAPABILITY:
        raise ValueError(f"未知文章任务能力: {payload.get('publisher_capability')}")
    url = payload.get("url")
    if not is_valid_mp_article_url(url):
        raise ValueError(f"文章任务包含非法 URL: {url!r}")
    return payload

