# AI-TR-002 离线交叉顺序实验规格

> 状态：已停止，结论 `REPEAT`；不得在本规格下继续提交请求。
>
> 对应总纲：[AI 内容安全与模型评估纲领](ai_safety_offline_validation_program.md)。本文件不是生产变更授权。

## 修订记录

| 版本 | 日期 | 作者 | 说明 |
| --- | --- | --- | --- |
| 1.0 | 2026-07-28 | Codex | 冻结三领域、交叉顺序的 DeepSeek thinking A/B 设计，尚未执行 API 请求 |
| 1.1 | 2026-07-28 | Codex | 首次基线请求未产生可解析对齐 JSON，按止损规则停止并记录为 `REPEAT` |

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

## 5. 执行记录与决定

负责人已批准最多 18 次请求、USD 0.05 总预算和每次 1,200 token 上限。首次执行发生以下结果：

| 项目 | 事实 |
| --- | --- |
| 已尝试请求 | 1 / 18 |
| 样本 | 财经 `75yVZjvfdTo` |
| 模式 | `production_baseline` |
| 结果 | 未得到可解析的、与 12 段输入对齐的 JSON |
| 后续动作 | 立即停止；未重试，剩余 17 次未提交 |
| 成本/usage | 首版执行器在失败前未持久化 usage，故记为未知，不能补造估算 |
| 原始报告 | `output/research/AI-TR-002/report.json` |

因此本规格的决定为 `REPEAT`。它不能证明 `thinking=disabled` 更好，也不能证明 1,200 token 上限是唯一根因。下一轮必须先形成新的实验 ID 与单一假设，明确如何保留失败 usage、如何验证输出上限和如何重新申请请求/预算，才可再次调用 API。
