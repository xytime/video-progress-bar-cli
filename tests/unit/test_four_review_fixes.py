"""四项旁路审查回归；合成媒体、真实布局与隔离 DAL，不调用外部供应商。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-03 | Codex | 覆盖长词、投递口径、混合失败与预算、修正转录及复核交接。 |
"""
import ast
from copy import deepcopy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
import time
import uuid

from click.testing import CliRunner
import pysubs2
import pytest

from video_processing.processors import vocabulary_outro as outro
from video_processing.processors import reviewed_caption_sources as reviewed
from video_processing.processors.caption_processor import AutoCaptionProcessor
from video_processing.utils.caption_checkpoints import fingerprint
from video_processing.utils.render_source_binding import digest
from video_processing.utils.subtitle_failure_receipt import (
    SubtitleTranslationFailure, SubtitleReviewRequired, safe_failure,
    read_bound_receipt, write_failure_receipt,
)
from video_processing.utils.subtitle_provider_window import require_single_video_budget, candidate_deadline
from video_processing.utils.translation_model_pool import DynamicTranslationModelPool
from video_processing.db.database import PipelineDB


LONG_TERM = 'relationship between the body and its surrounding space'


def write_ass(path, words):
    subs = pysubs2.SSAFile()
    subs.styles['GlossaryCard'] = pysubs2.SSAStyle()
    for word in words:
        subs.append(pysubs2.SSAEvent(start=0, end=1000, text=f'This is {word}.\\N这是含义'))
        subs.append(pysubs2.SSAEvent(start=0, end=1000, style='GlossaryCard', text=f'词汇  {word} · 含义'))
    subs.save(str(path))
    return path


def test_long_term_filtered_whole_and_short_term_unchanged(tmp_path):
    rejected = []
    path = write_ass(tmp_path/'video.ass', [LONG_TERM, 'cosmic'])
    items = outro.extract_items(path, rejected)
    assert [i['word'] for i in items] == ['cosmic']
    assert items[0]['context_sentence'] == 'This is cosmic.'
    assert rejected == [dict(word=LONG_TERM, start=0, code='term_exceeds_layout')]


def test_all_terms_filtered_produces_observable_empty_receipt(tmp_path, monkeypatch):
    from video_processing.utils import vocabulary_recovery
    source = tmp_path/'video.mp4'; source.write_bytes(b'media')
    ass = write_ass(tmp_path/'video.ass', [LONG_TERM])
    output = tmp_path/'video_vocab.mp4'
    monkeypatch.setattr(outro, 'probe', lambda _: dict(format=dict(duration='2')))
    monkeypatch.setattr(vocabulary_recovery, 'recover_items', lambda *a: [])
    assert outro.build(source, ass, output, '测试', recover_empty=True) == source
    data = json.loads(outro.receipt_path(output).read_text())
    assert data['status'] == 'no_suitable_terms' and data['rejected_items'][0]['word'] == LONG_TERM
    assert outro.valid_empty_receipt(source, ass, output)
    assert source.read_bytes() == b'media' and not output.exists()


def test_uncertain_delivery_counts_without_fabricating_acceptance(tmp_path, monkeypatch):
    db = PipelineDB(str(tmp_path/'pipeline.db'))
    db.add_video('sent', 'title', 'channel', score=80)
    db.record_wechat_publication_confirmation('sent', state='UNCERTAIN',
        evidence_path='/evidence/attempt/submission_attempt.json')
    from video_processing import pipeline_manager as manager_module
    manager = manager_module.PipelineManager.__new__(manager_module.PipelineManager)
    manager.db, manager.telegram_token, manager.telegram_chat_id = db, '', ''
    monkeypatch.setattr(manager_module.settings, 'wechat_publishing_paused', False)
    monkeypatch.setattr(type(manager_module.settings), 'is_public_publish_window', lambda self: True)
    notices = []
    monkeypatch.setattr(manager_module, 'send_telegram_text', lambda **kw: notices.append(kw))
    manager._check_wechat_delivery_health()
    assert not notices
    health = db.read_daily_ops_health(db.db_path)
    assert health['attempted_today'] == 1 and health['hours_since_delivery'] < 4
    assert health['accepted_today'] == health['confirmed_today'] == 0
    with db.get_connection() as c:
        c.execute("UPDATE wechat_publications SET created_at=datetime('now','-5 hours')")
    assert db.read_daily_ops_health(db.db_path)['hours_since_delivery'] >= 5
    manager._check_wechat_delivery_health()
    assert len(notices) == 1 and notices[0]['cooldown_seconds'] == 14400
    db.add_video('unknown', 'title', 'channel', score=80)
    db.record_wechat_publication_confirmation('unknown', state='UNCERTAIN', evidence_path=None)
    assert db.read_daily_ops_health(db.db_path)['hours_since_delivery'] >= 5


def test_mixed_failure_keeps_budget_and_all_quota_defers(tmp_path):
    errors = [safe_failure(p, c) for p,c in [('agy','auth_or_permission'),
        ('codex','translation_budget_exhausted'),('grok','timeout'),('deepseek','network'),
        ('gemini','budget_exhausted'),('google','rate_limit')]]
    error = SubtitleTranslationFailure(errors, exhausted=True)
    assert error.failure['category'] == 'budget' and 'budget' in error.failure['code']
    mixed = SubtitleTranslationFailure([safe_failure('grok', 'network'), safe_failure('google', 'rate_limit')], exhausted=True)
    assert mixed.failure['category'] == 'review' and mixed.failure['retry_at'] == 0
    quota = SubtitleTranslationFailure([safe_failure('google','rate_limit'),
        safe_failure('gemini','429')], exhausted=True)
    assert quota.failure['category'] == 'quota' and quota.failure['retry_at'] > time.time()
    source=tmp_path/'video.mp4';source.write_bytes(b'media')
    quota.binding=dict(input_sha256=digest(source), asr_sha256='b'*64, contract_sha256='c'*64, stage='TRANSLATING')
    receipt=tmp_path/'failure.json'
    payload=write_failure_receipt(receipt,uuid.uuid4().hex,source,quota)
    db=PipelineDB(str(tmp_path/'pipeline.db'));db.add_video('video','title','channel',score=80)
    state=db.record_subtitle_failure('video',0,payload,str(receipt),digest(receipt))
    assert state['state']=='WAITING' and state['next_attempt_at'] >= quota.failure['retry_at']


def test_614_segments_rejected_before_provider_or_audit(tmp_path, monkeypatch):
    (tmp_path/'video.mp4').write_bytes(b'media')
    processor=AutoCaptionProcessor(tmp_path/'video.mp4')
    monkeypatch.setattr(processor, '_start_translation_audit', lambda: pytest.fail('audit started before preflight'))
    with pytest.raises(SubtitleReviewRequired, match='614') as exc:
        processor._translate_segments([dict(text='Bonds matter.') for _ in range(614)])
    assert exc.value.failure['code']=='translation_budget_preflight'
    config=SimpleNamespace(subtitle_provider_budget_allocation_enabled=True,
        codex_subtitle_batch_size=40,codex_text_request_timeout_seconds=120,
        subtitle_translation_total_timeout_seconds=600,subtitle_translation_quality_reserve_seconds=120)
    require_single_video_budget(80,config)


def test_auth_notice_once_and_persistent_timeout_backoff(tmp_path, monkeypatch):
    clock=[10000.]
    monkeypatch.setattr('video_processing.utils.translation_model_pool.time.time',lambda:clock[0])
    path=tmp_path/'pool.json'
    pool=DynamicTranslationModelPool(path)
    assert pool.record_failure('agy','AGY_AUTH_REQUIRED') == clock[0]
    restored=DynamicTranslationModelPool(path)
    assert restored.record_failure('agy','AGY_AUTH_REQUIRED') is None
    assert restored.order(['agy','codex'])==['codex']
    end=candidate_deadline(600, ['codex'],0,now=0,total_seconds=600,quality_seconds=120,fallback_seconds=300)
    assert end==480
    for _ in range(3):
        clock[0]+=400
        restored.record_failure('grok','grok timeout')
    assert restored.snapshot()['grok']['cooldown_until']-clock[0]>=3600
    restored.record_quality('agy',score=90)
    assert restored.record_failure('agy','AGY_AUTH_REQUIRED')==clock[0]


class CorrectedCaption(AutoCaptionProcessor):
    original = [dict(start=i,end=i+.8,text='Bonds matter.') for i in range(9)]
    original[3]['text']='albarrier-lining'
    original[7]['text']=' A multi-organ congestion, apopsis,'
    original[8]['text']='Hematatic'
    fail_binding=False

    def _source_duration(self): return 9.
    def _validate_input(self): pass
    def _extract_audio(self): return None
    def _load_model(self): pass
    def _translate_segments(self, segments):
        self._translation_quality_audit=[]
        for s in segments:s['zh_text']='债券仍然重要。'
        return segments
    def _generate_ass_file(self,segments):
        path=write_ass(self.input_path.with_suffix('.ass'),['cosmic'])
        if self.fail_binding:
            self._subtitle_completion['asr_sha256']='0'*64
        return path
    def _burn_subtitles(self,path):
        self.output_path.write_bytes(b'rendered')
        return self.output_path


@pytest.mark.parametrize('fail_binding',[False,True])
def test_corrected_asr_render_and_binding_failure_cli_78(tmp_path,monkeypatch,fail_binding):
    module=importlib.import_module('cli.commands.auto_caption')
    source=tmp_path/'c4umlxsvAKg.mp4';source.write_bytes(b'synthetic original')
    original=deepcopy(CorrectedCaption.original)
    corrected=deepcopy(original)
    corrected[3]['text']='barrier lining'
    corrected[7]['text']=' It induces multi-organ congestion, apoptosis,'
    corrected[8]['text']='Hemostatic'
    monkeypatch.setitem(reviewed.SOURCES, source.stem, dict(source_sha256=digest(source),
        timeline_sha256=fingerprint(corrected),original_timeline_sha256=fingerprint(original),chinese_only=True))
    class Seeded(CorrectedCaption):
        def _extract_audio(self):
            path=self.input_path.with_suffix('.wav');path.write_bytes(b'audio');return path
        def _transcribe_audio(self,path): self.detected_lang='en';return deepcopy(original)
    monkeypatch.setattr(Seeded,'fail_binding',fail_binding)
    monkeypatch.setattr(module,'AutoCaptionProcessor',Seeded)
    receipt=tmp_path/'receipt.json';attempt=uuid.uuid4().hex;started=time.time()
    result=CliRunner().invoke(module.auto_caption,[str(source),'--output',str(tmp_path/'output.mp4'),
        '--subtitle-receipt',str(receipt),'--subtitle-attempt-id',attempt])
    assert result.exit_code==(78 if fail_binding else 0),result.output
    data=read_bound_receipt(receipt,attempt_id=attempt,input_path=source,input_sha256=digest(source),
                           started_at=started,success=not fail_binding)
    assert data
    asr=next(tmp_path.glob('.caption-checkpoints/*/asr.json'))
    assert json.loads(asr.read_text())['result']['segments']==original
    if fail_binding:
        assert data['category']=='review' and data['code']=='subtitle_checkpoint_binding'
        db=PipelineDB(str(tmp_path/'pipeline.db'));db.add_video(source.stem,'title','channel',score=80)
        state=db.record_subtitle_failure(source.stem,0,data,str(receipt),digest(receipt))
        assert state['state']=='NEEDS_REPAIR'
        video=db.get_video_by_youtube_id(source.stem)
        review=db.get_subtitle_manual_review(video['id'])
        assert db.release_subtitle_recovery_after_repair(video['id'],review['expected_receipt_sha'],actor='tester',reason='fixture')
        db.update_video_status(source.stem,'PROCESSING')
        # A new failed trial must close the previous release, never FAILED + RELEASED.
        data['attempt_id']=uuid.uuid4().hex
        state=db.record_subtitle_failure(source.stem,0,data,str(receipt),digest(receipt))
        assert state['state']=='NEEDS_REPAIR'
        assert not db.get_high_score_pending_videos()


def test_explicit_safety_raises_are_typed():
    root=Path(__file__).resolve().parents[2]/'src/video_processing'
    paths=[*(root/'processors').rglob('*.py'),root/'utils/subtitle_failure_receipt.py']
    violations=[]
    for path in paths:
        source=path.read_text()
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node,ast.Raise) or not isinstance(node.exc,ast.Call):continue
            text=ast.get_source_segment(source,node)
            if any(word in text for word in ('人工','审查','不确定','mismatch','安全修补边界','复核')):
                if not isinstance(node.exc.func,ast.Name) or node.exc.func.id!='SubtitleReviewRequired':
                    violations.append(f'{path.name}:{node.lineno}')
    assert not violations
