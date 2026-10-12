# v0.2.1 维护来源、接纳与恢复清单

责任记录：Codex；2026-10-12。适用独立实现；生产来源清单须在 A 获批准后重新回读，不能复制隔离夹具的 ABSENT 作为生产证据。

## 共同规则

控制状态由 `settings.maintenance_state_path` 指向同一绝对路径，默认 `output/maintenance-state.json`。原子替换及 fsync 持久化，短 flock 串行化 enter、单项准入、开始执行和 CAS 恢复；网络、制作及排空不持有控制互斥。缺失、损坏、权限故障及遗留接纳记录保持 UNKNOWN，不自动恢复。

接纳记录从 WAITING 到 ACTIVE；等待资源也计入排空，开始前再检维护状态。已 ACTIVE 的有限单项可按原授权走完全部 FSM，必要子执行者凭继承锁 FD、对象和精确 argv 绑定继续；其他对象、下一批次、独立通知和登录恢复均重新准入。进程崩溃留下的未持锁接纳记录使状态 UNKNOWN，需诊断和另行处置，不删锁冒充完成。

`gate.status()` 仅证明本地接纳情况；对外维护状态及本机 status/stop/resume 另检查角色、进程/旧业务锁、账本、关闭配置和来源回执。缺少来源回执时，即使接纳为空，也显示 UNKNOWN / safe=false。UI 注册到实际 PID、启动身份、cwd、协议及源码 hash；正常停止只对同一归属发 SIGTERM，最多 15 秒，没有 SIGKILL 分支。

## 来源覆盖

| 来源 | 入口与接纳点 | 排空/拒绝证据 | 恢复方式 |
| --- | --- | --- | --- |
| Web 全管线 | `_auto_pipeline_loop`、`_start_full_pipeline`；每轮及每个子执行者前检查 | M01 模拟 10 秒/4h 周期；真实 UI 三次生命周期；M04 写 503 | 一个 auto-pipeline 角色，原周期向前运行，不重播漏时点 |
| Web 队列/孤儿恢复/清理 | `_queue_runner_loop`；每轮 running，业务派发登记；DAL 写事务兜底 | M01 15 秒轮询零派发；M03 真实临时库回写；旧队列回归 | 一个 queue-runner 角色，原资格与保护不变 |
| 普通视频及资源等待 | `_process_single_video` 在单视频 TaskLease/资源后开始；`_run_tracked` 绑定子项 | M02 实际等待锁与跨进程；M03 当前完成、下一项拒绝；精确子 FD/argv 拒绝伪造 | 原单视频队列正常领取，不批量重置状态 |
| 独立成片监督/执行者 | `_ready_publication_supervisor`、`run_ready_publications.main`、提交单视频；角色锁 | M01 5 秒轮询；M04 直接入口；M07 角色竞争 | 一个 ready-supervisor + 一个 ready-worker；原成片身份与窗口 |
| cron / launchd / vpanel job | monitor/rescore/background/publication-window/English World 的根入口和逐项入口 | M04 同一脚本等价唤醒拒绝；无修改宿主 cron/launchd | A 操作员按原状清单恢复外部触发；本轮未执行 |
| 频道/热词/评分/研究 | monitor 每频道/每词，rescore 元数据批次及逐行；研究每 job；旧热词 GET 维护时只取缓存 | M04 直接拒绝；真实 DAL；热词 cache-only；生产 hub 副本兼容验收 | 原开关与频道策略；正常刷新登记并受排空统计约束 |
| Web 手工/重试/审批 | 写请求统一有限接纳；研究/生产/投稿/单视频线程在启动前登记；等待型投稿重新检查 | M04 实际 FastAPI 写 503、stats/候选 GET 200；旧控制面回归 | 原授权及商品/内容/发布资格，不新增远程恢复入口 |
| Bot 动作/重试 | PipelineAgent 工具逐动作接纳；阻塞资源后 start_current；对话各轮/重试再检查 | M04 根动作拒绝；既有 Bot 重试与登录回归 | 原消息流程，下一次正常事件按原资格执行 |
| 登录/会话保活 | 看门狗角色每次循环再检查；单登录任务与上传/评论会话锁后检查 | M01 保活周期零派发；M04 keepalive/uploader 直接入口 | 一个 keepalive-watchdog，原开关、优先锁与登录态 |
| 互动/通知 | interaction tick 单对象；通知线程/原子领取登记至账本终态 | M04 直接拒绝；M03 已接纳回写；原通知相关全量回归 | 原互动开关及去重，不集中补发维护期间事件 |
| Wall Street A/B | 独立 worker 角色；每 pair/发布/原生 ID 回查接纳；资源后再开始 | M04 根入口拒绝；真实角色互斥；商品/发布回归 | 一个 wallstreet-worker，原配对、原生身份和延期资格 |
| 直跑执行脚本 | copywriter/cover、微信/抖音/快手 uploader、通用投稿、添加频道、单视频 helper 的 single_script | M04 32 个直接入口调用维护前置拒绝；M03 精确子项归属 | 手工入口仍须 gate RUNNING，不能继承不同对象的豁免 |
| 专题候选 | start_search 先接纳；工作线程持有记录至结束；页面/CRUD 仅候选局部操作 | M08–M13；A01–A21；维护/配置关闭时零请求、零新作业/预算 | 健康恢复先清理/回收并强制 OFF，不自动搜索 |
| 旧账本合法写入 | PipelineDB 连接真实 SQLite authorizer；写事务接纳至提交/关闭，当前有限项继续 | M03/M04；M15 topic-only 回退和当前合法回写 | 不恢复整库，不篡改业务资格/在途状态 |
| 遗留/未知执行者 | 实际角色/旧锁/PID/cwd/hash 采集；未登记项目脚本、CLI、媒体进程及未知来源阻断 | M05/M16；CLI/Web 无来源回执时 UNKNOWN；停机拒绝 | 首次 A 外部冻结和自然排空，旧进程不能由新状态文件约束 |

覆盖不等于任意手工代码的 OS 防护：未知绕行、其他主机和未接入的插件仍须登记并阻断采用。本轮 OS 沙盒只约束隔离测试，未装入生产。

## 本机操作与来源回执

以下是未来 A 的工具契约，本轮没有在生产执行：

```sh
./vpanel maintenance enter --reason "候选工作台关闭状态验收"
./vpanel maintenance status --evidence /absolute/path/sources.json
./vpanel maintenance stop-ui --evidence /absolute/path/sources.json
./vpanel ui start --maintenance
./vpanel maintenance resume --expected-version N --evidence /absolute/path/sources.json
```

enter 成功仅表示暂停已保存；没有可靠来源核实仍返回 UNKNOWN / safe=false。status 未能证明可验收时退出 2；stop/resume 缺少或过期证据也拒绝。`ui start --maintenance` 先保存暂停，拒绝非本目录 LaunchAgent 或未确认的旧 UI，不强杀替换。未核实旧生产时，不能用这些新入口自动完成第一次退出。

来源回执由获授权的操作员产生，schema=1，绑定当前 maintenance version、`maintenance_runtime.code_hash()`、最近 300 秒时间、现有保护快照及五组来源 cron/launchd/manual/bot/independent-workers。每组至少一个检查，不接受通用 `verified=true`。

- `kind=file`：非秘密来源清单文件的 SHA256；内部同样绑定 group/version/source_hash，逐项 readbacks 状态只能 FROZEN、ABSENT 或 INTEGRATED。此文件记录人工核实，不自动证明外部系统已冻结。
- `kind=cron`：重新执行 `crontab -l`，输出须无本项目根命令且 SHA256 一致；间接 wrapper 仍须手工清单核实。
- `kind=launchd-disabled`：重新回读当前用户 `launchctl print-disabled` 指定 label 的 true 状态及完整输出 hash；该 label 的任务归属先由操作员核实。

操作时再次检查内核锁、PID 启动身份、源码、cwd、业务账本与有效搜索关闭。回执不是授权，隔离回执不能用于生产。实际保护应由 A 的独立运行回读确认；文件摘要和新代码检查不代替旧进程、外部触发者及远端调用者的事实核实。

## 失败后保留现场

保持维护和搜索关闭，记录脱敏错误。候选恢复最多每 60 秒一次单飞；旧业务共享存储故障另列，不能据候选 503 宣称隔离成功。候选回退保留维护准入、表、决定、审计、预算与合法既有回写；SQLite backup/integrity_check 只用于一致性恢复点，不自动整库覆盖。退出 OFF 未回读要标失败，不能自动恢复搜索。

首次 A 与 M17、M18 生产观察仍待单独授权，且需重新核实生产源/dirty、实际端口/目录、外部触发原状、安全空闲、LAN 边界及恢复后的唯一执行者。


## 2026-10-12 采用结果补记

用户后续确认 v0.3 并授权上线 A，已完成维护启动、关闭搜索验收、受控重启和恢复。详见[最终生产验收](../2026-10-12-dashboard-v0.3/ACCEPTANCE.md)。前文为当时的计划与授权边界；真实搜索 B 仍未批准，生产配额/凭据项目核实继续作为开放前置条件。
