"""以真实宽度、停顿和语法启发式求解可行分段，不删除词。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-07 | Codex | 带合法语义边界端口的动态规划分段 |
"""
from math import inf
from .contracts import PipelineError


def partition(words, capacity, measure, min_silence_tick, legal_boundaries=None):
    """measure(i,j) 由后端度量；语义 cue 分段仅允许已映射的双语边界。

    英文视觉折行可用全部边界，不改变 cue/中文意群；语义分段调用者应
    传入 legal_boundaries，禁止按词数比例伪造翻译。
    """
    n=len(words)
    if not 0 < n <= 512:
        raise PipelineError('LAYOUT_OVERFLOW','意群为空或超过有界分段预算')
    legal = set(range(n+1)) if legal_boundaries is None else set(legal_boundaries) | {0,n}
    costs, previous = [inf]*(n+1), [None]*(n+1)
    costs[0]=0
    articles={'a','an','the','this','that','my','your','our','to'}
    for end in range(1,n+1):
        if end not in legal:
            continue
        for start in range(end):
            if start not in legal or costs[start]==inf:
                continue
            width=measure(start,end)
            if width > capacity:
                continue
            cost=1 + ((capacity-width)/capacity)**2
            if end<n:
                left,right=words[end-1],words[end]
                if left['text'].lower().strip('.,;:!?') in articles:
                    cost+=4
                if left.get('boundary_punctuation') or left['text'].endswith(('.',',',';',':','!','?')):
                    cost-=.35
                a,b=left.get('interval'),right.get('interval')
                if a and b and b['start_tick']-a['end_tick']>=min_silence_tick:
                    cost-=.5
            if costs[start]+cost < costs[end]:
                costs[end],previous[end]=costs[start]+cost,start
    if previous[n] is None:
        raise PipelineError('TRANSLATION_MAPPING_MISSING','无法在可读容量内找到合法双语/词边界')
    result=[]
    end=n
    while end:
        start=previous[end]
        result.append((start,end))
        end=start
    return list(reversed(result))
