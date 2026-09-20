---
created_by: Gemini_3.8_Flash_planning
created_at: 2026-09-20
last_updated_at: 2026-09-20
version: 2.1.0
title: VP-POLARIS「北辰」架构重构与影子开发多角色工程实施指南
---

# VP-POLARIS「北辰」重构工程多角色影子开发实施指南 (Shadow Development Blueprint)

> **文档定位**：本指南借鉴 `/teamwork-preview` 的多角色协作范式，在 `VP-POLARIS-WORK-ORDER.md` 确立的 **Hybrid Plan B（Containment 旁路收口 → Contract/Harness 契约修正与失败测试 → Incremental Extraction 渐进解耦）** 战略指导下，细化为五个具有严格工程制衡关系角色的实操手册。  
> **核心铁律**：在 `POLARIS-101` ~ `POLARIS-105` 推进期间，**严禁修改任何生产运行代码**，所有安全与契约必须通过双轨隔离回归证据（先行失败与基线保绿）进行物理闭环。
> **当前阶段**：`Phase M6.2+`（黄金回放数据集建设与红蓝对抗加固完毕，第五轮架构终审 3 项 P1 缺口彻底闭环，待启动 `Phase M6.5A`）  

---

## 变更历史 (Change Log)

| 版本 | 日期 | 作者 | 说明 |
| :--- | :---: | :---: | :--- |
| 2.2.0 | 2026-09-20 | Antigravity | M6.2+ 第五轮架构终审 3 项 P1 缺口深度闭环：① 回滚剧本彻底消除文档间矛盾，实操命令全量更新为宿主 crontab 物理静音（# QUIESCE_DISABLED）、真实锁探测（canonical_wechat_session_lock_path）与反向恢复步骤；② 纠正领取事务外键顺序为 BEGIN IMMEDIATE -> 4 表联合阻断 -> 先 Attempt 后活跃租约 -> COMMIT，杜绝外键与主键冲突；③ 领取条件补齐历史 Attempt 联合阻断，增设历史 Attempt 独占拒绝与外键回滚无残留单测 |
| 2.1.0 | 2026-09-20 | Antigravity | M6.2+ 第四轮架构终审 3 项 P1 缺口终极闭环：① 纠正会话锁核验路径：调用 canonical_wechat_session_lock_path 解析真实锁文件 output/.wechat_state.json.browser.lock，并在 POLARIS-101 增加持锁反例测试；② 确立租约方案 A 完整契约：废弃方案 B，补齐 Attempt 表 CHECK 扩展迁移与 wechat_submission_active_claims 独立表创建、同事务 CAS 领取与按 active_attempt_id 条件释放；③ 升级启动源宿主级停用：引入 crontab 物理静音（# QUIESCE_DISABLED 注释与核验），彻底摆脱对可能被 revert 业务代码的依赖，静音窗口覆盖全回滚与沙箱测试 |
| 2.0.0 | 2026-09-20 | Antigravity | M6.2+ 架构终审 4 项缺陷闭环与基线漂移归属：① 彻底封堵 UNCERTAIN 领取 SQL 穿透漏洞（Attempt 与 Publication 联合阻断，补齐禁止重领单测）；② 消除历史数据唯一索引冲突风险（提出独立原子租约表 A 方案与同表去重归档 B 方案，避免 IntegrityError 崩溃）；③ 升级全系统受控停写与零消费物理核验（引入 pipeline_freeze.lock 封闭启动源、PGID 整树清理、Chromium 孤儿清理与会话锁释放验证）；④ 根除 WAL 备份覆写隐患（微秒时间戳+UUID 熵、拒绝覆盖、完整性校验与恢复点登记）；⑤ 明确 Git HEAD e897eb2 基线与 9b0eb71 业务提交归属，严格分离【协议已落盘】/【实现待完成】/【测试已验证】 |
| 1.3.0 | 2026-09-20 | Antigravity | M6.2 复审闭环加固：建立 BUSY 锁忙与普通退出码 1 区分协议；修正退出码 3 为结果未确认；补齐 QUEUED 响应前持久化与 At-Most-Once 提交前 Attempt 租约协议；确立受控安全回滚五步法（前置暂停+回滚后防线验证）；规范 SQLite 定点差异纠偏剧本（排除 PUBLISHED 终态）；明确共享读事务快照与超时物理中断释放 |
| 1.2.0 | 2026-09-20 | Antigravity | M6.2 架构审议整改：修正第 6 节回滚剧本为 Fail-Closed 只读降级与常驻进程重启 RTO、澄清 settings 构造机理与 SQLite 账本纠偏命令；收口 Bot 为单一具名任务分发客户端并扩展测试范围；纠偏会话锁互锁误区；补充影子比较器同一快照/时钟/排序/有界资源前置条件；对齐 RISK-STATE-003 与双轨红绿测试逻辑 |
| 1.1.0 | 2026-09-20 | Gemini_3.8_Flash_planning | M6.2+ 红蓝博弈迭代升级：注入 5 场红蓝博弈加固指令（防鬼魂状态、QUEUED 异步语义、正反双轨候选测试、会话共享锁对齐与美股盘中避让短路）；更新 2026-09-20 源码快照基线 |
| 1.0.0 | 2026-09-20 | Gemini_3.8_Flash_planning | 初始创建：建立多角色分工矩阵、影子开发机制、分阶段工单排期与一键回滚剧本 |

---

## 1. 架构现状与重构定位

### 1.1 现状物理规模与单体痛点 (2026-09-20 快照)
- **数据访问层单体**：[`src/video_processing/db/database.py`](../../src/video_processing/db/database.py)（`PipelineDB`），行数达 10.6k 行，245+ 方法，承担建表迁移、核心调度状态更新、各平台发布账本（WeChat, Douyin, Kuaishou）以及 English World 等多个业务领域的混合读写。
- **调度编排层单体**：[`src/video_processing/pipeline_manager.py`](../../src/video_processing/pipeline_manager.py)（`PipelineManager`），行数达 4.4k 行，其中主调度方法 `_process_single_video` 达约 1k 行，串联下载、切片、文案、字幕压制、封面生成、敏感词审查与多平台发布全流程。
- **外部执行脚本**：[`scripts/wechat_uploader.py`](../../scripts/wechat_uploader.py)（Playwright 无头/有头浏览器自动化，2.7k 行）。
- **控制平面**：Web 控制台（FastAPI `:8765`）与 Telegram 机器人（`src/bot/telegram_bot.py` 及 `pipeline_agent.py`）。
- **新增业务边界 (2026-09-19)**：视频号评论区互动系统（`WeChat-Interaction-Engine`）常驻运行，引入了 `guarded_wechat_browser_session` 浏览器会话锁。

### 1.2 重构宗旨与核心红线
1. **降低单点爆炸半径**：消除多角色同时编辑单体文件的 Git 冲突，使子模块具备清晰的输入输出边界与单元测试。
2. **绝对保真线上已有生产安全语义**：严格保留经过生产实战检验的 8 大系统不变式（`INV-001` ~ `INV-008`），特别是发布账本优先于工作流状态的原则。
3. **零生产中断与影子模式（Shadow Mode）**：任何阶段的重构代码必须先在离线沙箱、只读双跑或影子比对器中验证，绝不引发生产重复发布、假失败或脏数据。
4. **单工作区单主干纪律**：全项目仅维护 `main` 分支，禁止长期并行分支；所有代码变更遵循原子小提交、快速合流与随时可一键回滚。

---

## 2. 深度审查与红蓝博弈加固推演结果

在白盒 AST 审查与沙盒调用链推演基础上，经 2026-09-20 专项红蓝博弈压力测试，形成以下加固技术结论：

### 2.1 审查与博弈发现 1：Telegram Bot 退出码 6 误判、鬼魂状态、异步假死与会话锁契约
- **代码位置**：[`src/bot/pipeline_agent.py:L637-L752`](../../src/bot/pipeline_agent.py#L637) 与 [`scripts/wechat_uploader.py:L118-L120,L1221,L2620`](../../scripts/wechat_uploader.py#L118)
- **红队进攻揭露的致命隐患与事实核验**：
  1. **状态抹除与重复发布**：`upload_to_wechat` 将退出码 6（已点击发表但尚未落账）判为失败并置为 `FAILED`，管理员后续 `/retry` 时，`retry_video_in_db` 无条件写回 `PENDING`，导致已受理视频被二次重发封号。
  2. **无账本鬼魂状态 (Ghost State)**：若仅更新主表为 `SUBMITTED_UNBOUND` 而未写 `wechat_publications` 账本，巡检对账工具会判定状态缺乏事实支撑并强制纠偏震荡。
  3. **异步大模型幻觉**：若收口为异步接口瞬间返回成功，LLM 会误向群内宣告“已发布完成”，产生严重运维误导。
  4. **会话锁重复持锁与锁忙混淆风险**：
     - *锁持有层次*：`scripts/wechat_uploader.py:L1221`（`run_uploader`）已由 `@guarded_wechat_browser_session` 装饰持锁（`timeout_seconds=0.0, busy_result=1`）。若在 Bot 父进程也加该锁再去拉起子进程，由于锁超时为 0，子进程在同一 `state_path` 上获取锁必然立即失败并返回 `busy_result=1`，造成父子进程锁争用与立即锁忙失败；
     - *退出码 1 重载混淆*：`wechat_uploader.py` 在素材缺失（缺少视频、文案、短标题、封面）等永久性致命错误时同样 `return 1`。若调度器将所有退出码 1 盲目当作锁忙重试，会导致素材缺失的永久失败任务被无限循环重新入队！
  5. **外部执行结果映射统一校准**：
     - 退出码 `0`：发布成功（或草稿成功保存）；
     - 退出码 `6`：`EXIT_SUBMITTED_FOR_REVIEW`（已受理待审核，必须同事务写 Publication 账本并禁止自动重传）；
     - 退出码 `3`：`EXIT_RESULT_UNCERTAIN`（**发布结果未确认**，页面卡顿/超时/未跳转，绝非凭证失效，必须保留证据交由管线人工核验）；
     - 退出码 `2`：**登录凭证失效**（`LOGIN_REQUIRED`，需要扫码重新授权）；
     - 退出码 `1`：普通执行失败（素材/参数错误，不可自动重试）。
- **加固实施方案与架构边界**：
  - **Bot 收口唯一方向**：Bot 严格定位为**具名任务分发客户端**，仅负责校验操作权限、提交任务、返回 `QUEUED` 异步受理语义（包含 `task_id` 与时间戳）并校准提示词；核心应用服务统一负责安全拦截、排重抢占、子进程拉起及结果落账。
  - **锁忙与普通错误严格区分**：定义独立 BUSY 凭证机制（如特定退出码或 `[SESSION_LOCK_BUSY]` 结构化输出）。调度器**仅在捕获到明确锁忙凭据时**执行有界退避（最多 3 次指数退避）；任何缺乏锁忙凭证的通用退出码 1 均直接判定为 `FAILED`，绝不盲目重试。
  - **会话锁自洽持锁**：锁由子进程内部自洽持有；父进程/调度器负责传递统一的 `state_path` 并执行退避，父进程绝不外置重复加锁。
  - **边界声明**：SQLite 三表原子事务保障**本地状态机强一致性**；外部平台发帖物理不可逆，属于 At-Most-Once 语义，平台受理后本地崩溃窗口依赖离线人工对账，绝不可误认为本地事务能撤销外部发布。

### 2.2 审查与博弈发现 2：中心 DAL 候选过滤遗漏 DISCOVERY（`RISK-STATE-003`）与黄金测试陷阱
- **代码位置**：[`src/video_processing/db/database.py:L4253-L4305`](../../src/video_processing/db/database.py#L4253) 与权威风险登记表 `RISK-STATE-003`
- **红队进攻揭露的两大致命隐患**：
  1. **测试掩耳盗铃**：若仅修改 `GOLDEN-WF-01` 为 AUTO，无法证明“DISCOVERY 确实被阻止”。
  2. **大小写与空字符漂移**：存量脏数据中可能存在 `discovery`、带空格字符或 NULL，简单 `!= 'DISCOVERY'` 会被击穿。
- **加固实施方案与测试双轨逻辑**：
  - SQL 过滤加固为 `AND UPPER(TRIM(COALESCE(pv.source, ''))) != 'DISCOVERY'`；
  - **测试双轨红绿逻辑 (Dual-Track Testing)**：
    - *漏洞复现用例先红后绿*：在 `POLARIS-101` 中针对 DISCOVERY 漏入、Bot 退出码 6 误判及 Bot 越权重置的测试**必须先红（确证缺陷存在）**，且断言失败必须直接来自业务目标缺陷而非环境或语法报错；
    - *正常基线用例全程保绿*：正常 AUTO 候选纳入、正常 `promote_to_manual` 提拔及既有黄金场景回放必须**全程保持通过（GREEN）**，杜绝过度收紧引发正常功能退化。

### 2.3 架构拆分推演：同连接事务铁律与死锁防御
- `PipelineDB.record_wechat_submission_acceptance:L3406` 跨 3 张表强事务原子提交。
- **加固实施方案**：确立《子模块 DAL 编写规范》，子模块方法首个参数必须为 `conn: sqlite3.Connection`，严禁子模块自建连接或调用 `get_connection()`，由外层门面持有事务上下文，防止 SQLite 同进程并发死锁。

---

## 3. 借鉴 `/teamwork-preview` 的多角色分工协作体系

全面借鉴 `/teamwork-preview` 的职责分离模式，设立 5 大专业职能角色，各司其职、形成强制互锁：

```
                   ┌────────────────────────────────────────────────────────┐
                   │    1. 系统首席架构师兼安全门禁官 (Lead System Architect)   │
                   │    - 掌控 8 大不变式、5 类信封与 Gate 签署、唯一解锁权    │
                   └───────────────┬────────────────────────┬───────────────┘
                                   │ 签发工单 / 设定边界   │ 门禁评审
                                   ▼                        ▼
┌──────────────────────────────────────┐        ┌──────────────────────────────────────┐
│  2. 影子研发工程师 (Shadow Dev)       │        │  3. 对抗式红队审计员 (Red-Team)       │
│  - 纯影子实现、内部委托、配置降级开关 │        │  - 构造边界反例、设计退出码6/死锁注入│
└──────────────────┬───────────────────┘        └──────────────────┬───────────────────┘
                   │ 提交补丁                                      │ 提交攻击用例
                   └───────────────────────┬──────────────────────┘
                                           ▼
                       ┌──────────────────────────────────────┐
                       │  4. 测试与防护网工程师 (Harness QA)  │
                       │  - 离线沙箱、黄金回放、红灯先行验证  │
                       └───────────────────┬──────────────────┘
                                           │ 输出机器可信证据 (Receipt)
                                           ▼
                       ┌──────────────────────────────────────┐
                       │  5. SRE 运维与回滚守护官 (SRE)       │
                       │  - 任务空闲窗口复核、单主干原子提交  │
                       └──────────────────────────────────────┘
```

### 3.1 角色职责与边界矩阵 (Role & Responsibility Matrix)

| 角色名称 | 核心职责 (What to do) | 严禁行为 (Strict Non-Goals) | 关键交付物 (Key Deliverables) |
| :--- | :--- | :--- | :--- |
| **1. 系统首席架构师兼门禁官<br/>(Lead Architect & Gatekeeper)** | • 维护系统 8 大不变式（`INV-001`~`INV-008`）与 5 类兼容性信封<br/>• 负责各阶段 Gate（M6→M6.5→M7→M8→M9）的准入与准出评估<br/>• 拥有唯一的工单解锁与一票否决权 | • 严禁放宽发布账本优先原则<br/>• 严禁在未获机器证明前凭经验放行重构 | • Gate 准入准出签署报告<br/>• 架构契约修订案（更新 `refactor_handoff.md`） |
| **2. 影子研发工程师<br/>(Shadow Dev Engineer)** | • 遵循“Specify What, Not How”，只实现工单明确要求的功能<br/>• 编写无副作用的影子双跑器（Shadow Runner）与内部委托层<br/>• 为所有修改配置硬编码熔断降级开关（Feature Flags） | • 严禁触碰真实外部发布接口（WeChat/Douyin/Kuaishou）<br/>• 严禁随意更改现有 Public API 签名或数据库 Schema | • 影子双跑逻辑与内部委托补丁<br/>• 降级配置开关与 Fail-Closed 兜底处理 |
| **3. 对抗式红队审计员<br/>(Adversarial Auditor)** | • 专门针对重构方案挑刺，模拟极端边界与攻击向量<br/>• 构造注入场景：网络断开、退出码 6、长事务死锁、并发抢占<br/>• 审计状态分叉隐患，确保所有异常路径均为 Fail-Closed | • 严禁认可任何“看似合理但缺乏断言”的自我证明<br/>• 严禁妥协安全标准以迎合进度 | • 针对工单的《对抗式漏洞推演报告》<br/>• 失败注入用例规范（Fault Injection Specs） |
| **4. 测试与防护网工程师<br/>(Harness QA Engineer)** | • 维护独立沙箱环境（`scripts/run_isolated_tests.py`）<br/>• 负责黄金场景可执行回放数据集（Hermetic Golden Replay）<br/>• 执行“红灯先行（Test-First）”，先产生失败证据，后验证修复 | • 严禁使用系统全局环境直接跑裸 `pytest`<br/>• 严禁构造依赖外部网络或生产数据库的测试用例 | • 目标回归测试套件（红灯/绿灯完整证据）<br/>• 机器可信测试报告（Receipt JSON） |
| **5. SRE 运维与回滚守护官<br/>(SRE & Rollback Guardian)** | • 监控流水线运行状态，避开 09:00/21:00 cron 与空闲窗口判断<br/>• 严格执行单主干 Git 纪律，保护无关未提交工作<br/>• 准备原子回滚剧本，在发生异常时 30 秒内一键熔断回滚 | • 严禁在流水线处理或发布进行中触发测试或合并<br/>• 严禁私自启动或重启生产长驻进程 | • 生产环境空闲度审计日志<br/>• 一键回滚脚本与配置熔断验证证明 |

---

## 4. 影子开发（Shadow Mode）工程落地规范

### 4.1 副作用五分级与影子验证策略

```text
[PURE_READ]          ──> 内存级实时双跑比对 (Shadow Comparator) ──> 零写入，仅报警，主逻辑返回旧版
[DECISION]           ──> 规则引擎离线回放 + 线上双跑 ────────────> 零副作用，记录判定差分
[PERSISTENCE]        ──> 临时 SQLite 沙箱事务回滚回放 ───────────> 验证 SQL 一致性，严禁直连主库
[LOCAL_SIDE_EFFECT]  ──> 隔离临时目录 (/tmp/shadow_*) ───────────> 校验音视频/文案文件 Hash
[EXTERNAL_SIDE_EFFECT]──> ❌ 严禁线上双跑 ────────────────────────> 必须纯虚拟 Mock / Dry-Run
```

### 4.2 影子双跑比对器规范 (Shadow Dual-Run Comparator)

针对 `PURE_READ`（只读报表查询）和 `DECISION`（审查与发布窗口决策），必须遵循以下封装规范：
1. **主逻辑绝对优先**：始终无阻塞、低延迟地执行现有稳定逻辑并返回结果。
2. **异常零泄漏**：影子分支内发生的任何异常必须被内部 `try...except` 完全吞掉，仅打印 `logger.error` 并记录 Telemetry，绝不能导致主业务报错。
3. **动态可控**：必须通过 `settings.py` 暴露动态开关（如 `enable_shadow_comparison: bool = False`），支持在生产环境通过配置调整与守护进程热重启快速受控。
4. **盘中窗口强制静默 (Market Guard Short-Circuit)**：接入 `settings.is_us_market_guard_window()`，在美股盘中交易时段影子比对自动短路，绝对不消耗 CPU/磁盘 I/O，优先保障 OptionSense 实盘算力。
5. **采样限频保护 (Sampling & Log Throttling)**：比对器默认仅抽样 10% 请求进行影子执行；同类差异日志采用滑动窗口限流（单小时最多 3 次），杜绝日志雪崩。
6. **显式只读事务快照与时钟确定性前置条件 (Explicit Read Snapshot & Determinism)**：在 Gate M7 启动前，比对器必须强制满足以下三项物理前置条件，杜绝异步时钟与并发写入引入伪差异：
   - **显式开启读事务快照（严禁误用 `with conn:` 假读事务）**：
     > [!IMPORTANT]
     > Python `sqlite3` 官方规范明确指出：连接上下文管理器 `with conn:` 仅负责在异常时回滚、正常时提交，**绝对不会在执行 SELECT 语句前隐式开启事务**（在默认非 autocommit 模式下，事务仅在首个 DML/DDL 写入语句时才隐式开始）。因此，仅用 `with conn:` 包裹两次 SELECT **物理上无法创建共享读事务快照**！若两次 SELECT 之间存在并发写入提交，后一次查询将直接读到外部的新数据而引发假分叉。
     - **必须显式执行 SQL 开启事务**：比对器必须在专用读连接上显式执行 `conn.execute("BEGIN DEFERRED")`；随后的首条 SELECT 语句将锁定 WAL 读版本快照，第二条 SELECT（影子比对实现）在同一连接、同一事务内执行，从而物理保证两次查询读取到绝对同一的数据快照（Repeatable Read）。
     - **并发快照验收门禁**：必须编写专门的并发隔离测试：线程 1 执行 `BEGIN DEFERRED` 并完成 Query 1；随后线程 2 向被测表插入一条新记录并 COMMIT；线程 1 执行 Query 2，**必须硬性断言无法看到线程 2 新提交的记录**，以此作为快照隔离的机器证据。
     - **事务显式终止与连接清理**：查询比对完成后（或触发超时/中断时），必须显式执行 `conn.execute("ROLLBACK")` 结束事务，并显式调用 `conn.close()` 关闭影子专用连接，确保 SQLite C 引擎彻底释放底层 WAL 读锁，绝不阻塞后台 WAL Checkpoint。
   - **确定性唯一排序 (Deterministic Ordering with Unique Tie-Breaker)**：涉及分页和列表的查询，SQL 必须显式包含全局唯一键排序（例如 `ORDER BY created_at DESC, youtube_id ASC, slice_index ASC`），消除 SQLite 内部遍历顺序漂移。
   - **虚拟固定时钟 (Virtual Fixed Clock)**：包含相对时间过滤的查询，必须在函数入口捕获固定时间快照 `frozen_time` 并透传至双跑分支，消除微秒级时间差分。
7. **有界资源与底层物理中断超时 (Bounded Resources & Physical Query Interruption)**：
   - 影子异步执行队列必须设为硬上限有界队列（最大深度 100）；
   - 独立工作线程池并发上限设为 2；
   - **200ms 硬超时必须验收底层资源释放**：不仅是在 Python 层放弃结果等待，必须调用底层 `sqlite3_interrupt()` 或物理关闭影子连接，确保底层 SQLite C 引擎物理终止耗时查询并立即释放读锁与内存，严禁孤儿查询在后台无界空转占用 CPU 与磁盘 I/O；超时后同样必须完成连接关闭与读锁释放；
   - 当队列满或系统 CPU/内存压力高时，触发**静默丢弃与降级采样**，严禁积压内存或拖慢主请求响应。

---

## 5. 分阶段实操工单推进计划（从 POLARIS-000 到 POLARIS-105）

严格遵循 **Gate 驱动与“红灯先行”协议**，各角色按以下流水线推进工作：

### 5.1 工单详细推进流程与验收护栏

#### `POLARIS-000` — 生产现场、Git、运行空闲与文档基线复核
- **主责**：`SRE 运维守护官`；**复核**：`系统首席架构师`
- **前置**：接收到用户口令（`继续北辰重构`）。
- **执行**：
  1. 运行 `git status --short --branch`，确认处于 `main` 且工作树 CLEAN。
  2. 核对系统时间，确认不在每日 09:00 / 21:00 定时处理窗口内。
  3. 检索系统进程，确保无正在运行的 `wechat_uploader.py` 或 Playwright 实例。
- **验收护栏 (Guardrails)**：
  - [ ] Git 工作树处于绝对 CLEAN 状态。
  - [ ] 架构门禁官签署《POLARIS-000 准入放行令》。

#### `POLARIS-101` — 补写真实入口级隔离回归测试（双轨红绿与完整边界测试）
- **主责**：`测试与防护网工程师`；**协同**：`对抗式红队审计员`
- **前置**：`POLARIS-000` 签署完成。
- **执行**：
  1. **测试双轨红绿逻辑规范**：
     - *漏洞复现用例先红后绿*：在 `tests/unit/` 下新增针对 Bot 退出码 6（Mock 返回 exit code 6，断言当前系统是否错误判定为 `FAILED`）与越权重置（对已有发布账本记录执行 Bot 重置，断言当前系统是否放行）的测试用例；新增 DISCOVERY 候选泄露测试。上述用例在修复前**必须 100% 失败（产生预期红灯证据）**，且断言失败必须直接证明业务目标缺陷（非环境/语法错误）。
     - *现有基线用例全程保绿*：现有正常 AUTO 候选纳入用例、现有正常 `promote_to_manual` 提拔用例以及全套黄金回放数据集，在整个过程中**必须全程保持绿灯（GREEN）**，杜绝过度收紧导致既有正常逻辑受损。
  2. **全面扩展真实入口级测试边界**：
     - **视频删除操作覆盖 (`delete_video_from_db`)**：断言当视频存在关联微信发布账本时，删除操作是否具备级联清理安全或拒绝删除保护；
     - **并发重置与重复触发幂等性**：模拟并发调用调度接口，断言系统能否幂等拦截重复请求并复用已有 `task_id`；
     - **外部执行退出码 3 (`EXIT_RESULT_UNCERTAIN`) 结果映射**：断言退出码 3 精准识别为“发布结果未确认”（网络超时或页面未确认），系统必须保留现场素材与日志，标记为待人工核验，绝对不得触发自动重试，也不得误判为登录凭证失效（退出码 2）；
     - **子进程超时保护与资源清理**：模拟浏览器自动化长时间挂起，断言系统能否在配置超时后正常回收进程组并安全处理；
     - **外部已受理但本地写账本失败的崩溃窗口与租约恢复**：模拟在调用上传器前写入持久化 Attempt 租约；模拟在微信平台点击发表后、本地写入 Publication 账本前发生进程 SIGKILL，断言系统重启后检测到未确认的 `IN_PROGRESS` 尝试，强制 Fail-Closed 进入 `UNCERTAIN` 并阻止自动重复提交；
     - **转入 UNCERTAIN 后再次领取任务仍被拒绝的阻断测试 (`test_claim_attempt_rejected_when_prior_attempt_is_uncertain`)**：构建场景：前序任务因未决超时或崩溃恢复被标记为 `UNCERTAIN`（无论在 `wechat_submission_active_claims`、`wechat_submission_attempts` 还是 `wechat_publications` 中），断言调用发布任务原子领取 CAS 接口时**必须 100% 被拒绝**（抛出或返回 `SubmissionClaimRejectedUncertain` 结构化拒绝原因），且无任何新 Attempt 行插入，物理验证无法穿透阻断；
     - **独立活跃租约生命周期与条件释放测试 (`test_active_claims_lease_lifecycle`)**：在沙箱内断言 `wechat_submission_active_claims` 与 `wechat_submission_attempts` 在单事务内的原子创建；断言并发冲突时第二个领取被拒绝；断言携带匹配的 `active_attempt_id` 时可正常释放或更新状态，携带不匹配 ID 时无法篡改或删除他人租约；
     - **历史 Attempt 存在时的独立阻断测试 (`test_claim_attempt_rejected_when_only_historical_attempt_exists`)**：断言当某视频仅存在历史 `wechat_submission_attempts`（状态为 `SUBMITTED_UNBOUND` / `PLATFORM_ID_BOUND` / `UNCERTAIN`），且租约表 `wechat_submission_active_claims` 与 Publication 账本尚无记录时，调用原子领取接口**必须坚决被拒绝**（抛出或返回已发布/未决错误），绝不重复领取与重复发帖；
     - **外键兼容与领取失败原子回滚无残留测试 (`test_claim_attempt_rollback_leaves_no_residual_on_failure`)**：断言在 `BEGIN IMMEDIATE` 事务中，若步骤 3（插入租约表）遭遇主键冲突或外部异常失败，整个事务干净回滚，步骤 2 先行写入的 Attempt 审计行**必须完全回滚，数据库无任何残留孤儿数据**；
     - **微信真实会话锁规范化探测与持锁反例测试 (`test_wechat_session_lock_probe_detects_real_hold_and_release`)**：调用 `canonical_wechat_session_lock_path("output/wechat_state.json")` 解析出真实锁文件（`.wechat_state.json.browser.lock`）；断言当后台线程通过 `WeChatSessionLock` 持有该真实锁时，探测脚本**必须捕获 `BlockingIOError` 并判定为锁忙失败（非零退出码反例）**；持锁线程释放后，探测脚本必须成功断言为 FREE（返回码 0）。
- **验收护栏 (Guardrails)**：
  - [ ] **严禁修改任何生产代码**。
  - [ ] 漏洞用例红灯证据归档，正常基线用例全绿通过。

#### `POLARIS-102` — 封闭 Telegram Bot 直接 Uploader 与任意状态重置旁路
- **主责**：`影子研发工程师`；**协同**：`对抗式红队审计员`
- **前置**：`POLARIS-101` 红灯证据归档。
- **执行**：
  1. **QUEUED 响应前持久化协议与幂等复用**：
     - Bot 严格改造为具名任务分发客户端，仅负责权限校验与提交任务；
     - **响应前强制持久化 (Pre-Dispatch Durable Record)**：收到调度请求后，先在 SQLite 中原子持久化写入分发任务记录（包含 `task_id`、排队时间戳及目标视频状态），**随后**才向客户端返回 `QUEUED` 异步受理语义，杜绝内存丢单；
     - **重复请求幂等复用**：对处于活跃状态（`DISPATCHED` / `DOWNLOADING` / `PUBLISHING` / `UNDER_REVIEW`）的视频，幂等拦截并返回既有 `task_id` 与 `ALREADY_QUEUED`，杜绝重复创建并发流水线。
  2. **外部提交前不可自动重试 Attempt 租约、独立活跃租约表与原子领取规则 (Pre-Submission Non-Retryable Lease & Atomic Claim Protocol)**：
      - **架构选型裁决：明确采用方案 A（独立原子活跃租约表），彻底废弃方案 B**：
        - *方案 B 废弃技术裁决*：方案 B 试图在迁移时先执行 `UPDATE ... SET state = 'SUBMITTED_UNBOUND_ARCHIVED'`，但在原表 CHECK 约束尚未放开时会直接抛出 `CHECK constraint failed` 异常；且若历史数据存在相同 `created_at` 时间戳（如同一秒内多次重试），`a.created_at < b.created_at` 条件无法去重，后续建唯一索引仍将因重复项触发 `IntegrityError` 崩溃。故方案 B 不具备工业可操作性，**正式废弃，禁止作为备用剧本**；
        - *方案 A 表结构增量迁移契约 (Schema Migration for Scheme A)*：
          ① **Attempt 历史表 CHECK 约束平滑扩展**：
             `database.py:803` 现有约束为 `CHECK(state IN ('SUBMITTED_UNBOUND', 'PLATFORM_ID_BOUND'))`。在 `PipelineDB._migrate_database()` 迁移事务中检测建表 DDL 是否支持 `'IN_PROGRESS'`；若不支持，在单个 SQLite 事务中执行标准表重构：
             重命名旧表为 `wechat_submission_attempts_legacy` -> 新建表将 CHECK 约束升级为：
             `CHECK(state IN ('IN_PROGRESS', 'SUBMITTED_UNBOUND', 'PLATFORM_ID_BOUND', 'UNCERTAIN', 'RELEASED_BUSY'))`；
             全量复制数据并清理旧表。注意：新表**不建任何 `subject_id` 唯一约束**，保持为纯追加审计历史账本，存量所有重复 Attempt 100% 无损保留，零迁移冲突；
          ② **创建独立原子活跃租约表 `wechat_submission_active_claims`**：
             ```sql
             CREATE TABLE IF NOT EXISTS wechat_submission_active_claims (
                 subject_id TEXT PRIMARY KEY,
                 video_id INTEGER NOT NULL,
                 active_attempt_id TEXT NOT NULL,
                 claim_state TEXT NOT NULL CHECK(claim_state IN ('IN_PROGRESS', 'SUBMITTED_UNBOUND', 'PLATFORM_ID_BOUND', 'UNCERTAIN')),
                 claimed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                 updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                 FOREIGN KEY(subject_id) REFERENCES publication_subjects(id) ON DELETE RESTRICT,
                 FOREIGN KEY(active_attempt_id) REFERENCES wechat_submission_attempts(attempt_id) ON DELETE RESTRICT,
                 FOREIGN KEY(video_id) REFERENCES processed_videos(id) ON DELETE RESTRICT
             );
             ```
             `subject_id` 为主键，物理上天然保证每个发布主体全局仅存在至多一条活跃租约，彻底杜绝历史数据与高频互斥的耦合。
      - **外键兼容与四表联合原子领取契约 (FK-Compatible Joint Atomic Claim in Single Transaction)**：
        - 拉起 `wechat_uploader.py` 之前，必须在单个 SQLite 写入事务（`BEGIN IMMEDIATE`）内严格按外键依赖与防御顺序执行：
          - *步骤 1：多表联合前置阻断判定 (Pre-Claim Joint Blocking Check)*：
            在事务内查询当前 `subject_id` 是否满足所有阻断条件（租约表、历史 Attempt 表、Publication 事实表、主表状态）：
            ```sql
            SELECT 
                -- 阻断 1: 租约表中已存在活跃租约（IN_PROGRESS / SUBMITTED_UNBOUND / PLATFORM_ID_BOUND / UNCERTAIN）
                (SELECT claim_state FROM wechat_submission_active_claims WHERE subject_id = ? LIMIT 1) AS active_claim_state,
                -- 阻断 2: 历史 Attempt 表中已存在记录（保留历史 Attempt 的联合阻断，杜绝存量独立 Attempt 漏网）
                (SELECT state FROM wechat_submission_attempts 
                 WHERE subject_id = ? AND state IN ('IN_PROGRESS', 'SUBMITTED_UNBOUND', 'PLATFORM_ID_BOUND', 'UNCERTAIN') 
                 ORDER BY created_at DESC LIMIT 1) AS latest_attempt_state,
                -- 阻断 3: Publication 事实表中已存在未结或已发布记录
                (SELECT state FROM wechat_publications 
                 WHERE subject_id = ? AND state IN ('SUBMITTED_UNBOUND', 'SUBMITTED_BOUND', 'UNDER_REVIEW', 'UNCERTAIN', 'PUBLISHED') 
                 ORDER BY created_at DESC LIMIT 1) AS pub_state,
                -- 阻断 4: 对应视频主表状态处于已受理或已发布终态
                (SELECT status FROM processed_videos 
                 WHERE id = ? AND status IN ('SUBMITTED_UNBOUND', 'SUBMITTED_BOUND', 'UNDER_REVIEW', 'UNCERTAIN', 'PUBLISHED') 
                 LIMIT 1) AS main_status;
            ```
            *阻断判定与原子回滚*：
            若上述任一阻断字段非空，说明存在在途、未决或已发布冲突，立即执行 `ROLLBACK`：
            - 若任一冲突源状态为 `UNCERTAIN`，直接抛出 `SubmissionClaimRejectedUncertain("任务处于未决 UNCERTAIN 状态，禁止自动重领重发，必须人工核对微信后台后线下核销")`；
            - 若处于已受理或已发布终态（`SUBMITTED_*`, `PLATFORM_ID_BOUND`, `UNDER_REVIEW`, `PUBLISHED`），返回 `SubmissionClaimRejectedAlreadyPublished`；
            - 若处于 `IN_PROGRESS`，返回 `SubmissionClaimRejectedBusy`。
          - *步骤 2：同事务优先插入 Attempt 历史审计行 (Satisfies Foreign Key)*：
            若步骤 1 阻断检查完全通过，**必须先向 `wechat_submission_attempts` 插入新 Attempt**：
            ```sql
            INSERT INTO wechat_submission_attempts (attempt_id, video_id, subject_id, state, final_title, ...)
            VALUES (?, ?, ?, 'IN_PROGRESS', ?, ...);
            ```
            *设计原由*：`wechat_submission_active_claims.active_attempt_id` 外键引用 `wechat_submission_attempts.attempt_id`。SQLite 在默认开启外键检查（`PRAGMA foreign_keys = ON;`）且未声明延迟检查时，要求被引用的主表行必须先于外键行存在。因此必须先写 Attempt，杜绝 `FOREIGN KEY constraint failed` 异常。
          - *步骤 3：同事务插入活跃租约表 (Foreign Key Guaranteed & PK Mutex)*：
            紧接着向 `wechat_submission_active_claims` 插入活跃租约：
            ```sql
            INSERT INTO wechat_submission_active_claims (subject_id, video_id, active_attempt_id, claim_state)
            VALUES (?, ?, ?, 'IN_PROGRESS');
            ```
            *外键与主键双重互斥保证*：
            ① 由于步骤 2 已先行写入 `wechat_submission_attempts`，步骤 3 的 `FOREIGN KEY(active_attempt_id)` 立即满足约束，绝不触发外键失败；
            ② `subject_id` 为 `PRIMARY KEY`，若有并发事务抢先写入，步骤 3 将触发 `sqlite3.IntegrityError: UNIQUE constraint failed`，事务捕获异常后立即执行 `ROLLBACK`，步骤 2 插入的 Attempt 随之原子清除，绝不留存孤儿数据。
          - *步骤 4：原子提交 (Atomic Commit)*：
            执行 `COMMIT`。执行者原子获得排他性租约，物理杜绝多执行者并发与历史/在途重复发布。
      - **按 `active_attempt_id` 条件释放与生命周期闭环契约 (Conditional Release & Terminal Rules)**：
        - **BUSY 退出条件释放**：当子进程因会话锁争用退出并携带明确 BUSY 凭证（`[SESSION_LOCK_BUSY]`）时，调度系统在单一事务中执行：
          ```sql
          -- 条件释放：必须携带 active_attempt_id 与 claim_state 条件精确删除，防止误删新租约
          DELETE FROM wechat_submission_active_claims 
          WHERE subject_id = ? AND active_attempt_id = ? AND claim_state = 'IN_PROGRESS';
          
          -- 同事务更新 Attempt 历史审计
          UPDATE wechat_submission_attempts 
          SET state = 'RELEASED_BUSY' 
          WHERE attempt_id = ? AND state = 'IN_PROGRESS';
          ```
          释放成功后，调度系统进入有限指数退避（最多 3 次），退避到期后申请全新 `attempt_id` 重新原子 CAS 领取；
        - **退出码 6 正常受理落账**：在复合 4 表强原子事务中：
          ```sql
          -- 更新活跃租约状态为 SUBMITTED_UNBOUND（持续占用主键，防止重领）
          UPDATE wechat_submission_active_claims 
          SET claim_state = 'SUBMITTED_UNBOUND', updated_at = CURRENT_TIMESTAMP 
          WHERE subject_id = ? AND active_attempt_id = ?;
          
          UPDATE wechat_submission_attempts 
          SET state = 'SUBMITTED_UNBOUND' 
          WHERE attempt_id = ?;
          
          INSERT INTO wechat_publications (video_id, subject_id, state, evidence_path, ...)
          VALUES (?, ?, 'SUBMITTED_UNBOUND', ?, ...);
          
          UPDATE processed_videos SET status = 'SUBMITTED_UNBOUND' WHERE id = ?;
          ```
        - **崩溃恢复与禁止重领 (Fail-Closed Crash Recovery)**：若进程在外部发布被微信受理与本地事务完成之间遭遇崩溃（`SIGKILL`），系统重启扫描到悬空 `claim_state = 'IN_PROGRESS'` 租约：
          ```sql
          UPDATE wechat_submission_active_claims 
          SET claim_state = 'UNCERTAIN', updated_at = CURRENT_TIMESTAMP 
          WHERE subject_id = ? AND active_attempt_id = ? AND claim_state = 'IN_PROGRESS';
          
          UPDATE wechat_submission_attempts 
          SET state = 'UNCERTAIN' 
          WHERE attempt_id = ? AND state = 'IN_PROGRESS';
          
          UPDATE processed_videos SET status = 'UNCERTAIN' WHERE id = ?;
          ```
          由于 `wechat_submission_active_claims` 持续占位且状态为 `UNCERTAIN`，后续所有领取请求必须 100% 被拒，物理锁定，必须由人工核验微信后台后线下核销，真正物理闭环 At-Most-Once。
  3. **前置接入发布账本守卫**：在 `update_video_status` 与 `retry_video_in_db` 前置引入发布账本守卫，拒绝将已受理/已发布记录打回 `PENDING`。
  4. **退出码 6 原子四表落账**：在任务执行落地层捕获退出码 6 时，调用复合原子事务方法更新活跃租约、写入 Publication 账本、更新 Attempt 记录与主表 `SUBMITTED_UNBOUND` 状态，彻底杜绝无账本鬼魂状态。
  5. **锁忙与普通错误严格区分及会话锁协作**：
     - 执行环境接入 `_build_subprocess_env`；保持子进程内部 `@guarded_wechat_browser_session` 自洽持锁，父进程绝不外置重复持锁（防止锁超时为 0 导致立即 busy）；
     - 严格区分锁忙与通用错误：**仅在存在明确 BUSY 凭证时**执行有限指数退避重试（最多 3 次）；通用退出码 1（素材/配置错误）直接判定为不可自动重试失败，避免永久失败任务死循环入队。
  6. **架构边界声明**：确立 SQLite 四表原子事务保障**本地状态机一致性**，外部物理发帖遵循 At-Most-Once 语义，平台受理后的崩溃依赖离线人工对账。
  7. 引入特性开关 `settings.enable_bot_status_guard`。
- **验收护栏 (Guardrails)**：
  - [ ] `POLARIS-101` 中针对 Bot 的漏洞测试由红变绿，正常基线用例继续全绿。
  - [ ] 阻止对已受理视频执行重置并返回结构化拒绝原因，无账本分叉。

#### `POLARIS-103` — DAL 候选咽喉硬排除 DISCOVERY 与黄金契约修正
- **主责**：`影子研发工程师`；**协同**：`测试与防护网工程师`
- **前置**：`POLARIS-101` 红灯证据归档。
- **执行**：
  1. 修改 `PipelineDB.get_high_score_pending_videos()`，在 SQL WHERE 语句中加入 `AND UPPER(TRIM(COALESCE(pv.source, ''))) != 'DISCOVERY'`。
  2. 修正 `tests/fixtures/golden_replay/scenarios/GOLDEN-WF-01/` 夹具，将 `source` 改为 `"AUTO"`，纠偏黄金断言契约（正向排重生命周期验证）。
- **验收护栏 (Guardrails)**：
  - [ ] `POLARIS-101` 中针对 DISCOVERY 过滤的正反双轨测试全绿。
  - [ ] 全套黄金回放数据集（`test_golden_replay_dataset.py`）沙箱运行全绿。

#### `POLARIS-104` — 治理文档、风险登记册与状态矩阵语义对齐
- **主责**：`系统首席架构师兼门禁官`；**协同**：`SRE 运维守护官`
- **前置**：`POLARIS-102` 与 `POLARIS-103` 实施完毕且测试全绿。
- **执行**：
  1. 更新 `refactor_handoff.md`，将 `RISK-STATE-001` 与 `RISK-STATE-003` 标记为 `REMEDIATED`，`INV-008` 恢复为 `CONFIRMED`。
  2. 更新 `work_orders.md`，标记 `WO-STATE-001` 为 `COMPLETED`，解锁 `WO-SHADOW-001` 的准入门禁。
- **验收护栏 (Guardrails)**：
  - [ ] 治理文档内部引用行号、API 符号与最新代码库 100% 精确匹配。
  - [ ] 00_README 与 handoff 更新版本记录。

#### `POLARIS-105` — 全量隔离回归验证、目标原子提交与推送
- **主责**：`SRE 运维守护官`；**协同**：`系统首席架构师`
- **前置**：`POLARIS-101` ~ `POLARIS-104` 全部验收通过。
- **执行**：
  1. 运行完整非浏览器单元测试套件：
     `.venv/bin/python scripts/run_isolated_tests.py -- -q tests/unit`
     确保 1600+ 单元测试 100% 通过（零回归）。
  2. 仅暂存本工单目标修改文件，严禁夹带无关改动。
  3. 执行单主干 Git 提交并推送至 `origin main`。
- **验收护栏 (Guardrails)**：
  - [ ] 完整非浏览器单测全量通过。
  - [ ] 分别报告：文件变更完成、测试通过、Git 提交完成、推送完成、生产运行待采用。

---

## 6. 极速止血、常驻进程重启与账本纠偏操作剧本 (Rollback & Repair Playbooks)

> **配置热载机理说明**：当前项目配置单例 `settings = Settings()` 在模块导入时完成静态初始化（`from config.settings import settings`）。修改 `.env` 文件**不会**被常驻进程自动热感应；凡涉及配置生效或回滚，必须伴随常驻服务重启（`./vpanel bot restart` 或 `./vpanel ui restart`）。

| 故障现象 | 触发特征 | 应对级别 | 立即止血与回滚操作 (Immediate Action) | 恢复时效 (RTO) |
| :--- | :--- | :---: | :--- | :--- |
| **Bot 状态守卫异常阻断正常运维** | 正常合规的任务重置被意外拦截报错 | P2 | **严禁回退至无拦截危险透传！**<br/>执行 Fail-Closed 只读降级：暂停 Bot 重试与重置高危写指令，保留状态查询与核验；如需调整配置，更新 `.env` 后重启进程：`./vpanel bot restart` | `< 1 分钟` |
| **SQL 语法异常导致核心调度器停摆** | `get_high_score_pending_videos` 报错抛出异常 | P1 | **严禁无条件裸回滚！必须执行受控安全回滚五步法**（详见下文 6.1 节）：<br/>① 停写、终止在途执行进程并严格核验无活跃消费；<br/>② 绑定具体提交回滚 `git revert <TARGET_SHA> --no-edit`；<br/>③ 沙箱运行 POLARIS-101 新增防线测试（失败则坚决保持暂停）；<br/>④ 推送并重启全套守护进程；<br/>⑤ 确认平稳后恢复调度 | `< 3 分钟` |
| **影子双跑引发高 CPU 占用或内存暴涨** | 比较器日志大量告警，系统负载陡增 | P2 | 修改 `.env` 中 `ENABLE_SHADOW_COMPARISON=false`，执行 `./vpanel ui restart`，影子比对硬短路退出 | `< 1 分钟` |
| **外部社交平台凭据大面积失效** | 密集出现退出码 2 或 3 | P1 | 设置 `.env` 中 `WECHAT_PUBLISHING_PAUSED=true` 并重启调度器，全系统进入发布 Fail-Closed 保护 | `< 1 分钟` |

### 6.1 受控安全回滚五步机制 (Controlled Safe Rollback Protocol)

> [!CAUTION]
> **严禁裸 Revert 撤销安全防线**：若仅简单执行 `git revert`，虽然能消除新引入的代码语法错误，但同时会撤掉对已知严重漏洞（如 DISCOVERY 误发微信、Bot 任意重置已受理任务）的安全拦截，导致系统裸奔于不设防状态。凡触及安全防线的回滚，必须严格执行以下五步：

1. **第一步：前置全局停写、任务启动源封闭、在途任务清空与执行进程零消费物理核验 (Pre-Rollback Quiesce, Trigger Sealing & Zero-Consumer Verification)**：
   > [!IMPORTANT]
   > 运行 `./vpanel ui restart` 或 `ui stop` 仅仅管理 FastAPI 控制中心（`:8765`），**绝对无法停止**通过 cron 定时拉起、手动 `job run` 启动的独立 `PipelineManager` 进程、`Bot` 守护进程、以独立会话启动的互动 Worker (`pipeline_manager.py:1086` `start_new_session=True`) 以及正在执行的 `wechat_uploader.py` 浏览器进程！修改 `.env` 也无法使已经在运行中的进程自动热重载！若不在启动源头加锁，cron 会在回滚窗口内随时拉起新任务！必须执行以下七小步严格停写：
   - **第一小步（封闭宿主任务启动源，防定时任务/重入秒级复活）**：
     彻底脱离对应用层可被 `git revert` 代码的依赖，提升为 OS 宿主级物理静音：
     ```bash
     # 1. 导出当前宿主 crontab 备份
     crontab -l > "output/crontab_backup_$(date +%Y%m%d_%H%M%S).txt"

     # 2. 物理静音所有 Video-precessing 调度任务（加 # QUIESCE_DISABLED 前缀）
     crontab -l | sed -E '/Video-precessing/s/^([^#])/# QUIESCE_DISABLED \1/' | crontab -

     # 3. 严格核验活跃调度已清空（必须输出为空，否则立即人工排查）
     crontab -l | grep -v '^[[:space:]]*#' | grep 'Video-precessing'

     # 4. 创建本地调度冻结锁文件（双重进程内硬短路防线）
     touch output/pipeline_freeze.lock
     ```
     *规范约束*：所有管线与调度入口（`monitor_channels.py`、`pipeline_manager.py`、`run_publication_window.py`、`vpanel job run` 等）在启动前置检查 `output/pipeline_freeze.lock`；若文件存在，立即记入日志 `[FROZEN] 调度已全局冻结，跳过执行` 并以退出码 0 安全退出；配合宿主 crontab 物理静音，彻底杜绝回滚窗口内 cron（每分钟 `run_publication_window`、每 30 分钟 monitor、每天 09:00/21:00 定时发布）拉起新任务；
   - **第二小步（置环境变量与配置双重防护）**：在 `.env` 中将发布总开关置为暂停：`WECHAT_PUBLISHING_PAUSED=true`，双重阻止任何新拉起的进程消费外部发布；
   - **第三小步（停常驻服务）**：
     ```bash
     ./vpanel ui stop
     ./vpanel bot stop
     ```
   - **第四小步（整树扫描与进程组彻底清理，含 setsid worker 与 Chromium 孤儿）**：
     - 检索所有关联进程及其 PGID（进程组 ID）：
       ```bash
       ps -eo pid,pgid,ppid,command | grep -E "pipeline_manager|wechat_uploader|wechat_commenter|bot_daemon|web.app" | grep -v grep
       ```
     - 向各活跃进程组发送终止信号（涵盖 `pipeline_manager.py:1086` 以 `start_new_session=True` 启动的独立进程组）：
       `kill -TERM -<PGID>`
     - 清理残留的 Playwright Chromium 孤儿浏览器进程：
       `pgrep -fl "chromium.*wechat" | awk '{print $1}' | xargs -r kill -TERM`
     - 等待 30 秒；若仍有存活，执行强行终止：`kill -KILL -<PGID>` 及 `kill -KILL <PID>`；
   - **第五小步（会话排他锁与物理资源释放核验）**：
     通过 Python 脚本调用 `canonical_wechat_session_lock_path` 对实际派生的锁文件 `output/.wechat_state.json.browser.lock` 进行非阻塞 flock 探测，确保真实文件锁已被物理操作系统释放：
     ```bash
     PYTHONPATH=src .venv/bin/python -c "
     import fcntl
     from pathlib import Path
     from video_processing.core.wechat_session_lock import canonical_wechat_session_lock_path
     from config.settings import settings

     lock_path = canonical_wechat_session_lock_path(settings.wechat_state_path)
     print(f'正在探测真实会话锁: {lock_path}')
     lock_path.parent.mkdir(parents=True, exist_ok=True)
     try:
         with open(lock_path, 'a') as f:
             fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
             fcntl.flock(f, fcntl.LOCK_UN)
         print('✓ 微信真实会话锁已安全释放 (Lock is FREE)')
     except BlockingIOError:
         print('✗ 严重警告：微信真实会话锁仍被占用！')
         exit(1)
     "
     ```
   - **第六小步（在途中断任务安全收敛）**：
     对被强行终止且状态停留在 `IN_PROGRESS` 的在途 Attempt，运行收敛脚本将其置为 `UNCERTAIN`，保留现场日志与取证路径，严禁直接丢弃或自动重置为待发布；
   - **第七小步（全局零消费物理核验门禁）**：
     再次执行：
     ```bash
     ps aux | grep -E "pipeline_manager|wechat_uploader|wechat_commenter|bot_daemon|web.app|chromium.*wechat" | grep -v grep
     ```
     **物理核验输出必须完全为空**，且确认 `./vpanel ui status` 和 `./vpanel bot status` 均处于停止状态。
   > [!CAUTION]
   > **在上述“宿主 crontab 已静音、启动源已封闭、进程树已整树终结、真实会话锁已释放、在途任务已置 UNCERTAIN、全局零活跃消费”的物理核验证实完成之前，绝对禁止执行任何 `git revert` 操作！crontab 静音、冻结锁与暂停配置必须持续覆盖整个回滚与沙箱测试验证窗口！**

2. **第二步：绑定具体目标提交原子回滚 (Targeted Atomic Revert)**：
   确定引发异常的精确 Commit SHA，执行非编辑回滚：
   `git revert <TARGET_SHA> --no-edit`

3. **第三步：沙箱隔离验证安全门禁（必须执行 POLARIS-101 新增防线测试）**：
   > [!WARNING]
   > **严禁运行旧的 `test_characterization_baseline.py` 作为回滚验证**！该测试第 287 行明确记录了底层缺乏防线时状态重置成功的已知不安全基线，且完全不包含 DISCOVERY 过滤测试。若运行它，即使关键安全防线被撤掉，测试依然会全绿通过，造成严重虚假安全感！
   - 回滚验证必须在隔离沙箱中运行 `POLARIS-101` 新增的独立安全防护测试套件（`tests/unit/test_polaris_containment.py`），严格核验三项安全铁律：
     1) `PipelineDB.get_high_score_pending_videos()` 对 `source='DISCOVERY'` 的硬性排除依然生效；
     2) Bot 入口对已受理（`SUBMITTED_*`）与已发布（`PUBLISHED`）视频的状态重置守卫依然有效拦截；
     3) 正常 AUTO 任务依然能正常流转。
   - **门禁铁律**：如果防线测试失败（证明回滚操作把安全防线撤掉了），**系统必须保持 crontab 静音、`output/pipeline_freeze.lock` 存在与 `WECHAT_PUBLISHING_PAUSED=true` 暂停状态，严禁解除暂停，严禁恢复调度！** 必须先在暂停状态下由工程师介入排查，修复代码后方可恢复。

4. **第四步：推送与常驻服务热重启 (Push & Process Restart)**：
   ```bash
   git push origin main
   ./vpanel ui restart && ./vpanel bot restart
   ```
   检查进程状态：`./vpanel ui status && ./vpanel bot status`，确认进程采用最新回滚代码。

5. **第五步：解除暂停与恢复观测 (Unpause & Active Observation)**：
   在确认错误消除且防线完好后，恢复 crontab 调度并移除冻结锁：
   ```bash
   # 1. 恢复宿主 crontab 调度（移除 # QUIESCE_DISABLED 前缀）
   crontab -l | sed -E 's/^# QUIESCE_DISABLED (.*)$/\1/' | crontab -

   # 2. 物理核验调度已恢复生效
   crontab -l | grep -v '^[[:space:]]*#' | grep 'Video-precessing'

   # 3. 移除本地调度冻结锁
   rm -f output/pipeline_freeze.lock
   ```
   在 `.env` 中恢复 `WECHAT_PUBLISHING_PAUSED=false` 并重启服务：
   ```bash
   ./vpanel ui restart && ./vpanel bot restart
   ```
   持续观测 15 分钟日志。

---

### 6.2 SQLite 账本状态分叉纠偏专用剧本 (Ledger Divergence Repair Runbook)

> [!WARNING]
> **真实源码实现局限性与覆盖风险审查**：
> 1. `PipelineDB.repair_wechat_submission_status_divergence()`（位于 `src/video_processing/db/database.py:3505`）**物理上只查询 `wechat_publications` 事实表，不读取 `wechat_submission_attempts` 尝试表**。
> 2. **严重覆盖风险**：该方法内联 SQL 为 `WHERE id IN (SELECT video_id FROM wechat_publications WHERE state IN (...)) AND status NOT IN ('SUBMITTED_UNBOUND', 'SUBMITTED_BOUND', 'UNDER_REVIEW', 'UNCERTAIN')`。该条件**未显式排除 `processed_videos.status = 'PUBLISHED'`**！若某视频在主表中已确认发布（`PUBLISHED`），但 `wechat_publications` 历史状态仍停留在 `UNDER_REVIEW`，全库无差别调用该方法将**错误地把真正的 `PUBLISHED` 覆盖为 `UNDER_REVIEW`**！
> 3. **严禁全库盲跑与生产裸写 SQL**：绝对禁止在生产环境中直接执行全局 `repair_wechat_submission_status_divergence()`，且严禁直接调用 `sqlite3.connect` 裸写生产 SQL（遵守项目宪法 Rule 2“DAL 严格封装”铁律）。

必须严格遵循以下**一致性备份 → 受测 DAL 只读差异预览 → 受测 DAL 定点显式纠偏**四步操作规程：

#### 步骤一：SQLite WAL 模式一致性在线备份与完整性验证 (Consistent Online Backup & Integrity Verification)
> [!IMPORTANT]
> 1. **WAL 模式写入特性与 mtime 覆盖风险**：项目启用了 WAL 模式（`PRAGMA journal_mode=WAL;`），写事务直接追加到 `pipeline.db-wal`，主库文件 `pipeline.db` 的 mtime 不会随普通事务发生变化。若使用 `os.path.getmtime()` 命名备份，多次备份文件名完全相同，将导致已有备份被静默覆写！
> 2. **一致性保证**：单纯使用 shell `cp` 无法保证获取完整一致的 WAL 检查点。必须使用 SQLite 官方提供的在线备份 API (`sqlite3.Connection.backup()`)，由底层 C 引擎获取一致性读锁、同步 WAL 检查点并原子输出独立快照文件，且备份文件采用高精度微秒 UTC 时间戳与 UUID 随机熵命名，拒绝覆盖，并通过 `PRAGMA integrity_check;` 严格核验后将元数据登记为有效恢复点：
```bash
PYTHONPATH=src .venv/bin/python -c "
import sqlite3, os, uuid, json, hashlib
from datetime import datetime, timezone

os.makedirs('output/backups', exist_ok=True)
ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
entropy = uuid.uuid4().hex[:8]
bak_path = f'output/backups/pipeline_recovery_{ts}_{entropy}.sqlite3'

if os.path.exists(bak_path):
    raise FileExistsError(f'备份文件冲突，拒绝覆盖: {bak_path}')

# SQLite 官方在线备份 API 同步 WAL 检查点
src = sqlite3.connect('output/pipeline.db')
dst = sqlite3.connect(bak_path)
src.backup(dst)
dst.close()
src.close()

# 物理完整性验证
v_conn = sqlite3.connect(bak_path)
res = v_conn.execute('PRAGMA integrity_check;').fetchone()[0]
v_conn.close()
assert res == 'ok', f'备份完整性校验失败: {res}'

# 计算校验和并写入恢复点元数据
with open(bak_path, 'rb') as f:
    sha256 = hashlib.sha256(f.read()).hexdigest()

meta = {
    'recovery_file': bak_path,
    'sha256': sha256,
    'created_at_utc': ts,
    'integrity': 'ok'
}
meta_path = 'output/backups/latest_recovery_point.json'
with open(meta_path, 'w') as f:
    json.dump(meta, f, indent=2)

print(f'一致性备份成功且验证通过: {bak_path}')
print(f'恢复点元数据已落盘: {meta_path} (SHA256: {sha256[:16]}...)')
"
```

#### 步骤二：受测 DAL 接口只读差异预览 (DAL-Encapsulated Read-Only Preview)
在实施任何修改前，必须调用由 DAL 严格封装并经沙箱隔离测试验证的预览接口（以只读连接执行，显式排除 `PUBLISHED`）：
```bash
PYTHONPATH=src .venv/bin/python -c "
from video_processing.db.database import PipelineDB
db = PipelineDB()
records = db.preview_wechat_submission_divergence()
print(f'=== 待纠偏分叉记录 (共 {len(records)} 条，已安全排除 PUBLISHED) ===')
for r in records:
    print(r)
"
```

#### 步骤三：受测 DAL 接口定点范围纠偏 (DAL-Encapsulated Targeted Scoped Repair)
仅在人工确认差异预览无误后，针对指定的 `video_id` 集合调用 DAL 定点纠偏接口（必须传入显式非空 ID 列表，方法内部在单事务内校验状态、排除 `PUBLISHED` 并返回逐条审计结果）：
```bash
PYTHONPATH=src .venv/bin/python -c "
from video_processing.db.database import PipelineDB
db = PipelineDB()
target_ids = [12, 45]  # 替换为步骤二核验后确认需要纠偏的具体 video_id 整数列表
if not target_ids:
    print('未指定具体 video_id，终止执行')
    exit(0)
result = db.repair_wechat_submission_divergence_for_ids(target_ids)
print(f'成功安全纠偏分叉记录: {result}')
"
```

#### 步骤四：纠偏后物理证据复核
- 核对更新后的 `processed_videos.status` 是否与 `wechat_publications.state` 一致。
- 确认无任何 `PUBLISHED` 记录被篡改。
- 若无物理 Publication 账本但微信后台已存在内容，严禁脚本猜测，必须按照 `INV-001` / `INV-008` 线下人工补齐对账。

---

## 7. 架构治理铁律与不可逾越红线 (Engineering Invariants)

1. **单主干纪律**：一个工作区、一条主干 `main`、一个线上。严禁长期并行分支；所有工作在 `main` 验证收敛或使用短命隔离 worktree。
2. **严禁裸跑 Pytest**：测试必须通过 `scripts/run_isolated_tests.py` 在隔离沙箱中运行，防止本地生产数据库被清空或写入脏数据。
3. **严禁外部发布真实双跑**：任何带有 `EXTERNAL_SIDE_EFFECT` 的外部平台发布绝对禁止在影子模式下发起网络提交，必须保持 Dry-Run。
4. **禁止跨事务拆分**：严禁破坏 `record_wechat_submission_acceptance` 内部的 3 表同连接强原子事务。
5. **区分汇报状态**：严格区分“文件已改、测试通过、Git 已提交、已推送、线上采用”；任何层级未经实测确认前，一律标为 `UNKNOWN / NOT PERFORMED`。
6. **基线漂移归属与三层状态严格分离纪律**：
   - **基线 Commit 锚定**：当前 Git HEAD 物理锚定在 `e897eb2c2bf514b0f4505de8d51e88a137379100`。
   - **业务基线漂移说明**：前序提交 `9b0eb71` 打通了 English World 视频号账本发布并按原生 ID 索引定位发评，涉及 5 个生产文件及 1 个测试文件变动（+397/-78 行），属于正交业务功能落地。在 `VP-POLARIS` 架构治理期间，生产代码（`src/`、`scripts/`）严格保持 100% 只读冻结（零修改）。
   - **三层状态报告规程**：任何交接与审计报告必须严格物理切分：
     - **【协议已落盘】**：治理文档、工单架构、蓝图设计、回滚与备份剧本已在 Git 中物理落盘生效；
     - **【实现待完成】**：生产代码目前保持 0 修改，等待口令放行后在 `POLARIS-101` ~ `105` 中逐个工单实施；
     - **【测试已验证】**：在当前 `e897eb2` 快照下通过 `scripts/run_isolated_tests.py` 验证基线测试 100% 绿灯。

