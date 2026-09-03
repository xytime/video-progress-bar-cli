"""英语世界视频号原创申请硬门禁测试。

# Modification History
# | Version | Date | Author | Description |
# | --- | --- | --- |
# | 1.0.0 | 2026-09-03 | Codex | 固化英语世界投稿强制申请原创，声明失败不得进入发表。 |
# | 1.1.0 | 2026-09-03 | Codex | 覆盖声明原创标签局部的已选控件回读，避免隐藏 input 漏报。 |
"""

from pathlib import Path

from scripts import submit_english_world_review as submitter
from scripts import wechat_uploader


def test_english_world_uploader_command_requires_original_declaration(tmp_path: Path):
    item = {
        "mp4_path": tmp_path / "study-card.mp4",
        "copy_path": tmp_path / "copy.txt",
        "title_path": tmp_path / "title.txt",
        "cover_path": tmp_path / "cover.jpg",
        "cover_provenance_path": tmp_path / "cover-provenance.json",
    }

    command = submitter._english_world_uploader_command(item, tmp_path / "evidence")

    assert "--require-original-declaration" in command
    assert "--no-original-declaration" not in command


def test_required_original_declaration_blocks_publish_until_ui_confirms_it():
    assert wechat_uploader._original_declaration_publish_allowed(
        declare_original=True,
        require_original_declaration=True,
        declaration_applied=True,
    )


def test_original_declaration_dialog_completion_is_a_platform_action_confirmation():
    assert wechat_uploader._original_declaration_action_is_confirmed(
        direct_ui_confirmed=True,
        declaration_dialog_completed=False,
    )
    assert wechat_uploader._original_declaration_action_is_confirmed(
        direct_ui_confirmed=False,
        declaration_dialog_completed=True,
    )
    assert not wechat_uploader._original_declaration_action_is_confirmed(
        direct_ui_confirmed=False,
        declaration_dialog_completed=False,
    )
    assert not wechat_uploader._original_declaration_publish_allowed(
        declare_original=True,
        require_original_declaration=True,
        declaration_applied=False,
    )
    assert not wechat_uploader._original_declaration_publish_allowed(
        declare_original=False,
        require_original_declaration=True,
        declaration_applied=False,
    )
    assert wechat_uploader._original_declaration_publish_allowed(
        declare_original=True,
        require_original_declaration=True,
        declaration_applied=True,
    )


def test_original_declaration_receipt_requires_confirmed_ui_application(tmp_path: Path):
    receipt = tmp_path / "original_declaration_receipt.json"
    receipt.write_text(
        '{"required": true, "requested": true, "applied_in_ui": true}',
        encoding="utf-8",
    )

    assert submitter._original_declaration_receipt_is_confirmed(tmp_path)

    receipt.write_text(
        '{"required": true, "requested": true, "applied_in_ui": false}',
        encoding="utf-8",
    )
    assert not submitter._original_declaration_receipt_is_confirmed(tmp_path)


class _OriginalDeclarationPage:
    def __init__(self, confirmed: bool) -> None:
        self.confirmed = confirmed

    def evaluate(self, _script: str) -> bool:
        return self.confirmed


def test_original_declaration_requires_post_click_ui_confirmation():
    assert wechat_uploader._original_declaration_ui_is_confirmed(
        _OriginalDeclarationPage(True),
    )
    assert not wechat_uploader._original_declaration_ui_is_confirmed(
        _OriginalDeclarationPage(False),
    )


def test_original_declaration_ui_verifier_checks_checked_controls_inside_the_label_scope():
    class InspectingPage:
        def __init__(self) -> None:
            self.script = ""

        def evaluate(self, script: str) -> bool:
            self.script = script
            return True

    page = InspectingPage()

    assert wechat_uploader._original_declaration_ui_is_confirmed(page)
    assert "textScopes" in page.script
    assert "labeledScopes" in page.script
    assert ".ant-checkbox-checked" in page.script
