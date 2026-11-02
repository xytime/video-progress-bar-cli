"""具名故障原片的保留画面版式；只接受已复核的原片及完整对白。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.5.0 | 2026-11-01 | Codex | 7146沿用完整画面布局并将字号上限设为74，保留完整长句与原安全宽度；其他来源保持默认。 |
| 1.4.1 | 2026-11-01 | Codex | 7146 绑定处理器实际校验的视频流时长164.8秒，保持原有严格容差。 |
| 1.4.0 | 2026-11-01 | Codex | 7146 绑定已复核片头标题、原片与完整 65 段对白；保留画面并复用既有独立双语区。 |
| 1.3.0 | 2026-11-01 | Codex | 默认续跑采用原片摘要绑定的已复核 ASR 模型，保留完整时间轴校验。 |
| 1.2.0 | 2026-11-01 | Codex | 7135 已复核财富差距英文标题，绑定完整 33 段对白，保留原画面。 |
| 1.1.0 | 2026-11-01 | Codex | 7031 绑定复核后的原片及 large-v3 完整对白，保留英文标题叠字。 |
| 1.0.0 | 2026-11-01 | Codex | 三条已查明标题叠字的故障采用独立字幕区，不擦字、不裁切。 |
"""
from pathlib import Path

from ..utils.caption_checkpoints import fingerprint, valid_segments
from ..utils.render_source_binding import digest


SOURCES = {
    'c4umlxsvAKg': dict(
        source_sha256='752d21452fb93bf08a155203eaf8102d3fa009d316ad143ce2c1f3d830b640e3',
        timeline_sha256='eb26f634e6acf922695120d2cbd18048bdb9776cd6640566f75a4fb2cf570d62', duration=1511/30,
        original_timeline_sha256='97da875d22cc91574e52394cb3bc0e9a92e56a3b95da99c3d22b7b3f37549d7a', chinese_only=True,
        width=712, height=1280, x=184, y=70, subtitle_top=1400, subtitle_bottom=1700,
    ),
    'RYYM-6C4Vs4': dict(
        source_sha256='f58052062dad793e8dfc6169a43ca60992c6ee74836b5d66ebfa1e765e1feff8',
        timeline_sha256='c1adf016e2d7a826062c5696fce06b217581da536cb177f7c262484ca1165f68',
        duration=164.8,
        font_size=74,
    ),
    'ZVGS33A0nK0': dict(
        source_sha256='aa91512004ed2d8a8d390e23f8d5c1d77d5dee9c349a87a6bf91cb56301a7015',
        timeline_sha256='b3a29097498762c9b277abe020b66b34566671d094237adc17e634f6b35f522a',
        duration=142.684208,
    ),
    'CatuGloDkTQ': dict(
        source_sha256='2d525f43d92280d23c845880c60a1044ff6ea342b638fb40d93eccd29d5939ed',
        timeline_sha256='3c1ae232ed2905cf0d7892db40b3d5ec742317cf8b7d1d4d599e40ff57ea9289',
        duration=121.5214,
        asr_model='large-v3',
    ),
    'z9VaYmwImt8': dict(
        source_sha256='fc19f07417a3207c60a5e3c5751289dd057d832f9cb21fba7c54c75bbd9b6777',
        timeline_sha256='314ff18a36fa2f8cf0123d3dcb4bece0ea0fecd2f823a6c7c68fce251938e354',
        duration=179.746233,
    ),
    '-D4TV5q5yOM': dict(
        source_sha256='f0f2d0665b5ef36850aef6a2b00cfb6afb1d030bc8c66650bb31115aa8afbe8e',
        timeline_sha256='0629cfb8c1fe05218097c7db75053d48945f67ebb9832aec278e65b2c793dcce',
        duration=136.1,
    ),
    '5e-k8bBMFvY': dict(
        source_sha256='7d822d90a888e8615103b4df10ff366f8d0fe587def994d4133400a06824ed36',
        timeline_sha256='7d3b373f19c87df79ca6bad83c0aaa6f5ff66793b8ec6b75167367e1419d35c1',
        duration=165.431933,
    ),
}


def reviewed_asr_model(source):
    source = Path(source)
    record = SOURCES.get(source.stem)
    if record is None or not record.get('asr_model'):
        return None
    if digest(source) != record['source_sha256']:
        raise ValueError('具名故障版式原片摘要不符，需要重新复核')
    return record['asr_model']


def reviewed_layout(source, source_hash):
    record = SOURCES.get(source.stem)
    if record is None:
        return None
    if source_hash != record['source_sha256']:
        raise ValueError('具名故障版式原片摘要不符，需要重新复核')
    # 旧凭证会比对 profile；分离的登记表/校验实现变化同样使旧版式凭证失效。
    return dict(profile=f'{source.stem}-framed-v1-{digest(Path(__file__))[:12]}',
                source_sha256=source_hash,
                **{k: record[k] for k in ('font_size', 'width', 'height', 'x', 'y', 'subtitle_top', 'subtitle_bottom') if k in record})


def validate_reviewed_timeline(segments, duration, source_hash):
    record = next((row for row in SOURCES.values() if row['source_sha256'] == source_hash), None)
    if record is None:
        return False
    if not valid_segments(segments, translated=True) or abs(duration - record['duration']) > .05:
        raise ValueError('具名故障版式需要完整双语时间轴与原片时长')
    timeline = [{key: segment[key] for key in ('start', 'end', 'text')} for segment in segments]
    if fingerprint(timeline) != record['timeline_sha256']:
        raise ValueError('具名故障版式对白或时间轴变化，需要重新复核')
    return True


def corrected_source_segments(source, segments):
    """已确认的音频修正作用于副本；原 ASR 快照保留，译文合同随正文变化。"""
    from copy import deepcopy
    source = Path(source)
    record = SOURCES.get(source.stem)
    if not record or not record.get('chinese_only'):
        return segments
    if digest(source) != record['source_sha256']:
        raise ValueError('已复核音频源片身份变化')
    timeline = [{k: s[k] for k in ('start', 'end', 'text')} for s in segments]
    identity = fingerprint(timeline)
    if identity == record['timeline_sha256']:
        return deepcopy(segments)
    if identity != record['original_timeline_sha256']:
        raise ValueError('已复核音频时间轴变化，不能套用修正')
    result = deepcopy(segments)
    changes = {3: ('albarrier-lining', 'barrier lining'),
               7: (' A multi-organ congestion, apopsis,', ' It induces multi-organ congestion, apoptosis,'),
               8: ('Hematatic', 'Hemostatic')}
    for index, (old, new) in changes.items():
        result[index]['text'] = result[index]['text'].replace(old, new)
        for key in ('tokens', 'words', 'zh_text', 'vocab'):
            result[index].pop(key, None)
    return result


def chinese_only_ass(source, source_hash, segments):
    """保留完整原英文及动画；只在画外区添加中文，不参与擦字或 OCR 对齐。"""
    record = SOURCES.get(Path(source).stem)
    if not record or not record.get('chinese_only'):
        return None
    if source_hash != record['source_sha256']:
        raise ValueError('中文补充版式源片身份变化')
    validate_reviewed_timeline(segments, record['duration'], source_hash)
    import pysubs2
    from ..utils.subtitle_failure_receipt import SubtitleReviewRequired
    subs = pysubs2.SSAFile()
    subs.info.update(PlayResX=1080, PlayResY=1920)
    subs.styles['Default'] = pysubs2.SSAStyle(fontname='Hiragino Sans GB', fontsize=48,
        primarycolor=pysubs2.Color(255,255,255), outline=2, shadow=0,
        alignment=8, marginl=80, marginr=80, marginv=1400)
    for seg in segments:
        text = seg.get('zh_text', '').strip()
        if not text or '{' in text or '}' in text or '\\' in text:
            raise SubtitleReviewRequired('中文补充字幕缺失或含未审核排版控制符')
        import textwrap
        lines = textwrap.wrap(text, width=18)
        if len(lines)>4:
            raise SubtitleReviewRequired('中文补充字幕超过独立字幕区四行上限')
        subs.events.append(pysubs2.SSAEvent(start=round(seg['start']*1000),end=round(seg['end']*1000),
            text=r'{\pos(540,1400)}'+r'\N'.join(lines)))
    path=Path(source).with_suffix('.ass')
    subs.save(str(path))
    return path
