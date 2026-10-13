"""字幕绑定的生词片尾：离线抽取、独立成片、内容指纹断点续跑。

依赖：pipeline / CLI -> 本模块 -> vocabulary.leveler / Pillow / pysubs2。
不访问数据库、网络、发布器，不修改基础成片。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-13 | Codex | 接入已确认的三词分页、3 秒翻页和字幕绑定缓存 |
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile

import pysubs2

from .vocabulary_outro_layout import LOGO, PAGE_SECONDS, PAGE_SIZE
VERSION = 'approved-v4-1'


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def clean(text: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'\{[^}]*\}', '', text).replace(r'\N', ' ').replace(r'\n', ' ')).strip()


def extract_items(subtitle: Path) -> list[dict]:
    """只从同一 ASS 的 GlossaryCard 抽取，且必须在同时间主字幕中出现。"""
    subs = pysubs2.load(str(subtitle))
    main = [e for e in subs if not e.is_comment and e.style != 'GlossaryCard']
    items, seen = [], set()
    for event in sorted(subs, key=lambda e: e.start):
        if event.is_comment or event.style != 'GlossaryCard':
            continue
        # 项目词汇卡以三个空格分隔词条；先去标签，后拆条，不能先压缩空格。
        raw = re.sub(r'\{[^}]*\}', '', event.text).replace(r'\N', ' ')
        raw = re.sub(r'^\s*词汇\s*', '', raw)
        contexts = [clean(e.text) for e in main if e.start < event.end and e.end > event.start]
        for part in re.split(r'\s{3,}', raw):
            word, sep, meaning = part.partition('·')
            word, meaning = word.strip(), meaning.strip()
            key = word.casefold()
            if not sep or not meaning or not re.search('[a-zA-Z]', word) or key in seen:
                continue
            pattern = re.compile(r'(?<![A-Za-z])' + re.escape(word) + r'(?![A-Za-z])', re.I)
            context = next((c for c in contexts if pattern.search(c) and meaning in c), None)
            if context is None:
                continue
            # 双语行只取英文；保留原句内容，不挪用其他视频的例句。
            context = re.split(r'[\u3400-\u9fff]', context, maxsplit=1)[0].strip()
            context = context.rstrip('“「')
            items.append(dict(word=word, meaning_zh=meaning, context_sentence=context,
                              excerpt=context, start=event.start / 1000,
                              timestamp=f'{event.start // 60000:02}:{event.start // 1000 % 60:02}',
                              phonetic='', pos=''))
            seen.add(key)
    return items


def enrich_items(items: list[dict], subtitle: Path) -> None:
    """音标/词性可复用同身份、同词、同时间的导出元数据；否则离线查词。"""
    from video_processing.vocabulary.leveler import VocabularyLeveler
    sidecar = subtitle.with_name(subtitle.stem + '_vocabulary.json')
    metadata = []
    if sidecar.is_file():
        try:
            raw = json.loads(sidecar.read_text())
            if raw.get('video_id') == subtitle.stem:
                metadata = raw.get('items', [])
        except (ValueError, OSError):
            pass
    leveler = VocabularyLeveler()
    leveler.prepare_words([i['word'] for i in items])
    for item in items:
        candidate = next((m for m in metadata if isinstance(m, dict)
                          and m.get('word') == item['word']
                          and m.get('meaning_zh') == item['meaning_zh']
                          and isinstance(m.get('start'), (int, float))
                          and abs(m['start'] - item['start']) < .05), {})
        result = leveler.analyze_word(item['word'], context=item['context_sentence'])
        phonetic = candidate.get('phonetic') or result.phonetic
        item['phonetic'] = '/' + str(phonetic).strip('/') + '/' if phonetic else '—'
        item['pos'] = str(candidate.get('pos') or result.pos or '')


def fingerprint(source: Path, subtitle: Path, title: str) -> dict:
    sidecar = subtitle.with_name(subtitle.stem + '_vocabulary.json')
    return dict(version=VERSION, source=str(source.resolve()), source_sha256=sha256(source),
                subtitle=str(subtitle.resolve()), subtitle_sha256=sha256(subtitle), title=title,
                metadata_sha256=sha256(sidecar) if sidecar.is_file() else None,
                logo_sha256=sha256(LOGO), page_seconds=PAGE_SECONDS)


def receipt_path(output: Path) -> Path:
    return output.with_suffix('.receipt.json')


def valid_outro(source: Path, subtitle: Path, output: Path, title: str | None = None) -> bool:
    try:
        receipt = json.loads(receipt_path(output).read_text())
        expected = fingerprint(source, subtitle, receipt['inputs']['title'] if title is None else title)
        return (receipt['inputs'] == expected and receipt['status'] == 'rendered'
                and output.is_file() and receipt['output_sha256'] == sha256(output))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def probe(path: Path) -> dict:
    return json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
                      '-show_format', '-of', 'json', str(path)], text=True, timeout=30))


def build(source: Path, subtitle: Path, output: Path, title: str) -> Path:
    """只写独立派生成片；失败不留下可选中的半成品，重复运行不重复追加。"""
    if source.resolve() == output.resolve():
        raise ValueError('片尾输出不得覆盖源视频')
    allowed = {subtitle.stem + ending for ending in ('.mp4', '_vertical.mp4', '_vertical_interactive.mp4', '_insight.mp4')}
    if source.name not in allowed:
        raise ValueError('源视频与字幕身份不匹配')
    inputs = fingerprint(source, subtitle, title)
    if valid_outro(source, subtitle, output, title):
        return output
    items = extract_items(subtitle)
    info = probe(source)
    duration = float(info['format']['duration'])
    items = [i for i in items if i['start'] < duration]
    if not items:
        # 旧片尾不可继续被选中；基础视频保留。
        receipt_path(output).unlink(missing_ok=True)
        return source
    enrich_items(items, subtitle)
    from .vocabulary_outro_layout import render_cards, render_outro
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.vocab-', dir=output.parent) as temp:
        temp = Path(temp)
        cards = render_cards(items, title)
        outro = temp / 'outro.mp4'
        render_outro(cards, outro)
        video = next(s for s in info['streams'] if s['codec_type'] == 'video')
        width, height, rate = video['width'], video['height'], video['r_frame_rate']
        audio = any(s['codec_type'] == 'audio' for s in info['streams'])
        command = ['ffmpeg', '-v', 'error', '-i', str(source), '-i', str(outro)]
        if not audio:
            command += ['-f', 'lavfi', '-t', str(duration), '-i', 'anullsrc=r=44100:cl=stereo']
        graph = (f'[0:v]setsar=1,setpts=PTS-STARTPTS[v0];'
                 f'[1:v]scale={width}:{height}:force_original_aspect_ratio=decrease,'
                 f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={rate},setsar=1,setpts=PTS-STARTPTS[v1];'
                 f'[{"0" if audio else "2"}:a]aformat=sample_rates=44100:channel_layouts=stereo,asetpts=PTS-STARTPTS[a0];'
                 '[1:a]asetpts=PTS-STARTPTS[a1];[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]')
        pending = temp / 'final.mp4'
        command += ['-filter_complex', graph, '-map', '[v]', '-map', '[a]', '-c:v', 'libx264',
                    '-preset', 'veryfast', '-crf', '19', '-threads', '4', '-r', rate,
                    '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(pending)]
        subprocess.run(command, check=True, timeout=1800)
        actual = float(probe(pending)['format']['duration'])
        expected = duration + len(cards) * PAGE_SECONDS
        if abs(actual - expected) > .3:
            raise ValueError(f'片尾时长不符: {actual} / {expected}')
        # 输入渲染途中有变化时禁止提交缓存。
        if fingerprint(source, subtitle, title) != inputs:
            raise ValueError('渲染中源视频或字幕变化')
        receipt = dict(inputs=inputs, status='rendered', items=items, pages=len(cards),
                       duration=actual, output_sha256=sha256(pending))
        for number, card in enumerate(cards, 1):
            card.save(temp / f'page-{number}.png')
        pending.replace(output)
        evidence = output.with_suffix('.pages')
        evidence.mkdir(exist_ok=True)
        for page in temp.glob('page-*.png'):
            page.replace(evidence / page.name)
        receipt_temp = temp / 'receipt.json'
        receipt_temp.write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
        receipt_temp.replace(receipt_path(output))
    return output
