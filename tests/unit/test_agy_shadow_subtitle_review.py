"""AGY 字幕影子比较测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-24 | Codex | 覆盖影子比较的无正文报告、增量去重与手工 Promote 闸门。 |
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    path = Path(__file__).parents[2] / "scripts" / "agy_shadow_subtitle_review.py"
    spec = importlib.util.spec_from_file_location("agy_shadow_subtitle_review_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_bilingual_ass(path: Path) -> None:
    path.write_text(
        """[Script Info]\nScriptType: v4.00+\n\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\nStyle: Default,Arial,30,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\nDialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,The fund raised $49 billion.{\\alpha&HFF&}\\N基金募集490亿美元。\n""",
        encoding="utf-8",
    )


def test_shadow_rollout_writes_hash_only_report_and_deduplicates(tmp_path, monkeypatch):
    module = _load_module()
    input_dir = tmp_path / "output"
    input_dir.mkdir()
    ass_path = input_dir / "sample.ass"
    _write_bilingual_ass(ass_path)
    report_dir = tmp_path / "shadow"
    monkeypatch.setattr(module, "_now", lambda: module._parse_utc("2026-08-24T06:00:00Z"))

    def candidate(source_texts, _context):
        assert source_texts == ["The fund raised $49 billion."]
        return ["基金募集490亿美元。"]

    first = module.run_shadow_rollout(
        input_dir=input_dir,
        report_dir=report_dir,
        max_segments=80,
        start_if_missing=True,
        candidate_runner=candidate,
    )
    second = module.run_shadow_rollout(
        input_dir=input_dir,
        report_dir=report_dir,
        max_segments=80,
        start_if_missing=True,
        candidate_runner=candidate,
    )

    report = next((report_dir / "samples").glob("*.json")).read_text(encoding="utf-8")
    assert "The fund" not in report
    assert "基金募集" not in report
    assert first["unique_inputs_compared"] == 1
    assert second["new_inputs_evaluated"] == 0
    assert second["already_compared_inputs"] == 1
    assert second["auto_promote"] is False
    assert second["manual_decision_required"] is True


def test_shadow_review_marks_provider_failure_without_error_body(tmp_path, monkeypatch):
    module = _load_module()
    ass_path = tmp_path / "sample.ass"
    _write_bilingual_ass(ass_path)
    monkeypatch.setattr(module, "settings", type("Settings", (), {"agy_subtitle_model": "test"})())

    report = module._review_ass(
        ass_path,
        max_segments=80,
        candidate_runner=lambda *_args: (_ for _ in ()).throw(RuntimeError("private subtitle text")),
    )

    assert report["shadow_status"] == "PROVIDER_FAILED"
    assert report["shadow_error_class"] == "RuntimeError"
    assert "private subtitle text" not in str(report)
