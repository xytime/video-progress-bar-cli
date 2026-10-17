"""唯一官方搜索适配器和现有审查规则适配；无抓取或付费模型兜底。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 0.4.0 | 2026-10-13 | Codex | 关键词定时采集、统一评分和受控准入隔离实现 |
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


class SearchItems(list):
    """保留分页覆盖信息，同时兼容已有列表适配器。"""
    def __init__(self, items, has_more=False):
        super().__init__(items)
        self.has_more = has_more


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
            return SearchItems(value["items"], bool(value.get("nextPageToken")))
        except (httpx.HTTPError, TimeoutError) as exc:
            raise SearchFailure("NETWORK", "官方请求失败或超时", retryable=True) from exc
        except ValueError as exc:
            raise SearchFailure("INVALID_RESPONSE", "官方响应无法读取") from exc

    def search(self, topic, now, timeout):
        return asyncio.run(self._get("search", dict(part="snippet", type="video", order="date",
            safeSearch="strict", relevanceLanguage=topic.get("language", "en"), maxResults=25, q=topic["query"],
            publishedAfter=stamp(now - timedelta(days=topic["lookback_days"])),
            publishedBefore=stamp(now)), timeout))

    def details(self, ids, timeout):
        return asyncio.run(self._get("videos", dict(part="snippet,contentDetails,statistics,status", id=",".join(ids)), timeout))


class ExistingTopicRules:
    def version(self):
        from ..censor_engine import current_rules_fingerprint
        return current_rules_fingerprint()

    def check(self, meta):
        from ..censor_engine import check_text, check_channel_policy, matched_excerpt
        text = meta["title"] + "\n" + meta["description"]
        for checker in (check_text, check_channel_policy):
            result = checker(zh_text=text, en_text=text)
            if result.hit:
                sources = []
                for name, label in (("title", "标题"), ("description", "原始描述")):
                    value = meta[name]
                    local = checker(zh_text=value, en_text=value)
                    if local.hit and (local.level, local.matched) == (result.level, result.matched):
                        sources.append(f"{label}「{matched_excerpt(value, result.matched or '')}」")
                if not sources:
                    sources.append(f"标题＋原始描述（跨字段共现）「{matched_excerpt(text, result.matched or '')}」")
                label = "频道内容策略" if result.level == "CP" else (result.tag or "内容审查")
                return (f"{result.level} / {label} · 命中词：{result.matched or '共现规则'} · "
                        f"来源：{'；'.join(sources)} · 规则版本：{self.version()}")
        return None
