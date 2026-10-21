"""商品目录合并及异常隔离；夹具不依赖运营配置或真实库存。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-21 | Codex | 目录数量随夹具计算，任意候选编辑以 TED 验证，英语世界固定快捷英语 |
"""
from copy import deepcopy
import json
import pytest

from video_processing.utils.wechat_product_catalog import catalog_view
from tests.unit.test_wechat_product_groups import api_setup, data, TED


def snapshot(products):
    return dict(schema_version=1, captured_at='2026-10-10T15:54:10+08:00',
                source='fixture.html', source_sha256='a'*64, completeness='unverified',
                items=[dict(product_id=p['product_id'], title=p['title'], shop='测试店铺',
                            price='¥10', stock=None) for p in products])


def install_catalog(active, products):
    path = active.with_name('wechat_product_catalog.json')
    path.write_text(json.dumps(snapshot(products)))
    return path


def test_catalog_not_limited_to_three_and_read_does_not_write(api_setup):
    client, active, _, records = api_setup
    records.append(dict(preview_key='video:ted', youtube_id='ted', channel_id=TED,
                        content_type='GENERAL', state='PENDING'))
    original = active.read_bytes()
    old = json.loads(original)
    products = list(old['products'].values()) + [dict(product_id=str(80000000000000+i), title=f'新增书籍 {i}') for i in range(120)]
    install_catalog(active, products)
    result = client.get('/api/product-settings').json()
    assert len(result['catalog']['products']) == len(products)
    assert result['catalog']['live_verified'] is False
    assert result['catalog']['completeness'] == 'unverified'
    assert result['config'] == old and active.read_bytes() == original
    draft = deepcopy(result['config']); draft['products'] = result['catalog']['products']
    draft['profiles']['ted']['candidates'] = ['product_80000000000119']
    response = client.put('/api/product-settings', json={'config':draft,'expected_digest':result['status']['saved_digest']})
    assert response.status_code == 200
    reloaded = client.get('/api/product-settings').json()['config']
    preview = client.post('/api/product-settings/preview', json={'config':reloaded,'video_key':'video:ted'}).json()
    assert preview['candidates'][0]['product_id'] == '80000000000119'
    assert reloaded['profiles']['english_world'] == old['profiles']['english_world']
    assert reloaded['default_candidates'] == old['default_candidates']


def test_partial_keeps_missing_disabled_and_same_title_distinct_ids(tmp_path, data):
    data['products']['news']['enabled'] = False
    rows = [dict(product_id='70001',title='同名图书'), dict(product_id='70002',title='同名图书')]
    path=install_catalog(tmp_path/'policy.json', rows)
    catalog=json.loads(path.read_text());catalog['completeness']='partial';catalog['items'][0]['stock']=0
    path.write_text(json.dumps(catalog))
    result=catalog_view(path,data['products'])
    assert not result['error'] and len(result['products'])==len(data['products']) + len(rows)
    assert result['products']['news']['enabled'] is False
    assert result['items'][0]['stock']==0 and result['items'][1]['stock'] is None


@pytest.mark.parametrize('fault',['broken','empty','duplicate','conflict','stock','time','alias'])
def test_bad_catalog_retains_saved_products(tmp_path,data,fault):
    products=deepcopy(data['products'])
    rows=list(products.values())
    if fault=='alias': products['product_777']=dict(products['news']);rows.append(dict(product_id='777',title='新书'))
    path=install_catalog(tmp_path/'policy.json',rows)
    body=json.loads(path.read_text())
    if fault=='empty':body['items']=[]
    if fault=='duplicate':body['items'].append(body['items'][0])
    if fault=='conflict':body['items'][0]['title']='错误名称'
    if fault=='stock':body['items'][0]['stock']=-1
    if fault=='time':body['captured_at']='2026-10-10'
    path.write_text('{' if fault=='broken' else json.dumps(body))
    result=catalog_view(path,products)
    assert result['error'] and result['products']==products and not result['items']
