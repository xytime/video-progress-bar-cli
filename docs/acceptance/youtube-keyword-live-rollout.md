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
