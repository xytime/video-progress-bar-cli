# TED/TEDx 原片去开场等待验证

作者：Codex；2026-10-09；范围：本地实现及媒体验证，不含平台发布或留存率实验。

## 最终代码验证

隔离入口：`.venv/bin/python scripts/run_isolated_tests.py -- -q`，选取
`test_speech_opening`、`test_insight_editorial`、`test_insight_processor`、
`test_insight_processor_v2`、`test_insight_advisory`、`test_pipeline_title_consistency`、
`test_video_slicer` 和 `test_ready_publication_dispatch`。

结果：**108 passed in 27.90s，退出码0，无跳过**。
证据根：`/private/tmp/video-pytest-3xz30yjl/`；边界探针退出码0。
源清单 SHA256：`bf4fb83025f3023b819bd13063f7c004a971d8b2b7418787ac79f794de9ae69e`。

覆盖：真实离线 VAD、真实 FFmpeg 编码及全片解码、短问候保护、
源文件字节不变、源与目标重合保护、缓存及损坏回退、异常后重试、
绑定字幕/原片/竖版摘要、二创原片解析、自动采用、关闭开关及历史/切片/人工范围保护。
二创导读的绘制、旁白、长度及合成方法未修改。

## 本地真实开场检查

从已有原片只读复制前三十秒，在测试沙盒中离线处理；不写生产 output。
使用同一 v5.1 固定模型、最终裁剪算法及原有 FFmpeg 共享名额机制。
独立检查代码仅将共享名额目录重定向到测试临时目录，保持生产锁不受影响。
初次检查因未重定向名额目录被沙盒拒绝，返回原片；修正验证夹具后得到下列结果。

| YouTube ID | 决策 | 删除秒数 | 裁剪副本 SHA256 |
| --- | --- | --- | --- |
| 1qmF_znXxrE | 开头已有疑似讲话或收益不足，保留原片 | 0 | 不生成 |
| Uk31lVtda2g | 首次可靠讲话前连续非讲话 | 9.356 | be576a1550c37e56836d58e812cbd4b7311a3121a694735254bcdd57c6cb7811 |
| 6xbG8OLQYys | 首次可靠讲话前连续非讲话 | 8.332 | 6e8c537fd24d028913ec4acebc4f50553c332f0f95ef66f2573e54cb585b97f1 |

两段副本完整解码退出码0，无解码错误；生成时音视频起止及预期时长校验通过。
Uk31lVtda2g 的首帧黑场来自原片同一切点；副本1秒处已是演讲画面。
按音频边界保留原始音画次序，不为提前见到讲者而继续向后裁剪。

真实开场收据及首帧：
`/private/tmp/video-pytest-xh7x38ql/sandbox/tmp/real-openings/`。
这些是临时本地证据，未作为生产视频发布。

## 限制与交付边界

三条样本不代表整体准确率；模型概率不能识别开场重要文字、无声演示或角色语义。
复杂情况不引入人工确认，按照[规格与研究任务](../specs/ted-opening-trim.md)继续研究。
首版只自动加工 TED/TEDx 新整片，已有成片不重制；成本为离线检测加一次独立原片编码。
这份报告不宣称完成新视频的线上整链路加工、平台上传或公开播放。
