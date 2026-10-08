"""独立 B 投稿入口的实际内容闸门验收。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-09 | Codex | 验证内容命中时不领取上传意图或签发浏览器票据 |
| 1.0.1 | 2026-10-09 | Codex | 验证待授权字幕策划不调用服务且不改变 A 的发布状态 |
"""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from config.settings import settings
from video_processing.db.database import PipelineDB
from video_processing.db.wallstreet_experiment import CHANNEL_ID
from video_processing.utils.insight_v2_prompt import FEW_SHOT_EXAMPLE_CORNELL


def test_content_hit_cannot_enter_browser_submission(tmp_path,monkeypatch):
    path=Path('scripts/run_wallstreet_ab.py')
    spec=importlib.util.spec_from_file_location('wallstreet_worker_entry',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    db=PipelineDB(str(tmp_path/'db.sqlite'))
    db.add_video('abcdefghijk','已指定',CHANNEL_ID,score=80)
    pair=db.enroll_wallstreet_video('abcdefghijk',b_only=True)
    package={'files':{}}
    for key in ('video','a_video','original','subtitle','title','copy','cover','cover_provenance','script'):
        asset=tmp_path/(key+'.txt')
        asset.write_text(json.dumps(FEW_SHOT_EXAMPLE_CORNELL) if key=='script' else key)
        package[key]=str(asset);package['files'][key]=module.sha256(asset)
    job=db.claim_wallstreet_render()
    db.finish_wallstreet_render(pair['id'],job['lease_token'],package=package)
    monkeypatch.setattr(type(settings),'default_output_dir',property(lambda _:tmp_path))
    monkeypatch.setattr(settings,'wechat_publishing_paused',False)
    monkeypatch.setattr(settings,'enable_censorship_engine',True)
    monkeypatch.setattr(settings,'enable_channel_policy_filter',False)
    monkeypatch.setattr(module,'validate_dedicated_cover_file',lambda *a:True)
    monkeypatch.setattr(module,'valid_enrichment',lambda *a,**k:True)
    from video_processing import censor_engine
    monkeypatch.setattr(censor_engine,'check_text',lambda *a:SimpleNamespace(hit=True))
    module.submit_ready(db)
    assert {p['state'] for p in db.get_wallstreet_publications()}=={'WAITING'}
    assert all(p['attempt_count']==0 for p in db.get_wallstreet_publications())
    assert not (tmp_path/'submissions').exists()
    assert json.loads((tmp_path/'content-review.json').read_text())['blocked'] is True


def test_unapproved_remote_planning_keeps_a_and_never_calls_provider(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('wallstreet_planning_gate', Path('scripts/run_wallstreet_ab.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    db = PipelineDB(str(tmp_path/'db.sqlite'))
    db.set_wallstreet_experiment(active=True)
    db.add_video('abcdefghijk', '车贷观察', CHANNEL_ID, score=80)
    pair = db.enroll_wallstreet_video('abcdefghijk', mark_ready=True)
    monkeypatch.setattr(type(settings), 'default_output_dir', property(lambda _: tmp_path))
    monkeypatch.setattr(settings, 'wallstreet_ab_remote_planning_authorized', False)
    monkeypatch.setattr(module, 'resolve_inputs', lambda _: (tmp_path/'original.mp4', tmp_path/'subtitle.ass'))
    calls = []
    monkeypatch.setattr(module, 'generate_insight_script', lambda *a, **kw: calls.append(a))
    with pytest.raises(ValueError, match='REMOTE_PLANNING_APPROVAL_PENDING'):
        module.build_package(db, pair)
    assert calls == []
    assert db.get_video_by_youtube_id('abcdefghijk')['status'] == 'PENDING'
    assert all(p['attempt_count'] == 0 for p in db.get_wallstreet_publications())
