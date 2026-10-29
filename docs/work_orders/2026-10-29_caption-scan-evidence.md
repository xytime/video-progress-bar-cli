# 2026-10-29 OCR 扫描候选验收证据

作者：Codex（本地执行代理）。本单独立于 [吞吐优化主执行单](2026-10-29_pipeline-throughput.md)，只记录 OCR 候选与缓存兼容证据，不授予生产或发布权限。

**P1 保持 off。** `native_caption_scan_optimization_enabled=false`，未启用生产配置。候选只在独立验收子进程中临时开启。真实微样本冷扫描池化中位改善约0.04%，未达到20%门槛；Yux 退化7.52%，也超过主执行单当前5%的单样本退化限制。没有完成完整长片、语义 gold、长期资源或合格成片吞吐验收。

## 执行边界与工具

- 开发工作区：`/Users/ryusei/.codex/worktrees/824c/Video-precessing`。源视频与历史缓存来自只读生产目录 `/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output/original_video/`。
- `scripts/benchmark_caption_scan.py`：显式输入源文件、显式全新 EXT2T 输出根，拒绝覆盖、链接及生产 output 内的验收目录；默认仅准备小样，`--run-ocr` 才运行。
- 每条真实源仅取起始帧0至最多0.5秒的连续完整帧。OpenCV 解码后导出无损 FFV1 AVI，逐帧回读像素 SHA-256 与导出前对照；保留原分辨率、帧率，不缩放、不裁 ROI、不抽帧。这证明小样对应关系，不能代表整片时间轴已扫描。
- 三对顺序为 AB、BA、AB；A 为旧扫描分支，B 为优化候选（PNG compression=3）。每轮新进程、新扫描目录，单 OCR worker；所有轮次 `cache_hit=false`、`resumed_frames=0`。“冷”仅指应用扫描缓存，未清理系统缓存。
- 每批使用无 `.env` 的固定 `src` 副本，`source-manifest.json` 记录实际代码摘要。子进程使用显式清洁环境与验收根内 HOME/TMPDIR；macOS 沙盒禁止网络及验收根之外写入，只读本根、解释器依赖和标准系统目录。Vision 本机 IPC 可用，不调用语义模型或上传器。
- `scripts/verify_native_scan_cache.py` 另验证历史 v2 完整扫描复用：选定原视频仅按文件 literal 开放只读，复制 full/partial；系统拒绝执行 JXA，代码 guard 禁 OCR/语义调用，缓存未命中即失败，不自动重试。
- 未写生产数据库、源片、缓存或发布状态；没有投稿。证据目录后缀是人工命名，执行时间以收据/事件 timestamp 为准。

## 真实微样本：36轮

实际收据：[summary.json](/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/ocr-micro-ab-20261029-2040/summary.json)、[plan.json](/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/ocr-micro-ab-20261029-2040/plan.json)、[runs.json](/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/ocr-micro-ab-20261029-2040/runs.json)。每轮目录还保留完整扫描、阶段指标、日志及资源收据。

| 源 ID | 原尺寸 / fps | 小样帧数 / 秒 | A 三轮中位秒 | B 三轮中位秒 | B 相对 A | B 每轮 OCR / 复用帧 |
| --- | --- | --- | ---: | ---: | --- | --- |
| YuxF7u8LZO8 | 1280×720 / 60 | 30 / 0.500 | 7.741 | 8.322 | 慢7.52% | 30 / 0 |
| vD0fgM0XZaE | 1280×720 / 30 | 15 / 0.500 | 3.649 | 3.522 | 快3.49% | 10 / 5 |
| DWbJ31cxXyM | 1280×720 / 50 | 25 / 0.500 | 8.183 | 3.990 | 快51.24% | 3 / 22 |
| VN5Ix7fdh5w | 1280×720 / 29.97002997 | 14 / 0.467 | 5.416 | 5.582 | 慢3.06% | 14 / 0 |
| GLmfI0OuLKs | 360×640 / 30 | 15 / 0.500 | 4.928 | 4.973 | 慢0.92% | 15 / 0 |
| uWqFBoeLCPk | 1280×720 / 29.97002997 | 14 / 0.467 | 5.110 | 5.319 | 慢4.09% | 14 / 0 |

- 所有36轮完整 `runs`（含文本、置信度、位置、帧边界）严格相等，`frame_count/fps/width/height` 与各自小样一致；比较没有删去置信度或几何差异。仅候选特有的审计映射不参加核心结果判等。
- A 共339次实际 OCR，B 共258次 OCR、81个复用帧；合计678个完整帧访问全部有实际识别或可追溯相等证据。四源没有复用命中，DWb 的片头静止帧收益不能外推整片。
- 将每模式六源各三轮的18个扫描墙钟池化后，A 中位5.141615秒，B 中位5.139737秒，约改善0.0365%。该口径不是全片加权吞吐；也不是“典型视频快51%”。
- 先行单源1对探针确认沙盒/本机 Vision 可用：[探针收据](/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/ocr-micro-probe-20261029-2035/summary.json)。探针不计入上表三轮结果。

## 合成 gold：有效42轮

有效收据：[summary.json](/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/ocr-gold-ab-20261029-2055/summary.json)、[plan.json](/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/ocr-gold-ab-20261029-2055/plan.json)、[runs.json](/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/ocr-gold-ab-20261029-2055/runs.json)。每片为完整的720×1280、10fps、4帧/0.4秒合成短片；用本机 `/System/Library/Fonts/STHeiti Medium.ttc`，生成前逐字确认存在有效字形。

| 样本 | 人工已知 OCR 事实 | 三对结果 |
| --- | --- | --- |
| simplified | 第0–3帧“债券仍然重要” | 文字命中、中文出现帧一致、完整 runs 等价 |
| traditional | 第0–3帧“價格正在上漲” | 同上 |
| bilingual | 第0–3帧中文加“Bonds still matter” | 同上 |
| partial | 第0–1帧中文，第2–3帧空白 | 同上 |
| no_chinese | 第0–3帧仅英文 | 同上 |
| single_frame | 仅第1帧中文，其余空白 | 同上；没有以重复背景跳过该孤立帧 |
| title_nameplate | 第0–3帧顶部“宏观经济 / 王先生” | 同上；只证明识别，不证明已与对白字幕正确分流 |

42轮共168个完整帧访问，实际 OCR 114次、严格相等复用54帧。七类均满足已知文字及中文出现帧事实，所有 A/B 完整 runs 严格等价；收据明确 `semantic_gold=false`。

最初混合批次使用 Songti TTC 默认子字体，其“價/漲”为空字形，繁体 gold 无效。该批全部保留原收据，不将空字形归因 OCR、不把它计为有效 gold。工具已增加缺字拒绝检查，并在全新目录仅重跑上述七个合成样本；真实六源未重算。

这不是完整中文字幕/无中文字幕的语义金标。没有 ASR 对齐、对白匹配、低置信度视觉核验、移动/小字字幕或人工逐段语义复核；不据此签发 PRESERVE/GENERATE 或投稿许可。

## 历史 v2 完整缓存：6/6 零 OCR

收据：[summary.json](/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/ocr-legacy-cache-20261029-2105/summary.json)。实际原片 SHA-256 与旧缓存身份匹配，复制 `scan.json`、`partial-scan.json` 后运行开启优化的当前候选。

| 源 ID | 原有完整扫描帧数 | 结果 |
| --- | ---: | --- |
| YuxF7u8LZO8 | 51,456 | 旧完整 cache 命中，零 OCR |
| vD0fgM0XZaE | 19,290 | 同上 |
| DWbJ31cxXyM | 39,035 | 同上 |
| VN5Ix7fdh5w | 26,277 | 同上 |
| GLmfI0OuLKs | 4,568 | 同上 |
| uWqFBoeLCPk | 8,040 | 同上 |

共148,666个历史扫描帧被复用，未运行实际 OCR/JXA/语义网络；full/partial 副本字节摘要未改，没有创建 v3 扫描目录。只开放原视频文件只读，未修改生产缓存。

这里是**历史完整扫描缓存复用**验收：full 优先命中，partial 虽被复制保留，但未被消费。不能把本轮写成“真实历史 partial 续扫通过”，也不能把旧扫描复用写成整片无中文或语义审核通过。旧partial连续性由下面受控故障测试覆盖其代码路径，真实进程中断/恢复现场仍须另验。

## 资源与计时口径

- 真实36轮扫描子进程墙钟合计约215.12秒；这不包含全部样本准备、其他合成批次或原流水线耗时，不用来换算合格成片/小时。
- 每轮以 `ps` 采样后休眠0.1秒，汇总本轮 Python 及后代 RSS。A 最大323.03MiB，B 最大372.55MiB。共享页可能重复、短峰值可能漏采，系统 Vision/GPU 服务不一定在该进程树内；它不是完整主机内存预算证明。
- 历史 DWb 的61,158,969字节完整 JSON 缓存命中采样峰值仍约770MiB，提示大缓存加载也有内存成本；这不是长片冷扫描内存验收。
- 真实36轮期间整机 swapout 计数从2,531,805升至2,570,421页，swapin 从1,495,448升至1,506,954页。生产 OCR 同时运行，不能归因候选；短样本与整机混杂计数不能证明“不持续新增 swap”。
- `metrics.jsonl` 保留 `duration_seconds/frames/ocr_calls/reused_frames/cache_hit/resumed_frames/decode_seconds/compare_seconds/encode_seconds/vision_seconds/normalize_seconds/checkpoint_seconds`。分项不是总墙钟的完整分割，未单列的进程初始化、探测、源摘要及部分完整结果处理仍在总墙钟内，不能把各项与阶段墙钟重复相加。
- 本次微样本扫描均不足30秒，没有用真实长运行触发30秒/300帧周期断点或5分钟让行。单测 hook 的正确边界不等于真实队列公平/交接时间达标。
- 各批源码固定在对应 `source-manifest.json`。批次后的小修不倒填旧实测版本；最终代码测试与实测快照分别取证。

## 故障与保护测试映射

测试文件：[test_caption_scan_optimization.py](/Users/ryusei/.codex/worktrees/824c/Video-precessing/tests/unit/test_caption_scan_optimization.py)。以下故障注入/保护节点已进入最终定向隔离回归；受控测试与真实现场的边界仍须分别评估。

| 故障或约束 | 具体测试名 | 覆盖边界 |
| --- | --- | --- |
| 一像素变化、dtype变化、失败不能提交复用 | `test_exact_pixel_reuse_is_not_similarity_and_never_reuses_failure` | 严格完整像素相等，成功空结果可复用；没有相似度捷径 |
| 非JSON、缺rows、非dict、带error的空rows | `test_worker_failure_or_missing_rows_never_becomes_successful_empty_evidence` | 无效响应不能伪装为成功空证据；native/burned均覆盖 |
| 非法累计预算字段 | `test_checkpoint_elapsed_rejects_invalid_evidence` | 负数、布尔、无限值、字符串拒绝 |
| 重领重获完整扫描预算 | `test_native_resume_keeps_consumed_wall_budget` | v2/v3 两路径，耗尽预算后不能继续 OCR |
| 扫描中受控异常、恢复首帧、篡改复用映射 | `test_native_resume_first_frame_is_observed_and_invalid_map_cannot_pass` | 只保留完成帧；恢复无前帧像素时实际 OCR；非法映射不放行 |
| 开优化丢弃旧full/partial | `test_enabling_optimization_does_not_discard_legacy_cache_or_partial` | full命中不改字节，partial按旧合同续扫，不转写为v3证据 |
| PNG编码改变像素 | `test_png_experiment_keeps_all_pixels` | 0/1/3/9四等级逐像素往返；不代表各级性能已实测 |
| 分块篡改、孤立块、非连续前缀 | `test_chunk_integrity_contiguous_prefix_and_orphan_rejection` | manifest/chunk摘要及边界校验，未提交孤立块不作为进度 |
| 修补器恢复丢人脸或跨合同复用 | `test_burned_resume_retains_face_contract_and_does_not_reuse_first_resumed_frame` | 文字/人脸 observations 保留，恢复第一新帧必须识别 |
| 缺失人脸证据 | `test_burned_checkpoint_rejects_missing_face_evidence` | 不缓存为有效整片识别 |
| 优化关闭却偷偷复用/改PNG | `test_burned_checkpoint_only_keeps_every_ocr_call_and_default_png` | 仅分块路径每帧实际OCR，默认PNG不改 |
| dispatch关优化遗漏可恢复断点 | `test_burned_dispatch_scope_selects_chunk_checkpoint_with_optimization_off` | dispatch选chunk-only；不证明真实多任务公平 |
| 保存前让行 | `test_native_yield_occurs_only_after_valid_prefix_was_saved` | 已校验原子前缀落盘后才抛专用让行异常；不是OS强杀试验 |
| 完整 runs/低置信度及边界记录保持 | `test_native_full_frame_scan_reuses_only_exact_pixels_and_preserves_runs` | 全帧计数、实际调用、复用映射、置信度及边界审计保持 |

工具本身的路径/覆盖拒绝、清洁环境、无损导出、严格判等及不授予长片门禁，另映射到 `tests/unit/test_caption_scan_benchmark.py`。新增字体缺字拒绝、历史cache复制不改写及选定源literal/JXA拒绝也在该文件中。

已完成的早期隔离收据：[video-pytest-8w36vlvo/receipt.json](/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/video-pytest-8w36vlvo/receipt.json)、[JUnit](/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/video-pytest-8w36vlvo/pytest.xml)，共37 targeted pass；其清单包含当时10项 benchmark 工具测试及其他模块，**不包含本表 optimization 文件，也不包含之后补的字体/cache工具测试**，不能冒充最终本表通过证据。

最终定向隔离 runner：[video-pytest-lpa2c2w_/receipt.json](/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/video-pytest-lpa2c2w_/receipt.json)，330项通过、6项既有资格测试未执行；其中本表 optimization 22项、benchmark 13项全部通过。叠加现有生产源码副本的联合回归 [video-pytest-e3fjcfbf/receipt.json](/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/video-pytest-e3fjcfbf/receipt.json) 393项通过，包含上述6项资格测试和既有维护入口。最终浏览器/真实媒体回归 `video-pytest-qxfreg80` 19项通过，其 tiny/base ASR、字幕烧录和封面检查不替代本单缺失的语义金标或长片吞吐。

全unit runner `video-pytest-f92kwn8_` 及联合副本 `video-pytest-bjdsbruv` 均在600秒超时退出；不能报告全量通过。主干4处收集缺失导入已在原始28696dd副本复现，其余全量失败归属尚未完全核定。定向通过不消除该限制。

## 未满足的启用门槛

1. **性能未达标**：真实微样本池化中位改善不足20%，Yux退化超过5%；不能用DWb的静止片头代替代表样本收益。
2. **完整长片未测**：没有新旧引擎的完整长片冷扫描A/B、持续资源曲线、周期断点成本或真实partial续扫成本。
3. **语义与质量范围未闭环**：保持原置信度0.5、逐段覆盖95%、最大空隙250ms合同，但本次没有以ASR/逐段语义/人工审阅证明真实素材满足这些门槛；移动、小字、字体风格与复杂背景金标仍待补。
4. **实际故障/调度未替代验收**：本表最终定向单测通过；受控异常与缓存篡改单测不等于OS进程中断、子进程存活、实际竞争者5分钟让行或公平等待已验收。
5. **成片吞吐未测**：没有全链路入组分母、完成/复核/失败/待处理率、有效合格成片/小时或提升20%的证据；尝试数、扫描帧数、cache命中均不能替代。
6. **发布证据不在范围**：未验证成片、发布包就绪、平台受理或独立公开。任何微样本、gold、历史cache结果均不能证明整片noChinese、语义路由正确或授予投稿/历史重投权限。

因此 P1 保持关闭。后续若做更改，继续保留旧 v2 完整/partial及历史决定，在独立新命名空间验证；不能为提速放宽质量门、降低分辨率/抽帧，或删除旧证据以强迫重扫。

回滚遵循[主执行单的回退顺序](2026-10-29_pipeline-throughput.md#回退)：停止新准入、排空执行者及子孙、确认真实FD/锁释放后关闭相关开关，再恢复旧串行器，保留新旧证据。只关闭P1而保留P2上下文时，扫描仍可使用不复用像素的分块断点；不能误报已经切回完全旧路径。
