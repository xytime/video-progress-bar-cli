"""真实隔离 Chromium 中的视频号评论因果绑定验收。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-10-03 | Codex | 覆盖首页初始化竞态、延迟评论卡片、加载超时和登录回跳的只读导航边界。 |
| 1.1.0 | 2026-09-26 | Codex | 覆盖发送前错帖阻断、场景 ID 与完整作者回读。 |
| 1.0.0 | 2026-09-19 | Codex | 覆盖原生 ID、响应因果、完整作者回读、延迟成功和 verify-only。 |
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.browser_fixtures import chromium
from video_processing.interaction.browser_commenter import BrowserCommenter


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "wechat_interaction.html"
COMMENT_PATH = "/cgi-bin/mmfinderassistant-bin/comment/create"
COMMENT = "第一行完整评论\n第二行也必须完整匹配"


@pytest.fixture
def interaction_page(chromium):
    page = chromium.new_page(viewport={"width": 1280, "height": 800})
    writes = []

    def route_handler(route):
        request = route.request
        path = request.url.split("?", 1)[0].replace("http://wechat-fixture.invalid", "")
        if request.is_navigation_request():
            route.fulfill(content_type="text/html", body=FIXTURE.read_text(encoding="utf-8"))
            return
        if request.method == "POST":
            payload = request.post_data_json
            writes.append({"path": path, "payload": payload})
            mode = page.evaluate("window.fixtureState.mode")
            if request.url.startswith("http://wrong-origin.invalid/"):
                route.fulfill(
                    headers={"access-control-allow-origin": "*"},
                    json={
                        "errCode": 0,
                        "data": {"objectId": payload["objectId"], "commentId": "wrong-origin"},
                    },
                )
            elif path == COMMENT_PATH:
                if mode == "rejected":
                    route.fulfill(json={"errCode": 17, "errMsg": "fixture rejected"})
                elif mode == "unknown-response":
                    route.fulfill(json={"data": {"message": "schema changed"}})
                elif mode == "wrong-response-id":
                    route.fulfill(json={
                        "errCode": 0,
                        "data": {"objectId": "post-wrong", "commentId": "comment-1"},
                    })
                else:
                    route.fulfill(json={
                        "errCode": 0,
                        "data": {"objectId": payload["objectId"], "commentId": "comment-1"},
                    })
            else:
                route.fulfill(json={"errCode": 0, "data": {"items": []}})
            return
        route.fulfill(body="")

    page.route("**/*", route_handler)
    page.goto("http://wechat-fixture.invalid/platform/interaction/comment")
    try:
        yield page, writes
    finally:
        page.close()


def _run(page, tmp_path: Path, *, mode="success", target="post-target", verify_only=False):
    page.evaluate("mode => { window.fixtureState.mode = mode; }", mode)
    commenter = BrowserCommenter(
        state_path=tmp_path / "unused-state.json",
        response_timeout_ms=450,
        dom_timeout_ms=600,
        poll_interval_ms=25,
    )
    attempt = commenter._new_attempt_dir(tmp_path / "evidence")
    result = commenter._interact_with_page(
        page,
        comment_text=COMMENT,
        platform_post_id=target,
        video_title="重复标题",
        attempt_dir=attempt,
        before_submit=None if verify_only else (lambda: True),
        verify_only=verify_only,
    )
    receipt = json.loads((attempt / "receipt.json").read_text(encoding="utf-8"))
    return result, receipt, attempt


def test_reordered_duplicate_titles_bind_only_exact_native_id(interaction_page, tmp_path: Path):
    page, writes = interaction_page
    result, receipt, _ = _run(page, tmp_path)

    assert result[0] == "COMMENTED"
    assert writes == [{
        "path": COMMENT_PATH,
        "payload": {"objectId": "post-target", "content": COMMENT},
    }]
    assert receipt["accepted_comment_id"] == "comment-1"
    assert page.locator('[data-current-object-id="post-target"]').count() == 1


def test_wrong_or_ambiguous_native_id_never_opens_writer(interaction_page, tmp_path: Path):
    page, writes = interaction_page
    result, _, _ = _run(page, tmp_path, target="post-missing")
    assert result[0] == "FAILED"
    assert page.evaluate("window.fixtureState.writeOpened") == 0
    assert writes == []

    page.locator("#cards").evaluate("el => el.insertAdjacentHTML('beforeend', '<button data-object-id=\"post-target\">重复标题</button>')")
    result, _, _ = _run(page, tmp_path)
    assert result[0] == "FAILED"
    assert page.evaluate("window.fixtureState.writeOpened") == 0


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("unrelated-only", "UNCERTAIN"),
        ("cross-origin-only", "FAILED"),
        ("no-api", "UNCERTAIN"),
        ("rejected", "FAILED"),
        ("unknown-response", "UNCERTAIN"),
        ("wrong-response-id", "UNCERTAIN"),
        ("partial", "UNCERTAIN"),
        ("author-mismatch", "UNCERTAIN"),
        ("delayed", "COMMENTED"),
    ],
)
def test_submit_requires_correlated_acceptance_and_exact_author_readback(
    interaction_page, tmp_path: Path, mode: str, expected: str
):
    page, _ = interaction_page
    result, _, _ = _run(page, tmp_path, mode=mode)
    assert result[0] == expected


def test_preclick_stale_response_is_ignored(interaction_page, tmp_path: Path):
    page, writes = interaction_page
    page.evaluate(
        """async ([path, content]) => {
          await fetch(path, {method: 'POST', headers: {'content-type':'application/json'},
            body: JSON.stringify({objectId:'post-target', content})});
          window.fixtureState.mode = 'no-api';
        }""",
        [COMMENT_PATH, COMMENT],
    )
    result, _, _ = _run(page, tmp_path, mode="no-api")
    assert result[0] == "UNCERTAIN"
    assert len(writes) == 1  # 只有监听安装前的陈旧响应，点击后没有关联响应。


def test_selector_metacharacters_in_untrusted_id_fail_closed(interaction_page, tmp_path: Path):
    page, writes = interaction_page
    result, _, _ = _run(
        page,
        tmp_path,
        target='post-target"][data-object-id="post-other',
    )
    assert result[0] == "FAILED"
    assert page.evaluate("window.fixtureState.writeOpened") == 0
    assert writes == []


def test_detail_rebind_before_callback_stops_without_submit(interaction_page, tmp_path: Path):
    page, writes = interaction_page
    callback_calls = []
    page.evaluate("window.fixtureState.mode = 'reorder-before-submit'")
    commenter = BrowserCommenter(
        state_path=tmp_path / "unused-state.json",
        response_timeout_ms=200,
        dom_timeout_ms=200,
        poll_interval_ms=25,
    )
    attempt = commenter._new_attempt_dir(tmp_path / "evidence")
    result = commenter._interact_with_page(
        page,
        comment_text=COMMENT,
        platform_post_id="post-target",
        video_title="重复标题",
        attempt_dir=attempt,
        before_submit=lambda: callback_calls.append(True) or True,
        verify_only=False,
    )
    assert result[0] == "FAILED"
    assert callback_calls == []
    assert page.evaluate("window.fixtureState.submitClicked") == 0
    assert writes == []


def test_verify_only_never_opens_writer_or_submits(interaction_page, tmp_path: Path):
    page, writes = interaction_page
    result, _, _ = _run(page, tmp_path, verify_only=True)
    assert result[0] == "FAILED"
    assert page.evaluate("window.fixtureState.writeOpened") == 0
    assert page.evaluate("window.fixtureState.submitClicked") == 0
    assert writes == []


def test_incomplete_comments_fail_closed_before_writer(interaction_page, tmp_path: Path):
    page, writes = interaction_page
    page.locator('[data-object-id="post-target"]').click()
    page.locator("[data-comment-list]").evaluate("el => el.dataset.commentsComplete = 'false'")
    # 复用已打开详情：下一次点击会重建，因此改为让目标点击后即篡改的 listener。
    page.evaluate("""() => {
      const card = document.querySelector('[data-object-id="post-target"]');
      card.addEventListener('click', () => {
        document.querySelector('[data-comment-list]').dataset.commentsComplete = 'false';
      });
    }""")
    result, _, _ = _run(page, tmp_path)
    assert result[0] == "FAILED"
    assert page.evaluate("window.fixtureState.writeOpened") == 0
    assert writes == []


@pytest.mark.parametrize("blank_comment_id", ["", "   "])
def test_blank_author_comment_id_fails_closed_before_writer(
    interaction_page, tmp_path: Path, blank_comment_id: str
):
    page, writes = interaction_page
    page.evaluate(
        """blankId => {
          const card = document.querySelector('[data-object-id="post-target"]');
          card.addEventListener('click', () => {
            const node = document.createElement('div');
            node.setAttribute('data-author-role', 'author');
            node.setAttribute('data-comment-id', blankId);
            node.textContent = '已有作者评论';
            document.querySelector('[data-comment-list]').appendChild(node);
          });
        }""",
        blank_comment_id,
    )
    result, receipt, _ = _run(page, tmp_path)
    assert result[0] == "FAILED"
    assert "comment ID 为空" in (result[2] or "")
    assert receipt["invalid_author_comment_id_indexes"] == [0]
    assert page.evaluate("window.fixtureState.writeOpened") == 0
    assert page.evaluate("window.fixtureState.submitClicked") == 0
    assert writes == []


def test_wrong_request_is_blocked_before_network(interaction_page, tmp_path):
    page, writes = interaction_page
    result, receipt, _ = _run(page, tmp_path, mode="wrong-request-id")
    assert result[0] == "FAILED"
    assert writes == []
    assert receipt['blocked_requests'][0]['payload_id'] == 'post-other'


def test_existing_partial_author_text_is_not_success(interaction_page, tmp_path):
    page, writes = interaction_page
    page.evaluate("""text => document.querySelector('[data-object-id="post-target"]').addEventListener('click', () => {
      const node=document.createElement('div'); node.dataset.commentId='existing'; node.dataset.authorRole='author';
      node.textContent=text; document.querySelector('[data-comment-list]').append(node);
    })""", COMMENT[:5])
    result, _, _ = _run(page, tmp_path, verify_only=True)
    assert result[0] == 'SKIPPED_EXISTS'
    assert writes == []


def test_live_author_readback_requires_scoped_id_and_complete_text(interaction_page):
    from video_processing.interaction.browser_commenter import _read_live_author_comments
    page, _ = interaction_page
    page.locator('#detail-host').evaluate("""(el, text) => { el.innerHTML='<div class="comment-main-content"><div class="comment-row"><div class="comment-author-bandage">作者</div></div><div class="comment-row"><span class="comment-content"></span></div></div>';el.querySelector('.comment-content').textContent=text; }""", COMMENT)
    normalized = ' '.join(COMMENT.split())
    records = [{'platform_post_id':'other','comment_id':'wrong','content':normalized},
               {'platform_post_id':'target','comment_id':'right','content':normalized}]
    assert _read_live_author_comments(page, records, 'target') == [{'comment_id':'right','text':normalized}]
    assert _read_live_author_comments(page, records, 'missing') == []
    records[1]['content'] = normalized[:5]
    assert _read_live_author_comments(page, records, 'target') == []


def test_scene_id_requires_unique_full_published_description():
    from video_processing.interaction.browser_commenter import _interaction_post_id
    text = '完整发布文案用于唯一作品绑定和验证，不能用截断前缀替代完整的内容身份。'
    assert _interaction_post_id('canonical', text, {'scene':text}) == ('scene','unique_exact_published_description')
    for descriptions in ({'scene':text+'不同尾部'}, {'a':text,'b':text}):
        with pytest.raises(ValueError):
            _interaction_post_id('canonical',text,descriptions)


def test_pin_uses_only_target_author_container(interaction_page, tmp_path):
    page, _ = interaction_page
    page.locator('#detail-host').evaluate("""(el, text) => {
      el.innerHTML='<div data-author-role="viewer" data-pinned="true">观众</div><div data-author-role="author"><span></span><button data-action="pin">置顶</button></div>';
      const author=el.querySelector('[data-author-role="author"]');author.querySelector('span').textContent=text;
      author.querySelector('button').onclick=()=>author.dataset.pinned='true';
    }""", COMMENT)
    commenter = BrowserCommenter(state_path=tmp_path/'state.json',dom_timeout_ms=300)
    assert commenter._ensure_comment_pinned(page,page.locator('#detail-host'),' '.join(COMMENT.split())) is True
    assert page.locator('[data-author-role="author"]').get_attribute('data-pinned') == 'true'


def _navigation_page(
    chromium, *, home_ready=True, comment_ready=True, login_redirect=False, auto_comment=False, post_schema_ready=True,
):
    """模拟菜单先出现、首页稍后初始化并覆写路由的真实 SPA 顺序。"""
    page = chromium.new_page()
    writes = []
    options = json.dumps({"home": home_ready, "comment": comment_ready, "login": login_redirect, "auto": auto_comment})
    html = """<html><head><meta charset="utf-8"></head><body>
      <a href="#" id="interaction">互动管理</a>
      <a href="#" style="display:none">互动管理</a>
      <a href="#" id="comment" hidden>评论</a>
      <div id="surface">首页加载中</div>
      <script>
      const options = OPTIONS;
      window.earlyClicks = 0;
      window.ready = false;
      if (options.home) setTimeout(() => {
        window.ready = true;
        document.querySelector('#surface').textContent = '最近视频';
        history.replaceState({}, '', '/platform');
      }, 150);
      document.querySelector('#interaction').onclick = event => {
        event.preventDefault();
        if (!window.ready) { window.earlyClicks++; return; }
        document.querySelector('#comment').hidden = false;
        if (options.auto) startComment();
      };
      function startComment() {
        history.pushState({}, '', options.login ? '/platform/login.html' : '/platform/interaction/comment');
        document.querySelector('#surface').textContent = '评论加载中';
        if (options.comment && !options.login) setTimeout(() => {
          fetch('/micro/interaction/cgi-bin/mmfinderassistant-bin/post/post_list').then(() => {
            document.querySelector('#surface').innerHTML = '<div class="comment-feed-wrap">唯一目标</div>';
          });
        }, 200);
      }
      document.querySelector('#comment').onclick = event => {
        event.preventDefault();
        startComment();
      };
      </script></body></html>""".replace("OPTIONS", options)

    def handler(route):
        if route.request.method != "GET":
            writes.append(route.request.method)
        if route.request.url.endswith('/post/post_list'):
            route.fulfill(status=201, json={"data": {"list": [{"exportId": "comment-scene", "desc": "目标完整发布文案"}]}} if post_schema_ready else {"unknown": True})
            return
        route.fulfill(content_type="text/html", body=html if route.request.is_navigation_request() else "")

    page.route("**/*", handler)
    return page, writes


@pytest.mark.parametrize('auto_comment', [False, True])
def test_navigation_waits_for_initialized_home_and_rendered_comment_cards(chromium, tmp_path, auto_comment):
    from video_processing.interaction.browser_commenter import _capture_comment_posts
    page, writes = _navigation_page(chromium, auto_comment=auto_comment)
    resets = []
    ids, descriptions = ['stale'], {'stale': '首页文案'}
    seen = []

    def capture(response):
        seen.append((response.url, response.status))
        _capture_comment_posts(response, ids, descriptions)

    page.on('response', capture)

    def reset():
        resets.append(page.url)
        ids.clear()
        descriptions.clear()

    commenter = BrowserCommenter(state_path=tmp_path / 'unused.json', page_ready_timeout_ms=1500, poll_interval_ms=20)
    try:
        error = commenter._open_comment_page(page, reset, post_list_ready=lambda: bool(ids and descriptions))
        assert error is None
        assert page.evaluate('window.earlyClicks') == 0
        assert resets == ['https://channels.weixin.qq.com/platform']
        assert page.locator('.comment-feed-wrap:visible').count() == 1
        assert ids == ['comment-scene'], seen
        assert descriptions == {'comment-scene': '目标完整发布文案'}
        assert writes == []
    finally:
        page.close()


def test_visible_cards_without_valid_scene_snapshot_still_fail_closed(chromium, tmp_path):
    from video_processing.interaction.browser_commenter import _capture_comment_posts
    page, writes = _navigation_page(chromium, post_schema_ready=False)
    ids, descriptions = [], {}
    page.on('response', lambda response: _capture_comment_posts(response, ids, descriptions))
    commenter = BrowserCommenter(state_path=tmp_path / 'unused.json', page_ready_timeout_ms=500, poll_interval_ms=20)
    try:
        error = commenter._open_comment_page(page, lambda: None, post_list_ready=lambda: bool(ids and descriptions))
        assert '评论管理页未就绪 (PAGE_UNREADY)' in error
        assert page.locator('.comment-feed-wrap:visible').count() == 1
        assert ids == []
        assert writes == []
    finally:
        page.close()


@pytest.mark.parametrize(("home_ready", "comment_ready", "login_redirect", "reason", "reset_count"), [
    (False, True, False, '首页初始化未就绪 (PAGE_UNREADY)', 0),
    (True, False, False, '评论管理页未就绪 (PAGE_UNREADY)', 1),
    (True, True, True, '评论管理页未就绪 (LOGIN_REQUIRED)', 1),
])
def test_navigation_unready_or_login_never_reaches_target_resolution(
    chromium, tmp_path, home_ready, comment_ready, login_redirect, reason, reset_count,
):
    page, writes = _navigation_page(
        chromium, home_ready=home_ready, comment_ready=comment_ready, login_redirect=login_redirect,
    )
    resets = []
    commenter = BrowserCommenter(state_path=tmp_path / 'unused.json', page_ready_timeout_ms=500, poll_interval_ms=20)
    try:
        error = commenter._open_comment_page(page, lambda: resets.append(True), post_list_ready=lambda: True)
        assert reason in error
        assert len(resets) == reset_count
        assert page.locator('.comment-feed-wrap:visible').count() == 0
        assert page.evaluate('window.earlyClicks') == 0
        assert writes == []
    finally:
        page.close()
