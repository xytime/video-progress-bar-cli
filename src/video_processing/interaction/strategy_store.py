"""自生长策略存储与经验沉淀管理器。

负责维护和演化互动策略库，支持在 AI 接管期间从成功生成中提炼高质量模式，
并在程序化兜底时提供高拟真的模板支持。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-09-19 | Antigravity | 加固安全：引入 fcntl 文件锁、原子写盘、槽位抽象强校验与学习前审查门禁 |
| 1.0.0 | 2026-09-19 | Antigravity | 初始创建：实现自生长沉淀、经验滑动窗口与模板检索 |
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .contract import InteractionDraft, InteractionType

logger = logging.getLogger(__name__)

DEFAULT_STRATEGY_FILE = Path(__file__).resolve().parents[3] / "data" / "comment_strategies.json"
MAX_TEMPLATES_PER_CATEGORY = 20


class StrategyStore:
    """自生长策略知识库管理器。"""

    def __init__(self, storage_path: Path | str = DEFAULT_STRATEGY_FILE) -> None:
        self.path = Path(storage_path)
        self.lock_path = self.path.with_suffix(".lock")
        self._data: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """加载策略库；文件不存在时自动初始化。"""
        if self.path.is_file():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
                return
            except Exception as exc:
                logger.warning("Failed to load strategy file %s: %s; recreating.", self.path, exc)
        self._data = {
            "version": "1.0.0",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "categories": {
                "General": [
                    {
                        "id": "seed_general_poll",
                        "interaction_type": "POLL_STAND",
                        "topic_template": "针对视频中关于{core_subject}的核心争议，你怎么看？",
                        "poll_options": ["认同视频观点，合情合理", "持保留意见，有不同看法"],
                        "share_hook": "💬 你的看法是什么？直接在评论区留下 A 或 B，转给好友一起探讨！",
                        "weight": 1.0,
                        "learned_count": 0,
                    },
                    {
                        "id": "seed_general_warning",
                        "interaction_type": "WARNING_SHARE",
                        "topic_template": "视频中关于{core_subject}的风险警示与核心红线，很多人还在踩坑！",
                        "poll_options": ["已注意防范", "刚了解到及时避险"],
                        "share_hook": "⚠️ 随手转发给身边经常涉及的朋友提个醒，注意防范风险！",
                        "weight": 1.0,
                        "learned_count": 0,
                    },
                    {
                        "id": "seed_general_memo",
                        "interaction_type": "MEMO_COLLECTION",
                        "topic_template": "关于{core_subject}的核心知识与复盘，一次性吸收压力大？",
                        "poll_options": ["已抓住核心", "先收藏慢慢复盘"],
                        "share_hook": "📦 知识点密集建议先转发给‘文件传输助手’或收藏，闲暇时慢慢复盘！",
                        "weight": 1.0,
                        "learned_count": 0,
                    },
                    {
                        "id": "seed_general_discussion",
                        "interaction_type": "GROUP_DISCUSSION",
                        "topic_template": "关于{core_subject}的重大突破与争议，圈内正在热议！",
                        "poll_options": ["支持该方向", "认为纯属炒作"],
                        "share_hook": "💬 转到你的工作群/交流群，测测看同行和朋友们怎么选？",
                        "weight": 1.0,
                        "learned_count": 0,
                    },
                    {
                        "id": "seed_general_voice",
                        "interaction_type": "VOICE_RESONANCE",
                        "topic_template": "关于{core_subject}，他说出了很多人的真实心声与思考。",
                        "poll_options": ["感同身受深有体会", "角度独特很有启发"],
                        "share_hook": "🔥 认同作者观点的点赞集合👍，随手转发给懂你的同频好友！",
                        "weight": 1.0,
                        "learned_count": 0,
                    }
                ]
            },
            "learned_exemplars": [],
        }
        self.save()

    def save(self) -> None:
        """持久化策略库（带进程排他锁与临时文件原子重命名）。"""
        self._data["updated_at"] = datetime.now(timezone.utc).isoformat()
        content = json.dumps(self._data, indent=2, ensure_ascii=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.lock_path, "w") as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            try:
                temp_path = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
                temp_path.write_text(content, encoding="utf-8")
                temp_path.replace(self.path)
            finally:
                try:
                    fcntl.flock(lock_f, fcntl.LOCK_UN)
                except Exception:
                    pass

    def learn_from_success(self, draft: InteractionDraft, video_title: str) -> bool:
        """从已成功发表的互动中提取模式并沉淀自生长库。

        Returns:
            bool: 是否成功完成沉淀
        """
        # 1. 学习前敏感词与策略审查（Fail-Closed 绝不沉淀任何潜在违规内容）
        try:
            from video_processing.censor_engine import check_text, check_channel_policy
            c1 = check_text(zh_text=draft.formatted_comment)
            c2 = check_channel_policy(zh_text=draft.formatted_comment)
            c3 = check_text(zh_text=draft.topic)
            c4 = check_channel_policy(zh_text=draft.topic)
            if c1.hit or c2.hit or c3.hit or c4.hit:
                logger.warning("[StrategyStore] 拒绝沉淀学习：内容命中违禁规则 (c1=%s, c2=%s)", c1.hit, c2.hit)
                return False
        except Exception as exc:
            logger.warning("[StrategyStore] 学习前审查异常 (%s)，fail-closed 拒绝沉淀。", exc)
            return False

        # 2. 重新加载最新存储，避免覆盖其它进程更新
        self.load()

        category = draft.category if draft.category in self._data.get("categories", {}) else "General"
        if category not in self._data["categories"]:
            self._data["categories"][category] = []

        cat_list = self._data["categories"][category]

        # 3. 槽位抽象提炼（必须成功生成带有 {core_subject} 的通用句式）
        topic_pattern = draft.topic
        clean_title = re.sub(r"[#＃\[\]【】\s]+", " ", video_title).strip()
        if clean_title and clean_title in topic_pattern:
            topic_pattern = topic_pattern.replace(clean_title, "{core_subject}")

        # 仅当 topic_pattern 成功包含 {core_subject} 槽位时，才允许进入 categories 通用模版库
        # 绝不允许具体事件（如“白宫拉黑特定媒体”）无槽位污染通用模版
        if "{core_subject}" in topic_pattern:
            new_entry = {
                "id": f"learned_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
                "interaction_type": draft.interaction_type.value,
                "topic_template": topic_pattern,
                "poll_options": draft.poll_options,
                "share_hook": draft.share_hook,
                "formatted_comment_sample": draft.formatted_comment,
                "weight": 1.1,
                "learned_count": 1,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

            # 检查是否已存在高度相似的模板
            similar = next(
                (t for t in cat_list if t.get("share_hook") == draft.share_hook and t.get("interaction_type") == draft.interaction_type.value),
                None,
            )
            if similar:
                similar["weight"] = round(similar.get("weight", 1.0) + 0.1, 2)
                similar["learned_count"] = similar.get("learned_count", 0) + 1
            else:
                cat_list.append(new_entry)

            # 保持滑动窗口容量限制，按权重和学习频次排序保留 Top N
            cat_list.sort(key=lambda x: (x.get("weight", 1.0) * (x.get("learned_count", 0) + 1)), reverse=True)
            self._data["categories"][category] = cat_list[:MAX_TEMPLATES_PER_CATEGORY]

        # 4. 记录精选 Exemplars（仅保留已发表且审查通过的样本）
        exemplars = self._data.setdefault("learned_exemplars", [])
        exemplars.append({
            "title": video_title,
            "category": category,
            "type": draft.interaction_type.value,
            "comment": draft.formatted_comment,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self._data["learned_exemplars"] = exemplars[-30:]

        self.save()
        logger.info("[StrategyStore] 成功完成经验沉淀，当前类目 '%s' 模版数: %d", category, len(cat_list))
        return True

    def get_templates(self, category: str = "General", interaction_type: Optional[InteractionType] = None) -> List[Dict[str, Any]]:
        """按类目和互动类型检索最匹配的模板。"""
        categories = self._data.get("categories", {})
        candidates = categories.get(category) or categories.get("General") or []
        if interaction_type:
            filtered = [t for t in candidates if t.get("interaction_type") == interaction_type.value]
            if filtered:
                return filtered
        return candidates
