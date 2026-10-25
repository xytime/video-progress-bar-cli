# -*- coding: utf-8 -*-
"""语义脱敏与频道合规安检守门器 (censor_guard.py)

封装基于 src/video_processing/censor_engine.py 的 P0/P1/P2 违禁拦截与
频道内容策略 (Channel Policy) 审查机制。
对输入的待二创脚本、章节拆句、视频标题、数据卡片内容执行严格的 Fail-Closed 安全过滤。

# Modification History
| Version | Date       | Author      | Description |
| ------- | ---------- | ----------- | ----------- |
| 1.0.0   | 2026-10-25 | Antigravity | 初始创建，实现全链路二创脚本语义脱敏与合规安检门禁 |
| 1.2.0 | 2026-10-25 | Codex | 全量合同、Unicode与英文双通道检查，异常拒绝 |
| 1.1.0   | 2026-10-25 | Antigravity | 修复 PROJECT_ROOT 路径层级，增加 NFKC 归一化与零宽字符去隐形防绕过，补齐封面/徽标/关键词全字段安检 |
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


from video_processing.censor_engine import (
    CensorResult,
    check_channel_policy,
    check_text,
)

logger = logging.getLogger(__name__)

# 零宽字符、不可见格式符及软连字符正则
_INVISIBLE_CHARS_PATTERN = re.compile(r"[\u200b-\u200f\ufeff\u00ad\u2060\u202a-\u202e]")
# 符号插入防绕过模式
_SEPARATORS_PATTERN = re.compile(r"[\s\.\-_/|~`^#*+=，。、；：？！]+")


@dataclass
class ComplianceReport:
    """合规检查综合报告"""
    passed: bool
    total_items_checked: int
    violations: List[Dict[str, Any]]
    summary: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ComplianceCensorGuard:
    """合规安检守门器：对二创脚本的各个文本单元进行法律红线与频道策略审查。"""

    def __init__(self, fail_fast: bool = False):
        self.fail_fast = fail_fast

    def _normalize_text(self, text: str) -> str:
        """执行 NFKC 归一化并剔除零宽字符与不可见格式控制符。"""
        if not text:
            return ""
        norm = unicodedata.normalize("NFKC", text)
        clean = "".join(ch for ch in norm if unicodedata.category(ch) not in {"Cc", "Cf", "Mn", "Me"} and not (ord(ch) in {0x115F, 0x1160, 0x3164, 0xFFA0} or 0xFE00 <= ord(ch) <= 0xFE0F or 0xE0100 <= ord(ch) <= 0xE01EF))
        return clean.strip()

    def check_sentence(self, text: str, context: str = "") -> List[Dict[str, Any]]:
        """检查单句文本（中英双语通道 + 防绕过通道）。返回命中的违规项列表。"""
        violations: List[Dict[str, Any]] = []
        if not text or not text.strip():
            return violations

        # 变体集合：原始文本、清洗零宽归一化文本、去标点/空白连接文本
        cleaned_text = self._normalize_text(text)
        variants = [text]
        if cleaned_text and cleaned_text != text:
            variants.append(cleaned_text)

        # 若包含中文字符，增加去标点空白防拆字变体
        has_cjk = any('\u4e00' <= ch <= '\u9fff' for ch in cleaned_text)
        if has_cjk:
            de_spaced = "".join(ch for ch in cleaned_text if not (ch.isspace() or unicodedata.category(ch)[0] in {"P", "S"}))
            if de_spaced and de_spaced not in variants:
                variants.append(de_spaced)

        # 英文分词标点替代（检查变体，不改写交付文案）；不声称穷尽 Unicode。
        english_words = "".join(" " if unicodedata.category(ch)[0] in {"P", "S"} else ch for ch in cleaned_text)
        english_words = " ".join(english_words.split())
        if english_words and english_words not in variants:
            variants.append(english_words)
        seen_keys = set()
        for variant in variants:
            # 1. 法律/政治红线审查 (P0 / P1 / P2)
            legal_result: CensorResult = check_text(zh_text=variant, en_text=variant)
            if legal_result.hit:
                key = ("LEGAL_BLOCKLIST", legal_result.level, legal_result.matched)
                if key not in seen_keys:
                    seen_keys.add(key)
                    violations.append({
                        "type": "LEGAL_BLOCKLIST",
                        "level": legal_result.level,
                        "tag": legal_result.tag,
                        "matched": legal_result.matched,
                        "channel": legal_result.channel,
                        "action": legal_result.action,
                        "context": context,
                        "text_snippet": text[:100],
                    })

            # 2. 频道内容策略审查 (Channel Policy: 地缘政治、战争冲突、意识形态对抗等)
            cp_result: CensorResult = check_channel_policy(zh_text=variant, en_text=variant)
            if cp_result.hit:
                key = ("CHANNEL_POLICY", "CP", cp_result.matched)
                if key not in seen_keys:
                    seen_keys.add(key)
                    violations.append({
                        "type": "CHANNEL_POLICY",
                        "level": "CP",
                        "tag": cp_result.tag,
                        "matched": cp_result.matched,
                        "channel": cp_result.channel,
                        "action": cp_result.action,
                        "context": context,
                        "text_snippet": text[:100],
                    })

        return violations

    def validate_script_manifest(self, manifest: Dict[str, Any]) -> ComplianceReport:
        """检查整套制作清单中的所有文字资产（包含标题、封面、徽标、关键词、章节文案、分句、数据卡片）。"""
        from .manifest_contract import validate_manifest
        violations = []
        checked = 0
        try:
            validate_manifest(manifest)
            def walk(value, context):
                nonlocal checked
                if isinstance(value, str):
                    checked += 1
                    violations.extend(self.check_sentence(value, context))
                elif isinstance(value, dict):
                    for key, item in value.items():
                        walk(item, context + "." + key)
                elif isinstance(value, (tuple, list)):
                    for index, item in enumerate(value):
                        walk(item, f"{context}[{index}]")
            # 可信服务扩展含源证据/路径，不能作为最终文案误杀或带入成片。
            from .manifest_contract import MODEL_FIELDS
            for key in MODEL_FIELDS - {"comparison_table"}:
                walk(manifest[key], "manifest." + key)
            for index, row in enumerate(manifest["comparison_table"]):
                for key in ("remix_chinese_commentary", "reframing_rationale"):
                    walk(row[key], f"comparison[{index}].{key}")
        except Exception as error:
            violations.append({"type": "VALIDATION_ERROR", "context": "manifest", "matched": str(error)})
        passed = not violations and checked > 0
        return ComplianceReport(passed, checked, violations,
            f"规则检查{'通过，仍需人工审核' if passed else '拒绝'}：{checked} 个文本单元，{len(violations)} 项问题")


def main():
    parser = argparse.ArgumentParser(description="二创脚本合规安检工具")
    parser.add_argument("--manifest", type=str, help="待检测的 manifest.json 文件路径")
    parser.add_argument("--text", type=str, help="待检测的单条文本")
    parser.add_argument("--fail-fast", action="store_true", help="发现首个违规立即退出")
    args = parser.parse_args()

    guard = ComplianceCensorGuard(fail_fast=args.fail_fast)

    if args.manifest:
        path = Path(args.manifest)
        if not path.is_file():
            print(f"Error: manifest file not found: {path}", file=sys.stderr)
            sys.exit(1)
        data = json.loads(path.read_text(encoding="utf-8"))
        report = guard.validate_script_manifest(data)
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        sys.exit(0 if report.passed else 2)
    elif args.text:
        violations = guard.check_sentence(args.text)
        passed = len(violations) == 0
        print(json.dumps({
            "passed": passed,
            "violations": violations,
            "summary": "通过" if passed else f"发现 {len(violations)} 处违规"
        }, ensure_ascii=False, indent=2))
        sys.exit(0 if passed else 2)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
