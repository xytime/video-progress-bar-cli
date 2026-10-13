# YouTube 关键词采集 v0.4：OFF 状态生产验收

记录：Codex，2026-10-13。用户已确认 OFF 状态采用；本轮生产采用和回验已完成，真实搜索、试运行与准入开放不在本轮授权范围内。

## 后续并行维护后的最新回查

在本轮 21:18 回验后，另一项已授权维护将生产更新到 `cf400f2`，修复独立隔离测试进程的归属识别。该维护拥有独立 188 项回归及部署回执，本轮不把它与 590 项相加。再次调用其原生部署 final_status 通过，调度、来源和运行角色重新匹配；最新来源哈希 `f14bc7cc8034214816b0110786956880f7ebf510bb9b6b1330fe51b5f7d2982f`，维护 RUNNING/version 16，关键词 OFF/version 11，四项开关仍为 false，jobs 为空、预算为 0。

最新巡检保留一项 UNREGISTERED_PROCESS（82214）：现场为外部 c446 工作区借用生产 venv、以相对路径调用隔离测试脚本。该入口不满足新逻辑要求的绝对入口核实条件，因此仍按未知保护，没有加入排除名单或强杀。它不改变已经完成的 OFF 采用结论，但下次维护仍须重新核实并通过全部门禁。来源冻结证明在正常运行期仍不提供。详见[最新回读](evidence/youtube-keyword-collection-v0.4/production-off/latest-runtime.json)。本报告及证据随后仅作文档提交，不改变运行源码。

## 首次 OFF 采用结论

- 生产运行采用 `ff317aed9c3503f0662a09f2fdb640f0064c024c`，已整合原维护最终提交 `e4dd3ea`，保留文章/孤儿任务恢复、lsof 路径修复及其他并行开发。
- 最终隔离整合验收 **590 项通过、0 失败**，13 条依赖弃用警告。该数字不与历史 475/587 项累计。真实浏览器、关键词调度/评分/准入、维护/部署、既有流水线及数据库兼容测试均在隔离副本中运行。
- 生产恢复 `RUNNING / IDLE`（维护版本 14），搜索持久状态 `OFF / version 10`；搜索、定时采集、达标准入与配额已核实开关全部 false，持久准入为 0。
- 本次没有执行真实 YouTube 搜索或准入。回验时本模块当日 search/general 均为 0，jobs 为空；这不代表整个 Google 项目的共享配额已核实。

## 维护与采用证据

先等待其他维护正常完成，重新整合和测试后生成新鲜计划。冻结遇到在途 `wallstreet-render` 时原生门禁拒绝继续；等待其自然退出后重新检查，通过才正常停止、备份和采用。没有强杀、删除锁或绕过来源检查。

按已确认首次采用协议执行两版本 bootstrap：旧实现完成 baseline/freeze/stop/backup，新实现完成 adopt/migrate/start/resume/restore/verify。每一步独立记录并验证，未把混合实现冒充同版本正常部署 journal。本轮未额外执行新版 CLI 同版本完整维护循环，也未执行回滚演练。

数据库一致性备份完整性为 ok，SHA-256 为 `5f65561dc0883a6f91e0174cf6fd1fe8de9f97580333332cdbd9f82b62385b40`。私有部署证据保存在 `~/Library/Application Support/VideoProcessing/deployments/youtube-keyword-v04-off-20261013-b/`。备份不是自动覆盖生产数据库的授权。

六个已注册角色的 PID/birth/cwd 和运行来源完成核对，来源哈希一致：`6ee856f55a43f044d69a61dece1e62cd851552a2a6dbb75136100a7ec75b3dd6`。原 cron/launchd 调度已恢复。正常 RUNNING 回读中的 SOURCES_NOT_VERIFIED 表示没有当前冻结来源证明；实际维护阶段通过了完整安全检查，未忽略异常。

生产原七项 tracked dirty 均保留：database.py 三方整合保留生词开发，其余六项逐字一致；1197 个未跟踪文件保留。未 stash/reset 无关工作，未复制测试数据库到生产。

## 实际使用者验收

实际生产浏览器地址为 `http://localhost:9100/`：

| 路径 | 结果 |
| --- | --- |
| 首页 → 常用入口 → YouTube 关键词采集 | 可直达，与频道白名单并列 |
| 新建采集规则 | 表单可用，默认最近 24 小时、英语优先、最短 30 秒、有效 7 天；取消未保存 |
| 编辑既有肺鼠疫规则 | 原 72 小时/180 秒/2 天配置正确保留；取消未修改 |
| 搜索及准入状态 | 明确显示生产搜索未开放、定时采集未开放、准入关闭及凭据/共享配额前置条件 |
| 返回首页、生产队列、商品入口 | 可访问并正常载入；未触发处理或保存商品 |

既有肺鼠疫和 AI 产业与算力规则可读；生产没有创建虚构规则或视频。旧规则最短 180 秒与新建默认 30 秒的差异是保留旧配置的结果，不是本轮自动改写。

截图：[首页](evidence/youtube-keyword-collection-v0.4/production-off/home.png)、[关键词入口](evidence/youtube-keyword-collection-v0.4/production-off/keyword-entry.png)、[新建表单](evidence/youtube-keyword-collection-v0.4/production-off/new-rule.png)。

## 可核验证据与后续边界

- [隔离测试回执](evidence/youtube-keyword-collection-v0.4/production-off/receipt.json)、[日志](evidence/youtube-keyword-collection-v0.4/production-off/pytest.log)、[源码清单](evidence/youtube-keyword-collection-v0.4/production-off/source-manifest.json)。最终清单 SHA-256：`eb42ae9498c971d35bbb9a2860a3dd7f5c2dc9d342e871967ec03ef9fd405b7a`。
- [生产回读与文件保留摘要](evidence/youtube-keyword-collection-v0.4/production-off/production-readback.json)，采集时间 2026-10-13 21:18:37 +08:00。
- 凭据归属与共享配额仍未核实；下一阶段先核实这些门禁，再另行确认真实试运行、搜索和准入开放。当前可以人工维护采集规则，但规则启用不等于生产搜索已开放。

最终文档收敛时，上述独立测试进程已自然退出，API unknown 仅剩正常运行期的 SOURCES_NOT_VERIFIED；在途发布任务完成、active 为空后才快进合入验收文档。合入前后运行源码指纹一致，未再重启生产。
