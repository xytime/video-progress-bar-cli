---
title: 每日运维工单 (Daily Ops Work Order)
project: YouTube → 微信视频号 自动发布流水线
created: 2026-06-26
author: Claude_Opus_4.8
source: 2026-06-26 自我审查的循环项 + 历史事故教训
---

# 每日运维工单

> **怎么用**：在本机登录终端一次执行 `./scripts/install_daily_ops_schedule.sh`；之后每天早 **09:00** LaunchAgent 自动跑 `scripts/daily_ops_report.py`，把巡检报告推到 **Telegram**。
> 你只需看那条消息，按本工单「每天须办」处理标红项即可。本文件是配套说明 + 异常处置手册 + 一次性 backlog。

---

## 一、每天须办（看完 Telegram 工单后，1–3 分钟）

| # | 触发条件 | 动作 |
|---|---|---|
| 1 | 工单「微信会话」显示 🔴 已失效 | **重新扫码登录**（见下）。⚠️ 微信服务端 **~24h 硬上限**，与网络/IP 无关——**几乎每天都要扫一次**（2026-06-25 实验已实证：IP 整天没变也照样 24h 失效）|
| 2 | 工单「黑名单泄漏」> 0 | **立即排查**：`get_high_score_pending_videos` 的黑名单过滤是否被绕过；查是哪个频道、是否漏设 BLACKLISTED |
| 3 | 工单「今日发布」异常偏低 / 「失败」偏高 | 查 `output/pipeline.log`；常见根因见 §三 runbook |

**微信重扫命令**（机器上跑）：
```bash
cd /Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing
.venv/bin/python scripts/wechat_uploader.py --login-only
```
二维码会**自动推到你的 Telegram**（sendPhoto 已验证可达），手机微信扫即可；扫完卡 `LOGIN_REQUIRED` 的高分视频会自动续发。

---

## 二、自动巡检项含义（Telegram 工单逐行）

| 行 | 正常 | 异常 → 处理 |
|---|---|---|
| **发布健康** 今日发布/失败/可发队列/在途 | 发布 >0、失败小、队列有货在流 | 全 0 且无在途 → 可能发现断流或会话失效 |
| **黑名单完整性** 已拉黑频道泄漏 | `0 ✅` | `⚠️ N` → 见每天须办 #2，**最高优先级** |
| **微信会话** | 🟢 活跃 | 🔴 → 重扫 |
| **限流** discovery 累计限流跳过 | 缓慢增长正常 | 短期内暴涨 → YouTube 风控加剧，考虑降发现/重算频率 |

---

## 三、异常处置 Runbook（速查）

- **会话失效** → 重扫（每天须办 #1）。
- **黑名单泄漏 >0** → 查 `database.py: get_high_score_pending_videos` 过滤是否完好（应含 `status='BLACKLISTED'` + `blacklisted_videos` 子查询）；确认涉事频道已 `update_channel_status(ch,'BLACKLISTED')`。
- **发布断流（队列 0、新发现也 0）** → 查发现 cron：`tail output/monitor.log`。常见根因（均已根治，复发时核对）：
  - cron 找不到 `yt-dlp`/`deno` → 子进程 PATH 是否含 `.venv/bin` + `/opt/homebrew/bin`（`settings.ytdlp_path` / `_build_subprocess_env`）。
  - yt-dlp 过旧 → `format not available` → `.venv/bin/pip install -U yt-dlp`。
- **有片但都 <75 分** → 多为新片播放量未涨够；`rescore_refresh`（每 3 小时的 :15）会刷新当前播放量重算捞回。它只改评分，不下载、不加工、不发布。手动：`.venv/bin/python scripts/rescore_refresh.py`。
- **窗口无人执行** → 运行 `.venv/bin/python scripts/verify_publication_policy.py --check-installed-schedule`；若失败，执行 `./scripts/install_publication_window_schedule.sh` 恢复受管的 15 分钟窗口巡航。
- **限流暴涨（exit-101）** → 临时降频：把 crontab 里发现 `*/30` 调回 `0 */2 * * *`、重算 `15 */3 * * *` 拉长。
- **整机被某进程拖死** → `ps -o pid,stat,%cpu -ax | sort -k3 -rn | head`；强杀失效多为 D 态(I/O)或需 `sudo kill -9`；终极手段长按电源键 10s 硬重启（@reboot 会自动恢复 dashboard/bot）。

---

## 四、常驻自动化清单（已挂 cron，无需人工）

| 任务 | 频率 | 作用 |
|---|---|---|
| `daily_ops_report.py` | 每日 09:00 | **本工单巡检 → Telegram** |
| `monitor_channels.py` | 每 30 分钟 | 发现新视频 |
| `rescore_refresh.py` | 每 3 小时 :15 | 刷新播放量重算，捞回涨上来的爆款（黑名单安全）|
| `run_publication_window.py` | 每 15 分钟 06:00-21:45 | 只在 Settings 有效窗口内运行完整流水线；重叠轮次跳过 |
| `bot_watchdog.py` | 每 5 分钟 | Bot 存活看门狗 |
| `@reboot vpanel ui/bot start` | 开机 | 自动拉起仪表盘与 Bot |
| `session_ip_probe.py` *(临时)* | 每 30 分钟 | 登录失效实验探针——**实验已结论(候选②)，可删** |

---

## 五、一次性 Backlog（非每日；做完打勾，源自 2026-06-26 自我审查）

- [x] **建「无痛自动化重登」**（2026-06-27 完成可行部分）：✅ 会话失效前预警（keepalive 龄超 22h 推 TG）+ ✅ 二维码可靠推送（`/wechat_login` 无头登录→QR sendPhoto 到 Telegram，手机扫码）。「失效即自动备码」物理上不可行（微信必须人工扫码），已用「预警+远程取码」把重登做到无感。
- [ ] **清理临时探针**：登录实验已结论，删 `scripts/session_ip_probe.py` + crontab 中 `TEMP-WeChat-RCA-probe` 行 + 根目录 `*.err/*.e` scratch
- [x] **更新** `docs/wechat_login_expiry_rca.html` 结论为「候选②服务端~24h硬上限」已坐实（2026-06-26 完成）
- [ ] **提交**未入库的 `vpanel`(运维加固) / `monitor_channels.py` / `session_ip_probe.py` / `docs/*`
- [ ] **视频号手删**误发的黑名单频道视频：VSVUMPwwd98 / g2B1bsreLOc / oLiKg1fjCD8 / INtqRqDJO8k / kne_Q-F-KVM / xMGuEyMaPPY
- [ ] 决定是否按 vpanel 同标准**恢复 bot_daemon 进程管理加固**（曾被还原）
- [ ] **P0 安全收尾（2026-08-18）**：Bot 的旧传输日志曾记录带鉴权信息的请求 URL。已停止新增记录；仍需在 BotFather 轮换 token、更新本机 Bot 配置、重启并验证轮询，随后按保留策略清理旧 `output/bot.log`。同时审计 LaunchAgent 中的明文凭据，迁移到受控本机配置后再移除旧值。

---

*巡检脚本只读、不改状态；报告同时落 `output/daily_ops_report.log`。本工单随运维认知更新。*
