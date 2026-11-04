# 字幕预算复核与认证粘性旁路

维护：Codex，2026-11-04。此文档不授权历史重跑、改供应商顺序、增加预算或操作账号。

## 7212：只读复核，保留历史

视频 `sbwDGCm-LOw`（7212）的 recovery 23 仍为 `NEEDS_REPAIR`，
原码 `all_providers_failed:rate_limit`，没有下次自动尝试时间。
回执 `40b9e94950724e5fb4a16fb3dabf0281.json` 的 SHA256 为
`6c0262da77d9a8261cc973995e132da50eb9d0f85c34fc6054dc63d8eecdb405`，
与 DAL 中的 `last_receipt_sha` 一致。

run 2069（北京时间 2026-11-03 08:22:32–08:30:26）的 attempts 3524–3529：

| 供应商 | 原始分类 | 耗时 |
| --- | --- | --- |
| AGY | auth_or_permission | 1.659 秒 |
| Codex | budget_exhausted | 300.047 秒 |
| Grok | timeout | 150.575 秒 |
| DeepSeek | network | 10.933 秒 |
| Gemini | budget_exhausted | 1.904 秒 |
| Google | rate_limit | 8.722 秒 |

可以确认预算耗尽参与了失败，且 Google 确实限流；不能断言预算是唯一根因，
也不能把 600 秒总预算等同于各供应商都能使用 600 秒。
Google 当时的错误记录明确为第 1/614 段。
本机只读配置核对为 50 段/批、120 秒/请求、总预算 600 秒、质量预留 120 秒。
当前保守预检需要 `ceil(614/50)*120 = 1560` 秒，可用 480 秒，应转人工选择分片方案。
1560 秒是容量规划上界，并非已经实测的翻译耗时。
历史 run 没有不可变配置快照，不能用当前配置反推当时全部参数；
预算耗尽结论由当时的 attempts 和回执直接支持。

`5cf7a04` 已修复新失败的混合分类与预算预检。本次不回填历史，
避免破坏原回执绑定和审计事实；交付目录另存只读复核结论。
只改旧失败码不能使这部长片具备可重试条件。

人工单次重试复用 [字幕人工复核后放行一次](subtitle-manual-release.md)：

1. 先确认可行的处理方案和预算预检，不能仅因为冷却到期就放行。
2. 只读 `GET /api/videos/sbwDGCm-LOw/subtitle-review?slice_index=0`，
   重新取得 `review_token`、`expected_receipt_sha`、`releasable`。
3. 取得针对此视频的人工明确确认后，才向对应 `subtitle-release` POST
   上述当前摘要、实际操作者和复核理由。禁止使用过期 token 或自动重发。
4. 24 小时内只允许一次原子领取；全部字幕预检、内容审核和投稿保护仍生效。
   原片 614 段及配置未变化时仍会被预算预检阻断，不能承诺放行后成功。

本次不调用 POST、不更改 recovery、失败事件或历史视频状态。

## 认证错误：计时到期不等于恢复

`DynamicTranslationModelPool.order()` 原本就排除冷却中的 AGY。
新行为将 `auth_or_permission` 持久标为 `auth_blocked`，普通冷却到期和
`ignore_cooldown` 都不能解除。后续网络/超时错误也不能覆盖认证阻断。
旧池中未解除的 `auth_incident`，或认证错误且非零冷却时间，直接按旁路处理，
只读排序不会重写旧池；无需等待一次新的认证失败。

其他临时错误仍按原计时规则恢复；Gemini 外层限流的模型级冷却例外保留。
旧版本成功时留下的 `last_error_class`，在 cooldown 已清零且无 incident 时
不应误判为尚未恢复。

恢复要求：操作者先完成登录/权限修复，再经授权使用独立样例验证实际供应商返回
和质量验收。已有 `record_quality()` 成功路径才解除对应 provider 的认证标记。
禁止以时间经过、仅打开登录页、手改池文件或伪造质量成功来解锁。
此修复不新增自动探测，不改 `.env`、ORDER、密钥或账号状态。
登录确认和验证样例须单独授权；不以 7212 等历史视频当探针。
