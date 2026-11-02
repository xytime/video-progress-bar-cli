# 视频号商品池与 L1 内容匹配：实施及受控采用记录

作者：Codex。日期：2026-11-02（北京时间）。本报告对应用户已确认规格。

代码、隔离验证、受控重启和每日调度已完成；**真实自动采集未通过验收，业务挂载率提升待观察**。真实只读尝试未取得可验证清单，旧目录没有续期。当前严格商品池为空，新 AUTO 安全不挂商品，不能把历史假设匹配当成当前可挂载结果。

## 提交与工作区保护

- `ce0bec161f3edac3dcb782e42c634c0f353fa35e` — `feat: sync verified product pools and freeze L1 content matching`，已推送 `origin/main`。
- 本报告另作仅文档提交；最终提交号见交付回复及 Git 历史。
- 生产实际目录为 `/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing`，在 `main` 实施。未在会话 detached worktree 切换生产分支。
- 基线 60 个既有 tracked dirty 文件中，59 个字节摘要原样；唯一重叠的账号调度文件，剥离本任务 6 行后与基线逐字相同。未整文件纳入他人改动、未 reset/stash 或覆盖其它工作。
- 没有读取/编辑 `.env` 或输出凭证，没有写回登录态，没有向外发消息，没有为验收新增发布或重传历史任务。

## 本任务维护与运行采用

他人字幕任务的 MAINTENANCE v289 恢复 RUNNING v290 后，才进入本任务维护。没有接管、恢复他人的维护窗。

| 项目 | 北京时间 / 证据 |
| --- | --- |
| 本任务进入 | 2026-11-02 12:42:18.822580，MAINTENANCE v291 |
| 原因 | 商品池只读同步与L1内容匹配：7天TTL、独立预算、冻结重放与受控采用 |
| 恢复 | 2026-11-02 13:09:56.937573，RUNNING v292 |
| 采用目标 | `ce0bec161f3edac3dcb782e42c634c0f353fa35e`，连同保留的生产 dirty 经隔离源码清单核验 |
| 运行源码 SHA-256 | `094f849ecd76fba3518005ae4857c03f57cd0dac42b54bd768a577f3561ad2b2` |
| 原生部署日志 | `/Users/ryusei/.codex/tmp/product-pool-20261102/restart`，9 步 COMPLETE |
| 调度 | 每日本机 07:35；核验时主机 CST +0800；原 cron/launchd 全量恢复并登记运行意图 |
| cron SHA-256 | `d494e8e41c250e3aec736a53b5fab0a1315fabb87e7106b92d3bbc7433c70774` |

原生停止前核对账本无在途、PID/birth、内核角色锁及上次完整部署来源。旧 ready-worker 仅收到一次 SIGTERM；正常等待返回 STOP_TIMEOUT，随后确认是已退出但尚未由父进程回收的 zombie，birth 查询已不存在且角色锁释放，记录后继续；未补发信号。退役证据在 `/Users/ryusei/.codex/tmp/product-pool-20261102/worker-retirement`。原生重启有一致性 SQLite 备份、源码清单校验、启动与最终回读；全部调度在恢复 RUNNING 前恢复。

## 真实同步与当前商品池

| 项目 | 结果 |
| --- | --- |
| 真实单次开始/结束 | 2026-11-02 13:10:09.865121 / 13:10:15.110238 |
| 实际耗时 | 5.245 秒 |
| 尝试结果 | `PARTIAL`，`CATALOG_EMPTY_OR_UNSUPPORTED`，`live_verified=false` |
| 尝试取得的完整页/可提升条目 | 0 / 0；此代码表示空列表或尚不支持的公开 DOM，不能据此判断橱窗真实为空 |
| 当前目录 captured_at | `2026-10-10T15:54:10.031842+08:00`，未更新 |
| 当前目录 | v1，14 条，`completeness=unverified`，账号未知，`live_verified=false` |
| 当前有效/排除 | 0 / 14；首个门禁原因 `CATALOG_STALE: 14`，不重复计算多重原因 |
| TTL | 604800 秒（7 天） |
| 目录原始 SHA-256 | `2ddc752e78d17476f6b0bb5d68dd9d98c0a52e7fb41df04fb487541a7c253b3f` |
| live 采集凭证 | 无；未为旧资料生成新凭证或修改历史采集时间 |

真实回执：[只读同步尝试回执](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output/wechat_catalog_sync/1793596209865116000/receipt.json)。失败按独立预算留存，没有自动重试；下一次日常调度为 2026-11-03 07:35。本次无法证明公开 DOM 提供稳定账号、总数和完整分页，**不能宣称自动采集成功**。若后续仍无法取得证据，按批准规格保留人工 v2 导入；单纯导入不自证 live，新 AUTO 继续关闭商品候选。

同步默认滚动 24 小时最多 2 次、最短间隔 6 小时；启动与采集共用 60 秒上限并预留清理时间，最多 20 页。同步额度独立于旧六类操作池和 30 秒选品预算；维护、账号退避、登录失效、物理会话锁、发布优先级继续生效。未实际压测硬超时或平台限流，不以这次 5.245 秒结果推断所有平台响应的时长。

## 匹配行为与回执

新 AUTO 采用 `wechat-product-content-match-v1`，取消点赞率硬门槛；标题 4、对白字幕 2、主题/标签 2、分类支持 1，每字段最多两个不同特定短语，重复不累分。最低 4 分且有商品特定主题命中；最多 3 个精确身份、总尝试次数含技术重试，仍服从选品/清理共享 30 秒预算。无候选写 `MATCH_EMPTY`，不回退通用书。本期没有 LLM、付费调用或新供应商。

普通任务保留人工 NONE/PRODUCT；英语世界沿用已确认的专属优先合同，但快捷英语同受账号、TTL、可售、精确身份约束，失败后只可使用相关性合格的 L1 候选或安全无商品。显式 require_bound 仍要求实际绑定。旧冻结任务不重算；执行时最新负面证据只能否决，不能替换原候选。

冻结记录绑定内容来源/版本/digest、匹配配置和分数理由、目录 digest/age/TTL、采集凭证 digest。普通成片只读取自身标题及 ASS 对白；分片不借父片字幕；英语包读取审核哈希绑定的本分片清单和时间线。表单 ID+完整标题实读保持必要条件。

## 隔离测试

425 个单元测试 + 61 个真实 Chromium 测试通过；0 失败、0 错误、0 跳过。两次测试的完整生产源码清单 SHA-256 均为 `59cee41dba42cf10d0669a2b9dfdd86c3d7779a4c79268b2abdc6229a8919c1e`，与采用计划一致。

```sh
.venv/bin/python scripts/run_isolated_tests.py -- -q tests/unit/test_wechat_product_*.py tests/unit/test_wechat_catalog_import.py tests/unit/test_wechat_catalog_schedule.py tests/unit/test_product_final_receipts.py tests/unit/test_english_preferred_product.py tests/unit/test_wechat_publish_policy_20261025.py tests/unit/test_wechat_operations_policy.py tests/unit/test_deployment_schedules.py tests/unit/test_deployment_host.py
.venv/bin/python scripts/run_isolated_tests.py --browser -- -q tests/browser/test_wechat_product_picker_browser.py tests/browser/test_wechat_product_catalog_browser.py
```

单元证据：[425 项回执](/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/video-pytest-t9_hiwxg/receipt.json)；浏览器证据：[61 项回执](/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/video-pytest-3oiw6urq/receipt.json)。Chromium 148.0.7778.96 / revision 1223。包括分页异步等待、缺失账号/总数、重复与变化、超时、页预算、原子提升、旧目录归档和只读动作计数为 0；这些是隔离模拟网页，不是平台采集成功的证据。

## 20 条历史跳过任务离线回放

在真实尝试后于 13:10:36 重跑。严格当前池 **0/20（0%）会尝试挂载**，全部 `CATALOG_STALE`。历史假设忽略 TTL、live 与当天可售证据，仅帮助解释 L1：2/20（10%）有合格相关候选，另 18 条 MATCH_EMPTY；不计作当前命中率或绑定能力。

每条输入均带本地成片标题、对应 ASS/公开源元数据及其路径、字节数和 SHA-256；完整内容证据、逐商品分数和命中词见 [回放 JSON](/Users/ryusei/.codex/visualizations/2026/11/02/01a19a72-07e5-7701-b4e7-d409b8e35bad/product-pool/replay-results.json)。输入 SHA-256：`99d71bd4ebe46f9c62f12417ccf9e1d9051d9abd0e926a5d412540773049630e`。回放不修改生产 DB、旧决定或回执。

| 任务 ID | 标题 | 原原因 | 严格当前池 Top1 / 尝试 | 历史假设 Top1 / 规则理由 |
| --- | --- | --- | --- | --- |
| `pipeline:TH3ajuWSqF4:0` | 特朗普难说服选民 | `SKIP_BELOW_THRESHOLD` | 无 / 否（CATALOG_STALE） | 无；MATCH_EMPTY |
| `pipeline:AvyHU0m8vdE:0` | 美国高房价与诱导利率 | `SKIP_BELOW_THRESHOLD` | 无 / 否（CATALOG_STALE） | 无；MATCH_EMPTY |
| `pipeline:c7mY3lsfGJM:0` | 数学如何塑造民主 | `SKIP_BELOW_THRESHOLD` | 无 / 否（CATALOG_STALE） | 无；MATCH_EMPTY |
| `pipeline:SzNTvqvxswM:0` | 别让择偶标准挡住爱情 | `SKIP_BELOW_THRESHOLD` | 无 / 否（CATALOG_STALE） | 无；MATCH_EMPTY |
| `pipeline:sWFCOLjp2cI:0` | 币安热钱包被盗与冻结 | `SKIP_BELOW_THRESHOLD` | 无 / 否（CATALOG_STALE） | 无；MATCH_EMPTY |
| `pipeline:C0ysAy2LXjY:0` | 加州富豪税争议 | `SKIP_BELOW_THRESHOLD` | 无 / 否（CATALOG_STALE） | 无；MATCH_EMPTY |
| `pipeline:w21d64pB9jk:0` | 科技股抛售与币安被盗 | `SKIP_BELOW_THRESHOLD` | 无 / 否（CATALOG_STALE） | 股市趋势技术分析（10000028955239），6 分；subtitle:股市,股票；topics:stock market |
| `pipeline:LxCqqKwqeCo:0` | 英特尔股价单日重挫 | `SKIP_BELOW_THRESHOLD` | 无 / 否（CATALOG_STALE） | 股市趋势技术分析（10000028955239），4 分；subtitle:股票,证券交易 |
| `pipeline:F8Y7IigdTHA:0` | 得州参议员选情走访 | `SKIP_BELOW_THRESHOLD` | 无 / 否（CATALOG_STALE） | 无；MATCH_EMPTY |
| `pipeline:SqwiCJ8r8_Q:0` | 合唱中的归属感 | `SKIP_BELOW_THRESHOLD` | 无 / 否（CATALOG_STALE） | 无；MATCH_EMPTY |
| `pipeline:M1xyX3ZQJ6k:0` | 微软向六万人提供离职方案 | `SKIP_BELOW_THRESHOLD` | 无 / 否（CATALOG_STALE） | 无；MATCH_EMPTY |
| `pipeline:rAJXUWjhHt8:0` | 尸检如何帮助活人 | `SKIP_BELOW_THRESHOLD` | 无 / 否（CATALOG_STALE） | 无；MATCH_EMPTY |
| `pipeline:UGisxZs1Av4:0` | 人工智能伦理危机 | `SKIP_BELOW_THRESHOLD` | 无 / 否（CATALOG_STALE） | 无；MATCH_EMPTY |
| `pipeline:98MJXtcgEjc:0` | 女孩为何彼此竞争 | `SKIP_BELOW_THRESHOLD` | 无 / 否（CATALOG_STALE） | 无；MATCH_EMPTY |
| `pipeline:r2xjrq_e62k:0` | 麦肯蒂填补社区缺口 | `SKIP_BELOW_THRESHOLD` | 无 / 否（CATALOG_STALE） | 无；MATCH_EMPTY |
| `pipeline:UHmZl3PiOj0:0` | 熬夜并不等于努力 | `SKIP_BELOW_THRESHOLD` | 无 / 否（CATALOG_STALE） | 无；MATCH_EMPTY |
| `pipeline:ZVGS33A0nK0:0` | 萨莉谈民主为何失灵 | `SKIP_BELOW_THRESHOLD` | 无 / 否（CATALOG_STALE） | 无；MATCH_EMPTY |
| `pipeline:ZnD_l263eB4:0` | 校园霸凌为何发生 | `SKIP_BELOW_THRESHOLD` | 无 / 否（CATALOG_STALE） | 无；MATCH_EMPTY |
| `pipeline:p-nVeVG48FY:0` | 人工智能与人类创造力 | `SKIP_BELOW_THRESHOLD` | 无 / 否（CATALOG_STALE） | 无；MATCH_EMPTY |
| `pipeline:jnJX5Q9QJgQ:0` | 无感技术如何托起购物 | `SKIP_BELOW_THRESHOLD` | 无 / 否（CATALOG_STALE） | 无；MATCH_EMPTY |

历史假设 Top1 的精确完整标题：`股市趋势技术分析10版爱德华兹原书第10版金融投资策略股票入门基础知识指标价值投资书籍书新华文轩旗舰店正`，ID `10000028955239`。两条均为规则相关性分数，不能当作概率。

```sh
.venv/bin/python scripts/replay_wechat_product_matches.py --input /Users/ryusei/.codex/visualizations/2026/11/02/01a19a72-07e5-7701-b4e7-d409b8e35bad/product-pool/replay-inputs.json --output /Users/ryusei/.codex/visualizations/2026/11/02/01a19a72-07e5-7701-b4e7-d409b8e35bad/product-pool/replay-results.json --historical-hypothesis
```

## 自然发布观察与剩余问题

截至 13:12:23，恢复 RUNNING 后的新合同选品流程回执 **0**，BOUND **0**，尝试流程 **0**，实际商品尝试 **0**，安全无商品 **0**；BOUND/总流程及 BOUND/尝试流程均为 0/0，不可计算。尚未满足至少 10 次自然发布的观察要求，标记 **待观察**。没有为了样本新增投稿、重传历史 UNCERTAIN 或修改旧冻结决定。

历史近 14 天选品回执为 9/129=6.98% BOUND、尝试子集 9/10；它是对照背景，不能替代本期样本。选品 BOUND、平台受理/审核、作品管理回读和公开播放页商品展示分别需要证据；本轮没有新增这些发布与公开展示证据。

剩余验收：在预算内确认真实公开商品 DOM 的空态/布局及稳定账号、总数、分页证据；取得完整可信清单后，再用自然新流程观察至少 10 次并分别报告绑定与平台回读。本次不绕过预算、不猜私有 API、不以旧资料续期。

## 经核实不成立或需修正的背景假设

- 当前默认链为《人生只有一件事》，并非《思考快与慢》；后者库存为 0 属实。
- `product_topic=AI` 已参与旧粗分类，不能说完全没用；缺的是标题/对白相关性打分。
- 全历史 34/38 的分母遗漏了 4 条已尝试但 BLOCKED；含这些记录应为 34/42。两者都不是公开发布成功率。
- v2 完整人工导入本身不等于 live；不能通过改日期或 source 字段把旧资料变成今日库存。
- 新目录里出现的商品不会自动变成有相关性标签的商品；没有特定主题资料就不凭泛分类强配。

## 修改文件（功能提交 22 个）

| 路径 | 用途 |
| --- | --- |
| [.env.example](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/.env.example) | 声明 TTL、独立同步额度/间隔、超时和页数配置。 |
| [src/config/settings.py](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/config/settings.py) | 提供对应 5 项 typed settings，默认 7 天/2 次/6 小时/60 秒/20 页。 |
| [src/config/wechat_operations_schema.py](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/config/wechat_operations_schema.py) | 登记“商品同步”用途，既有六类操作池不变。 |
| [src/video_processing/core/wechat_account_schedule.py](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/core/wechat_account_schedule.py) | 为同步派生独立预算；仅提交本任务 6 行，保留同文件既有 dirty。 |
| [src/video_processing/core/deployment_schedules.py](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/core/deployment_schedules.py) | 维护排空、快照、CAS、cron 全量回读和运行意图登记。 |
| [src/video_processing/core/wechat_product_matching.py](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/core/wechat_product_matching.py) | 可重放的 L1 特定主题评分、稳定排序、身份去重及英语优先。 |
| [src/video_processing/utils/wechat_product_pool.py](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/utils/wechat_product_pool.py) | 完整/live/同账号/TTL/可售/人工停用门禁及目录凭证归档提升。 |
| [src/video_processing/utils/wechat_product_collector.py](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/utils/wechat_product_collector.py) | 公开可见商品弹窗只读分页；缺账号、总数、完整分页则不提升。 |
| [src/video_processing/utils/wechat_product_sync.py](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/utils/wechat_product_sync.py) | 一次同步的维护准入、会话锁、独立预算、总超时及失败回执。 |
| [src/video_processing/utils/wechat_product_content_task.py](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/utils/wechat_product_content_task.py) | 对应成片/分片内容提取、冻结输入及摘要、版本校验与回执字段。 |
| [src/video_processing/utils/wechat_product_task.py](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/utils/wechat_product_task.py) | 新 AUTO 路由至新合同，旧冻结任务原样返回，保留普通人工意图。 |
| [src/video_processing/utils/wechat_product_execution.py](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/utils/wechat_product_execution.py) | 执行前/最终回读校验当前负面证据及账号，回执写入匹配摘要。 |
| [scripts/submit_english_world_review.py](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/scripts/submit_english_world_review.py) | 传递已审核包哈希绑定的标题与清单证据。 |
| [scripts/sync_wechat_product_catalog.py](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/scripts/sync_wechat_product_catalog.py) | 单次真实只读同步及纯本地 --status 入口。 |
| [scripts/manage_wechat_catalog_schedule.py](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/scripts/manage_wechat_catalog_schedule.py) | 维护窗安装受管每日 07:35 调度。 |
| [scripts/replay_wechat_product_matches.py](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/scripts/replay_wechat_product_matches.py) | 严格当前池和历史假设分栏回放，不修改生产任务。 |
| [config/wechat_product_matching.json](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/config/wechat_product_matching.json) | 15 个精确商品身份及双语主题，启用新 L1，最低分 4。 |
| [tests/unit/test_wechat_product_content_match.py](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/tests/unit/test_wechat_product_content_match.py) | TTL、可售、冲突、冻结重放、内容证据、人工/英语和执行门禁测试。 |
| [tests/unit/test_wechat_catalog_schedule.py](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/tests/unit/test_wechat_catalog_schedule.py) | cron 快照、CAS、完整回读与用途独立性测试。 |
| [tests/browser/test_wechat_product_catalog_browser.py](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/tests/browser/test_wechat_product_catalog_browser.py) | 真实隔离 Chromium 分页、异步加载、原子归档与只读动作断言。 |
| [docs/specs/wechat-product-pool-content-match-2026-11-02.md](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/specs/wechat-product-pool-content-match-2026-11-02.md) | 用户批准规格、事实核验、边界及验收标准。 |
| [docs/workflows/wechat-product-pool-content-match.md](/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/workflows/wechat-product-pool-content-match.md) | 日常命令、预算、合同、失败处理、验收及回滚操作说明。 |

本报告为第 23 个本任务文件（仅文档提交）。运行回读摘要：[受控采用回读 JSON](/Users/ryusei/.codex/visualizations/2026/11/02/01a19a72-07e5-7701-b4e7-d409b8e35bad/product-pool/adoption-readback.json)。
