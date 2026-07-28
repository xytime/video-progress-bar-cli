# AI-TR-003 结构化输出契约诊断规格

> 状态：设计完成，待负责人批准；本文件本身不授权 API 调用或生产变更。
>
> 对应总纲：[AI 内容安全与模型评估纲领](ai_safety_offline_validation_program.md)。本项只解决 `AI-TR-002` 首次请求无法解析的问题，不检验或改变 thinking。

## 修订记录

| 版本 | 日期 | 作者 | 说明 |
| --- | --- | --- | --- |
| 1.0 | 2026-07-29 | Codex | 从 AI-TR-002 的不可解析结果派生，冻结 JSON 契约和失败元数据的最小诊断设计 |
| 1.1 | 2026-07-29 | Codex | 记录本地 dry-run、请求哈希和完整单测结果；未调用 API |

## 1. 为什么先做这一步

`AI-TR-002` 的首个生产基线请求在 1,200 token 上限下未得到可解析、与 12 段输入对齐的 JSON。首版执行器没有持久化 `finish_reason`、响应内容长度或完整 usage，因此无法区分以下原因：

1. 输出并非 JSON，或 JSON 外混入了额外文本。
2. 输出为 JSON 但字幕段落 ID 或数量不对齐。
3. 输出因 `max_tokens` 被截断。
4. 供应商响应或本地解析器出现其他异常。

在这个前提下，继续比较 thinking 会把“结构化输出不可靠”和“thinking 的质量/成本差异”混为一个变量。DeepSeek 的 Chat Completions 文档提供 `response_format={"type":"json_object"}` 以要求合法 JSON，同时要求提示词明确要求 JSON；该项只验证这个输出契约是否能让失败原因可复核。[DeepSeek Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion)

## 2. 实验合同

| 字段 | 定义 |
| --- | --- |
| 实验 ID | `AI-TR-003` |
| 唯一假设 | 在固定的本轮样本、生产基线提示词和 1,200 token 上限下，仅增加 `response_format={"type":"json_object"}` 能提高可解析且 ID 对齐的响应比例，或至少让失败能够由非敏感元数据归因。 |
| 基线 | 当前生产请求形态：不传 `thinking`、不传 `response_format`。 |
| 候选 | 基线请求仅增加 `response_format={"type":"json_object"}`。两组均不传 `thinking`。 |
| 非变量 | 模型、系统/用户提示词、温度、样本片段、上下文、超时、输出上限、解析器和质量守门。 |
| 生产边界 | 不改 `.env`、`settings.py`、生产 provider、状态机、数据库、队列、浏览器发布器或调度器。 |
| 原始输出 | `output/research/AI-TR-003/`，不进入 Git。 |
| 执行授权 | 必须单独批准本节的 4 次请求和 USD 0.01 预算；未批准时只允许 dry-run、单测和文档审阅。 |

## 3. 最小样本与上限

为避免再次把广泛性和输出契约混在一起，本项只用两个既有、已处理视频的开头连续 6 段：一个财经样本 `75yVZjvfdTo`，一个科技样本 `xHr18GEJqck`。执行时记录本地 ASS 和元数据文件的 SHA-256；不将原文、翻译正文、API key、模型长推理或原始模型响应写入 Git 或 Telegram。

| 项目 | 上限 |
| --- | --- |
| 视频样本 | 2 条，财经与科技各 1 条 |
| 片段/视频 | 6 段 |
| 外发英文源文本/请求 | 1,200 字符 |
| 共享上下文/请求 | 800 字符 |
| 输出/请求 | 1,200 token |
| 请求体/请求 | 6,000 bytes |
| API 请求 | 4 次，失败不补偿重试 |
| 超时 | 90 秒/请求 |
| 累计预算 | USD 0.01 |

请求顺序按样本交叉：财经为 `baseline -> json_object`，科技为 `json_object -> baseline`。顺序不会用于推断成本优势，只用于避免把第二次请求的偶然状态误读为输出契约效果。

## 4. 最小实现与审计记录

批准执行前，只允许在离线实验脚本与单测中加入以下能力，不能修改生产翻译器：

1. 生成基线和 `json_object` 两种 payload，并断言它们只差 `response_format`。
2. 对每次响应写入：HTTP 状态、`finish_reason`、模型名、延迟、usage、估算成本、消息内容字节数、JSON 解析是否成功、ID 对齐是否成功和失败分类。
3. 失败分类仅为 `HTTP_ERROR`、`EMPTY_CONTENT`、`INVALID_JSON`、`ID_MISMATCH`、`TOKEN_LIMIT`、`UNKNOWN`；`finish_reason=length` 必须标为 `TOKEN_LIMIT`，不得伪装成模型质量问题。
4. 报告不保存响应正文。仅保存其 SHA-256、字节数和上述元数据，以保持可审计而不保留完整外发内容或推理文本。

Dry-run 必须证明请求数、字节上限、token 上限和最坏情况预算均未超过合同，且不访问网络、不写 PipelineDB、不创建发布任务。

## 5. 指标和允许结论

预先登记的指标为：

- 每组可解析 JSON 率、字幕 ID 对齐率和失败分类。
- 每次调用的 `finish_reason`、延迟、输入/输出/缓存 token 与费用。
- 现有质量守门的 blocking issue 数；本项不做人工翻译质量排名。

本项只允许下列结论：

| 结论 | 条件 | 后续动作 |
| --- | --- | --- |
| `CONTRACT_OBSERVABLE` | 四次调用均保留完整元数据，且候选未新增解析/对齐失败 | 记录结构化输出证据；是否恢复 thinking 比较留给 AI-TR-004 另行批准 |
| `CONTRACT_INSUFFICIENT` | 候选仍出现解析/对齐失败，或 `TOKEN_LIMIT` 显示上限不足 | 保持生产现状；下一项只针对被确认的单一原因设计 |
| `REPEAT` | usage、`finish_reason`、顺序或输入 hash 缺失，或触及任一上限 | 不作比较结论；补齐审计实现后重新申请新的实验 ID |

无论哪一种结论，`AI-TR-003` 都不构成关闭 thinking、修改生产 `response_format`、扩大样本或启动 AI-SF 的授权。

## 6. 执行前批准文本

只有负责人明确批准以下内容后，才可执行：

> 批准 `AI-TR-003`：最多 4 次 DeepSeek API 请求，两个既有字幕样本，每次最多 1,200 输出 token、6,000 请求 bytes、90 秒，累计预算不超过 USD 0.01；仅写入 `output/research/AI-TR-003/`，不改变生产配置、队列或发布流程。

未获得上述批准时，当前决定是 `NO_EXECUTION`。

## 7. 本地就绪记录

`2026-07-29` 已使用 `scripts/run_ai_tr_003.py` 完成 dry-run，结果位于 `output/research/AI-TR-003/dry_run.json`。该文件仅在本机研究目录中保存，不进入 Git。

| 项目 | 结果 |
| --- | --- |
| API 请求 | 0 / 4；未传入 `--execute` |
| 决定 | `DRY_RUN_ONLY` |
| 最坏成本预留 | USD 0.004704 / USD 0.01 |
| 财经样本请求体 | baseline 2,410 bytes；`json_object` 2,454 bytes |
| 科技样本请求体 | `json_object` 1,980 bytes；baseline 1,936 bytes |
| 契约验证 | 每对 payload 除 `response_format` 外完全相同；每条请求均低于 6,000 bytes |
| 自动验证 | `PYTHONPATH=src .venv/bin/python -m pytest tests/unit -q`：671 passed，8 warnings，30 subtests passed |

当前唯一下一项是取得第 6 节的明确执行批准。批准前不得调用 API、不得改变 thinking 或生产翻译请求。
