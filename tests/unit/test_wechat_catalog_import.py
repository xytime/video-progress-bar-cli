"""全量清单导入的边界、CAS、原子性和保留策略验收。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-31 | Codex | 并发 CAS 使用两个预先合法的新增商品清单，避免改名冲突依赖抢锁顺序。 |
"""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
import pytest
from tests.unit.test_wechat_product_groups import api_setup, data
from tests.unit.test_wechat_product_catalog import install_catalog
from video_processing.utils.wechat_product_catalog import catalog_digest, decode_catalog


def document(products):
    items=[dict(product_id=p['product_id'],title=p['title'],shop='真实资料夹具店铺',price='¥20',stock=None) for p in products]
    return dict(schema_version=2,account_id='account-fixture',captured_at='2026-10-11T00:00:00+08:00',source='offline-fixture-export',
                total_pages=2,total_items=len(items),pages=[{'page':1,'items':items[:2]},{'page':2,'items':items[2:]}])


def request_body(client, document):
    state=client.get('/api/product-settings').json()
    return dict(content=json.dumps(document,ensure_ascii=False),expected_catalog_digest=state['catalog']['digest'],
                expected_policy_digest=state['status']['saved_digest'])


@pytest.fixture
def import_setup(api_setup):
    client,active,status,records=api_setup
    products=list(json.loads(active.read_text())['products'].values())
    path=install_catalog(active,products)
    doc=document(products+[dict(product_id='8880001',title='新增完整清单图书')])
    return client,active,path,doc


def test_preview_then_import_updates_catalog_only(import_setup):
    client,active,path,doc=import_setup
    old_policy=active.read_bytes();old_catalog=path.read_bytes();body=request_body(client,doc)
    configured_ids={product['product_id'] for product in json.loads(old_policy)['products'].values()}
    expected_ids=configured_ids|{'8880001'}
    document_ids={item['product_id'] for page in doc['pages'] for item in page['items']}
    assert configured_ids=={'10001054866768','10000028955239','10000129752415','10000006971274'}
    assert '10000006971274' in configured_ids  # 快捷英语商品也必须保留
    assert document_ids==expected_ids
    preview=client.post('/api/product-settings/catalog/preview',json=body)
    preview_result=preview.json()
    assert preview.status_code==200 and preview_result['total_items']==len(expected_ids)==5
    assert {item['product_id'] for item in preview_result['added']}=={'8880001'}
    assert preview_result['account_first_import'] is True
    assert path.read_bytes()==old_catalog and active.read_bytes()==old_policy
    response=client.post('/api/product-settings/catalog/import',json=body)
    assert response.status_code==200
    catalog=client.get('/api/product-settings').json()['catalog']
    assert {item['product_id'] for item in catalog['items']}==expected_ids
    assert len(catalog['items'])==len(expected_ids)==5 and catalog['completeness']=='complete'
    assert catalog['live_verified'] is False and catalog['account_id']=='account-fixture'
    assert 'product_8880001' in catalog['products']
    assert active.read_bytes()==old_policy
    assert client.post('/api/product-settings/catalog/import',json=body).status_code==409


@pytest.mark.parametrize('fault',[ 'missing_page','duplicate_page','wrong_count','duplicate_id','same_id_changed_title',
    'empty','future','older','unknown_field','invalid_stock','bool_page','v1','invalid_json','duplicate_json_key'])
def test_invalid_import_never_replaces_files(import_setup,fault):
    client,active,path,doc=import_setup;old=path.read_bytes();old_policy=active.read_bytes()
    if fault=='missing_page':doc['pages'].pop()
    if fault=='duplicate_page':doc['pages'][1]['page']=1
    if fault=='wrong_count':doc['total_items']+=1
    if fault=='duplicate_id':doc['pages'][1]['items'][1]=doc['pages'][0]['items'][0]
    if fault=='same_id_changed_title':doc['pages'][0]['items'][0]['title']='同 ID 错版本'
    if fault=='empty':doc['pages']=[];doc['total_items']=0;doc['total_pages']=0
    if fault=='future':doc['captured_at']='2999-01-01T00:00:00+08:00'
    if fault=='older':doc['captured_at']='2020-01-01T00:00:00+08:00'
    if fault=='unknown_field':doc['completeness']='complete'
    if fault=='invalid_stock':doc['pages'][0]['items'][0]['stock']=True
    if fault=='bool_page':doc['pages'][0]['page']=True
    if fault=='v1':doc=json.loads(old)
    body=request_body(client,doc)
    if fault=='invalid_json':body['content']='{'
    if fault=='duplicate_json_key':body['content']=body['content'].replace('"schema_version": 2','"schema_version": 2,"schema_version": 2')
    for endpoint in ('preview','import'):
        response=client.post('/api/product-settings/catalog/'+endpoint,json=body)
        assert response.status_code==422,response.text
        assert path.read_bytes()==old and active.read_bytes()==old_policy


def test_account_conflict_and_config_change(import_setup):
    client,active,path,doc=import_setup
    assert client.post('/api/product-settings/catalog/import',json=request_body(client,doc)).status_code==200
    before=path.read_bytes();doc['account_id']='different-account'
    response=client.post('/api/product-settings/catalog/import',json=request_body(client,doc))
    assert response.status_code==422 and '账号' in response.text and path.read_bytes()==before
    doc['account_id']='account-fixture';body=request_body(client,doc)
    data=json.loads(active.read_text());data['version']='operator-changed';active.write_text(json.dumps(data))
    assert client.post('/api/product-settings/catalog/import',json=body).status_code==409
    assert path.read_bytes()==before


def test_disk_failure_and_untrusted_origin(import_setup,monkeypatch):
    from video_processing.utils import wechat_product_catalog
    client,active,path,doc=import_setup;before=path.read_bytes();body=request_body(client,doc)
    assert client.post('/api/product-settings/catalog/import',json=body,headers={'Origin':'https://evil.invalid'}).status_code==403
    def fail(*args,**kwargs):raise OSError('disk fixture failure')
    monkeypatch.setattr(wechat_product_catalog,'atomic_json',fail)
    assert client.post('/api/product-settings/catalog/import',json=body).status_code==503
    assert path.read_bytes()==before


def test_concurrent_import_only_one_wins(import_setup):
    client,active,path,doc=import_setup
    policy_before=active.read_bytes()
    a=request_body(client,doc);second=deepcopy(doc)
    added=next(item for page in second['pages'] for item in page['items'] if item['product_id']=='8880001')
    added['title']='另一批新增商品'
    b=request_body(client,second)
    # 两个请求在同一初始版本都必须合法；修改已有商品名会先被 422 拒绝，测不到 CAS。
    for body in (a,b):
        preview=client.post('/api/product-settings/catalog/preview',json=body)
        assert preview.status_code==200,preview.text
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda body:client.post('/api/product-settings/catalog/import',json=body),[a,b]))
    assert sorted(response.status_code for response in responses)==[200,409]
    winner=next(body for body,response in zip((a,b),responses) if response.status_code==200)
    saved,_=decode_catalog(path.read_bytes())
    assert saved==json.loads(winner['content'])
    assert active.read_bytes()==policy_before


def test_missing_saved_product_is_retained(import_setup):
    client,active,path,doc=import_setup
    pid=doc['pages'][0]['items'].pop()['product_id'];doc['total_items']-=1
    result=client.post('/api/product-settings/catalog/import',json=request_body(client,doc))
    assert result.status_code==200
    assert any(p['product_id']==pid for p in result.json()['import_report']['missing'])
    assert any(p['product_id']==pid for p in result.json()['catalog']['products'].values())


def test_old_complete_label_not_trusted(import_setup):
    client,active,path,doc=import_setup
    old=json.loads(path.read_text());old['completeness']='complete';path.write_text(json.dumps(old))
    assert client.get('/api/product-settings').json()['catalog']['completeness']=='unverified'


def test_name_conflict_in_old_catalog_even_if_not_configured(import_setup):
    client,active,path,doc=import_setup
    assert client.post('/api/product-settings/catalog/import',json=request_body(client,doc)).status_code==200
    doc['pages'][1]['items'][1]['title']='同 ID 不同图书版本'
    assert client.post('/api/product-settings/catalog/import',json=request_body(client,doc)).status_code==422
