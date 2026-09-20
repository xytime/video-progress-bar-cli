---
work_order_id: VP-POLARIS
codename: 北辰
status: PLANNED_NOT_STARTED
created_at: 2026-09-12
last_updated_at: 2026-09-20
---

# VP-POLARIS「北辰」重构工程总工单

## 1. 工单目标

在不改变现有外部发布结果、不接触生产数据库的前提下，先封闭已经由源码证据确认的控制面旁路和自动候选漏洞，再建立足以支撑渐进拆分的入口级回归证据。总体路线采用 **Hybrid Plan B：Containment → Contract/Harness → Incremental Extraction**。

本工单是本轮重构的入口与首批执行清单。若它与同目录早期候选工单或 Gate 状态冲突，以本工单、根目录 `HANDOFF.md` 和开工时的现场证据为准；冲突必须在实施前说明并同步修订治理文档。

## 2. 启动口令与授权边界

- 推荐口令：`继续北辰重构`
- 等价口令：`启动 VP-POLARIS`
- 口令含义：读取根目录 `HANDOFF.md` 和本工单，进入 `POLARIS-000` 现场复核，然后在本工单范围内继续源码、测试和治理文档工作。
- 口令不授权：真实投稿、发送 Telegram、修改生产数据库、重启服务、操作创作者平台、清理无关 dirty changes，或扩展到首批工单之外。
- 当前状态：**PLANNED / NOT STARTED**。最早下周由用户明确说出口令后启动，不设置自动任务。

## 3. 首批工单队列

| 编号 | 内容 | 状态 | 前置条件 | 完成证据 |
| --- | --- | --- | --- | --- |
| `POLARIS-000` | 生产 checkout、Git、运行空闲和文档漂移复核 | READY | 用户发出启动口令 | 记录 `git status`、`main/origin/main`（当前锚定 `e897eb2`）、流水线/浏览器任务状态和文档差异，确认生产代码零修改 |
| `POLARIS-101` | 补真实入口级隔离回归测试（双轨红绿断言与扩展边界覆盖） | BLOCKED | `POLARIS-000` | 漏洞复现用例先红后绿，现有正常基线用例全程保绿；覆盖 Bot 退出码 6、状态与删除越权、DISCOVERY 候选硬排除与 promotion 纳入、并发重置、退出码 3（结果未确认）、超时及平台受理后本地崩溃窗口（未决 Attempt 租约恢复）、转入 UNCERTAIN 后再次领取仍被拒绝的阻断测试（`test_claim_attempt_rejected_when_prior_attempt_is_uncertain`）、独立活跃租约生命周期与条件释放测试（`test_active_claims_lease_lifecycle`）、历史 Attempt 存在时的独立阻断测试（`test_claim_attempt_rejected_when_only_historical_attempt_exists`）、外键兼容与领取失败原子回滚无残留测试（`test_claim_attempt_rollback_leaves_no_residual_on_failure`）、微信真实会话锁规范化探测与持锁反例测试（`test_wechat_session_lock_probe_detects_real_hold_and_release`，使用 `canonical_wechat_session_lock_path` 探测 `output/.wechat_state.json.browser.lock`，持锁时必须判定非零失败）、历史 Attempt 表扩展 CHECK 约束迁移平滑性测试 |
| `POLARIS-102` | 封闭 Telegram PipelineAgent 直接 uploader、任意状态、删除与重试旁路 | BLOCKED | `POLARIS-101` 红灯证据 | Bot 收口为具名任务分发客户端（执行 QUEUED 响应前持久化与活跃任务幂等复用）；全面确立方案 A 完整契约并废除方案 B：完成 Attempt 历史表 CHECK 约束平滑扩展迁移（纯追加审计历史无唯一约束，杜绝表迁移 IntegrityError），创建独立原子活跃租约表 `wechat_submission_active_claims`（`subject_id TEXT PRIMARY KEY`）；在单个 `BEGIN IMMEDIATE` 事务内严格按外键顺序执行：① 4 表联合前置阻断（覆盖活跃租约、历史 Attempt、Publication 与主表状态）；② 先插入 Attempt 记录满足外键依赖；③ 再插入活跃租约表实现主键原子排他（任一步失败全量回滚零残留）；按 `active_attempt_id` 条件精确释放与流转（明确 BUSY 时标记 RELEASED_BUSY 并释放活跃租约，退出码 6 原子四表落账，崩溃恢复 Fail-Closed 转入 UNCERTAIN 绝不自动重领，物理阻断并发与重复提交，闭环 At-Most-Once）；核心应用服务负责安全拦截与退出码 6 原子四表落账；子进程自洽持锁，仅对明确 BUSY 凭证有限退避，通用退出码 1 判定为永久失败，退出码 3 强制置为 UNCERTAIN 绝不自动重试 |
| `POLARIS-103` | 在中心 DAL 候选咽喉 `get_high_score_pending_videos()` 排除 `source='DISCOVERY'`，并修正错误 Golden 契约 | BLOCKED | `POLARIS-101` 红灯证据 | 高分 DISCOVERY 不进入自动候选（UPPER/TRIM 防护）；原子 promotion 为 MANUAL 后可进入；GOLDEN-WF-01 修正为 AUTO |
| `POLARIS-104` | 修订 M6、INV、RISK、Golden 和既有工单语义 | BLOCKED | `POLARIS-102/103` | M6 不再虚称完整回放通过；平台语义和风险边界一致；登记册对齐 RISK-STATE-001/003；吸收红蓝博弈加固结论 |
| `POLARIS-105` | 隔离验证、目标提交与推送 | BLOCKED | `POLARIS-104` | 目标测试及完整非浏览器单测通过；仅目标文件提交并推送 `main` |

以上工单按顺序推进。`POLARIS-102` 与 `POLARIS-103` 可以分别形成小提交，但不得在缺少各自入口级失败测试时先改生产逻辑。

## 4. 验收标准

1. Telegram Bot 不再拥有可绕过统一安全策略的直接发布或任意状态 mutation 路径；微信 uploader 的“已受理待审核”退出码 6 不得被写成普通失败并触发自动重试语义，且状态流转必须原子落盘 Publication 账本，杜绝鬼魂状态。
2. Bot 严格收口为具名任务分发客户端，执行响应前持久化协议与幂等复用，统一返回 `QUEUED` 异步受理语义及任务凭证，提示词对齐，严禁在后台执行中向用户宣称“已发布完成”；执行环境复用 `_build_subprocess_env`。确立方案 A 完整契约并废除方案 B：外部拉起前完成 Attempt 历史表 CHECK 约束平滑扩展迁移，创建独立原子活跃租约表 `wechat_submission_active_claims`（`subject_id TEXT PRIMARY KEY`，杜绝迁移 IntegrityError）；在单个 `BEGIN IMMEDIATE` 事务内严格按外键顺序执行：4 表联合前置阻断检查（包含租约、历史 Attempt、Publication 事实表与主表） → 优先插入 Attempt 满足外键约束 → 随后插入活跃租约实现主键互斥（失败原子回滚零残留）；按 `active_attempt_id` 条件精确释放（BUSY 释放重领，未决或崩溃恢复转入 `UNCERTAIN` 物理阻断再次重领，闭环 At-Most-Once）。
3. 会话锁由子进程内部自洽持有（严禁父进程外置重复持锁，杜绝因超时 0 秒导致锁争用立即锁忙失败）；会话锁探测必须调用 `canonical_wechat_session_lock_path("output/wechat_state.json")` 探测真实锁文件 `output/.wechat_state.json.browser.lock`，且验收测试必须包含真实持锁时的失败反例；仅对明确 BUSY 凭证有限退避（最多 3 次），通用退出码 1 判定为永久失败，退出码 3 明确为发布结果未确认（`EXIT_RESULT_UNCERTAIN`），绝不可自动重传。
4. `get_high_score_pending_videos()` 从中心候选层排除 DISCOVERY（加固 `UPPER(TRIM(COALESCE(pv.source, ''))) != 'DISCOVERY'`）；只有显式、原子 promotion 后的 MANUAL 记录可进入后续处理。
5. `GOLDEN-WF-01` 不再把高分 DISCOVERY 自动入队当作正确契约；由独立的正反双轨回归套件死守 DISCOVERY 防火墙。
6. 使用项目 `.venv` 与 isolated runner；先通过目标测试，再通过完整非浏览器单元套件。除非另获明确授权，不运行会触碰真实平台的测试或命令。
7. 遇异常回滚时，实行**受控安全回滚五步法**：① 宿主级停写（导出 crontab 备份并执行 `sed -E '/Video-precessing/s/^([^#])/# QUIESCE_DISABLED \1/'` 物理注释调度，核验活跃 crontab 为空彻底阻断 cron 复活；置 `WECHAT_PUBLISHING_PAUSED=true`；终止常驻服务与关联进程组 PGID 及 Chromium 孤儿；通过 `canonical_wechat_session_lock_path` 探测 `output/.wechat_state.json.browser.lock` 核验真实会话锁释放并标记在途任务为 `UNCERTAIN`，未证实零消费前严禁 revert）；② 绑定具体目标 Commit 执行原子回滚；③ 沙箱运行 `POLARIS-101` 新增防线测试（严禁运行包含不安全基线的历史单测，防线测试若失败必须保持暂停与 crontab 静音、严禁恢复调度）；④ 推送并重启全套守护进程；⑤ 确认无误后恢复 crontab 调度并解除暂停。账本纠偏严禁全库盲跑与裸写生产 SQL，备份必须采用 SQLite 在线备份 API（`conn.backup()`），命名采用高精度微秒 UTC 时间戳与 UUID 随机熵拒绝覆盖，验证完整性（`PRAGMA integrity_check;`）并登记恢复点元数据，通过 DAL 封装接口进行只读差异预览（排除 `PUBLISHED`）与受控定点纠偏。
8. 分别报告文件变更、测试、提交、推送、运行采用与外部平台状态；严格遵守【协议已落盘】、【实现待完成】与【测试已验证】三层状态分离，未验证层级保持 UNKNOWN/NOT PERFORMED。
9. 不夹带、不覆盖生产 checkout 中已有无关改动。确认前序提交 `9b0eb71` 属于正交业务演进，重构工单生产代码严格保持 100% 只读冻结。

## 5. 明确非目标

- 本批次不直接拆分约 10.6k 行 `PipelineDB` 或约 4.4k 行 `PipelineManager`。
- 本批次不迁移微信、抖音、快手真实投稿执行层。
- 不用 feature flag 恢复已知不安全的 Bot 透传路径。
- 不把本地文件、测试通过、Git push、进程启动、平台受理或公开可见混称为“已上线”。

## 6. 已知证据入口 (2026-09-20 校准快照)

- `src/bot/pipeline_agent.py:151-170,178-206,637-752`
- `src/bot/telegram_bot.py:1562-1572`
- `src/video_processing/db/database.py:3406-3505,4253-4310` (record_wechat_submission_acceptance & get_high_score_pending_videos)
- `src/video_processing/pipeline_manager.py:1498-1540,4255-4315` (_process_single_video WeChat 退出码 6 处理)
- `src/video_processing/core/wechat_session_lock.py:1-50` (2026-09-19 新增浏览器会话共享锁)
- `src/web/app.py:550-565,842-856,2128-2174` (队列轮询消费 get_high_score_pending_videos 与 guard reason)
- `scripts/wechat_uploader.py:118-120,2590-2625` (EXIT_SUBMITTED_FOR_REVIEW = 6 定义与返回)
- `tests/fixtures/golden_replay/scenarios/GOLDEN-WF-01/` (待修正的 DISCOVERY fixture 与 contract)
- `docs/refactor/video-processing/adversarial_red_blue_game_2026-09-20.md` (红蓝对抗博弈推演报告)

行号是 2026-09-20 静态快照校准，开工时应以当前源码重新定位。

首批安全修复验收后，才评估纯 Runner/context/checkpoint 提取、`PipelineDB` 外部 Facade 下的内部领域拆分，以及 WC/DY/KS publication 的分平台迁移；这些工作必须另建或解锁工单，不因“继续北辰重构”自动获得授权。

## 8. 下次最短提示词

> 继续北辰重构。按 `VP-POLARIS` 工单从第一个未完成项开始；先复核现场，再实施，不做任何真实外部操作。
