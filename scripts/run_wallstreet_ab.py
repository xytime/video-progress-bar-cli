"""华尔街 A/B 执行者：独立成片、独立提交、原生 ID 回读和指标导入。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.1 | 2026-10-21 | Codex | 有可投递成片时历史回查让路，并在领取浏览器锁后再次核实。 |
| 1.1.3 | 2026-10-10 | Codex | 抖音普通 A 已受理但尚无 ID 时只读精确正文取 ID，绝不回查未提交队列。 |
| 1.1.2 | 2026-10-10 | Codex | 明确的上传前登录退出保存尝试证据并冷却重试；未知接受结果不恢复。 |
| 1.1.1 | 2026-10-10 | Codex | 跨会话回读传入原提交回执 nonce，禁止历史无 nonce 作品弱绑定。 |
| 1.1.0 | 2026-10-10 | Codex | 具名补队、普通 A 强回读衔接和抖音原生 ID 字段修复。 |
| 1.0.0 | 2026-10-09 | Codex | 程序化固化 mobile-2 与可恢复配对试验，复用既有平台闸门 |
| 1.0.1 | 2026-10-09 | Codex | 外部字幕策划等待明确授权，本地脚本与普通 A 持续运行 |

| maintenance-v1 | 2026-10-12 | Codex | 接入共用维护准入，保留原业务资格。 |
"""
from __future__ import annotations
import argparse
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from config.settings import settings
from video_processing.db.database import PipelineDB
from video_processing.db.wallstreet_experiment import TEMPLATE, CHANNEL_ID
from video_processing.core.task_lease import TaskLease, TaskLeaseBusy, read_lease_owner
from video_processing.core.insight_script import InsightScriptV2
from video_processing.core.cover_policy import validate_dedicated_cover_file
from video_processing.processors.insight_processor import InsightProcessor, valid_enrichment, sha256
from video_processing.processors.insight_editorial import resolve_inputs
from video_processing.utils.insight_planner import generate_insight_script
from video_processing.utils.subprocess_env import build_subprocess_env
from video_processing.utils.wechat_product_context import video_product_context
from video_processing.utils.wechat_product_task import freeze_task_product_decision, write_product_task_arguments
from video_processing.utils.wechat_product_execution import product_artifacts_digest, product_observation_generation, product_task_preflight, blocked_product_task_keys


from video_processing.core.maintenance_child import run_admitted
from video_processing.core.maintenance import claimed as claim_unit, current, entry, guarded, gate, running, MaintenanceDenied
from video_processing.core.maintenance_runtime import registered

def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary = path.with_suffix('.tmp.json')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)


def payload_hash(package):
    from video_processing.core.douyin_launch_context import douyin_submission_payload_sha256
    value = douyin_submission_payload_sha256(video_path=package['video'],copy_path=package['copy'],
        title_path=package['title'],cover_path=package['cover'],horizontal_cover_path=package['horizontal_cover'])
    if not value:
        raise ValueError('投稿包不完整')
    return value


def content_gate(package):
    from video_processing.censor_engine import check_text, check_channel_policy, current_rules_fingerprint
    script = InsightScriptV2.model_validate_json(Path(package['script']).read_text())
    original = Path(package['subtitle']).read_text()
    text = '\n'.join([script.review_text(),Path(package['title']).read_text(),Path(package['copy']).read_text()])
    findings = []
    if settings.enable_censorship_engine:
        findings.append(check_text(text,original))
    cp_bypass = CHANNEL_ID in settings.censorship_bypass_channel_set
    if settings.enable_channel_policy_filter and not cp_bypass:
        findings.append(check_channel_policy(text,original))
    # 二创新增内容独立审查；不修改 A 的状态、评分或提交账本。
    blocked = any(result.hit for result in findings)
    write_json(Path(package['video']).parent/'content-review.json',
               {'blocked':blocked,'rules':current_rules_fingerprint(),'channel_policy_bypass':cp_bypass,
                'findings':[str(result) for result in findings], 'script_sha256':sha256(Path(package['script']))})
    if blocked:
        raise ValueError('二创新增内容触发现行内容闸门，保留正常 A')


def validate_package(package):
    for key,digest in package['files'].items():
        if sha256(Path(package[key])) != digest:
            raise ValueError('投稿资产在制作后变化：'+key)
    if not validate_dedicated_cover_file(Path(package['cover']),Path(package['cover_provenance'])):
        raise ValueError('二创专门封面来源不合法')
    if not valid_enrichment(Path(package['a_video']),Path(package['script']),Path(package['video']),
                            original_video=Path(package['original']),bilingual_subtitle=Path(package['subtitle'])):
        raise ValueError('母带或完整源片绑定验收失效')
    if sha256(Path(package['video'])) == sha256(Path(package['a_video'])):
        raise ValueError('不能将正常 A 作为 B 重发')
    content_gate(package)


@guarded("wallstreet-package", lambda db, pair: "pair:" + str(pair["id"]))
def build_package(db,pair):
    pair_view = next(p for p in db.get_wallstreet_pairs() if p['id']==pair['id'])
    video = db.get_video_by_youtube_id(pair_view['youtube_id'],slice_index=pair_view['slice_index'])
    inputs = json.loads(pair['inputs_json'])
    prefix = inputs.get('prefix') or video['youtube_id']+(f"_s{video['slice_index']}" if video['slice_index'] else '')
    out = Path(inputs.get('output_dir') or settings.default_output_dir)
    source = Path(inputs.get('a_video') or out/f'{prefix}_vertical.mp4')
    original,subtitle = resolve_inputs(source)
    folder = out/'wallstreet_ab'/str(pair['id'])/TEMPLATE
    folder.mkdir(parents=True,exist_ok=True)
    script_path = folder/f'{prefix}_insight.json'
    if not script_path.is_file():
        if not settings.wallstreet_ab_remote_planning_authorized:
            raise ValueError('REMOTE_PLANNING_APPROVAL_PENDING：外部字幕策划待授权；A 正常发布')
        if not generate_insight_script(video['title'],source,subtitle,script_path,explicit_editorial=True):
            raise ValueError('二创策划失败；不替换为普通成片')
    script = InsightScriptV2.model_validate_json(script_path.read_text())
    if script.video_id != video['youtube_id']:
        raise ValueError('二创脚本指向另一源视频')
    final = folder/'editorial.mp4'
    if not valid_enrichment(source,script_path,final,original_video=original,bilingual_subtitle=subtitle):
        if not InsightProcessor().process(source,script_path,final,original_video=original,bilingual_subtitle=subtitle):
            raise ValueError('二创渲染未通过验收')
    from video_processing.pipeline_manager import PipelineManager
    manager = PipelineManager(str(out/'pipeline.db'))
    manager._OUT_DIR = out
    cover = manager._resolve_cover_file(video['youtube_id'],video['slice_index'])
    horizontal = manager._resolve_douyin_horizontal_cover_file(video['youtube_id'],video['slice_index'])
    if not cover or not horizontal:
        raise ValueError('缺少经过验证的双比例专门封面')
    package = dict(video=str(final),a_video=str(source),original=str(original),subtitle=str(subtitle),script=str(script_path))
    for key,asset in [('cover',cover),('horizontal_cover',horizontal)]:
        target = folder/(key+asset.suffix)
        shutil.copyfile(asset,target)
        package[key] = str(target)
    manifest = json.loads(manager._cover_provenance_path(cover).read_text())
    manifest.update(cover_filename=Path(package['cover']).name,cover_sha256=sha256(Path(package['cover'])))
    package['cover_provenance'] = str(folder/'cover_provenance.json')
    write_json(Path(package['cover_provenance']),manifest)
    package['title'] = str(folder/'title.txt')
    # 封面标题保持 A 的策略；B 描述明确为独立深度观察，不能靠相同标题识别作品。
    Path(package['title']).write_text((out/f'{prefix}_title.txt').read_text(),encoding='utf-8')
    package['copy'] = str(folder/'copy.txt')
    Path(package['copy']).write_text('深度观察：'+script.headline+'\n'+script.hook.narration+'\n'+script.outro.comment_invitation,encoding='utf-8')
    package['category'] = str(folder/'category.txt')
    shutil.copyfile(out/f'{prefix}_category.txt',package['category'])
    package['files'] = {key:sha256(Path(package[key])) for key in ('video','copy','title','cover','horizontal_cover','cover_provenance','category','script','subtitle','original','a_video')}
    package['payload_sha256'] = payload_hash(package)
    validate_package(package)
    write_json(folder/'package.json',package)
    return package


def command(publication,package,evidence,*,verify=False,ticket=None,product_decision=None):
    platform = publication['platform']
    args = [str(ROOT/'.venv/bin/python'),str(ROOT/f'scripts/{"wechat" if platform=="wechat" else "douyin"}_uploader.py'),
            '--copy',package['copy'],'--title-file',package['title'],'--evidence-dir',str(evidence),'--fail-fast-login']
    if verify:
        args+=['--verify-only']
        if publication.get('platform_post_id'):
            args+=['--platform-post-id',publication['platform_post_id']]
        if platform=='wechat' and publication.get('identity_receipt'):
            args+=['--identity-receipt',publication['identity_receipt']]
        # B 的封面短标题可能不进入视频号列表索引；已有原生 ID 时直接精确回查。
    else:
        args+=['--video',package['video'],'--cover',package['cover']]
        if platform=='wechat':
            if product_decision is None:
                raise ValueError('微信 B 必须传入冻结的商品任务决定')
            args+=['--cover-provenance',package['cover_provenance'],'--category-file',package['category'],
                   '--no-original-declaration']
            args+=write_product_task_arguments(product_decision, evidence.parent/'_product_task_inputs'/evidence.name)
        else:
            args+=['--horizontal-cover',package['horizontal_cover'],'--publish',
                   '--douyin-launch-ticket',ticket['_douyin_launch_ticket_id'],'--douyin-launch-token',ticket['_douyin_launch_token']]
    return args


def run_command(args,evidence):
    evidence.mkdir(parents=True,exist_ok=True)
    with (evidence/'uploader.log').open('a') as log:
        return run_admitted(args,cwd=ROOT,env=build_subprocess_env(include_telegram=False),
                              stdout=log,stderr=log,timeout=1800,check=False).returncode


def product_submission_matches(receipt, decision):
    if (receipt.get('product_task_id') != decision['task_id']
            or receipt.get('product_config_digest') != decision.get('config_digest')
            or receipt.get('product_config_version') != decision.get('config_version')
            or receipt.get('product_attachment_reason') != decision['reason']):
        return False
    if decision['require_product'] is False:
        return (receipt.get('product_binding_confirmed') is False and receipt.get('product_unbound_confirmed') is True
                and not receipt.get('product_id') and not receipt.get('product_title'))
    if receipt.get('product_binding_required') is False and receipt.get('product_unbound_confirmed') is True:
        return (receipt.get('product_binding_confirmed') is False
                and not receipt.get('product_id') and not receipt.get('product_title'))
    allowed = {(p['product_id'],p['title']) for p in decision['product_decision']['candidates']}
    return (receipt.get('product_binding_confirmed') is True and receipt.get('product_unbound_confirmed') is False
            and (receipt.get('product_id'),receipt.get('product_title')) in allowed)


def apply_readback(db,publication,evidence,code,*,product_decision=None):
    platform = publication['platform']
    path = evidence/('management_readback.json' if platform=='wechat' else 'douyin_management_readback.json')
    receipt = evidence/'submission_receipt.json'
    value = json.loads(path.read_text()) if path.is_file() else {}
    accepted = json.loads(receipt.read_text()) if platform=='wechat' and receipt.is_file() else {}
    native = value.get('platform_post_id') or accepted.get('platform_post_id') or publication.get('platform_post_id')
    if (code == 14 and platform == 'wechat' and publication['variant'] == 'B'
            and product_decision and not native and not path.exists() and not receipt.exists()):
        try:
            product_receipt = json.loads((evidence/'product_selection_receipt.json').read_text())
            wait = json.loads((evidence/'product_wait.json').read_text())
            package = json.loads(publication['package_json'])
            validate_package(package)
            if db.defer_wallstreet_wechat_product_wait(publication['id'],
                    attempt_token=publication['attempt_token'], uploader_exit_code=code,
                    evidence_dir=str(evidence), receipt=product_receipt, wait_evidence=wait,
                    package_sha256=payload_hash(package), asset_sha256=sha256(Path(package['video'])),
                    artifacts_digest=product_artifacts_digest(Path(package['video']),Path(package['copy']),Path(package['cover']))):
                return 'WAITING'
        except (OSError,ValueError,KeyError,TypeError):
            pass
    if (code == 2 and platform == 'wechat' and publication['variant'] == 'B'
            and not native and not path.exists() and not receipt.exists()):
        proof = evidence/f"preupload-login-{publication['attempt_token']}.json"
        write_json(proof,{'publication_id':publication['id'],'attempt_token':publication['attempt_token'],
            'uploader_exit_code':code,'stage':'LOGIN_BEFORE_FILE_UPLOAD','captured_at':time.time(),
            'uploader_log':str(evidence/'uploader.log')})
        if db.recover_wallstreet_wechat_login_exit(publication['id'],
                attempt_token=publication['attempt_token'],uploader_exit_code=code,evidence_path=str(proof)):
            return 'WAITING'
    if (publication.get('platform_post_id') and native
            and native != publication['platform_post_id']):
        raise ValueError('回读作品 ID 不匹配，禁止覆盖')
    strong = value.get('matched_by') in {'EXACT_OBJECT_ID','EXACT_EXPORT_ID','EXACT_SUBMISSION_NONCE'} if platform=='wechat' else value.get('identity_source')=='API_EXACT_DESCRIPTION'
    state = value.get('state')
    if state=='PUBLISHED' and strong and native:
        outcome = 'PUBLISHED'
    elif state in {'REJECTED','RESTRICTED'} and strong:
        outcome = 'REJECTED'
    elif accepted.get('platform_post_id') or (state=='UNDER_REVIEW' and native) or code==6:
        outcome = 'UNDER_REVIEW'
    else:
        outcome = 'UNCERTAIN'
    if product_decision and outcome in {'PUBLISHED','UNDER_REVIEW'} and not product_submission_matches(accepted,product_decision):
        # 已受理仍保留原生 ID；商品证据不一致不能恢复等待或再次上传。
        outcome = 'UNCERTAIN'
    platform_time = value.get('platform_public_at')
    calibrated = (platform == 'wechat' and outcome == 'PUBLISHED'
        and value.get('public_time_evidence') == 'DOM_POSTED_INFO_AND_NATIVE_CREATE_TIME'
        and isinstance(platform_time,(int,float)) and not isinstance(platform_time,bool)
        and math.isfinite(platform_time) and 0 < platform_time <= time.time())
    db.observe_wallstreet_publication(publication['id'],state=outcome,platform_post_id=native,
        public_at=platform_time if calibrated else None,
        time_basis='platform' if calibrated else 'first_observed_public',
        evidence_path=str(path if path.is_file() else receipt if receipt.is_file() else evidence/'uploader.log'),
        attempt_token=publication.get('attempt_token'),error=None if outcome=='PUBLISHED' else f'回读状态 {state}; uploader={code}')
    if outcome == 'PUBLISHED' and publication['variant'] == 'A':
        db.sync_wallstreet_normal_a(publication['id'])
    return outcome


def _yield_to_ready_wechat_delivery(db, platform):
    """历史只读任务不抢占当前窗口中已通过队列资格的成片。"""
    if platform != 'wechat' or settings.wechat_publishing_paused:
        return False
    if settings.is_public_publish_window() and db.get_high_score_pending_videos(
            min_score=75, limit=1, ready_only=True,
            channel_min_scores=settings.auto_publish_channel_min_scores,
            excluded_product_tasks=blocked_product_task_keys(settings.default_output_dir,
                                                            settings.wechat_product_policy_path)):
        return True
    return bool(settings.enable_english_world_auto_publish and settings.is_english_world_publish_window()
                and db.get_next_auto_approved_english_world_submission(
                    excluded_product_tasks=blocked_product_task_keys(settings.default_output_dir,
                                                                    settings.wechat_product_policy_path)))


def reconcile(db):
    db.recover_unstarted_wallstreet_douyin()
    now = time.time()
    for publication in db.get_wallstreet_publications():
        with gate().admit("wallstreet-publication", "wallstreet:" + str(publication["id"])) as ticket:
            if publication['state']=='PUBLISHED':
                if publication['variant']=='A':
                    db.sync_wallstreet_normal_a(publication['id'])
                continue
            if publication['next_readback_at']>now:
                continue
            if _yield_to_ready_wechat_delivery(db, publication['platform']):
                continue
            if publication['variant']=='A':
                legacy = (db.get_wechat_publication(publication['youtube_id'],slice_index=publication['slice_index']) if publication['platform']=='wechat'
                          else db.get_douyin_publication(publication['youtube_id'],publication['slice_index']))
                if not legacy:
                    continue
                # 不把旧账本 PUBLISHED 直接视作强原生 ID 证据，仍只读回查管理页。
                out = settings.default_output_dir
                prefix = publication['youtube_id']+(f"_s{publication['slice_index']}" if publication['slice_index'] else '')
                package = {'copy':str(out/f'{prefix}_copy.txt'),'title':str(out/f'{prefix}_title.txt')}
                publication['platform_post_id'] = legacy.get(
                    'platform_post_id' if publication['platform']=='wechat' else 'external_post_id') or publication.get('platform_post_id')
                if publication['platform']=='douyin' and not publication['platform_post_id']:
                    # 抖音受理不返回原生 ID；仅已提交 A 可按既有完整正文契约只读取 ID。
                    if legacy['state'] not in {'UNDER_REVIEW','PUBLISHED'} or legacy['attempt_count'] < 1:
                        continue
                if publication['platform']=='wechat' and not publication['platform_post_id']:
                    continue
                if publication['platform']=='wechat' and legacy.get('evidence_path'):
                    receipt = Path(legacy['evidence_path']).parent/'submission_receipt.json'
                    if receipt.is_file():
                        publication['identity_receipt'] = str(receipt)
            elif publication['state'] in {'SUBMITTING','UNCERTAIN','UNDER_REVIEW'}:
                if not publication['package_json']:
                    continue
                package = json.loads(publication['package_json'])
                if publication['platform']=='wechat' and not publication['platform_post_id']:
                    # 没有原生 ID 不猜视频号作品，继续保留结果不明，供人工恢复绑定。
                    continue
            else:
                continue
            if publication['variant']=='B' and publication['platform']=='wechat':
                recorded = Path(publication['evidence_path']) if publication.get('evidence_path') else None
                receipt = ((recorded if recorded.is_dir() else recorded.parent)/'submission_receipt.json' if recorded
                           else Path(package['video']).parent/'submissions'/f"wechat-{publication['id']}"/'submission_receipt.json')
                if receipt.is_file():
                    publication['identity_receipt'] = str(receipt)
            evidence = settings.default_output_dir/'wallstreet_ab'/str(publication['pair_id'])/'readback'/f"{publication['id']}-{int(now)}"
            try:
                with TaskLease(settings.default_output_dir/f"{publication['platform']}_publish_priority.lock",stage='A/B只读回查'):
                    if _yield_to_ready_wechat_delivery(db, publication['platform']):
                        continue
                    ticket.start()
                    code = run_command(command(publication,package,evidence,verify=True),evidence)
                    apply_readback(db,publication,evidence,code)
            except TaskLeaseBusy:
                continue
            except Exception as exc:
                logging.warning('作品回查失败 id=%s %s',publication['id'],type(exc).__name__)
                db.observe_wallstreet_publication(publication['id'],state='UNCERTAIN',evidence_path=str(evidence/'uploader.log'),error=type(exc).__name__)


def submit_ready(db):
    if settings.wechat_publishing_paused or not settings.is_public_publish_window():
        return
    for pub in db.get_wallstreet_publications():
        with gate().admit("wallstreet-publication", "wallstreet:" + str(pub["id"])) as ticket:
            if pub['variant']!='B' or pub['state']!='WAITING' or not pub['package_json']:
                continue
            if pub['platform']=='douyin' and not settings.enable_douyin_browser_publishing:
                continue
            package = json.loads(pub['package_json'])
            evidence = Path(package['video']).parent/'submissions'/f"{pub['platform']}-{pub['id']}"/f'attempt-{time.time_ns()}'
            try:
                lock = 'wechat_publish_priority.lock' if pub['platform']=='wechat' else 'douyin_submission.lock'
                with TaskLease(settings.default_output_dir/lock,stage='二创提交'):
                    ticket.start()
                    validate_package(package)
                    product_decision = None
                    if pub['platform']=='wechat':
                        source = db.get_video_by_youtube_id(pub['youtube_id'],slice_index=pub['slice_index'])
                        if not source:
                            raise ValueError('微信 B 缺少原视频商品上下文')
                        context = dict(source, **video_product_context(settings.default_output_dir,source))
                        # A 和 B 是两个发布实体：原视频受理状态不代表 B 已经提交。
                        context.update(status=pub['state'],wallstreet_publication_id=pub['id'],variant='B')
                        product_decision = freeze_task_product_decision(db,f"wallstreet:wechat:B:{pub['id']}",
                            context,settings.wechat_product_policy_path)
                        if not product_task_preflight(product_decision,settings.default_output_dir,
                                product_artifacts_digest(Path(package['video']),Path(package['copy']),Path(package['cover'])),
                                observation_generation=product_observation_generation(settings.wechat_product_policy_path)):
                            continue
                    claim = db.claim_wallstreet_submission(pub['id'],package_sha256=payload_hash(package),
                        video_path=package['video'],asset_sha256=sha256(Path(package['video'])),evidence_path=str(evidence))
                    if not claim:
                        continue
                    try:
                        pub.update(claim)
                        if pub['platform']=='wechat':
                            write_json(evidence/'attempt_claim.json', {key:claim[key] for key in
                                ('id','attempt_token','attempt_count','package_sha256','asset_sha256','video_path','evidence_path')})
                        code = run_command(command(pub,package,evidence,ticket=claim,product_decision=product_decision),evidence)
                        apply_readback(db,pub,evidence,code,product_decision=product_decision)
                    except Exception as exc:
                        db.observe_wallstreet_publication(pub['id'],state='UNCERTAIN',attempt_token=claim['attempt_token'],
                            evidence_path=str(evidence/'uploader.log'),error=type(exc).__name__)
            except TaskLeaseBusy:
                continue
            except Exception as exc:
                logging.warning('B 提交前校验延后 id=%s %s',pub['id'],type(exc).__name__)


@entry
def run_once(db,*,render_only=False):
    if not render_only:
        reconcile(db)
        submit_ready(db)
    if read_lease_owner(settings.default_output_dir/'pipeline.lock'):
        return
    with claim_unit("wallstreet-render", lambda: db.claim_wallstreet_render(lease_seconds=settings.wallstreet_ab_render_lease_seconds),
                    lambda row: "pair:" + str(row["id"])) as pair:
        if not pair:
            return
        stop = threading.Event()
        admission = current()
        def renew():
            with admission.bind():
                while not stop.wait(60):
                    db.renew_wallstreet_render(pair['id'],pair['lease_token'],settings.wallstreet_ab_render_lease_seconds)
        thread = threading.Thread(target=renew,daemon=True); thread.start()
        try:
            package = build_package(db,pair)
            if not db.finish_wallstreet_render(pair['id'],pair['lease_token'],package=package):
                raise ValueError('二创租约失效，禁止采用产物')
        except Exception as exc:
            logging.exception('二创加工失败；保留 A')
            db.finish_wallstreet_render(pair['id'],pair['lease_token'],error=str(exc))
        finally:
            stop.set();thread.join(timeout=2)
    if not render_only:
        submit_ready(db)


def report(db):
    rows = db.get_wallstreet_metrics_report()
    groups = {}
    for row in rows:
        key = (row['pair_id'],row['platform'],row['account'],row['horizon_hours'])
        groups.setdefault(key,{})[row['variant']] = row
    pairs = []
    for key,versions in groups.items():
        a,b = versions.get('A',{}),versions.get('B',{})
        available = a.get('interaction_rate') is not None and b.get('interaction_rate') is not None
        comparable = available and all(v.get('public_time_basis')=='platform' and abs(v['observed_age_hours']-key[3])<=2 for v in (a,b))
        pairs.append({'pair_id':key[0],'platform':key[1],'account':key[2],'horizon_hours':key[3],
                      'interaction_rate_difference':b['interaction_rate']-a['interaction_rate'] if available else None,
                      'comparable':comparable,'versions':versions})
    config = db.get_wallstreet_experiment()
    publications = db.get_wallstreet_publications()
    enrolled = {p['pair_id'] for p in publications if p['mode']=='PAIRED'}
    completed = sum(all(p['state']=='PUBLISHED' for p in publications if p['pair_id']==pair_id) for pair_id in enrolled)
    return {'experiment':config,'completed_pairs':completed,
            'remote_planning_authorized':settings.wallstreet_ab_remote_planning_authorized,
            'review_due':bool(config and completed>=config['review_pairs']),
            'pairs':pairs,'metric_capture':'native_id_bound_import',
            'publications':[{key:pub[key] for key in ('id','pair_id','youtube_id','variant','platform','account',
                'state','platform_post_id','public_at','public_time_basis','evidence_path','last_error')}
                for pub in publications]}


@entry
@registered("wallstreet-worker")
def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--render-only',action='store_true')
    parser.add_argument('--activate',action='store_true')
    parser.add_argument('--pause',action='store_true')
    parser.add_argument('--enqueue-b-only')
    parser.add_argument('--recover-pair', help='具名补入实验启用后、普通 A 已绑定提交的漏单；不重发 A')
    parser.add_argument('--retry-render',type=int)
    parser.add_argument('--import-metrics',type=Path)
    parser.add_argument('--report',action='store_true')
    parser.add_argument('--bind-publication',type=int)
    parser.add_argument('--platform-post-id')
    args = parser.parse_args()
    db = PipelineDB(str(settings.default_output_dir/'pipeline.db'))
    if args.retry_render is not None:
        print(json.dumps({'retry_scheduled':db.retry_wallstreet_render(args.retry_render)}));return 0
    if args.activate or args.pause:
        print(json.dumps(db.set_wallstreet_experiment(active=args.activate),ensure_ascii=False));return 0
    if args.enqueue_b_only:
        db.set_publication_review_required(args.enqueue_b_only,True)
        print(json.dumps(db.enroll_wallstreet_video(args.enqueue_b_only,b_only=True),ensure_ascii=False));return 0
    if args.recover_pair:
        accounts = {'wechat':'default'}
        if settings.enable_douyin_browser_publishing:
            accounts['douyin'] = 'default'
        out = settings.default_output_dir
        print(json.dumps(db.recover_wallstreet_pair(args.recover_pair, accounts=accounts,
            inputs={'prefix':args.recover_pair,'output_dir':str(out),
                    'a_video':str(out/f'{args.recover_pair}_vertical.mp4')}),ensure_ascii=False));return 0
    if args.import_metrics:
        value = json.loads(args.import_metrics.read_text())
        for row in value if isinstance(value,list) else [value]:
            db.record_wallstreet_metrics(**row)
        return 0
    if args.report:
        print(json.dumps(report(db),ensure_ascii=False,indent=2));return 0
    if args.bind_publication:
        if not args.platform_post_id:
            parser.error('恢复绑定必须提供原生作品 ID')
        pub = next((p for p in db.get_wallstreet_publications() if p['id']==args.bind_publication),None)
        if not pub or not pub['package_json'] or pub['state']=='PUBLISHED':
            parser.error('只能恢复有独立投稿包且尚未确认公开的记录')
        pub['platform_post_id'] = args.platform_post_id
        package = json.loads(pub['package_json'])
        evidence = Path(package['video']).parent/'recovery'/str(int(time.time()))
        with TaskLease(settings.default_output_dir/f"{pub['platform']}_publish_priority.lock",stage='作品原生ID只读恢复'):
            code = run_command(command(pub,package,evidence,verify=True),evidence)
            result_path = evidence/('management_readback.json' if pub['platform']=='wechat' else 'douyin_management_readback.json')
            result = json.loads(result_path.read_text()) if result_path.is_file() else {}
            strong = result.get('matched_by') in {'EXACT_OBJECT_ID','EXACT_EXPORT_ID'} if pub['platform']=='wechat' else result.get('identity_source')=='API_EXACT_DESCRIPTION'
            if not strong or result.get('platform_post_id') != args.platform_post_id or result.get('state') not in {'PUBLISHED','UNDER_REVIEW','REJECTED','RESTRICTED'}:
                print('原生 ID 未核实，保持原记录');return 1
            print(apply_readback(db,pub,evidence,code))
        return 0
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    try:
        with TaskLease(settings.default_output_dir/'wallstreet_worker.lock',stage='二创独立执行者'):
            stopped = threading.Event()
            revision = run_admitted(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,timeout=5).stdout.strip()
            from video_processing.censor_engine import current_rules_fingerprint
            from video_processing.processors.insight_processor import render_spec
            adopted = render_spec()
            def heartbeat():
                while not stopped.is_set():
                    write_json(settings.default_output_dir/'wallstreet_worker_status.json',
                        {'pid':os.getpid(),'git_revision':revision,'loaded_template':TEMPLATE,'render_spec':adopted,
                         'remote_planning_authorized':settings.wallstreet_ab_remote_planning_authorized,
                         'rules_fingerprint':current_rules_fingerprint(),'heartbeat_at':time.time(),
                         'experiment':db.get_wallstreet_experiment(),'pairs':db.get_wallstreet_pairs()})
                    stopped.wait(5)
            thread = threading.Thread(target=heartbeat,daemon=True);thread.start()
            try:
                run_once(db,render_only=args.render_only)
            finally:
                stopped.set();thread.join(timeout=6)
    except TaskLeaseBusy:
        return 0
    return 0

if __name__=='__main__':
    raise SystemExit(main())
