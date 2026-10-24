"""配置中心的完整发现目录；只读参数显式列出，不把静态候选冒充生效值。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| runtime-center-v1 | 2026-10-24 | Codex | Settings/领域文件/18组静态候选统一分类；秘密与主机路径不返回值。 |
"""
from __future__ import annotations
import ast
import hashlib
import json
import re
from pathlib import Path
from pydantic_core import PydanticUndefined
from config.settings import settings
from config.runtime_registry import SETTING_FIELDS, TASK_FIELDS, OBSERVABILITY_FIELDS, GROUPS, TASK_DEFAULTS, OBSERVABILITY_DEFAULTS,REPLY_CONTROL_SETTING_NAMES

SECRET = re.compile(r'(token|password|secret|api_key|access_key|credential|private_key|app_id$|user_id$|account_id$|chat_id|admin_ids|proxy|base_url|endpoint|_url$|_path$|_dir$|_root$|_host$|cookie|command|_bin$)',re.I)
FILE_OWNERS = {
 'wechat_operations.json':('视频号六类操作','/runtime-configuration','已迁移；旧文件只作为迁移证据，不再覆盖活动版本'),
 'wechat_scheduler_policy.json':('旧账号调度','/wechat-cooldown-settings','已被分用途预算替代；真实限流恢复仍按安全合同，只读'),
 'secondary_reply_policy.json':('回复时段与审批','/secondary-reply-settings','时段与审批保持现值；旧额度字段不再覆盖独立回复池，变更需专门批准'),
 'wechat_products.json':('商品挂载','/product-settings','专用校验、CAS与版本历史；新任务冻结商品合同，在途不热改'),
 'wechat_product_catalog.json':('商品资料库','/product-settings','专用导入、身份校验与CAS；资料不是实时平台库存'),
 'vocabulary_outro.json':('生词片尾','/vocabulary-outro-settings','专用CAS/草稿；仅尚未开始的片尾步骤采用'),
 'wechat_articles.json':('公众号文章','', '内容身份与版本合同，需专用审阅；本轮只读'),
 'censor_rules.json':('内容安全规则','', '安全底线，需内容安全审阅与部署；普通编辑不可关闭'),
 'dubbing_voice_profiles.json':('译制音色档案','', '内容/音色模板，需专用内容审阅；在途不变'),
}


def group(name):
    for pattern, key in [
        (r'(secret|token|password|key|credential|login|approval|manual)', 'G15'),
        (r'(cooldown|recovery|rate_limit|scheduler_recovery)', 'G17'),
        (r'(douyin|kuaishou|topic_|wallstreet)', 'G18'),
        (r'(cover|ffmpeg|resource)', 'G11'), (r'(log|cache|retention|notification|telegram)', 'G12'),
        (r'(score|like_rate|view_count)', 'G09'), (r'(stock|preparation|production|daily_publish)', 'G10'),
        (r'(download|source_|monitor|discover|youtube)', 'G08'),
        (r'(translation|translate|subtitle.*timeout|batch|request)', 'G07'),
        (r'(browser|headless|playwright)', 'G04'), (r'(scan|reconcile)', 'G03'),
        (r'(english_world|render|audio|duration)', 'G14'), (r'(copy|caption|vocab|dubbing|tts)', 'G13'),
        (r'(lease|ttl|retry|wait)', 'G01'), (r'(queue|interval|scheduler)', 'G02')]:
        if re.search(pattern,name): return key
    return 'G16'


def _display(value):
    if isinstance(value,Path): return '主机路径（不展示）'
    if isinstance(value,str) and ('://' in value or '/Volumes/' in value or '/Users/' in value):
        return '连接或主机资料（不展示）'
    if type(value) in (int,float,bool,str) or value is None:return value
    return '结构化启动参数（只读）'


def catalog(current):
    rows=[];root=settings.project_root
    from config.wechat_operations_schema import APPROVED
    op_names={'publish':'发布','first_comment':'首评','reply':'回复','comment_scan':'评论扫描','post_match':'作品匹配','keepalive':'保活'}
    labels={'rolling_24h_limit':'24小时额度','rolling_1h_limit':'60分钟额度','min_interval_seconds':'流程间隔',
            'max_replies_per_video_lifetime':'每视频累计回复','max_videos_per_run':'每轮视频上限',
            'same_batch_success_cooldown_seconds':'同批查询冷却'}
    for op,fields in APPROVED.items():
        for name,default in fields.items():
            if name=='retry_policy':continue
            seconds=name.endswith('seconds');key='operations.'+op+'.'+name
            rows.append({'id':'wechat_operations:'+key,'name':op_names[op]+'：'+labels[name],'group':'G02',
                'current':current.domains()['wechat_operations']['operations'][op][name],'default':default,
                'source':'活动版本 wechat_operations；旧共享额度不再覆盖','unit':'秒' if seconds else '次/滚动24h' if name=='rolling_24h_limit' else '次/滚动60分钟' if name=='rolling_1h_limit' else '条/视频累计' if name=='max_replies_per_video_lifetime' else '个视频/轮',
                'range':[default,604800] if seconds else [1,default],'mode':'managed','boundary':'下一次准入；等待5秒内重算',
                'reason':'超出用户批准边界需单独批准','path':'src/config/wechat_operations_schema.py','line':None,
                'domain':'wechat_operations','key':key})
    for name,default in [('max_retries',2),('interval_seconds',60)]:
        key='retry_policies.write_actions.'+name
        rows.append({'id':'wechat_operations:'+key,'name':'发送重试：'+name,'group':'G01',
            'current':current.domains()['wechat_operations']['retry_policies']['write_actions'][name],'default':default,
            'source':'活动版本 wechat_operations','unit':'次' if name=='max_retries' else '秒',
            'range':[0,2] if name=='max_retries' else [60,604800],'mode':'managed','boundary':'下一次重试；旧链不可扩容',
            'reason':'超批准边界需单独批准','path':'src/config/wechat_operations_schema.py','line':None,
            'domain':'wechat_operations','key':key})
    tree=ast.parse((root/'src/config/settings.py').read_text())
    lines={n.target.id:n.lineno for n in ast.walk(tree) if isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name)}
    for name,field in type(settings).model_fields.items():
        hidden=bool(SECRET.search(name)); managed=name in SETTING_FIELDS
        raw=object.__getattribute__(settings,'__dict__').get(name)
        default=field.default if field.default is not PydanticUndefined else None
        source=settings.configuration_source(name)
        if name in REPLY_CONTROL_SETTING_NAMES:
            raw=current.domains()['interaction_controls']['automatic_replies_enabled']
            source='活动版本 interaction_controls；统一业务总开关的只读别名'
        spec=SETTING_FIELDS.get(name)
        rows.append({'id':'setting:'+name,'name':spec[0] if spec else name,'group':spec[5] if spec else group(name),
             'current':('已设置（不展示）' if raw else '未设置') if hidden else _display(current.domains()['runtime_settings'][name] if managed else raw),
             'default':None if hidden else _display(default),'source':'活动版本 runtime_settings' if managed else source,
             'unit':spec[1] if spec else '见字段定义；未推断单位','range':[spec[2],spec[3]] if spec else None,
             'mode':'managed' if managed else ('secret' if hidden else 'readonly'),
             'boundary':spec[4] if spec else ('启动/专用领域策略；不声称热加载'),
             'reason':('服务端批准基线内可编辑' if managed else '凭据/主机连接保持启动管理' if hidden else '尚未建立安全热更新适配；保持原值，需重启或专门领域审阅'),
             'path':'src/config/settings.py','line':lines.get(name),'domain':'runtime_settings' if managed else None,'key':name if managed else None})
    rows.append({'id':'interaction_controls:automatic_replies_enabled','name':'观众留言自动回复总开关','group':'G16',
        'current':current.domains()['interaction_controls']['automatic_replies_enabled'],'default':False,
        'source':'活动版本 interaction_controls','unit':'开启/关闭','range':None,'mode':'managed',
        'boundary':'下一次领取立即核验；在线执行者5秒内确认；在途不中断','reason':'保留既有时段、内容审查、原生身份和审批；不开启状态轮询',
        'path':'src/config/runtime_registry.py','line':None,'domain':'interaction_controls','key':'automatic_replies_enabled'})
    for domain, registry in [('task_scheduling',TASK_FIELDS),('observability',OBSERVABILITY_FIELDS)]:
        for name,spec in registry.items():
            rows.append({'id':domain+':'+name,'name':spec[0],'group':spec[5],'current':current.domains()[domain][name],
                         'default':(TASK_DEFAULTS if domain=='task_scheduling' else OBSERVABILITY_DEFAULTS)[name],'source':'活动版本 '+domain,'unit':spec[1],
                         'range':[spec[2],spec[3]],'mode':'managed','boundary':spec[4],
                         'reason':'结构化门禁优先；不改变账号额度','path':'src/config/runtime_registry.py','line':None,
                         'domain':domain,'key':name})
    extra=root/'config/configuration_candidates.json'
    if extra.exists():
        for i,item in enumerate(json.loads(extra.read_text())):
            rows.append({'id':'constant:'+str(i),'name':item['name'],'group':item.get('suggested_review_group') or 'G16',
                         'current':None,'default':item['value'],'source':'代码静态声明；调用方可能覆盖，实际值未知',
                         'unit':'未核定','range':None,'mode':'readonly','boundary':'代码/协议/模板，需逐域审阅',
                         'reason':item['disposition'],'path':item['path'],'line':item['line'],'domain':None,'key':None})
    files=[]
    for path in sorted((root/'config').glob('*.json')):
        if path.name=='configuration_candidates.json':continue
        title,url,reason=FILE_OWNERS.get(path.name,(path.name,'','新发现领域文件，未评审，不开放通用JSON编辑'))
        files.append({'name':path.name,'path':'config/'+path.name,'title':title,'editor':url,'boundary':reason,
                      'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'mode':'domain-editor' if url else 'readonly'})
    files.extend([{'name':'.env','path':'.env','title':'启动与凭据','editor':'','boundary':'只显示字段来源；不读取或返回秘密内容。修改需受控重启','mode':'secret'},
                  {'name':'runtime_configuration/active.json','path':'output/runtime_configuration/active.json','title':'活动版本包','editor':'/runtime-configuration',
                   'boundary':'四领域原子切换；来源与审计由服务端维护','mode':'managed'},
                  {'name':'专题/预筛选数据库配置','path':'DAL领域配置','title':'采集规则与预筛选','editor':'/topic-candidates',
                   'boundary':'专用本机会话、CAS和阶段合同；不从文件编辑恢复搜索或准入','mode':'domain-editor'}])
    return {'fields':rows,'files':files,'groups':[{'id':key,'name':name,'count':sum(r['group']==key for r in rows)} for key,name in GROUPS],
            'coverage':'覆盖全部Settings声明、config目录顶层JSON、18组已核候选；220项静态候选不是220个可编辑运行参数。未穷尽表达式内部常量和第三方平台规则。'}
