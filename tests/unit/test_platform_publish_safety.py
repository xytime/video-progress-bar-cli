"""平台发布安全护栏测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-27 | Codex | 静态锁定平台发布入口：公开提交必须先走上传前审查，审核回查不得发布 |
"""

import ast
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_MANAGER = PROJECT_ROOT / "src" / "video_processing" / "pipeline_manager.py"


def _pipeline_methods() -> dict[str, ast.FunctionDef]:
    module = ast.parse(PIPELINE_MANAGER.read_text(encoding="utf-8"))
    methods: dict[str, ast.FunctionDef] = {}
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == "PipelineManager":
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    methods[item.name] = item
    return methods


def _pipeline_method_names() -> list[str]:
    module = ast.parse(PIPELINE_MANAGER.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == "PipelineManager":
            names.extend(item.name for item in node.body if isinstance(item, ast.FunctionDef))
    return names


def _string_constants(node: ast.AST) -> list[tuple[str, int]]:
    values: list[tuple[str, int]] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            values.append((child.value, child.lineno))
    return values


def test_platform_publish_entrypoints_are_single_and_guarded() -> None:
    methods = _pipeline_methods()
    counts = Counter(_pipeline_method_names())

    for name in (
        "_publish_claimed_kuaishou_publication",
        "_publish_claimed_douyin_publication",
        "_run_kuaishou_history_migration",
        "_run_douyin_history_migration",
        "_retry_one_kuaishou_new_video",
        "_retry_one_douyin_new_video",
    ):
        assert name in methods
        assert counts[name] == 1, f"{name} must have exactly one implementation"

    publish_methods = []
    for name, method in methods.items():
        strings = _string_constants(method)
        if any(value == "--publish" for value, _ in strings):
            publish_methods.append(name)
            publish_line = min(line for value, line in strings if value == "--publish")
            guard_calls = [
                child.lineno
                for child in ast.walk(method)
                if isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "_platform_publication_censorship_blocked"
            ]
            assert guard_calls, f"{name} has --publish without upload-time censorship guard"
            assert min(guard_calls) < publish_line, f"{name} builds --publish before censorship guard"

    assert sorted(publish_methods) == [
        "_publish_claimed_douyin_publication",
        "_publish_claimed_kuaishou_publication",
    ]


def test_review_reconciliation_never_submits_public_publish() -> None:
    methods = _pipeline_methods()
    for name in ("reconcile_kuaishou_under_review", "reconcile_douyin_under_review"):
        strings = [value for value, _ in _string_constants(methods[name])]
        assert "--verify-only" in strings
        assert "--publish" not in strings
        assert "--video" not in strings
