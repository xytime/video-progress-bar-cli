"""独立审校协议、内容指纹与失败关闭判定；不依赖外层脚本。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-09 | Codex | 七项覆盖门禁、路径无关缓存键和绑定校验。 |
| 1.0.1 | 2026-09-09 | Codex | 强制逐项裁决转录差异和编辑修改，并以来源区间隔离任务账本。 |
| 1.0.2 | 2026-09-09 | Codex | 将零宽 ASR 时间修复逐组纳入转录准确性覆盖。 |
| 1.0.3 | 2026-09-10 | Codex | 支持带权威证据的 P1 误报裁决，并保留原始独立审校结果。 |
"""
from pathlib import Path

from .language_protocol import (
    CHECKS, VERSION, MODEL, digest, file_digest, read_json, atomic_json, review_schema,
    task_identity, expected_checks, evaluate, apply_adjudications, review_input, cache_key,
)


def validate_language_qa(timeline, *, manifest=None, required=True):
    """绝不把旧产物自动盖章；所有 v2 输入即使影子期开关关闭也验证。"""
    timeline = Path(timeline).expanduser().resolve()
    payload = read_json(timeline)
    if not required and payload.get("language_contract") != VERSION:
        return None
    root = timeline.parent
    if (root / "qa/source_resolution.json").exists():
        from .source_resolution import validate_resolution
        return validate_resolution(timeline, manifest=manifest)
    report = read_json(root / "qa/language_qa.json")
    plan = read_json(root / "display_plan.json")
    if report.get("version") != VERSION:
        raise ValueError("语言审校未通过")
    effective_result = report.get("result")
    if report.get("adjudications"):
        if report.get("state") != "PASS" or "effective_result" not in report:
            raise ValueError("语言裁决报告不完整")
        base_report = {key: value for key, value in report.items()
                       if key not in {"adjudications", "effective_result", "adjudication_version"}}
        base_report["state"] = "FAIL"
        base_digest = digest(base_report)
        if any(item.get("report_sha256") != base_digest for item in report["adjudications"]):
            raise ValueError("语言裁决未绑定原始 AGY 报告")
        effective_result = apply_adjudications(report["result"], report["adjudications"])
        if digest(effective_result) != digest(report["effective_result"]):
            raise ValueError("语言裁决结果与原始审校不一致")
    elif report.get("state") != "PASS":
        raise ValueError("语言审校未通过")
    if report.get("timeline_sha256") != file_digest(timeline) or report.get("plan_sha256") != digest(plan):
        raise ValueError("语言审校文件绑定失效")
    evidence = read_json(root / "qa/source_evidence.json")
    editorial = read_json(root / "editorial_changes.json")
    if report.get("input_key") != cache_key(
            review_input(plan, evidence, editorial, projection=report.get("input_projection", "legacy")),
            report["model"], report.get("effort")):
        raise ValueError("来源或编辑证据已经变化")
    if evaluate(effective_result, plan, evidence=evidence, editorial=editorial) != "PASS":
        raise ValueError("语言审校存在未解决问题")
    provenance = payload["source_provenance"]
    if evidence.get("source_start") != provenance["source_start_seconds"] or evidence.get("source_end") != provenance["source_end_seconds"]:
        raise ValueError("来源证据区间与时间线不一致")
    source = Path(provenance.get("source_video", root / "source/source.mp4"))
    if not source.is_absolute():
        source = root / source
    caption = root / provenance["caption_artifact"]
    if file_digest(source) != evidence["source_sha256"] or file_digest(caption) != evidence["caption_sha256"]:
        raise ValueError("源视频或字幕已经变化")
    if manifest is not None:
        value = read_json(manifest)
        if value.get("display_plan_sha256") != digest(plan):
            raise ValueError("成片与已审校展示计划不匹配")
        if value.get("language_qa_sha256") != file_digest(root / "qa/language_qa.json"):
            raise ValueError("成片与语言审校报告不匹配")
    return report


def validate_publication(item):
    """封装/提交复用相同文本；新文本必须重审，不继承正文 PASS。"""
    from config.settings import settings
    manifest = read_json(item["manifest_path"])
    if not settings.enable_english_world_language_qa and manifest.get("language_contract") != VERSION:
        return
    timeline = Path(manifest["timeline"])
    validate_language_qa(timeline, manifest=Path(item["manifest_path"]))
    from .publication_qa import approved_publication
    approved, supplement = approved_publication(timeline)
    for key in ("title", "copy"):
        if Path(item[key + "_path"]).read_text(encoding="utf-8") != approved[key]:
            raise ValueError(f"投稿 {key} 与独立审校文本不一致，需要重新审校")
    cover_payload = Path(item["cover_path"]).parent / "cover_payload.json"
    if digest(read_json(cover_payload)) != digest(approved["cover_payload"]):
        raise ValueError("实际封面载荷与审校内容不一致")
    if supplement:
        provenance = read_json(item["cover_provenance_path"])
        if provenance.get("language_supplement_sha256") != supplement:
            raise ValueError("投稿包未绑定当前增量文案审校")


def validate_display(timeline, manifest=None):
    """结构检查复算同一计划；不重新选词。音频/关键帧证据仍须另行完成。"""
    from .display_plan import verify_plan
    from .template_a import RecordUnderlineTemplate
    timeline = Path(timeline).expanduser().resolve()
    report = validate_language_qa(timeline, manifest=manifest)
    plan = read_json(timeline.parent / "display_plan.json")
    content = verify_plan(read_json(timeline), plan, file_digest(timeline), RecordUnderlineTemplate())
    if manifest is not None:
        value = read_json(manifest)
        if value.get("word_count") != len(content.words) or digest(value.get("display_screens")) != digest(plan["screens"]):
            raise ValueError("成片逐词或学习屏与计划不同")
        if not 30 < value.get("duration", 0) <= 300 or value.get("speech_end", 0) > value["duration"]:
            raise ValueError("成片时长或语音收尾非法")
    return {"state": report["state"], "screens": plan["screens"], "word_count": len(content.words)}
