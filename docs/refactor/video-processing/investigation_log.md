---
created_by: Gemini_3.8_Flash_planning
created_at: 2026-09-12
last_updated_at: 2026-09-12
version: 1.5.0
---

# Video-precessing 架构调查与治理日志 (Investigation & Governance Log)

## Version History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.5.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.2 阶段启动：M6.1 特征化基线正式签署完结，启动可执行黄金回放数据集 (Golden Replay Dataset) 建设与离线回放验证 |
| 1.4.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.1D 阶段升级：记录独立防线去重审计，分离 Fact 与 Defense，消除微信与快手防线重复计算，多维重塑控制族矩阵 |
| 1.3.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.1C 阶段升级：记录防线资格准入审计，区分 Publication Safety 与 Supporting Control，确立快手候选过滤断言缺失及 INV-003 降级为 PARTIAL |
| 1.2.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.1B 阶段升级：记录语义完整性审计、UNIQUE 约束分类校准、候选过滤与凭据守卫平台适用性、INV-001 降级理由纠偏及 M6.5A 路线收敛 |
| 1.1.1 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.1A 阶段升级：记录不变式双轨矩阵校准、INV-008 生产违规确认、INV-006 语义与可达性审计、消除 M6.5 治理路线冲突 |
| 1.1.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.1 阶段升级：记录特征化测试基线建立、INV-001~INV-008 覆盖矩阵与沙盒隔离验证证据 |
| 1.0.0-rc3 | 2026-09-12 | Gemini_3.8_Flash_planning | M5.1 阶段升级：记录风险语义核验（DEFINE RISK-DB-002/PIPE-002, RETIRE RISK-STATE-002）、兼容性信封调用方验证及完整性审计 |
| 1.0.0-rc2 | 2026-09-12 | Claude_Opus_4.6_planning | 自审修复：修正 `claim_next_douyin_publication` 行号漂移 (L8989→L8958)、frontmatter 时间戳 |
| 1.0.0-rc1 | 2026-09-12 | Gemini_3.8_Flash_planning | M5 阶段升级：沉淀治理校准事实（恢复协议、INV-006、INV-008、标准化风险与 UNK 处置） |
| 0.1.0 | 2026-09-12 | Gemini_3.8_Flash_planning | 沉淀 M1-M4 调查全过程与命题证据审计 |

---

## 📌 调查方法与证据标准

本调查基于仓库内建 AST 与静态调用拓扑图谱（Graft 索引），结合精准源码定位与 `git grep` 验证。所有结论严格遵循四级证据状态标记：
- **[CONFIRMED]**：已有明确源码实现、调用边或测试断言直接证实。
- **[INFERRED]**：基于代码逻辑与设计模式作出的强逻辑推导，尚待更完整运行时追踪验证。
- **[UNKNOWN]**：缺乏充分静态或动态证据，严禁推论。
- **[RETRACTED]**：此前曾做出的推断被后续确凿源码推翻，正式废弃并记录原因。
- **[CALIBRATED]**：前期定性或命名经深化分析后进行精确校准，消除歧义与不完备性。

---

## 阶段一：M1 — Repo Topology & Global Hotspots

### 调查事实记录
- **代码库规模 [CONFIRMED]**：464 个源文件，4,317 个符号定义，12,597 条静态调用边（涉及 Python, JavaScript）。
- **全局核心热点 (Top Hotspots) [CONFIRMED]**：
  1. [`get_connection`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/db/database.py#L225) (236← 入度)：底层 SQLite 连接池与事务生命周期上下文。
  2. [`PipelineDB`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/db/database.py#L166) (207← 入度)：DAL 数据访问层单点类，全库唯一允许执行原生 SQL 的构件。
  3. [`get_video_by_youtube_id`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/db/database.py#L5054) (74← 入度)：视频及切片状态的主键检索。
  4. [`add_video`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/db/database.py#L2605) (58← 入度)：候选视频入库录入。
  5. [`PipelineManager`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/pipeline_manager.py#L486) (57← 入度)：主流程有限状态机（FSM）总调度器。
  6. [`update_video_status`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/db/database.py#L2830) (54← 入度)：主表任务状态变迁原子操作。
  7. [`create_douyin_publication`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/db/database.py#L8210) (31← 入度)：抖音发布账本记录登记。

---

## 阶段二：M2 — Boundary Audit & DAL Boundary Analysis

### 调查事实记录
- **核心业务层 DAL 边界完整性 [CONFIRMED]**：
  对 `src/` 目录执行 `git grep "get_connection"`，所有 124 处命中**全部严格位于** `src/video_processing/db/database.py` 内部；核心领域（Web 控制台、Telegram Bot、各视频处理器）**零违规**。
- **运维脚本层 DAL 违规现象 [CONFIRMED]**：
  1. [`scripts/backfill_metadata.py:L12,L41`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/scripts/backfill_metadata.py#L12)：直接调用 `db.get_connection()` 并在外部执行原生 `SELECT` 与 `UPDATE`。
  2. [`scripts/regen_published_covers.py:L14`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/scripts/regen_published_covers.py#L14)：直接调用 `db.get_connection()` 执行原生 `SELECT`。
  3. `scripts/cleanup.py`、`scripts/daily_ops_report.py`、`scripts/session_ip_probe.py` 绕开 `PipelineDB`，自行通过 `sqlite3.connect` 打开数据库。
  - **定性判定**：DAL 边界整体定性为 **DAL boundary partially violated**（业务核心层坚固，脚本工具层存在局部泄露）。
- **PipelineDB 架构定性校准 [CALIBRATED]**：
  - *修正前*：盲目归类为 “CRITICAL God Class”。
  - *修正后 [CONFIRMED]*：更准确地记录为 **“具有多个内部高度自洽领域集群的高维护债务 Facade 单体”**。其内部涵盖 DB 生命周期、微信账本、抖音账本、快手账本、高光剪切、英语世界、配音重制等 10 余个自闭环业务域，表结构划分清晰，未出现大面积不可解耦的交织网。

---

## 阶段三：M3 — State Authority & Consistency Risk Map

### 调查事实记录
- **主表状态角色定位 [CONFIRMED]**：
  `processed_videos.status` 是**工作流调度与本地进度（Workflow State）的投影**，并非外部平台最终发布的真实源头。
- **平台发布账本角色定位 [CONFIRMED]**：
  `wechat_publications`、`douyin_publications`、`kuaishou_publications` 是记录外部平台行为、原生 `post_id` 与合规证据的**法律级客观事实账本（Source of Truth）**。
- **状态写入权限分散性 [CONFIRMED]**：
  `processed_videos.status` 存在 5 个独立写入源（FSM 引擎、FastAPI Web 路由、后台对账 Worker、审查服务、Telegram Bot），系统缺乏统一的状态机跃迁实体。
- **外部重复发布防线评估 [CONFIRMED]**：
  支持的生产路径包含多层强幂等与防重发设计：
  - 微信：SQL 层 `NOT EXISTS (wechat_publications)` + 磁盘提交截图 `_block_duplicate_wechat_submission_if_needed`。
  - 抖音：`asset_sha256` 排重 + 一次性启动凭据 `douyin_browser_launch_tickets`。
  - 快手：`WHERE (video_id = ? OR asset_sha256 = ?)` 强拦截。
  - 结论：仅重置主表为 `PENDING` 并不会轻易引发外部重复投稿。

### 历史命题审计与推断撤回
- **[POTENTIAL / UNCONFIRMED] `_init_db` 是否存在已观察到的死锁风险？**
  - *核实*：测试 `test_db_deadlock_purger` 实质测试的是任务超时回收（`purge_stale_tasks`），非数据库引擎锁。无任何测试或日志证实生产环境曾发生 `_init_db` schema lock。该项标记为高并发初次启动时的理论潜在风险。
- **[CONFIRMED] `repair_wechat_submission_status_divergence` 的性质？**
  - *核实*：测试用例 `test_submission_acceptance_is_atomic_and_repairs_prior_status_divergence` 明确注释为“模拟旧版本在账本后崩溃”，该方法是专门用于兜底“上传器已完成平台提交但进程在更新主表前瞬态崩溃”的**防御性架构不变式对账修复**。
- **[RETRACTED] `create_douyin_publication` 是否消耗投稿配额？**
  - *原推断*：创建抖音记录会消耗配额。
  - *撤回原因*：查验源码 [`database.py:L8210-L8259`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/db/database.py#L8210)，`create_douyin_publication` 仅向表内写入 `state='QUEUED'`；配额校验（`used >= daily_limit`）严格位于 [`claim_next_douyin_publication:L8958`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/db/database.py#L8958) 的任务领取逻辑中。

---

## 阶段四：M4 — Natural Seams & Migration Units

### 调查事实记录
- **副作用分类（Side-effect Taxonomy）[CONFIRMED]**：
  全系统逻辑自然归为：PURE READ（只读查询）、DECISION（无写决策）、PERSISTENCE（纯本地 DB 写）、LOCAL SIDE EFFECT（文件转码/删除）、EXTERNAL SIDE EFFECT（平台发布/网络 I/O）。
- **自然接缝识别（Natural Seams）[CONFIRMED]**：
  - PipelineDB 内部：抖音、快手、高光、英语世界等模块独享物理表，具备在不修改现有 public API 的情况下做内部委托（Internal Delegation）的天然接缝。
  - 不可拆分核心：`record_wechat_submission_acceptance` 涉及 3 表原子写入，属于强事务交织区，严禁轻率解耦。
- **PipelineManager 阶段界限 [CONFIRMED]**：
  `_process_single_video`（约 1k 行，2026-09-12 静态快照观测为 L3268-L4280）在逻辑上严格被 8 个磁盘检查点切分（Download, Slice, Copywriting, Transcribe/Render, Censorship, Cover, Window Gate, Publishing）。
- **控制面转换定性 [CONFIRMED]**：
  - Web 端操作（retry, reset-hard, stop, bypass, login-restore）均内置了 `_wechat_submission_guard_reason` 账本保护，属于**受控合法控制面转换**。
  - Telegram Bot [`src/bot/pipeline_agent.py:L714,L749`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/bot/pipeline_agent.py#L714) 缺失前置保护，直接覆写状态，属于**无约束状态修改（Unconstrained Mutation）**。

---

## 阶段五：M5 — Detailed Refactor Handoff v1.0 & Governance Calibrations

### 治理事实校准记录

1. **恢复协议校准 [CALIBRATED]**：
   - *修正前*：依赖“工单优先级（P0/P1/P2）”挑选工单实施。
   - *修正后*：确立严格的“Gate 驱动恢复协议”：`Read 00_README -> Identify Phase -> Complete mandatory Gate -> Execute explicitly UNBLOCKED WOs`。当前处于 M5 阶段，所有运行时工单（含 P1 的 `WO-STATE-001`）一律处于 `BLOCKED` 状态，必须完成 Gate M5 验收并建立 Gate M6 安全 Harness 后方可解锁。

2. **INV-006 语义校准 [CALIBRATED]**：
   - *修正前*：命名为 “Read-Only Reconciliation Must Not Generate Publication Side Effects”，易产生“对账 Worker 纯只读、不写任何东西”的错误理解。
   - *修正后*：重命名并校准为 **`INV-006 — Reconciliation Must Be Publication-Side-Effect-Free`**。明确后台对账允许且必须执行本地数据持久化（更新本地发布账本、同步主表工作流状态投影、记录审计日志），但**绝对不能产生任何外部平台发布动作（无新投稿、无媒体重传、无浏览器唤起、无 Ticket 消耗）**。

3. **INV-008 行为契约校准 [CALIBRATED]**：
   - *修正前*：偏向静态代码级假定“所有 Web 接口都共用一个简单 helper 函数”。
   - *修正后*：确立为行为级的安全防御契约：**`INV-008 — Control Plane Destructive/Retry Operations Must Fail Closed on Existing Publication Evidence`**。无论是 Web 端还是 Telegram Bot，凡涉及破坏性重试、硬重置或重跑的控制面入口，在检测到已有发布事实或在途状态时，必须统一 Fail-Closed 拒绝重发。

4. **风险字段标准化 [STANDARDIZED]**：
   - 全系统已知风险项与工单的风险属性统一按 6 个标准化维度进行结构化固化：`Severity`、`Likelihood`、`Evidence confidence`、`Current mitigation`、`Related invariant`、`Related work order`。

5. **已知未知项处置分级 (Known Unknown Triage) [TRIAGED]**：
   - `UNK-001`（同进程异步改造对事件循环压力）：维持子进程隔离基线，仅在测试沙箱压测。
   - `UNK-002`（无头浏览器反爬与弹窗恢复）：在 M6 建立 Mock 注入套件。
   - `UNK-003`（容器化 Docker/K8s 下进程组信号穿透）：定级为 **DEFERRED / CONDITIONAL**（当前线上为宿主机原生运行，近期无容器化规划，条件触发时再评估）。

---

## 阶段六：M5.1 — Documentation Integrity Pass & Referential Audit

### 治理事实校准与完整性审计记录

1. **悬空风险语义核验与正式定义 (E-001 Verification & Resolution) [CONFIRMED & DEFINED]**：
   - **`RISK-DB-002` (运维脚本绕过 DAL 直接执行原生 SQL)**：
     - *核验*：`WO-SCRIPTS-001` 解决的是 `scripts/backfill_metadata.py:L12,L41` 与 `scripts/regen_published_covers.py:L14` 直接调用 `db.get_connection()` 执行原生 SQL，违反项目工程宪法 DAL 封装约束。这与微信三表原子性的 `RISK-DB-001` 属于完全不同的物理表与逻辑域，不能混为一谈。
     - *决策*：**DEFINE**。在权威风险登记表中正式定义 `RISK-DB-002`，状态为 `ACTIVE`，严重度 `MEDIUM`，由 `WO-SCRIPTS-001` 解决。
   - **`RISK-PIPE-002` (复杂只读查询重构存在数据投影漂移风险)**：
     - *核验*：`WO-SHADOW-001` 针对的是 `PipelineDB.get_paginated_videos:L4587` 达 98 行的多表动态联表分页查询。对其重构若缺乏生产真实流量的影子比对，易引发分页漂移或数据漏显。这与核心状态机 1k 行混编的 `RISK-PIPE-001` 存在不同的影响范围与验证策略。
     - *决策*：**DEFINE**。在权威风险登记表中正式定义 `RISK-PIPE-002`，状态为 `ACTIVE`，严重度 `LOW`，由 `WO-SHADOW-001` 在 Gate M7 通过 Shadow Mode 解决。

2. **RISK-STATE-002 生命周期归档 (Lifecycle History Tracking) [RETIRED]**：
   - *核验*：旧版提出的 `RISK-STATE-002`（主状态写入源多头化且缺乏统一状态机契约）在 M3 属于定性描述。经 M4/M5 深入分析，除 Telegram Bot 之外的写入源均具备既有校验；未受控入口已由 `RISK-STATE-001`（工单 `WO-STATE-001`）精确继承承接；状态机顶层冲突由 `INV-001` 与 `INV-008` 封顶；长远调度重构由 `WO-PIPE-001` 负责。
   - *决策*：**RETIRED**。在权威风险登记表“退役风险与历史记录”专节中完整保留历史背景、退役理由与继承关系，避免历史编号静默消失，同时确保活跃风险均有清晰的工单对应。

3. **Compatibility Envelope 外部入口源码调用方核验 (E-002 Resolution) [CONFIRMED]**：
   - *核验*：全面检索全库 caller，确认不存在 `process_video()` 与 `retry_failed_video()`。
   - *证实有效入口*：
     - `run_daily_job()`：被 `scripts/run_publication_window.py:L184` 及模块 CLI 入口 `pipeline_manager.py:L4388` 调用。
     - `run_preparation_job()`：被 `scripts/run_background_preparation.py:L28` 调用。
     - `reset_video_artifacts(prefix)`：被 `src/web/app.py:L2731,L2830,L2931` 与 `src/bot/pipeline_agent.py:L732` 调用。
     - `process_high_score_videos(limit)`：被 `run_daily_job()` 及调度测试调用。
     - `recover_deferred_wechat_publications()`：被 `run_daily_job()` 调用。
   - *决策*：以“现有外部调用方依赖的稳定公共入口（existing externally-used PipelineManager entry points）”为契约承诺基础，彻底清除虚构符号。

4. **引用完整性全局审计 (Referential Integrity Audit) [CONFIRMED 100% PASS]**：
   - `INV-001` ~ `INV-008`：定义 8 个，引用 8 个，悬空 0。
   - `RISK-xxx`：活跃 6 个，退役归档 1 个，引用完全对齐权威登记表，悬空 0。
   - `UNK-001` ~ `UNK-003`：定义 3 个，引用 3 个，悬空 0。
   - `WO-xxx`：定义 7 个，引用 7 个，全量标记为 `BLOCKED`，悬空 0。
   - 重复权威定义：0。

---

## 阶段七：M6.1 — Characterization Baseline & Invariant Harness

### 1. 目标与执行纪律
- **核心原则**：Protect existing behavior before improving implementation.
- **约束落实**：0 行生产运行时修改；0 个 Work Order 解锁；0 外部网络调用。
- **产出交付**：
  - 新增特征化测试套件：[`tests/unit/test_characterization_baseline.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/tests/unit/test_characterization_baseline.py)
  - 新增特征化场景矩阵与黄金场景清单：[`characterization_matrix.md`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/refactor/video-processing/characterization_matrix.md)
  - 新增安全基线与不变式防护网：[`safety_harness.md`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/refactor/video-processing/safety_harness.md)

### 2. 八大系统不变式覆盖与验证事实
- **INV-001 (工作流状态非客观发布事实)**：覆盖切片复合主键独立生命周期与状态分叉可自动修复性。
- **INV-002 (凭据优于推断与关停防线)**：确证物理截图凭据与未删除账本阻断二次调度与重置。
- **INV-003 (多层级防御纵深幂等)**：确证候选过滤、在途领取、凭据校验、并发锁等多层防线。
- **INV-004 (媒体指纹 asset_sha256 强排重)**：确证成片哈希在多平台账本中防止跨视频 ID 重复投递。
- **INV-005 (单次使用浏览器凭据语义)**：确证 `begin_douyin_browser_launch` 负向拦截（虚假 ticket、篡改 token、篡改 payload、二次重放）。
- **INV-006 (对账只读无害性)**：确证在真实 SQLite 上未决对账零副作用，不改变凭据或状态。
- **INV-007 (微信提交受理三表原子变更)**：通过 SQLite 触发器注入中间异常，确证单一事务失败时三张表完整回滚，零残留。
- **INV-008 (控制面状态变更 Fail-Closed)**：确证 Web 控制面 `/reset-hard` 在有提交账本时拒绝重置。
- **RISK-STATE-001 (已知风险不安全基线)**：确证当前 `PipelineDB.update_video_status` 缺乏账本检查的缺陷事实，正确归类为 `KNOWN-UNSAFE-BASELINE`。

### 3. 沙盒隔离测试执行凭证
- 命令：`.venv/bin/python scripts/run_isolated_tests.py -- -q tests/unit/test_wechat_publications.py tests/unit/test_douyin_publications.py tests/unit/test_kuaishou_publications.py tests/unit/test_characterization_baseline.py`
- 结果：**66 passed, 0 failures** (耗时 3.55s)。
- 运行凭据：`/private/tmp/video-pytest-6tjx8wfu/receipt.json`

---

## 阶段八：M6.1A — Invariant Coverage Calibration & Evidence Audit

### 1. 审计动因与执行纪律
在 M6.1 建立初始测试套件后，由 Gemini 执行模型开展对抗性独立审计。
核心审计原则：**“任何已有的 COVERED 标签都视为待证明命题，而不是既定事实。”**
严格实行生产运行时代码零修改（0 runtime changes）、零工单提前解锁。

### 2. 双轨矩阵与关键不变式严重纠偏
1. **确立生产满足度与测试覆盖度双轨评估**：
   - 彻底废除将“测试通过”直接等同于“生产满足不变式”的简单归纳。
2. **INV-008 严重纠偏 (KNOWN-VIOLATION 确认)**：
   - 生产满足度评定为 **`KNOWN-VIOLATION`**。
   - 事实：虽然 Web 控制面（`/reset-hard`, `/retry`）实现了 Fail-Closed 拦截，但 Telegram Bot 的 `PipelineAgent.retry_video_in_db` 与 `update_video_status` 直接调用无状态锁 DAL 覆盖写入 `PENDING`，绕过账本防护。
   - 测试覆盖度降级为 **`PARTIAL`**（`test_characterization_baseline.py` 捕获了该已知不安全基线，但由于生产违规未消除，不变式整体不成立）。
3. **INV-006 语义与可达性校准 (Publication-Side-Effect-Free)**：
   - 纠正误导性词汇“对账只读无害”，更正为“**对账零发布端副作用 (Publication-Side-Effect-Free)**”——明确允许本地状态更新与审计写入，严禁外部发帖调用与凭据消耗。
   - 跨平台可达性审计证实：三大平台对账方法均硬编码 `--verify-only`，不可达发帖路径；但因抖音与快手单测依赖 Mock DB，测试覆盖度从 COVERED 降级为 **`PARTIAL`**。
4. **INV-001 证据剔除与范围校准**：
   - 明确指出 M6.1 将“切片生命周期测试”作为 INV-001 证明属于概念错配。
   - 确立核心证据体系：Evidence A（状态分叉共存）、Evidence B（非主状态依赖重试决策）、Evidence C（账本优先于主状态并可自动纠偏）。测试覆盖度降级为 **`PARTIAL`**。
5. **INV-004 / INV-005 平台特定范围确立**：
   - 澄清 `INV-004` (成片 SHA256 排重) 仅适用于抖音与快手，微信无对应字段（`NOT APPLICABLE`）。
   - 澄清 `INV-005` (单次浏览器凭据) 仅适用于抖音，微信与快手无 Ticket 机制（`NOT APPLICABLE`）。

### 3. 治理路线图冲突消除 (Phase M6.5 正式确立)
- 消除 M5 Handoff 中“Gate M6 退出直接进入 M7 影子模式”与“M6 期间修复 WO-STATE-001”的冲突。
- 正式确立治理流转序列：
  `Gate M5 签署 -> Phase M6 (Safety Harness only) -> Gate M6 → M6.5 -> Phase M6.5 (First Guarded Remediation: 实施 WO-STATE-001 / WO-SCRIPTS-001) -> Gate M6.5 → M7 -> Phase M7 (Shadow Mode)`。
- 在 Gate M6.5 完成前，所有 7 项重构工单保持严格 **`BLOCKED`**。

---

## 阶段九：M6.1B — Semantic Integrity Pass

### 1. 语义审计目标与执行纪律
在 M6.1A 证据校准的基础上，展开高度收敛的**语义完整性审计**。
目标：核验现有 coverage matrix 中每一层“防线”的名称是否与其真实底层语义一致，防止将 identity constraint、queue dedup、candidate exclusion、evidence capture 等异质机制混淆为通用的 publication idempotency。
坚持 0 runtime changes，0 生产侵入。

### 2. INV-003 六层防线语义与边界精确界定
1. **Candidate Exclusion (候选过滤)**：在进入平台发布流程前，由调度 SQL 查询（`NOT EXISTS`）直接将已有 publication 的视频从候选集中过滤。
2. **Queue / Ledger Dedup (队列/账本排重)**：在调用 `create_*_publication` 入队/登记时，基于 `video_id` 或 `asset_sha256` 检查既有账本，返回旧记录或拒绝插入新记录。
3. **Attempt Identity Integrity (尝试身份唯一性)**：数据库对 `(video_id, attempt_number)` 的唯一约束，仅确保同一次尝试的物理行唯一，**绝对不能阻止针对同一视频创建后续尝试（如 attempt 2）**，不能单独等同于防重复发布。
4. **Asset Identity Dedup (成片媒体指纹排重)**：跨尝试、跨视频比对成片二进制 SHA256，阻止相同媒体重复投递。微信无此字段（N/A）。
5. **Execution Authorization (执行授权/租约机制)**：拉起外部浏览器前的原子领取锁（Claim）或单次有效防篡改临时凭据（One-Time Ticket/Lease）。微信无此机制（N/A），快手仅有 Claim，抖音兼具 Claim 与 Ticket。
6. **External Submission Guard (外部提交前置硬阻断)**：调用外部上传器 CLI 前检测本地磁盘物理截图证据，若存在则主动熔断并阻止拉起浏览器。经源码核验，**仅微信通道具备此活跃机制 (`_block_duplicate_wechat_submission_if_needed`)**；抖音与快手截图仅作为 `DIAGNOSTIC SCREENSHOT` 与 `AUDIT EVIDENCE`，无前置磁盘扫描阻断。

### 3. 真实数据库 UNIQUE 约束特别审计
- **WeChat (`wechat_publications`)**:
  - DDL: `video_id INTEGER DEFAULT NULL UNIQUE`, `subject_id TEXT NOT NULL UNIQUE`
  - 判定: **True Single-Publication-Per-Video Unique Constraint**。单视频物理唯一，真正承担 Publication Dedup 职责。
- **Douyin (`douyin_publications`)**:
  - DDL: `UNIQUE(video_id, attempt_number)`
  - 判定: **Attempt Identity Integrity**。允许 `(video_id=1, attempt=1)` 与 `(video_id=1, attempt=2)` 并存，防止尝试序号内部冲突，不独立防止重复发布。
- **Kuaishou (`kuaishou_publications`)**:
  - DDL: `UNIQUE(video_id, attempt_number)`
  - 判定: **Attempt Identity Integrity**。同抖音。

### 4. 候选过滤 (Candidate Exclusion) 跨平台审计
- **WeChat**: `PipelineDB.get_high_score_pending_videos` (Lines 4130-4134: `NOT EXISTS (SELECT 1 FROM wechat_publications ...)`), 调度前执行, 位于行创建之前 (`CONFIRMED`)。
- **Douyin**: `PipelineDB.get_unqueued_douyin_new_videos` (Lines 8948-8950: `NOT EXISTS (SELECT 1 FROM douyin_publications ...)`), 批次排队前执行, 位于行创建之前 (`CONFIRMED`)。
- **Kuaishou**:
  - 历史迁移路径: `PipelineDB.get_unqueued_kuaishou_history_videos` (Lines 8039-8041: `NOT EXISTS ...`), 位于行创建前 (`CONFIRMED`)。
  - 新视频发布路径: `_dispatch_kuaishou_new_video` 由微信发布事件直接驱动，直接调用 `create_kuaishou_publication`，**无独立候选过滤查询 (`NOT APPLICABLE`)**。其防重第一道防线为下一层的 Queue / Ledger Dedup。

### 5. 凭据守卫 (Evidence Guard) 跨平台审计
- **WeChat**: `PipelineManager._block_duplicate_wechat_submission_if_needed` 检测本地 `post_list_after_submission.png` 截图，发现后主动退出并不启动上传器。判定为 **`FAIL-CLOSED SUBMISSION GUARD`** (`CONFIRMED`)。
- **Douyin**: `douyin_uploader.py` 捕获 `douyin_management_evidence.png` 等截图。流水线在调用上传器前不读取磁盘截图做前置拦截。判定为 **`DIAGNOSTIC SCREENSHOT / AUDIT EVIDENCE`** (作为前置阻断防线标为 `NOT APPLICABLE`)。
- **Kuaishou**: `test_kuaishou_review_evidence_blocks_duplicate_submission` 本质是在 DB 层解析 `error_message` 包含“审核中”并将账本置为 `UNDER_REVIEW`，进而通过 `asset_sha256` 阻止二次入队，未扫描磁盘截图文件。判定为 **`DIAGNOSTIC SCREENSHOT / AUDIT EVIDENCE`** (作为前置阻断防线标为 `NOT APPLICABLE`)。

### 6. INV-001 降级理由纠偏
- 核心要求：关注 **Authority Semantics**（账本优先于投影、决策优先于主状态、分叉后可修复），而非平台是否必须拥有双向自动对账。
- WeChat: 已有真实 SQLite 测试断言，证明当主状态分叉为 `DOWNLOADING` 或 `PENDING` 时，发布决策不重发且对账可自动修复为 `PUBLISHED`。
- Douyin & Kuaishou: 具备账本防重逻辑，但尚未建立针对“主状态被篡改/分叉后，派发决策依然严格优先账本”的显式特征化单测断言。
- 结论：降级理由更正为缺少抖音/快手通道针对 Authority Semantics 的显式特征化单测断言，维持 **`PARTIAL`**。

### 7. 路线图进一步收敛：Phase M6.5A
- 为防止首次运行时安全修复引入过大改动，将 M6.5 收敛为单一工单实施：
  - **`Phase M6.5A — First Guarded Remediation`**：仅解锁并实施 **`WO-STATE-001`** (Telegram Bot 状态防篡改校验加固)。
  - **`Phase M6.5B — Operational Scripts DAL Encapsulation`**：对 `WO-SCRIPTS-001` 实施条件评估，必须在 M6.5A 彻底通过契约测试、基线转换、回滚验证与零回归审计后，方可评估是否解锁。
- 现已全量同步至所有治理文档。

### 8. Receipt 内部计数一致性核准
- 消除声明计数与实际列表不符的问题：
  - Invariant 总量：**8 项** (`INV-001` ~ `INV-008`)。
  - 生产满足度 (Production Satisfaction)：
    - **SATISFIED (7 项)**: `INV-001`, `INV-002`, `INV-003`, `INV-004`, `INV-005`, `INV-006`, `INV-007`
    - **KNOWN-VIOLATION (1 项)**: `INV-008`
    - 7 + 1 = 8 项，声明计数与列表绝对一致。
  - 测试覆盖度 (Test Coverage)：
    - **COVERED (5 项)**: `INV-002`, `INV-003`, `INV-004`, `INV-005`, `INV-007`
    - **PARTIAL (3 项)**: `INV-001`, `INV-006`, `INV-008`
    - 5 + 3 = 8 项，声明计数与列表绝对一致。

---

## 阶段十：M6.1C — Publication Defense Qualification Audit

### 1. 审计动因与资格准入原则
在 M6.1B 语义审计的基础上，展开收敛性的**发布防线资格准入审计 (Publication Defense Qualification Audit)**。
核心原则：
1. **防线准入严格两分法**：只有机制失败与否会直接改变一个已存在/在途/等价内容的视频是否可能再次跨越外部投稿边界（启动上传器、投递媒体、消耗凭据）的机制，才能计入 **Publication Safety Defense**。
2. **辅助控制剥离防线计数**：仅负责保证物理行身份唯一、提供诊断截图、记录审计日志或保证本地事务原子性的机制，正式归类为 **Supporting Integrity Control**，明确不得计入防重防线层数。
3. **消除虚幻故障域概念**：彻底废除“Failure Domains”主观度量，替换为具体的**共享依赖分析 (Shared Dependencies & Common-Mode Failure Analysis)**。
4. **源码实现与测试覆盖分离证明**：源码具备机制标记为 `Source implementation: CONFIRMED`；但若缺乏断言覆盖，则必须诚实记录 `Test coverage: MISSING/PARTIAL`。

### 2. INV-003 机制资格两分法
- **Publication Safety Defenses (计入防线)**：
  - **Candidate Exclusion (调度候选过滤)**：SQL `NOT EXISTS` 阻断已发/在途视频进入候选集。
  - **Ledger Dedup / Active Publication Identity (账本/入队/活跃投影排重)**：入库或登记时拦截，阻止创建重复发布任务。
  - **Asset SHA256 Dedup (成片指纹排重)**：跨尝试、跨视频阻止相同成片二进制重复投递（仅抖音/快手）。
  - **Execution Authorization (Claim / Ticket)**：原子领取租约与单次有效时效凭据（快手 Claim，抖音 Claim + Ticket）。
  - **Fail-Closed Submission Guard (前置提交阻断)**：检测物理证据截图硬熔断阻断拉起上传器（仅微信）。
- **Supporting Integrity Controls (剥离防线计数)**：
  - **Attempt Identity Integrity (`UNIQUE(video_id, attempt_number)`)**：抖音与快手主表约束，仅保证同一次尝试的物理行唯一，不能阻止后续尝试创建。
  - **Audit Trail Records (`wechat_submission_attempts`)**：微信提交日志，仅用于事后审计排查。
  - **Diagnostic Screenshots**：抖音与快手上传器完成后的诊断截图与视觉存证。
  - **SQLite Transaction Rollback**：底层事务原子性，保证失败时不留脏数据。

### 3. 快手候选过滤测试实证审计 (Honest Audit)
- **源码审查 (`PipelineDB.get_unqueued_kuaishou_history_videos`)**：
  - L8039-8041 包含 `NOT EXISTS (SELECT 1 FROM kuaishou_publications kp WHERE kp.video_id = pv.id)` 明确过滤。
  - 源码结论：**`Source implementation: CONFIRMED`**。
- **现有测试断言审查 (`tests/unit/test_characterization_baseline.py`)**：
  - 函数 `test_history_candidates_only_include_wechat_published_and_non_blacklisted`:
    - ARRANGE: 插入若干测试视频，其中包含未发布、已发布但未加黑、已加黑等视频。**未插入任何 `kuaishou_publications` 记录！**
    - ACT: 调用 `get_unqueued_kuaishou_history_videos()`。
    - ASSERT: 仅断言过滤了 `status != 'PUBLISHED'` 及黑名单视频。**没有任何断言验证“既有快手发布记录会过滤候选”！**
  - 函数 `test_history_claim_respects_daily_limit_and_uncertain_never_requeues`:
    - 仅测试 `claim_next_kuaishou_history_publication`，完全未调用 `get_unqueued_kuaishou_history_videos`。
  - 测试结论：**`Test coverage: MISSING`**。

### 4. 微信数据模型与术语校准
- 微信通道无异步 Worker 队列，其状态由 `PipelineManager` 直接驱动。
- `PipelineDB.record_wechat_submission_acceptance` 依赖 `wechat_publications.video_id UNIQUE` 约束执行 `ON CONFLICT(video_id) DO UPDATE`。
- 术语纠偏：原“Queue / Ledger Dedup”修正为 **`Active Publication Identity & Projection Guard`**，反映其作为微信活跃发布投影唯一性防线的本质。

### 5. INV-003 评定与降级记录 [HISTORICAL / CALIBRATED IN M6.1D]
- **生产满足度 (Production Satisfaction)**：**`SATISFIED`**。
  - *(注：以下 3 层/4 层表述为 M6.1C 历史记录，在 M6.1D 独立防线审计中已校准为多维控制族与保护维度，消除了 Fact 与 Defense 的重复计算)*。
  - 微信：3 层发布防线 (Candidate Exclusion, Active Publication Identity, Fail-Closed Guard) `[CALIBRATED IN M6.1D]`。
  - 抖音：4 层发布防线 (Candidate Exclusion, Ledger Dedup, Asset SHA256, Claim + Ticket) `[CALIBRATED IN M6.1D]`。
  - 快手：历史 4 层 / 新视频 3 层发布防线 (Candidate Exclusion[历史], Ledger Dedup, Asset SHA256, Worker Claim) `[CALIBRATED IN M6.1D]`。
- **测试覆盖度 (Test Coverage)**：从 COVERED 降级为 **`PARTIAL`**。
  - 降级原因：快手候选过滤测试 (`test_history_candidates_only_include_wechat_published_and_non_blacklisted`) 缺失对“既有快手发布记录排除候选”的直接断言。

### 6. 共享依赖与共模失效分析 (Common-Mode Analysis)
各通道防线虽在不同生命周期生效，但存在以下共享依赖与共模绕过风险：
1. **绕过入口共模风险**：若直接调用 `wechat_uploader.py` / `douyin_uploader.py` 等底层 CLI，将直接绕过所有调度与 DAL 防线（仅微信在特定物理截图存在时有本地补救阻断）。
2. **状态重置共模风险 (`RISK-STATE-001`)**：Bot 等控制面直接调用无校验 DAL 重置主状态，可能导致某些生命周期保护失效。
3. **重新渲染指纹漂移风险**：若视频重新渲染生成新文件，SHA256 改变将使 Asset SHA256 排重失效。

### 7. 契约计数一致性确认 [HISTORICAL / CALIBRATED IN M6.1D]
- 8 大不变式双轨状态：
  - 生产满足度 (Production Satisfaction): 7 SATISFIED (`INV-001` ~ `INV-007`) + 1 KNOWN-VIOLATION (`INV-008`) = 8 项。
  - 测试覆盖度 (Test Coverage): 4 COVERED (`INV-002`, `INV-004`, `INV-005`, `INV-007`) + 4 PARTIAL (`INV-001`, `INV-003`, `INV-006`, `INV-008`) = 8 项。

---

## 阶段十一：M6.1D — Independent Defense & Double-Counting Audit

### 1. 审计动因与准入三要素
在 M6.1C 防线合格性审计后，针对“是否把同一底层数据事实拆分为多条独立防线重复计算”展开**收敛性去重与独立性审计 (Independent Defense & Double-Counting Audit)**。
核心准入三要素：
1. **Prevention relevance**：该机制实际参与阻止已存在、在途或等价内容再次跨越外部 publication boundary。
2. **Enforcement point**：存在真实代码路径在外部提交前使用该机制进行 allow/deny 或 candidate inclusion/exclusion。
3. **Failure independence**：不能只是另一个已计入机制所使用的同一个事实或同一个判断的重复命名。

### 2. Publication Fact ≠ Publication Defense 原则确立
- **Publication Fact (发布事实)**：已发生/已受理发布的本地客观权威记录（如数据库 `wechat_publications` 物理行、文件系统 `post_list_after_submission.png` 截图）。Fact 本身是静态持久化状态，不主动执行代码拦截。
- **Publication Defense (发布防线)**：在代码执行入口（Enforcement Point）主动读取 Fact/Evidence，并执行 `allow / deny`、`include / exclude`、`claim / reject` 或强行终止进程的动态判定逻辑。
- **治理铁律**：一个 Fact 可以被多个 Enforcement Points 读取（如 `wechat_publications` 既被调度器读取，也被控制面读取）；但绝不能把 Fact 自身（如 `video_id UNIQUE` 约束）与其某一个读取入口（如 `get_high_score_pending_videos`）分别计为两条独立的发布防线。

### 3. 微信 Active Publication Identity 专项审计 (三问三答)
- **Q1: `record_wechat_submission_acceptance` / UNIQUE 约束发生在提交前还是受理后？**
  - **实证**：[`PipelineManager.py:L927`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/pipeline_manager.py#L927) 证明该方法在 `wechat_uploader.py` 执行成功并捕获到受理截图后才被调用。
  - **结论**：发生于 **External submission AFTER acceptance**，属于客观发布事实的落库操作，而非提交前主动拦截。
- **Q2: 第二次启动上传器前，是否有代码直接查询 Active Publication Identity 并据此阻止发布？**
  - **实证**：拦截重发的实际代码入口为：
    1. 调度层：`get_high_score_pending_videos` (SQL `NOT EXISTS`)
    2. 控制面：`web/app.py` (`_wechat_submission_guard_reason`)
    3. 任务生命周期门：`PipelineManager._has_wechat_submission_terminal_state` (L3322)
    4. 前置探针：`PipelineManager._block_duplicate_wechat_submission_if_needed` (L3320, L4094)
  - **结论**：`wechat_publications.video_id UNIQUE` 属于 **Supporting Authoritative Fact**，上述入口才是 **Enforcement Defenses**。
- **Q3: 若 `wechat_publications` 行被删除，两者是否同时失效？**
  - **结论**：**YES**。一旦 DB 行被删，候选过滤与所谓 Active Identity 约束同时失效。二者共享同一底层物理行，绝非独立的 Failure Controls。此前分列属于 **Double Counting**。

### 4. 微信真实防御模型重塑 (Remodeled WeChat Architecture)
放弃“微信 3 层防线”的粗暴表述，忠实映射真实架构：
- **Family A: DB Publication Fact & Lifecycle Gates** (依赖 SQLite DB 与主流程状态一致性):
  - 事实源：`wechat_publications` 数据表物理行 (`video_id UNIQUE`)。
  - 执行入口：调度候选过滤 (`get_high_score_pending_videos`)、控制面拦截 (`web/app.py`)、流程边界门 (`_has_wechat_submission_terminal_state`)。
- **Family B: Filesystem Physical Evidence & Pre-submit Guard** (完全独立于 SQLite，具备极高故障隔离性):
  - 事实源：本地磁盘物理存证截图 `post_list_after_submission.png`。
  - 执行入口：上传器前置探针 `_block_duplicate_wechat_submission_if_needed`（在 L3320 与 L4094 硬熔断，退出码 10）。

### 5. 抖音与快手去重与维度复核
- **快手 (Kuaishou)**：
  - 源码证据：[`create_kuaishou_publication:L7961`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/db/database.py#L7961) 执行 `WHERE state IN (...) AND (video_id = ? OR asset_sha256 = ?)`。
  - 结论：`video_id` 与 `asset_sha256` 是在同一个函数、同一条 SQL 中评估的。它们属于 **双重保护维度 (Protection Dimensions: Identity & Content)**，但在执行拓扑上是 **单一执行判定点 (Single Enforcement Point)**。此前拆为两条独立防线属于 Double Counting。
- **抖音 (Douyin)**：
  - 源码证据：候选过滤在 `get_unqueued_douyin_new_videos`（身份维度），指纹排重在 `create_douyin_publication`（内容维度），时效授权在 `claim_next_douyin_publication` + Ticket。
  - 结论：分属不同执行阶段，但成片指纹排重依托于 `douyin_publications` 统一物理表。

### 6. M6.1C Checklist 内部矛盾修复
- **矛盾消除**：纠正前期“每项防线均精准绑定测试断言”与快手候选过滤 `MISSING` 的字面冲突。
- **终态契约**：所有被计入的生产控制机制均已绑定确凿源码实现证据；其实行覆盖度均已显式映射为 TEST-PROVEN、PARTIAL 或 MISSING，坚决不为美化报表而掩盖测试缺失。

### 7. INV-003 最终评级
- **Production Satisfaction**: **`SATISFIED`** (双控制族与多维判定点充分生效，生产防护无漏洞)。
- **Test Coverage**: **`PARTIAL`** (快手历史候选过滤单测断言缺失，如实保持降级)。
- **Evidence Confidence**: **`HIGH`** (源码行号与测试解剖确凿，彻底消除 Double Counting)。

---

## 阶段十二：M6.2 — Executable Golden Replay Dataset

### 1. 目标与范围界定
在 M6.1 特征化测试基线签署完结后，正式启动 **M6.2 可执行黄金回放数据集 (Executable Golden Replay Dataset)** 建设。
- **核心目标**：将 M6.1 场景规范转化为具备物理文件、离线可执行、确定性回放、无外部副作用的 Golden Replay Dataset。
- **权限边界**：零生产运行时修改，零生产 Schema 调整，所有工单保持 `BLOCKED`。
- **证据纪律**：遵循 Gemini 对抗性证据纪律（Claim → Fixture Inspection → Execution → Repeat Execution → Normalized Comparison → Conclusion）。

### 2. 覆盖场景集合
以 `characterization_matrix.md` 定义的 Golden Manifest 为基准，全量固化 6 个核心场景：
1. `GOLDEN-WF-01` (CONTRACT): 标准单视频生命周期与候选过滤门禁。
2. `GOLDEN-WF-02` (CONTRACT): 长视频切片父子关系与级联流转。
3. `GOLDEN-PUB-WC` (CONTRACT & SAFETY-REGRESSION): 微信三表原子受理与本地物理截图探针熔断。
4. `GOLDEN-PUB-DY` (CONTRACT): 抖音单次时效 Token 消费语义与成片 SHA256 排重。
5. `GOLDEN-PUB-KS` (CONTRACT & SAFETY-REGRESSION): 快手双键排重与审查证据保全。
6. `GOLDEN-RISK-BOT` (KNOWN-UNSAFE-BASELINE): Telegram Bot 状态无约束改写（真实复现 RISK-STATE-001 缺陷行为）。

### 3. 数据集建设与隔离原则
- **数据最小化**：仅保留证明语义所需的最小字段，禁止复制完整生产脏数据。
- **零凭证泄漏**：全量检索排除 cookie、token、secret、authorization、session 等敏感字段。
- **离线可执行**：通过沙盒与临时 SQLite 隔离运行，严禁拉起外部浏览器、发起网络请求或改写生产库。
- **规范化断言**：区分 EXACT、NORMALIZED、IGNORED、SEMANTIC-MATCH 规则，防止伪确定性与过度规范化。

### 4. 数据集实现与物理落地 (Physical Artifacts)
- **全局清单**：[`tests/fixtures/golden_replay/manifest.json`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/tests/fixtures/golden_replay/manifest.json)（Schema v1.0.0, Dataset v1.0.0）。
- **说明与纪律规范**：[`tests/fixtures/golden_replay/README.md`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/tests/fixtures/golden_replay/README.md)（声明 Anti-Auto-Accept 强制红线）。
- **物理场景目录**：[`tests/fixtures/golden_replay/scenarios/`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/tests/fixtures/golden_replay/scenarios/)
  - `GOLDEN-WF-01/`: `initial_db.json`, `contract.json`
  - `GOLDEN-WF-02/`: `initial_db.json`, `contract.json`
  - `GOLDEN-PUB-WC/`: `initial_db.json`, `contract.json`, `post_list_after_submission.png` (合成 67 字节探针截图)
  - `GOLDEN-PUB-DY/`: `initial_db.json`, `contract.json`
  - `GOLDEN-PUB-KS/`: `initial_db.json`, `contract.json`
  - `GOLDEN-RISK-BOT/`: `initial_db.json`, `contract.json`
- **执行套件**：[`tests/unit/test_golden_replay_dataset.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/tests/unit/test_golden_replay_dataset.py)

### 5. 对抗性验证与重放证据 (Adversarial Verification)
1. **两次独立运行一致性 (`Run A == Run B`)**：
   每个场景在完全独立的临时目录与独立的 SQLite 实例中先后执行两次，规范化提取观察值进行逐字段对比，100% 达成 `norm_a == norm_b`，并与 `contract.json` 预期严格匹配。
2. **凭证扫描与零泄露审计**：
   全量静态扫描回放数据集内所有 JSON 文件，对 `cookie`, `token`, `secret`, `authorization`, `session`, `password`, `api_key`, `bearer` 进行正则探测，确认为合成测试占位符，0 生产敏感信息泄漏。
3. **零生产副作用验证**：
   执行后核验生产数据库 `output/pipeline.db` 与 `output/wechat_evidence/`，确认为零触碰；网络与外部浏览器完全切断。
4. **隔离测试运行证据**：
   - 回放测试套件：`tests/unit/test_golden_replay_dataset.py` -> **8 passed in 2.35s**。
   - 联合全量套件：`tests/unit/test_characterization_baseline.py tests/unit/test_golden_replay_dataset.py` -> **15 passed in 2.08s**。

### 6. 决策与签署结论 (Decision & Sign-off)
- **M6.2 状态**：**COMPLETE / VERIFIED**。
- **可执行黄金回放数据集交付完结**：已物理实例化 6 个标准场景，具备双重隔离重放能力，完全满足 Gate M6 验收准则。
- **重构工单状态**：所有工单（`WO-STATE-001` ~ `WO-PUB-001`）严格保持 **BLOCKED**。未获授权严禁进入 M6.3 或 M6.5。
