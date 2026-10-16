# YouTube 关键词长期运行 v0.5 验收与采用记录

编写：Codex，2026-10-15。范围已获用户确认；以下分别记录代码验收、生产采用和真实运行，未发生的步骤不得标为完成。

## 范围与当前结论

本期按已确认规格落实：肺鼠疫规则从实际恢复起续期7天、每4小时搜索和热度刷新、关键词来源合计北京时间每日最多2条／滚动168小时6条／同时最多2条未结束根任务、硬时长180–1800秒。保留至少75分、原热度与内容门禁；API仍为每日20搜索／40详情，AI规则保持暂停，同时最多1条定时规则。

当前完成隔离实现、生产并行快照整合和失败项补测。首轮整合1112项通过／5项失败；5项均为片尾测试依赖生产运营开关，改用独立测试策略后，受影响的146项全部通过，未删断言或调整生产片尾配置。2026-10-16 05:21和05:29北京时间分别完成源码及LONG_TERM配置的两轮原生九步采用、重启与回读，采用目标1395577，全部并行修改保留。05:30:37已续期并开放v0.5；09:30第二轮自然搜索及09:31独立REFRESH成功，同6条候选相隔14427秒自然刷新，三作业共54条原始评分快照复算一致。13:31第三轮搜索／刷新成功，另35条评分复算一致。14:31并行提交65a3853引入新的运行来源漂移；15:24已通过全新原生九步完成正常换代，15:25恢复搜索和准入。17:31及次日04:15均自然完成采集和刷新；夜间到期任务遵守宿主保护窗口，至安全时段自动执行。**长期配置、按四小时计划且受保护窗口约束的自然采集和热度刷新已实际生效；新长期额度下的真实新准入仍待自然达标候选。**

规格：[youtube-keyword-long-term-v0.5.md](../specs/youtube-keyword-long-term-v0.5.md)。生产源码基线70a1eb4；隔离分支codex/topic-candidate-workbench已合入该基线，没有覆盖生产工作区。

## 5947 的失败原因

- 主任务5947，YouTube `X79tE-S-Aow`，KEYWORD根任务、292秒。真实准入发生于2026-10-15 09:37:08北京时间；随后FAILED。
- 原生审计incident182：2026-10-15 09:58:30北京时间，在`source_subtitle_preflight`阶段命中`blocklist.P0.en.china_sensitive_negative_news`，结果`REJECT_FAILED_BLACKLIST`，规则包`2a618ce6dfa4986c`，输入摘要`08eb606f66284581`。
- pipeline.log 3873191–3873201对应任务认领、获取锁、源VTT预检、P0拒绝、标记失败并加入黑名单、阻断视频下载、释放锁。该证据定位为既有内容门禁拦截，未发现关键词搜索或队列插入失败。
- 不重试、不豁免内容门禁；5947原始准入消耗保留。在其准入时间落入日／滚动窗口时计入额度，失败后释放在途容量。

旧v0.4验收末段将`automatic_used`称作累计准入不准确：该字段来自自动搜索预算，长期准入指标独立读取`keyword_admissions`持久账本。

## 实现及隔离证据

| 项目 | 验收点 | 状态 |
| --- | --- | --- |
| 持久准入事务 | 并发新增不超日2／168小时6／在途2；失败、删除、重启不退款；切片按根计容量 | 核心回归通过 |
| 历史迁移 | 原始准入时间不改，补齐持久YouTube身份；账本无法核实只关闭新增准入 | 核心回归通过 |
| 续期 | 过期必须明确“续期并恢复”；暂停续期不自动启用；CAS及忙碌拒绝；旧版本命中不能直接准入 | API和浏览器回归通过 |
| 工作台 | 北京日界／滚动168小时／在途独立显示，最早释放时间、24小时到期提示、冲突保留输入、键盘操作 | 三主题浏览器回归通过 |
| 受控迁移 | 新LONG_TERM schema2精确合同；旧schema1回执兼容；真实作业／自然4小时刷新链和持久账本绑定；漂移拒绝 | 原生适配器回归通过 |

- 核心/API/浏览器：`video-pytest-nqex7nhy`，178 passed／10 warnings，runner exit0，沙箱已回收。清单`71c3b32d0c29379dc09cea0af946b881156a89a528f2a6cab6ab307754d25303`。
- 加入硬时长和实际阶段文件加载／重启回读后：`video-pytest-p5zjw5b0`，17 passed，runner exit0，沙箱已回收。清单`0a99970bd6f26f966eaf3f3a3e8977470c1526bf642cb861518cf27be859288b`。
- 整合快照：`/Volumes/EXT2T/AppDataOffload/ryusei/keyword-v05-integration-20261015`，保留生产1491份维护文件及全部并行dirty/untracked，再叠加本期实现。`video-pytest-cnynxo0q`：1112 passed／5 failed／10 warnings，runner exit1，清单`8461650fd851ff24f80c6c2b54befb0ab5656b96e80af1f5443c9460623c4619`。
- 失败定位：生产并行`config/vocabulary_outro.json`将wallstreet／ai_news／other片尾关闭，而5项测试读取该运营配置并假定开启。将测试策略迁至独立JSON夹具，流水线连接测试显式指定临时策略；所有原断言保留，生产配置和应用行为不改。补测`video-pytest-iujjbp3u`：146 passed／10 warnings，runner exit0；包括全部5项失败、片尾API/浏览器、关键词额度/API/浏览器和原生LONG_TERM迁移。最终运行源码清单`3fbebf87c8fd390527edbc892314e09bea450a230b3b9172c8e11a420e346096`。两次覆盖合并仍有1117个用例、未解决失败0，不表述为一次1117项全绿。两次沙箱已回收。
- 三主题窄屏截图已人工回看，无横向溢出，独立日/周/在途额度和明确续期入口可见：[浅色](evidence/youtube-keyword-v0.5/long-term-light.png)、[深色](evidence/youtube-keyword-v0.5/long-term-dark.png)、[高对比](evidence/youtube-keyword-v0.5/long-term-contrast.png)。[收据与覆盖汇总](evidence/youtube-keyword-v0.5/coverage.json)保留两轮结果，未将测试等同真实采集。

## 生产采用顺序

1. 安全窗口重新核实生产HEAD、完整来源/birth/锁/保护/调度及并行文件指纹。没有变化不重复同一测试；有变化先合入并针对影响补验，不覆盖其他开发。非秘密Cloud配额证据刷新至1小时内，确认已知本地调用者；不读取或索取密钥。
2. 通过正常控制面关闭新增准入及搜索。用新原生`--preserve-keyword-profile`计划采用已测源码：先暂停接纳、自然排空，再正常停止、一致性备份、采用、维护启动、恢复调度和最终回读。旧CLI不识别LONG_TERM，故源码采用与下一步阶段迁移需分别执行，不加载未采用实现绕过原生检查。
3. 已采用新实现后，以当前ADMISSION回执的真实TRIAL/SCHEDULED/REFRESH证据链、新鲜配额和真实准入账本，编制全新`--keyword-stage LONG_TERM`计划。保持来源、锁、排空、保护、漂移、恢复九步门禁。计划30分钟内有效，超时重编，不改时间或复用完成journal。
4. 通过正常控制面核对肺鼠疫最短180秒、回看1天、定时开启；显式续期并恢复7天。AI保持暂停。正常恢复DISCOVERY_ONLY与准入开关；回读实际LONG_TERM、20/40、日2／168小时6／在途2和原始账本。截止时间以这次实际续期时刻为准。
5. 观察自然SCHEDULED及自然REFRESH，复核实际预算、评分、规则版本、下一次4小时计划和持久准入账本；不手工tick、改时间、造候选或降低门槛。有自然达标候选时逐条验证账本和新增KEYWORD主任务关联，额度以同一事务生效。

没有自然达标候选时，明确区分“长期配置和自然采集已生效”与“长期新准入待真实验证”；不把测试、配置或任务入队视为制作／平台公开完成。外部发布边界不扩大。

## 恢复和回退

故障先关闭新增准入；搜索故障仍遵循现有退避、预算和维护闭锁。所有主任务、历史消费和并行修改保留，不批量重试。需要回退阶段时使用新的原生LONG_TERM→ADMISSION或OFF计划，不编辑旧回执、不清空账本；ADMISSION的首轮累计上限1会阻止已消费后的新增准入。代码回退走新前向提交和维护采用，不从运行进程脚下替换源码。

## 生产与真实验收

- 隔离实现提交`53bb71fb357c1785203593098d812be3bc401418`已推送。23:08核对生产1491份维护文件，与整合基线无差异；23:09实际六类worker真实birth/hash均匹配生产磁盘`620463e8dfa75201665d1ca155f4932a6d12b9f8652b03c0d86ee0011ec90776`。页面RUNNING/IDLE，DISCOVERY_ONLY49、admission1/version10、MARKET_GUARD；此观察不代替执行时完整来源、锁与调度门禁。生产未写入v0.5代码/配置，仍保留27项并行dirty和维护untracked。
- 23:09按带时区现场时间重新计算，下一安全分钟仍为2026-10-16 04:15北京时间。已创建本会话原生跟进`youtube-v0-5`，04:15起在白天窗口继续已授权维护采用和真实验收；状态不变保持安静，完成后暂停，不要求用户重复批准。配额与新阶段计划均在实际执行时刷新，未预先冻结生产。
- 2026-10-16 05:14现场重算已在安全窗口；1491份生产维护基线未漂移，六类角色真实birth/hash匹配。05:15 Cloud只读配额搜索0/100、通用222/10000。正常CSRF/CAS控制面关闭准入至0/version11、搜索OFF/version50。
- 源码采用：计划`f5136dfea2b04579a131ff5f3545d7f3`，私有回执`~/Library/Application Support/VideoProcessing/deployments/keyword-v05-source-20261016-a`。首次freeze因在途返回`MAINTENANCE_NOT_IDLE`，原生status确认后维持暂停接纳；微信登录自然退出，视频5971自然到`AI_COVER_PENDING`，active清空。原生recover完成baseline/freeze/stop/backup/adopt/start/resume/restore/verify九步，05:21:35 COMPLETE。目标1395577、实际源码hash`27bedd3e9f6cafe93f2c31cd8078ed947d191de5878416ae839539053ec87b8c`，原ADMISSION配置完整保留；没有强杀、删锁、改旧journal或跳检查。
- LONG_TERM阶段采用：新计划`ea3db437d8a4411a95521da65f0ba2b0`，私有回执`~/Library/Application Support/VideoProcessing/deployments/keyword-v05-long-term-20261016-a`。原始TRIAL/SCHEDULED/同候选四小时REFRESH证据链和持久账本原生校验通过。05:21:53 freeze因两轮之间接纳的5981/5968在途暂停，MAINTENANCE61；5968自然到LOGIN_REQUIRED、5981自然到AI_COVER_PENDING，未重试或强停。status确认排空后原生recover完成九步，05:29:37 COMPLETE。两个journal均保留最初freeze被拒的历史，最终error为空，不编辑或重放完成journal。
- 7天续期和唯一规则恢复：05:30:37通过正常CSRF/CAS控制面先保存最短180秒、有效7天，再显式“续期并恢复”；肺鼠疫ACTIVE/version7、定时开启，到期北京时间2026-10-23 05:30:37。AI规则仍PAUSED/version3。DISCOVERY_ONLY/version53，admission1/version12；实际加载LONG_TERM已原生验证，API每日20搜索／40详情，自动搜索18次、保留手动2次。
- 自然搜索：作业`b1a502837dc04267b00fee6c0ae55f1b`，05:30:38–40，SCHEDULED/COMPLETE/OK，绑定肺鼠疫version7及control53，新增20、重复5、受限22；实际搜索1／详情1。25条数据库原始评分快照均按`heat-v1-channel-policy-v1`重算一致。下一搜索计划北京时间09:30:38；首批观察的自然刷新不早于09:30:40，未手工tick或改时间。
- 当前准入：05:34账本核实日0/2、滚动168小时1/6、在途0/2；旧5947仍保留原始准入时间和消耗。首轮唯一达到75分的候选`I-wLIXC21wI`得90分，但2669秒超过1800秒，RESTRICTED且task_id为空；未降低门槛或创建替代任务。新长期政策下真实新增准入及其主任务关联仍待自然达标候选。
- 最终生产配置、来源和恢复回读：05:34六类存活角色真实birth/hash全部匹配`27bedd3e9f6cafe93f2c31cd8078ed947d191de5878416ae839539053ec87b8c`；原生Sources.final验证生产main、全部运行源码及并行dirty/untracked保留，Schedules.restored验证cron/launchd恢复。实际API configuration与已加载配置一致，完整LONG_TERM回执验证通过；RUNNING，不把工作期间DRAINING称作IDLE。生产1395577已推送origin/main。
- [生产非秘密证据](evidence/youtube-keyword-v0.5/production-20261016.json)包含两轮journal摘要及原件哈希、真实作业/预算/评分快照、额度账本和来源验证；[实际生产页面](evidence/youtube-keyword-v0.5/production-long-term.jpg)已回看。后续只跟进自然刷新和新真实准入，源码未漂移不重复开发、回归或部署，7天到期不自动续期。
- 06:14只在active及unknown均为空时，将三份验收文档／JSON／截图快进至生产main `f80948f`并推送；运行源码、全部并行dirty/untracked前后相同。此后Git文档更新不等同运行来源漂移，已采用源码hash仍为`27bedd3e9f6cafe93f2c31cd8078ed947d191de5878416ae839539053ec87b8c`。
- 10:18–10:20真实周期复核：09:30:49–51自然SCHEDULED `ba71922539084b8093f5e4200c39f83c` COMPLETE/OK，新增4、重复19、受限20，搜索1／详情1；09:31:06–07自然REFRESH `473768a6b25c4cb3895c2e2d4323e88f` COMPLETE/OK，6条原始候选刷新，详情1。6条均与05:30首次作业的同一候选对应，实际刷新间隔14427.326345秒；未手工tick或改时钟。三作业共25+23+6条评分快照按统一公式复算全部一致，项目预算绑定正确。当前累计搜索2／详情3，下一自然搜索北京时间13:30:49。
- 10:20现场六角色真实birth/hash及完整LONG_TERM加载核验通过，RUNNING62/IDLE、unknown为空，DISCOVERY_ONLY53、admission1/version12；日0/2、滚动1/6、在途0/2，持久账本仍仅历史5947。当前版本高分候选`I-wLIXC21wI`刷新后仍90分、2669秒，因180–1800秒硬门槛RESTRICTED且task_id为空；其他历史高分候选存在时长、P0、频道策略或已入黑名单限制。**没有可据以验收的新长期真实准入，不能宣布本期完整验收完成。** 保持自然采集和现有门槛，到期不自动延期；只在出现新达标候选、故障或需要操作时通知。[本轮原始作业、评分、六条自然间隔及未准入证据](evidence/youtube-keyword-v0.5/natural-cycle-20261016.json)。
- 15:17复核第三个自然周期：13:31:02–04 SCHEDULED `aa2c62e5a8014b878ffa4cac121899df` COMPLETE/OK，新增6、重复19、受限22，搜索1／详情1；13:31:19–20 REFRESH `5248267a620843959fe25cdb03fe4056` COMPLETE/OK，实际10条刷新、详情1。两作业25+10条原始评分快照复算一致。当前观察35条中32条RESTRICTED、3条OBSERVING、无QUALIFIED；唯一90分候选仍2669秒且task_id为空。原额度账本没有新增。
- 本次实际故障及恢复：14:31生产并行提交`65a3853`已完成词汇超时重试修补，74项隔离测试通过，但六类存活角色仍持有旧源码hash，关键词调度明确返回`RUNTIME_UNVERIFIED`，不能把它归为等待候选。仅运行文件`pipeline_manager.py`发生变化，已完成会话和实际测试清单独立核实；本轮另补关键词／LONG_TERM／维护／部署82项，全部通过，两个沙箱已回收，两份运行源码清单均为`28122e64f98c5f160c81ff27e25441db18bb23798a7da72c3540c27ac7b9731d`。未重复1117项历史整合回归，也未新改实现。
- 15:21刷新非秘密Cloud配额（搜索0/100、通用1/10000；PT日界已切换），现场带时区窗口允许。正常控制面关闭搜索及准入后，新计划`855157080503440a839f6daf0f0c0a90`采用当前main `65a3853`、`--preserve-keyword-profile`；`--retire-from-deployment`只引用已完成LONG_TERM部署的原件和精确worker身份作为旧进程正常退役证明，没有重放旧journal或伪造指纹。两次`MAINTENANCE_NOT_IDLE`拒绝均先status再核实，保留暂停接纳状态；原生recover后九步于15:24:43 COMPLETE，正常停止、备份、启动和调度恢复全部通过。目录`~/Library/Application Support/VideoProcessing/deployments/keyword-v05-source-recovery-20261016-b`。
- 15:25独立最终回读：源码hash`aee901f6babfcb9982a2c3ea652d00d17fa699cd09b9bed14e79affc3fbd51ed`，新UI PID79150，七类存活角色真实birth/hash/cwd均匹配；完整LONG_TERM、cron/launchd恢复、392份运行源码和26项dirty／1246条untracked路径前后完全一致。先在OFF状态完成原生最终核验，再通过正常CSRF/CAS控制面恢复DISCOVERY_ONLY/version56、admission1/version14；15:26调度自然回读`REFRESH_OR_ADMISSION`，RUNNING64/IDLE、active及unknown为空。规则version7和北京时间10月23日05:30:37到期时间、日2／168h6／在途2均保留；当前日0、滚动1、在途0。下一自然搜索北京时间17:31:02，以现场计划为准，不手工tick。**来源故障已恢复；新长期真实准入仍为0，本期完整验收尚未完成。** [第三轮作业、评分、最新来源恢复及额度原件摘要](evidence/youtube-keyword-v0.5/source-recovery-20261016.json)。
- 18:16复核第四个自然周期：17:31:11–13 SCHEDULED `b7f27cbcc559484f9e5554deb5d31898` COMPLETE/OK，新增1、重复23、受限21，搜索1／详情1；17:31:29–30 REFRESH `153611f8a50b40aeac10f18cf61524f2` COMPLETE/OK，保存12条原始刷新快照、详情1。12条与前轮同候选的间隔均不少于14409.921145秒。24+12条快照中35条评分复算一致，另1条上游播放／点赞统计缺失，按既有缺失值规则保留空分而非补造0分，未据此准入。当前36条观察中33条RESTRICTED、3条OBSERVING，唯一90分视频仍2669秒、task_id为空；日0/2、滚动1/6、在途0/2，持久账本仍仅5947。七类当时存活角色真实birth/hash/cwd及完整LONG_TERM均通过；RUNNING64，检查期间原任务自然运行后回到IDLE，未修改配置或重做部署。生产main `623d599`仅追加首页template／测试修复，Python运行hash仍`aee901f6…`。下一自然搜索计划北京时间21:31:11；实际执行受原调度门禁约束。**自然运行持续生效，仍缺新长期真实准入证据。** [本轮作业、预算、评分与自然间隔原件](evidence/youtube-keyword-v0.5/natural-cycle-20261016-evening.json)。
- 2026-10-17 05:20复核夜间恢复：原计划21:31到期，宿主保护持续至北京时间04:15；按实际配置计算04:14:59仍保护、04:15:00允许。04:15:10–12自然SCHEDULED `9abba9bfe0a04ba5a8497d9cf45e296e` COMPLETE/OK，新增24、重复1、受限20，搜索1／详情1；04:15:27–28自然REFRESH `fc62e320ea4d4c1b81e3b955c1ab1895` COMPLETE/OK，实际35条刷新、详情1。两作业60条原始快照中59条数值评分复算一致，另1条统计缺失保持空分；与17:31前轮可对应的12条同候选间隔均为38638.245854秒，符合至少四小时，未手工补跑或改时间。六类存活角色真实birth/hash/cwd及完整LONG_TERM均通过，源码仍`aee901f6…`，生产main `f9958c0`的并行技能／测试提交不构成Python运行漂移。DISCOVERY_ONLY56、准入1/version14保留，PT日预算搜索2／详情4；规则下一自然搜索北京时间08:15:10。当前60条观察中52条RESTRICTED、8条OBSERVING、无QUALIFIED；唯一90分仍2669秒、task_id为空。北京日0/2、滚动1/6、在途0/2，账本仍仅旧5947，**长期新准入仍为0，未宣布完整验收**。原视频及queue-dispatch仍在途，未冻结、停止、重测或部署；本轮验收文档先在隔离分支保存，生产文档合入等待空闲。[夜间自然作业、原始评分、窗口边界及额度证据](evidence/youtube-keyword-v0.5/natural-cycle-20261017-dawn.json)。
