"""完整 OCR 证据的分页与宿主校验；不调用模型，不授予发布权限。

依赖：router / source_caption_contract -> 本模块 -> 标准库。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-31 | Codex | 全量分组、逐页视觉证明及整段结论一致性校验。 |
"""
CONTRACT = 'caption-visual-pages-v1'
GROUPS_PER_PAGE = 21  # 每次至多 24 张原分辨率图，另外保留首中尾。


def group_rows(rows):
    groups = {}
    for row in rows:
        key = (row['text'], tuple(round(v, 1) for v in row['box']))
        groups.setdefault(key, []).append(row)
    return list(groups.values())


def page_groups(groups):
    return [list(range(start, min(start + GROUPS_PER_PAGE, len(groups))))
            for start in range(0, len(groups), GROUPS_PER_PAGE)]


def validate_page(payload, ids):
    if (type(payload.get('context_clear')) is not bool
            or not isinstance(payload.get('groups'), list)
            or [r.get('group_id') for r in payload['groups']] != ids):
        raise ValueError('VISUAL_PAGE_IDS_INVALID')
    for row in payload['groups']:
        if (type(row['group_id']) is not int
                or row.get('classification') not in {'DIALOGUE_CHINESE', 'NON_DIALOGUE', 'UNCERTAIN'}
                or type(row.get('exact_text')) is not bool
                or not isinstance(row.get('reason'), str) or not row['reason'].strip()):
            raise ValueError('VISUAL_PAGE_INVALID')
    return payload


def verified_ids(groups, pages):
    expected = page_groups(groups)
    if len(pages) != len(expected):
        raise ValueError('VISUAL_PAGES_INCOMPLETE')
    verified = []
    for page, ids in zip(pages, expected):
        validate_page(page, ids)
        if not page['context_clear']:
            raise ValueError('VISUAL_PAGE_UNCERTAIN')
        for audit in page['groups']:
            if (audit['classification'] == 'UNCERTAIN'
                    or (audit['classification'] == 'DIALOGUE_CHINESE' and not audit['exact_text'])):
                raise ValueError('VISUAL_PAGE_UNCERTAIN')
            if audit['classification'] == 'DIALOGUE_CHINESE':
                verified.extend(row['id'] for row in groups[audit['group_id']])
    return verified


def validate_paged_review(review, rows):
    """可重放的全量证明：页不能缺失、重复，ABSENT 不能覆盖已发现的对白中文。"""
    if review.get('review_contract') != CONTRACT:
        raise ValueError('VISUAL_CONTRACT_INVALID')
    groups = group_rows(rows)
    proof = review['visual_page_proof']
    if proof['group_run_ids'] != [[r['id'] for r in group] for group in groups]:
        raise ValueError('VISUAL_GROUP_BINDING_INVALID')
    ids = verified_ids(groups, proof['pages'])
    selected = review.get('run_ids', [])
    if (not isinstance(selected, list) or any(type(i) is not int for i in selected)
            or len(set(selected)) != len(selected)
            or not set(selected).issubset(ids)
            or review.get('visual_verified_run_ids') != ids
            or (review.get('decision') == 'ABSENT' and (ids or selected))):
        raise ValueError('VISUAL_SEMANTIC_CONFLICT')
    return review
