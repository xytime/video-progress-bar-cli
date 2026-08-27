# Handoff

## Current task

英语世界短视频日更的制作、Telegram 交付和视频号受理链路已收口；当前发布状态仍待平台公开可见确认。

## Completed

- 修复日更协调器：只有本次机器回执 `ACCEPTED` / `SUPPRESSED` 才算交付成功；`PENDING` 失败关闭。
- 修复词汇富化：缺 IPA 候选不会进入成片。
- 新增窗口后监测：主任务 07:00、16:30；监测 09:15、19:00。仅当原窗口完全未启动时补发起一次，已有运行或失败记录绝不重跑。
- 修复通知器兼容 `timeline.enriched.json`；此前仅识别下划线命名，导致质检通过的成片无法投递。
- 已推送主干：`1def19b`、`75ba7d8`、`6a492c3`；工作树干净。

## Evidence and artifacts

- 2026-08-27 16:30 实际 LaunchAgent 运行；成片来源 `JzRFCm_TfGQ`（CBC Kids News），MP4 31.480 秒、1080x1920 H.264/AAC。
- 本次回执 `output/english_world_daily/run_2026-08-27_163000.delivery.json`：`review_and_auto_submission` / `ACCEPTED`，Telegram message IDs `6478`–`6483`。
- 审核项 `068a9ad4354b46d78f984901f45207af`：`UNDER_REVIEW`；提交开始/结束为 2026-08-27 08:41:26–08:42:43 UTC；`uploader_exit_code=6` 的语义是“视频号已受理、等待审核”，不是失败。
- 平台证据目录：`output/english_world_daily/2026-08-27/JzRFCm_TfGQ/wechat_evidence/1787820086829738000`。
- 相关回归：最终 `34 passed`。

## Blockers / open questions

- 尚无创作者后台的公开可见证据。因此只能报告 `UNDER_REVIEW`，不能报告已公开发布。

## Next steps

1. 只读查看创作者作品管理页，按平台作品身份确认该条是否公开；确认后才写 `PUBLISHED`。
2. 若仍审核中，保留现有账本与证据，禁止重复上传。
3. 观察下一次 07:00/16:30 回执及 09:15/19:00 监测健康 JSON。

## Pitfalls and constraints

- 本地 MP4、Telegram API 接收、视频号受理、作品公开可见是四种不同证据。
- `UNDER_REVIEW` / `UNCERTAIN` 是重传停止状态；不得直接调用通用上传器或重置队列。
- 英语世界只走 `notify_english_world_review.py` / `submit_english_world_review.py` 的隔离账本路径。
- 不要再假设 enriched 时间线都叫 `timeline_enriched.json`；生产器也会输出 `timeline.enriched.json`。

## Updated

2026-08-28 03:26 CST
