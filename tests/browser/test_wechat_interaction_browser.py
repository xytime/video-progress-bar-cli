"""真实隔离 Chromium 中的视频号评论因果绑定验收。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
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
        ("cross-origin-only", "UNCERTAIN"),
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
