# 2026-09-30 封面降级故障

作者：Codex。时间采用北京时间。

## 已确认的根因

今天凌晨四个任务各执行三次 AGY 调用，随后使用 `deterministic_fallback` 完成封面并提交视频号。十二次调用的 AGY 原生日志均明确返回：

`FAILED_PRECONDITION (code 400): User location is not supported for the API use.`

失败发生在模型执行阶段，尚未生成候选底图。项目原来将完整 stdout/stderr 中任意 `quota` 或 `429` 字样当成额度故障，其他错误一律归为 `provider_error`；worker 捕获异常后也没有输出 stderr，导致协调器日志为空。原来的“额度不足”记录不能作为实际额度耗尽的证据。

| 任务 | 提交时间（约） | 实际封面来源 |
| --- | --- | --- |
| `f30j685R7s4-22a97f8ded51` | 05:05 | deterministic_fallback |
| `9oz15WUa7zM-758c02ecf20f` | 05:14 | deterministic_fallback |
| `scN2-afWapQ-8f06e312280a` | 05:20 | deterministic_fallback |
| `vm2pRzlRK9g-515c91e44a24` | 05:45 | deterministic_fallback |

原始证据位于各任务的 `ai-cover-finish/<task_id>/`，包含尝试记录、来源回执、最终成图。与任务对应的 AGY 日志路径、时间和稳定错误摘要汇总于 `output/cover-repair-20260930/incident_summary.json`。原始历史记录保持原样。

## 本次修复

- 从 AGY JSON 的实际 `error` 字段提取稳定分类，避免使用提示词、响应正文或 usage 元数据判断额度。
- 明确区分地区拒绝、认证、额度、网络、超时，保留可解析的 HTTP 错误码；不把完整提示词、环境或原始提供商输出写入错误记录。
- worker 向协调器输出失败阶段、尝试次数和稳定 CLI 错误，修复空白日志。
- 移除强制传入的 Gemini `--effort high` 参数，使用模型 ID 自带档位；实际调用发现 Sonnet 不接受该参数。生产模型配置未改变。

## 当前限制

- AGY 1.2.13 的模型列表包含已配置的 `gemini-3.7-flash-high`。现场另用 `gemini-3.8-flash-high` 执行仅回复 OK 的请求，也返回同一地区拒绝；改模型不足以修复。
- 08:19 左右从本机无 Cookie 请求 Google 条款页 `https://policies.google.com/terms?hl=en`，可见文本为 `Country version: Russia`；YouTube 首页返回的客户端 `gl` 为 `RU`，Cloudflare 同时显示 `loc=US`。当前 Clash Mi 规则将 Google 与 googleapis.com 指向同一专用代理组。Google 侧回显俄罗斯，但 AGY 错误本身没有国家代码，不冒充取得其内部地区字段。
- Clash Mi 保持 Connected。现有独立代理端口 7899 的诊断调用超时，未采用。全机代理及其规则没有修改。
- AGY 的 Claude Sonnet 简单对话成功；使用该模型实际调用生图工具仍因地区限制没有产生图片。因此换推理模型不能恢复封面生成。隔离回执保存在 `output/cover-repair-20260930/finish/recovery-f30j685R7s4-b111dca1f298/`，未接入生产队列。
- 此补丁修复的是诊断缺陷，尚不能证明 AGY 生图服务已恢复。未执行测试套件。
- 9 月 27 日已确认规格允许三次失败后自动兜底。将其改为挂起、禁止退化封面发布，需要用户确认该策略变更；当前尚未实施。
- 四条已有提交处于 `SUBMITTED_BOUND`，不能据此宣称公开可见。未修改平台封面或重发历史视频。
