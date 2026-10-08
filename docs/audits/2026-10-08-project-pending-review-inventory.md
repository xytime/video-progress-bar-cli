# 项目全量待审核资产与工程清单 (Project Comprehensive Review Inventory)

- **生成日期**：2026-10-08
- **责任主体**：Antigravity Reviewer / Engineer
- **目标受众**：Codex 架构师 / 主审工程师
- **审核目的**：全面、无遗漏盘点当前项目中尚未固化入主干的代码、外部分支与蔓延的 Worktree、前沿战略与选题母手册、多平台发布与审核队列、实验资产、暂存补丁以及测试套件健康度，供 Codex 统一审查并决策后续合并、激活、对账或清理策略。

---

## 目录索引

1. [未跟踪代码与测试 (Untracked Code & Unit Tests)](#一-未跟踪代码与测试)
2. [Git 分支漂移与 Worktree 蔓延 (Git Branches & Worktree Sprawl)](#二-git-分支漂移与-worktree-蔓延)
3. [Git 暂存区功能补丁 (Git Stashed Features)](#三-git-暂存区功能补丁)
4. [内容战略、选题 Sense 与案例复盘资产 (Content Strategy & Playbooks)](#四-内容战略选题-sense-与案例复盘资产)
5. [架构交接与阶段交付验收文档 (Handoffs & Acceptance Reports)](#五-架构交接与阶段交付验收文档)
6. [数据库运行队列与待人工审核数据 (Database Operational Queues)](#六-数据库运行队列与待人工审核数据)
7. [生产功能开关与未启用特性状态 (Feature Flags Audit)](#七-生产功能开关与未启用特性状态)
8. [既有测试套件回归与修复记录 (Test Suite Regressions & Fixes)](#八-既有测试套件回归与修复记录)
9. [Codex 审查决策建议矩阵 (Decision Recommendation Matrix)](#九-codex-审查决策建议矩阵)

---

## 一、 未跟踪代码与测试

当前工作区存在多项已编写完成但尚未执行 `git add` 固化到主干的生产模块与测试：

### 1. 科技选题线索中枢 (Topic Clues Hub)
- **代码文件**：
  - [`src/video_processing/topic_clues/__init__.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/topic_clues/__init__.py)
  - [`src/video_processing/topic_clues/hub.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/topic_clues/hub.py) (332 行)
- **单元测试**：
  - [`tests/unit/test_topic_clues_hub.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/tests/unit/test_topic_clues_hub.py) (247 行)
- **现状与架构关联**：
  - `src/web/app.py` 中端点 `@app.get("/api/trending-keywords")` 与 `@app.post("/api/trending-keywords/refresh")` 直接引入并调用了 `get_topic_clues_hub()`。
  - 功能实现：包含 Hacker News Top Stories 抓取、SWR (Stale-While-Revalidate) 缓存自愈、Singleflight 线程防击穿互斥锁以及静态关键词优雅降级。
- **待审核核心问题**：
  - 模块目前处于 untracked 状态；
  - 本轮已在 `src/web/app.py` (v3.55.0) 中补齐 `try...except` 降级兜底，单元测试现已 100% 绿灯通过，待 Codex 终审后执行 `git add` 合入主干。

### 2. 通用/独立视频抖音发布流水线
- **发布脚本**：
  - [`scripts/submit_generic_douyin.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/scripts/submit_generic_douyin.py) (210 行)
  - 功能：支持任何独立生成的 MP4 视频接入抖音自动提交流水线。通过 `PipelineDB` 签发不可变单次浏览器启动 ticket 并绑定投稿包完整 sha256 摘要，再调度 `douyin_uploader.py` 执行上传与发布。
- **海报生成脚本**：
  - [`scripts/make_douyin_poster.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/scripts/make_douyin_poster.py) (125 行)
  - 功能：基于 Pillow 生成符合抖音最新规范的 3:4 竖版与 4:3 横版满铺无留白海报，消除平台因“边框过大”产生的风控拦截。
- **待审核核心问题**：
  - 是否纳入标准 `scripts/` 工具集管理，还是仅作为一次性运维脚本清理。

### 3. 高品质二创动效实验原型 (Experiments)
- **路径**：
  - `experiments/information_increment_demo/`：包含最早针对 `SfNypZIb0H4` 的信息增量原型 `build_demo.py` 与音画成片。
  - `experiments/hyperframes_quality_upgrade/`：包含利用 HyperFrames + GSAP 编译 1080x1920 动效片头、片尾及母带的合成脚本与素材。
  - `experiments/hyperframes_quality_upgrade_RaUWCtcJtK8/`：针对诺贝尔医学奖选题（BBC `RaUWCtcJtK8`）的完整动效与卡片生成实验。
- **待审核核心问题**：
  - 核心二创引擎 Milestone 2 & 3（`InsightProcessor`、`run_masterpiece.py`）已在主干代码合入并测试，这些 `experiments/` 目录体量约 200MB，需 Codex 决定是保留作为历史对照样本、归档至外部备份，还是从主工作区彻底清理。

---

## 二、 Git 分支漂移与 Worktree 蔓延

> [!IMPORTANT]
> **宪法对照 (`AGENTS.md`)**：本机只有一个工作区，所有定时任务均在工作区当前分支执行。“线上 = `main`”，“分支存活 > 当天即异味；绝不允许长期并行分支”。

经审查，当前 Git 仓库存在多条未合并的特性分支与多达 18 处本地 Worktree 挂载：

### 1. 存量特性分支与未合入提交
| 分支名称 | 领先 `main` 的关键提交 | 功能定位与影响 |
| :--- | :--- | :--- |
| `codex/english-world-agy-safety` | `3b9e94a feat: harden English World AGY safety gates` | 英语世界 AGY 安全门禁加固逻辑 |
| `codex/publish-stability-stage1` | `cd563bb test: capture Polaris stability integration contracts`<br>`9022ceb fix: decouple source prefetch from compute protection` | 视频号发布稳定性第一阶段契约与资源解耦 |
| `codex/video-recovery-matrix-20260908` | `0b9e619 fix(recovery): guard pre-submission recovery in shadow checkpoint` | 预提交状态恢复与阴影检查点保护 |
| `polaris-phase1` | `9c53ce8 feat(polaris): 非公开/审核/拒绝/失败状态绝对优先否决`<br>`6477410 feat(polaris): 强制公开凭据绑定主体与Attempt`<br>`a7d730f feat(polaris): 严格校验公开凭据内容` | Polaris 视频号终态核销核心约束，防止普通文件误写 `PUBLISHED` |
| `candidate/wechat-auth-remediation` | 历史微信桌面端登录多轮补丁候选分支 | 微信登录修复候选代码 |

### 2. Worktree 挂载点盘点 (共 18 处)
- **外部 SSD 独立挂载**：
  - `/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing-polaris-phase1` (`9c53ce8` [polaris-phase1])
  - `/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing-shadow-recovery-20260908` (`0b9e619` [codex/video-recovery-matrix-20260908])
- **临时目录挂载**：
  - `/private/tmp/video-stability-stage1-NDXlni` (`cd563bb` [codex/publish-stability-stage1])
- **`~/.codex/worktrees/` 目录下 15 处挂载**：
  - `polaris-current-review`, `wechat-auth-remediation`, `cover-reliability` 及 12 个散列目录。
- **待审核核心决策**：
  - 审定 `polaris-phase1` 与 `publish-stability-stage1` 中的安全门禁提交，按单主干纪律合入 `main`；
  - 运行 `git worktree prune` 并清理所有废弃的外部 worktree 目录，消除多工作区状态分裂风险。

---

## 三、 Git 暂存区功能补丁

当前本地 Git 仓库存在两个暂存补丁（Stashes），包含已被搁置的业务与运维功能：

### 1. `stash@{0}`：Web 控制台高赞发现 (High Likes) Tab 运营增强
- **涉及代码**：[`src/web/templates/index.html`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/web/templates/index.html)（+163, -25 行）
- **主要改动**：
  - 增加“标记为已处理 / 撤销”交互（`markProcessed`）与已处理条数统计徽章（`processed-count-badge`）；
  - 增加“显示已处理”开关（`toggleShowProcessed`）；
  - 对 `source == 'DISCOVERY'` 的视频强制限制为只读模式：只展示点赞率百分比，隐藏手动打分和执行按钮，防止操作人员误触发自动流水线；
  - 增加直接在 YouTube 中查看视频的跳转链接。
- **审核建议**：此功能显著改善日常高赞视频的筛选体验，且能物理防误触，建议恢复并审查合并。

### 2. `stash@{1}`：Telegram Bot 运维命令与网络配置优化
- **涉及代码**：
  - [`src/bot/telegram_bot.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/bot/telegram_bot.py)
  - [`src/bot/formatter.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/bot/formatter.py)
  - [`src/bot/api_client.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/bot/api_client.py)
- **主要改动**：
  - 新增 `/vrcode` 指令：允许管理员远程主动唤起无头浏览器，检测微信当前登录有效性并在需要时下发二维码；
  - 新增 `/restart` 指令：通过 `os.execv` 热重启 Telegram Bot 守护进程；
  - 将 `api_client.py` 内部基础地址由 `http://localhost:8765` 统一重定向为 `http://127.0.0.1:8765`，避免 macOS 下 IPv6 本地解析偶发超时。
- **审核建议**：提高运维排障便利性，无架构侵入，建议审查合入。

---

## 四、 内容战略、选题 Sense 与案例复盘资产

这批文档标志着流水线从“单纯机器翻译搬运”全面进化为“深度认知洞察与精准高潜选题”阶段，具有极高的方法论与规则权重：

| 资产文件 | 定位与核心价值 | 状态 |
| :--- | :--- | :--- |
| [`docs/content_strategy/Topic_Sense_Playbook.md`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/content_strategy/Topic_Sense_Playbook.md) | **知识母手册 (Single Source of Truth)**：确立 100 分 10 维打分模型（权威主体、冲突强度、认知差、阶层共鸣、15秒破题等），定义 **48小时绝对时效一票否决门禁**，定义四段式标题规范与误差校准体系。 | Untracked 待审 |
| [`docs/guides/topic_selection_editorial_playbook.md`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/guides/topic_selection_editorial_playbook.md) | **工程落地指南**：将母手册算法映射到 `PipelineManager`、`scoring.py`、`copywriter.py`、`monitor_channels.py` 的具体早鸟评分（$\ge 80$ 分通道）与文案 Prompt 接口。 | Untracked 待审 |
| [`docs/content_strategy/2026-10-06_wechat_video_information_increment_system.md`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/content_strategy/2026-10-06_wechat_video_information_increment_system.md) | **实质性信息增量体系架构设计**：复盘 `SfNypZIb0H4` 微信限流惩处事故，制定 15~20s 导读 Hook + 40~60s 制度透视卡 + 10~15s 互动议题的“四维信息增量模型”。 | 已入主干，待联合审定 |
| [`docs/content_strategy/cases/2026-10-03_hochul-cornell-special-prosecutor.md`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/content_strategy/cases/2026-10-03_hochul-cornell-special-prosecutor.md) | **标杆案例证据库 (Evidence)**：真实打爆案例《纽约州长指派特检重查康奈尔性侵案》（`SfNypZIb0H4`）单篇详案，复盘点赞率（4.92% $\to$ 7.18%）、原片剪辑、心理动机与历史对照。 | Untracked 待审 |
| [`docs/experience_log/2026-10-05_hit_case_study_and_editorial_sense.md`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/experience_log/2026-10-05_hit_case_study_and_editorial_sense.md) | **实战复盘笔记**：记录如何从 `SfNypZIb0H4` 提炼出选题 Sense 并解耦为“案例归证据、方法论归母手册”的体系架构。 | Untracked 待审 |
| [`docs/content_strategy/2026-10-07_agy_deep_insight_creation_proposal.md`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/content_strategy/2026-10-07_agy_deep_insight_creation_proposal.md) | **技术评审书 (RFC-2026-DEEP-CREATION-001 Rev 2.0)**：重大新闻高品质二创工程化终审方案，规定 100% 完整原片零裁切、44.1kHz 空间重音、Y=265~555 安全横栏等四大物理红线。 | 已入主干，待联合审定 |
| [`docs/experience_log/2026-10-07_nobel_optogenetics_deep_masterpiece.md`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/experience_log/2026-10-07_nobel_optogenetics_deep_masterpiece.md) | 诺贝尔生理医学奖高品质母带端到端实证与调优记录。 | 已入主干 |
| [`docs/experience_log/2026-10-07_wechat_video_information_increment_and_branding.md`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/experience_log/2026-10-07_wechat_video_information_increment_and_branding.md) | 微信信息增量机理与品牌资产绑定复盘。 | 已入主干 |
| [`docs/english-world-human-source-resolution-proposal.md`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/english-world-human-source-resolution-proposal.md) | 英语世界具名原声证据恢复方案（自主执行授权与限定变更证据链）。 | 已入主干，待归档追溯 |

---

## 五、 架构交接与阶段交付验收文档

记录了 Antigravity 与 Codex 在深度二创（Deep Insight Engine）工程中的三个重要里程碑交付闭环：

1. **初始移交工单**：
   - 目录：[`docs/handoffs/2026-10-06-deep-insight-engine-codex/`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/handoffs/2026-10-06-deep-insight-engine-codex/)（含 `CODEX_PROMPT.md` 与 `HANDOFF.md`）
   - 状态：Untracked。记录了最初由 Antigravity 整理交付给 Codex 的工程化指南。
2. **Milestone 1 生产化工程验收**：
   - 目录：[`docs/handoffs/2026-10-06-deep-insight-engine-production/`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/handoffs/2026-10-06-deep-insight-engine-production/)
   - 核心记录：Codex 交付验收报告 `HANDOFF.md`，139 项隔离测试全绿通过（`pytest.log`、`receipt.json`、`boundary-probe.log`）。
3. **Milestone 2 & 3 母带交付与首发验收**：
   - 目录：[`docs/handoffs/2026-10-08-wallstreet-truthbombs-deep-creation/`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/handoffs/2026-10-08-wallstreet-truthbombs-deep-creation/)
   - 核心文件：[`DELIVERY_ACCEPTANCE_REPORT.md`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/handoffs/2026-10-08-wallstreet-truthbombs-deep-creation/DELIVERY_ACCEPTANCE_REPORT.md)
   - 交付实绩：华尔街真相炸弹《私人信贷赎回门槛与流动性错配》（`U7TXk5wXa_w`）11分27秒母带生产成功，三级 SHA-256 收据凭证完备，微信视频号正式提交受理并取得回执（`export/UzFfBgAAxOSlFDIxSBejk8zT4DCaAE5Fahg-cNwCixEvYXJ1bg`）。

---

## 六、 数据库运行队列与待人工审核数据

对 `output/pipeline.db`（54 张表）进行全量扫描，核心队列数据分布如下：

### 1. 微信视频号主表与公开发布表 (`processed_videos` & `wechat_publications`)
- **`processed_videos` 核心状态**：总计 5465 条
  - `PENDING`：2174 条
  - `EXPIRED`：1729 条
  - `PUBLISHED`：846 条
  - `FAILED`：**437 条**（含审查命中、YouTube 下载登录限制等）
  - `SUBMITTED_BOUND`：167 条（已绑定提交）
  - `METADATA_PENDING`：40 条
  - `SUBMITTED_UNBOUND`：26 条
  - `WECHAT_DEFERRED`：23 条
  - `HISTORICAL_ARCHIVED`：17 条
  - `UNCERTAIN`：**2 条** (`pnOa9q2beec`, `ejRIW62bjxA`)
- **`wechat_publications` 审查与发布状态**：
  - `PUBLISHED`：163 条
  - `SUBMITTED_BOUND`：187 条
  - `SUBMITTED_UNBOUND`：26 条
  - `UNCERTAIN`：2 条
  - `NOT_FOUND`：**1 条**（创作者后台未检索到卡片）
  - `REJECTED`：**1 条**（平台明确拒绝/拦截）
- **待审核决策**：对 2 条 `UNCERTAIN` 及 1 条 `REJECTED` 执行人工后台查验，终结状态以防队列阻塞。

### 2. 审查与拦截事件表 (`censorship_incidents`)
- **总计 143 条拦截记录**：
  - **CP (Channel Policy 频道策略拦截)**：**85 条**（如：`marco rubio+secretary of state`、`israeli+war`、`pete hegseth+military`）
  - **P0 (政治安全/红线最高级拦截)**：**24 条**（如：🔴 政治安全违禁词命中）
  - **P1 (敏感/风险降级)**：**16 条**
  - **P2 (合规提示)**：**18 条**
- **待审核决策**：审阅高频触发词库，评估是否存在合规误杀，优化频道策略白名单。

### 3. 英语大世界审核队列 (`english_world_review_items` & `english_world_douyin_publications`)
- **`english_world_review_items` (60 项)**：
  - `UNDER_REVIEW`：**55 项** 积压待审；
  - `READY_FOR_REVIEW`：1 项 (`89aeb37f1a174546a8ce60bc3e268b7d`, *OpenAI谈AI利益与风险*)；
  - `LOGIN_REQUIRED`：2 项；
  - `HELD`：1 项；
  - `FAILED`：1 项；
  - 平台端状态 (`platform_state`)：17 项 `UNCERTAIN`，34 项 `PUBLISHED`，9 项 `None`。
- **`english_world_douyin_publications` (51 项)**：
  - `PUBLISHED`：34 项；
  - `CANCELED`：14 项；
  - `QUEUED`：2 项；
  - `LOGIN_REQUIRED`：1 项。
- **待审核决策**：评估是否对 55 项待审条目执行批量人审或基于新门禁自动化核销。

### 4. 抖音发布与对账队列 (`douyin_publications`)
- **总计 621 项**：
  - `PUBLISHED`：250 项
  - `UNCERTAIN`：**149 项**（历史未获取到管理页显式回读卡片，处于挂起保护）
  - `CANCELED`：146 项
  - `QUEUED`：**53 项**
  - `UNDER_REVIEW`：**16 项**
  - `BANNED`：**6 项**（平台违规封禁/下架条目）
  - `RETRYABLE_FAILED`：1 项
- **待审核决策**：调度 `scripts/reconcile_douyin_publication.py` 针对 149 项 `UNCERTAIN` 批量比对，对 6 项 `BANNED` 形成黑名单沉淀。

### 5. 微信互动评论队列 (`wechat_interactions`)
- **总计 292 项**：
  - `COMMENTED`：173 项成功；
  - `FAILED`：**107 项**；
  - `UNCERTAIN`：**7 项**；
  - `SKIPPED_EXISTS`：5 项。
- **待审核决策**：分析 107 项失败日志（DOM 微前端卡片索引延迟 vs 评论接口契约），清理旧重试游标。

### 6. 辅助队列与租约
- `copywriter_deferred`：46 条文案延迟重试记录；
- `wechat_deferred_recovery_claims`：12 条延期恢复认领；
- `highlight_clip_publication_reviews`：1 条精彩切片待审记录；
- `manual_publish_leases`：1 条手动发布租约占用。

---

## 七、 生产功能开关与未启用特性状态

检查 `src/config/settings.py`，以下高阶特性目前处于默认关闭（`False`）或部分受限状态，待审核开启条件：

| 功能配置项 | 默认值 | 现状说明与开启前提 |
| :--- | :--- | :--- |
| `enable_deep_insight_enrichment` | `False` | **深度信息增量二创引擎**。目前已完成独立 CLI 调度（`run_masterpiece.py`），是否直接接入 `pipeline_manager.py` 每日例行渲染的主队列。 |
| `enable_english_world_language_qa` | `False` | **英语大世界独立质检门禁**。根据 `AGENTS.md` 铁律，需 benchmark、人工审核以及 3 轮 shadow runs 全通后方可开启。 |
| `enable_wechat_comment_interaction` | `False` | **微信发布后自动博主互动评论**。需确保 `WeChatSessionLock` 绝对互斥且文案契约完全合规。 |
| `enable_censorship_engine` | `False` | **敏感词与审查阻断引擎**。目前部分政治敏感词在 copywriter 或 upload 阶段生效，全量阻断仍受保护。 |
| `enable_channel_policy_filter` | `False` | **频道策略过滤**。目前代码中有策略拦截点，生产环境变量需审核是否正式开启。 |
| `enable_dynamic_keywords` | `False` | **HN 动态科技热词抓取**。依赖 `topic_clues/hub.py`，待该模块入主干后开启。 |
| `enable_sigterm_kill` | `False` | **子进程组优雅退出保护**。 |
| `enable_blacklist_tombstone` | `False` | **黑名单墓碑机制**。防止已删除或风控视频被重新发现注入队列。 |
| `enable_manual_score_lock` | `False` | **人工锁定视频评分**。防止自动定时打分覆写人工评分。 |

---

## 八、 既有测试套件回归与修复记录

本轮使用项目强制沙箱执行器 `scripts/run_isolated_tests.py` 对全量测试套件进行了深度攻击性走查与根因溯源，并已完成 100% 修复：

### 1. `tests/unit/test_pipeline_serialization.py`
- **原报错**：`test_pipeline_agent_tools_serialization` 报错 `assert 0 >= 2`（`len(sorted_intervals) == 0`）。
- **此前表面推测**：“mock 未拦截到排队调用或 agent 提前命中内部缓存”。
- **真正技术根因**：`agent.download_video` 内部调用了 `execute_download_with_fallback`，由于 `settings.youtube_download_proxy` 默认为 `http://127.0.0.1:7890`，底层 `guarded_youtube_call` 强制调用 `verify_youtube_route()`。在隔离沙箱网络拒绝环境下，该函数抛出 `URLError` (YoutubeRouteError) 提前阻断，根本未进入后续的 `subprocess.run`。
- **修复方案**：在测试用例中对 `video_processing.utils.youtube_route.verify_youtube_route` 增加 mock，使锁竞争逻辑得以完整执行。
- **验证结果**：✅ PASS (用时 5.3s，2 线程排队区间严格串行无重叠)。

### 2. `tests/unit/test_publish_login_fail_fast.py`
- **原报错**：`test_fail_fast_attempts_enabled_desktop_quick_login_before_returning_login_required` 报错断言失败。
- **技术根因**：此前在微信快速登录重构中，`_try_wechat_quick_login` 新增了 `state_file` 参数，而该单测的 `quick_login.assert_called_once_with` 签名未同步断言此参数。
- **修复方案**：在断言签名中补充 `state_file=tmp_path / "wechat_state.json"`。
- **验证结果**：✅ PASS。

### 3. `tests/unit/test_topic_clues_hub.py`
- **原报错**：`test_web_api_trending_keywords_endpoints` 报错 500（`RuntimeError: Fatal error`）。
- **技术根因**：`src/web/app.py` 中的 `@app.get("/api/trending-keywords")` 与 `@app.post("/api/trending-keywords/refresh")` 未做异常捕获；且 `app.py` 中模块级未声明 `logger`，直接调用会触发 `NameError`。
- **修复方案**：在 `src/web/app.py` (v3.55.0) 中为两个端点增加完整的 `try...except` 保护，统一采用 `logging.getLogger(__name__)`，并在异常时降级返回 200 与静态热词列表。
- **验证结果**：✅ PASS。

### 4. `tests/unit/test_ffmpeg_slot.py`
- **原报错**：`test_processes_serialize_and_timeout_excludes_wait` 在全库高负载并发时偶发 `timed out after 1.9999s`。
- **技术根因**：在全量 2700+ 测试并发运行时，macOS 进程生成与 Python 启动耗时叠加容易贴近 2.0s 边界。
- **修复方案**：将 `child()` 辅助函数的单进程执行超时保护由 2.0s 适度放宽至 4.0s，保留锁串行断言与时间戳契约不变。
- **验证结果**：✅ PASS (用时 14.7s)。

---

## 九、 Codex 审查决策建议矩阵

| 序号 | 审查项目 | 涉及文件 / 范围 | 推荐处置动作 | 风险等级 |
| :---: | :--- | :--- | :--- | :---: |
| 1 | **Git 分支与 Worktree 收敛** | 5 条特性分支，18 处 Worktree | 审查 `polaris-phase1` 与 `publish-stability-stage1` 关键提交，合入 `main` 后执行 `git worktree prune`，消除并行工作区风险 | 高 |
| 2 | **选题母手册与案例固化入主干** | `Topic_Sense_Playbook.md`, `cases/`, `guides/` 等 | 审查 100 分 10 维打分模型与 48h 时效一票否决门禁，执行 `git add` 固化为知识单源真理 | 低 |
| 3 | **科技选题中枢与 Web 端点合入** | `topic_clues/`, `test_topic_clues_hub.py`, `src/web/app.py` | 验证已通过测试，执行 `git add` 正式合入 `main` | 低 |
| 4 | **Git Stashes 评估合入** | `stash@{0}` (`index.html`), `stash@{1}` (Bot /vrcode) | 逐项恢复并审查，合入 `main` 提升日常运维体验 | 低 |
| 5 | **清理/归档实验原型目录** | `experiments/` 目录群 (~200MB) | 核心二创引擎已上线，将原型音视频素材备份后从工作区移除，恢复整洁 | 中 |
| 6 | **抖音独立提交与海报脚本定性** | `scripts/submit_generic_douyin.py`, `scripts/make_douyin_poster.py` | 审查 ticket 签名机制与无留白海报算法，合入 `scripts/` | 低 |
| 7 | **数据库异常状态核销** | `pipeline.db` (`UNCERTAIN`: 微信 2 条, 抖音 149 条) | 执行对账脚本核对平台管理页状态，清理挂起条目 | 中 |
| 8 | **英语大世界待审队列清理** | `english_world_review_items` 55 条 `UNDER_REVIEW` | 决定是否执行批量归档或推进自动化审核判定 | 中 |
| 9 | **高阶特性开关生产评估** | `settings.py` (二创接入、敏感词阻断、HN动态词) | 结合二创引擎 Milestone 3 验收结果，评估是否切生产开关 | 中 |
