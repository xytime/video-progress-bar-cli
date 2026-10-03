"""真实 Chromium 验证封面字段范围，避免标签与播放视频污染封面指纹。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-03 | Codex | 覆盖真实混排 form-item 的编辑入口收窄、无媒体和多个入口拒绝。 |
| 1.0.0 | 2026-10-03 | Codex | 标签与图片为兄弟节点时确认图片变化；视频变化与缺失封面均拒绝。 |
"""
from tests.browser_fixtures import chromium
from scripts.wechat_uploader import (
    _find_wechat_cover_preview_card, _wechat_cover_preview_signatures,
    _wechat_cover_preview_visual_signature, _is_wechat_cover_applied,
)


def test_cover_scope_tracks_sibling_preview_and_excludes_video(chromium, tmp_path):
    page = chromium.new_page()
    try:
        page.set_content('''<video id="player"></video>
          <div id="cover-field"><div><span>封面预览</span></div>
          <div><img id="cover"><button>编辑</button></div></div>
          <p>封面已更新</p>''')
        label = page.get_by_text("封面预览", exact=True)
        assert not _wechat_cover_preview_signatures(label.locator("xpath=.."))
        card = _find_wechat_cover_preview_card(label, tmp_path)
        assert card.get_attribute("id") == "cover-field"
        assert "https://" not in (tmp_path / "cover_preview_scope.json").read_text()
        before = _wechat_cover_preview_signatures(card)
        visual_before = _wechat_cover_preview_visual_signature(card)
        page.locator("#player").evaluate("node => node.style.background = 'red'")
        assert not _is_wechat_cover_applied(page, card, before, visual_before)
        page.locator("#cover").evaluate("node => node.src = 'https://example.invalid/after.jpg'")
        assert _is_wechat_cover_applied(page, card, before, visual_before)
    finally:
        page.close()


def test_cover_scope_does_not_use_video_or_page_as_missing_preview(chromium):
    page = chromium.new_page()
    try:
        page.set_content('<section><video></video><div><span>封面预览</span></div></section>')
        assert _find_wechat_cover_preview_card(page.get_by_text("封面预览", exact=True)) is None
    finally:
        page.close()


def test_cover_scope_isolates_edit_card_in_mixed_form(chromium, tmp_path):
    page = chromium.new_page()
    try:
        page.set_content('''<div class="form-item flex-start">
          <div>封面预览</div><div><video id="player"></video>
          <div id="cover-card"><img><div><span>编辑</span></div></div>
          <div><img src="unrelated.jpg"></div></div></div><p>封面已更新</p>''')
        card = _find_wechat_cover_preview_card(page.get_by_text("封面预览", exact=True), tmp_path)
        assert card.get_attribute("id") == "cover-card"
        assert card.locator("video").count() == 0
        assert card.locator("img").count() == 1
        before = _wechat_cover_preview_signatures(card)
        visual_before = _wechat_cover_preview_visual_signature(card)
        page.locator("#player").evaluate("node => node.style.background = 'red'")
        assert not _is_wechat_cover_applied(page, card, before, visual_before)
        page.locator("#cover-card img").evaluate("node => node.src = 'https://example.invalid/after.jpg'")
        assert _is_wechat_cover_applied(page, card, before, visual_before)
        page.locator("#cover-card").evaluate("node => node.insertAdjacentHTML('beforeend', '<button>编辑</button>')")
        assert _find_wechat_cover_preview_card(page.get_by_text("封面预览", exact=True)) is None
    finally:
        page.close()


def test_cover_resource_change_survives_failed_image_decode(chromium):
    page = chromium.new_page()
    try:
        page.set_content('<div id="card"><img src="https://example.invalid/before.jpg"></div><p>封面已更新</p>')
        card = page.locator("#card")
        before = _wechat_cover_preview_signatures(card)
        assert "declared-img:https://example.invalid/before.jpg" in before
        page.locator("img").evaluate("node => node.src = 'https://example.invalid/after.jpg'")
        assert _is_wechat_cover_applied(page, card, before, None)
    finally:
        page.close()
