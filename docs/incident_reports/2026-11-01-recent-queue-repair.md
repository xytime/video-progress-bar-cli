# 最近48小时队列异常逐项修复

日期：2026-11-01；整理：Codex（具体模型版本未知）。

用户要求恢复已批准的少量字幕问题告警继续规则，并逐项处理近48小时异常，优先最近24小时。目标是未解决技术异常归零；历史失败事件保留，不删记录、不用重置状态制造清零。

## 基线

采样：2026-10-31T22:43:10.940231+00:00，按失败事件时间统计，48小时31条、24小时20条。最近24小时包括16条技术/识别失败、2条内容策略、2条投递结果待核实。入库日期不作为失败窗口。

证据：`/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output/investigations/2026-11-01-queue-repair-224305`。WAL一致备份SHA-256 `4a286c9c931437317117aea6caf24a5b4fcbf27fa53be7b4dc369e2ffb035f85`。

## 已实施修复

- 恢复原阈值：真实局部修复后，最多3段，段数和字幕并集时长占比均不超过5%，带告警继续；缺失、空段、结构错误及超范围继续阻断。
- 词注失配只清理附注，不反复重译正确正文；事实缺陷保留全片段号、原严重度与真实修复证据。独立合格行复用；金额遗漏的相邻行不被当成独立正确行。
- `$433.3 million shares` 按显式股数核验；旧缓存误译为股票价值时拒绝。单价、购买股票所花金额继续校验。
- 稳定累计额度与本轮翻译窗口分开。旧恢复账本不扩额、不清次数；累计耗尽和普通请求超时分别归因。
- 原字幕初查及补查均返回ABSENT时，继续检查全部首中尾窗口。全部窗口均有实拍负向证据才进入生成；未知、缺帧及正负混杂继续复核。
- 尾段ASR超出实际片尾不超过1秒时，抽样窗口裁到真实帧，原ASR文本和时间轴不改写；更大异常继续复核。#7146约0.32秒、#7135约0.84秒。
- 阶段回调和心跳的文件写入共用同一锁，消除同名临时文件竞争与旧快照覆盖新阶段。#7068/#7071确有该竞争，但其进程退出根因缺少退出码证据，不能据此宣布已经根治。

## 逐项清单

|任务|原错误|本轮处理/剩余证据|
|---|---|---|
|#7000 `M1xyX3ZQJ6k`|`NATIVE_CAPTION_VISUAL_BUDGET`|已采用的有界抽检路径替代旧全片视觉流程；须用当前源片实测，历史事件尚未解除|
|#7026 `NSPhe3R_kQs`|`CHANNEL_POLICY_REJECT`|内容策略审核，不能作为程序故障自动绕过|
|#7042 `F8Y7IigdTHA`|`NATIVE_CAPTION_VISUAL_BUDGET`|已采用的有界抽检路径替代旧全片视觉流程；须用当前源片实测，历史事件尚未解除|
|#7031 `CatuGloDkTQ`|`NATIVE_CAPTION_VISUAL_BUDGET`|已采用的有界抽检路径替代旧全片视觉流程；须用当前源片实测，历史事件尚未解除|
|#7045 `-D4TV5q5yOM`|`BURNED_CAPTION_REPAIR_UNCERTAIN`|原画面文字角色/定位不明确；保留像素与证据，不能把清零当作擦除授权|
|#7046 `f38UjmZEVv0`|`CHANNEL_POLICY_REJECT`|内容策略审核，不能作为程序故障自动绕过|
|#7054 `6ZpaPFXIgE4`|`CONTENT_CENSOR_BLOCK`|内容策略审核，不能作为程序故障自动绕过|
|#7030 `5e-k8bBMFvY`|`BURNED_CAPTION_REPAIR_UNCERTAIN`|原画面文字角色/定位不明确；保留像素与证据，不能把清零当作擦除授权|
|#7007 `SqwiCJ8r8_Q`|`NATIVE_CAPTION_VISUAL_BUDGET`|已采用的有界抽检路径替代旧全片视觉流程；须用当前源片实测，历史事件尚未解除|
|#7012 `YDeRVjCSCQU`|`NATIVE_CAPTION_VISUAL_BUDGET`|已采用的有界抽检路径替代旧全片视觉流程；须用当前源片实测，历史事件尚未解除|
|#7065 `C0ysAy2LXjY`|`NATIVE_CAPTION_VISUAL_BUDGET`|已采用的有界抽检路径替代旧全片视觉流程；须用当前源片实测，历史事件尚未解除|
|#7055 `1Vjzvjy3xig`|`NATIVE_CAPTION_INCOMPLETE`|旧完整识别超时；当前抽检路径需实测，不直接放行|
|#7059 `w21d64pB9jk`|`NATIVE_CAPTION_VISUAL_BUDGET`|已采用的有界抽检路径替代旧全片视觉流程；须用当前源片实测，历史事件尚未解除|
|#7093 `g7ZscMABkK4`|`CHANNEL_POLICY_REJECT`|内容策略审核，不能作为程序故障自动绕过|
|#7113 `XCMMCNPQBDk`|`NATIVE_CAPTION_VISUAL_BUDGET`|已采用的有界抽检路径替代旧全片视觉流程；须用当前源片实测，历史事件尚未解除|
|#7114 `THUSzemA-BM`|`CONTENT_CENSOR_BLOCK`|内容策略审核，不能作为程序故障自动绕过|
|#7108 `cfHekZAC-o4`|`WECHAT_DELIVERY_UNVERIFIED`|已跨提交边界/结果待核实；保留UNCERTAIN，不重复上传，遵守现行不自动查询策略|
|#7008 `jnJX5Q9QJgQ`|`NATIVE_CAPTION_VISUAL_BUDGET`|已采用的有界抽检路径替代旧全片视觉流程；须用当前源片实测，历史事件尚未解除|
|#7010 `p-nVeVG48FY`|`SUBTITLE_REPAIR_TRANSLATION_BUDGET_EXHAUSTED`|需单独核查前置供应商消耗；当前NEEDS_REPAIR，不清累计账本|
|#7089 `z9VaYmwImt8`|`BURNED_CAPTION_REPAIR_UNCERTAIN`|原画面文字角色/定位不明确；保留像素与证据，不能把清零当作擦除授权|
|#7013 `6kOHnXRiM58`|`WECHAT_DELIVERY_UNVERIFIED`|已跨提交边界/结果待核实；保留UNCERTAIN，不重复上传，遵守现行不自动查询策略|
|#7135 `ZVGS33A0nK0`|`NATIVE_CAPTION_INCOMPLETE`|确认尾段轻微越界；修复抽样窗口边界，需实测|
|#7068 `UHmZl3PiOj0`|`STAGE_EXECUTION_FAILED`|修复进度并发写入；旧长OCR路径也已替换，真实退出原因待进一步证据|
|#7121 `LxCqqKwqeCo`|`SUBTITLE_REPAIR_TOTAL_TIMEOUT`|股数误判、局部过度修复、预算分类已修；历史累计预算耗尽且缺32段，未解除|
|#7070 `r2xjrq_e62k`|`NATIVE_CAPTION_INCOMPLETE`|旧完整识别超时；当前抽检路径需实测，不直接放行|
|#7071 `98MJXtcgEjc`|`STAGE_EXECUTION_FAILED`|修复进度并发写入；旧长OCR路径也已替换，真实退出原因待进一步证据|
|#7146 `RYYM-6C4Vs4`|`NATIVE_CAPTION_INCOMPLETE`|确认尾段轻微越界；修复抽样窗口边界，需实测|
|#7137 `M3hvIUwAL7c`|`NATIVE_CAPTION_INCOMPLETE`|确认ABSENT分支误拦截并修复；需补完全部窗口后核验|
|#7072 `UGisxZs1Av4`|`NATIVE_CAPTION_INCOMPLETE`|确认ABSENT分支误拦截并修复；需补完全部窗口后核验|
|#7073 `ZnD_l263eB4`|`NATIVE_CAPTION_INCOMPLETE`|确认ABSENT分支误拦截并修复；需补完全部窗口后核验|
|#7134 `rAJXUWjhHt8`|`NATIVE_CAPTION_INCOMPLETE`|确认ABSENT分支误拦截并修复；需补完全部窗口后核验|

## 验证与采用

最终隔离测试证据：`/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/video-pytest-vjslhggn/`；具体数量见pytest.log，退出码0，边界探针退出码0。完整源快照摘要 `ab956061b1bf310da1a21715a352831ccc46465aaf612c03db1fdb8af11e7f82`。

实现、隔离测试、Git提交/推送、驻留后台采用、源片抽检通过、完整成片恢复及平台回读分别记账。运行采用及实测结果在后续回读追加，未完成前不得标已恢复或关闭事项。
