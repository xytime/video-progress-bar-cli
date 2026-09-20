---
title: VP-POLARIS「北辰」架构重构红蓝对抗博弈推演与设计加固报告
project: Video-precessing (YouTube → 微信视频号/多平台流水线)
date: 2026-09-20
author: Gemini_3.8_Flash_planning
companion: shadow_development_blueprint.md, VP-POLARIS-WORK-ORDER.md
status: 评审与基准终审签署稿 (FINAL ARCHITECT REVIEW - REVISED V2.1)
version: 2.1.0
---

# VP-POLARIS「北辰」架构重构红蓝对抗博弈推演与设计加固报告

## 规则说明与设计推演定位

本文档为**纯设计推演与理论红蓝博弈（Design Simulation & Adversarial Red-Blue Game）**，旨在对 `VP-POLARIS`「北辰」重构工程方案、近一周（2026-09-12 ~ 2026-09-20）代码库 25 次演进事实，以及即将实施的 `POLARIS-000` ~ `POLARIS-105` 计划，进行**极端对抗式压力测试与推演论证**，在不修改任何生产代码的前提下提前暴露死锁、竞态、状态分叉与契约漂移风险。

博弈采用四角色对抗轮转机制：
- ⚪ **白·命题/质询**（中立架构裁判）：提出系统关键脆弱点，框定技术争点，追问底层物理事实。
- 🔵 **蓝·防守**（方案辩护方）：以**最强理由（Steelman）** 为当前计划与现有设计进行防御与合理性论证。
- 🔴 **红·进攻**（对抗红队）：抛弃理论幻想，给出**具体可复现的致命漏洞、并发竞态、死锁路径与最坏破坏场景**。
- ⚖️ **白·裁决**：判定攻防胜负，确立定级（🔴 P0 立即 / 🟠 P1 一月 / 🟡 P2 季度 / 🟢 维持原案），并输出**直接指导修改实施的硬化加固指令**。

---

## 战役一：Telegram Bot 旁路收口 vs 用户交互假死与鬼魂状态 (Ghost State)

### ⚪ 白·命题
`POLARIS-102` 计划关闭 Telegram Bot（`pipeline_agent.py`）直调 `scripts/wechat_uploader.py` 与无约束 `update_video_status` 的特权，转为调用标准应用服务，并在上传器返回退出码 `6` 时对齐状态。
**争点**：如果 Bot 改为异步提交，如何避免 LLM Agent 误判完成？如果 Bot 自行标记 `SUBMITTED_UNBOUND`，是否会造成没有 Publication 账本的“鬼魂状态”？

### 🔵 蓝·防守
1. **统一门禁是第一原则**：Web 控制台有完善的 `_wechat_submission_guard_reason`，Bot 随意暴露直调接口本身就是严重的安全越权。
2. **退出码 6 的含义非常明确**：`EXIT_SUBMITTED_FOR_REVIEW = 6` 在 `wechat_uploader.py:L120` 明确声明为“已受理待审核”。Bot 只要在捕获到退出码 6 时，将状态更新为 `SUBMITTED_UNBOUND` 而非 `FAILED`，就不会引发管理员后续误点 `/retry`。
3. **LLM 只要按工具返回值播报即可**：工具返回什么，大模型就向用户解释什么，架构上无需过度复杂化。

### ⚪ 白·质询
- **追问蓝队**：在 `PipelineManager` 中，处理退出码 6 依赖 `_mark_wechat_submission_under_review`，该方法连续写入了 `wechat_publications` 账本、`wechat_submission_attempts` 尝试记录，最后才改主表状态。**如果 Bot 只是在 `pipeline_agent.py` 里调用 `self.db.update_video_status(yid, 'SUBMITTED_UNBOUND')`，那么底层账本是不是空的？**
- **追问蓝队**：现存 Bot 调用 `upload_to_wechat` 是同步等待的。如果改为调用 Web 的异步处理接口，接口瞬间返回 `{"success": True}`，**Agent 是否会给用户发送“已成功发布”，造成事实欺骗？**

### 🔴 红·进攻
1. **致命推演：无账本的“鬼魂状态”引发排重穿透与对账失明**：
   - 红队审计发现，若 Bot 仅更新状态而不写账本，主表调度状态变成了 `SUBMITTED_UNBOUND`，但事实发布账本（`wechat_publications`）中没有任何记录。
   - **真实物理危害**：
     a) **排重防线全面穿透**：核心排重方法（如 `has_active_wechat_submission`、`get_wechat_publication_by_video_id`）完全基于 `wechat_publications` 账本查询。无账本意味着该记录在防重校验中成为“透明人”，后续若被二次触发，系统将因查无账本而错误放行物理发帖，引发封号！
     b) **对账巡检失明**：`repair_wechat_submission_status_divergence()` 等工具严格基于“已有物理账本”去纠偏主状态。若根本没有物理账本，对账工具既无法推断外部平台是否真实受理，也不会凭空修复，导致 `SUBMITTED_UNBOUND` 成为永无事实支撑的孤儿鬼魂状态。
2. **大模型幻觉与用户假死矛盾**：
   - 现存 Bot System Prompt 规定：“When user sends /run... Update status to 'PUBLISHING', then run upload_to_wechat... If it succeeds, send a success message to Telegram.”
   - 若异步化后工具瞬间返回 `{"ok": True, "task_id": "xxx"}`，LLM 会误以为任务已经彻底完成并宣告大捷。而 3 分钟后如果切片因磁盘满崩溃，用户在群里以为视频已在发布，产生严重运维误导。
3. **文件锁争用（Lock Contention）**：
   - Bot 在 `upload_to_wechat` 内部持有 `fcntl.flock(pipeline.lock)`。如果调度器正在跑定时任务，Bot 会在 `fcntl.flock` 处无限期阻塞线程，导致 Telegram 轮询 Worker 响应超时被 Telegram 服务器判定为客户端死锁断开。

### ⚖️ 白·裁决 —— 🔴 P0｜判：红队胜，防御存在严重盲区

**裁决与加固指令**：
1. **Bot 收口唯一定位：具名任务分发客户端**：
   - 彻底剥离 Bot 直接执行业务流程或改写底层状态的权力，Bot 仅作为**具名任务分发客户端**。
   - `/run` 或单视频处理一律只暴露唯一的门面工具 `dispatch_pipeline_job(youtube_id)`：
     - **响应前强制持久化 (Pre-Dispatch Durable Record)**：收到调度请求后，先在 SQLite 原子落盘分发任务，随后才返回 `QUEUED` 异步受理语义（包含 task_id、排队时间戳及待处理提示），对活跃中任务幂等复用，严禁 LLM 擅自宣称“已发布完成”。
2. **Attempt 增量表迁移、部分唯一索引与原子领取规则**：
   - `PipelineDB._migrate_database()` 增量迁移 `wechat_submission_attempts`，扩展状态 CHECK 约束以包含 `IN_PROGRESS`、`UNCERTAIN`、`RELEASED_BUSY`；
   - 建立部分唯一活跃索引 `CREATE UNIQUE INDEX IF NOT EXISTS idx_wechat_active_attempt ON wechat_submission_attempts(subject_id) WHERE state IN ('IN_PROGRESS', 'SUBMITTED_UNBOUND');`，通过条件 CAS 插入执行原子领取，物理阻断多执行者并发领取重投；
   - 子进程退出携带明确 BUSY 凭据时，标记 `RELEASED_BUSY` 释放唯一索引以便有限退避重领；平台受理后本地写账本发生崩溃，重启强制 Fail-Closed 进入终态 `UNCERTAIN`，禁止自动重领。
3. **核心应用服务统一负责三表原子落账**：
   - 由核心应用服务/流水线执行器统一处理退出码 6，调用复合原子事务方法写入 Attempt 记录、创建/更新 Publication 账本，最后更新主表状态，杜绝任何无账本孤儿状态。
4. **清晰界定事务与发布边界**：
   - SQLite 三表原子事务保障**本地状态机强一致性**；外部平台物理发帖属于 At-Most-Once 语义，不可逆且无法由本地事务回滚，崩溃窗口依赖人工线下核销。
5. **移除 Bot 内部冗余文件锁**：
   - 统一由底层的 `PipelineManager` 与 `claim_video_for_processing` 控制并发互斥，消除 Bot 层的 `fcntl.flock` 避免阻塞 Telegram 线程。

---

## 战役二：DAL 中心候选硬排除 DISCOVERY vs 存量数据与黄金夹具雪崩

### ⚪ 白·命题
`POLARIS-103` 计划在 `get_high_score_pending_videos` 中硬编码增加 `AND IFNULL(pv.source, '') != 'DISCOVERY'`，并同步修正 `GOLDEN-WF-01` 契约。
**争点**：排除 DISCOVERY 是否会波及合法任务？是否会导致存量数据历史字段异常引发漏跑？如何保证测试修改不是在“掩耳盗铃”？

### 🔵 蓝·防守
1. **业务宪法明确**：系统设计初衷就是 `source='DISCOVERY'` 仅在仪表盘高赞发现 Tab 供人肉浏览；只有点击“加入队列（promote）”后变成 `MANUAL` 才能自动跑。
2. **漏洞确凿**：现有 SQL 漏掉了这一过滤，导致只要评分机制给 DISCOVERY 打出高分，后台 cron 就会自作主张发布，必须在 SQL 层一剑封喉。
3. **修正测试合情合理**：`GOLDEN-WF-01` 夹具以前写了 `source: DISCOVERY` 还断言能被拉取，本身就是把 bug 当 feature，改回 `source: AUTO` 是拨乱反正。

### ⚪ 白·质询
- **追问红队**：`IFNULL(pv.source, '') != 'DISCOVERY'` 是一个确定性的负向过滤，只要 source 不是 DISCOVERY 的视频（包括 NULL、AUTO、MANUAL、YOUTUBE）均不受影响，怎么会漏跑正常任务？
- **追问蓝队**：如果 `GOLDEN-WF-01` 被改成了 `source: AUTO`，**那么到底有没有测试来专门验证“DISCOVERY 确实被排除了”？** 如果没有，谁来证明这个修复生效了？

### 🔴 红·进攻
1. **测试掩耳盗铃风险（Test Neutralization）**：
   - 红队指出：如果蓝队把 `GOLDEN-WF-01` 改为 `AUTO` 并让测试通过，这只证明了“AUTO 能跑”，**完全没有形成对“DISCOVERY 不能跑”的强硬断言**！未来的开发者如果不小心删除了这一过滤条件，测试依然是绿的！
2. **存量隐式数据陷阱（Legacy Data Inconsistency）**：
   - 生产数据库 `processed_videos` 表历经多次版本升级，早期的历史条目中 `source` 字段可能存在大小写漂移（如 `discovery`）、首尾空格，或者部分切片子视频的 `source` 为 NULL。
   - 如果仅做简单的 `!= 'DISCOVERY'`，若遇到小写 `discovery`，依然会被漏过去！
3. **原子 Promotion 竞态漏洞**：
   - 用户在 Web 端点击 `/api/videos/{youtube_id}/promote` 时，执行 `promote_to_manual` 将 source 改为 `MANUAL`、score 改为 100。
   - 如果此时后台 cron 正在执行 `get_high_score_pending_videos`，如果 promotion 不是原子事务，可能造成视频处于半就绪状态被抢占。

### ⚖️ 白·裁决 —— 🔴 P0｜判：双方平手，裁决建立双向强制防护网

**裁决与加固指令**：
1. **SQL 过滤强化大小写与空字符防御**：
   - 过滤条件必须加固为：`AND UPPER(TRIM(COALESCE(pv.source, ''))) != 'DISCOVERY'`，彻底杜绝数据源大小写漂移漏洞。
2. **拒绝掩耳盗铃：建立正反双轨断言套件**：
   - 在 `POLARIS-101` 中，**新建专属安全回归测试** `test_discovery_candidate_firewall`：
     - Case A（正向）：插入 `source='AUTO', score=80`，断言必被纳入候选；
     - Case B（反向）：插入 `source='DISCOVERY', score=99`，**硬性断言绝对不得返回**；
     - Case C（提升）：调用 `promote_to_manual()` 后，**硬性断言必须被成功纳入**。
   - 修正后的 `GOLDEN-WF-01` 仅代表标准生命周期，安全防线必须由独立的 Regression 套件死死守住。

---

## 战役三：评论互动引擎（WeChat Interaction Engine）上线带来的浏览器锁与环境冲突

### ⚪ 白·命题
在 2026-09-12 规划形成后的一周内，项目上线了 `Project WeChat-Interaction-Engine`（互动评论系统，提交 `59a5cab` ~ `83acb41`），引入了 `guarded_wechat_browser_session`，并在 `PipelineManager` 中重构了 `_build_subprocess_env`。
**争点**：重构工单若继续沿用一周前的孤立假设，是否会在运行时与正在跑的评论系统发生撞车？

### 🔵 蓝·防守
1. **重构未动业务逻辑**：首批工单 `POLARIS-101` ~ `105` 只涉及 Bot 收口与 DAL SQL 过滤，根本没有修改微信上传执行层 `wechat_uploader.py`。
2. **评论系统有独立开关**：评论系统受 `enable_wechat_comment_interaction` 开关控制，发布与评论互斥有 `wechat_session_lock.py` 保护，无需在重构工单中大惊小怪。

### ⚪ 白·质询
- **追问蓝队**：事实是 `wechat_uploader.py` 的主流程在 2026-09-19 已经被修改（v5.7.0，`run_uploader` 内部包裹了 `@guarded_wechat_browser_session`）。如果 Bot 仍持有它自己的调用方式，**会话共享锁在父子进程间如何协作？是否存在锁争用或互锁？**

### 🔴 红·进攻
1. **实锤漏洞：父子进程锁争用导致立即锁忙失败（Father-Child Lock Contention & Immediate Busy Failure）**：
   - 源码事实核验：`scripts/wechat_uploader.py:L1221` 明确通过 `@guarded_wechat_browser_session` 在 `run_uploader` 入口对 `state_path` 进行互斥锁定，其锁超时机制默认 `timeout_seconds=0.0`，争用时立即返回 `busy_result=1`。
   - **锁争用陷阱**：若重构方案草率地在 Bot 父进程中也申请该会话锁再去拉起子进程，子进程启动后再次尝试获取同一 `state_path` 的锁，将因超时为 0 瞬间遭遇锁争用冲突返回 `busy_result=1`，**造成父子进程锁争用并导致子进程立即锁忙失败**（非无限等待死锁，而是立即快速失败退出）。
2. **退出码 1 语义严重混淆陷阱（Exit Code 1 Collision）**：
   - 源码物理事实：在 `scripts/wechat_uploader.py` 中，`@guarded_wechat_browser_session` 在锁争用时返回 `busy_result=1`；然而在业务逻辑中，**素材缺失（L1262 视频文件不存在、L1267 描述文案不存在、L1282 封面文件不存在）同样直接 `return 1`**！
   - **致命死循环风险**：若调度层盲目将所有退出码 1 解释为“会话锁争用”并执行退避重试，将会把永久性的素材缺失故障当成临时锁忙反复重新入队，造成任务队列死循环塞满！
   - **退出码语义对齐**：必须统一校准退出码定义——退出码 `2` 为登录凭据失效（`EXIT_LOGIN_REQUIRED`）；退出码 `3` 为**发布结果未确认**（`EXIT_RESULT_UNCERTAIN`，平台已点击提交但页面超时未确认，必须交由人工核销，绝不可自动重传）；退出码 `6` 为已受理待审核（`EXIT_SUBMITTED_FOR_REVIEW`）。
3. **子进程环境漂移隐患**：
   - 提交 `e7c9866` 与 `0a8380c` 建立了统一的 `PipelineManager._build_subprocess_env()`，规范了 PATH、动态代理与 Telegram 环境变量。
   - 但 `pipeline_agent.py` 当前执行子进程时**根本没用统一环境构建器**，依然在用系统的裸环境变量。这意味着在 cron 或后台服务触发的贫环境下，Bot 调起上传必因代理缺失而失败。

### ⚖️ 白·裁决 —— 🟠 P1｜判：红队抓出真实物理约束，澄清锁持有层次与退出码映射

**裁决与加固指令**：
1. **确立子进程内部自洽持锁铁律（严禁父进程外置重复加锁）**：
   - 会话锁必须且仅由 `scripts/wechat_uploader.py:run_uploader` 内部自洽持有。Bot 或主调度器**绝对禁止在父进程中申请该锁**，从物理机制上杜绝父子进程锁争用冲突。
2. **调度层建立独立 BUSY 凭证识别与有限退避协议（Explicit BUSY Credential & Finite Backoff）**：
   - 严禁单纯依据退出码 1 判断锁忙。必须依赖结构化凭证（例如进程输出特定 stderr 标记 `[SESSION_LOCK_BUSY]` 或分配独立退出码）；
   - **仅在存在明确 BUSY 凭证时**，调度器才执行有限指数退避（最多 3 次，间隔 30s/60s/120s）；通用退出码 1（素材/配置错误）必须判定为不可自动重试的永久失败；
   - 捕获退出码 3 时，强制置为 `UNCERTAIN`，严格按照 At-Most-Once 语义等待人工核验，禁止自动重试。
3. **环境统一规范**：
   - 在 `POLARIS-102` 中，Bot 统一作为具名任务分发客户端将任务转交核心服务；任务拉起子进程时必须由 `_build_subprocess_env()` 统一生成环境。

---

## 战役四：PipelineDB 的“内部委托”是否是掩耳盗铃与伪重构？

### ⚪ 白·命题
后续 `WO-DB-001`（Gate M8）主张“保持 `PipelineDB` 外部门面与 245 个方法签名不变，仅在内部拆分子模块委托”。
**争点**：这是真正有价值的解耦，还是把屎山包上一层金箔？如果在委托子模块间传递数据库连接，是否会引入更隐蔽的死锁？

### 🔵 蓝·防守
1. **这是唯一安全的工业级方案（Branch by Abstraction）**：外部有 464 个文件在调用 `PipelineDB`，任何对外签名的修改都会引发整个仓库的连环爆炸。
2. **领域清晰度大幅提升**：把 10.6k 行代码中的抖音账本（1.2k 行）、快手账本（300 行）、English World（2k 行）抽离到独立的子模块中，`PipelineDB` 单体体积直接缩减 50% 以上，日常 PR 冲突概率直线下降。
3. **保留了同连接事务**：不搞伪分布式微服务，保证了 SQLite 事务的原子性。

### ⚪ 白·质询
- **追问红队**：如果不走门面委托，难道你赞成直接推倒重写 10.6k 行代码、让 464 个文件改 import 吗？那样的故障率是多少？

### 🔴 红·进攻
1. **连接上下文泄漏与长事务死锁（Connection Leak & Deadlock）**：
   - 红队指出：子模块拆分最容易犯的错误就是**隐式新建连接**。
   - 如果主模块持有 `with self.get_connection() as conn:` 事务，随后调用 `self._douyin_ledger.record_pub(...)`，若子模块内部不小心写了 `with self.get_connection() as conn2:`，在 SQLite WAL 模式下，**同一线程/进程对同一文件申请两个写入连接，瞬间触发 `database is locked` 永久死锁**！
2. **代码可维护性幻觉**：
   - 如果子模块必须时刻把 `conn` 作为参数在所有函数间传导，代码会变得极其难看，充斥着大量的透传参数（Tramp Data）。

### ⚖️ 白·裁决 —— 🟠 P1｜判：蓝队战略正确，但红队点出了致命物理陷阱

**裁决与加固指令**：
1. **确立内部委托的铁律规范——严格的连接上下文透传（Connection Injection Protocol）**：
   - 制定《子模块 DAL 编写规范》：所有内部领域子模块（如 `DouyinLedgerModule`、`EnglishWorldModule`）的方法，**首个必选参数必须是 `conn: sqlite3.Connection`**。
   - 子模块内部**绝对禁止**持有独立的数据源或调用 `get_connection()`，必须由外层 `PipelineDB` 门面统一管理事务生命周期，根绝内部双连接死锁。
2. **增加静态 AST 规则守护**：
   - 编写专门的单元测试，通过 `ast` 模块扫描子模块代码，如果发现子模块内部调用了 `connect()` 或 `get_connection()`，测试直接报错，将死锁风险拦截在编译/测试阶段。

---

## 战役五：影子双跑比对（Shadow Mode）的性能负载与生产侵入性

### ⚪ 白·命题
`WO-SHADOW-001` 与 `WO-SHADOW-002`（Gate M7）主张在生产环境中对只读查询与决策引擎进行并行双跑比对。
**争点**：影子模式是否真如声称的那样“对生产零风险、零影响”？在资源受限的 Mac Mini 宿主机上，双跑是否会吃垮硬件？

### 🔵 蓝·防守
1. **严格限定在 PURE_READ 和 DECISION**：
   - 绝不在写操作或外部发布执行双跑。
   - 只对分页查询、敏感词过滤等内存计算做比对，内存与 CPU 增量可忽略不计。
2. **异常完全隔离**：
   - 影子执行被独立的 `try...except` 保护，影子报错绝不影响主流程返回。

### ⚪ 白·质询
- **追问红队**：纯只读的影子比对，在什么情况下会破坏生产稳定性？

### 🔴 红·进攻
1. **实锤隐患：美股盘中敏感期（Market Guard Window）资源侵犯**：
   - 本机不仅运行视频流水线，还承担实盘量化交易（OptionSense，见过去一周提交 `bccb944` 与 `7ff9ef7`）。
   - 盘中交易对 CPU 延迟要求极高。如果视频号的只读查询（包含动态 JOIN、聚合统计）在每次 Web 请求时都双跑一次，会导致 SQLite 产生额外的读锁与 CPU 缓存争用，违反系统现有的盘中避让原则。
2. **比对日志刷屏引发磁盘 I/O 阻塞**：
   - 如果新旧实现的语义在分页排序边缘存在微小的浮点数或时间戳不一致，影子比较器会疯狂向磁盘输出 `[SHADOW_MISMATCH]` 日志，导致 `output/pipeline.log` 迅速膨胀，耗尽磁盘甚至阻塞正常的轮询日志。

### ⚖️ 白·裁决 —— 🟡 P2｜判：红队提醒关键业务背景，增加两道保险阀

**裁决与加固指令**：
1. **盘中窗口强制静默（Market Guard Short-Circuit）**：
   - 影子比对器必须接入 `settings.is_us_market_guard_window()`。在美股盘中交易时段，影子比对**自动短路、绝对不执行**，优先保障实盘交易算力。
2. **采样率控制与错误限频（Rate-Limiting & Sampling）**：
   - 影子比对增加采样率配置（默认 10% 流量），并对比对日志实施滑动窗口限流（同一类 Mismatch 每小时最多打印 3 次），杜绝日志雪崩。

---

## 战役六：第三轮架构终审 4 项技术盲区深度渗透与终极硬化 (Round 6: Deep Penetration on Final Review Vulnerabilities)

### ⚪ 白·命题
架构师与评审员在第三轮终审中指出：虽然已建立了 BUSY 判别、退出码 3 与回滚防线测试，但仍存在 4 项物理技术缺口：
1. 崩溃恢复置为 `UNCERTAIN` 后，原有 CAS SQL 阻断失效，新任务依然能领取重发；
2. 存量生产库若已有重复的 `SUBMITTED_UNBOUND` 记录，直接建唯一索引将抛出 `IntegrityError` 崩溃；
3. 全局停写若只关控制台，独立管线、cron 与 `os.setsid` 启动的互动 Worker 仍会并发执行；
4. WAL 模式下主库 mtime 不变，导致在线备份静默覆写已有恢复点。

---

### 🔴 红·进攻（极限渗透）
1. **UNCERTAIN 穿透重复发帖**：当子进程因断网或崩溃导致 Attempt 停留在悬空状态，崩溃恢复将其置为 `state = 'UNCERTAIN'`。由于原 CAS 语句中 `NOT EXISTS` 仅过滤 `('IN_PROGRESS', 'SUBMITTED_UNBOUND')`，原部分唯一索引也只覆盖这两态。红队立即发起重新调度，`NOT EXISTS` 返回 True，新的 `IN_PROGRESS` Attempt 成功插入并拉起 Uploader 再次发帖，直接封号！
2. **存量数据致死异常**：生产库 `database.py:3424` 允许不同 `evidence_path` 写入多条 `SUBMITTED_UNBOUND`。若存量库已存在历史重复数据，`CREATE UNIQUE INDEX` 直接抛出 `UNIQUE constraint failed`，导致生产部署或表迁移在启动时直接炸库！
3. **假停写与 cron 幽灵复活**：运维在回滚时仅执行 `./vpanel ui stop` 并更新 `.env`。但系统 cron 依然每 30 分钟拉起 `monitor_channels.py`、每天定时拉起 `pipeline_manager.py`，且已启动的后台互动 Worker (`start_new_session=True`) 拥有独立进程组。在运维执行 `git revert` 的瞬间，cron 再次拉起流水线，带着旧代码或未决环境直接向平台发帖！
4. **备份覆写摧毁恢复点**：WAL 模式下写事务全在 `pipeline.db-wal`，主库文件 `pipeline.db` 的 mtime 不变。运维在纠偏前两次执行备份，由于文件名基于秒级 mtime，第二次备份直接无情覆写第一次备份。若第二次备份是在数据已被污染时触发，唯一的冷恢复点被永久销毁！

---

### 🔵 蓝·防守（硬化防御）
1. **多表联合 CAS 阻断**：CAS 领取 SQL 不仅排查 Attempt 表（排除 `IN_PROGRESS`, `SUBMITTED_UNBOUND`, `PLATFORM_ID_BOUND`, `UNCERTAIN`），更排查 Publication 事实表与主表状态；若被 `UNCERTAIN` 拦截，直接硬性抛出 `SubmissionClaimRejectedUncertain` 拒绝并报警，禁止自动重领。
2. **迁移双轨兼容与历史归档**：架构推荐**方案 A（独立原子活跃租约表）**，通过 `subject_id PRIMARY KEY` 物理保证单活跃，历史 Attempt 纯追加不加唯一约束；备选**方案 B（单事务冲突预检与旧记录归档）**：预检重复记录，保留最新 1 条为活跃，将其余旧记录安全置为 `'SUBMITTED_UNBOUND_ARCHIVED'`，保留全部证据与时间戳，再建唯一索引。
3. **七步受控停写与零消费物理核验**：创建全局物理调度冻结锁 `output/pipeline_freeze.lock`，所有管线入口前置硬短路退出；按 PGID 整树清理进程组；清理残留 Chromium 孤儿；非阻塞 flock 探测 `wechat_session.lock` 确保会话锁释放；在途任务收敛为 `UNCERTAIN`；确认进程输出为空后方可 revert。
4. **高精度微秒时间戳 + UUID 随机熵 + 覆写拒绝**：备份文件命名为 `pipeline_recovery_{ts_microsecond}_{uuid_entropy}.sqlite3`；目标文件已存在抛出 `FileExistsError`；独立连接运行 `PRAGMA integrity_check;` 断言为 `ok`；计算 SHA256 登记至元数据。

---

### ⚖️ 白·裁决（审议签署闭环）
- **定级**：🔴 **P1 立即硬化闭环**。4 项漏洞均具备物理可触发性，蓝队防御方案逻辑完备、工程扎实。
- **加固指令**：全部 4 项防御方案必须 100% 同步落盘至 `shadow_development_blueprint.md`、`VP-POLARIS-WORK-ORDER.md` 与 `qa_and_architecture_review.md`，并在当前基线 commit `e897eb2` 下生成机器收据。

---

## 战役七：第四轮架构终审 3 项 P1 缺口深度渗透与终极硬化 (Round 7: Deep Penetration on Fourth Review Vulnerabilities)

### ⚪ 白·命题
架构师与 Codex 在第四轮终审中指出：方案在细节闭环上仍有 3 项 P1 级缺陷尚未闭合：
1. 会话锁核验探测了错误的文件名（探测 `output/wechat_session.lock`），未调用真实规范派生逻辑，真实锁被占用时仍会输出 FREE 假象；且缺少持锁反例测试；
2. 租约方案 B 试图在迁移事务中先更新状态为 `SUBMITTED_UNBOUND_ARCHIVED`，触发旧 CHECK 约束报错；且相同 `created_at` 无法去重导致后续唯一索引创建失败；
3. 全局停写依赖应用层 `output/pipeline_freeze.lock`，一旦执行 `git revert`，代码回滚会撤销该检查，导致宿主机器每分钟执行一次的 crontab 立即拉起发帖！

---

### 🔴 红·进攻（极限渗透）
1. **虚假锁探测与并发冲突渗透**：`wechat_uploader.py` 内部实际持有的锁是 `output/.wechat_state.json.browser.lock`。红队启动一个后台进程持有该锁执行发帖，运维剧本却探测 `output/wechat_session.lock`。因该文件未被占用，脚本误报 `FREE`，运维误以为无任务并发执行而强行拉起新发布，导致两个 Chromium 共享同一用户目录并发写入，登录态直接被腾讯封禁！
2. **方案 B 迁移死锁与崩溃渗透**：红队在历史数据库中构造了 3 条相同 `created_at` 的 `SUBMITTED_UNBOUND` 记录。方案 B 在执行迁移时，首先尝试执行 `UPDATE ... SET state = 'SUBMITTED_UNBOUND_ARCHIVED'`，原表已有 CHECK 约束立即报错抛出 `sqlite3.IntegrityError: CHECK constraint failed`；即便绕过 CHECK，按 `a.created_at < b.created_at` 过滤保留的仍有多条相同时间戳记录，后续 `CREATE UNIQUE INDEX` 必然抛出 `UNIQUE constraint failed` 炸库崩溃！
3. **Revert 撤销业务锁与 Cron 幽灵秒级复活**：运维在异常回滚时创建了 `output/pipeline_freeze.lock`。随后运维执行 `git revert`，应用代码被回滚到重构前。重构前的旧代码根本没有检查 `output/pipeline_freeze.lock` 的逻辑！宿主机器 crontab 每 1 分钟拉起一次 `run_publication_window.py`，代码刚 revert 完成不到 30 秒，cron 带着旧代码和未决环境直接在后台拉起，向平台重复发帖！

---

### 🔵 蓝·防守（硬化防御）
1. **规范化派生路径与持锁反例测试**：
   - 剧本统一调用 `canonical_wechat_session_lock_path("output/wechat_state.json")` 解析真实锁文件 `output/.wechat_state.json.browser.lock`；
   - 在 `POLARIS-101` 中增设单测 `test_wechat_session_lock_probe_detects_real_hold_and_release`，后台线程持锁时断言探测逻辑捕获 `BlockingIOError` 并判定为失败（非零退出码反例），释放后断言探测成功（返回 0）。
2. **确立方案 A 完整契约，废除方案 B**：
   - 技术裁决彻底废除方案 B；
   - 方案 A 平滑扩展 Attempt 表 CHECK 约束为 `CHECK(state IN ('IN_PROGRESS', 'SUBMITTED_UNBOUND', 'PLATFORM_ID_BOUND', 'UNCERTAIN', 'RELEASED_BUSY'))`，新表不建任何唯一索引，纯追加历史审计，存量数据零冲突；
   - 创建独立表 `wechat_submission_active_claims`（`subject_id TEXT PRIMARY KEY`）；
   - 单事务内 CAS 领取活跃租约并插入 Attempt 记录；按 `active_attempt_id` 条件精确释放（BUSY 释放重领，退出码 6 原子四表落账持续占位，崩溃恢复 Fail-Closed 转入 UNCERTAIN 物理锁定）。
3. **升级为宿主级 crontab 物理静音**：
   - 彻底摆脱对应用层可被 revert 代码的依赖，上升到 OS 宿主级停写；
   - 导出 crontab 备份，执行 `sed -E '/Video-precessing/s/^([^#])/# QUIESCE_DISABLED \1/'` 物理静音所有任务；
   - 检查 `crontab -l | grep -v '^[[:space:]]*#' | grep 'Video-precessing'` 确认活跃调度为空；
   - 静音覆盖整个回滚与沙箱测试验证窗口，验证通过后方可反向恢复。

---

### ⚖️ 白·裁决（审议签署闭环）
- **定级**：🔴 **P1 立即硬化闭环**。红队指出的 3 项漏洞直击方案物理盲区，蓝队加固策略从根本上杜绝了隐患。
- **加固指令**：全部加固项 100% 同步更新至 `shadow_development_blueprint.md`、`VP-POLARIS-WORK-ORDER.md`、`work_orders.md` 与 `qa_and_architecture_review.md`。

---

## 战役总结：博弈对重构计划的加固修订决议（Revisions Mandate）

经过本次深度红蓝对抗，**完全确立了首批安全收口（Hybrid Plan B）的必要性与紧迫性**，同时将原本粗粒度的工单计划全面加固，形成以下**必须落盘的修正案**：

```text
┌───────────────────────────────────────────────────────────────────────────────┐
│                       红蓝博弈最终加固决议 (Adversarial Hardening Mandates)   │
├───────────────────────────────────────────────────────────────────────────────┤
│ 1. [Bot 闭环、方案 A 租约、UNCERTAIN 联合阻断与历史数据兼容迁移]              │
│    - Bot 严格定位为具名任务分发客户端，响应前持久化分发记录，统一返回 QUEUED； │
│    - 全面确立方案 A 独立原子租约表完整契约，彻底废除方案 B；                  │
│    - Attempt 表平滑扩展 CHECK 约束（纯追加历史，零迁移冲突）；                 │
│    - 创建独立表 wechat_submission_active_claims (subject_id PRIMARY KEY)；    │
│    - 单事务 CAS 领取活跃租约并落 Attempt；按 active_attempt_id 条件精确释放； │
│    - 锁由子进程内部自洽持锁，依赖明确 BUSY 凭证有限退避，退出码 3 明确为 UNCERTAIN；│
│    - 应用服务负责四表原子落账；确立本地强事务与外部 At-Most-Once 边界。       │
├───────────────────────────────────────────────────────────────────────────────┤
│ 2. [会话锁真实路径探测与持锁反例测试]                                         │
│    - 必须调用 canonical_wechat_session_lock_path 解析出真实浏览器锁文件        │
│      output/.wechat_state.json.browser.lock，严禁探测错误锁路径；              │
│    - POLARIS-101 必须包含真实持锁时的失败反例断言（非零返回码）。             │
├───────────────────────────────────────────────────────────────────────────────┤
│ 3. [DAL 候选与测试双轨]                                                       │
│    - SQL 过滤加固大小写与空字符防御：UPPER(TRIM(COALESCE(...))) != 'DISCOVERY'；│
│    - 确立双轨测试：漏洞复现用例先红后绿，现有正常基线用例全程保绿。          │
├───────────────────────────────────────────────────────────────────────────────┤
│ 4. [门面事务与动态棘轮]                                                       │
│    - 门面统一管理事务连接；内部领域子模块必须接收 conn 上下文，禁止自建连接； │
│    - 单体治理实行动态递减棘轮门禁（只许减不许增），辅以 AST 与回滚测试验证。  │
├───────────────────────────────────────────────────────────────────────────────┤
│ 5. [影子比对前置条件与资源上限]                                               │
│    - 显式执行 conn.execute("BEGIN DEFERRED") 开启读事务快照，严禁 with conn: 假事务；│
│    - 验收并发写不可见；Gate M7 前绑定确定性唯一排序与虚拟固定时钟；          │
│    - 实施有界队列（上限100）、并发限制（2线程）、200ms 超时底层中断与连接释放；│
│    - 接入美股盘中交易避让（Market Guard），交易时段硬短路。                   │
├───────────────────────────────────────────────────────────────────────────────┤
│ 6. [宿主级停写、零消费物理核验与 WAL 备份防覆写]                              │
│    - 回滚必须前置在宿主 crontab 中使用 # QUIESCE_DISABLED 物理静音调度任务；  │
│    - 按 PGID 整树清理进程组并 kill 残留 Chromium 孤儿，非阻塞 flock 核验真实会话锁；│
│    - 在途任务置 UNCERTAIN，物理证实 zero consumers 后方可执行原子 git revert； │
│    - 回滚后沙箱必须运行 POLARIS-101 新增防线测试（防线测试失败保持暂停禁恢复）；│
│    - crontab 静音覆盖整个回滚与沙箱测试窗口，稳定后方可反向恢复；              │
│    - SQLite 在线备份采用高精度微秒 UTC 时间戳 + UUID 随机熵，拒绝覆写抛异常； │
│    - 独立连接校验 PRAGMA integrity_check; 为 ok，登记恢复点元数据；            │
│    - 账本纠偏严禁裸写 SQL 与全库盲跑：统一通过排除 PUBLISHED 的受测 DAL 接口。 │
└───────────────────────────────────────────────────────────────────────────────┘
```

