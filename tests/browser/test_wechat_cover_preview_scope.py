"""真实 Chromium 验证封面字段范围，避免标签与播放视频污染封面指纹。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-03 | Codex | 标签与图片为兄弟节点时确认图片变化；视频变化与缺失封面均拒绝。 |
"""
from tests.browser_fixtures import chromium
from scripts.wechat_uploader import (
    _find_wechat_cover_preview_card, _wechat_cover_preview_signatures,
    _wechat_cover_preview_visual_signature, _is_wechat_cover_applied,
)


def test_cover_scope_tracks_sibling_preview_and_excludes_video(chromium):
    page = chromium.new_page()
    try:
        page.set_content('''<video id="player"></video>
          <div id="cover-field"><div><span>封面预览</span></div>
          <div><img id="cover" src="https://example.invalid/before.jpg"><button>编辑</button></div></div>
          <p>封面已更新</p>''')
        label = page.get_by_text("封面预览", exact=True)
        assert not _wechat_cover_preview_signatures(label.locator("xpath=.."))
        card = _find_wechat_cover_preview_card(label)
        assert card.get_attribute("id") == "cover-field"
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
