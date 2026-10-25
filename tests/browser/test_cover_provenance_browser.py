"""真实浏览器验证同一来源契约及冻结缩略图。

# Modification History
| Version | Date | Author | Description |
| 1.3 | 2026-10-25 | Codex | 自查九类列表、未投稿原图补位与分集实际封面及缺失隔离。 |
| 1.2 | 2026-10-25 | Codex | 验证素材原图补位、不可用终止与冻结投稿封面不降级为原图。 |
| 1.1 | 2026-10-25 | Codex | 验证跨状态封面真实加载、缺失占位、点击放大及分集隔离。 |
| 1.0 | 2026-10-15 | Codex | 桌面手机键盘展开和 API 来源一致性。 |
"""
import hashlib
from datetime import datetime
from io import BytesIO
from pathlib import Path
import pytest
from PIL import Image
from playwright.sync_api import expect
from tests.browser.test_dashboard_workspace import workspace
from tests.browser_fixtures import chromium
from video_processing.cover_provenance import version, canonical, source_path, freeze_submission
from web import app as web_app


@pytest.mark.parametrize('width', [1366, 390])
def test_waitlist_previews_source_thumbnail_when_cover_not_generated(workspace, tmp_path, monkeypatch, width):
    page, client, state, db = workspace
    monkeypatch.setattr(web_app, '_OUT_DIR', tmp_path)
    db.add_video('sourceImg01', '待筛选素材原图', 'UC-fixture', score=20)
    image_bytes = BytesIO()
    Image.new('RGB', (480, 360), 'green').save(image_bytes, format='JPEG')
    thumbnail_requests = []

    def thumbnail(route):
        thumbnail_requests.append(route.request.url)
        route.fulfill(content_type='image/jpeg', body=image_bytes.getvalue())

    thumbnail_url = 'https://i.ytimg.com/vi/sourceImg01/hqdefault.jpg'
    page.route(thumbnail_url, thumbnail)
    page.set_viewport_size(dict(width=width, height=844))
    url = 'http://127.0.0.1:9100/?view=topics&tab=waitlist&created_window=all&search=sourceImg01'
    page.goto(url)
    image = page.locator('#row-sourceImg01 .cover-thumb')
    expect(image).to_have_js_property('naturalWidth', 480)
    expect(image).to_have_attribute('alt', 'YouTube 原视频缩略图')
    expect(page.locator('#row-sourceImg01 .cover-source summary')).to_have_text('YouTube 原图')
    assert page.title() == '选题中心 · 视频运营工作台'
    assert thumbnail_requests == [thumbnail_url]
    image.click()
    expect(page.locator('#lb-img')).to_have_js_property('naturalWidth', 480)
    page.keyboard.press('Escape')
    summary = page.locator('#row-sourceImg01 .cover-source summary')
    summary.focus()
    page.keyboard.press('Enter')
    expect(page.locator('#row-sourceImg01 .cover-source[open]')).to_contain_text('仅供素材浏览')
    page.keyboard.press('Escape')
    expect(summary).to_be_focused()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')

    # 原图只补位，随后生成的本地封面仍然优先。
    requests_before_reload = list(thumbnail_requests)
    Image.new('RGB', (120, 160), 'blue').save(tmp_path / 'sourceImg01_cover.jpg')
    page.reload()
    expect(page.locator('#row-sourceImg01 .cover-thumb')).to_have_js_property('naturalWidth', 120)
    expect(page.locator('#row-sourceImg01 .cover-source summary')).to_have_text('来源未核验')
    assert thumbnail_requests == requests_before_reload


def test_unavailable_source_thumbnail_stops_and_bound_cover_never_falls_back(workspace, tmp_path, monkeypatch):
    page, client, state, db = workspace
    monkeypatch.setattr(web_app, '_OUT_DIR', tmp_path)
    db.add_video('brokenImg01', '原图不可用', 'UC-fixture', score=20)
    thumbnail_requests = []

    def unavailable(route):
        thumbnail_requests.append(route.request.url)
        route.fulfill(status=404, body='missing')

    page.route('https://i.ytimg.com/**', unavailable)
    page.goto('http://127.0.0.1:9100/?view=topics&tab=waitlist&created_window=all&search=brokenImg01')
    expect(page.locator('#row-brokenImg01 .cover-placeholder')).to_be_visible()
    expect(page.locator('#row-brokenImg01 .cover-source summary')).to_have_text('暂无预览图')
    assert len(thumbnail_requests) == 1
    assert not page.locator('#row-brokenImg01 .cover-thumb').count()

    # 即使投稿冻结文件丢失，也不能用 YouTube 原图冒充投稿封面。
    db.add_video('boundImg001', '投稿封面缺失', 'UC-fixture', score=20)
    cover = tmp_path / 'bound-cover.jpg'
    Image.new('RGB', (120, 160), 'blue').save(cover)
    data = version(dict(source='codex_luna_ai_visual', youtube_id='boundImg001', slice_index=0,
                        cover_sha256=hashlib.sha256(cover.read_bytes()).hexdigest()))
    source_path(cover).write_text(canonical(data))
    evidence = tmp_path / 'bound-submission'
    freeze_submission(cover, evidence)
    db.record_wechat_submission_acceptance('boundImg001', evidence_path=str(evidence),
                                          error_message=None, final_title='投稿封面缺失',
                                          platform_post_id='bound-post')
    (evidence / 'submitted_cover.jpg').unlink()
    page.goto('http://127.0.0.1:9100/?view=publications&tab=review&created_window=all&search=boundImg001')
    expect(page.locator('#row-boundImg001 .cover-placeholder')).to_be_visible()
    expect(page.locator('#row-boundImg001 .cover-placeholder')).to_contain_text('投稿封面缺失')
    expect(page.locator('#row-boundImg001 .cover-source summary')).to_have_text('Codex 接力')
    assert len(thumbnail_requests) == 1


@pytest.mark.parametrize('width', [1366, 390])
def test_existing_cover_loads_across_task_states(workspace, tmp_path, monkeypatch, width):
    page, client, state, db = workspace
    monkeypatch.setattr(web_app, '_OUT_DIR', tmp_path)
    title = '''已有封面 "双引号" '单引号' <标题>'''
    db.add_video('available-cover', title, 'UC-fixture', score=88,
                 view_count=1000, like_count=40, upload_date=datetime.now().strftime('%Y%m%d'))
    cover = tmp_path / 'available-cover_cover.jpg'
    Image.new('RGB', (120, 160), 'blue').save(cover)
    page.set_viewport_size(dict(width=width, height=844))
    for status, tab in [('PENDING', 'waitlist'), ('PENDING', 'queue'),
                        ('PENDING', 'ready'), ('UNCERTAIN', 'review'),
                        ('PENDING', 'high_likes'), ('WECHAT_DEFERRED', 'wechat_deferred'),
                        ('PUBLISHED', 'completed'), ('AI_COVER_PENDING', 'active'),
                        ('FAILED', 'error')]:
        db.update_video_status('available-cover', status)
        db.update_video_score('available-cover', 20 if tab == 'waitlist' else 88)
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


def test_source_preview_covers_unsubmitted_lists_but_not_publication_states(workspace, tmp_path, monkeypatch):
    page, client, state, db = workspace
    monkeypatch.setattr(web_app, '_OUT_DIR', tmp_path)
    db.add_video('queuedImg01', '未投稿列表原图', 'UC-fixture', score=88)
    image_bytes = BytesIO()
    Image.new('RGB', (480, 360), 'green').save(image_bytes, format='JPEG')
    requests = []

    def thumbnail(route):
        requests.append(route.request.url)
        route.fulfill(content_type='image/jpeg', body=image_bytes.getvalue())

    page.route('https://i.ytimg.com/**', thumbnail)
    for status, tab in [('PENDING', 'queue'), ('TRANSCRIBING', 'active'),
                        ('FAILED', 'error'), ('WECHAT_DEFERRED', 'wechat_deferred')]:
        db.update_video_status('queuedImg01', status)
        page.goto(f'http://127.0.0.1:9100/?tab={tab}&created_window=all&search=queuedImg01')
        expect(page.locator('#row-queuedImg01 .cover-thumb')).to_have_js_property('naturalWidth', 480)
        expect(page.locator('#row-queuedImg01 .cover-source summary')).to_have_text('YouTube 原图')
    before = len(requests)
    for status, tab in [('UNCERTAIN', 'review'), ('SUBMITTED_UNBOUND', 'review'),
                        ('PUBLISHED', 'completed')]:
        db.update_video_status('queuedImg01', status)
        page.goto(f'http://127.0.0.1:9100/?tab={tab}&created_window=all&search=queuedImg01')
        expect(page.locator('#row-queuedImg01 .cover-placeholder')).to_be_visible()
        assert len(requests) == before

    # 已记录的生成版本丢失文件，也不以素材图替代。
    db.record_cover_version(version(dict(source='deterministic_fallback', youtube_id='queuedImg01',
                                         slice_index=0, cover_sha256='f' * 64)))
    db.update_video_status('queuedImg01', 'FAILED')
    page.goto('http://127.0.0.1:9100/?tab=error&created_window=all&search=queuedImg01')
    expect(page.locator('#row-queuedImg01 .cover-placeholder')).to_be_visible()
    expect(page.locator('#row-queuedImg01 .cover-placeholder')).to_contain_text('生成封面缺失')
    expect(page.locator('#row-queuedImg01 .cover-source summary')).to_have_text('默认封面')
    assert len(requests) == before


@pytest.mark.parametrize('width', [1366, 390])
def test_expanded_slices_load_their_own_cover_and_missing_slice_stays_separate(workspace, tmp_path, monkeypatch, width):
    page, client, state, db = workspace
    monkeypatch.setattr(web_app, '_OUT_DIR', tmp_path)
    db.add_video('sliceTest01', '父视频封面', 'UC-fixture', score=88)
    parent = db.get_video_by_youtube_id('sliceTest01')
    title = '''分集 "封面" '独立' <验证>'''
    for index in [1, 2]:
        db.add_video('sliceTest01', title if index == 1 else '无封面分集', 'UC-fixture',
                     score=88, slice_index=index, parent_id=parent['id'])
    Image.new('RGB', (120, 160), 'blue').save(tmp_path / 'sliceTest01_cover.jpg')
    cover = tmp_path / 'sliceTest01_s1_cover.jpg'
    Image.new('RGB', (96, 128), 'green').save(cover)
    value = version(dict(source='deterministic_fallback', youtube_id='sliceTest01', slice_index=1,
                         cover_sha256=hashlib.sha256(cover.read_bytes()).hexdigest()))
    db.record_cover_version(value)
    source_requests = []
    page.route('https://i.ytimg.com/**', lambda route: (source_requests.append(route.request.url), route.abort()))
    page.set_viewport_size(dict(width=width, height=844))
    page.goto('http://127.0.0.1:9100/?tab=queue&created_window=all&search=sliceTest01')
    expect(page.locator('#row-sliceTest01 .cover-thumb')).to_have_js_property('naturalWidth', 120)
    page.locator('#btn-toggle-sliceTest01').click()
    image = page.locator('#row-sliceTest01_s1 .cover-thumb')
    expect(image).to_have_js_property('naturalWidth', 96)
    expect(image).to_have_attribute('alt', '分集封面')
    expect(page.locator('#row-sliceTest01_s2 .cover-placeholder')).to_be_visible()
    summary = page.locator('#row-sliceTest01_s1 .cover-source summary')
    expect(summary).to_have_text('默认封面')
    summary.focus()
    page.keyboard.press('Enter')
    expect(page.locator('#row-sliceTest01_s1 .cover-source[open]')).to_contain_text(value['version_id'])
    page.keyboard.press('Escape')
    expect(summary).to_be_focused()
    image.click()
    expect(page.locator('#lb-img')).to_have_js_property('naturalWidth', 96)
    expect(page.locator('#lb-caption')).to_have_text(title)
    page.keyboard.press('Escape')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.locator('#btn-toggle-sliceTest01').click()
    expect(page.locator('#row-sliceTest01_s1')).to_have_count(0)
    page.locator('#btn-toggle-sliceTest01').click()
    expect(page.locator('#row-sliceTest01_s1 .cover-thumb')).to_have_js_property('naturalWidth', 96)
    assert not source_requests


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
