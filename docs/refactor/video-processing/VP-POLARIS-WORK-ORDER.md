---
work_order_id: VP-POLARIS
codename: 北辰
status: PLANNED_NOT_STARTED
created_at: 2026-09-12
last_updated_at: 2026-09-12
---

# VP-POLARIS「北辰」重构工程总工单

## 1. 工单目标

在不改变现有外部发布结果、不接触生产数据库的前提下，先封闭已经由源码证据确认的控制面旁路和自动候选漏洞，再建立足以支撑渐进拆分的入口级回归证据。总体路线采用 **Hybrid Plan B：Containment → Contract/Harness → Incremental Extraction**。

本工单是本轮重构的入口与首批执行清单。若它与同目录早期候选工单或 Gate 状态冲突，以本工单、根目录 `HANDOFF.md` 和开工时的现场证据为准；冲突必须在实施前说明并同步修订治理文档。

## 2. 启动口令与授权边界

- 推荐口令：`继续北辰重构`
- 等价口令：`启动 VP-POLARIS`
- 口令含义：读取根目录 `HANDOFF.md` 和本工单，进入 `POLARIS-000` 现场复核，然后在本工单范围内继续源码、测试和治理文档工作。
- 口令不授权：真实投稿、发送 Telegram、修改生产数据库、重启服务、操作创作者平台、清理无关 dirty changes，或扩展到首批工单之外。
- 当前状态：**PLANNED / NOT STARTED**。最早下周由用户明确说出口令后启动，不设置自动任务。

## 3. 首批工单队列

| 编号 | 内容 | 状态 | 前置条件 | 完成证据 |
| --- | --- | --- | --- | --- |
| `POLARIS-000` | 生产 checkout、Git、运行空闲和文档漂移复核 | READY | 用户发出启动口令 | 记录 `git status`、`main/origin/main`、流水线/浏览器任务状态和文档差异 |
| `POLARIS-101` | 补真实入口级隔离回归测试 | BLOCKED | `POLARIS-000` | 覆盖 Bot 退出码 6、已有账本 mutation、DISCOVERY 候选排除、promotion 后纳入 |
| `POLARIS-102` | 封闭 Telegram PipelineAgent 直接 uploader、任意状态、删除与重试旁路 | BLOCKED | `POLARIS-101` 红灯证据 | Bot 写操作只经 canonical application service；已受理/有账本对象 fail-closed |
| `POLARIS-103` | 在中心 DAL 候选咽喉排除 `source='DISCOVERY'`，并修正错误 Golden 契约 | BLOCKED | `POLARIS-101` 红灯证据 | 高分 DISCOVERY 不进入自动候选；原子 promotion 为 MANUAL 后可进入 |
| `POLARIS-104` | 修订 M6、INV、RISK、Golden 和既有工单语义 | BLOCKED | `POLARIS-102/103` | M6 不再虚称完整回放通过；平台语义和风险边界一致 |
| `POLARIS-105` | 隔离验证、目标提交与推送 | BLOCKED | `POLARIS-104` | 目标测试及完整非浏览器单测通过；仅目标文件提交并推送 `main` |

以上工单按顺序推进。`POLARIS-102` 与 `POLARIS-103` 可以分别形成小提交，但不得在缺少各自入口级失败测试时先改生产逻辑。

## 4. 验收标准

1. Telegram Bot 不再拥有可绕过统一安全策略的直接发布或任意状态 mutation 路径；微信 uploader 的“已受理待审核”退出码 6 不得被写成普通失败并触发自动重试语义。
2. `get_high_score_pending_videos()` 从中心候选层排除 DISCOVERY；只有显式、原子 promotion 后的 MANUAL 记录可进入后续处理。
3. `GOLDEN-WF-01` 不再把高分 DISCOVERY 自动入队当作正确契约；Golden Replay 的真实覆盖边界在文档中如实标注。
4. 使用项目 `.venv` 与 isolated runner；先通过目标测试，再通过完整非浏览器单元套件。除非另获明确授权，不运行会触碰真实平台的测试或命令。
5. 分别报告文件变更、测试、提交、推送、运行采用与外部平台状态；未验证层级保持 UNKNOWN/NOT PERFORMED。
6. 不夹带、不覆盖生产 checkout 中已有无关改动。

## 5. 明确非目标

- 本批次不直接拆分约 9.7k 行 `PipelineDB` 或约 4.4k 行 `PipelineManager`。
- 本批次不迁移微信、抖音、快手真实投稿执行层。
- 不用 feature flag 恢复已知不安全的 Bot 透传路径。
- 不把本地文件、测试通过、Git push、进程启动、平台受理或公开可见混称为“已上线”。

## 6. 已知证据入口

- `src/bot/pipeline_agent.py:151-170,178-206,637-752`
- `src/bot/telegram_bot.py:1562-1572`
- `src/video_processing/db/database.py:3262-3359,4105-4158`
- `src/video_processing/pipeline_manager.py:1465-1535,4106-4230`
- `src/web/app.py:610-644,842-856,2128-2174`
- `scripts/wechat_uploader.py:2569-2618`
- `tests/fixtures/golden_replay/scenarios/GOLDEN-WF-01/`

行号是 2026-09-12 快照，开工时应以当前源码重新定位。

## 7. 后续阶段

首批安全修复验收后，才评估纯 Runner/context/checkpoint 提取、`PipelineDB` 外部 Facade 下的内部领域拆分，以及 WC/DY/KS publication 的分平台迁移；这些工作必须另建或解锁工单，不因“继续北辰重构”自动获得授权。

## 8. 下次最短提示词

> 继续北辰重构。按 `VP-POLARIS` 工单从第一个未完成项开始；先复核现场，再实施，不做任何真实外部操作。
