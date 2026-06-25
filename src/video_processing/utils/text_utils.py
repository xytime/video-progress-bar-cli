"""文本处理工具 — 标题优雅截断等纯函数

单一真相源：管线（pipeline_manager）、文案器（copywriter）、上传器（wechat_uploader）
共用 graceful_truncate_title。此前实现位于 scripts/copywriter.py，导致 pipeline_manager
反向 import scripts/（违反依赖 DAG）。下沉至 utils/ 后，core 层不再依赖 scripts 层。

# Modification History
| Version | Date       | Author          | Description                                                       |
|---------|------------|-----------------|------------------------------------------------------------------|
| 1.0.0   | 2026-06-22 | Claude_Opus_4.8 | 从 scripts/copywriter.py 下沉 graceful_truncate_title，消除 pipeline_manager→scripts 反向依赖；算法逐字保留（含 v1.10.0 悬空词惩罚评分） |
| 1.1.0   | 2026-06-22 | Claude_Opus_4.8 | [🅴 反搬运·零渲染] 新增 verbatim_overlap_ratio：度量文案对源描述的逐字照搬比例，作原创度信号 |
"""
import re


def graceful_truncate_title(title: str, max_len: int = 16, min_len: int = 6) -> str:
    """优雅截断短标题，保证截断后语义完整。

    算法：预处理净化（括号剔除）+ 正则分词 + 滑动窗口穷举 + 首部语义优先排序
    1. 预处理：对于超长标题，优先移除括号/方括号内的补充说明，避免其占据宝贵的短标题字数或导致分词不当
    2. 将处理后的标题按常见分隔符（：、，、|、—、空格等）切分为 token 列表（保留分隔符）
    3. 穷举所有 contiguous token 子序列，收集满足 [min_len, max_len] 的候选
    4. 按 (起始位置升序, 长度降序) 排序，优先保留最左侧（最核心）的语义段
    5. 若无任何合规候选，则进行安全兜底裁剪（末尾虚词/标点剔除）

    Args:
        title:   原始标题字符串（可能超出 max_len）
        max_len: 最大允许字符数，默认 16（微信视频号上限）
        min_len: 最小允许字符数，默认 6（微信视频号下限）

    Returns:
        满足 [min_len, max_len] 的最优子段，实在无法满足则返回安全截断结果
    """
    title = title.strip()
    if len(title) <= max_len:
        return title

    # 1. 预处理：优先移除括号/方括号内的辅助信息 (Try It and See / 尝试一下看看)
    cleaned_title = re.sub(r'\([^)]*\)|（[^）]*）|\[[^\]]*\]|【[^】]*】', '', title).strip()
    cleaned_title = re.sub(r'\s*，\s*，', '，', cleaned_title)
    cleaned_title = re.sub(r'\s*,\s*,', ',', cleaned_title)
    cleaned_title = re.sub(r'\s+', ' ', cleaned_title)

    if min_len <= len(cleaned_title) <= max_len:
        return cleaned_title

    title_for_trunc = cleaned_title if len(cleaned_title) >= min_len else title
    if len(title_for_trunc) <= max_len:
        return title_for_trunc

    # 2. 正则分词，捕获组保留分隔符本身
    sep_pattern = r'([：:\s|｜—–\-+，,、；;]+)'
    tokens = re.split(sep_pattern, title_for_trunc)

    candidates: list[tuple[int, int, str]] = []
    n = len(tokens)

    # 3. 穷举所有以文本段（偶数索引）为起止 of 连续子序列
    for i in range(0, n, 2):
        for j in range(i, n, 2):
            joined = "".join(tokens[i:j + 1]).strip()
            # 清除两端残留分隔符
            cleaned = re.sub(r'^[：:\s|｜—–\-+，,、；;]+|[：:\s|｜—–\-+，,、；;]+$', '', joined)
            if min_len <= len(cleaned) <= max_len:
                # 记录 (起始位置 i, 实际长度) — 排序时优先选最左侧起始（x[0] 越小越好），长度越长越好（-x[1] 越小越好）
                candidates.append((i, len(cleaned), cleaned))

    if candidates:
        # [Gemini_3.1_Pro_High_planning] v1.10.0 核心优化点：引入质量评分惩罚悬空词和转折词
        def score_candidate(cand_tuple):
            start_idx, length, text = cand_tuple
            score = start_idx  # 基础分是起始位置，越小越好 (即优先靠左)
            # 惩罚悬空陈述词结尾
            if re.search(r'(表示|认为|指出|宣布|警告|谈到|说|称|直言|坦言|解析|探讨|强调|证实|透露|预计|预测|建议|呼吁|提醒|坚信)$', text):
                score += 100
            # 惩罚以转折词或连词开头
            if re.match(r'^(但是|但|而且|并且|和|与|或|以及|却)', text):
                score += 50
            # 多余的单边引号惩罚
            if text.count('“') != text.count('”') or text.count('"') % 2 != 0:
                score += 30
            # 长度得分，越长越好，转为负数加上去，影响较小
            score -= (length * 0.1)
            return score

        candidates.sort(key=score_candidate)
        return candidates[0][2]

    # 4. 兜底裁剪：先去末尾标点，再按字符硬截，最后剔除末尾虚词/连接词
    safe = re.sub(r'[？?！!。，,：:\s]+$', '', title_for_trunc)
    if len(safe) <= max_len:
        return safe
    truncated = safe[:max_len]
    truncated = re.sub(r'[的得地与和或而将于在以等着了]$', '', truncated)
    truncated = re.sub(r'[：:，,|｜\s]+$', '', truncated).strip()
    return truncated


def verbatim_overlap_ratio(generated: str, source: str, min_run: int = 8) -> float:
    """度量 generated 有多大比例是「逐字照搬」自 source 的连续片段（反搬运原创度信号）。

    [Claude_Opus_4.8] 🅴 零渲染反搬运：用于检测微信文案是否大段照搬 YouTube 原始描述
    （如 Gemini 退化为复述、或降级路径直接贴原文）。大小写不敏感。

    算法：取 source 的全部 min_run 长度滑窗子串集合；扫描 generated，把命中该集合的
    位置标记为「被覆盖」；返回 覆盖字符数 / len(generated)。

    Args:
        generated: 生成文案（被检方）。
        source:    源描述（参照方）。
        min_run:   判定「逐字照搬」的最小连续字符数（默认 8）。

    Returns:
        [0.0, 1.0] 区间的覆盖比例。任一方短于 min_run 时返回 0.0。
    """
    g = (generated or "").lower()
    s = (source or "").lower()
    if len(g) < min_run or len(s) < min_run:
        return 0.0
    grams = {s[i:i + min_run] for i in range(len(s) - min_run + 1)}
    covered = [False] * len(g)
    for i in range(len(g) - min_run + 1):
        if g[i:i + min_run] in grams:
            for k in range(i, i + min_run):
                covered[k] = True
    return sum(covered) / len(g)
