"""内容语义分析器 (SemanticAnalyzer)

# Modification History
| Version | Date       | Author                       | Description                                                  |
|---------|------------|------------------------------|--------------------------------------------------------------|
| 1.0.0   | 2026-05-26 | Gemini_3.5_Flash_planning    | 初始创建，根据 content_hints 和标题关键字匹配视觉信号和主题颜色 |
| 1.1.0   | 2026-06-02 | Gemini_2.5_Pro_planning      | 将 template_variant 字段加入 ContentSignal，支持 rules.json 自定义模板变体 |
"""

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class ContentSignal:
    """[Gemini_3.5_Flash_planning] 驱动后续所有视觉决策的语义分析信号"""
    id: str
    accent: str
    base_gradient: str
    metaphor: str
    metaphor_placement: str
    emotion_temperature: str
    default_badge: str
    # [Gemini_2.5_Pro_planning] v1.1.0 模板变体，默认 'cover'
    template_variant: str = "cover"

class SemanticAnalyzer:
    """
    内容语义分析器 (Rules-based Chain of Responsibility)
    优先基于 content_hints 匹配，其次通过标题/副标题关键字匹配。
    """
    def __init__(self, rules_path: Path):
        self.rules_path = Path(rules_path)
        self.rules = []
        self._load_rules()

    def _load_rules(self) -> None:
        if not self.rules_path.exists():
            # [Gemini_3.5_Flash_planning] 防御性兜底：如果文件不存在，加载默认规则
            self.rules = [{
                "id": "default",
                "hints": [],
                "keywords": [],
                "accent": "cyan_pulsing",
                "base_gradient": "deep_blue",
                "metaphor": "zap",
                "metaphor_placement": "top-right",
                "emotion_temperature": "neutral",
                "default_badge": "科技观察"
            }]
            return
        try:
            with open(self.rules_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.rules = data.get("rules", [])
        except Exception:
            self.rules = []

    def analyze(self, payload: dict) -> ContentSignal:
        """
        根据标题、副标题和 hints 匹配对应的视觉主题规则
        """
        title = payload.get("title", "").lower()
        subtitle = payload.get("subtitle", "").lower()
        content_hints = [h.lower() for h in payload.get("content_hints", [])]
        
        matched_rule = None
        
        # 1. 优先遍历规则进行匹配（排除 default 兜底规则）
        for rule in self.rules:
            if rule.get("id") == "default":
                continue
                
            # A. 检查 content_hints (LLM精准提取)
            rule_hints = [h.lower() for h in rule.get("hints", [])]
            if any(h in content_hints for h in rule_hints if h):
                matched_rule = rule
                break
                
            # B. 检查标题/副标题关键字 (关键词模糊匹配)
            rule_keywords = [k.lower() for k in rule.get("keywords", [])]
            if any(k in title or k in subtitle for k in rule_keywords if k):
                matched_rule = rule
                break

        # 2. 如果没有任何匹配，退回到 default 规则
        if not matched_rule:
            for rule in self.rules:
                if rule.get("id") == "default":
                    matched_rule = rule
                    break
            if not matched_rule:
                # 终极 Fallback
                return ContentSignal(
                    id="default",
                    accent="cyan_pulsing",
                    base_gradient="deep_blue",
                    metaphor="zap",
                    metaphor_placement="top-right",
                    emotion_temperature="neutral",
                    default_badge="科技观察"
                )

        return ContentSignal(
            id=matched_rule["id"],
            accent=matched_rule["accent"],
            base_gradient=matched_rule["base_gradient"],
            metaphor=matched_rule["metaphor"],
            metaphor_placement=matched_rule["metaphor_placement"],
            emotion_temperature=matched_rule["emotion_temperature"],
            default_badge=matched_rule.get("default_badge", "科技观察"),
            # [Gemini_2.5_Pro_planning] v1.1.0: 传递 template_variant
            template_variant=matched_rule.get("template_variant", "cover"),
        )
