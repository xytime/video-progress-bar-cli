"""目录导入失败保留可离线复核证据，不能续期旧目录或改变身份校验。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-03 | Codex | 验证失败证据留存与既有身份、滚动校验及旧目录保护。 |
"""
from copy import deepcopy
import json

import pytest

from tests.unit.test_wechat_product_content_match import live, observation
from video_processing.utils import wechat_product_sync as sync
from video_processing.utils.wechat_product_catalog import catalog_digest
from video_processing.utils.wechat_product_config import load_policy
from video_processing.utils.wechat_product_pool import attestation_path, load_live_pool


@pytest.mark.parametrize('fault', ['title_conflict', 'account_conflict', 'scroll_digest'])
def test_rejected_candidate_is_replayable_without_replacing_catalog(live, tmp_path, fault):
    active, doc, _, _ = live
    doc = deepcopy(doc)
    if fault == 'title_conflict':
        doc['pages'][0]['items'][0]['title'] = '同 ID 的另一版本'
    if fault == 'account_conflict':
        doc['account_id'] = 'other-publisher'
    proof = observation(doc)
    if fault == 'scroll_digest':
        proof['completeness_evidence'] = {'kind': 'PUBLIC_DOM_SCROLL_ENUMERATION',
            'rounds': 2, 'steps': 2, 'observed_items': doc['total_items'],
            'identity_digest': 'wrong', 'explicit_total': False,
            'terminal_checks': [{'top': 0, 'height': 10, 'client': 10, 'bottom': True}] * 2}
    paths = [active, active.with_name('wechat_product_catalog.json'), attestation_path(active)]
    before = {p: p.read_bytes() for p in paths}
    output = tmp_path / 'attempt'
    diagnostics = {}
    with pytest.raises(ValueError):
        sync.promote_with_evidence(doc, proof, active, output, diagnostics,
            expected_catalog_digest=catalog_digest(paths[1]),
            expected_policy_digest=load_policy(active).digest)
    assert all(p.read_bytes() == raw for p, raw in before.items())
    saved = json.loads((output / 'candidate.json').read_text())
    assert saved == {'catalog': doc, 'observation': proof}
    error = diagnostics['promotion_error']
    assert error['type'] == 'ValueError' and error['line'] > 0
    assert error['module'] in {'wechat_product_catalog.py', 'wechat_product_pool.py'}
    assert 'message' not in error


def test_valid_candidate_still_passes_strict_promotion(live, tmp_path):
    active, doc, _, _ = live
    result = sync.promote_with_evidence(doc, observation(doc), active, tmp_path/'attempt', {},
        expected_catalog_digest=catalog_digest(active.with_name('wechat_product_catalog.json')),
        expected_policy_digest=load_policy(active).digest)
    assert result['live_verified'] and load_live_pool(active)['ready']
