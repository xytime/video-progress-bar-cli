# 发布故障处理运行手册

本手册记录 2026-07-10 发布断流后的固定处理顺序，目标是先保留证据，再恢复发布，避免重复发布或把真实失败误判为空队列。

## 1. 先判运行态

1. 查看 `ps`，确认是否存在 `pipeline_manager`、`wechat_uploader`、`monitor_channels`。
2. 查 `output/pipeline.db` 中的 `PUBLISHING`、`LOGIN_REQUIRED`、`FAILED` 和最近更新时间。
3. 不直接重试 `PUBLISHING`，先确认视频号后台是否已经接收，防止重复公开发布。

## 2. 微信登录分流

- `/api/wechat/status` 必须同时满足 `logged_in=true`、`login_flow_active=false`、`qr_exists=false` 才能视为可发布。
- 自动上传使用 `--fail-fast-login`，检测到 `login.html` 立即返回 `LOGIN_REQUIRED`，不等待扫码。
- 人工登录使用 `/api/wechat/login` 或 `--login-only --relogin`，扫码成功后必须看到 `wechat_login_at.txt` 更新。
- 登录恢复后只重试已核对未发布的任务，不批量重发未知结果任务。

## 3. YouTube 与频道监控分流

- `SSL`、`exit 101`、超时和真实 `empty` 必须分开记录。
- 先看 `output/monitor_health.json`，再看 `output/monitor.log` 原始错误。
- `Wall Street Truthbombs` 的白名单 ID 是 `UCTK_cv-y88CScoudcXnS1Ew`；单频道探针成功不代表全量监控恢复。
- 全部白名单频道失败时监控脚本返回非零；禁止把失败轮询解释成“没有新视频”。

## 4. 临时放行与复盘

当前 `ENABLE_CHANNEL_POLICY_FAIL_OPEN=true` 和 `ENABLE_TRANSLATION_QUALITY_FAIL_OPEN=true` 仅用于恢复发布，仍保留告警日志。

TODO：

- 修复金额单位漂移、事件方向误判和频道策略误杀后关闭两个 fail-open 开关。
- 将监控健康报告接入 Telegram/仪表盘告警，而不是只落本地 JSON。
- 为发布前登录预检增加独立健康检查，避免任务进入 `PUBLISHING` 后才发现会话失效。
- 固化主干提交和运行版本标识，禁止长期使用未提交工作区作为线上代码。
