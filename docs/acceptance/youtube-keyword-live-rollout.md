# YouTube 关键词采集：生产实际生效执行记录

记录：Codex，2026-10-13。状态：执行中；生产外部门禁待核实，尚未真实搜索或开放。

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
