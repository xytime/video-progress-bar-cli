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
- 英文字幕属于“无中文字幕”；只有实际看图确认中文却OCR不足时才复核。密集幻灯片不再发送重复raw_box及多余浮点精度，保留每帧图像、全部原文、原行号和原始完整审计，90k上限不变。
- 阶段回调和心跳的文件写入共用同一锁，消除同名临时文件竞争与旧快照覆盖新阶段。#7068/#7071确有该竞争，但其进程退出根因缺少退出码证据，不能据此宣布已经根治。补充带stderr时的子进程退出码记录，供后续定位。

## 逐项清单

|任务|原错误|本轮处理/剩余证据|
|---|---|---|
|#7000 `M1xyX3ZQJ6k`|`NATIVE_CAPTION_VISUAL_BUDGET`|真实源片/ASR绑定的首中尾抽检已通过，分流为GENERATE；仅证明识别阶段，不代表完整成片或队列已恢复|
|#7026 `NSPhe3R_kQs`|`CHANNEL_POLICY_REJECT`|内容策略审核，不能作为程序故障自动绕过|
|#7042 `F8Y7IigdTHA`|`NATIVE_CAPTION_VISUAL_BUDGET`|真实源片/ASR绑定的首中尾抽检已通过，分流为GENERATE；仅证明识别阶段，不代表完整成片或队列已恢复|
|#7031 `CatuGloDkTQ`|`NATIVE_CAPTION_VISUAL_BUDGET`|真实源片121.52秒、音频121.58秒，缓存ASR延伸至146.96秒且含乱码；不能作为轻微片尾误差放行，须重核ASR|
|#7045 `-D4TV5q5yOM`|`BURNED_CAPTION_REPAIR_UNCERTAIN`|失败帧为中央英文标题/叠字，并非邻近语音对白；按具名源摘要及完整ASR绑定，保留原画面并设独立双语区；全部段落的静态渲染、宽高和时间轴验证通过，完整成片待验证|
|#7046 `f38UjmZEVv0`|`CHANNEL_POLICY_REJECT`|内容策略审核，不能作为程序故障自动绕过|
|#7054 `6ZpaPFXIgE4`|`CONTENT_CENSOR_BLOCK`|内容策略审核，不能作为程序故障自动绕过|
|#7030 `5e-k8bBMFvY`|`BURNED_CAPTION_REPAIR_UNCERTAIN`|失败帧为中央英文标题/叠字，并非邻近语音对白；按具名源摘要及完整ASR绑定，保留原画面并设独立双语区；全部段落的静态渲染、宽高和时间轴验证通过，完整成片待验证|
|#7007 `SqwiCJ8r8_Q`|`NATIVE_CAPTION_VISUAL_BUDGET`|真实源片/ASR绑定的首中尾抽检已通过，分流为GENERATE；仅证明识别阶段，不代表完整成片或队列已恢复|
|#7012 `YDeRVjCSCQU`|`NATIVE_CAPTION_VISUAL_BUDGET`|真实源片/ASR绑定的首中尾抽检已通过，分流为GENERATE；仅证明识别阶段，不代表完整成片或队列已恢复|
|#7065 `C0ysAy2LXjY`|`NATIVE_CAPTION_VISUAL_BUDGET`|真实源片/ASR绑定的首中尾抽检已通过，分流为GENERATE；仅证明识别阶段，不代表完整成片或队列已恢复|
|#7055 `1Vjzvjy3xig`|`NATIVE_CAPTION_INCOMPLETE`|真实源片/ASR绑定的首中尾抽检已通过，分流为GENERATE；仅证明识别阶段，不代表完整成片或队列已恢复|
|#7059 `w21d64pB9jk`|`NATIVE_CAPTION_VISUAL_BUDGET`|真实源片/ASR绑定的首中尾抽检已通过，分流为GENERATE；仅证明识别阶段，不代表完整成片或队列已恢复|
|#7093 `g7ZscMABkK4`|`CHANNEL_POLICY_REJECT`|内容策略审核，不能作为程序故障自动绕过|
|#7113 `XCMMCNPQBDk`|`NATIVE_CAPTION_VISUAL_BUDGET`|修复英文字幕被错误要求引用中文行的提示冲突；第二轮真实抽检已通过GENERATE，队列未解除|
|#7114 `THUSzemA-BM`|`CONTENT_CENSOR_BLOCK`|内容策略审核，不能作为程序故障自动绕过|
|#7108 `cfHekZAC-o4`|`WECHAT_DELIVERY_UNVERIFIED`|已跨提交边界/结果待核实；保留UNCERTAIN，不重复上传，遵守现行不自动查询策略|
|#7008 `jnJX5Q9QJgQ`|`NATIVE_CAPTION_VISUAL_BUDGET`|密集幻灯片的重复raw_box和浮点精度撑满语义输入；保留所有行/图像，仅精简运输数据，第二轮真实抽检已通过GENERATE，队列未解除|
|#7010 `p-nVeVG48FY`|`SUBTITLE_REPAIR_TRANSLATION_BUDGET_EXHAUSTED`|183段完整翻译实测通过（480.4秒），原ASR未改；正文正确且仅失配词注已清理时立即接纳，避免继续调用其他供应商耗尽窗口；队列恢复另记|
|#7089 `z9VaYmwImt8`|`BURNED_CAPTION_REPAIR_UNCERTAIN`|失败帧为中央英文标题/叠字，并非邻近语音对白；按具名源摘要及完整ASR绑定，保留原画面并设独立双语区；全部段落的静态渲染、宽高和时间轴验证通过，完整成片待验证|
|#7013 `6kOHnXRiM58`|`WECHAT_DELIVERY_UNVERIFIED`|已跨提交边界/结果待核实；保留UNCERTAIN，不重复上传，遵守现行不自动查询策略|
|#7135 `ZVGS33A0nK0`|`NATIVE_CAPTION_INCOMPLETE`|真实源片/ASR绑定的首中尾抽检已通过，分流为GENERATE；仅证明识别阶段，不代表完整成片或队列已恢复|
|#7068 `UHmZl3PiOj0`|`STAGE_EXECUTION_FAILED`|真实源片/ASR绑定的首中尾抽检已通过，分流为GENERATE；仅证明识别阶段，不代表完整成片或队列已恢复|
|#7121 `LxCqqKwqeCo`|`SUBTITLE_REPAIR_TOTAL_TIMEOUT`|真实定点修复第30/59/87段金额遗漏，127段完整翻译75.6秒通过质量门；保留原Codex耗尽账和全局单位告警，未扩额；队列恢复另记|
|#7070 `r2xjrq_e62k`|`NATIVE_CAPTION_INCOMPLETE`|真实源片/ASR绑定的首中尾抽检已通过，分流为GENERATE；仅证明识别阶段，不代表完整成片或队列已恢复|
|#7071 `98MJXtcgEjc`|`STAGE_EXECUTION_FAILED`|真实源片/ASR绑定的首中尾抽检已通过，分流为GENERATE；仅证明识别阶段，不代表完整成片或队列已恢复|
|#7146 `RYYM-6C4Vs4`|`NATIVE_CAPTION_INCOMPLETE`|真实源片/ASR绑定的首中尾抽检已通过，分流为GENERATE；仅证明识别阶段，不代表完整成片或队列已恢复|
|#7137 `M3hvIUwAL7c`|`NATIVE_CAPTION_INCOMPLETE`|真实源片/ASR绑定的首中尾抽检已通过，分流为GENERATE；仅证明识别阶段，不代表完整成片或队列已恢复|
|#7072 `UGisxZs1Av4`|`NATIVE_CAPTION_INCOMPLETE`|真实源片/ASR绑定的首中尾抽检已通过，分流为GENERATE；仅证明识别阶段，不代表完整成片或队列已恢复|
|#7073 `ZnD_l263eB4`|`NATIVE_CAPTION_INCOMPLETE`|真实源片/ASR绑定的首中尾抽检已通过，分流为GENERATE；仅证明识别阶段，不代表完整成片或队列已恢复|
|#7134 `rAJXUWjhHt8`|`NATIVE_CAPTION_INCOMPLETE`|真实源片/ASR绑定的首中尾抽检已通过，分流为GENERATE；仅证明识别阶段，不代表完整成片或队列已恢复|

## 验证与采用

第二轮隔离测试：604项通过，pytest及边界探针退出码均为0。证据：`/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/video-pytest-dijq7osz/`，源快照摘要 `9579d83a84b0c478e29b75680626fe096492a73796993c031ecd64d3f7ec5713`。两项新增回归在修复前均复现失败：`video-pytest-20z1_est`。

实现、隔离测试、Git提交/推送、驻留后台采用、源片抽检通过、完整成片恢复及平台回读分别记账。运行采用及实测结果在后续回读追加，未完成前不得标已恢复或关闭事项。

首轮31条基线在2026-10-31T23:12:59Z的一致备份回读仍为29条FAILED、2条UNCERTAIN；滚动24小时20条历史失败事件、48小时31条。没有删除事件或重置状态。代码修复、抽检通过和完整恢复不能混为“清零”。

第一轮修复提交 `a9c8110` 已推送，原生部署 `204b5cd78d374c7fa36f917409a01205` 的9个步骤COMPLETE、verify.ok=true、维护闸门RUNNING/IDLE，5类驻留角色采用同一源摘要 `227a3efdb072b5103a00ef30fbb0b54f8e94a6f4513ccb906af6ec9a760d4e49`。第二轮提交 `e68cbec` 已推送；原生部署 `0fadf58fe22549d19a91c1822f893591` 也已完成全部9步，verify.ok=true、闸门RUNNING/IDLE；5类驻留角色采用源摘要 `92d8c5bbc2cc54c6759a6d778c69308515297c62496e4fa9fdc3cd96fa7477a1`。证据：调查目录 `runtime-adopted-r2.json` 和外置 `deployment-r3/`。

真实源片复测：19条首轮16条通过，#7113/#7008修复后第二轮均通过，累计18条完成抽检分流；#7031因ASR严重越界保留复核。两轮原始结果分别位于调查目录的 `sampling-validation-results.json`、`sampling-validation-r2-results.json`，独立副本包含源摘要/ASR摘要/实际画面/语义证据。全程未写队列或调用上传投稿。

第三轮新增：拒绝超过源片尾1秒的ASR缓存及新结果；具名单片保持全画面、完整字幕及源摘要绑定；中文按高亮原子实际折行高度缩字号。Gemini仅修复问题段，沿用原供应商和共享期限，背景不得覆盖该段事实。所有非目标段正文和词注保持。独立补丁兼容不含扩展词汇字段的主干候选。

第三轮实施前的综合隔离回归702项通过（`video-pytest-p2a9e7m9`）；最终兼容调整、Git提交、原生部署和队列恢复以追加回执为准。#7031重识别时间轴已不越界，但尾部文本在不同模型间不一致，仍保留人工/音频复核，不能以截断或删段代替修复。

第三轮最终验证：工作区综合隔离703项通过（`video-pytest-_9lbcm5e`），源快照摘要 `f5976b7a227b67aa32b35cae982e88adb47d209fb95abeb14c6cde53c639963c`；独立导出的已提交补丁隔离126项通过（`video-pytest-nubw1x50`），源快照摘要 `abd2658255a025f4117c8d9659f700d183a4f90f6914c6b8b5cd5b337107d281`。两轮边界探针及pytest退出码均为0，各有两项既有弃用告警。

第三轮提交 `3ee211610357520b883be220348a4cb40d7b41de` 已推送。原生部署 `94b2158ec3f04225827ae65a7ecb344b`（外置 `subtitle-sparse-repair-20261101/deployment-r5/`）全部9步COMPLETE、verify.ok=true、维护闸门RUNNING/IDLE；5类驻留角色采用源摘要 `0a9446b8b930144ec5302e64f9244e12905c8a03a9451f8acedd71ef513ff0f6`。`deployment-r4/` 因已有定时作业活动而未能完成计划，失败证据保留；未绕过该保护。

#7010和#7121的完整译文在最终合同下重新进行宿主核验并保存原供应商及质量审计，新增供应商调用均为0，未扩充旧额度或修改ASR。最终合同分别为 `a06d81cd3574b8b15186f5f67f8fcfa8f8c5fea97cd6f1e7d1074a1d3c3cefbf`、`8365aee36fec66b3c2cd0a10b63467f3a86685f91130f30c4144ebe46cf3a15e`；检查点摘要分别为 `ba897a195007d75d2b04cc3d0278657c93a4e80a6210bed4ac82d75c65963183`、`6bdbe77ed7eb52e79d2d57dde96c8e914a6dd63155cc6100833f548e1c10c0ab`。原文件和回执副本保存在 `completed-revalidation/`。完整成片及队列恢复仍按各自实际回执记录。

### 全片验证与原生恢复续跑

2026-11-01 08:03 BJ 前，#7121和#7010均经正式`VerticalCaptionProcessor`完成完整烧录、整片解码、时长比对、同源绑定与成功回执校验。成片摘要分别为`dc95a552f063dd24bd0edec69b2d73d13e7ed6452fa1fcca8b9b643815dcc2c7`、`01b7d37d87f6e56be65bb743bef6a85829c4c481d001a29f8348362ab61c74f3`。各保留一项质量告警；原ASR和完整译文检查点均被正常复用，未重译。实际成片3秒抽帧检查中英字幕分层，未与原片字幕重叠。

两条任务凭上述成功回执，经DAL正式`resolve_subtitle_recovery`从`NEEDS_REPAIR`转为`RESOLVED`，原尝试次数（#7121=1、#7010=0）和到期时间保持不变。随后通过官方预览/批次API创建恢复批次`3d91474d-adf1-4054-a7c1-0036da769cb6`，仅选择#7010/#7121；没有重置额度、冷却、退避、优先级或制作时段保护。解除字幕链、批次等待与实际发布仍分开记账。

18条原字幕识别异常均在正式输出路径经过原生路由和同源ASR指纹核验，证据位于`production-caption-validation/results.json`。通过官方API建立持久恢复批次`d3d259e8-90b9-49a8-b424-bf83951cae38`，按最近24小时优先选择18个固定ID，全部沿用正常准入和完整流水线；初始实际回读为等待完整成片验证所持有的加工锁。抽检通过不表示这18条已有完整译文或成片。

改进事项`IMP-8D838006ECE7`（原字幕识别）及`IMP-8E4E0B94C2FD`（翻译超时）分别绑定18次真实原生路由样本及2次完整烧录样本，按已批准方案由`RUNTIME_ADOPTED`进入`OBSERVING`。未提前结束7天观察期，也未将队列等待或平台待核实算为已交付。

2026-11-01 08:06 BJ，三条英文标题叠字任务#7089/#7045/#7030的正式完整烧录、整片解码、时长和同源回执全部通过，均无质量告警；成片摘要依次为`5f30c27173797c9787b59621b1f6310fc1afbcfcad7da899bba2fb8bda83c4cd`、`17ebac0181d09a99c14087b85bd9fb1231f649b81c10683dc3e3fcd54a286e07`、`39c0582868e1b37ac14da653858edb2fd05adc766a62319f6a0e277e6dbc94d4`。3秒实际成片抽帧确认原英文叠字保留，新增双语区独立；完整回执与首中尾帧位于`production-caption-validation/{id}/`。随后通过官方单项重试API和新鲜engagement版本启动原流水线，未改变内容审查标记。

续跑暴露独立缺陷：#7045的YouTube ID以`-`开头，Web派发以独立`--object-key`参数传入时，被argparse解释为新选项，子进程在加工前退出。修复为等号绑定的单个参数，使用真实Web派发参数和真实CLI解析器回归普通ID、负号ID及负号ID分片身份。工作区隔离116项通过（`video-pytest-be7umb0k`，源摘要`da054bdea19578ff549c0ce2834a9a8dc12536e7601ad62938b0271860d073c7`）；边界探针/pytest均为0。确认该任务进程已退出、单片锁为空、无提交保护后，正式记录`VIDEO_TASK_ARGUMENT_PARSE_FAILED`，保留实际失败事件及已有成片，待运行采用后再由原入口续跑。

独立导出的暂存补丁首次验证发现主干已有依赖缺口：`run_ready_publications.py`导入的`LOADED_SOURCE_HASH`及浏览器能力检查/退避函数未进入提交。复用并选择性暂存工作区已经存在的对应实现及单项回归，保留其他未提交改动。没有借此重置浏览器配置或修改生产会话。

最终独立补丁隔离139项通过（`video-pytest-67abw3ap`，源摘要`7ca0e085fe728e7fefdc2e12f77c3882a865e53934545a5607b34d95268d4e12`）；边界探针、pytest均为0，8项既有FastAPI弃用告警。旧派发参数在相同真实解析回归中复现负号ID及其分片两项失败；最终两项通过。前次独立验证的依赖导入失败另行保留，不计为通过。

08:15 BJ一致备份回读：48小时31条历史故障任务中，26条FAILED、2条PROCESSING、1条AI_COVER_PENDING、2条UNCERTAIN。#7055已完成原生字幕全片渲染，进入正常AGY封面底图等待；批次项被标记FAILED的原因是素材待完成，不能据此认定字幕回归失败。#7089/#7030原生续跑仍持有单任务锁，保留现场。历史事件没有删除，未将入队或等待视为恢复成功。


### 08:38 BJ：维护接续、封面登录和 7031 复核

提交 `4805a7686a2b6fffa47935a844760a49e0d2bc94` 已推送；原生部署 `d4034a3f0bcc403c96388ed135162991`（外置 `deployment-r7/`）9步全部COMPLETE、verify.ok=true，5类驻留角色采用源摘要 `2c21575611dc47008602ecca54622c820be32da6969e9f572c55870f57d2d1f2`。部署期间原#7059在途字幕继续排空，未强杀或扩额。

#7059完整463段在原共享窗口内失败，失败凭据为 `subtitle_recovery/w21d64pB9jk/6225568fc1ef4f678c3709bf61137267.json`：Gemini预算耗尽、DeepSeek网络、Google限流、Codex窗口耗尽。Codex持久账本记录31次请求、累计355.197秒，总期限600秒，剩余部分未归零、未扩额；不能将已有155段缓存当作完整翻译。维护排空期间还发现字幕 `-m cli.main` 子进程未继承同项凭据，造成审计运行2018停在RUNNING且尝试为空。新增 `scripts/run_caption_task.py` 复用现有精确argv摘要和继承flock FD校验；实际子进程、Click CLI与DAL测试证明排空期间原任务可完成审计，错配参数和新任务被拒绝。

封面AGY真实只读探测返回“Please sign in to view available models”及“You are not logged into Antigravity”。新版CLI明确未登录过去被归为UNKNOWN，本轮修为AUTH_REQUIRED；正向证据仍必须来自本次认证日志。后台检查不启动OAuth、不消耗生成次数、不发送Telegram。已经告知用户需人工执行 `agy` 登录；未伪造认证或更换素材供应商。

#7031以large-v3真实重识别得到38段、末尾121.00秒，通过完整翻译质量门。首次全片制作停在原片中央英文标题“PETERS SLAMS GOP”；首尾画面复核没有完整中文字幕，原画面全部保留，绑定原片摘要及完整新ASR指纹采用独立双语区。首次登记误用容器121.579683秒，而烧录器读取视频轨121.5214秒，严格时长绑定拒绝后已修正登记为视频轨时长，未放宽容差或截断对白。前两次失败结果与日志均保留；完整成片通过与队列恢复须另有实际回执。

工作区及独立暂存版本各152项隔离回归通过（`video-pytest-hondk85_`、`video-pytest-lfpq8hw5`），8项既有FastAPI弃用告警。最终视频轨登记修正后各补跑9项版式回归通过（`video-pytest-aiwqmdem`、`video-pytest-p82v0gmf`），边界探针及pytest均为0；两次快照之间唯一源码变化为具名版式登记。独立版本首次标题测试失败源于生产片尾开关而夹具不产片尾，现使用隔离关闭片尾的配置；未改变生产开关。

08:36 BJ一致备份回读，48小时31条历史故障任务当前24条FAILED、1条TRANSCRIBING、4条AI_COVER_PENDING、2条UNCERTAIN；系统类未解24条、策略5条、提交待核实2条。随后#7113也完成原生全片进入封面等待。恢复批次中8条因预览后版本变化被保护性SKIPPED，后续只按新鲜预览重新判断资格，不能绕过版本校验。未删除历史事件，尚未清零。


### 09:02 BJ：实际采用、悬空恢复项和监控刷新误跳过

提交`ed4bd33f137d51113e4ec4c5647e9f3065365356`已推送；部署`2d2738830e574f449ba64ef9195133e5`（`deployment-r8/`）全部9步COMPLETE、verify.ok=true，5类驻留角色采用源摘要`56e9368528e416dd3dfd9702f2ce3ca6d6b200e6ec4357d4dc2c1ccfb5cf8a31`，证据为`runtime-adopted-r8.json`。#7008原有15分钟全片及片尾已正常完成，状态为AI_COVER_PENDING；实际子进程审计2021为SUCCEEDED，验证维护排空时继承凭据确已生效。

部署排空发现#7008单片进程及所有锁已退出，但恢复项10仍RUNNING，原生部署拒绝UNFINISHED_LEDGER。新增维护DAL对账在独立导出源测试18项通过：要求精确MAINTENANCE版本、无活动或未知准入、旧PID不存在、4把真实锁可独占、视频和恢复项整行未变化且5类平台账本无证据；只将该恢复项按实际封面等待原因结束为FAILED，视频整行及发布许可均保持。生产执行使用摘要与测试清单一致的独立模块，留存一致备份及前后回执；未修改维护闸门、部署日志或伪造完成。随后原生recover完成原部署。#7059历史审计2018亦按同源实际失败凭据结束为FAILED，未补造缺失的供应商尝试。

#7031第三次正式完整制作通过：121.579683秒，源片及成片时长一致，整片FFmpeg解码、同源绑定和成功回执均通过，字幕质量告警0。成片摘要`7c29cd943a78cc88bf843e7d7f97bc43f274b0ba37cae752bea3e20303128628`，首尾帧实看双语区独立、原英文标题保留。证据为`production-caption-validation/7031/result.json`；未调用投稿，未改内容审查标记。

恢复误跳过已定位：首轮8条任务与原始快照相比只变化`updated_at/view_count/like_count`，实际来自监控热度刷新；全行版本散列误把它们当作执行意图变化。修复仅排除这3项，其他已有与未来字段仍默认参与散列。真实SQLite监控upsert在预览、等待和启动三个阶段均可保持恢复；审批、来源、状态、正文标题、评分、裁剪、错误等关键变化仍拒绝。旧版本快照不原地改签，采用后必须重新预览。诊断同步改为只报告恢复项实际SKIPPED及已知批次状态，不再虚构“监督器已退出”；实际活动任务和内容策略优先保留。

09:02 BJ一致备份：48小时31条历史故障任务现23条FAILED、6条AI_COVER_PENDING、2条UNCERTAIN；24小时20条任务仍有16条系统类未解、2条策略、2条提交待核实。字幕通过及封面等待不等于发布成功，未清零、未删除历史事件。

本轮最终工作区及独立导出源各145项隔离回归通过，边界探针及pytest均为0，8项既有FastAPI弃用告警。证据分别`video-pytest-kwt3yeag`（源清单`3edffe4f04fd1b5323a01c0ec97edd16f75f00dc0b6da547f619caf2dea7421c`）及`video-pytest-glr4bnb6`（源清单`e4df115865095578eacda4a6d6a6f1ab1143aec1d325666031552e00962dc0ed`）。首次维护锁回归因上下文将内核锁异常按既有规则包装为MaintenanceDenied而失败，改正测试对该闭锁异常的期待后通过，未放宽生产行为。提交及运行采用另记。


### 09:14 BJ：恢复批次实际采用与下一条英文标题阻断

提交`94334ab6137599bfea07cb25fc5cf2b092624669`已推送；部署`1c8f4e4e1fc949ceb46821ff60cf787c`（外置`deployment-r11/`）9步全部COMPLETE、verify.ok=true。5类驻留角色回读同一源码摘要`b5d102fdafa4a5789a9b1bc2ccb195f4993d595dcd008fa03e7c42a8f9d81e6a`；证据`runtime-adopted-r9.json`。部署途中发现中间版本ready-worker，先逐文件核对其544份源码与已通过隔离测试清单及进程身份，再经原生维护退役；STOP_TIMEOUT原始失败回执保留。原部署恢复后已确认该身份退出，未改写失败回执或维护闸门，证据`intermediate-worker-retirement-{before,final}.json`。

16条旧SKIPPED任务按新鲜48小时预览创建原生批次`55a52e67-7ba8-4236-9a1c-aef55a36368a`；#7031全片通过后创建原生批次`764ddb66-bcbd-49f4-94f5-76da14c4aa70`。额度、冷却、退避均未重置，入队不等于恢复成功。原调度器已对#7055/#7045执行发表，现为UNCERTAIN；保留防重投和当前不自动查询策略，不宣称平台公开。封面原生兜底恢复按已有许可执行；AGY仍需登录，Luna质量未过或未产出图的失败和确定性封面来源均留档，不宣称AI封面成功。

09:11 BJ一致备份：48小时31条历史故障任务当前22条FAILED、4条UNCERTAIN、2条PENDING、1条PUBLISHING、1条PROCESSING、1条AI_COVER_PENDING；系统类21条未解、策略5条、投递待核实4条。24小时20条任务系统类14条未解、策略2条、投递待核实3条。计数保留历史事件；未清零。

本地改进建议报告已通过`improvement_review.py report --refresh`刷新，73项记录及审批状态保留；报告`output/improvement/runs/dc3cdd784c7a4e9d8993d90df37989ff/report.md`，未发送消息。既有每日09:00报告与周一周报机制保持，已批准事项仍按7日观察验收。

下一条#7135 `ZVGS33A0nK0`原生翻译33段通过后，在英文标题“Why the wealth gap may be hurting more than your wallet”被误当对白字幕时停止。真实首帧、70秒和136秒画面核实：首帧为中央英文标题，后续为原演讲画面，没有完整中文字幕。沿用既有具名独立双语区修复，保留全部原画面和原ASR，不擦标题。原片SHA256`aa91512004ed2d8a8d390e23f8d5c1d77d5dee9c349a87a6bf91cb56301a7015`；完整33段时间轴摘要`b3a29097498762c9b277abe020b66b34566671d094237adc17e634f6b35f522a`，绑定实际视频轨142.684208秒。真实完整翻译时间轴验证通过；尚待新版本采用及全片验收。

候选完整运行源隔离74项通过，边界探针及pytest均为0、两项既有pysubs2弃用告警；证据`video-pytest-14mkj_66`，源清单`b5a47ccfe7228751cb90b13a977058882270ff11493f2602e617a6c0361d53df`。具名登记继续拒绝未知来源、错误源片和删改对白。既有登记文件摘要作为版式凭据的一部分，本轮登记变化会使旧版式凭据失效；由原生校验决定必要重渲，不伪造旧凭据或修改提交待核实任务。


## 09:24 BJ 运行回读与恢复收尾修复

提交 `cbc6796da8df04f88ecbff43fbbdeeb07e1367dc` 已推送；原生部署 `810cca580b144751ab2f5d811d366d3d`（外置 `deployment-r12/`）全部9步COMPLETE、verify.ok=true，5类驻留角色采用源码摘要 `f2f9c8a7a67fa032d0632e9726323c60a001dce0af5a716b09142cd941e8cb0f`。独立提交导出源74项隔离通过，证据 `video-pytest-77dd0eno`、源清单 `6aa6c91bac99914a709a7f553bf625eac89cc2d57b408b1cb11e0e550b9aed5a`。

#7010 的原生正文、互动提示及词汇片尾均正常完成，进入真实AI_COVER_PENDING。原进程77434已退出，但恢复项41仍RUNNING，导致维护检查拒绝恢复。经已部署且145项验证覆盖的维护DAL，核对维护版本241、已退出PID、4个空闲内核锁、完整视频/恢复项/批次快照及5张投稿保护表后，只把遗留恢复项结束为实际封面等待原因，视频、许可与平台账本完全不变。备份及前后回读为 `cover-item-reconciliation-r12{,-before}.json`；第一次ACTION_RESULT_UNKNOWN保留，不修改部署回执。

重复根因在发布窗口直接调用的 `PublishingRecoveryService.dispatch_once`：内层视频准入在加工返回时关闭，外层最终回写未被同项准入覆盖。将“单项激活—原流水线—结果回写”纳入相同视频身份的一次准入；每次只正式启动一项，新任务仍重新过闸门，不把整个批次包成可延续任务。真实SQLite与维护flock验证封面等待、失败、提交待核实、回队和异常五种收尾，以及资格核对后维护关闭的新领取竞态。

候选运行源104项隔离回归通过，边界探针及pytest均0，证据 `video-pytest-j4e16v_4`，源清单 `225f2f75ab3578826082fd78580578dae7dea5371524c2aeeaca58de241e2bc1`。首次测试误用会写入过期状态的许可查询而被维护正确拒绝，改为只读资格证据后通过；未修改生产维护规则。首次测试命令包含不存在文件，退出4，未作为通过证据。

09:21 BJ一致备份：48小时31条历史故障任务当前22条FAILED、6条UNCERTAIN、2条AI_COVER_PENDING、1条PENDING；24小时20条任务当前13条FAILED、4条UNCERTAIN、2条AI_COVER_PENDING、1条PENDING。已有发表动作的结果仍待人工核实、禁止重投；5条策略/内容拦截不技术放行，未清零。#7135完整字幕验证初次因真实加工锁占用而未启动；#7059在原持久预算内继续翻译，均不得提前宣告完成。


独立提交导出首次104项中102通过、2项既有发布窗口测试失败，证据 `video-pytest-gu7h2wbz`。查明主干缺失已经在线采用的“旧视频号作品不自动回查”无动作实现，而测试已进入主干；本次只选择性补入该无动作兼容入口及原有对应历史说明，不纳入工作区的保活告警改动。真实运行行为保持不查询、不领取、不通知，继续保护UNCERTAIN原始提交事实。


## 09:43 BJ：收尾修复实际采用、全片结果与诊断阶段纠正

提交 `5ee015953a63debdc00eab716388d2f5224e9461` 已推送；原生部署 `a9623c06a890422297a820bf74491e16`（外置 `deployment-r14/`）9步COMPLETE、verify.ok=true，维护闸门RUNNING。5类驻留角色在新进程身份下采用源码摘要 `0831d233fb9d54f241118d96eeef72846141868048e23d2da107ba4a1d5e9a06`，证据 `runtime-adopted-r11.json`。完整候选及独立提交导出源各104项隔离通过，后者为 `video-pytest-orf2trey`、清单 `7c24efbea72c5bf5e69306ab8c1a4eeada4826e217e9b8954af24f571f2b0509`。此前计划因定时任务活动被拒绝，以及维护恢复暂时拒绝的原始证据均保留，没有绕过准入。#7073 原生正文和片尾完成进入AI_COVER_PENDING，恢复项已正常结束而未遗留RUNNING；实际回执 `r11-first-native-recovery-finalization.json`。

#7135 正式完整字幕制作通过：142.756281秒，与原片容器时长一致，整片FFmpeg解码退出0，质量告警0，同源及成功回执有效；成片SHA256 `edb66194ebbaa6672c6f048cb620ce4480c3e0479705b46c01204a75e1c101a5`。0秒、70秒和136秒真实成片画面已复核，原英文标题与演讲全画面保留，双语字幕位于独立区域。官方单项重试API在新鲜版本、真实空闲单片锁及无投稿保护的前提下恢复原流水线；09:37原生正文、互动及片尾完成，进入AI_COVER_PENDING，证据 `production-caption-validation/7135/` 与 `7135-native-restoration.json`。等待封面不等于已发表。

#7059 在既有持久预算内的续跑于09:28实际失败，完整463段译文未完成，原始原因total_timeout。Codex有效分批缓存由155增至215段，但仍非完整翻译；持久账本累计45次请求、600.022秒，原上限600秒已耗尽，active_window为空。证据 `production-caption-validation/7059/result.json`、`7059-budget-{before,after}-continuation.json`。没有重置预算、截断字幕或把部分缓存算作恢复。这与少量不影响全片的字幕瑕疵不同，仍为真实未解决项。

09:37一致备份按初始固定队列计数，避免滚动窗口老化误算恢复：最初24小时20条现10条FAILED、3条AI_COVER_PENDING、6条UNCERTAIN、1条TRANSCRIBING；系统类未解11条、策略2条、提交待核实6条。最初48小时31条现19条FAILED、3条AI_COVER_PENDING、8条UNCERTAIN、1条TRANSCRIBING；系统类未解17条、策略5条、提交待核实8条。滚动48小时现30条，减少的一条是窗口老化，不是修复。固定计数及逐条事实见 `live-audits/20261101T013735Z/audit.json`。原审批与禁止自动回查、重投保持。

后台阶段误判已复现：#7135已等封面，旧字幕进度仍显示SOURCE_CAPTION_LOCATING；投稿后的任务也被旧TRANSLATING覆盖。仅让已知字幕后续状态决定当前阶段，不修改异常分类、恢复判据或投稿凭据。8项旧版复现失败、2项当前字幕反例通过，证据 `video-pytest-4dlt10x7`。候选完整运行源143项隔离通过，边界探针/pytest均0、8项既有FastAPI弃用告警，证据 `video-pytest-4jgp0862`、源清单 `74d47d38b0522125ff3be5e1758568f7a9db19412e3af6590aa93d02dafe1a75`。独立提交导出、运行采用及线上回读另记，不提前声明上线。

本地改进报告已刷新，73项建议保留审批及7日观察期，文件 `output/improvement/runs/efb78e61e0104455991841690c5a4ee3/report.md`；没有发送外部消息。恢复队列下一条#7068自09:37正常转录，尚无新的失败回执，不因耗时推断根因或重启。


## 09:56 BJ：诊断修复上线与生词词典重复扫描

提交 `87b91a2e7a5e86cde5c73eda97dbae402d582aca` 已推送。原生部署 `9975746501164a4d9fe7480d1f164d6f`（外置 `deployment-r17/`）9步COMPLETE、verify.ok=true；5类驻留角色回读同一源码摘要 `90b9e7e38ea60065d63dde3cb2cd11be93a51fa2c544dbe1a826c755f8fc0bd9`，维护恢复RUNNING，证据 `runtime-adopted-r12.json`。独立提交导出143项隔离通过，证据 `video-pytest-mgqvr4gi`、清单 `2014d736142a63b3721d86da570578b7a8f3f889daf7f03ffa95120b608b8cc8`。独立导出首次缺少Git清单退出2，初始化外置副本后重验，不将失败算作通过。

本次维护245关闭时，#7068原生字幕、互动提示和词汇片尾继续正常完成，随后恢复项结束并释放准入，未遗留RUNNING；原生部署因此自然排空完成，没有终止任务或重置锁。实际项28的最终状态FAILED保存真实“等待AGY专属底图”原因，视频为AI_COVER_PENDING，不能把该账本状态当字幕再次失败；证据 `r11-native-finalization-under-maintenance-r17.json`。下一条#7070由原生恢复批次正常领取。09:53一致备份初始48小时31条中为18条FAILED、4条AI_COVER_PENDING、8条UNCERTAIN、1条TRANSCRIBING，系统未解决17条、策略5条、投递待核实8条；初始24小时20条中系统未解决11条、策略2条、待核实6条。没有清零。

#7068于09:45已通过翻译质量门，但其子进程直到09:49才完成。真实3秒原生进程采样 `7068-caption-native-sample.txt` 显示主线程反复读取CSV；源代码确认生词导出对每个缺少音标或词性的词都重新构建VocabularyLeveler，并可能扫描整个ECDICT。旧代码的有效离线复现 `video-pytest-kdrtprak`：4个词创建4个词典，而目标为1次；实际音标、词性、首现语境与原逐词结果已逐项核对。

修复仅让单次导出共享词典并调用既有prepare_words批量预热，随后仍按各词首现原句选择词性；已有音标、词性、释义、等级、时间戳及缺词启发式兜底保持。翻译供应商、质量规则、预算和字幕时间轴不变；源码AST对照证明运行版本仅两个导出方法变化，翻译合同所绑定方法完全相同，证据外置 `r13-source-boundary.json`。主干尚缺少已经在线使用的Antigravity生词导出实现；为使补丁可独立使用，本次选择性纳入该实现的必要方法、调用、属性和导入，保留原作者记录。工作区其他供应商元数据扩展和重复导入不进入提交，不改写无关修改。

候选完整运行源55项隔离回归通过，边界探针和pytest均为0，无告警，证据 `video-pytest-2kt2i3xg`，源清单 `4dc37c04d1b8725672c78a0d4d960957a96daf322453b1d60778531754074dda`。覆盖真实CSV读取、原逐词输出对照、已有元数据、词表缺失、真实SQLite及切片路径、词典本体、字幕完成快照、翻译守门、准入延续与进度竞争。早期夹具为空词表、音标格式期待和共享测试库重复ID的问题均修正；失败证据保留，不计入通过。独立提交导出和运行采用另记。


## 10:09 BJ：词典扫描修复实际采用与词汇片尾投稿回执

提交 `f23ab73632185de3f5dfa9cd6fb937da7202fde1` 已推送；原生部署 `9584d806b9b14b2da3165c06c9f70713`（外置 `deployment-r18/`）全部9步COMPLETE、verify.ok=true。5类驻留角色实际采用源码摘要 `04887e0378bda788cff6e3813b23aa17cf4913e1f34d326b373223f00105cf87`，证据 `runtime-adopted-r13.json`。最终完整候选55项通过，证据 `video-pytest-2kt2i3xg`、清单 `4dc37c04d1b8725672c78a0d4d960957a96daf322453b1d60778531754074dda`；独立提交源48项通过，证据 `video-pytest-da2jxeb8`、清单 `d32e12ac7819c8cc68fc37e81f6f0f4c39899728e17578d654ad5ef433e3e666`。边界探针及pytest均0。

使用#7068的12个实际生词与完整公开离线词典，在隔离进程比较缺少音标/词性的相同输入：原逐词构建12次、17.2478秒；批量构建1次、1.8763秒，所有音标、词性、级别输出一致。证据 `r13-full-dictionary-benchmark.json` / `video-pytest-x_sotbd6`。这只证明该导出工作负载，不代表全片加速倍数。#7070在维护247关闭期间继续正常完成字幕、互动及片尾，真实恢复项29结束为封面等待并释放准入；随后原生部署排空完成。一次adopt前空闲检查拒绝的原始回执保留，显式恢复重新核验通过，没有终止在途任务。#7071由恢复批次正常领取并进入翻译。

10:06一致备份，最初24小时20条：8条FAILED、4条AI_COVER_PENDING、7条UNCERTAIN、1条TRANSCRIBING；系统类11条未解、策略2条、投递待核实7条。最初48小时31条：17条FAILED、4条AI_COVER_PENDING、9条UNCERTAIN、1条TRANSCRIBING；系统类17条、策略5条、投递待核实9条。滚动窗口老化不算恢复，实际事实在 `live-audits/20261101T020602Z/audit.json`。

继续核对本地投稿证据发现#7008、#7010均有同成片的submit_intent、submit_click_returned=true、manual_confirmation_required=true及禁止自动结果查询记录，但`operation_receipts.submission_feedback`只识别vertical/interactive文件名，漏认原生发布入口产出的`<prefix>_vocab.mp4`，错误降为RESULT_UNKNOWN。修复仅认可同任务/同切片的确切词汇片尾路径，仍要求全部原有标志、尝试路径边界与输入一致性；未知成片、其他任务/切片及坏证据继续拒绝。显示为“已执行发表，等待人工确认”，保留UNCERTAIN、不查询平台、不改写投稿账本、不重传。原始脱敏证据 `local-uncertain-submission-receipts-audit.json`。

旧版本新增回归3项失败、26项通过，证据 `video-pytest-urm8qds7`（两项直接复现词汇片尾误判，通知分支一项进入错误兜底）。修复后最终候选97项隔离通过，边界探针及pytest均0，8项既有FastAPI弃用告警；证据 `video-pytest-hm2qw463`，源清单 `f6ad6e7e7b3b160a86a5a2a9903148a8c1fe15b72e277ab16dec100ac649416e`。独立提交导出及本轮运行采用另记。


## 10:18 BJ：回执修复实际采用与 Bot 网络启动异常

提交 `385a5401f7a4141fc9fee66cfeb0b39f9efe978d` 已推送。原生部署 `c83d0469aca54ca592c942274b6209ee`（外置 `deployment-r21/`）9步COMPLETE、verify.ok=true，维护恢复RUNNING；5类驻留角色核对同一源码摘要 `56121cd677bd84ec7c8fb066535d893b7f745ad0e06173c0f45247030b87268b`，证据 `runtime-adopted-r14.json`。完整候选及独立提交导出各97项隔离通过，后者 `video-pytest-upq0hd6e` / `a4f59dfee22713b8caa6b119be05ba2245e4310d08c192cc8ba1d5135be6460e`，均8项既有FastAPI告警。两次部署基线因Bot定时进程身份变化拒绝的记录保留，未改写计划；最终正常排空后采用。

真实Bot启动日志表明初始化get_me期间ConnectError导致重复退出。无认证的Telegram根地址探测：直连连接被重置，当前macOS系统代理127.0.0.1:17890可达。进一步核对Bot正常模块加载后普通getproxies返回空值，macOS系统配置读取仍返回可达代理。修复让Bot通过settings既有TCP校验明确读取系统配置，并把同一代理接入主请求和getUpdates两个独立客户端，保持池大小、超时、并发和权限不变；其他get_active_proxies调用默认行为不变，无新环境变量。不读取或输出实际认证值。

真实SDK离线构造证据 `bot-candidate-real-routing-readback.json` 显示两池均使用当前代理；未初始化Bot、未认证、未发送消息。旧实现真实SDK复现2失败1通过，证据 `video-pytest-fnp65k1r`。最终完整候选93项及20子测试通过、9项既有弃用告警，边界探针及pytest均0；证据 `video-pytest-9k4p8m7s`，源清单 `8b35e793c0f202c212702191dc7f420ebcf98c4dc8663f68f8d9ae5e4e127c89`。独立提交导出、原生部署和启动稳定性另记，尚不据离线构造宣告运行恢复。

10:16一致备份固定24小时20条：8条FAILED、2条AI_COVER_PENDING、8条UNCERTAIN、1条PUBLISHING、1条TRANSCRIBING；系统10条、策略2条、提交待核实8条。固定48小时31条：17条FAILED、2条AI_COVER_PENDING、10条UNCERTAIN、1条PUBLISHING、1条TRANSCRIBING；系统16条、策略5条、提交待核实10条。#7071本轮供应商翻译窗口耗尽，原累计预算尚有约301秒，完整翻译当时仍未完成；#7146由原生恢复批次领取，#7135进入原生投稿。保留待核实与预算保护，没有清零。


## 10:37 BJ：Bot 网络恢复回读、重复轮询与两条字幕续跑

提交 `0d543bbe859ba32dd0132edf95584c7b0b6c4ca4` 已推送；原生部署 `16c3e9ecd6ea493897fc880c0a5724ca`（外置 `deployment-r22/`）9步COMPLETE、verify.ok=true，维护恢复RUNNING，5类角色核对同一实际源码摘要 `28b93db2c7683f2615699b33f668dcf959ee5129a2ba65158d82e7b4da6fef76`。独立提交导出93项及20子测试隔离通过、9项既有弃用告警；证据 `video-pytest-o5jkn4em`，源清单 `9e4639188161d50d17bf1d0104149156648f9734df46474ad641a29631d42e23`。运行证据 `runtime-adopted-r15.json`。

新原生Bot PID30913已正常初始化，启动后未再出现NetworkError或ConnectError，但getUpdates出现另一个实例竞争的Conflict。核对发现4天前遗留的PID6814，父进程1、精确脚本与工作目录均为本项目、日志为旧output/bot.log，且不是launchd当前实例。逐项核对身份、无子进程及无活动准入后只向该旧进程发送SIGTERM；8秒观察未退出的失败记录保留。旧SDK随后10:30:02优雅退出，无SIGKILL；同一受控PID持续运行，10:30:03至10:32:19观察窗口无新错误。证据 `bot-orphan-graceful-retirement.json`、`bot-post-retirement-health.json`。不能把启动后曾有的Conflict说成全程为零。

防止复发的修复在所有Bot入口共用main中取得同一个真实内核锁，并持有至完整生命周期结束；重复启动在Bot配置及网络初始化前返回，业务层异常继续传播，异常及正常退出均释放锁。真实跨进程争锁、递归重复启动和两类异常释放已验证。候选完整运行源97项及20子测试隔离通过、9项既有弃用告警，边界探针及pytest均0；证据 `video-pytest-swnp7h50`，源清单 `902ad603de49bce4efb1a74b6327e9dcc13879ffebb8664d89bba7d92bcf68d1`。本修复独立提交导出与实际采用另记。

#7071的错误是本轮供应商窗口耗尽，原累计账本仍剩约301秒；已纠正前文错误描述，未重置账本。在原账本与147段完整ASR下，正式完整字幕制作于10:30:32通过，548.827007秒、整片解码退出0、同源及成功回执均有效。成片SHA256 `ae1cae5bcc2b84a146c226f9184d4e3bae67ed2610c0075770face072a1de5f4`，唯一告警为删除失配词注、正文保留；3秒、270秒和540秒画面已实看。原生DAL只凭同源绑定成功回执解除修复链，随后官方重试入口恢复原任务，10:33为PROCESSING，不能据此声称已发表。证据 `production-caption-validation/7071/`、`7071-native-restoration.json`。

#7137也是本轮窗口耗尽，既有累计账本28次请求、约308.16/600秒，尚有约291.84秒；115/189段缓存通过原合同严格核验，未新增请求。保持原账本与完整ASR，等待真实加工锁空闲后续跑。#7146原片为娱乐选题，违反既有受众内容规则；仅使用现有发布前人工复核标记闭锁，状态、评分、来源及字幕失败记录不变，字幕技术问题仍未解决。证据 `7137-cache-only-validation.json`、`7146-policy-review-hold.json`。

10:36一致备份：初始24小时20条中，7条FAILED、10条UNCERTAIN、1条AI_COVER_PENDING、1条TRANSCRIBING、1条PROCESSING；系统类未解6条、策略3条、投递待核实10条。初始48小时31条中系统类12条、策略6条、投递待核实12条。#7146的分类转移不是技术修复，既有UNCERTAIN禁止重投保持。证据 `live-audits/20261101T023617Z/audit.json`；尚未清零。


## 10:51 BJ：单实例修复实际上线与自然退出核验

提交 `b797d685d83caba3d2d5dd85a22c32bc738d6940` 已推送；原生部署 `f8580ca158a648cd987e14f6c6aeffbb`（外置 `deployment-r23/`）9步COMPLETE、verify.ok=true、维护恢复RUNNING。5类驻留角色核对源码摘要 `28473457c0b85db48f0713d0a46447919c90182368795ba11406392e23946a9e`，证据 `runtime-adopted-r16.json`。独立提交源97项及20子测试通过、9项既有弃用告警，边界探针及pytest均0；证据 `video-pytest-8j9d7r3r`，清单 `62a624bceea1f15468b0d9284f5b7ee5e351d6b7f37b427459989f8bf7feaa26`。新Bot PID42764已就绪，真实单实例锁由同一PID持有；启动后的首轮有界日志观察中NetworkError、ConnectError、Conflict、Traceback均0，后续连续样本保留在 `bot-runtime-r16-samples.json`。

#7072原生翻译审计2031成功，正文、互动提示及词汇片尾于10:41全部正常完成，进入AI_COVER_PENDING；恢复项33按实际封面等待原因结束，无RUNNING遗留。#7071正式完整验证后经既有API恢复，正文和片尾于10:44正常完成，亦进入AI_COVER_PENDING，任务 `98MJXtcgEjc-093ac9933665`。两者均未据封面等待宣称发布成功。#7137在10:49维护恢复后取得真实加工锁，沿用同一持久账本及189段完整ASR继续正式字幕验证；结果另记。

部署原本因在途任务未排空而在freeze阶段关闭闸门后停止。任务结束后，原接续工具仍要求计划中的发布恢复worker继续持角色锁，错误地拒绝正常退出的PID33225。修复保留UI及所有仍在运行角色的精确身份，只允许计划内缺失角色同时满足内核锁空闲和原PID确已不存在；活PID、PID复用、未知进程查询、未计划角色、源码/调度/审批漂移及活动准入继续拒绝。原计划、闸门版本253、源码及部署日志均未手改；已测试的独立工具副本只完成真实冻结并交回原生recover，原生引擎实际完成其余8步。原始SCHEDULE_DAEMON_NOT_DRAINED和OWNER_DRIFT失败记录保留，真实退出身份及工具摘要见 `deployment-r23/partial-freeze-recovery.json`。

完整候选源143项隔离回归通过，覆盖真实子进程持锁、正常退出、释放锁但仍存活、未知新增角色，以及既有版本、身份、审批、源码、调度、账本、维护和Bot单例保护。边界探针及pytest均0、无告警，证据 `video-pytest-kv23opl2`，源清单 `768555ab43456cc1a73a62508146db58470a7b2b7cc1fe31ebeeeb0ade64665f`。首次命令误写不存在的测试文件退出4，不计为通过。本次工具修复的独立提交源及原生采用另记。

10:49一致备份：初始24小时20条当前7条FAILED、10条UNCERTAIN、3条AI_COVER_PENDING；系统类6条、策略3条、投递待核实10条。初始48小时31条当前16条FAILED、12条UNCERTAIN、3条AI_COVER_PENDING；系统类12条、策略6条、待核实12条。历史异常不删除，窗口老化不算修复，#7059完整译文仍缺失且原累计预算已耗尽；未清零。证据 `live-audits/20261101T024917Z/audit.json`。


## 11:00 BJ：冻结核验修复实际上线与字幕批次断点

提交 `3a1acf4a8eb949b3d0a3df7f1d5840853c7efdd3` 已推送；原生部署 `37f4653e1a6e4b51be7c4a3a30a07e7f`（外置 `deployment-r24/`）9步COMPLETE、verify.ok=true、维护恢复RUNNING。5类角色回读同一实际源码摘要 `d1b4189b15b70b25caab8e4ad5f3ae5c29f16f768c283650cc273be2f73ec43b`，证据 `runtime-adopted-r17.json`。完整候选143项、独立提交源142项隔离通过，后者 `video-pytest-kkmgiymt` / `f1e29c017c5ab5f455806317c8e9eb29f54e2bd8263320d25e7b08d1b656c7f1`，边界探针/pytest均0且无告警；数量差来自既有工作区测试，未纳入无关修改。

#7070原生AI封面兜底已产出并经原流程继续，10:52为UNCERTAIN，表示已执行发表但未取得公开回读，不重投。#7134由原批次正常领取。#7137正式完整字幕验证于10:57实际失败：缓存由115段增加至185/189段，但最后4段请求超时；同一原账本42次请求、600.035/600秒、active_window为空。证据 `production-caption-validation/7137/result.json`、`7137-budget-after-continuation.json`。没有重置预算、缩短ASR或声称字幕完整，后续完整恢复仍需真实成功凭据。

重复超时的另一根因已复现：Gemini前批成功、后批超时后，已完成结果仅在内存，重试又从第1批请求。新断点只保存完整且结构有效的批次，绑定全文、全部上下文、已给中文、词汇上下限、原文权威标记、提示原文、实现摘要及允许模型；读取重新解析并验证内容摘要、模型、段数、非空和错误页。部分译文、坏JSON、未知模型、变更全文或上下文均不复用。逐批原子写入，缓存失败不丢供应商现有结果；完整候选仍按原全片质量门、ASR绑定、供应商时限和发布门禁处理，无新配置、总时限或预算扩张。

新缓存实现纳入翻译完成合同，旧完整译文需由原规则决定是否重做；ASR合同和Codex累计账本身份算法完全未改，已有600秒耗尽事实继续生效。没有将部分批次包装成完整翻译完成凭据。

旧实现独立复现为同一52段输入执行5次请求，新实现为4次且后续完整复读不构造SDK客户端；旧版证据 `video-pytest-17vvp_cs`。候选88项隔离回归通过，覆盖新解释器磁盘复读、中断续跑、全文/上下文/实现变化、坏缓存、空行和错误页拒绝、失效期限及原有完整翻译快照、质量、少量瑕疵、供应商份额和持久预算规则；证据 `video-pytest-ft2hww11`，清单 `2680f6007484b4be0d9f917602ddd6606dbeaad0caf7ce96190a7fc4088ceb71`，边界探针/pytest均0、无告警。首次测试夹具误把包导出的settings对象当模块，3项设置失败；改为明确导入设置模块后通过，不修改生产规则。独立提交源和本次原生采用另记。

10:58一致备份固定24小时20条中系统未解5条、策略3条、提交待核实11条；固定48小时31条中系统11条、策略6条、待核实13条。尚未清零，见 `live-audits/20261101T025830Z/audit.json`。


## 11:11 BJ：批次断点实际上线与无效兜底预留

提交 `6e88d5ea723bdd6b31ffa81e08b31ae57c8ab071` 已推送；原生部署 `13c836c3578440ada0219bb76bdc9ce3`（外置 `deployment-r26/`）9步COMPLETE、verify.ok=true、维护恢复RUNNING。5类角色回读实际源码摘要 `8f16ab9711759ca9a69af644cc14811a6737e4377120f7e79dd272fcd079b4ca`，证据 `runtime-adopted-r18.json`。完整候选及独立提交导出各88项隔离通过，后者 `video-pytest-aoppbtyl` / `547e6232f079cbbdcfa5c59533b311191eefc6b71d4082dcd38d1d9e33973dcd`，边界探针/pytest均0且无告警。部署前定时任务活动拒绝及随后真实在途未排空失败记录保留，没有改写原计划或强停任务；#7134完整字幕及后续成片自然完成后进入AI_COVER_PENDING，队列已领取#7000。

两条长视频的原累计Codex预算均已耗尽，旧供应商时间分配仍为Codex预留300秒。4供应商计划中，Gemini因而只有60秒窗口；前序供应商失败、Codex不能再请求时，会留下未用时间而整轮失败。真实来源只读核验 `r19-real-source-capacity-preview.json`：#7059完整463段、#7137完整189段均匹配各自原账本，可执行余额0，读取前后原文件内容与mtime相同，未调用供应商或改写状态。用同一600秒总期限和120秒质量预留比较，Gemini可用窗口应为160秒而非60秒。

修复让真实执行和只读查询共用既有批量上限及请求数计算，账本身份配方不变；只读查询按原已用时间、实际请求数、历史较低上限和未清崩溃窗口计算可执行容量。旧账本不存在时只报告原配置容量、不创建账本；坏状态或真实锁忙时报告零执行容量，不重置或授予请求。前序时间预留不超过实际余额及原配置300秒；总期限、质量预留、供应商顺序、原缓存入口、真实预扣和完整质量门保持。耗尽后仍可读取完整且校验通过的原缓存，不把部分字幕当完整候选。

旧版本真实持久账本复现2项失败，证据 `video-pytest-5re8mchq`。候选完整源158项隔离通过，覆盖真实另一进程持预算锁、读取不改mtime或内容、配置上限不能扩大旧预算、崩溃窗口保守扣除、坏状态不重置、请求数耗尽、来源身份一致、关闭开关不读取账本、原完整缓存可复读和全部字幕质量/完整性规则；证据 `video-pytest-7o_2_8ex`，清单 `b125b45da5ec47e4c88be795828d4ae4c7a838254cc486fcb7695561a146ab86`，边界探针/pytest均0、无告警。独立提交及实际采用另记。

11:08一致备份固定24小时20条中系统未解5条、策略3条、提交待核实11条；固定48小时31条中系统11条、策略6条、待核实13条。已发表待人工核实的原防重保持，历史异常不删除，未清零。证据 `live-audits/20261101T030806Z/audit.json`。
