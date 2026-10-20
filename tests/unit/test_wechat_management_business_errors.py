"""平台业务错误不能伪装成有效空作品列表。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-20 | Codex | 覆盖真实 -360 限流、外层错误、畸形回执及真实空库存的区分。 |
"""
from types import SimpleNamespace

import pytest
from scripts import wechat_uploader as uploader


@pytest.mark.parametrize("payload,rate_limited", [
    ({"errCode": 0, "data": {"list": [], "baseResp": {"errcode": -360, "errmsg": "操作过于频繁，请稍后再试"}}}, True),
    ({"errCode": 1, "data": {"list": [], "baseResp": {"errcode": 0}}}, False),
    ({"errCode": 0, "data": {"list": [{"objectId": "stale", "desc": "旧缓存"}], "baseResp": {"errcode": -360}}}, True),
    ({"errCode": 0, "data": {"list": [], "baseResp": {"errcode": "0"}}}, False),
    ({"errCode": 0, "data": {"list": [], "baseResp": None}}, False),
    ({"errCode": 0, "data": {}}, False),
])
def test_failed_business_response_never_produces_cards_or_valid_baseline(payload, rate_limited, monkeypatch):
    class Page:
        url = "https://channels.weixin.qq.com/platform/post/list"
        def on(self, event, callback): self.callback = callback
        def remove_listener(self, *args): pass
        def goto(self, *args, **kwargs):
            self.callback(SimpleNamespace(url="https://channels.weixin.qq.com/micro/content/cgi-bin/mmfinderassistant-bin/post/post_list", json=lambda: payload))
        def wait_for_load_state(self, *args, **kwargs): pass
        def wait_for_timeout(self, *args): pass
    monkeypatch.setattr(uploader, "_collect_management_cards", lambda page: {"stale": {"card_text": "作品状态：已发布"}})
    assert uploader._collect_management_cards_from_post_list_payload(payload) == {}
    if rate_limited:
        with pytest.raises(uploader.ManagementListRateLimited):
            uploader._load_management_cards(Page())
    else:
        assert uploader._load_management_cards(Page()) == ({}, False)


def test_real_empty_success_is_distinct_from_rate_limited_empty_list():
    assert uploader._post_list_payload_usable({"errCode": 0, "data": {"list": [], "baseResp": {"errcode": 0}}})
    assert not uploader._post_list_payload_usable({"errCode": 0, "data": {"list": [], "baseResp": {"errcode": -360}}})


def test_rate_limit_stops_readback_without_immediate_retry(tmp_path, monkeypatch):
    import json
    calls = []
    def limited(page):
        calls.append(page)
        raise uploader.ManagementListRateLimited("-360")
    monkeypatch.setattr(uploader, "_load_management_cards", limited)
    monkeypatch.setattr(uploader, "_capture_wechat_evidence", lambda *a: None)
    assert uploader.verify_management_publication_by_id(object(), tmp_path, "native") == (uploader.MANAGEMENT_UNCERTAIN, "")
    assert len(calls) == 1
    assert json.loads((tmp_path / "management_rate_limit.json").read_text())["business_code"] == -360
    assert uploader.resolve_submission_platform_identity_after_publish(object(), {}, "title") is None
    assert len(calls) == 2


def test_rate_limit_does_not_switch_pages_and_repeat_baseline(monkeypatch):
    calls = []
    class Page:
        closed = False
        def close(self): self.closed = True
    secondary = Page()
    context = SimpleNamespace(new_page=lambda: secondary)
    def limited(page):
        calls.append(page)
        raise uploader.ManagementListRateLimited("-360")
    monkeypatch.setattr(uploader, "_load_management_cards", limited)
    with pytest.raises(uploader.ManagementListRateLimited):
        uploader.capture_submission_identity_baseline(context, Page())
    assert calls == [secondary] and secondary.closed
