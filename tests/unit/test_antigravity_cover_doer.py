"""程序化 AGY 生图及独立质量回执，不使用 OCR 字符数作为门禁。"""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from PIL import Image
from scripts import run_antigravity_cover_doer as worker
from video_processing.ai_cover_queue import AICoverQueue
from video_processing.utils.cover_agy import QUALITY_VERSION


def inputs(tmp_path):
    queue = AICoverQueue(tmp_path / 'queue', tmp_path / 'finish')
    task = queue.create_task(prefix='demo', youtube_id='demo', slice_index=0,
        cover_payload={'title': '国债回购'}, visual_brief={'visual_direction': 'finance'},
        final_cover_path=tmp_path/'cover.jpg', provenance_path=tmp_path/'prov.json',
        brief_path=tmp_path/'brief.json', content_aware=False, generation_deadline_minutes=32,
        fallback_after_minutes=34, primary_provider='agy')
    args = SimpleNamespace(task_id=task.task_id, queue_dir=str(queue.queue_dir),
        finish_dir=str(queue.finish_dir), agy_bin='agy', model='gemini-3.7-flash-high',
        timeout_seconds=120, review_timeout_seconds=90)
    return queue, task, args


def quality(path, **kwargs):
    return {'version': QUALITY_VERSION, 'provider': 'agy_cli', 'model': 'test',
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'review': dict(decision='PASS', image_inspected=True, subject_relevant=True,
            composition_complete=True, adequate_detail=True, no_severe_artifacts=True,
            observed_content='bonds and gold', reason='usable editorial scene')}


def generate(args, task, work_dir):
    Image.new('RGB', (896, 1200), '#273f52').save(work_dir/'candidate.png')
    return 'saved'


def test_generation_prompt_allows_english_and_never_calls_codex(tmp_path, monkeypatch):
    queue, task, args = inputs(tmp_path)
    captured = {}
    def cli(command, **kwargs):
        captured.update(command=command, **kwargs)
        return {'response': 'saved'}
    monkeypatch.setattr(worker, 'run_cli', cli)
    assert worker._generate(args, task, tmp_path) == 'saved'
    command = captured['command']
    assert command[0] == 'agy'
    assert 'Avoid non-English text' in command[-1]
    assert 'English lettering or numbers may appear' in command[-1]
    assert 'Absolutely no text' not in command[-1]
    assert '国债回购' in command[-1]
    assert captured['timeout'] <= args.timeout_seconds + 5


def test_worker_accepts_only_independent_quality_and_binds_hash(tmp_path, monkeypatch):
    queue, task, args = inputs(tmp_path)
    monkeypatch.setattr(worker, '_generate', generate)
    monkeypatch.setattr(worker, 'review_image', quality)
    assert worker.run(args) == 0
    visual = queue.accepted_visual(task)
    assert visual is not None
    assert not (task.finish_dir/'claim.json').exists()
    result = json.loads((task.finish_dir/'result.json').read_text())
    assert result['machine_visual_review'] == QUALITY_VERSION
    assert 'ocr_text' not in result
    assert result['quality_review']['sha256'] == result['sha256']
    assert worker.run(args) == 0
    # 图片变化使已有回执失效。
    Image.new('RGB', (896, 1200), 'red').save(visual)
    assert queue.accepted_visual(task) is None


def test_rejects_crude_image_then_retries_and_keeps_evidence(tmp_path, monkeypatch):
    queue, task, args = inputs(tmp_path)
    monkeypatch.setattr(worker, '_generate', generate)
    def rejected(path, **kw):
        r = quality(path)
        r['review'].update(decision='REJECT', adequate_detail=False, reason='crude placeholder')
        return r
    monkeypatch.setattr(worker, 'review_image', rejected)
    assert worker.run(args) == 1
    assert not (task.finish_dir/'result.json').exists()
    monkeypatch.setattr(worker, 'review_image', quality)
    assert worker.run(args) == 0
    assert queue.accepted_visual(task)
    old = json.loads((task.finish_dir/'antigravity_attempt_1.json').read_text())
    assert old['stage'] == 'quality_review'
    assert 'crude placeholder' in old['error']


@pytest.mark.parametrize('failure', ['PROCESS_TIMEOUT: budget=90s', 'AGY_QUALITY_MISSING_STRUCTURED_OUTPUT'])
def test_quality_unavailable_exhausts_three_attempts_then_fallback(tmp_path, monkeypatch, failure):
    queue, task, args = inputs(tmp_path)
    calls = []
    def unavailable(*a, **kw):
        calls.append(1)
        raise RuntimeError(failure)
    monkeypatch.setattr(worker, '_generate', generate)
    monkeypatch.setattr(worker, 'review_image', unavailable)
    assert [worker.run(args) for _ in range(3)] == [1, 1, 1]
    assert worker.run(args) == 0
    assert len(calls) == 3
    assert queue.should_fallback(task)
    assert not (task.finish_dir/'result.json').exists()
    assert failure in (task.finish_dir/'antigravity_attempt.json').read_text()


def test_worker_lock_prevents_second_generation(tmp_path, monkeypatch):
    import fcntl
    queue, task, args = inputs(tmp_path)
    monkeypatch.setattr(worker, '_generate', lambda *a: pytest.fail('duplicate call'))
    with (task.finish_dir/'worker.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert worker.run(args) == 0
    assert not (task.finish_dir/'antigravity_attempt.json').exists()
