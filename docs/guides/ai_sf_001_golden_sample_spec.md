# AI-SF-001 安全黄金样本合同

> 状态：schema 就绪，待人工标注。本项不调用模型、不外发内容、不改变任何视频或发布状态。
>
> 对应总纲：[AI 内容安全与模型评估纲领](ai_safety_offline_validation_program.md)。现有 P0/P1/P2 和发布前 fail-closed 闸门不在本项范围内。

## 修订记录

| 版本 | 日期 | 作者 | 说明 |
| --- | --- | --- | --- |
| 1.0 | 2026-07-29 | Codex | 定义 AI-SF-001 的本地黄金样本来源、标签、隐私边界和冻结条件 |
| 1.1 | 2026-07-29 | Codex | 记录 schema/冻结验证已完成，以及只读台账当前仅有两条 P0 候选 |

## 1. 实验合同

| 字段 | 定义 |
| --- | --- |
| 实验 ID | `AI-SF-001` |
| 唯一目标 | 建立可复核的人工安全标签合同，使后续规则回归或 AI 影子报告能够追溯到来源、规则快照和证据定位。 |
| 输入 | 既有 `censorship_incidents`、本地视频/字幕产物及人工复核记录的最小引用；不复制完整标题、文案、字幕或模型输出到 Git。 |
| 外部调用/预算 | 0 次 API、USD 0。 |
| 生产边界 | 不改 `censor_engine`、`CensorshipService`、规则包、数据库、队列、浏览器上传器、调度器或任何 feature flag。 |
| 原始数据 | 仅本机 `output/research/AI-SF-001/`；Git 只提交 schema、空 manifest、测试和本规格。 |
| 验收 | schema 可验证；四类来源均有最小配额；每条有可复核来源、规则快照、人工标签与复核日期；`UNRESOLVED` 不进入指标。 |

## 2. 来源桶与最小配额

当前本地 `censorship_incidents` 只有 2 条 P0 事后事件，均发生在 2026-07-25；它们只能作为 `RULE_HIT` 候选，不能单独构成黄金集或统计结论。

| 来源桶 | 说明 | 最小条数 | 标签预期 |
| --- | --- | --- | --- |
| `RULE_HIT` | 既有 P0/P1/P2/CP 命中或历史平台异常关联素材 | 1 | 通常 `BLOCK` 或 `REVIEW`，须人工确认 |
| `PUBLISHED_ALLOW` | 已发布且人工确认低风险的财经、科技、教育素材 | 每领域 1 | `ALLOW` |
| `RULE_HIT_HUMAN_ALLOW` | 规则命中后人工确认可放行的误杀候选 | 1 | `ALLOW` 或 `UNRESOLVED` |
| `CONTEXTUAL_VARIANT` | 跨句、翻译变体、同义表达或隐喻样本 | 1 | 由人工标为 `BLOCK`、`REVIEW`、`ALLOW` 或 `UNRESOLVED` |

最小总量是 6 条，其中 `PUBLISHED_ALLOW` 必须覆盖财经、科技、教育三个领域。未达到此门槛时只能标记为 `DRAFT` 或 `LABELING`，不得计算精确率/召回率、不得训练或接入模型。

## 3. 标签与隐私规则

人工标签只能是 `BLOCK`、`REVIEW`、`ALLOW`、`UNRESOLVED`：

- `BLOCK`：内容不应进入发布候选；不替代现有 P0/P1/P2 的动作。
- `REVIEW`：证据不足或语境有争议，后续只能进入人工审核。
- `ALLOW`：人工确认低风险；不表示未来自动发布，也不覆盖任何规则命中。
- `UNRESOLVED`：保留分歧或缺证据样本；不得进入模型指标、提示词优化或自动放行依据。

所有 `BLOCK` 与 `REVIEW` 必须提供至少一个仅含字段名、字符偏移和片段 hash 的证据定位。完整证据文本只能留在本地受限样本文件。Git、Telegram、测试断言和模型请求不得包含它。

## 4. 文件与冻结规则

| 文件 | 用途 |
| --- | --- |
| `docs/schemas/ai_safety_golden_manifest.schema.json` | JSON Schema 单一真相源。 |
| `docs/schemas/ai_safety_golden_manifest.example.json` | 无敏感正文的 `DRAFT` 模板。 |
| `output/research/AI-SF-001/manifest.json` | 本地实际 manifest；必须通过 schema，且不得进入 Git。 |

`FROZEN` manifest 必须满足四类来源与六条样本的最小配额。冻结后只允许新增样本或创建新 manifest 版本，不得静默修改已有样本的人工标签；重新标注必须新建 revision 并写明原因。

## 5. 下一步与停止条件

本项完成前，唯一允许动作是人工用本地 manifest 补齐来源与标签，或补充 schema 的本地验证测试。任何模型调用、AI 判断、后台展示、自动挂起、规则改写或发布路径改动都超出 AI-SF-001。

当 manifest 达到冻结条件后，才可启动 `AI-SF-002`：对现有规则运行纯离线回归，逐条比较规则输出与人工标签。

## 6. 当前证据与交接

只读汇总确认本地 `censorship_incidents` 当前共有 2 条记录，均为 `postmortem / P0 / POSTMORTEM_INCIDENT`，时间均为 `2026-07-25`。未读取标题、字幕、摘要、命中词或任何敏感正文。

已完成：

- `docs/schemas/ai_safety_golden_manifest.schema.json`：禁止 Git 保存原文，约束来源、规则快照、标签、证据偏移和 hash。
- `docs/schemas/ai_safety_golden_manifest.example.json`：不含任何样本正文的 `DRAFT` 模板。
- `scripts/validate_ai_sf_manifest.py`：本地验证 schema、重复 ID、证据偏移和 `FROZEN` 的四桶/三领域配额。

未完成且不能由规则或 AI 代填：人工确认的 `PUBLISHED_ALLOW`、`RULE_HIT_HUMAN_ALLOW`、`CONTEXTUAL_VARIANT` 样本，以及每条的人工标签。故当前不生成性能指标、不启动 AI-SF-002，也不作任何“安全模型有效”的结论。
