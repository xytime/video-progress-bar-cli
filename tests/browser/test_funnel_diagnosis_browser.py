"""健康诊断真实浏览器回归：范围、失败语义、键盘和精确身份，只允许隔离 GET。"""
from pathlib import Path
import re
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect

from tests.browser_fixtures import chromium
from video_processing.db.database import PipelineDB
from web import app as web_app


@pytest.fixture
def health(chromium, tmp_path, monkeypatch):
    db = PipelineDB(str(tmp_path / 'health.db'))
    db.add_channel('UC_HEALTH', '审计频道', status='APPROVED')
    db.add_video('health-failure', '系统异常 <img src=x onerror=alert(1)>', 'UC_HEALTH', score=85, source='MONITOR')
    db.add_video('health-policy', '策略待复核', 'UC_HEALTH', score=85, source='MONITOR')
    db.add_video('health-receipt', '提交后等待核对', 'UC_HEALTH', score=85, source='MONITOR')
    with db.get_connection() as conn:
        conn.execute("UPDATE processed_videos SET status='FAILED',error_msg='VISUAL_REVIEW_BUDGET_EXCEEDED' WHERE youtube_id='health-failure'")
        conn.execute("UPDATE processed_videos SET status='FAILED',error_msg='Channel Policy Reject: policy rejected' WHERE youtube_id='health-policy'")
        conn.execute("UPDATE processed_videos SET status='UNCERTAIN' WHERE youtube_id='health-receipt'")
        ids = dict(conn.execute('SELECT youtube_id,id FROM processed_videos').fetchall())
    monkeypatch.setattr(web_app, 'db', db)
    monkeypatch.setattr(web_app, '_OUT_DIR', tmp_path)
    monkeypatch.setattr(web_app.settings, 'topic_search_enabled', False)
    client = TestClient(web_app.app, base_url='http://127.0.0.1:9100', client=('127.0.0.1', 50000))
    page = chromium.new_page(viewport={'width': 1366, 'height': 900})
    state = {'writes': [], 'errors': [], 'offline': False, 'requests': []}
    page.on('pageerror', lambda error: state['errors'].append(str(error)))

    def route_handler(route):
        req, url = route.request, urlsplit(route.request.url)
        state['requests'].append(req.url)
        if req.method != 'GET':
            state['writes'].append(req.url)
            route.fulfill(status=500, json={'detail': '验收禁止写操作'})
        elif state['offline'] and url.path == '/api/funnel/diagnosis':
            route.fulfill(status=503, json={'detail': {'message': '诊断来源暂不可用'}})
        elif url.hostname != '127.0.0.1':
            route.fulfill(status=404, body='外网已隔离')
        else:
            response = client.get(url.path + ('?' + url.query if url.query else ''))
            route.fulfill(status=response.status_code, body=response.content, headers=dict(response.headers))

    page.route('**/*', route_handler)
    page.goto('http://127.0.0.1:9100/?view=health&created_window=7d&channel=UC_HEALTH')
    expect(page.locator('#funnel-diagnosis-status')).to_have_text('诊断已更新')
    page.evaluate('clearTimeout(refreshTimeoutId); scheduleNextRefresh=()=>{}')
    yield page, client, state, ids
    page.close()
    client.close()
    assert not state['writes']
    assert not state['errors']


def save_evidence(page, name):
    folder = Path(__file__).resolve().parents[2] / 'output/test-evidence/funnel-diagnosis'
    folder.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(folder / (name + '.png')), full_page=True)


def test_scope_reload_history_and_independent_overview(health):
    page, _, state, _ = health
    expect(page.locator('#funnel-window')).to_have_value('7d')
    expect(page.locator('#funnel-channel')).to_have_value('UC_HEALTH')
    page.reload()
    expect(page.locator('#funnel-window')).to_have_value('7d')
    expect(page.locator('#funnel-channel')).to_have_value('UC_HEALTH')
    page.locator('#funnel-window').select_option('24h')
    expect(page).to_have_url(re.compile('created_window=24h'))
    page.go_back()
    expect(page.locator('#funnel-window')).to_have_value('7d')
    page.locator('.console-primary[data-section=overview]').click()
    expect(page.locator('#overview-health-summary')).to_contain_text('北京时间，全频道')
    assert any('/api/funnel/diagnosis?window=today_bj' in url for url in state['requests'])


def test_keyboard_evidence_exact_details_and_receipt_no_navigation(health):
    page, _, _, ids = health
    task_id = ids['health-receipt']
    cause = page.locator('button[data-action=cause]').first
    page.locator('#funnel-category-POLICY').focus()
    page.keyboard.press('Tab')
    expect(cause).to_be_focused()
    page.keyboard.press('Space')
    expect(cause).to_have_attribute('aria-pressed', 'true')
    page.locator('#funnel-clear').click()
    toggle = page.locator(f'#funnel-toggle-{task_id}')
    toggle.focus()
    page.keyboard.press('Enter')
    expect(toggle).to_be_focused()
    expect(toggle).to_have_attribute('aria-expanded', 'true')
    drawer = page.locator(f'#funnel-evidence-{task_id}')
    expect(drawer).to_contain_text('核对发布回执')
    expect(drawer).not_to_contain_text('重试任务')
    drawer.locator('[data-action=details]').click()
    expect(page.locator('#funnel-task-dialog')).to_be_visible()
    expect(page.locator('#funnel-detail-content')).to_contain_text(f'#{task_id} · health-receipt · 分集 0')
    page.keyboard.press('Escape')
    expect(drawer.locator('[data-action=details]')).to_be_focused()
    old_url = page.url
    drawer.locator('[data-action=receipt]').click()
    expect(page.locator('#operation-receipt-title')).to_contain_text(f'#{task_id}')
    assert page.url == old_url
    page.keyboard.press('Escape')
    expect(drawer.locator('[data-action=receipt]')).to_be_focused()
    assert page.url == old_url
    assert page.locator('#funnel-diagnosis-mount img').count() == 0
    save_evidence(page, 'keyboard-detail-receipt')


def test_failed_refresh_preserves_explicit_stale_snapshot(health):
    page, _, state, _ = health
    old_count = page.locator('#funnel-pill-all_affected b').inner_text()
    state['offline'] = True
    page.locator('#funnel-refresh').click()
    expect(page.locator('.funnel-diag-banner-error')).to_contain_text('旧快照')
    expect(page.locator('.funnel-diag-banner-error')).to_contain_text('近 7 天')
    expect(page.locator('#funnel-pill-all_affected b')).to_have_text(old_count)
    expect(page.locator('.funnel-diag-scope-chip')).to_have_text('当前状态待核实')
    state['offline'] = False
    page.locator('#funnel-refresh').click()
    expect(page.locator('.funnel-diag-banner-error')).to_have_count(0)
    expect(page.locator('#funnel-diagnosis-status')).to_have_text('诊断已更新')


def test_category_change_clears_incompatible_cause_and_keeps_clear_action(health):
    page, _, _, ids = health
    page.locator('#funnel-category-SYSTEM').click()
    page.locator('button[data-action=cause]').first.click()
    expect(page).to_have_url(re.compile('cause='))
    expect(page.locator('#funnel-clear-cause')).to_be_visible()
    page.locator('#funnel-category-POLICY').click()
    assert 'cause=' not in page.url
    expect(page.locator('#funnel-toggle-' + str(ids['health-policy']))).to_be_visible()
    expect(page.locator('button[data-action=cause][aria-pressed=true]')).to_have_count(0)
    page.locator('#funnel-clear').click()
    expect(page.locator('#funnel-category-ALL')).to_have_attribute('aria-pressed', 'true')


def test_initial_failure_is_unknown_without_zero_metrics(health):
    page, _, state, _ = health
    state['offline'] = True
    page.reload()
    expect(page.locator('#funnel-diagnosis-status')).to_have_text('诊断读取失败，当前状态未知')
    expect(page.locator('.funnel-diag-banner-error')).to_contain_text('暂无可信诊断数据')
    expect(page.locator('#funnel-pill-all_affected')).to_have_count(0)
    expect(page.locator('.funnel-diag-scope-chip')).to_have_text('当前状态待核实')
    state['offline'] = False
    page.locator('#funnel-refresh').click()
    expect(page.locator('#funnel-diagnosis-status')).to_have_text('诊断已更新')


def test_late_response_cannot_replace_new_scope_even_if_abort_is_ignored(health):
    page, _, _, _ = health
    page.evaluate("""() => {
      const original = window.fetch;
      window.__releaseLateDiagnosis = null;
      window.fetch = (input, options) => {
        const url = new URL(String(input), location.origin);
        if (url.pathname === '/api/funnel/diagnosis' && url.searchParams.get('window') === '30d') {
          return original(input, {...options, signal:undefined}).then(async response => {
            const data = await response.json();
            data.as_of_bj = '迟到响应不可回写';
            return new Promise(resolve => {
              window.__releaseLateDiagnosis = () => resolve(new Response(JSON.stringify(data), {
                status:200, headers:{'Content-Type':'application/json'}
              }));
            });
          });
        }
        return original(input, options);
      };
    }""")
    page.locator('#funnel-window').select_option('30d')
    page.wait_for_function("typeof window.__releaseLateDiagnosis === 'function'")
    page.locator('#funnel-window').select_option('24h')
    expect(page.locator('#funnel-diagnosis-status')).to_have_text('诊断已更新')
    page.evaluate("async () => {window.__releaseLateDiagnosis();await new Promise(requestAnimationFrame);}")
    expect(page.locator('#funnel-window')).to_have_value('24h')
    expect(page.locator('#funnel-diagnosis-mount')).not_to_contain_text('迟到响应不可回写')
    expect(page).to_have_url(re.compile('created_window=24h'))


def test_broken_task_probe_never_displays_empty_lock_as_observed_fact(health):
    page, _, _, ids = health
    (Path(web_app._OUT_DIR) / 'health-failure_caption_progress.json').write_text('{broken')
    page.locator('#funnel-refresh').click()
    task = page.locator(f'#funnel-toggle-{ids["health-failure"]}').locator('xpath=ancestor::article')
    expect(task).to_contain_text('运行观测不可用')
    expect(task).not_to_contain_text('任务锁未占用')
    task.locator('[data-action=toggle]').click()
    task.locator('[data-action=details]').click()
    content = page.locator('#funnel-detail-content')
    expect(content).to_contain_text('锁未知')
    expect(content).to_contain_text('进程未知')
    expect(content).to_contain_text(re.compile(r'服务观测时间：\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} BJ'))
    page.keyboard.press('Escape')


@pytest.mark.parametrize('theme,width', [('light',1366), ('dark',390), ('contrast',683)])
def test_health_reflow_semantic_warning_and_first_screen(health, theme, width):
    page, _, _, _ = health
    page.evaluate('(theme)=>localStorage.setItem("vp-display-preferences",JSON.stringify({theme,size:"standard"}))', theme)
    page.set_viewport_size({'width':width,'height':844})
    page.reload()
    expect(page.locator('#funnel-diagnosis-status')).to_have_text('诊断已更新')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    box = page.locator('#funnel-window').bounding_box()
    assert box and box['y'] < 700
    for selector in ('.funnel-diag-banner-history', '.step-fail', '.step-warn'):
        ratio = page.locator(selector).first.evaluate("""el => {
          const canvas=document.createElement('canvas');canvas.width=canvas.height=1;
          const ctx=canvas.getContext('2d',{willReadFrequently:true});
          const rgba=color=>{ctx.clearRect(0,0,1,1);ctx.fillStyle=color;ctx.fillRect(0,0,1,1);return [...ctx.getImageData(0,0,1,1).data].map(v=>v/255);};
          const over=(fg,bg)=>fg.slice(0,3).map((v,i)=>v*fg[3]+bg[i]*(1-fg[3]));
          let nodes=[],node=el,bg=[1,1,1];
          while(node){nodes.unshift(node);node=node.parentElement;}
          for(const item of nodes)bg=over(rgba(getComputedStyle(item).backgroundColor),bg);
          const fg=over(rgba(getComputedStyle(el).color),bg);
          const luminance=rgb=>rgb.map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((n,v,i)=>n+v*[.2126,.7152,.0722][i],0);
          const a=luminance(fg),b=luminance(bg);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
        }""")
        assert ratio >= 4.5, (theme, selector, ratio)
    page.emulate_media(reduced_motion='reduce')
    assert page.locator('.funnel-diag-pill').first.evaluate('el=>getComputedStyle(el).animationName') == 'none'
    save_evidence(page, f'health-{theme}-{width}')
