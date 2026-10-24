"""英语世界优先挂载与默认兜底的完整冻结、执行及回执边界。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| english-preferred-v1 | 2026-10-25 | Codex | 核验配置默认链、最终绑定、无商品降级及旧冻结原样重放。 |
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts.submit_english_world_review import _product_receipt_is_confirmed
from tests.unit.test_wechat_product_attachment_v2 import EmptyPicker, product_fixture
from video_processing.core.wechat_product_policy import ProductLookup, parse_product_policy
from video_processing.db.database import PipelineDB
from video_processing.utils.wechat_product_execution import execute_product_task, finalize_product_before_submit
from video_processing.utils.wechat_product_task import (
    freeze_task_product_decision, read_product_task_decision, selection_from_task,
    write_product_task_arguments,
)


def test_default_chain_uses_current_configuration_and_deduplicates(tmp_path):
    active=product_fixture(tmp_path)
    data=json.loads(active.read_text())
    data['default_candidates']=['news','default']
    policy=parse_product_policy(data)
    decision=policy.decide(content_type='ENGLISH_WORLD_SHORT')
    assert decision.reason=='ENGLISH_WORLD_PREFERRED'
    assert decision.candidates==tuple(policy.products[k].identity for k in ['kuaijie_english','news','default'])
    assert decision.max_attempts==data['max_attempts'] and decision.timeout_seconds==data['timeout_seconds']
    data['default_candidates']=['kuaijie_english']
    assert len(parse_product_policy(data).decide(content_type='ENGLISH_WORLD_SHORT').candidates)==1
    data['default_candidates']=['news','default'];data['max_attempts']=2
    with pytest.raises(ValueError,match='不可达'):
        parse_product_policy(data)


@pytest.mark.parametrize('outcome',['preferred','default','none','identity_conflict'])
def test_frozen_english_fallback_through_final_receipt(tmp_path,outcome):
    active=product_fixture(tmp_path)
    db=PipelineDB(str(tmp_path/'db.sqlite'))
    task=freeze_task_product_decision(db,'english:new',dict(content_type='ENGLISH_WORLD_SHORT',product_intent='AUTO'),active)
    _,decision=selection_from_task(task)
    preferred,default=decision.candidates
    class Picker(EmptyPicker):
        def __init__(self):super().__init__();self.attempts=[]
        def find(self,product,**kwargs):
            self.attempts.append(product)
            if outcome=='identity_conflict':return ProductLookup.IDENTITY_CONFLICT
            available=preferred if outcome=='preferred' else default if outcome=='default' else None
            return ProductLookup.AVAILABLE if product==available else ProductLookup.UNAVAILABLE
        def select(self,product,**kwargs):self.binding=product
    picker=Picker();evidence=tmp_path/'evidence'
    allowed=execute_product_task(task,picker,evidence,tmp_path/'status')
    receipt=json.loads((evidence/'product_selection_receipt.json').read_text())
    assert allowed
    # 身份冲突不能继续选其他商品；确认清空后仍沿用已有的无商品降级。
    assert picker.attempts==([preferred] if outcome in {'preferred','identity_conflict'} else [preferred,default])
    assert finalize_product_before_submit(task,picker,evidence)
    assert _product_receipt_is_confirmed(evidence,task)
    assert receipt['state']==('BOUND' if outcome in {'preferred','default'} else 'UNBOUND')
    actual=preferred if outcome=='preferred' else default if outcome=='default' else None
    assert receipt['actual_product_id']==(actual.product_id if actual else None)
    if outcome=='default':
        assert receipt['actual_title']==default.title and receipt['fallback_reason']=='TARGET_UNAVAILABLE'
        receipt['actual_product_id']='foreign-product'
        (evidence/'product_selection_receipt.json').write_text(json.dumps(receipt))
        assert not _product_receipt_is_confirmed(evidence,task)
    # 修改活动默认不会回写本任务的冻结身份。
    changed=json.loads(active.read_text());changed['default_candidates']=['news'];active.write_text(json.dumps(changed))
    assert freeze_task_product_decision(db,task['task_id'],task['context'],active)==task
    assert selection_from_task(task)[1]==decision


def test_legacy_frozen_single_candidate_replays_without_expansion(tmp_path):
    active=product_fixture(tmp_path);db=PipelineDB(str(tmp_path/'db.sqlite'))
    current=freeze_task_product_decision(db,'english:new',dict(content_type='ENGLISH_WORLD_SHORT'),active)
    legacy=deepcopy(current)
    legacy.update(task_id='english:legacy',attachment_version='wechat-english-all-v1',reason='ATTACH_ENGLISH_ALL')
    legacy['product_decision']['matched_rule']='ENGLISH_WORLD_REQUIRED'
    legacy['product_decision']['candidates']=legacy['product_decision']['candidates'][:1]
    db.freeze_product_task_decision(legacy['task_id'],legacy)
    assert freeze_task_product_decision(db,legacy['task_id'],{},tmp_path/'missing.json')==legacy
    args=write_product_task_arguments(legacy,tmp_path/'legacy-evidence')
    assert read_product_task_decision(Path(args[1]))==legacy
    assert len(selection_from_task(legacy)[1].candidates)==1
    polluted=deepcopy(legacy)
    polluted['product_decision']['candidates']=current['product_decision']['candidates']
    with pytest.raises(ValueError,match='冻结的选品决定不一致'):
        selection_from_task(polluted)
