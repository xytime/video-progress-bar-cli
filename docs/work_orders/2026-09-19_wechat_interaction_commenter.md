# 【工程工单】Project WeChat-Interaction-Engine 视频号评论区互动与自生长引导系统

- **项目代号**：`Project WeChat-Interaction-Engine`
- **创建日期**：2026-09-19
- **状态**：已完成微内核开发、测试并通过 1698 项隔离回归（Verified on `main`）
- **目标分支**：`main`（严格遵守单主干单工作区纪律）
- **审计与复核目标**：交由 Codex 进行架构与安全性独立复核

---

## 一、背景与业务意图

视频号已发布视频如果缺乏初始互动，容易沉底。为了在视频发布初期（发布后 5~10 分钟）迅速激活评论区、拉升互动权重并激发转发裂变，本系统通过微信官方【作者】标签身份在后台评论管理页自动发表结构化的引导首评。

### 核心业务目标
1. **促活跃与低摩擦互动**：以单字符投票（`扣A` / `扣B` / `扣C`）或态度站队极大降低用户发言门槛；
2. **刺激转发裂变**：针对不同题材自动匹配 4 种底层社交转发心理学：
   - **利他避坑**（财经风险、健康误区、AI安全）：*随手转给身边经常涉及的朋友提个醒！*
   - **群聊研讨**（行业前沿、技术路线分歧）：*转发到你的工作/技术群，测测同行们站哪边？*
   - **干货备忘**（密集知识、教程步骤）：*转给‘文件传输助手’或收藏慢慢复盘！*
   - **观点嘴替**（痛点共鸣、反常识思考）：*认同作者观点的点赞集合👍，转给懂你的同频好友！*
3. **高可读性格式编排**：
   - 实测后台输入框为 `<textarea>`，自动化注入支持多行自然换行 `\n`；
   - 采用 Emoji 视觉色块（📌 话题、🗳️ 投票、🅰️ 🅱️ 选项、💬 引导、📢 转发提示）作为视觉锚点，即便在折行设备上也能保证清晰的语义分块。

---

## 二、架构设计：拒绝屎山与高内聚微内核

针对既有 `pipeline_manager.py`（4300+行）和 `wechat_uploader.py`（2700+行）体量庞大的现状，本系统坚决拒绝在既有大文件继续堆叠逻辑，采用**完全独立的微内核包**：

```
src/video_processing/interaction/
├── __init__.py               # 暴露统一外部接口
├── contract.py               # 数据合同与严格质量校验 (InteractionDraft, InteractionResult, InteractionType)
├── prompt.py                 # AGY 深度思考提示词构造与严格 JSON Schema
├── strategy_store.py         # 自生长策略库管理器 (data/comment_strategies.json)
├── rule_provider.py          # 基于自生长知识库的高水准程序化兜底引擎
├── agy_provider.py           # 受限结构化 AGY CLI 调用适配器 (run_agy_structured)
├── service.py                # 业务门面 (AGY优先 -> 敏感词过滤 -> 沉淀知识库 -> 兜底降级)
├── browser_commenter.py      # Playwright 浏览器自动化 (排他锁、查重、发评、截图)
└── notifier.py               # Telegram 运营群图文通知与大图证据汇报
```

### 依赖与调度解耦（Dependency DAG 严格单向）
- **主流水线零业务污染**：`pipeline_manager.py` 内部仅增加 15 行极简的异步触发代码，通过 `subprocess.Popen` 调用独立 CLI `scripts/wechat_commenter.py`；
- **DAL 封装**：所有数据库读写均收敛于 `PipelineDB`（新增 `wechat_interactions` 账本表），业务代码绝不写裸 SQL。

---

## 三、核心机制设计

### 1. 动态选题与自生长策略库（`strategy_store.py` + `rule_provider.py`）
- **种子库初始化**：预置覆盖各类目及 5 种互动类型的种子模板；
- **AI 运行期自沉淀**：
  - 每次 AGY 生成并通过合规审查的优质互动，系统自动提取抽象模式：
    `(category, interaction_type, topic_pattern, poll_options, share_hook)`；
  - 沉淀至 `data/comment_strategies.json`，动态增加频次与权重；
  - 维持固定滑动窗口容量（单类目最多保留 Top 20 优质模板），自动淘汰低频旧模式。
- **程序化兜底自进化**：
  - 在断网、模型超时或降级时，程序化引擎**直接复用自生长库中沉淀的高分模板与语义槽位**进行装配，使兜底效果随运行持续逼近 AI。

### 2. 浏览器自动化与幂等防风控（`browser_commenter.py`）
- **跨进程排他锁**：使用 `output/.wechat_browser.lock`（fcntl 锁），确保评论浏览器绝不与 keepalive 保活或视频上传产生会话覆盖冲突；
- **双重幂等查重**：
  - 数据库层：`wechat_interactions` 表对 `platform_post_id` 设为 `UNIQUE` 约束；
  - 页面事实层：进入视频评论区后检测是否已有【作者】标签的评论，若有则直接标记 `SKIPPED_EXISTS`，严防重复发评；
- **全链路审计证据**：每一步操作（未找到视频、已存在、发评成功）均在 `output/wechat_evidence/interactions/` 下保存实机截图。

### 3. Telegram 运营图文闭环（`notifier.py`）
- 在 `telegram_delivery.py` 中扩充标准 `send_photo` 方法；
- 发评成功后自动向 Telegram 群推送富文本卡片（包含视频标题、互动模式、策略生成来源、排版全文预览）以及后台发表成功的**实机大图照片**。

---

## 四、生产安全与开发隔离（零风险承诺）

用户明确要求：**“不要影响当前项目其他功能的正常使用，即使这个开发工作持续一段日子”**。

系统落实以下 4 级安全防御：
1. **Feature Flag 默认关闭**：
   `settings.enable_wechat_comment_interaction: bool = False`（生产默认 `False`）；
   `pipeline_manager.py` 在未显式启用时直接 `return`，主干发布 100% 走原有路径，零开销、零风险；
2. **故障强隔离（Fail-Safe）**：
   子进程完全独立（`stdout=DEVNULL, stderr=DEVNULL`），发评失败绝不会改写视频的 `PUBLISHED` 状态，主业务不受任何牵连；
3. **敏感词一票否决**：
   AI 生成内容强制接入既有 `CensorshipEngine`，只要命中任何违规词立刻阻断并回退至绝对合规的正向自生长模板；
4. **退避回查窗口**：
   若视频发布后 5 分钟仍在转码或审核，自动记录 `PENDING_REVIEW`，不盲目报错，等待下周期回查。

---

## 五、代码变更清单与验证证据

### 1. 代码变更
- `[NEW]` `data/comment_strategies.json` —— 策略知识库与自生长沉淀文件
- `[NEW]` `src/video_processing/interaction/*` (8个文件) —— 独立微内核
- `[NEW]` `scripts/wechat_commenter.py` —— 独立 CLI 入口 (130 行)
- `[NEW]` `tests/unit/test_wechat_interaction.py` —— 单元测试套件
- `[MODIFY]` `src/config/settings.py` —— 增加 `enable_wechat_comment_interaction` (默认 False)
- `[MODIFY]` `src/video_processing/db/database.py` —— 增加 `wechat_interactions` 表与 DAL 方法
- `[MODIFY]` `src/video_processing/telegram_delivery.py` —— 增加 `send_photo` 支持
- `[MODIFY]` `src/video_processing/pipeline_manager.py` —— 增加异步调用委托
- `[MODIFY]` `.env.example` —— 增加配置项文档

### 2. 隔离回归测试验证
- **新模块针对测试**：
  ```bash
  .venv/bin/python scripts/run_isolated_tests.py -- -q tests/unit/test_wechat_interaction.py
  # 结果：10 passed in 0.22s (退出码 0)
  ```
- **全量单元回归套件**：
  ```bash
  .venv/bin/python scripts/run_isolated_tests.py -- -q tests/unit --ignore=tests/unit/test_dashboard_interactions.py
  # 结果：1698 passed, 12 warnings, 30 subtests passed in 56.27s (退出码 0)
  ```
- **实机 Dry-run 演练**：
  验证 AGY 生成、选项前缀去重、自生长学习沉淀均达到预期。

---

## 六、交由 Codex 审查的核心焦点

请 Codex 重点审查以下 5 个关键边界：
1. **架构高内聚低耦合性**：`src/video_processing/interaction/` 微内核与 `pipeline_manager.py` 的解耦是否足够彻底？是否存在违背项目 DAG 的反向依赖？
2. **生产安全性与特性开关**：`enable_wechat_comment_interaction` 默认 `False` 配合子进程异步启动，是否能够 100% 确保主流水线不受任何影响？
3. **自生长存储演化逻辑**：`StrategyStore` 的特征提取、权重演化与容量限制（Top 20）是否健壮，是否存在潜在的并发写入或脏数据风险？
4. **Playwright 执行健壮性**：`BrowserCommenter` 的选择器层级、排他锁机制、查重与证据截图是否足够防御微信后台的异步渲染与潜在风控？
5. **DAL 封装规范**：`PipelineDB` 中对 `wechat_interactions` 的记录与查询是否完全符合项目 DAL 宪法要求？
