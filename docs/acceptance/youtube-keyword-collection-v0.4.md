# YouTube 关键词采集 v0.4 隔离验收

记录：Codex，2026-10-13。规格：[已确认 v0.4](../specs/youtube-keyword-collection-v0.4.md)。

## 结论与交付边界

定时关键词采集、热度刷新、统一评分及达标自动准入的受控能力已在隔离工作区实现。后端和浏览器联合回归 **460 项通过、0 失败**；属于 K01–K15 的合成数据/真实本地代码验收。K16 生产采用、真实搜索及准入开放均未执行，不以这份报告替代生产验收。

工作区为 `/Users/ryusei/.codex/worktrees/2d17/Video-precessing`，分支 `codex/topic-candidate-workbench`，开发基线 `abeb033c889aa8ca40ab5865bdd1dcde856f9b3e`。生产 checkout、配置、进程、数据库业务记录均未作本次采用变更。测试使用既有 venv 作为解释器，所有测试均经 `scripts/run_isolated_tests.py --browser`。

## 用户可见行为

- 首页及侧栏将 **频道白名单 / YouTube 关键词采集**并列；入口仍是 `/topic-candidates`，按钮为“新建采集规则”。
- 新规则默认近 24 小时、有效 7 天、30 秒至 30 分钟、英语偏好，可改语言和最低时长。保存后定时关闭；老规则保留原查询窗口、180 秒起点、收藏、排除和历史命中。
- 宿主允许后，运营者逐条启用定时规则，每 4 小时计划一轮，最多 3 条；只取最新 25 条，截断明确提示，不自动翻页。每条估计每日 6 次；保护窗口、暂停或预算会顺延。
- 初次低热度保留观察；72 小时观察窗内批量刷新详情，每批最多 50 个、活跃观察池最多 200 个，其他候选可见并等待轮候。跨规则共用一份视频统计。
- 评分复用已有热度与精确频道政策，缺失统计保持未知。事务硬门槛为 75 分；不因关键词命中获得额外加分，不称 AI 新闻质量分。
- 达标时先留候选；宿主与数据库准入双开关都允许后，事务复核才入 `KEYWORD/PENDING`。既有主任务只关联/展示，不改进度、人工分、DISCOVERY 或发布历史。候选提供主队列任务链接。
- 关闭准入阻挡新准入及尚未开始的关键词任务；来源被改为 MANUAL 或手工评分也不绕过已记录的关键词归因。已开始处理或已提交的平台动作仍按原维护/停止协议处理。

## 核心实现与维护约束

调度复用唯一 `queue-runner`，不新增 cron 或计时线程；必须具有当前 PID、出生时间、协议、工作目录及源码指纹一致的角色锁。作业先持久领取，再调用受共享文件锁、维护 ticket、市场保护与预算约束的适配器。重启仅安排当前到期轮次，不补跑多轮。

搜索总预算 20 次/配额日，定时最多 18 次，保留 2 次手动份额；搜索详情与观察刷新、重试共享 40 详情单位。每次调用预占，按太平洋配额日累计；这些是本模块预算，不证明其他共享调用者的可用额度。

`topic_scheduler_enabled`、`topic_admission_enabled` 默认 false；沿用 `topic_search_enabled=false`。新开关加入维护保护快照与部署检查，数据库准入也需关闭才能确认 OFF 采用。没有绕过维护检查。数据库旧名 `DISCOVERY_ONLY` 继续表示搜索控制模式，v0.4 的主队列准入由独立双开关控制，页面分别展示。

## 验收映射

测试完整文件列表与命令参数见 [runner 回执](evidence/youtube-keyword-collection-v0.4/receipt.json)。以下名称可直接在测试中定位，不将单元注入等同真实 API 验收。

| 条目 | 证据与结果 |
| --- | --- |
| K01 路径 | `test_a20_complete_task_desktop_and_narrow`、`test_k14_rule_language_selection_and_keyboard_save`、首页 workspace 回归：建规则、保存、导航、关闭原因通过 |
| K02 默认/迁移 | `test_closed_flags_and_expiry`、`test_old_schema_upgrade_keeps_rules_and_decisions`、既有默认关闭/恢复测试：真实 SQLite 移除新增列后迁移，保留历史决定 |
| K03 调度 | `test_parallel_ticks_one_search_restart_no_catchup`：4 个并发调用只搜索一次，推进虚拟时间 20 小时无补跑风暴；持久任务身份及锁复用 |
| K04 来源并列 | `test_coverage_and_nonwhitelist`、频道 funnel/TED/评分上限回归：未知频道可入候选，不新增白名单或 AUTO 专属资格 |
| K05 时效覆盖 | 查询窗口及官方适配器回归、coverage 测试、旧规则迁移、过期/陈旧拒绝；25 条截断标志可见 |
| K06 统一评分 | `test_shared_score_boundaries` 参数用例、TED 和 channel caps 回归、`test_admission_transaction_does_not_lower_keyword_score_line`：事务不能因其他频道低阈值放行 |
| K07 成长 | `test_scheduled_cold_refresh_hot_admission_and_close`：低分→仅刷新详情→达标→开准入才入主库；浏览器闭环同步覆盖 |
| K08 预算/缺失 | `test_atomic_shared_budget_reserved_manual_and_details`：8 并发预占仍为 18 自动+2 手动/40 详情；观察池 201 项轮候、缺失统计及原配额日/DST 测试通过 |
| K09 去重/历史 | 跨关键词与频道竞争、并发准入、DISCOVERY 不提升、切片/人工锁/发布历史回归：一个源任务、多个命中，不覆盖原任务 |
| K10 准入 | `test_admission_rechecks_current_boundaries`、原子竞争：暂停、版本、黑名单、排除、过期、统计缺失、规则变化均拒绝；主任务引用可回读 |
| K11 下游 | 准入关闭后准备/处理/提交领取为空，改来源/手工评分仍阻挡；队列串行、重试、发布窗口、原来源回归通过 |
| K12 维护 | 实际角色锁和错误指纹拒绝；在途搜索期间维护使后续详情/准入停止；新增开关引起保护漂移/闭合检查拒绝，原维护恢复与部署回归通过 |
| K13 故障 | 已有真实路由的断网/超时/旧响应/读取恢复及适配器错误测试；新增指纹与凭据错误浏览器截图；认证失败不会自动无限重试 |
| K14 使用闭环 | Chromium+真实 FastAPI/DAL：新建→启用→低分→刷新达标→受控准入→关闭→点击主任务并看到唯一记录；390px、明暗/高对比、草稿、焦点、键盘提交回归通过 |
| K15 隔离 | runner 的外部读取/写入、网络、跨边界信号、数据卷别名和子进程写入探针全部拒绝成功；没有 YouTube/发布平台外部请求 |
| K16 生产 | **未执行**：生产采用、真实 API 试运行、生产准入及制作发布均需另行确认 |

## 原始证据与可见结果

- [pytest 完整日志](evidence/youtube-keyword-collection-v0.4/pytest.log)：460 passed，13 条依赖弃用警告，113.46 秒。
- 最终来源标签补充后的[浏览器复核回执](evidence/youtube-keyword-collection-v0.4/final-browser/receipt.json)及[日志](evidence/youtube-keyword-collection-v0.4/final-browser/pytest.log)：101 passed，10 条依赖弃用警告，56.50 秒；这 101 项属于上面联合回归的重复复核，不累计为 561 项。最终源清单 SHA-256 为 `cfbc06e4667429c75fc2e2a1c3e8c6f06d4f951c0963b6086ba650834ad84064`，已逐项核对当前 src/tests/scripts 与通过快照一致。
- [源文件清单](evidence/youtube-keyword-collection-v0.4/source-manifest.json)：SHA-256 `a55762f024230d3af14a71f631add3dbaff2842413aa9185c8d246b1b805f799`。最终主队列来源文字补充后的浏览器复核另列，后端逻辑未再改动。
- [隔离探针](evidence/youtube-keyword-collection-v0.4/boundary-probe.log)、[沙盒规则](evidence/youtube-keyword-collection-v0.4/sandbox.sb)：探针退出 0；日志中隔离子进程无法导入宿主 `.pth` 的提示不代表网络或文件放行。
- [UI 严格审计](evidence/youtube-keyword-collection-v0.4/premium-audit.json)：0 错误、0 警告。[设计文档 lint](evidence/youtube-keyword-collection-v0.4/design-lint.txt)：0 错误、0 警告；5 条未显式列 token map 的信息项，现有 CSS 仍为值来源。
- 截图：[低分观察](evidence/youtube-keyword-collection-v0.4/v04-observing.png)、[达标入队](evidence/youtube-keyword-collection-v0.4/v04-admitted.png)、[关闭准入窄屏](evidence/youtube-keyword-collection-v0.4/v04-narrow-admission-closed.png)、[规则表单](evidence/youtube-keyword-collection-v0.4/v04-rule-editor-narrow.png)、[错误阻挡](evidence/youtube-keyword-collection-v0.4/v04-runtime-credential-blocked.png)、[主任务回读](evidence/youtube-keyword-collection-v0.4/v04-main-task-readback.png)。全为合成数据；测试时间可与浏览器时钟不同。

验收限制：macOS Chromium headless shell 不呈现系统原生 select 弹层。已验证真实 select 值保存、焦点、键盘打开/取消对话框及 Enter 保存，但不声称验证了系统弹层的方向键选项切换、其他浏览器或读屏软件。使用既有原生控件，不为测试另造替代组件。测试没有覆盖真实媒体制作、外部平台提交或真实热点报道质量。

## 生产回查与下一步

本次只用 HTTP GET 回查 `http://127.0.0.1:9100/topic-candidates` 及状态：[带时间的回执](evidence/youtube-keyword-collection-v0.4/production-readback.json)为 HTTP 200；`OFF/version=7`，`search_open=false`，`can_enable=false`；配额日 2026-10-13，本模块 search=0/general=0/jobs=0；维护 RUNNING/IDLE。这不证明全 Cloud 项目零消耗，也不证明 v0.4 已运行。

建议下一次单独确认 **v0.4 OFF 状态生产采用**：重新核对生产差异和所有运行来源→维护排空→受控备份/迁移/采用→指纹与恢复检查→在三个宿主开关及持久搜索/准入都关闭的状态回验入口、旧规则和错误提示。不得直接复制隔离数据库或复用旧部署保护快照。

真实试运行之前仍需证明生产凭据归属、共享调用者及可用配额，并取得单独授权；试运行阶段准入继续关闭。真实采集/刷新/预算回读通过后，再请用户决定准入开放及后续自动制作发布范围。当前没有启动这些步骤。
