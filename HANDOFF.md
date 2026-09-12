# Handoff

## Current task

`Video-precessing` 重构尚未开始实施。2026-09-12 已完成一次只读的独立架构 / Red-Team 审计，结论为 **REVISE BEFORE IMPLEMENTATION**：保留账本优先、隔离测试和单事务等安全骨架，但将路线改为“先封已知生产旁路与候选防火墙，再做最小 Harness，最后渐进拆分”。预计最快下周继续。

## Completed

- 完整审阅生产 checkout 下 `docs/refactor/video-processing/` 的 7 份治理文档，以及 PipelineManager、PipelineDB、Web、Telegram Bot、微信上传器和新增测试/fixture。
- 确认最高优先级风险：Telegram `PipelineAgent` 暴露直接微信上传、任意状态更新、删除和重试工具；`/run` 会手工串联这些工具。直接上传器把微信 uploader 的“已受理待审核”退出码 6 当作失败，可能形成 `平台已受理 -> FAILED -> 后续重试`。
- 确认中心候选 SQL `get_high_score_pending_videos()` 未排除 `source='DISCOVERY'`；Web 单视频入口虽有 guard，但定时调度直接消费该 SQL。
- 确认 `GOLDEN-WF-01` 用 score=88 的 DISCOVERY fixture，并期望其成为自动候选，与项目“DISCOVERY 只读浏览、永不自动发布”契约相反。
- 确认当前 Golden Replay 实质为 6 个 DAL micro-contract 场景：Run A/B 是同一实现运行两次，没有覆盖完整 workflow、真实 stage runner、10 类故障或点击边界注入。Gate M6 不应标为已通过。
- 确认三个平台都不应描述为 exactly-once：微信接近 `at-most-once automatic retry + manual reconciliation`；抖音是 `at-most-once browser launch per ticket + manual reconciliation`；快手是 `best-effort idempotent + manual reconciliation`。
- 已明确推荐 Hybrid Plan B：先 containment，后契约修订和最小 Harness，再按域拆 PipelineDB、按阶段拆 PipelineManager、逐个平台迁移 publication。
- 本轮没有改源码、测试、数据库、运行配置，没有重启服务，没有调用上传器、Telegram 或任何创作者平台。

## Evidence and artifacts

- 权威计划文档目前只存在于生产 checkout：`/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/refactor/video-processing/`。
- 关键源码证据：
  - `src/bot/pipeline_agent.py:151-170,178-206,637-752`
  - `src/bot/telegram_bot.py:1562-1572`
  - `src/video_processing/db/database.py:3262-3359,4105-4158`
  - `src/video_processing/pipeline_manager.py:1465-1535,4106-4230`
  - `src/web/app.py:610-644,842-856,2128-2174`
  - `scripts/wechat_uploader.py:2569-2618`
- Golden 反例：`tests/fixtures/golden_replay/scenarios/GOLDEN-WF-01/initial_db.json` 中 `source=DISCOVERY`；`contract.json` 期望 `step_1_candidate_found=true`。
- 隔离目标测试已通过：`.venv/bin/python scripts/run_isolated_tests.py -- -q tests/unit/test_characterization_baseline.py tests/unit/test_golden_replay_dataset.py`。
- 完整非浏览器单元测试已通过：`1635 passed, 12 warnings, 30 subtests passed in 49.51s`；receipt 当时位于 `/private/tmp/video-pytest-yl4x10cz/receipt.json`。
- 未运行 browser/media 全套，因此不得声称真实 Playwright、FFmpeg、ASR 或媒体重放已验证。
- 当前 Codex worktree `/Users/ryusei/.codex/worktrees/3df5/Video-precessing` 为 detached HEAD；本轮架构材料不在该 worktree 中。
- 生产 checkout 位于 `main`，但原本已有无关 dirty changes；`docs/refactor/`、Golden fixtures 和两个新增测试仍为 untracked。本轮未整理、提交或推送它们。

## Blockers / open questions

- 最高优先级 Bot 旁路和 DISCOVERY 自动候选漏洞都只完成审计，尚未修复。
- 治理文档、新 fixture 和测试尚未进入 Git，不能视为正式 System of Record。
- 下周开工前需先区分生产 checkout 中现有无关改动的归属，禁止把它们混进重构提交。
- 尚无真实 Bot 调用记录证明上述旁路曾产生重复投稿；该不确定性只影响事故发生史，不影响源码风险成立。
- 尚无 browser/media、断电/磁盘满、WAL/恢复、点击前后故障注入证据。
- 旧 HANDOFF 中 2026-08-27 的英语世界 `UNDER_REVIEW` 状态本轮没有重新核验；不得依据旧状态自动重传或宣称已公开。

## Next steps

1. 在生产 checkout 开工：先只读运行 `git status --short --branch`、核对 `main`/`origin/main`、确认流水线和浏览器任务空闲；阅读本 HANDOFF 及 `docs/refactor/video-processing/`。不要在 detached worktree 实施线上改动。
2. 将首批范围冻结为两个安全修复：A) Bot 不再直接持有 uploader、任意 status、delete、retry；统一走 canonical application service；B) 在中心 DAL 候选咽喉排除 DISCOVERY，仅允许原子 promotion 后进入 MANUAL。
3. 先补能真实击中入口的回归测试：Bot 退出码 6、Bot 已有账本时的 mutation、score>=75 DISCOVERY 不进入自动候选、promotion 后可进入。
4. 实施上述最小修复；安全回滚应关闭 Bot 写操作，不能通过 feature flag 恢复已知不安全透传。
5. 修订治理契约：M6 标为 PARTIAL；INV-003/INV-008 与 RISK-STATE-001/002 重新定界；当前 Golden 改称 DAL micro-contract suite。
6. 使用隔离 runner 先跑目标测试，再跑完整非浏览器单元套件；只有任务明确需要时才运行 browser/media，严禁真实投稿。
7. 首批修复验收后，再规划 Runner/context/checkpoint 的纯提取；PipelineDB 保持外部 Facade、内部按域单路径迁移；publication 按 WC/DY/KS 分开实施。
8. 仅在确认目标 diff、测试证据和流水线空闲后，按项目纪律将目标文件单独提交并推送 `main`；分别报告“文件已改、测试通过、已提交、已推送、运行采用”，不得混称已上线。

## Pitfalls and constraints

- 先修已知安全风险，不要机械等待完整 M6，也不要直接开始 4k/9k 行大拆分。
- Web、Bot、manual scripts、recovery worker 可以保留不同控制面，但必须共享平台感知的 safety policy；任何真实投稿只能走一个 canonical gateway。
- 不要复制 `_wechat_submission_guard_reason` 到 Bot；它是微信专用且会形成第二份漂移逻辑。
- 不要把 uploader 接收、`UNDER_REVIEW`、本地截图或新 PID 当成公开发布。
- 微信最终点击与 SQLite 事务无法构成 exactly-once；未知结果必须 fail-closed 并人工对账。
- 不要长期保留新旧两套有外部副作用的实现；优先小提交和单一执行路径。
- 不要以 `<100` 行、运行 7 天或测试全绿替代行为覆盖与故障边界证据。
- 保护生产 checkout 的无关 dirty changes；不读写密钥；不运行裸 pytest；只用项目 `.venv` 和 isolated runner。

## Resume prompt

下周可直接发送：

> 请先读取当前项目根目录 `HANDOFF.md`，并完整复核生产 checkout `/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing` 的 `git status`、`main/origin/main`、流水线是否空闲，以及 `docs/refactor/video-processing/` 当前状态。继续 2026-09-12 的独立架构审计结论，采用 Hybrid Plan B；不要重做全库审计。首批只处理两个已确认安全问题：① Telegram PipelineAgent 的直接 uploader/任意状态/删除/重试旁路及退出码 6 误判；② `get_high_score_pending_videos()` 未排除 DISCOVERY，且 Golden fixture 固化错误契约。先补真实入口级隔离回归测试，再做最小实现，随后修订 M6/INV/RISK/Golden 文档。保护现有无关 dirty changes，不真实投稿、不发 Telegram、不改生产数据库、不重启运行态；每一步分别报告 diff、测试、提交、推送和运行采用状态。若当前源码或工作树与 HANDOFF 不一致，以现场证据为准并先说明差异。

## Updated

2026-09-12 18:47 CST
