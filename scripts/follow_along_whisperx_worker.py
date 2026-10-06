"""用户指定隔离 Python 环境运行的离线 WhisperX CPU worker。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-07 | Codex | 本地权重、有限窗口、无隐式下载与原字符证据 |
"""
import argparse
from importlib.metadata import version
import json
from pathlib import Path
import sys
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from video_processing.follow_along.contracts import PipelineError
from video_processing.follow_along.whisperx_adapter import model_fingerprint, observed_words


def execute(request):
    if version('whisperx') != request['package_version']:
        raise PipelineError('MODEL_INCOMPATIBLE','WhisperX 安装版本与冻结版本不符')
    if model_fingerprint(Path(request['model_directory'])) != request['weights_sha256']:
        raise PipelineError('MODEL_INCOMPATIBLE','本地模型文件指纹不符')
    import nltk
    nltk.data.path = [request['nltk_directory']]
    nltk.data.find('tokenizers/punkt_tab/english/')  # 缺少时立即失败，不触发下载。
    with wave.open(request['audio']) as stream:
        if stream.getframerate()!=16000 or stream.getnchannels()!=1 or stream.getsampwidth()!=2:
            raise PipelineError('INPUT_INVALID','WhisperX 输入须为 16k mono PCM16')
        duration = stream.getnframes()/16000
    import whisperx
    model, metadata = whisperx.load_align_model(language_code='en', device='cpu', model_name=request['model_directory'], model_cache_only=True)
    words_by_id = {w['id']:w for w in request['words']}
    results, raw, seen = [], [], []
    previous = 0
    ticks = request['ticks_per_second']
    for window in request['windows']:
        start,end = window['start_tick']/ticks, window['end_tick']/ticks
        if not 0 <= start < end <= duration or end-start > 30 or start < previous:
            raise PipelineError('ALIGNMENT_AMBIGUOUS','窗口须有序、不重叠且不超过30秒')
        previous=end
        words=[words_by_id[i] for i in window['word_ids']]
        text=' '.join(w['alignment_text'] for w in words)
        if any(c.lower() not in metadata['dictionary'] for c in text if c.isalnum()):
            raise PipelineError('ALIGNMENT_INCOMPLETE','词含词表外字符，需要可逆 spoken-form 规范化')
        aligned=whisperx.align([{'text':text,'start':start,'end':end}],model,metadata,request['audio'],'cpu',return_char_alignments=True)
        chars=[c for s in aligned['segments'] for c in s.get('chars',[])]
        raw.append({'window':window,'alignment':aligned})
        results.extend(observed_words(words, chars, ticks))
        seen.extend(window['word_ids'])
    if seen != [w['id'] for w in request['words']]:
        raise PipelineError('ALIGNMENT_INCOMPLETE','粗窗口没有完整覆盖原词序列')
    return {'revision':request['revision'],'weights_sha256':request['weights_sha256'],'actual_device':'cpu',
            'package_version':version('whisperx'), 'words':results,'raw_windows':raw}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--request',type=Path,required=True)
    parser.add_argument('--response',type=Path,required=True)
    args=parser.parse_args()
    result=execute(json.loads(args.request.read_text()))
    args.response.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))


if __name__=='__main__':
    main()
