---
title: VP-POLARIS「北辰」架构重构与治理深度问答档案 (Q&A Review Compendium)
project: Video-precessing (YouTube → 微信视频号/多平台流水线)
date: 2026-09-20
author: Gemini_3.8_Flash_planning
companion: shadow_development_blueprint.md, adversarial_red_blue_game_2026-09-20.md, VP-POLARIS-WORK-ORDER.md
status: 架构师审议终审修订归档 (FOR ARCHITECT REVIEW - REVISED V2.1)
version: 2.1.0
---

# VP-POLARIS「北辰」架构重构与治理深度问答档案 (Q&A Review Compendium)

> **文档定位**：本文档汇总之于 2026-09-20 围绕 `VP-POLARIS`「北辰」重构工程展开的全部深度对话、代码审查、沙箱推演、红蓝博弈以及万行单体膨胀根因分析，形成一站式、结构化的问题与解答档案，专门供系统架构师、对齐评审员（Human/AI Reviewers）全面审查与签字决策。

---

## 目录
1. [Q1: 本次重构的核心工单是什么？当前生产系统的物理状态如何？](#q1)
2. [Q2: 深度审查与沙箱推演中，确证了哪些可能导致生产事故的致命隐患？](#q2)
3. [Q3: 为什么借鉴 `/teamwork-preview` 的多角色分工？五大角色如何权责互锁？](#q3)
4. [Q4: 影子开发（Shadow Mode）的核心机制是什么？如何实现零生产侵入与零副作用？](#q4)
5. [Q5: 从 `POLARIS-000` 到 `POLARIS-105` 的分阶段实操工单推进计划是怎样的？](#q5)
6. [Q6: 针对复杂的历史单体（“屎山工程”），我们的方案是否在以正确的软件工程范式解决问题？](#q6)
7. [Q7: 方案是否真正做到了“渐进式演进”与“充分的阶段性客观验证”？](#q7)
8. [Q8: 工单制定于一周前，近期的一系列业务迭代（25 次提交）是否影响了重构计划？做出了哪些修订？](#q8)
9. [Q9: 再次红蓝博弈（5 场极限对抗）推导出了哪些必须落地的硬化加固措施？](#q9)
10. [Q10: 为什么明明做了“有限止损”，`PipelineDB` 依然在过去 48 小时从 9.7k 暴涨至 10.6k？如何从物理机制上彻底终结反复？](#q10)
11. [Q11: 架构复审第三轮意见指出的 4 项具体技术缺陷（UNCERTAIN 穿透、历史数据索引冲突、零消费核验盲区、备份覆写）是如何彻底闭环的？基线漂移事实如何澄清？](#q11)
12. [Q12: 第四轮架构终审 3 项 P1 缺口（真实锁路径与反例、方案 A 一致性契约与方案 B 废弃、宿主级 crontab 静音）是如何彻底闭环的？](#q12)

---

<a id="q1"></a>
### Q1: 本次重构的核心工单是什么？当前生产系统的物理状态如何？

**答：**
- **重构总工单**：代号为 **`VP-POLARIS`「北辰」**，主文件为 [`docs/refactor/video-processing/VP-POLARIS-WORK-ORDER.md`](./VP-POLARIS-WORK-ORDER.md)，关联根目录交接备忘录 [`HANDOFF.md`](../../HANDOFF.md) 以及待办工单池 [`work_orders.md`](./work_orders.md)（`WO-STATE-001` ~ `WO-PUB-001`）。
- **工程战略**：确立为 **Hybrid Plan B（Containment 旁路收口 → Contract/Harness 契约修正与失败测试 → Incremental Extraction 渐进解耦）**。
- **当前物理状态（2026-09-20 快照）**：
  1. **Git 分支**：处于 `main` 主干，与 `origin/main` 保持最新（物理锚定 commit `e897eb2`），工作区绝对干净（`working tree clean`）。
  2. **生产代码权限**：严格处于只读冻结状态，**零业务代码修改**。
  3. **测试沙箱验证**：使用隔离运行器 `.venv/bin/python scripts/run_isolated_tests.py` 执行，特征化测试套件（`test_characterization_baseline.py`）与黄金回放套件（`test_golden_replay_dataset.py`）共 15 项测试在 2.96 秒内全绿通过，无任何生产写操作。

---

<a id="q2"></a>
### Q2: 深度审查与沙箱推演中，确证了哪些可能导致生产事故的致命隐患？

**答：** 
在完全保持生产代码只读的前提下，通过白盒 AST 扫描与调用链演练，定位了两大导致严重生产事故的已知漏洞：

1. **Telegram Bot 旁路与退出码 6 误判引发的“重复发布与封号”漏洞（`RISK-STATE-001`）**：
   - **断点位置**：[`src/bot/pipeline_agent.py:L637-L752`](../../src/bot/pipeline_agent.py#L637) 与 [`scripts/wechat_uploader.py:L118-L120,L2620`](../../scripts/wechat_uploader.py#L118)。
   - **推演机制**：微信上传脚本在作品发布跳转作品列表后，返回 `EXIT_SUBMITTED_FOR_REVIEW = 6`（代表平台已受理待审，禁止重传）。`PipelineAgent.upload_to_wechat` 未识别退出码 6，直接判定为失败并抛出错误；大模型提示词引导 Agent 将状态置为 `FAILED`。若管理员后续在 Telegram 发送 `/retry`，`retry_video_in_db` 无条件将状态重置为 `PENDING`，绕过了 Web 控制台严格的 `_wechat_submission_guard_reason`（检查 `wechat_publications` 账本），**导致已受理视频被流水线二次重新上传，引发平台重复发帖与账号风控。**
2. **中心 DAL 候选过滤遗漏 DISCOVERY 引发的“自动盗发”缺陷（`RISK-STATE-003`）**：
   - **断点位置**：[`src/video_processing/db/database.py:L4253-L4305`](../../src/video_processing/db/database.py#L4253) 与权威风险登记表 `RISK-STATE-003`（注：原 `RISK-STATE-002` 属于已在 M5.1 归档的历史退役编号，本缺陷赋予正式新编号以保持生命周期历史真实）。
   - **推演机制**：系统宪法明确规定 `source='DISCOVERY'`（高赞发现）条目仅在仪表盘供人工浏览，严禁自动发布。但中心调度消费高分视频的唯一咽喉 `get_high_score_pending_videos()` 的 SQL 过滤中，**遗漏了 `AND IFNULL(pv.source, '') != 'DISCOVERY'`**。且现存测试夹具 `GOLDEN-WF-01` 居然断言了 DISCOVERY 高分会被调度，**把严重的安全缺陷当成了正常契约固化了下来**。

---

<a id="q3"></a>
### Q3: 为什么借鉴 `/teamwork-preview` 的多角色分工？五大角色如何权责互锁？

**答：**
单体架构重构的最大风险是“改动无边界、开发自证自改、缺乏独立审计”。借鉴 `/teamwork-preview` 模式建立 **5 大互锁角色**，遵循三大原则（**Specify What, Not How**、**Objective Verification**、**Acceptance Criteria = Guardrails**）：

1. **系统首席架构师兼安全门禁官 (Lead Architect & Gatekeeper)**：维护 8 大不变式（`INV-001`~`INV-008`）与 5 类兼容性信封；掌控 Gate 准入准出签署；拥有一票否决权与工单解锁权。
2. **影子研发工程师 (Shadow Dev Engineer)**：仅负责编写无外部副作用的实现代码、影子比对器与内部委托类；为每项修改配置硬编码动态降级开关（Feature Flag）；严禁私自修改现有 Public API 签名。
3. **对抗式红队审计员 (Adversarial Auditor)**：专门负责寻找盲区，构造极限破坏与攻击用例（并发死锁、会话冲突、退出码 6 注入、状态分叉）；严禁认可任何开发者的主观口头背书。
4. **测试与防护网工程师 (Harness QA Engineer)**：维护隔离沙箱与黄金回放数据集；执行**“红灯先行（Test-First）”**——必须先编写能命中漏洞的失败测试产生红灯证据，修复后再跑出绿灯。
5. **SRE 运维与回滚守护官 (SRE & Rollback Guardian)**：监控任务空闲窗口，避开 09:00/21:00 cron 与美股盘中敏感期；执行单主干 Git 原子提交；准备一键回滚三板斧，确保异常时 30 秒内止血。

---

<a id="q4"></a>
### Q4: 影子开发（Shadow Mode）的核心机制是什么？如何实现零生产侵入与零副作用？

**答：**
影子开发是在不影响生产运行的前提下，在后台并行执行新逻辑并进行差分比对的工程手段：

1. **副作用 5 分级验证矩阵**：
   - `PURE_READ`（查询/报表）：线上异步实时双跑比对（Shadow Comparator），主响应始终取旧版本，仅记录 diff 日志；
   - `DECISION`（敏感词/发布窗口）：离线黄金数据集回放 + 线上静默双跑，比对判定结果；
   - `PERSISTENCE`（数据库写入）：临时 SQLite 内存沙箱事务回滚回放，严禁直连生产库；
   - `LOCAL_SIDE_EFFECT`（本地文件生成）：隔离到 `/tmp/shadow_*` 临时目录，校验媒体 Hash；
   - `EXTERNAL_SIDE_EFFECT`（外部平台投稿）：**绝对禁止线上双跑**，必须走离线 Mock 或 Dry-Run 模式。
2. **影子双跑比对器规范**：
   - **主逻辑绝对优先**：始终低延迟执行现有稳定逻辑并返回结果；
   - **异常零泄漏**：影子分支内的任何异常被内部 `try...except` 吞掉并记 Telemetry，绝不影响主流程；
   - **动态熔断可控**：通过 `settings.py` 提供毫秒级开关（`enable_shadow_comparison: bool = False`）；
   - **盘中强制避让**：美股交易时段（Market Guard）自动短路静默，不消耗生产 CPU；
   - **采样限频**：默认 10% 采样率，相同差分日志滑动窗口限频（单小时上限 3 次）。

---

<a id="q5"></a>
### Q5: 从 `POLARIS-000` 到 `POLARIS-105` 的分阶段实操工单推进计划是怎样的？

**答：**
严格遵循 Gate 驱动与“红灯先行”流水线：

```
[POLARIS-000] 生产现场、Git 与空闲窗口复核 ───────► [READY] (待启动口令触发)
      ↓
[POLARIS-101] 真实入口级隔离回归测试 (正反双轨红灯) ──► [BLOCKED] (等 POLARIS-000 签署)
      ↓
[POLARIS-102] 封闭 Bot 旁路、退出码6原子写账本 ─────► [BLOCKED] (等 POLARIS-101 红灯证据)
      ↓
[POLARIS-103] DAL 候选硬排除 DISCOVERY 与夹具修正 ──► [BLOCKED] (等 POLARIS-101 红灯证据)
      ↓
[POLARIS-104] 治理文档与风险矩阵对齐 ──────────────► [BLOCKED] (等 POLARIS-102/103 变绿)
      ↓
[POLARIS-105] 全量单测套件验证与单主干原子合流 ────► [BLOCKED] (等 POLARIS-104 完成)
```

- **`POLARIS-000`**：SRE 验证工作树 CLEAN、无运行中发布进程、不在发帖高峰；
- **`POLARIS-101`**：测试工程师编写真实入口级隔离回归测试，遵循**双轨红绿逻辑**（漏洞复现用例先红后绿，正常基线用例全程保绿），扩展覆盖视频删除（`delete_video_from_db`）、并发重置、退出码 3（结果未确认）、超时及平台受理后本地写账本崩溃窗口（未决 Attempt 租约恢复与禁止重领）；
- **`POLARIS-102`**：影子工程师将 Bot 收口为单一具名任务分发客户端：
  1. **QUEUED 响应前持久化**：先在 SQLite 中原子持久化写入分发记录，**随后**才返回 `QUEUED` 异步受理语义，对活跃中任务幂等复用；
  2. **不可重试 Attempt 租约与原子领取**：执行 `wechat_submission_attempts` 增量表结构迁移；建立部分唯一活跃索引（`idx_wechat_active_attempt`）；外部拉起前通过条件 CAS 原子领取不可重试 Attempt 租约（`IN_PROGRESS`），BUSY 退出标记 `RELEASED_BUSY` 释放重领，若平台受理后本地崩溃，重启强制 Fail-Closed 进入 `UNCERTAIN` 绝不自动重领，闭环 At-Most-Once；
  3. **退出码 6 原子三表落账**：核心服务统一调用强原子事务写入 Publication 账本与 Attempt 记录，杜绝无账本鬼魂状态；
  4. **锁争用与独立 BUSY 凭证**：子进程自洽持锁（防止锁超时为 0 导致立即 busy），仅对明确 BUSY 凭证有限退避，通用退出码 1 判定为永久失败，退出码 3 强制置为 `UNCERTAIN` 绝不自动重试；
- **`POLARIS-103`**：在 DAL SQL `get_high_score_pending_videos` 增加 `UPPER(TRIM(COALESCE(pv.source, ''))) != 'DISCOVERY'`，修正 `GOLDEN-WF-01` 夹具为 AUTO，测试转绿；
- **`POLARIS-104`**：架构门禁官修订治理文档，风险登记册将 `RISK-STATE-001/003` 标为 `REMEDIATED`；
- **`POLARIS-105`**：1600+ 单元测试 100% 跑通，单主干原子提交并 push 到 `origin/main`。

---

<a id="q6"></a>
### Q6: 针对复杂的历史单体（“屎山工程”），我们的方案是否在以正确的软件工程范式解决问题？

**答：是的，方案完全避开了所有典型的重构反面教材，严格践行了工业级重构科学。**

1. **反面教材 vs 正确解法**：
   - ❌ **Big-Bang 全面重写**：试图把 10.6k 行 `database.py` 一口气拆成 20 个类。**后果**：SQLite 事务连接断裂、引发大量死锁，线上直接报废。
     👉 **我们的解法（Branch by Abstraction）**：保持外部门面签名 100% 不变，464 个外部调用方零感，仅在单体内部做自然领域私有委托。
   - ❌ **目录大搬家（表面重构）**：不改耦合，只忙着挪文件夹改 import。**后果**：破坏 git blame，引发灾难性 Git Merge 冲突。
     👉 **我们的解法（筑堤防洪优先 Containment First）**：不动目录，先封死 Bot 抹除状态和 SQL 误拉候选这两个致命武器，优先保障生产不漏发、不重发。
   - ❌ **教条主义，阻断业务发展**：要求全公司“代码冻结两周搞重构”。
     👉 **我们的解法（业务无感并行）**：事实证明，过去一周业务团队完成了 25 次提交（上线了评论互动系统和跑道流光），我们的重构规划丝毫不阻碍主营业务前进。

---

<a id="q7"></a>
### Q7: 方案是否真正做到了“渐进式演进”与“充分的阶段性客观验证”？

**答：完全落实，且对机器证据与语义等价性有清晰的科学界定。**
- **渐进性（Incremental）**：将重构划分为 Tier A（只读/决策影子）、Tier B（独立账本内部委托）、Tier C（外部发布最后阶段），工单粒度控制在“先补红灯测试 -> 最小修复转绿 -> 单独原子提交”。
- **客观验证与机器收据边界（Objective Verification & Receipt Boundary）**：
  - **沙箱隔离收据 (`receipt.json`)**：依托 `.venv/bin/python scripts/run_isolated_tests.py`，机器凭据确切证明了**外部网络与非沙箱磁盘写操作被 OS 层硬性拒绝**，当次运行环境处于完全密封的隔离状态；
  - **确定性测试范围**：`Run A == Run B` 是测试套件内部用例（`test_golden_replay_dataset.py`）针对特定输入在沙箱中验证相同逻辑的两次确定性回放，而非测试运行脚本自身执行两次对比；
  - **语义等价性的审慎界定**：必须明确区分“隔离收据/单测通过”与“全量语义等价”。特征化测试与黄金回放通过，客观证明了**所捕获的生产关键路径与漏洞用例无回归**；对于未捕获的历史隐式边缘行为，不能夸大自封为全量等价，必须严格依靠后续 Tier A/B 的 Shadow Mode（线上只读比对）在显式执行 `conn.execute("BEGIN DEFERRED")` 的专用只读事务快照下进行长周期、多样本的动态等价性校验。

---

<a id="q8"></a>
### Q8: 工单制定于一周前，近期的一系列业务迭代（25 次提交）是否影响了重构计划？做出了哪些修订？

**答：核心战略 Hybrid Plan B 依然完全成立，但我们根据过去一周的 25 次真实提交，做出了 4 项针对性工程校准：**

1. **行号基线校准**：`database.py` 从 9.7k 增长至 10,649 行，文档中的所有行号证据（如 `record_wechat_submission_acceptance` 移至 `L3406`）已全量校准至 2026-09-20 快照。
2. **会话共享锁层次厘清与锁争用防范**：9月19日上线的 `WeChat-Interaction-Engine` 在 `scripts/wechat_uploader.py:L1221` 引入了 `@guarded_wechat_browser_session`（默认超时 0 秒）。工单 `POLARIS-102` 明确会话锁由子进程内部自洽持有，**严禁 Bot 父进程外置重复申请以杜绝父子进程因超时 0 秒产生锁争用并导致子进程立即锁忙失败**。
3. **退出码 1 混淆治理与明确 BUSY 凭证**：Uploader 中锁争用返回 `busy_result=1`，但素材缺失同样 `return 1`。调度层严禁盲目依据退出码 1 判定为锁忙；必须依赖结构化 BUSY 凭据才执行有限重试（最多 3 次），通用退出码 1 视为永久失败；退出码 3 明确为 `EXIT_RESULT_UNCERTAIN`（结果未确认），必须人工线下核验，绝不可自动重传。
4. **子进程环境对齐**：复用提交 `e7c9866` 统一提取的 `_build_subprocess_env`，确保 Bot 子进程调用在贫环境下 PATH 与代理变量一致。

---

<a id="q9"></a>
### Q9: 再次红蓝博弈（5 场极限对抗）推导出了哪些必须落地的硬化加固措施？

**答：** 专项博弈报告 [`adversarial_red_blue_game_2026-09-20.md`](./adversarial_red_blue_game_2026-09-20.md) 输出的核心决议：

1. **Bot 响应前持久化与不可重试 Attempt 租约闭环**：
   - 收到调度后先在 SQLite 原子写入任务记录再返回 `QUEUED`，杜绝内存丢单；活跃任务幂等复用；
   - 执行 `wechat_submission_attempts` 增量表迁移（扩展状态约束），建立部分唯一活跃索引（`idx_wechat_active_attempt`），外部调用前条件 CAS 原子领取 `IN_PROGRESS` Attempt 租约；BUSY 退出标记 `RELEASED_BUSY` 释放重领；捕获退出码 6 时复合原子落账；发生平台受理但本地写账本崩溃时，重启识别未决 Attempt 并 Fail-Closed 进 `UNCERTAIN` 绝不自动重领，物理阻断重复提交。
2. **DAL 候选过滤强化防漂移并建立正反双轨测试**：采用 `UPPER(TRIM(COALESCE(pv.source, ''))) != 'DISCOVERY'` 防止脏数据漂移；在 `POLARIS-101` 建立独立套件同时断言 AUTO 纳入、DISCOVERY 排除与 promotion 纳入，拒绝掩耳盗铃。
3. **PipelineDB 内部委托严禁子模块自建连接**：子模块方法首个参数必须为 `conn: sqlite3.Connection`，严禁在子模块内调用 `get_connection()`，防止 SQLite WAL 下同进程并发写入死锁。
4. **影子比对显式开启读事务快照与超时底层中断**：严禁误用 Python `with conn:` 假读事务，必须在专用连接显式执行 `conn.execute("BEGIN DEFERRED")` 获取 WAL 读快照并在同一事务内先后执行新旧查询，测试验收必须验证并发写不可见；200ms 硬超时必须验收底层中断释放（`sqlite3_interrupt`）并显式结束事务、关闭连接。
5. **受控安全回滚五步机制**：严禁裸 Revert 撤销安全防线；回滚必须严格执行“全局停写、终止在途执行进程并严格核验零活跃消费 -> 绑定具体 Commit 回滚 -> 沙箱运行 POLARIS-101 防线测试（失败保持暂停，禁止恢复调度） -> 推送并重启全套守护进程 -> 解除暂停恢复调度”。
6. **SQLite 账本纠偏严禁全库盲跑与裸写生产 SQL**：采用 SQLite 在线备份 API（`conn.backup()`）并执行 `PRAGMA integrity_check;` 验证；通过受测 DAL 封装方法（`preview_wechat_submission_divergence` 与 `repair_wechat_submission_divergence_for_ids`）执行排除 `PUBLISHED` 的只读差异预览与定点范围纠偏。

---

---

<a id="q10"></a>
### Q10: 为什么明明做了“有限止损”，`PipelineDB` 依然在过去 48 小时从 9.7k 暴涨至 10.6k？如何从物理机制上彻底终结反复？

**答：这是本次审查中最关键的根因发现。**

#### 1. 为什么会暴涨近 1,000 行？
- **事实数据**：过去 48 小时合入的 6 个提交（`59a5cab`, `f5b9544`, `a7ac697`, `bb51479`, `b7a727e`, `57e0bbc`）为刚上线的 `Project WeChat-Interaction-Engine`（评论互动引擎）在 `database.py` 中：**新增 990 行、删除 74 行、净增 916 行代码**！
- **业务耦合真相**：互动数据并非孤立表，其业务逻辑深度联查了 `wechat_publications`（发布事实）与 `processed_videos`（视频状态），涉及跨领域关联。
- **机制死结**：宪法 Rule 4 规定“所有 SQL 必须写在 `PipelineDB` 内，严禁裸调连接”；而 `PipelineDB` 又只有一个物理文件。当新业务急需上线建表存数据时，**为了不违背宪法，工程师/AI 唯一合规的做法就是把这净增的 916 行代码全部塞进 `database.py`！**
- **结论**：**“道德层面的止损约定”在“新业务交付”面前必然崩溃；只要不提供合法的物理代码扩展缝，单体就会作为引力黑洞无限膨胀。**

#### 2. 彻底终结反复的“物理三板斧”：
1. **第一斧：Facade 统一管理事务与连接上下文（Facade & Connection Injection Protocol）**：
   `PipelineDB` 作为统一门面持有连接生命周期与全局事务边界（`with self.get_connection() as conn:`）。拆分出来的领域子模块（如 `interaction_repository.py`）**强制将首个参数设为 `conn: sqlite3.Connection`**，严禁子模块自建连接或独立 commit。这不仅实现了物理文件拆分，更确保了涉及 `wechat_publications` 与 `processed_videos` 的跨表关联操作在同一个事务中原子执行，从根本上防止 SQLite WAL 下的并发死锁。
2. **第二斧：CI 动态递减棘轮门禁（Dynamic Monotonic Ratchet Gate）**：
   彻底废弃静态绝对上限（如 10,700 行留有巨大反弹空间的虚假门禁）。在单测门禁中建立**单调递减棘轮**：以当前代码库真实行数（10,649 行）为初始基线，任何针对 `database.py` 的 PR 其净行数**只许减少或持平（`current_loc <= baseline_loc`）**，若有净增则 CI 立即抛出 `AssertionError` 红灯阻断，逼迫所有新增领域方法物理写入独立子模块。
3. **第三斧：跨域事务回滚实测与双重防护（Cross-Domain Rollback Verification & AST Dual-Gate）**：
   鉴于互动表与发布事实表存在跨域业务关联，仅靠 AST 扫描“禁止调用 `get_connection()`”并不足以证明业务正确性。必须在测试套件中建立**跨域事务级联回滚测试**（模拟跨表操作异常时，断言互动表与发布表均干净回滚、零局部持久化），配合 AST 静态语法扫描，形成动静态双重防护网。在 `WO-DB-001` 实施时，通过将该模块解耦外移，直接削减近千行单体体积。

---

<a id="q11"></a>
### Q11: 架构复审第三轮意见指出的 4 项具体技术缺陷（UNCERTAIN 穿透、历史数据索引冲突、零消费核验盲区、备份覆写）是如何彻底闭环的？基线漂移事实如何澄清？

**答：针对架构师终审指出的 3 项 P1 与 1 项 P2 缺陷，本版已在技术方案上完成物理闭环，并对基线漂移做出了明确归属划分：**

#### 1. [P1] 彻底封堵 `UNCERTAIN` 状态领取穿透漏洞
- **缺陷本质**：原蓝图与工单中的 CAS 原子领取 SQL 和条件唯一索引仅检查 `('IN_PROGRESS', 'SUBMITTED_UNBOUND')`。当系统因崩溃恢复或超时将悬空任务置为 `UNCERTAIN` 状态后，原有的 `NOT EXISTS` 阻断失效，新任务依然能领取并生成新的 Attempt，再次拉起 Uploader 造成灾难性重复发帖！
- **闭环方案**：
  1) **CAS 阻断条件全面扩充为多表联合阻断**：
     领取 CAS SQL 必须同时联合检查 `wechat_submission_attempts`（排除 `IN_PROGRESS`, `SUBMITTED_UNBOUND`, `PLATFORM_ID_BOUND`, `UNCERTAIN`）、`wechat_publications`（排除 `SUBMITTED_UNBOUND`, `SUBMITTED_BOUND`, `UNDER_REVIEW`, `UNCERTAIN`, `PUBLISHED`）及主表状态。
  2) **阻断结果精准抛出**：受影响行数为 0 时，若冲突原因为 `UNCERTAIN`，直接抛出 `SubmissionClaimRejectedUncertain`，物理锁定该视频；必须经人工核验微信后台后线下核销，绝不重领。
  3) **防线单测**：在 `POLARIS-101` 增设用例 `test_claim_attempt_rejected_when_prior_attempt_is_uncertain`，严格验证处于 `UNCERTAIN` 状态时再次领取必须 100% 被拒。

#### 2. [P1] 历史多条活跃记录与条件唯一索引平滑兼容
- **缺陷本质**：当前生产代码 `database.py:3424` 允许同一 `subject_id` 存在多条 `SUBMITTED_UNBOUND` 记录（如不同 `evidence_path` 写入）。若直接执行 `CREATE UNIQUE INDEX`，已有存量生产库在启动迁移时将直接抛出 `sqlite3.IntegrityError: UNIQUE constraint failed` 崩溃！
- **闭环方案**：
  - **架构推荐方案 A（独立原子活跃租约表 `wechat_submission_active_claims`）**：
    将高频并发互斥控制与只读历史审计解耦。以 `subject_id` 为天然 PRIMARY KEY，物理保证每个发布主体全局仅有一条活跃租约，原 `wechat_submission_attempts` 保留为纯追加审计账本，零历史数据冲突风险。
  - **单表备选方案 B（单表冲突预检与历史重复数据安全归档迁移）**：
    在单事务内先执行预检；针对存在多条活跃状态的历史记录，保留按 `created_at DESC` 排序最新的 1 条作为活跃记录，将其余历史旧记录的状态安全更新为 `'SUBMITTED_UNBOUND_ARCHIVED'`，保留全部审计字段，再建立条件唯一索引。迁移过程包裹在单事务内，失败自动回滚。

#### 3. [P1] 全系统受控停写、启动源封闭与进程组零消费物理核验
- **缺陷本质**：`vpanel ui restart/stop` 仅管理 FastAPI 控制台，无法终止独立 `PipelineManager`、cron 定时任务（每 30 分钟 monitor、每天 09:00/21:00 定时发布）、Bot 守护进程、以 `start_new_session=True` (`os.setsid`) 启动的独立进程组互动 Worker 以及残留的 Chromium 孤儿；修改 `.env` 无法被静态常驻进程热重载。
- **闭环方案**：
  - 制定**七步停写与零消费核验规程**：
    ① 创建全局调度冻结锁 `output/pipeline_freeze.lock`，所有调度入口前置拦截直接退出，彻底阻断 cron 复活；
    ② 配置 `WECHAT_PUBLISHING_PAUSED=true`；
    ③ 停止受管服务（`./vpanel ui stop && ./vpanel bot stop`）；
    ④ 按 PGID 整树清理进程组并 kill 残留 Chromium 孤儿；
    ⑤ Python 脚本非阻塞 flock 探测 `output/wechat_session.lock` 确保会话排他锁已物理释放；
    ⑥ 将在途 `IN_PROGRESS` 任务收敛为 `UNCERTAIN` 保留现场；
    ⑦ 物理核验进程列表严格为空。
  - **门禁铁律**：未证实零消费前，严禁执行 `git revert`！冻结锁与暂停状态必须覆盖整个回滚与沙箱测试验证窗口。

#### 4. [P2] 根除 WAL 模式备份静默覆写隐患
- **缺陷本质**：WAL 模式下写事务直接写入 `-wal` 文件，主库文件 `pipeline.db` 的 mtime 不随普通写事务变化。原蓝图使用 `os.path.getmtime()` 命名备份，导致多次备份文件名完全一致，直接静默覆写旧恢复点，造成灾备失效。
- **闭环方案**：
  - 备份命名升级为：`output/backups/pipeline_recovery_{UTC微秒时间戳}_{UUID随机熵}.sqlite3`；
  - 增加 `os.path.exists()` 防护，若目标已存在直接抛出 `FileExistsError`，坚决拒绝覆盖；
  - 采用 SQLite 官方在线备份 API（`src.backup(dst)`）保证获取一致性 WAL 检查点；
  - 独立连接执行 `PRAGMA integrity_check;` 严格断言为 `'ok'`；
  - 计算 SHA256 校验和并将元数据持久化登记到 `output/backups/latest_recovery_point.json`。

#### 5. 审议基线漂移归属说明与三层状态清晰界定
- **基线 Commit 事实**：当前 Git HEAD 物理锚定在 `e897eb2c2bf514b0f4505de8d51e88a137379100`。
- **业务基线漂移说明**：前序提交 `9b0eb71` 解决了视频号评论互动系统（English World 账本发布与原生 ID 索引），涉及 5 个生产文件及 1 个测试文件变动（+397/-78 行），属于正交业务演进。重构总工单 `VP-POLARIS` 确立以来，生产代码（`src/`、`scripts/`）严格保持 100% 只读冻结（零修改）。
- **三层状态报告规程**：
  - **【协议已落盘】**：上述 4 项技术方案与剧本已在治理文档中物理落盘；
  - **【实现待完成】**：生产代码目前保持 0 修改，等待口令放行后在 `POLARIS-101` ~ `105` 中实施；
  - **【测试已验证】**：在当前 `e897eb2` 快照下通过 `scripts/run_isolated_tests.py` 验证基线测试 100% 绿灯。

---

<a id="q12"></a>
### Q12: 第四轮架构终审 3 项 P1 缺口（真实锁路径与反例、方案 A 一致性契约与方案 B 废弃、宿主级 crontab 静音）是如何彻底闭环的？

**答：针对架构师与 Codex 第四轮终审指出的 3 项 P1 方案内部未闭合缺陷，本版已在技术方案、契约规范与测试定义上完成彻底闭环：**

#### 1. [P1] 纠正会话锁核验路径并增加持锁失败反例测试
- **缺陷本质**：[蓝图第 381 行](./shadow_development_blueprint.md) 运维剧本探测的是 `output/wechat_session.lock`，但系统[真实实现](../../src/video_processing/core/wechat_session_lock.py#L30) 是从登录态文件路径派生真实锁文件。生产配置为 `output/wechat_state.json`，派生出的真实锁文件为 `output/.wechat_state.json.browser.lock`。若探测错误路径，当真实锁被后台浏览器进程占用时，剧本依然会输出 `FREE` 假象，导致并发拉起冲突！
- **闭环方案**：
  1) **规范化路径解析**：剧本与运维工具统一调用 `canonical_wechat_session_lock_path("output/wechat_state.json")` 解析真实锁文件 `output/.wechat_state.json.browser.lock`；
  2) **持锁反例测试入驻 POLARIS-101**：在沙箱测试套件中增设用例 `test_wechat_session_lock_probe_detects_real_hold_and_release`。启动后台线程通过 `WeChatSessionLock` 持有真实锁，断言探测逻辑**必须捕获 `BlockingIOError` 并判定为锁忙失败（非零退出码反例）**；持锁线程释放后，断言探测脚本成功返回 0（FREE）。

#### 2. [P1] 确立租约方案 A 完整一致契约，废除方案 B
- **方案 B 废弃技术裁决**：
  方案 B 试图在迁移事务中先将重复记录更新为 `'SUBMITTED_UNBOUND_ARCHIVED'`，但原表已有的 `CHECK(state IN ('SUBMITTED_UNBOUND', 'PLATFORM_ID_BOUND'))` 约束尚未放开，该 `UPDATE` 会直接抛出 `CHECK constraint failed` 异常；且若历史数据存在相同的 `created_at`（如同一秒内重试写入），`a.created_at < b.created_at` 无法消除重复项，后续 `CREATE UNIQUE INDEX` 仍将触发 `IntegrityError` 导致迁移崩溃。方案 B 物理上不可行，**正式废弃，禁止作为备选剧本**。
- **方案 A 完整物理闭环**：
  1) **Attempt 历史表 CHECK 约束平滑扩展**：
     在 `PipelineDB._migrate_database()` 增量迁移事务中检测表定义。若约束未扩展，单事务内重构表将 CHECK 约束扩展为：
     `CHECK(state IN ('IN_PROGRESS', 'SUBMITTED_UNBOUND', 'PLATFORM_ID_BOUND', 'UNCERTAIN', 'RELEASED_BUSY'))`；
     新表**不建任何 `subject_id` 唯一约束**，保持为纯追加审计历史账本，存量所有重复 Attempt 100% 无损保留，零迁移冲突；
  2) **创建独立原子活跃租约表 `wechat_submission_active_claims`**：
     以 `subject_id TEXT PRIMARY KEY` 物理保证全局唯一活跃租约；
  3) **单事务联合 CAS 原子领取**：
     步骤 1 向 `wechat_submission_active_claims` 执行 `INSERT INTO ... SELECT ... WHERE NOT EXISTS (...)` 插入活跃租约；若成功插入 1 行，步骤 2 在同一事务中插入 Attempt 审计记录，随后原子 `COMMIT`；
  4) **按 `active_attempt_id` 条件精确释放与流转**：
     - **BUSY 退出条件释放**：携带明确 BUSY 凭证时，在单事务中执行 `DELETE FROM wechat_submission_active_claims WHERE subject_id = ? AND active_attempt_id = ? AND claim_state = 'IN_PROGRESS';`，并更新 Attempt 为 `RELEASED_BUSY`；退避后申请全新 ID 重领；
     - **正常受理落账**：退出码 6 时，单事务更新租约状态为 `SUBMITTED_UNBOUND`（持续占位防止重领），落账 Publication 与主表；
     - **崩溃恢复与禁止重领**：重启扫描到悬空租约，Fail-Closed 将活跃租约、Attempt 与主表均置为 `UNCERTAIN`，因活跃表主键持续占用，后续所有领取请求 100% 被拒，物理锁定，闭环 At-Most-Once；
  5) **POLARIS-101 单测验收**：增设 `test_active_claims_lease_lifecycle` 严格验证租约创建、并发冲突互斥、按 `active_attempt_id` 条件释放与非法 ID 拒绝篡改。

#### 3. [P1] 升级启动源封闭为宿主级 crontab 物理静音
- **缺陷本质**：原蓝图仅在工作区创建 `output/pipeline_freeze.lock` 标记文件。但宿主机器每分钟都在通过 crontab 执行 `scripts/run_publication_window.py`。一旦运维执行 `git revert`，Git 会将带有该标记文件检查的应用代码撤销为旧代码，此时宿主 cron 会在 60 秒内拉起被回滚的旧版本代码直接发起发帖！
- **闭环方案**：
  1) **彻底脱离对应用层可被 revert 代码的依赖，提升为 OS 宿主级物理静音**：
     - 导出当前 crontab 备份：`crontab -l > "output/crontab_backup_$(date +%Y%m%d_%H%M%S).txt"`；
     - 对包含 `Video-precessing` 的活跃项添加注释前缀：`crontab -l | sed -E '/Video-precessing/s/^([^#])/# QUIESCE_DISABLED \1/' | crontab -`；
     - 物理核验活跃项已清空：`crontab -l | grep -v '^[[:space:]]*#' | grep 'Video-precessing'` 断言无输出；
  2) **静音窗口全覆盖**：宿主级 crontab 静音覆盖整个受控安全回滚、沙箱测试验证的全过程；
  3) **仅在沙箱测试 100% 绿灯且确认稳定后**：方可执行反向 sed 恢复 crontab 调度（`crontab -l | sed -E 's/^# QUIESCE_DISABLED (.*)$/\1/' | crontab -`）。

