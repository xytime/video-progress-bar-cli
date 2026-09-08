---
created_by: Unknown_Model_fast
created_at: 2026-09-08T12:09:00+08:00
---

# 浏览器测试隔离实施计划

目标：在实际 Chromium 中验收 dashboard 交互，同时维持正式配置、输出、网络和外部信号拒绝。修改测试设施，并修复验收确认的窄屏样式缺陷；不启动正式发布或服务。

调查后范围补充：窄屏真实测试复现批量管理复选框不可见。`index.html` 的 `.activity-table td.cb-cell` 隐藏规则比 `.in-edit-mode .cb-cell` 显示规则优先；仅修正后者选择器，让已存在的移动端编辑行为生效。该大模板不增加业务逻辑、不做无关重排；受影响范围是窄屏编辑模式的 checkbox 可见性，退出编辑仍必须隐藏并清空。

依赖：`run_isolated_tests → test_browser_runtime → stdlib/已安装 Playwright 元数据`；`dashboard tests → HTML snapshot/Playwright`。业务模块不依赖测试模块。

三道闸门：不涉及受保护业务、数据库迁移、配置密钥或线上状态；副作用集中在测试入口的一次性目录；runner 当前 213 行，浏览器依赖准备单独模块，目标每文件小于 300 行。现有 dashboard 测试文件不扩展业务逻辑。

受影响逻辑：runner 新增显式 `--browser`；复制并散列当前已安装 headless shell，仅为此模式允许 Chromium rendezvous 名称；marker/receipt 携带依赖快照；浏览器夹具明确依赖缺失失败，使用精确快照路径；增加边界与截图验收，维护使用文档。

顺序：先完成启动探针报告；在独立 worktree 实现；运行浏览器行为与真实隔离探针；检查截图、控制台与移动视口；审查差异及非浏览器回归；流水线空闲时合入并 push；在主干再跑测试、回读健康和远端 SHA，归档收据后移除本次 worktree。

权限边界：保留 network/read/write/signal 拒绝。Mach 例外仅 Chromium rendezvous 名称，按官方协议 PID 校验；不声称这是恶意代码容器或完全隔绝所有 Chromium IPC 的证明。不开放系统通知、钥匙串、应用控制服务。浏览器核心进程可能记录系统服务被拒的日志，页面 JS 错误仍须为零。

停止条件：需要真实生产数据/密钥、访问线上业务接口、宽泛放开 Mach 或网络、触发媒体生产任务时停止该路径，保留失败证据。浏览器缺失直接失败，不自动下载安装；默认非浏览器入口权限保持。

验收：现有 browser 行为全部真实执行；浏览器未路由请求被 OS 拒绝、canary file URL 无法读取、父/子进程原边界探针仍通过；截图人工查看；shadow 与 main 测试最终退出码和统计明确，跳过不算通过。

| Version | Date | Author | Description |
|---|---|---|---|
| 1.0 | 2026-09-08 | Unknown_Model_fast | 浏览器依赖快照、最小 IPC 例外、影子开发和双阶段验收计划 |
| 1.1 | 2026-09-08 | Unknown_Model_fast | 纳入真实验收发现的窄屏复选框 CSS 优先级缺陷，限定为原有规则修正 |
