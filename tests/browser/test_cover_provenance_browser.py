"""真实浏览器验证同一来源契约及冻结缩略图。

# Modification History
| Version | Date | Author | Description |
| 1.1 | 2026-10-25 | Codex | 验证跨状态封面真实加载、缺失占位、点击放大及分集隔离。 |
| 1.0 | 2026-10-15 | Codex | 桌面手机键盘展开和 API 来源一致性。 |
"""
import hashlib
from pathlib import Path
import pytest
from PIL import Image
from playwright.sync_api import expect
from tests.browser.test_dashboard_workspace import workspace
from tests.browser_fixtures import chromium
from video_processing.cover_provenance import version, canonical, source_path, freeze_submission
from web import app as web_app


@pytest.mark.parametrize('width', [1366, 390])
def test_existing_cover_loads_across_task_states(workspace, tmp_path, monkeypatch, width):
    page, client, state, db = workspace
    monkeypatch.setattr(web_app, '_OUT_DIR', tmp_path)
    title = '''已有封面 "双引号" '单引号' <标题>'''
    db.add_video('available-cover', title, 'UC-fixture', score=88)
    cover = tmp_path / 'available-cover_cover.jpg'
    Image.new('RGB', (120, 160), 'blue').save(cover)
    page.set_viewport_size(dict(width=width, height=844))
    for status, tab in [('PENDING', 'ready'), ('UNCERTAIN', 'review'),
                        ('FAILED', 'error'), ('AI_COVER_PENDING', 'active')]:
        db.update_video_status('available-cover', status)
        db.set_video_preparation_ready('available-cover', tab == 'ready')
        page.goto(f'http://127.0.0.1:9100/?tab={tab}&created_window=all&search=available-cover')
        image = page.locator('.cover-thumb')
        expect(image).to_be_visible()
        expect(image).to_have_js_property('naturalWidth', 120)
        image.click()
        expect(page.locator('#lb-img')).to_have_js_property('naturalWidth', 120)
        expect(page.locator('#cover-lightbox')).to_be_visible()
        expect(page.locator('#lb-caption')).to_have_text(title)
        page.keyboard.press('Escape')
        expect(page.locator('#cover-lightbox')).not_to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    cover.unlink()
    page.reload()
    expect(page.locator('.cover-placeholder')).to_be_visible()
    expect(page.locator('.cover-thumb')).to_have_count(0)


def test_cover_source_api_and_responsive_display(workspace,tmp_path):
    page,client,state,db=workspace
    db.add_video('cover-browser','封面来源验收','UC-fixture',score=88,source='MONITOR')
    cover=tmp_path/'cover.jpg';Image.new('RGB',(120,160),'blue').save(cover)
    data=version(dict(source='codex_luna_ai_visual',youtube_id='cover-browser',slice_index=0,
                      cover_sha256=hashlib.sha256(cover.read_bytes()).hexdigest(),handoff_reason='agy_failed'))
    source_path(cover).write_text(canonical(data))
    evidence=tmp_path/'submission';freeze_submission(cover,evidence)
    db.record_wechat_submission_acceptance('cover-browser',evidence_path=str(evidence),error_message=None,final_title='封面来源验收',platform_post_id='post-browser')
    db.record_wechat_publication_confirmation('cover-browser',evidence_path=str(tmp_path/'readback'),platform_post_id='post-browser',state='PUBLISHED')
    db.update_video_status('cover-browser','PUBLISHED')
    api=client.get('/api/videos?tab=completed&created_window=all').json()
    row=next(v for v in api['videos'] if v['youtube_id']=='cover-browser')
    assert row['cover_provenance']['version_id']==data['version_id']
    assert client.get('/api/covers/cover-browser').content==cover.read_bytes()
    cover.write_bytes(b'regenerated')
    assert hashlib.sha256(client.get('/api/covers/cover-browser').content).hexdigest()==data['cover_sha256']
    for width in [1366,390]:
        page.set_viewport_size({'width':width,'height':844})
        page.goto('http://127.0.0.1:9100/?tab=completed&created_window=all&search=cover-browser')
        summary=page.locator('.cover-source summary').first
        expect(summary).to_have_text('Codex 接力')
        summary.focus();page.keyboard.press('Enter')
        expect(page.locator('.cover-source[open]').first).to_contain_text(data['cover_sha256'])
        expect(page.locator('.cover-source[open]').first).to_contain_text('agy_failed')
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        folder=Path('output/test-evidence/cover-source');folder.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(folder/f'cover-{width}.png'),full_page=True)
        page.keyboard.press('Escape')
        expect(page.locator('.cover-source[open]')).to_have_count(0)
        expect(summary).to_be_focused()


def test_slice_api_keeps_source_separate_from_parent(workspace, tmp_path, monkeypatch):
    page,client,state,db=workspace
    monkeypatch.setattr(web_app, '_OUT_DIR', tmp_path)
    (tmp_path / 'eligible_cover.jpg').write_bytes(b'parent')
    (tmp_path / 'eligible_s1_cover.jpg').write_bytes(b'slice')
    parent=db.get_video_by_youtube_id('eligible')
    db.add_video('eligible','切片','UC-fixture',slice_index=1,parent_id=parent['id'])
    value=version(dict(source='deterministic_fallback',youtube_id='eligible',slice_index=1,cover_sha256='f'*64))
    db.record_cover_version(value)
    payload=client.get('/api/videos/eligible/slices').json()
    assert payload['slices'][0]['cover_provenance']['version_id']==value['version_id']
    assert payload['slices'][0]['cover_provenance']['label']=='默认封面'
    assert client.get('/api/covers/eligible?slice_index=1').content == b'slice'
    assert client.get('/api/covers/eligible').content == b'parent'
    assert db.get_cover_context('eligible',0)['source']=='unknown'
