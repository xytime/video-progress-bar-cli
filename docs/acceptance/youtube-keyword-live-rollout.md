# YouTube 关键词采集：生产实际生效执行记录

记录：Codex，2026-10-14。状态：执行中；凭据本机比对及无外部共享声明已取得，阶段协议整合验收中；尚未真实搜索或开放。以下按时间记录，最新进展见末尾。

## 最新授权

用户已确认持续推进到生产实际采集和端到端验收，包括必要修复、隔离验收、受控部署、最多 3 次真实搜索试运行、门禁通过后的手动搜索/定时采集/热度刷新，以及最多 1 条新候选的初始受控准入。延续现有发布审核与保护；不额外授权对外发布。授权不代替凭据与共享配额事实。

本记录承接已完成的 [OFF 上线](youtube-keyword-v0.4-off-production.md)；历史规格中“等待生产授权”描述已经被本次用户确认覆盖，事实门禁仍须通过。

## 2026-10-13 21:36 起现场核查

- Cloud 当前项目：anti-gravity / `gen-lang-client-0993011647`。YouTube Data API v3 已启用。
- 配额页实时显示：Search Queries per day 0/100，Queries per day 104/10,000；这是所选项目用量，不是生产密钥绑定证明。
- 与 YouTube API 兼容的凭据列表显示 `video-precessing-youtube-catalog`，资源 ID `286cb0f6-4231-4ca2-831f-1e4646829b55`，创建于 2026-07-28，限制为 YouTube Data API v3。没有点击显示密钥、读取密钥或修改凭据。
- 本机维护源码存在四条官方 API 调用路径：频道监控 `scripts/monitor_channels.py`、评分刷新 `scripts/rescore_refresh.py`、英语世界研究 `src/video_processing/english_world/research.py`、关键词 `src/video_processing/utils/topic_search.py`；均使用 settings 中同一配置字段。该代码证据不能排除其他主机/其他凭据使用同项目配额。
- 当前配置契约没有将生产 key 绑定到具体 Cloud 凭据资源的非秘密元数据。本机代码、历史文档及控制台名称不能完成该证明。已集中向配置负责人请求生产归属依据与外部共享调用清单，不索要密钥。
- 生产关键词 API 新会话回查：RUNNING/IDLE、OFF/version 12，定时和准入均 false、持久准入 0、jobs 空、search/general 0。直接无会话请求收到 403，按正常页面建立会话后可读，没有绕过本机边界。
- 生产主干核对为 `eac9f95`（后续相对测试入口归属修复已合入）。本轮保护原七项未提交修改，不修改生产源码和开关。

证据：[配额页](evidence/youtube-keyword-live-rollout/cloud-quota.txt)、[凭据元数据](evidence/youtube-keyword-live-rollout/credential-metadata.txt)。这些是非秘密页面信息。

## 已识别并修复的初始准入边界

原调度器开启准入后会遍历全部达标候选，缺少首轮最多 1 条的硬限制。隔离补充 `TOPIC_ADMISSION_TOTAL_LIMIT=1`：新增主任务前，在同一个 SQLite 写事务内计算历史 `ADMITTED` 数量，满额返回 `ADMISSION_LIMIT`。0 表示禁止新增；跨日、重启、主任务删除均不自动释放累计额度。既有任务只做来源关联，不消耗新额度。页面提供明确的累计上限提示。

扩大累计限额属于后续明确调整；不因“持续推进”自动提高。实现尚未生产采用，现有 OFF 状态不受影响。

## 后续执行顺序

1. 取得生产凭据资源绑定与全部共享调用者的可核实证据，刷新实际项目配额；核实既有业务观察余量与本模块分配。
2. 对最终生产基线及 dirty 整合副本验收，按原生维护协议部署准入限制；任何新漂移使旧计划失效。
3. 设置实际已证项目、搜索与配额门禁；准入和调度仍关闭。试运行至多累计 3 次搜索、6 详情单位，并发 1、原冷却与保护窗口保留。跨日不增加试运行总次数。失败/归属疑点/预算异常立即停止。
4. 搜索、结果入账、去重、评分与 OFF 恢复通过后开放本机手动搜索，预算 20/40；再启用至多 1 条现有有效规则的定时采集，按自然调度与统计新鲜度完成真实刷新，禁止伪造时间或调低热度阈值。
5. 经真实结果验证后开启累计上限 1 的受控准入，核对来源、幂等、主任务及既有保护。无达标候选时保持等待，不伪造真实准入完成。
6. 主干推送、生产来源/界面/配额及调度回读后形成最终端到端报告；当前记录不能代替该报告。

## 当前需要外部补齐的最小信息

用户最新回复：生产凭据归属“应该是的”；其他主机/程序共享该项目配额“否”。后者记录为用户提供的负责人声明，外部共享调用者信息已补齐，并非技术扫描所得；本机四条既有调用路径仍须计入共享预算。

唯一待补的外部事实是生产 `YOUTUBE_DATA_API_KEY` 与上述 Cloud 凭据资源的一致性及核对依据。“应该是”仍不能作为已验证绑定。请配置负责人在本机私下核对配置与 Cloud 凭据，只返回是否一致及核对方式，不发送密钥。搜索、定时采集和准入继续关闭；开放前仍需刷新现场配额、维护状态及部署基线。本次操作授权已充分，无需再次批准同一上线范围。

## 隔离修复验收

关键词单元、边界、API 和真实浏览器合计 **135 passed / 10 warnings**，不是与之前 32 项专项累加。[回执](evidence/youtube-keyword-live-rollout/receipt.json)、[测试日志](evidence/youtube-keyword-live-rollout/pytest.log)。源码清单 SHA-256 `734bb8da7d265ca4e48910963f2d7b7228c89d655ba737089dc8b5e6d64a92bf`，测试完成时间 2026-10-13T13:41:34Z。沙盒退出后自动清理，外部证据保留。修复已在隔离分支保存，尚未并入或采用到生产；最终整合与部署需要新鲜现场计划。

## 2026-10-13 22:41 独立推进与归属排查

- 按用户要求，不读取或暴露密钥。已检查维护源码、配置契约及现有部署/验收记录，未发现将生产实际配置绑定到 Cloud 凭据资源的非秘密记录。配置契约是项目根配置文件加可覆盖环境变量；没有资源 ID 绑定字段。
- [Google 官方说明](https://docs.cloud.google.com/api-keys/docs/get-info-api-keys)区分元数据 GetKey/ListKeys 与 LookupKey：前者能证明资源在项目中，后者才能由密钥反查项目，但要求传入 keyString。本次没有调用 LookupKey/GetKeyString，也没有查看密钥或用一次业务调用推断绑定。现有元数据证据不能补上生产配置这一端。
- 已向负责人给出私下核对的具体步骤：确认生产实际配置及启动覆盖，核对 Cloud 项目 `gen-lang-client-0993011647` 下资源 `286cb0f6-4231-4ca2-831f-1e4646829b55`，只返回一致性及核对方式，不发送秘密材料。此事实待答复，未改变 quota_verified。
- 隔离分支合入生产 `ba53a61`，候选提交为 `36803a6`，已推送。扩展盘整合副本保留生产原 7 项 dirty，并复制受维护的额外源码；未更改生产文件。原改动与本次差异无重叠，逐项保存哈希。
- 最终整合回归 **401 passed / 13 warnings**，包含关键词/API/真实浏览器、维护/部署、数据库兼容和生词超时；与历史批次不相加。测试完成时间 2026-10-13T14:41:00Z。源码清单 SHA-256 `8ef6d96acae885e8de41bb1456a098ca2e18e68e9f0069440ebab80d618ab531`。[回执](evidence/youtube-keyword-live-rollout/integration-20261013/receipt.json)、[保留摘要](evidence/youtube-keyword-live-rollout/integration-20261013/preparation.json)、[日志](evidence/youtube-keyword-live-rollout/integration-20261013/pytest.log)。沙盒已自动清理。
- 原生部署器生成计划成功，ID `b1c5f885c4ec4f4788f677a2bc4a8f0a`，私有目录 `~/Library/Application Support/VideoProcessing/deployments/youtube-keyword-cap-20261013-c/`；验证最终运行源码与测试清单匹配。仅生成计划，尚未 apply。任何生产漂移均须重新核对，不能直接沿用旧计划。
- 最新维护回查为 RUNNING/version 20，但有 `wallstreet-render` 在途任务和 UNREGISTERED_PROCESS，safe=false。没有冻结、停止、强杀或绕过；搜索/调度/准入仍关闭。需在采用前重新核查任务、未知进程、代码基线与全部门禁。

## 用户本机核对通过后的生产推进

用户提供核对脚本结果：production_file=MATCH、launchd_override=NOT_LISTED、result=CONFIG_MATCH_RESTART_REQUIRED，项目与资源 ID 均与上文相同。此为用户执行的本机核对证据；没有读取或接收密钥，不能描述为进程内存验证。

在途任务结束后重新生成计划 `4bc789652c2b4cf2b0e821dcf61bd05d`（私有目录 `~/Library/Application Support/VideoProcessing/deployments/youtube-keyword-cap-20261013-d/`），目标 `c797b6b`。原生部署器 baseline/freeze/stop/backup/adopt/start/resume/restore/verify 九步全部 COMPLETE，已完成正常重启和生产最终回读；main 已推送到该提交。保留原 dirty 和 untracked，沿用 401 项最终整合源码清单匹配证明。首轮累计准入上限补强已生产采用，仍为 OFF。

Cloud 最新只读回查：搜索 0/100，通用 135/10,000，API 已启用。用户已确认没有外部共享调用者；本机既有调用仍计入观察余量。

### 尚需完成的受控开放路径

现场有效配置显示宿主保护开启、当前受保护；按现有配置计算的下一安全分钟为北京时间 **2026-10-14 04:15**，执行时必须重新计算，不可仅凭此时间表放行。

现有 `deployment_host.protections/web_readback` 与 `maintenance_runtime.inspection` 都明确要求宿主搜索/调度/准入/配额绑定关闭；它们足以证明 OFF 部署，但不能承载已授权的分阶段开启。必须在隔离区补齐明确的配置状态转换与验证，不能直接改线上环境后跳过这些断言。该必要工程工作在用户已批准的实际生效范围内，不再请求同一范围授权。

推荐最小实现与验收：

1. 固定阶段：OFF → TRIAL（3 搜索/6 详情、调度和准入关）→ MANUAL（20/40）→ SCHEDULED（最多 1 条规则）→ ADMISSION（累计最多 1 条）。阶段跳跃、未知配置、凭据/共享配额证据缺失须拒绝。真实试运行次数持久记录，跨日不重置累计三次。
2. 非秘密配置变更独立记录预期前后状态、原配置保留证明和恢复动作；不读取或改写密钥。不得修改旧部署回执来匹配新状态，不得把配置修改当来源验收。
3. 保留原生排空、进程归属、锁、来源、备份、维护中启动与恢复检查。维护中持久搜索模式 OFF、准入关闭、无在途搜索和刷新；宿主能力开启仅能在明确匹配目标阶段的配置回执下启动，其他保护字段不得漂移。
4. 新进程实际非秘密配置回读与计划一致后，才允许恢复调度；持久搜索模式仍须在 RUNNING 且保护窗口允许时单独启用。失败保持关闭并给出可核实恢复位置。
5. 隔离覆盖非法阶段/过期证据/并发/配置漂移/启动失败/重启与跨日试运行累计上限，以及原 OFF 部署回归。全部通过、现场门禁复核后，再真实试运行和阶段开放。

上述路径尚未实现或验收；当前没有发起真实搜索，不能宣称采集实际生效。

## 2026-10-14 01:05 累计试运行预算隔离验收

- 同步最新生产 `95d331e`（生词片尾采用）到隔离分支，合并提交 `52ca574`。生产原七项 dirty 保留，本轮没有改动生产源码、配置或运行状态。
- 增加默认 false 的 `TOPIC_TRIAL_MODE`。试运行每一次官方调用前，在同一 SQLite 写事务中预留累计额度：最多 3 次搜索、6 次详情；失败、重试也占用。统计所有历史项目和日期的预算，不因跨日、重启、更换项目或重新进入试运行释放额度；每日上限同时约束。无删除预算或重新计数的接口。
- 试运行拒绝定时和准入能力同时开启；DAL 拒绝试运行的非手动作业。状态接口回读非秘密累计用量，页面显示累计上限、跨日不重置提示，耗尽时禁用搜索。维护保护快照纳入试运行、项目、配额门禁及限额，原 OFF-only 维护/部署继续拒绝开启状态；没有删除或绕过原断言。
- 最终隔离批次 **323 passed / 10 warnings**，涵盖跨日/重启/项目切换、失败重试、线程与子进程竞争、API、真实 Chromium、维护和部署回归。前一轮 111 项是较窄批次，不累加。测试完成于 2026-10-13T17:05:11Z，源码清单 SHA-256 `86a7fbf1fa8b70a91f0326e78c9f547fa75ab81bae5b6d7b5bb83eb0bc4f7fe2`；[回执](evidence/youtube-keyword-live-rollout/trial-budget-20261014/receipt.json)、[日志](evidence/youtube-keyword-live-rollout/trial-budget-20261014/pytest.log)、[源码清单](evidence/youtube-keyword-live-rollout/trial-budget-20261014/source-manifest.json)。测试沙盒已自动清理。
- 生产实际端口由 settings 回读为 9100；正常建立页面会话后回读 OFF/version 15、RUNNING/IDLE、搜索/定时/准入关闭、关键词 search/general=0。默认文档中的 8765 连接拒绝不代表生产服务停止；没有据此启动第二个服务。维护检查曾观察两个未登记进程，随后按 PID 查询已不存在；没有强杀、删除锁或将该瞬间视为部署安全证明。
- 01:05:27 北京时间现场重新计算：宿主保护开启且当前受保护，下一安全分钟仍为 **04:15**。此时间不是放行凭据，实际执行必须重新核实。

### 下一项仍须完成

累计试运行预算是受控阶段转换的一个组件，**阶段转换本身尚未实现**，本轮修复尚未生产采用。继续补齐非秘密配置前后状态绑定、重启回读及恢复，保留排空/来源/锁/备份/漂移校验；然后整合最新生产 dirty 做最终隔离验收，按原生维护流程采用。仅在安全窗口和全部门禁通过后开始真实试运行。没有真实搜索、刷新、统一评分或新主任务准入证据，目标仍未完成，跟进保持 ACTIVE。

## 2026-10-14 02:10 受控阶段协议隔离验收

- 已实现非秘密阶段配置与原生部署计划、九步事务日志、有效保护字段及重启回读绑定。每次真实调用须验证部署 COMPLETE；单独设置环境开关不能开放。文件/计划/保护漂移、过期证据、跳阶段和未完成部署均拒绝。维护中仍要求持久 OFF、准入关闭、排空和来源证明，未删除原门禁。
- 本轮入口只接受 OFF ↔ TRIAL。后续 MANUAL/SCHEDULED/ADMISSION 的合同已定义，实际作业证据核验和最多一条定时规则的约束仍须补齐，不能将合同定义当作后续阶段已完成。详见 [阶段协议](youtube-keyword-stage-transition.md)。
- 最终隔离 **377 passed / 10 warnings**，包含真实 Chromium、非法配置/证据、实际 Settings 重载、原生维护来源证明、部署恢复及 OFF 往返。源码清单 SHA-256 `c30bcdaec9cf091cca60f337e87b4b0f7403a8e1c063f86c291e1b8644af43ec`；[回执](evidence/youtube-keyword-live-rollout/stage-transition-20261014/receipt.json)、[日志](evidence/youtube-keyword-live-rollout/stage-transition-20261014/pytest.log)。
- 最新生产仍为 `95d331e`，保留七项 dirty。生产渲染任务已结束；维护检查发现的剩余未登记 Python 进程经 PID/命令核对为本次隔离整合测试 runner，须等其结束后重新核查，不排除或绕过该进程检查。
- 下一步：生产并行改动整合验收，原 OFF 原生九步采用协议，再创建全新阶段计划。04:15 仅为此前算出的下一安全分钟，真实试运行前须现场重算并刷新配额。没有真实搜索、刷新或准入证据，跟进继续 ACTIVE。

### 最终生产整合验证

扩展盘整合副本保留生产 `95d331e` 七项 dirty 与额外受维护源码，最终 **456 passed / 13 warnings**，不与 377 项累加。包含数据库、生词及片尾并行改动回归。完成于 2026-10-13T18:14:44Z，源码清单 SHA-256 `5279559455ec70ad65410778c05f7dc3a17b65958979dfd476a9818c357152f4`；[回执](evidence/youtube-keyword-live-rollout/stage-integration-20261014/receipt.json)、[日志](evidence/youtube-keyword-live-rollout/stage-integration-20261014/pytest.log)、[保留清单](evidence/youtube-keyword-live-rollout/stage-integration-20261014/preparation.json)。测试沙盒已清理。测试 runner 退出后，生产 active 为空、未登记进程已消失；来源仍需原生部署冻结后的正式证明，不能把此状态当作门禁已通过。

## 2026-10-14 02:17 协议 OFF 生产采用完成

- 目标提交 `1958e2e` 已通过原生九步并推送 `origin/main`。部署 ID `e840ec6e90bc41ed839ab288db6d6cb8`，私有目录 `~/Library/Application Support/VideoProcessing/deployments/youtube-keyword-stage-20261014-a/`。
- 首次 freeze 被 `MAINTENANCE_NOT_IDLE` 拒绝，源码尚未采用；复查 active 为空、未知进程消失后，通过原生 status/recover 核实冻结已完成，再执行剩余步骤，最终 journal COMPLETE。未手工改写日志、来源证明、锁或调度。
- 正常会话生产回读：RUNNING/IDLE、OFF/version 16；搜索/试运行/定时/准入能力均 false，准入累计上限 1。试运行累计 search=0/3、general=0/6；关键词日用量仍 0。阶段配置 identity=null、error=false，说明协议代码已采用，但尚未采用 TRIAL 配置或搜索。
- 现场 02:17:16 重新计算宿主窗口：当前受保护，下一安全分钟 04:15。真实试运行必须再次现场核实，不能提前调用。原七项 dirty 与额外源码仍保留。
- 继续独立补齐后续阶段的单规则上限与真实作业证据校验；最多三次真实搜索、自然统计刷新与达标准入尚无证据，不能宣布目标完成。

## 2026-10-14 02:21 首轮单规则限制隔离通过

- 已将首轮定时上限从三条收紧为一条；启用与暂停恢复在 SQLite 写事务内检查，并在自动请求预留预算和准入前再次检查。存量多规则异常时整个调度轮停止，不自动选任意一条、不删除规则、不扩大调用。页面说明同步为首轮一条。
- 并发启用、暂停恢复绕行、存量超限、已领取作业配置漂移、跨关键词去重与频道竞争，以及真实浏览器回归 **111 passed / 10 warnings**；[回执](evidence/youtube-keyword-live-rollout/single-rule-20261014/receipt.json)、[日志](evidence/youtube-keyword-live-rollout/single-rule-20261014/pytest.log)。源码清单 SHA-256 `a0c0c1521991f5824b81c397cb14d94792142e1f7ece1515a61fcfa98214e371`。第一批旧测试仍同时开启两条，与最新首轮范围冲突，已调整为顺序切换规则后重验，未删除原去重和竞争断言。
- 此补强目前仅隔离验证，尚未生产采用；生产仍为 `1958e2e` OFF。后续 MANUAL/SCHEDULED/ADMISSION 入口仍关闭，实际数据库试运行/刷新作业证据核验未完成。下一步可先完成证据核验的隔离工程；安全窗口到来后刷新现场配额，使用已采用协议生成新 TRIAL 计划并进行最多累计三次真实调用。首轮单规则补强必须在开放 SCHEDULED 前完成最终生产整合与原生采用。跟进保持 ACTIVE，不把 OFF 部署作为最终完成。

## 2026-10-14 03:06 真实作业证据门禁整合通过

- 补齐 MANUAL/SCHEDULED/ADMISSION 入口：每阶段读取实际数据库成功作业、官方调用预算、采集结果和可重算的统一评分快照，不能用字符串 ID 替代证据；快照与结果事务内写入，不为历史空记录补造。计划绑定证据，freeze/adopt 复核漂移。
- 后续阶段必须继承原试运行作业链；准入还须同一候选在 SCHEDULED 阶段的定时采集与至少四小时后自然刷新。保留全部原生维护、来源、锁、排空、保护字段和恢复校验，没有降低评分阈值。
- 隔离 396 项通过；保留生产七项 dirty 和额外受维护源码的最终整合 **475 passed / 13 warnings**，含真实 Chromium、部署恢复与并行数据库/字幕/生词片尾回归。两批不累加。最终清单 SHA-256 `e2024ac90e301862b8d92836dc915470c2d7eb60a502ddccdb940d6685ace1cd`，完成于 2026-10-13T19:05:41Z；[回执](evidence/youtube-keyword-live-rollout/job-proof-integration-20261014/receipt.json)、[日志](evidence/youtube-keyword-live-rollout/job-proof-integration-20261014/pytest.log)、[保留清单](evidence/youtube-keyword-live-rollout/job-proof-integration-20261014/preparation.json)。
- 当前尚未采用本轮代码；生产仍 1958e2e OFF，维护 active 为空、来源需原生冻结后正式核验。下一步先原生 OFF 采用，再于现场安全窗口刷新配额并创建 TRIAL 计划。测试里的受控适配器和 SQLite 仅证明门禁行为，不代表真实 YouTube 采集完成。

### 03:08 补强 OFF 生产采用完成

- 生产主干 `2fcb1d0becdbc45fe9b1501d0c4e4dc03729858f` 已推送；原生新计划 `5536f6d9014246c6866108dd6d433bbe` 九步全部 COMPLETE，无跳过或手工恢复。私有目录 `~/Library/Application Support/VideoProcessing/deployments/youtube-keyword-proof-20261014-a/`。最终整合 475 项测试对应实际采用源码，七项 dirty 和 untracked 通过来源保留检查。
- 重启后的正常页面会话 HTTP 200 回读：RUNNING/IDLE、OFF/version 17；搜索、试运行、定时、准入及配额门禁均 false，累计准入上限 1；试运行 search=0/3、general=0/6；阶段 identity=null/error=false。单规则和真实作业门禁代码已生效，但没有 TRIAL 配置或真实搜索。
- 03:08:33 现场重算当前仍在宿主保护窗口，下一安全分钟 **04:15**。真实调用前重新核实窗口和 Cloud 非秘密配额；此时获取的配额会在 04:15 前过一小时有效期，因此不将旧配额包装成可放行证据。新阶段必须生成全新计划，不能复用本次 OFF 计划。
- 后续 TRIAL→MANUAL→SCHEDULED→ADMISSION 入口已采用；仍需最多三次累计真实搜索，最多一条定时规则、至少四小时自然热度刷新、统一评分及最多一条真实达标新主任务证据。不能为赶进度降低阈值、伪造作业或扩大发布授权。自动跟进继续 ACTIVE。

## 2026-10-14 03:57 开放前现场复核

- 生产仍 `2fcb1d0`，隔离记录分支 `baf1e57`；原生 `Sources.final()` 对已采用计划再次核对通过：运行源码、目标提交、七项 dirty 和 untracked 均与采用保留清单一致。没有写入生产源码或配置。
- 正常会话回读 RUNNING/IDLE、OFF/version17，试运行累计 search=0/3、general=0/6，作业为空；肺鼠疫规则 ACTIVE、自动采集关闭，AI产业与算力规则 PAUSED。没有为凑验收改变规则或发起请求。
- 03:56:57 现场计算仍受保护，下一安全分钟04:15。维护状态 active 为空，但正式来源冻结门禁仍须由新部署计划执行，不能以空闲代替来源证明。
- 03:57 通过 Cloud 控制台配额页只读刷新：项目 `gen-lang-client-0993011647`、YouTube Data API 已启用；Search Queries per day 为0/100，Queries per day为225/10000（余量分别100和9775）。没有进入凭据值页面、读取密钥或发起 YouTube 业务搜索。此观察一小时后过期；下一次执行应刷新，不能改写观察时间。
- 尚未创建或执行 TRIAL 计划，等待现场安全窗口。后续继续按已授权阶段转换，不需用户重复确认，自动跟进仍 ACTIVE。

## 2026-10-14 04:55 安全时间窗口开放，但排空门禁未通过

- 04:55:31 现场 settings 判断宿主时间窗口已允许；生产仍 `2fcb1d0`，对上次原生计划执行 `Sources.final()` 再核实通过，运行源码、七项 dirty 和 untracked 保留一致。候选分支仅新增验收记录，未改实现。
- 生产当时有 `PpEUTpzWt2M:0`、`bTK1d3TuL5U:0` 及 queue-dispatch 在途；后一次检查前者已转为 review-notification，后者仍 ACTIVE。PID18437 的 Python 子进程和其子 PID18959 FFmpeg 的 cwd 均为生产目录；没有将渲染子进程直接排除。pipeline/pipeline_job 仍有未登记业务锁，正式来源证明也尚未生成，safe=false。
- 正常页面会话回读 OFF/version17、search_open=false，试运行 search=0/3、general=0/6，关键词作业为空。未生成 TRIAL 计划、未执行 freeze/stop/adopt，没有强杀、删除锁或改写维护状态。时间窗口允许不能替代任务排空与来源门禁。
- Cloud 配额只读刷新：YouTube Data API 已启用，指定项目 Search Queries per day为0/100，Queries per day为237/10000；余量100/9763。未访问凭据值或发起真实 YouTube 搜索。待在途自然结束后重新观察配额和门禁，再编制有效期内的新计划。
- 自动跟进继续 ACTIVE；下一步应关注任务排空，不再将04:15视为尚未到来的阻塞时间。无用户操作需求，真实采集目标尚未完成。

## 2026-10-14 06:03 门禁刷新

- 生产源码及并行改动再次与已采用计划核对一致，主干仍2fcb1d0。上轮视频和未知业务锁已退出检查，但当前 `53ATBUQXDAk:0` 的 video/continuation 已登记在途，尚未排空；来源仍须原生冻结证明。
- 06:02:57 实际宿主窗口重新为受保护状态；现场计算下一安全窗口为 **07:00 至20:30**，执行前仍须复核，不能沿用04:55的允许结论。
- 配额控制台只读刷新为搜索0/100、通用240/10000，API已启用；未读取凭据值。生产正常页面会话保持 RUNNING/DRAINING、OFF/version17、试运行0/3和0/6。
- 没有生成或执行TRIAL计划，没有停止在途或绕过门禁；下一轮同时核实07:00后窗口及新任务排空，重新刷新配额后继续。未获得真实搜索或端到端证据，自动跟进保持ACTIVE。

## 2026-10-14 08:14 维护暂停接纳、真实试运行及定时阶段采用

- 此前仅等待空闲而未先冻结接纳，运行中的 cron 和 queue-runner 会继续引入新任务，是迟迟无法排空的原因。本轮按用户指示使用原生部署 freeze：关闭接纳并冻结调度，排空、来源和锁检查通过后才 stop/adopt；未强杀在途任务或绕过断言。
- 08:08 Cloud 非秘密配额实际观察：指定项目搜索0/100、通用269/10000；未查看凭据值。生产 main 已采用并推送 `28c8aee`，沿用实际整合475项通过的清单，保留七项 dirty 及额外文件。
- TRIAL 新计划 `48600e880de7447b84e67038bf496fcf` 九步 COMPLETE，正常会话打开 DISCOVERY_ONLY。08:09:08–08:09:10 首次真实 YouTube 搜索作业 `dc6a28d3354a44b5b4baefc00b9bc815` COMPLETE/OK：新候选25、重复0、受限20，实际搜索1、详情1，结果/统计/统一评分快照落库。重放同一幂等键返回同一作业，预算未增加；随后通过正常控制面恢复 OFF。累计试运行使用1/3和1/6，未用完上限不影响通过。
- MANUAL 首计划在 baseline 被 SOURCE_BASELINE_DRIFT 拒绝，无运行变更；核对仅有并行新增 `experiments/macro_data_atlas_demo/STEP1_STEP2_PROPOSAL.md`，运行源码未变，保留该文件后生成新计划。新计划 `14c5d34ee0c94eeebbda681b8616166f` 冻结后首次 stop 前检查拒绝；使用原生来源回执现场复查为 MAINTENANCE/IDLE、active=[]、unknown=[]、safe=true，再原生 recover，九步 COMPLETE。未手工修改回执或删除锁。
- SCHEDULED 计划 `48ea710824c6411c8743803f521ed5c3` 九步 COMPLETE；实际成功试运行、预算和评分证据门禁通过。正常会话回读搜索20/日、详情40/日，scheduler=true、admission=false、累计准入上限1。08:13:12 打开 DISCOVERY_ONLY/version23，并仅开启既有“肺鼠疫”规则（id36de3a8eca584358851b05e5b9fdbf3f，version2）；另一规则仍暂停。
- 08:13 调度器已自然运行，返回 COOLDOWN：同专题15分钟间隔从真实08:09:08搜索计算，预计08:24:09后才允许第一次定时搜索。没有绕过冷却、手工调用tick或修改时间。此时仍只有上述1个真实搜索作业，不能宣布定时采集或端到端完成。
- 后续读取自然 SCHEDULED 成功作业，至少四小时后读取同一候选自然 REFRESH 和评分证据；再刷新配额、现场窗口与维护门禁，用新 ADMISSION 计划受控开放累计最多1条真实达标主任务。不得降低75分、热度或内容门槛。真实自然等待是验收条件，自动跟进保持 ACTIVE。
- 私有部署目录分别为 `~/Library/Application Support/VideoProcessing/deployments/youtube-keyword-trial-20261014-a`、`youtube-keyword-manual-20261014-b` 和 `youtube-keyword-scheduled-20261014-a`；阶段证据沿用原08:08观察时间，未伪造刷新时间。

## 2026-10-14 08:16 上线后外部源码漂移，重新关闭并维护

- 紧接上轮的自然调度回读出现 `RUNTIME_UNVERIFIED`。对 SCHEDULED 已采用清单逐项比较，生产 HEAD 仍28c8aee，但 `src/video_processing/db/wallstreet_experiment.py` 与 `src/video_processing/processors/insight_mobile.py` 新增署名 Antigravity 的重试退避/字幕分页修改，两个相关测试也在修改。这是上线后的并行磁盘源码变化，不是新任务再次占用窗口；本会话没有回退、覆盖或提交这些工作。
- 已通过正常会话将搜索恢复 OFF/version24；原生 `maintenance_control.py enter` 将接纳闸门置为 MAINTENANCE/version35。active=[]，但六个角色 LEGACY_WORKER，UI PID53443 和子 ready-worker PID53884 被检查列为未登记；已只读核对这两个进程的命令，未停止它们。空闲不等于来源门禁通过。
- 当前持久搜索关闭，宿主仍保留 SCHEDULED 配置，准入关闭；定时规则仍保留，不能继续把08:14的开启状态当作当前可运行。真实累计作业仍只有1次MANUAL成功，没有自然SCHEDULED/REFRESH/ADMISSION证据。
- 已请求用户让正在改生产的 AGY 暂停写入，保留改动且不要自行重启/恢复。需稳定基线后才能安全组织来源恢复，禁止修改角色指纹、旧回执或直接排除进程；不能用已通过测试替代停机来源门禁。跟进继续ACTIVE，等待协调期间保持维护与搜索关闭。

- 08:17 独立快照整合回归完成：**503 passed / 1 failed / 13 warnings**。失败为并行新增 `tests/unit/test_insight_mobile.py::test_short_subpage_and_short_event_do_not_crash_caption_pages`：期望至少3页，实际2页。没有删断言、修改该并行工作或声称新基线通过。四个相关代码/测试文件与测试快照哈希复查一致。证据：[回执](evidence/youtube-keyword-live-rollout/post-rollout-drift-20261014/receipt.json)、[日志](evidence/youtube-keyword-live-rollout/post-rollout-drift-20261014/pytest.log)。关键词、维护和部署原回归通过不抵消该整合失败；需协调该工作后再验收。

## 2026-10-14 08:22 用户确认分页工作已完成后的复验

- 用户确认新增字幕分页已完成上线，不再以“仍在开发/等待暂停”为继续推进的前提。最新复核：两份运行源码未再改变，分页测试已补足实际触发多页的长样例，保持严格三页与时间边界断言。重跑完整整合隔离回归 **504 passed / 13 warnings**，替代08:17失败快照作为最新测试证据；未由本会话修改分页实现或测试。
- [回执](evidence/youtube-keyword-live-rollout/pagination-integrated-20261014/receipt.json)及[日志](evidence/youtube-keyword-live-rollout/pagination-integrated-20261014/pytest.log)，源码清单SHA-256 `cc13fe9ee756dc715ef74cdbac8cc60ee47997e8b109b94bb241416eac92f764`。测试通过不等于当前后台进程采用。
- 运行回读仍为原UI PID53443，08:12:57启动，真实birth匹配登记；登记源码指纹8fc3b33…，当前磁盘6ede58a…，因此维护仍拒绝。保持MAINTENANCE/version35、搜索OFF/version24，不将用户所述分页上线解释为整个关键词后台已完成重启验收。
- 下一步沿用已授权运行来源恢复范围，保留新分页/重试及全部并行改动，准备精确旧运行基线的暂存/还原、原生安全停止和备份、恢复已测最新源码、维护启动和最终回读。不修改检查算法或角色锁，不把旧部署journal改成新采用证明。参考已实施的v0.3.1来源恢复记录；目前未执行任何源码还原或进程停止。定时搜索/自然刷新/准入仍待真实验收。

## 2026-10-14 09:22 来源恢复完成，首个自然定时采集成功

- 现场确认最新运行源码仍与504项通过清单一致；与旧进程登记基线只差两份分页/重试源码。保留完整inventory及两份新文件，精确重建旧源码hash 8fc3b33acd2ab7229ac0b2f48878d60ad211df86aaea09aae272d706b3dd133b 后，原生来源、排空、锁及保护检查通过，正常停止服务、校验数据库备份，再恢复全部新源码并维护启动。没有SIGKILL、删锁、改worker指纹或重放旧完成journal。
- 独立来源恢复目录 `~/Library/Application Support/VideoProcessing/deployments/keyword-source-recovery-20261014-a/`，含prepare/freeze/restore-old/stop/stop-backup/restore-new/start/resume/restore-schedules及final-readback回执。这是保留既有SCHEDULED配置的来源恢复，不是伪造一次同阶段转换。全部11项dirty及untracked保留，原阶段配置identity保持56c2dc122e0cb19fb84848fb0f8f841eeba6889033d36e5ba9501f4cf6486142。
- 新UI PID83486于09:17:59启动，五个核心角色及ready-worker、wallstreet-worker均登记当前hash 6ede58a30f9814ea009dda0c1818298ff3bcbac152ac3bfed7a8dad7c2d5c5d0；真实birth/cwd匹配。恢复RUNNING/version36、原调度，恢复过程中关键词预算维持1/1。正常业务在恢复后有已登记任务在途，不等于来源失配。
- 09:20–09:21 Cloud只读观察：API启用，项目搜索1/100、通用270/10000。使用带时区的当前时间现场核实宿主保护窗口为false；不能把无时区本地时间传入会按美东解释的settings接口。09:21正常控制面恢复DISCOVERY_ONLY/version26；搜索20/日、详情40/日、单规则定时、admission=false均保持。
- **09:21:38–09:21:40自然SCHEDULED作业fd2e71abfe5b404283e5f1d3e0a9002c COMPLETE/OK**：新增3、重复22、受限20，实际搜索1/详情1，总预算2/2。未手工调用tick。25条真实作业评分快照全部按现行统一公式重新计算一致，项目预算归属核对通过；原始DB证据保存在恢复目录scheduled-job-proof.json及scheduled-score-verification.json。
- 尚需同一候选至少4小时后的自然REFRESH（理论不早于13:21:40，实际以DB采样时间和调度为准），再用真实作业证据、新配额和完整维护门禁生成ADMISSION计划。累计最多1条真正达标新主任务，75分、热度及内容门槛不降；不得扩大发布授权。当前实际定时采集已生效，但完整端到端验收未完成，跟进保持ACTIVE。

## 2026-10-14 12:16 并行首页部署后的基线核实

- 生产已由并行工作采用main e0e05af（筛选记忆/紧凑点赞率显示），此前7dca9bb补齐了保留已采用关键词配置的源码部署路径。私有目录filter-preferences-20261014的journal九步COMPLETE，最新Sources.final、保护字段和已恢复调度现场核对通过；不能再用09:22旧inventory差异直接认定异常或回退。
- 当前运行hash cf252dbe7c561bc602e6b05e7c8a3f58327792cf7682215c000c5ac3c5b03e7b，登记worker源码及birth匹配。RUNNING、DISCOVERY_ONLY/version32，原SCHEDULED profile有效、日20/40、admission=false；两个真实成功作业和预算2/2保持，尚无REFRESH。25个候选自然刷新时间仍为13:21:40.517805，当前最高45分，不能降低75分门槛凑准入验收。
- 12:15观察保存在keyword-source-recovery-20261014-a/observation-20261014-1215.json；其中inventory_preserved=false是与旧源码恢复基线比较，已通过最新正式部署清单解释。下一阶段应读取最新主干的部署实现与清单，保留并行修改；四小时自然刷新完成前不生成ADMISSION计划。

## 2026-10-14 13:24 自然刷新验收及受控准入开放

- 最新生产e0e05af完整运行源码清单e2156cc517bfcabfa0d2e1d95fa85c18cc8266a08425ffeaf88732d06afb8e20再次隔离验证：434 passed/10 warnings，含关键词、阶段转换、原生维护部署与真实浏览器；证据 `/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/video-pytest-rmxuegsx`。保留所有并行dirty及untracked，没有修改产品代码。
- 13:17 Cloud实际只读观察搜索2/100、通用374/10000；带时区现场宿主窗口允许。13:21:50自然第二次SCHEDULED作业57deff6653d14a3d86d8530b885859e9成功（新5/重复20/受限21）。13:22:07–08自然REFRESH作业73182ac657e44a9eab9771fdb9a5b552成功，刷新5条，详情1单位；与首次SCHEDULED的同一候选间隔至少四小时，经原生job_proof预算/时间/统一评分快照全部通过。搜索重复命中的20条重新排定刷新，未命中的5条自然到期完成独立REFRESH；未手工tick或改时间。
- 关闭持久模式后生成全新ADMISSION计划d4ba437c6ce748f09fc64be5f23d3c24，私有目录 `~/Library/Application Support/VideoProcessing/deployments/youtube-keyword-admission-20261014-a`，原生九步COMPLETE。来源/锁/排空/备份/保护/恢复全部通过；未改旧journal、删锁或强杀。实际重启及最终回读通过后正常控制面开启DISCOVERY_ONLY/version35、admission=1/version2，宿主累计准入上限1，日预算20/40、单规则保留。
- 当前真实预算搜索3/详情4（仅首次1/1属于试运行，后续为已批准正式定时/刷新）；自然采集、自然热度刷新、统一评分、受控能力已生效。当前尚无达标新主任务，不能把准入配置打开当作自动准入验收完成。继续等待自然达标候选，75分、热度、内容门槛及外部发布授权不变；自动跟进保持ACTIVE。
- 13:23进一步读回：30个观察候选中2条评分分别88/86，但均RESTRICTED（不满足180–1800秒时长），task_id均null；其余候选未全部达标。不能沿用此前“最高45/尚未75分”的旧结论，也不能仅凭高分强行准入。自然调度持续运行，准入限制按预期阻止这两条。

## 2026-10-14 17:25 宿主重启后的恢复阻塞

- 宿主 uptime 证明约16:43重启；topic审计08:43:23 UTC由host关闭模式为OFF/version36。当前UI于16:45重建，五角色源码与进程birth匹配，源码/保护检查通过。未发生新的关键词搜索或准入。
- 原ADMISSION调度回读出现RESTORED_DEFINITION_MISMATCH：ai-cover-doer和english-world-forced-recovery改由原LaunchAgents plist加载，与部署临时恢复定义仅RunAtLoad不同。不能改旧journal或把旧计划复用为新恢复。
- 17:24依用户既有授权原生maintenance_control enter暂停接纳，MAINTENANCE/version43，现场active=[]。未强杀、删锁或重启。发现两个ABANDONED_ADMISSION，均为重启前channel-monitor登记：92a92ed674bd4274b769201bb2d047bf/PID72320、f6616aa5205a49dfa7ce8127b047506e/PID63279；两PID均不存在。该状态不能当作安全空闲。
- 当前代码仅检测ABANDONED_ADMISSION，没有原生显式回收命令。恢复必须先补齐受控、可审计的遗留登记对账路径，不得手工删除或伪造回执。搜索保持OFF，规则/准入上限/并行源码保持。需审阅恢复规格再实施，不能仅等待这些已无进程的登记自然消失。
- 17:24 Cloud只读刷新：项目gen-lang-client-0993011647，API启用，搜索0/100，通用106/10000（配额日已切换）；未来执行仍须刷新有效期。观察回执见私有ADMISSION目录observation-20261014-1722.json。

## 2026-10-14 18:25 恢复规格待确认

- 已完成 `docs/specs/maintenance-orphan-reconciliation-v0.4.1.md`：仅本次两个channel-monitor遗留记录的显式对账、保留原件归档、崩溃恢复及原生全门禁重新验收；包含首次独立维护入口的身份绑定要求，禁止宽泛进程豁免。规格718877d已推送隔离分支，未开发或修改生产恢复逻辑。
- 已集中请求用户确认新恢复范围，等待明确回复；未回复不得开发或归档。生产仍MAINTENANCE43/OFF36、active=[]。本次status出现短暂UNREGISTERED_PROCESS 28422，随后ps已不存在；这不是放宽检查的理由，正式执行仍须重新获取完整现场证据。

## 2026-10-14 20:28 并行恢复已采用，独立回归通过

- 已只读核实另一会话“排查YouTube连接与今日未发布原因”获得用户确认后完成恢复；生产main现为18b4cd1d80d5731c182f5838879011287b1dad29。本次两个遗留登记已通过其受控归档及原生部署恢复处理，不再等待18:25的同一恢复批准，也不重复归档或重放旧计划。v0.4.1通用增强规格并不因此自动视为全部实现。
- 独立核验 `/Volumes/EXT2T/AppDataOffload/ryusei/continuity-deploy-20261014-1926`：journal COMPLETE、两个归档原件SHA与计划一致、源码最终检查及保护字段通过、五类worker真实birth及来源一致。运行hash为3c0dd414abb0307e7f8746e0d8e266eb41fe49d4c141cf328c6b9f06868ce109。新增翻译队列cron与回执cron.after-title-worker逐字节匹配，不能误用旧cron基线判定漂移。
- 对最新生产快照独立执行关键词、维护、部署、浏览器回归：**434 passed / 10 warnings**，runner exit 0，沙箱清理完成。证据 `/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/video-pytest-h0k9wrsn`，源码清单SHA-256 34a3efcc726a403bd9f4f13ebe71866db76dad386d32c42bd1f77538f13f98a6。本次未改生产源码，保留全部并行工作。
- 现场RUNNING/version44、unknown=[]，搜索仍OFF/version37；完整已采用关键词profile校验通过，恢复回执记载admission=1/version4。存在在途视频r-IlR86-iVc:0及queue-dispatch，不强停、不覆盖运行源码。20:26带时区计算当前尚未进入保护窗口，但20:30即受保护，下一安全分钟为2026-10-15 04:15北京时间；执行时必须重算。此刻不仓促开放，也不提前将整个流水线冻结一夜。
- 下一安全窗口刷新非秘密Cloud配额，重新核实现场来源、调度、锁及保护；如需维护，用全新现场计划及preserve-keyword-profile路径，先暂停接纳、自然排空，保留全部门禁。不得复用旧完成计划。门禁通过后恢复已授权采集，再验收最多累计1条自然达标主任务。
- 自然定时采集、四小时自然刷新、统一评分已有真实证据，但真实达标准入仍未完成。肺鼠疫规则于10月15日14:33北京时间到期，不自动延长或降低门槛。跟进保持ACTIVE。

## 2026-10-15 02:31 并行修复后的运行来源差异

- 生产HEAD变为007dbd1（Telegram登录失败通知修复，涉及src/bot/pipeline_agent.py、telegram_bot.py及对应测试）。全部并行dirty/untracked保留，未回退或采用源码。
- 当前RUNNING44、active=[]、轻量登记unknown=[]；但单独检查六个现存角色的真实birth均匹配，而source_hash均与磁盘不匹配。磁盘hash为3712d8d062eb84b4fa40f5d3af6295fb1aeb7a08e315acf6b0b3ac7286737363。轻量status为空不表示完整来源门禁通过；434项通过只覆盖此前快照。
- 当前保护窗口仍有效，下一安全时间现场计算为10月15日04:15。保留搜索关闭，不强停、不改锁或登记；安全窗口先核实最新并行采用记录，若未完成则按已授权精确基线恢复及原生维护部署流程处理，重新验证当前快照，全部门禁通过再恢复采集。不得直接以007dbd1提交存在替代运行采用证据。

## 2026-10-15 06:29 来源恢复已完成，搜索仍未恢复

- 04:36原生enter暂停接纳，MAINTENANCE45，任务自然排空。最新生产快照437 passed/10 warnings，runner0且清理完成；证据video-pytest-15_tcfpa，清单bbdb4bdf2dbd515faaed49dcdcfe8dac1813ee2676a9cb22699830abd7d2b015。
- 新私有恢复目录 `~/Library/Application Support/VideoProcessing/deployments/keyword-source-recovery-20261015-a` 完成prepare、freeze、精确旧基线还原、原生安全停止及备份、恢复全部新代码、维护启动、resume及原调度恢复。仅两份bot文件暂存还原，完整inventory原样保留，无强杀、改锁或旧journal重放。04:40最终来源/保护/调度/角色birth/hash回读通过，RUNNING46。
- 04:40Cloud实际只读配额搜索0/100、通用239/10000、API启用；该证据到06:29已过期。搜索恢复尚未执行，不能把来源恢复当成采集恢复或完整上线。维护时准入正常关闭至version5；06:29当前OFF38、admission0、automatic_used0、六角色源码与birth全部匹配，active=[]、unknown=[]，runtime_code=MARKET_GUARD。
- 下一步只剩刷新配额、现场窗口和完整恢复记录后，通过正常控制面恢复已授权搜索及累计1条准入，再读取自然作业及真实主任务；当前源码未变时不重复开发、重跑同一回归或再次来源恢复。规则今日14:33到期，若仍无自然达标候选，明确报告“功能生效但真实准入未验收”，不得降低阈值或自行延长规则。

## 2026-10-15 06:38 验收记录收敛及实际入口复核

- 已将隔离分支的8项验收文档/证据合回生产main并推送，合并提交b3f276d。相对007dbd1仅docs变化；06:37运行hash仍3712d8d062eb84b4fa40f5d3af6295fb1aeb7a08e315acf6b0b3ac7286737363，六个存活角色的真实birth/hash均匹配。旧来源恢复inventory的HEAD不同来自文档合并，不能将其误判为运行代码再次漂移，也不改旧回执。
- 实际浏览器从首页顶部“YouTube 关键词采集”一击进入工作台；“新建采集规则”可打开名称、查询词、类别、时间范围、语言、时长、有效天数表单，取消后未写入新规则。33条候选成功加载，受限候选显示具体时长/频道/内容原因，过期统计明确提示等待刷新；保护窗口下搜索与准入禁用且给出原因。这里只验证真实导航、读取和未保存表单，不将其等同于恢复搜索或完整故障注入验收。
- 暗色页面“新建采集规则”主按钮文字对比偏低，记录为后续视觉修正项；按钮可操作，未因此改动运行代码或重新部署。
- 06:37仍受宿主保护，现场下一安全分钟07:00。RUNNING46、unknown=[]，出现正常登记的subprocess/continuation在途；没有提前冻结或强停。恢复已授权搜索应在窗口开放后刷新配额并走正常控制面，只有确需维护时才暂停接纳排空。当前搜索仍OFF38、准入仍关闭，真实准入0，尚未完成。
