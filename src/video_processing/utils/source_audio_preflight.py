"""无源字幕时仅下载音频并本地转写；输出仍必须经过主流程内容审查。

依赖：pipeline_manager -> 本模块 -> settings/YouTube 路由；不调用发布器。
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def transcript(video, output, run, python, settings):
    from .youtube_route import youtube_cli_args, youtube_environment, verify_youtube_route
    from .subprocess_env import build_subprocess_env
    yid = video['youtube_id']
    duration = float(video.get('duration_sec') or 0)
    if not 0 < duration <= settings.source_audio_max_duration_seconds:
        raise ValueError('AUDIO_DURATION_UNVERIFIED: 需已知且不超过上限的完整时长')
    model = Path(settings.source_audio_model_path).expanduser()
    if not model.is_file():
        raise ValueError('LOCAL_MODEL_MISSING: 不自动联网下载模型')
    directory = Path(output) / 'source_audio_preflight' / hashlib.sha256(yid.encode()).hexdigest()
    directory.mkdir(parents=True, exist_ok=True)
    receipt = directory / 'transcript.json'
    fingerprint = {'youtube_id': yid, 'duration': duration, 'model_sha256': digest(model), 'recipe': 1}
    if receipt.exists():
        saved = json.loads(receipt.read_text())
        if saved.get('fingerprint') == fingerprint and saved.get('text'):
            return saved['text']
    attempts = directory / 'attempts.json'
    state = json.loads(attempts.read_text()) if attempts.exists() else {'count': 0}
    if state['count'] >= settings.source_audio_max_attempts:
        raise ValueError('AUDIO_ATTEMPTS_EXHAUSTED: 需具名检查后恢复')
    state.update(count=state['count'] + 1, started_at=time.time())
    temp = attempts.with_suffix('.tmp')
    temp.write_text(json.dumps(state)); temp.replace(attempts)
    deadline = time.monotonic() + settings.source_audio_preflight_timeout_seconds
    def execute(command, **kwargs):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('音频预检总预算耗尽')
        return run(command, yid, slice_index=video.get('slice_index', 0),
                   isolate_process_group=True, timeout=remaining, text=True, capture_output=True, **kwargs)
    verify_youtube_route()
    execute([settings.ytdlp_path, *youtube_cli_args(), '--no-playlist',
             '-f', 'bestaudio[abr<=128]/bestaudio', '--max-filesize', '50M',
             *settings.get_yt_cookie_args(), '-o', str(directory / 'audio.%(ext)s'),
             f'https://youtu.be/{yid}'], env=youtube_environment(build_subprocess_env()))
    audio = [p for p in directory.glob('audio.*') if p.suffix in {'.m4a', '.webm', '.opus', '.ogg', '.mp3'}]
    if len(audio) != 1:
        raise ValueError('AUDIO_ARTIFACT_INVALID')
    wav = directory / 'screen.wav'
    execute([settings.ffmpeg_path or "ffmpeg", '-nostdin', '-y', '-i', str(audio[0]),
             '-vn', '-ar', '16000', '-ac', '1', str(wav)])
    # 完整音轨时长必须与候选一致，禁止用截断片段冒充全文审查。
    import wave
    with wave.open(str(wav)) as stream:
        actual = stream.getnframes() / stream.getframerate()
    if abs(actual - duration) > max(5, duration * .02):
        raise ValueError('AUDIO_DURATION_MISMATCH')
    result = directory / 'asr.json'
    execute([python, '-m', __name__, str(wav), str(model), str(result)])
    data = json.loads(result.read_text())
    text = data.get('text', '').strip()
    if len(text) < 20:
        raise ValueError('AUDIO_TRANSCRIPT_EMPTY')
    temporary = receipt.with_suffix('.tmp')
    temporary.write_text(json.dumps({'fingerprint': fingerprint, 'text': text,
                                    'audio_sha256': digest(audio[0]), 'actual_duration': actual}, ensure_ascii=False))
    temporary.replace(receipt)
    return text


if __name__ == '__main__':
    import whisper
    wav, model_path, result_path = sys.argv[1:]
    model = whisper.load_model(model_path, device='cpu')
    result = model.transcribe(wav, fp16=False, verbose=False)
    # 不用高无声概率的幻觉片段作为审核依据。
    segments = [s for s in result.get('segments', []) if s.get('no_speech_prob', 0) < .6]
    text = ' '.join(s['text'].strip() for s in segments)
    Path(result_path).write_text(json.dumps({'text': text}, ensure_ascii=False))
