# 视频号二级回复（Author Secondary Reply）代码审查、局部重构与自动化进程技术 Handoff

- **文档版本**: `v2.0 (Post-M3 Canary + Architect Review Refactoring Integrated)`
- **编制日期**: `2026-10-17 (Asia/Shanghai)`
- **基线提交**: `main @ 7bb24a6`（生产只读参考基线；历史 Canary 实测 `task_id=1` 原生回复 ID `15034300564280904584` 已归档锁定）
- **候选工作区**: `/Users/ryusei/.codex/worktrees/c446/Video-precessing`（分支 `task/secondary-reply-m0-m2`）
- **适用对象**: 架构师候选审核、以及后续负责 M3.5（半自动巡航闭环）与 M4（分级受控自动巡航）开发与验收的工程师 / Codex / AGY 智能体

---

## 1. 当前基线与 M3 真实 Canary 验收状态

### 1.1 已落地的工程模块清单
1. **核心模块**:
   - 类型合同、双语规范化校验、出站守卫与只读验证强类型契约: [secondary_reply_contract.py](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/interaction/secondary_reply_contract.py)
   - 生成门面与双通道内容安全审查: [secondary_reply_service.py](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/interaction/secondary_reply_service.py)
   - 审批签名、白名单门禁、HTML 转义与 64B 回调防护: [secondary_reply_approval.py](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/interaction/secondary_reply_approval.py)
   - 统一状态机编排（采集/草稿/审批/认领/终审/意图/守卫/回读/对账）: [secondary_reply_orchestrator.py](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/interaction/secondary_reply_orchestrator.py)
   - 浏览器适配器（校准与发送统一控件定位）: [secondary_reply_browser_adapter.py](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/interaction/secondary_reply_browser_adapter.py)
   - 浏览器平台端口实现: [secondary_reply_browser_platform.py](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/interaction/secondary_reply_browser_platform.py)
   - 单条运维、审批派发/回调消费与强类型只读验证: [secondary_reply_ops.py](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/interaction/secondary_reply_ops.py)
   - 命令行统一入口: [wechat_secondary_reply.py](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/scripts/wechat_secondary_reply.py)
   - 数据库表与事务方法: [database.py](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/db/database.py#L2218-L2336) & [#L12913-L13870](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/db/database.py#L12913-L13870)
   - 配置开关: [settings.py](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/config/settings.py)（`enable_wechat_secondary_reply` 与 `enable_wechat_secondary_reply_live_submission` 默认 `False`）

2. **M3 真实平台单条 Canary 历史记录（严禁重置、删除或再次作为发送测试对象）**:
   - **目标作品**: 《面对癌症，财富究竟能带来什么？》（`export/UzFfBgAAxOClNFsoN2Spk8zT4DCaVikQXENps3YeyGFwg_SlGQ`）
   - **目标父评论**: 观众 `隽永`（`15031175812304083586`）
   - **获批双语回复 SHA256**: `ea5f09f481dd9a2fa2f5d89cfcd8a6fc46ac7e502c543e0ecda0703a6e2d67f7`
   - **真实平台新生成二级回复原生 ID**: `15034300564280904584`（状态 `VERIFIED`）

---

## 2. 架构师代码审核意见核实与四项有边界局部重构（本轮已在隔离工作区完成）

针对架构师对 `7bb24a6` 提出的四项核心问题（控件定位重复维护、只读验证宽松默认通过、DAL/依赖边界穿透、本地自批混淆人工审批边界），已在隔离工作区 `/Users/ryusei/.codex/worktrees/c446/Video-precessing` 完成有边界重构。

### 2.1 改建前后职责及依赖关系对照

| 维度 | 改建前 (`7bb24a6`) | 改建后（当前候选版本） |
| :--- | :--- | :--- |
| **DOM 控件定位与校准** | `calibrate_page_controls()` 与 `_interact_with_page()` 各自独立维护一套作品卡片绑定、回复图标、编辑器、提交按钮和展开按钮的选择器遍历与唯一性判断，容易出现校准通过但发送路径行为不一致。 | 收敛为 `SecondaryReplyBrowserAdapter` 内部 4 个最小共享定位方法：`_select_and_bind_post_card`、`_locate_unique_visible_control`、`_locate_expand_control`、`_open_and_bind_reply_controls`。校准与发送共用同一套定位、作用域与 `count > 1` 歧义阻断规则。 |
| **只读平台验证契约** | `secondary_reply_ops.verify_platform()` 使用松散字典合并，缺失 `identity_verified` / `text_matched` 时默认 `True`，缺失实测 `native_username` 时用配置 `finder_id` 顶替，且用 `hasattr(platform, "calibrate_and_verify")` 兼容旧平台。 | 在 `secondary_reply_contract.py` 建立强类型契约 `PlatformVerificationReport`（含 `ObservedChannelProfile`、`ObservedTargetComment`、`ControlsCalibrationSummary`、`CalibratedControlState`）。严格区分配置期望值与平台观测值；缺失或矛盾证据一律降级为 `status="UNKNOWN", ok=False`；保留 `REPLIED` 与 `NOT_REPLIED` 的差异化证据规则；移除 `hasattr` 分支。 |
| **DAL 与模块依赖方向** | 1) `secondary_reply_approval.py` 与 `scripts/wechat_secondary_reply.py` 直接调用 `db.get_connection()` 执行裸 SQL；<br>2) `secondary_reply_orchestrator.py` 与 `secondary_reply_fake_platform.py` 直接导入浏览器适配器层的 `SecondaryReplySubmissionGuard`；<br>3) `secondary_reply_browser_platform.py` 直接调用适配器私有方法 `_interact_with_page` 与 `_new_evidence_dir`。 | 1) 裸 SQL 全部收回 `PipelineDB.get_audience_comment()` 与 `PipelineDB.delete_secondary_reply_task()`；<br>2) `SecondaryReplySubmissionGuard` 下沉至中立契约层 `secondary_reply_contract.py`，编排器与 Fake 平台零浏览器适配器导入；<br>3) 浏览器平台实现仅调用适配器公开方法 `create_evidence_dir()` 与 `execute_page_reply_flow()`。 |
| **人工审批信任边界** | `approve` (`approve_local`) 允许本地执行者读取配置身份或回填 `local_operator` + 正文哈希前 12 位，在同一进程内自生自消 token 直接将任务置为 `APPROVED`；且 `_orchestrator` 将 `approver_id` 传给 `admin_ids_override` 绕过了白名单校验。 | 清晰拆分为三步：<br>1) `preflight`：草稿只读检查；<br>2) `request-approval` (`request_approval`)：核对 `confirm_reply_sha12` + 校验 `telegram_admin_ids` 白名单与非空非 `local-cli:` 会话 + 绑定一次性随机 token 并通过外部 `transport` 派发审批卡片（任务保持 `PENDING_REVIEW`，未接通 `transport` 时返回 `APPROVAL_TRANSPORT_UNAVAILABLE`）；<br>3) `approve-callback` (`approve_callback`)：仅凭白名单审批人回调消费一次性 token 才可进入 `APPROVED`。旧 `approve` 入口硬拒绝并返回迁移说明。 |

### 2.2 四项改建对应代码位置与核实结果

1. **改建一：统一控件定位，消除校准与发送的重复实现**
   - **代码位置**: [secondary_reply_browser_adapter.py](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/interaction/secondary_reply_browser_adapter.py#L468-L625)（共享定位原语）、[#L627-L875](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/interaction/secondary_reply_browser_adapter.py#L627-L875)（发送流程 `execute_page_reply_flow`）、[#L1140-L1358](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/interaction/secondary_reply_browser_adapter.py#L1140-L1358)（只读校准 `calibrate_comment_controls` / `calibrate_page_controls`）。
   - **结果**: 作品卡片唯一绑定、父评论定位、展开按钮定位、回复触发按钮定位、编辑器与提交按钮绑定完全复用同一套函数；歧义（`count > 1`）、隐藏节点、未知结构、分页不足全部拒绝且绝不回退到 `first` 或下标 `0`；校准过程只探查控件状态并在結束后还原关闭编辑器，不输入待发送正文、不点击提交。

2. **改建二：建立严格的只读验证结果契约**
   - **代码位置**: [secondary_reply_contract.py](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/interaction/secondary_reply_contract.py#L220-L433)、[secondary_reply_ops.py](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/interaction/secondary_reply_ops.py#L369-L545)、[secondary_reply_browser_adapter.py](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/interaction/secondary_reply_browser_adapter.py#L1215-L1358)、[secondary_reply_browser_platform.py](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/interaction/secondary_reply_browser_platform.py#L168-L185)。
   - **结果**: `identity_verified` 缺失不再默认 `True`（要求 `observed_native_username != ""` 且等于 `expected_finder_id`）；`text_matched` 与 `fresh` 缺失不再默认 `True`；`native_username` 缺失绝不用配置 `finder_id` 冒充；`NOT_REPLIED` 要求 `completeness == "COMPLETE"` 且三大控件唯一就绪；`REPLIED` 要求身份、原文匹配、新鲜度及非错误 `completeness` 证据，但不强求与 `NOT_REPLIED` 相同的展开编辑器校准。

3. **改建三：恢复 DAL 封装和依赖边界**
   - **代码位置**:
     - DAL 方法封装: [database.py](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/db/database.py#L13015-L13044)（`get_audience_comment`）、[#L13850-L13867](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/db/database.py#L13850-L13867)（`delete_secondary_reply_task`）；
     - 守卫契约解耦: [secondary_reply_contract.py](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/interaction/secondary_reply_contract.py#L118-L217)（`SecondaryReplySubmissionGuard`）、[secondary_reply_orchestrator.py](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/interaction/secondary_reply_orchestrator.py#L22-L65)、[secondary_reply_fake_platform.py](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/interaction/secondary_reply_fake_platform.py#L18-L25)；
     - 适配器公开接口: [secondary_reply_browser_adapter.py](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/interaction/secondary_reply_browser_adapter.py#L459-L466)（`create_evidence_dir`）、[#L627-L645](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/interaction/secondary_reply_browser_adapter.py#L627-L645)（`execute_page_reply_flow`）、[secondary_reply_browser_platform.py](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/interaction/secondary_reply_browser_platform.py#L94-L148)。

4. **改建四：修正“人工审批”边界**
   - **代码位置**: [secondary_reply_ops.py](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/interaction/secondary_reply_ops.py#L71-L100) & [#L186-L318](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/interaction/secondary_reply_ops.py#L186-L318)、[secondary_reply_approval.py](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/interaction/secondary_reply_approval.py#L105-L273)、[database.py](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/db/database.py#L13144-L13245) & [#L13319-L13345](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/src/video_processing/db/database.py#L13319-L13345)、[wechat_secondary_reply.py](file:///Users/ryusei/.codex/worktrees/c446/Video-precessing/scripts/wechat_secondary_reply.py#L256-L425)。
   - **接口迁移说明**:
     - 旧命令 `approve --task-id <id> --confirm-reply-sha12 <sha12>` 已停止产生批准效果，调用时返回 `ok=False, reason="SELF_APPROVAL_DISABLED_REQUIRES_VERIFIED_CALLBACK"` 及迁移指引；
     - 新流程分两步：
       1. 发起审批请求并确认正文哈希：`request-approval --task-id <id> --confirm-reply-sha12 <sha12>`（校验白名单配置后通过 `approval_transport` 发送带一次性 token 的审批卡片，任务保持 `PENDING_REVIEW`；若 `approval_transport` 未接通，返回 `APPROVAL_TRANSPORT_UNAVAILABLE`）；
       2. 消费可验证审批回调：`approve-callback --callback-data "rep:<task_id>:<token>:app" --approver-user-id <uid> --approver-chat-id <cid>`（校验 `telegram_admin_ids` 白名单、绑定 `chat_id`、账号归属、源评论哈希、草稿版本、正文哈希与有效期后，原子消费 token 并将状态置为 `APPROVED`）。
   - **真实信任边界说明**:
     - 代码层与数据库事务层严格阻止了“仅凭配置项、`local_operator` 占位符、`local-cli:` 伪会话或执行者自行回填哈希就将任务标记为 `APPROVED`”的自批捷径；在未接通外部可验证审批传输通道（如 Telegram Bot Transport）时，发送链路默认保持不可用（`PENDING_REVIEW`）；
     - **不夸大安全边界**：本机制提供的是应用工作流与职责分离（SoD）层面的防误发与审计约束，**不能防御拥有本机任意 Python 代码修改权限或直接修改 SQLite 数据库文件权限的本地特权操作者**。

---

## 3. 存量代码与自动化方案审查跟踪表（Code & Design Review Status）

### 3.1 存量问题状态

| 编号 | 级别 | 问题描述 | 状态 |
| :--- | :--- | :--- | :--- |
| **CR-03** | **P1** | `secondary_reply_approval.py` 与 `scripts/wechat_secondary_reply.py` 直接调用 `db.get_connection()` 执行裸 SQL。 | ✅ **本轮已修复**（收回 `PipelineDB.get_audience_comment` 与 `delete_secondary_reply_task`） |
| **AR-01** | **P0** | 校准与发送分别维护回复按钮、编辑器、提交按钮及卡片绑定逻辑。 | ✅ **本轮已修复**（收敛为适配器共享定位原语） |
| **AR-02** | **P0** | `verify_platform` 缺失 `identity_verified` / `text_matched` 默认 `True`，缺 `native_username` 用配置 `finder_id` 顶替。 | ✅ **本轮已修复**（`PlatformVerificationReport` 强类型契约，缺证据一律 `UNKNOWN` / `ok=False`） |
| **AR-03** | **P0** | 编排器依赖浏览器层 `SecondaryReplySubmissionGuard`，平台层调用适配器私有方法 `_interact_with_page` / `_new_evidence_dir`。 | ✅ **本轮已修复**（守卫移至 `secondary_reply_contract.py`，适配器公开 `execute_page_reply_flow` / `create_evidence_dir`） |
| **AR-04** | **P0** | `approve_local` 允许执行者凭配置与回填哈希本地自批，且 `_orchestrator` 传入 `admin_ids_override` 绕过白名单。 | ✅ **本轮已修复**（拆分 `request-approval` 与 `approve-callback`，废止自批，强制校验 `telegram_admin_ids` 与真实 `chat_id`） |
| **CR-01** | **P1** | 提交后立即回读偶遇平台 2~4s 异步索引延迟落入 `UNCERTAIN`，需手动执行一次 `reconcile-platform`。 | ⏳ **归入 M3.5 自动进程开发** |
| **CR-02** | **P1** | 未显式传 `--evidence-dir` 时默认回退系统临时目录。 | ⏳ **归入 M3.5 自动进程开发** |
| **CR-04** | **P1** | 未显式传 `--video-title` 时 `post_hints` 从 `PipelineDB` 自动回填视频标题。 | ⏳ **归入 M3.5 自动进程开发** |

### 3.2 后续自动回复进程（M3.5 / M4）设计约束（待本轮候选审核通过并获批后实施）

| 编号 | 级别 | 涉及模块 | 核心设计约束 |
| :--- | :--- | :--- | :--- |
| **SR-01** | **P0** | `database.py`<br>`secondary_reply_runner.py` | **认领前只读配额与时间窗门禁**：Tick 发送阶段在调用 `claim_approved_reply_task` 前，先只读检查上海时间窗（08:30–23:00）、60m 滚动配额与 15s 最小间隔；暂不可发时保持 `APPROVED`，绝不因排队限流把已批准任务打成 `FAILED`。 |
| **SR-02** | **P0** | `database.py` | **Phase 0 `UNCERTAIN` 对账指数退避与上限**：新增 `reconcile_count` 与 `next_reconcile_at`，按 `1m -> 5m -> 30m -> 2h` 退避，最多自动对账 4 次；超限后保留防重墓碑不重发，转人工告警，防止单条异常任务饿死后续队列。 |
| **SR-03** | **P1** | `database.py` | **防止重入生成覆盖待审 Token**：已创建任务的评论排除在下次自动生成之外，避免刷新管理员手机上尚未点击的审批卡片 Token。 |
| **SR-04** | **P1** | `database.py` | **视频级扫描水位表 `wechat_comment_scan_state`**：记录每个作品的 `last_scanned_at` 与 `next_scan_after`（Hot $\le 72\text{h}$ 每 30m，Warm $\le 14\text{d}$ 每 4h），避免“0 评论视频”被无限重复扫描。 |

---

## 4. 后续自动回复进程（M3.5 / M4）架构与开发计划

> [!IMPORTANT]
> 本节为后续阶段的技术规划。在当前重构候选通过审核并获得明确阶段授权前，**不提前实现批量/常驻/自动生成或真实 Telegram 传输**。

### 4.1 依赖方向与模块职责边界（严格遵循 `CONTRIBUTING.md` DAG）

```
scripts/wechat_secondary_reply.py (CLI: import-draft / preflight / request-approval / approve-callback / submit / reconcile-platform / verify-platform / [M3.5: tick])
   ↓
src/video_processing/interaction/secondary_reply_ops.py  &  [M3.5: secondary_reply_runner.py]
   ↓
src/video_processing/interaction/secondary_reply_orchestrator.py
   ├── secondary_reply_contract.py (SecondaryReplySubmissionGuard + PlatformVerificationReport + 内容合同)
   ├── secondary_reply_service.py  ([M3.5: + secondary_reply_agy_provider.py])
   ├── secondary_reply_approval.py ([M3.5: + TelegramApprovalTransport])
   └── secondary_reply_browser_platform.py
         └── secondary_reply_browser_adapter.py
   ↓
src/video_processing/db/database.py (PipelineDB)  +  src/video_processing/core/wechat_session_lock.py
   ↓
src/config/settings.py
```

### 4.2 分阶段实施路线图

- **Milestone 3.2（当前已完成，待审核）**：四项有边界局部重构（统一控件定位、强类型只读验证契约、恢复 DAL 与守卫依赖边界、修正人工审批边界与禁用本地自批）+ 隔离回归测试闭环。
- **Milestone 3.5（下一阶段，需审核通过后授权）**：
  1. 接入真实 `TelegramApprovalTransport`（使用 `httpx` 发送审批卡片至白名单管理员私聊）与 `src/bot/telegram_bot.py` 的 `^rep:` 按钮回调（纯 DB 短事务调用 `approve_callback` 消费一次性 Token）；
  2. 接入受限沙箱 `AgySecondaryReplyProvider`（`--mode plan --sandbox --disable-slash-commands`，空临时目录，严格证据锚定）；
  3. 实现有界单次 `run_secondary_reply_tick`（对账优先 $\rightarrow$ 已批发送优先 $\rightarrow$ 增量采集 $\rightarrow$ 无锁草稿生成与推送审批卡）。
- **Milestone 4（远期阶段，需 M3.5 人工审批满 50 条且采纳率 $\ge 90\%$ 后另行评估授权）**：低风险评论分级受控巡航。
