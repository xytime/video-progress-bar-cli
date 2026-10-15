"""验证封面来源从冻结文件到投稿/API DTO/Telegram 回执的一致性。

# Modification History
| Version | Date | Author | Description |
| 1.0 | 2026-10-15 | Codex | 验证来源、不变绑定、未知证据和通知失败回执。 |
"""
import hashlib
import json
from types import SimpleNamespace
import pytest
from video_processing.cover_provenance import canonical, freeze_submission, source_path, version
from video_processing.db.database import PipelineDB
from video_processing import telegram_delivery

@pytest.mark.parametrize('source,label', [('antigravity_ai_visual','Antigravity'), ('codex_luna_ai_visual','Codex 接力'), ('deterministic_fallback','默认封面')])
def test_bound_cover_survives_regeneration_and_reconciliation(tmp_path, monkeypatch, source, label):
    db=PipelineDB(str(tmp_path/'db.sqlite'))
    db.add_video('new-cover-test','测试标题','test',score=88)
    cover=tmp_path/'cover.jpg';cover.write_bytes(b'first image')
    value=version(dict(source=source, youtube_id='new-cover-test', slice_index=0,
                       cover_sha256=hashlib.sha256(cover.read_bytes()).hexdigest(), handoff_reason='agy_failed'))
    source_path(cover).write_text(canonical(value))
    db.record_cover_version(value)
    evidence=tmp_path/'attempt1'; frozen=freeze_submission(cover,evidence)
    db.record_wechat_submission_acceptance('new-cover-test',evidence_path=str(evidence),error_message=None,final_title='测试',platform_post_id='post1')
    context=db.get_cover_context('new-cover-test')
    assert context['version_id']==value['version_id']
    assert context['label']==label
    assert context['degraded']==(source=='deterministic_fallback')
    cover.write_bytes(b'new image')
    db.record_cover_version(version(dict(value,version_id=None,cover_sha256=hashlib.sha256(cover.read_bytes()).hexdigest())))
    db.record_wechat_publication_confirmation('new-cover-test', evidence_path=str(tmp_path/'readback'),platform_post_id='post1',state='PUBLISHED')
    assert db.get_cover_context('new-cover-test')==context
    with pytest.raises(ValueError,match='different cover'):
        freeze_submission(cover,evidence)
    captured={}
    def post(url, **kwargs):
        captured.update(kwargs['json'])
        return SimpleNamespace(ok=True,status_code=200,json=lambda:{'ok':True,'result':{'message_id':1}})
    monkeypatch.setattr(telegram_delivery,'_post_with_connect_retry',post)
    result=telegram_delivery.send_text(event_type='test',priority='P1',text='视频号已受理',db=db,cover_context=context,token='test',chat_id='test')
    assert result.state=='ACCEPTED'
    assert label in captured['text'] and value['cover_sha256'] in captured['text']
    with db.get_connection() as conn:
        receipt=conn.execute('SELECT * FROM telegram_notification_receipts').fetchone()
        attempt=conn.execute('SELECT * FROM wechat_submission_attempts').fetchone()
    assert json.loads(receipt['cover_context_json'])==context
    assert attempt['cover_sha256']==value['cover_sha256']
    assert frozen.read_bytes()==b'first image'


def test_missing_or_mismatched_evidence_never_guesses(tmp_path):
    cover=tmp_path/'cover.jpg';cover.write_bytes(b'image')
    source_path(cover).write_text(canonical(version(dict(source='antigravity_ai_visual',cover_sha256='wrong'))))
    freeze_submission(cover,tmp_path/'attempt')
    value=json.loads((tmp_path/'attempt/cover_binding.json').read_text())
    assert value['source']=='unknown'
    (tmp_path/'attempt/submitted_cover.jpg').write_bytes(b'tampered')
    with pytest.raises(ValueError,match='integrity'):
        freeze_submission(cover,tmp_path/'attempt')


def test_transport_failure_preserves_cover_context(tmp_path,monkeypatch):
    db=PipelineDB(str(tmp_path/'db.sqlite'))
    def fail(*args,**kwargs):
        raise telegram_delivery.requests.ReadTimeout()
    monkeypatch.setattr(telegram_delivery,'_post_with_connect_retry',fail)
    context={'source':'unknown','label':'来源未核验'}
    result=telegram_delivery.send_text(event_type='test',priority='P1',text='受理',db=db,cover_context=context,token='test',chat_id='test')
    assert result.state=='UNKNOWN'
    with db.get_connection() as conn:
        receipt=conn.execute('SELECT * FROM telegram_notification_receipts').fetchone()
    assert json.loads(receipt['cover_context_json'])==context


def test_invalid_cover_evidence_cannot_erase_platform_acceptance(tmp_path):
    db=PipelineDB(str(tmp_path/'db.sqlite'))
    db.add_video('accepted-cover','测试','test',score=88)
    evidence=tmp_path/'attempt'; evidence.mkdir()
    (evidence/'cover_binding.json').write_text(canonical(version(dict(source='codex_luna_ai_visual',cover_sha256='bad'))))
    result=db.record_wechat_submission_acceptance('accepted-cover',evidence_path=str(evidence),error_message=None,final_title='测试',platform_post_id='accepted1')
    assert result['publication']['state']=='SUBMITTED_BOUND'
    assert db.get_cover_context('accepted-cover')['source']=='unknown'


def test_uploader_receipt_contains_exact_frozen_version(tmp_path):
    from scripts.wechat_uploader import _write_submission_receipt
    cover=tmp_path/'cover.jpg';cover.write_bytes(b'cover')
    evidence=tmp_path/'submission';freeze_submission(cover,evidence)
    binding=json.loads((evidence/'cover_binding.json').read_text())
    _write_submission_receipt(evidence, {'platform_post_id':'post-new'})
    receipt=json.loads((evidence/'submission_receipt.json').read_text())
    assert receipt['cover_version_id']==binding['version_id']
    assert receipt['cover_sha256']==binding['cover_sha256']
