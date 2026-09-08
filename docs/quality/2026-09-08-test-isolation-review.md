---
created_by: Unknown_Model_fast
created_at: 2026-09-08T11:50:03+08:00
---

# 视频测试隔离审查

基线：main `c50ea77b3eb077c621953b7551f22a68bd31488b`。独立工作区实现，生产 `src/` 零修改。审查方法为当前会话源码与差异逐项检查、真实进程边界探针和隔离环境 pytest；未委派独立审核代理。

## 发现与处理

| 级别 | 已验证触发条件 | 处理 |
|---|---|---|
| P1 | 原 conftest 在测试收集前导入 Settings；绝对 .env 路径不受 chdir 影响 | 在业务导入前拒绝裸 pytest；runner 清除继承配置并复制源码到临时根 |
| P1 | PipelineDB 默认构造即迁移源码根 output/pipeline.db；PipelineManager 和 web.app 导入/构造也触发初始化 | 保持业务行为，在 OS 沙盒内运行独立源码副本；默认 DB、输出及锁均位于该副本 |
| P2 | test_content_types 的两词正文只有一个词的时间轴，触发既有完整性检查 | 补齐真实样本时间轴；不放松生产校验 |
| P2 | serialization 和 keepalive 测试在单例构造后改 environ，清洁配置下失败 | 对实际消费的 settings 注入合成测试值；不依赖宿主 Gemini/Telegram 配置 |

新 runner 为 213 行、最长函数 40 行；conftest 54 行。没有向 4,309 行 FSM 或 9,568 行 DAL 追加测试分支。单向依赖保持；运行时只显式读取依赖路径，不导入业务模块获取配置。除测试基础设施的最小进程环境外，没有新增业务环境变量。

## 验证证据

- 最终影子运行 `/private/tmp/video-pytest-zifym9gc/`：**1495 passed, 8 warnings, 30 subtests passed in 31.65s**（准确计时以 pytest.log/JUnit 为准）；进程最终退出 0。8 个 warning 均为依赖弃用提示，没有线程异常或隐藏失败。
- 上述范围为 `tests/unit --ignore=tests/unit/test_dashboard_interactions.py`，没有跳过；子测试没有重复算入 1495 项。
- 新隔离契约覆盖真实默认构造、无宿主凭据、外部读写、符号链接、子进程继承、网络、收集前拒绝、源码快照过滤和超时回收。
- 每次 pytest 前都有实际边界拒绝探针，包括外部进程 signal 0 和 Data 卷路径别名。系统读权限收窄到具体依赖目录；旧宽目录策略的 canary 别名探针也被拒绝，未把它误报为已复现绕过漏洞。
- 全量收集 `/private/tmp/video-pytest-gup3h4ap/`：1521 项成功收集，未声称全部执行通过。
- 先前失败日志保留：`video-pytest-kry78sqy`（不完整时间轴与浏览器环境）、`video-pytest-t75519_y`（两项配置污染），提供修复前反例。

## 未覆盖与上线边界

在上述修改范围内未发现阻断问题。浏览器交互测试仍因 Chromium 安装资源不在严格沙盒读取允许清单而未验收；媒体集成测试未执行。测试目录的运行隔离不等于每个测试默认库独立、跨平台沙盒、CPU/内存配额或所有新会话后代回收。

本次只上线开发测试入口、三个测试样本修复及文档；不重启服务、不改生产 DB/FSM、不运行发布或模型任务。合入前须确认 main 干净、HEAD 与基线一致、流水线空闲。合入后从正式主干重新运行同一隔离入口，并回读版本、退出码与服务 PID。部署后结果记录在 OptionSense 本次质量证据目录，不把此处的影子通过数描述为部署后结果。

## Version History
| Version | Date | Author | Description |
|---|---|---|---|
| 1.0 | 2026-09-08 | Unknown_Model_fast | 记录修复、逐项审查、影子测试和剩余验收边界 |
