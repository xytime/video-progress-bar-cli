"""互动策略的只读种子与受限学习存储。

审阅过的策略只从仓库 ``data/comment_strategies.json`` 读取。运行期学习
只能写入独立的 ``output/wechat_interaction/strategies.json``，且只保存已经
发表的具体样本，不能把一次事件的措辞提升为跨主题模板。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-09-19 | Codex | 分离只读种子与运行学习，锁定完整读改写事务并拒绝损坏覆盖 |
| 1.1.0 | 2026-09-19 | Antigravity | 加固安全：引入 fcntl 文件锁、原子写盘、槽位抽象强校验与学习前审查门禁 |
| 1.0.0 | 2026-09-19 | Antigravity | 初始创建：实现自生长沉淀、经验滑动窗口与模板检索 |
"""

from __future__ import annotations

import copy
import fcntl
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .contract import InteractionDraft, InteractionType

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SEED_FILE = PROJECT_ROOT / "data" / "comment_strategies.json"
DEFAULT_STRATEGY_FILE = PROJECT_ROOT / "output" / "wechat_interaction" / "strategies.json"
MAX_TEMPLATES_PER_CATEGORY = 20
MAX_LEARNED_EXEMPLARS = 30


class StrategyStore:
    """提供审阅模板，并将成功样本受限地保存到独立运行存储。"""

    def __init__(
        self,
        storage_path: Path | str = DEFAULT_STRATEGY_FILE,
        *,
        seed_path: Path | str = DEFAULT_SEED_FILE,
    ) -> None:
        self.path = Path(storage_path)
        self.seed_path = Path(seed_path)
        if self.path.resolve() == self.seed_path.resolve():
            raise ValueError("策略种子文件是只读的，storage_path 必须指向独立运行目录")
        self.lock_path = self.path.with_suffix(f"{self.path.suffix}.lock")
        self._data: Dict[str, Any] = {}
        self._runtime_corrupt = False
        self.load()

    def load(self) -> None:
        """只读加载运行存储；缺失时仅在内存中使用种子，绝不初始化文件。"""
        seed = self._load_seed()
        self._runtime_corrupt = False
        if not self.path.exists():
            self._data = seed
            return
        try:
            runtime = self._read_runtime_validated()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            # 损坏文件是审计证据，绝不能以“新初始值”覆盖掉它。
            self._runtime_corrupt = True
            self._data = seed
            logger.error("策略运行存储不可用，拒绝覆盖 %s: %s", self.path, exc)
            return
        self._data = runtime

    def learn_from_success(self, draft: InteractionDraft, video_title: str) -> bool:
        """记录已发表且审查通过的具体样本，不自动提升为通用策略。"""
        if not self._passes_learning_censorship(draft):
            return False

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                # 锁内重新读取，不能用构造期快照覆盖其它进程的学习结果。
                data = self._load_runtime_for_update()
                if data is None:
                    return False
                category = draft.category.strip() or "General"
                exemplars = data.setdefault("learned_exemplars", [])
                exemplars.append(
                    {
                        "title": video_title.strip(),
                        "category": category,
                        "type": draft.interaction_type.value,
                        "comment": draft.formatted_comment,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
                data["learned_exemplars"] = exemplars[-MAX_LEARNED_EXEMPLARS:]
                data["updated_at"] = datetime.now(timezone.utc).isoformat()
                self._atomic_write(data)
                self._data = data
                self._runtime_corrupt = False
                return True
            except OSError as exc:
                logger.error("策略学习写入失败 %s: %s", self.path, exc)
                return False
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def get_templates(
        self,
        category: str = "General",
        interaction_type: Optional[InteractionType] = None,
    ) -> List[Dict[str, Any]]:
        """仅返回经种子/运行结构校验的审阅模板，不从 exemplars 推断模板。"""
        categories = self._data.get("categories", {})
        candidates = categories.get(category) or categories.get("General") or []
        if interaction_type is not None:
            return [
                copy.deepcopy(item)
                for item in candidates
                if item.get("interaction_type") == interaction_type.value
            ]
        return copy.deepcopy(candidates)

    def _load_runtime_for_update(self) -> Optional[Dict[str, Any]]:
        if not self.path.exists():
            return self._load_seed()
        try:
            return self._read_runtime_validated()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._runtime_corrupt = True
            logger.error("策略运行存储损坏，拒绝覆盖 %s: %s", self.path, exc)
            return None

    def _load_seed(self) -> Dict[str, Any]:
        try:
            return self._read_validated(self.seed_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            # 极端情况下保持一个受限的内存兜底；仍然不写入仓库文件。
            logger.error("策略种子不可用，使用内存通用模板: %s", exc)
            return self._memory_seed()

    def _read_runtime_validated(self) -> Dict[str, Any]:
        """运行文件可带样本，但不能自带或篡改可复用模板。"""
        runtime = self._read_validated(self.path)
        seed = self._load_seed()
        if runtime.get("categories") != seed.get("categories"):
            raise ValueError("运行存储包含未审阅或已变更的策略模板")
        return runtime

    @staticmethod
    def _read_validated(path: Path) -> Dict[str, Any]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        StrategyStore._validate_data(raw)
        return raw

    @staticmethod
    def _validate_data(data: Any) -> None:
        if not isinstance(data, dict) or not isinstance(data.get("categories"), dict):
            raise ValueError("策略文件缺少 categories 对象")
        exemplars = data.get("learned_exemplars", [])
        if not isinstance(exemplars, list):
            raise ValueError("策略文件 learned_exemplars 必须为列表")
        if len(exemplars) > MAX_LEARNED_EXEMPLARS:
            raise ValueError("学习样本超过保留上限")
        if not all(isinstance(item, dict) for item in exemplars):
            raise ValueError("学习样本必须为对象")
        for category, templates in data["categories"].items():
            if not isinstance(category, str) or not isinstance(templates, list):
                raise ValueError("策略类目必须是字符串到列表的映射")
            if len(templates) > MAX_TEMPLATES_PER_CATEGORY:
                raise ValueError("单类策略模板超过上限")
            for item in templates:
                if not isinstance(item, dict):
                    raise ValueError("策略模板必须是对象")
                if item.get("interaction_type") not in {kind.value for kind in InteractionType}:
                    raise ValueError("策略模板互动类型无效")
                if not isinstance(item.get("topic_template"), str) or "{core_subject}" not in item["topic_template"]:
                    raise ValueError("策略模板必须含 {core_subject} 槽位")
                options = item.get("poll_options")
                if not isinstance(options, list) or not 2 <= len(options) <= 4 or not all(
                    isinstance(option, str) and option.strip() for option in options
                ):
                    raise ValueError("策略模板选项必须为 2-4 个非空字符串")
                if not isinstance(item.get("share_hook"), str) or not item["share_hook"].strip():
                    raise ValueError("策略模板缺少转发引导")

    def _atomic_write(self, data: Dict[str, Any]) -> None:
        """在同目录创建、fsync 并替换文件；调用者必须已持有锁。"""
        payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        fd, temp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
                temp_file.write(payload)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, self.path)
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _passes_learning_censorship(draft: InteractionDraft) -> bool:
        try:
            from video_processing.censor_engine import check_channel_policy, check_text

            results = (
                check_text(zh_text=draft.formatted_comment),
                check_channel_policy(zh_text=draft.formatted_comment),
                check_text(zh_text=draft.topic),
                check_channel_policy(zh_text=draft.topic),
            )
            return not any(result.hit for result in results)
        except Exception as exc:
            logger.warning("学习前审查异常，拒绝沉淀: %s", exc)
            return False

    @staticmethod
    def _memory_seed() -> Dict[str, Any]:
        """种子文件缺失时的最小通用策略；仅在内存使用。"""
        templates = []
        rows = (
            (InteractionType.POLL_STAND, "针对视频中关于{core_subject}的核心争议，你怎么看？", ["认同视频观点", "持保留意见"], "💬 评论区留下你的选择，转给好友一起讨论！"),
            (InteractionType.WARNING_SHARE, "视频中关于{core_subject}的风险提醒，值得多留意。", ["已注意防范", "刚了解到"], "⚠️ 转给可能需要这条提醒的朋友。"),
            (InteractionType.GROUP_DISCUSSION, "关于{core_subject}的最新讨论，你更认同哪种看法？", ["支持这一方向", "继续观察"], "💬 转到讨论群，听听大家的观点。"),
            (InteractionType.MEMO_COLLECTION, "关于{core_subject}的知识要点，哪些最值得记下？", ["已抓住重点", "先收藏复盘"], "📦 收藏或转发，方便之后复盘。"),
            (InteractionType.VOICE_RESONANCE, "关于{core_subject}，这段分享带来了哪些启发？", ["很有共鸣", "提供了新角度"], "🔥 转给同样关注这个话题的朋友。"),
        )
        for index, (kind, topic, options, hook) in enumerate(rows):
            templates.append({"id": f"memory_{index}", "interaction_type": kind.value, "topic_template": topic, "poll_options": options, "share_hook": hook, "weight": 1.0, "learned_count": 0})
        return {"version": "1.0.0", "updated_at": None, "categories": {"General": templates}, "learned_exemplars": []}
