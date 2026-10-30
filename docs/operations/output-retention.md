# output 双七天清理

2026-10-31 经确认启用的规则：资源与所属任务都闲置满七天后，移到仓库外隔离；隔离成功后再观察七个完整的 24 小时，到期复核通过才删除。原文件修改时间不能缩短观察期。

`scripts/run_output_retention.py` 默认只预览。配置、隔离数据与每轮回执位于：

```
/Volumes/EXT2T/AppDataOffload/ryusei/VideoOutputRetention/
  policy.json
  latest.json
  runs/
  store/owner.json
  store/items/<id>/receipt.json
  store/items/<id>/payload
```

隔离使用同卷原子移动。移出仓库可减少 Git/IDE 扫描；只有到期实际删除才可能释放磁盘空间。APFS 快照、并发写入等会影响实际可用容量，不把逻辑字节数当作释放容量。

## 保护与运行边界

- 运行中的任务、打开文件、Git 跟踪文件、任务状态不明、失败/可重试任务、切片尚未完成、跨平台待确认、有效 manifest 依赖均保留。
- SQLite 数据库及 WAL/SHM、账号/浏览器会话、凭据、锁/PID、审核和提交证据、回执不参与七天清理。字幕文件保守保留，不能用本工具绕过字幕证据保留规则。
- 原片、成片等普通产物仅在能关联到真实任务、全部相关交付终结且最后活动满七天时成为候选。仅有历史路径记录不等于永久保留；没有可靠归属仍保留。
- 缓存只接纳可识别的 HyperFrames 帧缓存，以及历史测试快照内的 `sandbox/browser`、`sandbox/pytest-tmp`。历史 `sandbox/repo`、报告和顶层回执保留。
- 实际卷 UUID、目录身份、文件树元数据与工具所有权回执必须匹配。不跟随软链接，不接管任意 staging 目录；收据丢失、篡改或操作中断均停止自动删除。
- 每日一次、低 CPU 优先级、有时间/条目/容量预算且互斥。使用现有维护准入锁；忙碌则跳过，不停止或重启视频任务，不修改 cron 并发。
- 每轮最多 128 项、64 GiB 逻辑资源、300 秒；单项树扫描另有预算。先检查忙碌再扫描目录。引用清单只读明确的处理 manifest/timeline/contract/render/publication/job/script；历史下载元数据、OCR 和证据报告保留原文件，不当作当前处理依赖。
- 隔离后出现明确新引用时尝试恢复；原路径已出现新文件则保留隔离项并报冲突，不覆盖。

## 运维命令

以下命令都在项目根目录执行，使用项目虚拟环境；`CONTROL` 不是系统环境配置。

```zsh
CONTROL=/Volumes/EXT2T/AppDataOffload/ryusei/VideoOutputRetention
.venv/bin/python scripts/run_output_retention.py --control-dir "$CONTROL" status
.venv/bin/python scripts/run_output_retention.py --control-dir "$CONTROL" run
.venv/bin/python scripts/run_output_retention.py --control-dir "$CONTROL" run --apply
.venv/bin/python scripts/run_output_retention.py --control-dir "$CONTROL" restore <receipt-id>
```

`BLOCKED_UNKNOWN`/`SKIPPED_BUSY` 是未执行文件变更；先查看 `latest.json` 的原因，不放宽保护条件，不自动清理业务状态。`PURGING` 中断不自动续删，需要人工检查。

初始化只面向一个新空目录，绑定当前真实外盘 UUID；旧批次接管必须显式指定完整且逐项身份匹配的回执：

```zsh
.venv/bin/python scripts/run_output_retention.py --control-dir "$CONTROL" init --volume /Volumes/EXT2T
.venv/bin/python scripts/run_output_retention.py --control-dir "$CONTROL" import-legacy \
  /Volumes/EXT2T/AppDataOffload/ryusei/DiskCleanupStaging/2026-10-31-video-output-quarantine/receipt.json
```

接管只移动已隔离数据到具名 store，原回执保留；可重复执行并按工具收据续接，不重复隔离。该批次原隔离成功时间为 `2026-10-31T06:34:53.191215+08:00`，最早可清除时间是 `2026-11-07T06:34:53.191215+08:00`。

## 每日任务与停止

本机 LaunchAgent：`~/Library/LaunchAgents/com.video-processing.output-retention.plist`，每日 04:15，`Nice=15`，不唤醒、不保活、不在加载时立即执行。Mac 休眠期间的 calendar 任务可能在恢复时补触发，仍重新检查运行条件。

模板见 `scripts/com.video-processing.output-retention.plist`。启动工作目录和标准输出/错误位于本机用户目录，避免 launchd 在执行 Python 之前因外盘工作目录或日志路径访问失败；业务配置、隔离项和运行回执仍在外盘。标准日志：`~/Library/Logs/VideoOutputRetention/`。

```zsh
launchctl print gui/$(id -u)/com.video-processing.output-retention
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.video-processing.output-retention.plist
```

停止任务不会删除隔离数据。恢复单项使用上面的 `restore` 命令；不要手工编辑带完整性校验的收据。Git 优化已经通过移除误跟踪的生成文件完成，`output/` 保持原位置，数据库和流水线无需迁址。

## 验证

只使用隔离测试入口：

```zsh
.venv/bin/python scripts/run_isolated_tests.py -- -q \
  tests/unit/test_output_retention.py tests/unit/test_output_retention_cli.py \
  tests/unit/test_output_retention_db.py tests/unit/test_output_retention_store.py \
  tests/unit/test_output_retention_guard.py
```

覆盖双七天门槛、只读 WAL 账本、切片/跨平台保护、真实互斥锁、卷身份漂移、软链接/FIFO、恢复冲突、收据篡改、文件变化与中断恢复。线上首轮回执、微型隔离/恢复验证以及 LaunchAgent 运行状态另存于外部 control 目录，测试通过不等于每日任务已实际完成到期删除。
