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

**2026-10-17 12:14:39北京时间完成原生九步上线；两条候选均解除CIA误拦，并于12:15:43由自然调度自动准入。** 当前修复及长期新准入链路验收通过，不代表两条内容已获发布批准。

采用目标`284732b5b610ae4f9ed77ed939ce53f327499040`，包含片尾长例句并行修复553faa0及其后续文档eed288e。计划`5c1f0b5a0e044510bb4581b65b3c3d8e`，私有目录`~/Library/Application Support/VideoProcessing/deployments/keyword-cia-fix-20261017-c`；baseline/freeze/stop/backup/adopt/start/resume/restore/verify全部完成，verify.ok=true。11:57 Cloud非秘密搜索3/100、通用338/10000，采用时仍在一小时有效期内，宿主实际窗口通过。真实在途导致freeze拒绝后，先status核实，维持暂停新接纳并等待自然结束，再recover；未强杀、删锁、改指纹或编辑旧journal。

12:18独立回读：运行hash`df911b5285c439f953ebe692ef0b7535f7aaf85a097ba157f95fb631e1f6dd2a`，六类当时存活角色真实birth/hash/cwd匹配，完整LONG_TERM通过；26项原dirty哈希和1245条untracked路径全部保留，原生源码清单匹配。正常CSRF/CAS已恢复DISCOVERY_ONLY/version62、admission1/version18、RUNNING70；API20/40、每日2／滚动6／在途2、规则期限不变。

### 自然作业及两条候选

- 12:15:25–27自然SCHEDULED `e44c3e7fed534d8797262673a96086d5` COMPLETE/OK，新增4／重复21／受限17，搜索1、详情1。随后自然REFRESH `7a0e707fea984e048b47f146d6792272`及`b2d75e6402164526bbbb552d4e9bfa5b`均成功，各详情1。三作业67条原始快照中65条数值评分复算一致，另外2条上游统计缺失按原规则保留空分；没有补造0分、手工tick或创建候选。
- `vS2uoE_Rr8Q`：82分／1040秒保持；新规则`1190d2cf041c1a84`正常重评后CHECKABLE，12:15:43自然准入KEYWORD根任务**6135**，与持久账本精确关联。12:18为TRANSCRIBING，尚未制作或发布完成。
- `jD_5JhBOJWg`：85分／1156秒保持；正常重评后CHECKABLE，12:15:43自然准入KEYWORD根任务**6134**，与持久账本精确关联。随后源字幕预检命中原有`blocklist.P0.en.china_sensitive_negative_news`，审计**203**、`REJECT_FAILED_BLACKLIST`，12:15:54任务FAILED且已入黑名单，视频下载前阻断。这是独立内容门禁；不是CIA再次误匹配或频道白名单限制。未重试、未退款，失败释放在途容量。
- 12:18额度为北京日2/2、滚动168小时3/6、在途1/2；保留旧5947及新6134/6135三条真实消费。今日额度满只拦新增准入，搜索／刷新仍按预算和宿主窗口运行。未降低评分、热度、时长或内容门槛。

[生产作业、规则重评、主任务／准入账本、P0审计和来源保存证据](evidence/youtube-keyword-cia-fix/production-acceptance-20261017.json)。生产页面1280×900及390×844的两条候选共4张截图已回看，原因提示可见，无横向溢出或页面异常；浏览器仅GET、未触发搜索／保存／准入操作。手机视口模拟不等同真实手机浏览器验收：[82分手机](evidence/youtube-keyword-cia-fix/production-vS2uoE_Rr8Q-390.png)、[85分手机](evidence/youtube-keyword-cia-fix/production-jD_5JhBOJWg-390.png)。截图摄于12:15，不用截图中的较早PENDING代替12:18数据库状态。

12:20已通过应用原生工具将本期`youtube-v0-5`验收跟进设为PAUSED，生产定时采集与准入配置未变。12:21只读回查6135仍在转录，video及queue-dispatch在途，故本轮新增验收记录先提交并推送隔离分支，不在运行任务脚下合入文档或变更生产checkout；修复源码已实际采用。

### 前置拒绝与并行工作保留

首份准备遇到另一维护已冻结UI，`UI_ORIGINAL_STATE_UNSUPPORTED`，未创建可执行计划。[12:06基线](evidence/youtube-keyword-cia-fix/before-adoption-20261017.json)记录两条旧CIA误拦，及另一会话负责的6133／抖音770对账；该会话已完成自己的原生采用，本会话未修改或重传该视频。

第二份计划`096066683c3347649921d06b285fcf5e`在freeze后发现生产HEAD新增eed288e文档／测试提交，源码、dirty及untracked均未变。未改计划或回退Git；等6056自然结束，完整检查通过后，以原生resume及Schedules.restore撤销尚未停止／采用的冻结，留下`cancel-before-adoption.json`，旧journal原样保留。整合eed288e后再生成上述第三份全新计划并完成采用。不是重放旧计划或跳过漂移检查。
