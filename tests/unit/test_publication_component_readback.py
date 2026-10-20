"""已发表组件回执必须保持作品身份与六项平台状态完整。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-21 | Codex | 复现英语世界公开后无法归档，覆盖组件缺失、非布尔值、预约和身份冲突。 |
"""
import json

import pytest

from scripts.run_publication_window import _has_explicit_published_readback


@pytest.mark.parametrize("changed,expected", [
    ({}, True),
    ({"has_posted": False}, False),
    ({"process_success": None}, False),
    ({"posted_info_visible": 1}, False),
    ({"public_visibility": False}, False),
    ({"processing": True}, False),
    ({"scheduled": True}, False),
    ({"scheduled": 0}, False),
])
def test_component_readback_requires_all_native_public_flags(tmp_path, changed, expected):
    component = dict(has_posted=True, process_success=True, posted_info_visible=True,
                     public_visibility=True, processing=False, scheduled=False)
    component.update(changed)
    proof = dict(platform_post_id="export/native", state="PUBLISHED",
                 reason="DOM_POSTED_PUBLIC_COMPONENT", component_state=component)
    path = tmp_path / "management_readback.json"
    path.write_text(json.dumps(proof))
    screenshot = tmp_path / "management_published.png"
    screenshot.write_bytes(b"png")
    assert _has_explicit_published_readback(tmp_path, "export/native") is expected
    assert not _has_explicit_published_readback(tmp_path, "export/other")
    screenshot.unlink()
    assert not _has_explicit_published_readback(tmp_path, "export/native")
