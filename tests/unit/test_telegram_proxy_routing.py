"""验证真实 Telegram 客户端的系统代理路由；不初始化 Bot 或发送网络请求。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0 | 2026-11-01 | Codex | 覆盖请求和独立轮询池的动态代理与原有超时并发设置。 |
"""
import pytest
from config.settings import settings
from bot.telegram_bot import _build_application


@pytest.mark.asyncio
@pytest.mark.parametrize('proxies, expected', [
    ({'HTTPS_PROXY': 'http://127.0.0.1:23451', 'HTTP_PROXY': 'http://127.0.0.1:23452'}, 'http://127.0.0.1:23451'),
    ({'HTTP_PROXY': 'http://127.0.0.1:23452'}, 'http://127.0.0.1:23452'),
    ({}, None),
])
async def test_validated_system_proxy_reaches_both_real_sdk_clients(monkeypatch, proxies, expected):
    def selected(self, *, system_only=False):
        assert system_only is True
        return proxies
    monkeypatch.setattr(type(settings), 'get_active_proxies', selected)
    app = _build_application('123456:isolated-test-token')
    polling, requests = app.bot._request
    try:
        assert polling._client_kwargs['proxy'] == requests._client_kwargs['proxy'] == expected
        assert polling._client_kwargs['limits'].max_connections == 16
        assert requests._client_kwargs['limits'].max_connections == 256
        assert polling._client_kwargs['timeout'].pool == requests._client_kwargs['timeout'].pool == 20
        assert requests._client_kwargs['timeout'].connect == 15
        assert requests._client_kwargs['timeout'].read == 30
        assert requests._client_kwargs['timeout'].write == 60
        assert app.update_processor.max_concurrent_updates == 256
    finally:
        await polling.shutdown()
        await requests.shutdown()


def test_system_only_proxy_ignores_environment_selection_and_checks_endpoint(monkeypatch):
    import socket
    import urllib.request
    observed = []
    class ProbeSocket:
        def settimeout(self, timeout):
            observed.append(('timeout', timeout))
        def connect(self, address):
            observed.append(('connect', address))
        def close(self):
            observed.append(('close',))
    def inherited():
        raise AssertionError('system-only detection must not inherit stale process routing')
    monkeypatch.setattr(urllib.request, 'getproxies', inherited)
    monkeypatch.setattr(urllib.request, 'getproxies_macosx_sysconf',
                        lambda: {'http': 'http://127.0.0.1:23451'}, raising=False)
    monkeypatch.setattr(socket, 'socket', lambda *args: ProbeSocket())
    proxies = settings.get_active_proxies(system_only=True)
    assert proxies == {key: 'http://127.0.0.1:23451' for key in
                       ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy')}
    assert observed == [('timeout', 0.5), ('connect', ('127.0.0.1', 23451)), ('close',)]


@pytest.mark.parametrize('result', [{}, {'http': 'http://unavailable.invalid:23451'}])
def test_system_only_missing_or_unreachable_proxy_cannot_be_claimed(monkeypatch, result):
    import socket
    import urllib.request
    def refused(*args):
        raise OSError('isolated connection refused')
    monkeypatch.setattr(urllib.request, 'getproxies_macosx_sysconf', lambda: result, raising=False)
    monkeypatch.setattr(socket, 'socket', refused)
    assert settings.get_active_proxies(system_only=True) == {}
