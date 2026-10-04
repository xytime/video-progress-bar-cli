"""下载上下文不可在未知原路由下切换出口。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-05 | Codex | 缺失代理组时无 PUT 请求，并验证共享预算上界。 |
"""
import urllib.error
import pytest
from config.settings import Settings


def test_missing_proxy_group_does_not_switch(monkeypatch):
    settings = Settings(_env_file=None, clash_api_secret="test", clash_download_node="target")
    methods = []
    def missing(request, **kwargs):
        methods.append(request.get_method())
        raise urllib.error.HTTPError(request.full_url, 404, "missing", {}, None)
    monkeypatch.setattr("urllib.request.urlopen", missing)
    with settings.clash_switch_node():
        pass
    assert methods == ["GET"]


def test_translation_shared_budget_cannot_reach_watchdog():
    with pytest.raises(ValueError):
        Settings(_env_file=None, subtitle_translation_total_timeout_seconds=720)
