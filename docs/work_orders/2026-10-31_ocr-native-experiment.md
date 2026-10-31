# OCR 继续提速：实测拆分与原生实验后端

作者：Codex。2026-10-31；属于已批准的 OCR 性能优化范围。**本轮完成实验代码和轻量验证，尚未取得原生后端的真实识别性能/质量验收，不启用生产。**

## 已确认的耗时

本轮重新读取并比较 `ocr-long-isolated-ab-20261030-0235` 的四份完整扫描及收据：同一条 vD0fgM0XZaE，643 秒，19,290 帧，原扫描与 BMP 候选的完整 `frame_count/fps/width/height/runs` 相同。这里只完成两对，原规格要求三对。

| 冷扫描 | PNG/JXA 基线 | BMP/JXA 候选 | 实测降低 |
|---|---:|---:|---:|
| 第一对 | 3577.294 秒 | 2462.044 秒 | 31.18% |
| 第二对 | 3515.647 秒 | 2424.145 秒 | 31.05% |

候选的主要耗时是等待 Vision worker 返回：2404.734、2376.630 秒，占扫描墙钟约 98%。该指标包含 worker 内图像读取/解码、识别、结果转换和通信，不能全部称为模型推理。候选视频解码约 14 秒，BMP 编码/写入 23–33 秒，检查点约 1.5 秒；优先继续压缩这些小项不太可能带来显著收益。

完整像素相等复用仅命中 36/19,290 帧（0.19%），说明运动画面的瓶颈不能靠当前相邻帧缓存消除。不能将相似画面、相同 OCR 文本或字幕区域相似当作全帧相同。

本轮对生产 JXA worker 做了 1 秒只读栈采样：主线程 59 个采样中 43 个位于 `VNImageRequestHandler performRequests`，另见 PNG 解码、base64 和读管道等待。这只是瞬时现场定位，不能据此承诺原生替换能消除 98% 耗时，也不能把等待 Vision 子线程全部算作脚本开销。

上述收益属于既有 BMP 候选，不是本轮原生后端收益，也不是线上收益。全量三轮、语义金标、真实翻译恢复、完整双任务交接及成片吞吐门禁仍独立保留。

## 本轮改动

依赖：`benchmark_caption_scan.py → caption_vision_transport / native_caption_router → 系统 Foundation / Vision`。无核心层反向依赖。

- `scripts/native_caption_worker.m`：原生 Objective-C 常驻进程，逐帧 autoreleasepool；完整 BMP、accurate、`zh-Hans/zh-Hant/en-US`、关闭语言纠正、原始分辨率和全帧范围不变。每帧仍建立原有 request/handler，不实验改用其他识别算法。记录读取、request 初始化、Vision 执行和结果转换四段耗时及当前 OS 的 Vision revision。真实协议回读为 revision 3。
- `caption_vision_transport`：原有 JXA 入口默认行为保持；独立二进制入口仅供显式基准使用。共用完整像素文件、单调请求号、有限超时、STOP 和所属子进程回收。不存在自动选择原生后端的生产分支。
- `benchmark_caption_scan.py`：显式 `--native-worker` 时，对照为 BMP/JXA 与 BMP/原生；默认仍是原有 PNG/JXA 与 BMP/JXA。二进制复制到隔离根并验证 SHA，摘要进入实验扫描身份，不能复用其他后端断点。时序比较继续要求完整结果、完整时间轴和三轮交错顺序。
- 原生 OCR 实验必须显式提供目标生产 `--pipeline-lock`。只读打开现有锁、非阻塞领取；忙就退出，不创建基准输出、不启动 OCR。锁 FD 经 sandbox-exec、基准 Python 传到两种 OCR 子进程；验证 inode 身份，父进程死亡不能使仍在工作的子进程提前释放锁。16GB 主机继续只容纳一个重计算任务。

本轮不新增生产开关、服务、付费供应商、定时任务或自动补跑。保留旧 JXA 文件及其摘要；原有有效扫描、ASR、翻译、质量和发布检查点不迁移、不删除。内容审核、会话互斥、投稿去重和未知结果保护均未改变。

## 实际验证与限制

证据根：[ocr-native-20261031-1145](/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/ocr-native-20261031-1145)。

1. 原生代码在禁止联网、仅隔离根可写的 OS 沙盒内编译成功，clang `-O2 -fobjc-arc -Wall -Wextra`，0.871 秒，未发出编译警告；二进制 SHA `ea47b893395095219cbf580135da82080d0554c94acafe883996209ee6413714`。
2. 实际二进制 INFO、非法 JSON、错误类型、空文件、缺失文件、重复编号和 STOP 回读通过。错误均不返回 `rows=[]`。这些请求没有执行 Vision 识别，不能当作真实画面质量验收。
3. 真实 sandbox-exec → 原生子进程验证：父进程关闭 FD 后，子进程继续持锁；STOP 退出后锁可领取。
4. 实际生产准入检查返回 `OCR_BENCHMARK_BUSY`，生产锁文件字节未变，实验输出目录未创建。生产 w21d64pB9jk 的原 OCR 进程仍在运行；未停止它、未另开识别任务。
5. 最终隔离回归：[video-pytest-ns4m6pue](/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/video-pytest-ns4m6pue/receipt.json)，**211 passed、6 warnings**，runner 退出 0，所属残留进程 0、沙盒清理成功。源码 manifest `1a2ccea7a841927abf16c9b8919d278978fa1131eee76f92aff53f1b74cc9ab7`。覆盖真实管道、锁继承、二进制变更、计量绑定、扫描/检查点、字幕保留、分页核验、准备队列及阶段事件。此轮未重跑全量浏览器/媒体套件。

原生后端真实 OCR 帧数 **0**，合格成片 **0**，发布包 **0**，投稿 **0**。原生后端的 OCR 完成率、复核率、失败率、资源下降和有效成片/小时均未测；不得把这些未知值报告成通过或改善。既有 BMP 两对样本也不足以解除整体验收门禁。

## 后续验收顺序和回滚

优先顺序：先验证原生微样本与 BMP/JXA 的逐帧文字、置信度、位置及完整 runs 一致，再在安排的空闲验收窗口比较七类样本和完整长片三轮。长片验收可能占锁数小时，不能在生产补发等待期间直接开跑。保留现有长片冷扫描中位数至少降低 20%、任何样本不得退化超过 5%、合格成片/小时目标提高 20% 的原门禁；目标是验收条件，不是承诺。

与前一 BMP 候选比较时另行报告原生调用的增量收益。如果没有稳定净收益，或任何帧证据不同，保留 BMP 路径并停止该实验，不能放宽 OCR/字幕阈值。原有置信度 ≥0.50、覆盖 ≥95%、最大连续空隙 ≤250 ms 及原中文字幕保留规则不变。

编译入口为本机 clang + Foundation/Vision，无第三方依赖；二进制应输出到 EXT2T 独立验收根。基准入口：

```text
项目 .venv/bin/python scripts/benchmark_caption_scan.py
  --source <明确原片绝对路径> --output <尚不存在的 EXT2T 验收目录>
  --native-worker <本轮编译的绝对路径>
  --pipeline-lock <目标生产 output/pipeline.lock>
  --run-ocr --probe-only
```

`probe-only` 只做单短段一对，不授予长片门禁；完整验收使用原有三轮模式。未指定 `--run-ocr` 只准备计划/样本。所有输出继续受无网络、隔离根可写的沙盒限制。

回滚不涉及生产状态：结束实验所属进程，关闭继承 FD 后释放锁，继续使用原 BMP/JXA 候选；保留实验收据和全部既有检查点。生产采用范围仍为 **无**。代码只在已存在的隔离分支交付，不切换正在运行且有无关改动的生产 main，不强推、不重投。
