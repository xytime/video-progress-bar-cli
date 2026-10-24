"""已批准发布策略：无限日额仍有间隔，英语选品失败仅在实读清空后继续。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| english-preferred-v1 | 2026-10-25 | Codex | 增加默认兜底后仍核验首选商品及未知清理闭锁。 |
| 1.0.0 | 2026-10-25 | Codex | 验证无限日额仍防重，以及英语世界正向清空证据链。 |
"""
import copy
import json
import time
import pytest
from tests.unit.test_wechat_operations_policy import active, state, event
from tests.unit.test_wechat_product_attachment_v2 import EmptyPicker, product_fixture
from video_processing.core.wechat_account_schedule import evaluate, admission
from video_processing.core.wechat_product_policy import ProductLookup
from video_processing.db.database import PipelineDB
from video_processing.utils.wechat_operations_policy import validate
from video_processing.utils.wechat_product_task import freeze_task_product_decision
from video_processing.utils.wechat_product_execution import execute_product_task, finalize_product_before_submit
from scripts.submit_english_world_review import _english_world_uploader_command, _product_receipt_is_confirmed


def test_unlimited_publish_keeps_usage_interval_other_pools_and_submission_protection(active):
    policy,_=active;now=time.time()
    row=state([event(now-400-i,'publish') for i in range(250)])
    before=copy.deepcopy(row)
    info=evaluate(row,now,'发布','new')
    assert info['allowed'] and info['sessions_24h_count']==250 and info['daily_limit'] is None
    assert row==before
    assert admission(row,now,'发布','new',consume=True)==''
    assert len(row['schedule']['sessions'])==251
    assert not evaluate(row,now+179,'发布','next')['allowed']
    assert evaluate(row,now+180,'发布','next')['allowed']
    row['schedule']['submit_intents']={'protected.mp4':now}
    assert not evaluate(row,now+180,'发布','protected.mp4')['allowed']
    row['blocked_until']=now+600
    assert not evaluate(row,now+180,'发布','next',bypass_cooldown=True)['allowed']
    for op in ['first_comment','reply','post_match','keepalive']:
        broken=copy.deepcopy(policy);broken['operations'][op]['rolling_24h_limit']=None
        with pytest.raises(ValueError):validate(broken)


@pytest.mark.parametrize('failure',['unavailable','unknown_cleanup','residual','not_ready'])
def test_english_optional_attempt_and_final_receipt(tmp_path,failure):
    active_policy=product_fixture(tmp_path)
    db=PipelineDB(str(tmp_path/'test.sqlite'))
    task=freeze_task_product_decision(db,'english:optional',dict(content_type='ENGLISH_WORLD_SHORT',product_intent='AUTO'),active_policy)
    class Picker(EmptyPicker):
        def find(self,product,**kwargs):
            self.targets=getattr(self,'targets',[])+[product]
            return ProductLookup.UNAVAILABLE
        def cancel_and_clear(self,**kwargs):
            if failure=='unknown_cleanup':return False
            if failure=='residual':raise ValueError('unknown residual identity')
            return super().cancel_and_clear(**kwargs)
        def ready_to_submit(self,**kwargs):return failure!='not_ready'
    picker=Picker();evidence=tmp_path/'evidence'
    allowed=execute_product_task(task,picker,evidence,tmp_path/'status')
    assert allowed is (failure=='unavailable')
    assert picker.targets[0].product_id==task['product_decision']['candidates'][0]['product_id']
    assert not _product_receipt_is_confirmed(evidence,task)
    if allowed:
        assert finalize_product_before_submit(task,picker,evidence)
        assert _product_receipt_is_confirmed(evidence,task)
        proof=json.loads((evidence/'product_pre_submit_readback.json').read_text())
        assert proof['state']=='UNBOUND' and proof['binding_required'] is False
        # 最终证据丢失/污染不能用选品阶段的清空回执替代。
        proof['task_id']='another-task'
        (evidence/'product_pre_submit_readback.json').write_text(json.dumps(proof))
        assert not _product_receipt_is_confirmed(evidence,task)
        assert not finalize_product_before_submit(task,picker,evidence,require_bound=True)


def test_english_command_preserves_original_without_forced_product(tmp_path):
    item={key:tmp_path/key for key in ['mp4_path','copy_path','title_path','cover_path','cover_provenance_path']}
    command=_english_world_uploader_command(item,tmp_path/'evidence')
    assert '--require-bound-product' not in command
    assert '--require-original-declaration' in command and '--fail-fast-login' in command
