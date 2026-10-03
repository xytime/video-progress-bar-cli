# TED/TEDx 点赞率发布限制

2026-10-03 用户确认：在原有评分条件外增加源 YouTube 点赞率 **严格 >0.6%**，评分保持不变。

- 适用精确频道：TED `UCAuUUnT6oDeKwE6v1NGQxug`、TEDx Talks `UCsT0YIqwnpJCM-mx7-gSA4Q`。
- 点赞率 = 源视频点赞数 / 播放数 × 100。恰好 0.6% 不放行，显示值不参与判断；缺失指标、零播放不放行。
- 切片使用父视频指标。候选过滤在 LIMIT 前执行；加工前和视频号提交前从数据库重新核验。
- `TED_MIN_LIKE_RATE_PCT=0.6` 为百分数单位。`SPEECH_PUBLISH_SCORE_LINE=40`、新视频评分托底及 `TED_AUTO_PUBLISH_AFTER_ID=4812` 历史隔离保持。
- 未提交且不达标的任务保留评分和已有缓存，等待监控刷新指标；不修改既有投稿或公开作品，不重投历史视频。
- 回归证据：严格边界、指标缺失、其他频道、双候选入口、已就绪及高分任务、父视频指标、排队快照失效、提交账本保护，以及原有评分和发布测试。
- `output/ready_publications_status.json` 的 `ted_min_like_rate_pct` 和 `speech_publish_score_line` 可回读常驻发布执行者已加载的配置。
