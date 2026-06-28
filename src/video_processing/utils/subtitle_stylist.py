# -*- coding: utf-8 -*-
"""字幕样式工厂 — 负责 ASS 内联标签构造、动态字号缩放与折行计算

# Modification History
| Version | Date       | Author                              | Description                                                         |
| ------- | ---------- | ----------------------------------- | ------------------------------------------------------------------- |
| 1.0.0   | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | 初始创建：从 vertical_processor.py 抽取字幕样式/ASS标签/字号/折行职责，实现单一职责原则 |
| 1.0.1   | 2026-06-08 | Gemini_3.5_Flash_planning           | 修复 apply_word_highlights 中的 re.sub regex 转义错误，标注 # [Gemini_3.5_Flash_planning] |
| 1.1.0   | 2026-06-08 | Gemini_3.5_Flash_planning           | 新增 apply_chinese_highlights，在中文句子中寻找生词并绘制带颜色的下划线，标注 # [Gemini_3.5_Flash_planning] |
| 1.2.0   | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | 修复中文折行截断标签bug：将 apply_chinese_highlights 移到 textwrap.fill 之后；build_glossary_text 增加 en_size 参数以限制释义字号不超过英文主字幕字号 |
| 1.3.0   | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | 修复 apply_chinese_highlights 短词淘汰长词问题：改用 token分段方案仅在裸文本段进行匹配，封锁已标注内容 |
| 1.4.0   | 2026-06-09 | Claude_Opus_4.6_Thinking_planning   | 修复 build_glossary_text 字号 bug（gloss_size=en_size 覆盖样式层 35pt）改为 min(default,en_size)；释义区颜色改为淡色系，视觉分层 |
| 1.5.0   | 2026-06-28 | Claude_Opus_4.8                     | 修中英高亮不对称 Bug：①新增 tag_aware_wrap_zh，render() 中文路径改「先高亮→后折行」，使 vocab 词组（如「头条叙事」）不再被 \\N 从中间劈开导致 substring 失配；②tag_aware_wrap 分词器把完整高亮短语 {\\u1…}…{\\u0…}（含内部空格）当 1 个 token，避免 Wall|Street 跨行 |
"""

import re
import textwrap
from dataclasses import dataclass, field
from typing import Dict, Optional

# [Claude_Sonnet_4.6_Thinking_planning] ASS 颜色格式：BGR（注意不是 RGB！）
# 英文字幕色：暖金蓝 #3FD2FF (BGR) ≈ 近白蓝，在深色背景下高对比度
EN_COLOR = "&H3FD2FF&"
# 中文字幕色：暖灰白 #E9EFF2 (BGR)，柔和不刺眼
ZH_COLOR = "&HE9EFF2&"
# 词汇高亮色：青绿 #C7D36F (BGR)
VOCAB_HIGHLIGHT_COLOR = "&HC7D36F&"
# [Claude_Opus_4.6_Thinking_planning] 释义区专用淡色系 — 视觉分层，与主字幕拉开层级
# 释义区「词汇」标签色：淡青绿 (比主高亮色更淡)
GLOSS_LABEL_COLOR = "&HDBE5A0&"  # BGR: 淡薄荷绿
# 释义区英文词色：淡暖金（比主字幕 EN_COLOR 更柔和）
GLOSS_WORD_COLOR = "&H7FD9E8&"   # BGR: 淡金
# 释义区中文释义色：浅灰
GLOSS_TRANS_COLOR = "&HBDC5C9&"  # BGR: 浅暖灰

# [Claude_Sonnet_4.6_Thinking_planning] 动态缩放下限，防止过小无法阅读
SUBTITLE_MIN_EN_SIZE = 28
SUBTITLE_MIN_ZH_SIZE = 32

# 字体名称常量（避免到处硬编码字符串）
FONT_EN = "Georgia"
FONT_ZH = "Hiragino Sans GB"
FONT_GLOSS = "Songti SC"


@dataclass
class SubtitleLayout:
    """字幕区几何约束（单位：像素），由调用者传入，SubtitleStylist 不关心具体布局计算。

    Args:
        en_size: 初始英文字号（pt）
        zh_size: 初始中文字号（pt）
        safe_width: 字幕区安全宽度（px），用于折行计算
        max_height: 字幕区最大允许高度（px），用于动态缩放
        outline: ASS 轮廓宽度（px），用于高度估算
    """
    en_size: int
    zh_size: int
    safe_width: int
    max_height: int
    outline: int = 12

    # [Claude_Sonnet_4.6_Thinking_planning] 动态缩放迭代参数
    line_height_factor: float = 1.25
    spacer_px: int = 24
    scale_step: int = 2
    max_iterations: int = 30


@dataclass
class RenderedSubtitle:
    """单条字幕的渲染结果

    Attributes:
        ass_text: 完整的 ASS 内联标签文本（可直接写入 pysubs2.SSAEvent.text）
        en_size: 最终使用的英文字号（经动态缩放后）
        zh_size: 最终使用的中文字号（经动态缩放后）
    """
    ass_text: str
    en_size: int
    zh_size: int


def strip_trailing_punctuation(text: str) -> str:
    """[Claude_Sonnet_4.6_Thinking_planning] 去除段落末尾的半角/全角标点符号，防止折行时标点单独占行"""
    if not text:
        return text
    return re.sub(r'[\.,\?\!;\:\"\'。，？！；："、\s]+$', '', text)


def apply_word_highlights(text: str, word_colors: Dict[str, str]) -> str:
    """[Claude_Sonnet_4.6_Thinking_planning] 在英文句子中高亮重点难词并加下划线

    Args:
        text: 英文字幕原文（可能已含 ASS 标签）
        word_colors: {单词: ASS 颜色字符串} 映射

    Returns:
        注入了 {\\u1\\cCOLOR} ... {\\u0\\c} 标签的文本
    """
    if not word_colors or not text:
        return text

    # 按长度降序，优先匹配长词/短语，防止短词部分匹配
    sorted_words = sorted(word_colors.keys(), key=len, reverse=True)
    for word in sorted_words:
        word_clean = word.strip()
        if not word_clean:
            continue
        color = word_colors[word]
        pattern = re.compile(rf'\b({re.escape(word_clean)})\b', re.IGNORECASE)
        # [Gemini_3.5_Flash_planning] Escape backslashes in replacement string so re.sub receives literal backslashes
        text = pattern.sub(rf'{{\\u1\\c{color}}}\1{{\\u0\\c}}', text)
    return text


def apply_chinese_highlights(text: str, vocab_items: Dict[str, str]) -> str:
    """[Claude_Sonnet_4.6_Thinking_planning] v1.3.0 在中文字幕中高亮难词并画下划线。

    核心设计：先将 text 按 {ASS标签} 分割为 token 序列，仅在「裸文本」token
    上执行替换，已带标签的 token 完全跳过。这样即使先处理了长词（如"卓越的领导力"），
    短词（如"领导"）也不会再次匹配已被包裹的内容，消除了标签嵌套污染。

    Args:
        text: 可能含 ASS 内联标签（{...}）的中文字幕文本。
        vocab_items: {英文词: 对应中文子串} 字典。

    Returns:
        插入了高亮标签的中文字幕文本。
    """
    if not vocab_items or not text:
        return text

    # 按中文值长度降序排列，长词优先，防止短词切割长词
    zh_words = sorted(
        (v.strip() for v in vocab_items.values() if v and v.strip()),
        key=len,
        reverse=True,
    )
    if not zh_words:
        return text

    # 将 text 按 {tag} 分割为 token 列表：[bare_text, {tag}, bare_text, {tag}, ...]
    # re.split 保留分隔符（用 capture group）
    _TAG_RE = re.compile(r'(\{[^}]*\})')
    tokens: list[str] = _TAG_RE.split(text)

    # 构建 alternation pattern（长词优先）—— 单次扫描，避免短词二次匹配已标注内容
    pattern = re.compile('|'.join(re.escape(w) for w in zh_words))

    def _replace_in_bare_text(bare: str) -> str:
        """在裸文本段中，用 finditer 一次性处理所有命中，长词优先（pattern 已排序）。"""
        result_parts: list[str] = []
        last = 0
        for m in pattern.finditer(bare):
            result_parts.append(bare[last:m.start()])
            zh_word = m.group(0)
            open_tag  = '{' + '\\u1' + '\\c' + VOCAB_HIGHLIGHT_COLOR + '}'
            close_tag = '{' + '\\u0' + '\\c' + ZH_COLOR + '}'
            result_parts.append(open_tag + zh_word + close_tag)
            last = m.end()
        result_parts.append(bare[last:])
        return ''.join(result_parts)

    result_tokens: list[str] = []
    for tok in tokens:
        if _TAG_RE.fullmatch(tok):
            result_tokens.append(tok)  # {tag} 原样保留
        else:
            result_tokens.append(_replace_in_bare_text(tok))

    return ''.join(result_tokens)


def tag_aware_wrap(text: str, max_width: int) -> str:
    """[Claude_Sonnet_4.6_Thinking_planning] 标签敏感的折行函数

    忽略 ASS 样式标签（如 {\\c&H...}）的视觉长度，避免在标签内部断词。

    Args:
        text: 可能含 ASS 内联标签的英文文本
        max_width: 最大视觉字符宽度（忽略标签字符）

    Returns:
        以 \\N 分隔的折行文本
    """
    if not text:
        return text

    # [Claude_Opus_4.8] v1.5.0: 第一选择项「完整高亮短语」必须最先匹配——把
    # {\u1…}headline narrative{\u0…} / {\u1…}Wall Street{\u0…} 这类含内部空格的
    # 高亮词组整体当作 1 个 token，否则空格会把 "Wall" 与 "Street" 拆成两个 token
    # 而被折到两行，造成高亮短语被行尾劈断。
    token_pattern = re.compile(
        r'(\{\\u1[^}]*\}.*?\{\\u0[^}]*\}'          # ① 完整高亮短语（含内部空格）整体不拆
        r'|(?:\{[^\}]*\})*[^\s{]+(?:\{[^\}]*\})*'  # ② 普通词（可带前后标签）
        r'|\{[^\}]*\}'                             # ③ 独立标签
        r'|\s+)'                                   # ④ 空白
    )
    tokens = token_pattern.findall(text)

    def get_visual_len(s: str) -> int:
        return len(re.sub(r'\{[^\}]*\}', '', s))

    lines: list[str] = []
    current_line: list[str] = []
    current_len = 0

    for token in tokens:
        if not token:
            continue
        if token.isspace():
            if current_line:
                current_line.append(token)
            continue
        token_len = get_visual_len(token)
        if current_len + token_len > max_width:
            if not current_line:
                current_line.append(token)
                current_len = token_len
            else:
                lines.append("".join(current_line).rstrip())
                current_line = [token]
                current_len = token_len
        else:
            current_line.append(token)
            current_len += token_len

    if current_line:
        lines.append("".join(current_line).rstrip())

    return "\\N".join(lines)


def tag_aware_wrap_zh(text: str, max_width: int) -> str:
    """[Claude_Opus_4.8] v1.5.0 中文 tag/词-aware 折行。

    与 tag_aware_wrap（英文按空格分词）不同，中文逐字断行，但有两条不可破坏的约束：
    - {…} ASS 标签视觉宽度记为 0，且绝不在标签内部插入 \\N；
    - 完整高亮短语 {\\u1…}词{\\u0…} 作为不可分原子，绝不被 \\N 从中间劈开。
      旧逻辑「先 textwrap.fill 再高亮」会在任意字符处把「头条叙事」劈成
      「头\\N条叙事」，使 apply_chinese_highlights 的连续子串匹配失败而漏标，
      也让已标注词组被折行截断——本函数从源头杜绝。

    Args:
        text: 已施加中文高亮（含 ASS 标签）或纯中文文本。
        max_width: 每行最大可见字符数。

    Returns:
        以 \\N 分隔的折行文本。
    """
    if not text:
        return text

    # 切成原子序列：完整高亮短语 / 独立标签(0宽) / 单个可见字符(逐字断行)
    atom_pattern = re.compile(
        r'\{\\u1[^}]*\}.*?\{\\u0[^}]*\}'   # ① 完整高亮短语（含内部任意字符）整体
        r'|\{[^}]*\}'                       # ② 独立标签（视觉 0 宽）
        r'|[^{]'                            # ③ 单个可见字符
    )
    atoms = atom_pattern.findall(text)

    def visual_len(atom: str) -> int:
        return len(re.sub(r'\{[^}]*\}', '', atom))

    lines: list[str] = []
    current: list[str] = []
    current_len = 0
    for atom in atoms:
        alen = visual_len(atom)
        if alen == 0:
            # 0 宽标签：附着当前行，不触发折行
            current.append(atom)
            continue
        if current_len + alen > max_width and current:
            lines.append("".join(current))
            current = [atom]
            current_len = alen
        else:
            current.append(atom)
            current_len += alen
    if current:
        lines.append("".join(current))

    return "\\N".join(lines)


class SubtitleStylist:
    """字幕样式工厂 — 单一职责：将字幕文本转换为 ASS 内联标签文本。

    职责边界：
    - 负责：ASS 标签构造、颜色、字体、折行计算、动态字号缩放
    - 不负责：时间戳、文件写入、视频合成、布局坐标

    # [Claude_Sonnet_4.6_Thinking_planning] 设计原则
    - 无状态：每次 render() 调用均独立，不保留上一次调用的状态
    - 无副作用：不读写文件，不调用外部进程
    - 可测试：纯函数逻辑，输入确定则输出确定

    Usage::

        stylist = SubtitleStylist(layout)
        result = stylist.render(
            en_text="Hello world",
            zh_text="你好世界",
            vocab_items={"Hello": "你好，用于打招呼"},
            bilingual=True
        )
        event.text = result.ass_text
    """

    def __init__(self, layout: SubtitleLayout):
        """
        Args:
            layout: 字幕区几何约束，由 VerticalCaptionProcessor 提供
        """
        self.layout = layout

    def render(
        self,
        en_text: str,
        zh_text: str,
        vocab_items: Optional[Dict[str, str]] = None,
        bilingual: bool = True,
    ) -> RenderedSubtitle:
        """将原始字幕文本转换为带 ASS 标签的渲染文本。

        Args:
            en_text: 英文字幕原文（未经折行）
            zh_text: 中文字幕翻译（未经折行），若空则仅显示英文
            vocab_items: {单词: 释义} 词汇表，用于英文高亮
            bilingual: 是否渲染双语字幕

        Returns:
            RenderedSubtitle 包含 ass_text 和最终字号
        """
        layout = self.layout
        en_size = layout.en_size
        zh_size = layout.zh_size

        # 1. 清洗标点
        en_text = strip_trailing_punctuation(en_text)
        zh_text = strip_trailing_punctuation(zh_text)

        # 2. 英文词汇高亮（先于折行，避免英文标签被截断）
        # [Claude_Sonnet_4.6_Thinking_planning] 中文高亮故意推迟到折行之后（步骤4），
        # 确保 textwrap.fill 不会把 \N 插入 ASS 标签内部（如 {\u1\c&HC7D36F&}）
        word_colors: Dict[str, str] = {}
        if vocab_items:
            for idx, word in enumerate(vocab_items.keys()):
                # 统一使用青绿色高亮（未来可扩展为多色）
                word_colors[word] = VOCAB_HIGHLIGHT_COLOR
            en_text = apply_word_highlights(en_text, word_colors)

        # 3. 动态字号缩放：迭代缩小直至估算高度适配
        # 注意：此时 zh_text 还是纯文本（未加标签），_fit_font_size 的高度估算结果准确
        en_size, zh_size = self._fit_font_size(en_text, zh_text, en_size, zh_size)

        # 4. 以最终字号重新折行，折行后再施加中文高亮
        # [Claude_Sonnet_4.6_Thinking_planning] 折行必须在高亮之前，防止 \N 截断标签
        wrap_w_en = max(20, int(layout.safe_width / (en_size * 0.54)))
        wrap_w_zh = max(10, int(layout.safe_width / zh_size))

        if zh_text:
            # [Claude_Opus_4.8] v1.5.0: 先在「未折行的纯文本」上施加中文高亮，
            # 再用 tag/词-aware 折行（tag_aware_wrap_zh）。这样 vocab 词组作为不可分
            # 原子参与折行，绝不被 \N 从中间劈开——与英文路径（高亮→tag_aware_wrap）对称。
            # 旧顺序「textwrap.fill→高亮」会把「头条叙事」劈成「头\N条叙事」致 substring 失配漏标。
            if vocab_items:
                zh_text = apply_chinese_highlights(zh_text, vocab_items)
            zh_text = tag_aware_wrap_zh(zh_text, wrap_w_zh)
        if en_text:
            en_text = tag_aware_wrap(en_text, wrap_w_en)

        # 5. 组合 ASS 内联标签文本
        ass_text = self._compose_ass(en_text, zh_text, en_size, zh_size, bilingual, layout.en_size)

        return RenderedSubtitle(ass_text=ass_text, en_size=en_size, zh_size=zh_size)

    def build_glossary_text(
        self,
        vocab_items: Dict[str, str],
        en_size: Optional[int] = None,
        default_gloss_size: Optional[int] = None,
    ) -> str:
        """构造 GlossaryCard 的 ASS 文本（词汇释义区域）。

        [Claude_Opus_4.6_Thinking_planning] v1.4.0:
        - 字号修正：gloss_size = min(default_gloss_size, en_size)，
          确保释义区字号始终小于英文字幕字号，避免喧宾夺主。
        - 颜色分层：使用淡色系专用常量（GLOSS_LABEL_COLOR / GLOSS_WORD_COLOR / GLOSS_TRANS_COLOR），
          与主字幕（EN_COLOR / ZH_COLOR / VOCAB_HIGHLIGHT_COLOR）形成明显的视觉层级差。

        Args:
            vocab_items: {单词: 释义} 有序字典
            en_size: 当前段落英文字幕的实际字号（动态缩放后）。
            default_gloss_size: GlossaryCard SSAStyle 的默认字号（font_size*0.42）。
                gloss_size = min(default_gloss_size, en_size)，保证释义区始终更小。

        Returns:
            可直接写入 GlossaryCard SSAEvent.text 的字符串
        """
        if not vocab_items:
            return ""

        # [Claude_Opus_4.6_Thinking_planning] 字号计算：
        # 取 min(样式默认字号, 英文字幕字号)，确保释义区字号永远是最小的。
        # 之前的 bug 是直接 gloss_size = en_size（59pt），覆盖了样式层的 35pt。
        gloss_size: Optional[int] = None
        if default_gloss_size is not None and en_size is not None:
            gloss_size = min(default_gloss_size, en_size)
        elif en_size is not None:
            gloss_size = en_size
        elif default_gloss_size is not None:
            gloss_size = default_gloss_size

        parts = []
        for idx, (word, translation) in enumerate(vocab_items.items()):
            part = ""
            if idx == 0:
                # 插入字号控制标签 + 淡色「词汇」标签
                fs_tag = f"\\fs{gloss_size}" if gloss_size is not None else ""
                part += f"{{\\fn{FONT_ZH}{fs_tag}\\c{GLOSS_LABEL_COLOR}}}词汇  "
            # [Claude_Opus_4.6_Thinking_planning] 释义区使用淡色系：英文词用淡金，中文释义用浅灰
            part += f"{{\\fn{FONT_EN}\\i0\\c{GLOSS_WORD_COLOR}}}{word} {{\\fn{FONT_GLOSS}\\i1\\c{GLOSS_TRANS_COLOR}}}· {translation}{{\\i0}}"
            parts.append(part)

        return "   ".join(parts)

    # ── Private helpers ──────────────────────────────────────────────────────

    def _fit_font_size(
        self,
        en_text: str,
        zh_text: str,
        en_size: int,
        zh_size: int,
    ) -> tuple[int, int]:
        """动态字号缩放：估算折行后高度，不满足则按 scale_step 递减。

        Returns:
            (最终英文字号, 最终中文字号)
        """
        layout = self.layout
        for _ in range(layout.max_iterations):
            w_en = max(20, int(layout.safe_width / (en_size * 0.54)))
            w_zh = max(10, int(layout.safe_width / zh_size))

            wrapped_en = tag_aware_wrap(en_text, w_en) if en_text else ''
            raw_zh = re.sub(r'\{[^}]*\}', '', zh_text)
            wrapped_zh_raw = textwrap.fill(raw_zh, width=w_zh) if raw_zh else ''

            en_lines = wrapped_en.count('\\N') + 1 if wrapped_en else 0
            zh_lines = wrapped_zh_raw.count('\n') + 1 if wrapped_zh_raw else 0

            est_height = (
                en_lines * en_size * layout.line_height_factor
                + layout.spacer_px
                + zh_lines * zh_size * layout.line_height_factor
                + layout.outline * 2
            )

            if est_height <= layout.max_height:
                break

            if en_size <= SUBTITLE_MIN_EN_SIZE and zh_size <= SUBTITLE_MIN_ZH_SIZE:
                break  # 已达最小值，停止缩放

            en_size = max(SUBTITLE_MIN_EN_SIZE, en_size - layout.scale_step)
            zh_size = max(SUBTITLE_MIN_ZH_SIZE, zh_size - layout.scale_step)

        return en_size, zh_size

    def _compose_ass(
        self,
        en_text: str,
        zh_text: str,
        en_size: int,
        zh_size: int,
        bilingual: bool,
        default_font_size: int,
    ) -> str:
        """根据双语/单语模式组合 ASS 内联标签文本。

        Args:
            en_text: 已折行的英文文本（可含 ASS 标签）
            zh_text: 已折行的中文文本
            en_size: 最终英文字号
            zh_size: 最终中文字号
            bilingual: 是否双语模式
            default_font_size: 非动态缩放时回退的字号（仅单语降级时使用）

        Returns:
            完整 ASS text 字符串
        """
        if zh_text and en_text:
            if bilingual:
                # 双语：英文 + 透明占位行（视觉间距）+ 中文
                # fnGeorgia 是双语字幕的必要标识（Checkpoint 缓存校验依赖此标签）
                return (
                    f"{{\\fn{FONT_EN}\\fs{en_size}\\c{EN_COLOR}}}{en_text}"
                    f"\\N{{\\fs24\\alpha&HFF&}} "
                    f"\\N{{\\fn{FONT_ZH}\\fs{zh_size}\\alpha&H00&\\c{ZH_COLOR}}}{zh_text}"
                )
            else:
                # bilingual=False：仅显示中文
                return f"{{\\fn{FONT_ZH}\\fs{default_font_size}\\c{ZH_COLOR}}}{zh_text}"
        elif zh_text:
            return f"{{\\fn{FONT_ZH}\\fs{default_font_size}\\c{ZH_COLOR}}}{zh_text}"
        else:
            # 无中文翻译：仅显示英文
            return f"{{\\fn{FONT_EN}\\fs{en_size}\\c{EN_COLOR}}}{en_text}"
