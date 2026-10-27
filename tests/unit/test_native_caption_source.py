"""原字幕保留必须绑定源片、交付片、审查正文及用户确认。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-27 | Codex | 覆盖原样交付、摘要篡改、确认缺失及原有 ASS 不可冒充正文。 |
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_processing.utils import native_caption_source as native
from video_processing.utils.file_utils import read_subtitle_text
from video_processing.utils.render_source_binding import digest


@pytest.fixture
def approved(tmp_path, monkeypatch):
    source = tmp_path / 'original_video/demo.mp4'
    source.parent.mkdir()
    source.write_bytes(b'original video with Chinese captions')
    vertical = tmp_path / 'demo_vertical.mp4'
    approval = tmp_path / 'approval.json'
    approval.write_text(json.dumps({'version': 1, 'sources': {'demo': {
        'source_sha256': digest(source), 'user_confirmed': True,
        'review_text': '源片审查正文',
    }}}))
    monkeypatch.setattr(native, 'APPROVALS', approval)
    return source, vertical, approval


def test_preserve_native_captions_and_review_without_ass(approved):
    source, vertical, _ = approved
    native.preserve(source, vertical)
    assert source.read_bytes() == vertical.read_bytes()
    assert not source.with_suffix('.ass').exists()
    assert native.validate_preserved(vertical, source)
    assert read_subtitle_text(vertical.parent, 'demo') == '源片审查正文'


@pytest.mark.parametrize('target', ['source', 'vertical', 'approval', 'receipt'])
def test_modified_artifacts_fail_closed(approved, target):
    source, vertical, approval = approved
    native.preserve(source, vertical)
    path = {'source': source, 'vertical': vertical, 'approval': approval,
            'receipt': native.receipt_path(vertical)}[target]
    if target == 'receipt':
        data = json.loads(path.read_text())
        data['source_sha256'] = 'tampered'
        path.write_text(json.dumps(data))
    elif target == 'approval':
        data = json.loads(path.read_text())
        data['sources']['demo']['review_text'] = 'changed review'
        path.write_text(json.dumps(data))
    else:
        path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises((ValueError, OSError)):
        native.validate_preserved(vertical, source)


def test_unapproved_or_replaced_source_cannot_be_copied(approved):
    source, vertical, _ = approved
    source.write_bytes(b'other source')
    with pytest.raises(ValueError):
        native.preserve(source, vertical)
    assert not vertical.exists()
    assert native.approved_entry('other') is None


def test_missing_user_confirmation_cannot_be_copied(approved):
    source, vertical, approval = approved
    data = json.loads(approval.read_text())
    data['sources']['demo']['user_confirmed'] = False
    approval.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        native.preserve(source, vertical)


def test_invalid_native_receipt_cannot_fall_back_to_stale_ass(approved):
    source, vertical, _ = approved
    native.preserve(source, vertical)
    native.receipt_path(vertical).unlink()
    (vertical.parent / 'demo.ass').write_text('stale subtitle')
    with pytest.raises(OSError):
        read_subtitle_text(vertical.parent, 'demo')


def test_final_selection_keeps_exact_source_and_rejects_tamper(approved):
    from video_processing.pipeline_manager import PipelineManager
    source, vertical, _ = approved
    native.preserve(source, vertical)
    manager = SimpleNamespace(_OUT_DIR=vertical.parent)
    # 不依赖增强片、互动层、片尾；最终片必须与原片摘要相同。
    assert PipelineManager._get_published_video_path(manager, 'demo') == vertical
    vertical.write_bytes(b'changed')
    with pytest.raises(ValueError):
        PipelineManager._get_published_video_path(manager, 'demo')


def test_another_approval_does_not_invalidate_existing_video(approved):
    source, vertical, approval = approved
    native.preserve(source, vertical)
    data = json.loads(approval.read_text())
    data['sources']['another'] = {'user_confirmed': True, 'review_text': 'other'}
    approval.write_text(json.dumps(data))
    assert native.validate_preserved(vertical, source)


def test_legacy_submitted_receipt_stays_unchanged(approved, monkeypatch):
    source, vertical, approval = approved
    legacy = approval.with_name('legacy.json')
    legacy.write_bytes(approval.read_bytes())
    monkeypatch.setattr(native, 'LEGACY_APPROVALS', legacy)
    vertical.write_bytes(source.read_bytes())
    receipt = native.receipt_path(vertical)
    receipt.write_text(json.dumps(dict(version=1, mode='preserve_native_captions',
                                      approval_sha256=digest(legacy), source_sha256=digest(source))))
    before = receipt.read_bytes()
    data = json.loads(approval.read_text())
    data['sources']['another'] = {'user_confirmed': True}
    approval.write_text(json.dumps(data))
    native.preserve(source, vertical)
    assert receipt.read_bytes() == before
    data['sources']['demo']['review_text'] = 'tamper'
    approval.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        native.validate_preserved(vertical, source)
