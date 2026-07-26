# 字幕 API 与降级治理待办

更新时间：2026-07-13

## 当前优先级

- [ ] **P0：建立逐视频 AI 处理可观测性与后台审计页**
  - 每个进入处理链路的视频（成功、失败、登录中断、被质量拦截、已降级）都必须有一条可追溯的处理记录，关联 `youtube_id`、切片、开始/结束时间和最终状态。
  - 每次模型/翻译 provider 尝试记录：provider、模型名、能力标签、调用次数、耗时、可取得的 input/output token、错误码/错误分类、冷却命中、fallback 去向及最终选中结果。
  - 每次字幕质量记录：中文覆盖率、vocabulary 覆盖率、质量告警/阻断项、是否触发 fail-open、是否允许发布。
  - 管理后台新增“AI 处理审计”视图：按视频查看完整时间线；按时间、provider、模型、失败类型、降级状态筛选；展示今日/近 7 日用量、失败率、降级率和冷却中的 provider。
  - 记录必须写入 SQLite 结构化表，而非只靠日志；不得保存 API key、完整敏感 prompt 或未脱敏凭据。
  - 验收：构造 Gemini 429 → DeepSeek 成功、DeepSeek 不可用 → Google 成功、全 provider 失败、质量拦截四类测试任务，后台均可看到完整链路与最终结果。

- [ ] **P0：调查并提升 Gemini API 配额**
  - 当前项目：`ContentWorker`
  - 当前层级：Google AI Studio 免费层级
  - 现场基线（2026-07-13）：Gemini 2.5 Flash `RPM 4/5`、`TPM 6.4K/250K`、`RPD 27/20`；Gemini 3.1 Flash Lite `RPM 6/15`、`TPM 368.55K/250K`、`RPD 24/500`。
  - 下一步：确认是否允许绑定结算信息；绑定后复核 Tier 1、RPM/TPM/RPD 新值，并确认项目级配额而非仅更换 API key。
  - 目标：优先解决 Gemini 的输入 TPM 与 RPD 瓶颈，减少翻译和 vocabulary 对齐被迫降级。

- [ ] **P0：修复空翻译候选误接收**
  - 阿里云非 200、全空返回、中文覆盖率过低时，候选必须判定为不可用。
  - 禁止把等长度的空字符串列表当成成功翻译。
  - 发布前必须验证 ASS 中存在实际中文对白，而不是只检查字体/样式标记。

- [ ] **P0：修复 vocabulary 降级链路**
  - Gemini 不可用时，DeepSeek/阿里云/Google 只负责翻译；vocabulary 对齐单独处理并记录结果。
  - 对齐失败时允许保留合格的双语字幕，但不得伪装成完整 vocabulary 字幕。
  - 若中文翻译本身为空，直接阻止发布，不得由 `ENABLE_TRANSLATION_QUALITY_FAIL_OPEN=true` 放行。

## 保持一致性品质的备用方案

- [ ] 优先使用 DeepSeek 作为完整中文翻译备用，并固定同一套上下文约束、JSON 对齐格式、金额/实体校验。
- [x] 已移除阿里云翻译备用；由 Gemini、DeepSeek、Google 质量链路替代。
- [ ] Google Translate 仅作最后救援，不作为默认质量路径。
- [ ] 为每次字幕任务保存 provider、失败原因、中文覆盖率、vocabulary 对齐状态和最终选择结果。
- [ ] 关闭字幕质量 fail-open 前，先完成至少一轮真实视频回归测试。
