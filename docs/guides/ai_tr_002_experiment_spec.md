# AI-TR-002 离线交叉顺序实验规格

> 状态：设计完成，等待负责人批准 API 请求上限和预算。
>
> 对应总纲：[AI 内容安全与模型评估纲领](ai_safety_offline_validation_program.md)。本文件不是生产变更授权。

## 修订记录

| 版本 | 日期 | 作者 | 说明 |
| --- | --- | --- | --- |
| 1.0 | 2026-07-28 | Codex | 冻结三领域、交叉顺序的 DeepSeek thinking A/B 设计，尚未执行 API 请求 |

## 1. 实验合同

| 字段 | 定义 |
| --- | --- |
| 实验 ID | `AI-TR-002` |
| 假设 | 在相同模型、提示词、样本、输出上限下，显式 `thinking=disabled` 不会增加字幕质量问题，并可降低或不恶化 token 成本与延迟。 |
| 基线 | `deepseek-v4-flash` 的当前生产请求形态：不传 `thinking` 字段。 |
| 候选 | 同一请求仅增加 `"thinking": {"type": "disabled"}`。 |
| 生产边界 | 不改 `.env`、`settings.py`、生产 provider、状态机、数据库、队列、浏览器发布器或调度器。 |
| 原始输出 | `output/research/AI-TR-002/`，不进入 Git。 |
| 可复用实现 | 仅在批准后扩展 `scripts/deepseek_thinking_ab_review.py` 与其单测。 |

## 2. 样本和顺序

所有样本均为本地既有双语 ASS 和已处理视频；每条仅选取开头连续 12 段，英文源文本上限 2,400 字符。样本完整原文不写入 Git 或 Telegram。

| 领域 | YouTube ID | 标题缩写 | 执行顺序 |
| --- | --- | --- | --- |
| 财经 | `75yVZjvfdTo` | Wall Street's Biggest Fear Isn't AI | baseline -> disabled |
| 财经 | `LLNCelqS7PM` | Bank Balance Sheets Bend | disabled -> baseline |
| 财经 | `d57IXaxhZzo` | The Bitcoin Decoupling Lie | baseline -> disabled |
| 科技 | `xHr18GEJqck` | Why AI Will Never Replace a Great Teacher | baseline -> disabled |
| 科技 | `w24zeYdwnXU` | How to Stand Out in the Ocean of AI Slop | disabled -> baseline |
| 科技 | `aqyZ87euzz0` | This AI Agent Builds Viral Documentary Videos | baseline -> disabled |
| 演讲/教育 | `QBgpMFIlkx8` | What Shapes Our Everyday Decisions | disabled -> baseline |
| 演讲/教育 | `cbiyPOn-__M` | How You Can Learn in Information Overload | baseline -> disabled |
| 演讲/教育 | `Bz_iIA3kaLI` | Harvard Commencement 2026 | disabled -> baseline |

顺序按领域平衡：9 个样本中 baseline-first 5 个、disabled-first 4 个。结论只看按模式聚合后的分层数据，不将第二个请求的缓存收益解释为 thinking 本身的收益。

## 3. 硬上限和成本模型

| 项目 | 上限 |
| --- | --- |
| 视频样本 | 9 条 |
| 片段/视频 | 12 段 |
| 外发英文源文本/请求 | 2,400 字符 |
| 共享上下文/请求 | 1,800 字符 |
| 输出/请求 | 1,200 token |
| API 请求 | 18 次，失败不自动扩大或补偿重试 |
| 超时 | 90 秒/请求 |
| 累计预算 | USD 0.05，达到上限立即停止 |

费用使用供应商响应中的 `prompt_tokens`、`completion_tokens`、`prompt_cache_hit_tokens` 和 `prompt_cache_miss_tokens`，配合执行当日的官方价格快照计算。请求数、字符数、输出 token 和累计估算费用任一超过上限，都必须停止，输出不完整报告并标记 `REPEAT`。

## 4. 指标与判定

每种模式按全部样本及三个领域分别报告：

- 结构化 JSON 解析和字幕段落 ID 对齐率；必须为 100%。
- 新增质量守门 blocking issue 数；必须为 0。
- warning issue、金额/实体/术语/方向错误和人工盲评错误片段。
- P50/P95 延迟、输入/输出/缓存 token、每视频费用和总费用。
- 顺序和缓存状态，用于识别缓存混杂而非将其归因于 thinking。

本实验只允许三种结论：

| 结论 | 条件 | 后续动作 |
| --- | --- | --- |
| `REJECT` | disabled 出现新的严重翻译错误、对齐失败或明显质量退化 | 保持生产现状，记录失败样本 |
| `REPEAT` | 样本不足、缓存混杂无法解释、usage 缺失或人工评分未完成 | 修订单一假设后重做离线实验 |
| `EXPAND_ELIGIBLE` | 全部硬门槛通过，人工盲评未见严重退化 | 进入 `AI-TR-003` 扩大样本；仍不改生产设置 |

`EXPAND_ELIGIBLE` 不代表可关闭生产 thinking，也不代表 AI-SF 可以接入发布链路。

## 5. 执行前待批准事项

1. 将第三方 DeepSeek 请求从 `AI-TR-001` 的 2 次扩展到本实验的最多 18 次。
2. 允许外发上表 9 条既有公开字幕样本的受限片段与翻译上下文。
3. 批准累计预算硬上限 USD 0.05，以及每次最大输出 1,200 token。

获得批准前，只允许 dry-run、样本完整性检查和单测；不得发送 API 请求，也不得修改生产行为。
