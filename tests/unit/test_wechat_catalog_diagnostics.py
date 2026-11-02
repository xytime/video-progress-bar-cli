"""诊断脱敏、字段白名单和发布/采集浏览器参数契约。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-02 | Codex | 凭证 canary 不落诊断；保留 path 与公共计数，启动参数不跨调用污染。 |
"""
import json
import pytest
from video_processing.utils.wechat_catalog_diagnostics import public_text, public_path, sanitized_snapshot, timed_phase
from video_processing.core.wechat_browser_context import wechat_launch_options


@pytest.mark.parametrize('value', [
    'Cookie: session=PRIVATE_CANARY; second=PRIVATE_CANARY',
    'Authorization: Bearer PRIVATE_CANARY', 'token=PRIVATE_CANARY',
    'access_token:PRIVATE_CANARY', 'password=PRIVATE_CANARY', 'Bearer PRIVATE_CANARY',
    '{"token":"PRIVATE_CANARY"}', 'Cookie:\nsid=PRIVATE_CANARY\nother=PRIVATE_CANARY',
    '//channels.weixin.qq.com/path?q=PRIVATE_CANARY#PRIVATE_CANARY',
    '提示 https://channels.weixin.qq.com/platform/post/create?token=PRIVATE_CANARY#PRIVATE_CANARY',
])
def test_public_text_redacts_before_truncation(value):
    assert 'PRIVATE_CANARY' not in public_text(value)
    assert len(public_text('说明'*500)) <= 160


def test_diagnostic_whitelist_drops_unknown_keys_and_query():
    raw={'state':'LOADING', 'headers':['库存','token=PRIVATE_CANARY'],
         'cookie':'PRIVATE_CANARY', 'html':'PRIVATE_CANARY',
         'hints':['https://channels.weixin.qq.com/path?q=PRIVATE_CANARY'],
         'pagination_nodes':[{'selector':'.pagination-wrap','count':1,'texts':['共 14 件']}],
         'scope_account_nodes':[{'selector':'[data-finder-username]','count':0,'value':'PRIVATE_CANARY'}]}
    result=sanitized_snapshot(raw)
    assert 'PRIVATE_CANARY' not in json.dumps(result)
    assert result['headers'][0]=='库存'
    assert result['pagination_nodes'][0]['texts']==['共 14 件']
    assert public_path('https://channels.weixin.qq.com/platform/post/create?token=PRIVATE_CANARY#fragment')=='/platform/post/create'


def test_failed_phase_still_has_elapsed_time():
    diagnostics={}; ticks=iter((10,12))
    with pytest.raises(ValueError):
        with timed_phase(diagnostics,'navigation',lambda: next(ticks)):
            raise ValueError('synthetic')
    assert diagnostics=={'last_phase':'navigation','timings_seconds':{'navigation':2}}


def test_launch_profile_preserves_publisher_arguments_and_headed_mode():
    options=wechat_launch_options(headless=False)
    assert options['headless'] is False
    assert options['args']==['--disable-web-security','--no-sandbox',
        '--disable-blink-features=AutomationControlled','--disable-infobars',
        '--window-size=1280,800','--disable-accelerated-2d-canvas','--no-proxy-server',
        '--host-resolver-rules=MAP localhost.weixin.qq.com 127.0.0.1']
    options['args'].clear()
    assert wechat_launch_options(headless=True)['args']
