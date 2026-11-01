"""真实字幕快照/ASS/成片摘要验证恢复证明；不访问模型或平台。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 覆盖普通字幕失败进入封面、损坏/旧证据及非字幕/提交保护。 |
"""
from dataclasses import replace
import json
from pathlib import Path
import time
import uuid

import pytest

from config.settings import settings
from video_processing.core.runtime_probe import enrich_task_facts_with_runtime
from video_processing.funnel_diagnosis import TaskUnitFacts, RuntimeEnvironmentFacts, diagnose_task_unit
from video_processing.utils import caption_checkpoints as contract_module
from video_processing.utils.caption_checkpoints import CaptionCheckpoints, fingerprint
from video_processing.utils.caption_completion_evidence import read_caption_completion
from video_processing.utils.render_source_binding import digest
from video_processing.utils.subtitle_failure_receipt import (
    begin_subtitle_render, finish_subtitle_render, caption_checkpoint_ass_comment, write_success_receipt,
)


@pytest.fixture
def artifacts(tmp_path):
    prefix='CatuGloDkTQ';source=tmp_path/'original_video'/f'{prefix}.mp4'
    source.parent.mkdir();source.write_bytes(b'source media')
    output=tmp_path/f'{prefix}_vertical.mp4';output.write_bytes(b'rendered media')
    segments=[dict(start=0,end=1,text='Bonds are stable.',zh_text='债券稳定。')]
    store=CaptionCheckpoints(source,{'model':'fixture'})
    translation=dict(version=contract_module.VERSION,methods='e'*64,
        modules={name:digest(Path(contract_module.__file__).with_name(name+'.py'))
                 for name in contract_module.TRANSLATION_MODULES},
        config={name:getattr(settings,name,None) for name in contract_module.TRANSLATION_SETTINGS})
    contract=dict(asr_sha256=fingerprint(segments),translation=translation)
    store.save('asr',store.identity['asr'],segments,'en')
    store.save('translation',contract,segments,'en',segments)
    checkpoint=store.directory/'translation.json'
    completion=dict(input_sha256=digest(source),asr_sha256=fingerprint(segments),
        contract_sha256=fingerprint(contract),checkpoint_path=str(checkpoint),checkpoint_sha256=digest(checkpoint))
    ass=source.with_suffix('.ass');ass.write_text(caption_checkpoint_ass_comment(completion)+'\n')
    begin_subtitle_render(output,source,ass,completion);finish_subtitle_render(output,source,ass)
    receipt_dir=tmp_path/'subtitle_recovery'/prefix;receipt_dir.mkdir(parents=True)
    receipt=receipt_dir/(uuid.uuid4().hex+'.json')
    raw=write_success_receipt(receipt,receipt.stem,source,completion)
    failed=time.time()-60
    task=TaskUnitFacts(video_id=7031,youtube_id=prefix,status='AI_COVER_PENDING',failed_epoch=failed,
        failure_events=({'reason':'cli.commands.auto_caption: 具名故障版式对白或时间轴变化，需要重新复核',
                         'failed_epoch':failed},))
    return dict(root=tmp_path,prefix=prefix,source=source,output=output,ass=ass,checkpoint=checkpoint,
                asr=store.directory/'asr.json',receipt=receipt,task=task,failed=failed)


def diagnosis(artifacts, task=None):
    task=enrich_task_facts_with_runtime(task or artifacts['task'],artifacts['root'])
    return diagnose_task_unit(task,RuntimeEnvironmentFacts(now_epoch=time.time(),now_bj_iso='fixture'))


def test_real_bound_caption_completion_resolves_only_technical_failure(artifacts):
    proof=read_caption_completion(artifacts['root'],artifacts['prefix'],artifacts['failed'])
    assert proof and proof['output_sha256']==digest(artifacts['output'])
    diag=diagnosis(artifacts)
    assert diag.is_recovered and not diag.unresolved
    assert diag.cause_code=='RECOVERED_PENDING_DELIVERY'
    assert diag.delivery_state=='IN_PREPARATION'


@pytest.mark.parametrize('damage',['source','output','ass','checkpoint','asr','receipt','intent',
                                 'rendering','old','future','wrong_source','wrong_contract','symlink'])
def test_incomplete_old_replaced_or_wrong_evidence_does_not_clear_failure(artifacts,damage):
    if damage in ('source','output','ass','checkpoint','asr'):
        artifacts[damage].write_bytes(b'changed')
    elif damage=='receipt':artifacts['receipt'].unlink()
    else:
        path=artifacts['output'].with_name(artifacts['output'].name+'.subtitle-quality.json') if damage in ('intent','rendering') else artifacts['receipt']
        raw=json.loads(path.read_text())
        if damage=='intent':path.unlink()
        elif damage=='rendering':raw['state']='RENDERING';path.write_text(json.dumps(raw))
        elif damage=='symlink':
            copy=path.with_suffix('.saved');path.rename(copy);path.symlink_to(copy)
        else:
            key,value={'old':('created_at',artifacts['failed']-1),
                       'future':('created_at',time.time()+60),
                       'wrong_source':('input_sha256','0'*64),
                       'wrong_contract':('contract_sha256','0'*64)}[damage]
            raw[key]=value;path.write_text(json.dumps(raw))
    diag=diagnosis(artifacts)
    assert diag.unresolved and not diag.is_recovered


@pytest.mark.parametrize('reason',['cover generator failed','wechat_uploader failed',
                                  'cli.commands.auto_caption then wechat_uploader failed'])
def test_caption_completion_does_not_clear_later_stage_failures(artifacts,reason):
    task=replace(artifacts['task'],failure_events=({'reason':reason,'failed_epoch':artifacts['failed']},))
    assert diagnosis(artifacts,task).unresolved


@pytest.mark.parametrize('change',[{'status':'UNCERTAIN'},{'publication_review_required':True},
                                  {'subtitle_recovery':{'state':'NEEDS_REPAIR'}},
                                  {'submission_attempts':({'state':'INTENT'},)}])
def test_existing_policy_submission_and_repair_guards_remain_authoritative(artifacts,change):
    diag=diagnosis(artifacts,replace(artifacts['task'],**change))
    assert diag.unresolved and not diag.is_recovered


def test_completion_before_newest_failure_is_not_recovery(artifacts):
    task=replace(artifacts['task'],failed_epoch=time.time()+1,
        failure_events=artifacts['task'].failure_events+({'reason':'cli.commands.auto_caption: new failure',
                                                       'failed_epoch':time.time()+1},))
    assert diagnosis(artifacts,task).unresolved
