# 原片中文字幕自动分流验收

日期：2026-10-27。范围：普通流水线在翻译、原字幕修复和烧录之前决定保留、生成或复核；不触发历史投稿恢复。

## 实现与依赖

`PipelineManager -> auto-caption -> AutoCaptionProcessor -> native_caption_router -> source_caption_contract / native_caption_source / CodexTextProvider`。本机 OCR 使用独立 `native_caption_vision.js`，不改变原有修复器缓存或数据库结构。

新流程复用 ASR 快照，保留路径不生成 ASS、不做字幕遮挡或额外画面叠层；原文与识别出的中文仍送内容审核。一般 CLI 及已指定配音的任务不隐式采用本规则。普通流水线的新字幕加工会显式传入 `--preserve-source-chinese`。

## 验证证据

隔离测试命令：

```sh
.venv/bin/python scripts/run_isolated_tests.py -- -q \
  tests/unit/test_native_caption_source.py tests/unit/test_native_caption_routing.py \
  tests/unit/test_caption_checkpoints.py tests/unit/test_subtitle_censorship.py \
  tests/unit/test_auto_caption_progress.py tests/unit/test_caption_progress_watchdog.py
```

结果：66 项通过。测试证据目录：`/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/video-pytest-f01blv44/`。覆盖部分字幕、低置信度、缺少实际画面核验、引用错误、时间覆盖不足、服务异常、缓存复用、源片变化、旧凭证兼容、裁剪源提交绑定及不重复翻译/烧录。

真实本机 Vision + 项目 Codex 结构化入口测试使用 5 条合成字幕画面视频，每条 2 秒、12 帧，并提供固定对白时间轴；未将此测试宣称为真实语音识别验收。

| 画面 | 结果 |
| --- | --- |
| 完整简体中文字幕，附英文 | PRESERVE |
| 完整繁体中文字幕，附英文 | PRESERVE |
| 纯英文字幕 | GENERATE |
| 只有中文标题 | GENERATE |
| 第一段有中文，第二段只有英文 | REVIEW |

前两条实际执行保留，源文件与交付文件 SHA-256 分别一致，均未产生 ASS：

- 简体：`eb25c2096514f4db91b8e7283abcd5fc93116e79eab129edd5911c561ecfd70e`
- 繁体：`d3970eec36d9d7e99acb98d24bf86198b07c6bd9734f2e71bc05e8f22f383558`

现场证据：`output/diagnostics/native-caption-routing/sample-results.json`、`preserve-results.json` 及对应的单片决定、逐帧证据、模型缓存和实际图像。

另对真实源片 `5Fi-oCg2WxQ` 作独立诊断：完整扫描 1747 帧，自动结论为 REVIEW（部分 OCR 文字未得到逐种文字的实际画面核验），不冒充自动识别成功。该片已有人工确认，因此实际流程仍优先使用人工保留路径。只读验证证明旧凭证有效、凭证文件摘要未变；诊断没有调用发布器或重置任务状态。

## 限制

低清、字幕抖动、部分覆盖、时间轴不支持、模型不可用及预算耗尽均进入现有失败详情中的 `[NativeCaptionReview]` 复核事项。当前自动原样交付仅覆盖竖片；横片需单独核实布局。判定阈值及预算见 [流程规则](../workflows/source-chinese-subtitles.md)。

源代码提交、运行采用与平台发表是不同证据。本次验收不提交新视频，也不确认历史视频已公开。
