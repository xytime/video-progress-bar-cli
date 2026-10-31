# 首中尾抽检验收记录

记录者：Codex；日期：2026-10-31。

范围是用户于 2026-10-31 批准的正向抽检修订，见同目录 `2026-10-31_caption-sampling.md`。本文不把抽检通过等同于全片逐帧覆盖，不把完成一次尝试等同于成片吞吐。

## 本轮结论

| 项目 | 已取得的证据 | 状态 |
| --- | --- | --- |
| 抽检实现 | 首中尾各 15 秒，初轮最多 45 帧、补查后最多 63 帧；仅三段正向一致才保留，负向仍走完整路径 | 已提交并推送候选分支，代码版本 `3b39a77` |
| 全量隔离验证 | 实际 Chromium、tiny/base 媒体、完整 `tests`：6,518 passed、30 subtests passed；0 failed、0 skipped，退出 0，沙盒清理完成 | 通过 |
| 真实抽检 | 8.37 秒正向片段保留交付与源字节相同；14 分 37 秒首次 OCR 返回完整回退，未误放行 | 局部证据具备，长片正向交付未完成 |
| 整片语义恢复 | 单独用旧分页候选 `a429f78` 完成一条真实 62 段任务；14 次实际请求 314.33 秒；断网缓存回放 0.175 秒 | 不是本次抽检代码或成片吞吐验收，也未采用到生产 |
| 生产采用 | 旧 BMP 传图优化已生效；新抽检模块未部署、开关关闭 | 本轮不启用、不发起投稿 |

仍缺长片正向首次识别与交付、可靠的人工语义金标、完整真实翻译恢复、完整双任务交接及固定队列的有效成片吞吐。不能宣称整体吞吐目标达成。这次正向捷径主要帮助已有中文字幕的源片；纯英文片仍需完整扫描，当前生产的全片扫描和语义图片上限卡点不会因此自动消失。

## 代码与隔离边界

- 候选提交：`2ceee05`（历史测试夹具）、`863ea67`（测试隔离与精确回收）、`16abe89`（抽检实现）、`4dd939f`（并发测试的合法输入）、`ebe401a`（浏览器账户准入、请求模拟及延迟 ASR 的测试夹具）、`8403c0e`（页面策略热更新的测试隔离）、`d55adb0`（真实筛选分组及任务身份）、`3b39a77`（Python 限流回调同步）。均已推送 `codex/ocr-sampling-20261031`，远端回读确认 `3b39a77b2a9e642e2c21717dea852df263103dc4`；后续文档提交另记。
- 在独立目录叠加生产现有的 93 个未提交文件及验收所需资产，构造“生产现状 + 本次改动”。无关修改没有收入本次提交；单独 checkout 提交不等同于这份完整被测快照。
- 证据根目录：`/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/ocr-sampling-20261031`。保护清单为 `production-overlay-baseline.json`；15:15 前复核 93 项均无变化。
- `native_caption_sampling_enabled=false`。生产没有采用抽检代码，没有通过本次验收发起投稿，也没有重置生产任务、ASR、OCR、翻译或发布检查点。

## 自动化验证

- 针对性验证：125 passed，退出码 0；证据 `../video-pytest-q6nbakv2/receipt.json`、`pytest.log`。包括 45/63 帧上限、仅一次补查、简繁双语、局部/无中文/标题、供应商异常、缓存损坏与中断恢复、源/ASR 失效、关闭开关回退、保留原片及完整审核正文。
- 先前完整单元测试为 10 failed / 5,958 passed / 1 skipped / 30 subtests passed。三项失败来自共同目录残留的真实测试执行者；七项来自沙盒生命周期单测误调用宿主进程查询。修复测试隔离和宿主边界；没有放宽生产发布或字幕判断。
- 修正后完整非浏览器单元测试得到 1 failed / 5,969 passed / 1 skipped / 30 subtests passed，证据 `../video-pytest-pmr7ysc4/`；清单 SHA-256 为 `ac88874322dbea8da581bb881679b89e63c88442036c224927f81f4b8a5c8170`。剩余失败是商品导入并发夹具中一个请求错误地修改了已有商品名，422/409 随抢锁先后变化。改为两个初始均合法的新商品请求，先预览验证，再严格断言 200/409、获胜清单与规则文件不变。相关三模块 48 passed，证据 `../video-pytest-q1owbs2h/`。没有将 422 纳入宽松通过条件。
- `--browser --media -- -q --tb=short --durations=15 tests` 完整套件在浏览器阶段发现可复现失败后，精确中断该沙盒 pytest，保留 traceback/JUnit，避免继续消耗整机资源。证据 `../video-pytest-90c_i6_t/`：16 failed / 558 passed，退出码 2，沙盒清理完成；不能视为完整执行或通过。原因包括旧 helper 未取得真实账户准入、旧保活/自动核对已被默认调度停用、测试 context route 被后来安装的真实请求守卫覆盖，以及媒体阶段顺序断言未跟随 ASR 延迟加载。
- 修正测试采用隔离账户的真实锁与准入；旧保活内部页面合同显式测试旧模式，另保留默认模式禁止自动查询的零浏览器断言；页面模拟放到 page route，生产锁和账户守卫不变。媒体检查继续验证真实 base ASR、字幕文字/时序/像素及原音轨，只更新阶段顺序。专项含实际 Chromium、媒体和真实账户准入回归，证据 `../video-pytest-txtriypn/`：33 passed / 1 warning，250.72 秒，退出码 0、沙盒已清理；源码清单 SHA-256 `abbdd6c82022ff598f7c7be35a1841d9e0f841fc0ced6d6c0cbcfbd82c7bee2f`。
- 完整浏览器/媒体套件 `../video-pytest-rp20yc6o/`：1 failed / 6,517 passed / 30 subtests passed，pytest 1934.85 秒、runner 2024.202 秒，退出码 1；沙盒已清理，精确回收一条本沙盒遗留执行者。源码清单 `22973b94ce1809e5fe6f25767b82548c2ee6e3f08bb587d7696010dafd6ba5b0`。唯一失败为旧共享小时额度的竞争用例：浏览器保存策略把单例上限留在 7，而它预置 9 次并期待上限 10。
- `8403c0e` 给浏览器夹具恢复全部六项策略字段并在 teardown 断言恢复；竞争用例显式固定旧模式、测试配额和独立策略路径，保持恰一成功、一因 10/10 配额拒绝。首轮专项 `../video-pytest-azcu0sp8/` 1 failed / 57 passed 暴露仓库策略热加载覆盖测试间隔，修正独立路径后，按“浏览器保存 → 并发竞争 → 策略恢复/编排”顺序 `../video-pytest-r1d0qahv/` 58 passed，34.884 秒、退出码 0、沙盒清理完成。生产配额与数据库逻辑没有修改。
- 新一轮完整浏览器/媒体套件 `../video-pytest-_8iw9rrs/` 早期出现一个失败后中断。第一次 SIGINT 卡在 Playwright 的页面关闭，第二次 SIGINT 才退出；runner 退出码 -2，沙盒已清理，无 JUnit，不能算执行通过，也不能断言已保存该失败的具体 traceback。根据既有执行顺序，第 55 项为英语世界桌面筛选测试；单模块复测 `../video-pytest-h3oa32fa/` 8 passed，说明不能简单归为稳定失败。
- 检查发现该夹具将筛选分组 `failed` 与任务状态 `FAILED` 直接比较，而断言期待的是前一查询的 12 行，可被旧结果瞬态满足。`d55adb0` 对齐真实状态分组，严格检查失败任务 `job:fixture-03`、定时筛选零任务及清除后的 12 项。没有改变生产页面或接口。相关两模块 `../video-pytest-6vkvtfga/` 12 passed，20.315 秒，退出码 0，沙盒清理完成。
- 完整浏览器/媒体套件 `../video-pytest-q29leot7/` 在 `d55adb0` 与保护的生产覆盖上执行，使用 `-x` 后在第 478 项停止：1 failed / 477 passed，892.402 秒，退出码 1、沙盒清理完成。失败为 `test_initial_page_business_limit_is_seen_without_ready_controls[False]`，页面 JS 完成早于 Python 限流响应回调；完整 traceback/JUnit 已保留。
- `3b39a77` 单独移入旧候选已验证的有界回调等待，仍严格断言 -360、恰两次页面/API 请求、共享退避及无投稿回执，不改生产限流代码。重复该模块三次加账户上下文和 OS 浏览器隔离，`../video-pytest-20tiqa0b/` 13 passed、25.820 秒、退出码 0、沙盒清理完成；源码清单 `12e44de36bba3659014cd1a8a34865c0c304235e89c32556c9fda687054e96e1`。前一次误写测试路径导致 `../video-pytest-cu00kxtf/` 收集退出 4，明确不计通过。
- `3b39a77` 的完整浏览器/媒体套件 `../video-pytest-yoxobn_9/` 完整收集结果：**6,518 passed、50 warnings、30 subtests passed**；JUnit 为 6,548 项、0 failure、0 error、0 skipped。pytest 正文 1647.53 秒，runner 记录执行及退出等待 1740.477 秒；最终退出码 0。沙盒清理完成，精确回收该副本内一条 `run_ready_publications.py` 执行者，未回收其他根的进程。收据于 17:16:36 完成。
- 16:58 对该轮 1,980 项源码/资产清单逐项复算摘要，本次提交的 36 个文件均在快照中；除这份持续补充的验收报告外，全部文件与被测快照相同。见 `candidate-tested-source-binding.json`，清单 SHA-256 `12e44de36bba3659014cd1a8a34865c0c304235e89c32556c9fda687054e96e1`。摘要一致本身不代表测试通过。
- 一次重复启动的完整测试为避免 16 GB 主机内存压力主动中断，退出码 130；该次不计通过。回收只匹配本次沙盒 Python 与脚本的精确路径，失败保留证据。

## 真实样本

| 样本 | 输入与实际调用 | 结果 | 能证明的范围 |
| --- | --- | --- | --- |
| 8.37 秒繁体双语片段 | 原片真实声画；复用 8 帧历史 OCR；1 次实际 Codex 视觉核验 | 28.48 秒，PRESERVE；实际保留交付与源文件 SHA 相同，无 ASS | 短片正向语义与交付；不是首次 OCR 性能 |
| 28.8 秒同源片段 | 复用 15 帧；1 次实际核验 | 32.45 秒，PARTIAL 后回到完整路径 | 不通过的帧不能被其他可读标题替代，也不降低置信度 |
| 本次 43.57 分钟慢任务 | 463 段原 ASR；复制 74,617 帧时的检查点；读取其中 15 帧 | 1.09 秒，FULL_FALLBACK；0 新 OCR、0 语义请求，未重跑全片 | 负向抽检不声称全片无中文；不能用于首次 OCR 或成片吞吐对比 |
| 14 分 37 秒双语长片 | 复制真实成片和 ASR；15 帧新 OCR、0 缓存命中、1 次实际语义核验 | 33.93 秒，ABSENT 后 FULL_FALLBACK；首段音乐/标题不足以证明对白字幕 | 前奏音乐会阻止该样本走正向捷径，不能宣称此片已提速成片 |
| 14 分 13 秒访谈长片段 | 同一片从第 24 秒实际访谈开始无重编码切出，283 段 ASR 同步平移 | 等待生产 OCR 空闲后实测 | 单独保留切片来源、SHA 与失败的完整原片，不能挑成功片覆盖前次结果 |

对应证据：`real-positive-av/receipt.json`、`real-positive-av/delivery-receipt.json`、`real-replay-v2/receipt.json`、`real-long-negative/receipt.json`、`real-long-bilingual-fixture/provenance.json`。所有抽检正向凭证均标注 `full_timeline_verified=false`。

七类旧语义样本使用实际 `gpt-5.6-luna / medium` 复验，7 次、228.61 秒，未再出现认证错误；6 类与既定预期一致，双语例返回 GENERATE，与预期 PRESERVE 不符，见 `semantic-gold-reaudit/receipt.json` 和对应 `evidence.json`。双语画面可见“债券仍然重要 / Bonds still matter”，模型理由是“标题式双语卡片”。这批输入各仅 0.4 秒、四张静态合成帧且没有真实语音，不能独立证明对白字幕行为。不得改标签或修改生产判断来刷过这项；也不能据此报告真实字幕准确率为 6/7。已提供可放大的中文人工复核页 `HUMAN-REVIEW.html`，人工仍未确认；另需真实动态对白覆盖。

长片首次脚本调用直接传了 Whisper 扩展字段，`id` 与窗口标注冲突，在任何供应商调用前 TypeError；保留 `cold-attempt-1-error.json`。随后按正式路由的 start/end/text 规范化传参，独立缓存身份，15 帧全部重新 OCR；有效尝试的 OCR 1.39 秒（其中 Vision/传输 1.30 秒、BMP 编码写入 0.086 秒）、解码 0.734 秒、语义核验 31.30 秒。脚本总收据含前次不同身份的指标，不得将两组累加成一次成功，`cold_start` 的旧全目录判断亦不能代替具体缓存命中数。第二次的进程峰值 RSS 约 204 MiB、子进程峰值约 268 MiB，均非整机峰值，也不相加冒充并发峰值。

该真实长片随后在 OS 禁止联网、并明确禁止新 OCR worker 和供应商执行入口的条件下回放，0.134 秒返回相同的 FULL_FALLBACK，15 帧缓存命中、1 次语义缓存命中、0 解码、0 新 OCR、0 新供应商执行。见 `real-long-bilingual-fixture/warm-cache-receipt.json`；原冷运行 metrics/attempt 在 `before-warm-replay/` 保留。此项证明恢复复用有效，不是首次识别提速或成片吞吐验收。

访谈长片验收使用 `run_long_when_idle.py` 非阻塞尝试取得既有 pipeline.lock，仅在空闲后最多占用 300 秒，防止验收和下一条生产 OCR 重叠；不改锁文件、不终止生产进程。16:20、16:44、17:14 三次尝试均因生产持锁让行，锁内容未变化，见 `long-acceptance-lock-receipts.jsonl`。没有把等待算作执行通过。

## 尚未达到的启用条件

长片正向首次 OCR 及保留交付、人工语义金标、完整真实翻译恢复、双任务完整交接和固定队列有效成片吞吐，必须分别有证据，不能由以上单测或短片回放替代。长片首次 OCR 的负向回退和缓存复用已有上文证据，不能替代正向交付。旧分支 2026-10-30 的翻译恢复只验证了有限批次，存在供应商区域/限流与剩余预算不足；不得通过重置预算或无限重试写成通过。

目前没有优化前后同一完整队列的成片数、发布包就绪数、完成率、复核率、失败率及有效吞吐，故这些指标为未测量。短片通过一次、长片回退一次既不是完成率，也不是性能倍数。正向抽检仅减少已有中文字幕视频的工作，未证明解决多数纯英文源片的全量扫描成本。

## 采用与回滚

旧 BMP 传输部署是独立计划 `4309252f6e7146c291535c9c1033af71`。15:20 左右原任务自然退出后，原生部署完成，生产和远端 main 均为 `9a729c812f29a7ea5f687b14a9153c00386165d1`，运行优化开关为 true。维护恢复与采用以 `/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/ocr-production-20261031/delivery.json` 和原生 journal 为证；不与本次仍关闭的抽检混记。15:21:58 复核 93 个受保护文件，仅 settings.py 存在该已测 BMP 部署预期修改，无意外漂移，见 `production-preservation-readback.json`。

生产长任务 `w21d64pB9jk` 自然结束后的决定为 REVIEW，原因为 `VISUAL_REVIEW_BUDGET_EXCEEDED`，不是成片或发布成功。随后实际新任务 `XCMMCNPQBDk` 已运行 `native_caption_file_vision.js`，证明 BMP 传输被新进程使用；15:52 该 4 分 37 秒任务也留下同样的 REVIEW 决定，队列转入 `cfHekZAC-o4`。这两次完整识别没有产出成片，不能算作有效吞吐改善。

15:44 生产回读为维护 RUNNING/version 218，抽检模块不存在、抽检开关未启用。93 个受保护文件仍只有已部署的 settings.py 预期差异；该文件与被测候选剔除两行抽检配置后完全一致，见 `production-current-readback.json`。

16:06 再次比较全部 93 个受保护文件及生产 HEAD，结论相同，预期外变化为 0，见 `production-final-code-preservation.json`。两条自然结束任务的决定与凭证 SHA 见 `production-completed-ocr-readback.json`。

16:32 只读回查的 93 项仍无预期外变化，维护为 RUNNING/version 218，生产没有抽检模块。`cfHekZAC-o4` 也自然结束并记录相同的 `VISUAL_REVIEW_BUDGET_EXCEEDED`；三次观察均为 REVIEW，不能算成片完成，也不能将这三个观察样本当作整个队列的完成率。见 `production-readback-1632.json`，包含三条决定的原始路径及摘要。

17:06 的再次只读回查结论相同；15 分钟的 `jnJX5Q9QJgQ` 仍处于 `SOURCE_CAPTION_LOCATING`，心跳正常，见 `production-readback-1706.json`。30 秒主机观察记录于 `host-observation-1708.json`，该窗口新增 swap-out 为 0；这是并行测试期间的短时观察，不是整机峰值、性能归因或无干扰证明。

全量测试结束后于 17:17 再次核对：93 项无预期外变化，维护 RUNNING/version 218，新抽检模块仍不存在；当前生产任务继续扫描。见 `production-final-readback.json`。机器可读交付索引 `acceptance-summary.json` 绑定本轮测试收据、源码清单及真实样本收据摘要，明确 `production_sampling_enable_allowed=false`，未执行的完成率、复核率、失败率、成片/小时及发布状态指标均保持 null。

`production-bmp-scan-baseline.json` 从两份完成的检查点取得扫描壁钟：`XCMMCNPQBDk` 8,301 帧、1617.448 秒，严格相同像素复用 207 帧；`cfHekZAC-o4` 7,550 帧、1412.528 秒，复用 0 帧。扫描平均分别约 5.13 和 5.35 帧/秒；没有同源旧版对照，不计算优化倍数。它们分别有 9 段和 1 段超过单次语义图片上限；后者第 47 段含 40 组文字/位置。本次另用后者完整副本验证既有 `a429f78` 分页实现，单独记录在 `completed-task-semantic-cfHekZAC-o4/`；不重跑 OCR、不合并旧分支、不作为抽检候选的验收替代。

该完整副本已验收：62 段实际语义核验均为 ABSENT，宿主决定 GENERATE，14 次实际 `gpt-5.6-luna/medium` 请求、314.328 秒，含超量段的两页视觉及整段核验。整次设 600 秒上限，超量段仍共享原 120 秒；没有增加单请求时限、重置预算或跳过疑似中文。原片、原决定、完整 OCR、原语义证据四份生产文件 SHA 前后相同。见 `completed-task-semantic-cfHekZAC-o4/receipt.json`。

随后在 OS 拒绝网络及生产目录写入的条件下，禁止图片解码器和模型执行入口，完整 62 段回放 0.175 秒、14 批缓存命中、0 新 OCR、0 解码、0 模型执行，结果逐项相同。网络拒绝由实际 bind 探针验证，见 `warm-receipt.json`、`semantic-replay.sb`。这补足一个真实整片的语义与恢复证据，**不是人工语义金标、翻译恢复、成片吞吐或抽检长片正向验收**，也没有使分页代码在生产生效。

只读拆解该慢任务的完整 OCR 结果发现 10 段超过单次 24 张图上限。第一处为 33.04–39.48 秒，35 组不同文字/位置及 3 张上下文需 38 张，按帧完全去重仍需 37 张；最重的一段需 99 张，去重仍需 83 张。异常发生在调用供应商前，不能归因认证；也不能靠删证据、增加超时或把更多任务改为 REVIEW 宣称提速。证据 `slow-task-visual-packing-audit.json`；本次没有重跑、重置或投稿该任务。

抽检达标后仍须通过原生部署计划精确采用被测文件和无关改动覆盖，排空后校验进程所用版本及开关。回滚关闭抽检开关即可停止新抽检决定复用；已验证保留交付、旧扫描、新抽检缓存和发布状态均保留。UNCERTAIN、已提交、审核中和已发布记录不能自动重投。
