"""字幕候选的有效修复与全片放行编排；通用文案/标题质量门保持独立。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-27 | Codex | 清理失配词注、定点修复及全片范围审计，保留原始问题和候选。 |
"""
from dataclasses import replace

from .subtitle_sparse_policy import build_sparse_quality_report, _repair_covers
from .subtitle_translation_provider import SubtitleTranslationCandidate
from .translation_quality_guard import QualityIssue
from .subtitle_translation_quality import SubtitleTranslationQualityDecision


def prepare_subtitle_candidate(candidate, segments, *, context_text, repair=None):
    """修复回调只处理指定全片段号；没有实际修复证据不能使用新增容错。"""
    texts = [segment['text'] for segment in segments]
    history = list(candidate.repair_history)
    vocabs, removed = [], []
    for index, (source, translated) in enumerate(zip(texts, candidate.translations)):
        raw = candidate.vocabs[index] if index < len(candidate.vocabs) else {}
        clean = {}
        for english, chinese in (raw.items() if isinstance(raw, dict) else [('', '')]):
            if (isinstance(english, str) and english.strip() and english.casefold() in source.casefold()
                    and isinstance(chinese, str) and chinese.strip() and chinese in translated):
                clean[english] = chinese
            else:
                removed.append(dict(segment_number=index + 1, source_id=index,
                                    code='VOCAB_ALIGNMENT_MISMATCH', severity='P2'))
        vocabs.append(clean)
    if removed:
        history.append(dict(strategy='host_vocab_sanitization', executed=True,
                            segment_numbers=sorted({row['segment_number'] for row in removed}), details=removed))
    candidate = replace(candidate, vocabs=vocabs, repair_history=history)
    report = build_sparse_quality_report(segments, candidate.translations, context_text=context_text,
                                         vocabs=vocabs, repair_history=history)
    targets = sorted({issue['segment_number'] for issue in report['issues']
                      if not _repair_covers(issue, history)})
    if targets and repair:
        observation = dict(strategy='quality_observation', executed=False,
                           segment_numbers=targets, details=report['issues'],
                           translations=[candidate.translations[i - 1] for i in targets])
        candidate = replace(candidate, repair_history=[*history, observation])
        repaired = repair(candidate, targets[:10])
        if (repaired is not None and not repaired.contract_error_for(len(segments))
                and all(repaired.translations[index] == candidate.translations[index]
                        for index in range(len(segments)) if index + 1 not in targets[:10])):
            candidate = repaired
        report = build_sparse_quality_report(segments, candidate.translations, context_text=context_text,
                                             vocabs=candidate.vocabs, repair_history=candidate.repair_history)
    return replace(candidate, quality_report=report)


def sparse_quality_decision(candidate, *, final_provider, quality_context=None):
    """保留 P0 原级别；允许继续只改变动作，不将事实错误伪装成正确。"""
    report = candidate.quality_report
    issues = [QualityIssue(**{key: row.get(key, '') for key in
               ('severity', 'code', 'message', 'source_signal', 'translation_signal', 'suggested_fix')})
              for row in [*report['issues'], *report['global_warnings']]]
    if report['removed_vocab_issues'] and not issues:
        issues.append(QualityIssue(severity='P2', code='VOCAB_ALIGNMENT_SANITIZED',
                                  message='失配词注已移除，正文保持。',
                                  source_signal='source_preserved', translation_signal='invalid_vocab_removed'))
    accepted = report['status'] in {'clean', 'accepted_with_warnings'}
    return SubtitleTranslationQualityDecision(
        provider=candidate.provider, accepted=accepted, status=report['status'],
        action='accept' if accepted else 'fail' if final_provider else 'fallback',
        warning_issues=issues if accepted else [], blocking_issues=[] if accepted else issues,
        quality_context=quality_context,
    )
