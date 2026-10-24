"""英语卡商品清理失败沿用写入重试预算：合成账本，无平台访问。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| cleanup-timeout-v1 | 2026-10-24 | Codex | 三次技术失败闭锁、旧链不可增额、与其他技术重试合并计数，不清零原事实。 |
"""
import json
from pathlib import Path
from tests.unit.test_wechat_operations_policy import active
from tests.unit.test_english_world_delivery_reliability import _package
from video_processing.db.database import PipelineDB


def attempt_cleanup_failure(db,item,tmp_path,index,reason='PRODUCT_CLEANUP_BUDGET_EXHAUSTED'):
    evidence=tmp_path/('cleanup-'+str(index));evidence.mkdir()
    claim=db.claim_english_world_submission(item['id'],evidence_dir=str(evidence))
    assert claim is not None
    assert db.defer_english_world_product_wait(item['id'],attempt_id=claim['_attempt_id'],evidence_dir=str(evidence),
        receipt={'required':True,'binding_confirmed':False,'state':'BLOCKED','task_id':'synthetic-task','config_digest':'synthetic-digest'},
        wait_evidence={'not_submitted':True,'submission_state':'NOT_SUBMITTED','task_key':'synthetic-task','config_digest':'synthetic-digest','reason':reason})


def test_cleanup_failures_stop_at_three_and_survive_restart(active,tmp_path):
    db,item=_package(tmp_path);db.approve_english_world_submission(item['id'],authorization='AUTO_POLICY')
    for i in range(3):
        assert db.get_next_auto_approved_english_world_submission()['id']==item['id']
        attempt_cleanup_failure(db,item,tmp_path,i)
    assert db.get_next_auto_approved_english_world_submission() is None
    assert db.claim_english_world_submission(item['id'],evidence_dir=str(tmp_path/'forbidden-fourth')) is None
    restored=PipelineDB(db.db_path)
    assert restored.get_next_auto_approved_english_world_submission() is None
    with restored.get_connection() as conn:
        assert conn.execute('SELECT count(*) FROM english_world_submission_attempts WHERE review_id=?',(item['id'],)).fetchone()[0]==3
        assert conn.execute("SELECT initial_max_retries FROM wechat_write_retry_chains WHERE kind='english_world' AND task_id=?",(item['id'],)).fetchone()[0]==2
    assert restored.get_english_world_review_item(item['id'])['state']=='SUBMISSION_APPROVED'


def test_raising_config_does_not_expand_existing_cleanup_chain(active,tmp_path):
    policy,path=active;policy['retry_policies']['write_actions']['max_retries']=1;path.write_text(json.dumps(policy))
    db,item=_package(tmp_path);db.approve_english_world_submission(item['id'],authorization='AUTO_POLICY')
    attempt_cleanup_failure(db,item,tmp_path,0)
    policy['retry_policies']['write_actions']['max_retries']=2;path.write_text(json.dumps(policy))
    attempt_cleanup_failure(db,item,tmp_path,1)
    assert db.get_next_auto_approved_english_world_submission() is None
    assert db.claim_english_world_submission(item['id']) is None


def test_cleanup_and_other_technical_failures_share_one_budget(active,tmp_path):
    db,item=_package(tmp_path);db.approve_english_world_submission(item['id'],authorization='AUTO_POLICY')
    attempt_cleanup_failure(db,item,tmp_path,0)
    # 合成另一条已证明未提交的技术故障事实；不能另开一份2次重试预算。
    with db.get_connection() as conn:
        conn.execute("UPDATE wechat_write_retry_chains SET failure_count=1 WHERE kind='english_world' AND task_id=?",(item['id'],))
    attempt_cleanup_failure(db,item,tmp_path,1,reason='PRODUCT_CLEANUP_OPERATION_TIMEOUT')
    assert db.get_next_auto_approved_english_world_submission() is None
    assert db.claim_english_world_submission(item['id']) is None


def test_business_availability_wait_not_misclassified_as_technical_retry(active,tmp_path):
    db,item=_package(tmp_path);db.approve_english_world_submission(item['id'],authorization='AUTO_POLICY')
    for i in range(3):attempt_cleanup_failure(db,item,tmp_path,i,reason='PRODUCT_UNAVAILABLE')
    assert db.get_next_auto_approved_english_world_submission()['id']==item['id']
