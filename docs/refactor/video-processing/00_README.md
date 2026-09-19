---
created_by: Gemini_3.8_Flash_planning
created_at: 2026-09-12
last_updated_at: 2026-09-12
version: 1.5.0
---

# Video-precessing 架构治理与重构接手总指南

## Version History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.5.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.2 阶段启动：M6.1 特征化测试基线签署完结 (SIGNED OFF / COMPLETE)，正式启动 M6.2 可执行黄金回放数据集 (Executable Golden Replay Dataset) 建设 |
| 1.4.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.1D 独立防线与去重审计：分离 Fact 与 Defense，消除微信与快手防线重复计算，多维建模防线与控制族 |
| 1.3.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.1C 防线合格性审计：确立 Publication Safety Defense 准入标准，剔除 Attempt Identity 虚增防线，降级 INV-003 为 PARTIAL |
| 1.2.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.1B 语义审计：校准 INV-003 六层防线真实适用性，确立 M6.5A 独立修复路线 |
| 1.1.1 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.1A 证据校准：确立双轨覆盖矩阵，纠正 INV-008 违规基线，校准 M6.5 治理路线 |
| 1.1.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M6.1 阶段启动：M5 正式签署完结，启动 M6.1 Characterization Baseline 特征化测试基线 |
| 1.0.0-rc3 | 2026-09-12 | Gemini_3.8_Flash_planning | M5.1 阶段升级：同步 Phase M5.1 Documentation Integrity Pass 状态，更新快照观测标注 |
| 1.0.0-rc2 | 2026-09-12 | Claude_Opus_4.6_planning | 自审修复：纠正悬空风险引用、虚构 API 名、计数偏差与 frontmatter 时间戳 |
| 1.0.0-rc1 | 2026-09-12 | Gemini_3.8_Flash_planning | M5 阶段升级：确立 Gate 驱动恢复协议与正式交接合同规范 |
| 0.1.0 | 2026-09-12 | Gemini_3.8_Flash_planning | M4.5 架构事实冻结、接手指南与工单沉淀 |

---

## ⏱️ 5 分钟快速交接问答 (5-Minute Onboarding)

### 1. 为什么进行这次架构治理？
随着流水线演进为集 YouTube 监控、Gemini 评分、切片、文案、Whisper 转录、双语字幕压制、敏感词审查及微信视频号/抖音/快手多平台发布于一体的自动化系统，核心代码出现单体集中化膨胀：
- 数据访问层 [`src/video_processing/db/database.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/db/database.py)（`PipelineDB`）达约 9.7k 行、245 个方法（基于 2026-09-12 静态快照观测）。
- 状态机调度层 [`src/video_processing/pipeline_manager.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/pipeline_manager.py)（`PipelineManager`）达约 4.4k 行，且主编排方法 `_process_single_video` 达约 1k 行。
**治理目标不是追求理论架构漂亮或进行目录搬家**，而是：
1. 降低单点修改的爆炸半径（Blast Radius）；
2. 提高复杂音视频流转的可验证性与可观测性；
3. 严格保留线上已有安全发帖语义与多层幂等防线；
4. 建立可逐步安全迁移的影子比对（Shadow Mode）基础设施；
5. 降低未来工程师或 AI Agent 在维护大单体时的误伤概率。

### 2. 当前线上系统是否正常运行？
**是，当前生产系统处于稳定运行状态。**
虽然存在高维护债务，但核心数据流通过严格的 SQLite 事务契约、不可变发布账本（Ledger）以及基于 `asset_sha256` 的排重机制维持着有效的强一致性与防重投保护。

### 3. 当前是否允许开始代码重构或修改？
**否。严禁修改任何生产运行逻辑！**
> [!CAUTION]
> **当前阶段处于：Phase M6.2 — Executable Golden Replay Dataset。**  
> **Phase M6.1 特征化测试基线已正式签署完结 (M6.1 SIGNED OFF / COMPLETE)。**  
> **Production behavior changes remain strictly prohibited.**  
> 本阶段核心任务是将 M6.1 的场景清单转换为离线、确定性、无生产副作用的物理 Golden Replay Dataset。所有修改严格限制在 `tests/`、测试辅助代码及治理文档内。所有业务重构与风险修复工单（`WO-STATE-001` ~ `WO-PUB-001`）依然保持 **BLOCKED**。严禁在生产代码中改动任何方法签名、调用逻辑或数据库结构。

### 4. M1–M5 已完成了什么？
- **M1 Repo Topology**：完成全库 464 个文件、4,317 个符号、12,597 条调用边的拓扑映射与高入度 Hotspots 识别。
- **M2 Boundary Audit**：确认核心 `src/` 内部 100% 遵守 DAL 封装（0 越界）；定位 `scripts/` 中 2 处 `db.get_connection()` 与 3 处 `sqlite3.connect` 的局部违规；归纳了 PipelineDB 内部 10 余个自洽的自然领域。
- **M3 State Authority**：确认 `processed_videos.status` 为工作流调度状态，而各平台 `publication ledger` 才是法律级客观事实；查明状态写入存在 5 类调用源；验证了重复发布的 5 级防护梯次。
- **M4 Natural Seams**：建立副作用分类体系（PURE READ、DECISION、PERSISTENCE、LOCAL SIDE EFFECT、EXTERNAL SIDE EFFECT）；识别出天然可做内部委托的独立领域与 `_process_single_video` 阶段接缝；完成 Tier A / B / C 迁移分级。
- **M5 Refactor Handoff v1.0**：建立 20 章节正式交接合同（v1.0.0-rc3），涵盖 8 项系统不变式（含校准后的 `INV-006` 与 `INV-008`）、7 项标准化架构风险（6 活跃 + 1 退役归档）、5 类兼容性信封（API / Data / Workflow / Publication / Operational）、10 种典型故障场景模型、5 级幂等纵深防线、4 级安全门（Gate M5→M6→M7→M8→M9）、3 种影子比对策略与 Gate 驱动的流转协议。7 个结构化工单全部标记为 `BLOCKED`，严格遵循门禁依赖图谱。

### 5. 当前最关键架构事实是什么？
1. **主表状态 ≠ 最终发布事实**：`processed_videos.status` 是可受控制面重置的执行投影；各平台的 `publication ledger`（微信、抖音、快手）才是发布事实权威。
2. **多层幂等防线保护外部投稿**：自动调度在 SQL 层依据 `NOT EXISTS (wechat_publications)` 过滤；抖音依赖一次性 Ticket 与 SHA256 校验；快手依赖双键在途拦截。
3. **不可拆分的原子事务核心**：[`PipelineDB.record_wechat_submission_acceptance`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/db/database.py#L3261) 涉及 3 张物理表的同事务原子更新，绝不能盲目跨连接肢解。

### 6. 哪些区域目前禁止修改？
- ❌ 所有向微信、抖音、快手发起网络与浏览器提交的最终阶段代码（`scripts/wechat_uploader.py`, `_publish_claimed_douyin_publication`）。
- ❌ `record_wechat_submission_acceptance` 及其事务包。
- ❌ `_process_single_video` 核心流转与异常处理块。
- ❌ `_run_tracked` 进程组（`os.setsid` / `killpg`）信号管理。

### 7. 下一步从哪里继续？
**严禁按优先级随意挑选工单实施！** 接手者必须严格遵循以下 **Gate 驱动恢复协议**：
```text
1. Read 00_README.md (重温全局事实与安全红线)
      ↓
2. Identify Current Phase (当前处于 M6.2 可执行黄金回放数据集建设)
      ↓
3. Complete first unfinished mandatory Gate (推进 Gate M6 Safety Harness & M6.2 Golden Replay Dataset)
      ↓
4. Advance to Phase M6.5A (首个受控安全修复: WO-STATE-001 only) -> Phase M6.5B (条件评估 WO-SCRIPTS-001)
      ↓
5. Advance to Gate M7 (影子比对与回放验证门)
      ↓
6. Only execute Work Orders explicitly UNBLOCKED by that Gate
```

### 8. 其他详细文档在哪里？
- 详细调查过程与所有命题判定记录：[`investigation_log.md`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/refactor/video-processing/investigation_log.md)
- 正式重构交接合同（v1.1 规范）：[`refactor_handoff.md`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/refactor/video-processing/refactor_handoff.md)
- 特征化场景矩阵与黄金场景规范：[`characterization_matrix.md`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/refactor/video-processing/characterization_matrix.md)
- 黄金场景可执行回放数据集规范：[`golden_replay_dataset.md`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/refactor/video-processing/golden_replay_dataset.md)
- 安全防护网与不变式双轨矩阵：[`safety_harness.md`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/refactor/video-processing/safety_harness.md)
- 结构化研发与安全工单依赖图：[`work_orders.md`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/refactor/video-processing/work_orders.md)

---

## 📜 文档更新协议 (Documentation Update Protocol)

> [!IMPORTANT]
> **Chat history is supplemental context, not the system of record.**  
> **Repository documentation is the System of Record.**  
> 任何在对话中达成的结论，未经写入本目录文档并建立版本历史前，一律视为未正式生效。

后续任何开发者或 Agent 在推进重构阶段时，**必须**遵循以下更新要求：

1. **每次推进或调查产出**，必须在 `00_README.md` 的 Version History 登记版本，并在 `investigation_log.md` 追加审计记录。
2. **每次发现或推翻不变式**，必须同步更新 `refactor_handoff.md` 中的 `INV-xxx`、`RISK-xxx` 或 `UNK-xxx`。
3. **工单状态流转**，必须更新 `work_orders.md` 中的状态标签（PROPOSED → BLOCKED → READY → IN_PROGRESS → COMPLETED），并附带解除阻塞的 Gate 凭据。
4. **统一更新日志模板**：
   ```markdown
   ### Update [YYYY-MM-DD] · Phase [M?.?]
   - **Author**: [模型或工程师名]
   - **What changed**: [简要变更说明]
   - **New evidence**: [Graft 调用关系、文件行号或日志证据]
   - **Decision**: [作出的确定性决策]
   - **Next action**: [下一步明确事项]
   ```
