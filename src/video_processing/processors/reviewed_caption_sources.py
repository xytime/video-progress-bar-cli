"""具名故障原片的保留画面版式；只接受已复核的原片及完整对白。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 三条已查明标题叠字的故障采用独立字幕区，不擦字、不裁切。 |
"""
from pathlib import Path

from ..utils.caption_checkpoints import fingerprint, valid_segments
from ..utils.render_source_binding import digest


SOURCES = {
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


def reviewed_layout(source, source_hash):
    record = SOURCES.get(source.stem)
    if record is None:
        return None
    if source_hash != record['source_sha256']:
        raise ValueError('具名故障版式原片摘要不符，需要重新复核')
    # 旧凭证会比对 profile；分离的登记表/校验实现变化同样使旧版式凭证失效。
    return dict(profile=f'{source.stem}-framed-v1-{digest(Path(__file__))[:12]}',
                source_sha256=source_hash)


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
