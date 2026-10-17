# YouTube 关键词 CIA 误匹配修复与验收

编写：Codex，2026-10-17。用户已确认仅修复 CIA 误匹配及候选拦截原因提示，并完成隔离、维护采用及两条候选真实回读。

## 根因与边界

关键词候选不要求频道进入白名单。现有 `channel_policy.zh` 中的拉丁缩写 CIA 被当作中文连续子串查找，误命中西语 `diferencias` 和葡语 `oficial`，因此出现笼统的“频道策略限制”；两条频道均未列黑名单。不是频道白名单拦截。

- `vS2uoE_Rr8Q`：82分，1040秒，Dr. Luis Antonio Pacora Camargo。
- `jD_5JhBOJWg`：85分，1156秒，Rastro Químico。

本期仅为中文频道策略中的拉丁缩写加单词边界，仍识别真实 CIA、全角、大小写和拆空格变体；中文防拆字及共现规则不变。规则指纹包含匹配器版本，使缓存候选在正常读取／调度时重评，无须重新搜索。提示显示命中词、标题／原始描述、原文片段和规则版本；使用 textContent，保持原页面结构。

评分至少75、热度、180–1800秒、P0/P1/P2、频道黑名单、源字幕预检及发布边界均保持不变。长期日2／滚动168小时6／在途根任务2、规则期限及API20/40不改。元数据限制解除不等同源字幕审核或平台发布通过。

## 隔离证据

以生产1510份维护文件及全部并行dirty/untracked构成整合副本，再覆盖本期实现及测试。精确原始标题和完整描述保存在 `tests/fixtures/topic_cia_regression.json`，非秘密资料。

- `video-pytest-5v_aka_p`：405 passed／10 warnings，runner exit0、边界探针通过、沙箱回收。覆盖缩写边界、真实命中保留、原文提示、缓存重评、自动准入与持久账本、关键词长期策略、维护／部署，以及现有浏览器流程。
- 专项视觉留证 `video-pytest-0h8utr2t`：三主题3 passed，runner exit0，6张桌面1280×900／手机390×844截图已回看、无横向溢出、键盘可用、原文注入作为文字展示；沙箱已回收。当前未提供浏览器插件，沿用项目隔离 Playwright/Chromium 流程。
- 两轮相同源码清单 SHA256 `b9a168f6efa17e827a23589f0f8dc60c7409ce17b9ad83eece0711dbdae65f23`。结果不等同生产采用或真实新准入。

[隔离收据](evidence/youtube-keyword-cia-fix/isolated-tests.json)；[浅色手机](evidence/youtube-keyword-cia-fix/policy-reason-light-390.png)、[深色桌面](evidence/youtube-keyword-cia-fix/policy-reason-dark-1280.png)、[高对比手机](evidence/youtube-keyword-cia-fix/policy-reason-contrast-390.png)。

- 生产同时开始原生片尾长例句修复维护（553faa0）。本分支已整合该提交；最终联合快照另补141项，全部通过、沙箱回收，清单 `614cdab453658026301bf78711639d1213962c198a92b619ba53068d7d3b2451`。此前一次快照复制命令因工作目录引用失败，没有纳入这两份新源码；其旧清单测试不作为联合验收证据。最终联合141项以该清单为准。

## 维护采用及实际回读

待执行。第一份CIA计划在准备时发现UI已被另一原生维护冻结，返回 `UI_ORIGINAL_STATE_UNSUPPORTED`，未创建可执行计划、未修改源码；没有恢复或覆盖另一维护。11:57刷新Cloud非秘密配额搜索3/100、通用338/10000。执行前刷新非秘密Cloud配额和带时区宿主窗口，核实完整来源、锁、调度及保护字段。正常控制面关闭搜索及准入后，以全新原生 `--preserve-keyword-profile` 计划暂停新接纳、自然排空、正常停止、一致性备份、采用、维护启动、恢复调度、最终回读。原生拒绝先status再核实recover，不绕门禁、强杀、删锁或编辑旧journal。所有并行改动必须逐项核对保留。

采用完成后恢复已授权长期能力，正常读取两条候选，并检查原始分数／时长、精确规则原因、KEYWORD主任务与准入账本。自然调度完成后再报告真实状态；不手工tick、制造候选或降低内容门槛。

### 12:06 生产采用前基线

[只读基线](evidence/youtube-keyword-cia-fix/before-adoption-20261017.json)确认两条候选仍分别82分／1040秒与85分／1156秒，旧规则指纹2a618ce6dfa4986c，均RESTRICTED且无主任务。当前由另一维护暂停新接纳（MAINTENANCE65、OFF57、admission0/version15）；轻量active为空，但完整检查仍发现一条发布中总账6133，而抖音账本770已UNDER_REVIEW。该项正在由负责会话按受控对账处理，本会话未修改它、未重传、未复用其部署计划。其维护完成后才执行本次全新计划。
