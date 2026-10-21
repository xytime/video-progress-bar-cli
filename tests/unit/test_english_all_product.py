"""所有英语世界强制绑定快捷英语的隔离回归。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-21 | Codex | 覆盖跳过、手选、次序、唯一候选、不可售及最终绑定门禁。 |
"""
import json
from pathlib import Path
import pytest
from video_processing.core.wechat_product_attachment import attachment_decision
from video_processing.core.wechat_product_policy import parse_product_policy,ProductLookup
from video_processing.db.database import PipelineDB
from video_processing.utils.wechat_product_task import freeze_task_product_decision,write_product_task_arguments,read_product_task_decision
from video_processing.utils.wechat_product_execution import execute_product_task,finalize_product_before_submit


def policy(tmp_path):
    data=json.loads((Path(__file__).parents[2]/'config/wechat_products.json').read_text())
    active=tmp_path/'products.json';active.write_text(json.dumps(data))
    return data,active


@pytest.mark.parametrize('intent', ['AUTO','NONE','PRODUCT'])
@pytest.mark.parametrize('first', [True,False])
def test_all_intents_and_production_orders_are_mandatory(intent,first):
    identity = dict(product_id='wrong',product_title='另一件商品') if intent == 'PRODUCT' else {}
    decision=attachment_decision(dict(content_type='ENGLISH_WORLD_SHORT',product_intent=intent,
        **identity,view_count=0,like_count=0),dict(is_first=first))
    assert decision['require_product'] and decision['reason']=='ATTACH_ENGLISH_ALL'
    assert decision['attachment_version']=='wechat-english-all-v1'


def test_only_kuaijie_candidate_and_invalid_profile_stops(tmp_path):
    data,_=policy(tmp_path)
    decision=parse_product_policy(data).decide(content_type='ENGLISH_WORLD_SHORT')
    assert len(decision.candidates)==1
    assert decision.candidates[0].product_id=='10000006971274'
    data['profiles']['english_world']['candidates']=['default']
    with pytest.raises(ValueError):parse_product_policy(data).decide(content_type='ENGLISH_WORLD_SHORT')


@pytest.mark.parametrize('key,value',[('product_id','12345'),('title','另一件书')])
def test_alias_cannot_hide_another_product(tmp_path,key,value):
    data,_=policy(tmp_path)
    data['products']['kuaijie_english'][key]=value
    with pytest.raises(ValueError):parse_product_policy(data).decide(content_type='ENGLISH_WORLD_SHORT')


class Picker:
    def __init__(self,available):self.available=available;self.binding=None
    def read_binding(self,**kwargs):return self.binding
    def find(self,*args,**kwargs):return ProductLookup.AVAILABLE if self.available else ProductLookup.UNAVAILABLE
    def select(self,product,**kwargs):self.binding=product
    def ready_to_submit(self,**kwargs):return True
    def cancel_and_clear(self,**kwargs):self.binding=None;return True


@pytest.mark.parametrize('available',[True,False])
def test_selection_and_final_readback_cannot_downgrade(tmp_path,available):
    _,active=policy(tmp_path)
    database=PipelineDB(str(tmp_path/'db.sqlite'))
    context=dict(content_type='ENGLISH_WORLD_SHORT',product_intent='NONE',youtube_id='youtube1234')
    task=freeze_task_product_decision(database,'english:test',context,active)
    assert task['require_product']
    assert [p['product_id'] for p in task['product_decision']['candidates']]==['10000006971274']
    args=write_product_task_arguments(task,tmp_path/'task')
    assert read_product_task_decision(Path(args[1]))==task
    picker=Picker(available)
    evidence=tmp_path/'e'
    assert execute_product_task(task,picker,evidence,tmp_path/'status') is available
    assert finalize_product_before_submit(task,picker,evidence) is available
    if available:
        picker.binding=None
        assert not finalize_product_before_submit(task,picker,evidence)
    else:
        receipt=json.loads((evidence/'product_selection_receipt.json').read_text())
        assert receipt['state']=='BLOCKED' and receipt['binding_required']
