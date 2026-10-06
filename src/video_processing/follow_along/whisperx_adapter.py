"""WhisperX 隔离环境适配器；只接收有限粗窗口与作者原词。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-07 | Codex | 离线模型指纹、原始字符证据和完整词界导入 |
"""
import json
from pathlib import Path
import fcntl
import time

from .alignment import ExternalProvider
from .contracts import PipelineError, digest, fingerprint
from .timing import half_up


def model_fingerprint(directory):
    files = sorted(p for p in Path(directory).rglob('*') if p.is_file())
    if not files or any(p.is_symlink() for p in files):
        raise PipelineError('MODEL_INCOMPATIBLE', '模型目录为空或包含符号链接')
    return fingerprint([{'path':str(p.relative_to(directory)), 'sha256':digest(p)} for p in files])


def observed_words(words, chars, ticks):
    """缺失的字符不能被 WhisperX word interpolation 伪装成 observed。"""
    import math
    from fractions import Fraction
    text = ' '.join(w['alignment_text'] for w in words)
    if ''.join(c['char'] for c in chars) != text:
        raise PipelineError('MODEL_INCOMPATIBLE', 'WhisperX 原始 chars 与规范化输入不一致')
    output, offset = [], 0
    for word in words:
        portion = chars[offset:offset+len(word['alignment_text'])]
        voiced = [c for c in portion if c['char'].isalnum()]
        valid = bool(voiced) and all(isinstance(c.get('start'), (float,int)) and isinstance(c.get('end'), (float,int))
                                    and math.isfinite(c['start']) and math.isfinite(c['end']) and c['end'] > c['start'] >= 0 for c in voiced)
        interval = None
        if valid:
            interval = {'start_tick':half_up(Fraction(str(min(c['start'] for c in voiced))) * ticks),
                        'end_tick':half_up(Fraction(str(max(c['end'] for c in voiced))) * ticks)}
            valid = interval['end_tick'] > interval['start_tick']
        scores = [c['score'] for c in voiced if c.get('score') is not None and math.isfinite(c['score'])]
        output.append({'id':word['id'], 'text':word['text'], 'interval':interval if valid else None,
                       'timing_status':'observed' if valid else 'unaligned',
                       'alignment_score':sum(scores)/len(scores) if scores else None})
        offset += len(word['alignment_text'])+1
    return output


class WhisperXAligner:
    """生产 venv 只运行协议；CPU 推理在用户指定的独立 Python 环境中。"""
    def __init__(self, python, model_directory, nltk_directory, package_version, timeout=600, lock_directory=None):
        self.model_directory = Path(model_directory).resolve()
        self.nltk_directory = Path(nltk_directory).resolve()
        self.weights_sha256 = model_fingerprint(self.model_directory)
        self.package_version = package_version
        worker = Path(__file__).resolve().parents[3] / 'scripts/follow_along_whisperx_worker.py'
        self.provider = ExternalProvider([str(Path(python).resolve()), str(worker)], 'whisperx-raw-chars/1', self.weights_sha256, timeout)
        self.lock_directory = lock_directory or Path.home() / 'Library/Application Support/VideoProcessing/follow-along-model-slot'
        self.identity = {'adapter':'whisperx-raw-chars/1', 'weights_sha256':self.weights_sha256,
                         'package_version':package_version, 'actual_device':'cpu', 'worker_sha256':digest(worker)}

    def align(self, audio, words, windows, directory, ticks=48000):
        self.lock_directory.mkdir(parents=True, exist_ok=True)
        with (self.lock_directory / 'inference.lock').open('a+') as lock:
            started = time.monotonic()
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic()-started >= 60:
                        raise PipelineError('RESOURCE_TIMEOUT', '模型单名额等待超时')
                    time.sleep(.1)
            request = {'operation':'align', 'audio':str(audio), 'words':words, 'windows':windows, 'ticks_per_second':ticks,
                       'revision':self.provider.revision, 'weights_sha256':self.weights_sha256,
                       'model_directory':str(self.model_directory), 'nltk_directory':str(self.nltk_directory),
                       'package_version':self.package_version}
            return self.provider.execute(request, directory, pass_fds=(lock.fileno(),))
