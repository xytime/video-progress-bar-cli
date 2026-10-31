---
title: 每日运维工单 (Daily Ops Work Order)
project: YouTube → 微信视频号 自动发布流水线
created: 2026-06-26
author: Claude_Opus_4.8
source: 2026-06-26 自我审查的循环项 + 历史事故教训
---

# 每日运维工单

## 当前入口与人工审核（2026-11-01 更新）

本机已核实使用 cron 的 `daily-ops-workorder`，每天北京时间 **09:00** 执行 `scripts/daily_ops_report.py`；同名 LaunchAgent 未加载。继续复用 cron，**不要重复安装 LaunchAgent**。默认生成本地报告；Telegram 仅在显式 `--send` 时发送，本轮未开启。

日报先生成改进分析：全量未解决存量、上一自然日失败事件、七日趋势；周一追加周度复盘。新分析只读一致性数据库副本，不重试、重置或发布任务。方案、审核和验收保存在独立目录，具体修复逐项人工审核。

```bash
# 仅本地分析，不调用旧健康摘要的余额查询或消息接口
.venv/bin/python scripts/daily_ops_report.py --improvement-only
.venv/bin/python scripts/improvement_review.py show
# 当日默认幂等；明确需要更新时使用 --refresh
.venv/bin/python scripts/improvement_review.py report --refresh
```

`output/improvement/current.json` 指向最后一次完整批次：`runs/<generation>/report.md` 与 `record.json`；`last_attempt.json` 记录采集成功或失败。采集失败保留旧完整报告，旧时间不冒充当前。重复症状更新同一事项，未再出现也不会自动关闭。

审核流程：

1. 阅读报告中事项的 `plan`、版本及 `plan_sha`。默认是 `INVESTIGATION` 调查方案；实际修复应改为 `FIX`，填写完整范围、风险、回退、验收、保护条件和至少七天观察期。
2. 用 `set-plan <事项ID> --file <方案JSON>` 更新方案。实质修改会递增版本、清除旧批准。
3. 人工明确决定后，用 `review <事项ID> --plan-sha <当前指纹> --decision APPROVED|RETURNED|DEFERRED --reviewer <审核人> --evidence <已保存的批准记录文件>` 登记。保存证据的文件路径、字节数与 SHA-256；原文件需保留。模型建议或报告正文不构成批准。
4. `advance <事项ID> --plan-sha <当前指纹> --state <下一阶段> --evidence <验收JSON>` 只登记阶段，不执行修复。JSON 必须有对应 `plan_sha`、`state` 和 `passed: true`。修复按 `IMPLEMENTING → LOCAL_VERIFIED → RUNTIME_ADOPTED → OBSERVING → CLOSED`；关闭还要求实际观察满指定天数、`sample_count` 为正整数。调查按 `INVESTIGATING → ANALYZED`，不能借调查批准实施修复。

工具只验证记录格式与版本，验收内容仍须人工核查。实际执行分母和资源账本不足时，成功率与节省费用保持“不可计算”。批准修复不代表批准重跑历史任务或再次投稿。完整边界见 [已确认规格](specs/continuous-improvement-review-loop-2026-11-01.md)，首份分析见 [字幕异常专题](incident_reports/2026-11-01-caption-failure-analysis.md)。

以下为历史巡检手册和 backlog，**不是本次运行结论或操作授权**。历史“约 24h 必失效”“自动续发”等说法不能替代当前结构化会话状态、任务批准和原生投稿回执；缺少近期验证时先核查，不直接判定登出或重发。

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
- **有片但都 <75 分** → 多为新片播放量未涨够；`rescore_refresh`（每 3 小时的 :15）会批量刷新近期候选的播放量、点赞量与评分，新片优先复查，失败后冷却。它不下载、不加工、不发布。手动：`.venv/bin/python scripts/rescore_refresh.py`。
- **窗口无人执行** → 运行 `.venv/bin/python scripts/verify_publication_policy.py --check-installed-schedule`；若失败，执行 `./scripts/install_publication_window_schedule.sh` 恢复受管的 15 分钟窗口巡航。
- **限流暴涨（exit-101）** → 临时降频：把 crontab 里发现 `*/30` 调回 `0 */2 * * *`、重算 `15 */3 * * *` 拉长。
- **整机被某进程拖死** → `ps -o pid,stat,%cpu -ax | sort -k3 -rn | head`；强杀失效多为 D 态(I/O)或需 `sudo kill -9`；终极手段长按电源键 10s 硬重启（@reboot 会自动恢复 dashboard/bot）。

---

## 四、常驻自动化清单（已挂 cron，无需人工）

| 任务 | 频率 | 作用 |
|---|---|---|
| `daily_ops_report.py` | 每日 09:00 | 本地改进分析、周一复盘与健康摘要；外发需显式授权 |
| `monitor_channels.py` | 每 30 分钟 | 发现新视频 |
| `rescore_refresh.py` | 每 3 小时 :15 | 按到期时间轮转、批量刷新统计并重算，捞回涨上来的候选（黑名单安全）|
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
