"""平台题材审查的输入与证据契约。

依赖：pipeline/web/service -> 本模块 -> censor_engine/core、utils；无 DB 或外部调用。
源字幕、发布字幕都完整读取；不做 OCR，不更改历史任务。
"""
import json
import re
from pathlib import Path

from . import censor_engine
from .core.social_unrest import input_hash
from .utils.file_utils import read_webvtt_cues


FINAL_STAGES = {"wechat_publish", "platform_publish"}
REVIEW_STAGES = FINAL_STAGES | {"source_subtitle_preflight"}
TAG = "平台题材风险：社会动荡"
APPROVAL = "MANUAL_SOCIAL_UNREST_APPROVED"


def text_documents(title="", zh_title="", description="", subtitle=""):
    return [{"source": source, "text": text} for source, text in
            (("title", title), ("zh_title", zh_title), ("description", description), ("subtitle", subtitle)) if text and text.strip()]


def _cue_document(source, cues):
    offset = 0
    indexed = []
    for cue in cues:
        indexed.append({**cue, "offset": offset})
        offset += len(cue["text"]) + 1
    return {"source": source, "text": "\n".join(cue["text"] for cue in indexed), "cues": indexed}


def _ass_cues(path):
    import pysubs2
    subtitles = pysubs2.load(str(path), encoding="utf-8")
    def timestamp(ms):
        seconds, millis = divmod(ms, 1000)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}.{millis:03}"
    return [{"text": event.plaintext.strip(), "file": path.name,
             "start": timestamp(event.start), "end": timestamp(event.end)}
            for event in subtitles if event.plaintext.strip() and not event.is_comment]


def collect_documents(video, output_dir, *, title, zh_title="", description="", subtitle="", stage="pipeline"):
    """共享执行/复核输入；只读取该 ID/切片的维护产物，不猜测父片时间。"""
    documents = text_documents(title, zh_title, description)
    for field in ("title", "description"):
        if video.get(field):
            documents.append({"source": "source_" + field, "text": video[field]})
    if stage not in REVIEW_STAGES or output_dir is None:
        return documents + text_documents(subtitle=subtitle)
    root = Path(output_dir)
    yid, slice_index = video["youtube_id"], int(video.get("slice_index") or 0)
    prefix = f"{yid}_s{slice_index}" if slice_index else yid
    # 多语言 VTT 分开成文档，不能用两个语言文件的距离制造共现。
    source_prefix = prefix + "_source_subtitle"
    source_files = sorted(p for p in root.glob(f"{source_prefix}*.vtt")
                          if p.name == source_prefix + ".vtt" or p.name.startswith(source_prefix + "."))
    for path in source_files:
        # 文件存在但不能读/解析，不得把不完整证据当作通过。
        path.read_text(encoding="utf-8-sig")
        cues = read_webvtt_cues([path], max_chars=None)
        if not cues:
            raise ValueError(f"社会动荡审查无法解析源字幕：{path.name}")
        documents.append(_cue_document("source_vtt:" + path.name, cues))
    if stage in FINAL_STAGES:
        accept = re.compile(rf"^{re.escape(prefix)}(?:\.|$)")
        directories = (root, root / "original_video", root / "subtitle_evidence" / prefix / "ass")
        # 热字幕优先，归档只在热字幕缺失时回退，避免把过时版本混入本次发布。
        for directory in directories:
            paths = sorted(p for p in directory.glob(f"{prefix}*.ass") if accept.match(p.stem))
            if not paths:
                continue
            for path in paths:
                cues = _ass_cues(path)
                if not cues:
                    raise ValueError(f"社会动荡审查无法解析发布字幕：{path.name}")
                documents.append(_cue_document("rendered_ass:" + path.name, cues))
            break
        for suffix in ("_title.txt", "_display_title.txt", "_subtitle.txt", "_label.txt", "_category.txt"):
            path = root / (prefix + suffix)
            if path.exists():
                documents.append({"source": "cover_text:" + path.name, "text": path.read_text(encoding="utf-8")})
        provenance = root / (prefix + "_cover_provenance.json")
        if provenance.exists():
            record = json.loads(provenance.read_text(encoding="utf-8"))
            typography = record.get("rendered_typography") or {}
            lines = typography.get("bounds") or []
            rendered = "\n".join(str(line.get("text") or "") for line in lines)
            if rendered:
                documents.append({"source": "cover_rendered_text:" + provenance.name, "text": rendered})
        if not any(document.get("cues") for document in documents):
            raise ValueError("发布前平台题材复核缺少完整可定位字幕证据")
    elif not source_files and subtitle:
        documents += text_documents(subtitle=subtitle)
    return documents


def evaluate(documents):
    hit = censor_engine.check_social_unrest(documents)
    if hit:
        return {**hit, "input_hash": input_hash(documents),
                "rule_version": censor_engine.current_rules_fingerprint()}
    return None


def approved(incidents, evidence):
    return any(row.get("decision") == APPROVAL
               and row.get("input_hash") == evidence["input_hash"]
               and row.get("rule_pack_version") == evidence["rule_version"] for row in incidents)


def replay(video, incident, output_dir):
    """只在原输入/规则均可重现时展示位置；无法重现时不能提供泛化放行。"""
    base = {"status": "UNAVAILABLE", "incident_id": incident.get("id"),
            "rule_id": incident.get("rule_id"), "rule_version": incident.get("rule_pack_version"),
            "input_hash": incident.get("input_hash"), "review_stage": incident.get("review_stage")}
    try:
        stage = incident.get("review_stage")
        if stage in FINAL_STAGES:
            prefix = video["youtube_id"] + (f"_s{video['slice_index']}" if video.get("slice_index") else "")
            root = Path(output_dir)
            copy_file = root / (prefix + "_copy.txt")
            if stage == "platform_publish" and incident.get("platform") == "快手":
                dedicated_copy = root / (prefix + "_kuaishou_copy.txt")
                copy_file = dedicated_copy if dedicated_copy.is_file() else copy_file
                title = video.get("zh_title") or video.get("title") or video["youtube_id"]
                zh_title = video.get("zh_title") or title
            else:
                title = (root / (prefix + "_title.txt")).read_text(encoding="utf-8").strip()
                zh_title = title
            description = copy_file.read_text(encoding="utf-8")
            if stage == "platform_publish":
                description = description.strip()
        else:
            # 审计字段有长度上限，截断后不能匹配完整输入 hash 时按不可回放处理。
            title, zh_title, description = (incident.get(k) or "" for k in ("title", "zh_title", "description_preview"))
        documents = collect_documents(video, output_dir, title=title, zh_title=zh_title,
                                      description=description, stage=stage)
        evidence = evaluate(documents)
        if not evidence or evidence["input_hash"] != base["input_hash"] or evidence["rule_version"] != base["rule_version"]:
            raise ValueError("输入或规则与原审计不一致，须重新审查")
        return {**base, **evidence, "status": "VERIFIED_REPLAY",
                "message": "平台题材风险，非违法结论；原输入及规则指纹一致。",
                "timing_note": "时间来自实际 VTT/ASS cue；元数据无时间，不推测画面。"}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return {**base, "message": str(exc)}


def ledger_excerpt(evidence):
    # 保持 DAL 的 600 字限制；完整定位由输入/规则指纹一致的只读回放提供。
    return json.dumps({"context": evidence["context"][:220], "terms": evidence["terms"][:1]}, ensure_ascii=False)[:600]
