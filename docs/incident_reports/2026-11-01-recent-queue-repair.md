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
