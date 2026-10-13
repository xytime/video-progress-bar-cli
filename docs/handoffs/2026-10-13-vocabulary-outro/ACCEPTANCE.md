# 字幕生词片尾接入验收

记录：Codex，2026-10-13。范围：已确认 v4 排版接入自动加工；本次不上传、不发布，文章开关保持 false。

## 行为

- 在字幕烧录、审查与互动层完成后，通过受 PID 跟踪的子进程追加独立 `_vocab.mp4`；不修改源片、FSM、发布授权或数据库架构。
- 从本条规范 ASS 的 GlossaryCard 提取去重词条，并核对同时间正文英文及中文释义。例句及时间戳来自该字幕。同身份/词义/时间的 sidecar 只补充音标、词性；其余使用离线词典。
- 沿用六维时空号 logo/slogan、分层排版、“第 N 页 / 共 N 页”、“单击暂停 / 可截屏复习”和“双击收藏 / 随时回看”。每页三词、3 秒，最后 0.25 秒局部翻页，品牌与操作提示稳定。
- 输入视频、字幕、可选元数据、标题、logo 和版式版本绑定缓存，并核验输出哈希。无有效词条保留基础片；渲染失败不提交新回执。重复调用复用完整结果，不重复追加；清理保留绑定 ASS。
- 只有有效回执对应的成片才进入原有选片链。历史无片尾任务保持基础选片行为，不自动重试历史发布。

## 验收证据

隔离测试：106 passed，包含新增 12 项针对性测试，以及 interaction overlay、ready publication dispatch、rendered cache、标题一致性、insight、speech opening 回归。
证据：`/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/video-pytest-w_fobfi_`。

真实验证使用 `scripts/render_vocabulary_outro.py`，读取原有 `eW5Oi91m4SY_vertical.mp4` 和同 ID ASS，不运行发布入口。
- 17 个去重词条，6 页，片尾 18 秒，成片 160.170998 秒。
- 全片 FFmpeg 解码通过；重复运行输出哈希和 mtime 不变；源视频哈希不变。
- 成片 SHA-256：`8e087f11a69b1cb7bd260238cf9e28bca4e59566b24247516a2c2737bd6528b1`。
- 成片、逐页 PNG、字幕绑定回执及 verification.json：`/Volumes/EXT2T/AppDataOffload/ryusei/Deliverables/vocabulary-pipeline-verification-20261013/`。

## 运行采用与回退

此记录的测试和渲染证据不替代生产采用回执。生产目录有无关未提交开发工作，采用须保留并通过整合清单与维护门禁。
回退本功能时，在维护窗口精确回退本次新增模块/CLI及 pipeline_manager 接线，保留源片、派生 MP4、回执与账本，不回滚数据库，不触发重发。恢复原选片方法后仍使用原基础成片。
