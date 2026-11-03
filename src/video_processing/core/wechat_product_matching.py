"""商品 L1 相关性：纯函数、稳定排序、无网络和通用商品兜底。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| content-match-v1+default | 2026-11-03 | Grok Bot | 可选 default_products：仅当前有效池内精确 ID+全名商品可作末位兜底；未配置时行为与冻结重放不变。 |
| content-match-v1 | 2026-11-02 | Codex | 新 AUTO 以完整有效商品池和特定主题相关性准入；冻结输入可重放。 |
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata

MATCH_VERSION = 'wechat-product-content-match-v1'
CONTENT_VERSION = 'product-content-evidence-v1'
GENERIC = frozenset({'财经', '教育', '资讯', '新闻', '科技', '图书', '书籍', '人生',
                     '正版', '旗舰店', '推荐', '精选', 'finance', 'news', 'book', 'books', 'ai'})


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def normalize(text):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', str(text or '')).lower()).strip()


def validate_matching_config(data):
    required = {'schema_version', 'enabled', 'min_score', 'themes'}
    if (not isinstance(data, dict) or not required <= set(data) <= required | {'default_products'}
            or type(data['schema_version']) is not int or data['schema_version'] != 1
            or type(data['enabled']) is not bool or type(data['min_score']) is not int
            or not 4 <= data['min_score'] <= 40 or not isinstance(data['themes'], dict)):
        raise ValueError('商品匹配配置格式错误')
    for pid, row in data['themes'].items():
        if (not re.fullmatch(r'[0-9]{1,64}', pid) or not isinstance(row, dict)
                or set(row) != {'title', 'phrases', 'categories'} or not isinstance(row['title'], str)
                or not row['title'].strip()):
            raise ValueError('商品主题须绑定精确 ID 与全名')
        for field in ('phrases', 'categories'):
            values = row[field]
            if not isinstance(values, list) or len(values) > 40 or any(
                    not isinstance(v, str) or not 2 <= len(v.strip()) <= 100 for v in values):
                raise ValueError('商品主题必须是有界短语列表')
        if any(normalize(p) in GENERIC for p in row['phrases']):
            raise ValueError('粗分类或营销词不能作为商品特定主题')
    if 'default_products' in data:
        defaults = data['default_products']
        if not isinstance(defaults, list) or not 1 <= len(defaults) <= 3:
            raise ValueError('默认商品须为 1-3 个精确身份')
        for row in defaults:
            if (not isinstance(row, dict) or set(row) != {'product_id', 'title'}
                    or not isinstance(row['product_id'], str) or not re.fullmatch(r'[0-9]{1,64}', row['product_id'])
                    or not isinstance(row['title'], str) or not row['title'].strip()):
                raise ValueError('默认商品须绑定精确 ID 与全名')
        if len({row['product_id'] for row in defaults}) != len(defaults):
            raise ValueError('默认商品不能重复')
    return data


def _title_phrases(title):
    # 只用可追溯的书名片段；长营销标题没有可靠分隔时不猜测分词。
    pieces = re.split(r'[\s《》【】()（）:：,，/|]+', title)
    return [normalize(p) for p in pieces if 2 <= len(p) <= 18
            and normalize(p) not in GENERIC and not re.search(r'旗舰店|正版|新华|包邮|书籍|专项训练|推荐|精选|畅销', p)]


def _contains(text, phrase):
    if re.fullmatch(r'[a-z0-9 .+\-]+', phrase):
        return bool(re.search(r'(?<![a-z0-9])' + re.escape(phrase) + r'(?![a-z0-9])', text))
    return phrase in text


def rank_products(content, pool, config, *, max_attempts, english=False):
    """分数是规则分；每字段最多两个特定短语，粗分类独立最多一分。"""
    validate_matching_config(config)
    if not pool.get('ready'):
        return {'reason': pool.get('reason') or 'CATALOG_UNVERIFIED', 'candidates': [], 'scores': []}
    fields = {'title': normalize(content.get('title', '')),
              'subtitle': normalize(content.get('subtitle', '')),
              'topics': normalize(' '.join([str(content.get('product_topic') or ''),
                                            *content.get('tags', [])]))}
    category = normalize(content.get('category'))
    scores = []
    for item in pool['eligible']:
        theme = config['themes'].get(item['product_id'], {})
        if theme and theme['title'] != item['title']:
            continue  # 人工标签不能移植到同 ID 的不同标题/版本。
        phrases = sorted(set(_title_phrases(item['title']) + [normalize(p) for p in theme.get('phrases', [])]))
        hits, score = {}, 0
        for name, weight in (('title', 4), ('subtitle', 2), ('topics', 2)):
            found = [p for p in phrases if _contains(fields[name], p)]
            if found:
                hits[name] = found[:8]
                score += weight * min(2, len(found))
        specific = bool(hits)
        if category and category in {normalize(c) for c in theme.get('categories', [])}:
            score += 1
            hits['category'] = [content['category']]
        preferred = bool(english and item['product_id'] == '10000006971274'
                         and item['title'] == '快捷英语 时文阅读理解24-28期 涵盖小升初-高考 提高阅读题型成绩专项训练书')
        scores.append({'product_id': item['product_id'], 'title': item['title'], 'score': score,
                       'specific_theme_hit': specific, 'hits': hits, 'english_preferred': preferred,
                       'qualified': preferred or (specific and score >= config['min_score'])})
    scores.sort(key=lambda r: (not r['english_preferred'], -r['score'], r['product_id'], r['title']))
    candidates = [{'product_id': r['product_id'], 'title': r['title']} for r in scores if r['qualified']][:max_attempts]
    reason = 'MATCH_L1' if candidates else 'MATCH_EMPTY'
    # 默认商品只填剩余尝试位；必须与当前有效池同 ID 同全名，未配置时不改变旧结果。
    eligible = {(p['product_id'], p['title']) for p in pool['eligible']}
    for row in config.get('default_products', []):
        identity = {'product_id': row['product_id'], 'title': row['title']}
        if len(candidates) < max_attempts and (row['product_id'], row['title']) in eligible and identity not in candidates:
            candidates.append(identity)
            reason = 'MATCH_L1' if reason == 'MATCH_L1' else 'MATCH_DEFAULT'
    return {'reason': reason, 'candidates': candidates, 'scores': scores}
