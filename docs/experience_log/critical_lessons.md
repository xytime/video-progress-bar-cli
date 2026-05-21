---
created_by: Gemini_3.1_Pro_High
created_at: 2026-05-17
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
