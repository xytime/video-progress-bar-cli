---
created_by: Gemini_3.8_Flash_planning
created_at: 2026-09-12
last_updated_at: 2026-09-12
version: 1.4.0
---

# Video-precessing 重构交接合同 (Refactor Handoff Contract v1.0 Final)

## Version History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.4.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.1D 独立防线与去重审计：校准 INV-003 语义，分离 Publication Fact 与 Defense，引入 Protection Dimensions 与 Control Families 多维建模 |
| 1.3.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.1C 防线合格性审计：严格对齐 Publication Safety Defense 标准，删除未形式定义的故障域指标，改用共享依赖分析 |
| 1.2.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.1B 语义审计升级：收敛 M6.5 为 M6.5A (WO-STATE-001 only) 与条件化 M6.5B (WO-SCRIPTS-001)，对齐工单依赖图 |
| 1.1.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.1A 阶段升级：校准 Gate M6.5 受控安全修复路线，对齐不变式双轨矩阵语义 |
| 1.0.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M5 正式签署完结 (M5 Final Acceptance & Sign-off)。8 大不变式、7 项架构风险、兼容性信封与故障模型正式确立为不可篡改的系统重构宪法 |
| 1.0.0-rc3 | 2026-09-12 | Gemini_3.8_Flash_planning | M5.1 完整性升级：建立统一 12 字段 Authoritative Risk Register、归档 RISK-STATE-002 生命周期、基于源码调用核验兼容性信封入口、标注快照观测属性并补齐 Integrity Gate |
| 1.0.0-rc2 | 2026-09-12 | Claude_Opus_4.6_planning | 自审修复初稿：纠正虚构 API 名、补充风险登记表附录、修正计数与笔误 |
| 1.0.0-rc1 | 2026-09-12 | Gemini_3.8_Flash_planning | M5 阶段升级：确立 20 个正式章节、8 项系统不变式、10 种故障场景模型、兼容性信封与 Gate 驱动安全门 |
| 0.1.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M4.5 重构接手契约骨架 |

---

## 1. Document Status (文档状态与权限约束)

- **当前状态**：**v1.0.0 (FINAL SIGNED OFF / CONTRACT FROZEN)**
- **所属治理阶段**：**Phase M5 SIGNED OFF / Phase M6.1 Active**
- **当前生产代码修改权限 (Production Change Allowed)**：**❌ NO (STRICTLY FORBIDDEN)**
- **法律效力**：本交接合同是后续任何工程师或 AI Agent 进行代码结构调整、模块解耦、测试补齐与流程提取的**最高生产安全宪法**。在完成 Gate M5 验收并建立 Gate M6 安全线网（Safety Harness）之前，严禁修改任何业务代码。

---

## 2. Purpose (治理宗旨与核心目标)

明确 `Video-precessing` 核心流水线在代码重构、模块解耦与测试加固过程中的系统不变式（Invariants）、副作用分界与安全红线。
治理的核心目标是：
1. **降低维护单点的修改爆炸半径**：逐步解耦 `PipelineDB`（单体约 9.7k 行）与 `PipelineManager`（调度单体约 4.4k 行，含约 1k 行的 `_process_single_video`），将交织业务收敛为高内聚的子领域。
2. **绝对保真线上已有生产安全语义**：严格保留经生产实战检验的多层幂等拦截、发布凭据原子性及防重发机制。
3. **建立安全可控的渐进迁移基础设施**：通过影子比对（Shadow Mode）和离线黄金数据集（Golden Replay Dataset）确保重构过程对线上零风险、零侵入。

---

## 3. Non-Goals (明确非目标)

为了避免重构范围无限泛化与引入非必要风险，本治理工作明确以下非目标：
- ❌ **非架构重写或微服务化**：不引入分布式微服务、RPC 框架或更换基础关系型数据库（继续保持 SQLite WAL 模式）。
- ❌ **非业务需求变更或夹带优化**：重构严格限于内部结构优化，严禁借重构之机修改违禁词策略、调整视频评分权重或改变视频渲染视觉参数。
- ❌ **非外部平台 API 盲目双跑**：严禁在未经过虚拟 Dry-run 与隔离测试的前提下对外部平台发布流程实施真实双跑测试。
- ❌ **非盲目目录大搬家**：禁止在缺乏调用拓扑与测试覆盖保证下大面积移动文件或重命名核心符号。

---

## 4. Current Architecture (当前架构基线)

系统由以下核心子层与物理单体构成（代码行数与方法数均标注为 2026-09-12 静态快照观测事实）：
- **DAL 数据访问层单体**：[`PipelineDB`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/db/database.py#L166)（约 9.7k 行，245 个方法，基于 2026-09-12 静态快照观测），承载 SQLite 连接上下文、25+ 张表的建表迁移与跨平台业务数据操作。
- **状态机总调度中枢**：[`PipelineManager`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/pipeline_manager.py#L486)（约 4.4k 行），主驱动方法 `_process_single_video`（约 1k 行）串联视频下载、切片、文案、字幕压制、封面渲染及外部多平台发布。
- **双控制平面 (Dual Control Plane)**：
  - Web 控制台：[`src/web/app.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/web/app.py)（FastAPI 面板，监听 `:8765`）。
  - 远程运维机器人：[`src/bot/telegram_bot.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/bot/telegram_bot.py)（基于 Telegram 长轮询）。
- **执行工具与外部上传器**：
  - 核心计算与媒体处理器：`src/video_processing/processors/`（纯计算、FFmpeg 与 Whisper 封装）。
  - 外部上传执行脚本：`scripts/wechat_uploader.py`（Playwright 自动化，约 80KB）、`scripts/douyin_uploader.py`。

---

## 5. State Authority Hierarchy (状态权威梯次)

系统内存在三级状态体系，当状态表达发生分歧时，必须严格遵守以下权威层级：

```text
[Level 1: 绝对事实源 (External Ground Truth)]
 外部社交平台创作者中心客观事实 (平台原生 post_id、作品管理界面真实可见性、审核通过状态)
         ↓ (由后台只读对账 Worker 观测并写入)
[Level 2: 凭证账本源 (Platform Publication Ledgers)]
 本地平台发布账本 (*_publications, wechat_submission_attempts, asset_sha256)
         ↓ (约束与投影)
[Level 3: 本地调度态 (Workflow Execution State)]
 任务流水线工作流状态 (processed_videos.status: PENDING, DOWNLOADING, TRANSCRIBING, PUBLISHED...)
```

### 权威约束规则：
1. **账本优先准则 (Ledger Superiority)**：`processed_videos.status` 仅代表当前主机的执行进度投影。只要 Level 2 账本中存在合法发布记录或受理凭证，该视频在业务上就被判定为“已发布/在途”，**Level 2 账本无条件否决并修正 Level 3 状态**。
2. **对账校准准则 (Reconciliation Calibration)**：当 Level 2 账本与 Level 1 外部事实出现不一致时（例如平台人工下架或延迟审核通过），由后台巡检 Worker 观测 Level 1 事实后校准更新 Level 2 账本。

---

## 6. Side-Effect Taxonomy (副作用分类矩阵)

为确保重构模块的隔离度与影子验证的可行性，系统所有操作严格划分为 5 类副作用：

| 类别 | 描述 | 系统典型代表 | 重构验证策略 |
| :--- | :--- | :--- | :--- |
| **PURE_READ** | 仅读取数据库、文件或系统配置，对外部与本地状态零修改 | `get_video_by_youtube_id`, `get_paginated_videos` | **生产环境可直接并行影子比对 (Direct Shadow)** |
| **DECISION** | 纯内存计算，基于确定输入输出布尔判断或结构体，无任何 I/O 写 | `censor_engine.check_text`, `_is_public_publish_window` | **生产环境可直接并行影子比对 (Direct Shadow)** |
| **PERSISTENCE** | 修改本地数据库状态或写入流水记录，无进程外网络或外部实体动作 | `update_video_score`, `record_ai_provider_attempt` | **离线测试库或 Dry-run 事务回滚模式验证** |
| **LOCAL_SIDE_EFFECT**| 产生磁盘音视频文件、消耗大量本地 CPU/GPU/内存、调用子进程 | `_run_tracked` (Whisper, FFmpeg, 文案/封面生成) | **离线黄金数据集回放 (Replay Shadow) + 隔离目录** |
| **EXTERNAL_SIDE_EFFECT**| 发起外部网络 API、拉起无头浏览器发布、发送 Telegram 消息 | `scripts/wechat_uploader.py`, 抖音浏览器启动 | **❌ 严禁盲目双跑；仅允许 Mock 或最后阶段单跑** |

---

## 7. Compatibility Envelope (兼容性信封)

重构过程中必须严格受控的 5 类兼容性边界：

### 7.1 Public API Compatibility
- `PipelineDB` 对外暴露的公共方法（如 `get_video_by_youtube_id`, `get_paginated_videos`, `update_video_status` 等共计 245 个方法，基于 2026-09-12 静态快照观测）必须保持**方法签名、返回值结构与异常契约完全向后兼容**。内部可委托子领域实现，但外部调用代码零改动。
- `PipelineManager` 外部调用入口契约（现有外部调用方依赖的稳定公共入口 / existing externally-used PipelineManager entry points）：
  - `run_daily_job()`：日常批处理调度主入口，外部调用方包括 `scripts/run_publication_window.py:L184` 及模块 CLI 入口 `src/video_processing/pipeline_manager.py:L4388`。
  - `run_preparation_job()`：后台候选准备入口，外部调用方包括 `scripts/run_background_preparation.py:L28`。
  - `reset_video_artifacts(prefix)`：重置产物文件入口，外部调用方包括 `src/web/app.py:L2731,L2830,L2931` 与 `src/bot/pipeline_agent.py:L732`。
  - `process_high_score_videos(limit)`：高分视频批处理核心入口，由 `run_daily_job()` 串联调度，并被调度与发布集成测试作为核心公共契约调用。
  - `recover_deferred_wechat_publications()`：延后配额补发恢复入口，由 `run_daily_job()` 串联调度。
  以上外部入口必须保持方法签名、参数默认值及返回语义完全稳定，严禁任何破坏性签名调整。

### 7.2 Data & Schema Compatibility
- SQLite 数据库处于 WAL 模式，所有 DDL 必须满足**单向可加（Additive-only）**，严禁重命名或删除现有列。
- `processed_videos` 复合主键 `(youtube_id, slice_index)` 与外键级联契约不可变。
- `wechat_publications`, `douyin_publications`, `kuaishou_publications` 等账本表必须保持物理独立。

### 7.3 Workflow & Checkpoint Compatibility
- 磁盘检查点命名与归档路径不可变（如 `output/archive/{youtube_id}/` 下的视频文件、`.ass` 字幕、文案 json、封面图片）。
- 检查点跳过语义不可变：重构后当且仅当目标构件全集存在且校验合法时方可跳过该阶段。

### 7.4 Publication Semantics Compatibility
- 发布排重基于 `asset_sha256` 物理哈希的算法不可变。
- 浏览器自动化一次性 Ticket 消费协议不可变。
- 视频号三表原子受理语义不可变。

### 7.5 Operational Compatibility
- 命令行入口（`./vpanel`, `video-process`, `cli/main.py`）参数与行为不变。
- Web 控制台默认监听端口 `:8765` 及现有 REST 路由协议不变。
- Telegram 运维机器人核心指令响应格式不变。

---

## 8. Confirmed Invariants (八大系统不变式)

### `INV-001`: Workflow State != Publication Truth
- **陈述**：`processed_videos.status` 仅代表本地调度器执行进度投影，绝不能等同于外部社交平台的发布事实。
- **代码证据**：Web 控制台允许将失败视频打回 `PENDING`，但该视频可能在视频号平台早已审核通过。
- **治理后果**：任何防重发、排重与发布决策，严禁仅依赖 `status == 'PUBLISHED'` 作出判断，必须联合查询对应平台的发布账本。

### `INV-002`: Platform Evidence Outranks Workflow Projection (Fail-Closed)
- **陈述**：一旦存在已发布或在途的平台发布证据（如账本记录、不可变截图、平台 post_id），系统必须 Fail-Closed 拦截一切重发动作。
- **代码证据**：[`PipelineManager._block_duplicate_wechat_submission_if_needed:L972`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/pipeline_manager.py#L972)。
- **治理后果**：发布前检查点必须保留多重 fail-closed 拦截网，宁可报错终止，绝不冒进重投。

### `INV-003`: Supported Production Paths Contain Multi-Layer Idempotency Defenses
- **校准陈述**：所有受支持的生产发布路径均具备多维控制族（Control Families）与多处独立执行判定点（Enforcement Points）的纵深防御体系。区分 Publication Fact（客观发布事实记录）与 Publication Defense（读取事实并阻断的执行判定点），杜绝将同一事实及其在不同时机的读取拆解为重复层数。
- **代码证据**：调度候选过滤（Candidate Exclusion SQL）→ 控制面拦截（Web Guard）→ 流程门禁（Terminal State Check）→ 登记入库排重与成片哈希校验 → 执行授权凭据（Claim/Ticket）→ 本地物理截图前置探针硬熔断。
- **治理后果**：重构时严禁随意“精简”看似重复的校验逻辑，各控制族与执行判定点具有不同生命周期时机的兜底防御价值。

### `INV-004`: Asset SHA256 Publication Deduplication
- **陈述**：抖音与快手平台以成片文件的物理哈希 `asset_sha256` 作为绝对排重凭据。
- **代码证据**：[`create_douyin_publication:L8227`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/db/database.py#L8227) 与 [`create_kuaishou_publication:L7961`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/db/database.py#L7961)。
- **治理后果**：即使上游 `youtube_id` 发生变动或重新抓取，只要渲染出的成片二进制相同，系统坚决拒绝在同一平台重复发布。

### `INV-005`: One-Time Browser Launch Ticket Semantics
- **陈述**：外部浏览器自动化发布前必须在事务内领取并核销一张单次有效的 Ticket，未持有效 Ticket 严禁拉起浏览器。
- **代码证据**：[`douyin_browser_launch_tickets`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/db/database.py#L1708) 表由上层在领票事务内原子签发，低层消费后立即作废。
- **治理后果**：物理阻断网络重放攻击、并发进程冲突与死掉任务的晚到启动（Late-arriving execution）。

### `INV-006`: Reconciliation Must Be Publication-Side-Effect-Free
- **校准陈述**：后台对账 Worker（Reconciliation）允许并必须执行本地状态持久化（更新本地发布账本、同步工作流状态投影、记录审计日志），但**绝对不能产生任何外部平台发布副作用**（严禁触发新投稿、重新上传媒体、唤起浏览器或消耗发布 Ticket）。
- **代码证据**：`reconcile_wechat_under_review` 与 `reconcile_douyin_under_review` 仅抓取外部列表并在本地比对更新。
- **治理后果**：巡检任务必须保持单向观测性，绝不与发布动作代码混编。

### `INV-007`: WeChat Submission Acceptance Multi-Table Atomicity
- **陈述**：视频号提交受理必须在单一数据库事务内完成对确认账本、尝试账本与主表状态的原子更新。
- **代码证据**：[`PipelineDB.record_wechat_submission_acceptance:L3261-L3358`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/db/database.py#L3261) 跨 `wechat_publications`, `wechat_submission_attempts`, `processed_videos` 三表执行。
- **治理后果**：重构 DAL 内部委托时，该方法必须保留在单一 SQLite 连接事务上下文内，严禁拆分成异步跨连接操作。

### `INV-008`: Control Plane Destructive/Retry Operations Must Fail Closed on Existing Publication Evidence
- **校准陈述**：所有破坏性或重试类控制平面操作（Web 端重试、强重置、跳过、恢复登录态及 Telegram Bot 运维指令），当检测到该视频已存在平台发布凭据或处于在途发布状态时，**必须统一 Fail-Closed 拒绝执行**。
- **代码证据**：[`src/web/app.py:L842`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/web/app.py#L842) 的 `_wechat_submission_guard_reason` 在 9 处 Web 接口中执行拦截；Telegram Bot [`src/bot/pipeline_agent.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/bot/pipeline_agent.py#L714) 当前缺失此拦截（待 `WO-STATE-001` 补齐）。
- **治理后果**：控制平面必须建立统一的拦截规范，杜绝人工误操作或远程指令打乱在途任务。

---

## 9. Failure Model (十大典型故障场景模型)

为保障重构后的系统具备足够的韧性，重构设计必须显式防御以下 10 种故障场景：

1. **转码/提取阶段子进程崩溃**：FFmpeg 或 Whisper 发生 OOM/异常退出。系统需通过 `_run_tracked` 捕获异常，清理半成品垃圾文件，保留任务处于 `FAILED`，不得残留伪检查点。
2. **AI 文案生成超时或网络抖动**：Gemini / 阿里云服务超时或限流。系统必须支持降级备选（Fallback）重试，重试超限则进入优雅挂起，不阻断全局守护进程。
3. **无头浏览器在点击提交前崩溃**：Playwright 上传视频并填写表单完成，但在点击发布前会话中断。此时本地无提交凭证，任务安全退出，下一次重试安全幂等。
4. **无头浏览器在点击提交后、回写账本前瞬态崩溃**：外部平台已成功收到视频，但本地进程在写入账本前被 `SIGKILL` 或断电。**防御机制**：依靠不可变截屏证据与下一次循环触发的 `repair_wechat_submission_status_divergence` 自动对账修复。
5. **数据库写事务中途进程终止**：执行 `record_wechat_submission_acceptance` 过程中断电。SQLite WAL 机制保证事务原子回滚，无中间脏数据；后续重试重新触发受理修复。
6. **管理员在视频在途发布时点击 Web "Hard Reset"**：Web 端执行 `_wechat_submission_guard_reason`，检测到存在发布账本，直接抛出 HTTP 400/409 拒绝重置。
7. **管理员在 Telegram 群发送 `/retry` 干扰已发布视频**：当前存在 `RISK-STATE-001` 隐患；未来由 `WO-STATE-001` 接入对齐 Guard，拒绝篡改并向群组返回告警提示。
8. **抖音发布 Worker 遭遇当日发帖配额耗尽**：`claim_next_douyin_publication` 校验当日已用量超限，原子拒绝签发 Ticket，任务保留在 `QUEUED` 状态等待次日重试。
9. **抖音浏览器领票后因验证码弹窗卡死超时**：Ticket 被标记为已消费但未见发布完成。超时看门狗回收过期租约，释放任务并通知人工介入。
10. **切片子视频（Slice）与母视频（Parent）状态分叉**：母视频为 `SEGMENTED`，子视频独立推进。子视频故障只重试自身，不重置母视频；母视频删除时级联清理子切片。

---

## 10. Transaction Boundaries (关键事务边界规范)

### 核心事务标杆：`record_wechat_submission_acceptance`
- **定位**：[`src/video_processing/db/database.py:L3261-L3358`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/db/database.py#L3261)
- **跨越实体**：
  1. `wechat_publications`（插入或更新最终发布状态与 post_id）
  2. `wechat_submission_attempts`（记录本次提交尝试结果与证据链）
  3. `processed_videos`（同步更新工作流投影状态为 `PUBLISHED`）
- **铁律约束**：
  - 必须处于同一个 SQLite `BEGIN IMMEDIATE ... COMMIT` 连接上下文。
  - 任何针对 `PipelineDB` 的拆分或委托重构，**严禁将该事务拆分给不同连接**，以防在高并发 WAL 模式下产生锁冲突或部分提交（Partial Commit）。

---

## 11. Idempotency Model (多层纵深防御幂等模型)

系统对不可逆发布操作采取五级递进式幂等防护：

```text
[第 1 级：SQL 数据过滤层]
 调度器查询待发布候选集时，通过 NOT EXISTS / WHERE state='QUEUED' 物理排除已有记录项。
          ↓
[第 2 级：物理文件证据层]
 启动发布前，校验 output/archive/ 下是否存在合法提交成功证据截图与摘要。
          ↓
[第 3 级：内存互斥与租约层]
 领票机制（Ticket Claim），将记录状态原子从 QUEUED 跃迁为 CLAIMED，锁定并发租约。
          ↓
[第 4 级：内容物理指纹层]
 基于最终视频二进制文件的 asset_sha256 进行全库碰撞比对，排重同源内容。
          ↓
[第 5 级：数据库唯一约束层]
 (video_id, platform) 复合唯一索引，作为底层防止并发击穿的最后兜底强约束。
```

---

## 12. Natural Migration Units (候选迁移单元分级)

根据副作用与耦合度，将系统模块划分为三级迁移单元：

### Tier A (优先试点：只读与决策提取)
- **特征**：PURE_READ 或 DECISION，零磁盘/网络写副作用，风险极低。
- **模块清单**：
  1. 敏感词审查引擎 (`censor_engine.py`)
  2. 控制台数据分页与聚合查询 (`get_paginated_videos`)
  3. 窗口期与合规决策判定器 (`_is_public_publish_window`)
- **验证方式**：线上流量并行影子比对（Direct Shadow）。

### Tier B (中期攻坚：内部委托与独立产品线)
- **特征**：PERSISTENCE 或 LOCAL_SIDE_EFFECT，表结构独立或业务逻辑闭环。
- **模块清单**：
  1. 抖音发布账本与 Ticket 管理模块
  2. 快手发布账本管理模块
  3. 独立垂直产品线（Highlight Clips, English World, Dubbing）
- **验证方式**：保持 `PipelineDB` 外部接口不变，内部建立模块委托，依赖完备测试集保障。

### Tier C (末期触碰：核心状态机与外部发布)
- **特征**：EXTERNAL_SIDE_EFFECT 与强事务交织，修改爆炸半径极大。
- **模块清单**：
  1. `PipelineManager._process_single_video` 核心状态调度器
  2. 微信上传器与浏览器底层交互 (`scripts/wechat_uploader.py`)
  3. 三表原子受理事务 (`record_wechat_submission_acceptance`)
- **验证方式**：必须在 Tier A/B 完成、离线 Golden Dataset 就绪且前序安全门全部通过后，方可实施。

---

## 13. Safety Gates (阶段流转强制安全门)

后续治理推进必须严格按以下门禁顺序推进，**严禁跳跃**：

```text
[Gate M5 → M6] 契约冻结与交接确认门
  - refactor_handoff.md 达到 v1.0.0 正式标准
  - 0 运行时代码修改
  - M5 Exit Checklist 100% 通过
         ↓
[Gate M6 → M6.5A] 安全线网与黄金数据集门 (Safety Harness only)
  - Characterization Baseline 100% 通过且完成双轨矩阵审计
  - 建立可执行离线回放 Golden Replay Dataset (覆盖 10 大故障模型与典型媒体场景)
  - 建立隔离单测环境与影子比对执行框架 (Shadow Harness)
  - 证明失败注入与回滚熔断就绪
  - 严禁修改生产代码，所有运行时工单依然保持 BLOCKED
         ↓
[Gate M6.5A → M6.5B / M7] 首个受控安全修复验收门 (First Guarded Remediation - WO-STATE-001 only)
  - 仅解锁并在安全网监控下实施 WO-STATE-001 (Telegram Bot 状态拦截加固)
  - WO-SCRIPTS-001 保持 STRICTLY PENDING / BLOCKED，留待 M6.5A 完全闭环后再行评估 (M6.5B)
  - 对应期望契约测试通过、旧不安全基线成功转换、回滚能力验证无损
  - 彻底消除 INV-008 生产违规 (KNOWN-VIOLATION 消除)
  - 核心发布不变式零回归
         ↓
[Gate M6.5B → M7] 运维脚本 DAL 边界收口门 (条件评估 - WO-SCRIPTS-001)
  - 仅在 M6.5A 验收通过后评估是否开启
         ↓
[Gate M7 → M8] Tier A 影子验证验收门
  - Tier A 模块上线 Shadow Mode 连续运行 ≥ 7 天
  - 影子比对日志达到 100% 吻合（零语义漂移）
         ↓
[Gate M8 → M9] Tier B 模块化委托门
  - PipelineDB 内部委托完成，对外 245 个 API（基于 2026-09-12 静态快照观测）保持方法签名与调用契约零改动
  - 全量单元测试与回归测试 100% 通过
```

---

## 14. Rollback Principles (回滚与应急熔断原则)

1. **开关即时熔断 (Feature Flag Kill-Switch)**：任何重构提取的新逻辑必须由配置开关（如 `enable_refactored_censor`, `enable_modular_douyin_ledger`）保护，开关默认保持为 `False`。出现任何异常，10 秒内切回旧逻辑。
2. **旧代码共存策略 (Old Path Fallback)**：旧实现代码在重构初期绝不物理删除，作为 fallback 逻辑常驻，确保在最坏情况下随时可以单点回滚。
3. **事务独立性保障**：新代码的持久化写如果失败，必须彻底回滚，严禁遗留中间状态破坏后续旧代码的执行。

---

## 15. Shadow Strategy (影子比对实施策略)

- **Direct Shadow (实时双跑)**：仅适用于 PURE_READ 与 DECISION。主流程调用旧代码，异步协程并发调用新代码，比对输出数据并记录 diff 日志，不影响主流程响应。
- **Replay/Offline Shadow (离线回放)**：适用于 LOCAL_SIDE_EFFECT（如文案生成、音视频剪切）。基于离线 Golden Dataset 在独立隔离沙箱中运行，比对输出文件的二进制指纹或元数据。
- **Persistence Dry-Run**：适用于 PERSISTENCE。在独立的内存数据库或事务未提交前（Rollback 模式）比对生成的 SQL 语句与行数据变化。
- **Never Blind Dual-Run**：**对于 EXTERNAL_SIDE_EFFECT 严禁进行生产环境双跑！** 外部发帖绝无影子模式，只能通过 Mock 验证。

---

## 16. Observability Requirements (可观测性指标要求)

重构后的模块必须提供以下可观测性支持：
- **结构化日志**：所有关键决策与状态变迁必须输出包含 `youtube_id`, `slice_index`, `previous_status`, `target_status`, `reason` 的 JSON 日志。
- **影子比对指标 (Shadow Metrics)**：记录 `shadow_match_count`, `shadow_mismatch_count`, `shadow_latency_diff_ms`。任何 mismatch 必须触发 ERROR 级别日志。
- **状态分叉告警**：定期巡检主表状态与发布账本状态的一致性，发现分叉立即通过 Telegram 运维频道告警。

---

## 17. Work Order Dependency Graph (工单依赖图谱)

```text
[Gate M5 完成]
      ↓
[Phase M6: 安全线网构建 (Safety Harness only)]
      - Characterization Baseline 建立与双轨审计 (M6.1)
      - M6.2 可执行黄金回放数据集建设 (Golden Replay Dataset)
      - 所有工单保持 BLOCKED
      ↓
[Gate M6 → M6.5A 通行检查]
      ↓
[Phase M6.5A: 首个受控安全修复 (First Guarded Remediation - WO-STATE-001 only)]
      └── WO-STATE-001 (Telegram Bot 状态拦截加固) [P1, 运行时]
      ↓
[Gate M6.5A → M6.5B / M7 通行检查]
      ↓
[Phase M6.5B: (条件评估) 脚本 DAL 边界收口 - WO-SCRIPTS-001]
      └── WO-SCRIPTS-001 (脚本 DAL 边界收口) [P2, 运行时]
      ↓
[Gate M6.5B → M7 通行检查]
      ↓
[Phase M7: 影子比对验收 (Tier A)]
      ├── WO-SHADOW-001 (只读查询影子验证) [P2, 运行时]
      └── WO-SHADOW-002 (决策引擎影子验证) [P2, 运行时]
      ↓
[Phase M8: 模块化委托 (Tier B)]
      └── WO-DB-001 (PipelineDB 内部委托重构) [P3, 运行时]
      ↓
[Phase M9+: 核心调度与发布解耦 (Tier C)]
      ├── WO-PIPE-001 (_process_single_video 阶段接缝提取) [P1, 运行时]
      └── WO-PUB-001 (发布执行层标准化迁移) [P0, 最后一公里]
```

---

## 18. Known Unknown Triage (已知未知项处置方案)

- **`UNK-001`: 同进程异步改造对事件循环的压力**
  - *处置策略*：保持子进程隔离调用（`_run_tracked`）作为生产基线；仅在测试沙箱中进行同进程异步压测。
- **`UNK-002`: 无头浏览器面对反爬与弹窗的异常行为**
  - *处置策略*：在 Gate M6 构建无头浏览器 Mock 注入套件，模拟各种网络超时与验证码场景。
- **`UNK-003`: 容器化（Docker/K8s）环境下的进程组信号穿透**
  - *处置策略*：**DEFERRED / CONDITIONAL**。当前线上采用原生宿主机（macOS / Linux 独立环境）部署，容器化未在近期规划内，待未来启动容器化时再行深入评估。

---

## 19. Resume Protocol (未来接手与恢复协议)

未来任何工程师或 AI Agent 重新接手本项目时，**必须**严格遵循以下恢复协议：

```text
步骤 1: 阅读 docs/refactor/video-processing/00_README.md (重温全局事实与安全红线)
          ↓
步骤 2: 核对当前所处阶段 (Phase) 与未完成的安全门 (Mandatory Gate)
          ↓
步骤 3: 严格检查并执行当前 Gate 所要求的安全 Harness
          ↓
步骤 4: 仅在当前 Gate 明确解锁 (UNBLOCKED) 的工单范围内进行小步实施
          ↓
步骤 5: 遵循“一次一个工单、测试必须通过、文档同步更新”铁律
```

---

## 20. M5 Exit Checklist (M5 阶段退出就绪检查表)

### 20.1 基础交接与架构契约完备性
- [x] **0 运行时代码修改**：未触动任何 Python, JavaScript, SQL 或 DB Schema 代码。
- [x] **20 个正式交接章节完整**：包含宗旨、架构、权威梯次、副作用、兼容性信封、8 项不变式、10 种故障模型、事务边界、工单图谱等。
- [x] **校准项已完全固化**：
  - `INV-006` 校准为 `Reconciliation Must Be Publication-Side-Effect-Free`。
  - `INV-008` 校准为 `Control Plane Destructive/Retry Operations Must Fail Closed on Existing Publication Evidence`。
  - `UNK-003` 已处置为 `DEFERRED / CONDITIONAL`。
- [x] **工单状态全部受控**：所有运行时工单显式标记为 `BLOCKED`，直至 Gate M6 安全线网就绪。
- [x] **接手恢复协议已明确**：确立以 Gate 驱动而非以优先级驱动的恢复顺序。

### 20.2 Documentation Integrity Gate (M5.1 文档完整性门禁)
- [x] **No dangling INV/RISK/UNK/WO references**：全文档 ID 交叉引用无悬空（0 悬空，Referenced IDs ⊆ Defined IDs）。
- [x] **No fictional source symbols**：兼容性信封仅列举经源码调用证实的真实入口，无虚构符号。
- [x] **Risk Register authoritative and complete**：正式风险登记表包含全部 12 个统一字段，唯一定义全部活跃风险。
- [x] **Retired IDs retain lifecycle history**：`RISK-STATE-002` 明确记录退役原因与生命周期继承路径。
- [x] **Snapshot numbers labeled as observations**：代码行数与方法数均明确标注为静态快照观测事实（~9.7k LOC, ~4.4k LOC, ~1k LOC, 245 方法）。
- [x] **created_at / last_updated_at are truthful**：时间戳客观真实，区分创建与更新时间，不伪造秒级精度。
- [x] **README phase synchronized**：`00_README.md` 与当前阶段（Phase M5.1）完全同步。

---

## Appendix A: Authoritative Risk Register (权威架构风险登记表)

本登记表为 `Video-precessing` 架构治理中唯一权威的风险源。所有工单与文档引用的 `RISK-xxx` 编号均在此唯一定义。

### A.1 活跃风险 (Active Risks)

#### RISK-STATE-001
- **ID**: `RISK-STATE-001`
- **Title**: Telegram Bot 无约束直接篡改工作流状态
- **Status**: `ACTIVE`
- **Severity**: `HIGH`
- **Likelihood**: `LOW`
- **Evidence confidence**: `HIGH`
- **Statement**: Telegram Bot 指令直接调用 `self.db.update_video_status`，未接入 Web 控制台的防重投 Guard 校验。若管理员对正处于 `PUBLISHED` 或 `UNDER_REVIEW` 的视频执行重置或状态变更，会绕过发布保护强行打回 `PENDING`，引发状态机分叉。
- **Evidence**: [`src/bot/pipeline_agent.py:L714,L749`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/bot/pipeline_agent.py#L714)
- **Current mitigation**: 目前仅限白名单管理员在受限群组内手动执行。
- **Related invariants**: `INV-001`, `INV-008`
- **Related work orders**: `WO-STATE-001`
- **Disposition**: `ACTIVE`（待 Gate M6 建立安全 Harness 与测试用例后实施修复）。

#### RISK-DB-001
- **ID**: `RISK-DB-001`
- **Title**: 微信发布受理强依赖 SQLite 进程内多表事务原子性
- **Status**: `ACTIVE`
- **Severity**: `HIGH`
- **Likelihood**: `LOW`
- **Evidence confidence**: `HIGH`
- **Statement**: `PipelineDB.record_wechat_submission_acceptance` 涉及 `wechat_publications`、`wechat_submission_attempts` 与 `processed_videos` 三表在单一数据库事务内的原子覆写。若在 DAL 重构中轻率将事务拆分至不同连接或异步上下文，将导致局部提交脏数据或死锁。
- **Evidence**: [`src/video_processing/db/database.py:L3261-L3358`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/db/database.py#L3261)
- **Current mitigation**: 单一 `PipelineDB` 实例持有数据库连接上下文，由 WAL 模式强事务保障。
- **Related invariants**: `INV-007`
- **Related work orders**: `WO-DB-001`
- **Disposition**: `ACTIVE`（在 Tier B 内部模块化委托时，必须保持单连接事务透传，严禁拆分事务）。

#### RISK-DB-002
- **ID**: `RISK-DB-002`
- **Title**: 运维脚本绕过 DAL 直接执行原生 SQL 导致数据访问契约发散与维护脆弱性
- **Status**: `ACTIVE`
- **Severity**: `MEDIUM`
- **Likelihood**: `HIGH`
- **Evidence confidence**: `HIGH`
- **Statement**: 离线运维脚本直接调用 `db.get_connection()` 执行原生 `SELECT` 与 `UPDATE`，违反了项目工程宪法中“所有原生 SQL 必须严格封装在 DAL 方法内部”的架构契约，导致未来表结构重构或字段重命名时无法通过静态代码分析收口。
- **Evidence**: [`scripts/backfill_metadata.py:L12,L41`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/scripts/backfill_metadata.py#L12) 与 [`scripts/regen_published_covers.py:L14`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/scripts/regen_published_covers.py#L14)
- **Current mitigation**: 仅在手动运维脚本中使用，不进入核心流水线自动化高频调度。
- **Related invariants**: 项目工程宪法 DAL 封装原则（Section 7.1）
- **Related work orders**: `WO-SCRIPTS-001`
- **Disposition**: `ACTIVE`（待 Gate M6 在 `PipelineDB` 中增加标准 DAL 封装方法后完成脚本收口）。

#### RISK-PIPE-001
- **ID**: `RISK-PIPE-001`
- **Title**: `_process_single_video` 大单体混编状态编排与底层 I/O 实现
- **Status**: `ACTIVE`
- **Severity**: `HIGH`
- **Likelihood**: `HIGH`
- **Evidence confidence**: `HIGH`
- **Statement**: `PipelineManager._process_single_video` 长达约 1k 行，将下载、切片、文案、字幕压制、敏感词审查、封面渲染及多平台发布等 8 个阶段混在一个函数体内，阶段间通过局部变量隐式传参，异常处理与检查点判断高度交织，修改爆炸半径极大。
- **Evidence**: [`src/video_processing/pipeline_manager.py:L3268-L4280`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/pipeline_manager.py#L3268)
- **Current mitigation**: 依靠现有单元测试套件提供基本回归保障。
- **Related invariants**: `INV-002`, `INV-003`
- **Related work orders**: `WO-PIPE-001`, `WO-SHADOW-002`
- **Disposition**: `ACTIVE`（待 Gate M9 依赖离线黄金数据集 Golden Replay Dataset 逐步提取阶段处理器）。

#### RISK-PIPE-002
- **ID**: `RISK-PIPE-002`
- **Title**: 复杂只读查询与多账本聚合逻辑重构存在输出投影漂移风险
- **Status**: `ACTIVE`
- **Severity**: `LOW`
- **Likelihood**: `LOW`
- **Evidence confidence**: `HIGH`
- **Statement**: `PipelineDB.get_paginated_videos` 包含复杂的跨表动态 JOIN、字段聚合与分页排序。在对其进行解耦重构时，若缺乏基于生产真实请求的影子比对，微小逻辑变动可能导致分页漂移或数据漏显，影响 Web 控制台展示。
- **Evidence**: [`src/video_processing/db/database.py:L4587`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/db/database.py#L4587)
- **Current mitigation**: 纯只读操作，不产生持久化写或外部发布副作用。
- **Related invariants**: `INV-001`
- **Related work orders**: `WO-SHADOW-001`
- **Disposition**: `ACTIVE`（待 Gate M7 启动 Shadow Mode 实施 7 天只读并行比对验证）。

#### RISK-PUB-001
- **ID**: `RISK-PUB-001`
- **Title**: 外部社交平台发帖具有物理不可逆性
- **Status**: `ACTIVE`
- **Severity**: `CRITICAL`
- **Likelihood**: `LOW`
- **Evidence confidence**: `HIGH`
- **Statement**: 微信视频号、抖音与快手平台一旦调用浏览器完成物理发帖，操作无法在平台端撤回，重构过程中的逻辑瑕疵可能直接导致重复投递、违规封禁或凭据混乱。
- **Evidence**: `scripts/wechat_uploader.py`, `_publish_claimed_douyin_publication`, `_queue_and_publish_new_kuaishou_video`
- **Current mitigation**: 多层纵深防御：基于 `asset_sha256` 物理排重、一次性 Ticket 消费协议、SQL 预过滤及磁盘截图证据链。
- **Related invariants**: `INV-003`, `INV-004`, `INV-005`, `INV-007`
- **Related work orders**: `WO-PUB-001`
- **Disposition**: `ACTIVE`（作为 Last Mile 最后一公里迁移单元，必须在前序所有 Gate 验证通过后实施）。

---

### A.2 退役风险与历史记录 (Retired Risks / Risk History)

#### RISK-STATE-002
- **ID**: `RISK-STATE-002`
- **Title**: 主状态写入源多头化且缺乏统一状态机实体 (Historical Overview Risk)
- **Status**: `RETIRED`
- **Severity**: `HIGH`
- **Likelihood**: `MEDIUM`
- **Evidence confidence**: `HIGH`
- **Statement**: 主表状态 `processed_videos.status` 存在 5 个独立写入源（FSM、Web 路由、对账 Worker、审查服务、Telegram Bot），系统缺乏单一的状态机跃迁实体。
- **Evidence**: M3 状态调查事实（`PipelineManager`, `app.py`, `pipeline_agent.py`, `censor_engine.py`）
- **Current mitigation**: 各写入入口均具备既有局部守卫。
- **Related invariants**: `INV-001`, `INV-008`
- **Related work orders**: N/A (Superseded)
- **Disposition**: `RETIRED`
- **退役与生命周期历史 (Lifecycle History)**:
  - **产生背景**：在 Phase M3 状态调查中作为全局定性风险提出，记录主状态存在 5 类调用源的事实。
  - **退役原因**：经 Phase M4/M5 深入分析，写入源中唯二具备业务写冲突可能的是 Web 控制面与 Telegram Bot。其中 Web 端 9 处入口均已统一接入 `_wechat_submission_guard_reason` 校验；唯一未受控的 Telegram Bot 入口已明确下沉为独立高优先级风险 `RISK-STATE-001` 并由专属工单 `WO-STATE-001` 修复。状态机调度与发布事实的顶层冲突则被系统不变式 `INV-001`（工作流状态≠发布事实）与 `INV-008`（破坏性操作统一 Fail-Closed）全面封顶；远期调度器重构由 `WO-PIPE-001` 承接。
  - **继承关系**：本编号正式退役（RETIRED），具体风险与治理动作已完全下沉至 `RISK-STATE-001`、`INV-001`、`INV-008` 与 `WO-PIPE-001`，不再作为未分配工单的悬空风险追踪。

