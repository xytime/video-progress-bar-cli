"""唯一官方搜索适配器和现有审查规则适配；无抓取或付费模型兜底。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-11 | Codex | 官方搜索/详情总超时、脱敏错误；仅显式请求读取 API 配置 |
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

from ..core.topic_candidates import TopicError, stamp


class SearchFailure(TopicError):
    def __init__(self, code, message, *, retryable=False):
        super().__init__(code, message, 503)
        self.retryable = retryable


class YouTubeTopicSearch:
    def __init__(self, settings):
        self.settings = settings

    def configured(self):
        return bool(self.settings.youtube_data_api_key)

    async def _get(self, endpoint, params, timeout):
        import httpx
        key = self.settings.youtube_data_api_key
        if not key:
            raise SearchFailure("NO_API", "未配置 YouTube 官方 API")
        # API key 放请求头；请求 URL、错误及作业账本均不含密钥。
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False) as client:
                response = await asyncio.wait_for(client.get(
                    "https://www.googleapis.com/youtube/v3/" + endpoint,
                    params=params, headers={"X-Goog-Api-Key": key}), timeout)
            if response.status_code != 200:
                try:
                    error = response.json().get("error", {})
                    reasons = {entry.get("reason") for entry in error.get("errors", []) if isinstance(entry, dict)}
                except (ValueError, AttributeError, TypeError):
                    reasons = set()
                if reasons & {"quotaExceeded", "dailyLimitExceeded"}:
                    code, message = "API_QUOTA", "官方项目配额已耗尽"
                elif response.status_code == 401 or "keyInvalid" in reasons:
                    code, message = "API_CREDENTIALS", "官方凭据无效，请由管理员核实"
                elif response.status_code == 429:
                    code, message = "API_RATE_LIMIT", "官方请求受到限流"
                elif response.status_code == 403:
                    code, message = "API_ACCESS", "官方 API 访问受限，请由管理员核实"
                else:
                    code, message = "API_ERROR", "官方 API 暂不可用"
                raise SearchFailure(code, message, retryable=response.status_code >= 500)
            if len(response.content) > 2_000_000:
                raise SearchFailure("INVALID_RESPONSE", "官方响应过大")
            value = response.json()
            if not isinstance(value, dict) or not isinstance(value.get("items"), list):
                raise SearchFailure("INVALID_RESPONSE", "官方响应资料不足")
            return value["items"]
        except (httpx.HTTPError, TimeoutError) as exc:
            raise SearchFailure("NETWORK", "官方请求失败或超时", retryable=True) from exc
        except ValueError as exc:
            raise SearchFailure("INVALID_RESPONSE", "官方响应无法读取") from exc

    def search(self, topic, now, timeout):
        return asyncio.run(self._get("search", dict(part="snippet", type="video", order="date",
            safeSearch="strict", relevanceLanguage="en", maxResults=25, q=topic["query"],
            publishedAfter=stamp(now - timedelta(days=topic["lookback_days"])),
            publishedBefore=stamp(now)), timeout))

    def details(self, ids, timeout):
        return asyncio.run(self._get("videos", dict(part="snippet,contentDetails,statistics,status", id=",".join(ids)), timeout))


class ExistingTopicRules:
    def version(self):
        from ..censor_engine import current_rules_fingerprint
        return current_rules_fingerprint()

    def check(self, meta):
        from ..censor_engine import check_text, check_channel_policy
        text = meta["title"] + "\n" + meta["description"]
        for result in (check_text(zh_text=text, en_text=text), check_channel_policy(zh_text=text, en_text=text)):
            if result.hit:
                return " / ".join(filter(None, (result.level, result.tag))) or "现有内容规则受限"
        return None
