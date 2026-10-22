"""评论场景作品身份恢复：真实 DAL，完整文案唯一绑定，拒绝歧义和覆盖。"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from video_processing.db.database import PipelineDB
from video_processing.interaction.publication_reconciliation import reconcile_observed_publications

TEXT = '这是已发布视频的完整文案，用于验证原生作品身份恢复；必须逐字匹配且不可仅使用标题。'


def seed(db, root, yid):
    db.add_video(yid, yid, 'channel', score=80)
    (root / (yid + '_copy.txt')).write_text(TEXT)
    return db.record_wechat_publication_confirmation(yid, evidence_path=None, state='SUBMITTED_UNBOUND')


@pytest.mark.parametrize('case,expected', [('unique',1),('partial',0),('duplicate_native',0),('duplicate_local',0)])
def test_unique_full_description_only(tmp_path, case, expected):
    db = PipelineDB(db_path=str(tmp_path / 'db.sqlite'))
    row = seed(db, tmp_path, 'one')
    observed = {'export/one': TEXT}
    if case == 'partial': observed['export/one'] = TEXT[:30]
    if case == 'duplicate_native': observed['export/two'] = TEXT
    if case == 'duplicate_local': seed(db, tmp_path, 'two')
    receipt = tmp_path / 'receipt.json'
    receipt.write_text(json.dumps({'adapter_contract':'wechat-comment-v3-scoped-author-readback', 'observed_posts':observed, 'recorded_at':datetime.now(timezone.utc).isoformat()}))
    recovered = reconcile_observed_publications(db, receipt, tmp_path)
    assert len(recovered) == expected
    if expected:
        current = db.get_commentable_wechat_post_by_platform_id('export/one')
        assert current['publication_id'] == row['id']
        assert current['wechat_state'] == 'SUBMITTED_BOUND'
        assert reconcile_observed_publications(db, receipt, tmp_path) == []
        assert db.bind_observed_wechat_publication(row['id'], 'export/wrong', str(receipt)) is None
        assert db.get_commentable_wechat_post_by_platform_id('export/one') is not None


def test_idle_catalog_recovers_then_throttles_unchanged_misses(tmp_path):
    from video_processing.interaction.publication_reconciliation import recover_idle_publications
    db = PipelineDB(db_path=str(tmp_path / 'idle.sqlite'))
    db.add_video('anchor', 'anchor', 'channel', score=80)
    db.record_wechat_publication_confirmation('anchor', state='SUBMITTED_BOUND',
                                             platform_post_id='export/anchor', evidence_path=None)
    seed(db, tmp_path, 'one')

    class CatalogBrowser:
        calls = 0
        def discover_publications(self, anchor, evidence_dir):
            assert anchor.startswith('export/')
            self.calls += 1
            attempt = evidence_dir / str(self.calls)
            attempt.mkdir(parents=True)
            receipt = attempt / 'receipt.json'
            receipt.write_text(json.dumps({'adapter_contract': 'wechat-comment-catalog-v1',
                                           'recorded_at': datetime.now(timezone.utc).isoformat(),
                                           'observed_posts': {'export/one': TEXT}}))
            return 'CATALOG_OBSERVED', str(receipt), None

    browser = CatalogBrowser()
    assert len(recover_idle_publications(db, browser, tmp_path)) == 1
    assert recover_idle_publications(db, browser, tmp_path) == []
    assert browser.calls == 1
    seed(db, tmp_path, 'ambiguous')
    assert recover_idle_publications(db, browser, tmp_path) == []
    assert browser.calls == 2
    assert recover_idle_publications(db, browser, tmp_path) == []
    assert browser.calls == 2


@pytest.mark.parametrize('age_minutes', [-1, 16])
def test_stale_or_future_receipt_never_binds_new_publication(tmp_path, age_minutes):
    db = PipelineDB(db_path=str(tmp_path / 'fresh.sqlite'))
    seed(db, tmp_path, 'one')
    receipt = tmp_path / 'receipt.json'
    receipt.write_text(json.dumps({
        'adapter_contract': 'wechat-comment-catalog-v1',
        'observed_posts': {'export/one': TEXT},
        'recorded_at': (datetime.now(timezone.utc) - timedelta(minutes=age_minutes)).isoformat(),
    }))
    assert reconcile_observed_publications(db, receipt, tmp_path) == []
    assert db.get_commentable_wechat_post_by_platform_id('export/one') is None
