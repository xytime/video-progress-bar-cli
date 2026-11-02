# 2026-11-02 巡航恢复与翻译窗口验收

执行身份：Codex；具体模型身份未从运行时独立核实。
基线：main / 80611c010c762deed8167c161ec5bdb52999bdec。
私有证据目录：`/Volumes/EXT2T/AppDataOffload/ryusei/throughput-recovery-20261102`。

## 范围与保护

恢复受管每分钟公开窗巡航，按原规则处理正常新任务。保留 API 密钥、供应商账户、额度与累计恢复账本。7012/7166/7168/7169/7176 不恢复、不重跑。历史失败事件和现存恢复记录不迁移、不改写；正常业务继续追加新证据。

维护于北京时间 2026-11-02 10:38:45 进入，版本287。完成测试后使用项目原生维护重启部署工具，核验源码清单、工作进程身份及正常调度意图，再恢复 RUNNING。运行采用和两轮巡航证据需在完成后补记。

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
