"""本机配置中心：预览、受控编辑、CAS审计回滚与执行者实际加载状态。

# Modification History
| reply-linkage-v1 | 2026-10-25 | Codex | 每日额度联动与持久手动覆盖；校验实际检查节拍。 |
| reply-recovery-v1 | 2026-10-25 | Codex | 提取共用本机写入权限边界，保持原配置中心校验。 |
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| runtime-center-v1 | 2026-10-24 | Codex | 复用本机真实对端/会话/CSRF边界，放宽超批准基线无普通批准接口。 |
| runtime-center-v1.1 | 2026-10-24 | Codex | 回复时段显示下一次开放下界，并与额度门禁取较晚值；不改变允许时段。 |
"""
from __future__ import annotations
import datetime as dt
import json
import secrets
import threading
import time
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel,ConfigDict,Field
from config.settings import settings
from config.runtime_policy import ConfigurationConflict,ConfigurationError,ConfigurationUnavailable
from video_processing.utils.runtime_configuration import store,snapshot,approved_validation,recompute_waits
from video_processing.utils.configuration_catalog import catalog

class PreviewBody(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    expected_revision:str=Field(pattern='^[a-f0-9]{64}$')
    domains:dict|None=None
    rollback_version:str|None=None
    reason:str=Field(min_length=3,max_length=200)


class RecommendationBody(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    config:dict


class ApplyBody(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    preview_id:str=Field(pattern='^[a-f0-9]{32}$')
    operation_id:str=Field(pattern='^[a-zA-Z0-9_-]{16,80}$')


def differences(before,after,prefix=''):
    out=[]
    for key in sorted(set(before)|set(after)):
        path=(prefix+'.' if prefix else '')+key
        a,b=before.get(key),after.get(key)
        if isinstance(a,dict) and isinstance(b,dict):out.extend(differences(a,b,path))
        elif a!=b:out.append({'field':path,'before':a,'after':b})
    return out


def reply_window_blocker(now,start,end):
    """已知时段门禁有确定的下一开放下界，不能冒充无限期阻塞。"""
    from video_processing.utils.secondary_reply_policy import is_within_shanghai_window
    if is_within_shanghai_window(now.strftime('%H:%M'),start,end):
        return None
    hour,minute=map(int,start.split(':'))
    days,hour=divmod(hour,24)
    opening=now.replace(hour=hour,minute=minute,second=0,microsecond=0)+dt.timedelta(days=days)
    if opening<=now:opening+=dt.timedelta(days=1)
    return {'code':'REPLY_TIME_WINDOW','reason':'当前不在既有回复时段内；下一次开放 '+start+'（北京时间）','until':opening.timestamp()}


def blocking_until(blockers):
    if not blockers or any(b['until'] is None for b in blockers):return None
    return max(b['until'] for b in blockers)


def worker_state(current):
    records=[];directory=settings.default_output_dir/'runtime_config_workers'
    for role in ['dashboard','ready-worker','secondary-reply']:
        path=directory/(role+'.json')
        try:
            row=json.loads(path.read_text())
            fresh=time.time()-row['acknowledged_at']<=12
            row['state']='已加载' if fresh and row.get('loaded_revision')==current.revision else '待加载' if fresh else '失联或已停止'
            if role=='secondary-reply' and row.get('lifecycle')=='STOPPED':
                row['state']='最近定时运行已采用；下次运行再核验' if row.get('loaded_revision')==current.revision else '下次定时运行待加载'
        except (OSError,ValueError,KeyError):
            row={'role':role,'state':'尚无加载确认','loaded_revision':None}
        records.append(row)
    from video_processing.core.wechat_session_lock import inspect_wechat_session_lock
    owner=inspect_wechat_session_lock(settings.default_output_dir/'wechat_state.json')
    active=({'purpose':owner.owner.get('stage'),'pid':owner.owner.get('pid'),
             'active_attempt_revision':owner.owner.get('active_attempt_revision'),
             'started_at':owner.owner.get('started_at')} if owner.locked else None)
    return {'workers':records,'active_attempt':active,'target_seconds':5,
            'meaning':'下一次准入核验活动版本；在线等待5秒内重算。未确认的执行者不显示已加载，在途采用原快照。'}


def gates(db):
    from video_processing.core.wechat_request_guard import WeChatRequestGuard
    from video_processing.utils.secondary_reply_policy import sync_secondary_reply_settings
    guard=WeChatRequestGuard(settings.default_output_dir/'wechat_state.json')
    views={}
    for op,purpose in [('publish','发布'),('first_comment','首评'),('reply','回复'),('comment_scan','评论扫描'),('post_match','作品匹配'),('keepalive','保活')]:
        info=guard.evaluate(purpose=purpose,account_only=True)
        views[op]={key:info.get(key) for key in ['allowed','blockers','until','sessions_24h_count','sessions_1h_count','daily_limit','hourly_limit','interval_seconds']}
    waits=[]
    for row in db.runtime_configuration_waits()[:50]:
        info=guard.evaluate(purpose='首评',task=row['platform_post_id'])
        waits.append({'id':row['id'],'operation':'首评','blockers':info['blockers'],'until':info['until'],
                      'next_attempt_at':row['next_attempt_at'],'known_gate_lower_bound_only':True})
    sync_secondary_reply_settings()
    reply=views['reply']
    if not settings.enable_wechat_secondary_reply:
        reply['blockers'].append({'code':'REPLY_FEATURE_DISABLED','reason':'观众留言自动回复未启用','until':None})
    if not settings.enable_wechat_secondary_reply_live_submission:
        reply['blockers'].append({'code':'REPLY_SENDING_DISABLED','reason':'观众留言实际发送未启用','until':None})
    from zoneinfo import ZoneInfo
    window=reply_window_blocker(dt.datetime.now(ZoneInfo('Asia/Shanghai')),settings.wechat_reply_window_start_shanghai,settings.wechat_reply_window_end_shanghai)
    if window:reply['blockers'].append(window)
    if reply['blockers']:
        reply['allowed']=False
        reply['until']=blocking_until(reply['blockers'])
    return {'operations':views,'waits':waits,
            'additional_gates':[{'name':'观众回复功能','value':'已启用' if settings.enable_wechat_secondary_reply else '关闭（配额不是启用授权）'},
                                {'name':'观众回复实际发送','value':'已启用' if settings.enable_wechat_secondary_reply_live_submission else '关闭'},
                                {'name':'回复时段（北京时间）','value':settings.wechat_reply_window_start_shanghai+'–'+settings.wechat_reply_window_end_shanghai},
                                {'name':'回复审批','value':settings.wechat_reply_approval_mode},
                                {'name':'账号浏览器','value':'同一账号串行；正在执行不中断'},
                                {'name':'提交不确定','value':'UNKNOWN/UNCERTAIN不重发'},
                                {'name':'发布状态轮询','value':'禁止；配置中心不访问平台'},
                                {'name':'其他任务资格','value':'内容审查、原授权、暂停、商品合同、产物完整性仍分别核验'}],
            'meaning':'时间仅是已知门禁的最早下界，不保证有空闲浏览器或满足其他任务资格。'}


def create_runtime_configuration_router(db, *, port):
    router=APIRouter(); previews={};mutex=threading.Lock()

    from .local_runtime_access import create_runtime_access
    boundary, authorized, page_response = create_runtime_access(db, port)

    def call(action):
        try:return action()
        except ConfigurationConflict as exc:raise HTTPException(409,str(exc)) from exc
        except ConfigurationUnavailable as exc:raise HTTPException(503,str(exc)) from exc
        except (ConfigurationError,ValueError) as exc:raise HTTPException(422,str(exc)) from exc
        except (OSError,KeyError,TypeError) as exc:raise HTTPException(503,'配置或本地状态不可读取；草稿保留，不要重复提交') from exc

    @router.get('/runtime-configuration',response_class=HTMLResponse,dependencies=[Depends(boundary)])
    def page(request:Request):
        content=(Path(__file__).parent/'templates/runtime_configuration.html').read_text()
        return page_response(request, content)

    @router.get('/api/runtime-configuration/current')
    def current(actor=Depends(authorized)):
        def action():
            current=snapshot(fresh=True)
            if current is None:raise ConfigurationError('配置中心尚未显式迁移启用；当前只允许旧入口，不自动创建新基线')
            from video_processing.utils.reply_linked_policy import capacity_view, editor_config
            return {'revision':current.revision,'version':current.version,'domains':current.domains(),'catalog':catalog(current),
                    'reply_capacity':capacity_view(editor_config(current.domains())),
                    'reply_editor':{'schema_version':1, 'max_per_video':current.domains()['wechat_operations']['operations']['reply']['max_replies_per_video_lifetime'], **editor_config(current.domains())},
                    'access':{'role':'本机运营编辑','relaxation_approval_available':False,'restriction':'超批准边界需专门批准与受控更新；客户端不能自称风险审批人'},
                    **worker_state(current)}
        return call(action)

    @router.get('/api/runtime-configuration/state')
    def state(actor=Depends(authorized)):
        return call(lambda:{'revision':snapshot(fresh=True).revision,**worker_state(snapshot(fresh=True)),**gates(db)})

    @router.get('/api/runtime-configuration/history')
    def history(actor=Depends(authorized)):
        return call(lambda:{'versions':[{'revision':s.revision,**s.manifest} for s in store().history(limit=30)],'limit':30})

    @router.post('/api/runtime-configuration/reply-recommend')
    def reply_recommend(body:RecommendationBody, actor=Depends(authorized)):
        def action():
            from video_processing.utils.secondary_reply_policy import parse_editor_policy
            from video_processing.utils.reply_linked_policy import recommend
            config, capacity = recommend(parse_editor_policy(body.config))
            return {'config':config,'capacity':capacity}
        return call(action)

    @router.post('/api/runtime-configuration/preview')
    def preview(body:PreviewBody,actor=Depends(authorized)):
        def action():
            current=snapshot(fresh=True)
            if current.revision!=body.expected_revision:raise ConfigurationConflict('配置版本已变化；草稿保留，请重新载入')
            if (body.domains is None)==(body.rollback_version is None):raise ConfigurationError('选择编辑草稿或回滚版本其中一种')
            domains=body.domains if body.domains is not None else store().version(body.rollback_version).domains()
            if body.domains is not None:
                from video_processing.utils.reply_linked_policy import normalize_domains
                domains=normalize_domains(domains)
            allowed=True;approval=None
            try:approved_validation(domains)
            except (ConfigurationError,ValueError) as exc:allowed=False;approval=str(exc)
            changes=differences(current.domains(),domains)
            if not changes:allowed=False;approval='没有参数差异'
            local=gates(db)
            proposed={}
            if allowed:
                from video_processing.core.wechat_request_guard import WeChatRequestGuard
                from video_processing.core.wechat_account_schedule import _evaluate_operations
                account=WeChatRequestGuard(settings.default_output_dir/'wechat_state.json').snapshot()
                now=time.time()
                for op,purpose in [('publish','发布'),('first_comment','首评'),('reply','回复'),('comment_scan','评论扫描'),('post_match','作品匹配'),('keepalive','保活')]:
                    info=_evaluate_operations(account,now,purpose,'',domains['wechat_operations'],account_only=True)
                    proposed[op]={k:info.get(k) for k in ['allowed','blockers','until','sessions_24h_count','sessions_1h_count','daily_limit','hourly_limit']}
            from video_processing.utils.reply_linked_policy import capacity_view, editor_config
            try:reply_capacity=capacity_view(editor_config(domains))
            except ValueError:reply_capacity={'insufficient':None,'message':'参数未通过校验，无法估算容量。'}
            report={'reply_capacity':reply_capacity,'preview_id':secrets.token_hex(16),'expires_at':time.time()+120,'expected_revision':current.revision,
                    'changes':changes,'can_apply':allowed,'approval_required':not allowed,'message':approval,
                    'risk':'R3：需要专门批准' if not allowed else 'R2：批准范围内调整；保留历史事实',
                    'waiting_tasks':len(db.runtime_configuration_waits()),'in_flight':worker_state(current)['active_attempt'],
                    'current_operations':local['operations'],
                    'proposed_operations':proposed,
                    'effects':['下一次准入采用新值；在线等待5秒内重算','在途动作不中断；提交前安全校验保留','额度、重试次数、提交意图和UNKNOWN记录均不清零']}
            if any(c['field']=='interaction_controls.automatic_replies_enabled' for c in changes):
                report['effects'].append('观众回复按既有 '+settings.wechat_reply_window_start_shanghai+'–'+settings.wechat_reply_window_end_shanghai+'（北京时间）及 '+settings.wechat_reply_approval_mode+' 审批规则执行；不扩大到全天、不按额度强凑发送数量')
            with mutex:
                for k in list(previews):
                    if previews[k]['report']['expires_at']<time.time():del previews[k]
                previews[report['preview_id']]={'actor':actor,'body':body,'domains':domains,'report':report}
            return report
        return call(action)

    @router.post('/api/runtime-configuration/apply')
    def apply(body:ApplyBody,actor=Depends(authorized)):
        def action():
            with mutex:prepared=previews.get(body.preview_id)
            if not prepared or prepared['actor']!=actor:raise ConfigurationConflict('预览不存在或会话已变化，请重新预览')
            report=prepared['report']
            if report['expires_at']<time.time():raise ConfigurationConflict('预览已过期，请重新预览；草稿保留')
            if not report['can_apply']:raise ConfigurationError('没有可执行的批准范围；普通确认不能代替专门批准')
            saved=store().commit(prepared['domains'],expected_revision=report['expected_revision'],actor=actor,
                                 reason=prepared['body'].reason,operation_id=body.operation_id,validate=approved_validation,
                                 rollback_of=prepared['body'].rollback_version)
            recomputed=None;error=None
            try:recomputed=recompute_waits(db,saved)
            except Exception as exc:error=type(exc).__name__
            return {'saved':True,'revision':saved.revision,'version':saved.version,'waiting_recomputed':recomputed,
                    'recompute_error':error,**worker_state(saved)}
        return call(action)

    return router
