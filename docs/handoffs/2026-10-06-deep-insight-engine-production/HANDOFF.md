# Deep Insight Engine 工程验收

作者：Codex。日期：2026-10-06（Asia/Shanghai）。实现基线：806e9fa。

工单已完成：默认关闭配置、严格 InsightScript、Pillow 卡片、TTSEngine 解说、
FFmpeg 高光/浮窗/三段缝合、来源字幕策划、受跟踪生产编排、安全回退。
不改动原双语字幕处理器，不覆盖基础成片，保留切片主键。

回执使用独立 `{prefix}_insight.receipt.json`，不会覆盖 `{prefix}_insight.json` 脚本。
自动策划缓存绑定源片、字幕和脚本；增强缓存绑定源片、脚本、音色和输出。
新增卡片及口播正文进入统一审查，包括后续独立提交和多平台共享选片入口。

## 验收证据

- [pytest.log](pytest.log)：139 passed，2 个既有 FastAPI on_event 弃用 warning。
- [receipt.json](receipt.json)：标准隔离套件退出0，源码快照清单与沙盒哈希。
- [boundary-probe.log](boundary-probe.log)：正式路径读写、网络、信号和子进程越界拒绝探针。
- 新增洞察测试22项；相关回归覆盖文案、互动缓存、独立发布、提交预检、审查和 TTS。
- 真实 Pillow/FFmpeg 合成验证1080×1920、30fps、44.1kHz双声道、时长和音画起止偏差。
- 原始成片哈希不变；脚本与回执独立；音色/脚本变化使增强缓存失效。
- 默认关闭、TTS/卡片/编码失败、高光越界、供应商失败均回退；新增正文审查命中返回阻断。

## 使用与边界

详见 [生产接入说明](../../deep-insight-engine.md)。开关仍为默认 false。
没有启用生产配置、重启服务、触发队列、上传或提交视频。
联网 Edge TTS / Gemini / AGY 尚未实测，真实合成测试使用离线音轨替身。
没有真实题材增强成片的人审或微信平台回读，不能据此声称平台认可或限流解除。
现有未提交研究文档、experiments 和 topic_clues 等资产不属于此工单提交。
