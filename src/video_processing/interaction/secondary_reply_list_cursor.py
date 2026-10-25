"""评论作品列表的原生游标续扫；缓存只负责导航，不能提供作品身份证据。

依赖：browser_adapter -> 本模块 -> Python 标准库。调用方持有微信会话锁。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| reply-cursor-v1 | 2026-10-25 | Codex | 保存平台实际返回的游标，按凭据代次和查询隔离，支持跨上下文续扫与定位。 |
"""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
import time
from pathlib import Path


def _key(kind, value):
    normalized = re.sub(r'\s+', ' ', str(value or '')).strip()
    return hashlib.sha256((kind + ':' + normalized).encode()).hexdigest() if normalized else ''


class CommentListCursor:
    TTL = 6 * 3600
    MAX_ITEMS = 2048

    def __init__(self, state_path, generation, query, *, clock=time.time):
        self.path = Path(state_path).with_suffix('.reply-list-cursors.json')
        self.clock = clock
        self.scope = _key('scope', json.dumps([generation, query], sort_keys=True))

    def _read(self):
        try:
            document = json.loads(self.path.read_text())
            if document.get('schema') != 1 or not isinstance(document.get('scopes'), dict):
                return {}
            return {key: row for key, row in document['scopes'].items()
                    if isinstance(row, dict) and isinstance(row.get('updated'), (int, float))
                    and 0 <= self.clock() - row['updated'] < self.TTL}
        except (OSError, ValueError, TypeError, AttributeError):
            return {}

    def _write(self, scopes):
        scopes = dict(sorted(scopes.items(), key=lambda item: item[1]['updated'])[-8:])
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', dir=self.path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                json.dump({'schema': 1, 'scopes': scopes}, handle)
            temporary.replace(self.path)
        except OSError:
            pass  # 导航缓存不可写不改变平台准入或身份校验。
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def start(self, post_id, description):
        """取出真实页游标；消费目标提示，只有再次看到原生条目才恢复提示。"""
        scopes = self._read()
        row = scopes.get(self.scope, {})
        items = row.get('items', {})
        keys = [_key('id', post_id), _key('description', description)]
        points = [items[key] for key in keys if key in items and isinstance(items[key], dict)
                  and isinstance(items[key].get('cursor'), str)
                  and 0 <= self.clock() - items[key].get('seen', 0) < self.TTL]
        if points:
            cursor = max(points, key=lambda point: point['seen'])['cursor']
            for key in keys:
                items.pop(key, None)
            self._write(scopes)
            return cursor, False
        return str(row.get('next') or ''), True

    def observe(self, request_cursor, body, *, advance):
        """仅接收成功的原生列表响应；绝不推算、拼接或制造游标。"""
        if not isinstance(body, dict) or body.get('errCode', 0) != 0:
            self.reset()
            return
        data = body.get('data')
        if not isinstance(data, dict) or not isinstance(data.get('list'), list) or not isinstance(data.get('lastBuff'), str):
            return
        scopes = self._read()
        row = scopes.setdefault(self.scope, {'items': {}, 'next': ''})
        items = row.setdefault('items', {})
        for item in data['list']:
            if not isinstance(item, dict):
                continue
            description = item.get('desc') or ''
            if isinstance(description, dict):
                description = description.get('description') or ''
            for kind, value in [('id', item.get('objectId')), ('id', item.get('exportId')), ('description', description)]:
                key = _key(kind, value)
                if key:
                    items[key] = {'cursor': request_cursor, 'seen': self.clock()}
        row['items'] = dict(sorted(items.items(), key=lambda item: item[1].get('seen', 0))[-self.MAX_ITEMS:])
        if advance:
            row['next'] = data['lastBuff'] if data['list'] else ''
        row['updated'] = self.clock()
        self._write(scopes)

    def reset(self):
        scopes = self._read()
        scopes.pop(self.scope, None)
        self._write(scopes)
