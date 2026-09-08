"""隔离浏览器验证后台选择、中文状态与请求竞态。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-08 | Codex | 覆盖刷新选择、具名删除确认、状态一致性和过期响应隔离 |
| 1.1.0 | 2026-09-08 | Codex | 共用显式 Chromium 快照夹具；依赖缺失明确失败 |
"""

import pytest

from tests.browser_fixtures import chromium, dashboard, _payload, _video


def _select_first(page):
    page.locator("#batch-normal-view .btn-batch-del").click()
    page.locator('#row-first .row-cb').check()


def _assert_selection(page, ids):
    selected = page.evaluate("""() => ({
        ids: [..._selectedYids],
        checked: [...document.querySelectorAll('#activity-body .row-cb:checked')].map(el => el.dataset.yid),
        highlighted: [...document.querySelectorAll('#activity-body .row-selected')].map(el => el.id.slice(4)),
        count: document.getElementById('batch-selected-count').textContent,
    })""")
    assert selected == {"ids": ids, "checked": ids, "highlighted": ids, "count": str(len(ids))}


def _hold_video_requests(page):
    # 故意不遵守 AbortSignal，让测试同时证明“取消请求”和“拒绝旧响应回写”。
    page.evaluate("""() => {
        const originalFetch = window.fetch;
        window.pendingVideoRequests = [];
        window.fetch = (url, options = {}) => {
            if (new URL(url, location.href).pathname !== '/api/videos') return originalFetch(url, options);
            return new Promise(resolve => pendingVideoRequests.push({url, signal: options.signal,
                finish: (payload, ok = true) => resolve({ok, status: ok ? 200 : 500, json: async () => payload})}));
        };
    }""")


def test_refresh_keeps_visible_selection_and_prunes_missing_rows(dashboard):
    page, state = dashboard
    _select_first(page)
    page.evaluate("async () => { await loadVideos(); }")
    _assert_selection(page, ["first"])
    assert page.locator("#cb-header").evaluate("el => el.indeterminate")
    page.locator("#cb-header").check()
    _assert_selection(page, ["first", "second"])
    state["payload"] = _payload([_video("second")])
    page.evaluate("async () => { await loadVideos(); }")
    _assert_selection(page, ["second"])
    assert page.locator("#cb-header").is_checked()
    state["payload"] = _payload([], total=0)
    page.evaluate("async () => { await loadVideos(); }")
    _assert_selection(page, [])
    assert page.evaluate("Object.keys(_currentVideosMap)") == []
    assert not page.locator("#cb-header").is_checked()
    assert not state["writes"]


@pytest.mark.parametrize("action", [
    "() => changePage(1)",
    "() => { document.getElementById('video-filter-search').value = '新条件'; applyVideoFilters(); }",
    "() => { document.getElementById('video-filter-channel').value = '测试频道'; applyVideoFilters(); }",
    "() => { document.getElementById('video-filter-sort').value = 'score_desc'; applyVideoFilters(); }",
    "() => { document.getElementById('video-filter-score').value = '80_plus'; applyVideoFilters(); }",
    "() => { document.getElementById('video-filter-size').value = '50'; applyVideoFilters(); }",
    "() => switchTab('review')",
])
def test_query_changes_clear_selection_before_response(dashboard, action):
    page, state = dashboard
    _select_first(page)
    _hold_video_requests(page)
    page.evaluate(action)
    _assert_selection(page, [])
    assert page.evaluate("Object.keys(_currentVideosMap)") == []
    assert page.locator("#activity-body .row-cb").count() == 0
    page.evaluate("payload => pendingVideoRequests[0].finish(payload)", state["payload"])
    page.wait_for_function("!document.getElementById('activity-body').hasAttribute('aria-busy')")
    _assert_selection(page, [])


def test_delete_confirmation_names_only_current_checked_videos(dashboard):
    page, state = dashboard
    _select_first(page)
    page.evaluate("async () => { await loadVideos(); _selectedYids.add('invisible-old-id'); }")
    prompts = []

    def confirm(dialog):
        prompts.append(dialog.message)
        dialog.accept("delete")

    page.on("dialog", confirm)
    page.get_by_role("button", name="🗑 删除所选", exact=True).click()
    page.wait_for_function("document.getElementById('batch-selected-count').textContent === '0'")
    assert len(prompts) == 1
    assert "所选 1 条" in prompts[0]
    assert "测试视频 first [first]" in prompts[0]
    assert "second" not in prompts[0] and "invisible-old-id" not in prompts[0]
    assert state["writes"] == [{"method": "DELETE", "path": "/api/videos", "data": {"youtube_ids": ["first"]}}]


def test_delete_rechecks_selection_after_confirmation(dashboard):
    page, state = dashboard
    _select_first(page)
    page.evaluate("""async () => {
        window.prompt = () => { clearSelection(); return 'delete'; };
        await batchDelete();
    }""")
    assert not state["writes"]
    _assert_selection(page, [])


def test_normal_row_click_does_not_create_hidden_selection(dashboard):
    page, _ = dashboard
    page.locator("#row-first .time-cell").click()
    _assert_selection(page, [])


def test_chinese_statuses_match_table_platform_and_details(dashboard):
    page, state = dashboard
    labels = {
        "SUBMITTED_BOUND": "已提交，待确认发布",
        "SUBMITTED_UNBOUND": "本地已受理，待关联作品",
        "REJECTED": "审核未通过", "NOT_FOUND": "平台未找到作品", "CANCELED": "已取消",
        "QUEUED": "排队中", "UPLOADING": "上传中", "UNDER_REVIEW": "审核中",
        "PUBLISHED": "已发布", "COMPLETED": "处理完成", "LOGIN_REQUIRED": "需要登录",
        "NEW_UNMAPPED": "待核验", "__proto__": "待核验",
    }
    state["payload"] = _payload([_video(f"status-{i}", code) for i, code in enumerate(labels)])
    page.locator("#tab-review").click()
    page.locator("#row-status-0").wait_for()
    for i, (code, label) in enumerate(labels.items()):
        row = page.locator(f"#row-status-{i}")
        assert row.locator(".status-cell > .badge").inner_text() == label
        badge = row.locator(".plat-wechat")
        assert f"微信·{label}" in badge.inner_text()
        assert code in badge.get_attribute("title")
        badge.click()
        assert page.locator("#plat-modal-table-body tr").first.locator(".badge").inner_text() == label
        if code.startswith("SUBMITTED_"):
            assert "禁止重发" in page.locator("#plat-modal-table-body").inner_text()
            assert "公开发布证明" in badge.get_attribute("title")
            assert code not in page.locator("#plat-modal-table-body").inner_text()
        page.locator("#platform-detail-modal").get_by_role("button", name="关闭", exact=True).click()
    assert not state["writes"]


def test_platform_display_state_takes_precedence_and_unknown_is_not_unqueued(dashboard):
    page, state = dashboard
    video = _video("platform-overrides", "SUBMITTED_BOUND")
    video["platforms"] = {
        "wechat": {"state": "UNCERTAIN", "display_state": "SUBMITTED_BOUND"},
        "douyin": {},
    }
    state["payload"] = _payload([video])
    page.evaluate("async () => { await loadVideos(); }")
    row = page.locator("#row-platform-overrides")
    assert "已提交，待确认发布" in row.locator(".plat-wechat").inner_text()
    assert "待核验" in row.locator(".plat-douyin").inner_text()
    assert "未入队" in row.locator(".plat-kuaishou").inner_text()
    row.locator(".plat-douyin").click()
    assert page.locator("#plat-modal-table-body tr").last.locator(".badge").inner_text() == "待核验"


@pytest.mark.parametrize("older_ok", [True, False])
def test_old_tab_response_cannot_overwrite_new_tab(dashboard, older_ok):
    page, state = dashboard
    _hold_video_requests(page)
    page.locator("#tab-review").click()
    page.locator("#tab-waitlist").click()
    assert page.evaluate("pendingVideoRequests[0].signal.aborted")
    page.evaluate("payload => pendingVideoRequests[1].finish(payload)", state["payload"])
    page.locator("#row-first").wait_for()
    page.evaluate("args => pendingVideoRequests[0].finish(...args)",
                  [_payload([_video("old-review", "SUBMITTED_BOUND")], total=47), older_ok])
    assert page.locator(".tab-btn.active").get_attribute("id") == "tab-waitlist"
    assert page.evaluate("Object.keys(_currentVideosMap)") == ["first", "second"]
    assert page.locator("#total-count-display").inner_text() == "2"
    assert page.locator("#activity-body .row-cb").count() == 2
    assert page.locator("#row-old-review").count() == 0


def test_hotwords_invalidates_pending_video_requests(dashboard):
    page, state = dashboard
    _hold_video_requests(page)
    page.locator("#tab-review").click()
    page.locator("#tab-hotwords").click()
    assert page.evaluate("pendingVideoRequests[0].signal.aborted")
    page.evaluate("payload => pendingVideoRequests[0].finish(payload)", state["payload"])
    assert page.locator("#hotwords-panel").is_visible()
    assert page.evaluate("Object.keys(_currentVideosMap)") == []
    page.evaluate("async () => { await loadVideos(); }")
    assert page.evaluate("pendingVideoRequests.length") == 1


def test_same_query_latest_refresh_wins_and_query_failure_can_retry(dashboard):
    page, state = dashboard
    _hold_video_requests(page)
    page.evaluate("() => { loadVideos(); loadVideos(); }")
    page.evaluate("payload => pendingVideoRequests[1].finish(payload)", _payload([_video("newest")]))
    page.locator("#row-newest").wait_for()
    page.evaluate("payload => pendingVideoRequests[0].finish(payload)", state["payload"])
    assert page.evaluate("Object.keys(_currentVideosMap)") == ["newest"]
    page.locator("#tab-review").click()
    page.locator("#tab-waitlist").click()
    page.evaluate("() => pendingVideoRequests[3].finish({detail: '测试失败'}, false)")
    page.get_by_text("列表加载失败，请重试刷新。", exact=True).wait_for()
    assert page.evaluate("Object.keys(_currentVideosMap)") == []
    assert len(state["warnings"]) == 1 and "测试失败" in state["warnings"].pop()
    page.evaluate("() => { loadVideos(); }")
    page.evaluate("payload => pendingVideoRequests[4].finish(payload)", state["payload"])
    page.locator("#row-first").wait_for()


def test_missing_channel_stays_filtered_until_user_clears_it(dashboard):
    page, state = dashboard
    page.locator("#video-filter-channel").select_option("测试频道")
    page.wait_for_function("!document.getElementById('activity-body').hasAttribute('aria-busy')")
    state["payload"] = {**_payload([], total=0), "filter_options": {"channels": []}}
    page.evaluate("async () => { await loadVideos(); }")
    assert page.locator("#video-filter-channel").input_value() == "测试频道"
    page.evaluate("async () => { await loadVideos(); }")
    assert state["queries"][-1]["channel"] == ["测试频道"]
    page.locator(".btn-filter-clear").click()
    assert page.locator("#video-filter-channel").input_value() == ""
    assert page.evaluate("filterState.channel") == ""
