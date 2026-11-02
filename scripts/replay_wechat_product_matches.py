"""离线重放商品相关性；严格当前池与历史假设分栏，不修改任务、策略或目录。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-02 | Codex | 当前池时效口径、原始内容摘要和历史假设独立保存。 |
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from config.settings import settings
from video_processing.core.wechat_product_matching import MATCH_VERSION, digest, rank_products
from video_processing.utils.wechat_product_content_task import dialogue_text, _bounded
from video_processing.utils.wechat_product_pool import matching_config, load_live_pool
from video_processing.utils.wechat_product_catalog import decode_catalog
from video_processing.utils.wechat_product_config import load_policy, atomic_json


def replay(bundle, policy_path, *, historical=False):
    config=matching_config(policy_path)
    if config is None:
        raise ValueError('缺少显式内容匹配配置')
    pool=load_live_pool(policy_path)
    hypothesis=None
    if historical:
        _,catalog=decode_catalog(policy_path.with_name('wechat_product_catalog.json').read_bytes())
        configured=json.loads(load_policy(policy_path).serialized)
        known=list(configured['products'].values())+list(configured.get('library',{}).values())
        eligible=[{'product_id':i['product_id'],'title':i['title']} for i in catalog['items'] if i['stock']!=0
                  and not any(p['product_id']==i['product_id'] and
                              (not p.get('enabled') or p['title']!=i['title']) for p in known)]
        hypothesis={'ready':True,'eligible':eligible,'live_verified':False,
                    'captured_at':catalog['captured_at'],'label':'历史假设：忽略TTL和可售观察，仅解释规则；禁止用于生产或命中率验收'}
    rows=[]
    for row in bundle['rows']:
        raw=row['content'];context=row.get('original_context',{})
        content={'title':raw.get('title') or raw.get('source_title') or '',
                 'subtitle':_bounded(dialogue_text(raw.get('ass',''))), 'tags':raw.get('tags') or [],
                 'category':raw.get('category') or context.get('category'),'product_topic':context.get('product_topic')}
        options={'max_attempts':3,'english':context.get('content_type')=='ENGLISH_WORLD_SHORT'}
        strict=rank_products(content,pool,config,**options)
        rows.append({'task_id':row['task_id'],'title':content['title'], 'original_reason':row.get('original_reason'),
                     'content_digest':digest(content),'sources':row.get('sources'), 'strict_current_pool':strict,
                     'historical_hypothesis':rank_products(content,hypothesis,config,**options) if hypothesis else None})
    return {'schema_version':1,'algorithm_version':MATCH_VERSION,'at':datetime.now(timezone.utc).isoformat(),
            'config_digest':digest(config),'sample_count':len(rows),'current_pool':pool,
            'strict_matched':sum(bool(r['strict_current_pool']['candidates']) for r in rows),
            'strict_reasons':dict(Counter(r['strict_current_pool']['reason'] for r in rows)),
            'historical_hypothesis':hypothesis,'rows':rows,'natural_publication_observation':'待观察，不为补样本发布'}


def main():
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--historical-hypothesis',action='store_true')
    args=parser.parse_args()
    raw=args.input.read_bytes()
    report=replay(json.loads(raw),settings.wechat_product_policy_path,historical=args.historical_hypothesis)
    report['input_sha256']=hashlib.sha256(raw).hexdigest()
    atomic_json(args.output,report)
    print(json.dumps({k:report[k] for k in ('sample_count','strict_matched','strict_reasons','input_sha256')},ensure_ascii=False))


if __name__=='__main__':
    main()
