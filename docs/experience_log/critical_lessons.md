---
created_by: Gemini_3.1_Pro_High
created_at: 2026-05-17
updated_by: Claude_Sonnet_4.6_Thinking_planning
updated_at: 2026-06-08T10:05:00+08:00
purpose: 视频处理项目的关键教训防重犯清单
---

# 🧠 Critical Lessons — 视频字幕架构核心教训

## L1: ASS 字幕格式与 Python 换行符冲突 (P1)
**症状**: 英文过长自动折行时，如果不转换换行符，可能导致生成的 `.ass` 文件损坏或不生效。
**规约**: 必须在封装 `pysubs2.SSAEvent` 前，使用 `text.replace('\n', '\\N')`。`\N` 是 ASS 标准中唯一识别的强制换行符。

## L2: 双语字幕重叠与动态 Margin 计算 (P1)
**症状**: 中英双语同时渲染时，下方英文折行会导致其覆盖在上方中文字幕上。
**规约**: 中文层的底部边距不可硬编码，必须基于英文字符的逻辑换行数计算。例如：`margin_zh = 10 + (en_lines * 18) + 5`。

## L3: Whisper 识别输入格式强制约束 (P2)
**症状**: 识别卡死、效率低下、或显存爆炸。
**规约**: 调用 `whisper` 前的 `_extract_audio` 必须使用 FFmpeg 将音频转换为 Whisper 极简友好格式：`16kHz` 采样率且为 `单声道 (mono)`。

## L4: pysubs2.Color 参数陷阱 (P2)
**症状**: 配置的颜色无效，抛出类型错误。
**规约**: 禁用 HEX 或 RGBA 直传，必须使用 `(R, G, B, Alpha)` 整数。同时 ASS 的 Alpha 通道数值（255 代表完全透明）与普通图形库相反。

## L5: ASS 中文高亮必须在折行之后施加 (P1)
**症状**: `textwrap.fill` 对已含 `{\u1\c&HC7D36F&}` 等 ASS 标签的中文文本做折行时，会把 `\N` 插入标签内部（如 `{\u1\c&HC7D36\NF&}`），导致 libass 解析失败，字幕渲染出乱码或原始标签字符。
**规约**: **先折行，再高亮**。英文高亮（`apply_word_highlights`）可以在折行前执行，因为英文使用了 `tag_aware_wrap` 跳过标签字符长度计算。但中文高亮（`apply_chinese_highlights`）必须在 `textwrap.fill(...).replace('\n', '\\N')` 完成之后再调用，此时 `\N` 已经固化，不会再被 `textwrap` 修改。

## L6: GlossaryCard 释义区字号必须动态钳制，不可仅靠 SSAStyle (P2)
**症状**: 当主字幕因多行折叠触发动态缩放（`_fit_font_size`）后，英文字号可能降至 28-45pt。但 `GlossaryCard` SSAStyle 的 `fontsize` 是全局固定值（42% × 84 ≈ 35pt），不感知动态缩放结果。未来若主字号调低至 28pt 时，释义区固定 35pt 反而会比主字幕更大，违反「Principle 1：释义字号不超过英文字幕字号」。
**规约**: `build_glossary_text` 必须接收当前段落渲染后的实际英文字号 `en_size`，并在 ASS text 层插入 `{\fs{min(gloss_size, en_size)}}` 内联覆盖标签，以硬性保证释义字号 ≤ 当前段落英文字号，而非依赖静态样式。
