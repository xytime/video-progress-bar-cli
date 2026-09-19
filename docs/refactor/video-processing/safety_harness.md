---
created_by: Gemini_3.8_Flash_planning
created_at: 2026-09-12
last_updated_at: 2026-09-12
version: 1.5.0
---

# Video-precessing 安全基线与不变式防护网 (Safety Harness & Invariants Coverage)

## Version History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.5.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.2 阶段启动：M6.1 特征化基线正式签署完结，启动可执行黄金回放数据集 (Golden Replay Dataset) 建设 |
| 1.4.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.1D 独立防线与去重审计：分离 Publication Fact 与 Defense，消除微信与快手防线重复计算，引入 Protection Dimensions 与 Control Families 多维结构，修复 Checklist 内部矛盾 |
| 1.3.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.1C 防线合格性审计：严格区分 Publication Safety Defense 与 Supporting Integrity Control，剔除 Attempt 唯一性防重计数，替换故障域为共模依赖分析，纠偏快手候选过滤单测断言缺失并降级 INV-003 为 PARTIAL |
| 1.2.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.1B 语义审计与防线校准：逐层严格定义 INV-003 六层防线语义，纠正 UNIQUE 约束为 Attempt Identity Integrity，校准 Candidate Exclusion 与 Evidence Guard 平台适用性，修正 INV-001 降级理由，路线图收敛为 M6.5A 单工单解锁 |
| 1.1.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.1A 证据校准与审计：引入生产满足度与测试覆盖度双轨矩阵，严重纠偏 INV-008 为 KNOWN-VIOLATION，校准 INV-006 零发布端副作用语义，细化 INV-003 分层矩阵，消除 M6.5 路线冲突 |
| 1.0.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.1 阶段创建：确立 INV-001~INV-008 初版覆盖矩阵、测试分类体系与沙盒隔离测试凭证 |

---

## 1. Safety Harness Overview (安全防护网目标与原则)

Safety Harness 是在对单体 `PipelineDB` 与 `PipelineManager` 展开任何物理重构前，建立的一组**高保真行为锁定与回归防护测试网**。

### 核心审计原则
1. **双轨分离评估**：必须严格区分 **Production Satisfaction（线上生产代码是否真正满足该不变式）** 与 **Test Coverage（自动化测试是否已完整覆盖该不变式）**。禁止因“有测试跑通”而掩盖生产缺陷。
2. **零容忍虚假 COVERED**：任何存在已知生产违规、未覆盖全部平台分支、或缺少关键防线直接断言的不变式，不得标记整体 `COVERED`。
3. **真实 SQLite 与沙盒隔离**：禁止使用“全 Mock DB”充当通过证明；核心不变式必须在真实独立 SQLite 文件库上由沙盒隔离执行器验证。
4. **Golden Scenario Manifest ≠ Golden Replay Dataset**：M6.1 阶段仅完成场景规范（Specification）；可执行黄金回放数据集（Dataset）留待 M6.2 建设。
5. **独立发布安全防线准入三要素 (Independent Defense Criteria)**：
   - A. **Prevention relevance**：该机制实际参与阻止已存在、在途或等价内容再次跨越外部 publication boundary。
   - B. **Enforcement point**：存在真实代码路径在外部提交前使用该机制进行 allow/deny 或 candidate inclusion/exclusion。
   - C. **Failure independence**：不能只是另一个已计入机制所使用的同一个事实或同一个判断的重复命名。
6. **发布事实与发布防线分离 (Publication Fact ≠ Publication Defense)**：
   - **Publication Fact**：已发生/已受理发布的本地权威记录（如数据库 `wechat_publications` 行、文件系统物理截图证据）。
   - **Publication Defense**：在特定执行入口（Enforcement Point）读取该事实并执行拒重/阻断的防护逻辑。
   - **保护维度 (Protection Dimension) ≠ 独立执行点 (Enforcement Point)**：同一 SQL/函数内同时评估的身份维度与内容维度（如快手 `video_id OR asset_sha256`）属于双重保护维度，但在执行拓扑上是单一 Enforcement Point，禁止拆为两条独立防线重复计算。

---

## 2. Invariants Dual-Track Evaluation Matrix (不变式双轨评估矩阵)

| 不变式编号与名称 | 正式契约声明 (Formal Statement) | 生产满足度 (Production Satisfaction) | 测试覆盖度 (Test Coverage) | 证据置信度 (Confidence) | 审计结论与调整说明 (Audit Notes) |
| --- | --- | --- | :---: | :---: | :---: | --- |
| **INV-001**<br>工作流状态非客观发布事实 | `workflow state != publication truth`<br>工作流调度状态受控制面干预，客观发布事实以各平台账本（Ledger）为准。 | **SATISFIED** | **PARTIAL**<br>*(从 COVERED 降级)* | **HIGH** | **降级理由纠偏**：原 M6.1 错配切片测试。真实证据证明主状态与账本可分叉且决策严格优先账本（微信通道已由真实单测验证 Authority Semantics：分叉不重发、对账可修复），但抖音与快手通道尚未建立针对“主状态分叉时决策严格服从账本”的专门特征化断言，因此 Test Coverage 评定为 PARTIAL。 |
| **INV-002**<br>凭据优于推断与关停防线 | `evidence outranks projection / fail-closed on evidence gap`<br>平台物理截图凭据与未删除账本阻断二次提交；缺失必要凭据时关闭发布通道。 | **SATISFIED** | **COVERED** | **HIGH** | 微信物理截图守卫（Fail-Closed Submission Guard）、快手/抖音审核中账本阻断、以及 Web `/republish` 缺失物理凭据拦截均有独立正反向测试。 |
| **INV-003**<br>多层级防御纵深幂等 | `supported publication paths contain multi-layer idempotency defenses`<br>各平台发布路径具备独立的发布安全防线（候选过滤、账本排重、成片哈希排重、执行授权等）。 | **SATISFIED** | **PARTIAL**<br>*(从 COVERED 降级)* | **HIGH** | **去重审计与多维建模**：消除 Double Counting（将微信 `wechat_publications` 唯一约束归位为 Authoritative Publication Fact，快手 `video_id OR asset_sha256` 归位为单一 Enforcement Point 内的双重 Protection Dimensions）。重新以「保护维度」与「控制族」建模后，三大平台均具备跨调度、入库、授权或前置探针的多重纵深防御能力，且微信具备完全独立的磁盘物理证据控制族，生产满足 SATISFIED；测试覆盖度因快手历史候选过滤缺少排除账本断言维持 PARTIAL。 |
| **INV-004**<br>成片媒体指纹强排重 | `asset_sha256 deduplication on publication`<br>基于成片二进制计算的 SHA256 在发布后阻止相同媒体重复投递。 | **SATISFIED (DY/KS)**<br>*NOT APPLICABLE (WC)* | **COVERED (DY/KS)**<br>*NOT APPLICABLE (WC)* | **HIGH** | **范围校准**：微信数据表无 `asset_sha256` 字段，该不变式仅适用于抖音与快手。抖音与快手成片排重均由真实单测证明。 |
| **INV-005**<br>单次使用浏览器凭据语义 | `one-time browser ticket semantics`<br>浏览器启动必须依赖单次有效、加密绑定、防篡改的临时凭据，严禁二次消费。 | **SATISFIED (DY)**<br>*NOT APPLICABLE (WC/KS)* | **COVERED (DY)**<br>*NOT APPLICABLE (WC/KS)* | **HIGH** | **范围校准**：仅适用于抖音；微信与快手无 Ticket 机制。测试已覆盖：虚假 ID、错 Token、篡改 Payload、合法首次消费、二次重放拒绝 5 个完整分支。 |
| **INV-006**<br>对账零发布端副作用 | `reconciliation must be publication-side-effect-free`<br>对账允许观测外部与更新本地账本/主状态，严禁触发新发布、二次上传、浏览器启动或消费凭据。 | **SATISFIED** | **PARTIAL**<br>*(从 COVERED 降级)* | **HIGH** | **语义与覆盖降级**：确证无发布端副作用。降级理由：真实 SQLite 端到端测试仅覆盖微信，抖音与快手回查测试依赖 Mock DB。 |
| **INV-007**<br>微信受理三表原子变更 | `3-table atomic state mutation in WeChat acceptance`<br>受理事实写入 `wechat_publications`、`wechat_submission_attempts` 与更新 `processed_videos` 必须在同事务原子完成。 | **SATISFIED** | **COVERED** | **HIGH** | 微信三表原子受理正向流转与 SQLite 触发器注入异常后的完整回滚（三表 0 残留）均有强断言验证。 |
| **INV-008**<br>控制面破坏/重试操作对账本 Fail-Closed | `control plane destructive/retry operations must fail closed on existing publication evidence`<br>Web 与 Bot 控制面在面对已有提交账本时必须拒绝重试或破坏性重置。 | **KNOWN-VIOLATION**<br>*(重大生产违规)* | **PARTIAL**<br>*(从 COVERED 降级)* | **HIGH** | **严重纠偏**：Web 控制面（`/reset-hard`, `/retry`）已实现 Fail-Closed 并有单测；但 Telegram Bot（`RISK-STATE-001`）直接调用无锁 DAL 强写 `PENDING`，构成已知生产违规。整体绝不能标 COVERED。 |

---

## 3. INV-003 Independent Defense & Double-Counting Audit (独立防线与重复计算审计)

### 3.1 独立防线准入原则与 Fact vs Defense 分离

1. **核心准入准则**：
   - 机制必须具备**直接阻止外部二次提交**的相关性（Prevention relevance）。
   - 机制必须拥有**真实的执行拦截入口**（Enforcement point）。
   - 机制必须具备**故障独立性**（Failure independence），不能将同一底层数据事实与其读取逻辑拆解重复计数。
2. **Publication Fact（发布事实）与 Publication Defense（发布防线）的本质差异**：
   - **Publication Fact**：表示已发生或已受理发布的客观权威记录（如数据库 `wechat_publications` 行、文件系统物理截图证据）。Fact 本身是静态的数据持久化，不主动执行代码拦截。
   - **Publication Defense**：在代码执行入口主动读取 Fact，并执行 `allow / deny`、`include / exclude` 或中断进程的动态防护逻辑。
   - **治理结论**：一个 Fact 往往被多个 Enforcement Points 使用；但绝不能把 Fact 本身与读取它的 Enforcement Point 分别算作两条“独立防线”。

### 3.2 微信防线解构与重复计算消除 (WeChat Defense Audit)

针对前期将微信判定为“3 层独立防线”展开三问专项复核：

- **Q1: `record_wechat_submission_acceptance` / `UNIQUE` 约束发生在提交前还是受理后？**
  - **源码实证**：[`PipelineManager.py:L927`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/pipeline_manager.py#L927)。
  - 该方法是在调用 `wechat_uploader.py` 退出且捕获到受理截图（`post_list_after_submission.png`）或回执后才调用的。
  - **结论**：发生于 **External submission AFTER acceptance**，属于客观发布事实的受理落库，非提交前主动拦截。
- **Q2: 第二次启动上传器前，是否有代码直接查询 Active Publication Identity 阻止发布？**
  - 真正拦截重发的执行入口是：
    1. 调度层：[`get_high_score_pending_videos`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/db/database.py#L4130) 使用 `NOT EXISTS (SELECT 1 FROM wechat_publications)` 过滤。
    2. 控制面：[`web/app.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/web/app.py#L842) `_wechat_submission_guard_reason` 拦截手动重置。
    3. 流程门：[`PipelineManager._has_wechat_submission_terminal_state`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/pipeline_manager.py#L961) 在 L3322 拦截标题升级与重跑。
    4. 前置硬阻断：[`PipelineManager._block_duplicate_wechat_submission_if_needed`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/pipeline_manager.py#L972) 在 L3320 与 L4094 探针熔断。
  - **结论**：`wechat_publications.video_id UNIQUE` 是 **SUPPORTING AUTHORITATIVE FACT**，上述入口才是 **ENFORCEMENT DEFENSES**。
- **Q3: 若 `wechat_publications` 行被删除，两者是否同时失效？**
  - **结论**：**YES**。一旦 DB 行被删，候选过滤与唯一性约束同时丧失依托。二者共享同一底层物理行，绝非独立 Failure Controls。此前分列属于 **Double Counting**。

#### 微信真实防御模型重塑 (Remodeled WeChat Defense Architecture)

| Control Family (控制族) | Fact / Evidence Source (事实与证据源) | Enforcement Point (判定与阻断入口) | Prevents External Re-submit? (阻止外部重投?) | Independent from Other Family? (故障独立性) |
| :--- | :--- | :--- | :---: | :---: |
| **Family A: DB Publication Fact & Lifecycle Gates** | `wechat_publications` 数据表物理行<br>*(Authoritative DB Fact, `video_id` UNIQUE)* | 1. 调度过滤：`get_high_score_pending_videos`<br>2. 控制面拦截：`web/app.py`<br>3. 任务边界门：`_has_wechat_submission_terminal_state` | **YES**<br>(阻断入队、阻断控制面重置、阻断流程推进) | 依赖 SQLite DB 与主流程状态一致性 |
| **Family B: Filesystem Physical Evidence & Pre-submit Guard** | 本地文件系统物理截图存证<br>`post_list_after_submission.png`<br>*(Independent Secondary Evidence)* | 流水线拉起上传器前置探针：<br>`_block_duplicate_wechat_submission_if_needed`<br>(在 L3320 与 L4094 硬熔断阻断启动子进程，退出码 10) | **YES**<br>(启动 Playwright 进程前强制熔断退出) | **YES**<br>(完全独立于 SQLite，即使 DB 行被误删，只要本地磁盘截图仍在即可独立阻断) |

### 3.3 抖音与快手去重与维度复核 (Douyin & Kuaishou Double-Count Check)

- **快手 (Kuaishou)**：
  - 源码实证：[`PipelineDB.create_kuaishou_publication:L7961`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/db/database.py#L7961) 包含：
    `WHERE state IN ('QUEUED', 'UPLOADING', 'UNDER_REVIEW', 'UNCERTAIN', 'PUBLISHED') AND (video_id = ? OR asset_sha256 = ?)`。
  - 判定：`video_id` (身份维度) 与 `asset_sha256` (内容维度) 是由**同一条 SQL 在同一个函数、同一个执行入口**一次性评估的。
  - 纠偏：它们属于 **两个保护维度 (Protection Dimensions)**，但属于 **同一个执行拦截点 (Single Enforcement Point)**。此前宣称两条完全独立防线属于重复计算，现重构为单一入库门禁下的双保护维度。
- **抖音 (Douyin)**：
  - 源码实证：
    1. `get_unqueued_douyin_new_videos` (L8948): `NOT EXISTS (SELECT 1 FROM douyin_publications dp WHERE dp.video_id = pv.id)` → 身份维度候选过滤（Enforcement Point 1: 调度查询）。
    2. `create_douyin_publication` (L8227): `SELECT * FROM douyin_publications WHERE asset_sha256 = ? AND state = 'PUBLISHED'` → 内容维度成片指纹排重（Enforcement Point 2: 登记入库）。
    3. `claim_next_douyin_publication` + `create_douyin_launch_ticket` (L8958, L9033): 租约行锁与单次有效 Ticket（Enforcement Point 3: 执行授权）。
  - 判定：抖音的身份候选过滤与成片指纹排重确实发生在不同函数与不同阶段，但成片指纹与发布账本均依托于 `douyin_publications` 同一物理表。

### 3.4 结构化多维矩阵 (Revised INV-003 Structural Matrix)

彻底弃用“独立防线总数 (3 层 / 4 层)”的主观表述，改用多维结构化表：

| Platform (平台) | Protection Dimensions (保护维度) | Key Enforcement Points (核心执行判定点) | Independent Evidence/Control Families (独立证据/控制族) | Test Coverage (测试覆盖度) |
| :--- | :--- | :--- | :--- | :---: |
| **微信 (WeChat)** | 1. 任务身份维度 (video_id)<br>2. 磁盘物理证据维度 (screenshot) | 1. 调度候选过滤 (`get_high_score_pending_videos`)<br>2. 控制面重试拦截 (`_wechat_submission_guard_reason`)<br>3. 流程边界检查 (`_has_wechat_submission_terminal_state`)<br>4. 前置探针熔断 (`_block_duplicate_wechat_submission_if_needed`) | **Family A**: 数据库发布事实与生命周期门禁<br>**Family B**: 文件系统物理截图探针硬阻断 | **`COVERED`** |
| **抖音 (Douyin)** | 1. 任务身份维度 (video_id)<br>2. 成片物理内容维度 (asset_sha256)<br>3. 执行时效授权维度 (ticket/lease) | 1. 调度候选过滤 (`get_unqueued_douyin_new_videos`)<br>2. 登记入库指纹排重 (`create_douyin_publication`)<br>3. 任务抢占租约锁 (`claim_next_douyin_publication`)<br>4. 浏览器启动凭据校验 (`begin_douyin_browser_launch`) | **Family A**: 数据库发布事实与调度门禁<br>**Family B**: 成片物理指纹查重<br>**Family C**: 单次有效浏览器凭据与租约锁 | **`COVERED`** |
| **快手 (Kuaishou)** | 1. 任务身份维度 (video_id)<br>2. 成片物理内容维度 (asset_sha256)<br>3. 任务抢占租约维度 (worker claim) | 1. 历史迁移候选过滤 (`get_unqueued_kuaishou_history_videos`)<br>2. 登记入库身份与指纹联合门禁 (`create_kuaishou_publication`)<br>3. 任务抢占租约锁 (`claim_next_kuaishou_history_publication`) | **Family A**: 数据库发布事实与历史候选过滤<br>**Family B**: 登记入库联合排重 (身份+内容双维度)<br>**Family C**: Worker 抢占租约锁 | **`PARTIAL`**<br>*(历史候选过滤单测断言缺失)* |

### 3.5 修复 M6.1C Checklist 内部矛盾声明

- **冲突根源**：前期 Checklist 声明“每项防线均精准绑定隔离测试断言”，但同时在正文中将快手候选过滤标记为 `MISSING`，形成字面矛盾。
- **契约修正**：正式更正 Checklist 为：**“所有被计入的生产控制机制均已绑定确凿源码实现证据，其实行覆盖度均已显式映射为 TEST-PROVEN、PARTIAL 或 MISSING，不存在未经验证的推断覆盖。”**
- **原则承诺**：坚决不为了让表格变绿而人为将快手历史候选过滤改为 COVERED，诚实保留 `MISSING` 与 `PARTIAL` 状态。

---

---

---

## 4. INV-006 Reconciliation Reachability & Side-Effect Audit (对账可达性与副作用审计)

### 4.1 正式契约语义校准
- **允许的副作用 (Allowed Local Side Effects)**：外部状态观测、本地 publication 账本状态更新（`PUBLISHED` / `UNDER_REVIEW` / `REJECTED`）、工作流投影修复（`processed_videos.status` 同步）、审计证据写入。
- **严禁的副作用 (Prohibited Publication Side Effects)**：创建新发布记录、媒体文件二次重新上传、启动发帖浏览器上下文、消费发帖 ticket。

### 4.2 三大平台对账调用可达性分析 (Contradiction Search)
| 平台 | 对账入口方法 | 允许的本地写操作 | 是否可达发帖提交？ | 是否消费发帖凭据？ | 已执行测试 | 测试覆盖状态 |
| :--- | :--- | :--- | :---: | :---: | :--- | :---: |
| **WeChat** | `reconcile_wechat_under_review` | `record_wechat_publication_confirmation`<br>`update_video_status` | 否（仅传 `--verify-only`） | 否 (N/A) | `test_characterization_baseline.py` (真实 SQLite) | **COVERED** |
| **Douyin** | `reconcile_douyin_under_review` | `reserve_douyin_reconciliation_slot`<br>`update_douyin_publication_state` | 否（仅传 `--verify-only`，无 `--publish`） | 否（不调用 `begin_douyin_browser_launch`） | `test_douyin_pipeline.py` (Mocked DB) | **PARTIAL** |
| **Kuaishou** | `reconcile_kuaishou_under_review` | `update_kuaishou_publication_state` | 否（仅传 `--verify-only`） | 否 (N/A) | `test_kuaishou_pipeline.py` (Mocked DB) | **PARTIAL** |

---

## 5. INV-008 Deep-Dive: Known Violation Analysis (已知生产违规审计)

### 5.1 违规事实与代码位置
- **违规入口**：[`src/bot/pipeline_agent.py:L714,L749`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/bot/pipeline_agent.py#L714)
  ```python
  # PipelineAgent.retry_video_in_db
  self.db.update_video_status(youtube_id, "PENDING", error_msg=None)
  ```
- **违规机制**：Telegram Bot 运维命令直接调用底层 `PipelineDB.update_video_status`。该 DAL 方法直接执行原生 SQL UPDATE，**完全未校验该视频是否已有 `wechat_publications` 提交账本，也未检查是否已在外部平台公开**。
- **违规后果**：管理员在 Telegram 中误发重试指令时，可将已提交或已发布的视频强行置回 `PENDING`，直接破坏 `INV-008`。

### 5.2 子覆盖范围矩阵 (Subcoverage Breakdown)
- **Web 控制面硬重置 (`/api/videos/{yid}/reset-hard`)**：`SATISFIED` & `COVERED`（在已有提交账本时返回 `success: false`，Fail-Closed）。
- **Web 控制面重试 (`/api/videos/{yid}/retry`)**：`SATISFIED` & `COVERED`（在 `PUBLISHING` 或有账本时拒绝）。
- **Web 控制面二次发布 (`/api/videos/{yid}/republish`)**：`SATISFIED` & `COVERED`（无平台物理删除证明时拒绝）。
- **Telegram Bot 控制面 (`update_video_status / retry_video_in_db`)**：**`KNOWN-VIOLATION`**（无状态锁、无账本检查直接覆盖）。
- **测试现状**：在 [`test_characterization_baseline.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/tests/unit/test_characterization_baseline.py) 中以 `KNOWN-UNSAFE-BASELINE` 明确记录。

---

## 6. Golden Scenario Manifest vs. Executable Golden Replay Dataset

| 维度 | M6.1 黄金场景清单 (Golden Scenario Manifest) | M6.2 可执行黄金回放集 (Executable Golden Replay Dataset) |
| :--- | :--- | :--- |
| **当前状态** | **已完成 (SPECIFICATION COMPLETE)** | **未开始 (PLANNED FOR M6.2)** |
| **文件形态** | [`characterization_matrix.md`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/refactor/video-processing/characterization_matrix.md) 中的确定性元数据与预期不变式 JSON 规范 | 物理媒体切片、ASS 字幕快照、真实 SQLite 夹具与影子比对输入文件集合 |
| **凭据安全性** | 100% 合成数据，零外部真实 Token、零网络依赖 | 100% 离线脱敏脱密，静态哈希锁定 |
| **执行能力** | 声明测试场景的标准输入与断言期望 | 支持在回放框架中直接挂载并驱动离线端到端重放 |

---

## 7. Roadmap Conflict Resolution: Phase M6.5 (治理路线图冲突校准)

消除此前文档中“Gate M6 退出直接进入 M7 影子模式”与“M6 期间修复 WO-STATE-001”的路线冲突。

正式校准路线图如下：
```text
[Gate M5 完成: 交接契约签署]
      ↓
[Phase M6: 安全线网构建 (Safety Harness only)]
      - M6.1: 特征化测试基线建立与 Invariants 覆盖校准
      - M6.2: 可执行黄金回放数据集 (Golden Replay Dataset) 建设与 Harness 验收
      - 规则：严禁修改任何生产代码，所有工单保持 BLOCKED
      ↓
[Gate M6 → M6.5A 通行检查]
      - Characterization Baseline 100% 通过
      - Golden Replay Dataset 完备
      - Harness & Failure Injection 证据齐全
      - 熔断开关与回滚机制已就绪
      ↓
[Phase M6.5A: 首个受控安全修复 (First Guarded Remediation - WO-STATE-001 only)]
      - 仅解锁并实施 WO-STATE-001 (Telegram Bot 状态防篡改校验加固，修复 RISK-STATE-001)
      - WO-SCRIPTS-001 保持 STRICTLY PENDING / BLOCKED
      ↓
[Gate M6.5A → M6.5B / M7 通行检查]
      - desired contract tests pass
      - old unsafe baseline converted
      - rollback proven
      - no publication regression
      - 消除 INV-008 KNOWN-VIOLATION
      ↓
[Phase M6.5B: (条件评估) 脚本层 DAL 封装 - WO-SCRIPTS-001]
      - 仅在 M6.5A 彻底通过后才评估是否解锁
      ↓
[Gate M6.5B → M7 通行检查]
      ↓
[Phase M7: 影子比对验收 (Tier A Shadow Mode)]
      ├── WO-SHADOW-001 (只读查询影子验证)
      └── WO-SHADOW-002 (决策引擎影子验证)
      ↓
[Phase M8: 模块化委托 (Tier B Modular Delegation)]
      └── WO-DB-001 (PipelineDB 内部委托重构)
      ↓
[Phase M9+: 核心调度与发布解耦 (Tier C)]
      ├── WO-PIPE-001 (_process_single_video 阶段接缝提取)
      └── WO-PUB-001 (外部多平台发布网关模块化)
```

---

## 8. Contradiction Search & Counterexample Log (独立反证审计)

| 不变式 | 反证提问 (If false, what code path violates it?) | 代码排查路径 | 是否发现反例？ | 处置结论 (Disposition) |
| --- | --- | --- | :---: | --- |
| **INV-001** | 是否存在某条路径把主状态当作唯一客观发布事实？ | Bot retry / Web reset | **是**（Bot 强改主状态，但 uploader 依然检查账本） | 账本胜过主状态（微信通道验证），抖音/快手尚缺状态分叉时决策严格服从账本的单测断言，生产满足，测试覆盖为 PARTIAL。 |
| **INV-002** | 是否存在无物理截图凭据却被确认为已发布的路径？ | `reconcile_wechat_under_review` / Web republish | 否（缺失截图时直接 continue，不改状态） | 凭据优于推断与缺失关停成立，COVERED。 |
| **INV-003** | 是否存在任意一条发布通道缺少多层幂等防线？ | 三大平台主调度与重试链路 | 否（消除重复计算后，各通道均具备跨调度、入库、授权或前置探针的多重纵深防御） | 生产满足 SATISFIED；因快手历史候选过滤缺少排除账本的单测断言，测试覆盖严格降级为 PARTIAL。 |
| **INV-004** | 微信通道是否支持成片指纹排重？ | `wechat_publications` 表结构 | **是（发现反例：微信不支持）** | 校准适用范围为抖音/快手，微信标为 N/A。 |
| **INV-005** | 是否能用同一 ticket 启动两次抖音浏览器？ | `begin_douyin_browser_launch` | 否（原子事务标记 `launch_started_at`，二次拒绝） | 单次凭据语义成立，COVERED。 |
| **INV-006** | 对账方法是否会意外触发真实视频投稿？ | 三大平台 `reconcile_*` 方法 | 否（全部硬编码 `--verify-only`） | 零发布端副作用成立；因缺少部分真实库单测降为 PARTIAL。 |
| **INV-007** | 微信受理写入中途崩溃是否会破坏一致性？ | `record_wechat_submission_acceptance` | 否（触发器注入中止后三表均回滚） | 三表原子性成立，COVERED。 |
| **INV-008** | 控制面是否能在已有账本时直接重置视频？ | Bot `update_video_status` | **是（发现生产重大违规）** | 生产满足度定为 KNOWN-VIOLATION，测试覆盖降为 PARTIAL。 |

### 8.2 架构级共模旁路反证分析 (Common-Mode Bypass Audit)

针对 INV-003 各平台多层防线，反证排查“最可能导致全线防重被穿透的共模旁路”：
1. **微信通道共模旁路**：
   - **路径**：`手动/Bot 篡改主状态为 PENDING` + `物理删除本地 wechat_evidence/ 目录`（或直接通过 CLI 调用 `scripts/wechat_uploader.py`）。
   - **穿透分析**：直接通过 ID 指定处理视频会旁路 `get_high_score_pending_videos`（候选过滤失效）；若本地截图目录被删除，`_block_duplicate_wechat_submission_if_needed` 检测为 False（前置硬阻断失效）；最终上传器被唤起。
   - **结论**：证明本地文件系统截图与 DAL 状态存在紧密耦合，`WO-STATE-001` 收口 Bot 随意改状态是唯一根治手段。
2. **抖音通道共模旁路**：
   - **路径**：`成片微调重新导出 (New Asset Hash)` + `新视频入队`（或直接调用 `scripts/douyin_uploader.py`）。
   - **穿透分析**：若源视频仅修改 1 帧或 1 字节，`asset_sha256` 发生漂移，成片指纹排重失效；Ticket 机制仅防单次凭据重放，对新任务会签发新 Ticket。
   - **结论**：指纹排重依赖于媒体文件的确定性哈希，若上游重复剪辑导致哈希变化，防线将后撤至平台侧自带的去重机制。
3. **快手通道共模旁路**：
   - **路径**：`新视频事件派发` + `新成片哈希`。
   - **穿透分析**：快手新片无独立候选过滤 SQL，若微信发布成功后派发的视频使用了新渲染的素材（新哈希），Queue Dedup 与 Asset Dedup 将双双放行。
   - **结论**：多层防线虽位于不同调度时机（调度前 SQL、入队创建时查重、Worker 领取锁、上传前文件检查），并非单一 if 的重复包装，但在面对“成片内容重新生成”或“直接绕过 PipelineManager 执行 uploader 脚本”时存在共模短板。

---

## 9. Testability Gaps Register (可测性断层登记)

1. **`TESTABILITY-GAP-001` (PipelineManager 子进程执行硬编码耦合)**：`_process_single_video` 内部直接调用 `subprocess.Popen`，轻量单测无法端到端拉通，需在 M6.5A/M6.5B/M9 引入 Runner 抽象。
2. **`TESTABILITY-GAP-002` (平台上传器强绑定 Playwright)**：沙盒环境无法直接拉起真实平台页面，需依赖 CLI 参数守卫与凭据隔离单测。
3. **`TESTABILITY-GAP-003` (Telegram Bot 直连 DB 绕过状态机)**：已作为 `KNOWN-UNSAFE-BASELINE` 锁定，将在 M6.5A 通过 `WO-STATE-001` 彻底修复。

---

## 10. Isolated Test Execution Trace (沙盒测试执行凭证)

- **执行器契约**：使用 `.venv/bin/python scripts/run_isolated_tests.py`，受控于 macOS seatbelt 沙盒与 Canary 边界探测文件，零外部网络连接。
- **最新执行事实**：
  - `tests/unit/test_characterization_baseline.py`：**7 passed in 2.00s** (退出码 0，凭证 `/private/tmp/video-pytest-gofq4ern/receipt.json`)。
  - `tests/unit/test_golden_replay_dataset.py` (M6.2 回放数据集)：**8 passed in 2.35s** (退出码 0，凭证 `/private/tmp/video-pytest-zyxog39g`)。
  - 联合回归套件 (`test_characterization_baseline.py` + `test_golden_replay_dataset.py`)：**15 passed in 2.08s** (退出码 0，凭证 `/private/tmp/video-pytest-q9y8ycs_`)。
  - 全量隔离单元测试套件：**1626 passed in 37.83s** (退出码 0，凭证 `/private/tmp/video-pytest-n8lr7hws/receipt.json`)。
  - *执行证据审计说明*：测试通过（Passing count）仅证明受试断言执行成功，不代表 Invariant 已 100% 完整覆盖；整体评估以第 2 节双轨矩阵为准。
