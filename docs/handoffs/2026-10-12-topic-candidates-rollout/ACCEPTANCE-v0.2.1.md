# 候选工作台 v0.2.1 隔离开发与验收

责任记录：Codex；2026-10-12（北京时间）。模型版本未单独核实。

**结论：用户确认的维护启动、候选故障隔离和恢复补充已实现，隔离验收通过。生产采用、生产重启及真实搜索均未执行；M17 和 M18 生产观察仍待 A 另行确认。**

确认依据：用户明确“确认 v0.2.1，按补充规格开始隔离开发并完成验收，生产采用另行确认，生产搜索继续保持关闭。”范围以[唯一规格 §11](../../specs/topic-keyword-tracking-architecture.md#11-v021-维护启动故障隔离与恢复验收补充)为准，保留原 v0.2、A01–A21 与 20/40 日预算。不新增候选制作、发布、自动搜索或远程恢复能力。

独立目录为 `/Users/ryusei/.codex/worktrees/2d17/Video-precessing`，分支 `codex/topic-candidate-workbench`。本轮在隔离分支整合生产已提交的商品及 TED 修复，最终基线 `49195acfb5258fbb05fa5fa1f1ac8ea60a6366b9`，包含生产提交 `0419de50cfd806353256db607878bdd34a096878`；没有切换生产分支或将候选合入生产 main。

## 实现与可观察行为

- 维护控制独立于候选 SQLite，原子替换、文件/目录 fsync、短 flock；缺失、损坏、权限故障或不明接纳记录均 UNKNOWN。普通启动、崩溃拉起和重启不解除已保存的维护状态。
- 接纳与进入维护共用短互斥；资源等待项计入排空，锁获取后再准入。当前 ACTIVE 有限单项可完成原 FSM、同对象子项和合法回写；下一项重新拒绝。子项通过真实继承锁 FD、对象及精确 argv 校验归属。
- Web 四类调度、独立执行者、监控/研究、Bot、手工请求、直跑脚本和 DAL 写事务接入；执行角色有实际 PID/启动身份/cwd/源码 hash 与互斥。实际覆盖、排空及恢复方式见[覆盖清单](MAINTENANCE-COVERAGE.md)。
- `vpanel maintenance enter/status/stop-ui/resume`、`ui start --maintenance` 已提供。enter 成功只表示暂停保存；没有可信来源回执仍 UNKNOWN / safe=false。恢复须 CAS、可靠空闲、来源及保护回读，候选保持关闭；正常停止只针对归属正确的空闲 UI 发 SIGTERM，15 秒超时失败，无 SIGKILL。
- 候选已知 open/flock、connect/PRAGMA/DDL/事务/close 故障统一转为脱敏 503。候选局部故障时旧健康 GET 保持可用；共享数据库故障不承诺旧业务正常。初始化单飞，每 60 秒最多一次尝试，SQLite 等待 2 秒，已知故障 10 秒内反馈。
- 清理失败拒绝展示到期字段并继续有界恢复；退出 OFF 写入或回读失败如实记录未确认，仍等待本模块结束并释放资源。恢复先清理和核对有效 OFF，不自动请求、清预算或重播作业。
- 三次真实应用/浏览器生命周期验证本地专题新建、编辑、刷新及维护重启持久化，关闭搜索且无预算/作业新增；原 CSRF、CAS、回环边界与候选产品行为保留。

生产未提交的词汇导出代码原本缺少 `re` 导入，兼容回归出现 5 项 NameError。本轮仅在隔离分支为 `caption_processor.py` 补一行导入，临时整合副本中的词汇导出回归随后通过；生产目录没有修改。其余相关 dirty/untracked 差异只放入临时整合副本，没有纳入候选分支或覆盖生产文件。

## 本轮实际测试

所有测试经 `scripts/run_isolated_tests.py` 在一次性源码根和 macOS 沙盒执行；收集前验证外部读取/写入、网络、信号及子进程越界拒绝。借用已安装 venv 仅作为解释器，不导入生产配置、不读取密钥或生产数据库。测试响应、身份、任务与业务数据均为合成夹具。

| 批次 | 实际结果 | 适用源码与证据 |
| --- | --- | --- |
| 全量单元基线 | **3303 passed，30 subtests passed，0 failed/0 skipped，25 warnings** | [回执](evidence/v0.2.1/full-unit/receipt.json)、[日志](evidence/v0.2.1/full-unit/pytest.log)。除 Dashboard 交互文件外的全部 unit；manifest `8848dc29…`。之后 CLI enter 回读、单行 re 修复、新 CAS/故障用例及新增 TED 基线由下列增量批次补验 |
| 最终维护/故障/兼容补测 | **55 passed，0 failed/0 skipped，4 warnings** | [回执](evidence/v0.2.1/final-focused/receipt.json)、[日志](evidence/v0.2.1/final-focused/pytest.log)。真实维护/进程、CLI、故障及字幕/词汇超时回归；含真实只读 SQLite、第三张 DDL 失败全回退 |
| 最终候选故障响应补测 | **12 passed，0 failed/0 skipped** | [回执](evidence/v0.2.1/final-faults/receipt.json)、[日志](evidence/v0.2.1/final-faults/pytest.log)。最后仅完善 M10 测试：真实 SQLite 占写锁、100 个并发页面请求在 503→200 恢复期间恰好初始化三次，旧 GET 持续 200，搜索调用 0；产品源码未再变化 |
| 真实浏览器与 Dashboard 交互 | **33 passed，0 failed/0 skipped，6 warnings** | [回执](evidence/v0.2.1/browser/receipt.json)、[日志](evidence/v0.2.1/browser/pytest.log)、[运行依赖](evidence/v0.2.1/browser/browser-runtime.json)。Chromium 148.0.7778.96 / revision 1223；最终 Web/候选生命周期源码，三次维护重建及完整既有候选 UI 流程 |
| 最新生产相关差异整合 | **547 passed，0 failed/0 skipped，4 warnings** | [回执](evidence/v0.2.1/production-overlay/receipt.json)、[日志](evidence/v0.2.1/production-overlay/pytest.log)。含 0419de5 及下述 10 个生产差异副本；27 个受影响测试文件，保留词汇、商品、字幕、队列/控制面、候选与 TED 行为 |

各批计数有重叠，**不相加**；30 subtests 也不另加到 3303。旧 v0.2 的 113/297/93 为历史记录，不移作此次计数。全量基线 pytest 438.99 秒；其他批次完整 runner 耗时与参数见各 receipt。warnings 为原 FastAPI 生命周期、httpx Cookie 及 SWIG 依赖提示，没有失败/跳过被记作通过。

最终测试文件与实现逐项 SHA256 绑定见[tested-files.json](evidence/v0.2.1/tested-files.json)，保留每批完整 source-manifest.json。**55 个改动源码/配置/测试文件均匹配至少一个成功快照**；快照内容匹配只证明文件版本，实际执行范围以回执参数为准。文档后续更新单独审计，不冒充测试快照内容。运行源码摘要为 `243b85d54dc47881508b521e774b3a820ec980373751ed0bf09b0f0bfb0888dd`。

## M01–M18 对照

以下“通过”只指隔离执行，没有操作真实 cron/launchd、生产数据库、公开投稿或生产局域网。

| ID | 状态与实际观察 | 主要证据 |
| --- | --- | --- |
| M01 | 通过：真实崩溃/重拉起、至少两次应用重启不改维护版本；四种调度越过首次及周期时点零派发；每次 Web 生命周期四线程启动并正常退出 | `test_m01_*`、`test_m01_m07_actual_web_lifecycle_restarts_one_scheduler_group`；浏览器三次重建 |
| M02 | 通过：真实多进程与控制锁竞争；已接纳项统计完整，真实资源锁等待项不漏报，维护后解锁也不能开始新业务 | `test_m02_m03_*`、`test_m02_actual_resource_waiter_rechecks_after_lock` |
| M03 | 通过：当前合成单项完成/回写、第二项拒绝；正确子 FD/argv 可继续，伪造和对象/命令不匹配拒绝，无外部 kill | 真实进程、临时账本；`test_m03_child_continuation_exact_fd_argv_and_object` |
| M04 | 通过：32 个脚本/业务直接入口前置拒绝；Web 写 503、stats 与健康候选 GET 200；热词维护时仅缓存；旧合法内部回写保留 | `test_m04_*`；未 mock SQL 或文件锁。cron/launchd 用同入口等价唤醒，未改变宿主调度 |
| M05 | 通过：缺失、损坏、控制及接纳目录权限故障均 UNKNOWN；CLI enter 只确认持久化，不虚报 safe；无法采集外部进程也拒绝 | `test_m05_*`；沙盒外 ps/lsof 无法读进程时正确失败关闭 |
| M06 | 通过：真实空闲 UI 只收到 SIGTERM；不空闲不发信号；忽略 SIGTERM 的隔离 UI 超时失败，未强杀，测试最后用合成释放文件自然结束 | `test_m06_*`；没有向沙盒外发信号 |
| M07 | 通过：双进程 enter 幂等；双进程 CAS 仅一次 RUNNING 转换，另一次版本冲突；重复角色拒绝；三次 Web 生命周期无遗留调度线程 | `test_m07_*`、M01/M06 真实角色竞争 |
| M08 | 通过：真实目录、权限与单窄点 flock 故障；候选 503/LOCK_UNAVAILABLE，健康 GET 200，错误不泄露路径，零搜索 | `test_m08_*` |
| M09 | 通过：真实连接覆盖 connect/PRAGMA/DDL/close；持写锁等待约 2 秒，10 秒内错误；实际 mode=ro 拒绝写；第三张表 DDL 失败回滚前两张并 integrity_check=ok；局部故障旧 GET 200 | `test_m09_*`；局部连接故障不等于共享数据库仍健康 |
| M10 | 通过：真实 SQLite 写锁下并发页面返回 503；可控时钟 100/160/220 仅三次初始化，159/219 不重试；释放故障后 HTTP 200；旧 GET 持续可用 | 最终 `test_m10_concurrent_retry_anchor_and_m12_recovery_off`；100 次 HTTP 请求、真实临时库 |
| M11 | 通过：真实 SQLite 锁使清理失败、到期数据不可读；下一周期解除后清空到期字段并保留决定；OFF 写入失败记未确认，解除后确认停止与资源释放 | `test_m11_*`、原 A19；周期循环对已知故障保留下一次重试 |
| M12 | 通过：配置关闭、未知维护、故障恢复及 RUNNING 恢复后有效搜索仍关闭；可读时修正 OFF，作业/预算不新增 | `test_m10_*`、M16/M18、浏览器闭态；原 A12/A14 |
| M13 | 通过：真实 Chromium 新建/编辑运营专题、刷新、三次新服务实例仍保留；CSRF 403、旧版本 409、非回环对端 403，关闭按钮，无请求/作业/预算 | `test_m13_*`；[第三次重启截图](evidence/v0.2.1/screenshots/maintenance-restart-2.png) |
| M14 | 通过：原 A01–A21 重新执行，既有控制面/商品/词汇/字幕/队列回归通过；最新生产相关差异整合通过 | 全单元、33 浏览器及 547 整合回归；不挪用旧测试成绩 |
| M15 | 通过：仅移除候选 DAL mixin 的回退演练保留维护闸门、新表、候选/决定/审计/作业/预算及合法回写；SQLite 一致性 backup 与当前库 integrity_check=ok | `test_m15_*`；无整库恢复、删表或任务批量重置 |
| M16 | 通过：模拟未知/遗留 PID、无来源清单时 safe=false，拒绝停止/恢复；不把新代码状态当成旧进程已暂停 | `test_m16_*`、M05 CLI/Web 状态、来源覆盖清单 |
| M17 | **未执行：待 A 授权** | 生产同端口/目录、实际 PID/hash、维护安全重启、真实 LAN 和原调度恢复均不能由隔离替代 |
| M18 | **隔离通过；生产待回读**：正常既有任务原子领取一次，第二次拒绝；候选 OFF 且作业/预算无新增，没有集中补跑 | `test_m16_unknown_source_and_m18_single_normal_resume`；生产只观察合适既有任务，不为验收制造投稿 |

测试路径：`tests/unit/test_maintenance.py`、`test_maintenance_entries.py`、`test_topic_runtime_failures.py` 与 `tests/browser/test_topic_candidates_browser.py`。操作与回执格式另见覆盖清单。真实浏览器通过路由转发连接 TestClient/临时 SQLite，实际非回环边界是隔离请求身份测试，**不是生产 LAN 实测**。

## 最新生产差异与首次采用边界

[临时整合记录](evidence/v0.2.1/production-overlay/overlay-receipt.json)绑定生产 HEAD 0419de5 及 10 个相关文件原 SHA256、整合后 SHA256；[整合脚本](evidence/v0.2.1/production-overlay/build-overlay.py)只复制维护源码并排除 `.env`、secrets、output 和运行数据库。

副本三方整合的 6 个文件为 `database.py`、`caption_processor.py`、`subtitle_translation_provider.py`、`vocab_helper.py`、`submit_generic_douyin.py`、`config/wechat_products.json`；4 个相关未跟踪文件为 `topic_clues/__init__.py`、`topic_clues/hub.py`、`test_topic_clues_hub.py`、`test_vocabulary_export.py`。仅数据库/通用投稿的历史表格行发生文档冲突并逐行保留，业务冲突不自动解决。其他生产未提交/未跟踪工作保持原样，未拷入交付分支。

归档时的[源码重新核对](evidence/v0.2.1/production-source-refresh.json)确认 HEAD 与这 10 个文件仍匹配；这是一份源码时点证明，不证明生产 PID、状态、配额、保护或外部来源。A 执行前必须重新核对；若改变，重新整合/验受影响部分。

首次 A 仍需独立核实并冻结旧 cron/launchd、Web 内存线程、独立 worker、Bot/人工入口及再启动来源，等待当前单项自然结束并证明竞争窗口受控。当前已加载旧进程不认识维护协议；**不能写入新状态文件就宣布已排空，也不能以停掉 cron 代替全部来源核实**。无法证明安全时延期 A，不强杀、不删锁、不改发布资格。

在 A 尚未获批时，本轮没有改生产 `.env`、读取密钥、修改业务库、停进程、重启、调用真实 API、改变现有保护或公开发布。临时副本与测试数据均不进入生产。凭据所属项目仍未知；控制台历史额度不能代替这个门禁，B 继续未授权。

## 复验与下一步

在独立目录使用已安装 venv：

```sh
/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/.venv/bin/python scripts/run_isolated_tests.py -- -q tests/unit --ignore=tests/unit/test_dashboard_interactions.py
/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/.venv/bin/python scripts/run_isolated_tests.py -- -q tests/unit/test_maintenance.py tests/unit/test_maintenance_entries.py tests/unit/test_topic_runtime_failures.py
/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/.venv/bin/python scripts/run_isolated_tests.py --browser -- -q tests/unit/test_dashboard_interactions.py tests/browser/test_topic_candidates_browser.py
```

生产差异整合批次从临时副本运行该副本的 runner；完整 27 文件参数和原始时间见回执。本轮静态 AST、`bash -n vpanel` 与 Git 空白检查通过；原始日志按局部 Git 属性保留。按 codereview 方法完成本轮自检，未发现剩余阻断缺陷；未冒充独立外部评审或生产验收。未执行全媒体/其他无关浏览器套件。

下一步是按[上线方案 A](ROLLOUT-PLAN.md)另行确认关闭状态生产采用。安全空闲/证据齐备后预计 1–2 工时，排空等待与未知来源处置另计。真实搜索 B 必须再核实生产凭据项目、配额和共享调用者，并单独获得开放授权。
