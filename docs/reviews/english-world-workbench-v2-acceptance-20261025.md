# 英语世界桌面工作台 v2 验收记录

日期：2026-10-25
状态：已实施、r4 最终修订已采用，隔离验证与线上验收完成；外部平台受理/公开状态未核验。

## 后续复核更新（12:56 +08:00）

下文的 27 failed / 6 errors 保留为当时记录。相邻修复 `e1cbccf` 已通过 191 项浏览器、130 项 Python 回归，原始回执分别为 `video-pytest-s9yxf856`、`video-pytest-it5yj5p9`，并已受控采用。本轮又修复人工 job 关联复核项的错误投稿派发身份及不可执行队首阻塞，提交 `4a78b29` 已采用，164 项专项与 98 项浏览器测试通过。主列表、商品设置和工作台的旧回归失败不再属于当前未解决项。完整范围、证据与后续策略规格见 [两日需求与实现复核](requirements-implementation-review-20261024-25.md)。未重试历史投稿，外部平台状态仍未核验。

## 验收基线

本次按已确认的 [v2 规格](../specs/english-world-workbench-v2.md) 实施，采用经审查的 Superdesign v10 草图。目标是将 `/english-world` 从只读混合列表改为可处理业务任务的工作台：任务与定时运行分开，待办不截断，运行身份可追溯，动作由服务端资格判定并审计。

规格边界包括：任务搜索及组合筛选、历史与分页；研究、候选选择、制作确认、审核和质量证据；受限媒体访问；安全续做及人工登记投稿结果。运行记录不能算作业务待办；缺失或不匹配的身份不能拼接证据；未知投稿状态不得重发；工作台按钮不绕过服务端授权、CAS、幂等和安全闸门。

## 实现链路与安全边界

- 查询层分别呈现任务、审核项、运行记录及历史分页；支持任务 ID、标题和来源查询以及状态、触发方式、日期范围组合。运行记录与业务待办分开计数。
- 任务详情聚合当前步骤、证据和动作资格。报告摘要须先与当前产物绑定；绑定失败时不展示可采纳的问题摘要。媒体接口按任务和媒体类型读取，不接受任意路径。
- 写操作使用已验证会话、同源及 CSRF 校验；操作者从会话派生，不采信请求体 actor。动作带 revision/CAS 和 operation id 幂等键；重放返回原回执，冲突或未完成操作失败关闭。
- 日常运行写入明确 run identity、attempt/workspace/stage 关联；按固定 run-log 与 identity sidecar 配对，不通过最近时间、同标题或目录扫描猜测身份。不能明确配对的历史记录保留为未绑定状态。
- 工作台安全续做限定为原生产交付请求、身份与输入哈希一致、宿主明确记录 `FAILED_BEFORE_NOTIFIER` 且 `notifier_started=false`、没有受理或不确定投稿记录，并受锁、维护态、原预算及执行器资格约束。入口强制人工审核模式，不自动投稿。普通旧续做语义保持独立。
- 人工公开结果登记要求权威身份匹配证据，只记审计和核验状态，不调用投稿或“确认未投稿后重试”路径。测试均在隔离数据库、夹具和受控执行器中。本轮未触发真实业务研究、制作、投稿或外部平台访问；首轮部署包含生产迁移与备份写入，因此不表述为“未写任何生产数据”。

## 测试与可复核证据

下列目录均为隔离测试 runner 生成的回执目录，包含 `receipt.json`、`pytest.log`、`pytest.xml`、源清单和边界探针记录。runner 在临时快照中执行；退出码 0 的记录仅证明相应隔离测试通过。线上采用及只读回读另由 r4 部署回执和最终回读文件证明。

| 范围 | 结果 | 证据目录 | 说明 |
|---|---:|---|---|
| 英语世界专项 unit/contract/recovery 等隔离回归 | 283 passed / 0 failed / 8 warnings | `/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/video-pytest-uzzsfut8` | 最终冻结源的11个英语世界相关模块，包含任务状态、动作幂等、安全续做、投稿保护、运行身份与计划时刻。source-manifest SHA256：`a6b62283b91e130e8f2727e7a0a9ca39b67034e9a47d2d84164aa97091494d30`。 |
| 工作台浏览器场景 | 8 passed | `/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/video-pytest-6nb047nd` | 最新浏览器回归覆盖资源版本补丁 `edc0f60`；source-manifest SHA256：`a98131c31f69ecd867453824138ea2db5d84376bf72cb49cb075f96ad599defd`。旧 WebView 刷新后复用旧资源的问题已修复，页面 CSS/JS 使用 `?v=20261025-workbench-3`。 |
| 真实媒体端点与浏览器读取 | 包含于浏览器场景 | 同上 | 使用小型隔离MP4/PNG，经真实TestClient+DB和媒体路由验证Range 206、视频元数据/拖动及封面加载；属于隔离媒体链路。 |
| 严格设计审计 | 0 errors / 0 warnings | `premium-audit.json`（不提交生成文件） | 最终审计为 strict；1366×768、1440、大字号、三主题和窄屏截图保留在浏览器回执sandbox内；主代理已目视复核1366首屏。 |

最终浏览器复查确认：时区统一、诊断默认折叠且可展开、三行 grid 避免 footer 遮挡、筛选 chip 使用中文。运行记录不计入任务数由线上 API 回读与专项契约测试共同验证，不归因于浏览器用例。

曾有两项1秒超时测试出现fake协调器启动竞态：runner正确返回124，但`env bash`尚未写启动记录。测试夹具改为直接`/bin/sh`记录后执行休眠，保留1秒预算和全部断言，未修改runner超时语义。调整后的scheduler完整回归67 passed，回执`video-pytest-nibpimp8`；最终专项再包含这些用例。

### 首轮采用与真实只读回读

- 首轮采用版本为 `cc8fca1`；实现修订 `1c32d76` 已由 r2 采用；最终资源版本 `edc0f606e3bbd35f0127545a413494cc8ec4d90d` 已由 r4 完成采用。最终回读文件为 `/Volumes/EXT2T/AppDataOffload/ryusei/english-world-workbench-deployment-20261025-r4/final-readback.json`。
- 已核验真实审核项 `review:82d…`，标题为“TD投资教育月”，本地提交状态为 `UNCERTAIN`，没有原生平台 ID。该记录未被登记为公开或已受理。
- 该任务真实 MP4 可加载，时长 36 秒；播放器可拖到 18 秒并播放、暂停。封面 SHA 与当前任务记录一致。
- 语言报告显示实际 P1 问题；历史 `PASS` 与 `review_state=FAIL` 同时保留，工作台没有改写旧 QA 记录。
- 旧 07:49 定时运行仍标为关联不足，没有把候选或阶段失败按视频/时间猜到该运行。
- 真实查询只读回读：标题命中 1 条、任务 ID 命中 1 条、来源 BNN 命中 35 条；来源+失败组合命中 1 条，再加人工触发条件为 0 条；清除条件恢复 93 条。
- 全部任务共 93 条；第 2 页显示 20 条，首条为 `review:a24b830ae71f41549ff83a8839406d53`。浏览器点击下一页并 reload 后，URL 保留 `page=2`、页码显示 `2/5`，首条记录仍一致。
- 日期范围只读验证：真实 API 使用 `date_from=2026-10-25&date_to=2026-10-25` 返回 1 条 `review:d4c6aa3a744240b490f5cec6e0bc6e0c`。
- r4 最终 API 回读：总计 93 条、5 页，每页 20 条且无重复；`waiting=57`、`active=0`。标题与 ID 搜索各命中 1 条，来源筛选命中 35 条；全局 `failed+manual` 命中 3 条，限定 BNN 后为 0 条；日期范围仍为 1 条。该计数来自线上只读 API 回读，不以浏览器测试数量代替。
- 最终线上界面确认 CSS/JS 响应哈希与部署磁盘文件一致，页面资源带 `?v=20261025-workbench-3`；真实浏览器 reload 后仍显示失败状态、人工中文筛选 chip 与 0 结果。r4 的 sanitized 回读记录包含页面及 API 核验结果。
- root 在最终 r4 真实页面打开“TD投资教育月”详情，看到 08:29→08:30 阶段；安全诊断默认折叠，正常点击可展开并显示实际提交摘要，正文可滚动且 footer 未遮挡。成片入口加载 0:36 视频，原生进度条从 0:18 播放至 0:27，学习卡和视频画面变化可见；暂停后关闭并成功返回详情。真实封面图片已显示；完整语言报告显示 2 条 P1 与 `review_state: FAIL`，历史 `PASS` 保留。关闭报告返回原入口，关闭详情后焦点恢复到“打开TD投资教育月”。
- 最终审核与投稿时间窗为 `2026-10-25 08:29:20–08:30:14 +08:00`；6 项证据与产物哈希绑定，诊断默认折叠，操作仅为 `record_outcome`。媒体 Range 返回 `206`；旧运行仍为 `HISTORICAL_UNBOUND`。
- 本次没有触发真实业务研究、制作、投稿或平台访问；隔离测试中的 fake research 不产生真实业务任务。首轮部署的迁移及备份属于生产写入，部署采用与业务动作分别记录。

### 相邻全站回归

相邻测试回执 `/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/video-pytest-oxv3613q` 结果为 **129 passed、27 failed、6 errors**（总耗时约 470 秒），不能称为全绿，也不能据此推断工作台测试失败。

从该回执的测试日志看，27 个失败分为两组：13 个在 `tests/browser/test_product_settings_browser.py`，涉及商品设置/商品选择 fixture 与预览断言；14 个在 `tests/unit/test_dashboard_interactions.py`，涉及主列表交互断言。6 个 errors 是主列表流程中相应失败用例的错误报告。失败属于本轮相邻页面/交互范围；当前没有同基线对照，因此不判定为既有问题，也不将其归入工作台验收通过项。后续处理需由 root 按具体断言和目标范围安排。

## 部署与线上验收

- 首轮部署时间、采用版本/提交：**`cc8fca1` 已采用；完成 epoch `1792898759.908513`，即 2026-10-25 11:25:59 +08:00**
- 后续实现修订：**`1c32d76` 已由 r2 成功采用；回执目录 `/Volumes/EXT2T/AppDataOffload/ryusei/english-world-workbench-deployment-20261025-r2`，任务 ID `60507ee6c2c341019bc924f05b48baef`**
- 最终资源版本：**`edc0f606e3bbd35f0127545a413494cc8ec4d90d` 已由 r4 采用。部署目录 `/Volumes/EXT2T/AppDataOffload/ryusei/english-world-workbench-deployment-20261025-r4`，任务 ID `d90dcad68a3b47ef91c9292f6244571f`；9 步全部完成，`pending=null`、`error=null`，完成时间 `2026-10-25 11:42:03 +08:00`（epoch `1792899723.878589`）。r3 仅生成未采用计划，不作为部署记录。**
- 最终运行身份：UI PID `17056`，birth `1792899715.055091`；source hash `79efbd6babbdaaaa4e9c7b5480cfc5823c610c886561eb171d5a53a9b8ad8c36`。native verify 为 `RUNNING/IDLE`，control `OFF`，版本 `v114`。
- sanitized 最终部署与回读证明：`/Volumes/EXT2T/AppDataOffload/ryusei/english-world-workbench-deployment-20261025-r4/final-readback.json`。部署期间曾等待下载/Whisper 在途任务；任务自然结束后核实仅为 `SOURCES_NOT_VERIFIED`，通过受控 recover 继续，未强杀进程或绕过门禁。
- `/english-world` 真实账本、分页/筛选、任务与运行分离，以及身份、阶段事件、报告绑定：**r4 后已完成只读回读**，具体计数与身份边界见上文；任务数排除运行记录由线上 API 回读及专项契约测试支持。
- 线上媒体 Range 读取及封面哈希：**r4 回读确认**；最终真实页面已加载 36 秒成片并验证播放、画面变化、暂停和返回详情；封面真实图片可见。语言报告问题摘要与任务绑定状态按实际报告呈现，历史 QA 未改写。
- 外部平台接受、审核中或公开状态：**未访问平台；`UNCERTAIN` 且无原生 ID，不据此宣称已受理或公开**

首轮、r2 和 r4 部署会产生服务采用、迁移和备份写入；这些事实不等于业务研究、制作或投稿。最终资源采用与核心线上只读回读已完成；外部平台未访问，`UNCERTAIN` 且无原生 ID 的审核项仍不能宣称已受理或公开。以上本地隔离结果不替代线上证据。

## 最终更新记录

已记录冻结源的11模块专项283项通过、8条警告、最新浏览器8场景通过，以及 strict 设计审计0 errors/0 warnings；相邻全站回归为129 passed、27 failed、6 errors，结果单列且无 baseline 对照，不推断为既有失败。`cc8fca1` 首轮、`1c32d76` r2 与最终资源版本 `edc0f606e3bbd35f0127545a413494cc8ec4d90d` r4 均已采用；r4 9步完成、sanitized 最终回读与真实详情/媒体复查均完成。本轮未触发真实业务研究、制作、投稿或平台访问。外部平台受理或公开状态仍未核验。
