# 2026-09-28 英语世界审校预算耗尽重复入选

作者：Codex（模型版本未知）。用户授权：修复并上线。

## 故障与证据

- 原运行：`output/english_world_daily/run_2026-09-28_100003_488310.log`。
- 原目录：`output/english_world_programmatic/20260928_100301_925286_VhCGzz_87-k`。
- `qa/language_execution_error.json`：`ValueError`，同一任务最多三个审校输入。
- 来源片段对应任务 `864b22ca2bf9c9cd8b0083c38509cb578e86e8b307ee080a92baefc42577ff88`：
  账本 `attempts=3`、三个输入键、`inflight=false`；外层 `1/3` 不是这个持久预算。
- 协调器原先直到生成新草稿并进入 review 才检查预算。已锁题后异常安全停止，
  不将技术错误列入来源黑名单，但下次窗口又选中相同已耗尽的来源片段。
- 本次原目录不存在 `english_world.mp4`。只读 SQLite 备份的 DAL 核验中，
  该来源不在投稿保护列表，最近审核项中无匹配项。未核验平台公开页面；
  Telegram 故障通知的接受记录不等于视频交付或投稿。

## 修复范围

源码提交：`f4a68f41dff2dc477201f8cef42833a71e7442e8`，已推送 `origin/main`。

在来源证据确定任务身份之后、锁题与 AGY 草稿之前读取持久审校预算。
耗尽、终止或在途任务写入 `qa/language_admission.json`，然后在原有最多十个
候选的预检范围内继续。失败仍记录到 `candidate_failure.json`，不列为来源质量拒绝。
账本损坏、不可读或未知运行错误停止；锁题后的异常不通过换题绕过。

依赖仍为 `scripts` → `study_cards.language_review_service` → 原有协议与存储辅助函数。
原 review / publication 的三次硬上限、独立审核、投稿保护和内容安全门保持不变。
不清空次数、不改写历史 QA、不更改功能开关、不修改其他会话工作。

## 验证

```sh
.venv/bin/python scripts/run_isolated_tests.py -- -q \
  tests/unit/test_english_world_programmatic_daily.py \
  tests/unit/test_english_world_language_qa.py \
  tests/unit/test_english_world_daily_scheduler.py \
  tests/unit/test_english_world_candidate_budget.py
```

结果：219 passed。隔离边界探针通过，退出码 0。
证据已保存到 `output/english_world_daily/repair_20260928/test_evidence/`。
回归覆盖：实际入口连续跳过十个不可新制候选、不进入草稿/渲染/交付，
不加入来源黑名单；账本不变；新片段独立预算；损坏账本停止；锁题后禁止切换。

生产 venv 加载上述提交，对原始来源证据实际执行新预算检查，得到
`EXPECTED_BLOCK_BEFORE_DRAFT / ATTEMPT_BUDGET_EXHAUSTED`，原账本 SHA256 未变。
证据：`output/english_world_daily/repair_20260928/original_admission/runtime_verification.json`，
其中包含提交和两个源码文件哈希。

已核验 LaunchAgent `com.videopipeline.english-world-daily` 指向当前工作区 venv 与
`scripts/run_english_world_daily.py --coordinator-provider programmatic`，无常驻协调器。
相同入口的单次影子验证保留原共享运行锁、来源通路预检及投稿保护；
不发送 Telegram、不执行平台交付，最长 1200 秒。

```sh
PYTHONPATH=src .venv/bin/python scripts/run_english_world_daily.py \
  --coordinator-provider programmatic --shadow-only --max-attempts 1 \
  --coordinator-timeout-seconds 1200 --log-dir output/english_world_daily/repair_20260928
```

影子运行日志：`output/english_world_daily/repair_20260928/run_2026-09-28_103127_469782.log`。
真实运行先以 `REVIEW_TERMINAL` 跳过 `8H0dTo_9CFU`，再以
`ATTEMPT_BUDGET_EXHAUSTED` 跳过原故障来源 `VhCGzz_87-k`，随后进入 `82Y8O9phXbc`。
原故障的生产入口回执位于
`output/english_world_programmatic/20260928_103452_118880_VhCGzz_87-k/qa/language_admission.json`，
`attempts=3`，`candidate_failure.json` 记录 `locked_source=false`，没有生成新草稿。
`82Y8O9phXbc` 随后因 ASR 零宽词缺少可证明后续边界被来源门禁拒绝。
第四个候选 `Dg1ZmvSCMvk` 的检查返回 `READY / NEW_TASK`，通过来源与候选安全检查，
完成初稿生成并进入独立审校，证据目录为
`output/english_world_programmatic/20260928_103528_596683_Dg1ZmvSCMvk`。
影子验证于本机 10:43:15 完成，`last_run_status.txt` 为 `SHADOW_COMPLETED`、
`exit_code=0`、`attempts=1`，共享运行锁已释放。
生成《英语世界｜加拿大野火背后的科学》，ffprobe 实测 32.68 秒，MP4 大小 7,169,419 字节。
语言 QA（一次调用）、音频 QA、视觉安全、最终交付安全门均 PASS；宿主接受 `kind=production`
的影子请求，日志明确 `host delivery was not invoked`。完整制作验证通过，未发 Telegram、未投稿。
生产定时入口保留原有调度和交付策略，本次未修改。

终态再次核验原故障账本：`attempts=3`，SHA256 仍为
`c5c17b402f8fce69b508c22921e9bee7b7546192ca0935c3bcd0dfa2aa2465bc`。
代码上线、影子成片成功与平台交付是独立事实；本轮无平台受理或公开可见结果。

## 回退

空闲时对源码提交执行具名 `git revert f4a68f4` 并推送主干；不重置账本、不回退
整个工作区，不覆盖并行会话的修改。回退会恢复旧的耗尽任务重复入选问题。
