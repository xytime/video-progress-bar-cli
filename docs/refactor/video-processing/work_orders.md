---
created_by: Gemini_3.8_Flash_planning
created_at: 2026-09-12
last_updated_at: 2026-09-20
version: 1.5.0
---

# Video-precessing 重构工单池 (Refactor Work Orders v1.0 Candidate)

## Version History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.7.0 | 2026-09-20 | Antigravity | M6.2+ 第五轮终审 P1 缺口闭环：确立外键兼容的领取顺序（先 Attempt 后租约）、补齐历史 Attempt 联合阻断，及单测覆盖 |
| 1.6.0 | 2026-09-20 | Antigravity | M6.2+ 第四轮终审 P1 缺口闭环：确立租约方案 A 契约（废除方案 B）、引入宿主级 crontab 静音与真实会话锁路径探测及持锁反例单测 |
| 1.5.0 | 2026-09-20 | Antigravity | M6.2 架构审议校准：修补 WO-STATE-001 回滚方案为 Fail-Closed 只读降级与常驻进程重启，澄清子进程持锁与退避契约，扩展入口边界测试 |
| 1.4.0 | 2026-09-20 | Gemini_3.8_Flash_planning | M6.2+ 红蓝博弈加固：将 Bot 退出码 6 事务闭环（防鬼魂状态）、微信会话锁遵循与 QUEUED 异步语义注入 WO-STATE-001 |
| 1.3.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.2 阶段升级：重申 M6.2 黄金数据集建设期间全部 7 项重构工单保持严格 BLOCKED |
| 1.2.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.1B 语义升级：路线图细化为 Gate M6.5A 独立解锁 WO-STATE-001，WO-SCRIPTS-001 归入 Gate M6.5B 条件评估 |
| 1.1.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.1 阶段升级：M5 正式签署完结，建立 M6.1 特征化测试基线，全量锁定运行时工单 |
| 1.0.0-rc3 | 2026-09-12 | Gemini_3.8_Flash_planning | M5.1 完整性升级：对齐 Authoritative Risk Register 引用、标注快照观测属性并严格锁定全部运行时工单 |
| 1.0.0-rc2 | 2026-09-12 | Claude_Opus_4.6_planning | 自审修复初稿：标准化悬空风险引用、修正 PipelineDB 方法计数 |
| 1.0.0-rc1 | 2026-09-12 | Gemini_3.8_Flash_planning | M5 阶段升级：确立 Gate 驱动依赖图谱、标准化风险属性并全量锁定运行时工单 |
| 0.1.0 | 2026-09-12 | Gemini_3.8_Flash_planning | 建立初始研发与安全工单 Backlog |

---

## 🛑 运行时代工单冻结声明 (Runtime Work Order Freeze)

> [!CAUTION]
> **All runtime work orders are currently BLOCKED.**  
> 当前处于 **Phase M6.2+ — Executable Golden Replay Dataset & Adversarial Review**。M6.1 特征化测试基线已正式签署完结 (SIGNED OFF / COMPLETE)。  
> 目前已完成 M6.1 特征化测试基线、M6.2 可执行黄金回放数据集（`GOLDEN-WF-01` ~ `GOLDEN-RISK-BOT`）以及 2026-09-20 红蓝对抗博弈加固，但**所有运行时工单（`WO-STATE-001` ~ `WO-PUB-001`）依然保持严格 BLOCKED 状态**。  
> 必须在通过 Gate M6 完整验收评审后，方可在受控条件下逐项解锁。未来进入安全修复时，将首先且仅进入 **Phase M6.5A** 单独实施 `WO-STATE-001`，严禁多工单并发实施。

---

## 📋 工单总览与 Gate 依赖图谱

| 工单编号 | 标题 | 优先级 | 运行时改动? | 生产暴露? | 状态 | 所属 Gate | Blocked By |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **WO-STATE-001** | Telegram Bot 状态防篡改校验加固 | P1 | **YES** | **YES** | **BLOCKED** | Gate M6.5A | Gate M6 Exit (Harness & Dataset) |
| **WO-SCRIPTS-001** | 运维脚本 DAL 边界收口与封装 | P2 | **YES** | **NO** | **BLOCKED** | Gate M6.5B (条件评估) | Gate M6.5A Exit |
| **WO-SHADOW-001** | 只读查询与报表 Shadow Mode 试点验证 | P2 | **YES** | **NO** | **BLOCKED** | Gate M7 | Gate M6.5A Exit, Shadow Framework |
| **WO-SHADOW-002** | 决策引擎 (敏感词/窗口期) 影子比对 | P2 | **YES** | **NO** | **BLOCKED** | Gate M7 | Gate M6.5A Exit, Golden Replay Dataset |
| **WO-DB-001** | PipelineDB 内部模块化委托可行性验证 | P3 | **YES** | **NO** | **BLOCKED** | Gate M8 | Gate M7 Exit, Full DAL Tests |
| **WO-PIPE-001** | `_process_single_video` 阶段特征化与安全提取 | P1 | **YES** | **YES** | **BLOCKED** | Gate M9 | Gate M8 Exit, Replay Pipeline Harness |
| **WO-PUB-001** | 外部多平台发布执行层模块化迁移 | P0 | **YES** | **YES** | **BLOCKED** | Last Mile| All prior Gates & WOs |

---

## 📝 详细工单规范与验收标准

### WO-STATE-001 — Telegram Bot unrestricted workflow-status mutation
- **工单编号**: `WO-STATE-001`
- **状态**: **BLOCKED (DO NOT REMEDIATE IN M6)**
- **优先级**: P1 (HIGH)
- **运行时改动?**: **YES**
- **生产暴露?**: **YES** (影响 Telegram 运维命令执行行为)
- **所属 Gate**: **Gate M6.5A (First Guarded Remediation - WO-STATE-001 only)**
- **Blocked By**: Gate M6 Exit (Harness & Golden Replay Dataset complete), 受控沙箱环境
- **Unblocks**: Gate M6.5A Exit / Phase M6.5B & Phase M7, 彻底消除 `RISK-STATE-001` 与 `INV-008` KNOWN-VIOLATION
- **风险与不变式属性**:
  - `Severity`: **HIGH**
  - `Likelihood`: **LOW**
  - `Evidence confidence`: **HIGH** (源码确证)
  - `Current mitigation`: 目前仅限白名单管理员在受限群组内手动执行
  - `Related invariant`: [`INV-001`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/refactor/video-processing/refactor_handoff.md#8-confirmed-invariants-八大系统不变式), [`INV-008`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/refactor/video-processing/refactor_handoff.md#8-confirmed-invariants-八大系统不变式)
  - `Related risk`: `RISK-STATE-001`
- **事实证据**: 
  - [`src/bot/pipeline_agent.py:L714,L749`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/bot/pipeline_agent.py#L714) 直接调用 `self.db.update_video_status(youtube_id, status)` 和 `self.db.update_video_status(youtube_id, "PENDING")`，未接入 [`src/web/app.py:L842`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/web/app.py#L842) 的 `_wechat_submission_guard_reason` 校验。
  - [`src/bot/pipeline_agent.py:L683-L695`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/bot/pipeline_agent.py#L683) 未识别 `scripts/wechat_uploader.py` 退出码 `6`，误当作失败抛出。
  - [`scripts/wechat_uploader.py:L1221`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/scripts/wechat_uploader.py#L1221) 内部由 `@guarded_wechat_browser_session` 装饰持锁（超时 0 秒，争用时立即返回 `busy_result=1`）；但素材缺失（视频/文案/封面）同样返回 `1`。Bot 当前使用裸子进程环境，且对退出码 1 语义缺乏明确 BUSY 凭证校验与退避处理。
- **治理问题**: 管理员若在 Telegram 群组内对正处于 `PUBLISHED` 或 `UNDER_REVIEW` 的视频执行状态修改或重试指令，会绕过 Web 控制台的防重投 Guard，将视频打回 `PENDING`，带来二次重复发布与封号隐患；且 Bot 缺少对退出码 6 的正确处理，会造成假失败与无账本鬼魂状态。
- **实施范围**: 
  1. 将 Bot 严格收口为具名任务分发客户端：执行**响应前强制持久化**（先在 SQLite 原子写入分发记录，随后返回 `QUEUED` 异步受理语义包含 task_id 与时间戳），对活跃中任务执行幂等复用，严禁 LLM 擅自向用户宣称“已发布完成”。
  2. 确立方案 A 完整契约并废除方案 B：外部物理调用前执行 `wechat_submission_attempts` 历史表 CHECK 约束扩展迁移（纯追加审计历史无唯一约束，杜绝表迁移 `IntegrityError` 崩溃），创建独立原子活跃租约表 `wechat_submission_active_claims`（`subject_id TEXT PRIMARY KEY`）；在单个 `BEGIN IMMEDIATE` 事务内严格按外键依赖执行原子领取：4 表联合前置阻断检查（租约、历史 Attempt、Publication 事实表与主表） → 先插入 Attempt 记录满足外键依赖 → 再插入活跃租约表实现主键排他互斥，任一步失败全量回滚零残留；按 `active_attempt_id` 条件精确释放与流转：BUSY 退出时标记 `RELEASED_BUSY` 并从活跃租约表精确删除；若外部平台受理后本地崩溃或超时未决，Fail-Closed 进 `UNCERTAIN` 物理阻断再次重领，彻底闭环 At-Most-Once。
  3. 由核心应用服务统一负责发布账本守卫校验，阻断对已发布/在途视频的非法回写与删除。
  4. 捕获退出码 6 并原子调用事务方法更新活跃租约、写入 Publication 账本、Attempt 记录与主表 `SUBMITTED_UNBOUND` 状态，明确本地四表强一致性 vs 外部 At-Most-Once 边界。
  5. 接入 `_build_subprocess_env`；会话锁由子进程内部自洽持有（严禁父进程外置重复加锁，防止超时 0 秒产生锁争用立即锁忙失败）；会话锁探测必须对齐调度器与上传入口约定路径 `output/wechat_state.json`，调用 `canonical_wechat_session_lock_path("output/wechat_state.json")` 探测真实锁文件 `output/.wechat_state.json.browser.lock`；仅对明确 BUSY 凭证有限退避（最多 3 次），通用退出码 1 判定为永久失败，退出码 3 明确为发布结果未确认（`EXIT_RESULT_UNCERTAIN`），绝不可自动重传。
- **明确非目标**: 重构 Telegram Bot 的长轮询网络通信机制。
- **安全 Harness 要求**: 编写自动化回归测试，验证退出码 6 的原子账本写入、针对已发布视频执行 Bot 重置与删除命令被明确拒绝、并发重置互斥、退出码 3 告警、子进程超时回收、转入 UNCERTAIN 后再次领取仍被拒绝的阻断测试（`test_claim_attempt_rejected_when_prior_attempt_is_uncertain`）、独立活跃租约生命周期与条件释放测试（`test_active_claims_lease_lifecycle`）、历史 Attempt 存在时的独立阻断测试（`test_claim_attempt_rejected_when_only_historical_attempt_exists`）、外键兼容与领取失败原子回滚无残留测试（`test_claim_attempt_rollback_leaves_no_residual_on_failure`）、真实会话锁探测与持锁反例测试（`test_wechat_session_lock_probe_detects_real_hold_and_release`，动态提取蓝图第 6.1 节完整命令并执行，基于实际上传约定路径 `output/wechat_state.json` 派生，持锁时断言非零失败，释放后断言返回 0，杜绝缩进语法错误与配置脱节），以及 Attempt 历史表扩展 CHECK 约束迁移平滑性测试。
- **验收标准**: 任何通过 Bot 指令重置或删除已存在平台账本的视频均被拒绝并返回明确报错；未受阻任务仍可正常重置；退出码 6 正确转入审核中并记录四表原子账本；方案 A 独立租约表外键兼容原子 CAS、四表联合阻断与条件释放完整通过；真实会话锁反例测试通过。
- **回滚方案**: 实行**受控安全回滚五步法**：① 宿主级停写（导出 crontab 备份并执行 `sed -E '/Video-precessing/s/^([^#])/# QUIESCE_DISABLED \1/'` 物理注释调度，核验活跃 crontab 为空彻底阻断 cron 复活；置 `WECHAT_PUBLISHING_PAUSED=true`；终止常驻服务与关联进程组 PGID 及 Chromium 孤儿；通过 `canonical_wechat_session_lock_path` 探测 `output/.wechat_state.json.browser.lock` 核验真实会话锁释放并标记在途任务为 `UNCERTAIN`，未证实零消费前严禁 revert）；② 绑定具体目标 Commit 执行原子回滚；③ 沙箱运行 `POLARIS-101` 新增防线测试（严禁运行包含不安全基线的历史单测，防线测试若失败必须保持暂停与 crontab 静音、严禁恢复调度）；④ 推送并重启全套守护进程；⑤ 确认无误后恢复 crontab 调度并解除暂停。若已发生状态分叉，严禁全库盲跑与裸写生产 SQL，按专用剧本执行：SQLite 在线备份 API（`conn.backup()`，采用高精度微秒 UTC 时间戳与 UUID 随机熵拒绝覆盖，并验证 `PRAGMA integrity_check;` 登记恢复点） → 排除 `PUBLISHED` 的受测 DAL 只读差异预览 → 针对指定 `video_id` 的受测 DAL 定点纠偏。

---

### WO-SCRIPTS-001 — Operational scripts DAL boundary encapsulation
- **工单编号**: `WO-SCRIPTS-001`
- **状态**: **BLOCKED (PENDING M6.5A COMPLETION)**
- **优先级**: P2 (MEDIUM)
- **运行时改动?**: **YES**
- **生产暴露?**: **NO** (仅限离线/运维脚本)
- **所属 Gate**: **Gate M6.5B (条件评估 - 仅在 M6.5A 验收通过后评估)**
- **Blocked By**: Gate M6.5A Exit
- **Unblocks**: Phase M7, 脚本层 DAL 边界彻底合规
- **风险与不变式属性**:
  - `Severity`: **MEDIUM**
  - `Likelihood`: **HIGH**
  - `Evidence confidence`: **HIGH** (静态检索确证)
  - `Current mitigation`: 仅在手动运维脚本中使用，不影响核心调度
  - `Related invariant`: 架构宪法“全库原生 SQL 必须严格封装在 DAL 方法内部”
  - `Related risk`: `RISK-DB-002` (架构维护债务)
- **事实证据**: [`scripts/backfill_metadata.py:L12,L41`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/scripts/backfill_metadata.py#L12) 与 [`scripts/regen_published_covers.py:L14`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/scripts/regen_published_covers.py#L14) 直接调用 `db.get_connection()` 并在外部执行原生 SQL。
- **治理问题**: 违反了项目工程宪法中关于数据访问层（DAL）封装的规定，外部直接写 SQL 导致数据访问逻辑发散。
- **实施范围**: 在 `PipelineDB` 中增加 `get_videos_needing_metadata_backfill()` 与 `update_video_metadata_fields()` 等标准 DAL 方法，重构这两个脚本使其仅调用封装方法。
- **明确非目标**: 改变元数据抓取逻辑或封面重制业务。
- **安全 Harness 要求**: 运行单元测试验证新增的 DAL 包装方法及其边界。
- **验收标准**: `git grep "get_connection" scripts/` 输出为 0。
- **回滚方案**: Git commit 级别原子回滚。

---

### WO-SHADOW-001 — Read-only query shadow pilot
- **工单编号**: `WO-SHADOW-001`
- **状态**: **BLOCKED**
- **优先级**: P2 (MEDIUM)
- **运行时改动?**: **YES**
- **生产暴露?**: **NO** (仅在后台记录影子比对 diff，主响应仍取旧版本)
- **所属 Gate**: **Gate M7**
- **Blocked By**: Gate M6 Exit, 影子比对框架就绪
- **Unblocks**: Gate M8, 只读查询模块解耦
- **风险与不变式属性**:
  - `Severity`: **LOW**
  - `Likelihood`: **LOW**
  - `Evidence confidence`: **HIGH**
  - `Current mitigation`: 只读操作，零持久化副作用
  - `Related invariant`: [`INV-001`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/refactor/video-processing/refactor_handoff.md#8-confirmed-invariants-八大系统不变式)
  - `Related risk`: `RISK-PIPE-002`
- **事实证据**: [`PipelineDB.get_paginated_videos:L4587`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/db/database.py#L4587) 达 98 行，包含跨表动态 JOIN、复杂过滤与排序。
- **治理问题**: 控制台分页与多账本聚合查询逻辑冗长，直接优化或提取存在产生分页漂移或数据漏出的风险。
- **实施范围**: 编写新的只读提取版本，在 Web 端异步并发执行两套查询并自动对比输出 JSON，若不一致则打印告警日志，始终以旧版本结果返回前端。
- **明确非目标**: 修改前端 UI 或接口协议。
- **安全 Harness 要求**: 零写操作，任何异步比较异常被吞掉并不影响旧逻辑主流程返回。
- **验收标准**: 线上真实请求连续运行 7 天，两套查询结果达到 100% 吻合（零 mismatch）。
- **回滚方案**: 特性开关 `enable_shadow_query`，随时可置为 False。

---

### WO-SHADOW-002 — Decision replay/shadow pilot
- **工单编号**: `WO-SHADOW-002`
- **状态**: **BLOCKED**
- **优先级**: P2 (MEDIUM)
- **运行时改动?**: **YES**
- **生产暴露?**: **NO** (仅比对决策输出)
- **所属 Gate**: **Gate M7**
- **Blocked By**: Gate M6 Exit, 离线黄金样本集 (Golden Replay Dataset)
- **Unblocks**: Gate M8, 决策引擎独立提取
- **风险与不变式属性**:
  - `Severity`: **LOW**
  - `Likelihood`: **LOW**
  - `Evidence confidence`: **HIGH**
  - `Current mitigation`: 纯内存计算，无外部写
  - `Related invariant`: [`INV-003`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/refactor/video-processing/refactor_handoff.md#8-confirmed-invariants-八大系统不变式)
  - `Related risk`: `RISK-PIPE-001`
- **事实证据**: [`censor_engine.check_text:L719`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/censor_engine.py#L719) 与 `_is_public_publish_window` 属于纯 DECISION，无持久化副作用。
- **治理问题**: 审核规则与发布窗口判定混杂在调度器各处，缺乏独立的规则引擎抽象。
- **实施范围**: 对历史离线样本与实时任务的文案/字幕进行双跑，比对判定结果（是否放行、阻断原因、tag 命中）是否完全一致。
- **明确非目标**: 修改违禁词库或改变敏感词过滤等级。
- **安全 Harness 要求**: 决策比对器仅记录 diff 日志，不改变实际拦截行为。
- **验收标准**: 比对 100+ 个真实历史视频样本的审核决策，结论完全对齐。
- **回滚方案**: 特性开关即时关闭。

---

### WO-DB-001 — PipelineDB internal delegation feasibility
- **工单编号**: `WO-DB-001`
- **状态**: **BLOCKED**
- **优先级**: P3 (LOW)
- **运行时改动?**: **YES**
- **生产暴露?**: **NO** (API 签名 100% 保持)
- **所属 Gate**: **Gate M8**
- **Blocked By**: Gate M7 Exit, 全量 DAL 单元测试集
- **Unblocks**: Gate M9, DAL 彻底解耦
- **风险与不变式属性**:
  - `Severity`: **HIGH** (若事务拆分不当引发锁或分叉)
  - `Likelihood`: **LOW** (内部委托模式设计成熟)
  - `Evidence confidence`: **HIGH**
  - `Current mitigation`: 单一 `PipelineDB` 实例持有上下文连接写操作
  - `Related invariant`: [`INV-007`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/refactor/video-processing/refactor_handoff.md#8-confirmed-invariants-八大系统不变式) (强事务原子性)
  - `Related risk`: `RISK-DB-001`
- **事实证据**: `PipelineDB` 拥有 245 个方法（基于 2026-09-12 静态快照观测），但抖音账本（L8210-L9457）、快手账本（L7936-L8207）及英语世界（L5611-L7530）在物理表上完全独立。
- **治理问题**: 约 9.7k 行的单体文件导致日常代码审查冲突频繁，维护成本高。
- **实施范围**: 保持 `PipelineDB` 对外 public API 签名绝对不变，内部将其对抖音、快手等独立表的操作委托给子模块实现。
- **明确非目标**: 拆分 `record_wechat_submission_acceptance` 等多表强原子事务；修改外部调用方的引用方式。
- **安全 Harness 要求**: 事务连接对象透传，确保处于同一外层事务时不发生锁死或新建连接。
- **验收标准**: 外部调用无需改写任何一行 import 或代码，全库测试无回归。
- **回滚方案**: 保持旧单体实现文件暂不删除，可通过开关直接切换回旧实现。

---

### WO-PIPE-001 — _process_single_video stage characterization / eventual extraction
- **工单编号**: `WO-PIPE-001`
- **状态**: **BLOCKED**
- **优先级**: P1 (HIGH)
- **运行时改动?**: **YES**
- **生产暴露?**: **YES**
- **所属 Gate**: **Gate M9**
- **Blocked By**: Gate M8 Exit, Replay Pipeline Harness, Golden Replay Dataset
- **Unblocks**: Gate M10, 调度引擎轻量化
- **风险与不变式属性**:
  - `Severity`: **HIGH**
  - `Likelihood`: **HIGH** (约 1k 行方法内部包含大量隐式依赖)
  - `Evidence confidence`: **HIGH**
  - `Current mitigation`: 依靠现有单元测试套件提供基本回归保障
  - `Related invariant`: [`INV-002`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/refactor/video-processing/refactor_handoff.md#8-confirmed-invariants-八大系统不变式), [`INV-003`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/refactor/video-processing/refactor_handoff.md#8-confirmed-invariants-八大系统不变式)
  - `Related risk`: `RISK-PIPE-001`
- **事实证据**: [`PipelineManager._process_single_video:L3268-L4280`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/pipeline_manager.py#L3268) 长达约 1k 行，单体方法包含 8 个阶段。
- **治理问题**: 阶段间通过局部变量隐式传递状态，异常处理与检查点判断紧耦合，任意一处修改爆炸半径极大。
- **实施范围**: 将 Download, Slice, Copywriting, Transcribe/Render, Cover, Censorship 等阶段逐个提取为明确输入输出的阶段处理器。
- **明确非目标**: 改变阶段流转顺序；改变临时文件命名规范。
- **安全 Harness 要求**: 严格的阶段级检查点比对。
- **验收标准**: 提取后的各子函数行数不超过 100 行，全链路重放测试与线上实际生产行为完全等价。
- **回滚方案**: 保留原始约 1k 行方法作为 fallback 方法，由开关控制。

---

### WO-PUB-001 — Publication side-effect migration
- **工单编号**: `WO-PUB-001`
- **状态**: **BLOCKED / LAST MILE**
- **优先级**: P0 (CRITICAL)
- **运行时改动?**: **YES**
- **生产暴露?**: **YES** (直接操作外部社交平台发布接口)
- **所属 Gate**: **Last Mile (所有前置门通过后)**
- **Blocked By**: Gate M5 至 M9 所有工单全部验收闭环
- **Unblocks**: 最终架构治理全面收敛
- **风险与不变式属性**:
  - `Severity`: **CRITICAL**
  - `Likelihood`: **LOW** (依赖底层多层防线)
  - `Evidence confidence`: **HIGH** (业务属性)
  - `Current mitigation`: 多层基于 SHA256 与 Ticket 的严格幂等拦截网
  - `Related invariant`: [`INV-004`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/refactor/video-processing/refactor_handoff.md#8-confirmed-invariants-八大系统不变式), [`INV-005`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/refactor/video-processing/refactor_handoff.md#8-confirmed-invariants-八大系统不变式), [`INV-007`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/refactor/video-processing/refactor_handoff.md#8-confirmed-invariants-八大系统不变式)
  - `Related risk`: `RISK-PUB-001`
- **事实证据**: `scripts/wechat_uploader.py` 与 `_publish_claimed_douyin_publication` 涉及外部平台实际浏览器自动化与不可逆物理发帖。
- **治理问题**: 任何逻辑瑕疵均可能直接导致封号、重复发帖或发布违规内容。
- **实施范围**: 对发布器外部调用接口进行最终的标准化封装与凭据生命周期收敛。
- **明确非目标**: 任何提前或脱离全套安全 harness 的修改。
- **安全 Harness 要求**: 真实账号 Dry-run 模式与单次投稿人工确认闸门。
- **验收标准**: 连续 30 天无重复投稿、无漏对账、无凭据泄漏。
- **回滚方案**: 物理保留旧上传脚本与配置，一键切回。
