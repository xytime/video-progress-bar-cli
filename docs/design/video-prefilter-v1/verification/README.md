# 视频预筛选 v1 开发验证

日期：2026-10-21；执行者 Codex（具体模型版本未知）。

实现已提交在 `codex/video-prefilter-v1`，基于最新已提交主干 `48d4d4d`。主工作区存在大量未提交改动，并与本次 DESIGN.md、UX-CONTRACT.md、导航文件重叠；未覆盖主工作区，未合并主干或重启线上服务。测试与运行采用分开记录。

- 新增 `/video-prefilter`，独立规则保存、手动官方检索、分类/排序/分页、跨规则收藏/排除/撤销与历史快照。
- 使用现有官方传输适配、来源审查、本机会话/Origin/CSRF、维护准入、搜索文件锁及预算。未引入 yt-dlp 搜索；未提高配额或开启现有搜索开关。
- `PREFILTER_ONLY` 和独立表隔离；不写 `processed_videos`、`topic_candidates`、`topic_hits`，没有生产准入或发布调用。既有自动关键词命中行为保留。

## 验证结果

所有测试通过 `scripts/run_isolated_tests.py` 运行；临时数据库、内存官方响应与独立 Chromium，没有真实平台检索或发布。

| 范围 | 结果 | 证据 |
|---|---|---|
| 新增及关键词/试运行/额度/运行时保护后端回归 | 285 通过 | backend-receipt.json |
| 最终中断计数修正后，预筛选/边缘/运行故障复测 | 55 通过 | final-boundaries-receipt.json |
| 新预筛选浏览器全流程、空态/部分/请求失败、主题对比、手机与默认配置保存 | 10 通过 | prefilter-browser-receipt.json |
| 完整共享页面浏览器回归 | 137 通过、11 失败 | browser-regression-receipt.json |
| 不含本次改动的主干商品页对照 | 21 通过、相同 11 失败 | main-product-baseline-receipt.json、baseline-comparison.json |
| 前端静态 strict 审计 | 0 错误、0 警告 | ui-audit.json |
| DESIGN.md lint | 0 错误、0 警告 | 已声明运行时 token 来源；5项 info 为有意省略 |

11 项既有失败均在商品挂载测试，涉及主干“英语世界唯一快捷英语商品”约束与旧测试流程不兼容。对照使用 `git archive main` 的临时副本，再执行同一隔离测试器，未读取/改变线上配置；失败用例集合完全相同。本次未修改这些约束来绕过测试。

最终停止边界：若详情返回后门禁关闭，禁止写入候选，作业标中断，尚未落库的分类计入“尚未分类”。不会展示为成功零结果。

## 页面证据和限制

`desktop.png`、`mobile-dark.png`、`mobile-light.png`、`mobile-contrast.png` 为真实页面配合隔离模拟数据的截图；标题、统计、额度和时间不代表实际 YouTube 检索结果。源资料保留30天、规则与时间窗口冻结、缺失统计不按零处理。

目前证据证明文件实现、隔离测试与浏览器操作；尚未完成主干整合、线上采用及真实官方 API 回读。采用前应保留主工作区既有改动，核对运行来源和当前门禁，不因新功能自行打开 `SEARCH_CLOSED` 或自动生产/发布开关。
