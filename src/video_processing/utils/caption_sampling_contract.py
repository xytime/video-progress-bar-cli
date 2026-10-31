"""首中尾抽检的独立宿主合同；只允许正向保留，不生成全片无中文结论。

依赖：source_caption_contract / native_caption_sampling -> 本模块 -> 标准库。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-31 | Codex | 用户批准抽样保留及未抽到局部缺失的风险，仍保留严格负向路径。 |
"""
import math
import re

MODE = 'sampled-positive-v1'
HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')


def windows(segments, fps, count):
    """15 秒墙钟窗口，锚定实际对白；短片重叠窗口如实合并。"""
    if not segments or not math.isfinite(fps) or fps <= 0 or type(count) is not int or count < 1:
        raise ValueError('SAMPLE_TIMELINE_INVALID')
    for segment in segments:
        start, end = segment['start'], segment['end']
        if (not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end <= count / fps + 1 / fps
                or not isinstance(segment['text'], str) or not segment['text'].strip()):
            raise ValueError('SAMPLE_TIMELINE_INVALID')
    if any(a['start'] > b['start'] for a, b in zip(segments, segments[1:])):
        raise ValueError('SAMPLE_TIMELINE_INVALID')
    first, last = segments[0]['start'], min(count / fps, max(s['end'] for s in segments))
    length = min(15., last - first)
    middle = (first + last) / 2
    # 中点为无对白过场时，移到最近的对白内，不拿静音画面判定缺字幕。
    segment = min(segments, key=lambda s: max(s['start'] - middle, middle - s['end'], 0))
    middle = min(segment['end'], max(segment['start'], middle))
    starts = sorted({first, max(first, min(last - length, middle - length / 2)), last - length})
    return [dict(id=i, start=start, end=start + length) for i, start in enumerate(starts)]


def sample_frames(window, segments, fps, count, *, supplement=False):
    offset = .25 if supplement else .5
    frames = sorted({min(count - 1, math.floor((window['start'] + offset + i) * fps))
                     for i in range(math.ceil(window['end'] - window['start']))
                     if window['start'] + offset + i < window['end']})
    frames = [f for f in frames if any(s['start'] <= f / fps < s['end'] for s in segments)]
    if supplement and len(frames) > 6:
        frames = [frames[round(i * (len(frames) - 1) / 5)] for i in range(6)]
    return frames


def matched_text(sample, match):
    """语义引用必须是本帧可读的中文 OCR 行，模型不能自行补写文本。"""
    rows, ids = sample['rows'], match['row_ids']
    if (match['frame'] != sample['frame'] or not ids or len(set(ids)) != len(ids)
            or any(type(i) is not int or not 0 <= i < len(rows) for i in ids)):
        raise ValueError('未引用实际画面中文字幕')
    for i in ids:
        row = rows[i]
        if (not HAN.search(row['text']) or not math.isfinite(row['confidence'])
                or not .5 <= row['confidence'] <= 1):
            raise ValueError('中文字幕识别置信度不足')
    return ''.join(rows[i]['text'] for i in ids)


def decide_sampled(evidence):
    """所有被抽到的对白帧都需实际图像/语义正证据；不伪造逐帧覆盖。"""
    def result(decision, reason, text=''):
        return dict(decision=decision, reason=reason, review_text=text,
                    inspection_mode=MODE, full_timeline_verified=False)

    try:
        segments, fps, count = evidence['segments'], evidence['fps'], evidence['frame_count']
        planned = windows(segments, fps, count)
        if evidence['sample_windows'] != planned:
            raise ValueError('抽样窗口与实际对白不一致')
        samples, reviews = evidence['samples'], evidence['sample_reviews']
        mapped = {s['frame']: s for s in samples}
        if len(mapped) != len(samples) or [r['window_id'] for r in reviews] != list(range(len(planned))):
            raise ValueError('抽样帧或语义审查编号不一致')
        expected_all = set()
        for window, review in zip(planned, reviews):
            base = sample_frames(window, segments, fps, count)
            if type(review.get('supplemented')) is not bool:
                raise ValueError('补查记录缺失')
            extra = sample_frames(window, segments, fps, count, supplement=True) if review['supplemented'] else []
            expected = sorted(set(base + extra))
            expected_all.update(expected)
            if len(base) < 3 or review['decision'] != 'MATCH':
                raise ValueError('抽样对白不足或未一致确认中文字幕')
            if [m['frame'] for m in review['matches']] != expected:
                raise ValueError('抽样语义证据未覆盖实际抽检帧')
            texts = set()
            for match in review['matches']:
                sample = mapped[match['frame']]
                if not re.fullmatch('[a-f0-9]{64}', sample['image_sha256']):
                    raise ValueError('缺少抽检画面摘要')
                texts.add(matched_text(sample, match))
            if len(texts) < 2:
                raise ValueError('窗口内未见随对白变化的中文字幕')
        if set(mapped) != expected_all:
            raise ValueError('抽样证据存在缺帧或未核验的额外帧')
        text = '\n'.join(s['text'] for s in segments) + '\n' + '\n'.join(
            dict.fromkeys(r['text'] for s in samples for r in s['rows']))
        return result('PRESERVE', '首中尾中文字幕抽样判断通过；未验证全片逐帧完整性', text)
    except (KeyError, TypeError, ValueError, IndexError, OverflowError) as exc:
        return result('REVIEW', str(exc) if isinstance(exc, ValueError) else '抽样证据结构无效')
