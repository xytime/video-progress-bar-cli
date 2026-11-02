# 2026-11-02 巡航恢复与翻译窗口验收

执行身份：Codex；具体模型身份未从运行时独立核实。
基线：main / 80611c010c762deed8167c161ec5bdb52999bdec。
私有证据目录：`/Volumes/EXT2T/AppDataOffload/ryusei/throughput-recovery-20261102`。

## 范围与保护

恢复受管每分钟公开窗巡航，按原规则处理正常新任务。保留 API 密钥、供应商账户、额度与累计恢复账本。7012/7166/7168/7169/7176 不恢复、不重跑。历史失败事件和现存恢复记录不迁移、不改写；正常业务继续追加新证据。

维护于北京时间 2026-11-02 10:38:45 进入，版本287。测试通过后已使用原生 recover_maintenance_restart.py 完成维护重启，10:51:56 恢复 RUNNING（版本288），10:51:59 部署九步 COMPLETE。运行采用及两轮巡航证据见后文。

`pipeline_preserve_history=true` 默认暂停巡航日志裁剪、旧待筛选过期归档和 ghost pending 整理。现有待筛选清理是 UPDATE EXPIRED，并非删除。正常新任务处理不受此开关影响；显式设 false 可恢复原整理行为，本次不改生产 .env。

## 实测与窗口取舍

只读数据来自 ai_processing_runs / ai_provider_attempts，operation=subtitle_translation；排除 test_speech 等测试任务。

| run / attempts | 源视频 | AGY | Codex | 结果 |
|---|---|---|---|---|
| 2052 / 3485–3490 | AvyHU0m8vdE | timeout 80.038s | budget_exhausted 79.990s | 全失败 |
| 2053 / 3491–3492 | c7mY3lsfGJM | timeout 96.015s | 72.610s，selected=1 | 成功 |
| 2054 / 3493–3494 | SzNTvqvxswM | timeout 96.033s | 69.362s，selected=1 | 成功 |
| 2061 / 3510 | OYWnj6pZvwI | 冷却跳过，无请求 | 42.166s，selected=1 | 翻译成功，后续帧审查人工门禁；不重跑 |

最近真实 Codex 成功曾耗时273.524s，不能仅以42–77s作为上限。Grok没有真实成功样本。AGY的80–96s是失败/超时观察，不是成功所需时间证明。

600s总期限和120s质量预留不变。生产顺序 agy,codex,grok,deepseek,gemini,google 的最坏候选分配由30/300/150/0/0/0改为120/300/60/0/0/0。Codex保留300s，Grok保底60s、有余时仍最多150s，前序未用时间顺延至后序。该取舍优先保留已成功验证的Codex长请求，同时给AGY覆盖既有观察时长的机会；不承诺Grok最坏60s能够成功，也不承诺AGY地区限制消失。

## 人工门禁

新失败本来已有独立 subtitle_recovery.state=NEEDS_REPAIR，不需要重复增加字段。旧记录存在只依赖 processed_videos.error_msg 的缺口，尤其7012的恢复链已经RESOLVED。

所有领取和复核入口增加只读检查既有 publishing_failure_events 中的人工失败证据。改写当前 error_msg 或把旧链标记 RESOLVED 均不等于具名放行；既有 RELEASED 事件才可解除它之前的失败。新放行事件在同一事务绑定当时最大失败事件ID，防止墙钟偏差或旧授权解锁后来失败。无数据库迁移或历史回填。

## 巡航正常状态

新增 Schedules.enable_publication_cruise(expected_cron_sha)，仅允许维护排空、原正常意图通过、精确旧cron摘要匹配且受管入口仍带非阻塞lockf。先备份，再仅解注释一行，完整回读后调用原 record_operational_intent；失败保留维护并保存旧意图。后续原生部署应能 snapshot/baseline。

## 验收边界

代码测试、Git提交/推送、运行采用、实际巡航、新翻译成功样本分别记录。旧run2053/2054仅支持分析，不能作为此次部署后的真实链式样本；AGY本地冷却到期也不代表服务可用。management_verify熔断只阻断对应回查和历史迁移，NEW仍由独立准入、日限和提交证据保护。

## 隔离回归

证据目录：`/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/video-pytest-bg3trny7`。

`.venv/bin/python scripts/run_isolated_tests.py -- -q` 后接下列19个文件：

```text
tests/unit/test_deployment_schedules.py
tests/unit/test_subtitle_recovery.py
tests/unit/test_subtitle_provider_window.py
tests/unit/test_publishing_recovery.py
tests/unit/test_database_codex_text_recovery.py
tests/unit/test_database_media_recovery.py
tests/unit/test_retry_review_state.py
tests/unit/test_publication_window_runner.py
tests/unit/test_publication_maintenance_drain.py
tests/unit/test_publication_eligibility.py
tests/unit/test_queue_waitlist_governance.py
tests/unit/test_subtitle_recovery_cli.py
tests/unit/test_subtitle_failure_receipt.py
tests/unit/test_subtitle_exhausted_reserve.py
tests/unit/test_subtitle_sparse_processor.py
tests/unit/test_native_caption_routing.py
tests/unit/test_native_caption_sampling.py
tests/unit/test_in_place_captions.py
tests/unit/test_source_caption_fallback.py
```

结果：414 passed、0 failed、0 skipped，12项弃用警告，pytest耗时76.57s；OS边界探针与测试退出码均0，隔离副本已由测试工具正常回收。源码清单包含原工作区其他未提交代码；只提交本次增量，部署仍逐文件核对实际测试清单。

## 最终运行回执（北京 2026-11-02 11:00）

代码提交 `8493e459d877ab3a221884de37a4f2ec0e563877` — `fix(pipeline): restore cruise safely and protect subtitle review gates`，已推送 origin/main。

- 维护：10:38:45 进入，10:51:56 恢复 RUNNING；巡航按每分钟恢复。crontab 与 operational-intent.json 一致，原始二者及 launchd 定义已备份到证据目录的 cruise-activation/。
- 发布策略校验：` .venv/bin/python scripts/verify_publication_policy.py --check-installed-schedule` 通过。
- 原生部署：`deployment-v2/journal.json` 为 COMPLETE，九步 baseline/freeze/stop/backup/adopt/start/resume/restore/verify 全通过。首次 plan 因 UNEXPECTED_UNKNOWN 拒绝，尚未停止或采用；保留该目录，再经空闲核验建立新计划，未绕过未知检查。
- UI 16052 → 32455；Bot 16171 → 32689；ready-worker 16463 → 33049。新执行者采用源码哈希 `700ee0917c397acc3a062e41bd0bf8b7df87b88e274b86e8cc1815334f80f3c0`。549个实际运行文件与隔离测试清单一致。
- 10:52 / 10:53 / 10:54 巡航均正常触发，因为重启后的调度轮持有作业锁而退出，没有排队积压；该调度轮把7157于10:54:13提交为 UNDER_REVIEW。
- 第一轮实际接续巡航：`1793588108-34203`，10:55:08 → 10:58:08；7167于10:58:07变为 UNDER_REVIEW。management_verify 熔断继续阻止管理回查和 HISTORY，未阻断 NEW。
- 第二轮：`1793588342-35462`，10:59:02 → 10:59:03，COMPLETED；没有合格候选，正常结束，无错误重试。
- 日限按实际 DAL 口径：普通 NEW 11 + English World 0 = 11/20。原报告的“已领取10”是包含CANCELED行的原始领取数，不能直接等同当前有效日限占用；本次未修改计数规则。
- 视频号发布准入 allowed=true、blockers=[]；授权最近验证时间有正常业务刷新。日志中的旧“4小时无受理”健康警告仍存在，不能将准入正常当作新视频号投稿成功。
- 观察段 TaskLeaseBusy=0、新 publishing_failure_events=0。五条指定视频均未自动重跑，字幕门禁仍为 NEEDS_REPAIR。
- 7012、7166分别在10:54:39、10:54:38发生并发控制台 POST /ignore，成为 IGNORED，error_msg也改变；本次执行未调用这些接口、未回滚该操作。历史失败事件仍能锁住两条任务。其余三条指定视频记录未变。
- 原174条失败事件、21条字幕恢复记录、33份Codex恢复JSON逐项保持原值/原哈希；没有清账、改额度、改API密钥或供应商账户。保存的原有工作区非本次修改未被覆盖。

证据：同一私有证据目录的 acceptance-final.json、historical-integrity-final.json、cruise-observation.log、runtime-adoption.json、new-translation-candidate-blockers.json。

## 尚未完成的真实样本验收

截至11:00，部署后新增字幕供应商attempt为0，新增成片为0；上述两条是既有成片的抖音补同步受理，不是新渲染，也不是公开可见证明。

正常候选查询为0：6216/5756未满足TED点赞率门槛，7172等待源字幕有界重检。AGY仍因region_restricted冷却到12:44:54；不清冷却，不强制重跑。旧run2053/2054已证实AGY失败后Codex成功，但不能冒充此次上线后的新链式样本。Grok仍无真实成功样本。此项必须保留未验收，待正常调度遇到合格新视频且AGY实际尝试后补证，不能以单测或冷却时间推算替代。

## 核实后不成立或需修正的假设

1. 发布不只依赖4小时调度：独立ready-worker还会约每15秒巡查成片；恢复每分钟完整巡航主要补足包括抖音NEW同步在内的完整轮次。
2. 30秒偏紧属实，但AGY的80–96秒是失败/超时，无法据此证明120秒必然成功；Codex也不只需要42–77秒。
3. 人工门禁并非全部只依赖error_msg，新失败本来有独立状态；旧历史事件缺少稳定复核才是本次补强处。
4. management_verify熔断并不全局禁止NEW，本次两条实际受理直接验证这一点。
5. 待筛选TTL整理是归档为EXPIRED，不是删除；日志裁剪则确实替换旧日志，已暂停。

## 本次文件清单

| 文件 | 改动 |
|---|---|
| src/video_processing/utils/subtitle_provider_window.py | CLI最坏120/300/60，保留总限、质量预留及快速失败让时。 |
| src/video_processing/db/subtitle_recovery.py | 只读历史失败事件硬门禁，具名放行绑定已存在事件序号。 |
| src/video_processing/core/deployment_schedules.py | 维护下备份、解注释受管巡航并验证正常调度意图。 |
| src/config/settings.py | 声明默认保留历史开关。 |
| .env.example | 记录保留历史开关，不改生产.env。 |
| scripts/run_publication_window.py | 保留历史时跳过日志裁剪。 |
| src/video_processing/pipeline_manager.py | 保留历史时跳过旧待筛选/ghost归档整理。 |
| tests/unit/test_subtitle_provider_window.py | 当前生产顺序、实测链时长及Grok余时窗口。 |
| tests/unit/test_subtitle_recovery.py | 文案改写、旧RESOLVED链、新失败与旧放行的隔离。 |
| tests/unit/test_deployment_schedules.py | 巡航备份/回读/后续部署，以及维护与漂移拒绝。 |
| tests/unit/test_publication_window_runner.py | 保留历史不裁剪、不写裁剪状态。 |
| tests/unit/test_publication_maintenance_drain.py | 两种历史保留模式及维护排空边界。 |
| docs/acceptance/2026-11-02-throughput-recovery.md | 需求取舍、完整测试命令、上线与剩余样本验收回执。 |
