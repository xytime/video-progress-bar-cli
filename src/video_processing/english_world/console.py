"""英语世界只读管理视图；所有证据都限于本地产物，绝不回查或提交平台。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-25 | Codex | 真实任务、自动运行失败、组合筛选分页与文件身份绑定报告。 |
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo('Asia/Shanghai')
LABELS = {
    'RESEARCH_QUEUED': '等待研究', 'RESEARCHING': '研究中', 'CANDIDATES_READY': '等待选题',
    'CANDIDATE_SELECTED': '等待制作确认', 'PRODUCTION_REQUESTED': '等待制作',
    'PRODUCING': '制作中', 'READY_FOR_REVIEW': '成片待复核', 'SUBMISSION_APPROVED': '已授权 · 等待投稿',
    'SUBMITTING': '投稿中', 'UNDER_REVIEW': '平台审核中', 'UNCERTAIN': '投稿结果不明',
    'LOGIN_REQUIRED': '等待登录', 'FAILED': '处理失败', 'HELD': '已暂停', 'CANCELED': '已取消',
    'PUBLISHED': '已公开（历史回读）', 'SUBMITTED_BOUND': '已受理', 'UNKNOWN': '当前未知',
    'REQUESTED': '等待制作', 'REJECTED': '平台拒绝', 'DELETED': '已删除',
}
ATTENTION = {'FAILED', 'UNCERTAIN', 'LOGIN_REQUIRED', 'HELD', 'UNKNOWN', 'REJECTED',
             'CANDIDATES_READY', 'CANDIDATE_SELECTED', 'READY_FOR_REVIEW'}
ACTIVE = {'RESEARCH_QUEUED', 'RESEARCHING', 'PRODUCTION_REQUESTED', 'REQUESTED',
          'PRODUCING', 'SUBMISSION_APPROVED', 'SUBMITTING', 'UNDER_REVIEW', 'SUBMITTED_BOUND'}


def stamp(value):
    if not value:
        return None
    try:
        date = datetime.fromisoformat(str(value))
        return (date.replace(tzinfo=timezone.utc) if date.tzinfo is None else date).astimezone(SHANGHAI).isoformat()
    except (TypeError, ValueError):
        return None


def clean(value):
    """错误只保留有用摘要；本机路径和可能的凭据不进入页面。"""
    text = str(value or '')[:2000]
    text = re.sub(r'https?://\S+', '[链接已省略]', text)
    text = re.sub(r'/(?:Users|Volumes|tmp|private)/[^\s,;，；]*', '[本地文件]', text)
    text = re.sub(r'(?i)(token|api[_-]?key|authorization|password)\s*[:=]\s*\S+', r'\1=[已隐藏]', text)
    return text[:600]


class EnglishConsole:
    def __init__(self, db, output: Path):
        self.db, self.output = db, Path(output).resolve()

    def local(self, path):
        if not path:
            raise ValueError('没有本地证据')
        candidate = Path(path)
        resolved = candidate.resolve()
        if candidate.is_symlink() or not resolved.is_relative_to(self.output) or not resolved.is_file():
            raise ValueError('证据缺失或超出允许目录')
        return resolved

    def read(self, path):
        file = self.local(path)
        if file.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('证据超过展示上限')
        value = json.loads(file.read_text())
        if not isinstance(value, dict):
            raise ValueError('证据格式异常')
        return value

    def tasks(self):
        snapshot = self.db.english_console_snapshot()
        reviews = {r['id']: r for r in snapshot['reviews']}
        result, linked, manifests = [], set(), set()
        for job in snapshot['jobs']:
            review = reviews.get(job.get('review_id'))
            if review:
                linked.add(review['id'])
            result.append(self.task(job, review))
        for review in reviews.values():
            if review['id'] not in linked:
                result.append(self.task(None, review))
        for row in result:
            if row['_record'].get('manifest_path'):
                manifests.add(str(Path(row['_record']['manifest_path']).resolve()))
        directory = self.output / 'english_world_daily'
        # 只读取固定命名的协调器回执；原始日志/提示词/环境不暴露。
        logs = sorted(directory.glob('run_*.log'), reverse=True)
        warnings = []
        for path in logs[:200]:
            request = path.with_suffix('.delivery-request.json')
            try:
                data = self.read(request) if request.exists() else {}
                if data.get('manifest') and str(Path(data['manifest']).resolve()) in manifests:
                    continue
                recorded = datetime.strptime(path.stem, 'run_%Y-%m-%d_%H%M%S_%f').replace(tzinfo=SHANGHAI).isoformat()
                state = 'FAILED' if data.get('failure') else 'UNKNOWN'
                record = {'id': path.stem, 'title': data.get('title') or '英语世界定时运行',
                          'state': state, 'created_at': recorded, 'updated_at': recorded,
                          'error_message': data.get('failure') or '暂无关联成片台账；运行结果待核实',
                          'mp4_path': data.get('mp4'), 'manifest_path': data.get('manifest'),
                          '_request': str(request)}
                result.append(self.task(None, record, run=True))
            except (OSError, ValueError, TypeError):
                warnings.append('一条定时运行回执无法读取，未作为成功记录展示')
        result.sort(key=lambda r: (r['updated_at'] or '', r['id']), reverse=True)
        coverage = {'jobs': snapshot['counts']['english_world_jobs'],
                    'reviews': snapshot['counts']['english_world_review_items'], 'run_logs': len(logs),
                    'limited': any(n > 1000 for n in snapshot['counts'].values()) or len(logs) > 200}
        return result, coverage, sorted(set(warnings))

    def task(self, job, review, run=False):
        record = dict(review or job)
        state = record.get('state', 'UNKNOWN')
        if job and not review:
            state = job.get('production_state') or state
        platform = record.get('platform_state')
        public = platform == 'PUBLISHED' and bool(record.get('platform_post_id'))
        # 公共状态来自有原生身份的既有回读，不执行现场查询。
        display = 'PUBLISHED' if public else state
        updated = stamp(record.get('updated_at'))
        stale = bool(display in ACTIVE and (not updated or
                     (datetime.now(timezone.utc)-datetime.fromisoformat(updated)).total_seconds() > 86400))
        trigger = ('scheduled' if run else 'manual' if job else 'auto')
        return {
            'id': ('run:' if run else 'job:' if job else 'review:') + str(record['id'] if not job else job['id']),
            'title': record.get('title') or record.get('source_title') or '英语世界研究任务',
            'source': record.get('source_publisher') or record.get('source_channel') or record.get('source_title') or '来源尚未登记',
            'state': display, 'label': (LABELS.get(display, '状态待核实 · '+display) +
                                      (' · 记录过期，当前待确认' if stale else '')),
            'trigger': trigger, 'created_at': stamp(record.get('created_at')),
            'updated_at': updated, 'error': clean(record.get('error_message')), 'stale': stale,
            'active': display in ACTIVE and not stale, 'attention': display in ATTENTION or stale,
            'done': public or display in {'CANCELED', 'HELD', 'FAILED'},
            'review_id': review.get('id') if review and not run else None,
            'approved_at': stamp(record.get('approved_at')),
            'wechat': {'state': platform or ('NOT_SUBMITTED' if state in {'READY_FOR_REVIEW','SUBMISSION_APPROVED'} else state if review and not run else 'UNKNOWN'),
                       'post_id': record.get('platform_post_id'), 'observed_at': stamp(record.get('last_reconciled_at'))},
            'douyin': {'state': record.get('douyin_state') or 'UNKNOWN', 'post_id': record.get('douyin_post_id'),
                       'observed_at': stamp(record.get('douyin_updated_at'))},
            '_record': record, '_job': job,
        }

    @staticmethod
    def public(row):
        return {k: v for k, v in row.items() if not k.startswith('_')}

    def view(self, *, q='', category='all', trigger='', date='', page=1):
        rows, coverage, warnings = self.tasks()
        counts = {'all': len(rows), **{key: sum(bool(r[key]) for r in rows) for key in ('active','attention','done')}}
        query = q.strip().casefold()
        selected = [r for r in rows if (not query or query in (r['title']+' '+r['source']).casefold())
                    and (category == 'all' or r[category]) and (not trigger or r['trigger'] == trigger)
                    and (not date or (r['created_at'] or '').startswith(date))]
        pages = max(1, (len(selected)+19)//20)
        page = min(page, pages)
        return {'items': [self.public(r) for r in selected[(page-1)*20:page*20]],
                'total': len(selected), 'page': page, 'pages': pages, 'counts': counts,
                'coverage': coverage, 'warnings': warnings, 'fetched_at': datetime.now(timezone.utc).isoformat()}

    def find(self, task_id):
        rows, _, _ = self.tasks()
        row = next((r for r in rows if r['id'] == task_id), None)
        if row is None:
            raise LookupError('任务不在当前可读取窗口')
        return row

    def report(self, task_id, kind):
        row = self.find(task_id)
        record = row['_record']
        result = {'task': self.public(row), 'kind': kind, 'status': '本地记录', 'lines': []}
        lines = result['lines']
        if kind == 'history':
            lines.extend([f"创建：{row['created_at'] or '未知'}", f"最近更新：{row['updated_at'] or '未知'}",
                          f"台账状态：{row['label']} ({row['state']})"])
            for key, label in [('production_started_at','制作开始'), ('production_finished_at','制作结束'),
                               ('approved_at','投稿授权'), ('submission_started_at','投稿开始'),
                               ('submission_finished_at','投稿结束')]:
                value = record.get(key) or (row['_job'] or {}).get(key)
                if value:
                    lines.append(f'{label}：{stamp(value) or "未知"}')
            if row['error']:
                lines.append('停止原因：'+row['error'])
        elif kind == 'platform':
            for key, label in [('wechat','视频号'),('douyin','抖音')]:
                info = row[key]
                lines.extend([f"{label}：{LABELS.get(info['state'], info['state'])}",
                              f"原生作品 ID：{info['post_id'] or '未登记'}",
                              f"最近台账时间：{info['observed_at'] or '未登记'}"])
            lines.append('以上为已有本地台账；本次刷新没有访问平台。受理、审核中和结果不明均不代表当前公开可见。')
        elif kind == 'asset':
            for key, label in [('mp4_path','成片'),('manifest_path','成片清单'),('cover_path','封面')]:
                try:
                    file = self.local(record.get(key))
                    lines.append(f'{label}：{file.name} · {file.stat().st_size:,} 字节（当前文件存在）')
                except (OSError,ValueError):
                    lines.append(f'{label}：尚无可读取文件')
            lines.append('文件存在不代表质量通过、投稿授权或平台发表；本页不修改产物。')
        else:
            names = {'audio': 'final_audio_qa.json', 'language': 'language_qa.json',
                     'visual': 'visual_safety.json', 'safety': 'safety_gate.json'}
            if kind not in names:
                raise ValueError('未知报告类型')
            try:
                manifest = self.local(record.get('manifest_path'))
                path = manifest.parent/'qa'/names[kind]
                data = self.read(path)
                binding = self.bind_report(record, manifest, data)
                result['status'] = '身份一致 · 历史报告 '+str(data.get('state') or data.get('status') or '未判定') if binding else '关联未核实'
                lines.extend([f"报告：{path.name}", f"报告记录：{clean(data.get('state') or data.get('status') or '未判定')}",
                              '当前文件指纹与报告绑定一致' if binding else '缺少一致的当前文件指纹，不能采纳为通过'])
                for key in ('provider','model','effort','review_state','failure_kind','expected_final_word','observed_final_word','sample_rate','channels'):
                    if key in data and isinstance(data[key], (str,int,float,bool)):
                        lines.append(f'{key}：{clean(data[key])}')
            except (OSError,ValueError,TypeError):
                result['status'] = '证据缺失或不可读取'
                lines.append('暂无可核验的对应报告；不会沿用其他任务的通过结论。')
        return result

    def bind_report(self, record, manifest, data):
        """采纳只按现有文件内容指纹，未知绑定失败关闭；不重跑 QA。"""
        def digest(path):
            h = hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024*1024), b''):
                    h.update(chunk)
            return h.hexdigest()
        manifest_content = None
        def timeline():
            nonlocal manifest_content
            manifest_content = manifest_content or self.read(manifest)
            return self.local(manifest_content.get('timeline'))
        if data.get('mp4_sha256'):
            video = self.local(record.get('mp4_path'))
            if digest(video) != data['mp4_sha256'] or (record.get('artifact_sha256') and data['mp4_sha256'] != record['artifact_sha256']):
                return False
            if data.get('manifest_sha256') and digest(manifest) != data['manifest_sha256']:
                return False
            if data.get('timeline_sha256') and digest(timeline()) != data['timeline_sha256']:
                return False
            if data.get('source_evidence_sha256') and digest(self.local(timeline().parent/'qa/source_evidence.json')) != data['source_evidence_sha256']:
                return False
            if data.get('contact_sheet_sha256'):
                sheet = self.local(data.get('contact_sheet_path') or data.get('contact_sheet'))
                if digest(sheet) != data['contact_sheet_sha256']:
                    return False
            return True
        if data.get('timeline_sha256'):
            expected = record.get('manifest_sha256')
            return bool(expected and digest(manifest) == expected and digest(timeline()) == data['timeline_sha256'])
        return False
