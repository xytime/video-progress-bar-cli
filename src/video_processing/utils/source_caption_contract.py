"""原字幕分流的宿主合同；OCR 和模型输出是证据，不直接授予跳过字幕权限。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-31 | Codex | 新增独立抽样正向保留证据，不改历史逐帧合同或负向结论。 |
| 1.0.0 | 2026-10-27 | Codex | 三态分流、逐对白覆盖检查及单片证据绑定。 |
"""
import hashlib
import json
import math
from pathlib import Path

VERSION = 'source-chinese-v1'


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False).encode()).hexdigest()


def decision_path(output: Path) -> Path:
    return output.with_suffix('.source-captions.json')


def evidence_path(output: Path) -> Path:
    return output.with_suffix('.source-captions.evidence.json')


def validate_decision(output: Path) -> dict:
    data = json.loads(decision_path(output).read_text(encoding='utf-8'))
    entry = data['entry']
    evidence = json.loads(evidence_path(output).read_text(encoding='utf-8'))
    if (data['sha256'] != fingerprint(entry) or entry['version'] != VERSION
            or entry['evidence_sha256'] != fingerprint(evidence)
            or entry['source_sha256'] != evidence['source_sha256']
            or entry['asr_sha256'] != fingerprint(evidence['segments'])):
        raise ValueError('原字幕识别证据已变更，需重新核验')
    expected = decide(evidence)
    if any(entry.get(key) != value for key, value in expected.items()):
        raise ValueError('原字幕决定与宿主覆盖校验不一致')
    return entry


def decide(evidence: dict) -> dict:
    """分别验证获批的抽样正向证据与原完整覆盖合同；不接受模型总分。"""
    def result(decision, reason, text=''):
        return dict(decision=decision, reason=reason, review_text=text)

    if evidence.get('error'):
        return result('REVIEW', evidence['error'])
    if evidence.get('inspection_mode'):
        from .caption_sampling_contract import MODE, decide_sampled
        if evidence['inspection_mode'] != MODE:
            return result('REVIEW', '未知原字幕检查方式')
        return decide_sampled(evidence)
    segments, runs = evidence['segments'], evidence['runs']
    fps, count = evidence['fps'], evidence['frame_count']
    if not segments or not math.isfinite(fps) or fps <= 0 or count < 1:
        return result('REVIEW', '缺少有效对白或完整帧证据')
    reviews = evidence.get('reviews', [])
    if len(reviews) != len(segments) or [r.get('segment_id') for r in reviews] != list(range(len(segments))):
        return result('REVIEW', '对白语义审查缺失或编号不一致')
    run_map = {r['id']: r for r in runs}
    if len(run_map) != len(runs):
        return result('REVIEW', 'OCR 字幕编号重复')
    # 一个字幕 run 连续覆盖全部相同文字的帧，零星字、画面标题也保留给审查者。
    selected, absent = [], 0
    for index, (segment, review) in enumerate(zip(segments, reviews)):
        if review.get('decision') == 'ABSENT':
            if review.get('run_ids'):
                return result('REVIEW', '无字幕结论含字幕引用')
            absent += 1
            continue
        if review.get('decision') != 'COMPLETE' or not review.get('run_ids'):
            return result('REVIEW', f'第 {index + 1} 段对白字幕不完整或无法确认')
        ids = review['run_ids']
        if len(set(ids)) != len(ids) or any(i not in run_map for i in ids):
            return result('REVIEW', '审查引用不存在或重复的字幕')
        matched = [run_map[i] for i in ids]
        visually_verified = review.get('visual_verified_run_ids', [])
        if not set(ids).issubset(visually_verified):
            return result('REVIEW', '中文字幕缺少逐种文字的实际画面复核')
        if any(r['confidence'] < .50 or not r['chinese'] for r in matched):
            return result('REVIEW', '中文字幕识别置信度不足')
        start, end = segment['start'], segment['end']
        if not (0 <= start < end <= count / fps + 1 / fps):
            return result('REVIEW', '对白时间超出完整视频范围')
        # 逐帧覆盖，容许极短切字/时间对齐空隙：总量最多 5%，连续最多 250ms。
        first, last = math.floor(start * fps), min(count, math.ceil(end * fps))
        covered = [any(r['first'] <= frame < r['last'] for r in matched)
                   for frame in range(first, last)]
        gap, max_gap = 0, 0
        for present in covered:
            gap = 0 if present else gap + 1
            max_gap = max(max_gap, gap)
        if (not covered or sum(covered) / len(covered) < .95 or max_gap / fps > .25):
            return result('REVIEW', f'第 {index + 1} 段对白中文字幕时间覆盖不足')
        selected.extend(ids)
    if absent == len(segments):
        return result('GENERATE', '逐段核验未发现对白对应的中文字幕')
    if absent:
        return result('REVIEW', '仅部分对白已有中文字幕')
    ordered = sorted(set(selected), key=lambda key: (run_map[key]['first'], key))
    text = '\n'.join(s['text'] for s in segments) + '\n' + '\n'.join(run_map[i]['text'] for i in ordered)
    return result('PRESERVE', '逐段语义及整片逐帧覆盖检查通过', text)
