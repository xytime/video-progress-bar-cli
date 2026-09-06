# 2026-09-07 Telegram 告警线索代码审查与修复

| 版本 | 日期 | 作者 | 说明 |
| --- | --- | --- | --- |
| 1.0 | 2026-09-07 | Codex | 今日回执关联、四项缺陷复现、修复与验证边界 |

## 范围与证据

审查起点为 `main` 的 `c2fb04b`，初始工作区干净。时间按 Asia/Shanghai；数据库 `created_at` 为 UTC，今日范围从 `2026-09-06 16:00:00` 开始。

Telegram 桌面只读截图可见机器人 07:00 的今日巡检告警预览；聊天点击被本机辅助功能接口拒绝，未取得完整聊天正文。因此以下消息关联依据本地 `telegram_notification_receipts` 的 API 接受回执及同时段日志，不声称已逐条读取 Telegram 客户端或确认用户已读。

- 消息 `7150`：01:16:54，`pipeline.video_failed`，API ACCEPTED。对应视频 `rUhllpnYWR8`（How to Make Learning Impossibly Fun），`processed_videos.error_msg` 保存完整文案失败堆栈。
- 消息 `7159` 至 `7163`：05:39，英语世界审核文字及三个附件、延后状态通知，API ACCEPTED。审核项 `3bc60cc48b234f20a0d032eab70e6ca3`。
- 消息 `7169`：06:48:36，`english_world.reconciliation_recording_required`，API ACCEPTED，同一英语世界项达到两次回查失败阈值。
- 消息 `7170`：07:00:56，`pipeline.status`，API ACCEPTED；完整消息正文未取得，不将预览中的告警逐项认定为代码故障。
- `output/pipeline_window.log`：05:40 起反复出现 `deferred submission worker returned 10`；06:15 同一项最终领取，06:16 受理并绑定原生 ID。这说明此前是正常等待锁，并非投稿失败。

## 发现与修复（按严重程度）

### P1：接口正文被当作平台状态，且覆盖同 ID 页面证据

位置：`scripts/wechat_uploader.py` 的 `_load_management_cards()`、`verify_management_publication_by_id()`。

原实现将接口 `desc` 写入 `card_text`，再用 `cards.update()` 覆盖同 ID 的 DOM 卡片，最后调用状态词解析器。普通正文会永久得到 UNCERTAIN；正文恰为“已发布”“审核未通过”等独立词时则可被误判为终态。新回归测试直接复现这两类错误。今日 06:48 告警所走代码也使用了该路径；旧证据只保存截图，无法还原当次原生数值状态。

修复：接口正文仅供身份绑定；合并时单独保留同原生 ID 的 DOM 状态文本和链接。API-only 记录不再从描述推断发布状态。数值 `status=0` 不再被 `or ''` 吞掉，读取结果另存 `management_readback.json`，记录原生状态与 `API_STATUS_UNMAPPED` 等原因。未增加未经验证的数值枚举映射。

### P2：标题合同失败后原样重试，缺少纠错反馈

位置：`scripts/copywriter.py` 的 `generate_wechat_content()`。

01:16 的 Gemini 首次响应因平台标题 19 字超过 6–16 字限制被拒；第二次仍收到同一提示词，随后再次抛出 `TitleContractError`，进入翻译兜底，最后因缺少中文主旨失败。原代码既没有向第二次请求提供被拒标题，也没有提供具体合同错误；第二次失败日志还丢失具体错误信息。

修复：保留原来源和事实约束，向已有的一次重生成请求补充三个被拒字段、具体校验错误以及完整改写要求。第二次失败也记录具体合同错误。调用次数上限和内容守门保持不变。用替身验证收到反馈才返回合格标题，并验证两次都不合规时仍失败关闭；未调用真实 Gemini 验证该视频的修复效果。

### P2：失败通知截取 INFO 前缀，真正异常被丢弃

位置：`src/video_processing/pipeline_manager.py` 的 `_notify_failed()` 及 CalledProcessError 日志分支。

旧通知将整段 stderr 折叠后截取前 200 字；今天的错误以多行 SDK INFO 日志开头，真正的 `ValueError: WeChat copy quality guard blocked output` 在最后。日志同样只截前 500 字，进一步隐藏根因。

修复：通知取最后一个非空行并保留 HTML 转义；日志保留末尾 500 字。数据库完整错误仍保留。回归覆盖 INFO 前缀加 traceback、单行错误和空白输入。

### P2：正常延后退出码 10 被记录为 ERROR

位置：`scripts/run_publication_window.py` 的 `dispatch_one_deferred_english_world_submission()`。

专用投稿器明确以 `EXIT_DEFERRED=10` 表示锁忙、暂停或窗口限制下尚未领取；调度器却将任意非零退出码记为 ERROR。今天 05:40 起的连续错误就是该分支。

修复：10 记 INFO 并保留批准队列；真实失败仍记 ERROR。回归覆盖退出码 0、10、1，不改变领取、锁或发布策略。

## 验证与边界

新用例在修复前复现 7 个失败断言，另加通知用例复现 1 个失败；修复后执行相关 8 个测试文件，结果 **173 passed**：

```sh
PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/unit/test_copywriter.py tests/unit/test_title_contract.py \
  tests/unit/test_publication_window_runner.py tests/unit/test_publish_confirmation.py \
  tests/unit/test_english_world_submission_window.py tests/unit/test_pipeline_pre_submit_retry.py \
  tests/unit/test_english_world_jobs.py tests/unit/test_english_world_delivery_reliability.py
```

本次没有手动调用生产任务、Gemini、Telegram 发送或视频投稿，没有重置失败/审核/熔断账本。历史英语世界项仍是 `UNDER_REVIEW`、`platform_state=UNCERTAIN`；旧 `.delivery.json` 是 05:39 的投递快照，不能作为后续平台状态。已有截图显示作品列表中的相关内容，但不据此宣称公开可见。API 数值状态语义尚未核验，该项的公开状态与自动回查恢复仍未验证。
