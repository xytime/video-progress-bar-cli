---
created_by: Gemini_3.8_Flash_planning
created_at: 2026-09-12
last_updated_at: 2026-09-12
version: 1.4.0
---

# Video-precessing 特征化测试矩阵与黄金场景清单 (Characterization Matrix & Golden Manifest)

## Version History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.4.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.1D 审计对齐：对齐 Publication Fact 与 Defense 分离，确认各场景与多维控制族映射关系 |
| 1.3.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.1C 防线合格性审计：严格对齐 Publication Safety Defense 准入标准，标记快手候选过滤单测断言缺失事实 |
| 1.2.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.1B 语义完整性纠偏：校准 KS-02 为账本与指纹排重而非磁盘截图阻断，对齐 M6.5A 路线图引用 |
| 1.1.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.1A 审计校准：清理误导性绝对词，增加执行状态列明确分离“已执行验证”与“待执行规范”，纠正 W-01/W-05/W-06 测试映射，明确黄金清单为规范而非执行集 |
| 1.0.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.1 阶段创建：确立工作流、三大平台发布、控制面特征化场景初版与黄金场景清单规范 |

---

## 1. Scope & Principles (范围与核心原则)

在任何生产实现代码被修改或解耦之前，必须先建立证明“现有系统今天到底如何工作”的特征化测试基线。

### 核心原则
1. **Protect existing behavior before improving implementation**（在改进实现前，先保护现有行为）。
2. **规范声明与执行证据分离**：表格中声明的场景若尚未建立独立可执行测试，必须显式标注为 `SPECIFIED / NOT YET EXECUTED`，禁止将“场景存在”等同于“已测试覆盖”。
3. **零生产侵入**：特征化测试仅针对现有实现建立黑盒/状态机观测网，严禁修改任何生产运行时代码。
4. **零外部网络与无害化**：所有平台交互、浏览器启动、外部 CLI 均通过沙盒隔离、临时 SQLite 库与边界 Mock 保证测试无害、确定性及幂等。
5. **四级测试分类体系**：
   - `CONTRACT`：核心调用契约与系统不变式，未来重构必须保持严格保真（如原子事务、凭据哈希校验）。
   - `SAFETY-REGRESSION`：既有安全守卫与防御纵深回归测试，阻止非法的重试/重置/重投（Fail-Closed）。
   - `CHARACTERIZATION ONLY`：精确记录当前生产代码特定流转行为，作为后续渐进重构的客观比对基准。
   - `KNOWN-UNSAFE-BASELINE`：记录已识别的不安全/缺陷行为基线（如 `RISK-STATE-001`），**严禁当作正确行为巩固**，仅用于证明重构前的问题真实存在。

---

## 2. Characterization Scenarios Matrix (特征化场景矩阵)

### 2.1 Workflow Lifecycle Progression (工作流生命周期流转)

| 场景编号 | 场景名称 | 触发条件 / 输入 | 预期状态流转 / 行为 | 分类 | 关联不变式 / 风险 | 执行状态 (Execution Status) | 测试用例位置 |
| --- | --- | --- | --- | --- | --- | :---: | --- |
| **W-01** | 标准单视频全流程推进 | 评分 ≥ 75，单视频源 | `PENDING` → `DOWNLOADING` → `COPYWRITING` → `TRANSCRIBING` → `PUBLISHING` → `PUBLISHED` | `CONTRACT` | `INV-001` | **SPECIFIED / NOT YET EXECUTED**<br>*(受限 TESTABILITY-GAP-001)* | 待 M6.2/M6.5A/M6.5B/M9 Runner 抽象注入后补充 |
| **W-02** | 长视频切片流转 | 长视频启用切片，拆解为 N 个分段 | 父任务状态置为 `SEGMENTED`；子切片记录生成独立 `(youtube_id, slice_index)`，`parent_id` 指向父记录，状态初始化为 `PENDING` | `CHARACTERIZATION ONLY` | `INV-001` | **EXECUTED (TEST-PROVEN)** | [`tests/unit/test_characterization_baseline.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/tests/unit/test_characterization_baseline.py) |
| **W-03** | 下载阶段瞬态故障重试 | yt-dlp 网络抖动或源视频瞬态不可达 | 命中上传前瞬态错误，`requeue_transient_pre_submission_failure` 将状态恢复为 `PENDING`，`retry_count + 1`；超限后落入 `FAILED` | `SAFETY-REGRESSION` | `INV-001` | **EXECUTED (TEST-PROVEN)** | [`tests/unit/test_v7_features.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/tests/unit/test_v7_features.py) |
| **W-04** | 转录/压制不可恢复失败 | Whisper 致命错误或字幕压制脚本异常 | 任务直接置为 `FAILED`，记录 `error_msg`，不进入发布状态 | `SAFETY-REGRESSION` | `INV-001` | **EXECUTED (TEST-PROVEN)** | [`tests/unit/test_v7_features.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/tests/unit/test_v7_features.py) |
| **W-05** | 断点续传与检查点跳过 | 目标成片、双语字幕、封面已完整存在 | 调度器检测到物理检查点完整，跳过耗时渲染与生成，直接复用既有产物推进至发布准备态 | `CHARACTERIZATION ONLY` | `INV-002` | **SPECIFIED / NOT YET EXECUTED**<br>*(受限 TESTABILITY-GAP-001)* | 待 M6.2 离线重放套件补充 |
| **W-06** | 低分视频与发现池隔离 | 视频评分 < 75 或 `source='DISCOVERY'` | 仅入库展示于高赞/发现池，不进入自动发布队列 | `SAFETY-REGRESSION` | `INV-008` | **EXECUTED (TEST-PROVEN)** | [`tests/unit/test_waitlist_discovery_firewall.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/tests/unit/test_waitlist_discovery_firewall.py) |

---

### 2.2 WeChat Publication (微信视频号发布通道)

| 场景编号 | 场景名称 | 触发条件 / 输入 | 预期状态流转 / 行为 | 分类 | 关联不变式 / 风险 | 执行状态 (Execution Status) | 测试用例位置 |
| --- | --- | --- | --- | --- | --- | :---: | --- |
| **WC-01** | 受理写入三表原子事务 | 上传器完成页面投递，获得受理凭据 | 单一事务原子写入 `wechat_publications`、`wechat_submission_attempts` 并将 `processed_videos.status` 置为 `SUBMITTED_UNBOUND` / `SUBMITTED_BOUND` | `CONTRACT` | `INV-007` | **EXECUTED (TEST-PROVEN)** | `test_inv007_wechat_acceptance_transaction_rollback_on_failure`<br>`test_wechat_publications.py:119` |
| **WC-02** | 受理写入中途异常事务回滚 | 更新 `processed_videos` 时发生 SQL/约束异常 | 事务完整回滚，三张表均不产生持久化残留，主状态回退原始态 | `CONTRACT` | `INV-007` | **EXECUTED (TEST-PROVEN)** | `test_inv007_wechat_acceptance_transaction_rollback_on_failure` |
| **WC-03** | 既有受理凭据阻止重复发布 | 视频已有 `SUBMITTED_UNBOUND` 或物理截图 | `wechat_uploader` 启动前前置探针拦截，直接退出码 10，不启动无头浏览器重复投递 | `SAFETY-REGRESSION` | `INV-002`, `INV-003` | **EXECUTED (TEST-PROVEN)** | [`tests/unit/test_wechat_duplicate_guard.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/tests/unit/test_wechat_duplicate_guard.py) |
| **WC-04** | 审核中对账零发布端副作用 | 对账执行器触发精确回查 (`--verify-only`) | 仅按已绑定的 `platform_post_id` 回查；若外部未决/超时，状态保持 `SUBMITTED_BOUND`，不触发重新上传或重试 | `CONTRACT` | `INV-006` | **EXECUTED (TEST-PROVEN)** | `test_inv006_wechat_reconciliation_zero_side_effect_on_sqlite` |

---

### 2.3 Douyin Publication (抖音发布通道)

| 场景编号 | 场景名称 | 触发条件 / 输入 | 预期状态流转 / 行为 | 分类 | 关联不变式 / 风险 | 执行状态 (Execution Status) | 测试用例位置 |
| --- | --- | --- | --- | --- | --- | :---: | --- |
| **DY-01** | 单次使用浏览器凭据签发 | `claim_douyin_publication` 领取任务 | 生成单次使用凭据 `ticket_id` 与加密 `token`，绑定 `video_path` 与 `asset_sha256` | `CONTRACT` | `INV-005` | **EXECUTED (TEST-PROVEN)** | [`tests/unit/test_douyin_publications.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/tests/unit/test_douyin_publications.py) |
| **DY-02** | 凭据绑定与合法消费启动 | 投递产物完整，摘要匹配 | `bind_douyin_browser_launch_ticket_payload` 绑定有效摘要；`begin_douyin_browser_launch` 消费凭据并置 `launch_started_at` | `CONTRACT` | `INV-005` | **EXECUTED (TEST-PROVEN)** | `test_inv005_douyin_browser_launch_negative_validation_paths` |
| **DY-03** | 虚假/篡改凭据消费拒绝 | 虚假 ticket_id、篡改 token 或修改 payload | `begin_douyin_browser_launch` 返回 `False`，拒绝消费，拒绝启动浏览器 | `CONTRACT` | `INV-005` | **EXECUTED (TEST-PROVEN)** | `test_inv005_douyin_browser_launch_negative_validation_paths` |
| **DY-04** | 单次凭据二次消费防重 | 同一 ticket 再次调用 `begin_douyin_browser_launch` | 返回 `False`，不允许同一凭据重放消费 | `CONTRACT` | `INV-005` | **EXECUTED (TEST-PROVEN)** | `test_inv005_douyin_browser_launch_negative_validation_paths` |
| **DY-05** | 已发布成片指纹排重 | 媒体计算所得 `asset_sha256` 已存在且状态为 `PUBLISHED` | `create_douyin_publication` 拒绝生成新记录，返回已有发布记录 | `CONTRACT` | `INV-004` | **EXECUTED (TEST-PROVEN)** | `test_inv004_asset_sha256_deduplication_contract` |

---

### 2.4 Kuaishou Publication (快手发布通道)

| 场景编号 | 场景名称 | 触发条件 / 输入 | 预期状态流转 / 行为 | 分类 | 关联不变式 / 风险 | 执行状态 (Execution Status) | 测试用例位置 |
| --- | --- | --- | --- | --- | --- | :---: | --- |
| **KS-01** | 排队中与已发布指纹双重拦截 | `asset_sha256` 已在快手账本处于 QUEUED 或 PUBLISHED | `create_kuaishou_publication` 自动折叠至已有记录，阻止在途或重复投递 | `CONTRACT` | `INV-004` | **EXECUTED (TEST-PROVEN)** | [`tests/unit/test_kuaishou_publications.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/tests/unit/test_kuaishou_publications.py) |
| **KS-02** | 快手作品管理审核中状态拦截 (Ledger 状态与指纹排重) | 外部回查或作品管理报告审核中消息 ('快手作品管理已可见，当前审核中') | 状态更新为 `UNDER_REVIEW`，相同 `asset_sha256` 阻止二次入队提交 | `SAFETY-REGRESSION` | `INV-002`, `INV-004` | **EXECUTED (TEST-PROVEN)** | [`tests/unit/test_kuaishou_publications.py:61`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/tests/unit/test_kuaishou_publications.py) |
| **KS-03** | 对账精确回查零发布端副作用 | 对账执行器触发快手精确回查 | 仅根据 `work_id` 查询，不触发重新投递；非公开状态不修改主状态 | `CONTRACT` | `INV-006` | **EXECUTED (MOCKED DB)** | [`tests/unit/test_kuaishou_pipeline.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/tests/unit/test_kuaishou_pipeline.py) |

---

### 2.5 Control Plane Operations (控制面操作防护)

| 场景编号 | 场景名称 | 触发条件 / 输入 | 预期状态流转 / 行为 | 分类 | 关联不变式 / 风险 | 执行状态 (Execution Status) | 测试用例位置 |
| --- | --- | --- | --- | --- | --- | :---: | --- |
| **CP-01** | 发布中与账本激活时重试拦截 | 视频处于 `PUBLISHING` 或有 `SUBMITTED_UNBOUND` 账本 | `/api/videos/{yid}/retry` 返回 `success: false`，状态保持原样 | `SAFETY-REGRESSION` | `INV-008` | **EXECUTED (TEST-PROVEN)** | [`tests/unit/test_v7_features.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/tests/unit/test_v7_features.py) |
| **CP-02** | 账本激活时硬重置拦截 | 视频存在未删除的物理凭据或提交账本 | `/api/videos/{yid}/reset-hard` 返回 `success: false`，Fail-Closed 拒绝重置 | `SAFETY-REGRESSION` | `INV-008` | **EXECUTED (TEST-PROVEN)** | `test_inv008_control_plane_hard_reset_fails_closed_against_wechat_ledger` |
| **CP-03** | 无凭据不可二次发布 | 视频在本地记录为 `PUBLISHED`，但无平台物理删除证明 | `/api/videos/{yid}/republish` 返回 `success: false` | `SAFETY-REGRESSION` | `INV-008`, `INV-002` | **EXECUTED (TEST-PROVEN)** | [`tests/unit/test_v7_features.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/tests/unit/test_v7_features.py) |
| **CP-04** | Bot 外部源无约束写入基线 | Telegram Bot 直接调用底层 `update_video_status` | 绕过发布账本检查将状态覆盖为 `PENDING`，造成状态分叉 (已知生产违规) | `KNOWN-UNSAFE-BASELINE` | `RISK-STATE-001` | **EXECUTED (KNOWN-UNSAFE-BASELINE)** | `test_risk_state_001_unconstrained_status_mutation_known_unsafe_baseline` |

---

## 3. Golden Scenario Manifest Specification (黄金场景规范清单)

> [!IMPORTANT]
> **本清单当前为 M6.1 阶段的黄金场景规范声明 (Scenario Specification Complete)**。  
> 包含离线视频二进制切片、字幕 ASS 文件、数据库快照与脱敏测试夹具的**可执行离线重放数据集 (Executable Golden Replay Dataset)** 留待 **Phase M6.2** 正式建设。

```json
{
  "schema_version": "1.0.0",
  "manifest_name": "video_processing_characterization_golden_manifest",
  "manifest_status": "SPECIFICATION_ONLY",
  "environment": "offline_isolated_sandbox",
  "scenarios": [
    {
      "scenario_id": "GOLDEN-WF-01",
      "description": "标准单视频生命周期基线规范",
      "synthetic_data": {
        "youtube_id": "synth-golden-std-001",
        "slice_index": 0,
        "title": "Synthetic Golden Test Video - Standard",
        "channel_id": "SyntheticChannel_001",
        "score": 88,
        "duration_sec": 180,
        "asset_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
      },
      "expected_invariants": ["INV-001", "INV-003"]
    },
    {
      "scenario_id": "GOLDEN-WF-02",
      "description": "长视频切片父子关系流转基线规范",
      "synthetic_data": {
        "parent_youtube_id": "synth-golden-parent-002",
        "parent_title": "Synthetic Golden Parent Long Video",
        "channel_id": "SyntheticChannel_001",
        "score": 92,
        "slice_count": 2,
        "slices": [
          { "slice_index": 1, "title": "Part 1" },
          { "slice_index": 2, "title": "Part 2" }
        ]
      },
      "expected_invariants": ["INV-001"]
    },
    {
      "scenario_id": "GOLDEN-PUB-WC",
      "description": "微信三表原子受理与凭据防重基线规范",
      "synthetic_data": {
        "youtube_id": "synth-golden-wechat-003",
        "slice_index": 0,
        "evidence_path": "/tmp/synthetic_evidence_wechat.png",
        "platform_post_id": "post_synthetic_wx_12345",
        "final_title": "合成微信发布标题"
      },
      "expected_invariants": ["INV-002", "INV-007", "INV-008"]
    },
    {
      "scenario_id": "GOLDEN-PUB-DY",
      "description": "抖音单次凭据绑定与摘要排重基线规范",
      "synthetic_data": {
        "youtube_id": "synth-golden-douyin-004",
        "slice_index": 0,
        "mock_video_bytes": "synthetic_douyin_media_payload",
        "action_scope": "publish"
      },
      "expected_invariants": ["INV-004", "INV-005"]
    },
    {
      "scenario_id": "GOLDEN-PUB-KS",
      "description": "快手双键排重与审查证据保全基线规范",
      "synthetic_data": {
        "youtube_id": "synth-golden-kuaishou-005",
        "slice_index": 0,
        "mock_video_bytes": "synthetic_kuaishou_media_payload",
        "work_id": "ks_work_synthetic_98765"
      },
      "expected_invariants": ["INV-002", "INV-004"]
    },
    {
      "scenario_id": "GOLDEN-RISK-BOT",
      "description": "Telegram Bot 状态无约束改写不安全基线规范 (已知风险记录)",
      "synthetic_data": {
        "youtube_id": "synth-golden-risk-006",
        "initial_status": "SUBMITTED_UNBOUND",
        "target_status": "PENDING"
      },
      "expected_invariants": ["INV-001"],
      "classification": "KNOWN-UNSAFE-BASELINE",
      "associated_risk": "RISK-STATE-001"
    }
  ]
}
```

---

## 4. Testability Gap Register (可测性断层登记)

在建立特征化测试基线过程中，确认以下 3 项现有架构带来的可测性断层：

### TESTABILITY-GAP-001: PipelineManager 外部子进程硬编码耦合
- **事实描述**：`PipelineManager._process_single_video` 内部直接调用 `subprocess.Popen` 与 `os.setsid` 执行 `yt-dlp`、`cli.main auto-caption`、`scripts/copywriter.py`、`scripts/cover_generator.py`、`scripts/wechat_uploader.py`。
- **测试影响**：无法在不 mock 复杂进程树或不准备庞大音视频二进制环境的情况下，直接进行端到端全链路集成测试（如 `W-01`, `W-05`）。
- **M6.1 应对策略**：在单测中 mock `_run_tracked`，隔离子进程边界，聚焦状态流转与 DAL 写入；将完整流水线推进标记为 `SPECIFIED / NOT YET EXECUTED`。
- **解耦工单计划**：`WO-PIPE-001` (阶段接缝解耦) 与 `WO-SCRIPTS-001` (Runner 抽象注入)。

### TESTABILITY-GAP-002: 上传器直接依赖 Playwright 浏览器自动化
- **事实描述**：`scripts/wechat_uploader.py`、`scripts/douyin_uploader.py`、`scripts/kuaishou_uploader.py` 直接在脚本主流程中初始化 Playwright 浏览器上下文并操作 DOM 选择器。
- **测试影响**：在无图形环境或受限沙盒中无法直接执行完整的真实网页投递测试。
- **M6.1 应对策略**：基于已有的 CLI 参数守卫测试（`--verify-only`、`--evidence-dir` 探针）、凭据拦截单测及 `TestClient` 模拟控制面。
- **解耦工单计划**：`WO-PUB-001` (Platform Publication Gateway)。

### TESTABILITY-GAP-003: Telegram Bot 直连 PipelineDB 并缺乏状态机约束
- **事实描述**：`src/bot/pipeline_agent.py` 直接实例化 `PipelineDB()` 并调用 `db.update_video_status(...)`，完全未经过 PipelineManager 状态校验，也未检查底层发布账本。
- **测试影响**：无法通过标准工作流拦截非法状态重写；在特征化测试中必须以 `KNOWN-UNSAFE-BASELINE` 记录这一缺陷行为。
- **解耦工单计划**：`WO-STATE-001` (Workflow Status Machine Extraction)。
