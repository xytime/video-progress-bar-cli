"""采集标题翻译磁盘队列：采集只读缓存/入队，独立消费者负责网络调用。

依赖：scripts -> 本模块 -> settings/标准库；不访问业务数据库。
"""
import fcntl
import hashlib
import json
import os
import uuid
from pathlib import Path
import subprocess
import sys
import time
from .provider_circuit import ProviderCircuit


def cached_or_enqueue(directory, title):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(title.encode()).hexdigest()
    path = directory / (key + '.json')
    if path.exists():
        row = json.loads(path.read_text())
        return row.get('translation') or title
    # 完整写入后用硬链接原子发布，读者不会看到半个 JSON，也不覆盖已有缓存。
    temporary = directory / (key + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps({'title': title, 'created_at': time.time()}))
        try:
            os.link(temporary, path)
        except FileExistsError:
            pass
    finally:
        temporary.unlink(missing_ok=True)
    return title


def drain(directory, timeout, limit=5):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'worker.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        circuit = ProviderCircuit(directory / 'provider-health', threshold=1, cooldown=900)
        done = 0
        for path in sorted(directory.glob('*.json'), key=lambda p: p.stat().st_mtime):
            if done >= limit or circuit.blocked():
                break
            row = json.loads(path.read_text())
            if row.get('translation'):
                continue
            try:
                result = subprocess.run([sys.executable, '-m', __name__, '--one'],
                                        input=row['title'], text=True, capture_output=True,
                                        timeout=timeout, check=True)
                # 翻译日志可能在 stdout，结果仅接受最后一行 JSON。
                translated = json.loads(result.stdout.splitlines()[-1])['translation']
                if not translated or translated == row['title']:
                    raise ValueError('未生成译文')
                row['translation'] = translated
                temporary = path.with_suffix('.tmp')
                temporary.write_text(json.dumps(row, ensure_ascii=False))
                temporary.replace(path)
                circuit.record(True)
                done += 1
            except (subprocess.SubprocessError, ValueError, KeyError, IndexError):
                circuit.record(False)
                break
        return done


if __name__ == '__main__':
    from .translation_helper import translate_text
    from .generated_content_validation import is_upstream_error_response
    title = sys.stdin.read()
    translated = translate_text(title, src_lang='auto', target_lang='zh-CN')
    if not translated or is_upstream_error_response(translated):
        raise SystemExit(2)
    print(json.dumps({'translation': translated}, ensure_ascii=False))
