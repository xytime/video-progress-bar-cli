---
title: 系统架构审查与改进报告
project: YouTube → 微信视频号 自动发布流水线
date: 2026-06-24
author: Claude_Opus_4.8
scope: 架构审查（只读，不改代码）
status: 评审稿
---

# 系统架构审查与改进报告

> 本报告从**系统架构角度**重新审查当前系统，给出完整的优点盘点、系统性缺陷诊断与分级改进路线图。
> 配套文档：《白蓝白红博弈推演》(`docs/adversarial_game_2026-06-24.md`)，对本报告的核心结论做对抗式压力测试。

---

## 0. 执行摘要（给决策者）

**一句话结论**：系统的业务逻辑成熟、工程约束（宪法）扎实，但**韧性（resilience）落后于功能**。近期"发布数量与质量骤降"不是单点 bug，而是**一个反复出现的架构缺陷类**的集中爆发——**运行环境脆弱性**：关键子进程依赖"调用者恰好拥有正确的 PATH/环境"，一旦由 cron 这类最小环境拉起就静默失效。

**最具说服力的证据（2026-06-23 当日实测）**：同一类根因，在**三个不同位置**各自造成一次生产事故：

| # | 位置 | 现象 | 根因（同一类） |
|---|---|---|---|
| 1 | `monitor_channels.py` 发现 | 频道发现每轮全灭、被吞成"无新视频" | cron 最小 PATH 找不到裸 `yt-dlp`（`monitor.log` 累计 1555 条 `FileNotFoundError`）|
| 2 | `pipeline_manager` 下载 | 高分视频"format not available"下载失败 | cron 最小 PATH 找不到 `deno` → yt-dlp 解不了 YouTube n-sig 挑战 |
| 3 | 历史 v2.5.0 | Feature Flags 全部回退 False、密钥失效 | cron `cwd != project_root` 时相对路径 `.env` 加载失败 |

三者根因同构：**"代码隐式假设了一个富环境（交互 shell / dashboard 进程），而真正的生产触发器（cron）是贫环境。"** 这是本报告的主线。

**Top 风险（按"爆炸半径 × 发生概率"）**：

| 级别 | 风险 | 爆炸半径 | 今日状态 |
|---|---|---|---|
| 🔴 P0 | 运行环境脆弱性（PATH/env 隐式依赖） | 整条发现+下载链路 | **已修 3 处**，但缺**机制性防线**（见 §3.A）|
| 🔴 P0 | 微信单账号会话 = 发布唯一出口 | 会话一过期，全部发布停摆 | 今早即发生（2 条高分卡 LOGIN_REQUIRED）|
| 🔴 P0 | 静默失败：失败被伪装成"正常空结果" | 故障潜伏数天无人知 | 1555 次失败无任何告警 |
| 🟠 P1 | 外置卷 `/Volumes/EXT2T` 承载 DB + 全部产物 | 卷掉线=全业务中断 | 结构性 |
| 🟠 P1 | Dashboard 单进程托管全部调度线程 | 进程退出=自动化全停 | 结构性 |
| 🟠 P1 | 评分悬崖 + dateafter 3天 = 发布漏斗自我饿死 | 可发布候选周期性归零 | 结构性 |
| 🟡 P2 | `PipelineManager` 上帝类（~1200 行） | 维护性/回归风险 | 结构性 |

**核心建议**：把工程宪法里已有的"配置单一真相源"原则，**升维成"运行环境单一真相源"**——任何子进程的可执行文件路径、PATH、代理、密钥都必须由 `settings` 显式构造，绝不继承"调用者碰巧有什么"。这一条原则就能根除 P0 中的第 1 类风险。

---

## 1. 系统全景

### 1.1 分层与依赖 DAG（宪法强制单向）

```
scripts/  cli/            ← 操作胶水层（cron / vpanel / bot 入口）
   ↓
pipeline_manager.py       ← FSM 编排器（唯一的业务流大脑）
   ↓
db/  processors/  core/  utils/  validators/   ← 领域层
   ↓
config/settings.py        ← 配置单一真相源（pydantic-settings）
```

**评价**：DAG 方向清晰、有宪法背书、有历史整改（v3.20.0 把 `sys.path.insert(scripts/)` 反向 import 下沉到 `utils.text_utils`）。这是本系统**最值得肯定的架构资产**。

### 1.2 业务状态机（每条视频）

```
PENDING ─►DOWNLOADING─►(COPYWRITING)─►TRANSCRIBING(+RENDERING)─►[CENSORSHIP]─►cover─►PUBLISHING─►PUBLISHED
   │                                                                                    
   ├─►SEGMENTED（父视频被切片后的准终态）
   └─►off-ramp：FAILED / LOGIN_REQUIRED
```
- 每步**断点续跑**：产物已存在且通过校验则跳过。历史多次踩坑于"checkpoint 命中但依赖产物缺失"（封面丝带 label、双语 `.ass`），故现在校验"完整产物集"而非单文件——这是好设计。

### 1.3 控制平面（触发器）

| 触发器 | 周期 | 环境特征 | 备注 |
|---|---|---|---|
| cron：`monitor_channels.py` | 每 6h（00/06/12/18） | **贫环境（最小 PATH）** | 发现 |
| cron：`pipeline_manager` | 每日 09:00 / 21:00 | **贫环境** | 评分+处理+发布 |
| Dashboard 调度线程（`app.py`，:9100） | 秒级轮询 | 富环境（交互启动，PATH 含 homebrew） | 高分≥75 队列触发 |
| WeChat keepalive 看门狗 | ~50–65min | 富环境 | 刷新会话 |
| Web API / Telegram Bot | 人工 | 富环境 | 手动触发/重试 |

> **架构警示**：同一份 `pipeline_manager` 代码，被**贫环境(cron)与富环境(dashboard)双触发**。富环境掩盖了贫环境的 bug——这正是为什么"手动跑能成、定时任务静默失败"，也是本类缺陷极难被发现的根本原因。

### 1.4 数据与配置

- **DB**：SQLite（WAL + 外键级联），`processed_videos` 复合唯一键 `(youtube_id, slice_index)`，`parent_id` 自引用 `ON DELETE CASCADE`。schema 在 `__init__` 自迁移（加列守卫）。
- **DAL**：所有 SQL 封装在 `PipelineDB` 方法内（宪法第 3 条）。
- **配置**：`settings.py` 单例，pydantic-settings，computed_field，Feature Flags 默认 False。

### 1.5 外部依赖

yt-dlp（下载+发现）、Gemini/阿里云MT（翻译）、Whisper（转录）、WeChat Playwright（发布）、Clash 代理（日本节点提速）、Telegram（通知/控制）。**全部为单实例、无冗余**。

---

## 2. 架构优点（必须保留的资产）

1. **工程宪法（CONTRIBUTING.md）真正落地**：配置 SSOT、DAL 封装、依赖 DAG、Mock 红线、修改历史。多数项目只有口号，本项目有执行证据（如 DAG 违规被 v3.20.0 整改）。
2. **断点续跑的 FSM**：失败可从最近 checkpoint 续跑，产物级校验避免"假成片"（v3.17.0 用 ffprobe 验完整性，不只看体积）。
3. **配置单一真相源 + computed_field**：`settings` 把路径/代理/市场窗口判定集中化，复用性强。
4. **审查分层（P0/P1/P2 + 频道策略 + 字幕正文）+ 双语双通道**：翻译失效时英文通道兜底；词库 JSON 热加载、损坏时安全回退默认、**绝不置空审查**——这是成熟的安全姿态。
5. **共享主机的"好邻居"设计**：`is_us_market_guard_window()`（ET 09:15–16:15）让重负载避让同机实盘交易管线，且为单一真相源、被调度器与管线共用。
6. **进程隔离与可控中断**：子进程独立进程组（`os.setsid`）+ PID 跟踪，SIGTERM 可精准击杀整棵进程树而不波及父进程。
7. **服务化解耦进行中（架构 B）**：`scoring.compute_auto_score`、`CensorshipService` 从上帝类抽出并补单测——方向正确。

---

## 3. 系统性缺陷（按主题，含严重度）

### 3.A 🔴 运行环境脆弱性 —— 本系统的"头号架构债"

**症结**：子进程的可执行文件与运行环境，依赖"调用者碰巧拥有正确的 PATH/cwd/proxy"，而非由代码显式构造。

**已实证的三次同类事故**（见 §0 表）。其本质是一个**抽象泄漏**：业务代码假设了富环境。

**今日已打的补丁（治标 + 部分治本）**：
- `settings.ytdlp_path` 计算属性 → 三处裸 `yt-dlp` 改绝对路径；
- 发现命令加 `--ignore-no-formats-error`（元数据不需格式解析）；
- `_build_subprocess_env()` 强制 PATH 注入 `.venv/bin` + `/opt/homebrew/bin`（deno）；
- yt-dlp 升级 2026.03.17 → 2026.06.09。

**仍缺的机制性防线（治本）**：
1. **运行环境 SSOT**：应有唯一的 `settings.build_subprocess_env()` / `settings.tool_path(name)`，所有子进程（发现、下载、上传、CLI 字幕、封面）一律经它构造，禁止任何地方裸调外部命令或继承环境。今日只覆盖了下载与发现，**上传、cli.main、cover_generator 等仍是隐患面**。
2. **环境自检（fail-fast）**：进程启动时校验 `yt-dlp/deno/ffmpeg/.venv/.env` 可达，缺失则**显式报错 + Telegram 告警**，而非运行到一半静默失败。
3. **cron 加固**：crontab 顶部声明 `PATH=` 兜底（注意该 crontab 与同机 Futu 任务共用，改动需谨慎）。

> **建议把宪法第 2 条"配置单一真相源"扩写为"配置与运行环境单一真相源"**，把"禁止业务层裸调 `os.getenv`"扩展为"禁止业务层裸调外部可执行文件 / 继承隐式 PATH"。

### 3.B 🔴 单点故障（SPOF）集群

| SPOF | 失效后果 | 现状 | 建议 |
|---|---|---|---|
| **微信单账号会话** | 发布唯一出口，会话过期=全部发布停摆 | 今早实发：2 条高分卡 LOGIN_REQUIRED；keepalive 默认需手工启用 | ①keepalive 默认开 + 启动自检；②会话将失效**提前**告警（剩余时效预测），而非失效后才告警；③评估备用账号池（合规前提下） |
| **外置卷 `/Volumes/EXT2T`** | 承载 DB + WAL + 全部产物，卷掉线=全业务中断、DB 锁异常 | 结构性 | DB 迁本机 SSD（产物可留外置卷）；或定时 `wal_checkpoint` + 卷健康探测告警 |
| **Dashboard 单进程** | 秒级调度、keepalive、队列触发全挂在一个 Python 进程的 daemon 线程上；进程退出=自动化全停，无自愈 | 结构性 | 改 launchd/supervisor 守护 + 自动重启；或将调度与 Web 解耦为独立服务 |
| **单代理 / 单 Clash 节点** | 下载/翻译走代理，节点轮换或 Clash 宕机即失败 | 有 TCP 探测降级，但无备用节点池 | 多节点池 + 探测失败重试；Clash API 不可达时显式告警 |
| **单 yt-dlp cookie 文件** | cookie 失效→限流/bot-check；失败后仍重试同一坏 cookie | 无 TTL、手工维护 | cookie 健康探测 + 失效快速熔断 + 自动刷新流程 |

### 3.C 🔴 可观测性缺口与"静默失败"

**最危险的反模式**：失败被伪装成"正常的空结果"。
- 发现脚本 yt-dlp 失败 → 返回空 → 调度器当成"无新视频"→ **故障潜伏数天**（1555 次失败零告警，直到人工发现发布量下降）。
- 这类"沉默不等于成功"的盲区遍布外部依赖边界。

**建议**：
1. 每个外部调用边界检查 returncode 并区分"真空结果"与"失败"；失败必发 Telegram。
2. 关键漏斗指标（每日发现数、过门数、发布数、各状态计数）落"心跳表"，**连续 N 小时无 PUBLISHED 自动告警**。
3. 结构化日志（带 video_id 追踪）替代纯文本，便于跨步骤串联。

### 3.D 🟠 调度与并发

- **双触发掩盖 bug**（见 §1.3）：cron 与 dashboard 双跑，富环境掩盖贫环境缺陷。建议统一为"单一调度真相源"，并让两条路径走**完全相同的环境构造**。
- **子进程无超时**（待核实但高度可疑）：`_run_pipeline_manager` 若用 `subprocess.run` 无 `timeout`，一旦 yt-dlp/Whisper 永久 hang，队列永久堵塞。建议所有子进程加超时 + 僵尸收割。
- **盘中保护的轮询窗口**：秒级轮询在 16:15 ET 临界点附近仍可能拉起任务，轻微抢占实盘 CPU。可改为更短轮询或事件驱动。

### 3.E 🟠 质量漏斗会"自我饿死"

两个独立设计叠加，导致可发布候选周期性归零：
1. **评分悬崖**（`compute_auto_score`）：要么"过门"得 80–95，要么"没过"≤70，**71–79 是空档**——发布线 75 变成二元判定。
2. **`--dateafter now-3days`**：只发 3 天内新片，而新片往往还没攒够 `views>1500 & 点赞率>3%` 的热度门槛。

二者叠加 → 即便发现端正常，"够新且够热"的交集也极小。这既压数量，也压质量（在热度未验证前抢发投机内容）。**这属于产品/策略参数，建议由人决策**（见配套博弈文档"评分悬崖"战役），可选项：放宽 dateafter 到 7 天、给评分曲线加 71–79 过渡区、对频道轮询与关键词搜索采用不同时窗。

### 3.F 🟡 上帝类与隐藏状态

- `PipelineManager`（~1200 行）仍承担 FSM 编排 + 字幕样式 + TTS 决策 + 进程管理 + GC + 缓存判定。架构 B 已抽出评分/审查，**应继续抽出**：缓存/checkpoint 管理器、下载器、GC 策略。
- **模块级 `_sigterm_received` 全局标志**靠"每视频手工重置"保证正确性——隐藏状态，易回归。建议封装进每次处理的上下文对象。

### 3.G 🟡 数据/状态完整性

- **WAL checkpoint 自管理**：长期高并发下 `-wal`/`-shm` 可能膨胀，建议定期 `wal_checkpoint(RESTART)`。
- **复合键查询易漏 `slice_index`**：多数查询默认 `slice_index=0`，切片任务易查错父行；建议关键查询将其设为显式必填。
- **安全面**：`wechat_state.json` 明文存登录 cookie；Web API 无鉴权/限流；密钥（Clash secret、TG token）明文 env。属内网部署可接受，但应纳入风险登记。

---

## 4. 改进路线图（分级）

### P0（立即，1–2 周）—— 根除"环境脆弱性"与最致命 SPOF
1. **运行环境 SSOT**：实现 `settings.build_subprocess_env()` 与 `settings.tool_path()`，**全量**替换所有外部命令调用（含上传、cli、cover）。
2. **启动环境自检 + 失败告警**：缺 deno/yt-dlp/ffmpeg/卷不可达 → fail-fast + Telegram。
3. **外部调用边界"非空≠成功"改造**：returncode 检查 + 失败 Telegram；发布漏斗心跳表 + "N 小时无 PUBLISHED"告警。
4. **微信会话韧性**：keepalive 默认开 + 启动自检 + 会话**预警式**告警（失效前提醒）。

### P1（1 月内）—— SPOF 收敛与漏斗修复
5. **DB 迁本机 SSD**（产物留外置卷）+ 卷健康探测。
6. **Dashboard 调度守护化**（launchd/supervisor 自动重启），或调度与 Web 解耦。
7. **所有子进程加超时 + 僵尸收割**。
8. **质量漏斗策略评审**（dateafter 时窗、评分过渡区）——产品决策后实施。

### P2（季度内）—— 可维护性与纵深
9. **拆分 `PipelineManager`**（缓存/下载/GC 子模块），消除全局 `_sigterm_received` 隐藏状态。
10. **代理/cookie/Clash 节点池化 + 健康探测 + 自动切换**。
11. **WAL checkpoint 定期任务**；复合键查询 `slice_index` 显式化。

### P3（持续）—— 安全与运维
12. `wechat_state.json` 加密 + 权限收紧；Web API 增加最小鉴权/限流；密钥纳入轮转计划。
13. 结构化日志 + 日志轮转；漏斗指标可视化面板。

---

## 5. 附录：今日（2026-06-23）已修复项 —— 作为"环境脆弱性"模式的实证

| 修复 | 文件 | 性质 |
|---|---|---|
| `ytdlp_path` 单一真相源 | `settings.py` | 治本（局部）|
| 三处发现命令绝对路径 + `--ignore-no-formats-error` | `monitor_channels.py` | 治标+治本 |
| `_build_subprocess_env` 强制 PATH 含 deno | `pipeline_manager.py` | 治本（局部）|
| block2 频道发现 `--flat-playlist`（60s 超时→3.5s）| `monitor_channels.py` | 性能 |
| yt-dlp 升级 2026.03.17→2026.06.09 | venv | 依赖卫生 |
| 重提 4 条 cron 误杀的高分视频，3 条已发布 | DB（DAL） | 数据修复 |

> 这些修复证明了主线判断：**只要把"环境"当成一等架构关注点、用 SSOT 显式构造，整类故障即可根除。** 本报告的 P0 第 1 项就是把这些零散补丁升级为机制。

---
*（本报告中标注"待核实"或来自子代理探查的具体行号，建议在实施前以代码为准二次确认；架构级结论均有当日实测或代码直读支撑。）*
