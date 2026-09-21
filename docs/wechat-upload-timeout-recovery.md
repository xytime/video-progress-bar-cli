# 视频号零进度上传恢复

2026-09-21，Codex。

上传等待超过五分钟时，只有页面仍显示“取消上传”、可见百分数全部为零，且
截图落盘成功，上传器才在本次证据目录写入 `pre_submit_upload_timeout.json`
并返回 7。此分支发生在文案、封面和发表操作之前。

管线核对目录、视频路径、凭据阶段及全部既有投稿保护，再由 DAL 在一个事务中
消费凭据和恢复任务。任何活跃投稿账本、历史归档、提交尝试或提交后文件证据
均阻止恢复。普通错误码 1、未知结果 3、受理结果 6 的语义保持原样。

每个视频/切片最多安排两次恢复，分别等待 10、30 分钟。`wechat_upload_retries`
保存不可重复消费的凭据路径、尝试序号和下次时间；候选查询与原子领取均检查
冷却。重新领取后仍走原来的素材验证、内容审查及防重闸门；保留成片检查点。
旧的 FAILED 项没有本次协议凭据，不会因部署修复被重新发布。

每轮正常流水线结束加工后检查交付：允许发布的窗口内，超过四小时没有新的
平台受理，或零进度失败使可领取队列耗尽时，产生 P1 告警。同一事故按四小时
去重；平台暂停或非发布窗口时不告警。Telegram API 受理不代表手机端已读。

日报按北京时间当天零点统计；“今日受理”取不可变投稿尝试，“今日确认公开”
取公开确认账本。后者是确认发生的时间，不能推断作品实际上线时间。
`processed_videos.updated_at` 不再作为发布量依据。“高分待处理”包含冷却项。

依赖方向：`scripts/wechat_uploader.py → core/wechat_upload_recovery.py`；
`pipeline_manager.py → db/database.py → core/wechat_upload_recovery.py`。
核心凭据模块只依赖标准库，数据库 SQL 保留在 DAL 内。

验证入口：

```sh
.venv/bin/python scripts/run_isolated_tests.py -- -q \
  tests/unit/test_wechat_upload_recovery.py \
  tests/unit/test_pipeline_pre_submit_retry.py \
  tests/unit/test_wechat_publications.py \
  tests/unit/test_wechat_duplicate_guard.py \
  tests/unit/test_daily_ops_report_translation_quality.py
```

上述隔离测试不访问真实创作者后台。若需要恢复旧失败视频，应单独核对该视频
的原生作品记录及提交证据，再按具名授权处理；不得伪造新凭据或批量重置历史状态。
